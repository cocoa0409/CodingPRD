# Vitamin & Supplement Store API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Vitamin & Supplement Store API, the back-office and storefront platform for a GNC-style nutritional-supplement retailer. The platform manages a catalogue of supplement SKUs alongside the finite, expiration-dated inventory lots those SKUs draw from, and it coordinates the full commercial lifecycle: browsing and ordering, loyalty accrual and redemption, recurring auto-ship subscriptions, practitioner-authorized purchases of restricted product lines, and returns.

Two regulatory and operational pressures shape the system. First, supplements are governed by DSHEA labeling rules and by lot-level traceability: a manufacturer lot can be quarantined, released, or recalled, and a recall must cascade corrections through every open order that reserved units from the affected lot. Second, inventory is a finite resource allocated first-expire-first-out across lots, so every order placement reserves specific units, every fulfilment consumes them, and every cancellation or return releases or restocks them. The API therefore treats inventory quantities, loyalty balances, and order totals as derived values that must be reconciled synchronously inside the request that triggers a change, never left to drift.

The remainder of this document defines the global contracts every endpoint honours (Section 2), the domain workflows and the business rules woven through them (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles: `StoreOperator`, `Customer`, and `Practitioner`. When a caller's role is not permitted to invoke the requested operation per the access matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` binds to persisted data:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a customer — an `Order`, a `Subscription`, or a `Return` the caller is mutating — compare that resource's owning customer foreign key to `X-User-ID`. A customer acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Practitioner`, `X-User-ID` is the `id` of the acting `Practitioner`. Ownership checks on a `Recommendation` compare its issuing-practitioner foreign key to `X-User-ID`; a practitioner acting on a recommendation they did not issue is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `StoreOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may accept and record it, but it does not compare it to any entity's `id`; a store operator is never subject to the ownership check.

All GET read endpoints are available to all three roles. The remaining operations are partitioned as described in Section 4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by the order in which the resources were created (their internal creation sequence).

Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every persisted resource carries an `id`: a server-minted UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded when the resource is first created.

Most resources additionally carry two mutation-tracking fields. `updated_at` is an ISO 8601 UTC timestamp refreshed on every change to the resource, including changes to purely derived fields. `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation of the resource, and it is the value used for optimistic concurrency control (Section 2.9). All entities in this system — `Product`, `Lot`, `Customer`, `Practitioner`, `Recommendation`, `Bundle`, `Subscription`, `Order`, `OrderLine`, and `Return` — carry `updated_at` and `version` in addition to `id` and `created_at`.

### 2.5. Monetary Precision and Rounding

All prices, subtotals, refunds, and redemption amounts are stored and returned as integer counts of cents; there are no fractional cents. Where a discount produces a non-integer intermediate value, the amount is rounded to the nearest whole cent using the round-half-up convention (a value ending in exactly one-half cent rounds up). The precise point at which rounding is applied is pinned per calculation and is stated with each formula in Section 3; in particular, per-unit discounted prices are rounded to whole cents *before* being multiplied by a line quantity, not after. Loyalty point counts are always whole integers, obtained by discarding any fractional part (rounding toward zero) after the governing multiplication or division.

### 2.6. Inventory as a Reconciled Ledger

Each inventory `Lot` maintains three quantity fields that must remain mutually consistent at the end of every request. `quantity_received` is the immutable count of units booked into the lot at receipt. `quantity_on_hand` is the count of physical units still in the lot; it is initialized to `quantity_received`, decremented when a fulfilled allocation ships out, and incremented when an unwanted return is restocked into it. `quantity_reserved` is the sum of the quantities of that lot's allocations currently in `RESERVED` status, and it starts at 0. `quantity_available` is always `quantity_on_hand` minus `quantity_reserved`, and it is the count a new allocation may draw against.

A lot is sellable — eligible to serve a new allocation — only when its `status` is `AVAILABLE` and its `expiration_date` is strictly after the current logical clock. Lots that are `QUARANTINED`, `RECALLED`, or `EXPIRED` are excluded from the allocation candidate set. When allocation is attempted and no sellable lot can serve the demand, the offending condition surfaces as `ERR_LOT_NOT_SELLABLE`.

### 2.7. Cascading Corrections and Hierarchical Consistency

Several operations mutate more than one resource, and every secondary effect resolves synchronously within the triggering request. A lot recall releases the reservations that drew on the recalled lot and marks the affected order lines short; a customer suspension pauses that customer's active subscriptions, cancels their draft auto-ship orders, and releases the reservations those orders held; an order cancellation releases its reservations and refunds any held redemption; a return refund reverses loyalty points and may restock units. Each of these cascades is specified in full within the workflow narrative of Section 3. Whenever a cascade mutates a resource — a parent order, a customer, a lot, a recommendation — that resource's `updated_at` is refreshed and its `version` is incremented, exactly as a direct mutation would do.

### 2.8. Left-to-Right Reference Validation

Requests frequently reference multiple resources: a path identifier plus one or more foreign keys in the body. The system validates every such reference for existence in left-to-right order — path identifiers first, then body foreign keys in the order they appear — and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request that supplies a required field of the wrong type, omits a required field, or supplies an out-of-range enum value is rejected with `ERR_VALIDATION`.

### 2.9. Optimistic Concurrency Control on Auto-Ship Generation

Generating the next auto-ship order for a subscription is guarded by optimistic concurrency control on the subscription's `version`. The generate-order request must carry `expected_subscription_version`, a non-optional field holding the `version` of the target `Subscription` that the client last observed. If `expected_subscription_version` does not equal the subscription's current `version` — because another writer has already generated a cycle and advanced the version since the client last read it — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client holding a stale view of the subscription from generating a duplicate cycle order. No other endpoint takes a version field; only auto-ship generation is version-guarded.

### 2.10. Validation Precedence

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. The order is: authentication of the headers (`ERR_UNAUTHENTICATED`), role authorization (`ERR_UNAUTHORIZED`), resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`), existence of every referenced resource (`ERR_NOT_FOUND`), and then the target resource being in a state that admits the requested transition (`ERR_INVALID_STATE`). Only after these succeed are the endpoint-specific business rules evaluated; where a single endpoint carries several business rules, their relative order is stated with the workflow in Section 3 (most consequentially, at order placement).

### 2.11. DSHEA Labeling Compliance

Under the Dietary Supplement Health and Education Act, a product may bear a structure/function claim or no claim, but never a disease claim. The system enforces this at catalogue entry: a product's claim classification may be recorded as structure/function or none, but a request attempting to record a disease claim is rejected outright with `ERR_DSHEA_DISEASE_CLAIM` and the disease value is never persisted. Whether a product must display the FDA "This statement has not been evaluated by the Food and Drug Administration" disclaimer is derived directly from its recorded claim classification, as detailed in Section 3.

### 2.12. The Logical Clock and Expiry Materialization

The server keeps a logical clock rather than reading wall-clock time. On startup, and before any operator sets it, the clock reads exactly `2026-07-01T00:00:00Z`. An operator may advance the clock to a supplied instant, provided as `to_iso8601`; doing so does not itself change any lot or recommendation state. Expiry becomes visible only when an operator runs the expiry sweep, which materializes the appropriate expired states as described in Section 3. All time comparisons in the system — lot expiration, recommendation validity, subscription scheduling — are made against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Building the Catalogue: Products and Inventory Lots

A `StoreOperator` seeds the catalogue by creating a `Product`, supplying its display `name`, its dosage `form` (one of `CAPSULE`, `TABLET`, `POWDER`, `GUMMY`, or `LIQUID`), the list of `regimen_goals` it targets (each element drawn from `IMMUNITY`, `SLEEP`, `ENERGY`, `JOINT`, and `DIGESTION`), and its `unit_price_cents` (the integer list price per unit). The operator may mark a SKU as a practitioner line by setting `is_practitioner_line`; when omitted it defaults to false, meaning the product is freely purchasable. The operator also supplies the product's `dshea_claim_type`, which may be `STRUCTURE_FUNCTION` or `NONE`; a submitted value of `DISEASE` is refused with `ERR_DSHEA_DISEASE_CLAIM` (see Section 2.11) and never stored. The system computes `requires_fda_disclaimer` as a stored boolean that is true exactly when `dshea_claim_type` is `STRUCTURE_FUNCTION`, and false otherwise.

Physical stock arrives as lots. Receiving a `Lot` against a product records the manufacturer's `lot_number`, the lot's `expiration_date` (an ISO 8601 UTC instant), and the `quantity_received`. The owning `product_id` is taken from the receiving path, not the body. A freshly received lot begins with `status` `AVAILABLE`; its `quantity_on_hand` is initialized to `quantity_received`, its `quantity_reserved` to 0, and its `quantity_available` therefore equals `quantity_received`. Its `recall_reason` and `recall_severity` are both absent until a recall occurs. A lot may be listed under its product or filtered by `status`.

### 3.2. Lot Lifecycle: Quarantine, Recall, and Expiry

A `StoreOperator` drives a lot through its lifecycle by supplying a target status (`to_status`), optionally accompanied by a `reason` and `severity` when recalling. A lot moves from `AVAILABLE` to `QUARANTINED` when the current status is `AVAILABLE`; while `QUARANTINED` the lot is excluded from the first-expire-first-out candidate set and cannot serve new allocations, but any allocations already `RESERVED` against it are left untouched. A quarantined lot returns to `AVAILABLE` (re-entering the candidate set) when its current status is `QUARANTINED`. This forms a cyclic `AVAILABLE` ↔ `QUARANTINED` loop. A transition requested from a status that does not admit it is rejected with `ERR_INVALID_STATE`.

Recall is the consequential transition. A lot may move to `RECALLED` from either `AVAILABLE` or `QUARANTINED`, and the request must carry the recall `reason` and the FDA recall `severity` (`CLASS_I`, `CLASS_II`, or `CLASS_III`), which are stored on `recall_reason` and `recall_severity`. Recalling runs a cascade: every allocation on the recalled lot that is currently `RESERVED` transitions to `RELEASED`; each released allocation increases the `short_quantity` of its owning `OrderLine` by that allocation's quantity, marking those units as no longer shippable; and the lot's `quantity_reserved` decreases by the total quantity of the released allocations. The parent `Order` of each affected line keeps its `provisional_subtotal_cents` unchanged — the shortfall is not realized until the order is fulfilled, at which point the final subtotal reflects it. `RECALLED` is a terminal lot status.

Expiry is materialized only by the operator-run expiry sweep. When the sweep runs, any lot in `AVAILABLE` or `QUARANTINED` whose `expiration_date` is at or before the current logical clock transitions to `EXPIRED`; an expired lot is permanently excluded from the allocation candidate set. `EXPIRED` is terminal. The same sweep also materializes recommendation expiry, described in Section 3.4.

### 3.3. Customers and the Loyalty Ledger

A `StoreOperator` onboards a `Customer` with an `email` (the login identity) and a `full_name`. A new customer starts with `status` `ACTIVE`, `lifetime_points_earned` of 0, `points_balance` of 0, and `loyalty_tier` `BRONZE`.

Two loyalty accumulators are tracked and must be kept distinct. `lifetime_points_earned` is the cumulative count of settled points the customer has ever earned; it drives the tier and is sticky — it is never decremented, not even by a return. `points_balance` is the spendable balance: settled earnings are added to it at order fulfilment, redeemed points are held out of it at order placement, and held or settled points are added back on cancellation or return refund as described in the order and return workflows. The `loyalty_tier` is derived from `lifetime_points_earned`: a customer with at least 1000 lifetime points is `GOLD`, a customer with at least 500 but fewer than 1000 is `SILVER`, and anyone below 500 is `BRONZE`. The thresholds are inclusive at the boundary — exactly 1000 lifetime points is `GOLD`, and 999 is `SILVER`. Because no ordinary endpoint writes these computed accumulators directly, an operator-only seeding capability may set a customer's `lifetime_points_earned` and/or `points_balance` and then recompute `loyalty_tier`; this seeding increments the customer's `version`.

Suspending a customer is a `StoreOperator` action that moves an `ACTIVE` customer to `SUSPENDED` and runs a three-level cascade; an attempt to suspend a customer that is not currently `ACTIVE` is rejected with `ERR_INVALID_STATE`. First, every `Subscription` of that customer currently in `ACTIVE` status is moved to `PAUSED`. Second, for each such subscription, any of its auto-ship `Order`s still in `DRAFT` are moved to `CANCELLED`. Third, each of those cancelled orders releases its lines' `RESERVED` allocations back to their lots, decreasing each lot's `quantity_reserved` accordingly. A suspended customer may no longer place orders or open subscriptions; attempts to buy while suspended surface as `ERR_CUSTOMER_SUSPENDED`.

### 3.4. Practitioner Lines: Recommendations and Their Consumption

A `Practitioner` is onboarded by a `StoreOperator` with a `full_name` and `license_number`. A practitioner authorizes a restricted purchase by issuing a `Recommendation`: the request supplies the `customer_id` being authorized, the `product_id` of the practitioner-line SKU, the `expires_at` instant, and `max_units`, the total number of units the authorization covers. The issuing `practitioner_id` is taken from `X-User-ID`, and `issued_at` is stamped with the current logical clock; the validity interval is the half-open span from `issued_at` up to but not including `expires_at`. A new recommendation begins with `status` `ISSUED` and `consumed_units` of 0. A new recommendation's interval may not overlap the interval of any existing `ISSUED` recommendation for the same customer-and-product pair; because the interval is half-open, two intervals that merely touch at an endpoint do not overlap and are allowed, but any genuine overlap is rejected with `ERR_RECOMMENDATION_OVERLAP`. Recommendations may be listed and filtered by `practitioner_id`, `customer_id`, `product_id`, or `status`.

A recommendation leaves `ISSUED` down one of three branches. It is `EXHAUSTED` by the system at order fulfilment when its consumption reaches its cap (detailed below). It is moved to `EXPIRED` by the operator-run expiry sweep when its `expires_at` is at or before the current logical clock. And it is moved to `REVOKED` when its issuing practitioner revokes it while it is still `ISSUED` (a revoke on a recommendation not in `ISSUED` is rejected with `ERR_INVALID_STATE`). In all three cases the authorization can no longer back a practitioner-line purchase. `EXHAUSTED`, `EXPIRED`, and `REVOKED` are terminal.

Consumption is measured at fulfilment. A recommendation's `consumed_units` is the sum, over the fulfilled order lines of the same customer and product that drew on the authorization, of each such line's fulfilled quantity (its `quantity` less its `short_quantity`). When `consumed_units` reaches `max_units` exactly, the recommendation transitions from `ISSUED` to `EXHAUSTED`; the boundary is inclusive equality — reaching the cap exhausts it, and it is never allowed to exceed the cap.

### 3.5. Bundles and Auto-Ship Subscriptions

A `StoreOperator` defines a `Bundle` (a stack) with a display `name`, the `component_product_ids` that make up the stack, and a fractional `discount_pct` (for example, 0.15) applied to any order line whose product is one of the stack's components.

A `Customer` opens an auto-ship `Subscription` for themselves. The request supplies the `product_id` to ship, the `quantity_per_cycle`, the `cadence_days`, and the `first_ship_date`. The owning `customer_id` is taken from `X-User-ID`. The `quantity_per_cycle` must be at least 1; a value below 1 is rejected with `ERR_INVALID_QUANTITY`. The `cadence_days` must be one of 30, 60, or 90; any other value is rejected with `ERR_INVALID_CADENCE`. A new subscription begins `ACTIVE`; its `next_ship_date` is initialized to `first_ship_date`; and its `autoship_discount_pct` is derived from the cadence — 0.05 for a 30-day cadence, 0.08 for a 60-day cadence, and 0.10 for a 90-day cadence. To avoid overlapping recurring shipments, a new subscription's `first_ship_date` must be at least a fixed buffer of `SUBSCRIPTION_BUFFER_DAYS` (which is 7) days away from the `next_ship_date` of any existing `ACTIVE` or `PAUSED` subscription for the same customer and product: a first-ship date strictly closer than 7 days is rejected with `ERR_SUBSCRIPTION_WINDOW_CONFLICT`, while one exactly 7 days apart is accepted. Opening a subscription while the customer is suspended is rejected with `ERR_CUSTOMER_SUSPENDED`. Subscriptions may be listed and filtered by `customer_id`, `product_id`, or `status`.

The owning customer drives subscription state by supplying a target status (`to_status`). An `ACTIVE` subscription may be paused, moving it to `PAUSED`; a `PAUSED` subscription may be resumed back to `ACTIVE`, forming a cyclic `ACTIVE` ↔ `PAUSED` loop. A subscription may be cancelled to `CANCELLED` from either `ACTIVE` or `PAUSED`, which is terminal. A transition requested from a status that does not admit it is rejected with `ERR_INVALID_STATE`.

Generating the next auto-ship cycle is a customer action carrying `expected_subscription_version` (see the concurrency contract in Section 2.9). Generation is refused while the subscription is `PAUSED`. When it succeeds against an `ACTIVE` subscription, the system creates a new `DRAFT` order of auto-ship type whose owning subscription is set, containing a single line for the subscription's product at `quantity_per_cycle`; it advances the subscription's `next_ship_date` by `cadence_days`; and it increments the subscription's `version` by one.

### 3.6. The Order Lifecycle: Draft, Placement, Fulfilment, and Cancellation

A `Customer` opens a one-off order, which begins in `DRAFT` with an `order_type` of `ONE_OFF` and no owning subscription (`subscription_id` null). At creation the buyer may declare `points_redeemed`, the number of loyalty points to apply against this order (defaulting to 0; a negative value is rejected with `ERR_VALIDATION`). Opening a one-off order while the acting customer is suspended is rejected with `ERR_CUSTOMER_SUSPENDED`. Auto-ship orders are instead created by subscription generation as described above; those carry an `order_type` of `AUTOSHIP` and their originating subscription reference. Orders may be listed and filtered by `customer_id`, `subscription_id`, or `status`.

While an order is in `DRAFT`, the customer adds order lines. Each `OrderLine` names a `product_id` and a `quantity`, and may optionally name a `bundle_id` to claim a stack discount. If a `bundle_id` is supplied, the line's product must be a component of that bundle; otherwise the line is rejected with `ERR_BUNDLE_PRODUCT_MISMATCH`. The `quantity` must be at least 1; a quantity below 1 is rejected with `ERR_INVALID_QUANTITY`. On line creation the system snapshots `gross_unit_price_cents` from the product's current `unit_price_cents`. A line also carries the computed pricing fields `net_unit_price_cents`, `line_total_cents`, the `lot_allocations` array (initially empty), and `short_quantity` (initially 0), all of which are filled in at placement or later. Lines may be listed for an order or fetched individually, and may be filtered by `product_id` or `bundle_id`.

Placing a draft order is the pivotal transition, and its checks run in a fixed order after the universal precedence of Section 2.10. First, for every line whose product is a practitioner line, there must exist an `ISSUED`, non-expired `Recommendation` for that customer and product whose already-consumed units plus this line's quantity do not exceed its `max_units`; a line lacking such backing is rejected with `ERR_PRACTITIONER_AUTH_REQUIRED`. Next, allocation must be able to draw only from sellable lots — when a line cannot be fully served from its product's sellable lots and that product has at least one lot that is not `AVAILABLE`-and-non-expired (a `QUARANTINED`, `RECALLED`, or `EXPIRED` lot, or one whose `expiration_date` is at or before the logical clock), the placement surfaces as `ERR_LOT_NOT_SELLABLE`; an unservable line whose product has no such blocking lot is instead rejected with `ERR_INSUFFICIENT_INVENTORY` (below). The buyer must be `ACTIVE`, or the placement is rejected with `ERR_CUSTOMER_SUSPENDED`. The order must contain at least one line, or it is rejected with `ERR_INVALID_QUANTITY`. Inventory must fully cover every line (below), or the placement is rejected with `ERR_INSUFFICIENT_INVENTORY`. Finally, the redemption must be affordable: `points_redeemed` must not exceed the customer's `points_balance` and the redemption value must not exceed the order's provisional subtotal, or the placement is rejected with `ERR_INSUFFICIENT_POINTS`.

Allocation is first-expire-first-out. For each line, the candidate lots are the lots of the line's product whose `status` is `AVAILABLE` and whose `expiration_date` is strictly after the current logical clock; they are considered in order of `expiration_date` ascending, breaking ties by `created_at` ascending. Walking the candidates, the system takes from each lot the smaller of the remaining unmet demand and that lot's `quantity_available`; when it takes a positive amount it records a `RESERVED` allocation of that quantity against the lot (an entry of `lot_id`, `quantity`, and `status` in the line's `lot_allocations`) and increases the lot's `quantity_reserved` by the same amount, reducing the remaining demand. Allocation for the line stops as soon as the remaining demand reaches zero. When an order carries multiple lines drawing on the same product, the lines are allocated in `created_at` (then creation-sequence) order and each line's tentative reservations within this placement reduce the `quantity_available` seen by later lines drawing on the same lot. If the candidate pool is exhausted while demand remains, the entire order is rejected with `ERR_INSUFFICIENT_INVENTORY` and no allocation from this placement persists.

Pricing is computed per line at placement. The applicable purchase discount depends on the order kind: for an auto-ship order it is the owning subscription's `autoship_discount_pct`; for a one-off order it is the loyalty purchase discount for the buyer's tier — 0.00 for `BRONZE`, 0.05 for `SILVER`, and 0.10 for `GOLD`. The bundle discount is the bundle's `discount_pct` when the line supplies a `bundle_id` and its product is a component of that bundle, and 0 otherwise. The `net_unit_price_cents` is the `gross_unit_price_cents` multiplied by one minus the bundle discount and then by one minus the applicable purchase discount, rounded half-up to a whole cent at the per-unit level before any multiplication by quantity. The `line_total_cents` is then `net_unit_price_cents` multiplied by the line's `quantity`. The order's `provisional_subtotal_cents` is the sum of `line_total_cents` across all lines, captured at placement when every line is fully allocated and no line is short. The `redemption_cents` is `points_redeemed` multiplied by the per-point redemption value in cents (`POINT_REDEMPTION_VALUE_CENTS`, which is 1 cent, so `redemption_cents` equals `points_redeemed`). The order's `total_cents` while placed is `provisional_subtotal_cents` minus `redemption_cents`. Placement also computes a provisional `points_earned` (below) and holds the redemption by decreasing the customer's `points_balance` by `points_redeemed`.

The provisional loyalty earning at placement is computed on the provisional subtotal, which is the pre-redemption merchandise value. The base points are the provisional subtotal in cents divided by 100 and floored to a whole number. The earn multiplier is the tier multiplier — 1.0 for `BRONZE`, 1.25 for `SILVER`, 1.5 for `GOLD` — plus an additional 0.25 auto-ship bonus when the order is an auto-ship order. The `points_earned` is the base points multiplied by the earn multiplier, floored to a whole number, and then capped at 2000. At placement this provisional value is written to `points_earned` but is not credited to `points_balance`.

Fulfilling a placed order is a `StoreOperator` action, advancing it from `PLACED` to `FULFILLED`. Each `RESERVED` allocation on the order transitions to `CONSUMED`; for each, the source lot's `quantity_on_hand` decreases by the allocation's quantity and its `quantity_reserved` also decreases by that quantity. The order's `final_subtotal_cents` is recomputed as the sum over lines of `net_unit_price_cents` multiplied by the line's `quantity` minus its `short_quantity`; a recall that shorted a line between placement and fulfilment makes the final subtotal fall below the provisional one, and the order's `total_cents` becomes `final_subtotal_cents` minus `redemption_cents`. Loyalty is then settled on the final subtotal using the same base-points, multiplier, and cap rule as the provisional computation but sourced from `final_subtotal_cents`; the settled `points_earned` is added to the customer's `points_balance` and to `lifetime_points_earned`, and `loyalty_tier` is recomputed. For each practitioner-line line, the backing recommendation's `consumed_units` increases by the line's fulfilled quantity — its `quantity` less its `short_quantity` (a line fully shorted by a recall consumes nothing) — and if that reaches its `max_units` the recommendation is exhausted as described in Section 3.4.

An order may be cancelled from `DRAFT` or from `PLACED`. Cancelling a `DRAFT` order releases nothing, because allocation only happens at placement. Cancelling a `PLACED` order is compensating: every `RESERVED` allocation transitions to `RELEASED` and its lot's `quantity_reserved` decreases by the allocation's quantity, restoring `quantity_available`; the held redemption is refunded by increasing the customer's `points_balance` by `points_redeemed`. Because points are only settled at fulfilment, a placed-then-cancelled order has no earned points to claw back. Cancellation may be performed by the owning customer or by a store operator.

### 3.7. Returns and Refunds

A `Customer` requests a `Return` against a fulfilled order line, supplying the `order_id`, the `order_line_id`, the `quantity` being returned, and the `reason` (`DEFECT`, `UNWANTED`, `RECALL`, or `EXPIRED`). The returned `quantity` must be at least 1 (else `ERR_INVALID_QUANTITY`) and must not exceed the line's fulfilled, non-shorted quantity (else `ERR_RETURN_QUANTITY_EXCEEDS`). A new return begins with `status` `REQUESTED`. Returns may be listed and filtered by `order_id`, `order_line_id`, or `status`.

A `StoreOperator` adjudicates a return by supplying a target status (`to_status`). A `REQUESTED` return may be approved to `APPROVED` or rejected to `REJECTED`; an `APPROVED` return may be refunded to `REFUNDED`. `REJECTED` and `REFUNDED` are terminal, and a transition from a status that does not admit it is rejected with `ERR_INVALID_STATE`.

Refunding computes the money and points to return, with two variants keyed on the reason. The gross refund value is the line's `net_unit_price_cents` multiplied by the return's `quantity`. The `points_reversed` is the order's settled `points_earned` multiplied by the gross refund value, divided by the order's `final_subtotal_cents`, and floored to a whole number — the share of earned points attributable to the returned merchandise. When the reason is `DEFECT`, `RECALL`, or `EXPIRED`, the full variant applies: `refund_cents` equals the gross refund value with no restocking fee, and `restock` is false (the units are not returned to inventory). When the reason is `UNWANTED`, the unwanted variant applies: `refund_cents` is the gross refund value multiplied by one minus the 0.15 restocking fee, rounded half-up to a whole cent, and `restock` is true when the source lot — the lot referenced by the line's first `lot_allocations` entry — has `status` still `AVAILABLE` and false otherwise. On refund, the customer's `points_balance` is decreased by `points_reversed` (a compensating claw-back of the earned points), and if `restock` is true and the source lot is `AVAILABLE`, that lot's `quantity_on_hand` is increased by the returned `quantity`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that fetch, list, or modify an existing resource (including state transitions and the administrative test-driving operations) return `200 OK`. All list endpoints accept the `limit` and `offset` pagination query parameters described in Section 2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a Product/SKU | StoreOperator |
| GET | `/products/{id}` | Fetch a Product | StoreOperator, Customer, Practitioner |
| POST | `/products/{id}/lots` | Receive a new inventory Lot for a product | StoreOperator |
| GET | `/products/{id}/lots` | List a product's lots | StoreOperator, Customer, Practitioner |
| GET | `/lots/{id}` | Fetch a Lot | StoreOperator, Customer, Practitioner |
| POST | `/lots/{id}/state` | Quarantine, release, or recall a Lot | StoreOperator |
| POST | `/customers` | Onboard a Customer | StoreOperator |
| GET | `/customers/{id}` | Fetch a Customer | StoreOperator, Customer, Practitioner |
| POST | `/customers/{id}/suspend` | Suspend a Customer (runs the pause/cancel/release cascade) | StoreOperator |
| POST | `/practitioners` | Onboard a Practitioner | StoreOperator |
| GET | `/practitioners/{id}` | Fetch a Practitioner | StoreOperator, Customer, Practitioner |
| POST | `/recommendations` | Issue a purchase authorization | Practitioner |
| GET | `/recommendations/{id}` | Fetch a Recommendation | StoreOperator, Customer, Practitioner |
| GET | `/recommendations` | List/filter recommendations | StoreOperator, Customer, Practitioner |
| POST | `/recommendations/{id}/revoke` | Revoke an ISSUED recommendation | Practitioner |
| POST | `/bundles` | Create a Bundle/stack | StoreOperator |
| GET | `/bundles/{id}` | Fetch a Bundle | StoreOperator, Customer, Practitioner |
| POST | `/subscriptions` | Create an auto-ship Subscription | Customer |
| GET | `/subscriptions/{id}` | Fetch a Subscription | StoreOperator, Customer, Practitioner |
| GET | `/subscriptions` | List/filter subscriptions | StoreOperator, Customer, Practitioner |
| POST | `/subscriptions/{id}/state` | Pause, resume, or cancel a Subscription | Customer |
| POST | `/subscriptions/{id}/generate-order` | Generate the current-cycle auto-ship Order (OCC-guarded) | Customer |
| POST | `/orders` | Open a one-off DRAFT Order | Customer |
| GET | `/orders/{id}` | Fetch an Order | StoreOperator, Customer, Practitioner |
| GET | `/orders` | List/filter orders | StoreOperator, Customer, Practitioner |
| POST | `/orders/{id}/lines` | Add an OrderLine to a DRAFT order | Customer |
| GET | `/orders/{id}/lines` | List an order's lines | StoreOperator, Customer, Practitioner |
| GET | `/order-lines/{id}` | Fetch a single OrderLine | StoreOperator, Customer, Practitioner |
| GET | `/order-lines` | List/filter order lines | StoreOperator, Customer, Practitioner |
| POST | `/orders/{id}/place` | Place a DRAFT order (allocate, price, hold points) | Customer |
| POST | `/orders/{id}/fulfill` | Fulfill a PLACED order (consume, settle points) | StoreOperator |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT or PLACED order | Customer, StoreOperator |
| POST | `/returns` | Request a return against a fulfilled line | Customer |
| GET | `/returns/{id}` | Fetch a Return | StoreOperator, Customer, Practitioner |
| GET | `/returns` | List/filter returns | StoreOperator, Customer, Practitioner |
| POST | `/returns/{id}/state` | Approve, reject, or refund a Return | StoreOperator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreOperator |
| POST | `/_jobs/run-expiry-sweep` | Materialize lot and recommendation expiry | StoreOperator |
| POST | `/_inject/loyalty_state` | Seed a customer's loyalty accumulators | StoreOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DSHEA_DISEASE_CLAIM` | 422 |
| `ERR_PRACTITIONER_AUTH_REQUIRED` | 403 |
| `ERR_LOT_NOT_SELLABLE` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_BUNDLE_PRODUCT_MISMATCH` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_INVALID_CADENCE` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_RECOMMENDATION_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_WINDOW_CONFLICT` | 409 |
| `ERR_RETURN_QUANTITY_EXCEEDS` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
