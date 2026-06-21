# Worklog — task_0386_general_retail_pos_inventory

## Step 1: Create Task Directory — 2026-06-17T02:48:51.000Z

Created `tasks/task_0386_general_retail_pos_inventory/` and `tasks/task_0386_general_retail_pos_inventory/workspace/` (pre-assigned path, index not auto-computed). Scenario: General Retail POS & Inventory. Difficulty band: Expert.

## Step 2: Generate Scaffold — 2026-06-17T03:12:00.000Z

Generated a complete Expert-band scaffold at `tasks/task_0386_general_retail_pos_inventory/`. All three files pass `scaffold_lint.py` with **VERDICT: clean lint** (345 §1.8/§1.9 calls scanned, all conform to §1.5; all FKs have reverse-reachability).

**Complexity profile:** Quota/allocation primary + Pricing-engine secondary; hybrid→flat topology; parallel state-machine shape; peer_roles; immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation.

**SCAFFOLD.yaml dimensions:**
- **11 entities** — Store, Product, InventoryItem, LoyaltyAccount, Promotion, CashDrawerSession, Sale, TenderLine (immutable, common_fields:false), Layaway, Transfer, CountSheet
- **7 state machines** — Store.posture (LOCKED↔DRAWER_OPEN), CashDrawerSession (with force-close cascade), Sale.settlement_status × Sale.stock_status (true **parallel** dimensions), Layaway (**cyclic** ACTIVE↔DELINQUENT), Transfer (**branching fork** DISPATCHED→{RECEIVED,REJECTED}), CountSheet
- **3 concurrency rules** — OCC on Sale/Layaway/Transfer version (expected_*_version, 412)
- **7 calculations** — sale_total_pricing (sum-then-round tax pinned), return_value_provisional_vs_final (dual variant), loyalty_points_earned (earn vs clawback dual variant), loyalty_tier_recompute, cash_reconciliation, inventory_available_and_reorder, store_posture
- **16 validations** (priority-ordered), **18 error codes**, **48 endpoints** (incl. `/_clock/advance` and `/_loyalty/grant` test-driving), **4 roles** (StoreManager/Cashier/InventoryClerk opaque, Customer entity_backed:LoyaltyAccount)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** all 9 Difficulty Rules × **2 instances = 18 total**, differentiation honored; all formula asserts pre-computed literals.

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **37 instances** (34 active + 3 `excluded_because` stubs) spanning all 9 claim-extraction-guide sections.

All grounds references resolve, no duplicate instance names, no forbidden concurrency vocabulary, keys correctly isolated.

## Step 3: Copy INSTRUCTION.md — 2026-06-17T03:13:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_0386_general_retail_pos_inventory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-17T03:18:56.000Z

Generated `workspace/PRD.md` (292 lines, 28 section headings) for General Retail POS & Inventory API (Expert band). §2 has 10 subsections (RBAC, verbatim envelope, pagination, common properties, nested retrieval, precision, OCC, drawer posture, inventory accounting, cascading reversal); §3 has 13 workflow subsections; §4 endpoint table (4 cols); §5 error catalogue (2 cols).

**Hard Contracts — all PASS:** Contract 1 field coverage 76/76; Contract 2 rule coverage (16 validations, 3 OCC rules, all state machines, 7 calculations, 18 error IDs); Contract 3 path purity (443 backtick tokens, 0 paths/methods in §3). §2.2 verbatim envelope confirmed.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate Unit Tests — 2026-06-17T03:45:00.000Z

NOTE: First Step 5 subagent crashed mid-response (API connection closed, 0 tokens recorded) leaving a partial `test_helpers/` (7 of 9 files) and empty `test_suite/`. SendMessage is unavailable in this environment, so a fresh Step 5 subagent was spawned to regenerate the complete, self-consistent test infrastructure.

**Test helpers (`test_helpers/`)** — 9 files. Prior partial files (api_client.py, api_errors.py, assertions.py, constants.py, factories.py, test_users.py, types.py) verified correct against PRD and retained; 3 missing files created: `fixtures.py` (28 composite setup helpers built only from PRD-declared endpoints), `__init__.py` (barrel export), `test_suite/conftest.py` (pytest fixture bridge, one fixture per role).

**Test suite (`test_suite/`)** — 5 files, **70 tests**:
- test_01_pricing_and_settlement.py (10), test_02_loyalty_and_returns.py (7), test_03_state_machines_and_cascades.py (16), test_04_inventory_transfers_layaways.py (13), test_05_validations_crud_rbac_concurrency.py (24)

**Queue A (Difficulty)** — all **18/18** instances translated, each ≥2 tests (36+ tests). None skipped.
**Queue B (Corner)** — all **34/34 non-stub** instances translated (1 test each). The 3 `excluded_because` stubs (sale_parallel_dimensions_corner, tax_rounding_order_corner, drawer_not_open_corner) NOT translated. Nothing skipped — every instance passed the PRD-first two-condition filter.

**Audits passed:** all files byte-compile; every docstring ends with exactly one verbatim `Design:` tag resolving to a real instance; all citation quotes verbatim in PRD.md (0 non-verbatim); every test_helpers import resolves; all 48 `api.<method>()` calls map to real ApiClient methods; conftest fixtures align with TEST_USERS; no scaffold/section-reference leakage.

Notable nuance handled: corner instance `non_cash_overtender_rejected` has prose in `distinguishing_aspect` (3300/3219) contradicting its own `setup_api_calls`/`assert` (CARD 2500 vs total 2000) — generator followed canonical setup_api_calls+assert per skill (PRD-consistent, §3.5 ERR_OVERTENDER).

## Step 6: Generate Implementation — 2026-06-17T03:45:00.000Z

Generated complete Python + Flask implementation in `workspace/implementation/` (26 files). Launcher `start.sh` (reads $PORT default 10000, binds 0.0.0.0, foreground via exec, guards pip install on cheap flask import), requirements.txt. Core: app.py, db.py (in-memory store), errors.py (18-code catalogue), response.py (envelope), middleware.py (auth/RBAC), common.py. Routes (11): stores, cash_sessions, products, inventory_items, count_sheets, loyalty, promotions, sales, layaways, transfers, clock. Services (5): inventory, loyalty, pricing, posture, sale_ops.

**Endpoints: 48 implemented** — exactly matching PRD §4 table. Behaviors traced to PRD prose: response envelope, auth/RBAC (4 roles, Customer ownership), validation priority order (§3.13), pricing engine (six pinned steps, sum-then-round half-up tax), dual-variant refund (provisional per-unit floor vs final basket-delta), loyalty earn/clawback with tier multipliers (SILVER 1.25, GOLD 1.50, inclusive 1000/5000 thresholds, lifetime never decremented), parallel state machines (settlement_status × stock_status), cash reconciliation, layaway cyclic ACTIVE↔DELINQUENT with clock sweep, branching transfers with shrinkage, force-close cascade (void→tender-reversal→restock→loyalty-restore), OCC on tenders/layaway-payments/transfer-dispatch (412).

**Storage confirmation:** in-memory only (Python dicts in db.py, wiped on each process start). No seeding — cold start.sh boot returns total_count: 0 for all collections; reboot test confirmed state fully wipes.

## Step 7: Test-Iterate-Fix Loop — 2026-06-17T04:07:37.000Z

All 8 parallel rounds pass cleanly: 68/68 in every round (was 70 tests with 3 failing; 2 deleted, 1 fixed → 68 tests, all passing). The two deletions and one fix are stable across all rounds.

**Iterations run:** 2 (initial sweep surfaced 3 stable failures; one fix + two deletions cleared them; confirming sweep passed 68/68 in all 8 rounds). Initial sweep showed a consistent (non-flaky) 67/70 in every round.

**Tests deleted (2):**
- `test_second_open_cash_session_per_store_rejected` (test_04) — **STEP 1b ERROR-CHOICE-SILENCE**. Asserted `ERR_DUPLICATE_RESOURCE` for opening a second cash session while one is `OPEN`. PRD §2.8 verbatim covers the constraint ("A store enforces at most one session in `OPEN` or `CLOSE_REQUESTED` at a time") but never names the error_id for the violation. PRD §3.13 scopes `ERR_DUPLICATE_RESOURCE` to "uniqueness collisions" (store code, sku, barcode, inventory-item pair, promo code, loyalty phone — not the cash-session singleton). A faithful PRD-only reader naturally treats this as a state constraint → `ERR_INVALID_STATE` (what impl returns). Scaffold rule: `Difficulty/resource_temporal_overlap/cash_session_singleton_occupation_overlap_per_store`; scaffold left the constraint as a bare note with no error_id.
- `test_second_session_blocked_while_first_close_requested` (test_04) — same ERROR-CHOICE-SILENCE pattern, same scaffold rule (second open blocked while first is `CLOSE_REQUESTED`).

**Fixes applied to `test_suite/` (1):**
- `test_05_validations_crud_rbac_concurrency.py` :: `test_dispatch_received_transfer_rejected` — **STEP 2 TEST BUG**. Intends to assert `ERR_INVALID_STATE` for re-dispatching an already-`RECEIVED` transfer, but its fixture re-dispatched with the post-dispatch version while `receive` had bumped the version. Per PRD §3.13 ("ERR_STALE_VERSION is evaluated next, ahead of the general state-transition check"), the OCC guard correctly fired first → `ERR_STALE_VERSION`. Fixed the fixture to capture the version returned by `receive` and re-dispatch with the current version, so the request actually exercises the out-of-state transition it claims to test.

**Fixes applied to `implementation/`:** none. The implementation was PRD-correct in all three cases (returns `ERR_INVALID_STATE` for the cash-session singleton; correctly enforces STALE-before-STATE precedence for transfers).

**Final state:** 68/68 tests passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-06-17T04:09:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **Line counts:** PRD.md = 292, PRD_FINALIZED.md = 292 (net 0 lines; single in-line insertion, ~0.34% of lines touched).

**Changes (1):**
- §2.8 The Drawer Posture Principle — *insert* — pinned the error_id for the cash-session singleton violation: opening a second session for a store that already has one in `OPEN` or `CLOSE_REQUESTED` is rejected with `ERR_INVALID_STATE` (explicitly "not as a uniqueness collision") — `implementation/routes/cash_sessions.py:40-41`.

**Pre-edit search log (Edit 1):** (a) subject = error returned when "at most one OPEN/CLOSE_REQUESTED session per store" is violated by an open attempt. (b) Grepped routes/ + services/ for OPEN, CLOSE_REQUESTED, singleton, posture, DRAWER_OPEN, LOCKED; constraint enforced in exactly one place (`cash_sessions.py:20-26` helper called from open_session at :40-41 → ERR_INVALID_STATE). Confirmed parallel paths do NOT raise this error: posture_for_store (services/posture.py:13-18) only derives, never raises; other drawer transitions raise ERR_INVALID_STATE only for own wrong-status guards; inventory_items.py:36 is a different uniqueness constraint → ERR_DUPLICATE_RESOURCE. (c) Scoped clause narrowly to the open-endpoint path; added "(not as a uniqueness collision)" to stay consistent with §3.13 ERR_DUPLICATE_RESOURCE scoping.

**No PRD edit needed:** the test_dispatch_received_transfer fix was a pure fixture bug; impl correctly enforces STALE-before-STATE at transfers.py:94-97, already uniquely determined by PRD §2.7 + §3.13.

## Step 9: Complete PRD — 2026-06-17T04:16:05.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`. Lines: 292 → 292 (every edit in-paragraph; no new sections). Chars: 46,897 → 49,742 (+2,845). **12 paragraphs revised** across §3.1, §3.2, §3.3, §3.4, §3.5, §3.9, §3.10, §3.11: **11 ambiguity-pins + 1 mismatch-revision** (§3.9 layaway create — impl can fulfill at creation when initial deposit clears the balance, contradicting unconditional "ACTIVE").

**Per-change list:**
- §3.1 (products) — revise — ambiguity — discontinuing a non-ACTIVE product → ERR_INVALID_STATE — routes/products.py:85
- §3.1 (inventory) — insert — ambiguity — reorder_point/reorder_qty non-negative, default 0; default 0 makes fresh item below_reorder:true — routes/inventory_items.py:27-28,47
- §3.2 (cash session) — insert — ambiguity — new session carries counted_cash_cents/variance_cents as null until reconcile — routes/cash_sessions.py:46-47
- §3.3 (sale create) — insert — ambiguity — lines non-empty, positive quantity, unknown line product_id → ERR_REFERENCE_NOT_FOUND; resource echoes lines with assigned 1-based line_no; cash_session_id null until first tender — services/sale_ops.py:28-46, routes/sales.py:25-37,106-108,256-257
- §3.4 (promotions) — revise — ambiguity — disabling a non-ACTIVE promotion → ERR_INVALID_STATE — routes/promotions.py:66
- §3.4 (promo apply) — insert — ambiguity — promo_code resolved by code (not FK); unknown code → ERR_PROMO_NOT_APPLICABLE — services/sale_ops.py:102-112
- §3.5 (settlement) — insert — ambiguity — positive-total_due EXCHANGE settles on the SALE at-least rule — routes/sales.py:273-280
- §3.9 (layaway create) — revise — mismatch — initial_deposit_cents may not exceed total (ERR_INVALID_REQUEST); missing InventoryItem → ERR_REFERENCE_NOT_FOUND; deposit clearing balance fulfills at creation (FULFILLED + stock drawdown) — routes/layaways.py:47-77
- §3.9 (layaway deposit) — insert — ambiguity — deposit amount_cents strictly positive, not exceeding balance_cents (ERR_INVALID_REQUEST), after OCC and state — routes/layaways.py:145-148
- §3.10 (transfer create) — insert — ambiguity — received_qty null until receive — routes/transfers.py:41
- §3.10 (transfer receive) — insert — ambiguity — out-of-range received_qty → ERR_INVALID_REQUEST; missing destination item → ERR_REFERENCE_NOT_FOUND (after DISPATCHED check) — routes/transfers.py:119-125
- §3.11 (count sheet) — insert — ambiguity — counted_qty non-negative; variance_qty null until post computes — routes/count_sheets.py:26,35-36

**Deliberately not changed:** negative-total_due refund convention already pinned by §3.5/§3.7; one local quirk (reconcile checks state before required counted_cash_cents, inverting §3.13's global order) left unpinned — rare combined-error only, untested, broad/risky to globally revise.

---

## Pipeline complete — 2026-06-17T04:16:05.000Z

All 9 steps done. Final: 68/68 tests passing across 8 parallel stability rounds. Task artifacts complete: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (5 files, 68 tests), workspace/implementation/ (Flask, 48 endpoints, in-memory).
