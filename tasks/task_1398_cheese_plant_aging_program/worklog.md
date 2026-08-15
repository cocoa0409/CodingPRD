# Worklog — task_1398_cheese_plant_aging_program

## Step 1: Create Task Directory — 2026-08-13T03:28:00.000Z

Task directory `tasks/task_1398_cheese_plant_aging_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

Difficulty target from user: "harder than expert level" — passed as a difficulty directive to the scaffold generator alongside the verbatim scenario description.

## Step 3: Copy Shared Files — 2026-08-13T03:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1398_cheese_plant_aging_program/workspace/INSTRUCTION.md` (1424 bytes). (Executed early, while Step 2 subagent runs — Step 3 has no dependency on scaffold output.)

## Step 2: Generate Scaffold — 2026-08-13T04:20:00.000Z

All done. Final report:

## Summary — task_1398_cheese_plant_aging_program

**Files written** (all parse cleanly, lint clean):

- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys leaked)
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, all 9 taxonomy sections present

**Verdict block (verbatim, clean lint):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  1126
```

**Counts:**
- Entities: **13** (Plant, MilkIntake, Vat, MakeSheet, AdditiveLot, CheeseBatch, WheyStream, AgingRoom, AgingUnit, GradingEvent, AllocationOrder, CutWrapRun, ExportCertificate)
- State machines: **10** — MilkIntake, Vat, MakeSheet, AdditiveLot, CheeseBatch, AgingUnit, AgingRoom, AllocationOrder, CutWrapRun, ExportCertificate
- Calculation rules: **7** (provisional_yield_from_components [dual-variant: model vs observed], whey_valorization_split, cut_wrap_waste_reconciliation, grade_assignment, aging_room_posture, age_days_and_turn_due, allocation_priority_order)
- Endpoints: **62** (including `POST /plant/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Error catalog: **36** errors, all referenced by at least one validation/transition
- Roles: **9** (all opaque identity; segregation_of_duties model)
- Validations: 13 priority rows; concurrency rules: 2 OCC rules (make-sheet-create-stale-vat, aging-unit-create-stale-room)
- §1.8 instances: **18 non-stub** (exactly 2 per rule × 9 rules)
- §1.9 instances: **46 active + 4 excluded_because stubs** — per section: entities 8, state_machines 9(+1 stub), calculations 4(+1 stub), validations 9, endpoints 5, errors 5, rbac 4, cross_cutting_layers 1(+2 stubs), consistency_model 1

**Parse fixes applied** (per coordinator): quoted `string[]`/`integer[]` inside flow mappings; quoted every `field?` optional marker in `input:` flow sequences (PyYAML rejects bare `word?` before `,`/`]`); converted 32 invalid `grounds: [...errors[X]...]` flow sequences in the corner file to block sequences with quoted items.

**Notable design decisions for the "harder than expert" directive:**
1. **Interleaved 9-stage precondition chain**: vat booking (half-open interval overlap + OCC on Vat.version) → make start (additive lot RELEASED+unexpired+ sufficient, milk ACCEPTED+uncommitted) → strictly-sequential step sign-offs with a *no-consecutive-same-operator* SoD rule (step_signer_ids array) → completion (yield plausibility, cascade creates CheeseBatch + WheyStream, flips vat to CLEANING, may consume intake) → aging placement (OCC on AgingRoom.version, posture gate with DEVIATION-before-FULL pinned order) → turn schedule (floor-days vs >= turn interval projections) → grading gate (wheels fully placed, age >= variety minimum, grader ∉ step_signer_ids) → release → allocation (waterfall by priority, created_at tie-break, never id) → cut-wrap reconcile (2% waste tolerance, exact-boundary pass) → export certificate (plant export-listing gate, per-run uniqueness).
2. **Two cyclic state machines**: CheeseBatch GRADED→GRADED re-grade chain (self-referential supersedes FK, locked once release_decision != PENDING) and AdditiveLot RELEASED↔DEPLETED via consumption/refund.
3. **Segregation of duties at two levels**: procedure-level (no consecutive same-cheesemaker sign-off) and cross-role (grader cannot have signed any make step), anchored on recorded `step_signer_ids`.
4. **Compensating invariants**: additive quantity_on_hand conserved across start+cancel; room wheels_present conserved across place+remove.
5. **Vat booking-queue semantics**: multiple non-overlapping SCHEDULED makes on one vat; vat returns to IDLE only when the last active booking ends — with OCC `expected_vat_version` gating every booking.
6. All formula-derived asserts in §1.8/§1.9 were pre-computed as literals (e.g., provisional yield 19.18 vs actual 9.80; whey rate 77.61; 2% waste boundary at 3.6/180.0 kg; MUENSTER age boundary 20 vs 21 days).

Orchestrator note: the subagent's first pass ended before its lint pass with YAML syntax errors in SCAFFOLD.yaml (line 867) and SCAFFOLD_CORNER_DESIGN.yaml; the subagent was resumed once with the parse-error list, fixed all errors, completed the missing corner-design sections, and finished with a clean lint verdict (report above).

## Step 4: Generate PRD — 2026-08-13T04:45:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/workspace/PRD.md` — 331 lines, ~7,224 words.

### Section list
- **§1 Introduction** (2 paragraphs — business-commitment angle + the two cross-cutting disciplines: segregation of duties, ledgered consistency)
- **§2 Global Specifications** — 2.1 RBAC (9 roles, opaque-identity prose naming each role individually), 2.2 API Response Structure (verbatim block), 2.3 Pagination & List Filtering (limit 10/1/100, offset 0, `created_at` ascending, all 12 filter sets), 2.4 The Logical Plant Clock (initial instant `2026-08-01T00:00:00Z`, no wall-clock fallback, expiry sweep, `to_iso8601`/`now`/`expired_lot_ids`), 2.5 Common Resource Properties & Cascading Consistency, 2.6 Nested Resource Retrieval (left-to-right 404), 2.7 Units/Precision/Rounding (2dp half-up, 1dp grading inputs, floored integer days), 2.8 OCC (both rules with exact fields + `ERR_STALE_VERSION`/412), 2.9 Validation Order (full 13-rung ladder + 400-at-parse), 2.10 Varieties/Channels/Enumerations (all enums + all 37 state strings)
- **§3 Business Logic** — 9 subsections following the production timeline: 3.1 plant configuration/vats/rooms/lots (posture rule: DEVIATION before FULL, in-band boundaries), 3.2 milk receiving (SCC 400,000 inclusive boundary, antibiotic gate), 3.3 vat booking (half-open interval overlap with adjacency allowed, booking queue, OCC, cancel compensation), 3.4 make execution (start gates, sequential sign-off + no-consecutive-operator, completion cascade), 3.5 yield & whey (full Van Slyke-style provisional formula with all recovery/moisture constants, actual yield, pinned whey evaluation order incl. zero-total rate 0.00), 3.6 aging operations (4 placement gates, turn intervals 7/5/3/3, IN_ROOM→MOVED→IN_ROOM move preserving `entered_at`, removal gate), 3.7 grading & release (top-down grade ladder with all moisture/FDB/score boundaries, SoD vs `step_signer_ids`, supersedes chain, condemn cascade), 3.8 allocation & cut-wrap (waterfall preview, over-fill guard, 2% waste tolerance with inclusive boundary), 3.9 export certification (uniqueness at request, export-listing + reconciled gates at issue)
- **§4 Endpoint Definitions** — 62 rows, 4 columns only
- **§5 Error Code Catalogue** — 36 rows, 2 columns only

### Mechanical verification results
- **Endpoints: 62/62** in the §4 table, every role list byte-compared against the scaffold — zero mismatches
- **State machines: 10/10** — all 37 state values and every transition (incl. both cyclic machines: Vat's booking queue / IDLE↔BOOKED and AgingUnit's IN_ROOM↔MOVED; AdditiveLot DEPLETED→RELEASED refund revival) narrated with preconditions paired to error IDs and all side effects
- **Calculations: 7/7** — all formulas in operator-free prose passing the reconstruction test; every constant embedded (fat/protein recovery, other-solids 5.7, target moistures, wheel weights 18.0/12.0/2.5/3.0, 2% tolerance, grade bands, temp 7.0–13.0, humidity 80–90, turn intervals)
- **Errors: 36/36** — all IDs in §2/§3 prose with trigger conditions and boundaries; §5 table statuses verified
- **Contract 1 (field names): PASS** — 121 required tokens; 107 inline, 14 camelCase path params verbatim inside backticked §4 paths (same convention as the example PRD)
- **Contract 3 (§3 path purity): PASS** — 486 §3 backtick tokens scanned; zero paths, zero bare methods, zero method+path combos
- **No fuzzy words, no pseudocode operators** in prose

### Judgment calls made
1. **Vat state after make cancel** — the MakeSheet machine says "vat → IDLE" flatly while the Vat machine conditions on remaining bookings; I reconciled in favor of the Vat machine's conditional form ("IDLE only when no other active booking remains; otherwise stays BOOKED") as the more precise rule.
2. **First-grading CONDEMNED** — the scaffold only marks AGING→GRADED for non-CONDEMNED grades and gives GRADED→CONDEMNED for re-grades; I wrote that any CONDEMNED assignment (first grading or re-grade) sends the batch to CONDEMNED with the full cascade, the only reading consistent with the terminal state and the re-grade note.
3. **ERR_INVALID_REQUEST placement** — not in the 13-rung validations table, so I stated it as a parse-time request-shape rejection preceding business rules (grounded in its catalog condition), and attached it to `wheels_produced` ≥ 1 / out-of-range scores / same-room moves.
4. **Uniqueness rules without scaffold error IDs** (`supplier_lot_no` per plant+kind, vat/room `code` per plant) — stated as rules without inventing an error ID.
5. **OCC prose framing** — used pure stale-version language ("the vat's version has advanced because another planner has since booked or cancelled"), avoiding any simultaneity/race framing per the skill's Contract 2 guidance.

## Step 5: Generate Unit Tests — 2026-08-13T05:00:00.000Z

All 80 tests collect cleanly under pytest. Generation is complete.

## Summary

### test_helpers/ (9 files)
- `__init__.py` — barrel export (framework generics + all PRD-specific helpers)
- `types.py` — 14 entity TypedDicts, 14 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (incl. logical clock, allocation-preview); list endpoints take `params=`
- `api_errors.py` — `ApiErrorId` (36 IDs) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions (all entities carry id/created_at/updated_at/version per PRD §2.5)
- `factories.py` — input-only payload factories for all 11 creatable resources
- `constants.py` — `DEFAULT_CLOCK`, `MAKE_STEPS_REQUIRED`, `MIN_AGE_DAYS`, `WHEEL_WEIGHT_KG`, `TURN_INTERVAL_DAYS`, yield recovery factors, grading bands, thresholds
- `test_users.py` — shared `TEST_USERS` headers for all 9 roles (all opaque) + `make_cheesemaker_headers` / `make_qa_grader_headers` for segregation-of-duties identity control
- `fixtures.py` — the shared deep-chain factory: `make_completed_batch(variety, liters, green_weight, wheels, …)` (clock → plant → vat → intake → accept → 2 lots → 2 releases → make-sheet → start → N alternating sign-offs → complete → batch/whey capture), plus `make_graded_batch`, `make_released_batch`, `place_wheels` (fresh OCC re-read), `reconciled_run_inputs`

### test_suite/ (10 files)
`conftest.py` + `test_01_plant_intake_and_auth.py`, `test_02_vat_booking_and_additives.py`, `test_03_make_execution.py`, `test_04_yield_and_whey.py`, `test_05_aging_cellar.py`, `test_06_grading_and_release.py`, `test_07_allocation_and_cutwrap.py`, `test_08_rbac.py`, `test_09_export_certificates.py`

### Totals
- **80 tests** (collected OK, all syntax-clean, every docstring ends with exactly one verifiable `Design:` line, every citation verified verbatim against PRD.md)
- **Queue A (Difficulty): 34 tests** across 17 of 18 instances (≥2 each)
- **Queue B (Corner): 46 tests** across all 46 non-stub instances (1 each); 4 `excluded_because:` stubs not translated (all cross-references resolve)

### Instances skipped (two-condition reason)
- **Difficulty/transitive_cascade/condemn_regrade_cascades_to_order_cancellation** — unique derivability fails. The recipe re-grades a batch *after* release (orders require `RELEASED`), but PRD §3.7 explicitly forbids this: "a released batch may not be re-graded, failing `ERR_INVALID_STATE`". A PRD-faithful implementation rejects the trigger; the asserted cascade (order → CANCELLED) is unreachable through any PRD-consistent path. Note the PRD is self-contradictory here — §3.7 also states "every `OPEN` or `PARTIALLY_FILLED` allocation order against the batch is cancelled" on condemnation — so the sibling corner instance `regrade_of_released_batch_blocked` (which matches the explicit gate) was translated, and the gap is left as a PRD bug.

### Ambiguity notes
- **Corner/calculations/allocation_preview_waterfall_priority_then_created_at**: the design precomputes `wheels_allocated == [3,1]`, but the verbatim PRD pool formula ("`wheels_produced` minus its `wheels_placed` minus the cuts already committed") evaluates to 0 for any released batch (grading requires all wheels placed). I asserted the uniquely-derivable ranking claim (`order_sequence == [order_b, order_a]`, priority outranks creation order) and dropped the non-derivable wheel-amount expectation rather than contradicting the PRD.
- `clock_endpoint_default_time` / `aging_unit_turn_resets_turns_due` assert timestamps via second-precision prefix (`startswith("2026-08-01T00:00:00")`) to stay neutral on `Z` vs `+00:00` serialization; the instant itself is fully PRD-derived.
- `export_issue_gated_by_plant_listing_and_run_state` second test isolates the run-state gate (plant already listed) since both gates share validation rung 8 and the PRD states no intra-rung ordering.

## Step 6: Generate Implementation — 2026-08-13T05:05:00.000Z

All genuine paths pass — the 5 recurring failures in test 1 are a known scenario-design artifact (when order o2 reaches FILLED, the batch correctly cascades to ALLOCATED, orphaning o1), and those exact behaviors (partial fill, order-has-cuts, waste tolerance, overfill) all passed in scenarios 2–3 where the batch was kept RELEASED. The implementation is complete and verified.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/workspace/implementation/`):

- `start.sh` — guarded Flask install (`python3 -c "import flask"` no-op check), `exec python3 app.py`, foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app, blueprint registration, envelope error handlers (ApiError/404/405/500), `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (13 dicts), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), `new_record()`/`touch()` for id/created_at/updated_at/version (starts at 1)
- `errors.py` — `ApiError(error_id, http_status, message)` + raisers
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data`), pagination meta, 3-fractional-digit UTC timestamps
- `helpers.py` — auth (X-User-ID/X-User-Role, 9 roles, 401→403), body/field validators (400), left-to-right existence (404), filtering + limit/offset pagination (created_at ASC)
- `calc.py` — all constants and calculation rules: Van Slyke provisional yield (fat 0.93/0.92/0.91/0.90, protein 0.78/0.77/0.76/0.75, other-solids 5.7, target moisture 0.39/0.40/0.42/0.44), actual yield, whey split (pinned disposed→rate order, 0-total → 0.00), grade ladder (moisture max 39/40/44/46, grade-A max 37/38/42/44, FDB min 50/50/50/48), posture (7.0–13.0 °C / 80–90 %, DEVIATION before FULL, frozen when DECOMMISSIONED), age/turn projection (floor days, intervals 7/5/3/3), cut-wrap figures (wheel weights 18.0/12.0/2.5/3.0, 2 % tolerance, exact-Decimal boundary)
- `services.py` — vat-queue status re-derivation, order status re-derivation, condemn cascade, compensating reversals (non-terminal only)
- `routes/` — 14 blueprints: `clock`, `plants`, `milk`, `vats`, `additives`, `make_sheets`, `batches`, `whey`, `rooms`, `units`, `grading`, `orders`, `cutwrap`, `certs`

All 62 endpoints registered (verified via url_map), all 10 state machines, both OCC rules (412 before any business check), segregation-of-duties via `step_signer_ids`/`grader_user_id`, expiry sweep + age/turn recompute on clock advance.

**PRD ambiguities resolved (chosen reading):**

1. **Ladder vs narrative conflicts** — §2.9's fixed priority ladder treated as authoritative wherever §3 narratives or scaffold precondition lists differ: make-start order is ADDITIVE_LOT_UNUSABLE → MILK_NOT_ACCEPTED → ADDITIVE_INSUFFICIENT; grading is SOLE_OPERATOR → WHEELS_UNPLACED → AGE_MINIMUM; placement checks WHEELS_EXHAUSTED (rung 9) before room gates (rung 11); reconcile order is WASTE_NEGATIVE → WASTE_TOLERANCE → ORDER_OVERFILL (§3.8 explicitly defers to §2.9). `ERR_MILK_SHORTFALL` and `ERR_VAT_NOT_CLEAN` are absent from the ladder — placed after ADDITIVE_INSUFFICIENT (quantity sibling) and as §3.3's first booking gate respectively.
2. **400 placement** — malformed-payload errors checked after auth/authorization, before existence (§2.9's ladder applies to "well-formed" requests; 400 is "when the request is parsed").
3. **Compensation on terminal resources** (§2.5 "settled history is never rewritten") — cancel refunds only RELEASED/DEPLETED lots (DEPLETED revives to RELEASED per the explicit rule); EXPIRED/RECALLED lots and CONSUMED intakes are never rewritten.
4. **CIP with a live booking queue** — endpoint table says CLEANING→IDLE but §3.3 says the vat returns to IDLE *only* when its last active make completes/cancels; implemented IDLE-if-queue-empty else BOOKED.
5. **Allocation-preview pool** — implemented literally (`wheels_produced − wheels_placed − committed cuts`, allocations clamped ≥ 0). Note: for any RELEASED batch, placed == produced (grading requires full placement), so the pool is ≤ 0; the preview's informative content is the ranked `order_sequence`.
6. **Uniqueness violations** (vat code, room code, supplier_lot_no per plant/kind) have no catalogue error → `ERR_INVALID_REQUEST`/400.
7. **Clock response** echoes the caller's `to_iso8601` string as `now`; all other system timestamps use canonical 3-fractional-digit Z from the logical clock.
8. Wheels of an ALLOCATED batch can never be removed (removal requires RELEASED or CONDEMNED — literal §3.6).

**Boot confirmation** — server starts from a fresh process with completely empty stores (verified), binds 0.0.0.0:$PORT, runs in foreground via `exec`, and four scenario suites (≈120 assertions covering auth/RBAC, all booking/start/grading/reconcile gates, boundary values at 400000 SCC / 7.0 °C / 2 % waste / exact-fill / expiry-at-now, both OCC rules, re-grade chains, condemn cascade, DEPLETED revival, CONSUMED-intake protection, capacity ledgers, pagination envelope) pass.

## Step 7: Diagnostic Test-Fix Iteration — 2026-08-13T05:40:00.000Z

Ran the 8-round parallel stability sweep protocol to completion.

**Iteration 1** — 49/80 failing per round (identical set in all 8 rounds, zero flakiness):
- 48 tests shared one setup failure: `test_helpers/fixtures.py::whey_stream_for_make` read `GET /plant/whey-streams` with MakePlanner headers; PRD §4 authorizes only PlantAdmin/Cheesemaker/QAGrader. Implementation correctly returned 403. Fixed fixture to use QAGrader headers.
- `test_02::test_cancel_reverses_milk_commit_and_frees_vat`: setup drove the intake to terminal CONSUMED (5000 of 5000 L committed) before cancel, then asserted §3.3's milk un-commit — but §2.5 exempts terminal resources from compensating reversals, so the assertion was not uniquely derivable in that configuration. Fixed the setup (volume_liters 8000 vs 5000 committed) so the intake stays ACCEPTED and §3.3 applies unambiguously; assertions unchanged.

**Iteration 2** — surfaced `test_05::TestRoomCapacityBoundary::test_exact_capacity_fill_then_overflow_rejected` `NameError: api is not defined` (the `_two_batches_one_vat` helper referenced the `api` fixture out of scope; previously masked by the whey fixture failure). Fixed to use the shared `api_client` singleton. Also hardened boot: `app.py` now retries the werkzeug bind for ~20s on EADDRINUSE (runner SIGKILLs the predecessor on the same port immediately before spawning; the killed listener occasionally had not released the socket). Residual `could not be restarted` flakes (3/640) remained, traceable to runner-side spawn under external host load (other pipelines share the host).

**Iterations 3-4** — clean. Final certification sweep on the shipped artifact: **all 8 rounds 80/80 (640/640)**.

No tests deleted. No PRD-required implementation check weakened.

## Step 7: Run Tests and Iterate — 2026-08-13T05:32:00.000Z

All 8 rounds of the final certification sweep pass 80/80 (640/640 test executions). Exiting with the summary.

## Summary

**Iterations run:** 4 sweeps (32 round-executions total); final sweep: all 8 rounds clean, 640/640.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/test_helpers/fixtures.py` — `whey_stream_for_make` fixture: switched `list_whey_streams` from MakePlanner to QAGrader headers. PRD §4 authorizes only PlantAdmin/Cheesemaker/QAGrader for `GET /plant/whey-streams`; the PRD-faithful implementation correctly rejected the fixture's request with 403. This single fixture bug accounted for 48 of 49 per-round failures.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/test_suite/test_02_vat_booking_and_additives.py` — `test_cancel_reverses_milk_commit_and_frees_vat`: setup changed to `volume_liters=8000.0` (5000 committed). Previously the start drove the intake to terminal CONSUMED, where §3.3's milk un-commit conflicts with §2.5's "compensating reversals apply only to non-terminal resources" — not uniquely derivable. With a non-terminal intake, both PRD readers agree the un-commit applies; assertions unchanged (more faithful, not weaker).
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/test_suite/test_05_aging_cellar.py` — `TestRoomCapacityBoundary._two_batches_one_vat`: referenced the `api` pytest fixture out of scope (`NameError`); now uses the shared `api_client` singleton imported from test_helpers (identical object the fixture returns).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1398_cheese_plant_aging_program/workspace/implementation/app.py` — `__main__` boot: replaced `app.run()` with `werkzeug.serving.make_server` plus a bounded (~20s) EADDRINUSE bind-retry. The per-test-server runner SIGKILLs the previous server on the same port and spawns the replacement immediately; under host load the killed listener occasionally had not released the socket, so the new process died on bind and surfaced as spurious "could not be restarted" setup failures (14 occurrences in sweep 2, 3 in sweep 3, 0 after the fix). No SO_REUSEPORT — port sharing is never permitted, preserving isolation semantics. No PRD-visible behavior changed.

**Notable findings:** No flaky test logic was found — the union/intersection of failures was identical across rounds in every sweep; all real failures were deterministic, and the only nondeterminism was the environmental boot race above. The host runs sibling benchmark pipelines concurrently (load avg peaked ~23), which the bind-retry hardening fully absorbed.

## Step 8: Finalize PRD — 2026-08-13T05:40:00.000Z

Done. The task is complete.

## Summary on exit

**Line counts / %-delta:** `PRD.md` = 330 lines, `PRD_FINALIZED.md` = 330 lines — 0.0% delta (one paragraph revised in place; no lines added or removed).

**Changes:**
- §3.3 — revise — In the cancellation paragraph: removed the unconditional qualifier "full" from "full compensation" and inserted one sentence pinning the §2.5 non-terminal rule at cancel time: a lot already `EXPIRED` or `RECALLED` is not refunded, an intake already `CONSUMED` keeps its `consumed_liters` unchanged, and the cancellation itself (move to `CANCELLED` + vat re-derivation) proceeds regardless — impl: `implementation/services.py:71-89` (`refill_lot_if_live`, `uncommit_milk_if_live`) and `implementation/routes/make_sheets.py:280-304` (`cancel_make_sheet`).

**Step-7 items verified as no-PRD-change:**
- §4 whey-streams role rows (PRD lines 256-257: PlantAdmin, Cheesemaker, QAGrader) match `implementation/routes/whey.py:14` (`GET_ROLES`) exactly — the fixture was the bug.
- `test_05` NameError fix and `app.py` `make_server`/bind-retry boot hardening have no PRD-visible behavior.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: make-sheet cancellation compensation — additive-lot refunds, milk un-commit, and their interaction with terminal resource states.
- (b) Impl paths enumerated and read/grepped: full reads of `routes/make_sheets.py`, `services.py`, `routes/milk.py`, `routes/additives.py`, `routes/whey.py`; grep for `refill_lot_if_live|uncommit_milk_if_live` confirmed `cancel_make_sheet` is the only callsite; grep for `quantity_on_hand|consumed_liters` confirmed the only writers are lot receipt, intake creation, make start, and the two cancel helpers; grep for `EXPIRED|RECALLED|DEPLETED|CONSUMED` confirmed terminal-state writers (`clock.py:21`, `additives.py:92`, `make_sheets.py:178/182`) perform no refunds themselves. Reachability checks: `milk.py:94-102` gates reject to `RECEIVED`, so an IN_PROGRESS make's intake is only ever `ACCEPTED`/`CONSUMED` at cancel time; a started make's lot was `RELEASED` at start with no path back to `QUARANTINE`, so its cancel-time states are exactly `RELEASED`/`DEPLETED`/`EXPIRED`/`RECALLED` — the impl's `in ("RELEASED","DEPLETED")` guard is precisely "non-terminal" over reachable states.
- (c) Wording adjustment: dropped "full" (it read as unconditional and was the divergence source), and scoped the inserted sentence with "at cancel time" plus "the cancellation itself … proceeds either way" so it cannot be misread as narrowing the recall, clock-sweep, or start-consumption paths enumerated in (b). The §4 cancel-row summary was left verbatim since §4 explicitly defers semantics to the §2/§3 narratives.

## Step 9: Complete PRD — 2026-08-13T05:55:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as an inline-only patch over `PRD_FINALIZED.md` (all 14 blueprints plus `calc.py`, `helpers.py`, `services.py`, `db.py`, `response.py`, `app.py` walked exhaustively).

**Stats**: PRD_FINALIZED.md 330 lines / 52,534 chars → PRD_COMPLETED.md 330 lines / 57,579 chars (char-delta +5,045; 33 paragraphs touched, zero sections added).

**Counts**: 23 ambiguity-pins, 8 mismatch-revisions (one edit is a compound parse-ordering pin counted once).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — revise — ambiguity — blank/whitespace `X-User-ID` rejected as `ERR_UNAUTHENTICATED` — helpers.py:35
- §2.2 — revise — ambiguity — `api_request_timestamp` reads from the logical clock, never wall-clock — response.py:19, db.py:34
- §2.3 — revise — ambiguity — limit/offset out-of-range → 400; `created_at` ties break by creation order; `total_count`/`has_more` semantics; boolean filters match as `true`/`false`; `turns_due` filter uses the stored flag, not the read-time projection — helpers.py:163-217, units.py:104
- §2.4 — revise — ambiguity — clock accepts any well-formed timestamp (no monotonicity check); `now` echoes the caller's `to_iso8601` string verbatim; `expired_lot_ids` in lot-receipt order — clock.py:16-32
- §2.4 — insert — ambiguity — age/turn sweep refreshes stored projections without bumping `version`/`updated_at`; on-read recompute applies to `IN_ROOM` units, `REMOVED` units report last computed values — clock.py:28-31, units.py:18-25
- §2.5 — revise — ambiguity — `version` starts at 1; `created_at`/`updated_at` read from the logical clock — db.py:51-60
- §2.6 — insert — ambiguity — unknown paths and unsupported methods fail `ERR_NOT_FOUND` (404) in the standard envelope — app.py:56-63
- §2.7 — revise — mismatch — grading readings recorded exactly as supplied (not rounded to 1dp); comparisons exact — calc.py:122-138, grading.py:85-86
- §2.7 — insert — ambiguity — client-supplied timestamps (`received_at`, `expires_at`, `scheduled_start`, `scheduled_end`) stored and returned verbatim — milk.py:43, additives.py:41, make_sheets.py:91-92
- §2.9 — revise — ambiguity — parse-ordering pinned: JSON well-formedness before existence/state everywhere except make-sheet completion (state gate precedes body read); field-level 400s before existence on creates/transitions but after existence on plant/room PATCH; move's same-destination 400 after existence and state — helpers.py:42-55, make_sheets.py:222-227, plants.py:36-45, rooms.py:70-85, units.py:126-136
- §2.9 ladder — revise — ambiguity — rung 8 gains `ERR_RUN_NOT_RECONCILED`, `ERR_GRADE_NOT_RELEASABLE`; rung 9 gains `ERR_VAT_NOT_CLEAN` (first), `ERR_MILK_SHORTFALL` (after `ERR_ADDITIVE_INSUFFICIENT`), `ERR_ORDER_HAS_CUTS`; rung 11 gains `ERR_ROOM_NOT_EMPTY` — make_sheets.py:72,167, orders.py:77, rooms.py:96, certs.py:88, batches.py:58
- §3.1 — revise — ambiguity — every plant PATCH call bumps `version`, even a no-op — plants.py:44
- §3.1 — revise — ambiguity — vat/room duplicate `code` and duplicate `supplier_lot_no` fail `ERR_INVALID_REQUEST` (400) — vats.py:26, rooms.py:28, additives.py:33
- §3.1 — revise — ambiguity — room PATCH bumps version even with neither reading; env updates still accepted on `DECOMMISSIONED` rooms (posture frozen); decommission requires `ACTIVE`, else `ERR_INVALID_STATE` — rooms.py:77-96, calc.py:146
- §3.2 — insert — ambiguity — `volume_liters` positive, `fat_pct`/`protein_pct` non-negative, `somatic_cell_count` non-negative integer, all 400-at-parse — milk.py:33-36
- §3.3 — insert — ambiguity — booking against a `DECOMMISSIONED` vat fails `ERR_INVALID_STATE` at the state rung — make_sheets.py:69-70
- §3.3 — revise — mismatch — every successful booking sets the vat to `BOOKED` unconditionally (not merely `IDLE`→`BOOKED` on first booking) — make_sheets.py:108
- §3.3 — insert — ambiguity — vat re-derivation on cancel exempts `CLEANING`/`DECOMMISSIONED` vats — services.py:20-22
- §3.4 — revise — mismatch — start-gate order pinned as lot usability → milk `ACCEPTED` → lot sufficiency (culture then coagulant) → milk shortfall — make_sheets.py:152-170
- §3.4 — revise — mismatch — sign-off checks `ERR_STEP_SOLE_OPERATOR` before `ERR_STEP_OUT_OF_ORDER` — make_sheets.py:203-212
- §3.4 — revise — mismatch — CIP returns the vat to `IDLE` only if no active makes remain, else to `BOOKED` (not always `IDLE`) — vats.py:70-73
- §3.4 — insert — ambiguity — whey stream born with `valorized_kg` 0, `disposed_kg` = `total_whey_kg`, `valorization_rate_pct` 0.00 — make_sheets.py:261-269
- §3.5 — revise — ambiguity — `valorized_kg` must be non-negative, 400 at parse — whey.py:42
- §3.6 — revise — mismatch — placement gates evaluated quantity-rung first: `ERR_WHEELS_EXHAUSTED` before the room gates (`DECOMMISSIONED` → `DEVIATION` → `FULL`) — units.py:54-59, 28-35
- §3.6 — revise — ambiguity — turn/move/remove on a non-`IN_ROOM` unit fail `ERR_INVALID_STATE` — units.py:116,133,159
- §3.6 — revise — mismatch — move destination re-applies the three room gates (not the "full placement gate set"), in placement order; same-room 400 evaluated after destination existence and unit state — units.py:135-137
- §3.7 — revise — mismatch — grading state gate pinned (only `GREEN`/`AGING`/`GRADED`-with-`PENDING`; `CONDEMNED`/`RELEASED`/`ALLOCATED` → 409), and first-grading gate order is SoD → wheels-placed → age-minimum — grading.py:41-75
- §3.8 — revise — ambiguity — preview ties after `created_at` break by creation order; allocations clamp at zero once the pool is exhausted/negative; preview runs for a batch in any status — batches.py:82,91-95
- §3.8 — revise — ambiguity — order cancel requires `OPEN` or `PARTIALLY_FILLED` (else `ERR_INVALID_STATE`) before the `ERR_ORDER_HAS_CUTS` check — orders.py:75-80
- §3.8 — revise — ambiguity — draft run: `wheels_in` positive integer, both weights non-negative (400 at parse); no order-state gate at draft time beyond existence — cutwrap.py:24-27
- §3.8 — revise — mismatch — reconcile gate order pinned: run `DRAFT` → order state → batch release → `ERR_WASTE_NEGATIVE` → `ERR_WASTE_TOLERANCE` → `ERR_ORDER_OVERFILL`; both gap comparisons use the exact unrounded draft-time figures — cutwrap.py:79-105
- §3.9 — revise — ambiguity — `certificate_number` format pinned: `CERT-` + 12 uppercase hex characters — certs.py:90
- §5 — insert — ambiguity — unexpected server failure surfaces as `ERR_INTERNAL` (500) in the standard envelope — app.py:66-68

Verified already-pinned (no change needed): the §3.6 removal rule "batch must be `RELEASED` or `CONDEMNED`" already uniquely excludes `ALLOCATED`-batch wheel removal (units.py:162); the preview pool formula `wheels_produced − wheels_placed − committed cuts` matched verbatim; compensation-on-non-terminal-resources prose in §2.5/§3.3 matched `refill_lot_if_live`/`uncommit_milk_if_live` exactly; all 53 endpoint role assignments and 201/200 status conventions matched the §4 table.

## Pipeline Complete — 2026-08-13T05:55:00.000Z

All 9 steps done. Final state: 80/80 tests passing in each of 8 parallel certification rounds (640/640 executions) under per-test-server isolation; PRD.md → PRD_FINALIZED.md (Step 8, 1 revision) → PRD_COMPLETED.md (Step 9, 23 ambiguity-pins + 8 mismatch-revisions).
