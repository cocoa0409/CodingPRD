# Worklog — task_0424_pension_defined_benefit_administration

## Step 1: Create Task Directory — 2026-06-19T13:30:51.000Z

Created `tasks/task_0424_pension_defined_benefit_administration/` and `tasks/task_0424_pension_defined_benefit_administration/workspace/` (pre-assigned directory, no auto-increment). Confirmed `INSTRUCTION.md` exists at project root for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-19T14:10:44.000Z

All structural checks pass. The scaffold package is complete and consistent.

Generated all three scaffold artifacts for **task_0424_pension_defined_benefit_administration**, all written to the target directory and passing `scaffold_lint.py` with `VERDICT: clean lint`.

**Files written (all three required):**
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Counts (Expert band per §0.4):**
- **Entities: 10** — PensionPlan, Participant, AnnualCompensation, ServiceCreditAdjustment, PlanYearFiling, PbgcPremiumFiling, BenefitElection, QdroAward, BenefitPayment, SpousalConsent
- **Endpoints: 41** (15 GET + 26 POST)
- **Errors: 18**
- **Roles: 3** — PlanSponsor, PlanActuary, BenefitsAdministrator (segregation-of-duties model)
- **State machines: 6** — Participant (**parallel dimensions**: employment_status × vesting_status evolving independently), BenefitElection (**branching + cyclic** revision loop APPROVED→DRAFT→SUBMITTED), QdroAward (**branching + cyclic** amend loop REJECTED→DRAFT), BenefitPayment (**cyclic** suspend/resume IN_PAY⇄SUSPENDED), PlanYearFiling (certify + supersede), PensionPlan (posture-driven termination). Four machines carry cycles or parallel dimensions.
- Plus: 13 calculations (incl. dual-variant FAP-vs-CB benefit formula and SLA-vs-417(e) lump-sum), 16 validations, 1 concurrency rule (OCC on PensionPlan.version).

**Difficulty design:** all 9 §0.5 rules × 2 instances = **18 instances**. **Corner design:** 32 active instances + 5 `excluded_because` stubs across all 9 claim-extraction sections. All formula-derived asserts are precomputed literals (verified by code); all FKs are reverse-reachable; no forbidden concurrency vocabulary; all `grounds[]` resolve and all instance names are unique.

**Note on endpoint count:** 41 sits above the 20–32 guideline — structural floor for this domain (10 entities with rich lifecycles drive ~26 state-transition POSTs + ~15 discovery GETs from canonical-FK reverse-reachability). Consolidated from 43 to 41. Skill treats count as guideline; difficulty located in coupling depth.

## Step 3: Copy Shared Files — 2026-06-19T14:11:06.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0424_pension_defined_benefit_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-19T14:16:11.000Z

Generated `workspace/PRD.md` (267 lines, written and confirmed on disk). Difficulty/corner design files were NOT opened.

**Section structure:**
- **§1. Introduction** — framing dual-variant (FAP vs cash-balance) and compliance-gating nature + three segregated roles.
- **§2. Global Specifications** — 2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Funded-Status Posture & Gating, 2.6 Precision/Rounding, 2.7 OCC on Certification, 2.8 Hierarchical Consistency & Cascades, 2.9 Nested Retrieval, 2.10 Validation Ordering.
- **§3. Business Logic** — 3.1 plan setup, 3.2 census/service credit (parallel employment×vesting axes), 3.3 compensation & benefit bases, 3.4 election form/reduction/valuation, 3.5 QDRO splits, 3.6 funded-status filings, 3.7 PBGC premiums, 3.8 payments/COLA.
- **§4. Endpoint Definitions** — 4-column table (42 endpoints) + query-param sentence.
- **§5. Error Code Catalogue** — 2-column table (18 error IDs).

All three Hard Contracts PASS (Field coverage 59/59 + 5/5; Rule coverage 16 validations + 1 OCC + 6 state machines + 14 calculations; Path purity 0 violations).

## Step 5: Generate Unit Tests — 2026-06-19T14:32:28.000Z

**Test infrastructure generated.**

**`test_helpers/`** (9 files): `__init__.py`, `types.py` (entity TypedDicts + status/role enums; append-only `ServiceCreditAdjustment`/`SpousalConsent` carry only `id`+`created_at`), `api_client.py` (one method per PRD endpoint), `api_errors.py` (18 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (three opaque roles + distinct ADM_A/ADM_B for segregation-of-duties), `fixtures.py` (composite lifecycle helpers).

**`test_suite/`** (6 files): `conftest.py` + 5 domain test files (`test_01_benefit_calculations`, `test_02_election_lifecycle`, `test_03_cascades_and_payments`, `test_04_funding_and_concurrency`, `test_05_crud_uniqueness_rbac`).

**Test counts: 68 total.** Queue A (Difficulty): all 18 instances × 2 tests = 36. Queue B (Corner): all 32 non-stub instances × 1 test = 32. **0 instances skipped** — every non-stub instance passed the PRD-first two-condition filter. 5 corner stubs (`election_revision_cycle`, `record_death_cascade`, `aftap_frozen_below_060`, `benefit_formula_cash_balance_variant`, `benefit_not_available_below_age_55`) correctly not translated (carry `excluded_because`).

Verification: all files compile; every difficulty instance ≥2 tagged tests, every non-stub corner instance exactly 1 (set-diff verified); every docstring ends with one `Design:` line; ~24 PRD citations grep-verified; all imports resolve; all literal expected values independently recomputed from PRD formulas and matched.

## Step 6: Generate Implementation — 2026-06-19T14:32:28.000Z

Built Python + Flask implementation at `workspace/implementation/`.

**File structure:** `start.sh` (executable launcher), `requirements.txt` (Flask==3.0.3), `app.py` (single-file server ~1580 lines: foundation → calculations → routes).

**Endpoint count: 41 functional** (matching PRD §4 table) + unlisted `/health`. Covers all 11 entities.

**start.sh contract confirmed:** reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec python3 app.py`, dependency install guarded against concurrent reboots.

**Boot confirmed:** boots cleanly from fresh process, `/health` returns 200 within ~3s, empty in-memory store (no seeding), Python dicts keyed by id, no disk persistence. 76 smoke assertions across 3 suites all passing. `decimal.Decimal` ROUND_HALF_UP for money/ratios, ROUND_DOWN for service-credit/payment-setup floors per PRD.

## Step 7: Run Tests and Iterate — 2026-06-19T14:37:54.000Z

All 8 parallel rounds pass with 68/68 (verified: rounds 1–8 each passed=68 total=68). The sweep is clean.

**Iterations run:** 2 (one baseline sweep that surfaced the failure, one verification sweep confirming the fix).

**Tests deleted:** None. The single failing test was PRD-covered, uniquely derivable, and faithful — the bug was in the implementation.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py`, function `create_spousal_consent` — the `consenting_spouse_dob` DOB-match check was rejecting **any** consent on an election whose `spouse_date_of_birth` was `None` (`if e.get("spouse_date_of_birth") is None or ...`). LUMP_SUM elections never carry a `spouse_date_of_birth` (PRD §3.4: "both are ignored for the other forms"), yet they must proceed through spousal consent (PRD §3.4: "a `JOINT_AND_SURVIVOR` or `LUMP_SUM` election is automatically advanced ... to `SPOUSAL_CONSENT_PENDING`, because those forms require spousal consent" and approval requires a `SpousalConsent` with `waives_qjsa == true`). The old logic made every LUMP_SUM election unapprovable. Changed the guard to apply the match only when the election actually carries a `spouse_date_of_birth` (`if e.get("spouse_date_of_birth") is not None and to_date(dob) != ...`), so J&S consents still require an exact DOB match while LUMP_SUM consents (which have nothing to match against) are accepted.

**Diagnostic trace:** The lone failure across all 8 baseline rounds — `test_lump_sum_relative_value_failed_age_57` — failed deterministically in a setup step (`record_spousal_consent` on a LUMP_SUM election → HTTP 422 `ERR_INVALID_REQUEST`). STEP 1 confirmed the asserted rule (`ERR_RELATIVE_VALUE_FAILED` for an age-57 lump sum below the 0.95 floor) is verbatim in PRD §3.4 and uniquely determined. STEP 2 confirmed the test setup was PRD-faithful. STEP 3 located the root cause in the implementation's over-broad DOB-match guard. After the fix, all 8 parallel rounds report 68/68 with no flakiness.

## Step 8: Finalize PRD — 2026-06-19T14:40:04.000Z

Produced `workspace/PRD_FINALIZED.md` (Step 7 had 1 implementation fix → Step 8 not skipped).

**Line counts:** PRD.md = 267 lines, PRD_FINALIZED.md = 267 lines (line 160 edited in place; %-delta in lines = 0%, change is intra-line prose expansion).

**Change:**
- **§3.4 (Spousal Consent) — revise — DOB-match scope** — Changed the unconditional rule "`consenting_spouse_dob` (which must match the election's `spouse_date_of_birth`)" to specify that the match is enforced **only when the election carries a `spouse_date_of_birth`** (i.e., `JOINT_AND_SURVIVOR`); a `LUMP_SUM` election has no `spouse_date_of_birth`, so its consent is accepted regardless of the supplied value. `consenting_spouse_dob` remains a required date in both cases. — `implementation/app.py:1304` (required) and `app.py:1314` (conditional match).

**Pre-edit search log (Edit 1):** (a) Subject: `consenting_spouse_dob` ↔ `spouse_date_of_birth` matching rule + lifecycle of `spouse_date_of_birth` across forms. (b) Enumerated `create_spousal_consent` (app.py:1299-1325), `create_election` (app.py:1099-1119, confirms `spouse_date_of_birth` non-None only for J&S), `calc_js_reduction` (app.py:555-570, reads it only in J&S branch), full grep of both field names (no other writer/clearer; reopen does not repopulate). (c) Kept `consenting_spouse_dob` as "a required date" (always required), scoped match to J&S only, explicitly stated LUMP_SUM accept-regardless; tied `ERR_INVALID_REQUEST` rejection to J&S case only. Sole edit (Step 7 diff had exactly one impl fix, no deletions, no test_helpers fixes).

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-19T18:48:27.000Z

Resumed after an account-session-limit interruption that had killed the prior Step 9 right after the initial copy (PRD_COMPLETED.md was byte-identical to PRD_FINALIZED.md, scan never ran). Re-ran Step 9 fully: re-copied PRD_FINALIZED.md → PRD_COMPLETED.md, then performed the full PRD-vs-`implementation/` scan. Steps 1–8 artifacts (SCAFFOLD*.yaml, PRD.md, PRD_FINALIZED.md, test_suite/, test_helpers/, implementation/) left untouched.

**Files:** Source PRD_FINALIZED.md = 267 lines / 43,517 chars; output PRD_COMPLETED.md = 267 lines / 45,572 chars. Char delta **+2,055** (line count unchanged — all edits in-paragraph). 16 changed lines across 7 edits.

**Counts:** 6 ambiguity-pins, 1 mismatch-revision (7 total).

**Per-change list** (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.3 Pagination — insert — ambiguity — Pinned that out-of-range `limit`/`offset` are clamped (limit→[1,100], offset→≥0) rather than rejected, that non-integer values yield `ERR_INVALID_REQUEST`, and that `meta` echoes post-clamp values — `app.py:342-365` (`get_pagination`).
- §3.2 Census — revise — mismatch — Death cascade said only `IN_PAY`; impl also terminates `SUSPENDED` payments. Added "or `SUSPENDED`" (matches §3.8) — `app.py:839-842` (`record_death`).
- §3.3 Benefit bases — insert — ambiguity — Pinned the cash-balance accumulation algorithm: walk comp rows by `plan_year` asc, interest-credit the running balance first (×(1+rate)) then add the year's pay credit, one interest application per row, final balance rounded half-up — `app.py:507-528` (`calc_cash_balance`).
- §3.4 Lump-sum valuation — insert — ambiguity — Pinned `relative_value_pct` = 0.0 when the comparator present value is zero (division skipped) — `app.py:584-587` (`calc_lump_sum_apv`).
- §3.4 Election reopen — insert — ambiguity — Pinned exactly which fields reopen clears to null (the four computed benefit fields plus `submitted_by_user_id`) — `app.py:1246-1251` (`reopen_election`).
- §3.5 QDRO carve-outs — insert — ambiguity — Pinned base selection: the most recently created election carrying a computed `js_reduced_monthly_cents`; base treated as 0 (carves → 0) when no such election exists at qualification time — `app.py:1439-1457` (`_recompute_qdro_carves`).
- §3.6 Filing certification — insert — ambiguity — (a) Pinned `aftap_pct`=0.0 when `funding_target_cents`=0 at creation (division skipped); (b) pinned the certify check order: DRAFT (`ERR_INVALID_STATE`) → funding_target>0 (`ERR_INVALID_REQUEST`) → OCC version (`ERR_STALE_VERSION`) — `app.py:616-622` (`calc_aftap`), `app.py:998-1004` (`certify_filing`).

**Behaviors verified as already-pinned (no change):** dual gross-benefit formulas, J&S reduction factor + clamp, segment-factor age bands, vesting 3-to-7 schedule, credited-service floor/round-down/adjustment ordering, FAP consecutive-window + tie-break, PBGC premium cap-after-rate, supersede `>=` rule, posture thresholds + greatest-plan_year/created_at tie-break, all state-machine transitions, RBAC, validation precedence (§2.10), cascades, OCC, and the response envelope. Tests used only as auxiliary cross-reference, not as authority.
