# Stationery & Custom-Invitation Shop API — Product Requirements Document

## 1. Introduction

A boutique stationery shop needs an API to orchestrate the end-to-end workflow of custom-invitation orders — from a customer choosing a paper stock and finish, through a designer producing proofs, through deposit collection and pressroom scheduling, through addressing add-ons, and finally through shipping and delivery. Each of these stages has its own cadence: catalog managers change paper prices out of band, designers may resubmit a proof several times before the customer signs off, and cancellations can arrive at almost any point in the pipeline. The system must keep prices, deposits, paper reservations, and store credit reconciled through all of it.

The API is also the shop's mechanism for reorders, rush jobs, and multi-event packages (weddings, announcements, and other custom occasions). Because a reorder replays a prior delivered order at its captured prices, and because rush pricing depends on how far the ship-by deadline is from today, the system must reason about the customer's history and its own logical clock, not just the current row. The document below defines the entities, workflows, endpoints, and error contracts that govern this end-to-end system.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and boilerplate that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

All requests must carry two mandatory headers: `X-User-ID` identifies the acting principal, and `X-User-Role` names their operational capacity. The system recognises three roles: `Customer`, `Designer`, and `ShopAdmin`. A request that omits either header, or supplies an unrecognised value in `X-User-Role`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorised for the target endpoint — or whose entity-backed identity does not match the acting resource's owner — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` foreign key to `X-User-ID`. In particular, a `Customer` may only act on a `Design` whose `customer_id` equals `X-User-ID`, on an `Order` whose `customer_id` equals `X-User-ID`, and on a `Proof` whose parent `Design.customer_id` equals `X-User-ID`.

When `X-User-Role` is `Designer`, `X-User-ID` is the `id` of the acting `Designer`; ownership checks on any resource that references a `Designer` compare the resource's `designer_id` foreign key to `X-User-ID`. In particular, a `Designer` may only submit a `Proof` whose `designer_id` equals `X-User-ID`, and creating the initial proof for a `Design` binds the `Design`'s `designer_id` to `X-User-ID` on the spot.

When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in audit trails but does not compare it to any entity's `id`; `ShopAdmin` has unrestricted access to the operations listed for that role and is not scoped by any owner check.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All top-level resources — `Customer`, `Designer`, `PaperStock`, `FinishOption`, `EventPackage`, `Design`, `Proof`, `Order`, `LineItem`, `AddressingJob`, `WorkOrder`, and `Shipment` — carry a shared set of system-managed fields:

- **`id`** is a unique, server-minted UUID with no type prefix.
- **`created_at`** is an ISO 8601 UTC timestamp with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) recorded when the resource is first created.
- **`updated_at`** is an ISO 8601 UTC timestamp with three fractional digits updated on every mutation — including mutations to derived fields such as `subtotal_cents`, `total_cents`, `reserved_units`, `deposit_paid_cents`, `revision_fee_cents`, `expires_at`, and `expected_lead_days`.
- **`version`** is a system-managed integer that starts at 1 and is incremented by one on every mutation of that resource. It is used for optimistic concurrency control (see §2.7).

Server-minted computed fields on the individual resources — for example `Proof.expires_at`, `Order.subtotal_cents`, `Shipment.tracking_number`, `AddressingJob.status`, `WorkOrder.production_status`, and `WorkOrder.addressing_status` — are populated by the server and are read-only for clients.

### 2.5. Nested Resource Retrieval

Endpoint paths that carry multiple identifiers (for example a line item nested under an order, or a proof listed under a design) are validated left-to-right. When any identifier in the path does not correspond to an existing resource, the server rejects the request with the corresponding 404 error before evaluating deeper checks: `ERR_CUSTOMER_NOT_FOUND`, `ERR_DESIGNER_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_ADDRESSING_JOB_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PAPER_STOCK_NOT_FOUND`, `ERR_FINISH_OPTION_NOT_FOUND`, or `ERR_EVENT_PACKAGE_NOT_FOUND`. A malformed body, missing required key, invalid enum value, or type mismatch on any of the input fields is rejected before further business rules run, with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Monetary Amounts, Days, and Precision

All monetary values on `Order`, `LineItem`, `Proof`, and `AddressingJob` are stored and transported as integer cents (there are no fractional cents on the wire). Where a monetary calculation involves a percentage or a non-integer multiplier — the reorder discount, the rush surcharge, the deposit fraction, and the per-line tier-multiplier product — the intermediate calculation is performed with exact decimal arithmetic and the final result is rounded to two decimal places (equivalently, to a whole number of cents) using the standard "round half up" method.

Lead-time calculations produce whole days: `PaperStock.lead_days`, `FinishOption.additional_lead_days`, and the computed `Order.expected_lead_days` are all integers, and the addressing/rush adjustments described in §3 are integer arithmetic.

Timestamps such as `submitted_at`, `approved_at`, and `expires_at` on `Proof`, `deposit_paid_at` on `Order`, and `dispatched_at` and `delivered_at` on `Shipment` are stored in UTC. `AddressingJob.scheduled_date` is an ISO 8601 calendar date in `YYYY-MM-DD` form (no time component). The `EventPackage.deposit_pct` field is a decimal fraction strictly greater than zero and at most one — that is, in the half-open range `(0.0, 1.0]`.

### 2.7. Optimistic Concurrency Control

Adding a `LineItem` to a `CART` order is the only endpoint in the system that requires optimistic concurrency control. The request body of the add-line-item operation must carry an `expected_order_version` field alongside the pricing fields; the value is the client's last observed `Order.version`. If, at the moment the server evaluates the request, `expected_order_version` does not equal the current `Order.version` — because another writer has since added, removed, or repriced a line on the same order and therefore advanced `Order.version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection is expressed purely in terms of a stale-version check: the client re-reads the order to see the fresh `version` and retries. No other write endpoint in the system takes a version field; all other mutations succeed without an OCC check.

Both a successful add-line-item and a successful delete-line-item on an order increment `Order.version` by exactly one.

### 2.8. Catalog Lifecycle and Paper Reservations

Every `PaperStock` and every `FinishOption` carries a `status` of either `ACTIVE` or `DISCONTINUED`; both default to `ACTIVE` at creation. An `EventPackage` similarly carries `status` `ACTIVE` or `DISCONTINUED`. Discontinuing a paper stock does not disturb any order that is already running; new line items on a new order may not select the stock unless the order is a valid reorder of a prior delivered order that already used the same stock. The same rule holds for finish options.

Each `PaperStock` exposes an aggregated read-only `reserved_units` field. This field is the sum of `LineItem.quantity` across every line whose parent `Order` is currently in `DEPOSIT_PENDING`, `IN_PRODUCTION`, or `READY_TO_SHIP`. Orders in `CART` do not reserve — a customer that has not confirmed has not committed to production. Orders that have `SHIPPED` or been `DELIVERED`, and orders that have been `CANCELLED`, release their reservation. The system maintains this invariant on every add, delete, confirm, cancel, ship, and deliver operation.

### 2.9. Store Credit and Cash Conservation

For every customer, the system tracks a running total of deposit cash they have funded — `Customer.cumulative_deposits_paid_cents` — and their current shop store-credit balance — `Customer.credit_balance_cents`. Both fields default to zero when a customer is created. The `cumulative_deposits_paid_cents` field is monotonically non-decreasing: it is bumped every time a deposit payment succeeds and is never decremented, even when a subsequent cancellation refunds the money.

The cash conservation invariant is that, for a fixed value of `cumulative_deposits_paid_cents`, the sum of `credit_balance_cents` plus the `deposit_paid_cents` across all of the customer's orders whose status is `DEPOSIT_PENDING`, `IN_PRODUCTION`, `READY_TO_SHIP`, `SHIPPED`, or `DELIVERED` must remain unchanged over time. The two operations that touch this invariant — deposit payment and cancellation refund — are designed so that money moves rather than appears or disappears: cancelling a `DEPOSIT_PENDING` order with paid deposit shifts the entire `deposit_paid_cents` amount into `credit_balance_cents` and resets `Order.deposit_paid_cents` to zero, so the two changes cancel out in the sum above.

Forfeiture is the deliberate exception: when a `ShopAdmin` cancels an order that has already advanced past `DEPOSIT_PENDING` (that is, an `IN_PRODUCTION` cancellation), the deposit is not returned as store credit — `Order.deposit_paid_cents` is retained on the (now `CANCELLED`) order. Because a `CANCELLED` order is outside the invariant's set of eligible statuses, the customer ledger is left short by the forfeited amount — this is the intended accounting outcome of a mid-production cancellation.

### 2.10. Cascades and Auto-Transitions

The order, proof, work-order, and shipment lifecycles are tightly coupled, and the server drives several transitions on its own rather than waiting for a client request:

- Confirming an order creates a fresh `Proof` (with `status` `DRAFT` and `current_revision_number` of zero, and `designer_id` left unset), advances `Design.status` to `PROOFING`, snapshots `Order.event_package_id` from the `Design`, and, for each `LineItem`, adds `LineItem.quantity` to the referenced `PaperStock.reserved_units`.
- Approving a proof sets `Proof.approved_at` to the current UTC instant, transitions `Design.status` to `APPROVED`, and — if `Order.deposit_paid_at` is already set at that moment — cascades the parent order from `DEPOSIT_PENDING` to `IN_PRODUCTION` and spawns a `WorkOrder` (with `production_status` of `NOT_STARTED`, and `addressing_status` of either `NOT_APPLICABLE` when the order has no addressing jobs or `PENDING` when it has at least one).
- Recording the last cent of the deposit sets `Order.deposit_paid_at` to the current UTC instant, increments `Customer.cumulative_deposits_paid_cents` by the deposit amount, and — if `Proof.status` is already `APPROVED` at that moment — cascades the parent order from `DEPOSIT_PENDING` to `IN_PRODUCTION` and spawns the same `WorkOrder`.
- A `WorkOrder` completing its `production_status` while `addressing_status` is `NOT_APPLICABLE` or `COMPLETED`, or completing its `addressing_status` while `production_status` is `COMPLETED`, cascades the parent order from `IN_PRODUCTION` to `READY_TO_SHIP` and spawns a `Shipment` with `status` `PREPARING` and a server-minted `tracking_number`.
- Dispatching a shipment transitions the parent order to `SHIPPED` and records `Shipment.dispatched_at`; marking a shipment as delivered transitions the parent order to `DELIVERED`, records `Shipment.delivered_at`, moves `Design.status` to `ARCHIVED`, and releases each `LineItem.quantity` from the corresponding `PaperStock.reserved_units`.
- An expired proof (the current UTC time has advanced past `Proof.expires_at`) cascades the parent order to `CANCELLED` and moves `Design.status` to `ARCHIVED`.
- Cancelling the parent order propagates to its `Proof` (if non-terminal, moved to `CANCELLED`), its `WorkOrder` (if one exists, cancelled), its `Shipment` (moved to `CANCELLED` if still `PREPARING`), and its `AddressingJob` set (each moved to `CANCELLED`).

Each of these mutations updates `updated_at` and bumps `version` on the specific resource being changed.

### 2.11. Validation Priority

When several failures could apply to the same request, the server evaluates them in a fixed order and returns the first failure it finds. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (the family of `..._NOT_FOUND` errors, including `ERR_CUSTOMER_NOT_FOUND`, `ERR_DESIGNER_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PAPER_STOCK_NOT_FOUND`, `ERR_FINISH_OPTION_NOT_FOUND`, and `ERR_EVENT_PACKAGE_NOT_FOUND`).

State-machine preconditions are evaluated next as a single band. Within that band, `ERR_STALE_VERSION` (the OCC check on add-line-item) surfaces alongside `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_PROOF_EXPIRED`, `ERR_PROOF_NOT_APPROVED`, `ERR_ORDER_NOT_CANCELLABLE`, `ERR_RUSH_TOO_LATE`, and `ERR_DEPOSIT_NOT_PAID`. Business-safety checks that guard catalog integrity — `ERR_PAPER_DISCONTINUED` and `ERR_FINISH_DISCONTINUED` — are evaluated after state preconditions. Business-constraint checks come after that, covering quantity minimums (`ERR_QUANTITY_BELOW_MIN`), quantity validity (`ERR_QUANTITY_INVALID`), press-slot overlap (`ERR_PRESS_SLOT_OVERLAP`), addressing capacity (`ERR_ADDRESSING_CAPACITY_EXCEEDED`), and — last — reorder eligibility (`ERR_REORDER_WINDOW_EXPIRED`) and rush feasibility (`ERR_RUSH_INFEASIBLE`). A malformed body surfacing `ERR_INVALID_REQUEST` short-circuits everything else.

## 3. Business Logic & Workflows

### 3.1. Catalog: Paper, Finish, Event Packages, and Designers

Before workflow entities are introduced, the shop authors its catalog. A `Customer` record is registered by a `ShopAdmin` with the customer's contact `email` (which must be unique), `full_name`, and `phone`; the newly created customer begins with `credit_balance_cents` of zero and `cumulative_deposits_paid_cents` of zero.

The shop's catalog itself is authored by `ShopAdmin` staff. A paper stock is defined by a human-readable `name` (e.g., "Ivory Cotton 220gsm"), a per-unit `base_price_cents` that must be strictly greater than zero, a `lead_days` count of business days needed to source it, and a lifecycle `status`. A finish option is defined by a `name` (e.g., "Gold Foil"), a per-unit `surcharge_cents` that must be at least zero, and an `additional_lead_days` count of extra business days that must be at least zero. Both `PaperStock.status` and `FinishOption.status` default to `ACTIVE` at creation and may be flipped later; flipping a paper stock to `DISCONTINUED` is a first-class capability described later in this section.

An `EventPackage` is the sales unit for a particular kind of stationery job. It carries a `name`, a `package_type` drawn from `WEDDING`, `ANNOUNCEMENT`, or `CUSTOM`, a `deposit_pct` that governs how much of the discounted subtotal is held as deposit, a `min_qty` (at least one) that constrains every line item of any order derived from a design against this package, and a `proof_expiry_days` (at least one) that governs how long a submitted proof remains valid before the system auto-cancels it. A package likewise carries a `status` of `ACTIVE` or `DISCONTINUED`.

Designers are staff members. Each `Designer` has a `full_name` and an `active` flag that defaults to true; the flag records whether the designer is currently accepting new proof work. Listing designers accepts an `active` filter alongside the standard `limit` and `offset` pagination.

A `ShopAdmin` may reprice a paper stock, adjusting either `base_price_cents` or `lead_days` in place. This is a business endpoint, not a versioning event: the update overwrites the live catalog values but does not touch `captured_base_price_cents` or `captured_finish_surcharge_cents` on any existing line item — that snapshot is exactly what makes the reorder-locked pricing variant possible.

A `ShopAdmin` may also discontinue a paper stock. Once `PaperStock.status` is `DISCONTINUED`, a new order may not reference the stock through a fresh line item — the system rejects the addition with `ERR_PAPER_DISCONTINUED`. The one exception is a reorder: on an order whose `prior_order_id` points at a delivered predecessor, a line item that continues the exact paper choice of a prior line is tolerated even if that paper is now `DISCONTINUED`. The symmetric rule holds for `FinishOption` with `ERR_FINISH_DISCONTINUED`. Both `ERR_PAPER_DISCONTINUED` and `ERR_FINISH_DISCONTINUED` fire on line-item addition, on order confirmation, and on design creation.

### 3.2. Design and Order Creation

A `Customer` initiates work by drafting a **Design**. Creating a design supplies a `customer_id` (which must equal the acting `X-User-ID`), an `event_package_id`, a `paper_stock_id`, a `finish_option_id`, and optional free-text `notes` that defaults to an empty string. The paper stock and finish option must both be `ACTIVE` at creation time. A fresh design starts with `status` `DRAFT` and no `designer_id`; the designer is bound later, when the first proof is created. The `Design.status` field evolves through `DRAFT`, `PROOFING`, `APPROVED`, and `ARCHIVED` as the associated `Proof` and `Order` progress. While the design remains `DRAFT`, its owner may amend `paper_stock_id`, `finish_option_id`, or `notes` in place.

Placing an order supplies `customer_id`, `design_id`, an optional `prior_order_id` for a reorder, and an optional `rush_deadline`. A new `Order` starts with `status` `CART`, `subtotal_cents` of zero, `total_cents` of zero, `rush_requested` false, `deposit_paid_cents` and `reorder_discount_cents` and `rush_surcharge_cents` all zero, and `Order.event_package_id` snapshotted from the parent design. Reorder eligibility is checked at this creation call: when `prior_order_id` is provided, the referenced prior `Order` must belong to the same customer, must be in `DELIVERED` status, and must have been created within the reorder window — that is, the calendar-day difference between the new order's `created_at` and the prior order's `created_at` must be at most 365 days. If any of those preconditions is violated, the create is rejected with `ERR_REORDER_WINDOW_EXPIRED`.

### 3.3. Line Items, Quantity Tiers, and Reorder Pricing

While the order sits in `CART`, its owner assembles it by adding **line items**. An add-line-item request supplies a `paper_stock_id`, a `finish_option_id`, a `quantity` — and, as described in §2.7, the OCC guard `expected_order_version` naming the client's last observed `Order.version`. On success, the server stamps the new `LineItem` with a snapshot of the live catalog: `captured_base_price_cents` is set from the current `PaperStock.base_price_cents`, and `captured_finish_surcharge_cents` from the current `FinishOption.surcharge_cents`. That snapshot is retained for the life of the line and is the input to reorder-locked pricing later.

The line's own `line_price_cents` is computed on the spot and stored on the row. The formula uses three inputs: the quantity, the captured paper price, and the captured finish surcharge. First, the system selects a tier multiplier by locating the quantity band into which `quantity` falls — the bands are 1 to 49 with multiplier one, 50 to 99 with multiplier one, 100 to 199 with multiplier nine-tenths, 200 to 499 with multiplier eight-tenths, and 500 or more with multiplier seven-tenths. The **paper component** is the captured paper price multiplied by the quantity multiplied by the tier multiplier, and this intermediate product is rounded half-up to a whole number of cents before it goes any further. The **finish component** is the captured finish surcharge multiplied by the quantity (integer arithmetic; nothing to round). `LineItem.line_price_cents` is the paper component plus the finish component. The per-line rounding is deliberate: order aggregation later is a sum of the already-rounded per-line values, never a fresh round on the total, because the tier-multiplier arithmetic across a whole order would otherwise drift.

Adding a line item requires `quantity` to be at least one and an integer — a non-integer or non-positive value is rejected with `ERR_QUANTITY_INVALID`. It also requires `quantity` to be at least the parent order's `event_package.min_qty` — a value below the minimum is rejected with `ERR_QUANTITY_BELOW_MIN`. The same minimum check runs again at confirm time. Every successful add or delete of a line item recomputes `Order.subtotal_cents` (the sum of `LineItem.line_price_cents` across all live lines on the order) and `Order.total_cents`, and increments `Order.version` by one; a delete of a line item on a `CART` order is a no-body operation returning 204.

The reorder-locked pricing variant applies when the parent `Order` was created with a `prior_order_id` that is inside the 365-day window and the new line item's `paper_stock_id` and `finish_option_id` both match a corresponding line on the prior order. In that case, the captured paper price and captured finish surcharge for the new line are taken from the matching prior line's own `captured_base_price_cents` and `captured_finish_surcharge_cents`, not from the current live catalog. When the live `PaperStock.base_price_cents` has changed between the two orders, the two pricing variants diverge — that price divergence, not a discount, is what "reorder-locked" delivers. A first-time order (no `prior_order_id`), or a reorder outside the 365-day window, uses the list-price variant that reads the live catalog.

### 3.4. Rush Requests and the Rush Surcharge

Between order creation and proof approval, a customer or a `ShopAdmin` may promote an order to a rush job. The rush-request payload supplies (or updates) `rush_deadline` — the client's ship-by target. The system computes the number of whole days between `rush_deadline` and the current UTC time, and rejects the request with `ERR_RUSH_INFEASIBLE` unless that number is at least three and strictly less than fourteen: a deadline fourteen or more days out is too far away for the rush tier to apply, and a deadline fewer than three days out is infeasible. Within the feasible range, the surcharge percentage is fifteen hundredths when the day count is at least seven and strictly less than fourteen, and thirty hundredths when the day count is at least three and strictly less than seven. The surcharge amount is that percentage applied to the base of `Order.subtotal_cents` minus `Order.reorder_discount_cents` — the same discounted subtotal on which the deposit is computed — and the result is rounded half-up to a whole number of cents. `Order.rush_surcharge_cents` records the result, `Order.rush_requested` flips to true, and `Order.total_cents` and `Order.expected_lead_days` are both recomputed.

Rushing an order also shortens any in-flight proof. When a rush is applied while the associated `Proof.status` is `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED`, the server recomputes `Proof.expires_at` using the rush proof-expiry variant described in §3.6.

A rush request that arrives after `Proof.status == APPROVED` is rejected with `ERR_RUSH_TOO_LATE` — once the customer has signed off, the deadline for accepting a rush has passed. The `Order.rush_deadline` field is nullable until a rush is applied; before that, it may be set (as an optional input) at order creation, but no rush arithmetic runs until an explicit rush request lands.

The expected lead-time calculation is a simple integer aggregation over the order's line items and add-ons: take the maximum `lead_days` across the paper stocks used on the lines, add the maximum `additional_lead_days` across the finish options used on the lines, add three additional business days if the order has any `AddressingJob` records, and subtract four business days if `Order.rush_requested` is true. The final `Order.expected_lead_days` is that sum with a floor of one — the field never drops below a single day.

### 3.5. Confirming the Order: Discount, Deposit, and Proofing

When the customer is satisfied with the cart, they confirm the order, moving `Order.status` from `CART` to `DEPOSIT_PENDING`. Confirmation requires at least one line item, each with `quantity` at least the package's `min_qty`, and requires every referenced `PaperStock` and `FinishOption` to be `ACTIVE` unless the order carries a `prior_order_id` that legitimises the discontinued item as a reorder. Violation of the paper or finish rule surfaces the same `ERR_PAPER_DISCONTINUED` or `ERR_FINISH_DISCONTINUED` seen earlier. Violation of the minimum-quantity rule surfaces `ERR_QUANTITY_BELOW_MIN` again.

At confirmation, the server locks three numbers. First, `Order.reorder_discount_cents` is computed: if the order has no `prior_order_id`, or if the prior order does not belong to the same customer, or if the prior order is not in `DELIVERED` status, or if the calendar-day difference between the two orders' `created_at` values exceeds 365, the discount is zero. Otherwise, the discount is `Order.subtotal_cents` multiplied by one-tenth, rounded half-up to a whole number of cents.

Second, `deposit_due_cents` on the order is locked. The base is `Order.subtotal_cents` minus `Order.reorder_discount_cents`; the deposit due is that base multiplied by `EventPackage.deposit_pct`, rounded half-up to a whole number of cents. The deposit-due value is intentionally frozen at confirm time — a subsequent rush request cannot retroactively raise the deposit that the customer has committed to pay.

Third, `Order.expected_lead_days` is recomputed by the formula in §3.4.

`Order.total_cents` — the running total after every adjustment — is `Order.subtotal_cents` minus `Order.reorder_discount_cents` plus `Order.rush_surcharge_cents` plus any `Proof.revision_fee_cents` accrued on the associated proof (zero when no proof yet exists). It is recomputed on every line-item change, on every rush application, on confirmation, and every time a revision fee accrues.

Confirmation also creates the initial `Proof` record for the order — with `status` `DRAFT`, `current_revision_number` of zero, and `designer_id` unset — writes the created proof's identifier back onto the order as `proof_id`, advances `Design.status` from `DRAFT` to `PROOFING`, and, for each line, adds `LineItem.quantity` to the referenced `PaperStock.reserved_units`. The `Proof.designer_id` is assigned when a designer creates the first proof submission through the initial-proof endpoint (described below).

The deposit is collected either through the customer-side pay-deposit endpoint, which pins the paid amount to `Order.deposit_due_cents`, or through the admin-only payments-simulation endpoint, which takes an explicit `order_id`, `amount_cents`, and `outcome`. Either way, the pay-deposit or payment-simulate operation requires `amount_cents` to equal `Order.deposit_due_cents` exactly — partial deposits are not supported, and a mismatched amount is rejected with `ERR_DEPOSIT_NOT_PAID`. On success (or on a simulated `SUCCEEDED` outcome), `Order.deposit_paid_cents` accumulates the payment; when it reaches `Order.deposit_due_cents`, `Order.deposit_paid_at` is set to the current UTC instant and `Customer.cumulative_deposits_paid_cents` is bumped by the amount. Payment at a moment when `Proof.status` is already `APPROVED` triggers the cascade described in §2.10.

The dispatch endpoint additionally re-checks that the deposit has in fact been fully paid; a shipment cannot leave the shop otherwise. The same `ERR_DEPOSIT_NOT_PAID` error covers this defensive dispatch check.

### 3.6. Proof Workflow: Submission, Revisions, Approval, and Expiry

Once an order sits in `DEPOSIT_PENDING`, its associated `Design.status` is `PROOFING`. A `Designer` opens the workflow by creating the initial `Proof` submission through an endpoint that binds the acting designer to the design. The initial-proof payload supplies a `designer_id` (which must equal the acting `X-User-ID`), creates the `Proof` in `status` `DRAFT` and `current_revision_number` zero, and stamps the parent `Design.designer_id` with the acting designer. Only a `Designer` may create proofs. If the referenced designer does not exist, the request is rejected with `ERR_DESIGNER_NOT_FOUND`.

The designer then submits the proof for customer review. Submission is only valid while the design is `PROOFING` (i.e., the parent order is past `CART`), and only the designer bound to the proof may act. A successful submission from `DRAFT → SUBMITTED` — or a resubmission from `CHANGES_REQUESTED → SUBMITTED` — increments `Proof.current_revision_number` by one, sets `Proof.submitted_at` to the current UTC instant, and (idempotently) recomputes `Order.expected_lead_days`. The very first submission takes `current_revision_number` from zero to one, and no revision fee applies. From the fourth submission onward — that is, whenever the post-increment `current_revision_number` is strictly greater than three — `Proof.revision_fee_cents` accrues an additional 2500 cents (twenty-five dollars) per resubmission and `Order.total_cents` is recomputed to include the new fee. The customer, in turn, may request changes — transitioning `SUBMITTED → CHANGES_REQUESTED`, clearing `Proof.submitted_at` back to null — or approve — transitioning `SUBMITTED → APPROVED`, stamping `Proof.approved_at`, advancing `Design.status` to `APPROVED`, and possibly cascading the order per §2.10. Both customer-side actions require the acting customer to own the parent design and require the current UTC time not to have passed `Proof.expires_at`; otherwise the action is rejected with `ERR_PROOF_EXPIRED`.

Every submission recomputes `Proof.expires_at` from the current UTC instant. The standard variant, used when `Order.rush_requested` is false, adds `EventPackage.proof_expiry_days` days to the submission timestamp. The rush variant, used when `Order.rush_requested` is true, halves the package's proof-expiry window and rounds the halved value up to a whole number of days — that is, the number of days added is the ceiling of `EventPackage.proof_expiry_days` divided by two. This is why applying a rush to an order with a proof already in flight recomputes `Proof.expires_at` immediately.

When the current UTC time passes `Proof.expires_at` while the proof is still in `SUBMITTED`, the system observes the expiry on the next invocation of any proof-scoped endpoint that touches this proof (any of the proof fetch, proof list, submit, request-changes, or approve endpoints; endpoints scoped to other resources such as `Order` or `Design` do not themselves trigger the observation) and drives the proof to `EXPIRED`, cascades the parent order to `CANCELLED`, and archives the design. Cancelling the parent order cascades the proof from any of `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` to `CANCELLED`. `APPROVED`, `EXPIRED`, and `CANCELLED` are terminal proof states.

Any state-transition endpoint invoked from a state where the transition is not permitted returns `ERR_INVALID_STATE`. Any action taken against a resource already in a terminal state — for example, cancelling an already-`CANCELLED` order, or acting on an already-`APPROVED` or `EXPIRED` proof — returns `ERR_ALREADY_TERMINAL`.

### 3.7. Production, Press Scheduling, and Addressing

The `IN_PRODUCTION` order runs against a **WorkOrder**. The work order is spawned automatically by the deposit/approval cascade in §2.10, with `order_id` bound to the parent order, `production_status` initialised to `NOT_STARTED`, and `addressing_status` initialised to `NOT_APPLICABLE` if the parent order has no `AddressingJob` records or to `PENDING` if it has at least one. The two dimensions advance independently.

The production dimension advances through `NOT_STARTED → PRINTING → FINISHING → COMPLETED` under `ShopAdmin` control. Each transition is driven by the production endpoint with a `new_status` value naming the target production state. The transition into `PRINTING` requires the parent order to still be in `IN_PRODUCTION` and requires the caller to lock in `press_id`, `press_slot_start`, and `press_slot_end`. The press slot is a closed interval — `press_slot_end` must be strictly greater than `press_slot_start` — and the interval must not overlap any other `WorkOrder`'s already-locked interval on the same `press_id`. Adjacency at the boundary (one interval's end equal to another interval's start) is also treated as a conflict; the closed-interval semantics reject that too. A conflict returns `ERR_PRESS_SLOT_OVERLAP`. The transition into `FINISHING` and the transition into `COMPLETED` on the production dimension carry no additional preconditions.

The addressing dimension advances through `PENDING → IN_PROGRESS → COMPLETED` when the order has addressing jobs. The addressing endpoint likewise carries a `new_status` value naming the target addressing state. Advancing into `IN_PROGRESS` requires the parent order to have at least one `AddressingJob`, and requires that the same-day aggregate not exceed the shop's daily addressing capacity of five hundred pieces. Concretely, the server sums `AddressingJob.quantity` across every `AddressingJob` whose `scheduled_date` equals today and whose parent order's `WorkOrder.addressing_status` is currently `IN_PROGRESS`; if that running total plus the quantities that would enter `IN_PROGRESS` by this transition would exceed five hundred, the request is rejected with `ERR_ADDRESSING_CAPACITY_EXCEEDED`. The successful transition also cascades every `AddressingJob` on the order to `IN_PROGRESS`. The subsequent transition to `COMPLETED` cascades every `AddressingJob` on the order to `COMPLETED`.

An `AddressingJob` is created against a `CART` or `DEPOSIT_PENDING` order by either its customer or a `ShopAdmin`. Creation supplies `job_type` (one of `ADDRESSING` or `ASSEMBLY`), a `quantity` of at least one, an ISO-8601 `scheduled_date`, and a per-piece `unit_price_cents` that must be strictly greater than zero. The job starts in `SCHEDULED` and is advanced by the addressing-dimension transitions on its parent work order. The lifecycle values `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED` cover every state an addressing job can occupy. Adding the first `AddressingJob` to an order triggers a recompute of `Order.expected_lead_days` — the three-day addressing adder described in §3.4 flips in.

When production completes while addressing is `NOT_APPLICABLE` or already `COMPLETED`, or when addressing completes while production is already `COMPLETED`, the parent order advances from `IN_PRODUCTION` to `READY_TO_SHIP` and a `Shipment` is spawned. This joint precondition is the reason for the cross-entity check `ERR_PROOF_NOT_APPROVED` — the order cannot reach `READY_TO_SHIP` without an `APPROVED` proof, which is enforced by the earlier deposit-plus-approval cascade in §2.10.

### 3.8. Fulfillment: Shipment and Delivery

A `Shipment` is spawned by the ready-to-ship cascade with `status` `PREPARING`, a server-minted `tracking_number`, and an `order_id` bound to the parent order. A `ShopAdmin` moves the shipment through `PREPARING → DISPATCHED → DELIVERED`. Dispatching requires the parent `WorkOrder.production_status` to be `COMPLETED` and `addressing_status` to be `NOT_APPLICABLE` or `COMPLETED`, and requires the deposit to have been fully paid — a violation of the latter reuses `ERR_DEPOSIT_NOT_PAID`, and the cross-entity state check reuses `ERR_INVALID_STATE`. Successful dispatch stamps `Shipment.dispatched_at` and advances `Order.status` to `SHIPPED`. Marking the shipment delivered stamps `Shipment.delivered_at`, advances `Order.status` to `DELIVERED`, archives the associated design (`Design.status` becomes `ARCHIVED`), and releases each line's `LineItem.quantity` from the referenced `PaperStock.reserved_units`. The delivery cascade does not touch `Customer.cumulative_deposits_paid_cents` — that field is retained by design.

`balance_due_cents` on the order is a read-only field defined as the greater of zero and `Order.total_cents` minus `Order.deposit_paid_cents`. It is the final invoice amount the customer would owe on delivery, but the shop bills that balance out of band — the delivery transition itself does not consume it. Terminal shipment states are `DELIVERED` and `CANCELLED`; a cancellation of the parent order while the order is `IN_PRODUCTION` or `READY_TO_SHIP` cascades the shipment (still in `PREPARING`) to `CANCELLED`.

### 3.9. Cancellation, Forfeiture, and Refund Flow

Cancellation is available at multiple points, and who may invoke it depends on where the order sits. From `CART`, either the acting customer (if the order belongs to them) or a `ShopAdmin` may cancel. From `DEPOSIT_PENDING`, likewise. From `IN_PRODUCTION`, only a `ShopAdmin` may cancel; a customer attempt against an `IN_PRODUCTION` order is rejected with `ERR_ORDER_NOT_CANCELLABLE`. From any terminal state (`SHIPPED` cannot be cancelled through this path, `DELIVERED` and `CANCELLED` are terminal), a cancellation request returns `ERR_ALREADY_TERMINAL`.

A `CART` cancellation cascades every `AddressingJob` on the order to `CANCELLED` (there is no proof yet to cascade, and no work order or shipment yet exists).

A `DEPOSIT_PENDING` cancellation cascades the proof — whichever of `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` it currently occupies — to `CANCELLED`, cascades every `AddressingJob` on the order to `CANCELLED`, and releases every `LineItem.quantity` from the referenced `PaperStock.reserved_units`. If `Order.deposit_paid_cents` is strictly greater than zero at the moment of cancellation, the entire paid amount is moved into `Customer.credit_balance_cents` and `Order.deposit_paid_cents` is reset to zero — this is the money-conservation move described in §2.9.

An `IN_PRODUCTION` cancellation is the forfeiture path. The `ShopAdmin` cancels; the work order is cancelled; a shipment, if one has been spawned, is cancelled if still `PREPARING`; the design is archived; and every `LineItem.quantity` is released from the paper stock's `reserved_units`. `Order.deposit_paid_cents` is retained on the (now `CANCELLED`) order and is not refunded to `Customer.credit_balance_cents`. The customer ledger described in §2.9 is deliberately left short by that amount — this is the intended accounting outcome.

The logical clock used by every deadline check in the system — proof expiry, rush feasibility, reorder eligibility — is settable by a `ShopAdmin` through an admin-only test-driving capability that accepts a `to_iso8601` value and advances the server's logical `current_utc` monotonically non-decreasingly. Server startup default is `2026-03-01T00:00:00Z`, which sits at or before every fixture date, so an unset clock is a deterministic earliest instant rather than wall-clock time.

## 4. Endpoint Definitions

Operations that create new stand-alone resources — for example a customer, a designer, a paper stock, a finish option, an event package, a design, a proof, a line item, an addressing job, or an order — return a 201 Created status code. Operations that modify an existing resource, including state transitions such as confirming an order, submitting or approving a proof, dispatching a shipment, or applying a rush, return a 200 OK status code. A successful deletion of a line item returns 204 No Content. In the table below, `Any` in the Authorized Role column is shorthand for "authorized under the scoping rules of §2.1 — the operation is available to `ShopAdmin`, `Customer` (scoped to own resources), and `Designer` (scoped to designer-visible resources) as noted in the RBAC matrix".

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/customers` | Register a customer. | ShopAdmin |
| GET | `/customers/{id}` | Fetch a customer. | ShopAdmin, Customer |
| GET | `/customers/{id}/designs` | List designs owned by a customer. | ShopAdmin, Customer |
| GET | `/customers/{id}/orders` | List orders owned by a customer. | ShopAdmin, Customer |
| POST | `/designers` | Register a designer. | ShopAdmin |
| GET | `/designers/{id}` | Fetch a designer. | ShopAdmin, Customer, Designer |
| GET | `/designers` | List designers. | ShopAdmin, Customer, Designer |
| POST | `/paper-stocks` | Create a paper stock. | ShopAdmin |
| POST | `/paper-stocks/{id}/discontinue` | Discontinue a paper stock. | ShopAdmin |
| PATCH | `/paper-stocks/{id}` | Reprice a paper stock. | ShopAdmin |
| GET | `/paper-stocks/{id}` | Fetch a paper stock. | ShopAdmin, Customer, Designer |
| GET | `/paper-stocks` | List paper stocks. | ShopAdmin, Customer, Designer |
| POST | `/finish-options` | Create a finish option. | ShopAdmin |
| GET | `/finish-options/{id}` | Fetch a finish option. | ShopAdmin, Customer, Designer |
| GET | `/finish-options` | List finish options. | ShopAdmin, Customer, Designer |
| POST | `/event-packages` | Create an event package. | ShopAdmin |
| GET | `/event-packages/{id}` | Fetch an event package. | ShopAdmin, Customer, Designer |
| GET | `/event-packages` | List event packages. | ShopAdmin, Customer, Designer |
| POST | `/designs` | Customer creates a design draft. | Customer |
| GET | `/designs/{id}` | Fetch a design. | ShopAdmin, Customer, Designer |
| PATCH | `/designs/{id}` | Customer updates a DRAFT design. | Customer |
| GET | `/designs` | Filtered list of designs. | ShopAdmin, Customer, Designer |
| POST | `/designs/{id}/proofs` | Designer creates the initial proof record for a PROOFING design. | Designer |
| POST | `/proofs/{id}/submit` | Designer submits or resubmits a proof. | Designer |
| POST | `/proofs/{id}/request-changes` | Customer rejects the submitted proof and asks for changes. | Customer |
| POST | `/proofs/{id}/approve` | Customer approves the submitted proof. | Customer |
| GET | `/proofs/{id}` | Fetch a proof. | ShopAdmin, Customer, Designer |
| GET | `/designs/{id}/proofs` | List proofs for a design. | ShopAdmin, Customer, Designer |
| GET | `/proofs` | Filtered list of proofs. | ShopAdmin, Customer, Designer |
| POST | `/orders` | Customer places a new order in CART. | Customer |
| POST | `/orders/{id}/line-items` | Add a line item to a CART order (requires expected_order_version). | Customer |
| DELETE | `/orders/{id}/line-items/{lid}` | Remove a line item from a CART order. | Customer |
| POST | `/orders/{id}/apply-rush` | Apply a rush to an order before proof approval. | Customer, ShopAdmin |
| POST | `/orders/{id}/confirm` | Customer confirms the order (CART → DEPOSIT_PENDING). | Customer |
| POST | `/orders/{id}/pay-deposit` | Customer records a deposit payment. | Customer |
| POST | `/orders/{id}/cancel` | Cancel an order. | Customer, ShopAdmin |
| GET | `/orders/{id}` | Fetch an order. | ShopAdmin, Customer |
| GET | `/orders` | Filtered list of orders. | ShopAdmin, Customer |
| GET | `/orders/{id}/line-items` | List line items on an order. | ShopAdmin, Customer |
| GET | `/line-items/{id}` | Fetch a line item by id. | ShopAdmin, Customer |
| GET | `/line-items` | Filtered list of line items. | ShopAdmin |
| POST | `/orders/{id}/addressing-jobs` | Add an addressing or assembly add-on to an order. | Customer, ShopAdmin |
| GET | `/orders/{id}/addressing-jobs` | List addressing jobs for an order. | ShopAdmin, Customer |
| GET | `/addressing-jobs/{id}` | Fetch an addressing job. | ShopAdmin, Customer |
| POST | `/work-orders/{id}/production` | Advance the production dimension of a work order. | ShopAdmin |
| POST | `/work-orders/{id}/addressing` | Advance the addressing dimension of a work order. | ShopAdmin |
| GET | `/work-orders/{id}` | Fetch a work order. | ShopAdmin, Customer |
| GET | `/orders/{id}/work-orders` | List work orders for an order. | ShopAdmin, Customer |
| POST | `/shipments/{id}/dispatch` | Dispatch a shipment (PREPARING → DISPATCHED). | ShopAdmin |
| POST | `/shipments/{id}/mark-delivered` | Mark a shipment delivered (DISPATCHED → DELIVERED). | ShopAdmin |
| GET | `/shipments/{id}` | Fetch a shipment. | ShopAdmin, Customer |
| GET | `/orders/{id}/shipments` | List shipments for an order. | ShopAdmin, Customer |
| POST | `/_clock/set_current_utc` | Advance the server's logical UTC clock. | ShopAdmin |
| POST | `/_payments/simulate` | Simulate an external deposit payment. | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGNER_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGN_NOT_FOUND` | 404 Not Found |
| `ERR_PROOF_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ADDRESSING_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAPER_STOCK_NOT_FOUND` | 404 Not Found |
| `ERR_FINISH_OPTION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_PROOF_NOT_APPROVED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROOF_EXPIRED` | 409 Conflict |
| `ERR_QUANTITY_BELOW_MIN` | 422 Unprocessable Entity |
| `ERR_QUANTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_PAPER_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_FINISH_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_PRESS_SLOT_OVERLAP` | 409 Conflict |
| `ERR_ADDRESSING_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RUSH_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_RUSH_TOO_LATE` | 409 Conflict |
| `ERR_REORDER_WINDOW_EXPIRED` | 422 Unprocessable Entity |
