# Riverboat Dinner Cruise API — Product Requirements Document

## 1. Introduction

A riverboat dinner cruise line sells two products off the same hull inventory: per-seat tickets for scheduled public sailings, and full-boat private charters negotiated through a sales pipeline. Every sailing is bounded by the vessel's Coast Guard certified capacity, provisioned from the galley against the live reservation book, crewed by staff whose alcohol-server certifications must be current, and exposed to weather that can hold a departure, cancel a cruise outright, and ripple through guest refunds, galley orders, berth assignments, and shore-side parking. This document specifies the API that serves as the system of record for all of it: cruise inventory, bookings and payment state, the boarding manifest, galley provisioning, staffing, charter negotiation, weather events and guest credits, dock scheduling, and parking.

Several operating principles recur throughout. Money is always integer cents, and every calculation pins its own rounding steps. Time is a logical clock under operator control, never the wall clock. Seats, parking stalls, and berths are finite pools governed by explicit capacity arithmetic. And cancellation is never a single-entity event — it is a cascade that must leave every dependent record in a consistent terminal state. Engineers implementing this service should treat §2 as the structural contract and §3 as the complete behavioral specification; the endpoint table in §4 is deliberately a summary, and the full request and response semantics of every operation are defined by the narratives that precede it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes six roles, spelled exactly as follows. `OperationsManager` runs cruise inventory, scheduling, weather cancellation, charter conversion, and staffing. `Captain` is the vessel master and owns manifest freeze/amend plus departure and completion. `Customer` is the paying guest and owns bookings, passengers, parking passes, and charter acceptance. `CharterSalesAgent` owns the charter pipeline — opening inquiries and posting quotes — and never converts a charter, by segregation of duties. `GalleyManager` owns galley provisioning. `DockAttendant` runs shore-side operations: boarding check-in and parking. An attempt to perform an operation outside the roles authorized for it in §4 is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a Customer compare the resource's customer foreign-key field to `X-User-ID`. When `X-User-Role` is `OperationsManager`, `Captain`, `CharterSalesAgent`, `GalleyManager`, or `DockAttendant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. One controlled step does compare two operator identifiers against each other: charter conversion requires the converting `OperationsManager`'s `X-User-ID` to differ from the accepting `Customer`'s `X-User-ID` (see §3.9).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints additionally accept optional equality filters. The cruise list may be narrowed by `status` or `vessel_id`; a cruise's booking list by `booking_status`, `payment_status`, or `customer_id`; the charter inquiry list by `status`, `cruise_id`, or `customer_id`; a cruise's provision orders, staff assignments, and the weather event list by `status`; and a customer's credit list by `credit_status`.

### 2.4. The Logical Clock

Every time-dependent rule in the system reads a single server-side logical clock; the wall clock is never consulted. Before any call to set it, the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default. An `OperationsManager` may advance or set the clock through an admin-only test-driving capability whose request body carries a `to_iso8601` timestamp; the response reports the resulting reading as `current_utc`. Setting the clock re-evaluates all time-based automatic transitions against the new reading — most notably the expiry of unanswered charter quotes.

The logical clock governs, among other things: the comparison against alcohol-server certification expiries (both when a bartender assignment is confirmed and whenever bar service eligibility is recomputed), the stamping of `declared_at` on weather events, the stamping of `boarded_at` at passenger check-in, and the hours-of-notice measurement used by the weather-credit calculation. One age rule deliberately does not read the clock: a passenger's minor status is measured against the cruise's scheduled departure instant, not against "now" (see §3.3).

### 2.5. Common Resource Properties

All primary resources — vessels, docks, menu tiers, cruises, customers, bookings, boarding manifests, staff members, staff assignments, galley provision orders, charter inquiries, weather events, dock slots, and parking passes — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix. Every resource is addressed by its `id` in URL paths.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource, including modifications driven by cascades and by recomputation of derived fields.

Two resources are deliberately lighter. A booking passenger record and a cruise credit record carry only `id` and `created_at`; both `updated_at` and `version` are absent on those two resources. Because every modification elsewhere increments `version`, a client that reads a resource, then writes against it, can always state which revision it observed — the mechanism §2.9 builds on.

The system renders every stored instant in one canonical style: UTC with exactly three fractional digits and a `Z` suffix — `2026-08-10T16:45:00.000Z`, never `2026-08-10T16:45:00Z`. Server-stamped instants (`created_at`, `updated_at`, and stamps such as `declared_at` and `boarded_at`) are always produced in this style. User-supplied instant fields are likewise normalized on the way in: a cruise's `depart_at` and `return_at`, a dock slot's `slot_start` and `slot_end`, and a weather event's `window_start` and `window_end` are each parsed from whatever ISO 8601 form the client sends, converted to UTC, and then stored and returned in the canonical rendering; and the clock-set call of §2.4 reports the new reading `current_utc` in the same style. Comparisons and calculations always operate on the parsed instant, never on the client's original string, so two request strings denoting the same instant behave identically.

### 2.6. Cents, Covers, and Rounding Discipline

All monetary values in the system are integer cents. Whenever a calculation produces a fractional cent at a pinned rounding step, the value is rounded half-up to whole cents; each calculation in §3 states exactly where its rounding steps sit, and the pinned order of those steps is part of the contract. Galley provisioning load is the one non-monetary decimal quantity: load units are carried to two decimal places, rounded half-up. Counts — covers, passengers, stalls, rounds — are always integers. Berth windows and turnaround buffers are compared at minute granularity. No calculation in this document may be reordered, aggregated differently, or evaluated at a different precision than stated; two formulations that would agree mathematically but differ in rounding placement are different calculations here.

### 2.7. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers, the system validates the existence of each identifier in a sequential, left-to-right order, and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve. A check-in call against a missing booking, for example, yields `ERR_BOOKING_NOT_FOUND` before the passenger identifier is ever examined; a valid booking with a missing passenger yields `ERR_PASSENGER_NOT_FOUND`.

The not-found family is exhaustive and maps one-to-one to resource types: a missing vessel yields `ERR_VESSEL_NOT_FOUND`; a dock, `ERR_DOCK_NOT_FOUND`; a menu tier, `ERR_MENU_TIER_NOT_FOUND`; a cruise, `ERR_CRUISE_NOT_FOUND`; a booking, `ERR_BOOKING_NOT_FOUND`; a booking passenger, `ERR_PASSENGER_NOT_FOUND`; a boarding manifest, `ERR_MANIFEST_NOT_FOUND`; a provision order, `ERR_PROVISION_ORDER_NOT_FOUND`; a staff member, `ERR_STAFF_MEMBER_NOT_FOUND`; a staff assignment, `ERR_ASSIGNMENT_NOT_FOUND`; a customer, `ERR_CUSTOMER_NOT_FOUND`; a cruise credit, `ERR_CREDIT_NOT_FOUND`; a charter inquiry, `ERR_INQUIRY_NOT_FOUND`; a weather event, `ERR_WEATHER_EVENT_NOT_FOUND`; a dock slot, `ERR_DOCK_SLOT_NOT_FOUND`; and a parking pass, `ERR_PARKING_PASS_NOT_FOUND`. All sixteen are HTTP 404.

### 2.8. The Validation Ladder

Before the business ladder below runs, request shape is validated: a malformed JSON body, an unrecognized enum value in any field, a missing required field, or an inverted time range — a cruise whose `return_at` is not later than its `depart_at`, a dock slot whose `slot_end` is not later than its `slot_start`, or a weather window whose `window_end` is not later than its `window_start` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

When a request is well-formed and an endpoint enforces several of the following rules, the system evaluates them in this fixed order, and the first failure determines the error returned:

1. Header presence and well-formedness — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role permission for the operation per the §4 matrix — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. Existence of every path identifier, validated left to right — the appropriate `ERR_*_NOT_FOUND` (404) from §2.7.
4. Target entity state permits the requested transition — `ERR_INVALID_STATE` (409).
5. The cruise is in a status permitting booking-level mutations, namely `SCHEDULED` — `ERR_CRUISE_NOT_BOOKABLE` (409). This rung guards booking creation, payment, customer cancellation, provision-order placement, staff-assignment confirmation, and charter quoting and conversion.
6. Coast Guard capacity — the resulting `reserved_covers` or `boarded_count` must not exceed the vessel's certified `coast_guard_capacity` — `ERR_CAPACITY_EXCEEDED` (409). This rung guards booking creation, passenger check-in, manifest freeze, opening boarding, and departure.
7. Alcohol service rules — bartender certification at confirmation (`ERR_ALCOHOL_CERT_EXPIRED`, 409) and bar-service availability when paying for beverage packages (`ERR_BAR_SERVICE_UNAVAILABLE`, 409).
8. Berth turnaround-buffer overlap for the same vessel — `ERR_DOCK_SLOT_CONFLICT` (409).
9. Dock parking pool headroom — `ERR_PARKING_FULL` (409).
10. Charter negotiation rounds remaining — `ERR_QUOTE_ROUNDS_EXHAUSTED` (409).
11. A covering severe-weather event exists for a weather cancellation — `ERR_NO_ACTIVE_WEATHER_EVENT` (409).
12. All affected bookings still await settlement before credits settle — `ERR_CREDITS_NOT_PENDING` (409).
13. Segregation of duties on controlled two-sided steps — `ERR_SEGREGATION_OF_DUTIES` (403).
14. Optimistic-concurrency freshness — `ERR_STALE_VERSION` (412).
15. Manifest frozen where required — `ERR_MANIFEST_NOT_FROZEN` (409), guarding the opening of boarding and departure.
16. At least one provisional cover before a provision order is placed — `ERR_NO_COVERS_TO_PROVISION` (422).
17. The vessel is in service when a cruise is scheduled — `ERR_VESSEL_OUT_OF_SERVICE` (409).

Two consequences of this fixed ordering are worth stating plainly. A request that is both stale (rung 14) and in breach of capacity (rung 6) is rejected with `ERR_CAPACITY_EXCEEDED`, because capacity is evaluated first. And a weather cancellation attempted without a covering event fails at rung 11 even if the cruise's own state would have been acceptable at rung 4.

### 2.9. Optimistic Concurrency Control

Exactly two write operations in the API take an optimistic-concurrency token, and for both the token is a non-optional request field.

Creating a booking against a cruise requires `expected_cruise_version`, carrying the `version` of the cruise as the client last observed it. If the cruise's current `version` does not match — for example because another writer has just created or cancelled a booking, legitimately changing `reserved_covers` and therefore the capacity headroom the current writer believes remains — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than allowing a sale computed from a stale view of remaining capacity. Booking creation itself increments the cruise's `version` by one, so every successful sale invalidates every previously observed revision.

Posting a charter quote requires `expected_inquiry_version`, carrying the `version` of the charter inquiry as the sales agent last observed it. If the inquiry's current `version` does not match — for example because the customer has just posted a counter, legitimately advancing `quote_round` — the quote is rejected with `ERR_STALE_VERSION` (HTTP 412). Both the quote and counter actions increment the inquiry's `version` by one.

No endpoint other than these two accepts a version field of any kind; all other writes rely on the state machine and the validation ladder alone.

### 2.10. Derived Counters and Cascading Consistency

Several resources carry derived counters that the server recomputes immediately whenever an underlying event occurs — never lazily at read time. These are: a cruise's `reserved_covers`, `boarded_count`, and `bar_service_enabled`; a dock's `parking_in_use`; a customer's `credit_balance_cents`; and a boarding manifest's `passenger_count` while the manifest remains in `DRAFT`. Each recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version` per §2.5.

Parent state transitions cascade to dependent records in the same request or system pass. The fullest example is weather cancellation of a cruise, which in one cascade moves bookings into refund processing, issues guest credits, cancels the galley order with a restocking rebate when applicable, releases parking passes, releases crew assignments, and advances the driving weather event — every step of which is enumerated in §3.8. Completion of a voyage likewise files the manifest, settles the provision order, and strands no-shows in a single act (§3.6). A faithful implementation applies all listed cascade steps atomically with the transition that triggers them.

## 3. Business Logic & Workflows

### 3.1. Piers, Vessels, and Menu Tiers

Everything sellable hangs off three kinds of standing inventory. A **Dock** is created by an `OperationsManager` with a `name` and a `parking_capacity` — the count of shore-side parking stalls attached to that pier. Its `parking_in_use` counter starts at zero and thereafter tracks how many stalls are spoken for (§3.7).

A **Vessel** is registered with a display `name`, its `coast_guard_capacity` — the certified maximum passenger count from the vessel's USCG Certificate of Inspection, which is a hard upper bound on boarding everywhere in the system — and a `home_dock_id` identifying the dock where the vessel is home-ported; the set of vessels home-ported at a dock can be listed through the dock. A vessel's `status` is `ACTIVE` when created. Taking a vessel out of service moves it from `ACTIVE` to `OUT_OF_SERVICE`; scheduling a cruise on a vessel that is not `ACTIVE` is rejected with `ERR_VESSEL_OUT_OF_SERVICE` (rung 17).

A **MenuTier** carries a `code` of `STANDARD`, `PREMIUM`, or `LUXE`; a per-person `base_price_cents` charged before any discount, seasonal multiplier, or holiday premium; a `galley_load_per_cover` expressing how many provisioning load units one reserved cover consumes on that tier; and a per-person `bar_package_price_cents` for the beverage package, which is subject to its own per-line rounding rule (§3.3). The cruises sold on a tier can be listed back from the tier.

### 3.2. Scheduling Cruises and Berthing the Fleet

An `OperationsManager` schedules a **CruiseInstance** by naming the operating `vessel_id`, the `menu_tier_id` being sold, a scheduled departure instant `depart_at`, and a scheduled return instant `return_at` (all times UTC). The return must be strictly later than the departure, or the request fails as `ERR_INVALID_REQUEST`. From `depart_at` the server derives two computed fields. The cruise's `season` is `PEAK` when the departure month is June, July, or August; `SHOULDER` when it is May or September; and `OFF` in every other month. The flag `is_holiday` is true exactly when the departure's UTC calendar date falls in the fixed holiday set: 2026-07-04, 2026-09-07, 2026-12-25, or 2026-12-31.

A new cruise begins with `status` `SCHEDULED`, `reserved_covers` zero, `boarded_count` zero, `bar_service_enabled` false, and `charter_booking_id` null. Scheduling also auto-creates the cruise's **BoardingManifest** in `DRAFT` status, carrying a snapshot of the vessel's `coast_guard_capacity` taken at manifest creation; exactly one manifest ever exists per cruise. The cruise list can be filtered by `status` or `vessel_id`, and individual cruises are readable by every role.

Alongside cruise scheduling, an `OperationsManager` reserves berth windows. A **DockSlot** is created under a dock with a `vessel_id`, a `slot_start`, and a `slot_end`, the latter strictly later than the former (`ERR_INVALID_REQUEST` otherwise). Slots occupy half-open intervals: the vessel is committed from `slot_start` up to but not including `slot_end`. Two slots naming the same vessel — regardless of which docks they sit at — conflict whenever the first slot's start falls before the second slot's end plus a forty-five-minute turnaround buffer, and the second slot's start falls before the first slot's end plus the same buffer. Adjacency exactly at the earlier slot's end plus forty-five minutes is permitted: the buffer is a gap requirement, not an occupancy extension. A creation that would violate this rule is rejected with `ERR_DOCK_SLOT_CONFLICT`. Slots are listed per dock or per vessel.

### 3.3. Selling Seats: Customers, Bookings, and Ticket Pricing

Guests enter the system when an `OperationsManager` registers a **Customer** with an `email` and a `full_name`; email addresses are unique across customers, and a registration reusing an existing address is rejected as an invalid request. A customer's `credit_balance_cents` starts at zero and later reflects issued and settled credits (§3.8).

A `Customer` creates a **Booking** against a specific cruise with a payload naming the paying `customer_id`, a `party_size` of at least one, an optional `bar_package_count` (default zero, and never greater than `party_size`), and — mandatorily — the optimistic-concurrency token `expected_cruise_version` described in §2.9. Violations of these input-shape rules are rejected with `ERR_INVALID_REQUEST`. The cruise must be `SCHEDULED` or the sale fails with `ERR_CRUISE_NOT_BOOKABLE`; and if adding this party would push the cruise's `reserved_covers` above the vessel's `coast_guard_capacity`, the sale fails with `ERR_CAPACITY_EXCEEDED`. A booking is born with `payment_status` `PENDING` and `booking_status` `RESERVED`; these two state dimensions evolve in parallel — `payment_status` walks `PENDING`, `PAID`, `REFUND_PENDING`, `REFUNDED`, and `CREDITED`, while `booking_status` walks `RESERVED`, `CONFIRMED`, `BOARDED`, `NO_SHOW`, `CANCELLED`, and `CONVERTED_TO_CHARTER` — and the booking is terminal once payment stands at `REFUNDED` or `CREDITED`, or the booking stands at `CANCELLED`, `CONVERTED_TO_CHARTER`, or `NO_SHOW`. On creation the server computes `booking_total_cents` and `bar_package_total_cents` per the pinned pricing below, recomputes the cruise's `reserved_covers`, and increments the cruise's `version` by one.

A cruise's `reserved_covers` is defined precisely: the sum of `party_size` over the cruise's bookings whose `booking_status` is `RESERVED`, `CONFIRMED`, or `BOARDED` and whose `payment_status` is `PENDING`, `PAID`, or `REFUND_PENDING`.

Ticket pricing is a pinned four-step evaluation, in this exact order. First, the base line is the booking's `party_size` multiplied by the menu tier's `base_price_cents`. Second, a party-size discount is applied to that line: parties of ten or more receive fifteen percent off; parties of six to nine receive ten percent off; parties of four or five receive five percent off; parties of three or fewer receive no discount. The discounted line is rounded half-up to whole cents — the first pinned rounding step. Third, the discounted line is multiplied by the cruise's seasonal multiplier: 1.25 for a `PEAK` sailing, 1.10 for `SHOULDER`, and 1.00 for `OFF`; the product is rounded half-up to whole cents — the second pinned rounding step. Fourth, only when the cruise's `is_holiday` flag is true, a flat holiday premium of 1,500 cents per passenger — the `party_size` multiplied by 1,500 cents — is added to the seasonal result; on non-holiday departures nothing is added. The result is the booking's `booking_total_cents`. The order discount, then seasonal multiplier, then holiday premium is fixed and may not be rearranged.

The beverage package has its own pinned rounding. For each package purchased, a gratuity line of eighteen percent of the tier's `bar_package_price_cents` is computed and rounded half-up to whole cents; the per-package price is then the `bar_package_price_cents` plus that rounded gratuity; and the booking's `bar_package_total_cents` is the per-package price multiplied by `bar_package_count`. Rounding each package line first and then multiplying is pinned — computing eighteen percent on the aggregate and rounding once is a different, non-conformant calculation.

Each passenger travels on a **BookingPassenger** record, added one call per passenger to an existing booking with the passenger's `full_name` (as it will be shown to the Coast Guard) and `date_of_birth`. From the date of birth the server derives `is_minor`: true when the passenger's age at the cruise's scheduled departure instant is under twenty-one years — the US alcohol-service benchmark — and this flag drives alcohol-service denial. A passenger's `boarded_at` is null until boarding check-in stamps it (§3.6), and each passenger record is tied to its booking through `booking_id`.

Paying for a booking is gated four ways: the booking's `payment_status` must be `PENDING` and its `booking_status` must be `RESERVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`); the cruise must be `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`); and when `bar_package_count` is greater than zero, the cruise's `bar_service_enabled` must be true at that moment (otherwise `ERR_BAR_SERVICE_UNAVAILABLE` — see §3.4 for how that flag is earned). On successful payment the ticket total is recomputed and frozen into `booking_total_cents`, the beverage total is stored into `bar_package_total_cents`, `payment_status` moves to `PAID`, a `RESERVED` booking advances automatically to `CONFIRMED`, and the cruise's `reserved_covers` is recomputed.

A `Customer` may cancel their own booking while it stands at `RESERVED` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and only while the cruise is still `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`). Cancellation moves the booking to `CANCELLED`, moves `payment_status` to `REFUNDED` when it had been `PAID` (an unpaid booking simply cancels), and recomputes the cruise's `reserved_covers`.

### 3.4. Crew Assignments and Alcohol-Service Compliance

A **StaffMember** is registered by an `OperationsManager` with a `full_name`, a `role_code` of `SERVER`, `BARTENDER`, `GALLEY`, `ENTERTAINER`, or `DECKHAND`, and an optional `alcohol_cert_expires_at` — the expiry instant of the worker's state alcohol-server certification, left null for roles that never serve alcohol.

An `OperationsManager` crews a cruise by creating a **StaffAssignment** under that cruise (the cruise's `id` in the path becomes the record's `cruise_id`) and naming the `staff_member_id` and the `assigned_role` (the same five role codes); the assignment starts in `ASSIGNED` status. Confirming an assignment requires it to stand at `ASSIGNED` (otherwise `ERR_INVALID_STATE`), requires the cruise to be `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`), and — when the `assigned_role` is `BARTENDER` — requires the referenced staff member's `alcohol_cert_expires_at` to be later than the current logical clock reading, failing with `ERR_ALCOHOL_CERT_EXPIRED` when the certification has lapsed. Confirmation moves the assignment to `CONFIRMED` and recomputes the cruise's `bar_service_enabled`. An assignment can be released from either `ASSIGNED` or `CONFIRMED` — by an explicit release from an `OperationsManager`, or automatically when the cruise is weather-cancelled (§3.8) — moving it to `RELEASED`, which is terminal; either path recomputes `bar_service_enabled`.

That flag is the cruise's license to pour. `bar_service_enabled` starts false and is true only while at least one `CONFIRMED` staff assignment on the cruise references a staff member whose `alcohol_cert_expires_at` is later than the current logical clock reading. Because the comparison is against the live clock, advancing time can silently flip the flag even with no staffing change; and because §3.3 gates beverage-package payment on it, a booking carrying a positive `bar_package_count` can only be paid while certified staff stand confirmed on the cruise. Minors, flagged by `is_minor`, are never served regardless of the flag.

### 3.5. Provisioning the Galley

The galley works from **GalleyProvisionOrder** records, of which at most one non-cancelled order may exist for a cruise at any time. A `GalleyManager` creates an order in `DRAFT` status; at creation the server computes the forward-looking `provisional_covers` — the sum of `party_size` over the cruise's bookings whose `booking_status` is `RESERVED` or `CONFIRMED` and whose `payment_status` is `PENDING` or `PAID` — and derives `provision_load_units` as the `provisional_covers` multiplied by the menu tier's `galley_load_per_cover`, carried to two decimal places and rounded half-up. Note the provisional booking set deliberately includes unpaid (`PENDING`) reservations and excludes `BOARDED` ones, so it does not coincide with the `reserved_covers` definition in §3.3.

Placing the order requires it to stand at `DRAFT` (otherwise `ERR_INVALID_STATE`), requires the cruise to be `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`), and requires at least one provisional cover — an order with zero covers is rejected with `ERR_NO_COVERS_TO_PROVISION` (HTTP 422). Placement moves the order to `PLACED` and recomputes `provision_load_units`. Receipt of goods moves a `PLACED` order to `RECEIVED`. When the cruise completes (§3.6), an order standing at `PLACED` or `RECEIVED` settles automatically to `SETTLED`, and its `final_covers` is computed on the chronological variant: the count of the cruise's booking passengers with a non-null `boarded_at`, plus the count of the cruise's staff assignments standing at `CONFIRMED` — crew meals are provisioned in the settlement, not the forecast. The two cover counts legitimately disagree whenever reservations diverge from boarded reality; no-shows consume forecast covers but not final ones, and confirmed crew appear only in the final. A `DRAFT` order left over at completion is simply not settled by it.

Weather cancellation retires the order instead (§3.8): a `DRAFT` order moves to `CANCELLED` with no further effect, while a `PLACED` order moves to `CANCELLED` and earns a restocking rebate — `restocking_rebate_cents` is computed as 300 cents multiplied by the order's `provisional_covers`, and that rebate later flows into the guests' final weather credits. The rebate field defaults to zero and stays zero on every path other than the placed-at-cancellation one.

### 3.6. Manifest, Boarding, and the Voyage

The boarding manifest is the Coast Guard-facing document. It exists exactly once per cruise, created in `DRAFT` at scheduling time with the vessel's capacity snapshot in its own `coast_guard_capacity` field (§3.2). Its `passenger_count` starts at zero and counts the cruise's booking passengers whose `boarded_at` is non-null; while the manifest is in `DRAFT` this count is recomputed as boarding events occur, and once the manifest is frozen the count is a held snapshot. Reading the manifest yields a collection of zero or one element.

The `Captain` freezes the manifest, moving it from `DRAFT` to `FROZEN`. Freezing requires the manifest to stand at `DRAFT` (otherwise `ERR_INVALID_STATE`) and requires the current `passenger_count` not to exceed the snapshot `coast_guard_capacity` (otherwise `ERR_CAPACITY_EXCEEDED`); at freeze time the passenger count is snapshotted. Should a late correction be needed before boarding opens, the `Captain` may amend the manifest, returning it from `FROZEN` to `DRAFT` — permitted only while the cruise itself is still `SCHEDULED`, otherwise `ERR_INVALID_STATE` — and this `DRAFT` → `FROZEN` → `DRAFT` amendment cycle may repeat. On cruise completion the manifest moves from `FROZEN` to `FILED` automatically and is terminal.

With a frozen manifest in hand, an `OperationsManager` opens boarding, moving the cruise from `SCHEDULED` to `BOARDING`. Opening requires the cruise to stand at `SCHEDULED` (otherwise `ERR_INVALID_STATE`), requires the manifest to exist and stand at `FROZEN` (otherwise `ERR_MANIFEST_NOT_FROZEN`), and requires `reserved_covers` to sit within the vessel's `coast_guard_capacity` (otherwise `ERR_CAPACITY_EXCEEDED`). As boarding opens, the manifest's `passenger_count` snapshot is recomputed one final time.

While the cruise is in `BOARDING`, a `DockAttendant` checks passengers in one at a time; attempting check-in in any other cruise state fails with `ERR_INVALID_STATE`. Check-in stamps the passenger's `boarded_at` from the logical clock, and a check-in that would push the count of boarded passengers beyond the vessel's certified capacity is rejected with `ERR_CAPACITY_EXCEEDED`. Each check-in recomputes the cruise's `boarded_count` — the count of the cruise's booking passengers with non-null `boarded_at`. When every passenger of a `CONFIRMED` booking has boarded, that booking advances automatically from `CONFIRMED` to `BOARDED`, recomputing `boarded_count` again and refreshing the manifest's `passenger_count` if the manifest is still in `DRAFT`.

The `Captain` then departs, moving the cruise from `BOARDING` to `UNDERWAY`. Departure requires the `BOARDING` state (otherwise `ERR_INVALID_STATE`), requires `boarded_count` within certified capacity (otherwise `ERR_CAPACITY_EXCEEDED`), and requires the manifest to stand at `FROZEN` (otherwise `ERR_MANIFEST_NOT_FROZEN`). Departure strands no-shows: every booking standing at `PAID` and `CONFIRMED` whose passengers all remain unboarded moves to `NO_SHOW`. Departure also sweeps the parking pool — every parking pass for this cruise still standing at `RESERVED` expires (§3.7).

After the voyage, the `Captain` completes the cruise, moving it from `UNDERWAY` to `COMPLETED` — the only precondition is the `UNDERWAY` state, enforced as `ERR_INVALID_STATE`. Completion is a settling act with four cascades, applied together: the manifest moves from `FROZEN` to `FILED`; the galley provision order, if standing at `PLACED` or `RECEIVED`, moves to `SETTLED` with its `final_covers` computed on the chronological variant (§3.5); bookings standing at `BOARDED` remain `BOARDED`; and any booking still standing at `CONFIRMED` with not a single boarded passenger moves to `NO_SHOW`. As with every mutation, completing the cruise refreshes its `updated_at` and increments its `version` by one.

### 3.7. Shore-Side Parking

Each dock's parking is a single shared pool. A **ParkingPass** is created under a dock — the dock's `id` in the path becoming the record's `dock_id` — by a `Customer` or a `DockAttendant`, naming the `booking_id` it is attached to and the `cruise_id` whose date it is valid for; the pass begins in `RESERVED` status and the dock's `parking_in_use` is incremented. The capacity check is aggregate-count semantics over the pool: `parking_in_use` counts the dock's passes standing at `RESERVED` or `REDEEMED`, and a new pass is allowed only while that count is strictly below the dock's `parking_capacity` — the final stall is usable, so a count exactly one short of capacity admits the pass, while a count equal to capacity rejects it with `ERR_PARKING_FULL`. Passes for the same cruise date draw on the same pool regardless of arrival hour; there is no time-slicing.

A `DockAttendant` redeems a pass at the lot, moving it from `RESERVED` to `REDEEMED`; redemption requires the pass to stand at `RESERVED` and the associated cruise to stand at `SCHEDULED` or `BOARDING` — any other state fails with `ERR_INVALID_STATE`. A redeemed pass keeps its stall: `REDEEMED` still counts toward `parking_in_use`. Releasing a pass — by a `DockAttendant`'s explicit release, or automatically when the cruise is weather-cancelled — moves a `RESERVED` pass to `RELEASED` and decrements `parking_in_use`. And when a cruise departs with a pass still `RESERVED`, that pass expires automatically to `EXPIRED`, again decrementing `parking_in_use`. `REDEEMED`, `RELEASED`, and `EXPIRED` are all terminal. Passes can be listed by dock, by booking, or by cruise.

### 3.8. Weather, Cancellation, and Guest Credits

An `OperationsManager` declares a **WeatherEvent** with a `severity` of `ADVISORY`, `GALE_WARNING`, or `CANCELLATION_REQUIRED` and an affected window from `window_start` to `window_end`, the end strictly later than the start (`ERR_INVALID_REQUEST` otherwise). The server stamps `declared_at` from the logical clock and the event begins in `DECLARED` status. When the severity is `CANCELLATION_REQUIRED`, declaration immediately places every still-`SCHEDULED` cruise whose scheduled departure instant falls inside the window into `WEATHER_HOLD`; lesser severities declare without holding anything.

A held cruise can be released to sail. Clearing a weather hold moves the cruise from `WEATHER_HOLD` back to `SCHEDULED` and is permitted while the covering event stands at `DECLARED` or `CLOSED` — an operator may elect to sail despite a declared event — but once the covering event has advanced to `CANCELLATION_ISSUED`, clearing is rejected with `ERR_WEATHER_EVENT_ACTIVE`. The `SCHEDULED` → `WEATHER_HOLD` → `SCHEDULED` cycle may repeat across distinct weather events.

When a cruise cannot sail, the `OperationsManager` weather-cancels it. The cruise must stand at `SCHEDULED` or `WEATHER_HOLD` (otherwise `ERR_INVALID_STATE`), and there must exist a covering `CANCELLATION_REQUIRED` event standing at `DECLARED` or `CANCELLATION_ISSUED` (otherwise `ERR_NO_ACTIVE_WEATHER_EVENT`). The cancellation then executes a six-part cascade, atomically:

1. Every booking of the cruise whose `payment_status` is `PENDING` or `PAID` moves to `REFUND_PENDING`, and its `booking_status` moves to `CANCELLED`. Bookings already cancelled by their customers are untouched by the cascade.
2. For each such booking a **CruiseCredit** is created in `ISSUED` status with a provisional `amount_cents`: the number of whole hours between the current logical clock reading and the cruise's scheduled `depart_at` selects a percentage — at least seventy-two hours of notice yields one hundred percent; at least twenty-four but fewer than seventy-two yields seventy-five percent; at least six but fewer than twenty-four yields fifty percent; fewer than six hours yields twenty-five percent — and the provisional amount is the booking's frozen `booking_total_cents` multiplied by that percentage, rounded half-up to whole cents.
3. The cruise's provision order, if standing at `DRAFT` or `PLACED`, moves to `CANCELLED`; if it stood at `PLACED`, its `restocking_rebate_cents` is computed as 300 cents per provisional cover (§3.5).
4. The driving weather event moves from `DECLARED` to `CANCELLATION_ISSUED` — this happens on the first weather-cancel beneath it.
5. Every parking pass for the cruise standing at `RESERVED` moves to `RELEASED`, decrementing the dock's `parking_in_use` once per released pass.
6. Every staff assignment for the cruise standing at `ASSIGNED` or `CONFIRMED` moves to `RELEASED`, with `bar_service_enabled` recomputed.

Credits are then settled under the event, not per cruise. An `OperationsManager` settles credits for an event that stands at `CANCELLATION_ISSUED` (otherwise `ERR_INVALID_STATE`), and only when every booking on every cruise cancelled under the event still stands at `REFUND_PENDING` — if any such booking has moved on, settlement is rejected with `ERR_CREDITS_NOT_PENDING`. For each `REFUND_PENDING` booking the final credit is computed: the base recomputes the identical hours-of-notice percentage against the same frozen `booking_total_cents`, rounded half-up to whole cents; when the cruise's provision order stood at `PLACED` at cancellation time, the restocking rebate of 300 cents per `provisional_covers` is added; and a flat processing fee of 450 cents is subtracted, yielding the credit's `final_amount_cents`. The credit moves from `ISSUED` to `SETTLED`, the booking's `payment_status` moves from `REFUND_PENDING` to `CREDITED`, each affected customer's `credit_balance_cents` is recomputed, and the event itself advances from `CANCELLATION_ISSUED` to `CREDITS_SETTLED`, which is terminal.

An event that never triggers a cancellation can instead be closed: moving it from `DECLARED` to `CLOSED` requires the `DECLARED` state (otherwise `ERR_INVALID_STATE`) and requires that no covered cruise remain in `WEATHER_HOLD` (otherwise `ERR_WEATHER_HOLDS_OUTSTANDING`). `CLOSED` is terminal.

A cruise credit's `credit_status` walks `ISSUED`, `SETTLED`, `REDEEMED`, and `EXPIRED`. A customer's `credit_balance_cents` is the sum over their credits of the `amount_cents` while a credit stands at `ISSUED`, the `final_amount_cents` while it stands at `SETTLED`, and zero once it stands at `REDEEMED` or `EXPIRED`. A `Customer` may redeem a settled credit against their balance, moving it from `SETTLED` to `REDEEMED` and recomputing the balance; credits are listed per customer (filterable by `credit_status`), per booking, and readable individually.

### 3.9. Private Charters: From Inquiry to Conversion

A `CharterSalesAgent` opens a **CharterInquiry** naming the target `cruise_id` and the charter client's `customer_id`; the inquiry begins in `DRAFT` with its `quote_round` counter at zero. The negotiation then alternates between two sides. The agent posts a quote: from `DRAFT` this requires only that the target cruise be `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`), and it moves the inquiry to `QUOTED`, computing `quoted_total_cents` and incrementing `quote_round`. The customer counters a standing quote, moving the inquiry from `QUOTED` to `COUNTERED` and incrementing `quote_round`; the agent re-quotes a countered inquiry, moving it from `COUNTERED` back to `QUOTED`, recomputing `quoted_total_cents`, and incrementing `quote_round`. Both the counter and the re-quote are capped: they require `quote_round` to still be below six rounds, failing with `ERR_QUOTE_ROUNDS_EXHAUSTED` once the negotiation has used them up; the opening quote from `DRAFT` does not consult the cap. Every quote posting must carry the `expected_inquiry_version` token of §2.9 — an agent quoting from a stale view of the negotiation is rejected with `ERR_STALE_VERSION` (HTTP 412) — and every quote or counter increments the inquiry's `version` by one.

The quoted amount is deterministic. The operating vessel's `coast_guard_capacity` selects a tier: forty-nine or fewer passengers is the small tier, fifty through ninety-nine is the medium tier, and one hundred or more is the large tier. The tier's base price — 350,000 cents for small, 620,000 cents for medium, 980,000 cents for large — is multiplied by the cruise's seasonal multiplier, the same 1.25-for-`PEAK`, 1.10-for-`SHOULDER`, 1.00-for-`OFF` ladder used in ticket pricing, and the product is rounded half-up to whole cents exactly once. The quote leans on the cruise's `season`, which derives from `depart_at`; conversion never moves the departure and never re-quotes, so there is no circularity.

The customer accepts a standing quote, moving the inquiry from `QUOTED` to `ACCEPTED` (only `QUOTED` accepts; anything else fails `ERR_INVALID_STATE`). The customer may instead decline from either `QUOTED` or `COUNTERED`, moving the inquiry to `DECLINED`. Left unanswered, a quote standing at `QUOTED` lapses automatically to `EXPIRED` once the logical clock passes forty-eight hours after the quote was posted; `DECLINED`, `EXPIRED`, and `CONVERTED` are all terminal.

Conversion is the controlled step, and segregation of duties guards both halves of the negotiation: the agent posting a quote and the customer countering it must be different operators, and the `OperationsManager` converting an accepted inquiry must not be the customer who accepted it — the converting request compares the two `X-User-ID` values and rejects a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Beyond that, conversion requires the inquiry to stand at `ACCEPTED` (otherwise `ERR_INVALID_STATE`) and the cruise to be `SCHEDULED` (otherwise `ERR_CRUISE_NOT_BOOKABLE`). A successful conversion executes as one cascade: the server creates a new booking for the charter client with `booking_status` `CONFIRMED`, `payment_status` `PAID`, and `party_size` equal to the vessel's full `coast_guard_capacity`, and points the cruise's `charter_booking_id` at it; every pre-existing booking of the cruise standing at `RESERVED` or `CONFIRMED` moves to `CONVERTED_TO_CHARTER`, and when such a booking had been `PAID` its `payment_status` moves to `CREDITED` with a conversion CruiseCredit issued in `ISSUED` status for the booking's frozen `booking_total_cents` less a twelve-percent conversion fee — that is, eighty-eight percent of the frozen total, in integer cents under the system-wide rounding rule; and the cruise's `reserved_covers` is recomputed, reading exactly the certified capacity. The inquiry lands in `CONVERTED`. A booking that became a charter booking can be traced back to its cruise through the reverse read, which returns a collection of zero or one cruise.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. Created and modified resources are returned in the envelope's `data` field per §2.2. The table below is a summary only — request fields, computed response fields, preconditions, and cascade side effects for every operation are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | OperationsManager |
| POST | `/vessels` | Create a vessel | OperationsManager |
| POST | `/vessels/{id}/set-out-of-service` | Take a vessel out of service | OperationsManager |
| GET | `/vessels` | List vessels | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/vessels/{id}` | Get a vessel | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| POST | `/docks` | Create a dock | OperationsManager |
| GET | `/docks` | List docks | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/docks/{id}` | Get a dock | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/docks/{id}/vessels` | List vessels home-ported at a dock | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/docks/{id}/dock-slots` | List dock slots for a dock | OperationsManager, Captain, DockAttendant |
| GET | `/docks/{id}/parking-passes` | List parking passes for a dock | OperationsManager, Captain, DockAttendant |
| POST | `/menu-tiers` | Create a menu tier | OperationsManager |
| GET | `/menu-tiers` | List menu tiers | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/menu-tiers/{id}` | Get a menu tier | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| POST | `/cruises` | Schedule a cruise | OperationsManager |
| GET | `/cruises` | List cruises | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/cruises/{id}` | Get a cruise | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| POST | `/cruises/{id}/open-boarding` | Open boarding | OperationsManager |
| POST | `/cruises/{id}/depart` | Depart | Captain |
| POST | `/cruises/{id}/complete` | Complete cruise | Captain |
| POST | `/cruises/{id}/clear-weather-hold` | Clear weather hold | OperationsManager |
| POST | `/cruises/{id}/weather-cancel` | Weather-cancel a cruise | OperationsManager |
| POST | `/cruises/{id}/bookings` | Create a booking (OCC on cruise) | Customer |
| GET | `/cruises/{id}/bookings` | List bookings for a cruise | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/bookings/{id}` | Get a booking | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/bookings/{id}/passengers` | List passengers of a booking | OperationsManager, Captain, Customer, DockAttendant |
| POST | `/bookings/{id}/passengers` | Add a passenger to a booking (one call per passenger) | Customer |
| POST | `/bookings/{id}/pay` | Pay for a booking | Customer |
| POST | `/bookings/{id}/cancel` | Cancel a booking | Customer |
| POST | `/bookings/{id}/passengers/{id}/check-in` | Boarding check-in for one passenger | DockAttendant |
| GET | `/cruises/{id}/manifest` | Get the cruise's boarding manifest (array of 0 or 1) | OperationsManager, Captain |
| POST | `/cruises/{id}/manifest/freeze` | Freeze manifest | Captain |
| POST | `/cruises/{id}/manifest/amend` | Amend (unfreeze) manifest | Captain |
| POST | `/cruises/{id}/provision-orders` | Create a provision order (DRAFT) | GalleyManager |
| GET | `/cruises/{id}/provision-orders` | List provision orders for a cruise | OperationsManager, Captain, GalleyManager |
| POST | `/cruises/{id}/provision-orders/{id}/place` | Place the order | GalleyManager |
| POST | `/cruises/{id}/provision-orders/{id}/receive` | Receive the order | GalleyManager |
| POST | `/staff-members` | Create a staff member | OperationsManager |
| GET | `/staff-members` | List staff members | OperationsManager, Captain, GalleyManager |
| GET | `/staff-members/{id}` | Get a staff member | OperationsManager, Captain, GalleyManager |
| GET | `/staff-members/{id}/assignments` | List assignments of a staff member | OperationsManager, Captain, GalleyManager |
| POST | `/cruises/{id}/staff-assignments` | Assign staff to a cruise | OperationsManager |
| GET | `/cruises/{id}/staff-assignments` | List staff assignments for a cruise | OperationsManager, Captain, GalleyManager |
| POST | `/cruises/{id}/staff-assignments/{id}/confirm` | Confirm an assignment | OperationsManager |
| POST | `/cruises/{id}/staff-assignments/{id}/release` | Release an assignment | OperationsManager |
| POST | `/customers` | Register a customer | OperationsManager |
| GET | `/customers` | List customers | OperationsManager, CharterSalesAgent |
| GET | `/customers/{id}` | Get a customer | OperationsManager, CharterSalesAgent, Customer |
| GET | `/customers/{id}/bookings` | List a customer's bookings | OperationsManager, CharterSalesAgent, Customer |
| GET | `/customers/{id}/credits` | List a customer's cruise credits | OperationsManager, CharterSalesAgent, Customer |
| POST | `/credits/{id}/redeem` | Redeem a settled credit against the balance | Customer |
| POST | `/charter-inquiries` | Open a charter inquiry | CharterSalesAgent |
| GET | `/charter-inquiries` | List charter inquiries | OperationsManager, CharterSalesAgent, Customer |
| GET | `/charter-inquiries/{id}` | Get a charter inquiry | OperationsManager, CharterSalesAgent, Customer |
| POST | `/charter-inquiries/{id}/quote` | Post a quote (OCC on inquiry) | CharterSalesAgent |
| POST | `/charter-inquiries/{id}/counter` | Customer counters the quote | Customer |
| POST | `/charter-inquiries/{id}/accept` | Customer accepts the quote | Customer |
| POST | `/charter-inquiries/{id}/decline` | Customer declines | Customer |
| POST | `/charter-inquiries/{id}/convert` | Convert cruise to private charter | OperationsManager |
| POST | `/weather-events` | Declare a weather event | OperationsManager |
| GET | `/weather-events` | List weather events | OperationsManager, Captain |
| GET | `/weather-events/{id}` | Get a weather event | OperationsManager, Captain |
| POST | `/weather-events/{id}/settle-credits` | Settle all provisional credits for the event | OperationsManager |
| POST | `/weather-events/{id}/close` | Close an event without cancellations | OperationsManager |
| POST | `/docks/{id}/dock-slots` | Create a dock slot | OperationsManager |
| GET | `/dock-slots/{id}` | Get a dock slot | OperationsManager, Captain, DockAttendant |
| GET | `/vessels/{id}/dock-slots` | List dock slots for a vessel | OperationsManager, Captain, DockAttendant |
| POST | `/docks/{id}/parking-passes` | Create a parking pass | Customer, DockAttendant |
| GET | `/parking-passes/{id}` | Get a parking pass | OperationsManager, DockAttendant, Customer |
| GET | `/bookings/{id}/parking-passes` | List parking passes attached to a booking | OperationsManager, DockAttendant, Customer |
| GET | `/cruises/{id}/parking-passes` | List parking passes for a cruise | OperationsManager, DockAttendant |
| POST | `/parking-passes/{id}/redeem` | Redeem a pass | DockAttendant |
| POST | `/parking-passes/{id}/release` | Release a pass | DockAttendant |
| GET | `/menu-tiers/{id}/cruises` | List cruises sold on a menu tier | OperationsManager, Captain, CharterSalesAgent, Customer, GalleyManager, DockAttendant |
| GET | `/bookings/{id}/charter-cruises` | List cruises chartered by a booking (array of 0 or 1) | OperationsManager, CharterSalesAgent, Customer |
| GET | `/credits/{id}` | Get a cruise credit | OperationsManager, CharterSalesAgent, Customer |
| GET | `/bookings/{id}/credits` | List credits issued for a booking | OperationsManager, CharterSalesAgent, Customer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VESSEL_NOT_FOUND` | 404 Not Found |
| `ERR_DOCK_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_CRUISE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_PASSENGER_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_PROVISION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INQUIRY_NOT_FOUND` | 404 Not Found |
| `ERR_WEATHER_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOCK_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PARKING_PASS_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CRUISE_NOT_BOOKABLE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_MANIFEST_NOT_FROZEN` | 409 Conflict |
| `ERR_ALCOHOL_CERT_EXPIRED` | 409 Conflict |
| `ERR_BAR_SERVICE_UNAVAILABLE` | 409 Conflict |
| `ERR_DOCK_SLOT_CONFLICT` | 409 Conflict |
| `ERR_PARKING_FULL` | 409 Conflict |
| `ERR_QUOTE_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_NO_ACTIVE_WEATHER_EVENT` | 409 Conflict |
| `ERR_WEATHER_EVENT_ACTIVE` | 409 Conflict |
| `ERR_WEATHER_HOLDS_OUTSTANDING` | 409 Conflict |
| `ERR_CREDITS_NOT_PENDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NO_COVERS_TO_PROVISION` | 422 Unprocessable Entity |
| `ERR_VESSEL_OUT_OF_SERVICE` | 409 Conflict |
