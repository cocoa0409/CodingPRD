# Worklog — task_0727_vinyl_records_shop

## Step 1: Create Task Directory — 2026-07-04T00:00:00.000Z

Task directory pre-assigned: tasks/task_0727_vinyl_records_shop (with workspace/). Skipped ./tasks/ scan and auto-numbering per orchestration instructions. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-04T06:15:00.000Z

Generated three Expert-difficulty scaffold files for task_0727_vinyl_records_shop (Vinyl Records & Used-Media Shop).

Files written: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

Counts:
- Entities: 13 (Customer, Product, Allocation, InventoryItem, TradeIn, TradeInLine, Order, OrderLine, PreOrder, Consignment, DisplaySlot, GradingDispute, SpecialOrder)
- Endpoints: 70 (includes reverse-reachability GETs for all 13 FK relationships, plus 2 test-driving endpoints: /shop/_clock/set_current_utc, /shop/_loyalty/adjust-points)
- Calculations: 6 · State machines: 8 · Validations: 15 · Errors: 16 · Roles: 5 (peer-role model) · Concurrency rules: 1 (OCC on Allocation.version)
- Difficulty rules (§1.8): 18 instances — all 9 §0.5 rules × 2 instances each
- Corner cases (§1.9): 22 active instances + 3 excluded_because stubs across all 9 claim-guide sections

Complexity profile: Quota/allocation (RSD pre-order pools) + ledger-reconciliation secondary; hybrid topology; parallel Order state machine (payment × fulfillment) plus cyclic GradingDispute; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.

Verification: scaffold_lint.py reports VERDICT: clean lint — 226 §1.8/§1.9 calls all conform to §1.5; every §1.1 FK has a reverse-reachability GET; all excluded_because stubs reference §1.8 instances that exist by name.

Note: endpoint count (70) is above the Expert band's 20–32 guideline, driven by mandatory FK reverse-reachability GETs (one per FK across 13 entities) plus 10 sub-workflows needing action endpoints.

## Step 3: Copy Shared Files — 2026-07-04T06:17:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0727_vinyl_records_shop/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-04T06:25:00.000Z

Generated workspace/PRD.md for the vinyl-records-shop domain.

Structure: 5 top-level sections, 19 subsections, ~286 lines.
- §1 Introduction (business-context)
- §2 Global Specifications — 9 subsections (RBAC, fixed §2.2 envelope verbatim, pagination, common properties, precision/grades, OCC on Allocation, cascade consistency, nested-path validation, validation precedence)
- §3 Business Logic — 10 scattered subsections (catalog/stocking, order assembly, payment+loyalty, fulfillment/cancel, allocation/pre-order/pickup, trade-ins, consignment, grading-dispute regrade cascade, special orders, operator/test-driving)
- §4 Endpoint table (73 endpoints), §5 Error catalogue (16 errors)

Documented: 14 entities, 8 state machines, 6 calculations, single OCC concurrency rule, all 13 priority-ordered validations.

Hard Contracts: Contract 1 Field-Name Coverage 73/73 PASS; Contract 2 Rule Coverage PASS; Contract 3 §3 Path Purity PASS. All 16 error IDs in prose + §5 table. §2.2 emitted byte-for-byte. Withheld design files not opened.

## Step 6: Generate Implementation — 2026-07-04T06:45:00.000Z

(Note: Steps 5 & 6 run sequentially, not concurrent, because background subagents stall on this host. Isolation preserved deterministically: Step 6 ran FIRST while test_suite/ did not exist; Step 5 will run next with an explicit ban on reading implementation/.)

Generated complete Python + Flask implementation in workspace/implementation/.

Files: start.sh (foreground launcher; reads $PORT default 10000, binds 0.0.0.0, guards pip install on `import flask` check, exec python3 app.py), requirements.txt, app.py (factory + error handlers + blueprint registration), db.py (in-memory store, logical clock default 2026-03-01T00:00:00Z, UUID/ISO helpers), models.py, response.py (meta/response_type/data envelope), middleware.py (X-User-ID/X-User-Role auth + RBAC), errors.py, validators.py, calculations.py (Decimal ROUND_HALF_UP), services.py (cascades/recomputes); routes/: customers, products (+catalog lifecycle+allocations), inventory, orders (+order-lines), tradeins, preorders, consignments (+display-slots), disputes, specialorders, admin (clock+loyalty).

Endpoints: all ~70 from PRD §4 including the two test-driving admin endpoints. In-memory dicts only; no seeding at startup.

Key spec-fidelity decisions:
- authorize-payment: gated on ≥1 line, payment UNPAID, not-cancelled (NOT fulfillment==PENDING, since adding a line sets RESERVED, which would make AUTHORIZED unreachable — per scaffold note "payment advances independently of fulfillment").
- Trade-in reversal claws back final_value_cents per literal PRD §3.6 wording.
- TradeInLine carries no product FK, so approval mints a minimal backing Product (base = line's base_value_cents) per created used InventoryItem so list_price_cents is computable.

Confirmed: start.sh reads $PORT, binds 0.0.0.0, foreground exec, boots clean from fresh empty process each invocation.

## Step 5: Generate Unit Tests — 2026-07-04T07:10:00.000Z

Generated complete test infrastructure, authored purely from PRD + two design indices (implementation/ never inspected).

test_helpers/ (9 files): __init__.py (barrel export), types.py (14 entity TypedDicts + 11 enums), api_client.py (~65 methods incl. _clock/_loyalty), api_errors.py (16 errors + HTTP map), assertions.py (per-entity + assert_allocation_invariants three-counter partition + assert_order_totals_consistent), factories.py (payload factory per entity), constants.py (grade/buy multipliers, commission tiers, loyalty thresholds, buffer days), test_users.py (TEST_USERS + make_customer_headers), fixtures.py (tiered composite helpers).

test_suite/ (conftest + 8 test files, 59 tests): catalog/inventory, orders/pricing/loyalty, trade-ins, consignments, disputes/cascades, allocations/pre-orders, validation-precedence/RBAC, refund-conservation.

Coverage: Queue A (Difficulty) all 18 instances translated, ≥2 tests each (36+), none skipped. Queue B (Corner) all 20 non-stub instances translated (≥1 each); 3 excluded_because stubs not translated (cross-refs verified to resolve). No skips — PRD states every asserted rule verbatim and uniquely derives each expected value.

Verification: pytest --collect-only = 59 tests, zero errors; all files byte-compile; every docstring ends with one verbatim Design: tag; no scaffold/§/Table leakage; no skip/xfail.

## Step 7: Run Tests and Iterate — 2026-07-04T07:30:00.000Z

All 8 rounds pass cleanly (59/59 each). Ran as 2 waves of 4 per host-saturation constraint.

Iterations run: 2 (baseline sweep + 1 fix iteration). Baseline showed 3 consistent failures across all 8 rounds (not flaky); after fixes, all 8 rounds pass 59/59.

Tests deleted: None. All three failures were test-artifact bugs, not PRD-silence issues.

Fixes applied to test_suite/:
- test_07_validation_precedence_and_rbac.py — test_fulfill_online_order_wrong_channel_rejected: changed asserted error from ERR_DEPENDENCY_NOT_READY to ERR_INVALID_STATE. Test fulfills a PAID ONLINE order via the IN_STORE /fulfill endpoint. PRD §3.4 scopes ERR_DEPENDENCY_NOT_READY to "while payment has not settled" — payment is settled here; channel mismatch is a state-validity failure → ERR_INVALID_STATE (§2.9). Design name confirms intent. Made more faithful, not weakened.

Fixes applied to test_helpers/ (via test_suite fixture):
- test_06_allocations_preorders.py — fixture _two_preorders_first_ready: added api.list_product + api.open_preorders to advance RSD product DRAFT→LISTED→PRE_ORDER_OPEN before readying. Two pickup-capacity tests failed because fixture never advanced catalog_status, so readying po1 correctly tripped PRD §3.5 cross-entity guard (ERR_DEPENDENCY_NOT_READY). Fixed the fixture precondition rather than removing the PRD-required impl check.

Fixes applied to implementation/: None. Impl was PRD-faithful in all three cases; failing checks (catalog_status readiness guard, ERR_INVALID_STATE for wrong-channel fulfill) trace to verbatim PRD prose and were preserved.

## Step 8: Finalize PRD — 2026-07-04T07:40:00.000Z

Produced workspace/PRD_FINALIZED.md. PRD.md 286 lines vs PRD_FINALIZED.md 286 lines, 0% line-count delta (one in-paragraph revision in §3.4).

Changes (1 edit):
- §3.4 (Fulfillment) — revise — Pinned the channel-mismatch error and its precedence: invoking the wrong fulfillment endpoint for the order's channel (/ship on IN_STORE, /fulfill on ONLINE) yields ERR_INVALID_STATE, evaluated before the PAID payment readiness guard — so a wrong-channel call on an already-PAID order returns ERR_INVALID_STATE not ERR_DEPENDENCY_NOT_READY. — implementation/routes/orders.py:204-209 (ship), :218-223 (fulfill).

Pre-edit search: enumerated ship_order (orders.py:200-211) + fulfill_order (:214-225), both order state-validity (channel) check before payment guard; grepped all channel usages (creation :38-46, :206, :220) — no other endpoint branches on channel; confirmed §2.9 precedence places state-validity (5th) before cross-entity readiness (6th), consistent with impl.

Item NOT edited: catalog_status readiness guard (§3.5) — PRD already states the cross-entity guard verbatim; the Step 7 change was a pure fixture precondition bug, not a PRD silence.

## Step 9: Complete PRD — 2026-07-04T07:43:00.000Z

Produced workspace/PRD_COMPLETED.md (source: PRD_FINALIZED.md). 286 vs 286 lines; char delta +1,936 (all in-paragraph, no new lines/sections).

Counts: 14 ambiguity-pins, 5 mismatch-revisions (19 discrete pins).

Largest real mismatches revised to match impl:
- §3.5 waitlist-promotion semantics: per-Allocation (not per-product), fires only on pre-order cancellation (services.py:90-105, preorders.py:214).
- §3.5 ERR_ALLOCATION_EXHAUSTED unreachable: half-open window guard runs first, so pool exhaustion always waitlists while window open (preorders.py:65-86).
- §2.7 order cancellation touches no allocation counter and triggers no waitlist promotion; only pre-order cancellation promotes (orders.py:258-265).
- §3.3 authorize-payment requires ≥1 line + not-cancelled, NOT fulfillment_status==PENDING (orders.py:159-167).
- §3.7 consignment expiry sweep fires on read/list not activation, skips returning a SOLD copy (services.py:131-146).

Ambiguity-pins covered: positive-integer input validations (base_price_cents, allocation_total, pickup_concurrency≥1, new_list_price_cents, consignment list_price_cents, base_value_cents), duplicate email rejection, credit_applied_cents default 0, points-reversal/adjust-points floor-at-zero, readying catalog_status set + absent-copy guard, activation slot-skip when no display_slot_id, special-order arrival mints NM used=false copy, trade-in copy minted DRAFT Product backing + reversal ERR_INVALID_STATE when created copy RESERVED/SOLD, trade-in lines addable only while DRAFT.

## Pipeline Complete — 2026-07-04T07:44:00.000Z

All 9 steps complete. Final 8-round stability sweep: 59/59 tests pass in all 8 rounds. Deliverables in place: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), workspace/PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (59 tests), workspace/implementation/ (Flask, in-memory, start.sh).
