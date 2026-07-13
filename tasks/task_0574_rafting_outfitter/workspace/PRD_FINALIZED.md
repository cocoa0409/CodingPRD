# Rafting Outfitter API — Product Requirements Document

## 1. Introduction

Whitewater rafting is a business of perishable inventory and unforgiving conditions. A river run departs at a fixed instant, seats a strictly limited number of paddlers, must be staffed by enough certified guides to keep the ratio of guests to guides safe, and can be scrubbed at short notice when the river runs too high or too low. This document specifies the Rafting Outfitter API, a back-office system that coordinates the full lifecycle of a river trip: scheduling the run, staffing it with guides, taking group and private bookings, collecting waivers and fitting safety gear, moving passengers on shuttles between the put-in and take-out, reading river flow and holding or cancelling trips for weather, and finally settling every booking and distributing the guides' gratuity pool.

The system serves four cooperating operators. An outfitter manager owns the trip catalogue and all physical inventory — trips, guides, gear, and shuttle vehicles. A reservationist runs the front desk, taking bookings, collecting deposits, checking guests in, fitting gear, and settling accounts. A safety officer records river-flow readings and holds the authority to cancel a trip outright. Guests interact minimally, signing their own liability waiver. The rules below trade heavily on the interplay between these actors: a booking cannot be confirmed unless the trip is open and has capacity; a check-in cannot proceed unless every paddler has signed a waiver and been fitted with a personal flotation device; and a single unsafe flow reading can cascade a full trip into cancellation, refunding deposits and releasing every guide and every piece of gear in one atomic sweep.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. All resource collections are mounted at the root path; there is no nesting of one resource under another in the URL structure.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_AUTH`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `OutfitterManager`, `Reservationist`, `SafetyOfficer`, and `Guest`.

- When `X-User-Role` is `OutfitterManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `OutfitterManager` owns trips, guides, guide assignments, gear inventory, shuttle vehicles and runs, and trip completion.
- When `X-User-Role` is `Reservationist`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Reservationist` owns bookings, guests, payments, gear assignment, check-in, and settlement.
- When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `SafetyOfficer` records river-condition readings and cancels trips for safety.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest` entity. Ownership checks on a waiver compare the waiver's `guest_id` foreign key to `X-User-ID`: a guest may sign only a waiver whose `guest_id` equals their own `X-User-ID`, and an attempt to sign someone else's waiver is rejected with `ERR_NOT_WAIVER_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, serving as identity only. Most resources also carry three system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the resource; and `version`, an integer that starts at 1 and increments by one on every mutation. These common fields are present on `RiverTrip`, `Guide`, `GuideAssignment`, `Reservation`, `Guest`, `Waiver`, `GearItem`, `GearAssignment`, `ShuttleVehicle`, and `ShuttleRun`.

The one exception is the `RiverConditionReading`, which is an append-only event record. A condition reading carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because a reading is never modified after it is written.

Whenever a computed or derived field on a resource changes — for example `committed_guests`, `assigned_guide_count`, `deposits_held_cents`, or `booking_mode` on a `RiverTrip` — that change is a mutation of the resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Monetary Values, Counts, and Rounding

All money is expressed as an integer number of cents; there are no fractional-cent representations. Where a calculation multiplies a rate by a fractional discount, the base term is rounded to a whole number of cents using the round-half-up method before any further whole-cent amounts (such as a photo fee or gratuity) are added. Discount fractions themselves are exact decimal values and are never rounded. Guide-gratuity shares are computed as whole cents using floor division, with any leftover cents distributed one at a time as described in §3. Guest counts, guide counts, and gear counts are whole integers.

### 2.6. Validation Order and Precedence

When more than one rule could reject a request, the checks are applied in a fixed order of precedence, and the first failing check determines the returned error. The order is:

1. **Authentication.** Both `X-User-ID` and `X-User-Role` must be present and well-formed, otherwise `ERR_MISSING_AUTH` (HTTP 401).
2. **Authorization.** The declared role must be permitted for the operation, otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence.** Every identifier referenced in the path or in a foreign-key body field must resolve to an existing resource, otherwise the corresponding not-found error (HTTP 404), described in §2.7.
4. **State.** The target resource must be in a state that admits the requested transition, otherwise the corresponding state-conflict error (HTTP 409) — for example `ERR_TRIP_NOT_BOOKABLE`, `ERR_INVALID_TRIP_STATE`, `ERR_RESERVATION_CANCELLED`, `ERR_NOT_CHECKED_IN`, `ERR_INVALID_RESERVATION_STATE`, `ERR_GEAR_UNAVAILABLE`, `ERR_INVALID_GEAR_STATE`, `ERR_WAIVER_NOT_PENDING`, `ERR_GUIDE_IN_USE`, `ERR_UNRESOLVED_RESERVATIONS`, or `ERR_NO_GUIDE_ASSIGNED`.
5. **Safety (age, guardian, weight).** Age, guardian, and gear-fit safety rules, yielding `ERR_GUEST_UNDER_MIN_AGE`, `ERR_GUARDIAN_REQUIRED`, or `ERR_WEIGHT_OUT_OF_RANGE` (HTTP 422).
6. **Referential compatibility.** Guide certification class, waiver-signed, and gear-assigned prerequisites, yielding `ERR_GUIDE_CLASS_INSUFFICIENT`, `ERR_WAIVER_NOT_SIGNED`, or `ERR_GEAR_NOT_ASSIGNED` (HTTP 409).
7. **Business constraints.** Capacity, guide ratio, uniqueness, private buyout, and temporal-overlap constraints, yielding `ERR_CAPACITY_EXCEEDED`, `ERR_GUIDE_RATIO_UNMET`, `ERR_PRIVATE_CONFLICT`, `ERR_GUIDE_DOUBLE_BOOKED`, `ERR_SHUTTLE_BUFFER_CONFLICT`, or `ERR_DUPLICATE_GEAR_TYPE` (HTTP 409).
8. **Fiscal sufficiency.** Deposit adequacy, yielding `ERR_DEPOSIT_TOO_LOW` (HTTP 402).
9. **Optimistic concurrency.** The trip-version check on booking creation, yielding `ERR_STALE_TRIP_VERSION` (HTTP 412), described in §2.9.

Malformed request bodies — a missing required field, a value of the wrong type, or an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A time-window body that is internally inconsistent (a trip whose scheduled take-out is not strictly after its launch, or a shuttle run whose arrival is not strictly after its departure) is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400).

### 2.7. Reference Resolution and Existence Checks

Because entities reference one another by foreign keys carried in request bodies and by identifiers embedded in URL paths, existence is validated left to right: path identifiers are resolved before body foreign keys, and body foreign keys are resolved in the order they appear. The first identifier that fails to resolve determines the returned error. Each entity type has its own not-found error: `ERR_TRIP_NOT_FOUND`, `ERR_GUIDE_NOT_FOUND`, `ERR_GUIDE_ASSIGNMENT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_GEAR_NOT_FOUND`, `ERR_GEAR_ASSIGNMENT_NOT_FOUND`, `ERR_SHUTTLE_VEHICLE_NOT_FOUND`, and `ERR_SHUTTLE_RUN_NOT_FOUND`. All are HTTP 404.

### 2.8. State Reconciliation and Cascading Effects

Many operations mutate more than one resource. When a booking's fulfillment advances, the parent trip's `committed_guests` is recomputed and the trip's own posture may change; when a guide assignment is released, the parent trip's `assigned_guide_count` is decremented. These secondary mutations are performed automatically by the server, without a separate client request against the affected resource, and each such secondary mutation independently refreshes that resource's `updated_at` and increments its `version`.

Two named cascades govern the largest reconciliations. The first, triggered by trip cancellation, unwinds an entire trip: every dependent reservation, guest, waiver, guide assignment, gear assignment, and shuttle run is resolved and every held deposit is refunded. The second, triggered by reservation cancellation or guest removal, unwinds a booking or a single guest: gear is released back to inventory, waivers are voided, capacity is returned to the trip, and any paid deposit is refunded. Both cascades are detailed in §3.9. Throughout, the derived aggregates on the trip (`committed_guests`, `assigned_guide_count`, `deposits_held_cents`, and `booking_mode`) are recomputed to remain consistent with the surviving children.

### 2.9. Optimistic Concurrency Control on the Trip Version

Creating a reservation is the one write in the system guarded by optimistic concurrency control, because a booking attaches itself to a trip and consumes part of that trip's finite capacity. A reservation-creation request must carry `expected_trip_version`, a non-optional field holding the `version` of the target `RiverTrip` as the client last observed it. If `expected_trip_version` does not equal the trip's current `version`, the create is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412): the client's view of the trip's booking set is stale — another writer may already have consumed the capacity the client intended to claim — so the booking is refused rather than allowed to overwrite an unobserved state. On success, the booking increments the `RiverTrip.version` by one, so that two strictly sequential creates carrying the same `expected_trip_version` behave as expected: the first advances the version and succeeds, and the second, still carrying the now-behind value, is rejected as stale. No other endpoint accepts or requires a version field; reservation creation is the sole optimistic-concurrency write.

### 2.10. The Server Logical Clock

All temporal comparisons — guide schedule overlap, shuttle turnaround buffers — are evaluated against the server's logical clock rather than wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it holds this value and never falls back to wall-clock time. An outfitter-manager-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant.

## 3. Business Logic & Workflows

### 3.1. Trips, Guides, and Guide Assignments

The `OutfitterManager` builds the operating catalogue. A **RiverTrip** is created with a `river_name`, a `difficulty_class` (one of `CLASS_I`, `CLASS_II`, `CLASS_III`, `CLASS_IV`, or `CLASS_V`), a launch instant `trip_date` and a scheduled take-out instant `end_time` (the take-out must be strictly after the launch), a `put_in_location` and a `take_out_location`, a `max_capacity` of at least one guest, a `guide_ratio_max` of at least one (the largest number of guests a single guide may cover), a `base_rate_cents` per-guest fare of zero or more, an optional `min_age` defaulting to 0, and the three flow bounds `safe_flow_min`, `safe_flow_max`, and `marginal_flow_max` that define this run's safety bands. A new trip begins in status `SCHEDULED` with `booking_mode` `GROUP`, and its computed aggregates `committed_guests`, `assigned_guide_count`, and `deposits_held_cents` all start at zero. The `booking_mode` becomes `PRIVATE` only once a private reservation is confirmed against the trip, and is `GROUP` otherwise.

A **Guide** is created with a `full_name` and a `max_class` (the highest whitewater class the guide is certified to lead, drawn from the same `CLASS_I` through `CLASS_V` scale). A guide starts with employment `status` `ACTIVE`. The manager may deactivate a guide, moving `status` from `ACTIVE` to `INACTIVE`, but only when the guide holds no `ASSIGNED` guide assignment on any non-terminal trip; attempting to deactivate a guide still committed to live work is rejected with `ERR_GUIDE_IN_USE`.

Guides are placed on trips through a **GuideAssignment**, created by the manager with a `trip_id`, a `guide_id`, and a `role` (one of `LEAD`, `SAFETY`, or `SWEEP`). A new assignment begins in `status` `ASSIGNED` and its two gratuity fields, `provisional_gratuity_share_cents` and `final_gratuity_share_cents`, both begin at zero. Creating the assignment recomputes the trip's `assigned_guide_count` upward by one. Two prerequisites guard the assignment. First, the guide must be certified for the run: the guide's `max_class` must be at least the trip's `difficulty_class` on the `CLASS_I`-through-`CLASS_V` ordering, otherwise `ERR_GUIDE_CLASS_INSUFFICIENT`. Second, the guide must be free during the run: if the guide is already `ASSIGNED` to another trip whose half-open interval from that trip's `trip_date` up to but not including its `end_time` strictly overlaps this trip's half-open interval, the assignment is rejected with `ERR_GUIDE_DOUBLE_BOOKED`; exact adjacency, where the next trip's `trip_date` equals the previous trip's `end_time`, is permitted. Releasing a guide assignment moves its `status` from `ASSIGNED` to `RELEASED` and recomputes the trip's `assigned_guide_count` downward by one.

A `SCHEDULED` trip becomes bookable when the manager opens it, transitioning its `status` from `SCHEDULED` to `OPEN`. Opening requires that the trip already have at least one guide assigned — its `assigned_guide_count` must be one or more — otherwise the open is rejected with `ERR_NO_GUIDE_ASSIGNED`. Once `OPEN`, reservations against the trip may be confirmed.

### 3.2. Booking: Reservations, Capacity, and Group Discounts

A `Reservationist` books a party through a **Reservation** created against a trip. The create payload carries the `trip_id`, a `booking_type` (`GROUP` or `PRIVATE`), a `party_size` of at least one, an optional `photo_addon` flag defaulting to false, a `deposit_cents` amount tendered at booking, and the `expected_trip_version` required for the concurrency check in §2.9. A new reservation begins with `payment_status` `UNPAID` and `fulfillment_status` `PENDING`, its `checked_in_guest_count` starts at zero, and its provisional charge `estimated_total_cents` is computed immediately. A reservation carries two independent status dimensions: `payment_status` (one of `UNPAID`, `DEPOSIT_PAID`, `SETTLED`, `REFUNDED`) tracks money, and `fulfillment_status` (one of `PENDING`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`) tracks the guest journey; the two move independently.

The estimated charge is built from the booked party. First a group-discount fraction is chosen from the booked `party_size`: a party of at least 8 guests earns a fraction of 0.15, otherwise a party of at least 4 guests earns 0.10, and a smaller party earns 0.00. The base term is the `base_rate_cents` multiplied by the `party_size` multiplied by one minus that discount fraction, rounded half up to a whole number of cents. To the rounded base is added a photo fee of 4000 cents when `photo_addon` is true, and nothing when it is false. The sum is the `estimated_total_cents`.

Confirming a reservation advances its `fulfillment_status` from `PENDING` to `CONFIRMED` and commits its guests against trip capacity. Three conditions must hold. The parent trip must be bookable — its `status` must be `OPEN` or `FULL` — otherwise `ERR_TRIP_NOT_BOOKABLE`. The trip must have room: the trip's current `committed_guests` plus this reservation's `party_size` must not exceed `max_capacity`, otherwise `ERR_CAPACITY_EXCEEDED`. And if the `booking_type` is `PRIVATE`, no other reservation on the trip may already be `CONFIRMED` or `CHECKED_IN`, otherwise `ERR_PRIVATE_CONFLICT`; the same conflict error guards a `GROUP` confirmation attempted while a `PRIVATE` booking already holds the trip. On confirmation, the trip's `committed_guests` is recomputed upward by the `party_size`. The trip's `committed_guests` is defined as the sum of `party_size` over all reservations whose `fulfillment_status` is `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`. If that recomputation brings `committed_guests` up to `max_capacity`, or if the confirming reservation is `PRIVATE`, the trip transitions from `OPEN` to `FULL`; a `PRIVATE` confirmation additionally sets the trip's `booking_mode` to `PRIVATE`. While a trip is `FULL`, no further confirmation may proceed.

When a `CONFIRMED` or `CHECKED_IN` reservation later cancels and frees capacity, the trip returns from `FULL` to `OPEN` provided two conditions hold: after the cancellation the trip's `committed_guests` is strictly below `max_capacity`, and the trip's `booking_mode` is `GROUP`. A trip bought out privately does not reopen on partial capacity change; it reopens only when the private reservation itself cancels.

### 3.3. Adding Guests, Waivers, and Age Rules

Each paddler on a booking is recorded as a **Guest**, added by the reservationist with a `reservation_id`, a `full_name`, an `age` in whole years at trip date, and a `weight_lbs` (a positive weight used later for flotation-device sizing). A new guest starts in `status` `BOOKED`. At the moment a guest is added, the trip reached through the reservation imposes its minimum-age rule: the guest's `age` must be at least the trip's `min_age`, otherwise the guest is rejected with `ERR_GUEST_UNDER_MIN_AGE`.

Adding a guest automatically creates a **Waiver** for that guest, linked by `guest_id` and starting in `status` `PENDING`. At creation the waiver's `guardian_required` flag is derived from the guest's age: it is true when the guest is younger than 18 years old at creation, and false otherwise. The waiver also carries a `guardian_name`, which defaults to null.

A guest signs their own waiver, advancing its `status` from `PENDING` to `SIGNED`. The signer must be the waiver's owner — the acting `X-User-ID` must equal the waiver's `guest_id`, otherwise `ERR_NOT_WAIVER_OWNER`. If the waiver's `guardian_required` flag is true, a `guardian_name` must be supplied in the signing request, otherwise `ERR_GUARDIAN_REQUIRED`. A waiver that is not `PENDING` cannot be signed; such an attempt is rejected with `ERR_WAIVER_NOT_PENDING`. A waiver reaches `VOID` only through the system, when its guest is removed or its trip or reservation is cancelled.

### 3.4. Gear Inventory and Assignment

The manager stocks physical equipment as **GearItem** records, each created with a `gear_type` (one of `RAFT`, `WETSUIT`, or `PFD`), a human `size_label`, and, for weight-sensitive items, a `min_weight_lbs` (defaulting to 0) and `max_weight_lbs` (defaulting to 100000) marking the inclusive wearer-weight range the item safely fits. A gear item starts in `status` `AVAILABLE`. The manager may retire an item, moving its `status` from `AVAILABLE` to `OUT_OF_SERVICE`, but only while it is currently `AVAILABLE`; retiring an item that is not available is rejected with `ERR_GEAR_UNAVAILABLE`.

A reservationist fits a guest by creating a **GearAssignment** with a `gear_item_id`, a `guest_id`, and a `trip_id`. Creating the assignment requires the gear item to be `AVAILABLE`, otherwise `ERR_GEAR_UNAVAILABLE`; on success the assignment begins in `status` `ASSIGNED` and the linked gear item moves from `AVAILABLE` to `ASSIGNED`. Two constraints apply at fitting time. For weight-sensitive gear (a `PFD` or `WETSUIT`), the guest's `weight_lbs` must lie within the item's inclusive range from `min_weight_lbs` to `max_weight_lbs`, otherwise `ERR_WEIGHT_OUT_OF_RANGE`. A guest may not hold two assigned items of the same kind: if the guest already holds an `ASSIGNED` gear assignment of the same `gear_type`, the new assignment is rejected with `ERR_DUPLICATE_GEAR_TYPE`.

Releasing a gear assignment moves its `status` from `ASSIGNED` to `RELEASED` and returns the linked gear item's `status` to `AVAILABLE`. Because assignment moves an item from `AVAILABLE` to `ASSIGNED` and release moves it back, the serviceable inventory of any given `gear_type` — the count of items that are `AVAILABLE` plus the count that are `ASSIGNED`, excluding those `OUT_OF_SERVICE` — is invariant across an assign followed by its compensating release.

### 3.5. Check-In: Guide Ratio, Waivers, and Flotation

Checking a reservation in advances its `fulfillment_status` from `CONFIRMED` to `CHECKED_IN` and is the safety gate of the whole workflow. The parent trip must still be bookable — `status` `OPEN` or `FULL` — otherwise `ERR_TRIP_NOT_BOOKABLE`. Three prerequisites then guard the check-in, each scoped to the reservation's non-removed guests. The trip must be adequately staffed: the trip's `assigned_guide_count` must be at least the required guide count for the trip, otherwise `ERR_GUIDE_RATIO_UNMET`. The required guide count is the trip's `committed_guests` divided by its `guide_ratio_max`, rounded up to the next whole number — so a committed load exactly equal to `guide_ratio_max` needs one guide, and one more guest tips the requirement to two. This required-guide figure is also consulted when a guide assignment is released, to keep a checked-in trip within its ratio. Next, every non-`REMOVED` guest on the reservation must have a `SIGNED` waiver, otherwise `ERR_WAIVER_NOT_SIGNED`. Finally, every non-`REMOVED` guest must have an `ASSIGNED` gear assignment for a `PFD`, otherwise `ERR_GEAR_NOT_ASSIGNED`. On a successful check-in, every non-`REMOVED` guest on the reservation moves from `BOOKED` to `CHECKED_IN`, and the reservation's `checked_in_guest_count` — the count of its guests in `status` `CHECKED_IN` — is recomputed.

A guest may be removed from a reservation, moving the guest's `status` to `REMOVED`. Removal releases that guest's `ASSIGNED` gear assignments (each release returning its gear item to `AVAILABLE`), voids the guest's waiver, and recomputes the parent reservation's `checked_in_guest_count`.

### 3.6. Payments: Deposits, Settlement, and Gratuity

The deposit is recorded separately from booking. Recording it advances the reservation's `payment_status` from `UNPAID` to `DEPOSIT_PAID`. The reservation must not have been cancelled, otherwise `ERR_RESERVATION_CANCELLED`. The tendered `deposit_cents` must be sufficient: it must be at least the required deposit, which is the reservation's `estimated_total_cents` multiplied by the deposit percentage of 25 percent (0.25), rounded half-up to the nearest whole cent; a deposit exactly equal to the required amount is accepted, and only a strict shortfall is rejected with `ERR_DEPOSIT_TOO_LOW`. On success the trip's `deposits_held_cents` is recomputed. That aggregate is the sum of `deposit_cents` over the trip's reservations whose `payment_status` is `DEPOSIT_PAID` or `SETTLED`.

Settlement closes the account and advances `payment_status` from `DEPOSIT_PAID` to `SETTLED`. Settlement is permitted only when the reservation's `fulfillment_status` is `CHECKED_IN`, otherwise `ERR_NOT_CHECKED_IN`. The settle request supplies `gratuity_cents`, which is recorded on the reservation. The final charge `final_total_cents` is then computed on actuals rather than the booked estimate: the group-discount fraction is still chosen from the booked `party_size` (at least 8 guests gives 0.15, at least 4 gives 0.10, otherwise 0.00), but the base term multiplies `base_rate_cents` by the reservation's `checked_in_guest_count` and by one minus that fraction, rounded half up to whole cents; to this base is added the 4000-cent photo fee when `photo_addon` is true, and then the `gratuity_cents`. The final total therefore diverges from the estimate exactly when a guest was removed between booking and check-in.

Settlement also refreshes the guides' provisional gratuity split. The gratuity pool is the sum of `gratuity_cents` across the trip's reservations whose `payment_status` is `SETTLED`. The provisional split divides this pool equally among the trip's `ASSIGNED` guide assignments, ordered by `created_at` ascending (ties broken by `created_at`, never by `id`). If there are no assigned guides, no distribution occurs. Otherwise each guide's base share is the pool divided by the number of guides, rounded down to whole cents; the leftover cents — the pool minus that base share times the number of guides — are handed out one cent each to the first several guides in `created_at` ascending order. The result is written to each guide assignment's `provisional_gratuity_share_cents`.

### 3.7. River Conditions and Weather-Driven Trip Posture

The `SafetyOfficer` records a **RiverConditionReading** against a trip, supplying the `trip_id`, the observed `flow_cfs` in cubic feet per second, and the `reading_time`. The reading is classified into a `resulting_band` against the trip's own bounds: the band is `SAFE` when `flow_cfs` is greater than or equal to `safe_flow_min` and less than or equal to `safe_flow_max`; it is `MARGINAL` when `flow_cfs` is strictly greater than `safe_flow_max` and less than or equal to `marginal_flow_max`; and it is `UNSAFE` in every other case, that is when `flow_cfs` is below `safe_flow_min` or above `marginal_flow_max`. All three named bounds are inclusive: a flow exactly equal to `safe_flow_max` is `SAFE`, while the smallest amount above it is `MARGINAL`.

The classified band drives the trip's posture automatically. A `MARGINAL` reading holds the trip: a trip in `OPEN` or `FULL` transitions to `WEATHER_HOLD`, and while a trip is on `WEATHER_HOLD` both reservation confirmation and check-in are blocked. A `SAFE` reading lifts the hold: a trip in `WEATHER_HOLD` returns to `OPEN` and becomes bookable again, and if it is at capacity it will recompute to `FULL` on the next confirmation. An `UNSAFE` reading cancels the trip outright, transitioning it to `CANCELLED` and triggering the full trip-cancellation cascade described in §3.9.

### 3.8. Shuttles

Passengers are moved between access points on shuttle runs. The manager first registers a **ShuttleVehicle** with a `name` and a `seat_capacity` of at least one seat. A **ShuttleRun** is then scheduled with a `trip_id`, a `shuttle_vehicle_id`, a `direction` (either `TO_PUT_IN` or `FROM_TAKE_OUT`), a `depart_time`, and an `arrive_time` that must be strictly after the departure. A new run begins in `status` `SCHEDULED`. A vehicle needs turnaround time between runs: if the same vehicle already has a `SCHEDULED` run and the gap between the nearer endpoints of the two runs is strictly less than 30 minutes, the new run is rejected with `ERR_SHUTTLE_BUFFER_CONFLICT`; a gap of exactly 30 minutes is permitted. A run may be cancelled, moving its `status` from `SCHEDULED` to `CANCELLED`.

### 3.9. Completion and the Cancellation Cascades

When the day's work is done the manager completes the trip, transitioning it from `OPEN` or `FULL` to `COMPLETED`. Completion has two guards: no reservation on the trip may still be `PENDING`, otherwise `ERR_UNRESOLVED_RESERVATIONS`; and every `CHECKED_IN` reservation must have `payment_status` `SETTLED`, otherwise `ERR_UNSETTLED_RESERVATION`. On completion every `CHECKED_IN` reservation advances its `fulfillment_status` to `COMPLETED`, and the final, role-weighted gratuity split is computed for every `ASSIGNED` guide assignment. The final split takes the same pooled gratuity — the sum of `gratuity_cents` over the trip's `SETTLED` reservations — and weights it by role, with `LEAD` weighted 3, `SAFETY` weighted 2, and `SWEEP` weighted 1. Let the total weight be the sum of the weights of all `ASSIGNED` guides; if that total weight is zero, no distribution occurs. Otherwise each guide's raw share is the pool multiplied by that guide's role weight, divided by the total weight, rounded down to whole cents. The leftover — the pool minus the sum of all raw shares — is distributed one cent at a time to the guides in `created_at` ascending order (never by `id`). The result is written to each guide assignment's `final_gratuity_share_cents`, and it generally diverges from the equal-split provisional shares because it favors the lead over the sweep.

Trip cancellation is the largest reconciliation in the system. It is reached two ways: the `SafetyOfficer` may cancel a trip directly, and an `UNSAFE` flow reading cancels it automatically. A trip in `SCHEDULED`, `OPEN`, `FULL`, or `WEATHER_HOLD` transitions to `CANCELLED`, and the following cascade runs. Every reservation on the trip whose `fulfillment_status` is `PENDING`, `CONFIRMED`, or `CHECKED_IN` moves to `CANCELLED`. Each such reservation whose `payment_status` is `DEPOSIT_PAID` or `SETTLED` moves to `REFUNDED`, and the trip's `deposits_held_cents` is recomputed as the refunds land. Each cancelled reservation's `ASSIGNED` gear assignments move to `RELEASED`, each release returning its gear item to `AVAILABLE`. Each cancelled reservation's guests move to `REMOVED`, and their `SIGNED` or `PENDING` waivers move to `VOID`. Every `ASSIGNED` guide assignment on the trip moves to `RELEASED`, and every `SCHEDULED` shuttle run on the trip moves to `CANCELLED`.

Cancelling a single reservation runs the same unwinding at booking scope. A reservation in `PENDING`, `CONFIRMED`, or `CHECKED_IN` moves to `CANCELLED`. The trip's `committed_guests` is recomputed downward by the `party_size`, and if the trip was `FULL`, is now below capacity, and has `booking_mode` `GROUP`, it returns to `OPEN`. The reservation's guests' `ASSIGNED` gear assignments move to `RELEASED` (each returning its gear item to `AVAILABLE`), the guests move to `REMOVED`, and their waivers move to `VOID`. If the reservation's `payment_status` was `DEPOSIT_PAID` or `SETTLED`, it moves to `REFUNDED` and the trip's `deposits_held_cents` is recomputed downward by the `deposit_cents`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Setting the logical clock returns `200 OK` with no resource body. Request bodies, response bodies, and side effects for each endpoint are described in the §3 narratives above; the table below lists only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/trips` | Create a river trip | OutfitterManager |
| GET | `/trips` | List river trips | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| GET | `/trips/{id}` | Get a river trip | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| POST | `/trips/{id}/open` | Open a scheduled trip for booking | OutfitterManager |
| POST | `/trips/{id}/complete` | Complete a trip; finalize gratuity shares | OutfitterManager |
| POST | `/trips/{id}/cancel` | Cancel a trip; run full cascade | SafetyOfficer |
| POST | `/guides` | Create a guide | OutfitterManager |
| GET | `/guides` | List guides | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/guides/{id}` | Get a guide | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/guides/{id}/deactivate` | Deactivate a guide | OutfitterManager |
| POST | `/guide-assignments` | Assign a guide to a trip | OutfitterManager |
| GET | `/guide-assignments` | List/filter guide assignments | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/guide-assignments/{id}` | Get a guide assignment | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/guide-assignments/{id}/release` | Release a guide assignment | OutfitterManager |
| POST | `/reservations` | Create a reservation (OCC on trip version) | Reservationist |
| GET | `/reservations` | List/filter reservations | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| GET | `/reservations/{id}` | Get a reservation | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| POST | `/reservations/{id}/confirm` | Confirm a reservation; commit capacity | Reservationist |
| POST | `/reservations/{id}/pay-deposit` | Record the deposit payment | Reservationist |
| POST | `/reservations/{id}/check-in` | Check in a reservation | Reservationist |
| POST | `/reservations/{id}/settle` | Settle a reservation with gratuity | Reservationist |
| POST | `/reservations/{id}/cancel` | Cancel a reservation; run cascade | Reservationist |
| POST | `/guests` | Add a guest to a reservation | Reservationist |
| GET | `/guests` | List/filter guests | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| GET | `/guests/{id}` | Get a guest | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| POST | `/guests/{id}/remove` | Remove a guest from a reservation | Reservationist |
| GET | `/waivers` | List/filter waivers | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| GET | `/waivers/{id}` | Get a waiver | OutfitterManager, Reservationist, SafetyOfficer, Guest |
| POST | `/waivers/{id}/sign` | Guest signs their own waiver | Guest |
| POST | `/gear-items` | Create a gear item | OutfitterManager |
| GET | `/gear-items` | List/filter gear items | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/gear-items/{id}` | Get a gear item | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/gear-items/{id}/retire` | Retire a gear item | OutfitterManager |
| POST | `/gear-assignments` | Assign a gear item to a guest | Reservationist |
| GET | `/gear-assignments` | List/filter gear assignments | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/gear-assignments/{id}` | Get a gear assignment | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/gear-assignments/{id}/release` | Release a gear assignment | Reservationist |
| POST | `/shuttle-vehicles` | Create a shuttle vehicle | OutfitterManager |
| GET | `/shuttle-vehicles` | List shuttle vehicles | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/shuttle-vehicles/{id}` | Get a shuttle vehicle | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/shuttle-runs` | Schedule a shuttle run | OutfitterManager |
| GET | `/shuttle-runs` | List/filter shuttle runs | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/shuttle-runs/{id}` | Get a shuttle run | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/shuttle-runs/{id}/cancel` | Cancel a shuttle run | OutfitterManager |
| POST | `/condition-readings` | Record a river-flow reading | SafetyOfficer |
| GET | `/condition-readings` | List/filter condition readings | OutfitterManager, Reservationist, SafetyOfficer |
| GET | `/condition-readings/{id}` | Get a condition reading | OutfitterManager, Reservationist, SafetyOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | OutfitterManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_WAIVER_OWNER` | 403 |
| `ERR_TRIP_NOT_FOUND` | 404 |
| `ERR_GUIDE_NOT_FOUND` | 404 |
| `ERR_GUIDE_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_GUEST_NOT_FOUND` | 404 |
| `ERR_WAIVER_NOT_FOUND` | 404 |
| `ERR_GEAR_NOT_FOUND` | 404 |
| `ERR_GEAR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_SHUTTLE_VEHICLE_NOT_FOUND` | 404 |
| `ERR_SHUTTLE_RUN_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 400 |
| `ERR_TRIP_NOT_BOOKABLE` | 409 |
| `ERR_INVALID_TRIP_STATE` | 409 |
| `ERR_NO_GUIDE_ASSIGNED` | 409 |
| `ERR_RESERVATION_CANCELLED` | 409 |
| `ERR_INVALID_RESERVATION_STATE` | 409 |
| `ERR_NOT_CHECKED_IN` | 409 |
| `ERR_UNRESOLVED_RESERVATIONS` | 409 |
| `ERR_UNSETTLED_RESERVATION` | 409 |
| `ERR_WAIVER_NOT_PENDING` | 409 |
| `ERR_GEAR_UNAVAILABLE` | 409 |
| `ERR_INVALID_GEAR_STATE` | 409 |
| `ERR_GUIDE_IN_USE` | 409 |
| `ERR_GUEST_UNDER_MIN_AGE` | 422 |
| `ERR_GUARDIAN_REQUIRED` | 422 |
| `ERR_WEIGHT_OUT_OF_RANGE` | 422 |
| `ERR_GUIDE_CLASS_INSUFFICIENT` | 409 |
| `ERR_WAIVER_NOT_SIGNED` | 409 |
| `ERR_GEAR_NOT_ASSIGNED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_GUIDE_RATIO_UNMET` | 409 |
| `ERR_PRIVATE_CONFLICT` | 409 |
| `ERR_GUIDE_DOUBLE_BOOKED` | 409 |
| `ERR_SHUTTLE_BUFFER_CONFLICT` | 409 |
| `ERR_DUPLICATE_GEAR_TYPE` | 409 |
| `ERR_DEPOSIT_TOO_LOW` | 402 |
| `ERR_STALE_TRIP_VERSION` | 412 |
