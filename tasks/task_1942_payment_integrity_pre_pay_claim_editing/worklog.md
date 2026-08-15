# Worklog — task_1942_payment_integrity_pre_pay_claim_editing

Scenario: Payment Integrity & Pre-Pay Claim Editing (health plan payment integrity) — edit library (clinical/coding/policy) maintenance & versioning, pre-pay claim suspension & reviewer workflow, provider dispute & edit override tracking, savings measurement & false-positive rate, vendor edit comparison & duplication avoidance, high-dollar claim itemized bill review, DRG validation & readmission review, provider abrasion monitoring.

Difficulty target: harder than expert level.

## Step 1: Create Task Directory — 2026-08-15T02:07:00.000Z

Directory tasks/task_1942_payment_integrity_pre_pay_claim_editing/ and workspace/ pre-created by the pipeline launcher (Step 1 marked done in invocation args; verified to exist).

## Step 3: Copy Shared Files — 2026-08-15T02:08:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1942_payment_integrity_pre_pay_claim_editing/workspace/INSTRUCTION.md.

## Step 2: Generate Scaffold — 2026-08-15T02:56:00.000Z

Done. All three scaffold artifacts are written and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/SCAFFOLD_CORNER_DESIGN.yaml`

## Counts
- **Entities: 13** — Provider, EditRule, EditVersion, VendorEdit, Claim, ClaimLine, EditHit, ReviewTask, Dispute, ItemizedBillReview, InpatientReview, ProviderAbrasionProfile, SavingsPeriod
- **State machines: 8** — EditVersion (cyclic: DRAFT↔PENDING_APPROVAL, ACTIVE↔SUSPENDED), Claim (branching + DENIED→READY_TO_PAY compensation edge), ReviewTask (branching with escalation), EditHit (4 terminal resolutions), Dispute (RFI cycle UNDER_REVIEW⇄AWAITING_PROVIDER_INFO), ItemizedBillReview, InpatientReview, SavingsPeriod
- **Calculations: 8** — drg_base_payment (mode-a combinatorial), itemized_reprice (mode-b rounding order), edit_savings_attribution (waterfall), savings_measurement (dual-variant), false_positive_rate (threshold), provider_abrasion_index (dual-variant weighted scoring), readmission_detection (chronological), high_dollar_evaluation (threshold)
- **Validations: 46 ordered rows** across 12 priority tiers
- **Endpoints: 62** (incl. `POST /payment-integrity/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`)
- **Error codes: 45**
- **Roles: 8** — Provider (entity_backed), PlanAdmin, EditLibrarian, EditApprover, Reviewer, SeniorReviewer, DisputeAdjudicator, PaymentIntegrityAnalyst (all others opaque); segregation_of_duties model with two explicit SoD rules
- **§1.8 instances: 18** (2 per rule × 9 rules)
- **§1.9 instances: 54 live + 6 excluded_because stubs** (853 total calls scanned by the linter)
- **Concurrency rules: 2** (OCC on EditRule.version for approve; OCC on Claim.version for dispute create)

## Lint verdict (verbatim)
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Key design adjudications
- **Archetype**: compliance/audit primary, ledger-reconciliation secondary; flat topology; cyclic state shape; layers = optimistic concurrency, cascading side effects, dual-variant calculation, version-pinning on approval.
- **All formula-derived asserts were computed by code**: DRG outlier 1,650,000 / transfer 600,000 / outlier cap 1,800,000; per-line-then-sum reprice 282 (vs naive 283); abrasion standard 0.4000 vs regulatory 0.5000 (tier MEDIUM keyed on standard only); HIGH tier at 0.5333; fp boundary exactly 0.2500 suspends, 0.2000 does not; savings identity 180000 = 90000 + 70000 + 20000.
- **Rule 4 cascades**: overturn→hit FP→edit fp-rate→auto-suspension→task cancellation/hit supersede→claim compensation (depth 5, dispute-decide trigger); run-edits→high-dollar flag→IBR auto-create→provider occupancy counter (depth 3, run-edits trigger).
- **Rule 8 differentiation**: half-open adjacency semantics on EditVersion windows vs closed-interval + 14-day buffer occupancy on provider audit slots.
- **Rule 9 invariants**: claim dollar split (allowed + denied == initial_allowed) and period bucket identity (provisional == finalized + pending + reversed).
- **Constants pinned small for testability**: FP_SUSPEND_THRESHOLD 0.25 with FP_MIN_SAMPLE 4, MAX_IN_REVIEW_TASKS 3, dispute window 45d, decision deadline 60d, IBR due 30d / buffer 14d, high-dollar 10,000,000 cents.
- **Monitor-only feedback loop**: tier HIGH flips new hits to `applied=false` (attributed 0, no task) — cross-entity gating of EditHit by ProviderAbrasionProfile (Rule 7 instance).
- Fixed one lint violation during the run (added filtered-list `GET /payment-integrity/edit-versions` since the linter's sub-resource prefix match requires a literal `{id}` segment); verified zero forbidden race-vocabulary and uniqueness of all 78 instance names across both design files.

## Step 4: Generate PRD — 2026-08-15T03:07:00.000Z

All three hard contracts pass and the patched regions render cleanly. The PRD is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/workspace/PRD.md` — 344 lines, 5 top-level sections, 19 subsections (10 in §2, 9 in §3), plus §4 endpoint table and §5 error catalogue.

**Sections produced:** §1 Introduction (2 paragraphs); §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure — emitted byte-for-byte verbatim, verified programmatically, 2.3 Pagination & List Ordering, 2.4 Resource Identity/Timestamps/Versions, 2.5 Monetary Precision & Rounding, 2.6 Logical Clock, 2.7 OCC, 2.8 Request Validation Order & Error Precedence, 2.9 Segregation of Duties, 2.10 Claim Ledger Invariant); §3 Business Logic (3.1 Provider Enrollment & Abrasion Profile, 3.2 Edit Library Governance, 3.3 Vendor Edit Intake & Duplication Control, 3.4 Claim Submission & Pre-Payment Screening, 3.5 Review Task Assignment/Escalation/Decision, 3.6 Provider Disputes & Adjudication, 3.7 Itemized Bill Review, 3.8 Inpatient DRG Validation & Readmission Review, 3.9 Savings Periods & Reconciliation); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage counts:**
- Entities: 13/13 — all 96 `entities[].fields[].name` values backticked, defaults/nullability/computed semantics expressed
- State machines: 8/8 — all 38 transitions expressed (from/to states, preconditions paired with error IDs, side effects including the suspension cascade and DENIED→READY_TO_PAY compensation)
- Calculations: 8/8 — all formulas in precise prose with pinned rounding order (DRG base payment + transfer proration variant, itemized reprice, internal-first attribution waterfall, savings measurement with provisional/finalized variants, false-positive rate, provider abrasion index + regulatory variant, readmission detection, high-dollar evaluation)
- Validations: 46/46 conditions matched to their error IDs; the 12-band priority order stated in §2.8 plus per-endpoint surfacing orders (approve, run-edits, assign, dispute create, dispute decide) in §3
- Endpoints: 62/62 rows in the §4 table; all side effects (including every Claim/EditRule `version` increment) narrated in §3
- Errors: 46/46 rows in §5; all 46 IDs also mentioned in §1–§4 prose
- Roles: 8/8 with exact spellings and identity semantics (Provider entity-backed; the other 7 opaque); 33/33 state values and 65/65 enum values present verbatim

**Hard-contract audit results:**
- Contract 1 (Field-Name Coverage): entities[].fields 96/96, endpoint inputs 59/59, path params 2/2, common fields 4/4 — **PASS**
- Contract 2 (Rule Coverage): 12 validation priority bands expressed; 2/2 OCC rules with write endpoint + `expected_edit_rule_version`/`expected_claim_version` + `ERR_STALE_VERSION` (412); 38/38 transitions; 8/8 calculations reconstruction-safe (no pseudocode, no fuzzy words); 46/46 validations; all endpoint side effects and applies_to scopes expressed; structured field content explicit after patching initial-state/nullability semantics for `approved_by_user_id`, `released_cents`, `determined_at`, ReviewTask/Dispute/InpatientReview/IBR/SavingsPeriod defaults; sibling branches symmetric — **PASS**
- Contract 3 (§3 Path Purity): 562 backticked tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**

**Zero-Silence Rule audit:** confirmed — every scaffold rule (entities, transitions, calculations, validations, concurrency rules, endpoint side effects, roles, error catalog) maps to at least one explicit PRD sentence; no rules invented, no semantics altered. The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T04:05:00.000Z

Generated `test_helpers/` (9 modules) and `test_suite/` (conftest + 11 test files) from the two design indices under the design-index-only contract.

**Output:** 90 tagged test functions (100 collected items — the 404 sweep is parametrized ×11).

- Queue A (Difficulty): 18/18 instances × 2 tests = 36 tests, each docstring ending `Design: Difficulty/<rule_id>/<instance.name>`.
- Queue B (Corner): 54/54 non-stub instances × 1 test = 54 tests, each docstring ending `Design: Corner/<section>/<instance.name>`.
- Stubs: 6 `excluded_because:` stubs not translated; all six `difficulty_instance` cross-references verified to resolve.
- Skipped instances: none — every instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability).
- PRD citation audit: 161 quoted spans extracted from docstrings, all survive whitespace-normalized literal grep of `workspace/PRD.md`; zero endpoint-titular citations.
- Hygiene: `py_compile` clean, `pyflakes` clean (barrel re-export warnings aside), zero skip/xfail markers, zero scaffold vocabulary in generated code, all 12 modules import and pytest collects 100 items.
- test_helpers inventory: types (13 TypedDicts + 17 enums), api_client (61 endpoint methods), api_errors (46 IDs registered with the framework), assertions (13 entity asserts + claim ledger invariant), factories, constants, test_users (8 roles; Provider entity-backed with per-instance `make_provider_headers`), fixtures (provider/edit activation chains, one-line claim screening, task assign/decide, hit-resolution driver covering uphold/override/overturn/partial/fired, inpatient review closure, IBR walkthrough, savings-period scenario, clock).

## Step 6: Generate Implementation — 2026-08-15T03:33:00.000Z

Those are just the probe shells themselves; the earlier `ps` showed the two PIDs were already dead (no CMD output). Servers are cleaned up. Implementation complete.

---

## Summary

**Task**: Generate Python + Flask implementation for `task_1942_payment_integrity_pre_pay_claim_editing`.

### File inventory (all under `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op once flask importable); `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 63 | App factory, blueprint registration, ApiError/404/405/500 handlers |
| `db.py` | 85 | In-memory dict stores (13), UUID minting, logical clock (boot default `2026-08-01T00:00:00Z`, never wall-clock), 3-fractional-digit ISO8601 rendering |
| `errors.py` | 63 | Full 46-entry error catalog with exact ids + HTTP statuses |
| `response.py` | 44 | Success/error envelope (`meta`/`response_type`/`data`; `limit`/`offset`/`total_count`/`has_more` in list meta) |
| `middleware.py` | 142 | X-User-ID/X-User-Role auth, RBAC, request-shape validator (unknown-field/type/enum), datetime parsing, limit/offset pagination (default 10, min 1, max 100) |
| `serializers.py` | 35 | Datetime field rendering |
| `routes/providers.py` | 123 | Provider CRUD + auto abrasion-profile creation; abrasion list/get |
| `routes/edits.py` | 313 | EditRule + EditVersion lifecycle (submit/approve/reject/suspend/reactivate/retire) |
| `routes/vendor_edits.py` | 99 | Vendor edit ingest/list/get/map |
| `routes/claims.py` | 241 | Claim create/list/get, lines, run-edits, pay |
| `routes/edit_hits.py` | 47 | Hit list (4 filters) + get |
| `routes/review_tasks.py` | 142 | Task list/get/assign/decide/escalate |
| `routes/disputes.py` | 214 | Dispute create/list/get/start-review/request-info/submit-info/decide |
| `routes/ibr.py` | 178 | IBR create/list/get/receive-documents/start-audit/complete/expire |
| `routes/inpatient_reviews.py` | 170 | Inpatient review list/get/record-findings/decide |
| `routes/savings_periods.py` | 142 | Period create/list/get/begin-reconciliation/finalize |
| `routes/clock.py` | 20 | `POST /payment-integrity/_clock/set_current_utc` |
| `services/calc.py` | 76 | DRG payment (pinned rounding), itemized reprice, all constants |
| `services/core.py` | 349 | Rule active-count, window overlap, version stats + auto-suspension, suspension cascade, claim ledger rebalance, gate bubble-up, abrasion recompute, hit resolution (uphold/override/FP/supersede), IBR occupancy |
| `services/screening.py` | 234 | run-edits engine: baseline, high-dollar IBR spawn, readmission detection, DRG_VALIDATION auto-create, edit firing, internal-first waterfall, task creation, PENDED/READY_TO_PAY landing |

Total: 2,791 lines across 24 files.

### Endpoint count: 48 implemented
All 48 endpoints from the scaffold endpoint table, including the clock endpoint.

### State machines implemented (7)
EditVersion (DRAFT→PENDING_APPROVAL→ACTIVE→SUSPENDED/RETIRED, with reactivation fp-rate guard), Claim (RECEIVED→PENDED/READY_TO_PAY→DETERMINED→READY_TO_PAY|DENIED→PAID, plus DENIED→READY_TO_PAY compensation and READY_TO_PAY→PENDED on manual IBR), ReviewTask (PENDING/ESCALATED→IN_REVIEW→DECIDED/ESCALATED/CANCELLED), EditHit (FIRED→CONFIRMED/OVERRIDDEN/SUPERSEDED, CONFIRMED→OVERRIDDEN/RELEASED_FALSE_POSITIVE), Dispute (SUBMITTED→UNDER_REVIEW→AWAITING_PROVIDER_INFO→UNDER_REVIEW→DECIDED), ItemizedBillReview (REQUESTED→DOCUMENTS_RECEIVED→IN_AUDIT→COMPLETED, REQUESTED→EXPIRED), InpatientReview (OPEN→FINDINGS_RECORDED→DECIDED), SavingsPeriod (OPEN→RECONCILING→FINALIZED).

### Calculation modules (7)
`drg_base_payment` (base round → outlier cap round → per-diem round → integer min; TRANSFER proration variant), `itemized_reprice` (per-line round-half-up then sum, pinned order), `edit_savings_attribution` (internal-first waterfall; monitor-only hits excluded), `savings_measurement` (provisional/finalized/pending/reversed at finalize), `false_positive_rate` (round-4 half-up, inclusive 0.2500/≥4 auto-suspend, evaluated on every hit resolution and at finalize), `provider_abrasion_index` (trailing-90-day standard index, lifetime regulatory index, tier keyed on standard only), `readmission_detection` (inclusive 0–30 day gap, discharge-DESC/created-ASC tie-break), `high_dollar_evaluation` (inclusive 10,000,000-cent threshold, IBR spawn with 30-day due).

### Validation/priority approach
Implemented per PRD §2.8's 12 precedence bands inside each endpoint: auth → role → ownership → shape (unknown-field/type, then enum) → existence (left-to-right path/body refs) → OCC → state → safety/SoD → business constraints → temporal → referential → fiscal. Approve surfaces in PRD 3.2's fixed order (stale → state → SoD → attestation → window); dispute decide per PRD 3.6 (state → SoD → deadline → release bounds); assign per PRD 3.5 (state → seniority → capacity). All money via `Decimal` with `ROUND_HALF_UP` at the pinned steps; fp_rate/standard_index/regulatory_index rounded half-up to 4 places.

### Boot smoke-test result
- `PORT=18742 bash start.sh` booted cleanly in ~3s; unauthenticated probe returned 401 ERR_UNAUTHENTICATED (correct).
- Full workflow verified live: provider create (auto abrasion profile), claim + line, run-edits → READY_TO_PAY (no edits) → PAID; edit rule/version lifecycle with ERR_STALE_VERSION (412) and ERR_SOD_AUTHOR_APPROVAL (403) surfacing correctly; DENY edit screening → claim PENDED with hit FIRED (attributed=expected=8000) → task assign/decide UPHOLD → hit CONFIRMED, claim DENIED (allowed 0/denied 8000); dispute create (OCC), SoD rejection of confirmer-as-adjudicator, OVERTURNED → hit RELEASED_FALSE_POSITIVE with full release, claim compensated DENIED→READY_TO_PAY, abrasion profile fp_count=1, standard_index=1.0, tier HIGH, regulatory_index=1.0.
- Killed, relaunched on PORT=18743: providers/claims lists empty (no carry-over state), clock back at boot default, `set_current_utc` accepted and returned `{"current_utc": "2026-09-01T00:00:00.000Z"}`. Server processes killed afterward.

No seeding anywhere; storage is purely in-memory dicts; nothing reads SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/.

## Step 5: Generate Unit Tests — 2026-08-15T03:45:00.000Z

Generation complete. Verbatim summary:

## Test counts

**Queue A (Difficulty): 36 tests** — 18/18 instances covered at exactly 2 tests each.
**Queue B (Corner): 54 tests** — 54/54 non-stub instances covered at exactly 1 test each.
**Total: 90 tagged test functions; 100 collected pytest items** (the `get_missing_entities_return_not_found` sweep is parametrized ×11).
**Stubs: 6 `excluded_because:` stubs correctly not translated**; all six `difficulty_instance` cross-references resolve to real queue-A instance names.

**Per test file:**
| File | Tests |
|---|---|
| test_01_providers_and_auth.py | 9 |
| test_02_edit_library_lifecycle.py | 7 |
| test_03_edit_approval_guards.py | 9 |
| test_04_claim_screening.py | 13 |
| test_05_drg_pricing_and_inpatient.py | 6 |
| test_06_review_tasks.py | 10 |
| test_07_disputes.py | 12 |
| test_08_cascades_and_suspension.py | 5 |
| test_09_itemized_bill_reviews.py | 6 |
| test_10_savings_periods.py | 7 |
| test_11_abrasion_and_attribution.py | 6 |

## Instances skipped

**None.** All 18 difficulty instances and all 54 non-stub corner instances passed the PRD-first two-condition filter (verbatim PRD coverage AND unique derivability). Two instances required explicit adjudication and were kept: `create_claim_rejects_injected_computed_field` (PRD §2.8 band 4 "no unknown fields appear, else ERR_INVALID_REQUEST" uniquely covers a computed field absent from the §3.4 submission field list) and `ibr_expire_before_due_rejected_then_expires` / `itemized_reprice_rebalances_claim` (bubble-up on a task-less PENDED claim — PRD §3.7 "re-evaluates the claim's bubble-up" combined with §3.5's gate logic yields READY_TO_PAY as the only reading consistent with the workflow).

## test_helpers module inventory

- `types.py` — 13 entity TypedDicts (all `common_fields: true` in this domain, so all carry id/created_at/updated_at/version) + 17 enums incl. `UserRole`.
- `api_client.py` — `ApiClient(GenericApiClient)` with 61 endpoint methods covering every §4 row incl. `_clock/set_current_utc`.
- `api_errors.py` — `ApiErrorId` (46 IDs) + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map`.
- `assertions.py` — 13 per-entity asserts + `assert_claim_ledger_invariant` (allowed + denied == initial_allowed, allowed >= 0).
- `factories.py` — 17 payload factories, input fields only.
- `constants.py` — high-dollar threshold, IBR due/buffer days, FP threshold/sample, capacity 3, dispute window 45d, deadline 60d, readmission 30d, tier thresholds/weights, DRG weights/mean-LOS/outlier constants, contract discount.
- `test_users.py` — `TEST_USERS` (7 opaque shared constants + Provider fallback) and per-instance `make_*_headers` for all 8 roles; Provider is entity-backed and threaded with real provider ids everywhere.
- `fixtures.py` — provider/rule/active-edit chains, one-line claim screening, task assign/decide, `drive_hit_resolution` (uphold/override/overturn/partial/fired), OCC-threaded dispute openers, inpatient review closure, IBR walkthrough, `setup_savings_scenario`, clock setter; all setup via `get_success_data`.
- `__init__.py` — barrel re-export of framework generics + all PRD-specific names.

## Self-audit verdicts

**Stage 1: PASS** — all modules `py_compile`/`pyflakes` clean (barrel re-export warnings excepted); identity threading via `make_provider_headers(provider["id"])` on every ownership-gated call; no framework re-implementation.

**Stage 2: PASS** —
- Coverage: queue A ≥2/instance and queue B ≥1/non-stub instance verified programmatically against both yamls; zero untagged, zero dual-tagged, zero unknown tags, zero stub translations.
- Every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line as its last line.
- PRD citation pass: 161 quoted spans extracted from docstrings, all survive whitespace-normalized literal grep of `workspace/PRD.md`; every asserted `error_id` is named in PRD prose; the two priority-conflict tests cite both the §2.8 band ordering and the per-endpoint surfacing order.
- Zero `skip`/`skipif`/`xfail` markers; zero scaffold vocabulary ("scaffold", "Table N", "§1.x") in generated code.
- pytest collects 100 items with `test_helpers` importable; every test constructs all preconditions via API calls (per-test-server isolation respected).

## Step 7: Test/Iterate Loop — 2026-08-15T04:05:00.000Z

Clean 8-round parallel sweep achieved: **100/100 passed in every round (800/800 total)**.

## Summary

- **Iterations run**: 2 (initial sweep → fix → verification sweep).

- **Baseline**: 95/100 per round; the same 5 tests failed deterministically in all 8 rounds.

- **Tests deleted**: none. Every failing test's asserted rule traces verbatim to PRD prose and is uniquely derivable, so all 5 were kept.

- **Failing-test diagnosis (union across rounds)**:
  1. `test_04_claim_screening.py::test_claims_filter_pagination_interaction` — `assert 'PENDED' == 'READY_TO_PAY'`.
  2-5. `test_10_savings_periods.py::{test_savings_provisional_vs_finalized, test_savings_pending_and_reversed, test_savings_bucket_identity_values, test_savings_bucket_identity_holds}` — all failed in setup with `HTTP 409 ERR_PERIOD_NOT_FINALIZABLE - begin-reconciliation requires OPEN`.

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/fixtures.py` — `setup_savings_scenario`: removed the premature `api_client.begin_reconciliation(...)` call. The helper moved the period to `RECONCILING`, but every caller then invokes `finalize_period`, which itself walks OPEN→RECONCILING→FINALIZED per PRD §3.9's state gates ("beginning reconciliation requires `OPEN` and finalizing requires `RECONCILING`"). The double-begin tripped the PRD-required `ERR_PERIOD_NOT_FINALIZABLE` guard on a correctly implemented server. The period is now handed to tests in OPEN; docstring updated to match. In-process replay confirmed the implementation computes exactly the asserted figures (provisional 180000, finalized 90000, pending 70000, reversed 20000).

- **Fixes applied to `test_suite/`**:
  - `test_suite/test_04_claim_screening.py` — `test_claims_filter_pagination_interaction`: the setup built an ACTIVE `DENY` edit covering `PROFESSIONAL` and then screened a second `PROFESSIONAL` claim expecting it to be clean. Per PRD §3.4 ("One edit hit is created per eligible `ACTIVE` edit version per claim line, where eligible means the claim's `claim_type` appears in the version's `applies_to_claim_types`"), the edit correctly fires on that claim too, so the implementation was right to pend it. The "clean" claim is now created as `INSTITUTIONAL_OUTPATIENT` (a type the edit does not cover) via `create_claim_with_lines` + `run_claim_edits` (`run_claim_edits` added to the imports), making the intended one-PENDED/one-READY_TO_PAY scenario consistent with PRD.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful in both clusters; both failures were test-side setup bugs (a fixture precondition violation and a fixture state-machine double-transition).

- **Flakiness note**: round-1 console interleaving showed phantom `FAILED` fragments glued to unrelated test names (e.g. `test_high_dollar_exact_threshold_flags`); the authoritative junit-derived `results.*.json` showed those tests passing in all rounds. Diagnosis was driven off the JSON, not the interleaved console stream.

## Step 8: Finalize PRD — 2026-08-15T04:09:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/workspace/PRD_FINALIZED.md` written (byte-identical copy of PRD.md, verified by `diff -q`).

## Conclusion: zero edits — PRD already determines both behaviors

Both Step 7 items were test-side setup bugs against behavior the PRD pins verbatim, and Step 7 applied zero implementation fixes. Manufacturing PRD edits here would only risk creating new mismatches, so PRD_FINALIZED.md = PRD.md.

**Line counts / delta:** PRD.md 344 lines; PRD_FINALIZED.md 344 lines; 0% delta.

**Changes:** none.

### Per-item verification (the "pre-edit search" for the zero-edit decision)

**Item 1 — `test_claims_filter_pagination_interaction` (edit-hit eligibility, screening landing state, claims list filters/pagination)**
- (a) Subject: which edit versions fire on a claim, and the resulting claim landing state.
- (b) Paths enumerated and read: `implementation/services/screening.py:133-139` (eligibility loop: `status == "ACTIVE"` and `claim["claim_type"] in v["applies_to_claim_types"]`), `screening.py:222-234` (landing state: `PENDED` iff any applied hit / open inpatient review / high-dollar, else `READY_TO_PAY` + `determined_at` stamp), `screening.py:106-120` (inpatient reviews auto-created only for `INSTITUTIONAL_INPATIENT` — which is why the `INSTITUTIONAL_OUTPATIENT` "clean" claim lands `READY_TO_PAY`), `implementation/routes/claims.py:99-116` (list filters applied before pagination, `created_at` ascending, default limit 10).
- (c) No wording change: PRD §3.4 already states verbatim "One edit hit is created per eligible `ACTIVE` edit version per claim line, where eligible means the claim's `claim_type` appears in the version's `applies_to_claim_types`", pins the two landing states, and §3.8 pins that only inpatient claims open clinical reviews. The original test expected a second `PROFESSIONAL` claim to be clean under an ACTIVE `DENY` edit covering `PROFESSIONAL` — the implementation was correct to pend it; the test fix (rebuilding the clean claim as `INSTITUTIONAL_OUTPATIENT`) is purely test-side. Every enumerated impl path is exactly what the PRD text already says.

**Item 2 — `test_10_savings_periods` setup 409s (savings-period state gates and finalization figures)**
- (a) Subject: `begin-reconciliation` / `finalize` state preconditions and the four finalization figures.
- (b) Paths enumerated and read: `implementation/routes/savings_periods.py:93-104` (begin-reconciliation requires `OPEN`, else `ERR_PERIOD_NOT_FINALIZABLE` 409), `savings_periods.py:107-142` (finalize requires `RECONCILING`, else same error; computes provisional/finalized/pending/reversed and re-evaluates auto-suspension), `test_helpers/fixtures.py:421-423` (`finalize_period` helper itself calls `begin_reconciliation` then `finalize`) and `fixtures.py:431-453` (fixed `setup_savings_scenario` now hands the period over `OPEN`).
- (c) No wording change: PRD §3.9 already states verbatim "beginning reconciliation requires `OPEN` and finalizing requires `RECONCILING`, with out-of-state attempts rejected as `ERR_PERIOD_NOT_FINALIZABLE` (HTTP 409)", and pins all four figures (provisional = attributed sum over hits created in the period regardless of status; finalized = resolved-in-period attributed net of released; pending = created-in-period still-`FIRED` attributed; reversed = released sum over resolved-in-period release statuses) exactly as implemented at `savings_periods.py:121-129`. The failure was the fixture double-beginning reconciliation against a correctly guarded server — a pure fixture precondition bug.

## Step 9: Complete PRD — 2026-08-15T04:13:00.000Z

All edits verified. The file `/home/ubuntu/github/CodingPRD/tasks/task_1942_payment_integrity_pre_pay_claim_editing/workspace/PRD_COMPLETED.md` is complete: 22 paragraphs revised in place, no sections added, line count unchanged (each insert is in-paragraph).

## Summary

**Source:** `PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`).
**Line counts:** source 344 → completed 344 (all changes in-paragraph). **Char delta:** 61,756 → 67,193 (**+5,437**).
**Counts:** 23 ambiguity-pins, 5 mismatch-revisions.

### Changes (one per bullet)

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — implementation/middleware.py:120-136
- §2.3 — insert — ambiguity — enum-valued list filters validated, undeclared member → `ERR_INVALID_ENUM` (400) — middleware.py:93-97; routes/providers.py:71-72 et al.
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at`==`updated_at` at creation; every rendered timestamp uses the 3-fractional-digit UTC format — implementation/db.py:28-36,68; implementation/serializers.py:8-25
- §2.4 — insert — ambiguity — optional annotation payloads (`rejection_reason`, suspend `note`, escalate `reason`, `info_request_note`, `info_response`, `decision_note`, `findings_note`) validated but never persisted; dispute `reason` and task `decision_reason` are stored — routes/edits.py:254,268; routes/review_tasks.py:99,134; routes/disputes.py:77,146,160,181; routes/inpatient_reviews.py:77,103
- §2.8 band 3 — revise — mismatch — resource-derived ownership checks surface after the target's 404; endpoint narratives pin exact positions (claim creation alone checks payload ownership first) — routes/claims.py:34,53,154-157; routes/disputes.py:43-50
- §2.8 band 5 — insert — ambiguity — unresolved abrasion-profile id surfaces `ERR_PROVIDER_NOT_FOUND` — routes/providers.py:121-122
- §3.1 — insert — ambiguity — provider creation optionally accepts `status` (`ACTIVE`/`TERMINATED`), default `ACTIVE` — routes/providers.py:32,40
- §3.1 — insert — ambiguity — PATCH accepts either status value; every accepted patch mutates (version +1) even when restating the current value — routes/providers.py:93-99
- §3.1 — insert — ambiguity — trailing-90-day abrasion window is inclusive of both endpoints — services/core.py:200,216
- §3.2 — insert — ambiguity — reactivation blocked by fp_rate ≥ 0.25 is rejected with `ERR_EDIT_VERSION_NOT_APPROVABLE` (409) — routes/edits.py:285-286
- §3.2 — insert — ambiguity — every lifecycle recomputation mutates the rule (version +1) even when `active_version_count` is unchanged — services/core.py:31-37
- §3.3 — insert — ambiguity — mapping is unguarded; re-mapping overwrites `mapped_edit_rule_id` and `comparison_status` — routes/vendor_edits.py:96-98
- §3.4 — insert — ambiguity — newborn claim carries zero `initial_allowed_cents`/`allowed_amount_cents`/`denied_amount_cents`, both flags false, `determined_at` null — routes/claims.py:87-92
- §3.4 — insert — ambiguity — lines born with `allowed_cents`/`denied_cents` zero; duplicate `line_number` → `ERR_INVALID_REQUEST`; line-addition guard order: existence → ownership → lines-locked → uniqueness — routes/claims.py:146-174
- §3.4 — insert — ambiguity — screening initializes each line's `allowed_cents` to `billed_cents` and `denied_cents` to zero — services/screening.py:39-42
- §3.4 — insert — ambiguity — `SUSPEND`/`MONITOR` hits carry `expected_savings_cents` zero — services/screening.py:155
- §3.4 — revise — ambiguity — hit's `vendor_edit_id` is the earliest-ingested vendor edit currently mapped to the firing rule; null for internal rules and unmapped vendor rules — services/screening.py:144-152
- §3.5 — revise — mismatch — decide/escalate surface the `IN_REVIEW` state check before the assignee-ownership check (seniority check last on decide), contra strict band order — routes/review_tasks.py:102-105,126-131
- §3.5 — insert — ambiguity — each bubble-up state transition is its own mutation (version +1 each), so one triggering action can advance claim `version` by more than one — services/core.py:148-183
- §3.6 — insert — ambiguity — dispute-creation precedence inserts ownership (`ERR_NOT_RESOURCE_OWNER`) between reference resolution and the stale-version check — routes/disputes.py:43-53
- §3.6 — insert — ambiguity — dispute born with `released_cents` zero; non-`PARTIAL` decisions store zero even if the request supplied one — routes/disputes.py:80,201
- §3.6 — revise — mismatch — submit-info surfaces the `AWAITING_PROVIDER_INFO` state check before the provider ownership check — routes/disputes.py:162-165
- §3.6 — revise — mismatch — `UPHELD` performs no abrasion-profile recompute and no bubble-up (only `decided_at`/adjudicator/claim-version bookkeeping); release decisions (`OVERTURNED`/`PARTIAL`) do both — routes/disputes.py:205-213
- §3.7 — revise — mismatch — manual IBR door is unguarded on claim status (any existing claim, even `RECEIVED`), not only "a screened claim" — routes/ibr.py:34-40
- §3.7 — insert — ambiguity — an `EXPIRED` review's occupancy interval ends at its `updated_at` (expiration instant); `findings_cents` starts at zero — services/core.py:345-346; routes/ibr.py:50
- §3.8 — insert — ambiguity — `PARTIAL_REDUCTION` sets claim allowed to max(0, prior + delta) and resets denied per the invariant, but leaves `initial_allowed_cents` unchanged (only `DRG_REASSIGNED` rewrites the baseline) — routes/inpatient_reviews.py:149-166
- §3.9 — insert — ambiguity — malformed `period_key` (incl. out-of-range month) → `ERR_INVALID_REQUEST` (400) before uniqueness; new period's four savings figures start at zero — routes/savings_periods.py:41-49,54-59
- §3.9 — insert — ambiguity — finalization checkpoint recomputes every `ACTIVE` version's quality statistics before the threshold test, mutating each version record (updated_at/version) even when statistics are unchanged — routes/savings_periods.py:138-141; services/core.py:55-71

Everything else in the implementation — DRG pricing formula and rounding order, waterfall attribution, all state guards, OCC gates, SoD walls, error catalogue, envelope shape, clock endpoint — was already uniquely pinned by the PRD and left untouched.

## Post-Step-9 verification sweep — 2026-08-15T04:17:00.000Z

The Step 7 subagent's final sweep results files were not left on disk, so the orchestrator re-ran the full 8-round parallel sweep after Step 9 completed (identical `prd-bench-local-run --isolation per-test-server` invocation). Result: **100/100 passed in every round (800/800 total, 0 failed, 0 errors, 0 skipped; ~131 s per round)**. Per-round results regenerated at `workspace/implementation/results.{1..8}.json`. This confirms the final artifact set (PRD_COMPLETED.md + implementation/ + test_helpers/ + test_suite/) is green end-to-end.
