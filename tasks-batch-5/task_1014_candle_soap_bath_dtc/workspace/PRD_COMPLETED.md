# Candle, Soap & Bath DTC API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Candle, Soap & Bath direct-to-consumer (DTC) commerce API. The platform runs an artisanal home-goods brand end to end: a merchandising catalog of scented candles, wax melts, soaps, and bath bombs; the finite, cured production batches those goods are made from; seasonal drops and gift bundles that reshape pricing for a window of time; and the shoppers who buy, subscribe, earn loyalty, and occasionally return.

The dominant engineering challenge is **finite inventory reconciliation**. Every unit a customer buys is drawn from a specific production batch whose counters — reserved, shipped, recalled, and available — must always balance against the quantity that was actually produced. Reservations, shipments, cancellations, returns, and product recalls all move quantities between these counters, and a single misfiled unit corrupts availability for every later order. Layered on top of inventory is a **pricing and loyalty engine**: bulk-quantity discount tiers, loyalty-tier discounts, free-shipping thresholds, and a points economy in which credits are posted provisionally at checkout and reconciled again at delivery, on cancellation, on return, and on recall. Because carts can be edited concurrently, checkout is guarded by optimistic concurrency control so that a shopper never pays against a total that has silently changed underneath them.

Time itself is a first-class input. Seasonal drops go live and end on a schedule, batch cure windows must not collide on a shared production line, and subscriptions renew when they come due — all evaluated against a server-controlled logical clock rather than wall-clock time, so that test scenarios are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles:

- **`Customer`** — a DTC shopper acting as their own persisted customer record. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership is enforced on every self-service operation: for any order, return, or subscription the customer acts on, the resource's owning `customer_id` (directly on an `Order` or `Subscription`, or reached through the `order_id` on a `Return`) must equal `X-User-ID`. A `Customer` acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- **`MerchOps`** — a merchandising and operations operator managing catalog, inventory, drops, bundles, fulfillment, returns, and subscription renewals. When `X-User-Role` is `MerchOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`PlatformAdmin`** — a superset operator who can perform every `MerchOps` operation, every `Customer` write operation (acting on behalf of shoppers), all reads, and additionally the customer-lifecycle, loyalty-grant, and logical-clock operations reserved to this role. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Read operations on the public catalog (products, skus, batches, drops, bundles) and on a principal's own resources are available to all three roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A supplied `limit` below 1 or above 100, or an `offset` below 0, is silently clamped to the nearest bound rather than rejected; a pagination value that is not a valid integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by insertion (creation) order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching items before pagination and `has_more` is true when items remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — `Product`, `Sku`, `Batch`, `Drop`, `Bundle`, `Customer`, `Order`, `OrderLine`, `Return`, and `Subscription` — carries the same four system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at creation and increments by one on every mutation of the resource.

Whenever a computed field changes as a side effect of some workflow — a batch's availability counters, an order's totals, or a customer's loyalty balance — that change is a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented. This holds even when the change was triggered indirectly (for example, a recall that voids lines and refreshes the affected orders and customers).

### 2.5. Monetary Amounts, Loyalty Points, and Rounding

All monetary amounts in this system are integers denominated in cents; there are no fractional cents. Line subtotals, order totals, discounts, shipping fees, and refund amounts are all exact integer-cent quantities.

Rounding enters at exactly one place: the discount computation at checkout. When a combined discount percentage is applied to a subtotal, the resulting discount amount is rounded **half up** to a whole number of cents. All subsequent arithmetic — subtracting the discount, testing the free-shipping threshold, and adding shipping — operates on those already-rounded integer cents, and the evaluation order is fixed: compute and round the discount first, subtract it from the subtotal, test the free-ship threshold against that discounted subtotal, then add shipping.

Loyalty points are always whole integers. When points are earned from an order, each qualifying line contributes the floor of its own subtotal-in-cents divided by 100, and those per-line floors are summed. The floor is applied **per line and then summed** — never by flooring a combined subtotal — so that the rounding behavior is independent of how a cart is split across lines.

### 2.6. Batch Inventory Ledger and the Availability Invariant

Each production `Batch` maintains four quantity counters against its immutable `quantity_produced`: `quantity_reserved` (units held by non-shipped order lines), `quantity_shipped` (units shipped or delivered and not yet returned), `quantity_recalled` (units removed by a recall), and `quantity_available`. Availability is always the produced quantity minus reserved, minus shipped, minus recalled. The following invariant holds at all times: the produced quantity equals available plus reserved plus shipped plus recalled.

`quantity_available` is never negative. Any reservation that would drive it below zero is rejected upstream with `ERR_INSUFFICIENT_INVENTORY` before any counter is touched. When a reservation brings availability to exactly zero, the batch is depleted; when a later compensating change raises availability back above zero, the batch becomes sellable again (see §2.9 and §3.2).

### 2.7. Optimistic Concurrency Control at Checkout

Because an order's lines can be added or repriced by more than one writer, checkout is protected by optimistic concurrency control on the `Order`. A checkout request must carry `expected_order_version` as a required field. The server compares it to the order's current `version`; if another writer has advanced the order's version since the client last read it — for example by adding or repricing a line, which legitimately mutates the cart and bumps the order version — the totals the client is paying against are stale, and the checkout is rejected with `ERR_STALE_VERSION` (HTTP 412). Only when `expected_order_version` equals the order's current `version` does checkout proceed. No other endpoint takes a version field; concurrency control applies solely to checkout.

### 2.8. The Logical Clock and Time-Windowed Behavior

All time-sensitive evaluation is performed against a server-controlled logical clock, never wall-clock time. The clock's startup default is `2026-07-01T00:00:00Z`; before any clock-setting call the server reads exactly this default and never falls back to real time. A `PlatformAdmin` may advance or reset the clock by supplying a target instant as `to_iso8601`. Every drop window, batch cure window, and subscription renewal due-date is evaluated against this clock.

A `Drop`'s `status` is derived from the clock on each read: it is `SCHEDULED` while the current instant is before `starts_at`, `LIVE` while the current instant is at or after `starts_at` and strictly before `ends_at`, and `ENDED` once the current instant is at or after `ends_at`. Because the status is computed on read, a drop that is created when the clock is already at or past its `ends_at` reads as `ENDED` immediately.

### 2.9. Cascades, Reconciliation, and Automatic State Transitions

Several operations mutate more than one entity in a single logical step, and the system reconciles all affected resources before responding. The three most consequential cascades are order cancellation, batch recall, and return settlement; each is specified in full in §3. Two batch transitions are automatic rather than operator-driven: a `RELEASED` batch whose availability is driven to exactly zero by a reservation transitions itself to `DEPLETED` and accepts no further reservations while depleted; and a `DEPLETED` batch whose availability is raised above zero by a release, cancellation, or return transitions itself back to `RELEASED` and becomes sellable again. Every entity touched during a cascade — batches, orders, order lines, customers — has its `updated_at` refreshed and its `version` incremented as part of that reconciliation.

### 2.10. Referential Existence and Nested-Path Validation

Every path and body identifier is validated for existence before the operation's business rules run. When a URL nests one resource under another — a sku under a product, a batch under a sku, an order or subscription under a customer, a line under an order — the identifiers are validated left to right, and the first identifier that does not resolve produces its own not-found error. The not-found errors are entity-specific: `ERR_PRODUCT_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, and `ERR_SUBSCRIPTION_NOT_FOUND`, each returning HTTP 404. Body-supplied foreign keys — for example the `sku_id` and `batch_id` on an order line — are validated the same way. A single order line can also be fetched directly by its `order_line_id`; because the catalogue defines no order-line-specific not-found code, an `order_line_id` that does not resolve returns `ERR_ORDER_NOT_FOUND`. A drop, bundle, return, or subscription may likewise be fetched by its `drop_id`, `bundle_id`, `return_id`, or `subscription_id` respectively.

### 2.11. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: presence and validity of the auth headers (`ERR_UNAUTHENTICATED`). Then role authorization for the endpoint (`ERR_UNAUTHORIZED`). Then, for a `Customer` acting on an order, return, or subscription, the resource-ownership check (`ERR_NOT_RESOURCE_OWNER`). Then existence of all path and body foreign keys, left to right (the entity-specific 404s of §2.10). Then whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE` and its specific siblings `ERR_BATCH_NOT_RELEASED`, `ERR_ORDER_NOT_EDITABLE`, `ERR_ORDER_NOT_DELIVERED`, `ERR_SUBSCRIPTION_NOT_DUE`). Then, on checkout only, the optimistic-concurrency check (`ERR_STALE_VERSION`). Then domain safety and temporal rules — safety-label enforcement (`ERR_SAFETY_LABEL_REQUIRED`), drop-liveness (`ERR_DROP_NOT_LIVE`), and customer-active-for-renewal (`ERR_CUSTOMER_SUSPENDED`). Then structural constraints — drop-window overlap, cure-window conflict, empty bundle, empty order, and no-eligible-batch (`ERR_DROP_WINDOW_OVERLAP`, `ERR_BATCH_LINE_CONFLICT`, `ERR_EMPTY_BUNDLE`, `ERR_EMPTY_ORDER`, `ERR_NO_ELIGIBLE_BATCH`). Then fiscal and quantity floors — inventory sufficiency and the bulk-order minimum (`ERR_INSUFFICIENT_INVENTORY`, `ERR_BULK_MIN_NOT_MET`). General request-format validation (`ERR_VALIDATION`) — required fields present, correct types, valid enums, and strictly positive quantities and prices — applies to all endpoints as the catch-all for malformed input.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Products, Skus, and Safety Labeling

A `MerchOps` or `PlatformAdmin` operator seeds the catalog by creating a `Product`, supplying its `product_type` — one of `CANDLE`, `WAX_MELT`, `SOAP`, or `BATH_BOMB` — along with a marketing `collection_name` (such as an "Autumn Hearth" line), a `scent_family` grouping (such as WOODY, CITRUS, or FLORAL), and a display `title`. Products of type `CANDLE` and `WAX_MELT` are the wax/melt goods that carry a legal safety-labeling obligation; soaps and bath bombs do not.

Beneath a product, an operator defines sellable variants as skus. Creating a sku under its parent product records the parent's identity as `product_id`, and the operator supplies the variant's `size` — one of `SMALL`, `MEDIUM`, or `LARGE` — a concrete `scent` name for that variant, and a default `list_price_cents`, which must be strictly greater than zero. The sku's `requires_safety_label` flag is computed, not supplied: it is true exactly when the parent product's `product_type` is `CANDLE` or `WAX_MELT`, and any client-provided value is ignored. Skus can be listed and filtered by their `product_id` for reverse lookup.

### 3.2. Production Batches and Their Lifecycle

Physical inventory lives in batches. A batch is created under its sku, capturing the parent as `sku_id` and recording the `quantity_produced` (strictly positive and immutable thereafter), the production `line_code` the batch was cured on, and the cure window bounded by `cure_starts_at` and `cure_ends_at`, whose end must be strictly later than its start. On creation the batch starts in `CREATED` status with `is_safety_labeled` false, `quantity_available` equal to `quantity_produced`, and its `quantity_reserved`, `quantity_shipped`, and `quantity_recalled` counters at zero.

Cure windows on a shared production line may not collide: creating a batch whose cure window overlaps that of another batch on the same `line_code` is rejected with `ERR_BATCH_LINE_CONFLICT`. The cure windows are treated as **closed intervals**, so two windows that merely touch at an endpoint are considered overlapping.

A batch advances through an operator-driven lifecycle. From `CREATED`, a labeling action stamps the batch as safety-labeled, moving it `CREATED → LABELED` and setting `is_safety_labeled` to true. A release action makes the batch sellable inventory: it can be released either from `CREATED` directly or from `LABELED`, moving it to `RELEASED`. Releasing from `CREATED` does not change `is_safety_labeled`, which may remain false — labeling and releasing are independent, and only labeling ever sets the flag. Once `RELEASED`, the batch participates in the automatic depletion cycle of §2.9: reservations that exhaust availability move it `RELEASED → DEPLETED`, and compensating changes move it `DEPLETED → RELEASED`. Batches can be listed and filtered by `sku_id`.

A recall is the batch's terminal event and is covered in full in §3.10; a batch may be recalled from either `RELEASED` or `DEPLETED`, reaching `RECALLED`.

### 3.3. Seasonal Drops and Exclusive Pricing

A `MerchOps` or `PlatformAdmin` operator schedules a seasonal `Drop` by supplying a `season` label (such as "FALL_2026"), a display `title`, an inclusive-start `starts_at`, an exclusive-end `ends_at` that must be strictly later than the start, and a `listings` array (which may be empty). Each listing is an object naming a `sku_id`, a `drop_price_cents` that overrides that sku's `list_price_cents` while the drop is live, and an `is_exclusive` flag (defaulting to false when omitted) marking whether the sku is sold *only* through this drop during its window. Note that only an *exclusive* listing's `drop_price_cents` is actually applied when a line is priced (see §3.6); a non-exclusive listing's price is never used at line add. The drop's `status` is not stored but derived from the logical clock on each read, moving `SCHEDULED → LIVE → ENDED` as described in §2.8, including the direct `SCHEDULED → ENDED` reading when the clock is already past `ends_at` at creation.

Exclusive listings may not double-book a sku in time: if any exclusive listing's window overlaps the exclusive window of the same sku in another drop that has not already `ENDED`, the drop is rejected with `ERR_DROP_WINDOW_OVERLAP`. These windows are treated with **half-open** semantics — start inclusive, end exclusive — so a new drop that begins exactly when a prior one ends does not overlap.

### 3.4. Gift Bundles

A gift `Bundle` is a fixed collection of skus sold at a single flat price. An operator creates a bundle with a display `title`, an `items` array whose entries each name a `sku_id` and a `quantity`, and a `bundle_price_cents` flat price that must be strictly greater than zero. A newly created bundle starts in `DRAFT`. Activating a bundle moves it `DRAFT → ACTIVE`, after which it is publicly purchasable; activation requires the bundle to contain at least one item, and activating an empty bundle is rejected with `ERR_EMPTY_BUNDLE`.

### 3.5. Customers, Loyalty Points, and Tiers

A `PlatformAdmin` registers a `Customer` with a unique `email` and a `full_name`; registering a customer whose `email` duplicates an existing customer's is rejected with `ERR_VALIDATION`. New customers begin `ACTIVE`, with a `loyalty_points_balance` of zero and the corresponding `BRONZE` tier. A customer's `loyalty_tier` is computed from the running balance: `BRONZE` while the balance is below 500 points, `SILVER` while the balance is at least 500 and below 2000, and `GOLD` once the balance is at least 2000. Both `loyalty_points_balance` and `loyalty_tier` are returned when a customer is fetched.

The loyalty balance moves throughout the commerce lifecycle: it rises when points are posted provisionally at checkout, is reconciled at delivery, and falls when points are reversed by an order cancellation, revoked by a settled return, or reversed by a recall — each detailed in the sections that follow. A `PlatformAdmin` may also make a direct customer-service adjustment that grants a positive integer number of `points`; the granted amount is added to `loyalty_points_balance` and the `loyalty_tier` is recomputed immediately.

Suspending a customer is a `PlatformAdmin` action that moves the customer `ACTIVE → SUSPENDED`. While a customer is `SUSPENDED`, their subscription renewals are blocked (see §3.9).

### 3.6. Building an Order: Lines, Reservation, and Provisional Pricing

A shopper (or a `PlatformAdmin` acting on their behalf) opens a cart by creating an order under a customer, which records the owner as `customer_id`. The optional `order_type` — one of `RETAIL`, `BULK`, or `GIFT`, defaulting to `RETAIL` — drives later pricing eligibility and checkout constraints. Two further optional fields, `gift_message` and `recipient_name`, are meaningful only when `order_type` is `GIFT`. A new order begins with `payment_status` of `UNPAID` and `fulfillment_status` of `PENDING`; its computed money and points fields — `total_quantity`, `provisional_total_cents`, `discount_cents`, `shipping_fee_cents`, `final_total_cents`, `provisional_points`, and `awarded_points` — all begin at zero. Orders can be listed and filtered by `customer_id`.

Lines may only be added while the order's `fulfillment_status` is `PENDING`; adding a line to an order in any other fulfillment state is rejected with `ERR_ORDER_NOT_EDITABLE`. A line names the `sku_id` being ordered, the `batch_id` to reserve against, and a `quantity` that must be strictly positive; each new line records its parent as `order_id`. Adding a line runs the priority-ordered checks of §2.11 and, on success, reserves stock and reprices the cart.

The batch a line reserves against must itself be sellable: if the chosen batch is not in `RELEASED` status the line is rejected with `ERR_BATCH_NOT_RELEASED`. Two domain guards then apply, in this order. First, safety labeling: if the sku's `requires_safety_label` is true, the chosen batch must have `is_safety_labeled` true, otherwise the line is rejected with `ERR_SAFETY_LABEL_REQUIRED`. Second, drop exclusivity: if the sku is exclusive to a drop, that drop must be `LIVE` at the current logical-clock instant for the line to be added, otherwise it is rejected with `ERR_DROP_NOT_LIVE`. Finally, inventory sufficiency: the batch's `quantity_available` must be at least the requested `quantity`, otherwise the line is rejected with `ERR_INSUFFICIENT_INVENTORY`.

When the line is accepted, its `unit_price_cents` is resolved at add time: if the sku is in a `LIVE` exclusive drop, the price is that drop's `drop_price_cents`; otherwise it is the sku's `list_price_cents`. The line's `line_subtotal_cents` is its `unit_price_cents` multiplied by its `quantity`, and the line begins in `RESERVED` status. Adding the line reserves stock — the batch's `quantity_reserved` increases by the line quantity and its `quantity_available` decreases by the same amount, moving the batch `RELEASED → DEPLETED` if availability reaches zero — and reprices the order: its `provisional_total_cents` becomes the sum of `line_subtotal_cents` over the order's non-voided lines, and its `total_quantity` becomes the sum of `quantity` over those same lines. The order's `version` is incremented by one on each line addition, which is exactly what makes concurrent cart edits observable at checkout. Individual lines can be fetched by `order_line_id` or listed and filtered by `order_id`, `sku_id`, or `batch_id`.

The provisional total is a raw sum with no discounts and no shipping. Only lines whose status is `RESERVED` or `SHIPPED` are counted in `provisional_total_cents` and `total_quantity`; lines that have become `VOIDED_RECALL`, `RELEASED`, or `RETURNED` are excluded.

### 3.7. Checkout Pricing, Fulfillment, and Cancellation

**Checkout.** A shopper pays for a `PENDING` order, transitioning it `fulfillment=PENDING → fulfillment=ALLOCATED` and `payment=UNPAID → payment=PAID` in one step. Checkout requires the order to be `PENDING` and `UNPAID`, to contain at least one `RESERVED` line (an order with zero reserved lines is rejected with `ERR_EMPTY_ORDER`), and to pass the optimistic-concurrency check on `expected_order_version` described in §2.7 (`ERR_STALE_VERSION`, HTTP 412). If the `order_type` is `BULK`, the order's `total_quantity` must be at least 50 units; a bulk order below that floor is rejected with `ERR_BULK_MIN_NOT_MET`.

At checkout the final price is computed from the subtotal, which is the `provisional_total_cents` over the reserved lines. A bulk-quantity discount rate is chosen from `total_quantity`: zero when fewer than 50 units, 10 percent when at least 50 and fewer than 100 units, and 20 percent when 100 units or more. A loyalty discount rate is chosen from the customer's `loyalty_tier` read at the checkout instant: `BULK` orders forgo the loyalty discount entirely and take zero; otherwise `BRONZE` takes zero, `SILVER` takes 5 percent, and `GOLD` takes 10 percent. The two rates are added, then capped at a combined maximum of 25 percent. The `discount_cents` is that combined rate applied to the subtotal, rounded half up to whole cents. The discounted subtotal is the subtotal minus `discount_cents`. Shipping is then decided against the discounted subtotal: `shipping_fee_cents` is zero when the discounted subtotal is at least 5000 cents, and otherwise a flat 800 cents. The `final_total_cents` is the discounted subtotal plus `shipping_fee_cents`.

Checkout also posts loyalty points provisionally. The order's `provisional_points` is computed over the order's `RESERVED` lines at checkout (the same lines that form the subtotal — lines already voided by an earlier recall are excluded) as the sum of the per-line floors of `line_subtotal_cents` divided by 100, and that amount is added to the customer's `loyalty_points_balance` immediately. Checkout increments the order's `version` by one.

**Fulfillment.** A `MerchOps` or `PlatformAdmin` operator ships and delivers an `ALLOCATED`, `PAID` order, moving it `fulfillment=ALLOCATED → fulfillment=DELIVERED`. Each `RESERVED` line becomes `SHIPPED`, and for each such line the batch's `quantity_reserved` decreases by the line `quantity` while its `quantity_shipped` increases by the same amount. Fulfillment finalizes loyalty: `awarded_points` is set to the sum of the per-line floors of `line_subtotal_cents` divided by 100 over the lines that are still active (that is, the `SHIPPED` lines, excluding any voided by a recall between checkout and delivery). No separate balance change is applied at delivery — the provisional credit posted at checkout, net of any recall reversals already applied, already equals `awarded_points`, so the running `loyalty_points_balance` is left settled at that value.

**Cancellation.** A `PENDING` or `ALLOCATED` order may be cancelled — by the owning shopper, or by a `MerchOps` or `PlatformAdmin` operator — moving its fulfillment to `CANCELLED`. Cancellation releases inventory and unwinds loyalty: each `RESERVED` line becomes `RELEASED`; per released line, the batch's `quantity_reserved` decreases by the line `quantity` and its `quantity_available` increases by the same amount; and any batch that was `DEPLETED` and now has availability above zero transitions back to `RELEASED`. If the order's `payment_status` was `PAID`, it becomes `REFUNDED` and the customer's `loyalty_points_balance` is reduced by the order's `provisional_points`, reversing the provisional credit.

### 3.8. Returns

Returns are full-order and only apply to delivered orders. A shopper (or `PlatformAdmin`) requests a return against an order by supplying a `reason`; the request captures the target as `order_id` and requires that order's `fulfillment_status` to be `DELIVERED`, otherwise it is rejected with `ERR_ORDER_NOT_DELIVERED`. A new return begins in `REQUESTED` status, with `refund_amount_cents` and `revoked_points` at zero. Returns can be listed and filtered by `order_id`.

A `MerchOps` or `PlatformAdmin` operator adjudicates a requested return. Approving it moves the return `REQUESTED → APPROVED`, and approval additionally requires the underlying order to still be `DELIVERED`. Rejecting it moves the return `REQUESTED → REJECTED` and makes no inventory or loyalty change. Settling an approved return is the terminal, reconciling step: it requires the return to be `APPROVED` and the order to be `DELIVERED`, moves the return `APPROVED → REFUNDED`, and in the same step transitions the order `fulfillment=DELIVERED → fulfillment=RETURNED` and `payment → REFUNDED`. On settlement each `SHIPPED` line becomes `RETURNED` and its units are restocked — the batch's `quantity_shipped` decreases by the line `quantity` and its `quantity_available` increases by the same amount, moving a `DEPLETED` batch back to `RELEASED` if applicable. Settlement sets `refund_amount_cents` equal to the order's `final_total_cents`, sets `revoked_points` equal to the order's `awarded_points`, and reduces the customer's `loyalty_points_balance` by that same `awarded_points`, revoking the delivery credit.

### 3.9. Subscriptions and Recurring Renewal

A shopper (or `PlatformAdmin`) starts a `Subscription` under a customer, which records the owner as `customer_id`, the recurring `sku_id`, the `quantity` per renewal (strictly positive), and the `cadence_days` between renewals (strictly positive). The subscription begins `ACTIVE` with `renewal_count` at zero and `next_renewal_at` set to its `created_at` plus `cadence_days`. Subscriptions can be listed and filtered by `customer_id` or `sku_id`.

The owning shopper controls the subscription's steady state: pausing moves it `ACTIVE → PAUSED`, resuming moves it `PAUSED → ACTIVE`, and cancelling moves it to `CANCELLED` from either `ACTIVE` or `PAUSED`. Cancellation is terminal.

Renewal is an operator-driven cyclic transition (`ACTIVE → ACTIVE`) invoked by `MerchOps` or `PlatformAdmin`. A renewal requires the subscription to be `ACTIVE`, requires the logical clock to have reached or passed `next_renewal_at` (a too-early renewal is rejected with `ERR_SUBSCRIPTION_NOT_DUE`), requires the owning customer to be `ACTIVE` rather than `SUSPENDED` (a suspended customer's renewal is rejected with `ERR_CUSTOMER_SUSPENDED`), and requires an eligible batch to be found by the selector below (otherwise `ERR_NO_ELIGIBLE_BATCH`). On success the renewal creates a `RETAIL` order for the customer containing a single `RESERVED` line for the subscription's sku, batch, and quantity (the line's `unit_price_cents` resolved exactly as at line-add time — the `LIVE` exclusive-drop price if the sku is in one, otherwise the sku's `list_price_cents`); reserves the stock (the selected batch's `quantity_reserved` increases by the quantity and its `quantity_available` decreases by it, depleting the batch if it reaches zero); advances `next_renewal_at` by `cadence_days`; and increments `renewal_count` by one.

The renewal batch selector chooses deterministically. The candidate set is every batch whose `sku_id` equals the subscription's `sku_id`, whose `status` is `RELEASED`, and whose `quantity_available` is at least the subscription's `quantity`. Candidates are ranked by `created_at` ascending — the earliest-produced batch first — with `created_at` as the sole ranking key; the resource `id` is never used as a tiebreaker. The first candidate after ranking is selected. If the candidate set is empty, the renewal fails with `ERR_NO_ELIGIBLE_BATCH` and neither `next_renewal_at` nor `renewal_count` is advanced.

### 3.10. Batch Recall and Its Cascade

A recall is a `MerchOps` or `PlatformAdmin` action that withdraws a batch from the market and unwinds everything downstream of it. A batch can be recalled only from `RELEASED` or `DEPLETED`; the recall moves it to the terminal `RECALLED` status, sets `quantity_recalled` equal to `quantity_produced`, and drives `quantity_available` to zero. The cascade is identical whether the batch was `RELEASED` or `DEPLETED` before the recall.

The cascade proceeds in layers. First, every order line whose `batch_id` is the recalled batch and whose status is `RESERVED` or `SHIPPED`, and whose parent order's `fulfillment_status` is neither `CANCELLED` nor `RETURNED`, is voided to `VOIDED_RECALL`, and its reserved or shipped units are released from the batch. Per voided line, the batch's `quantity_reserved` is decremented by the line `quantity` if that line had been `RESERVED`, or its `quantity_shipped` is decremented by the line `quantity` if that line had been `SHIPPED`. Then, for each affected order, if all of its lines are now `VOIDED_RECALL`, the order's `fulfillment_status` becomes `CANCELLED`, and if its `payment_status` was `PAID` it becomes `REFUNDED`. Finally, posted loyalty for the voided lines is reversed: for an order that had posted provisional points (it was `ALLOCATED`) or awarded points (it was `DELIVERED`), the customer's `loyalty_points_balance` is reduced by the sum, over the voided lines, of the floor of each voided line's `line_subtotal_cents` divided by 100. When a recall voids every line of an order, that reversal equals the order's original `provisional_points`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. State-transition and other modifying operations return `200 OK`, as does the logical-clock control endpoint. All endpoints emit the standard envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/products` | Create a catalog product | MerchOps, PlatformAdmin |
| GET | `/products/{product_id}` | Fetch a product | Customer, MerchOps, PlatformAdmin |
| POST | `/products/{product_id}/skus` | Create a sku variant under a product | MerchOps, PlatformAdmin |
| GET | `/skus/{sku_id}` | Fetch a sku | Customer, MerchOps, PlatformAdmin |
| GET | `/skus` | List skus (filter by `product_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/skus/{sku_id}/batches` | Create a production batch for a sku | MerchOps, PlatformAdmin |
| GET | `/batches/{batch_id}` | Fetch a batch | Customer, MerchOps, PlatformAdmin |
| GET | `/batches` | List batches (filter by `sku_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/batches/{batch_id}/label` | Stamp a batch as safety-labeled | MerchOps, PlatformAdmin |
| POST | `/batches/{batch_id}/release` | Release a batch to sellable inventory | MerchOps, PlatformAdmin |
| POST | `/batches/{batch_id}/recall` | Recall a batch and cascade | MerchOps, PlatformAdmin |
| POST | `/drops` | Create a seasonal drop with listings | MerchOps, PlatformAdmin |
| GET | `/drops/{drop_id}` | Fetch a drop (status reflects the clock) | Customer, MerchOps, PlatformAdmin |
| POST | `/bundles` | Create a gift bundle in DRAFT | MerchOps, PlatformAdmin |
| GET | `/bundles/{bundle_id}` | Fetch a bundle | Customer, MerchOps, PlatformAdmin |
| POST | `/bundles/{bundle_id}/activate` | Activate a bundle | MerchOps, PlatformAdmin |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{customer_id}` | Fetch a customer | Customer, MerchOps, PlatformAdmin |
| POST | `/customers/{customer_id}/suspend` | Suspend a customer | PlatformAdmin |
| POST | `/customers/{customer_id}/loyalty-grant` | Grant loyalty points | PlatformAdmin |
| POST | `/customers/{customer_id}/orders` | Create a cart order for the customer | Customer, PlatformAdmin |
| GET | `/orders/{order_id}` | Fetch an order with computed totals | Customer, MerchOps, PlatformAdmin |
| GET | `/orders` | List orders (filter by `customer_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/orders/{order_id}/lines` | Add a line to a pending order | Customer, PlatformAdmin |
| GET | `/order-lines/{order_line_id}` | Fetch a single order line | Customer, MerchOps, PlatformAdmin |
| GET | `/order-lines` | List order lines (filter by `order_id`, `sku_id`, `batch_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/orders/{order_id}/checkout` | Pay for the order (OCC guarded) | Customer, PlatformAdmin |
| POST | `/orders/{order_id}/fulfill` | Ship and deliver the order | MerchOps, PlatformAdmin |
| POST | `/orders/{order_id}/cancel` | Cancel a pending/allocated order | Customer, MerchOps, PlatformAdmin |
| POST | `/orders/{order_id}/returns` | Request a full-order return | Customer, PlatformAdmin |
| GET | `/returns/{return_id}` | Fetch a return | Customer, MerchOps, PlatformAdmin |
| GET | `/returns` | List returns (filter by `order_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/returns/{return_id}/approve` | Approve a requested return | MerchOps, PlatformAdmin |
| POST | `/returns/{return_id}/reject` | Reject a requested return | MerchOps, PlatformAdmin |
| POST | `/returns/{return_id}/settle` | Settle an approved return | MerchOps, PlatformAdmin |
| POST | `/customers/{customer_id}/subscriptions` | Create a recurring subscription | Customer, PlatformAdmin |
| GET | `/subscriptions/{subscription_id}` | Fetch a subscription | Customer, MerchOps, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions (filter by `customer_id`, `sku_id`) | Customer, MerchOps, PlatformAdmin |
| POST | `/subscriptions/{subscription_id}/pause` | Pause an active subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{subscription_id}/resume` | Resume a paused subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{subscription_id}/cancel` | Cancel a subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{subscription_id}/renew` | Run a due renewal | MerchOps, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_SKU_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_DROP_NOT_FOUND` | 404 |
| `ERR_BUNDLE_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BATCH_NOT_RELEASED` | 409 |
| `ERR_ORDER_NOT_EDITABLE` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_SUBSCRIPTION_NOT_DUE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SAFETY_LABEL_REQUIRED` | 409 |
| `ERR_DROP_NOT_LIVE` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_DROP_WINDOW_OVERLAP` | 409 |
| `ERR_BATCH_LINE_CONFLICT` | 409 |
| `ERR_EMPTY_BUNDLE` | 422 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_NO_ELIGIBLE_BATCH` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_BULK_MIN_NOT_MET` | 422 |
| `ERR_VALIDATION` | 400 |
