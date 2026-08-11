# Worklog — task_0985_firewood_bulk_fuel_delivery

Scenario: 985. Firewood & Bulk-Fuel Delivery: product (cord/pellet) & seasoned grade, order & stacking add-on, delivery route & window, winter subscription, volume pricing, moisture/quality, area restriction, billing

Difficulty parameter: "generate task hard than expert level!" (passed through to prd-bench-scaffold-generator at Step 2 only)

## Step 1: Create Task Directory — 2026-08-10T10:04:25.241Z

Output folder pre-assigned by the caller: `tasks/task_0985_firewood_bulk_fuel_delivery` with `workspace/` subdirectory already present. Step 1 auto-index scan skipped per instructions; directory treated as created. Environment verified: skills at `/home/ubuntu/github/CodingPRD/skills/`, `prd-bench-local-run` at `/usr/local/bin/prd-bench-local-run`, root `INSTRUCTION.md` present.

## Step 2: Generate Scaffold — 2026-08-10T10:25:12.686Z

## Step 2 complete: Scaffold generated for task_0985_firewood_bulk_fuel_delivery

**Scenario:** "985. Firewood & Bulk-Fuel Delivery: product (cord/pellet) & seasoned grade, order & stacking add-on, delivery route & window, winter subscription, volume pricing, moisture/quality, area restriction, billing"

**Difficulty calibration:** Substantially harder than expert level — pricing-engine archetype blended with temporal windowing, layered with optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions, derived-field reconciliation, and rate-threshold triggers.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/SCAFFOLD.yaml` — 1728 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1396 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/SCAFFOLD_CORNER_DESIGN.yaml` — 1172 lines

### Scaffold counts (§1.0–§1.7)
- Entities: **11** (Customer, Product, AreaRestriction, Subscription, DeliveryRoute, DeliveryWindow, Order, OrderLine, MoistureReading, Invoice, PaymentEvent)
- State machines: **5** (Customer, Subscription, DeliveryWindow, Order [parallel payment × fulfillment axes], Invoice)
- Calculations: **14** (cord_equivalent_conversion, seasoned_grade_price_multiplier, volume_tiered_discount [marginal straddle], subscription_discount, loyalty_tier_discount, seasonal_surcharge, stacking_fee, delivery_fee [provisional vs final variant], order_total, cancellation_fee, subscription_shortfall_penalty, subscription_early_termination_clawback [provisional vs final variant], moisture_pass_fail, invoice_amount_snapshot)
- Endpoints: **52** (incl. `/_clock/set_current_utc`, `/_sweep/season_end` test-driving endpoints)
- Errors: **27**
- Roles: **5** (Customer [entity_backed:Customer], CustomerService [opaque], OperationsManager [opaque], RoutePlanner [opaque], Driver [opaque])
- Concurrency rules (OCC): **3** (order-schedule, order-reschedule, subscription-attach)
- Validations: **24** priority-ordered

### §1.8 difficulty instances: **18** (exactly 2 per rule × 9 rules)
- dual_variant_calc: 2 (delivery_fee provisional-vs-final; clawback provisional-vs-final — different entity domains)
- combinatorial_formula: 2 (volume tier marginal straddle [mode a]; stacking-fee circular evaluation-order pinning [mode c] — different modes)
- non_linear_state_machine: 2 (Order parallel axes; Subscription 4-terminal branching)
- transitive_cascade: 2 (deliver → subscription → loyalty [depth 3]; window-lock → dispatch eligibility [depth 2])
- priority_pair_validation_conflict: 2 (state vs business_temporal; business_safety vs business_fiscal — different pairs)
- boundary_precision_check: 2 (window capacity `<=` equality permitted; moisture ceiling inclusive `<=`)
- cross_entity_state_dependency: 2 (Order→Customer account_status; DeliveryWindow→Order payment_status)
- resource_temporal_overlap: 2 (window half-open hours; area-restriction year-wrapping calendar window — different interval semantics)
- compensating_invariant: 2 (stock conservation available+reserved; invoice paid-refunded zero-sum with wallet credit)

### §1.9 corner instances: **35**
- entities: 7, state_machines: 5, calculations: 3, validations: 8, endpoints: 2, errors: 2, rbac: 4, cross_cutting_layers: 3, consistency_model: 1

### Lint verdict
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 52 endpoints, 11 entities, 18 §1.8 instances, 35 §1.9 instances, 446 calls scanned, 0 violations.

## Step 3: Copy Shared Files — 2026-08-10T10:25:38.312Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_0985_firewood_bulk_fuel_delivery/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T10:39:53.452Z

## Step 4 Complete: PRD Generation — task_0985_firewood_bulk_fuel_delivery

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/PRD.md`
**Line count:** 324 lines
**Inputs read:** `/home/ubuntu/github/CodingPRD/skills/prd-bench-doc-generator/SKILL.md`, `.../section-2.2-response-structure.md` (verbatim §2.2 source), `.../example-prd.md` (style reference), `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/SCAFFOLD.yaml`. The two forbidden files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were not opened, grepped, or referenced; no other tasks/ directory was touched.

### Section list
- §1. Introduction (2 paragraphs: business context + logical-clock technical constraint)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block, byte-identical) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, and Versioning · 2.5 The Logical Clock and Scheduled System Actions · 2.6 Money, Precision, and Rounding Conventions · 2.7 Optimistic Concurrency Control · 2.8 Validation Order of Precedence · 2.9 Nested Resource Retrieval
- §3. Business Logic & Workflows (9 subsections, organized by business-process timeline with cross-cutting concerns woven in)
  - 3.1 Customer Accounts, Wallet Credit, and Loyalty Standing · 3.2 The Fuel Catalog and Delivery-Area Restrictions · 3.3 Winter Subscriptions: Commitment, Activation, and Early Exit · 3.4 Delivery Routes and Windows · 3.5 Composing and Submitting an Order · 3.6 The Pricing Pipeline: From Line Prices to Order Total · 3.7 Delivery-Day Execution: Dispatch, Moisture Verification, and Failed Delivery · 3.8 Invoicing, Payments, Refunds, and Cancellation · 3.9 Season-End Sweep and Settlement Reconciliation
- §4. Endpoint Definitions (52-row table, 4 columns only: Method / Path / Description / Authorized Role(s))
- §5. Error Code Catalogue (27-row table, 2 columns only: Error ID / HTTP Status Code)

### Zero-Silence self-audit (every scaffold rule verified covered by PRD prose)

**Contract 1 — Field-Name Coverage: PASS.** Mechanical diff (fenced code blocks stripped before tokenization): 100 required identifiers — 89 `entities[].fields[].name` across all 11 entities, 9 endpoint-input-only names (`to_iso8601`, `season_year`, `reason`, `lines`, `expected_customer_version`, `expected_order_version`, `current_utc`, `transitioned_subscription_ids`, plus `limit`/`offset`) — 100 present in backticks, 0 missing. Two passes run; pass 1 caught `invoice_id`, `order_line_id`, and the `VOID` state token, which were added in §3.7/§3.8 before pass 2 confirmed empty diff.

**Contract 2 — Rule Coverage: PASS.** Manual walk of every rule-bearing scaffold entry:
- validations[] with priority: 24 checked, 24 expressed in §2.8 as a numbered priority-ordered list with explicit first-failure-wins semantics, each carrying its `error_id`, HTTP status, and exact `applies_to` path set; 0 missing.
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed in §2.7 (schedule + reschedule via `expected_order_version`, subscription create via `expected_customer_version`, all rejected `ERR_STALE_VERSION` / 412, stated purely in stale-version terms); 0 missing.
- state_machines[].transitions: 31 checked (Customer 4, Subscription 6, DeliveryWindow 5 + conditional CLOSED→OPEN re-open, Order fulfillment 13, Order payment-axis 7, Invoice 5), 31 fully expressed with preconditions and per-entity version/updated_at side effects; 0 missing.
- calculations[]: 14 checked, 14 expressed as precise prose (cord-equivalent factors with 3-decimal line-level rounding; grade multipliers 0.75/1.00/1.35; marginal volume tiers T0–T3 at 2.0/4.0/8.0 with 0/4/7/11% and straddle-split, single round-half-up per line; subscription/loyalty/seasonal chain with Dec 15–Feb 15 peak and 12/8/0% rates; stacking 3,500 + 1,200×ceil; delivery-fee zones 4,500/6,500/9,500 by prefix length with >4.0/>8.0 bulk surcharges and provisional-vs-final variants; order total unrounded; cancellation fee with 72-hour threshold and mandatory admin 10%; shortfall penalty 20% with weighted-average reference and catalog fallback; clawback with 5,000-cent fee and 7-day ADJUST_CREDIT reconciliation variant; inclusive moisture ceiling; invoice snapshot with 7-day due date); 0 missing.
- validations[] conditions ↔ error_id: 24 + generic `ERR_VALIDATION` all matchable in §2.8/§3 prose; `ERR_WINDOW_LOCKED` (named in the scaffold's window-lock side effect though absent from the error catalog) is rendered in §3.4 and bridged to `ERR_WINDOW_CLOSED_FOR_SCHEDULING`; 0 missing.
- endpoints[].side_effects / applies_to: all 52 endpoints' side effects expressed in workflow narrative; all applies_to scopes enumerated; 0 missing.
- entities[].fields[] structured content: defaults/initials all placed (credit 0, loyalty STANDARD, DRAFT+UNPAID birth state, subscription PENDING, window OPEN with committed 0, invoice OPEN with paid/refunded 0, `reserved_qty` 0, `discontinued` false, `active` true, common_fields:false absence of `updated_at`/`version` on MoistureReading and PaymentEvent stated explicitly in §2.4); 0 missing.
- sibling-branch symmetry: 8 groups checked (cancel branches ×6, refund branches ×3, close ACTIVE/SUSPENDED, lock OPEN/CLOSED, window-cancel OPEN/CLOSED, sweep SHORTFALL/EXPIRED, delivery-fee variants, clawback variants) with equal prose density; 0 asymmetric.

**Contract 3 — §3 Path Purity: PASS.** 484 backticked tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path combos. Endpoints referenced only via state-transition framing, role + action verb, or capability description.

Additional contract-precision checks: §2.2 emitted verbatim (diff against `section-2.2-response-structure.md`: identical, `data: { }` left empty); §2.3 states limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending sort, and the four `meta` fields; all 5 role names exact with per-role identity prose (Customer entity-backed; the other four opaque, with `recorded_by_user_id` as the opaque-recording example); all enum/state values (57 tokens incl. tiers T0–T3, loyalty tiers, payment-event kinds) present as exact UPPERCASE strings; all 27 catalog error IDs plus `ERR_WINDOW_LOCKED` mentioned in §2/§3 narrative; logical-clock startup default `2026-05-01T00:00:00Z` stated; status-code rules (201 create / 200 modify / 204 line delete) stated in the §4 preamble.

## Step 5: Generate Unit Tests — 2026-08-10T11:02:02.353Z

## Step 5: Unit test generation — complete

**Output files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/`):

`test_helpers/` (1,117 lines):
- `types.py` (287) — 10 status enums, role enum, 13 entity TypedDicts; `MoistureReading`/`PaymentEvent` TypedDicts omit `updated_at`/`version` per PRD §2.4 append-only rule
- `api_client.py` (187) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (40 methods)
- `api_errors.py` (67) — 28 `ApiErrorId` entries + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` (163) — per-entity assertions + `assert_stock_conservation` / `assert_wallet_non_negative` invariants
- `factories.py` (117) — payload factories with unique SKU/email/ref sequencing
- `constants.py` (67) — CE factors, grade multipliers, volume tiers, loyalty/seasonal rates, zone fees, thresholds
- `test_users.py` (28) — `TEST_USERS` for the 4 opaque roles + `make_customer_headers(id)` / `make_driver_headers(id)` builders (entity-backed Customer role)
- `fixtures.py` (182) — tiers: clock control, entity creators, OCC-aware `create_subscription` (re-reads customer version), `pay_order_in_full` (reads back `total_cents`, AUTHORIZE+CAPTURE), `submit_and_pay`, `schedule_order` (fresh OCC version), `deliver_scheduled_order` (lock → clock → dispatch → moisture → deliver), `create_delivered_order`, `drive_customer_lifetime_ce` (threshold targeting)
- `__init__.py` (19) — barrel export

`test_suite/` (1,698 lines): `conftest.py` (34) + 9 test files (`test_01_customers`, `test_02_catalog_and_zones`, `test_03_order_composition`, `test_04_volume_pricing`, `test_05_routes_and_windows`, `test_06_scheduling`, `test_07_delivery_day`, `test_08_subscriptions`, `test_09_payments_invoices_cancellation`).

**Test count: 63 total — 30 queue-A (Difficulty) + 33 queue-B (Corner).**

**Coverage: Queue A — 15/18 instances covered with ≥2 tests each.** Skipped (PRD-first filter):
- `clawback_provisional_vs_final_on_post_cancellation_delivery` — the recipe cancels the subscription while O_B is SCHEDULED, but PRD §3.3 forbids cancelling an ACTIVE subscription "when no order referencing it is `SCHEDULED` or `OUT_FOR_DELIVERY`"; the scenario is unreachable, so the provisional/final divergence is not PRD-derivable.
- `order_parallel_axes_payment_and_fulfillment_independent` — the asserted chain requires reaching PAYMENT_FAILED, but the PRD never specifies what makes an authorization decline ("a declined authorization..." has no trigger a PRD-only reader can construct).
- `business_safety_vs_business_fiscal_on_refund_path` — asserts ERR_ACCOUNT_INACTIVE wins on a payments call, but PRD §2.8 rule 8 explicitly scopes that check to `POST /orders`, `POST /subscriptions`, `POST /orders/{id}/submit` only; a payments-endpoint application contradicts the PRD.

**Coverage: Queue B — 33/35 non-stub instances covered with ≥1 test each** (no `excluded_because` stubs exist). Skipped:
- `end_hour_must_exceed_start_hour` — instance asserts ERR_VALIDATION, but PRD §2.8 rule 13 uniquely assigns end_hour≤start_hour to ERR_WINDOW_CLOSED_FOR_SCHEDULING; asserted outcome contradicts PRD.
- `idempotent_capture_via_external_ref_uniqueness` — PRD §3.8 states the uniqueness constraint but never names the rejection error/status; "reject duplicate" vs "idempotent replay (2xx)" are both PRD-faithful, so no unique observable outcome.

**Setup-plumbing corrections vs. recipes (asserted values unchanged):** direct CAPTURE-without-AUTHORIZE chains replaced by AUTHORIZE+CAPTURE (PRD §3.8 capture requires AUTHORIZED); wrong hardcoded payment amounts replaced by read-back `total_cents`; routes added where recipes omitted them (PRD §3.6 ERR_NO_ROUTE on empty candidate set at draft pricing); the no-op wallet adjustment that would have stale-ned the OCC version in the GOLD-tier recipe was dropped; the OCC schedule test's version-bump uses a partial REFUND (the recipe's post-PAID AUTHORIZE is itself an invalid transition).

**Self-audit results:**
- Tag coverage: every test has exactly one `Design:` line; all 63 tags resolve to real instances in the correct rule/section — 0 errors.
- Verbatim PRD citation check (C1): automated sweep of every quoted fragment ≥12 chars against whitespace-normalized PRD.md — 0 failures (17 initial boundary-punctuation mismatches fixed by extending quotes to verbatim boundaries).
- `python3 -m py_compile` on all 19 files — OK; full-module import + `pytest --collect-only` — 63 tests collected, 0 errors.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code.

## Step 6: Generate Implementation — 2026-08-10T11:02:02.353Z

# Implementation Report: task_0985_firewood_bulk_fuel_delivery

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 69 | Flask app, blueprint registration, APIError + 404/405/generic handlers |
| `db.py` | 30 | In-memory dicts keyed by id; empty at boot, invoice sequence counters |
| `errors.py` | 147 | All 27 error IDs from PRD §5 with correct HTTP statuses |
| `response.py` | 78 | Envelope: `meta.api_request_id` (`req_` + 20 alnum), `api_request_timestamp` (ISO 8601, 3 fractional digits), `response_type`, `data`; list meta adds `limit/offset/total_count/has_more` |
| `middleware.py` | 50 | `X-User-ID`/`X-User-Role` auth; five declared roles; OperationsManager hierarchical override over CustomerService + RoutePlanner |
| `clock.py` | 49 | Logical clock pinned at `2026-05-01T00:00:00Z` on boot |
| `util.py` | 120 | Decimal half-up helpers, pagination (limit default 10, min 1, max 100, offset 0), field validation, `touch()` (version bump + updated_at) |
| `services/pricing.py` | 381 | Pricing pipeline + calculations |
| `services/domain.py` | 372 | Area restrictions, wallet clamping, loyalty recompute, season sweep, serializers |
| `routes/customers.py` | 178 | 7 endpoints |
| `routes/products.py` | 140 | 4 endpoints |
| `routes/area_restrictions.py` | 86 | 3 endpoints |
| `routes/subscriptions.py` | 195 | 5 endpoints |
| `routes/delivery_routes.py` | 82 | 3 endpoints |
| `routes/delivery_windows.py` | 164 | 6 endpoints |
| `routes/orders.py` | 861 | 15 endpoints (orders, order lines, submit/schedule/dispatch/deliver/fail/cancel, payments, reset-failure) |
| `routes/moisture.py` | 79 | 2 endpoints |
| `routes/invoices.py` | 79 | 4 endpoints |
| `routes/system_ops.py` | 82 | 2 endpoints (`_clock/set_current_utc`, `_sweep/season_end`) |

Total: ~3,253 lines.

## Endpoint coverage: 53 implemented vs PRD's 52

All 52 PRD §4 endpoints are implemented, plus one extra: `POST /api/v1/orders/{id}/payments/reset-failure`, which the PRD §3.8 payment-axis state machine requires ("a failure-reset returns it to UNPAID"; scaffold lists "POST /api/v1/orders/{id}/payments reset-failure" as a CustomerService exclusive) but which lacks its own row in the §4 table. Implemented as a sub-path of the payments surface.

## The 14 calculations

1. **cord_equivalent_conversion** — per-kind factors 1.0/0.5/0.8/0.016 stored as `Decimal`; `line_cord_equivalent` rounded half-up to 3dp at line level; order total is the Decimal sum.
2. **seasoned_grade_price_multiplier** — `unit_price_cents = round_half_up(base × {0.75, 1.00, 1.35})` frozen at line-add time; later catalog price changes do not revisit lines.
3. **volume_tiered_discount** — marginal tiers T0/T1/T2/T3 (0%/4%/7%/11% at boundaries 2.0/4.0/8.0) over order-level cumulative CE; lines processed `created_at` ASC, `line_cord_equivalent` DESC on tie; straddling lines split at boundaries with portion quantity = portion_CE / per-unit factor; portions summed unrounded, line rounded half-up once; `volume_tier_applied` = tier at the line's cumulative end.
4. **subscription_discount** — `round_half_up((subtotal − volume_discount) × discount_pct)` only when subscription ACTIVE and requested date inside season window, else 0.
5. **loyalty_tier_discount** — rate 0/2%/4% by tier at recompute time, applied to subtotal net of both prior discounts.
6. **seasonal_surcharge** — winter peak Dec 15 → Feb 15 inclusive (wraps year end, evaluated on month-day tuple); rate 12%/8%/0% by tier on the post-discount base.
7. **stacking_fee** — 0 if add-on off or qualifying subscription with `stacking_included` covers it; else 3500 + 1200 × ceil(total CE).
8. **delivery_fee** — provisional: longest-prefix match over ACTIVE routes, tie-break (smaller capacity, smaller route_code), empty set → ERR_NO_ROUTE; final (once `delivery_window_id` bound): bound window's route. Zone fee by prefix length (≥5→4500, 3–4→6500, 1–2→9500); +1500 at CE > 4.0, another +1500 at CE > 8.0.
9. **order_total** — subtotal − 3 discounts + surcharge + stacking + delivery; no further rounding.
10. **cancellation_fee** — hours until `service_date@start_hour` floored; OperationsManager always 10% of total; customer only when < 72 h; never credited to wallet; stored as `_cancellation_fee_cents`.
11. **subscription_shortfall_penalty** — 20% of shortfall CE × weighted-average `unit_price_cents` over KILN_DRIED CORD lines on the customer's DELIVERED orders this season; fallback: max `base_price_cents` × 1.35; invoiced against the most recent delivered order or as a standalone customer-bound invoice.
12. **subscription_early_termination_clawback** — sum of `subscription_discount_cents` over DELIVERED orders referencing the subscription + 5000; debited under wallet clamping. The 7-logical-day reconciliation pass is implemented at deliver-time: a subscription CANCELLED within 7 days gets the newly-delivered order's subscription discount debited via an `ADJUST_CREDIT` PaymentEvent.
13. **moisture_pass_fail** — `moisture_pct <= moisture_ceiling_pct` (inclusive boundary passes), Decimal comparison.
14. **invoice_amount_snapshot** — `amount_cents = total_cents` at PENDING_PAYMENT entry, immutable thereafter; `due_date = requested_delivery_date + 7 days`; `invoice_number = INV-<season_year>-<6-digit-seq>` with per-year sequence (season year derived from subscription when linked, else from requested delivery date: Nov/Dec → that year, Jan–Oct → previous).

## OCC and validation precedence

**OCC** (only the two PRD §2.7 surfaces accept version fields):
- `POST /orders/{id}/schedule`: `expected_order_version` must equal `Order.version`, checked at priority 6 — after state (order must be CONFIRMED or DELIVERY_FAILED, priority 5) but before window-status/cutoff/capacity checks. Mismatch → `ERR_STALE_VERSION` 412. Verified live: stale version returns 412.
- `POST /subscriptions`: `expected_customer_version` must equal `Customer.version`; creation also increments `Customer.version` per PRD §3.3.

**Validation precedence** follows PRD §2.8 strictly: auth (1) → authorization (2) → path existence left-to-right (3) → body FK existence (4) → state permission (5) → OCC (6) → self-override guard (7) → account standing (8) → area restriction (9) → discontinued (10) → quantity granularity (11) → product spec (12) → window temporal (13) → subscription season (14) → window overlap (15) → window capacity (16, equality permitted) → stock (17) → capacity hierarchy (18) → cancellability (19) → subscription ownership (20) → moisture gate (21) → refund range (22) → void eligibility (23) → outstanding refund (24); field-level failures fall through to `ERR_VALIDATION` 422. Verified live: Driver hitting a nonexistent order-cancel gets 403 before 404; CustomerService gets 404; area restriction is checked before discontinued before quantity on order create/add-line.

## Boot smoke test

Fresh process via `PORT=<port> bash start.sh`, repeated 6 times across different ports:
- Boot succeeds in ~1 s; store starts empty (`total_count: 0` on products and customers after a fresh boot — no seeding anywhere; no `seed_*` function exists).
- Unauthenticated request → 401 `ERR_UNAUTHENTICATED` in the correct envelope.
- Full lifecycle exercised: customer create → product create → route create → order create (3 cords KILN_DRIED: subtotal 39960, volume_discount 540, delivery_fee 4500, total 43920 — hand-verified marginal tier split) → submit (stock reserved, invoice issued) → authorize/capture (CONFIRMED cascade, settled_at) → schedule with stale version (412) then correct version (SCHEDULED, window committed) → lock → clock set to service date/hour → dispatch → moisture reading 18.5 ≤ 20.0 passes → deliver (DELIVERED, reservation released, customer lifetime CE 3.0).
- Subscription flow: OCC stale → 412; HEARTH_PLUS create → `stacking_included=true`; activate → prepaid credited; winter-peak order with subscription: subscription_discount 7520 = (97000−3000)×0.08, surcharge 10378 = 86480×0.12, stacking forced to 0, delivery 6000 (4500 + 1500 for CE > 4), total 102858 — all hand-verified.
- Edge checks: adjacent half-open windows permitted, true overlap → 409 `ERR_WINDOW_OVERLAP`; window capacity > route capacity → 422 `ERR_CAPACITY_MISMATCH`; DRAFT cancel by owner; pellet kind + OAK → `ERR_INVALID_PRODUCT_SPEC`; PELLET_BAG qty 1.5 → `ERR_INVALID_QUANTITY`; duplicate `external_ref` rejected; second subscription create while one is ACTIVE for the same season → `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (also guarded on the activation side).

`start.sh` honors `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec`, and the guarded `pip install` is a no-op once Flask is present so per-test reboots stay fast.

## Step 7: Run Tests and Iterate — 2026-08-10T11:19:44.682Z

## Step 7: Test/Fix Iteration Loop — Complete

**Result: all 8 parallel sweep rounds pass 63/63.**

### Iterations run
2 (iteration 1: 6 deterministic failures in all 8 rounds; iteration 2: clean).

### Tests deleted
None. Every failing test traced to verbatim PRD prose with uniquely derivable outcomes.

### Diagnosis and fixes

**Cluster A — `test_03_order_composition.py::TestOrderInitialState::test_order_initial_state_is_draft_and_unpaid`** (`NameError: create_order not defined`, all 8 rounds)
- STEP 1: PRD §3.5 covers the rule verbatim ("A new order is born in `DRAFT` on the fulfillment axis and `UNPAID` on the payment axis").
- STEP 2: TEST IS WRONG — the test called the `create_order` fixture helper but the file's `from test_helpers import (...)` list omitted it.
- Fix (test artifact): added `create_order` to the import list in `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/test_suite/test_03_order_composition.py`. No helper logic changed.

**Cluster B — window-lock cascade tests** (`test_07_delivery_day.py::TestWindowLockCascade::test_dispatch_rejected_while_window_open` and `::test_window_lock_cascade_window_order_delivery_eligibility`, `Expected response_type 'error', got 'object'`, all 8 rounds)
- STEP 1: PRD covers both rules verbatim — §3.7 "Dispatch ... is permitted only when the bound window is `LOCKED`..." and §2.5 "Crossing a delivery window's day-before cutoff — 18:00 local time on the day before the window's `service_date` — automatically locks that window."
- STEP 2: TEST IS WRONG — both tests scheduled a paid order into an OPEN window (service_date 2026-08-20) and then advanced the clock to the service date, assuming the window remained OPEN. Per PRD §2.5 the cutoff crossing at 2026-08-19T18:00 auto-locks it (the scheduled order is necessarily PAID, since scheduling requires CONFIRMED), so dispatch correctly succeeded. An OPEN window holding a paid scheduled order cannot exist on its service date; the tests' premise was PRD-inconsistent.
- Fix (test artifact): `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/test_suite/test_07_delivery_day.py` — both tests now close the window manually (`POST /delivery-windows/{id}/close`, RoutePlanner) before advancing the clock. Auto-lock fires only on OPEN windows, so the CLOSED window stays non-LOCKED on the service date; with date and hour conditions satisfied, dispatch is rejected `ERR_INVALID_STATE` 409 solely for the window gate. The cascade test then locks manually (§3.4: "a planner may also lock an `OPEN` or `CLOSED` window manually") and asserts dispatch succeeds to `OUT_FOR_DELIVERY`. Assertions unchanged in strength (exact error_id + status); docstrings updated to cite §2.5 and explain the CLOSED vehicle.

**Cluster C — volume-pricing subtotal semantics** (`test_04_volume_pricing.py::test_volume_tier_marginal_straddle_across_boundary` `88800 == 90000`; `::test_stacking_fee_circular_evaluation_order_pinned_stages` `460620 == 486000`; `::test_stacking_fee_circular_evaluation_order_pinned_total` `380191 == 401632`; all 8 rounds)
- STEP 1: PRD §3.6 covers every asserted field verbatim. Unique-derivability analysis: the sentence "The order's `subtotal_cents` is the sum of extended prices" (unbackticked "extended prices" = standard line extensions, unit_price × quantity) is the only reading under which the three surrounding sentences cohere — "`subscription_discount_cents` is ... applied to the subtotal net of the volume discount", loyalty "applied to the subtotal net of both prior discounts", and "`total_cents` is `subtotal_cents` minus `volume_discount_cents` minus ...". All three require a gross (pre-volume-discount) subtotal so each discount is subtracted exactly once; the discounted-subtotal reading double-charges the volume discount in the total and makes "net of both prior discounts" incoherent.
- STEP 3: IMPLEMENTATION FIX — `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/implementation/services/pricing.py`, `recompute_order_pricing`: `subtotal_cents` now accumulates the gross per-line amount `round_half_up(unit_price_cents × quantity)`, and `volume_discount_cents = subtotal − Σ extended_price_cents` (was: subtotal accumulated the discounted extended prices, double-applying the volume discount downstream). Downstream stage bases (`subtotal − volume_discount`, etc.) were already formula-correct and now yield the PRD values: straddle line extended 88800 with subtotal 90000/discount 1200; GOLD+ESTATE scenario subtotal 486000, volume 25380, subscription 55274, loyalty 16214, surcharge 0, stacking 0, delivery 12500, total 401632 — all hand-verified live against a booted server before the sweep.
- Ripple check: the only other hardcoded pricing assertions in the suite (`test_03` subtotal 108000 with zero volume discount, stacking 5900, unit prices, `test_06` delivery fee 9500) are discount-free and unaffected; `test_09` derives invoice/fee expectations dynamically from response fields.

### Final sweep evidence (iteration 2, `results.1..8.json`)
- Round 1: 63/63 · Round 2: 63/63 · Round 3: 63/63 · Round 4: 63/63 · Round 5: 63/63 · Round 6: 63/63 · Round 7: 63/63 · Round 8: 63/63 (0 failed, 0 errors, 0 skipped in every round)

### Files changed
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/test_suite/test_03_order_composition.py` — import fix (test bug).
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/test_suite/test_07_delivery_day.py` — two TestWindowLockCascade tests made PRD-consistent with §2.5 auto-lock via manual window close (test bug).
- `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/implementation/services/pricing.py` — `recompute_order_pricing` subtotal/volume-discount semantics (implementation bug).

Step 7 exit condition met: clean 8-round parallel sweep, no deletions, no skips, no weakened assertions.

## Step 8: Finalize PRD — 2026-08-10T11:29:25.173Z

## Step 8 — PRD Finalization Report (task_0985_firewood_bulk_fuel_delivery)

### Line counts and delta
- `PRD.md`: 323 lines; `PRD_FINALIZED.md`: 323 lines. Delta: 0 lines (0.0%); exactly one line modified in place (line 184, §3.6 volume-discount paragraph). No sections added or removed.

### Triage of step_7_diff items
- **Cluster A** (`test_03` missing `create_order` import) — pure test-artifact bug. PRD §3.5 pins the rule verbatim ("A new order is born in `DRAFT` on the fulfillment axis and `UNPAID` on the payment axis"); impl matches at `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/implementation/routes/orders.py:266-267`. **No PRD edit.**
- **Cluster B** (window-lock cascade tests) — pure test-artifact bug; the tests' premise (a window staying OPEN on its service date) contradicted PRD §2.5/§3.4. Impl matches PRD verbatim on all three pinned behaviors: auto-lock applies to OPEN windows only (`workspace/implementation/routes/system_ops.py:40-58`), manual lock from OPEN or CLOSED (`workspace/implementation/routes/delivery_windows.py:131-141`), dispatch gate LOCKED + service date + hours (`workspace/implementation/routes/orders.py:532-549`). Step 7 changed tests only; impl was untouched and PRD-conformant. **No PRD edit.**
- **Cluster C** (subtotal/volume-discount semantics) — the one item where implementation previously used a different logic than the PRD and Step 7 applied an `implementation/` fix (`services/pricing.py`). Although Step 7 derived the intended reading by cross-sentence coherence, the PRD sentence "The order's `subtotal_cents` is the sum of extended prices" sits two sentences after the discounted field `extended_price_cents` is defined, and empirically produced the buggy reading in 8/8 rounds — it did not uniquely determine the behavior for a fresh reader. Patched (one edit, below).

### Changes
- **§3.6 — revise —** Replaced the closing sentence of the volume-discount paragraph. `subtotal_cents` is now defined explicitly as the sum over lines of the undiscounted line amount (`unit_price_cents` × `quantity`, rounded half-up to integer cents per line), "taken gross of the volume discount (it is not the sum of the discounted `extended_price_cents`)"; the `volume_discount_cents` clause is kept verbatim and anchored with the derivable identity "`subtotal_cents` minus `volume_discount_cents` always equals the sum of the lines' `extended_price_cents`" — `workspace/implementation/services/pricing.py:219-236` (per-line gross accumulation at :225, assignments at :235-236).

### Pre-edit search log (NO-NEW-MISMATCH RULE)
Edit 1 (the only edit):
- **(a) Subject:** computation of order `subtotal_cents` and `volume_discount_cents` from line-level amounts, including per-line rounding of the undiscounted amount and the relationship to `extended_price_cents`.
- **(b) Impl paths enumerated and read/grepped:** `services/pricing.py:205-293` (sole computational writer; `undiscounted = round_half_up_int(unit_price_cents × quantity)` at :225, `subtotal += undiscounted` at :232, `volume_discount_cents = subtotal − extended_sum` at :236, downstream nets at :246/:255/:262, total at :285-293); all six callsites of `recompute_order_pricing` (`routes/orders.py:284` create, `:335` add line, `:390` patch line, `:406` delete line, `:450` submit, `:528` order PATCH/schedule fee-finalization) — all funnel through the single function, no parallel implementation; zero-initializer `routes/orders.py:270-271` (consistent: sum over zero lines = 0); read-only serializer `services/domain.py:300-301`; downstream consumers of the outputs (invoice snapshot of `total_cents`, cancellation fee `pricing.py:297-311`, clawback `pricing.py:359-366`) — all insensitive to this definition beyond the gross semantics. PRD-side neighbors checked: §2.6 rounding convention (line 88), §3.6 lines 178/186/188/196 ("net of the volume discount", "net of both prior discounts", total formula) — all cohere only under the gross-subtotal reading; no other PRD sentence uses "extended prices" unbackticked. Test anchors confirmed consistent: test_03 subtotal 108000 with zero discount, test_04 straddle 90000/1200/88800 and GOLD+ESTATE 486000/25380/…/401632.
- **(c) Wording adjustment:** replaced the ambiguous "sum of extended prices" with the explicit per-line gross definition plus a negative clause naming `extended_price_cents`, kept the second clause verbatim, and appended the identity `subtotal − volume_discount == Σ extended_price_cents` (true at `pricing.py:236` by construction) as a reader checksum. Made the per-line half-up rounding of the undiscounted amount explicit to match `pricing.py:225` exactly; this is an application of §2.6, not a new rule, and holds for every enumerated path.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-10T11:52:42.743Z

## Step 9 report — PRD_COMPLETED.md produced

**Source:** `workspace/PRD_FINALIZED.md` (323 lines) → **output:** `workspace/PRD_COMPLETED.md` (324 lines; +1 line = the added §4 table row). Character delta: +3,525 chars (55,362 → 58,887). Diff touches 37 existing paragraphs/rows in place plus 1 added table row; no new sections, no renumbering.

**Method:** copied PRD_FINALIZED.md, then walked every file in `implementation/` (all 10 route modules, services/pricing.py, services/domain.py, middleware/response/util/clock/db/app) endpoint-by-endpoint, transition-by-transition, formula-by-formula, and pinned each behavior into the PRD with minimal inline edits. Tests were used only as cross-reference (e.g. confirming `discount_pct=0.05` fractional semantics in test_helpers/factories.py:58).

**Counts:** 33 ambiguity-pins, 18 mismatch-revisions (51 total).

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.1 — insert — ambiguity — ownership checks evaluated after path-existence and referenced-existence resolution — implementation/routes/orders.py:192-199
- §2.3 — insert — ambiguity — list ordering ties broken by `id` after `created_at` asc — implementation/util.py:103
- §2.4 — insert — ambiguity — `version` starts at 1 (was "its initial value") — implementation/routes/customers.py:41 (all creates)
- §2.4 — insert — ambiguity — record timestamps (`created_at`/`updated_at`/envelope) use wall clock; business timestamps (`issued_at`, `settled_at`, `scheduled_at`, `delivered_at`, `activated_at`, `closed_at`, `recorded_at`) use the logical clock — implementation/util.py:11-18 vs implementation/routes/orders.py:479
- §2.5 — insert — ambiguity — clock-triggered auto-lock applies the same all-scheduled-orders-PAID precondition as manual lock; failing windows stay OPEN — implementation/routes/system_ops.py:44-58
- §2.8 rule 4 — insert — ambiguity — `route_id` added to body-referenced FK list — implementation/routes/delivery_windows.py:53-56
- §2.8 rule 8 — insert — ambiguity — account-standing check also applies to `POST /api/v1/subscriptions/{id}/activate` — implementation/routes/subscriptions.py:140-141
- §2.8 rule 10 — insert — ambiguity — discontinued check also applies at `POST /api/v1/orders/{id}/submit` — implementation/routes/orders.py:430
- §2.8 rule 14 — insert — ambiguity — subscription-season check also applies at submit when attached — implementation/routes/orders.py:436-437
- §2.8 closing — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — implementation/app.py:45-51
- §3.1 — insert — ambiguity — reinstatement with outstanding refunds rejected with `ERR_OUTSTANDING_REFUND` — implementation/routes/customers.py:128-129
- §3.2 — insert — ambiguity — out-of-set `product_kind`/`species` also rejected with `ERR_INVALID_PRODUCT_SPEC` — implementation/routes/products.py:30-36,45-46
- §3.2 — insert — ambiguity — PATCH also permits seasoned-grade/species corrections, re-validated under the spec rule — implementation/routes/products.py:133-138
- §3.3 — insert — ambiguity — one-ACTIVE-per-season check evaluated after the OCC version check — implementation/routes/subscriptions.py:60-70
- §3.3 — insert — ambiguity — activation also rejected with `ERR_SUBSCRIPTION_ACTIVE_EXISTS` when another ACTIVE sub exists for the season — implementation/routes/subscriptions.py:148-156
- §3.4 — insert — ambiguity — `postal_code` list filter returns routes serving the code by prefix match — implementation/routes/delivery_routes.py:75-80
- §3.4 — insert — ambiguity — `CANCELLED` windows do not participate in the overlap check — implementation/routes/delivery_windows.py:42
- §3.5 — insert — ambiguity — initial `lines` may be omitted or empty — implementation/routes/orders.py:228
- §3.6 — insert — ambiguity — stacking per-cord uses a ceiling; an exact whole number of cords is unchanged — implementation/services/pricing.py:276
- §3.6 — insert — ambiguity — scheduled (final) fee with no matching bound-route prefix falls back to zone C — implementation/services/pricing.py:194
- §3.7 — insert — ambiguity — self-override window is strictly less than one logical hour — implementation/routes/moisture.py:43
- §3.7 — insert — ambiguity — a passing reading exactly 24 logical hours old still qualifies at completion — implementation/routes/orders.py:568
- §3.7 — insert — ambiguity — failure `reason` is recorded in the order's `cancelled_reason` — implementation/routes/orders.py:638
- §3.8 — insert — ambiguity — invoice `season_year` taken from the attached subscription, else derived from `requested_delivery_date` (Nov–Dec → that year, Jan–Oct → previous), sequence per season year from 000001 — implementation/routes/orders.py:454-465, implementation/services/pricing.py:375-378
- §3.8 — insert — ambiguity — decline convention: any positive `amount_cents` authorizes (not checked against invoice); non-positive denotes decline → `PAYMENT_FAILED` — implementation/routes/orders.py:765-781
- §3.8 — insert — ambiguity — duplicate `external_ref` per (invoice, kind, ref) rejected with `ERR_VALIDATION` — implementation/routes/orders.py:741-748
- §3.8 — insert — ambiguity — `CHARGEBACK` debits the wallet under clamping; `ADJUST_CREDIT` debits when positive, credits when negative; both postable whenever the order has an invoice, neither alters order/invoice status — implementation/routes/orders.py:826-847
- §3.8 — insert — ambiguity — non-OperationsManager attempt to cancel from `DELIVERY_FAILED` rejected with `ERR_UNAUTHORIZED` — implementation/routes/orders.py:667-669
- §3.8 — insert — ambiguity — failure-reset named as `POST /api/v1/orders/{id}/payments/reset-failure`, permitted only from `PAYMENT_FAILED` — implementation/routes/orders.py:853-861
- §3.8 — insert — ambiguity — `CustomerService` cancellation fee follows the <72-hour timing rule (only OperationsManager always pays 10%) — implementation/services/pricing.py:297-311
- §3.9 — insert — ambiguity — synthetic penalty invoice opens in `OPEN`, uses the same `INV-<season_year>-<6-digit-seq>` numbering, `due_date` = sweep date — implementation/services/domain.py:150-167
- §3.9 — insert — ambiguity — catalog holding no `KILN_DRIED` `CORD` product → reference price and penalty are zero — implementation/services/pricing.py:351-354
- §4 — insert — ambiguity — added table row `POST /api/v1/orders/{id}/payments/reset-failure` (CustomerService, OperationsManager), adjudicating the known lead: the endpoint existed in impl and was implied by §3.8 prose but missing from the endpoint surface — implementation/routes/orders.py:853-861

### Mismatch-revisions (PRD said X, impl does Y — PRD revised to impl)

- §1 — revise — mismatch — "nothing in the system reads wall-clock time directly" → "no business rule reads wall-clock time directly" (created_at/updated_at/envelope use wall clock) — implementation/util.py:11-18
- §2.6 — revise — mismatch — moisture percentages recorded exactly as supplied, not rounded to one decimal — implementation/routes/moisture.py:31-33,56 (companion wording fix in §3.7)
- §2.8 rule 8 — revise — mismatch — on `POST /api/v1/subscriptions` account standing (check 8) is evaluated before OCC (check 6) — implementation/routes/subscriptions.py:52-61
- §2.8 rule 15 — revise — mismatch — removed applicability to nonexistent `PATCH /api/v1/delivery-windows/{id}` — no such route in implementation/routes/delivery_windows.py
- §2.8 rule 18 — revise — mismatch — same phantom-PATCH removal — implementation/routes/delivery_windows.py
- §2.8 rule 20 — revise — mismatch — removed applicability to nonexistent `PATCH /api/v1/orders/{id}` — no such route in implementation/routes/orders.py
- §3.1 — revise — mismatch — credit-landing mechanics: an incoming credit first pays down `outstanding_refund_cents`, remainder goes to `credit_balance_cents` (PRD had the remainder carried into outstanding) — implementation/services/domain.py:53-62
- §3.1 — revise — mismatch — wallet adjustment applies `amount_cents` as credit when positive / debit when negative under the clamping rule (not simply "adds to credit_balance_cents") — implementation/routes/customers.py:173-176
- §3.2 — revise — mismatch — `sku` is not checked for uniqueness — implementation/routes/products.py:43 (no uniqueness check exists)
- §3.3 — revise — mismatch — canonical `discount_pct` values are fractional 0.05/0.08/0.12, not "5, 8, and 12 percent" — implementation/services/pricing.py:248-250
- §3.3 — revise — mismatch — clawback reconciliation fires for any order referencing the subscription that reaches `DELIVERED` within 7 logical days (inclusive) of cancellation; the PRD's "SCHEDULED at cancellation time" precondition is unreachable because cancellation is blocked while SCHEDULED orders exist — implementation/routes/orders.py:605-623, implementation/routes/subscriptions.py:179-183
- §3.4 — revise — mismatch — `route_code` is not checked for uniqueness — implementation/routes/delivery_routes.py:27
- §3.6 — revise — mismatch — subscription discount stated explicitly as subtotal-net-of-volume-discount multiplied by `discount_pct` — implementation/services/pricing.py:248-250
- §3.8 — revise — mismatch — `CustomerService` may cancel from `DRAFT`, `PENDING_PAYMENT`, and `CONFIRMED` (narrative had named only owner/OperationsManager; §4 table already authorized CS) — implementation/routes/orders.py:670-675
- §3.8 — revise — mismatch — inside the 24-hour lock window `CustomerService` or `OperationsManager` may cancel (not "only an OperationsManager override"); a customer attempt there is rejected with `ERR_INVALID_STATE` — implementation/routes/orders.py:681-688
- §3.8 — revise — mismatch — dropped "an absolute `amount_cents` whose sign is implied by the kind" (sign is load-bearing for AUTHORIZE decline and ADJUST_CREDIT direction) — implementation/routes/orders.py:771,839-842
- §3.9 — revise — mismatch — reconciliation recap sentence aligned to the any-order-within-grace-window trigger — implementation/routes/orders.py:605-623
- §4 intro — revise — mismatch — wallet adjustment returns `201` with the updated customer, an explicit exception to the modify→200 rule — implementation/routes/customers.py:178

**Notable non-changes (verified already uniquely pinned):** refund-range vs refundable-state ordering at `POST .../payments` (the combined failure is unreachable, so §2.8 precedence needs no exception); capture double version-increment on the PENDING_PAYMENT→CONFIRMED cascade (covered by §2.4's per-mutation rule); `PARTIALLY_PAID` being unreachable given the exact-equality capture rule already pinned in §3.8; delivery releasing `reserved_qty` without restoring `available_qty` (pinned by asymmetry with the cancellation wording).
