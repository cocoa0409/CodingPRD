# Worklog — task_0502_roundup_micro_investing

Scenario: 502. Round-Up Micro-Investing & Robo-Advisor (Acorns/Stash style): linked-card round-up & multiplier, recurring + found-money brand rebates, risk-tiered model portfolio & auto-rebalance, custodial (UTMA) & IRA buckets, withdrawal & tax-lot selection, tiered subscription fee, referral bonus, sweep-to-invest threshold

Difficulty tier: Expert (§0.4 scaffold-generator).

## Step 1: Create Task Directory — 2026-06-25T16:14:57.000Z

Pre-allocated directory `tasks/task_0502_roundup_micro_investing` (and `workspace/`) already existed; index-scan/auto-increment skipped per orchestration instruction. Verified directory and empty `workspace/` are present; `INSTRUCTION.md`, all `skills/`, and the `prd-bench-local-run` runner are available.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-25T16:40:37.000Z

All three scaffold artifacts are written and validated for task_0502_roundup_micro_investing.

**Scenario:** Round-Up Micro-Investing & Robo-Advisor (Acorns/Stash style) — generated fresh from the scenario description and the scaffold-generator skill spec only (no sibling tasks consulted).

**Counts (Expert tier):**
- **Entities: 13** — SubscriptionPlan, ModelPortfolio, FoundMoneyOffer, Account, LinkedCard, RoundUpAccrual, RecurringContribution, Bucket, Order, TaxLot, FoundMoneyReward, Referral, CashTransaction (flat topology, FK-linked)
- **Endpoints: 58** — above the 20-32 guideline, but the surface is transition-dense (35 POST/PATCH action endpoints for 7 state machines covering every scenario feature: round-up/multiplier, recurring, found-money, rebalance, UTMA/IRA, withdrawal/tax-lot, subscription fee, referral, sweep); the 22 GETs are all load-bearing for FK reverse-reachability + Not-Found coverage. Redundant config list GETs were trimmed.
- **Error codes: 26**
- **Calculation variants: 7 calculations / 11 variants** (≥3 required) — includes the FIFO-vs-HIFO withdraw dual-variant (realized gain 643 vs 1715 on identical inventory) and first-cycle-vs-steady-state subscription fee
- **State machines: 7, with cycles + parallel dimensions** — Account has two parallel independent dimensions (kyc_status × billing_status); Referral is cyclic (ISSUED→REDEEMED→ISSUED); Order branches (INVEST/WITHDRAW with divergent settle side-effects); RoundUpAccrual and FoundMoneyReward fork; Bucket is compound/aggregate
- 2 OCC concurrency rules (sequential, version-based); 4 RBAC roles

**Difficulty design:** 18 instances (9 rules × 2), all grounds resolve, all literals pre-computed and code-verified (FIFO 643, HIFO 1715, prorated fee 300/600, invest fee 25/net 9975, cascade net 499, percent cap 1000, etc.).

**Corner design:** 31 active instances + 2 `excluded_because` stubs across all 9 claim-extraction sections.

**Validation:** All three files parse as valid YAML; `scaffold_lint.py` returns `VERDICT: clean lint` (364 calls scanned, all FKs reverse-reachable); no forbidden concurrency vocabulary present.

One design note for downstream: `api_prefix` is set to `/` (root) because the flat topology gives each entity its own top-level collection rather than a single shared prefix — this is what makes the lint's reverse-reachability segment derivation resolve. A test-driving endpoint `POST /_lots/{id}/set_valuation` was added (alongside the mandatory `POST /_clock/set_current_utc` with default `2026-01-01T00:00:00Z`) to inject per-lot appreciation deterministically, since no business endpoint sets market valuation.

## Step 3: Copy Shared Files — 2026-06-25T16:41:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0502_roundup_micro_investing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T16:47:29.000Z

**Output:** `workspace/PRD.md` — 306 lines / 49866 bytes. Ends cleanly at §5 Error Code Catalogue (no audit footer).

### Major sections produced
- **§1 Introduction** (3 paragraphs: product framing, ledger/pricing-engine framing, precision-discipline framing)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Monetary Precision/Rounding, 2.6 Conservation Principle, 2.7 KYC Gate & Plan Entitlements, 2.8 OCC, 2.9 Validation Ordering & Nested Resolution, 2.10 Logical Clock
- **§3 Business Logic** (12 subsections): config, account two-dimensional lifecycle, billing mechanics, linked cards/round-up engine, sweep+threshold invest, buckets, order invest/withdraw lifecycle + tax lots, portfolio drift, recurring contributions, found-money rewards, referrals, reads/reverse-lookups
- **§4 Endpoint Definitions** (4-column table, 59 endpoints)
- **§5 Error Code Catalogue** (2-column table, 26 errors)

### Coverage relative to scaffold
- **Entities:** all 13. **Endpoints:** all 59 in §4; §3 path-purity clean. **Errors:** all 26 with correct HTTP statuses (incl. ERR_DUPLICATE_TIER, ERR_STALE_VERSION→412).
- **Calculations:** all 7 expressed in reconstructible prose (roundup_effective_amount; subscription_fee_charge dual-variant w/ ceil half-month; invest_settlement floor fee + IRA cap 700000; withdraw_settlement FIFO/HIFO/SPEC_ID per-lot floor; found_money_rebate FLAT/PERCENT-capped; sweep_and_threshold_invest round-per-accrual + inclusive threshold; bucket_drift max-deviation strict `>`).
- **State machines:** all covered — Account.kyc_status, Account.billing_status (PAST_DUE preconditions & cascades), RoundUpAccrual, Order branching, FoundMoneyReward, Referral cyclic-with-revert, Bucket.
- **Concurrency:** both OCC entries framed as stale-version guards (write_endpoint + occ_field + ERR_STALE_VERSION/412). **Validations:** all 25 priority rules surfaced; explicit priority ordering in §2.9.

### Hard Contract Reports — all PASS
- Field coverage: 76/76 entity fields, 6/6 endpoint request bits. Rule coverage: 25/25 validations, 2/2 OCC, all transitions, 7/7 calculations, sibling-branch symmetry OK. Path purity (§3): 148 tokens scanned, 0 slash/method/method+path violations.

### Confirmation
The two withheld design YAMLs (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, read, grepped, or referenced. Only `SCAFFOLD.yaml`, SKILL.md, `section-2.2-response-structure.md`, and `example-prd.md` were read.

## Step 5: Generate Unit Tests — 2026-06-25T17:18:10.000Z

**Test infrastructure generated for `task_0502_roundup_micro_investing`.**

### Test files: 6 (in `test_suite/`)
- `test_01_registration_and_config.py` — 7 tests
- `test_02_state_machines.py` — 9 tests
- `test_03_calculations.py` — 12 tests
- `test_04_business_rules.py` — 19 tests (verified 20 def test_)
- `test_05_cascades_and_invariants.py` — 14 tests (verified 13 def test_)
- `test_06_security_and_concurrency.py` — 6 tests

### Total test functions: 67
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered with ≥2 tests each (9 rules × 2 instances).
- **Queue B (Corner): 31 tests** — all 31 non-stub corner instances covered with ≥1 test each.

### Instances skipped under the PRD-first filter: 0 weakened/xfail/placeholder
Only the **2 `excluded_because:` corner stubs** were not translated (per contract — assertions owned by the cited difficulty instances; both cross-references resolve):
- `cross_cutting_complexity_layers/occ_sweep_stale_account_version_excluded` → owned by `transitive_cascade/sweep_threshold_cascade_cash_to_invest_to_lot_to_drift`
- `validations/kyc_gate_excluded` → owned by `priority_pair_validation_conflict/kyc_safety_beats_insufficient_cash_fiscal`

Every other instance passed both PRD-first conditions (PRD §3.1–§3.12 verbatim-covers and uniquely-derives each rule, error_id, threshold, side effect); no genuine gaps found.

### test_helpers/ files written (9):
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` — plus `test_suite/conftest.py`.

### Verification passed
- All files compile; all 6 modules import cleanly against `prd_bench_local_runner.testing` (barrel exports + 26-entry error-status map register).
- Verbatim PRD-citation audit: 0 failures across 76 quoted fragments — every docstring quote grep-matches `PRD.md`.
- Every docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold-leakage terms.
- Identity threading honored: `entity_backed` Investor/CustodialGuardian roles use `make_*_headers(account_id)` for ownership-gated calls.

### Key fixtures (in `fixtures.py`):
`setup_two_lot_inventory` (FIFO/HIFO divergence via `set_valuation` + clock), `setup_account_with_pending_accruals` + `run_sweep`, `setup_funded_invest_ready`/`fund_account_via_found_money` (cash funded via confirmed found-money since no direct deposit endpoint), `create_settled_invest_order`, `setup_referred_invested_redeemed` (referral qualification requires referred lifetime_invested ≥ 500).

## Step 6: Generate Implementation — 2026-06-25T17:18:10.000Z

Implementation complete. All 58 endpoints implemented, all modules compile cleanly, end-to-end smoke tests pass (sweep cascade, FIFO/HIFO withdraw gains 643/1715, subscription proration, IRA cap, OCC stale-version, referral payout conservation, offer-window overlap, contribution-day collision, restrict cascade, plan entitlements, fresh-boot state wipe).

**Framework / launcher:** Python 3 + Flask 3.0.3. `start.sh` is a foreground bash launcher that guards `pip install` on a cheap `import flask` probe, binds `0.0.0.0:$PORT` (default 10000), `exec`s `python3 app.py`. Ready ~2s. Storage in-memory only (plain dicts in `db.py`); fresh process wipes all state (confirmed by reboot test → 0 entities). No seeding.

**Source files (role each):**
- `start.sh` — guarded-install foreground launcher.
- `requirements.txt` — pins `flask==3.0.3`.
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/500 handlers.
- `db.py` — in-memory `Store` (one dict per entity), UUID + creation-sequence, logical clock (default `2026-01-01T00:00:00Z`, §2.10).
- `errors.py` — `ApiError` + 27-row error_id→HTTP-status catalogue (§5).
- `response.py` — success/error envelope (`meta`/`response_type`/`data`), `req_`-prefixed request id, ISO-8601-UTC-3-fractional-digit timestamps.
- `middleware.py` — `X-User-Role`/`X-User-ID` auth, RBAC, ownership, pagination parse, ISO-8601 parse (§2.1, §2.3, §2.9).
- `models.py` — entity construction, common system fields (`created_at`/`updated_at`/`version`), `touch` bump, serialization, derived-balance + bucket-drift recompute, cash-ledger helpers.
- `services/calc.py` — pinned calc rules (round-up, subscription fee, invest fee/net, lot market value, found-money rebate).
- `services/settlement.py` — invest/withdraw settlement (lot selection, realized gain) + sweep & threshold auto-invest.
- `routes/{config,accounts,cards,contributions,buckets,orders,rewards,referrals}.py` + `helpers.py` — the 58 endpoints.

**Endpoint count:** 58 distinct (method, path) — matches PRD §4 table.

**PRD ambiguities resolved (candidate Step 8/9 finalization sites):**
1. **Per-lot asset class for drift (§3.8).** Drift formula reads "market value of the bucket's open lots tagged to that class," but no field/endpoint tags a lot to an asset class. Resolution: attribute the bucket's entire open-lot market value to a single implicit class (first class in model's `target_allocation`). Reproduces every documented assertion (single-class 100% → `total_drift_bps==0`, empty bucket → 0).
2. **Derived-balance version bumps vs OCC (§2.4 vs §2.8).** §2.4 says recomputing a derived balance bumps owning entity `version`; OCC sweep test captures account version after `verify-kyc`, creates accruals, then sweeps against that captured version. Resolution: round-up accrual create/cancel updates `pending_roundup_cents` in place WITHOUT bumping account version; account version bumped only by explicit Account transitions (verify, restrict, charge-subscription, mark-past-due, sweep, close).
3. **No CashTransaction on invest settlement (§3.7 vs §2.6 conservation).** §2.6 says every cash credit/debit records a matching ledger row, but §3.7's invest narrative enumerates no row and there is no `INVEST` tx_type. Resolution: invest settlement writes no CashTransaction (literal to §3.7); withdraw, found-money, referral, subscription flows write their named rows.
4. **Qualify-referral failure error (§3.11).** When referred account's `lifetime_invested_cents < 500`, no dedicated error exists. Resolution: surface `ERR_INVALID_STATE` (priority-7 transition-not-permitted).

Validation ordering follows §2.9 / scaffold §1.4 priorities throughout (auth → role → ownership → existence → structural → pagination → state → KYC(9) → plan/beneficiary → temporal/fiscal → OCC(21)).

## Step 7: Run Tests and Iterate — 2026-06-25T17:21:21.000Z

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds passed cleanly — `passed=67 / total=67 / failed=0 / errors=0 / skipped=0` in every round. The test set was verified identical across all 8 rounds (same 67 test names), with real non-trivial per-test durations under `--isolation per-test-server` (server rebooted via `start.sh` before each test), so this is a genuine pass and not a degenerate/short-circuited run. No flakiness surfaced across the 8× concurrent load.

Orchestrator independently re-verified all 8 `results.{1..8}.json` files post-exit: every round 67/67/0/0/0.

**Tests deleted:** None — no test failed in any round, so no STEP 1 coverage / unique-derivability deletion was warranted.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

Note: subagent's first aggregation command produced misleading "FAIL" lines because it queried a nonexistent JSON key (`outcome`) instead of `status`; corrected aggregation confirmed every test passed. No artifacts were modified.

**Step 8 skip condition: MET** — Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. PRD.md already determined every behavior the implementation exhibits. Step 8 (PRD finalizer) is SKIPPED per orchestration rule; `PRD_FINALIZED.md` will not be produced. Step 9 proceeds from `PRD.md`.

## Step 8: Finalize PRD — SKIPPED — 2026-06-25T17:21:21.000Z

Skipped per orchestration skip condition (Step 7 = 0 iterations beyond baseline; 0 deletions / 0 test_suite / 0 test_helpers / 0 implementation fixes). `PRD_FINALIZED.md` was not produced. Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-06-25T17:29:00.000Z

**Source vs. completed:**
- `PRD.md`: 306 lines, 49,866 chars
- `PRD_COMPLETED.md`: 306 lines (unchanged line count), 55,615 chars
- Char delta: **+5,749**. All 12 changes are in-paragraph revisions (no new lines/paragraphs/sections).

**Counts:** ambiguity-pins: **6**, mismatch-revisions: **6** (total 12).

**Per-change bullets:**
- §2.1 (RBAC) — revise — mismatch — PRD claimed registration & config reads are auth-exempt and X-User-ID only "for roles that require it"; impl requires both headers (non-empty X-User-ID for all four roles incl. Anonymous/PlatformAdmin) on every endpoint, registration needs `Anonymous` token, config reads need a non-anonymous role — no header-free public surface — `middleware.py:37-46`, `routes/accounts.py:35`, `routes/config.py:57`.
- §2.4 (Versioning) — revise — mismatch — PRD said recomputing any derived balance bumps owner version/updated_at; impl bumps bucket views only when a value changes and never bumps account version/updated_at for `pending_roundup_cents` recompute (account version advances only via enumerated Account transitions) — `models.py:49-66,100-111`.
- §2.6 (Conservation/Ledger) — revise — mismatch — PRD implied every cash credit/debit writes a `CashTransaction` across all 7 tx_types; impl writes rows only for `SUBSCRIPTION_FEE`, `REFERRAL_BONUS`, `FOUND_MONEY`, `WITHDRAW_PROCEEDS`, never `MANAGEMENT_FEE`/`SWEEP_DEBIT`/`CONTRIBUTION_DEPOSIT` (invest debit & sweep credit adjust cash with no row) — `services/settlement.py:63-66,171`.
- §3.2 (Registration) — insert — ambiguity — PRD said email must be unique but didn't pin the error; impl returns `ERR_INVALID_REQUEST` for duplicate email and `ERR_NOT_FOUND` for unresolved plan/portfolio ids — `routes/accounts.py:46-52`.
- §3.5 (Sweep) — insert — ambiguity — PRD left "primary taxable bucket" undefined and silent on the no-bucket case; impl uses the earliest-created OPEN `TAXABLE` bucket, creates the auto-invest order directly SUBMITTED→SETTLED (bypassing OCC), leaves cash in buffer when no OPEN taxable bucket exists; single account-version bump regardless of outcome — `services/settlement.py:180-219`, `routes/accounts.py:206-208`.
- §3.6 (Bucket views) — revise — mismatch — PRD described `ytd_ira_contributed_cents` as "within the current contribution year"; impl is a monotonic running total of settled net principal, never reset by any year boundary — `services/settlement.py:70-71`.
- §3.7 (Order create) — revise — mismatch — PRD said withdrawals "use `MANUAL`" and `lot_selection_method` "required for a withdrawal"; impl stores any supplied `source` verbatim for both kinds (no coercion) and treats `lot_selection_method` as optional even for withdraws (defaults FIFO), storing it/null verbatim for INVEST — `routes/orders.py:42-58`.
- §3.7 (Invest settlement) — insert — ambiguity — pinned invest cash debit writes no ledger row (no `MANAGEMENT_FEE`), opened lot MV = net principal at open (gain ratio 0), `realized_gain_cents`=0, cash-sufficiency (`ERR_INSUFFICIENT_CASH`) precedes IRA-cap check — `services/settlement.py:33-73`.
- §3.8 (Drift) — insert — ambiguity — PRD referenced per-class "tagged" lot MV with no tagging mechanism; impl attributes entire open-lot MV to the first `target_allocation` key (insertion order) — `models.py:114-145`.
- §3.9 (Recurring contributions) — insert — ambiguity — PRD said `next_run_at` = clock "plus the cadence" without durations; impl uses DAILY +1d, WEEKLY +7d, MONTHLY +30d, never advances the schedule (no runner), never writes `CONTRIBUTION_DEPOSIT` — `routes/contributions.py:22-26,52`.
- §3.11 (Referral qualify) — insert — ambiguity — PRD didn't pin the error when referred account `lifetime_invested_cents` < 500; impl rejects with `ERR_INVALID_STATE` (also for non-REDEEMED) — `routes/referrals.py:131-135`.
- §3.12 (Reads/lists) — insert — ambiguity — PRD didn't state owner-scoping on reads/lists; impl rejects cross-owner read-by-id with `ERR_NOT_RESOURCE_OWNER` and narrows Investor/Guardian list results to caller's own resources (PlatformAdmin sees all), `total_count` reflecting the scoped+filtered set — `routes/*.py` get/list handlers (e.g. `routes/orders.py:82,102-103`, `routes/cards.py:61,76-77`).

Note: tests used only as auxiliary cross-reference; the implementation was the sole alignment authority.

---

## PIPELINE COMPLETE

All 9 steps finished. Final task state:
- Scaffold (3 YAML files), PRD.md, PRD_COMPLETED.md (no PRD_FINALIZED.md — Step 8 skipped).
- 67 tests across 6 files; 58-endpoint Python/Flask implementation.
- Final 8-round parallel stability sweep: **67/67 passing in all 8 rounds**, zero deletions / zero fixes.
