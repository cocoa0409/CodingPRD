# Water Delivery & Bottled Water Service API — Product Requirements Document

## 1. Introduction

A bottled-water distributor runs a mixed book of business: office accounts with rented coolers and standing weekly deliveries, households that call in a delivery only when the last five-gallon bottle runs dry, and a scattering of coffee, filtration, and cup add-ons attached to both. Every delivery is also a bottle exchange — the driver drops full bottles, collects empties, and the difference between what was owed and what came back becomes money: refundable deposits, non-return fees, and credits when a stop is skipped. This document specifies the API that runs that operation end to end, mounted under the `/api/v1` prefix.

The system covers account registration and standing, delivery zones and the routes that serve them, per-stop execution by drivers (including partial deliveries, shortages, skips, and failures), a bottle custody ledger that tracks where every five-gallon bottle sits, cooler rental contracts with prorated rent, on-demand work orders, and the billing engine that turns all of it into invoices, payments, late fees, and skip credits. Because drivers, dispatchers, and billing staff act on the same records throughout the day, the API leans on explicit state machines, optimistic concurrency checks, and a logical clock that drives time-based transitions such as invoices going overdue and credits expiring.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and cross-cutting principles that apply to every resource and every request in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `OpsAdmin` (a back-office operator with full administrative privileges), `Dispatcher` (a route planner who builds routes and schedules work orders), `Driver` (a field operator executing routes and cooler installs), `BillingAdmin` (a billing operator managing invoices and payments), and `CustomerSelf` (an end customer acting on their own account). A request with missing or malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); this check applies to every endpoint except the logical-clock test-driving capability described in §2.4, which is exempt so test harnesses can initialize time before any identity exists; on that one capability the role header is optional, but if `X-User-Role` is supplied it must be `OpsAdmin` — any other supplied role is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A request whose declared role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For `OpsAdmin`, `Dispatcher`, `Driver`, and `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`. When `X-User-Role` is `CustomerSelf`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order (earliest created first). List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Driven Transitions

The server never consults the wall clock. It maintains a logical clock that starts at 2026-05-01T00:00:00Z on a fresh deployment and changes only when an `OpsAdmin` invokes the admin-only clock-setting capability with a target instant supplied as `to_iso8601` (any well-formed target instant is accepted, including one behind the current logical time); the capability responds with the new logical time in `now_iso8601`. Setting the logical clock fires time-based auto-transitions: any `OPEN` invoice whose `due_date` has been passed while its `balance_due_cents` remains positive flips to `OVERDUE`, and any `PENDING` skip credit whose `expires_at` has been reached flips to `EXPIRED`. Every rule in this document that references "the current date" or "the current time" — route start eligibility, credit expiry, prorated rent accrual, overdue evaluation — reads this logical clock.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID rendered in its canonical dashed 8-4-4-4-12 lowercase hexadecimal string form, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at` is the same style of timestamp, refreshed on every mutation. The `version` field is an integer starting at 1 that increments by one on every modification to the resource, including modifications caused by cascading side effects from operations on other resources.

One resource is deliberately lighter. Entries in the bottle custody ledger are immutable once written: a custody entry carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.6. Request Validation Order

Every request passes through a fixed cascade of checks, and the order matters because an early failure masks all later ones. The cascade runs as follows:

1. Header presence and well-formedness — violations return `ERR_UNAUTHENTICATED`.
2. Role permission for the invoked endpoint — violations return `ERR_UNAUTHORIZED`.
3. Existence of every resource named by a path parameter — violations return `ERR_NOT_FOUND`.
4. Whether the target resource is in a state that permits the requested transition — violations return `ERR_INVALID_STATE`; an operation attempted on a resource already sitting in a terminal state is instead rejected with `ERR_ALREADY_TERMINAL`.
5. Presence, types, and enum membership of required request fields — violations return `ERR_INVALID_REQUEST`.
6. Whether foreign-key references in the body resolve to existing, compatible entities — violations return `ERR_INVALID_REFERENCE`.
7. Well-formedness of date fields and date-range sanity — violations return `ERR_INVALID_DATE_RANGE`.

Only after all seven generic stages pass do endpoint-specific business checks run, each with its own error code and each described in §3 next to the workflow it guards: stop-sequence uniqueness within a route (`ERR_DUPLICATE_SEQUENCE`), truck-capacity enforcement (`ERR_ROUTE_CAPACITY_EXCEEDED`), payment-amount sanity at apply time (`ERR_OVERPAYMENT`), the zero-balance gate on account closure (`ERR_OUTSTANDING_BALANCE`), the zero-bottle-custody gate on account closure (`ERR_BOTTLES_OUTSTANDING`), the mandatory skip explanation (`ERR_SKIP_REASON_REQUIRED`), credit expiry at apply time (`ERR_CREDIT_EXPIRED`), customer-self ownership (`ERR_FORBIDDEN`), pricing-configuration consistency (`ERR_INVALID_PRICING_CONFIG`), optimistic-concurrency freshness (`ERR_STALE_VERSION`), and the restricted source states for raising an invoice dispute (`ERR_INVALID_STATE`).

### 2.7. Nested Resource Retrieval

Endpoints whose paths nest one resource inside another — a stop inside a route, a payment listing inside an invoice, a customer sub-collection — validate path identifiers strictly left to right. The request is rejected immediately with `ERR_NOT_FOUND` for the first identifier, reading from the left, that does not resolve to an existing resource; the system does not evaluate identifiers further right, and it does not evaluate the request body, until every path identifier to its left has resolved. Existence checking per §2.6 stage 3 therefore always surfaces the leftmost dangling reference.

### 2.8. Monetary Values, Counts, and Precision

All money in this system is carried as integer cents — prices, deposits, rents, invoice subtotals, balances, credits, and late fees are whole-cent integers, and no monetary field ever holds a fractional cent. Where a calculation could produce a fraction (the daily rent rate, a partial skip credit, an invoice total), the result is rounded half-up to the nearest whole cent at the step this document specifies, and no additional rounding is applied afterward. Bottle counts, sequence indices, thresholds, and version numbers are plain integers. Dates are ISO 8601 strings — `YYYY-MM-DD` where a calendar date is expected, full UTC timestamps where an instant is expected.

### 2.9. Optimistic Concurrency Control

Two write operations carry an explicit optimistic-concurrency contract, and no other endpoint takes a version field.

First, updating a customer record requires the request to carry `expected_customer_version`, holding the customer `version` the client last observed. If another writer has advanced the customer's `version` since that read — for example because a delivery cascaded a `bottles_on_site` update onto the account — the value will no longer match and the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an account state it has not observed.

Second, recording a delivery against a stop requires the request to carry `expected_route_version`, holding the parent route's `version` as last observed by the driver. Because every delivery, skip, or failure on a route mutates the route's `committed_bottles` and bumps the route's `version`, a stale value signals that the driver's view of the route is out of date, and the delivery is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Bottle Custody and Deposit Liability

The bottle custody ledger is the system's memory of where every five-gallon bottle physically sits. Each ledger entry records a `customer_ref` identifying the customer whose custody changed, an optional `stop_id` linking the entry to the stop that caused it (absent for manual adjustments), an `entry_kind` classifying the movement, a signed `quantity` (positive adds custody to the customer, negative removes it), and a server-recorded `occurred_at` timestamp used as the chronological tie-break when entries are replayed. The recognized movement kinds are `DELIVER_FULL`, `PICKUP_EMPTY`, `MARK_SHORTAGE`, `ADJUSTMENT`, `RETURN_FULL`, and `EXCHANGE`.

From this ledger the system derives two customer-level figures. The `bottles_on_site` count reflects how many full or owed bottles currently sit with the customer and is recomputed on every delivery, every exchange pickup, and every shortage marking. The `deposit_liability_cents` figure is purely derived, never independently stored: it is the customer's current `bottles_on_site` multiplied by the per-bottle deposit in the active pricing configuration. Both figures appear whenever the customer record is read.

## 3. Business Logic & Workflows

### 3.1. Pricing Configuration and Delivery Zones

Everything the billing engine charges traces back to a **PricingConfig**. An `OpsAdmin` authors one by supplying the `effective_from` date from which it applies, the refundable per-bottle `bottle_deposit_cents`, the non-return `bottle_shortage_fee_cents` (which must be at least the deposit, so a shortage never costs the customer less than the deposit refund they forfeit), the three per-bottle rates — `standard_per_bottle_cents`, `silver_per_bottle_cents`, and `gold_per_bottle_cents` — the two monthly volume thresholds `silver_volume_threshold` and `gold_volume_threshold` that drive automatic tier upgrades, and the `late_fee_flat_cents` charged once when an invoice first goes overdue. All five money fields must be strictly positive except the late fee, which may be zero, and the two volume thresholds must also be strictly positive. Configurations tile time as half-open intervals: a config governs from its `effective_from` up to, but not including, the `effective_from` of the next one. Because `SILVER` must trigger before `GOLD`, the gold threshold must be strictly greater than the silver threshold; a configuration violating that ordering, or carrying non-positive amounts, is rejected with `ERR_INVALID_PRICING_CONFIG`.

The delivery geography is organized into zones. A **DeliveryZone** is created by an `OpsAdmin` with a short unique `code` such as "NW-1" (a submission reusing an existing code is rejected with `ERR_INVALID_REQUEST`), a display `name`, and an `active` flag that defaults to true. Retiring a zone by clearing `active` stops new route assignment into it: creating a route in an inactive zone is rejected with `ERR_INVALID_REFERENCE`, and a route may only be published while its zone is active — but retirement does not disturb historical data. Zone listings, and the per-zone listings of customers and routes, support the standard pagination parameters.

### 3.2. Customer Accounts and Their Lifecycle

An `OpsAdmin` registers each customer with an `account_type` of `OFFICE` or `HOME`, a `business_name` (the company name for offices, a household label for homes), a `billing_email` for invoice delivery, a `service_address`, and the `delivery_zone_id` of the zone that will serve them; an unresolvable zone reference is rejected with `ERR_INVALID_REFERENCE`. Two optional fields shape service. The `service_mode` is `AUTO` for recurring scheduled delivery or `WILL_CALL` for on-demand ordering, defaulting to `AUTO`. The `par_level_bottles` is the target bottle inventory an `AUTO` customer keeps on site, defaulting to 2 and never negative. A `pricing_tier` of `STANDARD`, `SILVER`, or `GOLD` may be assigned at registration and defaults to `STANDARD`.

New accounts begin `ACTIVE` with `bottles_on_site` at zero. Two further fields are computed rather than stored from input: `outstanding_balance_cents`, which aggregates what the customer currently owes (defined in §3.8), and `overdue_since`, the timestamp at which the customer first slipped into an overdue posture, which stays null while no overdue invoices exist. Customer listings support filtering by `account_status` and `delivery_zone_id` alongside the standard pagination parameters.

Account maintenance goes through the same door. An `OpsAdmin` may change `business_name`, `service_address`, `par_level_bottles`, `pricing_tier`, or `service_mode` while the account stands in `ACTIVE` or `SUSPENDED` (an update attempted on a `CLOSED` account is rejected with `ERR_ALREADY_TERMINAL`), subject to the optimistic-concurrency rule in §2.9 — the request must carry `expected_customer_version` matching the account's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. A successful update increments the customer `version` by exactly one.

Non-payment is the one path to suspension. An `OpsAdmin` may suspend an account only while it is `ACTIVE` and only while `outstanding_balance_cents` is positive; attempting to suspend a paid-up account violates the business rule behind `ERR_OUTSTANDING_BALANCE`. Suspension is a hard stop with cascading consequences: every work order still `PENDING` for the customer is cancelled, every `PLANNED` stop for the customer on a route whose `service_date` is the current logical date or later is cancelled (releasing its bottles from the route's commitment), and the customer's `updated_at` refreshes while `version` increments. Reinstatement returns a `SUSPENDED` account to `ACTIVE`, but only once `outstanding_balance_cents` has returned to zero — the debt must actually be cleared, not merely promised.

Closure is the terminal act and is gated on a clean exit. From `ACTIVE`, closure requires `outstanding_balance_cents` at zero (otherwise `ERR_OUTSTANDING_BALANCE`), `bottles_on_site` at zero (otherwise `ERR_BOTTLES_OUTSTANDING`), and no cooler rental standing in `INSTALLED`, `SUSPENDED`, or `RETURN_REQUESTED` (a standing rental is rejected with `ERR_INVALID_STATE`); a clean closure cancels every add-on on the account and voids every `DRAFT` or `OPEN` invoice. From `SUSPENDED`, closure requires the same zero balance and zero bottles, and cancels the account's add-ons. Either way the account lands in `CLOSED` with its `updated_at` refreshed and `version` incremented, and `CLOSED` is terminal.

### 3.3. Planning Routes and Stops

A **Route** is the dispatcher's unit of work: one truck, one day, one zone. A `Dispatcher` creates one with a `zone_id`, the `service_date` on which the truck rolls, the `driver_name`, and the `truck_capacity_bottles` — the maximum full bottles the truck can carry, which must be positive. A route's `service_date` must not lie in the past relative to the logical clock, and a malformed or backward-reaching date is rejected with `ERR_INVALID_DATE_RANGE`. New routes are born in `DRAFT` with `committed_bottles` at zero; route listings may be filtered by `service_date`, `route_status`, or `zone_id`.

Stops fill the route. A `Dispatcher` plans a stop while the route stands in `DRAFT` or `PUBLISHED` by naming the `customer_id` and a `sequence_index` — a positive integer giving the stop's order on the route, unique within that route; reusing an index is rejected with `ERR_DUPLICATE_SEQUENCE`. The system then computes the plan. For an `AUTO` customer, `planned_bottles` is the gap between target and reality: the customer's `par_level_bottles` minus their current `bottles_on_site`, floored at zero, measured at plan time. For a `WILL_CALL` customer the plan comes from the work order that generated the stop — manual stop planning without a work order is not meaningful for on-demand accounts and is refused with `ERR_INVALID_REQUEST`. The `planned_empties_pickup` defaults to `planned_bottles`, enforcing exchange parity: the driver expects to collect one empty for every full bottle dropped. Each stop is born in `PLANNED` with `actual_bottles_delivered`, `actual_empties_collected`, and `shortage_count` all at zero, and its arrival increments the route's `committed_bottles` by `planned_bottles` and bumps the route `version`.

The truck is a hard ceiling. A route's `committed_bottles` — the sum of `planned_bottles` across its stops standing in `PLANNED`, `EN_ROUTE`, or `ARRIVED` — must never exceed `truck_capacity_bottles`. Any stop insertion or work-order scheduling that would push the commitment over capacity is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. Skips, cancellations, deliveries, and failures all release their stop's planned bottles back out of the commitment.

A route comes alive in stages. Publishing moves `DRAFT` to `PUBLISHED` and requires at least one `PLANNED` stop on the route and an `active` zone; it also bumps the route `version`. When the day arrives, the driver starts the route — permitted only once the logical clock's current date has reached the `service_date` — moving it from `PUBLISHED` to `IN_PROGRESS` and cascading every `PLANNED` stop to `EN_ROUTE`. Completion moves `IN_PROGRESS` to `COMPLETED`, but only once every stop on the route has reached a terminal state — `DELIVERED`, `PARTIAL`, `SKIPPED`, `FAILED`, or `CANCELLED`. Completion itself writes no billing records; the charges for `DELIVERED` and `PARTIAL` stops are picked up later, when an invoice is drafted for the covering period per §3.8. A `Dispatcher` may also cancel a route from `DRAFT` or `PUBLISHED`; cancellation moves every stop not already in a terminal state to `CANCELLED` (terminal stops are left untouched) and resets `committed_bottles` to zero. Each publish, start, complete, and cancel bumps the route `version`.

### 3.4. Running the Route: Arrival, Delivery, Shortage, and Failure

Once the route is rolling, the driver works each stop. Arrival moves a stop from `EN_ROUTE` to `ARRIVED`. From there the driver records the drop, and the record must carry three things: `actual_bottles_delivered`, `actual_empties_collected`, and — per §2.9 — `expected_route_version` matching the route's current `version`. Both actuals must be non-negative integers, and an `actual_bottles_delivered` greater than the stop's `planned_bottles` is rejected with `ERR_INVALID_REQUEST`. If another stop on the same route was just delivered and advanced the route `version` through the commitment-release side effect, the driver's stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) before any bottle movement is written.

A clean exchange — `actual_bottles_delivered` exactly equal to `planned_bottles`, and `actual_empties_collected` at least equal to `planned_empties_pickup` (collecting more empties than planned still counts as clean) — moves the stop `ARRIVED` to `DELIVERED`. When bottles delivered fall short of plan, or fewer empties than planned come back, the stop instead lands in `PARTIAL`: the recorded `shortage_count` is the number of empties owed but not returned, computed as `planned_empties_pickup` minus `actual_empties_collected` and floored at zero (a clean exchange records `shortage_count` zero). Either way the system records the actuals on the stop and writes the custody trail: a `DELIVER_FULL` entry crediting the customer with the bottles dropped, a `PICKUP_EMPTY` entry removing the empties collected, and — for a partial with shortages — a `MARK_SHORTAGE` entry for the missing count, which keeps those bottles in the customer's custody but flags them as owed. Entries are only written for non-zero quantities: a delivery of zero bottles writes no `DELIVER_FULL`, a collection of zero empties writes no `PICKUP_EMPTY`, and a zero shortage writes no `MARK_SHORTAGE`. The customer's `bottles_on_site` is then recomputed from the ledger (and, for a clean delivery, `deposit_liability_cents` is recomputed with it), while the route releases the stop's `planned_bottles` from `committed_bottles` and bumps its `version`.

Delivery is what turns bottles into money. When a stop lands in `DELIVERED` or `PARTIAL`, the water charge is the per-bottle rate for the customer's `pricing_tier` — drawn from the pricing configuration in effect on the route's `service_date`, so `STANDARD` accounts pay `standard_per_bottle_cents`, `SILVER` accounts pay `silver_per_bottle_cents`, and `GOLD` accounts pay `gold_per_bottle_cents` — multiplied by `actual_bottles_delivered`. Because the rate is already whole cents, no rounding is ever needed. Planning shows a provisional figure computed the same way but against `planned_bottles`; that projection lives only in a projected-charges cache, is never persisted to an invoice, and is discarded the moment the actuals-based charge is written. Stop listings across routes may be filtered by `route_id`, `customer_id`, or `stop_status`.

Not every stop ends in a drop. From `EN_ROUTE` or `ARRIVED` the driver may mark a stop `FAILED` — a gate-locked building, a refused delivery — which releases the stop's planned bottles from the route commitment and bumps the route `version`, without touching custody or credits. A stop can also be cancelled out of `PLANNED` by the system when its parent route is cancelled or its customer is suspended, again releasing the commitment.

### 3.5. Skipped Stops and Skip Credits

Skipping is the polite failure: the customer asked to be passed by, or the driver judges delivery pointless. A skip is accepted from `PLANNED`, `EN_ROUTE`, or `ARRIVED`, and it always requires a non-empty `skip_reason`; an empty explanation is rejected with `ERR_SKIP_REASON_REQUIRED`. The skip request may also carry `notified_before_cutoff`, defaulting to false when omitted, recording whether the customer gave notice at least 24 hours before the route's `service_date` start. The cutoff is inclusive — notice landing exactly at the 24-hour mark counts as before the cutoff. A successful skip returns the updated stop object.

Every skip creates a **SkipCredit** for the stop's customer, and its size depends on that notice flag. The projected charge for the skipped stop is `planned_bottles` multiplied by the per-bottle rate for the customer's tier in the pricing configuration in effect on the route's `service_date`. With timely notice the `credit_cents` equal the full projected charge; without it the credit is half the projected charge, rounded half-up to a whole cent. Each credit carries a `stop_id` pointing back at the skipped stop, begins life with `credit_status` at `PENDING`, and is stamped with an `expires_at` exactly 90 days after creation.

A credit is redeemed when a `BillingAdmin` applies it. Applying requires the credit to still be `PENDING` and the logical clock to be earlier than `expires_at` — a credit past its expiry is rejected with `ERR_CREDIT_EXPIRED`. If the customer has a `DRAFT` invoice, the earliest-created one absorbs the credit immediately, its `total_due_cents` and `balance_due_cents` each reduced by the credit amount; if no `DRAFT` exists yet, no invoice is created at apply time — the credit moves to `APPLIED` and is instead absorbed automatically, again as a negative amount, the next time an invoice is drafted for the customer (§3.8). Credits that outlive their welcome expire automatically: once the logical clock reaches `expires_at`, a `PENDING` credit flips to `EXPIRED` with no further effect. An `OpsAdmin` may also revoke a `PENDING` credit outright, moving it to `REVOKED`. A skip, like any terminal stop event, releases the stop's planned bottles from the route commitment and bumps the route `version`.

### 3.6. Work Orders and Cooler Rentals

On-demand service enters the system as a **WorkOrder**, raised by the customer (`CustomerSelf`) or by a `Dispatcher` on their behalf, with a `customer_id`, an `order_kind`, a `requested_date`, and a `quantity_bottles` that is never negative; a `CustomerSelf` raising an order whose `customer_id` is not their own `X-User-ID` is rejected with `ERR_FORBIDDEN`. The recognized kinds are `DELIVERY`, `COOLER_INSTALL`, `COOLER_RETURN`, `PICKUP_ONLY`, and `EXCHANGE_ONLY`; for delivery and exchange orders `quantity_bottles` counts full five-gallon bottles, while for a pickup-only order it counts empties. Work orders are born `PENDING` with `linked_stop_id` and `linked_rental_id` both null, and the work-order listing supports filtering by `customer_id`, `order_status`, `order_kind`, `linked_stop_id`, and `linked_rental_id`.

Scheduling is the dispatcher's commit. A `PENDING` order may be scheduled only while the customer is `ACTIVE`. For `DELIVERY`, `EXCHANGE_ONLY`, and `PICKUP_ONLY` orders, scheduling requires a route already existing on the `requested_date` in the zone matching the customer's `delivery_zone_id`, with that route still in `DRAFT` or `PUBLISHED` — when several routes match, the earliest-created one is chosen, and when none matches the scheduling is rejected with `ERR_INVALID_REFERENCE`. Scheduling then creates a stop on that route, sets the order's `linked_stop_id`, and adds the planned bottles to the route's `committed_bottles` — subject to the same truck-capacity ceiling, so an over-capacity schedule is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. For `DELIVERY` and `EXCHANGE_ONLY` the stop's `planned_bottles` and `planned_empties_pickup` both equal the order's `quantity_bottles`; for `PICKUP_ONLY` the stop is planned with `planned_bottles` zero and `planned_empties_pickup` equal to `quantity_bottles`, so a pickup-only order consumes no truck capacity. For a `COOLER_INSTALL` order, scheduling instead requires the rental referenced by `linked_rental_id` to be standing in `PENDING_INSTALL` (otherwise `ERR_INVALID_STATE`); for a `COOLER_RETURN` order it requires that rental to be standing in `RETURN_REQUESTED` (otherwise `ERR_INVALID_STATE`); cooler work creates no stop and rides the rental lifecycle instead. Once scheduled, an order moves to `IN_PROGRESS` automatically when its linked route starts rolling or when the driver begins the install, and it completes automatically when its linked stop reaches `DELIVERED` or `PARTIAL`, or its linked rental reaches `INSTALLED` or `RETURNED`.

Cancellation is a customer prerogative while the work is still young: the customer or a dispatcher may cancel an order in `PENDING` or `SCHEDULED`, and when a linked stop is still `PLANNED` it is cancelled too, releasing its bottles from the route commitment. A `Dispatcher` may also reject a `PENDING` order outright, moving it to `REJECTED`. Customer-self cancellation is ownership-checked per §2.1 — a customer touching an order whose `customer_id` is not their own `X-User-ID` is rejected with `ERR_FORBIDDEN`.

Cooler rentals braid into this flow. A rental is requested by an `OpsAdmin` or the customer with a `customer_id`, a `cooler_model` of `COUNTERTOP`, `FREESTANDING`, `BOTTOM_LOAD`, or `FILTRATION_POE`, a non-negative `monthly_rent_cents`, and a one-time non-negative `deposit_cents` held as a liability. Creation immediately spawns a linked work order of kind `COOLER_INSTALL` — stamped with the current logical date as its `requested_date` and a `quantity_bottles` of zero — and the rental stands in `PENDING_INSTALL` with `installed_at` and `returned_at` null and `accrued_rent_cents` at zero.

Installation happens in the field: the driver marks the rental installed — allowed only while the customer is `ACTIVE` and the linked work order stands `SCHEDULED` or `IN_PROGRESS` (the driver beginning the install is itself what carries a still-`SCHEDULED` order forward) — which stamps `installed_at` from the logical clock and completes the linked work order. From `INSTALLED`, an `OpsAdmin` may suspend the rental — its `rental_status` moving to `SUSPENDED` — to pause rent accrual, and later resume it back to `INSTALLED`, restarting accrual from that moment. The customer initiates the off-ramp: requesting a return moves the rental from `INSTALLED` to `RETURN_REQUESTED` and spawns a work order of kind `COOLER_RETURN` linked to the rental; this is a self-service action, so an `X-User-ID` that does not match the rental's `customer_id` is rejected with `ERR_FORBIDDEN`. The driver then confirms the physical return, moving `RETURN_REQUESTED` to `RETURNED`: `returned_at` is stamped, a final prorated rent is computed up to the return instant, the `deposit_cents` becomes refundable and is applied as a deposit credit on the customer's next invoice, and the linked work order completes provided it still stands `SCHEDULED` or `IN_PROGRESS`. Finally, an `OpsAdmin` closes a `RETURNED` rental, moving it to `CLOSED`; no billing-state gate applies — any `RETURNED` rental may be closed. Both `RETURNED` and `CLOSED` are terminal outcomes for a rental, with `CLOSED` the administrative end state.

### 3.7. Add-On Services

Add-ons attach recurring or one-shot extras to an account. An `OpsAdmin` or the customer creates one with a `customer_id`, an `addon_kind` of `COFFEE`, `FILTRATION`, `CUPS`, or `SANITIZATION`, a `quantity` of at least 1 (bags of coffee, filter kits, and the like), a non-negative `unit_price_cents`, and a `cadence` of `RECURRING` or `ONE_TIME` that defaults to `RECURRING`. Add-ons are born with `addon_status` at `ACTIVE`. The customer manages their own extras from there — pausing an `ACTIVE` add-on to `PAUSED`, resuming a `PAUSED` one back to `ACTIVE`, or cancelling from either `ACTIVE` or `PAUSED` into the terminal `CANCELLED` state — and each of these self-service actions enforces the ownership check, rejecting cross-account touches with `ERR_FORBIDDEN`. Add-ons feed the billing engine: a `RECURRING` add-on is charged once per billing period, but only while it stands `ACTIVE` — a `PAUSED` or `CANCELLED` recurring add-on contributes nothing — while a `ONE_TIME` add-on is charged only in the period of its purchase, and only if it has not been `CANCELLED`. Each charge is `quantity` multiplied by `unit_price_cents`.

### 3.8. Invoicing, Payments, and Account Standing

Billing is a `BillingAdmin` domain. An invoice is drafted for a customer with a `billing_period_start`, a `billing_period_end`, and a `due_date`. The period is a half-open interval — it includes the start date and excludes the end date — and an end that does not fall strictly after the start is rejected with `ERR_INVALID_DATE_RANGE`. Drafting computes the whole shape of the bill. The `subtotal_water_cents` aggregates the per-stop water charges (per §3.4) for the customer's stops in the period that reached `DELIVERED` or `PARTIAL`, each priced at the per-bottle rate for the customer's `pricing_tier` as it stands when the invoice is drafted, drawn from the configuration in effect on the stop's service date. The `subtotal_addon_cents` collects add-on charges per §3.7. The `subtotal_rent_cents` prorates cooler rent, as detailed below. The `shortage_charge_cents` totals shortage events: for every stop in the period that finished `PARTIAL` with a positive `shortage_count`, the count is multiplied by the `bottle_shortage_fee_cents` from the configuration in effect on the stop's service date, and because the shortage fee is never less than the deposit, a shortage always costs at least the deposit refund that was forfeited. The `deposit_credit_cents` refunds deposits for net returned bottles, also detailed below, and additionally absorbs the `deposit_cents` of any cooler rental already returned and not yet credited on an earlier invoice; it is never negative. The `total_due_cents` is the water, add-on, and rent subtotals plus the shortage charge, minus the deposit credit, and minus any skip credits standing `APPLIED` for the customer that have not yet been absorbed by an earlier invoice (per §3.5); every input is already a whole-cent integer, so no rounding step ever fires. Finally `balance_due_cents` starts equal to the total due — no payments can exist against a brand-new draft — and `issued_at` stays null while the invoice sits in `DRAFT`.

Prorated rent follows a daily rhythm. For each rental that stands `INSTALLED`, `SUSPENDED`, or `RETURN_REQUESTED` at period end, or whose `returned_at` falls inside the period, the daily rate is the `monthly_rent_cents` multiplied by twelve — the months in a year — and divided by 365, the days in a year, rounded half-up to a whole cent at that daily-rate step. The rental's accrual for the period is that daily rate multiplied by the number of days in the half-open billing window on which the rental stood `INSTALLED` (a day in `RETURN_REQUESTED` also accrues, since the cooler is still on site); suspended days accrue zero. The install day counts as a full accrual day, and when a return day falls inside the period it likewise counts as a full accrual day, because the cooler was installed at some point that day — the alternative, treating the return day as free, would undercharge by one day and is explicitly rejected. The `subtotal_rent_cents` is the sum of these per-rental accruals, and a rental's `accrued_rent_cents` field caches the running figure between its `installed_at` and the current clock on each billing run.

The deposit refund works on net movement, never per event. Walking the customer's custody ledger in strict chronological order — `occurred_at` ascending, ties broken by `created_at` ascending — the system establishes `bottles_on_site` at the period start and again at the period end. The net returned count is the opening count minus the closing count, floored at zero, and the `deposit_credit_cents` is that net count multiplied by the `bottle_deposit_cents` from the configuration in effect at period end. Refunding at each individual pickup event is explicitly not the rule: under exchange parity a customer's count often stays flat while empties flow back, and per-event refunding would pay out deposits that were never truly returned, double-refunding against full-bottle deliveries in the same period.

Issuing moves an invoice from `DRAFT` to `OPEN`, requires a positive `total_due_cents` (a non-positive total is rejected with `ERR_INVALID_STATE`), stamps `issued_at` from the logical clock, and refreshes the customer's `outstanding_balance_cents`. Issuing also looks forward: the bottles the customer actually took in the period just closed — the sum of `actual_bottles_delivered` across their `DELIVERED` and `PARTIAL` stops with service dates inside the half-open billing window — are compared against the thresholds of the pricing configuration in effect at `billing_period_end`, and a count meeting or exceeding `gold_volume_threshold` earns `GOLD`, meeting or exceeding `silver_volume_threshold` earns `SILVER`, and anything less earns `STANDARD`, with the thresholds inclusive and the new `pricing_tier` taking effect for the next period only, since the current period has already been billed at the prior tier.

A customer's `outstanding_balance_cents` is always the sum of `balance_due_cents` across their invoices standing in `OPEN`, `OVERDUE`, `PARTIALLY_PAID`, or `DISPUTED`, recomputed on every invoice state change and every payment application or refund. Time works against the unpaid: when the logical clock passes an `OPEN` invoice's `due_date` while its `balance_due_cents` remains positive, the invoice flips to `OVERDUE`, the `late_fee_flat_cents` is charged once onto its `total_due_cents` (and therefore its balance), and the customer's `overdue_since` is set if not already set.

Payments enter as records against an invoice — an `invoice_id`, a positive `amount_cents`, and a `method` of `CARD`, `ACH`, `CHECK`, or `CREDIT_MEMO` — created by a `BillingAdmin` or the customer and born with `payment_status` at `PENDING`. Application is where money moves: a `PENDING` payment may be applied only while its invoice stands in `OPEN`, `OVERDUE`, `PARTIALLY_PAID`, or `DISPUTED`, and its `amount_cents` may not exceed the invoice's `balance_due_cents` — an overlarge application is rejected with `ERR_OVERPAYMENT`. A successful application stamps `applied_at`, reduces the invoice balance by the payment amount, and lets the invoice follow the money: an applied amount smaller than the balance moves an `OPEN` or `OVERDUE` invoice to `PARTIALLY_PAID` (a partial application against a `DISPUTED` invoice reduces the balance but leaves the invoice `DISPUTED`), while an amount that covers the balance in full moves the invoice to `PAID` from `OPEN`, `OVERDUE`, `PARTIALLY_PAID`, or `DISPUTED`, zeroing its balance. When an invoice is paid and the customer holds no other `OPEN` or `OVERDUE` invoices, `overdue_since` clears. Every application recomputes the customer's outstanding balance. A payment that will never clear is marked `FAILED` from `PENDING`; a payment already `APPLIED` against a `PAID` invoice may be refunded — its `payment_status` moving to the terminal `REFUNDED` state — which returns the amount to the invoice's balance, reopens the invoice from `PAID` back to `OPEN`, and again recomputes the customer's standing.

Disputes pause the collection machinery. The customer may dispute an invoice standing in `OPEN` or `PARTIALLY_PAID` — any other source state is rejected with `ERR_INVALID_STATE`, and cross-account disputes earn `ERR_FORBIDDEN` — moving it to `DISPUTED`, where the clock-driven slide into `OVERDUE` is suppressed. Resolution is a `BillingAdmin` decision expressed as an `outcome`: `RESTORE` returns the invoice to `OPEN` with its balance intact, while `VOID` zeroes the `balance_due_cents`, drops the invoice into the terminal `VOID` state, and refreshes the customer's outstanding balance. A `BillingAdmin` may also void an invoice directly, but only while it is still a `DRAFT`. Invoice listings may be filtered by `customer_id` and `invoice_status`, and each invoice exposes the list of payments recorded against it.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, a route, a stop on a route, a pricing configuration, a zone, a work order, a cooler rental, an add-on, an invoice, or a payment — return `201 Created`. Operations that act on an existing resource, including every state-transition action, return `200 OK`. The clock-setting capability also returns `200 OK`. All paths below are relative to the `/api/v1` mount.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/_clock/set_current_utc` | Set the logical clock (server starts at 2026-05-01T00:00:00Z and never uses the wall clock) | OpsAdmin |
| POST | `/api/v1/pricing-configs` | Create a pricing configuration | OpsAdmin |
| GET | `/api/v1/pricing-configs` | List pricing configs | OpsAdmin, BillingAdmin, Dispatcher |
| GET | `/api/v1/pricing-configs/{id}` | Get one pricing config | OpsAdmin, BillingAdmin, Dispatcher |
| POST | `/api/v1/delivery-zones` | Create a delivery zone | OpsAdmin |
| GET | `/api/v1/delivery-zones` | List zones | OpsAdmin, Dispatcher, Driver, BillingAdmin |
| GET | `/api/v1/delivery-zones/{id}` | Get one zone | OpsAdmin, Dispatcher, Driver, BillingAdmin |
| GET | `/api/v1/delivery-zones/{id}/customers` | List customers in a zone | OpsAdmin, Dispatcher, BillingAdmin |
| GET | `/api/v1/delivery-zones/{id}/routes` | List routes in a zone | OpsAdmin, Dispatcher, Driver |
| POST | `/api/v1/customers` | Register a new customer account | OpsAdmin |
| GET | `/api/v1/customers` | List customers | OpsAdmin, Dispatcher, BillingAdmin |
| GET | `/api/v1/customers/{id}` | Get one customer (with computed outstanding balance, bottles on site, deposit liability) | OpsAdmin, Dispatcher, BillingAdmin, CustomerSelf |
| PATCH | `/api/v1/customers/{id}` | Update customer fields (OCC via expected_customer_version) | OpsAdmin |
| POST | `/api/v1/customers/{id}/suspend` | Suspend account for non-payment | OpsAdmin |
| POST | `/api/v1/customers/{id}/reinstate` | Reinstate a suspended customer | OpsAdmin |
| POST | `/api/v1/customers/{id}/close` | Close account; requires zero balance and zero bottles on site | OpsAdmin |
| GET | `/api/v1/customers/{id}/cooler-rentals` | List a customer's cooler rentals | OpsAdmin, Dispatcher, BillingAdmin, Driver, CustomerSelf |
| GET | `/api/v1/customers/{id}/addons` | List a customer's addons | OpsAdmin, BillingAdmin, CustomerSelf |
| GET | `/api/v1/customers/{id}/invoices` | List a customer's invoices | OpsAdmin, BillingAdmin, CustomerSelf |
| GET | `/api/v1/customers/{id}/work-orders` | List a customer's work orders | OpsAdmin, Dispatcher, CustomerSelf, Driver |
| GET | `/api/v1/customers/{id}/bottle-custody-ledger` | List custody ledger entries for a customer | OpsAdmin, BillingAdmin, CustomerSelf |
| GET | `/api/v1/customers/{id}/skip-credits` | List a customer's skip credits | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/routes` | Create a route | Dispatcher |
| GET | `/api/v1/routes` | List routes | OpsAdmin, Dispatcher, Driver |
| GET | `/api/v1/routes/{id}` | Get one route | OpsAdmin, Dispatcher, Driver |
| POST | `/api/v1/routes/{id}/publish` | Publish a DRAFT route | Dispatcher |
| POST | `/api/v1/routes/{id}/start` | Start a route (PUBLISHED to IN_PROGRESS) | Driver |
| POST | `/api/v1/routes/{id}/complete` | Complete a route (all stops terminal) | Driver |
| POST | `/api/v1/routes/{id}/cancel` | Cancel a route | Dispatcher |
| GET | `/api/v1/routes/{id}/stops` | List stops on a route | OpsAdmin, Dispatcher, Driver |
| POST | `/api/v1/routes/{id}/stops` | Manually plan a stop on a route | Dispatcher |
| GET | `/api/v1/stops` | List stops across routes | OpsAdmin, Dispatcher, Driver |
| GET | `/api/v1/stops/{id}` | Get one stop | OpsAdmin, Dispatcher, Driver |
| GET | `/api/v1/stops/{id}/bottle-custody-ledger` | List custody ledger entries tied to a stop | OpsAdmin, Dispatcher, BillingAdmin |
| GET | `/api/v1/stops/{id}/skip-credits` | List skip credits generated by this stop | OpsAdmin, Dispatcher, BillingAdmin |
| POST | `/api/v1/stops/{id}/arrive` | Driver arrives at a stop (EN_ROUTE to ARRIVED) | Driver |
| POST | `/api/v1/stops/{id}/deliver` | Record a delivery (ARRIVED to DELIVERED or PARTIAL); OCC via expected_route_version | Driver |
| POST | `/api/v1/stops/{id}/skip` | Skip a stop | Driver |
| POST | `/api/v1/stops/{id}/fail` | Mark a stop failed | Driver |
| POST | `/api/v1/work-orders` | Create a work order (will-call delivery, cooler install/return, etc.) | CustomerSelf, Dispatcher |
| GET | `/api/v1/work-orders` | List work orders | OpsAdmin, Dispatcher, Driver |
| GET | `/api/v1/work-orders/{id}` | Get one work order | OpsAdmin, Dispatcher, Driver, CustomerSelf |
| POST | `/api/v1/work-orders/{id}/schedule` | Schedule a PENDING work order onto a route (creates a stop for delivery kinds) | Dispatcher |
| POST | `/api/v1/work-orders/{id}/cancel` | Cancel a work order | CustomerSelf, Dispatcher |
| POST | `/api/v1/work-orders/{id}/reject` | Reject a work order | Dispatcher |
| POST | `/api/v1/cooler-rentals` | Request a new cooler rental | OpsAdmin, CustomerSelf |
| GET | `/api/v1/cooler-rentals/{id}` | Get one cooler rental | OpsAdmin, Dispatcher, Driver, CustomerSelf, BillingAdmin |
| POST | `/api/v1/cooler-rentals/{id}/install` | Mark a cooler installed (linked work order must be IN_PROGRESS) | Driver |
| POST | `/api/v1/cooler-rentals/{id}/suspend` | Pause rent accrual | OpsAdmin |
| POST | `/api/v1/cooler-rentals/{id}/resume` | Resume rent accrual | OpsAdmin |
| POST | `/api/v1/cooler-rentals/{id}/request-return` | Customer requests a return (creates a COOLER_RETURN work order) | CustomerSelf |
| POST | `/api/v1/cooler-rentals/{id}/confirm-return` | Confirm a cooler returned | Driver |
| POST | `/api/v1/cooler-rentals/{id}/close` | Close out a returned rental | OpsAdmin |
| POST | `/api/v1/addons` | Add a recurring or one-time addon to a customer | OpsAdmin, CustomerSelf |
| GET | `/api/v1/addons/{id}` | Get one addon | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/addons/{id}/pause` | Pause an addon | CustomerSelf |
| POST | `/api/v1/addons/{id}/resume` | Resume an addon | CustomerSelf |
| POST | `/api/v1/addons/{id}/cancel` | Cancel an addon | CustomerSelf |
| POST | `/api/v1/invoices` | Create a DRAFT invoice for a customer for a billing period | BillingAdmin |
| GET | `/api/v1/invoices` | List invoices | OpsAdmin, BillingAdmin |
| GET | `/api/v1/invoices/{id}` | Get one invoice | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/invoices/{id}/issue` | Issue a DRAFT invoice (DRAFT to OPEN); fires the automatic tier upgrade | BillingAdmin |
| POST | `/api/v1/invoices/{id}/dispute` | Customer disputes an OPEN or PARTIALLY_PAID invoice | CustomerSelf |
| POST | `/api/v1/invoices/{id}/resolve-dispute` | Resolve a dispute | BillingAdmin |
| POST | `/api/v1/invoices/{id}/void` | Void a DRAFT invoice | BillingAdmin |
| GET | `/api/v1/invoices/{id}/payments` | List payments against an invoice | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/payments` | Record a payment against an invoice | BillingAdmin, CustomerSelf |
| GET | `/api/v1/payments/{id}` | Get one payment | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/payments/{id}/apply` | Apply a PENDING payment | BillingAdmin |
| POST | `/api/v1/payments/{id}/mark-failed` | Mark a PENDING payment failed | BillingAdmin |
| POST | `/api/v1/payments/{id}/refund` | Refund an APPLIED payment | BillingAdmin |
| GET | `/api/v1/skip-credits/{id}` | Get one skip credit | OpsAdmin, BillingAdmin, CustomerSelf |
| POST | `/api/v1/skip-credits/{id}/apply` | Apply a PENDING skip credit to the next invoice | BillingAdmin |
| POST | `/api/v1/skip-credits/{id}/revoke` | Revoke a PENDING skip credit | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_DUPLICATE_SEQUENCE` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 422 |
| `ERR_BOTTLES_OUTSTANDING` | 422 |
| `ERR_SKIP_REASON_REQUIRED` | 400 |
| `ERR_CREDIT_EXPIRED` | 422 |
| `ERR_INVALID_PRICING_CONFIG` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ALREADY_TERMINAL` | 409 |
