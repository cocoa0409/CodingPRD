# Paratransit ADA Transit API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an Access-A-Ride style paratransit service platform that delivers ADA complementary transit. The system governs the full arc of a paratransit rider's relationship with the service: eligibility certification through an in-person functional assessment, recertification when a certification lapses, reservation of both ad-hoc and standing (subscription) trips, a negotiated pickup-time workflow between dispatchers and riders, capacity-aware assignment of trips onto vehicle runs, execution of trips with on-time-performance measurement, and enforcement of the no-show / late-cancel penalty regime that a public agency must administer fairly.

The platform must reconcile several competing pressures. It has to honor the ADA's geographic promise — a rider is entitled to service only within a three-quarter-mile band around a certified zone center — while capping fares at the federally mandated multiple of the comparable fixed-route fare. It has to keep vehicle runs safe and legally compliant by never overbooking securement positions or ambulatory seats, and it has to discourage no-shows through a graduated, points-based suspension ladder without punishing riders for cancellations made in good time. Because the same vehicle run can legitimately accept two different trips against spare capacity, booking is governed by optimistic concurrency so that two views of a run's capacity cannot silently clobber one another. Every time-sensitive rule in the system reads from a single server-controlled logical clock rather than wall-clock time, so that test scenarios and audits are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Authentication is decided solely from `X-User-Role`: if it is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A missing `X-User-ID` is not itself an authentication failure — it simply resolves to no acting identity, so a later rider-ownership comparison against it fails. If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Rider`, `Dispatcher`, `Driver`, `EligibilitySpecialist`, and `Admin`.

When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`; ownership checks on any resource that references a rider compare that resource's `rider_id` to `X-User-ID`. A rider acting on a trip reservation, subscription, or appeal they do not own is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403). When `X-User-Role` is `Dispatcher`, `Driver`, `EligibilitySpecialist`, or `Admin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id` for ownership.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it reflects real wall-clock time and is independent of the logical clock of §2.4.
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

List endpoints accept two query parameters. `limit` is the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0. A supplied `limit` below 1 or above 100, or an `offset` below 0, is silently clamped into range rather than rejected; a `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order, and resources that share a `created_at` are further ordered by their creation sequence (insertion order). Each list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

Every time-gated rule in this system — certification validity, certification expiry, penalty rolling windows, penalty timestamps, late-cancel lead-time, and pickup-window on-time evaluation — reads the current instant from a single server-controlled logical clock, never from wall-clock time. An administrative test-driving capability sets that clock to a supplied instant, provided as `to_iso8601`, and returns the new value as `current_utc`. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any set call it holds that default rather than falling back to real time.

### 2.5. Common Resource Properties

Most resources are audited resources and carry a standard system-managed set of fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation, and it — like `updated_at` — is read from the logical clock of §2.4 (the current logical instant at creation or mutation), not from wall-clock time. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 and increments by one on every mutation of the resource; it underpins optimistic concurrency. Riders, eligibility applications, functional assessments, trip reservations, subscription trips, vehicle runs, and penalty events are all audited resources of this kind.

Two resource types are deliberately lightweight. A `ServiceZone` and a `NegotiationOffer` carry only `id` and `created_at`; they have neither `updated_at` nor `version`, because a zone is configuration and an offer is an immutable historical record of a single negotiation round.

### 2.6. Request Validation Order and Existence Checks

Validations are applied in a fixed priority order so that the same failing request always produces the same error. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization (`ERR_UNAUTHORIZED`). Next — and before any referenced resource is looked up — the request body itself is validated: structural problems (a missing required field, a wrong type, or an unrecognized enum member) yield `ERR_INVALID_REQUEST` (HTTP 400), and numeric inputs outside their allowed range yield `ERR_OUT_OF_RANGE` (HTTP 422), so a structurally invalid or out-of-range body is rejected before existence is checked. Then every resource referenced in the path or body must exist; existence is validated left-to-right along the URL, and the first identifier that does not resolve produces the corresponding not-found error — `ERR_RIDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_PENALTY_NOT_FOUND` (all HTTP 404). After existence, a rider acting through their entity-backed identity must own the target resource, or the request fails with `ERR_FORBIDDEN_NOT_OWNER`; this ownership check guards rider countering, accepting, and cancelling of trips, subscription creation and cancellation, and appeal of an application by a rider.

Following those cross-cutting gates, endpoint-specific business rules apply. The generic state guard — the target resource must be in a state that permits the requested transition — surfaces as `ERR_INVALID_STATE` (HTTP 409) on every state-changing endpoint. The structural (`ERR_INVALID_REQUEST`) and range (`ERR_OUT_OF_RANGE`) body validations described above are the ones that gate these business rules, and they run before the existence and ownership gates rather than after the state guard. Numeric range checking (negative capacities, negative fares, negative service radius, negative companion counts, or invalid coordinates) applies to service-zone creation, vehicle-run creation, trip requests, and subscription creation.

### 2.7. Service-Area Geometry: The Three-Quarter-Mile Rule

The ADA service area is a circular band around each zone's center. A `ServiceZone` is created with a `zone_code` (unique across all zones; a duplicate `zone_code` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a human-readable `name`, a center given by `center_lat` and `center_lng`, and a `service_radius_miles` that defaults to 0.75 when omitted — the three-quarter-mile ADA radius. A location is inside the zone when the great-circle distance from the zone center to the location is less than or equal to `service_radius_miles`; a point lying exactly on the boundary is considered in-service.

Distance is computed with the haversine great-circle formula on an Earth radius of 3958.7613 miles. For two points, take the latitude difference and the longitude difference in radians; the haversine term is the square of the sine of half the latitude difference, plus the product of the cosine of the first latitude, the cosine of the second latitude, and the square of the sine of half the longitude difference; the distance is twice the Earth radius times the arcsine of the square root of that term. The distance is kept at full floating-point precision and compared inclusively against the radius. Whenever a trip or subscription is created, both the pickup point and the dropoff point are checked against their respective zones' centers, and any point beyond its zone's radius rejects the request with `ERR_OUTSIDE_SERVICE_AREA` (HTTP 422).

### 2.8. Fares and Monetary Precision

All monetary values are integer cents, and fare arithmetic performs no rounding because every input is already an integer number of cents. A zone declares its `base_fare_cents` (the base one-way paratransit fare for a trip within the zone) and its `fixed_route_fare_cents` (the comparable fixed-route fare, which anchors the ADA fare cap). The fare computation and its cross-zone, cap, and companion terms are detailed in §3.8.

### 2.9. Vehicle-Run Capacity and Optimistic Concurrency

A `VehicleRun` is a dated route with finite capacity. It is created with a `service_zone_id`, a `service_date` (formatted `YYYY-MM-DD`), a `total_ambulatory_seats` count, and a `total_wheelchair_positions` count. The run tracks `available_ambulatory_seats` and `available_wheelchair_positions`, each equal to the corresponding total minus the peak concurrent occupancy across the run's assigned non-terminal trips over the relevant interval. Both availability figures begin equal to their totals when the run is created.

Because a run with spare capacity can legitimately accept two different trips, booking a trip onto a run is governed by optimistic concurrency rather than by capacity alone. When a rider accepts an offered trip onto a run, the request must carry `expected_run_version` holding the `version` of the target `VehicleRun` that the client last observed. If that value does not match the run's current `version` — that is, if another accept has already booked against the run and advanced its version since the client last read it — the accept is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412), preventing the client from booking against a run whose capacity it has not actually seen. Only the accept operation carries this version field; no other endpoint takes one. Every capacity-mutating event on a run — an accept, a release on cancel or dropoff, and the dispatch cascade — increments the run's `version` by one and refreshes its `updated_at`.

### 2.10. No-Show Penalty Accounting

The agency administers a points-based penalty ledger. Each `PenaltyEvent` records a `rider_id`, the `trip_id` that caused it, an `event_type` of either `NO_SHOW` or `LATE_CANCEL`, the `points` assessed, a `status` of `ACTIVE` or `VOIDED`, and the `occurred_at` logical-clock instant at which it was recorded. A no-show event assesses a fixed no-show point value of 3 points (`NO_SHOW_POINTS`) and a late-cancel event assesses a fixed late-cancel point value of 1 point (`LATE_CANCEL_POINTS`).

Two running totals are maintained per rider. The rolling total, `no_show_points_rolling`, is the sum of `points` over the rider's `ACTIVE` penalty events whose `occurred_at` falls on or after the logical clock minus 30 days (the lower bound is inclusive). The lifetime total, `no_show_points_lifetime`, is the sum of `points` over all of the rider's `ACTIVE` penalty events regardless of age; once events age past 30 days the lifetime total exceeds the rolling total. Both totals are integer points and are recomputed whenever a penalty event is created and whenever one is waived.

The rolling total drives the rider's `penalty_tier`. If the rolling total is at least 6 points, the tier is `SUSPENDED`; otherwise if it is at least 3 points, the tier is `WARNING`; otherwise the tier is `NONE`. Both threshold comparisons are inclusive (at-least) at their boundary. Crossing into the suspended tier drives the account-suspension cascade described in §3.9, and the length of a suspension is determined by how many suspensions the rider has already served: with a `prior_suspension_count` of 0 the suspension lasts 7 days, with a count of 1 it lasts 15 days, and with a count of 2 or more it lasts 30 days; the count is read before it is incremented.

## 3. Business Logic & Workflows

### 3.1. Rider Registration and the Certification Lifecycle

A rider is registered with a `full_name`, a `phone`, an `email`, a home location given by `home_lat` and `home_lng`, an optional `mobility_device`, and an optional `requires_pca` flag indicating the rider travels with a Personal Care Attendant. The `mobility_device` is one of `NONE`, `CANE`, `WALKER`, `MANUAL_WHEELCHAIR`, `POWER_WHEELCHAIR`, or `SCOOTER`, defaulting to `NONE`, and `requires_pca` defaults to false. A newly registered rider begins with `eligibility_status` of `UNCERTIFIED` and `account_status` of `ACTIVE`. The rider's `eligibility_status` is one of `UNCERTIFIED`, `CONDITIONAL`, `FULL`, `EXPIRED`, or `SUSPENDED`, while the independent `account_status` dimension is either `ACTIVE` or `SUSPENDED`; the two gate bookings separately. A rider read exposes the computed `eligibility_status`, `no_show_points_rolling`, `no_show_points_lifetime`, and `penalty_tier`, along with `certification_expires_at`, `suspension_until`, and `prior_suspension_count`.

Certification runs through an `EligibilityApplication`, which references its `rider_id` and carries an `application_type` of either `NEW` (an initial certification) or `RECERT` (a recertification), defaulting to `NEW`. A specialist submits an application, which is created in `SUBMITTED`. A rider may hold only one open application at a time: if the rider already has a non-terminal application — one in any state other than the terminal `CERTIFIED` — a new submission is rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION` (HTTP 409). An application's `status` progresses through `SUBMITTED`, `ASSESSMENT_SCHEDULED`, `ASSESSED`, `CERTIFIED`, `DENIED`, and `APPEALED`; `CERTIFIED` is the terminal state. It also carries an `assessment_outcome` (copied from the assessment, one of `PENDING`, `PASS_UNCONDITIONAL`, `PASS_CONDITIONAL`, or `FAIL`), a `certified_category` (one of `UNCONDITIONAL` or `CONDITIONAL`, set only at certification), a `certification_valid_until` instant, and an `appeal_count`.

### 3.2. Functional Assessment

Scheduling an in-person functional assessment is permitted when the parent application is in either `SUBMITTED` or `APPEALED`; the act creates a `FunctionalAssessment` in `SCHEDULED` and advances the application from `SUBMITTED` to `ASSESSMENT_SCHEDULED` (or, when re-entering after an appeal, from `APPEALED` to `ASSESSMENT_SCHEDULED`). The assessment references its `application_id` and records the appointment time as `scheduled_at`. If the application is in any other state, the transition is refused with `ERR_INVALID_STATE`.

Completing an assessment records its `outcome` and the `assessed_mobility_device` confirmed in person, moves the assessment from `SCHEDULED` to `COMPLETED`, and, as a cross-entity side effect, advances the parent application from `ASSESSMENT_SCHEDULED` to `ASSESSED` with the assessment's `outcome` copied into the application's `assessment_outcome`. Completion is permitted only when the assessment being completed belongs to the referenced application, the assessment's `status` is `SCHEDULED`, and the parent application's `status` is `ASSESSMENT_SCHEDULED`; otherwise the request is rejected with `ERR_INVALID_STATE`. A functional assessment carries a `status` of either `SCHEDULED` or `COMPLETED` and an `outcome` that defaults to `PENDING` until completion.

### 3.3. Certification, Denial, and Appeal

Certifying an application is permitted only when its `status` is `ASSESSED` and its `assessment_outcome` is either `PASS_UNCONDITIONAL` or `PASS_CONDITIONAL`; otherwise the request is refused with `ERR_INVALID_STATE`. On certification the application advances from `ASSESSED` to `CERTIFIED` and its `certified_category` is set to `UNCONDITIONAL` when the outcome was `PASS_UNCONDITIONAL` and to `CONDITIONAL` otherwise. The application's `certification_valid_until` is set to the logical clock plus the certification-validity period (`CERT_VALIDITY_DAYS`, which is 1095 days). As a cascade onto the rider, the rider's `eligibility_status` becomes `FULL` when the category is `UNCONDITIONAL` and `CONDITIONAL` otherwise, and the rider's `certification_expires_at` is set equal to the application's `certification_valid_until`.

Denying an application is the symmetric branch: it is permitted only when the `status` is `ASSESSED` and the `assessment_outcome` is `FAIL`, and it advances the application from `ASSESSED` to `DENIED`, leaving the rider's `eligibility_status` unchanged (the rider remains `UNCERTIFIED` or `EXPIRED`). Any other combination is rejected with `ERR_INVALID_STATE`.

A denied application may be appealed, either by the specialist or by the owning rider. Appeal is permitted only when the application's `status` is `DENIED`; it advances the application from `DENIED` to `APPEALED` and increments `appeal_count` by one. Scheduling a fresh assessment against an `APPEALED` application (per §3.2) reopens the assessment cycle, so the full recovery path runs `DENIED → APPEALED → ASSESSMENT_SCHEDULED → ASSESSED`, from which the application may again be certified or denied.

### 3.4. Requesting Trips and Standing Subscriptions

Before any booking is created the system enforces the rider's eligibility. To request a trip the rider's `eligibility_status` must be either `FULL` or `CONDITIONAL`, or the request is rejected with `ERR_RIDER_NOT_ELIGIBLE` (HTTP 409); the rider's `account_status` must be `ACTIVE` and not under a no-show suspension, or the request is rejected with `ERR_RIDER_SUSPENDED` (HTTP 409); and the rider's `certification_expires_at` must be strictly after the logical clock, or the request is rejected with `ERR_ELIGIBILITY_EXPIRED` (HTTP 409). All three checks apply when requesting an ad-hoc trip. The suspension check is evaluated purely on `account_status`: a suspended rider's `account_status` stays `SUSPENDED` until it is explicitly changed, and `suspension_until` is recorded for reference but does not by itself restore booking eligibility even once the logical clock passes it. Because a no-show suspension also drives the rider's `eligibility_status` to `SUSPENDED`, the suspension check takes precedence over the eligibility check for a suspended rider — such a request is rejected with `ERR_RIDER_SUSPENDED`, not `ERR_RIDER_NOT_ELIGIBLE`.

An ad-hoc trip request supplies the `rider_id`, the `pickup_zone_id` and `dropoff_zone_id`, the pickup and dropoff coordinates `pickup_lat`, `pickup_lng`, `dropoff_lat`, and `dropoff_lng`, and the `requested_pickup_at`; it may also supply the trip's capacity-shaping attributes `needs_wheelchair` (default false), `num_companions` (default 0), and `has_pca` (default false), which are stored on the trip and later drive its seat/position demand and fare. The pickup and dropoff points are each validated against their zone's three-quarter-mile radius per §2.7. A successful request creates a `TripReservation` in `REQUESTED`. The trip's `subscription_trip_id` is null for an ad-hoc trip and is set only when the trip is materialized from a standing subscription.

A standing subscription is created as a `SubscriptionTrip` template for a rider, supplying the `rider_id`, `pickup_zone_id`, `dropoff_zone_id`, the standing coordinates `pickup_lat`, `pickup_lng`, `dropoff_lat`, and `dropoff_lng`, a recurring `day_of_week` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`), and a recurring `pickup_time_utc` expressed as `HH:MM` in UTC; like an ad-hoc request it also accepts the optional `needs_wheelchair` (default false), `num_companions` (default 0), and `has_pca` (default false) attributes on the template. Creating a subscription checks that the rider's `eligibility_status` is `FULL` or `CONDITIONAL` (else `ERR_RIDER_NOT_ELIGIBLE`) and validates both coordinates against their zones' service radii (else `ERR_OUTSIDE_SERVICE_AREA`); it does not apply the suspension or expiry gates at template-creation time. A subscription is created with `status` `ACTIVE` and may later be `CANCELLED`.

Materializing a dated trip from an `ACTIVE` subscription is a dispatcher action that re-checks eligibility, suspension, expiry, and service area at materialization time: the rider must be eligible (`ERR_RIDER_NOT_ELIGIBLE`), must not be suspended (`ERR_RIDER_SUSPENDED`), must have an unexpired certification (`ERR_ELIGIBILITY_EXPIRED`), and both coordinates must be in-service (`ERR_OUTSIDE_SERVICE_AREA`). The dispatcher supplies the `service_date` and the `requested_pickup_at` for the instance, and the system creates a `TripReservation` in `REQUESTED` with its `subscription_trip_id` set to the originating subscription; the materialized trip inherits the subscription's `pickup_zone_id`, `dropoff_zone_id`, pickup and dropoff coordinates, and `needs_wheelchair`, `num_companions`, and `has_pca` attributes, while the supplied `service_date` is required as a non-empty string but is not itself persisted on the trip.

### 3.5. Negotiating the Pickup Time

A requested trip enters a negotiation loop over the pickup time. A dispatcher makes an offer, supplying a `proposed_pickup_at`; this advances the trip from `REQUESTED` to `OFFERED` (or from `COUNTERED` back to `OFFERED` on a subsequent round), records a `NegotiationOffer` whose `offered_by` is `DISPATCHER` and whose `proposed_pickup_at` and `round_number` capture the proposal, sets the trip's `current_offer_pickup_at` to the proposed time, and increments the trip's `offer_round`. The owning rider may counter an offered time, supplying their own `proposed_pickup_at`; this advances the trip from `OFFERED` to `COUNTERED`, records a `NegotiationOffer` whose `offered_by` is `RIDER`, updates `current_offer_pickup_at`, and increments `offer_round`. Each `NegotiationOffer` carries a one-based `round_number`, and the trip's `offer_round` counts the exchanges. The `OFFERED` and `COUNTERED` states form the negotiated-pickup cycle, which continues until the rider accepts or someone cancels. Attempting to offer or counter from a state that does not permit it is refused with `ERR_INVALID_STATE`, and only the owning rider may counter (else `ERR_FORBIDDEN_NOT_OWNER`).

### 3.6. Accepting an Offer onto a Vehicle Run

Acceptance is the booking act, and it is where the system's capacity, concurrency, and scheduling rules converge. The owning rider accepts the current offer, supplying the target run as `run_id` and the run version they last observed as `expected_run_version`; a successful accept advances the trip from `OFFERED` to `SCHEDULED`. Acceptance is guarded by a sequence of checks evaluated in this order after existence and ownership: the trip must be `OFFERED` (else `ERR_INVALID_STATE`); the rider's `account_status` must be `ACTIVE` (else `ERR_RIDER_SUSPENDED`); the target run's `status` must be `PLANNED` or `OPEN` (else `ERR_RUN_NOT_OPEN`, HTTP 409); the supplied `expected_run_version` must match the run's current `version` (else `ERR_STALE_RUN_VERSION`, HTTP 412, per §2.9); a wheelchair position must be free over the trip's interval when the trip needs securement (else `ERR_NO_WHEELCHAIR_CAPACITY`, HTTP 409); enough ambulatory seats must be free over the interval (else `ERR_NO_SEAT_CAPACITY`, HTTP 409); and the rider must have no other non-terminal trip whose buffered interval overlaps this one (else `ERR_RIDER_TRIP_OVERLAP`, HTTP 409).

The seat and position demand of a trip depends on how the rider travels. When the trip's `needs_wheelchair` flag is set, the rider occupies one wheelchair (securement) position and does not consume an ambulatory seat; otherwise the rider occupies one ambulatory seat. Each of the `num_companions` fare-paying companions consumes an ambulatory seat, and when `has_pca` is set the accompanying Personal Care Attendant also consumes an ambulatory seat (though the PCA rides free). Wheelchair availability compares the peak concurrent wheelchair occupancy over the trip's interval against `total_wheelchair_positions`, and ambulatory availability compares the peak concurrent ambulatory demand — rider-if-ambulatory plus companions plus PCA — over the interval against `total_ambulatory_seats`. The overlap guard compares this trip's buffered interval against the buffered interval of each of the rider's other non-terminal trips, where a trip's buffered interval extends from fifteen minutes before its pickup to fifteen minutes after its dropoff (`TURNAROUND_BUFFER_MINUTES` of 15 minutes on each side); the intervals are closed, so touching endpoints count as an overlap.

A successful accept sets `scheduled_pickup_at` equal to `current_offer_pickup_at` and `scheduled_dropoff_at` equal to `scheduled_pickup_at` plus the fixed trip duration (`TRIP_DURATION_MINUTES`, which is 60 minutes), sets `assigned_run_id` to the chosen run, computes the provisional fare into `estimated_fare_cents`, decrements the run's `available_wheelchair_positions` and `available_ambulatory_seats` by the trip's needs, and increments the run's `version` by one.

### 3.7. Vehicle Runs: Opening, Dispatching, and Manifests

A dispatcher creates a run in `PLANNED`, opens it for booking (advancing `PLANNED → OPEN`), and later dispatches it (advancing `OPEN → DISPATCHED`). A run's `status` moves through `PLANNED`, `OPEN`, `DISPATCHED`, and the terminal states `CLOSED` and `CANCELLED`. Opening is permitted only from `PLANNED` and dispatching only from `OPEN`; otherwise the transition is refused with `ERR_INVALID_STATE`. Dispatching a run cascades to its trips: every trip assigned to the run that is currently `SCHEDULED` advances from `SCHEDULED` to `EN_ROUTE`, and the run's `version` is incremented by one. A run's manifest lists the trips assigned to it (those whose `assigned_run_id` is the run), and the run read exposes `available_ambulatory_seats`, `available_wheelchair_positions`, and `version`.

### 3.8. Executing the Trip: Pickup, Dropoff, Fares, and On-Time Performance

A driver records the actual pickup, supplying the `actual_pickup_at` instant and the `actual_pickup_zone_id`; this advances the trip from `SCHEDULED` or `EN_ROUTE` to `PICKED_UP` and computes the `on_time` flag. A pickup is on-time when the actual pickup instant falls within the pickup window, which opens at `scheduled_pickup_at` and closes 30 minutes later (`PICKUP_WINDOW_MINUTES`): `on_time` is true when the actual pickup is at or after the window start and at or before the window end, with both boundaries inclusive so that a pickup exactly at the closing edge is still on-time. Until pickup, `on_time` is null.

A driver then records the dropoff, supplying the `actual_dropoff_at` instant and the `actual_dropoff_zone_id`; this advances the trip from `PICKED_UP` to `COMPLETED`, computes the final fare into `final_fare_cents`, releases the trip's held positions and seats back to the run, and increments the run's `version` by one.

The fare is computed twice from the same rule: a provisional fare at accept, stored in `estimated_fare_cents` and priced from the trip's requested `pickup_zone_id` and `dropoff_zone_id`, and a final fare at dropoff, stored in `final_fare_cents` and priced from the actual `actual_pickup_zone_id` and `actual_dropoff_zone_id`. For the pickup and dropoff zones of the variant being priced, the base is determined as follows: when the pickup zone and the dropoff zone are the same zone, the base equals that zone's `base_fare_cents`; otherwise the base equals the greater of the pickup zone's `base_fare_cents` and the dropoff zone's `base_fare_cents`, plus a cross-zone surcharge of 150 cents. That base is then capped at the ADA ceiling: the capped amount is the lesser of the base and twice the pickup zone's `fixed_route_fare_cents` (a fare-cap multiplier of 2). Finally, a companion charge of 275 cents per companion is added, one charge for each of the trip's `num_companions`; the Personal Care Attendant is never charged and is not counted in this term. The fare is the capped amount plus the companion charge, kept in integer cents with no rounding. Because the final variant uses the actual dropoff zone, the final fare may differ from the provisional one when the actual dropoff zone differs from the requested one.

The fleet on-time-performance report aggregates over every trip that reached `PICKED_UP` or `COMPLETED` within an optional `service_zone_id` and `service_date` filter — that is, every trip whose `on_time` is not null. When either filter is supplied it is matched against the trip's assigned run: a trip counts only when its `assigned_run_id` resolves to a run whose `service_zone_id` (and/or `service_date`) equals the filter, and a qualifying trip with no assigned run is excluded whenever any filter is present. It returns `total_pickups` (the count of such trips), `on_time_pickups` (the count of those whose `on_time` is true), and `otp_pct`. The percentage is computed by summing across all matching trips first, then dividing `on_time_pickups` by `total_pickups`, then multiplying by 100, and rounding that single result half-up to two decimal places; rounding each trip or run individually before averaging is not used. When `total_pickups` is 0, `otp_pct` is `0.0`.

### 3.9. Cancellations, No-Shows, and the Suspension Cascade

A rider may cancel their own trip. A cancellation before the trip is scheduled — while the trip is `REQUESTED`, `OFFERED`, or `COUNTERED` — moves the trip to `CANCELLED` with no penalty. A cancellation of a `SCHEDULED` trip depends on lead time: if the interval from the logical clock to `scheduled_pickup_at` is at least the late-cancel lead time (`LATE_CANCEL_LEAD_HOURS`, which is 2 hours), the trip moves to `CANCELLED`, its held positions and seats are released back to the run, and the run's `version` is incremented by one. If instead that lead time falls short of `LATE_CANCEL_LEAD_HOURS`, the trip moves to `LATE_CANCELLED`: its `late_cancel` flag is set to true, a `PenaltyEvent` of `event_type` `LATE_CANCEL` is created with the late-cancel point value (`LATE_CANCEL_POINTS`) and `occurred_at` set to the logical clock, the rider's rolling total, lifetime total, and `penalty_tier` are recomputed, and the run capacity is released with the run's `version` incremented by one.

A no-show is recorded by a driver or dispatcher against a trip that is `SCHEDULED` or `EN_ROUTE`, advancing it to `NO_SHOW`. This triggers a four-hop cascade. First, a `PenaltyEvent` of `event_type` `NO_SHOW` is created with the no-show point value (`NO_SHOW_POINTS`) and `occurred_at` set to the logical clock. Second, the rider's `no_show_points_rolling` is recomputed, and if it is at least 6 points the rider's `account_status` becomes `SUSPENDED`, the `eligibility_status` becomes `SUSPENDED`, the `suspension_until` is set to the logical clock plus the tiered suspension length (7, 15, or 30 days by the `prior_suspension_count` read before increment, per §2.10), and `prior_suspension_count` is incremented by one. Third, if the rider is thereby suspended, every one of the rider's other non-terminal trips transitions to `CANCELLED_BY_SYSTEM`. Fourth, each such system-cancelled trip that was holding run capacity releases it back to its own `VehicleRun` and increments that run's `version` by one. In addition, the no-show trip's own held positions and seats are released back to its run and that run's `version` is incremented by one. A trip's lifecycle states are `REQUESTED`, `OFFERED`, `COUNTERED`, `SCHEDULED`, `EN_ROUTE`, `PICKED_UP`, `COMPLETED`, `CANCELLED`, `LATE_CANCELLED`, `NO_SHOW`, and `CANCELLED_BY_SYSTEM`, of which the last five are terminal.

### 3.10. Waiving Penalties

A specialist may waive a penalty event, moving its `status` from `ACTIVE` to `VOIDED`. Because both running totals count only `ACTIVE` events, a waiver recomputes the affected rider's `no_show_points_rolling`, `no_show_points_lifetime`, and `penalty_tier`. The same recomputation that runs on any penalty creation therefore also runs on a waiver, keeping the rolling total, the lifetime total, and the tier consistent with the surviving active penalties.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; state transitions and other modifications of existing resources return `200 OK`, and reads return `200 OK`. The logical-clock set operation returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/service-zones` | Create a service zone | Admin |
| POST | `/riders` | Register a rider | EligibilitySpecialist, Admin |
| GET | `/riders/{id}` | Read a rider with computed eligibility and penalty fields | Admin, Dispatcher, Driver, EligibilitySpecialist, Rider |
| POST | `/eligibility-applications` | Submit a new or recertification application | EligibilitySpecialist |
| GET | `/eligibility-applications/{id}` | Read an eligibility application | Admin, EligibilitySpecialist, Rider |
| GET | `/eligibility-applications` | List eligibility applications (filter by rider_id, status) | Admin, EligibilitySpecialist, Rider |
| POST | `/eligibility-applications/{id}/certify` | Certify an assessed, passing application | EligibilitySpecialist |
| POST | `/eligibility-applications/{id}/deny` | Deny an assessed, failing application | EligibilitySpecialist |
| POST | `/eligibility-applications/{id}/appeal` | Appeal a denied application | EligibilitySpecialist, Rider |
| POST | `/functional-assessments` | Schedule a functional assessment | EligibilitySpecialist |
| GET | `/functional-assessments/{id}` | Read a functional assessment | Admin, EligibilitySpecialist, Rider |
| GET | `/functional-assessments` | List functional assessments (filter by application_id) | Admin, EligibilitySpecialist, Rider |
| POST | `/functional-assessments/{id}/complete` | Record the assessment outcome | EligibilitySpecialist |
| POST | `/trip-reservations` | Request an ad-hoc trip | Rider |
| GET | `/trip-reservations/{id}` | Read a trip reservation | Admin, Dispatcher, Driver, EligibilitySpecialist, Rider |
| GET | `/trip-reservations` | List trips (filter by rider_id, pickup_zone_id, dropoff_zone_id, subscription_trip_id, status) | Admin, Dispatcher, Driver, EligibilitySpecialist, Rider |
| POST | `/trip-reservations/{id}/offer` | Dispatcher proposes a pickup time | Dispatcher |
| POST | `/trip-reservations/{id}/counter` | Rider counters the offered pickup time | Rider |
| POST | `/trip-reservations/{id}/accept` | Rider accepts the current offer and books onto a run | Rider |
| POST | `/trip-reservations/{id}/cancel` | Rider cancels a trip | Rider |
| POST | `/trip-reservations/{id}/pickup` | Driver records actual pickup | Driver |
| POST | `/trip-reservations/{id}/dropoff` | Driver records actual dropoff | Driver |
| POST | `/trip-reservations/{id}/no-show` | Mark a trip a no-show | Driver, Dispatcher |
| GET | `/trip-reservations/{id}/offers` | List the negotiation offers for a trip | Admin, Dispatcher, Driver, EligibilitySpecialist, Rider |
| POST | `/subscription-trips` | Create a standing subscription trip | Rider |
| GET | `/subscription-trips/{id}` | Read a subscription trip | Admin, Dispatcher, EligibilitySpecialist, Rider |
| GET | `/subscription-trips` | List subscription trips (filter by rider_id, pickup_zone_id, dropoff_zone_id) | Admin, Dispatcher, EligibilitySpecialist, Rider |
| POST | `/subscription-trips/{id}/instantiate` | Materialize a dated trip from a standing trip | Dispatcher |
| POST | `/vehicle-runs` | Create a vehicle run | Dispatcher |
| GET | `/vehicle-runs/{id}` | Read a vehicle run | Admin, Dispatcher, Driver |
| GET | `/vehicle-runs` | List vehicle runs (filter by service_zone_id, service_date) | Admin, Dispatcher, Driver |
| GET | `/vehicle-runs/{id}/manifest` | List the trips assigned to a run | Admin, Dispatcher, Driver |
| POST | `/vehicle-runs/{id}/open` | Open a planned run for booking | Dispatcher |
| POST | `/vehicle-runs/{id}/dispatch` | Dispatch an open run | Dispatcher |
| GET | `/penalty-events/{id}` | Read a penalty event | Admin, EligibilitySpecialist, Rider |
| GET | `/penalty-events` | List penalty events (filter by rider_id, trip_id) | Admin, EligibilitySpecialist, Rider |
| POST | `/penalty-events/{id}/waive` | Waive (void) a penalty event | EligibilitySpecialist |
| GET | `/reports/on-time-performance` | Fleet on-time performance report | Admin, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_RIDER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_TRIP_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_PENALTY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_OUT_OF_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_ACTIVE_APPLICATION` | 409 |
| `ERR_RIDER_NOT_ELIGIBLE` | 409 |
| `ERR_RIDER_SUSPENDED` | 409 |
| `ERR_ELIGIBILITY_EXPIRED` | 409 |
| `ERR_RUN_NOT_OPEN` | 409 |
| `ERR_STALE_RUN_VERSION` | 412 |
| `ERR_OUTSIDE_SERVICE_AREA` | 422 |
| `ERR_NO_WHEELCHAIR_CAPACITY` | 409 |
| `ERR_NO_SEAT_CAPACITY` | 409 |
| `ERR_RIDER_TRIP_OVERLAP` | 409 |
