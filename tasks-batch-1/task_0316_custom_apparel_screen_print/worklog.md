# Worklog — task_0316_custom_apparel_screen_print

## Step 1: Create task directory — 2026-06-12T18:41:36.000Z

Created `tasks/task_0316_custom_apparel_screen_print/` and `tasks/task_0316_custom_apparel_screen_print/workspace/` (pre-assigned index 0316, no auto-scan per parallel-pipeline constraint). No collision with existing directories.

## Step 2: Generate scaffold (Expert band) — 2026-06-12T19:10:31.000Z

The scaffold for **task_0316_custom_apparel_screen_print** is complete. All three files were written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0316_custom_apparel_screen_print/` and `scaffold_lint.py` returns **VERDICT: clean lint**.

## Counts (Expert band, §0.4)
- **Entities: 13** — Shop, Customer, DecorationMethod, GarmentStyle, BlankSku, Press, EmbroideryStation, Order, OrderLine, ArtProof, BlankReservation, Quote, ProductionRun
- **State machines: 3** — ArtProof (cyclic revision loop), Order (parallel `fulfillment_status` × `billing_status`), ProductionRun (branching good/scrap)
- **Calculations: 9** (4 variant entries across 2 dual-variant calcs)
- **Validations: 17** (priority-ordered) · **Concurrency rules: 1** (OCC on Order.version)
- **Endpoints: 51** · **Errors: 20** · **Roles: 4** (ShopManager, ArtStaff, Customer entity-backed, System)
- **§1.8: 18 difficulty instances** (all 9 rules × 2) · **§1.9: 31 active corner instances + 5 `excluded_because` stubs** · 54 unique instance names; all `excluded_because` references resolve to real §1.8 instances.

## Expert-band design choices
- **Primary archetype pricing_engine + secondary quota_allocation**: multi-dimensional pricing (quantity tiers × ink colors × locations, screen/digitizing setup, rush surcharge, spoilage allowance) layered over finite blank-stock reservation.
- **Two dual-variant calcs on different domains** (Rule 1): `order_price` ESTIMATE-vs-FINAL on the Order, `blank_consumption_cost` RESERVED-vs-CONSUMED on the BlankSku/BlankReservation domain.
- **Two combinatorial modes** (Rule 2): mode (a) tier×color×location run cost; mode (b) pinned per-line-then-sum rounding order.
- **Non-linear machines on two entities** (Rule 3): ArtProof cyclic revision loop + Order parallel fulfillment/billing dimensions.
- **Two transitive cascades from different triggers** (Rule 4): depth-3 `complete → FULFILLED → reservation CONSUMED → BlankSku stock`; depth-2 `cancel → reservation RELEASED → BlankSku restock` (+ proof VOID).
- **Two resource-overlap rules with different interval semantics on different entities** (Rule 8): Press teardown-buffer adjacency vs EmbroideryStation half-open head-count concurrency.
- **Two conserved-quantity invariants** (Rule 9): blank-unit conservation (reserve↔release) and customer deposit-cents conservation (confirm↔cancel).
- All formula-derived asserts are pre-computed literals (e.g., decoration 79200, grand_total 119400, rush 19800, deposit 59700), verified by code.
- API uses **flat topology** (`api_prefix: ""`, root-level collections) per lint heuristic + skill diversity guidance; Shop scoping carried via `shop_id` in bodies/filters.

## Step 3: Copy INSTRUCTION.md — 2026-06-12T19:10:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0316_custom_apparel_screen_print/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-12T19:17:15.000Z

Generated `workspace/PRD.md` (255 lines) from SCAFFOLD.yaml only. Did NOT read either withheld design YAML.

**Section structure:** §1 Introduction; §2 Global Specs (2.1 RBAC all 4 roles + opaque vs entity-backed identity, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Properties/versioning, 2.5 Nested Retrieval + FK filters, 2.6 Monetary/Quantity Precision, 2.7 Test-Driving Clock, 2.8 Blank Inventory Conservation, 2.9 OCC on Proof Approval, 2.10 Validation Ordering); §3 Business Logic (9 lifecycle subsections: Shop/Catalog/Customers, Machines, Order Composition/Proofs, Confirmation/Pricing/Reservation/Deposit, Tier+Per-Method Run Pricing, Setup Charges+Reorder Waiver, Scheduling/Running Production, Fulfillment/Cancellation/Stock Cascades, Billing); §4 Endpoint table (51 rows); §5 Error table (20 rows).

**Rendered into prose:** 13 entities, 51 endpoints, 8 calculations, 3 state machines (ArtProof cyclic, Order dual fulfillment×billing, ProductionRun branching), 1 OCC rule, 20 errors. Hard Contract 1 (field coverage), Contract 2 (rule coverage), Contract 3 (path purity §3) all PASS. §2.2 byte-identical to source.

## Step 5: Generate unit tests — 2026-06-12T19:34:45.000Z

Generated complete test infrastructure (EXPERT band, pricing-engine / quota-allocation domain).

### test_helpers/ (Stage 1) — 9 files
- `types.py` — entity TypedDicts (all versioned per PRD §2.4) + 9 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)`, 57 endpoint methods (one per PRD §4 row)
- `api_errors.py` — 20-member `ApiErrorId` enum + HTTP status map, registered so `validate_error()` auto-checks status
- `assertions.py` — per-entity assertions + `assert_blank_conservation_invariant`
- `factories.py` — input-field-only payload factories per resource
- `constants.py` — tier rates, shop/method/machine defaults, deposit pct
- `test_users.py` — opaque shared headers for ShopManager/ArtStaff/Customer + mandatory `make_customer_headers(id)` builder for entity_backed Customer role
- `fixtures.py` — layered composite builders (catalog → approved-proof order → confirmed → started-run → fulfilled → invoiced) with identity threading
- `__init__.py` — barrel export

### test_suite/ (Stage 2) — 7 test files, 68 collected tests
Domain-grouped: pricing/quotes, state machines, cascades/inventory, validations/errors, machine scheduling, proof-approval OCC, resources/access.

### Translation tally
- **Queue A (Difficulty): 18/18 instances translated, 0 skipped** (39 A-tagged tests).
- **Queue B (Corner): 31/31 non-stub instances translated, 0 skipped** (32 B-tagged tests). 4 `excluded_because` stubs correctly NOT translated; all 4 cross-refs resolve to real difficulty instances.
- **No PRD-first skips needed** — every instance had verbatim PRD coverage + unique derivability.

### Audits passed
Every docstring ends with exactly one `Design:` tag; all 67 tags resolve; zero dangling/dual/untagged. Every quoted PRD citation survives whitespace-normalized grep of PRD.md. No scaffold/Table N/test_recipe leakage; no skip/skipif/xfail. `pytest --collect-only` succeeds (68 tests) under Python 3.12 venv.

## Step 6: Generate implementation — 2026-06-12T19:34:45.000Z

Generated complete Python + Flask implementation (27 source files + launcher).

### Files
- **Launcher/deps**: `start.sh`, `requirements.txt` (Flask==3.0.3)
- **Entry/foundation**: `app.py`, `db.py` (in-memory store + common-field/`touch`), `errors.py` (verbatim PRD §5 catalog), `response.py` (envelope meta/response_type/data), `serialize.py`, `clock.py`, `middleware.py` (auth/RBAC), `validation.py`
- **Routes**: clock, shops, customers, decoration_methods, garment_styles (+ blank-skus), machines (presses + stations), orders (+ lines, confirm, cancel, invoice, pay, quote), art_proofs, reservations, production_runs
- **Services**: pricing, quote (ESTIMATE/FINAL), inventory (reserve/release/consume/restock), lifecycle (confirm/cancel/fulfill cascade/invoice), scheduling (press buffer + station head-count), lookups (left-to-right path validation)

### Storage model
Pure in-memory dicts keyed by UUID (one dict per entity); module-level singleton `store`; monotonic `_seq` for deterministic `created_at` tie-breaks. No disk/SQLite/seeding — empty on every boot.

### State machines & calculations
- Parallel Order dimensions (fulfillment_status × billing_status); billing advances only past FULFILLED gate.
- Cyclic ArtProof revision loop (SUBMITTED↔CHANGES_REQUESTED, `revision_round` increments) with OCC on `expected_order_version` at approve (412 on mismatch).
- Branching ProductionRun (good/scrap) driving depth-3 fulfill cascade + depth-2 cancel cascade (release + restock + proof VOID + deposit refund).
- Decimal for percentage rounds (ceil for spoilage/rush/deposit; floor for rush-window whole-days). Per-line-rounded-then-summed. Dual variants ESTIMATE (ordered) vs FINAL (consumed). Locked values verified (decoration 79200, setup 15000, blank 25200, grand_total 119400, deposit 59700, final_total 120100).

### Validation ordering
PRD §2.10 priority order (auth 400 → RBAC 403 → existence 404 left-to-right → body 400 → state 409 → business). Confirm preconditions per §3.4 prose order (ORDER_EMPTY → PROOF_NOT_APPROVED → BLANK_INSUFFICIENT).

### start.sh
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, guards `pip install` behind Flask-import check, seeds no data.

### Impl-gen design-artifact note (carried for Step 7/8 awareness)
Impl-gen flagged that the withheld DIFFICULTY_DESIGN `cancel_release_void_restock_depth2` case asserts an APPROVED proof becomes VOID on cancel, which contradicts PRD ("only non-terminal ArtProof — DRAFT/SUBMITTED/CHANGES_REQUESTED — is voided"; "APPROVED and VOID are terminal") and the SCAFFOLD state machine. Impl voids only non-terminal proofs per PRD-wins rule. Step 7 should evaluate any related test failure against PRD prose.

## Step 7: Test + fix loop — 2026-06-12T19:41:29.000Z

All 8 parallel rounds pass 68/68. Loop complete.

**Iterations run:** 2 (1 baseline sweep with 3 failures — deterministic, same 3 every round, no flakiness; 1 verification sweep clean).

**Tests deleted:** None.

**Fixes applied to test_suite/** (one test, split per Cardinal Rule STEP 1c — partial coverage):
- `test_suite/test_03_cascades_and_inventory.py` → `test_cancel_releases_reservation_restores_stock_and_voids_proof`: removed the assertion `proof_after["status"] == "VOID"` (and the now-unused `proof_id` fetch). This is the difficulty-design case flagged in the prompt (`cancel_release_void_restock_depth2`). The proof on a CONFIRMED order is APPROVED, which PRD §3.3 declares terminal ("`APPROVED` and `VOID` are the proof's terminal states"); PRD §3.8 voids only "every non-terminal `ArtProof`". The VOID assertion fails STEP 1b unique-derivability — it contradicts PRD prose, which a faithful implementer correctly leaves APPROVED. The PRD-covered assertions in the same test (reservation→RELEASED, SKU restock to 200/0) were kept. Category: BRANCH-ASYMMETRIC / scaffold-only assertion — scaffold rule `Difficulty/transitive_cascade/cancel_release_void_restock_depth2` over-specified VOID on a terminal proof.

**Fixes applied to implementation/** (one file, one function):
- `workspace/implementation/routes/production_runs.py` → `schedule_run()`: moved the order-state check (`ERR_ORDER_NOT_CONFIRMED`) to run before the order's `resource_kind` resolution. Previously a DRAFT order with no lines hit `_order_resource_kind() == None` and raised a fabricated tier-4 `ERR_INVALID_REQUEST` ("Order has no lines to determine the machine"), pre-empting the PRD-named state error. Per PRD §2.10 the enumerated tier-4 body checks do not include "order has lines"; an order has lines only by virtue of being CONFIRMED, so the no-lines condition is a state consequence and must yield PRD §3.7 error `ERR_ORDER_NOT_CONFIRMED`. Fixed both `test_production_run_requires_confirmed_order` and `test_production_run_reports_state_error_before_window_conflict`; sibling window-conflict test (both orders CONFIRMED) still resolves kind and raises `ERR_PRESS_WINDOW_CONFLICT` correctly.

**Final state:** 8/8 parallel rounds, 68/68 tests passing, 0 failures, 0 errors. No implementation checks weakened, no PRD-required behavior removed, no seeded data, in-memory storage untouched.

**Orchestrator note:** The subagent's final results.{1..8}.json were not persisted on its exit; the orchestrator independently re-ran the full 8-round parallel sweep (2026-06-12T19:41:29Z) and confirmed all 8 rounds = 68/68 passing, regenerating the results artifacts.

## Step 8: Finalize PRD — 2026-06-12T19:45:06.000Z

Produced `workspace/PRD_FINALIZED.md` (255 lines, **0% delta — byte-identical to PRD.md**). After full analysis both `<step_7_diff>` items resolve to behavior PRD already uniquely determines; neither is a PRD silence nor a surviving PRD/impl mismatch, so no edits were warranted.

- **Item 1 (test_suite VOID-assertion removal):** PRD §3.3 ("APPROVED and VOID are the proof's terminal states") and §3.8 ("every non-terminal `ArtProof` ... is voided") already pin that an APPROVED proof stays APPROVED on cancel. The deleted assertion contradicted PRD — an over-specified scaffold assertion, not a PRD gap. Impl path `services/lifecycle.py:127-159` (`cancel_order`) voids only `NON_TERMINAL_PROOF`. No edit.
- **Item 2 (impl ordering fix in `schedule_run`):** PRD §2.10's tier-4 enumeration is a closed list that does not include any "order has lines / determinable machine" check, and §3.7 yields `ERR_ORDER_NOT_CONFIRMED` for a non-confirmed order. A faithful PRD-only implementer would already produce the fixed ordering; Step 7 corrected an implementation bug to match PRD. Impl paths `routes/production_runs.py:33-97`, `_order_resource_kind` (22-28), `services/lookups.py:115-116`, confirm precondition `lifecycle.py:37-48` (CONFIRMED order always has ≥1 line). No edit.

## Step 9: Complete PRD — 2026-06-12T19:52:07.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` (255 → 255 lines, char-delta **+1,725**). All changes in-paragraph; no new sections. **8 changes — 6 ambiguity-pins, 2 mismatch-revisions:**

- **§2.4** — insert — ambiguity — pinned `version` creation value to concrete **1** — `db.py:62`.
- **§2.7** — insert — ambiguity — clock-set takes `shop_id` body field, re-serializes `to_iso8601` to millisecond ISO before storing — `routes/clock_routes.py:21,26`.
- **§2.9** — insert — ambiguity — missing/non-integer `expected_order_version` → `ERR_INVALID_REQUEST`; proof `SUBMITTED` state checked before OCC compare (`ERR_INVALID_STATE` precedes `ERR_STALE_ORDER_VERSION`) — `routes/art_proofs.py:96-108`.
- **§3.2** — insert — ambiguity — press also rejects a window directly overlapping a prior non-terminal run, independent of buffer — `services/scheduling.py:59-60`.
- **§3.3** — insert — ambiguity — fresh order initial values: `deposit_paid_cents` 0, `is_rush` null, `final_total_cents` null — `routes/orders.py:57-61`.
- **§3.7** — revise+insert — mismatch — `resource_kind` from order's first line; `window_end` strictly after `window_start` (`ERR_INVALID_REQUEST` up front); wrong/both/neither machine ref → `ERR_INVALID_REQUEST` but after `ERR_ORDER_NOT_CONFIRMED` gate; run QC/pull fields start null — `routes/production_runs.py:22-66,82-88`.
- **§3.9 (FINAL)** — insert — ambiguity — FINAL rush surcharge uses decoration/setup from stored ESTIMATE quote and shop `rush_surcharge_pct` as of invoice time — `services/quote.py:83-90`.
- **§3.9 (quote read)** — insert — mismatch — `GET /orders/{id}/quote` returns an array (paginated) with the single ESTIMATE quote as lone element, empty before confirmation — `routes/orders.py:231-239`.

**Pipeline complete.** Final state: 8/8 parallel rounds, 68/68 tests passing. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md, test_helpers/ + test_suite/ (68 tests), workspace/implementation/ (Flask, in-memory), results.{1..8}.json (all green).
