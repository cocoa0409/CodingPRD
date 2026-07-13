# Restaurant Supply & Smallwares Distribution API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Restaurant Supply & Smallwares Distribution API, a business-to-business (B2B) platform in the spirit of large foodservice distributors. The system serves three constituencies whose work must stay perfectly reconciled: account managers who onboard commercial buyers and govern their credit, buyers who place and pay for wholesale orders, and warehouse operators who own the catalog, fulfill shipments, process returns, and schedule dock deliveries and equipment installations.

The platform's defining challenge is that a single wholesale order touches pricing, inventory, credit, tax, freight, and scheduling at once, and each of those dimensions carries its own rules. Case-and-pallet tier pricing must resolve to the cheapest whole-tier breakdown; stock must be allocated (or backordered) atomically at confirmation; freight must be quoted provisionally from what was ordered and re-quoted finally from what actually shipped; sales tax must respect a buyer's tax-exempt certification; and every credit reservation must be protected against acting on a stale view of the account. Returns, restock fees, and inventory replenishment close the loop after delivery.

Because these concerns interlock, the API is built around immediate consistency: whenever an order, shipment, return, or certificate changes state, every derived figure it influences — inventory counts, reorder signals, order totals, and an account's outstanding balance — is recomputed in the same operation. A server-controlled logical clock drives all time-sensitive rules (certificate expiry, return windows, and equipment lead times), so behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly three roles, spelled precisely as `AccountManager`, `Buyer`, and `WarehouseOps`.

- An `AccountManager` administers accounts, credit terms and limits, credit holds, and tax-exempt certificate approvals, and invoices confirmed orders.
- A `Buyer` is the B2B customer and drives their own account's orders, order lines, payments, returns, and certificate submissions.
- A `WarehouseOps` operator owns the catalog and inventory, order fulfillment (shipments), returns processing, and dock and install scheduling, and is the only role permitted to advance the logical clock.

The `Buyer` role is entity-backed. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an account compare the resource's account to `X-User-ID`. Concretely, for orders, returns, and certificates, the resource's `account_id` (directly, or transitively through the order for returns and lines) must equal the `Buyer`'s `X-User-ID`; a mismatch is rejected with `ERR_NOT_ACCOUNT_OWNER`. This ownership check applies to all `Buyer`-scoped writes: creating, confirming, cancelling, or paying an order; creating or resubmitting a certificate; and opening a return or adding a return line.

The `AccountManager` and `WarehouseOps` roles are opaque operator identifiers. When `X-User-Role` is `AccountManager` or `WarehouseOps`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. All three roles may perform `GET` reads across accounts, certificates, products, orders, order lines, shipments, returns, return lines, docks, delivery appointments, install crews, and install jobs.

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

All list endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` supplied outside these bounds is clamped to the nearest valid value rather than rejected (a `limit` above 100 becomes 100, a `limit` below 1 becomes 1, and a negative `offset` becomes 0), while a `limit` or `offset` that is not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching items before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (see §2.9).

The following entities carry all four fields: `Account`, `TaxExemptCertificate`, `Product`, `PurchaseOrder`, `OrderLine`, `Shipment`, `ReturnAuthorization`, `ReturnLine`, `Dock`, `DeliveryAppointment`, `InstallCrew`, and `InstallJob`. Every entity in this system carries the full common set; none is version-free. When a derived field on a resource is recomputed as a side effect of another operation (for example, an account's outstanding balance changing because an order was confirmed), that recomputation is itself a mutation of the affected resource: it refreshes `updated_at` and increments `version`.

### 2.5. Monetary Values, Weights, and Precision

All monetary amounts are stored and returned as integer cents; the field names carrying money end in `_cents`. Where a calculation multiplies an integer amount by a fractional rate — sales tax, per-pound freight, and restock fees — the result is rounded to a whole number of cents using the round-half-up convention (a fractional cent of exactly one-half rounds up). Where a rounding step is specified as per-line, each line's figure is rounded to whole cents before any summation across lines; summing first and rounding once is explicitly not equivalent and must not be substituted. Calculations that involve only integer terms (such as tier pricing) need no rounding, as every term is already in whole cents.

Shipping weight is expressed in whole pounds. Each product declares its `weight_lbs_per_unit`, and shipment weight is the sum of per-each weights across the eaches being weighed.

### 2.6. The Logical Clock

All time-dependent behavior is driven by a server-held logical clock rather than wall-clock time. On startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. A `WarehouseOps` operator may advance the clock by supplying a target instant, `to_iso8601`, through an administrative test-driving capability; the description column of §4 identifies the corresponding endpoint.

Advancing the clock has a side effect: any `TaxExemptCertificate` currently in `APPROVED` state whose `expiry_date` is at or before the new clock instant transitions to `EXPIRED`, and each such certificate's owning account moves its `tax_exempt_status` to `EXPIRED` with the account's `version` incremented. All other time-sensitive rules — certificate approval eligibility, the return window, and equipment install lead times — read the current clock instant at the moment the relevant operation is attempted.

### 2.7. Nested Resource Retrieval and Filtered Listing

The API is a flat, multi-collection API: each entity is addressed under its own top-level collection, and cross-references between entities are carried as identifier fields rather than deep URL nesting. When an endpoint path names a resource identifier — for example a `cert_id`, `order_id`, `order_line_id`, `shipment_id`, `return_id`, `return_line_id`, `dock_id`, `appointment_id`, `crew_id`, `job_id`, `account_id`, or `product_id` — that identifier is validated for existence. When a path contains more than one identifier, they are validated left to right, and the first identifier that does not resolve produces the corresponding not-found error (for instance `ERR_ACCOUNT_NOT_FOUND`, `ERR_CERT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_RETURN_LINE_NOT_FOUND`, `ERR_DOCK_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, or `ERR_JOB_NOT_FOUND`).

Several list endpoints accept optional filter parameters that reach across collections by foreign key. Certificates may be filtered by `account_id`; orders may be filtered by `account_id`; order lines may be filtered by `order_id` and/or `product_id`; shipments and returns may be filtered by `order_id`; return lines may be filtered by `return_id` and/or `product_id`; and delivery appointments and install jobs may be filtered by `order_id` and, respectively, by `dock_id` or `crew_id`. These filters combine with the standard `limit` and `offset` pagination parameters.

### 2.8. Cascading State Consistency

Many operations mutate more than one resource. The system applies every such cascade in the same operation and never leaves derived figures stale. Three recurring patterns govern this:

- **Order confirmation and cancellation reach into inventory.** Confirming an order draws stock from products and may leave lines backordered; cancelling a confirmed order returns that stock. In both directions, every product touched has its reorder signals recomputed, and the account's balance is recomputed because the set of orders counting against credit has changed.
- **Shipment booking and delivery drive the parent order.** Booking a shipment advances its order and every non-cancelled line to shipped; delivering it completes the order. These order and line transitions occur as system side effects of the shipment action, not as separate client requests.
- **Return receipt restocks inventory; return refund credits the account.** Receiving returned goods increments product stock and recomputes reorder signals; refunding credits the return amount against the owning account's outstanding balance.

Each affected resource independently records the mutation by refreshing `updated_at` and incrementing `version`.

### 2.9. Optimistic Concurrency on Account Version

Confirming an order reserves credit against the owning account, so the confirming client must prove it is acting on a fresh view of that account. The confirm request must carry `expected_account_version`, and its value must equal the owning account's current `version`. If another operation — a different order confirmed against the same account, a certificate approved or expired, or a credit hold applied — has advanced the account's `version` since the client last read it, the account's `credit_available_cents` has moved, and a confirm still carrying the earlier `expected_account_version` is rejected as stale with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). This is the point at which a later confirmation legitimately supersedes a client's outdated view of remaining credit. Confirming an order is the only operation that takes an expected-version field; no other endpoint requires one.

### 2.10. The Credit Ledger and Outstanding Balance

Each account exposes two read-only figures that are recomputed on every event that could move them — order confirmation, order cancellation, order payment, and return refund — as well as whenever the account is read. The `outstanding_cents` figure is the sum of `total_cents` across the account's orders whose `lifecycle_status` is `CONFIRMED`, `SHIPPED`, or `COMPLETED` and whose `payment_status` is `UNPAID` or `INVOICED`, reduced by the sum of `refund_cents` across the account's returns whose `status` is `REFUNDED`. The `credit_available_cents` figure is the account's `credit_limit_cents` minus its `outstanding_cents`. An order that has been paid (payment status `PAID`) no longer counts toward the outstanding balance, and neither does a draft or cancelled order.

## 3. Business Logic & Workflows

### 3.1. Accounts, Credit Terms, and Credit Holds

An `AccountManager` onboards a commercial buyer by creating an `Account` with a `business_name`, a `credit_terms` selection, and a `credit_limit_cents`. The `credit_terms` value is one of `PREPAID`, `NET_15`, or `NET_30`. The `credit_limit_cents` is the maximum outstanding balance the account may carry and must be zero or greater. An optional `tax_rate` may be supplied; when omitted it defaults to 0.08, and it is the sales-tax rate applied to taxable line subtotals whenever the account is not tax-exempt. A newly created account begins with `status` set to `ACTIVE`, `tax_exempt_status` set to `NONE`, an outstanding balance of zero, and `version` 1.

An account's `status` is either `ACTIVE` or `SUSPENDED`. Placing a credit hold moves an `ACTIVE` account to `SUSPENDED`; the account must be `ACTIVE` for this to be allowed, and an attempt on an already-suspended account is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. Lifting a hold moves a `SUSPENDED` account back to `ACTIVE`, and requires the account to currently be `SUSPENDED`, otherwise `ERR_ACCOUNT_NOT_SUSPENDED`. Both transitions increment the account's `version`. A suspended account cannot have new orders confirmed against it, as described in §3.5.

### 3.2. Tax-Exempt Certification Lifecycle

A `Buyer` submits a `TaxExemptCertificate` for their own account, providing a `cert_number`, a two-letter `state_code` for the state the exemption covers, and an `expiry_date` (the ISO 8601 UTC instant at or after which the certificate is considered expired). The certificate records the owning `account_id` and enters `SUBMITTED` state. Because this is a buyer-scoped write, the acting `Buyer`'s `X-User-ID` must equal the account it is filed against, or the request is rejected with `ERR_NOT_ACCOUNT_OWNER`.

A certificate moves through the states `SUBMITTED`, `APPROVED`, `REJECTED`, and `EXPIRED`. An `AccountManager` reviews a `SUBMITTED` certificate and either approves or rejects it. Approval requires the certificate to be `SUBMITTED` (otherwise `ERR_CERT_NOT_SUBMITTED`) and requires the certificate's `expiry_date` to be strictly after the current logical clock instant (otherwise `ERR_CERT_ALREADY_EXPIRED`). On approval the certificate transitions `SUBMITTED → APPROVED`, and the owning account's `tax_exempt_status` becomes `CERTIFIED` with the account's `version` incremented — from this point the account's taxable lines are exempt from tax. Rejection also requires the certificate to be `SUBMITTED` (otherwise `ERR_CERT_NOT_SUBMITTED`) and simply transitions it `SUBMITTED → REJECTED` with no effect on the account.

A rejected certificate can re-enter review. The owning `Buyer` may resubmit it, which requires the certificate to be `REJECTED` (otherwise `ERR_CERT_NOT_REJECTED`) and requires the acting `Buyer`'s `X-User-ID` to equal the certificate's `account_id` (otherwise `ERR_NOT_ACCOUNT_OWNER`); the certificate cycles `REJECTED → SUBMITTED` for a fresh review. Finally, an approved certificate expires automatically: as described in §2.6, when the logical clock advances to an instant at or after a certificate's `expiry_date`, an `APPROVED` certificate transitions `APPROVED → EXPIRED` and its owning account's `tax_exempt_status` moves to `EXPIRED`, incrementing the account's `version`. The `EXPIRED` state is terminal.

### 3.3. The Product Catalog, Tiered Pricing, and Reorder Signals

A `WarehouseOps` operator creates catalog products. A `Product` carries a `sku`, a display `name`, and a `category` of `SMALLWARE`, `EQUIPMENT`, or `CONSUMABLE`. A `taxable` flag (defaulting to true) controls whether the product's line subtotal is taxed. Pricing is defined across three tiers: `unit_price_cents` is the per-each price, `case_price_cents` is the price of one full case, and `pallet_price_cents` is the price of one full pallet; `case_qty` is the number of eaches in a case (at least 1) and `pallet_case_qty` is the number of cases in a pallet (at least 1). Each product also declares its `weight_lbs_per_unit`, a `fulfillment_type` of `STOCK` or `DROPSHIP`, a `freight_type` hint of `PARCEL` or `LTL`, and — for equipment — a `lead_time_days` (defaulting to 0) that is the whole-day lead time required before an install may be scheduled. Inventory fields are `on_hand_qty` (physical eaches in stock), `par_level` (the target replenishment level), and `reorder_point` (the stock level at or below which the product needs reordering). A `WarehouseOps` operator may also manually restock a product by supplying a `quantity`, which is added to `on_hand_qty`.

Two read-only reorder signals are recomputed whenever a product's `on_hand_qty` changes (on creation, restock, order allocation, order cancellation, or return receipt). The `needs_reorder` flag is true exactly when `on_hand_qty` is less than or equal to `reorder_point`. The `reorder_suggested_qty` is the target-level shortfall — the `par_level` minus the current `on_hand_qty` — but only when the product needs reordering, and it is never negative; when the product does not need reordering it is zero. Equivalently, when `needs_reorder` holds, the suggested quantity is the larger of zero and `par_level` minus `on_hand_qty`, and otherwise it is zero.

Tiered line pricing resolves a requested quantity to the cheapest whole-tier breakdown. Given the requested `quantity` and the product's tier definitions, first compute the number of eaches per pallet as `case_qty` multiplied by `pallet_case_qty`. The number of full pallets is the integer quotient of the quantity divided by eaches-per-pallet; the remainder after removing those pallets is then divided by `case_qty` to yield the number of full cases, and whatever eaches remain after removing full cases are priced individually. The `line_subtotal_cents` is the number of full pallets times `pallet_price_cents`, plus the number of full cases times `case_price_cents`, plus the leftover eaches times `unit_price_cents`. The `pricing_tier` records the highest whole tier reached: it is `PALLET` if there is at least one full pallet, otherwise `CASE` if there is at least one full case, otherwise `EACH`. As a boundary illustration, a quantity of exactly `case_qty` (with no full pallet) is one full case and prices as `CASE`, while a quantity of `case_qty` minus one is all eaches and prices as `EACH`. All terms are whole cents, so no rounding is applied.

### 3.4. Building an Order: Drafts and Lines

A `Buyer` opens a `PurchaseOrder` for their own account by supplying the `account_id`; the acting `Buyer`'s `X-User-ID` must equal that account, or the request is rejected with `ERR_NOT_ACCOUNT_OWNER`. A new order begins in `lifecycle_status` `DRAFT` with `payment_status` `UNPAID` and `freight_cents` of 0; its `confirmed_at` is null until the order is confirmed. The order also exposes read-only rollups: `merchandise_subtotal_cents` (the sum of `line_subtotal_cents` over the order's non-cancelled lines), `tax_cents`, `freight_cents`, and `total_cents` (which is the merchandise subtotal plus tax plus freight).

While an order is `DRAFT`, the `Buyer` adds lines to it, each naming a `product_id` and a `quantity` of at least one. Adding a line computes that line's `pricing_tier` and `line_subtotal_cents` using the tiered pricing of §3.3, and recomputes the order's merchandise subtotal and tax. Adding a line is only permitted while the order is `DRAFT`; attempting it on a non-draft order is rejected with `ERR_ORDER_NOT_DRAFT`. Each `OrderLine` records its parent `order_id`, and while pending carries `allocated_qty` and `backordered_qty` of 0 and a `status` of `PENDING`; the full status vocabulary a line may occupy across the order's lifecycle is `PENDING`, `ALLOCATED`, `PARTIAL`, `BACKORDERED`, `DROPSHIP_PENDING`, `SHIPPED`, and `CANCELLED`.

Order tax is recomputed whenever the lines change while the order is `DRAFT`, and again at confirmation. If the owning account's `tax_exempt_status` is `CERTIFIED` at the moment tax is computed, the order's `tax_cents` is zero. Otherwise, tax is assessed line by line: for each non-cancelled line whose product's `taxable` flag is true, multiply that line's `line_subtotal_cents` by the account's `tax_rate` and round the product to whole cents using round-half-up; the order's `tax_cents` is the sum of those per-line rounded amounts. The per-line rounding happens first, before summation, and this may differ from rounding a single grand total.

### 3.5. Confirming an Order: Allocation, Backorder, and Credit Reservation

Confirmation is the pivotal transition in an order's life, moving it `DRAFT → CONFIRMED`. It is performed by the owning `Buyer` and carries a single input, `expected_account_version`. The system evaluates the following preconditions in this order, stopping at the first that fails: the order must exist and, being buyer-scoped, must be owned by the acting `Buyer` (`ERR_NOT_ACCOUNT_OWNER`); the order must be in `DRAFT` (`ERR_ORDER_NOT_DRAFT`); the order must have at least one non-cancelled line (`ERR_ORDER_HAS_NO_LINES`); the owning account's `status` must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the order's `total_cents` computed as merchandise subtotal plus tax, with freight still 0, must be less than or equal to the account's `credit_available_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`); and finally `expected_account_version` must match the account's current `version` (`ERR_STALE_ACCOUNT_VERSION`). Evaluating the credit and account-state checks before the stale-version check means a genuine business rejection surfaces on its own terms rather than being masked by a version mismatch.

On success, the order stamps `confirmed_at` with the current logical clock instant and performs a stock cascade line by line. For each `STOCK` line, the allocated quantity is the smaller of the line's `quantity` and the product's current `on_hand_qty`; the backordered quantity is the line's `quantity` minus that allocated amount; and the product's `on_hand_qty` is decremented by the allocated amount. The line's `status` becomes `ALLOCATED` when nothing is backordered, `PARTIAL` when some but not all of the quantity was allocated, and `BACKORDERED` when nothing could be allocated. Each `DROPSHIP` line instead moves to `DROPSHIP_PENDING` and never draws from `on_hand_qty`. Every product whose stock changed has its `needs_reorder` and `reorder_suggested_qty` recomputed. The order then recomputes its `tax_cents`, `merchandise_subtotal_cents`, and `total_cents`; the owning account's outstanding and available credit are recomputed because the order now counts; the account's `version` is incremented (this is the optimistic-concurrency advance of §2.9); and the order settles into `CONFIRMED` with `payment_status` unchanged at `UNPAID`.

Cancellation is available while an order is `DRAFT` or `CONFIRMED`; attempting it in any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling a `DRAFT` order simply marks every non-cancelled line `CANCELLED` and moves the order `DRAFT → CANCELLED`. Cancelling a `CONFIRMED` order additionally compensates the earlier allocation: for each `STOCK` line, the product's `on_hand_qty` is increased by that line's `allocated_qty`, and the line's `allocated_qty` and `backordered_qty` are reset to 0; each affected product's reorder signals are recomputed; every non-cancelled line becomes `CANCELLED`; the account's outstanding and available credit are recomputed because the order no longer counts; and the order moves `CONFIRMED → CANCELLED`.

### 3.6. Invoicing and Payment

An order's payment progresses on a dimension parallel to its lifecycle. The `payment_status` values are `UNPAID`, `INVOICED`, and `PAID`, and this dimension evolves independently once the order is `CONFIRMED`. An `AccountManager` invoices an order whose `lifecycle_status` is `CONFIRMED` or `SHIPPED` (otherwise `ERR_ORDER_NOT_CONFIRMED`) and whose `payment_status` is `UNPAID` (otherwise `ERR_PAYMENT_NOT_UNPAID`); this moves the payment dimension to `INVOICED` while leaving `lifecycle_status` untouched. The owning `Buyer` then records payment on an order whose `payment_status` is `INVOICED` (otherwise `ERR_PAYMENT_NOT_INVOICED`); this moves the payment dimension to `PAID` and recomputes the account's outstanding and available credit, since a paid order no longer counts against the balance.

### 3.7. Shipping: Freight Quoting, Booking, and Delivery

A `WarehouseOps` operator opens fulfillment by creating a `Shipment` quote for a confirmed order, supplying the `order_id`, a `carrier` name, and an optional `liftgate_required` flag (defaulting to false). Shipment creation validates only that the `order_id` resolves; it does not check the order's `lifecycle_status`, so the `CONFIRMED` requirement is enforced at booking rather than at creation. A shipment moves through `QUOTED`, `BOOKED`, `DELIVERED`, and `CANCELLED`. At creation the shipment is `QUOTED`; the system computes its `shipping_mode` and a provisional `freight_quote_cents`, writes that quote onto the order's `freight_cents`, and recomputes the order total.

Freight is computed from a shipped weight. The weight is the sum, over the order's non-cancelled, non-dropship lines, of a per-line quantity multiplied by the product's `weight_lbs_per_unit`. There are two variants that differ only in which quantity feeds the weight. The provisional variant, used at shipment creation for `freight_quote_cents`, weighs each line's ordered `quantity` (so it includes eaches that were backordered). The final variant, used at booking for `final_freight_cents`, weighs each line's `allocated_qty` only, so it diverges from the provisional figure whenever any line was partially or fully backordered. Given the weight, the mode and charge follow a weight breakpoint: if the weight is at most 150 pounds, the `shipping_mode` is `PARCEL` and the base charge is 1200 cents plus 50 cents per pound multiplied by the weight (that per-pound product rounded half-up to whole cents); however, if the order's `merchandise_subtotal_cents` is at least 250000 cents, the base charge is instead 0 (free freight), and no liftgate fee ever applies to a parcel shipment. If the weight exceeds 150 pounds, the `shipping_mode` is `LTL` and the freight is 7500 cents plus 30 cents per pound multiplied by the weight (that product rounded half-up), plus a 4500-cent liftgate fee when `liftgate_required` is true.

Booking a quoted shipment is performed by `WarehouseOps` and may supply an updated `carrier`. It requires the shipment to be `QUOTED` (otherwise `ERR_SHIPMENT_NOT_QUOTED`) and its order to be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`). Booking computes `final_freight_cents` using the final freight variant over allocated quantities (also recomputing the shipment's `shipping_mode` from that final weight, so a mode set at `QUOTED` time may change when backorders reduce the shipped weight), writes it onto the order's `freight_cents`, recomputes the order total, and drives the order and its non-cancelled lines: the order advances `CONFIRMED → SHIPPED` and every such line becomes `SHIPPED`. Delivering a booked shipment is also a `WarehouseOps` action and requires the shipment to be `BOOKED` (otherwise `ERR_SHIPMENT_NOT_BOOKED`); it stamps the shipment's `delivered_at` with the current clock instant, advances the shipment to `DELIVERED`, and moves the order `SHIPPED → COMPLETED`, which opens the return window anchored at `delivered_at`. A shipment may be cancelled by `WarehouseOps` while it is `QUOTED` or `BOOKED` (otherwise `ERR_SHIPMENT_NOT_CANCELLABLE`); cancellation moves the shipment to `CANCELLED`, and if this shipment had set the order's `freight_cents`, that freight is reset to 0.

### 3.8. Returns, Restock Fees, and Refunds

Once an order is delivered, its owning `Buyer` may open a `ReturnAuthorization` against it, supplying a free-text `reason`. Opening a return requires the order to be in `COMPLETED` (delivered) state, otherwise `ERR_ORDER_NOT_COMPLETED`, and it must fall within the return window: the return may be opened only within 30 days of the order's shipment `delivered_at`, and a later attempt is rejected with `ERR_RETURN_WINDOW_EXPIRED`. Because opening a return is buyer-scoped, the acting `Buyer` must own the order (`ERR_NOT_ACCOUNT_OWNER`). A return begins in `REQUESTED` and progresses through `APPROVED`, `RECEIVED`, `REFUNDED`, and `REJECTED`, and records read-only `restock_fee_cents` and `refund_cents` that begin at 0.

The owning `Buyer` adds return lines while the return is `REQUESTED`; adding a line to a return in any other state is rejected with `ERR_RETURN_NOT_REQUESTED`. Each `ReturnLine` names a `product_id`, a `quantity` of at least one, and a `condition` of `SEALED` or `OPENED`, and records its parent `return_id` and a `line_refund_cents` of 0. Two business constraints guard a return line: the product must appear on the original order (otherwise `ERR_PRODUCT_NOT_IN_ORDER`), and the returned `quantity` must not exceed the quantity that was ordered for that product on the original order (otherwise `ERR_RETURN_QTY_EXCEEDS_ORDERED`). A return line begins in `PENDING` and later becomes `RECEIVED`.

A `WarehouseOps` operator processes the return. Approving it requires the return to be `REQUESTED` (otherwise `ERR_RETURN_NOT_REQUESTED`) and to have at least one return line (otherwise `ERR_RETURN_HAS_NO_LINES`). Approval computes fees and refunds per line: for each return line, the merchandise value is the line's `quantity` multiplied by the product's `unit_price_cents` (the each-price is always the return basis, regardless of the tier at which it was purchased); the restock percentage is 15 percent when the `condition` is `SEALED` and 25 percent when it is `OPENED`; the line's restock fee is that merchandise value multiplied by the percentage, rounded half-up to whole cents; and the line's `line_refund_cents` is the merchandise value minus that restock fee. The return's `restock_fee_cents` is the sum of the per-line restock fees and its `refund_cents` is the sum of the per-line refunds, after which it moves `REQUESTED → APPROVED`. A sealed line therefore yields a larger refund than an opened line of identical merchandise value.

An approved return can be sent back for revision by `WarehouseOps`, which requires it to be `APPROVED` (otherwise `ERR_RETURN_NOT_APPROVED`) and reverts the computed figures — the return's `refund_cents` and `restock_fee_cents` and each line's `line_refund_cents` are all reset to 0 — as it cycles `APPROVED → REQUESTED`. A `REQUESTED` return may instead be rejected by `WarehouseOps` (requiring the `REQUESTED` state, otherwise `ERR_RETURN_NOT_REQUESTED`), moving it `REQUESTED → REJECTED` with no inventory or ledger change; `REJECTED` is terminal. Receiving an approved return requires the `APPROVED` state (otherwise `ERR_RETURN_NOT_APPROVED`) and restocks inventory: each line moves to `RECEIVED` and the product's `on_hand_qty` is increased by that line's `quantity`, every affected product's reorder signals are recomputed, and the return moves `APPROVED → RECEIVED`. Finally, refunding a received return requires the `RECEIVED` state (otherwise `ERR_RETURN_NOT_RECEIVED`) and moves it `RECEIVED → REFUNDED`, at which point the owning account's outstanding and available credit are recomputed so that the return's `refund_cents` is credited against the outstanding balance. `REFUNDED` is terminal.

### 3.9. Dock Deliveries and Equipment Install Scheduling

Warehouse operations schedule physical delivery windows against docks and equipment installations against install crews. A `WarehouseOps` operator creates a `Dock` with a `name` and an optional `location` label (defaulting to an empty string when omitted), and an `InstallCrew` with a `name`. Delivery and install windows both use a half-open interval `[window_start, window_end)`, and both require `window_end` to be strictly after `window_start`, otherwise `ERR_INVALID_TIME_WINDOW`.

A `DeliveryAppointment` occupies a dock for an order. Creating one names the `order_id`, the `dock_id`, and the `window_start` and `window_end`; the appointment starts `SCHEDULED`. A dock has a capacity of one: the requested window may not overlap any existing `SCHEDULED` appointment on the same dock, where overlap uses half-open intersection so that two windows sharing only an endpoint (one ending exactly when the other starts) are considered adjacent and permitted; a genuine overlap is rejected with `ERR_DOCK_DOUBLE_BOOKED`. Cancelling an appointment requires it to be `SCHEDULED` (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`) and moves it `SCHEDULED → CANCELLED`, freeing the dock interval for later bookings.

An `InstallJob` occupies a crew to install an order's equipment. Creating one names the `order_id`, the `crew_id`, and the `window_start` and `window_end`; the job starts `SCHEDULED`. Two rules beyond the window-validity check apply. First, the order must contain at least one `EQUIPMENT` line, otherwise `ERR_NO_EQUIPMENT_LINE`. Second, the install may not be scheduled before its equipment lead time has elapsed: the `window_start` must be at or after the order's `confirmed_at` plus a number of days equal to the largest `lead_time_days` among the order's `EQUIPMENT` lines' products, and an earlier start is rejected with `ERR_LEAD_TIME_NOT_ELAPSED` (this lead-time check is applied only when the order has a `confirmed_at`; an order that was never confirmed carries a null `confirmed_at` and is not subject to it). Third, a crew enforces a 60-minute buffer between jobs: the new job conflicts with any existing `SCHEDULED` job on the same crew when the new window's start falls before that job's end extended by 60 minutes and that job's start falls before the new window's end extended by 60 minutes; such a conflict is rejected with `ERR_CREW_BUFFER_CONFLICT`. Cancelling an install job requires it to be `SCHEDULED` (otherwise `ERR_JOB_NOT_SCHEDULED`) and moves it `SCHEDULED → CANCELLED`, freeing the crew interval.

A general note on input validation applies across all create and update operations in this section and throughout §3: a malformed body, an unknown enum value, or an out-of-range numeric field (for example a negative quantity, a `case_qty` below 1, or an unrecognized category) is rejected with `ERR_INVALID_REQUEST`. This validation is the lowest-priority check, applied after the header, permission, ownership, existence, and state checks that precede it.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock capability — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a B2B account | AccountManager |
| GET | `/accounts` | List accounts | AccountManager, Buyer, WarehouseOps |
| GET | `/accounts/{account_id}` | Get an account | AccountManager, Buyer, WarehouseOps |
| POST | `/accounts/{account_id}/suspend` | Place a credit hold on an account | AccountManager |
| POST | `/accounts/{account_id}/reinstate` | Lift a credit hold | AccountManager |
| POST | `/accounts/{account_id}/tax-certificates` | Submit a tax-exempt certificate for the own account | Buyer |
| GET | `/accounts/{account_id}/tax-certificates` | List certificates for an account | AccountManager, Buyer, WarehouseOps |
| GET | `/tax-certificates` | List certificates, filterable by account | AccountManager, Buyer, WarehouseOps |
| GET | `/tax-certificates/{cert_id}` | Get a certificate | AccountManager, Buyer, WarehouseOps |
| POST | `/tax-certificates/{cert_id}/approve` | Approve a submitted certificate | AccountManager |
| POST | `/tax-certificates/{cert_id}/reject` | Reject a submitted certificate | AccountManager |
| POST | `/tax-certificates/{cert_id}/resubmit` | Resubmit a rejected certificate (owner only) | Buyer |
| POST | `/products` | Create a catalog product | WarehouseOps |
| GET | `/products` | List products | AccountManager, Buyer, WarehouseOps |
| GET | `/products/{product_id}` | Get a product | AccountManager, Buyer, WarehouseOps |
| POST | `/products/{product_id}/restock` | Manually add stock to a product | WarehouseOps |
| POST | `/orders` | Create a draft order for the own account | Buyer |
| GET | `/orders` | List orders, filterable by account | AccountManager, Buyer, WarehouseOps |
| GET | `/orders/{order_id}` | Get an order | AccountManager, Buyer, WarehouseOps |
| POST | `/orders/{order_id}/lines` | Add a line to a draft order | Buyer |
| GET | `/orders/{order_id}/lines` | List an order's lines | AccountManager, Buyer, WarehouseOps |
| GET | `/order-lines` | List order lines, filterable by order and/or product | AccountManager, Buyer, WarehouseOps |
| GET | `/order-lines/{order_line_id}` | Get a single order line | AccountManager, Buyer, WarehouseOps |
| POST | `/orders/{order_id}/confirm` | Confirm a draft order (allocate, price, reserve credit) | Buyer |
| POST | `/orders/{order_id}/cancel` | Cancel a draft or confirmed order | Buyer |
| POST | `/orders/{order_id}/invoice` | Invoice a confirmed order | AccountManager |
| POST | `/orders/{order_id}/pay` | Record payment on an invoiced order | Buyer |
| POST | `/shipments` | Create a shipment quote for a confirmed order | WarehouseOps |
| GET | `/shipments` | List shipments, filterable by order | AccountManager, Buyer, WarehouseOps |
| GET | `/shipments/{shipment_id}` | Get a shipment | AccountManager, Buyer, WarehouseOps |
| POST | `/shipments/{shipment_id}/book` | Book a quoted shipment; order becomes SHIPPED | WarehouseOps |
| POST | `/shipments/{shipment_id}/deliver` | Mark a booked shipment delivered; order COMPLETED | WarehouseOps |
| POST | `/shipments/{shipment_id}/cancel` | Cancel a quoted or booked shipment | WarehouseOps |
| POST | `/orders/{order_id}/returns` | Open an RMA against a delivered order (owner only) | Buyer |
| GET | `/returns` | List RMAs, filterable by order | AccountManager, Buyer, WarehouseOps |
| GET | `/returns/{return_id}` | Get an RMA | AccountManager, Buyer, WarehouseOps |
| POST | `/returns/{return_id}/lines` | Add a return line (owner only) | Buyer |
| GET | `/returns/{return_id}/lines` | List an RMA's return lines | AccountManager, Buyer, WarehouseOps |
| GET | `/return-lines` | List return lines, filterable by return and/or product | AccountManager, Buyer, WarehouseOps |
| GET | `/return-lines/{return_line_id}` | Get a single return line | AccountManager, Buyer, WarehouseOps |
| POST | `/returns/{return_id}/approve` | Approve an RMA (compute restock fees & refunds) | WarehouseOps |
| POST | `/returns/{return_id}/revise` | Send an approved RMA back to REQUESTED | WarehouseOps |
| POST | `/returns/{return_id}/reject` | Reject a requested RMA | WarehouseOps |
| POST | `/returns/{return_id}/receive` | Receive returned goods (restock inventory) | WarehouseOps |
| POST | `/returns/{return_id}/refund` | Refund a received RMA (credit account) | WarehouseOps |
| POST | `/docks` | Create a delivery dock/bay | WarehouseOps |
| GET | `/docks` | List docks | AccountManager, Buyer, WarehouseOps |
| GET | `/docks/{dock_id}` | Get a dock | AccountManager, Buyer, WarehouseOps |
| POST | `/delivery-appointments` | Schedule a dock delivery window | WarehouseOps |
| GET | `/delivery-appointments` | List delivery appointments, filterable by order or dock | AccountManager, Buyer, WarehouseOps |
| GET | `/delivery-appointments/{appointment_id}` | Get a delivery appointment | AccountManager, Buyer, WarehouseOps |
| POST | `/delivery-appointments/{appointment_id}/cancel` | Cancel a delivery appointment | WarehouseOps |
| POST | `/install-crews` | Create an equipment install crew | WarehouseOps |
| GET | `/install-crews` | List install crews | AccountManager, Buyer, WarehouseOps |
| GET | `/install-crews/{crew_id}` | Get an install crew | AccountManager, Buyer, WarehouseOps |
| POST | `/install-jobs` | Schedule an equipment install | WarehouseOps |
| GET | `/install-jobs` | List install jobs, filterable by order or crew | AccountManager, Buyer, WarehouseOps |
| GET | `/install-jobs/{job_id}` | Get an install job | AccountManager, Buyer, WarehouseOps |
| POST | `/install-jobs/{job_id}/cancel` | Cancel an install job | WarehouseOps |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | WarehouseOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_CERT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_DOCK_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_CERT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CERT_NOT_REJECTED` | 409 Conflict |
| `ERR_CERT_ALREADY_EXPIRED` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_PAYMENT_NOT_UNPAID` | 409 Conflict |
| `ERR_PAYMENT_NOT_INVOICED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_QUOTED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_BOOKED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RETURN_NOT_REQUESTED` | 409 Conflict |
| `ERR_RETURN_NOT_APPROVED` | 409 Conflict |
| `ERR_RETURN_NOT_RECEIVED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_JOB_NOT_SCHEDULED` | 409 Conflict |
| `ERR_PRODUCT_NOT_IN_ORDER` | 422 Unprocessable Entity |
| `ERR_RETURN_QTY_EXCEEDS_ORDERED` | 422 Unprocessable Entity |
| `ERR_ORDER_HAS_NO_LINES` | 422 Unprocessable Entity |
| `ERR_RETURN_HAS_NO_LINES` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_NO_EQUIPMENT_LINE` | 422 Unprocessable Entity |
| `ERR_DOCK_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREW_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
