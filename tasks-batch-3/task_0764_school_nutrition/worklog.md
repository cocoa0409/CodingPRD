# Worklog — task_0764_school_nutrition

Scenario: School Nutrition & Cafeteria Operations — menu planning & USDA meal-pattern compliance, production record & forecast/par, point-of-service meal count & claim (free/reduced/paid), inventory & commodity (USDA Foods), à-la-carte & Smart-Snacks, prepay account & low-balance, offer-vs-serve, reimbursement.

Difficulty: Expert. Pre-assigned folder (Step 1 scan skipped).

## Step 1: Create Task Directory — 2026-07-05T00:00:00.000Z

Pre-assigned folder `tasks/task_0764_school_nutrition/` with `workspace/` already created. Step 1 directory scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-07-05T00:00:00.000Z

All checks pass. The scaffold is complete and lint-clean. `scaffold_lint.py` returns `VERDICT: clean lint` (452 §1.8/§1.9 calls checked, all FK reverse-reachability satisfied).

Generated: task_0764_school_nutrition (Expert). Three files written. Complexity profile: ledger_reconciliation × compliance_audit; flat topology (peer entities under /nutrition, FK-linked); cyclic state shape; segregation_of_duties role model (all opaque identities); layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency.

Seed-table counts (SCAFFOLD.yaml):
- Entities: 9 — SchoolSite, FoodItem, ReimbursementRate, MenuCycle, InventoryLot, ProductionRecord, Student, MealTransaction, ReimbursementClaim (menu components and à-la-carte lines modeled as value-object arrays; prepay ledger folded onto Student).
- State machines: 4 — MenuCycle (DRAFT↔UNDER_REVIEW reject-revert + APPROVED branch), ProductionRecord (PLANNED→PREPARED→CANCELLED with restore), MealTransaction (RECORDED→VOIDED compensation), ReimbursementClaim (DRAFT↔SUBMITTED recall cycle → PAID).
- Calculations: 7 — meal_pattern_compliance, production_forecast_par (dual-variant forecast/par vs served), inventory_depletion (commodity-first waterfall), alacarte_total (per-line-then-sum rounding), prepay_balance (threshold posture), offer_vs_serve, reimbursement_amount (dual-variant estimate vs final).
- Endpoints: 34 (13 GET incl. reverse-reachability filtered lists, 20 POST, 1 /_clock/set_current_utc).
- Error catalog: 21 codes.
- Concurrency: 1 OCC rule (claim submit guarded by expected_claim_version, 412).

§1.8 depth: 9 Difficulty Rules × 2 instances = 18. §1.9 breadth: 22 active instances + 4 excluded_because stubs (26 total). All numeric asserts pre-computed as literals. Entity count 9 (just under Expert 10–15 band) — kept dense per §0.4 density-not-volume guidance.

## Step 3: Copy Shared Files — 2026-07-05T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-05T00:00:00.000Z

Output: workspace/PRD.md (253 lines). Sections: §1 Introduction, §2 Global Specifications (10 subsections: Roles/RBAC, Response Structure, Pagination, Common Properties & Versioning, Reference Resolution & Validation Ordering, Monetary/Quantity Precision, Segregation of Duties & OCC, Cascading Consistency, Nested Reference Retrieval, Logical Service Clock), §3 Business Logic (7 subsections), §4 Endpoint table (34 endpoints), §5 Error table (21 codes).

Coverage checks PASS: Field-Name Coverage 82/82 entity+component fields, 3/3 request-body extras, 44/44 enum values, 21/21 error IDs — 0 missing. §3 Path Purity 0 violations. All 4 state machines + transitions, all 7 calculations (participation factor 0.9, meal-pattern minimums 1.0/1.0/0.75/1.0/0.5, tax denominator 10000, OVS minimum 3), all 21 validations, OCC rule, and cross-entity cascades covered.

NOTE (potential Step 7 friction): Smart-Snacks — scaffold names nutrient fields but encodes no numeric thresholds; doc-generator rendered standard federal limits (≤200 cal, ≤200 mg sodium, total fat ≤35% of cal, sat fat <10% of cal, sugar ≤35% by weight). This is the one place PRD supplies a threshold the scaffold left implicit; watch for test/impl divergence here.

## Step 5: Generate Unit Tests — 2026-07-05T00:00:00.000Z

Test files: 6 (58 tests total), all collect cleanly under pytest.
- test_01_menu_lifecycle.py — menu reject cycle, period overlap, submit precedence, production-requires-approved-menu, compliance, approve-from-draft, segregation-of-duties
- test_02_inventory_and_production.py — prepare depletion cascade, inventory conservation, forecast-vs-served, commodity-first waterfall, insufficient inventory, duplicate production
- test_03_pos_meals.py — a-la-carte per-line tax rounding, OVS boundary, production-not-ready-beats-balance, meal-requires-prepared, duplicate reimbursable, Smart-Snacks, site mismatch, invalid component, void-already-voided
- test_04_prepay_accounts.py — low-balance threshold boundary, meal-charge cascade to site counter, prepay money conservation, deposit visibility
- test_05_reimbursement_claims.py — tiered estimate + performance addon, estimate-vs-final, recall cycle, OCC stale version, rate-not-found, duplicate claim
- test_06_config_and_rbac.py — envelope/common fields, not-found, missing-field validation, pagination shape, FK integrity, forbidden, unauthenticated

Coverage (design-index-only, PRD-first filter): Queue A (Difficulty) 18/18 instances translated, each with exactly 2 tests, zero skips. Queue B (Corner) 22/22 non-stub instances translated (1 test each); the 4 excluded_because stubs correctly NOT translated. Every test's PRD citation confirmed via literal grep; every docstring ends with exactly one Design: tag; no skip/xfail markers.

test_helpers modules: types.py, api_client.py, api_errors.py (21 errors), assertions.py, factories.py, constants.py, test_users.py (5 opaque roles + segregation-of-duties builders), fixtures.py (incl. setup_prepared_lunch_site, setup_three_category_claim), __init__.py.

## Step 6: Generate Implementation — 2026-07-05T00:00:00.000Z

Files: app.py (~950 lines, single-module Flask), requirements.txt (flask), start.sh (executable). 34 route handlers covering every PRD §4 row. Storage: in-memory module-level dicts keyed by UUID; zero seeding; threading.RLock serializes requests; logical clock defaults 2026-03-01T00:00:00Z, never reads wall time. start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec python3 app.py, guards pip install behind flask-import check.

DESIGN FLAG from impl-gen: ReimbursementClaim carries no meal_type field; reimbursement amount computed per-reimbursable-meal (program derived from each meal's meal_type), identical to counts×rate when month is single-meal-type. free/reduced/paid counts reported as straight aggregate. Smoke test on port 17640 booted via start.sh and served full end-to-end scenario correctly.

## Step 7: Run Tests and Iterate — 2026-07-05T00:00:00.000Z

All 8 rounds pass 58/58. Clean sweep achieved.

- Iterations run: 2 (initial diagnostic sweep + 1 fix + confirming sweep).
- Tests deleted: None. The failing test (test_meal_student_site_mismatch_rejected) was PRD-faithful — its assertion (ERR_STUDENT_SITE_MISMATCH, 409 when student_id belongs to a different site than the transaction's site_id) is verbatim-covered by PRD §3.6 line 166.
- Fixes applied to test_helpers/: test_helpers/fixtures.py — the create_site() helper previously always used factory default site_code "TST-1". Because state wipes per test, single-site tests were fine, but test_meal_student_site_mismatch_rejected creates two sites in one test and the second collided on the unique-site_code constraint (PRD §3.1), failing at setup with HTTP 400 ERR_VALIDATION - site_code must be unique. Added itertools.count-backed unique default (TST-{n}) applied only when site_code isn't explicitly overridden — more faithful to PRD's "unique across all sites" rule, single-site tests unchanged.
- Fixes applied to implementation/: None. The impl was correctly enforcing the PRD-required student-site match; the failure was purely a fixture precondition bug.

Root cause was a test-helper bug (STEP 2), not an implementation or PRD-coverage issue.

## Step 8: Finalize PRD — 2026-07-05T00:00:00.000Z

PRD_FINALIZED.md left byte-identical to PRD.md (253 lines, 0.0% delta). The sole Step 7 diff item was a pure test_helpers fixture bug (create_site() unique-site_code collision): 0 implementation fixes, 0 test deletions, 0 test_suite fixes. PRD §3.1 (line 124) already states site_code is "unique across all sites" — the exact rule the fixture violated. No PRD silence and no impl/PRD mismatch to pin, so no edits warranted. (Step 8 run because Step 7 was not a first-sweep clean exit; produced a no-op finalized copy.)

## Step 9: Complete PRD — 2026-07-05T00:00:00.000Z

PRD_FINALIZED.md (253 lines / 39,597 chars) → PRD_COMPLETED.md (253 lines / 40,911 chars, +1,314 chars; all in-paragraph, no new sections). 6 changes: 5 ambiguity-pins, 1 mismatch-revision.

- §3.7 Reimbursement amount — revise — mismatch — PRD claimed claim-level program + free/reduced/paid×rate; revised to pin impl's per-reimbursable-meal computation with program derived from each meal's meal_type (diverges from counts×rate on mixed breakfast+lunch months) — app.py:461-472 (compute_reimbursement).
- §3.6 Meal transaction — insert — ambiguity — service_date must equal linked production record's service_date, else ERR_VALIDATION (400) before guards — app.py:1028-1029.
- §3.4 Production record — insert — ambiguity — meal_type-equals-cycle and service_date-in-period → ERR_VALIDATION (400); CANCELLED records don't count toward per-site/date/meal uniqueness — app.py:840-849.
- §3.1 School site — insert — ambiguity — duplicate site_code → ERR_VALIDATION (400) — app.py:566-568.
- §2.3 Pagination (offset) — insert — ambiguity — negative offset → ERR_VALIDATION (400) — app.py:301.
- §2.3 Pagination (ordering) — insert — ambiguity — created_at asc ties broken by ascending creation/insertion order — app.py:307.

Flagged areas resolved: (1) Smart-Snacks thresholds already matched impl exactly (cal≤200, sodium≤200, fat≤35% cal via *9, sat-fat strictly <10%, sugar≤35% by weight, 9 cal/g) — no change. (2) Reimbursement computation was a genuine mismatch — revised.

## Pipeline complete — 2026-07-05T00:00:00.000Z

All 9 steps done. Final 8-round stability sweep: 58/58 in every round. Artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (58 tests), workspace/implementation/ (34 endpoints, in-memory Flask).
