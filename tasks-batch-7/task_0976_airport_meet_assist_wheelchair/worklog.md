# Worklog — task_0976_airport_meet_assist_wheelchair

## Step 1: Create Task Directory — 2026-08-10T07:50:35.679Z

Pre-assigned output folder `tasks/task_0976_airport_meet_assist_wheelchair/` and its `workspace/` subdirectory already exist; Step 1 auto-index scan skipped per headless-run instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T08:09:53.633Z

All checks pass. Final summary:

## Summary

**Files written** (all three required):
- `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/SCAFFOLD.yaml` (§1.0–§1.7; 1501 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8; 1446 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9; 1184 lines)

**Counts:**
- Entities: 12 (Airport, Terminal, FlightSegment, Passenger, Agent, WheelchairAsset, AssistRequest, ServiceLeg, Assignment, Incident, Invoice, TrackingEvent)
- State machines: 8 (Airport posture, Agent status, WheelchairAsset status, AssistRequest request_status, AssistRequest billing_status as parallel dimension, ServiceLeg, Assignment, Incident, Invoice)
- Endpoints: 50
- Difficulty rule instances: 18 (9 rules × 2 instances each, per §0.5 minimum)
- Corner test instances: 25 (across 9 sections: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model)

**Difficulty design (harder than expert):**
- Primary archetype: workflow orchestration; secondary: compliance/audit
- Complexity layers: optimistic concurrency (3 OCC rules), cascading side effects, dual-variant calculation, temporal windowing, selector policy, derived field reconciliation
- Segregation of duties (Requester / Dispatcher / Agent / Confirmer / OpsManager / BillingClerk, with dual-signer UMNR and write-off clerk != provisional creator rules)
- Dual-variant charges (provisional at SUBMIT vs final at COMPLETE with posture+time-dependent divergence; final vs write-off baseline with posture normalization)
- Multi-mode combinatorial formulas (mode (a) tiered+conditional fees; mode (b) per-leg-round-then-sum vs sum-then-round divergence)
- Cascading chains: LOCKDOWN → legs → assignments → chairs → agent count (depth 4); Incident(CRITICAL) → Agent SUSPEND → unassign cascade (depth 3)

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy Shared Files — 2026-08-10T08:10:10.277Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_0976_airport_meet_assist_wheelchair/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T08:16:14.353Z

All three hard contracts PASS. PRD is on disk.

**Summary**

- **Output path**: `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/workspace/PRD.md`
- **Line count**: 329 lines
- **Section list**:
  - §1 Introduction (3 paragraphs — pain points, system overview, design tensions)
  - §2 Global Specifications — 2.1 RBAC, 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Properties & Logical Time, 2.5 Airport Posture, 2.6 Nested Retrieval, 2.7 OCC, 2.8 Monetary Precision, 2.9 Validation Priority
  - §3 Business Logic — 10 subsections organized by lifecycle (Provisioning → Passenger/Request → Submit → Dispatch → In-Field → Finalization → Posture/Ops → Incidents → Tracking → Cancellation/Segregation)
  - §4 Endpoint Definitions — 49 endpoints, 4-column table
  - §5 Error Code Catalogue — 19 errors, 2-column table

**Skill's coverage-audit verdicts (all three hard contracts PASS)**:
- **Contract 1 (Field-Name Coverage)**: 89 required, 89 present, 0 missing — PASS. All 19 `error_id` strings present, all state-enum values present.
- **Contract 2 (Rule Coverage)**: Validation priority order (§2.9) renders all 14 rules with rank and error_id pairing; 3 OCC rules expressed with `write_endpoint` + `expected_*_version` + `ERR_STALE_VERSION`/412; all state-machine transitions across 8 state machines expressed with from/to states, preconditions, and side-effect cascades (including LOCKDOWN chair-release without `usage_count` decrement, agent-suspend leg-rebook semantics, UMNR 3-way distinctness, airline-write-off clerk distinctness, 20% property-damage adjustment, connection-leg `scheduled_pickup_utc` recompute); both pricing formulas (provisional & final) expressed in precise prose with all 9 fee constants, basis-point multipliers, half-up rounding order, and after-round delay surcharge; agent and wheelchair selector eligibility + 4-level ranking + half-open overlap rule + leg-kind minute estimates (45/60/75) all expressed; ops-epoch threshold cascade (OFF_SHIFT / NO_SHOW 30-min / SUBMITTED-stale-after-2-ticks) expressed — PASS.
- **Contract 3 (§3 Path Purity)**: 482 §3 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 combined — PASS.

## Step 5: Generate Unit Tests — 2026-08-10T08:31:28.878Z

All files in place. Summary:

**Files written**

- `test_helpers/` (9 files, 1852 lines): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`
- `test_suite/` (18 files, 2219 lines): `conftest.py` + 17 `test_*.py` modules

**Test counts per queue**

- Queue A (Difficulty): 18 instances, 36 tests (2 per instance) — coverage target met
- Queue B (Corner): 25 non-stub instances, 25 tests (1 per instance) — coverage target met
- Total: 61 tests across 17 test files; 79 `Design:` tags emitted (some tests tag multiple aspects of one instance)
- 0 `excluded_because:` stubs present in the corner index

**Instances skipped**

None. Every non-stub instance in both queues passes the PRD-first two-condition filter (verbatim PRD coverage + unique derivability). Spot-checked 43 verbatim citations against `workspace/PRD.md`; all literal-grep-clean.

**Stage-gate verdicts**

- Stage 1 (test_helpers): PASS — all 9 required files present, framework generics re-exported, `TrackingEvent` correctly modeled as append-only (no `version`/`updated_at`), agent role entity-backed with `make_agent_headers()` builder
- Stage 2 (test_suite): PASS — every test carries exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` tag resolving to a real source instance; no freelance tests; no `skip`/`xfail`/`skipif` markers; citations are rule-bearing (not endpoint-titular)
- Completeness audit: queue A 18/18 instances ≥2 tests; queue B 25/25 non-stub instances ≥1 test; 0 unknown tags; 0 shortfalls
- PRD-citation pass: all quoted strings survive verbatim grep of PRD.md (modulo whitespace); all asserted `error_id`s named in PRD prose; priority-ordering tests cite §2.9's explicit priority list; two-reader test applied (e.g., dispatch-under-lockdown accepts any state-priority error rather than hard-coding `ERR_POSTURE_RESTRICTED` when the lockdown cascade may have already cancelled the leg)
- Python syntax + smoke-import: all 25 files compile and import cleanly with a stubbed framework

Key paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/test_suite/`

## Step 6: Generate Implementation — 2026-08-10T08:31:28.878Z

Implementation complete and verified.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/workspace/implementation/`:

- `start.sh` (executable, guarded pip install, `exec python3 app.py`)
- `requirements.txt` (Flask only)
- `app.py` — Flask entrypoint, blueprint registration, error handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores + logical clock
- `errors.py` — `ApiError` + all 19 error IDs from the SCAFFOLD catalog
- `response.py` — envelope helpers matching SCAFFOLD §1.0 (`meta` / `response_type` / `data`; pagination via `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID` / `X-User-Role` extraction + role gating
- `routes/` — 9 route modules (airports, passengers, agents, requests, dispatch, incidents, invoices, tracking, util)
- `services/` — `pricing.py` (provisional/final leg charge with per-leg round-half-up, delay surcharge appended after rounding), `selectors.py` (agent + wheelchair eligibility/ranking, half-open overlap), `cascades.py` (posture ladder, ops-epoch advance, agent-suspend unassign chain, completion finalization, lockdown cascade)

**Endpoint count**: 44 routes implemented (all paths from SCAFFOLD §1.5: airports/terminals/segments, passengers, agents, wheelchairs, assist-requests, legs, dispatch, assignments, incidents, invoices, tracking, and `POST /maa/_clock/set_current_utc`).

**State handling**: Pure in-memory Python dicts (`db.airports`, `db.legs`, etc.) keyed by UUID. Nothing is seeded at startup — module-level dicts initialize empty and are populated only via the declared API surface. Confirmed by killing the dev server and re-launching via `bash start.sh`: previously-created entities return 404 on the fresh boot.

**Clock handling**: Module-level `_now_utc` in `db.py` initialized to exactly `2026-05-01T00:00:00Z` at process start (no wall-clock fallback). All business comparisons (TSA expiry, shift windows, NO_SHOW threshold, future-tracking rejection, stale-request detection) read `db.now()`. `POST /maa/_clock/set_current_utc` mutates only this logical clock; entity `created_at`/`updated_at` are also stamped from it for deterministic per-test state. Envelope `api_request_timestamp` uses wall-clock UTC (PRD §2.2 format requirement, not business logic).

**Smoke test**: Booted on a free port and ran an end-to-end script covering airport→terminal→segment→agent→wheelchair→passenger→request→leg→SUBMIT (OCC) → dispatch (selector) → ARRIVE_PICKUP → DEPART_PICKUP → ARRIVE_GATE → HANDOFF → COMPLETE (with segregation-of-duties rejection and retry) → FINAL invoice issuance → PROVISIONAL voiding → MARK_PAID → tracking ping + future-rejection. All assertions pass, including provisional=6800 / final=6800 charge math and OCC 412 on stale expected version.

## Step 7: Run Tests and Iterate — 2026-08-10T08:51:12.498Z

## Summary

**Final state: clean 8-round parallel sweep — 61/61 tests passed in every round (8 × 61 = 488/488).**

### Iterations run
3 (iteration 1: 22–26 unique failures; iteration 2: 3 remaining; iteration 3: all green, including zero recurrence of iteration-1's "server could not be restarted" infra flakes, which traced to CPU contention with a concurrent 8-round sweep of a different task on the same 8-core box).

### Tests deleted
None. Every failing test traced to a PRD-verbatim rule once its fixture/assertion was corrected.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — `setup_dispatched_assignment`: derived the default agent shift window from `clock_at_submit` (clock−1h to clock+8h) when the caller doesn't pin one. Root cause of the 5-test `ERR_NO_ELIGIBLE_AGENT` cluster: factory shift defaults were anchored to a fixed calendar day (June 16) while scenarios set the logical clock to other dates, so the PRD §3.4 in-shift eligibility check correctly rejected every dispatch.

### Fixes applied to `test_suite/` (all STEP-2 fixture/assertion faithfulness fixes)
- `test_01_provisional_vs_final_charge.py` — corrected expected charges for WCHR passengers (no `requires_wheelchair` per PRD §3.2 → no equipment fee per §3.3): 6800→6000, 9050→8250, 10375→9375.
- `test_02_provisional_charge_formula.py` — same WCHR correction: per-leg 15313→14063, request total 30626→28126 (per-leg vs sum-level rounding still diverges: 28126 vs 28125); renamed test to `..._produces_28126`.
- `test_12_calculations_corner.py` — WCHR corrections: 6800→6000 in both `TestProvisionalBaseline` and `TestOnTimeArrivalZeroDelaySurcharge`.
- `test_04_transitive_cascades.py` — `TestIncidentCriticalCascade`: passenger WCHR→WCHS so the leg actually requires a wheelchair and the chair the test observes gets checked out.
- `test_09_compensating_invariants.py` — `TestWheelchairUsageCountConserved`: same WCHR→WCHS fix (chair was never checked out for WCHR).
- `test_06_boundary_precision.py` — `TestUsageCountMaintenanceBoundary`: agent shift 00:00–23:59 (23h59m) violated PRD §3.1's 12-hour cap; narrowed to 08:00–20:00; cycle passenger WCHR→WCHS so each of the 50 cycles actually checks out the chair.
- `test_10_entities_corner.py` — `TestTrackingEventImmutable`: added `set_clock` to 09:30 before posting the event; previously `occurred_at_utc` was in the logical clock's future and the server correctly rejected it per PRD §3.9.
- `test_11_state_machines_corner.py` — `TestRetireChairInUseRejected`: passenger WCHR→WCHS so the chair is CHECKED_OUT with an in-flight assignment (the PRD §3.1 precondition for the in-use rule).
- `test_13_validations_corner.py` — `TestStaleVersionOcc`: rewrote setup to derive staleness from a PRD-sanctioned version bump (SUBMIT increments `version` per §2.7) instead of leg creation, whose version side effect PRD never states; now SUBMITs then CANCELS with the pre-SUBMIT version → `ERR_STALE_VERSION`.
- `test_17_cross_cutting_corner.py` — added missing `validate_paginated` import (NameError).

### Fixes applied to `implementation/`
- `services/pricing.py` — typo: constant defined as `UMNR_FEE_CENTS` but referenced as `UMMR_FEE_CENTS` in `_leg_flat_fees_cents` (NameError → 400 on any UMNR submit).
- `routes/requests.py` (`assist_request_event`, CANCEL branch) — moved the in-flight-assignment guard (AT_PICKUP/IN_TRANSIT/AT_GATE → `ERR_ALREADY_IN_SERVICE`) above the request-state gate, per PRD §3.10's named rejection for "attempting to cancel with such an in-flight assignment" (an assignment at AT_PICKUP has already advanced the parent to IN_SERVICE via §3.5, so the state-first order made the named error unreachable in the canonical single-leg flow).
- `routes/agents.py` (`wheelchair_event`, RETIRE branch) — check in-flight-assignment references before the MAINTENANCE from-state gate, per PRD §3.1's "attempting retirement while such a reference exists is rejected with `ERR_CHAIR_IN_USE`"; neither reordering conflicts with §2.9 (neither error is in the priority list).

## Step 8: Finalize PRD — 2026-08-10T08:56:41.180Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/workspace/PRD_FINALIZED.md` is written with exactly three inline sentence insertions and nothing else.

## Line counts
- PRD.md: 328 lines; PRD_FINALIZED.md: 328 lines; delta 0 lines (0.0%) — all three edits are in-place sentence appends within existing paragraphs (no new sections, no line-count change; only 3 lines' content changed).

## Changes (one bullet per edit)
- **§3.1** — revise — appended to the wheelchair paragraph: the `RETIRE` in-flight-reference check is evaluated **before** the `MAINTENANCE` from-state precondition, so a doubly-violating attempt (e.g. a `CHECKED_OUT` chair still referenced by an in-flight assignment) yields `ERR_CHAIR_IN_USE`, not `ERR_INVALID_STATE` — `implementation/routes/agents.py:200-205`.
- **§3.2** — revise — appended to the leg-creation paragraph: adding a service leg does not mutate the parent assist request; its `version` and `updated_at` are unchanged — `implementation/routes/requests.py:86-149` (no `db.touch(request)` in `create_leg`).
- **§3.10** — revise — appended to the request-cancellation paragraph: the in-flight-assignment check is evaluated **before** the request-state gate, so `ERR_ALREADY_IN_SERVICE` fires even when the assignment has already advanced the parent to `IN_SERVICE` per §3.5 — `implementation/routes/requests.py:284-291`.

## Step-7 items deliberately not edited into the PRD
- `services/pricing.py` `UMNR_FEE_CENTS` typo — pure impl bug; §3.3 already names the "UMNR fee … 2500 cents".
- WCHR/no-equipment-fee test corrections — §3.2 already pins `requires_wheelchair` exactly to `WCHS`/`WCHC`, §3.3 pins the fee.
- test_02 28126 vs 28125 — §2.8/§3.3 already pin per-leg rounding with no sum-level re-round; impl's Decimal per-leg round-half-up matches.
- 12-hour shift cap (§3.1) and tracking future-rejection (§3.9) — already pinned verbatim.
- `fixtures.py` shift-window derivation and test_17 import fix — test-side only.

## Per-edit pre-edit search log
1. **§3.10 CANCEL ordering.** (a) Subject: request-cancellation validation ordering / `ERR_ALREADY_IN_SERVICE`. (b) Enumerated paths: `routes/requests.py:214-312` (`assist_request_event`; sole raiser at :289 — order is OCC → DRAFT short-circuit → in-flight guard → state gate); `errors.py:28,94-95`; grep `already_in_service` across all `*.py` (no other callsites); `services/cascades.py:149-154` (`_maybe_advance_to_in_service` advances only from `ASSIGNED`, so in-flight assignments can coexist with parent `SUBMITTED` or `IN_SERVICE` — both hit the guard first); `routes/dispatch.py` MARK_NO_SHOW/CANCEL_ASSIGN (never raise it); §2.9 (error absent from the priority list — no conflict). (c) Wording scoped to the relative order of the two checks and added the `IN_SERVICE` example; no claim made about the DRAFT early-return path (a DRAFT request can never hold assignments since dispatch requires `SUBMITTED`/`ASSIGNED`, `dispatch.py:40`).
2. **§3.1 RETIRE ordering.** (a) Subject: wheelchair-retirement validation ordering / `ERR_CHAIR_IN_USE`. (b) Enumerated paths: `routes/agents.py:174-208` (`wheelchair_event`; sole raiser at :203, reference scan before the `MAINTENANCE` gate at :204); `errors.py:29,98-99`; grep `chair_in_use` (no other callsites); `SCHEDULE_MAINTENANCE`/`COMPLETE_MAINTENANCE` branches (no in-flight check — wording scoped to "a retirement attempt" so it doesn't imply one); `services/cascades.py:47-73` chair-release paths and `services/selectors.py:88-117` selection (never raise it); §2.9 (error absent — no conflict). (c) Included the `CHECKED_OUT`-with-in-flight-assignment example matching the failing test's setup; explicitly scoped to retirement.
3. **§3.2 leg-creation version silence.** (a) Subject: parent-request `version`/`updated_at` side effects of `POST /maa/assist-requests/{id}/legs`. (b) Enumerated paths: `routes/requests.py:86-149` (`create_leg` — no `db.touch(request)`); grep `touch(request` across all `*.py` confirming every site that *does* bump the parent (SUBMIT/CANCEL `requests.py:263,282,311`; dispatch `dispatch.py:86` + `cascades.py:146`; assignment events `dispatch.py:169,180,191,212,248,255` + `cascades.py:154,189,377`; settlement `invoices.py:64,72,80,111`; failure/reprice/ops bubbles `cascades.py:132,220,306,323`) — the edit asserts only a negative about leg creation, so it cannot misdescribe any of these; also cross-checked sibling create endpoints (`airports.py` terminal/segment/agent/wheelchair creates don't touch parents either — wording stays scoped to leg creation so it says nothing about them); §2.7's bump list left untouched and remains true. (c) Added `updated_at` alongside `version` to stay consistent with §2.4's common-fields contract.

## Step 9: Complete PRD — 2026-08-10T09:10:29.988Z

Done. PRD_COMPLETED.md is written with 38 inline edits. Summary below.

## File stats
- Source: `workspace/PRD_FINALIZED.md` — 328 lines, 49,129 chars
- Output: `workspace/PRD_COMPLETED.md` — 329 lines, 55,697 chars (+6,568 chars; +1 net line — all edits are in-paragraph except one new bullet in §3.4)

## Counts
- Ambiguity-pins (PRD silent → pinned impl behavior): 32
- Mismatch-revisions (PRD described different behavior → revised to impl): 6 (marked below)

## Changes (one bullet each)
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is wall-clock UTC, independent of the logical clock — `implementation/response.py:13-16`
- §2.3 — revise — mismatch — "capped at 100" → out-of-range/non-integer `limit` or bad `offset` is rejected with `ERR_BAD_REQUEST`, not clamped — `implementation/routes/util.py:12-27`
- §2.4 — insert — ambiguity — entity `created_at`/`updated_at` stamped from the logical clock — `implementation/db.py:83-97`
- §2.4 — insert — ambiguity — clock-override call responds with an object carrying `now_utc` — `implementation/routes/tracking.py:55-62`
- §2.5 — insert — ambiguity — posture body field named `posture`; self-transition or off-ladder move → `ERR_INVALID_STATE` — `implementation/routes/airports.py:67-78`
- §2.7 — insert — ambiguity — version bumps +2 when one call also advances the parent's status (dispatch→ASSIGNED, first ARRIVE_PICKUP→IN_SERVICE, final COMPLETE→finalize) — `implementation/routes/dispatch.py:85-86`, `implementation/services/cascades.py:149-154,377-378,189`
- §2.9 — insert — ambiguity — non-JSON-object body falls under format validation (`ERR_BAD_REQUEST`) — `implementation/routes/util.py:39-47`
- §2.9 — insert — ambiguity — unlisted guards (`ERR_NO_LEGS`, `ERR_POSTURE_RESTRICTED`, etc.) take per-endpoint order from §3 — n/a (structural note)
- §3.1 — insert — ambiguity — malformed/duplicate `iata_code` → `ERR_BAD_REQUEST`; `meet_buffer_minutes` integer ≥15 → `ERR_BAD_REQUEST` — `implementation/routes/airports.py:32-42`
- §3.1 — insert — ambiguity — duplicate terminal `code` → `ERR_BAD_REQUEST` — `implementation/routes/airports.py:104-106`
- §3.1 — insert — ambiguity — segment `terminal_id` unresolved/cross-airport → `ERR_BAD_REQUEST`; optional `international` boolean defaulting to false — `implementation/routes/airports.py:158-173`
- §3.1 — insert — ambiguity — segment-event from-states (`LANDED`/`DEPARTED` only from `SCHEDULED`; `CANCELLED` from any non-`CANCELLED`); missing `actual_utc` → `ERR_BAD_REQUEST` — `implementation/routes/airports.py:222-235`
- §3.1 — insert — ambiguity — duplicate `asset_tag` → `ERR_BAD_REQUEST` — `implementation/routes/agents.py:125-127`
- §3.1 — revise — mismatch — "manual chairs are never WCHC-rated" is not enforced at creation; flag accepted as supplied, manual chairs merely never eligible for WCHC legs — `implementation/routes/agents.py:128-140`, `implementation/services/selectors.py:98-102`
- §3.1 — insert — ambiguity — `SCHEDULE_MAINTENANCE` (AVAILABLE→MAINTENANCE) / `COMPLETE_MAINTENANCE` (MAINTENANCE→AVAILABLE, resets `usage_count`, stamps `last_maintenance_utc`) lifecycle — `implementation/routes/agents.py:184-195`
- §3.2 — insert — ambiguity — `dob` strict `YYYY-MM-DD`; class thresholds (<18 UMNR, ≥65 SENIOR, else ADULT by full years); billing instruments optional/null — `implementation/routes/passengers.py:19-48`
- §3.2 — insert — ambiguity — unresolvable `passenger_id` → `ERR_BAD_REQUEST`; `companion_count` non-negative integer; `umnr_handoff_required` stored but gates nothing — `implementation/routes/requests.py:30-40`
- §3.2 — insert — ambiguity — unresolvable `segment_id` → `ERR_REFERENTIAL_INTEGRITY`; `pickup_zone` free-form non-empty string; `onward_leg_id` on non-CONNECTION_TRANSFER → `ERR_REFERENTIAL_INTEGRITY` — `implementation/routes/requests.py:94-113`
- §3.2 — insert — ambiguity — `scheduled_pickup_utc = scheduled_utc + meet_buffer_minutes` (sign pinned) — `implementation/routes/requests.py:119`
- §3.3 — revise — mismatch — submit precondition order pinned to impl: OCC → DRAFT state → no-legs → payment → posture (PRD had listed OCC third) — `implementation/routes/requests.py:222-245`
- §3.3 — insert — ambiguity — `LOCKDOWN` posture multiplier = 10000 bp (recomputation paths only) — `implementation/services/pricing.py:63,77`
- §3.3 — insert — ambiguity — provisional invoice's `created_by_user_id` records the submitting requester's `X-User-ID` — `implementation/routes/requests.py:274`
- §3.4 — insert — ambiguity — TSA precheck "candidate agent" = ACTIVE, in-shift, homed at the leg's airport — `implementation/services/selectors.py:73-85`
- §3.4 — insert — ambiguity — agent-eligibility bullet: agent must belong to the leg segment's airport — `implementation/services/selectors.py:43-44`
- §3.4 — revise — mismatch — `ERR_WCHC_CHAIR_REQUIRED` is never raised by dispatch; non-qualifying chairs are filtered out, empty pool → `ERR_NO_AVAILABLE_WHEELCHAIR` — `implementation/services/selectors.py:98-105`
- §3.4 — revise — mismatch — dispatch version bump is +2 when it advances the request to `ASSIGNED` (was "by one") — `implementation/routes/dispatch.py:85-86`
- §3.5 — revise — mismatch — LOCKDOWN gate applies only to the four agent field events; `COMPLETE`/`MARK_NO_SHOW`/`CANCEL_ASSIGN` carry no posture gate; per-event role restriction with `ERR_UNAUTHORIZED` for wrong role or foreign assignment — `implementation/routes/dispatch.py:138-152,157-158,174-175,185-186,196-197`
- §3.5 — insert — ambiguity — missing `umnr_second_signoff_user_id` → `ERR_SEGREGATION_OF_DUTIES` — `implementation/routes/dispatch.py:199-202`
- §3.5 — insert — ambiguity — `cumulative_delay_minutes` overrun truncated down to whole minutes — `implementation/services/cascades.py:351-356`
- §3.5 — insert — ambiguity — onward-leg recompute skipped when onward leg is terminal; request-level `provisional_charge_cents` not recomputed there — `implementation/services/cascades.py:365-375`
- §3.6 — insert — ambiguity — delay minutes truncated down to whole minutes before grace — `implementation/services/pricing.py:87-89`
- §3.6 — revise — mismatch — `DISPUTE` guards on `OPEN` status only; an `OPEN` provisional invoice is disputable — `implementation/routes/invoices.py:66-72`
- §3.6 — revise — mismatch — write-off SOD compares against provisional invoice's `created_by_user_id` (the submitting requester), not "the clerk who created" it — `implementation/routes/invoices.py:85-95`
- §3.6 — insert — ambiguity — baseline recorded on the invoice's `writeoff_baseline_cents` field — `implementation/routes/invoices.py:107`
- §3.7 — insert — ambiguity — lockdown cascade also cancels in-flight assignments of cancelled legs and decrements agents' `active_assignment_count` — `implementation/services/cascades.py:232-241`
- §3.7 — insert — ambiguity — epoch NO_SHOW side effects (chair release, count decrement, leg marked `NO_SHOW` when siblings terminal, request FAILED with invoice void + billing UNBILLED) — `implementation/services/cascades.py:271-306`
- §3.7 — insert — ambiguity — stale detection mechanics: `ops_epoch` snapshot at submit, fail when epoch advanced ≥2; stale failure voids provisional invoice and returns billing to `UNBILLED` — `implementation/services/cascades.py:308-323`, `implementation/routes/requests.py:256-262`
- §3.8 — insert — ambiguity — unresolvable `assignment_id` on incident open → `ERR_BAD_REQUEST` — `implementation/routes/incidents.py:23-25`
- §3.8 — insert — ambiguity — `SUSPEND` valid only from `ACTIVE`, `REINSTATE` only from `SUSPENDED` (else `ERR_INVALID_STATE`) — `implementation/routes/agents.py:96-108`
- §3.8 — insert — ambiguity — ADJUSTMENT credit rounded to nearest whole cent and carried as negative `amount_cents` — `implementation/routes/incidents.py:91-103`
- §3.9 — insert — ambiguity — unresolvable `tracking_token` → `ERR_BAD_REQUEST`; token possession alone authorizes publication (no agent-identity check) — `implementation/routes/tracking.py:19-28`
- §3.10 — insert — ambiguity — request-cancel cascade releases chairs without decrementing `usage_count` and decrements agents' `active_assignment_count` — `implementation/routes/requests.py:293-295`, `implementation/services/cascades.py:97-111`
- §3.10 — insert — ambiguity — no-show bubble marks the leg `NO_SHOW`, voids the provisional invoice, returns billing to `UNBILLED`; leg stays `DISPATCHED` while siblings are non-terminal — `implementation/routes/dispatch.py:221-248`
- §3.10 — insert — ambiguity — direct `CANCEL_ASSIGN` bubbles the request to `FAILED` (invoice void, billing UNBILLED) when all legs are `CANCELLED`/`FAILED` — `implementation/routes/dispatch.py:253-254`, `implementation/services/cascades.py:114-132`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair/workspace/PRD_COMPLETED.md`.
