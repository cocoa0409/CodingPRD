# Worklog — task_0735_handmade_marketplace

## Step 1: Create Task Directory — 2026-07-04T11:32:16.000Z

Task directory `tasks/task_0735_handmade_marketplace` was pre-allocated (workspace/ already created). Skipped ./tasks/ scan and auto-numbering per orchestrator instructions. No new task dir created. Difficulty for design: Expert (passed only to Step 2 scaffold generator).

## Step 2: Generate Scaffold — 2026-07-04T12:24:40.000Z

All checks pass. The scaffold is complete and self-consistent.

## Summary

Generated three files under `/home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace/` for the **Expert**-difficulty Etsy-seller-side handmade/made-to-order marketplace, all passing `scaffold_lint.py` (`VERDICT: clean lint`).

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Archetype**: event_sourcing + pricing_engine; **flat** topology mounted under `api_prefix: /seller`; **parallel** state-machine shape; **peer_roles**; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.
- **9 entities**: Shop, ShippingProfile, Material, Listing (variations as an array field), VacationPeriod, Order, Review, Case, Payout. 12 FKs, all with filtered-list reverse-reachability GETs (lint check f clean).
- **6 state machines**: Shop (cyclic ACTIVE↔VACATION, + SUSPENDED/CLOSED), Listing (cyclic ACTIVE↔INACTIVE / ACTIVE↔SOLD_OUT, terminal REMOVED), Order (parallel payment_status × fulfillment_status), Case (branching seller/admin resolution), Payout (SCHEDULED/ON_HOLD/PAID), plus derived Material stock posture. 1 concurrency rule: OCC on Shop.version for payout create-with-supersede (`ERR_STALE_SHOP_VERSION`, 412).
- **6 calculations**: order_shipping_cost (tiered, non-linear), order_fees, payout_net (dual-variant estimated↔settled, round-per-order-then-sum), shop_rating (dual-variant simple↔Bayesian), ship_by_date, material_stock_status. All literal assertions computed under round_half_up and verified.
- **48 endpoints**, **22 ordered validations**, **30 errors**, **3 roles** (Seller `entity_backed:Shop`, Buyer/PlatformAdmin `opaque`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **18 instances** — exactly 2 per each of the 9 Difficulty Rules, each with executable `setup_api_calls`/`trigger`/`assert` chains and pre-computed literals (e.g. payout estimated 90 vs settled 45; per-order fees 110 vs sum-then-round 109; simple rating 5.0 vs Bayesian 4.29).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **41 instances** across all 9 claim-extraction sections — **33 full** corner tests (required-field/enum, invalid/terminal transitions, RBAC + ownership denials, FK reverse-reach, OCC stale-version, derived-field recompute, not-found, computed pricing) and **8 `excluded_because` stubs** pointing to covering §1.8 instances.

All 59 instance names are unique across both design files; all excluded_because refs resolve.

Orchestrator validation: all three files parse as valid YAML with correct top-level keys; SCAFFOLD.yaml contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the two design files each have exactly their single required top-level key.

## Step 3: Copy Shared Files — 2026-07-04T12:24:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0735_handmade_marketplace/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T12:36:13.000Z

All checks pass. The PRD is complete and validated.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace/workspace/PRD.md` (289 lines) from `SCAFFOLD.yaml` alone. The two `SCAFFOLD_*_DESIGN.yaml` files and all sibling tasks were left untouched.

**Section outline**
- §1 Introduction — 3 paragraphs (business context, money/inventory conservation, logical-clock + flat `/seller` topology).
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all three roles + `identity` translations), 2.2 Response Structure (verbatim, confirmed byte-identical), 2.3 Pagination/ordering, 2.4 Common Properties + Versioning (VacationPeriod called out as `id`+`created_at` only), 2.5 Referential Integrity/left-to-right resolution + all `*_NOT_FOUND` codes + list filters, 2.6 Precision/rounding (per-component + per-order-then-sum), 2.7 Shop Ledger conservation, 2.8 Cascading effects (suspend cascade, depth-3 pay cascade, cancel compensation, case→payout hold), 2.9 OCC on payout create, 2.10 Logical Clock (default `2026-03-01T00:00:00Z`).
- §3 Business Logic — 9 subsections organized by entity lifecycle/business timeline: shop onboarding+status, shipping/materials, listings, order placement+pricing, payment+fulfillment, cancellation/refunds, reviews+rating, disputes/cases, payouts/settlement.
- §4 Endpoint table (4 columns, all 48 endpoints) and §5 Error table (2 columns, all 30 errors).

**Hard Contract reports (transcript-only, per spec):**
- Contract 1 (Field-Name Coverage): 83 required identifiers, 83 present, 0 missing — Status: PASS.
- Contract 2 (Rule Coverage): all state transitions, 6 calculations (with constants embedded as 6.5%/3%/20¢/25¢ and Bayesian prior 5@4.0), OCC rule, all validation priority orderings (order-create, pay, review, payout, resolve, mark-paid all stated in relative order), cross-entity cascades, and sibling branches (seller-vs-admin resolve, escalate sources, ship sources, suspend sources, estimated-vs-settled net, simple-vs-weighted rating) expressed with equal density — Status: PASS.
- Contract 3 (§3 Path Purity): 398 backtick tokens scanned in §3, 0 leading-slash, 0 bare-method, 0 method+path — Status: PASS.

**Notable scattering/coverage decisions**
- Endpoints in §3 are referenced only by state-transition framing or role+verb; the `/seller` mount is disclosed once in §1 and §4.
- Parameters deliberately scattered: `expected_shop_version` (§2.9 + §3.9), `restock_qty` (§3.2 material + §3.3 listing), personalization fields split between listing config (§3.3) and order placement (§3.4), `close` (§3.1), `to_iso8601` (§2.10).
- Two ordering nuances I resolved from scaffold priorities: payout-create checks eligibility (priority 21) before OCC (22); case-resolve checks state (8) before the `decision`-value check (18) — both made explicit in prose.
- Late-caught fixes during the contract passes: added `scheduled_at` (payout) which had no natural home initially, plus `personalization_enabled`/`personalization_required`/`variations` default values for Contract 2 field-level completeness.

Orchestrator validation: PRD.md present, 288 lines on disk, well-formed heading tree (§1–§5); design-index leakage sniff (`test_recipe`/`excluded_because`/`scaffold_*`/§1.8/§1.9) returned no hits.

## Step 5: Generate Unit Tests — 2026-07-04T13:04:39.000Z

Test infrastructure generation complete. Everything verifies against the design-index-only contract.

## Summary

**Stage 1 — `test_helpers/`** (9 modules): `types.py` (entity TypedDicts + status/role enums; `VacationPeriod` correctly carries only `id`+`created_at`, no `updated_at`/`version` since `common_fields: false`), `api_errors.py` (all 30 PRD errors + HTTP-status map registered with the framework), `api_client.py` (one method per endpoint, incl. `_clock/set_current_utc`), `constants.py`, `factories.py`, `assertions.py`, `test_users.py` (Seller `entity_backed:Shop` → `make_seller_headers(shop_id)` identity threading; opaque Buyer/Admin), `fixtures.py` (composite setups reused across both queues), and the `__init__.py` barrel.

**Stage 2 — `test_suite/`** (`conftest.py` + 10 domain-named files): **69 tests total**.

- **Queue A (Difficulty): 36 tests** — all 18 instances (9 rules × 2) translated with exactly 2 tests each.
- **Queue B (Corner): 33 tests** — all 33 non-stub instances translated with 1 test each. The 8 `excluded_because:` stubs were NOT translated; all 8 cross-references were verified to resolve into real difficulty instances.

**Instances skipped: none.** Every non-stub instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

**One notable adjudication:** `Difficulty/cross_entity_state_dependency/payout_release_hold_requires_case_resolved` — the PRD states the release-hold precondition ("permitted only once no swept order still has `has_open_case` true") but does not name the specific rejection `error_id` for a premature release-hold. Rather than hard-code `ERR_PAYOUT_HAS_OPEN_CASE` (not uniquely derivable for that endpoint), the blocked-path test uses `validate_error_is_one_of([ERR_PAYOUT_HAS_OPEN_CASE, ERR_INVALID_STATE])`; the companion test asserts the fully-derivable `ON_HOLD → SCHEDULED` transition after resolution.

**Verification passed:**
- 69 tests collect cleanly under `PYTHONPATH=<taskdir>`; all files byte-compile.
- Coverage audit: every `Design:` tag maps to a real instance; ≥2/difficulty and ≥1/corner-non-stub confirmed; no tags on stubs.
- Citation audit: all 96 quoted docstring fragments are verbatim in `PRD.md` (whitespace-normalized).
- No `skip`/`skipif`/`xfail`; no "scaffold"/section/table leakage in generated code.
- Framework interface (`_request`, `validate_*`, `build_user_headers`, `set_error_http_status_map`) read back from the installed package and matched exactly; enum-vs-string equivalence confirmed for error lookups.

Files are under `/home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace/test_helpers/` and `/test_suite/`.

## Step 6: Generate Implementation — 2026-07-04T13:38:00.000Z

Fresh boot works cleanly with empty store (200 for admin list returns 0 items). Auth returns 401. All the smoke tests passed:

- Shop CRUD + vacation cycle + suspend cascade
- Order create with correct pricing (item_subtotal, shipping, total)
- Pay with correct fee calc (2600 → 20+169+103 = 292 fee, 2308 net)
- Ledger flow (pending → available on complete)
- Payout OCC (rejected 412 on stale version)
- Payout mark-paid with settled net
- MADE_TO_ORDER cascade: order pay → material depletion → listing SOLD_OUT
- Cancel: refund + restore material + listing back to ACTIVE
- Rating computation: 2×5-star → simple 5.0, weighted 4.29 (PRD example)
- Case-on-payout: SCHEDULED → ON_HOLD, mark-paid blocked, release-hold → SCHEDULED
- Vacation overlap: adjacency allowed, real overlap rejected
- Free shipping boundary: subtotal == threshold ships free (>= boundary)
- Pagination `limit`/`offset`/`total_count`/`has_more`
- Response envelope with `meta`/`response_type`/`data`, `error_id`/`message`

The implementation lives at `/home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace/workspace/implementation/`:

- `start.sh` — guarded pip install + `exec python3 app.py`
- `requirements.txt` — `flask==3.0.3`
- `app.py` — Flask factory, error handlers, blueprint registration
- `db.py` — in-memory `Store`, logical clock (default `2026-03-01T00:00:00Z`), UUID + `req_XXX` generation, ISO 8601 formatting with 3 fractional digits
- `errors.py` — error IDs + `HTTP_STATUS` map + `AppError` + `raise_err`
- `envelope.py` — success/error envelope helpers
- `auth.py` — `X-User-ID`/`X-User-Role` extraction, role check, seller/buyer ownership
- `helpers.py` — JSON body parsing, pagination, sort-by-created
- `calculations.py` — order shipping (with free-shipping `>=` boundary), fees (round-half-up per component then sum: 20 + 6.5% + 3% + 25), ship-by-date fallback, material threshold (`<=` for LOW), Bayesian rating (prior 5 at 4.0, 2 dp)
- `serializers.py` — entity view functions (VacationPeriod omits `updated_at`/`version` per PRD 2.4)
- `services.py` — shop cascade, material-freed cascade, pay/cancel SOLD_OUT cascade, production window overlap counting, shop rating recompute
- `routes/{shops,shipping_profiles,materials,listings,vacation_periods,orders,reviews,cases,payouts,clock}.py` — all 50 endpoints, empty store at boot, no seeding

Sanity check: fresh boot from a killed process starts on empty store, returns 200 for admin list and 401 without auth headers.

result: Python + Flask implementation for task_0735_handmade_marketplace written under `workspace/implementation/` (start.sh + 10 route modules + services/calc/envelope/auth/db/errors), verified end-to-end via curl (shop lifecycle, pay/ship/complete, MTO cascade + restore, dual-variant rating 5.0/4.29, payout OCC + hold/release/settled-net, vacation overlap, free-shipping boundary).

## Step 7: Run Tests and Iterate — 2026-07-04T13:41:00.000Z

All 8 parallel rounds pass 69/69 on the baseline. No iterations needed — the implementation and test suite are already in a clean state.

Sanity check: verified that every one of the 8 results.${i}.json files reports `passed=69/69, failed=0, errors=0` from a fresh sweep launched with per-test-server isolation.

Summary:
- Iterations run: 0 (baseline sweep already fully green).
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: none.

result: All 8 parallel rounds pass 69/69 for /home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace — no changes required.

## Step 8: Finalize PRD — 2026-07-04T13:41:05.000Z

SKIPPED — Step 7 exited on the first 8-round sweep with 0 iterations (0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes). Per the skill's skip condition, PRD.md already uniquely determines every behavior the implementation exhibits at the sites Step 7 touched, so no PRD_FINALIZED.md is produced.

## Step 9: Complete PRD — 2026-07-04T13:49:00.000Z

result: PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_0735_handmade_marketplace/workspace/PRD_COMPLETED.md — 12 minimal in-paragraph edits pinning impl behavior.

Summary:
- Source (PRD.md) 288 lines / 44047 chars; PRD_COMPLETED.md 288 lines / 48554 chars (delta +4507 chars, +0 lines).
- Counts: 10 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.3 Pagination — insert — ambiguity — added tiebreak "with ties broken by server-side insertion order" — helpers.py:79 (sort_by_created uses `_seq`).
- §2.5 Referential Integrity — insert — ambiguity — added role-based silent narrowing paragraph for list endpoints — routes/orders.py:146-149, routes/reviews.py:99-102, routes/cases.py:106-110, routes/payouts.py:106-107, routes/shipping_profiles.py:70-71, routes/materials.py:66-67, routes/vacation_periods.py:84-85.
- §2.9 OCC — revise — mismatch — pinned that any mismatch (higher or lower) rejects with ERR_STALE_SHOP_VERSION, and required/int-typed guard — routes/payouts.py:33-37,49-50.
- §3.1 Shop Suspend/Close — insert — ambiguity — added "listings cascade runs on close only when prior state was ACTIVE/VACATION" — routes/shops.py:130-133.
- §3.3 Listings personalization — revise — mismatch — pinned that `personalization_enabled` is advisory and not checked at order-placement — routes/orders.py:60-63 (no enabled-check).
- §3.3 Listings publish — insert — ambiguity — added "failure of either precondition is rejected with ERR_INVALID_STATE" — routes/listings.py:156-159.
- §3.3 Listings restock — insert — ambiguity — pinned that `restock_qty` is optional/defaults to 0, resulting <1 → ERR_INVALID_STATE, invalid type → ERR_VALIDATION, and it is ignored for MADE_TO_ORDER — routes/listings.py:194-207.
- §3.4 Order create — insert — ambiguity — pinned unknown `variation_id` → ERR_VALIDATION — routes/orders.py:53-56.
- §3.5 Pay preconditions — insert — ambiguity — pinned production overlap counted only over `IN_PRODUCTION` orders; variation sale checks only variation stock; made-to-order without primary_material_id performs no material shortfall check — services.py:98-116, routes/orders.py:192-207.
- §3.5 Pay inventory decrement — insert — ambiguity — pinned that variation sale decrements both variation `stock_qty` and listing `quantity`, and material-less made-to-order skips material decrement — routes/orders.py:220-232.
- §3.6 Cancel — insert — ambiguity — pinned variation restore, material-cascade on freed material, and no reconciliation for unpaid cancels — routes/orders.py:315-353.
- §3.7 Review response/hide — revise — mismatch — pinned `seller_response` required non-empty string; response allowed on both PUBLISHED and HIDDEN; hide only from PUBLISHED — routes/reviews.py:117, 130-133.
- §3.8 Case respond/escalate — insert — ambiguity — pinned that `message` on respond is accepted but not persisted; escalation only by original opener (else ERR_NOT_SHOP_OWNER) — routes/cases.py:129, 142-144.
- §3.8 Case resolve — insert — ambiguity — pinned per-actor state gate (seller→SELLER_RESPONDED only, admin→ESCALATED only) and missing `decision` → ERR_INVALID_RESOLUTION — routes/cases.py:165-176.
