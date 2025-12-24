#!/usr/bin/env python3
"""
Chain multiple Sora-2 segments with DIFFERENT prompts for each scene.
Perfect for storytelling where each segment has a unique action, while
maintaining visual continuity through last-frame chaining and crossfades.
"""

import argparse
import os
import subprocess
import sys
from typing import List, Optional

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def run_command(cmd, description):
    """Run a shell command and handle errors."""
    print(f"\n🔧 {description}...")

    encoding = 'utf-8' if sys.platform == "win32" else None
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors='replace'
    )

    if result.returncode != 0:
        print(f"❌ Error: {description} failed")
        print(result.stderr)
        sys.exit(1)

    return result.stdout


def get_video_duration(path: str) -> float:
    """Return the duration of a video in seconds using ffprobe."""
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        print(f"❌ Error: Could not read duration for {path}")
        sys.exit(1)
    try:
        return float(probe.stdout.strip())
    except ValueError:
        print(f"❌ Error: Invalid duration returned for {path}: {probe.stdout}")
        sys.exit(1)


def get_video_fps(path: str) -> Optional[float]:
    """Return the average FPS for a video or None if unavailable."""
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=avg_frame_rate',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        return None
    rate = probe.stdout.strip()
    if '/' in rate:
        num, den = rate.split('/')
        try:
            num = float(num)
            den = float(den)
            if den != 0:
                return num / den
        except ValueError:
            return None
    else:
        try:
            return float(rate)
        except ValueError:
            return None
    return None


def pad_segment_with_frame(segment_path: str, frame_path: str,
                           pad_seconds: float, fps: Optional[float]) -> None:
    """Prepend a short still section from the previous segment's last frame."""
    if pad_seconds <= 0:
        return

    if not os.path.exists(frame_path):
        print(f"⚠️ Warning: pad frame missing ({frame_path}); skipping padding.")
        return

    seg_duration = get_video_duration(segment_path)
    if pad_seconds >= seg_duration:
        pad_seconds = max(0, seg_duration - 0.1)
        print(f"⚠️ Pad trimmed to {pad_seconds:.2f}s to fit segment duration")
    if pad_seconds <= 0:
        return

    fps_value = fps if fps else 30
    padded_path = segment_path.replace('.mp4', '_padded.mp4')

    filter_complex = (
        f"[0:v]fps={fps_value},format=yuv420p,setsar=1[vpad];"
        f"[1:v]setpts=PTS-STARTPTS[vseg];"
        f"[1:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[aseg];"
        f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[asilence];"
        f"[vpad][vseg]concat=n=2:v=1:a=0[vout];"
        f"[asilence][aseg]concat=n=2:v=0:a=1[aout]"
    )

    cmd = (
        f'ffmpeg -y -loop 1 -t {pad_seconds} -i "{frame_path}" '
        f'-i "{segment_path}" -f lavfi -t {pad_seconds} '
        f'-i anullsrc=r=48000:cl=stereo '
        f'-filter_complex "{filter_complex}" '
        f'-map "[vout]" -map "[aout]" -c:v libx264 -crf 18 -preset fast '
        f'-c:a aac -shortest "{padded_path}"'
    )
    run_command(cmd, f"Padding {segment_path} with previous last frame ({pad_seconds}s)")
    os.replace(padded_path, segment_path)


def chain_story_segments(prompts: List[str], output: str, segment_duration: int = 12,
                         crossfade_duration: float = 1.0, pad_seconds: Optional[float] = None,
                         size: Optional[str] = None):
    """Create a story video by chaining segments with different prompts for each scene."""

    num_segments = len(prompts)
    pad_value = crossfade_duration if pad_seconds is None else pad_seconds

    print(f"🎬 Creating story video with {num_segments} scenes")
    print(f"Output: {output}")
    print(f"Crossfade: {crossfade_duration}s")
    print(f"Start pad: {pad_value}s of previous last frame for continuity")
    print(f"🔗 Using image-to-video chaining for smooth scene transitions\n")

    for i, prompt in enumerate(prompts):
        print(f"  Scene {i+1}: {prompt[:60]}{'...' if len(prompt) > 60 else ''}")
    print()

    segment_files = []
    last_frame = None
    segment_durations = []

    # Continuity hint for subsequent segments
    continuity_hint = (
        "Continue with the same characters, style, lighting, and visual consistency. "
        "Maintain the same camera style and color grading. Smooth motion continuation."
    )

    for i, scene_prompt in enumerate(prompts):
        segment_num = i + 1
        segment_file = f"segment_{segment_num}.mp4"
        frame_file = f"frame_{segment_num}.jpg"

        print(f"\n{'='*60}")
        print(f"🎬 Scene {segment_num}/{num_segments}")
        print(f"📝 Prompt: {scene_prompt}")
        print(f"{'='*60}")

        size_flag = f" -r {size}" if size else ""

        # Generate segment
        if i == 0:
            # First segment: text-to-video
            cmd = f'python video_generator.py "{scene_prompt}" -s {segment_duration}{size_flag} -o {segment_file}'
        else:
            # Subsequent segments: image-to-video using last frame + scene prompt + continuity hint
            full_prompt = f"{scene_prompt}. {continuity_hint}"
            cmd = f'python video_generator.py "{full_prompt}" -s {segment_duration}{size_flag} -o {segment_file} -i {last_frame}'

        run_command(cmd, f"Generating scene {segment_num}")

        # Prepend a short still frame for smooth crossfade
        if i > 0 and pad_value > 0:
            segment_fps = get_video_fps(segment_file)
            pad_segment_with_frame(segment_file, last_frame, pad_value, segment_fps)

        segment_files.append(segment_file)

        # Extract last frame for next segment (except for the last segment)
        if i < num_segments - 1:
            extract_cmd = f'python extract_last_frame.py {segment_file} -o {frame_file}'
            run_command(extract_cmd, f"Extracting last frame from scene {segment_num}")
            last_frame = frame_file

        # Track actual duration for accurate crossfade offsets
        duration = get_video_duration(segment_file)
        segment_durations.append(duration)
        print(f"   Scene duration after padding: {duration:.2f}s")

    # Combine all segments
    print(f"\n{'='*60}")
    print("🎬 Combining scenes into final story...")
    print(f"{'='*60}\n")

    if len(segment_files) == 1:
        import shutil
        shutil.copy(segment_files[0], output)
        print(f"Single scene - copied to {output}")
    else:
        # Multiple segments - use crossfade for smooth transitions
        video_filter_parts = []
        audio_filter_parts = []

        min_duration = min(segment_durations)
        if crossfade_duration >= min_duration:
            new_cf = max(0.1, min_duration - 0.1)
            print(f"⚠️ Crossfade trimmed from {crossfade_duration}s to {new_cf}s to fit segment length")
            crossfade_duration = new_cf

        cumulative_duration = segment_durations[0]
        for i in range(len(segment_files) - 1):
            if i == 0:
                v_in_label = f"[0:v][{i+1}:v]"
                a_in_label = f"[0:a][{i+1}:a]"
            else:
                v_in_label = f"[v{i-1}{i}][{i+1}:v]"
                a_in_label = f"[a{i-1}{i}][{i+1}:a]"

            v_out_label = f"[v{i}{i+1}]" if i < len(segment_files) - 2 else "[vout]"
            a_out_label = f"[a{i}{i+1}]" if i < len(segment_files) - 2 else "[aout]"

            offset = cumulative_duration - crossfade_duration

            video_filter_parts.append(
                f"{v_in_label}xfade=transition=fade:duration={crossfade_duration}:offset={offset:.3f}{v_out_label}"
            )
            audio_filter_parts.append(
                f"{a_in_label}acrossfade=d={crossfade_duration}:c1=tri:c2=tri{a_out_label}"
            )

            cumulative_duration = cumulative_duration + segment_durations[i + 1] - crossfade_duration

        filter_complex = ";".join(video_filter_parts + audio_filter_parts)
        inputs = " ".join([f'-i "{seg}"' for seg in segment_files])

        ffmpeg_cmd = (
            f'ffmpeg {inputs} -filter_complex "{filter_complex}" -map "[vout]" -map "[aout]" '
            f'-c:v libx264 -crf 18 -preset slow -c:a aac -b:a 192k "{output}" -y'
        )
        run_command(ffmpeg_cmd, "Combining scenes with smooth crossfade transitions")

    # Cleanup temporary files
    print("\n🧹 Cleaning up temporary files...")
    for seg in segment_files:
        if os.path.exists(seg):
            os.remove(seg)
            print(f"  Removed {seg}")

    for i in range(1, num_segments):
        frame_file = f"frame_{i}.jpg"
        if os.path.exists(frame_file):
            os.remove(frame_file)
            print(f"  Removed {frame_file}")

    total_duration = sum(segment_durations) - crossfade_duration * (num_segments - 1)
    print(f"\n✅ Complete! Story video saved as: {output}")
    print(f"   Total duration: ~{total_duration:.1f} seconds")
    print(f"   Scenes: {num_segments}")
    print(f"   Transitions: {crossfade_duration}s smooth crossfade between scenes")


def main():
    parser = argparse.ArgumentParser(
        description='Chain multiple Sora-2 video segments with DIFFERENT prompts for storytelling',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Three-scene bowling dog story with smooth transitions
  python story_chain.py \\
    "A cute little dog enters a colorful bowling alley, looking around excitedly, camera follows the dog" \\
    "The dog nudges a bowling ball with its nose, the camera zooms in on the action" \\
    "The bowling ball rolls down the lane knocking down all the pins, the dog celebrates joyfully" \\
    -o bowling_dog.mp4

  # Two-scene adventure
  python story_chain.py \\
    "A knight stands at the edge of a dark forest, torchlight flickering" \\
    "The knight ventures into the forest, shadows dancing around" \\
    -o knight_adventure.mp4

  # Custom settings
  python story_chain.py \\
    "Scene one" "Scene two" "Scene three" \\
    -o story.mp4 --crossfade 1.5 --segment-duration 8

Note: Each segment uses the last frame of the previous segment for visual continuity.
      Crossfades blend scenes smoothly like a continuous camera following the action.
        '''
    )

    parser.add_argument('prompts', nargs='+', 
                        help='Text descriptions for each scene (one prompt per segment)')
    parser.add_argument('-o', '--output', type=str, default='story_output.mp4',
                        help='Output filename (default: story_output.mp4)')
    parser.add_argument('-s', '--segment-duration', type=int, default=12, choices=[4, 8, 12],
                        help='Duration of each segment in seconds (default: 12)')
    parser.add_argument('-c', '--crossfade', type=float, default=1.0,
                        help='Crossfade duration in seconds between scenes (default: 1.0)')
    parser.add_argument('--pad-start', type=float, default=None,
                        help='Seconds of previous last frame to prepend (default: 60%% of crossfade)')
    parser.add_argument('--size', type=str, default=None,
                        help='Resolution for all segments (e.g., 1280x720)')

    args = parser.parse_args()

    if len(args.prompts) < 1:
        print("❌ Error: At least one prompt is required")
        sys.exit(1)

    if args.crossfade < 0 or args.crossfade > args.segment_duration:
        print("❌ Error: Crossfade duration must be between 0 and segment duration")
        sys.exit(1)

    # Check dependencies
    try:
        subprocess.run(['python', 'video_generator.py', '--help'],
                      capture_output=True, check=True)
    except Exception:
        print("❌ Error: video_generator.py not found or not working")
        sys.exit(1)

    try:
        subprocess.run(['python', 'extract_last_frame.py', '--help'],
                      capture_output=True, check=True)
    except Exception:
        print("❌ Error: extract_last_frame.py not found or not working")
        sys.exit(1)

    try:
        subprocess.run(['ffmpeg', '-version'],
                      capture_output=True, check=True)
    except Exception:
        print("❌ Error: ffmpeg not found")
        print("   Install ffmpeg: https://ffmpeg.org/download.html")
        sys.exit(1)

    # Default pad: short ramp-in to avoid long stills
    default_pad = min(args.crossfade * 0.6, 0.6)
    pad_value = args.pad_start if args.pad_start is not None else default_pad

    chain_story_segments(args.prompts, args.output, args.segment_duration,
                         args.crossfade, pad_value, args.size)


if __name__ == '__main__':
    main()
