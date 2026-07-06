# Farm-Box Aggregator API — Product Requirements Document

## 1. Introduction

The Farm-Box Aggregator is a marketplace platform that connects independent local farms with shoppers who buy through pickup hubs and time-slotted home delivery. It solves a coordination problem that neither a single farm stand nor a generic e-commerce cart handles well: dozens of small vendors each offer a limited, perishable supply for a specific ordering window, customers assemble multi-farm baskets and reserve fulfillment capacity, and the platform must reconcile what was ordered against what is actually packed — where a bunch of kale priced by weight rarely weighs exactly what was estimated, and a sold-out item may be swapped for a substitute.

Layered on top of the ordering flow is a set of public-nutrition and financial obligations. The platform participates in SNAP/EBT payment and a "Double-Up" incentive that matches SNAP dollars spent on eligible produce, up to a per-customer ceiling. It also runs vendor economics: a per-farm commission is withheld from gross sales, and each cycle is settled into a per-farm payout balance. Because the same order can be re-priced between checkout and fulfillment (variable weights, shortages, substitutions, cancellations), the system distinguishes an **estimated** view computed when the customer commits from a **final** view computed when goods are physically packed, and it must issue precise partial refunds — reversing SNAP, Double-Up, and store credit in a fixed order — whenever the final value falls short of the estimate.

This document specifies the complete API contract: the resource model, the parallel state machines that govern market cycles, orders, order lines, and subscriptions, the pricing and benefit calculations in their estimated and final variants, the validation and authorization rules with their precedence, and the settlement process that closes out each cycle.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `PlatformAdmin`, `Farm`, and `Customer`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The marketplace operator runs cycle lifecycle operations, onboarding, and settlements; the server does not compare a `PlatformAdmin` identifier against any entity's `id`.
- When `X-User-Role` is `Farm`, `X-User-ID` is the `id` of the acting `Farm`. Ownership checks on any resource that references a farm compare against this value: a `Product`'s `farm_id`, and — transitively — an `Offering`'s product's `farm_id` and an `OrderLine`'s offering's product's `farm_id`. A farm may only write its own catalog, offer its own products, and pack lines drawn from its own offerings.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks compare this value against an `Order`'s `customer_id` and a `Subscription`'s `customer_id`. When a customer creates an order, the order's `customer_id` is taken from `X-User-ID` rather than from the request body.

When an entity-backed actor (a `Farm` or a `Customer`) is authenticated and authorized for the endpoint but is not the owner of the specific targeted resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. Ownership enforcement applies to writes (create/mutate/cancel/pack/transition operations) and to the `GET /customers/{id}` self-read; read-only GETs of an order, order line, subscription, or their list endpoints — as well as `GET /offerings/{id}`, `GET /offerings`, `GET /farms/{id}`, `GET /farms/{id}/products`, `GET /pickup-hubs/{id}`, `GET /market-cycles/{id}`, `GET /settlements/{id}`, and `GET /settlements` — are gated only by role authorization and do not additionally check that the acting `Farm` or `Customer` owns the resource.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with the literal prefix `req_` followed by 20 random alphanumeric characters (mixed-case ASCII letters and digits).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside the inclusive range of 1 through 100, or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix (a version-4 UUID in canonical 8-4-4-4-12 hex form).
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by 1 on every mutation. It is the basis for optimistic concurrency control described in §2.9.

`Farm`, `Product`, `MarketCycle`, `Offering`, `PickupHub`, `Customer`, `Subscription`, `Order`, and `OrderLine` all carry the full set above. The one exception is `VendorSettlement`: a settlement is immutable once written, so it carries only `id` and `created_at`. It has no `updated_at` and no `version` field.

Whenever the server updates a resource — including recomputing derived fields such as an offering's `remaining_qty`, an order's `customer_owed_cents`, or a farm's `payout_balance_cents` — that update is a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary Values, Weights, and Rounding

All monetary amounts are integer counts of whole cents; there are no fractional-cent values stored or returned. Where a calculation multiplies a quantity or a weight by a per-unit or per-kilogram rate and the intermediate result is not a whole number of cents, the result is rounded using the **round half up** convention to the nearest whole cent. Rounding is applied once, at the point each rule specifies — for a weight-priced line, exactly once after multiplying weight by rate; for commission, once per line before the per-line amounts are summed (see §3.9). Amounts that are already integer cents — sums of already-rounded line values, benefit applications, and refunds — are computed in whole cents and require no rounding.

Weights are expressed in kilograms and may be fractional. Quantities of whole units (offered, requested, allocated, fulfilled) are integers.

### 2.6. Availability Accounting and Quantity Conservation

Every `Offering` tracks three derived quantities against its `offered_qty`. The `reserved_qty` is the sum of `requested_qty` across the offering's order lines whose `line_status` is either `REQUESTED` or `ALLOCATED` — units that are spoken for but not yet physically committed. The `committed_qty` is the sum of `fulfilled_qty` across the offering's order lines whose `line_status` is `PACKED`, `SUBSTITUTED`, or `FULFILLED` — units that have been physically packed against the offering. The `remaining_qty` is `offered_qty` minus `reserved_qty` minus `committed_qty`.

These three figures are recomputed whenever a line is added, cancelled, allocated, packed, or substituted. The platform holds a conservation invariant at all times: an offering's `offered_qty` always equals the sum of its `remaining_qty`, `reserved_qty`, and `committed_qty`. `remaining_qty` is never persisted as a negative number; any request that would drive it below zero is rejected before it is written (see the availability rule in §2.10 and §3.5).

### 2.7. Cascading State Reconciliation and Parent–Child Consistency

Several operations mutate more than one resource in a single request, and the platform is responsible for propagating every consequence rather than leaving dependents stale. When a market cycle reaches its cutoff, it drives its placed orders and their lines forward together. When an order is cancelled, the cancellation cascades to its lines, and each cancelled line in turn releases its reserved units back to the offering. When a line is packed short or substituted cheaper, the shortfall cascades into a refund record on the order, and the refund record cascades again into adjustments of the customer's balances. Each of these secondary and tertiary effects is a first-class mutation: it refreshes `updated_at` and increments `version` on every resource it touches, exactly as described in §2.4. The detailed cascades are specified alongside their workflows in §3.

### 2.8. Retrieval, Path Validation, and Reverse-Reachability Filters

For any endpoint whose path names a resource, the server validates the existence of each path segment from left to right and rejects the first missing identifier with `ERR_NOT_FOUND`. For endpoints that additionally reference resources by identifiers in the request body — `product_id`, `offering_id`, `market_cycle_id`, `pickup_hub_id`, and `substitute_offering_id` — the referenced target must exist or the request is likewise rejected with `ERR_NOT_FOUND`.

Collection endpoints support filtering so that related resources can be reached from their parents. A farm's products can be listed under the farm. Offerings can be filtered by `product_id`, `market_cycle_id`, or `farm_id`. Subscriptions can be filtered by `customer_id` or `pickup_hub_id`. Orders can be filtered by `customer_id`, `market_cycle_id`, `pickup_hub_id`, `subscription_id`, or `order_status`. Order lines can be filtered by `order_id`, `offering_id`, `substitute_offering_id`, or `line_status`. Settlements can be filtered by `farm_id` or `market_cycle_id`. All filtered lists honor the `limit` and `offset` pagination parameters of §2.3.

### 2.9. Optimistic Concurrency Control on Settlements

Creating a `VendorSettlement` for a farm requires optimistic concurrency control keyed on the farm's `version`. The settlement-create request must carry `expected_farm_version`, a non-optional field holding the `version` of the target `Farm` that the client last observed. Finalizing a settlement posts `net_payout_cents` into the farm's `payout_balance_cents` and therefore advances the farm's `version`; if a client's `expected_farm_version` no longer equals the farm's current `version`, the client is working from a payout-balance view taken before some earlier settlement posted. Such a request is rejected with `ERR_STALE_FARM_VERSION` (HTTP 412) to prevent double-posting a payout onto a stale balance. This is the only endpoint that takes a version field; no other operation accepts or checks a client-supplied version.

### 2.10. Request Validation Order and Precedence

When several checks could fail on a single request, the server evaluates them in a fixed priority order and returns the error for the first failing check. Lower-numbered checks are evaluated first:

1. **Authentication** — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted for the endpoint, else `ERR_UNAUTHORIZED`.
3. **Path existence** — every path-referenced resource exists, validated left to right, else `ERR_NOT_FOUND`.
4. **Body reference existence** — every body-referenced foreign key target exists, else `ERR_NOT_FOUND`.
5. **Ownership** — an entity-backed actor owns the targeted resource (a customer owns the order or subscription; a farm owns the product or offering being written), else `ERR_NOT_RESOURCE_OWNER`.
6. **Well-formedness** — pagination parameters are valid (`ERR_INVALID_PAGINATION`) and the request body is well-formed (`ERR_INVALID_REQUEST`): required fields present, enums valid, quantities at least 1, `commission_pct` within the inclusive range 0 through 1, delivery slots present with end after start for delivery orders, weight-priced products carrying `price_per_kg_cents` and `estimated_weight_kg`, and fixed-price products carrying `unit_price_cents`.
7. **Parent-order posture for packout** — when packing a line, the parent order must be in `ALLOCATED`, checked *before* the line's own state; a line whose parent order is not `ALLOCATED` yields `ERR_ORDER_NOT_ALLOCATED`. Because this precedes the generic state check below, packing a line while its order is still `PLACED` (before cutoff) surfaces `ERR_ORDER_NOT_ALLOCATED`, whereas re-packing an already-packed line while the order is `ALLOCATED` falls through to the generic state check and surfaces `ERR_INVALID_STATE`.
8. **Cycle-open posture** — creating an order, adding a line, or checking out requires the market cycle to be `OPEN`, else `ERR_CYCLE_NOT_OPEN`.
9. **Target state** — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE`; the state-specific variants at this same tier are `ERR_EMPTY_ORDER` (checkout of a zero-line order), `ERR_LINES_NOT_PACKED` (fulfill while some line is not yet packed/substituted/shorted), `ERR_ORDER_IN_PACKOUT` (cancel of an allocated order that already has packed work), and `ERR_CYCLE_HAS_OPEN_ORDERS` (settle while some order is neither fulfilled nor cancelled).
10. **Business-referential** — `ERR_PRODUCT_FARM_MISMATCH` (offering a product the acting farm does not own), `ERR_OFFERING_CYCLE_MISMATCH` (substituting across cycles), and `ERR_NOT_LINE_OWNER` (packing a line whose farm the actor does not own).
11. **SNAP authorization** — a SNAP-eligible product may only be created or offered under a SNAP-authorized farm, else `ERR_FARM_NOT_SNAP_AUTHORIZED`.
12. **Cycle window** — a new cycle must not conflict with an existing same-region window, else `ERR_CYCLE_WINDOW_CONFLICT`.
13. **Capacity and measurement** — `ERR_SLOT_CAPACITY_EXCEEDED` (delivery slot overbooking), `ERR_OVER_PACK` (packing more than allocated), and `ERR_INVALID_WEIGHT` (weight-priced pack with a missing or non-positive actual weight).
14. **Availability and concurrency** — `ERR_INSUFFICIENT_AVAILABILITY` (requested units exceed remaining) and `ERR_STALE_FARM_VERSION` (settlement OCC mismatch).

The platform also maintains a logical clock used for all time comparisons (window buffers, delivery slots). An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; on server startup, and before any such call, the clock reads exactly `2026-03-01T00:00:00Z` and never the wall clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding Farms and Catalog Products

A `PlatformAdmin` onboards a vendor by creating a `Farm` with a display `name`, a `region_code` that scopes which market cycles it can participate in, a `commission_pct`, and an optional `snap_authorized` flag that defaults to false. The `commission_pct` is the fraction of gross sales the platform withholds at settlement and must lie within the inclusive range from 0 to 1. A new farm starts with `payout_balance_cents` and `settled_cycle_count` both at 0; `payout_balance_cents` is the running sum of `net_payout_cents` from the farm's finalized settlements, and `settled_cycle_count` counts those finalized settlements.

Catalog products are created under a farm, either by the owning `Farm` or by a `PlatformAdmin`. Each `Product` carries the owning `farm_id`, a display `name`, a `category` (one of `PRODUCE`, `DAIRY`, `MEAT`, `PANTRY`, or `OTHER`), and a `pricing_mode`. When `pricing_mode` is `FIXED`, the product is priced per whole unit and must supply `unit_price_cents` (its `price_per_kg_cents` and `estimated_weight_kg` remain null). When `pricing_mode` is `WEIGHT`, the product is priced per kilogram with a variable actual weight and must supply both `price_per_kg_cents` and `estimated_weight_kg`, the latter being the assumed weight of one ordered unit used for estimated pricing; its `unit_price_cents` remains null. A malformed combination — a fixed product missing its unit price, or a weight product missing either weight field — is rejected with `ERR_INVALID_REQUEST`.

A product may be marked `snap_eligible`, defaulting to false, meaning it qualifies for SNAP payment and Double-Up matching. A SNAP-eligible product may only be created under a farm whose `snap_authorized` is true; attempting to create a SNAP-eligible product under a farm that is not SNAP-authorized is rejected with `ERR_FARM_NOT_SNAP_AUTHORIZED`.

### 3.2. Market Cycles: Windows and Lifecycle

A `MarketCycle` is the finite ordering window that all supply and demand hang from. A `PlatformAdmin` creates a cycle with a human-readable `cycle_code`, a `region_code` it serves, and three instants: `order_open_at` (when ordering opens), `order_cutoff_at` (when ordering closes and allocation runs), and `fulfillment_date` (when orders are fulfilled). The instants must strictly increase — `order_cutoff_at` after `order_open_at`, and `fulfillment_date` after `order_cutoff_at` — or the request is rejected with `ERR_INVALID_REQUEST`. To keep a region from running overlapping cycles, a new cycle is rejected with `ERR_CYCLE_WINDOW_CONFLICT` when another cycle in the same `region_code` has a `[order_open_at, fulfillment_date]` window that falls within 24 hours of the new cycle's window; both windows are treated as closed intervals and the 24-hour buffer separates them, so two same-region windows conflict whenever the gap between them is less than 24 hours.

A cycle's `status` begins at `SCHEDULED`. A `PlatformAdmin` drives it through a strictly linear posture: opening it advances `SCHEDULED → OPEN`, running the cutoff advances `OPEN → CUTOFF`, and settling advances `CUTOFF → SETTLED`, which is terminal. Each transition requires the cycle to currently hold the expected predecessor state; an out-of-order attempt is rejected with `ERR_INVALID_STATE`.

Opening a cycle enables ordering and also generates subscription boxes. For every `Subscription` in `ACTIVE` status whose pickup hub's `region_code` matches the cycle's `region_code`, the system generates one box order for that subscription, as detailed in §3.4. Eligible subscriptions are visited in ascending `created_at` order, and the box orders inherit their `customer_id` from the owning subscription; a generated box's `order_status` begins at `CART` and its `payment_status` at `UNPAID` — the platform does not auto-checkout the box, so the owning customer must check it out (or cancel it) before the cycle can eventually settle.

Running the cutoff closes ordering: every order in the cycle that is `PLACED` advances to `ALLOCATED`, and each such order's lines advance from `REQUESTED` to `ALLOCATED` with `allocated_qty` set equal to `requested_qty`. Allocation does not change any offering's `reserved_qty` — allocated units are still counted as reserved, not committed. After cutoff, attempts to create an order, add a line, or check out in that cycle are rejected with `ERR_CYCLE_NOT_OPEN`.

Settling a cycle is permitted only from `CUTOFF`, and only once every order in the cycle has reached `FULFILLED` or `CANCELLED`; if any order is still open, settlement is rejected with `ERR_CYCLE_HAS_OPEN_ORDERS`. Reaching `SETTLED` enables per-farm settlement creation for the cycle (see §3.9).

### 3.3. Offerings: Publishing Availability for a Cycle

Supply for a cycle is published as `Offering` records. A `Farm` (or a `PlatformAdmin`) makes one of its products available in a specific cycle by supplying the `product_id` and the whole-unit `offered_qty`, which must be at least 1. The offering may optionally override pricing for the cycle: `unit_price_cents` overrides the fixed per-unit price and `price_per_kg_cents` overrides the per-kilogram price. When an override is null, pricing resolves to the underlying product's corresponding price. A new offering starts with `reserved_qty` and `committed_qty` at 0 and `remaining_qty` equal to `offered_qty`.

The product being offered must belong to the acting farm: if the product's `farm_id` is not the acting farm, the request is rejected with `ERR_PRODUCT_FARM_MISMATCH`. And because an offering exposes a product to buyers, the SNAP rule from §3.1 applies here as well — offering a `snap_eligible` product under a farm whose `snap_authorized` is false is rejected with `ERR_FARM_NOT_SNAP_AUTHORIZED`. An offering names both the `product_id` it publishes and the `market_cycle_id` it belongs to, and it exposes its live `reserved_qty`, `committed_qty`, and `remaining_qty` per the accounting in §2.6.

### 3.4. Hubs, Customers, and Subscriptions

Fulfillment locations are `PickupHub` records, created by a `PlatformAdmin` with a `name`, a `hub_type` (`PICKUP` for customer collection or `DELIVERY` for time-slotted delivery), a `slot_capacity` of at least 1, and a `region_code`. For a delivery hub, `slot_capacity` is the maximum number of delivery orders whose time windows may overlap at once, enforced at checkout in §3.6.

Customers are created by a `PlatformAdmin` with a `name` and an optional starting `snap_balance_cents` (defaulting to 0). A `Customer` also carries two derived balances, both starting at 0: `wallet_credit_cents`, store credit accrued from refunds, and `doubleup_used_cents`, the cumulative Double-Up match the customer has consumed. A customer's own record — exposing `snap_balance_cents`, `wallet_credit_cents`, and `doubleup_used_cents` — is readable by that customer and by an admin.

A `Customer` (or a `PlatformAdmin` acting for them) creates a box `Subscription` under the customer. The subscription records the owning `customer_id` taken from the path, the `pickup_hub_id` the generated boxes route to, a `box_size` (`SMALL`, `MEDIUM`, or `LARGE`), a `cadence` (`WEEKLY` or `BIWEEKLY`), and a `price_cap_cents` of at least 1 that caps each generated box's value. A subscription's `status` starts `ACTIVE` and moves cyclically: pausing advances `ACTIVE → PAUSED`, resuming advances `PAUSED → ACTIVE`, and cancelling advances either `ACTIVE → CANCELLED` or `PAUSED → CANCELLED`, which is terminal. Each transition requires the acting customer to own the subscription and the subscription to hold the expected predecessor state, else `ERR_INVALID_STATE`. No boxes are generated while a subscription is `PAUSED`; box generation resumes at the next cycle open after it returns to `ACTIVE`.

When a cycle opens (see §3.2), each `ACTIVE` subscription in the cycle's region generates one `CART` order routed to the subscription's pickup hub as a `PICKUP` order, with the order's `subscription_id` set to that subscription. The generated box targets a value equal to the smaller of the size-based target and the subscription's `price_cap_cents`. The size-based targets are 1500 cents for `SMALL`, 3000 cents for `MEDIUM`, and 6000 cents for `LARGE`. To fill the box, the system considers this cycle's offerings whose product `category` is `PRODUCE`, taken in ascending `created_at` order (this timestamp is the sole, deterministic ordering key; the offering `id` is never used to break ties). Offerings are added one at a time, each contributing a single unit (`requested_qty` of 1), and the system stops before adding an offering whose one-unit estimated line price would push the cumulative box value above the target — iteration halts as a whole at that first over-target offering; the system does not skip past it to try smaller subsequent offerings. In other words, an offering is added only while the running total plus that offering's single-unit estimated price stays at or below the target.

### 3.5. Assembling an Order: Cart and Line Items

A `Customer` opens an order in a currently `OPEN` cycle, supplying the `market_cycle_id`, the `pickup_hub_id`, and a `fulfillment_type` of either `PICKUP` or `DELIVERY`. The order's `customer_id` is taken from `X-User-ID`, its `subscription_id` is null for a directly created order, its `order_status` starts at `CART`, and its `payment_status` starts at `UNPAID`. Creating an order while the cycle is not `OPEN` is rejected with `ERR_CYCLE_NOT_OPEN`. Delivery-specific fields are covered in §3.6.

While the order is in `CART`, the customer adds line items, each naming the `offering_id` and a `requested_qty` of at least 1. Adding a line requires the cycle to still be `OPEN`, else `ERR_CYCLE_NOT_OPEN`. The requested units may not exceed the offering's current `remaining_qty`; a request that would oversell the offering is rejected with `ERR_INSUFFICIENT_AVAILABILITY`. When the line is accepted it starts in `line_status` `REQUESTED`, its `snap_eligible` flag is copied from the offering's product `snap_eligible`, its offering's `reserved_qty` grows by the requested units (and `remaining_qty` is recomputed), and its `estimated_line_cents` is computed by the estimated pricing rule below. A line also exposes `allocated_qty`, `fulfilled_qty`, `actual_weight_kg`, `final_line_cents`, `substitute_offering_id`, and `price_delta_cents`, all of which are null or zero until later stages populate them.

**Estimated line pricing.** Pricing first resolves the effective rates: the effective per-unit price is the offering's `unit_price_cents` when it is not null, otherwise the product's `unit_price_cents`; the effective per-kilogram price is the offering's `price_per_kg_cents` when it is not null, otherwise the product's `price_per_kg_cents`. For a `FIXED` product, `estimated_line_cents` is the `requested_qty` multiplied by the effective per-unit price. For a `WEIGHT` product, `estimated_line_cents` is the `requested_qty` multiplied by the product's `estimated_weight_kg` and by the effective per-kilogram price, rounded half up to whole cents. The rounding for a weight line is applied exactly once, after that product.

### 3.6. Checkout: Delivery Slots, SNAP, and Double-Up

Checking out moves an order from `CART` to `PLACED` and, in parallel, its payment from `UNPAID` to `AUTHORIZED`. The acting customer must own the order, the order must currently be in `CART`, and the cycle must be `OPEN` (else `ERR_CYCLE_NOT_OPEN`). An order with no lines cannot be checked out and is rejected with `ERR_EMPTY_ORDER`.

**Delivery slots.** When the order's `fulfillment_type` is `DELIVERY`, the order must carry a `delivery_slot_start` and a `delivery_slot_end`, with the end strictly after the start; a missing or backwards slot is an `ERR_INVALID_REQUEST` on the order. At checkout, the platform enforces the hub's capacity: treating each active delivery order's `[delivery_slot_start, delivery_slot_end)` as a half-open interval on the target hub, adding this order must keep the number of mutually overlapping intervals at or below the hub's `slot_capacity`. "Active delivery order" here means any delivery order on the same hub whose `order_status` is `PLACED`, `ALLOCATED`, or `FULFILLED`, drawn across all cycles (the hub scope, not the cycle scope); `CART`, `CANCELLED`, and non-delivery orders are excluded. Intervals that merely touch — where one's end equals another's start — do not count as overlapping. If admitting the order would push the overlap count above `slot_capacity`, checkout is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`.

**Applying benefits.** Checkout computes and freezes the order's benefit figures in a fixed evaluation order: subtotal, then eligible subtotal, then SNAP applied, then Double-Up match, then the customer's out-of-pocket. Concretely:

- `subtotal_cents` is the sum of `estimated_line_cents` over all of the order's lines.
- `eligible_subtotal_cents` is the sum of `estimated_line_cents` over only those lines whose `snap_eligible` is true.
- `snap_applied_cents` is the smaller of the customer's `snap_balance_cents` and `eligible_subtotal_cents`.
- `doubleup_match_cents` is the smaller of `snap_applied_cents` and the customer's remaining Double-Up headroom, where headroom is the Double-Up cap of 2000 cents ($20) minus the customer's current `doubleup_used_cents`, and headroom is never treated as less than zero.
- `customer_owed_cents` is the subtotal minus `snap_applied_cents` minus `doubleup_match_cents`, but never less than zero.

All of these are whole-cent figures and involve no rounding. As side effects of checkout, the customer's `snap_balance_cents` is reduced by `snap_applied_cents` and their `doubleup_used_cents` is increased by `doubleup_match_cents`. The `snap_applied_cents` and `doubleup_match_cents` values are frozen on the order at these checkout amounts and are not recomputed later; only the subtotal side is refreshed at fulfillment (see §3.7).

### 3.7. Packout: Packing, Shorting, and Substituting Lines

After cutoff, a cycle's orders are `ALLOCATED` and their lines await packout. A `Farm` (or a `PlatformAdmin`) packs each line by recording what was actually assembled. Every pack requires the parent order to be `ALLOCATED` — checked first, so a pack attempted while the order is still `PLACED` yields `ERR_ORDER_NOT_ALLOCATED` — and requires the acting farm to own the line's offering's product (`ERR_NOT_LINE_OWNER`). A line already in a packout state re-packed while its order is `ALLOCATED` instead trips the generic state check with `ERR_INVALID_STATE`. Packout has three outcomes, all starting from `ALLOCATED`:

**Full pack (`ALLOCATED → PACKED`).** The packer records a `fulfilled_qty` equal to `allocated_qty` (and at least 1) and provides no substitute. For a weight-priced line, `actual_weight_kg` must be present and greater than zero, else `ERR_INVALID_WEIGHT`. A `fulfilled_qty` greater than `allocated_qty` is rejected with `ERR_OVER_PACK`. The final price is computed by the final pricing rule below, `price_delta_cents` is set to `final_line_cents` minus `estimated_line_cents`, the offering's `reserved_qty` decreases by the line's `requested_qty` while its `committed_qty` increases by `fulfilled_qty`. If `price_delta_cents` is negative (the goods came in cheaper), a partial refund is issued per §3.8; unlike the SHORTED and SUBSTITUTED branches, the order's `payment_status` is NOT flipped to `PARTIALLY_REFUNDED` for a full-pack cheaper case — the customer's balances and the order's `refunded_snap_cents`/`refunded_wallet_cents` still receive the refund waterfall's allocation, but `payment_status` stays at its checkout value (`AUTHORIZED`) until fulfillment advances it to `CAPTURED`. If `price_delta_cents` is positive (heavier actual weight), no immediate refund occurs; the additional amount owed is folded into `customer_owed_cents` when the order is fulfilled and its final benefit figures are recomputed.

**Short pack (`ALLOCATED → SHORTED`).** The packer records a `fulfilled_qty` that is at least 0 and strictly less than `allocated_qty`. The `ERR_INVALID_WEIGHT` requirement for a weight-priced line applies only when the recorded `fulfilled_qty` is at least 1; a fully shorted weight line (`fulfilled_qty` of 0) is accepted without any `actual_weight_kg`, and its `final_line_cents` is 0. When `fulfilled_qty` is at least 1 on a weight-priced short, the weight rule applies and `actual_weight_kg` must be present and greater than zero, else `ERR_INVALID_WEIGHT`. The final price is computed over the actually fulfilled quantity (or actual weight), `price_delta_cents` becomes `final_line_cents` minus `estimated_line_cents` and is negative, the offering's `reserved_qty` decreases by `requested_qty` and its `committed_qty` increases by `fulfilled_qty`. The shortfall — the estimated line value minus the final line value — becomes a refund credit: the order's `refunded_snap_cents` and `refunded_wallet_cents` are updated per the refund waterfall in §3.8, the order's `payment_status` moves to `PARTIALLY_REFUNDED` (only when the shortfall credit is strictly positive; a zero-credit short leaves `payment_status` unchanged), and the customer's `snap_balance_cents`, `doubleup_used_cents`, and `wallet_credit_cents` are adjusted accordingly.

**Substitution (`ALLOCATED → SUBSTITUTED`).** The packer provides a `substitute_offering_id` and a `substitute_qty` of at least 1, replacing the ordered item with another offering. The acting farm must own both the original line's product farm and the substitute offering's product farm (`ERR_NOT_LINE_OWNER`), the substitute offering must belong to the same `market_cycle_id` as the original line's offering (`ERR_OFFERING_CYCLE_MISMATCH`), and the substitute offering must have `remaining_qty` at least `substitute_qty` (`ERR_INSUFFICIENT_AVAILABILITY`). When the substitute offering's product is `WEIGHT`-priced (and `substitute_qty` is at least 1), the packer must also supply an `actual_weight_kg` greater than zero, else `ERR_INVALID_WEIGHT`; for a `FIXED`-priced substitute, `actual_weight_kg` is not required. On success, the line's `substitute_offering_id` is set, its `fulfilled_qty` is set to `substitute_qty`, its `actual_weight_kg` is set to the supplied weight (or left null for a fixed substitute), `final_line_cents` is computed from the substitute offering's resolved price and `substitute_qty` (or actual weight for a weight-priced substitute), and `price_delta_cents` is `final_line_cents` minus `estimated_line_cents`. The line's `snap_eligible` flag is not recomputed from the substitute product; it retains the value copied at line-add time from the original offering's product, so a swap between differing eligibilities does not alter benefit or refund routing for this line. The original offering's `reserved_qty` decreases by the line's `requested_qty` and the substitute offering's `committed_qty` increases by `substitute_qty`. If `price_delta_cents` is negative, a partial refund is issued per §3.8, the order's `payment_status` moves to `PARTIALLY_REFUNDED`, and the customer is credited. If `price_delta_cents` is zero or positive, `payment_status` is not changed and no refund is issued; a positive delta on a substitution is folded into `customer_owed_cents` at fulfillment just as it is for a heavier full pack.

**Final line pricing.** Using the same effective-rate resolution as §3.5 (offering override when present, else product base), the final price is computed at packout from what was measured. For a `FIXED` line, `final_line_cents` is `fulfilled_qty` multiplied by the effective per-unit price. For a `WEIGHT` line, `final_line_cents` is the recorded total `actual_weight_kg` multiplied by the effective per-kilogram price, rounded half up to whole cents once. For a substitution, the final price uses the substitute offering's resolved price with `substitute_qty` (fixed) or the measured weight (weight). Note that even when requested and fulfilled unit counts match, a weight line's final value can differ from its estimate because the measured weight differs from the product's `estimated_weight_kg`.

### 3.8. Fulfillment, Cancellation, and the Refund Waterfall

**Fulfillment.** Once every line of an `ALLOCATED` order is in a terminal packout state — `PACKED`, `SUBSTITUTED`, or `SHORTED` — a `Farm` or `PlatformAdmin` fulfills the order, advancing it `ALLOCATED → FULFILLED` and moving each of those lines to `FULFILLED`; a shorted line carries its (possibly zero) `fulfilled_qty` forward. Attempting to fulfill while some line is not yet packed is rejected with `ERR_LINES_NOT_PACKED`. At fulfillment the order's `final_total_cents` is set to the sum of its lines' `final_line_cents`, and `customer_owed_cents` is recomputed in the final variant of the benefit rule: the frozen `snap_applied_cents` and `doubleup_match_cents` are left untouched, only the gross is refreshed to `final_total_cents`, so `customer_owed_cents` becomes `final_total_cents` minus the frozen SNAP minus the frozen Double-Up, never less than zero. In parallel, `payment_status` advances `AUTHORIZED → CAPTURED`.

**Cancellation.** A `Customer` or `PlatformAdmin` may cancel an order while it is in `CART`, `PLACED`, or `ALLOCATED`. Cancelling an order that is still in `CART` simply closes it; because no benefits were ever applied, there is no refund. Cancelling a `PLACED` or `ALLOCATED` order runs a full cascade: every non-terminal line moves to `CANCELLED`, and each such cancellation releases the line's `requested_qty` back to its offering's `reserved_qty` (with `remaining_qty` recomputed). A full refund is then issued — the order's frozen `snap_applied_cents` is returned to the customer's `snap_balance_cents` and recorded in the order's `refunded_snap_cents`; the `doubleup_match_cents` is reversed out of the customer's `doubleup_used_cents`; and the order's `customer_owed_cents` is credited to the customer's `wallet_credit_cents` and recorded in the order's `refunded_wallet_cents`. The order's `payment_status` moves to `REFUNDED`. An allocated order cannot be cancelled once any of its lines is already `PACKED`, `SUBSTITUTED`, `SHORTED`, or `FULFILLED`; such a request is rejected with `ERR_ORDER_IN_PACKOUT`.

**The refund waterfall.** Every partial refund (from a short, a cheaper full pack, or a cheaper substitution) and the per-line portion of a cancel refund allocates its credit across three buckets in a pinned order — SNAP first, then Double-Up reversal, then wallet credit. A refund with a non-positive credit (zero or negative) is a no-op: no balances move, no order counters change, and no state transition (such as flipping `payment_status` to `PARTIALLY_REFUNDED`) is triggered. For a given credit amount on a line: the remaining refundable SNAP on the order is its frozen `snap_applied_cents` minus its already-recorded `refunded_snap_cents`, and the remaining refundable Double-Up is its frozen `doubleup_match_cents` minus what has already been reversed for this order. If the line is `snap_eligible`, the refund to SNAP is the smaller of the credit and the remaining refundable SNAP; the refund to Double-Up is the smaller of the still-unallocated credit and the remaining refundable Double-Up; and whatever credit remains after those two becomes wallet credit. If the line is not `snap_eligible`, the entire credit becomes wallet credit and nothing is returned to SNAP or Double-Up. The credited amounts then flow to the customer and the order: `snap_balance_cents` increases by the SNAP portion, `doubleup_used_cents` decreases by the Double-Up portion (reversing the earlier match), `wallet_credit_cents` increases by the wallet portion, the order's `refunded_snap_cents` increases by the SNAP portion, and the order's `refunded_wallet_cents` increases by the wallet portion. When multiple lines refund, they draw from these shared remaining counters in line-creation order (ascending `created_at`), which keeps the outcome independent of processing order. As a conservation guarantee, a checkout followed by a full refund returns the customer's `snap_balance_cents` to its exact pre-checkout value.

### 3.9. Vendor Settlement and Payout

Once a cycle is `SETTLED`, a `PlatformAdmin` finalizes each participating farm's payout by creating a `VendorSettlement`, supplying the settled `market_cycle_id` and the `expected_farm_version` required by the concurrency rule in §2.9. The settlement's candidate lines are the order lines in that cycle drawn from offerings whose product belongs to this farm; the final settlement counts only those lines that reached `FULFILLED`, valued by their `final_line_cents`.

From those fulfilled lines the settlement derives its figures. `gross_sales_cents` is the sum of `final_line_cents` across the farm's fulfilled lines in the cycle. `commission_cents` is computed per line and then summed: for each fulfilled line, multiply its `final_line_cents` by the farm's `commission_pct` and round half up to whole cents, then add those per-line commissions together — this per-line rounding is deliberate and can differ by a cent or more from rounding a single combined product. `net_payout_cents` is `gross_sales_cents` minus `commission_cents`. `snap_reimbursable_cents` is the portion of the gross funded by SNAP and Double-Up dollars attributable to this farm's fulfilled `snap_eligible` lines, which the program reimburses to the farm; it is computed per order by first forming that order's net SNAP+Double-Up pool as `(snap_applied_cents − refunded_snap_cents) + (doubleup_match_cents − amount already reversed out of `doubleup_used_cents` for this order)` (each of the two terms clamped at zero), then walking that order's FULFILLED `snap_eligible` lines in line-creation (ascending `created_at`) order, capping each line's attribution at its own `final_line_cents` and draining the pool. Only the per-line attributions belonging to this farm's fulfilled `snap_eligible` lines are summed into the settlement's `snap_reimbursable_cents`. `line_count` is the number of fulfilled candidate lines swept into the settlement. (A preview of these figures can be taken provisionally at cutoff over the farm's `ALLOCATED` lines valued by their `estimated_line_cents`; the final settlement differs because actual weights, shorts, and substitutions change both which lines are included and their values.)

Finalizing the settlement posts its `net_payout_cents` into the farm's `payout_balance_cents`, increments the farm's `settled_cycle_count` by 1, and increments the farm's `version` by 1 — which is exactly why a second create carrying a stale `expected_farm_version` is rejected with `ERR_STALE_FARM_VERSION`. The fulfilled lines swept into the settlement are flagged as settled internally, so that a subsequent settlement for the same farm and cycle would not re-count them; this flag is not exposed as part of the OrderLine response. A settlement is immutable once created and, per §2.4, carries only `id` and `created_at` in addition to `farm_id`, `market_cycle_id`, `gross_sales_cents`, `commission_cents`, `snap_reimbursable_cents`, `net_payout_cents`, and `line_count`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a farm, a product, a cycle, an offering, a hub, a customer, a subscription, an order, an order line, or a settlement) return `201 Created`. Operations that modify an existing resource — including all lifecycle transitions such as opening, cutting off, or settling a cycle; checking out, cancelling, or fulfilling an order; packing a line; and pausing, resuming, or cancelling a subscription — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/farms` | Create a farm/vendor | PlatformAdmin |
| GET | `/farms/{id}` | Get a farm (exposes version and payout balance) | PlatformAdmin, Farm, Customer |
| GET | `/farms/{id}/products` | List a farm's catalog products | PlatformAdmin, Farm, Customer |
| POST | `/farms/{id}/products` | Create a catalog product under a farm | PlatformAdmin, Farm |
| POST | `/market-cycles` | Create a market cycle | PlatformAdmin |
| GET | `/market-cycles/{id}` | Get a market cycle | PlatformAdmin, Farm, Customer |
| POST | `/market-cycles/{id}/open` | Open ordering; generate subscription boxes | PlatformAdmin |
| POST | `/market-cycles/{id}/cutoff` | Close ordering and run allocation | PlatformAdmin |
| POST | `/market-cycles/{id}/settle` | Mark cycle settled | PlatformAdmin |
| POST | `/market-cycles/{id}/offerings` | Offer a product with a quantity in this cycle | PlatformAdmin, Farm |
| GET | `/offerings/{id}` | Get an offering | PlatformAdmin, Farm, Customer |
| GET | `/offerings` | List offerings | PlatformAdmin, Farm, Customer |
| POST | `/pickup-hubs` | Create a pickup or delivery hub | PlatformAdmin |
| GET | `/pickup-hubs/{id}` | Get a hub | PlatformAdmin, Farm, Customer |
| POST | `/customers` | Create a customer | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | PlatformAdmin, Customer |
| POST | `/customers/{id}/subscriptions` | Create a box subscription | PlatformAdmin, Customer |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, Customer |
| GET | `/subscriptions` | List subscriptions | PlatformAdmin, Customer |
| POST | `/subscriptions/{id}/pause` | Pause an active subscription | PlatformAdmin, Customer |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | PlatformAdmin, Customer |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | PlatformAdmin, Customer |
| POST | `/orders` | Create a cart order in an open cycle | Customer |
| GET | `/orders/{id}` | Get an order | PlatformAdmin, Customer |
| GET | `/orders` | List orders | PlatformAdmin, Customer |
| POST | `/orders/{id}/lines` | Add a line to a cart order | Customer |
| POST | `/orders/{id}/checkout` | Check out a cart order | Customer |
| POST | `/orders/{id}/cancel` | Cancel an order | Customer, PlatformAdmin |
| POST | `/orders/{id}/fulfill` | Fulfill an allocated, fully packed order | PlatformAdmin, Farm |
| GET | `/order-lines/{id}` | Get an order line | PlatformAdmin, Customer, Farm |
| GET | `/order-lines` | List order lines | PlatformAdmin, Customer, Farm |
| POST | `/order-lines/{id}/pack` | Packout: pack, short, or substitute a line | Farm, PlatformAdmin |
| POST | `/farms/{id}/settlements` | Finalize a farm's settlement for a settled cycle | PlatformAdmin |
| GET | `/settlements/{id}` | Get a settlement | PlatformAdmin, Farm |
| GET | `/settlements` | List settlements | PlatformAdmin, Farm |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_EMPTY_ORDER` | 409 |
| `ERR_ORDER_NOT_ALLOCATED` | 409 |
| `ERR_LINES_NOT_PACKED` | 409 |
| `ERR_ORDER_IN_PACKOUT` | 409 |
| `ERR_CYCLE_HAS_OPEN_ORDERS` | 409 |
| `ERR_PRODUCT_FARM_MISMATCH` | 409 |
| `ERR_OFFERING_CYCLE_MISMATCH` | 409 |
| `ERR_NOT_LINE_OWNER` | 403 |
| `ERR_FARM_NOT_SNAP_AUTHORIZED` | 422 |
| `ERR_CYCLE_WINDOW_CONFLICT` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_OVER_PACK` | 409 |
| `ERR_INVALID_WEIGHT` | 422 |
| `ERR_INSUFFICIENT_AVAILABILITY` | 409 |
| `ERR_STALE_FARM_VERSION` | 412 |
