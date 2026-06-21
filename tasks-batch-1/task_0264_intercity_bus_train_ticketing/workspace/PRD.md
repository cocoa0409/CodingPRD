# Intercity Ticketing API — Product Requirements Document

## 1. Introduction

The Intercity Ticketing API powers an Amtrak/Greyhound-style reservation platform that sells seats on scheduled rail and bus services. The system has to reconcile several concerns that ordinarily live in separate products: a hierarchical catalog of carriers, routes, and dated trip instances; a seat-inventory ledger that must stay consistent as seats move between hold, sold, and available pools; a dynamic pricing engine whose fares respond to both demand and how far in advance a traveler books; and a settlement layer that handles cash refunds, travel credit, multi-ride passes, baggage fees, and accessibility accommodations.

Travelers expect to hold seats, pay, exchange a leg onto a different departure, or cancel for a refund, all while the operator simultaneously delays, suspends, or cancels trips. Those two streams of activity collide on shared inventory, so the platform is built around immediate consistency: every hold, sale, release, refund, and ride restoration is reflected the instant it happens, and concurrent writers that act on a stale view of a trip or a booking are rejected rather than allowed to overwrite each other. This document specifies the entities, their lifecycles, the pricing and settlement math, the validation order, and the full HTTP surface that together make those guarantees enforceable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API. The API is mounted under the `/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When both headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles: `ScheduleManager`, `FareAnalyst`, `Passenger`, `GateAgent`, and `SupportAgent`.

A `ScheduleManager` owns the operational catalog — operators, routes, and the scheduling and lifecycle of service dates. A `FareAnalyst` owns fare-class configuration and pricing parameters. A `Passenger` is the end traveler who books, pays, cancels, exchanges, and manages baggage and accessibility on resources they own. A `GateAgent` scans tickets at boarding gates. A `SupportAgent` is the operational back-office agent who registers passengers, issues passes, adjudicates accessibility requests, and assists passengers with refunds and exchanges; the `SupportAgent` also controls the server clock used for test-driving time-dependent logic.

Identity binding differs by role. When `X-User-Role` is `Passenger`, `X-User-ID` is the `id` of the acting `Passenger` entity; ownership checks on any resource that references a passenger compare that resource's `passenger_id` to `X-User-ID`. A passenger-scoped mutation on a booking, pass, or baggage item that the acting passenger does not own is rejected with `ERR_NOT_OWNER`. When `X-User-Role` is any of `ScheduleManager`, `FareAnalyst`, `GateAgent`, or `SupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`, and these four roles are not subject to passenger ownership checks.

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

List endpoints accept two pagination query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed bounds is rejected with `ERR_VALIDATION_PAGINATION`.

Unless stated otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every resource is addressed by an `id`, a server-minted UUID with no type prefix that serves as identity only and is never supplied by the client. Most resources also carry three system-managed audit fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arise from cascades or from a recompute of derived counters; and `version`, an integer that starts at 1 and increments by 1 on every mutation of the resource.

One entity is an exception. A settlement note (the refund/credit document described in §3) is append-only and immutable once written: it carries `id` and `created_at` but has neither `updated_at` nor `version`. Every other entity — operators, fare classes, routes, service dates, passengers, travel passes, bookings, booking legs, tickets, baggage items, and accessibility requests — carries the full `created_at` / `updated_at` / `version` triple.

### 2.5. Nested Resource Retrieval and Reference Validation

Many endpoints embed one or more resource identifiers in the path, and several write bodies reference resources by id. The system validates every referenced resource left-to-right, in the order it appears in the path and then the body, and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. For example, a request to act on a service date that does not exist fails with `ERR_NOT_FOUND` before any state or business rule is considered.

List endpoints support reverse-reachability filtering so that children can be located from a parent. Fare classes can be filtered by `operator_id`; routes by `operator_id`; service dates by `route_id`; travel passes by `passenger_id` or `operator_id`; bookings by `passenger_id` or `pass_id`; booking legs by `booking_id`, `service_date_id`, or `fare_class_id`; tickets by `booking_id` or `booking_leg_id`; baggage items by `booking_id`; accessibility requests by `booking_leg_id`; and settlement notes by `booking_id`.

### 2.6. Seat-Inventory Ledger and Derived Counters

Each service date maintains a live seat ledger that the system reconciles on every hold, sale, release, exchange, and cascade. Three counters are derived and never set directly by clients. The held count, `seats_held`, is the number of `ACTIVE` booking legs on the service date whose owning booking is in `HELD` status. The sold count, `seats_sold`, is the number of `ACTIVE` booking legs on the service date whose owning booking is in `CONFIRMED` status. The available count, `seats_available`, is the physical capacity `seats_total` minus `seats_held` minus `seats_sold`; this value is an invariant that is never allowed to go negative. The `load_factor` is `seats_sold` divided by `seats_total` — only confirmed legs count toward it — and it is an exact ratio used solely for demand-pricing tier comparison. Whenever any of these counters changes, the service date's `version` increments by 1 and its `updated_at` is refreshed.

### 2.7. Pricing Precision and Monetary Rounding

All monetary amounts are integer cents. Per-leg fares are computed by multiplying a base fare by a demand multiplier and an advance factor; the resulting raw product is rounded half up to whole cents, and only then is the fare class's flat surcharge added. Rounding is therefore applied per leg, before the surcharge, and a booking total is formed by summing the already-rounded per-leg cents — the summation itself is exact. The same round-half-up-to-whole-cents convention applies to refund and credit penalties and to baggage overweight fees. Where a calculation subtracts one integer-cent quantity from another (for example, a net refund or an exchange settlement), the subtraction is exact and no further rounding occurs.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a shared resource.

Confirming a booking requires the body field `expected_service_date_version`, which carries the `version` of the referenced service date that the client last observed. This field is mandatory on confirm. If, at confirm time, that value does not match the service date's current `version` — for instance because another writer already confirmed a booking that consumed the last seat and legitimately advanced the service date — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). A multi-leg booking observes a single shared version baseline, so `expected_service_date_version` pins the version of the referenced service date the client last read.

Exchanging a leg requires the body field `expected_booking_version`, which carries the `version` of the booking that the client last observed. This field is mandatory on exchange. If that value does not match the booking's current `version` — for instance because a prior exchange or partial settlement already advanced the booking — the exchange is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field; endpoints that are not guarded above do not take one.

### 2.9. The Logical Clock

All time-dependent logic — advance-window pricing, hold expiry, pass expiry, and cancellation penalty tiers — reads from a single server clock rather than wall-clock time. A `SupportAgent` may set that clock to a supplied UTC instant by providing the field `to_iso8601`; the supplied instant becomes the server's current time for every subsequent time-dependent computation. This capability exists to drive deterministic testing of the time-sensitive workflows in §3.

### 2.10. Hierarchical Consistency and Cascades

State changes propagate down the hierarchy. When a parent resource transitions in a way that invalidates its children — most consequentially the cancellation of a service date — the system resolves every dependent booking, leg, ticket, settlement, and pass balance immediately and as part of the same operation, rather than leaving them inconsistent. Every entity touched in such a cascade independently has its `updated_at` refreshed and its `version` incremented. The specific cascades, their depth, and the fiscal and conserved-quantity restorations they trigger are detailed in §3.

### 2.11. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the same input always yields the same error. The order is: (1) authentication headers present, else `ERR_UNAUTHENTICATED`; (2) the role is permitted for the operation, else `ERR_FORBIDDEN_ROLE`; (3) every referenced resource exists, validated left-to-right, else `ERR_NOT_FOUND`; (4) for passenger-scoped mutations on bookings, passes, and baggage, the acting passenger owns the target, else `ERR_NOT_OWNER`; (5) the request body is well-formed — field types and enums are valid, required fields are present, and conditional presence rules hold (seat-number presence matching seating mode, pass-id presence matching funding kind) — else `ERR_INVALID_REQUEST`; (6) the target resource is in a valid state for the requested transition, else `ERR_INVALID_STATE`; (7) cross-entity state preconditions hold, else `ERR_PRECONDITION_NOT_MET`; (8) temporal checks (hold not expired, pass not expired) hold, else `ERR_HOLD_EXPIRED`; (9) the multi-leg connection buffer is satisfied, else `ERR_CONNECTION_TOO_TIGHT`; (10) accessibility-slot availability holds, else `ERR_ACCESSIBILITY_UNAVAILABLE`; (11) reserved-seat uniqueness holds, else `ERR_SEAT_TAKEN`; (12) refund eligibility holds, else `ERR_REFUND_NOT_ALLOWED`; (13) aggregate seat capacity holds, else `ERR_SOLD_OUT`; (14) pass balance holds, else `ERR_PASS_DEPLETED`; (15) the OCC version matches, else `ERR_STALE_VERSION`. Authentication is checked before authorization, existence before ownership, request shape before state, generic state before cross-entity preconditions, and the family of business and fiscal constraints last. Several of these checks raise more specific error codes for particular conditions, described alongside the workflows they guard in §3 — for example a retired fare class raises `ERR_FARE_CLASS_RETIRED`, an unpublished route raises `ERR_ROUTE_NOT_PUBLISHED`, an expired pass raises `ERR_PASS_EXPIRED`, an unpaid booking presented for refund raises `ERR_NOT_PAID`, and a duplicate passenger email raises `ERR_DUPLICATE_EMAIL`.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Operators, Fare Classes, and Routes

A `ScheduleManager` seeds the catalog by creating an **Operator** — a carrier identified by its `name` and its transport `mode`, which is either `RAIL` or `BUS` and applies to every route under that operator. Each operator also configures two policy values used much later in the lifecycle: `default_connection_buffer_min`, the minimum number of minutes that must elapse between an inbound leg's arrival and the next leg's departure on a multi-leg booking (at least 0, defaulting to 30), and `exchange_fee_cents`, the flat fee charged when a passenger exchanges a leg (at least 0, defaulting to 1000). An operator begins at `version` 1.

A `FareAnalyst` defines the pricing tiers as **Fare Classes**, each owned by an operator referenced through its `operator_id`. A fare class declares a `code` of either `ECONOMY` or `BUSINESS`, and a `seating_mode` of either `RESERVED` or `OPEN`. In `RESERVED` mode every leg priced under the class must name a specific seat; in `OPEN` mode only aggregate capacity is counted. The class carries a `surcharge_cents` (at least 0, defaulting to 0) that is added to a leg's fare after the demand and advance multipliers are applied, and `refundable`, a boolean defaulting to true that, when false, restricts every leg of that class to travel-credit refunds only and forbids cash. A fare class is created with `status` `ACTIVE` and may be moved to `RETIRED` by a `FareAnalyst`; retiring it bumps its `version`. A `RETIRED` fare class can still be read and still applies to existing legs, but a new booking leg that references a `RETIRED` class is rejected with `ERR_FARE_CLASS_RETIRED`.

A `ScheduleManager` lays out the network as **Routes**, each owned via its `operator_id` and described by a 3-letter `origin_code`, a 3-letter `destination_code`, a scheduled departure expressed as `depart_minute_of_day` (minutes from midnight, 0 through 1439), and a scheduled arrival expressed as `arrive_minute_of_day` (also 0 through 1439); when the arrival minute is less than the departure minute it denotes a next-day arrival. A route is created in `status` `DRAFT`. Only a route that has been advanced to `PUBLISHED` — publishing bumps its `version` — may have service dates scheduled against it; attempting to schedule a trip on a non-`PUBLISHED` route is rejected with `ERR_ROUTE_NOT_PUBLISHED`.

### 3.2. Scheduling Trips and Driving the Service-Date Lifecycle

A **Service Date** is a single dated trip instance of a published route, created by a `ScheduleManager` against a `route_id` with a `departure_date` (the calendar date in `YYYY-MM-DD` form), a physical `seats_total` (at least 1), and a `base_fare_cents` (at least 0) that anchors the dynamic pricing for the trip. On creation its seat counters are initialized, its `lifecycle` is `SCHEDULED`, its `sales` gate is `OPEN`, and its `version` is 1. The combination of `departure_date` and the route's departure minute drives advance-window pricing.

The service date carries two independent state axes. The first is the operational `lifecycle`, which moves among `SCHEDULED`, `DELAYED`, `DEPARTED`, and `CANCELLED`. Marking a `SCHEDULED` trip as delayed advances `lifecycle` from `SCHEDULED` to `DELAYED` and bumps the version; this is reversible, and restoring a delayed trip moves it from `DELAYED` back to `SCHEDULED`, again bumping the version. From either `SCHEDULED` or `DELAYED`, a `ScheduleManager` may mark the trip departed, advancing `lifecycle` to `DEPARTED`; departure freezes the trip, also forcing the `sales` gate to `SUSPENDED` and bumping the version, after which no new holds are possible. `DEPARTED` and `CANCELLED` are terminal lifecycle states. Each lifecycle transition requires the trip to currently be in an admissible source state — delay requires `lifecycle` to be `SCHEDULED`, restore requires it to be `DELAYED`, and both depart and cancel require it to be one of `SCHEDULED` or `DELAYED` — and a request that finds the trip in the wrong state is rejected with `ERR_INVALID_STATE`.

The second axis is the `sales` gate, which toggles between `OPEN` and `SUSPENDED` independently of lifecycle. A `ScheduleManager` may suspend sales, moving `sales` from `OPEN` to `SUSPENDED`, or resume them, moving from `SUSPENDED` back to `OPEN`; each bumps the version. Suspending requires `sales` to currently be `OPEN`, resuming requires it to be `SUSPENDED`, and both require the trip's `lifecycle` to be neither `DEPARTED` nor `CANCELLED`; a violation is rejected with `ERR_INVALID_STATE` or, where the lifecycle precondition fails, `ERR_PRECONDITION_NOT_MET`. New holds require the gate to be `OPEN`.

Cancelling a service date is the most consequential operation in the system. From `SCHEDULED` or `DELAYED`, a `ScheduleManager` moves `lifecycle` to `CANCELLED` and forces `sales` to `SUSPENDED`, then runs a three-hop cascade. Hop one: every `ACTIVE` booking leg whose `service_date_id` equals this trip has its owning booking force-cancelled, setting that booking's `booking_status` to `CANCELLED`. Hop two: each force-cancelled booking releases all of its legs, setting each `BookingLeg.leg_state` to `RELEASED`. Hop three runs three parallel restorations: each released leg's ticket, if currently `ISSUED`, is moved to `VOID` and the seat counters are recomputed; if the force-cancelled booking was a `PAID` cash booking, a cash settlement note is created with a penalty percentage of 0 (a full refund) and the booking's `payment_status` is set to `REFUNDED`; and if the force-cancelled booking was pass-funded, the travel pass's `rides_consumed` is decremented by that booking's redeemed leg count and `rides_remaining` is recomputed. The service date's own `version` increments, and every affected booking, leg, ticket, and pass independently has its version bumped and `updated_at` refreshed. A system-cascade refund of this kind always issues cash at a penalty percentage of 0 and bypasses the refundability check that constrains passenger-initiated cash refunds.

### 3.3. Holding Seats: Booking Creation and Inventory Holds

A `Passenger` opens a journey by creating a **Booking** for their own `passenger_id`. A booking carries two parallel state axes: a fulfillment axis, `booking_status`, ranging over `HELD`, `CONFIRMED`, `CANCELLED`, and `EXCHANGED`; and a settlement axis, `payment_status`, ranging over `UNPAID`, `PAID`, `REFUNDED`, and `CREDITED`. A new booking begins `HELD` and `UNPAID`. The booking also declares a `funding_kind` of either `CASH` or `PASS`, defaulting to `CASH`. A `PASS` booking must supply a `pass_id` referencing the travel pass that will fund it, and a `CASH` booking must not supply one; a presence mismatch between `pass_id` and `funding_kind` is a malformed body and is rejected with `ERR_INVALID_REQUEST`.

The create payload includes `legs`, an array in which each entry names a `service_date_id`, a `fare_class_id`, a `leg_order` (the 1-based position of the leg within the journey, at least 1, used to order adjacent legs for the connection-buffer check), and, when the chosen fare class is `RESERVED`, a `seat_number` such as "12A"; for an `OPEN` fare class the seat number must be omitted, and a presence mismatch between `seat_number` and the seating mode is rejected with `ERR_INVALID_REQUEST`. The system creates one **Booking Leg** per entry, each linked to its booking through `booking_id` and beginning in `leg_state` `ACTIVE`. For each leg, the referenced service date's `seats_held` increases by 1, its counters are recomputed, and its `version` is bumped.

At create time the booking's `hold_expires_at` is set to the current clock instant plus the hold time-to-live; a held booking that is not confirmed before that UTC instant has expired. Holding seats requires that, for each leg, the service date's gate be `OPEN` and there be at least one available seat (`seats_available` of at least 1 for the requested legs); a sold-out trip is rejected with `ERR_SOLD_OUT`. For a `RESERVED` leg, the requested `seat_number` must not already be occupied by another `ACTIVE` leg on the same service date, or the hold is rejected with `ERR_SEAT_TAKEN`. A multi-leg booking must also satisfy the connection buffer described in §3.7. For a pass-funded create, the pass must not be `EXPIRED`; redeeming against an expired pass is rejected with `ERR_PASS_EXPIRED`, and a held pass booking that is later found expired at confirm raises the same temporal family handled under `ERR_HOLD_EXPIRED` for the hold itself.

### 3.4. Confirming, Pricing, and Issuing Tickets

A `Passenger` confirms a held booking to lock in fares, consume inventory, and issue travel documents, advancing `booking_status` from `HELD` to `CONFIRMED`. Confirmation is admissible only when the booking is currently `HELD`; otherwise it is rejected with `ERR_INVALID_STATE`. The hold must not have expired — the current clock instant must be strictly before `hold_expires_at`, or the confirm is rejected with `ERR_HOLD_EXPIRED`. For every leg, the referenced service date's `sales` gate must be `OPEN` and its `lifecycle` must be `SCHEDULED` or `DELAYED`, or the confirm is rejected with `ERR_PRECONDITION_NOT_MET`. Seat availability is re-checked at confirm time: each leg's service date must still have at least one available seat, or the confirm is rejected with `ERR_SOLD_OUT`, and any reserved seat must still be free, or `ERR_SEAT_TAKEN`. The multi-leg connection buffer is re-checked. Finally, the confirm carries `expected_service_date_version` and is subject to the optimistic-concurrency check of §2.8.

On a successful confirm, each leg's service date moves one seat from held to sold — `seats_held` decreases by 1 and `seats_sold` increases by 1 — and the counters and `load_factor` are recomputed. The booking's `total_fare_cents` is finalized: for a cash booking it is the sum of the per-leg fares; for a pass booking it is 0. One **Ticket** per leg is issued in state `ISSUED`, each carrying a fresh server-issued `barcode`, a `booking_id`, and a `booking_leg_id` naming the leg it admits travel on. The booking's `version` increments by 1, and each referenced service date's `version` increments by 1. A pass-funded confirm additionally consumes one ride per leg from the pass and bumps the pass's version.

The per-leg fare, recorded as `fare_cents` on each booking leg, is locked at confirm time. For a cash booking it is computed as follows. First the demand multiplier is read from the leg's service date load factor — defined as that service date's `seats_sold` divided by `seats_total`, measured before this booking's seats are moved to sold and counting confirmed legs only. If that load factor is below 0.5 the demand multiplier is 1.00; if it is at least 0.5 but below 0.8 the multiplier is 1.25; and if it is at least 0.8 the multiplier is 1.60 (each tier is lower-inclusive). Next the advance factor is read from the whole-day calendar difference between the trip's `departure_date` and the current clock date, never negative: if that difference is at least 14 days the factor is 0.90; if it is at least 7 but fewer than 14 the factor is 1.00; if it is at least 3 but fewer than 7 the factor is 1.15; and otherwise (fewer than 3 days out) the factor is 1.40. The base fare `base_fare_cents` of the service date is multiplied by the demand multiplier and the advance factor, that product is rounded half up to whole cents, and the fare class's `surcharge_cents` is then added to produce `fare_cents`. For a pass-funded booking there is no demand or advance math at all: `fare_cents` is 0 on every leg, and one travel-pass ride is consumed per leg instead. The booking's `total_fare_cents` is the sum of the `fare_cents` of all `ACTIVE` legs — each leg already rounded — summed exactly; for a pass booking the total is 0.

### 3.5. Payment and the Settlement Axis

Payment advances the settlement axis independently of fulfillment. A `Passenger` pays a confirmed cash booking, moving `payment_status` from `UNPAID` to `PAID`. Paying requires the booking to be `CONFIRMED`, its `funding_kind` to be `CASH`, and its `payment_status` to currently be `UNPAID`; a violation is rejected with `ERR_INVALID_STATE` (or `ERR_PRECONDITION_NOT_MET` where the funding kind disqualifies it). On payment the booking's `total_paid_cents` is set equal to its `total_fare_cents`, and the booking's `version` increments. The captured `total_paid_cents` is the basis for all later refund and credit math; it defaults to 0 and stays 0 for pass bookings, which never go through payment. A pass-funded booking is not paid: confirming it leaves it `UNPAID` with `total_paid_cents` of 0, and `CREDITED` is reachable only via the paid-to-credited refund path described below, never via pass confirmation.

### 3.6. Cancellation, Refunds, and Travel Credit

A `Passenger` (or, on the passenger's behalf, a `SupportAgent`) may cancel a booking. The behavior depends on where the booking sits on its two axes.

Cancelling a still-`HELD` booking simply releases the hold: it requires `booking_status` to be `HELD`, sets every `ACTIVE` leg to `RELEASED`, decrements each affected service date's `seats_held` by 1 with counters recomputed, and bumps the booking's version. If the held booking was pass-funded, the pass's `rides_consumed` is reduced by the redeemed leg count, `rides_remaining` is recomputed, and the pass status is re-derived.

Cancelling a `CONFIRMED` booking is admissible only when no ticket on the booking is in state `SCANNED`; a scanned ticket blocks the cancel with `ERR_PRECONDITION_NOT_MET`. On a successful confirmed-booking cancel, every `ACTIVE` leg is set to `RELEASED`, each affected service date's `seats_sold` decreases by 1 with counters and `load_factor` recomputed, and every `ISSUED` ticket is moved to `VOID`. The booking's version increments. If the booking is pass-funded, the pass rides are restored (`rides_consumed` reduced by the leg count). If the booking was `PAID` and cash-funded, the settlement axis advances and a settlement note is produced according to the `refund_destination` supplied on the cancel request.

The `refund_destination` field is one of `CASH` or `TRAVEL_CREDIT` and is required only when `payment_status` is `PAID`; a cancel of a paid booking that omits it, or a refund/exchange attempted on a booking that is not paid, is rejected with `ERR_NOT_PAID` where the booking is not in a paid state. A cash refund moves `payment_status` from `PAID` to `REFUNDED` and is permitted for a passenger only when every leg's fare class is refundable; if any leg's fare class has `refundable` false, a cash refund is rejected with `ERR_REFUND_NOT_ALLOWED` and only travel credit is available. A travel-credit refund moves `payment_status` from `PAID` to `CREDITED` and is always permitted regardless of refundability.

The amount settled is computed by a single cancellation-settlement calculation with two variants. First the days-before-departure is measured at cancel time as the whole-day calendar difference between the earliest `ACTIVE` leg's service-date `departure_date` and the current clock date. If that difference is at least 7 days the base penalty percentage is 0.00; if it is at least 1 day but fewer than 7 it is 0.25; and otherwise (same-day, fewer than 1 day) it is 0.50. The gross amount is the booking's `total_paid_cents`. For the cash variant the penalty percentage is exactly the base penalty percentage. For the travel-credit variant the penalty percentage is the base penalty percentage minus 0.10, floored at 0.00 — credit is ten percentage points more lenient and never negative. The withheld penalty is the gross multiplied by the chosen penalty percentage, rounded half up to whole cents; the net is the gross minus that penalty, an exact subtraction. The resulting **settlement note** records its `settlement_kind` (`CASH` or `TRAVEL_CREDIT`), the `gross_cents` equal to the booking's `total_paid_cents` at settlement, the withheld `penalty_cents`, and the `net_cents` actually refunded or credited; it is created at the settlement instant and is immutable thereafter. Because the two variants apply different penalty percentages, an identical booking yields a different number and a different entity-level outcome depending on which destination the passenger chooses. A system-driven cascade refund (from a service-date cancellation) always uses the cash variant at a penalty percentage of 0, regardless of the fare classes' refundability.

### 3.7. Multi-Leg Connections

When a booking spans more than one leg, the legs are ordered by `leg_order` and each adjacent pair is checked against the operator's connection buffer. For an inbound leg followed by the next leg, the next leg's scheduled departure minute minus the inbound leg's scheduled arrival minute must be at least the owning operator's `default_connection_buffer_min`, accounting for next-day rollover when a route's arrival minute is earlier than its departure minute. If any adjacent pair leaves too little time, the booking create or confirm is rejected with `ERR_CONNECTION_TOO_TIGHT`. This buffer is evaluated both when the multi-leg booking is created and again when it is confirmed.

### 3.8. Exchanging a Leg

A `Passenger` (or assisting `SupportAgent`) may exchange the leg of a confirmed cash booking onto a different trip, moving the old booking's `booking_status` from `CONFIRMED` to the terminal `EXCHANGED`. An exchange is admissible only when the booking is `CONFIRMED`, its `funding_kind` is `CASH`, and no ticket on it is `SCANNED`; the target trip named by `target_service_date_id` must have its `sales` gate `OPEN`, its `lifecycle` one of `SCHEDULED` or `DELAYED`, and at least one available seat. A scanned ticket or an unsuitable target trip is rejected with `ERR_PRECONDITION_NOT_MET`, a sold-out target with `ERR_SOLD_OUT`, and a target reserved seat already taken with `ERR_SEAT_TAKEN`. The exchange carries `expected_booking_version` and is subject to the optimistic-concurrency check of §2.8.

The exchange body names the `target_service_date_id`, the `target_fare_class_id`, and, for a reserved target class, a `target_seat_number`. On success the old leg is set to `RELEASED` and the old service date's `seats_sold` decreases by 1 with counters recomputed; a new booking is created in `CONFIRMED` and `PAID` status holding the replacement leg on the target trip, with the target service date's `seats_sold` increased by 1; the old booking's tickets are voided and a fresh ticket is issued for the new booking; the old booking's version increments and both service dates' versions increment.

The settled amount is computed in a pinned order to resolve the otherwise circular dependency. Step one computes the new leg's fare against the target service date using the same per-leg pricing as a fresh confirm (fresh demand and advance factors, independent of the old booking). Step two sets the amount due to the new leg's fare minus the old booking's `total_paid_cents` plus the operator's `exchange_fee_cents`. Step three: if the amount due is negative, the surplus is never returned as cash but is issued as a travel-credit settlement note. All quantities are integer cents throughout, and the new leg's fare is already rounded by the per-leg pricing step.

### 3.9. Tickets and Gate Scanning

Each confirmed leg yields one ticket beginning in state `ISSUED` with a unique `barcode`. A `GateAgent` scans a ticket at the gate, advancing its `state` from `ISSUED` to `SCANNED` and bumping the ticket's `version`. Scanning is admissible only when the ticket is currently `ISSUED` — a non-issued ticket is rejected with `ERR_INVALID_STATE` — and only when the service date underlying the ticket's leg has a `lifecycle` of `SCHEDULED`, `DELAYED`, or `DEPARTED`; if that cross-entity precondition fails the scan is rejected with `ERR_PRECONDITION_NOT_MET`. Tickets are also driven to `VOID` automatically by the system, never by a direct request, when their booking is cancelled or exchanged or their service date is cancelled; voiding requires the ticket to be `ISSUED` and bumps its version. `VOID` is terminal. A scanned ticket on a booking is precisely what blocks that booking from being cancelled or exchanged.

### 3.10. Travel Passes and Ride Accounting

A `SupportAgent` issues a **Travel Pass** to a passenger, naming the `passenger_id` of the holder and the `operator_id` on whose service dates the pass may be redeemed, the `rides_total` bundled into the pass (at least 1), and an `expires_on` calendar date after which the pass is expired and can fund no new legs. A new pass starts with `status` `ACTIVE`, `rides_consumed` 0, and `version` 1. The pass tracks two derived quantities: `rides_consumed`, the total count of `ACTIVE` legs across the pass-funded bookings currently redeeming it, and `rides_remaining`, which is `rides_total` minus `rides_consumed` and is never allowed to go negative.

A pass-funded booking confirm consumes one ride per leg; a cancellation or service-date cascade restores them by decrementing `rides_consumed`. The pass status is re-derived from the balance: when `rides_remaining` reaches 0 the pass auto-transitions from `ACTIVE` to `EXHAUSTED`, and when a restore brings `rides_remaining` back above 0 an `EXHAUSTED` pass reverts to `ACTIVE`. Confirming a pass-funded booking requires `rides_remaining` to be at least the leg count; an under-funded pass is rejected with `ERR_PASS_DEPLETED`. Independently, advancing the clock past the pass's `expires_on` drives the pass to the terminal `EXPIRED` state when observed on the next redemption attempt; an expired pass cannot fund new legs, and a redemption against it is rejected with `ERR_PASS_EXPIRED`. Each redeem, restore, and expiry transition bumps the pass version.

### 3.11. Baggage

A checked **Baggage Item** is added to a booking by a `Passenger` or `SupportAgent`, supplying only the bag's `weight_kg` in kilograms (which must be greater than 0); the item is linked to its booking through `booking_id` and starts at `version` 1. Its `fee_cents` is computed as an overweight fee at creation: if the weight is at most the free allowance of 23.0 kilograms the fee is 0; otherwise the fee is the weight minus 23.0 kilograms, multiplied by an overweight rate of 500 cents per kilogram, rounded half up to whole cents. A bag at exactly 23.0 kilograms incurs a fee of 0.

### 3.12. Accessibility Accommodations

A **Passenger** registers with a `full_name`, an `email` that must be unique among passengers (a repeat raises `ERR_DUPLICATE_EMAIL`), and an optional self-declared `needs_accessibility` flag defaulting to false; that flag is informational and does not itself reserve any accessible seating. A passenger begins at `version` 1.

An accessibility accommodation is requested against a specific leg by a `Passenger` or `SupportAgent` as an **Accessibility Request**, linked to the leg through `booking_leg_id` and naming an `accommodation` of `WHEELCHAIR_SPACE`, `COMPANION_SEAT`, or `SERVICE_ANIMAL`. It begins in `status` `REQUESTED`. A `SupportAgent` adjudicates it, either granting it — moving `status` from `REQUESTED` to `GRANTED`, which reserves one accessible slot on the leg's service date — or denying it, moving `status` to `DENIED`. Each adjudication bumps the request's version. A grant is allowed only if the count of `GRANTED` accommodations on that service date would not exceed the per-service-date accessible-slot ceiling; if no slot remains, the grant is rejected with `ERR_ACCESSIBILITY_UNAVAILABLE`.

## 4. Endpoint Definitions

Operations that create a brand-new, standalone resource return `201 Created`. Operations that read a resource or modify an existing one — including all state transitions and the clock control — return `200 OK`. Every endpoint is mounted under the `/v1` prefix shown in the table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the server's current UTC instant | SupportAgent |
| POST | `/v1/operators` | Create a carrier | ScheduleManager |
| GET | `/v1/operators/{operator_id}` | Read an operator | ScheduleManager, FareAnalyst, Passenger, GateAgent, SupportAgent |
| POST | `/v1/fare-classes` | Create a fare class under an operator | FareAnalyst |
| GET | `/v1/fare-classes` | List fare classes, filterable by operator | FareAnalyst, ScheduleManager, Passenger, SupportAgent |
| GET | `/v1/fare-classes/{fare_class_id}` | Read a fare class | FareAnalyst, ScheduleManager, Passenger, SupportAgent |
| POST | `/v1/fare-classes/{fare_class_id}/retire` | Retire a fare class | FareAnalyst |
| POST | `/v1/routes` | Create a route under an operator | ScheduleManager |
| GET | `/v1/routes` | List routes, filterable by operator | ScheduleManager, FareAnalyst, Passenger, SupportAgent |
| GET | `/v1/routes/{route_id}` | Read a route | ScheduleManager, FareAnalyst, Passenger, SupportAgent |
| POST | `/v1/routes/{route_id}/publish` | Publish a route | ScheduleManager |
| POST | `/v1/service-dates` | Schedule a service date on a published route | ScheduleManager |
| GET | `/v1/service-dates` | List service dates, filterable by route | ScheduleManager, FareAnalyst, Passenger, SupportAgent |
| GET | `/v1/service-dates/{service_date_id}` | Read a service date with live counters and load factor | ScheduleManager, FareAnalyst, Passenger, GateAgent, SupportAgent |
| POST | `/v1/service-dates/{service_date_id}/delay` | Mark a service date delayed | ScheduleManager |
| POST | `/v1/service-dates/{service_date_id}/restore` | Restore a delayed service date to scheduled | ScheduleManager |
| POST | `/v1/service-dates/{service_date_id}/depart` | Mark a service date departed | ScheduleManager |
| POST | `/v1/service-dates/{service_date_id}/cancel` | Cancel a service date (depth-3 cascade) | ScheduleManager |
| POST | `/v1/service-dates/{service_date_id}/suspend-sales` | Suspend sales on a service date | ScheduleManager |
| POST | `/v1/service-dates/{service_date_id}/resume-sales` | Resume sales on a service date | ScheduleManager |
| POST | `/v1/passengers` | Register a passenger | SupportAgent, Passenger |
| GET | `/v1/passengers/{passenger_id}` | Read a passenger | Passenger, SupportAgent |
| POST | `/v1/passes` | Issue a multi-ride travel pass | SupportAgent |
| GET | `/v1/passes` | List travel passes, filterable by passenger or operator | Passenger, SupportAgent |
| GET | `/v1/passes/{pass_id}` | Read a travel pass | Passenger, SupportAgent |
| POST | `/v1/bookings` | Create a held booking with one or more legs | Passenger |
| GET | `/v1/bookings/{booking_id}` | Read a booking | Passenger, SupportAgent, GateAgent |
| GET | `/v1/bookings` | List bookings, filterable by passenger or pass | Passenger, SupportAgent |
| POST | `/v1/bookings/{booking_id}/confirm` | Confirm a held booking | Passenger |
| POST | `/v1/bookings/{booking_id}/pay` | Capture payment for a confirmed cash booking | Passenger |
| POST | `/v1/bookings/{booking_id}/cancel` | Cancel a held or confirmed booking | Passenger, SupportAgent |
| POST | `/v1/bookings/{booking_id}/exchange` | Exchange the leg of a confirmed cash booking | Passenger, SupportAgent |
| GET | `/v1/legs` | List booking legs, filterable by booking, service date, or fare class | Passenger, SupportAgent, GateAgent |
| GET | `/v1/legs/{booking_leg_id}` | Read a single booking leg | Passenger, SupportAgent, GateAgent |
| GET | `/v1/tickets` | List tickets, filterable by booking or leg | Passenger, SupportAgent, GateAgent |
| GET | `/v1/tickets/{ticket_id}` | Read a ticket | Passenger, SupportAgent, GateAgent |
| POST | `/v1/tickets/{ticket_id}/scan` | Scan a ticket at the gate | GateAgent |
| POST | `/v1/bookings/{booking_id}/baggage` | Add a checked baggage item to a booking | Passenger, SupportAgent |
| GET | `/v1/baggage` | List baggage items, filterable by booking | Passenger, SupportAgent |
| GET | `/v1/baggage/{baggage_item_id}` | Read a baggage item | Passenger, SupportAgent |
| POST | `/v1/legs/{booking_leg_id}/accessibility-requests` | Request an accessibility accommodation on a leg | Passenger, SupportAgent |
| GET | `/v1/accessibility-requests` | List accessibility requests, filterable by leg | Passenger, SupportAgent |
| GET | `/v1/accessibility-requests/{accessibility_request_id}` | Read an accessibility request | Passenger, SupportAgent |
| POST | `/v1/accessibility-requests/{accessibility_request_id}/grant` | Grant an accessibility accommodation | SupportAgent |
| POST | `/v1/accessibility-requests/{accessibility_request_id}/deny` | Deny an accessibility accommodation | SupportAgent |
| GET | `/v1/settlement-notes` | List settlement notes, filterable by booking | Passenger, SupportAgent |
| GET | `/v1/settlement-notes/{settlement_note_id}` | Read a settlement note | Passenger, SupportAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRECONDITION_NOT_MET` | 409 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_CONNECTION_TOO_TIGHT` | 409 |
| `ERR_SEAT_TAKEN` | 409 |
| `ERR_SOLD_OUT` | 409 |
| `ERR_REFUND_NOT_ALLOWED` | 409 |
| `ERR_PASS_DEPLETED` | 409 |
| `ERR_PASS_EXPIRED` | 409 |
| `ERR_ACCESSIBILITY_UNAVAILABLE` | 409 |
| `ERR_FARE_CLASS_RETIRED` | 409 |
| `ERR_ROUTE_NOT_PUBLISHED` | 409 |
| `ERR_NOT_PAID` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
