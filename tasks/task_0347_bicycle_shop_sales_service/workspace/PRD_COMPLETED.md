# Bicycle Shop Sales & Service API — Product Requirements Document

## 1. Introduction

A neighborhood bicycle shop runs two intertwined businesses out of one stockroom: it sells bikes, parts, and accessories over the counter, and it runs a service department that tunes, repairs, and custom-builds bicycles. Both businesses draw down the same physical inventory, and both make promises to customers — a quoted turnaround on a tune-up, a held unit on a layaway, a procured part on a special order, a replacement frame under warranty. This API is the system of record that keeps those promises honest. It governs the full commercial lifecycle: catalog and stock, service tickets and the labor menu, tune-up tiers and turnaround quoting, custom builds gated on parts availability, layaway and special-order deposits, trade-in appraisal and store credit, warranty adjudication, and product recalls.

The central design tension is allocation. A single stock-keeping unit may be wanted at the same moment by a sales order at the register, a custom build on the workbench, a layaway plan in the back, and a special order on its way in. The system mediates all of these through a single reservation pool so that available units are never double-promised, and it uses optimistic concurrency to reject writes built on a stale view of that pool. Layered on top are the workflows themselves — a service ticket that loops back for re-approval whenever new labor is discovered mid-repair, a warranty claim that forks into repair, replacement, or denial, and a build that cannot begin assembly until every required part is in hand.

This document specifies the entities, state machines, calculations, validation rules, role permissions, endpoints, and error semantics that together define correct behavior. It is written for the engineer who will implement the service; the prose is the contract.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `SalesAssociate`, `ServiceAdvisor`, `ShopManager`, and `Customer`. When an authenticated caller invokes an endpoint their role is not permitted to use, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The first three roles are operator roles whose identities are opaque. When `X-User-Role` is `SalesAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `ServiceAdvisor` and for `ShopManager`: each is an opaque staff identifier, never matched against a stored entity's identity. `ShopManager` is a hierarchical override role: in addition to its exclusive catalog, recall, trade-in, and forfeit powers, a `ShopManager` may perform any operation a `SalesAssociate` may perform.

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. The one place a customer takes an action that mutates a resource is approving the quote on their own service ticket. When a `Customer` approves a ticket, the acting `X-User-ID` must equal that ticket's `customer_id`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. (A ticket created as the execution of an approved warranty claim is an exception described in §3, where the customer-ownership requirement is relaxed.)

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include the following fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every resource is assigned a server-minted `id`, a UUID string carrying no type prefix. Most resources also carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increases by exactly one on every mutation of that resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every mutation.

Three entities are append-only or immutable ledger-style records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version` field at all: `RecallNotice`, `RecallAck`, and `Payment`. (`Reservation` is not among them; it is a full entity carrying `updated_at` and `version`, both bumped when it is committed or released.) The recall notices a shop publishes, a customer's acknowledgement of one, and each captured payment are never edited in place; corrections happen by writing a new row (for example, voiding a payment). Every other entity in this system carries the full `id` / `created_at` / `updated_at` / `version` set.

### 2.5. Nested Reads and Left-to-Right Resolution

Several read endpoints are expressed as a parent path followed by a child collection — listing the reservations that draw on a given stock-keeping unit, the recall notices published against it, the bookings on a service bay, and so on. For any such path, the parent id is resolved first: if the stock-keeping unit, bay, or other named parent does not exist, the request fails with `ERR_NOT_FOUND` before any child filtering occurs. More generally, on every request each path id and each foreign key supplied in the body is checked, left to right, against the store of existing resources; the first that fails to resolve yields `ERR_NOT_FOUND`.

### 2.6. The Reservation Pool and Stock Reconciliation

The stock-keeping unit (`Sku`) is the single allocation pool of this system. Each `Sku` records `on_hand`, the count of physical units in stock, and exposes a computed `reserved` count and the implied availability, surfaced on the `Sku` resource as a computed `available` field. The `reserved` count is the sum of the `qty` of every `Reservation` row that points at this `Sku` and is currently in `ACTIVE` status; `Reservation` rows in `COMMITTED` or `RELEASED` status contribute nothing. The number of units available to promise — the `available` field — is `on_hand` minus `reserved`, and is not floored at zero. This reconciliation is recomputed on every reservation status change — when an `ACTIVE` reservation is created, when one moves from `ACTIVE` to `COMMITTED`, and when one moves from `ACTIVE` to `RELEASED` — and whenever a `Sku` is restocked. Stock and reservation accounting use whole integer units with no rounding.

The lifecycle of a reservation drives two distinct ledger movements. When a reservation is created, the held units leave the available pool by raising `reserved`. When a holder finally takes delivery of its goods, its reservations are committed: committing decreases both `on_hand` and `reserved` by the committed quantity in the same step, so the units physically leave the stockroom and simultaneously leave the active reserved set — availability is unchanged by a commit, because those units were never available to begin with. When a holder is cancelled or released before delivery, its reservations move to `RELEASED`, which lowers `reserved` and so raises availability again. Because every reservation row names its holder polymorphically through `holder_type` (one of `SALES_ORDER`, `BUILD_JOB`, `LAYAWAY_PLAN`, or `SPECIAL_ORDER`) and `holder_id`, a single `Sku` can be drawn down by all four kinds of holder at once, all competing over the same available count. Reservations are never created directly through their own endpoint; they come into being only as side effects of holder transitions, and they are read back through the reservation list and the per-`Sku` reservation listing.

### 2.7. Optimistic Concurrency on the Stock Pool

Two write operations consume stock the instant they are invoked, and both guard against acting on a stale view of the `Sku` they draw from. Reserving stock for a sales order requires the caller to submit `expected_sku_version` carrying the client's last observed `version` of the order's primary `Sku` — the `Sku` of the order's earliest-created order line. A missing or non-integer `expected_sku_version` is rejected with `ERR_INVALID_REQUEST`. If that value does not equal the `Sku`'s current `version` — because another holder (a build, a layaway, an earlier sales reserve, or a restock) has advanced it since the client last read it — the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412), since the writer's view of availability can no longer be trusted; on success the reserve increments that `Sku`'s `version`. Opening a layaway plan likewise requires `expected_sku_version` matching the target `Sku`'s current `version`; a layaway immediately reserves a unit, so an advanced version means the availability the client saw is stale and the open is refused with `ERR_STALE_VERSION` (HTTP 412). A successful open increments the `Sku`'s `version`. No other endpoint takes a version field; only the sales-order reserve and the layaway open carry optimistic-concurrency protection.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored as integer cents. Most calculations are purely integral and require no rounding — order subtotals, payment sums, store-credit application, and build fees are all exact integer arithmetic. Where a calculation multiplies by a basis-point rate it produces a fractional intermediate; in every such case the result is rounded half up to the nearest whole cent before any further step (minimum, maximum, or floor) is applied. The specific terms that round half up are the rush labor surcharge, the layaway restocking-fee percentage, the trade-in grade haircut, and the special-order deposit percentage; each is detailed with its workflow in §3. Turnaround quoting works in whole business hours, and the rush halving rounds the hour count up to the next whole hour, never down.

### 2.9. Cascades, Compensation, and Recall Safety

Many transitions in this system mutate more than the resource named in the request. A delivery commits reservations and decrements stock; a cancellation releases reservations, restores availability, and — when money has changed hands — reverses payments and restores consumed store credit; a warranty close resolves the underlying claim; a layaway forfeit both releases stock and credits a refund. Each such cascade is specified in full alongside its workflow in §3. In all cases, every entity touched by a cascade is independently mutated: its `updated_at` is refreshed and its `version` is incremented by one, including the parent or sibling entities reached across an aggregate boundary.

A product safety overlay sits across the allocation pool. When a stock-keeping unit is under an active `MANDATORY` recall, the shop must not promise or hand over more of it: reserving stock for a sales order, receiving a special order into stock, and opening a layaway plan are all blocked with `ERR_RECALL_BLOCK` while such a recall stands. Recalls of `ADVISORY` severity inform customers but do not block allocation. The recall overlay also feeds a per-customer awareness count described in §3.

## 3. Business Logic & Workflows

This section describes the operational workflows of the shop. Field names, thresholds, and side effects are introduced where they make business sense; a complete implementation requires reading across subsections.

### 3.1. Catalog, Customers, and Stock Intake

The catalog is built from stock-keeping units. A `Sku` carries a human-readable `name`, a `category` that is one of `BIKE`, `PART`, or `ACCESSORY`, and a `list_price_cents` that must be at least 1. It also carries `on_hand`, which defaults to 0 and may never be negative; a `warranty_class` of `NONE`, `COMPONENT`, or `FRAME_AND_COMPONENT` defaulting to `NONE`; and an `is_serialized` boolean defaulting to false that marks frame-numbered bikes. The computed `reserved` count and availability are reconciled as described in §2.6. Only a `ShopManager` creates stock-keeping units and only a `ShopManager` restocks: a restock supplies a count of `units` to add to `on_hand`, bumps the `Sku`'s `version`, and re-reconciles availability.

A `Customer` record carries a `full_name` and an `email`. The email must contain an `@` character and must be unique across all customers, compared case-insensitively; an attempt to create a customer whose email duplicates an existing one — ignoring letter case — is rejected with `ERR_DUPLICATE_EMAIL`. Two further customer fields are computed and never supplied on input: `store_credit_cents`, the running store-credit balance in cents that begins at 0, and `open_recall_count`, which also begins at 0. The store-credit balance is credited when a trade-in is accepted to credit and when certain refunds land, and it is debited when a sales order consumes it at delivery; its movements are described in the workflows that drive them.

A customer's `open_recall_count` is a derived awareness figure recomputed whenever the customer is read, whenever a recall notice is published, and whenever a recall acknowledgement is recorded. It is the number of distinct recall notices that match a stock-keeping unit the customer has actually taken delivery of and that the customer has not yet acknowledged. Concretely: gather the set of `sku_id` values appearing on order lines of this customer's sales orders that have reached `DELIVERED` fulfillment; then count the distinct recall notices whose `sku_id` is in that set and for which no acknowledgement by this customer exists. The count is a plain integer with no rounding.

### 3.2. Tune-Up Tiers and the Service Ticket Lifecycle

The service department prices labor against tune-up tiers. A `TuneUpTier` has a `code` that is one of `BASIC`, `STANDARD`, or `PREMIUM` and unique per code, a flat `base_labor_cents` of at least 0, a `turnaround_hours` quote of at least 1 business hour, and a `rush_multiplier_bps` rush surcharge in basis points that defaults to 5000 (that is, fifty percent) and must be at least 0.

A `ServiceAdvisor` opens a service ticket against a `customer_id` and a `tier_id`, optionally flagging `is_rush` and optionally supplying a `warranty_claim_id`. A new ticket begins in `INTAKE`. Its lifecycle field `status` ranges over `INTAKE`, `AWAITING_APPROVAL`, `IN_PROGRESS`, `READY_FOR_PICKUP`, `CLOSED`, and `CANCELLED`; the terminal states are `CLOSED` and `CANCELLED`. The ticket also carries computed fields: `promised_ready_at`, `labor_subtotal_cents` defaulting to 0, `revision_count` defaulting to 0, and `customer_owes_cents` defaulting to 0.

Quoting a ticket advances it from `INTAKE` to `AWAITING_APPROVAL`. This is permitted only from `INTAKE`, and the referenced tune-up tier must exist; quoting computes the labor subtotal, the amount the customer owes, and the promised ready time (see §3.3), and increments the ticket's `version`. From `AWAITING_APPROVAL`, the customer approves the quote, moving the ticket to `IN_PROGRESS`; approval is permitted only from `AWAITING_APPROVAL`, the acting `Customer` must own the ticket unless the ticket is a warranty execution with `warranty_claim_id` set, and it increments the `version`.

A ticket in progress can discover unforeseen work, which produces the system's revision loop. Adding a labor line to a ticket that is `IN_PROGRESS` marks that line as added after approval and cycles the ticket back to `AWAITING_APPROVAL` for re-approval; this is the `IN_PROGRESS → AWAITING_APPROVAL` transition, and it may repeat any number of times, with each loop tracked by `revision_count`. From `IN_PROGRESS`, the advisor instead marks the work complete, moving the ticket to `READY_FOR_PICKUP`; completion is permitted only from `IN_PROGRESS` and increments the `version`. At pickup, the advisor closes the ticket, moving it from `READY_FOR_PICKUP` to `CLOSED`, which increments the `version`. A ticket that has not yet started — that is, one whose `status` is either `INTAKE` or `AWAITING_APPROVAL` — may instead be cancelled to `CANCELLED`; cancellation increments the `version`. A transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

Closing a warranty ticket has a cross-entity consequence. If the ticket being closed has a `warranty_claim_id` set, that linked claim must be in `APPROVED_REPAIR` status at close time; otherwise the close is an invalid state for the claim. On a successful close of such a ticket, the linked warranty claim is transitioned from `APPROVED_REPAIR` to `RESOLVED` in the same operation — its `updated_at` is refreshed and its `version` is incremented — so the repair and its claim settle together.

### 3.3. Labor Lines, Quoting, and Rush Pricing

Labor on a ticket is itemized as labor lines. A `LaborLine` belongs to a ticket via `ticket_id`, names a labor menu entry by `menu_code` (for example a brake bleed or a wheel true), carries a `labor_cents` charge of at least 0, and has a computed `added_after_approval` flag defaulting to false. A line added while the ticket is still in `INTAKE` or `AWAITING_APPROVAL` leaves that flag false; a line added while the ticket is `IN_PROGRESS` sets it true, bumps the ticket's `revision_count`, and triggers the re-approval cycle described in §3.2. Warranty repairs are the exception to the cycle: when a ticket's `warranty_claim_id` is set, adding labor while in progress does not force a re-approval cycle, because warranty work is never billed to the customer.

The ticket quote is computed at the `INTAKE → AWAITING_APPROVAL` transition, on every labor-line addition, and on each revision loop back to `AWAITING_APPROVAL`. It begins from the tier's flat base labor. If the ticket is not flagged rush, the effective base is exactly `base_labor_cents`. If the ticket is rush, the effective base is `base_labor_cents` multiplied by the quantity (ten thousand plus the tier's `rush_multiplier_bps`) divided by ten thousand, with that product rounded half up to a whole cent — so a default rush multiplier of 5000 basis points yields one and a half times the base labor. The `labor_subtotal_cents` is then the effective base plus the sum of `labor_cents` over every labor line on the ticket, counting all lines regardless of their `added_after_approval` flag.

Turnaround feeds the promised ready time. The effective turnaround in hours equals the tier's `turnaround_hours` for a non-rush ticket; for a rush ticket it is `turnaround_hours` divided by two and rounded up to the next whole hour, so a five-hour tier rushed becomes three hours, not two. The `promised_ready_at` is the server's current UTC time plus that many hours. The amount the customer owes depends on whether the ticket is warranty work: when `warranty_claim_id` is set, `customer_owes_cents` is 0 even though `labor_subtotal_cents` is still computed in full; otherwise `customer_owes_cents` equals `labor_subtotal_cents`. The server's current UTC clock that anchors `promised_ready_at` can be set for test-driving by a `ShopManager` supplying a `to_iso8601` instant.

### 3.4. Service Bays and Booking Intervals

Repairs occupy physical bays. A `ServiceBay` has a `name` and an `is_active` flag defaulting to true; an inactive bay accepts no new bookings. A `BayBooking` ties a bay to a ticket: it carries `bay_id`, `ticket_id`, a `start_at`, an `end_at`, and a computed `status` of `BOOKED` or `RELEASED` defaulting to `BOOKED`.

Booking intervals are half-open, covering `start_at` inclusive up to `end_at` exclusive, and the `end_at` must be strictly after the `start_at`. A new booking is rejected with `ERR_BAY_DOUBLE_BOOKED` if its `end_at` is at or before its `start_at`, or if it overlaps any existing `BOOKED` interval on the same bay. Two intervals overlap exactly when the existing start is before the new end and the new start is before the existing end; because the intervals are half-open, a booking that starts precisely at an existing booking's `end_at` merely touches it with zero overlap and is therefore allowed. A `ServiceAdvisor` may release a booking, moving it from `BOOKED` to `RELEASED`, which frees the interval for re-booking and increments the booking's `version`.

### 3.5. Sales Orders: the Parallel Payment and Fulfillment Axes

A sales order tracks two independent axes at once. A `SalesOrder` is opened against a `customer_id` and starts with `payment_status` `UNPAID` and `fulfillment_status` `PENDING`. The payment axis ranges over `UNPAID`, `PARTIALLY_PAID`, `PAID`, and `REFUNDED`; the fulfillment axis ranges over `PENDING`, `RESERVED`, `DELIVERED`, and `CANCELLED`. These two axes advance largely on their own, and an order's terminal conditions are a delivered-and-paid order, a cancelled order whose money was refunded, and a cancelled order that was never paid. The order also carries computed totals: `subtotal_cents`, `store_credit_applied_cents`, `total_due_cents`, and `amount_paid_cents`, all defaulting to 0.

Lines are added to a pending order. An `OrderLine` names its parent `order_id`, the `sku_id` sold, and a `qty` of at least 1; at line creation the line's `unit_price_cents` is snapshotted from the `Sku`'s current `list_price_cents` and is immutable thereafter. Adding a line recomputes the order totals: `subtotal_cents` is the sum over the order's lines of `qty` times `unit_price_cents`. Before delivery, `store_credit_applied_cents` is 0, so `total_due_cents` equals `subtotal_cents`; `amount_paid_cents` is the sum of the amounts of this order's captured payments. The order is `PAID` when `amount_paid_cents` is greater than 0 and at least `total_due_cents`, `PARTIALLY_PAID` when `amount_paid_cents` is greater than 0 but below `total_due_cents`, and `UNPAID` otherwise.

Reserving the order advances fulfillment from `PENDING` to `RESERVED`. This is permitted only from `PENDING`, requires that the order have at least one order line, and requires that every line's `Sku` have enough availability; availability is evaluated over the summed quantity of all lines for the same `Sku` within the request, so two lines for the same product must be satisfiable together. Reserving carries `expected_sku_version` and is subject to the optimistic-concurrency check of §2.7, and is blocked by a `MANDATORY` recall on the `Sku` per §2.9. On success it creates one `ACTIVE` reservation per order line with `holder_type` `SALES_ORDER` and the order as `holder_id`, raises each `Sku`'s `reserved`, increments the primary `Sku`'s `version`, and increments the order's `version`. If availability is insufficient the reserve fails with `ERR_INSUFFICIENT_STOCK`.

Delivering the order advances fulfillment from `RESERVED` to `DELIVERED`. Delivery is permitted only from `RESERVED` and only when the order's `payment_status` is `PAID`; a delivery attempted on an order that is not fully paid is rejected with `ERR_NOT_FULLY_PAID`. The store-credit waterfall (§3.6) runs first, then each `ACTIVE` reservation of the order is committed (`ACTIVE → COMMITTED`), decrementing both `on_hand` and `reserved` for each `Sku`, after which the order totals are refreshed and the order's `version` is incremented. Cancelling the order takes fulfillment to `CANCELLED` and is permitted while fulfillment is `PENDING` or `RESERVED`. Cancellation releases each `ACTIVE` reservation of the order (`ACTIVE → RELEASED`), lowering each `Sku`'s `reserved`; and if the order's payment status was `PARTIALLY_PAID` or `PAID`, it sets `payment_status` to `REFUNDED`, voids all captured payments on the order, and restores any consumed store credit to the customer's `store_credit_cents` as compensation. The order's `version` is incremented.

### 3.6. Payments and Store Credit

Payments are captured against several kinds of target. A `Payment` names a `target_type` of `SALES_ORDER`, `LAYAWAY_PLAN`, or `SPECIAL_ORDER`, the polymorphic `target_id`, and an `amount_cents` of at least 1; its `status` is `CAPTURED` or `VOIDED` and defaults to `CAPTURED`. Capturing a payment recomputes its target's monetary fields — order totals for a sales order, accrued deposit for a layaway plan, paid deposit for a special order — and increments the target's `version`. A payment may not be captured against a target whose lifecycle no longer accepts payments: a sales order whose fulfillment is `CANCELLED` or `DELIVERED`, a layaway plan that is not `ACTIVE`, or a special order that is `FULFILLED` or `CANCELLED`. Such an attempt is rejected with `ERR_TARGET_NOT_PAYABLE`.

For a sales order, the payment axis advances as cumulative captured payments accumulate. A capture that leaves `amount_paid_cents` below `total_due_cents` puts the order at `PARTIALLY_PAID`; a capture that brings cumulative captured payments to at least `total_due_cents` marks the order `PAID`. Payment is only permitted while the order's fulfillment is not `CANCELLED` and the payment status is `UNPAID` or `PARTIALLY_PAID`.

Store credit is applied as a single waterfall bucket at the moment of delivery, before the fully-paid precondition is re-evaluated. The credit applied is the smaller of the customer's `store_credit_cents` and the order's `subtotal_cents`, and the order's `total_due_cents` becomes `subtotal_cents` minus that applied amount. The same applied amount is deducted from the customer's `store_credit_cents`. Because store credit can fully cover an order, `total_due_cents` may reach 0 — and a zero total counts as `PAID` only when `amount_paid_cents`, which is at least 0, is at least `total_due_cents`. All store-credit arithmetic is in whole cents with no rounding.

### 3.7. Layaway Plans

A layaway plan lets a customer pay off a single product over time while the shop holds a unit. A `LayawayPlan` names a `customer_id`, the `sku_id` being laid away, and a `qty` of at least 1 that defaults to 1. Opening a plan immediately reserves the units: it snapshots `price_cents` as the `Sku`'s `list_price_cents` times `qty` (immutable thereafter), creates one `ACTIVE` reservation with `holder_type` `LAYAWAY_PLAN`, raises the `Sku`'s `reserved`, and increments the `Sku`'s `version`. The open carries `expected_sku_version` and is subject to the optimistic-concurrency check of §2.7, requires sufficient availability (failing with `ERR_INSUFFICIENT_STOCK` otherwise), and is blocked by a `MANDATORY` recall per §2.9. The plan's `status` is one of `ACTIVE`, `FORFEITED`, `FULFILLED`, or `CANCELLED`, defaulting to `ACTIVE`; the terminal states are `FORFEITED`, `FULFILLED`, and `CANCELLED`. Two further computed fields, `deposit_cents` and `forfeit_fee_cents` and `refund_cents`, track the money: `deposit_cents` is the sum of captured payments attached to the plan, while `forfeit_fee_cents` and `refund_cents` default to 0 and are set only at settlement.

A `SalesAssociate` fulfills a fully-paid plan, taking it from `ACTIVE` to `FULFILLED`. Fulfillment is permitted only from `ACTIVE` and only when `deposit_cents` is at least `price_cents`; a fulfill attempted on a plan that is not fully paid off is rejected with `ERR_LAYAWAY_NOT_PAID_OFF`. Fulfillment commits the layaway reservation (`ACTIVE → COMMITTED`), decrementing the `Sku`'s `on_hand` and `reserved` by the plan's `qty`, and increments the plan's `version`.

Settlement of an abandoned or cancelled plan returns money through store credit. When a `ShopManager` forfeits an `ACTIVE` plan to `FORFEITED`, the layaway reservation is released (`ACTIVE → RELEASED`, lowering the `Sku`'s `reserved` by the plan's `qty`), a restocking fee is withheld, and the remainder is refunded to the customer's `store_credit_cents`. The fee in the forfeit case is the larger of a flat floor of 2000 cents and fifteen percent of `price_cents` — that is, `price_cents` times 1500 basis points divided by ten thousand, rounded half up to a whole cent — but never more than the accrued `deposit_cents`; that is, `forfeit_fee_cents` is the smaller of the accrued deposit and the larger of the floor and the percentage term. The `refund_cents` is then `deposit_cents` minus `forfeit_fee_cents`, and that refund is credited to the customer's `store_credit_cents`. When a `SalesAssociate` cancels an `ACTIVE` plan to `CANCELLED`, the reservation is likewise released and the `Sku`'s `reserved` lowered, but the cancel variant withholds nothing: `forfeit_fee_cents` is 0 and `refund_cents` is the full accrued `deposit_cents`, credited in full to the customer's `store_credit_cents`. Both settlement transitions increment the plan's `version`. All amounts are whole cents, with the percentage term rounded half up.

### 3.8. Special Orders

A special order procures a product the shop does not stock, possibly one with zero units on hand. A `SpecialOrder` names a `customer_id`, the `sku_id` to procure, and a `qty` of at least 1. At creation it computes `deposit_required_cents`, a non-refundable deposit demanded to confirm; it also tracks a computed `deposit_paid_cents` defaulting to 0 (the sum of captured payments against it). The `status` ranges over `QUOTED`, `CONFIRMED`, `ARRIVED`, `FULFILLED`, and `CANCELLED`, defaulting to `QUOTED`, with `FULFILLED` and `CANCELLED` terminal.

The required deposit is computed at creation from the line value, which is the `Sku`'s `list_price_cents` snapshotted at create multiplied by `qty`. The percentage term is thirty percent of the line value — the line value times 3000 basis points divided by ten thousand, rounded half up to a whole cent. The required deposit is then the smaller of the line value itself and the larger of a flat minimum of 5000 cents and that percentage term; in other words the deposit is at least 5000 cents (subject to the line-value cap), but never exceeds the line value.

Confirming a special order moves it from `QUOTED` to `CONFIRMED` and is permitted only from `QUOTED` and only when `deposit_paid_cents` is at least `deposit_required_cents`; a confirm with too little deposit is rejected with `ERR_DEPOSIT_SHORT`. Receiving goods moves the order from `CONFIRMED` to `ARRIVED`: it increases the `Sku`'s `on_hand` by the order's `qty`, creates one `ACTIVE` reservation with `holder_type` `SPECIAL_ORDER`, raises the `Sku`'s `reserved` by `qty`, and increments the order's `version`; receiving is blocked by a `MANDATORY` recall on the `Sku` per §2.9. Fulfilling moves the order from `ARRIVED` to `FULFILLED`, committing the special-order reservation (`ACTIVE → COMMITTED`) and decrementing both `on_hand` and `reserved` by `qty`. Cancelling is permitted while the order is `QUOTED` or `CONFIRMED` and takes it to `CANCELLED`: if a reservation exists it is released and the `Sku`'s `reserved` decreased, and the deposit handling differs by stage — a deposit paid on a still-`QUOTED` order is refunded by voiding its payments, whereas once the order is `CONFIRMED` the deposit is non-refundable and is not returned. Every special-order transition increments the order's `version`.

### 3.9. Custom Builds Gated on Parts Readiness

A custom build assembles a bicycle from a frame and a set of parts, and may not begin until every required part is reserved. A `BuildJob` names a `customer_id`, a `frame_sku_id`, and a `required_part_count` of at least 1; the frame's `Sku` must be of `category` `BIKE`, and a build whose frame is not a bike is rejected at creation with `ERR_FRAME_NOT_BIKE`. The job carries a computed `reserved_part_count` defaulting to 0, a computed `build_fee_cents` defaulting to 0, and a `status` of `DRAFT`, `PARTS_RESERVED`, `ASSEMBLING`, `COMPLETED`, or `CANCELLED` defaulting to `DRAFT`, with `COMPLETED` and `CANCELLED` terminal.

While the job is in `DRAFT`, the advisor reserves parts and the frame against it. Reserving a part supplies a `sku_id` and an optional `qty`, creating one `ACTIVE` reservation with `holder_type` `BUILD_JOB`, raising that `Sku`'s `reserved`, incrementing that `Sku`'s `version`, and raising the build's `reserved_part_count`; the `reserved_part_count` is the count of `ACTIVE` reservations with `holder_type` `BUILD_JOB` pointing at this build. Reserving the frame creates a `BUILD_JOB` reservation of quantity 1 for the `frame_sku_id` in the same fashion, raising the frame `Sku`'s `reserved` and bumping its `version`. Both reservation actions increment the build's `version`. Unlike the sales-order, layaway, and special-order allocations, neither part nor frame reservation is gated on availability or on a `MANDATORY` recall: each simply creates its `ACTIVE` reservation, so a part or frame `Sku` may be drawn into a build even when its computed `available` is zero or negative.

The build advances from `DRAFT` to `PARTS_RESERVED` only when readiness is met: `reserved_part_count` must be at least `required_part_count` and the frame's reservation for this build must be `ACTIVE`. A mark-parts-reserved attempt that fails either condition is rejected with `ERR_BUILD_NOT_READY`. From `PARTS_RESERVED` the advisor starts assembly, moving the job to `ASSEMBLING`; starting computes the assembly fee (below) and increments the `version`. From `ASSEMBLING` the advisor completes the build to `COMPLETED`, which commits every `ACTIVE` reservation of the build — the frame and all parts — moving each to `COMMITTED` and decrementing each `Sku`'s `on_hand` and `reserved` by the committed quantity. A build may be cancelled from `DRAFT`, `PARTS_RESERVED`, or `ASSEMBLING` to `CANCELLED`, which releases every `ACTIVE` reservation of the build (`ACTIVE → RELEASED`) and lowers each `Sku`'s `reserved` as compensation. Every build transition increments the build's `version`.

The assembly fee is computed when assembly starts, marginally tiered on the build's `required_part_count`. It begins with a flat base of 5000 cents. The first up to five parts are charged at 1200 cents each; parts six through ten are charged at 900 cents each; every part beyond the tenth is charged at 600 cents each. The bands are marginal, not average: each band's rate applies only to the parts that fall within it. So the fee is the base, plus the smaller of the count and five multiplied by 1200 cents, plus — when the count exceeds five — the quantity (the smaller of the count and ten, minus five) multiplied by 900 cents, plus — when the count exceeds ten — the count minus ten multiplied by 600 cents. All terms are integral, so no rounding is needed.

### 3.10. Warranty Claims: Repair, Replace, or Deny

A warranty claim adjudicates a defect against a delivered purchase. A `WarrantyClaim` names a `customer_id`, the defective product's `sku_id`, the `source_order_line_id` that establishes ownership, and a `defect_part` of either `FRAME` or `COMPONENT`. Its `status` ranges over `SUBMITTED`, `UNDER_REVIEW`, `APPROVED_REPAIR`, `APPROVED_REPLACE`, `DENIED`, and `RESOLVED`, defaulting to `SUBMITTED`, with `DENIED` and `RESOLVED` terminal. A claim approved for replacement also carries a `resolution_sku_id` naming the replacement product.

A claim may be submitted by a `ServiceAdvisor` or by the `Customer`. At submission and again at approval, the system verifies purchase: the `source_order_line_id` must belong to a sales order whose fulfillment is `DELIVERED` and whose `customer_id` equals the claim's `customer_id`; a claim that fails this referential check is rejected with `ERR_NOT_PURCHASED`. A `ServiceAdvisor` moves the claim from `SUBMITTED` to `UNDER_REVIEW` for review, incrementing its `version`.

From `UNDER_REVIEW` the claim forks three ways, all driven by the service advisor. The first branch approves a repair, supplying a `resolution` of `REPAIR` and moving the claim to `APPROVED_REPAIR`. This requires the claim to be `UNDER_REVIEW`, the purchase check to pass, and warranty coverage to hold: when `defect_part` is `FRAME`, the source `Sku` must have `warranty_class` of `FRAME_AND_COMPONENT` and `is_serialized` true; when `defect_part` is `COMPONENT`, the source `Sku` must have `warranty_class` of either `COMPONENT` or `FRAME_AND_COMPONENT`. A coverage failure is rejected with `ERR_WARRANTY_NOT_COVERED`. An approved repair is later executed by a follow-on service ticket carrying this claim's `warranty_claim_id` at zero customer cost; when that ticket reaches `CLOSED`, the claim moves from `APPROVED_REPAIR` to `RESOLVED` automatically as described in §3.2.

The second branch approves a replacement, supplying a `resolution` of `REPLACE` and a `resolution_sku_id`, and moving the claim to `APPROVED_REPLACE`. This requires the claim to be `UNDER_REVIEW`, the purchase check to pass, and the replacement `Sku` to have at least one available unit; if the replacement `Sku` has insufficient availability the approval fails with `ERR_INSUFFICIENT_STOCK`. The same coverage rule applies as for repair. On success it pulls the replacement from stock by creating one `ACTIVE` reservation of quantity 1 against the resolution `Sku` (held under `holder_type` `SALES_ORDER` for the source order), raising that `Sku`'s `reserved` and incrementing its `version`. The replacement is later finalized by resolving the claim, moving it from `APPROVED_REPLACE` to `RESOLVED`: resolving commits that replacement reservation (`ACTIVE → COMMITTED`), decrementing the resolution `Sku`'s `on_hand` and `reserved` by 1. The third branch denies the claim, supplying no further input and moving it from `UNDER_REVIEW` to `DENIED`; denial is terminal and carries no stock or ticket side effects. Each of the three branch transitions, and the resolve, increments the claim's `version`.

### 3.11. Trade-Ins, Recalls, and Acknowledgements

A trade-in turns a used bicycle into store credit or cash. A `TradeIn` names a `customer_id`, a free-text `description`, a `condition_grade` of `A`, `B`, or `C`, an `appraised_value_cents` of at least 0 set at intake, and an `apply_to` of `STORE_CREDIT` or `CASH` defaulting to `STORE_CREDIT`. It carries a computed `offer_cents` defaulting to 0 and a `status` of `APPRAISED`, `ACCEPTED`, or `REJECTED`, defaulting to `APPRAISED`, with `ACCEPTED` and `REJECTED` terminal. A `ShopManager` accepts or rejects an appraised trade-in. Accepting moves it from `APPRAISED` to `ACCEPTED` and computes the offer; rejecting moves it from `APPRAISED` to `REJECTED` with no further effect. Both increment the trade-in's `version`.

The offer applies a grade-dependent haircut to the appraised value, then a flat handling deduction, floored at zero. The haircut rate is 8500 basis points for grade `A`, 7000 basis points for grade `B`, and 5000 basis points for grade `C`. The value after haircut is `appraised_value_cents` multiplied by that rate divided by ten thousand, rounded half up to a whole cent. The `offer_cents` is then that after-haircut value minus a flat handling deduction of 1500 cents, but never below zero. On acceptance, if `apply_to` is `STORE_CREDIT`, the `offer_cents` is credited to the customer's `store_credit_cents`; a `CASH` payout makes no store-credit movement.

Recalls protect customers from defective products. A `RecallNotice` names the recalled `sku_id`, a `severity` of `ADVISORY` or `MANDATORY`, and free-text `remedy` instructions; only a `ShopManager` publishes one, and publishing recomputes the affected customers' open-recall awareness counts. A `MANDATORY` notice additionally blocks new allocation of the `Sku` as described in §2.9. A `RecallAck` records that a customer has acknowledged a notice, naming the `recall_id` and the acknowledging `customer_id`; it may be created by a `Customer`, a `ServiceAdvisor`, or a `ShopManager`. A customer may acknowledge a given notice at most once; a duplicate acknowledgement is rejected with `ERR_ALREADY_ACKNOWLEDGED`. Recording an acknowledgement recomputes that customer's `open_recall_count`.

### 3.12. Ordering of Validation Checks

Because several checks can apply to a single request, the system evaluates them in a fixed priority order, and the first failure determines the error returned. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED`, then role authorization yields `ERR_FORBIDDEN_ROLE`, then — for a customer acting on their own ticket — ownership yields `ERR_NOT_RESOURCE_OWNER`. Existence comes next: any unresolved path id or body foreign key, checked left to right, yields `ERR_NOT_FOUND`. Then state is checked: a transition not defined from the resource's current state yields `ERR_INVALID_STATE`. Then request shape: missing or ill-typed fields, enum values outside their declared domain, integers outside their declared ranges, and a malformed email all yield `ERR_INVALID_REQUEST`.

After those structural checks come the business rules, each guarding its own operations. Customer email uniqueness on create yields `ERR_DUPLICATE_EMAIL`. The warranty purchase check yields `ERR_NOT_PURCHASED`, and warranty coverage yields `ERR_WARRANTY_NOT_COVERED`. A build whose frame is not a bike yields `ERR_FRAME_NOT_BIKE`, and a build advanced before readiness yields `ERR_BUILD_NOT_READY`. A mandatory recall blocking allocation yields `ERR_RECALL_BLOCK`, evaluated before the availability check; insufficient availability yields `ERR_INSUFFICIENT_STOCK`. The fiscal gates follow: delivering an unpaid order yields `ERR_NOT_FULLY_PAID`, confirming a special order with too small a deposit yields `ERR_DEPOSIT_SHORT`, and fulfilling an unpaid-off layaway yields `ERR_LAYAWAY_NOT_PAID_OFF`. The optimistic-concurrency check on the stock version yields `ERR_STALE_VERSION`. Paying a target that no longer accepts payments yields `ERR_TARGET_NOT_PAYABLE`, a duplicate recall acknowledgement yields `ERR_ALREADY_ACKNOWLEDGED`, and an overlapping bay booking yields `ERR_BAY_DOUBLE_BOOKED`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/shop` prefix, with the sole exception of the test-driving clock endpoint, which is mounted at `/_clock/set_current_utc` (no `/shop` prefix). Endpoints that create a new resource return HTTP 201; endpoints that read a resource or perform a state transition or other modification return HTTP 200. Request bodies, response bodies, and side effects are not repeated here — they are specified in the §3 workflow narratives. The table lists only the method, path, purpose, and the roles permitted to invoke each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /shop/customers | Create a customer. | SalesAssociate, ShopManager |
| GET | /shop/customers/{id} | Read a customer, including store credit and open recall count. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/customers | List customers. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/skus | Create a stock-keeping unit. | ShopManager |
| GET | /shop/skus/{id} | Read a stock-keeping unit, including reserved units. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/skus | List stock-keeping units, filterable by category. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| POST | /shop/skus/{id}/restock | Add units to on-hand stock. | ShopManager |
| GET | /shop/skus/{id}/reservations | List reservations drawing on this stock-keeping unit. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/skus/{id}/recalls | List recall notices on this stock-keeping unit. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| POST | /shop/tune-up-tiers | Create a tune-up tier. | ShopManager |
| GET | /shop/tune-up-tiers/{id} | Read a tune-up tier. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/tune-up-tiers | List tune-up tiers. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| POST | /shop/service-tickets | Open a service ticket. | ServiceAdvisor |
| GET | /shop/service-tickets/{id} | Read a service ticket. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/service-tickets | List service tickets. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/service-tickets/{id}/quote | Quote a ticket; computes labor and promised ready time. | ServiceAdvisor |
| POST | /shop/service-tickets/{id}/approve | Customer approves the quote. | Customer |
| POST | /shop/service-tickets/{id}/complete | Mark work complete. | ServiceAdvisor |
| POST | /shop/service-tickets/{id}/close | Close at pickup; resolves a linked repair claim. | ServiceAdvisor |
| POST | /shop/service-tickets/{id}/cancel | Cancel a non-started ticket. | ServiceAdvisor |
| POST | /shop/labor-lines | Add a labor line to a ticket. | ServiceAdvisor |
| GET | /shop/labor-lines/{id} | Read a labor line. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/labor-lines | List labor lines. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/service-bays | Create a service bay. | ShopManager |
| GET | /shop/service-bays/{id} | Read a service bay. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/service-bays | List service bays. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/service-bays/{id}/bookings | List bookings on a bay. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/bay-bookings | Book a bay for a ticket over a half-open interval. | ServiceAdvisor |
| GET | /shop/bay-bookings/{id} | Read a bay booking. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/bay-bookings | List bay bookings. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/bay-bookings/{id}/release | Release a booking. | ServiceAdvisor |
| POST | /shop/sales-orders | Create an empty sales order. | SalesAssociate, ShopManager |
| GET | /shop/sales-orders/{id} | Read a sales order with both status axes and totals. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/sales-orders | List sales orders. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/sales-orders/{id}/reserve | Reserve stock for all lines. | SalesAssociate, ShopManager |
| POST | /shop/sales-orders/{id}/deliver | Deliver the order; applies store credit, requires paid. | SalesAssociate, ShopManager |
| POST | /shop/sales-orders/{id}/cancel | Cancel the order; releases reservations and refunds. | SalesAssociate, ShopManager |
| POST | /shop/order-lines | Add a line to a pending sales order. | SalesAssociate, ShopManager |
| GET | /shop/order-lines/{id} | Read an order line. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/order-lines | List order lines. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/reservations/{id} | Read a reservation. | SalesAssociate, ServiceAdvisor, ShopManager |
| GET | /shop/reservations | List reservations, filterable by stock-keeping unit and holder. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/layaway-plans | Open a layaway plan; reserves units immediately. | SalesAssociate, ShopManager |
| GET | /shop/layaway-plans/{id} | Read a layaway plan. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/layaway-plans | List layaway plans. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/layaway-plans/{id}/fulfill | Fulfill a fully-paid plan; commits the reservation. | SalesAssociate, ShopManager |
| POST | /shop/layaway-plans/{id}/forfeit | Forfeit a plan; withholds fee, credits refund. | ShopManager |
| POST | /shop/layaway-plans/{id}/cancel | Cancel a plan; full deposit refunded to store credit. | SalesAssociate, ShopManager |
| POST | /shop/special-orders | Create a special order; computes required deposit. | SalesAssociate, ShopManager |
| GET | /shop/special-orders/{id} | Read a special order. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/special-orders | List special orders. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/special-orders/{id}/confirm | Confirm a deposited order. | SalesAssociate, ShopManager |
| POST | /shop/special-orders/{id}/receive | Receive goods into stock; restocks and reserves. | SalesAssociate, ShopManager |
| POST | /shop/special-orders/{id}/fulfill | Hand over goods; commits the reservation. | SalesAssociate, ShopManager |
| POST | /shop/special-orders/{id}/cancel | Cancel a special order. | SalesAssociate, ShopManager |
| POST | /shop/build-jobs | Create a build job on a bike frame. | ServiceAdvisor |
| GET | /shop/build-jobs/{id} | Read a build job, including reserved part count. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/build-jobs | List build jobs. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/build-jobs/{id}/reserve-part | Reserve one part for a draft build. | ServiceAdvisor |
| POST | /shop/build-jobs/{id}/reserve-frame | Reserve the frame for a draft build. | ServiceAdvisor |
| POST | /shop/build-jobs/{id}/mark-parts-reserved | Advance the build once readiness is met. | ServiceAdvisor |
| POST | /shop/build-jobs/{id}/start | Begin assembly; computes the build fee. | ServiceAdvisor |
| POST | /shop/build-jobs/{id}/complete | Finish the build; commits all reservations. | ServiceAdvisor |
| POST | /shop/build-jobs/{id}/cancel | Cancel the build; releases reservations. | ServiceAdvisor |
| POST | /shop/warranty-claims | Submit a warranty claim. | ServiceAdvisor, Customer |
| GET | /shop/warranty-claims/{id} | Read a warranty claim. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/warranty-claims | List warranty claims. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/warranty-claims/{id}/review | Begin review. | ServiceAdvisor |
| POST | /shop/warranty-claims/{id}/approve | Approve as repair or replace. | ServiceAdvisor |
| POST | /shop/warranty-claims/{id}/deny | Deny a claim. | ServiceAdvisor |
| POST | /shop/warranty-claims/{id}/resolve | Resolve a replacement claim; commits the reservation. | ServiceAdvisor |
| POST | /shop/trade-ins | Record a trade-in appraisal. | SalesAssociate, ShopManager |
| GET | /shop/trade-ins/{id} | Read a trade-in. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/trade-ins | List trade-ins. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/trade-ins/{id}/accept | Accept the trade-in; computes offer, credits store credit. | ShopManager |
| POST | /shop/trade-ins/{id}/reject | Reject the trade-in. | ShopManager |
| POST | /shop/payments | Capture a payment against an order, plan, or special order. | SalesAssociate, ShopManager |
| GET | /shop/payments | List payments. | SalesAssociate, ServiceAdvisor, ShopManager |
| POST | /shop/recall-notices | Publish a recall notice on a stock-keeping unit. | ShopManager |
| GET | /shop/recall-notices/{id} | Read a recall notice. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/recall-notices | List recall notices. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| POST | /shop/recall-acks | Acknowledge a recall notice. | Customer, ServiceAdvisor, ShopManager |
| GET | /shop/recall-acks/{id} | Read a recall acknowledgement. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| GET | /shop/recall-acks | List recall acknowledgements. | SalesAssociate, ServiceAdvisor, ShopManager, Customer |
| POST | /_clock/set_current_utc | Set the server's current UTC clock for test-driving. | ShopManager |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives, not here. This table maps each error identifier to its HTTP status code.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_NOT_PURCHASED | 409 |
| ERR_WARRANTY_NOT_COVERED | 409 |
| ERR_FRAME_NOT_BIKE | 409 |
| ERR_BUILD_NOT_READY | 409 |
| ERR_RECALL_BLOCK | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_NOT_FULLY_PAID | 409 |
| ERR_DEPOSIT_SHORT | 409 |
| ERR_LAYAWAY_NOT_PAID_OFF | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TARGET_NOT_PAYABLE | 409 |
| ERR_ALREADY_ACKNOWLEDGED | 409 |
| ERR_BAY_DOUBLE_BOOKED | 409 |
| ERR_INVALID_PAGINATION | 400 |
