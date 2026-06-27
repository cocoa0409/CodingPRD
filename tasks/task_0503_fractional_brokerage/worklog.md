# Worklog — task_0503_fractional_brokerage

Scenario: 503. Commission-Free Fractional Brokerage (Robinhood style): instant deposit & buying power, dollar-based fractional order, market/limit & extended-hours, dividend reinvestment (DRIP), options approval levels, settlement (T+1)/PFOF routing, margin & pattern-day-trader rule, 1099-B & cost basis

Difficulty tier: Expert (§0.4 scaffold-generator) — applied only in Step 2.

## Step 1: Create Task Directory — 2026-06-25T16:14:58.000Z

Pre-allocated directory `tasks/task_0503_fractional_brokerage` with `workspace/` subdir already existed; index-scan/auto-increment/mkdir logic skipped per orchestration instructions. Verified directory + workspace/ present, project root `/Users/uni/Desktop/吉/project/custom_prd_bench`, `prd-bench-local-run` on PATH at `/Users/uni/.local/bin/prd-bench-local-run`.

## Step 2: Generate Scaffold — 2026-06-25T16:46:32.000Z

Generated the Expert-tier scaffold for **task_0503_fractional_brokerage** (Commission-Free Fractional Brokerage, Robinhood style). All three files written and pass `scaffold_lint.py` with **VERDICT: clean lint**.

**Structural counts (Expert band §0.4):**
- **Entities: 12** (Account, Security, Deposit, Order, Fill, Settlement, Position, Lot, Disposal, DividendEvent, OptionsApproval, MarginCall) — in band (10–15).
- **Endpoints: 34** — 2 over the soft 32 guideline, justified by the domain's rich lifecycle surface (8 state machines × distinct action endpoints) and FK reverse-reachability obligations; flat topology with `api_prefix: /`, filtered-list + Account/Position sub-resource reverse-reachability for all 12 FKs.
- **Error codes: 26** — in band (18–30).
- **Calculations: 10** with **4 explicit variants** (cost_basis FIFO/AVERAGE on Position/Lot; buying_power CASH/MARGIN on Account) plus 8 more calcs (instant_credit, options_suitability, drip_reinvest, order_required_cash, pfof_routing, pdt_day_trade, maintenance_excess, window_overlap) — exceeds 3+ requirement.
- **State machines: 8** — includes cycles and parallel dimensions: Account.trading_status (cyclic posture ACTIVE↔RESTRICTED↔MARGIN_CALL↔FROZEN), Order.order_status × Settlement.status (parallel T+1 dimension), DividendEvent (branching PAID→{REINVESTED,REVERSED}), OptionsApproval (branching), MarginCall (branching/reopen), plus Deposit and Lot. Exceeds 4+ with cycles/parallel.
- **Concurrency rules: 2** (OCC on Account.version for order placement and options decisions); **18 validations**; **4 roles** (peer_roles: AccountHolder entity_backed, ComplianceOfficer/ClearingSystem/MarketData opaque).

**Design files:**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: **18 instances** (all 9 rule_ids × 2), each with verified literal asserts (FIFO pl=6000 vs AVG pl=5600; CASH bp=500000 vs MARGIN bp=1000000; DRIP residual=2; PDT equity exactly 2500000 → not flagged; instant cap headroom boundary; margin deficiency=200000; etc.).
- `SCAFFOLD_CORNER_DESIGN.yaml`: **35 active instances + 1 `excluded_because` stub** across 8 taxonomy sections (entities, state_machines, calculations, validations, errors, rbac, endpoints, cross_cutting_complexity_layers, consistency_model).

All formula-derived assertions were computed in code (decimal round_half_up / truncate-to-6dp) before being pinned as literals. All `${var}` placeholders close to earlier `captures:`, OCC versions reference `${var}` from prior reads, and all FKs have reverse-reachability GETs. All three required files written.

Orchestrator verification: SCAFFOLD.yaml=1328 lines (no design-key leakage), SCAFFOLD_DIFFICULTY_DESIGN.yaml=1102 lines (1 top-level key), SCAFFOLD_CORNER_DESIGN.yaml=1173 lines (1 top-level key).

## Step 3: Copy Shared Files — 2026-06-25T16:46:54.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0503_fractional_brokerage/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T16:53:10.000Z

**PRD generated:** `workspace/PRD.md` — **266 lines** (51167 bytes).

**Sections covered:**
- **Entities (12):** Account, Security, Deposit, Order, Fill, Settlement, Position, Lot, Disposal, DividendEvent, OptionsApproval, MarginCall — all 76 entity field names present; `common_fields: false` entities (Security, Fill) noted as carrying only `id`/`created_at`.
- **State machines (8):** Account.trading_status (4-state compound posture, first-match priority), Order.order_status, Settlement.status, Deposit.status, DividendEvent.status (branching reinvest loop), OptionsApproval.status, MarginCall.status (revert/reopen), Lot.status — every transition rendered with preconditions paired to error IDs and side-effect cascades.
- **Calculations (8):** cost_basis_disposal (FIFO vs AVERAGE), buying_power (CASH vs MARGIN), instant_credit (cap headroom + inclusive boundary), options_suitability, drip_reinvest (pinned truncate-then-round), order_required_cash/PFOF rebate, pfof_routing (venue scoring + tie-break), pdt_day_trade (rolling window + exact boundaries), maintenance_excess, window_overlap (half-open dividend vs closed-upper margin) — round-half-up stated 15×.
- **Validations (18):** priority-ordered in §2.7 + distributed across §3 workflows, each paired with error ID and applies_to scope.
- **Endpoints (34):** 4-column table (Method, Path, Description, Authorized Roles).
- **Errors (26 catalog):** 2-column table; all 26 IDs mentioned in §2/§3 narrative with trigger conditions.
- **RBAC:** 4 roles (AccountHolder entity-backed; ComplianceOfficer/ClearingSystem/MarketData opaque); X-User-ID/X-User-Role headers + auth error IDs.

**Hard contracts:** Field coverage PASS (76/76 fields, 39/39 request bodies, OCC field present); Rule coverage PASS (18/18 validations, 2/2 OCC rejections, all 8 state machines, 8/8 calculations, 26 error IDs, cascades, sibling-branch symmetry); Path purity PASS (0 paths/methods in §3 backticks).

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/grepped/referenced. Orchestrator verified both design files retain on-disk timestamp Jun 26 00:44 (PRD written 00:51).

## Step 5: Generate Unit Tests — 2026-06-25T17:17:38.000Z

**Test files:** 8 test files in `test_suite/` (plus `conftest.py`)
- `test_01_cost_basis_and_cascades.py`, `test_02_buying_power_and_account.py`, `test_03_combinatorial_calcs.py`, `test_04_margin_and_posture.py`, `test_05_priority_and_boundaries.py`, `test_06_dividends_and_compensation.py`, `test_07_orders_and_validations.py`, `test_08_rbac_concurrency_settlement.py`

**Total test functions:** 71
- **Queue A (Difficulty):** 36 tests — all 18 difficulty instances covered with ≥2 tests each
- **Queue B (Corner):** 35 tests — all 35 non-stub corner instances covered with ≥1 test each

**Design instances SKIPPED:** 0 skipped for PRD-coverage reasons. PRD uniquely-derives every asserted outcome. The single `excluded_because:` stub (`account_frozen_blocks_order`) correctly NOT translated — its cross-reference resolves to a real difficulty instance owning the FROZEN-block assertion.

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py` (one method per all 34 endpoints), `api_errors.py` (26 codes + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (`make_account_holder_headers(account_id)` for entity-backed AccountHolder), `fixtures.py` (funded CASH/MARGIN accounts, buy/sell-and-fill, position-with-lots, margin-in-deficiency, margin-with-issued-call, position-with-paid-dividend, options-approval lifecycle).

**Audits passed:** all files byte-compile + import cleanly against framework stub; every test has exactly one `Design:` tag resolving to a real instance; every docstring carries verbatim ≥8-word PRD citation grep-confirmed; no skip/skipif/xfail; no scaffold-references in emitted code.

## Step 6: Generate Implementation — 2026-06-25T17:17:38.000Z

**Stack:** Python + Flask, in-memory storage only.

**Source files written (under `workspace/implementation/`):**
- Top-level (12): `start.sh` (reads `$PORT`, binds `0.0.0.0`, `exec`s foreground, guards pip install on flask import check), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory `Store` dicts + logical clock at 2026-01-01T00:00:00Z), `errors.py` (26-entry catalog), `response.py` (meta/response_type/data envelope, req_ ids, 3-digit ISO ts), `middleware.py` (X-User-Role/X-User-ID auth, RBAC, AccountHolder ownership), `models.py`, `money.py` (Decimal round-half-up, bps, 6dp share truncation), `constants.py`, `timeutil.py`.
- `routes/` (12): common, accounts, deposits, securities, orders, settlements, positions, dividends, options, margin, clock, __init__.
- `services/` (7): account (equity/maintenance/buying-power/PDT/posture recompute), order (placement, fills, day-trade detection), position (lots + FIFO/AVERAGE cost basis), routing (PFOF), settlement (T+1 sweep + fail compensation), margin (liquidation force-sells), __init__.

**Endpoint count: 34** (exact match to PRD §4 table; verified via url_map).

**Storage:** Pure in-memory Python dicts in a single `Store` instance. No SQLite/disk/tmp/JSON dump. No `seed_*` functions, no entity data at import/startup — fresh boot returns total_count:0 for every collection; restart wipes all state.

**start.sh:** reads `$PORT` (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`. Booted cleanly; default logical clock confirmed (deposit settles_on = 2026-01-02T00:00:00.000Z, no wall-clock leakage).

**Design note:** `cost_basis_method` (Position, source:input, pinned at first open) has no dedicated creation endpoint (Positions created implicitly by BUY fills), so order body accepts optional `cost_basis_method` (default FIFO) — the only API-reachable mechanism to exercise the AVERAGE variant.

## Step 7: Run Tests and Iterate — 2026-06-25T17:53:36.000Z

**Outcome: CLEAN FIRST SWEEP — 0 iterations beyond baseline.**

The 8-round parallel stability sweep was run once as a single foreground blocking command (all 8 rounds launched concurrently, joined with `wait`). Every round read independently afterward.

- **8-round sweep result:** all 8 rounds `passed == total == 71` (failed=0, errors=0, skipped=0 in every round; per-round duration ≈47.4s). Authoritative per-test status union across all 8 `results.{1..8}.json`: zero non-passing entries.
- **Iterations run:** 1 (the baseline sweep; no fix-and-rerun cycle was needed).
- **Tests deleted (PRD-silence / unique-derivability):** 0. No test failed in any of the 8 rounds, so the diagnostic protocol (STEP 0–3) found no failing test to subject to the PRD coverage + unique-derivability filter.
- **Fixes applied to `test_helpers/`:** 0.
- **Fixes applied to `test_suite/`:** 0.
- **Fixes applied to `implementation/`:** 0.

PRD.md already uniquely determined every behavior the implementation exhibits that the suite exercises — the full 71-test suite passed deterministically across 8 concurrent rounds with no flakiness signal.

## Step 8: Finalize PRD — SKIPPED — 2026-06-25T17:53:36.000Z

**Skip condition met.** Per the skill's Step 8 skip rule: Step 7 exited on the FIRST 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). Therefore `PRD.md` already determined every behavior the implementation exhibits, and the PRD finalizer subagent was NOT spawned. No `workspace/PRD_FINALIZED.md` is produced. Step 9 will start from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-25T17:58:00.000Z

Full PRD-vs-`implementation/` scan produced `workspace/PRD_COMPLETED.md` (PRD_FINALIZED.md absent, so started from `PRD.md`). Subagent summary (verbatim):

```
Source: workspace/PRD.md (PRD_FINALIZED.md absent)
PRD.md: 266 lines, 51167 chars
PRD_COMPLETED.md: 266 lines, 53609 chars
char-delta: +2442

Counts: ambiguity-pins=6, mismatch-revisions=1 (7 changed paragraphs)

Changes:
- §2.3 Pagination — insert — ambiguity — pinned out-of-range clamping (limit<1→1, >100→100, offset<0→0) and missing/non-integer fallback to default, vs PRD stating only min/max — routes/common.py:26-47 (paginate/_parse_int)
- §3.2 Securities and Market Data — insert — ambiguity — pinned that `required_options_level` must be one of 0/1/2/3 else ERR_INVALID_REQUEST (PRD gave only the default) — routes/securities.py:41-44
- §3.3 Placing an Order — insert — ambiguity — pinned the optional `cost_basis_method` (FIFO|AVERAGE, default FIFO) order-body input, not echoed on the order resource, applied by the opening fill to pin Position.cost_basis_method, FIFO/AVERAGE-only else ERR_INVALID_REQUEST; PRD §3.5 named the position field but never said how it is set — routes/orders.py:82-84,111 + services/order.py:65
- §3.5 Executions/lifecycle — insert — ambiguity — pinned the order's target quantity: quantity order → submitted quantity; notional order → notional_cents / reference price (limit_price for LIMIT else last_price at acceptance), truncated toward zero at 6dp; fixed once at acceptance; completion uses a 6dp tolerance — services/order.py:29-39, 87
- §3.6 Settlement leg fail — revise — mismatch — PRD said fail reverses "the provisional cash and position effects of the originating fill"; impl always reverses unsettled cash but reverses the position effect only for a DEBIT/BUY leg (deletes the lot it opened, matched by original qty + still fully OPEN), leaving a CREDIT/SELL leg's disposals and lot consumption un-unwound — services/settlement.py:35-82
- §3.9 PDT day-trade detection — insert — ambiguity — pinned the precise "closing fill" definition: SELL closes only when prior position qty>0, BUY covers only when prior qty<0; an opening BUY (qty≥0) or fresh-short SELL never triggers; increment is one per matching closing fill, stopping at first match — services/order.py:135-172
- §3.9 Margin-call liquidation — insert — ambiguity — pinned that each forced fill sells a whole position's quantity at current last_price_cents, one position at a time rechecking excess, skipping non-positive-price securities, with synthetic fills carrying no order_id and pfof_rebate_cents 0, each spawning a CREDIT T+1 settlement leg — services/margin.py:17-88
```

Orchestrator verification: `PRD_COMPLETED.md` present (266 lines, 53609 bytes, +2442 chars), 7 in-paragraph changed lines (no new sections/paragraphs), `PRD_FINALIZED.md` correctly absent. Pipeline complete.
