# Vinyl Records Shop API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a hybrid vinyl-records and used-media retailer that operates both an online storefront and a physical shop floor. The business sells new and second-hand records, CDs, and cassettes; buys media from the public through trade-ins that pay out in either store credit or cash; takes stock on consignment from private owners; runs Record Store Day (RSD) and label-exclusive releases through a finite allocation pool with pre-orders and pickup windows; adjudicates disputes over the condition grade a used copy received; and rewards repeat buyers through a loyalty program. Each of these surfaces has its own lifecycle, but they share a single catalog, a single customer ledger of store credit and loyalty points, and a single pool of physical inventory copies.

The recurring difficulty this service must solve is that money and scarce units move through provisional and final stages that must always reconcile. A trade-in is valued twice — once from what the seller claims, once from what a grader actually finds — and only the final figure touches the customer's balance. A consignment is quoted an estimated payout when it goes on display and settled at an actual payout when it sells, and those two numbers legitimately diverge when the price is marked down. An exclusive release has a fixed number of units that are competed for, reserved, promoted from a waitlist, and finally committed, and the pool's three counters must always sum to the total the store was allotted. A grading dispute can retroactively change a copy's grade, which ripples into its price and into any open order that still holds it. The specifications below fix the exact field names, states, formulas, rounding rules, and error codes so that every one of these reconciliations is deterministic.

## 2. Global Specifications & System-Wide Principles

All endpoints are mounted under the `/shop` path prefix. This section defines the contracts that hold uniformly across every resource: authentication, the response envelope, pagination, shared resource properties, monetary precision, optimistic concurrency, cascade consistency, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every protected request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting as. Requests to a protected endpoint that omit either header, or that send a malformed value, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are five roles, spelled exactly as follows: `Anonymous`, `Customer`, `StoreClerk`, `Grader`, and `Manager`.

`Anonymous` represents the unauthenticated public browsing the catalog. Its `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The public catalog reads — reading and listing products, reading and listing inventory items — are the only operations available without authentication.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning foreign-key field to `X-User-ID`. Concretely, a `Customer` may act only on orders, trade-ins, pre-orders, grading disputes, and special orders whose `customer_id` equals their `X-User-ID`, and on consignments whose `consignor_id` equals their `X-User-ID`. An attempt by an authenticated `Customer` to mutate a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

`StoreClerk`, `Grader`, and `Manager` are operational roles. For each of these three, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`, and these roles are not subject to per-resource ownership checks. A `StoreClerk` runs the shop floor: capturing payment, shipping and fulfilling orders, readying and fulfilling pre-orders, sourcing and fulfilling special orders, and adding inventory. A `Grader` inspects trade-ins and adjudicates grading disputes. A `Manager` holds catalog and allocation authority, activates and withdraws consignments, reverses trade-ins, resolves escalated disputes, adjusts store credit, and controls the logical clock.

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

### 2.3. Pagination

List endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and has a minimum of 0. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside its `meta` object, where `total_count` is the total number of matching records across all pages and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every persisted resource is assigned a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every entity in this system also carries an `updated_at` timestamp (same format) and an integer `version` that starts at 1 and increments by one on every mutation of that resource. Clients never supply `id`, `created_at`, `updated_at`, or `version`; these are managed entirely by the server. The `version` field is the anchor for the optimistic-concurrency mechanism described in §2.6, and it also advances whenever a cascade (§2.7) touches a resource.

### 2.5. Monetary Precision, Grades, and Rounding Discipline

All monetary amounts are stored and returned as whole integer cents. Wherever a computation produces a fractional cent, the result is rounded half up to the nearest whole cent. Several calculations are composed of multiple rounding steps whose order is significant; those calculations state their pinned evaluation order in §3, and implementations must follow that order exactly rather than rounding once at the end.

Condition is expressed on the Goldmine scale, and every grade field accepts exactly one of these seven values: `M`, `NM`, `VG_PLUS`, `VG`, `G`, `F`, `P`. The pricing of a store-owned copy is driven by a fixed grade multiplier applied to the release's reference price: `M` multiplies by 1.10, `NM` by 1.00, `VG_PLUS` by 0.80, `VG` by 0.60, `G` by 0.40, `F` by 0.25, and `P` by 0.15. The reference price a `Product` carries, `base_price_cents`, is defined as the price of a NEAR-MINT (that is, `NM`) copy, which is why the `NM` multiplier is exactly 1.00.

### 2.6. Optimistic Concurrency on Allocation Pools

Reserving a unit of an exclusive release competes for a finite pool, so pre-order creation is guarded by optimistic concurrency on the `Allocation`. A pre-order creation request must include `expected_allocation_version`, carrying the client's last observed `version` of the target `Allocation`. If that value does not match the allocation's current `version` — because another writer has advanced it since the client last read the allocation, legitimately decrementing `available_count` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than allowing the client to over-commit the pool from a stale view of its remaining capacity. A successful pre-order creation itself increments the allocation's `version` by one. Pre-order creation is the only endpoint that takes a version field; no other write in this system requires a client-supplied version.

### 2.7. Cascading Consistency and Version Propagation

Many operations mutate more than one resource, and every such cascade resolves atomically within the request that triggers it — there is no deferred or eventual settlement. When a cascade writes a resource, that resource's `updated_at` is refreshed and its `version` increments, exactly as for any direct mutation. The specific cascades — order cancellation releasing reserved copies (an ordinary order cancellation does not touch any allocation counter or promote a waitlisted pre-order), a pre-order cancellation returning a unit to the pool and promoting the earliest waitlisted pre-order on that allocation, a sale settling a consignment and crediting the consignor, a regrade resyncing an open order's line prices and totals, and a trade-in reversal clawing back credit and voiding created copies — are described in the workflow subsections of §3. The governing principle here is that a cascade never leaves a counter, balance, or price in a state that contradicts the invariants those subsections define.

### 2.8. Nested Resource Retrieval and Path Validation

Several resources are addressed through nested paths (for example, the lines belonging to an order or a trade-in). Path parameters are validated left to right: each referenced resource in the path must exist before the next segment is considered, and any missing resource yields `ERR_NOT_FOUND` (HTTP 404). The same existence rule applies to resources referenced in a request body — for instance, the product, allocation, inventory item, or consignment a request names must exist, or the request is rejected with `ERR_NOT_FOUND`.

### 2.9. Validation Ordering and Precedence

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first: a missing or malformed `X-User-ID`/`X-User-Role` yields `ERR_UNAUTHENTICATED` (401). Role authorization is checked next: a role not permitted for the operation yields `ERR_FORBIDDEN` (403). Existence of all referenced resources is checked third, left to right, yielding `ERR_NOT_FOUND` (404). Resource ownership is checked fourth: an authenticated `Customer` acting on a resource they do not own yields `ERR_NOT_RESOURCE_OWNER` (403). State validity is checked fifth: if the target resource is not in a state that permits the requested transition, the request yields `ERR_INVALID_STATE` (409). Cross-entity readiness guards are checked sixth, yielding `ERR_DEPENDENCY_NOT_READY` (409) when a prerequisite on a related entity is unmet. Only after these general gates pass are the operation-specific business rules — pre-order windows, pickup capacity, slot availability and overlap, grade-for-new, inspection completeness, allocation exhaustion, credit sufficiency, and allocation version freshness — evaluated. A malformed body, a missing required field, or an invalid enum value is reported as `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Building the Catalog and Stocking Physical Copies

A `Manager` seeds the catalog by creating a `Product`, supplying the recording `artist`, the release `title`, the media `format` (one of `VINYL`, `CD`, or `CASSETTE`), and the `base_price_cents` reference price for a NEAR-MINT copy, which must be a positive integer. A product may optionally be flagged with `is_rsd_exclusive`, which defaults to false and marks Record Store Day and label-exclusive releases that are sold through allocation and pre-order rather than off open stock. Every new product begins with a `catalog_status` of `DRAFT`.

A product's `catalog_status` walks a small lifecycle. A `Manager` lists a product, moving it from `DRAFT` to `LISTED`, but only once the product is stockable: at least one `InventoryItem` already exists for it, or the product carries `is_rsd_exclusive` set to true (an exclusive is allowed to list ahead of any physical stock because its units arrive through the allocation). From `LISTED`, an exclusive product can be opened for pre-orders, advancing `catalog_status` to `PRE_ORDER_OPEN`; this requires that the product is flagged `is_rsd_exclusive`, that an `Allocation` exists for it, and that the logical clock has not yet reached that allocation's `window_close_at`. While in `PRE_ORDER_OPEN`, the first pre-order create attempt evaluated at or after the allocation's `window_close_at` moves the product to `PRE_ORDER_CLOSED`. Separately, a `Manager` may discontinue a `LISTED` product, moving it to the terminal `DISCONTINUED` state, provided no `InventoryItem` for that product is currently `RESERVED`; discontinuation is blocked while a copy is held for a buyer. All four of these transitions are guarded by the state-validity check, so an attempt from the wrong starting state is rejected with `ERR_INVALID_STATE`.

Physical stock is represented by `InventoryItem` records, each a single copy. A `StoreClerk` or `Manager` adds a copy by naming its `product_id`, whether it `is_used`, and its `condition_grade`; a consigned copy also carries the `consignment_id` of the consignment that owns it, which is otherwise null. A newly added copy starts with `status` of `AVAILABLE`. New sealed copies are held to a quality floor: when `is_used` is false, the `condition_grade` must be either `M` or `NM`, and any other grade on a new copy is rejected with `ERR_INVALID_GRADE_FOR_NEW` (HTTP 422).

Each copy's `list_price_cents` is computed the moment it is created. For a consigned copy — one whose `consignment_id` is set — the price is taken directly from the owning consignment's `list_price_cents`, because the consignor sets the ask. For a store-owned copy, the price is the product's `base_price_cents` multiplied by the grade multiplier for the copy's `condition_grade` (the multipliers in §2.5), with that product rounded half up to whole cents. New copies carry one extra rule: a copy whose `is_used` is false is never priced below the product's reference price, so its `list_price_cents` is the greater of the rounded computed price and `base_price_cents`. A copy's `status` moves through `AVAILABLE`, `ON_DISPLAY`, `RESERVED`, and the terminal `SOLD`; the transitions between these are driven by orders, consignments, and pre-orders and are described where those workflows appear.

### 3.2. Assembling an Order and Reserving Copies

Before any purchase, a buyer registers as a `Customer` by supplying a unique, non-empty `email` (the login identifier) and a display `full_name`; an `email` already registered to another customer is rejected with `ERR_INVALID_REQUEST`; registration initializes `store_credit_cents` and `loyalty_points` to zero and `loyalty_tier` to `STANDARD`.

A `Customer` opens an order by supplying their `customer_id` and the `channel`, which is either `ONLINE` or `IN_STORE`. A fresh order starts with `payment_status` of `UNPAID` and `fulfillment_status` of `PENDING`; these two dimensions advance independently, which is why the order carries them as separate fields. The order also carries the computed money fields `subtotal_cents`, `discount_cents`, `shipping_cents`, and `total_cents`, all starting at zero, plus `points_earned` and `credit_applied_cents`, which also start at zero.

The buyer adds copies to the order one line at a time. Each `OrderLine` names the `order_id` it belongs to and the `inventory_item_id` of the specific copy, and carries a `qty` that is always exactly 1 because each physical copy is unique. Adding the first line advances the order's `fulfillment_status` from `PENDING` to `RESERVED`. Every copy added this way must currently be in `AVAILABLE` or `ON_DISPLAY` status, and adding it moves that copy to `RESERVED` so no other buyer can claim it. The line captures a `unit_price_cents` snapshot of the copy's `list_price_cents` at the moment the line is created; this snapshot is later re-synced only by a regrade cascade while the order is still open (see §3.8). Adding a line to a copy that is not available for sale fails the state check with `ERR_INVALID_STATE`.

Order totals are recomputed on every line addition (and again whenever a regrade cascade touches an open order), following a pinned order of steps. First, `subtotal_cents` is the sum over all lines of each line's `unit_price_cents` multiplied by its `qty`. Second, a new-item subtotal is formed as the sum of the same product over only those lines whose copy has `is_used` equal to false. Third, `discount_cents` is that new-item subtotal multiplied by the loyalty discount rate for the buyer's current `loyalty_tier` — 0 percent for `STANDARD`, 5 percent for `SILVER`, and 10 percent for `GOLD` — with the single product rounded half up to whole cents; the loyalty discount therefore applies only to new merchandise, never to used or consigned copies. Fourth, `shipping_cents` is zero when the `channel` is `IN_STORE`; for an `ONLINE` order it is zero when `subtotal_cents` is at least 5000 cents and otherwise a flat 599 cents. Fifth, `total_cents` is `subtotal_cents` minus `discount_cents` plus `shipping_cents`.

### 3.3. Payment, Store Credit, and the Loyalty Program

Payment advances in two operator steps. A `Customer` authorizes payment on their own order, moving `payment_status` from `UNPAID` to `AUTHORIZED`; this is permitted only when the order has at least one `OrderLine` (so its `fulfillment_status` is `RESERVED`) and has not been cancelled. A `StoreClerk` then captures payment, moving `payment_status` from `AUTHORIZED` to `PAID`. At capture the clerk may apply store credit by supplying `credit_applied_cents`; the amount applied must not exceed the buyer's `store_credit_cents` balance, and an attempt to apply more is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402). A successful capture debits `store_credit_cents` by the credit applied, computes and awards the order's `points_earned` to the buyer's `loyalty_points`, and then recomputes the buyer's `loyalty_tier`.

Loyalty points are earned on capture from the order's final `total_cents`. The base award is one point for each whole dollar of `total_cents` — that is, `total_cents` divided by 100 and floored to a whole number. That base is then multiplied by the tier multiplier for the buyer's `loyalty_tier` — 1.0 for `STANDARD`, 1.0 for `SILVER`, and 1.5 for `GOLD` — and the product is floored to a whole number of points. The buyer's `loyalty_points` accumulate over time and are never reset when the tier changes. The `loyalty_tier` itself is derived from the cumulative `loyalty_points`: a customer with at least 500 points is `GOLD`, a customer with at least 100 (but fewer than 500) points is `SILVER`, and anyone below 100 points is `STANDARD`. These boundaries are inclusive at the stated lower bound.

A `StoreClerk` may cancel a paid order (subject to the fulfillment restrictions in §3.4). When an order that has reached `PAID` is cancelled, the capture is compensated exactly: `payment_status` moves to `REFUNDED`, the previously applied `credit_applied_cents` is credited back to the buyer's `store_credit_cents`, the `points_earned` that were awarded are reversed out of `loyalty_points` (with the balance floored at zero should the subtraction go negative), and `loyalty_tier` is recomputed. This conserves store credit and points precisely across a capture-then-cancel cycle.

### 3.4. Fulfillment, Shipping, and Cancellation

Fulfillment depends on the order's `channel` and on payment having settled. For an `ONLINE` order, a `StoreClerk` ships it, advancing `fulfillment_status` from `RESERVED` to `SHIPPED`; this requires the `channel` to be `ONLINE` and the `payment_status` to be `PAID`. For an `IN_STORE` order, a `StoreClerk` completes an in-store pickup, advancing `fulfillment_status` from `RESERVED` to `PICKED_UP`; this requires the `channel` to be `IN_STORE` and the `payment_status` to be `PAID`. In both cases, every copy on the order's lines moves to the terminal `SOLD` status. The requirement that the order's `channel` match the endpoint — `ONLINE` for shipping, `IN_STORE` for pickup — is a state-validity check evaluated before the payment guard: invoking the wrong endpoint for the order's channel (including on an order whose payment has already settled to `PAID`) is rejected with `ERR_INVALID_STATE`. The requirement that payment be `PAID` before shipping or pickup is a cross-entity readiness guard: attempting either, once the channel matches, while payment has not settled is rejected with `ERR_DEPENDENCY_NOT_READY`.

Cancellation releases what an order was holding. A `Customer` (or a `StoreClerk`) cancels an order, moving `fulfillment_status` to the terminal `CANCELLED`, but only while it has not already shipped or been picked up — cancellation is blocked once `fulfillment_status` is `SHIPPED` or `PICKED_UP`. On cancellation, each copy on the order's lines is released back to `AVAILABLE`; however, a released copy that is consigned reverts instead to `ON_DISPLAY` when its owning `Consignment` is still `ACTIVE`, so consigned stock returns to the shelf rather than to general availability. If the cancelled order had already reached `PAID`, the refund compensation described in §3.3 runs as part of the same cancellation.

### 3.5. Exclusive Releases: Allocations, Pre-Orders, and Pickup

An exclusive release is sold from a finite pool. A `Manager` creates an `Allocation` for a product by supplying the `allocation_total` (the fixed number of units the store was allotted, immutable after creation, and required to be a positive integer), the `window_open_at` and `window_close_at` instants that bound the pre-order window, and optionally a `pickup_concurrency` that defaults to 1 and must be at least 1. On creation, the allocation's `available_count` is set equal to `allocation_total`, while `reserved_count` and `committed_count` start at zero. These three counters partition the pool: at all times `available_count` plus `reserved_count` plus `committed_count` equals `allocation_total`. The allocation also references its `product_id`.

A `Customer` places a pre-order by naming their `customer_id`, the `product_id`, the `allocation_id` the unit is drawn from, the requested `pickup_window_start` and `pickup_window_end`, and the `expected_allocation_version` demanded by the concurrency rule in §2.6. A pre-order is permitted only while the logical clock is at or after `window_open_at` and strictly before `window_close_at` — a half-open window — and an attempt outside that window is rejected with `ERR_PREORDER_WINDOW_CLOSED` (HTTP 409). When a unit is available, the pre-order is created in `RESERVED` status, `available_count` is decremented by one, and `reserved_count` is incremented by one. When the pool is exhausted — that is, a reservation would drive `available_count` below zero — the pre-order is instead created in `WAITLISTED` status, holding no unit; because the half-open window guard is evaluated before exhaustion, any request evaluated outside the window is rejected first with `ERR_PREORDER_WINDOW_CLOSED`, so an exhausted pool always waitlists while the window is open and the `ERR_ALLOCATION_EXHAUSTED` (HTTP 409) rejection is not reached in practice. Every pre-order create increments the allocation's `version` by one.

When a pre-order cancellation returns a unit to the pool, the system promotes the earliest-created `WAITLISTED` pre-order on that same `Allocation`, ordered by `created_at` ascending, provided `available_count` is at least 1 after the freeing event; an ordinary order cancellation releases the copy it held but does not touch any allocation counter and therefore triggers no promotion. Promotion moves that pre-order from `WAITLISTED` to `RESERVED`, decrements `available_count` by one, and increments `reserved_count` by one.

Preparing a reserved pre-order for handover is the `StoreClerk`'s job. Readying a pre-order advances it from `RESERVED` to `READY_FOR_PICKUP`; it requires that an `AVAILABLE` `InventoryItem` exists for the product. Readying selects the earliest-created available copy (by `created_at` ascending), records it as the pre-order's `fulfilled_item_id`, moves that copy to `RESERVED`, and sets the copy's `hold_start_at` to `pickup_window_start` and `hold_end_at` to `pickup_window_end`. Pickup-desk capacity is bounded: readying is rejected when the number of already-`READY_FOR_PICKUP` pre-orders on the same allocation whose half-open pickup interval, from `pickup_window_start` up to but not including `pickup_window_end`, overlaps this pre-order's interval would reach the allocation's `pickup_concurrency`; that rejection carries `ERR_PICKUP_CAPACITY_EXCEEDED` (HTTP 409). The requirement that the product's `catalog_status` permit the pre-order to be readied — its `catalog_status` must be either `PRE_ORDER_OPEN` or `PRE_ORDER_CLOSED` — is a cross-entity guard reported with `ERR_DEPENDENCY_NOT_READY` when unmet; the absence of any `AVAILABLE` copy for the product is likewise reported with `ERR_DEPENDENCY_NOT_READY`.

A `StoreClerk` fulfills a pre-order once a copy is held for it — that is, when it is `READY_FOR_PICKUP`, or when it is `RESERVED` with a `fulfilled_item_id` already set — moving it to the terminal `FULFILLED`. Fulfillment moves the held copy to `SOLD`, decrements the allocation's `reserved_count` by one, and increments its `committed_count` by one. A `Customer` may cancel their own pre-order at any time before it is `FULFILLED`. Cancelling a `RESERVED` pre-order moves it to the terminal `CANCELLED`, increments `available_count` by one and decrements `reserved_count` by one, and then triggers the waitlist promotion described above. Cancelling a `WAITLISTED` pre-order simply moves it to `CANCELLED` with no change to any allocation counter, because a waitlisted pre-order holds no unit.

### 3.6. Trading In Media for Credit or Cash

A `Customer` who wants to sell media opens a `TradeIn`, supplying their `customer_id` and optionally a `payout_method` that defaults to `CREDIT`; `CREDIT` grants a store-credit bonus while `CASH` pays face value. A new trade-in starts in `DRAFT` status with `provisional_value_cents` and `final_value_cents` both zero. The seller then adds one or more `TradeInLine` entries, each naming the `trade_in_id` it belongs to, its `format`, the `claimed_grade` the seller asserts, and the `base_value_cents` reference buy value for that title at NEAR-MINT condition (a positive integer). Lines may be added only while the trade-in is still `DRAFT`. A line also has an `inspected_grade`, which is null until a grader sets it.

Submitting the trade-in advances it from `DRAFT` to `SUBMITTED` and requires at least one line; submission computes `provisional_value_cents`. A `Grader` then starts inspection, moving it from `SUBMITTED` to `UNDER_INSPECTION`, and sets the `inspected_grade` on each line to the condition actually found. Approval advances it from `UNDER_INSPECTION` to the terminal `APPROVED` and requires that every line has an `inspected_grade` set; approving before inspection is complete is rejected with `ERR_INSPECTION_INCOMPLETE` (HTTP 422). Approval computes `final_value_cents`, credits the seller's `store_credit_cents` by that amount when the `payout_method` is `CREDIT`, and creates one `AVAILABLE` used `InventoryItem` per line at that line's `inspected_grade`. Because a `TradeInLine` carries no product reference, each created copy is backed by a freshly minted `Product` (of the line's `format`, with empty `artist`/`title`, `catalog_status` `DRAFT`, and `base_price_cents` set to the line's `base_value_cents`), and the copy's `list_price_cents` follows the store-owned item pricing rule of §3.1 against that backing reference price. Alternatively, a `Grader` may reject a trade-in under inspection, moving it to the terminal `REJECTED` with no credit granted.

The trade-in valuation shares one formula across two variants. For each line, a per-line value is the line's `base_value_cents` multiplied by the buy multiplier for the relevant grade — `M` at 0.55, `NM` at 0.50, `VG_PLUS` at 0.40, `VG` at 0.30, `G` at 0.20, `F` at 0.10, and `P` at 0.05 — and this per-line product is rounded half up to whole cents before anything is summed. The trade-in value is the sum of those already-rounded per-line amounts; the rounding order is pinned to round each line first and then sum, because summing first and rounding once could differ by up to one cent per line. The provisional variant, computed at submission, uses each line's `claimed_grade` and never applies the credit bonus, since the bonus is an inspection-verified reward. The final variant, computed at approval, uses each line's `inspected_grade`; when the `payout_method` is `CREDIT`, the summed total is then multiplied by 1.20 (a 20 percent credit bonus) and that result is rounded half up to whole cents. When the payout method is `CASH`, the final value is the summed total with no bonus.

A `Manager` may reverse an approved trade-in, moving it from `APPROVED` to the terminal `REVERSED`. Reversal is permitted only when the seller's `store_credit_cents` is at least the trade-in's `final_value_cents` — so the granted credit can be fully clawed back — and when none of the `InventoryItem` copies created by this trade-in has become `RESERVED` or `SOLD` — a reversal blocked because a created copy is `RESERVED` or `SOLD` is rejected with `ERR_INVALID_STATE`. When the balance is insufficient to claw back the full amount, the reversal is rejected with `ERR_INSUFFICIENT_CREDIT`. A successful reversal debits `store_credit_cents` by `final_value_cents`, conserving credit exactly against the original approval, and voids the copies the trade-in had created.

### 3.7. Consignment: Displaying and Settling Third-Party Stock

The shop also sells stock owned by private consignors. A `StoreClerk` or `Manager` creates a `Consignment` by supplying the `consignor_id`, the asking `list_price_cents` (a positive integer), the `product_id` and `condition_grade` of the item, and optionally a `display_slot_id` together with the `display_start` and `display_end` days of a display booking. Creating a consignment also creates its linked used `InventoryItem` — with `consignment_id` set — in `AVAILABLE` status. A new consignment starts in `DRAFT` status; its `sale_price_cents` is null until it sells, and its `estimated_payout_cents` and `actual_payout_cents` both start at zero.

A `Manager` activates a consignment, moving it from `DRAFT` to `ACTIVE`. When the consignment was created with a `display_slot_id`, activation books that slot and therefore enforces two conditions (a consignment created without a `display_slot_id` skips both slot checks and activates directly). First, the targeted `DisplaySlot` must have `is_active` set to true; booking a retired slot is rejected with `ERR_SLOT_INACTIVE` (HTTP 409). Second, when both `display_start` and `display_end` are present, the requested closed-interval booking from `display_start` through `display_end` must not overlap another `ACTIVE` consignment on the same slot after each existing active booking has been expanded by a two-day buffer on both sides; an overlap under those buffered semantics is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). A successful activation computes `estimated_payout_cents` from the current `list_price_cents`, and moves the linked copy to `ON_DISPLAY`.

The payout to a consignor is what remains after the shop's commission, and commission is tiered marginally on the sale price. The first 5000 cents of the price are charged commission at 30 percent; the slice above 5000 and up to 20000 cents is charged at 20 percent; and any amount above 20000 cents is charged at 10 percent. Each tier's commission is computed on the portion of the price falling inside that tier and rounded half up to whole cents, and the tier commissions are summed in that order — the per-tier rounding is pinned before summation. The payout is the price minus the total commission. The estimated variant, computed at activation, uses `list_price_cents` as the price basis. The actual variant, computed at sale, uses `sale_price_cents` (the post-markdown price) and is what is credited to the consignor.

A `Manager` may mark down an `ACTIVE` consignment by supplying `new_list_price_cents` (a positive integer), which replaces `list_price_cents` and resyncs the linked copy's `list_price_cents`. Importantly, `estimated_payout_cents` is not recomputed on a markdown — it stays pinned at the value computed at activation — so the actual payout at sale legitimately diverges from the estimate. A consignment sells as a side effect of an order that references its copy: when a `StoreClerk` fulfills or ships an order whose line holds the consigned copy, the consignment moves from `ACTIVE` to the terminal `SOLD`. On that sale, `sale_price_cents` is set to the price on that order line (`unit_price_cents`), `actual_payout_cents` is computed from `sale_price_cents`, the consignor's `store_credit_cents` is credited by `actual_payout_cents`, and the display slot is released for reuse. A `Manager` may instead withdraw an `ACTIVE` consignment, moving it to the terminal `WITHDRAWN` — permitted only while the linked copy is not `SOLD` — which returns the copy to `AVAILABLE` and releases the slot. A consignment whose display booking has run past its `display_end` under the logical clock is swept to the terminal `EXPIRED` when it is read (either individually or within a list), likewise returning the copy to `AVAILABLE` (unless that copy is already `SOLD`) and releasing the slot.

A `Manager` provisions the shelf itself by creating a `DisplaySlot` with a unique `slot_label` and an optional `is_active` flag that defaults to true; setting `is_active` to false retires a slot so it can no longer be booked.

### 3.8. Grading Disputes and the Regrade Cascade

When a buyer believes a used copy was graded incorrectly, they raise a `GradingDispute`, naming the `inventory_item_id`, their own `customer_id`, and the `claimed_grade` they believe is correct. A dispute opens in `OPEN` status and carries a `resolution_grade` that is null until it is resolved by regrade. A `Grader` starts review, moving the dispute from `OPEN` to `UNDER_REVIEW`, but only when the disputed copy's `is_used` is true — the process applies to second-hand stock. While under review, the grader may request more information, moving the dispute to `NEEDS_INFO`; the buyer then provides information, moving it back to `UNDER_REVIEW`. This revision loop between `NEEDS_INFO` and `UNDER_REVIEW` may repeat any number of times.

From `UNDER_REVIEW`, a `Grader` may take one of three paths, each with equal standing. Resolving by regrade requires that a `resolution_grade` is provided and moves the dispute to the terminal `RESOLVED_REGRADE`, applying the regrade cascade described below. Resolving in the shop's favor moves the dispute to the terminal `RESOLVED_UPHELD` with no grade or price change. Escalating moves the dispute to `ESCALATED`. An escalated dispute is handled by a `Manager`, who may likewise resolve it by regrade (supplying `resolution_grade`, running the identical cascade to reach `RESOLVED_REGRADE`) or uphold it to reach `RESOLVED_UPHELD`.

The regrade cascade resolves atomically in three steps. First, the disputed `InventoryItem`'s `condition_grade` is set to the `resolution_grade`. Second, that copy's `list_price_cents` is recomputed under the item pricing rule of §3.1 at the new grade. Third, if that copy sits on an `OrderLine` whose order has a `fulfillment_status` of `PENDING` or `RESERVED` — that is, an order still open and not yet shipped, picked up, or cancelled — the line's `unit_price_cents` is resynced to the copy's new price and the order's `subtotal_cents`, `discount_cents`, `shipping_cents`, and `total_cents` are recomputed under the order-total rule of §3.2. A regrade on a copy that is not on any open order stops after repricing the copy.

### 3.9. Special Orders

A `Customer` may request a title the shop does not stock through a `SpecialOrder`, supplying their `customer_id`, a free-text `description` of the request, an optional `product_id` when the requested title already exists in the catalog, and an optional `deposit_cents` that defaults to zero. The deposit is non-refundable. A special order opens in `REQUESTED` status. A `StoreClerk` starts sourcing, moving it to `SOURCING`, then marks it arrived, moving it to `ARRIVED`; marking arrival creates one `AVAILABLE` `InventoryItem` for the `product_id` when a product was named, minted as a new (`is_used` false) copy graded `NM`. Finally the clerk fulfills the special order, moving it to the terminal `FULFILLED`. A `Customer` may cancel their own special order while it is still `REQUESTED` or `SOURCING`, moving it to the terminal `CANCELLED`; in either case the `deposit_cents` is forfeited.

### 3.10. Operator and Test-Driving Capabilities

A `Manager` may correct or seed a customer's balance through a store-credit adjustment that supplies a `delta_cents` and a `reason`; the adjustment adds `delta_cents` to the customer's `store_credit_cents`, which must remain at or above zero. Two capabilities exist purely to drive the system deterministically in testing. An administrative clock capability sets the server's logical clock to a supplied `to_iso8601` instant; the clock's startup default is 2026-03-01T00:00:00Z, and before any call it reads exactly that default and never falls back to wall-clock time. A second administrative capability directly adds a `delta_points` amount to a customer's `loyalty_points` (flooring the resulting balance at zero if a negative delta would drive it below zero) and recomputes their `loyalty_tier`, letting a target tier be reached without replaying many paid orders.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. All error responses use the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /shop/customers | Register a customer | Anonymous |
| GET | /shop/customers/{id} | Read a customer (balances, tier) | Customer, StoreClerk, Manager |
| POST | /shop/customers/{id}/credit-adjustments | Operator adjustment of store credit | Manager |
| POST | /shop/products | Create a catalog product | Manager |
| GET | /shop/products/{id} | Read a product | Anonymous, Customer, StoreClerk, Manager |
| GET | /shop/products | List/catalog products | Anonymous, Customer, StoreClerk, Manager |
| POST | /shop/products/{id}/list | List a product for sale | Manager |
| POST | /shop/products/{id}/open-preorders | Open pre-orders for an exclusive | Manager |
| POST | /shop/products/{id}/discontinue | Discontinue a product | Manager |
| POST | /shop/products/{id}/allocations | Create the finite allocation pool | Manager |
| GET | /shop/allocations/{id} | Read an allocation (counts + version) | Customer, StoreClerk, Manager |
| GET | /shop/products/{id}/allocations | List allocations of a product | Customer, StoreClerk, Manager |
| POST | /shop/inventory-items | Add a physical copy to stock | StoreClerk, Manager |
| GET | /shop/inventory-items/{id} | Read an inventory item | Anonymous, Customer, StoreClerk, Manager |
| GET | /shop/inventory-items | List inventory items | Anonymous, Customer, StoreClerk, Manager |
| POST | /shop/orders | Open an empty order | Customer |
| GET | /shop/orders/{id} | Read an order with computed totals | Customer, StoreClerk, Manager |
| GET | /shop/orders | List orders | Customer, StoreClerk, Manager |
| POST | /shop/orders/{id}/lines | Add a line (reserves the item) | Customer |
| GET | /shop/orders/{id}/lines | List lines of an order | Customer, StoreClerk, Manager |
| GET | /shop/order-lines/{id} | Read a single order line | Customer, StoreClerk, Manager |
| GET | /shop/order-lines | List order lines | StoreClerk, Manager |
| POST | /shop/orders/{id}/authorize-payment | Authorize payment | Customer |
| POST | /shop/orders/{id}/capture-payment | Capture payment; apply credit; award points | StoreClerk |
| POST | /shop/orders/{id}/ship | Ship an online order | StoreClerk |
| POST | /shop/orders/{id}/fulfill | Complete an in-store pickup | StoreClerk |
| POST | /shop/orders/{id}/cancel | Cancel an order | Customer, StoreClerk |
| POST | /shop/trade-ins | Open a trade-in draft | Customer |
| GET | /shop/trade-ins/{id} | Read a trade-in with provisional/final values | Customer, Grader, Manager |
| GET | /shop/trade-ins | List trade-ins | Customer, Grader, Manager |
| POST | /shop/trade-ins/{id}/lines | Add a line to a draft trade-in | Customer |
| GET | /shop/trade-ins/{id}/lines | List lines of a trade-in | Customer, Grader, Manager |
| POST | /shop/trade-ins/{id}/submit | Submit; compute provisional value | Customer |
| POST | /shop/trade-ins/{id}/start-inspection | Start inspection | Grader |
| PATCH | /shop/trade-in-lines/{id} | Set inspected grade during inspection | Grader |
| POST | /shop/trade-ins/{id}/approve | Approve; final value; credit; create used items | Grader |
| POST | /shop/trade-ins/{id}/reject | Reject a trade-in | Grader |
| POST | /shop/trade-ins/{id}/reverse | Reverse; claw back credit; void items | Manager |
| POST | /shop/pre-orders | Reserve a unit of an exclusive (OCC); waitlist if exhausted | Customer |
| GET | /shop/pre-orders/{id} | Read a pre-order | Customer, StoreClerk, Manager |
| GET | /shop/pre-orders | List pre-orders | Customer, StoreClerk, Manager |
| POST | /shop/pre-orders/{id}/ready | Ready a pre-order; hold a copy for pickup | StoreClerk |
| POST | /shop/pre-orders/{id}/fulfill | Fulfill; commit the unit | StoreClerk |
| POST | /shop/pre-orders/{id}/cancel | Cancel; release unit; promote waitlist | Customer |
| POST | /shop/display-slots | Create a display slot | Manager |
| GET | /shop/display-slots/{id} | Read a display slot | StoreClerk, Manager |
| POST | /shop/consignments | Create a consignment draft (with linked item) | StoreClerk, Manager |
| GET | /shop/consignments/{id} | Read a consignment with payout estimates | Customer, StoreClerk, Manager |
| GET | /shop/consignments | List consignments | Customer, StoreClerk, Manager |
| POST | /shop/consignments/{id}/activate | Activate; book slot; item on display; estimated payout | Manager |
| POST | /shop/consignments/{id}/markdown | Mark down an active consignment's list price | Manager |
| POST | /shop/consignments/{id}/withdraw | Withdraw; release slot; item available | Manager |
| POST | /shop/grading-disputes | Raise a grading dispute on a used copy | Customer |
| GET | /shop/grading-disputes/{id} | Read a dispute | Customer, Grader, Manager |
| GET | /shop/grading-disputes | List disputes | Customer, Grader, Manager |
| POST | /shop/grading-disputes/{id}/start-review | Start review | Grader |
| POST | /shop/grading-disputes/{id}/request-info | Request more information | Grader |
| POST | /shop/grading-disputes/{id}/provide-info | Provide requested information | Customer |
| POST | /shop/grading-disputes/{id}/escalate | Escalate a dispute | Grader |
| POST | /shop/grading-disputes/{id}/resolve-regrade | Resolve by regrade; cascade price/order resync | Grader, Manager |
| POST | /shop/grading-disputes/{id}/resolve-uphold | Resolve upholding the grade; no change | Grader, Manager |
| POST | /shop/special-orders | Request a special order (deposit non-refundable) | Customer |
| GET | /shop/special-orders/{id} | Read a special order | Customer, StoreClerk, Manager |
| GET | /shop/special-orders | List special orders | Customer, StoreClerk, Manager |
| POST | /shop/special-orders/{id}/start-sourcing | Start sourcing | StoreClerk |
| POST | /shop/special-orders/{id}/mark-arrived | Mark arrived; create item if product set | StoreClerk |
| POST | /shop/special-orders/{id}/fulfill | Fulfill a special order | StoreClerk |
| POST | /shop/special-orders/{id}/cancel | Cancel; forfeit deposit | Customer |
| POST | /shop/_clock/set_current_utc | Set the server logical clock | Manager |
| POST | /shop/_loyalty/adjust-points | Adjust a customer's loyalty points and recompute tier | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_DEPENDENCY_NOT_READY | 409 |
| ERR_INVALID_GRADE_FOR_NEW | 422 |
| ERR_INSPECTION_INCOMPLETE | 422 |
| ERR_PREORDER_WINDOW_CLOSED | 409 |
| ERR_PICKUP_CAPACITY_EXCEEDED | 409 |
| ERR_ALLOCATION_EXHAUSTED | 409 |
| ERR_SLOT_OVERLAP | 409 |
| ERR_INSUFFICIENT_CREDIT | 402 |
| ERR_STALE_VERSION | 412 |
| ERR_SLOT_INACTIVE | 409 |
