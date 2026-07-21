# Chocolate & Confectionery Shop API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an artisan chocolate and confectionery business that spans a surprisingly wide operational surface: a catalog of single and bundled SKUs, temperature-sensitive production lots that must be tempered on shared machinery, seasonal and holiday pre-orders, bespoke corporate commissions poured from physical molds, curated gift boxes, recurring subscription boxes, and the allergen and shelf-life obligations that tie all of them together. Underneath the storefront sits a real inventory problem: chocolate is produced in finite lots that expire, and those lots must be reserved, committed, and released in a first-expiry-first-out discipline so that the freshest promises are never broken by the oldest stock.

The service exists to make those competing concerns reconcile automatically. Sales staff quote and allocate, production staff temper and release, administrators manage the catalog and billing, and customers place and negotiate their own orders — each acting on a disjoint slice of the same shared state. Because several of these actors can touch the same production lot, the system leans on optimistic concurrency to prevent a stale view from over-committing a batch, and on cascading state propagation so that a single quarantine or cancellation ripples correctly through reservations, order lines, and orders. The remainder of this document defines the global contracts every endpoint honors (Section 2), the business workflows that move each entity through its lifecycle (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers the API can return (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `Customer`, `SalesManager`, `ProductionManager`, and `Admin`.

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's `customer_id` to `X-User-ID`. Concretely, a `Customer` may only act on an `Order`, `CustomOrder`, or `Subscription` whose `customer_id` equals their own `X-User-ID`; a mismatch is rejected with `ERR_OWNERSHIP_FORBIDDEN` (HTTP 403).

The `SalesManager`, `ProductionManager`, and `Admin` roles are each opaque operator identifiers not tied to any persisted entity. For these three roles the server treats `X-User-ID` as an operator label; it does not compare that identifier against any entity's `id`, and no ownership relationship is implied. Their authority is defined purely by the operations their role is permitted to perform, enumerated in Section 4.

All four roles may perform every read (GET) operation. Write authority is partitioned: `Admin` owns catalog, customer, wallet, subscription-billing, and system-clock operations; `ProductionManager` owns molds, tempering lines, batch lifecycle (except manual reservations), custom-order production, and order fulfilment; `SalesManager` owns custom-order quoting, order allocation, and manual inventory reservations; and `Customer` owns the creation and progression of their own orders, custom orders, and subscriptions. Cancelling an order may be performed by either a `Customer` (the owner) or a `SalesManager`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are returned sorted by `created_at` in ascending order (oldest first) unless a subsection states otherwise.

For list responses, the `meta` object carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the count of records matching the query before pagination is applied, and `has_more` is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties, Versioning, and Timestamps

Most resources carry four common properties. `id` is a server-minted UUID string with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was created. `updated_at` is the ISO 8601 UTC timestamp of the most recent mutation, refreshed on every state change or field update. `version` is an integer that begins at 1 on creation and increments by 1 on every mutation of the resource; it is the anchor for optimistic concurrency described in Section 2.7.

One entity is deliberately immutable and therefore does not carry the full set: a `BundleComponent` is a fixed junction record that carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once a component line is attached to a bundle it is never edited in place. Every other entity — `Customer`, `Product`, `Mold`, `TemperingLine`, `Batch`, `Order`, `OrderLine`, `Reservation`, `CustomOrder`, `MoldBooking`, `Subscription`, and `SubscriptionShipment` — carries all four common properties.

### 2.5. Validation Order and Error Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The ordering, highest priority first, is: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) request-body well-formedness — required fields present, enum members valid, and required quantities present (`ERR_VALIDATION`); (4) existence of every referenced resource (`ERR_NOT_FOUND` and its concrete variants); (5) ownership for `Customer`-role writes (`ERR_OWNERSHIP_FORBIDDEN`); (6) account-type compatibility on order confirm (`ERR_ACCOUNT_TYPE_MISMATCH`); (7) state legality of the requested transition (`ERR_INVALID_STATE`); and then the domain-specific business rules described throughout Section 3, which include allergen safety (`ERR_ALLERGEN_RESTRICTED`), tempering-line conflict (`ERR_TEMPERING_LINE_CONFLICT`), mold day-capacity (`ERR_MOLD_CAPACITY_EXCEEDED`), fulfilment window (`ERR_FULFILLMENT_WINDOW_CLOSED`), mold activity (`ERR_MOLD_INACTIVE`), batch expiry (`ERR_BATCH_EXPIRED`), inventory sufficiency (`ERR_INSUFFICIENT_INVENTORY`), quantity positivity (`ERR_INVALID_QUANTITY`), bundle-component validity (`ERR_BUNDLE_COMPONENT_INVALID`), duplicate line (`ERR_DUPLICATE_LINE`), credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`), and stale version (`ERR_STALE_VERSION`).

Existence checks (priority 4) are evaluated left to right in the order references appear: a path identifier is validated before any foreign key in the body, and body references are validated in the order listed. The concrete not-found identifiers are `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_MOLD_NOT_FOUND`, `ERR_CUSTOM_ORDER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_TEMPERING_LINE_NOT_FOUND`, and `ERR_RESERVATION_NOT_FOUND`; the umbrella `ERR_NOT_FOUND` names the same 404 condition generically. For nested retrievals, each path segment is resolved before the segment to its right, so a missing parent surfaces its own not-found identifier rather than the child's.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents. Wherever a calculation produces a fractional cent that must be persisted, the value is rounded half up (a value exactly at the midpoint rounds away from zero, upward) to a whole cent. The one deliberate exception to immediate rounding is the per-unit price of an order line, `unit_price_cents`, which is retained at full fractional precision until the line total is computed; only then is the line rounded. The authoritative rounding discipline for order subtotals is round-per-line-then-sum — each line is rounded to whole cents first, and the subtotal is the sum of those already-rounded line totals, never the rounded sum of exact line amounts. Discount fractions and tax rates are exact fractions and are not themselves rounded.

### 2.7. Optimistic Concurrency on Inventory Lots

Manual inventory reservations use optimistic concurrency control to prevent a stale reader from over-subscribing a production lot. The manual-reservation operation on a batch requires the input field `expected_batch_version`, carrying the `version` of the target `Batch` that the caller last observed. If that value does not equal the batch's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no reservation is created. A version mismatch means another writer has already drawn units from the same lot since the caller last read it — legitimately reducing the lot's `available_units` and advancing its `version` — so the caller's view is stale and its reservation could over-commit the lot. On a successful reservation the batch's `version` advances by 1, which is precisely what causes a subsequent request holding the old value to be rejected. This is the only endpoint that accepts `expected_batch_version`; no other write takes a version field.

### 2.8. Allergen Safety and Shelf-Life Consistency

Every `Product` declares the `allergens` it contains, and every `Customer` may declare `allergen_restrictions` — allergen codes (for example `MILK`, `NUT`, `SOY`, `GLUTEN`) that the customer must never be sold. No order line whose product contains any restricted allergen may pass the customer's order through pricing, allocation, or line addition; the guarded operations are detailed in Section 3, and each such rejection carries `ERR_ALLERGEN_RESTRICTED`.

Shelf life is derived, not entered: a batch's expiry instant `lot_expiry` is its `produced_at` timestamp advanced by the owning product's `shelf_life_days`. Once the logical clock reaches or passes `lot_expiry`, the lot is expired and may no longer be tempered, released, cleared from quarantine, reserved, or allocated against; such attempts are rejected with `ERR_BATCH_EXPIRED`. A `Mold` also carries an `allergens` residual profile and a `TemperingLine` carries only its `name` label, both used in production planning.

### 2.9. Derived Inventory and Cascade Consistency

A batch's `available_units` is a derived quantity, never set arbitrarily. For a lot in `RELEASED` status it equals the lot's `initial_units` minus the sum of `units` across all reservations on that lot in `ACTIVE` status; reservations in `VOIDED`, `RELEASED`, or `CONSUMED` status do not subtract. For a lot in any of `QUARANTINED`, `DISCARDED`, `EXPIRED`, `RAW`, `TEMPERING`, or `TEMPERED` status, `available_units` is 0. For a released lot the invariant holds that `initial_units` equals `available_units` plus the summed units of all `ACTIVE` and `CONSUMED` reservations against it.

Because several entities share this derived state, some operations cascade across aggregate boundaries; every such cascade also refreshes `updated_at` and advances `version` on each entity it mutates. The two most consequential cascades — batch quarantine and order cancellation — are described where they occur in Section 3, and each names the full set of secondary effects so no downstream mutation is left to inference.

## 3. Business Logic & Workflows

### 3.1. Catalog: Products, Bundles, Molds, and Tempering Lines

The catalog is the foundation of everything else and is curated by administrators for products and by production staff for the physical apparatus. A `Product` is created with a unique human `sku` code, a display `name`, a `product_type` of either `SINGLE` or `BUNDLE`, a catalog unit price `base_price_cents` that must be greater than zero, a `shelf_life_days` window that must be greater than zero, and a net `unit_weight_g` per unit. A product may optionally set `requires_tempering`, which defaults to false, and a `tempering_minutes` line-occupation duration, which defaults to 0 but must be greater than zero whenever `requires_tempering` is true. A product also declares the `allergens` it contains (defaulting to an empty list) and a `status` that is `ACTIVE` on creation and may later become `DISCONTINUED`. Administrators may adjust a product's `base_price_cents` or `status` after creation; each such update advances the product's `version`.

Bundles are assembled by attaching components. Adding a component to a bundle takes a `component_product_id` and a `quantity` — the number of units of that component contained in one bundle unit. A component attachment is only valid when the parent product it is attached to is of type `BUNDLE`, the referenced component product is of type `SINGLE`, the component is not the bundle itself, and the `quantity` is greater than zero; any violation is rejected with `ERR_BUNDLE_COMPONENT_INVALID`. Each attachment records the owning `bundle_product_id` alongside the `component_product_id` and `quantity`, and is an immutable junction record. Components may later be listed or filtered by their `bundle_product_id` or `component_product_id`.

Production apparatus is owned by production staff. A `Mold` is created with a `name`, a `cavity_count` greater than zero (the cavities filled per pour), a `daily_capacity_units` greater than zero (the maximum total units that may be booked against the mold on any single usage day), and an optional `allergens` residual profile. A mold's `status` begins `ACTIVE` and may be moved to `MAINTENANCE` or `RETIRED`; changing it advances the mold's `version`. A `TemperingLine` is the simplest catalog entity, created with just a `name`.

### 3.2. Customers, Accounts, and the Store-Credit Wallet

A `Customer` record is created by an administrator and represents a retail, wholesale, or corporate buyer. Creation captures the account holder or business `name`, a contact `email`, and an `account_type` of `RETAIL`, `WHOLESALE`, or `CORPORATE`. Optional fields include a `credit_limit_cents` ceiling on outstanding wholesale credit (defaulting to 0 for cash accounts), a `loyalty_discount_pct` per-unit retail discount fraction between 0 and 0.5 (defaulting to 0), and the `allergen_restrictions` list of allergen codes the customer must never be sold (defaulting to empty). Administrators may later revise a customer's `credit_limit_cents`, `loyalty_discount_pct`, or `allergen_restrictions`; each such change advances the customer's `version`.

Each customer also carries a store-credit balance, `wallet_credit_cents`, which begins at 0 and is a system-maintained field. It is mutated in exactly three ways: an administrator may grant or deduct credit through a wallet adjustment supplying a signed `amount_cents`, which is added to the balance; confirming an order debits the balance by the amount of store credit applied; and cancelling a confirmed, allocated, or backordered order refunds that applied credit. No other operation touches the wallet.

### 3.3. Production Batches: Tempering and the Path to Release

A production lot, or `Batch`, is created by production staff in the `RAW` state. Creation supplies the `product_id` whose SKU the lot produces, an `initial_units` count greater than zero, and optionally a `produced_at` production timestamp (defaulting to the current logical clock when omitted) and a `mold_id` for lots poured for custom orders. On creation the lot's `lot_expiry` is computed as `produced_at` advanced by the product's `shelf_life_days`, its `available_units` is 0, and its `reseed_count` is 0.

Whether a lot must be tempered depends on its product. When the product requires tempering, the lot must travel `RAW → TEMPERING → TEMPERED → RELEASED`; when the product does not, the lot goes directly `RAW → RELEASED`. Starting tempering advances a `RAW` lot to `TEMPERING` and requires that the product's tempering flag is set, that the lot is not expired, and that the requested tempering interval does not conflict with another lot on the same line. The request supplies the `tempering_line_id` to occupy and the `temper_start` instant; the system records both and computes `temper_end` as `temper_start` advanced by the product's `tempering_minutes`. The occupation interval runs from `temper_start` inclusive to `temper_end` exclusive (half-open), so two lots that merely touch end-to-start — one ending exactly when the next begins — do not conflict, whereas any true overlap on the same `tempering_line_id` is rejected with `ERR_TEMPERING_LINE_CONFLICT`. Attempting to start tempering on a product that does not require it, or an interval on an expired lot, is likewise refused (`ERR_BATCH_EXPIRED` for the expiry case).

Completing tempering advances a `TEMPERING` lot to `TEMPERED`, and is permitted only once the logical clock has reached or passed the lot's `temper_end`; the transition frees the line by clearing the lot's `tempering_line_id`. Should a batch need to be re-tempered, reseeding sends a `TEMPERING` lot back to `RAW`: it increments the lot's `reseed_count` by 1 and frees the line by clearing `tempering_line_id`, `temper_start`, and `temper_end`. This reseed loop may repeat. Releasing a lot moves it to `RELEASED` — from `TEMPERED` for tempered products, or directly from `RAW` for products that do not require tempering — provided the lot is not expired; on release the lot's `available_units` is set equal to its `initial_units`, making the full lot sellable.

### 3.4. Quarantine, Discard, Expiry, and the Cascade to Orders

A released lot can be quarantined by production staff if a quality concern arises, moving it `RELEASED → QUARANTINED`. Quarantine is the system's most far-reaching cascade and must be applied atomically in full. First, every reservation drawing on the quarantined lot that is currently `ACTIVE` is set to `VOIDED`. Second, each voided reservation decrements the `allocated_units` of its owning order line by the reservation's `units`. Third, any order in `ALLOCATED` status that, as a result, now has at least one line whose `allocated_units` has fallen below its `quantity` transitions from `ALLOCATED` to `BACKORDERED`. Finally, the quarantined lot's `available_units` is set to 0, freezing its stock. A quarantine may optionally record a `reason`.

From quarantine a lot has two exits. Clearing quarantine returns the lot to `RELEASED`, provided it is not expired, and recomputes `available_units` as the lot's `initial_units` minus the summed `units` of the reservations still `ACTIVE` on it. Discarding sends the lot from `QUARANTINED` to the terminal `DISCARDED` state and sets `available_units` to 0. Separately, an administrator-triggered inventory sweep is the system capability that ages stock out: any `RELEASED` lot whose `lot_expiry` has been reached or passed by the logical clock transitions to the terminal `EXPIRED` state with `available_units` set to 0. The `DISCARDED` and `EXPIRED` states are terminal for a batch.

### 3.5. Orders: Building, Pricing, and Confirmation

A `Customer` opens an `Order` in the `DRAFT` state, supplying their own `customer_id`, an `order_type` of `RETAIL`, `WHOLESALE`, or `PREORDER`, an optional `is_gift` flag (defaulting to false), and — for a pre-order — an optional fulfilment window bounded by `fulfillment_window_start` and `fulfillment_window_end`, both inclusive. Lines are then added to the draft: each line addition supplies a `product_id` and a `quantity` greater than zero, creating an `OrderLine` that records its parent `order_id`. An order may not carry two lines for the same `product_id`; a second line for a product already on the order is rejected with `ERR_DUPLICATE_LINE`. A non-positive `quantity` is rejected with `ERR_INVALID_QUANTITY`. Even at line-addition time, a line whose product carries an allergen in the owning customer's restriction list is refused with `ERR_ALLERGEN_RESTRICTED`.

Confirming an order advances it `DRAFT → CONFIRMED` and is the moment prices are pinned. Confirmation requires that the order has at least one line, that no line's product carries any allergen in the customer's `allergen_restrictions`, and that the `order_type` is compatible with the customer's `account_type`: a `WHOLESALE` order requires a `WHOLESALE` account, while a `RETAIL` or `PREORDER` order requires a `RETAIL` or `CORPORATE` account. An incompatible pairing is rejected with `ERR_ACCOUNT_TYPE_MISMATCH`.

Pricing is computed line by line. For a `RETAIL` or `PREORDER` order, each line's `unit_price_cents` is the product's `base_price_cents` reduced by the customer's `loyalty_discount_pct` — that is, the base price multiplied by one minus the loyalty fraction — independent of quantity, and this per-unit figure is kept at full fractional precision. For a `WHOLESALE` order, the discount is instead a volume tier keyed on the total number of units across all lines of the order: when that total is at least 500 units the discount is 0.25, when it is at least 200 units (but under 500) it is 0.18, when it is at least 50 units (but under 200) it is 0.10, and below 50 units there is no discount. These boundaries are inclusive on the lower edge, so 49 total units earn no discount while 50 total units earn the 0.10 tier. Each wholesale line's `unit_price_cents` is the product's base price multiplied by one minus the applicable tier fraction, again retained at fractional precision.

The order totals are then assembled with a strict rounding order. Each line's `line_total_cents` is the line's `unit_price_cents` multiplied by its `quantity`, rounded half up to whole cents. The order's `subtotal_cents` is the sum of those already-rounded line totals — rounding each line before summing, never summing exact amounts and rounding once. Tax, `tax_cents`, is the subtotal multiplied by the tax rate of 0.0725, rounded half up to whole cents. The gift fee, `gift_fee_cents`, is 500 cents when `is_gift` is true and 0 otherwise. Confirmation may also apply store credit: the request may supply `wallet_apply_cents`, and the amount actually applied, `wallet_applied_cents`, is the smallest of the requested amount, the customer's available `wallet_credit_cents`, and the sum of subtotal, tax, and gift fee; the customer's `wallet_credit_cents` is debited by exactly that applied amount. The order's `total_cents` is the subtotal plus tax plus gift fee, minus the wallet amount applied. For a wholesale order, confirmation additionally requires that the resulting `total_cents` does not exceed the customer's `credit_limit_cents`; exceeding it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

### 3.6. Allocation, Fulfilment, Cancellation, and Manual Reservations

Once confirmed, an order is allocated against inventory by a `SalesManager`, advancing it `CONFIRMED → ALLOCATED`. Allocation re-checks that no line's product carries a restricted allergen and requires that, for every line, the `RELEASED` non-expired batches of that line's product hold at least the line's `quantity` in aggregate `available_units`. Allocation then runs a first-expiry-first-out (FEFO) draw. Order lines are processed in ascending order of their creation. For each line the remaining need is its `quantity` less any `allocated_units` already covered; candidate lots are the `RELEASED` batches of the line's product that are not expired (their `lot_expiry` strictly after the current clock) and still have `available_units` above zero, considered in ascending order of `lot_expiry` with ties broken by ascending creation time — never by identifier. From each candidate the draw takes the smaller of the remaining need and that lot's `available_units`, creates an `ACTIVE` `Reservation` recording the `order_line_id`, the supplying `batch_id`, and the `units` taken, decrements that batch's `available_units`, and increases the line's `allocated_units` by the same amount, continuing to the next candidate until the need reaches zero. If, after all candidates for a line are exhausted, any need remains, the entire allocation is rejected with `ERR_INSUFFICIENT_INVENTORY` and no reservations are committed — allocation is all-or-nothing. A backordered order may be allocated again the same way, re-running the draw only for lines still short of their quantity, provided every line can now be fully covered.

An order reaches `BACKORDERED` only as a consequence of the quarantine cascade described earlier, when voided reservations pull an already-allocated line below its quantity; it is not entered directly from `CONFIRMED`. Fulfilment, performed by production staff, advances an order `ALLOCATED → FULFILLED` and requires that every line's `allocated_units` equals its `quantity`; for a pre-order it additionally requires that the current logical clock falls within the inclusive window from `fulfillment_window_start` to `fulfillment_window_end`, a window violation being rejected with `ERR_FULFILLMENT_WINDOW_CLOSED`. Fulfilment sets every `ACTIVE` reservation on the order to `CONSUMED`. Both `FULFILLED` and `CANCELLED` are terminal for an order.

Cancellation is available to the owning `Customer` or a `SalesManager` and behaves according to the order's current state. A `DRAFT` order simply becomes `CANCELLED`. A `CONFIRMED` order becomes `CANCELLED` and refunds any `wallet_applied_cents` back to the customer's `wallet_credit_cents`, resetting `wallet_applied_cents` to 0. An `ALLOCATED` order, on cancellation, additionally releases each `ACTIVE` reservation on the order by setting it to `RELEASED` and restoring its batch's `available_units` by the reservation's `units`, and then refunds the wallet as above. A `BACKORDERED` order cancels the same way — releasing any remaining `ACTIVE` reservations, restoring the corresponding batch stock, and refunding the wallet.

Beyond order-driven allocation, a `SalesManager` may reserve units from a specific lot manually. A manual reservation supplies the `order_line_id` being satisfied, the `units` to draw (greater than zero), and the `expected_batch_version` for optimistic concurrency. The lot must not be expired, and it must hold enough `available_units` to satisfy the draw — a shortfall is rejected with `ERR_INSUFFICIENT_INVENTORY`. On success the reservation is created `ACTIVE`, the batch's `available_units` is decremented by the drawn `units`, the batch's `version` advances by 1, and the owning line's `allocated_units` increases accordingly. Reservations may be read or filtered by their `order_line_id` or supplying `batch_id`.

### 3.7. Custom & Corporate Orders and Mold Bookings

A corporate or bespoke commission is handled through a `CustomOrder`, opened by a `Customer` in the `DRAFT` state with their own `customer_id`, the target `product_id`, the `mold_id` to pour from, and a `units_estimated` count greater than zero. The lifecycle is a negotiation loop. A `SalesManager` issues a quote, advancing the order `DRAFT → QUOTED`; quoting computes the provisional `quoted_amount_cents` and increments `quote_round` by 1. A quoted order may be sent back by the customer for revision, moving it `QUOTED → REVISION_REQUESTED` (optionally carrying a `note`), from which a fresh quote may again be issued (`REVISION_REQUESTED → QUOTED`), recomputing `quoted_amount_cents` and again incrementing `quote_round`. This re-quote loop may repeat any number of times.

The provisional amount is the estimated unit count multiplied by the sum of the product's `base_price_cents` and a per-unit mold surcharge of 300 cents, plus a fixed mold setup fee of 25000 cents. From a quoted state the customer may accept, reject, or cancel. Accepting advances the order `QUOTED → ACCEPTED` and books the mold: the request supplies the `usage_date`, and acceptance requires that the mold's `status` is `ACTIVE` (otherwise `ERR_MOLD_INACTIVE`) and that the estimated units plus the summed `units` of all `ACTIVE` mold bookings already held for that mold on that same `usage_date` do not exceed the mold's `daily_capacity_units` (otherwise `ERR_MOLD_CAPACITY_EXCEEDED`). Acceptance records the `usage_date` on the custom order and creates a `MoldBooking` in `ACTIVE` status recording the `mold_id`, the owning `custom_order_id`, the `usage_date`, and `units` equal to the estimated count. Rejecting a quoted order moves it to the terminal `REJECTED` state.

Production of an accepted order is driven by production staff. Starting production advances it `ACCEPTED → IN_PRODUCTION`, re-checks that the mold's `status` is still `ACTIVE` (again `ERR_MOLD_INACTIVE` if not), and creates a `RAW` `Batch` for the target product and mold with `initial_units` equal to the estimated units. Fulfilling advances the order `IN_PRODUCTION → FULFILLED`: the request supplies the actual `units_produced`, the system pins the final `invoiced_amount_cents` as that actual unit count multiplied by the same per-unit base-plus-surcharge figure plus the 25000-cent setup fee, and the order's `MoldBooking` is set to `RELEASED`. The invoiced amount equals the earlier quote only when the units produced match the units estimated. A custom order may be cancelled from `DRAFT` or `QUOTED` with no side effect, and from `ACCEPTED` — in which case its `MoldBooking` is set to `CANCELLED`, freeing the day's capacity. Mold bookings may be listed or filtered by `mold_id`, `custom_order_id`, `usage_date`, or `status`. The `FULFILLED`, `REJECTED`, and `CANCELLED` states are terminal for a custom order.

### 3.8. Subscriptions and Recurring Shipments

A `Customer` opens a `Subscription` in the `ACTIVE` state with their own `customer_id`, the recurring box's `box_product_id`, a `cadence_days` interval greater than zero, and the first `next_ship_date`. A subscription may be paused by its owner (`ACTIVE → PAUSED`) and later resumed (`PAUSED → ACTIVE`); this pause/resume cycle may repeat. Cancelling a subscription — permitted from either `ACTIVE` or `PAUSED` — moves it to the terminal `CANCELLED` state and cascades by setting every `SCHEDULED` `SubscriptionShipment` of that subscription to `CANCELLED`.

Billing is driven by an administrator advancing the subscription on its cadence. An advance is permitted only while the subscription is `ACTIVE` and only once the logical clock has reached or passed its `next_ship_date`. Each advance emits a new `SubscriptionShipment` child: the shipment's `period_index` is the next one-based sequence number, its `scheduled_date` captures the subscription's `next_ship_date` at that moment, and its `estimated_charge_cents` is the box product's current `base_price_cents` read at scheduling time. The advance then moves the subscription's `next_ship_date` forward by `cadence_days`, leaving the subscription `ACTIVE`.

A scheduled shipment is shipped by an administrator, advancing it `SCHEDULED → SHIPPED`, but only while its parent subscription is still `ACTIVE`. Shipping settles the charge: `settled_charge_cents` is the box product's `base_price_cents` re-read at ship time. Because the estimate and the settlement read the price at two different clock positions, the settled charge equals the earlier estimate only when the box SKU's `base_price_cents` did not change in between; if it did, the settled figure is authoritative. A shipment carries `SHIPPED` and `CANCELLED` as its terminal states.

## 4. Endpoint Definitions

All endpoints return the standard envelope of Section 2.2. Endpoints that create a new resource respond with HTTP 201; endpoints that read or modify an existing resource respond with HTTP 200. Request bodies, responses, and side effects are not repeated here — they are specified in the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/products` | Create SKU | Admin |
| GET | `/products/{id}` | Read product | Customer, SalesManager, ProductionManager, Admin |
| GET | `/products` | List products | Customer, SalesManager, ProductionManager, Admin |
| PATCH | `/products/{id}` | Update price/status | Admin |
| POST | `/products/{id}/bundle-components` | Attach a component to a BUNDLE product | Admin |
| GET | `/bundle-components/{id}` | Read bundle component | Customer, SalesManager, ProductionManager, Admin |
| GET | `/bundle-components` | List/filter bundle components | Customer, SalesManager, ProductionManager, Admin |
| POST | `/customers` | Create customer/account | Admin |
| GET | `/customers/{id}` | Read customer | Customer, SalesManager, Admin |
| GET | `/customers` | List customers | Admin |
| PATCH | `/customers/{id}` | Update credit/loyalty/allergen restrictions | Admin |
| POST | `/customers/{id}/wallet/adjust` | Grant/deduct store credit | Admin |
| POST | `/molds` | Create mold | ProductionManager |
| GET | `/molds/{id}` | Read mold | Customer, SalesManager, ProductionManager, Admin |
| GET | `/molds` | List molds | Customer, SalesManager, ProductionManager, Admin |
| POST | `/molds/{id}/set-status` | Set mold ACTIVE/MAINTENANCE/RETIRED | ProductionManager |
| GET | `/mold-bookings/{id}` | Read mold booking | Customer, SalesManager, ProductionManager, Admin |
| GET | `/mold-bookings` | List/filter mold bookings | Customer, SalesManager, ProductionManager, Admin |
| POST | `/tempering-lines` | Create tempering line | ProductionManager |
| GET | `/tempering-lines/{id}` | Read tempering line | Customer, SalesManager, ProductionManager, Admin |
| GET | `/tempering-lines` | List tempering lines | Customer, SalesManager, ProductionManager, Admin |
| POST | `/batches` | Create production lot (RAW) | ProductionManager |
| GET | `/batches/{id}` | Read batch | Customer, SalesManager, ProductionManager, Admin |
| GET | `/batches` | List/filter batches | Customer, SalesManager, ProductionManager, Admin |
| POST | `/batches/{id}/start-tempering` | RAW→TEMPERING; occupy a tempering line interval | ProductionManager |
| POST | `/batches/{id}/complete-tempering` | TEMPERING→TEMPERED | ProductionManager |
| POST | `/batches/{id}/reseed` | TEMPERING→RAW reseed loop | ProductionManager |
| POST | `/batches/{id}/release` | TEMPERED→RELEASED (or RAW→RELEASED when no tempering) | ProductionManager |
| POST | `/batches/{id}/quarantine` | RELEASED→QUARANTINED; cascade void reservations and backorder affected orders | ProductionManager |
| POST | `/batches/{id}/clear-quarantine` | QUARANTINED→RELEASED | ProductionManager |
| POST | `/batches/{id}/discard` | QUARANTINED→DISCARDED (terminal) | ProductionManager |
| POST | `/batches/{id}/reservations` | Manually reserve units from a lot (OCC on batch version) | SalesManager |
| GET | `/reservations/{id}` | Read reservation | Customer, SalesManager, ProductionManager, Admin |
| GET | `/reservations` | List/filter reservations | Customer, SalesManager, ProductionManager, Admin |
| POST | `/orders` | Create DRAFT order | Customer |
| GET | `/orders/{id}` | Read order | Customer, SalesManager, ProductionManager, Admin |
| GET | `/orders` | List/filter orders | Customer, SalesManager, ProductionManager, Admin |
| POST | `/orders/{id}/lines` | Add a line to a DRAFT order | Customer |
| GET | `/order-lines/{id}` | Read order line | Customer, SalesManager, ProductionManager, Admin |
| GET | `/order-lines` | List/filter order lines | Customer, SalesManager, ProductionManager, Admin |
| POST | `/orders/{id}/confirm` | DRAFT→CONFIRMED; price and apply wallet | Customer |
| POST | `/orders/{id}/allocate` | CONFIRMED/BACKORDERED→ALLOCATED via FEFO | SalesManager |
| POST | `/orders/{id}/fulfill` | ALLOCATED→FULFILLED | ProductionManager |
| POST | `/orders/{id}/cancel` | Cancel order; release reservations and refund wallet | Customer, SalesManager |
| POST | `/custom-orders` | Create DRAFT custom order | Customer |
| GET | `/custom-orders/{id}` | Read custom order | Customer, SalesManager, ProductionManager, Admin |
| GET | `/custom-orders` | List/filter custom orders | Customer, SalesManager, ProductionManager, Admin |
| POST | `/custom-orders/{id}/quote` | DRAFT/REVISION_REQUESTED→QUOTED (provisional amount) | SalesManager |
| POST | `/custom-orders/{id}/request-revision` | QUOTED→REVISION_REQUESTED (negotiation loop) | Customer |
| POST | `/custom-orders/{id}/accept` | QUOTED→ACCEPTED; book mold day-capacity | Customer |
| POST | `/custom-orders/{id}/reject` | QUOTED→REJECTED | Customer |
| POST | `/custom-orders/{id}/start-production` | ACCEPTED→IN_PRODUCTION; create batch | ProductionManager |
| POST | `/custom-orders/{id}/fulfill` | IN_PRODUCTION→FULFILLED; final invoice | ProductionManager |
| POST | `/custom-orders/{id}/cancel` | Cancel custom order; free mold booking | Customer |
| POST | `/subscriptions` | Create ACTIVE subscription | Customer |
| GET | `/subscriptions/{id}` | Read subscription | Customer, SalesManager, ProductionManager, Admin |
| GET | `/subscriptions` | List/filter subscriptions | Customer, SalesManager, ProductionManager, Admin |
| POST | `/subscriptions/{id}/pause` | ACTIVE→PAUSED | Customer |
| POST | `/subscriptions/{id}/resume` | PAUSED→ACTIVE | Customer |
| POST | `/subscriptions/{id}/cancel` | Cancel subscription; cancel scheduled shipments | Customer |
| POST | `/subscriptions/{id}/advance` | Emit next shipment (system); advance next_ship_date | Admin |
| GET | `/subscription-shipments/{id}` | Read shipment | Customer, SalesManager, ProductionManager, Admin |
| GET | `/subscription-shipments` | List/filter shipments | Customer, SalesManager, ProductionManager, Admin |
| POST | `/subscription-shipments/{id}/ship` | SCHEDULED→SHIPPED; settle charge at current price | Admin |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-07-01T00:00:00Z) | Admin |
| POST | `/_inventory/sweep-expired` | Transition RELEASED batches past expiry to EXPIRED | Admin |

The list endpoints accept the filter query parameters described in Section 3 in addition to `limit` and `offset`: products filter by `product_type` and `status`; bundle components by `bundle_product_id` and `component_product_id`; customers by `account_type`; molds by `status`; mold bookings by `mold_id`, `custom_order_id`, `usage_date`, and `status`; batches by `product_id`, `mold_id`, `tempering_line_id`, and `status`; reservations by `order_line_id`, `batch_id`, and `status`; orders by `customer_id`, `order_type`, and `status`; order lines by `order_id` and `product_id`; custom orders by `customer_id`, `mold_id`, `product_id`, and `status`; subscriptions by `customer_id`, `box_product_id`, and `status`; and subscription shipments by `subscription_id` and `status`. The clock-setting capability takes a `to_iso8601` instant; before any such call the logical clock reads exactly its startup default and never falls back to wall-clock time.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_MOLD_NOT_FOUND` | 404 |
| `ERR_CUSTOM_ORDER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_TEMPERING_LINE_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_OWNERSHIP_FORBIDDEN` | 403 |
| `ERR_ACCOUNT_TYPE_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALLERGEN_RESTRICTED` | 422 |
| `ERR_TEMPERING_LINE_CONFLICT` | 409 |
| `ERR_MOLD_CAPACITY_EXCEEDED` | 409 |
| `ERR_FULFILLMENT_WINDOW_CLOSED` | 422 |
| `ERR_MOLD_INACTIVE` | 409 |
| `ERR_BATCH_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_BUNDLE_COMPONENT_INVALID` | 422 |
| `ERR_DUPLICATE_LINE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_VERSION` | 412 |
