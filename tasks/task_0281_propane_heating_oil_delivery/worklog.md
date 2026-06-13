# Worklog — task_0281_propane_heating_oil_delivery

## Step 1: Create task directory — 2026-06-10T00:00:00.000Z

Created `tasks/task_0281_propane_heating_oil_delivery/` and `tasks/task_0281_propane_heating_oil_delivery/workspace/` (pre-assigned/reserved index, no re-scan). Scenario: Propane / Heating Oil Delivery (Expert difficulty).

## Step 2: Generate scaffold — 2026-06-10T00:00:00.000Z

All three files are present, parse cleanly, and the scaffold lint passes with a clean verdict. (Note: `worklog.md` and `workspace/` already existed in the directory; I did not touch them and they are unrelated to this scaffold task — I read no sibling task directories.)

The scaffold generation is complete.

## Summary

Generated a complete Expert-difficulty scaffold for **Propane / Heating Oil Delivery** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0281_propane_heating_oil_delivery/`. All three files pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Complexity profile:** primary archetype `pricing_engine` + secondary `ledger_reconciliation`; layers dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation; hybrid topology, branching/parallel state-machine shape, peer-roles, immediate consistency. `api_prefix` set to empty so resources are globally addressable by id (`GET /<collection>/{id}`) with FK-filterable lists — needed for the linter's reverse-reachability derivation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities:** Account (OCC parent), PricePlan, Tank, TankMonitorReading, DegreeDayReading, MarketPrice, TankLease, SafetyInspection, Truck, DeliveryRoute, DeliveryOrder, BudgetPlan.
- **8 state machines:** Account, PricePlan, Tank (parallel service/reorder dimensions), TankLease, MarketPrice, DeliveryRoute, DeliveryOrder (cyclic HOLD↔SCHEDULED + branching + compensation), BudgetPlan.
- **6 calculations:** tank_reorder_projection (dual variant MONITOR_BASED vs DEGREE_DAY_ESTIMATE), budget_reconciliation (dual variant PROVISIONAL vs FINAL), monthly_installment, delivery_price (tiered FIXED/CAP/MARKET with min/max + volume tiers), invoice_total (pinned per-line rounding), auto_delivery_target.
- **14 validations** (priority-ordered), **56 endpoints**, **27 errors**, **6 roles** (AccountManager/Dispatcher/Driver/Inspector opaque; Customer entity_backed:Account; System opaque), **2 concurrency rules** (OCC on Account.version for deliver + reverse, both 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 18 instances — all 9 Difficulty Rules × 2, each grounded in §1.1–§1.7 with executable empty-DB setup chains and pre-computed literal asserts (e.g. CAP price 295, emergency invoice 110916, reorder boundary at exactly pct 30 = DUE, budget settlement 58500→0).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 50 instances across all 9 claim-extraction sections (45 full recipes + 5 `excluded_because` stubs pointing at §1.8 instances) — covering CRUD, defaults, system-field immutability, FK reverse-reachability, invalid-transition/terminal-state lockdown, precondition errors, calculation correctness, RBAC denial/ownership, OCC success+stale, derived-field reconciliation, and immediate consistency.

Verified: all grounds resolve, no name collisions across both design files, all stub references exist, every error is referenced, no forbidden concurrency vocabulary, no id-based business decisions, no fuzzy selector adjectives, and correct file split (neither design key appears in SCAFFOLD.yaml).

## Step 3: Copy shared files — 2026-06-10T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0281_propane_heating_oil_delivery/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-10T00:00:00.000Z

Generated `workspace/PRD.md` — prose PRD for Propane / Heating Oil Delivery API (~50 KB, 310 lines; 27 errors / 12 entities / 5 calculations / 14 validations / 56 endpoints).

Structure: §1 Introduction; §2 Global Specifications (11 subsections: RBAC + role identities, fixed envelope, pagination, identity/timestamp/versioning, hierarchical consistency & cascades, nested-path validation order, OCC on account ledger, validation priority ordering, money/quantity precision, logical clock, regional config); §3 Business Logic (10 lifecycle subsections); §4 endpoint table (56 rows); §5 error table (27 rows).

Coverage (all three Hard Contracts PASS, verified programmatically): Contract 1 field-name coverage 58/58 + 11 path params + 6 roles, 0 missing. Contract 2 rule coverage: all 21 state-transition pairs in FROM → TO notation with preconditions/errors/side-effects/cascades; both OCC rules express expected_account_version + ERR_STALE_VERSION + HTTP 412; all 5 calculations rendered as precise prose with no pseudocode; validation priority order stated. Contract 3 §3 path purity: 472 tokens scanned, 0 path leaks. All 27 error IDs in narrative + table.

## Step 5: Generate unit tests — 2026-06-10T00:00:00.000Z

Generated complete test infrastructure for task_0281_propane_heating_oil_delivery (Propane / Heating Oil Delivery, Expert).

test_helpers/ (9 modules): types.py (entity TypedDicts; immutable TankMonitorReading/DegreeDayReading carry only id+created_at), api_client.py (ApiClient with one method per endpoint — 56 endpoints incl. /_clock/set_current_utc), api_errors.py (all 27 ApiErrorIds + HTTP-status map), assertions.py (per-entity structural assertions + route-reservation-conservation checker), factories.py (per-entity input-only payload factories), constants.py (calculation thresholds), test_users.py (opaque headers for 4 operator roles + System; make_customer_headers(account_id) for entity_backed:Account Customer), fixtures.py (5-tier composite setup helpers), __init__.py.

test_suite/ (8 test files + conftest) — 81 test functions, each tagged with exactly one verbatim Design: line.

Queue coverage: Queue A (Difficulty) 18/18 instances translated, ≥2 tests each (36 difficulty-tagged tests). Queue B (Corner) 45/45 non-stub instances translated, ≥1 test each (45 corner-tagged tests). 5 excluded_because stubs not translated (cross-refs verified). No non-stub instances skipped. One asserted outcome dropped under PRD-first unique-derivability filter: route_window_buffer_conflict_on_truck's "gap exactly 60 == buffer admitted" assertion (not uniquely derivable — literal reader double-counts buffer); instance still covered by two uniquely-derivable conflict tests.

Verification: all 18 modules compile; all 103 PRD citations confirmed verbatim-present; every docstring ends with exactly one resolving Design: line; no skip/xfail; no scaffold leakage; all error IDs / api.* methods / fx.* fixtures / imports resolve.

## Step 6: Generate implementation — 2026-06-10T00:00:00.000Z

Built complete Python + Flask REST API in workspace/implementation/.

Files: start.sh (reads $PORT default 10000, binds 0.0.0.0, exec foreground, pip install guarded behind import flask check), requirements.txt (flask==3.0.3), app.py (blueprint registration, error handlers ApiError→envelope, 404/405/400 mapped to catalog, app.run host 0.0.0.0 port $PORT), clock.py (logical system clock §2.10, ISO-8601-UTC-millis), db.py (in-memory dicts keyed by id; touch bumps version vs touch_no_version; no seeding at import), errors.py/response.py/middleware.py/common.py, services/calculations.py (reorder projection both variants, delivery_price FIXED/MARKET/CAP + volume tiers + 50¢ floor, invoice_total per-line surcharge rounding then sum + off-route fee, monthly_installment, settlement_balance; Decimal/ROUND_HALF_UP for money, floor for gallons/percent), services/lookups.py, routes/ (accounts, price_plans, tanks, readings + degree-day, market_prices, leases, inspections, trucks + routes, orders, budget_plans, clock_route).

Confirmations: in-memory only (module-level dicts in db.py); no SQLite/JSON/tmp/disk; nothing seeded at startup (verified total_count 0 on fresh boot); start.sh reads $PORT, binds 0.0.0.0, runs foreground via exec.

Verification: two smoke suites (57 checks, all passing) covered auth/role/ownership, full create→activate→schedule→dispatch→deliver→reverse lifecycle, FIXED+CAP pricing with volume tier 2 + emergency surcharge + off-route fee, OCC stale-version 412, cascading delivery effects, budget installment/reconcile true-up, both projection variants, generate-auto-order fill-to-capacity, safety/capacity/window/lease-overlap/account-close guards, half-open lease adjacency, pagination meta, success/error envelopes.

## Step 7: Test and iterate to green — 2026-06-10T00:00:00.000Z

Clean exit — all 8 parallel rounds pass 81/81.

**Iterations run:** 2 (baseline sweep showing 6 consistent failures, then one fix sweep → all clean).

**Root cause:** All 6 failures were TypeErrors raised in the test layer (never reached the implementation). They were three distinct test/helper argument-shape bugs, all PRD-faithful in intent. No implementation bug existed.

**Tests deleted:** None. Every failing test verbatim-covers a PRD rule and is uniquely derivable (route window conflict §3.5, lease half-open overlap §3.9, unassign-on-dispatched-route ERR_ROUTE_ALREADY_DISPATCHED §3.6, deliver-without-plan ERR_NO_ACTIVE_PRICE_PLAN §3.6). The failures were mechanical, not coverage problems.

**Fixes applied to test_suite/** (assertion/call layer, made more faithful to PRD's RBAC):
- test_04_routes_and_scheduling.py — test_route_window_buffer_conflict_on_truck and test_route_window_direct_overlap_conflict_on_truck: added the missing DISP (Dispatcher) headers arg to two api.create_route(...) calls. PRD line 258 mandates Dispatcher for POST /trucks/{truckId}/routes.
- test_07_leases_inspections_budget.py — test_lease_touching_interval_admitted and test_lease_overlapping_interval_rejected: added the missing AM (AccountManager) headers arg to two api.create_lease(...) calls. PRD §3.9 ("An account manager creates one") mandates AccountManager.

**Fixes applied to test_helpers/:**
- fixtures.py — setup_order_on_dispatched_route(): added a with_plan=True parameter and forwarded it to the underlying setup_order_scheduled_on_planning_route() (which already had it). The fixture was missing the kwarg that two tests (test_unassign_dispatched_route_order_rejected, test_deliver_without_active_price_plan_rejected) pass as with_plan=False to set up the no-active-plan precondition. Confirmed the implementation's deliver-guard ordering (routes/orders.py:246) correctly surfaces ERR_NO_ACTIVE_PRICE_PLAN for that precondition.

**Fixes applied to implementation/:** None — the implementation was already correct on all 6 rules.

## Step 8: Finalize PRD — 2026-06-10T00:00:00.000Z

Outcome: No changes. PRD_FINALIZED.md is a verbatim copy of PRD.md (310 lines each, 0 line delta, 0% change).

Changes: None — all Step 7 items were test-layer fixes against already-pinned PRD behavior. All four behaviors covered by the six failing tests are mechanical test/helper argument-shape bugs (missing RBAC role-header args, a missing fixture kwarg). Each verifies behavior the PRD already determines uniquely, and the implementation already matches the PRD verbatim. No PRD silence and no PRD/impl mismatch to pin.

Per-item analysis:
1. Route window conflict (test fix: missing DISP header on create_route) — Subject: route window collision + RBAC for POST /trucks/{truckId}/routes. Impl: routes/trucks.py:67-101 (require_role Dispatcher :70; buffer-extended closed-interval overlap :87-99, skipping CANCELLED). Matches PRD line 169 + line 258. No edit.
2. Lease half-open overlap (test fix: missing AM header on create_lease) — Subject: lease interval overlap + RBAC for POST /tanks/{tankId}/leases. Impl: routes/leases.py:20-56 (require_role AccountManager :23; half-open start<o_end and o_start<end vs ACTIVE :36-45). Matches PRD line 205 + line 248. No edit.
3. Unassign on dispatched route (fixture fix) — Subject: SCHEDULED→CREATED unassign guard. Impl: routes/orders.py:177-197 (rejects DISPATCHED parent with ERR_ROUTE_ALREADY_DISPATCHED :186-188). Matches PRD line 181. No edit.
4. Deliver without active price plan (fixture-kwarg fix, with_plan=False) — Subject: deliver-guard precondition ordering, ERR_NO_ACTIVE_PRICE_PLAN. Impl: routes/orders.py:245-292 (ordered checks: status, route DISPATCHED, tank IN_SERVICE, active plan :272-275, market price, overfill, stale version). Matches §2.8 ordering + PRD line 183. No edit.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-10T00:00:00.000Z

Produced workspace/PRD_COMPLETED.md as a minimal patch over PRD_FINALIZED.md.

Counts: Source (PRD_FINALIZED.md) 310 lines / 50,628 chars; Result (PRD_COMPLETED.md) 310 lines / 52,822 chars (char delta +2,194). Changes: 10 total — 9 ambiguity-pins, 1 mismatch-revision. No new sections; 28 headings in both.

Per-change log:
- §2.2 — insert — ambiguity — pinned api_request_timestamp to real wall-clock, independent of the logical clock — response.py:27-32
- §2.3 — insert — ambiguity — pinned bad limit/offset (non-int, limit outside 1–100, negative offset) → ERR_INVALID_REQUEST — common.py:13-44
- §2.3 — insert — ambiguity — pinned list tie-break (id ascending) and exact has_more formula — common.py:58, response.py:49
- §2.10 — insert — ambiguity — pinned clock fallback to real wall-clock when never set, to_iso8601 parse-or-ERR_INVALID_REQUEST, empty-object 200 response — clock.py:56-60, clock_route.py:14-24
- §3.5 — revise — mismatch — corrected route-window conflict from PRD's "each window extended by the buffer" (2×buffer) to impl's single-buffer rule (gap must strictly exceed buffer; new window extended once on each side vs un-extended existing) — trucks.py:87-101
- §3.6 — insert — ambiguity — pinned create_order tank_id validation (missing/non-string/non-resolving/not-on-account → ERR_INVALID_REQUEST) — orders.py:50-63
- §3.6 — insert — ambiguity — pinned assign route_id validation: presence as body well-formedness, non-resolving route → ERR_INVALID_REQUEST after the order-state check — orders.py:133-144
- §3.6 — insert — ambiguity — pinned deliver requires integer delivered_gallons ≥1 and expected_account_version as body well-formedness (ERR_INVALID_REQUEST) before state/business checks — orders.py:252-253
- §3.8 — insert — ambiguity — pinned "most recent inspection" ordering key (inspected_at, ties broken by later created_at) — lookups.py:58-71
- §3.10 — insert (×2) — ambiguity — pinned that installment posting and reconciliation refresh account updated_at but do NOT increment Account.version — budget_plans.py:104-105,127-128, db.py:57-65

Key finding (the one true mismatch): route-window conflict prose in §3.5 said both windows are "each extended by the turnaround buffer" (implies 2×buffer separation); the implementation extends only the new window once on each side and compares against the un-extended existing window (gap must merely exceed one buffer). Tests don't exercise the divergent gap range, so this was a latent PRD-vs-impl mismatch now revised to the implementation's single-buffer semantics.

## Pipeline complete — 2026-06-10T00:00:00.000Z

All 9 steps complete. Final 8-round stability sweep: 81/81 tests pass in all 8 parallel rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (verbatim) → PRD_COMPLETED.md (10 edits), test_helpers/ (9 modules) + test_suite/ (8 files, 81 tests), workspace/implementation/ (Python/Flask, in-memory).
