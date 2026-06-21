# Worklog — task_0187_funeral_home_cemetery

## Step 1: Create task directory — 2026-06-06T05:52:52.000Z

Created `./tasks/task_0187_funeral_home_cemetery/` and `./tasks/task_0187_funeral_home_cemetery/workspace/` (pre-allocated directory, index scan skipped per instructions).

## Step 2: Generate Scaffold (Expert) — 2026-06-06T06:21:00.000Z

Generated all three scaffold artifacts for **task_0187_funeral_home_cemetery** at **Expert** difficulty, lint-clean (`VERDICT: clean lint` — 414 §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable).

**Files written** (all under `tasks/task_0187_funeral_home_cemetery/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Complexity profile:** primary archetype `compliance_audit` + secondary `ledger_reconciliation`; **flat** topology (`api_prefix: ""`, peer collections joined by FKs); `segregation_of_duties` role model; layers: dual-variant calc, cascading side-effects, derived-field reconciliation, OCC, temporal windowing.

**Scaffold inventory:**
- **11 entities**: FuneralHome, GplItem, Case, StatementLine, Contract, TrustDeposit, InsuranceAssignment, Plot, Venue, Event, Permit
- **State machines**: 7 entity-blocks over 6 entities, 27 transitions. Non-linear shapes: Case carries **parallel dimensions** (arrangement_status × interment_status); Contract is **cyclic** (PENDING_FUNDING↔DRAFT reopen loop); Permit is **branching-with-revert** (APPLIED→{ISSUED,REJECTED}, REJECTED→APPLIED).
- **6 calculations**: statement_total (provisional/final dual-variant + per-line-then-sum rounding), contract_funded_amount (preneed projection vs at-need chronological dual-variant), trust_required_principal (conditional/tiered/floored), projected_trust_earnings, plot_charge (preneed-locked vs at-need-live), trust_balance_reconciliation (conserved quantity).
- **12 validations** (priority-ordered: auth→authz→existence→request→OCC→state→disclosure-safety→segregation→referential→temporal→empty-set→fiscal)
- **55 endpoints**, **27 error codes** (every error triggerable; verified), **5 roles** (Admin, Arranger, TrustOfficer, CemeteryClerk, Registrar), **2 concurrency rules** (plot-reserve and contract-mark-funded OCC, both 412).

**Design instances:** §1.8 = **18** (9 rules × 2, each meeting its §0.5 differentiation clause; all formula-derived asserts precomputed as literals). §1.9 = **49** total (**42 active** test recipes + **7 `excluded_because` stubs**, every stub pointing at an existing §1.8 instance by name). No duplicate names across the union; all grounds resolve to declared §1.1–§1.7 elements; no forbidden concurrency vocabulary; tie-breaks use `created_at`, never `id`.

## Step 3: Copy shared files — 2026-06-06T06:21:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-06T06:30:00.000Z

Generated `workspace/PRD.md` — prose PRD for the Funeral Home & Cemetery API. ~304 lines / 6,625 words.

Sections: §1 Introduction (compliance-audit + reconciling-ledger framing, FTC Funeral Rule, segregation of duties, two case axes); §2 Global Specs (RBAC all 5 roles, fixed §2.2 envelope, pagination, common props, hierarchical consistency/cascades, money/rounding, OCC, conserved trust ledger, validation ordering); §3 Business Logic (11 lifecycle subsections); §4 Endpoint table; §5 Error table.

Coverage verified: entities 57/57 fields, request_body 36/36, query_params 8/8, path_params 11/11; all 55 endpoints; all 27 error IDs; all 6 calculations as prose; all state-machine transitions incl. cancel cascade + interment cascade; both OCC rules; 12-level validation ordering.

Hard Contracts: Contract 1 (field coverage) PASS; Contract 2 (rule coverage, 29 phrasings) PASS; Contract 3 (§3 path purity, 0 violations) PASS. Difficulty/corner design files NOT read.

## Step 5: Generate Unit Tests — 2026-06-06T06:46:00.000Z

Generated test infrastructure entirely from the two design indices. 78 test functions total.

**Coverage**
- Queue A (Difficulty): 36 tests, all 18 instances (9 rule_ids × 2), each ≥2 tests. No instances skipped — every difficulty instance verbatim-covered by PRD with uniquely-derivable outcome.
- Queue B (Corner): 42 tests, one per non-stub instance, all 42 non-stub instances across entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting/consistency_model.
- 7 stubs skipped (not translated) — all carry excluded_because/difficulty_instance pointers resolving to real Difficulty instances: error_case_cancel_void_release_cascade, error_statement_total_per_line_rounding, error_trust_required_formula, error_state_vs_fiscal_priority, error_schedule_conflict_chapel, dual_variant_funded_amount, case_cancel_cascade_endtoend.

Verification: 18/18 Difficulty + 42/42 Corner tag cross-checks pass; 99 PRD citations verbatim-present; all api.* calls resolve; no scaffold leakage; no skip/skipif/xfail; all byte-compile.

Files — test_helpers/: __init__, types, api_client, api_errors, assertions, factories, constants, test_users, fixtures. test_suite/: conftest + test_01..test_07. All 5 roles opaque (PRD §2.1); test_users.make_headers(user_id, role) controls distinct/identical X-User-ID for segregation tests.

## Step 6: Generate Implementation — 2026-06-06T06:46:00.000Z

Built Python + Flask implementation at workspace/implementation/. 24 source files + launcher.

Files: start.sh (guarded pip-install, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (blueprints, error handlers, 0.0.0.0:$PORT bind), db.py (11 in-memory dicts keyed by id, UUID/timestamp/version stamping), clock/response/errors/middleware/validate/serialize foundation, services/calc.py + services/cascade.py + services/lookup.py, routes/ (11 modules).

55 endpoints implemented (matches §1.5 / PRD §4). start.sh reads PORT (default 10000), binds 0.0.0.0, foreground exec; pip install guarded by import check. Storage strictly in-memory dicts, zero seeding.

Notable: Decimal ROUND_HALF_UP for tax/trust, ROUND_FLOOR for 3% projected earnings; per-line-rounded-then-summed (101362-vs-101363 boundary). Computed fields recomputed lazily at serialization. Validation ordering via decorator (auth→authz) then existence→request→OCC→state→business. **Conserved trust ledger / void cascade: the one place PRD prose overrode scaffold literal side-effect text** — PRD §2.8 conserved formula (POSTED PRINCIPAL − POSTED REFUND) requires net-zero; for PRINCIPAL keeps original POSTED + adds POSTED REFUND leg (nets 0); for EARNINGS drops original out of POSTED set so credited_earnings returns to 0. Polymorphic events: chapel = buffered half-open interval on Venue; graveside = whole-day exclusivity on Plot.

Validated against 97 design-literal assertions — all passing. No pytest run yet (suite generated concurrently).

## Step 7: Run Tests and Iterate — 2026-06-06T06:55:00.000Z

**Iterations run:** 2 sweeps (1 diagnostic baseline at 75/78, 1 verification at 78/78).

**Diagnosis:** All 3 failures were identical and deterministic (failed in all 8 baseline rounds), all in event scheduling:
- `test_chapel_booking_beyond_buffer_succeeds`
- `test_graveside_different_day_same_plot_succeeds`
- `test_cancel_event_frees_interval_then_reschedule_succeeds`

Each called `validate_success(api.create_event(...))`, which defaults to asserting HTTP 200. But `POST /cases/{caseId}/events` creates a new, distinct Event resource, so the PRD-faithful implementation correctly returns **201 Created**. Per the diagnostic protocol this is a STEP 2 test bug (assertion mistranslation), not an implementation defect.

- STEP 1a COVERAGE: PRD §4 states verbatim "Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource, and all read operations, return `200 OK`." Scheduling an event creates a new Event — covered.
- STEP 1b UNIQUE DERIVABILITY: A PRD-only implementer uniquely arrives at 201 for event creation. The companion conflict tests already passed (use validate_error); only success-path companions had the bug. Entity-CRUD create tests already correctly used expected_status=201, confirming 201 is the suite's established contract for create endpoints.

**Tests deleted:** None. (No PRD-silence or non-derivability; the rule is verbatim and uniquely determined.)

**Fixes applied to test_suite/** (assertion mistranslation → made tests more faithful to PRD §4):
- `test_03_gates_boundaries_overlap.py` (chapel-beyond-buffer success, line ~366): added `expected_status=201` to the `validate_success(api.create_event(...))` call.
- `test_03_gates_boundaries_overlap.py` (graveside-different-day success, line ~418): added `expected_status=201`.
- `test_07_endpoints_rbac_concurrency.py` (cancel-then-reschedule success, line ~46): added `expected_status=201`.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation was already PRD-faithful (event creation returns 201, conflict detection returns ERR_SCHEDULE_CONFLICT, cancellation frees the interval). No implementation check was weakened or added.

**Final state:** 8/8 parallel rounds at 78/78 passing, no flakiness.

## Step 8: Finalize PRD — 2026-06-06T07:00:00.000Z

No edits needed. PRD_FINALIZED.md is byte-identical to PRD.md (304 lines, 0% delta).

Rationale: the entire Step 7 diff consisted of three test-assertion mistranslations in success-path event-scheduling tests — each used validate_success(api.create_event(...)) defaulting to HTTP 200, while POST /cases/{caseId}/events creates a new distinct Event and correctly returns 201. Step 7 fixed the fixtures (added expected_status=201); no implementation/PRD change needed. PRD §4 (line 214) already verbatim and uniquely determines this: "Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource, and all read operations, return `200 OK`."

Pre-edit search: enumerated all 41 ok_object/ok_array return sites across every route file — every create returns 201, every modify/transition/read returns 200; all consistent with PRD §4. No edit committed (manufacturing one would risk a new mismatch with no corresponding PRD silence).

## Step 9: Complete PRD — 2026-06-06T07:10:00.000Z

Full PRD-vs-implementation scan. PRD_COMPLETED.md is a minimal in-paragraph patch over PRD_FINALIZED.md.

**Source vs completed:** PRD_FINALIZED.md 304 lines / 45,966 chars → PRD_COMPLETED.md 304 lines / 48,623 chars. Char delta +2,657 (8 paragraphs revised in place; no lines/sections/paragraphs added).

**Counts:** 4 ambiguity-pins, 4 mismatch-revisions.

**Per-change:**
- §2.8 (Conserved Trust Ledger) — revise — mismatch — void reversal is per-kind: principal deposits stay POSTED with a new compensating REFUND leg; earnings deposits flipped to REFUNDED with no compensating deposit (PRD claimed every deposit gets a compensating refund + original marked REFUNDED) — services/cascade.py:35-56
- §3.11 (Void-and-Release Cascade, L2) — revise — mismatch — same per-kind reversal detail — services/cascade.py:40-55
- §3.1 (GPL catalog) — revise — mismatch — `active` flag is informational; adding a statement line does not gate on it — routes/cases.py:175-208
- §3.3 (Issuing the GFS) — revise — mismatch — FTC disclosure gate evaluated ahead of DISCLOSED-state check; undisclosed non-DISCLOSED case yields ERR_DISCLOSURE_REQUIRED (not ERR_INVALID_STATE); pinned order state→contract-required→empty-statement — routes/cases.py:102-123
- §2.9 (Validation Ordering) — insert — mismatch — issue-GFS exception to the general sixth-before-seventh ordering — routes/cases.py:102-106
- §2.9 (Validation Ordering) — insert — mismatch — create operations validate body fields before resolving body-supplied parent (funeral_home_id), so malformed create body yields ERR_INVALID_REQUEST even if parent missing — routes/gpl_items.py:17-27, cases.py:21-37, plots.py:18-23, venues.py:17-21
- §3.8 (Plot Reservation) — insert — ambiguity — reserving for CANCELLED/COMPLETED target case yields ERR_INVALID_STATE; check order case existence→OCC→plot-AVAILABLE→case active-state — routes/plots.py:71-84
- §3.8 (Plot Release) — insert — ambiguity — releasing a plot whose holding case is INTERRED yields ERR_INVALID_STATE — routes/plots.py:100-103
- §3.9 (Scheduling) — insert — ambiguity — chapel conflict computes [start, end+buffer) for both new and existing; back-to-back gap of exactly chapel_buffer_minutes does not conflict — routes/events.py:78-92
- §3.9 (Scheduling) — insert — ambiguity — graveside date taken in UTC, supplied ends_at discarded, stored event's ends_at is null — routes/events.py:57-71,95-96

## Pipeline complete — 2026-06-06T07:10:00.000Z

All 9 steps done. Final test state: 8/8 parallel rounds at 78/78 passing. Artifacts: SCAFFOLD.yaml (+DIFFICULTY+CORNER design), worklog.md, test_helpers/, test_suite/ (78 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
