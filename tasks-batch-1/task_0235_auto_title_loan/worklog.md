# Worklog — task_0235_auto_title_loan

## Step 1: Create Task Directory — 2026-06-07T16:40:13.000Z

Created `tasks/task_0235_auto_title_loan/workspace` via `mkdir -p` (pre-allocated path, no ID auto-increment scan per orchestrator instruction). Verified `./INSTRUCTION.md` and `./skills/prd-bench-scaffold-generator/SKILL.md` exist.

## Step 2: Generate Scaffold — 2026-06-07T17:14:22.000Z

All three scaffold artifacts are written and verified. Here is the summary.

## Summary

Generated the three Expert-tier scaffold artifacts for **Auto Title Loan** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0235_auto_title_loan/`, working only from the scenario and the scaffold-generator skill (no sibling tasks consulted).

**Difficulty level applied:** Expert (§0.4). Primary archetype compliance/audit blended with ledger-reconciliation; layers: cascading side-effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency, derived-field reconciliation. Topology hybrid, parallel state-machine shape (Loan carries independent `delinquency_status` × `payoff_status` dimensions), segregation-of-duties role model.

**SCAFFOLD.yaml counts:**
- Entities: **14** (Borrower, RegulatoryProfile, Vehicle, Appraisal, LoanApplication, Loan, TitleLien, Installment, Payment, Renewal, RepossessionOrder, RepossessionAssignment, Device, DeviceCommand)
- State machines: **6** (Appraisal, LoanApplication, TitleLien, Loan [parallel+cyclic], RepossessionOrder [branching fork-join], Device [cyclic])
- Calculations: **11** (incl. dual-variant redemption vs reinstatement on Loan, trade-in vs auction basis on Appraisal; per-installment-rounding amortization; waterfall allocation; deficiency)
- Validations: **20** (ordered, with deliberate priority conflicts) · Errors: **21** · Endpoints: **43** (incl. 1 `/_clock` test-driving endpoint) · Roles: **6** · Concurrency rules: 1 (OCC stale Loan version on renewal)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 §0.5 rules × 2 instances = **18 difficulty instances**, each with executable `setup_api_calls`/`trigger` chains and code-computed literal asserts (e.g., redemption 640176 vs reinstatement 434236; deficiency 195176; amortization 194118/199942/205940).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **40 corner instances** (33 active with full recipes + 7 `excluded_because` stubs that all resolve to named §1.8 instances), spanning all 9 claim-extraction-guide sections.

**Verification:** all three files parse as YAML; `scaffold_lint.py` reports `VERDICT: clean lint` (515 calls scanned across §1.8+§1.9, all FK reverse-reachability satisfied); every error code is referenced; every enum value (incl. Borrower BARRED) has a producing path; no forbidden concurrency vocabulary; design keys live only in their own files. All numeric asserts were re-derived in Python against the scaffold's own formulas and match exactly.

One note: used `api_prefix: /atl` (resources nest as `/atl/loans/{id}`, `/atl/borrowers`, etc.) rather than `/loans` directly, because the lint's FK reverse-reachability deriver requires each entity's collection segment to sit one level below the prefix.

## Step 3: Copy Shared Files — 2026-06-07T17:14:49.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0235_auto_title_loan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T17:20:35.000Z

**PRD written to:** `workspace/PRD.md` — 274 lines.

**Sections covered:**
- §1 Introduction (system goals + per-state regulatory profiles + dual payoff/delinquency state dimensions)
- §2 Global Specifications (10 subsections): RBAC + segregation-of-duties, response envelope, pagination, common resource properties (RegulatoryProfile flagged as `common_fields: false` exception lacking `updated_at`/`version`), nested-resource existence ordering, validation precedence, OCC, monetary precision, cascade/versioning, test clock
- §3 Business Logic (9 subsections): config & onboarding → appraisal/LTV → underwriting → origination → amortization → servicing/delinquency/device → default/cure/redemption/payoff → renewal → repossession/sale/charge-off
- §4 Endpoint table (all 43 endpoints) · §5 Error catalogue (all 21 error IDs)

**Hard Contracts:** Field coverage PASS (75/75 required fields present); Rule coverage PASS (11/11 calculations, all 7 state machines, 1/1 OCC rule, 21/21 error IDs); Path purity PASS (0 path tokens in §3).

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate Unit Tests — 2026-06-07T17:38:11.000Z

Generated complete test infrastructure for the Auto Title Loan PRD benchmark task.

**Test files:** 11 (1 `conftest.py` + 10 `test_*.py`)
**Total tests:** 69

**Coverage by queue:**
- **Queue A (Difficulty, §1.8):** 36 tests covering **all 18/18** instances (every instance has ≥2 tests).
- **Queue B (Corner, §1.9):** 33 tests covering **all 33/33 non-stub** instances (≥1 test each).

**Instances skipped:** 0 — every Difficulty and non-stub Corner instance passed both the verbatim-coverage and unique-derivability conditions (PRD is unusually explicit: every error_id, threshold, cascade, and precedence order is stated in §3 prose). The 6 Corner `excluded_because:` stubs were correctly NOT translated; all 6 stub cross-references resolve to real §1.8 instances.

**test_helpers/ files written (9):** `__init__.py`, `types.py` (RegulatoryProfile omits `updated_at`/`version` per `common_fields: false`), `api_client.py` (43 endpoints incl. `/_clock/set_current_utc`), `api_errors.py` (21 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (6 roles + SoD header builders), `fixtures.py` (lifecycle composites).

**Verification:** every test docstring ends with exactly one standalone `Design:` tag resolving to a real instance; citations match PRD verbatim (≥8-word substring); no skip/xfail; all asserted error_ids appear in PRD prose; all imports resolve; all 20 files parse. Note: an automated backtick-normalization pass mangled 7 docstrings; all 7 detected and manually repaired.

## Step 6: Generate Implementation — 2026-06-07T17:38:11.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`.

**Files written (21 total):** `start.sh`, `requirements.txt` (`flask==3.0.3`), `app.py`, `db.py` (in-memory store, 14 entity dicts), `errors.py` (21-entry error_id→HTTP catalogue), `response.py` (envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC, 6 roles), `validate.py`, `clock.py`/`timeutil.py` (test clock), `calculations.py` (all 10 calcs incl. amortization half-up rounding + residue absorption, redemption/reinstatement, deficiency), `lookups.py`/`serialize.py`/`device_service.py`/`loan_service.py`, and route modules `routes_core.py`, `routes_applications.py`, `routes_loans.py`, `routes_liens.py`, `routes_repossession.py`, `routes_devices.py`.

**Endpoint count:** 43 — exactly matching PRD §4 (42 under `/atl` + `/_clock/set_current_utc`).

**Storage / seeding:** in-memory only (plain dicts in `db.py`); no SQLite, no disk, no `/tmp`. Store starts empty on every boot — no `seed_*`, no entity population at import. Fresh boot returns `total_count: 0`.

**start.sh contract:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guarded `pip install`. Confirmed boots and serves within ~1s.

**Verification:** ran five end-to-end smoke suites covering origination cascade, servicing/delinquency + device disable, repossession lifecycle + deficiency + charge-off, reinstatement/redemption/payoff with device invariants, OCC renewal (stale→412, rollover limit), and validation precedence — all produced expected results and exact error IDs.

## Step 7: Run Tests and Iterate — 2026-06-07T19:49:09.000Z

Clean sweep: 69/69 passing, 0 failed/errors/skipped, across all 8 parallel rounds. No tests were skipped or deleted, and all are genuinely passing.

## Summary

**Iterations run:** 2 (1 diagnostic sweep establishing the baseline + 1 fix-verification sweep).

**Root cause (single, centralized test-helper bug):** All 46 union failures traced to one mis-assumption in `test_helpers`. The fixtures and one inline test helper treated the return value of `POST /atl/applications/{id}/approve` as the originated **Loan**, then used `loan["id"]` for every downstream loan call (`assess_delinquency`, `list_installments`, `create_payment`, `create_repossession_order`, `declare_default`, etc.). But the approve endpoint targets the application: per PRD §2.2 ("operations that create or modify a resource will return the created or updated resource object") the modified resource is the *application*, and SCAFFOLD confirms `output: LoanApplication`. So `loan["id"]` was actually the application id, and every downstream loan-id call returned `ERR_NOT_FOUND` (404) — surfacing as 37 "Setup step failed" errors, 7 direct 404s in test_02/test_03, and 2 error-precedence mismatches in test_05/test_09 (where the 404 pre-empted the expected `ERR_LOAN_NOT_IN_DEFAULT` / `ERR_INVALID_STATE`). The implementation was correct; the test harness mis-read the response contract.

**Tests deleted:** None. No PRD-silence or unique-derivability failures were found.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — added `loan_for_application(application_id)` helper that resolves the originated Loan by reverse-reference list (`list_loans` filtered by `application_id`, which is PRD §3.4: "Loans can be ... listed with filters by `application_id`"). Updated `setup_originated_loan` to capture approve's return as the APPROVED application and then fetch the Loan via `loan_for_application`. This single change repaired all transitive fixtures (`setup_delinquent_loan`, `setup_defaulted_loan`, `setup_recovered_repo`, `setup_charged_off_loan`, `setup_loan_at_renewal_cap`).

**Fixes applied to `test_suite/`:**
- `test_01_appraisal_underwriting.py` — the local `_setup_ca_delinquent_loan_with_device` helper had the same approve-returns-loan bug; switched it to fetch the Loan via the new `loan_for_application` helper (added to its import list).

**Fixes applied to `implementation/`:** None. The implementation was faithful to PRD throughout; the approve endpoint correctly returns the modified application and exposes the loan via the filtered list endpoint.

Final state: 8/8 parallel rounds green at 69/69, 0 failed/errors/skipped.

## Step 8: Finalize PRD — 2026-06-07T19:51:37.000Z

PRD_FINALIZED.md created and verified byte-identical to PRD.md.

## Step 8 Summary

**PRD.md vs PRD_FINALIZED.md:** 274 lines vs 274 lines — 0 lines changed, 0% delta. Byte-identical (verified via `diff`).

**Changes:** None. Zero PRD edits made.

**Rationale.** The entire Step 7 diff was a single centralized test-helper bug: the fixtures and one inline test helper (`test_01`'s `_setup_ca_delinquent_loan_with_device`) treated `POST /atl/applications/{id}/approve`'s return value as the originated Loan and used `loan["id"]` for downstream loan calls, when the response is actually the modified application. The fix added `loan_for_application(application_id)` to resolve the Loan via `GET /atl/loans?application_id=...`. Per Method step 1, a pure fixture bug warrants a PRD edit only if it reveals a genuine PRD silence or PRD/impl mismatch. Both behaviors the fix relied on are already uniquely pinned by existing PRD prose, so no edit is warranted:

- **Approve return contract** — already determined by §2.2 (line 45: "operations that create or modify a resource will return the created or updated resource object"), the §4 endpoint catalogue (line 221: approve targets the application; line 202: action endpoints that modify return 200 OK), and §3.3's framing of the loan/lien/schedule as a downstream cascade rather than the operation's primary resource. `routes_applications.py:227` returns the application; no ambiguity.
- **Loan listing by `application_id`** — already determined verbatim by §3.4 (line 140: "Loans can be fetched individually and listed with filters by `application_id`, `borrower_id`, or `vehicle_id`"). `routes_loans.py:47-63` implements exactly this filter set.

**Per-edit pre-edit search log:** No edits were committed, but the mandatory pre-edit search was performed for the one subject considered (the approve-endpoint return-value contract) before deciding not to edit:

- (a) **Subject identified:** the resource returned by action endpoints that modify state, specifically `POST /atl/applications/{id}/approve` returning the application rather than the cascaded Loan.
- (b) **Impl paths enumerated and read/grepped:** `routes_applications.py` approve (line 227, returns application), reject (line 241, returns application); `routes_loans.py` list_loans `application_id`/`borrower_id`/`vehicle_id` filters (lines 47-63), assess_delinquency (line 141, returns loan), declare_default (line 176, returns loan); `routes_liens.py` file_lien (line 60, returns lien); `routes_repossession.py` assign_order (line 160), recover_order (line 185), sell_order (line 233) — all return the targeted order; `routes_devices.py` issue_command returns the command (lines 106/116/120). Grepped all `return success(...)`/`status=200`/`status=201` sites across the five route modules. Every action endpoint uniformly returns the resource its path targets, confirming the universal pattern that §2.2 already prescribes.
- (c) **Wording adjustment:** None — no edit was made. The enumeration confirmed that any attempt to pin the approve return value inline would be redundant with §2.2/§4 and would risk narrowing the uniform convention shared by every parallel action endpoint, creating a new mismatch. Under-determined existing prose was correctly left verbatim.

PRD_FINALIZED.md is produced (byte-identical copy) as required.

## Step 9: Complete PRD — 2026-06-07T19:59:01.000Z

**Step 9 Summary — task_0235_auto_title_loan**

**File sizes:** `PRD_FINALIZED.md` (source) = 274 lines / 49302 chars → `PRD_COMPLETED.md` = 274 lines / 53832 chars. Char delta: **+4530**. Line count unchanged (every change is an in-paragraph insert/revision; no new sections or paragraphs).

**Counts:** ambiguity-pins = **13**, mismatch-revisions = **2**. Total changes = 15.

**Per-change bullets:**

- §2.3 Pagination — insert — ambiguity — pinned that a non-integer `limit`/`offset`, a `limit` outside [1,100], or a negative `offset` is rejected with `ERR_INVALID_REQUEST` — validate.py:75-86.
- §2.3 Pagination — insert — ambiguity — defined `total_count` as the full pre-pagination filtered set size and `has_more` as true exactly when `offset + len(page) < total_count` — response.py:47.
- §2.6 Validation Ordering — insert — ambiguity — pinned that `ERR_VALIDATION_RANGE` (after field-presence/type) also enforces the numeric constraints on regulatory-profile-create, application-create (`contract_apr_bps`/`term_months`), vehicle-create (`odometer_miles`), appraisal-create (`trade_in`/`auction`), and renewal-create (`new_term_months`), which 2.6's operation list had omitted — routes_core.py:62-73,184,253-258; routes_applications.py:66-68; routes_loans.py:372.
- §2.10 Time and the Test Clock — insert — ambiguity — pinned HTTP 200 + ISO-8601-3-digit `current_utc` echo, the wall-clock UTC default before any set, and that `created_at`/`updated_at` always use wall-clock (not the test clock) — routes_core.py:32-40; clock.py:12-16; db.py:48,62.
- §3.1 Regulatory profile — insert — ambiguity — pinned that a duplicate `state_code` create is rejected with `ERR_INVALID_STATE` — routes_core.py:76-77.
- §3.1 Borrower — insert — ambiguity — pinned that a duplicate `email` create is rejected with `ERR_INVALID_STATE` — routes_core.py:129-131.
- §3.1 Vehicle — insert — ambiguity — pinned that a duplicate `vin` create is rejected with `ERR_INVALID_STATE` — routes_core.py:187-189.
- §3.2 Appraisal finalize — insert — ambiguity — pinned that a missing regulatory profile for the borrower's state rejects with `ERR_INVALID_STATE` (and that the same applies at application submit/approve and renewal) — routes_core.py:295-298; routes_applications.py:72-73,156-157; routes_loans.py:384-385.
- §3.3 Application submission — insert — ambiguity — pinned that submission does not require a FINALIZED appraisal, but a non-finalized appraisal (no `max_principal_cents`) makes any positive principal fail the LTV gate with `ERR_LTV_EXCEEDED` after the APR-cap then term-bounds gates; also pinned the APR→term→LTV gate evaluation order — routes_applications.py:91-101,23-43.
- §3.6 Payments — insert — ambiguity — pinned that `posted_at` is set to the Section 2.10 current clock time — routes_loans.py:192.
- §3.6 Device registration — insert — ambiguity — pinned that a duplicate `vehicle_id` or `serial_number` device-create is rejected with `ERR_INVALID_STATE` — routes_devices.py:34-38.
- §3.6 Public STARTER_DISABLE — insert — ambiguity — pinned that the absence of an active OUTSTANDING loan for the device's vehicle also yields `ERR_DEVICE_LOAN_NOT_DELINQUENT` — routes_devices.py:90-92.
- §3.7 Reinstatement — insert — ambiguity — pinned that a `REINSTATEMENT` against a `CURRENT` loan is rejected with `ERR_INVALID_STATE`, and pinned the payment-record applied-portion breakdown (principal=arrears principal, interest=arrears interest, fees=remainder incl. DEFAULT repo fee, overpayment=amount−required) — routes_loans.py:244-245,287-301.
- §3.7 Reinstatement (DEFAULT) — revise — mismatch — corrected "requires that an active repossession order exists" to match impl, which does not require one and simply cancels any active ORDERED/ASSIGNED/RECOVERED order (no-op if none) — routes_loans.py:268-270; loan_service.py:23-30.
- §3.7 Regular payoff — insert — ambiguity — pinned that the lien-release cascade fires only for a `FILED` lien; a still-`PENDING` lien is left unchanged and the vehicle's `lien_state` is not cleared — loan_service.py:13-20.
- §3.7 Redemption — insert + revise — ambiguity/mismatch — pinned that `REDEMPTION` against a non-`OUTSTANDING` loan is rejected with `ERR_INVALID_STATE`; revised the cascade to note `STARTER_ENABLE` sets `starter_state` to `ENABLED` and fires only when a device exists; pinned the payment-record applied-portion breakdown and that balances are then zeroed — routes_loans.py:306-307,317-336.
- §3.9 Repossession assign — insert — ambiguity — pinned the assign guard order and errors: order `ORDERED` (`ERR_INVALID_STATE`) → loan `DEFAULT` (`ERR_LOAN_NOT_IN_DEFAULT`) → at-least-one-assignment (`ERR_INVALID_STATE`) — routes_repossession.py:147-156.

(Note: the two "revise" mismatch items are the DEFAULT-reinstatement active-order requirement and the redemption cascade wording; the redemption change also carries an ambiguity insert for the state guard. Tallied as 13 ambiguity-pins / 2 mismatch-revisions.)
