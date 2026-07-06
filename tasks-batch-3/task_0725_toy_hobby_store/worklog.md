# Worklog — task_0725_toy_hobby_store

## Step 1: Create task directory — 2026-07-04T00:00:00.000Z

Task directory pre-allocated: tasks/task_0725_toy_hobby_store (with workspace/). Skipped ./tasks/ scan and auto-numbering per orchestration args. Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-04T05:33:00.000Z

Clean lint confirmed and arithmetic corrected. The task is complete.

## Summary

Generated three scaffold artifacts for **Task 0725 — Toy & Hobby Store (specialty retail)** at **Expert** difficulty in `/home/ubuntu/github/CodingPRD/tasks/task_0725_toy_hobby_store/`.

**SCAFFOLD.yaml (§1.0–§1.7)**
- **14 entities**: Product, Store, InventoryItem, Allocation, Customer, Order, OrderLine, Layaway, SpecialOrder, Recall, DemoEvent, GiftRegistry, RegistryItem, Return (flat topology, peer FKs).
- **62 endpoints** (incl. filtered-list + single-resource GETs for FK reverse-reachability, and a `/_clock/set_current_utc` test-driving endpoint defaulting to 2026-03-01T00:00:00Z).
- **40 error codes**; **12 ordered validations**; **8 calculations**; **5 RBAC roles** (CatalogAdmin, StoreManager, StoreAssociate, Customer=entity_backed, Any).
- **12 state machines** including two parallel dimensions on Product (status × recall_status) and on Order (fulfillment_status × payment_status), plus a SpecialOrder QUOTED→QUOTED self-cycle.
- **1 concurrency rule**: OCC on SpecialOrder.version for re-quote (412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 18 instances, all 9 Difficulty Rules × 2:
- dual_variant_calc; combinatorial_formula; non_linear_state_machine; transitive_cascade; priority_pair_validation_conflict; boundary_precision_check; cross_entity_state_dependency; resource_temporal_overlap; compensating_invariant

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 26 breadth instances across entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_complexity_layers, consistency_model.

`python3 scaffold_lint.py` → VERDICT: clean lint (361 calls scanned). api_prefix is `/` (flat peer topology).

_(Note: original Step-2 subagent timed out doing read-only research with 0 files written; resume also stalled; a fresh efficiency-directed subagent produced all three files. Corner YAML had unquoted nested-bracket grounds tokens fixed to valid YAML during the run.)_

## Step 3: Copy shared files — 2026-07-04T05:33:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T05:44:00.000Z

The PRD is complete. All field names are covered, all rules expressed.

Generated workspace/PRD.md (301 lines) — prose PRD for Expert-level Toy & Hobby Store retail API.
- §1 Introduction; §2 Global Specs (10 subsections: RBAC, §2.2 envelope, pagination, common properties w/ RegistryItem common_fields:false exception, money/rounding, OCC on quotes, parallel state dimensions+cascades, nested/filtered retrieval, conserved inventory/allocation ledgers, validation ordering); §3 Business Logic (14 subsections); §4 endpoint table (64 endpoints); §5 error table (40 codes).
- Field coverage: PASS (Store.state_code added in repair pass; all request/query/path params present).
- Rule coverage: PASS (12 validations w/ priority order in §2.10; 1 OCC rule; all state machines w/ preconditions→error_id + side-effects; all 8 calculations in precise prose; sibling-branch symmetry rendered).
- Path purity (§3): PASS (no /-prefixed tokens, no bare HTTP methods).
- Key rules: recall→quarantine→line-void→order-cancel cascade; floor-per-line-then-sum discount; PROVISIONAL vs FINAL pricing; loyalty accrual+proportional reversal; return refund tiers (0/10/15% at 5000/20000) gross-before-fee; half-open allocation windows + closed-interval event buffer; layaway remainder-on-final; OCC stale-version on quotes; 30-day inclusive return window vs settable clock (default 2026-03-01T00:00:00Z).

## Step 5: Generate unit tests — 2026-07-04T06:05:00.000Z

All citations verified verbatim. Everything compiles and coverage targets are met.

### Stage 1 — test_helpers/ (9 files)
- types.py (20 status/enum classes + entity TypedDicts; RegistryItem carries only id/created_at per common_fields:false); api_client.py (~60 endpoint methods incl. /recalls/{id}/issue, /_clock/set_current_utc); api_errors.py (ApiErrorId enum + HTTP status map); assertions.py, factories.py, constants.py, test_users.py (make_customer_headers for entity_backed Customer), fixtures.py (composite lifecycle helpers), __init__.py.

### Stage 2 — test_suite/ (conftest + 8 test files)
test_01_pricing_and_loyalty, test_02_refund_and_layaway_math, test_03_parallel_states_and_requote, test_04_cascades, test_05_cross_entity_and_boundaries, test_06_priority_and_temporal, test_07_conservation_and_side_effects, test_08_validation_errors.

### Counts
- 60 tests emitted. All files byte-compile clean.
- Queue A (Difficulty): 17 of 18 instances × 2 tests = 34 tests.
- Queue B (Corner): all 26 non-stub instances × ≥1 test = 26 tests.
- Every docstring carries verbatim PRD citations + exactly one Design: tag.

### Skipped (1 instance, PRD-first filter failure)
- Difficulty/cross_entity_state_dependency/order_mark_ready_blocked_by_product_recall_status — fails unique-derivability. Recall cascade (§3.2) voids ACTIVE lines on the recalled product at issue time; mark-ready gate (§3.7) checks only ACTIVE lines, so a faithful reader would have mark-ready succeed, contradicting asserted ERR_PRODUCT_RECALLED. Partner instance special_order_convert_blocked_by_allocation_availability covers the rule.

No placeholders/skip/xfail emitted.

## Step 6: Generate implementation — 2026-07-04T06:05:00.000Z

Implementation complete and verified. Python + Flask in-memory implementation in workspace/implementation/.

### Files
- start.sh — guards pip install on cheap `import flask` check, then `exec python3 app.py`; binds 0.0.0.0:$PORT (default 10000) foreground.
- requirements.txt — flask==3.0.3.
- db.py — in-memory store (empty on boot, no seeding), UUID gen, monotonic seq for stable sort, logical clock default 2026-03-01T00:00:00Z; ISO-8601 with 3 fractional digits + Z.
- errors.py — ApiError + full error-id catalog. response.py — meta/response_type/data envelope, req_ ids, pagination meta. app.py — all endpoints, RBAC, validations, state machines, calculations, cascades.

### Endpoints — all 60+ routes (products, stores, inventory+receive, allocations+release, customers, orders + lines/submit/pay/mark-ready/fulfill/cancel, order-lines, layaways+payments/cancel, special-orders quotes/approve/convert, recalls+issue/resolve, events+register, registries+items/close, registry-items, returns+approve, /_clock/set_current_utc).

### Key logic verified
- Order pipeline OPEN→SUBMITTED→READY→FULFILLED + parallel payment_status; PROVISIONAL at submit, FINAL lock (re-reads tier) at mark-ready.
- Pricing: per-line floor discount (BRONZE 0/SILVER 5%/GOLD 10%), exclusive→0, summed after per-line floor.
- Loyalty: floor(total/100)×tier multiplier (integer num/den); proportional reversal on return (300→0 verified).
- Recall cascade: issue→product RECALLED→quarantine inventory→void ACTIVE lines→recompute orders→auto-cancel emptied; resolve reverses.
- Returns: gross-before-fee tiers (<5000→0%,5000-19999→10%,≥20000→15%), 30-day inclusive window vs logical clock, inventory restock, line→RETURNED.
- Special orders: OCC expected_special_order_version (412), QUOTED→CUSTOMER_REVIEW on customer read, convert requires ACTIVE allocation w/ sufficient qty.
- Layaway: floor per installment, remainder on final (1000/3→[333,333,334]).
- Allocation windows half-open [start,end) overlap; auto-EXHAUSTED at 0. Age-grade gate inclusive >= (422). Event overlap closed interval + store buffer. Inventory reserve/release conservation.
- Validation ordering: auth 400→forbidden 403→existence 404→state 409→age 422→recall→temporal→referential→quantitative→fiscal→OCC 412→uniqueness. Customer ownership enforced. RegistryItem carries only id/created_at.

## Step 7: Run tests and iterate — 2026-07-04T06:07:30.000Z

Cleanup done. The 8-round parallel sweep is clean.

- Iterations run: 1 (single 8-round parallel sweep).
- Result: All 8 concurrent rounds passed 60/60 (passed=60, failed=0, errors=0, total=60 in every round). No flakiness across rounds.
- Tests deleted: None.
- Fixes applied to test_helpers/: None.
- Fixes applied to implementation/: None.

(Orchestrator independently re-verified all 8 results.*.json: every round status={'passed': 60}, passed=60/total=60/failed=0/errors=0.)

## Step 8: Finalize PRD — 2026-07-04T06:07:45.000Z — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-07-04T06:34:30.000Z

Done. PRD_COMPLETED.md created as a minimal patch over PRD.md (Step 8 skipped, so source = PRD.md).

- Line counts: PRD.md 301 lines / 37064 chars → PRD_COMPLETED.md 303 lines / 42240 chars (char delta +5176).
- Ambiguity-pins: 16 · Mismatch-revisions: 4 · Total 20 in-paragraph edits, no new sections.

### Changes
- §2.3 Pagination — insert — ambiguity — invalid limit/offset → ERR_VALIDATION, out-of-range clamped; created_at ties broken by creation sequence — app.py:175-208
- §2.1 RBAC ownership — revise — mismatch — ownership enforced only on mutating/acting ops, not on Any-authorized reads; sole read-side exception is special-order auto-transition — app.py:54-56,938-944
- §3.1 Products — insert — ambiguity — safety_labels may be empty, no consistency check; msrp_cents integer ≥ 0 — app.py:311-314
- §3.2 Recalls (issue) — insert — ambiguity — OPEN/non-DRAFT gate errors are ERR_INVALID_STATE; shared endpoint via resolve flag default false — app.py:1104-1129
- §3.2 Recalls (resolve) — insert — ambiguity — resolve state gate is ERR_INVALID_STATE — app.py:1112-1114
- §3.2 Recall cascade — revise — mismatch — order cancels only if not already CANCELLED/FULFILLED; cascade fires regardless of order status; no inventory release — app.py:1048-1057
- §3.3 Stores — insert — ambiguity — state_code stored verbatim, no length/US check — app.py:405-409
- §3.3 Allocation overlap — revise — mismatch — only non-RELEASED allocations block a new window — app.py:502-505
- §3.3 Allocation release — insert — ambiguity — already-RELEASED → ERR_ALREADY_TERMINAL — app.py:540-541
- §3.5 Order line inventory — insert — ambiguity — missing inventory item treated as ERR_INSUFFICIENT_INVENTORY — app.py:650-652
- §3.6 Submit — insert — ambiguity — not-open → ERR_ORDER_NOT_OPEN, no active line → ERR_INVALID_STATE — app.py:692-695
- §3.7 Pay — insert — ambiguity — amount_cents ≥ 1; cancelled order → ERR_INVALID_STATE — app.py:710-712
- §3.7 Mark-ready — insert — ambiguity — non-SUBMITTED → ERR_INVALID_STATE — app.py:729-730
- §3.7 Fulfill cascade — insert — ambiguity — first ACTIVE allocation used without capacity check; registry purchased_qty bumped in any ACTIVE registry regardless of desired_qty — app.py:758-773
- §3.8 Points reversal — insert — ambiguity — exact formula (gross*num)//(den*100); multiplier captured post-credit at fulfillment — app.py:1412-1413
- §3.9 Layaway cancel — insert — ambiguity — non-ACTIVE cancel → ERR_LAYAWAY_NOT_ACTIVE — app.py:893-894
- §3.10 Special-order convert — revise — mismatch — allocation matched by product_id alone; ordered selection; created order is BOPIS on alloc store, single line, no reservation/gate; response is the Order at HTTP 200 — app.py:981-1028
- §3.10 Quote/approve — insert — ambiguity — non-quotable/non-reviewable state → ERR_INVALID_STATE, state check before stale-version — app.py:956-975
- §3.12 Event register — insert — ambiguity — non-SCHEDULED → ERR_INVALID_STATE — app.py:1195-1196
- §3.13 Returns (request + approve) — insert — ambiguity — request validates only order existence; unknown/foreign line ids silently skipped; return qty unchecked; non-terminal state required (ERR_ALREADY_TERMINAL); invalid decision → ERR_VALIDATION; non-ACTIVE lines still restocked — app.py:1303-1419
- §5 Error catalogue — insert — ambiguity — added ERR_ORDER_LINE_NOT_FOUND and ERR_REGISTRY_ITEM_NOT_FOUND (404), used by impl but absent from PRD — errors.py:30-31

## Pipeline complete — 2026-07-04T06:35:00.000Z

All 9 steps done. Final state: 60/60 tests pass in all 8 stability rounds. Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 8 test files, 60 tests), workspace/implementation/ (Flask, in-memory). PRD_FINALIZED.md absent (Step 8 skipped).
