# Coffee Roaster Wholesale API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Coffee Roaster Wholesale API, the operational backbone for a specialty roaster that sells to cafes and other wholesale buyers. The system has to reconcile two worlds that rarely move at the same pace: a production floor where finite green coffee is received, planned into roast batches, charged into a drum, and weighed out as roasted lots; and a commercial desk where wholesale accounts place orders, subscribe to recurring deliveries, sample new coffees, and settle invoices on net terms. Between these worlds sits a hard physical constraint — coffee has a roast date, and a roasted lot is only shippable while it is fresh.

The central challenge the API solves is keeping finite inventory honest under concurrent demand. Green kilograms are reserved the moment a batch is planned and consumed the moment it starts roasting; roasted kilograms are reserved the moment a shipment is staged and consumed the moment it ships. Because two operators may be looking at the same lot at the same time, the system protects the green and roasted pools with optimistic concurrency control so that no lot is ever over-reserved against a stale view of its availability. Layered on top of inventory is a pricing and credit engine: every order is priced against the account's tier, every invoice ages against its net terms, and an account that drifts past its credit ceiling or lets an invoice go overdue is placed on hold. The sections that follow define the response contract, the system-wide principles, and the detailed business workflows that an implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `RoasterStaff`, `SalesRep`, and `WholesaleBuyer`.

`RoasterStaff` operate the production side: they receive green lots, author roast profiles, plan and run roast batches, manage roasted inventory, ship fulfillments, and record cupping decisions on sample requests. `SalesRep` operate the commercial side: they manage price tiers and accounts, create and cancel orders, reserve and cancel fulfillments, issue invoices, apply payments, drive the standing-order lifecycle, and convert approved samples into orders. Both `RoasterStaff` and `SalesRep` are operator identities: when `X-User-Role` is `RoasterStaff` or `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier internally but it does not compare it to any entity's `id`, and these two roles act across all accounts without ownership restriction.

`WholesaleBuyer` is different. When `X-User-Role` is `WholesaleBuyer`, `X-User-ID` is the `id` of the acting `WholesaleAccount`; the buyer acts as their own account. Any ownership check on a resource that references a `WholesaleAccount` — an order, a standing order, a sample request, an invoice, a fulfillment under one of those orders, or the account record itself — compares that resource's owning-account foreign key to `X-User-ID`. A `WholesaleBuyer` whose `X-User-ID` does not match the targeted account's `id` (or the owning account of the targeted child resource) is rejected with `ERR_FORBIDDEN`. A `WholesaleBuyer` may place orders, create standing orders and sample requests, pause, resume, and cancel their own standing orders, and read their own account's data, but may not perform any production, pricing, invoicing, fulfillment-reservation, sample-review, or sample-conversion operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0. Out-of-range or non-integer values are not rejected: a `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100, a negative `offset` is clamped up to 0, and any value that does not parse as an integer falls back to its default.

Unless an endpoint explicitly states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Almost every resource in the system carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix; clients never supply it. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification; it is refreshed on every mutation. The `version` is an integer that begins at `1` on creation and increments by one on every mutation of the resource — including mutations that only touch computed fields — and it is the value the optimistic-concurrency mechanism in §2.6 checks against.

One entity is deliberately leaner. A `Payment` is an append-only event: once created it is never modified, so a `Payment` carries only `id` and `created_at`. It has no `updated_at` and no `version`. Every other entity — price tiers, accounts, roast profiles, products, green lots, roast batches, roasted lots, standing orders, orders, fulfillments, sample requests, and invoices — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

When a path identifies a nested resource, the server validates the identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. A request for a standing order under a non-existent account, for instance, fails on the account before the standing order is ever examined. The same left-to-right existence discipline applies to foreign keys named in a request body: a referenced account, product, green lot, roasted lot, roast profile, price tier, order, invoice, batch, fulfillment, standing order, sample request, or payment that does not exist yields `ERR_NOT_FOUND`.

### 2.5. Quantities, Money, and Rounding

Weights in this system are kilograms carried to three decimal places, and every kilogram quantity that the system computes is rounded half-up to three decimals. Computed inventory quantities — a green lot's on-hand, reserved, and available kilograms, and a roasted lot's reserved, on-hand, and available kilograms — are never allowed to go negative; whenever a subtraction would produce a value below zero the result is clamped to zero.

Monetary amounts are always integer cents. Per-line pricing is rounded half-up to whole cents and the tier discount is rounded half-up to whole cents; because every monetary summand is already an integer, the sums and differences that follow require no further rounding. Basis-point fields — a tier's discount and a profile's expected shrink — express fractions of a whole in ten-thousandths, so a discount expressed as a basis-point value is converted to a fraction by dividing by ten thousand before it multiplies a money or weight amount.

### 2.6. Optimistic Concurrency on the Inventory Pools

Two operations draw down finite inventory pools and are therefore guarded by optimistic concurrency control, because a second writer acting on a pool another writer has already drawn from would otherwise overbook it.

Planning a roast batch reserves green kilograms on a green lot. The batch-creation request must carry `expected_green_lot_version` holding the `version` of the target `GreenLot` that the client last observed. If that value does not equal the green lot's current `version` — because another batch creation has already reserved green from the same lot and advanced its version since the client read it — the create is refused with `ERR_STALE_VERSION` (HTTP 412) rather than over-reserving the finite green pool.

Reserving roasted kilograms against a roasted lot works the same way. The fulfillment-reservation request must carry `expected_roasted_lot_version` holding the `version` of the target `RoastedLot` that the client last observed. If that value does not equal the roasted lot's current `version` — because a prior reservation has already consumed available kilograms and advanced the lot's version — the reservation is refused with `ERR_STALE_VERSION` (HTTP 412) rather than overbooking the lot against a stale view of its available kilograms. These are the only two endpoints that take a version field; no other endpoint accepts or requires one.

### 2.7. The Green-Coffee Pool and Par-Based Reorder

A green lot is the finite physical pool from which all roasting draws, and the system keeps three derived quantities on it in sync at all times. The `on_hand_kg` is the lot's `received_kg` less the green actually charged into every one of its batches that has reached `ROASTING`, `COOLING`, or `COMPLETED` (the charged amount is each such batch's `actual_green_kg`), rounded half-up to three decimals and clamped at zero. The `reserved_kg` is the sum of `planned_green_kg` over every batch of the lot still in `PLANNED`, rounded half-up to three decimals. The `available_kg` is `on_hand_kg` minus `reserved_kg`, rounded half-up to three decimals and clamped at zero.

Each green lot carries a `par_level_kg` threshold that flags when the lot is running low. The lot's `reorder_status` is `BELOW_PAR` when `available_kg` is strictly less than `par_level_kg`, and `OK` otherwise; the boundary is inclusive on the safe side, so a lot whose available kilograms exactly equal its par level reads `OK`. This status is recomputed on green-lot creation and on every batch event that changes the lot's reserved or on-hand kilograms — planning, starting, cancelling, or completing a batch.

### 2.8. Roasted-Lot Availability and the Freshness Window

A roasted lot tracks the inverse accounting against shipments. Its `reserved_kg` is the sum of `allocated_kg` over every fulfillment referencing the lot that is in `RESERVED` or `SHIPPED`, rounded half-up to three decimals. Its `on_hand_kg` is the lot's `produced_kg` less the sum of `allocated_kg` over fulfillments that have reached `SHIPPED`, rounded half-up to three decimals and clamped at zero. Its `available_kg` is `produced_kg` minus `reserved_kg`, rounded half-up to three decimals and clamped at zero. A reservation thus reduces available kilograms immediately, while on-hand kilograms only fall once the shipment actually ships.

Freshness is governed by the lot's `roast_date`. A roasted lot may only be allocated to a shipment while its age in whole days does not exceed the effective freshness ceiling for that order's account, where the effective ceiling is the smaller of the product's `freshness_window_days` and the account's price tier's `freshness_max_days`. The exact rule lives in §3 with the fulfillment workflow it guards.

### 2.9. Credit, Net Terms, and the Account Ledger

Each wholesale account carries a running `outstanding_balance_cents`, which is the sum of `amount_due_cents` over the account's invoices whose status is `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE`; fully `PAID` invoices are excluded. This posted balance is recomputed whenever an invoice is issued, a payment clears, an aging sweep runs, or an account is read. An account also carries a `credit_limit_cents` ceiling and a `status` of either `ACTIVE` or `CREDIT_HOLD`. The relationship between the posted balance, a candidate order, the credit ceiling, and the hold status is detailed in the invoicing and aging workflows in §3.

### 2.10. State Reconciliation and Cascades

Many operations mutate more than one entity at once, and the system performs these reconciliations immediately and synchronously. When a roast batch consumes or releases green, the owning green lot's computed quantities and reorder status are recomputed in the same operation. When a fulfillment reserves, ships, or cancels, the referenced roasted lot's computed quantities are recomputed and the owning order's `fulfillment_status` is re-derived from its children. When an invoice is issued or a payment clears, the owning account's outstanding balance is recomputed, and an account may move between `ACTIVE` and `CREDIT_HOLD` as a consequence. Each such reconciliation that changes a resource is itself a mutation of that resource: it refreshes the resource's `updated_at` and increments its `version`. The precise cascades — which entity bumps which, and in what order — are specified alongside the workflows that trigger them in §3.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalog: Tiers, Profiles, and Products

Before any commerce can happen, a `SalesRep` establishes the pricing structure by creating **price tiers**. A tier is created with a `code` (its short label, such as BRONZE or SILVER), a `discount_bps` discount expressed in basis points, a `min_monthly_kg` minimum committed monthly volume that qualifies an account for the tier, and a `freshness_max_days` ceiling that caps how old a roasted lot may be when shipped to accounts on this tier. A tier's `discount_bps` must lie between 0 and 3000 inclusive. A newly created tier is not archived; its `archived` flag starts false. Tiers can be soft-deleted by archiving, and archived tiers are excluded from the default tier listing unless the caller explicitly asks to include them via the `archived` filter. A tier's `code` must be unique among tiers that are not archived; a collision is rejected with `ERR_DUPLICATE`.

On the production catalog side, a `RoasterStaff` authors **roast profiles**. A profile carries a `name`, a `roast_level` of `LIGHT`, `MEDIUM`, or `DARK`, an `expected_shrink_bps` that records the expected roasting weight loss in basis points (which must lie between 500 and 2500 inclusive), and a `charge_temp_c` drum charge temperature in Celsius. Roast profiles can be filtered by `roast_level` when listed.

A **product** ties the commercial and production worlds together and may be created by either a `SalesRep` or a `RoasterStaff`. A product is created with a `sku`, a `name`, a `roast_profile_id` naming the roast profile every batch for this product must use, a `base_price_cents_per_kg` list price before any tier discount, and a `freshness_window_days` that caps how many days past its roast date a roasted lot of this product remains shippable independent of any tier ceiling. A newly created product has its `archived` flag false. A product's `sku` must be unique among non-archived products; a duplicate is rejected with `ERR_DUPLICATE`. Archiving a product sets its `archived` flag true so that it can no longer be added to new order lines; this is a modification of the existing product. Products can be listed filtered by `roast_profile_id` or by `archived`, and the default product listing excludes archived products.

### 3.2. Onboarding Accounts and Their Standing Orders

A `SalesRep` opens a **wholesale account** by supplying the cafe's `name`, the `price_tier_id` of the tier that will govern its pricing and freshness ceiling, the `net_terms_days` payment window, and the `credit_limit_cents` ceiling. The `net_terms_days` value must be one of 0, 15, 30, 45, or 60; any other value is an invalid request. On creation the account's `outstanding_balance_cents` is initialized to zero and its `status` is `ACTIVE`. Reading an account recomputes and returns its current `outstanding_balance_cents`. Accounts can be listed filtered by `price_tier_id` or by `status`.

An account can subscribe to recurring deliveries through a **standing order**, created by a `SalesRep` or by the owning `WholesaleBuyer` acting on their own account. The creator supplies the `product_id` of the recurring product, the `qty_kg` generated each cycle, the `cadence_days` between generated orders, and the `next_release_at` timestamp at or after which the first cycle may be released. The `cadence_days` value must be one of 7, 14, or 28; any other value is an invalid request. The standing order records its owning `account_id`, starts in `ACTIVE` status with a `cycles_released` count of zero, and is addressable both under its account and in the global standing-order listing (which can be filtered by `product_id`, `account_id`, or `status`).

Releasing the next cycle of a standing order is a `SalesRep` action that keeps the order in `ACTIVE` (a cyclic self-loop) while spinning off a child order. A release is permitted only when the standing order is itself `ACTIVE`; an attempt to release a `PAUSED` or `CANCELLED` standing order is rejected with `ERR_INVALID_STATE`. Releasing also requires that the logical clock has reached or passed `next_release_at`; releasing before then is rejected with `ERR_RELEASE_NOT_DUE`. The owning account must be `ACTIVE` (not on credit hold) — a release against an account on `CREDIT_HOLD` is rejected with `ERR_INVALID_STATE` — and the subscribed product must not be archived; a release against an archived product is rejected with `ERR_PRODUCT_MISMATCH`. When all of these hold, the release creates a new order for the account with a single line for the standing order's `product_id` and `qty_kg`, priced against the account's tier; advances `next_release_at` forward by `cadence_days` days; increments `cycles_released` by one; and increments the standing order's `version` by one. The generated order records the originating `standing_order_id`.

A standing order can be paused by a `SalesRep` or the owning `WholesaleBuyer`, moving it from `ACTIVE` to `PAUSED`; pausing anything not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A paused standing order can be resumed, moving it from `PAUSED` back to `ACTIVE`; resuming anything not `PAUSED` is rejected with `ERR_INVALID_STATE`. A standing order can be cancelled from either `ACTIVE` or `PAUSED`, moving it to the terminal `CANCELLED`; cancelling from any other state is rejected with `ERR_INVALID_STATE`. Pause, resume, and cancel each increment the standing order's `version` by one. Pause, resume, and cancel are available to both a `SalesRep` and the owning `WholesaleBuyer`.

### 3.3. Green Inventory and the Roast Batch Lifecycle

A `RoasterStaff` receives a **green lot** into inventory by supplying its `origin`, a supplier `lot_ref` reference, the `received_kg` total green kilograms, and a `par_level_kg` reorder threshold. The `lot_ref` must be unique among green lots that are not yet depleted; a collision is rejected with `ERR_DUPLICATE`. On receipt the lot's `on_hand_kg` equals `received_kg`, its `reserved_kg` is zero, its `available_kg` equals `received_kg`, and its `reorder_status` is computed per §2.7. Green lots can be listed filtered by `reorder_status`, and each lot exposes the roast batches that draw from it.

A **roast batch** is the unit of production. A `RoasterStaff` plans a batch by supplying the `green_lot_id` it draws from, the `product_id` it will yield, the `planned_green_kg` it intends to charge, and the `expected_green_lot_version` for the optimistic-concurrency check of §2.6. At creation the batch copies the product's roast profile into its own `roast_profile_id` and pins it for the life of the batch, so the batch's profile never drifts even if the product is later re-pointed. The batch also computes a forward yield estimate: its `planned_roasted_kg` is `planned_green_kg` multiplied by one minus the profile's `expected_shrink_bps` divided by ten thousand, rounded half-up to three decimals. Planning a batch reserves `planned_green_kg` on the green lot — the batch starts in `PLANNED`, so this amount immediately counts toward the lot's `reserved_kg` — and recomputes the green lot's `reserved_kg`, `available_kg`, and `reorder_status`, then increments the green lot's `version` by one. A batch's `actual_green_kg` and `actual_roasted_kg` are both empty until the relevant later transitions populate them; its `actual_shrink_bps` and `roast_date` are likewise empty until completion. Roast batches can be listed and filtered by `product_id`, by `roast_profile_id`, or by `status`.

Starting a batch advances it from `PLANNED` to `ROASTING` and is the moment reservation becomes consumption. The `RoasterStaff` supplies the `actual_green_kg` actually charged, which must be greater than zero and must not exceed the green lot's current `on_hand_kg` — charging more green than physically on hand is rejected with `ERR_INSUFFICIENT_GREEN`. Starting from any state other than `PLANNED` is rejected with `ERR_INVALID_STATE`. On a successful start the batch's `actual_green_kg` is recorded, the green lot's reservation of `planned_green_kg` is dropped (the batch has left `PLANNED`) while its consumption rises by `actual_green_kg`, the green lot's `on_hand_kg`, `reserved_kg`, `available_kg`, and `reorder_status` are recomputed, and the batch's `version` increments by one.

Dropping a batch advances it from `ROASTING` to `COOLING`; dropping anything not in `ROASTING` is rejected with `ERR_INVALID_STATE`, and the drop increments the batch's `version` by one. From `COOLING` the roaster has two onward paths. The first is a re-roast: a cooling batch can be sent back to `ROASTING` for a bounded development re-pass, which increments an internal re-roast counter and the batch's `version`. Re-roasting is only allowed while the batch is in `COOLING` and while the re-roast count is below the cap of two; a re-roast attempt from a non-`COOLING` state or once the cap has been reached is rejected with `ERR_INVALID_STATE`. The second path is completion.

Completing a batch advances it from `COOLING` to the terminal `COMPLETED`. The `RoasterStaff` supplies the `actual_roasted_kg` weighed out, which must be greater than zero. A roast cannot gain weight, so `actual_roasted_kg` must not exceed the batch's `actual_green_kg`; a violation is rejected with `ERR_WEIGHT_GAIN`. Completing from any state other than `COOLING` is rejected with `ERR_INVALID_STATE`. On completion the system records `actual_roasted_kg`; computes the batch's `actual_shrink_bps` as one minus the ratio of `actual_roasted_kg` to `actual_green_kg`, multiplied by ten thousand, rounded half-up to a whole number; stamps `roast_date` to the current clock; and increments the batch's `version` by one. Completion also cascades a child **roasted lot** into existence, copying the producing batch's `roast_batch_id`, the `product_id`, the `roast_date`, and a `produced_kg` equal to the batch's `actual_roasted_kg`. The roasted lot's availability fields then follow §2.8. A roasted lot's producing batch exposes the lots it created, and roasted lots can be listed and filtered by `product_id`.

A `PLANNED` batch that is no longer wanted can be cancelled, moving it to the terminal `CANCELLED`. Cancelling is only allowed from `PLANNED`; cancelling from any other state is rejected with `ERR_INVALID_STATE`. Cancellation releases the batch's `planned_green_kg` reservation and recomputes the green lot's `reserved_kg`, `available_kg`, and `reorder_status`, then increments the batch's `version` by one.

### 3.4. Ordering and Tier Pricing

A wholesale order can originate three ways — placed directly, released by a standing order, or converted from an approved sample — and in every case it is priced the same way against the account's tier. A `SalesRep` or the owning `WholesaleBuyer` places an order against an account by supplying the `lines`, an array of line items each naming a `product_id` and a `qty_kg`, where every `qty_kg` must be greater than zero and no archived product may appear on a new line. The order records its owning `account_id`, starts with `fulfillment_status` of `OPEN` and `billing_status` of `UNBILLED`, and (when generated by a subscription) records its `standing_order_id`; a directly placed order has no standing order.

Pricing is computed in a pinned order that matters for rounding. First, each line's contribution is `qty_kg` multiplied by that product's `base_price_cents_per_kg`, rounded half-up to whole cents per line. The order's `subtotal_cents` is the sum of these already-rounded per-line amounts — the per-line rounding happens first, then the summation, never the other way around. The order's `discount_cents` is the `subtotal_cents` multiplied by the tier's `discount_bps` divided by ten thousand, rounded half-up to whole cents, applied once to the whole-order subtotal rather than line by line. The order's `total_cents` is `subtotal_cents` minus `discount_cents`. Orders can be listed under an account or globally, filtered by `fulfillment_status`, `billing_status`, `standing_order_id`, or `account_id`.

An order's two status dimensions move independently. The `fulfillment_status` is driven by shipments and is described in §3.5; the `billing_status` is driven by invoicing and is described in §3.6. An open order can be cancelled by a `SalesRep` or the owning `WholesaleBuyer`, moving its `fulfillment_status` to the terminal `CANCELLED`. Cancellation is only permitted while the order's `fulfillment_status` is `OPEN` and its `billing_status` is still `UNBILLED` (no invoice has been issued for it); an attempt to cancel an order that is not open and unbilled is rejected with `ERR_INVALID_STATE`. Cancelling an order also cancels every `RESERVED` fulfillment on it, and each such cancellation releases that fulfillment's roasted-lot reservation so the roasted lot's `reserved_kg` and `available_kg` recompute; the order's `version` increments by one.

### 3.5. Fulfillment, Allocation, and Freshness

Shipping an order is a two-step reservation-then-ship flow that lets the commercial and production sides hand off cleanly. A `SalesRep` reserves a **fulfillment** against an order by supplying the `product_id` of the order line being shipped, the `roasted_lot_id` of the lot to draw from, the `allocated_kg` to draw, and the `expected_roasted_lot_version` for the optimistic-concurrency check of §2.6. The `allocated_kg` must be greater than zero. The reservation is gated by several checks. The order must be in `OPEN` or `PARTIALLY_FULFILLED` (a `FULFILLED` or `CANCELLED` order takes no new shipments), or the reservation is rejected with `ERR_INVALID_STATE`. The roasted lot's `product_id` must equal the fulfillment's `product_id` — you cannot ship the wrong coffee — or the reservation is rejected with `ERR_PRODUCT_MISMATCH`; the fulfillment's `product_id` must also name a product that appears on one of the order's lines, and a `product_id` that matches no order line is likewise rejected with `ERR_PRODUCT_MISMATCH`. The lot must have enough unreserved stock: its `available_kg` must be at least `allocated_kg`, and the new allocation must not push the cumulative reserved-plus-shipped kilograms for that line's product above the line's ordered `qty_kg`; either shortfall is rejected with `ERR_INSUFFICIENT_ROASTED`.

The reservation is also freshness-gated. The lot's age in whole days is the floor of the difference between the current clock and the lot's `roast_date`, taken in seconds and divided by 86,400 seconds per day. The effective ceiling is the smaller of the product's `freshness_window_days` and the freshness ceiling of the order account's price tier, namely its `freshness_max_days`. The lot is eligible only when its age in whole days is at most that effective ceiling; an age equal to the ceiling is still eligible, while an age one day beyond it is stale and the reservation is rejected with `ERR_STALE_ROAST`. When all gates pass, the fulfillment is created in `RESERVED`, its `roast_date` is copied from the roasted lot, the roasted lot's `reserved_kg` and `available_kg` recompute, the roasted lot's `version` increments by one, and the order's `version` increments by one. Fulfillments can be listed under an order or globally, filtered by `roasted_lot_id`, `product_id`, or `status`.

Shipping a reserved fulfillment is a `RoasterStaff` action that advances it from `RESERVED` to the terminal `SHIPPED`; shipping anything not in `RESERVED` is rejected with `ERR_INVALID_STATE`. On ship, the reservation becomes consumption: the roasted lot's `on_hand_kg` decreases by `allocated_kg` while its `reserved_kg` and `available_kg` recompute, and the owning order's `fulfillment_status` is re-derived by bubbling up from its shipped children, then the order's `version` increments by one. The bubble-up rule is precise. If, after this shipment, every order line has its full ordered `qty_kg` covered by `SHIPPED` allocations of that product, the order becomes `FULFILLED` — whether it reaches that state in a single covering shipment straight from `OPEN` or as the final shipment from `PARTIALLY_FULFILLED`. If at least one line has some but not all of its ordered kilograms shipped, with no line over-shipped, and the order is not yet fully covered, the order is `PARTIALLY_FULFILLED`. Both `FULFILLED` and `CANCELLED` are terminal for the fulfillment dimension.

A reserved fulfillment that is no longer wanted can be cancelled by a `SalesRep`, moving it from `RESERVED` to the terminal `CANCELLED`; cancelling anything not in `RESERVED` is rejected with `ERR_INVALID_STATE`. Cancellation releases the roasted-lot reservation so the lot's `reserved_kg` and `available_kg` recompute, and the order's `version` increments by one.

### 3.6. Invoicing, Net Terms, and Aging

Once an order has begun shipping it can be billed. Issuing an **invoice** is a `SalesRep` action that drives the order's `billing_status` from `UNBILLED` to the terminal `INVOICED`. Three preconditions guard the issue, and they are evaluated together as the credit gate. The order must still be `UNBILLED`, or the request is rejected with `ERR_INVALID_STATE`. At least one fulfillment must have shipped — the order's `fulfillment_status` must be `PARTIALLY_FULFILLED` or `FULFILLED` — otherwise the order has shipped nothing to bill and the issue is rejected with `ERR_INVALID_STATE`. Finally, the account's credit must accommodate the order: the account must be `ACTIVE`, and the account's current posted `outstanding_balance_cents` plus this order's `total_cents` must not exceed the account's `credit_limit_cents`. This is the projected balance — the posted balance plus the candidate order's total, computed before the invoice exists, so a credit decision can differ from the posted view for otherwise-identical invoice data. If the account is on `CREDIT_HOLD` or the projected balance would exceed the ceiling, the issue is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

When the credit gate passes, the system creates a child invoice copying the order's `total_cents` into the invoice's `amount_cents`, stamps `issued_at` to the current clock, pins `due_at` to `issued_at` plus the account's `net_terms_days` days, and starts the invoice in `ISSUED`. The invoice records its owning `account_id` and the billed `order_id`. The order's `billing_status` becomes `INVOICED`, the account's `outstanding_balance_cents` is recomputed, and the order's `version` increments by one. An invoice tracks its `paid_cents` as the sum of `amount_cents` over its cleared payments and its `amount_due_cents` as `amount_cents` minus `paid_cents`, never negative. Invoices can be listed under an account or globally, filtered by `order_id`, `account_id`, or `status`.

A **payment** is applied to an invoice by a `SalesRep` supplying the `amount_cents` to apply, which must be greater than zero. A payment is recorded as an append-only event with `status` `CLEARED` and is never reversed; it records the `invoice_id` it paid. The applied amount may not exceed the invoice's current `amount_due_cents` — overpayment, where the amount is not within the half-open range from just above zero up to and including the amount due, is rejected with `ERR_OVERPAYMENT`. A payment may be applied to an invoice that is `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID`. A partial payment (strictly less than the amount due) on an `ISSUED` invoice moves it to `PARTIALLY_PAID`; a payment that exactly equals the amount due moves an `ISSUED`, `OVERDUE`, or `PARTIALLY_PAID` invoice to the terminal `PAID` with `amount_due_cents` of zero. Each payment recomputes the invoice's `paid_cents` and `amount_due_cents` and recomputes the owning account's `outstanding_balance_cents`. When a payment clears an invoice in full and the account had been on `CREDIT_HOLD` but is now back under its limit with no overdue invoices, the account returns to `ACTIVE`. Payments on an invoice can be listed.

Time advances through a test-driving clock capability. One capability sets the simulated current UTC clock to a supplied `to_iso8601` instant without itself running any aging. A second capability advances the clock to a supplied `to_iso8601` instant and then runs the invoice aging sweep. During the sweep, any invoice that is `ISSUED` or `PARTIALLY_PAID`, whose pinned `due_at` the clock has now passed (the clock is strictly later than `due_at`), and which still has a positive `amount_due_cents`, is moved to `OVERDUE`. As a consequence of aging, an account that now has any `OVERDUE` invoice, or whose `outstanding_balance_cents` exceeds its `credit_limit_cents`, is cascaded to `CREDIT_HOLD`. Both clock capabilities are available to `SalesRep` and `RoasterStaff` for driving the simulation.

### 3.7. Samples, Cupping, and Conversion

A prospective or existing relationship often begins with a **sample request**. A `SalesRep` or the owning `WholesaleBuyer` creates one against an account by supplying the `product_id` to sample and the `sample_kg` sample size. The request records its owning `account_id`, starts in `REQUESTED`, and leaves its `cupping_score` empty until review. Sample requests can be listed under an account or globally, filtered by `product_id`, `account_id`, or `status`.

Reviewing a sample request is a `RoasterStaff` action that forks the request. The reviewer supplies a `decision` of either APPROVE or DECLINE along with a `cupping_score` between 0 and 100. Reviewing is only allowed while the request is `REQUESTED`; reviewing in any other state is rejected with `ERR_INVALID_STATE`. On an APPROVE decision the request moves from `REQUESTED` to `APPROVED`, recording the supplied `cupping_score`, and the request's `version` increments by one. On a DECLINE decision the request moves from `REQUESTED` to the terminal `DECLINED`, likewise recording the supplied `cupping_score`, and the request's `version` increments by one; a declined sample carries no further order eligibility. The two branches are symmetric in everything but their target state and the eligibility a declined request forfeits.

Converting an approved sample into an order is a `SalesRep` action that moves the request from `APPROVED` to the terminal `CONVERTED`. The converter supplies the `qty_kg` for the resulting order. Conversion is only allowed while the request is `APPROVED`, or it is rejected with `ERR_INVALID_STATE`. The recorded `cupping_score` must be at least 80 — the minimum conversion score, and a conversion whose recorded score falls below 80 is rejected with `ERR_INVALID_STATE` — and the sampled product must not be archived; an archived product blocks the conversion with `ERR_PRODUCT_MISMATCH`. When these hold, conversion cascades the creation of a new order for the account with a single line for the sampled `product_id` and the supplied `qty_kg`, priced against the account's tier exactly as in §3.4, and increments the sample request's `version` by one.

### 3.8. Validation Ordering Across Endpoints

When a single request could trip several checks, the system evaluates them in a fixed priority order so that the reported error is deterministic. Authentication comes first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` before anything else is considered. Authorization comes next: a role not permitted for the operation — including a `WholesaleBuyer` reaching for another account's resources — yields `ERR_FORBIDDEN`. Existence comes third: any path or body resource that does not resolve, validated left-to-right through the path, yields `ERR_NOT_FOUND`. Request well-formedness comes fourth: a missing or malformed body, a bad enum member, a non-positive quantity where a positive one is required, or a disallowed `net_terms_days`, `cadence_days`, or `roast_level` yields `ERR_INVALID_REQUEST`. Uniqueness comes fifth, applying to tier-, product-, and green-lot creation: a colliding `code`, `sku`, or `lot_ref` yields `ERR_DUPLICATE`.

Only after those five system-wide gates pass does the system evaluate the operation's own business rules. State validity is the sixth gate: a transition attempted from a state the resource is not in yields `ERR_INVALID_STATE` on any action endpoint. The remaining business checks then apply per operation — referential compatibility (`ERR_PRODUCT_MISMATCH`), freshness (`ERR_STALE_ROAST`), release timing (`ERR_RELEASE_NOT_DUE`), green sufficiency (`ERR_INSUFFICIENT_GREEN`), roasted sufficiency and line over-allocation (`ERR_INSUFFICIENT_ROASTED`), roast weight conservation (`ERR_WEIGHT_GAIN`), the credit ceiling (`ERR_CREDIT_LIMIT_EXCEEDED`), and payment sanity (`ERR_OVERPAYMENT`). The optimistic-concurrency check (`ERR_STALE_VERSION`) guards the two version-bearing writes described in §2.6. This ordering means that, for example, a request that is both forbidden and references a non-existent resource reports the forbidden error, not the not-found one.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection — a price tier, an account, a product, a green lot, a roast batch, a standing order, an order, a fulfillment, a sample request, an invoice, or a payment — return a `201 Created` status code. Operations that modify an existing resource, including state transitions, archival, and the test-driving clock controls, return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in the §3 narratives; the table below is only a routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/price-tiers` | Create a price tier | SalesRep |
| GET | `/price-tiers` | List price tiers (excludes archived by default) | SalesRep, RoasterStaff |
| GET | `/price-tiers/{id}` | Get a price tier | SalesRep, RoasterStaff |
| POST | `/accounts` | Create a wholesale account | SalesRep |
| GET | `/accounts` | List wholesale accounts | SalesRep, RoasterStaff |
| GET | `/accounts/{id}` | Get an account | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/roast-profiles` | Create a roast profile | RoasterStaff |
| GET | `/roast-profiles` | List roast profiles | RoasterStaff, SalesRep |
| GET | `/roast-profiles/{id}` | Get a roast profile | RoasterStaff, SalesRep |
| POST | `/products` | Create a product | SalesRep, RoasterStaff |
| GET | `/products` | List products (excludes archived by default) | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/products/{id}` | Get a product | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/products/{id}/archive` | Archive a product | SalesRep, RoasterStaff |
| POST | `/green-lots` | Receive a green-coffee lot | RoasterStaff |
| GET | `/green-lots` | List green lots | RoasterStaff, SalesRep |
| GET | `/green-lots/{id}` | Get a green lot | RoasterStaff, SalesRep |
| GET | `/green-lots/{id}/roast-batches` | List roast batches drawing from this green lot | RoasterStaff, SalesRep |
| POST | `/roast-batches` | Plan a roast batch (OCC on green lot) | RoasterStaff |
| GET | `/roast-batches` | List roast batches | RoasterStaff, SalesRep |
| GET | `/roast-batches/{id}` | Get a roast batch | RoasterStaff, SalesRep |
| POST | `/roast-batches/{id}/start` | Start roasting; record charged green | RoasterStaff |
| POST | `/roast-batches/{id}/drop` | Drop the roast to cooling | RoasterStaff |
| POST | `/roast-batches/{id}/reroast` | Send a cooling batch back for a bounded re-roast | RoasterStaff |
| POST | `/roast-batches/{id}/complete` | Complete the roast; create roasted lot | RoasterStaff |
| POST | `/roast-batches/{id}/cancel` | Cancel a planned batch; release green | RoasterStaff |
| GET | `/roast-batches/{id}/roasted-lots` | List roasted lots produced by this batch | RoasterStaff, SalesRep |
| GET | `/roasted-lots` | List roasted lots | RoasterStaff, SalesRep |
| GET | `/roasted-lots/{id}` | Get a roasted lot | RoasterStaff, SalesRep |
| POST | `/accounts/{id}/standing-orders` | Create a standing order for an account | SalesRep, WholesaleBuyer |
| GET | `/accounts/{id}/standing-orders` | List standing orders for an account | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/standing-orders` | List standing orders | SalesRep, RoasterStaff |
| GET | `/standing-orders/{id}` | Get a standing order | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/standing-orders/{id}/release` | Release the next cycle (generate an order) | SalesRep |
| POST | `/standing-orders/{id}/pause` | Pause a standing order | SalesRep, WholesaleBuyer |
| POST | `/standing-orders/{id}/resume` | Resume a paused standing order | SalesRep, WholesaleBuyer |
| POST | `/standing-orders/{id}/cancel` | Cancel a standing order | SalesRep, WholesaleBuyer |
| POST | `/accounts/{id}/orders` | Create a wholesale order for an account | SalesRep, WholesaleBuyer |
| GET | `/accounts/{id}/orders` | List orders for an account | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/orders` | List orders | SalesRep, RoasterStaff |
| GET | `/orders/{id}` | Get an order | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/orders/{id}/cancel` | Cancel an open, unbilled order | SalesRep, WholesaleBuyer |
| POST | `/orders/{id}/invoice` | Issue an invoice for a fulfilled order | SalesRep |
| POST | `/orders/{id}/fulfillments` | Reserve a roasted lot against an order line (OCC on roasted lot) | SalesRep |
| GET | `/orders/{id}/fulfillments` | List fulfillments for an order | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/fulfillments` | List fulfillments | SalesRep, RoasterStaff |
| GET | `/fulfillments/{id}` | Get a fulfillment | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/fulfillments/{id}/ship` | Ship a reserved fulfillment | RoasterStaff |
| POST | `/fulfillments/{id}/cancel` | Cancel a reserved fulfillment | SalesRep |
| POST | `/accounts/{id}/sample-requests` | Create a sample request for an account | SalesRep, WholesaleBuyer |
| GET | `/accounts/{id}/sample-requests` | List sample requests for an account | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/sample-requests` | List sample requests | SalesRep, RoasterStaff |
| GET | `/sample-requests/{id}` | Get a sample request | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/sample-requests/{id}/review` | Review a sample request (approve or decline) | RoasterStaff |
| POST | `/sample-requests/{id}/convert` | Convert an approved sample into an order | SalesRep |
| GET | `/accounts/{id}/invoices` | List invoices for an account | SalesRep, RoasterStaff, WholesaleBuyer |
| GET | `/invoices` | List invoices | SalesRep, RoasterStaff |
| GET | `/invoices/{id}` | Get an invoice | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/invoices/{id}/payments` | Apply a payment to an invoice | SalesRep |
| GET | `/invoices/{id}/payments` | List payments on an invoice | SalesRep, RoasterStaff, WholesaleBuyer |
| POST | `/_clock/set` | Set the simulated current UTC clock | SalesRep, RoasterStaff |
| POST | `/_clock/advance` | Advance the clock and run the aging sweep | SalesRep, RoasterStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRODUCT_MISMATCH` | 409 Conflict |
| `ERR_STALE_ROAST` | 409 Conflict |
| `ERR_RELEASE_NOT_DUE` | 409 Conflict |
| `ERR_INSUFFICIENT_GREEN` | 409 Conflict |
| `ERR_INSUFFICIENT_ROASTED` | 409 Conflict |
| `ERR_WEIGHT_GAIN` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_OVERPAYMENT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
