# Chauffeured Limousine Dispatch API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Chauffeured Limousine Dispatch API, the back-office operating system for a black-car operator. Dispatchers, corporate booking agents, affiliate partners, and the chauffeurs themselves all coordinate around a single shared object — the reservation — as it travels from an initial quote, through confirmation and resource assignment, to the moment a passenger is dropped and the trip is settled. The system must speak fluently about the realities of premium ground transportation: point-to-point and hourly charters, airport pickups whose timing is hostage to flight delays, meet-and-greet service inside the terminal, gratuity and toll handling, affiliate farm-out when in-house capacity runs short, and a tiered cancellation policy that depends on how much lead time the operator was given.

Two pressures shape almost every rule in this specification. The first is **time**: chauffeurs and vehicles occupy windows that must not collide, rest and turnaround buffers must be respected, flight arrivals slide a confirmed window forward or back, and the lead time before a pickup decides whether a cancellation is free or penalized. The second is **money**: every reservation carries two distinct monetary stories — a forward-looking estimate stamped at quote time and a final settlement stamped at completion that folds in the actual wait — and a farm-out introduces a third figure entirely, the payout owed to the affiliate, computed on a different basis again. The API keeps the operational story (where is the car, who is driving, is the flight late) and the financial story (what was quoted, what is owed, what has been invoiced and settled) as two independent axes that advance on their own schedules. Getting both axes right, simultaneously and consistently, is the core problem this system solves.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API. The collections in this system are peers — there is no shared URL prefix — and each resource type is addressed at its own top-level path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `DispatchAdmin`, `Dispatcher`, `CorporateBooker`, `AffiliatePartner`, and `Chauffeur`.

`DispatchAdmin` is the operations superuser and an operational superset of `Dispatcher`. When `X-User-Role` is `DispatchAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The admin provisions configuration data (corporate accounts, affiliates, vehicle classes, vehicles, chauffeurs), suspends and reinstates resources, writes off invoices, and drives the deterministic test clock.

`Dispatcher` runs day-to-day operations: building and quoting reservations, confirming them, assigning chauffeurs and vehicles in-house, offering and recalling farm-outs, dispatching, completing, invoicing, and settling. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

`CorporateBooker` acts on behalf of exactly one corporate account. When `X-User-Role` is `CorporateBooker`, `X-User-ID` is the `id` of the acting `CorporateAccount`; any ownership check on a reservation compares the reservation's `corporate_account_id` to `X-User-ID`, so a booker may only read and act on reservations belonging to their own account. A booker who references a resource owned by another account is rejected with `ERR_FORBIDDEN`.

`AffiliatePartner` acts on behalf of exactly one affiliate operator. When `X-User-Role` is `AffiliatePartner`, `X-User-ID` is the `id` of the acting `Affiliate`; ownership checks on a farm-out offer compare the order's `affiliate_id` to `X-User-ID`, so a partner may only accept or reject offers addressed to their own affiliate.

`Chauffeur` acts on behalf of exactly one chauffeur. When `X-User-Role` is `Chauffeur`, `X-User-ID` is the `id` of the acting `Chauffeur`; ownership checks compare the relevant chauffeur reference (for example, the chauffeur assigned to the reservation being dispatched, or the `id` in a duty-event path) to `X-User-ID`, so a chauffeur may only clock themselves in and out and act on their own trips.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by `created_at` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` formatted as a UUID with no type prefix, and an `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits at the moment of creation.

Most resources additionally carry two system-managed fields. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource, and `version` is an integer that begins at its initial value and increments by one with every mutation, including mutations that only touch a computed field. These full-lifecycle resources are `CorporateAccount`, `Affiliate`, `VehicleClass`, `Vehicle`, `Chauffeur`, `Reservation`, `FlightTracking`, `Assignment`, and `FarmOutOrder`.

Three record types are deliberately leaner. `WaitEvent`, `CancellationRecord`, and `ClockState` carry only `id` and `created_at`; they have neither `updated_at` nor `version`. `WaitEvent` is an append-only log of pickup events, `CancellationRecord` is an immutable audit row written once when a reservation is cancelled, and `ClockState` is the singleton-like server clock used to make time-gated behavior deterministic.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several endpoints address a resource that lives under a parent in the URL path, and several creation endpoints carry foreign-key references in the request body. In all cases, identifiers are resolved left to right. The first identifier in a path that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` before any later identifier or body reference is examined; body-borne references (for example, a reservation's `corporate_account_id` and `vehicle_class_id`, or an assignment's `chauffeur_id` and `vehicle_id`) are likewise checked for existence, and any unresolved reference yields `ERR_NOT_FOUND`. This existence sweep is the third validation gate, after authentication and authorization but before request-body shape validation. Because relationships are navigated through filtered list endpoints rather than reverse pointers, a vehicle's class is discoverable by filtering vehicles on `vehicle_class_id`, a reservation's history is reachable through its account and class filters, and a chauffeur's current work is discoverable by filtering assignments on `chauffeur_id`.

### 2.6. Validation Ordering

When a single request could fail several checks, the checks are applied in a fixed priority order so the returned error is predictable. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first. Authorization, including the ownership tests for entity-backed roles (`ERR_FORBIDDEN`), is second. Existence of every referenced resource (`ERR_NOT_FOUND`) is third. Request-body well-formedness — required fields present with correct types and valid enum values (`ERR_INVALID_REQUEST`) — is fourth. Only after these four universal gates pass does the system evaluate the domain-specific rules described throughout §3, in the relative order called out where each rule is introduced.

### 2.7. Monetary Amounts, Rounding, and Time Precision

All money in the system is expressed as an integer number of cents. Wherever a calculation step is described as rounding, the system rounds half up to the nearest whole cent, and rounding is applied at each rounding step in the order the calculation specifies rather than only once at the end. Percentages (discount, gratuity, payout share) are applied as described and then rounded at their step. Durations derived from timestamps are computed in whole minutes by taking the total elapsed seconds and discarding any partial minute (a floor operation), so a partial minute never counts as a full one. Charter hours, where they apply, are rounded up to the next whole hour before billing.

### 2.8. Optimistic Concurrency on Reservation Fulfillment

A reservation can be fulfilled in exactly one of two mutually exclusive ways — assigned in-house or farmed out to an affiliate — and both creation paths are guarded against acting on a stale view of the reservation. The two fulfillment-creation operations each require a non-optional `expected_reservation_version` field in the request body, carrying the `version` of the target reservation that the client last observed.

When a `Dispatcher` creates an in-house assignment, the request must carry `expected_reservation_version` equal to the reservation's current `version`. If another writer has advanced that `version` since the client last read the reservation — most importantly, if a farm-out offer was accepted in the meantime, legitimately moving the reservation toward `FARMED_OUT` and `COMPLETED` and bumping its `version` — the create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing the dispatcher from overwriting a fulfillment decision they never saw.

Symmetrically, when a `Dispatcher` offers a reservation to an affiliate, the farm-out create must also carry `expected_reservation_version` equal to the reservation's current `version`. If an in-house assignment has advanced the reservation to `ASSIGNED` and bumped its `version` since the client's last read, the farm-out create is rejected with `ERR_STALE_VERSION` at HTTP 412. No other endpoint takes a version field; these are the only two OCC-guarded writes.

### 2.9. Cross-Entity Consistency and Computed Aggregates

Many operations in this system mutate more than one entity at once, and every such cascade is part of the operation's contract — never an incidental side effect. When a reservation is assigned, the chauffeur's duty status changes; when a trip completes or is cancelled, the chauffeur reverts and the assignment is released; when a farm-out is accepted, the reservation itself completes. Each entity touched by a cascade has its `updated_at` refreshed and its `version` incremented in its own right. The specific cascades are documented alongside the workflows that trigger them in §3.

Two aggregate fields are recomputed rather than set directly. A corporate account's `outstanding_balance_cents` is the sum, over that account's reservations whose `settlement_status` is `INVOICED`, of each reservation's billable amount — its `final_total_cents`, or its `cancellation_fee_cents` when `final_total_cents` is unset (as on an invoiced cancellation) — less amounts that have moved on to `SETTLED` or `WRITTEN_OFF` (which are excluded by virtue of no longer being `INVOICED`); it is refreshed whenever a billing event changes a reservation's settlement state. An affiliate's `open_farmouts` is the count of that affiliate's farm-out orders whose `status` is `OFFERED` or `ACCEPTED`; it is refreshed whenever a farm-out is offered or decided.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Operating Environment

Before any trip can be booked, a `DispatchAdmin` provisions the static fixtures of the operation. A **corporate account** is created with a `company_name` and a `billing_email`, and may carry three commercial parameters: a `negotiated_discount_pct` applied to the pre-gratuity, pre-tax fare base (defaulting to 0 and constrained to between 0 and 40 inclusive), a `default_gratuity_pct` auto-applied to that account's reservations (defaulting to 20 and constrained to between 0 and 30 inclusive), and a `cancellation_grace_minutes` lead-time window (defaulting to 120 and required to be zero or greater). Every account is born with `status` of `ACTIVE` and an `outstanding_balance_cents` of 0. An admin may later suspend an account, moving its `status` from `ACTIVE` to `SUSPENDED`; suspending an account that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

An **affiliate** operator is created with a `name`, a `market_code` (a service market such as SFO, JFK, or LAX), and a `payout_share_pct` — the percent of a reservation's fare base paid to the affiliate when a trip is farmed out, constrained to between 0 and 90 inclusive. Affiliates start `ACTIVE` with `open_farmouts` at 0, and an admin may suspend one to `SUSPENDED`, which blocks it from receiving new offers; suspending an affiliate that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

A **vehicle class** is the rate card for a tier of service. It is created with a `code` (such as SEDAN, SUV, SPRINTER, or STRETCH), a flat `base_fare_cents` charged on any point-to-point trip in the class, a `per_mile_cents` distance rate, an `hourly_rate_cents` charter rate, a `wait_per_minute_cents` charge for chargeable wait beyond the grace, and an `included_wait_minutes` grace that defaults to 15. All four rate fields and the wait grace must be zero or greater. A class starts `ACTIVE`. The `code` must be unique among all vehicle classes that are not `SUSPENDED`; a colliding code is rejected with `ERR_DUPLICATE_CLASS_CODE`.

A **vehicle** is created against a `vehicle_class_id` with a `plate` and an optional `turnaround_minutes` cleaning-and-refuel buffer that defaults to 30 and must be zero or greater. The `plate` must be unique across every vehicle in the system; a duplicate is rejected with `ERR_DUPLICATE_PLATE`. A vehicle's `status` is `AVAILABLE`, the only state in this version.

A **chauffeur** is created with a `full_name`, a `home_market_code`, and an optional `rest_buffer_minutes` mandatory rest gap that defaults to 20 and must be zero or greater. A new chauffeur begins `OFF_DUTY`, with `active_assignment_id` null. The range constraints on all percent inputs — discount within 0 to 40, gratuity (both `default_gratuity_pct` and a reservation's `gratuity_pct_override`) within 0 to 30, and payout share within 0 to 90 — are enforced at account, affiliate, and reservation creation respectively, and a value outside its band is rejected with `ERR_VALIDATION_RANGE`.

### 3.2. Booking a Reservation and Producing a Quote

A `Dispatcher` or a `CorporateBooker` opens a reservation, which is the spine of the whole system. Creation requires the `corporate_account_id` that owns it (in this version every reservation is corporate), a `trip_type` of `POINT_TO_POINT`, `HOURLY`, or `AIRPORT`, the requested `vehicle_class_id`, a `pickup_at` scheduled pickup time, and a `planned_drop_at`. The `planned_drop_at` must be strictly after `pickup_at`; otherwise the request is rejected with `ERR_INVALID_TIME_WINDOW`. The reservation also accepts an `estimated_miles` quoted distance (defaulting to 0), a `charter_hours` booked-hours figure (defaulting to 0), a `tolls_cents` pass-through amount (defaulting to 0, required to be zero or greater, and treated as a pass-through that is added after gratuity and never discounted or gratuity-bearing), and an optional `gratuity_pct_override` that, when present, replaces the account default for this one reservation. Trip-type-specific fields are required: a `POINT_TO_POINT` or `AIRPORT` reservation must supply an `estimated_miles` greater than zero, and an `HOURLY` reservation must supply a `charter_hours` greater than zero; a violation is rejected with `ERR_TRIP_TYPE_FIELDS`, which is evaluated immediately after the time-window check and before any non-negativity or percent-range check. A negative `tolls_cents`, `estimated_miles`, or `charter_hours` — like an out-of-band `gratuity_pct_override` — is rejected with `ERR_VALIDATION_RANGE` (the non-negativity checks on `tolls_cents`, then `estimated_miles`, then `charter_hours` are applied in that order, ahead of the `gratuity_pct_override` band check). A new reservation starts with `trip_status` of `DRAFT`, `settlement_status` of `UNBILLED`, and `fulfillment_mode` of `IN_HOUSE`; its computed monetary fields begin unstamped — `quote_estimate_total_cents` and `final_total_cents` are null, while `chargeable_wait_minutes` and `cancellation_fee_cents` begin at 0.

The reservation event endpoints carry an `action` field selecting which transition to apply. When a `Dispatcher` (or the owning account's `CorporateBooker`) quotes a `DRAFT` reservation with `action` set to `QUOTE`, it advances `DRAFT → QUOTED`. This is permitted only while `trip_status` is `DRAFT` and the requested vehicle class's `status` is `ACTIVE`; a wrong-state attempt is rejected with `ERR_INVALID_STATE`. Quoting runs the estimate calculation and stamps the result into `quote_estimate_total_cents`, and it records a quote snapshot of the estimate variant for the audit trail.

The **estimate** is forward-looking and reads only the values booked so far — no actual wait has occurred yet. It is computed in a pinned order. First the fare base is established: for an `HOURLY` trip, the booked `charter_hours` are rounded up to the next whole hour and multiplied by the class's `hourly_rate_cents`; for a `POINT_TO_POINT` or `AIRPORT` trip, the fare base is the class's `base_fare_cents` plus the product of the class's `per_mile_cents` and the reservation's `estimated_miles`, with that distance product rounded to whole cents. Next the account's `negotiated_discount_pct` is applied: the discounted base is the fare base multiplied by the quantity (100 minus the discount percent) divided by 100, rounded to whole cents. Then gratuity is taken on the discounted base: the gratuity percent is the reservation's `gratuity_pct_override` when present and otherwise the account's `default_gratuity_pct`, and the gratuity is the discounted base multiplied by that percent divided by 100, rounded to whole cents. Finally the estimate total is the discounted base plus the gratuity plus the reservation's `tolls_cents`. The estimate deliberately excludes any wait charge and any cancellation fee.

### 3.3. Confirming, Assigning, and Dispatching In-House

Confirmation moves a reservation `QUOTED → CONFIRMED` and may be performed by a `Dispatcher` or a `CorporateBooker`. It requires the reservation to be `QUOTED` and the owning corporate account's `status` to be `ACTIVE`; if the account has been suspended, confirmation is rejected with `ERR_ACCOUNT_SUSPENDED`, and a wrong trip-state attempt is rejected with `ERR_INVALID_STATE`. No money moves on confirmation; the reservation now awaits either an in-house assignment or a farm-out offer.

A `Dispatcher` assigns a confirmed reservation in-house by nominating a `reservation_id`, a `chauffeur_id`, a `vehicle_id`, and the `expected_reservation_version` described in §2.8. A successful assignment is the gateway from `CONFIRMED` to `ASSIGNED`, and it is hedged by a sequence of preconditions. The reservation must be `CONFIRMED` and its `fulfillment_mode` must still be `IN_HOUSE`; a wrong reservation state is rejected with `ERR_INVALID_STATE`. The reservation must not already carry a fulfillment commitment: a reservation may have at most one `ACTIVE` assignment, and it may not hold both an `ACTIVE` assignment and a farm-out order that is `OFFERED` or `ACCEPTED`, because in-house and farm-out are mutually exclusive — a conflict here is rejected with `ERR_FULFILLMENT_CONFLICT`. The nominated chauffeur must be available, meaning its `status` is `OFF_DUTY` or `ON_DUTY` and not `ON_TRIP` or `SUSPENDED`; an unavailable chauffeur is rejected with `ERR_RESOURCE_UNAVAILABLE`.

The assignment is also gated by two temporal checks. The chauffeur must be free across the reservation's window plus a one-sided rest guard: an `ACTIVE` assignment already held by that chauffeur conflicts with the new one when the new window starts before the existing window's end extended by the chauffeur's `rest_buffer_minutes`, and at the same time the existing window starts before the new window's end extended by the same `rest_buffer_minutes`. Windows are half-open, so adjacency exactly at an existing window's end plus the buffer is allowed and is not a conflict. A chauffeur conflict is rejected with `ERR_CHAUFFEUR_DOUBLE_BOOKED`. The vehicle is checked differently: rather than a one-sided rest guard, the vehicle requires a shared gap between consecutive trips at least as large as its `turnaround_minutes`. For the two windows ordered by start time (ties broken by `created_at`), the gap is the whole minutes between the earlier window's end and the later window's start, computed by discarding any partial minute. A gap strictly smaller than the vehicle's `turnaround_minutes` is a conflict; a gap exactly equal to `turnaround_minutes` is allowed. A vehicle conflict is rejected with `ERR_VEHICLE_TURNAROUND_VIOLATION`. These checks are evaluated in their priority order — resource availability first, then the chauffeur overlap, then the vehicle turnaround, then the fulfillment-exclusivity rule and the version guard — so the surfaced error reflects the first failing condition.

When all preconditions hold, the system creates an assignment whose `status` is `ACTIVE` and whose `window_start_at` and `window_end_at` are copied from the reservation's `pickup_at` and `planned_drop_at`. As the first hop of a cross-entity cascade, the reservation moves to `ASSIGNED` and its `version` increments by one. As the second visible effect, the chauffeur moves from `OFF_DUTY` to `ON_DUTY` (a chauffeur already `ON_DUTY` stays `ON_DUTY`). A chauffeur may also clock themselves in independently: a duty event from a `Chauffeur` (or an admin) with action `CLOCK_IN` moves the chauffeur `OFF_DUTY → ON_DUTY`, and `CLOCK_OUT` moves `ON_DUTY → OFF_DUTY` but only when the chauffeur's `active_assignment_id` is null.

Dispatching the trip advances the reservation `ASSIGNED → EN_ROUTE` and may be triggered by a `Dispatcher` or by the assigned `Chauffeur`. It requires the reservation to be `ASSIGNED` and an `ACTIVE` assignment to exist for it; otherwise it is rejected with `ERR_INVALID_STATE`. The cascade's second hop fires here: the chauffeur moves `ON_DUTY → ON_TRIP` and the chauffeur's `active_assignment_id` is set to the driving assignment's `id`.

### 3.4. Arrival, Wait Time, and Completion

The wait window is captured by two append-only events posted by the `Dispatcher` or the assigned `Chauffeur`, each carrying a `kind` and an `occurred_at` server-clock timestamp. Posting a `CHAUFFEUR_ARRIVED` event advances the reservation `EN_ROUTE → ON_LOCATION` and opens the wait window; it is allowed only while the reservation is `EN_ROUTE`. Posting a `PASSENGER_BOARDED` event advances the reservation `ON_LOCATION → PASSENGER_ABOARD` and closes the wait window; it is allowed only while the reservation is `ON_LOCATION`. Wait events must arrive in order: a `PASSENGER_BOARDED` requires an existing `CHAUFFEUR_ARRIVED` with an earlier `occurred_at`, and an `occurred_at` that predates the prior event — or a duplicate `CHAUFFEUR_ARRIVED`, or a `PASSENGER_BOARDED` before any arrival — is rejected with `ERR_WAIT_SEQUENCE`. The sequence checks take priority over the trip-state gate: a duplicate `CHAUFFEUR_ARRIVED`, an out-of-order or arrival-less `PASSENGER_BOARDED` surfaces `ERR_WAIT_SEQUENCE` before the `EN_ROUTE`/`ON_LOCATION` state requirement is evaluated (whose violation is `ERR_INVALID_STATE`). A reference to a `reservation_id` for the wait log allows the events to be listed back per reservation.

When the boarding event closes the window, the system computes the chargeable wait and stamps it into `chargeable_wait_minutes`. The raw wait is the whole minutes between the `occurred_at` of the `CHAUFFEUR_ARRIVED` event and the `occurred_at` of the `PASSENGER_BOARDED` event, taking the total elapsed seconds and discarding the partial minute. The grace is the vehicle class's `included_wait_minutes`. The chargeable wait is the raw wait minus the grace when that difference is positive, and zero otherwise — so a wait of exactly the grace yields zero chargeable minutes, and the first chargeable minute is the one immediately past the grace.

Completion advances the reservation `PASSENGER_ABOARD → COMPLETED` and may be triggered by a `Dispatcher` or the assigned `Chauffeur`; it requires the reservation to be `PASSENGER_ABOARD`. Completion runs the final settlement and stamps `final_total_cents`, then unwinds the operational cascade: the chauffeur moves `ON_TRIP → ON_DUTY`, the chauffeur's `active_assignment_id` is cleared, and the assignment moves `ACTIVE → RELEASED`, freeing both the chauffeur and the vehicle for their next trip.

The **final settlement** is the chronological dual of the estimate. It follows the same pinned order, but the fare base now absorbs the actual wait charge before any discount or gratuity is taken, which is why a trip with chargeable wait settles for more than it was quoted, while a trip with zero chargeable wait and unchanged tolls settles for exactly the estimate. The fare base is established identically to the estimate: for `HOURLY`, the `charter_hours` rounded up to whole hours times `hourly_rate_cents`; otherwise `base_fare_cents` plus the rounded product of `per_mile_cents` and `estimated_miles`. The wait charge is the reservation's `chargeable_wait_minutes` multiplied by the class's `wait_per_minute_cents`. The pre-discount amount is the fare base plus the wait charge. The discounted base is that pre-discount amount multiplied by (100 minus the account's `negotiated_discount_pct`) divided by 100, rounded to whole cents. Gratuity is the discounted base multiplied by the effective gratuity percent (the reservation's `gratuity_pct_override` when present, otherwise the account's `default_gratuity_pct`) divided by 100, rounded to whole cents. The final total is the discounted base plus the gratuity plus the reservation's `tolls_cents`.

### 3.5. Farming Out to Affiliates

When in-house capacity is short, a `Dispatcher` may offer a confirmed reservation to an affiliate by submitting a `reservation_id`, an `affiliate_id`, and the `expected_reservation_version` guard. Offering creates a farm-out order whose `status` is `OFFERED`, and as a side effect increments the reservation's `version` and refreshes the affiliate's `open_farmouts`. Offer creation enforces no `trip_status` precondition on the reservation itself; its domain checks run in the order version guard, then fulfillment-exclusivity, then affiliate eligibility. The version guard is evaluated first: an `expected_reservation_version` that does not equal the reservation's current `version` is rejected with `ERR_STALE_VERSION` at HTTP 412 before either conflict check. An offer is then rejected with `ERR_FULFILLMENT_CONFLICT` if the reservation already holds an `ACTIVE` assignment or an `OFFERED`/`ACCEPTED` order, and with `ERR_AFFILIATE_INELIGIBLE` if the target affiliate's `status` is `SUSPENDED` rather than `ACTIVE`. At offer time the system snapshots the payout into `offered_payout_cents`.

The **affiliate payout** is computed on a deliberately different basis from the customer-facing total — it is the operator-side value of the trip, taken on the raw fare base alone with no wait, no discount, no gratuity, and no tolls. For an `HOURLY` trip the fare base is `hourly_rate_cents` times the `charter_hours` rounded up to whole hours; otherwise it is `base_fare_cents` plus the rounded product of `per_mile_cents` and `estimated_miles`. The payout is that fare base multiplied by the affiliate's `payout_share_pct` divided by 100, rounded to whole cents. The same trip therefore carries two legitimate but divergent value figures: the customer's `final_total_cents` on the reservation (post-discount, gratuity-inclusive, toll-inclusive) and the affiliate's `offered_payout_cents` on the order (raw fare base only).

The affiliate decides the offer through a decision event. An `AffiliatePartner` whose `id` matches the order's `affiliate_id` may accept, moving the order `OFFERED → ACCEPTED`, or reject, moving it `OFFERED → REJECTED` and optionally recording a `decline_reason`. A `Dispatcher` may instead recall an outstanding offer, moving it `OFFERED → RECALLED`. Acceptance requires the order to be `OFFERED`, the affiliate's `status` to be `ACTIVE`, and the linked reservation's `trip_status` to be `CONFIRMED`; a state violation is rejected with `ERR_INVALID_STATE`. Acceptance is a three-hop cascade: the reservation's `fulfillment_mode` moves `IN_HOUSE → FARMED_OUT`, the reservation's `trip_status` jumps `CONFIRMED → COMPLETED` because the affiliate is now serving it, and the final settlement runs on the reservation to stamp `final_total_cents` — noting that on a farm-out accept there are no in-house wait events, so `chargeable_wait_minutes` is 0 and the wait charge is zero. Accepting also refreshes the affiliate's `open_farmouts`. A reject or a recall leaves the reservation `CONFIRMED` with `fulfillment_mode` still `IN_HOUSE` and refreshes the affiliate's `open_farmouts`; the order ends `REJECTED` or `RECALLED` respectively.

### 3.6. Airport Trips, Flight Tracking, and Run-Late Propagation

For an `AIRPORT` reservation, a `Dispatcher` or `CorporateBooker` may attach flight tracking by submitting a `reservation_id`, a `flight_number`, a `scheduled_arrival_at`, and an optional `meet_and_greet` flag (defaulting to false) requesting inside-terminal greeting. Flight tracking may be attached only to a reservation whose `trip_type` is `AIRPORT`, and at most one tracking record may exist per reservation; a non-airport reservation or a second tracking attempt is rejected with `ERR_FLIGHT_NOT_APPLICABLE`. A new tracking record starts with `status` of `ON_TIME` and an `estimated_arrival_at` defaulted to the `scheduled_arrival_at`. The tracking for a reservation can be listed back through its `reservation_id`.

A `DispatchAdmin` or `Dispatcher` pushes flight updates. An update either supplies a revised `estimated_arrival_at` or signals a landing via a `kind` of `LANDED`; an update that supplies neither, or that carries a `kind` other than `LANDED`, is rejected with `ERR_INVALID_REQUEST`. The delay is the whole minutes between the `estimated_arrival_at` and the `scheduled_arrival_at`, computed by discarding any partial minute. A landing update finalizes the flight: it sets `status` to `LANDED`, sets `estimated_arrival_at` to the actual landing time supplied on the update (or, when the landing update omits `estimated_arrival_at`, leaves the current `estimated_arrival_at` unchanged), and applies no window shift. A non-landing update compares the delay against a threshold of fifteen minutes. When the delay is strictly greater than fifteen minutes, the flight becomes `DELAYED` (from either `ON_TIME` or `DELAYED`); when the delay is within fifteen minutes, the flight returns to `ON_TIME`. A delay of exactly fifteen minutes leaves the flight `ON_TIME` — only a delay strictly past the threshold trips it into `DELAYED`.

Run-late propagation links the flight to the car. When a non-landing update crosses into `DELAYED` and the linked reservation is `ASSIGNED` with exactly one `ACTIVE` assignment, the system slides that assignment's `window_start_at` and `window_end_at` forward by the incremental difference between the current delay and the shift already applied, so successive updates only move the window by the new delta. When a non-landing update returns the flight to `ON_TIME`, any shift previously applied to the assignment window is reverted back toward the scheduled time. A landing never shifts the window.

### 3.7. Cancellations and the Lead-Time Tiers

A reservation may be cancelled from any non-terminal trip state — `DRAFT`, `QUOTED`, `CONFIRMED`, `ASSIGNED`, or `EN_ROUTE` — by a `Dispatcher` or a `CorporateBooker`, except that a cancellation from `EN_ROUTE` is reserved for a `Dispatcher`. Cancellation drives the reservation to `CANCELLED`, runs the tier calculation to stamp `cancellation_fee_cents`, and writes an immutable `CancellationRecord` referencing the reservation by `reservation_id` and capturing the chosen `tier`, the `lead_minutes`, and the `fee_cents` mirrored from the reservation. A cancellation from a state that already carries committed resources also unwinds them: cancelling an `ASSIGNED` reservation releases the assignment `ACTIVE → RELEASED` and reverts the chauffeur `ON_DUTY → OFF_DUTY`, while cancelling an `EN_ROUTE` reservation releases the assignment and reverts the chauffeur `ON_TRIP → OFF_DUTY` while clearing its `active_assignment_id`. Cancelling from `DRAFT` or `QUOTED` or `CONFIRMED` has no resource to unwind.

The **cancellation tier** is decided by lead time against the account's grace. The lead is the whole minutes between the reservation's `pickup_at` and the server's current time taken from the clock, computed by discarding any partial minute and going negative once pickup has passed. The penalty base is the estimate's discounted base — that is, the `quote_estimate_total_cents` less its gratuity and less its tolls — and if the reservation never reached `QUOTED`, there is no estimate and the penalty base is zero, which always yields a free cancellation. The grace is the account's `cancellation_grace_minutes`. If the lead is at least the grace, the tier is `FREE` and the fee is zero. Otherwise, if the lead is at least sixty minutes, the tier is `TIER1` and the fee is the penalty base times twenty-five percent, rounded to whole cents. Otherwise, if the lead is at least zero minutes, the tier is `TIER2` and the fee is the penalty base times fifty percent, rounded to whole cents. Otherwise — pickup has already passed — the tier is `NO_SHOW` and the fee is the full penalty base. The boundaries are inclusive on the lower edge of each band: a lead exactly equal to the grace is `FREE`, a lead of exactly sixty minutes is `TIER1`, and a lead of exactly zero is `TIER2`.

### 3.8. Billing, Settlement, and the Account Balance

The financial axis of a reservation advances independently of its trip axis. A `Dispatcher` invoices a reservation, moving its `settlement_status` `UNBILLED → INVOICED`. Invoicing requires the reservation to be `UNBILLED` and its `trip_status` to be `COMPLETED` or `CANCELLED`, and it requires a known final amount — `final_total_cents` set for a completed trip, or `cancellation_fee_cents` set for a cancelled one. An attempt to invoice a reservation that is neither completed nor cancelled, or that otherwise lacks a billable amount, is rejected with `ERR_NOT_BILLABLE`; a wrong settlement state is rejected with `ERR_INVALID_STATE`. The settlement-state gate is evaluated first: a reservation that is not `UNBILLED` surfaces `ERR_INVALID_STATE` before the `COMPLETED`/`CANCELLED` and billable-amount checks (which surface `ERR_NOT_BILLABLE`) are reached. Invoicing recomputes the owning account's `outstanding_balance_cents`.

From `INVOICED`, a `Dispatcher` settles the reservation, moving `settlement_status` `INVOICED → SETTLED`, which recomputes the account's `outstanding_balance_cents` so it drops by the settled amount. Alternatively, a `DispatchAdmin` writes off the reservation, moving `settlement_status` `INVOICED → WRITTEN_OFF`, which likewise recomputes `outstanding_balance_cents` so the written-off amount falls away. The write-off action is reserved for `DispatchAdmin`; settle and invoice belong to `Dispatcher`. Both settle and write-off require the reservation to be `INVOICED` and are rejected with `ERR_INVALID_STATE` otherwise.

### 3.9. Chauffeur Duty Lifecycle and Administrative Holds

Beyond the automatic transitions driven by assignment and completion, a chauffeur's `status` moves through a cycle over a shift. A chauffeur loops `ON_DUTY → ON_TRIP → ON_DUTY` across many trips before clocking out, with `active_assignment_id` set when entering `ON_TRIP` and cleared when leaving it. A `Chauffeur` (or admin) clocks in with `CLOCK_IN` while `OFF_DUTY` and clocks out with `CLOCK_OUT` while `ON_DUTY` and free of any active assignment; a `CLOCK_OUT` attempted while the chauffeur still carries a non-null `active_assignment_id` is rejected with `ERR_INVALID_STATE`. A `DispatchAdmin` may suspend an off-duty chauffeur with action `SUSPEND`, moving `OFF_DUTY → SUSPENDED`, and may later reinstate one with `REINSTATE`, moving `SUSPENDED → OFF_DUTY`; the suspend and reinstate actions are reserved for `DispatchAdmin` even though the duty-event endpoint is otherwise shared with the chauffeur. A wrong-state duty event is rejected with `ERR_INVALID_STATE`. For deterministic time-gated behavior, a `DispatchAdmin` may set the server clock by supplying a `to_iso8601` instant, which writes `current_utc` on the clock and governs every lead-time, wait, and flight comparison thereafter; the set-clock call returns a clock object exposing only `current_utc`, and until the clock is first set every such comparison falls back to the real wall-clock time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, advance a state machine, or read data return `200 OK`. Every endpoint requires the authentication headers of §2.1, and authorization is enforced per the roles listed below; for the action-bearing event endpoints, the per-action role limits described in §3 apply as business rules on top of the endpoint's role list.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/corporate-accounts` | Create a corporate account | DispatchAdmin |
| GET | `/corporate-accounts/{id}` | Get a corporate account, including computed outstanding balance | DispatchAdmin, Dispatcher, CorporateBooker |
| POST | `/corporate-accounts/{id}/suspend` | Suspend a corporate account | DispatchAdmin |
| POST | `/affiliates` | Create an affiliate operator | DispatchAdmin |
| GET | `/affiliates/{id}` | Get an affiliate, including computed open farm-outs | DispatchAdmin, Dispatcher, AffiliatePartner |
| POST | `/affiliates/{id}/suspend` | Suspend an affiliate; blocks new offers | DispatchAdmin |
| POST | `/vehicle-classes` | Create a vehicle class with its rate card | DispatchAdmin |
| POST | `/vehicles` | Create a vehicle | DispatchAdmin |
| GET | `/vehicles/{id}` | Get a vehicle | DispatchAdmin, Dispatcher |
| GET | `/vehicles` | List or filter vehicles | DispatchAdmin, Dispatcher |
| POST | `/chauffeurs` | Create a chauffeur | DispatchAdmin |
| GET | `/chauffeurs/{id}` | Get a chauffeur | DispatchAdmin, Dispatcher, Chauffeur |
| POST | `/chauffeurs/{id}/duty-events` | Clock in/out (Chauffeur, Admin) or suspend/reinstate (Admin only) | DispatchAdmin, Chauffeur |
| POST | `/reservations` | Create a reservation in DRAFT | Dispatcher, CorporateBooker |
| GET | `/reservations/{id}` | Get a reservation, including computed quote/final/wait/cancellation fields | DispatchAdmin, Dispatcher, CorporateBooker, Chauffeur |
| GET | `/reservations` | List or filter reservations | DispatchAdmin, Dispatcher, CorporateBooker |
| POST | `/reservations/{id}/trip-events` | Advance trip status: QUOTE, CONFIRM, DISPATCH, COMPLETE, CANCEL | Dispatcher, CorporateBooker, Chauffeur |
| POST | `/reservations/{id}/wait-events` | Append a wait event and advance the reservation | Dispatcher, Chauffeur |
| GET | `/reservations/{id}/wait-events` | List wait events for a reservation | DispatchAdmin, Dispatcher, Chauffeur |
| POST | `/reservations/{id}/billing-events` | Advance settlement status: INVOICE, SETTLE, WRITE_OFF | Dispatcher, DispatchAdmin |
| GET | `/reservations/{id}/cancellation-record` | List the cancellation record(s) for a reservation, returned as a paginated array (`response_type` "array") | DispatchAdmin, Dispatcher, CorporateBooker |
| POST | `/assignments` | Assign a chauffeur and vehicle in-house to a confirmed reservation | Dispatcher |
| GET | `/assignments/{id}` | Get an assignment | DispatchAdmin, Dispatcher, Chauffeur |
| GET | `/assignments` | List or filter assignments | DispatchAdmin, Dispatcher, Chauffeur |
| POST | `/farm-out-orders` | Offer a confirmed reservation to an affiliate | Dispatcher |
| GET | `/farm-out-orders/{id}` | Get a farm-out order | DispatchAdmin, Dispatcher, AffiliatePartner |
| GET | `/farm-out-orders` | List or filter farm-out orders | DispatchAdmin, Dispatcher, AffiliatePartner |
| POST | `/farm-out-orders/{id}/decision-events` | Decide a farm-out offer: ACCEPT, REJECT, RECALL | AffiliatePartner, Dispatcher |
| POST | `/flight-trackings` | Attach flight tracking to an airport reservation | Dispatcher, CorporateBooker |
| GET | `/reservations/{id}/flight-trackings` | List flight tracking for a reservation | DispatchAdmin, Dispatcher, CorporateBooker, Chauffeur |
| POST | `/flight-trackings/{id}/flight-updates` | Push a flight status update; may shift the assignment window | DispatchAdmin, Dispatcher |
| POST | `/_clock/set_current_utc` | Set the deterministic server clock | DispatchAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_TRIP_TYPE_FIELDS` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FLIGHT_NOT_APPLICABLE` | 409 |
| `ERR_WAIT_SEQUENCE` | 409 |
| `ERR_RESOURCE_UNAVAILABLE` | 409 |
| `ERR_CHAUFFEUR_DOUBLE_BOOKED` | 409 |
| `ERR_VEHICLE_TURNAROUND_VIOLATION` | 409 |
| `ERR_FULFILLMENT_CONFLICT` | 409 |
| `ERR_AFFILIATE_INELIGIBLE` | 409 |
| `ERR_NOT_BILLABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_DUPLICATE_PLATE` | 409 |
| `ERR_DUPLICATE_CLASS_CODE` | 409 |
