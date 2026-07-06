# Worklog — task_0723_donut_bagel_shop

## Step 1: Create task directory — 2026-06-30T00:00:00.000Z

Pre-assigned task directory `tasks/task_0723_donut_bagel_shop` (with `workspace/` subdir) used as-is. No index scan / auto-increment performed (three sibling pipelines running concurrently; rescan would collide). {task_dir} = tasks/task_0723_donut_bagel_shop for all steps.

## Step 2: Generate scaffold (Expert) — 2026-06-30T00:00:00.000Z

**Task:** `task_0723_donut_bagel_shop` — Donut & Bagel Shop (retail + wholesale), **Expert** difficulty.

**Archetype/profile:** Ledger reconciliation × Pricing engine; hybrid topology; posture-driven state shape (ProductionDay gates child ops); peer_roles RBAC; immediate consistency. Layers: dual-variant calc, cascading side effects, optimistic concurrency, rate/threshold triggers, derived-field reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 9** — Product, ProductionDay, BakeBatch, RetailOrder, LoyaltyAccount, WholesaleAccount, StandingOrder, WholesaleDelivery, PreOrder.
- **State machines: 6** — ProductionDay (OPEN→BAKING→SELLING→CUTOFF→RECONCILED, OCC-guarded reconcile), BakeBatch (PLANNED→BAKED→MARKED_DOWN→SWEPT, branching), RetailOrder (CART→PAID→{VOIDED,REFUNDED}, branching + compensation), WholesaleDelivery (SCHEDULED→PICKED→DELIVERED→INVOICED / CANCELLED), PreOrder (REQUESTED→CONFIRMED→FULFILLED / CANCELLED), WholesaleAccount (ACTIVE↔SUSPENDED cycle). **1 concurrency rule** (reconcile-stale-day OCC, 412).
- **Calculations: 10** — line_price (tiered dozen/bulk), markdown_price, retail_order_total (reward redemption), loyalty_punch (threshold auto-convert), wholesale_delivery_amount (sum-then-round), preorder_deposit (catering threshold), reconcile_day (forward expected vs chronological actual, dual-variant), wholesale_outstanding_balance, catering_slot_overlap (half-open aggregate capacity), route_window_overlap (closed + buffer).
- **Validations: 15** (priority-ordered: auth→authz→existence→request→day-state→target-state→temporal cutoff→standing-order-state→account-suspended→route-overlap→catering-slot→markdown-stock→stock→credit→deposit→reconcile-preconds→OCC).
- **Endpoints: 53** (incl. reverse-reachability GETs for all 10 FKs and a `/_clock/set_current_utc` test endpoint; default clock 2026-03-01T00:00:00Z). api_prefix `/`.
- **Errors: 27.**
- **Roles: 5** — ShopAdmin (opaque, superset), BakeManager (opaque), Cashier (opaque), RouteDriver (opaque), WholesaleClient (entity_backed:WholesaleAccount).

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 = **18 instances** (all 9 Difficulty Rules satisfied; all asserts pre-computed literals).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **41 instances** total = **34 active** corner tests + **7 `excluded_because` stubs** (spanning entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

**`scaffold_lint.py` verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (53 endpoints, 9 entities, 18 §1.8 + 34 §1.9 instances, 345 calls scanned). No duplicate instance names; all stub `difficulty_instance` references resolve.

## Step 3: Copy shared files — 2026-06-30T00:00:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0723_donut_bagel_shop/workspace/INSTRUCTION.md. (Done early, ahead of Step 2 completion, since it is scaffold-independent.)

## Step 4: Generate PRD — 2026-06-30T00:00:00.000Z

Generated `workspace/PRD.md` — **289 lines**, complete prose PRD for Donut & Bagel Shop (Ledger-reconciliation archetype).

**Sections:** §1 Introduction (production-day spine); §2 Global Specs (10 subsections: RBAC/5 roles, response envelope, pagination, identity/timestamps/versioning, cents/round-half-up, nested addressing, validation ordering 1–6, cascades/compensation, OCC, logical clock); §3 Business Logic (9 entity-lifecycle subsections); §4 Endpoint table (all 53 incl. `/_clock`); §5 Error table (all 27).

**Hard Contracts — all PASS:** Contract 1 field coverage 51/51; Contract 2 rule coverage (all transitions, 9 calcs with constants embedded — MARKDOWN_PCT 40%, REWARD_VALUE 1200, PUNCHES_PER_REWARD 10, CATERING_THRESHOLD 4050, DEPOSIT_PCT 25%, SLOT_CAPACITY 2, ROUTE_BUFFER 30 — all 27 error ids in prose); Contract 3 §3 path purity (342 backtick tokens, 0 slash-paths/bare methods).

**Notable decisions:** wholesale sum-then-round worked example (285×0.85→242 vs 243); deposit threshold boundary (4050→1013, 4035→0); catering slots half-open; route windows closed + 30-min buffer (strictly >30 min apart); tiered line pricing three-branch order (marked-down → inclusive bulk → dozen+remainder); void/refund equal density with refund's absence of day-status precondition stated explicitly. Both withheld design files not read.

## Step 6: Generate implementation — 2026-06-30T00:00:00.000Z

Built Python + Flask in-memory implementation at `workspace/implementation/`.

**Files (7):** `start.sh` (foreground, reads `$PORT` default 10000, binds 0.0.0.0, guarded pip install, `exec python3 app.py`); `requirements.txt` (flask==3.0.3); `app.py` (app factory, per-request meta hook, error handlers); `core.py` (in-memory Store dicts, starts empty no seeding, response envelope, auth X-User-ID/X-User-Role, pagination default 10/min 1/max 100, Decimal round-half-up, logical clock default 2026-03-01T00:00:00Z); `calc.py` (line_price tiered, markdown 40%, wholesale sum-then-round, preorder_deposit ≥4050→25%, loyalty accrual/reversal); `serialize.py`; `routes.py`.

**Endpoints implemented: 56** (all PRD §4 rows incl. `/_clock/set_current_utc`).

**Verified live:** validation precedence; tiered pricing (qty13→1650, qty24→2880); markdown 150→90/175→105; wholesale 242 vs 243; deposit 4050→1013/4035→0; route 30-min buffer; catering half-open cap 2; loyalty auto-convert + redemption min(1200,subtotal); void compensation symmetry; credit-limit 402; WholesaleClient ownership 403; clock past-cutoff; reconcile dual-variant (expected 7500, waste 2000, variance 5500) + OCC 412; invalid-window 422.

**PRD ambiguities resolved:** (1) standing-order pause/resume invalid-state → `ERR_STANDING_ORDER_NOT_ACTIVE` (409); (2) WholesaleClient collection GETs filtered to own account, single-resource non-owner → `ERR_FORBIDDEN_ROLE` (403); (3) amount_cents int ≥0 (neg→422), outstanding balance may go negative on overpay; (4) retired-product `active` guard enforced on create paths (no retire endpoint exists, so always true currently).

## Step 5: Generate unit tests — 2026-06-30T00:00:00.000Z

**test_helpers/** (9 files): types.py, api_client.py (one method/endpoint), api_errors.py (27 error IDs + HTTP status map), assertions.py, factories.py (GLAZED/EVERYTHING/SESAME canonical specs), constants.py, test_users.py (opaque-role shared constants + make_wholesale_client_headers for entity_backed role), fixtures.py (composite tiers: SELLING-day-with-baked-batch, loyalty-at-9-punches, account+standing-order, delivered/invoiced delivery, cutoff/reconciled day), __init__.py.

**test_suite/** (conftest + 7 files): test_01_pricing_and_calculations, test_02_loyalty_cascade, test_03_wholesale_ledger, test_04_scheduling_windows, test_05_reconciliation, test_06_state_machines, test_07_crud_rbac_listing.

**Test counts: 70 functions = 36 queue A (Difficulty) + 34 queue B (Corner).**

**Coverage (audited):** Queue A all 18 difficulty instances ≥2 tests each (two wholesale amount_cents==242 instances each got 2nd distinct-angle test). Queue B all 34 non-stub corner instances ≥1 test, 0 missing/0 extras. All 7 excluded_because stubs correctly NOT translated; 7 stub cross-refs resolve.

**Instances skipped: none** — every non-stub instance passed PRD-first two-condition filter (literal expected values copied from design YAMLs). Citations verified: every docstring ends with exactly one Design: line + ≥8-word PRD substring surviving literal grep. No skip/xfail markers. 70 collected under pytest, zero import/syntax errors. Tests not executed (no impl at gen time).

## Step 7: Test and iterate to green — 2026-06-30T00:00:00.000Z

**Iterations run:** 2 (1 diagnostic sweep + 1 verification sweep).

**Failing set (identical across all 8 rounds of iteration 1):** 6 tests, all `AssertionError: Expected 200, got 201`. Root-caused to two issues against PRD §2.7 line 198 verbatim: *"Newly created resources are returned with HTTP 201; all other successful operations, including every state transition and every read, return HTTP 200."*

**Tests deleted:** none. Both layers traced cleanly to PRD prose.

**Fixes applied to implementation/:**
- `routes.py`, `record_payment()` — changed success status `201` → `200`. Recording a wholesale payment is a mutation returning the *updated* WholesaleAccount, not a new resource, so per PRD line 198 must return 200. Fixed `test_payment_lowers_outstanding_balance_to_pre_invoice` and `test_invoice_then_partial_then_full_payment_zeroes_balance` (test_03_wholesale_ledger.py).

**Fixes applied to test_suite/:**
- `test_04_scheduling_windows.py` (helper `_paused_standing_order_with_clock` @131, `test_schedule_after_cutoff_clock_active_so_rejected` @188) and `test_05_reconciliation.py` (`test_version_increments_after_start_baking` @160) — these called `validate_success(_ac.create_production_day(...))` with default expected 200, but `create_production_day` is genuine creation → 201 per PRD line 198 (impl correct). Changed each to `validate_success(..., 201)`. Fixed `test_schedule_past_cutoff_with_paused_so_returns_cutoff_error`, `test_schedule_past_cutoff_not_standing_order_error`, `test_schedule_after_cutoff_clock_active_so_rejected`, `test_version_increments_after_start_baking`.

**Fixes applied to test_helpers/:** none.

**Final counts:** 70/70 passed in all 8 rounds (verified via results.{1..8}.json). All 8 green.

## Step 8: Finalize PRD — 2026-06-30T00:00:00.000Z

(Not skipped — Step 7 had 1 implementation fix + test_suite fixes.)

**Line counts:** PRD.md = 288 → PRD_FINALIZED.md = 288 lines (0% line delta, single in-place revision of line 198). Chars 42,941 → 43,709 (+768, +1.8%).

**Changes (1 edit):**
- §4 (line 198) — revise — Clarified 201-vs-200 rule: enumerated the nine genuine create endpoints returning 201, pinned that recording a wholesale payment (`POST /wholesale-accounts/{id}/payments`) and recording a pre-order deposit (`POST /pre-orders/{preOrderId}/deposit`) are NOT creation — each returns 200 with updated parent resource. — implementation/routes.py:698 (record_payment→200), routes.py:1033 (deposit_preorder→200).

**Pre-edit search log:** subject = which POSTs are creation (201) vs ledger-movement mutations (200); enumerated all `return ok(...,201)` callsites (routes.py:95,154,291,415,594,635,724,850,993 = nine creators), record_payment (687-698, 200), deposit_preorder (1022-1033, 200), ok() helper (core.py:133 default 200), clock-set (1095, 200), §2.4 entity list; wording scoped to the nine §2.4-entity create endpoints so it neither over-claims every POST is 201 nor under-claims state-transitions/clock-set. test_suite create_production_day→201 fixtures were pure fixture bugs already consistent with the clarified rule, needing no separate pin.

## Step 9: Complete PRD — 2026-06-30T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` (minimal patch over PRD_FINALIZED.md), full PRD-vs-implementation scan.

**File metrics:** lines 288 → 288 (unchanged, all in-paragraph edits); chars 43,709 → 47,098 (+3,389).

**Counts:** ambiguity-pins 12, mismatch-revisions 2, total 14 changes.

**Changes:**
- §2.3 Pagination — insert — ambiguity — limit/offset out-of-range clamped (not rejected); non-integer → ERR_INVALID_REQUEST — core.py:191-207
- §2.1 RBAC — insert — ambiguity — ownership mismatch → ERR_FORBIDDEN_ROLE (403), after existence (404 wins if absent) — routes.py:53-55
- §2.1 RBAC — insert — ambiguity — WholesaleClient collection lists silently pre-scoped to own account; account-/standing-order-nested lists apply 403 ownership check — routes.py:732-733, 859-860, 1001-1002, 651-652, 759
- §2.7 window note — insert — mismatch — window well-formedness checked at step 4 (ahead of day/target-status); unparseable → ERR_INVALID_REQUEST — routes.py:809-815
- §2.4 versioning — revise — ambiguity — version begins at 1 — core.py:110
- §2.9 reconcile — insert — ambiguity — expected_production_day_version must be present+integer (ERR_INVALID_REQUEST), checked before day-status/version-match — routes.py:225-227
- §2.10 clock — insert — ambiguity — to_iso8601 must be parseable; set unconditional, accepts earlier instants (non-monotonic) — routes.py:1090-1094
- §3.1 catalogue — insert — ambiguity — duplicate sku → ERR_INVALID_REQUEST (422) — routes.py:81-82
- §3.1 catalogue — insert — ambiguity — pricing/cost/threshold fields must be true integers — routes.py:70-77
- §3.1 catalogue — insert — ambiguity — invalid allergen member → ERR_INVALID_REQUEST — routes.py:78-80
- §3.1 catalogue — insert — ambiguity — retired-product add → ERR_INVALID_REQUEST (422) after existence; no retire/update endpoint — routes.py:42-46, 281-282
- §3.2 day — insert — ambiguity — duplicate business_date → ERR_INVALID_REQUEST; delivery_cutoff_utc must be parseable — routes.py:139-144
- §3.3 batch bake — revise — mismatch — fixed check order: baked_qty presence → day BAKING → batch PLANNED → baked_qty≥1 (ERR_INVALID_BAKE_QTY) — routes.py:331-338
- §3.3 batch plan — insert — ambiguity — par_qty integer ≥0 (ERR_INVALID_REQUEST) — routes.py:279-280
- §3.5 loyalty — insert — ambiguity — duplicate phone → ERR_INVALID_REQUEST (422) — routes.py:588-589
- §3.6 ledger — insert — ambiguity — payment amount_cents integer ≥0; unbounded (may go negative); no ACTIVE requirement — routes.py:693-696
- §3.8 pre-order deposit — insert — ambiguity — deposit amount_cents integer ≥0; may exceed deposit_due_cents — routes.py:1029-1031
- §3.8 confirm — revise — mismatch — check order REQUESTED → day-not-RECONCILED → deposit-met — routes.py:1041-1047

Passages already uniquely pinning impl (tiered pricing eval order, sum-then-round, loyalty accrual/auto-convert/reversal, markdown, reconcile formulas+gate order, invoice credit-check order, refund no day-state precond, route-window buffer, catering half-open overlap, 201-vs-200) left unchanged.

---

**Pipeline complete (Steps 1–9).** All 8 sweep rounds green at 70/70.
