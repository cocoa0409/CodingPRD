# School Bus Routing & Ridership API — Product Requirements Document

## 1. Introduction

School transportation departments juggle two responsibilities that constantly press against each other: deciding *who* is entitled to ride a bus, and running the daily fleet safely once those riders are on board. This document specifies the School Bus Routing & Ridership API, a system that unifies both responsibilities behind a single set of resources. On the eligibility side, the API determines whether a student qualifies for transportation based on how far they live from campus and whether their walking route crosses a designated hazard, then shepherds a parent's ridership request through review, revision, and a capacity-aware approval. On the operations side, it models the live trip — driver assignment and substitution, GPS-driven arrival estimates, RFID tap-on/tap-off ridership accounting, incident holds, and the missed-bus protocol — while keeping parents informed through a notification feed.

The design centers on a small number of postures and lifecycles that gate everything else. A route's operational posture decides whether new riders may be assigned and whether buses may roll. A bus trip moves through a branching lifecycle with an incident fork and a stop-by-stop progression. A ridership application cycles between review and parent revision until it is decided. Throughout, the system holds itself to immediate consistency: every count, every onboard tally, and every derived distance is reconciled the moment the triggering event occurs, and concurrent edits to the same route are mediated by optimistic version checks so that a stale writer can never silently overwrite a decision it never observed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the capacity in which they act. When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation — or a parent attempts to act on a student or application they do not own — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `TransportAdmin`, `Parent`, and `Driver`.

A `TransportAdmin` is the district transportation operator. When `X-User-Role` is `TransportAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The admin configures districts, routes, and stops, reviews and decides ridership applications, manages drivers and assignments, schedules and cancels trips, clears incidents, and runs the missed-bus protocol.

A `Driver` runs their own scheduled trips. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on any resource that references a `Driver` compare the resource's driver foreign key to `X-User-ID`. Concretely, a driver may only operate a bus trip whose `driver_assignment_id` resolves to a `DriverAssignment` whose `driver_id` equals the acting driver's `X-User-ID`. This driver-ownership check gates only the write operations a driver performs against a specific bus trip — its GPS ping, start-boarding, depart-stop, raise-incident, complete, and tap-recording transitions; the read endpoints a driver is authorized for (getting or listing drivers, driver assignments, bus trips, and tap events) are not ownership-scoped, so a driver may read any such resource.

A `Parent` is the guardian who owns student records. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Parent`; ownership checks on any resource that references a `Parent` compare the resource's `parent_id` to `X-User-ID`. A parent's `id` is an opaque guardian identifier minted outside this API: there is no standalone Parent resource or Parent CRUD endpoint. The guardian id is supplied as a student's `parent_id` at student creation and presented as `X-User-ID` on the parent's own calls. Ownership of a ridership application is determined transitively through the application's student's `parent_id`. Children of a parent — students and parent notifications — are discoverable through their respective `parent_id` list filters rather than through any reverse lookup of a Parent entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp indicating the most recent modification; it is refreshed on every change to the resource.
- **`version`** — a system-managed integer that begins at its initial value and increments by one with every modification. It is the basis for optimistic concurrency control.

Two resource types are append-only event records and therefore carry only `id` and `created_at`: a `TapEvent` and a `ParentNotification`. Neither of these has an `updated_at` field and neither has a `version` field, because once written they are never modified. All other resources — districts, routes, stops, students, ridership applications, drivers, driver assignments, bus trips, and missed-bus reports — carry the full quartet of common fields.

Whenever the server changes a derived or system field on a resource (for example, recomputing a route's rider counts, advancing a trip's current stop, or refreshing a trip's onboard tally), that change is a mutation: it refreshes `updated_at` and increments `version` on the affected resource, exactly as a direct edit would.

### 2.5. Hierarchical Consistency and Cascades

The system maintains immediate consistency across related resources. When a single operation alters more than one resource, every secondary effect is applied synchronously within that same operation, and each affected resource independently has its `updated_at` refreshed and its `version` incremented.

The most consequential cascade originates from suspending a route. Suspension forces every bus trip on that route that is still in `SCHEDULED` status to `CANCELLED`, and for each such cancelled trip, if its driver was `ON_DUTY` on account of that trip, the driver is returned to `AVAILABLE`. The substitute-driver mechanism produces a second cascade: creating a `SUBSTITUTE` driver assignment that names a `PRIMARY` assignment drives that named primary assignment from `ACTIVE` to `SUPERSEDED`, while the substitute itself remains `ACTIVE`. Approving a ridership application cascades into recomputed rider counts on the target route. Raising or clearing an incident recomputes the route's `open_incident` flag. Recording a tap recomputes the trip's `onboard_count`. In every case the recomputation happens at the moment of the triggering event, never lazily.

### 2.6. Computed Counts and Postures

Several fields are never written directly by clients but are always derived from the current state of related resources:

- A district's `active_route_count` is the number of routes belonging to that district whose posture is either `OPEN` or `RESTRICTED`; routes in `SUSPENDED` posture are excluded from the count.
- A route's `assigned_rider_count` is the number of ridership applications in `APPROVED` status whose `assigned_route_id` is that route.
- A route's `assigned_wheelchair_count` is the number of those `APPROVED` applications on the route whose subject student has `special_needs` set to true.
- A route's `open_incident` flag is true exactly when at least one bus trip on that route is in `INCIDENT_HOLD` status, and false otherwise.
- A bus trip's `onboard_count` is the number of students currently on the bus, computed by replaying that trip's tap log (see §3.6).
- A bus trip's `eta_next_stop_minutes` is the estimated minutes to the current stop, computed as described in §3.5.

### 2.7. Nested Reference Validation

Although every collection in this API lives at the top level and parent links are carried as foreign-key fields in request bodies and query strings rather than as nested URL segments, requests still reference resources both by path identifier and by body foreign key, and these are validated in a fixed order. Path-referenced resources are validated first, left to right: if any identifier named in the path does not correspond to an existing resource, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any body-level work begins. Only after all path resources are confirmed to exist does the system validate the request body.

### 2.8. Request Validation Ordering

For any write, the system evaluates checks in a strict priority order, returning the first failure it encounters. The order is: authentication of the headers first (`ERR_UNAUTHENTICATED`, HTTP 401); then role authorization including parent-ownership (`ERR_FORBIDDEN`, HTTP 403); then existence of all path-referenced resources (`ERR_NOT_FOUND`, HTTP 404); then well-formedness of the request body — required fields present, enum values valid, and numbers within range (`ERR_INVALID_REQUEST`, HTTP 422); then resolution and parentage of body foreign-key references (`ERR_INVALID_REFERENCE`, HTTP 422); then uniqueness constraints (`ERR_DUPLICATE`, HTTP 409); then, where it applies, the stop-time ordering constraint (`ERR_STOP_TIME_ORDER`, HTTP 422); then the optimistic-concurrency version check (`ERR_STALE_VERSION`, HTTP 412); then the legality of the requested state transition (`ERR_INVALID_STATE`, HTTP 409); and finally the domain-specific business safety, fiscal, referential, and temporal checks described throughout §3. Because authentication outranks existence, a request with bad headers against a non-existent resource surfaces `ERR_UNAUTHENTICATED`, not `ERR_NOT_FOUND`; and because the version check outranks the state-legality check, a stale-version posture write surfaces `ERR_STALE_VERSION` rather than `ERR_INVALID_STATE`.

A body is considered well-formed only when its numeric inputs are in range: a route's `seat_capacity` must be greater than zero, a route's `wheelchair_capacity` must be at least zero, a stop's `sequence` must be at least one, a student's `grade` must be between 0 and 12 inclusive, and latitude/longitude values must be numeric. Any violation of these yields `ERR_INVALID_REQUEST`.

### 2.9. Precision and Rounding

The system computes three derived numeric quantities, each with its own precision rule, and all rounding throughout the system uses the round-half-up convention.

A student's `home_distance_miles` — the straight-line distance from home to campus — is rounded to exactly two decimal places. A bus trip's `eta_next_stop_minutes` is rounded to exactly one decimal place. Counts such as `onboard_count`, `assigned_rider_count`, `assigned_wheelchair_count`, and `active_route_count` are exact integers and are never rounded. Eligibility comparisons are performed against the two-decimal-place `home_distance_miles` value as already stored.

### 2.10. Optimistic Concurrency Control

Two write operations on a route are guarded by optimistic concurrency control, and both target the parent `Route` entity. The first is a posture change. A posture-change request must carry `expected_route_version` carrying the route version the client last observed; if another writer has advanced the route's `version` since then — for instance, an earlier posture write already flipped the posture and bumped the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A posture write legitimately supersedes the prior posture, so a stale writer is rejected on the version check rather than being allowed to re-flip a posture it never saw.

The second guarded operation is creating a driver assignment on a route. Such a request must likewise carry `expected_route_version` matching the route's current `version`. Because a substitute assignment legitimately supersedes the primary it covers, a writer holding a stale route version — one whose version was already advanced by an earlier assignment creation — is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding a primary on a route it has not observed in its current form.

Both checks are framed purely in terms of the client's last-observed version versus the route's current version; no other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Districts, Routes, and Stops: the Service Skeleton

Everything begins with a **District**, created by a `TransportAdmin`. A district carries a human-readable `name` and the campus coordinates `school_lat` and `school_lng` in decimal degrees, which anchor every distance calculation. Three configuration knobs shape eligibility and the missed-bus protocol. The `walk_threshold_miles` value, defaulting to 1.5, is the straight-line distance beyond which a student is considered too far to walk. The `hazard_override_enabled` flag, defaulting to true, decides whether a hazardous walking route can rescue an otherwise-ineligible student. The `missed_bus_grace_minutes` value, defaulting to 10, sets how long after a stop's scheduled departure a missed-bus report may still be filed. The district also maintains a monotonic operations-epoch counter, `service_day_index`, which starts at 0 and is advanced one at a time by an admin-only advance-service-day capability; that same advance operation returns the updated district. At creation, `service_day_index` is 0 and `active_route_count` computes as 0.

A **Route** belongs to a district by way of its `district_id` and carries a `name`. Its `seat_capacity` sets the maximum number of seated riders and must be greater than zero, while its `wheelchair_capacity` sets the number of securement positions for special-needs riders, defaults to 0, and must be at least zero. A route begins life in `OPEN` posture, with `assigned_rider_count`, `assigned_wheelchair_count` both at 0 and `open_incident` false. Routes can be listed with optional filters on `district_id` and `posture`.

A **Stop** belongs to a route through its `route_id` and is described by a `label`, its coordinates `lat` and `lng`, a one-based `sequence` giving its order along the route, and a `scheduled_departure` — the ISO 8601 UTC time the bus is scheduled to leave that stop on any service day. Stops can be listed filtered by `route_id`. Two integrity rules govern stop creation. First, `sequence` must be unique within its route; a collision is rejected with `ERR_DUPLICATE`. Second, the stops of a route form a strictly increasing one-dimensional timeline: a new stop's `scheduled_departure` must be strictly later than the departure of every existing stop on the route with a lower `sequence`, and strictly earlier than the departure of every existing stop with a higher `sequence`. A departure that ties or inverts against an adjacent stop's time is rejected with `ERR_STOP_TIME_ORDER`.

### 3.2. Students and the Distance/Hazard Eligibility Engine

A **Student** record is owned by a guardian and registered either by that `Parent` or by a `TransportAdmin`. It carries the student's `district_id`, the owning `parent_id`, a `full_name`, a `grade` between 0 (kindergarten) and 12 inclusive, the home coordinates `home_lat` and `home_lng`, a `hazard_zone` flag (default false) indicating whether the home-to-school walk crosses a state-designated hazard such as a missing sidewalk or a highway crossing, a `special_needs` flag (default false) indicating the student requires a wheelchair securement position, and a unique `rfid_uid` for the student's tap card. The `rfid_uid` must be unique across all students in the district; a reused value is rejected with `ERR_DUPLICATE`. Students can be listed filtered by `district_id` and by `parent_id`; when the acting role is `Parent`, the list is implicitly restricted to that parent's own students regardless of the supplied filters.

At the moment a student is created, the system computes `home_distance_miles`: the great-circle straight-line distance from the student's home to the district campus. Using an Earth radius of 3958.7613 miles, the system takes the difference between the home and school latitudes and the difference between the home and school longitudes, both converted to radians; forms the haversine term as the square of the sine of half the latitude difference plus the product of the cosine of the home latitude, the cosine of the school latitude, and the square of the sine of half the longitude difference; takes twice the arcsine of the square root of that term as the central angle; multiplies the central angle by the Earth radius to obtain the distance in miles; and rounds that distance half-up to two decimal places. This value is stored on the student and is the sole distance input to eligibility.

Eligibility itself is not computed at student creation; it is determined for a specific ridership application when that application enters review and again whenever it is resubmitted. The rule places distance first and treats hazard strictly as an override. Let the student's stored `home_distance_miles` be the distance and the district's `walk_threshold_miles` be the threshold. If the distance is strictly greater than the threshold, the application's `eligibility_basis` is `DISTANCE`. Otherwise, if the district's `hazard_override_enabled` is true and the student's `hazard_zone` is true, the basis is `HAZARD`. In every other case the basis is `NONE`, meaning ineligible. The boundary is decisive: a student whose distance exactly equals the threshold is not distance-eligible — the comparison is strictly greater-than, not greater-than-or-equal — and so falls through to the hazard test, becoming `HAZARD` only if override is enabled and the home is in a hazard zone, and `NONE` otherwise. When `hazard_override_enabled` is false, hazard is ignored entirely and only distance counts.

### 3.3. The Ridership Application Lifecycle

A **RidershipApplication** is the parent-driven request to put a student on a particular route and stop. It is submitted by a `Parent` (for their own student) or by a `TransportAdmin`, and carries the `district_id`, the `student_id`, the requested `requested_route_id`, and the requested `requested_stop_id`, which must belong to the requested route. On submission, all four body references are resolved first — any of `district_id`, `student_id`, `requested_route_id`, or `requested_stop_id` that does not resolve, or a `requested_stop_id` that does not belong to `requested_route_id`, is rejected with `ERR_INVALID_REFERENCE` — and only after those references resolve is the parent-ownership check applied: because that check reads the resolved student's `parent_id`, a `Parent` submitting for a student they do not own surfaces `ERR_INVALID_REFERENCE` ahead of `ERR_FORBIDDEN` whenever any of the body references fails to resolve, and surfaces `ERR_FORBIDDEN` only once all references resolve. On submission the application starts in `SUBMITTED` status with `eligibility_basis` of `PENDING`. The application also tracks `review_round` (the number of completed change-and-resubmit cycles, starting at 0), and on approval records its `assigned_route_id` and `assigned_stop_id`; on denial it records a `denial_reason`. Applications can be listed filtered by `district_id`, `student_id`, `requested_route_id`, `requested_stop_id`, `assigned_route_id`, `assigned_stop_id`, and `status`; when the acting role is `Parent`, the list is implicitly restricted to applications whose student is owned by that parent regardless of the supplied filters.

A `TransportAdmin` opens review by starting review on a `SUBMITTED` application, advancing it from `SUBMITTED` to `UNDER_REVIEW`; this is legal only from `SUBMITTED`, and as a side effect the system recomputes `eligibility_basis` using the distance/hazard rule of §3.2, landing on `DISTANCE`, `HAZARD`, or `NONE`. From `UNDER_REVIEW` the admin may request changes, moving the application to `CHANGES_REQUESTED`; this is legal only from `UNDER_REVIEW` and has no further side effect. The owning `Parent` may then resubmit, returning the application from `CHANGES_REQUESTED` to `UNDER_REVIEW`; this is legal only from `CHANGES_REQUESTED` and only when the acting parent owns the student (the parent's `X-User-ID` equals the student's `parent_id`). Resubmission increments `review_round` by one, may update `requested_route_id` and/or `requested_stop_id` from the resubmit body, and recomputes `eligibility_basis`. This forms a cyclic revision loop: an application may bounce between `UNDER_REVIEW` and `CHANGES_REQUESTED` any number of times before it is decided.

From `UNDER_REVIEW` the admin reaches a decision. Denial moves the application from `UNDER_REVIEW` to `DENIED`, sets `denial_reason` from the body (one of `INELIGIBLE`, `ROUTE_FULL`, `WHEELCHAIR_FULL`, or `ROUTE_NOT_OPEN`), and appends an application-decision parent notification recording the `DENIED` decision for the student's parent. A parent may also `WITHDRAW` their own application: withdrawal is legal from `SUBMITTED` and from `CHANGES_REQUESTED`, requires the acting parent to own the student, and moves the application to `WITHDRAWN` with no further effect. The statuses `APPROVED`, `DENIED`, and `WITHDRAWN` are terminal.

### 3.4. Approving a Rider: the Capacity Gauntlet

Approval is the most heavily guarded transition in the application lifecycle and is reserved for a `TransportAdmin`. It is legal only from `UNDER_REVIEW`; attempting it from any other status yields `ERR_INVALID_STATE`. Beyond legality, approval enforces a chain of business checks, evaluated in this order so that the earliest-failing condition is the one reported.

First, the applicant must be eligible: the `eligibility_basis` must be either `DISTANCE` or `HAZARD`. If it is `NONE`, approval is rejected with `ERR_NOT_ELIGIBLE`. Second, the requested route must be fully open for new ridership: its posture must be `OPEN`. If the route is `RESTRICTED` or `SUSPENDED`, approval is rejected with `ERR_ROUTE_NOT_OPEN` — a `RESTRICTED` route continues to serve its existing riders but accepts no new assignment. Third, the route must have a free seat: its `assigned_rider_count` must be strictly less than its `seat_capacity`; if the count has reached capacity, approval is rejected with `ERR_ROUTE_FULL`. Fourth, and only when the subject student has `special_needs` set to true, the route must also have a free securement position: its `assigned_wheelchair_count` must be strictly less than its `wheelchair_capacity`; if not, approval is rejected with `ERR_WHEELCHAIR_FULL`.

When all four checks pass, the application moves from `UNDER_REVIEW` to `APPROVED`. The system sets `assigned_route_id` equal to `requested_route_id` and `assigned_stop_id` equal to `requested_stop_id`, both captured at approval time. The target route's `assigned_rider_count` is recomputed and rises by one, and if the student is special-needs the route's `assigned_wheelchair_count` is likewise recomputed and rises by one. Finally, an application-decision parent notification recording the `APPROVED` decision is appended for the student's parent.

### 3.5. Drivers, Assignments, and the Substitute Chain

A **Driver** belongs to a district through `district_id`, carries a `full_name`, and an `is_substitute` flag (default false) marking a driver who may hold only substitute assignments. A driver's `status` starts at `AVAILABLE` and becomes `ON_DUTY` when a trip they drive starts boarding, and it returns to `AVAILABLE` only when that trip completes, is cancelled, or is cancelled by a route-suspension cascade. Driver status is set solely by those transitions: once `ON_DUTY`, the driver stays `ON_DUTY` across departures and across an `INCIDENT_HOLD` and its clearing, and neither raising nor clearing an incident changes the driver's status. Drivers can be listed filtered by `district_id` and `status`.

A **DriverAssignment** binds a driver to a route. It carries the `route_id`, the `driver_id`, a `role` that defaults to `PRIMARY`, and — for substitutes — a `replaces_assignment_id` naming the primary assignment being covered. Its `status` starts `ACTIVE`. Creating an assignment is an admin-only operation against the route, and because it is version-guarded, the request must include `expected_route_version` (see §2.10) and creation increments the route's `version` by one. Assignments can be listed filtered by `route_id`, `driver_id`, `replaces_assignment_id`, and `status`.

The substitute rules are strict. A `SUBSTITUTE` assignment must name a `replaces_assignment_id` that resolves to an assignment that is both `ACTIVE` and of role `PRIMARY` on the *same* route; for a `PRIMARY` assignment the `replaces_assignment_id` is absent. Furthermore, a driver flagged `is_substitute` may never hold a `PRIMARY` assignment. Any violation of these conditions — a missing or invalid replaces target, a replaced assignment that is not an active primary on the same route, or a substitute-only driver assigned as primary — is rejected with `ERR_SUBSTITUTE_RULE`. When a valid substitute is created, the named primary assignment transitions from `ACTIVE` to `SUPERSEDED`, while the newly created substitute itself remains `ACTIVE`; this forms a self-referential substitute chain in which each substitute points back at the assignment it covers.

### 3.6. Scheduling and Running a Bus Trip

A **BusTrip** is scheduled by a `TransportAdmin` against a route by supplying the `route_id` and the `driver_assignment_id` of the active assignment whose driver will run the trip. At scheduling time the named `driver_assignment_id` must resolve and must belong to the supplied `route_id`, otherwise the request is rejected with `ERR_INVALID_REFERENCE`; the assignment's `status` is not checked at scheduling — the `ACTIVE` requirement is enforced only later, at start-boarding. On creation the trip is `SCHEDULED`, its `service_day_index` is captured from the district's current counter, and its `current_stop_sequence` is 0. The trip also exposes the live GPS fields `last_lat` and `last_lng` (null until the first ping), the computed `eta_next_stop_minutes`, the computed `onboard_count`, and an `incident_count` that starts at 0. Trips can be listed filtered by `route_id`, `driver_assignment_id`, and `status`.

The acting `Driver` starts boarding a `SCHEDULED` trip to begin the run. This is legal only from `SCHEDULED`, and it carries several safety preconditions. The route's posture must be `OPEN` or `RESTRICTED`; a `SUSPENDED` route blocks boarding with `ERR_ROUTE_NOT_OPEN`. The acting driver must be the driver named by the trip's `driver_assignment_id`. That assignment's `status` must be `ACTIVE`, or boarding is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`. And the driver must not already be running another in-flight trip — no other bus trip with the same driver may be in `BOARDING` or `IN_TRANSIT` — because a driver occupies at most one in-flight slot at a time; a second concurrent trip is rejected with `ERR_DRIVER_DOUBLE_BOOKED`. On success the trip moves from `SCHEDULED` to `BOARDING`, `current_stop_sequence` is set to 1 (the first stop), and the driver's `status` becomes `ON_DUTY`.

The driver then progresses the trip stop by stop by departing the current stop, supplying the `stop_sequence` of the stop being left, which must equal the trip's `current_stop_sequence`. The first such departure carries the trip from `BOARDING` to `IN_TRANSIT`; each subsequent departure is a self-loop that keeps the trip `IN_TRANSIT`, permitted only while the current stop is not the route's final stop. On every departure, `current_stop_sequence` advances to the next stop's sequence on the route (the smallest sequence strictly greater than the current one), and `eta_next_stop_minutes` is recomputed. When the trip has reached the final stop's sequence, the driver completes the trip, which is legal only from `IN_TRANSIT`, only when `current_stop_sequence` equals the route's final stop sequence, and only when `onboard_count` is exactly 0 — a trip with riders still aboard is rejected with `ERR_RIDERS_STILL_ONBOARD`. Completion moves the trip to `COMPLETED`, sets `eta_next_stop_minutes` to null, and returns the driver to `AVAILABLE`. A `TransportAdmin` may instead cancel a still-`SCHEDULED` trip; this is legal only from `SCHEDULED`, moves it to `CANCELLED`, and frees its driver back to `AVAILABLE` if the driver was `ON_DUTY` for that trip. Both `COMPLETED` and `CANCELLED` are terminal.

The trip's arrival estimate is produced by a forward-looking calculation that targets the next undeparted stop — the stop on the route whose sequence equals the trip's `current_stop_sequence`. The estimate is computed only while the trip is `BOARDING` or `IN_TRANSIT`; in every other status (`SCHEDULED`, `INCIDENT_HOLD`, `COMPLETED`, or `CANCELLED`) `eta_next_stop_minutes` is null even when a GPS ping has been recorded. If there is no such stop (the current sequence has moved past the final stop), `eta_next_stop_minutes` is null. Otherwise the system measures the straight-line haversine distance in miles, using the same Earth radius of 3958.7613 miles, from a measurement origin to that next stop's coordinates, divides that distance by an assumed average speed of 25.0 miles per hour, multiplies by 60 to convert hours to minutes, and rounds the result half-up to one decimal place. The measurement origin depends on what telemetry exists: once a GPS ping has been recorded (the trip's `last_lat` and `last_lng` are set), the origin is those actual last-ping coordinates; before any ping has arrived but while the trip is `BOARDING` or `IN_TRANSIT`, the origin is the coordinates of the previously departed stop, or the campus for the first stop, with the same speed constant applied. A `Driver` reports a GPS ping for their own trip by supplying `lat` and `lng`; the ping updates `last_lat` and `last_lng` and recomputes the ETA using the GPS-based origin.

The onboard tally is a projection over the trip's tap log rather than a directly stored number. To compute `onboard_count`, the system replays every tap event for the trip in ascending `created_at` order — implemented as ascending order of a monotonic per-process insertion sequence that rises in lockstep with `created_at`, so that two events sharing the same millisecond `created_at` are ordered by the order in which they were recorded — and then by ascending `stop_sequence`, never by id: each `TAP_ON` adds the student to the onboard set and each `TAP_OFF` removes them, and the resulting set size is the count. This replay is re-evaluated on every tap, is read whenever the trip is fetched, and is the value the completion guard inspects.

### 3.7. RFID Taps and the Incident Fork

A **TapEvent** is an append-only record written by the acting `Driver` of a trip when a student taps their card. The driver supplies the `rfid_uid` that was tapped, the `direction` (`TAP_ON` or `TAP_OFF`), and the `stop_sequence` at which the tap occurred, which must equal the trip's `current_stop_sequence`; a `stop_sequence` that does not equal the trip's `current_stop_sequence` is rejected with `ERR_INVALID_STATE`. The system resolves the `rfid_uid` to a student — searching only among students of the district that owns this trip's route, where `rfid_uid` is unique — and records the resolved `student_id` and the trip's `bus_trip_id` on the event; an `rfid_uid` that resolves to no such student is rejected with `ERR_INVALID_REFERENCE`. The resolution and `stop_sequence` checks are evaluated before the two rider rules, with `rfid_uid` resolution first and the `stop_sequence` check second. Two rider rules gate a tap. The tapped student must have an `APPROVED` ridership application whose `assigned_route_id` is this trip's route; a student with no such assignment is rejected with `ERR_NOT_ASSIGNED_RIDER`. And the tap must respect onboard ordering: a `TAP_OFF` requires a prior unmatched `TAP_ON` for that student on this trip, and a `TAP_ON` requires that the student is not already onboard; either violation is rejected with `ERR_TAP_SEQUENCE`. Each accepted tap recomputes the trip's `onboard_count` and appends a parent notification of kind `TAP_ON` or `TAP_OFF` for the tapped student's parent. Tap events can be fetched individually or listed filtered by `bus_trip_id`, `student_id`, and `direction`; tap-event reads are not ownership-scoped for any authorized role, so a `Parent` may fetch or list any tap event and the result is not implicitly narrowed to that parent's own students.

The incident fork interrupts a running trip. From either `BOARDING` or `IN_TRANSIT`, the acting `Driver` may raise an incident, moving the trip to `INCIDENT_HOLD`. Raising an incident increments the trip's `incident_count` by one, recomputes the route's `open_incident` flag to true, and appends a parent notification of kind `INCIDENT` for every student currently onboard the bus. A `TransportAdmin` later clears the incident, returning the trip from `INCIDENT_HOLD` to `IN_TRANSIT` and recomputing the route's `open_incident` flag, which becomes false only when no other `INCIDENT_HOLD` trip remains on the route. Each of these transitions is legal only from the status named as its source; an attempt from any other status is rejected with `ERR_INVALID_STATE`.

### 3.8. Route Posture as the Master Gate

A route's **posture** is the master switch that gates both ridership assignment and trip operations, and only a `TransportAdmin` may change it. Every posture change is version-guarded and must carry `expected_route_version`; a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.10, and every successful change increments the route's `version` by one. Posture is changed by an `action` of `RESTRICT`, `REOPEN`, or `SUSPEND`.

Restricting takes a route from `OPEN` to `RESTRICTED`; this is legal only from `OPEN`. While `RESTRICTED`, existing riders and running trips are preserved but no new ridership application may be approved onto the route — the approval gate of §3.4 enforces this. Reopening returns a route to `OPEN`: it is legal from `RESTRICTED` and from `SUSPENDED`, in both cases landing on `OPEN`. Suspending takes a route to `SUSPENDED` from either `OPEN` or `RESTRICTED`. Suspension is gated by a safety rule: it is refused while any bus trip on the route is in `BOARDING` or `IN_TRANSIT`, with `ERR_TRIP_IN_FLIGHT`. When suspension proceeds, it cascades as described in §2.5: every `SCHEDULED` trip on the route is driven to `CANCELLED`, and each such trip's driver is returned to `AVAILABLE` if it was `ON_DUTY` for that trip. Any posture transition attempted from a status other than the one it is defined for is rejected with `ERR_INVALID_STATE`.

### 3.9. The Missed-Bus Protocol

When a student misses their bus, a `Parent` (for their own student) or a `TransportAdmin` files a **MissedBusReport** carrying the `district_id`, the `student_id`, the missed `bus_trip_id`, and the `reported_stop_sequence` where the student should have boarded. The `district_id`, `student_id`, and `bus_trip_id` body references are resolved first, with any that does not resolve rejected with `ERR_INVALID_REFERENCE`; only after they resolve is the parent-ownership check applied (because it reads the resolved student's `parent_id`), so a `Parent` filing for a student they do not own surfaces `ERR_INVALID_REFERENCE` ahead of `ERR_FORBIDDEN` whenever one of those references fails to resolve, and surfaces `ERR_FORBIDDEN` only once they all resolve. Filing is gated by a three-part window test, all parts of which must hold or the report is rejected with `ERR_MISSED_BUS_WINDOW`. The three-part test presupposes that a stop on the trip's route has a sequence equal to `reported_stop_sequence`; if the trip's route has no such stop the filing is rejected with `ERR_INVALID_REFERENCE` before the window test runs. First, the report must be timely: against the stop on the trip's route whose sequence equals `reported_stop_sequence`, the deadline is that stop's `scheduled_departure` plus the district's `missed_bus_grace_minutes`, and the current server clock must be at or before that deadline — a clock reading exactly equal to the deadline is still inside the window. Second, the bus must actually have departed that stop: the trip's `current_stop_sequence` must be greater than `reported_stop_sequence`, or the trip must be `COMPLETED`. Third, the student must not already have boarded: no `TAP_ON` event may exist for that student on that trip. When accepted, the report is created in `OPEN` status with its `resolution` field null until a later resolve sets it, and a parent notification of kind `MISSED_BUS` is appended.

A `TransportAdmin` runs the report through its linear lifecycle. Acknowledging an `OPEN` report moves it to `ACKNOWLEDGED` (legal only from `OPEN`). Resolving an `ACKNOWLEDGED` report moves it to `RESOLVED` (legal only from `ACKNOWLEDGED`) and sets its `resolution` from the body to either `PARENT_PICKUP` or `REBOARDED_NEXT_TRIP`. `RESOLVED` is terminal. Reports can be fetched individually or listed filtered by `district_id`, `student_id`, `bus_trip_id`, and `status`; when the acting role is `Parent`, fetching a report whose student is not owned by that parent is rejected with `ERR_FORBIDDEN`, and a parent's list is implicitly restricted to reports about their own students regardless of the supplied filters.

### 3.10. Parent Notifications

A **ParentNotification** is an append-only record the system emits to keep guardians informed; parents never create them directly. Each notification records the `district_id`, the recipient `parent_id`, the subject `student_id`, the triggering `bus_trip_id` (null for application-decision notices), a `kind`, and a free-form `payload` body carrying contextual details such as the stop sequence, the estimated minutes, or the decision. The `kind` is one of `TAP_ON`, `TAP_OFF`, `MISSED_BUS`, `INCIDENT`, or `APPLICATION_DECISION`, each emitted by the correspondingly named transition or side effect: a tap emits `TAP_ON` or `TAP_OFF` to the tapped student's parent; raising an incident emits `INCIDENT` to every onboard student's parent; filing a missed-bus report emits `MISSED_BUS`; and an application decision emits `APPLICATION_DECISION` with the decision in the payload. Notifications can be fetched individually or listed filtered by `district_id`, `parent_id`, `student_id`, `bus_trip_id`, and `kind`; when the acting role is `Parent`, fetching a notification whose `parent_id` is not the acting parent is rejected with `ERR_FORBIDDEN`, and a parent's list is implicitly restricted to notifications whose `parent_id` is the acting parent regardless of the supplied filters.

### 3.11. The Service-Day Clock

Two distinct clocks drive time-sensitive behavior. The district's `service_day_index` is a logical ops-epoch counter advanced one step at a time by an admin-only advance-service-day capability; each bus trip captures the district's current `service_day_index` at the moment it is scheduled. Separately, the missed-bus window test consults the server's wall-clock current UTC time, which in tests is controlled by an admin-only clock-setting capability that accepts a `to_iso8601` instant and sets the server's current UTC clock to it. The two are independent: advancing the service day does not move the wall clock, and setting the wall clock does not advance the service day.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, including state-machine transitions and counter advances, return a `200 OK` status code. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/districts` | Create a district | TransportAdmin |
| GET | `/districts/{district_id}` | Get a district | TransportAdmin, Parent, Driver |
| POST | `/districts/{district_id}/advance-service-day` | Advance the district service-day epoch | TransportAdmin |
| POST | `/routes` | Create a route | TransportAdmin |
| GET | `/routes` | List routes (filter by district_id, posture) | TransportAdmin, Parent, Driver |
| GET | `/routes/{route_id}` | Get a route | TransportAdmin, Parent, Driver |
| POST | `/routes/{route_id}/posture` | Change route posture (RESTRICT, REOPEN, SUSPEND) | TransportAdmin |
| POST | `/stops` | Add a stop to a route | TransportAdmin |
| GET | `/stops` | List stops (filter by route_id) | TransportAdmin, Parent, Driver |
| GET | `/stops/{stop_id}` | Get a stop | TransportAdmin, Parent, Driver |
| POST | `/students` | Register a student | TransportAdmin, Parent |
| GET | `/students/{student_id}` | Get a student | TransportAdmin, Parent |
| GET | `/students` | List students (filter by district_id, parent_id) | TransportAdmin, Parent |
| POST | `/ridership-applications` | Submit a ridership application | TransportAdmin, Parent |
| GET | `/ridership-applications/{application_id}` | Get a ridership application | TransportAdmin, Parent |
| GET | `/ridership-applications` | List ridership applications | TransportAdmin, Parent |
| POST | `/ridership-applications/{application_id}/start-review` | Begin review (computes eligibility) | TransportAdmin |
| POST | `/ridership-applications/{application_id}/request-changes` | Request changes from the parent | TransportAdmin |
| POST | `/ridership-applications/{application_id}/resubmit` | Parent resubmits | Parent |
| POST | `/ridership-applications/{application_id}/approve` | Approve and assign the rider | TransportAdmin |
| POST | `/ridership-applications/{application_id}/deny` | Deny the application | TransportAdmin |
| POST | `/ridership-applications/{application_id}/withdraw` | Parent withdraws the application | Parent |
| POST | `/drivers` | Create a driver | TransportAdmin |
| GET | `/drivers/{driver_id}` | Get a driver | TransportAdmin, Driver |
| GET | `/drivers` | List drivers (filter by district_id, status) | TransportAdmin, Driver |
| POST | `/routes/{route_id}/driver-assignments` | Assign a driver to a route (PRIMARY or SUBSTITUTE) | TransportAdmin |
| GET | `/driver-assignments/{assignment_id}` | Get a driver assignment | TransportAdmin, Driver |
| GET | `/driver-assignments` | List driver assignments | TransportAdmin, Driver |
| POST | `/bus-trips` | Schedule a bus trip on a route | TransportAdmin |
| GET | `/bus-trips/{bus_trip_id}` | Get a bus trip (with ETA and onboard count) | TransportAdmin, Parent, Driver |
| GET | `/bus-trips` | List bus trips | TransportAdmin, Parent, Driver |
| POST | `/bus-trips/{bus_trip_id}/gps` | Report a GPS ping for a trip | Driver |
| POST | `/bus-trips/{bus_trip_id}/start-boarding` | Start boarding at the first stop | Driver |
| POST | `/bus-trips/{bus_trip_id}/depart-stop` | Depart the current stop, advancing to the next | Driver |
| POST | `/bus-trips/{bus_trip_id}/raise-incident` | Raise an incident hold on the trip | Driver |
| POST | `/bus-trips/{bus_trip_id}/clear-incident` | Clear an incident hold (returns to IN_TRANSIT) | TransportAdmin |
| POST | `/bus-trips/{bus_trip_id}/complete` | Complete the trip (requires onboard count 0) | Driver |
| POST | `/bus-trips/{bus_trip_id}/cancel` | Cancel a SCHEDULED trip | TransportAdmin |
| POST | `/bus-trips/{bus_trip_id}/taps` | Record an RFID tap on/off | Driver |
| GET | `/tap-events/{tap_event_id}` | Get a single tap event | TransportAdmin, Parent, Driver |
| GET | `/tap-events` | List tap events (filter by bus_trip_id, student_id, direction) | TransportAdmin, Parent, Driver |
| GET | `/parent-notifications/{notification_id}` | Get a single parent notification | TransportAdmin, Parent |
| GET | `/parent-notifications` | List parent notifications | TransportAdmin, Parent |
| POST | `/missed-bus-reports` | File a missed-bus report | TransportAdmin, Parent |
| GET | `/missed-bus-reports/{report_id}` | Get a missed-bus report | TransportAdmin, Parent |
| GET | `/missed-bus-reports` | List missed-bus reports | TransportAdmin, Parent |
| POST | `/missed-bus-reports/{report_id}/acknowledge` | Acknowledge an open report | TransportAdmin |
| POST | `/missed-bus-reports/{report_id}/resolve` | Resolve an acknowledged report | TransportAdmin |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC clock | TransportAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_STOP_TIME_ORDER` | 422 |
| `ERR_DRIVER_DOUBLE_BOOKED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TRIP_IN_FLIGHT` | 409 |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_SUBSTITUTE_RULE` | 409 |
| `ERR_RIDERS_STILL_ONBOARD` | 409 |
| `ERR_NOT_ASSIGNED_RIDER` | 409 |
| `ERR_TAP_SEQUENCE` | 409 |
| `ERR_NOT_ELIGIBLE` | 409 |
| `ERR_ROUTE_NOT_OPEN` | 409 |
| `ERR_ROUTE_FULL` | 409 |
| `ERR_WHEELCHAIR_FULL` | 409 |
| `ERR_MISSED_BUS_WINDOW` | 409 |
