# Worklog — task_0207_ecommerce_order_returns

## Step 1: Create task directory — 2026-06-06T16:29:17.000Z

Task directory pre-allocated by orchestrator: `tasks/task_0207_ecommerce_order_returns` with `workspace/` subdirectory present. Step 1 auto-scan skipped per instruction. No new directory created.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T16:30:00.000Z

All checks pass. The scaffold is complete and self-consistent.

Generated all three Expert-difficulty scaffold artifacts for **E-commerce Order & Returns (RMA)**. The lint runs clean (`VERDICT: clean lint`, 614 §1.8/§1.9 calls + all 23 FK reverse-reachability checks pass).

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Scaffold contents (Expert band):**
- **Entities: 13** — Customer, Warehouse, Product, InventoryItem, Order, OrderLine, Reservation, Shipment, ShipmentLine, ReturnAuthorization, ReturnLine, Refund, CreditLedgerEntry
- **State machines: 4** — Order (parallel `payment_status × fulfillment_status` dimensions), Shipment (linear + cancel branch), Reservation (HELD→{COMMITTED, RELEASED}), ReturnAuthorization (branching APPROVED→{REFUNDED, EXCHANGED, RESTOCKED}). Plus 2 concurrency rules (OCC on Order.version at checkout, ReturnAuthorization.version at approve).
- **Calculations: 4** — order_totals (tiered shipping + round-per-line-then-sum tax), reservation_waterfall (split/backorder allocation), return_settlement (cash vs store-credit-bonus vs exchange-delta variants), customer_return_risk (lifetime vs trailing-window variants)
- **Validations: 16** (priority-ordered, 8 business categories)
- **Endpoints: 55** (multi-root flat/hybrid topology; `api_prefix: ""`)
- **Errors: 18**
- **Roles: 4** — Anonymous, Customer (entity_backed), WarehouseOperator (opaque), StoreAdmin (opaque)

**Design indices:**
- **§1.8 difficulty: 18 instances** (9 rules × 2), all numeric asserts computed by code (e.g., cash refund 2437 vs store credit 2968, tax 176 not 175 for round-order, shipping tier flip 6345 vs 6045, split 5+3, risk 0.2207)
- **§1.9 corner: 46 instances** (37 full + 9 `excluded_because` stubs citing §1.8 instances) across all 9 claim-extraction-guide sections

Key arithmetic foundations were verified independently in Python before being embedded as literals. No forbidden concurrency vocabulary; all enum values are produced by some transition; all errors are referenced; all grounds resolve; all instance names are unique across both design files.

## Step 3: Copy shared files — 2026-06-06T16:30:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0207_ecommerce_order_returns/workspace/INSTRUCTION.md

## Step 4: Generate PRD — 2026-06-06T16:36:00.000Z

Generated `workspace/PRD.md` for the ecommerce-order-returns domain. **Line count:** 265 lines.

**Sections produced:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 4 roles), 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties & Versioning (CreditLedgerEntry flagged as common_fields:false exception with only id/created_at), 2.5 Derived Fields/Cascades/Hierarchical Consistency (parallel payment×fulfillment Order dimensions), 2.6 Optimistic Concurrency Control (both OCC rules), 2.7 Monetary Precision & Rounding, 2.8 Nested Resource Retrieval & Existence Checks, 2.9 Validation Ordering (priority 1–16 in prose), 2.10 The Test-Driving Clock
- §3 Business Logic — 9 scattered workflow subsections (catalog/inventory, cart pricing, reservation waterfall, capture/void, split shipments, opening returns, deciding returns, settling returns with cash/store-credit/exchange variants, restocking & customer ledgers/risk)
- §4 Endpoint Definitions (4-column table, all 55 endpoints)
- §5 Error Code Catalogue (2-column table, all 18 error IDs)

**Hard Contracts — all PASS:** Field coverage (58/58 entity fields, 30/30 request bodies, 8/8 query params), Rule coverage (16 validations ranked in §2.9, 2 OCC rules, all state transitions, all 4 calculations, sibling-branch symmetry), Path purity (§3 has 0 path tokens). All 6 calculation constants embedded in business context. No fuzzy quantity words.

**Confirmation:** Did NOT read either withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml). All content derived solely from SCAFFOLD.yaml + skill spec.

## Step 5: Generate unit tests — 2026-06-06T16:54:00.000Z

**Test files emitted:** 11 (1 conftest.py + 10 test_*.py) in test_suite/. **Total test functions:** 72, all tagged with exactly one Design: line.

**Provenance breakdown:**
- Queue A (Difficulty, §1.8): 18 instances → 36 tests (every instance ≥2 tests).
- Queue B (Corner, §1.9): 37 non-stub instances → 36 tests (each ≥1 test). 9 excluded_because stubs not translated; all stub cross-refs resolve to real Difficulty instances.

**Instances skipped under PRD-first filter:** 1
- Corner/entities/customer_id_system_generated_input_ignored — asserts supplying a client `id` is rejected with ERR_INVALID_REQUEST. PRD §2.4 says id is server-minted but never states unknown/extra body fields are rejected. Not uniquely derivable. Gap left as gap.

**Coverage audit (all green):** every Difficulty instance ≥2 tests; every non-stub Corner instance ≥1 except documented skip; no tag → stub/nonexistent; no untagged/dual-tagged; no skip/xfail; no scaffold leakage. Citation audit: all 105 quoted PRD sentences verified verbatim.

**test_helpers/ files (9):** __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

## Step 6: Generate implementation — 2026-06-06T16:54:00.000Z

Generated complete Python + Flask implementation. **Self-reported test result: 72/72 passed** across three runs (two concurrent for restart contention) — no flaky restart failures.

**Source files (21):** start.sh, requirements.txt, app.py, db.py, errors.py, response.py, middleware.py; routes/ (customers, warehouses, products[+inventory/reservations], orders[cart/checkout/capture/void/order-lines], shipments, returns[RMA+refunds], clock, __init__); services/ (calc, derive, serialize, fulfillment, clock_util, common, __init__).

**Endpoints:** 55 (34 GET, 21 POST) incl. /_clock/set_current_utc. **Storage:** in-memory only, fresh Store() per boot, no seeding. **start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, guards pip install behind flask-import check.

**Test-driven spec reconciliations (noted for Step 8/9):**
1. Inventory available_qty/reserved_qty count HELD only (not COMMITTED) — COMMITTED already decremented on_hand_qty at ship.
2. lifetime_purchased_cents is one-way lifetime figure — orders count after bubbling to PARTIALLY_REFUNDED/REFUNDED; opening return allowed on PARTIALLY_REFUNDED order; restock allowed on settled RMA.
3. created_at/updated_at derive from logical clock, not wall-clock — trailing-window risk compares created_at vs clock-derived cutoff.

**Evaluator note:** under per-test-server isolation the start-command must be `cd <abs-impl-dir> && bash start.sh` form.

## Step 7: Run tests and iterate — 2026-06-06T17:00:00.000Z

Two consecutive clean 8-round parallel sweeps (16 rounds total, 72/72 every round). The fix is stable.

**Iterations run:** 2 sweeps after the initial baseline (3 total 8-round parallel sweeps). Baseline showed 1 failure; after the fix, two consecutive clean sweeps confirmed stability.

**Root cause diagnosis:** The only failure across the baseline sweep was `test_return_window_closed_one_day_past_boundary` in round 1, failing during fixture setup with:
```
requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /inventory HTTP/1.1\r\n'))
```
This is the classic boot-race signature of Werkzeug's development server: the kernel accepts a TCP connection into the listen backlog before the WSGI handler loop is actually serving it, so the first request after a restart receives a malformed/empty status line. Under this iteration protocol (8 concurrent rounds × a server reboot before every test under per-test-server isolation) dozens of `python3 app.py` processes start simultaneously, and CPU contention widens that accept-before-ready window. It is infrastructure flakiness, not a logic bug — the test passed in the other 7 rounds with the same assertions.

**Tests deleted:** None. The lone failure was a transient connection error, not a PRD-coverage or unique-derivability problem. All 72 tests trace to PRD prose.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/ (infrastructure hardening only, no PRD behavior touched):**
- `workspace/implementation/app.py` (`__main__` block): Switched the WSGI server from Flask's dev server to `waitress.serve(..., threads=8)`, whose accept loop is bound to its worker threads and does not expose the accept-before-ready window. Falls back to `app.run(threaded=True)` via `ImportError` guard so the app still runs in a bare environment.
- `workspace/implementation/requirements.txt`: Added `waitress==3.0.0`.
- `workspace/implementation/start.sh`: Extended the idempotent install guard from `import flask` to `import flask, waitress` so a fresh environment installs both, while still skipping reinstall (and the associated boot contention) when both are already present.

State remains in-memory only (fresh `Store()` per boot); no seeding, no persistence — start.sh re-invocation wipes all state. **Final result: 72/72 passing in all 8 rounds across two consecutive parallel sweeps.**

## Step 8: Finalize PRD — 2026-06-06T17:03:00.000Z

Done. `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` — zero behavioral edits.

**Line counts:** PRD.md = 265 lines, PRD_FINALIZED.md = 265 lines. Delta: 0 lines, 0.0%.

**Changes:** Zero edits. Every item in <step_7_diff> is infrastructure-only and traces to no PRD-describable behavior:
- app.py:66-80 — switched __main__ launch block from Flask dev server to waitress.serve(threads=8) with ImportError fallback. WSGI-host choice; PRD describes no server.
- requirements.txt:2 — added waitress==3.0.0. PRD carries no dependency manifest.
- start.sh:7 — extended idempotent install guard from `import flask` to `import flask, waitress`. PRD describes no install/launch procedure.

The fix was a transient boot-race connection error (BadStatusLine on first post-restart request), not a logic bug. No tests deleted, no test_helpers/test_suite fixes, no implementation behavior path touched. HTTP request/response contract (envelopes, status codes, error IDs, state machines, calculations) is produced entirely by the Flask blueprints/error handlers in create_app(), byte-identical regardless of WSGI host.

**Pre-edit search log:** All three diff items subjected to mandatory subject-identification + impl-path enumeration before being rejected as non-edits (WSGI host, dependency manifest, launcher guard — none PRD-describable). Confirmatory diff shows PRD_FINALIZED.md identical to PRD.md.

## Step 9: Complete PRD — 2026-06-06T17:13:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over PRD_FINALIZED.md, pinning every PRD ambiguity/mismatch to what implementation/ actually does.

**File metrics:** Source PRD_FINALIZED.md = 265 lines / 44,390 chars; PRD_COMPLETED.md = 265 lines / 48,395 chars (char delta +4,005; 11 lines revised in place, 0 new paragraphs/sections).

**Counts:** ambiguity-pins = 8, mismatch-revisions = 5 (13 distinct behaviors across 11 edited lines).

**Per-change:**
- §2.4 — revise — ambiguity — version "starts at 1 on creation" — db.py:53
- §2.10 — revise — ambiguity — created_at/updated_at/shipped_at/delivered_at stamped from logical clock (envelope api_request_timestamp is lone wall-clock); clock defaults to wall-clock at boot; clock-set returns empty object at 200 — db.py:39-70, response.py:14-17, routes/clock.py:26
- §3.1 — revise — mismatch — InventoryItem.reserved_qty counts only HELD (not HELD or COMMITTED; committing already decrements on_hand_qty) — services/derive.py:11-21
- §3.3 — revise — ambiguity — OrderLine.reserved_qty is live HELD+COMMITTED count (persists post-ship, drops on void), distinct from InventoryItem's; backordered_qty is frozen checkout snapshot — services/derive.py:31-36, services/serialize.py:98
- §3.4 — revise — ambiguity — void failures pinned to ERR_INVALID_STATE (409) — routes/orders.py:237-242
- §3.6 — revise — mismatch — opening return allowed on CAPTURED or PARTIALLY_REFUNDED orders — routes/returns.py:93
- §3.6 — revise — ambiguity — order-line-not-belonging-to-order → ERR_VALIDATION (422) — routes/returns.py:99
- §3.6 — revise — ambiguity — "quantity already returned" = returned_qty summing return lines of RMAs in APPROVED/REFUNDED/EXCHANGED/RESTOCKED — services/derive.py:50-58
- §3.8 — revise — mismatch — zero/positive exchange delta creates no Refund and no CreditLedgerEntry (only RMA settlement_cents); negative-delta refund amount_cents is absolute value; replacement reservation uses checkout waterfall — routes/returns.py:341-399
- §3.9 — revise — mismatch — restock permitted on refund-bearing return in APPROVED/REFUNDED/EXCHANGED; state-then-refund-then-warehouse check order; creates inventory row if absent — routes/returns.py:410-453
- §3.9 — revise — mismatch — lifetime_purchased_cents counts orders ever captured (CAPTURED, PARTIALLY_REFUNDED, REFUNDED), not only CAPTURED — services/derive.py:77-85
- §3.9 — revise — ambiguity — credit-adjustment returns the created CreditLedgerEntry (201), not the customer — routes/customers.py:114-135
- §3.9 — revise — ambiguity — window_days must be non-negative integer (else ERR_VALIDATION 422); /customers/{id}/risk returns full Customer object with three ledger figures + windowed risk (lifetime when omitted) — routes/customers.py:42-75

**Deliberately not changed:** uniqueness violations + qty-below-one already resolved by §2.9 generic-422 clause; customer/clock self-service auth exemption already governed by §2.1; local add_order_line/create_inventory ordering deviations only affect inputs no path can observe, so global §2.9 ordering left intact.

---

## Pipeline complete

All 9 steps finished. Final 8-round parallel stability sweep: **72/72 passing in all 8 rounds.**

Final artifacts in tasks/task_0207_ecommerce_order_returns/:
- SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml (Expert difficulty)
- worklog.md
- test_helpers/ (9 files), test_suite/ (conftest + 10 test files, 72 tests)
- workspace/INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (= PRD.md), PRD_COMPLETED.md, implementation/ (Python+Flask, 55 endpoints)
