# Worklog — task_0742_event_av_production_rental

Scenario: 742. Event AV & Production Rental: equipment (sound/lighting/staging/LED) inventory, event quote & package, crew (tech/operator) scheduling, load-in/out & venue logistics, sub-rental & cross-rental, damage/loss & deposit, multi-day & standby, certificate of insurance

Difficulty: Expert

## Step 1: Create task directory — 2026-07-04T16:58:09.000Z

Task directory pre-allocated by orchestrator invocation: `tasks/task_0742_event_av_production_rental` (with `workspace/`). Skipped ./tasks/ scan and auto-numbering per instructions. No new task dir created.

## Step 2: Generate Scaffold — 2026-07-04T17:58:43.000Z

All three artifacts are complete, lint-clean, and self-consistent. Here is the summary.

## Generated: `task_0742_event_av_production_rental` — Expert difficulty

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_0742_event_av_production_rental/`
- `SCAFFOLD.yaml` (§1.0–§1.7 + preamble)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**`scaffold_lint.py` verdict:** `clean lint` — all 366 §1.8/§1.9 calls conform to §1.5; all 14 FKs have reverse-reachability GETs. All formula-derived assert literals were executed in code and verified.

### Complexity profile
- **Archetype:** quota_allocation (finite equipment units across overlapping event windows) + secondary temporal_windowing. Topology **flat** (peer collections, `api_prefix: "/"`), state-machine shape **cyclic**, role model **peer_roles**.
- **Layers:** optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

### Counts
- **11 entities:** Customer, Venue, EquipmentItem, CrewMember, RentalOrder (OCC parent), EquipmentReservation, CrewAssignment, SubRental, CertificateOfInsurance, DamageReport, DepositLedgerEntry (append-only, `common_fields:false`).
- **6 state machines:** RentalOrder (cyclic QUOTED↔DRAFT → CONFIRMED → LOADED_OUT → IN_EVENT → LOADED_IN → SETTLED / CANCELLED), EquipmentReservation (branching CHECKED_OUT→{CHECKED_IN,DAMAGED}), DamageReport (branching ASSESSED→{CHARGED,WAIVED}), CertificateOfInsurance, CrewAssignment, SubRental. 1 concurrency rule (confirm-stale-order, OCC on RentalOrder.version, 412).
- **5 calculations:** equipment_line_pricing (tiered multi-day + standby, round-per-line), crew_labor_pricing (min-call/overtime/operator-premium), order_totals (pinned discount→surcharge eval order), deposit_settlement (forward-hold vs chronological-waterfall dual variant), equipment_availability (inclusive-day aggregate-capacity overlap).
- **10 validations** (priority-ordered), **19 errors**, **51 endpoints** (includes `/_clock/set_current_utc`, default `2026-03-01T00:00:00Z`), **4 roles** (AccountManager/WarehouseManager/CrewChief opaque + Client entity_backed:Customer).

### §1.8 depth — 18 instances (9 rules × 2)
dual_variant_calc (revenue provisional vs final; deposit hold vs settlement), combinatorial_formula (mode-a crew nonlinear; mode-b per-line rounding), non_linear_state_machine (order cycle; damage branch), transitive_cascade (order-cancel depth-3; damage-checkin depth-3), priority_pair_validation_conflict (state>temporal; safety>fiscal), boundary_precision_check (unit quota; COI coverage), cross_entity_state_dependency (order←COI; reservation←order), resource_temporal_overlap (equipment aggregate-capacity; crew turnaround-buffer), compensating_invariant (equipment units; deposit cents).

### §1.9 breadth — 29 instances (22 with executable recipes + 7 `excluded_because` stubs)
Spanning entities/calculations/state_machines/validations/rbac/endpoints/cross_cutting/errors. Every error code is triggered by at least one §1.8 or §1.9 instance; all excluded stubs resolve to real §1.8 instance names; all 47 instance names are unique.

**Note:** endpoint count (51) sits above the Expert 20–32 guideline — a consequence of 11 entities each carrying full CRUD + lifecycle actions plus the FK reverse-reachability GETs the lint requires. Per §0.4 these bands are explicit guidelines, not hard rules; the coupling density (5 interlocking calculations, cross-entity gates, two depth-3 cascades) is where the difficulty lives.

## Step 3: Copy Shared Files — 2026-07-04T17:59:07.000Z

Copied ./INSTRUCTION.md → tasks/task_0742_event_av_production_rental/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T18:10:16.000Z

All three hard contracts pass. The PRD is complete and verified.

Generated `workspace/PRD.md` (302 lines) from the scaffold. Read only the skill spec, the permitted `SCAFFOLD.yaml`, the fixed §2.2 source, and the example PRD — did NOT open either withheld design file.

**Structure (5 top-level sections):**
- §1 Introduction — production-rental domain framing.
- §2 Global Specifications — 10 subsections: RBAC, fixed verbatim envelope, pagination, common properties + DepositLedgerEntry common-fields exception, monetary precision/round-half-up/per-line rounding, logical event clock, 10-rung validation priority ladder, OCC on confirmation, derived-field reconciliation + cascades, nested reference resolution.
- §3 Business Logic — 9 scattered workflow subsections (catalog → order+reservations → crew → sub-rental → COI → quoting → confirmation/deposit → load cycle → damage settlement/settle/cancel).
- §4 endpoint table (51 endpoints), §5 error table (19 errors).

**Coverage:** 11 entities (all 70 field names) with defaults/initial states; 8 state machines with every transition, precondition→error pairing, side-effect cascade (incl. two depth-3 cascades); 5 calculations with all constants; priority-ordered validation ladder; OCC rule (expected_order_version/ERR_STALE_VERSION/412); all 19 error IDs.

Hard Contract Reports: Field coverage PASS (70/70 fields, 55/55 endpoint I/O), Rule coverage PASS (10 validations, 1 OCC, 27 transitions, 5 calcs, 19 errors, sibling-branch symmetry), Path purity PASS (0 path tokens in §3).

## Step 5: Generate Unit Tests — 2026-07-04T18:39:53.000Z

All modules compile; all 7 `excluded_because` stub cross-references resolve to real difficulty instances (correctly skipped, no placeholders).

### Tests emitted: 58 total
- **Queue A (Difficulty): 36 tests** — all 18 instances (9 rule_ids × 2) covered with exactly 2 tests each.
- **Queue B (Corner): 22 tests** — all 22 non-stub instances (entities 4, calculations 3, state_machines 8, validations 2, rbac 2, endpoints 1, cross_cutting 2).

### Instances skipped: 7 (all `excluded_because` stubs, per contract)
- 6 in `errors` (ERR_EQUIPMENT_UNAVAILABLE, ERR_COI_INSUFFICIENT_COVERAGE, ERR_CREW_DOUBLE_BOOKED, ERR_ORDER_NOT_LOADED_OUT, ERR_COI_NOT_APPROVED, ERR_INVALID_STATE) + 1 cross_cutting (confirm_correct_version_succeeds). All cite a difficulty instance that owns the assertion; all resolve. No non-stub instance failed the PRD-first filter.

### One assertion relaxed (not a full skip)
For `reservation_damage_checkin_files_report_recompute_depth3`, the index asserts `deposit_at_risk_cents == 500000`, but PRD §3.8 defines `deposit_at_risk_cents` as summed `assessed_cost_cents` of OPEN reports — 0 for a just-auto-FILED report. That single non-derivable assertion was dropped per two-reader rule; tests assert PRD-derivable cascade effects (DAMAGED status, open_damage_count==1, auto-filed FILED report).

### test_helpers/ (9 files)
`__init__.py`, `types.py` (DepositLedgerEntry omits updated_at/version per common_fields:false), `api_client.py` (50 endpoints), `api_errors.py` (20 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque roles + entity_backed make_client_headers), `fixtures.py`.

### test_suite/ (7 files)
- conftest.py — pytest bridge (api + 4 role-header fixtures)
- test_01_pricing_calculations.py — 9
- test_02_state_machines.py — 12
- test_03_cascades_and_deposits.py — 9
- test_04_validation_precedence_and_boundaries.py — 10
- test_05_cross_entity_and_temporal.py — 10
- test_06_access_and_catalog.py — 8

All 58 collect cleanly; every module byte-compiles; every test has exactly one Design: tag resolving to a real instance; no skip/xfail; all 72 PRD citations verbatim-present. Not yet executed against a live server (impl generated concurrently).

## Step 6: Generate Implementation — 2026-07-04T18:39:53.000Z

Complete Python + Flask REST API under `workspace/implementation/`.

### Files written
- `start.sh` — cd to script dir, flask-import-guarded pip install, `exec python3 app.py`; binds 0.0.0.0:$PORT (default 10000), foreground.
- `requirements.txt` — flask>=3.0,<4.0.
- `store.py` — in-memory dicts keyed by id, UUID/timestamp helpers, logical clock (default 2026-03-01T00:00:00Z), ApiError, envelope builders, round_half_up via Decimal/ROUND_HALF_UP.
- `calc.py` — equipment line pricing (standby ×0.5, multi-day tiers 0/10/15%), crew labor (min-call 4h, OT >10h ×1.5, OPERATOR ×1.20), order totals (volume tiers, pinned discount-before-rush), deposit sizing (20%).
- `app.py` — all 40+ endpoints, auth/RBAC, validation ladder, state machines, cascades, derived-field reconciliation.

Storage purely in-memory dicts wiped on every boot — no disk, no seeding. Fresh restart yields empty collections. Boots in ~1s.

### PRD ambiguities resolved (concrete choices — Step 8/9 alignment targets)
1. **Order `version` bumping** — bumps on every lifecycle transition, reservation create/release, crew-assignment create/cancel, COI approve, damage-report file/assess/charge/waive, sub-rental confirm/cancel. Makes OCC stale test fire.
2. **Settle precedence** — §2.7 ranks insurance-safety (7) above referential-readiness (9); ERR_COI_NOT_APPROVED preempts ERR_OPEN_DAMAGE_REPORT.
3. **sub_rental_cost_cents recomputation** — sum over {CONFIRMED, RETURNED} sub-rentals.
4. **Clock current_utc output format** — canonical ISO-8601 ms-Z (e.g. 2026-06-01T00:00:00.000Z).
5. **ERR_RESERVATION_ORDER_MISMATCH ordering** — after body validation, before parent-state (both 409), per §2.10.

## Step 7: Run Tests and Iterate — 2026-07-04T18:47:14.000Z

All 8 rounds green (58/58 each). Clean sweep complete.

**Iterations run:** 1 full 8-round sweep after the fix (2 waves of 4), all green.

**Root cause:** Baseline sweep showed exactly 2 tests failing identically across every round — `test_operator_overtime_labor_charge` and `test_operator_overtime_reflected_in_crew_subtotal` in `test_01_pricing_calculations.py` — both with `NameError: name 'new_crew_member' is not defined`. Both call the `new_crew_member(...)` helper, but the test module's import block omitted it. Pure test-file bug (Diagnostic STEP 2: test setup references a helper that exists in test_helpers but wasn't imported), NOT an implementation defect.

**Tests deleted:** None. Both failing tests are PRD-faithful — assert operator overtime crew pricing quoted verbatim from PRD §3.6 (OT multiplier 1.5, OPERATOR premium 1.20, min-call 4h, OT threshold 10h all verbatim). Implementation (`calc.crew_assignment_cost`) already computed expected 93600 correctly.

**Fixes applied to test_suite/:**
- `test_suite/test_01_pricing_calculations.py` — added `new_crew_member` to the `from test_helpers import (...)` block so the two operator-overtime tests resolve the fixture. (`new_crew_member` was already defined in `test_helpers/fixtures.py` and re-exported via `test_helpers/__init__.py`; the other four modules using it already imported it.)

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — no PRD-traceable implementation defect surfaced.

**Operational note:** The provided sweep script's `pkill -f "…/workspace/implementation"` reap line matches the runner shell's own command line, so it can kill the parent shell before the next wave (exit 144). Ran the two waves as separate calls and verified no orphan servers accumulated; per-test-server isolation already tears down each server after every test.

## Step 8: Finalize PRD — 2026-07-04T18:49:14.000Z

Zero edits. PRD_FINALIZED.md is a verbatim copy of PRD.md (302 vs 302 lines, 0.0% delta, byte-identical).

The single <step_7_diff> item was a pure Python missing-import bug (`new_crew_member` absent from the import block in test_01_pricing_calculations.py → NameError in two operator-overtime tests). No implementation change, no deletion, no assertion weakening. Locating the corresponding behavior (operator-overtime crew pricing, PRD §3.6 / calc.crew_assignment_cost) confirmed PRD §3.6 already uniquely determines what the implementation computes (12h OPERATOR @6000 → reg 72000 + OT 21600 = 93600, matching §3.6 prose verbatim). Nothing to patch. Not an implementation defect and not a PRD silence.

Step 8 was run (not skipped) because the literal skip condition requires 0 test_suite fixes; there was 1. It correctly found empty scope.

## Step 9: Complete PRD — 2026-07-04T18:59:18.000Z

Applied as in-paragraph revisions/inserts; no new sections. Line count unchanged (302 → 302), char delta +1814 (46215 → 48029).

**Counts**: 6 ambiguity-pins, 3 mismatch-revisions.

**Changes** (one per edit):
- §2.3 Pagination — insert — ambiguity — non-integer limit/offset rejected with ERR_PAGINATION_INVALID (app.py:293-299)
- §2.6 Logical Event Clock — insert — ambiguity — current_utc is ISO 8601 UTC with exactly 3 fractional (ms) digits + trailing Z (store.py:69-71 / app.py:349)
- §2.8 Optimistic Concurrency — revise — mismatch — "added/released in a way that re-runs pricing" was false; reservation/crew add/release bump order version but pricing not re-run until quote/settle (app.py:747,837,879,932 vs run_pricing at 561,671)
- §2.9 Derived-Field Reconciliation — insert — ambiguity — added the two omitted reconciliations (sub_rental_cost_cents recompute; has_approved_coi recompute on COI approve) as order mutations that bump version (app.py:1009,1036,836,702,1100 / store.py:184-195)
- §2.10 Nested Reference Resolution — insert — ambiguity — ERR_RESERVATION_ORDER_MISMATCH evaluated after body validation (§2.7 step 4) and before parent-order state check (§2.7 step 5) (app.py:952-961,1127-1136)
- §3.2 Availability read — insert — ambiguity — default horizon = earliest reserve_start_date to latest reserve_end_date over item's HELD/CHECKED_OUT reservations; peak_reserved_units 0 when none (app.py:439-450)
- §3.4 Sub-Rental — revise — mismatch/ambiguity — confirmation adds cost_cents irrespective of direction (not inbound-only); total = sum over CONFIRMED or RETURNED; return keeps cost, only removes capacity (store.py:191-195, app.py:1007-1010,1032-1037)
- §3.9 Settlement — insert — ambiguity — COI check precedes open-damage check (§2.7 ladder); order lacking valid COI + open report refused with ERR_COI_NOT_APPROVED (app.py:664-670)
- §3.9 Cancellation — revise — mismatch — "every step increments order version" was wrong; each touched child gets its own version bump, order version incremented exactly once (app.py:689-710)

**Five flagged items:** all confirmed against code and pinned. Item 1 (version bumping) mostly covered by §2.4/§2.9 framework, but §2.8's "re-runs pricing" and §3.9's "every step" claims were wrong, and §2.9 omitted sub-rental-cost + COI reconciliations — those were the load-bearing fixes. Verified-no-change: sub-rental create/return, COI submit/reject, reservation check-out/clean check-in, crew complete do NOT bump order version.

---

## Pipeline complete — 2026-07-04T18:59:18.000Z

All 9 steps done. Final test status: 58/58 passing across all 8 stability rounds (2 waves of 4). Steps 8/9 edited only PRD_*.md documentation (no code/test changes), so the green state is preserved.
