# Worklog — task_1923_inpatient_pharmacy_iv_compounding_workflow

## Step 1: Create Task Directory — 2026-08-15T01:01:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/` and its `workspace/` already existed; orchestrator skipped index scan and directory creation as instructed.

## Step 2: Generate Scaffold — 2026-08-15T01:44:00.000Z

All done. Final summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts (SCAFFOLD.yaml)

- **Entities: 17** — StaffMember, PatientProfile, DrugProduct, CompoundingHood, HoodSession, CoverageShift, MedicationOrder, ClinicalIntervention, CompoundingBatch, CompoundedPreparation, ADCStation, ADCPocket, InventoryEvent, DiscrepancyCase, DiversionCase, SubstitutionProtocol, WasteRecord
- **State machines: 8** (38 transitions) — incl. cyclic batch rework loop (REJECTED→DRAFT, cap 2 → FAILED), parallel dimensions on MedicationOrder (verification × fulfillment), branching DiversionCase adjudication, clock-sweep auto-transitions (preparation EXPIRED at inclusive BUD boundary, protocol EXPIRED)
- **Concurrency rules: 2** (both true CREATE-with-supersede / stale-observation OCC per §1.2.1 filter: `order-create-stale-patient-version`, `pocket-restock-stale-version`, both 412)
- **Calculations: 7** — renal_dose_adjustment (IBW vs ABW variants), dose_rounding (pinned per-component-then-sum), beyond_use_dating (default USP 797 table vs stability-extended variant), batch_yield_and_waste (pinned evaluation order over circular-looking dependency), diversion_risk_score (weighted + C-II multiplier + floor), substitution_equivalent_dose, adc_expected_on_hand (chronological ledger replay)
- **Validations: 35** (auth → existence → state/OCC → safety → constraint → temporal → referential)
- **Endpoints: 83** (incl. `POST /pharmacy/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` and expiry sweeps)
- **Errors: 34**, every one referenced by a validation or concurrency rule
- **Roles: 6** — segregation_of_duties model (QA releaser ≠ compounder, waste witness ≠ recorder, discontinuer must be ordering prescriber); PharmacyAdmin/DiversionOfficer opaque, others entity_backed:StaffMember

## Design instances

- **§1.8: 18 non-stub instances** (2 per each of the 9 rules, all differentiation clauses honored: different entity domains, different combinatorial modes a/b, different machine shapes/entities, cascade depths 3 and 2 from different triggers, different error-category pairs, different boundary metrics/endpoints, different entity pairs, different interval semantics (half-open adjacency vs aggregate capacity cap), different conserved quantities (ADC units vs batch mL))
- **§1.9: 49 non-stub + 15 excluded_because stubs** across all nine guide sections

## Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 677 calls scanned, zero violations; all FKs reverse-reachable
- Zero unbound `${var}` placeholders; all OCC version inputs are `${var}` references; unique instance names across both files; no forbidden concurrency vocabulary; all stub citations resolve
- Every formula-derived assert literal was executed as code and matches: renal 750.0/1000.0 (CrCl 45.67/53.33), boundary CrCl exactly 30.0 → 600.0, computed-panel 74.99/27.78/104.15, rounding 2.3 vs 2.0, overage 77.0% vs 60% tolerance, mass conservation 20.0 = 2.3 + 17.7, risk score 93.0 OPEN_CASE / 62.0 WATCH, BUD 2026-08-15 vs 2026-08-31, substitution clamp 40.0, ledger replay 48

## Notable design decisions

- Single `StaffMember` entity backs four roles (PRESCRIBER/PHARMACIST/TECHNICIAN/NURSE) with a priority-3 `ERR_ROLE_MISMATCH` header-vs-row identity check; this keeps entity count at 17 while preserving entity-backed SoD comparisons
- One mid-design fix: waste endpoint roles widened to `[PharmacyTechnician, Pharmacist]` so the diversion-risk fixture's subject (a pharmacist) can legally record both wastes and counts under the formula's `recorded_by_staff_id == subject` filter
- Logical clock drives all time-dependent rules (BUD, protocol expiry, 30-day risk window, after-hours classification), making every deadline deterministic
- Two negative-test details worth noting: CrCl boundary fixture engineered so IBW is exactly 54.00 (height 156.82 cm) yielding CrCl exactly 30.00; risk-score fixture places counts at noon and wastes at 23:30 to pin the after-hours term at exactly 4

(Orchestrator note: the first scaffold subagent turn was cut off after writing SCAFFOLD.yaml only; it was resumed via SendMessage and completed both design YAMLs, including a YAML flow-sequence quoting fix and a fixture-consistency repair in the diversion-risk instance. Difficulty directive "harder than expert level" was passed to the generator and reflected in §1.8/§1.9 instance selection.)

## Step 3: Copy Shared Files — 2026-08-15T01:46:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T01:55:00.000Z

All three hard contracts PASS. Here is the summary.

---

## Summary

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/workspace/PRD.md`

**Size:** 340 lines, 8,452 words.

**Section list:**
- §1. Introduction (3 paragraphs)
- §2. Global Specifications & System-Wide Principles
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - §2.3 Pagination
  - §2.4 Common Resource Properties and the Version Counter
  - §2.5 Optimistic Concurrency Control
  - §2.6 The Logical Clock
  - §2.7 Validation Priority Order
  - §2.8 Nested Resource Retrieval
  - §2.9 Precision and Rounding
- §3. Business Logic & Workflows
  - §3.1 Staff, Formulary, Hoods, and Coverage: the Configuration Layer
  - §3.2 The Patient Renal Panel
  - §3.3 Ordering, Verification, and the Clinical Review Loop
  - §3.4 Renal Dosing and the Dose-Rounding Step Ladder
  - §3.5 Compounding: Batches, Preparations, and Quality Gates
  - §3.6 Cabinet Inventory: Pockets, the Ledger, and Dispensing
  - §3.7 Discrepancy Resolution and Diversion Surveillance
  - §3.8 Shortage Substitution Protocols
  - §3.9 Waste Accounting Across the Two Domains
- §4. Endpoint Definitions (4-column table, 83 rows)
- §5. Error Code Catalogue (2-column table, 34 rows)

**Scaffold → PRD section mapping:**
- `scenario` → §1 introduction (3 paragraphs: chain-of-custody framing, scope enumeration, logical-clock determinism).
- `roles` + auth validations (priority 1–3) → §2.1 (header names, six roles spelled, opaque vs `entity_backed:StaffMember` identity translated per role; `staff_role` enum mismatch called out).
- `response_envelope` → §2.2 (verbatim) + §2.3 (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending sort, four `meta` fields).
- `entities[].fields` with `common_fields: true/false` → §2.4 (UUID `id`, ISO 8601 UTC `created_at`/`updated_at`, `version` integer; explicit absence of `updated_at`/`version` on `ClinicalIntervention`, `InventoryEvent`, `WasteRecord`).
- `concurrency_rules` + the two optional version inputs on verify/resume/complete → §2.5.
- logical clock + `_clock/set_current_utc` + expiry sweeps → §2.6 (default `2026-08-01T00:00:00Z`, two sweeps, inclusive-expired boundary).
- `validations[].priority` 1–35 → §2.7 as an explicit ordered list of failure tiers; individual checks then surface in §3 beside their workflows with their `error_id`.
- path-validation rule → §2.8.
- `calculations[].precision` → §2.9 (2 dp round-half-up default; step ladder and integer ledger as named exceptions; BUD in whole hours).
- `StaffMember`/`DrugProduct`/`CompoundingHood`/`HoodSession`/`CoverageShift` entities + hood overlap, coverage cap, session window, ISO/HD flags, shortage/formulary flags → §3.1.
- `PatientProfile` panel (`age_years`, `bmi`, `ibw_kg`, `abw_kg`, `crcl_ibw_ml_min`, `crcl_abw_ml_min`) → §3.2 with formulas in prose.
- `MedicationOrder` state machine (PENDING → VERIFIED ⇄ ON_HOLD, DISCONTINUED, SUPERSEDED; fulfillment NONE → QUEUED/READY → DISPENSED → ADMINISTERED) + interventions + prescriber-ownership + 3-level discontinue cascade → §3.3.
- `renal_dose_adjustment` (both `IBW` and `ABW_WHEN_OBESE` variants, tier factors 1.00/0.75/0.50/0.25 at 50/30/10) + `dose_rounding` (step 0.1 / 0.5 / 1.0, round-then-sum pinned) → §3.4.
- `CompoundingBatch` + `CompoundedPreparation` state machines, `batch_yield_and_waste` (pinned 6-step order, tier thresholds 25/100 mL, tolerances 60/30/10 %, lifetime accumulators, invariant `total_drawn_ml = delivered_ml + waste_ml`), `beyond_use_dating` (LOW/MEDIUM/HIGH × ROOM/REFRIGERATED/FROZEN table + 720-hour stability-extension cap), QA SoD, rework cap of 2 with terminal `FAILED` at 200 → §3.5.
- `ADCStation`/`ADCPocket`/`InventoryEvent`, `adc_expected_on_hand` (chronological replay with `occurred_at`/`created_at` tie-break, per-event sign convention), dispense guard chain, C_II witness rules, count thresholds 2 vs 5, quarantine cycle → §3.6.
- `DiscrepancyCase` + `DiversionCase` state machines, FOUND_ERROR/UNRESOLVED_ESCALATE branch, `diversion_risk_score` (30-day window inclusive, weights 10/5/3, divisor 2, hard trigger 10 with floor 80, C_II multiplier 1.5, tiers 75/50) → §3.7.
- `SubstitutionProtocol` state machine + activation cascade (flag orders, block pockets) + revocation/expiry compensation + `substitution_equivalent_dose` (factor → step-round → clamp) → §3.8.
- `WasteRecord` two-shape model (compounding vs ADC) → §3.9.
- `endpoints[]` → §4 table (83 rows, 4 columns: Method / Path / Description / Authorized Roles).
- `errors[]` → §5 table (34 rows, 2 columns).

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): 113 required, 113 present, 0 missing — PASS.
- Contract 2 (Rule Coverage): 35 validations with priorities expressed (§2.7 enumerates the priority order explicitly); 2 concurrency rules each with `write_endpoint` + `occ_field` + `error_id` + HTTP 412 in prose; 38 state-machine transitions with from/to/preconditions/side-effects; 7 calculations with full formulas, constants, precision, and variants in prose; all endpoint side-effects and `applies_to` scopes covered; sibling branches (verify-vs-resume, release-vs-reject, FOUND_ERROR-vs-UNRESOLVED_ESCALATE, SUBSTANTIATED-vs-CLOSED_UNSUBSTANTIATED) given equal density — PASS.
- Contract 3 (§3 Path Purity): 711 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS.

**Zero-silence / wording decisions worth flagging:**
- **`staff_role` enum mismatch:** scaffold defines roster enum `TECHNICIAN` but RBAC role `PharmacyTechnician`; §3.1 explicitly calls this out and §2.1 ties `staff_role` equality to the header's corresponding enum, so the implementer knows the roster stores `TECHNICIAN` while calls arrive as `PharmacyTechnician`.
- **Half-open interval semantics** for hood sessions and coverage shifts: prose uses "at or after `start_at` and strictly before `end_at`" plus "adjacency, where one session's `start_at` equals another's `end_at`, is allowed" to uniquely determine the `[start_at, end_at)` overlap check without pseudocode.
- **Round-then-sum vs sum-then-round** for batch `demand_ml`: §3.4 and §3.5 both state that per-component rounding precedes summation and that the reverse "is explicitly not the policy and yields different results," preserving the scaffold's pinned order.
- **BUD inclusive-expired boundary:** "the boundary itself counts as expired" / "at or after `bud_expiry`" to encode `logical clock >= bud_expiry` without operator syntax.
- **Rework terminal semantics:** scaffold says the rework call at `rework_count == 2` returns 200 with status `FAILED`; §3.5 preserves the unusual 200-on-terminal detail and the cap of 2.
- **Optional OCC fields** (`expected_order_version`, `expected_batch_version`) are distinguished from the two mandatory ones (`expected_patient_version`, `expected_pocket_version`) so the implementer does not make all four required or all four optional.
- **Optional `order_id` on return:** drug-match check is stated as conditional on `order_id` being supplied, matching the scaffold's optionality.
- **Diversion risk score window:** "inclusive range from 30 days before the logical clock to the logical clock itself — both bounds inclusive" and after-hours "before 6 or at or after 22, evaluated in UTC" reproduce the exact bounds.
- **Substitution substitution_pending reset on revoke:** restricted to orders flagged by this protocol with `substituted_by_protocol_id` still null, per the scaffold's compensation semantics.

## Step 5: Generate Unit Tests — 2026-08-15T02:25:00.000Z

All checks pass. The suite is complete and verified. Final summary:

## Files written

**test_helpers/** (`/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/test_helpers/`)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 18 entity TypedDicts + 21 enums; append-only entities (ClinicalIntervention, InventoryEvent, WasteRecord) omit `updated_at`/`version` per PRD §2.4; `STAFF_ROLE_TO_USER_ROLE` map encodes the §3.1 TECHNICIAN/PharmacyTechnician spelling split
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` enum + 35-entry HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_batch_mass_invariant` + `assert_pocket_ledger_consistent`
- `factories.py` — payload factories (input fields only)
- `constants.py` — renal tiers, step ladder, BUD table, waste tolerances, discrepancy thresholds, risk-score weights, default clock
- `test_users.py` — opaque roles as shared constants; per-instance `make_<role>_headers(user_id)` builders for the four entity-backed roles
- `fixtures.py` — composite fixtures: staff makers, `place_order` (reads current patient version for OCC), `setup_verified_order`, `setup_session`/`setup_batch`/`setup_batch_in_progress`/`setup_batch_qa_review`, `setup_station_with_pocket` + ledger action helpers, `setup_active_protocol`, `setup_discrepancy_case`, `setup_diversion_case`

**test_suite/** (`.../test_suite/`) — `conftest.py` + 12 test files (`test_01` renal panel/dosing, `test_02` config/envelope, `test_03` ordering/OCC, `test_04` verification/clinical loop, `test_05` discontinuation cascade, `test_06` hoods/coverage, `test_07` batch lifecycle gates, `test_08` batch calculations, `test_09` ADC ledger, `test_10` discrepancy/diversion, `test_11` substitution, `test_12` security/RBAC, `test_13` listings, `test_14` diversion risk score)

## Test counts
- **Queue A (Difficulty): 34 tests** — 17 of 18 instances × 2 tests each
- **Queue B (Corner): 55 tests** covering all 49 non-stub instances (6 have 2 tests); all 14 `excluded_because:` stubs left untranslated (cross-references verified to resolve)
- **Total: 89 tests**, all collected cleanly by pytest; tag audit: zero unresolved/duplicate/misplaced `Design:` lines; verbatim-citation sweep: every quoted string is a literal substring of PRD.md

## Instances skipped
- **Difficulty/compensating_invariant/batch_mass_conservation_across_rework** — fails the two-condition filter. Its pinned trigger chain drives the batch to 77.0% overage in the SMALL tier and then asserts `qa-release → RELEASED`; PRD §3.5 verbatim forbids that outcome ("the batch's `overage_pct` must not exceed the tolerance of its size tier — 60 percent for SMALL…otherwise the release is rejected with `ERR_WASTE_TOLERANCE_EXCEEDED`"). A faithful PRD-only implementer rejects the release, so the asserted final invariant state (delivered 2.3 / waste 17.7 / drawn 20.0) is unreachable and not uniquely derivable. Not weakened, no placeholder emitted; the release-block path remains covered by Corner/calculations/waste_tolerance_release_gate.

## Translation deviations (recipe repaired to stay PRD-consistent, assertions unchanged)
Three instances' recipes use `route: "PO"` for orders that are then substituted; PRD §3.3 routes verified non-IV orders straight to READY while §3.8 requires QUEUED/COMPOUNDING for substitution, so PO would surface ERR_INVALID_STATE instead of the asserted outcome. These were translated with `route: "IV"` (all asserted values unchanged): `Corner/calculations/substitution_equivalent_dose_computed`, `Corner/cross_cutting_layers/protocol_revoke_compensates_cascade`, `Difficulty/priority_pair_validation_conflict/substitute_safety_beats_protocol_referential`, `Corner/errors/error_substitution_not_pending`. Also, `Corner/validations/qa_release_same_as_compounder_forbidden` pins ERR_ROLE_MISMATCH (the compounder is a TECHNICIAN staff row presented under the Pharmacist header), matching the instance's own pinned expectation. BUD timestamps are asserted as parsed instants (not literal strings) to respect the serializer's ISO-8601 choice.

## Helper-layer design decisions
- Entity-backed roles always authenticate via `make_<role>_headers(staff["id"])` inside fixtures; opaque roles (PharmacyAdmin, DiversionOfficer) use shared `TEST_USERS` constants exposed through `fixtures.ADMIN` / `fixtures.OFFICER`.
- OCC call sites never hard-code versions: `place_order`/`restock_pocket` GET the parent's current version first; tests asserting staleness capture the pre-mutation version explicitly.
- All fixture setup uses `get_success_data` (clear "Setup step failed" errors); tests use `validate_success`/`validate_error`/`validate_paginated`.
- Timestamp-sensitive assertions compare parsed `datetime` instants; money/dose assertions use `pytest.approx` with PRD-precision tolerances.

(Orchestrator note: this subagent hit the output-token limit twice and was resumed via SendMessage; during the resume it also repaired a revoke→re-activate dance in test_11 that would have hit the terminal REVOKED state.)

## Step 6: Generate Implementation — 2026-08-15T02:25:00.000Z

Implementation complete and verified. All six smoke suites pass against the running server.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/workspace/implementation/`)

- `start.sh` — executable launcher; guarded `pip install` (no-op when Flask present, per the per-test-server reboot constraint), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/400 handlers producing the PRD envelope, `main` reading `PORT`
- `db.py` — in-memory tables (plain dicts keyed by id, zero seeding), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall clock), UUID minting, monotonic insertion sequence, `base_fields`/`append_fields`/`touch` (version starts at 1, +1 per mutation)
- `errors.py` — full error catalog (all 35 error IDs with exact HTTP statuses)
- `response.py` — `meta`/`response_type`/`data` envelope, error body `error_id`/`message`, `limit`/`offset`/`total_count`/`has_more` pagination in meta (default 10, clamped to 1–100, offset ≥ 0), `created_at`-ascending sort with insertion-seq tie-break, Decimal/datetime JSON serialization
- `timeutil.py` — ISO8601 parsing (Z, offsets, date-only) and the 3-fractional-digit UTC format
- `auth.py` — `X-User-ID`/`X-User-Role` chain: 401 → 403 forbidden → entity-backed staff resolution with the `PharmacyTechnician`↔`TECHNICIAN` enum mapping (403 role-mismatch); PharmacyAdmin/DiversionOfficer opaque
- `validate.py` — body well-formedness validators (required/type/enum/OCC fields), all raising `ERR_INVALID_REQUEST`
- `calc.py` — renal panel (age with birthday-on-date, BMI, IBW, ABW-null-under-30, Cockcroft-Gault ×2), renal tier factors on the rounded CrCl, dose-rounding step ladder (round-each-then-sum), BUD table + 720h-capped stability extension, batch demand/vials/delivered, size tiers/tolerances, 30-day diversion risk score (variance/2·10 + waste·5 + after-hours·3, C_II hard floor 80 then ×1.5)
- `ops.py` — ledger append + chronological replay, waste-record append, batch derived recompute, the L1→L3 discontinue/supersede cascade (preparations→CANCELLED, batch recompute/auto-cancel from DRAFT|IN_PROGRESS, hood session cancel), protocol flagging/compensation cascades, and the clock/dispense expiry sweeps
- `routes_config.py` / `routes_orders.py` / `routes_compounding.py` / `routes_adc.py` / `routes_surveillance.py` / `routes_protocols.py` — all 66 endpoints with per-endpoint check sequences following the PRD §2.7 priority tiers

## Subsystems implemented

- **State machines**: parallel MedicationOrder dimensions (verification + fulfillment), batch lifecycle with rework cap (REJECTED→DRAFT twice, then the same call returns 200/FAILED), preparation lifecycle incl. EXPIRED sweep, hood sessions, pockets (ACTIVE↔QUARANTINED), discrepancy cases (FOUND_ERROR→ADJUSTMENT / UNRESOLVED_ESCALATE→auto DiversionCase), diversion cases, substitution protocols (activate/revoke/expire with flagging and compensation cascades)
- **Calculations**: all seven from the scaffold, Decimal-based, 2dp ROUND_HALF_UP; verified numerically (IBW/ABW CrCl, all four renal tiers, step-ladder boundaries 0.95→1.0 / 10.5→11, tier boundaries 25/100, BUD 48h/72h/stability-capped, overage vs MEDIUM 30% gate)
- **OCC**: mandatory `expected_patient_version` (order create) and `expected_pocket_version` (restock); optional `expected_order_version` / `expected_batch_version` checked only when supplied; 412 `ERR_STALE_VERSION`
- **Clock**: logical clock drives every timestamp (including `created_at`/`occurred_at`/envelope meta); `POST /pharmacy/_clock/set_current_utc` runs both sweeps (preparations at/past `bud_expiry` → EXPIRED + EXPIRED waste record; ACTIVE protocols past `expires_at` → EXPIRED + compensation); sweeps also run at the top of dispense
- **Cascades**: supersede-on-create scoped to same prescriber+patient+drug (PRD wording), protocol activation flagging orders (+1 version each) and blocking pockets, revocation/expiry compensation

## PRD-vs-scaffold divergence decisions (PRD won)

1. **Supersede scope**: scaffold said same (patient, drug); PRD §3.3 says "the same prescriber" — filtered by `prescriber_staff_id == X-User-ID`.
2. **Version bumps on every transition**: scaffold side-effect lists omit version bumps for hood-session complete/cancel, diversion adjudicate, and protocol expiry; PRD §2.4 mandates +1 on every state transition/field update — applied everywhere.
3. **Substitute guard order**: PRD §3.8's explicit "guards fire in priority order" (VERIFIED → NOT_PENDING → NO_ACTIVE_PROTOCOL → NO_ELIGIBLE_SUBSTITUTE → ALLERGY → fulfillment INVALID_STATE) overrides the global tier order that would put allergy first.
4. **Dispense ordering**: global §2.7 tiers (quantity 17 → stock 21 → mismatch 22 → not-verified 28 → prep 29 → quarantined 30), with a fulfillment==READY from-state check placed *after* the enumerated preconditions so PENDING orders still surface `ERR_ORDER_NOT_VERIFIED` while double-dispense surfaces `ERR_INVALID_STATE`.
5. **Count does not bump pocket version** — scaffold's per-endpoint side effects omit it; only restock/dispense/return/waste/adjustment/quarantine bump.
6. Unspecified literals chosen: waste-record reasons `"PARTIAL_VIAL"` (complete), `"QA_REJECT"` (reject input `reason` is validated but the record carries the constant per §3.5), `"EXPIRED"` (sweep), `"ADC_WASTE"` (cabinet waste has no reason input); auto-created diversion cases get descriptive `reason` strings; sweep-generated waste records attribute `recorded_by_staff_id` to the calling `X-User-ID`; pagination out-of-range values clamp rather than error; `overage_pct` initializes to 0 before any completion.

Verified behavior via six smoke suites covering: auth chain (401/403/role-mismatch), envelope shape, OCC 412s, supersede + patient version bump, verify math (all renal tiers, ABW_WHEN_OBESE), intervention hold/resume, HD cert + hood gating (422s in priority order), complete/BUD timestamps, QA SoD + waste-tolerance gate, reject→rework→FAILED cap, discontinue L1–L3 cascade (batch + session auto-cancelled), restock capacity, dispense readiness/quarantine/stock/double-dispense, witness rules, count thresholds (C_II=2/other=5), discrepancy resolve both branches, diversion lifecycle + risk score value check, protocol activate/flag/block/substitute/revoke/expire, and clock-sweep prep expiry. All passed; the only smoke failures were my own test-side arithmetic/window mistakes, never server behavior.

## Step 7: Run/iterate until all tests pass (8-round sweeps) — 2026-08-15T03:10:00.000Z

Sweep protocol: 8 concurrent `prd-bench-local-run --isolation per-test-server` rounds per iteration; union of failures across all 8 rounds drives the next fix batch.

### Iteration 1 — 55/87... (initial: 55 passed / 34 failed per round, deterministic across all 8 rounds)

Failure clusters and dispositions:

1. **Cluster A — 24 tests failing with `ERR_ROLE_MISMATCH` (403).** Root cause in the test artifact: `test_suite/conftest.py` exposed the entity-backed roles (`pharmacist_headers` etc.) as shared constants (`X-User-ID: test-pharmacist-1`) that are not registered `StaffMember` ids; PRD §2.1 requires entity-backed roles to resolve to an existing, active, role-matching staff row, so the PRD-faithful implementation correctly rejected those calls. STEP 2 fixture bug. **Fix (test_suite/conftest.py):** the four entity-backed header fixtures now register a fresh `StaffMember` per test via `test_helpers.fixtures.make_*` and return per-instance headers; opaque roles (`admin_headers`, `diversion_officer_headers`) keep the canonical shared constants.
2. **Cluster B — 5 tests failing schema assertions with "id must be a valid UUID".** Implementation minted ids as `uuid4().hex` (32 hex chars, no dashes); PRD §2.4 declares "a server-minted UUID" and the runner's canonical UUID check requires the hyphenated form. **Fix (implementation/db.py):** `new_id()` now returns `str(uuid.uuid4())`.
3. **Cluster C — `TestDiscontinueCascade::test_discontinue_stores_reason_and_moves_verification` (`assert 4 == (2 + 1)`).** Test compared the post-discontinue version against the stale pre-batch observation (v2); batch creation had already bumped the order QUEUED→COMPOUNDING (v3, PRD §3.5 + §2.4). STEP 2 fixture-staleness bug. **Fix (test_05):** setup re-fetches the order after batch creation and asserts `discontinued["version"] == pre_discontinue["version"] + 1`.
4. **Cluster D — `test_same_pattern_on_non_controlled_drug_stays_watch` (score 42 vs asserted 62).** The test's expected value counted the NON_CONTROLLED pocket's waste events toward `w`, contradicting PRD §3.7 verbatim ("The waste signal `w` counts the window's `WASTE` events on pockets whose drug is controlled — any schedule other than `NON_CONTROLLED`"). PRD-derived values for the pinned setup: v=10·((2+4)/2)=30, w=0, a=3·4=12 → raw 42 → CLEAR. **Fix (test_14):** assertions corrected to score 42.0 / tier CLEAR / no case; test renamed to `test_same_pattern_on_non_controlled_drug_scores_clear`.
5. **Cluster E — DELETED `TestTerminalLockdown::test_intervention_on_discontinued_order_rejected_terminal`** (Corner/state_machines/order_discontinue_terminal_lockdown). Unique-derivability failure: PRD §3.3's "any mutation attempted on an order ... ERR_ORDER_ALREADY_TERMINAL" does not determine whether appending an append-only `ClinicalIntervention` with `placed_on_hold=false` (no order field changes, no version bump; §3.3 also says "Every call appends an immutable ClinicalIntervention row" with no terminal caveat) counts as such a mutation. Two faithful PRD-only implementations diverge.
6. **Cluster F — DELETED `TestSubstituteGuardFailures::test_substitute_allergy_beats_draft_protocol_referential_failure`** (Difficulty/priority_pair_validation_conflict/substitute_safety_beats_protocol_referential). Unique-derivability failure: PRD §2.7's global tiers order the allergy screen (business-safety) ahead of substitution preconditions (business-referential), while PRD §3.8's endpoint-specific sentence ("The guards fire in priority order: ... ERR_NO_ACTIVE_PROTOCOL ... ERR_ALLERGY_CONFLICT ...") enumerates NO_ACTIVE_PROTOCOL ahead of ALLERGY_CONFLICT. The two verbatim sentences conflict for exactly this request. The sibling probe (`test_substitute_with_draft_protocol_alone_reports_no_active_protocol`, no allergy live) is order-independent and stays.

### Iteration 2 — 86/87 in all 8 rounds

Single remaining failure: `TestPreparationAutoExpiry::test_clock_reaching_bud_expiry_marks_preparation_expired` asserted the literal string `"2026-08-02T00:00:00Z"` while PRD §2.4 mandates the 3-fractional-digit wire format (`...:00.000Z`). STEP 2 assertion bug. **Fix (test_07):** compare parsed instants (mirrors the test_08 BUD convention).

### Iteration 3 — 87/87 in all 8 rounds. EXIT CONDITION MET.

Final tally: 87 tests (89 generated, 2 deleted under the PRD-First contract), 8/8 green rounds, zero flaky signals observed in any iteration (every failure reproduced 8/8 before its fix).

Subagent exit summary (verbatim):

**Iterations run:** 3 (rounds were deterministic — every failure reproduced 8/8; no flaky-only failures observed). Final sweep: **87/87 passed in all 8 parallel rounds.**

**Tests deleted (2):**
1. `test_05…TestTerminalLockdown::test_intervention_on_discontinued_order_rejected_terminal` — unique-derivability collapse (scope silence): PRD §3.3's "any mutation attempted on an order … ERR_ORDER_ALREADY_TERMINAL" does not determine whether appending an append-only `ClinicalIntervention` (placed_on_hold=false mutates no order field; §3.3 also says "Every call appends an immutable ClinicalIntervention row" with no terminal caveat) counts as such a mutation. Two faithful PRD-only implementations diverge. Scaffold driver: Corner/state_machines/order_discontinue_terminal_lockdown.
2. `test_11…TestSubstituteGuardFailures::test_substitute_allergy_beats_draft_protocol_referential_failure` — unique-derivability collapse (error-precedence conflict): PRD §2.7's global tiers put allergy (business-safety) ahead of substitution preconditions (business-referential), while PRD §3.8's endpoint-specific sentence "The guards fire in priority order: … ERR_NO_ACTIVE_PROTOCOL … ERR_ALLERGY_CONFLICT …" enumerates NO_ACTIVE_PROTOCOL first. Both orderings are verbatim-supported and conflict on exactly this request. Scaffold driver: Difficulty/priority_pair_validation_conflict/substitute_safety_beats_protocol_referential. (The sibling probe asserting NO_ACTIVE_PROTOCOL with no allergy live is order-independent and was kept.)

**Fixes applied to `test_helpers/`:** none directly — the fixture-layer bug lived in `test_suite/conftest.py` (see below).

**Fixes applied to `test_suite/` (4 files):**
- `conftest.py` — the four entity-backed header fixtures (`prescriber_headers`/`pharmacist_headers`/`technician_headers`/`nurse_headers`) returned shared fallback constants (`test-pharmacist-1`, …) that are not registered StaffMember ids, so the PRD §2.1-faithful implementation correctly rejected them with ERR_ROLE_MISMATCH (24 failing tests). Fixtures now register a fresh StaffMember per test via `test_helpers.fixtures.make_*` and return per-instance headers; opaque-role fixtures unchanged.
- `test_05_discontinuation_and_cascade.py` — `test_discontinue_stores_reason_and_moves_verification` compared the post-discontinue version against a stale pre-batch observation; batch creation had already bumped the order (QUEUED→COMPOUNDING, PRD §3.5+§2.4). Setup now re-fetches the order pre-discontinue and asserts +1 against that baseline.
- `test_07_compounding_batches.py` — `test_clock_reaching_bud_expiry_marks_preparation_expired` asserted the literal string `"2026-08-02T00:00:00Z"`; PRD §2.4 mandates the 3-fractional-digit wire format (`.000Z`). Assertion now compares parsed instants (mirrors test_08's BUD convention).
- `test_14_diversion_risk_score.py` — `test_same_pattern_on_non_controlled_drug_stays_watch` expected raw 62 by counting a NON_CONTROLLED pocket's waste events toward `w`, contradicting PRD §3.7 verbatim ("w counts the window's WASTE events on pockets whose drug is controlled — any schedule other than NON_CONTROLLED"). Corrected to the PRD-derived values (v=30, w=0, a=12 → raw 42.0, tier CLEAR, no case) and renamed `..._scores_clear`. Also removed two imports orphaned by the test_11 deletion.

**Fixes applied to `implementation/` (1 file):**
- `workspace/implementation/db.py` — `new_id()` returned `uuid4().hex` (no dashes), failing the canonical UUID format PRD §2.4 implies ("a server-minted UUID") and the suite's `is_valid_uuid` checks. Now returns `str(uuid.uuid4())`.

## Step 8: Finalize PRD — 2026-08-15T03:30:00.000Z

The diff shows exactly the four intended in-place revisions, nothing else. Line count is unchanged at 339 (edits are intra-paragraph, so 0.0% line delta; 4 lines modified in place).

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/workspace/PRD_FINALIZED.md` — 339 lines vs PRD.md's 339 (0% line delta; 4 lines revised in place, no new sections).

### Changes (one bullet per edit)

- **§2.4** — revise — `id` now pinned as "a server-minted UUID rendered in its canonical hyphenated string form (five hexadecimal groups of 8-4-4-4-12 characters)" — `implementation/db.py:55-57` (`new_id()` returns `str(uuid.uuid4())` after the Step 7 fix).
- **§2.7** — insert — added the endpoint-specific exception: on the substitution endpoint the guards fire in exactly §3.8's enumerated order, with `ERR_SUBSTITUTION_NOT_PENDING` → `ERR_NO_ACTIVE_PROTOCOL` → `ERR_NO_ELIGIBLE_SUBSTITUTE` surfacing ahead of `ERR_ALLERGY_CONFLICT`, §3.8 governing over the global tiers wherever they disagree — `implementation/routes_orders.py:288-326` (`substitute_order` fires NO_ACTIVE_PROTOCOL/NO_ELIGIBLE_SUBSTITUTE before the allergy check).
- **§3.3** — revise — intervention paragraph now pins the terminal-lockdown split: `placed_on_hold=true` is a mutation of the order and runs the terminal lockdown first (`ERR_ORDER_ALREADY_TERMINAL` on verification `DISCONTINUED`/`SUPERSEDED` or fulfillment `ADMINISTERED`), then the from-state check (`ERR_INVALID_STATE` when not `PENDING`/`VERIFIED`); a plain append (`placed_on_hold` false/omitted) mutates no order field and returns 201 even on a terminal order — `implementation/routes_orders.py:228-252` (`_check_not_terminal` is called only inside the `if placed_on_hold:` branch, before the state check).
- **§3.5** — revise — batch creation sentence now explicitly pins "each such order's `version` increments by 1 with its `updated_at` refreshed (per §2.4)" when fulfillment moves `QUEUED`→`COMPOUNDING` — `implementation/routes_compounding.py:200-201` (`db.touch(order)` at batch creation).

Step 7 items confirmed as needing **no** PRD change: conftest header-fixture repair (§2.1 already pins entity-backed resolution; `auth.py:29-44` matches), test_07 timestamp assertion (§2.4/§2.2 already pin 3-fractional-digit format; `timeutil.fmt` matches), test_14 diversion `w` signal (§3.7 already restricts `w` to controlled-drug pockets; `calc.py:281-286` matches).

### Per-edit pre-edit search log

1. **§2.4 UUID edit.** (a) Subject: resource `id` wire format. (b) Enumerated: `db.py:55-57` (`new_id`, sole id generator), `db.py:60-78` (`base_fields`/`append_fields`, the only callers — covers every resource family), `response.py:20-21` (`_request_id` — not a resource id; §2.2's `req_`-prefixed description left untouched), grep for other id minting/format validation across routes — none (path ids are raw dict-key lookups). (c) Wording scoped to resource `id` only; no adjustment needed beyond that scoping.
2. **§2.7 substitute-exception edit.** (a) Subject: guard ordering, allergy screen vs substitution preconditions. (b) Enumerated: `routes_orders.py:288-326` (substitute — the Step 7 site; also fires fulfillment `ERR_INVALID_STATE` *after* allergy, another §2.7-tier deviation on this endpoint), `:148-168` (verify: allergy before drug-discontinued — tier-consistent), `:171-188` (resume: allergy only), `routes_adc.py:147-196` (dispense: constraint-tier stock/drug-match before referential-tier verified/QA/quarantine — tier-consistent), `routes_protocols.py:76-95` (activate: temporal before referential — tier-consistent), waste/count/discrepancy/diversion routes (no allergy involvement). (c) Wording defers wholesale to §3.8's enumeration ("wherever it and the global tier order above disagree") rather than naming only the allergy/referential pair, so the fulfillment-state-after-allergy ordering at `routes_orders.py:315-316` is also covered; exception scoped to the substitution endpoint so verify/resume/dispense stay under the global tiers.
3. **§3.3 intervention-terminal edit.** (a) Subject: whether appending a `ClinicalIntervention` is a "mutation on an order" for terminal lockdown. (b) Enumerated: `routes_orders.py:228-252` (create_intervention — terminal check only when `placed_on_hold` true, fired before the PENDING/VERIFIED from-state check), `ops.py:125-129` (`order_is_terminal` definition — verification DISCONTINUED/SUPERSEDED or fulfillment ADMINISTERED; mirrored verbatim in the edit), all other `_check_not_terminal` callers — verify `:155`, resume `:178`, discontinue `:197`, administer `:216`, substitute `:299` — where the guard is unconditional (edit is scoped to the intervention endpoint and says nothing about those), plus the §3.3 terminal sentence itself, which stays consistent because the edit defines the plain append as not being such a mutation. (c) Added the explicit error-id pinning for both the terminal (`ERR_ORDER_ALREADY_TERMINAL`) and non-terminal-wrong-state (`ERR_INVALID_STATE`, e.g. ON_HOLD) branches so neither faithful-PRD reading diverges.
4. **§3.5 batch-creation version edit.** (a) Subject: order `version` bump when batch creation moves fulfillment `QUEUED`→`COMPOUNDING`. (b) Enumerated every impl path that transitions an order's fulfillment or mutates an order as a side effect: `routes_compounding.py:200-201` (create_batch — touch), `:330-342` (qa_release COMPOUNDING→READY — touch), `routes_adc.py:185-195` (dispense READY→DISPENSED — touch; §3.6 already pins it), `routes_orders.py:104-117` (supersede — touch; §3.3 already pins), `:211-221` (administer — touch; §3.3 already pins), plus protocol flagging/compensation cascades (`ops.py:136-165` — touch orders; untouched by this edit). (c) Wording is additive ("and each such order's version increments by 1 ... per §2.4") with no exclusivity claim, so the QA-release and protocol-cascade order bumps — which §3.5/§3.8 state less explicitly — remain covered by §2.4's blanket rule rather than being implied away.

## Step 9: Complete PRD — 2026-08-15T03:55:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1923_inpatient_pharmacy_iv_compounding_workflow/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`. All edits are in-paragraph inserts/revisions; no new sections, no new paragraphs, no invented behavior.

**Size delta**
- `PRD_FINALIZED.md`: 339 lines, 63,622 chars → `PRD_COMPLETED.md`: 339 lines, 69,412 chars (**+5,790 chars**, 24 paragraph lines touched, 0 lines added/removed structurally).

**Counts**: 26 ambiguity-pins, 5 mismatch-revisions.

**Ambiguity-pins (PRD silent → pinned to impl)**
- §2.3 — insert — ambiguity — pagination out-of-range clamping (limit→[1,100], offset→≥0), non-integer limit/offset → `ERR_INVALID_REQUEST`, `created_at` ties break by creation order, filters exact-match with boolean `true`/`1` parsing, unknown query params ignored — response.py:79-114; routes_config.py:162-175.
- §2.4 — insert — ambiguity — `version` starts at 1; `updated_at` equals `created_at` at creation — db.py:60-69.
- §2.6 — insert — ambiguity — sweep waste records attribute `recorded_by_staff_id` to the triggering call's `X-User-ID`; each expiry recomputes batch derived figures and bumps batch `version`; sweeps process preparations then protocols, each in creation order; on dispense, sweeps run after pocket/order resolution and before every guard (rejected dispenses still apply expiries) — ops.py:172-205; routes_adc.py:157-158; routes_protocols.py:140-147.
- §3.1 — insert — ambiguity — every drug PATCH increments `version` even when neither updatable field is supplied — routes_config.py:180-194.
- §3.2 — insert — ambiguity — every patient PATCH recomputes the panel and bumps `version` even when no field is supplied — routes_config.py:101-119.
- §3.3 — insert — ambiguity — the `ClinicalIntervention` row stores the supplied `intervention_type`, `note`, and `placed_on_hold` value — routes_orders.py:240-247.
- §3.5 — insert — ambiguity — batch create: non-IV or non-`QUEUED` order fails the whole create with `ERR_INVALID_STATE`; the VERIFIED check runs across all named orders before the route/queue check — routes_compounding.py:158-164.
- §3.5 — insert — ambiguity — batch opens with `total_drawn_ml`/`delivered_ml`/`waste_ml`/`overage_pct` all 0 — routes_compounding.py:175-180.
- §3.5 — insert — ambiguity — hazardousness at batch start is evaluated over still-`PLANNED` preparations only — routes_compounding.py:233-234.
- §3.5 — insert — ambiguity — batch-start guard firing order: `DRAFT` from-state → HD certification → hood rating → session `IN_USE` → at-least-one-`PLANNED` (`ERR_INVALID_STATE`) — routes_compounding.py:230-253.
- §3.5 — insert — ambiguity — completion waste record carries reason `PARTIAL_VIAL` and is appended even when recorded waste is 0 — routes_compounding.py:308-311.
- §3.5 — insert — ambiguity — `prepared_volumes_ml` maps to `PLANNED` preparations in creation order; completion guard order: OCC → `IN_PROGRESS` → count match → non-negative waste — routes_compounding.py:266-290.
- §3.5 — insert — ambiguity — `vials_used` divides by the first named order's drug's `vial_size_ml` — calc.py:213-215; routes_compounding.py:198-199.
- §3.5 — insert — ambiguity — `overage_pct` is 0 when the run's drawn volume is zero; with reworks, `overage_pct` and the size tier reflect the most recent completion — routes_compounding.py:299-302, 326-327.
- §3.5 — insert — ambiguity — qa-reject requires a free-text `reason` body field, validated for presence but not persisted; a single `QA_REJECT` waste record carries the summed rejected volume — routes_compounding.py:349, 355-366.
- §3.6 — insert — ambiguity — pocket `max_units` must be ≥ 1 (`ERR_INVALID_QUANTITY`) — routes_adc.py:73-74.
- §3.6 — insert — ambiguity — ledger-mutating pocket endpoints (restock, dispense, return, waste) and the quarantine pair each return the updated pocket object — routes_adc.py:144, 196, 218, 246, 296, 308.
- §3.6 — insert — ambiguity — restock performs no pocket-status check; `QUARANTINED` pockets accept restocks — routes_adc.py:129-144.
- §3.6 — insert — ambiguity — dispense guard firing order (sweeps → terminal → units≥1 → stock → drug match → VERIFIED → IV QA-prep existence → BUD → pocket-`ACTIVE` → fulfillment-`READY` last); earliest-created `QA_PASSED` preparation is dispensed against; its batch is recomputed with `version` bumped — routes_adc.py:147-196.
- §3.6 — insert — ambiguity — negative `physical_count_units` → `ERR_INVALID_QUANTITY`; discrepancy threshold is inclusive ("reaches or exceeds", impl `abs(variance) >= threshold`) — routes_adc.py:255, 267.
- §3.6 — insert — ambiguity — quarantine blocks dispense only; restock/return/waste/count operate normally on `QUARANTINED` pockets — routes_adc.py:129-284.
- §3.7 — insert — ambiguity — resolve stores `resolution` (and `adjustment_units` under `FOUND_ERROR`) on the case; escalation auto-case `reason` is the literal `Escalated from discrepancy case {id}`; both branches return the updated discrepancy case — routes_surveillance.py:70-102.
- §3.7 — insert — ambiguity — manual diversion create with a source case records `opened_via` = `ESCALATION` — routes_surveillance.py:138.
- §3.7 — insert — ambiguity — risk-score auto-case `reason` is the literal `Auto-created by diversion risk evaluation` — routes_surveillance.py:215.
- §3.8 — insert — ambiguity — activation gate firing order: `DRAFT` from-state → `ERR_PROTOCOL_EXPIRED` → substitute formulary-`ACTIVE` → shortage `in_shortage` — routes_protocols.py:81-91.
- §3.9 — revise — ambiguity — replaced open-ended "such as … `CONTAMINATION`" list with the exact reason mapping: `PARTIAL_VIAL` (completion), `QA_REJECT` (rejection), `EXPIRED` (sweep, volume = expired prep's `prepared_volume_ml`), `ADC_WASTE` (cabinet) — ops.py:190-195; routes_compounding.py:308-311, 363-366; routes_adc.py:241-244.

**Mismatch-revisions (PRD said X, impl does Y → revised to Y)**
- §2.5 — revise — mismatch — the "two further endpoints" optional-guard sentence (plus its "endpoints not named take no version field" exclusivity) omitted substitution, which accepts `expected_order_version`; now names it — routes_orders.py:293, 298.
- §2.7 — revise — mismatch — "One endpoint-specific exception exists" was falsified by dispense's non-tier guard order; now two exceptions (dispense §3.6 + substitution §3.8) — routes_adc.py:147-196.
- §3.5 — revise — mismatch — the invariant "`total_drawn_ml` equals `delivered_ml` plus `waste_ml` at every observable read" is false in impl (vial round-up; in-flight `COMPOUNDED` volume counted in neither figure; expiry sweep lowers `delivered_ml` without touching the `waste_ml` accumulator); replaced with the actual figure-maintenance semantics. Cross-check: the test helper asserting it (`assert_batch_mass_invariant`) is imported but never called — calc.py:207-233; routes_compounding.py:292-306; ops.py:189-198.
- §3.6 — revise — mismatch — "every pocket-mutating call increments the pocket's `version`" contradicted by count (zero-delta event, pocket row untouched); scoped to exclude count — routes_adc.py:249-284.
- §3.9 — revise — mismatch — "for `C_II` drugs, the `witness_staff_id`" implied compounding waste carries witnesses and non-C_II ADC waste never does; impl records `witness_staff_id` only on ADC-waste records (mandatory for `C_II`, optional otherwise), null on all compounding-waste records — ops.py:52-65; routes_adc.py:240-244.

All Step-6 hint leads were verified against the implementation and are covered above (waste reasons, pagination clamping, `overage_pct` zero-init, count not bumping pocket version, dispense READY-check placement, sweep `recorded_by` attribution, auto-created diversion case reason strings).
