# Worklog — task_0304_foodservice_distribution_wholesale

## Step 1: Create Task Directory — 2026-06-11T14:28:01.000Z

Created `tasks/task_0304_foodservice_distribution_wholesale/` with `workspace/` subdirectory (pre-allocated index, no auto-increment). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-11T15:06:34.000Z

All three Expert-band scaffold artifacts written and lint-clean (`scaffold_lint.py` VERDICT: clean lint). Files verified present: SCAFFOLD.yaml (1280 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1345 lines, top-key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (1668 lines, top-key `scaffold_corner_design`).

Archetype/profile: pricing_engine + quota_allocation; flat topology (peer collections, FK-in-body — `api_prefix: ""`); parallel state-machine shape; peer_roles; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

Entities (13): Distributor, Warehouse, Route, Product, PriceTier, Customer, OrderGuide, OrderGuideItem, InventoryLot, Order, OrderLine, Shipment, Return.

State machines (4):
- Customer — ACTIVE ↔ CREDIT_HOLD → CLOSED (posture-style AR gating)
- Order — two parallel dimensions: fulfillment_status (DRAFT→SUBMITTED→PICKING→LOADED→DELIVERED / CANCELLED) × credit_status (PENDING/APPROVED/ON_HOLD)
- Shipment — PICKING→LOADED→DELIVERED (pick/load/POD)
- Return — REQUESTED→{APPROVED→CREDITED, REJECTED} (branching fork)
- 1 concurrency rule — `approve-credit-stale-customer` (genuine CREATE-with-supersede OCC on Customer.version)

Counts: 5 calculations (line_pricing tiered dual-basis, allocate_inventory FEFO+substitution, order_totals, par_replenishment, return_credit — each with variants) · 17 validations (priorities 1–17, unique/ordered) · 54 endpoints · 27 errors (all referenced) · 4 roles.

Design files: SCAFFOLD_DIFFICULTY_DESIGN.yaml = 18 instances (2 per each of the 9 Difficulty Rules, including temporal-overlap: Route delivery-gap buffer vs InventoryLot freshness-window containment). SCAFFOLD_CORNER_DESIGN.yaml = 32 active instances + 6 excluded stubs across all 9 claim-extraction sections.

Verification performed: lint clean (535 calls scanned); all `grounds` resolve to declared elements; all 27 errors referenced; enum-value closure holds; no forbidden concurrency vocabulary; OCC fields/version-bumps satisfy §1.2.1; pinned numeric assertions re-computed exact (dual-basis 2200-tier × 48 = 8800; depth-3 cascade AR 11000→5400; overage restock 15% credit 680 vs damage 800).

Note: restructured from nested URLs to flat topology (`api_prefix: ""`) because `scaffold_lint.py`'s FK reverse-reachability check requires `<prefix>/<seg>/{id}`-shaped single-resource GETs; flat design is lint-clean and diversity-prioritized per §0.3.

## Step 3: Copy Shared Files — 2026-06-11T15:06:34.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0304_foodservice_distribution_wholesale/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T15:13:23.000Z

Generated `workspace/PRD.md` (279 lines / 45199 bytes) from SCAFFOLD.yaml only. Difficulty/corner design files were NOT read (confirmed by subagent).

Section list:
- §1. Introduction (system goals + hard cross-cutting problems)
- §2. Global Specifications & System-Wide Principles
  - 2.1 RBAC (4 roles, opaque identity); 2.2 API Response Structure; 2.3 Pagination; 2.4 Tenancy/Common Properties/Identifiers; 2.5 Hierarchical Consistency & Cascading Effects; 2.6 Money/Quantities/Rounding; 2.7 OCC on Credit Approval; 2.8 Catalog Revision Tracking; 2.9 The Server Clock
- §3. Business Logic & Workflows (7 subsections: catalog setup → customers/guides/replenishment → order capture → credit approval w/ allocation+pricing+AR → credit governance → fulfillment → returns)
- §4. Endpoint Definitions (4-column table, 57 endpoints)
- §5. Error Code Catalogue (2-column table, 27 error IDs)

Hard Contracts — all PASS: Field coverage (61/61 names, 13/13 path params), Rule coverage (1 OCC rule, all 4 state machines' transitions/preconditions/cascades, all 5 calculations in precise prose, all 17 validations + precedence, all 27 error IDs surfaced), Path purity (449 backtick tokens, 0 path-like in §3).

## Step 5: Generate Unit Tests — 2026-06-11T15:30:06.000Z

test_helpers/ (9 files): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.
test_suite/ (7 test files + conftest.py): 66 tests total, each tagged with exactly one `Design:` line, no skip/xfail markers, no scaffold leakage.

Queue A (Difficulty) — 18 instances: 17 translated (≥2 tests each, 35 tests), 1 skipped:
- SKIPPED `priority_pair_validation_conflict/invalid_state_beats_credit_hold_state_vs_safety`: not uniquely derivable. Instance sets up a DRAFT order whose credit_status IS PENDING then expects ERR_INVALID_STATE; but PRD §3.4 ties approve-credit's ERR_INVALID_STATE precondition to credit_status==PENDING (passes here), so two faithful readers diverge (ERR_INVALID_STATE gating on fulfillment SUBMITTED vs proceeding to hold check → ERR_CUSTOMER_ON_CREDIT_HOLD). Fails two-reader test.

Queue B (Corner) — 31 non-stub instances: all 31 translated (31 tests). The 5 excluded_because: stubs (1 state_machines + 4 errors) correctly not translated; each cross-reference resolves to a real difficulty instance owning the assertion.

Notable adjudication: GET /order-guides/{id}/replenishment computed read uses validate_success (not validate_paginated) — PRD describes a computed read; only suggested_uom/suggested_qty asserted. Ellipsis-spliced citations tightened to single-sentence verbatim quotes. All 66 PRD citations verified verbatim by grep; all api.* calls and test_helpers imports resolve against Stage-1 interface.

## Step 6: Generate Implementation — 2026-06-11T15:30:06.000Z

Generated Python + Flask implementation at workspace/implementation/ (20 source files): start.sh, requirements.txt (flask==3.0.3), app.py, db.py (13 module-level in-memory dicts), errors.py (27 error-id constants), response.py (meta/response_type/data envelope), middleware.py (X-User-ID/X-User-Role auth + RBAC + pagination), models.py (common-field discipline), services/ (clocks.py, calc.py, lookup.py, serialize.py), routes/ (catalog.py, customers.py, orders.py, shipments.py, returns.py, listing.py).

Endpoint count: 54 implemented — matches PRD §4 endpoint table (54 rows).

Startup contract confirmed: start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec; pip-install guarded on cheap `import flask`. Storage purely in-memory (module-level dicts in db.py, wiped on every restart); NO seeding/preloading; every db write inside a route handler.

Subagent self-verified end-to-end via scripted suites (order lifecycle, tiered+split pricing, FEFO allocation+substitution, ON_HOLD rollback, OCC stale-version 412, AR sweep, credit hold/release/over-limit, cutoff/delivery-day/gap, perishable freshness, return credit memos w/ OVERAGE restock, cancel compensation, par replenishment, cross-distributor refs, RBAC, pagination). All sources byte-compile cleanly.

Design note flagged by impl subagent: on ON_HOLD credit path, preserves order_total_cents (used by credit-release/issue-credit cascades vs customer headroom) while rolling back lot reservations and leaving AR unchanged; re-approval re-runs allocation/pricing from scratch over non-removed lines. Traces to PRD §3.4 (rollback scope), §3.5/§3.7 (headroom uses order_total_cents).

## Step 6: Re-run Verification (RESUME) — 2026-06-12T02:06:13.000Z

Resume session opened with instructions to RE-RUN Step 6 on the premise that `workspace/implementation/` was "only a STUB (app.py ~60 lines, route handlers and serializers missing)". On-disk cross-check CONTRADICTS that premise — the implementation is COMPLETE, not a stub. The Step 6 re-run was therefore SKIPPED to avoid destroying a working, fully-passing implementation. Evidence:

- 20 source files present (matches the original Step 6 entry above), all written 23:14–23:22 in a single uninterrupted Step 6 pass (consistent mtimes; not a mid-generation truncation).
- 2157 total lines of Python. app.py (60 lines) is a thin blueprint-registration entry point — the route handlers live in routes/ (orders.py 407, catalog.py 322, customers.py 247, returns.py 141, shipments.py 91) and the serializers live in services/serialize.py (106). Neither is "missing".
- `listing.py` is a shared list-response helper (filter→sort created_at ASC→paginate), correctly imported by all six route modules — NOT an unregistered blueprint; app.py is correct to not register it.
- All files byte-compile cleanly (`python3 -m py_compile`).
- Server boots cleanly and registers exactly 54 business endpoints + 1 `_clock` control endpoint (full distributors/warehouses/routes/products/price-tiers/inventory-lots/customers/order-guides/order-guide-items/orders/order-lines/shipments/returns surface).
- Single diagnostic round via `prd-bench-local-run --isolation per-test-server`: **66/66 passed, 0 failed, 0 errors, 0 skipped** (40.7s). Test count still 66 → no prior partial Step 7 ran (no deletions yet); no results.*.json, no PRD_FINALIZED.md, no PRD_COMPLETED.md on disk → Steps 7/8/9 never ran.

Genuine resume point: Step 7 (8-round parallel stability sweep) against the existing complete implementation. No regeneration performed; no files overwritten.

## Step 7: Run Tests and Iterate — 2026-06-12T02:09:07.000Z

All 8 parallel rounds passed cleanly: 66/66 in every round, with zero failures, errors, or skips. My initial confusion was a scripting bug on my end (I queried the wrong field name — `outcome` instead of `status`); the actual results were green from the first read.

This satisfies the exit condition: all 8 rounds have `passed == total`. No flakiness, races, or port collisions surfaced under 8× concurrent load. As expected for this resume, the implementation that already passed a single sequential round is stable across the parallel sweep. No tests deleted, no fixes applied.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep)

**Tests deleted:** None. No test failed in any round, so no PRD-silence or unique-derivability analysis was triggered.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None. The implementation was not modified, regenerated, or seeded — per the resume contract.

**Final sweep evidence (passed/total per round):**
- results.1.json — 66/66
- results.2.json — 66/66
- results.3.json — 66/66
- results.4.json — 66/66
- results.5.json — 66/66
- results.6.json — 66/66
- results.7.json — 66/66
- results.8.json — 66/66

All rounds: `failed=0, errors=0, skipped=0`. The 8-round parallel stability sweep is fully green; the implementation is stable under 8× concurrent load.

## Step 8: Finalize PRD — SKIPPED — 2026-06-12T02:09:07.000Z

Skipped per the skill's Step 8 skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond the baseline). PRD.md already determined every behavior the implementation exhibits, so no `<step_7_diff>` focus list exists to patch. `PRD_FINALIZED.md` is intentionally NOT produced. Step 9 will therefore read `PRD.md` as its source.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-12T02:13:53.000Z

Source was `PRD.md` (PRD_FINALIZED.md absent because Step 8 was skipped). Produced `workspace/PRD_COMPLETED.md` via a full PRD-vs-implementation/ scan. All six edits are in place, each a minimal in-paragraph insert/revision. The line count is unchanged (279), and the char delta is +1080.

Final cross-check on the return request precedence: the impl checks customer-closed BEFORE the order_line-belongs-to-order check. The inserted prose lists them in that same order (CLOSED first, then belongs-to-order), so the narrative ordering is consistent with impl (returns.py:34-38).

## Summary

**Source vs output:** `PRD.md` = 279 lines / 45,199 chars → `PRD_COMPLETED.md` = 279 lines / 46,279 chars (char delta **+1,080**; line count unchanged — all edits are in-paragraph).

**Counts:** ambiguity-pins = **5**, mismatch-revisions = **1**.

**Changes (one per edit):**

- §2.4 (Common Resource Properties) — insert — ambiguity — pinned the `version` initial value as `1` (PRD said only "begins at its initial value") — `implementation/models.py:22`.
- §3.1 (Catalog/Products) — insert — ambiguity — pinned that a supplied `substitute_product_id` is validated at product creation: must resolve (`ERR_NOT_FOUND`) and be under the same distributor (`ERR_CROSS_DISTRIBUTOR_REFERENCE`); PRD was silent on validation — `implementation/routes/catalog.py:182-185`.
- §3.2 (Replenishment) — insert — ambiguity — pinned that the replenishment endpoint returns qualifying items in `created_at` ascending order and is not paginated (meta reports full-set `limit`/`total_count`, `offset` 0, `has_more` false) — `implementation/routes/customers.py:194-204`.
- §3.4 (Credit Approval / Allocation) — revise — mismatch — PRD said "Each `OrderLine` still in `OPEN` status is processed"; impl processes every non-`REMOVED` line and, on a re-approval (post-`ON_HOLD`→`PENDING`), resets each line's allocation/pricing fields before re-allocating — `implementation/routes/orders.py:251,278-287`.
- §3.4 (Credit Approval / Pricing) — insert — ambiguity — pinned that when the fulfilled product carries no qualifying tier, `unit_case_price_cents` is taken as zero — `implementation/services/calc.py:160`.
- §3.7 (Returns) — insert — ambiguity — pinned that an `order_line_id` not belonging to the cited `order_id` is rejected with `ERR_INVALID_STATE` (PRD named no error) — `implementation/routes/returns.py:37-38`.

**Notable behaviors confirmed already pinned (no change):** standard submission/approval precedence; cutoff `<=` boundary; FEFO allocation ordering; ordered-tier/allocated-charge pricing; rounding directions; cancel/POD compensation; OCC version-check; AR sweep; issue-credit transitive cascade; `fulfilled_product_id` selection for fully-shorted lines (falls to "otherwise" = original product). Deliberately did NOT add edits for non-domain framework behavior (404/405 envelope handling) or for the clock-advance monotonicity (PRD's "sets it to a supplied instant" already matches the impl, which performs no backward-rejection).

---

## Pipeline complete — 2026-06-12T02:13:53.000Z

Resume finished. `PRD_COMPLETED.md` exists and the 8-round parallel stability sweep is fully green (66/66 × 8). Step 6 was NOT re-run (the existing implementation was already complete and passing — see Step 6 Re-run Verification above); Step 8 was skipped per its skip condition; Steps 7 and 9 completed. No implementation regeneration, no test weakening/skipping, no data seeding.
