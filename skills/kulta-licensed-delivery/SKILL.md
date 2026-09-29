---
name: kulta-licensed-delivery
description: >-
  Upload a finished dataset delivery folder to the kulta-licensed S3 bucket as a
  formal LICENSED delivery, then verify the object counts. Use whenever the user
  wants to deliver / upload / push / 正式交付 a {DATASET_NAME}_{YYYY-MM-DD} folder
  from the local delivery workspace to the kulta vendor bucket, or sync a
  delivery folder to s3://kulta-licensed/licensed/dataset=.../delivery=.../ and
  confirm it matches the local files. This skill ONLY operates on folders located
  directly under /Users/uni/Desktop/吉/product_delivery_workspace/delivery and
  refuses anything else; it is always class `licensed` (for evaluation-only
  `sample` uploads, use meta-vendor-s3-delivery instead). Trigger for
  "正式交付 this folder", "upload prd_to_repo_2026-06-29", "deliver <dataset> to
  kulta", "push the delivery to S3".
---

# Kulta Licensed Delivery

One-command **formal (licensed) delivery** of a finished dataset folder to the
kulta vendor bucket, with built-in verification. This is the simplified
single-`aws s3 sync` path — no name normalization, no `task.toml` rewriting.
(All the task names in these deliveries are already compliant snake_case, so the
heavier meta-vendor-s3-delivery machinery isn't needed.)

## Hard constraints (the script enforces these — do not bypass)

- **Source must live directly under the delivery base** — by default
  `/Users/uni/Desktop/吉/product_delivery_workspace/delivery`, overridable with
  the `KULTA_BASE` env var (needed on non-mac hosts).
  `deliver.sh` canonicalizes the path and refuses any folder whose parent is not
  exactly that directory.
- **Folder name must be `{DATASET_NAME}_{YYYY-MM-DD}`** — `DATASET_NAME` is
  `[a-z0-9_]` only, the date is an ISO8601 **UTC** date. The dataset name and the
  delivery date are parsed straight from the folder name; nothing is typed by hand.
- **Destination is fixed and derived:**
  ```
  s3://kulta-licensed/licensed/dataset={DATASET_NAME}/delivery={YYYY-MM-DD}/
  ```
- Class is always **`licensed`** (formal delivery). For evaluation-only samples
  this is the wrong tool — use `meta-vendor-s3-delivery` with class `sample`.

The upload source inside the folder is its `harbor_tasks/` subdirectory when one
exists (the established layout: `{DATASET}_{DATE}/harbor_tasks/<task>/...`),
otherwise the folder itself — so task dirs land directly under `delivery={date}/`.

## Usage

This is an **outward-facing, hard-to-reverse** upload of real licensed data.
Confirm the dataset name + delivery date (i.e. the folder name) with the user
first, then run from this skill's directory:

```bash
# Dry-run first when unfamiliar — shows exactly what would be written, touches nothing.
bash scripts/deliver.sh <folder_name> --dry-run

# The real delivery: uploads, then verifies S3 counts vs local.
bash scripts/deliver.sh <folder_name>
```

`<folder_name>` may be the bare name (`prd_to_repo_2026-06-29`) or a full path;
either way it must resolve to a folder directly under the delivery base.
Large deliveries take a while and emit one `upload:` line per file — run it in
the background and tail `scripts/.work/deliver_{DATASET}_{DATE}.log`.

What `deliver.sh` does, in order:
1. Resolves + validates the path restriction and the `{DATASET}_{YYYY-MM-DD}`
   name, deriving `dataset=` and `delivery=`.
2. Prints the plan (source, destination, local file/task counts, live vs dry-run).
3. `aws s3 sync` — idempotent and **resumable** (re-run to fill gaps), `.DS_Store`
   excluded, region `us-east-2`, logged under `scripts/.work/`.
4. Verifies: S3 object count == local file count (excl `.DS_Store`), S3 task-prefix
   count == local task-dir count, no non-compliant top-level prefixes, zero
   `upload failed:` lines → prints `DELIVERY: PASS` or `FAIL`.

Pass `--no-verify` to skip step 4 (e.g. when verifying separately later).

## Redelivery (updating a dataset)

Create a new folder with the **same dataset name and a NEW date**
(`{DATASET}_{NEW-DATE}`) and run the skill again. Meta versions by the
`delivery=` date — **never** add a `-v2` suffix or rename tasks.

## Notes

- macOS ships bash 3.2; `deliver.sh` is 3.2-compatible (no `declare -A`). The
  original `meta-vendor-s3-delivery/scripts/upload_delivery.sh` uses `declare -A`
  and silently does nothing on bash 3.2 — that's why this simplified script exists.
- AccessDenied / cross-account IAM troubleshooting lives in
  `meta-vendor-s3-delivery/references/format-spec.md`.
- Override the region with the `KULTA_REGION` env var if ever needed
  (default `us-east-2`).
- Override the delivery base with the `KULTA_BASE` env var. Required when running
  somewhere other than the mac — e.g. on the kulta dev EC2 box:
  `KULTA_BASE=/home/ubuntu/product_delivery_workspace/delivery bash scripts/deliver.sh <folder>`
