# Meta Vendor Data — Format Spec (reference)

Detailed reference for the `meta-vendor-s3-delivery` skill. Read the relevant
section when you go beyond the happy path.

## Table of contents
- Why the format matters
- Keypath format & rules
- Redelivery semantics (examples)
- AWS access: identity, IAM policy, cross-account gotcha
- AccessDenied troubleshooting tree
- Performance: bandwidth vs. concurrency vs. EC2
- Name normalization details

## Why the format matters

Tasks are ingested into a Meta system that tracks metadata and runs validations.
Meta derives meaning from **S3 keypath segments**, not from parsing names. It uses
segments like `licensed`/`sample` to classify, but deliberately does NOT parse
prefixes/suffixes inside task or dataset names (a `_sample` suffix carries no
meaning). So the path layout and exact task naming are what make ingestion work.

In Meta's model a Task has many TaskVersions; the latest TaskVersion of a given
task name is canonical. That is why redelivery = same name + new date (below).

## Keypath format & rules

```
s3://{VENDOR}-licensed/{licensed|sample}/dataset={DATASET}/delivery={ISO8601_DATE_UTC}/{TASK_NAME}/...
```

- `{VENDOR}-licensed` is the bucket (e.g. `kulta-licensed`, so vendor=`kulta`).
- `licensed` = real delivery, `sample` = evaluation-only.
- `dataset=` / `delivery=` are literal key=value segments.
- `delivery=` is a UTC date `YYYY-MM-DD`.
- `{TASK_NAME}` is a directory containing a `task.toml` whose name == dir name.
- Charset for vendor/dataset/task: `[a-z0-9_]` (lowercase, digits, underscore).
  No hyphens, dots, uppercase, spaces.
- `len({VENDOR}_{DATASET}_{TASK_NAME}) <= 255`.

Caveat: the spec's examples sometimes use hyphens in *dataset* names
(`tbench-100`), contradicting the charset rule. Default to snake_case; confirm
with Meta before relying on hyphens.

## Redelivery semantics (examples)

- Initial:   `.../dataset=tbench-100/delivery=2026-06-08/traveling_salesman` ✅
- Update it: `.../dataset=tbench-100/delivery=2026-06-09/traveling_salesman` ✅ (new version)
- WRONG:     `.../dataset=tbench-100/delivery=2026-06-10/traveling_salesman-v2` 🚫 (new task, not a version; also `-` is illegal)
- Same task re-sent unchanged under a new date = no-op for that task.
- Different task name under a new date = initial delivery of a new task.

## AWS access

1. `aws sts get-caller-identity` — the `Arn` is the principal Meta authorizes.
   Give Meta the EXACT arn, e.g. `arn:aws:iam::<acct>:user/Data_Delivery_for_Meta`
   (IAM user arns use a DOUBLE colon for the empty region field:
   `arn:aws:iam::123...:user/Name` — a malformed arn in the bucket policy silently
   grants nothing).
2. If no credentials are configured, the user must `aws configure` with a valid
   access key id + secret. An access key id has exactly ONE secret (fixed at
   creation); a "different secret for the same key id" is a copy error. Test a new
   pair non-destructively before overwriting a working config:
   `AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... aws sts get-caller-identity`.
3. Delivery buckets are usually write-only by design: `ListBucket` and
   `GetObject`/`DeleteObject` may be denied. Not being able to `ls` is normal;
   what matters is whether `PutObject` works.

### IAM policy to attach (your side)

These buckets are normally **cross-account** (bucket in Meta's account). Cross-
account S3 requires BOTH Meta's bucket policy AND an identity-based IAM policy on
your principal. Attach this to the delivery user/role in YOUR account:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "DeliveryUpload", "Effect": "Allow", "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::<bucket>/*" },
    { "Sid": "DeliveryList", "Effect": "Allow", "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::<bucket>" }
  ]
}
```

Note the two different resource forms: `ListBucket` targets the bucket arn
(`...:bucket`), `PutObject` targets objects (`...:bucket/*`). Mixing these up is
the classic "can write but can't ls" (or vice-versa) bug. Add `s3:DeleteObject`
only if you truly need to delete (delivery buckets are best kept write-once;
versions come from new dates, not overwrites/deletes).

## AccessDenied troubleshooting tree

- `s3:ListAllMyBuckets` denied with "no identity-based policy allows ..." →
  your user has no/empty identity-based permissions. Attach the IAM policy above.
- Authenticated (`sts` works) but every `PutObject`/`ListBucket` is AccessDenied →
  cross-account with your-side IAM policy missing, OR Meta's bucket policy
  Principal doesn't match your real arn (often a malformed/typo'd arn you sent).
  Fix: send Meta the exact arn AND attach your-side IAM policy.
- `head-bucket` returns 403 (not 404) → bucket exists, you're just unauthorized
  (a permissions problem, not wrong bucket/region).
- After adding the policy, re-test with a tiny object, then clean it up only if
  you have DeleteObject.

## Performance: bandwidth vs. concurrency vs. EC2

For big deliveries (tens of thousands of files), first decide what the bottleneck
is — don't assume concurrency:

- Raise concurrency: `aws configure set default.s3.max_concurrent_requests 20-30`.
- Measure byte throughput: sample `aws s3 ls <prefix> --recursive --summarize`
  total size twice ~20s apart; `(size2-size1)/20` = bytes/sec.
- If raising concurrency does NOT change throughput, you are **bandwidth-bound**
  (the upstream link is the cap). More concurrency won't help; only a
  higher-bandwidth host will.
- EC2 only helps if data compresses a lot: you still push the bytes over your slow
  uplink to EC2 first. Measure: `tar --exclude=.DS_Store -czf x.tgz -C <parent> <dir>`.
  Modest ratios (~3x on source+binaries) rarely justify the EC2 setup + credential
  transfer overhead vs. just letting an unattended sync finish.
- Resume is free: `upload_delivery.sh` uses `aws s3 sync`, so stopping and
  re-running skips everything already uploaded. To change concurrency mid-flight,
  stop the run, set the config, and re-run — sync continues from the gap.

## Name normalization details

`normalize(name) = lowercase, then replace every char outside [a-z0-9_] with _`.
Examples:
- `Linux-189f164e573e-kasan-...-T4` -> `linux_189f164e573e_kasan_..._t4`
- `addr2line-2.42-...-A5O3V2C4-t4` -> `addr2line_2_42_..._a5o3v2c4_t4`
- `alex-gda-minimax-optimizer-scaffold` -> `alex_gda_minimax_optimizer_scaffold`

When a name is normalized, the matching `name = "<old>"` lines in `task.toml`
(both `[task]` and `[metadata]`) are rewritten to the new name. Only the exact
full task-name string is replaced, so `keywords`/`description` values that merely
contain a hyphenated substring (e.g. `"alex-gda"`) are left untouched.

Always collision-check after normalization: different originals can collapse to
the same snake_case name (e.g. `foo-bar`, `foo.bar`, `foo_bar` -> `foo_bar`). The
scripts abort on any collision so you resolve it at the source rather than
silently overwriting one task with another.
