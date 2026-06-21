# Ecommerce Order Returns API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an end-to-end commerce platform that carries a shopper from an empty cart all the way through checkout, multi-warehouse fulfillment, and post-purchase returns. The platform treats inventory as a finite, contended resource: stock is reserved against specific warehouses at checkout, committed when a parcel ships, and either consumed or released depending on how the order resolves. Because a single order may draw stock from several warehouses, ship in multiple parcels, fall partly into backorder, and later be returned in pieces, the system must keep an order's payment and fulfillment pictures coherent at every step.

The second half of the platform governs the Return Merchandise Authorization (RMA) lifecycle. A customer who has received goods may request a return, choosing a reason and a desired resolution — a cash refund, store credit, or an exchange for a different product. The settlement math differs sharply between these paths: cash refunds may withhold a per-product restocking fee, store credit waives that fee and pays a bonus, and exchanges compute a price delta that can fall in either party's favor. Throughout, the platform maintains per-customer lifetime ledgers — total purchased, total refunded, redeemable store credit, and a derived return-risk score — so that the business always has an accurate view of each shopper's standing. All cascades described in this document resolve atomically within the request that triggers them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `Anonymous`, `Customer`, `WarehouseOperator`, and `StoreAdmin`. If either header is missing, or if `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Two endpoints are exempt from the authentication requirement and may be called without valid headers: customer self-registration and the test-driving clock setter. When an authenticated principal attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles relate to persisted identity in different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A `Customer` may act only on carts, orders, and returns they own — attempting to check out, add lines to, open a return against, or cancel a return for a resource whose `customer_id` does not equal the caller's `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the visitor may browse the catalog and self-register. When `X-User-Role` is `WarehouseOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity — operators are global and are not bound to a single warehouse, so an operator may act on any warehouse's shipments and inventory; the server does not compare a `WarehouseOperator`'s identifier to any entity's `id`. When `X-User-Role` is `StoreAdmin`, `X-User-ID` is also an opaque operator identifier not tied to any persisted entity; an admin is never subject to the ownership check.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of system-managed fields. The `id` is a unique, server-minted identifier formatted as a UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every subsequent modification of the resource. The `version` field is an integer that starts at its initial value and increments by one with every mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.6.

One entity is the exception. A `CreditLedgerEntry` is an immutable audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written a ledger entry is never modified. Every other entity — `Customer`, `Warehouse`, `Product`, `InventoryItem`, `Order`, `OrderLine`, `Reservation`, `Shipment`, `ShipmentLine`, `ReturnAuthorization`, `ReturnLine`, and `Refund` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Derived Fields, Cascades, and Hierarchical Consistency

A defining characteristic of this platform is that many fields are not written directly by clients but are derived from the rows beneath them, and the system keeps them reconciled automatically. Whenever an operation changes facts that feed a derived field, the system recomputes that field within the same request, refreshes the owning resource's `updated_at`, and increments its `version`. These reconciliations may fire on a parent or sibling resource without an explicit client request naming that resource — for example, settling a return moves money on a `Customer` and may advance an `Order`'s payment picture even though the request targeted the return.

A key consequence is that an `Order` carries two independent state dimensions that evolve on separate axes. The payment dimension, `payment_status`, is one of `CART`, `AUTHORIZED`, `CAPTURED`, `VOIDED`, `PARTIALLY_REFUNDED`, or `REFUNDED`. The fulfillment dimension, `fulfillment_status`, is one of `UNFULFILLED`, `PARTIALLY_SHIPPED`, `SHIPPED`, `PARTIALLY_DELIVERED`, `DELIVERED`, or `BACKORDERED`. A new cart begins at `CART` payment and `UNFULFILLED` fulfillment. The two dimensions advance through different triggers described in §3, and the fulfillment dimension is re-derived from the underlying shipments whenever a parcel's own status changes. By contrast, a `Reservation`, a `Shipment`, a `ReturnAuthorization`, and a `Refund` each carry a single `status` field tracking their own lifecycle, with the enumerated values given where each entity's workflow is described in §3.

### 2.6. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of their parent by requiring the client to declare the parent's last observed `version`. The first is checkout: a checkout request must carry `expected_order_version`, and the value must match the target `Order`'s current `version`. If a line was added or removed since the client last read the cart — each such mutation increments `Order.version` and changes the totals the client is about to authorize — the client's view is stale and the checkout is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This prevents the client from authorizing an amount that no longer matches the server's recomputed `grand_total_cents`. The second is return approval: an approve request must carry `expected_return_version`, and the value must match the target `ReturnAuthorization`'s current `version`. If another operator has already approved or otherwise mutated the RMA — advancing its `version` and locking a settlement figure — the approver's view is stale and the request is rejected with `ERR_STALE_RETURN_VERSION` (HTTP 412). No other endpoint takes a version field; endpoints not named here perform no optimistic-concurrency check.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are stored and exchanged as integer counts of cents; there are no fractional-cent fields in any response. Likewise, all quantities are integer unit counts with no rounding. Wherever a calculation produces a fractional cent — per-line tax, the allocation of tax or promotional discount to a partial return, a restocking fee, or the store-credit bonus — the result is rounded half up to a whole cent at the specific step the calculation names. The return-risk ratio is the sole non-cent computed value: it is a number rounded half up to four decimal places. The exact rounding points are pinned in the calculation narratives of §3 and must be applied where stated, because rounding per line and then summing can differ from summing and then rounding by one or more cents.

### 2.8. Nested Resource Retrieval and Existence Checks

Many paths address a resource nested under one or more parents — for instance, a return line under a return, or a shipment under an order. For any such path, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource, before examining anything further to its right. Path identifiers are checked before any foreign-key identifiers carried in the request body, and those body references are themselves validated for existence in turn. This existence sweep applies to every identifier-bearing endpoint.

### 2.9. Validation Ordering

When several checks could fail on the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED` before anything else. Role permission is checked next, yielding `ERR_FORBIDDEN_ROLE`. Resource ownership for `Customer`-acted endpoints is checked third, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of every referenced resource is checked fourth, yielding `ERR_NOT_FOUND`. The shape of the request body — required fields present, correct types, valid enum members — is checked fifth, yielding `ERR_INVALID_REQUEST` (HTTP 400). The target's state eligibility for the requested transition is checked sixth, yielding `ERR_INVALID_STATE` (HTTP 409). Optimistic-concurrency version match is checked seventh, yielding `ERR_STALE_ORDER_VERSION` or `ERR_STALE_RETURN_VERSION` (HTTP 412) as appropriate to the endpoint. Only after all of these pass does the system evaluate the business-rule checks (the 422-class rules described throughout §3), in the relative order those narratives specify. A generic business-rule violation not covered by a more specific code — such as a negative `promo_flat_cents` or a quantity below one — is reported as `ERR_VALIDATION` (HTTP 422).

### 2.10. The Test-Driving Clock

Return-window arithmetic depends on the passage of time, so the platform maintains a logical current UTC clock rather than reading the wall clock. An unauthenticated test-driving capability sets this clock to a supplied instant; the request body carries the target timestamp in the `to_iso8601` field. Every time-sensitive comparison — when a shipment is delivered and whether a return window is still open — reads this logical clock. Setting the clock returns no resource payload.

## 3. Business Logic & Workflows

### 3.1. Catalog, Warehouses, and Inventory

The catalog and its physical backing are configured by a `StoreAdmin`. A `Product` is created with a stock-keeping unit `sku` (unique across all products), a display `title`, a catalog price `unit_price_cents` (which may not be negative), a sales-tax rate `tax_rate_bps` expressed in basis points (so 875 means 8.75 percent; may not be negative), an optional `restocking_fee_bps` also in basis points and defaulting to 0 (constrained to the inclusive range from 0 to 10000), a `return_window_days` count (may not be negative) governing how long after delivery a return may be opened, and an optional `final_sale` flag defaulting to false. When `final_sale` is true, lines of that product can never be returned or exchanged.

A `Warehouse` is created with a short `code` (unique across all warehouses), a display `name`, a `fulfillment_priority` integer (which must be at least 1, where a lower number is filled before a higher one), and an optional `accepts_returns` flag defaulting to true that governs whether restocked returns may be routed back to it. Physical stock lives in an `InventoryItem`, created for a given pair of `product_id` and `warehouse_id` with an `on_hand_qty` count of physical units present (may not be negative). Each inventory row also exposes two derived counts: `reserved_qty`, the sum of the quantities of reservations against that product-and-warehouse pair whose status is `HELD` or `COMMITTED` (and which never exceeds `on_hand_qty`), and `available_qty`, equal to `on_hand_qty` minus `reserved_qty` and floored at 0 — the quantity reservable right now. A freshly stocked item begins with `reserved_qty` of 0 and `available_qty` equal to its `on_hand_qty`.

The catalog and inventory are reachable through a family of reverse-lookup listings: a warehouse's inventory, shipments, and reservations; a product's inventory across warehouses, its reservations, the order lines that purchased it, and the return lines naming it as an exchange target. Each `InventoryItem` exposes its `product_id` and `warehouse_id`; the single-item read returns its computed `reserved_qty` and `available_qty`.

### 3.2. Building and Pricing the Cart

A shopping session begins when a `Customer` (or a `StoreAdmin` acting on their behalf) opens an empty cart, supplying the owning `customer_id` and an optional `promo_flat_cents` flat promotional discount that defaults to 0 and may not be negative. The new `Order` begins in `CART` payment status and `UNFULFILLED` fulfillment status with every computed total at 0. Items are added one line at a time by submitting a `product_id` and a `qty` (the ordered quantity, at least 1). At the moment a line is added, the product's current price and tax rate are snapshotted onto the line as `unit_price_cents_snapshot` and `tax_rate_bps_snapshot`, immunizing the line against any later catalog edits. Each `OrderLine` records its owning `order_id` and its `product_id`, and exposes several derived counts discussed in later subsections: `line_tax_cents`, `reserved_qty`, `backordered_qty`, `shipped_qty`, and `returned_qty`. Adding a line increments the parent `Order`'s `version` by one — which is precisely why a client that adds a line must re-read the cart before checking out.

Checkout is performed by the owning `Customer` and is the single moment at which the cart is priced and inventory is committed against it. The request carries `expected_order_version` for the optimistic-concurrency check of §2.6, and the order must currently be in `CART` payment status with at least one `OrderLine`; an attempt to check out an order that is not in `CART` is an `ERR_INVALID_STATE` rejection. A successful checkout recomputes all order totals and advances `payment_status` from `CART` to `AUTHORIZED`.

The pricing computation runs in a pinned order, and the order is load-bearing. First, each line's subtotal is its `unit_price_cents_snapshot` multiplied by its `qty`, and `subtotal_cents` is the sum of those line subtotals. Second, `discounted_subtotal_cents` is the larger of 0 and `subtotal_cents` minus `promo_flat_cents`; this discounted figure both drives the shipping tier and serves as the base that will eventually be captured. Third, tax is computed per line on the full, pre-discount line subtotal: each line's `line_tax_cents` is the line subtotal multiplied by `tax_rate_bps_snapshot`, divided by 10000, rounded half up to a whole cent — and `tax_total_cents` is the sum of those already-rounded per-line taxes, never the rounding of their unrounded sum. Fourth, shipping is selected from `discounted_subtotal_cents` against two thresholds: if the discounted subtotal is below 50 dollars (5000 cents) the fee is 999 cents; if it is at least 50 dollars but below 100 dollars (10000 cents) the fee is 499 cents; and if it is at least 100 dollars the fee is 0. Fifth, `grand_total_cents` is the sum of `discounted_subtotal_cents`, `tax_total_cents`, and `shipping_fee_cents`; this is the amount authorized at checkout and later captured. Checkout also increments the `Order`'s `version` by one.

### 3.3. Reserving Inventory: The Waterfall

As part of the same checkout transaction, and once per `OrderLine`, the system allocates each line's ordered quantity across warehouses using a waterfall. The candidates for a line are the `InventoryItem` rows for the line's `product_id` whose `available_qty` is greater than 0. These candidates are ordered first by their warehouse's `fulfillment_priority` ascending (priority 1 before priority 2), and ties are broken by the inventory item's `created_at` ascending — never by `id`. The system then walks the ordered candidates, and for each one takes the smaller of the still-unfilled remaining quantity and that item's `available_qty`. Whenever that take is greater than zero, it creates a `Reservation` for the line at that warehouse — recording `order_line_id`, `warehouse_id`, the denormalized `product_id`, and the held `qty` (at least 1) — in `HELD` status, and reduces the remaining quantity by the amount taken. The walk stops as soon as the remaining quantity reaches zero.

After the walk, the line's `reserved_qty` is the ordered quantity minus whatever remains unfilled, and its `backordered_qty` is that remaining shortfall. If exactly one warehouse alone can cover the line, a single `HELD` reservation results with no split. If no single warehouse covers the line but the cumulative availability across warehouses does, two or more `HELD` reservations are created, filling higher-priority warehouses first. If the cumulative availability across all warehouses falls short of the line's quantity, the reserved quantity equals the total available and the `backordered_qty` carries the shortfall. Each touched `InventoryItem` then has its `reserved_qty` and `available_qty` recomputed. Finally, the order's fulfillment dimension is set: if any `OrderLine` has a `backordered_qty` greater than zero the `fulfillment_status` becomes `BACKORDERED`, otherwise it remains `UNFULFILLED`. A reservation in `HELD` status means stock is held but not yet shipped; the lifecycle continues in §3.5.

### 3.4. Capturing and Voiding Payment

After authorization, a `StoreAdmin` decides the order's financial fate. Capturing payment is permitted only when `payment_status` is `AUTHORIZED`; it freezes the captured base by setting `captured_total_cents` to the current `grand_total_cents`, advances `payment_status` from `AUTHORIZED` to `CAPTURED`, and increments the `Order`'s `version`. Capture also causes the order to begin counting toward the owning customer's lifetime purchases, which in turn refreshes that customer's return-risk score, both described in §3.9. The captured amount is frozen at this moment and remains 0 until capture occurs.

Voiding is the alternative, and it too is permitted only when `payment_status` is `AUTHORIZED`, with the additional precondition that no shipment of the order is in `SHIPPED` or `DELIVERED` status — an authorized order cannot be voided once any of its goods are in transit or delivered. Voiding releases every `HELD` reservation belonging to the order, transitioning each from `HELD` to `RELEASED`; this is the compensation for the hold taken at checkout, returning the held quantity to each touched `InventoryItem`'s `available_qty` (the physical `on_hand_qty` is unchanged because nothing ever shipped). The order's fulfillment is cleared, `payment_status` advances from `AUTHORIZED` to `VOIDED`, and the `Order`'s `version` increments. A voided order is terminal.

### 3.5. Splitting Shipments and Committing Stock

Fulfillment is driven by a `WarehouseOperator`, who may also create the parcels (a `StoreAdmin` may create them as well). A `Shipment` is created against an order from a single warehouse, supplying that `warehouse_id` and a set of `lines`, each of which names a `reservation_id` to fulfill. Each parcel is born in `PENDING` status with no `shipped_at` and no `delivered_at`. A shipment line records the owning `shipment_id`, the `reservation_id` it commits, the denormalized `order_line_id`, and a `qty`. Because an order's stock may sit in several warehouses, an order naturally fans out into multiple parcels — one per warehouse — which is how split shipment and backorder are expressed. For each attached shipment line, the `qty` must equal the referenced reservation's `qty`, the referenced reservation must be in `HELD` status and belong to the order, and the shipment's warehouse must match the reservation's warehouse; any violation is rejected with `ERR_RESERVATION_MISMATCH` (HTTP 422).

Dispatching a parcel — the ship action — is restricted to a `WarehouseOperator` and is permitted only when the shipment is `PENDING`. It additionally requires that the parent order's `payment_status` already be `CAPTURED`: goods may never ship before payment is captured, and an attempt to ship an order that is not yet captured is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409). Every referenced `ShipmentLine.reservation_id` must point at a `HELD` reservation belonging to the order. Shipping triggers a three-link cascade: first, each referenced `Reservation` transitions from `HELD` to `COMMITTED`; second, each committed reservation decrements its `InventoryItem`'s `on_hand_qty` by the reservation's `qty`; third, each touched item's `available_qty` is recomputed. The system then recomputes each affected `OrderLine`'s `shipped_qty` — the sum of shipment-line quantities across that line's shipments whose parcel status is `SHIPPED` or `DELIVERED` — and re-derives the order's `fulfillment_status`, which becomes `SHIPPED` once every non-backordered unit has shipped and `PARTIALLY_SHIPPED` otherwise. The parcel's status moves to `SHIPPED` and its `shipped_at` is stamped with the current clock.

Marking a parcel delivered is also a `WarehouseOperator` action and is permitted only when the shipment is `SHIPPED`. Delivery stamps `delivered_at` with the current clock — this timestamp anchors the return window — and re-derives the order's `fulfillment_status`, which becomes `DELIVERED` once every shipped unit has been delivered and `PARTIALLY_DELIVERED` otherwise. Cancelling a parcel is permitted only when the shipment is `PENDING`; it sets the parcel to `CANCELLED` and removes its shipment lines, but deliberately leaves the referenced reservations in `HELD` status so they remain re-shippable — a cancelled pending parcel does not release stock. A delivered parcel and a cancelled parcel are both terminal.

### 3.6. Opening a Return

Once an order is paid for and its goods have arrived, the owning `Customer` (or a `StoreAdmin`) may open a Return Merchandise Authorization against it. The request supplies a `reason`, a `resolution`, and a set of `lines`. The `reason` is one of `DEFECTIVE`, `WRONG_ITEM`, `NO_LONGER_WANTED`, or `ARRIVED_LATE`, where `DEFECTIVE` and `WRONG_ITEM` waive the restocking fee. The `resolution` is one of `REFUND`, `STORE_CREDIT`, or `EXCHANGE`. Each return line names the `order_line_id` being returned, a `return_qty` (at least 1), and an `exchange_product_id` that is required only for exchanges and otherwise defaults to null. The created `ReturnAuthorization` records its `order_id` and the denormalized owner `customer_id`, begins in `REQUESTED` status, and exposes three computed settlement figures — `refund_subtotal_cents`, `restocking_fee_cents`, and `settlement_cents` — that are previewed at this point and locked later. Each `ReturnLine` records its owning `return_authorization_id` and its `order_line_id`.

Opening a return must satisfy several business rules. The order's `payment_status` must be `CAPTURED`, and every return line's order line must belong to the order named in the path. No return line may reference a product whose `final_sale` is true; such an attempt is rejected with `ERR_FINAL_SALE_NOT_RETURNABLE` (HTTP 422). For each return line, the return window must be open: some shipment carrying that line must be `DELIVERED`, and the current logical clock must be no later than that shipment's `delivered_at` plus the product's `return_window_days` days, with the boundary day inclusive; a window that has no delivered shipment for the line, or whose deadline has passed, is rejected with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422). For each return line, the requested `return_qty` plus the quantity already returned for that order line must not exceed the order line's `shipped_qty` — one cannot return more than was delivered — and a violation is rejected with `ERR_RETURN_QTY_EXCEEDS_SHIPPED` (HTTP 422). When the resolution is `EXCHANGE`, every return line's `exchange_product_id` must be non-null and must reference a product that is not final-sale; a missing or final-sale exchange target is rejected with `ERR_EXCHANGE_TARGET_REQUIRED` (HTTP 422). Among these business checks the final-sale rule is evaluated first, then the return-window check, then the quantity-against-shipped check, then the exchange-target requirement. Opening the return creates the `ReturnAuthorization` in `REQUESTED` status together with its return-line rows, and previews the settlement figures described in §3.8.

### 3.7. Deciding a Return: Approve, Reject, Cancel

A `REQUESTED` return awaits a decision. A `StoreAdmin` may approve it, which is permitted only when the status is `REQUESTED` and requires `expected_return_version` to match the RMA's current `version` per §2.6; approval re-locks the settlement computation so that `settlement_cents` is frozen for the chosen resolution, advances the status from `REQUESTED` to `APPROVED`, and increments the RMA's `version`. Alternatively, a `StoreAdmin` may reject a `REQUESTED` return, which moves it to the terminal `REJECTED` status with no ledger movement and no effect on any order line's `returned_qty`. The owning `Customer` may instead cancel their own `REQUESTED` return — permitted only when the caller's `X-User-ID` equals the RMA's `customer_id` — which moves it to the terminal `CANCELLED` status, again with no ledger movement. A return that is not in `REQUESTED` status cannot be approved, rejected, or cancelled.

### 3.8. Settling a Return: Refund, Store Credit, and Exchange

Settlement is a `StoreAdmin` action permitted only on an `APPROVED` return, and the path it takes depends on the resolution that was chosen. The underlying settlement computation works line by line. For each return line, drawing on its order line, the returnable subtotal is that order line's `unit_price_cents_snapshot` multiplied by the line's `return_qty`. The allocated tax for the line is the order line's `line_tax_cents` multiplied by the `return_qty`, divided by the order line's `qty`, rounded half up. The line's share of the order-level promotion is computed in two rounded steps: first the line promo is the order's `promo_flat_cents` multiplied by that order line's full subtotal (its `unit_price_cents_snapshot` times its `qty`) divided by the order's `subtotal_cents`, rounded half up; then the returned portion of that line promo is the line promo multiplied by the `return_qty` divided by the order line's `qty`, rounded half up. The restocking fee is waived for a line when the RMA's `reason` is `DEFECTIVE` or `WRONG_ITEM`, or when the resolution is anything other than `REFUND`; when not waived, the line's restocking fee is the returnable subtotal multiplied by the product's `restocking_fee_bps`, divided by 10000, rounded half up, and is otherwise 0.

From these line figures the system aggregates three totals. The `refund_subtotal_cents` is the sum of the returnable subtotals over the lines. The `restocking_fee_cents` is the sum of the per-line restocking fees. A base refund — used by the cash and store-credit paths — is the sum over the lines of the returnable subtotal plus the allocated tax minus the returned promo share; shipping is never refunded. The settlement then branches on resolution. For a `REFUND`, the `settlement_cents` is the larger of 0 and the base refund minus the total restocking fee, and the money is paid back to the original payment method. For `STORE_CREDIT`, the restocking fee is always waived and a bonus is applied: the `settlement_cents` is the base refund multiplied by 10500, divided by 10000, rounded half up — that is, a 5 percent bonus on top of the base — making store credit strictly larger than the equivalent cash refund for identical inputs.

Settling a `REFUND` or `STORE_CREDIT` return advances the status from `APPROVED` to `REFUNDED` and runs a three-link cascade. First, it creates a `Refund` in `SETTLED` status whose `destination` is `ORIGINAL_PAYMENT` when the resolution is `REFUND` and `STORE_CREDIT` when the resolution is `STORE_CREDIT`, whose `amount_cents` equals the RMA's `settlement_cents`, and which records the settled `return_authorization_id` along with the denormalized `order_id` and `customer_id`; a refund is created already settled in this immediate-consistency model, and its `amount_cents` may not be negative. Second, when the destination is `STORE_CREDIT`, the system writes a `CreditLedgerEntry` of kind `REFUND_CREDIT` whose `amount_cents` is the positive settlement amount and whose `refund_id` points at the new refund, after which the customer's `store_credit_cents` is recomputed. Third, each returned order line's `returned_qty` is recomputed — the units now count as returned — and the customer's `lifetime_refunded_cents` and `return_risk_score` are recomputed. When the destination is `ORIGINAL_PAYMENT`, the order's payment dimension bubbles up: if the cumulative `amount_cents` of `ORIGINAL_PAYMENT` refunds for the order is still less than `captured_total_cents` the order moves to `PARTIALLY_REFUNDED`, and when that cumulative total reaches `captured_total_cents` the order moves to `REFUNDED`.

Settling an `EXCHANGE` return advances the status from `APPROVED` to `EXCHANGED` and requires that the exchange product have an `available_qty` of at least the `return_qty` in at least one warehouse; insufficient stock is rejected with `ERR_EXCHANGE_OUT_OF_STOCK` (HTTP 422). The exchange `settlement_cents` is a sign-magnitude delta: the sum over the lines of the exchange product's `unit_price_cents` multiplied by the `return_qty`, minus the RMA's `refund_subtotal_cents`; no restocking fee ever applies to an exchange. A positive delta means the customer owes the store, and it is recorded as a positive owed amount collected on the original payment. A negative delta means the store owes the customer, and its absolute value is issued as store credit: the system creates a `CreditLedgerEntry` of kind `REFUND_CREDIT` for that absolute amount together with a `Refund` whose `destination` is `STORE_CREDIT`, then recomputes the customer's `store_credit_cents`. In either case each returned order line's `returned_qty` is recomputed and a `HELD` reservation is created for the replacement exchange product.

### 3.9. Restocking, Customer Ledgers, and Return Risk

After a return has produced its refund (or for a restock-only resolution), a `WarehouseOperator` may restock the returned units. The request supplies the target `warehouse_id`, which must have `accepts_returns` set to true; a warehouse that does not accept returns is rejected with `ERR_WAREHOUSE_REJECTS_RETURNS` (HTTP 422). Restocking is permitted only on an `APPROVED` return that has already produced a refund, advances the status to `RESTOCKED`, increments each chosen `InventoryItem`'s `on_hand_qty` by the corresponding `return_qty`, and recomputes that item's `available_qty`.

A customer is brought into being by self-registration, supplying a login `email` (unique across all customers) and a display `full_name`; the new `Customer` starts with `store_credit_cents`, `lifetime_purchased_cents`, `lifetime_refunded_cents`, and `return_risk_score` all at 0. Every customer carries a running financial picture. The `store_credit_cents` balance is the sum of the `amount_cents` of all of that customer's credit ledger entries and is never allowed to go negative. The `lifetime_purchased_cents` figure is the sum of `captured_total_cents` over the customer's orders whose `payment_status` is `CAPTURED`, excluding carts and voided orders. The `lifetime_refunded_cents` figure is the sum of `amount_cents` over the customer's refunds whose status is `SETTLED`, across all destinations. These lifetime figures span the customer's entire history and count only rows in their terminal, counted states.

A `StoreAdmin` may directly adjust a customer's credit by recording a signed `amount_cents` with a `kind` of `REFUND_CREDIT`, `ADMIN_ADJUSTMENT`, or `REDEMPTION`; a positive amount grants credit and a negative amount redeems it. The adjustment writes a `CreditLedgerEntry` and recomputes the customer's `store_credit_cents`, but it is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 422) if applying it would drive the balance below 0. Each ledger entry records the affected `customer_id`, the optional `refund_id` that issued it (null for non-refund adjustments), the signed `amount_cents`, and its `kind`.

The platform also derives a `return_risk_score` for each customer, refreshed whenever payment capture changes lifetime purchases or a refund settlement changes lifetime refunds. The lifetime score is the customer's `lifetime_refunded_cents` divided by their `lifetime_purchased_cents`, rounded half up to four decimal places; when lifetime purchases are 0 the score is 0. A customer whose score is at least 0.5 is considered high-risk. A `StoreAdmin` may also request a trailing-window variant of this score by supplying a `window_days` query parameter: the numerator and denominator are then restricted to orders captured and refunds settled on or after the current clock minus that many days (comparing each order's and refund's `created_at` against that cutoff), which yields a different score than the lifetime figure because a recent burst of returns scores higher within the window than when averaged over the customer's whole history.

A customer's full standing is reachable through a set of reverse-lookup listings: their orders, their credit ledger entries, their refunds, and their RMAs across all orders. An order's lines, shipments, returns, and refunds; a return's lines and refunds; a refund's credit entries; a reservation's committing shipment lines; and an order line's reservations (optionally filtered to a specific warehouse via a `warehouse_id` query parameter), shipment lines, and return lines are all individually listable as well.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. Read operations return `200 OK`.

To reconstruct the full request body, response body, and side effects of any endpoint below, refer back to the workflow narratives of §3; this table is intentionally limited to method, path, purpose, and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | Anonymous, StoreAdmin |
| GET | `/customers/{id}` | Fetch a customer with computed ledgers and risk score | Customer, StoreAdmin |
| GET | `/customers/{id}/risk` | Computed read: lifetime or trailing-window return-risk score | StoreAdmin |
| GET | `/customers/{id}/orders` | List a customer's orders | Customer, StoreAdmin |
| GET | `/customers/{id}/credit-entries` | List a customer's credit ledger entries | Customer, StoreAdmin |
| GET | `/customers/{id}/refunds` | List a customer's refunds | Customer, StoreAdmin |
| GET | `/customers/{id}/returns` | List a customer's RMAs across orders | Customer, StoreAdmin |
| POST | `/customers/{id}/credit-adjustments` | Adjust store credit or record a redemption | StoreAdmin |
| POST | `/warehouses` | Create a warehouse | StoreAdmin |
| GET | `/warehouses/{id}` | Fetch a warehouse | StoreAdmin, WarehouseOperator |
| GET | `/warehouses/{id}/inventory` | List inventory items in a warehouse | StoreAdmin, WarehouseOperator |
| GET | `/warehouses/{id}/shipments` | List shipments dispatched from a warehouse | StoreAdmin, WarehouseOperator |
| GET | `/warehouses/{id}/reservations` | List reservations held at a warehouse | StoreAdmin, WarehouseOperator |
| POST | `/products` | Create a product | StoreAdmin |
| GET | `/products/{id}` | Fetch a product | Anonymous, Customer, StoreAdmin, WarehouseOperator |
| GET | `/products/{id}/inventory` | List inventory items for a product across warehouses | StoreAdmin, WarehouseOperator |
| GET | `/products/{id}/reservations` | List reservations for a product | StoreAdmin, WarehouseOperator |
| GET | `/products/{id}/order-lines` | List order lines that purchased this product | StoreAdmin |
| GET | `/products/{id}/return-lines` | List return lines naming this product as exchange target | StoreAdmin |
| POST | `/inventory` | Create/stock an inventory item for a product and warehouse | StoreAdmin, WarehouseOperator |
| GET | `/inventory/{id}` | Fetch an inventory item with computed reserved/available | StoreAdmin, WarehouseOperator |
| GET | `/reservations/{id}` | Fetch a single reservation with its status | StoreAdmin, WarehouseOperator |
| GET | `/reservations/{id}/shipment-lines` | List shipment lines that committed a reservation | StoreAdmin, WarehouseOperator |
| POST | `/orders` | Create an empty cart for a customer | Customer, StoreAdmin |
| GET | `/orders/{id}` | Fetch an order with both status dimensions and totals | Customer, StoreAdmin, WarehouseOperator |
| POST | `/orders/{id}/lines` | Add a line to a CART order | Customer, StoreAdmin |
| GET | `/orders/{id}/lines` | List order lines | Customer, StoreAdmin, WarehouseOperator |
| GET | `/order-lines/{id}` | Fetch a single order line | Customer, StoreAdmin, WarehouseOperator |
| GET | `/order-lines/{id}/reservations` | List reservations serving an order line | StoreAdmin, WarehouseOperator |
| GET | `/order-lines/{id}/shipment-lines` | List shipment lines fulfilling an order line | StoreAdmin, WarehouseOperator |
| GET | `/order-lines/{id}/return-lines` | List return lines against an order line | Customer, StoreAdmin |
| POST | `/orders/{id}/checkout` | Price the cart, reserve inventory, authorize payment | Customer |
| POST | `/orders/{id}/capture-payment` | Capture an authorized order's payment | StoreAdmin |
| POST | `/orders/{id}/void` | Void an authorized, not-yet-shipped order | StoreAdmin |
| GET | `/orders/{id}/refunds` | List refunds issued against an order | Customer, StoreAdmin |
| POST | `/orders/{id}/shipments` | Create a PENDING shipment from one warehouse | WarehouseOperator, StoreAdmin |
| GET | `/orders/{id}/shipments` | List shipments of an order | Customer, StoreAdmin, WarehouseOperator |
| GET | `/shipments/{id}` | Fetch a shipment | Customer, StoreAdmin, WarehouseOperator |
| GET | `/shipments/{id}/lines` | List shipment lines | Customer, StoreAdmin, WarehouseOperator |
| POST | `/shipments/{id}/ship` | Dispatch a PENDING shipment | WarehouseOperator |
| POST | `/shipments/{id}/deliver` | Mark a SHIPPED shipment DELIVERED | WarehouseOperator |
| POST | `/shipments/{id}/cancel` | Cancel a PENDING shipment | WarehouseOperator |
| POST | `/orders/{id}/returns` | Open an RMA against a CAPTURED order | Customer, StoreAdmin |
| GET | `/orders/{id}/returns` | List RMAs of an order | Customer, StoreAdmin |
| GET | `/returns/{id}` | Fetch an RMA with computed settlement figures | Customer, StoreAdmin |
| GET | `/returns/{id}/lines` | List return lines | Customer, StoreAdmin |
| GET | `/returns/{id}/refunds` | List refunds produced by an RMA | Customer, StoreAdmin |
| GET | `/refunds/{id}` | Fetch a single refund with destination and amount | Customer, StoreAdmin |
| GET | `/refunds/{id}/credit-entries` | List credit ledger entries issued by a refund | Customer, StoreAdmin |
| POST | `/returns/{id}/approve` | Approve a REQUESTED RMA; lock settlement | StoreAdmin |
| POST | `/returns/{id}/reject` | Reject a REQUESTED RMA | StoreAdmin |
| POST | `/returns/{id}/cancel` | Cancel one's own REQUESTED RMA | Customer |
| POST | `/returns/{id}/settle` | Settle an APPROVED RMA | StoreAdmin |
| POST | `/returns/{id}/restock` | Restock returned units into an accepts-returns warehouse | WarehouseOperator |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | StoreAdmin, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_RETURN_VERSION` | 412 Precondition Failed |
| `ERR_FINAL_SALE_NOT_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_RETURN_QTY_EXCEEDS_SHIPPED` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_TARGET_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RESERVATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_OUT_OF_STOCK` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 422 Unprocessable Entity |
| `ERR_WAREHOUSE_REJECTS_RETURNS` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
