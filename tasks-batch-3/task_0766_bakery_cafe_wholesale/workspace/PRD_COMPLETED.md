# Bakery Café & Wholesale Bread API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Bakery Café & Wholesale Bread platform, a single back-office system that unifies two businesses that share the same oven floor: a retail café that bakes to a daily par, sells over a point-of-sale counter, and marks perishable stock down as it approaches expiry; and a wholesale operation that fulfils standing restaurant orders on scheduled delivery routes and bills those customers on credit. The tension the platform must reconcile is that both businesses draw from one finite pool of baked goods, so every wholesale reservation is bread that will not be available at the retail counter, and every unsold retail unit is measurable waste.

The system is fundamentally a reconciliation ledger layered over a quota allocation. Each product family carries an allergen profile and a shelf life; each day's production is planned as a set of par quantities, physically realized as baked lots occupying timed oven slots, drawn down by counter sales and wholesale deliveries, and finally reconciled into two independent waste figures — a forward-looking target waste and a chronological actual waste. Alongside this, wholesale accounts accumulate credit balances that must never exceed their limits, standing orders spawn ad-hoc deliveries under lead-time cutoffs, and routes sequence deliveries within promised time windows. Managers orchestrate planning, pricing, and account governance; bakers record production and markdowns; cashiers ring up sales; drivers close out deliveries; and wholesale customers place and pay for their own orders.

Because the platform coordinates money, perishable inventory, and time-sensitive logistics, correctness is defined by invariants rather than by any single happy path: a par pool must always partition into what is reserved and what remains available; a credit balance must always equal the outstanding value of delivered-and-unvoided orders; and a deliver-then-void sequence must leave every derived total exactly where it started.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `Manager`, `Baker`, `Cashier`, `Driver`, and `WholesaleClient`. A `Manager` is the superset operator, governing products, ovens, bake plans, wholesale accounts, standing orders, routes, order packing and cancellation, payments, and the logical clock. A `Baker` records baked lots and performs markdowns and expiries. A `Cashier` records retail point-of-sale transactions. A `Driver` completes route stops and marks orders delivered. A `WholesaleClient` is a restaurant or wholesale customer operating on its own account.

For `Manager`, `Baker`, `Cashier`, and `Driver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any resource's `id`. For `WholesaleClient`, `X-User-ID` is the `id` of the acting `WholesaleAccount`; ownership checks on any resource that references a wholesale account compare that resource's `wholesale_account_id` to `X-User-ID`. Concretely, a `WholesaleClient` may read and act only on its own account, its own statement, its own standing orders, and its own delivery orders and payments — an attempt to touch another account's resources is rejected with `ERR_UNAUTHORIZED`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100 — a supplied value below 1 or above 100 is silently clamped into that range rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative offset is clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with resources that share the same `created_at` (common because timestamps come from the logical clock) further ordered by the sequence in which they were created. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources share a common set of system-managed fields. Every resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. Resources that can be modified after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and a `version` integer that begins at 1 (or the server's chosen initial value) and increments by one on every mutation. `Product`, `Oven`, `BakePlan`, `BakePlanLine`, `BakeLot`, `WholesaleAccount`, `StandingOrder`, `DeliveryOrder`, `DeliveryRoute`, and `RouteStop` all carry the full `updated_at` and `version` set.

The one exception is `RetailSale`, which is an immutable record of a completed point-of-sale transaction. A `RetailSale` carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because it is never modified after it is written.

Whenever a derived or computed field is recalculated as a side effect of some operation — for example a bake-plan line's reserved and available quantities, a route's load totals, or an account's credit balance — the owning resource is treated as mutated: its `updated_at` is refreshed and its `version` increments.

### 2.5. The Logical Clock and Temporal Fields

The system does not read wall-clock time. It maintains a single logical clock whose startup default is exactly `2026-03-01T00:00:00Z`; before any clock-setting call is made, every time-dependent computation reads precisely this instant. A `Manager` may advance or reset the clock through an administrative capability that accepts a single field, `to_iso8601`, and sets the logical clock to that instant. All timestamps derived by the system — a sale's `sold_at`, a lot's `best_by`, and every eligibility or cutoff comparison — are taken against this logical clock.

Several fields are instants supplied by clients: a bake plan's `production_date` and a route's `route_date` denote the calendar day (midnight UTC) the plan bakes for and the route runs; a lot's `produced_at`, `slot_start`, and `slot_end`; a route's `window_start` and `window_end`; a stop's `arrival_window_start` and `arrival_window_end`; and an order's `delivery_date`. Wherever an interval is defined by a start and an end, the end must be strictly after the start; a violation is rejected with `ERR_INVALID_WINDOW`.

### 2.6. Monetary Values, Discount Pricing, and Rounding

All monetary values in the system are integer cents. Wherever a discount or a per-unit price must be reduced to whole cents, the system rounds half up — a fractional result of exactly one half cent rounds up to the next cent. This rounding rule governs the wholesale unit price, the wholesale line total, and every markdown price.

One rounding-order rule is load-bearing and must not be simplified. When a wholesale line total is computed, the system multiplies the quantity by the product's exact discounted per-unit amount and rounds the product **once**, at the end. It does not round the per-unit price first and then multiply. This distinction matters again when an account statement is assembled: a statement sums the already-rounded per-line totals of the qualifying orders; it does not re-derive the invoice by summing exact discounted amounts and rounding a single time at the very end. Round-per-line-then-sum is the pinned order, and it can diverge from sum-then-round when several lines' fractional cents round in the same direction.

### 2.7. The Par Pool, the Credit Ledger, and Reconciliation Invariants

Two running balances are the backbone of the platform, and both are maintained by continuous reconciliation rather than by stored deltas.

The **par pool** of a bake-plan line partitions its planned quantity. At all times a line's `reserved_qty` equals the sum of the `qty` of every one of that line's delivery orders whose `fulfillment_status` is anything other than `CANCELLED`, and its `available_qty` equals `par_qty` minus `reserved_qty`. The invariant `reserved_qty + available_qty == par_qty` therefore holds continuously, and `available_qty` must never be driven negative — the reservation guard described in §3.7 exists precisely to preserve this. Whenever an order reserves or releases against a line, both derived quantities are recomputed.

The **credit ledger** of a wholesale account is likewise derived, never accumulated blindly. An account's `credit_balance_cents` equals the sum, over that account's delivered-and-not-voided delivery orders, of each order's `line_total_cents` minus its `amount_paid_cents`. Delivering an order books its outstanding amount into the balance; voiding a previously delivered order reverses exactly that booking; and a payment applied to an already-delivered order reduces the balance by the payment amount. The balance is never negative, and the guaranteed consequence is that delivering an order and then voiding it restores `credit_balance_cents` to precisely its pre-delivery value.

### 2.8. Nested Retrieval, Referential Integrity, and Validation Precedence

Requests that address nested resources validate identifiers left to right. For a path such as a route's stops or a plan's lines, the system confirms the parent exists before it looks for the child, and the first identifier in the path that does not resolve produces the corresponding not-found error (`ERR_ROUTE_NOT_FOUND`, `ERR_BAKE_PLAN_NOT_FOUND`, and so on). After path identifiers, foreign keys carried in the request body are resolved in their declared order, each producing its own resource-specific not-found error: `ERR_PRODUCT_NOT_FOUND`, `ERR_OVEN_NOT_FOUND`, `ERR_BAKE_PLAN_LINE_NOT_FOUND`, `ERR_BAKE_LOT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, and `ERR_ROUTE_STOP_NOT_FOUND`.

Validation across the whole API follows a fixed precedence, so that when several conditions could fail on the same request, the earliest failing tier is the one reported:

1. Authentication of the headers (`ERR_UNAUTHENTICATED`).
2. Authorization of the role and, for a `WholesaleClient`, ownership of the target resource (`ERR_UNAUTHORIZED`).
3. Existence of every path identifier and body foreign key (the not-found errors above), together with well-formedness of the request body — a body that is absent, missing a required field, or carrying a wrong type or an invalid enum value is rejected with `ERR_INVALID_REQUEST`. These two tier-3 concerns (existence and body well-formedness) are both evaluated before any state or business rule.
4. State legality: the target must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`; plus the state-adjacent guards described where they apply (`ERR_LOT_EXPIRED`, `ERR_ACCOUNT_SUSPENDED`, `ERR_ROUTE_NOT_DISPATCHED`).
5. Allergen safety (`ERR_ALLERGEN_CONFLICT`).
6. Referential business rules — product discontinuation (`ERR_PRODUCT_DISCONTINUED`) and account/line matching (`ERR_ACCOUNT_MISMATCH`).
7. Quantity and capacity constraints (`ERR_INSUFFICIENT_PAR`, `ERR_INSUFFICIENT_INVENTORY`, `ERR_OVEN_SLOT_CONFLICT`, `ERR_STOP_WINDOW_OVERLAP`, `ERR_DUPLICATE_STOP`).
8. Temporal constraints (`ERR_PAST_CUTOFF`, `ERR_INVALID_WINDOW`, `ERR_MARKDOWN_NOT_ELIGIBLE`).
9. The fiscal credit ceiling (`ERR_CREDIT_LIMIT_EXCEEDED`).
10. The optimistic-concurrency version check (`ERR_STALE_LOT_VERSION`).

### 2.9. Optimistic Concurrency Control on Markdowns

Recording a markdown against a baked lot is guarded by optimistic concurrency control. The markdown request must carry `expected_bake_lot_version`, a non-optional field holding the client's last observed `version` of the target `BakeLot`. If that value does not equal the lot's current `version`, the request is rejected with `ERR_STALE_LOT_VERSION` and HTTP 412. This guard exists because a lot may legitimately be marked down more than once as expiry nears — a re-markdown is a valid transition and is not blocked by any state precondition — so the version check is the only thing that distinguishes a writer whose view of the lot predates a prior markdown from one acting on the current price. The version comparison is the last check applied to a markdown, after state legality and eligibility. No other endpoint accepts or requires a version field.

### 2.10. Cascading Cancellations and Derived-Field Recomputation

Many operations mutate more than one resource, and every secondary effect is mandatory. Cancelling a delivery order releases its reservation on its bake-plan line (its `qty` is removed from the line's `reserved_qty`, and `available_qty` is recomputed) and cancels any non-cancelled route stop that references it, after which that stop's route recomputes its `stop_count` and `total_load_qty`. Closing a wholesale account cascades through its standing orders and their open delivery orders. Closing a reconciled bake plan expires every still-fresh or marked-down lot belonging to it. Each of these cascades is spelled out in the workflow subsections of §3; the governing rule here is that a cascade never stops at the primary resource, and every resource it touches has its derived fields recomputed and its `version` and `updated_at` advanced.

A route's derived load figures are pure functions of its live stops: `stop_count` is the count of the route's stops whose `status` is not `CANCELLED`, and `total_load_qty` is the sum of the `qty` of the delivery orders behind those non-cancelled stops. They are recomputed whenever a stop is added or cancelled, or when an order behind a stop is cancelled.

## 3. Business Logic & Workflows

### 3.1. The Product Catalogue and the Oven Floor

The catalogue is the starting point. A `Manager` registers a `Product` with a `sku` (a unique, non-empty stock-keeping unit), a display `name`, a `category` that is one of `BREAD`, `PASTRY`, `CAKE`, `SANDWICH`, or `OTHER`, a `base_price_cents` retail list price of zero or more cents, and a `shelf_life_hours` of at least one hour. A product may declare an `allergens` array — each entry one of `GLUTEN`, `DAIRY`, `EGG`, `NUT`, `SOY`, or `SESAME`, defaulting to empty — and an `is_custom` boolean, defaulting to false, that marks made-to-order items such as custom cakes. Every product begins with `status` equal to `ACTIVE`. The `base_price_cents` value does triple duty: it is the retail list price, the basis for wholesale discount pricing, and the per-unit basis for valuing end-of-day waste. Products can be listed with optional `category` and `status` filters.

A `Manager` may discontinue a product, moving its `status` from `ACTIVE` to `DISCONTINUED`; the transition is defined only from `ACTIVE`. Once a product is `DISCONTINUED`, it may no longer be named on a new bake-plan line, a new standing order, or a new delivery order — such attempts are rejected with `ERR_PRODUCT_DISCONTINUED`. This discontinuation guard is a tier-6 referential check on par-line creation, standing-order creation, and delivery-order creation alike.

Ovens are configured by a `Manager`. An `Oven` has a `name`, a `capacity_trays` of at least one (informational only), and a `clean_buffer_minutes` of zero or more, defaulting to 15, that fixes the mandatory cooldown-and-cleaning gap required between two consecutive bake slots on that oven. An oven's `status` begins `ACTIVE` and may later be `RETIRED`. Ovens can be listed with an optional `status` filter.

### 3.2. Planning the Day: Par Lines and Commitment

Daily production is organized by a **bake plan**. A `Manager` opens a `BakePlan` for a given `production_date`, optionally with free-text `notes` (default null); it is created in `DRAFT` with waste totals of zero. While the plan is `DRAFT`, the manager adds **par lines** to it. Each `BakePlanLine` names a `product_id` and a `par_qty` of at least one — the planned bake quantity and the finite pool that wholesale and pre-orders reserve against. The line's `bake_plan_id` is taken from the plan in the path, and on creation its `available_qty` equals its `par_qty` while its `reserved_qty` is zero. A line also carries the computed fields `baked_qty`, `sold_qty`, `delivered_qty`, `theoretical_waste_units`, and `actual_waste_units`, all starting at zero and populated as production and reconciliation proceed. Par lines can be listed under their plan, and can also be listed across plans and filtered by `bake_plan_id` or `product_id`.

Committing a plan freezes the day's par pools: a `Manager` advances the plan from `DRAFT` to `COMMITTED`, a transition defined only when the plan is `DRAFT` and it already holds at least one par line. A plan later moves from `COMMITTED` to `BAKED` automatically the first time a lot is recorded against any of its lines — the baker does not request this transition explicitly. From `BAKED` the plan can be reconciled, and from `RECONCILED` it can be closed; those two stages are covered in §3.5.

### 3.3. Baking Lots and Oven-Slot Scheduling

Physical production is captured as **bake lots**. A `Manager` or `Baker` records a `BakeLot` against a `bake_plan_line_id`, on a given `oven_id`, with a `baked_qty` of at least one physical unit, a `produced_at` instant, and an occupancy interval defined by `slot_start` and `slot_end`. On creation the lot's `best_by` is computed as `produced_at` advanced by the product's `shelf_life_hours`; its `remaining_qty` is initialized to `baked_qty`; its `status` is `FRESH`; its `markdown_price_cents` is null; and its `current_unit_price_cents` is the product's `base_price_cents`. Recording the lot recomputes the line's `baked_qty`, and if the parent plan is `COMMITTED` it advances the plan to `BAKED`. Recording a lot carries no bake-plan-state precondition: a lot may be recorded against a line whose plan is in any status, and the `COMMITTED`→`BAKED` advance fires only when the plan happens to be `COMMITTED` at that moment (a plan in any other state is left unchanged).

The occupancy interval is subject to two temporal rules. First, `slot_end` must be strictly after `slot_start` (and likewise `produced_at` is a plain instant); an inverted or empty interval is rejected with `ERR_INVALID_WINDOW`. Second, the new lot must not collide with another lot on the same oven: treating each lot's `[slot_start, slot_end]` occupancy as a closed interval and requiring the oven's `clean_buffer_minutes` of clear separation between consecutive slots, any overlap — including endpoints that merely touch, or a gap smaller than the buffer — is rejected with `ERR_OVEN_SLOT_CONFLICT`. Although stated first here, the interval-validity check ranks below the slot-conflict check in the validation precedence of §2.8 (tier 8 versus tier 7): when a proposed lot both collides with an existing slot and has an inverted or empty interval, `ERR_OVEN_SLOT_CONFLICT` is the error reported. Lots can be fetched individually and listed, filterable by `bake_plan_line_id`, `oven_id`, or `status`.

A lot's `remaining_qty` is floor stock: it is drawn down only by retail sales, never by wholesale delivery. Its `current_unit_price_cents` is the markdown price while the lot is `MARKED_DOWN`, and otherwise the product's `base_price_cents`.

### 3.4. Retail Sales and Shelf-Life Markdowns

A `Cashier` or `Manager` records a point-of-sale transaction as a `RetailSale`, naming a `bake_lot_id` and a `qty` of at least one. The sale snapshots the lot's `current_unit_price_cents` into the sale's `unit_price_cents`, sets `total_cents` to the quantity multiplied by that unit price, and stamps `sold_at` with the current logical-clock instant. The sale then reduces the lot's `remaining_qty` by the quantity sold and increases the owning line's `sold_qty` by the same amount; if the draw takes `remaining_qty` to exactly zero, the lot advances to `SOLD_OUT`. A sale whose quantity exceeds the lot's `remaining_qty` is refused with `ERR_INSUFFICIENT_INVENTORY`, and a sale against an `EXPIRED` lot is refused with `ERR_LOT_EXPIRED`. A lot's sales history can be listed under the lot.

As a lot nears its `best_by`, a `Baker` or `Manager` marks it down. The number of hours to expiry is the `best_by` minus the current clock instant, expressed in hours and possibly fractional. A markdown is eligible only when that figure is at most eight hours and strictly greater than zero; a still-`FRESH` or `MARKED_DOWN` lot with more than eight hours of life left, or one whose `best_by` is already at or past the current clock instant, is refused with `ERR_MARKDOWN_NOT_ELIGIBLE`. A lot that is already in `EXPIRED` status is instead refused with `ERR_LOT_EXPIRED`, applied as a tier-4 state guard ahead of the eligibility comparison. The discount is tiered. When more than four hours remain, the base discount is 25%; when four hours or fewer remain (but the lot is still not expired), the base discount is 50%. A surplus bonus of an additional 15% is added when the remaining ratio — the lot's `remaining_qty` divided by its `baked_qty` — is at least one half. The resulting discount is then capped at 60%. The `markdown_price_cents` is the product's `base_price_cents` multiplied by one minus the final discount, rounded half up to whole cents, and the same value is written to `current_unit_price_cents`.

The first markdown moves the lot from `FRESH` to `MARKED_DOWN`. A lot may be marked down again while already `MARKED_DOWN`: the price is recomputed on the same tiers as the hours-to-expiry figure shrinks, superseding the prior `markdown_price_cents`. Both the first markdown and every re-markdown require the caller to supply `expected_bake_lot_version` matching the lot's current `version` and increment that `version` by one on success (see §2.9); an optional free-text `reason` may accompany the request. A `Baker` or `Manager` may also expire a lot outright, moving it from `FRESH` or `MARKED_DOWN` to `EXPIRED`, which removes it from floor stock.

### 3.5. Reconciliation and Closing the Bake Plan

Once the day's baking and selling are done, a `Manager` reconciles a `BAKED` plan, advancing it to `RECONCILED` and computing waste for every line. For each par line, let the baked total be the sum of `baked_qty` across all of that line's lots regardless of lot status, let the sold figure be the line's `sold_qty`, and let the delivered figure be the sum of `qty` across that line's delivery orders whose `fulfillment_status` is `DELIVERED`. Two waste figures are then produced. The **theoretical** waste — the forward-looking, par-based target — is the amount by which the baked total exceeds the line's `par_qty`, floored at zero, and is written to the line's `theoretical_waste_units`; it ignores actual sell-through. The **actual** waste — the chronological, sales-based end-of-day figure — is the baked total minus the sold figure minus the delivered figure, floored at zero, and is written to the line's `actual_waste_units`. The two diverge whenever the baked total differs from par or sell-through differs from what the overbake would predict.

The plan's own totals are then set: `total_theoretical_waste_units` is the sum of every line's `theoretical_waste_units`; `total_actual_waste_units` is the sum of every line's `actual_waste_units`; and `total_waste_value_cents` is the sum, over lines, of each line's `actual_waste_units` multiplied by its product's `base_price_cents`. All of these are integers.

Finally, a `Manager` closes a `RECONCILED` plan, advancing it to `CLOSED`. Closing cascades a cleanup: every lot of that plan still in `FRESH` or `MARKED_DOWN` is transitioned to `EXPIRED`.

### 3.6. Wholesale Accounts, Contract Pricing, and Standing Orders

A `Manager` opens a `WholesaleAccount` with a customer `name`, a `credit_limit_cents` of zero or more, an optional `contract_tier` that is one of `STANDARD`, `PREMIUM`, or `BULK` (defaulting to `STANDARD`), and an optional `allergen_restrictions` array drawn from the same allergen vocabulary as products. The account opens `ACTIVE` with `credit_balance_cents` of zero. A `WholesaleClient` may read its own account. The `allergen_restrictions` set is a hard safety boundary: ordering a product whose `allergens` intersect the account's restrictions is refused with `ERR_ALLERGEN_CONFLICT`, and this allergen check guards both delivery-order creation and standing-order creation.

The `contract_tier` selects the wholesale discount. The per-unit price starts from the product's `base_price_cents`; the tier discount is 10% for `STANDARD`, 15% for `PREMIUM`, and 20% for `BULK`. A volume floor then applies: when the ordered quantity is at least 24 units, the discount is raised to no less than the bulk rate of 20% (that is, the greater of the tier discount and 20%). The booked `unit_price_cents` is the base price times one minus the effective discount, rounded half up. The booked `line_total_cents` is the ordered quantity times the base price times one minus the effective discount, with the multiplication performed on the exact discounted amount and the rounding applied once at the end. The reference `list_total_cents` is simply the quantity times the base price with no discount, and diverges from the booked total by exactly the discount whenever a discount applies.

Recurring business is modelled as **standing orders**. A `Manager` creates a `StandingOrder` naming a `wholesale_account_id`, a `product_id`, a `qty_per_delivery` of at least one, a non-empty `weekday_mask` whose entries are drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, and `SUN`, and an optional `cutoff_hours` lead time (default 24, zero or more). The standing order opens `ACTIVE`. A manager may pause an `ACTIVE` standing order to `PAUSED` and resume a `PAUSED` one back to `ACTIVE`; while a standing order is `PAUSED`, no new delivery order may cite it. Standing orders can be read by their owning `WholesaleClient` and listed with `wholesale_account_id`, `product_id`, or `status` filters.

Cancelling a standing order — permitted from either `ACTIVE` or `PAUSED` — sets it to `CANCELLED` and triggers a three-link cascade. First, every delivery order citing this standing order whose `fulfillment_status` is `PENDING`, `PACKED`, or `OUT_FOR_DELIVERY` is transitioned to `CANCELLED`. Second, each such order cancellation releases its par (the order's `qty` is removed from its bake-plan line's `reserved_qty`) and cancels that order's non-cancelled route stop, if any. Third, each stop cancellation makes the stop's route recompute its `stop_count` and `total_load_qty`.

### 3.7. Delivery Orders: Reservation, Fulfilment, and Payment

A wholesale **delivery order** is where the par pool, contract pricing, and credit ledger meet. A `Manager` or `WholesaleClient` creates a `DeliveryOrder` naming a `wholesale_account_id`, a `product_id`, a `bake_plan_line_id` (the par pool it reserves from), a `delivery_date`, and a `qty` of at least one, and optionally a `standing_order_id` for orders spawned from a recurring template (null for one-off ad-hoc orders). On creation the order is priced by the contract-tier rules of §3.6 — populating `unit_price_cents`, `line_total_cents`, and `list_total_cents` — reserves its quantity against the line (raising `reserved_qty` and lowering `available_qty`), and opens with `payment_status` of `UNPAID` and `fulfillment_status` of `PENDING`, with `amount_paid_cents` at zero.

Creation is gated by several checks beyond allergen safety and product discontinuation. The order's `bake_plan_line_id` must reference a line whose product matches the order's `product_id`, and any cited `standing_order_id` must belong to the same `wholesale_account_id` and be `ACTIVE`; either mismatch is refused with `ERR_ACCOUNT_MISMATCH`. The reservation must not drive the line's `available_qty` negative — the ordered quantity must not exceed the currently available quantity — else `ERR_INSUFFICIENT_PAR`. For an order citing a standing order, the current clock must be at least `cutoff_hours` before the `delivery_date`; an order placed inside that lead-time window is refused with `ERR_PAST_CUTOFF`. Delivery orders can be fetched (a `WholesaleClient` only its own) and listed with filters on `wholesale_account_id`, `standing_order_id`, `bake_plan_line_id`, `product_id`, `delivery_date`, and `fulfillment_status`.

Fulfilment and payment advance on two independent tracks. On the fulfilment track: a `Manager` packs a `PENDING` order to `PACKED`, but only if the order's account is `ACTIVE` — a `SUSPENDED` or `CLOSED` account blocks packing with `ERR_ACCOUNT_SUSPENDED`. A packed order becomes `OUT_FOR_DELIVERY` automatically when a route covering it is dispatched (see §3.8). Marking an order delivered advances it to `DELIVERED`: this can happen directly from `PACKED` as a counter delivery without a route (performed by a `Manager` or `Driver`, and subject to the credit ceiling below), or from `OUT_FOR_DELIVERY` after dispatch (performed by a `Manager` or `Driver`, or reached automatically when a route stop is completed). Either way, delivery books the order's outstanding amount — `line_total_cents` minus `amount_paid_cents` — into the account's `credit_balance_cents`, and that quantity feeds the line's `delivered_qty` at the next reconcile. Before a direct counter delivery is allowed, the projected balance (the account's current `credit_balance_cents` plus the order's outstanding amount) must not exceed the account's `credit_limit_cents`; a breach is refused with `ERR_CREDIT_LIMIT_EXCEEDED`. This same fiscal ceiling also guards delivery-order booking at creation.

An order may be cancelled by a `Manager`. Cancelling an order that is `PENDING`, `PACKED`, or `OUT_FOR_DELIVERY` sets it to `CANCELLED`, releases its par (its `qty` leaves the line's `reserved_qty`, and `available_qty` is recomputed), and cancels any non-cancelled route stop referencing it, after which that stop's route recomputes its load. Cancelling an order that is already `DELIVERED` is a void: it likewise moves to `CANCELLED` and releases its par, but it additionally reverses the credit that delivery booked — the outstanding amount is subtracted back out of `credit_balance_cents` — so that a deliver-then-void sequence leaves the balance exactly where it began.

On the payment track, independent of fulfilment, a `Manager` or `WholesaleClient` applies a payment of `amount_cents` to an order that is not `CANCELLED`. A payment strictly between zero and the outstanding amount moves an `UNPAID` order to `PARTIALLY_PAID`; a payment exactly equal to the remaining outstanding amount settles a `PARTIALLY_PAID` order to `PAID`; and a payment equal to the full `line_total_cents` moves an `UNPAID` order straight to `PAID`. Each payment adds to `amount_paid_cents` (a full settlement sets it to `line_total_cents`). The `amount_cents` must be a positive integer of at least 1, else `ERR_INVALID_REQUEST`. Any payment that does not match one of the three transitions above — an amount larger than the outstanding balance, a partial payment against a `PARTIALLY_PAID` order whose amount does not exactly clear the remaining outstanding balance, or any payment against an order that is already `PAID` — is rejected with `ERR_INVALID_STATE`; a payment against a `CANCELLED` order is likewise rejected with `ERR_INVALID_STATE`. If the order has already been delivered, the payment also reduces the account's `credit_balance_cents` by the payment amount, since that outstanding value is no longer owed.

### 3.8. Routes, Stops, and Dispatch

Wholesale deliveries are sequenced onto **routes**. A `Manager` creates a `DeliveryRoute` for a `route_date` with a `driver_name` and an operating window defined by `window_start` and `window_end` (end strictly after start); it opens `PLANNED` with `stop_count` and `total_load_qty` at zero. The manager then adds **stops** to the route. A `RouteStop` names a `delivery_order_id`, a `sequence` of at least one giving the visit order, and a promised arrival window defined by `arrival_window_start` (inclusive) and `arrival_window_end` (exclusive); the stop's `route_id` comes from the route in the path and it opens `PENDING`. Adding a stop is not gated by the route's status — a stop may be added regardless of whether the route is `PLANNED`, `DISPATCHED`, or in any other state. Adding a stop recomputes the route's `stop_count` and `total_load_qty`.

Two placement rules govern stops. A stop's arrival window is treated as half-open, so touching endpoints are allowed, but it must not overlap the window of any other non-cancelled stop on the same route — an overlap is refused with `ERR_STOP_WINDOW_OVERLAP` — and the stop window must fall within the route's own `[window_start, window_end)` operating window, with both windows well-formed, else `ERR_INVALID_WINDOW`. Additionally, at most one non-cancelled stop may reference a given delivery order; a second is refused with `ERR_DUPLICATE_STOP`. Routes and their stops can be fetched and listed; stops can be listed under their route or across routes filtered by `route_id`, `delivery_order_id`, or `status`.

Dispatching a route advances it from `PLANNED` to `DISPATCHED`, and is defined only when the route has at least one stop (`stop_count` of one or more). Dispatch moves every covered order that is `PACKED` to `OUT_FOR_DELIVERY`. A `Driver` (or `Manager`) then completes each stop: completing a `PENDING` stop requires its route to be `DISPATCHED` — otherwise `ERR_ROUTE_NOT_DISPATCHED` — and sets the stop to `DELIVERED`, which drives its `OUT_FOR_DELIVERY` order to `DELIVERED` (booking credit as in §3.7). When every non-cancelled stop of a dispatched route has reached `DELIVERED`, the route automatically advances to `COMPLETED`. A `Manager` may instead cancel a `PLANNED` route, which sets it to `CANCELLED` and cancels all of its still-`PENDING` stops. Whenever a stop is cancelled — whether by route cancellation, order cancellation, or a standing-order cascade — its route recomputes `stop_count` and `total_load_qty`.

### 3.9. Account Statements and Closure

A `Manager` or the owning `WholesaleClient` may pull a daily statement for an account, supplied with a `delivery_date`. The statement gathers the account's delivery orders for that exact `delivery_date` whose `fulfillment_status` is `DELIVERED` and returns three figures: `invoice_total_cents`, the sum of those orders' already-rounded `line_total_cents`; `list_total_cents`, the sum of their `list_total_cents`; and `order_count`, the number of qualifying orders. As stressed in §2.6, the invoice sums the pre-rounded per-line totals rather than re-deriving from exact discounted amounts.

Governance of an account closes the loop. A `Manager` may suspend an `ACTIVE` account to `SUSPENDED`, which (per §3.7) blocks packing of its orders. Closing an account is permitted from either `ACTIVE` or `SUSPENDED`, but only when its `credit_balance_cents` is exactly zero; the account then moves to `CLOSED` and a cascade runs. Every standing order of the account that is `ACTIVE` or `PAUSED` is cancelled, and each such standing order's non-cancelled, non-delivered delivery orders (those in `PENDING`, `PACKED`, or `OUT_FOR_DELIVERY`) are cancelled as well — which releases their par exactly as an individual order cancellation would, cancelling any route stops and recomputing route loads along the way.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions, markdowns, payments, and cancellations — return `200 OK`. The single administrative clock-setting capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Manager |
| POST | `/products` | Create a product | Manager |
| GET | `/products` | List products | Manager, Baker, Cashier, Driver, WholesaleClient |
| GET | `/products/{id}` | Get a product | Manager, Baker, Cashier, Driver, WholesaleClient |
| POST | `/products/{id}/discontinue` | Discontinue a product | Manager |
| POST | `/ovens` | Create an oven | Manager |
| GET | `/ovens` | List ovens | Manager, Baker |
| POST | `/bake-plans` | Create a daily bake plan | Manager |
| GET | `/bake-plans/{id}` | Get a bake plan with waste totals | Manager, Baker |
| POST | `/bake-plans/{id}/lines` | Add a par line to a draft plan | Manager |
| GET | `/bake-plans/{id}/lines` | List a plan's par lines | Manager, Baker |
| POST | `/bake-plans/{id}/commit` | Commit a plan | Manager |
| POST | `/bake-plans/{id}/reconcile` | Reconcile a plan; compute waste | Manager |
| POST | `/bake-plans/{id}/close` | Close a reconciled plan; expire lots | Manager |
| GET | `/bake-plan-lines/{id}` | Get a par line | Manager, Baker |
| GET | `/bake-plan-lines` | List par lines | Manager, Baker |
| POST | `/bake-lots` | Record a baked lot | Manager, Baker |
| GET | `/bake-lots/{id}` | Get a bake lot | Manager, Baker, Cashier |
| GET | `/bake-lots` | List bake lots | Manager, Baker, Cashier |
| GET | `/bake-lots/{id}/retail-sales` | List a lot's POS sales | Manager, Baker, Cashier |
| POST | `/bake-lots/{id}/markdown` | Mark a lot down (OCC-guarded) | Manager, Baker |
| POST | `/bake-lots/{id}/expire` | Expire a lot | Manager, Baker |
| POST | `/retail-sales` | Record a POS sale | Cashier, Manager |
| POST | `/wholesale-accounts` | Create a wholesale account | Manager |
| GET | `/wholesale-accounts/{id}` | Get an account | Manager, WholesaleClient |
| POST | `/wholesale-accounts/{id}/suspend` | Suspend an account | Manager |
| POST | `/wholesale-accounts/{id}/close` | Close an account; cascade cancellations | Manager |
| GET | `/wholesale-accounts/{id}/statement` | Get an account's daily invoice | Manager, WholesaleClient |
| POST | `/standing-orders` | Create a standing order | Manager |
| GET | `/standing-orders/{id}` | Get a standing order | Manager, WholesaleClient |
| GET | `/standing-orders` | List standing orders | Manager, WholesaleClient |
| POST | `/standing-orders/{id}/pause` | Pause a standing order | Manager |
| POST | `/standing-orders/{id}/resume` | Resume a standing order | Manager |
| POST | `/standing-orders/{id}/cancel` | Cancel a standing order; cascade | Manager |
| POST | `/delivery-orders` | Create a delivery order | Manager, WholesaleClient |
| GET | `/delivery-orders/{id}` | Get a delivery order | Manager, WholesaleClient |
| GET | `/delivery-orders` | List delivery orders | Manager, WholesaleClient |
| POST | `/delivery-orders/{id}/pack` | Pack an order | Manager |
| POST | `/delivery-orders/{id}/deliver` | Mark an order delivered | Manager, Driver |
| POST | `/delivery-orders/{id}/payments` | Apply a payment | Manager, WholesaleClient |
| POST | `/delivery-orders/{id}/cancel` | Cancel or void an order | Manager |
| POST | `/delivery-routes` | Create a delivery route | Manager |
| GET | `/delivery-routes/{id}` | Get a route | Manager, Driver |
| POST | `/delivery-routes/{id}/dispatch` | Dispatch a route | Manager |
| POST | `/delivery-routes/{id}/cancel` | Cancel a planned route | Manager |
| POST | `/delivery-routes/{id}/stops` | Add a stop to a route | Manager |
| GET | `/delivery-routes/{id}/stops` | List a route's stops | Manager, Driver |
| GET | `/route-stops/{id}` | Get a route stop | Manager, Driver |
| GET | `/route-stops` | List route stops | Manager, Driver |
| POST | `/route-stops/{id}/complete` | Complete a stop; deliver its order | Manager, Driver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_OVEN_NOT_FOUND` | 404 |
| `ERR_BAKE_PLAN_NOT_FOUND` | 404 |
| `ERR_BAKE_PLAN_LINE_NOT_FOUND` | 404 |
| `ERR_BAKE_LOT_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_STANDING_ORDER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_ORDER_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_ROUTE_STOP_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOT_EXPIRED` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_ACCOUNT_MISMATCH` | 409 |
| `ERR_INSUFFICIENT_PAR` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_OVEN_SLOT_CONFLICT` | 409 |
| `ERR_STOP_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_STOP` | 409 |
| `ERR_PAST_CUTOFF` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_MARKDOWN_NOT_ELIGIBLE` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_LOT_VERSION` | 412 |
