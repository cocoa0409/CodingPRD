# Worklog — task_2473_hotel_management_agreement_owner_reporting

## Step 1: Create task directory — 2026-09-02T21:26:15.687Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2473_hotel_management_agreement_owner_reporting` and its `workspace/` subdirectory. Index 2473 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T22:49:14.189Z

Done. All three artifacts are in place at `/home/ubuntu/github/CodingPRD/tasks/task_2473_hotel_management_agreement_owner_reporting/` and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**`SCAFFOLD.yaml`** (2778 lines) — archetype `multi_party_negotiation` / `ledger_reconciliation`, `difficulty_level: expert_plus`, layers `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`; consistency `immediate`; role model `segregation_of_duties`.
- 13 entities (ManagementAgreement, OperatingBudget, VarianceRequest, MonthlyReportPackage, MarketBenchmark, CentralizedServiceCharge, FeeAccrual, CashDistribution, ReserveLedgerEntry, WorkingCapitalCall, PerformanceTest, BrandStandardDispute, EmploymentClaim)
- 11 state machines (OperatingBudget and BrandStandardDispute are revision/negotiation cycles), 2 OCC concurrency rules (`budget-revision-stale-agreement`, `true-up-stale-agreement`, both on `expected_agreement_version` → 412)
- 13 calculations (3 with divergent variants), 50 ordered validations, 40 endpoints, 50 error codes, 4 roles all `identity: opaque`
- Logical clock pinned at `2026-08-01T00:00:00Z` with a 5-step epoch sweep (deemed-approved budgets → overdue calls → lapsed cures → deadlocked disputes → terminated agreements)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 9 rule_ids, 23 instances: `dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — all nine guide sections walked, 70 instances (59 with full recipes + 11 `excluded_because` stubs, every stub citing a real §1.8 instance name and carrying no `test_recipe`): entities 12, state_machines 11, calculations 11, validations 12, endpoints 6, errors 4, rbac 6, cross-cutting complexity layers 6, consistency model 2.

Checks run beyond the lint: no `scaffold_*_design` keys leaked into SCAFFOLD.yaml; instance names unique across the union of both design files; no forbidden concurrency vocabulary anywhere; every asserted literal hand-derived from the §1.3 formulas.

Two mechanical YAML fixes were needed to make the files parse (PyYAML rejects both in flow context): optional-input markers in `input: [...]` lists are now quoted (`"note?"`, matching the skill's own examples), and JSONPath captures containing an index are now quoted (`"$.data[0].id"`). I also corrected the stale density-notes comment in `complexity_profile` to 13 calculations / 50 validations / 50 error codes.

## Step 3: Copy shared files — 2026-09-02T22:49:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T23:04:16.947Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2473_hotel_management_agreement_owner_reporting/workspace/PRD.md`
- **Final line count: 457** (13,330 words)
- **Final section title: `## 5. Error Code Catalogue`** — the file ends at a real section boundary, on the last row of the 50-row error table (`| \`ERR_BUDGET_AGOP_NON_POSITIVE\` | 422 |`), not mid-sentence. No audit footer was written into the document.

**Structure:** §1 Introduction; §2 with ten subsections (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Identity/Audit/Logical Clock, 2.5 Cents & Rounding, 2.6 Version Pinning & OCC, 2.7 Cascade Discipline & Distribution Hold, 2.8 Nested Path Resolution & Validation Precedence, 2.9 Fee Ledger & Reserve as Append-Only, 2.10 The Epoch Sweep); §3 with nine workflow subsections (agreement activation; budget cycle; variance authority; monthly package/chargebacks/fees; chargeback contest; owner review + cash waterfall + working-capital funding; benchmarking + performance test + cure + termination; annual incentive true-up; brand disputes + employment-claim liability); §4 40-endpoint 4-column table; §5 50-error 2-column table.

**Hard Contract results (report only, not in the PRD):**
- **Contract 1 — Field-Name Coverage: PASS.** Mechanical diff over 154 required identifiers (140 entity `fields[].name` + all endpoint input names + `id`/`created_at`/`updated_at`/`version`): 0 missing. One gap found and fixed during verification (`budget_id` was implicit in §3.3 prose; now backticked explicitly). All 14 non-entity response-summary fields (true-up settlement fields and the five sweep counters plus `current_utc`) are also present.
- **Contract 2 — Rule Coverage: PASS.** All 50 validations appear as a numbered precedence list in §2.8 with error ID, HTTP status and full `applies_to` enumeration (verified exactly 50 numbered items); all 50 error IDs appear in §1–§4 prose *before* the §5 catalogue; both `expected_agreement_version` OCC rules are expressed; all 11 state machines' states/transitions are covered, including sibling-branch symmetry pairs (financial ACCEPT vs DISPUTE, `FFE_RESERVE` vs `OWNER_CONTRIBUTION`, cap `allow_deferral` false vs true, agreement `ACTIVE` vs `CURE_PERIOD` termination branches, `RESOLVE_OWNER_FUNDS`/`RESOLVE_WAIVED` from two origins each); all 13 calculations are reconstructible in prose, including the three deliberately divergent rounding orders and the weighted-vs-simple RPI split.
- **Contract 3 — §3 Path Purity: PASS.** Scan of every backticked token between `## 3.` and `## 4.`: 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path combos; also 0 plain-text `/hotel-management` or bare-method occurrences outside backticks in §3.

Other checks: §2.2 is byte-verbatim against `section-2.2-response-structure.md`; no fuzzy words (`approximately`, `roughly`, `conservatively`) and no pseudocode blocks anywhere. The hard constraint was honoured — neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator anti-truncation verification:** independently confirmed 457 lines, 5 top-level sections at lines 3/11/197/357/404, tail ends on a complete markdown table row (`| \`ERR_BUDGET_AGOP_NON_POSITIVE\` | 422 |`). Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T00:16:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first. Its own summary heading self-labelled "Step 7 implementation" — that is the subagent's typo; this is the Step 6 artifact. Summary below is verbatim otherwise.)

Server boots cleanly from `start.sh`, serves, and shuts down; port closed and no lingering process.

### Files written (all under `.../workspace/implementation/`)

```
start.sh              guarded pip install + exec python3 app.py; PORT env, default 10000
requirements.txt      Flask>=3.0.0
app.py                app factory, 7 blueprints, ApiError/HTTPException/Exception handlers
money.py              Decimal prec 60; dec / rhu (HALF_UP) / ffloor (FLOOR) / round_dp / as_json_number
timeutil.py           logical-clock ISO helpers, 3-fraction-digit formatting, cmp_iso
errors.py             ApiError + all 50 error ids -> HTTP status + default messages
db.py                 in-memory Store (13 dicts), logical clock, new_row/touch/by_seq/serialize
response.py           meta envelope (req_ + 20 uppercase alnum), ok / ok_list / error
auth.py               X-User-ID + X-User-Role -> (user_id, role); 401 then 403
validate.py           rule-3 body/bounds helpers, rule-4 check_enum, pagination(strict=)
services/calc.py      13 pure calculations (three divergent base-fee rounding conventions)
services/core.py      finders, cascades, freeze, accrual set, waterfall, holds, reserve ledger
routes/common.py      paged()
routes/agreements.py  agreements, activate, reserve-ledger, WC calls, fund, annual-true-up   (8)
routes/budgets.py     budgets CRUD, submit, decision, variance requests + decision            (8)
routes/packages.py    packages, benchmarks, charges, charge review, submit, owner-review,
                      fee-accruals, distributions, execute                                   (13)
routes/perf.py        performance tests score/list, cure, terminate                           (4)
routes/disputes.py    brand disputes create/list, rounds                                      (3)
routes/claims.py      employment claims create/list, allocation                               (3)
routes/clock.py       POST /_clock/set_current_utc + five-step epoch sweep                     (1)
```

**Endpoint count: 40** (verified via `app.url_map`, matching the 40-row PRD §4 table). Storage is in-memory dicts only; no seeding anywhere — `Store.reset()` starts every collection empty and a fresh `GET /hotel-management/budgets` on a new process returns `total_count: 0`.

### Verification
- `pyflakes` clean.
- End-to-end smoke run over **every** endpoint: agreement → activate → budget submit/approve → variance (PENDING → APPROVED) → package → benchmark → chargeback → submit (base 270000, central 100000, agop 3630000 all correct by hand) → CONTEST/REAFFIRM/CONTEST/ADJUST (agop correctly re-rose to 3680000 and the incentive accrual was rewritten) → owner-review both dimensions (`package_status` COMPLETE) → waterfall → execute → WC call + fund → true-up (delta −268000, a legitimately negative accrual) → performance test FAILED_CURABLE → CURE_PERIOD + hold → ELECT_CURE/PAY_CURE → back to ACTIVE with holds released → full dispute cycle incl. rescission and both funding branches (ledger `[CONTRIBUTION +360000 → 360000, DISBURSEMENT −1000 → 359000]`) → claim allocate (odd cent stays with the owner: 500001/500000) and reverse → repeat failure → TERMINATION_TRIGGERED → notice → clock sweep (`lapsed_cure_count 1, overdue_call_count 1, terminated_agreement_count 1, deadlocked_dispute_count 1`) → TERMINATED. Error surface spot-checked: 401/403/404/405/409/412/422, `ERR_INVALID_PAGINATION` on the one strict list, silent clamping elsewhere.
- Real boot: `PORT=<free> bash start.sh`, trivial GET returned 200, zero errors in the log, process killed.

### PRD ambiguities resolved by choosing an interpretation (Step 8/9 will need these)

1. **Ordering ties.** The logical clock does not move between requests, so many rows share `created_at`. Every "created_at ASC" ordering and every "strictly earlier" comparison uses an internal monotonic `_seq`; `created_at` is still stamped from the clock and `_seq` is stripped on serialization.
2. **Version bumps.** `touch()` de-duplicates per request, so a row mutated by several cascade hops of one request bumps `version` exactly once.
3. **Ratio rounding mode.** The scaffold writes `round(x, N)` (banker's) but §2.5 admits only half-up and floor. Chose `ROUND_HALF_UP` for `variance_pct` (6dp), `rpi`/`rpi_weighted`/`rpi_simple_average` (2dp) and `gop_achievement_pct` (4dp). Ratios serialize as JSON floats; threshold comparisons happen on the Decimal.
4. **Validation ordering.** PRD §2.8's absolute 1–50 numbering governs over per-endpoint scaffold prose. Notably rule 40 (`ERR_BUDGET_NOT_APPROVED`) is evaluated **before** rule 41 (`ERR_NO_ACCEPTED_PERIODS`) on performance-tests, even though the scaffold's formula checks accepted periods first.
5. **Undeclared-error gaps.** Activating a non-DRAFT agreement → `ERR_AGREEMENT_NOT_ACTIVE` (409). Owner-review FINANCIAL / claim ALLOCATE / test terminate when the agreement is outside {ACTIVE, CURE_PERIOD} → `ERR_AGREEMENT_NOT_ACTIVE` (409), checked at rule 18's position (before the row-state checks 21/26/28). Charge CONTEST when the parent package `financial_status` ∉ {SUBMITTED, ACCEPTED} → `ERR_INVALID_PACKAGE_STATE` (409), checked after rule 29 and rule 32. Claim REVERSE has **no** agreement-status gate (only ALLOCATE does).
6. **Action-conditional required fields.** On multi-action endpoints: validate `action` presence/type, then — only for a recognised action — its conditionally required fields, then `action` enum membership, then other enums. Missing `cost_estimate_cents`, `funding_source` and `payment_amount_cents` are `ERR_INVALID_REQUEST`; missing `adjusted_amount_cents` on ADJUST is `ERR_ADJUSTMENT_OUT_OF_RANGE` per explicit rule 48.
7. **CENTRALIZED_SERVICES accrual rewrite target.** The spec says "the charge's post-review allocated amount" but the accrual is package-level; used `package.allocated_centralized_cents`, so REAFFIRM is economically a no-op.
8. **Accrual restore target** on REAFFIRM/ADJUST: `INVOICED` when the package is ACCEPTED, otherwise `ACCRUED`.
9. **FAILED_CURABLE off ACTIVE.** The streak increment, hold and distribution freeze are side effects of the ACTIVE→CURE_PERIOD transition, so they are hop-skipped when the agreement is not ACTIVE (the test still lands FAILED_CURABLE with its deadline). The TERMINATION_TRIGGERED branch's increment is unconditional.
10. **ADJUST cascade.** Hop 1 rewrites the charge; hop 2 re-runs the *full* allocation recompute (an ADJUSTED row keeps its adjusted amount and still consumes cap, so later charges may be re-allocated **upward**) then AGOP and the provisional incentive; hop 3 rewrites the INCENTIVE/PROVISIONAL and CENTRALIZED_SERVICES accruals and releases the hold.
11. **Multiple INVOICED accruals of one bucket on execute.** Paid greedily in `_seq` ASC with `min(remaining, amount)`; only accruals receiving > 0 move INVOICED→PAID.
12. **WAIVED_OFFSET on execute.** FLOOR_RESTORATION + REQUESTED calls are extinguished whenever the post-restoration balance ≥ floor (no requirement that `wc_restoration_cents > 0`).
13. **Zero-value ledger/accrual rows.** A `reserve_contribution_cents` of 0 appends no CONTRIBUTION entry; CENTRALIZED_SERVICES and INCENTIVE accruals are omitted when 0 (BASE is always created).
14. **`incentive_tier2_pct` default.** The `>= incentive_fee_pct` bound is enforced only when the field is supplied; the 0.15 default is written as-is even if it falls below `incentive_fee_pct`.
15. **`funded_amount_cents` has no declared bound**, so a negative amount yields `ERR_FUNDING_AMOUNT_MISMATCH` (rule 47), not `ERR_INVALID_REQUEST`.
16. **Non-strict pagination.** Only `GET /hotel-management/budgets` validates pagination (rule 5); every other list clamps silently, and unparseable filter values are ignored rather than rejected.
17. **Sweep boundary strictness.** Steps 1–3 use strict `<` (deadline strictly before the new clock); steps 4–5 use `<=`. The clock is written before sweeping, so all five steps compare against the new value.
18. **`api_request_timestamp`** is real wall-clock time (a server-generated request stamp), deliberately independent of the logical clock, which governs only business deadlines.
19. **Premature ESCALATE** (`round < max_dispute_rounds`) returns `ERR_INVALID_DISPUTE_STATE`, checked immediately after the origin-state check and before the action-role check.
20. **`GET /hotel-management/agreements/{id}/brand-disputes`** supports the scaffold's `franchise_requirement_ref` filter in addition to `status`.

## Step 5: Generate unit tests — 2026-09-03T02:56:00.000Z

(Appended after the Step 6 entry because Step 6 returned first; both were launched concurrently in one orchestrator message per the skill's isolation requirement.)

Generation is complete. Final state of the deliverable:

### Files written

**`test_helpers/`** (Stage 1, 9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** — `conftest.py` plus 18 numbered files, **186 tests**, all collecting cleanly (`pytest --collect-only` → 186, 0 errors; `pyflakes` silent).

| Queue | Files | Tests | Instances |
| :-- | :-- | :-- | :-- |
| A (Difficulty §1.8) | test_01–test_09 | 78 | 23 / 23 |
| B (Corner §1.9) | test_10–test_18 | 108 | 58 / 59 non-stub |

Queue B by section: entities 11, state_machines 8, calculations 9, validations 10, endpoints 5, errors 4, rbac 5, `cross-cutting complexity layers` 4, `consistency model` 2.

Audit ends at **files 18 tests 186 instances 81 problems 0** — every test carries exactly one trailing `Design:` tag, every tag resolves to a real non-stub instance, and every quoted span ≥12 chars greps literally against PRD.md.

### Skipped instances

1. `Corner/state_machines/agreement_activate_twice_second_call_rejected` — rule 18's applies-to list excludes `POST /agreements/{id}/activate` and §3.1 names no error id for a second activate, so the asserted `ERR_AGREEMENT_NOT_ACTIVE` (409) is not uniquely derived from the PRD.

That is the only whole-instance skip. The 11 `excluded_because:` stubs were not translated, by design.

**Recovered instance:** a cross-check of every non-stub corner name against the emitted tags found `Corner/state_machines/termination_notice_from_active_denies_pending_variance_and_holds_distributions` uncovered with no recorded skip reason. PRD §3.7 fully supports it, so it is now translated in `test_11_state_machines.py` (`TestTerminationNoticeFromActive`, 2 tests: notice raises the hold and dates the termination at 2026-10-30; the cascade denies the PENDING `OWNER_REP` variance with `denied_by_cascade` true, holds the distribution at `shortfall_cents` 3702000, and leaves the FY2027 budget `SUBMITTED` since only the `CURE_PERIOD` branch supersedes budgets).

### Design-yaml defects corrected while translating

- `centralized_cap_resets_for_each_reporting_period` names `service_code: "MARKETING"`, which is not one of the five declared codes (PRD §3.4) — a literal translation would have tripped the enum rule instead of the cap. Substituted `REVENUE_MANAGEMENT`, preserving the 100000/90000/10000 arithmetic.
- `owner_review_response_already_reflects_the_full_cascade` sets `ffe_reserve_pct: 0.04` yet asserts `shortfall_cents == 3702000`; with a 0.04 reserve the five demands total 4742000. Used `ffe_reserve_pct: 0` so the pinned 3702000 is the PRD-derived figure.

### In-file partial omissions (not whole-instance skips)

Claims dropped because the PRD does not derive them, while the rest of the instance was translated: the "null data member" error-shape claim; "existence is checked before body validity" (rule 3 precedes rules 6–15); the DRAFT-agreement employment-claim refusal leg (that endpoint is absent from rule 18's twelve); the already-ACTIVE re-activation bullet; a call's pre-funding `funded_amount_cents == 0` (also omitted in the new sweep-consistency test); `late_funded is False` after a REQUESTED→FUNDED funding; `cure_paid_cents == 0` before payment; the "BASE/INCENTIVE accrual still INVOICED" claim after a zero-allocation execution; and `budget_submit_requires_active_agreement` reached via `CURE_PERIOD`.

No file under `workspace/implementation/` was read or written, and the suite was not executed (no server), only collected.

## Step 7: Run tests and iterate — 2026-09-03T01:25:30.910Z

All 8 parallel rounds pass 186/186. Clean sweep achieved.

**Iterations run:** 2 (sweep → fix → sweep). Both sweeps were fully deterministic — no flakiness at all: iteration 1 produced exactly the same 4 failures in all 8 rounds, iteration 2 produced 186/186 in all 8 rounds.

**Tests deleted:** none. All 4 failures survived STEP 1 (PRD verbatim-covers the rule *and* uniquely determines the outcome) and were resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`:** none. The shared factory default in `test_helpers/factories.py` (`budget_payload` → `budgeted_capital_ffe_cents: 4000000`) was deliberately left alone: it is a legitimate non-zero default that the rest of the suite depends on, and every other fixture that wants a zero capital line passes `0` explicitly.

**Fixes applied to `implementation/`:** none. The implementation was correct on all four points.

**Fixes applied to `test_suite/` (STEP 2 — assertion/setup did not faithfully express the cited PRD sentence):**

1. `test_suite/test_01_dual_variant_calculations.py` — `TestRpiWeightedVersusSimpleAverage.test_only_the_weighted_leg_decides_a_passed_covenant`: expected `gop_achievement_pct` 0.7009 → **0.7008**. PRD §3.7: "`gop_achievement_pct` is the actual divided by the pro-rated budget, rounded to four decimal places." With the test's own (passing) `actual_agop_cents == 40410000` and `prorated_budget_agop_cents == 57666667`, the exact ratio is 0.70075144…, which is 0.7008 half-up and 0.7007 floor — 0.7009 is unreachable under any rounding mode PRD §2.5 admits. Arithmetic slip in the test.

2. `test_suite/test_04_transitive_cascades.py` — `TestCurableFailureHoldsThenReleases.test_both_legs_fail_and_the_cure_obligation_is_the_profit_gap`: same 0.7009 → **0.7008**, same numbers (corroborated by the sibling test's `cure_payment_due_cents == 17256667 == 57666667 − 40410000`, which passed).

3. `test_suite/test_12_calculations.py` — `TestGrossNegligenceOverride.test_negligence_puts_the_whole_claim_on_the_manager_up_to_the_cap`: expected `working_capital_balance_cents` 3998999 → **3999999**. PRD §3.9: "the agreement's `working_capital_balance_cents` is decreased by `owner_share_cents`." The test's own asserted `owner_share_cents == 1000001` against `initial_working_capital_cents == 5000000` gives 3999999; the old value was off by exactly 1000.

4. `test_suite/test_13_validations.py` — `_zero_baseline_hotel` fixture: now passes `budgeted_capital_ffe_cents=0, budgeted_capital_brand_cents=0` explicitly. The fixture's docstring claimed it "left both capital lines at their zero default", but it omitted them from the call and so inherited the factory's 4000000, meaning the CAPITAL_FFE baseline was not zero and `ERR_VARIANCE_BASELINE_ZERO` correctly did not fire. PRD §3.3 pins the refusal to the case "when a capital line was budgeted at zero", so the fixture — not the implementation — was inconsistent with the rule under test.

**Orchestrator independent verification** (per standing guidance that a Step 7 subagent can claim a clean sweep without leaving artifacts): read all 8 `results.{1..8}.json` directly — every one reports `passed=186 total=186 failed=0`, all written at 01:20:29–01:20:31 UTC, ~5 minutes before this entry. The clean sweep is real. Sweep was run under `setsid nohup` as required; no `Terminated` reaping signature appeared.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 applied 4 `test_suite/` fixes, so Step 8 runs with those four items as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T01:28:05.323Z

`PRD_FINALIZED.md` written. One edit total.

### Line counts
- `PRD.md`: 457 lines
- `PRD_FINALIZED.md`: 457 lines
- Delta: 0 lines (0.0%) — one line revised in place (§2.5, line 102)

### Changes
- **§2.5 (Cents, Rates and Rounding Discipline)** — *revise* — the "Derived ratios carry pinned precision" sentence now pins the rounding **mode** as half up (the §2.5 half-away-from-zero operation, applied at the ratio's decimal place rather than at whole cents) for all five derived ratios, and explicitly rules out truncation/floor at the pinned precision. Precision values themselves kept verbatim. — `implementation/money.py:38-46` (`round_dp`/`ratio` use `ROUND_HALF_UP`), `implementation/services/calc.py:154,210,214,220,225`

### Per-edit pre-edit search log

**Edit 1 — §2.5 derived-ratio rounding mode**

(a) **Subject identified:** the rounding *mode* applied when a derived ratio is reduced to its pinned number of decimal places. Triggered by Step 7 items 1 and 2, where the reachable value 0.7008 vs 0.7007 for `gop_achievement_pct` distinguishes half-up from floor — PRD stated only the precision, never the mode, so the impl's choice was a genuine PRD silence.

(b) **Impl paths enumerated (read/grepped):**
- `implementation/money.py:38-46` — `round_dp(value, places)` quantizes with `ROUND_HALF_UP`; `ratio()` delegates to it. Single choke point for all ratio rounding.
- `grep -rn "round_dp\|ratio(\|rhu(\|ffloor(" --include=*.py` over the whole tree — every ratio callsite goes through `round_dp`; no bespoke rounding anywhere.
- `services/calc.py:154` `variance_routing` → `round_dp(..., 6)` for `variance_pct` (§3.3 site).
- `services/calc.py:210` `gop_achievement` → `round_dp(..., 4)` (the Step 7 site).
- `services/calc.py:214` `benchmark_rpi` → `round_dp(..., 2)`; consumed at `routes/packages.py:140` and copied unmodified to `package["reported_rpi"]` at `routes/packages.py:146`.
- `services/calc.py:220` `rpi_weighted` → `round_dp(..., 2)`; `calc.py:225` `rpi_simple_average` → `round_dp(..., 2)`.
- `routes/perf.py:74-75` — threshold comparisons use the already-rounded `achievement`/`weighted` Decimals (existing "compare the rounded figure" sentence stays accurate).
- `money.py:49-53` `as_json_number` + `grep -rn "as_json_number"` (`routes/perf.py:87-89`, `routes/budgets.py:279`, `routes/packages.py:140`, `services/core.py:421`) — emission is a plain `float(Decimal)`, so no second rounding step to describe.
- Money-side roundings (`rhu`/`ffloor` at `calc.py:62-64,73,77,103,107,122,135-136,146,198,206`) checked to confirm the new sentence does not bleed into them — it is explicitly scoped to ratios "instead of at whole cents", leaving the existing fee/cap sentences untouched.

(c) **Wording adjustment made:** two. (1) Phrased the mode as "the same half-up operation defined above, applied at the ratio's stated number of decimal places instead of at whole cents" rather than introducing a fresh rule — this keeps `Decimal.ROUND_HALF_UP`'s half-away-from-zero semantics correct for a **negative** `gop_achievement_pct`, which `calc.py:210` can produce when `actual_agop_cents` is negative while `prorated_cents > 0` (a naive "round 0.5 upward" phrasing would have mis-described that off-Step-7 path). (2) Scoped the claim to "every one of them" across the five named ratios rather than to `gop_achievement_pct` alone, since `money.py:38` is a single shared helper — narrowing it to the Step 7 field would have left the other four ratios' mode falsely open.

### Items with no edit
- **Item 3** (`working_capital_balance_cents` 3998999 → 3999999): `routes/claims.py:100-104` decreases the balance by exactly `owner_share_cents` and increases `manager_liability_accrued_cents` by `manager_share_cents`, matching §3.9 verbatim (and the `REVERSE` path at `claims.py:118-129` mirrors it). Pure test arithmetic slip — no PRD silence, no edit.
- **Item 4** (`_zero_baseline_hotel` fixture omission): `routes/budgets.py:254-267` sums the category budget line plus `AUTO_APPROVED`/`APPROVED` siblings and raises `ERR_VARIANCE_BASELINE_ZERO` on `baseline <= 0`, exactly §3.3's "not greater than zero". Pure fixture bug — no edit.
- **Items 1/2** beyond the rounding mode: the ratio's numerator/denominator (`actual_agop_cents` / `prorated_budget_agop_cents`) and `cure_payment_due_cents = max(0, prorated - actual)` at `routes/perf.py:107` already match §3.7 verbatim — only the mode needed pinning.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk (`102c102`), both files 457 lines. Confirmed minimal.

## Step 9: Complete PRD — 2026-09-03T01:42:38.241Z

`PRD_COMPLETED.md` is written.

- **Source**: `PRD_FINALIZED.md` — 457 lines, 102,333 chars (102,660 bytes)
- **Completed**: `PRD_COMPLETED.md` — 457 lines, 116,238 chars (116,618 bytes)
- **Char delta**: +13,905 (+13.6%); **line delta: 0** — every change is an in-paragraph insert or an in-place revision; no new sections, no new paragraphs, no added lines
- **Counts**: 32 ambiguity-pins (inserts), 6 mismatch-revisions, across 38 changes in 30 edited lines

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock time, independent of the logical clock, so it never coincides with a `created_at` — `response.py:20`, `timeutil.py:57`
- §2.2 — insert — ambiguity — three transport-level errors sit outside the §5 catalogue and the §2.8 ordering: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 400 — `app.py:52-61`
- §2.3 — insert — ambiguity — only `GET /hotel-management/budgets` validates pagination (unparseable values included); all other lists clamp/default silently; filter params are never validated and an unparseable numeric/boolean filter is discarded rather than matching nothing — `validate.py:156-212`
- §2.3 — insert — ambiguity — every `created_at` ASC ordering and every "strictly earlier"/"most recently created" comparison tie-breaks on an internal monotonic insertion counter that is never emitted — `db.py:96,121,128`
- §2.4 — insert — ambiguity — `to_iso8601` is normalised to three fractional digits; backward clock moves are accepted and sweep against the new value — `timeutil.py:28-41`, `db.py:60-65`
- §2.5 — insert — ambiguity — threshold comparisons use the exact rounded decimal; ratios are emitted as ordinary JSON numbers with no trailing-zero preservation — `money.py:38-52`
- §2.6 — revise — mismatch — the "three operations" are the three that bump `version` with no balance change; every other agreement-row mutation also bumps it once per request — `agreements.py:210`, `packages.py:495`, `perf.py:102`, `core.py:325`
- §2.7 — insert — ambiguity — `touch()` bumps a row at most once per request, and a row created by the request never leaves `version` 1 — `db.py:101-118`
- §2.8 rule 3 — insert — ambiguity — action-conditional required fields belong to rule 3 and precede the action enum check; `funded_amount_cents`/`adjusted_amount_cents` are deliberately unbounded there — `perf.py:150-151`, `disputes.py:128-133`, `clock.py:162`, `agreements.py:191`, `packages.py:274-275`
- §2.8 rule 18 — revise — mismatch — twelve → **thirteen** gated ops (adds `POST /agreements/{id}/employment-claims`), plus four widened `ACTIVE|CURE_PERIOD` gates (activate=DRAFT only; owner-review FINANCIAL, claim ALLOCATE, test terminate); all other writes ungated — `claims.py:34`, `agreements.py:124`, `packages.py:406`, `claims.py:83`, `perf.py:199`
- §2.8 rule 21 — insert — ambiguity — CONTEST's parent-package gate shares this error id but is the one declared departure from the absolute ordering, running after rules 29 and 32 — `packages.py:283-295`
- §2.8 rule 27 — insert — ambiguity — premature `ESCALATE_TO_FRANCHISOR` shares `ERR_INVALID_DISPUTE_STATE`, checked after the origin check and before rule 32 — `disputes.py:142-150`
- §2.8 rule 47 — insert — ambiguity — a negative `funded_amount_cents` fails here, not at rule 3 — `agreements.py:189-197`
- §2.8 rule 48 — insert — ambiguity — omission of `adjusted_amount_cents` fails rule 48; a non-integer value fails rule 3 — `packages.py:274-275,315-323`
- §2.9 — insert — ambiguity — `paid_amount_cents` opens at 0 on every accrual, including the `FINAL` true-up accrual — `core.py:278`
- §2.10 — insert — ambiguity — the clock is written before any sweep step runs, so all five steps evaluate against the new reading — `clock.py:165`
- §3.1 — insert — ambiguity — `incentive_tier2_pct`'s `>= incentive_fee_pct` floor validates supplied values only; the 0.15 default is written unchecked — `agreements.py:37-39`
- §3.1 — insert — ambiguity — activating a non-DRAFT agreement yields `ERR_AGREEMENT_NOT_ACTIVE` (409) at rule 18's position — `agreements.py:124-125`
- §3.1 — revise — mismatch — "twelve" → "thirteen" operational writes blocked from TERMINATED — `claims.py:34`
- §3.2 — insert — ambiguity — the deadlock branch records `decided_by_user_id` like the other two decision branches — `budgets.py:221`
- §3.2 — insert — ambiguity — a resubmission clears nothing: `decided_by_user_id` and `carryforward_applied` are retained — `budgets.py:158-177`
- §3.4 — insert — ambiguity — no `financial_status` gate on posting a chargeback; the post recomputes only the allocation, leaving fees, AGOP and accruals stale — `packages.py:184-224`
- §3.5 — insert — ambiguity — CONTEST outside {SUBMITTED, ACCEPTED} raises `ERR_INVALID_PACKAGE_STATE` after rules 29/32; the most recently created eligible accrual moves, and the step is skipped when none is eligible — `packages.py:242-248,283-301`
- §3.5 — revise — mismatch — REAFFIRM rewrites the accrual to the package's `allocated_centralized_cents` (not the charge's own share), runs no recompute, and is economically a no-op — `packages.py:304-312`
- §3.5 — insert — ambiguity — ADJUST hop 2 re-strikes sibling charges (a deferred sibling can be re-allocated upward); hop 3 rewrites the most recent non-REVERSED PROVISIONAL incentive accrual whatever its status, each rewrite skipped when no row exists — `packages.py:325-346`, `core.py:182-212`
- §3.6 — insert — ambiguity — owner-review FINANCIAL outside {ACTIVE, CURE_PERIOD} raises `ERR_AGREEMENT_NOT_ACTIVE` (409) ahead of the `financial_status` check — `packages.py:406-408`
- §3.6 — revise — mismatch — WAIVED_OFFSET tests the **post-restoration** balance against the floor, so a zero restoration still extinguishes the call; an `OVERDUE` call is never waived — `packages.py:497-501`
- §3.6 — insert — ambiguity — multiple INVOICED accruals in one bucket are paid greedily in `created_at` ASC with `min(remaining, amount)`; only accruals receiving more than zero move to PAID; the incentive bucket settles PROVISIONAL variants only — `packages.py:517-533`
- §3.6 — insert — ambiguity — a manually raised working-capital call accepts any of the three `reason` values; `auto_created` is the only field distinguishing it from a cascade-raised call — `agreements.py:160-167`
- §3.7 — revise — mismatch — rule 40 precedes rule 41: the budget is resolved and `ERR_BUDGET_NOT_APPROVED` raised before accepted periods are counted — `perf.py:44-55`
- §3.7 — insert — ambiguity — FAILED_CURABLE off a non-ACTIVE agreement skips the streak bump, the distribution hold and the freeze and does not write the agreement row; the TERMINATION_TRIGGERED increment is unconditional — `perf.py:109-122`
- §3.7 — insert — ambiguity — `cure_paid_cents` opens at 0 on every scored test — `perf.py:93`
- §3.7 — insert — ambiguity — PAY_CURE against a non-CURE_PERIOD agreement still records CURED and `cure_paid_cents` but performs no agreement-side effect — `perf.py:177-183`
- §3.7 — insert — ambiguity — terminate checks the agreement gate at rule 18's position, so `ERR_AGREEMENT_NOT_ACTIVE` outranks `ERR_INVALID_TEST_STATE` — `perf.py:199-201`
- §3.9 — revise — mismatch — the dispute list is filterable by `status` **and** `franchise_requirement_ref` — `disputes.py:110-115`
- §3.9 — insert — ambiguity — the ACTIVE|CURE_PERIOD gate belongs to `ALLOCATE` alone; `REVERSE` carries no agreement-status condition — `claims.py:82-116`
- §4 — insert — ambiguity — each action endpoint answers with the named resource, never a cascade-created row (owner-review→package, charge review→charge, round→dispute, allocation→claim, execute→distribution, fund→call, cure/terminate→test; benchmark and charge creates answer with the new row) — `packages.py:302,346,436,514`, `perf.py:184,221`, `disputes.py:220`, `claims.py:112`

Cross-checks performed at the end: every `ApiError` raise site in `routes/` and `services/` was enumerated and matched against a §5 catalogue entry plus a §2.8 rule position; rule 17 (stale version) correctly precedes rule 18 in both version-pinned writes; the true-up's target-package selection (highest `period_month`, insertion-order tie-break) was confirmed already pinned.

**Orchestrator verification:** `PRD_COMPLETED.md` is 457 lines / 116,618 bytes (vs 102,660 for `PRD_FINALIZED.md`); `diff` reports 35 modified lines and zero added/removed lines; all 5 top-level sections intact and the file still ends on the complete final row of the §5 error table. No truncation.

---

# Pipeline complete

All nine steps finished. Final state: 40 endpoints, 186 tests, 8/8 sweep rounds at 186/186, `PRD_COMPLETED.md` written.
