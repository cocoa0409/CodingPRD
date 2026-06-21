# Worklog — task_0008_mortgage_origination

## Step 1: Create task directory — 2026-05-26

Created `tasks/task_0008_mortgage_origination/` and `tasks/task_0008_mortgage_origination/workspace/` (pre-allocated index per orchestrator argument; no re-scan performed).

## Step 2: Generate scaffold — 2026-05-26

Generated three scaffold artifacts at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0008_mortgage_origination/`:

- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency_rules)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

`scaffold_lint.py` verdict: **clean lint** — all 364 §1.8/§1.9 calls conform to §1.5 and all 8 §1.1 FKs (every child→LoanApplication and LoanApplication→Applicant) have reverse-reachability GETs in §1.5.

**Counts:**

| Item | Count |
|------|-------|
| Entities (§1.1) | 9 (Applicant, LoanApplication, IncomeVerification, AssetVerification, Appraisal, TitleSearch, RateLock, Disclosure, UDAAPCheck) |
| State machines (§1.2) | 7 (LoanApplication, IncomeVerification, AssetVerification, Appraisal, TitleSearch, RateLock, Disclosure) |
| Concurrency rules (§1.2.1) | 2 (rate-lock create stale, disclosure create stale — both OCC on LoanApplication.version) |
| Calculations (§1.3) | 6 (dti_ratio, ltv_ratio, apr_calculation, rate_lock_extension_calc, trid_timeline_calc, cd_redisclose_check) |
| Validations (§1.4) | 18 (priorities 1–17 plus a 13.5 lock-duration cap) |
| Endpoints (§1.5) | 48 (includes one `/_clock/set_current_utc` test-driving endpoint) |
| Error codes (§1.6) | 18 |
| Roles (§1.7) | 7 (LoanOfficer, Underwriter, Closer, Appraiser, TitleAgent, ComplianceOfficer, Applicant — six opaque + one entity_backed:Applicant) |
| §1.8 difficulty instances | 18 (9 rules × 2 instances each) |
| §1.9 corner instances | 44 (34 with full `test_recipe` + 10 `excluded_because:` stubs pointing into §1.8) |

**Complexity profile:** compliance_audit (primary) blended with workflow_orchestration (secondary); layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_deferred_actions; entity_topology=hybrid; state_machine_shape=branching (LoanApp prequalify branches and auto-DENY cascade; Appraisal cyclic COMPLETED↔RECONSIDERED; RateLock ACTIVE→ACTIVE self-loop); role_model=segregation_of_duties (ERR_SOD_VIOLATION enforces LoanOfficer ≠ Underwriter on same application).

**Key difficulty signatures:** dual-variant APR (provisional ignores extension fees vs final includes them) and dual-variant DTI (front-end housing-only vs back-end housing+debt); nested-rounding rate-lock extension fee (per-extension round-then-sum, principal chosen so order matters); depth-3 cascade Appraisal-COMPLETE → LTV recompute → LoanApp auto-DENY → RateLock auto-CANCEL; TRID timeline max-merge of LE+7d and CD+3d floors; CD redisclose strict-> 12.5 bps APR delta boundary.

## Step 3: Copy INSTRUCTION.md — 2026-05-26

Copied `INSTRUCTION.md` from project root to `tasks/task_0008_mortgage_origination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-26

**PRD generated at:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0008_mortgage_origination/workspace/PRD.md` (281 lines).

**Section layout (domain-derived, not example-copied):**

- §1 Introduction — 2 paragraphs framed around three simultaneous pressures (regulatory/TRID+UDAAP, financial/rate-lock, operational/SoD)
- §2 Global Specifications — 10 subsections:
  - 2.1 User and Role-Based Access Control (lists all 7 roles; explicitly translates `Applicant` as entity-backed and the other six as opaque-operator)
  - 2.2 API Response Structure (verbatim from section-2.2-response-structure.md)
  - 2.3 Pagination
  - 2.4 Common Resource Properties (explicitly calls out `UDAAPCheck` as the only entity with `common_fields: false` — has only `id` and `created_at`)
  - 2.5 Optimistic Concurrency Control (both `concurrency_rules` entries spelled out with `write_endpoint`, `expected_application_version`, `ERR_STALE_VERSION`, HTTP 412)
  - 2.6 Hierarchical Consistency and Cascading Mutations (introduces appraisal-LTV three-hop cascade and rate-lock supersession)
  - 2.7 Nested Resource Retrieval
  - 2.8 Validation Priority Ordering (priorities 1–17 expressed as explicit ordering prose, including the in-business-tier ordering)
  - 2.9 Monetary Precision, Ratio Precision, and Time Arithmetic
  - 2.10 Test-Driving the Clock (frames `/_clock/set_current_utc` as a capability)
- §3 Business Logic & Workflows — 10 subsections organized by lifecycle-stage timeline (Applicants → Pre-Qual → Verifications → Appraisal+Cascade → Title → RateLock → Disclosures+APR+TRID → UDAAP → Submission/Approve/Deny/Withdraw → Clear-to-Close/Close)
- §4 Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Role(s)), with no request bodies or side effects in the table
- §5 Error Code Catalogue — 2-column table (Error ID, HTTP Status Code), with no trigger conditions

**Information scattering decisions:**

- Pre-qualification's `back_end_dti ≤ 0.43` AND `ltv_ratio ≤ 0.95` thresholds and the `prequal_decision` enum live in §3.2, while the front-end DTI ceiling of 0.31 (`ERR_DTI_FRONTEND_TOO_HIGH`) is introduced as a short-circuit BEFORE the approve/deny branch — readers must reconstruct that priority from prose, not from a table.
- Rate-lock extension fee tier table (`{7: 5, 15: 10, 30: 25}` bps) is embedded in §3.6 narrative; the per-extension-rounding-before-summing rule is called out as "load-bearing" in prose form.
- The 90-day total-duration cap, the extension-count cap of 2, and the lock-expired temporal check are all distributed across §3.6 — and their firing order is restated in §2.8 (validation priority ordering subsection) to enforce the priority-ordering Contract 2 requirement.
- Segregation-of-duties (`ERR_SOD_VIOLATION`) is split: the originating LoanOfficer's `X-User-ID` capture appears at §3.1 (creation side effect); the comparison rule appears at §3.9 (approve). The capture-then-compare narrative spans two subsections by design.
- APR computation lives in §3.7 with its Newton-Raphson seed, tolerance `1e-8`, and 50-iteration cap as prose. The `change_requires_redisclose` 12.5 bps boundary explicitly notes that "exactly 12.5 bps → false" (not a redisclose trigger), preserving the inequality strictness.
- TRID 7-day-LE / 3-day-CD floors are described as "exactly 7 times 86400 seconds" and "exactly 3 times 86400 seconds" rather than "approximately a week / three days" — translating the scaffold's "no DST adjustments" requirement into reconstructible prose.

**Rules in SCAFFOLD.yaml that resisted natural-language phrasing (flag for finalize pass):**

1. **APR Newton-Raphson formula.** The present-value identity `effective_principal_cents = sum_{k=1..n} monthly_payment_cents / (1 + apr_decimal/12)**k` translated into prose may strain implementer comprehension.
2. **DTI housing-payment formula.** Same amortization formula appears twice (once for DTI housing payment in §3.2, once for the APR's monthly_payment in §3.7) with slightly different framings.
3. **Rate-lock cascade-hop accounting.** Appraisal completion always-incrementing-vs-only-when-LTV-recomputed is preserved but subtle.
4. **Auto-cascade symmetry** from PREQUALIFIED OR UNDER_REVIEW phrased as unusual prose.
5. **Withdraw's from-state symmetry** compressed into a single sentence.

**Hard Contracts:** Field coverage PASS (54/54), Rule coverage PASS, Path purity PASS (0 path tokens in §3, 389 backtick tokens scanned).

## Step 5: Generate unit tests — 2026-05-26

**Stage 1 (test_helpers/)** — 9 modules generated:
- `types.py` (239 lines) — entity TypedDicts, status enums, role enum; UDAAPCheck omits `updated_at`/`version` per PRD §2.4
- `api_client.py` (211 lines) — one method per PRD endpoint
- `api_errors.py` (50 lines) — 18 error IDs with HTTP-status mapping
- `assertions.py` (148 lines) — per-entity assertions; `assert_udaap_check` deliberately omits updated_at/version
- `factories.py` (216 lines) — payload factories with auto-incremented email/ssn defaults
- `constants.py` (56 lines) — PRD thresholds
- `test_users.py` (55 lines) — role-headers dict + `make_applicant_headers(applicant_id)`
- `fixtures.py` (381 lines) — 5-tier composite setup
- `__init__.py` (121 lines) — barrel export

**Stage 2 (test_suite/)** — 10 test files, 67 test functions:
- `test_01_prequalify_and_dti.py` (11), `test_02_appraisal_and_ltv.py` (9), `test_03_rate_lock_and_extension.py` (9), `test_04_disclosures_and_apr.py` (6), `test_05_trid_and_close.py` (5), `test_06_workflow_state_transitions.py` (6), `test_07_validations_and_priority.py` (6), `test_08_crud_and_inputs.py` (9), `test_09_rbac.py` (4), `test_10_occ_and_concurrency.py` (2)

**Coverage audit:**
- Queue A (Difficulty): 17 of 18 instances translated × 2 tests each = 34 tests
- Queue B (Corner): 33 of 34 non-stub instances translated × 1 test each = 33 tests
- 10 corner stubs (excluded_because) correctly not translated

**Skipped under PRD-first filter (2 total):**
1. `Difficulty/priority_pair_validation_conflict/lock_expired_vs_extension_cap_on_extend` — instance asserts ERR_EXTENSION_CAP_EXCEEDED wins, but PRD §2.8 verbatim says ERR_LOCK_EXPIRED fires first. Unique derivability fails.
2. `Corner/endpoints/title_search_filtered_list_by_application_id` — PRD §2.3 enumerates only `limit`/`offset` as list query params; never names `application_id` as a filter. Applies_to-scope silence.

**Cross-test isolation concerns:** none. Per-test server restart, fresh DB, no test relies on others' entities.

## Step 6: Generate implementation — 2026-05-26

**Source files (21 total):**
- Root: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `requirements.txt`, `start.sh`
- `routes/` (10): `applicants.py`, `loan_applications.py`, `income_verifications.py`, `asset_verifications.py`, `appraisals.py`, `title_searches.py`, `rate_locks.py`, `disclosures.py`, `udaap_checks.py`, `clock.py`, `__init__.py`
- `services/` (4): `calculations.py`, `common.py`, `lookup.py`, `__init__.py`

**Stack:** Python 3 + Flask 3.0.3. `start.sh` does `pip install -q -r requirements.txt && exec python3 app.py`. Server binds `0.0.0.0:$PORT` (default 10000), foreground, threaded.

**Architectural decisions:**
- **State machines** dispatched directly inside each endpoint handler (no central dispatcher). Validation priority enforced by ordering checks in code.
- **OCC** for `POST /rate-locks` and `POST /disclosures`: `expected_application_version` required int, mismatch → `ERR_STALE_VERSION` (412).
- **Cascades:** Appraisal-LTV three-hop (appraisal → loan-app version bump → if LTV>0.95 DENIED + cascade ACTIVE locks → CANCELLED); rate-lock supersession; disclosure same-type supersession; lazy lock expiry on read.
- **Validation priority on extend:** state → ERR_LOCK_EXPIRED (13) → ERR_EXTENSION_CAP_EXCEEDED (11) → ERR_LOCK_DURATION_CAP_EXCEEDED (13.5) → ERR_INVALID_EXTEND_DAYS (12).
- **Monetary precision:** integer cents; ratios/APR use `decimal.Decimal` ROUND_HALF_UP. Rate-lock extension fees per-extension rounded half-up *before* summing.
- **Tie-breaking sort key:** hidden `_seq` monotonic counter appended after `created_at` for deterministic ordering.

**Interpreted PRD prose where exact semantics were ambiguous:**
1. **TRID disclosure set** — "DELIVERED" treated as "has been delivered" ({DELIVERED, ACKNOWLEDGED}) since CD must be ACKNOWLEDGED for CTC.
2. **CD redisclose comparison** — also includes ACKNOWLEDGED; excludes the newly-delivered CD itself.
3. **Applicant email uniqueness** — no specific error reserved; returns `ERR_INVALID_REQUEST`.
4. **CD redisclose freshness** — "fresh" = "delivered after the flagged one's delivered_at" (strictly later).
5. **Submit-for-review LE prereq** — ACKNOWLEDGED also satisfies "at least one DELIVERED LE".

**Storage:** Pure in-memory Python dicts. No on-disk persistence, no startup seeding, no hardcoded entities. Only "seed" is Newton-Raphson initial value in `compute_apr_percent`.

## Step 7: Iterate tests + fixes until green — 2026-05-26

All 8 parallel rounds passed (66/66 each). Exiting per the protocol.

- **Iterations run:** 2 (initial diagnostic + one fix-and-verify sweep).

- **Tests deleted:**
  - `test_applicant_get_not_found` in `test_suite/test_08_crud_and_inputs.py` — STEP 1b unique-derivability collapse. PRD §2.7 names `ERR_APPLICATION_NOT_FOUND` for missing loan-application path segments and `ERR_APPLICANT_NOT_FOUND` only for FK-in-body referents, but is silent on which error_id applies when the path on `GET /applicants/{id}` is missing. A PRD-faithful reader could pick either code.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_01_prequalify_and_dti.py::test_prequalify_branches_to_pass_or_deny_on_back_end_dti` — FAIL applicant had `annual_income_cents=4_800_000` which made front-end DTI ≈ 0.50, tripping the priority-higher `ERR_DTI_FRONTEND_TOO_HIGH` ceiling instead of the back-end-DTI branch the test was designed to exercise. Changed to `annual_income_cents=7_726_104` + `monthly_debt_cents=100_000` so front-end stays at 0.31 (the ceiling) while back-end DTI ≈ 0.4653 > 0.43.
  - `test_02_appraisal_and_ltv.py::test_appraisal_cyclic_completed_reconsidered_completed_loop`, `::test_appraisal_reconsider_roundtrip_preserves_ltv`, `::test_appraisal_cyclic_two_full_revisions`, `::test_appraisal_reconsider_first_recompute_changes_ltv` — all four used appraised values (e.g. 31_000_000 against property=31_578_948) that drove the recomputed LTV above 0.95 on the very first complete, firing PRD §3.4's auto-DENY cascade and ending the parent app's life before the subsequent reconsider/confirm steps could run. Raised `property_value_cents` to 50_000_000 and chose appraised values (32M–45M) that hold LTV at 0.75–0.9375. The roundtrip LTV assertion was retuned to 0.9375 (= 30M/32M) and the recompute-changes assertion was retuned to compare 0.8571 vs 0.75.
  - `test_04_disclosures_and_apr.py::test_apr_provisional_versus_final_diverge_after_extension` — assertion expected `final_apr == 6.895`. PRD §3.7 explicitly mandates two-step rounding: converged apr_decimal → 4dp → ×100 → 3dp. The PRD-faithful pipeline yields `0.068946 → 0.0689 → 6.89 → 6.890`, not 6.895. Corrected the expectation to 6.890 (provisional 6.870, still divergent).

- **Fixes applied to `implementation/`:** none. All seven original failures traced to test-side bugs.

## Step 8: Finalize PRD — 2026-05-26

**Line counts:** PRD.md 281 lines, PRD_FINALIZED.md 281 lines. Delta: +0 lines (0.00%). Net character delta: one inline clause added inside the §2.7 paragraph; no new paragraphs/sections.

**Step 7 diff items, mapped to impl:**

- **Item 1 (test_applicant_get_not_found, PRD §2.7 silence on GET /applicants/{id} 404 error_id):** Genuine PRD silence. impl `routes/applicants.py:113-119` raises `ERR_APPLICANT_NOT_FOUND` when the `aid` path segment misses. PATCHED.
- **Item 2 (test_prequalify_branches_to_pass_or_deny_on_back_end_dti):** Pure fixture bug. PRD §2.8 + §3.2 already pin front-end DTI fires before back-end branching; impl `routes/loan_applications.py:232-237` follows verbatim. No PRD silence; no patch.
- **Item 3 (four appraisal-cycle tests):** Pure fixture bug. PRD §3.4 already pins the LTV>0.95 auto-DENY cascade verbatim, and impl `services/calculations.py:127-132` uses `min(property_value, appraised)` exactly per PRD. No PRD silence; no patch.
- **Item 4 (test_apr_provisional_versus_final_diverge_after_extension, 6.890 vs 6.895):** Pure fixture/expectation bug. PRD §3.7 already pins the two-step rounding (4dp decimal → ×100 → 3dp percent); impl `services/calculations.py:188-190` implements that exact pipeline. No PRD silence; no patch.

**Changes:**
- §2.7 — insert — added one inline sentence pinning that `GET /applicants/{id}` returns `ERR_APPLICANT_NOT_FOUND` (HTTP 404) for a missing applicant path segment — `implementation/routes/applicants.py:113-119`
