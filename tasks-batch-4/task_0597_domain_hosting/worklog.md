# Worklog — task_0597_domain_hosting

## Step 1: Create task directory — 2026-07-12T00:00:00.000Z

Created `tasks/task_0597_domain_hosting/` and `tasks/task_0597_domain_hosting/workspace/` (directory ID pre-assigned by the user; no scan of tasks/ performed).

## Step 2: Generate scaffold (Expert) — 2026-07-12T02:30:00.000Z

All three artifacts are generated and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0597_domain_hosting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0597_domain_hosting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0597_domain_hosting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  517

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design (Expert)
`api_prefix: /registrar`. Profile: compliance/audit × pricing engine; graph topology; **parallel** state-machine shape; `segregation_of_duties` role model; layers = cascading side effects, dual-variant calc, OCC, rate/threshold triggers, ops-run checkpoint.

**Counts:** 14 entities · 9 state machines · 2 concurrency rules (OCC) · 12 calculations · 37 validations · 52 endpoints · 46 errors · 6 roles. §1.8 = 9 rules × 2 = **18 instances**; §1.9 = **45 active + 8 `excluded_because` stubs** across all nine claim-guide sections.

**Key mechanics:**
- Domain carries **two independent state dimensions** (`lifecycle_status` with EXPIRED→ACTIVE / REDEMPTION→ACTIVE revival cycles, × `lock_status` LOCKED↔UNLOCKED); TransferRequest is **cyclic** (INITIATED→PENDING_ACK→REJECTED→INITIATED, capped at 3 attempts); AbuseReport **branches** UNDER_REVIEW→{UPHELD, DISMISSED} with divergent side-effect sets.
- Dual variants on *different* domains: renewal QUOTED-vs-CHARGED across a redemption sweep (1199 vs 9199) and bandwidth overage PROVISIONAL-vs-FINAL over identical usage rows (3079 vs 2809).
- Combinatorial modes (b) per-line tax rounding-then-sum (98 ≠ 99) and (c) pinned discount→service-fee tier ordering (299 ≠ 999).
- Cascades: abuse uphold → domain suspend → add-ons revoked/suspended + risk recompute → account suspend → subscription suspend (depth 4); expiry sweep → domain expire → subscription suspend → add-on suspend (depth 3).
- Conserved quantities: `net_cash_cents` (pay + full CARD refund → 0) and `storage_committed_mb` (mailbox create + delete → no drift).
- Interval semantics differ per resource: SSL certs use **closed intervals + 1-day buffer** on a Domain; BillingPeriods use **half-open** intervals on a HostingSubscription.
- Logical clock defaults to `2026-05-01T00:00:00Z`; `/_clock/set_current_utc` + `/_ops/run-expiry-sweep` are the only `/_`-namespaced endpoints.

Every formula-derived assertion literal (invoice totals, taxes, overage cents, risk scores, decayed scores, expiry dates) was computed in Python and pinned. Two YAML-syntax normalizations were applied so PyYAML parses cleanly: optional inputs are quoted (`"auto_renew_default?"`) and all path params use `{id}` (required by lint check (f)'s sub-resource matcher).

## Step 3: Copy shared files — 2026-07-12T02:31:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0597_domain_hosting/workspace/INSTRUCTION.md`.
