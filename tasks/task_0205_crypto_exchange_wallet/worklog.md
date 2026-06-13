# Worklog — task_0205_crypto_exchange_wallet

Scenario: Cryptocurrency Exchange & Custodial Wallet: account/KYC tiers, market/limit order book, deposit/withdrawal whitelist, network-confirmation hold, maker/taker fee, balance & cost-basis (1099-DA), staking rewards, travel-rule compliance

Difficulty: Expert (§0.4 Expert calibration band) — applied to Step 2 scaffold-generator only.

## Step 1: Create task directory — 2026-06-06T16:29:10.000Z

Pre-allocated directory `tasks/task_0205_crypto_exchange_wallet` confirmed (Step 1 auto-scan skipped per instruction). `workspace/` subdirectory already present. No new directory created.

## Step 2: Generate scaffold (Expert) — 2026-06-06T17:01:00.000Z

All three scaffold artifacts generated, lint-clean, self-consistent. `scaffold_lint.py` verdict: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability (572 calls scanned, 50 endpoints, 12 entities). Forbidden-vocabulary scan clean; all grounds resolve; no name collisions across §1.8+§1.9; all `excluded_because` stubs reference existing §1.8 instances.

Scaffold counts (Expert band):
- Entities: 12 (Account, AssetConfig, FeeSchedule, Balance, WithdrawalAddress, Deposit, Withdrawal, TravelRuleRecord, Order, Trade, CostBasisLot, StakingPosition)
- State machines: 6 (Account — parallel kyc_status × account_status with REJECTED→PENDING cycle; Deposit — confirmation hold; WithdrawalAddress; Withdrawal — cyclic screening + travel-rule hold + resubmit; Order — parallel fill axis OPEN→PARTIALLY_FILLED→FILLED; StakingPosition)
- Calculations: 7 (order_book_match_selection, realized_gain_on_disposal FIFO/HIFO, trade_fee maker/taker, order_reserve_amount, account_30d_taker_volume round-then-sum, staking_reward_accrual, daily_withdrawal_usd_used)
- Validations: 22 (priority-ordered, 8 categories)
- Endpoints: 50 (incl. single-resource GETs for FK reverse-reachability, filtered lists, action endpoints, one /_clock test-driving endpoint)
- Errors: 23
- Roles: 4 (Anonymous, Trader [entity_backed:Account], Operator [opaque], ComplianceOfficer [opaque]; segregation_of_duties model)
- Concurrency rules: 2 (OCC on Account.version)

§1.8 Difficulty Design: 9 rule_ids × 2 = 18 instances (all nine Difficulty Rules; each instance distinguished per §0.5).
§1.9 Corner Design: 8 sections, 40 instances (35 full test recipes + 5 excluded_because stubs).
All formula-derived assertions computed in code and pinned as literals (FIFO/HIFO lot depletion, maker 40.00 / taker 120.00, reserve 42126.00 / 40120.00, round-then-sum 300.03, staking 2.50000000, daily-limit 1600>1000).

Files: SCAFFOLD.yaml (918 lines, no design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1517 lines, key scaffold_difficulty_design), SCAFFOLD_CORNER_DESIGN.yaml (1443 lines, key scaffold_corner_design). All verified.

## Step 3: Copy INSTRUCTION.md — 2026-06-06T17:01:37.000Z

Copied ./INSTRUCTION.md → tasks/task_0205_crypto_exchange_wallet/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T17:07:23.000Z

PRD generated at workspace/PRD.md (294 lines). Neither design file read (confirmed by subagent — only SCAFFOLD.yaml, skill spec, §2.2 fixed block, example PRD were read).

Major sections: §1 Introduction; §2 Global Specs (2.1 RBAC/4 roles, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Props & Ledger Clock, 2.5 Cascading Reconciliation, 2.6 Balance Partitioning, 2.7 Precision/Rounding, 2.8 OCC, 2.9 Nested/Filtered Retrieval, 2.10 Validation Ordering); §3 Business Logic (11 subsections: KYC progression, account freeze, asset/fee config, deposit hold, withdrawal whitelist, withdrawal screening + travel-rule SoD, settlement + daily ceiling, order place/reserve/match cascade, fees + rolling taker volume, cost-basis FIFO/HIFO, staking accrual/unbonding); §4 Endpoints (50, 4-col); §5 Error Catalogue (23 IDs, 2-col).

Hard Contracts all PASS: Contract 1 field-name coverage (72 entity fields + 49 endpoint identifiers + 1 OCC field, 0 missing); Contract 2 rule coverage (23 states, both OCC rules with expected_*_version/ERR_STALE_*/HTTP 412, dual-variant FIFO/HIFO + maker/taker prose, validation priority chains, cascade side-effects, half-open vs closed window distinction); Contract 3 §3 path purity (496 backtick tokens, 0 paths/methods leaked).

## Step 5: Generate unit tests — 2026-06-06T17:22:18.000Z

7 test files, 71 tests total. Queue split: 36 from queue A (Difficulty) + 35 from queue B (Corner).
- test_01_accounts_kyc.py (11) — account create/defaults/computed, KYC progression, RBAC + auth
- test_02_assets_pagination.py (3) — asset immutability, pagination range, spot-price patch
- test_03_deposits_balances.py (5) — deposit→lot seeding, confirmation boundary, balance listing
- test_04_withdrawals.py (16) — whitelist hold/overlap, screening, travel-rule, daily ceiling, reject/resubmit, conservation invariant, SoD
- test_05_orders_matching.py (26) — reserve nesting, maker/taker fees, fills, freeze/cancel cascades, OCC, order validations, derived reconciliation
- test_06_cost_basis.py (4) — FIFO/HIFO divergence, depth-4 trade cascade
- test_07_staking.py (6) — reward accrual, zero-claim boundary, cooldown overlap, release-before-cooldown

Coverage: all 18 Difficulty instances → exactly 2 tests each (36); all 35 non-stub Corner instances → ≥1 test each. 5 instances skipped — all the excluded_because Corner stubs (no test_recipe; cited Difficulty instance owns the assertion); each cross-reference verified to resolve. No PRD-filter skips.
test_helpers/ files (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py. All 71 tests collect under pytest against the real prd_bench_local_runner framework.

## Step 6: Generate implementation — 2026-06-06T17:22:18.000Z

Python + Flask, blueprint-per-resource, decimal.Decimal throughout (ROUND_HALF_UP, ROUND_CEILING for reserves). Storage purely in-memory — Store holds one dict per entity collection keyed by UUID. No SQLite, no disk persistence, no seeded data (fresh boot returns total_count=0). start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec, guarded pip install.

Files: start.sh, requirements.txt (Flask==3.0.3), app.py, db.py, clock.py, errors.py, numeric.py, response.py, auth.py, serializers.py, services/ (common.py, pagination.py, fees.py, cost_basis.py, matching.py, orders.py), routes/ (accounts.py, assets.py, deposits.py, withdrawal_addresses.py, withdrawals.py, orders.py, staking.py, ledger.py). 51 routes register, app imports cleanly.

Design note from impl subagent: non-fiat deposits always transit DETECTED→CONFIRMING (crediting held) on first confirmation regardless of delta size, since the state machine defines no non-fiat DETECTED→CREDITED edge; reaching CREDITED requires a subsequent advance from CONFIRMING.

## Step 7: Run tests and iterate — 2026-06-06T17:39:12.000Z

All clean. The benchmark passes every test across two consecutive 8-round parallel stability sweeps. (Orchestrator re-verified independently with a fresh 8-round sweep: all 8 rounds 71/71, failed=0.)

**Iterations run:** 3 sweep iterations. Baseline 35/71 → after batch 1 (logic + fixture fixes) 70/71 with load-induced connection-reset flakiness → after batch 2 (server-robustness + boot-latency fixes) a clean 71/71, confirmed across two consecutive 8-round parallel sweeps (16 rounds total, all 71/71, runner exit 0).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule that uniquely determined its expected outcome; all failures were genuine fixture/implementation/infrastructure bugs, not PRD-silence or non-derivable assertions.

**Fixes applied to test_helpers/:**
- `factories.py` — `usd_asset_payload` / `btc_asset_payload` / `eth_asset_payload`: changed from passing named defaults alongside `**overrides` (which raised `TypeError: got multiple values for keyword argument 'symbol'/'required_confirmations'` whenever a test overrode those fields) to a defaults-dict-then-`.update(overrides)` merge so overrides win cleanly. Fixed ~6 tests.
- `fixtures.py` — `create_and_credit_deposit`: the shared funding helper did a single confirmation advance and expected the deposit CREDITED. Per PRD §3.4 (and the scaffold state machine) a non-fiat deposit always passes through CONFIRMING on the first advance (credits `held_amount` only), and a *subsequent* advance reaching `required_confirmations` crosses to CREDITED. Changed to two advances (enter CONFIRMING, then reach the threshold). This was the dominant root cause — ~28 setup steps were leaving funds in `held` and then failing with `ERR_INSUFFICIENT_AVAILABLE`.

**Fixes applied to test_suite/ (setup-only, assertions unchanged):**
- `test_03_deposits_balances.py::test_deposit_creates_lot_with_correct_unit_cost` — single advance → two advances (PRD §3.4 two-step credit).
- `test_01_accounts_kyc.py::test_operator_cannot_screen_withdrawal` — single BTC advance → two advances so the withdrawal under test is actually funded.

**Fixes applied to implementation/:**
- `routes/orders.py` (`place_order`) — order-shape violations (missing/zero `limit_price`, `MARKET` carrying a price, non-positive `quantity`) were raising `ERR_KYC_TIER_INSUFFICIENT`. PRD §3.8 reserves `ERR_KYC_TIER_INSUFFICIENT` for the tier failure only and routes order-shape failures to "the order-shape rejection described next," i.e. `ERR_INVALID_ORDER`. Changed those four checks to `ERR_INVALID_ORDER`; the TIER_0 tier-gate path still raises `ERR_KYC_TIER_INSUFFICIENT` (verified by `test_trading_below_tier1_rejected`).
- `app.py` — switched the WSGI server from the single-process Werkzeug dev server to **waitress** (with a Flask dev-server fallback). The dev server dropped connections under 8x concurrent per-test reboots, surfacing as `ConnectionResetError` and whole 0/0 rounds. `requirements.txt` adds `waitress==3.0.0`.
- `start.sh` — the hot path ran a `python3 -c "import ..."` probe on every one of the 71×8 reboots, doubling interpreter-start cost under contention and pushing some boots past the runner's 15s restart window (spurious "could not be restarted"). Gated the one-time dependency install behind a cheap filesystem sentinel so the reboot hot path is just `exec python3 app.py`; also reduced the waitress thread pool to 4 and enabled `_quiet`. No API behavior changed — purely boot-latency/robustness.

**Note on storage:** No seeding or on-disk entity persistence was introduced. The `.deps_installed` sentinel is a build/dependency marker only (empty file), not entity data; in-memory storage still starts empty on every boot.

## Step 8: Finalize PRD — 2026-06-06T17:43:13.000Z

NOT skipped (Step 7 had non-zero test_helpers/test_suite/implementation fixes). PRD_FINALIZED.md created as a verbatim copy of PRD.md (294 lines, 0% delta, diff empty/IDENTICAL).

After full investigation of both candidate items against implementation/, no PRD edits warranted — PRD already pins both behaviors uniquely and correctly:
- (a) Non-fiat deposit two-step CONFIRMING→CREDITED credit semantics — PRD §3.4 (line 149) already specifies the two-step flow verbatim; impl (routes/deposits.py:108-140) matches. The Step 7 change was a pure fixture bug fix, not PRD silence. No edit.
- (b) Order-shape vs KYC-tier error routing — PRD §3.8 (line 179) already reserves ERR_KYC_TIER_INSUFFICIENT for the tier failure and routes order-shape failures to ERR_INVALID_ORDER (named in next sentence); impl (routes/orders.py:71-93) now matches. The Step 7 change was an impl bug fixed to match PRD, not PRD silence. No edit.

Remaining Step 7 items (factories.py kwargs merge, app.py waitress swap, start.sh sentinel, test_suite setup-step counts) are pure fixture/infra fixes with no PRD consequence → no edit. Per-edit pre-edit NO-NEW-MISMATCH enumeration was performed for both candidate subjects (deposit confirm cascade incl. fiat/non-fiat/orphan branches + lot creation; order place_order full check chain + amend_order parallel shape checks + matching liquidity path); all enumerated impl paths consistent with existing PRD prose, so no widening needed.

## Step 9: Complete PRD — 2026-06-06T17:49:55.000Z

Full PRD-vs-implementation/ completeness scan (always runs). Source PRD_FINALIZED.md (294 lines, 50,461 chars) → PRD_COMPLETED.md (294 lines, 52,565 chars; char delta +2,104; all edits in-paragraph, no new lines/sections).

Counts: 10 ambiguity-pins, 3 mismatch-revisions (13 total edits).

Changes:
- §2.2 — insert — ambiguity — api_request_timestamp is real server wall-clock, not ledger clock — response.py:14-17
- §2.3 — insert — ambiguity — present-but-unparseable limit/offset rejected with ERR_VALIDATION — services/pagination.py:12-16
- §2.8 — insert — ambiguity — amend applies only to OPEN/PARTIALLY_FILLED LIMIT (else ERR_INVALID_STATE), optional limit_price/quantity validated (ERR_INVALID_ORDER), re-reserves worst-case (ERR_INSUFFICIENT_AVAILABLE), re-runs matching — routes/orders.py:177-246
- §3.1 — insert — ambiguity — duplicate email on registration → ERR_INVALID_REQUEST — routes/accounts.py:37-38
- §3.3 — insert — ambiguity — duplicate asset symbol → ERR_INVALID_REQUEST — routes/assets.py:44-45
- §3.3 — insert — ambiguity — duplicate fee tier_name → ERR_INVALID_REQUEST — routes/assets.py:93-94
- §3.4 — insert — ambiguity — fiat deposit credit increments confirmations by supplied delta — routes/deposits.py:110
- §3.6 — insert — ambiguity — HOLD on a non-travel-rule withdrawal → ERR_INVALID_STATE — routes/withdrawals.py:188-189
- §3.8 — revise — mismatch — MARKET-BUY best ask spans OPEN or PARTIALLY_FILLED resting SELL LIMITs with unfilled reserved qty (PRD said only OPEN) — services/matching.py:18-29
- §3.8 — insert — ambiguity — MARKET order leftover cancelled regardless of time_in_force — routes/orders.py:144-148
- §3.8 — insert — ambiguity — TRADE_BUY lot unit_cost_usd = fill notional_usd ÷ filled base qty; disposal proceeds = that fill's notional_usd — services/matching.py:185-187
- §3.9 — insert — ambiguity — fee_tier falls back to TIER_BASE (zero rates) when no schedule row qualifies — services/fees.py:47-69
- §4 — revise — mismatch — KYC application POST returns 201 Created (exception to modify→200 rule) — routes/accounts.py:107

Implementation/ and tests untouched by Step 9 (doc-only patch); the verified clean 8-round sweep (71/71 × 8) remains valid.

---

## PIPELINE COMPLETE

All 9 steps finished. Final state: 71/71 tests passing across an independently-verified 8-round parallel stability sweep (per-test-server isolation). Deliverables: SCAFFOLD.yaml + 2 design indices, workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files) + test_suite/ (7 files, 71 tests), workspace/implementation/ (Flask, in-memory, start.sh).
