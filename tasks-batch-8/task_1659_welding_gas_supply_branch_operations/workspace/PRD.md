# Welding Gas & Supply Branch Operations API — Product Requirements Document

## 1. Introduction

A welding-gas and industrial-supply branch runs several businesses under one roof: counter sales of hardgoods and compressed-gas cylinders, cylinder exchange for walk-in customers, specialty gas blends mixed to order, cylinder demurrage and weld-machine rental, scheduled truck routes alongside will-call pickup, safety training classes with certification issuance, and a small repair shop for customer-owned machines. This document specifies the API that serves as the branch's system of record for all of these operations — customer accounts, the product catalog, the cylinder float, contract pricing, orders, delivery routes, rental agreements, invoicing, training, and repair tickets.

Three themes dominate the design. First, several finite shared pools — the per-grade cylinder float, daily truck capacity, and classroom seats — are reserved, committed, and released as work moves through the branch, and the API is responsible for keeping those pools consistent at every step. Second, money flows through two distinct pricing regimes (retail list prices versus per-customer contract price books) and two settlement regimes (cash at the counter versus NET30 invoicing with credit-exposure tracking and automatic credit holds). Third, the business is time-driven: demurrage accrues daily, price books carry effective windows, specialty blends need lead time, machines need a turnaround buffer between rentals, and certifications expire — so every temporal rule in the system is evaluated against a single controllable logical clock rather than wall-clock time.

All resources live in a flat topology of top-level collections; relationships between them are expressed through identifier references in payloads rather than nested URLs. Consistency is immediate: every mutation and all of its cascading side effects commit atomically within the request that triggered them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `CounterRep` (front-counter sales representative: accounts, orders, will-call fulfillment, payments, rentals, enrollments, route planning), `BranchManager` (branch manager with full override power: catalog, cylinder float, price books, waivers, credit holds, invoice voids, billing runs, and the logical clock), `RouteDriver` (delivery driver: dispatches and closes routes and fulfills route orders at the stop), `Trainer` (safety training instructor: schedules classes, enrolls attendees, marks attendance, issues certifications), and `ServiceTech` (repair technician: intake, diagnosis, quoting, and repair execution on customer-owned machines).

A request whose `X-User-Role` header is missing, or whose value does not name one of these five roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not listed for the endpoint — or that fails a per-action role condition, such as the fulfillment-type split on order fulfillment or the per-target role split on repair-ticket and enrollment advancement described in §3 — is rejected with `ERR_FORBIDDEN` (HTTP 403).

All five roles are opaque staff identities. When `X-User-Role` is `CounterRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true independently for `BranchManager`, for `RouteDriver`, for `Trainer`, and for `ServiceTech`: in every case `X-User-ID` is an opaque operator identifier, never matched against a persisted entity. Ownership-style checks in this system are always relationship checks between entities — for example, matching a returned cylinder's recorded holder to the order's customer — never comparisons against `X-User-ID`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it may not be less than 1 or greater than 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Time in this system is governed by a single logical clock, not by wall-clock time. Every accrual, due-date, expiry, effective-window, lead-time, and turnaround rule evaluates against this clock, and all calendar arithmetic is performed in whole days. At server startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time.

A `BranchManager`-only, test-driving capability sets the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Advancing the clock performs a price-book sweep: every book still in `ACTIVE` status whose window end has been reached or passed is flipped to `EXPIRED`. Operators should treat the clock as the single source of "now" for the entire branch — an order confirmed today, a rental closed tomorrow, and a certification issued next week all read the same clock.

### 2.5. Common Resource Properties

Every resource in the system — customers, price books, products, cylinder assets, machines, rental agreements, delivery routes, orders, invoices, training classes, training enrollments, and repair tickets alike — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2025-05-24T10:30:00.123Z`), set when the resource is created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- **`version`** (integer): a system-managed integer that increments by one on every mutation of the resource.

A mutation is any change to the resource, whether applied directly by a client request or indirectly by a cascade from another entity's transition — a route whose `reserved_units` moves because an order confirmed onto it, an invoice whose `paid_cents` grows during a payment sweep, an enrollment cancelled by a class cancellation: each such change refreshes the affected resource's `updated_at` and increments its `version` by one.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integers denominated in whole cents — prices, fees, invoice amounts, payments, exposure figures, accruals, and waiver amounts alike.

Exactly one rounding event exists in the entire pricing pipeline. When a contract unit price is computed for an order line, the discounted figure is rounded half-up to a whole cent, and this rounding happens exactly once, at the very end of the unit-price calculation; the intermediate discounted base is never rounded. Line totals are then plain integer multiplications of the already-rounded unit price by the line quantity, with no further rounding, and an order's subtotal is the sum of those rounded line totals — summing raw unrounded per-line products is forbidden because it yields different cents. Rental accrual math applies ceiling or floor operations only to the quotient of chargeable days over the period length, never to cent amounts.

### 2.7. Optimistic Concurrency Control

Optimistic concurrency control exists to stop a client from writing against a resource whose state has moved on since the client last read it. Exactly two write endpoints in the entire API participate, and each names its own non-optional version field:

- Applying a payment to a customer account requires a non-optional `expected_customer_version` field carrying the customer's `version` as the client last observed it. If the customer's current `version` no longer matches — because an invoice was created, an earlier payment landed, or a credit-hold action ran in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The payment waterfall's allocation set (the customer's open invoices, credit balance, and exposure figures) may have changed since the client read the account, so the client must re-read before applying cash. The rejection is detected purely by the version mismatch; two strictly sequential requests are enough to produce it.
- Granting a goodwill waiver on a rental agreement requires a non-optional `expected_rental_agreement_version` field carrying the agreement's `version` as the client last observed it. If the agreement's current `version` no longer matches, the waiver is rejected with `ERR_STALE_VERSION` (HTTP 412), because accrual-affecting mutations — suspension, resumption, closure, prior waivers, and billing runs — rebase the accrued amount the waiver was judged against. Here too the rejection is detected purely by the version mismatch, with no overlap in time required.

No other endpoint accepts a version field; every other write in the system is unconditional.

### 2.8. Validation Order of Precedence

A single request can violate several rules at once, so the API evaluates its checks as an ordered cascade of gates and reports the first gate that fails. The order below is normative:

1. **Authentication.** The `X-User-Role` header is present and names a declared role; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The role is listed for the endpoint and any per-action role condition holds — the fulfillment-type split on order fulfillment (a `CounterRep` fulfills will-call orders only, a `RouteDriver` fulfills route orders only, a `BranchManager` fulfills either), the per-target split on repair-ticket advancement (approval and rejection targets require a `BranchManager`; all other targets require a `ServiceTech` or `BranchManager`), and the per-target split on enrollment advancement (attended and no-show targets require a `Trainer` or `BranchManager`, while cancellation also allows a `CounterRep`). Violations are `ERR_FORBIDDEN`.
3. **Existence.** Every identifier in the path exists, and every body-referenced identifier — `customer_id`, `product_id`, `route_id`, `price_book_id`, cylinder or machine asset identifiers, `class_id` — exists. Violations are `ERR_NOT_FOUND`.
4. **Request shape.** Required fields are present, types and enum members are valid, quantities and amounts are positive where required, a price book's `effective_from` is earlier than its `effective_to`, a class's `start_at` is earlier than its `end_at`, `route_id` is present exactly when the order ships by route and absent for will-call, and the polymorphic rental item pairing is consistent with the declared `item_type` and `rate_plan`. Shape failures are `ERR_VALIDATION`, with one dedicated exception: an inconsistent rental item/plan combination is reported as `ERR_RENTAL_ITEM_MISMATCH`. Taking counter payment on a NET30 customer's order is also a shape failure.
5. **Stale versions.** On the two version-checked endpoints of §2.7, the expected version matches the entity's current `version`; otherwise `ERR_STALE_VERSION`.
6. **Target state.** The target entity's own state permits the requested transition — an order advancing along its fulfillment dimension, an enrollment advancing only from its initial state, a route dispatching only from its planned state, a returned cylinder accepted only from the correct holder, and so on. Violations are `ERR_INVALID_STATE`.
7. **Pressure-vessel safety.** No `RETIRED` cylinder may be issued on an order or put on rent; violations are `ERR_CYLINDER_CONDEMNED`.
8. **Linked-entity state.** Entities referenced by the request are in compatible states: the customer is `ACTIVE` for order confirmation, rental opening, and enrollment creation (`ERR_ACCOUNT_ON_HOLD`); the route is still `PLANNED` when an order confirms onto it (`ERR_ROUTE_NOT_ACCEPTING`); the route is `DISPATCHED` when one of its orders is fulfilled (`ERR_ROUTE_NOT_DISPATCHED`); the class is `SCHEDULED` for enrollment creation and attendance marking (`ERR_CLASS_NOT_SCHEDULED`).
9. **Temporal and window rules.** Specialty staging waits for the blend's ready date (`ERR_MIX_NOT_READY`); attendance is not marked before the class starts (`ERR_CLASS_NOT_STARTED`); price-book activation respects the no-overlap window rule (`ERR_PRICE_BOOK_OVERLAP`); a classroom is not double-booked (`ERR_ROOM_DOUBLE_BOOKED`); a machine's post-rental turnaround buffer is honored (`ERR_RENTAL_OVERLAP`).
10. **Uniqueness and capacity.** Account numbers, SKUs, and serial numbers are unique (`ERR_DUPLICATE_ACCOUNT`, `ERR_DUPLICATE_SKU`, `ERR_DUPLICATE_SERIAL`); an attendee is not enrolled twice in the same class under the same paying account (`ERR_DUPLICATE_ENROLLMENT`); hardgood stock covers each line (`ERR_STOCK_INSUFFICIENT`); enough full cylinders of the required grade exist (`ERR_CYLINDER_UNAVAILABLE`); the truck has room (`ERR_ROUTE_CAPACITY_EXCEEDED`); a machine or cylinder is free to rent (`ERR_ASSET_NOT_AVAILABLE`); the class has seats (`ERR_CLASS_FULL`); a route closes only when all of its orders are terminal (`ERR_ROUTE_HAS_OPEN_ORDERS`); and issued/returned cylinder grades and counts match the order's gas lines (`ERR_CYLINDER_GRADE_MISMATCH`).
11. **Fiscal rules.** The NET30 credit check at confirmation (`ERR_CREDIT_LIMIT_EXCEEDED`); exact-amount cash payment (`ERR_PAYMENT_AMOUNT_MISMATCH`); payment before fulfillment of a cash order (`ERR_PAYMENT_REQUIRED`); a waiver no larger than the accrued amount (`ERR_WAIVER_EXCEEDS_ACCRUED`); and voiding only an untouched invoice (`ERR_INVOICE_NOT_VOIDABLE`).

Because the cascade is ordered, a request that is both unauthenticated and malformed always surfaces `ERR_UNAUTHENTICATED`; a stale payment on a nonexistent customer surfaces `ERR_NOT_FOUND`; and a credit-limit failure on an otherwise valid confirmation surfaces only after every state, safety, temporal, and capacity gate has passed.

### 2.9. Customer Credit Exposure

Every customer account carries a family of computed balance figures, denominated in whole cents, that together drive the branch's credit management. `outstanding_balance_cents` is the plain ledger view: the sum, over the customer's invoices in `OPEN` status, of each invoice's `amount_cents` minus its `paid_cents`. `credit_balance_cents` is the customer's unapplied overpayment credit, which starts at zero. `posted_exposure_cents` is the credit-managed view: the outstanding balance minus the credit balance, floored at zero. `accrued_rental_cents` looks forward instead of backward: it sums the `accrued_unbilled_cents` of the customer's rental agreements in `ACTIVE` or `SUSPENDED` status, recomputed on every read against the logical clock (a `CLOSED` agreement carries no unbilled accrual and contributes nothing). Finally, `projected_exposure_cents` is the forward-looking credit-check view: the posted exposure plus the accrued rental figure plus the sum of `total_cents` over the customer's orders whose `fulfillment_status` is `CONFIRMED` or `STAGED`. The projected figure is never less than the posted figure, so a confirmation can fail the credit check even when the ledger-only view would pass.

Two automatic transitions hang off these figures, and both apply only to `NET30` customers — cash accounts are not credit-managed. When an invoice-creation event (an order fulfillment, a rental billing run, or a rental close-out) pushes the customer's `posted_exposure_cents` strictly above the account's `credit_limit_cents`, the customer's status flips from `ACTIVE` to `CREDIT_HOLD` automatically; landing exactly at the limit does not trigger the hold. Symmetrically, when a payment waterfall or an invoice void brings the posted exposure back down to at or below the limit, a customer sitting in `CREDIT_HOLD` is returned to `ACTIVE` automatically. Each automatic flip is a mutation of the customer record and increments its `version`.

### 2.10. Cylinder Float Conservation and Pressure-Vessel Safety

The branch's cylinder float is the set of registered cylinder assets, and it obeys a strict per-grade conservation law. For each `gas_grade`, the float summary counts the assets in `FULL`, `EMPTY`, `OUT`, and `RETIRED` status, and defines the grade's total as the full, empty, and out counts combined — retired assets are excluded from the total. That total changes only through registration, which adds one, and retirement, which removes one; every other transition merely moves a cylinder between buckets. A balanced exchange fulfillment — a customer returning k cylinders of a grade and being issued k full cylinders of the same grade — leaves the grade's out count and total unchanged while its full count drops by k and its empty count rises by k.

Safety governs the float as firmly as arithmetic does. A cylinder that has been condemned — moved to `RETIRED`, which is permitted only from `FULL` or `EMPTY`, never while the cylinder is `OUT` at a customer site — is permanently out of circulation: it may not be issued against an order and may not be put on rent, and any attempt to supply one is rejected with `ERR_CYLINDER_CONDEMNED`. Retired assets still appear in the float summary, but only in the dedicated retired counts.

A read-only float-summary capability reports this reconciliation: a `grades` array with one entry per grade carrying its `gas_grade`, `full`, `empty`, `out`, `retired`, and `total` counts, plus the fleet-wide `total_assets` and `retired_assets` figures. It is served from a dedicated literal address that the router prefers over the by-identifier template, so the summary word is never interpreted as an asset `id`.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Contract Price Books

A `CounterRep` or `BranchManager` opens a customer account by supplying a unique branch `account_no` (a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT`), a display `name`, and optionally the account `terms`, its `credit_limit_cents`, and a `price_book_id`. Terms are either `CASH` or `NET30` and default to `CASH` when omitted; the credit limit defaults to 0 and only has meaning for `NET30` accounts; the price book link defaults to null, which means the account buys at retail pricing. New accounts start in `ACTIVE` status with all computed balances at zero. Reading an account returns those computed figures — `outstanding_balance_cents`, `posted_exposure_cents`, `accrued_rental_cents`, `projected_exposure_cents`, and `credit_balance_cents` as defined in §2.9 — evaluated against the current logical clock. The customer list accepts optional `status`, `terms`, and `price_book_id` filters alongside the standard `limit` and `offset`.

After creation, the mutable account fields — `name`, `terms`, `credit_limit_cents`, and `price_book_id` — can be updated by a `CounterRep` or `BranchManager` through the account-update operation, each update incrementing the customer's `version`. This update path is the only way to attach or replace a price book on an existing account, and it exists to break a creation-order cycle: a contract price book references its owning customer, while the customer's pricing link references the book, so one of the two links must be set after both records exist.

Manual account-status actions are a `BranchManager` exclusive, driven by an `action` field with four possible values. `PLACE_HOLD` moves an `ACTIVE` customer to `CREDIT_HOLD` (the manual form requires the customer to currently be `ACTIVE`; the system may also place the hold itself per §2.9). `RELEASE_HOLD` returns a `CREDIT_HOLD` customer to `ACTIVE` (the manual form requires the customer to currently be in `CREDIT_HOLD`; the system may also release the hold itself after a payment waterfall or invoice void). `SUSPEND` moves a customer from either `ACTIVE` or `CREDIT_HOLD` to `SUSPENDED`, and `REINSTATE` returns a `SUSPENDED` customer to `ACTIVE`. Every manual action increments the customer's `version`. A customer in `CREDIT_HOLD` or `SUSPENDED` is blocked from order confirmation, rental opening, and enrollment creation with `ERR_ACCOUNT_ON_HOLD`.

Contract pricing is governed by price books, which a `BranchManager` creates in `DRAFT` status. A book carries a `name`, a `scope` of `RETAIL` or `CONTRACT`, an effective window from `effective_from` (inclusive) to `effective_to` (exclusive, and strictly later than `effective_from` — otherwise `ERR_VALIDATION`), a `default_discount_pct` expressed as a fraction from 0 to 0.90 inclusive, applied to retail prices, and an optional `volume_tiers` array. Each volume-tier entry pairs a `min_qty` of at least 1 with an `extra_discount_pct`, the array is kept sorted by `min_qty` in ascending order, and it defaults to empty. A `CONTRACT` book requires a `customer_id` naming the account it belongs to; a `RETAIL` book must leave `customer_id` null. The price-book list supports `customer_id`, `scope`, and `status` filters.

Activation moves a book from `DRAFT` to `ACTIVE` and is guarded by a window-exclusion rule: no other `ACTIVE` book with the same `scope` and the same `customer_id` may have a window overlapping the candidate's window. Windows are half-open — `effective_to` is exclusive — so a book whose window begins exactly when another's ends is allowed; a genuine overlap is rejected with `ERR_PRICE_BOOK_OVERLAP`. Thereafter the book participates in pricing until the logical clock reaches its `effective_to`, at which point the system flips it to `EXPIRED` (a terminal state) and it stops participating in contract price resolution. Each activation increments the book's `version`.

### 3.2. Catalog, Branch Inventory, and the Cylinder Float

A `BranchManager` registers each sellable product with a unique `sku` (duplicates fail with `ERR_DUPLICATE_SKU`), a display `name`, a `category` of `HARDGOOD`, `GAS`, or `SPECIALTY_GAS`, and a `retail_price_cents` list price of zero or more. Products in the two gas categories must declare a `gas_grade` — one of `OXYGEN`, `ACETYLENE`, `ARGON`, `AR_CO2_7525`, or `NITROGEN` — while hardgoods must leave it null. The `hazmat` flag defaults to false and, when true on any line of an order, triggers the flat per-order hazmat fee described in §3.3. `reorder_point` and `lead_time_days` both default to 0; specialty gases typically carry a positive lead time, which drives order readiness in §3.3. Physical unit stock is tracked in `stock_on_hand`, which starts at 0, increases by the received `qty` (a positive integer) when a `BranchManager` receives stock into branch inventory — each receipt incrementing the product's `version` — decreases as orders confirm, and is restored if a confirmed order is cancelled. A product whose `stock_on_hand` has fallen to at or below its `reorder_point` reports `needs_reorder` as true.

Cylinders are tracked individually as pressure vessels. Registering one — again a `BranchManager` operation — records its stamped `serial_no` (unique across both cylinders and machines, enforced as `ERR_DUPLICATE_SERIAL`), its `gas_grade`, and its `size` of `SMALL`, `MEDIUM`, or `LARGE`; a newly registered cylinder arrives `FULL`. While a cylinder sits at the branch its `holder_customer_id` and `rental_agreement_id` are null; they are set when the cylinder goes out and cleared when it comes back. The cylinder list supports `status`, `gas_grade`, `holder_customer_id`, and `rental_agreement_id` filters. Retirement — the condemnation path of §2.10 — moves a `FULL` or `EMPTY` cylinder to `RETIRED`, permanently excluding it from issue and rental.

Rental weld machines are registered with a `model`, a unique `serial_no` (sharing the same uniqueness pool as cylinder serials), and three rate fields — `daily_rate_cents`, `weekly_rate_cents`, and `monthly_rate_cents` — each strictly greater than zero, feeding the rate plans of §3.6. A machine begins life `AVAILABLE`.

### 3.3. Building and Confirming an Order

An order begins when a `CounterRep` or `BranchManager` creates it with a `customer_id`, an `order_type` of `RETAIL`, `EXCHANGE`, or `SPECIAL_MIX`, a `fulfillment` mode of `WILL_CALL` or `ROUTE`, and a `lines` array in which each line references a `product_id` and a positive integer `qty`. Route orders must supply a `route_id` naming their delivery route, while will-call orders must leave it null; the pairing is enforced as `ERR_VALIDATION`. Line composition is also shape-checked: `EXCHANGE` lines must reference `GAS` products and `SPECIAL_MIX` lines must reference `SPECIALTY_GAS` products, with violations rejected as `ERR_VALIDATION`. A new order starts with `fulfillment_status` `DRAFT` and `payment_status` `UNPAID`, and its `subtotal_cents` remains 0 while it is a draft. Two derived figures appear immediately: `units`, the sum of quantities across all lines, and `available_date`, which for orders containing specialty-gas lines is the order's creation date plus the largest `lead_time_days` among those specialty lines, and which is null for orders without specialty lines. The order list accepts `customer_id`, `route_id`, `invoice_id`, and `fulfillment_status` filters.

Confirmation — the `DRAFT` → `CONFIRMED` transition, performed by a `CounterRep` or `BranchManager` — is the order's great checkpoint, and it runs a battery of guards. The customer must be `ACTIVE`, or the confirm is rejected with `ERR_ACCOUNT_ON_HOLD`. Every `HARDGOOD` line must be covered by the product's `stock_on_hand` (a shortfall is `ERR_STOCK_INSUFFICIENT`); gas lines are stocked as cylinders rather than shelf units, so for each `GAS` or `SPECIALTY_GAS` line the branch must hold at least as many `FULL` cylinders of the line's grade as the line quantity, or the confirm fails with `ERR_CYLINDER_UNAVAILABLE`. A route order may confirm only onto a route that is still `PLANNED` (`ERR_ROUTE_NOT_ACCEPTING`), and only while the truck has room: the route's `reserved_units` plus the order's `units` may not exceed the route's `truck_capacity_units` — landing exactly at capacity is allowed, one unit over is `ERR_ROUTE_CAPACITY_EXCEEDED`. Finally, for a `NET30` customer, confirmation runs the credit check: the customer's `projected_exposure_cents` plus the new order's `total_cents` must not exceed the account's `credit_limit_cents`; the comparison is strict, so landing exactly at the limit passes while one cent over is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

When confirmation succeeds, pricing is resolved and frozen. For each line, contract price resolution runs against the logical clock date: if the customer has no linked price book, or the linked book is not `ACTIVE`, or the clock date falls outside the book's window (which runs from `effective_from` inclusive to `effective_to` exclusive), the line's `unit_price_cents` snapshot is simply the product's `retail_price_cents`. Otherwise the discounted base is the product's retail price reduced by the book's `default_discount_pct` fraction; the applicable volume tier is the `volume_tiers` entry with the greatest `min_qty` that does not exceed the line quantity (if no tier qualifies, no extra discount applies); and the line's `unit_price_cents` is that base further reduced by the tier's `extra_discount_pct` fraction, rounded half-up to a whole cent — the single rounding event of §2.6, with no intermediate rounding of the base. Each line's `line_total_cents` is the rounded unit price multiplied by its quantity.

Order totals then aggregate in a pinned evaluation order, because the fees depend on the subtotal and never vice versa. `subtotal_cents` is the sum of the line totals. `delivery_fee_cents` is a flat 2500 cents ($25.00) when the order ships by route and its subtotal is strictly below the free-delivery threshold of 20000 cents ($200.00) — a subtotal exactly equal to the threshold waives the fee — and 0 otherwise. `hazmat_fee_cents` is a flat 1500 cents ($15.00) per order when any line's product is hazmat-flagged, regardless of how many hazmat lines exist, and 0 otherwise. `total_cents` is the subtotal plus the two fees. Confirmation also commits resources: each hardgood line's quantity is deducted from its product's `stock_on_hand`, a route order adds its `units` to the route's `reserved_units`, and the order's `version` increments.

Staging — the `CONFIRMED` → `STAGED` transition, again a `CounterRep` or `BranchManager` action — marks the order physically picked and ready. An order containing specialty-gas lines may stage only once the logical clock date is on or after its `available_date`; an earlier attempt is rejected with `ERR_MIX_NOT_READY`.

### 3.4. Counter Payment, Fulfillment, and Cancellation

Cash settlement happens at the counter through the order-payment action, available to a `CounterRep` or `BranchManager`. It exists only for `CASH` customers — invoking it against a `NET30` customer's order is a shape error, `ERR_VALIDATION` — and only while the order's `fulfillment_status` is `CONFIRMED` or `STAGED`, otherwise `ERR_INVALID_STATE`. The supplied `amount_cents` must equal the order's `total_cents` exactly; an over- or under-payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment flips `payment_status` from `UNPAID` to `PAID` while the fulfillment dimension stays exactly where it was, and increments the order's `version`.

Fulfillment — the `STAGED` → `FULFILLED` transition — hands the goods over, and the acting role depends on how the order ships: a `CounterRep` fulfills will-call orders, a `RouteDriver` fulfills route orders at the stop, and a `BranchManager` may fulfill either; any other combination is `ERR_FORBIDDEN`. A route order can fulfill only after its route has been dispatched (`ERR_ROUTE_NOT_DISPATCHED`), and a cash customer's order can fulfill only once its `payment_status` is `PAID` (`ERR_PAYMENT_REQUIRED`). Gas accountability is exact: for an order with gas lines the request must supply `issued_asset_ids` whose count equals the total quantity across the order's `GAS` and `SPECIALTY_GAS` lines, every issued asset must be `FULL` with a `gas_grade` matching one of the order's gas-line grades (a mismatch is `ERR_CYLINDER_GRADE_MISMATCH`), and no issued asset may be `RETIRED` (`ERR_CYLINDER_CONDEMNED`). An `EXCHANGE` order additionally requires `returned_asset_ids`, one per line quantity, where every returned cylinder must currently be `OUT`, must be held by the order's customer — its `holder_customer_id` equal to the order's `customer_id` — and must match the issued grades, with violations again reported as `ERR_CYLINDER_GRADE_MISMATCH`.

Fulfilling flips the assets: each issued cylinder moves `FULL` → `OUT` with its `holder_customer_id` set to the ordering customer, and each returned cylinder moves `OUT` → `EMPTY` with its holder link cleared, conserving the float per §2.10. What happens next depends on terms. For a cash customer, nothing further occurs — the order was already paid. For a `NET30` customer, fulfillment posts the order's invoice: an invoice is created with `source` `ORDER`, `amount_cents` equal to the order's `total_cents`, and `due_at` thirty days after issue; the order's `payment_status` moves `UNPAID` → `INVOICED` and its `invoice_id` is set to the new invoice. That invoice creation is hop 1 of the credit cascade — it recomputes the customer's exposure figures (hop 2), and if the posted exposure has risen strictly above the credit limit the customer's status flips `ACTIVE` → `CREDIT_HOLD` automatically (hop 3, per §2.9). Fulfillment increments the order's `version`.

Cancellation is possible from `DRAFT`, `CONFIRMED`, or `STAGED`, and is performed by a `CounterRep` or `BranchManager`. Cancelling a draft is bookkeeping-only, since nothing was reserved yet. Cancelling a confirmed or staged order restores each hardgood line's quantity to its product's `stock_on_hand` and, for a route order, subtracts the order's `units` from the route's `reserved_units`. Either way the order lands in the terminal `CANCELLED` state with its `version` incremented; `FULFILLED` is the other terminal state, and neither terminal state can be cancelled out of.

### 3.5. Delivery Routes and Truck Capacity

A `CounterRep` or `BranchManager` plans a delivery route by supplying a `route_date` and a `truck_capacity_units` figure — the total line-unit capacity of the truck for the day, which must be positive. A new route is `PLANNED` with `reserved_units` 0. From then on `reserved_units` is a derived figure: the sum of `units` over the orders bound to the route whose `fulfillment_status` is `CONFIRMED` or `STAGED`. Draft orders never reserve capacity, and fulfilled or cancelled orders release their units, so the figure rises at confirmation and falls at fulfillment or cancellation.

Dispatching — `PLANNED` → `DISPATCHED`, performed by a `RouteDriver` or `BranchManager` — sends the truck out, and only after dispatch may the route's orders be fulfilled by the driver. Closing — `DISPATCHED` → `CLOSED`, same roles — ends the day, and is refused with `ERR_ROUTE_HAS_OPEN_ORDERS` while any bound order is still in a non-terminal state: every order on the route must be `FULFILLED` or `CANCELLED` before the route can close. `CLOSED` is terminal. Both transitions increment the route's `version`.

### 3.6. Rentals, Demurrage, and Cycle Billing

A `CounterRep` or `BranchManager` opens a rental agreement by naming the renting `customer_id`, an `item_type` of `CYLINDER` or `MACHINE`, a `rate_plan`, and a `start_date` — which may be any past, present, or future date — plus an optional `scheduled_end_date` and an optional `grace_days` override. The item fields are polymorphic: `cylinder_asset_id` is required exactly when the item type is `CYLINDER` and must be null otherwise, `machine_id` is required exactly when the item type is `MACHINE` and must be null otherwise, and the rate plan must match the item — `DEMURRAGE` is for cylinders only, while `DAILY`, `WEEKLY`, and `MONTHLY` are for machines only. Any inconsistent combination of item type, asset field, and rate plan is rejected with `ERR_RENTAL_ITEM_MISMATCH`. When `grace_days` is omitted it defaults to 5 free days for `DEMURRAGE` agreements and to 0 for the machine plans.

Opening is guarded on several axes. The customer must be `ACTIVE` (`ERR_ACCOUNT_ON_HOLD`). A cylinder being put on rent must be `FULL`, and a machine must be `AVAILABLE`; otherwise the open fails with `ERR_ASSET_NOT_AVAILABLE` — and per §2.10 a `RETIRED` cylinder is rejected outright with `ERR_CYLINDER_CONDEMNED`. Machines carry an additional turnaround rule: after a rental closes, the machine needs a one-day service buffer, so a new rental's `start_date` must be strictly later than one day after the most recent close date among that machine's `CLOSED` rentals — a prior close on date D blocks start dates on D itself and on the following day — and a violation is `ERR_RENTAL_OVERLAP`.

A successful open starts the agreement in `ACTIVE` status with `lifetime_billed_cents` 0, `waived_cents` 0, `closed_at` null, and `billed_through_date` null until the first billing run or close. The rented asset flips with it: a cylinder moves `FULL` → `OUT` with its `holder_customer_id` set to the renting customer and its `rental_agreement_id` set to the new agreement, while a machine moves `AVAILABLE` → `RENTED`. The customer's `accrued_rental_cents` picks up the new agreement from that moment. The agreement list supports `customer_id`, `machine_id`, `cylinder_asset_id`, and `status` filters.

Accrual is computed against the logical clock in whole days. The chargeable days at a given as-of date are the whole days elapsed from `start_date` to that date minus `grace_days`, never less than zero. The period length depends on the rate plan: 1 day for `DAILY`, 7 days for `WEEKLY`, and 30 days for both `MONTHLY` and `DEMURRAGE`. The period rate is the rented machine's `daily_rate_cents`, `weekly_rate_cents`, or `monthly_rate_cents` for the machine plans, and a flat 1200 cents ($12.00) per 30-day period for `DEMURRAGE`. Two valuations of the same accrual exist, and they answer different questions. The provisional value rounds the chargeable-days-over-period quotient up to a whole number of periods and multiplies by the rate — the customer currently owes for a period they have started. The billed value rounds the same quotient down to whole completed periods only — a started-but-unfinished period is not yet billed, so the billed figure is smaller than the provisional figure whenever a partial period is in flight. The agreement's stored `accrued_unbilled_cents` is the provisional value at the current clock date minus `lifetime_billed_cents` and minus `waived_cents`, never below zero, and it is what account reads fold into `accrued_rental_cents`.

Suspension and resumption form a cycle: a `CounterRep` or `BranchManager` may move an agreement `ACTIVE` → `SUSPENDED` and later `SUSPENDED` → `ACTIVE`, each step incrementing the agreement's `version`. Suspension stops billing, not accrual — billing runs skip agreements in `SUSPENDED` status, but the provisional value keeps accruing against the clock.

The monthly billing run is a `BranchManager`-only ops checkpoint. It iterates every agreement in `ACTIVE` status, computes each one's billed value at the current clock date as the complete-period figure minus `lifetime_billed_cents` and minus `waived_cents` (never below zero), and for every agreement with a positive amount posts the charge. Charges are grouped per customer into a single invoice per customer with `source` `RENTAL_CYCLE`; each billed agreement's `billed_through_date` advances to the run date and its `lifetime_billed_cents` grows by the billed amount. The run responds with `invoices_created`, the list of `invoice_ids`, and the `total_billed_cents` across the run. Because invoice creation is an exposure event, a billing run can tip a `NET30` customer into an automatic `CREDIT_HOLD` per §2.9.

Goodwill waivers are a `BranchManager` exclusive carrying three inputs: `waive_amount_cents`, a free-text `reason`, and the concurrency token `expected_rental_agreement_version` of §2.7. The waived amount may not exceed the agreement's current `accrued_unbilled_cents` — waiving exactly the accrued amount is allowed, one cent more is rejected with `ERR_WAIVER_EXCEEDS_ACCRUED`. A successful waiver adds the amount to `waived_cents`, recomputes the accrual, and increments the agreement's `version`.

Closing is allowed from either `ACTIVE` or `SUSPENDED` and lands in the terminal `CLOSED` state with identical side effects from both. The close stamps `closed_at` with the logical clock and sets `billed_through_date` to the close date, then settles up: the final charge is the provisional (round-up) value at the close date minus `lifetime_billed_cents` and minus `waived_cents`, never below zero. When the final charge is positive, an invoice with `source` `RENTAL_CLOSE` is created for that amount and `lifetime_billed_cents` grows by it. The asset comes back: a rented cylinder moves `OUT` → `EMPTY` with its holder and rental links cleared, while a rented machine moves `RENTED` → `AVAILABLE`, arming the turnaround buffer for the next rental. The invoice, if any, triggers the exposure recompute and possible automatic credit hold of §2.9, and the agreement's `version` increments.

### 3.7. Invoices, the Payment Waterfall, and Settlement

Invoices are the branch's receivables ledger, and the system creates them — clients never do. Each invoice records the billed `customer_id`, a `source` of `ORDER`, `RENTAL_CYCLE`, or `RENTAL_CLOSE`, an `order_id` that is set exactly when the source is `ORDER` and null otherwise, the invoiced `amount_cents`, and `paid_cents` starting at 0. `issued_at` is stamped from the logical clock at creation, and `due_at` is thirty days after issue for `NET30` customers or equal to `issued_at` for `CASH` customers. An invoice begins `OPEN`, becomes `PAID` the moment its `paid_cents` reaches or exceeds its `amount_cents`, and can end `VOID`; both `PAID` and `VOID` are terminal. The invoice list supports `customer_id`, `order_id`, and `status` filters.

Applying a payment is a `CounterRep` or `BranchManager` action on the customer account carrying `amount_cents` and the concurrency token `expected_customer_version` of §2.7. The payment sweeps the customer's `OPEN` invoices — and only those; `PAID` and `VOID` invoices are never candidates — in a pinned order: earliest `due_at` first, ties broken by earliest `issued_at`, further ties by earliest `created_at`, and never by identifier. Starting from the full amount, each invoice in turn receives the smaller of the remaining funds and that invoice's own outstanding balance; an invoice whose `paid_cents` thereby reaches its `amount_cents` flips to `PAID`. Whatever remains after the sweep is added to the customer's `credit_balance_cents` as unapplied overpayment. Allocation is exact: the sum of the per-invoice applications plus the credit added equals the payment amount to the cent. The response reports the per-invoice `allocations`, the `credit_added_cents`, and the customer's refreshed `outstanding_balance_cents` and `posted_exposure_cents`.

An invoice reaching `PAID` fires the settlement cascade. If the invoice's `source` is `ORDER`, the linked order's `payment_status` moves `INVOICED` → `SETTLED`, incrementing the order's `version`. The customer's exposure figures are then recomputed, and if the customer was sitting in `CREDIT_HOLD` and the posted exposure has fallen to at or below the credit limit, the account returns to `ACTIVE` automatically — the release half of §2.9.

Voiding is a `BranchManager` override for invoices that should never have been issued. It is permitted only while the invoice is `OPEN` and its `paid_cents` is still 0; an attempt against an invoice that has collected any payment, or that has already left `OPEN`, is rejected with `ERR_INVOICE_NOT_VOIDABLE`. A void drops the balance out of the customer's exposure figures — which may release a credit hold — and, when the voided invoice's `source` is `ORDER`, reverts the linked order's `payment_status` from `INVOICED` back to `UNPAID`. The invoice lands in the terminal `VOID` state with its `version` incremented.

### 3.8. Safety Training Classes, Enrollment, and Certification

A `Trainer` or `BranchManager` schedules a safety class by supplying a `title`, a `room` of `ROOM_A` or `ROOM_B`, a `start_at` and `end_at` (the start must be strictly earlier than the end, else `ERR_VALIDATION`), a positive `capacity` seat count, and a `price_cents` of zero or more. The new class is `SCHEDULED` with `seats_booked` 0. One room cannot hold two overlapping scheduled classes: a new class whose half-open window from `start_at` (inclusive) to `end_at` (exclusive) overlaps another `SCHEDULED` class in the same room is rejected with `ERR_ROOM_DOUBLE_BOOKED`, while a class that begins exactly when another ends is allowed.

From `SCHEDULED`, a `Trainer` or `BranchManager` advances the class along one of two paths by naming a target `to`. Advancing to `COMPLETED` marks the class taught and requires the logical clock to have reached the class's `end_at` — completing early is rejected with `ERR_CLASS_NOT_STARTED`. Advancing to `CANCELLED` cancels the class and cascades downward: every enrollment still in `ENROLLED` status is moved to `CANCELLED`, while enrollments already marked `ATTENDED` or `NO_SHOW` are untouched, and `seats_booked` is recomputed. Both `COMPLETED` and `CANCELLED` are terminal, and each advance increments the class's `version`.

Enrollment puts a named attendee in a seat: a `CounterRep`, `Trainer`, or `BranchManager` supplies the `class_id`, the paying account's `customer_id`, and the `attendee_name`. The class must still be `SCHEDULED` (`ERR_CLASS_NOT_SCHEDULED`) and the paying customer must be `ACTIVE` (`ERR_ACCOUNT_ON_HOLD`). Capacity is hard: `seats_booked` counts the enrollments in `ENROLLED`, `ATTENDED`, or `NO_SHOW` status, and when that count already equals the class's `capacity` the class is full and further enrollments are rejected with `ERR_CLASS_FULL`. Duplicates are rejected too — a second enrollment with the same class, paying customer, and attendee name in any non-`CANCELLED` status fails with `ERR_DUPLICATE_ENROLLMENT`. A successful enrollment starts `ENROLLED` and occupies a seat immediately. The enrollment list supports `class_id`, `customer_id`, and `status` filters.

Attendance is marked by advancing an enrollment, which is permitted only from `ENROLLED` (any other starting point is `ERR_INVALID_STATE`) by naming a target `to`. Advancing to `ATTENDED` requires the class to be `SCHEDULED` (`ERR_CLASS_NOT_SCHEDULED`) and the logical clock to be at or after the class's `start_at` (`ERR_CLASS_NOT_STARTED`); success issues the attendee's certification — `cert_code` becomes the string `CERT-` followed by the enrollment's `id`, and `cert_expires_at` is set to the attendance timestamp plus 1095 days, a three-year validity — and both fields remain null for enrollments that never attend. Advancing to `NO_SHOW` requires only that the class still be `SCHEDULED`, and the seat remains consumed. Advancing to `CANCELLED` frees the seat, since cancelled enrollments no longer count toward `seats_booked`. Role power is split per target: `ATTENDED` and `NO_SHOW` require a `Trainer` or `BranchManager`, while `CANCELLED` additionally allows a `CounterRep`. `ATTENDED`, `NO_SHOW`, and `CANCELLED` are all terminal, and every advance increments the enrollment's `version`.

### 3.9. Repair Tickets and the Re-Quote Loop

The repair shop tracks customer-owned machines through repair tickets. A `ServiceTech` or `BranchManager` intakes a ticket with the owner's `customer_id`, a free-text `machine_desc` describing the machine, and an `issue_desc` describing the reported fault; the ticket starts in `INTAKE` with `revision_no` 0. The ticket list supports `customer_id` and `status` filters.

Work proceeds by advancing the ticket to a named target `to`, drawn from `DIAGNOSING`, `QUOTED`, `APPROVED`, `REJECTED`, `IN_REPAIR`, `READY_FOR_PICKUP`, and `CLOSED`, with each legal move incrementing the ticket's `version`. The legal path runs `INTAKE` → `DIAGNOSING` → `QUOTED`, and quoting requires a `quote_cents` greater than zero to be supplied with the advance (a missing or non-positive quote is `ERR_VALIDATION`), which is recorded on the ticket. From `QUOTED` the decision is managerial: only a `BranchManager` may advance the ticket to `APPROVED` or to `REJECTED`, while the other targets are open to a `ServiceTech` or `BranchManager`. An approved ticket proceeds `APPROVED` → `IN_REPAIR` → `READY_FOR_PICKUP` → `CLOSED`.

Rejection is not the end: a `REJECTED` ticket can be advanced back to `DIAGNOSING` for another look, and each such re-quote loop increments `revision_no` and clears `quote_cents` back to null, so the next quote starts clean. Closure settles the money: a ticket closed from `READY_FOR_PICKUP` sets `charged_cents` to its `quote_cents`, while a ticket closed from `REJECTED` — the customer declined the work — sets `charged_cents` to 0; until closure, `charged_cents` is null. `CLOSED` is terminal, and any advance whose from-state and target do not form one of the pairs above is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, read a single resource, or list resources return a `200 OK` status code. The table below is a summary only — request payloads, response bodies, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Open a customer account | CounterRep, BranchManager |
| GET | `/customers` | List customers with pagination and filters | CounterRep, BranchManager, RouteDriver, Trainer, ServiceTech |
| GET | `/customers/{id}` | Get one customer including computed balance/exposure fields | CounterRep, BranchManager, RouteDriver, Trainer, ServiceTech |
| PATCH | `/customers/{id}` | Update mutable account fields; the only way to attach or replace a price book after creation | CounterRep, BranchManager |
| POST | `/customers/{id}/credit-hold` | Manual account-status actions: PLACE_HOLD, RELEASE_HOLD, SUSPEND, REINSTATE | BranchManager |
| POST | `/customers/{id}/payments` | Apply a payment across the customer's open invoices via the payment waterfall; leftover becomes credit balance | CounterRep, BranchManager |
| POST | `/price-books` | Create a price book in DRAFT; CONTRACT scope requires a customer, RETAIL scope forbids one | BranchManager |
| GET | `/price-books` | List price books with filters | CounterRep, BranchManager |
| POST | `/price-books/{id}/activate` | Activate a DRAFT book; rejects overlapping active windows for the same scope and customer | BranchManager |
| GET | `/price-books/{id}` | Get one price book | CounterRep, BranchManager |
| POST | `/products` | Register a product/SKU | BranchManager |
| GET | `/products/{id}` | Get one product including stock and reorder flag | CounterRep, BranchManager, RouteDriver, Trainer, ServiceTech |
| POST | `/products/{id}/receive` | Receive stock into branch inventory | BranchManager |
| POST | `/cylinder-assets` | Register a branch-owned cylinder into the float (arrives FULL) | BranchManager |
| GET | `/cylinder-assets` | List cylinders with filters | CounterRep, BranchManager, RouteDriver |
| GET | `/cylinder-assets/float-summary` | Per-grade float reconciliation; the literal `float-summary` segment is declared before and wins over the `{id}` template | CounterRep, BranchManager, RouteDriver |
| GET | `/cylinder-assets/{id}` | Get one cylinder asset | CounterRep, BranchManager, RouteDriver |
| POST | `/cylinder-assets/{id}/retire` | Condemn a cylinder (FULL or EMPTY only, never OUT) | BranchManager |
| POST | `/machines` | Register a rental weld machine | BranchManager |
| GET | `/machines/{id}` | Get one machine | CounterRep, BranchManager, RouteDriver, ServiceTech |
| POST | `/rental-agreements` | Open a cylinder-demurrage or machine rental, flipping the asset and clearing the turnaround buffer | CounterRep, BranchManager |
| GET | `/rental-agreements` | List rental agreements with filters | CounterRep, BranchManager |
| GET | `/rental-agreements/{id}` | Get one agreement including the computed accrual at the current logical clock | CounterRep, BranchManager |
| POST | `/rental-agreements/{id}/suspend` | Suspend billing; accrual keeps accruing while billing runs skip the agreement | CounterRep, BranchManager |
| POST | `/rental-agreements/{id}/resume` | Resume a suspended agreement | CounterRep, BranchManager |
| POST | `/rental-agreements/{id}/close` | Close from ACTIVE or SUSPENDED: posts the final charge, releases the asset, may trigger a credit hold | CounterRep, BranchManager |
| POST | `/rental-agreements/{id}/waive` | Waive accrued demurrage/rental cents (goodwill waiver, version-checked) | BranchManager |
| POST | `/delivery-routes` | Plan a delivery route for a date | CounterRep, BranchManager |
| GET | `/delivery-routes/{id}` | Get one route including computed reserved units | CounterRep, BranchManager, RouteDriver |
| POST | `/delivery-routes/{id}/dispatch` | Dispatch a PLANNED route; only after dispatch may its orders be fulfilled | RouteDriver, BranchManager |
| POST | `/delivery-routes/{id}/close` | Close a DISPATCHED route; requires every bound order FULFILLED or CANCELLED | RouteDriver, BranchManager |
| POST | `/orders` | Create an order (DRAFT, payment UNPAID) | CounterRep, BranchManager |
| GET | `/orders` | List orders with filters | CounterRep, BranchManager, RouteDriver |
| GET | `/orders/{id}` | Get one order with its pricing snapshot and both state dimensions | CounterRep, BranchManager, RouteDriver |
| POST | `/orders/{id}/confirm` | Confirm a draft: snapshot pricing, reserve stock and route units, run the NET30 credit check | CounterRep, BranchManager |
| POST | `/orders/{id}/stage` | Stage a confirmed order; specialty blends stage only once the ready date arrives | CounterRep, BranchManager |
| POST | `/orders/{id}/pay` | Take counter payment for a CASH customer's order; the amount must equal the order total exactly | CounterRep, BranchManager |
| POST | `/orders/{id}/fulfill` | Fulfill a staged order; issues and returns cylinders, posts the invoice for NET30 orders | CounterRep, RouteDriver, BranchManager |
| POST | `/orders/{id}/cancel` | Cancel from DRAFT, CONFIRMED, or STAGED; restores reserved stock and releases route units | CounterRep, BranchManager |
| GET | `/invoices` | List invoices with filters | CounterRep, BranchManager |
| GET | `/invoices/{id}` | Get one invoice | CounterRep, BranchManager |
| POST | `/invoices/{id}/void` | Void an untouched OPEN invoice; ORDER-sourced voids revert the order's payment status | BranchManager |
| POST | `/billing/run-rental-cycle` | Run the monthly demurrage/rental billing cycle across all ACTIVE agreements, one invoice per affected customer | BranchManager |
| POST | `/training-classes` | Schedule a safety class; rooms may not be double-booked | Trainer, BranchManager |
| GET | `/training-classes/{id}` | Get one class including the computed seats booked | CounterRep, BranchManager, Trainer |
| POST | `/training-classes/{id}/advance` | Advance a class to COMPLETED or CANCELLED (cancellation cascades to enrollments) | Trainer, BranchManager |
| POST | `/enrollments` | Enroll an attendee; class must be SCHEDULED with seats free; duplicates rejected | CounterRep, Trainer, BranchManager |
| GET | `/enrollments` | List enrollments with filters | CounterRep, BranchManager, Trainer |
| GET | `/enrollments/{id}` | Get one enrollment | CounterRep, BranchManager, Trainer |
| POST | `/enrollments/{id}/advance` | Mark ATTENDED (issues the certification), NO_SHOW, or CANCELLED (frees the seat) | CounterRep, Trainer, BranchManager |
| POST | `/repair-tickets` | Intake a customer-owned machine for repair | ServiceTech, BranchManager |
| GET | `/repair-tickets` | List repair tickets with filters | ServiceTech, BranchManager, CounterRep |
| GET | `/repair-tickets/{id}` | Get one repair ticket | ServiceTech, BranchManager, CounterRep |
| POST | `/repair-tickets/{id}/advance` | Drive the repair state machine; quote required for QUOTED; approval and rejection are manager-only | ServiceTech, BranchManager |
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps price books whose window has ended into EXPIRED | BranchManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_RENTAL_ITEM_MISMATCH` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYLINDER_CONDEMNED` | 409 Conflict |
| `ERR_ACCOUNT_ON_HOLD` | 409 Conflict |
| `ERR_ROUTE_NOT_ACCEPTING` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_CLASS_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CLASS_NOT_STARTED` | 409 Conflict |
| `ERR_MIX_NOT_READY` | 409 Conflict |
| `ERR_PRICE_BOOK_OVERLAP` | 409 Conflict |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RENTAL_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_STOCK_INSUFFICIENT` | 409 Conflict |
| `ERR_CYLINDER_UNAVAILABLE` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ASSET_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CYLINDER_GRADE_MISMATCH` | 409 Conflict |
| `ERR_CLASS_FULL` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_PAYMENT_REQUIRED` | 409 Conflict |
| `ERR_WAIVER_EXCEEDS_ACCRUED` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
