# Worklog — task_0943_cottage_food_preorder_bakery

Scenario (verbatim): `943. Cottage-Food DTC & Pre-Order Bakery: menu & pre-order window, batch/production planning, local-pickup/porch & delivery, allergen/cottage-food labeling, subscription (bread/cookie club), payment & tip, capacity/cutoff, review`

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!"). Density parameter phrased per the 0912/0930/0934/0937 recipe — as a calibration parameter in the Step-2 prompt, never as a gate.

Host context at start: 8 cores, load ~2.5, **5 sibling PRD-bench pipelines (tasks 0938–0942) running concurrently**. Sweep concurrency to be chosen against measured load at Step 7 (2 waves of 4 baseline, narrower if saturated).

## Step 1: Create task directory — 2026-08-09T04:39:00.000Z

Created `tasks/task_0943_cottage_food_preorder_bakery/workspace`. Index 0943 = highest existing (0942) + 1.

## Step 2: Generate scaffold — 2026-08-09T05:52:00.000Z

Scaffold generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_0943_cottage_food_preorder_bakery/`.

## Files
- `SCAFFOLD.yaml` (4549 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

## Density (all targets met)
| Metric | Value | Target |
|---|---|---|
| Entities | **17** | 17–18 |
| Endpoints | **80** | 72–80 |
| Error codes | **49** | 40–50 |
| Status axes | **18**, of which **17 non-linear** | 14–17 / ≥12 |
| 3 parallel axes on one entity | **OfferWindow** (window_status × plan_status × capacity_posture) and **Order** (order_status × payment_status × handoff_status) | ≥1 |
| Calculations | **28**, of which **8 dual-variant** (variant selected by a field value) | 22–28 / ≥7 |
| Ladder rungs | **55**, fully ordered, deterministic | 40+ |
| OCC rules | **5** | ≥3 |
| Conservation invariants | **6** | ≥5 |
| Deepest cascade | **6** (IngredientLot → RecipeComponent → Recipe → Batch → OrderLine → Order → Label+refund); plus depth-4 (under-yield) and depth-3 (republish) from different triggers | depth-5/6 |
| Named constants | **72**, **0 undeclared** | 45+, zero undeclared |
| §1.8 instances | **23** (2–3 per rule, all 9 rules) | ≥18 |
| §1.9 instances | **74** (59 with full recipes + 15 `excluded_because` stubs) across 8 guide sections | — |

The only linear axis is `Payment.payment_state`. Two ordered global write gates (rung 15 permit-not-active, rung 16 LOCKED window) pre-empt many later rungs, each with an explicit `applies_to` carve-out.

## Audits A–F

**A. Incremental writes** — every file built in 5–8 bounded `Write`/append increments; no single large write. No write-boundary deaths.

**B. YAML lint** — all three files `yaml.safe_load` clean. One known offender hit and fixed: `$.data[0].id` inside a flow mapping (nested `[`) broke the parse in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; all list-indexed JSONPaths are now quoted. Also hit and fixed a generator bug where a doubled-brace template block was appended unsubstituted (truncated and regenerated).

**C. Undeclared-constant sweep** — automated regex sweep of ALL_CAPS tokens across all three files against `global_constants`, error ids, enum values, and state names: **0 undeclared, 72 declared, none with a null value.** Three bare tokens (`DELIVERY_FEE`, `TAXABLE_SUBTOTAL`, `EARLIEST_PLACEMENT`) were living only inside order-string values; each is now a declared constant (`REFUND_LEG_*`, `SHORTFALL_KEY_*`) with a value, and the order strings reference the constant names.

**D. Reachability audit — 7 repairs, each named:**
1. **Added `IngredientLot CONSUMED → RECALLED`** (terminal states narrowed to `[RECALLED, EXPIRED]`). `Batch MIXED → BAKED` consumes the lot, so the depth-6 recall cascade was unreachable in *every* scenario where any batch had been baked — a lot is normally recalled after it is baked into product.
2. **`Subscription ACTIVE→PAST_DUE` / `PAST_DUE→ACTIVE` preconditions retargeted from `cycle_status == CONFIRMED` to `ORDER_PLACED`.** CONFIRMED auto-advances to ORDER_PLACED inside the same request, so no cycle is ever observably CONFIRMED and the whole PAST_DUE axis plus its re-entry loop was unreachable.
3. **Rung 19 (`ERR_INVALID_STATE`) given a carve-out for `POST /batches/{id}/confirm-yield`.** Rung 19 pre-empted rung 36, making `ERR_BATCH_NOT_BAKED` unreachable; priority 36 now owns that precondition exclusively.
4. **`Order MISSED → SCHEDULED` now advances a second step to `PICKUP_READY` in the same request when the window is already HANDOFF_OPEN.** `SCHEDULED→PICKUP_READY` otherwise fires only on the window advance, so a *second* miss — and therefore rung 45 `ERR_REBOOK_LIMIT_EXCEEDED` — was unreachable.
5. **Deleted `OrderLine ALLOCATED → RECALL_VOID` as unreachable** (arithmetic/ordering infeasible: a line only becomes ALLOCATED at yield confirmation, which moves its batch out of `{PLANNED, MIXED, BAKED}` — the exact set hop 3 scraps). The reasoning is documented as a `note:` on the surviving `PENDING → RECALL_VOID`.
6. **`MoneyMovement` gained `subscription_id` (FK) and `ledger_scope` {CUSTOMER_CREDIT, SUBSCRIPTION_PREPAID, SETTLEMENT}, plus a new `subscription_prepaid_balance` calculation and `PREPAID_DEPOSIT_CYCLES: 4`.** Club prepaid deposits were otherwise summed into `Customer.credit_balance_cents`, so `credit_ledger_conservation` could not hold for any PREPAID club; `order_money_conservation` was also scoped to orders that actually have a Payment.
7. Verified all 116 transitions, 55 rungs, and every cascade leg have at least one concrete reachable input, including arithmetic feasibility (e.g. the 3-slot window makes the per-item ceiling rejection reachable; the 2.0-oven-hour window makes rung 55 reachable; the 4600/4599 cap pair makes both the exact-ceiling admit and `ERR_ANNUAL_CAP_EXCEEDED` reachable). All 49 error codes are triggered by a §1.8 or §1.9 instance; all 49 are owned by a ladder rung or OCC rule. Forbidden concurrency vocabulary: 0 hits. 97 instance names, 0 duplicates. 0 unresolvable `grounds`.

**E. Instance-verb check** — every §1.8 instance's asserted operation matches the verb in its cited grounds (checked case by case; e.g. the oven-hours instance asserts `planned_yield_units` from `UNPLANNED_to_PLANNED`, whose side effect *creates* batches with that field). One grounds gap found and fixed: the stale-subscription OCC corner asserts a created club Order, so `state_machines.SubscriptionCycle.CONFIRMED_to_ORDER_PLACED` was added to its grounds.

**F. Numerics hand-derived** — every literal was computed in Python against the declared formulas and constants. Non-monotone chain derived on both sides of both boundaries: q=13→**4600** vs q=12→**5400** (reduction *raises* the total by 800), and q=26→**9200** vs q=25→**10000** (+800). Also derived: per-line-then-sum tax **726** vs rejected sum-then-round **725**; tip on subtotal **1230** vs rejected tip-on-subtotal+tax **1269**; grand total **9691**; shortfall allocation 24/6/0 with credit **2477**; refund legs (1230, 0, 270, 0) then (0, 0, 8191, 0) driving counted gross **8461 → 0** while 1230 of tip legs never touch it; prepaid cycle **8595** vs pay-per-cycle **9550**; reserve cap **72**; allergen union `[milk, sesame, wheat]` at depth 3.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read, listed, globbed, or grepped at any point.

**Orchestrator's independent verification:** all three files `yaml.safe_load` clean; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (grep count 0); counts re-derived from the parsed YAML — 17 entities / 80 endpoints / 49 errors / 18 state machines / 28 calculations / 72 constants. Line counts 4549 / 2878 / 5382.

## Step 3: Copy INSTRUCTION.md — 2026-08-09T05:53:00.000Z

Copied repo-root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T06:10:00.000Z

PRD generated at `workspace/PRD.md`.

## Size and structure

**525 lines / 18,813 words**, written in 11 bounded increments (no single large write).

- **§1 Introduction** — 3 paragraphs (business context → window/capacity model → the two cross-cutting obligations: statutory compliance and traceability).
- **§2 Global Specifications** — 12 subsections: 2.1 Operators, Buyers, Regulators (headers, 4 roles, identity translation for all four); 2.2 API Response Structure (**verified byte-identical** to `section-2.2-response-structure.md`); 2.3 Pagination (defaults + every list filter name); 2.4 Resource Identity, Versioning, and the Logical Clock (UUID/timestamps/`version`, `MoneyMovement` having neither `updated_at` nor `version`, clock default, left-to-right path/body id resolution with its four 404 codes); 2.5 Money, Units, and Rounding (integer cents, half-up, 2-dp oven hours and rating, the pinned per-line-then-sum tax order with the 726-vs-725 illustration); 2.6 The Rejection Ladder (**all 55 rungs in order**, each with error id, HTTP status, and exact `applies_to` scope, including both global write gates with their verbatim carve-outs); 2.7 OCC (all 5 rules: endpoint + `expected_*` field + parent + error id + 412); 2.8 Statutory Envelope; 2.9 Three Capacity Axes and the Derived Posture; 2.10 Six Conservation Invariants; 2.11 Cascades, Propagation, Nested Reads; 2.12 The Status Axes (all 18 axes plus every non-lifecycle enum's value set).
- **§3 Business Logic** — 10 subsections, grouped by lifecycle/process: onboarding & permits → recipes/lots/allergens → storefront → pre-order window → order placement → the club → production/yield/shortfall/labels → handoff & routes → money → recalls & reviews.
- **§4** 80-row endpoint table, 4 columns. **§5** 49-row error table, 2 columns. File ends at §5 with no audit footer.

## Completeness counts (mechanically verified)

- **Error ids: 49 / 49** present in §2–§3 prose (plus the §5 table).
- **Constants: 72 / 72** — each verified by a distinct evidence string proving its *value* (not just its name) is recoverable from prose, e.g. `HOLD_TTL_MINUTES`→"45 minutes", `CUTOFF_EXTENSION_MINUTES`→"120 minutes", `SUBSCRIPTION_RESERVE_UNIT_SHARE_PCT`→"30 percent … rounded down", both statutory text strings verbatim.
- **Endpoints: 80 / 80** in §4; every request-body field (79), query param (42), path param (17), and computed-output field (34) appears in backticks.

Hard contracts: **Contract 1** entities 155/155, body 79/79, query 42/42, path 17/17, outputs 34/34 — 0 missing, PASS. **Contract 2** — all 55 priority rungs ordered in prose, 5 OCC rules, all 18 axes' transitions (~120) with preconditions and side effects, all 28 calculations (including all 8 dual-variant selectors), 6 invariants, 3 cascades with their non-firing hops, PASS. **Contract 3** — 1,109 backtick tokens in §3, 0 path/method violations, PASS. No fuzzy words, no operator syntax anywhere.

## Un-adjudicated friction points (both readings rendered neutrally in the prose)

1. **Label issuance version bump** (§3.7) — (a) issuance increments the *`Recipe`*'s `version` as declared, so `expected_recipe_version` must be re-read between labels of one order; (b) the increment belongs to the new `Label` alone and the recipe is untouched.
2. **Error id for unmet non-state preconditions** (§2.6 close) — the window's four temporal gates, the aggregate gates (batches all allocated, no `READY` order, replan-only-while-`PLANNED`, extension cap, recipe-retire, route sequence/complete, lot release/expiry) and the club gates carry no declared error id: (a) `ERR_INVALID_STATE` 409; (b) `ERR_VALIDATION` 400.
3. **`apply_credit_cents` vs the credit formula** (§3.9) — (a) the field is only validated against the balance and the applied amount is the full lesser-of(balance, eligible); (b) the applied amount is lesser-of(requested, eligible).
4. **`OfferWindow.confirmed_units`** (§2.9) — (a) the order-status-based definition (lines not released/void on orders in the four live statuses); (b) the field-level line-status definition (`ALLOCATED`/`FULFILLED`/`SHORTED`/`CREDITED` plus `PENDING` lines of `CONFIRMED` orders). They diverge on `PENDING` lines of `IN_PRODUCTION`/`READY` orders and on `ALLOCATED` lines of `FORFEITED` orders.
5. **`review_window_closed_latch`** (§3.10) — (a) set on the first observation of a closed window, after which rung 41 rejects on the latch; (b) a passive field nothing writes, rung 41 evaluated purely from the clock.
6. **Customer standing `unattended_consent` / `cooler_provided`** (§3.1) — (a) defaults inherited onto each new order; (b) informational only, order-level flags are the sole gate for rungs 31/32.
7. **Rungs 25 and 26 on listing-status** (§2.6) — (a) guard only transitions *into* `LISTED`; (b) guard *every* listing-status call, which would trap a refrigerated or unpublished-recipe item in `LISTED`.
8. **Shortfall credit for a `DECLINED`/`VOIDED` payment** (§3.7) — matched by neither declared variant: (a) takes the `SHORTFALL_CREDIT` branch (no money left the operator); (b) no movement is written at all.
9. **Club-generated order's `placed_at`** (§3.6) — (a) set to the current instant, so the order joins the counted `cap_year` set; (b) stays null, so the calendar-year filter excludes it from counted gross.
10. **Prepaid club order's `grand_total_cents`** (§3.6) — (a) stays 0, since the grand-total computation is triggered by payment authorisation and no payment exists; (b) computed at cycle confirmation via the pinned six steps with a zero tip.
11. **Forfeiture of a missed DELIVERY order** (§3.8) — the order-axis transition restricts `FORFEITED` to pickup modes while the handoff-axis `MISSED → FORFEITED` names no mode and compares against a `pickup_forfeit_at` that is null for delivery: (a) forfeiture is unreachable for delivery; (b) the handoff axis admits it.

**Orchestrator's independent verification:** `PRD.md` 525 lines / 18,813 words; 5 top-level sections (`## 1`–`## 5`), 30 headings total; §4 endpoint table has exactly **80** method rows; **49** unique `ERR_*` tokens; file terminates inside the §5 table (not truncated mid-sentence).

## Step 5: Generate unit tests — 2026-08-09T06:55:00.000Z

(Launched concurrently with Step 6 in a single assistant message — parallel throughput plus physical isolation, since `test_suite/` did not exist on disk when impl-gen started.)

Test infrastructure complete. `workspace/implementation/` was never read, listed, or globbed.

## File inventory

**`test_helpers/`** (2,748 lines)
| file | lines |
|---|---|
| `__init__.py` | 37 |
| `api_client.py` | 390 (one method per each of the 80 endpoints) |
| `api_errors.py` | 112 (49 error ids + status map, registered with the framework) |
| `assertions.py` | 359 (semantic instant helpers, 17 entity assertions, 6 invariant checkers) |
| `constants.py` | 138 |
| `factories.py` | 234 |
| `fixtures.py` | 867 (5 tiers: primitives → storefront → order lifecycle → production/accumulation → club/route/review) |
| `test_users.py` | 44 |
| `types.py` | 567 (18 status enums, 15 other enums, 17 entity TypedDicts) |

**`test_suite/`** (3,990 lines, 11 files + `conftest.py`): `test_01_operator_and_storefront` 14 · `test_02_recipes_and_allergens` 5 · `test_03_window_capacity` 12 · `test_04_pricing_and_tax` 7 · `test_05_holds_and_cutoff` 7 · `test_06_rejection_ladder` 10 · `test_07_allergen_and_handoff` 11 · `test_08_club_subscriptions` 8 · `test_09_production_and_labels` 12 · `test_10_money_and_recall` 15 · `test_11_reviews_and_rollup` 4.

## Tests emitted: 105 (queue A 46, queue B 59)

- **Queue A**: 23/23 instances translated, **0 skipped**, exactly 2 tests each.
- **Queue B**: 59/59 non-stub instances translated, **0 skipped**, ≥1 test each. All 15 `excluded_because` stubs verified to cross-reference a real difficulty instance; none translated.

## Per-friction disposition

| # | Friction | Disposition |
|---|---|---|
| 1 | Label issuance bumps `Recipe.version`? | **(a)** `issue_label()` re-reads the recipe's `version` immediately before every issuance, and no test issues two labels from one recipe read, so the echoed value is fresh under either reading. `recipe_version_pinned` is asserted as `1` — that tracks `published_version`, a different counter PRD pins verbatim. |
| 2 | Error id for unmet non-state preconditions | **(b)** two instances touch it — `handoff_open_advance_requires_every_batch_allocated` and `cycle_confirm_blocked_by_subscription_in_past_due`. Both use a new `assert_rejected()` helper that asserts a 4xx with a well-formed error envelope and then asserts nothing was mutated; the identifier is not pinned. The second instance's other test asserts the uncontested arrears loop instead (`ORDER_PLACED` + `UNPAID` order → `PAST_DUE` + `past_due_since`). |
| 3 | `apply_credit_cents` lesser-of | **(a)** the only instance touching credit has `credit_balance_cents == 0`; lesser-of(0, eligible) = lesser-of(requested, 0-capped) = 0 either way, and the test asserts `ERR_INSUFFICIENT_CREDIT` + `credit_applied_cents == 0`. |
| 4 | `confirmed_units` order- vs line-status definition | **(a)** every one of the 12 `confirmed_units` assertions reads a window whose confirmed lines are `PENDING` lines of `CONFIRMED` orders (or nothing at all: 0). Def 1 counts "lines not RELEASED/RECALL_VOID of CONFIRMED orders" → 5/13/24; def 2 counts "PENDING lines of CONFIRMED orders" → 5/13/24. The two only diverge on `PENDING` lines of `IN_PRODUCTION`/`READY` orders and `ALLOCATED` lines of `FORFEITED` orders; no test reads capacity in either state. |
| 5 | `review_window_closed_latch` | **(a)** no test reads or asserts the field. |
| 6 | Customer standing consents inherited? | **(a)** every customer is built without `unattended_consent`/`cooler_provided`, so both default to `false`; inheritance and non-inheritance both leave the order flag `false`. The order-level flags are then set explicitly on the order or in the scheduling request. |
| 7 | Rungs 25/26 on listing-status | **(a)** the `REFRIGERATION_REQUIRED` cheesecake is created with `list_it=False` and never receives a listing-status call; no test changes listing status while a backing recipe is outside `PUBLISHED`. |
| 8 | Shortfall credit on `DECLINED`/`VOIDED` payment | **(a)** no test creates a declined or voided payment; the shortfall tests use `CAPTURED` and no-payment orders, the two branches PRD states explicitly. |
| 9 | Club order's `placed_at` → counted year | **(b)** the design's `annual_gross_sales_cents == 16273` assertion in the under-yield instance is **omitted** (it includes the club order's 9550, which the "null `placed_at`" reading excludes → 6723). Everything else in that instance is asserted, including both credit branches, both movement shapes, the allocation split 24/6/0, and `credit_balance_cents == 4600`. All other gross-sales assertions (8461→0, 4000, 4600, 8200→3600) are on club-free scenarios. |
| 10 | Prepaid club order's `grand_total_cents` | **(a)** no test asserts a club order's `grand_total_cents` or `credit_applied_cents`. |
| 11 | Forfeiture of a missed DELIVERY order | **(a)** the only forfeiture test uses `PICKUP_COUNTER`, where the path is reachable under both readings. |

## Deviations from the design indices worth flagging

- **`handing_off_a_pickup_order_after_the_grace_expires_is_rejected`**: the design marks the order `MISSED` *before* attempting `HANDED_OFF`, but `MISSED → HANDED_OFF` is not a declared transition, so rung 19 (`ERR_INVALID_STATE`) would pre-empt rung 39 and the instance's own asserted error would be unreachable. The test therefore attempts `HANDED_OFF` from `PICKUP_READY` at exactly `pickup_forfeit_at` — rung 19 passes, rung 35 is satisfied (label `ISSUED`), and rung 39 fires — then marks `MISSED` and `FORFEITED` to assert the latch, the null `fulfilled_at`, the still-`ISSUED` label, and the zero movements.
- **Ordering determinism**: because the logical clock is frozen unless moved, `created_at` ties. Two design assertions that depended on `created_at` order were made tie-free: the baker listing now asserts the two pages partition the three operators (rather than a specific `data[0]`), the money-movement listing asserts the returned id set. The two tests that legitimately exercise a PRD-declared `created_at` tie-break (route stop sequencing, under-yield walk-up priority) now advance the logical clock between the competing creations so the tie-break is observable.
- **`allergen_union_is_a_recursive_union_over_a_depth_three_tree`**: the `component_count == 2` assertion is omitted — PRD names the field in the allergen-profile response but never says whether it counts direct or transitive components (2 vs 4), so two readers diverge. Union, `tree_depth`, and the advisory text are asserted.

## Arithmetic re-derived from PRD prose (not the yaml literals)

Baker's dozen 450/4600: q=13→4600, q=12→5400 (delta +800 on a *reduction*), q=25→10000, q=24→9550, q=5→2250 — all four match §3.3/§3.6 verbatim figures. Tax 725bps half-up per line: 4600→334, 5400→392, sum 726 ≠ 725 (§2.5 worked illustration). Tip 8200×0.15=1230 ≠ 1269; grand total 8200+261+0+1230−0=9691. Shortfall credits 4600×7/13→2477 and 3600×1/4→900. Prepaid cycle 9550×0.90→8595. Oven hours 1×1.5 vs 1×3.0, remaining 18.0−4.5=13.5. Slot cap floor(240×0.30)=72.

**Every emitted test carries exactly one `Design:` line naming a real, non-stub instance** — verified programmatically, together with a verbatim `grep` of all 300+ quoted PRD citations against `workspace/PRD.md` (whitespace-normalised): 0 failures, 0 untagged tests, 0 dual-tagged tests, 0 `skip`/`skipif`/`xfail` markers, and no reference to the scaffold anywhere in the generated code. `pytest --collect-only` collects all 105 cleanly.

## Step 6: Generate implementation — 2026-08-09T06:55:00.000Z

Implementation complete at `workspace/implementation/`. Built strictly from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md — no test directory or sibling task was read.

## Module inventory (5477 lines total)

| file | lines | file | lines |
|---|---|---|---|
| `app.py` | 107 | `routes/orders.py` | 459 |
| `config.py` | 172 | `routes/handoff.py` | 289 |
| `db.py` | 134 | `routes/payments.py` | 266 |
| `errors.py` | 114 | `routes/recipes.py` | 211 |
| `ladder.py` | 270 | `routes/bakers.py` | 208 |
| `response.py` | 84 | `routes/batches.py` | 182 |
| `serialize.py` | 136 | `routes/reviews.py` | 153 |
| `tsutil.py` | 190 | `routes/menu_items.py` | 134 |
| `services/cascade.py` | 347 | `routes/delivery.py` | 132 |
| `services/money.py` | 231 | `routes/lots.py` | 119 |
| `services/capacity.py` | 192 | `routes/admin.py` | 79 |
| `services/allergen.py` | 140 | `routes/common.py` | 29 |
| `services/pricing.py` | 129 | `routes/subscriptions.py` | 445 |
| `services/gates.py` | 114 | `routes/windows.py` | 368 |
| `services/rollup.py` | 26 | `start.sh` / `requirements.txt` | 15 / 2 |

## G1 — endpoint completeness (numeric, programmatic)

Parsed SCAFFOLD `endpoints[]`, booted in-process, dumped `app.url_map`, normalised path params, diffed the sets:

```
declared endpoints : 80
matched            : 80
missing            : 0
extra              : 1   → GET /static/{}   (Flask's built-in, the one expected extra)
```

## G2 — the two recurring bugs, adjudicated

**Timestamp rendering.** Every instant is a `TS` (aware datetime + the exact string to render); `tsutil.render` is the *only* formatter and nothing else ever formats an instant. Three-case policy, verified over live HTTP:

- **Case A — canonical server-minted:** `created_at`, `updated_at`, `meta.api_request_timestamp` always render `YYYY-MM-DDTHH:MM:SS.mmmZ` (three fractional digits), because PRD §2.4 mandates exactly that for them.
- **Case B — caller-supplied echo, byte-verbatim:** `opens_at`, `order_cutoff_at`, `production_date`, `handoff_date`, `handoff_window_end_at`, `received_at`, `expires_at`, `payout_period_start`, and the clock's `to_iso8601`/`current_utc`/`previous_utc`. A plain `Z` is never normalised to `.000Z`, and a `.000000Z` input is never truncated (both verified).
- **Case C — derived, rendered in the style of its source string:** same fractional-digit count and suffix as the instant it derives from — `hold_expires_at` (placed_at + 45 m), `pickup_forfeit_at` (handoff_window_end_at + 90 m), `skip_deadline_at` (order_cutoff_at − 24 h), `review_window_closes_at` (fulfilled_at + 21 d), `MoneyMovement.expires_at` (created_at + 365 d), the extended `order_cutoff_at` (now + 120 m). Instants that *are* the logical clock (`placed_at`, `fulfilled_at`, `responded_at`, `dispatched_at`, `past_due_since`) are case C with a zero delta, i.e. they echo the clock's own string. Verified: with the clock at `...08:00:00.250Z`, `placed_at` = `2026-05-10T08:00:00.250Z` and `hold_expires_at` = `2026-05-10T08:45:00.250Z`, while `skip_deadline_at` keeps `order_cutoff_at`'s plain-`Z` style.

Comparisons never touch strings — `cmp_instants` compares `.dt` truncated to whole seconds (PRD §2.4 second granularity).

**Enum / validation routing — closed, exhaustive iff-list.** A field routes to `ERR_INVALID_ENUM` (400) **iff** it is one of: `channel`, `handoff_mode`, `disposition`, `pricing_basis`, `product_class`, `oven_profile`, `cadence`, `billing_mode`, `tip_mode`, `outcome` (both on payment authorisation and on handoff-outcome), `to_status` (permit-status, recipe lifecycle, menu-item listing-status, window advance, subscription status, route status, review moderation), `mode` (plan), `movement_kind`, and the `severity` member of an `allergen_avoidances` entry. **No other field routes here.** All sixteen reachable sites verified over HTTP.

Deliberate exclusions, each verified:
- `movement_kind` is on the declared list but **has no body site anywhere** — it appears only as a query filter, so its routing is vacuous. Named here rather than silently dropped.
- **Query filters never error**: `order_status`, `movement_kind`, `permit_status`, `window_status`, `line_status`, `lot_status`, `listing_status`, `batch_status`, `label_status`, `sub_status`, `cycle_status`, `payment_state`, `route_status`, `review_status`, `plan_status`, `capacity_posture`, `product_class`, `billing_mode`, `reason`, `ledger_scope`, `payment_status`, `handoff_status` — a nonsense value returns 200 and matches nothing.
- **Numeric-range fields** → rung 13 `ERR_VALIDATION` or their own fiscal rung, never `ERR_INVALID_ENUM`: `rating` (42 → `ERR_VALIDATION`), `quantity`, `tip_pct`/`tip_fixed_cents` (→ rung 46 `ERR_TIP_OUT_OF_RANGE` when in range but over the ceiling), `amount_cents`, `apply_credit_cents`, `actual_yield_units`, `limit`/`offset`.
- **Body FKs 404 instead**: `offer_window_id` → `ERR_OFFER_WINDOW_NOT_FOUND`, `menu_item_id` → `ERR_MENU_ITEM_NOT_FOUND`, everything else → `ERR_RESOURCE_NOT_FOUND` (verified).
- **Wrong-state values that are legal members of their set** → rung 19 `ERR_INVALID_STATE` (409), e.g. `to_status: CLOSED` on an OPEN window.
- **Free text and booleans** → rung 13 `ERR_VALIDATION` on a type violation (verified for a string field, a numeric field and a boolean field).

## G3 — EADDRINUSE-tolerant boot, self-verified

Socket pre-bound in `app.py` with `SO_REUSEADDR` in a bounded loop — **24 × 0.25 s = 6 s ceiling, then hard `sys.exit(1)`** — then served via `werkzeug.serving.make_server(..., fd=sock.fileno())`. `start.sh` guards the install behind a `find_spec` probe (not a full import).

- **(i) Squatter:** a real process held the port; the app probed `000` while squatted, then bound and answered 200 **2.61 s** after the squatter exited. PASS.
- **(ii) 14-cycle tight kill/relaunch loop:** **0 start failures / 14**, **0 orphan processes** added (baseline count identical before and after), **0** sockets left LISTENing on the port.
- **(iii) Ceiling proof:** against a *permanent* squatter the process exited **1** after 6.5 s with `could not bind 0.0.0.0:10944 within 6.0s: [Errno 98]` — bounded, never unbounded, never left to squat.

## G4 — storage and data purity

`grep -rnE 'sqlite|json\.dump|pickle|/tmp/|datetime\.now|utcnow|time\.time\(\)'` → **one match, a comment in `db.py`**. No code match. A second sweep for `open(|seed_|.write(|shelve|dbm|redis|sqlalchemy` found only `sys.stderr.write` in the bind-failure log line. `time` is imported solely for the bounded bind retry `sleep`. Store is plain dicts; **nothing is seeded, preloaded or hardcoded** — every entity is built through the declared endpoints. The clock is the PRD's logical clock, defaulting to `2026-05-01T00:00:00Z`.

## G5 — determinism

Ids are `uuid.UUID(int=(counter48 << 80) | random80, version=4)`. The version/variant bits live in the low 80 bits, so forcing them cannot disturb the counter in the high 48. Verified over 2000 ids: all canonical version-4 UUID strings, no collisions, **lexicographically ascending == creation order**, and `int >> 80 == n` exactly. PRD ordering rules that tie-break on `id` are therefore deterministic despite the coarse clock. `DB.values()` sorts by `(created_at, id)`.

## The 11 friction adjudications

Each has a `# Adjudication of friction N:` comment at its decision site.

1. **Label issuance → bumps `Recipe.version`.** Both the scaffold's endpoint side-effect list and PRD §3.7 state the increment outright; dropping it makes a declared, observable side effect unreachable, while keeping it strands nothing — a client labelling several lines re-reads the recipe between calls, exactly the consequence PRD §3.7 spells out. (`routes/batches.py`)
2. **Unmet non-state preconditions → `ERR_INVALID_STATE` (409) at rung 19.** *Forced by reachability:* routing them to `ERR_VALIDATION` places them at rung 4/13, i.e. **before** the two global write gates, which would make `ERR_PERMIT_NOT_ACTIVE` (15) and `ERR_WINDOW_LOCKED` (16) unreportable on any call that also misses a temporal gate (e.g. advancing a DRAFT window before `opens_at` under a PENDING permit). Rung 19 keeps both gates reachable. (`services/gates.py`, referenced from `recipes.py`/`lots.py`)
3. **`apply_credit_cents` → lesser-of(requested, eligible)**, omitted meaning zero. Strictly dominates the balance-driven reading: passing the whole balance reproduces it exactly, whereas the balance reading makes the state "customer holds credit **and** the order applied none of it" unreachable. Rung 48 still caps the request at the balance. (`routes/payments.py`)
4. **`OfferWindow.confirmed_units` → the order-status definition.** Essentially forced: the line-status reading diverges on PENDING lines of IN_PRODUCTION orders and ALLOCATED lines of FORFEITED orders, which would make the declared `window_unit_conservation` invariant — stated over the *stored* field — false in exactly those cases and desynchronise the stored figure from the rung 53–55 ladder. (`services/capacity.py`)
5. **`review_window_closed_latch` → actively set on first observation.** Under the passive reading nothing ever writes it, so `true` is unreachable for a declared field. Set at rung 41 on a late submission, which then rejects on the latch **or** the clock. Only that rung writes it — plain reads stay side-effect free per §2.11. (`routes/reviews.py`)
6. **Customer standing consent flags → informational only.** Strictly dominates: inheritance makes "standing consent true, order flag false" unreachable (an omitted optional flag is indistinguishable from an explicit `false`), and with it the rung 31/32 rejections for such a customer. Informational keeps all four combinations reachable. (`routes/orders.py`)
7. **Rungs 25/26 on listing-status → narrow (only transitions *into* `LISTED`).** Broad reading strands an item whose backing recipe left `PUBLISHED` — it could be neither paused nor delisted — and since a recipe may only be RETIRED while no item backed by it is LISTED, the recipe's `REVISING → RETIRED` transition becomes unreachable. Narrow strands nothing. (`routes/menu_items.py`)
8. **Shortfall credit on a DECLINED/VOIDED payment → write the `SHORTFALL_CREDIT` movement.** No money ever left the operator, which is the exact ground the credit branch stands on. Writing nothing leaves a CREDITED line with no ledger entry and makes the movement unreachable for any order whose only payment attempt was declined. (`services/cascade.py`)
9. **Club order `placed_at` → the current instant.** *Forced:* a null `placed_at` drops the order out of §2.8's `cap_year` filter, making the declared "recomputes `annual_gross_sales_cents`" side effect of cycle confirmation a no-op and rung 51's declared application to club-cycle confirmation unreachable. (`routes/subscriptions.py`)
10. **Prepaid club order `grand_total_cents` → computed at cycle confirmation** through the six pinned steps with tip 0 and the cycle price as applied credit. Such an order never sees a payment, so leaving it at 0 makes the pinned computation unreachable for the whole PREPAID club path. A PAY_PER_CYCLE club order stays at 0 until its payment, since §3.9 pins the grand total to authorisation and this friction is declared for PREPAID alone. `delivery_distance_km` is also set on a club DELIVERY order, because route sequencing sorts on it. (`routes/subscriptions.py`)
11. **Forfeiture → pickup pipeline only.** The order-axis `READY → FORFEITED` transition names the mode restriction explicitly and `pickup_forfeit_at` is null for delivery. Admitting delivery forfeiture would need an invented comparison against a null deadline, or would move `handoff_status` to FORFEITED while `order_status` could not follow — an undeclared pairing. Refusing strands nothing: FORFEITED stays reachable on both axes via the two pickup modes. (`routes/handoff.py`)

## Reachability findings (hypotheses — verify by reading the code)

1. **One deliberate widening, driven by a *demonstrated* stranding.** The scaffold gives `NOT_SCHEDULED → SCHEDULED` the precondition `order_status ∈ {CONFIRMED, IN_PRODUCTION}`. Implemented literally, this made scheduling a handoff impossible once the window reached `HANDOFF_OPEN` (every order is `READY` by then) — my suite hit a real 409, and with it PRD §3.8's declared "when the window is *already* `HANDOFF_OPEN` at the moment of scheduling, within the scheduling request itself" branch became unreachable from `NOT_SCHEDULED`, taking rungs 35 and 39 with it for any order that reached READY unscheduled. I admitted `READY` as a third source status (PRD prose over the narrower scaffold list). Site: `routes/handoff.py`.
2. **`ERR_LOT_RECALLED` on line addition is reachable only through a *sub-recipe* closure** — hypothesis, verified by test. Recall hop 2 moves the component's own recipe to `REVISING`, so rung 26 (`ERR_RECIPE_NOT_PUBLISHED`) always pre-empts rung 27 for a menu item backed by that recipe directly; but a **parent** recipe that references it stays `PUBLISHED`, so rung 26 passes and rung 27 fires. Both orderings are asserted in the suite.
3. **Rung 19 does not apply to refund creation**, mirroring the declared rung-36 carve-out on yield confirmation: rung 49 owns the payment-state precondition exclusively, otherwise `ERR_PAYMENT_NOT_CAPTURED` would be unreachable. Site: `routes/payments.py`.
4. **A negative integer amount reports rung 13 `ERR_VALIDATION`, not the later fiscal rung** — so `ERR_TIP_OUT_OF_RANGE`'s "below zero" clause is reachable via `tip_pct` (a float, not an integer amount) but not via `tip_fixed_cents`. This follows from the ladder being total with the lowest rung winning; both codes stay reachable overall.
5. **Window version bumps at most once per request per window** — when the endpoint declares it, or when `capacity_posture` moved (§2.9). This keeps an OCC client that read version *N* landing on *N+1* whether or not the posture happened to move in the same call.
6. **A baker-initiated refund carries `reason: null`** — the `reason` enum's five members all name cascades, none fits a manual refund, and `MoneyMovement` has no field for the free-text `refund_reason`. Flagging in case a later step disagrees.

## Verification totals

444 assertions across four HTTP suites, each on a fresh boot, all green: happy path end-to-end; the 55-rung ladder including both global write gates and their carve-outs; the depth-6 recall cascade with both deliberate stopping points; the depth-3 label supersession cascade; the depth-4 shortfall cascade with priority ordering and proportional credit; the non-monotone baker's-dozen pricing (12 units cost 5400, 13 cost 4600); per-line-then-sum tax (726, not 725); the per-item slot ceiling (2+2=4, not 3); both oven-hours variants; the four-leg refund waterfall with leg resumption and the tip-leg-only gross-sales carve-out; the club deposit/share cap/skip/confirm path; capacity rising when a hold lapses with nobody cancelling; the CAP_REACHED latch firing *after* the crossing confirm succeeds; delivery zone tiers with inclusive bounds; the rebook loop and the pickup grace latch.

**Orchestrator's independent isolation + readiness verification (Steps 5/6):** `grep -rIl "test_suite\|test_helpers\|conftest" workspace/implementation/` → **no hits** (physical isolation held); `grep -rIl "implementation/\|SCAFFOLD" test_suite/ test_helpers/` → **no hits**; `def test_` count **105** == `Design:` tag count **105**; `pytest.mark` occurrences **0** (every textual "skip" hit is the domain's own `skip_cycle` feature, not a marker); impl 31 modules / 5,460 `.py` lines; `start.sh` uses the `find_spec` probe as instructed.


## Step 7: Run tests and iterate — 2026-08-09T07:20:00.000Z

All 8 rounds green and every audit complete. Cleaning up my probe artifacts is done; nothing was edited after the passing sweep.

## Report

**Iterations:** 2 sweeps. `WAVE=2` both times (4 waves of 2). Load: 3.87 before sweep 1, 4.86 before sweep 2; in-sweep 1-min load 4.82–7.00, so never raised to `WAVE=4`. Sweep 1 = 104/105 in all 8 rounds (one deterministic failure, zero flakiness). Sweep 2 = **105/105 × 8**.

**Tests deleted:** none.
**Fixes to `test_suite/`:** none.
**Fixes to `implementation/`:** none.

**Fix to `test_helpers/` (1):** `test_helpers/assertions.py` → `assert_money_movement`. STEP 1c partial-coverage split: assert `reason` ∈ the §2.12 set only when a reason is present, rather than demanding presence.

Why: the shared entity-shape helper demanded a non-null `reason` on every movement, but the impl writes `reason: null` for the operator-initiated refund of §3.9. I checked all 10 other `create_movement` sites — every one carries a reason PRD assigns verbatim (SHORTFALL ×2, RECALL_VOID, CUSTOMER_CANCEL ×3, SUBSCRIPTION_PREPAY, ORDER_APPLY ×2). Only the manual refund is null, and it is the only pathway PRD assigns no reason to: the request carries free-text `refund_reason`, and all five enum members are bound by prose to *other*, system-driven pathways. That is 1b ENUM-MEMBERSHIP-ONLY collapse — picking any member would attribute a cause PRD gives to a different pathway, with no verbatim sentence to cite. The test's own docstring cites §2.4 (immutability) and §3.9 (`refunded_cents`, money axis) and never §2.12; the reason check arrived incidentally through the shared helper. The membership half (§2.12 verbatim) is kept, so the one cascade movement that uses the helper (test_09:161) is unaffected — it pins `reason == "SHORTFALL"` on the next line anyway.

### Audit A — the result is real
105 rows in every round; `passed == total == 105`, `failed == errors == skipped == 0`, status set exactly `{"passed"}`; sorted test-name lists **byte-identical across all 8** (105 unique names). `def test_` = 105 = `Design:` tags = collected count (82 unique tags — legitimately paired, e.g. each `priority_pair_validation_conflict` item has one test for the pre-empting rung and one for the pre-empted rung). 0 pytest markers (`@pytest.mark`/`pytest.skip`/`xfail`/`skipif`/`importorskip` — the `skip` grep hits are all `skip_deadline_at`/`skip_cycle` domain names). Forbidden-pattern grep on impl: single hit is db.py's comment *stating* the constraint; no `open()`/`.write()`/shelve/dbm, storage is plain dicts, empty on boot. Exactly 1 `Killed` and 0 tracebacks per round log. `find -newer results.1.json` on the three source trees: **empty** (only sibling `results.N.json` are newer, as expected) — and `assertions.py` mtime 07:06:45 < results.1.json 07:08:14, so the fix preceded the passing sweep.

**Reset witness found and used:** `test_01:93` calls `list_bakers` with **no filter** and asserts `total_count == 3` after creating exactly 3 operators — a global count every other test would inflate, since `create_baker` sits at the root of every setup. I proved it positively: run against one shared server it fails `assert 4 == 3` (one leaked operator from the preceding test). It passes in all 8 sweep rounds ⇒ per-test state reset genuinely happens. (`Killed`-once only proves a swap was attempted.)

### Audit B — the suite is FAIR (11/11 frictions, 0 DEPENDS)
| # | Friction | Verdict |
|---|---|---|
| 1 | Label issuance bumps `Recipe.version` | **AGREEMENT-BY-CONSTRUCTION** — `issue_label` re-reads the version immediately before each call; only 2 call sites, one label each. The stale/fresh test's `fresh == stale + 1` comes from `add_recipe_component` (§3.2 verbatim), captured *before* any label existed, and the rejected call mutates nothing; `recipe_version_pinned == 1` tracks `published_version`, a separate counter. |
| 2 | Non-state preconditions → 409 vs 400 | **AGREEMENT-BY-CONSTRUCTION** — the 2 gates exercised (club "membership ACTIVE", "every batch ALLOCATED/CLOSED/SCRAPPED" before handoff) use `assert_rejected`, which pins the 4xx class + envelope + no-mutation but not the identifier, matching §2.6's verbatim "rejected and nothing is mutated". The 3 tests that *do* pin `ERR_INVALID_STATE` are pure rung-19 source-state violations (re-cancel a CANCELLED order, re-lock a LOCKED window with the temporal gate already satisfied, second HANDED_OFF on a FULFILLED order). |
| 3 | `apply_credit_cents` lesser-of | **AGREEMENT-BY-CONSTRUCTION** — re-derived all 4 sites: balance is 0 at every payment authorisation, so `min(0, eligible) = min(requested, eligible) = 0`. The two tests that *do* build a balance (900, 4600) assert it as their terminal result and authorise no further payment. |
| 4 | `confirmed_units` definition | **AGREEMENT-BY-CONSTRUCTION** — re-derived the state logic at all 12 `confirmed_units` and every `units_remaining` assertion: each is taken while orders are DRAFT/PENDING_HOLD/EXPIRED_HOLD/CONFIRMED/CANCELLED. For a just-confirmed order every live line is PENDING, so definition A (order-status) and B ("PENDING lines of CONFIRMED orders") return the identical figure; RELEASED lines are excluded by both. PRD's two divergence cases — a PENDING line on an IN_PRODUCTION order, an ALLOCATED line on a FORFEITED order — are never observed (no capacity read after IN_PRODUCTION; the sole test_09 capacity read is on a LOCKED+PLANNED window and asserts only oven hours, which §2.9 derives from its own unambiguous definitions). |
| 5 | `review_window_closed_latch` set at rung 41 | **CLEAN** — appears only as a declarative field name in `types.py` (0 asserts in that file; annotations aren't enforced). No test reads it. |
| 6 | Standing consent flags informational | **AGREEMENT-BY-CONSTRUCTION** — `create_customer_payload` never sets `unattended_consent`/`cooler_provided`, so the standing flags are false everywhere; both readings give `order.unattended_consent = false` and rung 31 fires. The cooler test sets `unattended_consent=True` **on the order** explicitly, which both readings honour. test_01:133/134 assert the *customer's* own defaults (§3.1 verbatim). |
| 7 | Rungs 25/26 narrow vs broad | **CLEAN** — every rung-25/26 assertion is on line addition; the only `set_listing_status` call in the whole artifact is `to_status: LISTED` on a published, SHELF_STABLE item, which both readings guard identically. No PAUSED/DELISTED call exists. |
| 8 | Shortfall credit on DECLINED/VOIDED | **CLEAN** — no test ever sends `outcome: DECLINED`; DECLINED/VOIDED appear only inside enum-membership sets. No such payment exists, so the cascade never meets one. |
| 9 | Club order `placed_at` | **CLEAN** — no `annual_gross_sales_cents`/`cap_remaining_cents` assertion involves a club cycle (all are walk-up); no test asserts a club order's `placed_at`. |
| 10 | Prepaid club `grand_total_cents` | **CLEAN** — a PREPAID cycle *is* confirmed (`setup_under_yield_scenario`), but no test asserts that order's `grand_total_cents`, `credit_applied_cents` or `subtotal_cents`. The one club money assertion, `cycle_price_cents == 8595`, is §3.6's verbatim worked example. |
| 11 | Forfeiture pickup-only | **AGREEMENT-BY-CONSTRUCTION** — the only forfeiture test uses `setup_ready_pickup_order()`; both readings admit a *pickup* forfeiture. No delivery order ever reaches MISSED (both MISSED tests are pickup). test_09:323's `pickup_forfeit_at is None` for delivery is §3.8 verbatim. |

### Audit C — near-miss register (fair only by accident)
**Distance one (one added call / one changed value):**
1. **F4, sharpest.** `setup_under_yield_scenario` leaves an IN_PRODUCTION window with PENDING lines, and the forfeiture test leaves an ALLOCATED line on a FORFEITED order — both exact §2.9 divergence states. A single added `read_capacity(...)["confirmed_units"]` in either makes the test friction-4-dependent (A says 0/13, B says 13/0).
2. **F9.** One added `read_compliance(s.baker_id)["annual_gross_sales_cents"]` after the club-cycle confirm in test_08 or `setup_under_yield_scenario` → diverges (impl counts the club order; the null-`placed_at` reading excludes it).
3. **F10.** One added assertion on the PREPAID club order's `grand_total_cents` (impl 955; competing reading 0) — the order already exists in the suite, unasserted.
4. **F3.** The three `credit_applied_cents == 0` sites (test_04:201, test_10:98, test_10:127) are fair only because the balance is 0; granting the customer credit first flips the competing reading to a non-zero applied amount.
5. **F6.** Creating the customer with `unattended_consent=True` while the porch order omits the flag splits the two readings (inheritance schedules; informational fires rung 31).
6. **F2.** Swapping either `assert_rejected` for `validate_error(..., ERR_INVALID_STATE)` makes it friction-2-dependent immediately. (A tighter-but-still-fair form would be `validate_error_is_one_of([ERR_INVALID_STATE, ERR_VALIDATION])`, the two identifiers §2.6 names; left as-is since it is passing and grounded.)
7. **F5.** One added assertion on `review_window_closed_latch` after a late submission attempt.

**Distance two:**
8. **F1.** Needs both hoisting the version read out of `issue_label` *and* issuing a second label from the cached value.
9. **F11.** Needs driving a delivery order to MISSED (no fixture does) *and* then forfeiting it.
10. **F7.** Needs moving the recipe out of PUBLISHED *and* adding a PAUSED/DELISTED listing-status call.
11. **F8.** Needs authorising with `outcome: DECLINED` *and* routing that order through a shortfall.
12. **F3 / test_10:179.** Fair by the rung itself rather than by accident — granting ≥500 credit removes the rung-48 rejection the test exists to prove, so it needs a second change to become friction-dependent.

### Audit D — assertion provenance
- **Field names:** 129 distinct asserted keys extracted (docstrings stripped so PRD quotes don't seed the set); **123/123 genuine response fields appear verbatim in PRD.md**. The 6 non-matches are not response fields: `tree_nut`/`sesame` are allergen *values* in request payloads, and the four `*_headers` are `TEST_USERS` dict keys in conftest.
- **Numeric literals — all hand-derived from PRD formulas/constants.** Non-monotone baker's dozen: q=12→5400 vs q=13→4600, and q=25→10000 vs q=26→9200 (both directions confirmed). Per-line-then-sum tax: 4600→334, 5400→392, **order tax 726**, versus the rejected 10000-aggregate reading's **725**. Also re-derived: test_04 quote (10000/392/10892), test_10 two-item (3600 loaf line, tax 261, tip 1230 on subtotal only — *not* 1269 on sub+tax+fee, grand 9691), shortfall credits (3600×1/4=900; 4600×7/13=2477; 4600×13/13=4600), club pricing (base 9550 → 10% → 8595 → 4-cycle deposit 34380), slots/oven hours (ceil(13/24)=1 slot; STANDARD 1.5 + LONG_BAKE 3.0 = 4.5 used, 13.5 remaining; per-item 25+25→2+2=4 slots vs aggregate 50→3), share cap floor(240×0.30)=72 → 168 remaining, the §3.9 waterfall (600 → tip 450 + fee 150, gross reduced by 150 only), and the under-yield chain (demand 50 → 3 slots → planned 72; yield 30 → club 24, early 6/short 7, late 0/short 13, surplus 0).
- **Instants:** all semantic. `assert_same_instant` parses both sides and compares at second granularity per §2.4; zero byte-literal timestamp equalities anywhere in the suite.
- **List indices:** 4 total. `reviews[0]` and `orders[0]` (×2) are each on a filtered single-element list (`total_count == 1` asserted, or one order per cycle per §3.6); `exact[0]` is a Python local, not a response. Order-sensitive checks use `sorted()` (pagination partition, movement ids) or a cited PRD ordering rule — `stop_sequence` by "`delivery_distance_km` ascending, with the owning order's `created_at` ascending as the tie-break" (§3.8 verbatim) and `allergen_union` "deduplicated and sorted ascending as lowercase strings" (§3.2 verbatim).
- **Exceptions:** none.

**Orchestrator's independent re-verification of the green sweep:** all 8 `results.N.json` re-parsed → **105 individual rows each**, `passed=105 failed=0`, status set exactly `{'passed'}`, sorted test-name sha256 `539975bd363a` **identical across all 8 rounds**; 0 pytest markers in either test tree; impl forbidden-pattern grep → the single `db.py` comment only; exactly **1 `Killed` and 0 `Traceback` per round log** (rounds 1–8); `find test_suite test_helpers workspace/implementation -newer results.1.json` → **empty**; independent route diff (scaffold `endpoints[]` vs in-process `app.url_map`, params normalised) → **80 declared / 80 matched / 0 missing / 1 extra = Flask's built-in `GET /static/{}`**.

## Step 8: Finalize PRD — 2026-08-09T07:32:00.000Z

(Step 8 ran rather than being skipped: Step 7 applied 1 `test_helpers/` fix, so the zero-iteration skip condition was not met. Impl-gen's 6 confirmed reachability findings were handed down as a second source of items, per the "suite is silent → no Step-7 signal" pattern.)

Done. `PRD_FINALIZED.md` written with 6 targeted edits.

## Line counts
- `PRD.md` 525 lines / 131,755 chars → `PRD_FINALIZED.md` 527 lines / 135,042 chars (**+2 lines, +0.38% lines / +2.5% chars**). No sections added; all edits are in-place sentence revisions or one inserted paragraph in an existing section.

## Changes
- **§3.8 ¶1 (scheduling entry)** — revise — source `order_status` set for `NOT_SCHEDULED → SCHEDULED` widened from `{CONFIRMED, IN_PRODUCTION}` to `{CONFIRMED, IN_PRODUCTION, READY}`, with the rung-19 `ERR_INVALID_STATE` rejection named — `routes/handoff.py:63`
- **§3.8 ¶ rebook** — revise — a rebook (from `MISSED`) admits `READY` **alone**, and the widened set is explicitly scoped to the `NOT_SCHEDULED` branch only — `routes/handoff.py:68`
- **§2.6 rung 19** — revise — "one carve-out" → "two carve-outs": refund creation takes no source-state check; rung 49 exclusively owns the payment-state precondition (on both `payment_state` and order `payment_status`) — `routes/payments.py:175-191` (no `require_state` call in the handler)
- **§3.9 tip-range sentence** — revise — a *negative* `tip_fixed_cents` is rung 13 `ERR_VALIDATION`, not rung 46; rung 46's below-zero half is reachable via `tip_pct` only — `routes/payments.py:34` (`opt_int(minimum=0)`) vs `:48` / `:54`
- **§2.9 (after the non-monotone paragraph)** — insert — a window's `version` moves at most once per request; refreshing the four derived figures is not itself an increment; bumped on a write of the window's recorded state, on the four declared capacity writes (line add, line patch, hold sweep, cycle reservation), otherwise only on a posture move — `services/capacity.py:177-192`
- **§3.9 refund-waterfall paragraph** — insert — the operator-initiated refund's movement carries `reason` **null**, and `refund_reason` is required, validated, then discarded — `routes/payments.py:200-211`, `:184`
- **§2.12 `MoneyMovement.reason`** — revise — the field may be absent; a present `reason` is always a member of the five — `services/money.py:28-52`, `routes/payments.py:206`

## Zero-edit items
- **Finding 2 (`ERR_LOT_RECALLED` on line addition reachable only through a sub-recipe closure)** — no edit. Already governed verbatim: §2.6 — "*For any request that violates more than one rung, **the lowest-numbered violated rung wins and no later rung is evaluated at all***"; §2.6 rung 26 — "*the recipe backing every referenced menu item has `recipe_status` `PUBLISHED`… this applies to line addition*"; §3.10 Hop 2 — "*Each affected component's owning recipe moves from `PUBLISHED` to `REVISING` on its `recipe_status` axis… A recipe that was not `PUBLISHED` is not moved.*" Together these already entail that a directly-backed item fails at 26 while a parent recipe (untouched by hop 2, still `PUBLISHED`) passes 26 and fails 27. Code matches: `routes/orders.py:145` then `:146-148`; `services/cascade.py:60-69` moves only component-owning recipes. Pure reachability observation, no under-determination.

## Per-edit pre-edit search log
1. **§3.8 scheduling source set.** (a) Subject: the `handoff_status` scheduling endpoint's order-status precondition. (b) Enumerated: `routes/handoff.py:37-128` (both branches), `:135-202` (outcome preconditions incl. the `MISSED→FORFEITED` READY check), `routes/windows.py:186-216` (the `HANDOFF_OPEN` advance that makes every order `READY` and moves `SCHEDULED→PICKUP_READY`), `services/gates.py:59` `require_state`, `routes/delivery.py:64-95` (dispatch moves `SCHEDULED`+`READY` orders to `OUT_FOR_DELIVERY`). (c) Adjustment: scoped the widened list to the `NOT_SCHEDULED` branch and added the separate rebook clause, so the wording cannot be read as admitting `CONFIRMED`/`IN_PRODUCTION` on a rebook (which the impl refuses).
2. **§2.6 rung 19 carve-outs.** (a) Subject: which endpoints skip the source-state rung. (b) Enumerated: every `require_state` callsite in the codebase (grep over `routes/` + `services/gates.py`) — recipes, lots, reviews, delivery, windows, orders, batches, menu_items, payments, subscriptions, bakers, handoff; exactly two handlers have none: `routes/batches.py:81-85` (yield confirmation, already declared) and `routes/payments.py:172-196` (refund creation). (c) Adjustment: added "on either the payment's `payment_state` or the order's `payment_status` axis" so the sentence does not leave open a hidden order-axis check (there is none — a `PARTIALLY_REFUNDED` order self-loops per §3.9).
3. **§3.9 negative tip.** (a) Subject: negative integer amount/quantity fields vs the later domain rung. (b) Enumerated all `req_int`/`opt_int(minimum=…)` sites: `tip_fixed_cents`, `apply_credit_cents` (`payments.py:34-35`), refund `amount_cents`/`expected_order_version` (`:183-185`), `quantity`/`expected_offer_window_version` (`orders.py:130-131`, `:224-225`), `actual_yield_units` (`batches.py:80`), `sequence_number` (`subscriptions.py:208`), window capacities (`windows.py:58-62`), review `rating`; plus `opt_num("tip_pct")` with no minimum (`payments.py:33`) and the rung-46 checks at `:48`/`:54`. (c) Adjustment: kept the sentence strictly about the tip fields and cited rung 13's general "integers are zero or greater" rule as the mechanism, so the sibling fields (quantity → rung 34, credit → rung 48, refund amount → rung 50) are covered by the same already-stated rule without a per-field claim. Nothing was written about the absent-tip-field case (impl gives `ERR_TIP_OUT_OF_RANGE`) because that is outside the listed item — flagging it here for Step 9.
4. **§2.9 window version.** (a) Subject: every increment of an `OfferWindow.version`. (b) Enumerated all 13 `capacity.sync` callsites plus `db.touch`/`capacity.store`: force-bump — `windows.py:119,147,169,184,216,226,244,286`, `orders.py:182,257`, `subscriptions.py:246`, `admin.py:60`; posture-only — `orders.py:349,414`, `subscriptions.py:180,266,398`, `cascade.py:164`; plus every `window["…"] = ` assignment (all inside `windows.py`, each followed by a force-bump) and the read path `windows.py:349-368` (stores figures, never touches). (c) Adjustment: the first draft keyed the bump on "mutates the window", which would have wrongly implied a bump on order confirmation (it rewrites the stored figures); reworded to exclude the four derived figures explicitly and to enumerate the four declared no-recorded-state bumps and the six posture-only paths.
5. **§3.9 / §2.12 null `reason`.** (a) Subject: the `reason` field on every `MoneyMovement`. (b) Enumerated all 11 `create_movement` callsites (`grep reason=`): `payments.py:138` `ORDER_APPLY`, `payments.py:206` `None`, `orders.py:434`/`:451` `CUSTOMER_CANCEL`, `cascade.py:137` `RECALL_VOID`, `cascade.py:241`/`:268` `SHORTFALL`, `subscriptions.py:132` `SUBSCRIPTION_PREPAY`, `:160`/`:169` `CUSTOMER_CANCEL`, `:377` `ORDER_APPLY`; plus `services/money.py:28-59` (no default, field always written) and `serialize.py:91` (field always emitted). (c) Adjustment: phrased §2.12 as "a present `reason` is always a member of that set but a movement need not carry one" rather than adding `null` to the value set, and added the "every *other* movement carries one of the five" sentence so exactly one exception is licensed.

## Reachability findings — verdicts
1. **Widened `NOT_SCHEDULED → SCHEDULED` source set — CONFIRMED-BY-CODE.** `routes/handoff.py:63` accepts `("CONFIRMED", "IN_PRODUCTION", "READY")`; PRD §3.8 named only the first two. Related (also confirmed): the `MISSED` rebook branch requires `READY` exclusively, `handoff.py:68`.
2. **`ERR_LOT_RECALLED` on line addition only via a sub-recipe closure — CONFIRMED-BY-CODE, no edit.** `routes/orders.py:145` (rung 26) precedes `:146` (rung 27); `services/cascade.py:62-68` moves only the component-owning recipe to `REVISING`, leaving parents `PUBLISHED`; `services/allergen.py:97-111` scans the transitive closure. Already entailed by existing PRD prose.
3. **Rung 19 does not apply to refund creation — CONFIRMED-BY-CODE.** `routes/payments.py:172-196` has no `require_state`; rung 49 at `:189`. Mirrors `routes/batches.py:81-85`.
4. **Negative amount → rung 13, not the fiscal rung — CONFIRMED-BY-CODE.** `routes/payments.py:34` `opt_int("tip_fixed_cents", minimum=0)` → `ladder.py:133-134` `ERR_VALIDATION`; rung 46 checks only `> 5000` at `:54`, while `tip_pct` (`opt_num`, no minimum) still reaches the `< 0` check at `:48`.
5. **Window `version` bumps at most once per request — CONFIRMED-BY-CODE.** `services/capacity.py:177-192`: `sync()` touches once, iff `force_bump` or the posture moved; verified against all 13 callsites and all window field writes.
6. **Baker-initiated refund carries `reason: null` — CONFIRMED-BY-CODE.** `routes/payments.py:201-211` passes `reason=None`; `services/money.py:43` stores it verbatim; it is the only one of 11 movement writes without a reason, matching the Step-7 `test_helpers` split.

**Orchestrator's independent verification:** `PRD.md` 525 lines / 132,089 bytes → `PRD_FINALIZED.md` 527 lines / 135,393 bytes; `diff` of all `^#` headings between the two → **identical** (no sections added); `find implementation -name '*.py' -newer results.1.json` → **empty** (Step 8 touched no code).

## Step 9: Complete PRD — 2026-08-09T10:20:00.000Z

(Step 9 was interrupted mid-scan at ~§3.3 by a session-limit API error. It was **resumed from its own transcript via SendMessage rather than restarted**, so the completed portion of the scan was preserved; `PRD_COMPLETED.md` was intact on disk at the cutoff.)

# Completeness scan — task 0943 cottage-food pre-order bakery

## Size

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 527 | 530 (+3) |
| chars | 135,393 | 179,876 (**+44,483**) |

Headings identical (22 `###` subsections in both), both markdown tables byte-identical in row count, backtick/bold parity even. The +3 lines are one new bullet in §2.2's envelope list and one new paragraph in §2.4; **no new sections**.

## Counts

**84 changes — 71 ambiguity-pins, 13 mismatch-revisions.**

## Per-question yield

| | yield | headline finding |
|---|---|---|
| **Q1** field nobody reads | **14** | largest cluster again. `RecipeComponent.quantity_grams`, `Label.net_weight_grams`, `SubscriptionCycle.sequence_number`, **`Subscription.cadence`** (required, enum-validated, and then nothing ever schedules from it), `IngredientLot.received_at`, `Baker.jurisdiction_code`, `MenuItem.allergen_summary`, four Batch planning snapshots, `Review.shortfall_affected`, the three route/stop figures, and three validated-then-discarded reason strings (`cancel_reason`, `recall_reason`, plus `cap_year` on every permit move except the CAP_REACHED escape) |
| **Q2** universal quantifiers | **6** | "Baking proceeds in two steps *once the window has reached IN_PRODUCTION*" — the BAKED step takes no window check at all; §4's "endpoints that bring a new resource into existence answer 201"; "beyond 40 km the order is refused" (club-cycle confirm exempts itself); §2.4's "a request that mutates two entities increments both"; "Activation is admissible only while LISTED"; "never the identifier" |
| **Q3** derived-on-read vs stored | **6** | the order line's `hold_expires_at` mirror is **computed at serialisation**, not stored; the money breakdown recomputes *nothing* despite §4 calling it computed; the capacity read stores its four figures without bumping `version` |
| **Q4** serializer projections | **3** | one projection per entity across create/read/list/nested — no per-endpoint variation; `meta` pagination keys on list endpoints only; movements always emit all four legs |
| **Q5** list semantics | **4** | `id` ascending as tie-break; empty-string param = absent; off-enum filter → empty page never 400; `has_more` = offset + returned < total |
| **Q6** cascade legs that don't fire | **6** | a **third, unnamed stopping point** in the recall: hop 3 gathers only recipes hop 2 actually *moved*, so a batch behind a DRAFT/REVISING/RETIRED recipe is never reached; the shortfall's zero-credit guard; hop 6 always lands on `REFUNDED` |
| **Q7** version ledger | **15** | consolidated into one new §2.4 paragraph: the **operator is bumped by every gross/payout recompute** (9 call sites); balance/summary refreshes bump nothing; `Payment` returns at v1 but `SubscriptionCycle` at v2 |
| **Q8** uniqueness/scope | **5** | customer email uniqueness *is* enforced (→`ERR_VALIDATION`); `sequence_number` is not; list endpoints are unscoped; a label's `order_line_id` is never checked against its recipe; a review's `menu_item_id` need not appear on the order |
| **Q9** error precedence | **12** | the §2.6 closing open point resolved to **`ERR_INVALID_STATE` (409)** for all ~20 non-rung preconditions, plus a whole family I found unowned: an in-set-but-not-requestable `to_status` on six endpoints |
| **Q10** timestamps & defaults | **8** | three distinct rendering families (canonical 3-digit / byte-verbatim echo / style-of-source derived) |
| **carried (i)** absent tip | **1** | pinned: `PERCENT` without `tip_pct`, `FIXED` without `tip_fixed_cents` → `ERR_TIP_OUT_OF_RANGE`; and the *unused* field is ignored by rung 46 but still bound by rung 13 |
| **carried (ii)** sibling integers | **1 consolidated** | rung 13 now carries the explicit 17-field integer-floor list, so `quantity`→34, `apply_credit_cents`→48, `amount_cents`→50, `actual_yield_units`→36, `sequence_number`, capacities and `rating` each route unambiguously |

## Changes

**§2 — global (17)**

- §2.1 — revise — ambiguity — ownership walk pinned for all 8 non-owning entities; MoneyMovement exempt; lists unscoped — `ladder.py:105`
- §2.2 — insert — ambiguity — pagination meta on lists only; one projection per entity — `serialize.py:114`, `response.py:19`
- §2.3 — revise — ambiguity — limit/offset parse, empty string = absent, over-range offset — `response.py:64`
- §2.3 — revise — ambiguity — `id` tie-break; `has_more` formula — `db.py:100`, `response.py:41`
- §2.3 — insert — ambiguity — filters string-compared, never 400 — `routes/common.py:23`
- §2.4 — insert — ambiguity — three timestamp families — `tsutil.py:111`
- §2.4 — revise — ambiguity — clock response strings verbatim — `routes/admin.py:20`
- §2.4 — insert — ambiguity — cross-order `{order_line_id}` → `ERR_ORDER_NOT_FOUND` — `routes/orders.py:218`
- §2.4 — insert — **mismatch** — version ledger: operator bumps, refreshes don't, same-request creates — `db.py:130`, `payments.py:100`, `subscriptions.py:227`
- §2.6 — insert — ambiguity — rung 4 empty body = `{}` — `ladder.py:208`
- §2.6 — insert — ambiguity — rung 13 integer-floor list, null=absent, enum absence — `ladder.py:129`
- §2.6 — revise — ambiguity — rungs 25/26 **narrow** reading — `routes/menu_items.py:101`
- §2.6 — insert — ambiguity — rung 34 both halves; negative quantity → rung 13 — `routes/orders.py:149`
- §2.6 — revise — ambiguity — **all non-rung preconditions → `ERR_INVALID_STATE`** + non-requestable `to_status` family — `services/gates.py:1`
- §2.9 — revise — ambiguity — stored `confirmed_units` = order-status reading — `services/capacity.py:1`
- §2.9 — revise — ambiguity — which writes force a window bump — `services/capacity.py:177`
- §2.10/§2.11 — insert/revise — ambiguity+**mismatch** — yield invariant unreachable; quote recomputes nothing — `services/cascade.py:289`, `services/pricing.py:109`

**§3.1–3.4 — operator, recipes, storefront, window (21)**

- §3.1 ×4 — insert — ambiguity — `jurisdiction_code` unread; permit `to_status` set + `cap_year` discard; CAP_REACHED escape failure — `routes/bakers.py:33,65,78`
- §3.1 — revise — ambiguity — email uniqueness, avoidance validation, **friction 6: consent flags informational only** — `routes/bakers.py:151`, `routes/orders.py:60`
- §3.2 ×5 — insert/revise — ambiguity — `quantity_grams`; attach effects; `component_count` = direct only; lifecycle targets; lot receipt/release — `routes/recipes.py:57,78,183,117`, `routes/lots.py:32`
- §3.3 ×2 — revise/insert — **mismatch**+ambiguity — `allergen_summary` empty at creation; `DRAFT` target unreachable — `routes/menu_items.py:73,97`
- §3.4 ×7 — insert/revise — ambiguity — creation floors + rung 15 before 44; lock; extension scope; HANDOFF_OPEN stamps every pickup order; CLOSED → RECONCILED unconditionally; REPLAN line bumps; capacity read — `routes/windows.py:58,100,140,198,228,274,349`

**§3.5–3.6 — orders and the club (17)**

- §3.5 ×10 — insert/revise — ambiguity — creation defaults & no cutoff; **subsequent line does not refresh the hold**; mirror derived on read; patch disposition default; capacity **delta ≤ 0 skips all three rungs**; sweep posture selection rule; confirm prices into temporaries + lines stay PENDING; ack override + case folding; cancel (`cancel_reason` discarded, payment stays CAPTURED, no DRAFT); quote's eight fields — `routes/orders.py:77,160,226,186,299,286,388`, `serialize.py:119`, `routes/admin.py:59`, `services/pricing.py:109`
- §3.6 ×7 — insert/revise — 2 **mismatch** + 5 ambiguity — `cadence` unread; **activation LISTED gate only on PENDING→ACTIVE**; **cancel identical from all three sources** (not "no effect" from PAUSED); generation takes no `sub_status` check, cycle at v2; skip gates; club tax always 0 + **club delivery beyond 40 km yields fee 0, not a rejection**; frictions 9 & 10 both resolved — `routes/subscriptions.py:45,84,147,199,250,291,325`

**§3.7–3.10 — production, handoff, money, recall (26)**

- §3.7 ×8 — insert/revise — 2 **mismatch** — plan snapshots unread; **BAKED takes no window check**; yield bounds; sort key's two extra tie-breaks; **CAPTURED shortfall capped at remainder → can land on REFUNDED**; friction 8 (DECLINED/VOIDED take the credit branch) + zero-credit guard; label `statement_text` exact format; friction 1 (issuance bumps the recipe) — `routes/windows.py:290`, `routes/batches.py:49,80,126,156`, `services/cascade.py:172,231,254`
- §3.8 ×5 — insert/revise — 1 **mismatch** — effective consent flags + route id discarded on pickup; handoff recomputes gross too + label-consumption asymmetry; friction 11 (no delivery forfeiture); **sequencing does fall through to `id`** and resequence keeps `total_distance_km`; route defaults — `routes/handoff.py:73,205,173`, `routes/delivery.py:38,70`
- §3.9 ×9 — insert/revise — 1 **mismatch** — decline writes nothing + payment v1; **absent tip field → `ERR_TIP_OUT_OF_RANGE`**; friction 3 (request-driven credit); capture; waterfall clamp + zero refund; refund ladder order + **201 with the movement**; `payment_state` stays CAPTURED; payout scoped + full amount; `expires_at` by `movement_kind` — `routes/payments.py:45,84,100,155,183,212`, `services/money.py:48,130,201`
- §3.10 ×7 — insert/revise — 2 **mismatch** — `recall_reason` discarded; **hop 2's third stopping point**; hop 5 payout + window resync; hop 6 remainder → always REFUNDED; friction 5 (**latch actively written on a rejected submission**); review creation details; respond/moderate don't bump the item — `routes/lots.py:93`, `services/cascade.py:60,127,149`, `routes/reviews.py:55,70,104`

**§4–§5 (2)**

- §4 — revise — **mismatch** — exactly 16 endpoints answer 201; the three incidental creators (cycle confirm, plan, recall) answer 200 with their named resource
- §5 — insert — ambiguity — unknown path and unsupported method both → `ERR_RESOURCE_NOT_FOUND` 404 **before rung 1**; trailing slash insignificant — `app.py:47`

## Close calls — examined, PRD left unchanged

- **"exactly eighteen read endpoints" for `HealthInspector`** — counted the decorators: exactly 18, and the capacity read is correctly excluded. Correct as written.
- **§2.9 posture asymmetry** — `EXHAUSTED` on units `== 0` and slots `== 0` but oven `<= 0`. The code matches the prose literally, so a *negative* units_remaining is `CONSTRAINED`, not `EXHAUSTED`. Odd, but faithfully specified; left alone.
- **All five worked numeric examples verified against the code**: the 334/392/726 tax rounding, the baker's-dozen 5400/4600/10000/9200, the club 9550→8595→34,380, the 600-cent waterfall dropping gross by only 150, and the 72-unit club share cap.
- **MoneyMovement reads take no ownership check** — §2.1's original list already omitted MoneyMovement, so the PRD was right; I made the omission explicit rather than revising it.
- **Rung 17's four-operation list** — verified order creation and cycle generation genuinely take no cutoff check. Correct.
- **§2.12's claim that `reason` is null only on the operator-initiated refund** — that is the only `reason=None` call site in the codebase. Correct.

**Orchestrator's independent final verification:** `PRD.md` 525 → `PRD_FINALIZED.md` 527 → `PRD_COMPLETED.md` 530 lines (132,089 → 135,393 → 179,876 bytes); `diff` of all `^#` headings `PRD.md` vs `PRD_COMPLETED.md` → **identical** (Steps 8 and 9 added no sections); `PRD_COMPLETED.md` still carries exactly **80** endpoint rows and **49** unique `ERR_*` ids; all 8 `results.N.json` still read `passed=105 failed=0`; `find test_suite test_helpers workspace/implementation -newer results.1.json` → **empty** after cleaning one `__pycache__` directory left by the orchestrator's own route-diff import, proving Steps 8 and 9 modified no code or tests.

## Pipeline complete — final tally

105/105 tests × 8 rounds. 0 deletions, 0 `test_suite/` fixes, 0 `implementation/` fixes, 1 `test_helpers/` fix. Step 8 = 7 edits; Step 9 = 84 edits (71 pins + 13 mismatches), the largest Step-9 yield recorded on this pipeline.
