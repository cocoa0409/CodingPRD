# Worklog — task_0472_hardware_lumber_yard

Scenario: 472. Hardware Store & Lumber Yard (Ace style): SKU & bin/aisle, lumber by-the-foot & cut, rental & propane exchange, key-cutting/paint-mix service, contractor account & net terms, special order & vendor drop-ship, loyalty & co-op buying, inventory/reorder

## Step 1: Create Task Directory — 2026-06-22T11:34:48.000Z

Pre-allocated directory `tasks/task_0472_hardware_lumber_yard` confirmed to exist with empty `workspace/` subfolder. No index scan performed (fixed directory per orchestration instructions to avoid ID collisions with concurrent runs).

## Step 2: Generate Scaffold (Expert tier) — 2026-06-22T12:00:09.000Z

Everything checks out. The scaffold meets the Expert tier (13 entities [10-15], 63 endpoints [≥20-32, well above — the extra GETs are reverse-reachability + read endpoints required by the FK lint, not padding], 25 errors [18-30], 3 calc variants [3+], 5 state machines [4+] with a cyclic SpecialOrder, parallel-dimension SalesOrder, and branching ServiceTicket).

All three files parse, the lint is clean (304 calls, all conform to §1.5; all 13 FKs reverse-reachable), all 9 difficulty rules have exactly 2 instances (18 total), 37 active corner instances + 5 exclusion stubs, zero forbidden concurrency vocabulary, every error triggerable and referenced, and no `scaffold_difficulty_design`/`scaffold_corner_design` keys leaked into SCAFFOLD.yaml.

## Summary

Generated the three Expert-tier scaffold artifacts for **task_0472_hardware_lumber_yard** (Hardware Store & Lumber Yard, Ace-style). All files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0472_hardware_lumber_yard/`.

**Complexity profile:** quota/allocation (finite inventory + credit pool) × pricing-engine secondary; layers = cascading side effects, dual-variant calculation, derived-field reconciliation, optimistic concurrency; hybrid topology; parallel state-machine shape; peer-roles. `api_prefix: /` (flat multi-resource API), logical clock default `2026-01-01T00:00:00Z`.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **13 entities:** Vendor, Product (SKU + bin/aisle + EACH/BY_FOOT + reorder), ContractorAccount, SalesOrder, OrderLine, Invoice, RentalAsset, RentalAgreement, ServiceStation, ServiceTicket, SpecialOrder, PurchaseOrder, LoyaltyLedger (append-only event log).
- **5 state machines:** SalesOrder (parallel payment×fulfillment dimensions), RentalAgreement, ServiceTicket (branching), SpecialOrder (cyclic QUOTED↔REVISION_REQUESTED loop), PurchaseOrder.
- **2 concurrency rules:** OCC on SalesOrder.version for place and fulfill (412 ERR_STALE_ORDER_VERSION).
- **11 calculations** (3 with dual variants): line_total (per-line rounding), reorder_flag, order_total_provisional/final (dual variant), loyalty_discount (subtotal-tier keyed), loyalty_accrual, rental_charge, service_fee, special_order_total, coop_rebate, account_credit_available (committed vs settled dual variant).
- **19 validations** (ordered, distinct error-categories), **63 endpoints**, **25 errors** (all triggerable/referenced), **5 roles** (Contractor is entity_backed:ContractorAccount; rest opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 §0.5 rules × exactly 2 instances = **18 instances**, each grounded, with executable setup_api_calls chains and pre-computed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **37 active corner instances + 5 exclusion stubs** across sections entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_complexity_layers (OCC happy/stale/fulfill-stale + derived reconciliation), consistency_model.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (304 calls scanned, all conform to §1.5; all 13 FKs reverse-reachable). Independently audited: zero unbound placeholders, zero forbidden concurrency vocabulary, all 60 instance names unique, all stub references resolve, every priority/assert pair consistent, every enum value produced by some path, OCC version arithmetic verified end-to-end.

One design note for downstream: `POST /sales-orders/{id}/lines` deliberately does **not** bump SalesOrder.version (only state-transition action endpoints do), so the version captured at order-create stays valid through the first place; stale-version negative tests use the `${var} - 1` form.

## Step 3: Copy Shared Files — 2026-06-22T12:00:09.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T12:05:00.000Z

All structural checks confirm. The PRD is complete and all three Hard Contracts pass.

Generated `workspace/PRD.md` (~298 lines) for the Hardware Lumber Yard API.

**Section structure:**
- §1. Introduction — dual finite-resource model (physical inventory + contractor credit), immediate-consistency stance.
- §2. Global Specifications (11 subsections): 2.1 RBAC (5 roles, opaque vs entity-backed Contractor), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties & Mutation Semantics (LoyaltyLedger only id/created_at), 2.5 Nested Retrieval / existence ordering, 2.6 Money & per-line-rounding, 2.7 OCC on sales orders, 2.8 Inventory invariants & reorder flag, 2.9 Account credit (settled vs committed exposure) + account opening, 2.10 Loyalty/co-op principles.
- §3. Business Logic (11 subsections): catalog, order building & line pricing, placement (provisional total + credit), fulfillment (depth-3 stock cascade + loyalty accrual), cancellation (compensating restock + loyalty reversal), net-term billing, rentals, service benches, special orders (quote/revision loop), purchase orders & co-op rebate, cross-cutting validation-priority + logical-clock.
- §4. Endpoint Definitions — 4-column table, 63 endpoints.
- §5. Error Code Catalogue — 2-column table, 25 errors.

**Hard Contract reports:** Field coverage PASS (62/62 entity fields, 6/6 request bodies, 2/2 query params); Rule coverage PASS (19 validations, 2 OCC, 5 state machines, 9 calc groups, 25 error_ids, sibling-branch symmetry); Path purity PASS (412 backtick tokens, 0 paths/methods in §3). §2.2 byte-identical to canonical source.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read, opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-22T12:24:00.000Z

All imports resolve. The test suite is complete and self-consistent.

Generated complete test infrastructure for `task_0472_hardware_lumber_yard`.

**test_helpers/ (9 files, Stage 1):** types.py (16 enums + 13 entity TypedDicts; LoyaltyLedger only id+created_at), api_client.py (58 endpoint methods), api_errors.py (26-entry ApiErrorId enum + HTTP status map: 422 for ERR_INVALID_REQUEST, 412 for ERR_STALE_ORDER_VERSION), assertions.py (per-entity + credit/total invariant checkers), factories.py (input-only payload factories, unique SKU/asset_tag/bin generators), constants.py (loyalty tiers, service fees, thresholds), test_users.py (opaque operator roles + make_contractor_headers(account_id)), fixtures.py (composite lifecycle helpers + clock control), __init__.py.

**test_suite/ (7 test files + conftest, Stage 2): 73 test functions, 100 verbatim PRD citations.**
- test_01_pricing_and_calculations.py, test_02_state_machines.py, test_03_cascades_and_invariants.py, test_04_validations_and_boundaries.py, test_05_temporal_overlap.py, test_06_catalog_crud.py, test_07_rbac_and_concurrency.py

**Coverage (design-index-only):** Queue A (Difficulty) all 18/18 instances translated (≥2 tests each, 0 skipped); Queue B (Corner) all 37/37 non-stub instances translated (≥1 test each, 0 skipped); the 5 excluded_because: stubs correctly NOT translated.

**Notable finding:** corner-design excluded stub `error_cylinder_not_certified` points to a difficulty instance `safety_vs_state_offline_station_propane_uncertified` that does not exist (real name `state_offline_station_beats_safety_uncertified_cylinder`) — a corner-design cross-reference bug, left as a gap (no placeholder, per spec). The cylinder-not-certified rule still gets a verbatim-cited assertion as the second test of that difficulty instance.

**Audits passed:** every test exactly one Design: tag; all 100 citation segments survive literal grep of PRD.md; no skip/xfail; no scaffold-table references; all imports resolve; all files parse. One two-reader gap avoided: ambiguous "station booking exactly at buffer edge" replaced with unambiguous window.

## Step 6: Generate Implementation — 2026-06-22T12:24:00.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

**Generation-time test result (single round):** All 73/73 tests pass under `prd-bench-local-run --isolation per-test-server`. (Authoritative 8-round stability sweep is Step 7.)

**Files produced (19 total):** start.sh (guarded-install foreground launcher), requirements.txt (flask==3.0.3), app.py, errors.py, response.py (envelope), db.py (in-memory store), clock.py (logical clock), auth.py (RBAC), validate.py, calc.py, serialize.py (output + derived-field recomputation), helpers.py; routes/: catalog.py, accounts.py, sales.py, billing_reads.py, rentals.py, services.py, special_orders.py, purchase_orders.py, admin.py (clock).

**Endpoints implemented:** 67 — vendors, products (+adjust-stock/discontinue), contractor accounts (+suspend/loyalty-ledger/invoices), sales orders + order lines + parallel-axis state machine (place/fulfill/cancel/invoice/pay/void-invoice), invoices, loyalty-ledger, rental assets/agreements (reserve/check-out/return/cancel), service stations/tickets (book/start/complete/cancel), special orders (quote/request-revision/confirm/receive/cancel cyclic loop), purchase orders (submit/receive/cancel + co-op rebate), /_clock/set_current_utc.

**Storage:** In-memory dicts keyed by UUID, single coarse RLock for per-request atomicity. No seeding — store starts empty on every boot. Decimal + ROUND_HALF_UP money math.

**Key correctness:** exact response envelope (meta/response_type/data), X-User-ID/X-User-Role auth with entity-backed Contractor ownership, OCC on expected_sales_order_version (412), per-line round-then-sum lumber pricing, loyalty tiers keyed on pre-discount subtotal, dual settled-vs-committed credit views, depth-3 fulfill cascade + compensating cancel restock/loyalty reversal, half-open rental overlap with cross-midnight day billing, buffer-expanded station booking conflicts, validation priority order (auth→authz→existence→request-validity→state→domain→OCC). Fixed: existence (404) before body request-validity (422) on path-scoped action endpoints.

**start.sh confirmation:** reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guards pip install behind import check so concurrent per-test reboots don't re-install.

## Step 7: Run Tests and Iterate — 2026-06-22T12:33:34.000Z

**Resume note:** A prior parallel run was OOM-killed partway through. On resume, Steps 5/6 artifacts were sanity-checked before the sweep: all `implementation/`, `test_helpers/`, and `test_suite/` Python files compile cleanly (no truncation), `app.py` imports, Flask 3.0.3 is present, `start.sh` is intact, and all 9 `routes/` modules are present. No file was found truncated; nothing required completion. A single-round smoke run passed 73/73, confirming a healthy baseline.

**Sweep protocol (resource-capped):** Per the mandatory OOM cap, the 8-round stability sweep ran in TWO sequential waves of 4 concurrent rounds each (`prd-bench-local-run --isolation per-test-server`, `--timeout 120 --test-timeout 30`, free port per round via the runner's file-locked registry), not 8-at-once. Union of failures taken across all 8 rounds.

Subagent summary (verbatim):

All 8 rounds are clean: 73/73 passed, 0 failed, 0 errors, 0 skipped in every round. No flakiness surfaced across the full two-wave sweep, so no diagnostic protocol, deletions, or fixes were needed. This is a valid 0-fix exit.

- Iterations run: 1
- Tests deleted: none
- Fixes applied to test_helpers/: none
- Fixes applied to implementation/: none
- Final sweep result: all 8 rounds 73/73 passed.

## Step 8: Finalize PRD — 2026-06-22T12:33:34.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). Per the skill's skip condition, `PRD.md` already determines every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-22T12:33:34.000Z

Produced `workspace/PRD_COMPLETED.md` via a full PRD-vs-`implementation/` scan starting from `PRD.md` (no `PRD_FINALIZED.md` since Step 8 was skipped).

**File deltas:** PRD.md 298 lines / 47,226 chars → PRD_COMPLETED.md 298 lines (all edits in-paragraph) / 48,636 chars (+1,410 chars).

**Change counts:** 5 total — 2 ambiguity-pins, 3 mismatch-revisions.

**Per-change log:**
- §2.1 (User and RBAC) — insert — ambiguity — Pinned that a Contractor ownership-check mismatch yields `ERR_UNAUTHORIZED`, and that the ownership check runs after existence (a non-existent reference yields `ERR_NOT_FOUND` first); PRD was silent on the error for ownership failures — `routes/accounts.py:24-25`, `routes/sales.py:46-47`, `routes/special_orders.py:23-24`.
- §2.3 (Pagination) — insert — ambiguity — Pinned the list tie-break: equal-`created_at` resources (common because the logical clock is frozen) are ordered by ascending creation sequence; PRD only specified `created_at` ascending — `helpers.py:18`, `db.py:44-51`.
- §2.9 (Credit Principle) — revise — mismatch — PRD claimed the credit decision "uses the committed view"; impl refuses when settled `balance_cents` + only this operation's total exceeds `credit_limit_cents` (other placed-unbilled totals not double-added). Revised to match — `routes/sales.py:222-224`, `routes/special_orders.py:140-141`.
- §3.9 (Special Orders) — revise — mismatch/ambiguity — Pinned the confirmation invoice's full shape: `due_at` = clock + `net_terms_days`, `sales_order_id` = `null`, plus `contractor_account_id`; PRD only mentioned `amount_cents` and `status` — `routes/special_orders.py:148-155,187-190`.
- §3.10 (Purchase Orders) — revise — mismatch — PRD draft sentence implied the "product must be one the vendor supplies" constraint at draft time; impl checks only existence at draft and defers the supplier-match rule to submit (`ERR_VENDOR_INACTIVE`). Revised the draft sentence to match and pinned line-field types — `routes/purchase_orders.py:50-53` (create) vs `:109-113` (submit).

Tests used only as auxiliary cross-reference; `implementation/` was the sole alignment authority. No new sections, no invented behavior.
