# Worklog — task_0007_airline_crew_scheduling

## Step 1: Create task directory — 2026-05-26T00:00:00Z

Created `tasks/task_0007_airline_crew_scheduling/` and `tasks/task_0007_airline_crew_scheduling/workspace/` (pre-allocated path supplied by user; no ID scan).

## Step 2: Generate scaffold — 2026-05-26T03:52:00Z

All three files written.

**Lint verdict** (final): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (460 calls scanned across 18 §1.8 + 19 §1.9 instances; 37 §1.5 endpoints; 8 §1.1 entities)

**SCAFFOLD.yaml** (§1.0–§1.7 + complexity profile)

- **Complexity profile**: temporal_windowing primary + compliance_audit secondary; hybrid topology; branching state-machine shape; peer_roles RBAC; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, selector_policy
- **Entities (8)**: CrewMember, Pairing, FlightLeg, Bid, Assignment, SickCall, ReserveCallup, TripTrade
- **State machines (5)**: Pairing (DRAFT→BID_OPEN→BID_CLOSED→AWARDED→IN_PROGRESS→COMPLETED + CANCELLED branches), Assignment (SCHEDULED→CONFIRMED→ACTIVE→COMPLETED + RELEASED/RECOVERED branches), SickCall (REPORTED→ACKNOWLEDGED→CLOSED), ReserveCallup (OFFERED→ACCEPTED/DECLINED cycle), TripTrade (PROPOSED→COUNTERSIGNED→APPROVED→EXECUTED + REJECTED/WITHDRAWN branches)
- **Calculations (5)**: pairing_duty_window, rolling_duty_window (variants: completed_actual vs preview_with_candidate), crew_rest_interval, pairing_credit_block (variants: scheduled_estimate vs actual_block), reserve_selector
- **Validations (17)**: priority-ordered from auth → existence → state → cross-entity state → FAA duty/flight caps → crew rest → rank-seat → temporal → overlap → uniqueness → OCC → required fields
- **Endpoints (37)**: CRUD + actions for all entities, plus `/_clock/set_current_utc` test-driving endpoint
- **Errors (16)**: ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_CROSS_ENTITY_STATE, ERR_FAA_DUTY_CAP_EXCEEDED, ERR_FAA_FLIGHT_CAP_EXCEEDED, ERR_CREW_REST_VIOLATION, ERR_RANK_SEAT_MISMATCH, ERR_INVALID_TIME_WINDOW, ERR_PAIRING_OVERLAP, ERR_LEG_OVERLAP, ERR_DUPLICATE_BID, ERR_STALE_VERSION, ERR_NO_RESERVE_AVAILABLE, ERR_INVALID_REQUEST
- **Roles (3)**: SchedulingPlanner (opaque), OperationsController (opaque), CrewMember (entity_backed:CrewMember)
- **Concurrency rules (2)**: trade-execute-stale-pairing (TripTrade.version OCC), pairing-award-stale-version (Pairing.version OCC)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8)
- **18 instances** total across 9 §0.5 rule_ids (2 each): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9)
- **22 instances** total across 9 sections: entities (5), state_machines (4), calculations (2), validations (2), endpoints (1), errors (2), rbac (3), cross_cutting_complexity_layers (2), consistency_model (1) — includes 3 `excluded_because:` stubs referencing §1.8 instances

## Step 3: Copy INSTRUCTION.md — 2026-05-26T03:53:00Z

Copied `./INSTRUCTION.md` → `tasks/task_0007_airline_crew_scheduling/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-26T03:59:00Z

**Output written**: `workspace/PRD.md`

**Document stats**: 288 lines, 6,417 words.

**Section structure**:
- §1 Introduction (3 paragraphs — system goals, organizing concepts, consistency model)
- §2 Global Specifications (12 subsections, domain-derived titles):
  - 2.1 RBAC, 2.2 Response Structure (fixed verbatim), 2.3 Pagination
  - 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval
  - 2.6 Logical Clock and Time-Driven Auto-Transitions
  - 2.7 FAA Duty and Flight Caps, 2.8 Crew Rest Minimum Interval
  - 2.9 Validation Priority Order, 2.10 OCC
  - 2.11 Cascading Side Effects, 2.12 Integer-Minute Precision and Boundary Inclusivity
- §3 Business Logic & Workflows (6 subsections, mixed lifecycle + cross-cutting strategy): Pairing Lifecycle → Crew/Bidding → Assignment Confirmation → SickCall+Reserve Recovery → Trip Trades → Trade Overlap
- §4 Endpoint table (4 columns, 37 rows)
- §5 Error table (2 columns, 16 errors)

**Scattering decisions**:
- Trade-execute's `expected_trip_trade_version` parameter introduced in §2.10 OCC, but the surrounding workflow (the four-stage trade lifecycle, the seat/rank guard, the half-open overlap rule) is distributed across §3.5 and §3.6.
- Pairing-award's `expected_pairing_version` declared in §2.10, while the seniority tie-break and bid-pool coverage rule live in §3.1.
- FAA cap constants embedded as "60 hours of duty" / "30 hours of flight" / "10 hours" rather than raw minutes — readers must connect prose to scaffold's `FAA_DUTY_CAP_7D_MIN: 3600` etc.
- Validation priority (1–17) consolidated in §2.9 since the order spans multiple endpoints, but each error_id is also restated in the workflow that triggers it.
- Reserve `MAX_CALLUP_ATTEMPTS: 5` written as "cannot grow beyond 5" inside the decline narrative.
- Rank↔seat compatibility table written into §3.2 (bidding) and re-triggered in §3.5 (trade approval).
- FlightLeg flight_minutes floor formula tucked into §3.1's leg paragraph, not in a separate calculations section.

**Hard Contracts**: Field coverage PASS, Rule coverage PASS, Path purity PASS.

## Step 5: Generate unit tests — 2026-05-26T04:14:00Z

**Helpers** (`test_helpers/`): `__init__.py` (116), `api_client.py` (182), `api_errors.py` (46), `assertions.py` (149), `constants.py` (16), `factories.py` (126), `fixtures.py` (615), `test_users.py` (40), `types.py` (225).

**Tests** (`test_suite/`): 13 files, **55 tests total**.
- test_01_entities_and_inputs.py (6)
- test_02_pairing_lifecycle.py (5)
- test_03_bidding_and_award.py (2)
- test_04_assignment_confirmation.py (4)
- test_05_calculations_dual_variant.py (5)
- test_06_cascades_and_workflows.py (2)
- test_07_trip_trade_flow.py (3)
- test_08_reserve_callup_flow.py (3)
- test_09_invariants_and_compensation.py (2)
- test_10_concurrency_and_versioning.py (2)
- test_11_rbac_and_auth.py (4)
- test_12_listing_and_consistency.py (1)
- test_13_difficulty_followups.py (16)

**Coverage**: Difficulty Queue A — all 18 instances × 2 tests = 36; Corner Queue B — 19 non-stub instances × 1 test = 19. All 3 `excluded_because:` stubs cross-reference real Difficulty instances; no placeholder tests emitted. No instances skipped via PRD-first filter. Every test docstring ends with one verbatim `Design: …` tag.

## Step 6: Generate implementation — 2026-05-26T05:31:00Z

**Test result self-reported**: 55/55 passed under `prd-bench-local-run --isolation per-test-server` (~5 min wall-clock; ~5 s per restart).

**Files (line counts)**: `start.sh` (12), `requirements.txt` (1, Flask==3.0.3), `app.py` (97), `db.py` (40), `errors.py` (92), `response.py` (69), `middleware.py` (31), `routes/crew_members.py` (102), `routes/pairings.py` (404), `routes/bids.py` (126), `routes/assignments.py` (82), `routes/sick_calls.py` (305), `routes/trip_trades.py` (311), `routes/clock.py` (27), `routes/common.py` (43), `services/constants.py` (51), `services/calc.py` (153), `services/cascade.py` (114), `services/entity.py` (22), `services/validate.py` (60), `services/timeutil.py` (33). Total: 2,175 lines.

**Endpoints**: 37 (CrewMember 3, Pairing 8, FlightLeg 2, Bid 4, Assignment 3, SickCall 4, ReserveCallup 4, TripTrade 8, clock 1).

**State machines wired**: Pairing, Assignment, Bid, SickCall, ReserveCallup, TripTrade (all with cascades and clock-driven auto-transitions).

**Calculations**: pairing_duty_window, scheduled_block_minutes, actual_block_minutes (averaging), crew_rolling_totals (completed_actual persisted vs preview), crew_rest_interval, reserve_selector, FlightLeg flight_minutes floor.

**Validations**: priority-ordered 1–17 enforced (auth → forbid → not_found → state → cross-entity → FAA caps → rest → rank-seat → time-window → pairing-overlap half-open → duplicate-bid → leg-overlap closed → stale-version OCC → no-reserve → schema).

**Key implementation note**: `_ReusePortServer(ThreadedWSGIServer)` subclass in `app.py` sets `SO_REUSEADDR + SO_REUSEPORT` to survive per-test-server restarts on macOS without TIME_WAIT delays.

**Launcher**: `start.sh` foreground via `exec python3 app.py` on `0.0.0.0:$PORT`.

## Step 7: Run tests and iterate — 2026-05-26T05:52:00Z

- Iterations run: 1 (initial 8-round parallel sweep)
- All 8 parallel rounds: 55/55 passed, 0 failed (440/440 test executions total)
- Tests deleted: none required
- Fixes applied to `test_helpers/`: none required
- Fixes applied to `implementation/`: none required

Result files written: `workspace/implementation/results.{1..8}.json` (all green).

## Step 8: PRD finalization — SKIPPED — 2026-05-26T05:52:00Z

Step 7 exited on the first 8-round sweep with **0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes**. Per Step 8's skip condition: `PRD.md` already uniquely determined every behavior the implementation exhibits, so no finalization patch is needed. `PRD_FINALIZED.md` is not generated.
