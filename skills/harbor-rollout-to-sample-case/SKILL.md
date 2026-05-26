---
name: harbor-rollout-to-sample-case
description: Postprocess a Harbor rollout directory (jobs/{rollout_time}) into a portable sample case — rewrites each task's `trial_uri` to `file:///app/jobs/...` so it resolves inside the Harbor container, then writes a `README.md` at the rollout root summarizing the rollout config, dataset-level reward average, and per-task reward + unit-task failure counts. Trigger this skill whenever the user asks to package / postprocess / sample-case-ify / share / "write a README for" a Harbor rollout, mentions rewriting `trial_uri` or "changing the prefix to /app", or asks to summarize a `jobs/<timestamp>` directory's results, even if they don't say "skill" or "postprocess" explicitly.
---

# Harbor rollout → sample case

This skill turns a finished Harbor rollout directory (`jobs/<rollout_time>/`) into a self-describing, portable sample case. Two things happen in one pass:

1. **Path portability.** Each `task_*/result.json` carries a `trial_uri` like `file:///Users/<dev>/.../custom_prd_bench/jobs/<timestamp>/task_…`. That absolute local path doesn't resolve inside the Harbor container, where the project root is mounted at `/app`. We rewrite the prefix to `file:///app/jobs/<timestamp>/task_…` so the URI stays meaningful when the directory is later mounted, shipped, or shared.
2. **Secret redaction.** Any `config.json` string value whose key contains `TOKEN` (recursive, case-sensitive) is rewritten to `"***"` so credentials don't leak when the rollout directory is shared.
3. **Human-readable summary.** A top-level `README.md` is written into the rollout directory capturing the rollout config, the dataset-level reward average, and a per-task table (reward + unit-task failures + agent step count).

If the user asks for only one of the two operations, still do both — they're cheap and together are what make the directory portable. The summary is what makes the directory readable without opening any JSON.

## How to run

Use the bundled script — don't re-implement the rewrite or the README rendering inline. Both operations are deterministic, and reinventing them per invocation is the kind of thing that drifts.

```bash
python3 <SKILL_DIR>/scripts/process_rollout.py <path-to-jobs/{rollout_time}>
```

The path can be absolute or relative. The script:
- iterates every subdirectory containing a `result.json` and rewrites the `trial_uri` field in place (idempotent — re-running is safe),
- redacts any `*TOKEN*`-keyed string values in `config.json` to `"***"` (recursive, idempotent),
- writes `README.md` at the rollout-directory root, overwriting any existing one.

After it runs, give the user a one-line summary: number of `result.json` files touched and the path to the new README. Also surface: any redacted token keys, any tasks that fell back to `agent/claude-code.txt` for the step count (info, not a problem), and any tasks missing `verifier/results.json` or *both* trajectory sources (those rows show `N/A` / `—`).

## What goes in the README

The script renders these sections, in this order (kept stable so successive runs produce diff-friendly output):

```
# Rollout `<job_name>`

## Config
  Key rollout settings — agent name + model, dataset(s) + task filter,
  n_attempts, n_concurrent_trials, environment type, timeout multipliers
  (only listed when non-default).

## Run summary
  Started / finished / duration, completed/errored/cancelled trial counts,
  total cost, token usage.

## Dataset reward (avg)
  One row per `stats.evals.<combo>` key from result.json: trials, errors,
  reward mean.

## Per-task results
  One row per task subdirectory: trial name, reward, unit-task failures
  (`failed + errors` from `verifier/results.json`), total unit tasks,
  agent step count (`len(steps)` from `agent/trajectory.json` — counts every
  trajectory event: user messages, agent text/reasoning, agent tool-call
  steps; falls back to reconstructing the same count from
  `agent/claude-code.txt` when the ATIF file is absent),
  status (completed / errored), duration.
```

## Why these specific choices

- **`/app` prefix.** Harbor's container mounts the project root at `/app`. URIs that hardcode a developer's local absolute path silently rot the moment the directory leaves that machine. Rewriting once, at the postprocess boundary, is how a rollout becomes shareable.
- **Failure count from `verifier/results.json`, not the task `result.json`.** The task-level `result.json` only carries the aggregate `reward` (typically 0.0 or 1.0). The detailed unit-test counts (`failed`, `errors`, `total`) live next to it in `verifier/results.json`. Surfacing those gives a much more useful at-a-glance picture than a binary pass/fail.
- **Dataset reward avg from `stats.evals.<combo>.metrics[0].mean`.** That's what the Harbor runner already computed. Mirroring it (instead of recomputing from per-task rewards) keeps this README consistent with other Harbor tooling reading the same field.

## Edge cases worth knowing

- **Missing verifier data.** If a trial errored before tests ran, `verifier/results.json` won't exist. The failures/total columns show `N/A` and the status column reflects the error.
- **Missing trajectory data.** If `agent/trajectory.json` is absent, the script falls back to `agent/claude-code.txt` (Claude Code's raw JSONL event log) and reconstructs the step count as `1 + assistant_lines + non_tool_result_user_lines` — the `+1` accounts for the initial task prompt, which Claude Code receives via CLI args and does not echo into the event stream. If both files are missing, the steps column shows `—`. The fallback only works for Claude Code; other agents would need their own fallback logic.
- **Config token redaction.** Any string value whose key contains `TOKEN` (case-sensitive, recursive over dicts and lists) is rewritten to `"***"`. Re-running is a no-op once values are `***`. If a future Harbor version stores credentials under differently-named keys (e.g. `*SECRET*`, `*KEY*`), extend `_redact_tokens` in `scripts/process_rollout.py`.
- **Multiple dataset combos.** `stats.evals` can hold several keys (one per agent × model × dataset). The Dataset reward table lists each on its own row.
- **Re-running is safe.** The `trial_uri` rewrite is idempotent (rewriting an already-`/app` URI is a no-op); the README is regenerated by overwrite. Re-running after a partial rollout finishes adds the newly-completed tasks.
- **Only `trial_uri` is rewritten.** That's the only field observed to carry the developer's absolute path. If a future Harbor version adds more such fields, extend the rewrite loop in `scripts/process_rollout.py` rather than patching JSON by hand at the call site.
