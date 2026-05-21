---
name: trans-task-start-method-from-dockerfile-to-bash
description: >
  Migrate PRD-bench tasks from the legacy Dockerfile-based startup contract to
  the new `start.sh` contract defined in `INSTRUCTION_NEW_VERSION.md`. For each
  task under `tasks/<task_name>/`, this skill replaces
  `workspace/INSTRUCTION.md` with the new-version instruction file and
  generates `workspace/implementation/start.sh` by translating the existing
  `workspace/implementation/Dockerfile` into an equivalent shell script
  (dependency install + foreground server launch). Use this skill whenever the
  user wants to adapt tasks for Harbor single-container deployment + testing,
  asks to "switch to start.sh", "remove Dockerfile in favor of start.sh",
  "apply INSTRUCTION_NEW_VERSION", "migrate tasks to the new startup contract",
  or wants to bulk-convert one/many tasks from the Dockerfile flow to the
  bash-script flow. Also trigger on phrases like "harbor adaptation",
  "harbor 适配", "把 Dockerfile 换成 start.sh", "新版指令", "新版启动脚本".
---

# Trans-task: Dockerfile → start.sh Migration

You are migrating PRD-bench tasks from the **old startup contract** (each task ships a `Dockerfile` and the evaluator builds + runs a container) to the **new startup contract** (each task ships a `start.sh` and the evaluator runs it directly inside a single shared container — the Harbor flow).

The new contract lives in `INSTRUCTION_NEW_VERSION.md` at the repo root. Read it first if you haven't — it is the source of truth for what `start.sh` must do.

## Why this migration exists

Harbor (the new evaluation runner) hosts implementations as single-container deployments and exercises them with the test suite in the same container. Building a per-task Docker image is unnecessary overhead in that setup, so the contract collapses from "Dockerfile + CMD" down to "one shell script that installs deps and runs the server in the foreground". Keeping that intent in mind helps when you encounter a Dockerfile that does something unusual — translate the *behavior*, not the syntax.

## Inputs

- **Repo root** containing `INSTRUCTION_NEW_VERSION.md`. Default: the current working directory. Confirm with the user if ambiguous.
- **Target scope** — one of:
  - A single task path: `tasks/<task_name>/`
  - A glob/list of task paths
  - All tasks: every `tasks/task_*/` directory

If the user says "do this for every task" or names no specific task, assume all tasks under `tasks/`.

## What to produce, per task

For each task directory `tasks/<task_name>/`:

1. **Overwrite** `tasks/<task_name>/workspace/INSTRUCTION.md` with the exact contents of `INSTRUCTION_NEW_VERSION.md`. This is a straight copy — do not edit, paraphrase, or annotate.
2. **Create** `tasks/<task_name>/workspace/implementation/start.sh` by translating the existing `Dockerfile` into a shell script (rules below).
3. **`chmod +x`** the new `start.sh` so the evaluator can execute it directly.

**Do not delete the existing `Dockerfile`** unless the user explicitly asks. Leaving it in place is harmless (the new evaluator ignores it) and lets the user diff old vs new. Mention it in your end-of-turn summary so the user knows to make the call.

## Dockerfile → start.sh translation rules

The `start.sh` contract from `INSTRUCTION_NEW_VERSION.md`:

- Install all runtime dependencies.
- Bind to `0.0.0.0` on the `PORT` env var (default 10000) — usually the existing app already does this, so you don't need to inject port-handling code.
- Respond to HTTP within 60s of `bash start.sh` being invoked.
- Keep the server in the foreground — use `exec` for the final command so signals propagate and the script doesn't exit while the server runs.

Map Dockerfile directives like this:

| Dockerfile directive | start.sh equivalent |
|---|---|
| `FROM <image>` | **drop** — base image is the Harbor container, not per-task |
| `WORKDIR /app` | **drop** — evaluator runs `bash start.sh` from `./implementation/`, which already is the working dir |
| `COPY ... .` | **drop** — files are already in place |
| `ENV PORT=10000` | **drop** — the app reads `PORT` with a default; the evaluator sets it if needed |
| `EXPOSE <port>` | **drop** — no container being built |
| `RUN pip install --no-cache-dir -r requirements.txt` | `pip install -q -r requirements.txt` |
| `RUN pip install --no-cache-dir "flask>=3.0"` | `pip install -q -r requirements.txt` if `requirements.txt` exists (prefer it — covers transitive deps the Dockerfile happened to skip), else mirror the literal install line |
| `RUN apt-get update && apt-get install -y <pkgs>` | usually drop — Harbor image already has system deps. Keep only if the package is clearly project-specific and not in a typical base image. If kept, prefix with `sudo` only if the script is expected to run as non-root. Ask the user when unsure rather than guessing. |
| `CMD ["python", "app.py"]` | `exec python app.py` |
| `CMD ["node", "server.js"]` | `exec node server.js` |
| `CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]` | `exec gunicorn -b "0.0.0.0:${PORT:-10000}" app:app` (parameterize the port) |
| `ENTRYPOINT [...]` + `CMD [...]` | combine into the single foreground `exec ...` line |

### Template

For the overwhelmingly common Python/Flask case, the result is:

```bash
#!/bin/bash
set -e
pip install -q -r requirements.txt
exec python app.py
```

`set -e` is important — without it a failed `pip install` would silently fall through to `exec` and the evaluator would see a confusing crash later instead of a clean fail-fast.

For Node:

```bash
#!/bin/bash
set -e
npm install --silent
exec node server.js
```

Stay close to this shape. The contract is two lines of substance (install, exec). If your translation balloons past ~6–8 lines, you're probably preserving Dockerfile concerns that no longer apply — re-read the rules table above.

## How to execute the migration

Match the implementation strategy to scope:

### Single task

Read the Dockerfile, write `start.sh`, copy the instruction file, `chmod +x`. Use the dedicated tools (Read / Write / Bash). Verify by reading back the generated `start.sh`.

### Many tasks (10+)

Hand-editing 100+ files is wasteful and error-prone. Run a single Bash loop instead — but **before looping, sample a handful of Dockerfiles to confirm they share a template**. If they do (the common case in this repo — almost every task is Python/Flask with `pip install -r requirements.txt` + `python app.py`), one template covers them all and you can blast through with:

```bash
# Repo-root cwd. SRC = the new instruction file.
SRC="INSTRUCTION_NEW_VERSION.md"
for d in tasks/task_*/workspace; do
  cp "$SRC" "$d/INSTRUCTION.md"
  cat > "$d/implementation/start.sh" <<'EOF'
#!/bin/bash
set -e
pip install -q -r requirements.txt
exec python app.py
EOF
  chmod +x "$d/implementation/start.sh"
done
```

If the sample shows variation (different base languages, custom system deps, non-standard entry commands), **don't** force one template. Either:

- Branch in the loop based on what the Dockerfile contains (e.g., grep for `node` vs `python`), or
- Group tasks by template and run a short loop per group.

Either way, before going wide, verify pre-conditions across all targets in a single pass:

```bash
# Every implementation has the expected files?
for d in tasks/task_*/workspace/implementation; do
  [ -f "$d/requirements.txt" ] || echo "MISSING req: $d"
  [ -f "$d/app.py" ] || echo "MISSING app: $d"
done
```

A clean run means the template is safe. Outliers should be handled by hand after the loop.

### Verification after bulk runs

After a bulk run, do three quick checks:

1. **Counts match expectations** — `ls tasks/task_*/workspace/implementation/start.sh | wc -l` should equal the task count.
2. **Spot-check the first, last, and one middle output** — read them to confirm the content is what you intended (not, say, an empty file from a heredoc gone wrong).
3. **All scripts executable** — `find tasks -name start.sh -not -perm -u+x` should print nothing.

Report counts to the user. Don't paper over partial failures; if 5 tasks were skipped because they lacked a `Dockerfile`, name them.

## Edge cases worth thinking about

- **Task has no `Dockerfile`**: skip it and report. The skill's job is to translate an existing Dockerfile, not invent one.
- **Task has no `requirements.txt` but its Dockerfile installed packages inline**: prefer creating/preserving a `requirements.txt` over hardcoding `pip install foo==1.2` in `start.sh` — the script stays small and dep changes happen in the canonical place. If unwilling to touch source files beyond `start.sh`, mirror the literal install command and note it.
- **Dockerfile starts the server via a non-standard mechanism** (e.g., `supervisord`, multiple processes): the new contract assumes one foreground server. Flag this to the user instead of guessing at a translation.
- **Existing `start.sh` already present**: ask before overwriting. The user may have hand-tuned it.
- **Repo-root location**: the loop above uses relative paths from the repo root. If you're invoked from elsewhere, `cd` once or use absolute paths — don't sprinkle `cd` calls through the loop.

## End-of-turn summary

After running the migration, tell the user:

- How many `INSTRUCTION.md` files were replaced and how many `start.sh` files were created (with counts).
- Any tasks that were skipped, and why.
- The template you used (one or two lines is enough — they can verify by reading a sample).
- That existing `Dockerfile`s were left in place, with an offer to remove them in a follow-up if the user wants a clean Harbor-only tree.
