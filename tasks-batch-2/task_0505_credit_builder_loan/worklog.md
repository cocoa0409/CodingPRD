# Worklog — task_0505_credit_builder_loan

Scenario: 505. Credit-Builder Loan & Secured Card (Self/Chime style): locked-savings installment loan, on-time payment → tri-bureau reporting, graduation to unsecured & deposit release, secured-card deposit/limit, autopay & delinquency handling, score-tracking dashboard, APR/fee disclosure, early-payoff

## Step 1: Create task directory — 2026-06-26T08:22:28.000Z

Created reserved directory `tasks/task_0505_credit_builder_loan/` and `tasks/task_0505_credit_builder_loan/workspace/`. Used the pre-allocated index 0505 verbatim (did not scan ./tasks). Verified `./INSTRUCTION.md` exists for Step 3.

## Step 2: Generate scaffold (Expert tier) — 2026-06-26T08:46:15.000Z

All three files are written correctly with the proper single top-level keys, and the SCAFFOLD.yaml has none of the forbidden design keys.

Generated the **Expert-tier** scaffold for task_0505_credit_builder_loan (Credit-Builder Loan & Secured Card, Self/Chime style). All three files written and the lint passes clean.

**Scaffold profile** — primary archetype compliance/audit blended with ledger reconciliation; layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled/clock-driven actions, rate/threshold triggers; topology hybrid; state-machine shape parallel; role model segregation-of-duties; consistency immediate.

**Counts**
- **Entities: 11** — Account, Disclosure, CreditBuilderLoan, InstallmentSchedule, Payment, SecuredCard, CardDeposit, AutopayEnrollment, BureauReport, ScoreSnapshot, PayoffQuote
- **State machines: 5** — Account (compound posture w/ freeze cascade + revert), CreditBuilderLoan (parallel axes: lifecycle × delinquency, with delinquency cure cycles), SecuredCard (branching suspend/resume revert + release), Disclosure (issue/ack/supersede), PayoffQuote (quote/consume/expire)
- **Calculation rules: 6** — compute_amortized_payment (non-linear), build_amortization_split (pinned per-line rounding order), allocate_payment (fee→interest→principal waterfall + wallet overpay), compute_payoff (dual-variant: actual vs scheduled), compute_score_delta (dual-variant: optimistic vs realized), compute_late_fee_assessment (capped threshold)
- **Validations: 18** (priority-ordered); **Errors: 16**; **Endpoints: 46** (incl. 4 `/_clock/*` test-driving sweeps with mandatory default clock 2026-01-01T00:00:00Z); **Roles: 4**; **Concurrency rules: 2** (loan-payment OCC, card-deposit OCC, both 412)

**Difficulty design (§1.8):** all 9 rules × 2 instances = 18 instances; all formula-derived asserts precomputed as literals (e.g. monthly_payment 10887, payoff 110712, savings 9045, score delta 6, deposit-cap 250000 boundary).

**Corner design (§1.9):** 52 instances (46 active + 6 `excluded_because` stubs pointing at real §1.8 instances) spanning all nine claim-extraction sections.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (496 calls checked across §1.8/§1.9; all FK reverse-reachability satisfied — required setting `api_prefix: /` and adding `GET /autopay-enrollments/{id}`). No forbidden concurrency vocabulary; no dead enum values; design keys correctly isolated to their own files.

One note for downstream: graduation was modeled as PAID_OFF → GRADUATED (not ACTIVE → GRADUATED) to resolve a contradiction (outstanding==0 already auto-fires PAID_OFF), so a fully-paid loan must still be explicitly graduated by a LoanServicer to flag the linked card for deposit release.

## Step 3: Copy INSTRUCTION.md — 2026-06-26T08:46:33.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0505_credit_builder_loan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T08:52:53.000Z

Generated `workspace/PRD.md` (~291 lines, 48480 bytes). Read SCAFFOLD.yaml only; confirmed neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

**Document metrics:** 5 top-level sections; §2 has subsections 2.1–2.10; §3 has 3.1–3.12 (27 headings total). §4 endpoint table = 46 rows (matches all 46 scaffold endpoints). §5 error table = 16 rows.

**Hard Contract reports (all PASS):**
- Field coverage: 59/59 entity fields, 7/7 endpoint body/query/path params present.
- Rule coverage: 18/18 validations in §2.5 ordered prose; 2/2 OCC rejections (expected_loan_version/expected_card_version → ERR_STALE_VERSION/412); all Account/Loan(dual-axis)/SecuredCard/Disclosure/PayoffQuote transitions expressed; 6/6 calculations rendered step-for-step with constants embedded; sibling-branch symmetry preserved.
- Path purity (§3): 437 backtick tokens scanned, 0 path-like tokens.
- §2.2 matches fixed verbatim block byte-for-byte; no pseudocode operators / fuzzy words leaked.

## Step 5: Generate unit tests — 2026-06-26T09:23:07.000Z

**Test files:** 9 test files (plus `conftest.py`) in `test_suite/`, totaling **82 tests**.

**Coverage by queue:**
- **Queue A (Difficulty, §1.8):** all **18 instances** translated, each covered by **2 tests** (36 difficulty-tagged tests). Primary tests in domain files (test_02–test_07); a second-angle test per instance in `test_09_difficulty_reinforcement.py`, each asserting a distinct, uniquely-PRD-derivable observable.
- **Queue B (Corner, §1.9):** all **46 non-stub instances** covered by ≥1 test (46 corner-tagged tests), spanning sections entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model.

**Instances skipped:** none beyond the design's own stubs. **6 corner stubs** carry `excluded_because:` (correctly NOT translated; all 6 cross-references resolve to real §1.8 difficulty instances). No non-stub instance failed the PRD-first filter.

**Two instances using `validate_error_is_one_of`** (faithful adjudication, not a skip): `disclosure_not_acknowledged_blocks_loan_create` and `loan_fund_requires_account_eligible` — setup (VERIFIED but disclosure-unacknowledged → posture BLOCKED) makes both priority-5 eligibility and priority-8 disclosure 409s applicable; design YAML hedges with `IN {...}`.

**Audit (all green):** every test has exactly one resolvable `Design:` tag; no dual/untagged/unknown tags; 122 PRD citations verbatim; no skip/skipif/xfail; no scaffold leakage; all files compile; all imports/`api.<method>` calls resolve.

**test_helpers/ files written:** __init__.py, types.py (BureauReport & ScoreSnapshot omit updated_at/version per common_fields:false), api_client.py, api_errors.py (16 error IDs + status map), assertions.py, constants.py, factories.py, test_users.py (Borrower entity-backed make_borrower_headers(account_id); opaque operator roles), fixtures.py (composite chains: funded-loan, paid-off, graduated-card-release-ready).

## Step 6: Generate implementation — 2026-06-26T09:23:07.000Z

Complete Python + Flask implementation in `workspace/implementation/`.

**Source files:** start.sh (guarded dep install, `exec python3 app.py`), requirements.txt (flask==3.0.3), app.py (46 endpoints + error handlers + envelope), constants.py, errors.py (16-entry catalogue), clock.py (logical clock default 2026-01-01T00:00:00Z, ISO 3-digit fractional, calendar-month math), db.py (in-memory Store, UUID + monotonic seq), response.py (meta/response_type/data envelope + pagination), middleware.py (X-User-ID/X-User-Role auth + role gate), common.py (common-field stamping, touch/touch_time_only, pagination), calculations.py, services.py (posture, payment application, delinquency/autopay/bureau sweeps, cascades), serialize.py, validate.py.

**Storage:** pure in-memory dicts on one global Store; no persistence; nothing seeded — every start.sh relaunch = fresh empty process (verified 0 accounts across 3 restarts).

**start.sh boots:** reads $PORT (default 10000), `python3 app.py` → `app.run(host="0.0.0.0", port=PORT, threaded=True)` foreground via exec; dep install guarded by import check.

**Notable design decisions:**
- Payment allocation: fees first (global), then walk installments oldest-first taking interest then principal until cash exhausted; remainder → wallet. Reproduces all pinned figures (payoff 110712/119757/9045, waterfall 1500/1599/9288, lump 60000, overpay 70000→wallet).
- OCC decoupling: loan `version` is the payment-OCC token; system sweeps advance state via `touch_time_only` (no version bump) so the cure-recipe payment carrying fund-time version still succeeds. Payments/deposits bump version normally.
- Delinquency sweep = strict one-bucket advance per run, one capped late fee per crossing (only model consistent with the late-fee-cap test: CURRENT+bg35→DPD_30→DPD_60→DPD_90 = 4500 at cap).

**One documented inconsistency (flagged, not a bug):** `charge_off_drives_default_compound` corner expects a single sweep CURRENT→CHARGED_OFF at >90 DPD, mathematically incompatible with the strict one-step-per-sweep mandated by the late_fee_cap test. Chose strict one-step (matches §1.8 difficulty instances + fee-cap rule). Under this impl a loan reaches CHARGED_OFF via successive sweeps (4 from CURRENT). All other §1.8/§1.9 instances replayed live and pass.

## Step 7: Run tests and iterate — 2026-06-26T09:32:10.000Z

**Iterations run:** 2 (1 diagnostic baseline at 80/82, 1 verification at 81/81 × 8 rounds clean). Initial sweep showed 80/82 consistently across all 8 rounds (no flakiness — both failures deterministic). Union of failures: `test_charge_off_drives_default`, `test_wallet_funded_autopay_insufficient_wallet`.

**Tests deleted (1):**
- `test_charge_off_drives_default` (test_suite/test_04_payments_and_delinquency.py) — **STEP 1b unique-derivability failure**, BRANCH-AMBIGUOUS state-machine semantics. PRD §3.5 describes status-guarded delinquency edges ("`DPD_90` advances to `CHARGED_OFF`") that admit two faithful readings: (A) one-bucket-per-sweep status-guarded edges, vs (B) jump-to-bucket-matching-DPD. This test required reading (B) — a single sweep at 117 DPD jumping CURRENT→CHARGED_OFF — while `test_late_fee_cap_reached_exactly`, `test_loan_parallel_axes_advance_and_cure`, and `test_dpd_30_at_grace_boundary` all require reading (A). PRD prose does not uniquely determine which; the suite's own tests prove the ambiguity. Implementation (one-step model) satisfies all four other delinquency tests. Scaffold rule that drove generation: `Corner/state_machines/charge_off_drives_default_compound` (already flagged as a documented inconsistency in Step 6).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/` (1):**
- `services.py`, `run_autopay()` — when a wallet-funded autopay draft cannot be covered by `wallet_cents`, the impl was aborting the entire sweep request with `ERR_INSUFFICIENT_WALLET` (HTTP 409). Changed it to skip that single draft (no payment created, no wallet debit) and continue, so the sweep capability returns 200 OK. Mandated verbatim by PRD §4 line 221 ("The clock and sweep capabilities return `200 OK`") and faithful to §3.11 line 209 ("the draft is rejected ... autopay never overdrafts the wallet" → no payment, no debit). PRD-required no-overdraft behavior fully preserved; only the wrongly-propagated HTTP 409 on the sweep endpoint removed. Made `test_wallet_funded_autopay_insufficient_wallet` pass (its setup `run_autopay()` call goes through `get_success_data`, which requires 2xx).

**Final state:** 81/81 passing on all 8 parallel rounds, no flakiness. Storage remains in-memory only. Orchestrator re-ran a confirming 8-round sweep: all 8 → passed=81/total=81/failed=0.

## Step 8: Finalize PRD — 2026-06-26T09:37:33.000Z

Produced `workspace/PRD_FINALIZED.md` (Step 7 had 1 deletion + 1 implementation fix, so Step 8 ran).

**Line counts:** PRD.md = 291; PRD_FINALIZED.md = 291. Net delta 0 lines (all three edits are inline sentence extensions/revisions). Three lines changed (99, 165, 209).

**Changes:**
- §3.5 (line 165) — *insert* — Pinned the one-bucket-per-sweep, status-guarded, lower-bound-threshold delinquency model (CURRENT→DPD_30→DPD_60→DPD_90→CHARGED_OFF advances at most one adjacent bucket per sweep, gated by days-past-due ≥ {1,31,61,91} with no upper bound), with the 117-DPD-still-CURRENT example. — services.py:184-228.
- §3.11 (line 209) — *revise* — Changed "the draft is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 409)" to: the single draft is skipped (no payment, no wallet debit), the sweep continues, capability returns 200 OK with no error surfaced. — services.py:295-303, app.py:1024-1029.
- §2.5 (line 99, item 16) — *revise* — Removed the false claim that the wallet-coverage check on wallet-funded autopay surfaces `ERR_INSUFFICIENT_WALLET`; clarified it only exists inside the batch sweep and produces no synchronous request-endpoint error (silent skip). — services.py:295-303; errors.py:30,48.

**§5 catalogue left unchanged:** `ERR_INSUFFICIENT_WALLET | 409` retained because impl still defines the code (just never raises it); removing it would diverge from impl.

**Per-edit pre-edit search log:** (1) §3.5 — enumerated _DPD_LADDER/_NEXT_THRESHOLD, delinquency_sweep_one single-step ladder + lower-bound guards + per-bucket _assess_late_fee + CHARGED_OFF→DEFAULTED coupling, run_delinquency_sweep, cure_delinquency reverse path; rephrased gate as lower-bound "at least N, no upper bound" and "at most one adjacent bucket per sweep"; confirmed no fee on CHARGED_OFF crossing, cure path untouched. (2) §3.11 — enumerated run_autopay skip-continue, run_autopay_route→ok_empty (200), grepped all *.py for INSUFFICIENT_WALLET (only defined in errors.py, zero raise sites); worded skip-and-continue + 200 OK + no error, retained no-overdraft guarantee. (3) §2.5 item 16 — same paths + §2.5 numbering dependency; kept item number "(16)" intact, reworded only the parenthetical, cross-referenced §3.11.

## Step 9: Complete PRD — 2026-06-26T09:48:33.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan starting from PRD_FINALIZED.md (always runs).

**Files:** Source PRD_FINALIZED.md (291 lines, 49,895 chars) → PRD_COMPLETED.md (291 lines, 55,676 chars). Char delta: **+5,781**. Line count unchanged — all edits in-paragraph; no new sections.

**Counts:** 17 changed lines — **13 ambiguity-pins**, **4 mismatch-revisions**.

**Per-change bullets:**
- §2.4 — revise — mismatch — `version` starts at 1; add delinquency-sweep version-non-increment exception — common.py:21,32 / services.py:216
- §2.10 — insert — mismatch — note delinquency-sweep exception to "every touched resource increments version" — common.py:32 / services.py:216,220,228
- §3.1 — insert — ambiguity — duplicate-email & bad-state_code → ERR_INVALID_REQUEST; KYC decision VERIFIED/REJECTED/PENDING + state-guard/ERR_INVALID_REQUEST outcomes — app.py:83-88,136-148
- §3.1 — revise — mismatch — acknowledgement barred only by account status FROZEN/CLOSED (not disclosure-driven BLOCKED posture); eligibility(5) before ISSUED guard(6) — app.py:337-340
- §3.3 — insert — ambiguity — due_date day-clamping; schedule-list ordered by period_index (overriding §2.3 default) + optional status filter — clock.py:41-52 / app.py:530,526-528
- §3.4 — revise — mismatch — allocation is per-installment interleave (oldest-first interest-then-principal per installment, all unpaid), not all-interest-then-all-principal; principal capped at outstanding — calculations.py:90-129
- §3.4 — insert — ambiguity — payment valid only when loan lifecycle_status ACTIVE (ERR_INVALID_STATE); unknown source → ERR_INVALID_REQUEST — app.py:663-671
- §3.5 — insert — ambiguity — every delinquency-sweep loan mutation refreshes updated_at without bumping version — services.py:216,220,228
- §3.6 — revise — mismatch — terminal-state graduation → ERR_INVALID_STATE (vs ERR_GRADUATION_NOT_ELIGIBLE); flag every account card with balance 0; final report only if no LOAN row for cycle — app.py:498-516 / services.py:465-469
- §3.8 — insert — ambiguity — per-diem "last due date" = most recent due_date ≤ clock, else from funded_at, floored at 0 — app.py:590-602
- §3.8 — insert — ambiguity — early-payoff quote must belong to the path loan, else ERR_NOT_FOUND — app.py:627-628
- §3.9 — insert — ambiguity — charge amount_cents ≥ 1 (ERR_INVALID_REQUEST) and card must be ACTIVE (ERR_INVALID_STATE) — app.py:836-839
- §3.10 — insert — ambiguity — "linked loan" for SoD = account's GRADUATED loan else earliest-created; no-op when no loan — services.py:47-59 / app.py:887-889
- §3.11 — insert — ambiguity — autopay skips non-ACTIVE-loan enrollments; draft amount = oldest unpaid installment's remaining amount_due; skip if nothing owed; idempotency window anchored on funded_at — services.py:274-307,247-271
- §3.12 — insert — ambiguity — ACTIVE card with no account loan emits no SECURED_CARD row; row's loan_id/rating/balance sources pinned — services.py:423-429,337-351
- §3.12 — revise — mismatch — ScoreSnapshot persisted only for accounts with ≥1 funded loan; payment-history marks counted only from LOAN-tradeline rows — services.py:432-459,354-369
- §3.12 — insert — ambiguity — utilization card selection (ACTIVE-first else earliest, else 0); "first loan" = earliest funded_at; on-demand score read response shape + projection validation — services.py:372-410 / app.py:226-245

**Note:** Additive optional query filters on lists where PRD enumerates none (payments, deposits, payoff-quotes, disclosures, bureau-reports) left undocumented — additive capabilities that don't make documented default behavior ambiguous.

---

## Pipeline complete

All 9 steps finished. Final state: **81/81 tests passing across all 8 parallel rounds** (no flakiness). Deliverables in `tasks/task_0505_credit_builder_loan/`: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml; test_helpers/ + test_suite/ (81 tests); workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
