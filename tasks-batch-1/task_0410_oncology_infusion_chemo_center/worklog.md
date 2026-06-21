# Worklog — task_0410_oncology_infusion_chemo_center

Scenario: 410. Oncology Infusion & Chemotherapy Center: regimen/protocol order set, chair & nurse scheduling, dose calculation (BSA/AUC) & double verification, drug mixing & waste (JW modifier), pre-medication & sequencing, prior-auth & specialty-drug acquisition, toxicity/reaction monitoring, treatment-cycle calendar

## Step 1: Create task directory — 2026-06-18T18:15:18.000Z

Created `tasks/task_0410_oncology_infusion_chemo_center/` and `workspace/` subdirectory. Index 0410 (previous max 0409).

## Step 2: Generate scaffold — 2026-06-18T18:26:00.000Z

All three scaffold artifacts are complete, self-consistent, and pass the linter cleanly. Here is the summary of what I generated.

## Summary — task_0410_oncology_infusion_chemo_center

Three files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0410_oncology_infusion_chemo_center/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** Advanced band. Primary archetype `temporal_windowing` (chair + nurse interval scheduling) blended with `compliance_audit` (double verification, JW waste, segregation of duties). Topology `flat` (FK-linked peers, non-nested URLs — prioritized for diversity); state-machine shape `branching` (reject-revert + active/on-hold loops); role model `segregation_of_duties`. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Scaffold contents:**
- **10 entities**: Patient, RegimenProtocol, OrderSetItem, Chair, Nurse, PriorAuthorization, TreatmentCycle, DrugOrder, InfusionAppointment, ToxicityEvent.
- **5 state machines**: RegimenProtocol (DRAFT→PUBLISHED), TreatmentCycle (PLANNED→ACTIVE↔ON_HOLD→COMPLETED/ABANDONED, with self-loop cycle advance), DrugOrder (ORDERED↔PREPARED→VERIFIED→ADMINISTERED + reject-revert), InfusionAppointment (SCHEDULED→CHECKED_IN→COMPLETED), PriorAuthorization (REQUESTED→APPROVED→EXHAUSTED). **1 concurrency rule** (OCC on `TreatmentCycle.version` for appointment booking, ERR_STALE_CYCLE_VERSION/412).
- **5 calculations**: Mosteller BSA, ordered_dose (BSA/AUC-Calvert/FLAT variants + JW waste, reduce-before-round pinned), prior_auth_consumed_units (aggregation + exhaustion boundary), nurse_acuity_load (aggregate-capacity interval overlap), cycle_day_schedule (calendar projection).
- **49 endpoints**, **14 validations** (auth → existence → invalid-request → OCC → state → safety → temporal → referential → fiscal), **39 errors**, **3 roles** (Pharmacist=opaque, Nurse=entity_backed:Nurse, PriorAuthCoordinator=opaque).

**Design instance counts:**
- §1.8: 9 rule_ids × exactly 2 instances = **18 instances** (all 9 §0.5 rules present, each with differentiated pairs across distinct entity domains / error-category pairs / interval semantics / conserved quantities).
- §1.9: **37 instances** (35 active + 2 `excluded_because` stubs, both citing valid §1.8 instance names) across entities, state_machines, calculations, validations, rbac, cross-cutting layers, endpoints, errors.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (391 calls scanned, all FKs reverse-reachable). All grounds refs resolve to declared elements; all names unique across both design files; every asserted numeric literal (doses 319/525/420/750, waste/JW flags, BSA 1.63/2.00, calendar 2026-07-29, acuity boundary 6) independently recomputed against the formulas; no forbidden concurrency vocabulary; envelope verbatim; no `id`-based business decisions (created_at fallback).

## Step 3: Copy shared files — 2026-06-18T18:33:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-18T18:39:19.000Z

Generated `workspace/PRD.md` (304 lines) from the oncology-infusion scaffold.

**Structure:** 5 top-level sections. §2 has 11 domain-derived subsections (auth/RBAC, fixed response envelope, pagination, common properties, hierarchical cascades, OCC, dose-arithmetic/JW-waste, temporal scheduling, segregation of duties, validation ordering, status codes). §3 has 11 workflow subsections organized by clinical lifecycle.

**Coverage:** 10 entities; all 49 scaffold endpoints in §4 table; all 39 error IDs in §5 table and narrative.

**Hard contracts (mechanically verified):** Contract 1 Field-Name Coverage PASS (59/59); Contract 2 Rule Coverage PASS (OCC, both dose variants, JW waste, prior-auth EXHAUSTED cascade, hold/abandon cascades, 4-precondition verification gate, nurse-acuity half-open interval strict `>`, §2.10 validation precedence); Contract 3 §3 Path Purity PASS (0 slash/method/method+path tokens). §2.2 envelope verbatim.

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml, and did not look at any sibling task.

## Step 5: Generate unit tests — 2026-06-18T18:52:20.000Z

Test infrastructure generation complete for task_0410.

**Stage 1 — `test_helpers/` (9 files):** types.py, api_client.py, api_errors.py (40 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque Pharmacist/PriorAuthCoordinator + entity-backed Nurse), fixtures.py, __init__.py.

**Stage 2 — `test_suite/` (conftest + 6 test files):** test_01 dose calculation (9), test_02 chairside verification (7), test_03 cycle lifecycle/cascades (14), test_04 scheduling (9), test_05 CRUD/validation/RBAC (12), test_06 difficulty second-assertions (18).

**Counts:** 69 test functions, 69 Design tags (1:1 parity). Queue A (Difficulty): 36 tests covering all 18 difficulty instances ×2. Queue B (Corner): 33 tests covering all 33 non-stub corner instances ≥1 each. 2 excluded_because stubs not translated.

**Instances SKIPPED (2, PRD-first filter):**
1. `Corner/endpoints/order_set_item_attach_to_published_protocol_rejected` — asserts ERR_INVALID_REQUEST, but PRD §3.2 only says items "attach only while DRAFT" without naming that error_id; faithful reader could return 409 (fails unique derivability).
2. `Corner/validations/specialty_chemo_order_without_prior_auth_rejected` — PRD §3.7 gates on a drug "requiring authorization" but never defines how the system identifies such a drug (fails unique derivability).

## Step 6: Generate implementation — 2026-06-18T18:52:20.000Z

Built complete Python + Flask in-memory REST API under `workspace/implementation/`.

**Files (17):** start.sh (foreground, exec, reads $PORT, binds 0.0.0.0), requirements.txt, app.py (blueprints under `/infusion-center`), db.py, errors.py, response.py, middleware.py, validation.py, calculations.py (Decimal-based), store_helpers.py, services.py, routes/ (patients, protocols+order-set-items, resources chairs/nurses, prior_auth, cycles, drug_orders, appointments, toxicity).

**Endpoints: 51 implemented.**

**Verified behaviors:** envelope, X-User-ID/X-User-Role auth, 3-role RBAC, validation precedence, Mosteller BSA, BSA dose (175×1.82=318.5→319, 7 vials, waste 31, JW true), AUC/Calvert with 20% reduction (525→420), FLAT dose, GFR cap 125, 4-precondition verify gate + reject loop, administer + PA consumption + auto-EXHAUSTED, cycle lifecycle (activate freezes BSA/GFR snapshots, hold/abandon two-step cascade, advance self-loop), toxicity grade≥3 auto-hold + resume block, half-open interval scheduling (chair double-book, nurse acuity strict `>`), OCC stale-version 412, pagination.

**PRD ambiguities resolved with noted defaults:**
1. Specialty-drug detection for ERR_PRIOR_AUTH_REQUIRED: a CHEMO drug treated as specialty-requiring-auth when a PriorAuthorization exists for patient+drug_name; such order must link APPROVED matching PA.
2. Cycle activate from non-PLANNED: enforces only the two declared guards (patient ACTIVE, protocol PUBLISHED).
3. Order-set-item attach to PUBLISHED protocol: rejected with ERR_INVALID_REQUEST (400).
4. ERR_UNRESOLVED_TOXICITY on resume: any grade≥3 event on the cycle treated as the open blocker.

## Step 7: Run tests and iterate — 2026-06-18T18:58:00.000Z

All tests pass. Exiting with the summary.

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 verification). Final state: all 8 parallel rounds pass 67/67 with an empty failure union — stable, non-flaky. The initial sweep showed a consistent 66/69 in every round (the same 3 tests failed in all 8 rounds — deterministic, not flaky). The implementation was already PRD-faithful; all three failures traced to unfair/buggy tests.

**Tests deleted (2):**
- `test_booking_on_planned_cycle_returns_state_error_over_acuity` (test_04_scheduling.py, class `TestStateVsAcuityPriority`) — PRD-silence / state-gate not assigned to this operation. The test demanded `ERR_CYCLE_NOT_ACTIVE` when booking an appointment onto a non-ACTIVE cycle. PRD §2.10 confines the parent-cycle-ACTIVE state check to "drug-order creation and appointment check-in" — appointment booking is deliberately excluded, and §3.10's booking guards (chair OPEN, double-book, acuity) never mention cycle state. A PRD-faithful implementation correctly returns `ERR_NURSE_ACUITY_EXCEEDED`. Driven by scaffold rule `priority_conflict_state_vs_acuity_on_booking`.
- `test_booking_on_held_cycle_returns_state_error` (test_06_difficulty_second_assertions.py, class `TestPriorityPairSecond`) — identical PRD-silence pattern (ON_HOLD variant), same scaffold rule.

**Fixes applied to test_suite/ (1):**
- `test_single_appointment_acuity_equal_to_max_allowed` (test_06_difficulty_second_assertions.py) — TEST BUG fix (STEP 2). The test booked a lone appointment with `acuity=6` on a `max_acuity_load=6` nurse expecting 201, but `acuity=6` violates PRD §3.10's declared range ("an integer `acuity` weight in the range 1 through 5"). The PRD-faithful implementation rightly returns `ERR_INVALID_REQUEST` (priority-4 body validation, §2.10) before the load check. Changed `acuity` 6→5 and `max_acuity_load` 6→5 so concurrent load is exactly 5 == max within the valid range — preserving the "load exactly at ceiling is permitted" boundary intent while making the request PRD-consistent.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation was already correct on every checked rule.

## Step 8: Finalize PRD — 2026-06-18T19:01:05.000Z

**Zero edits made.** `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (304 lines each, 0% delta). All three `<step_7_diff>` items were test-side corrections against behavior the PRD already pins. Verified each against `implementation/` and found no PRD silence or PRD/impl mismatch.

- Items 1&2 (booking on non-ACTIVE cycle returns acuity/scheduling error, not ERR_CYCLE_NOT_ACTIVE): `create_appointment` (appointments.py:29-95) has no parent-cycle-state check — matches PRD §2.10 (state gate confined to drug-order creation & check-in) and §3.10 (booking guards list no cycle-state guard). No edit.
- Item 3 (acuity range / exact-max-load): impl uses `require_int(body,"acuity",ge=1,le=5)` (appointments.py:48) and strict-greater `concurrent_load > max_acuity_load` (appointments.py:80) — matches PRD §3.10 verbatim. Fixed test was a fixture bug. No edit.

No-new-mismatch enumeration confirmed the ACTIVE cycle-state gate is present exactly at drug_orders.py:47/158/224, appointments.py:139 (check-in), cycles.py:144/172 (hold/advance) and absent at appointments.py:29-95 (booking) — consistent with PRD §2.10/§3.10.

## Step 9: Complete PRD — 2026-06-18T19:07:11.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Line counts:** PRD_FINALIZED.md = 304 lines, PRD_COMPLETED.md = 304 lines (all in-paragraph edits; no new lines/sections). **Char delta:** 45,304 → 47,626 (+2,322).

**Counts:** 9 ambiguity-pins, 2 mismatch-revisions (11 edits total).

**Per change:**
- §3.4 PA decide — revise — mismatch — `decision` accepts exactly APPROVE/DENY (uppercase); other → ERR_INVALID_REQUEST — routes/prior_auth.py:20,76,81
- §3.4 PA open — insert — ambiguity — authorized_units_mg initialized null until approve — routes/prior_auth.py:40
- §3.2 order-set-item — insert — ambiguity — dose field must be > 0; sequence_index required int no minimum — routes/protocols.py:105-113
- §3.2 publish/attach — insert — ambiguity — attaching item to non-DRAFT protocol → ERR_INVALID_REQUEST — routes/protocols.py:120-122
- §3.3 chair — insert — ambiguity — close has no state precondition; re-closing CLOSED re-sets and bumps version — routes/resources.py:60-68
- §3.1 patient — insert — ambiguity — mark-deceased no state precondition; succeeds on already-DECEASED — routes/patients.py:93-101
- §3.5 activate — insert — ambiguity — only two declared preconditions guard activation; patient-before-protocol — routes/cycles.py:118-134
- §3.6 calendar — insert — ambiguity — full projection as array, un-paginated, no pagination meta — routes/cycles.py:81-110
- §3.7 drug-order PA gate — revise — mismatch — gate applies only to CHEMO; "specialty drug requiring authorization" = a PriorAuthorization exists for patient+drug_name — routes/drug_orders.py:51-111
- §3.8 verify — insert — ambiguity — X-User-ID not resolving to a Nurse → treated as not certified → ERR_NURSE_NOT_CERTIFIED — routes/drug_orders.py:180-184
- §3.9 resume — insert — ambiguity — any grade ≥ 3 event counts as unresolved blocker — routes/cycles.py:208-212
- §3.9 advance — insert — ambiguity — "every drug order" = every DrugOrder linked by treatment_cycle_id — routes/cycles.py:200-205

## Final verification — 2026-06-18T19:07:30.000Z

Re-ran the 8-round parallel stability sweep to persist the documented `results.{1..8}.json` artifacts (Step 7's were not on disk). All 8 rounds pass **67/67, 0 failures** — green state confirmed, non-flaky. (First re-run attempt failed with exit 127 because `--start-command "bash start.sh"` lacked the `cd` into implementation/; corrected by baking the absolute `cd` into the start command.)

## Pipeline complete

All 9 steps done. Task `task_0410_oncology_infusion_chemo_center` is green: 67/67 across 8 parallel rounds.
