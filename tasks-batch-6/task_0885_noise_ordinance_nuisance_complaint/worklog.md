# Worklog — task_0885_noise_ordinance_nuisance_complaint

## Step 1: Create task directory — 2026-07-28T16:44:33.000Z

Created pre-assigned directory `tasks/task_0885_noise_ordinance_nuisance_complaint/` with `workspace/` subdir. Skipped the Step-1 index scan (folder pre-assigned to avoid ID contention with parallel runs).

## Step 2: Generate scaffold — 2026-07-28T17:10:55.000Z

All three files in place, parse cleanly (safe_load OK ×3), pass `scaffold_lint.py`. No sibling task consulted.

### Counts
- **Entities:** 10 — Property, NoiseLimitPolicy, VariancePermit, Complaint, Inspection, Enforcement, Hearing, AbatementOrder, CrossAgencyReferral, Payment
- **Endpoints:** 38 (flat topology, `api_prefix: "/"`, incl. `POST /_clock/set_current_utc` with mandated `2026-05-01T00:00:00Z` default)
- **State machines:** 7 (Complaint, VariancePermit, Enforcement[cyclic], Hearing, Property[parallel axes], AbatementOrder, CrossAgencyReferral)
- **Calculations:** 8; **Errors:** 35; **Roles:** 5 (SoD model); **OCC rules:** 2
- **§1.8 difficulty instances:** 18 (2 per rule × 9 rules)
- **§1.9 corner instances:** 30 (27 executable + 3 `excluded_because` stubs), across all 9 guide sections

### Lint
`VERDICT: clean lint` — all 345 scanned §1.8/§1.9 calls conform to §1.5; every §1.1 FK has reverse-reachability in §1.5.

### Design notes worth flagging
- Archetype: compliance/audit + posture-driven gating; layers = OCC, cascading side-effects, dual-variant calc, rate/threshold triggers.
- Two OCC true-races (CREATE-with-supersede): payment→Enforcement.version, manual abatement→Property.version. No forbidden race vocabulary.
- Load-bearing rounding divergence pinned: late penalty is round-per-day-then-sum (INDUSTRIAL 7500 @1.5%/day × 2 days = 226, vs sum-then-round 225) — Rule-2 mode-(b) instance. All formula-derived asserts computed in Python, written as literals (15000, 11250, 7500, 226, 30000/20000 variance fees, etc.).
- Pinned evaluation order: fine's chronic multiplier reads `chronic_status` BEFORE the substantiate cascade recomputes it (circular-looking dependency made deterministic).
- No undeclared constants: every constant in a `calculations[].constants` block, mirrored in a `constants_index` guard block (BASE_FINE_CENTS, ZONING_FINE_FACTOR map, CHRONIC thresholds/window, PAYMENT_DUE_DAYS, LATE_PENALTY_DAILY_PCT, variance fee constants, VARIANCE_ABSOLUTE_MAX_DB, HEARING_BUFFER_MINUTES, ABATEMENT_COMPLIANCE_DAYS, DEFAULT_CLOCK_UTC).
- Self-consistency fix: dropped dead `Payment.status = VOIDED` (no producing transition; append-only ledger uses REFUND rows).
- Two interval semantics for Rule 8: variance windows half-open `[start,end)` on Property; hearing slots closed + 60-min officer buffer on HearingOfficer.

## Step 3: Copy shared files — 2026-07-28T17:10:55.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-28T17:17:34.000Z

Generated `workspace/PRD.md` (273 lines). All 3 hard contracts pass (Field-Name Coverage 63/63; Rule Coverage all SMs/8 calcs/11 validations/2 OCC/cascades; §3 Path Purity 338 tokens, 0 leaks). Withheld design YAMLs not opened.

Constants rendered into prose: BASE_FINE_CENTS $100.00, MAX_FINE_CENTS $5,000.00 cap, CHRONIC_FINE_MULTIPLIER 1.5, ZONING_FINE_FACTOR (RES 1.0/COM 1.5/IND 0.75/MIXED 1.25); fine = base × level × zoning × chronic, round-half-up then min-cap; chronic factor reads chronic_status BEFORE recompute. CHRONIC_WATCH_THRESHOLD 2, CHRONIC_DESIGNATED_THRESHOLD 3, CHRONIC_WINDOW_DAYS 365. PAYMENT_DUE_DAYS 30; LATE_PENALTY_DAILY_PCT 1.5% round-per-day-then-sum, floor of overdue days. variance_fee CONSTRUCTION $50.00 + $25.00/day (ceil sec/86400); EVENT $100.00 + $0.50/attendee; estimate uses requested, final uses approved window. VARIANCE_ABSOLUTE_MAX_DB 95, HEARING_BUFFER_MINUTES 60, ABATEMENT_COMPLIANCE_DAYS 30, DEFAULT_CLOCK_UTC 2026-05-01T00:00:00Z. Boundaries: strict > for exceeds; half-open daytime [day_start,night_start) and variance-overlap [approved_start,approved_end); reduction_pct in [0,1).

Left open (matching scaffold openness): exact state-error code per transition deferred to §5 catalogue + priority-5 list + generic ERR_INVALID_STATE fallback.

## Step 6: Generate implementation — 2026-07-28T17:17:34.000Z (completed later)

Built `workspace/implementation/`: `app.py` (~1000 lines single-file), `requirements.txt` (Flask 3.0.3), `start.sh` (foreground, reads $PORT default 10000, binds 0.0.0.0, guards pip install behind flask import check, exec). 38 endpoints. In-memory only, no seed.

Logical clock: module-global init `2026-05-01T00:00:00Z` at import (fresh per process, no wall-clock). POST /_clock/set_current_utc overrides. System timestamps rendered `.000Z`; input datetimes stored raw + echoed verbatim. OCC: expected_enforcement_version (payments) + expected_property_version (abatement-orders) → ERR_STALE_VERSION (412), checked prio 6. version starts 1, bumps per mutation. Enum failures → ERR_INVALID_ENUM.

PRD ambiguities resolved (concrete choices):
1. Substantiate precondition order — checks no-inspection → within-limit → variance-covers (§3.4 workflow order, dependency-safe); isolation tests identical under either order.
2. /_clock/set_current_utc response — returns data: {} (§2.2 rule) despite scaffold output: null.
3. Property version increment in cascades — bumps parcel version exactly once per substantiate/dismiss cascade (PRD singular prose over scaffold per-hop language).
4. Contest state guard — ERR_INVALID_STATE (409) when contesting non-ISSUED enforcement, checked before ERR_ENFORCEMENT_NOT_CITATION tier check.
5. Payment amount_cents — positive integer enforced (ERR_VALIDATION on ≤0).

## Step 5: Generate unit tests — 2026-07-28T17:32:32.000Z

Generated 7 test files + conftest.py in test_suite/ (63 tests) and 9 test_helpers files. Queue A (Difficulty): all 18 instances × 2 tests = 36. Queue B (Corner): all 27 non-stub instances × 1 = 27. 3 consistency_model `excluded_because` stubs correctly not translated (cross-refs resolve to real queue-A instances). ZERO skips — PRD unusually explicit (§2.5 states SoD-before-reduction + numbered validation priority verbatim). Every docstring has verbatim PRD citation + one Design: tag. All 63 collect cleanly. test_users.py provides per-user-id header builders (issuer officer-1 vs decider hof-9) since all 5 roles opaque but SoD needs distinct X-User-ID. fixtures.py: setup_level1_citation, setup_scheduled_hearing, setup_watch_property, setup_designated_property.

## Step 7: Test-and-fix loop — 2026-07-28T17:37:06.000Z

CLEAN FIRST-SWEEP PASS. Iterations run: 1 (single 8-round parallel sweep). Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none. All 8 concurrent rounds reported passed=63/total=63/failed=0/errors=0/skipped=0. No flakiness (union of failing tests empty).

OP note: Step-7 subagent left no results.*.json on disk (known pattern, cf. task_0879). Orchestrator re-ran the 8-round sweep via workspace/sweep.sh to re-verify on-disk before skipping Step 8 — confirmed 63/63 all 8 rounds (results.1.json..results.8.json now on disk).

## Step 8: Finalize PRD — SKIPPED — 2026-07-28T17:37:06.000Z

Skip condition met: Step 7 exited on first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7 sites. No PRD_FINALIZED.md produced. Step 9 still runs (full completeness scan).

## Step 9: Complete PRD — full impl completeness scan — 2026-07-29T00:00:00.000Z

RESUMED Step 9 only (session-limit kill at Step 8→9 boundary; stale byte-identical PRD_COMPLETED.md overwritten with real scan). No PRD_FINALIZED.md (Step 8 correctly skipped) → scanned from PRD.md.

Source: PRD.md = 273 lines / 36171 chars. PRD_COMPLETED.md = 273 lines / 37454 chars. Char delta: +1283. 9 lines revised.
Counts: ambiguity-pins = 8, mismatch-revisions = 1.

Changes:
- §3.1 — insert — ambiguity — hour boundary outside 0–23 rejected with `ERR_VALIDATION` — app.py:623-624
- §3.2 — insert — ambiguity — review of a complaint not in `RECEIVED` rejected with `ERR_INVALID_STATE` — app.py:835-836
- §3.4 — revise — ambiguity — variance-coverage window is half-open `[approved_start, approved_end)` at substantiation — app.py:918
- §3.5 — revise — mismatch — issuance accepts only approved_start/approved_end/permitted_max_db; attendees never re-adjusted, so EVENT `fee_final_cents` always equals `fee_estimate_cents` (PRD's "approved attendees" implied a divergence impl never produces) — app.py:717-751
- §3.6 — revise — ambiguity — contest requires enforcement in `ISSUED` (else `ERR_INVALID_STATE`), checked before the tier/`ERR_ENFORCEMENT_NOT_CITATION` check — app.py:1088-1091
- §3.6 — revise — ambiguity — hearing slot conflict spans the whole docket regardless of status; conflict when the gap between closed slots is strictly < 60 min (overlap = gap 0 conflicts; exactly 60 min allowed) — app.py:1112-1125
- §3.7 — insert — ambiguity — `amount_cents` must be a positive integer > 0, else `ERR_VALIDATION`; refund rows carry `status` `CLEARED` and `method` `CARD` — app.py:1160-1161, 1244-1246
- §3.8 — revise — ambiguity — comply and escalate both require the order to be `PENDING` (else `ERR_INVALID_STATE`), checked before the abatement_status / deadline checks — app.py:1359-1363, 1376-1380
- §4 — revise — ambiguity — `/enforcements` list filters by `complaint_id`, `property_id`, `status`, `tier` — app.py:1058-1070

## Pipeline complete — 2026-07-29T00:00:00.000Z

All 9 steps done. Step 7 clean first-sweep (63/63 × 8 rounds), Step 8 skipped, Step 9 completeness scan pinned 8 ambiguities + 1 mismatch. PRD_COMPLETED.md well-formed (5 top-level sections, error-catalogue ending) and differs from PRD.md. Task green.
