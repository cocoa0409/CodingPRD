#!/usr/bin/env python3
"""Postprocess a Harbor rollout directory (jobs/<rollout_time>/).

Two operations, both idempotent:

1. Rewrite the `trial_uri` field in every task_*/result.json so the local
   absolute prefix becomes `/app` — Harbor mounts the project root at `/app`
   inside its container, so this is the path that resolves once the rollout
   directory is shipped elsewhere.

2. Write `README.md` at the rollout-directory root summarizing the rollout
   config (from config.json), dataset-level reward avg (from result.json
   stats.evals), and a per-task table with reward + unit-task failure counts
   (from each task's verifier/results.json).

Usage:
    python process_rollout.py <path-to-jobs/{rollout_time}>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any


# --- trial_uri rewrite -------------------------------------------------------

# Match `file://` + any path + `/jobs/`, non-greedy so we strip the *first*
# `/jobs/` segment (which is where the rollout directory begins).
_PREFIX_RE = re.compile(r"^file://.+?/jobs/")


def rewrite_uri(value: str) -> str:
    """`file:///<anything>/jobs/X` -> `file:///app/jobs/X`. Idempotent."""
    return _PREFIX_RE.sub("file:///app/jobs/", value)


def rewrite_task_result(path: Path) -> bool:
    """Rewrite `trial_uri` in `path` in place. Returns True if the file changed."""
    original = path.read_text()
    data = json.loads(original)

    uri = data.get("trial_uri")
    if not isinstance(uri, str):
        return False
    new = rewrite_uri(uri)
    if new == uri:
        return False
    data["trial_uri"] = new
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


# --- config.json token redaction ---------------------------------------------

def _redact_tokens(obj: Any, redacted_keys: list[str], path: tuple[str, ...] = ()) -> bool:
    """Recursively replace str values under keys containing `TOKEN` with `***`.

    Returns True if any value was rewritten. `redacted_keys` is filled with the
    dotted paths of the keys that were redacted, for logging.
    """
    changed = False
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = path + (str(k),)
            if isinstance(v, str) and "TOKEN" in str(k) and v != "***":
                obj[k] = "***"
                redacted_keys.append(".".join(here))
                changed = True
            elif isinstance(v, (dict, list)):
                if _redact_tokens(v, redacted_keys, here):
                    changed = True
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                if _redact_tokens(v, redacted_keys, path + (f"[{i}]",)):
                    changed = True
    return changed


def redact_config_tokens(cfg_path: Path) -> list[str]:
    """Redact `*TOKEN*`-keyed string values in `config.json` in place. Idempotent.

    Returns the list of dotted key paths that were redacted (empty if no change).
    """
    data = json.loads(cfg_path.read_text())
    redacted: list[str] = []
    if _redact_tokens(data, redacted):
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return redacted


# --- formatting helpers ------------------------------------------------------

def _fmt_int(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _parse_ts(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(started: str | None, finished: str | None) -> float | None:
    a, b = _parse_ts(started), _parse_ts(finished)
    if a and b:
        return (b - a).total_seconds()
    return None


# --- README sections ---------------------------------------------------------

def _config_section(cfg: dict[str, Any]) -> list[str]:
    lines: list[str] = ["## Config", ""]
    lines.append(f"- **Job name**: `{cfg.get('job_name', '?')}`")

    for agent in (cfg.get("agents") or []):
        name = agent.get("name", "?")
        model = agent.get("model_name", "?")
        lines.append(f"- **Agent**: `{name}` (model: `{model}`)")

    for ds in (cfg.get("datasets") or []):
        bits = [f"path=`{ds.get('path')}`"]
        if ds.get("task_names"):
            bits.append(f"task_names={ds['task_names']}")
        if ds.get("exclude_task_names"):
            bits.append(f"exclude_task_names={ds['exclude_task_names']}")
        if ds.get("n_tasks"):
            bits.append(f"n_tasks={ds['n_tasks']}")
        lines.append(f"- **Dataset**: {', '.join(bits)}")

    lines.append(f"- **n_attempts**: {cfg.get('n_attempts')}")
    lines.append(f"- **n_concurrent_trials**: {cfg.get('n_concurrent_trials')}")

    env = cfg.get("environment") or {}
    if env.get("type"):
        env_bits = [env["type"]]
        if env.get("override_cpus"):
            env_bits.append(f"cpus={env['override_cpus']}")
        if env.get("override_memory_mb"):
            env_bits.append(f"mem_mb={env['override_memory_mb']}")
        if env.get("override_gpus"):
            env_bits.append(f"gpus={env['override_gpus']}")
        lines.append(f"- **Environment**: {', '.join(env_bits)}")

    # Only show timeout multipliers when non-default, to keep the section tight.
    for key in (
        "timeout_multiplier",
        "agent_timeout_multiplier",
        "verifier_timeout_multiplier",
        "agent_setup_timeout_multiplier",
        "environment_build_timeout_multiplier",
    ):
        val = cfg.get(key)
        if val not in (None, 1.0):
            lines.append(f"- **{key}**: {val}")

    return lines


def _run_summary_section(result: dict[str, Any]) -> list[str]:
    lines: list[str] = ["", "## Run summary", ""]
    lines.append(f"- **Started**: `{result.get('started_at')}`")
    lines.append(f"- **Finished**: `{result.get('finished_at')}`")
    dur = _duration_seconds(result.get("started_at"), result.get("finished_at"))
    lines.append(f"- **Duration**: {_fmt_duration(dur)}")
    lines.append(f"- **Total trials**: {result.get('n_total_trials')}")

    stats = result.get("stats") or {}
    for k in (
        "n_completed_trials",
        "n_errored_trials",
        "n_running_trials",
        "n_pending_trials",
        "n_cancelled_trials",
        "n_retries",
    ):
        if k in stats:
            lines.append(f"- **{k}**: {stats[k]}")

    if stats.get("cost_usd") is not None:
        lines.append(f"- **Cost (USD)**: ${stats['cost_usd']:.4f}")
    tok_in = stats.get("n_input_tokens")
    tok_out = stats.get("n_output_tokens")
    tok_cache = stats.get("n_cache_tokens")
    if any(v is not None for v in (tok_in, tok_out, tok_cache)):
        lines.append(
            "- **Tokens**: input "
            f"{_fmt_int(tok_in)} / output {_fmt_int(tok_out)} / cache {_fmt_int(tok_cache)}"
        )
    return lines


def _dataset_reward_section(result: dict[str, Any]) -> list[str]:
    lines: list[str] = ["", "## Dataset reward (avg)", ""]
    evals = ((result.get("stats") or {}).get("evals")) or {}
    if not evals:
        lines.append("_No dataset-level evals reported._")
        return lines

    lines.append("| Eval combo | Trials | Errors | Reward avg |")
    lines.append("|---|---|---|---|")
    for combo, e in evals.items():
        metrics = e.get("metrics") or []
        mean = metrics[0].get("mean") if (metrics and isinstance(metrics[0], dict)) else None
        mean_s = f"{mean:.4f}" if isinstance(mean, (int, float)) else "—"
        lines.append(
            f"| `{combo}` | {e.get('n_trials', '—')} | {e.get('n_errors', '—')} | {mean_s} |"
        )
    return lines


def _trajectory_step_count(task_dir: Path) -> int | None:
    """Return `len(steps)` from `agent/trajectory.json`, or None if missing/unreadable."""
    p = task_dir / "agent" / "trajectory.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return len(d.get("steps") or [])


def _claude_code_step_count(task_dir: Path) -> int | None:
    """Reconstruct an ATIF-equivalent step count from `agent/claude-code.txt`.

    `claude-code.txt` is the raw Claude Code event stream (JSONL). Mapping to
    ATIF `steps`:
      - every `type=="assistant"` line is one agent step,
      - every `type=="user"` line is a tool_result wrapper *unless* its content
        contains a non-tool_result block (then it's a real user message),
      - the initial user task prompt is delivered to Claude Code via CLI args
        and is NOT echoed into this file, so we add 1 for it.

    Returns None if the file is missing or has no parseable events.
    """
    p = task_dir / "agent" / "claude-code.txt"
    if not p.exists():
        return None

    n_assistant = 0
    n_real_user = 0
    parsed_any = False
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        t = o.get("type")
        if t == "assistant":
            n_assistant += 1
        elif t == "user":
            msg = o.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list) and content and all(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                continue
            n_real_user += 1

    if not parsed_any:
        return None
    return 1 + n_assistant + n_real_user


def _step_count(task_dir: Path) -> tuple[int | None, str | None]:
    """Return `(step_count, source)` where source is 'trajectory', 'claude-code', or None.

    Prefers `agent/trajectory.json` (ATIF schema, agent-agnostic) and falls back
    to parsing `agent/claude-code.txt` when the former is absent.
    """
    n = _trajectory_step_count(task_dir)
    if n is not None:
        return n, "trajectory"
    n = _claude_code_step_count(task_dir)
    if n is not None:
        return n, "claude-code"
    return None, None


def _per_task_section(
    rollout_dir: Path,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Returns (lines, missing_verifier_trials, missing_trajectory_trials, fallback_trajectory_trials)."""
    lines: list[str] = ["", "## Per-task results", ""]
    lines.append(
        "| Trial | Reward | Unit task failures | Total unit tasks | Steps | Status | Duration |"
    )
    lines.append("|---|---|---|---|---|---|---|")

    missing_verifier: list[str] = []
    missing_trajectory: list[str] = []
    fallback_trajectory: list[str] = []

    task_dirs = sorted(
        d for d in rollout_dir.iterdir()
        if d.is_dir() and (d / "result.json").exists()
    )
    for td in task_dirs:
        t = json.loads((td / "result.json").read_text())
        trial = t.get("trial_name") or td.name
        reward = (t.get("verifier_result") or {}).get("rewards", {}).get("reward")
        reward_s = f"{reward}" if reward is not None else "—"

        verifier_results = td / "verifier" / "results.json"
        if verifier_results.exists():
            v = json.loads(verifier_results.read_text())
            failed = int(v.get("failed", 0) or 0)
            errors = int(v.get("errors", 0) or 0)
            total = v.get("total")
            failures_s = f"{failed + errors} (failed={failed}, errors={errors})"
            total_s = str(total) if total is not None else "—"
        else:
            missing_verifier.append(trial)
            failures_s = "N/A"
            total_s = "N/A"

        step_count, src = _step_count(td)
        if step_count is None:
            missing_trajectory.append(trial)
            steps_s = "—"
        else:
            if src == "claude-code":
                fallback_trajectory.append(trial)
            steps_s = str(step_count)

        status = "errored" if t.get("exception_info") else "completed"
        dur = _duration_seconds(t.get("started_at"), t.get("finished_at"))
        lines.append(
            f"| `{trial}` | {reward_s} | {failures_s} | {total_s} | {steps_s} | {status} | {_fmt_duration(dur)} |"
        )
    return lines, missing_verifier, missing_trajectory, fallback_trajectory


def build_readme(
    rollout_dir: Path, cfg: dict, result: dict
) -> tuple[str, list[str], list[str], list[str]]:
    title = f"# Rollout `{cfg.get('job_name', rollout_dir.name)}`"
    parts: list[str] = [title, ""]
    parts += _config_section(cfg)
    parts += _run_summary_section(result)
    parts += _dataset_reward_section(result)
    per_task_lines, missing_verifier, missing_trajectory, fallback_trajectory = _per_task_section(rollout_dir)
    parts += per_task_lines
    parts.append("")
    return "\n".join(parts), missing_verifier, missing_trajectory, fallback_trajectory


# --- main --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rollout_dir", type=Path, help="Path to jobs/<rollout_time>/")
    args = ap.parse_args(argv)

    rollout = args.rollout_dir.resolve()
    if not rollout.is_dir():
        print(f"error: {rollout} is not a directory", file=sys.stderr)
        return 2

    cfg_path = rollout / "config.json"
    res_path = rollout / "result.json"
    if not cfg_path.exists() or not res_path.exists():
        print(
            f"error: {rollout} doesn't look like a rollout directory "
            "(missing config.json or result.json)",
            file=sys.stderr,
        )
        return 2

    rewritten: list[str] = []
    for task_dir in sorted(rollout.iterdir()):
        if not task_dir.is_dir():
            continue
        tr = task_dir / "result.json"
        if not tr.exists():
            continue
        if rewrite_task_result(tr):
            rewritten.append(task_dir.name)

    redacted_keys = redact_config_tokens(cfg_path)

    cfg = json.loads(cfg_path.read_text())
    result = json.loads(res_path.read_text())
    readme, missing_verifier, missing_trajectory, fallback_trajectory = build_readme(rollout, cfg, result)
    (rollout / "README.md").write_text(readme)

    print(f"rollout: {rollout}")
    print(f"trial_uri rewritten in {len(rewritten)} task result.json file(s)")
    for t in rewritten:
        print(f"  - {t}")
    if redacted_keys:
        print(f"redacted {len(redacted_keys)} TOKEN-key string value(s) in config.json:")
        for k in redacted_keys:
            print(f"  - {k}")
    if fallback_trajectory:
        print(f"info: {len(fallback_trajectory)} task(s) used claude-code.txt fallback for step count:")
        for t in fallback_trajectory:
            print(f"  - {t}")
    if missing_verifier:
        print(f"warning: {len(missing_verifier)} task(s) missing verifier/results.json (N/A in failures column):")
        for t in missing_verifier:
            print(f"  - {t}")
    if missing_trajectory:
        print(f"warning: {len(missing_trajectory)} task(s) missing both agent/trajectory.json and agent/claude-code.txt (— in steps column):")
        for t in missing_trajectory:
            print(f"  - {t}")
    print(f"wrote: {rollout / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
