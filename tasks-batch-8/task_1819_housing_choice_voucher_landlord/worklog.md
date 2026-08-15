# Worklog — task_1819_housing_choice_voucher_landlord

## Step 1: Create Task Directory — 2026-08-14T18:32:00.000Z

Directory `tasks/task_1819_housing_choice_voucher_landlord/` and `workspace/` pre-created by pipeline (per entrance command args; orchestrator skipped index scan).

## Step 2: Generate Scaffold — 2026-08-14T18:45:00.000Z

Clean lint. Summary of the generated scaffold:

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/SCAFFOLD.yaml` (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

**Counts**
- Entities: 13 (Landlord, Property, Unit, VoucherFamily, PaymentStandard, HAPContract, Inspection, RepairItem, RentComparable, RentIncreaseRequest, Recertification, HAPPayment, PortabilityAction)
- State machines: 10 (Landlord, Unit, HAPContract, Inspection, RepairItem, RentIncreaseRequest, Recertification, HAPPayment, PortabilityAction, VoucherFamily) + 2 OCC concurrency rules
- Endpoints: 56
- Difficulty design instances: 18 (2 per each of the 9 rules)
- Corner design instances: 21

**Design highlights** (harder-than-expert calibration): compliance/audit primary archetype with temporal windowing; dual-variant `rent_reasonableness` (standard-cap vs comparable-cap) and `hap_split` (standard-anniversary vs portability-restandard); cyclic Inspection repair-verification loop and compound Unit abatement loop; depth-3 abatement cascade (clock → contract → unit → payments) and a distinct termination cascade; two OCC true races on `POST /hcv/contracts` and `POST /hcv/recertifications/{id}/complete`; boundary precision on day-of-month first-payment scheduling and empty-repair-item FAIL rejection; payment-standard effective-window selection vs unit live-contract exclusion as the two distinct temporal-overlap semantics; per-row half-up abatement proration pinning nested rounding order. `scaffold_lint.py` verdict: clean lint (333 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-08-14T18:47:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1819_housing_choice_voucher_landlord/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T18:52:00.000Z

PRD generation is complete. Final summary:

## Output

- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/workspace/PRD.md`
- **Line count**: 239 lines

## Section List

1. **§1. Introduction** — 3 paragraphs, business-context + user-journey framing
2. **§2. Global Specifications & System-Wide Principles**
   - §2.1 User and Role-Based Access Control
   - §2.2 API Response Structure (verbatim fixed block)
   - §2.3 Pagination
   - §2.4 Common Resource Properties
   - §2.5 Validation Order and Optimistic Concurrency Control
   - §2.6 Ownership and Landlord Standing
   - §2.7 Monetary Precision and the Logical Clock
3. **§3. Business Logic & Workflows** (8 subsections, lifecycle-grouped)
   - §3.1 Registering Landlords, Properties, and Units
   - §3.2 Payment Standards, Comparables, and Rent Reasonableness
   - §3.3 From Listing to Lease: The Contract Pipeline
   - §3.4 Inspection, Repair, and Abatement
   - §3.5 Activation and the Payment Start Date
   - §3.6 Disbursement and Abatement Proration
   - §3.7 Recertification and Rent Increases
   - §3.8 Termination, Move-Out, and Portability
4. **§4. Endpoint Definitions** — 4-column table (Method, Path, Description, Authorized Roles), 56 endpoints
5. **§5. Error Code Catalogue** — 2-column table (Error ID, HTTP Status), 15 errors

## Zero-Silence Rule Coverage Audit

### Contract 1 — Field-Name Coverage: **PASS**
- `entities[].fields`: 41 required, 41 present, 0 missing
- `endpoints[].request_body` / `query_params` / `path_params` / OCC fields: 6 additional required (`expected_unit_version`, `expected_contract_version`, `outcome`, `to_iso8601`, `limit`, `offset`), all present
- Total: 47 required, 47 present, 0 missing (after repair pass added `family_code`, `inspection_id`, `property_id`)

### Contract 2 — Rule Coverage: **PASS**
- **Validations priority ordering** (15 rules): expressed as a single explicit ordered sequence in §2.5 with each `error_id` named in order; individual triggers re-stated near their workflows in §3.
- **Concurrency rules** (2 rules): `POST /hcv/contracts` ↔ `expected_unit_version` ↔ `ERR_STALE_VERSION` (HTTP 412) at §2.5 and §3.3; `POST /hcv/recertifications/{id}/complete` ↔ `expected_contract_version` ↔ `ERR_STALE_VERSION` (HTTP 412) at §2.5 and §3.7. Framed purely in OCC terms — no "simultaneously"/"race" wording.
- **State-machine transitions** (33 transitions across 10 entities): all `from`/`to` pairs named in §3 narratives, with preconditions and side-effects (including all version bumps, cascades to Unit/VoucherFamily/HAPPayment/Inspection).
- **Calculations** (4 rules): `rent_reasonableness` (incl. empty/non-empty comparable variants, median rule, 1.10 cap, payment-standard selection tie-break) at §3.2; `hap_split` (incl. tenant-minimum rounding before max, 0.30 ratio) at §3.2; `abatement_proration` (per-row, start-inclusive/end-exclusive window, half-up cents, full-month-abated → 0) at §3.6; `first_payment_schedule` (day-1 vs day-2..31 month-aligned variants) at §3.5.
- **Validation conditions**: all 15 checks matchable to their `error_id` in §2/§3 prose.
- **Endpoint side-effects / applies_to**: landlord-ownership 9-endpoint list enumerated at §2.6; landlord-suspended 3-endpoint list at §2.6/§3.1; payment-start, abatement, cure, termination, port-out cascades all narrated in §3.
- **Field-level structured content**: defaults (`status` initial values, `is_life_threatening` false, `approved_rent_cents`/`hap_portion_cents`/`tenant_portion_cents` zero at DRAFT, `next_recert_due_date` null until ACTIVE, `effective_to` null = open-ended, `result_recorded_date` null until PASSED/FAILED) all stated; `HAPPayment` noted as `common_fields: false` (no `updated_at`, no `version`) at §2.4.
- **Sibling-branch symmetry**: `ACTIVE→TERMINATED` vs `ABATED→TERMINATED` cascades given parallel density at §3.8; `PASS` vs `FAIL` verify branches given parallel density at §3.4; `month_aligned_start` vs `mid_month_start` at §3.5; `cure_within_period` vs `full_period_abated` at §3.6; `PORT_IN`/`PORT_OUT` at §3.8; landlord suspend/reinstate/terminate at §3.1.

### Contract 3 — §3 Path Purity: **PASS**
- Backtick tokens scanned in §3: 308
- Tokens starting with `/`: 0
- Bare HTTP-method tokens: 0
- Method+path combined tokens: 0
- All §3 endpoint references use state-transition framing (`DRAFT → PENDING_INSPECTION`, `ACTIVE → ABATED`), role + action verb ("an admin activates", "the landlord submits"), or capability description ("admin-only test-driving capability accepts a `to_iso8601` instant").

## Step 6: Generate Implementation — 2026-08-14T19:00:00.000Z

Both fresh boots start with empty stores. Implementation is complete.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/workspace/implementation/`:

- `start.sh` — executable launcher, guarded pip install, `exec python3 app.py`
- `requirements.txt` — Flask
- `app.py` — Flask app factory, blueprint registration, error handlers, `app.run(host="0.0.0.0", port=$PORT)`
- `db.py` — in-memory dicts (13 tables, all empty at boot), logical clock (initially `2026-08-01T00:00:00Z`), `iso_timestamp()` with 3-fractional-digit format
- `errors.py` — `APIError` class + all 15 scaffold error IDs
- `response.py` — `{meta, response_type, data}` envelope helpers with `api_request_id` (`req_*`) and `api_request_timestamp`; list helper adds `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-Role`/`X-User-ID` extraction, role validation, entity-backed check for `Landlord`
- `services/calculations.py` — `rent_reasonableness`, `hap_split`, `abatement_proration`, `first_payment_period`, `add_one_year`, `find_payment_standard` (with latest `effective_from` + `created_at` ASC tie-break), half-up rounding via `Decimal`
- `services/clock_eval.py` — clock-advance evaluator: contract `ACTIVE → ABATED` on breached repair deadline (30-day standard, 1-day life-threatening), recert `OPEN → OVERDUE` past `due_date`
- `routes/` — 13 blueprints: `landlords`, `properties`, `units`, `voucher_families`, `payment_standards`, `rent_comparables`, `contracts`, `inspections`, `repair_items`, `rent_increase_requests`, `recertifications`, `hap_payments`, `portability_actions`, `clock`, plus `helpers.py`

**Endpoint count**: 56 routes implemented, covering every endpoint in SCAFFOLD §1.5 including the `_clock/set_current_utc` test driver.

**Logical clock**: A module-level `_LOGICAL_NOW` in `db.py`, initialized to `2026-08-01T00:00:00Z` at import time. Never falls back to wall-clock. `POST /hcv/_clock/set_current_utc` (admin-only) replaces it and runs `evaluate_all()` to trigger deadline-driven transitions. Every `iso_timestamp()` and `current_logical_date()` reads from this logical clock, so `created_at`, `result_recorded_date`, abatement deadlines, recert overdue, etc. all honor the test-driven time.

**Verification**: booted twice from fresh processes; both started with `total_count: 0` for landlords (no seeding). End-to-end smoke test exercised the full pipeline (landlord → property → unit → payment standard → family → contract create → submit → INITIAL inspection → PASS → activate → first HAPPayment) and a complete abatement cycle (ANNUAL inspection FAIL → 30-day clock advance → `ABATED` + `ABATED_HELD` → mark-repaired → request-reinspection → verify PASS → `ACTIVE` + prorated payment 60000 − ⌈60000·1/31⌉ = 58065 → terminate).

**`bash start.sh` confirmation**: `start.sh` runs `python3 app.py` via `exec` in the foreground, binds `0.0.0.0` on `$PORT` (default 10000), and responds to HTTP within 2 seconds of invocation — well under the 60-second contract.

## Step 5: Generate Unit Tests — 2026-08-14T19:05:00.000Z

All 60 tests collect cleanly. Final state:

**Files written:**

`test_helpers/` (9 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/__init__.py` — barrel export
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/types.py` — 12 status/role enums, 13 entity TypedDicts (HAPPayment correctly omits `updated_at`/`version` per PRD §2.4)
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 methods incl. `_clock/set_current_utc`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/api_errors.py` — 15 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/assertions.py` — per-entity assertions + `assert_contract_portion_invariants`
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/factories.py` — payload factories, input fields only
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/constants.py` — INCOME_RATIO 0.30, COMPARABLE_CAP_RATIO 1.10, repair windows, clock default
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/test_users.py` — shared constants + `make_landlord_headers(user_id)` for the entity-backed Landlord role
- `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_helpers/fixtures.py` — composite fixtures: priced-unit hierarchy, contract progression (draft→submit→approve→activate), failed-inspection/repair-verification setups, `setup_abated_contract` + `cure_abatement`, recertification/increase helpers

`test_suite/` (8 files, 60 tests):
- `conftest.py`, `test_01_rent_reasonableness.py` (6), `test_02_hap_split.py` (3), `test_03_contract_pipeline.py` (8), `test_04_activation_payments.py` (4), `test_05_inspection_repair.py` (5), `test_06_abatement.py` (6), `test_07_termination_portability.py` (4), `test_08_validations_occ.py` (7), `test_09_rbac_ownership.py` (3), `test_10_entities_endpoints.py` (10), `test_11_rent_increase_errors.py` (2)

**Queue A (Difficulty):** 17 of 18 instances emitted, all with ≥2 tests. **Skipped 1:**
- `compensating_invariant/abatement_and_cure_conserve_total_hap_minus_abated_days` — SKIP: the quantitative conservation claim (exact per-row cent deductions) is not uniquely derivable from the PRD. The PRD does not pin the abatement window's start date precisely enough (deadline date vs. clock-advance detection date) for a two-reader-exact cents assertion, and activation creates exactly one HAPPayment row ("Subsequent months' payment rows are managed outside the activation cascade"), so a multi-row conservation sum is unobservable via the API.

Notes on two repaired recipes: `contract_activate_requires_approved_and_lease_date_reached` was emitted with the recipe's missing INITIAL-PASS step restored (the recipe as written could never reach ACTIVE); `state_vs_business_fiscal_on_contract_submit` emits the plain invalid-state rejection its trigger actually exercises plus a resubmit-after-withdraw positive control. The dual-variant portability instance's muddled numeric assert was replaced by two PRD-derivable tests: PORT_IN lifecycle to ABSORBED, and PORT_IN absorb leaving the ACTIVE contract/LEASED family untouched (PRD §3.8 conditions the cascade on PORT_OUT).

**Queue B (Corner):** all 21 non-stub instances emitted with ≥1 test (no stubs exist in this file). 0 skipped. One initially mis-tagged test (invented `port_out_absorb_move_out_cascade` tag) was removed — no design instance owns it.

**Design-tag audit:** PASS — all 60 docstrings end with exactly one `Design:` line; every tag resolves to a real instance name in the source yamls; every difficulty instance has ≥2 tests; every corner non-stub has ≥1; no `skip`/`xfail` markers; all quoted PRD citations verified verbatim against PRD.md by automated grep; all files compile and pytest collects 60 tests cleanly.

## Step 7: Run Tests and Iterate — 2026-08-14T19:15:00.000Z

Clean 8-round parallel sweep confirmed: 60/60 passed in every round.

**Summary**

- **Iterations run:** 2 sweeps (16 total round-executions). Sweep 1: 59/60 in all 8 rounds, same test failing deterministically. Sweep 2 after fix: 60/60 in all 8 rounds.

- **Tests deleted:** none.

- **Fixes applied to test layer (1):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/test_suite/test_04_activation_payments.py` — `TestFirstPaymentMonthBoundary::test_lease_start_day_two_first_payment_following_month`: added `api.set_current_utc("2026-08-02T00:00:00Z", ADMIN)` before activation. The test asserted PRD §3.5's mid-month rule (lease day 2–31 → first payment `period_month` is the first of the following month), which is verbatim-covered and uniquely derivable, but its setup activated the contract with `lease_start_date="2026-08-02"` while the logical clock still read `2026-08-01` — violating PRD §3.5's activation precondition ("An admin activates the contract once the current logical date is on or after `lease_start_date`; attempting activation before the lease start is rejected with `ERR_INVALID_STATE`"). The implementation's 409 rejection was PRD-correct; the fixture flow was the bug. Advancing the clock to the lease start date makes the test satisfy the PRD precondition while keeping the day-2 boundary assertion intact.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on the only failing path.

## Step 8: Finalize PRD — 2026-08-14T19:20:00.000Z

Step 8 complete. **Zero edits** — PRD_FINALIZED.md is byte-identical to PRD.md.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/workspace/PRD_FINALIZED.md`

**Line counts / delta**: PRD.md = 239 lines; PRD_FINALIZED.md = 239 lines; 0% delta (diff confirms IDENTICAL).

**Changes**: none — one bullet covering the audit outcome:
- §3.5 — no change — the sole Step 7 item was a pure test-fixture bug (test activated with `lease_start_date="2026-08-02"` while the logical clock still read the 2026-08-01 default). PRD §3.5 already uniquely determines both behaviors the test touched: the activation precondition ("An admin activates the contract once the current logical date is on or after `lease_start_date`; attempting activation before the lease start is rejected with `ERR_INVALID_STATE`", line 134) matches `implementation/routes/contracts.py:215-219` verbatim, and the mid-month rule ("day 1 → first of same month; day 2–31 → first of following month", line 136) matches `implementation/services/calculations.py:151-161` verbatim.

**Per-edit pre-edit search log** (audit performed for the two subjects implicated by the Step 7 item; both concluded no edit was warranted):

1. (a) Subject: activation precondition (logical date vs `lease_start_date`). (b) Paths enumerated: `implementation/routes/contracts.py:211-243` (sole `/activate` route — role check, 404, `APPROVED` gate at :215-216, `lease_start > current_logical_date()` → `errors.invalid_state` at :217-219); `implementation/db.py:24` (`current_logical_date`); all other `current_logical_date` callsites in contracts.py (:178 INITIAL inspection `scheduled_date`, :262 terminate-cascade future-period cutoff, :306 schedule-inspection `ERR_SCHEDULE_IN_PAST`) — none gate activation; grep confirmed no second activation path. (c) No wording adjustment — PRD §3.5 + §5 (ERR_INVALID_STATE → 409) already pin the impl behavior exactly.
2. (a) Subject: first-payment `period_month` month alignment. (b) Paths enumerated: `implementation/services/calculations.py:151-161` (`first_payment_period`, including Dec→Jan year rollover) and its sole callsite `implementation/routes/contracts.py:232`. (c) No wording adjustment — PRD §3.5's day-1/day-2–31 rule uniquely determines the impl, and "first of the following month" covers the December rollover as a corollary.

A fresh implementer reading PRD_FINALIZED.md (== PRD.md) hits no ambiguity on any path Step 7 exercised; the implementation was PRD-faithful on the only failing path, so no PRD pinning was required.

## Step 9: Complete PRD — 2026-08-14T19:30:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1819_housing_choice_voucher_landlord/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` with 21 in-place paragraph/table-line revisions — no new sections, no restructuring.

**Line counts / char delta:** PRD_FINALIZED.md 239 lines / 37,125 chars → PRD_COMPLETED.md 239 lines / 41,778 chars (+4,653 chars; 21 lines rewritten inline).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (the two "period after the breach"/"future payment" phrasings and the "PAID … delta recorded" phrasing each appeared twice and were revised in both places; counted once per semantic change).

**Changes:**

- §2.3 — insert — ambiguity — pagination never rejects: limit clamped to [1,100], negative offset clamped to 0, non-integer values fall back to defaults; sort tie-break by `id` ascending; `has_more` = `offset + returned < total_count` — routes/helpers.py:9-40, response.py:37
- §2.7 — insert — ambiguity — clock set accepts any ISO 8601 (Z/offset/naive-as-UTC), backward moves allowed, malformed → `ERR_INVALID_AMOUNT` 422, returns 200 with empty `data` — routes/clock.py:16-40
- §2.7 — revise — mismatch — only the first breaching contract abates per clock advance; the rest abate on later advances (impl `return`s after one flip) — services/clock_eval.py:44-46,84-88
- §3.1 — insert — ambiguity — duplicate `tax_id` rejected with `ERR_INVALID_STATE` (409) — routes/landlords.py:40
- §3.1 — insert — ambiguity — landlord termination blocked by a live contract fails with `ERR_INVALID_STATE` (409) — routes/landlords.py:98
- §3.1 — insert — ambiguity — duplicate `family_code` → `ERR_INVALID_STATE` (409); `annual_income_cents` must be a non-negative integer → `ERR_INVALID_AMOUNT` (422) — routes/voucher_families.py:35-40
- §3.2 — insert — ambiguity — no matching payment standard ⇒ standard treated as 0 cents (approved rent collapses to 0) — services/calculations.py:84-88
- §3.3 — revise — ambiguity — exact amount rules pinned: `contract_rent_cents` integer > 0, `annual_income_cents` integer ≥ 0; plus no unit-state precondition beyond the one-live-contract rule (a `DELISTED` unit can be contracted) — routes/contracts.py:64-77,101-104
- §3.4 — insert — ambiguity — schedule-inspection: date check runs before type check; bad/missing type (incl. `INITIAL`) → `ERR_INVALID_STATE` 409; missing `scheduled_date` stored null — routes/contracts.py:303-316
- §3.4 — insert — ambiguity — record-result: outcome must be `PASS`/`FAIL` → `ERR_INVALID_AMOUNT` 422, checked before the `SCHEDULED` state check — routes/inspections.py:46-49
- §3.4 — insert — ambiguity — repair-item attach has no inspection-status precondition — routes/inspections.py:105-118
- §3.4 — revise — mismatch — ABATED_HELD flip covers rows whose `period_month` is in or after the breach month (not strictly "after the breach"); breached deadline date recorded as proration window start — services/clock_eval.py:52,60-69
- §3.4 — insert — ambiguity — verify preconditions: item `REPAIRED` + parent inspection `REPAIR_VERIFICATION` else `ERR_INVALID_STATE`; bad outcome → `ERR_INVALID_AMOUNT` before state checks — routes/repair_items.py:77-85
- §3.4 — revise — mismatch — already-`PAID` rows are left untouched; no delta is recorded — routes/repair_items.py:60-68
- §3.5 — insert — ambiguity — Feb 29 lease start ⇒ Feb 28 anniversaries on non-leap years — services/calculations.py:164-169
- §3.6 — revise — mismatch — abatement window pinned as [breached deadline date, final-PASS verification date), start-inclusive/end-exclusive; only `ABATED_HELD` rows recomputed (against current `hap_portion_cents`), all returning to `SCHEDULED`; `PAID` rows untouched — routes/repair_items.py:45-68
- §3.6 — revise — mismatch — termination voids payments whose `period_month` ≥ first of current logical month; earlier periods untouched — routes/contracts.py:262-272
- §3.7 — insert — ambiguity — recert open: `new_family_income_cents` must be non-negative integer → `ERR_INVALID_AMOUNT` — routes/recertifications.py:41-42
- §3.7 — insert — ambiguity — recert complete requires parent contract `ACTIVE` (else `ERR_INVALID_STATE`, before the OCC check); split recomputed with the payment standard at the current not-yet-advanced `next_recert_due_date`; auto-created successor copies `new_family_income_cents` — routes/recertifications.py:70-71,89-91,105-109
- §3.7 — insert — ambiguity — rent-increase create requires contract `ACTIVE` and positive integer `requested_rent_cents`; approve requires request `PENDING` + contract still `ACTIVE`, ceiling uses the payment standard at the request's `effective_date` — routes/rent_increase_requests.py:41-58,81-107
- §3.8 — insert — ambiguity — bad/missing `action_type` → `ERR_INVALID_AMOUNT` 422; absorb with non-`LEASED` family or no `ACTIVE` contract changes only the action's status — routes/portability_actions.py:36-37,74-87
- §4 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` 404; no presence/type validation beyond itemized rules (absent fields stored null) — app.py:51-57
- §4 table — insert — ambiguity — list payment-standards and list rent-comparables accept optional `zip_code`/`bedroom_count` filters; non-integer `bedroom_count` yields an empty list — routes/payment_standards.py:46-56, routes/rent_comparables.py:44-54
