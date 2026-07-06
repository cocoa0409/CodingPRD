# Worklog — task_0736_farm_box_aggregator

Scenario: 736. Local Farm-Box & Online Farmers-Market Aggregator: multi-farm catalog & availability, customer order & pickup-hub/delivery slot, vendor allocation & packout, weight/variable pricing, SNAP/Double-Up match, vendor settlement & commission, substitution/refund, subscription option

Difficulty: Expert (passed to Step 2 scaffold-generator only).

## Step 1: Create task directory — 2026-07-04T11:32:32.000Z

Task directory `tasks/task_0736_farm_box_aggregator` was pre-assigned and pre-created (with `workspace/`). Skipped ./tasks/ scan and auto-numbering per orchestrator instructions. No new task directory created.

## Step 2: Generate scaffold — 2026-07-04T12:29:00.000Z

All validations pass. The scaffold is complete and internally consistent. Here is the final summary.

## Generated: `task_0736_farm_box_aggregator` — Expert difficulty

Three files written to `/home/ubuntu/github/CodingPRD/tasks/task_0736_farm_box_aggregator/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**`scaffold_lint.py` verdict (pasted verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 36   §1.1 entities: 10
  §1.8 instances: 18   §1.9 instances: 26   Calls scanned: 440
```

### Structure
- **Complexity profile:** primary `quota_allocation` + secondary `pricing_engine`; layers = dual-variant calc, cascading side-effects, rate/threshold triggers, optimistic concurrency; topology `flat`; state-machine shape `parallel`; role model `peer_roles`.
- **10 entities** (14 FKs): Farm, Product, MarketCycle, Offering, PickupHub, Customer, Subscription, Order, OrderLine, VendorSettlement (VendorSettlement is `common_fields:false`, immutable event).
- **4 state machines**, three non-linear on distinct entities: Order (parallel `order_status × payment_status`), OrderLine (branching ALLOCATED→{PACKED,SHORTED,SUBSTITUTED}→FULFILLED), Subscription (cyclic ACTIVE⇄PAUSED); MarketCycle linear posture gate.
- **6 calculations:** `line_pricing` (est/final dual-variant, WEIGHT), `order_benefit_application` (SNAP+Double-Up, nested min/max), `vendor_settlement_payout` (per-line commission rounding + provisional/final), `offering_availability`, `refund_allocation` (SNAP→Double-Up→wallet waterfall), `subscription_box_build`.
- **36 endpoints** (slightly above the 32 soft cap — surplus is entirely mandatory FK reverse-reachability GETs), **1 concurrency rule** (settlement-create OCC on `Farm.version`), **23 errors** (all triggerable), **3 roles** (PlatformAdmin opaque; Farm/Customer entity-backed), **18 validations** with a priority ladder keeping `ERR_ORDER_NOT_ALLOCATED` reachable and both conflict pairs valid.

### Design instance counts
- **§1.8:** 18 instances = 9 Difficulty Rules × 2. All numeric asserts pre-computed literals (verified with decimal/round-half-up).
- **§1.9:** 33 instances = 26 active corners + 7 `excluded_because` stubs (all citing real §1.8 instance names).

One deliberate design fix: validation priority ordering restructured so `ERR_ORDER_NOT_ALLOCATED` is checked before the generic line-state error; both priority-conflict pairs (`{state, business_fiscal}` and `{business_referential, business_safety}`) resolve deterministically.

## Step 3: Copy INSTRUCTION.md — 2026-07-04T12:29:40.000Z

Copied ./INSTRUCTION.md → tasks/task_0736_farm_box_aggregator/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T12:39:14.000Z

The PRD is generated and all three hard contracts pass.

**Output:** `workspace/PRD.md` — 303 lines, ~44 KB.

**Sections covered:**
- §1 Introduction — multi-farm aggregator, SNAP/Double-Up, estimated-vs-final pricing split.
- §2 Global Specifications (10 subsections) — RBAC (PlatformAdmin opaque, Farm/Customer entity-backed); §2.2 verbatim; pagination; common properties (VendorSettlement common_fields:false → only id/created_at); monetary precision (whole-cent round-half-up, per-line commission rounding); availability accounting + conservation invariant; cascading reconciliation; path validation + reverse-reachability filters; settlement OCC; priority-ordered validation list §2.10 (priority-7-before-9 keeps ERR_ORDER_NOT_ALLOCATED reachable).
- §3 Business Logic (9 subsections) — farm/product onboarding, market-cycle windows+lifecycle+subscription box generation, offerings, hubs/customers/subscriptions, cart assembly+estimated pricing, checkout (SNAP/Double-Up + delivery slots), packout (pack/short/substitute equal density)+final pricing, fulfillment/cancellation/refund waterfall, vendor settlement/payout. All six calculations rendered as precise prose.
- §4 endpoint table (all 36 endpoints incl. `_clock` capability); §5 error catalogue (all 23 errors).

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS 73/73; Contract 2 (Rule Coverage) PASS (validation priority ordering, settlement OCC as stale-version, all transitions/cascades, all six calculations, all 23 error IDs); Contract 3 (§3 Path Purity) PASS (0 slash-prefixed / bare-method / method+path tokens).

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/grepped/referenced. Only SKILL.md, SCAFFOLD.yaml, section-2.2 doc, and example-prd.md consulted.

## Step 5: Generate unit tests — 2026-07-04T13:03:33.000Z

Test infrastructure and suite generation complete.

**test_helpers/** (Stage 1): types.py (11 entity TypedDicts; VendorSettlement only id/created_at per common_fields:false + 12 status/enum types), api_client.py (one method per PRD endpoint incl. /_clock/set_current_utc), api_errors.py (23-member ApiErrorId enum + HTTP-status map), assertions.py (per-entity + assert_offering_conservation for §2.6 invariant), factories.py, constants.py, test_users.py (make_farm_headers/make_customer_headers), fixtures.py (setup_open_egg_market, setup_allocated_egg_line, setup_snap_three_line_cart/_placed, primitives), __init__.py.

**test_suite/** (Stage 2): conftest.py + 10 domain-named test files (test_01…test_10).

**Test count: 62** — Queue A (Difficulty §1.8): 36 tests (all 18 instances × 2). Queue B (Corner §1.9): 26 tests (all 26 non-stub instances × 1). Instances skipped: none (PRD unusually complete; §2.10 fixes validation-precedence order). 7 excluded_because corner stubs correctly not translated; all 7 difficulty_instance pointers resolve.

**Verification:** all 62 tests collect cleanly, pyflakes clean; design-tag audit passes (every tag → real instance, no stub/untagged/dual-tagged); verbatim-citation audit: all 83 quoted PRD sentences survive literal grep of PRD.md.

Flag: `compensating_invariant/offering_unit_conservation_add_then_cancel` asserts reserved-unit release on a CART cancel — §3.8 says CART cancel "simply closes it… no refund" but §2.7 states unconditionally cancellation cascades to lines releasing reserved units (uniquely derivable, cited §2.7+§2.6). Tests only structurally verified (not run against live server yet).

## Step 6: Generate implementation — 2026-07-04T13:03:33.000Z

Complete Python + Flask implementation generated and smoke-verified end-to-end.

**Files** (workspace/implementation/): start.sh (cd's to dir, guards pip install behind `import flask`, `exec python3 app.py`), requirements.txt (flask), errors.py (ApiError + 22-code error_id→HTTP catalog from §5), db.py (in-memory dict store, monotonic system-clock ISO-8601 UTC 3-frac-digit timestamps, DOUBLEUP_CAP=2000/box targets/24h buffer, logical clock), response.py (meta/response_type/data envelope, req_-prefixed request id, pagination meta, per-entity field whitelists; VendorSettlement only id+created_at), app.py (routes, validation-precedence pipeline, state machines, calculations).

**Endpoints: 36** — every row of PRD §4 table.

**start.sh:** binds 0.0.0.0:$PORT (default 10000), foreground via exec, in-memory dicts only (fresh boot lists total_count=0; no seeding/SQLite/disk/JSON).

**Verified behaviors (live smoke):** weight pricing round-half-up; SNAP+Double-Up freeze at checkout, deduct balance, recompute at fulfill; refund waterfall (SNAP→Double-Up→wallet) on short/cheaper-sub/cheaper-full-pack; full-order cancel restores SNAP (conservation); offering reserved/committed/remaining incl. substitution; per-line commission rounding; OCC on expected_farm_version (412 stale); subscription box build (PRODUCE, ascending created_at, stop-before-exceeding); delivery slot half-open overlap (adjacent end==start allowed); validation precedence (ERR_ORDER_NOT_ALLOCATED before line-state, ERR_INVALID_STATE on re-pack, ownership/auth/existence ordering, ERR_FARM_NOT_SNAP_AUTHORIZED, ERR_INVALID_PAGINATION).

**Two interpretive calls (toward literal PRD):** cheaper full pack issues refund but does NOT move payment_status→PARTIALLY_REFUNDED (§3.7 sets that only for short/substitution); snap_reimbursable_cents computed as net SNAP+Double-Up pool allocated across FULFILLED snap-eligible lines in creation order, capped per line at final_line_cents.

## Step 7: Run tests and iterate — 2026-07-04T13:34:12.000Z

- Iterations run: 1
- Tests deleted: none
- Fixes applied to test_suite/: none
- Fixes applied to test_helpers/: none
- Fixes applied to implementation/: none
- Final sweep: 8/8 rounds passing, 62 tests per round

## Step 8: Finalize PRD — 2026-07-04T13:34:12.000Z

SKIPPED per skill skip-condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, and 0 implementation fixes — zero iterations beyond the baseline. PRD.md already determined every behavior the implementation exhibits at every site Step 7 could have surfaced, so no PRD_FINALIZED.md is produced. Step 9 will scan the full PRD-vs-implementation surface (which Step 8's Step-7-diff-scoped patch does not cover) to eliminate any residual ambiguity or mismatch.

## Step 9: Complete PRD — 2026-07-04T13:46:00.000Z

- Source (PRD.md) vs PRD_COMPLETED.md line counts and char-delta.
  - PRD.md: 303 lines, 44467 chars
  - PRD_COMPLETED.md: 303 lines, 48850 chars
  - Char delta: +4383
- Counts: ambiguity-pins = 11, mismatch-revisions = 0
- One bullet per change:
  - §2.1 Ownership scope — insert — ambiguity — pinned that ownership checks apply to writes and to GET /customers/{id}, but not to read-only GETs of order/line/subscription/other resources — implementation/app.py:669-673, 776-796, 984-1008
  - §2.2 api_request_id format — revise — ambiguity — pinned `req_` prefix plus exactly 20 random mixed-case alphanumeric characters — implementation/response.py:15-19
  - §2.4 id UUID format — revise — ambiguity — pinned version-4 UUID in canonical 8-4-4-4-12 hex form — implementation/db.py:67-68
  - §3.2 subscription-box generation ordering and initial state — insert — ambiguity — pinned that subscriptions are visited in ascending `created_at` order, orders start in CART/UNPAID, no auto-checkout — implementation/app.py:446-454, 457-483
  - §3.4 subscription-box fill halting — revise — ambiguity — pinned that iteration halts entirely at the first over-target offering rather than skipping to smaller ones — implementation/app.py:476-483
  - §3.6 slot capacity scope — revise — ambiguity — pinned "active delivery order" = PLACED/ALLOCATED/FULFILLED on the same hub across all cycles — implementation/app.py:883-912
  - §3.7 Full pack cheaper case payment_status — revise — ambiguity — pinned that a full-pack negative delta issues the refund but does NOT flip payment_status to PARTIALLY_REFUNDED — implementation/app.py:1099-1106
  - §3.7 Short pack weight-check gating and zero-credit case — revise — ambiguity — pinned weight rule applies only for fulfilled_qty ≥ 1, zero-credit short leaves payment_status unchanged — implementation/app.py:1085-1112
  - §3.7 Substitution field-side-effects & weight rule — revise — ambiguity — pinned substitute_qty ≥ 1, weight check for WEIGHT substitute, fulfilled_qty/actual_weight_kg fields, snap_eligible not recomputed, zero/positive delta leaves payment_status unchanged — implementation/app.py:1015-1078
  - §3.8 refund waterfall — revise — ambiguity — pinned that full-pack cheaper case flows through the waterfall too, and that non-positive credit is a no-op — implementation/app.py:259-282, 1099-1106
  - §3.9 snap_reimbursable_cents attribution algorithm — revise — ambiguity — pinned per-order pool (net SNAP + net Double-Up, clamped ≥ 0) walked over FULFILLED snap_eligible lines in created_at order, each capped at final_line_cents — implementation/app.py:1121-1140
  - §3.9 settled-line internal flag & VendorSettlement fields — revise — ambiguity — pinned that the swept lines are flagged internally (not exposed) and enumerated the settlement's payload fields — implementation/app.py:1199-1205, implementation/response.py:91-95
