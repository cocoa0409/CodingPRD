# Worklog — task_1020_chocolate_confectionery

## Step 1: Create task directory — 2026-07-14T18:00:22.000Z

Created `./tasks/task_1020_chocolate_confectionery/` with `workspace/` subdirectory. Pre-assigned folder used verbatim (no ID re-scan). INSTRUCTION.md present at project root.

## Step 2: Generate scaffold — 2026-07-14T18:26:00.000Z

All checks pass. The three scaffold artifacts are complete and self-consistent.

Generated a fresh **Expert-difficulty** scaffold for the Chocolate & Confectionery Shop (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml). `scaffold_lint.py` reports **`VERDICT: clean lint`** (218 design calls conform to §1.5; all 18 FKs reverse-reachable). All three files verified to yaml.safe_load cleanly.

**Complexity profile:** quota/allocation primary + workflow-orchestration secondary; graph topology (self-referential BundleComponent over Product); cyclic state machines; peer_roles; immediate consistency.

**Contents:**
- **13 entities** — Customer, Product, BundleComponent, Mold, TemperingLine, Batch, Order, OrderLine, Reservation, CustomOrder, MoldBooking, Subscription, SubscriptionShipment.
- **5 state machines** — Batch (cyclic reseed loop + quarantine + expiry), Order (allocate/backorder/fulfil), CustomOrder (cyclic quote↔revision negotiation), Subscription (pause/resume cycle + self-loop advance), SubscriptionShipment.
- **7 calculations** — line_unit_price, wholesale_tier_discount, order_total (pinned round-per-line-then-sum), custom_order_amount (quote vs invoice dual-variant), subscription_period_charge (estimate vs settled dual-variant), batch_available_units, fefo_allocation (FEFO by lot_expiry then created_at, never id).
- **19 ordered validations**, **30 error codes**, **66 endpoints** (incl. `/_clock/set_current_utc` default `2026-07-01T00:00:00Z` and `/_inventory/sweep-expired`), **4 roles** (Customer entity_backed; SalesManager/ProductionManager/Admin opaque).
- **1 concurrency rule** — OCC on Batch.version for reservation over-subscription (412).

**§1.8 Difficulty design:** 18 instances (9 rules × 2). **§1.9 Corner design:** 26 instances (20 active recipes + 6 `excluded_because` stubs).

Note: endpoint count (66) sits above the Expert 20–32 guideline — scenario spans 8 subsystems; ~18 are mandatory FK reverse-reachability GET pairs.

## Step 3: Copy INSTRUCTION.md — 2026-07-14T18:26:46.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-14T18:32:47.000Z

Generated `workspace/PRD.md` (284 lines) from SCAFFOLD.yaml (never opened either withheld design file). All three hard contracts PASS.

**Structure:** §2 Global Specs (9 subsections: RBAC, response envelope, pagination, common props/versioning, validation-order/error-precedence, monetary precision, OCC on batches, allergen/shelf-life, derived inventory/cascade). §3 Business Logic (8 lifecycle subsections). §4 = 66 endpoints (4-col table). §5 = 30 error codes.

**Hard Contract reports:** Contract 1 Field-Name Coverage 71/71 PASS. Contract 2 Rule Coverage (19 validations, 1 concurrency rule ERR_STALE_VERSION/412, 5 state machines, 7 calculations incl. TAX_RATE 0.0725, GIFT_WRAP_FEE 500, custom surcharge 300 + setup 25000, FEFO) PASS. Contract 3 §3 Path Purity 330 tokens, 0 leaks PASS.

**Notable decisions:** request `wallet_apply_cents` vs system `wallet_applied_cents` both documented; BundleComponent is the one `common_fields:false` entity (id/created_at only); half-open tempering interval (adjacency allowed); inclusive wholesale tier boundaries (49→0%, 50→10%); CONFIRMED→BACKORDERED reachable only via quarantine cascade.

## Step 5: Generate unit tests — 2026-07-14T18:46:49.000Z

All checks pass: 56 tests compile and collect cleanly, no scaffold leakage, no skip/xfail, every PRD citation verifies verbatim.

**test_helpers/** (9 files): types.py (12 status enums + entity TypedDicts, BundleComponent id/created_at only), api_client.py (one method per endpoint), api_errors.py (30 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque roles as constants; make_customer_headers() for entity-backed Customer), fixtures.py (released-batch, allocated-order, quoted/accepted custom-order, tempering-batch composites), __init__.py.

**test_suite/** (conftest + 7 domain files): test_01_pricing_calculations, test_02_custom_orders, test_03_subscriptions, test_04_batch_tempering, test_05_inventory_cascades, test_06_orders_wallet, test_07_catalog_rbac.

**Coverage: 56 tests.** Queue A (Difficulty): 36 (all 18 instances × 2). Queue B (Corner): 20 (all 20 non-stub instances × 1). 6 excluded_because stubs correctly not translated. **Skipped for PRD-coverage/unique-derivability: none.** Boundary tests exploit PRD-derivable variants (49-vs-50 wholesale tier; end-to-start tempering adjacency).

## Step 6: Generate implementation — 2026-07-14T18:46:49.000Z

Complete Python + Flask REST API in workspace/implementation/. ast.parse OK; 66 @app.route routes (== scaffold 66 endpoints); start.sh foreground/PORT/0.0.0.0/guarded-pip verified.

**Files (5):** start.sh, requirements.txt (Flask 3.0.3), errors.py (id→HTTP catalog + ApiError), db.py (in-memory Store, empty on boot, logical clock default 2026-07-01T00:00:00Z, versioning), app.py (~1547 lines).

**Key decisions:** in-memory only, empty every boot (no seeding); verbatim structural names (envelope meta/response_type/data, error_id/message, limit/offset/total_count/has_more, X-User-ID/X-User-Role, expected_batch_version/ERR_STALE_VERSION); Decimal round-half-up, per-line-then-sum; validation precedence per PRD §2.5; created_at/updated_at wall-clock + _seq monotonic for list sort & FEFO tie-break; logical clock governs domain temporal logic only; cascades bump version/updated_at per §2.9.

**Ambiguities resolved:** start-tempering on non-tempering product → ERR_VALIDATION; too-early temporal preconditions → ERR_INVALID_STATE; empty-order confirm → ERR_VALIDATION; usage_date capacity bucketed by calendar date.

**Verification:** two smoke suites (53 checks) all pass; server boots cleanly.

## Step 7: Test-and-fix loop — 2026-07-14T18:52:18.000Z

All 8 rounds pass cleanly (56/56 each). Verified independently: results.1..8.json all passed=56 total=56.

**Iterations run:** 2 (baseline sweep + 1 fix, then confirming sweep).

**Diagnosis:** baseline sweep showed a consistent 2-test failure across all 8 rounds, both in `test_03_subscriptions.py`, both `AssertionError: Expected 200, got 201`. Both traced to a single root cause: `_advance_shipment` helper called `validate_success(api.advance_subscription(...))`, defaulting to HTTP 200. Per PRD §4 line 178 ("Endpoints that create a new resource respond with HTTP 201...") and §3.8 line 172 (advance "emits a new `SubscriptionShipment` child"), the PRD-faithful status is **201**, which the implementation correctly returned. The test was the buggy artifact (STEP 2: test-vs-PRD inconsistency).

**Tests deleted:** None.
**Fixes applied to test_helpers/:** None.
**Fixes applied to test_suite/:** `test_03_subscriptions.py`, `TestEstimateVsSettledDivergence._advance_shipment` — changed `validate_success(api.advance_subscription(sub["id"], ADMIN))` → `validate_success(..., 201)` because advance creates a new SubscriptionShipment (PRD §4 → HTTP 201). This helper feeds both failing tests; one fix resolved both.
**Fixes applied to implementation/:** None — implementation was PRD-faithful.

Final state: 8/8 rounds pass, 56/56 tests each.

## Step 8: Finalize PRD — 2026-07-14T18:53:39.000Z

No edits required. `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (284 lines, 0% delta). Step 8 ran (not skipped) because there was 1 test_suite/ fix in Step 7.

The single Step 7 item (advance-endpoint status 200→201 test fix) is a fixture bug, not a PRD silence/mismatch — PRD.md already uniquely determines HTTP 201 via §4 create-convention ("Endpoints that create a new resource respond with HTTP 201") + §3.8 ("Each advance emits a new `SubscriptionShipment` child"). Impl `app.py:1464-1488` returns `ok_entity(sh, 201)`. Grep of `advance` confirmed no divergent parallel path. No edit warranted.

## Step 9: Complete PRD — 2026-07-14T18:58:48.000Z

Full PRD-vs-implementation scan. Source `PRD_FINALIZED.md` (284 lines, 42321 chars) → `PRD_COMPLETED.md` (284 lines, 44046 chars); char-delta +1725. All in-paragraph inserts/revisions; no new sections.

**Counts:** ambiguity-pins = 9, mismatch-revisions = 1.

**Changes:**
- §2.1 RBAC — revise — mismatch — blanket "all four roles may read" contradicted §4 table; pinned GET /customers/{id} to Customer/SalesManager/Admin, GET /customers to Admin only (app.py:507,513)
- §2.3 Pagination — insert — ambiguity — out-of-range/non-numeric limit/offset silently clamped/defaulted; created_at ties broken by ascending creation sequence (app.py:271-300)
- §2.4 Timestamps — insert — ambiguity — created_at/updated_at/api_request_timestamp from server wall clock, independent of settable logical clock (db.py:99,118; app.py:54)
- §3.2 Wallet — insert — ambiguity — deduction has no lower bound, may drive wallet_credit_cents negative (app.py:546)
- §3.3 Start tempering — revise — ambiguity — non-tempering product → ERR_VALIDATION (app.py:707-708)
- §3.3 Complete tempering — insert — ambiguity — completing before temper_end → ERR_INVALID_STATE (app.py:734-735)
- §3.5 Confirm/wallet — insert — ambiguity — missing/non-int wallet_apply_cents → 0, applied floored at 0 (app.py:1047-1052)
- §3.6 Fulfil window — insert — ambiguity — pre-order window enforced only when both bounds present (app.py:1130-1135)
- §3.7 Custom-order fulfil — insert — ambiguity — units_produced must be positive int else ERR_VALIDATION (app.py:1350-1351)
- §3.8 Advance — insert — ambiguity — non-ACTIVE or before next_ship_date → ERR_INVALID_STATE (app.py:1468-1471)

Cross-checked remaining surface (pricing/rounding, FEFO, cascades, wholesale tiers, credit-limit, OCC, validation precedence, subscription indexing) — already uniquely pinned.

---

## Pipeline complete — 2026-07-14T18:58:48.000Z

All 9 steps done. Final: 56/56 tests pass across 8/8 stability rounds. Artifacts: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/, test_suite/ (56 tests), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}.
