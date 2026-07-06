# Worklog — task_0722_fast_casual_digital_ordering

## Step 1: Create task directory — 2026-06-30T10:35:02.000Z

Pre-assigned task directory `tasks/task_0722_fast_casual_digital_ordering` with `workspace/` subdir already existed. Per orchestration instructions, skipped the index scan / auto-increment (three sibling pipelines running concurrently). No directory created or renamed.

## Step 2: Generate scaffold (Expert) — 2026-06-30T10:53:07.000Z

Scaffold generator subagent (Expert difficulty) produced all three artifacts; all validate as YAML with correct top-level structure. Agent's own text-summary notification did not arrive (transcript appears to have been flushed only on write; files settled at 10:43–10:47 UTC), so this summary is reconstructed directly from the validated files:

- `SCAFFOLD.yaml` (58.5 KB) — top keys: scenario, domain_name (`fast-casual-digital-ordering`), api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` present (correct).
  - complexity_profile: primary_archetype=quota_allocation, secondary=pricing_engine; layers=[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]; entity_topology=flat; state_machine_shape=parallel; role_model=peer_roles; consistency=immediate.
  - Counts: 12 entities, 4 state_machines, 1 concurrency_rules block, 10 calculations, 13 validations, 47 endpoints, 19 errors, 3 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (59.0 KB) — single top key `scaffold_difficulty_design`; 9 depth rules × 2 instances = **18 depth-test instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- `SCAFFOLD_CORNER_DESIGN.yaml` (60.4 KB) — single top key `scaffold_corner_design`; 9 sections, **32 breadth-test instances**.

Scaffold subagent's verbatim summary (delivered after the worklog reconstruction above):

> Generated the complete scaffold for **task_0722_fast_casual_digital_ordering** at **Expert** difficulty. `scaffold_lint.py` returns **VERDICT: clean lint** (all 394 §1.8/§1.9 calls conform to §1.5; all §1.1 FKs have reverse-reachability).
>
> **Complexity profile:** Primary archetype *quota/allocation* (slot throughput + locker pool) blended with *pricing engine*; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Topology **flat** (peer entities by FK), state-machine shape **parallel** (Order's two axes), role model **peer_roles**.
>
> **SCAFFOLD.yaml (§1.0–§1.7):**
> - **12 entities**: Store, MenuItem, Modifier, PickupSlot, Customer, LoyaltyAccount, PointsLedgerEntry (common_fields:false, append-only), SubscriptionPlan, Subscription, Order, OrderLine, LoyaltyChallenge.
> - **4 state machines**: Order *order_status* lifecycle (CART→PLACED→PREPARING→READY→COMPLETED/CANCELLED with full compensation on cancel); Order *settlement_status* parallel axis (UNSETTLED→CAPTURED→PARTIALLY_REFUNDED→REFUNDED); Subscription (cyclic ACTIVE↔PAST_DUE recovery loop); LoyaltyChallenge (cyclic ROUND_COMPLETE→IN_PROGRESS).
> - **1 concurrency rule**: OCC on PickupSlot.version for `POST /orders/{id}/place` (ERR_STALE_SLOT_VERSION, 412).
> - **10 calculations**: line_total, line_calories (per-unit clamp), delivery_fee (tiered by state band + subscription waiver), redemption_value (block flooring), order_total (pinned 6-step evaluation order — combinatorial mode c), points_earned (dual-variant base vs subscription-boosted), make_it_right_refund (wallet vs original), points_clawback (proportional rounding — combinatorial mode b), queue_status (threshold), tier_recompute (threshold).
> - **13 validations** (priority-ordered auth→authz→existence→state→business safety/temporal/constraint/fiscal→OCC).
> - **47 endpoints** (incl. two test-driving: `POST /_clock/set_current_utc` with default 2026-03-01T00:00:00Z, and `POST /_inject/place_n_orders`).
> - **19 errors**; **3 roles** (Customer entity_backed; StoreManager & PlatformAdmin opaque).
>
> **SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × **2 instances = 18 instances**, all with executable `setup_api_calls` chains and code-computed literal asserts (e.g. points 290 vs 435; order_total 2731; clawback summing to exactly 100; tier GOLD@5000).
>
> **SCAFFOLD_CORNER_DESIGN.yaml:** 9 sections, **32 instances** (31 with full test_recipe + 1 `excluded_because` stub pointing at a §1.8 instance) covering creation/not-found/required-fields/defaults/computed-fields, invalid-transition & terminal lockdown, calculation boundaries, validation error triggers, RBAC denials & ownership, FK reverse-reachability, OCC stale-version, and immediate-consistency.

## Step 3: Copy INSTRUCTION.md — 2026-06-30T10:53:07.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0722_fast_casual_digital_ordering/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-30T11:13:00.000Z

doc-generator subagent produced `workspace/PRD.md` (281 lines, 41.9 KB) from SCAFFOLD.yaml only (both design indices withheld). Section map covers every scaffold area:
- §1 Introduction; §2 Global Specs (2.1 RBAC/roles, 2.2 response envelope, 2.3 pagination, 2.4 common resource props, 2.5 nested retrieval & reference validation, 2.6 monetary & points precision, 2.7 store throughput & queue posture, 2.8 OCC on slot placement, 2.9 allergen safety, 2.10 points ledger & loyalty tiers, 2.11 logical clock).
- §3 Business Logic & Workflows (3.1 stores/menus/modifiers, 3.2 pickup slots & channels, 3.3 customers/wallets/loyalty accounts, 3.4 cart build & pricing, 3.5 place order: gates/pricing waterfall/reservation, 3.6 kitchen progression, 3.7 cancellation & reversal, 3.8 make-it-right refunds & points clawback, 3.9 subscriptions & perks, 3.10 loyalty challenges, 3.11 validation ordering, 3.12 test-driving capabilities).
- §4 Endpoint Definitions; §5 Error Code Catalogue.
doc-generator subagent's verbatim summary:

> Generated `workspace/PRD.md` for the Fast-Casual Digital Ordering & Rewards domain.
>
> **Document size:** 282 lines, 5 top-level sections (§1–§5), 23 subsections (11 in §2, 12 in §3).
>
> **Scaffold areas covered:**
> - **§1 Introduction** — 2 paragraphs framing the three governing concerns (throughput, money conservation, points conservation) plus the slot OCC guard.
> - **§2 Global Specs (11 subsections)** — RBAC with all 3 roles and their `identity` translated to prose (Customer entity-backed, StoreManager/PlatformAdmin opaque); fixed §2.2 envelope emitted verbatim; pagination defaults/min/max/sort; common properties incl. the `PointsLedgerEntry` exception (no `updated_at`/`version`); nested-retrieval + reverse-reachability filters; cents precision/round-half-up; queue posture thresholds; slot OCC; allergen safety; the points ledger + tier thresholds; logical clock default `2026-03-01T00:00:00Z`.
> - **§3 Business Logic (12 subsections)** — organized by lifecycle: stores/menus/modifiers, slots/channels, customers/wallets/loyalty, cart building + line/calorie calc, the pinned 6-step pricing waterfall + delivery-fee bands + subscription free-delivery waiver, kitchen progression + completion earn + depth-3 challenge cascade, cancellation/reversal, make-it-right refunds + proportional points clawback, subscriptions (with `PAST_DUE` recovery loop), challenge cycling, the priority-ordered validation chain, and the two test-driving capabilities.
> - **§4 Endpoint table** — all 47 endpoints, 4 columns only.
> - **§5 Error table** — all 19 error IDs with HTTP status, 2 columns only.
>
> **Hard Contracts:** Field coverage check PASS (71 required, 71 present, 0 missing). Rule coverage check PASS (1/1 OCC; all 4 state machines fully expressed; all 10 calculations reconstructible; validations priority 1–13 ordered in §3.11; all cross-entity cascades stated; all 19 errors appear in narrative). Path purity check PASS (348 backtick tokens, 0 slash-leading/bare-method/method+path in §3). The withheld difficulty/corner design files were not opened.

## Step 5: Generate unit tests — 2026-06-30T11:25:00.000Z

unit-test-generator subagent produced `test_helpers/` (9 files) + `test_suite/` (conftest + 5 domain files). Verbatim summary:

> **Stage 1 — `test_helpers/`** (9 files): `types.py` (TypedDicts for all 12 entities + enums; `PointsLedgerEntry` correctly carries only `id`/`created_at` per its `common_fields: false`), `api_client.py` (51 endpoint methods over `GenericApiClient`), `api_errors.py` (19 error IDs registered with the framework HTTP-status map), `constants.py`, `factories.py`, `assertions.py`, `test_users.py` (entity-backed `make_customer_headers(id)` builder for ownership threading + opaque-role constants), `fixtures.py` (composite helpers: bootstrap, place/complete/cancel/make-it-right lifecycles, active-subscription, slot-saturation, clock control), and the barrel `__init__.py`. Imports verified clean.
>
> **Stage 2 — `test_suite/`** (conftest + 5 domain-language files): **67 test functions, all collect successfully.**
> - **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered by exactly **2 tests each** (the second test on each instance asserts a distinct, PRD-uniquely-derived facet of the same instance's `grounds`/`assert` block).
> - **Queue B (Corner): 31 tests** — all **31 non-stub** corner instances covered by ≥1 test.
>
> **Skipped instances:** only the single `excluded_because:` stub `error_stale_slot_version_occ_stub` (its rationale defers `ERR_STALE_SLOT_VERSION` to corner `occ_stale_slot_version_conflict`, which is covered). No PRD-first filter skips were needed: both priority-pair precedence orderings are stated verbatim in PRD §3.11.
>
> **Audits passed:** every test docstring ends with exactly one `Design:` tag resolving to a real source instance; every cited PRD sentence is verbatim-present in `PRD.md` (literal-grep verified); no `skip`/`xfail`/`skipif`; no scaffold/table references leaked. All pre-computed expected values (CA delivery fee 631, pinned total 2731, base/boost 290/435, clawback no-drift) independently recomputed from PRD formulas and match the design indices.

## Step 6: Generate implementation — 2026-06-30T11:25:00.000Z

implementation-generator subagent produced `workspace/implementation/` (Python + Flask, in-memory, no seeding). Verbatim summary:

> Built a complete Python + Flask in-memory implementation for **task_0722**.
>
> ### File list
> - `start.sh` — foreground launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a flask import probe, `exec python3 app.py`
> - `requirements.txt` — flask==3.0.3
> - `app.py` — app factory, blueprint registration, ApiError + HTTP error handlers
> - `db.py` — in-memory store (dicts per entity), UUID/common-field minting, logical clock (default `2026-03-01T00:00:00Z`), ISO parsing. **No seeding.**
> - `response.py` — success/error envelope (`meta`/`response_type`/`data`), `req_`-prefixed request id, 3-fractional-digit UTC timestamps
> - `errors.py` — full 19-entry error catalog + ApiError
> - `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gate, Customer ownership gate
> - `serializers.py` — per-entity public field projections (PointsLedgerEntry correctly omits `updated_at`/`version`)
> - `helpers.py` — body parsing, typed field validation, FK-existence (404), pagination (limit 10/1-100, offset 0), reverse-reachability filters
> - `services/loyalty.py` — append-only ledger, balance/lifetime/tier recompute
> - `services/queue.py` — queue_status from most-loaded active slot
> - `services/pricing.py` — line totals/calories, delivery fee, redemption, pinned order-total waterfall, points-earned dual-variant, proportional clawback (Decimal, round-half-up)
> - `routes/` — catalog, customers, subscriptions, challenges, orders, testdrive
>
> ### Endpoints implemented: **48** (all from §1.5 / §4 tables), including both `_inject/place_n_orders` and `_clock/set_current_utc`.
>
> ### PRD areas resolved deliberately (potential ambiguity)
> 1. **`ERR_DUPLICATE_EMAIL` / unique constraints vs. existence ordering** — neither duplicate-email nor unique `tier_name` is in the §1.4 priority table. Placed FK existence (priority 3) before business uniqueness checks. Unique `tier_name` collisions return `ERR_INVALID_REQUEST` (no dedicated code).
> 2. **Cancel of PLACED/PREPARING with `refund_destination`** — implemented exactly the §3.7 side-effect list: re-credit `wallet_applied_cents`, restore redeemed points via compensating `ADJUSTMENT`, release slot + bump version, `refunded_cents += total_cents`. `refund_destination` body field accepted but the only in-system money movement on cancel is the wallet_applied re-credit (ORIGINAL charge reversed off-ledger).
> 3. **`points_clawback` cap clause** — implemented per PRD §3.8 wording (cap at `points_earned` net of prior clawbacks on the order; PRD prose wins over scaffold).
>
> No PRD sentence was left unmapped; no entity data is seeded at startup.

## Step 7: Iterate tests to all-pass — 2026-06-30T11:35:00.000Z

Long-lived fix subagent drove the run/diagnose/fix loop to a clean 8-round parallel per-test-server sweep. Verbatim summary:

> **Iterations run:** 2 (one diagnostic sweep at 63/67, one verification sweep at 67/67).
>
> **Tests deleted:** None. All four failures were test-artifact or implementation bugs, not PRD-silence cases.
>
> **Fixes applied to `test_helpers/`:**
> - `test_helpers/fixtures.py` — `create_and_place_order()`: it returned `placed["version"]` (the **order's** version) while its docstring promised "(order, new_slot_version)". Callers threaded that value into the next placement as `expected_pickup_slot_version`, so chained placements tripped `ERR_STALE_SLOT_VERSION` (order version 3 ≠ slot version 2). Changed it to re-read the slot after placement and return the slot's current `version`. Fixed `test_slot_capacity_strict_less_than_boundary` and `test_slot_capacity_below_boundary_permits_placement`.
>
> **Fixes applied to `test_suite/`:**
> - `test_04_placement_gates.py` import block — added the missing `create_completed_order` to the explicit `from test_helpers import (...)` list (barrel-exported but never bound in this file), fixing the `NameError` in `test_earn_boost_skipped_for_non_active_subscription`.
> - `test_04_placement_gates.py::test_order_place_requires_store_active` — rewrote per STEP 2. It asserted `ERR_SLOT_UNAVAILABLE` at *placement* for an inactive store, but PRD §3.5's slot-availability gate covers only slot state, never store `is_active` — that expectation traced to SCAFFOLD, not PRD. PRD §3.4 verbatim routes store-inactive to `ERR_ITEM_UNAVAILABLE` at the *add-line* stage. Rewrote to add a line at an inactive store and assert `ERR_ITEM_UNAVAILABLE`, fixing the docstring citation. Makes the test MORE faithful to PRD.
>
> **Fixes applied to `implementation/`:** None. The `add_order_line` check at `routes/orders.py:130` raising `ERR_ITEM_UNAVAILABLE` for an inactive store is PRD-required (§3.4) and was correct — the failure was the test issuing a request inconsistent with PRD, fixed in test_helpers/test_suite per the cardinal rule.
>
> **Final per-round results (all 8 parallel rounds):** round 1–8 all 67/67 (failed=0, errors=0 in every round).

## Step 8: Finalize PRD — 2026-06-30T11:42:00.000Z

PRD finalizer subagent ran (not skipped — Step 7 had 2 iterations with test_helpers/test_suite fixes). Result: `PRD_FINALIZED.md` is a **byte-identical verbatim copy** of `PRD.md` (281→281 lines, 0.0% delta). Verbatim summary:

> **Changes:** No changes — all Step 7 items were pure test/fixture bugs. The PRD already uniquely determines every behavior the implementation exhibits at the Step 7 sites.
>
> **Per-item analysis (why no PRD edit):**
> - `test_helpers/fixtures.py` `create_and_place_order()` return value — pure fixture bug; impl behavior (placement bumps slot `version`, `routes/orders.py:300-301`) already pinned by PRD §2.8/§3.2/§3.5.
> - `test_04` missing `create_completed_order` import — pure test-binding bug (NameError); no PRD relevance.
> - `test_04::test_order_place_requires_store_active` — test (traced to SCAFFOLD) wrongly asserted `ERR_SLOT_UNAVAILABLE` at placement; impl routes store-inactivity to `ERR_ITEM_UNAVAILABLE` at add-line (`routes/orders.py:130`), exactly as PRD §3.4 states verbatim. No PRD gap.
>
> **NO-NEW-MISMATCH enumeration for the store `is_active` subject:** grep `is_active` → `catalog.py:37` (creation default true → PRD §3.1 ✓), `routes/orders.py:130` (add-line gate → `ERR_ITEM_UNAVAILABLE` → §3.4 ✓), `routes/orders.py:320` (advance-from-PLACED requires store active → `ERR_INVALID_STATE` → §3.6 ✓), placement path `routes/orders.py:250-251` (slot-availability gate checks only is_closed/window/channel, deliberately NOT store is_active → §3.5 ✓). All four already accurately described by unedited PRD; no wording change needed.

## Step 9: Complete PRD — 2026-06-30T11:48:00.000Z

PRD completeness-scan subagent walked `implementation/` exhaustively against `PRD_FINALIZED.md`, producing `PRD_COMPLETED.md`. Verbatim summary:

> **Line counts:** source 281 → completed 281 (all edits in-paragraph; no lines added/removed). **Char delta:** +1139 chars (41869 → 43009).
> **Counts:** 5 ambiguity-pins, 3 mismatch-revisions (8 changes total).
>
> **Changes:**
> - §2.4 — insert — ambiguity — pinned the `version` initial value to `1` — `db.py:44`
> - §3.4 — insert — ambiguity — pinned that a line's `effective_allergen_tags` are presented as distinct tags sorted ascending lexicographically (PRD said only "union") — `services/pricing.py:39`
> - §3.5 — revise — mismatch — reordered the placement gate list to match impl/§3.11: empty → allergen → slot-availability → capacity → locker → points → version; also pinned that the locker gate does not count the order being placed — `routes/orders.py:237-274`
> - §3.6 — insert — ambiguity — pinned that advancing a `PLACED` order while the store is inactive yields `ERR_INVALID_STATE` — `routes/orders.py:319-321`
> - §3.7 — revise — mismatch — pinned that on cancel of a placed/preparing order the charge is reversed off-ledger and the wallet receives only the `wallet_applied_cents` re-credit regardless of `refund_destination` — `routes/orders.py:399-412`
> - §3.11 — insert — ambiguity — pinned that for an order-line add/update the target order's `CART`-state check fires before body-referenced `menu_item_id`/`modifier_ids` existence (impl deviates from the global existence-before-state rule here) — `routes/orders.py:120-122`
> - §3.12 — insert — ambiguity — pinned the test-driving response shapes: `_inject/place_n_orders` returns the updated pickup slot at `201`; `_clock/set_current_utc` returns an empty data object at `200` — `routes/testdrive.py:94,113`
> - §4 — revise — mismatch — pinned that the operator wallet-credit adjustment and operator points adjustment both return `201 Created` — `routes/customers.py:87,124`
>
> All edits in-paragraph; no new sections; no behavior absent from `implementation/` introduced. Tests used only as auxiliary cross-reference, never as alignment authority.

---

## Pipeline complete — 2026-06-30T11:48:00.000Z

All Steps 1–9 finished. Test status: **67/67 passing across all 8 parallel per-test-server rounds** (Step 7, 0 flaky, 0 errors). Final PRD artifact: `workspace/PRD_COMPLETED.md` (8 pins over PRD.md).
