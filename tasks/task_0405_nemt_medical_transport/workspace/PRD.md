# Nemt Medical Transport API — Product Requirements Document

## 1. Introduction

Non-Emergency Medical Transport (NEMT) brokerages sit between the state Medicaid program and a fragmented network of transportation providers. A member with a covered benefit needs to reach a dialysis chair, a wound-care clinic, or a specialist appointment; a coordinator must confirm that the member's coverage is current and that the requested vehicle is appropriate to the member's mobility; a broker must locate a driver whose vehicle and service area actually fit the trip; the driver must execute the run, including the awkward reality of will-call returns where the member calls only once their appointment ends; and finally the money must be settled — a forward-looking claim the broker submits against the schedule, reconciled against an encounter record capturing what actually happened on the road. This API models that full chain.

The platform is organized around the **TripRequest** as the hub entity, with peer entities — members, eligibility spans, brokers, drivers, rate schedules, legs, assignments, standing orders, claims, and encounters — referencing one another by identifier rather than nesting under a single hierarchy. Two ideas make the domain genuinely hard and are worth stating up front. First, a trip carries two independent status axes: a lifecycle axis that tracks the operational journey from draft to completion, and a billing axis that tracks claim-and-encounter reconciliation; the two advance on their own clocks. Second, the system deliberately computes the cost of a trip twice — once forward, from the estimate captured at intake, and once chronologically, from the odometer and dwell actuals recorded by the driver — and treats the divergence between the two as a first-class reconciliation outcome.

This document specifies the system-wide contract first (Section 2), then the business workflows where the real rules live (Section 3), and finally the endpoint and error catalogues (Sections 4 and 5). Readers implementing the API should treat Section 3 as the authoritative source for behavior; the tables at the end are deliberately thin and must be reconstructed against the narrative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the request is made. If `X-User-Role` is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes four acting roles plus a shared read posture. A `Coordinator` performs intake, eligibility management, scheduling, broker and rate-schedule administration, standing-order management, will-call readiness, and the test-driving operations. A `Broker` operates a transportation-provider network: it creates drivers, manages driver availability, assigns trips, and submits claims. A `Driver` is a field driver who executes legs. An `Auditor` captures encounters and performs reconciliation. Read operations are shared: each GET endpoint independently names the set of roles permitted to call it (see Section 4).

Three of these roles carry an opaque identity. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `Broker` and when `X-User-Role` is `Auditor` — in each case `X-User-ID` is an opaque operator identifier the server does not match against any stored record. The `Driver` role is different: it is entity-backed. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` row, and ownership checks on any leg compare the leg's owning trip's `assigned_driver_id` against `X-User-ID`. A driver who is not the trip's assigned driver may not act on that trip's legs.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of leading items to skip and defaults to 0.

Unless an endpoint's description states otherwise, list results are sorted by `created_at` in ascending order. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` is an integer that begins at its initial value and increments by one on each mutation; it is the basis for optimistic concurrency control described in Section 2.8.

Two entity types are immutable append-only records and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. The first is the **EligibilitySpan**, a coverage record that, once written, is never edited in place (it can be retired only by the voiding operation, which sets its `voided` flag). The second is the **RateSchedule** row, a pricing configuration fixed at creation. For both of these, do not expose `updated_at` or `version` in their representations. All other entities — Member, Broker, Driver, TripRequest, Leg, Assignment, StandingOrder, Claim, and Encounter — carry the full common-field set.

### 2.5. Hierarchical Consistency and Automatic Cascades

Because trips, legs, assignments, drivers, brokers, members, and standing orders are tightly coupled, several operations mutate more than one entity in a single call, and the server performs those secondary mutations automatically without a separate client request. Whenever the server changes a resource as part of such a cascade — releasing an assignment, flipping a driver's availability, cancelling a leg, pausing a standing order — that change is a real mutation: it refreshes the touched resource's `updated_at` and increments its `version` (for entities that carry a version). The specific cascades are described where the triggering workflow lives in Section 3; this subsection establishes only that they are server-driven and that each touched resource is independently versioned.

A trip's two status axes evolve independently. The lifecycle axis is `trip_status`; the billing axis is `billing_status`. A transition on one axis never implicitly drives the other except where Section 3 explicitly states a dependency (for example, a claim may be submitted only after the lifecycle axis reaches `COMPLETED`).

### 2.6. Nested Resource Retrieval and Path Validation

Several read endpoints address a resource through a parent identifier in the path (for example, listing the legs that belong to a trip, or the eligibility spans that belong to a member). When a path contains a resource identifier, the server validates that identifier's existence before attempting any deeper lookup, evaluating identifiers left to right. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any subsequent identifier or body field is considered.

### 2.7. Modality, Level of Service, and County Coverage

Two ordered enumerations recur throughout the domain. **Modality** orders the vehicle types from least to most capable as `AMBULATORY`, then `WHEELCHAIR`, then `STRETCHER`; a higher-ranked modality vehicle can serve any lower-ranked need but not the reverse. **Level of service** orders the Medicaid authorization tiers from least to most as `ROUTINE`, then `URGENT`, then `BARIATRIC`. Wherever the rules below speak of one rank being "at least" another, they mean this ordering: a value satisfies a requirement when its position in the ordering is greater than or equal to the required position. County coverage is exact-match: a broker serves a county only if that county code appears in its `covered_counties` list, and a driver garages in exactly one `base_county`.

### 2.8. Optimistic Concurrency Control on Assignment

Assignment is the one write in this system that is guarded by optimistic concurrency control, because two writers racing to bind a driver to the same trip would otherwise double-book it. The operation that advances a trip from `SCHEDULED` to `ASSIGNED` requires `expected_trip_version` in its body as a non-optional field, carrying the client's last observed `version` of the target `TripRequest`. If `expected_trip_version` does not equal the trip's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has already created an `ACTIVE` assignment for the trip — legitimately advancing its `version` — so that the current writer's view is stale and its assignment would otherwise silently double-book the trip. No other endpoint takes a version field; only the assignment write performs this check.

### 2.9. Monetary and Temporal Precision

All money in this system is expressed in whole integer cents; there are no fractional cents. Where a calculation multiplies miles or minutes by a per-unit rate, the rounding method is **round half up**, and the *point* at which rounding is applied differs between the two cost variants and is specified precisely in Section 3 — the difference is intentional and is the engine of reconciliation variance. Dwell time is measured in whole integer minutes, obtained by taking the floor of the elapsed duration. Dead-head distance is measured in miles. All timestamps the server stamps are ISO 8601 UTC.

The server maintains a logical clock used for all timestamp stamping and for eligibility recomputation. An administrative test-driving capability sets this clock to a supplied instant, and another seeds the symmetric county-to-county dead-head distance matrix; both are described as capabilities in Section 3 and exposed in Section 4.

### 2.10. Validation Ordering

When a single operation is subject to several checks, they are evaluated in a fixed priority order so that the same failing request always produces the same error. The order is: first, authentication of the role header (`ERR_UNAUTHENTICATED`); then role authorization for the operation (`ERR_FORBIDDEN`); then existence of every path identifier, left to right (`ERR_NOT_FOUND`); then existence of every foreign-key identifier supplied in the body (`ERR_FK_NOT_FOUND`); then that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); then ownership constraints binding a driver or broker to the trip they act on (`ERR_NOT_OWNER`); then the member-eligibility gate (`ERR_MEMBER_INELIGIBLE`); then modality and level-of-service authorization at schedule time (`ERR_LOS_NOT_AUTHORIZED`); then provider modality and county matching at assign time (`ERR_MODALITY_MISMATCH`); then will-call leg sequencing (`ERR_LEG_SEQUENCE_VIOLATION`); then the single-active-assignment rule (`ERR_ASSIGNMENT_EXISTS`); then reconciliation completeness (`ERR_RECON_INCOMPLETE`); then candidate-pair availability (`ERR_NO_BROKER_AVAILABLE`); then the optimistic-concurrency version check (`ERR_STALE_VERSION`); then the member-dependency guard on termination (`ERR_DEPENDENCY_EXISTS`); and finally, malformed-or-out-of-domain field values (`ERR_INVALID_REQUEST`). Note in particular that the eligibility gate precedes every fiscal or provider check: a member who is not eligible fails with `ERR_MEMBER_INELIGIBLE` before the system ever considers modality, level of service, or provider availability.

## 3. Business Logic & Workflows

### 3.1. Members, Eligibility Spans, and the Eligibility Posture

A `Coordinator` creates a member by supplying a `medicaid_id` (the state identifier, unique among members), a `full_name`, the member's `mobility_level` (the highest modality the member is approved to require, one of `AMBULATORY`, `WHEELCHAIR`, or `STRETCHER`), and a `home_county` code. A new member begins with `eligibility_status` of `ELIGIBLE`, a `noshow_strike_count` of 0, and `standing_orders_paused` set to false.

Coverage itself lives in append-only **EligibilitySpan** records, not on the member. A coordinator appends a span by providing the `member_id` it covers, the `level_of_service` it authorizes (`ROUTINE`, `URGENT`, or `BARIATRIC`), an inclusive `coverage_start`, and an exclusive `coverage_end`; the span covers the half-open interval that begins at `coverage_start` and ends just before `coverage_end`. A span begins with `voided` false. A coordinator may retroactively void a span, which sets its `voided` flag to true; voided spans never contribute to eligibility. Because spans are immutable coverage records, they carry only `id` and `created_at`.

The `eligibility_status` on a member is a derived posture, not directly set. A coordinator triggers a recompute, which inspects the spans and the current clock. The member becomes `SUSPENDED` from `ELIGIBLE` when no non-voided span has a `coverage_start` at or before the current clock instant and a `coverage_end` strictly after it — that is, when no live coverage exists for "now." Conversely, the member returns to `ELIGIBLE` from `SUSPENDED` when some non-voided span does cover the current clock instant under the same half-open test. `TERMINATED` is a terminal posture reached only by explicit termination, described below; once terminated a member does not return.

The lapse from `ELIGIBLE` to `SUSPENDED` fires a cascade with several arms, all of which run as one server-driven operation. Every `TripRequest` for this member whose `trip_status` is `SCHEDULED` or `ASSIGNED` is moved to `CANCELLED`. For each such cascaded trip, every `OUTBOUND` or `RETURN` leg in `PENDING`, `READY`, or `EN_ROUTE` is moved to `CANCELLED`; the trip's `ACTIVE` assignment, if any, is moved to `RELEASED`, and the driver named by that assignment, if `ON_TRIP`, returns to `AVAILABLE`. The member's `standing_orders_paused` flag is set to true, and every `ACTIVE` standing order for the member is moved to `PAUSED`. The restore direction is deliberately asymmetric: returning to `ELIGIBLE` clears `standing_orders_paused` back to false but does **not** auto-resume paused standing orders — those require an explicit resume.

A coordinator may terminate a member from either `ELIGIBLE` or `SUSPENDED`. Termination is blocked, with `ERR_DEPENDENCY_EXISTS`, if the member has any `TripRequest` whose `trip_status` is `ASSIGNED` or `IN_PROGRESS` — in-flight work must be resolved first. When termination succeeds, every standing order for the member that is `ACTIVE` or `PAUSED` is moved to `CANCELLED`.

### 3.2. Brokers, Drivers, and Rate Schedules

A coordinator registers a **Broker** with a `name`, a `covered_counties` array of county codes the network serves, a `max_modality` naming the highest modality the broker can fulfill, a `free_deadhead_miles` allowance, and a `deadhead_rate_cents_per_mile`. A new broker starts `ACTIVE`. Suspending a broker is itself a cascade: every `TripRequest` whose `assigned_broker_id` is this broker and whose `trip_status` is `ASSIGNED` is reverted to `SCHEDULED`; for each such trip the `ACTIVE` assignment is moved to `RELEASED`, its driver — if `ON_TRIP` — returns to `AVAILABLE`, and the trip's `assigned_broker_id` and `assigned_driver_id` are cleared. Reinstating a suspended broker returns it to `ACTIVE` with no cascade; a `SUSPENDED` broker cannot receive new assignments while suspended.

A `Broker` creates a **Driver** by supplying the `broker_id` of the owning network, the driver's `full_name`, a `vehicle_modality` (the highest modality the vehicle supports), and a `base_county` where the vehicle garages — this base county is the dead-head origin for mileage. A new driver is `AVAILABLE`. A driver's availability moves through three states. The server flips a driver from `AVAILABLE` to `ON_TRIP` when an assignment is created `ACTIVE` for that driver, and back from `ON_TRIP` to `AVAILABLE` when that assignment is released or superseded or when the trip completes, cancels, or no-shows. Separately, a broker may take a driver from `AVAILABLE` to `OFFLINE` and bring it back from `OFFLINE` to `AVAILABLE`.

A coordinator defines pricing as immutable **RateSchedule** rows, one per modality. Each row carries a `modality`, a flat `base_fare_cents` charged per leg of that modality, a `loaded_rate_cents_per_mile` for member-on-board miles, a `dwell_free_minutes` allowance before a will-call dwell surcharge begins, and a `dwell_cents_per_minute` charged for billable dwell minutes beyond the free allowance. Rate rows are immutable configuration and carry only `id` and `created_at`.

### 3.3. Creating and Scheduling a Trip

A coordinator opens a trip by creating a **TripRequest** for a `member_id`, naming the required `modality`, the `requested_level_of_service`, the `appointment_at` instant by which the outbound leg must arrive, and the `scheduled_loaded_miles` — the intake estimate of loaded miles for the outbound leg, which feeds the forward claimed-cost variant. The request may set `is_round_trip` (a return leg is required; defaults to true) and `return_is_will_call` (the return leg is a will-call the member calls when ready; defaults to false). A trip generated from a recurring order also carries the `standing_order_id` that produced it; for an ordinary ad-hoc trip this is null. A new trip begins with `trip_status` of `DRAFT` and `billing_status` of `UNBILLED`, and its computed money fields — `claimed_cost_cents`, `encounter_cost_cents`, and `reconciliation_variance_cents` — all start at 0, as do its `assigned_broker_id` and `assigned_driver_id`, which remain null until assignment.

Scheduling advances a trip from `DRAFT` to `SCHEDULED` and is where eligibility and authorization are first enforced. The member's `eligibility_status` must be `ELIGIBLE`; otherwise the schedule is rejected with `ERR_MEMBER_INELIGIBLE`. The trip's required modality must be within the member's approval — the member's `mobility_level` rank must be at least the trip's `modality` rank — and there must be some non-voided eligibility span that covers `appointment_at` (under the same half-open coverage test used for the posture) whose authorized `level_of_service` rank is at least the trip's `requested_level_of_service` rank. If the modality exceeds the member's mobility level, or no covering span exists at `appointment_at`, or the covering span's level of service is below what the trip requests, the schedule is rejected with `ERR_LOS_NOT_AUTHORIZED`. On success, the system creates the legs: one `OUTBOUND` leg in `PENDING`, and — only if `is_round_trip` is true — one `RETURN` leg in `PENDING` whose `is_will_call` is copied from the trip's `return_is_will_call`.

A coordinator may cancel a trip from `DRAFT`, `SCHEDULED`, or `ASSIGNED`. Cancelling a `DRAFT` trip has no legs to clean up. Cancelling a `SCHEDULED` trip moves all of its non-terminal legs to `CANCELLED`. Cancelling an `ASSIGNED` trip additionally moves the `ACTIVE` assignment to `RELEASED`, returns the `ON_TRIP` driver to `AVAILABLE`, and clears the trip's assigned broker and driver identifiers.

### 3.4. Assignment, Provider Selection, and Dead-Head

Assignment is a `Broker` operation that advances a trip from `SCHEDULED` to `ASSIGNED`. The body must carry `expected_trip_version` for the concurrency check described in Section 2.8, and may optionally carry a `preferred_broker_id` to bias selection toward a particular network. Before anything is bound, the member must still be `ELIGIBLE` (otherwise `ERR_MEMBER_INELIGIBLE`).

The selector looks for a candidate pairing of a broker and one of its drivers that can actually serve the trip. A candidate broker must be `ACTIVE`, must have the member's `home_county` in its `covered_counties`, and must have a `max_modality` rank at least the trip's `modality` rank. A candidate driver must belong to that broker, must be `AVAILABLE`, and must have a `vehicle_modality` rank at least the trip's `modality` rank. If a `preferred_broker_id` was supplied and yields a valid candidate it is used; otherwise the selector falls back across eligible brokers. If no candidate broker-and-driver pair satisfies these conditions at all, the assignment is rejected with `ERR_NO_BROKER_AVAILABLE`. If a specific selected or preferred broker or driver is examined but fails the modality or county test — its modality rank is below the trip's, or its broker does not cover the member's home county — that specific mismatch is reported as `ERR_MODALITY_MISMATCH`. A trip may have at most one `ACTIVE` assignment; attempting to create a second `ACTIVE` assignment without the prior one having been superseded is rejected with `ERR_ASSIGNMENT_EXISTS`.

When a candidate is found, the system creates an **Assignment** in `ACTIVE` status recording the chosen `trip_id`, `broker_id`, and `driver_id`. It computes and stores the assignment's `deadhead_miles`. It sets the trip's `assigned_broker_id` and `assigned_driver_id`, flips the chosen driver from `AVAILABLE` to `ON_TRIP`, and increments the trip's `version` by one — which is precisely why a second writer holding a stale `expected_trip_version` is rejected. An assignment's `status` is one of `ACTIVE`, `SUPERSEDED`, or `RELEASED`, and only one assignment per trip is `ACTIVE` at a time.

Dead-head is the empty distance a driver covers from base to the member before carrying anyone. The raw dead-head is the county-to-county distance between the driver's `base_county` and the member's `home_county`, read from the symmetric distance matrix (a same-county pair is zero miles). This raw value is stored on the assignment as `deadhead_miles`. Billable dead-head accrues only above the broker's free allowance, and the boundary is strict: if the raw dead-head is strictly greater than the broker's `free_deadhead_miles`, the billable portion is the raw dead-head minus that allowance; if the raw dead-head is less than or equal to the allowance, the billable portion is zero. The dead-head charge in cents is that billable portion multiplied by the broker's `deadhead_rate_cents_per_mile`, rounded half up after the multiplication.

### 3.5. Executing Legs and the Will-Call Return Cycle

A **Leg** belongs to a trip via its `trip_id` and has a `direction` of `OUTBOUND` or `RETURN`. Its `is_will_call` flag is meaningful only on a `RETURN` leg. Each leg carries timestamps the driver stamps as it progresses — `arrived_at`, `picked_up_at`, `dropped_off_at` — plus `ready_called_at` for will-call returns, an `odometer_loaded_miles` reading recorded at drop-off (0 until then), and a computed `dwell_minutes` that stays 0 except on a will-call return. A leg's `leg_status` moves through `PENDING`, `EN_ROUTE`, `ARRIVED`, `PICKED_UP`, and `DROPPED_OFF`, with `NO_SHOW` and `CANCELLED` as terminal outcomes; a will-call return additionally cycles between `PENDING` and `READY`. Only the trip's assigned driver may act on its legs; any other driver attempting a leg action is rejected with `ERR_NOT_OWNER`.

For an ordinary leg, the driver departs directly from `PENDING` to `EN_ROUTE`. When the departing leg is the `OUTBOUND` leg of an `ASSIGNED` trip, that first departure also promotes the trip from `ASSIGNED` to `IN_PROGRESS`. From `EN_ROUTE` the driver arrives, moving the leg to `ARRIVED` and stamping `arrived_at` to the current clock. From `ARRIVED` the driver picks up the member, moving the leg to `PICKED_UP` and stamping `picked_up_at`. From `PICKED_UP` the driver drops off, which requires an `odometer_loaded_miles` value of at least zero supplied in the body; this records the odometer reading, stamps `dropped_off_at`, and moves the leg to `DROPPED_OFF`. When the last non-cancelled leg of a trip reaches `DROPPED_OFF`, the server promotes the trip from `IN_PROGRESS` to `COMPLETED`, releases the `ACTIVE` assignment, and returns the driver from `ON_TRIP` to `AVAILABLE`.

The will-call return is the cyclic part. A `RETURN` leg whose `is_will_call` is true sits in `PENDING` until the member calls ready. A coordinator marks it `READY`, which stamps `ready_called_at` to the current clock — but only if the parent trip is `IN_PROGRESS` and the `OUTBOUND` leg is already `DROPPED_OFF`; a will-call return readied or departed before its outbound leg has been dropped off, or while the trip is not `IN_PROGRESS`, is rejected with `ERR_LEG_SEQUENCE_VIOLATION`. If the member turns out not to be ready, a coordinator retracts the readiness, moving the leg from `READY` back to `PENDING` and clearing `ready_called_at` to null; this is the cycle. From `READY`, the assigned driver departs the will-call return to `EN_ROUTE` only once `ready_called_at` is set, after which it proceeds through arrive, pickup, and dropoff like any other leg.

A driver may mark a member no-show only on the `OUTBOUND` leg and only while that leg is `ARRIVED` — the driver arrived but the member never boarded. This moves the outbound leg from `ARRIVED` to `NO_SHOW` and promotes the trip from `IN_PROGRESS` to `NO_SHOW`. Any `RETURN` leg still in `PENDING` or `READY` is moved to `CANCELLED`, the `ACTIVE` assignment is released, and the driver returns to `AVAILABLE`. The member's `noshow_strike_count` is incremented by one. When that incremented count reaches the suspension threshold of three or more strikes, the member is automatically moved to `SUSPENDED` and the full eligibility-lapse cascade of Section 3.1 fires exactly as if a recompute had found no coverage.

### 3.6. Standing Orders and Recurring Generation

Recurring riders — the dialysis member who travels the same three weekdays — are modeled as a **StandingOrder**. A coordinator creates one for a `member_id` with the `modality` and `level_of_service` to stamp on every generated trip, a `weekday_mask` bitmask selecting the weekdays to generate on (bit 0 is Monday through bit 6 is Sunday), an `appointment_time_utc` time of day in `HH:MM:SS` applied to each generated date, and a `scheduled_loaded_miles` estimate copied onto each generated trip. A new standing order is `ACTIVE` with a `horizon_through` of null. Its `status` is one of `ACTIVE`, `PAUSED`, or `CANCELLED`; `PAUSED` suppresses generation.

Generation rolls a horizon forward over a requested half-open window, from an inclusive `generate_from` date through an exclusive `generate_through` date, and is idempotent. The effective start is the later of `generate_from` and the order's current `horizon_through` (treating a null horizon as `generate_from`), so dates already covered by a prior run are skipped rather than duplicated. Walking the dates in ascending order from that effective start up to but not including `generate_through`, the system creates one `DRAFT` trip for each date whose weekday bit is set in `weekday_mask` — but only while the order's `status` is `ACTIVE` and the owning member is not paused. Each generated trip is a `TripRequest` carrying the member, the order's modality and level of service, an `appointment_at` formed by combining the date with `appointment_time_utc`, the order's `scheduled_loaded_miles`, and the `standing_order_id` linking it back to the order; it begins in `DRAFT`. After the run, the order's `horizon_through` is advanced to `generate_through`. A coordinator may pause a standing order (`ACTIVE` to `PAUSED`) and resume it (`PAUSED` to `ACTIVE`); recall that an eligibility lapse pauses active orders automatically, but a return to eligibility does not resume them.

### 3.7. The Forward Claim: Pricing from the Estimate

Once a trip's lifecycle axis reaches `COMPLETED`, the billing axis comes into play. The `Broker` that is the trip's `assigned_broker_id` submits a **Claim** by supplying the `trip_id`. The broker submitting the claim must be the trip's assigned broker; another broker is rejected with `ERR_NOT_OWNER`. The trip must be `COMPLETED` on its lifecycle axis, and there must be no existing claim for the trip — a duplicate is rejected with `ERR_RECON_INCOMPLETE`. Submission advances `billing_status` from `UNBILLED` to `CLAIMED`, creates the claim in `SUBMITTED` status recording its `trip_id` and the `broker_id` copied from the trip's active assignment, and computes the trip's `claimed_cost_cents`. The claim's `billed_cents` is set equal to that computed `claimed_cost_cents`. A claim's `status` is one of `SUBMITTED`, `RECONCILED`, or `DENIED`.

The forward claimed cost is priced from the intake estimate, not from anything the driver recorded. Select the rate row whose `modality` equals the trip's `modality` (there is exactly one such row). Let the leg multiplier be 2 when the trip `is_round_trip` and 1 otherwise — a round trip forecasts a doubled return. The loaded component is the rate's `loaded_rate_cents_per_mile` multiplied by the trip's `scheduled_loaded_miles`; the base component is the rate's `base_fare_cents` multiplied by the leg multiplier. The claimed cost is the sum of the base component plus the loaded component itself multiplied by the leg multiplier, and the whole sum is rounded half up exactly once, after the summation. Will-call dwell is not forecastable at claim time and is therefore excluded entirely from the forward claim; odometer actuals are likewise ignored.

### 3.8. The Encounter: Pricing from Actuals, Chronologically

After a claim exists, an `Auditor` captures an **Encounter** for the same trip by supplying the `trip_id`. The trip must still be `COMPLETED` and there must be no existing encounter for it; a duplicate is rejected with `ERR_RECON_INCOMPLETE`. Capture advances `billing_status` from `CLAIMED` to `ENCOUNTERED`, creates the encounter in `OPEN` status recording its `trip_id`, and computes the trip's `encounter_cost_cents`. The encounter's `captured_cents` is set equal to that computed `encounter_cost_cents`. An encounter's `status` is either `OPEN` or `RECONCILED`.

The encounter cost replays the trip's legs in the order they actually finished and accumulates real cost per leg, and — this is the deliberate divergence from the forward claim — it rounds each leg to whole cents *before* summing rather than rounding once at the end. Select the rate row whose `modality` equals the trip's `modality`. Consider only legs in `DROPPED_OFF` status; `CANCELLED` and `NO_SHOW` legs are excluded. Order those legs by `dropped_off_at` ascending, breaking ties by `created_at` ascending. For each leg in that order, compute the leg's cost as the rate's `base_fare_cents`, plus the rate's `loaded_rate_cents_per_mile` multiplied by the leg's `odometer_loaded_miles`, plus the rate's `dwell_cents_per_minute` multiplied by the leg's `dwell_minutes`, and round that per-leg amount half up to whole cents. The encounter cost is the sum of those rounded per-leg amounts. Dwell is included only for will-call returns, where it was computed at pickup; on every other leg `dwell_minutes` is zero.

The dwell figure itself is computed at the moment a will-call return is picked up. Take the elapsed time between `ready_called_at` and `picked_up_at` and floor it to whole minutes — call this the raw dwell. Compare it to the rate row's `dwell_free_minutes`, with a strict boundary: if the raw dwell is strictly greater than the free allowance, the leg's `dwell_minutes` is the raw dwell minus the free allowance; if the raw dwell is less than or equal to the free allowance (including exactly equal), `dwell_minutes` is zero. Non-will-call legs never accrue dwell.

### 3.9. Reconciliation and Dispute

Reconciliation is an `Auditor` operation that closes the loop between the forward claim and the captured encounter, advancing the billing axis from `ENCOUNTERED`. It requires that the trip have both a `SUBMITTED` claim and an `OPEN` encounter; if either is missing, the reconcile is rejected with `ERR_RECON_INCOMPLETE`. The variance is computed as an exact subtraction in cents: the trip's `reconciliation_variance_cents` is its `encounter_cost_cents` minus its `claimed_cost_cents`. A positive variance means the encounter exceeded the claim — the broker under-billed.

The routing depends on the magnitude of that variance against a tolerance of 500 cents. If the absolute value of the variance is at most 500 cents — that is, not strictly greater than 500 — the trip moves from `ENCOUNTERED` to `RECONCILED`, its claim moves to `RECONCILED`, and its encounter moves to `RECONCILED`. If the absolute value of the variance is strictly greater than 500 cents, the trip moves from `ENCOUNTERED` to `DISPUTED` instead: the variance is still recorded on the trip, but the claim stays `SUBMITTED` and the encounter stays `OPEN`, pending manual review. From `DISPUTED`, an auditor may override the dispute, which moves the trip to `RECONCILED` and moves both the claim and the encounter to `RECONCILED`, accepting the variance.

### 3.10. Test-Driving the Clock and Geography

Two coordinator-only capabilities exist purely to make the system deterministic under test. A clock-setting capability sets the server's current UTC clock to a supplied `now_utc` instant; all subsequent timestamp stamping and every eligibility recompute read from this clock. A geography-seeding capability records a symmetric dead-head distance between two counties, taking `county_a`, `county_b`, and a `miles` value, and storing it (together with its mirror entry) in the county distance matrix that dead-head billing consults. Same-county distance is always zero regardless of seeding.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify, transition, or act upon an existing resource — including the lifecycle and billing transitions, will-call actions, and the test-driving capabilities — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members` | Create a Member (begins ELIGIBLE) | Coordinator |
| GET | `/members/{id}` | Get a Member | Coordinator, Broker, Auditor, Driver |
| POST | `/members/{id}/eligibility/recompute` | Recompute eligibility posture from spans and clock | Coordinator |
| POST | `/members/{id}/terminate` | Terminate a Member | Coordinator |
| GET | `/members/{id}/eligibility-spans` | List a Member's EligibilitySpans | Coordinator, Auditor |
| GET | `/members/{id}/trips` | List a Member's TripRequests | Coordinator, Broker, Auditor |
| GET | `/members/{id}/standing-orders` | List a Member's StandingOrders | Coordinator |
| POST | `/eligibility-spans` | Append an EligibilitySpan | Coordinator |
| POST | `/eligibility-spans/{id}/void` | Void an EligibilitySpan | Coordinator |
| POST | `/brokers` | Create a Broker (begins ACTIVE) | Coordinator |
| GET | `/brokers/{id}` | Get a Broker | Coordinator, Broker, Auditor |
| POST | `/brokers/{id}/suspend` | Suspend a Broker | Coordinator |
| POST | `/brokers/{id}/reinstate` | Reinstate a Broker | Coordinator |
| GET | `/brokers/{id}/drivers` | List a Broker's Drivers | Coordinator, Broker, Auditor |
| POST | `/drivers` | Create a Driver (begins AVAILABLE) | Broker |
| GET | `/drivers/{id}` | Get a Driver | Coordinator, Broker, Auditor, Driver |
| POST | `/drivers/{id}/offline` | Take a Driver OFFLINE | Broker |
| POST | `/drivers/{id}/online` | Bring a Driver AVAILABLE | Broker |
| POST | `/rate-schedules` | Create a RateSchedule row (immutable) | Coordinator |
| GET | `/rate-schedules/{id}` | Get a RateSchedule row | Coordinator, Broker, Auditor |
| POST | `/trips` | Create a TripRequest (DRAFT / UNBILLED) | Coordinator |
| GET | `/trips/{id}` | Get a TripRequest | Coordinator, Broker, Auditor, Driver |
| GET | `/trips` | List TripRequests, optional FK filters | Coordinator, Broker, Auditor |
| POST | `/trips/{id}/schedule` | Schedule a DRAFT trip; create legs | Coordinator |
| POST | `/trips/{id}/assign` | Assign broker+driver (OCC on trip version) | Broker |
| POST | `/trips/{id}/cancel` | Cancel a DRAFT/SCHEDULED/ASSIGNED trip | Coordinator |
| POST | `/trips/{id}/reconcile` | Reconcile claim vs encounter | Auditor |
| POST | `/trips/{id}/reconcile/override` | Override a DISPUTED trip to RECONCILED | Auditor |
| GET | `/trips/{id}/legs` | List a trip's Legs (OUTBOUND first, then RETURN, then created_at ASC) | Coordinator, Broker, Auditor, Driver |
| GET | `/trips/{id}/assignments` | List a trip's Assignments | Coordinator, Broker, Auditor |
| GET | `/assignments/{id}` | Get an Assignment | Coordinator, Broker, Auditor |
| GET | `/assignments` | List Assignments, optional FK filters | Coordinator, Broker, Auditor |
| GET | `/trips/{id}/claims` | List a trip's Claims | Coordinator, Broker, Auditor |
| GET | `/claims` | List Claims, optional FK filters | Coordinator, Broker, Auditor |
| GET | `/trips/{id}/encounters` | List a trip's Encounters | Coordinator, Auditor |
| GET | `/legs/{id}` | Get a Leg | Coordinator, Broker, Auditor, Driver |
| POST | `/legs/{id}/ready` | Member calls ready on a will-call RETURN leg | Coordinator |
| POST | `/legs/{id}/cancel-ready` | Retract a will-call ready | Coordinator |
| POST | `/legs/{id}/depart` | Driver departs toward pickup | Driver |
| POST | `/legs/{id}/arrive` | Driver arrives at pickup | Driver |
| POST | `/legs/{id}/pickup` | Member boards; will-call dwell computed | Driver |
| POST | `/legs/{id}/dropoff` | Member dropped off; records odometer; may complete trip | Driver |
| POST | `/legs/{id}/no-show` | Driver marks member no-show | Driver |
| POST | `/standing-orders` | Create a StandingOrder (ACTIVE) | Coordinator |
| GET | `/standing-orders/{id}` | Get a StandingOrder | Coordinator |
| POST | `/standing-orders/{id}/generate` | Roll the horizon forward, generating DRAFT trips | Coordinator |
| POST | `/standing-orders/{id}/pause` | Pause generation | Coordinator |
| POST | `/standing-orders/{id}/resume` | Resume generation | Coordinator |
| POST | `/claims` | Broker submits a Claim for a COMPLETED trip | Broker |
| GET | `/claims/{id}` | Get a Claim | Coordinator, Broker, Auditor |
| POST | `/encounters` | Auditor captures an Encounter for a CLAIMED trip | Auditor |
| GET | `/encounters/{id}` | Get an Encounter | Coordinator, Auditor |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | Coordinator |
| POST | `/_geo/county_distance` | Seed a symmetric county dead-head distance (test-driving) | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_MEMBER_INELIGIBLE` | 409 |
| `ERR_LOS_NOT_AUTHORIZED` | 409 |
| `ERR_MODALITY_MISMATCH` | 409 |
| `ERR_NO_BROKER_AVAILABLE` | 409 |
| `ERR_ASSIGNMENT_EXISTS` | 409 |
| `ERR_LEG_SEQUENCE_VIOLATION` | 409 |
| `ERR_RECON_INCOMPLETE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DEPENDENCY_EXISTS` | 409 |
