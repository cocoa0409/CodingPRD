# Helicopter Tour Ops API — Product Requirements Document

## 1. Introduction

A Grand Canyon helicopter sightseeing operator runs one of the most constrained small-aircraft businesses in the country. Every flying day is a high-cycle rotation of short hops over noise-sensitive terrain: the National Park Service and the gateway communities expect strict adherence to quiet-hours windows and route-level noise commitments, the airframe demands disciplined weight-and-balance accounting on every departure, and pilots accumulate flight and duty time against hard daily limits across a dozen or more legs. Weather over the canyon changes faster than the schedule can, and every cancelled rotation leaves a desk full of passengers expecting refunds, credits, or a seat on the next departure. Meanwhile the community-relations office tracks every noise complaint, because a route that draws too many substantiated complaints must come off the schedule before regulators do it for them.

This document specifies the operations API that ties those concerns together. It covers operating-base configuration and the weather posture derived from observations; the catalogue of routes, pricing seasons, aircraft, and pilots; flight scheduling with turnaround buffers and crew-assignment safety gates; seat sales with tiered pricing, time-boxed holds, card settlement, and a rebooking-credit ledger; the passenger waiver, briefing, and check-in chain that feeds the weight-and-balance manifest; dispatch under segregation of duties; and the community-complaint workflow whose quota can suspend a route automatically. All time-gated behavior in the system — holds, credit expiry, duty-day rollovers, weather validity, refund tiers — reads a single logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or presenting a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint — or that violates an entity-backed ownership rule — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Six roles exist, spelled exactly as follows. `OpsAdmin` is the operator administrator owning configuration: bases, routes, seasons, aircraft, pilots, the batch tick, and the logical clock. `Dispatcher` runs flight operations: scheduling, crew assignment, manifest close-out, dispatch, completion, cancellations, and weather observations. `BookingAgent` staffs the reservations desk: bookings, credit application, passenger waiver/briefing/check-in events. `ComplianceOfficer` is the community-relations officer who reviews and dispositions noise complaints. `CommunityReporter` is a member of the public filing noise complaints, with read access limited to bases, routes, seasons, aircraft, pilots, flights, weather observations, and complaints. `Pilot` is the entity-backed role described below.

For `OpsAdmin`, `Dispatcher`, `BookingAgent`, `ComplianceOfficer`, and `CommunityReporter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` and `dispatched_by_user_id` on a flight — but does not compare it to any entity's `id`. When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot`; ownership checks on any resource that references a `Pilot` compare the resource's foreign-key field to `X-User-ID`. Concretely, a pilot may acknowledge only a flight whose `pilot_id` equals `X-User-ID`, and may query duty-day ledgers only for their own `pilot_id`; a pilot reading another pilot's duty-day rows is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Responses place `limit`, `offset`, `total_count`, and `has_more` in `meta`. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending. Several list endpoints also accept filter parameters named after the resource's own identifier or state fields — `status`, `base_id`, `route_id`, `aircraft_id`, `pilot_id`, `flight_id`, `booking_id`, `duty_date`, `contact_email`, `noise_class`, and `matched_route_id` — each narrowing the result set to rows matching the supplied value.

### 2.4. Resource Identity, Timestamps, and Change Tracking

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC with three fractional digits. `version` increments on every mutation of the resource, and `updated_at` refreshes to the mutation instant. The single exception is `WeatherObservation`: observations are immutable once recorded and carry only `id` and `created_at` — both `updated_at` and `version` are absent from that resource.

The resource topology is flat: all twelve resources are peers joined by identifier references such as `flight_id` or `pilot_id` carried in request bodies, and no write path nests one resource under another. Whenever a request addresses resources by identifier, path identifiers are validated first, left to right along the URL, followed by foreign-key identifiers in the body; the first unknown identifier is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock

The server maintains a logical clock, and every time-gated rule in this document — hold expiry, credit expiry, duty-day rollover, weather validity, complaint windows, refund tiers, departure-in-the-past checks — reads that clock, never wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it advances only when an `OpsAdmin` invokes the test-driving capability `POST /_clock/set_current_utc` with a `to_iso8601` instant; the response body carries `current_utc`. The logical clock never falls back to wall-clock time between invocations.

### 2.6. Optimistic Concurrency Control

Four write operations are guarded against stale reads. Each requires the request to carry a version field holding the value of the parent resource's `version` the client last observed; if that value does not match the parent resource's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The guarded operations are:

- Reassigning a flight's crew (`PATCH /flights/{id}/assignment`) requires `expected_flight_version`, matched against the flight's current `version`. Reassignment is legitimate whenever the flight is `SCHEDULED` or `DELAYED`, so a client whose view predates another landed assignment must be told its view is stale rather than silently overwrite it.
- Closing a manifest (`POST /flights/{id}/close-manifest`) requires `expected_flight_version`, because interim flight mutations — assignment changes, delays — invalidate the weight-and-balance picture the closer computed from.
- Moving a booking to another flight (`POST /bookings/{id}/move`) requires `expected_booking_version`, since interim mutations such as credit applications or a confirm change the settlement base the mover priced from.
- Updating base configuration (`PATCH /bases/{id}`) requires `expected_base_version`, so two operators cannot unknowingly overwrite each other's regulatory settings.

Endpoints not listed here take no version field.

### 2.7. Money, Weights, and Measures

All monetary amounts are integer cents; any percentage leg of a monetary calculation rounds half-up to whole cents, and the complement is assigned to the other leg so that cents are never created or destroyed. Price multipliers are expressed in basis points, where ten thousand basis points is exactly parity (1.00x). Weights are integer pounds with no rounding. Center-of-gravity results are rounded half-up to two decimal places before any envelope comparison. Durations are integer minutes; actual airborne time credited to a pilot is the whole-minute floor of the elapsed interval. Load percentages used by pricing are whole-number floors. Wherever a threshold comparison appears in this document, the boundary inclusivity stated in prose is exact.

### 2.8. Windows, Intervals, and Boundary Semantics

The system leans on half-open intervals. A pricing season covers dates from `start_date` inclusive to `end_date` exclusive, and two seasons may touch — one ending exactly when another begins — without overlapping. Quiet hours are expressed as minutes since 00:00 UTC on the operating base, from `quiet_hours_start_min_utc` inclusive to `quiet_hours_end_min_utc` exclusive. The overflight window used to match noise complaints to flights is half-open at its end. Turnaround buffers extend a flight's occupied interval half-open, so a departure exactly at the previous flight's buffered end is permitted. Two windows are instead inclusive at both bounds: the rolling complaint-quota window, and the center-of-gravity envelope. Expiry checks fire at the boundary itself — a hold or credit whose `expires_at` is at or before the current instant is expired — while a scheduled departure must be strictly in the future.

### 2.9. Validation Order and Error Precedence

Every endpoint evaluates its guards in a fixed global order, and a failure at an earlier rung masks every later one. The ladder is:

1. **Request validity** — the body parses, required fields are present, enum values are valid; unknown fields are ignored. Failure: `ERR_INVALID_REQUEST` (HTTP 400).
2. **Authentication** — `X-User-Role` and `X-User-ID` present and the role recognized. Failure: `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Authorization** — the role is permitted on the endpoint and entity-backed ownership holds (a pilot acknowledges only their own flight; a pilot reads only their own duty-days). Failure: `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
4. **Existence** — path identifiers first, left to right, then body foreign keys. Failure: `ERR_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency** — on the four guarded writes of §2.6, the expected version matches the parent's current `version`. Failure: `ERR_STALE_VERSION` (HTTP 412).
6. **State** — the target resource is in a state that permits the requested transition; terminal states reject every transition. Failure: `ERR_INVALID_STATE` (HTTP 409).
7. **Business safety rules** — posture, availability, duty limits, noise class, quiet hours, weight and balance, segregation of duties, in the relative order stated with each workflow in §3.
8. **Business temporal rules** — departure in the future, season windows, turn and overlap conflicts, hold liveness.
9. **Business referential rules** — waiver, briefing, pilot acknowledgment, complaint linkage.
10. **Business constraint rules** — route status, seat capacity, seat numbers, name and code uniqueness.
11. **Business fiscal rules** — exact payment amounts and credit redeemability.

Where a single endpoint runs several business rules, §3 states their relative order explicitly at the workflow they guard.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Operation: Bases, Routes, Seasons, and Fleet

Before the first flight can be scheduled, an `OpsAdmin` establishes the operating environment. Creating a base registers a heliport with its `name`, its quiet-hours window `quiet_hours_start_min_utc` and `quiet_hours_end_min_utc` (minutes since 00:00 UTC), and the `current_waiver_version` that new bookings must pin. Weather thresholds carry defaults used when the create payload omits them: `weather_ceiling_min_ft` defaults to 1000 feet, `weather_visibility_min_sm` to 3 statute miles, `weather_wind_max_kt` to 25 knots, and `weather_validity_min` to 60 minutes. The community-relations knobs default to `complaint_quota_threshold` of 3 substantiated complaints inside a `complaint_window_days` window of 30 days, and the reservations hold lives `hold_expire_minutes` minutes, defaulting to 30. A new base starts with `posture` NORMAL — posture is always derived from weather observations, never set directly — and an `ops_run_index` of 0, incremented once per batch tick. Base configuration is mutable afterward through the OCC-guarded update described in §2.6, which increments the base's `version`.

Routes are the commercial inventory. Each carries a `route_code` unique across all routes, a `tier` of SHORT, STANDARD, or GRAND, a scheduled block time `duration_minutes`, a `base_seat_price_cents` before multipliers, the planned fuel load `fuel_required_lb`, and a `min_altitude_ft` recording the route's minimum cruise altitude above ground level as an informational compliance floor. Noise policy rides on three fields: `noise_sensitive`, which subjects non-QUIET aircraft to the base's quiet-hours window; `noise_zones`, the community zones overflown, a subset of VILLAGE, RIM, and AIRPORT; and `min_aircraft_noise_class`, either QUIET_ONLY or ANY. The turnaround buffer `turn_minutes` is derived from the tier — 15 minutes for SHORT, 25 for STANDARD, 40 for GRAND — and never supplied directly. A route is created ACTIVE, and its `substantiated_complaints_30d` counter is recomputed from complaints on every read (§3.9).

Pricing seasons are publication windows. A season carries a `label`, a `start_date` (first covered date, inclusive), an `end_date` (first uncovered date, exclusive, which must be later than `start_date`), and a `multiplier_bps` between 1 and 30000 basis points. Creation rejects a window that overlaps any PUBLISHED season — adjacency, where one season's `end_date` equals another's `start_date`, is allowed — or whose end is not after its start, with `ERR_SEASON_OVERLAP`. A season is created PUBLISHED; retiring it moves it to the terminal RETIRED state, after which it is invisible to pricing selection and to the overlap check.

Aircraft registration captures the tail as `tail_number` (unique across all aircraft, enforced with `ERR_UNIQUENESS_CONFLICT`), the passenger `seat_capacity`, the operating `empty_weight_lb`, the `empty_moment_lb_in` relative to the datum, the `max_takeoff_weight_lb`, the `fuel_arm_inches` station, and the `seat_arms_inches` array giving the arm per seat index from 0 through `seat_capacity` minus one — the array's length must equal `seat_capacity`. The center-of-gravity envelope is `cg_forward_limit_in` through `cg_aft_limit_in`, both inclusive, and `noise_class` is QUIET or STANDARD. An aircraft begins AVAILABLE. Lifecycle events across the registry resources — aircraft maintenance and grounding, route suspension and resumption, season retirement — are all driven the same way: the operator posts an `event_type` naming the intended transition, and the state machine of the target resource decides whether it is permitted. Placing it into maintenance is refused while any of its flights sits in SCHEDULED, DELAYED, BOARDING, or MANIFEST_CLOSED with a departure now or later; otherwise it transitions AVAILABLE → IN_MAINTENANCE, and ending maintenance returns IN_MAINTENANCE → AVAILABLE. Grounding is the heavier hammer: grounding an AVAILABLE aircraft cancels every one of its flights in SCHEDULED, DELAYED, BOARDING, or MANIFEST_CLOSED departing now or later, driving each to CANCELLED_OPS with `cancel_reason` AIRCRAFT_GROUNDED and firing the booking cascade of §3.8, while grounding from IN_MAINTENANCE fires no cascade because no such future flights can exist. Recertification moves GROUNDED → AVAILABLE.

Pilot registration records a `display_name` and a `certificate_no` unique across all pilots (again `ERR_UNIQUENESS_CONFLICT`); a pilot begins AVAILABLE.

### 3.2. Weather Surveillance and Base Posture

A `Dispatcher` posts a weather observation for a base with `base_id`, the `observed_at` instant, `ceiling_ft`, `visibility_sm`, and `wind_kt`. The server derives two fields. `adverse` is true when the ceiling is below the base's `weather_ceiling_min_ft`, or visibility is below `weather_visibility_min_sm`, or wind exceeds `weather_wind_max_kt`. `validity_until` is `observed_at` plus the base's `weather_validity_min` minutes.

A base's `posture` is computed on read, never stored. The governing observation is the one with the greatest `observed_at` at or before now, ties broken by the greatest `created_at`. Posture is WEATHER_HOLD exactly when that observation exists, is adverse, and now is strictly before its `validity_until`; in every other case posture is NORMAL. The weather cascade fires the moment a newly posted adverse observation supersedes every previously posted observation of its base — no prior observation of that base has a greater `observed_at`, and a tie on `observed_at` resolves in favor of the newly posted one: every flight of that base in SCHEDULED, DELAYED, BOARDING, or MANIFEST_CLOSED whose `scheduled_departure_utc` falls within the window from `observed_at` inclusive to `validity_until` exclusive is cancelled to CANCELLED_WEATHER with `cancel_reason` WEATHER, and the booking cascade of §3.8 runs on each. This trigger is not limited to observations at or before now: a forward-dated adverse observation fires the cascade at posting time, pre-cancelling the flights inside its future window, even though it cannot be the governing observation for posture before now reaches its `observed_at`. When a newer non-adverse observation becomes governing, or the adverse observation's validity passes, the base returns WEATHER_HOLD → NORMAL — but nothing restores the cancelled flights; that is a deliberate one-way door.

Posture gates two later operations: opening boarding and dispatch both refuse while the base sits in WEATHER_HOLD, rejected with `ERR_WEATHER_HOLD_ACTIVE`.

### 3.3. Scheduling and Crewing Flights

A `Dispatcher` schedules a flight by naming `base_id`, `route_id`, `aircraft_id`, `pilot_id`, and `scheduled_departure_utc`. The create runs a battery of gates in a fixed order: after the universal request, auth, and existence rungs of §2.9 (an unknown `aircraft_id` surfaces as `ERR_NOT_FOUND` before any safety check), the pilot must be AVAILABLE — a FATIGUE_LOCKED pilot cannot be assigned, `ERR_PILOT_NOT_AVAILABLE` — then the pilot's projected flight time and duty span for that UTC date must admit the new block (`ERR_PILOT_FLIGHT_TIME_EXCEEDED`, then `ERR_PILOT_DUTY_LIMIT_EXCEEDED`; §3.4), then the aircraft must be AVAILABLE (`ERR_AIRCRAFT_NOT_AVAILABLE` when IN_MAINTENANCE or GROUNDED), then a route whose `min_aircraft_noise_class` is QUIET_ONLY demands an aircraft whose `noise_class` is QUIET (`ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT`), then a noise-sensitive route flown by a non-QUIET aircraft may not depart with its minute-of-day inside the base's quiet-hours window (`ERR_QUIET_HOURS_VIOLATION`), then the departure must be strictly in the future (`ERR_DEPARTURE_IN_PAST`), then the aircraft's turnaround-buffered interval and the pilot's plain block interval must each be free of conflicts (`ERR_AIRCRAFT_TURN_CONFLICT`, `ERR_PILOT_SCHEDULE_OVERLAP`), and finally the route must be ACTIVE (`ERR_ROUTE_SUSPENDED`).

The two conflict gates deserve precision. An aircraft is occupied from a flight's `scheduled_departure_utc` to its `scheduled_arrival_utc` plus the route's `turn_minutes`, half-open: a candidate conflicts when its departure falls strictly before an existing flight's buffered end and that flight's departure falls strictly before the candidate's buffered end, which means a departure exactly at the previous flight's buffered end is allowed. A pilot is occupied over the plain half-open block from departure to arrival with no buffer, so a departure exactly at the previous flight's arrival is allowed. Both gates consider only flights on the same UTC date in SCHEDULED, DELAYED, BOARDING, MANIFEST_CLOSED, or DISPATCHED; cancelled and completed flights do not block. Because one aircraft can never hold two flights departing at the same instant under this rule, ties in the rotation sequence cannot occur.

A successfully created flight lands in SCHEDULED. Its `scheduled_arrival_utc` is the departure plus the route's `duration_minutes`; its `rotation_seq` is assigned per aircraft per UTC date by ordering that aircraft's non-cancelled flights by departure ascending and numbering from 1; `created_by_user_id` records the creating dispatcher's `X-User-ID`; `pilot_acknowledged` starts false; `actual_departure_utc`, `actual_arrival_utc`, and `cancel_reason` start null. Three load figures track the flight's bookings: `seats_booked` sums `seat_count` over bookings in HELD, CONFIRMED, CHECKED_IN, or MANIFESTED; `seats_available` is the aircraft's `seat_capacity` minus `seats_booked`; and `estimated_gross_weight_lb` keeps the running provisional estimate of §3.5. Creation also upserts the pilot's duty-day ledger row for that UTC date, folding the block time into `flight_minutes_scheduled`.

Crew changes happen through the OCC-guarded reassignment (§2.6), legitimate while the flight is SCHEDULED or DELAYED, accepting an optional `pilot_id` and/or `aircraft_id` alongside `expected_flight_version`; the duty, turn, noise, and availability gates re-run for the new crew, and the flight's `version` increments. A dispatcher may also DELAY a SCHEDULED flight, supplying `new_departure_utc` strictly in the future — a departure at or before now is rejected with `ERR_DEPARTURE_IN_PAST`; the turn, quiet-hours, noise-class, and duty gates re-pass at the new slot, after which `scheduled_departure_utc` is replaced, `scheduled_arrival_utc` and `rotation_seq` are recomputed, and the duty-day ledgers of the former and new dates are both adjusted. Accepting the delayed slot moves DELAYED → SCHEDULED with no field changes. The assigned pilot acknowledges the flight through a PILOT_ACK — a self-transition accepted from SCHEDULED → SCHEDULED or DELAYED → DELAYED — whose `X-User-ID` must equal the flight's `pilot_id` (`ERR_PILOT_MISMATCH` otherwise) and which sets `pilot_acknowledged` to true.

### 3.4. Duty Ledger and Fatigue Management

Every pilot and UTC date pair has at most one `DutyDay` row, keyed by `pilot_id` and `duty_date`, created lazily when the pilot's first flight that date is scheduled. The ledger keeps two variants of the same question, and they diverge whenever a flight completes earlier or later than scheduled.

The forward-looking variant is the assignment gate, consulted at flight creation, reassignment, and delay. `flight_minutes_scheduled` sums `duration_minutes` over the pilot's flights that UTC date in SCHEDULED, DELAYED, BOARDING, MANIFEST_CLOSED, DISPATCHED, or COMPLETED — cancelled flights are excluded. The candidate's block time is added, and the sum must be at most eight hours; eight hours exactly is permitted, one minute more is rejected with `ERR_PILOT_FLIGHT_TIME_EXCEEDED`. `duty_minutes_projected` spans from forty-five minutes before the earliest scheduled departure among the pilot's active flights plus the candidate, to fifteen minutes after the latest scheduled arrival among them, and must be at most fourteen hours — again equality is allowed, overflow rejected with `ERR_PILOT_DUTY_LIMIT_EXCEEDED`. With no flights on the date, `duty_minutes_projected` is 0.

The chronological variant is the actual ledger, written at flight completion: `flight_minutes_actual` gains the whole-minute floor of the airborne interval from `actual_departure_utc` to `actual_arrival_utc`. The moment the running total reaches or exceeds eight hours, the pilot flips AVAILABLE → FATIGUE_LOCKED, and a FATIGUE_LOCKED pilot cannot be assigned to new flights.

The batch tick — an `OpsAdmin`-run operation on a base, the run-ops sweep — is the system's nightly broom. In one invocation it expires every HELD booking whose `expires_at` is at or before now (§3.8), expires every rebooking credit whose `expires_at` has likewise arrived, and closes every OPEN `DutyDay` whose `duty_date` is before the current UTC date, moving it OPEN → CLOSED. A pilot left with no remaining OPEN duty-day returns FATIGUE_LOCKED → AVAILABLE. Each run increments the base's `ops_run_index` by one.

### 3.5. Selling Seats: Quotes, Holds, and Payment

Every seat price is computed by the quote algorithm, which runs at booking creation — where the result locks — and again when a booking is moved, where it recomputes and relocks. The quote starts from the route's `base_seat_price_cents` and applies three multipliers in a pinned order, each in basis points and each multiplication rounded half-up to whole cents before the next is applied. First comes the seasonal multiplier: the `multiplier_bps` of the PUBLISHED season whose window covers the departure date, ten thousand basis points when no PUBLISHED season covers it (RETIRED seasons are invisible to this selection), and the covering season's `id` is remembered on the booking as `season_id` — null in the fallback case. Second comes the load multiplier, driven by how full the flight already is before this booking's seats are added: the load percentage is the whole-number floor of `seats_booked` times one hundred divided by `seat_capacity`; below fifty percent the multiplier is parity, from fifty percent up to but not including eighty percent it is 1.10x, and at eighty percent or above it is 1.25x. Third comes the weekend multiplier: 1.10x when the UTC day-of-week of `scheduled_departure_utc` is Saturday or Sunday, parity otherwise. The per-seat figure after the third rounding is `quoted_per_seat_cents`, and `quoted_total_cents` is that per-seat figure multiplied by `seat_count` — the multiplication happens only after per-seat rounding, never before.

A `BookingAgent` creates a booking with `flight_id`, `contact_name`, `contact_email`, and a `passengers` list whose entries each carry a `full_name` and a `declared_weight_lb`. Two passengers in one booking may not share a `full_name` — `ERR_DUPLICATE_PASSENGER`. Two gates guard the create, evaluated after existence and in this order: the provisional weight estimate, then seat capacity. The estimate adds the aircraft's `empty_weight_lb`, a five-pound allowance on top of each passenger's `declared_weight_lb` across this flight's bookings in HELD, CONFIRMED, or CHECKED_IN including the new booking's own passengers, and the route's full `fuel_required_lb` — the provisional estimate never trims fuel, which is precisely how it diverges from the final manifest of §3.7. A total above `max_takeoff_weight_lb` is rejected with `ERR_GROSS_WEIGHT_EXCEEDED`; a total exactly at the limit is allowed. Capacity then requires the new `seat_count` — the number of passengers on the booking — to be no more than the flight's `seats_available`, with equality filling the flight exactly, allowed; overflow is `ERR_SEAT_CAPACITY_EXCEEDED`.

A created booking lands in HELD with its quote locked, `expires_at` set to `created_at` plus the base's `hold_expire_minutes`, `waiver_version_pinned` captured from the base's `current_waiver_version`, and its `Passenger` rows created with `pax_index` assigned 0, 1, 2… in input order. The money fields start clean: `paid_cents`, `refunded_card_cents`, `credited_cents`, `retained_fee_cents`, and `credits_applied_cents` all start at 0. While HELD, two desk operations are available, and both require the hold to be live — at or past `expires_at` either is rejected with `ERR_BOOKING_HOLD_EXPIRED`. Applying a credit consumes a `credit_id` against the balance due (§3.8). Confirming collects the card: `card_amount_cents` must equal `quoted_total_cents` minus `credits_applied_cents` to the cent, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402) — and the expiry check runs first, so an expired hold surfaces as `ERR_BOOKING_HOLD_EXPIRED` even when the amount is also wrong. Confirm additionally requires the flight to still be in SCHEDULED or DELAYED. A successful confirm moves HELD → CONFIRMED, records `card_amount_cents` into `paid_cents`, and clears `expires_at` to null.

### 3.6. Waivers, Briefings, and Passenger Check-In

Each passenger progresses through a compliance chain before boarding. A new passenger has `waiver_signed` false, `briefing_completed` false, `checked_in` false, and `actual_weight_lb` null. Signing the waiver presents a `waiver_version` that must equal the booking's `waiver_version_pinned` — a mismatch means the base has rotated waiver text since the booking was created and is rejected with `ERR_WAIVER_VERSION_STALE`; a match sets `waiver_signed` true and records the version into `waiver_version_signed`. Completing the safety briefing sets `briefing_completed` true.

Check-in is the scale-and-seat moment, allowed while the booking is CONFIRMED or CHECKED_IN, with its guards evaluated in order: the waiver must be signed (`ERR_WAIVER_NOT_SIGNED`), the briefing completed (`ERR_BRIEFING_INCOMPLETE`), and the presented `seat_number` must lie within the aircraft's seat range — from 0 up to but not including `seat_capacity` — and not already be held by another checked-in passenger on the same flight (`ERR_SEAT_NUMBER_TAKEN`). A successful check-in records the scale-measured `actual_weight_lb` and the `seat_number`, flips `checked_in` true, and — when this was the booking's last unchecked passenger — automatically moves the booking CONFIRMED → CHECKED_IN. Unchecking reverses it: `actual_weight_lb` and `seat_number` are cleared, `checked_in` returns false, and a booking sitting in CHECKED_IN reverts to CONFIRMED. Passenger listings order rows by `pax_index` ascending within a booking.

### 3.7. Manifest, Dispatch, and Flight Completion

When the flight's slot approaches, a dispatcher opens boarding — SCHEDULED → BOARDING, or DELAYED → BOARDING — permitted only while the base posture is NORMAL. Closing the manifest is the weight-and-balance reckoning, an OCC-guarded write requiring `expected_flight_version` (§2.6) from BOARDING, and it evaluates in a pinned order because the fuel and weight figures couple. First, passenger weight is summed from `actual_weight_lb` over the checked-in passengers of this flight's CHECKED_IN bookings — the final manifest uses scale weights with no allowance, unlike the estimate. Second, the fuel budget is what remains of `max_takeoff_weight_lb` after subtracting `empty_weight_lb` and that passenger weight. Third, `manifested_fuel_lb` is the smaller of the route's `fuel_required_lb` and the fuel budget — fuel is trimmed to fit, never the passengers. Fourth, the trimmed fuel must be at least the minimum: `fuel_required_lb` scaled by sixty percent, rounded half-up to whole pounds; falling short is rejected with `ERR_FUEL_BELOW_MINIMUM`. Fifth, `actual_gross_weight_lb` — empty weight plus passenger weight plus manifested fuel — must not exceed `max_takeoff_weight_lb`, equality allowed, else `ERR_GROSS_WEIGHT_EXCEEDED`. Sixth, the total moment is `empty_moment_lb_in` plus each manifested passenger's `actual_weight_lb` times the arm at their `seat_number` from `seat_arms_inches`, plus `manifested_fuel_lb` times `fuel_arm_inches`. Seventh, `actual_cg_in` is that moment divided by the gross weight, rounded half-up to two decimal places, and must sit inside the envelope from `cg_forward_limit_in` to `cg_aft_limit_in` with both bounds inclusive, else `ERR_CG_OUT_OF_ENVELOPE`. A successful close freezes `manifested_fuel_lb`, `actual_gross_weight_lb`, `actual_cg_in`, and `manifested_passenger_count` — the count of checked-in passengers on the manifested bookings — moves every CHECKED_IN booking of the flight to MANIFESTED, and increments the flight's `version` by one.

Dispatch turns the aircraft loose: MANIFEST_CLOSED → DISPATCHED. Its three guards evaluate in order — base posture must be NORMAL (`ERR_WEATHER_HOLD_ACTIVE`), then segregation of duties demands the dispatching dispatcher differ from the one recorded in `created_by_user_id` (`ERR_SEGREGATION_OF_DUTY`, HTTP 403), then the assigned pilot must have acknowledged (`ERR_PILOT_ACK_REQUIRED`). Dispatch stamps `actual_departure_utc` with the current instant, records `dispatched_by_user_id`, and cleans house: bookings still in CONFIRMED become NO_SHOW — the entire `paid_cents` is retained as `retained_fee_cents` with no refund and no credit — and bookings still in HELD become EXPIRED.

Completion requires the current instant to be after `actual_departure_utc`. It stamps `actual_arrival_utc`, credits the whole-minute floor of airborne time into the pilot's `flight_minutes_actual`, applies the eight-hour fatigue lock of §3.4 the moment the ledger reaches it, and moves every MANIFESTED booking to FLOWN.

### 3.8. Cancellations, Moves, and the Credit Ledger

A `BookingAgent` may cancel a live booking voluntarily, and the settlement depends on how far out the flight stands. Cancelling from HELD is free: any applied credits release back to their original `RebookingCredit` rows — each credit's `redeemed_cents` is reduced by what it contributed and its status recomputed — and the seats release. Cancelling from CONFIRMED or CHECKED_IN runs the settlement tiers against `paid_cents`, measuring the whole-minute floor from now to the flight's `scheduled_departure_utc`. At twenty-four hours or more, the full `paid_cents` refunds to card and `retained_fee_cents` stays 0. Between two hours and twenty-four hours, the retained fee is ten percent of `paid_cents` rounded half-up, and the remainder refunds. Inside two hours there is no card refund: a credit leg of seventy-five percent of `paid_cents`, rounded half-up, is minted as a new `RebookingCredit`, and the fee keeps the remainder. In every tier `refunded_card_cents` grows by the refunded leg, and the fiscal invariant holds to the cent: `paid_cents` always equals `refunded_card_cents` plus `credited_cents` plus `retained_fee_cents`. Separately from the card settlement, whatever the booking had consumed in credits — its `credits_applied_cents` — is re-minted in full as a fresh `RebookingCredit` with a new 365-day validity.

Moving a booking swaps its flight without breaking CONFIRMED — a self-transition carrying the swap. The mover must carry `expected_booking_version` (§2.6), no passenger may yet be checked in, and the target named by `new_flight_id` must exist, sit in SCHEDULED or DELAYED, hold at least `seat_count` seats of `seats_available` (equality allowed, else `ERR_SEAT_CAPACITY_EXCEEDED`), and pass the provisional estimate gate of §3.5 (else `ERR_GROSS_WEIGHT_EXCEEDED`); these guards evaluate after the stale-version and state rungs, weight before capacity. Settlement then runs a pinned waterfall. The quote recomputes against the new flight — its season, its load, its weekend. The delta is the new `quoted_total_cents` minus the old. When the delta is positive, `additional_card_cents` must equal it exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`) and `paid_cents` grows by it. When negative, the card refund is the smaller of the delta's magnitude and `paid_cents`; the refund adds to `refunded_card_cents` while `paid_cents` itself is left unchanged — it remains the historical amount paid — and any excess beyond what the card can absorb is minted as a `RebookingCredit`. Finally the booking relocks: `flight_id` points at the new flight, `quoted_per_seat_cents`, `quoted_total_cents`, and `season_id` take the new quote's values, `credits_applied_cents` is recomposed as the new `quoted_total_cents` minus the new `paid_cents`, and the booking's `version` increments by one.

Involuntary cancellations share one cascade regardless of cause. Whether the trigger is the weather cascade of §3.2, the route suspension of §3.9, the aircraft grounding of §3.1, or a dispatcher's own weather or ops cancellation — available from SCHEDULED, DELAYED, BOARDING, or MANIFEST_CLOSED, stamping `cancel_reason` WEATHER or OPS_MANUAL respectively, with an optional `reason` note on the event — the bookings move the same way: HELD bookings become EXPIRED with no refund; CONFIRMED and CHECKED_IN bookings become CREDITED, their `credited_cents` set to `paid_cents`, and a `RebookingCredit` is minted for `paid_cents` plus `credits_applied_cents`; when the flight had already closed its manifest, MANIFESTED bookings take the same CREDITED path with the same credit minted. Cancellation also releases the flight from the rotation: `rotation_seq` recomputes over the remaining non-cancelled flights of that aircraft and date.

The credit ledger itself is simple and auditable. A `RebookingCredit` records the `booking_id` whose cancellation or move minted it, its `amount_cents` face value, `redeemed_cents` starting at 0, and `remaining_cents` always equal to face minus redeemed — the invariant `amount_cents` equals `redeemed_cents` plus `remaining_cents` holds at all times. `issued_at` stamps the logical clock at minting, and `expires_at` is exactly 365 days later; a credit whose `expires_at` is at or before now is EXPIRED, swept by the batch tick from either ISSUED or PARTIALLY_REDEEMED. Redemption applies a credit to a HELD booking: the credit must be ISSUED or PARTIALLY_REDEEMED with `remaining_cents` above zero, otherwise `ERR_CREDIT_NOT_REDEEMABLE`. The balance due is `quoted_total_cents` minus `credits_applied_cents` — `paid_cents` is always 0 while HELD — and the waterfall consumes the smaller of the credit's `remaining_cents` and that balance, adding it to both the credit's `redeemed_cents` and the booking's `credits_applied_cents`. A credit drained to zero becomes REDEEMED; one partially consumed becomes PARTIALLY_REDEEMED, passing ISSUED → PARTIALLY_REDEEMED on the way.

### 3.9. Community Complaints and the Noise Quota

A `CommunityReporter` files a noise complaint with `base_id`, the `zone` where the event was heard (VILLAGE, RIM, or AIRPORT), the `observed_at` instant, a free-text `description`, and an opaque `reporter_ref`. The moment a complaint is created, the auto-matcher runs. Eligible flights belong to the same base, sit in DISPATCHED or COMPLETED, fly a route whose `noise_zones` contain the complaint's `zone`, and have an overflight window — from `scheduled_departure_utc` up to but not including thirty minutes past `scheduled_arrival_utc` — containing `observed_at`. Candidates rank by absolute distance between `observed_at` and the flight's scheduled departure, nearest first; ties break to the earlier scheduled departure, then the earlier `created_at`. The winner sets `match_status` MATCHED, `matched_flight_id` to the flight, and `matched_route_id` to that flight's route; an empty candidate set is not an error — the complaint simply lands UNMATCHED with `matched_flight_id` null. A `ComplianceOfficer` may later link a flight manually; the link requires the target flight's route to overfly the complaint's zone, otherwise `ERR_COMPLAINT_FLIGHT_MISMATCH`, and it sets the same match fields without itself advancing the workflow status.

The complaint workflow runs LOGGED → UNDER_REVIEW when an officer opens review, or LOGGED → DISMISSED when dismissed outright; UNDER_REVIEW can likewise fall to DISMISSED. Substantiation — UNDER_REVIEW → SUBSTANTIATED — is the consequential step: it requires a matched flight, and that flight must be DISPATCHED or COMPLETED, otherwise `ERR_COMPLAINT_FLIGHT_MISMATCH`. When a complaint substantiates, the matched route's `substantiated_complaints_30d` recomputes — the count of SUBSTANTIATED complaints matched to that route whose `observed_at` lies within the rolling window from `complaint_window_days` days ago through now, both bounds inclusive — and if the count now meets or exceeds the base's `complaint_quota_threshold`, the route flips ACTIVE → SUSPENDED and its cascade fires: every flight of that route in SCHEDULED, DELAYED, or BOARDING departing now or later becomes CANCELLED_OPS with `cancel_reason` ROUTE_SUSPENDED, and the booking cascade of §3.8 runs on each. Flights already at MANIFEST_CLOSED or beyond are deliberately untouched — a route suspension never strands a closed manifest. An `OpsAdmin` may also suspend a route directly, firing the identical cascade. Resumption moves SUSPENDED → ACTIVE only when the recomputed count has fallen strictly below `complaint_quota_threshold`; otherwise the resume is rejected with `ERR_ROUTE_QUOTA_STILL_EXCEEDED`.

Closure records the outcome: SUBSTANTIATED → CLOSED or DISMISSED → CLOSED, capturing the officer's `resolution_note`. And closure is not necessarily the end — a CLOSED complaint may be reopened back to UNDER_REVIEW; the prior substantiation is retained in history, but the complaint stops counting toward the quota until it is substantiated again.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`. Operations that modify an existing resource, trigger state transitions, run batch sweeps, or read resources return HTTP 200 with the affected resource (or resources) in `data`. Errors carry the codes of §5 in the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/bases` | Create an operating base with regulatory config | OpsAdmin |
| GET | `/bases/{id}` | Get a base (posture computed on read) | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| PATCH | `/bases/{id}` | Update base config (OCC-guarded) | OpsAdmin |
| POST | `/bases/{id}/run-ops` | Batch tick: expire HELD bookings and credits, close stale duty-days, reset fatigue locks | OpsAdmin |
| POST | `/routes` | Create a route | OpsAdmin |
| GET | `/routes` | List routes | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/routes/{id}` | Get a route (substantiated complaint count recomputed on read) | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| POST | `/routes/{id}/events` | SUSPEND or RESUME a route | OpsAdmin |
| POST | `/seasons` | Create a PUBLISHED pricing season (half-open overlap check) | OpsAdmin |
| GET | `/seasons` | List seasons | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/seasons/{id}` | Get a season | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| POST | `/seasons/{id}/events` | RETIRE a season | OpsAdmin |
| POST | `/aircraft` | Register a helicopter | OpsAdmin |
| GET | `/aircraft` | List aircraft | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/aircraft/{id}` | Get an aircraft | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| POST | `/aircraft/{id}/events` | START_MAINTENANCE, END_MAINTENANCE, GROUND, or RECERTIFY | OpsAdmin |
| POST | `/pilots` | Register a pilot | OpsAdmin |
| GET | `/pilots` | List pilots | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/pilots/{id}` | Get a pilot | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/duty-days` | List duty-day ledgers (Pilot role may query only its own `pilot_id`) | OpsAdmin, Dispatcher, Pilot |
| GET | `/duty-days/{id}` | Get a duty-day ledger | OpsAdmin, Dispatcher, Pilot |
| POST | `/flights` | Schedule a flight (route-status, duty, availability, noise, quiet-hours, turn-window, and departure gates) | Dispatcher |
| GET | `/flights` | List flights with filters | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/flights/{id}` | Get a flight | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| PATCH | `/flights/{id}/assignment` | Reassign pilot and/or aircraft while SCHEDULED or DELAYED (OCC) | Dispatcher |
| POST | `/flights/{id}/events` | DELAY, ACCEPT_DELAY, OPEN_BOARDING, DISPATCH, COMPLETE, CANCEL_WEATHER, CANCEL_OPS (Dispatcher); PILOT_ACK (Pilot, own flights only) | Dispatcher, Pilot |
| POST | `/flights/{id}/close-manifest` | Close the weight-and-balance manifest from BOARDING (OCC) | Dispatcher |
| POST | `/bookings` | Create a HELD booking with passengers; locks the quote; runs capacity and estimate gates | BookingAgent |
| GET | `/bookings` | List bookings | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| GET | `/bookings/{id}` | Get a booking | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| POST | `/bookings/{id}/apply-credit` | Apply a rebooking credit to a HELD booking | BookingAgent |
| POST | `/bookings/{id}/confirm` | Confirm a HELD booking by paying the exact balance due | BookingAgent |
| POST | `/bookings/{id}/events` | CANCEL a booking (voluntary settlement tiers) | BookingAgent |
| POST | `/bookings/{id}/move` | Move a CONFIRMED booking to another flight with re-quote and settlement (OCC) | BookingAgent |
| GET | `/passengers` | List passengers (pax_index ascending within a booking) | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| GET | `/passengers/{id}` | Get a passenger | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| POST | `/passengers/{id}/events` | SIGN_WAIVER, COMPLETE_BRIEFING, CHECK_IN, or UNCHECK | BookingAgent |
| GET | `/credits` | List rebooking credits | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| GET | `/credits/{id}` | Get a rebooking credit | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer |
| POST | `/weather-observations` | Post a weather observation; adverse observations drive posture and the weather cascade | Dispatcher |
| GET | `/weather-observations` | List weather observations | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| GET | `/weather-observations/{id}` | Get a weather observation | OpsAdmin, Dispatcher, BookingAgent, ComplianceOfficer, CommunityReporter, Pilot |
| POST | `/complaints` | File a community noise complaint; auto-match runs at creation | CommunityReporter |
| GET | `/complaints` | List complaints | OpsAdmin, Dispatcher, ComplianceOfficer, CommunityReporter |
| GET | `/complaints/{id}` | Get a complaint | OpsAdmin, Dispatcher, ComplianceOfficer, CommunityReporter |
| POST | `/complaints/{id}/events` | REVIEW, LINK_FLIGHT, SUBSTANTIATE, DISMISS, CLOSE, or REOPEN | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_WEATHER_HOLD_ACTIVE | 409 |
| ERR_PILOT_NOT_AVAILABLE | 409 |
| ERR_PILOT_FLIGHT_TIME_EXCEEDED | 409 |
| ERR_PILOT_DUTY_LIMIT_EXCEEDED | 409 |
| ERR_AIRCRAFT_NOT_AVAILABLE | 409 |
| ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT | 409 |
| ERR_QUIET_HOURS_VIOLATION | 409 |
| ERR_GROSS_WEIGHT_EXCEEDED | 422 |
| ERR_FUEL_BELOW_MINIMUM | 422 |
| ERR_CG_OUT_OF_ENVELOPE | 422 |
| ERR_SEGREGATION_OF_DUTY | 403 |
| ERR_DEPARTURE_IN_PAST | 409 |
| ERR_SEASON_OVERLAP | 409 |
| ERR_AIRCRAFT_TURN_CONFLICT | 409 |
| ERR_PILOT_SCHEDULE_OVERLAP | 409 |
| ERR_BOOKING_HOLD_EXPIRED | 409 |
| ERR_WAIVER_VERSION_STALE | 409 |
| ERR_WAIVER_NOT_SIGNED | 409 |
| ERR_BRIEFING_INCOMPLETE | 409 |
| ERR_PILOT_MISMATCH | 403 |
| ERR_PILOT_ACK_REQUIRED | 409 |
| ERR_COMPLAINT_FLIGHT_MISMATCH | 409 |
| ERR_ROUTE_SUSPENDED | 409 |
| ERR_ROUTE_QUOTA_STILL_EXCEEDED | 409 |
| ERR_SEAT_CAPACITY_EXCEEDED | 409 |
| ERR_SEAT_NUMBER_TAKEN | 409 |
| ERR_DUPLICATE_PASSENGER | 409 |
| ERR_UNIQUENESS_CONFLICT | 409 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 402 |
| ERR_CREDIT_NOT_REDEEMABLE | 409 |
