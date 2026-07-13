# Worklog — task_0847_airport_ground_transport_tnc

## Step 1: Create task directory — 2026-07-12T07:09:00.000Z

Created pre-assigned directory `tasks/task_0847_airport_ground_transport_tnc/` with `workspace/` subdir. No ID scan (folder pre-allocated).

## Step 2: Generate scaffold — 2026-07-12T07:41:00.000Z

All three artifacts complete and pass linter cleanly. Verified all three safe_load OK.

Complexity profile: compliance-audit primary + pricing-engine secondary; flat topology; branching state-machine shape; peer roles; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency.

Counts:
- Entities: 10 (Operator, Vehicle, Permit, StagingLot, QueueEntry, CurbZone, CurbAssignment, Trip, Violation, SettlementStatement)
- State machines: 6 (Operator cyclic SUSPENDED↔ACTIVE; Violation branching fork-join OPEN→{ASSESSED,DISMISSED}, APPEALED→{UPHELD,OVERTURNED}; plus Vehicle, Permit, Trip, SettlementStatement)
- Calculations: 5 (trip_fee provisional/final variants; operator_penalty_score rolling/lifetime variants; settlement_statement_totals sum-then-round; wav_compliance_check; fifo_position_assignment)
- Concurrency rules: 1 (OCC permit-create-supersede on Vehicle.version)
- Endpoints: 32 (incl. /_clock/set_current_utc, default 2026-03-01T00:00:00Z)
- Error catalog: 21 codes
- RBAC: 3 roles (AirportAuthority opaque, Operator entity_backed, CurbCoordinator opaque)
- §1.8: 9 rules × 2 = 18 difficulty instances
- §1.9: 32 active corner instances + 4 excluded_because stubs, across 7 claim-guide sections

Key mechanics: dual-variant trip fee (dispatch-hour vs pickup-hour peak crossing → 350 vs 525) and rolling-vs-lifetime penalty scoring; sum-then-round monthly settlement admin fee (25 vs per-trip 26); depth-3 cascade Operator→Vehicle→Trip→CurbAssignment; half-open curb-interval overlap vs closed staging-cooldown-buffer overlap; conserved-quantity invariants; >=12 penalty suspension boundary and zero-trip WAV empty-set boundary.

## Step 3: Copy INSTRUCTION.md — 2026-07-12T07:42:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-12T07:47:00.000Z

PRD.md generated (239 lines). §1 Intro, §2 Global Specs (RBAC, envelope, pagination, versioning, logical clock, cascade, OCC, monetary precision), §3 Business Logic (8 subsections), §4 endpoint table (32 endpoints), §5 error table (21 codes). 10 entities covered. Hard Contracts: Field-Name Coverage 69/69 PASS; Rule Coverage PASS (6 state machines, 4 calcs, OCC rule, cascades, validation priority orderings); §3 Path Purity 305 tokens 0 violations PASS. No material scaffold ambiguities. Design files not opened.

## Step 5: Generate unit tests — 2026-07-12T08:04:00.000Z

test_helpers/ (9 files): __init__, types (10 entity TypedDicts + 13 enums), api_client (32 endpoint methods), api_errors (21), assertions, factories, constants, test_users (opaque AirportAuthority/CurbCoordinator + make_operator_headers builder), fixtures (composite setups: setup_queued_vehicle, setup_dispatched_trip, setup_completed_trip, setup_two_dispatched_trips, + granular helpers).
test_suite/: conftest + 9 test files, 67 test functions.
- Queue A (Difficulty): all 18 instances covered, ≥2 tests each (37 tests; penalty_threshold_ge_12_boundary got 3 for X-1/X/X+1).
- Queue B (Corner): 30 tests, one per covered non-stub instance.
- Skipped 2: entities/create_operator_missing_type_returns_invalid_request and create_operator_bad_enum_returns_invalid_request — both assert ERR_VALIDATION but PRD's only verbatim ERR_VALIDATION prose (§2.3) covers pagination limit/offset only; no PRD sentence names ERR_VALIDATION for missing field / bad enum. Gaps left as gaps.
- Stubs 3: trip_fee_dual_variant_covered, settlement_sum_then_round_covered, operator_suspend_cascade_covered (excluded_because pointers → real difficulty instances; correctly not translated).
Verification: 67/67 collect (confirmed by orchestrator with PYTHONPATH=.), all quoted PRD citations verbatim, 67 test funcs ↔ 67 Design: tags 1:1, 0 skip/xfail.

## Step 6: Generate implementation — 2026-07-12T08:04:00.000Z

workspace/implementation/: start.sh (guarded dep-install, exec python3 app.py, $PORT default 10000, binds 0.0.0.0, foreground), app.py (Flask factory + blueprints + ApiError/404/405/500 handlers), store.py (10 in-memory dicts, logical clock default 2026-03-01T00:00:00Z, base_record/touch), errors.py, calc.py (pricing/scoring/haversine + constants), common.py (envelope/auth/validators/pagination), serializers.py (operator computed fields live), logic.py (cascades/sweep/FIFO renumber/auto-suspend), routes/ (11 blueprint modules). Route count = 32 (matches scaffold, confirmed by orchestrator). All 19 .py files pass ast.parse. Pure in-memory, zero persistence/seeding.
PRD ambiguities resolved: (1) FINE_CENTS_BY_TYPE has no numeric schedule in PRD/scaffold — fixed deterministic schedule, not test-assertable; (2) operator rolling/lifetime/outstanding derived live on read (no version bump on GET), declared recompute side effects call touch(operator); (3) permit-window activation → ERR_INVALID_STATE (409); (4) transition validation ordering: action-role 403 after body-validation before existence, ownership 403 after existence; PRD-ordered business guard chains implemented in exact order; (5) SETTLE missing payment_amount_cents → ERR_VALIDATION 400, wrong amount → ERR_SETTLEMENT_AMOUNT_MISMATCH 402.

## Step 7: Test and iterate — 2026-07-12T08:15:00.000Z

All 8 rounds pass cleanly (67/67 each). Clean sweep achieved.

Iterations run: 2 (baseline sweep + 1 fix + confirming sweep).
Tests deleted: None.
Fixes applied to test_helpers/: None.
Fix applied to test_suite/ (STEP 2 — test-vs-PRD consistency, not an implementation change):
- test_suite/test_01_operator_registration.py, test_suspend_revoked_operator_returns_invalid_state: setup created a PENDING operator and immediately called REVOKE. PRD §3.1 permits REVOKE only from ACTIVE or SUSPENDED — a PENDING operator is not revocable — so the PRD-faithful implementation correctly rejected the setup step with ERR_INVALID_STATE. Added activate=True to create_operator(...) so the operator reaches REVOKED via PENDING → ACTIVE → REVOKED. The test's actual assertion (SUSPEND on REVOKED → ERR_INVALID_STATE) is unchanged and now runs against a valid precondition.
Fixes applied to implementation/: None — implementation was already PRD-faithful.
Failure was fully deterministic (1/67 failing identically in all 8 baseline rounds); no flakiness observed.

## Step 8: Finalize PRD — 2026-07-12T08:18:00.000Z

No edits required. PRD_FINALIZED.md is byte-for-byte copy of PRD.md (239 lines, 0% delta).
Evidence: routes/operators.py:80-84 rejects REVOKE unless status in (ACTIVE, SUSPENDED) → ERR_INVALID_STATE; PRD.md:112 lists REVOKE only from ACTIVE/SUSPENDED, PENDING never revocable. Impl and PRD.md already agree; the single Step 7 item was a pure test-fixture bug (activate=True added), zero implementation changes. No PRD-silence, no mismatch to pin.

## Step 9: Complete PRD — 2026-07-12T08:24:00.000Z

PRD_COMPLETED.md produced. PRD_FINALIZED.md → PRD_COMPLETED.md: 239 → 239 lines; 36,691 → 37,487 chars (+796). 8 in-place line revisions (all in-paragraph inserts, no new sections). ambiguity-pins: 8; mismatch-revisions: 0.
Changes:
- §2.2 — api_request_timestamp stamped from logical clock not wall time (common.py:33).
- §2.3 — list created_at ties broken by ascending creation order (common.py:215).
- §3.1 — wheelchair_pledge_pct outside 0.0–1.0 → ERR_VALIDATION (routes/operators.py:27-28).
- §3.2 — activating permit outside validity window → ERR_INVALID_STATE (routes/permits.py:91-92).
- §3.3 — geofence check great-circle haversine, R=6,371,000 m, boundary inclusive (calc.py:68-76, queue_entries.py:49-51).
- §3.7 — fixed fine_cents schedule (STAGING 5000, CURB 7500, AVI_MISMATCH 15000, NO_DECAL 15000, WAV_SHORTFALL 10000) (calc.py:25-31; absent elsewhere).
- §3.8 — period_month outside 1–12 → ERR_VALIDATION (routes/settlements.py:25-26).
- §4 — clock-setting endpoint returns empty data object (routes/clock.py:19).
Verified-consistent non-changes: stale-before-duplicate ordering, all fee math, cascade scope, penalty scoring, appeal/staging windows, curb half-open overlap, settlement math, guard orderings.

## Pipeline complete — 2026-07-12T08:24:00.000Z

All 9 steps done. Final: 8/8 sweep rounds pass 67/67. Artifacts: SCAFFOLD.yaml + 2 design files, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (67 tests), workspace/implementation/ (Flask, 32 routes, in-memory).
