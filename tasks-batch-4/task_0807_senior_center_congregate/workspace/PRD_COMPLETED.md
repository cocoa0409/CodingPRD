# Senior Center & Congregate Programs API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a senior center operating congregate programs under the Older Americans Act (OAA). The center registers older adults, records their demographic profile for federal reporting, schedules classes and wellness workshops in physical rooms, reserves seats at congregate meal sites, links transportation to those activities, and accounts for every delivered unit of service against a mix of finite grant awards and earmarked donations. The animating problem is fiscal and demographic accountability: each meal served, ride given, wellness session run, or activity attended must be traceable to a funding source and, at reporting time, aggregated into OAA units of service without ever double-counting a dollar or a seat.

Two forces shape the design. The first is that money is finite and must conserve: a grant award authorizes a fixed pool of cents, donations top up a supplemental pool, and the two are drawn down by a strict waterfall so that authorized funds always equal the sum of what has been committed and what remains available. When a service is reversed or a grant is suspended, the compensating logic must return every cent to its source. The second force is that seats, rooms, and vehicles are scarce and time-bound: reservations and signups race for finite capacity, rooms and vehicles cannot be double-booked, and the system must reconcile derived counts (reserved seats, enrolled participants, served meals) against the underlying rows at every mutation.

Because the center reports to federal and state auditors, the service also maintains a strict separation between provisional (forward-looking, projected) figures and final (actual, chronological) figures — for meal reimbursement counts and for wellness-program graduation alike. All time reasoning is performed against a logical clock that the test harness controls, never the real wall clock, so that age computations, signup cutoffs, and reporting windows are deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present and the role is recognized but that role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `CenterAdmin`, `Coordinator`, `Participant`, and `Auditor`.

- A `CenterAdmin` is the center administrator. This role manages grant awards, donations, rooms, vehicles, meal service days, wellness programs, participant lifecycle, and reporting. When `X-User-Role` is `CenterAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`.
- A `Coordinator` runs the operational programs: activity sessions, signups, transportation, meal check-ins and reservations, wellness enrollments, and funded-service entry. When `X-User-Role` is `Coordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.
- A `Participant` is a registered older adult performing self-service actions on their own behalf. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` entity. For any self-service write — signing up for or cancelling an activity, reserving or cancelling a meal, or requesting a ride — the `participant_id` named in the request must equal `X-User-ID`; ownership checks compare the resource's participant foreign key to `X-User-ID`, and a mismatch is an `ERR_UNAUTHORIZED` (HTTP 403). A `Participant` may also read resources; the ownership equality check above applies only to self-service writes, so a `Participant` authorized to fetch or list a resource type may read any instance of it (including another participant's record or contribution statement), not only those whose participant foreign key equals `X-User-ID`.
- An `Auditor` is a read-only oversight role for OAA reporting and record review. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

Section 4 lists the authorized roles for each endpoint; the authorization check (priority 2 below) is evaluated only after authentication (priority 1) succeeds.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, has a minimum of 1, and a maximum of 100. The `offset` defaults to 0 and has a minimum of 0. Results are always ordered by `created_at` in ascending order (oldest first); this is equivalently the order in which the records were created, and records that share the same `created_at` timestamp retain their creation (insertion) order. Each list response includes, inside `meta`, the effective `limit`, the effective `offset`, the `total_count` of records matching the filter before pagination, and a `has_more` boolean that is true when records beyond the current page remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — an opaque UUID string carrying no type prefix. Clients never supply an `id`.

Most entities also carry three common bookkeeping fields. `created_at` is the ISO 8601 UTC timestamp (with three fractional digits) at which the resource was created and never changes. `updated_at` is the ISO 8601 UTC timestamp of the most recent mutation and is refreshed on every write that changes the resource. These bookkeeping timestamps (and the envelope's `api_request_timestamp`) are drawn from the server's real wall-clock UTC at the moment of creation or mutation; they are independent of, and never taken from, the logical clock of Section 2.8. `version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource; it is the value clients echo back for optimistic concurrency control. The following entities carry all three common fields plus `id`: `Participant`, `GrantAward`, `Donation`, `FundedService`, `ActivitySession`, `ActivitySignup`, `TransportationRequest`, `MealServiceDay`, `MealReservation`, `WellnessProgram`, `WellnessEnrollment`, and `VolunteerShift`.

Two entities are lightweight reference resources that carry only `id` and `created_at`: `Room` and `Vehicle`. Neither `Room` nor `Vehicle` has an `updated_at` or a `version` field — they are immutable once created, and no endpoint mutates them.

### 2.5. Optimistic Concurrency Control on Finite Pools

Two create operations draw down a finite shared pool and therefore require optimistic concurrency control against the parent resource they consume. In each case the client must submit, as a required (non-optional) field, the parent's `version` as the client last observed it; if that value does not equal the parent's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.

- Recording a funded service consumes a grant award's finite `available_cents`. The create request must carry `expected_grant_award_version` equal to the target grant award's current `version`. If another funded-service creation has already drawn on the same grant and advanced its `version` since the client last read it, the client's view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Reserving a congregate meal seat consumes a service day's finite `capacity`. The create request must carry `expected_service_day_version` equal to the target meal service day's current `version`. If another reservation has already taken a seat and advanced the day's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field. The version echoed is always that of the parent pool resource (the grant award or the meal service day), not of the row being created.

### 2.6. Validation Order and Error Precedence

When more than one validation could fail for a single request, the checks are evaluated in a fixed priority order and the first failure determines the response. The ordering is:

1. **Authentication** — headers present and `X-User-Role` recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the operation, and for a `Participant` self-service write the `X-User-ID` equals the target `participant_id`; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — every id in the path and every foreign-key id in the body resolves to an existing entity, validated left to right in the order they appear, each yielding its entity-specific not-found error (HTTP 404). The entity-specific codes are `ERR_PARTICIPANT_NOT_FOUND` for a participant, `ERR_GRANT_NOT_FOUND` for a grant award, `ERR_DONATION_NOT_FOUND` for a donation, `ERR_FUNDED_SERVICE_NOT_FOUND` for a funded service, `ERR_ROOM_NOT_FOUND` for a room, `ERR_SESSION_NOT_FOUND` for an activity session, `ERR_SIGNUP_NOT_FOUND` for an activity signup, `ERR_VEHICLE_NOT_FOUND` for a vehicle, `ERR_TRANSPORT_NOT_FOUND` for a transportation request, `ERR_SERVICE_DAY_NOT_FOUND` for a meal service day, `ERR_RESERVATION_NOT_FOUND` for a meal reservation, `ERR_PROGRAM_NOT_FOUND` for a wellness program, and `ERR_ENROLLMENT_NOT_FOUND` for a wellness enrollment.
4. **Optimistic concurrency** — for the two finite-pool creates, the supplied `expected_grant_award_version` or `expected_service_day_version` matches the parent's current `version`, else `ERR_STALE_VERSION` (412).
5. **State** — the target resource is in a state that permits the transition (for example, a grant is `ACTIVE` before it can fund, a meal day is `OPEN` before it can take reservations, a participant is `ACTIVE` for self-service writes), else the applicable state error (HTTP 409).
6. **Temporal validity** — time-window rules (HTTP 422).
7. **Business constraints** — capacity, overlap, and uniqueness rules (HTTP 409), then funding-category coherence (HTTP 422) and meal-specific capacity/duplicate rules.

Malformed input — a missing required field, a value outside an enum's allowed set, or a non-positive amount or quantity — is rejected with `ERR_VALIDATION` (HTTP 400). Body-shape validation of this kind is applied after authentication and role authorization but before existence resolution (priority 3) and every later check, so a malformed body is rejected with `ERR_VALIDATION` (400) even when a path or foreign-key id in the same request refers to a non-existent entity.

### 2.7. Monetary Conservation and Precision

All money is stored and computed in whole integer cents; funding-waterfall arithmetic performs no rounding because every input and output is already a whole number of cents. Two aggregate reports do divide and therefore round: they round half up to the nearest whole cent. There is no fractional-cent representation anywhere in the system.

A grant award obeys a conservation invariant at all times: its `authorized_cents` equals its `committed_cents` plus its `available_cents`. Committing funds moves cents from available to committed; reversing or suspending returns them. This invariant is never allowed to drift — every operation that touches grant funds updates both sides in lockstep. Likewise a donation's `remaining_cents` never exceeds its original `amount_cents`, decreasing as allocations draw on it and increasing again as reversals return funds.

### 2.8. The Logical Clock and Temporal Semantics

All time-dependent reasoning uses a server-held logical clock, never the host's real time. Before any clock call is made, the clock reads `2026-03-01T00:00:00Z`. An administrative test-driving capability sets the clock to a supplied instant. A participant's `age` is the whole number of years between their `birth_date` and the logical clock's current UTC date. Signup cutoffs, session and trip windows, and reporting date ranges are all interpreted against this clock.

### 2.9. Cascading State Propagation and Derived-Field Reconciliation

Several operations mutate more than one entity at once, and every derived count or balance must be kept consistent with the rows it summarizes. Whenever a mutation changes a derived field — a grant's `committed_cents`/`available_cents`, a donation's `remaining_cents`, a participant's `funded_cents`, a session's `enrolled_count`, a meal day's `reserved_count`/`available_seats`/`served_count`, or a wellness enrollment's attendance counters — the owning entity's `updated_at` is refreshed and its `version` is incremented by 1. When one operation cascades across several entities, every entity it mutates has its own `version` incremented by 1 and its `updated_at` refreshed. The specific cascades (grant suspension reversing its funded services down to participant ledgers, participant deactivation cancelling meal reservations and freeing seats) are described in Section 3 where the workflows that trigger them live.

## 3. Business Logic & Workflows

### 3.1. Participant Registration, Demographics, and Deactivation

Registration is where an older adult enters the system. A `CenterAdmin` or `Coordinator` registers a participant by supplying their legal `full_name`, their `birth_date` as an ISO 8601 date, and the OAA demographic profile: `gender` (one of `FEMALE`, `MALE`, `OTHER`, or `DECLINED`), `ethnicity` (the Hispanic-origin category, one of `HISPANIC`, `NON_HISPANIC`, or `DECLINED`), `race` (one of `WHITE`, `BLACK`, `ASIAN`, `NATIVE`, `PACIFIC`, `MULTI`, or `DECLINED`), and `poverty_status` (self-declared, one of `BELOW`, `AT_OR_ABOVE`, or `DECLINED`). Because the OAA prohibits means testing, `poverty_status` is always self-reported and never verified. Three social indicators are captured as booleans: `lives_alone`, `rural`, and `veteran`. The count of self-reported ADL/IADL limitations is given as `disability_count`; this field is optional on input and defaults to 0 when omitted. A newly registered participant is given `status` of `ACTIVE` and a `funded_cents` ledger initialized to 0.

The `age` field is never stored from input; it is derived as the whole number of completed years between `birth_date` and the current logical-clock UTC date. The `funded_cents` field is a maintained ledger equal to the sum, across this participant's funded-service rows whose `status` is `APPLIED`, of each row's `grant_amount_cents` plus `donation_amount_cents`; it moves only through the funding workflows in Section 3.3.

Anyone — `CenterAdmin`, `Coordinator`, `Participant`, or `Auditor` — may fetch a single participant. Only a `CenterAdmin` may deactivate one, and only while the participant's `status` is `ACTIVE`; attempting the transition from any other state is an `ERR_INVALID_STATE` (409). Deactivation moves the participant from `ACTIVE` to `INACTIVE` and then cascades: for every meal reservation belonging to this participant whose `status` is `CONFIRMED`, that reservation is moved to `CANCELLED`, and each such cancellation decrements the reservation's meal service day `reserved_count` by 1 while incrementing that day's `available_seats` by 1. The participant, every reservation it cancels, and every meal service day it touches each have their `version` incremented by 1. Reservations already `CHECKED_IN` or already `CANCELLED` are left untouched. Once a participant is `INACTIVE`, any self-service write attempted on their behalf is rejected with `ERR_PARTICIPANT_INACTIVE` (409).

A monthly voluntary-contribution statement can be produced for any single participant, readable by all four roles. It takes a `month` parameter in `YYYY-MM` form and returns only two figures: `total_suggested_contribution_cents` and `meal_count`. Its computation is described in Section 3.6, where the meal reservations it sums are defined.

### 3.2. Grant Awards and the Donation Pool

Grant awards are the primary, restricted source of funding. Only a `CenterAdmin` creates one, supplying a `title`, the OAA funding `oaa_title` (one of `IIIB`, `IIIC1`, `IIIC2`, `IIID`, or `IIIE`), the service `category` this award funds (one of `CONGREGATE_MEAL`, `TRANSPORTATION`, `WELLNESS`, or `ACTIVITY`), and `authorized_cents`, the total funds authorized under the award, which must be strictly greater than zero. On creation the award is in `status` `DRAFT`, its `committed_cents` is 0, and its `available_cents` is initialized to `authorized_cents`. The `available_cents` field is always maintained as `authorized_cents` minus `committed_cents`.

An award follows a small non-linear lifecycle across the `DRAFT`, `ACTIVE`, and `SUSPENDED` states, driven entirely by the `CenterAdmin`. Activating an award moves it into `ACTIVE`: this same activation capability serves both the initial `DRAFT → ACTIVE` transition and the `SUSPENDED → ACTIVE` resume, closing the `ACTIVE ↔ SUSPENDED` cycle. Activation is permitted only from `DRAFT` or `SUSPENDED`; invoking it on an award that is already `ACTIVE` is rejected with `ERR_INVALID_STATE` (409). A `SUSPENDED` award that is resumed simply returns to `ACTIVE` with its funds still committed as they stood — resuming reverses nothing. A grant may be funded against only while it is `ACTIVE`.

Suspending an award is the consequential cascade. It is permitted only from `ACTIVE` (otherwise `ERR_INVALID_STATE`, 409) and moves the award to `SUSPENDED`. It then reverses every one of that award's funded services whose `status` is `APPLIED`: each such row is set to `REVERSED`; the row's `grant_amount_cents` is returned to the award (the award's `committed_cents` decreases by that amount and its `available_cents` increases by the same amount); if the row drew on a donation, the row's `donation_amount_cents` is returned to that donation's `remaining_cents`; the row's `funding_status` is set to `UNFUNDED`, its `grant_amount_cents` and `donation_amount_cents` are set to 0, and its `unfunded_amount_cents` is set to its `billable_cents`; and the recipient participant's `funded_cents` is decreased by that row's pre-reversal `grant_amount_cents` plus `donation_amount_cents`. This is a depth-three cascade from award to funded service to participant. The award, and every funded service, donation, and participant it mutates, each have `version` incremented by 1.

Grant awards may be fetched by `CenterAdmin`, `Coordinator`, or `Auditor`.

Donations form the supplemental funding pool. Only a `CenterAdmin` records one, supplying a `donor_name`, a `category` the gift is earmarked for (one of `CONGREGATE_MEAL`, `TRANSPORTATION`, `WELLNESS`, `ACTIVITY`, or `UNRESTRICTED`), and an `amount_cents` that must be strictly greater than zero. On creation the donation's `remaining_cents` is initialized to `amount_cents`, and its `restricted` flag is computed as true exactly when `category` is not `UNRESTRICTED` (an `UNRESTRICTED` donation is unrestricted and may fund any category). A donation may be fetched by `CenterAdmin`, `Coordinator`, or `Auditor`.

### 3.3. Funded Services and the Grant-then-Donation Waterfall

A funded service records one delivered unit of OAA service and settles its cost against the funding pools. A `CenterAdmin` or `Coordinator` creates one by naming the recipient `participant_id`, the service `category` (one of `CONGREGATE_MEAL`, `TRANSPORTATION`, `WELLNESS`, or `ACTIVITY`), the `quantity` of countable units delivered (meals served, one-way trips, and so on, which must be at least 1), the `service_date` on which the service was delivered, the primary funding `grant_award_id`, and — when supplemental donation funding should be drawn — an optional `donation_id`; when no donation is used the `donation_id` is omitted. The create also carries `expected_grant_award_version` for the concurrency check of Section 2.5.

Before any money moves, three domain preconditions are checked. The named grant must be `ACTIVE`; funding against a grant in any other status is rejected with `ERR_GRANT_NOT_ACTIVE` (409). The funded service's `category` must equal the grant's `category`; a mismatch is `ERR_GRANT_CATEGORY_MISMATCH` (422). When a donation is supplied, that donation's `category` must either equal the funded service's `category` or be `UNRESTRICTED`; otherwise the create is rejected with `ERR_DONATION_CATEGORY_MISMATCH` (422).

The cost of the unit, `billable_cents`, is the `quantity` multiplied by the per-unit cost for the service's category. Those per-unit costs are fixed: a congregate meal is 850 cents per unit, a transportation trip is 1200 cents per unit, a wellness unit is 1500 cents, and an activity unit is 400 cents. The waterfall then allocates this cost in a pinned order. The grant is drawn first: `grant_amount_cents` is the lesser of the `billable_cents` and the grant's current `available_cents`. Whatever cost the grant did not cover is the running remainder. The donation is drawn second, and only if a `donation_id` was supplied: `donation_amount_cents` is the lesser of that remainder and the donation's `remaining_cents`; if no donation was supplied, `donation_amount_cents` is 0. The `unfunded_amount_cents` is the remainder still left after the donation draw. From these, `funding_status` is `FUNDED` when `unfunded_amount_cents` is 0; `UNFUNDED` when the grant and donation together applied nothing (their sum is 0); and `PARTIALLY_FUNDED` in every other case.

The allocation's side effects commit the money: the grant's `committed_cents` increases by `grant_amount_cents` and its `available_cents` decreases by the same; the donation's `remaining_cents` decreases by `donation_amount_cents`; and the recipient participant's `funded_cents` increases by `grant_amount_cents` plus `donation_amount_cents`. A new funded service is created in `status` `APPLIED`, and the grant award's `version` is incremented by 1 (this is the very advance that later makes a stale `expected_grant_award_version` reject with `ERR_STALE_VERSION`). On this apply path only the grant award's `version` and `updated_at` advance; notwithstanding the general derived-field rule of Section 2.9, the donation's `remaining_cents` and the recipient participant's `funded_cents` are updated in place without incrementing that donation's or that participant's `version` or refreshing their `updated_at`.

A funded service may be fetched by `CenterAdmin`, `Coordinator`, or `Auditor`, and the collection may be listed by those same three roles with optional filters on `participant_id`, `grant_award_id`, `donation_id`, and `category` (plus `limit` and `offset`).

Reversing a funded service is its compensating action, available to a `CenterAdmin` or `Coordinator` and permitted only while the row's `status` is `APPLIED` (otherwise `ERR_INVALID_STATE`, 409). Reversal returns the row's `grant_amount_cents` to its grant (the grant's `committed_cents` decreases by that amount and its `available_cents` increases by it), returns the row's `donation_amount_cents` to the donation's `remaining_cents` when a `donation_id` is set, and decreases the recipient participant's `funded_cents` by `grant_amount_cents` plus `donation_amount_cents`. The row is then zeroed: `grant_amount_cents` and `donation_amount_cents` become 0, `unfunded_amount_cents` becomes the row's `billable_cents`, `funding_status` becomes `UNFUNDED`, and the row moves to `REVERSED`. This preserves each grant's conservation identity of `authorized_cents` equal to `committed_cents` plus `available_cents`. The funded service, the grant award, the donation (if any), and the participant each have `version` incremented by 1. `REVERSED` is terminal — a reversed row is never funded again.

### 3.4. Rooms, Activity Sessions, and Signups

Rooms are the physical spaces classes occupy. A `CenterAdmin` creates a room with a `name` and a `capacity` (the maximum number of seats, at least 1). A room is a lightweight reference resource with no lifecycle.

Scheduling an activity or class session is done by a `CenterAdmin` or `Coordinator`. A session is created with a `title`, an optional programmatic `category` (one of `ACTIVITY` or `WELLNESS`, defaulting to `ACTIVITY` when omitted), the `room_id` of the room it occupies, a `starts_at` and `ends_at` bounding its interval, and a `capacity` (maximum confirmed signups, at least 1). The `starts_at` must be strictly before the `ends_at`; if it is not, the request is rejected with `ERR_INVALID_TIME_WINDOW` (422). The room must not already be in use: if the new session's half-open interval — inclusive of `starts_at`, exclusive of `ends_at` — overlaps the interval of any existing `SCHEDULED` session in the same room, the request is rejected with `ERR_ROOM_DOUBLE_BOOKED` (409). Because the interval is half-open, a session that begins exactly when another ends (adjacency at the shared boundary) does not overlap and is allowed. A new session opens in `status` `SCHEDULED` with `enrolled_count` of 0.

A session may be fetched or listed by `CenterAdmin`, `Coordinator`, `Participant`, or `Auditor`; the list accepts an optional `room_id` filter (plus `limit` and `offset`). A `CenterAdmin` or `Coordinator` may cancel a session while it is `SCHEDULED`, moving it to `CANCELLED` and incrementing its `version` by 1. Cancellation matters beyond the calendar: a `CANCELLED` session can no longer back a transportation approval, as explained in Section 3.5.

Signing a participant up for a session is a self-service action available to a `Participant` (acting on their own behalf) or a `Coordinator`. A signup names the `session_id` and the `participant_id`. Signups close at the session's start: a signup attempted at or after the session's `starts_at`, measured against the logical clock, is rejected with `ERR_SIGNUP_CLOSED` (422). The session must have room: if its `enrolled_count` is already at or above its `capacity`, the signup is rejected with `ERR_SESSION_FULL` (409). A participant may not hold two active signups for the same session; if the participant already holds a `CONFIRMED` signup for that session, the request is rejected with `ERR_DUPLICATE_SIGNUP` (409). A successful signup is created in `status` `CONFIRMED`, increments the session's `enrolled_count` by 1, and increments the session's `version` by 1.

A signup may be fetched or listed by `CenterAdmin`, `Coordinator`, `Participant`, or `Auditor`; the list accepts optional `session_id` and `participant_id` filters (plus `limit` and `offset`). Cancelling a signup is available to a `Participant` (own signup) or a `Coordinator`, and is permitted while the signup is `CONFIRMED`. Cancellation moves the signup to `CANCELLED`, decrements the backing session's `enrolled_count` by 1 (freeing the seat), and increments the `version` of both the signup and the session by 1.

### 3.5. Vehicles and Transportation Requests

Vehicles carry participants to their activities. A `CenterAdmin` creates a vehicle with a `name` and a `seat_capacity` (rider seats, at least 1). Like a room, a vehicle is a lightweight reference resource with no lifecycle.

A ride is requested by a `Participant` (on their own behalf) or a `Coordinator`, naming the rider `participant_id`, the assigned `vehicle_id`, the `linked_session_id` of the activity the ride serves, and the pickup-to-dropoff window as `starts_at` and `ends_at`. The window must be valid — `starts_at` strictly before `ends_at`, else `ERR_INVALID_TIME_WINDOW` (422). A vehicle cannot be in two places at once, and it needs turnaround time between trips: the new trip window, expanded by a fifteen-minute turnaround buffer on each side, must not overlap any existing non-`CANCELLED` trip already assigned to that vehicle; an overlap is rejected with `ERR_VEHICLE_UNAVAILABLE` (409). A transportation request has two independent status dimensions. On creation its `eligibility_status` is `PENDING` and its `trip_status` is `SCHEDULED`; the two axes evolve independently and neither transition touches the other.

A transportation request may be fetched or listed by `CenterAdmin`, `Coordinator`, `Participant`, or `Auditor`; the list accepts optional `participant_id`, `vehicle_id`, and `linked_session_id` filters (plus `limit` and `offset`).

Two operations, both reserved to a `Coordinator`, advance the two axes. Approving the ride's eligibility advances `eligibility_status` from `PENDING` to `APPROVED` and leaves `trip_status` unchanged; it is permitted only while `eligibility_status` is `PENDING`, and it additionally requires that the linked activity session still be `SCHEDULED` — if that session has been cancelled, approval is rejected with `ERR_SESSION_NOT_SCHEDULED` (409). Completing the ride advances `trip_status` from `SCHEDULED` to `COMPLETED` and leaves `eligibility_status` unchanged; it is permitted only while `trip_status` is `SCHEDULED` and only once the ride's `eligibility_status` is already `APPROVED`. A `COMPLETED` trip is terminal on the operational axis. Each of these two transitions increments the transportation request's `version` by 1.

### 3.6. Congregate Meal Service Days and Reservations

A congregate meal service day represents one site serving meals on one date. A `CenterAdmin` opens a day with a `service_date`, a `site_name`, and a `capacity` (the maximum confirmed reservations, at least 1). A new day opens in `status` `OPEN`, with `reserved_count` of 0 and `available_seats` initialized to its `capacity`. The `available_seats` is always maintained as `capacity` minus `reserved_count`. The `reserved_count` is the number of that day's reservations whose `status` is either `CONFIRMED` or `CHECKED_IN` — a checked-in participant still occupies a seat. The `served_count` is the number of that day's reservations whose `status` is `CHECKED_IN`.

The day also reports two reimbursable-unit counts, a provisional figure and a final figure, that split apart exactly at attendance. The `provisional_reimbursable_units` is the forward-looking projection: the count of the day's reservations whose `status` is `CONFIRMED` or `CHECKED_IN` (equivalently, all held seats, which equals `reserved_count`). The `final_reimbursable_units` is the chronological actual: the count of the day's reservations whose `status` is `CHECKED_IN`. The provisional figure is the OAA reimbursement projection reported once the day is closed; the final figure is reported after check-ins and differs from the provisional exactly by the no-shows who reserved but never checked in. Any of the four roles may fetch a meal service day, and the fetched resource carries both reimbursable-unit counts.

A `CenterAdmin` may close a day while it is `OPEN`, moving it to `CLOSED` and incrementing its `version` by 1. Closing freezes new reservations: once a day is `CLOSED`, an attempt to reserve a seat on it is rejected with `ERR_SERVICE_DAY_CLOSED` (409). Check-ins, however, remain permitted on a `CLOSED` day.

Reserving a seat is a self-service action for a `Participant` (own behalf) or a `Coordinator`. A reservation names the `service_day_id`, the `participant_id`, an optional `suggested_contribution_cents` (the voluntary contribution the participant pledges for the meal, defaulting to 0 when omitted — under the OAA this is never a fee and never a means test), and the `expected_service_day_version` for the concurrency check of Section 2.5. The day must be `OPEN` (else `ERR_SERVICE_DAY_CLOSED`, 409). The day must have a free seat: if its `reserved_count` is already at or above its `capacity`, the reservation is rejected with `ERR_MEAL_CAPACITY_EXCEEDED` (409). A participant may not double-book a day: if they already hold a `CONFIRMED` or `CHECKED_IN` reservation for that same service day, the request is rejected with `ERR_DUPLICATE_RESERVATION` (409). A successful reservation is created in `status` `CONFIRMED`, increments the day's `reserved_count` by 1 while decrementing its `available_seats` by 1, and increments the day's `version` by 1 (the advance behind the stale-version check).

A reservation may be fetched or listed by any of the four roles; the list accepts optional `service_day_id` and `participant_id` filters (plus `limit` and `offset`). Cancelling a reservation is available to a `Participant` (own reservation) or a `Coordinator` and is permitted while the reservation is `CONFIRMED`; it moves the reservation to `CANCELLED`, decrements the day's `reserved_count` by 1 while incrementing its `available_seats` by 1, and increments the `version` of both the reservation and the day by 1. Checking a participant in is reserved to a `Coordinator` and is permitted while the reservation is `CONFIRMED` and the day's `status` is either `OPEN` or `CLOSED`; it moves the reservation from `CONFIRMED` to `CHECKED_IN`, increments the day's `served_count` by 1, and increments the `version` of both the reservation and the day by 1. Because a `CHECKED_IN` seat is still an occupied seat, check-in leaves `reserved_count` and `available_seats` unchanged. `CANCELLED` is terminal for a reservation.

The monthly contribution statement of Section 3.1 draws on these reservations. For the requested `month`, the statement considers the participant's reservations whose `status` is `CHECKED_IN` and whose `service_date` falls within that calendar month in UTC — from the first day of the month at 00:00:00Z through the last day at 23:59:59Z inclusive. For each such meal, the per-meal suggested contribution is the congregate-meal unit cost of 850 cents multiplied by the contribution rate of fifteen percent (0.15), rounded half up to a whole number of cents. The rounding order is pinned: each meal's contribution is rounded to whole cents first, and only then are the per-meal amounts summed — summing first and rounding once would yield a different total and is not used. The returned `total_suggested_contribution_cents` is that per-meal sum, and `meal_count` is the number of qualifying meals.

### 3.7. Evidence-Based Wellness Programs and Enrollments

A wellness program is an evidence-based workshop series. A `CenterAdmin` or `Coordinator` creates one with a `title`, a recognized `model` (one of `CDSMP`, `DPP`, `ENHANCE_FITNESS`, or `MATTER_OF_BALANCE`), a `total_sessions` count for the full series (at least 1), and a `fidelity_min_sessions` graduation threshold — the minimum number of sessions a participant must attend for a fidelity-valid completion, which must be at least 1 and at most `total_sessions`.

A `Coordinator` enrolls a participant by naming the `program_id` and the `participant_id`. A new enrollment opens in `status` `ACTIVE` with `sessions_attended` of 0, `absences_total` of 0, and `consecutive_absences` of 0. Enrollments may be fetched or listed by any of the four roles; the list accepts optional `program_id` and `participant_id` filters (plus `limit` and `offset`), and the fetched enrollment carries its `projected_graduation_status`.

Attendance is recorded by a `Coordinator`, one session at a time, by logging whether the participant `attended`. The enrollment tracks three counters: `sessions_attended` (attended logs), `absences_total` (a monotonic count of every absence log, i.e. every log with `attended` false), and `consecutive_absences` (a running streak of absences that resets whenever an attended session is logged). The enrollment cycles between `ACTIVE` and `LAPSED`:

- Logging an attended session (`attended` true) while the enrollment is `ACTIVE` increments `sessions_attended` by 1, resets `consecutive_absences` to 0, and keeps the enrollment `ACTIVE`.
- Logging an absence (`attended` false) while `ACTIVE` always increments both `consecutive_absences` and `absences_total` by 1. Whether the enrollment lapses depends on the resulting streak against a lapse threshold of 2 consecutive absences: if the value `consecutive_absences` would reach after this log (its current value plus one) is at least 2, the enrollment transitions from `ACTIVE` to `LAPSED`; if that value is still below 2 (that is, this is the first absence in the streak), the enrollment stays `ACTIVE`. In practice a single absence logged when `consecutive_absences` is already 1 lapses the enrollment.
- Logging an attended session (`attended` true) while the enrollment is `LAPSED` is a re-engagement: it increments `sessions_attended` by 1, resets `consecutive_absences` to 0, and moves the enrollment from `LAPSED` back to `ACTIVE`, closing the cycle.

Logging attendance is permitted only while the enrollment is `ACTIVE` or `LAPSED`; attempting to log a session on a terminal (`GRADUATED` or `WITHDRAWN`) enrollment is rejected with `ERR_INVALID_STATE` (409). Every attendance log increments the enrollment's `version` by 1.

A read of the enrollment reports a projected graduation outlook, `projected_graduation_status`. This is the optimistic variant: it assumes the participant attends every remaining session. It is `WILL_GRADUATE` when the program's `total_sessions` minus the enrollment's `absences_total` is at least the program's `fidelity_min_sessions`, and `AT_RISK` otherwise. (Because every remaining session is assumed attended, the best reachable attendance equals `total_sessions` minus the absences already accrued.)

Finalizing an enrollment is a `Coordinator` action, permitted only while the enrollment's `status` is `ACTIVE` or `LAPSED` (finalizing from any other state is `ERR_INVALID_STATE`, 409). Finalize decides the outcome by the pessimistic final variant, which counts only sessions actually attended: if `sessions_attended` is at least the program's `fidelity_min_sessions`, the enrollment moves to `GRADUATED`; otherwise it moves to `WITHDRAWN`. This holds whether the enrollment was `ACTIVE` or `LAPSED` at finalize time — both source states graduate when the attended count meets the threshold and withdraw when it does not. `GRADUATED` and `WITHDRAWN` are terminal. Finalize increments the enrollment's `version` by 1. Note that the projected outlook and the final outcome can diverge: an enrollment reading `WILL_GRADUATE` can still be finalized to `WITHDRAWN` if it is finalized before enough sessions have actually been attended.

### 3.8. Volunteer Hours, OAA Reporting, and the Logical Clock

Volunteer shifts capture donated labor. A `CenterAdmin` or `Coordinator` logs a shift with the `volunteer_name` (an opaque grouping key used to aggregate hours), the `role` worked (for example meal-server or driver), the `hours` worked (which must be greater than 0), and the `service_date`. Shifts may be listed by `CenterAdmin`, `Coordinator`, or `Auditor`, with an optional `volunteer_name` filter (plus `limit` and `offset`) so hours can be totaled per volunteer.

The OAA units-of-service report is the accountability capstone, readable by a `CenterAdmin` or an `Auditor`. It takes a `category`, a `from` instant, and a `to` instant. It aggregates the funded-service rows in that `category` whose `status` is `APPLIED` and whose `service_date` falls within the window from `from` to `to` inclusive on both ends; reversed rows are excluded. It returns `total_units` (the sum of those rows' `quantity`), `total_billable_cents` (the sum of their `billable_cents`), `grant_funded_cents` (the sum of their `grant_amount_cents`), `donation_funded_cents` (the sum of their `donation_amount_cents`), `unfunded_cents` (the sum of their `unfunded_amount_cents`), and `cost_per_unit_cents`. The cost per unit is the `total_billable_cents` divided by `total_units`, rounded half up to a whole cent; when `total_units` is 0 (an empty result set), `cost_per_unit_cents` is reported as 0 rather than dividing by zero. The response also echoes the requested `category`.

Finally, an administrative test-driving capability lets a `CenterAdmin` set the logical clock to a supplied instant, provided as `to_iso8601`. Setting the clock returns the new `current_utc`. Before any such call is made, the clock reads `2026-03-01T00:00:00Z`, and the server never falls back to the host's real time.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that fetch, list, or modify an existing resource (including all state transitions and the administrative and reporting endpoints) return HTTP 200. Request and response payloads are not repeated here — reconstruct them from the workflow narratives in Section 3. All list endpoints honor the pagination and ordering rules of Section 2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/participants` | Register a participant with OAA demographics | CenterAdmin, Coordinator |
| GET | `/participants/{id}` | Fetch a participant | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/participants/{id}/deactivate` | Deactivate a participant; cascades cancellation of their confirmed meal reservations | CenterAdmin |
| GET | `/participants/{id}/contribution-statement` | Monthly voluntary-contribution statement | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/grant-awards` | Create a grant award (DRAFT) | CenterAdmin |
| GET | `/grant-awards/{id}` | Fetch a grant award | CenterAdmin, Coordinator, Auditor |
| POST | `/grant-awards/{id}/activate` | Activate a DRAFT grant or resume a SUSPENDED grant | CenterAdmin |
| POST | `/grant-awards/{id}/suspend` | Suspend an ACTIVE grant; cascades reversal of its applied funded services | CenterAdmin |
| POST | `/donations` | Record a donation into the funding pool | CenterAdmin |
| GET | `/donations/{id}` | Fetch a donation | CenterAdmin, Coordinator, Auditor |
| POST | `/funded-services` | Record a delivered OAA unit and run the grant-then-donation waterfall | CenterAdmin, Coordinator |
| GET | `/funded-services/{id}` | Fetch a funded service | CenterAdmin, Coordinator, Auditor |
| GET | `/funded-services` | List funded services; filter by participant, grant, donation, or category | CenterAdmin, Coordinator, Auditor |
| POST | `/funded-services/{id}/reverse` | Reverse an applied funded service; compensating waterfall | CenterAdmin, Coordinator |
| POST | `/rooms` | Create a room resource | CenterAdmin |
| POST | `/activity-sessions` | Schedule an activity/class session in a room | CenterAdmin, Coordinator |
| GET | `/activity-sessions/{id}` | Fetch an activity session | CenterAdmin, Coordinator, Participant, Auditor |
| GET | `/activity-sessions` | List activity sessions; filter by room | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/activity-sessions/{id}/cancel` | Cancel a scheduled session | CenterAdmin, Coordinator |
| POST | `/activity-signups` | Sign a participant up for a session | Participant, Coordinator |
| GET | `/activity-signups/{id}` | Fetch a signup | CenterAdmin, Coordinator, Participant, Auditor |
| GET | `/activity-signups` | List signups; filter by session or participant | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/activity-signups/{id}/cancel` | Cancel a confirmed signup, freeing a seat | Participant, Coordinator |
| POST | `/vehicles` | Create a vehicle resource | CenterAdmin |
| POST | `/transportation-requests` | Request a ride to an activity on a vehicle | Participant, Coordinator |
| GET | `/transportation-requests/{id}` | Fetch a transportation request | CenterAdmin, Coordinator, Participant, Auditor |
| GET | `/transportation-requests` | List transportation requests; filter by participant, vehicle, or linked session | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/transportation-requests/{id}/approve` | Approve ride eligibility (requires the linked session SCHEDULED) | Coordinator |
| POST | `/transportation-requests/{id}/complete` | Mark the trip completed (requires eligibility APPROVED) | Coordinator |
| POST | `/meal-service-days` | Open a congregate meal service day | CenterAdmin |
| GET | `/meal-service-days/{id}` | Fetch a meal service day (includes provisional/final reimbursable counts) | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/meal-service-days/{id}/close` | Close a meal service day for new reservations | CenterAdmin |
| POST | `/meal-reservations` | Reserve a congregate meal seat | Participant, Coordinator |
| GET | `/meal-reservations/{id}` | Fetch a meal reservation | CenterAdmin, Coordinator, Participant, Auditor |
| GET | `/meal-reservations` | List meal reservations; filter by service day or participant | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/meal-reservations/{id}/cancel` | Cancel a confirmed reservation, freeing a seat | Participant, Coordinator |
| POST | `/meal-reservations/{id}/check-in` | Check a participant in for their reserved meal | Coordinator |
| POST | `/wellness-programs` | Create an evidence-based wellness program | CenterAdmin, Coordinator |
| POST | `/wellness-enrollments` | Enroll a participant in a wellness program | Coordinator |
| GET | `/wellness-enrollments/{id}` | Fetch a wellness enrollment (includes projected graduation status) | CenterAdmin, Coordinator, Participant, Auditor |
| GET | `/wellness-enrollments` | List wellness enrollments; filter by program or participant | CenterAdmin, Coordinator, Participant, Auditor |
| POST | `/wellness-enrollments/{id}/log-session` | Log a session attendance (attended true/false) | Coordinator |
| POST | `/wellness-enrollments/{id}/finalize` | Finalize enrollment to GRADUATED or WITHDRAWN | Coordinator |
| POST | `/volunteer-shifts` | Log a volunteer shift with hours | CenterAdmin, Coordinator |
| GET | `/volunteer-shifts` | List volunteer shifts; filter by volunteer for hour totals | CenterAdmin, Coordinator, Auditor |
| GET | `/reports/oaa-units` | OAA units-of-service report by category over a service-date window | CenterAdmin, Auditor |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock | CenterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_PARTICIPANT_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_DONATION_NOT_FOUND | 404 |
| ERR_FUNDED_SERVICE_NOT_FOUND | 404 |
| ERR_ROOM_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_SIGNUP_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_TRANSPORT_NOT_FOUND | 404 |
| ERR_SERVICE_DAY_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_GRANT_NOT_ACTIVE | 409 |
| ERR_SERVICE_DAY_CLOSED | 409 |
| ERR_SESSION_NOT_SCHEDULED | 409 |
| ERR_PARTICIPANT_INACTIVE | 409 |
| ERR_INVALID_TIME_WINDOW | 422 |
| ERR_SIGNUP_CLOSED | 422 |
| ERR_ROOM_DOUBLE_BOOKED | 409 |
| ERR_VEHICLE_UNAVAILABLE | 409 |
| ERR_SESSION_FULL | 409 |
| ERR_DUPLICATE_SIGNUP | 409 |
| ERR_GRANT_CATEGORY_MISMATCH | 422 |
| ERR_DONATION_CATEGORY_MISMATCH | 422 |
| ERR_MEAL_CAPACITY_EXCEEDED | 409 |
| ERR_DUPLICATE_RESERVATION | 409 |








