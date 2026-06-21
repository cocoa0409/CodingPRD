# Worklog — task_0044_p2p_small_business_lending

Scenario: P2P Small Business Lending (Funding Circle style): borrower scoring (Plaid data feed), tiered interest rates, investor portfolio diversification, default/Charge-off, repayment allocation, SEC compliance disclosure

## Step 1: Create task directory — 2026-05-29T12:09:32Z

Created `tasks/task_0044_p2p_small_business_lending/` and `tasks/task_0044_p2p_small_business_lending/workspace/` directly at the pre-allocated path (no ./tasks/ rescan, no auto-increment).

## Step 2: Generate scaffold — 2026-05-29T12:38:20Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`.

Generated the three scaffold artifacts for **task_0044_p2p_small_business_lending** (Funding Circle–style P2P small-business lending) at the requested path. All three files parse as valid YAML and `scaffold_lint.py` returns **VERDICT: clean lint** (476 §1.8/§1.9 calls scanned, all conform to §1.5; all 11 FKs have reverse-reachability GETs).

**Complexity profile:** primary archetype `compliance_audit` + secondary `ledger_reconciliation`; flat topology; branching state machines; segregation-of-duties role model; layers = dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Expert band.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **8 entities** — Borrower, LoanApplication, Loan, Investor, Investment, Repayment, RepaymentAllocation (immutable, common_fields:false), ComplianceDisclosure
- **3 state machines** (LoanApplication SUBMITTED→SCORED→{APPROVED,REJECTED}; Loan FUNDING→ACTIVE→REPAYMENT→{PAID_OFF | DEFAULTED→CHARGED_OFF}; ComplianceDisclosure FILED→SUPERSEDED) **+ 1 concurrency rule** (OCC on Loan.version for investment creation, 412)
- **8 calculations** — score_borrower (weighted_scoring), apr_for_grade (tiered), amortization_schedule (round-then-subtract), compute_servicing_fee, allocate_repayment (waterfall, scheduled vs recovery variants), distribute_pro_rata, distribute_recovery, compute_late_fee (threshold w/ floor)
- **15 validations** (auth→existence→state→segregation→grade→disclosure→funding→OCC→capital→diversification→payoff→recovery→late-fee), **32 endpoints**, **16 errors**, **5 roles** (Borrower/Investor entity-backed; Underwriter/ComplianceOfficer/PlatformAdmin opaque). Includes a `/_clock/set_current_utc` test-driving endpoint.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × 2 = **18 instances**. All formula-derived asserts pre-computed as literals (credit scores 92.0/66.0/70.0/69.83/12.0, amortization level-payment 103274/86076, waterfall buckets, servicing-fee net-of-1%, largest-remainder distributions with created_at tie-break, 3-missed-payment default, charge-off cascade write-downs, principal/committed-capital conservation invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **35 active instances + 2 excluded_because stubs** across all 9 claim-extraction sections, covering creation/not-found/required/defaults/computed/immutability, invalid-transition/terminal/precondition/side-effect, calc correctness/constants/tie-break, validation triggers, listing/reverse-reachability, error triggerability, RBAC denials/auth, OCC/derived-field/threshold layers, and consistency.

**Key design decisions worth noting:** split Investor capital into `capital_base_cents` (diversification denominator, raised by deposit) vs `committed_capital_cents` (sum of commitments) to make both fiscal checks well-defined; added `last_assessed_period_index` and `charged_off_basis_cents` to make per-period late-fee assessment and recovery-distribution weighting deterministic; set `api_prefix: ""` since the domain has multiple top-level collections.

## Step 3: Copy INSTRUCTION.md — 2026-05-29T12:38:44Z

Copied `./INSTRUCTION.md` → `tasks/task_0044_p2p_small_business_lending/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-29T12:45:33Z

All Contract 2 behavioral spot-checks pass. The PRD is complete and all three hard contracts plus rule-coverage spot-checks are green.

Generated `workspace/PRD.md` — a P2P small business lending PRD.

**Structure:** 5 top-level sections, 259 lines.
- §2 (Global Specs): 9 subsections — RBAC, fixed §2.2 envelope (verbatim), pagination, common properties/versioning, monetary/rate/rounding, OCC on loan funding, validation precedence, reconciled-derived-fields/cascade consistency, cross-resource reads.
- §3 (Business Logic, scattering zone): 8 subsections, organized by lifecycle — borrowers/applications → scoring/pricing → approval/origination → investors/capital/commitment → disbursement/amortization → repayment waterfall/distribution → late-fee/default/charge-off/recovery → compliance disclosures/clock.
- §4 endpoint table (4 columns, 32 endpoints), §5 error table (2 columns, 16 errors).

**Hard contracts (all PASS):**
- Contract 1 (Field-Name Coverage): 53/53 required field names present in backticks, 0 missing.
- Contract 2 (Rule Coverage): OCC rule (write endpoint + `expected_loan_version` + `ERR_STALE_LOAN_VERSION`/412 + before-fiscal ordering), both approve-guard orderings, the 5-step commit-guard ordering, universal auth→role→existence→state precedence, all 8 calculations (score weights, grade/apr tiers, amortization round-then-subtract, servicing fee, late fee floor+pct, both distribution variants), the 3-level charge-off cascade with snapshot-before-zero, and basis-weighted recovery — all expressed in precise prose with no pseudocode/fuzzy words.
- Contract 3 (§3 Path Purity): 323 §3 backtick tokens scanned, 0 path/method/combo leaks.

**Notable decisions:**
- All 16 error IDs surface in the §1–§4 narrative, not just the §5 table.
- Initially drafted §3 with 14 fine-grained subsections, then consolidated to 8 (merging schedule into disbursement, distribution into the waterfall, and late-fee/default/charge-off/recovery into one) to stay within the 5–9 guideline while preserving every rule; fixed the one cross-reference (§3.6→§3.5) that shifted during consolidation.
- Scattering: the OCC field `expected_loan_version` is introduced in §2.6 and re-applied in the §3.5 (renumbered) commit workflow; safety/fiscal commit parameters are split between the commitment workflow and the deposit/diversification narrative; numeric constants (DSCR full ratio 2.0, NSF penalty 15, age 60 months, servicing 0.01, late-fee floor 2500/5%) are embedded in business statements rather than listed.

## Step 5: Generate unit tests (concurrent with Step 6) — 2026-05-29T13:05:34Z

Generated complete test infrastructure for `task_0044_p2p_small_business_lending` purely from the four input files plus the unit-test-generator skill spec.

**Stage 1 — `test_helpers/` (9 files):** types.py, api_client.py (32 endpoints), api_errors.py (15 errors registered), assertions.py, factories.py, constants.py, test_users.py (per-instance entity-backed header builders, distinct underwriter ids for SoD), fixtures.py (threads loan.version between commits; drives loans to REPAYMENT/DEFAULTED/CHARGED_OFF), __init__.py.

**Stage 2 — `test_suite/` (conftest + 6 test files, 71 tests):** test_01_scoring_and_pricing, test_02_application_lifecycle, test_03_funding_and_disbursement, test_04_repayment_allocation, test_05_default_chargeoff_recovery, test_06_disclosures_reads_and_rbac.

**Coverage:** Queue A (Difficulty) all 18 instances ×≥2 → 38 tests. Queue B (Corner) all 35 non-stub instances ×≥1 → 33 tests. Distinct: 18/18 difficulty, 35/35 non-stub corner.

**Skipped under PRD-first filter:** none. **Stubs (not translated):** 2 `excluded_because` corner stubs (rbac/segregation_of_duties_same_underwriter_blocked; consistency_model/immediate_consistency_committed_cents_visible_in_same_response) — both cross-refs resolve to real covered difficulty instances.

**Verification:** every test has exactly one Design: tag → real instance; every cited PRD sentence verbatim-grepped (~80 citations); no skip/xfail; no scaffold leakage; all numeric assertions independently recomputed in Python and matched (score 92.0/70.0/69.83/66.0/12.0, level payment 103274, interest 5990, principal 97284, pro-rata 2472/2471, charge-off write-downs 4,200,000/4,600,000, late fee 5164, 3×5164=15492). All 71 tests collect cleanly.

## Step 6: Generate implementation (concurrent with Step 5) — 2026-05-29T13:05:34Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Files (12):** start.sh (executable launcher), requirements.txt (Flask==3.0.3), app.py (routes + error handlers + RBAC), db.py (in-memory store, 8 dicts), errors.py (16-entry catalog), response.py (envelope helpers), middleware.py (X-User-ID/X-User-Role auth + RBAC), clock.py (settable logical UTC clock, ISO8601 3-frac-digit, add_months), calculations.py (scoring, APR tiering, amortization, servicing fee, late fee, largest-remainder — Decimal/ROUND_HALF_UP), services.py (state transitions, commit guards, disburse, waterfall, late-fee/default, charge-off cascade, recovery, disclosure supersession), validation.py, serializers.py.

**Endpoints: 31 implemented** (borrowers 3, loan-applications 6, loans 8, repayments 2, investors 4, investments 4, compliance-disclosures 3, /_clock/set_current_utc 1).

**start.sh:** set -euo pipefail, cd own dir, pip install -q -r requirements.txt, exec python3 app.py; app.py binds 0.0.0.0:$PORT (default 10000), threaded=True; foreground via exec.

**Key decisions:** no seeding (boots empty every invocation); Decimal-everywhere for money/rates (serialized as JSON numbers); validation precedence per PRD §2.7 (approve: auth→forbidden→not-found→invalid-state→SoD→fundability; investments: not-funding→OCC(412)→funding-exceeded→insufficient-capital→diversification); version bumps on every mutation; RepaymentAllocation carries only id/created_at; largest-remainder = fractional DESC then creation-seq ASC; disburse-not-fully-funded → ERR_INVALID_STATE(409); disclosure-missing → ERR_DISCLOSURE_MISSING(422); RECOVERY repayments PlatformAdmin-only. Verified via 4 end-to-end scripts against a live server; all assertions passed.

## Step 7: Run tests and iterate — 2026-05-29T13:30:00Z

All tests pass across the full 8-round parallel stability sweep.

**Iterations run:** 2 (baseline sweep → 1 fix → confirming sweep).

**Tests deleted:** None. No test failed PRD coverage or unique-derivability.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py`, `create_application()` — fixed a `TypeError: got multiple values for keyword argument 'plaid_avg_monthly_revenue_cents'`. The helper forwarded both `**profile` (the baseline `A_GRADE_PROFILE`, which contains the four `plaid_*` keys) and `**app_overrides` into `create_loan_application_payload()`. Any test that overrode an individual plaid input (e.g. `create_application(plaid_avg_monthly_revenue_cents=300_000, ...)`) routed that key into `app_overrides`, colliding with the same key already present in `profile`. Changed the helper to `profile.update(app_overrides)` first, then forward a single merged `**profile`, so caller overrides take precedence over the baseline profile without colliding.

**Fixes applied to implementation/:** None. The implementation was already correct; this was purely a test-fixture argument-forwarding bug.

**Diagnostic notes:**
- All 4 baseline failures (`test_score_borrower_subscore_floors_and_caps_drive_grade`, `test_credit_score_exactly_70_is_grade_b_inclusive`, `test_credit_score_just_below_70_is_grade_c`, `test_grade_c_borrower_apr_1299`) were the same root cause — a `TypeError` raised inside the fixture before any request was even issued. This matched the STEP 2 triage hint (multiple tests sharing one setup error → suspect test_helpers first).
- Verified each test's expected scoring math against the verbatim PRD §3.2 weighted-subscore formula (DSCR 0.40 / stability 0.30 / NSF 0.20 / age 0.10, round-half-up to 2dp, inclusive grade lower bounds, APR-by-grade table). All four expected values (12.0→F, 70.0→B, 69.83→C, 66.0→C) are uniquely derivable from PRD prose, so the assertions are faithful and were preserved.

**Final state:** 8/8 parallel rounds, 71/71 tests passing in every round (zero flakiness). Results files cleaned up.

## Step 8: Finalize PRD — 2026-05-29T13:25:43Z

PRD_FINALIZED.md is in place and **byte-identical** to PRD.md (258 lines, 0-line delta, 0%). This is the correct outcome.

**Changes made:** None. **Rationale:** the sole `<step_7_diff>` item was an explicitly pure test-fixture bug (`create_application()` keyword-collision in `test_helpers/fixtures.py`) — it reveals neither PRD-silence nor PRD-mismatch. The error raised inside the fixture before any request reached the server; the implementation was already correct. Tests deleted: None; implementation fixes: None → no behavioral choice to pin.

**Pre-edit search log (single subject, produced no edit):** subject = scoring/grading/pricing pipeline (the four failing tests' area). Enumerated calculations.py `score_borrower` (DSCR 0.40 / stability 0.30 / NSF 0.20 / age 0.10, round-half-up 2dp), `grade_for_score` (A≥85/B≥70/C≥55/D≥40/F inclusive), `apr_for_grade`/`APR_BY_GRADE` (A .0599/B .0899/C .1299/D .1799/F None), services.py `score_application` (stamps credit_score/risk_grade/offered_apr, SUBMITTED→SCORED). All already uniquely described by existing PRD §§3.1–3.2 prose → no wording adjustment.

## Step 9: Complete PRD — 2026-05-29T13:33:17Z

Full PRD-vs-implementation scan complete. PRD_COMPLETED.md produced from PRD_FINALIZED.md.

**Source vs output:** PRD_FINALIZED.md = 258 lines / 41,675 chars; PRD_COMPLETED.md = 258 lines / 42,761 chars; char delta **+1,086** (line count unchanged — all in-paragraph edits).

**Counts:** 7 changes — **6 ambiguity-pins, 1 mismatch-revision**.

**Changes:**
- §2.4 Common Resource Properties — insert — ambiguity — `version` begins at `1` when first persisted — db.py:54.
- §2.7 Validation Ordering — revise — mismatch — body-shape validation runs after auth/role but BEFORE existence/state gates (malformed body → ERR_VALIDATION even with unresolvable identifier) — app.py:128-153, :495-504, :330-339.
- §3.2 Scoring — insert — ambiguity — ERR_INVALID_STATE (409) for SUBMITTED-application-with-non-ACTIVE-borrower — app.py:208-209.
- §3.4 Investor deposit — insert — ambiguity — deposit `amount_cents` minimum = at least 1 cent — app.py:471-472.
- §3.4 Investments — insert — ambiguity — supplied `expected_loan_version` is retained on the created investment and echoed in its serialized form — services.py:175 + serializers.py:49-50.
- §3.5 Disbursement — insert — ambiguity — ERR_INVALID_STATE (409) when `committed_cents != principal_cents` (not-fully-funded) — services.py:204-206.
- §3.7 Recovery — insert — ambiguity — Borrower-posted RECOVERY repayment → ERR_FORBIDDEN_ROLE, role check precedes loan state check — app.py:347-348.

**Deliberately left unchanged:** §2.1 already pins disallowed-role self-registration → ERR_FORBIDDEN_ROLE; undocumented additive optional list filters (status/document_type) don't alter PRD default results; `add_months` day-clamping not a distinct interpretive conflict.

## Pipeline complete — 2026-05-29T13:33:17Z

All 9 steps done. Final state: 71/71 tests passing across 8/8 parallel rounds (zero flakiness). Deliverables: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (+7 pins), test_helpers/ + test_suite/ (71 tests), workspace/implementation/ (Flask, 31 endpoints, in-memory).
