# Perfume & Fragrance Retail API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Perfume & Fragrance Retail API, a backend platform for a specialty fragrance house that sells full bottles alongside decants, samples, and curated discovery sets. The business spans several intertwined concerns: a searchable scent catalog with a note-based finder, a scent-of-month subscription program, a loyalty and tiering ledger, hygiene-sensitive returns, and time-boxed allocation of exclusive, high-demand releases. Each of these concerns carries its own rules, but they share a common inventory pool and a single customer ledger, so the platform must keep pricing, inventory, loyalty, and fulfillment consistent as events ripple across entities.

Two characteristics shape the design. First, several quantities are conserved: physical inventory moves between an on-hand pool and a reservation pool without being created or destroyed until an order actually ships, and allocation units are drawn down against a fixed release quota. Second, many computations exist in two flavors — a provisional estimate quoted early and a final settled value computed later — for refunds and for subscription charges alike. The specification below is careful to pin the exact evaluation order and rounding behavior of every such computation, because provisional and final values can legitimately differ and both must be reproducible.

The platform serves four operator audiences — shoppers acting on their own accounts, catalog and allocation managers, fulfillment operations staff, and platform administrators — and every mutation is governed by role, resource state, and a strict validation ordering described in Section 2.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, the response envelope, pagination, common resource fields, precision, concurrency, and the cross-cutting invariants that hold across every workflow in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Customer`, `Merchandiser`, `FulfillmentOps`, and `PlatformAdmin`.

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning-customer foreign key to `X-User-ID`. Concretely, a `Customer` may only place, cancel, or return against an `Order` whose `customer_id` equals `X-User-ID`, and may only act on a `ReturnRequest` whose underlying order belongs to them; an ownership violation is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403).
- When `X-User-Role` is `Merchandiser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `Merchandiser` manages the catalog: creating products, variants, and allocation windows.
- When `X-User-Role` is `FulfillmentOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. This role fulfills orders and shipments, generates shipments, and adjudicates returns.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. `PlatformAdmin` is a hierarchical-override superset role: it may perform every operation that a `Merchandiser` or `FulfillmentOps` may perform and every shared operation a `Customer` may perform, and in addition it exclusively registers and suspends customers and controls the logical clock.

Because `Merchandiser`, `FulfillmentOps`, and `PlatformAdmin` identities are opaque, ownership comparisons never apply to them; only the `Customer` role is subject to the owner check above.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation. It is the basis for the optimistic concurrency mechanism in Section 2.6.

Two resources are deliberately append-only records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: the `AllocationClaim` and the `LoyaltyTransaction`. Every other resource — `Customer`, `Product`, `Variant`, `Order`, `OrderLine`, `Subscription`, `Shipment`, `AllocationWindow`, and `ReturnRequest` — carries the full four-field set, and any change to a derived or computed field on such a resource (for example a customer's `tier` or an order's `payment_status`) is a mutation that refreshes `updated_at` and increments `version`.

### 2.5. Monetary and Point Precision

All monetary amounts are stored and returned as integer cents; there are no fractional cents. Loyalty points are integers, and one loyalty point is worth exactly one cent of discount when redeemed. Wherever a computation would otherwise yield a fraction — the volume-tier discount, per-line loyalty earning, and the restock deduction on an opened return — the result is rounded to the nearest integer using the round-half-up convention (a value ending in exactly one-half rounds up). The precise point at which rounding is applied is specified per computation in Section 3, because rounding before versus after summation can change the result, and the platform pins one specific order in each case.

### 2.6. Optimistic Concurrency on Allocation Claims

Claiming units from an allocation window is guarded by optimistic concurrency control. A request that claims allocation against a window must include `expected_window_version`, carrying the client's last observed `version` of the target `AllocationWindow`; this field is required, not optional. If `expected_window_version` does not equal the window's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The rationale is that whenever another claim succeeds against the same window it advances that window's `claimed_units` and bumps its `version`; a mismatch therefore means the claimant's view of remaining allocation is stale and must be refreshed before retrying, preventing a claim built on unobserved state. No other endpoint takes a version field; claim creation is the only optimistically-locked operation in the system.

### 2.7. Existence Checks and Left-to-Right Path Validation

When an endpoint path or request body references resources by id, the server validates their existence before applying any business rule. Path identifiers are checked left to right: for a nested path, the outer resource is validated before the inner one, and the first identifier that does not resolve determines the error. Each entity has its own not-found error and all are HTTP 404: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ALLOCATION_WINDOW_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND`. Body-referenced foreign keys are validated after path identifiers, in the order they appear.

### 2.8. Validation Ordering

Many operations run several checks, and the order in which they fire is fixed so that the same request always produces the same error. The global ordering, highest priority first, is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization, including the customer-ownership check (`ERR_UNAUTHORIZED`, or `ERR_NOT_ORDER_OWNER` for an owner mismatch); (3) existence of every referenced resource (the 404 family in Section 2.7); (4) the target resource being in a valid state for the requested transition (`ERR_INVALID_STATE`, HTTP 409); (5) the hygiene rule on returns (`ERR_HYGIENE_NON_RETURNABLE`); (6) referential business checks — that returned lines belong to the order and are active (`ERR_LINE_NOT_IN_ORDER`), and that an allocation claim targets an exclusive product (`ERR_PRODUCT_NOT_EXCLUSIVE`); (7) temporal checks — window overlap (`ERR_ALLOCATION_WINDOW_OVERLAP`), shipment-period overlap (`ERR_SHIPMENT_PERIOD_OVERLAP`), and claiming only against an open window (`ERR_ALLOCATION_WINDOW_NOT_OPEN`); (8) capacity and constraint checks — suspended customer (`ERR_CUSTOMER_SUSPENDED`), empty order (`ERR_EMPTY_ORDER`), insufficient inventory (`ERR_INSUFFICIENT_STOCK`), exhausted allocation (`ERR_ALLOCATION_EXHAUSTED`), and per-customer allocation limit (`ERR_PER_CUSTOMER_LIMIT`); (9) fiscal checks — insufficient loyalty points (`ERR_INSUFFICIENT_POINTS`) and the stale-version rejection (`ERR_STALE_VERSION`); and finally (10) generic request-body validation of required fields, enums, and types (`ERR_INVALID_REQUEST`, HTTP 400), which applies to every POST. When two checks share a priority tier, either being unsatisfied is a valid rejection; the tiers themselves are the binding order — for instance, a request that both targets a wrong state and would exhaust allocation surfaces the state error first.

### 2.9. Parallel Status Dimensions and Cascading Consistency

An `Order` tracks two independent status dimensions that evolve separately: `fulfillment_status`, which moves through `CART`, `PLACED`, `FULFILLED`, `CANCELLED`, `PARTIALLY_RETURNED`, and `RETURNED`; and `payment_status`, which moves through `UNPAID`, `PAID`, `REFUNDED`, and `PARTIALLY_REFUNDED`. Placing an order advances fulfillment to `PLACED` while independently advancing payment to `PAID`; later events move each dimension on its own schedule as described in Section 3.

Several operations mutate more than one entity in a single atomic step, and every cascade must complete together. Fulfilling an order and fulfilling a shipment both write a loyalty ledger row, adjust the customer's point balance and lifetime spend, and recompute the customer's tier. Approving a return reaches even further: it retires order lines, recomputes the order's two status dimensions, reverses previously earned points, and rolls back lifetime spend and tier. Each affected resource that carries a `version` has it incremented and its `updated_at` refreshed as part of the cascade. These consistency updates are performed by the server automatically as a consequence of the triggering operation; a client never issues a separate request against the cascaded resource.

### 2.10. Inventory Conservation

For each `Variant`, the sum of `on_hand_qty` (units physically available and sellable) and `reserved_qty` (units held for placed-but-unshipped orders) is a conserved quantity: reserving units for a placement moves them from on-hand to reserved without changing the total, and releasing a cancelled placement moves them back. Units only leave this conserved total when an order is fulfilled, at which point the reserved units are committed and depart inventory as sold. A variant's `status` is derived directly from its on-hand count: it is `AVAILABLE` while `on_hand_qty` is greater than zero and `OUT_OF_STOCK` when `on_hand_qty` reaches zero.

### 2.11. The Logical Clock

The platform runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. A `PlatformAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field of the clock-control capability; doing so re-derives every allocation window's clock-driven `status` and governs the effective-date comparison used when charging subscriptions. All temporal comparisons in this specification — window open/closed boundaries, subscription fee effective dates, and certification of "now" — are made against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Catalog: Products, Variants, and the Note Finder

A `Merchandiser` builds the catalog by creating a `Product`, which represents a SKU and is described by a `name`, a `brand` (the fragrance house), a `concentration` that is one of `EDT`, `EDP`, `PARFUM`, or `COLOGNE`, and a merchandising `kind` that is one of `SINGLE`, `BUNDLE`, or `DISCOVERY_SET` and defaults to `SINGLE`. A product carries an embedded `notes` array (defaulting to empty), where each entry is an object with a note `name`, a `family` drawn from `CITRUS`, `FLORAL`, `WOODY`, `ORIENTAL`, `FOUGERE`, and `GOURMAND`, and a `level` of `TOP`, `HEART`, or `BASE`. When the product is a `BUNDLE` or `DISCOVERY_SET`, the `component_variant_ids` array records the variant ids gathered into the set as an informational manifest; it is not treated as a parsed set of foreign keys and defaults to empty.

Two product attributes govern downstream behavior. The `hygiene_returnable` boolean (defaulting to false, the norm for fragrances) determines whether opened units of this product's variants may be returned, as described in Section 3.5. The `is_exclusive` boolean (defaulting to false) marks a product as purchasable only by claiming allocation from an open release window; when a product is exclusive, its `per_customer_limit` caps the cumulative units one customer may claim across all of that product's windows, and a null value means there is no such cumulative cap.

Shoppers and staff discover products through a note-finder listing that filters the catalog by the query parameters `note` (matching an embedded note's name), `family` (matching an embedded note's family), and `kind` (matching the product's merchandising kind); any combination may be supplied, and the standard `limit` and `offset` pagination applies. A product's purchasable forms are its variants: a `Merchandiser` creates a `Variant` under a product, and the variant records its parent `product_id`, a `kind` of `FULL_BOTTLE`, `DECANT`, or `SAMPLE`, its `volume_ml`, a `unit_price_cents` (which must be zero or greater), and a seed `on_hand_qty` (zero or greater). The variant also exposes its live `reserved_qty` and derived `status` as described in Section 2.10.

### 3.2. Building and Placing an Order

A `Customer` opens an order as a cart by supplying their `customer_id`; the new order starts with `fulfillment_status` of `CART` and `payment_status` of `UNPAID`. While the order is a cart, the customer adds lines, each identifying a `variant_id` and a `quantity` of at least one. On line creation the server snapshots the variant's price into the line's `unit_price_cents` and computes `line_total_cents` as that unit price multiplied by the quantity. Each `OrderLine` also carries an `order_id`, a `status` that begins `ACTIVE` (and may later become `RETURNED` or `CANCELLED`), and a `points_earned` field that stays zero until fulfillment.

Placing the order advances `fulfillment_status` from `CART` to `PLACED` and requires several preconditions, checked in the order of Section 2.8. The order must currently be a cart. It must contain at least one `ACTIVE` line, or the placement is rejected with `ERR_EMPTY_ORDER`. The owning customer's account `status` must be `ACTIVE`; a suspended account is rejected with `ERR_CUSTOMER_SUSPENDED`. For every line, the variant's `on_hand_qty` must be at least the line's quantity — availability exactly equal to the quantity is acceptable, one unit short is rejected with `ERR_INSUFFICIENT_STOCK`. If the customer chooses to redeem points, the optional `redeem_points` amount supplied at placement must not exceed the customer's current `loyalty_points_balance`, or the request is rejected with `ERR_INSUFFICIENT_POINTS`.

When placement succeeds, the server prices the order and computes its five monetary fields. The `subtotal_cents` is the sum, over the active lines, of each line's total. A volume-tier discount is then keyed on that subtotal: a subtotal below one hundred dollars (10000 cents) earns no discount; a subtotal from one hundred dollars up to but not including three hundred dollars (at least 10000 cents and below 30000 cents) earns five percent; a subtotal of three hundred dollars (30000 cents) or more earns ten percent. The `discount_cents` is the subtotal multiplied by that rate, rounded half up to whole cents. The net after discount is the subtotal minus the discount. Loyalty redemption is then applied: `loyalty_redeemed_cents` is the smallest of the requested `redeem_points`, the customer's available `loyalty_points_balance`, and that net amount — redemption can never exceed what is owed after discount. The net-after-loyalty amount is the net minus the redeemed cents. Shipping is evaluated on this net-after-loyalty figure, before shipping itself is added: `shipping_fee_cents` is zero when net-after-loyalty is at least seventy-five dollars (7500 cents) and otherwise a flat five dollars and ninety-five cents (595 cents). Finally, `total_cents` — the amount charged — is the net-after-loyalty amount plus the shipping fee.

Placement also has inventory and ledger side effects. For each line the variant's `on_hand_qty` is decreased by the line quantity and its `reserved_qty` increased by the same amount, reserving the goods while conserving the on-hand-plus-reserved total. The order's `payment_status` is set to `PAID`. If any points were redeemed, the server writes a `LoyaltyTransaction` with `reason` `REDEEM` and a `points_delta` equal to the negative of the redeemed cents, and decreases the customer's `loyalty_points_balance` by that many points.

### 3.3. Fulfillment, Loyalty Earning, and Tiering

Fulfilling a placed order — a `FulfillmentOps` or `PlatformAdmin` action — advances `fulfillment_status` from `PLACED` to `FULFILLED` and requires only that the order currently be `PLACED`. On fulfillment the reserved units are committed: each active line's quantity is subtracted from the variant's `reserved_qty`, and those units leave inventory permanently as sold.

Fulfillment is where loyalty is earned. The customer's tier sets a multiplier: `BRONZE` earns at one times, `SILVER` at one-and-a-quarter times, and `GOLD` at one-and-a-half times. Points are computed per line and then summed — the order is pinned: for each active line, the server takes the line's total in cents, divides by one hundred to convert to dollars, multiplies by the tier multiplier, and rounds half up to a whole number of points; that per-line result is stored on the line's `points_earned`. The order's earned points are the sum of these already-rounded per-line values (rounding each line before summing, not rounding once after summing, so that per-line remainders are preserved). The server then writes a `LoyaltyTransaction` with `reason` `EARN` and a `points_delta` equal to the summed points, and increases the customer's `loyalty_points_balance` by that sum.

Fulfillment also drives tiering. The customer's `lifetime_spend_cents` is increased by the order's net-after-loyalty amount (its subtotal minus discount minus redeemed loyalty), and the customer's `tier` is then recomputed from the new lifetime spend: a lifetime spend of two thousand dollars (200000 cents) or more is `GOLD`; a lifetime spend of five hundred dollars (50000 cents) or more but below the gold threshold is `SILVER`; anything below five hundred dollars is `BRONZE`. These boundaries are inclusive at the stated amount.

### 3.4. Order Cancellation

A cart order may be cancelled by its owning `Customer` (or by fulfillment staff), moving `fulfillment_status` from `CART` to `CANCELLED` with no inventory or ledger effect, since a cart never reserved anything. Cancelling a placed order is a depth-two cascade: it is permitted only while the order is `PLACED`, and it releases what placement reserved. Each active line's `status` becomes `CANCELLED`, and that line-cancellation returns its units to inventory — the variant's `reserved_qty` is decreased by the line quantity and its `on_hand_qty` increased by the same amount, again conserving the total. The order's `payment_status` is set to `REFUNDED`. If the placement had redeemed loyalty (its `loyalty_redeemed_cents` was greater than zero), the server writes a compensating `LoyaltyTransaction` with `reason` `REVERSAL` and restores the customer's `loyalty_points_balance` by the previously redeemed amount. Note that lifetime spend and tier were never touched at placement, so cancellation does not adjust them.

### 3.5. Returns and the Hygiene Rule

Only a fulfilled order may be returned. A `Customer` requests a return by naming the `order_id`, the `line_ids` being returned, and the reported `condition`, which is either `SEALED` or `OPENED`. The request is admitted only if the order's `fulfillment_status` is `FULFILLED` or `PARTIALLY_RETURNED`, otherwise it is rejected with `ERR_ORDER_NOT_FULFILLED` (HTTP 409). Every id in `line_ids` must belong to the named order and must currently be an `ACTIVE` line, or the request is rejected with `ERR_LINE_NOT_IN_ORDER`. The hygiene rule then applies: if the reported condition is `OPENED`, every returned line's variant must belong to a product whose `hygiene_returnable` is true; if any does not, the request is rejected with `ERR_HYGIENE_NON_RETURNABLE`. Per the ordering in Section 2.8, the hygiene check takes precedence over the line-membership check.

At request time the server computes a provisional `refund_estimate_cents`. The returned-merchandise base is the sum of `line_total_cents` over the lines named in `line_ids`. The estimate is condition-agnostic: it is that base minus a flat restock fee of five dollars (500 cents). The request creates a `ReturnRequest` in status `REQUESTED`.

A `FulfillmentOps` or `PlatformAdmin` operator adjudicates the request. Rejecting it moves the return from `REQUESTED` to `REJECTED` and has no refund, line, inventory, or loyalty effect. Approving it moves the return from `REQUESTED` to `APPROVED` and settles the final refund. The `final_refund_cents` is condition-driven over the same returned-merchandise base: for a `SEALED` return the final refund is the full base; for an `OPENED` return on a hygiene-returnable product, the final refund is the base reduced by a twenty-percent restock deduction — that is, the base multiplied by eighty percent, rounded half up to whole cents. (An opened return on a non-hygiene-returnable product cannot reach approval, having been rejected at request time.)

Approval triggers the system's deepest cascade. Each returned line's `status` becomes `RETURNED`. The server then recomputes the order's `fulfillment_status`: if at least one but not all active lines have been returned, fulfillment becomes `PARTIALLY_RETURNED` and payment becomes `PARTIALLY_REFUNDED`; if all remaining active lines are now returned, fulfillment becomes `RETURNED` and payment becomes `REFUNDED`. A subsequent approved return that covers the last remaining lines moves an order from `PARTIALLY_RETURNED` to `RETURNED` with payment `REFUNDED`. Approval also claws back loyalty exactly: the server writes a `LoyaltyTransaction` with `reason` `REVERSAL` and a `points_delta` equal to the negative of the sum of `points_earned` across the returned lines, and decreases the customer's `loyalty_points_balance` by that sum. Finally the customer's `lifetime_spend_cents` is reduced by the returned lines' net contribution and the customer's `tier` is recomputed against the thresholds in Section 3.3.

### 3.6. Scent-of-Month Subscriptions and Shipments

A `Customer` (or `PlatformAdmin`) opens a scent-of-month `Subscription` by naming the `customer_id`, a `tier` of `BASIC` or `PREMIUM`, and a `monthly_fee_cents` (zero or greater) currently in effect per monthly shipment. The subscription may also declare `included_sample_credits` granted per shipment (defaulting to zero) and, optionally, a scheduled fee change expressed as `pending_fee_cents` together with the `fee_effective_date` on or after which that new fee takes effect; both default to null when no change is scheduled. A new subscription starts `ACTIVE`, and its `current_period_end` is set to one month after the period start.

The subscription lifecycle is cyclic. Pausing an `ACTIVE` subscription moves it to `PAUSED` and increments its `version`; resuming a `PAUSED` subscription moves it back to `ACTIVE` and again increments `version`. Cancelling is terminal and is permitted from either `ACTIVE` or `PAUSED`, setting `status` to `CANCELLED`. A pause requires the subscription to currently be `ACTIVE`, and a resume requires it to currently be `PAUSED`.

Each subscription exposes a forward-looking `projected_next_charge_cents`, the charge the next period would incur. Charging follows a single fee-selection rule: the fee effective at an instant is `pending_fee_cents` when a `fee_effective_date` is set and that instant falls on or after it, and otherwise the standing `monthly_fee_cents`. The projected charge is that rule evaluated at the subscription's `current_period_end` — the next boundary. A shipment's actual charge, by contrast, is the same rule evaluated at the shipment's own `period_start`, so the projected and actual figures diverge only when a scheduled fee change straddles the period boundary.

A `FulfillmentOps` or `PlatformAdmin` operator generates a monthly `Shipment` against a subscription by supplying the billing period as `period_start` (inclusive) and `period_end` (exclusive). The subscription must be `ACTIVE`, or generation is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`; a paused or cancelled subscription cannot be shipped. The new period must not overlap any existing shipment period of the same subscription; because periods are half-open intervals of the form beginning at `period_start` and ending just before `period_end`, two periods that merely touch — one ending exactly where the next begins — are adjacent and allowed, while any true overlap is rejected with `ERR_SHIPMENT_PERIOD_OVERLAP`. The shipment records its `subscription_id`, starts in status `PENDING`, and its `charge_cents` is computed as the actual charge described above (the fee effective at its `period_start`).

Fulfilling a shipment moves it from `PENDING` to `FULFILLED` and charges the subscriber's loyalty and tier through the subscription owner. The server writes a `LoyaltyTransaction` with `reason` `EARN` whose `points_delta` is the shipment's charge in cents divided by one hundred, multiplied by the owning customer's tier multiplier, rounded half up to whole points, and increases the customer's `loyalty_points_balance` accordingly. It then increases the customer's `lifetime_spend_cents` by the shipment's `charge_cents` and recomputes the customer's `tier`.

### 3.7. Exclusive Allocation: Windows and Claims

Exclusive releases are distributed through time-boxed allocation windows. A `Merchandiser` creates an `AllocationWindow` under an exclusive product, supplying `window_start` and `window_end` (both inclusive bounds of the claimable interval), a `total_allocation` of at least one unit releasable in the window, and a `per_customer_cap` of at least one unit that any single customer may claim within this window. A window records the parent `product_id`, exposes its running `claimed_units` (the conserved sum of its claims' units), and derives its `status` from the logical clock: `SCHEDULED` before `window_start`, `OPEN` from `window_start` through `window_end` inclusive, and `CLOSED` after `window_end`. A new window must not overlap any existing window of the same product and must be separated from adjacent windows of that product by at least the allocation buffer of 24 hours (`ALLOCATION_BUFFER_HOURS` = 24 hours); a violation is rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`.

A `Customer` claims allocation against a window by supplying their `customer_id`, the `units` requested (at least one), and the `expected_window_version` required by the concurrency rule in Section 2.6. The checks fire in the Section 2.8 order. The claimant's account must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`). The target product must be exclusive, or the claim is rejected with `ERR_PRODUCT_NOT_EXCLUSIVE`. The window must currently be `OPEN` — a claim against a `SCHEDULED` or `CLOSED` window is rejected with `ERR_ALLOCATION_WINDOW_NOT_OPEN`. Remaining allocation is the window's `total_allocation` minus its `claimed_units`; the requested units must not exceed that remainder — a request exactly equal to the remainder is admissible, one unit beyond it is rejected with `ERR_ALLOCATION_EXHAUSTED`. Two per-customer ceilings also apply: the customer's cumulative units within this window must not exceed the window's `per_customer_cap`, and their cumulative units across all of this product's windows must not exceed the product's `per_customer_limit` (when that limit is set); reaching either limit exactly is allowed, exceeding it by one unit is rejected with `ERR_PER_CUSTOMER_LIMIT`. Finally the `expected_window_version` must equal the window's current `version`, or the claim is rejected with `ERR_STALE_VERSION`.

A successful claim creates an `AllocationClaim` recording its `window_id`, `customer_id`, and `units`, then increases the window's `claimed_units` by those units and increments the window's `version` by one — the very advance that makes a concurrent claimant's stale `expected_window_version` fail.

### 3.8. Customer Accounts and the Loyalty Ledger

A `PlatformAdmin` registers a `Customer` with an `email` (unique across customers and non-empty) and a `full_name`; the account starts with `status` `ACTIVE`, `tier` `BRONZE`, a `loyalty_points_balance` of zero, and a `lifetime_spend_cents` of zero. An administrator may suspend an active account, moving `status` from `ACTIVE` to `SUSPENDED` and incrementing the customer's `version`; suspension requires the account to currently be `ACTIVE`. A suspended customer is barred from placing orders and from claiming allocation, as enforced by `ERR_CUSTOMER_SUSPENDED` in those workflows.

The customer's `loyalty_points_balance` is not stored independently of its history: it always equals the sum of `points_delta` across that customer's `LoyaltyTransaction` rows, where one point equals one cent of redeemable discount. Every ledger row carries the owning `customer_id`, a signed `points_delta`, a `reason` of `EARN`, `REDEEM`, or `REVERSAL`, and a polymorphic origin captured as `source_type` (either `ORDER` or `RETURN`) with the `source_id` of the originating order or return. Earning rows are written at order fulfillment and shipment fulfillment; redemption rows at placement when points are spent; and reversal rows when a placed order is cancelled or a return is approved. The customer's `lifetime_spend_cents` accumulates net merchandise actually paid — increased at order and shipment fulfillment and decreased on return approval — and drives the tier recomputation described in Section 3.3.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource return `201 Created`; endpoints that modify an existing resource — including state-transition actions — return `200 OK`. The request and response bodies for each operation are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/customers/{id}/suspend` | Suspend a customer account | PlatformAdmin |
| GET | `/customers/{id}/allocation-claims` | List a customer's allocation claims | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/customers/{id}/loyalty-transactions` | List a customer's loyalty ledger | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/products` | Create a product SKU | Merchandiser, PlatformAdmin |
| GET | `/products/{id}` | Fetch a product | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/products` | Note-finder / catalog list | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/products/{id}/variants` | Create a purchasable variant | Merchandiser, PlatformAdmin |
| GET | `/products/{id}/variants` | List a product's variants | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/variants/{id}` | Fetch a variant | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/variants/{id}/order-lines` | List order lines referencing a variant | Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/products/{id}/allocation-windows` | Create an allocation window | Merchandiser, PlatformAdmin |
| GET | `/products/{id}/allocation-windows` | List a product's allocation windows | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/allocation-windows/{id}` | Fetch an allocation window | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/allocation-windows/{id}/claims` | Claim exclusive allocation | Customer |
| GET | `/allocation-windows/{id}/claims` | List a window's claims | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/subscriptions` | Create a scent-of-month subscription | Customer, PlatformAdmin |
| GET | `/subscriptions/{id}` | Fetch a subscription | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/subscriptions/{id}/pause` | Pause an active subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/shipments` | Generate a monthly shipment | FulfillmentOps, PlatformAdmin |
| GET | `/subscriptions/{id}/shipments` | List a subscription's shipments | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/shipments/{id}` | Fetch a shipment | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/shipments/{id}/fulfill` | Fulfill a shipment | FulfillmentOps, PlatformAdmin |
| POST | `/orders` | Open a cart for a customer | Customer, PlatformAdmin |
| GET | `/orders/{id}` | Fetch an order | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/orders` | List orders | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/orders/{id}/lines` | Add a line to a cart order | Customer, PlatformAdmin |
| GET | `/orders/{id}/lines` | List an order's lines | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/orders/{id}/place` | Checkout: price, redeem, reserve | Customer |
| POST | `/orders/{id}/fulfill` | Ship the order | FulfillmentOps, PlatformAdmin |
| POST | `/orders/{id}/cancel` | Cancel a cart or placed order | Customer, FulfillmentOps, PlatformAdmin |
| POST | `/returns` | Request a return | Customer |
| GET | `/returns/{id}` | Fetch a return request | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| GET | `/returns` | List returns | Customer, Merchandiser, FulfillmentOps, PlatformAdmin |
| POST | `/returns/{id}/approve` | Approve a return | FulfillmentOps, PlatformAdmin |
| POST | `/returns/{id}/reject` | Reject a return | FulfillmentOps, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_VARIANT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_WINDOW_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 403 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_HYGIENE_NON_RETURNABLE` | 422 |
| `ERR_LINE_NOT_IN_ORDER` | 422 |
| `ERR_ORDER_NOT_FULFILLED` | 409 |
| `ERR_PRODUCT_NOT_EXCLUSIVE` | 422 |
| `ERR_ALLOCATION_WINDOW_NOT_OPEN` | 409 |
| `ERR_ALLOCATION_EXHAUSTED` | 409 |
| `ERR_PER_CUSTOMER_LIMIT` | 409 |
| `ERR_ALLOCATION_WINDOW_OVERLAP` | 409 |
| `ERR_SHIPMENT_PERIOD_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
