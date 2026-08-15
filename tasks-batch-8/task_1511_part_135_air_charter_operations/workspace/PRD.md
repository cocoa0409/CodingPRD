# Part 135 Air Charter Operations API — Product Requirements Document

## 1. Introduction

A Part 135 charter operator sells on-demand flights against a fleet it does not wholly own. Every trip begins as a sales inquiry priced off a published category rate card — before any specific tail is chosen — and only later binds to an aircraft, a crew, a passenger manifest, and, for international work, a stack of overflight and landing permits. Along the way the operator must prove crew duty and rest legality, keep every tail clear of its 100-hour inspection ceiling, screen each passenger under the applicable TSA program, honor a tiered cancellation and weather-waiver refund policy, and settle each completed trip with the aircraft's owner under a revenue-share agreement that may include a per-block-minute minimum guarantee. FAA operations-specification compliance hangs over all of it: a tail not on the certificate cannot be confirmed, and an open grounding finding stops both dispatch and return-to-service.

This document specifies the API through which the operator runs that business. The API is the single system of record for the registry (owners, aircraft, crew), the sales pipeline (trip requests, quote legs, payments), the operations pipeline (aircraft and crew assignments, dispatch, flight logs), and the compliance surface (screenings, permits, findings, maintenance windows). Consistency is immediate: every state change, cascade, and derived amount is applied within the request that triggers it, and all time-dependent behavior — quote expiry, screening validity, permit validity, maintenance-window activation — is driven by a controllable logical clock rather than wall-clock time. All endpoints are mounted under the `/charter` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are exactly seven: `OpsAdmin`, `SalesAgent`, `DispatchManager`, `MaintenanceController`, `ComplianceOfficer`, `AircraftOwner`, and `CrewMember`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is not permitted on the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five staff roles are opaque identities. When `X-User-Role` is `OpsAdmin`, `SalesAgent`, `DispatchManager`, `MaintenanceController`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

The two remaining roles are entity-backed. When `X-User-Role` is `AircraftOwner`, `X-User-ID` is the `id` of the acting `AircraftOwner`; ownership checks on any resource that references an `AircraftOwner` compare the resource's owner reference to `X-User-ID` — concretely, an owner listing revenue-share statements may read only its own, and any other owner's statements yield `ERR_FORBIDDEN`. When `X-User-Role` is `CrewMember`, `X-User-ID` is the `id` of the acting `CrewMember`; recording a flight log requires it to equal the `crew_member_id` of a vetted pilot-in-command assignment on that trip, and any other crew identity yields `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Based Expiry

All time-dependent behavior in the system is evaluated against a logical clock, never wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z. An `OpsAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; every phrase in this document of the form "current clock" or "now" refers to this logical clock.

Every clock advance runs a time-based expiry sweep in a pinned order — trip requests first, then passengers, then overflight permits, then maintenance windows. In detail: a trip request still in `QUOTED` status whose `quote_valid_until` now lies in the past transitions to `EXPIRED` and its `version` increments; a passenger whose `tsa_status` is `CLEARED` and whose screening is now more than 72 hours old transitions to `EXPIRED`; an overflight permit in `GRANTED` status now more than 30 days past its decision transitions to `EXPIRED`; and a maintenance window in `PLANNED` status whose `starts_at` has been reached activates — provided its aircraft is not `IN_TRIP`, since activation is skipped while the tail is flying and re-evaluated on the next clock set — moving the window to `ACTIVE` and an `AVAILABLE` aircraft to `MAINTENANCE_HOLD`.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time as ISO 8601 UTC with three fractional digits. The `updated_at` timestamp refreshes on every mutation of the resource. The `version` is a system-managed integer that increments by one on every mutation, including mutations applied by system cascades.

Three resources are immutable ledger-style records and break this pattern: a `Payment`, a `FlightLog`, and a `WeatherAdvisory` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these three resources.

### 2.6. Money, Rates, and Rounding Discipline

All monetary values are integer cents — quoted totals, deposits, payments, fees, refunds, statement lines, and the hourly rate card alike. Every rounding in a monetary calculation uses round-half-up to the nearest whole cent. Where a calculation has multiple rounding steps, the rounding order is pinned: each per-leg charge is rounded half up to whole cents first, and only then are the leg charges summed. Summing raw unrounded amounts and rounding once at the end produces a different number and is not acceptable. The same discipline applies to multi-step fees: the volume discount is rounded half up on its own, and the fuel surcharge is then computed on the discounted amount and rounded half up again.

### 2.7. Optimistic Concurrency Control

Two write endpoints guard against stale snapshots of a trip request by optimistic concurrency control: requoting a quoted trip, and creating an aircraft assignment. Both require the request body to carry `expected_trip_request_version`, holding the `version` of the `TripRequest` the client last observed. If the supplied value does not equal the trip's current `version` — because another writer has quoted, booked, requoted, or otherwise advanced the trip since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This check is evaluated before the state preconditions of the endpoint, so a stale version surfaces as `ERR_STALE_VERSION` rather than being masked by a state error. No endpoint other than these two accepts a version field.

### 2.8. Occupancy Windows and Interval Arithmetic

Aircraft scheduling is governed by two kinds of intervals, and the distinction is contractual. An aircraft assignment occupies its tail over a buffered, half-open interval: `occupied_start_at` is the trip's `departure_at` minus a 45-minute turnaround buffer, and `occupied_end_at` is the trip's `departure_at` plus the sum of the planned block minutes of all the trip's legs plus the same 45-minute turnaround buffer. When two confirmed assignments on the same tail are tested for conflict, the test is intersection of half-open intervals — one assignment ending exactly when another begins does not conflict.

Maintenance windows and weather advisories, by contrast, use closed intervals on both ends, and the maintenance-conflict test is deliberately stricter: a maintenance window conflicts with a flight when the window's closed interval from `starts_at` to `ends_at` intersects the raw flight interval running from `departure_at` to `departure_at` plus the total planned block minutes — and touching endpoints count as intersection. The same closed-interval, touching-counts rule applies when two maintenance windows on the same tail are tested against each other.

### 2.9. Cascading Consistency Across the Operations Graph

The operations graph is small but densely connected, and several single operations mutate more than one entity. The system's rule is that cascades are complete and immediate: when a triggering event fires, every dependent record it reaches is resolved within the same request, and each mutated resource refreshes its `updated_at` and increments its `version`. Grounding an aircraft releases its tentative and confirmed assignments and knocks any booked trip that lost its confirmed aircraft back to quoted status; completing a trip resolves the aircraft's status, releases the crew, and drafts the owner's statement; cancelling a trip releases assignments and crew and may return a dispatched aircraft to service; entering maintenance hold releases the tail's tentative assignments. A client never observes a half-applied cascade.

### 2.10. Nested Resource Retrieval and Existence Validation

Requests that address nested resources — a trip's legs, manifest, payments, permits, or statements, or an aircraft's maintenance windows — are validated left to right along the path. The server confirms each path identifier exists before looking at the next one, and the first missing identifier determines the error: a nonexistent owner id yields `ERR_AIRCRAFT_OWNER_NOT_FOUND`, a nonexistent aircraft id yields `ERR_AIRCRAFT_NOT_FOUND`, a nonexistent crew id yields `ERR_CREW_MEMBER_NOT_FOUND`, a nonexistent trip id yields `ERR_TRIP_REQUEST_NOT_FOUND`, and likewise `ERR_QUOTE_LEG_NOT_FOUND`, `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`, `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`, `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND` for their respective resources, each with HTTP 404. The same existence rule covers foreign keys supplied in request bodies — a payload naming a nonexistent `trip_request_id`, `aircraft_id`, `crew_member_id`, `owner_id`, or `quote_leg_id` fails with the corresponding 404 — and a compliance finding's `subject_id` must exist in the collection named by its `subject_type`. Payments and weather advisories are collection-only resources: they are listed and created but never fetched individually.

### 2.11. Validation Priority Order

Every request is evaluated against an ordered validation cascade, and the first failing check determines the error returned. The order is:

1. Authentication context — both headers present and the role declared; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT`.
2. Authorization and ownership — the role is permitted on the endpoint and, for entity-backed roles, the ownership rule of §2.1 holds; otherwise `ERR_FORBIDDEN`.
3. Request-body shape — required fields present, enum values valid, and amounts that must be positive (`block_minutes`, `amount_cents`, `actual_block_minutes`, `seats`) greater than zero; otherwise `ERR_INVALID_REQUEST`.
4. Time-range coherence on the three endpoints that accept intervals — maintenance window creation, weather advisory publication, and flight log recording; an end at or before its start yields `ERR_INVALID_TIME_RANGE`.
5. Existence — path identifiers and body foreign keys, validated left to right per §2.10; the resource-specific 404 applies.
6. Optimistic concurrency — on the two endpoints that declare `expected_trip_request_version`, the supplied version must equal the trip's current `version`; this tier is evaluated before the state preconditions below, and a mismatch yields `ERR_STALE_VERSION`.
7. State preconditions — the target resource must be in a valid state for the requested transition; the 409 state-error family applies.
8. FAA and TSA compliance gates — ops-spec membership at assignment confirm, type qualification at crew-assignment creation, the full dispatch gate sequence, and the grounding-finding check at return-to-service; the 422 compliance family applies.
9. Interval conflicts — schedule and maintenance conflicts at assignment confirm, maintenance and window-overlap conflicts at window creation, and weather-advisory coverage at weather cancellation; the 409 conflict family applies.
10. Cross-reference consistency — category match at confirm, leg-to-trip match and duplicate-log rejection at flight-log recording, and duplicate-permit rejection at permit creation; the 422 family applies.
11. Money gates, always last — deposit sufficiency at booking, payment-state and overpayment limits on manual payments, and balance settlement at dispatch; the 402 family applies.

## 3. Business Logic & Workflows

### 3.1. Registry Onboarding: Owners, Aircraft, and Crew

Before a single trip can be sold, an `OpsAdmin` builds the registry. An aircraft owner is registered with its legal `name`, a `contact_email`, the `revenue_share_pct` it earns of gross charter revenue (a number from 0 to 100), and optionally a `guarantee_cents_per_block_min` minimum guarantee per logged block minute, which defaults to 0 when omitted. The guarantee splits owners into two settlement variants: an owner with a zero guarantee settles under the STANDARD variant, while a positive guarantee enables the GUARANTEED variant described in §3.9.

Each aircraft tail is registered with its `owner_id`, a unique `tail_number`, a `category` of exactly one of `TURBOPROP`, `LIGHT_JET`, `MIDSIZE_JET`, or `HEAVY_JET`, its `home_base_icao`, the certified passenger `seats` count, the `hourly_rate_cents` used when this actual tail bills a completed trip, the `on_ops_spec` flag recording whether the tail is listed on the operator's FAA operations specifications, the `initial_airframe_minutes` already flown at registration, and the `next_check_due_minutes` airframe reading at which the next 100-hour inspection falls due. A new tail starts in `AVAILABLE` status, and its `total_airframe_minutes` is initialized to `initial_airframe_minutes`; thereafter the total accumulates the `actual_block_minutes` of every flight log from trips on which this aircraft held the `CONFIRMED` assignment. Over its life a tail moves among `AVAILABLE`, `IN_TRIP`, `MAINTENANCE_HOLD`, and `GROUNDED`.

Crew members are registered with a `name`, a `base_icao`, and `qualified_categories`, the array of aircraft category enums the member is type-qualified to fly. A new crew member starts `ACTIVE`; an `OpsAdmin` may later patch its `status` to `SUSPENDED` and back to `ACTIVE`.

### 3.2. Trip Requests and Itinerary Construction

A `SalesAgent` opens the sales pipeline by creating a trip request with the `customer_name` and `customer_email`, the `requested_category` (one of the four category enums), the `origin_icao` and `destination_icao`, the planned first-leg `departure_at` as an ISO 8601 UTC instant, the planned `passenger_count`, and the `international` flag marking whether the trip crosses a border. The trip is born in `QUOTE_DRAFT` status with its `payment_posture` at `UNPAID`. Two status axes now run in parallel: the booking axis (`QUOTE_DRAFT`, `QUOTED`, `BOOKED`, `DISPATCHED`, and the terminals `COMPLETED`, `CANCELLED`, `EXPIRED`) is driven by explicit actions, while the payment axis (`UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, and the post-cancellation `REFUNDED_PARTIAL` and `REFUNDED_FULL`) is derived solely from posted payment rows and is never set directly. Until the trip is priced, `quoted_total_cents`, `deposit_required_cents`, and `quote_valid_until` are all null; `final_total_cents` stays null until completion; and `cancellation_reason`, `cancellation_fee_cents`, and `refund_cents` stay null unless the trip is cancelled.

The itinerary is built leg by leg. Each quote leg names its `trip_request_id`, a `seq_no` sequencing it ascending within the trip, a `leg_type` of `REVENUE` or `POSITIONING`, the leg's `origin_icao` and `destination_icao`, the planned `block_minutes` (which must be greater than zero), and an optional `fuel_stop` flag that defaults to false. Legs may be added or removed only while the trip is in `QUOTE_DRAFT`; either operation against a trip in any other status is rejected with `ERR_TRIP_NOT_QUOTE_DRAFT`. Because the itinerary drives crew legality, adding or deleting a leg forces a re-vet loop: every crew assignment on the trip sitting in `VETTED` or `FLAGGED_ILLEGAL` returns to `PROPOSED`, with `duty_legal`, `rest_legal`, and `vetted_at` cleared.

### 3.3. Quoting and the Category Rate Card

With at least one leg in place — pricing a legless trip fails with `ERR_INVALID_REQUEST` — a `SalesAgent` prices a `QUOTE_DRAFT` trip (any other status yields `ERR_TRIP_NOT_QUOTE_DRAFT`). Quoting uses the published category rate card, not any aircraft's own hourly rate, because no tail has been assigned yet: `TURBOPROP` bills at 150000 cents per block hour, `LIGHT_JET` at 250000, `MIDSIZE_JET` at 400000, and `HEAVY_JET` at 650000. Each leg is priced in `seq_no` ascending order: the leg's planned `block_minutes` multiplied by the category's hourly rate and divided by sixty gives the raw charge, a `POSITIONING` leg's raw charge is then multiplied by 0.6, and the leg charge is rounded half up to whole cents — per the pinned rounding order of §2.6, each leg rounds first and the rounded leg charges then sum to the legs total.

Discounts and surcharges apply in a pinned evaluation order. First the volume discount is taken from the legs total: a legs total of at least 5000000 cents earns a discount of ten percent of the legs total, rounded half up; a legs total below that but of at least 2000000 cents earns five percent, rounded half up; below 2000000 cents there is no discount. Next the fuel surcharge is computed as eight percent of the discounted amount — the legs total minus the volume discount — rounded half up; computing the surcharge on the pre-discount total is a different, wrong number. A fuel-stop fee of 15000 cents is added for each leg whose `fuel_stop` is true, and a flat international fee of 250000 cents applies when the trip's `international` flag is true. The `quoted_total_cents` is the legs total minus the volume discount plus the fuel surcharge, the stop fees, and the international fee. The `deposit_required_cents` is one quarter of the quoted total, rounded half up. The `quote_valid_until` is stamped at the current clock plus 48 hours, the trip moves to `QUOTED`, and its `version` increments. If any tentative aircraft assignments already hang on the trip — possible after a requote cycle — their `occupied_start_at` and `occupied_end_at` are recomputed from the current legs, since the itinerary may have changed.

A quoted trip can be sent back for re-pricing. Requoting requires the trip to be `QUOTED` (otherwise `ERR_TRIP_NOT_QUOTED`) and carries the optimistic-concurrency guard of §2.7: the request must present `expected_trip_request_version` equal to the trip's current `version`, or it is rejected with `ERR_STALE_VERSION`. Requoting clears `quoted_total_cents`, `deposit_required_cents`, and `quote_valid_until` to null, returns the trip to `QUOTE_DRAFT`, increments its `version`, and forces the same re-vet loop as an itinerary change — `VETTED` and `FLAGGED_ILLEGAL` crew assignments fall back to `PROPOSED` with their computed fields cleared. Left alone, a quoted trip does not last: when a clock advance carries the logical clock past `quote_valid_until`, the sweep of §2.4 moves the trip from `QUOTED` to `EXPIRED` and increments its `version`.

### 3.4. Booking, Payments, and the Cancellation Policy

Booking converts a quote into a commitment. A `SalesAgent` books a trip in `QUOTED` status (otherwise `ERR_TRIP_NOT_QUOTED`) by supplying `deposit_cents`. The booking must arrive while the quote is still alive — at or before `quote_valid_until` on the logical clock; past that instant the sweep has already moved the trip to `EXPIRED`. The deposit must be at least the `deposit_required_cents`, or booking is rejected with `ERR_DEPOSIT_INSUFFICIENT`. A successful booking creates a payment row of type `DEPOSIT` for the supplied amount in `POSTED` status, recomputes the `payment_posture` — `DEPOSIT_PAID` normally, or `PAID_IN_FULL` immediately if the deposit happens to cover the entire quote — moves the trip to `BOOKED`, and increments its `version`.

Payments are an append-only ledger. Every payment row carries the `trip_request_id` it pays against, a `payment_type` of `DEPOSIT`, `BALANCE`, or `REFUND`, an `amount_cents` strictly greater than zero, and a `status` that is always `POSTED` — the only value it ever takes. Deposit rows are created only through booking and refund rows only through cancellation; the manual payment capability exists for balance collection and accepts only `BALANCE` payments on trips in `BOOKED` or `DISPATCHED` status — a manual `DEPOSIT` or `REFUND`, or a balance payment on a trip in any other status, is rejected with `ERR_PAYMENT_STATE_INVALID`. A balance payment may not exceed the trip's outstanding balance, defined as `quoted_total_cents` minus `collected_cents`; overpayment is rejected with `ERR_OVERPAYMENT`. Every posted payment recomputes two derived values on the trip: `collected_cents`, the sum of all posted deposit and balance amounts minus the sum of posted refunds, and the `payment_posture` — on a non-cancelled trip, a net collection of zero reads `UNPAID`, a net collection below the quoted total reads `DEPOSIT_PAID`, and a net collection at or above the quoted total reads `PAID_IN_FULL`.

Cancellation is a `SalesAgent` action carrying a `reason` of `CUSTOMER`, `WEATHER`, or `OPS`, and the cancellable states depend on the reason. A `CUSTOMER` cancellation is allowed from `QUOTE_DRAFT`, `QUOTED`, or `BOOKED`; a `WEATHER` or `OPS` cancellation is additionally allowed from `DISPATCHED`. Cancelling from `COMPLETED`, `CANCELLED`, or `EXPIRED` — or a `CUSTOMER` cancellation from `DISPATCHED` — is rejected with `ERR_TRIP_NOT_CANCELLABLE`. A `WEATHER` cancellation must be backed by a published weather advisory whose `station_icao` matches the trip's `origin_icao` or `destination_icao` and whose closed effective window contains the trip's `departure_at`; without one, the cancellation is rejected with `ERR_NO_ACTIVE_WEATHER_ADVISORY`. (Advisories themselves are published by a `DispatchManager` with a `station_icao`, a `severity` of `SIGMET`, `CONVECTIVE`, `WINTER`, or `OTHER`, and a closed `starts_at`-to-`ends_at` window whose end must lie after its start, on pain of `ERR_INVALID_TIME_RANGE`.)

The refund policy tiers on the time remaining before departure, measured in hours from the current clock to `departure_at` with fractional hours allowed, and it computes against the amount actually collected, not the quoted total. A `WEATHER` or `OPS` cancellation waives the fee entirely. For a `CUSTOMER` cancellation, at least 72 hours before departure the fee is ten percent of `collected_cents`; at least 24 hours but less than 72 hours before, the fee is fifty percent; under 24 hours, the fee is the entire collected amount. Boundary precision matters: exactly 72.0 hours before departure falls in the ten-percent tier, and exactly 24.0 hours falls in the fifty-percent tier. The `cancellation_fee_cents` is the collected amount times the tier percentage, rounded half up, and the `refund_cents` is the collected amount minus the fee. When the refund is positive, a `POSTED` payment of type `REFUND` is created for it; when the refund is zero, no payment row appears. The `payment_posture` then recomputes on the cancelled trip: a positive refund with a zero fee reads `REFUNDED_FULL`, a positive refund with a positive fee reads `REFUNDED_PARTIAL`, and a zero refund leaves the pre-cancellation posture unchanged. The `cancellation_reason` is recorded, and the cancellation cascades: every aircraft assignment of the trip in `TENTATIVE` or `CONFIRMED` is released; if the released assignment was `CONFIRMED` and its aircraft was `IN_TRIP` — the post-dispatch cancellation case — the aircraft returns to `AVAILABLE`, unless an `ACTIVE` maintenance window exists on it, in which case it goes to `MAINTENANCE_HOLD`; and every crew assignment in `PROPOSED`, `VETTED`, or `FLAGGED_ILLEGAL` is released. The trip's `version` increments.

### 3.5. Assigning the Tail: Assignments, Maintenance Windows, and Grounding

A `DispatchManager` attaches an aircraft to a quoted or booked trip by creating an aircraft assignment naming the `trip_request_id` and the `aircraft_id`. The create carries the second optimistic-concurrency guard of §2.7 — `expected_trip_request_version` must equal the trip's current `version`, or the request is rejected with `ERR_STALE_VERSION` — because creating an assignment legitimately supersedes whatever tentative assignment the trip already has, and a writer acting on an old snapshot of the trip must be turned away. The trip must be `QUOTED` or `BOOKED`; creating an assignment against a trip in any other status is rejected with `ERR_INVALID_STATE`. The new assignment is born `TENTATIVE`, any prior `TENTATIVE` assignment on the same trip is released in the same motion, the buffered occupancy window is computed per §2.8, and the trip's `version` increments.

Confirming an assignment is where the fleet gates bite, and each gate maps to its own error. The assignment must be `TENTATIVE` (`ERR_ASSIGNMENT_NOT_TENTATIVE` otherwise). The trip must be `BOOKED` (`ERR_TRIP_NOT_BOOKED`). The aircraft must be `AVAILABLE` (`ERR_AIRCRAFT_NOT_AVAILABLE`) and listed on the operator's FAA operations specifications, with `on_ops_spec` true (`ERR_AIRCRAFT_NOT_ON_OPS_SPEC`). No other `CONFIRMED` assignment on the same tail may have a buffered half-open occupancy interval intersecting this one (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`). No maintenance window on the same tail in `PLANNED` or `ACTIVE` status may have a closed interval intersecting the raw flight interval — and under the closed-interval rule of §2.8, touching endpoints count (`ERR_MAINTENANCE_CONFLICT`). Finally the aircraft's `category` must equal the trip's `requested_category` (`ERR_CATEGORY_MISMATCH`). All gates passing moves the assignment to `CONFIRMED`. An assignment can also be released outright while it is `TENTATIVE` or `CONFIRMED`; releasing an already-`RELEASED` assignment is rejected with `ERR_ASSIGNMENT_ALREADY_RELEASED`.

Maintenance control runs a parallel window lifecycle. A `MaintenanceController` schedules a window with the `aircraft_id`, a `window_type` of `INSPECTION_100H`, `ANNUAL`, or `AOG_REPAIR`, and a closed `starts_at`-to-`ends_at` interval whose end must be strictly after its start (`ERR_INVALID_TIME_RANGE` otherwise). At creation the window is conflict-checked in both directions: against the raw flight intervals of the tail's `CONFIRMED` assignments (`ERR_MAINTENANCE_CONFLICT`) and against the tail's other `PLANNED` or `ACTIVE` windows (`ERR_WINDOW_OVERLAP`), both under the closed-interval, touching-counts rule. A scheduled window sits in `PLANNED` until the clock sweep of §2.4 activates it once its `starts_at` is reached — unless the tail is `IN_TRIP`, in which case activation is skipped and retried on the next clock set — moving the window to `ACTIVE` and an `AVAILABLE` aircraft to `MAINTENANCE_HOLD`. Completing the window requires it to be `ACTIVE` (`ERR_WINDOW_NOT_COMPLETABLE`); completion moves it to `COMPLETED`, and for an `INSPECTION_100H` window it resets the tail's inspection horizon, setting `next_check_due_minutes` to the current `total_airframe_minutes` plus 6000 minutes — one hundred hours. When the completed window was the last `ACTIVE` window on the tail and the accumulated airframe time sits below the check-due threshold, the aircraft leaves `MAINTENANCE_HOLD` for `AVAILABLE`. A window still in `PLANNED` may instead be cancelled, moving it to `CANCELLED`; cancelling a window in any other status is rejected with `ERR_INVALID_STATE`.

Compliance can remove a tail from service at a stroke. A `ComplianceOfficer` grounds an aircraft in `AVAILABLE` or `MAINTENANCE_HOLD` (grounding from `IN_TRIP` or `GROUNDED` yields `ERR_INVALID_STATE`), moving it to `GROUNDED`. The cascade is three links deep: every `TENTATIVE` or `CONFIRMED` assignment on the tail is released, and every trip in `BOOKED` status whose `CONFIRMED` assignment was just released falls back to `QUOTED` — a new aircraft must be confirmed before that trip can dispatch. Returning the tail to service requires it to be `GROUNDED` (`ERR_AIRCRAFT_NOT_GROUNDED` otherwise) and requires that no compliance finding with `subject_type` `AIRCRAFT` pointing at this tail, flagged `grounding` true, remains `OPEN` (`ERR_GROUNDING_FINDING_OPEN`); a clean return moves the aircraft to `AVAILABLE`.

The findings themselves are filed by a `ComplianceOfficer` with a `subject_type` of `AIRCRAFT`, `CREW_MEMBER`, or `TRIP_REQUEST` — a polymorphic reference resolved together with the `subject_id`, which must exist in the collection the type names (the corresponding resource-specific 404 applies) — plus a `finding_code` such as OPSPEC-A001, the `grounding` flag that, on an aircraft subject, blocks dispatch and return-to-service while the finding is `OPEN`, and optional free-text `notes`. A finding is born `OPEN` and is resolved by the same role; resolving requires `OPEN` status (`ERR_FINDING_ALREADY_RESOLVED` otherwise) and stamps `resolved_at` at the current clock.

### 3.6. Crew Assignment and Duty/Rest Legality

Crewing begins when a `DispatchManager` creates a crew assignment naming the `trip_request_id`, the `crew_member_id`, and a `duty_role` of `PIC` or `SIC`. The trip must be `QUOTED` or `BOOKED` — any other status yields `ERR_INVALID_STATE` — and the crew member must be `ACTIVE` and type-qualified, meaning the trip's `requested_category` appears in the member's `qualified_categories`; an unqualified member is rejected with `ERR_CREW_NOT_TYPE_QUALIFIED`. The assignment is born `PROPOSED`, with `duty_legal`, `rest_legal`, and `vetted_at` all null until the vetting run.

Vetting is the legality check, executed by a `DispatchManager` on a `PROPOSED` assignment (`ERR_CREW_ASSIGNMENT_NOT_PROPOSED` otherwise) whose crew member is still `ACTIVE` (a suspended member yields `ERR_INVALID_STATE`). The run computes the `planned_duty_minutes`: the sum of the planned `block_minutes` across the trip's legs plus 60 minutes of report and debrief allowance. Duty is legal when the planned duty is at most 840 minutes — fourteen hours — and exactly 840 minutes is legal. Rest is evaluated over duty intervals: a trip's duty interval opens 30 minutes before its `departure_at` (the report allowance) and closes 30 minutes after the planned arrival implied by the total block time (the debrief allowance). Rest is legal when, against every other `VETTED` assignment of the same crew member, the gap between the two duty intervals is at least 600 minutes — ten hours — on both sides, where the gap is the later interval's start minus the earlier interval's end, floored at zero. Overlapping intervals therefore have a gap of zero and always violate rest, while a gap of exactly 600 minutes is legal.

The vetting run stamps `vetted_at` at the current clock and records both flags. When both `duty_legal` and `rest_legal` come out true, the assignment advances to `VETTED`; when either fails, it advances to `FLAGGED_ILLEGAL` instead. Neither result is sticky: adding or deleting a quote leg on the trip, or requoting it, returns every `VETTED` or `FLAGGED_ILLEGAL` assignment on the trip to `PROPOSED` with `duty_legal`, `rest_legal`, and `vetted_at` cleared, forcing a fresh vet against the new itinerary. Trip cancellation and trip completion both release the crew — every assignment in `PROPOSED`, `VETTED`, or `FLAGGED_ILLEGAL` moves to `RELEASED`, its terminal state.

### 3.7. Manifest, Screening, and Overflight Permits

The manifest is built by a `SalesAgent`, one passenger at a time, each row carrying the `trip_request_id`, the passenger's `full_name`, and their `date_of_birth` as an ISO 8601 date. Passengers may be added while the trip is `QUOTED` or `BOOKED`; against any other status the add is rejected with `ERR_INVALID_STATE`. A new passenger starts with `tsa_status` `PENDING` and a null `screened_at`.

Screening is a `ComplianceOfficer` decision supplied as an `outcome` of `CLEARED` or `DENIED`. Only a passenger in `PENDING` or `EXPIRED` may be screened — screening a `CLEARED` or `DENIED` passenger is rejected with `ERR_PASSENGER_NOT_SCREENABLE`. A `CLEARED` outcome sets `tsa_status` to `CLEARED` and stamps `screened_at` at the current clock; a `DENIED` outcome sets `tsa_status` to `DENIED` — a terminal state — and likewise stamps `screened_at`. Clearances age out: when a clock advance carries the logical clock more than 72 hours past `screened_at`, the sweep of §2.4 moves the passenger from `CLEARED` to `EXPIRED`, from which a fresh screening decision can clear them again.

International trips need permits. A `SalesAgent` requests one with the `trip_request_id`, the two-letter `country_code` of the permit authority, a `permit_type` of `OVERFLIGHT` or `LANDING`, and an optional `required` flag that defaults to true and marks whether dispatch is gated on this permit being granted. Duplicates are refused: a second permit for the same trip, country, and type while one already sits in `REQUESTED` or `GRANTED` is rejected with `ERR_DUPLICATE_PERMIT`. A new permit starts `REQUESTED` with a null `decided_at`. A `ComplianceOfficer` decides it by supplying a `decision` of `GRANTED` or `DENIED`; only a `REQUESTED` permit may be decided (`ERR_PERMIT_NOT_DECIDABLE` otherwise). Granting sets the status to `GRANTED`, denying sets it to `DENIED` — a terminal state — and both stamp `decided_at`. Grants lapse with time: when the logical clock advances more than 30 days past `decided_at`, the sweep moves the permit from `GRANTED` to `EXPIRED`.

### 3.8. Dispatch: The Compliance Gate Sequence

Dispatch is the point of no return, executed by a `DispatchManager` against a `BOOKED` trip (any other status yields `ERR_TRIP_NOT_BOOKED`). The gates fire in a fixed sub-order within the tiers of §2.11, and the first failure determines the error. First, in the state tier, the trip must hold exactly one `CONFIRMED` aircraft assignment; zero or several yield `ERR_NO_CONFIRMED_ASSIGNMENT`. Then the compliance tier runs in this sequence: crew legality — at least one crew assignment with `duty_role` `PIC` must be `VETTED` with both `duty_legal` and `rest_legal` true, and when the assigned aircraft's category is `HEAVY_JET` at least one equally vetted and legal `SIC` is also required, failing which the dispatch is rejected with `ERR_CREW_NOT_VETTED`; manifest completeness — the number of passenger rows on the trip must equal the trip's `passenger_count` (`ERR_PASSENGER_MANIFEST_INCOMPLETE`); security — every passenger must hold `tsa_status` `CLEARED` (`ERR_TSA_NOT_CLEARED`); permits — when the trip's `international` flag is true, at least one overflight permit must exist for the trip and every permit flagged `required` must be `GRANTED` (`ERR_PERMIT_NOT_GRANTED`); inspection headroom — the confirmed tail's `total_airframe_minutes` plus the trip's total planned block minutes must be at most its `next_check_due_minutes`, with equality legal and a single minute over rejected with `ERR_CHECK_HOURS_EXCEEDED`; and findings — no `OPEN` compliance finding flagged `grounding` may point at the assigned aircraft (`ERR_GROUNDING_FINDING_OPEN`). Only after all compliance gates pass does the money tier run: `collected_cents` must be at least the `quoted_total_cents`, or dispatch is rejected with `ERR_BALANCE_NOT_SETTLED`.

A clean dispatch moves the trip to `DISPATCHED`, moves the confirmed tail from `AVAILABLE` to `IN_TRIP`, and increments the trip's `version`.

### 3.9. Flight Logging, Completion, and Owner Settlement

Once airborne, each flown leg is logged by the trip's pilot in command. Recording a log is the one write a `CrewMember` may perform, and it is identity-bound per §2.1: `X-User-ID` must equal the `crew_member_id` of a `VETTED` `PIC` crew assignment on the trip, or the request is rejected with `ERR_FORBIDDEN`. The log names the `trip_request_id` and the `quote_leg_id` flown, the `actual_block_minutes` (greater than zero), and the actual `departed_at` and `arrived_at`, with arrival strictly after departure (`ERR_INVALID_TIME_RANGE` otherwise). The trip must be `DISPATCHED` (`ERR_INVALID_STATE`); the leg must belong to the named trip (`ERR_LEG_TRIP_MISMATCH`); and a leg may be logged exactly once — a second log against the same leg is rejected with `ERR_DUPLICATE_FLIGHT_LOG`. The server stamps `recorded_by_crew_id` from the acting header. Every posted log adds its `actual_block_minutes` to the confirmed tail's `total_airframe_minutes`.

Completion is automatic: the moment every quote leg of the trip has exactly one flight log, the trip moves from `DISPATCHED` to `COMPLETED` and the settlement machinery runs. Final pricing uses the confirmed tail's own `hourly_rate_cents` — the actual rate, not the category rate card — and applies no volume discount and no fuel surcharge. Each leg is billed in `seq_no` order: a `REVENUE` leg bills the greater of its logged `actual_block_minutes` or a 60-minute minimum, multiplied by the hourly rate and divided by sixty; a `POSITIONING` leg bills its planned `block_minutes` regardless of actuals, multiplied by the hourly rate, multiplied by 0.6, and divided by sixty. Per the pinned rounding order of §2.6, each leg charge is rounded half up to whole cents before summing. The same 15000-cent fee per `fuel_stop` leg and the same 250000-cent international fee then apply, giving `final_total_cents`. This dual pricing is deliberate: the quoted number reflects planned minutes at the rate card with discount and surcharge, while the final number reflects logged actuals at the tail's own rate with the 60-minute minimum on revenue legs — the two diverge whenever actuals differ from plan, the tail's rate differs from the card, or the minimum bites.

The completion cascade resolves everything the trip touched. The tail's status is resolved by its inspection horizon: if, after accumulating the logged minutes, `total_airframe_minutes` has reached or passed `next_check_due_minutes`, or an `ACTIVE` maintenance window exists on the tail, the aircraft moves from `IN_TRIP` to `MAINTENANCE_HOLD` and every `TENTATIVE` assignment on that tail is released; otherwise it returns to `AVAILABLE`. An owner statement is drafted for the owner of the confirmed tail. Every crew assignment of the trip still in `PROPOSED`, `VETTED`, or `FLAGGED_ILLEGAL` is released.

The owner statement settles the trip with the aircraft's owner, in a pinned evaluation order. The `owner_id` and `trip_request_id` are system-set from the confirmed assignment. The `gross_cents` is the trip's `final_total_cents`. The `standard_share_cents` is the gross multiplied by the owner's `revenue_share_pct` and divided by one hundred, rounded half up. The `guarantee_floor_cents` is the owner's `guarantee_cents_per_block_min` multiplied by the total logged `actual_block_minutes` across every flight log of the trip — revenue and positioning legs alike. The `owner_share_cents` is the greater of the standard share and the guarantee floor, and the `operator_retained_cents` is the residual gross minus the owner share, which may legitimately go negative when the guarantee binds. Conservation holds always: owner share plus operator retained equals the gross. Under the STANDARD variant — an owner whose per-minute guarantee is zero — the owner share equals the standard share; under the GUARANTEED variant, the floor exceeds the standard share and binds, so identical trip economics pay out differently. The statement is born `DRAFT`; an `OpsAdmin` issues it, which requires `DRAFT` status (`ERR_STATEMENT_NOT_DRAFT` otherwise), moves it to `ISSUED`, and stamps `issued_at`. Statements are readable by the back office across all the usual list views, and an `AircraftOwner` may list the statements on its own record — attempting to list another owner's statements is rejected with `ERR_FORBIDDEN`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, screening and permit decisions, window completions, and the logical-clock advance — return `200 OK`. The single deletion operation, removing a quote leg, returns `204 No Content` with an empty body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/charter/aircraft-owners` | Register an aircraft owner | OpsAdmin |
| GET | `/charter/aircraft-owners` | List aircraft owners | All roles |
| GET | `/charter/aircraft-owners/{id}` | Get an aircraft owner | All roles |
| POST | `/charter/aircraft` | Register an aircraft tail | OpsAdmin |
| GET | `/charter/aircraft` | List aircraft, optionally filtered by owner, category, or status | All roles |
| GET | `/charter/aircraft/{id}` | Get an aircraft | All roles |
| POST | `/charter/aircraft/{id}/ground` | Ground an aircraft | ComplianceOfficer |
| POST | `/charter/aircraft/{id}/return-to-service` | Return a grounded aircraft to service | ComplianceOfficer |
| POST | `/charter/crew-members` | Register a crew member | OpsAdmin |
| GET | `/charter/crew-members` | List crew members, optionally filtered by status | All roles |
| GET | `/charter/crew-members/{id}` | Get a crew member | All roles |
| PATCH | `/charter/crew-members/{id}` | Suspend or reactivate a crew member | OpsAdmin |
| POST | `/charter/trip-requests` | Create a trip request in QUOTE_DRAFT | SalesAgent |
| GET | `/charter/trip-requests` | List trip requests, optionally filtered by status | All roles |
| GET | `/charter/trip-requests/{id}` | Get a trip request | All roles |
| POST | `/charter/trip-requests/{id}/quote` | Price the trip and move it to QUOTED | SalesAgent |
| POST | `/charter/trip-requests/{id}/requote` | Return a QUOTED trip to QUOTE_DRAFT for re-pricing | SalesAgent |
| POST | `/charter/trip-requests/{id}/book` | Book a QUOTED trip with a deposit | SalesAgent |
| POST | `/charter/trip-requests/{id}/cancel` | Cancel a trip under the tiered refund policy | SalesAgent |
| POST | `/charter/trip-requests/{id}/dispatch` | Dispatch a BOOKED trip through the compliance gates | DispatchManager |
| POST | `/charter/quote-legs` | Add a leg to a QUOTE_DRAFT trip | SalesAgent |
| GET | `/charter/quote-legs/{id}` | Get a quote leg | All roles |
| GET | `/charter/trip-requests/{id}/quote-legs` | List the legs of a trip | All roles |
| DELETE | `/charter/quote-legs/{id}` | Remove a leg from a QUOTE_DRAFT trip | SalesAgent |
| POST | `/charter/aircraft-assignments` | Assign an aircraft to a QUOTED or BOOKED trip, superseding any prior tentative assignment | DispatchManager |
| GET | `/charter/aircraft-assignments` | List aircraft assignments, optionally filtered by trip, aircraft, or status | All roles |
| GET | `/charter/aircraft-assignments/{id}` | Get an aircraft assignment | All roles |
| POST | `/charter/aircraft-assignments/{id}/confirm` | Confirm a TENTATIVE assignment through the availability gates | DispatchManager |
| POST | `/charter/aircraft-assignments/{id}/release` | Release a TENTATIVE or CONFIRMED assignment | DispatchManager |
| POST | `/charter/crew-assignments` | Assign a crew member to a QUOTED or BOOKED trip | DispatchManager |
| GET | `/charter/crew-assignments` | List crew assignments, optionally filtered by trip, crew member, or status | All roles |
| GET | `/charter/crew-assignments/{id}` | Get a crew assignment | All roles |
| POST | `/charter/crew-assignments/{id}/vet` | Run duty and rest legality on a PROPOSED crew assignment | DispatchManager |
| POST | `/charter/maintenance-windows` | Schedule a maintenance window | MaintenanceController |
| GET | `/charter/aircraft/{id}/maintenance-windows` | List the maintenance windows of an aircraft | All roles |
| GET | `/charter/maintenance-windows/{id}` | Get a maintenance window | All roles |
| POST | `/charter/maintenance-windows/{id}/complete` | Complete an ACTIVE maintenance window | MaintenanceController |
| POST | `/charter/maintenance-windows/{id}/cancel` | Cancel a PLANNED maintenance window | MaintenanceController |
| POST | `/charter/passengers` | Add a passenger to a trip manifest | SalesAgent |
| GET | `/charter/trip-requests/{id}/passengers` | List the manifest of a trip | All roles |
| GET | `/charter/passengers/{id}` | Get a passenger | All roles |
| POST | `/charter/passengers/{id}/screen` | Record a TSA program screening decision | ComplianceOfficer |
| POST | `/charter/overflight-permits` | Request an overflight or landing permit | SalesAgent |
| GET | `/charter/trip-requests/{id}/overflight-permits` | List the permits of a trip | All roles |
| GET | `/charter/overflight-permits/{id}` | Get a permit | All roles |
| POST | `/charter/overflight-permits/{id}/decide` | Grant or deny a REQUESTED permit | ComplianceOfficer |
| POST | `/charter/payments` | Post a manual BALANCE payment | SalesAgent |
| GET | `/charter/trip-requests/{id}/payments` | List the payments of a trip | All roles |
| POST | `/charter/flight-logs` | Record actual block times for a flown leg | CrewMember |
| GET | `/charter/flight-logs` | List flight logs, optionally filtered by trip or leg | All roles |
| GET | `/charter/flight-logs/{id}` | Get a flight log | All roles |
| GET | `/charter/aircraft-owners/{id}/owner-statements` | List the statements of an owner (owners may read their own only) | OpsAdmin, AircraftOwner |
| GET | `/charter/trip-requests/{id}/owner-statements` | List the statements generated by a trip | All roles |
| POST | `/charter/owner-statements/{id}/issue` | Issue a DRAFT statement | OpsAdmin |
| POST | `/charter/compliance-findings` | File an FAA ops-spec compliance finding | ComplianceOfficer |
| GET | `/charter/compliance-findings` | List findings, optionally filtered by subject or status | All roles |
| GET | `/charter/compliance-findings/{id}` | Get a finding | All roles |
| POST | `/charter/compliance-findings/{id}/resolve` | Resolve an OPEN finding | ComplianceOfficer |
| POST | `/charter/weather-advisories` | Publish a weather advisory | DispatchManager |
| GET | `/charter/weather-advisories` | List weather advisories, optionally filtered by station | All roles |
| POST | `/charter/_clock/set_current_utc` | Advance the logical clock and run the expiry sweep | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_AIRCRAFT_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MAINTENANCE_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_PASSENGER_NOT_FOUND` | 404 Not Found |
| `ERR_OVERFLIGHT_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLIANCE_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_QUOTE_DRAFT` | 409 Conflict |
| `ERR_TRIP_NOT_QUOTED` | 409 Conflict |
| `ERR_TRIP_NOT_BOOKED` | 409 Conflict |
| `ERR_TRIP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_CONFIRMED_ASSIGNMENT` | 409 Conflict |
| `ERR_AIRCRAFT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_AIRCRAFT_NOT_GROUNDED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_TENTATIVE` | 409 Conflict |
| `ERR_ASSIGNMENT_ALREADY_RELEASED` | 409 Conflict |
| `ERR_CREW_ASSIGNMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_WINDOW_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_PASSENGER_NOT_SCREENABLE` | 409 Conflict |
| `ERR_PERMIT_NOT_DECIDABLE` | 409 Conflict |
| `ERR_STATEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_FINDING_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_AIRCRAFT_NOT_ON_OPS_SPEC` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_TYPE_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_VETTED` | 422 Unprocessable Entity |
| `ERR_TSA_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_PASSENGER_MANIFEST_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_GRANTED` | 422 Unprocessable Entity |
| `ERR_CHECK_HOURS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GROUNDING_FINDING_OPEN` | 422 Unprocessable Entity |
| `ERR_AIRCRAFT_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_MAINTENANCE_CONFLICT` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_ACTIVE_WEATHER_ADVISORY` | 409 Conflict |
| `ERR_CATEGORY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LEG_TRIP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FLIGHT_LOG` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PERMIT` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 Payment Required |
| `ERR_BALANCE_NOT_SETTLED` | 402 Payment Required |
| `ERR_OVERPAYMENT` | 402 Payment Required |
| `ERR_PAYMENT_STATE_INVALID` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
