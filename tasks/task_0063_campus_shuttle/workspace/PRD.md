# Campus Shuttle Dispatch API — Product Requirements Document

## 1. Introduction

University campuses operate dense, time-sensitive transit networks whose planning is rarely a clean optimisation problem: fixed-route loops must absorb peak-hour congestion, vehicle ledgers must respect maintenance windows, drivers must respect licensing expiry, employees expect predictable seat availability, and finance teams expect a defensible monthly accounting against every trip. The Campus Shuttle Dispatch API is the system of record that ties these concerns together. It captures every route version, every daily run, every reservation, every actual ridership scan, every delay event, and every cost line, so that operational decisions made in the morning rush remain auditable at month-end close.

The API is organised around four overlapping concerns: a planning surface (routes and stops), an operational surface (vehicles, drivers, daily run-sheets, delays), a passenger-facing surface (reservations, waitlists, check-in), and a financial surface (per-reservation fares, monthly bills, refunds). These surfaces are intentionally cross-referenced — promoting a route version retires its predecessor and propagates cancellations into pending runs and reservations; cancelling a billed reservation reaches into a finalized bill and writes a refund line; reporting a breakdown delay reaches into the vehicle ledger and selects a substitute. The contract below specifies every such cascade in deterministic, side-effect-explicit terms so that operators, drivers, employees, and auditors all see consistent state regardless of timing.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` (the acting principal's identifier) and `X-User-Role` (their operational capacity). If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING`. The system recognises four roles, spelled exactly as: `Dispatcher`, `Driver`, `Employee`, and `Auditor`. A header value outside this set is rejected with `ERR_INVALID_ROLE`. When a recognised role attempts an operation that the role-permission matrix does not grant it, the request is rejected with `ERR_FORBIDDEN`.

Role identity binds to persisted entities as follows:

- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` row; ownership checks on any resource that references a `Driver` (for example, `assigned_driver_id` on a daily run-sheet) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on an audit log entry that a state transition writes) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Employee`, `X-User-ID` is an opaque employee identifier carried through to the `employee_id` field on a new reservation and used to scope cancellation and listing of that employee's own reservations; it is not joined against a persisted Employee row in this system.
- When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque read-only operator identifier with the same recording semantics as `Dispatcher`.

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

List endpoints accept two query parameters. The `limit` parameter is an integer, defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` parameter is an integer, defaults to 0, with a minimum of 0. Any value outside these bounds, or any non-integer value, is rejected with `ERR_INVALID_PAGINATION`.

Unless an endpoint specifies otherwise, list responses are sorted by the resource's creation timestamp in ascending order. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All top-level resources (Route, Stop, Vehicle, Driver, RunSheet, Reservation, MonthlyBill) carry a standard set of system-managed fields:

- `id` is a server-minted UUID with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` is a non-negative integer that begins at 1 and increments by one on every mutation; it is used for optimistic concurrency control as described in §2.6.

Three entities are append-only or snapshot-style and accordingly carry only `id` and `created_at` (no `updated_at` and no `version`): `RouteVersion`, `RidershipRecord`, `DelayEvent`, and `AuditLog`. Their downstream attributes (for example, the `retired_at` stamp on a `RouteVersion`, the `alighted_at` stamp on a `RidershipRecord`, or the `notification_dispatched`/`substitute_dispatched` flags on a `DelayEvent`) may flip after creation as the result of cascades, but those changes do not increment a version counter on the snapshot itself.

### 2.5. Hierarchical Consistency and Side-Effect Propagation

Every state transition in this system can produce cascades into sibling and child entities. The server reconciles those cascades synchronously in the same request, in the order specified by the relevant state machine, and the resulting mutations refresh each affected entity's `updated_at` and increment its `version` (for entities that carry those fields). The reader should expect, for instance, that retiring an `ACTIVE` route version mutates not only the route row but every `PLANNED` run-sheet hanging off it, which in turn mutates every `CONFIRMED` or `WAITLISTED` reservation hanging off those runs, which in turn may mutate a `FINALIZED` monthly bill by appending a refund line. Each link in this chain is described in §3 in terms of the originating transition, and each downstream mutation is independent — there is no atomicity bypass that lets a parent transition while a stipulated child cascade is silently skipped.

When a downstream entity is in a state from which the cascade has no legal target, the cascade is a no-op for that entity but does not block the originating transition. For example, retiring a route whose only run-sheets are already `COMPLETED` mutates only the route and route-version rows.

### 2.6. Optimistic Concurrency Control

Endpoints that mutate a resource by id accept an optional `version` field in the request body. When present, the server compares it against the row's current `version` before applying the change; a mismatch is rejected with `ERR_VERSION_CONFLICT` and the row is not mutated. When the `version` field is omitted from the body, the server applies the mutation without an optimistic-concurrency check. This convention applies to every `PATCH` endpoint that targets a specific resource by its identifier in the path.

OCC is distinct from the route-publish race, which is governed by a different error: two dispatchers concurrently publishing a new version of the same `code` will see exactly one PUBLISH succeed; the loser is rejected with `ERR_ROUTE_VERSION_CONFLICT` because the predecessor row it observed has already been retired.

### 2.7. Nested Resource Retrieval

URL paths that contain multiple resource identifiers are validated left-to-right. A request that references a non-existent parent (for example, a run-sheet id that does not resolve) is rejected with `ERR_NOT_FOUND` before the server attempts to look up any child identifier or evaluate any body validation. Once path identifiers are resolved, request bodies that carry foreign-key references — `route_id`, `assigned_driver_id`, an optional `assigned_vehicle_id`, `boarding_stop_id`, `alighting_stop_id`, `reservation_id`, `start_stop_id`, `end_stop_id`, and entries in `intermediate_stop_ids` — are validated to point at existing rows; an unresolved body FK is rejected with `ERR_REFERENCE_NOT_FOUND`. State-transition preconditions (§3) are evaluated only after both existence checks pass.

### 2.8. Validation Priority

When more than one validation could apply to a request, the system evaluates them in a fixed order so that the rejection reason is deterministic:

1. Authentication header presence (`ERR_AUTH_MISSING`).
2. Role enumeration (`ERR_INVALID_ROLE`).
3. Role authorisation per the RBAC matrix (`ERR_FORBIDDEN`).
4. Path-id existence, left-to-right (`ERR_NOT_FOUND`).
5. Body-referenced foreign-key existence (`ERR_REFERENCE_NOT_FOUND`).
6. State-machine eligibility of the subject entity (`ERR_INVALID_STATE`).
7. Endpoint-specific business validations, themselves ordered: stop activation status at publish time (`ERR_STOP_NOT_ACTIVE`); vehicle maintenance occupation (`ERR_VEHICLE_HAS_BOOKED_RUNS`); driver licence currency (`ERR_DRIVER_LICENSE_EXPIRED`); employee cancel window (`ERR_CANCEL_WINDOW_CLOSED`); check-in window (`ERR_CHECKIN_WINDOW_CLOSED`); reservation stop-pair validity (`ERR_INVALID_STOP_PAIR`); employee daily reservation limit (`ERR_DAILY_LIMIT_EXCEEDED`); frequency-window structural rules (`ERR_INVALID_FREQUENCY_WINDOWS`); vehicle double-booking (`ERR_VEHICLE_DOUBLE_BOOKED`); driver double-booking (`ERR_DRIVER_DOUBLE_BOOKED`); capacity (`ERR_RUN_FULL`); route-code uniqueness (`ERR_DUPLICATE_ROUTE_CODE`); bill uniqueness (`ERR_BILL_ALREADY_EXISTS`).
8. Pagination parameter validity on list endpoints (`ERR_INVALID_PAGINATION`).
9. Optimistic-concurrency `version` check on mutating endpoints (`ERR_VERSION_CONFLICT`).

This ordering matters wherever two checks could simultaneously fire — for example, a non-existent run id with a body that also violates the stop-pair rule must return `ERR_NOT_FOUND`, not `ERR_INVALID_STOP_PAIR`.

### 2.9. Numerical Precision

Distance, duration, fare, and statistical computations all use round-half-up arithmetic. Specifically:

- Per-segment haversine distance is rounded to four decimal places, and the total distance of a route is the rounded-half-up sum of those segments to two decimal places.
- Duration estimates are ceilinged to the next whole minute.
- Fares are integer cents; the final multiplication step of fare calculation is rounded half-up before truncation to an integer.
- The ridership match-rate statistic is a float rounded half-up to four decimal places.
- Monthly bill aggregation operates only on integer cents and performs no further rounding.

### 2.10. Frequency Windows, Peak Periods, and Time Semantics

Every route declares its operational rhythm via `peak_frequency_minutes`, `offpeak_frequency_minutes`, and a `peak_windows` array. Each window in `peak_windows` is a `[HH:MM, HH:MM)` half-open local-time interval (start inclusive, end exclusive). The full peak-windows array must be sorted ascending, must not overlap, and successive windows must be separated by a gap of at least one minute; the peak headway must be no greater than the off-peak headway. Any structural violation — unsorted, overlapping, touching, or peak headway exceeding off-peak — is rejected with `ERR_INVALID_FREQUENCY_WINDOWS` both at route creation and at publish time. The peak headway must lie in the integer range from 5 through 60 inclusive, and the off-peak headway from 5 through 120 inclusive.

A run is considered "peak" when its `scheduled_departure`, projected onto the local time-of-day, falls inside at least one of its route version's snapshot `peak_windows`. This peak flag drives both the duration estimate variant and the fare multiplier described in §3.

### 2.11. Audit Trail

Selected state transitions append a row to the audit log with an `event_type` drawn from the set `RESERVATION_CREATED`, `RESERVATION_CANCELLED`, `RESERVATION_CHECKED_IN`, `RESERVATION_NO_SHOW`, `DELAY_REPORTED`, `SUBSTITUTE_DISPATCHED`, `ROUTE_PUBLISHED`, and `BILL_REFUNDED`. Each entry records the `subject_type` (one of `Reservation`, `RunSheet`, `Route`, `MonthlyBill`, `DelayEvent`), the `subject_id` of the affected row, the `actor_role` and `actor_id` taken from the request's `X-User-Role` and `X-User-ID`, and a free-form `payload` object containing structured details (the diff, reason code, or related ids). The audit log carries an `id` and `created_at` but no `updated_at` or `version`.

### 2.12. Test-Driving the Clock

A test-driving capability advances the system clock to a supplied `to_timestamp` ISO 8601 UTC instant. Advancing the clock fires deferred transitions in this order: vehicles whose `maintenance_window_end` is now less than or equal to the new clock instant transition from `MAINTENANCE` back to `ACTIVE`, with `maintenance_window_start` and `maintenance_window_end` cleared.

## 3. Business Logic & Workflows

### 3.1. Stops: Geographic Anchors of the Network

Every transit network begins with its stops. A `Dispatcher` registers a new stop in `DRAFT` status by providing its `code`, display `name`, `latitude`, `longitude`, an `amenities` array (zero or more of `LIGHTING`, `SEATING`, `USB`, `DISPLAY`, `RAMP`), a `has_shelter` flag (defaulting to false), and a `capacity_reference` integer between 1 and 500 inclusive that represents how many waiting riders the stop can hold without crowding. The latitude must satisfy at least -90 and at most 90, with up to six decimal places; the longitude must satisfy at least -180 and at most 180, with up to six decimal places. A stop's `code` must be unique among stops whose `status` is `ACTIVE`; `DRAFT` and `OFFSHELF` rows may reuse a code.

A `DRAFT` stop becomes available for inclusion in published routes by activation, which a `Dispatcher` initiates; the only precondition is that the row's coordinates and `capacity_reference` are populated. The transition pair is `DRAFT → ACTIVE`. Once activated, a stop can be taken off-shelf with the transition `ACTIVE → OFFSHELF` — but only if no `ACTIVE` route references it as its start stop, its end stop, or in its intermediate stop list; otherwise the request is rejected with `ERR_INVALID_STATE`. Off-shelf stops can be brought back via `OFFSHELF → ACTIVE` with no extra precondition. Retired route versions may continue to reference an off-shelf stop in their snapshot, but no new route may include it while it is off-shelf.

### 3.2. Routes: Versioned Service Definitions

A `Dispatcher` drafts a route by supplying its human-friendly `code` (uppercase, three to twelve characters, drawn from letters, digits, and the hyphen), a display `name`, a `start_stop_id`, an `end_stop_id`, an ordered `intermediate_stop_ids` list (possibly empty) of stops to visit between start and end, and the peak/off-peak `peak_frequency_minutes` / `offpeak_frequency_minutes` headways together with the `peak_windows` array. A new route is created in `DRAFT` and assigned `version_number` 1. The fields `estimated_distance_km` and `estimated_duration_minutes` are computed at publish time and are not accepted as input.

A `DRAFT` route may be edited in place by a `Dispatcher`, who supplies any subset of `name`, `start_stop_id`, `end_stop_id`, `intermediate_stop_ids`, `peak_frequency_minutes`, `offpeak_frequency_minutes`, `peak_windows`, and an optional `version` for OCC; `ACTIVE` and `RETIRED` routes are immutable, and an attempt to modify them is rejected with `ERR_INVALID_STATE`.

Publishing a route is the central event in route management: a `Dispatcher` promotes the route from `DRAFT` to `ACTIVE`. Four preconditions must hold. First, the `start_stop_id`, the `end_stop_id`, and every entry in `intermediate_stop_ids` must currently be in `ACTIVE` stop status; otherwise the publish is rejected with `ERR_STOP_NOT_ACTIVE`. Second, the peak headway must be no greater than the off-peak headway, and the `peak_windows` array must be sorted, half-open, non-overlapping, and separated by at least one minute between successive windows (`ERR_INVALID_FREQUENCY_WINDOWS` otherwise). Third, if another route with the same `code` is currently `ACTIVE`, that route is auto-retired in the same operation (see below); however, the precondition that no other concurrent publish has already retired the predecessor is enforced — two simultaneous publish attempts for the same `code` resolve to exactly one winner, and the loser is rejected with `ERR_ROUTE_VERSION_CONFLICT` because the predecessor it expected to retire has already been replaced. Fourth, a draft cannot be published if it would violate the `code` uniqueness rule and no predecessor exists to retire (`ERR_DUPLICATE_ROUTE_CODE`).

A successful publish performs five side-effects in this order. The route's `estimated_distance_km` is recomputed: starting from the ordered stop list `[start_stop, intermediate_stop_1, …, end_stop]`, the great-circle distance between each consecutive pair of stops is computed using the haversine formula on their `latitude` and `longitude` with an Earth radius of 6371.0088 kilometres, rounded half-up to four decimal places per segment, and the resulting per-segment distances are summed and then rounded half-up to two decimal places. The route's `estimated_duration_minutes` is then computed in the BASE variant: take the route's distance in kilometres, divide by the configured average speed of 25 kilometres per hour, multiply by 60 to express the travel time in minutes, add a one-minute dwell allowance per intermediate stop, and ceiling the result to a whole minute. A `RouteVersion` snapshot row is appended whose `route_code` matches the route's `code`, whose `version_number` is the largest prior `version_number` for that code plus one, and which freezes the `stop_sequence_snapshot` (the ordered start, intermediates, end), the `peak_frequency_minutes`, the `offpeak_frequency_minutes`, the `peak_windows`, and stamps `published_at` to the current instant with `retired_at` left null. If a prior `ACTIVE` route with the same `code` exists, its `status` is set to `RETIRED` and the corresponding `RouteVersion.retired_at` is stamped — and this retire-step in turn cascades: every `PLANNED` run-sheet on the prior route auto-transitions to `CANCELLED`, which in turn cancels each of those runs' `CONFIRMED` and `WAITLISTED` reservations, and any cancelled reservation that had already rolled into a `FINALIZED` monthly bill triggers a refund line. Finally, an audit entry of type `ROUTE_PUBLISHED` is recorded.

An explicit retire (`ACTIVE → RETIRED`) is also available to a `Dispatcher` and triggers the same cascade chain into pending run-sheets and reservations. The transition is not blocked by the presence of pending runs — those are auto-cancelled rather than refused.

The route `code` is unique only among `ACTIVE` routes: multiple `DRAFT` or `RETIRED` rows may share a code. A list of historical snapshots for a given route id is available via the route-versions list operation and is restricted to dispatchers and auditors.

### 3.3. Vehicles and Drivers: The Operational Roster

A `Dispatcher` registers a vehicle by providing its `plate_number`, an integer `seat_capacity` between 8 and 80 inclusive, and a `vehicle_type` drawn from `STANDARD`, `ELECTRIC`, and `SHUTTLE_VAN`. Vehicles begin in `ACTIVE` status. The `plate_number` is unique among vehicles whose `status` is `ACTIVE` or `MAINTENANCE` — retired plates may be reused. The system also tracks two maintenance-window fields, `maintenance_window_start` and `maintenance_window_end`, that are populated only while the vehicle is in `MAINTENANCE`, and a `last_run_completed_at` timestamp that reflects the latest completion of any run-sheet served by that vehicle (null until the first completion).

Starting maintenance is a `Dispatcher`-initiated transition `ACTIVE → MAINTENANCE` taking a `maintenance_window_start` and `maintenance_window_end` instant pair. Two preconditions apply: the supplied start must strictly precede the supplied end, and the vehicle must not be the `assigned_vehicle_id` of any run-sheet whose planned occupation window (defined as the half-open interval from `scheduled_departure` minus 15 minutes up to `scheduled_arrival` plus 15 minutes) overlaps the requested maintenance window, where the run-sheet is in `PLANNED`, `BOARDING`, `IN_TRANSIT`, or `DELAYED`. A failed second precondition surfaces as `ERR_VEHICLE_HAS_BOOKED_RUNS`. On success the supplied start and end are stamped onto the vehicle row.

Maintenance is closed either manually by a `Dispatcher` (transition `MAINTENANCE → ACTIVE`) with no further precondition, or automatically when the system clock advances past the recorded `maintenance_window_end` — in both cases the two maintenance-window fields are cleared.

Retiring a vehicle (`ACTIVE → RETIRED`) is permitted only when the vehicle is not the `assigned_vehicle_id` of any run-sheet in `PLANNED`, `BOARDING`, `IN_TRANSIT`, or `DELAYED`. Concurrent attempts to put the same `ACTIVE` vehicle into `MAINTENANCE` resolve to exactly one winner; the loser sees `ERR_INVALID_STATE` because the vehicle is no longer `ACTIVE`.

Drivers are onboarded by a `Dispatcher` with an HR-system `employee_code`, a `full_name`, and a `license_expiry_date`. A driver's `status` begins at `ACTIVE` and can be `SUSPENDED` or `OFFBOARDED`; the `employee_code` is unique among `ACTIVE` drivers. When a driver is assigned to a run-sheet, the `license_expiry_date` must be strictly after that run's `scheduled_departure`, otherwise the assignment is rejected with `ERR_DRIVER_LICENSE_EXPIRED`.

### 3.4. Daily Run-Sheets: From Planning to Completion

A daily run-sheet is the concrete realisation of a route on a specific calendar day. A `Dispatcher` creates a run-sheet by supplying the `route_id` of an `ACTIVE` route, a `scheduled_date` (UTC midnight), a `scheduled_departure` instant, an `assigned_driver_id`, and optionally an `assigned_vehicle_id`. At creation, the run-sheet pins `route_version_number` to the route's current `version_number`, computes `scheduled_arrival` from the route's `estimated_duration_minutes` using the PEAK_ADJUSTED variant (see below), and enters `PLANNED` status with a computed `capacity_remaining` equal to the assigned vehicle's `seat_capacity`. The `substitute_vehicle_id` is null until a substitute is dispatched; the `delay_minutes_accumulated` counter starts at zero; `completed_at` is null until the run completes.

The PEAK_ADJUSTED duration variant projects `scheduled_departure` onto the local time of day, and if that projection falls inside any peak window of the route version snapshot, the travel-time portion of the duration is multiplied by a peak factor of 1.25 (dwell time is not affected); otherwise the BASE variant is used. The resulting minute count is ceilinged to a whole minute and added to `scheduled_departure` to yield `scheduled_arrival`.

When `assigned_vehicle_id` is omitted, the system selects a vehicle automatically. The candidate set comprises every vehicle whose `status` is `ACTIVE`, whose maintenance window (defined by `maintenance_window_start` and `maintenance_window_end`, when populated) does not intersect the run's planned occupation window from `scheduled_departure` minus 15 minutes up to `scheduled_arrival` plus 15 minutes, and whose `seat_capacity` is at least the minimum-capacity floor of 20. Candidates are ranked in ascending order of `last_run_completed_at` — a null `last_run_completed_at` is treated as the earliest possible value so that previously-unused vehicles are picked first to spread rotation evenly. Ties are broken by ascending lexicographic order of `plate_number`. If the candidate set is empty, the request is rejected with `ERR_NO_VEHICLE_AVAILABLE`.

Two scheduling invariants are enforced. A vehicle must not be the `assigned_vehicle_id` of two run-sheets whose planned occupation windows (the closed-closed interval from `scheduled_departure` minus 15 minutes through `scheduled_arrival` plus 15 minutes) overlap; a violation surfaces as `ERR_VEHICLE_DOUBLE_BOOKED`. A driver must not be the `assigned_driver_id` of two run-sheets whose `[scheduled_departure, scheduled_arrival]` intervals are adjacent or overlapping under closed-open semantics: even a touching boundary (one run's end equal to another's start) counts as conflict and surfaces as `ERR_DRIVER_DOUBLE_BOOKED`. Both invariants apply to run-sheet creation, to run-sheet modification, and — for the vehicle invariant — to manual substitute dispatch.

A run-sheet progresses through the lifecycle pair `PLANNED → BOARDING → IN_TRANSIT → COMPLETED`, with optional `DELAYED` excursions along the way. Boarding is initiated by a `Driver` or `Dispatcher`; it requires that the assigned vehicle is currently `ACTIVE` (not `MAINTENANCE`, not `RETIRED`), and that the current instant lies within plus or minus 30 minutes of `scheduled_departure`. On `PLANNED → BOARDING` the system promotes as many `WAITLISTED` reservations on this run as the `capacity_remaining` allows, in ascending `waitlist_position` order, recomputing `capacity_remaining` after each promotion.

Departure (`BOARDING → IN_TRANSIT`) is initiated by a `Driver` or `Dispatcher` with no minimum-checked-in precondition. The act of departing automatically transitions every `CONFIRMED` reservation that has not checked in to `NO_SHOW`. Completion (`IN_TRANSIT → COMPLETED` or `DELAYED → COMPLETED`) is initiated by a `Driver` or `Dispatcher`; it stamps `completed_at` to the current instant, sets `last_run_completed_at` on the assigned vehicle (which in turn becomes the sort key for the next vehicle-rotation selection on that route), and auto-transitions every `CHECKED_IN` reservation on this run to `COMPLETED`.

Cancellation (`PLANNED → CANCELLED`) is initiated by a `Dispatcher` or arises as a cascade from retiring a route. Every `CONFIRMED` or `WAITLISTED` reservation on the run is cancelled in turn, and any cancelled `CONFIRMED` reservation already rolled into a `FINALIZED` monthly bill triggers a refund line on that bill.

### 3.5. Delays, Notifications, and Substitute Vehicles

A `Driver` or `Dispatcher` can report a delay against a run-sheet that is currently `PLANNED` or `IN_TRANSIT`. The request body supplies the `cause` (one of `TRAFFIC`, `BREAKDOWN`, `WEATHER`), an integer `delay_minutes` between 1 and 480 inclusive, and the `affected_from_stop_id` — the first downstream stop affected by this delay. A delay event row is appended with `reported_at` stamped to the current instant, `notification_dispatched` and `substitute_dispatched` both defaulting to false. The run-sheet transitions to `DELAYED` (from either `PLANNED` or `IN_TRANSIT`), its `delay_minutes_accumulated` is increased by the supplied `delay_minutes`, and its `scheduled_arrival` is pushed forward by the same `delay_minutes`.

Two threshold-triggered side-effects fire. When the cumulative `delay_minutes_accumulated` on the run reaches at least 30 minutes (counting the newly-appended event), the IM-system notification is dispatched and the newly-appended delay event's `notification_dispatched` is set to true. When the `cause` is `BREAKDOWN` and the run's `substitute_vehicle_id` is still null, the substitute-vehicle selector is invoked and, on success, the run's `substitute_vehicle_id` is set and the new delay event's `substitute_dispatched` is set to true. The substitute selector applies the same eligibility filter as the rotation selector except that it additionally excludes the run's currently-`assigned_vehicle_id` and any vehicle that is currently the `substitute_vehicle_id` of another active run. Ranking proceeds in two waterfall tiers: first, vehicles whose `seat_capacity` is greater than or equal to the run's currently-confirmed rider count form the compliant subset and are ranked by ascending `last_run_completed_at` with tie-breaking by ascending `plate_number`; if the compliant subset is empty, the largest non-compliant vehicle is selected by descending `seat_capacity` with tie-break by ascending `plate_number`, but only if the confirmed rider count does not exceed the candidate's `seat_capacity` by more than ten percent — once the overflow tolerance is exhausted the request is rejected with `ERR_NO_SUBSTITUTE_VEHICLE`.

A delayed run can be resumed (`DELAYED → IN_TRANSIT`) by a `Dispatcher`, or it can be completed directly (`DELAYED → COMPLETED`) with the same completion side-effects described above. A substitute vehicle may also be set manually by a `Dispatcher` via the substitute-dispatch capability, which takes a `vehicle_id` in the body; the same vehicle-double-booking invariant applies.

### 3.6. Reservations, Waitlists, Check-In, and Ridership

A reservation expresses an `Employee`'s intent to ride a specific run-sheet. The reservation creation body contains `employee_id`, `boarding_stop_id`, `alighting_stop_id`, `payer_mode` (one of `SELF_PAY` or `DEPARTMENT_PAID`), and an optional `department_code`. A `Dispatcher` may also create reservations on behalf of an employee. On creation the system first validates stop-pair correctness: both `boarding_stop_id` and `alighting_stop_id` must appear in the run's pinned `RouteVersion.stop_sequence_snapshot`, and the boarding stop must precede the alighting stop in that snapshot; otherwise the request is rejected with `ERR_INVALID_STOP_PAIR`. The system enforces the payer-mode coherence rule: when `payer_mode` is `DEPARTMENT_PAID` a `department_code` is required, and when `payer_mode` is `SELF_PAY` a `department_code` must not be supplied — either form of mismatch is rejected with `ERR_PAYER_MODE_MISMATCH`. The system also enforces a per-employee daily reservation limit of at most 3 non-cancelled reservations whose run-sheet `scheduled_date` is the same calendar day; an attempt to create a fourth such reservation is rejected with `ERR_DAILY_LIMIT_EXCEEDED`.

After validation, the fare for the new reservation is computed and pinned to `fare_cents`. The segment count between `boarding_stop_id` and `alighting_stop_id` on the snapshot determines a tier: 1 to 2 segments yields the base tier at 200 cents, 3 to 5 segments yields the base tier plus 100 cents, and 6 or more segments yields the base tier plus 200 cents. If the run's `scheduled_departure` projects into a peak window of the route version's `peak_windows`, the tier amount is multiplied by 1.5; otherwise it stands. The final integer-cents fare is then computed by rounding the multiplication result half-up to the nearest cent — the tier-then-peak order is fixed and pinned for forward compatibility with future per-tier multipliers. The reservation is placed in `CONFIRMED` status if the run has at least one seat of `capacity_remaining`, otherwise it is placed in `WAITLISTED` with a `waitlist_position` strictly greater than every existing waitlist position on the run (and null otherwise). Two simultaneous reservations on a run with exactly one seat left serialize to exactly one `CONFIRMED` winner; the loser receives `WAITLISTED` if waitlisting is admissible, otherwise the loser sees `ERR_RUN_FULL`. An audit entry of type `RESERVATION_CREATED` is recorded. The `no_show_penalty_points` and `cancelled_at` fields begin at zero and null respectively.

Cancellation is initiated by the owning `Employee` or by a `Dispatcher`. Employee-triggered cancellation requires that the current instant is at or before the run's `scheduled_departure` minus 15 minutes; an attempt later than that surfaces as `ERR_CANCEL_WINDOW_CLOSED`. A cancel on a `CONFIRMED` reservation stamps `cancelled_at`, frees a seat on the run's `capacity_remaining`, and — if any `WAITLISTED` reservation exists on the same run and the run is still in `PLANNED` — promotes the lowest `waitlist_position` to `CONFIRMED`. A cancel on a `WAITLISTED` reservation simply removes the row and renumbers the remaining waitlist positions by decrementing every position strictly greater than the one removed. If a cancelled `CONFIRMED` reservation has already been rolled into a `FINALIZED` monthly bill, the bill's `refund_cents` is incremented by this reservation's `fare_cents` and the bill auto-transitions to `REFUNDED`; an audit entry of type `RESERVATION_CANCELLED` is recorded. An attempt by a driver to check in a reservation while the employee simultaneously cancels resolves to exactly one winner: if cancel commits first, the check-in fails with `ERR_INVALID_STATE`; if check-in commits first, the cancel fails with `ERR_RESERVATION_ALREADY_CHECKED_IN`. A second cancel arriving for an already-cancelled reservation is rejected idempotently with `ERR_INVALID_STATE`.

Check-in is initiated by a `Driver` (typically) or a `Dispatcher`. The body supplies `reservation_id`, `check_in_method` (one of `QR`, `CARD`, `FACE`), and `boarded_stop_id`. Preconditions: the run-sheet is in `BOARDING`, `IN_TRANSIT`, or `DELAYED`, and the current instant lies in the half-open interval from `scheduled_departure` minus 30 minutes up to `scheduled_arrival` plus 60 minutes; otherwise the check-in is rejected with `ERR_CHECKIN_WINDOW_CLOSED`. Successful check-in transitions the reservation `CONFIRMED → CHECKED_IN`, creates a `RidershipRecord` row capturing `reservation_id`, `run_sheet_id`, `employee_id` (copied from the reservation for fast filtering), the supplied `check_in_method` and `boarded_stop_id`, the current instant as `boarded_at`, and leaves `alighted_stop_id` and `alighted_at` null. An audit entry of type `RESERVATION_CHECKED_IN` is recorded. The departure cascade — every `CONFIRMED` reservation that did not check in transitions to `NO_SHOW` — assigns each affected reservation a `no_show_penalty_points` value computed as follows: start at a base of 10; add 5 if the run's `scheduled_departure` projects into a peak window; subtract 3 if the run's `delay_minutes_accumulated` at departure is at least 30 (a partial mitigation for delays that contributed to the missed run); add 2 for each prior `NO_SHOW` reservation by the same employee whose run's `scheduled_departure` falls in the trailing 30-day window exclusive of this run; floor the result at zero so the value can never go negative. An audit entry of type `RESERVATION_NO_SHOW` is recorded. A `NO_SHOW` reservation remains chargeable; the corresponding fare is not refunded.

When a run completes from `IN_TRANSIT` or `DELAYED`, every `CHECKED_IN` reservation on that run transitions to `COMPLETED`. As part of that completion, each associated `RidershipRecord` has its `alighted_at` stamped to the current instant if not already set, and its `alighted_stop_id` defaulted to the reservation's `alighting_stop_id`. A `Driver` or `Dispatcher` can also record an alighting earlier than completion via the ridership-update capability, which accepts a body `alighted_stop_id` and stamps `alighted_at` to the current instant.

### 3.7. Ridership Statistics

A `Dispatcher` or `Auditor` can retrieve summary statistics for a run-sheet. The response carries three counts and a rate. The `ridership_actual` count is the number of `RidershipRecord` rows whose `run_sheet_id` is this run. The `ridership_expected` count is the number of reservations on this run whose `status` is in `CHECKED_IN`, `COMPLETED`, or `NO_SHOW`; `WAITLISTED` reservations never enter the statistic. The `no_show_count` is the number of reservations on this run whose `status` is `NO_SHOW`. The `match_rate` is the actual ridership count divided by the maximum of the expected count and 1, rendered as a float rounded half-up to four decimal places.

### 3.8. Monthly Billing and Settlement

A `Dispatcher` opens a draft monthly bill by supplying a `billing_month` (a string matching the four-digit year, hyphen, two-digit month form, the month between 01 and 12), a `payer_scope` (`EMPLOYEE` or `DEPARTMENT`), and a `payer_id` that is either the `employee_code` when scope is `EMPLOYEE` or the `department_code` when scope is `DEPARTMENT`. At most one bill may exist for any (`payer_scope`, `payer_id`, `billing_month`) triple — a duplicate is rejected with `ERR_BILL_ALREADY_EXISTS`. Two simultaneous creations against the same triple resolve to exactly one winner; the loser sees `ERR_BILL_ALREADY_EXISTS`. The new bill enters `DRAFT` with `gross_cents`, `net_cents`, and `line_count` all unpinned; `refund_cents` starts at zero; `finalized_at` is null.

A draft is finalised (`DRAFT → FINALIZED`) by a `Dispatcher` once two preconditions hold. First, the `billing_month` must be strictly before the current UTC month; an attempt to finalise the current or a future month is rejected with `ERR_BILLING_MONTH_NOT_COMPLETE`. Second, every reservation in the bill's scope must already be in a terminal state — that is, `COMPLETED`, `NO_SHOW`, or `CANCELLED`; any in-scope reservation still in a non-terminal state surfaces as `ERR_BILL_HAS_OPEN_RESERVATIONS`. The in-scope reservations for an `EMPLOYEE`-scoped bill are those whose `employee_id` equals the bill's `payer_id`, whose `payer_mode` is `SELF_PAY`, whose `status` is in `COMPLETED` or `NO_SHOW` (`CANCELLED` reservations are excluded from gross), and whose run-sheet `scheduled_date` falls in the `billing_month` interpreted as UTC. The in-scope reservations for a `DEPARTMENT`-scoped bill are those whose `department_code` equals the bill's `payer_id`, whose `payer_mode` is `DEPARTMENT_PAID`, whose `status` is in `COMPLETED` or `NO_SHOW`, and whose `scheduled_date` falls in the same UTC `billing_month`. The bill's `line_count` is set to the number of in-scope reservations; the bill's `gross_cents` is the integer-cent sum of the `fare_cents` of those reservations, with no further rounding because each line is already an integer; `finalized_at` is stamped to the current instant.

While a bill is `FINALIZED`, any cancellation of an in-scope `CONFIRMED` reservation (already counted in `gross_cents`) adds its `fare_cents` to the bill's `refund_cents` and transitions the bill `FINALIZED → REFUNDED`; an audit entry of type `BILL_REFUNDED` is recorded. Settlement (`FINALIZED → SETTLED` or `REFUNDED → SETTLED`) is initiated by a `Dispatcher`. The `FINALIZED → SETTLED` path requires that no pending cancel events remain to apply; both settlement paths pin `net_cents` to `gross_cents` minus `refund_cents` at settlement time.

## 4. Endpoint Definitions

Operations that create a new resource (a route, a stop, a vehicle, a driver, a run-sheet, a reservation, a check-in, a delay event, a bill) return HTTP 201 Created. Operations that modify an existing resource — including state-transition actions, list reads, and detail reads — return HTTP 200 OK.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/shuttle/routes` | Create a DRAFT route. | Dispatcher |
| GET | `/shuttle/routes` | List routes with optional status filter; supports pagination. | Dispatcher, Driver, Employee, Auditor |
| GET | `/shuttle/routes/{id}` | Get one route including computed distance/duration. | Dispatcher, Driver, Employee, Auditor |
| PATCH | `/shuttle/routes/{id}` | Edit a DRAFT route (RETIRED/ACTIVE are immutable; create a new version instead). | Dispatcher |
| POST | `/shuttle/routes/{id}/publish` | Publish a DRAFT route, retiring any prior ACTIVE route with the same code. | Dispatcher |
| POST | `/shuttle/routes/{id}/retire` | Retire an ACTIVE route; cascades into PLANNED runs and reservations. | Dispatcher |
| GET | `/shuttle/routes/{id}/versions` | List RouteVersion snapshots for a route code. | Dispatcher, Auditor |
| POST | `/shuttle/stops` | Create a DRAFT stop. | Dispatcher |
| GET | `/shuttle/stops` | List stops with optional status filter. | Dispatcher, Driver, Employee, Auditor |
| POST | `/shuttle/stops/{id}/activate` | Bring a stop on-shelf (DRAFT->ACTIVE or OFFSHELF->ACTIVE). | Dispatcher |
| POST | `/shuttle/stops/{id}/offshelf` | Take a stop off-shelf; rejected if referenced by ACTIVE routes. | Dispatcher |
| POST | `/shuttle/vehicles` | Register a vehicle (ACTIVE). | Dispatcher |
| GET | `/shuttle/vehicles` | List vehicles. | Dispatcher, Driver, Auditor |
| POST | `/shuttle/vehicles/{id}/maintenance` | Start a maintenance window. | Dispatcher |
| POST | `/shuttle/vehicles/{id}/maintenance-complete` | Manually end maintenance early. | Dispatcher |
| POST | `/shuttle/drivers` | Onboard a driver. | Dispatcher |
| GET | `/shuttle/drivers` | List drivers. | Dispatcher, Auditor |
| POST | `/shuttle/run-sheets` | Create a daily run-sheet on an ACTIVE route; vehicle auto-selected when assigned_vehicle_id is omitted. | Dispatcher |
| GET | `/shuttle/run-sheets` | List run-sheets with filters. | Dispatcher, Driver, Employee, Auditor |
| GET | `/shuttle/run-sheets/{id}` | Get a run-sheet including capacity_remaining. | Dispatcher, Driver, Employee, Auditor |
| POST | `/shuttle/run-sheets/{id}/start-boarding` | Transition PLANNED -> BOARDING; promotes waitlist. | Dispatcher, Driver |
| POST | `/shuttle/run-sheets/{id}/depart` | Transition BOARDING -> IN_TRANSIT; auto-marks no-shows. | Dispatcher, Driver |
| POST | `/shuttle/run-sheets/{id}/complete` | Transition IN_TRANSIT/DELAYED -> COMPLETED. | Dispatcher, Driver |
| POST | `/shuttle/run-sheets/{id}/cancel` | Cancel a PLANNED run-sheet; cascades to reservations. | Dispatcher |
| POST | `/shuttle/run-sheets/{id}/delays` | Report a delay event; auto-dispatches IM notification at threshold, substitute vehicle for BREAKDOWN. | Dispatcher, Driver |
| POST | `/shuttle/run-sheets/{id}/resume` | Transition DELAYED -> IN_TRANSIT. | Dispatcher |
| POST | `/shuttle/run-sheets/{id}/dispatch-substitute` | Manually assign a substitute vehicle to a run. | Dispatcher |
| GET | `/shuttle/run-sheets/{id}/statistics` | Return ridership statistics for this run. | Dispatcher, Auditor |
| POST | `/shuttle/run-sheets/{id}/reservations` | Create a reservation; auto-waitlists if full. | Employee, Dispatcher |
| GET | `/shuttle/reservations` | List reservations with filters. | Dispatcher, Employee, Auditor |
| GET | `/shuttle/reservations/{id}` | Get a reservation. | Dispatcher, Employee, Auditor |
| DELETE | `/shuttle/reservations/{id}` | Cancel a reservation. | Employee, Dispatcher |
| POST | `/shuttle/run-sheets/{run_id}/check-in` | Check in a rider (QR/CARD/FACE). | Driver, Dispatcher |
| PATCH | `/shuttle/ridership/{id}` | Record alighting on an existing ridership entry. | Driver, Dispatcher |
| POST | `/shuttle/bills` | Create a DRAFT monthly bill. | Dispatcher |
| POST | `/shuttle/bills/{id}/finalize` | Finalize a draft bill, pinning gross_cents. | Dispatcher |
| POST | `/shuttle/bills/{id}/settle` | Settle a finalized (or refunded) bill, pinning net_cents. | Dispatcher |
| GET | `/shuttle/bills` | List bills with filters. | Dispatcher, Auditor |
| GET | `/shuttle/audit-logs` | Query audit log entries. | Auditor, Dispatcher |
| POST | `/shuttle/_clock/advance` | Advance the system clock to a given ISO 8601 UTC instant. | Dispatcher, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STOP_NOT_ACTIVE` | 409 |
| `ERR_VEHICLE_HAS_BOOKED_RUNS` | 409 |
| `ERR_DRIVER_LICENSE_EXPIRED` | 409 |
| `ERR_CANCEL_WINDOW_CLOSED` | 409 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 |
| `ERR_INVALID_STOP_PAIR` | 422 |
| `ERR_DAILY_LIMIT_EXCEEDED` | 409 |
| `ERR_INVALID_FREQUENCY_WINDOWS` | 422 |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 |
| `ERR_DRIVER_DOUBLE_BOOKED` | 409 |
| `ERR_RUN_FULL` | 409 |
| `ERR_DUPLICATE_ROUTE_CODE` | 409 |
| `ERR_BILL_ALREADY_EXISTS` | 409 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_ROUTE_VERSION_CONFLICT` | 409 |
| `ERR_RESERVATION_ALREADY_CHECKED_IN` | 409 |
| `ERR_NO_VEHICLE_AVAILABLE` | 409 |
| `ERR_NO_SUBSTITUTE_VEHICLE` | 409 |
| `ERR_PAYER_MODE_MISMATCH` | 422 |
| `ERR_BILLING_MONTH_NOT_COMPLETE` | 409 |
| `ERR_BILL_HAS_OPEN_RESERVATIONS` | 409 |
