# Auto Parts Retail & Distribution API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auto Parts Retail & Distribution API, the backend that runs a parts house serving two very different customers at the same counter: the walk-in retail buyer paying list price, and the trade account buying at negotiated wholesale pricing on open credit terms. The system unifies the parts catalog, vehicle-fitment lookups, and part-to-part interchange cross-references with the order desk, so that a clerk can find the right part for a vehicle, price it correctly for the buyer in front of them, reserve and ship physical stock, and settle the money — all against a single source of truth.

The domain is dense with rules that retail software usually hides. Rebuildable parts carry a refundable core deposit that must be tracked from sale through the customer's eventual core return. Wholesale lines must respect a per-account price matrix and a margin floor that protects the business from selling below cost. Inventory must be reserved at allocation and only deducted at shipment, with low-stock thresholds quietly generating replenishment suggestions. Defective merchandise flows through a warranty adjudication process that can refund money or issue a replacement. And special-order parts the store does not stock can be expedited by a hotshot driver whose runs must be scheduled against shared drivers and loading bays without conflict. The API exists to make every one of these flows precise, auditable, and consistent.

This specification is the authoritative contract for the implementation. Where a calculation, threshold, state transition, or validation is described in prose, that prose is the rule — there is no separate schema document. All monetary amounts are carried as integer cents to avoid floating-point drift, and all time windows for delivery scheduling are carried as integer minutes from a fixed epoch.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles, spelled precisely as follows: `CounterClerk`, `WholesaleRep`, `InventoryManager`, and `WarrantyAdmin`. A `CounterClerk` works the retail counter, opening walk-in orders on the `COUNTER` channel and driving them through fulfillment and settlement, and intaking core returns and warranty claims for adjudication by others. A `WholesaleRep` runs the trade desk, managing accounts and their credit lifecycle and selling on the `WHOLESALE` channel. An `InventoryManager` owns the catalog, vehicle records, fitments, cross-references, price tiers, parts, stock receipts, and the full reorder lifecycle. A `WarrantyAdmin` adjudicates core returns and warranty/defective claims.

All four roles are operator roles whose identity is opaque: when `X-User-Role` is `CounterClerk`, `WholesaleRep`, `InventoryManager`, or `WarrantyAdmin`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit, but it does not compare `X-User-ID` to any entity's `id`, and there is no resource-ownership check that ties a record to the user who created it. Authorization is determined purely by role, per the matrix in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system are mutable, first-class records that carry a standard set of system-managed fields. For these resources — Part, Vehicle, Account, PriceTier, SalesOrder, OrderLine, CoreReturn, WarrantyClaim, ReorderRequest, Driver, Bay, and DeliveryRun — the server maintains:

- `id`: a unique, server-minted identifier formatted as a UUID, carrying no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation, including mutations driven by cascades and by recomputation of derived fields.
- `version`: an integer that begins at its initial value on creation and increments by one on every mutation of the resource.

Two association records are deliberately immutable and therefore carry a reduced field set. A Fitment and a CrossReference each receive only an `id` (UUID) and a `created_at`; they have no `updated_at` and no `version`, because once written they are never modified — to change an association the operator creates a new record. Any derived-field recomputation that lands on a mutable parent (for example, recomputing an order's totals, or recomputing a part's available quantity) is itself a mutation that refreshes that parent's `updated_at` and increments its `version`.

### 2.5. Monetary Values, Quantities, and Rounding

Every monetary amount in the system is an integer count of cents; field names ending in `_cents` are always whole-number cents, never fractional dollars. The pricing engine produces per-unit prices that may require rounding, and the rounding discipline is fixed: per-unit amounts are rounded to whole cents using the round-half-up method, and the margin floor is rounded up to the next whole cent (so the floor can never be undercut by rounding). Rounding is always applied to the per-unit figure first, and only then is the rounded per-unit amount multiplied by the line quantity — the system rounds-then-multiplies, never multiplies-then-rounds. Order- and account-level totals are integer sums of already-rounded per-line amounts and receive no further rounding. Inventory quantities are integer unit counts and are never permitted to go negative.

### 2.6. Inventory Accounting and the Reorder Trigger

Each stockable Part tracks three quantity fields that the server maintains and the client never writes directly: `on_hand_qty` is the number of units physically in stock; `reserved_qty` is the number of units committed to allocated-but-unshipped order lines; and `available_qty` is the read-only difference defined as `on_hand_qty` minus `reserved_qty`. None of the three may ever become negative. On-hand stock is debited at shipment and credited on receiving and on a defective restock; reserved stock is raised at allocation and relieved at shipment or at cancellation of an allocated order. The available quantity is recomputed every time on-hand or reserved changes.

A low-stock replenishment suggestion is generated automatically as a side effect of any inventory decrement that recomputes a part's available quantity (specifically after a shipment and after a warranty-replacement issue). Immediately after the recompute, the system creates a new reorder suggestion for that part when, and only when, all of the following hold together: the part is stockable, the part's status is `ACTIVE`, the part's `available_qty` is at or below its `reorder_point`, and there is no existing reorder request for that part already in `SUGGESTED`, `ORDERED`, or `PARTIALLY_RECEIVED` status. The threshold is inclusive: an available quantity equal to the reorder point triggers a suggestion, while an available quantity of one unit above the reorder point does not. The suggested request's replenishment quantity is snapshotted from the part's `reorder_qty`.

### 2.7. Left-to-Right Existence Validation

When a request names resources — whether a single resource in the URL path or one or more foreign-key references in the request body — the server validates their existence in order, path identifiers before body identifiers, and rejects the request at the first identifier that does not resolve. Each resource type has its own not-found error: `ERR_PART_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_FITMENT_NOT_FOUND`, `ERR_CROSS_REFERENCE_NOT_FOUND`, `ERR_PRICE_TIER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_REORDER_REQUEST_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, and `ERR_DELIVERY_RUN_NOT_FOUND`. Existence is checked after authentication and authorization but before business-rule evaluation.

### 2.8. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed precedence so that the rejection a client receives is deterministic. The global precedence is: first the authentication-header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 401); then the role-permission check (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403); then existence of every referenced resource, path before body (the not-found errors of §2.7, HTTP 404); then request-body well-formedness — required fields present and correctly typed, enum members valid, and numeric fields within their declared ranges (`ERR_INVALID_REQUEST`, HTTP 422); and only then the operation-specific business rules described in §3. Within the business-rule tier, an operation's own checks are evaluated in the order their narratives describe; where a creation also enforces a uniqueness or referential rule (such as a duplicate SKU, a channel/account mismatch, or a discontinued-part reference), those follow the body-well-formedness check.

### 2.9. Optimistic Concurrency Control on Order Fulfillment

Two order-fulfillment transitions are guarded by optimistic concurrency control, because the act of adding a line to an order legitimately advances the order's `version`, and a client acting on a stale view of the order's line set must not be allowed to proceed. Both the allocation step and the shipment step require the request body to carry `expected_sales_order_version` as a non-optional field, holding the `version` of the SalesOrder that the client last observed.

When allocating an order, if `expected_sales_order_version` does not equal the target SalesOrder's current `version`, the allocation is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the intended guard against allocating an order whose line set has changed since the client read it: adding a line recomputes the order's subtotals and bumps the order's `version`, so an allocation carrying the pre-add version is operating on a stale view and is refused. Likewise, when shipping an order, if `expected_sales_order_version` does not equal the order's current `version`, the shipment is rejected with `ERR_STALE_VERSION` (HTTP 412); the allocation step itself advances the order's `version`, so a ship request carrying the pre-allocation version is stale and refused. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.10. Accounts Receivable and Credit Discipline

Each Account carries an outstanding accounts-receivable balance, `ar_balance_cents`, which the server maintains and which begins at zero. It is charged when an order is invoiced and relieved when an order is paid, when an accepted core return refunds a deposit, and when an approved refund-resolution warranty claim issues a credit. The A/R balance is never allowed to fall below zero: every relief operation that would drive it negative instead clamps it at zero.

Credit discipline applies only to wholesale trade. For a `WHOLESALE` account, an order may be invoiced only if the account's current `ar_balance_cents` plus the order's `order_total_cents` would remain at or below the account's `credit_limit_cents`; otherwise the invoice is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). The `credit_limit_cents` field is meaningful only for wholesale accounts and is ignored for retail accounts, which never carry an open balance subject to a limit.

### 2.11. Delivery Window Conflict Semantics

Hotshot delivery runs compete for two shared resources — a driver and a loading bay — and each resource uses a different notion of "conflict." A run occupies a window expressed as two integer minute marks, `window_start_min` and `window_end_min`, where the end must be strictly greater than the start. When a new run is scheduled, its window is checked against every existing non-`CANCELLED` run on the same driver and, separately, against every existing non-`CANCELLED` run on the same bay.

For a driver, the window is **buffered** by the driver's `turnaround_min`: two runs on the same driver conflict whenever the first run's start is earlier than the second run's end plus the turnaround, and the second run's start is earlier than the first run's end plus the turnaround. In other words, the runs must be separated by a gap of at least the turnaround minutes; any closer — including touching or near-touching within the buffer — is a conflict and is rejected with `ERR_DRIVER_WINDOW_CONFLICT`. For a bay, the window is **half-open** with no buffer: two runs on the same bay conflict only when they positively overlap, that is, when the first run's start is earlier than the second's end and the second's start is earlier than the first's end. Exact adjacency, where one run's end equals the next run's start, does not conflict; a positive overlap is rejected with `ERR_BAY_WINDOW_CONFLICT`. Cancelling a run frees both its driver window and its bay window for future scheduling.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Parts, Vehicles, Fitments, and Cross-References

The catalog is the foundation, and an `InventoryManager` is its sole author. A Part is created with its manufacturer part number `sku`, a catalog `description`, a manufacturer `list_price_cents`, and a wholesale acquisition `cost_cents`. The list price must be greater than zero and the cost must be at least zero. A part may optionally declare a refundable core deposit through `core_charge_cents` (defaulting to zero, meaning no core) and a boolean `is_rebuildable` flag (defaulting to false). These two are tightly coupled: a rebuildable part must carry a positive core charge, and a non-rebuildable part must carry a core charge of exactly zero; any other combination is rejected with `ERR_CORE_CHARGE_INCONSISTENT`. A part also declares a warranty coverage window in days, `warranty_days` (defaulting to zero, and at least zero), and a `stockable` flag (defaulting to true); marking a part non-stockable designates it as special-order-only merchandise that is never held in stock and never auto-reordered. Replenishment behavior is configured by `reorder_point` and `reorder_qty`, each at least zero and each defaulting to zero. The manufacturer part number must be unique across all parts; a creation that repeats an existing `sku` is rejected with `ERR_DUPLICATE_SKU`. On creation the three inventory counters `on_hand_qty`, `reserved_qty`, and `available_qty` all start at zero and the part's `status` starts at `ACTIVE`.

A Vehicle is a vehicle-application record described by a `year`, a `make`, and a `model`, with an optional `engine` qualifier (defaulting to an empty string). The model year must fall between 1900 and 2100 inclusive. Vehicles can be listed and filtered to support lookups.

A Fitment links one part to one vehicle, recording which part fits which vehicle. It is created with a `part_id` and a `vehicle_id`, an optional `position` (one of `FRONT`, `REAR`, `LEFT`, `RIGHT`, or `UNIVERSAL`, defaulting to `UNIVERSAL`), and free-text `notes` (defaulting to empty). Fitment lookups resolve in either direction: the listing of fitments can be filtered by `part_id` to find every vehicle a part fits, or by `vehicle_id` to find every part that fits a vehicle. A CrossReference records a directed interchange edge from one catalog part to an equivalent substitute, created with a `part_id` (the part being looked up), an `interchange_part_id` (the equivalent part), and a `relation` describing the kind of interchange — one of `SUPERSEDES`, `EQUIVALENT`, or `OE_TO_AFTERMARKET`, defaulting to `SUPERSEDES`. Cross-references can be listed and filtered by `part_id` or by `interchange_part_id`. Both fitments and cross-references are immutable once written.

A part's catalog lifecycle is short: it is `ACTIVE` until discontinued. Discontinuing a part — moving its `status` from `ACTIVE` to `DISCONTINUED` — is permitted only when the part is currently `ACTIVE` (otherwise `ERR_PART_ALREADY_DISCONTINUED`) and when it has no live reservations, meaning its `reserved_qty` is exactly zero (otherwise `ERR_PART_HAS_RESERVATIONS`). Discontinuation cascades: every reorder request for that part that is currently `SUGGESTED` or `ORDERED` is moved to `CANCELLED` as part of the same operation, and then the part's status becomes `DISCONTINUED`. A discontinued part can no longer start new order lines.

### 3.2. Pricing Tiers and Account Setup

Pricing is organized as a matrix of tiers. An `InventoryManager` creates a PriceTier with a `name` (such as JOBBER, INSTALLER, or LIST), a `discount_pct` giving the fractional discount off list price applied to non-core merchandise, an optional `core_discount_pct` giving the fractional discount applied to the core-charge component (defaulting to zero), and an optional `min_margin_pct` giving the margin floor (defaulting to zero). The merchandise discount and core discount each range from 0.00 to 0.90 inclusive, and the minimum-margin percentage ranges from 0.00 to 5.00 inclusive.

Accounts are the buyers. An Account is created with a `name`, an `account_type` of either `RETAIL` or `WHOLESALE`, a `price_tier_id` naming the pricing tier that applies to the account's lines, and, for wholesale buyers, a `credit_limit_cents` (defaulting to zero, at least zero). A `RETAIL` account models the walk-in counter customer; a `WHOLESALE` account models a trade shop buying on credit. On creation an account's `ar_balance_cents` starts at zero and its `status` starts at `ACTIVE`. An account's status governs whether it can transact: a `WholesaleRep` (or an `InventoryManager`) can place an account `ON_HOLD`, which blocks it from opening new business, and can later reinstate it to `ACTIVE`. Accounts can be listed and filtered by `price_tier_id` or by `account_type`.

### 3.3. Opening Orders and Pricing Lines

A sale begins when a `CounterClerk` or `WholesaleRep` opens a SalesOrder for a buyer, supplying the `account_id`, the `channel`, and an optional `hotshot_requested` flag (defaulting to false). The channel must agree with the account's type: a `RETAIL` account must be sold on the `COUNTER` channel and a `WHOLESALE` account on the `WHOLESALE` channel; a mismatch is rejected with `ERR_CHANNEL_ACCOUNT_MISMATCH`. A new order opens with its `fulfillment_status` at `OPEN`, its `settlement_status` at `UNBILLED`, and its computed totals — `merchandise_subtotal_cents`, `core_subtotal_cents`, `order_total_cents`, and `hotshot_fee_cents` — all at zero. These two status dimensions evolve independently of one another: the physical fulfillment dimension (`OPEN`, `ALLOCATED`, `SHIPPED`, `CANCELLED`) and the financial settlement dimension (`UNBILLED`, `INVOICED`, `PAID`) are tracked separately. Orders can be listed and filtered by `account_id`, by `fulfillment_status`, or by `settlement_status`.

Lines are added to an order one at a time. Adding a line requires the parent order's `fulfillment_status` to be `OPEN`; adding a line to any other state is rejected with `ERR_ORDER_NOT_OPEN`. The line is created with the `order_id`, the `part_id`, and a `qty` of at least one. The referenced part must be `ACTIVE`; attempting to line up a discontinued part is rejected with `ERR_PART_DISCONTINUED`. At creation the line snapshots the account's current pricing tier into its own `price_tier_id` so that later tier changes never disturb already-priced lines — this snapshot is version-pinned to the tier the account points at when the line is written. The line's `is_special_order` flag is determined at creation: it is set true when the part is non-stockable, or when the requested `qty` exceeds the part's `available_qty` at the moment of line creation; otherwise it is false.

Each new line is priced immediately, and the result is stored on the line as `unit_merch_price_cents`, `unit_core_price_cents`, `line_merch_total_cents`, and `line_core_total_cents`. The net per-unit merchandise price is computed in a fixed order. First, take the part's list price and apply the tier's merchandise discount, giving a discounted price equal to the list price multiplied by one minus the discount percentage, rounded half-up to whole cents. Second, compute a margin floor equal to the part's cost multiplied by one plus the tier's minimum-margin percentage, rounded **up** to the next whole cent. Third, the net per-unit merchandise price `unit_merch_price_cents` is the greater of the discounted price and the margin floor — the floor protects against selling below the cost-plus-margin minimum. Fourth, the net per-unit core price `unit_core_price_cents` is the part's core charge multiplied by one minus the tier's core-discount percentage, rounded half-up to whole cents. Finally, the line's extended totals are the per-unit figures multiplied by quantity: `line_merch_total_cents` is `unit_merch_price_cents` times `qty`, and `line_core_total_cents` is `unit_core_price_cents` times `qty`. The per-unit rounding in the first and fourth steps happens before the multiplication in the last step.

This pricing has two variants driven by the order's channel. On a retail counter sale — an account of type `RETAIL` on the `COUNTER` channel — lines always price at full list: the merchandise discount is treated as zero and the margin floor never binds (list is at or above cost), so `unit_merch_price_cents` equals the part's list price regardless of the tier's discount. On a wholesale sale — an account of type `WHOLESALE` on the `WHOLESALE` channel — the full tier matrix applies, so both the discount and the margin floor bind and the same part yields a different `unit_merch_price_cents` than it would at retail.

Every time a line is added (and again whenever lines are cancelled or the order is allocated), the order's totals are rolled up. The `merchandise_subtotal_cents` is the sum of `line_merch_total_cents` over all lines whose status is not `CANCELLED`; the `core_subtotal_cents` is the sum of `line_core_total_cents` over the same non-cancelled lines; and the `order_total_cents` is the merchandise subtotal plus the core subtotal plus the order's `hotshot_fee_cents`. These sums are of already-rounded per-line amounts and are not rounded again. Adding a line is a mutation of the parent order: it recomputes the rollup and increments the order's `version` by one — which is precisely why a later allocation must present a matching `expected_sales_order_version`.

### 3.4. Allocation, Shipment, Cancellation, and the Hotshot Fee

Allocation is the step that reserves stock and locks the order. A `CounterClerk` or `WholesaleRep` allocates an order, advancing its `fulfillment_status` from `OPEN` to `ALLOCATED`. Several preconditions guard the transition, evaluated as a group: the order must have at least one line (otherwise `ERR_EMPTY_ORDER`); the buying account must be `ACTIVE` (otherwise `ERR_ACCOUNT_ON_HOLD`); every non-special-order line must have a part whose `available_qty` is at least that line's `qty` (otherwise `ERR_INSUFFICIENT_STOCK`); and the supplied `expected_sales_order_version` must match the order's current `version` (otherwise `ERR_STALE_VERSION`, as described in §2.9). On success, for each non-special-order line the part's `reserved_qty` is increased by the line's `qty` and the part's `available_qty` is recomputed (this may cross the reorder point, though the reorder suggestion is generated at shipment, not at allocation), and the line's status moves to `ALLOCATED`. Special-order lines are left in `PENDING` status with no reservation, because they await receiving or hotshot delivery. The hotshot fee is computed at this point, the order totals are recomputed to include it, the order's `version` is incremented by one, and the order moves to `ALLOCATED`.

The hotshot fee compensates for expediting special-order merchandise. It is computed at allocation and stored in `hotshot_fee_cents`. If the order did not request hotshot delivery, or if it has no non-cancelled special-order line, the fee is zero. Otherwise the fee is a flat base charge of twenty-five dollars plus seven dollars and fifty cents for each special-order unit, where the special-order unit count is the sum of `qty` over all non-cancelled special-order lines. As a boundary, an order that requested hotshot but has exactly zero special-order lines still gets a fee of zero, while a single special-order unit yields the base plus the per-unit charge.

Shipment fulfills an allocated order. A `CounterClerk` or `WholesaleRep` ships an order, advancing `fulfillment_status` from `ALLOCATED` to `SHIPPED`. The transition requires that the order currently be `ALLOCATED` (otherwise `ERR_INVALID_FULFILLMENT_STATE`); that no special-order line still sits `PENDING` without received stock to fulfill it (otherwise `ERR_SPECIAL_ORDER_NOT_READY`); and that the supplied `expected_sales_order_version` match the order's current `version` (otherwise `ERR_STALE_VERSION`). On success, for each allocated line the part's `on_hand_qty` is decreased by the line's `qty` and its `reserved_qty` is decreased by the line's `qty`, then `available_qty` is recomputed; this recompute is the first hop of a cascade, because if the part is now at or below its reorder point and is stockable with no open reorder request, a new `SUGGESTED` reorder request is auto-created as the second hop (per §2.6). For every shipped line whose part is rebuildable, the line's `cores_outstanding` is set to the line's `qty`, opening the core-deposit obligations. Each line moves to `SHIPPED`, the order's `version` is incremented by one, and the order moves to `SHIPPED`.

Cancellation retires an unsettled order. A `CounterClerk` or `WholesaleRep` can cancel an order whose `fulfillment_status` is `OPEN` or `ALLOCATED`; cancelling from any other fulfillment state is rejected with `ERR_INVALID_FULFILLMENT_STATE`, and an order that has already been invoiced cannot be cancelled regardless of fulfillment, which is to say cancellation requires `settlement_status` to be `UNBILLED` (otherwise `ERR_ORDER_ALREADY_INVOICED`). These two guards are evaluated in this order: the fulfillment-state check fires first, so an order that is neither `OPEN` nor `ALLOCATED` is rejected with `ERR_INVALID_FULFILLMENT_STATE` even when it has also been invoiced; the `ERR_ORDER_ALREADY_INVOICED` guard is reached only after the fulfillment-state check has passed. Cancelling an `OPEN` order simply moves all its lines to `CANCELLED`, increments the order's `version`, and moves the order to `CANCELLED`. Cancelling an `ALLOCATED` order additionally compensates the reservation: for each allocated line the part's `reserved_qty` is decreased by the line's `qty` and the part's `available_qty` is recomputed, which conserves the total of on-hand plus reserved across the allocate/cancel pair; then all lines move to `CANCELLED`, the order's `version` is incremented, and the order moves to `CANCELLED`.

### 3.5. Settlement: Invoicing and Payment

Settlement runs on its own track. A `CounterClerk` or `WholesaleRep` invoices a shipped order, advancing `settlement_status` from `UNBILLED` to `INVOICED`. Invoicing requires the order's `fulfillment_status` to be `SHIPPED` (otherwise `ERR_NOT_SHIPPED`) and its `settlement_status` to be `UNBILLED` (otherwise `ERR_ALREADY_INVOICED`). For a wholesale buyer, the credit check of §2.10 applies: the account's `ar_balance_cents` plus the order's `order_total_cents` must remain at or below `credit_limit_cents`, or the invoice is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the order total is charged to the account — the account's `ar_balance_cents` is increased by the order's `order_total_cents`, recomputing the account's outstanding A/R — and the order moves to `INVOICED`.

Payment closes the financial loop. The same roles record payment of an invoiced order, advancing `settlement_status` from `INVOICED` to `PAID`. Payment requires the order's `settlement_status` to be `INVOICED` (otherwise `ERR_NOT_INVOICED`). On success the charge is relieved: the account's `ar_balance_cents` is decreased by the order's `order_total_cents`, clamped at a floor of zero, and the order moves to `PAID`. Invoice and payment form a compensation pair that conserves the account's A/R.

### 3.6. Core Returns

When a customer brings back the old rebuildable core, the deposit is refunded through a CoreReturn. Any of `CounterClerk`, `WholesaleRep`, or `WarrantyAdmin` can open a core return against a shipped line, supplying the `order_line_id` and a `qty` of at least one that does not exceed the line's `cores_outstanding`. At creation the refund amount `refund_cents` is computed as the return `qty` multiplied by the line's net per-unit core price `unit_core_price_cents`, drawn from the line's snapshot, and the return opens in `PENDING_INSPECTION` status. Core returns can be listed and filtered by `order_line_id` or by `status`.

A `WarrantyAdmin` adjudicates each return. Accepting a return — moving it from `PENDING_INSPECTION` to `ACCEPTED` — requires the return to be `PENDING_INSPECTION` (otherwise `ERR_CORE_RETURN_NOT_PENDING`), the referenced order line to be `SHIPPED` (otherwise `ERR_CORE_RETURN_LINE_NOT_SHIPPED`), and the return's `qty` to not exceed the line's current `cores_outstanding` (otherwise `ERR_CORE_EXCEEDS_OUTSTANDING`). Acceptance cascades in two hops: first the line's `cores_outstanding` is decreased by the return `qty`, and then the refund is credited against the order's account — the account's `ar_balance_cents` is decreased by `refund_cents`, clamped at a floor of zero — before the return moves to `ACCEPTED`. Rejecting a return — moving it from `PENDING_INSPECTION` to `REJECTED` — requires only that the return be `PENDING_INSPECTION` (otherwise `ERR_CORE_RETURN_NOT_PENDING`); no deposit is refunded and `cores_outstanding` is left unchanged.

### 3.7. Warranty and Defective Claims

Defective merchandise is handled through a WarrantyClaim. Any of `CounterClerk`, `WholesaleRep`, or `WarrantyAdmin` can file a claim against a shipped line, supplying the `order_line_id`, a `qty` claimed defective that is at least one and does not exceed the line's `qty` (a claim quantity over the line quantity is rejected with `ERR_CLAIM_QTY_EXCEEDS_LINE`), a free-text `reason`, an optional `resolution` of `REPLACE` or `REFUND` (defaulting to `REPLACE`), and an optional `restock_defective` flag (defaulting to false). The referenced line must itself be `SHIPPED`; filing a claim against a line that has not shipped is rejected with `ERR_CLAIM_LINE_NOT_SHIPPED`. The claim opens in `SUBMITTED` status. Claims can be listed and filtered by `order_line_id` or by `status`.

A `WarrantyAdmin` works each claim through a review fork. Starting review moves a claim from `SUBMITTED` to `UNDER_REVIEW`, and is permitted only when the claim is `SUBMITTED` (otherwise `ERR_CLAIM_NOT_SUBMITTED`). A claim can be denied either while `SUBMITTED` or while `UNDER_REVIEW`: denial moves the claim to `DENIED` and is permitted whenever the claim is in `SUBMITTED` or `UNDER_REVIEW` (otherwise `ERR_CLAIM_NOT_OPEN`); a denied claim issues no credit and performs no restock. Approval is the consequential branch: approving a claim moves it from `UNDER_REVIEW` to `APPROVED`, and is permitted only when the claim is `UNDER_REVIEW` (otherwise `ERR_CLAIM_NOT_UNDER_REVIEW`) and only within the warranty window — the claim's `created_at` must be no later than the referenced line's ship time plus the part's `warranty_days` days (otherwise `ERR_WARRANTY_EXPIRED`).

Approval computes a credit and applies remedy-specific side effects symmetrically across the two resolutions. On a `REFUND` resolution the credit `credit_cents` is the claim `qty` multiplied by the line's snapshot `unit_merch_price_cents`, and that credit is applied against the account — the account's `ar_balance_cents` is decreased by `credit_cents`, clamped at a floor of zero — with no replacement unit issued. On a `REPLACE` resolution the `credit_cents` is zero and no A/R credit is issued; instead a replacement unit is issued by decreasing the part's `on_hand_qty` by the claim `qty` and recomputing `available_qty`, which may cross the reorder point and auto-suggest a reorder request per §2.6. Independently of the resolution, if `restock_defective` is true the defective unit is returned to inventory by increasing the part's `on_hand_qty` by the claim `qty` and recomputing `available_qty`; if it is false the defective unit is discarded. After these effects the claim moves to `APPROVED`.

### 3.8. Replenishment: The Reorder Lifecycle

Reorder requests keep stock on the shelf. A request can arise two ways: automatically, as the low-stock cascade described in §2.6 fires after a shipment or a warranty-replacement issue; or manually, when an `InventoryManager` creates one for a `part_id`. Either way the replenishment quantity `qty_ordered` is snapshotted from the part's `reorder_qty` at generation and must be at least one, the units-received counter `qty_received` starts at zero, and the request opens in `SUGGESTED` status. Reorder requests can be listed and filtered by `part_id` or by `status`.

An `InventoryManager` drives the lifecycle. Placing a request with the supplier moves it from `SUGGESTED` to `ORDERED`, and requires the request to be `SUGGESTED` (otherwise `ERR_REORDER_NOT_SUGGESTED`) and the part to be `ACTIVE` (otherwise `ERR_PART_DISCONTINUED`). Receiving applies against an `ORDERED` or `PARTIALLY_RECEIVED` request, supplying a `receive_qty`. A receipt is valid only when `receive_qty` is at least one and the running total of `qty_received` plus the new `receive_qty` does not exceed `qty_ordered`; an invalid receive quantity is rejected with `ERR_INVALID_RECEIVE_QTY`, and receiving against a request not in `ORDERED` or `PARTIALLY_RECEIVED` is rejected with `ERR_REORDER_NOT_RECEIVABLE`. Each receipt increases the part's `on_hand_qty` by `receive_qty`, recomputes the part's `available_qty`, and adds `receive_qty` to `qty_received`. When the new running total of `qty_received` plus `receive_qty` still falls short of `qty_ordered`, the request lands in (or remains in) `PARTIALLY_RECEIVED` and can absorb further partial receipts in a loop. When the running total of `qty_received` plus `receive_qty` exactly equals `qty_ordered`, the receipt completes the request: `qty_received` becomes equal to `qty_ordered` and the request moves to `RECEIVED`. Both an `ORDERED` request and a `PARTIALLY_RECEIVED` request can complete this way. Cancelling a request moves it to `CANCELLED` with no inventory change, and is permitted only while the request is `SUGGESTED` or `ORDERED` (otherwise `ERR_REORDER_NOT_CANCELLABLE`).

### 3.9. Hotshot Delivery: Drivers, Bays, and Runs

Expedited special-order merchandise is moved by hotshot delivery runs against shared drivers and bays. An `InventoryManager`, `CounterClerk`, or `WholesaleRep` can register a Driver with a `name` and a `turnaround_min` (the required buffer in minutes between two runs on that driver, at least zero, defaulting to zero), and can register a Bay with a `code` that must be unique across all bays (a repeat is rejected with `ERR_DUPLICATE_BAY_CODE`).

A `CounterClerk` or `WholesaleRep` schedules a DeliveryRun, supplying the `order_id` whose special-order/hotshot lines the run delivers, the `driver_id`, the `bay_id`, and the run window as `window_start_min` and `window_end_min` (each a non-negative integer minute mark, with the end strictly greater than the start). Scheduling enforces the two distinct overlap rules of §2.11 — the buffered driver check that can yield `ERR_DRIVER_WINDOW_CONFLICT` and the half-open bay check that can yield `ERR_BAY_WINDOW_CONFLICT` — and on success the run opens in `SCHEDULED` status. Runs can be listed and filtered by `order_id`, by `driver_id`, by `bay_id`, or by `status`.

The run then moves through its own lifecycle. Dispatching a run advances it from `SCHEDULED` to `DISPATCHED`, and requires the run to be `SCHEDULED` (otherwise `ERR_RUN_NOT_SCHEDULED`) and the referenced order to be in `ALLOCATED` or `SHIPPED` fulfillment (otherwise `ERR_RUN_ORDER_NOT_READY`). Completing a run advances it from `DISPATCHED` to `DELIVERED`, and requires the run to be `DISPATCHED` (otherwise `ERR_RUN_NOT_DISPATCHED`). Cancelling a run moves it to `CANCELLED` and is permitted while the run is `SCHEDULED` or `DISPATCHED` (otherwise `ERR_RUN_NOT_CANCELLABLE`); a cancelled run frees both its driver and bay windows so that later runs may reuse those times.

### 3.10. Ad-Hoc Stock Receipts

Beyond the reorder lifecycle, an `InventoryManager` can record an ad-hoc stock receipt directly against a part — for initial stocking or a manual upward adjustment — by supplying a `qty`. The receipt increases the part's `on_hand_qty` by that quantity and recomputes the part's `available_qty`. This path does not involve a reorder request and does not by itself fire the low-stock suggestion, since it only raises stock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and stock adjustments — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parts` | Create a catalog part | InventoryManager |
| GET | `/parts` | List parts (filterable by sku, status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/parts/{id}` | Get a part | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/parts/{id}/receive-stock` | Ad-hoc stock receipt (raise on-hand) | InventoryManager |
| POST | `/parts/{id}/discontinue` | Discontinue a part | InventoryManager |
| POST | `/vehicles` | Create a vehicle application record | InventoryManager |
| GET | `/vehicles` | List vehicles (filterable by year, make, model) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/vehicles/{id}` | Get a vehicle | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/fitments` | Associate a part with a vehicle | InventoryManager |
| GET | `/fitments` | List fitments (filterable by part_id, vehicle_id) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/fitments/{id}` | Get a fitment | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/cross-references` | Create an interchange edge between two parts | InventoryManager |
| GET | `/cross-references` | List cross-references (filterable by part_id, interchange_part_id) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/cross-references/{id}` | Get a cross-reference | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/price-tiers` | Create a price tier | InventoryManager |
| GET | `/price-tiers` | List price tiers | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/price-tiers/{id}` | Get a price tier | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/accounts` | Create a retail or wholesale account | InventoryManager, WholesaleRep |
| GET | `/accounts` | List accounts (filterable by price_tier_id, account_type) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/accounts/{id}` | Get an account | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/accounts/{id}/hold` | Place an account ON_HOLD | WholesaleRep, InventoryManager |
| POST | `/accounts/{id}/reinstate` | Return an ON_HOLD account to ACTIVE | WholesaleRep, InventoryManager |
| POST | `/sales-orders` | Open a sales order for an account | CounterClerk, WholesaleRep |
| GET | `/sales-orders` | List sales orders (filterable by account_id, fulfillment_status, settlement_status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/sales-orders/{id}` | Get a sales order with computed totals | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/sales-orders/{id}/allocate` | Reserve stock, price hotshot, lock order | CounterClerk, WholesaleRep |
| POST | `/sales-orders/{id}/ship` | Ship an allocated order | CounterClerk, WholesaleRep |
| POST | `/sales-orders/{id}/cancel` | Cancel an OPEN or ALLOCATED order | CounterClerk, WholesaleRep |
| POST | `/sales-orders/{id}/invoice` | Invoice a shipped order; charge A/R | CounterClerk, WholesaleRep |
| POST | `/sales-orders/{id}/pay` | Record payment; relieve A/R | CounterClerk, WholesaleRep |
| POST | `/order-lines` | Add a line to an OPEN order | CounterClerk, WholesaleRep |
| GET | `/order-lines` | List order lines (filterable by order_id, part_id, price_tier_id) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/order-lines/{id}` | Get an order line | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/core-returns` | Open a core return against a shipped rebuildable line | CounterClerk, WholesaleRep, WarrantyAdmin |
| GET | `/core-returns` | List core returns (filterable by order_line_id, status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/core-returns/{id}` | Get a core return | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/core-returns/{id}/accept` | Accept a core; refund the deposit | WarrantyAdmin |
| POST | `/core-returns/{id}/reject` | Reject a core; no refund | WarrantyAdmin |
| POST | `/warranty-claims` | File a warranty/defective claim against a shipped line | CounterClerk, WholesaleRep, WarrantyAdmin |
| GET | `/warranty-claims` | List warranty claims (filterable by order_line_id, status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/warranty-claims/{id}` | Get a warranty claim | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/warranty-claims/{id}/start-review` | Move a claim into review | WarrantyAdmin |
| POST | `/warranty-claims/{id}/approve` | Approve a claim; issue credit and/or replacement | WarrantyAdmin |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | WarrantyAdmin |
| POST | `/reorder-requests` | Manually create a reorder request for a part | InventoryManager |
| GET | `/reorder-requests` | List reorder requests (filterable by part_id, status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/reorder-requests/{id}` | Get a reorder request | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/reorder-requests/{id}/place` | Place a suggested reorder with the supplier | InventoryManager |
| POST | `/reorder-requests/{id}/receive` | Receive units against a reorder | InventoryManager |
| POST | `/reorder-requests/{id}/cancel` | Cancel a suggested/ordered reorder | InventoryManager |
| POST | `/drivers` | Create a hotshot delivery driver | InventoryManager, CounterClerk, WholesaleRep |
| GET | `/drivers` | List drivers | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/drivers/{id}` | Get a driver | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/bays` | Create a loading bay | InventoryManager, CounterClerk, WholesaleRep |
| GET | `/bays` | List bays | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/bays/{id}` | Get a bay | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/delivery-runs` | Schedule a hotshot delivery run | CounterClerk, WholesaleRep |
| GET | `/delivery-runs` | List delivery runs (filterable by order_id, driver_id, bay_id, status) | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| GET | `/delivery-runs/{id}` | Get a delivery run | CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin |
| POST | `/delivery-runs/{id}/dispatch` | Dispatch a scheduled run | CounterClerk, WholesaleRep |
| POST | `/delivery-runs/{id}/complete` | Mark a dispatched run delivered | CounterClerk, WholesaleRep |
| POST | `/delivery-runs/{id}/cancel` | Cancel a scheduled/dispatched run | CounterClerk, WholesaleRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_CORE_CHARGE_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_FITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_PRICE_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_SALES_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_CORE_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REORDER_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_CHANNEL_ACCOUNT_MISMATCH` | 409 Conflict |
| `ERR_PART_DISCONTINUED` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_ACCOUNT_ON_HOLD` | 409 Conflict |
| `ERR_INVALID_FULFILLMENT_STATE` | 409 Conflict |
| `ERR_SPECIAL_ORDER_NOT_READY` | 409 Conflict |
| `ERR_ORDER_ALREADY_INVOICED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_NOT_SHIPPED` | 409 Conflict |
| `ERR_ALREADY_INVOICED` | 409 Conflict |
| `ERR_NOT_INVOICED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_CORE_RETURN_NOT_PENDING` | 409 Conflict |
| `ERR_CORE_RETURN_LINE_NOT_SHIPPED` | 409 Conflict |
| `ERR_CORE_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_OPEN` | 409 Conflict |
| `ERR_CLAIM_QTY_EXCEEDS_LINE` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_CLAIM_LINE_NOT_SHIPPED` | 409 Conflict |
| `ERR_REORDER_NOT_SUGGESTED` | 409 Conflict |
| `ERR_REORDER_NOT_RECEIVABLE` | 409 Conflict |
| `ERR_REORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INVALID_RECEIVE_QTY` | 409 Conflict |
| `ERR_PART_ALREADY_DISCONTINUED` | 409 Conflict |
| `ERR_PART_HAS_RESERVATIONS` | 409 Conflict |
| `ERR_DUPLICATE_BAY_CODE` | 409 Conflict |
| `ERR_DRIVER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RUN_NOT_SCHEDULED` | 409 Conflict |
| `ERR_RUN_NOT_DISPATCHED` | 409 Conflict |
| `ERR_RUN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RUN_ORDER_NOT_READY` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
