# Worklog — task_1853_problem_loan_workout_special_assets

## Step 1: Create Task Directory — 2026-08-14T20:52:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1853_problem_loan_workout_special_assets/` and `workspace/` already existed; no index scan or new directory creation performed (concurrent pipeline runs in repo).

## Step 2: Generate Scaffold — 2026-08-14T21:16:00.000Z

All checks pass. Final state:

- `SCAFFOLD.yaml` — §1.0–§1.7 only (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`
- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (440 calls scanned)

## Completion Summary

**Counts**
- Entities: 12 (Borrower, Loan, WorkoutCase, ActionPlan, RestructureProposal, CollateralItem, CollateralAppraisal, ImpairmentAssessment, LegalReferral, ChargeOffEvent, RecoveryEvent, ExitStrategyDecision)
- State machines: 9 (Borrower, Loan, WorkoutCase, ActionPlan, RestructureProposal, CollateralItem, CollateralAppraisal, ImpairmentAssessment, LegalReferral)
- Calculations: 7 (liquidation_value, loss_given_default, cecl_reserve, tdr_dcf_reserve, recovery_allocation, forgiveness_cap_check, portfolio_classified_exposure)
- Validations: 10 (priorities 1–10 across auth/existence/state/business_safety/business_constraint/business_fiscal/business_temporal)
- Endpoints: 72 (nested action routes + flat single-resource and filtered-list GETs added for FK reverse-reachability)
- Errors: 46
- Roles: 8 (WorkoutOfficer, SpecialAssetsManager, CreditCommittee, AppraisalDesk, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin — all opaque identity)
- Concurrency rules: 3 OCC rules (plan-create, proposal-create, appraisal-create — each on a different parent entity)
- §1.8 difficulty-design instances: 18 (9 rules × 2, each with full structured test_recipe and pre-computed literal asserts)
- §1.9 corner-design instances: 35 total = 31 active recipes + 4 excluded_because stubs

**Notable design decisions**
- Archetype blend: compliance/audit primary + ledger-reconciliation secondary; segregation-of-duties role model (plan submitter ≠ approver, impairment finalizer ≠ case officer) enforced via X-User-ID equality.
- Harder-than-expert difficulty drivers: dual-variant reserves (CECL PD×LGD vs TDR DCF discounted at the ORIGINAL contractual rate — a regulatory subtlety that flips results: 10,000,000 vs 20,173,230 on identical inputs); dual-variant recovery allocation (CHRONOLOGICAL vs WATERFALL with a 10% costs tier, ceil-rounding trap producing 1,000,001 on a 10,000,001 recovery); cyclic negotiation state machine (UNDER_BORROWER_REVIEW → COUNTERED → RESUBMITTED loop with negotiation_round increments) plus ActionPlan reject→revise revert loop and APPROVED→SUPERSEDED supersede chain; depth-3 consummation cascade (proposal → cascaded forgiveness ChargeOffEvent → loan balances → LGD recompute) and depth-2 guarantor-settle cascade (settle → synthesized RecoveryEvent → allocation/LGD recompute); inclusive-vs-strict boundary pins (forgiveness cap == passes, statute deadline == clock fails, staleness 365 passes / 366 fails, cure 60 fails / 59 passes, nonaccrual at exactly 90).
- Two compensating invariants: principal-ledger conservation across charge-off + offsetting recovery (current + charged_off constant), and LGD + collateral cover == principal across appraisal supersede (no stale-value drift).
- All assertion numerics were executed in Python before writing (CECL 3,910,217; TDR DCF 20,173,230 vs 12,989,379 at concession rate; liquidation values 64,000,000 / 40,000,000 / 28,000,000; waterfall vs chrono bucket splits).
- Two corrections made during authoring: forgiveness-cap boundary setup recalibrated (20,000,000 charged off + 5,000,000 forgiveness == 25% cap exactly), and the WATERFALL-after-CHRONO current-principal assert fixed to 43,000,000 after replaying bucket math.
- Lint-driven fix: added 21 flat convenience GET routes (single-resource + filtered-list per FK child) so all 12 FKs satisfy check (f); `api_prefix` set to root (`""`) since the domain routes are multi-root (`/loans`, `/borrowers`, `/portfolio-report`).

Orchestrator verification: files on disk — SCAFFOLD.yaml 1764 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1336 lines, SCAFFOLD_CORNER_DESIGN.yaml 1372 lines; all YAML-parseable with correct top-level keys.

## Step 3: Copy Shared Files — 2026-08-14T21:18:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1853_problem_loan_workout_special_assets/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T21:33:00.000Z

All verification complete. Final summary:

## Deliverable

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1853_problem_loan_workout_special_assets/workspace/PRD.md`
**PRD line count:** 357 lines

**Section list:**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block, byte-identical to `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Resource Identity and Common Properties
  - 2.5 The Logical Clock
  - 2.6 Money, Basis Points, and Rounding Discipline
  - 2.7 Hierarchical and Flat Resource Retrieval
  - 2.8 Optimistic Concurrency Control
  - 2.9 Derived Balances and Cascading Recomputation
  - 2.10 Segregation of Duties
  - 2.11 Validation Priority Order
- 3. Business Logic & Workflows
  - 3.1 Onboarding Borrowers and Booking Loans
  - 3.2 Entering the Watchlist and Disciplining the Action Plan
  - 3.3 Negotiating Restructure Terms with the Borrower
  - 3.4 Consummation and Troubled-Debt Determination
  - 3.5 Collateral Valuation and Loss-Given-Default
  - 3.6 Impairment Measurement: CECL and Discounted Cash Flow
  - 3.7 Legal Referral and Guarantor Pursuit
  - 3.8 Charge-Offs, Recoveries, and the Allocation Ladder
  - 3.9 Exit Decisions, Case Closure, and Portfolio Reporting
- 4. Endpoint Definitions (72-row table, 4 columns, matches scaffold's 72 endpoints)
- 5. Error Code Catalogue (46-row table, 2 columns, matches scaffold's 46 errors; document ends here, no audit footer)

## Self-check results

**Contract 1 — Field-Name Coverage (two passes run; pass 1 caught `ACCEPTED`/`RESUBMITTED` as bare prose words, both repaired to exact backticked state tokens; pass 2 clean):**
```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body: 5 required, 5 present, 0 missing
- endpoints[].query_params: 8 required, 8 present, 0 missing
- (also verified: 4 computed-report/clock output names, 46 error IDs, 66 enum/state values — all present)
Status: PASS
```

**Contract 2 — Rule Coverage (manual walk of every scaffold rule table against the prose):**
```
Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose (§2.11 ordered layers with masking semantics), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_case_version/expected_collateral_version + ERR_STALE_VERSION 412 all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed (from/to states, preconditions paired with error IDs, side effects), 0 missing
- calculations[]: 7 checked, 7 fully expressed (liquidation value, LGD, CECL, TDR_DCF, recovery allocation both variants, forgiveness cap with inclusive boundary, portfolio gross/net) with pinned rounding orders, 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 72 checked, 72 expressed; all 4 validation applies_to scopes enumerated, 0 missing
- entities[].fields[] structured content: 72 checked, 72 reconstructible from prose (defaults, initial values, ranges stated), 0 missing
- sibling-branch symmetry: 6 groups checked (CHRONOLOGICAL/WATERFALL, CECL/TDR_DCF, LEGAL vs NEGOTIATION exit paths, withdraw from 4 states, appraisal accept/reject, gross vs net report), 6 with equal prose density, 0 asymmetric
Status: PASS
```

**Contract 3 — §3 Path Purity:**
```
Path purity check (§3 only):
- backtick tokens scanned: 433
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional checklist results:** zero fuzzy/approximating words (grep-verified); zero leaked operator syntax outside backticks (scan-verified); no pseudocode — all formulas rendered as precise natural language passing the reconstruction test; §4 table has exactly 4 columns; §5 table has exactly 2 columns with no trigger conditions; scattering verified (e.g., appraisal inputs split across §2.8/§3.5, plan inputs across §2.8/§2.11/§3.2, recovery inputs across §3.7/§3.8); constants embedded as business language (ninety days, one year/365 days, one quarter of original principal, ten percent costs tier). The forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T22:02:00.000Z

All artifacts complete and validated. Final summary:

## Generation Summary — task_1853_problem_loan_workout_special_assets

### Files generated

**`test_helpers/`** (9 files):
- `types.py` — 11 status enums + role enum; 10 entity TypedDicts with `common_fields: true` (id/created_at/updated_at/version) and 3 append-only ledger TypedDicts (ChargeOffEvent, RecoveryEvent, ExitStrategyDecision) that omit `updated_at`/`version` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (52 methods)
- `api_errors.py` — `ApiErrorId` enum (46 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (ledger assertions forbid `updated_at`/`version`) + loan-ledger and case invariant checkers
- `factories.py` — payload factories, input fields only
- `constants.py` — domain thresholds (NONACCRUAL_DPD=90, STALE_APPRAISAL_DAYS=365, FORGIVENESS_CAP_BPS=2500, CURE_DPD_LIMIT=60, etc.)
- `test_users.py` — shared header constants + per-role `make_*_headers(user_id)` builders for all 8 opaque roles
- `fixtures.py` — composite setup: `make_borrower_with_loan`, `open_workout_case`, `setup_case_in_action_plan`, `setup_case_in_negotiation`, `setup_case_in_impairment_review` (concession toggle → TDR_CONFIRMED/TDR_REJECTED), `setup_case_in_legal`, `make_accepted_appraisal`, `set_clock`; all identity-threaded
- `__init__.py` — barrel export

**`test_suite/`** (conftest + 15 test files): `test_01_reserve_and_allocation_variants.py`, `test_02_negotiation_cycles_and_plan_revision.py`, `test_03_transitive_cascades.py`, `test_04_validation_priority_pairs.py`, `test_05_boundary_precision.py`, `test_06_cross_entity_gates.py`, `test_07_temporal_windows.py`, `test_08_compensating_invariants.py`, `test_09_entity_basics.py`, `test_10_state_machine_corners.py`, `test_11_calculation_corners.py`, `test_12_validation_corners.py`, `test_13_endpoint_corners.py`, `test_14_error_corners.py`, `test_15_rbac_occ_and_consistency.py`

### Test counts
- **Queue A (Difficulty): 36 tests** — 18/18 instances, exactly 2 tests each
- **Queue B (Corner): 31 tests** — 31/31 non-stub instances, 1 test each
- Total: **67 tests**, all collected by pytest successfully

### Skipped instances
None. All 18 difficulty and 31 non-stub corner instances passed the PRD-first two-condition filter. The 4 `excluded_because:` stubs were not translated; all 4 `difficulty_instance` cross-references verified to resolve.

### Deviations / adjudications (PRD-first)
1. **`recovery_waterfall_costs_tier_nested_rounding`**: the design's pre-computed literals (costs tier 1,000,001 via `ceil`, current→0) contradict the PRD, which pins the costs-tier rounding as "ten percent of the recovery amount, with that ten-percent figure rounded half up to whole cents" (§3.8, §2.6). 10% of 10,000,001 = 1,000,000.1 → half-up = 1,000,000, leaving current_principal 1,000,000 (not 0). I asserted the PRD-derived values; the instance's tested claim (costs-tier-first ordering, single rounding on the total) is preserved. The second test for this instance uses amount 10,000,005 where half-up (1,000,001) genuinely diverges from truncation, pinning the rounding rule.
2. **`_setup_active_guarantor_referral`** corrected from the recipe order: the referral is created directly from NEGOTIATION (a second referral from LEGAL would hit ERR_CASE_NOT_REFERRABLE), matching the design's actual `setup_api_calls` chain.

### Stage-check results
- **Stage 1**: test_helpers complete; all modules compile and import cleanly (110 exported names)
- **Stage 2 collection**: `pytest --collect-only` → 67 tests, 0 errors
- **Coverage audit**: every difficulty instance has ≥2 tagged tests; every non-stub corner instance has ≥1; no stub tags used; no unresolved tags
- **C4 tag audit**: every test's docstring ends with exactly one `Design:` line resolving to a real yaml `name:`
- **C1 verbatim sweep**: all quoted PRD citations survive normalized literal grep of PRD.md (0 failures after fixing 5: two C3 ellipsis-abbreviations in test_04 rewritten as full sentences; three C2 endpoint-table citations in test_15 replaced with rule-bearing §2.1 role-description prose)
- **No-skip sweep**: zero `pytest.mark.skip`/`skipif`/`xfail`/`pytest.skip` occurrences
- **Scaffold-leakage sweep**: zero "scaffold"/table-section references in generated code comments/docstrings
- **Two-reader fixes applied**: case_officer_id header consistency in `test_10` second-case attempt (only the loan-state rule can fire) and `test_11` L3 case creation; immediate-consistency assertion tightened to the PRD-pinned version increment

## Step 6: Generate Implementation — 2026-08-14T22:05:00.000Z

The implementation is complete and verified. Final summary:

## File list

All under `/home/ubuntu/github/CodingPRD/tasks/task_1853_problem_loan_workout_special_assets/workspace/implementation/`:

- `start.sh` — executable launcher: `cd` to script dir, guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/fallback error handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — empty module-level `STORE` dicts (no seeding), logical clock (boots at exactly `2026-08-01T00:00:00Z`, never falls back to wall clock), UUID minting, `now_iso()` (wall UTC, 3 fractional digits) for `created_at`/`updated_at`/`meta`, `fmt_clock()` for `booked_at`/`decided_at`/`current_utc`, insertion sequence for deterministic `created_at`-ASC ordering, `stamp()`/`touch()` (version starts at 1, +1 per mutation)
- `errors.py` — all error-ID constants incl. `ERR_IMPAIRMENT_NOT_DRAFT`/`ERR_CASE_NOT_IMPAIRABLE` (named in PRD §3.6 though absent from §5's table)
- `response.py` — exact envelope: `meta.api_request_id` (`req_` + 20 alnum), `meta.api_request_timestamp`, `response_type` object/array/error, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` (default 10, clamp [1,100], offset ≥ 0); report response carries the same pagination meta
- `auth.py` — `X-User-ID`/`X-User-Role` extraction; the 8 exact role names; `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) / `ERR_INSUFFICIENT_PERMISSIONS` (403)
- `validate.py` — strict payload validation: unknown fields, missing required fields, wrong types (bool rejected as int), enum membership, int ranges, ISO-8601 parsing → `ERR_INVALID_REQUEST` (400)
- `services.py` — calculations, cascades, per-entity serializers (explicit field lists; ledger events correctly omit `updated_at`/`version`; case exposes `version_anchor` mirroring `version`)
- `routes/core.py` — clock set, borrowers (tax_id uniqueness → 422), loans (loan_number uniqueness), aging-refresh, workout-case create/get/list
- `routes/plans.py` — action-plan draft/submit/approve/reject/revise
- `routes/proposals.py` — proposal draft/submit/counter/resubmit/escalate/committee-approve/committee-reject/consummate/withdraw
- `routes/collateral.py` — pledge/list/get/release + appraisal order/submit/accept/reject
- `routes/impairments.py` — CECL/TDR_DCF create + finalize
- `routes/legal.py` — referral create/accept/settle/dismiss
- `routes/ledger.py` — charge-offs, recoveries
- `routes/exits.py` — exit-decision, close, `/portfolio-report`
- `routes/flat.py` — all 20 flat convenience GET routes with per-scaffold role lists and FK filters

## Calculation chains

- **Liquidation value**: `(appraised * (10000 - discount_bps) + 5000) // 10000` — integer multiply-first, divide-once, round-half-up-once.
- **LGD**: `max(0, current_principal − Σ current_liquidation_value_cents over items in {PLEDGED, UNDER_REVALUATION})`; recomputed on appraisal accept, charge-off, principal recovery, liquidation, release; touches the loan's non-CLOSED case (falls back to latest case), bumping version only when the value moves.
- **CECL reserve**: single chain `(current * PD * LGD + 5·10⁷) // 10⁸` (exact half-up).
- **TDR DCF reserve**: `Decimal` (prec 60) monthly rate `contractual_rate_bps/10000/12` (original rate, never concession), per-period PVs summed unrounded in ascending period order, one half-up rounding after summation, reserve `max(0, current − pv)`; empty flows → `ERR_EMPTY_CASH_FLOWS`, duplicate `period_index` → `ERR_DUPLICATE_CASH_FLOW_PERIOD`.
- **Recovery allocation**: CHRONOLOGICAL = min(amount, charged_off) then min(remainder, current), excess → `unapplied_cash_cents`; WATERFALL = costs tier `min(amount, round_half_up(amount/10))` first, then charged-off, then current, excess → unapplied. Loan buckets debited; guarantor settle books a linked CHRONOLOGICAL recovery.
- **Forgiveness cap**: `floor(original * 2500 / 10000)`, reject iff `charged_off + forgiveness > cap` (equal allowed) at committee-approve.
- **Portfolio report**: loans with status in {WATCHLIST, WORKOUT, FORECLOSURE} ordered `created_at` ASC (seq tiebreak); per-loan gross = current + charged_off, net = gross − open case's active `impairment_reserve_cents`; totals aggregated at full precision over the whole inclusion set while `loan_rows` is paginated; loans with no open case contribute 0.
- **Misc**: `staleness_days` = `(clock − effective_date).days`, computed at submit and re-evaluated at accept (>365 → `ERR_APPRAISAL_STALE`); `is_partial` = amount < current at booking; TDR flag = (rate < contract OR forgiveness > 0) AND (rating_at_entry ≥ 6 OR dpd ≥ 60); exit argmax with ties → DEED_IN_LIEU, non-argmax without non-empty `override_justification` → `ERR_BUSINESS_CONSTRAINT`; nonaccrual = `dpd ≥ 90 OR any case LEGAL`, forced true on referral create and on FORECLOSURE/DEED_IN_LIEU exit.

## State machine wiring

Full transition sets for WorkoutCase (WATCHLIST→ACTION_PLAN→NEGOTIATION⇄IMPAIRMENT_REVIEW→LEGAL→RESOLUTION→CLOSED, incl. NEGOTIATION→RESOLUTION with consummated-proposal gate and path restriction), Loan (PERFORMING→WATCHLIST→WORKOUT→FORECLOSURE→RESOLVED, PERFORMING regain only via RETURN_TO_PERFORMING close), ActionPlan (incl. REJECTED→DRAFT revise, APPROVED→SUPERSEDED on successor approval, `ERR_ACTIVE_PLAN_EXISTS` otherwise, first-approval cascade), RestructureProposal (auto SUBMITTED→UNDER_BORROWER_REVIEW, COUNTERED→RESUBMITTED cycle with `negotiation_round` += 1, withdrawable states), CollateralItem (PLEDGED⇄UNDER_REVALUATION, LIQUIDATED via recovery with `collateral_id` in LEGAL/RESOLUTION, RELEASED with encumbrance check), CollateralAppraisal, ImpairmentAssessment (finalize supersedes prior FINALIZED, single `is_active`), LegalReferral (statute re-check at accept), Borrower auto-EXITED when all cases on all its loans close. Validation priority enforced per endpoint: auth → role → left-to-right path/body existence (404) → state (409 specifics) → OCC `expected_case_version`/`expected_collateral_version` (412) → segregation of duties (403; case-officer equality on case create/plan draft/submit, approver ≠ officer, finalizer ≠ officer; appraisal accept is peer-exempt) → regulatory timing → structural (422) → fiscal caps → temporal.

## Smoke checks run

Booted via `bash start.sh` on a fresh process three times; confirmed empty state on boot (`/loans`, `/workout-cases` return empty arrays) and HTTP-ready within ~2s. Ran three urllib-based suites covering ~110 assertions — all passing (two initial "failures" were bugs in my test scripts' own arithmetic, corrected and verified against PRD math): full arc watchlist→plan→proposal counter cycle→committee→consummation (TDR + forgiveness charge-off cascade, verified balances 10M→9M/1M), appraisal revaluation (4.8M liquidation from 6M at 2000bps), CECL reserve 180,000 exactly, TDR_DCF floor-at-zero, supersede chain, guarantor pursuit with demand ceilings and settle-recovery cascade (1M excess → unapplied), WATERFALL 10%-of-105 half-up rounding (charged_off 100→6), charge-off fiscal limits, statute expiry, stale appraisal, encumbered/unencumbered release, RTP cure check, override/argmax/tie outcomes, portfolio report totals and pagination, RBAC denials, and malformed-payload 400s. Calculation functions additionally unit-checked in-process against `Decimal` references.

## Step 7: Run Tests and Iterate — 2026-08-14T22:35:00.000Z

All 8 rounds pass cleanly: 66/66 in every round, zero flakiness. The iteration loop is complete.

## Summary

**Iterations run:** 2 (sweep 1: 50/67 passed, 17 deterministic failures identical across all 8 rounds; fixes applied; sweep 2: 66/66 × 8 rounds, clean).

**Tests deleted (1):**
- `test_tdr_method_gate_masks_fiscal_range_complaint` (test_suite/test_04_validation_priority_pairs.py) — unique-derivability collapse. The scenario required creating a TDR_DCF impairment with out-of-range `probability_of_default_bps=15000` and surviving to finalize, but PRD §3.6 attaches the PD 1–10000 range to *CECL inputs* only, and §2.11 layer 9 enumerates only the forgiveness ceiling, charge-off amounts, and positive recovery/appraisal amounts — no PD-range fiscal rule or error_id exists anywhere in PRD. A PRD-faithful implementer may reject the payload at creation (the reference implementation does, with ERR_INVALID_REQUEST), making the test's setup non-constructible. The TDR method gate it targeted remains covered by `test_tdr_method_gate_fires_regardless_of_assessment_inputs` and `test_tdr_dcf_finalize_blocked_when_case_tdr_rejected`. Scaffold driver: `Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_committee_conflict` — a priority-8×9 pair PRD never renders as a constructible conflict.

**Fixes to `test_helpers/` (1):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1853_problem_loan_workout_special_assets/test_helpers/fixtures.py` — `setup_case_in_impairment_review`: added the missing `plan_overrides` parameter and forwarded it to `setup_case_in_negotiation`. One fixture-signature bug masqueraded as 12 independent failures (the triage-hint pattern).

**Fixes to `test_suite/` (4 files, 5 tests):**
- `test_08_compensating_invariants.py` — `test_chargeoff_then_compensating_recovery_conserves_principal_total`: post-recovery ledger-total assertion corrected 50,000,000 → 38,000,000; PRD §3.8 subtracts recovery portions from both principal buckets, so a recovery retires debt (the old assertion contradicted both the PRD and the test's own preceding lines).
- `test_15_rbac_occ_and_consistency.py` — `test_occ_stale_case_version_on_plan_create`: added `supersedes_plan_id` to the second/third plan payloads per PRD §3.2 ("for every plan after the first — the supersedes_plan_id of the plan it replaces"); the implementation's 400 on the missing field is PRD-grounded.
- `test_15_rbac_occ_and_consistency.py` — `test_occ_stale_collateral_version_on_appraisal_create`: walk the item back to PLEDGED (submit + reject the first appraisal, §3.5) before re-ordering with the stale version, so §2.11's state layer (4) passes and the OCC layer (5) is what fires.
- `test_05_boundary_precision.py` — both statute-deadline tests: rewrote the shared fixture to (a) book a charge-off so LGD (39M) clears the §3.7 demand ceilings for the 5M demand, (b) create one referral per case (creation moves the case to LEGAL, so a second referral on the same case is ERR_CASE_NOT_REFERRABLE), and (c) use a creation-valid deadline strictly after the default clock, then advance the logical clock to the boundary — exercising the PRD-named acceptance-time re-check (`ERR_STATUTE_EXPIRED` at exact equality; ACTIVE one second past). The old setup relied on creating a referral with deadline ≤ clock, which §3.7's creation-time "must lie strictly after" forbids.

**Fixes to `implementation/`:** none — every failure traced to test-artifact bugs; the implementation was PRD-faithful in all 17 cases (validation priority order, OCC layering, demand ceilings, statute re-check, and the §3.2 supersedes payload contract all verified against PRD prose before each test-side fix).

## Step 8: Finalize PRD — 2026-08-14T22:50:00.000Z

All edits are in place. The diff shows exactly 3 lines revised in place, nothing else. Here is the summary.

## Summary

**Line counts / delta:** PRD.md 357 lines → PRD_FINALIZED.md 357 lines (0.0% line delta; 3 lines revised in place, character-level changes only).

**Changes (all trace to `<step_7_diff>` items):**

- **§3.6 — revise** — Pinned impairment PD/LGD payload discipline: both fields required on `CECL` (missing/wrongly-typed/out-of-range → `ERR_INVALID_REQUEST` 400 at creation); on `TDR_DCF` both are optional, default to zero, must be integers in 0–10000 when supplied (violations likewise `ERR_INVALID_REQUEST` at creation), are stored and returned, but are never read by the DCF computation — `workspace/implementation/routes/impairments.py:89-105,116-117`; `workspace/implementation/services.py:41-52,405-419`. (Trace: deleted test `test_tdr_method_gate_masks_fiscal_range_complaint` — PRD attached the PD range to CECL inputs only and named no error_id anywhere; the impl rejects out-of-range PD on a TDR_DCF create with `ERR_INVALID_REQUEST`, making the old test's setup non-constructible.)
- **§3.7 — revise** — Named the creation-time statute-deadline violation error: "a deadline at or before the clock is rejected with `ERR_INVALID_TEMPORAL` (HTTP 422)" — `workspace/implementation/routes/legal.py:96-100`. (Trace: test_05 statute-deadline fixture rewrite, which had to stop relying on creating referrals with deadline ≤ clock.)
- **§2.11 layer 10 — revise** — Extended the `ERR_INVALID_TEMPORAL` enumeration to include "a referral's statute deadline must lie strictly in the future at creation", keeping the priority catalogue consistent with the §3.7 pin — `workspace/implementation/routes/legal.py:95-100` (plus the two pre-existing sites: `plans.py:82-86`, `collateral.py:168-172`).

**Step-7 items with no PRD edit (PRD already determines behavior, prose kept verbatim):** the `test_helpers/fixtures.py` `plan_overrides` fix (pure test-helper bug); test_08's 50M→38M assertion (§3.8 already pins subtraction from both principal buckets; impl `services.py:239-241` matches); test_15's plan-payload fix (§3.2 already requires `supersedes_plan_id` after the first plan and §2.11 grounds the 400; Step 7 itself judged it PRD-grounded); test_15's appraisal-OCC walk (§2.11 already orders state layer 4 before OCC layer 5; not-PLEDGED resolves via the layer-4 `ERR_INVALID_STATE` catch-all, impl `collateral.py:155-158`); test_05's charge-off/one-referral-per-case fixture changes (§3.7 already pins both demand ceilings and the `NEGOTIATION`/`IMPAIRMENT_REVIEW`-only creation window moving the case to `LEGAL`).

**Per-edit pre-edit search log:**

1. **§3.6 edit** — (a) Subject: impairment PD/LGD payload fields (presence, defaults, ranges, violation error, computational use). (b) Enumerated/read: `impairments.py` `create_impairment` (78–124, the only validation site), `finalize_impairment` (139–187: CECL uses PD/LGD, TDR path ignores them, no re-validation); `services.py` `cecl_reserve` (35–38), `tdr_dcf_reserve` (41–52 — signature takes only principal/rate/cash flows), `impairment_out` (405–419 — both fields always serialized); `test_helpers/factories.py:125-133` (TDR factory supplies in-range PD/LGD — must remain accepted); remaining `test_04` test (creates TDR_DCF with PD=2000/LGD=3000). (c) Adjustment: avoided the word "malformed" (§2.11's final paragraph enumerates only unknown fields/wrong types/unparsable values) and used "rejected at creation with `ERR_INVALID_REQUEST` (HTTP 400)" instead, so §2.11 stays verbatim and no cross-section tension is introduced; scoped the TDR_DCF PD floor to 0 (impl `minimum=0`), distinct from CECL's 1.
2. **§3.7 edit** — (a) Subject: `statute_deadline` temporal validation and its error code at creation vs acceptance. (b) Enumerated/read: `legal.py:61-63` (parse), `legal.py:96-100` (creation: `statute_dt <= logical_now()` → `ERR_INVALID_TEMPORAL` 422), `legal.py:140-143` (acceptance re-check → `ERR_STATUTE_EXPIRED`), `services.py:429` (serialization); confirmed no other statute touchpoints via grep. (c) Adjustment: phrased as "at or before the clock" to mirror the impl's `<=` exactly, and attached the error only to the creation sentence so the untouched acceptance paragraph (`ERR_STATUTE_EXPIRED` at equality) is not re-scoped.
3. **§2.11 layer-10 edit** — (a) Subject: exhaustiveness of the `ERR_INVALID_TEMPORAL` enumeration. (b) Enumerated/read: all three `ERR_INVALID_TEMPORAL` raise sites — `plans.py:82-86` (target date strictly-after), `legal.py:96-100` (statute creation strictly-after), `collateral.py:168-172` (effective date not-future); cross-checked layer 7 (acceptance-time statute check) and the §3.2/§3.5 narratives that already name the other two cases. (c) Adjustment: scoped the added clause with "at creation" so it cannot be read as colliding with layer 7's acceptance-time `ERR_STATUTE_EXPIRED` companion.

One deliberate non-pin: the impl's 400-priority placement for a missing `supersedes_plan_id` on later plans (raised after OCC/SoD at `plans.py:77-80`, not at parse time) and its first-plan omission default (`""`) were left under-determined — pinning them risked mis-describing the first-plan path and the validation-priority interplay, and Step 7 judged the tested behavior PRD-grounded.

## Step 9: Complete PRD — 2026-08-14T22:58:00.000Z

All edits are complete and verified. Here is the final report.

## Summary

**Files** (both at `/home/ubuntu/github/CodingPRD/tasks/task_1853_problem_loan_workout_special_assets/workspace/`):
- Source: `PRD_FINALIZED.md` — 357 lines, 58,542 chars
- Produced: `PRD_COMPLETED.md` — 357 lines, 65,685 chars (char-delta **+7,143**; 29 paragraphs revised in place, zero new sections/paragraphs)

**Counts**: 38 edit hunks over 29 paragraphs → **32 ambiguity-pins**, **6 mismatch-revisions** (two hunks were mixed pin+revise and are counted by their dominant character).

### Mismatch revisions
- §2.1 — revise — mismatch — appraisal `appraiser_id` is stored from the order payload verbatim, never compared to the desk user's `X-User-ID` — `implementation/routes/collateral.py:149,180`
- §2.7 — revise — mismatch — flat `/workout-cases` list filters by `loan_id` only; the PRD's `case_id` filter for workout cases removed — `implementation/routes/flat.py:60-67`
- §2.8 — revise — mismatch — drafting a plan does not itself supersede an approved predecessor; the flip to `SUPERSEDED` happens at the new plan's approval — `implementation/routes/plans.py:144-159`
- §3.2 — revise — mismatch — drafting paragraph reworded likewise ("naming an approved predecessor that will flip … at the new plan's approval — not at drafting") — `implementation/routes/plans.py:99-101,154-159`
- §3.5 — revise — mismatch — "the ordering desk user's own `X-User-ID` as `appraiser_id`" → payload-supplied `appraiser_id` recorded verbatim — `implementation/routes/collateral.py:149,180`
- §3.6 — revise — mismatch — assessments may be drafted in any case status (not only "while a case sits in `IMPAIRMENT_REVIEW`"); the `ERR_CASE_NOT_IMPAIRABLE` gate applies only at finalization — `implementation/routes/impairments.py:79-124,145-149`

### Ambiguity pins
- §2.3 — insert — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` 400; out-of-range values clamped (`limit`→[1,100], `offset`→≥0); unknown query params ignored; `has_more` = `offset+limit < total_count`; millisecond `created_at` ties break by insertion order — `implementation/response.py:57-87`, `implementation/services.py:145-146`
- §2.5 — insert — `to_iso8601` without timezone read as UTC, no monotonicity enforced; logical-clock stamps render whole seconds on second boundaries else three fractional digits; `created_at`/`updated_at`/`api_request_timestamp` come from the wall clock — `implementation/db.py:47-57,78-98`
- §2.7 — insert — undefined route or unsupported method → `ERR_NOT_FOUND` 404 — `implementation/app.py:23-29`
- §2.11 — insert — missing required fields and out-of-set enum values are `ERR_INVALID_REQUEST` 400; payload-shape screening runs after path resolution, before body-reference/business layers, except guarantor-settlement where the `ACTIVE` state check precedes payload parsing — `implementation/validate.py:10-66`, `implementation/routes/legal.py:156-161`
- §3.1 — insert — duplicate `tax_id` → `ERR_BUSINESS_CONSTRAINT` 422; out-of-range `internal_risk_rating` and negative `guarantor_net_worth_cents` → `ERR_INVALID_REQUEST` 400 — `implementation/routes/core.py:55-64`
- §3.1 — insert — duplicate `loan_number` → `ERR_BUSINESS_CONSTRAINT` 422; `original_principal_cents`/`contractual_rate_bps`/`days_past_due` must be non-negative integers else 400 — `implementation/routes/core.py:112-122`
- §3.1 — insert — aging-refresh `days_past_due` non-negative integer else 400; answers with the updated loan — `implementation/routes/core.py:159-173`
- §3.2 — insert — `case_officer_id` ≠ acting `X-User-ID` → `ERR_SEGREGATION_OF_DUTIES` 403; `risk_rating_at_entry` out-of-range → 400 — `implementation/routes/core.py:189-204`
- §3.2 — insert — `milestone_count` < 1 → 400; later plans must carry `supersedes_plan_id` (omission → 400) resolving to a plan on the same case (else 404) — `implementation/routes/plans.py:57-80`
- §3.2 — insert — the `WATCHLIST` gate applies only to the very first plan; later plans have no case-status precondition — `implementation/routes/plans.py:67-69`
- §3.2 — insert — plan rejection is not segregation-guarded (any `SpecialAssetsManager`, even one matching `case_officer_id`); any `WorkoutOfficer` may revise — `implementation/routes/plans.py:174-196`
- §3.3 — insert — no proposal endpoint applies a segregation-of-duties comparison; any `WorkoutOfficer` may draft/counter/resubmit/escalate/consummate/withdraw — `implementation/routes/proposals.py:55-270`
- §3.3 — insert — each of the four term fields must be an integer ≥ 0 else 400 — `implementation/routes/proposals.py:62`
- §3.3 — insert — a fresh proposal's `tdr_flag` is false until consummation computes it — `implementation/routes/proposals.py:83`
- §3.3 — insert — counter payload must carry all four term fields (missing → 400) — `implementation/routes/proposals.py:126-127`
- §3.3 — insert — escalation from any state other than `UNDER_BORROWER_REVIEW` → `ERR_PROPOSAL_NOT_UNDER_REVIEW` 409 — `implementation/routes/proposals.py:168-172`
- §3.3 — insert — committee rejection likewise requires `COMMITTEE_REVIEW` else `ERR_PROPOSAL_NOT_COMMITTEE_REVIEW` — `implementation/routes/proposals.py:209-216`
- §3.5 — insert — `liquidation_discount_bps` outside 0–9000 → 400 — `implementation/routes/collateral.py:78-80`
- §3.5 — insert — ordering an appraisal on a non-`PLEDGED` item → `ERR_INVALID_STATE` 409 — `implementation/routes/collateral.py:154-158`
- §3.5 — insert — `staleness_days` is null until submission, a whole-day count, and is re-derived and re-stored at acceptance — `implementation/routes/collateral.py:59-61,181,209,225-231`
- §3.5 — insert — LGD recomputation targets the loan's most recently created non-`CLOSED` case (or the most recent case when all are `CLOSED`; no-op with no case) and touches the case's `updated_at`/`version` only when the value changes — `implementation/services.py:153-179`
- §3.5 — insert — release encumbrance: unencumbered iff principal is zero, or the loan has ≥1 case and all cases are `CLOSED`; a loan with no case fails the second branch — `implementation/routes/collateral.py:116-127`
- §3.6 — insert — omitted `expected_cash_flows` stored as empty array; CECL may carry it (stored, unread); `computed_reserve_cents` null until finalization — `implementation/routes/impairments.py:49,106,119`
- §3.7 — insert — `demand_amount_cents` required non-negative on every referral kind (else 400); the two ceilings apply only to guarantor pursuits; missing guarantor name / missing rationale → `ERR_BUSINESS_CONSTRAINT` 422 — `implementation/routes/legal.py:60,73-94`
- §3.7 — insert — guarantor settlement requires `settled_amount_cents` > 0 else `ERR_FISCAL_LIMIT`; settling other kinds ignores the body and books no recovery — `implementation/routes/legal.py:158-170`
- §3.8 — insert — charge-off booking has no case-state precondition; charge-off event exposes exactly `id, case_id, amount_cents, reason_code, booked_at, is_partial, created_at` — `implementation/routes/ledger.py:55-70`, `implementation/services.py:438-447`
- §3.8 — insert — liquidation requires `collateral_id` in the payload resolving to a `PLEDGED` item on the same loan (`ERR_NOT_FOUND` / `ERR_COLLATERAL_NOT_PLEDGED`); other sources ignore `collateral_id` and carry no case-state gate; recovery event exposes exactly `id, case_id, amount_cents, recovery_source, allocation_mode, booked_at, created_at` with the collateral reference not retained — `implementation/routes/ledger.py:100-131`, `implementation/services.py:450-459`
- §3.9 — insert — `override_justification` defaults to empty string; exit decision exposes exactly `id, case_id, chosen_path, npv_foreclosure_cents, npv_deed_in_lieu_cents, decision_rule_outcome, override_justification, decided_at, created_at` — `implementation/routes/exits.py:56-58`, `implementation/services.py:462-473`
- §3.9 — insert — for `NOTE_SALE`/`RETURN_TO_PERFORMING` the loan's status is untouched at decision time and `nonaccrual` is re-evaluated under the §3.1 rule — `implementation/routes/exits.py:129-134`
- §3.9 — insert — report: `as_of` validated as string but never filters; aggregates computed over the full included set while pagination windows only `loan_rows` (`total_count` = included loans); response is `response_type` "object" still carrying the four pagination fields; row shape pinned — `implementation/routes/exits.py:197-250`

No behavior was invented; every pin traces to a specific implementation line. Calculations (liquidation value, CECL, TDR DCF, forgiveness cap, both allocation ladders), the validation-priority layers, RBAC tables, and state-machine transitions in the PRD were already exactly aligned with the implementation and were left untouched.
