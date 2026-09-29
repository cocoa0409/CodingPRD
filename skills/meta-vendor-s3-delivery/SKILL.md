---
name: meta-vendor-s3-delivery
description: >-
  Deliver/upload Harbor task datasets to a Meta vendor S3 bucket (e.g.
  kulta-licensed) following the "Meta Vendor Data - Format Spec". Use this
  whenever the user wants to upload a delivery or sample of harbor_tasks to S3,
  mentions a *-licensed vendor bucket, dataset=/delivery= keypaths, the Meta
  vendor format spec, or needs to validate/normalize task names
  (hyphens/dots/uppercase -> snake_case) and their task.toml before delivering,
  rename task directories in place to the [a-z0-9_] charset and keep their
  task.toml name fields in sync, resume/speed up a large S3 upload, or verify
  that an S3 delivery matches the local files. Also trigger for "rename these
  task dirs to snake_case", "make the dir names match ^[a-z0-9_]",
  "check if my AWS is logged in for the delivery",
  "package and upload these tasks to Meta", "why is my upload getting
  AccessDenied", or "summarize what I uploaded and where".
---

# Meta Vendor S3 Delivery

Upload Harbor task datasets to a vendor delivery bucket so Meta's ingestion
system can pick them up. Meta derives all metadata from the **S3 keypath
structure**, not from parsing names, so getting the path layout and the task
naming exactly right is the whole job.

## The keypath format (non-negotiable)

```
s3://{VENDOR}-licensed/{licensed|sample}/dataset={DATASET}/delivery={ISO8601_DATE_UTC}/{TASK_NAME}/...
```

- `licensed` = real delivery; `sample` = evaluation-only. Meaning comes **only**
  from this path segment, never from a name suffix like `_sample`.
- `dataset=` and `delivery=` are literal `key=value` segments — keep them verbatim.
- `delivery=` is an ISO8601 **UTC date**, `YYYY-MM-DD` (e.g. `2026-06-21`).
- Each `{TASK_NAME}` is a directory containing the task files plus a `task.toml`
  whose name fields match the directory name.

**Naming rules** (apply to vendor, dataset, and task names):
- charset `[a-z0-9_]` only — lowercase letters, digits, underscore. **No hyphens,
  dots, uppercase, or spaces.** (The spec's own examples sometimes use hyphens in
  *dataset* names like `tbench-100`; that contradicts the rule, so confirm with
  Meta before using hyphens, and default to snake_case.)
- `len({VENDOR}_{DATASET}_{TASK_NAME}) <= 255`.

**Redelivery rule:** to update a task, re-upload it with the **same task name +
same dataset + a NEW `delivery=` date**. That creates a new version. Do NOT add a
suffix like `-v2` or rename the task — Meta would treat it as a brand-new task.

## Prerequisites: AWS access

1. Confirm identity: `aws sts get-caller-identity`. The Arn is the principal Meta
   must authorize. If credentials are missing, see `references/format-spec.md`.
2. These delivery buckets are typically **write-only** (PutObject, often no
   ListBucket, never DeleteObject) and usually **cross-account** (the bucket lives
   in Meta's account). Cross-account S3 needs BOTH sides: Meta's bucket policy
   granting your principal AND an identity-based IAM policy on your side. A
   missing IAM policy on your side is the most common cause of `AccessDenied`
   even after Meta says "access granted". The IAM policy to attach and the full
   troubleshooting tree are in `references/format-spec.md` — read it whenever you
   hit AccessDenied or the user asks why they can't ls/upload.

## Workflow

Run these three scripts in order. They live in `scripts/` and take plain
arguments; invoke with `bash`. `{VENDOR}` is the bucket name minus `-licensed`
(e.g. bucket `kulta-licensed` -> vendor `kulta`).

### 1. Validate (read-only — always do this first)

```bash
bash scripts/validate_tasks.sh <harbor_tasks_dir> <vendor> <dataset> [namemap_out.tsv]
```

Reports, for every task dir: charset compliance, whether `task.toml` name matches
the dir name, the combined-length invariant, `.DS_Store` count, and — critically —
**name collisions** that would appear after normalization. Exits non-zero if there
are blocking problems. Fix blocking issues at the source before uploading.

### 1b. Normalize at the source — in place (optional)

```bash
bash scripts/normalize_tasks.sh <harbor_tasks_dir> [--apply]
```

Use this when you want the **local** dataset itself to be name-compliant (e.g.
before committing or sharing the folder), not just the uploaded copy. It renames
each task directory to the `[a-z0-9_]` charset (`tr A-Z a-z`, then any char
outside `[a-z0-9_]` -> `_`) and rewrites the matching name string inside that
task's `task.toml` so the dir name and `name = "…/<dir>"` field stay in sync —
the same substring that appears as `security/<dir>` is replaced, keywords and
descriptions are left alone.

- **Defaults to dry-run** (prints `would rename: old -> new`); pass `--apply` to
  actually rename. After `--apply` it re-checks that every dir matches
  `^[a-z0-9_]+$`.
- Aborts before touching anything if two names would collide (two old names
  normalizing to the same new name, or a new name clashing with an existing dir).
- This is the in-place counterpart to the on-the-fly normalization that
  `upload_delivery.sh` (step 2) already does to the uploaded copy — you do NOT
  need this step just to deliver; it is for fixing the source tree itself.

### 2. Upload (validate first, then this)

```bash
bash scripts/upload_delivery.sh <harbor_tasks_dir> <bucket> <licensed|sample> <dataset> <delivery_YYYY-MM-DD> [region] [--dryrun]
```

What it does, per task:
- Normalizes the task name to snake_case (`tr A-Z a-z`, then any char outside
  `[a-z0-9_]` -> `_`). If the name changes, it also rewrites the matching `name`
  fields inside `task.toml` so dir name == toml name (keywords/descriptions are
  left alone — only the exact task-name string is replaced).
- Uploads with **`aws s3 sync`** (not `cp`), so it is idempotent and **resumable**:
  re-running skips objects already present and only fills gaps. `.DS_Store` is
  always excluded.
- Aborts up front if normalization would cause a collision.
- Writes a log + `.meta` summary under `scripts/.work/` and prints the failure count.

Always do a `--dryrun` first on anything large or unfamiliar — it shows exactly
what would be written without touching S3. Uploading to a real vendor bucket is
outward-facing; confirm the dataset name, class (licensed vs sample), and date
with the user before the real run.

**Large deliveries (tens of thousands of files):** raise S3 concurrency before
uploading — `aws configure set default.s3.max_concurrent_requests 20`. Note this
only helps when you are NOT bandwidth-limited; if the upstream link is saturated
(measure MB/s), more concurrency won't help and the only real fix is a
higher-bandwidth host. See `references/format-spec.md` (Performance) for the
bandwidth-vs-EC2 decision and how to measure.

### 3. Verify (after upload completes)

```bash
bash scripts/verify_delivery.sh <harbor_tasks_dir> <bucket> <licensed|sample> <dataset> <delivery_YYYY-MM-DD> [region] [upload_log]
```

Checks the delivery is complete and correct:
- S3 object count == local file count − `.DS_Store` count
- S3 task-prefix count == local task-dir count
- no non-compliant (hyphen/uppercase/dot) prefixes remain
- zero `upload failed:` lines in the log (if given)

Report the result plainly. A count mismatch means re-run the upload (sync will
fill the gaps).

## Reference

`references/format-spec.md` — the full format spec summary, the exact IAM policy
to attach, the cross-account / AccessDenied troubleshooting tree, performance &
bandwidth guidance, and redelivery examples. Read it for anything beyond the
happy path.
