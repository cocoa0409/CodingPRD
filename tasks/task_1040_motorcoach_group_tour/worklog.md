# Worklog — task_1040_motorcoach_group_tour

## Step 1: Create Task Directory — 2026-07-16

Created `./tasks/task_1040_motorcoach_group_tour/` with `workspace/` subdir. Pre-assigned folder used verbatim (no ./tasks/ ID scan). Scenario: Motorcoach & Group-Tour Operator. Difficulty: Expert (passed to Step 2 scaffold-generator only).

## Step 2: Generate Scaffold (Expert) — 2026-07-16

All three files written and `yaml.safe_load`-clean. Entities: 10 (TourProduct, Coach, Driver, Guide, Departure, HotelBlock, Booking, Passenger, Payment [append-only], Voucher). Endpoints: 36 (flat topology, api_prefix /api, incl. /_clock/set_current_utc default 2026-07-01T00:00:00Z). Errors: 20. Validations: 20 (priority-ordered). Calculations: 7 (2 dual-variant). Concurrency: 1 (OCC CREATE-with-supersede on Departure.version via POST /api/departures/{id}/assign). State machines: 8 — Departure.status cyclic OPEN↔GUARANTEED; Booking parallel dims (reservation_status × payment_status); linear/cyclic Coach, Driver, Guide, HotelBlock, Voucher.

Constants ALL declared with values (subagent reports no undeclared refs): SMALL_MAX_PAX=5, LARGE_MIN_PAX=12, band mults 1.20/1.00/0.90; SERVICE_FEE_RATE=0.0725; INSURANCE_PREMIUM_RATE=0.06; MEAL_VOUCHER_CENTS=2500; deposit_per_person_cents default 20000; cancellation tiers 0.10/0.25/0.50/1.00; TURNAROUND_BUFFER_DAYS=1; DOT_MAX_DRIVE_HOURS_PER_DAY=10.

Design cleanups: removed Coach MAINTENANCE, Driver OFF_DUTY, ERR_COACH_NOT_AVAILABLE, ERR_MIN_PAX_NOT_MET (no API path produced them). §1.8 = 9 rules × 2 = 18 instances; §1.9 = 24 active + 7 excluded stubs. Lint: clean.

## Step 3: Copy INSTRUCTION.md — 2026-07-16

`cp ./INSTRUCTION.md workspace/INSTRUCTION.md` — done.

## Step 4: Generate PRD — 2026-07-16

PRD written to workspace/PRD.md — 269 lines, 36 endpoints documented, 20 errors. Hard Contracts (field-name coverage, rule coverage, §3 path purity) all PASS per subagent.

**Undeclared-constant patch (pre-Step-5):** PRD-gen flagged `TURNAROUND_BUFFER_DAYS` as referenced-but-undeclared (coach-overlap validation priority 10, Coach AVAILABLE→ASSIGNED, ERR_COACH_OVERLAP). Difficulty-design instance `coach_overlap_closed_interval_with_turnaround_buffer` pins it = **1 whole day** (Dep1 ends 08-05 → same coach on Dep2 starting 08-06 rejected: 08-06 <= 08-05+1). Contrast: guide overlap is half-open, no buffer (adjacency allowed). Patched value =1 into SCAFFOLD.yaml (2 sites: Coach transition precondition + validation priority 10) and PRD.md §2.10 (added "D+2 or later; a start on D+1 still conflicts"). SCAFFOLD re-verified safe_load OK. DOT_MAX_DRIVE_HOURS_PER_DAY declared inline (10) — no patch.

## Step 5: Generate Unit Tests — 2026-07-16

58 tests total; all collect cleanly. Queue A (Difficulty): 34 tests / 17 instances (2 each). Queue B (Corner): 24 tests / 24 non-stub instances (1 each). 7 excluded_because stubs correctly not translated.

**1 instance SKIPPED** — `Difficulty/cross_entity_state_dependency/hotel_block_confirm_depends_on_departure_not_terminal` — unique-derivability failure (PRD self-contradiction): §2.8 says confirming a HELD block on a CANCELLED departure yields ERR_DEPARTURE_TERMINAL, but §3.4 says the same case yields ERR_INVALID_STATE. Two faithful readers diverge → skipped. (Step 6 impl chose ERR_DEPARTURE_TERMINAL per §2.8; Step 9 should pin PRD.)

Files: test_helpers/{__init__,types,api_client,api_errors,assertions,factories,constants,test_users,fixtures}.py; test_suite/{conftest, test_01_pricing_and_charges(7), test_02_settlement(3), test_03_booking_lifecycle(10), test_04_cascades_and_invariants(8), test_05_validation_precedence(6), test_06_resource_scheduling(9), test_07_state_transitions(4), test_08_rbac_and_crud(11)}.py. Payment TypedDict omits updated_at/version (append-only, common_fields:false). All 4 roles share opaque-identity headers (X-User-ID never entity-matched per §2.1).

## Step 6: Generate Implementation — 2026-07-16

17 files under workspace/implementation/. start.sh (foreground, exec python3 app.py, guarded pip). app.py + store.py (in-memory dicts + logical clock default 2026-07-01T00:00:00Z) + calc.py (Decimal ROUND_HALF_UP) + errors.py (20-entry catalog) + web.py (envelope/RBAC/pagination/validators) + services.py + routes/ (8 modules: catalog, departures, hotel_blocks, bookings, passengers, payments, vouchers, clock). ast.parse clean on all 15 py (0 failures). 37 route decorators = 36 endpoints + clock dual-registered (/_clock + /api/_clock). In-memory only, empty boot, no seeding. Impl chose ERR_DEPARTURE_TERMINAL for hotel-confirm-on-terminal-departure (§2.8 over §3.4). Assign OCC checked last (after DOT/overlap per §3.3). Route-count == endpoint-count verified (no partial-write gap).

## Step 7: Test-and-Fix Loop — 2026-07-16

Iterations: 2 (initial sweep → 1 deletion → clean sweep). Final: **57/57 pass across all 8 rounds** (2 waves of 4), 0 failures/errors/flakiness. 0 implementation/ fixes, 0 test_helpers/ fixes.

**Test deleted (1):** `test_06_resource_scheduling.py::test_guide_end_to_start_adjacency_sets_guide_assigned` — UNOBSERVABLE-STATE / non-unique-derivability (STEP 1b). Asserted guide `status == ASSIGNED` via `GET /api/guides/{id}`, but PRD endpoint table documents GET for coaches & drivers but **deliberately omits GET /api/guides/{id}** — no guide-read capability in PRD prose. Rule "assignment sets status to ASSIGNED" (§2.10/§3.3) is stated but not observable for a guide via any PRD-faithful impl (impl returned 404 ERR_NOT_FOUND); STEP 3 forbids adding an undocumented endpoint → deleted. Sibling `test_guide_end_to_start_adjacency_allowed` (verifies adjacency via departure.guide_id, observable via documented GET departure) retained and passes. Intermittent test_guarantee_boundary_* failures were host-saturation boot-timeouts that cleared under lower load — not real bugs.

## Step 8: Finalize PRD — 2026-07-16

PRD_FINALIZED.md written as verbatim copy of PRD.md — **0 edits** (268 → 268 lines, 0% delta). Sole Step-7 item was a test deletion (guide-read unobservable), and PRD/impl coherently agree in omitting GET /api/guides/{id} (impl routes/catalog.py has GET for coaches & drivers, POST-only for guides). Not a pinned choice or divergence → nothing to patch.

## Step 9: Complete PRD — 2026-07-16

PRD_COMPLETED.md written (from PRD_FINALIZED.md). 268 → 268 lines, +1,974 chars, all in-paragraph. **9 edits: 6 ambiguity-pins + 3 mismatch-revisions.**
- §2.3 pagination — insert — limit clamps [1,100], offset<0→0, non-int limit/offset→ERR_VALIDATION.
- §2.10 crew scheduling — revise (mismatch) — removed "may only be assigned when AVAILABLE" gate; assignment governed solely by date-conflict rules (already-ASSIGNED on non-overlapping departure may still be assigned).
- §3.2 publish — insert — non-PLANNING→ERR_INVALID_STATE, terminal→ERR_DEPARTURE_TERMINAL first, empty itinerary_days→ERR_VALIDATION.
- §3.4 hotel init — revise (mismatch) — rooms_committed initializes to departure's current committed-room sum (not hard 0).
- §3.4 hotel confirm/release — revise (mismatch) — terminal parent on confirm→ERR_DEPARTURE_TERMINAL (resolves §2.8/§3.4 contradiction in impl's favor); non-HELD→ERR_INVALID_STATE; double-release→ERR_INVALID_STATE.
- §3.7 confirm from-state — insert — non-terminal non-DRAFT (already CONFIRMED)→ERR_INVALID_STATE.
- §3.7 seat/room numbering — revise — lowest unused number across CONFIRMED/TRAVELED; rooming pairs via roommate_passenger_id.
- §3.9 manifest — insert — rooming element shape {passenger_id, room_no, roommate_passenger_id}; passengers/vouchers only from CONFIRMED/TRAVELED.
- §3.9 settlement provisional — insert — provisional applies for any status other than DEPARTED/SETTLED.

No guide-read endpoint added. SCAFFOLD/worklog not read.

## Pipeline Complete — 2026-07-16

All 9 steps done. Final: **57/57 tests pass across all 8 stability rounds**. Deliverables: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (9 edits), full test suite (test_helpers/ + test_suite/, 57 tests), working Flask implementation (17 files, 36 endpoints, in-memory).
