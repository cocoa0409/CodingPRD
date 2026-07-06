# Toy & Hobby Store API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a specialty toy-and-hobby retailer that must reconcile several overlapping concerns at once: a safety-conscious product catalog with age-grade labeling and recall management, scarce seasonal and exclusive inventory that has to be allocated across stores, and a customer-facing loyalty program that spans ordinary purchases, layaway plans, special orders, gift registries, and demonstration events. The retailer sells through both buy-online-pickup-in-store (BOPIS) and ship-from-store fulfillment, so the same order pipeline must serve two logistics models while keeping physical stock, reservations, and safety holds perfectly conserved.

The central challenge the platform solves is consistency under pressure. A single recall can ripple through inventory, open orders, and pricing; a fulfillment can simultaneously consume a store's seasonal allocation, credit loyalty points, and advance a gift-registry counter; a return can restock units and claw back points earned earlier. Because these operations touch multiple records, the service treats every quantity as a conserved ledger and every derived figure as something recomputed from primary facts rather than trusted blindly.

This specification is written for the engineers who will implement the API. It describes the domain rules first and the HTTP surface second. Where a figure is derived, the exact arithmetic and rounding are given so that two independent implementations converge on identical results.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing or its value is not recognized, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

There are five roles, spelled exactly as follows: `CatalogAdmin`, `StoreManager`, `StoreAssociate`, `Customer`, and `Any`. `CatalogAdmin` curates the product catalog, safety labeling, recalls, and the logical clock. `StoreManager` owns allocations, special-order quotes, and return approvals. `StoreAssociate` handles front-line operations — inventory receipt, customer creation, order fulfillment steps, layaway, special-order intake and conversion, demo events, and return intake. `Customer` is a loyalty member acting on their own resources. `Any` denotes read access granted to all authenticated roles for every retrieval endpoint.

For `CatalogAdmin`, `StoreManager`, `StoreAssociate`, and `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept it but does not compare it to any record's `id`. For `Customer`, the identity is entity-backed: `X-User-ID` is the `id` of the acting `Customer`. Ownership is enforced on the mutating and acting operations a `Customer` invokes — creating or acting on an order, adding an order line, submitting/paying/cancelling an order, paying a layaway, creating a registry or adding a registry item or closing it, registering for an event, and approving a special order — where a target or body `customer_id` that does not equal the requesting `Customer`'s `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE`. Retrieval endpoints are `Any`-authorized and do not apply this ownership check, so a `Customer` may read another customer's resource; the sole read-time exception is that the `QUOTED`→`CUSTOMER_REVIEW` auto-transition on reading a special order fires only when the reader is the owning `Customer`. A `StoreAssociate`, by contrast, may act on any customer's order or layaway payment on their behalf.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, while a `limit` or `offset` that is not a valid integer is rejected with `ERR_VALIDATION`. `offset` defaults to 0, is clamped up to 0 if negative, and has no upper bound beyond the available result set. Results are ordered by `created_at` ascending, with ties broken by ascending creation sequence (insertion order) — a meaningful tiebreak because the logical clock (§3.14) can stamp many records with an identical `created_at`. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when unreturned records remain beyond the current page).

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` that is a UUID with no type prefix and serves as identity only. Most resources also carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 and increases by exactly one on every mutation of the resource. `updated_at` is refreshed on every mutation, including mutations caused by cascades originating elsewhere.

`RegistryItem` is the single exception. It carries only `id` and `created_at`; it has no `updated_at` and no `version`, and it is never versioned or timestamp-refreshed after creation.

### 2.5. Money, Points, and Rounding

All monetary amounts are integers denominated in cents (`msrp_cents`, `unit_price_cents`, `extended_cents`, `subtotal_cents`, `discount_cents`, `total_cents`, `amount_paid_cents`, `total_cents` and `paid_cents` on layaways, `gross_refund_cents`, `restocking_fee_cents`, `net_refund_cents`, `deposit_cents`, and `quoted_unit_price_cents`). Loyalty points are integers. Whenever a computation would produce a fractional cent or a fractional point, the result is rounded down to the nearest whole unit (floor). Rounding is applied at the points the calculation rules specify — in particular, discounts are floored per line and only then summed, never summed and then floored. All conserved quantities (inventory units, allocation units) are non-negative integers.

### 2.6. Optimistic Concurrency on Special-Order Quotes

Issuing a quote against a special order is guarded by optimistic concurrency control. A quote request must include `expected_special_order_version`, which must carry the `version` of the target `SpecialOrder` that the manager last observed. Because a new quote legitimately supersedes the prior one — replacing `quoted_unit_price_cents` and `deposit_cents` and advancing `quote_revision` — a manager working from a stale view would otherwise silently overwrite a newer quote. If `expected_special_order_version` does not equal the special order's current `version`, the quote is rejected with `ERR_STALE_SPECIAL_ORDER_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.7. Parallel State Dimensions and Cascade Consistency

Several entities track two independent state dimensions at once. A `Product` has a lifecycle `status` (`DRAFT`, `ACTIVE`, `DISCONTINUED`) and a separate `recall_status` (`CLEARED`, `RECALLED`) that move independently. An `Order` has a `fulfillment_status` (`OPEN`, `SUBMITTED`, `READY`, `FULFILLED`, `CANCELLED`) and an independent `payment_status` (`UNPAID`, `PARTIALLY_PAID`, `PAID`). When any operation mutates an entity — directly or as the downstream target of a cascade — that entity's `updated_at` is refreshed and its `version` is incremented. Cascades that touch inventory, allocations, order lines, and orders are described in §3; the governing principle is that a derived field is always recomputed from its primary inputs after any change, never left stale.

### 2.8. Nested and Filtered Retrieval

Path parameters are validated left to right. For a nested path, each identifier segment is checked for existence in order, and the first unresolved identifier produces the corresponding not-found error (for example `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REGISTRY_NOT_FOUND`, and their siblings listed in §5). List endpoints support reverse-reachability filtering by their natural foreign keys — for instance inventory and allocations by `product_id` and `store_id`, orders by `customer_id` and `store_id`, order lines by `order_id` and `product_id`, layaways by `customer_id` and `order_id`, special orders by `customer_id`, `product_id`, and `converted_order_id`, recalls and events by `product_id` (events also by `store_id`), registries by `customer_id`, registry items by `registry_id` and `product_id`, returns by `order_id`, and products by `category` and `sku`.

### 2.9. Conserved Inventory and Allocation Ledgers

Each `InventoryItem` binds a `product_id` to a `store_id` and maintains four quantities. `on_hand_qty` is the total physical units held. `reserved_qty` counts units held by open or submitted order lines. `quarantined_qty` counts units frozen by an active recall. `available_qty` is the derived remainder, computed as `on_hand_qty` minus `reserved_qty` minus `quarantined_qty`, and it is recomputed on every reserve, release, receive, or quarantine mutation. The invariant `on_hand_qty` equals `available_qty` plus `reserved_qty` plus `quarantined_qty` holds at all times, and `available_qty` is never negative.

Each `Allocation` binds a `product_id` and `store_id` to a scarce seasonal pool. `allocated_qty` is the units granted to the store; `committed_qty` counts units committed to fulfilled orders and converted special orders; `released_qty` records units handed back on release. `available_alloc_qty` is derived as `allocated_qty` minus `committed_qty`. The invariant is that `allocated_qty` equals `committed_qty` plus `available_alloc_qty`, plus `released_qty` once the allocation has been released.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: (1) presence and validity of the user-context headers; (2) role authorization, including the `Customer` ownership check comparing the resource's `customer_id` to `X-User-ID`; (3) existence of every path and body identifier, validated left to right; (4) the target resource being in a valid state for the requested transition; (5) the age-grade safety gate; (6) the recall safety gate; (7) temporal constraints (event overlap, allocation-window overlap, return window); (8) cross-entity referential links (allocation present for conversion, active registry for item add); (9) quantitative constraints (inventory, allocation, event capacity); (10) fiscal constraints (order and layaway overpayment); (11) the special-order stale-version check; and (12) uniqueness constraints (`sku`, `email`). A malformed body, a missing required field, or a wrong type is rejected with `ERR_VALIDATION` as part of the earliest structural evaluation.

## 3. Business Logic & Workflows

### 3.1. Catalog, Safety Labeling, and Product Lifecycle

A `CatalogAdmin` seeds the catalog by creating a product, supplying its unique `sku`, its `name`, its `category` (one of `BOARD_GAME`, `MODEL_KIT`, `PLUSH`, `ACTION_FIGURE`, or `CRAFT_KIT`), its `age_grade_min_months` (the minimum recipient age in months for safe use, at least 0), its `safety_labels` (an array — possibly empty — each element drawn from `CHOKING_HAZARD`, `SMALL_PARTS`, `FLAMMABLE`, `BATTERY`, and `NONE`, with no further consistency check), and its `msrp_cents` (an integer of at least 0). The optional `is_exclusive` flag defaults to false and marks allocation-only items that are never eligible for a loyalty discount. A newly created product begins in `DRAFT` status with `recall_status` of `CLEARED`. If the submitted `sku` already belongs to another product, creation is rejected with `ERR_DUPLICATE_SKU`. Products may be listed and filtered by `category` and `sku`, or fetched individually.

The admin may amend `name`, `age_grade_min_months`, `safety_labels`, `msrp_cents`, and `is_exclusive` on an existing product; each such edit increments `version`. Activating a product moves it from `DRAFT` to `ACTIVE`, and this is permitted only while the product is in `DRAFT`. Discontinuing a product moves it from `ACTIVE` to `DISCONTINUED`, permitted only while it is `ACTIVE`; `DISCONTINUED` is terminal. An attempt to transition from an ineligible state is rejected with `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` when the resource has already reached a terminal state).

### 3.2. Recalls and Their Cascades

A recall is opened by a `CatalogAdmin` against a product, carrying a `severity` of either `ADVISORY` or `MANDATORY` and a free-text `reason`; it begins in `OPEN` status. Issuing a recall advances it from `OPEN` to `ISSUED` and is allowed only when the recall is `OPEN` (otherwise `ERR_INVALID_STATE`) and the referenced product is not in `DRAFT` (a `DRAFT` product also yields `ERR_INVALID_STATE`). Issuing sets the product's `recall_status` to `RECALLED`, which itself is permitted only while `recall_status` was `CLEARED`. The issue and resolve capabilities share one endpoint distinguished by a `resolve` boolean flag that defaults to false when absent.

The move to `RECALLED` fires a quarantine cascade across inventory. For every `InventoryItem` whose `product_id` matches the recalled product, the currently available and reserved units are frozen: `quarantined_qty` increases by the sum of that item's `available_qty` and `reserved_qty`, and both `available_qty` and `reserved_qty` are set to 0. `on_hand_qty` is unchanged, and each affected item's `updated_at` and `version` are bumped. Quarantining reserved units in turn voids the order lines that were holding them: every `ACTIVE` line on the recalled product transitions to `VOIDED` by system action. Each such void triggers a recompute of its parent order's `subtotal_cents`, `discount_cents`, and `total_cents` excluding voided lines, and if the order thereby has no remaining `ACTIVE` line and is not already `CANCELLED` or `FULFILLED`, that order's `fulfillment_status` moves to `CANCELLED`. This void-and-recompute cascade fires whatever the order's current `fulfillment_status`, and the voided lines release no inventory reservation because the units they held were just quarantined.

Resolution reuses the issue capability with a `resolve` flag set to true. It advances the recall from `ISSUED` to `RESOLVED` (terminal), permitted only while the recall is `ISSUED` (otherwise `ERR_INVALID_STATE`), and sets the product's `recall_status` back to `CLEARED`, permitted only while it was `RECALLED`. On clearing, each affected inventory item keeps its `on_hand_qty`, sets `quarantined_qty` to 0, and recomputes `available_qty` as `on_hand_qty` minus `reserved_qty`.

### 3.3. Inventory Receipt and Allocation Pools

Stores themselves are created by a `CatalogAdmin` with a `name`, a two-letter US `state_code`, and an optional `event_buffer_minutes` cleanup gap. Only presence and string type are enforced on `state_code`; the value is stored verbatim without any length or membership check, so it is not rejected for failing the two-letter US convention. A `StoreAssociate` creates an inventory item for a `product_id` and `store_id` with an opening `on_hand_qty`; on creation `reserved_qty` and `quarantined_qty` are 0 and `available_qty` equals `on_hand_qty`. Receiving stock adds the supplied `qty` to `on_hand_qty` and recomputes `available_qty`.

A `StoreManager` creates a seasonal or exclusive allocation for a `product_id` and `store_id`, supplying `allocated_qty` (at least 1) and a window bounded by `season_start` (inclusive) and `season_end` (exclusive). Allocations begin `ACTIVE` with `committed_qty` and `released_qty` at 0. The season window is half-open on `[season_start, season_end)`; if it overlaps the window of another non-`RELEASED` allocation (i.e. `ACTIVE` or `EXHAUSTED`) for the same product and store, creation is rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`; a `RELEASED` allocation's window never blocks a new one. As orders consume allocated units the pool shrinks, and when `available_alloc_qty` reaches 0 the allocation automatically moves to `EXHAUSTED`. A manager may release an allocation from either `ACTIVE` or `EXHAUSTED` to `RELEASED` (terminal); releasing an already-`RELEASED` allocation is refused with `ERR_ALREADY_TERMINAL`. Releasing sets `released_qty` to the remaining `available_alloc_qty` and drives `available_alloc_qty` to 0.

### 3.4. Customers and the Loyalty Ledger

A `StoreAssociate` enrolls a loyalty customer with a `name` and a unique `email`; a duplicate email is rejected with `ERR_DUPLICATE_EMAIL`. A new customer starts with `lifetime_points` and `points_redeemed` at 0 and `loyalty_tier` of `BRONZE`. The `points_balance` is a conserved figure equal to `lifetime_points` minus `points_redeemed` and is recomputed whenever either component changes. The tier is derived purely from `lifetime_points`: a customer is `GOLD` once lifetime points reach at least 5000, `SILVER` once they reach at least 1000 (but below 5000), and `BRONZE` otherwise. Over any fulfill-then-full-return pair, `points_balance` returns to its pre-fulfillment value.

### 3.5. Building an Order

A `Customer` (acting on their own `customer_id`) or a `StoreAssociate` opens an order by supplying `customer_id`, `store_id`, and `fulfillment_type` (`BOPIS` or `SHIP_FROM_STORE`). The order begins with `fulfillment_status` of `OPEN`, `payment_status` of `UNPAID`, and `pricing_variant` of `PROVISIONAL`.

Lines are then added to an open order. Each line names a `product_id`, a `qty` (at least 1), and the `recipient_age_months` for whom the item is intended. Adding a line enforces two safety gates. The age-grade gate passes only when `recipient_age_months` is greater than or equal to the product's `age_grade_min_months` — the boundary is inclusive, so an exact match passes — and otherwise fails with `ERR_AGE_GRADE_VIOLATION`. The recall gate requires the product's `recall_status` to be `CLEARED`; a recalled product is refused with `ERR_PRODUCT_RECALLED`. A line may be added only while the order's `fulfillment_status` is `OPEN`; otherwise `ERR_ORDER_NOT_OPEN` is returned. When the line is accepted, `unit_price_cents` is snapshotted from the product's current `msrp_cents`, the line's `status` is `ACTIVE`, and the requested units are reserved on the matching inventory item: `reserved_qty` increases by `qty` and `available_qty` decreases by `qty`. If no inventory item exists for the product at the order's store, or the matching item does not have `available_qty` of at least `qty`, the add is rejected with `ERR_INSUFFICIENT_INVENTORY` (a missing inventory item is treated as insufficient inventory, not a not-found error). Order lines may be listed and filtered by `order_id` and `product_id` or fetched individually.

### 3.6. Provisional and Final Pricing

Order pricing is computed over `ACTIVE` lines only; `VOIDED` and `RETURNED` lines are excluded. For each active line, `extended_cents` is `unit_price_cents` multiplied by `qty`. The per-line loyalty discount depends on the customer's tier: `BRONZE` earns no discount, `SILVER` earns 5 percent, and `GOLD` earns 10 percent. For a non-exclusive product, `line_discount_cents` is the product of `extended_cents` and the tier percentage, rounded down to whole cents; for an exclusive product (`is_exclusive` true) the line discount is 0. The order's `subtotal_cents` is the sum of `extended_cents` across active lines, `discount_cents` is the sum of the already-floored per-line discounts (floored per line, then summed), and `total_cents` is `subtotal_cents` minus `discount_cents`.

Submitting an order moves it from `OPEN` to `SUBMITTED` and computes provisional pricing; it requires the order to be `OPEN` (else `ERR_ORDER_NOT_OPEN`) with at least one `ACTIVE` line (else `ERR_INVALID_STATE`). Provisional pricing reflects the tier and lines as of submit and is recomputed if lines change before the order becomes ready; `pricing_variant` stays `PROVISIONAL`. When the order is marked ready, `pricing_variant` locks to `FINAL` and the discount is recomputed against the customer's `loyalty_tier` as read at mark-ready time — so if the tier changed between submit and mark-ready, the final discount can differ from the provisional one. At submit time an implementation may also expose a provisional estimate of points that would accrue on the projected total; this estimate is informational only and is never persisted to `lifetime_points`.

### 3.7. Payment, Readiness, and Fulfillment

Payments may be applied to an order by the owning `Customer` or a `StoreAssociate` via an `amount_cents` payment (an integer of at least 1), as long as the order is not `CANCELLED` (a payment against a `CANCELLED` order is refused with `ERR_INVALID_STATE`). Each payment adds `amount_cents` to `amount_paid_cents`. While the cumulative `amount_paid_cents` remains below `total_cents`, `payment_status` becomes `PARTIALLY_PAID`; once it reaches or exceeds `total_cents`, `payment_status` becomes `PAID`. A payment that would push `amount_paid_cents` beyond `total_cents` — that is, beyond the remaining balance — is rejected with `ERR_OVERPAYMENT`.

Marking an order ready advances it from `SUBMITTED` to `READY` and is performed by a `StoreAssociate`. Beyond requiring the order to be `SUBMITTED` (else `ERR_INVALID_STATE`), it re-checks the recall gate across the order: every `ACTIVE` line's product must have `recall_status` of `CLEARED`, else the request is refused with `ERR_PRODUCT_RECALLED`. The final pricing lock described above happens here.

Fulfillment advances a `READY` order to `FULFILLED` and requires `payment_status` of `PAID` (an order not yet ready is refused with `ERR_ORDER_NOT_READY`; a ready but unpaid order with `ERR_ORDER_NOT_PAID`). Fulfillment applies several coordinated effects. For each `ACTIVE` line, the matching inventory item's `on_hand_qty` and `reserved_qty` are each reduced by the line's `qty`. If an `ACTIVE` allocation exists for that line's product and store, its `committed_qty` increases by `qty` and `available_alloc_qty` decreases by `qty`, and the allocation flips to `EXHAUSTED` when `available_alloc_qty` reaches 0; the first such `ACTIVE` allocation is used and fulfillment does not verify that the allocation has enough remaining units. The customer is credited loyalty points computed on the `FINAL` total (see §3.8). Finally, for any fulfilled line whose product matches a registry item in any `ACTIVE` registry belonging to the customer, that item's `purchased_qty` is incremented by the fulfilled units regardless of the item's `desired_qty`.

### 3.8. Loyalty Point Accrual and Reversal

Points are earned at fulfillment on the final order total. The base is `total_cents` divided by 100 and rounded down to a whole number. That base is multiplied by the tier multiplier — 1.0 for `BRONZE`, 1.5 for `SILVER`, and 2.0 for `GOLD` — and the product is rounded down to whole points to give the points earned, which are added to the customer's `lifetime_points`. Only lines that were still `ACTIVE` at fulfillment contribute, since the total excludes any lines voided beforehand.

When a return is later approved, points are reversed proportionally as a compensating adjustment rather than by editing `lifetime_points`. The reversal takes the returned gross amount multiplied by the tier multiplier that was captured on the order at fulfillment, then divided by 100, rounded down to whole points (i.e. `floor(gross_refund_cents * mult / 100)` evaluated as `(gross * num) // (den * 100)`), and adds that figure to the customer's `points_redeemed`. The captured multiplier is the customer's tier multiplier as read at the end of fulfillment, after the fulfillment's own point credit has been applied; in the ordinary case where that credit does not cross a tier boundary this equals the tier used to earn the points. Because `points_balance` is `lifetime_points` minus `points_redeemed`, a full return of a fulfilled order returns the balance to its pre-fulfillment value.

### 3.9. Layaway Plans

A `StoreAssociate` opens a layaway plan for a `customer_id` with a `total_cents` (at least 1) and an `installment_count` (at least 1), optionally linked to an `order_id`. The plan begins `ACTIVE` with `paid_cents` at 0. Its `installment_schedule_cents` is computed at creation: the base installment is `total_cents` divided by `installment_count` rounded down, every installment is set to that base, and the leftover remainder — `total_cents` minus the base times `installment_count` — is added onto the final installment so the schedule sums exactly to `total_cents`.

Installment payments may be applied by the owning `Customer` or a `StoreAssociate` and add `amount_cents` to `paid_cents`, with `remaining_cents` recomputed as `total_cents` minus `paid_cents`. When cumulative `paid_cents` reaches or exceeds `total_cents`, the plan moves from `ACTIVE` to `PAID_IN_FULL` and `remaining_cents` is driven to 0. A payment exceeding `remaining_cents` is rejected with `ERR_LAYAWAY_OVERPAYMENT`, and a payment against a plan not in `ACTIVE` state is refused with `ERR_LAYAWAY_NOT_ACTIVE`. A `StoreAssociate` may cancel an `ACTIVE` plan, moving it to `CANCELLED` (terminal); cancelling a plan not in `ACTIVE` state is refused with `ERR_LAYAWAY_NOT_ACTIVE`.

### 3.10. Special Orders and Quotes

A `StoreAssociate` records a special order for a `customer_id` and `product_id` with a `requested_qty` (at least 1); it begins in `DRAFT` with `quote_revision` at 0. A `StoreManager` issues a quote, supplying `unit_price_cents`, `deposit_cents`, and the `expected_special_order_version` for concurrency control. Quoting is permitted from `DRAFT`, `QUOTED`, or `CUSTOMER_REVIEW` (any other state is rejected with `ERR_INVALID_STATE`, checked before the stale-version comparison), and re-quoting from `QUOTED` is a deliberate self-cycle that supersedes the prior quote. A successful quote sets `quoted_unit_price_cents` and `deposit_cents`, increments `quote_revision`, increments `version`, and leaves the special order in `QUOTED`. The stale-version rejection is described in §2.6. When a customer first reads a quoted order, it auto-transitions from `QUOTED` to `CUSTOMER_REVIEW`.

The owning `Customer` approves a quote, moving the order from `QUOTED` or `CUSTOMER_REVIEW` to `APPROVED`; approval from any other state is rejected with `ERR_INVALID_STATE`. A `StoreAssociate` then converts an `APPROVED` special order; conversion requires that at least one `ACTIVE` allocation for the product exists — matched by `product_id` alone, since a special order carries no `store_id` — (otherwise `ERR_NO_ALLOCATION`) and that some such allocation has `available_alloc_qty` of at least `requested_qty` (otherwise `ERR_INSUFFICIENT_ALLOCATION`). Attempting to convert an order not in `APPROVED` yields `ERR_SPECIAL_ORDER_NOT_APPROVED`. When more than one `ACTIVE` allocation exists for the product, the eligible allocation with sufficient `available_alloc_qty` is chosen in ascending `created_at` then creation-sequence order; if no single `ACTIVE` allocation has `available_alloc_qty` of at least `requested_qty`, the request is rejected with `ERR_INSUFFICIENT_ALLOCATION` (allocations are not combined). Conversion creates an `Order` on the chosen allocation's `store_id`, with `fulfillment_type` of `BOPIS`, a single `ACTIVE` line whose `qty` is `requested_qty`, `recipient_age_months` of 0, and `unit_price_cents` snapshotted from the special order's `quoted_unit_price_cents`; this created line performs no inventory reservation and applies no safety or inventory gate. Conversion records that order's id in `converted_order_id`, moves the special order to `CONVERTED` (terminal), and increases the allocation's `committed_qty` by `requested_qty` (flipping the allocation to `EXHAUSTED` if `available_alloc_qty` thereby reaches 0). The response body of a successful conversion is the newly created `Order`, not the special order, and it is returned with HTTP 200 (the conversion is treated as a state transition rather than a resource creation). Special orders may be listed and filtered by `customer_id`, `product_id`, and `converted_order_id`. `CANCELLED` is the other terminal state and is never re-quoted afterward.

### 3.11. Order Cancellation and Cascades

An order may be cancelled by the owning `Customer` or a `StoreAssociate` while its `fulfillment_status` is `OPEN`, `SUBMITTED`, or `READY`, moving it to `CANCELLED` (terminal). Cancellation cascades: every `ACTIVE` line becomes `VOIDED`. Each voided line releases its reservation on the matching inventory item — `reserved_qty` decreases by the line's `qty` and `available_qty` increases by the same `qty`. Allocations are untouched by cancellation, because allocation commitment occurs only at fulfillment and fulfilled orders are not cancellable. As lines void, the order's `subtotal_cents`, `discount_cents`, and `total_cents` are recomputed over the remaining `ACTIVE` lines.

### 3.12. Demo Events and Gift Registries

A `StoreAssociate` schedules a demo event at a `store_id` featuring a `product_id`, bounded by `start_at` (inclusive) and `end_at` (inclusive), with a `capacity` (at least 1). The event begins `SCHEDULED` with `registered_count` at 0 and an empty `registered_customer_ids`. Scheduling must not collide with another `SCHEDULED` event at the same store: the new event's closed interval, expanded by the store's `event_buffer_minutes` cleanup gap (which defaults to 30 when the store is created without one), must not overlap an existing event; a collision is rejected with `ERR_EVENT_OVERLAP`. A `Customer` registers for a scheduled event by supplying their `customer_id`; registration is refused unless the event is `SCHEDULED` (else `ERR_INVALID_STATE`), then appends the id to `registered_customer_ids` and increments `registered_count`. Registration is refused if the event is full — `registered_count` has reached `capacity` — with `ERR_EVENT_FULL`, or if the same customer is already registered, with `ERR_DUPLICATE_EVENT_REGISTRATION`.

A `Customer` creates a gift registry or wishlist by supplying their `customer_id` and a `registry_type` (`BIRTHDAY`, `HOLIDAY`, or `WISHLIST`); it begins `ACTIVE`. Registry items may be added only while the registry is `ACTIVE`, else `ERR_REGISTRY_NOT_ACTIVE`; each item names a `product_id` and a `desired_qty` (at least 1) and starts with `purchased_qty` at 0. Items may be listed within a registry or filtered globally by `registry_id` and `product_id`, and fetched individually. As described in §3.7, fulfilling an order raises the matching item's `purchased_qty`. The owning customer may close a registry, moving it from `ACTIVE` to `CLOSED` (terminal).

### 3.13. Returns and Refunds

A `StoreAssociate` requests a return against an order by supplying its `order_id` and a non-empty `lines` array, where each element identifies an `order_line_id` (a non-empty string) and a returned `qty` (an integer of at least 1); a missing or empty array, or a malformed element, is rejected with `ERR_VALIDATION`. Only the order's existence is checked at request time — the order need not yet be `FULFILLED`, and the referenced line ids are not validated until approval. The return begins `REQUESTED`. A `StoreManager` then approves or rejects it by supplying a `decision` of either APPROVE or REJECT (any other value is rejected with `ERR_VALIDATION`). Both decisions first require the return to be `REQUESTED`; a return already in a terminal state is refused with `ERR_ALREADY_TERMINAL`. Rejection simply moves the return to `REJECTED` (terminal). Approval requires the parent order's `fulfillment_status` to be `FULFILLED` (otherwise `ERR_ORDER_NOT_FULFILLED`), and the approval to fall within 30 days of the order's fulfillment — the current clock must be at or before the fulfillment instant plus 30 days, inclusive; a later approval is refused with `ERR_RETURN_WINDOW_EXPIRED`.

On approval the refund is computed in a fixed order. First the gross refund is accumulated over the returned lines: for each returned line, the line's effective total after discount is `extended_cents` minus `line_discount_cents`, the effective paid amount per unit is that effective total divided by the line's `qty` rounded down, and the contribution is the per-unit amount multiplied by the returned quantity; `gross_refund_cents` is the sum of these contributions. A referenced `order_line_id` that does not exist or does not belong to the return's parent order is silently skipped (it contributes nothing and is neither validated nor restocked); the requested return `qty` is not checked against the line's original quantity or its remaining returnable quantity. Next the restocking-fee tier is looked up from `gross_refund_cents`: a gross below 5000 cents incurs no fee, a gross from 5000 through 19999 cents incurs 10 percent, and a gross of 20000 cents or more incurs 15 percent. The `restocking_fee_cents` is the gross multiplied by the tier percentage, rounded down to whole cents. The `net_refund_cents` is `gross_refund_cents` minus `restocking_fee_cents`. The gross is always computed before the fee tier is selected. Approval also transitions each referenced order line that is still `ACTIVE` to `RETURNED` (a line not `ACTIVE` keeps its status but is still restocked), restocks the returned units by adding them to the matching inventory item's `on_hand_qty`, and reverses loyalty points as described in §3.8. The parent-order `FULFILLED` requirement is enforced once for the return as a whole (via the order referenced by the return), not re-checked per line.

### 3.14. Logical Clock

A `CatalogAdmin` may set the service's logical clock by supplying a `to_iso8601` instant; this test-driving capability governs temporal checks such as the return window. At server startup the clock reads exactly 2026-03-01T00:00:00Z, and before it is ever set it reports that default rather than any wall-clock time.

## 4. Endpoint Definitions

New resource creations return HTTP 201; all other successful operations, including state transitions, updates, and reads, return HTTP 200. All endpoints require the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/products` | Create product (DRAFT) | CatalogAdmin |
| GET | `/products` | List products | Any |
| GET | `/products/{productId}` | Get product | Any |
| PATCH | `/products/{productId}` | Update product fields | CatalogAdmin |
| POST | `/products/{productId}/activate` | Activate product | CatalogAdmin |
| POST | `/products/{productId}/discontinue` | Discontinue product | CatalogAdmin |
| POST | `/stores` | Create store | CatalogAdmin |
| GET | `/stores` | List stores | Any |
| GET | `/stores/{storeId}` | Get store | Any |
| POST | `/inventory` | Create inventory item for product+store | StoreAssociate |
| GET | `/inventory` | List/filter inventory | Any |
| GET | `/inventory/{inventoryItemId}` | Get inventory item | Any |
| POST | `/inventory/{inventoryItemId}/receive` | Receive stock | StoreAssociate |
| POST | `/allocations` | Create seasonal/exclusive allocation | StoreManager |
| GET | `/allocations` | List/filter allocations | Any |
| GET | `/allocations/{allocationId}` | Get allocation | Any |
| POST | `/allocations/{allocationId}/release` | Release remaining allocation | StoreManager |
| POST | `/customers` | Create loyalty customer | StoreAssociate |
| GET | `/customers/{customerId}` | Get customer | Any |
| POST | `/orders` | Create order (OPEN/UNPAID) | Customer, StoreAssociate |
| GET | `/orders` | List/filter orders | Any |
| GET | `/orders/{orderId}` | Get order | Any |
| POST | `/orders/{orderId}/lines` | Add order line | Customer, StoreAssociate |
| GET | `/order-lines` | List/filter order lines | Any |
| GET | `/order-lines/{orderLineId}` | Get order line | Any |
| POST | `/orders/{orderId}/submit` | Submit order (provisional pricing) | Customer, StoreAssociate |
| POST | `/orders/{orderId}/pay` | Apply payment | Customer, StoreAssociate |
| POST | `/orders/{orderId}/mark-ready` | Mark ready (final pricing lock, recall gate) | StoreAssociate |
| POST | `/orders/{orderId}/fulfill` | Fulfill (BOPIS pickup / ship) | StoreAssociate |
| POST | `/orders/{orderId}/cancel` | Cancel order (cascade release) | Customer, StoreAssociate |
| POST | `/layaways` | Create layaway plan | StoreAssociate |
| GET | `/layaways` | List/filter layaways | Any |
| GET | `/layaways/{layawayId}` | Get layaway | Any |
| POST | `/layaways/{layawayId}/payments` | Apply layaway installment payment | Customer, StoreAssociate |
| POST | `/layaways/{layawayId}/cancel` | Cancel layaway | StoreAssociate |
| POST | `/special-orders` | Create special order request | StoreAssociate |
| GET | `/special-orders` | List/filter special orders | Any |
| GET | `/special-orders/{specialOrderId}` | Get special order | Any |
| POST | `/special-orders/{specialOrderId}/quotes` | Issue/re-issue quote (OCC on version) | StoreManager |
| POST | `/special-orders/{specialOrderId}/approve` | Customer approves quote | Customer |
| POST | `/special-orders/{specialOrderId}/convert` | Convert approved special order to an Order | StoreAssociate |
| POST | `/recalls` | Open a recall for a product | CatalogAdmin |
| GET | `/recalls` | List/filter recalls | Any |
| GET | `/recalls/{recallId}` | Get recall | Any |
| POST | `/recalls/{recallId}/issue` | Issue recall (cascade) or resolve (resolve=true) | CatalogAdmin |
| POST | `/events` | Schedule demo event | StoreAssociate |
| GET | `/events` | List/filter events | Any |
| GET | `/events/{eventId}` | Get event | Any |
| POST | `/events/{eventId}/register` | Register customer for event | Customer |
| POST | `/registries` | Create gift registry / wishlist | Customer |
| GET | `/registries` | List/filter registries | Any |
| GET | `/registries/{registryId}` | Get registry | Any |
| POST | `/registries/{registryId}/items` | Add registry item | Customer |
| GET | `/registries/{registryId}/items` | List registry items | Any |
| GET | `/registry-items` | List/filter registry items | Any |
| GET | `/registry-items/{registryItemId}` | Get registry item | Any |
| POST | `/registries/{registryId}/close` | Close registry | Customer |
| POST | `/returns` | Request return on a fulfilled order | StoreAssociate |
| GET | `/returns` | List/filter returns | Any |
| GET | `/returns/{returnId}` | Get return | Any |
| POST | `/returns/{returnId}/approve` | Approve/reject return | StoreManager |
| POST | `/_clock/set_current_utc` | Set logical clock | CatalogAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_VALIDATION | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_STORE_NOT_FOUND | 404 |
| ERR_INVENTORY_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_LAYAWAY_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_RECALL_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_REGISTRY_NOT_FOUND | 404 |
| ERR_RETURN_NOT_FOUND | 404 |
| ERR_ORDER_LINE_NOT_FOUND | 404 |
| ERR_REGISTRY_ITEM_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_NOT_OPEN | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_LAYAWAY_NOT_ACTIVE | 409 |
| ERR_SPECIAL_ORDER_NOT_APPROVED | 409 |
| ERR_AGE_GRADE_VIOLATION | 422 |
| ERR_PRODUCT_RECALLED | 409 |
| ERR_EVENT_OVERLAP | 409 |
| ERR_ALLOCATION_WINDOW_OVERLAP | 409 |
| ERR_RETURN_WINDOW_EXPIRED | 409 |
| ERR_NO_ALLOCATION | 409 |
| ERR_REGISTRY_NOT_ACTIVE | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_INSUFFICIENT_ALLOCATION | 409 |
| ERR_EVENT_FULL | 409 |
| ERR_OVERPAYMENT | 409 |
| ERR_LAYAWAY_OVERPAYMENT | 409 |
| ERR_STALE_SPECIAL_ORDER_VERSION | 412 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_ORDER_NOT_FULFILLED | 409 |
| ERR_ORDER_NOT_READY | 409 |
| ERR_ORDER_NOT_PAID | 409 |
| ERR_DUPLICATE_EVENT_REGISTRATION | 409 |
