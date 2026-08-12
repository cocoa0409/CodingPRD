# Worklog — task_1202_manufacturer_patient_assistance_program

## Step 1: Create Task Directory — 2026-08-11T19:27:39.669Z

Pre-assigned output folder `tasks/task_1202_manufacturer_patient_assistance_program` with `workspace/` subdirectory already exists on disk; per instruction, Step 1 auto-index scan skipped and treated as done. Difficulty parameter: "generate task hard than expert level!" (passed through to Step 2 scaffold generator).

## Step 2: Generate Scaffold — 2026-08-11T20:29:38.425Z

All three scaffold artifacts generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/`. (No sibling task was opened; the design is fresh from the scenario text plus the skill spec.)

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys):
- **16 entities** — AssistanceProgram, BudgetPeriod, Patient, Prescriber, EligibilityScreening, ScreeningDocument, Application, Enrollment, ChangeOfCircumstance, Appeal, CopayCard, InventoryLot, Shipment, ShipmentLine, DispenseEvent, ReconciliationRun. Flat topology, all linkage via canonical `FK ->` fields.
- **11 state machines / 38 transitions** — cyclic revision loops (Screening REJECTED→DRAFT), info-request cycle (Application), enrollment suspend/reinstate cycle, system sweeps (STALE/EXPIRED), and compensation paths (shipment cancel/release, return-to-quarantine).
- **10 calculations** — incl. two dual-variant pairs (committed-vs-disbursed utilization on the budget domain; YTD-annualized vs prior-year income on the screening domain), mode-(a) nested-min+conditional benefit cap, mode-(b) pinned per-line vs per-event rounding (7407 vs 7408 cents for identical units), FEFO waterfall allocation, reconciliation variance, inclusive temporal windows.
- **12 ordered validation priorities**, **68 endpoints** (incl. `/_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` default and `/_system/run-daily-sweep`), **59 error codes**, **6 roles** (segregation-of-duties between CaseWorker and AppealsOfficer; Patient/Prescriber are entity-backed), **2 OCC concurrency rules** (renewal-create on `Enrollment.version`, config-update on `AssistanceProgram.version`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 21 instances, every rule ≥2 with the required differentiators: dual_variant 2 (different entity domains), combinatorial 2 (modes a and b), non_linear_sm 2 (different entities), cascade 2 (depth-4 appeal overturn, depth-3 circumstance terminate), priority_conflict 3 (state/fiscal, safety/fiscal, temporal/referential), boundary 3 (90.00% inclusive posture, 400.00 FPL inclusive, appeal day-30 inclusive), cross_entity 3 (three distinct pairs), temporal_overlap 2 (closed-interval adjacency vs expiry-buffer semantics), compensating_invariant 2 (units vs money). All numeric asserts pre-computed (e.g., cap 360000, fpl '383.39'/'402.56', variance −20000, renewal dates 2026-07-30..2026-10-27).

**SCAFFOLD_CORNER_DESIGN.yaml** — 53 instances (49 active + 4 excluded stubs) across all 9 guide sections.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (68 endpoints, 16 entities, 21 §1.8 + 49 §1.9 active instances, 946 calls scanned). One FK_REVERSE_UNREACHABLE violation found and fixed during the run (added `renewal_of_enrollment_id?` filter to `GET /pap/applications`). Auxiliary audit: no forbidden concurrency vocabulary, all 59 errors referenced, all grounds resolve, instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-08-11T20:30:06.261Z

Copied `./INSTRUCTION.md` → `tasks/task_1202_manufacturer_patient_assistance_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T20:37:59.425Z

The PRD has been generated at `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/workspace/PRD.md`. The difficulty/corner design files were not touched.

## What was generated

**Structure** (skeleton designed from the domain, not copied from the example):
- §1 Introduction (2 paragraphs: fiscal-trust framing, then the three compliance pressures — duplication prevention, forward-looking commitment, segregation of duties)
- §2 Global Specifications, 11 subsections: RBAC with per-role `identity` translation (entity-backed `Patient`/`Prescriber` vs. opaque staff roles) → verbatim §2.2 response envelope → pagination → common resource properties (including the `DispenseEvent` exception: no `updated_at`, no `version`) → the logical clock (`2026-05-01T00:00:00Z` startup default, closed-interval date windows) → money/rounding discipline (integer cents, 4-fraction-digit unit-cost strings, round-half-up, pinned per-line/per-event rounding with the 12.3456 → 7408-vs-7407 example) → the 12-tier validation priority cascade → OCC (`expected_program_version` / `expected_enrollment_version`, `ERR_STALE_VERSION` 412, renewal creation advancing the enrollment version) → idempotent shipment creation → nested-resource left-to-right 404 resolution → conserved-budget ledger and posture derivation (90.00/100.00 inclusive thresholds, committed vs. disbursed basis divergence)
- §3 Business Logic, 8 subsections organized by lifecycle: programs/budget periods → intake/screening/documents (FPL constants 1,565,000 + 550,000/member, 400.00/500.00 thresholds, both income variants) → application review/approval (pinned fiscal-gate order, pinned benefit-cap evaluation order, renewal commitment release before the sufficiency test) → appeals (depth-4 cascade, SoD, fresh gate re-evaluation) → enrollment renewal/suspension/termination/circumstances → copay cards and symmetric duplication guards → inventory/FEFO/shipment lifecycle → dispensing/reconciliation/daily sweep (pinned 3-phase sweep order)
- §4 endpoint table (4 columns, 61 endpoints) and §5 error catalogue (2 columns, 59 error IDs)

**Hard-contract verification (all PASS, checked mechanically):**
- Contract 1 field coverage: 0 missing of ~140 required names (entity fields, request bodies, query params, utilization/sweep/clock output fields)
- Contract 2 rule coverage: all 59 error IDs appear in §2/§3 prose with trigger conditions; all state values (including `APPLIED` and `QUARANTINED`, added in a repair pass) named; all transitions, side-effect cascades, calculation formulas (annualized income, FPL, benefit cap, FEFO, per-line/per-event valuation, utilization/posture, commitment release, reconciliation variance, temporal windows), OCC rules, and validation priority ordering expressed in prose
- Contract 3 §3 path purity: 0 backticked tokens in §3 start with `/` or are HTTP methods — endpoints referenced via state-transition framing, role+verb, or capability description; §4 table covers all 57 unique scaffold paths

## Step 5: Generate Unit Tests — 2026-08-11T21:10:28.290Z

Generation complete and verified. Summary:

## Deliverables

**`test_helpers/`** (9 files, all importing cleanly):
- `types.py` — 16 entity TypedDicts + 17 status/role enums; `DispenseEvent` correctly carries only `id`/`created_at` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (57 methods incl. `/_clock` and `/_system` drivers)
- `api_errors.py` — all 59 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_lot_units_conserved` / `assert_program_budget_conserved` invariant checkers
- `factories.py` — 13 payload factories (canonical PAP-LYMX program config as default)
- `constants.py` — FPL figures, 90.00/100.00 posture thresholds, clock default, period window
- `test_users.py` — shared constants for opaque roles; mandatory `make_patient_headers` / `make_prescriber_headers` builders for the two entity-backed roles
- `fixtures.py` — tiered composites: `setup_program_with_period`, `setup_submitted/verified_screening`, `setup_under_review_application`, `setup_approved_enrollment`, `setup_denied_application`, `setup_filed_appeal`, `setup_reserved/dispatched/delivered_shipment`, `setup_suspended_enrollment`, `setup_second_patient_application`, all threading entity-backed identity

**`test_suite/`** — conftest + 6 files, **90 tests**:

| File | Tests |
|---|---|
| test_01_api_envelope_and_access.py | 5 |
| test_02_programs_budgets_utilization.py | 11 |
| test_03_screenings_documents_fpl.py | 19 |
| test_04_applications_appeals.py | 23 |
| test_05_enrollments_renewal_copay.py | 11 |
| test_06_shipments_inventory_reconciliation.py | 21 |

## Coverage
- **Queue A (Difficulty): 21/21 instances, exactly 2 tests each (42 tests)** — dual-variant (income basis, utilization bases), combinatorial cap formula, per-line vs per-event rounding, both cyclic state machines, both cascade chains, all three priority-pair conflicts (legitimate because PRD §2.7 explicitly enumerates the tier order), all boundary instances, cross-entity gates, temporal overlap, both conservation invariants.
- **Queue B (Corner): 48/49 non-stub instances, 1 test each (48 tests)**. All 4 `excluded_because:` stubs verified to resolve to real difficulty instances and not translated.

## Skipped instance (gap left as gap, no placeholder)
- `Corner/entities/screening_computed_field_input_ignored` — its trigger depends on the server *accepting* a request body containing the computed field `fpl_percent`. PRD §2.7/§3.2 pin required/conditional fields but never state whether extraneous non-input fields are ignored or rejected; a strict-schema implementer would 400 the trigger while remaining PRD-faithful. Fails unique derivability → skipped.

## Verification passes
- All files compile; every test module imports with the task dir on PYTHONPATH.
- Tag audit: 90/90 tests carry exactly one `Design:` line at docstring end; all tags resolve to real instances; zero orphans.
- Citation sweep: 127 quoted fragments (≥6 words) all survive literal grep of `PRD.md` (em-dash/backtick exact).
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated comments/docstrings.

## Step 6: Generate Implementation — 2026-08-11T21:10:28.290Z

## Summary

Created a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/workspace/implementation/`:

**Files created**
- `start.sh` — executable launcher; guards `pip install` behind `import flask`, then `exec python3 app.py`
- `requirements.txt` — `flask>=2.3,<4`
- `app.py` — all routes, state machines, calculations, validations (~1300 lines)
- `store.py` — in-memory store + logical clock (starts at `2026-05-01T00:00:00Z`); no seeding
- `util.py` — envelope helpers, pagination, auth, ID/timestamp generators, decimal parsing
- `errors.py` — `ApiError` exception class

**Coverage**
- **Entities (16):** AssistanceProgram, BudgetPeriod, Patient, Prescriber, EligibilityScreening, ScreeningDocument, Application, Enrollment, ChangeOfCircumstance, Appeal, CopayCard, InventoryLot, Shipment, ShipmentLine, DispenseEvent (no `updated_at`/`version` per spec), ReconciliationRun
- **State machines (10):** screening DRAFT/SUBMITTED/VERIFIED/REJECTED/STALE with revise loop, document PENDING→ACCEPTED/REJECTED, application SUBMITTED/UNDER_REVIEW/MORE_INFO_REQUESTED/APPROVED/DENIED/SUPERSEDED (incl. claim, info cycle, appeal overturn cascade), enrollment ACTIVE/SUSPENDED/TERMINATED/EXPIRED/CLOSED_RENEWED, circumstance REPORTED→APPLIED/DISMISSED with cascade to enrollment, appeal FILED→UPHELD/OVERTURNED with full gate re-evaluation, copay card ACTIVE/SUSPENDED/TERMINATED, shipment RESERVED/DISPATCHED/DELIVERED/CANCELLED/RETURNED with lot-quantity movements, lot ACTIVE→QUARANTINED/EXPIRED/UNDER_INVESTIGATION, budget period OPEN→CLOSED
- **Calculations (9):** `annualized_household_income` (YTD vs PRIOR_YEAR), `fpl_percent_and_eligibility` (FPL_BASE 1565000, +550000/person, 400/500 thresholds, round-half-up 2dp), `enrollment_benefit_cap_cents` (unit conversion → product axis → min with annual cap → underinsured scaling), `fefo_lot_allocation` (expiry ASC, `_seq` tiebreak, strict buffer, all-or-nothing), `shipment_value_cents` (per-line rounding pinned), `dispense_event_value_cents` (per-event rounding pinned), `program_utilization_and_posture` (committed+disbursed/allocated, 90/100 inclusive), `enrollment_commitment_release`, `reconciliation_variance` (per-lot rounding, CLEAN/VARIANCE_FLAGGED, UNDER_INVESTIGATION cascade)
- **Endpoints: 49 routes registered** — 5 programs, 4 budget-periods, 2 patients, 2 prescribers, 6 screenings, 3 documents, 8 applications, 3 appeals, 5 enrollments, 4 circumstances, 5 copay-cards, 6 inventory-lots, 9 shipments (incl. lines + dispense-events), 3 reconciliation-runs, 2 system (`_clock/set_current_utc`, `_system/run-daily-sweep`)

**Key design choices verified**
- Validation priority order followed (auth → role → schema → ownership → existence → OCC → state → duplication → temporal → constraint → cross-ref → fiscal)
- OCC via `expected_program_version` (PUT programs) and `expected_enrollment_version` (renewal-applications) returning `ERR_STALE_VERSION` 412
- Idempotency-Key (header or body field) — replay verified returning identical shipment id
- Posture thresholds inclusive (90.00 → RESTRICTED, 100.00 → EXHAUSTED), `'0.00'` when allocated=0
- Closed-interval date geometry for budget-period overlap (shared day = overlap, one-day adjacency allowed)
- Money as integer cents, unit costs as 4-fraction-digit decimal strings, Decimal + ROUND_HALF_UP throughout
- Smokescreen verified end-to-end: program/period/patient/screening/docs/verify/apply/claim/approve → enrollment with committed=100000 → ship (FEFO, idempotent replay) → dispatch → deliver (money moved committed→disbursed) → dispense (per-event rounding)

## Step 7: Run Tests and Iterate — 2026-08-11T21:21:06.301Z

All 8 rounds pass 90/90. Clean exit achieved.

## Summary

**Iterations run:** 2 (initial sweep surfaced 3 deterministic failures, identical across all 8 rounds; second sweep after fixes: 8/8 rounds × 90/90 passed).

**Tests deleted:** None. All three failing tests traced to verbatim PRD prose with uniquely derivable outcomes:
- `test_ytd_basis_projects_annualized_run_rate` / `test_prior_year_basis_can_diverge_to_ineligible` — PRD §3.2 verbatim: "under `YTD_ANNUALIZED`, the year-to-date income is divided by the months elapsed, multiplied by 12, and rounded half up to whole cents ... under `PRIOR_YEAR`, the filed prior-year total is used verbatim".
- `test_stale_screening_reported_before_mismatch` — PRD §2.7 verbatim tier list: tier 9 Temporal windows (`ERR_SCREENING_STALE`) evaluated before tier 11 Cross-reference agreement (`ERR_SCREENING_MISMATCH`).

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/test_helpers/factories.py` — `create_screening_payload`: after merging overrides, prune *defaulted* conditional fields inconsistent with the final basis/status (`prior_year_income_cents` dropped when basis is `YTD_ANNUALIZED`; `ytd_income_cents`/`ytd_months_elapsed` dropped when `PRIOR_YEAR`; `insurance_coverage_pct` dropped unless `UNDERINSURED`). Explicit caller overrides are preserved. Why: the factory's defaults leaked a wrong-basis field into YTD payloads, and PRD §3.2 ("Supplying a conditional field for the wrong basis or status ... fails schema validation as `ERR_INVALID_REQUEST`") makes the implementation's 400 the correct behavior — a fixture bug, not an implementation bug.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/workspace/implementation/app.py` — `create_application`: reordered validation to match the PRD §2.7 priority cascade. `ERR_SCREENING_MISMATCH` (tier 11, cross-reference agreement) was being raised before `ERR_SCREENING_NOT_VERIFIED` (tier 7) and `ERR_SCREENING_STALE` (tier 9); it now runs after state-legality, temporal-window, and uniqueness (`ERR_APPLICATION_ALREADY_EXISTS`, tier 10) checks.

## Step 8: Finalize PRD — 2026-08-11T21:27:36.502Z

Done. `PRD_FINALIZED.md` is written with exactly one minimal revision.

## Summary

**Line counts / delta:** PRD.md = 361 lines, PRD_FINALIZED.md = 361 lines (0% line delta). The single change is an in-place sentence insertion within line 166 (§3.3); +433 characters.

**Changes (one bullet per change):**
- **§3.3 (Applications: From Submission to Approval)** — revise — inserted one sentence into the fresh-application paragraph pinning the evaluation order when several creation-time checks fail at once on a fresh filing: `VERIFIED` state first, then validity window (`ERR_SCREENING_STALE`), then the per-patient-and-program uniqueness rule (`ERR_APPLICATION_ALREADY_EXISTS`), then cross-reference agreement (`ERR_SCREENING_MISMATCH`) last, explicitly per the §2.7 cascade — `implementation/app.py:851-866` (`create_application`, the Step 7 reorder site).

**Step 7 items that required no PRD edit:**
- *`test_helpers/factories.py` fixture fix* — pure fixture bug. PRD §3.2 already pins verbatim: "Supplying a conditional field for the wrong basis or status, or omitting one that applies, fails schema validation as `ERR_INVALID_REQUEST`." Impl `create_screening` (app.py:436-463) matches exactly (rejects `prior_year_income_cents` under `YTD_ANNUALIZED`, ytd fields under `PRIOR_YEAR`, and `insurance_coverage_pct` unless `UNDERINSURED`).
- *`test_ytd_basis_projects_annualized_run_rate` / `test_prior_year_basis_can_diverge_to_ineligible`* — PRD §3.2 verbatim already determines both variants; impl `compute_screening_fields` (app.py:394-405) matches (YTD: income/months×12 rounded half up; PRIOR_YEAR verbatim).

**Per-edit pre-edit search log:**
- (a) Subject: relative evaluation order of the four fresh-application creation checks (`ERR_SCREENING_NOT_VERIFIED`, `ERR_SCREENING_STALE`, `ERR_APPLICATION_ALREADY_EXISTS`, `ERR_SCREENING_MISMATCH`).
- (b) Impl paths enumerated and read/grepped: `create_application` (app.py:831-881 — VERIFIED→STALE→ALREADY_EXISTS→MISMATCH, the Step 7 fix); `_run_approval_gates` (app.py:786-828) plus both callsites (line 984 `decide_application`, line 1091 appeal decision) — no uniqueness/mismatch checks on those paths; `create_renewal_application` (app.py:1133-1196 — checks MISMATCH *first*, matching §3.5 prose verbatim); `reinstate_enrollment` (app.py:1218-1243 — MISMATCH first, matching §3.5 prose). A grep over all four error ids confirmed these are the only raise sites. PRD-side mentions checked: §2.7 tiers (lines 103-115), §3.3 (line 166), §3.5 (lines 188, 192), §5 catalogue.
- (c) Wording adjustment: scoped the inserted sentence with "on a fresh filing" (the paragraph already defers renewals to §3.5) so it asserts nothing about renewal/reinstate paths, where the impl legitimately evaluates mismatch first; phrased tier-10 as "the per-patient-and-program uniqueness rule" to avoid redefining the rule. §3.5 prose and §2.7 tier list left verbatim since both already match the impl paths they govern.

## Step 9: Complete PRD — 2026-08-11T21:49:22.607Z

# Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1202_manufacturer_patient_assistance_program/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, aligning every passage where the PRD was silent or divergent with the behavior `implementation/` (Flask app in `app.py`, helpers in `util.py`, store in `store.py`) actually exhibits. All edits are in-paragraph inserts/revisions; no new sections; no behavior invented.

**Size delta:** 361 → 362 lines; 60,293 → 64,198 chars (**+3,905 chars**, +3,929 bytes).

**Counts:** 35 changes total — **24 ambiguity-pins**, **11 mismatch-revisions** (one pin, #23, also resolves a cascade mismatch within it).

- §2.2 — insert — ambiguity — unknown route / unsupported method → `ERR_NOT_FOUND` (404) in the standard envelope — app.py:68-77
- §2.3 — insert — ambiguity — out-of-range/non-numeric `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — util.py:161-176
- §2.5 — revise — mismatch — clock capability "sets" any supplied instant, not only "advances" — app.py:2014-2023
- §2.7 tier 3 — revise — mismatch — negative `actual_on_hand` fails as `ERR_INVALID_QUANTITY`, not `ERR_INVALID_REQUEST` — app.py:1929-1930
- §2.7 tier 4 — insert — ambiguity — path-identifier existence resolves before the ownership comparison (per §2.10) — app.py:535-539, 589-593, 941-944
- §2.7 tier 10 — revise — mismatch — dropped "destination" (impl evaluates destination rules before state/quantity checks) — app.py:1627-1633
- §2.7 tier 11 — revise — mismatch — dropped prescriber clause; `ERR_PRESCRIBER_REQUIRED` is a destination-rule error evaluated earlier, prescriber resolvability is `ERR_NOT_FOUND` — app.py:1630-1633, 1660-1661
- §2.7 — insert — ambiguity — endpoint-section sequences govern over the generic tier order; decision-branch conditional fields (`decision_reason`, `rejection_reason`) validated when the branch is taken — app.py:577-579, 965-968
- §2.9 — insert — ambiguity — idempotency body comparison excludes the `idempotency_key` field itself — app.py:1637-1638
- §2.11 — insert — ambiguity — `active_enrollment_count` (ACTIVE only) and `open_application_count` (SUBMITTED/UNDER_REVIEW/MORE_INFO_REQUESTED) semantics — app.py:243-250
- §3.1 — insert — ambiguity — all twelve config fields required at creation; every integer field ≥ 0 — app.py:154-175
- §3.1 — insert — ambiguity — program update is partial (any subset of fields) — app.py:224-226
- §3.1 — revise — mismatch — period `committed_cents` is gross anchored benefit caps reduced only at release (deliveries do not reduce it), not "remaining commitment" — app.py:718-719, 781, 1787-1790
- §3.2 — insert — ambiguity — `insurance_coverage_pct` requires exactly two fraction digits — util.py:79, app.py:459-460
- §3.2 — insert — ambiguity — document upload outside DRAFT/SUBMITTED → `ERR_SCREENING_NOT_DRAFT` — app.py:621-623
- §3.2 — insert — ambiguity — screening `decision` field carries `VERIFIED`/`REJECTED` — app.py:557
- §3.2 — insert — ambiguity — `rejection_reason` requirement enforced on the REJECTED branch after the SUBMITTED-state check — app.py:561-562, 577-579
- §3.2 — revise — mismatch — revision also clears `rejection_reason` and `eligibility_determination`, not only `verified_at` — app.py:596-599
- §3.3 — insert — ambiguity — state error surfaces before reviewer mismatch — app.py:927-930, 961-964
- §3.3 — insert — ambiguity — denial `decision_reason` enforced on the DENIED branch after state+reviewer — app.py:965-968
- §3.4 — insert — mismatch — `ERR_APPEAL_ALREADY_EXISTS` evaluated before the appeal-window check (contra tier 9<10) — app.py:1012-1019
- §3.4 — insert — ambiguity — OVERTURNED gate re-run includes screening VERIFIED + freshness (`ERR_SCREENING_NOT_VERIFIED`/`ERR_SCREENING_STALE`) — app.py:791-797 via 1091
- §3.5 — insert — ambiguity (with mismatch aspect) — renewal filing sequence pinned: schema → enrollment existence → OCC match → ownership → ACTIVE state → screening existence → cross-reference → VERIFIED → freshness → window last; OCC thus precedes ownership — app.py:1136-1173
- §3.5 — insert — ambiguity — renewal approval requires prior enrollment still ACTIVE, else `ERR_ENROLLMENT_NOT_ACTIVE` — app.py:803-807
- §3.5 — revise — mismatch — `ERR_ENROLLMENT_NOT_ACTIVE` applies at report time and at applied-review time; dismissal exempt — app.py:1281-1283, 1334-1336
- §3.5 — insert — ambiguity — circumstance review `decision` values: `APPLIED_SUSPEND`/`APPLIED_TERMINATE`/`DISMISSED` — app.py:1330
- §3.5 — revise — mismatch — applied-suspend also permitted from SUSPENDED (re-affirming), not only ACTIVE → SUSPENDED — app.py:1334-1353
- §3.5 — insert — ambiguity — suspension records the review note as each cancelled shipment's `status_reason` — app.py:1351
- §3.5 — insert — ambiguity — reinstatement clears `status_reason` — app.py:1241
- §3.5 — revise — ambiguity — `termination_reason` optional; stored as enrollment `status_reason` and propagated to cancelled shipments — app.py:1206-1213
- §3.7 — revise+insert — ambiguity — Patient callers may create only PATIENT-destination shipments (`ERR_OWNERSHIP_VIOLATION` otherwise); full creation check sequence pinned (existence → destination rules → idempotency replay → ownership → prescriber existence → ACTIVE state → caps → FEFO) — app.py:1622-1675
- §3.7 — insert — ambiguity — returning a non-DISPATCHED shipment → `ERR_SHIPMENT_NOT_DISPATCHED` — app.py:1818-1819
- §3.8 — insert — ambiguity — dispense `quantity` < 1 → `ERR_INVALID_QUANTITY`; DELIVERED-state check precedes lot membership; unknown `lot_id` → `ERR_NOT_FOUND` vs `ERR_LOT_NOT_IN_SHIPMENT` for an existing lot absent from the lines — app.py:1852-1871
- §3.8 — revise — mismatch — per-entry lot existence/program-match (`ERR_NOT_FOUND`/`ERR_RECONCILIATION_LOT_MISMATCH`) evaluated before coverage completeness (`ERR_RECONCILIATION_COUNTS_MISSING`); negative `actual_on_hand` → `ERR_INVALID_QUANTITY` — app.py:1919-1954
- §3.8 — revise — mismatch — only counted non-zero-variance lots still ACTIVE move to UNDER_INVESTIGATION — app.py:1983-1986

Everything else in the PRD (envelope shape, FPL/benefit-cap/valuation formulas and rounding, posture thresholds, FEFO rules, duplication guards, fiscal-gate ordering, sweep passes, error catalogue) was verified to already match the implementation exactly and was left untouched.
