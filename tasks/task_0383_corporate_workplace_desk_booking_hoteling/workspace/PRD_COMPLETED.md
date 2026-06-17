# Workplace Desk Booking & Hoteling API — Product Requirements Document

## 1. Introduction

Modern corporate offices have moved away from permanently assigned desks toward a hoteling model, where employees reserve seats and meeting rooms on demand against a managed floor plan. This API is the system of record for that model. It holds the spatial inventory — sites, floors, neighborhoods (team zones), individual desks, and meeting rooms — and governs the full reservation lifecycle on top of it: booking, check-in, completion, voluntary cancellation, and automated release of no-shows once a grace window lapses.

Two operational tensions drive most of the rules in this document. The first is **scarcity under policy**: every neighborhood carries a capacity cap, team zones may be restricted to a particular team, and an employee who repeatedly fails to show up accrues strike points that eventually suspend their booking privilege. The second is **dual-dimension accounting on a single reservation**: a reservation simultaneously tracks where it sits in the occupancy lifecycle and where it sits in the amenity-chargeback lifecycle, and these two dimensions advance independently. Layered onto all of this is a visitor desk, run by reception, and a utilization-analytics surface that reports both planned demand and realized usage.

Because grace windows, no-show sweeps, and check-in deadlines are time-driven, the system runs against a settable logical clock rather than wall-clock time. This lets a deployment deterministically advance time, fire the no-show sweep, and observe the resulting cascades. The remainder of this document specifies the global contracts every endpoint obeys (Section 2), the domain workflows and the rules scattered through them (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. The API is mounted under the `/workplace` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or blank, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `FacilityManager`, `Employee`, `Receptionist`, and `Analyst`.

A `FacilityManager` owns the physical inventory and the operating policy. This role exclusively creates and manages sites, floors, neighborhoods, seats, rooms, employees, and capacity policies; takes seats out of service, restores them, and retires them; approves and denies amenity lines; force-releases no-show reservations; reinstates suspended employees; and drives the logical clock and the no-show sweep. When `X-User-Role` is `FacilityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

An `Employee` books seat and room reservations, checks in, completes, cancels, manages their own amenity lines, and acts as host on visitor passes. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare that resource's employee foreign key to `X-User-ID`. Concretely, creating a reservation requires the supplied `employee_id` to equal `X-User-ID`; checking in, completing, or cancelling a reservation, and adding or cancelling an amenity line, require the parent reservation's `employee_id` to equal `X-User-ID`; and requesting changes on or approving a visitor pass require the pass's `host_employee_id` to equal `X-User-ID`. On the read side this same ownership applies: an `Employee` fetching a single reservation, its check-ins, its amenity lines, or an individual amenity request whose parent reservation it does not own is rejected with `ERR_FORBIDDEN`, and an `Employee` listing reservations or a reservation's amenity lines sees only those tied to its own reservations (other employees' rows are silently excluded rather than erroring). An ownership failure for an `entity_backed` actor is reported as `ERR_FORBIDDEN`.

A `Receptionist` owns the visitor desk: filing visitor passes, resubmitting amended passes, checking visitors in, completing visits, and cancelling passes. When `X-User-Role` is `Receptionist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

An `Analyst` has read-only reach across the floor plan, reservations, amenities, visitor passes, the strike ledger, and utilization analytics. When `X-User-Role` is `Analyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and must be zero or greater. A `limit` outside the inclusive range of 1 to 100, or a negative `offset` (or a `limit`/`offset` that is non-integer), is rejected with `ERR_INVALID_PAGINATION` (HTTP 422). The one exception is the reservation check-ins list (`GET /workplace/reservations/{id}/check-ins`), which is not paginated: it returns every check-in of the reservation in creation order, ignoring any `limit`/`offset` and reporting `total_count` equal to the full count with `offset` 0 and `limit` equal to that count.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the full count of matching resources before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties

Every primary resource is system-stamped with an `id`, a server-minted UUID carrying no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that begins at 1 and increments by one on each mutation that changes the resource. These four fields are present on `Site`, `Floor`, `Neighborhood`, `Seat`, `Room`, `Employee`, `Reservation`, `AmenityRequest`, `CapacityPolicy`, and `VisitorPass`.

Two record types are immutable audit rows and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: the `CheckIn` record that captures a single check-in, and the `NoShowEvent` row that records one strike-ledger adjustment. Whenever a derived field on a resource is recomputed (for example a reservation's chargeback totals, or an employee's strike score), that recomputation counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. Resource Identifier Resolution Order

Many endpoints address nested resources through a multi-segment path. The system resolves every path identifier left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first segment that does not name an existing resource — for example, when listing the seats of a neighborhood, the neighborhood id is checked before any seat is considered. After path identifiers resolve, body-referenced foreign keys (such as `employee_id`, `seat_id`, `room_id`, `host_employee_id`, or `reservation_id`) are validated in the order they appear, and an unknown reference likewise yields `ERR_NOT_FOUND`. Existence resolution runs after authentication and authorization but before any business-rule evaluation.

### 2.6. Validation Order and Precedence

When several checks could fail on one request, they are evaluated in a fixed precedence so the returned `error_id` is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization including `entity_backed` ownership (`ERR_FORBIDDEN`); (3) existence of every path-referenced and body-referenced resource (`ERR_NOT_FOUND`); (4) structural well-formedness of the body — required fields present and correctly typed (`ERR_INVALID_REQUEST`); and (5) pagination-parameter validity on list endpoints (`ERR_INVALID_PAGINATION`). Only after these pass does the system evaluate domain-specific business rules, themselves ordered as described in Section 3.7. Throughout this document, the phrase "well-formed body" refers to check (4): a body whose required fields are present with the correct types — for instance `resource_type` being one of the accepted values, `booking_date` being an ISO calendar date of the form YYYY-MM-DD, and `start_minute` and `end_minute` being integers — failing which the request is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 2.7. Time, the Logical Clock, and Workday Windows

All booking times are expressed as **minutes from local midnight** — an integer count of minutes since 00:00 in the relevant site's local day. A `booking_date` is a local calendar date in YYYY-MM-DD form. The site's `timezone`, an IANA zone string that defaults to `"UTC"`, is the zone in which booking dates are interpreted against the clock.

Rather than reading wall-clock time, the system keeps a settable logical clock holding a current local date and a current minute-of-day. A `FacilityManager` sets it by supplying `current_date` (a YYYY-MM-DD date) and `current_minute` (an integer minute-of-day), failing whose well-formedness the set is rejected with `ERR_INVALID_REQUEST` (HTTP 422); a successful set returns 200 with a `data` object echoing `current_date` and `current_minute`. The clock is what check-in grace evaluation and the no-show sweep consult. The same minute-of-day convention bounds each floor's bookable day: a floor opens at `workday_start_minute` (default 540, i.e. 9 hours past midnight, or 9:00 a.m.) and closes at `workday_end_minute` (default 1080, i.e. 18 hours past midnight, or 6:00 p.m.). A floor's `capacity_minutes` is a derived field equal to `workday_end_minute` minus `workday_start_minute` and serves as the per-seat denominator for utilization.

### 2.8. Occupancy Counters and Derived-Field Reconciliation

Neighborhood and reservation counters are kept continuously consistent with the events that drive them. A neighborhood exposes a derived `seat_count`, the number of its seats whose `status` is not `RETIRED`, and a derived `effective_cap_seats`, the largest number of distinct seats reservable on any single date. Whenever a seat is added to or retired from a neighborhood, both `seat_count` and `effective_cap_seats` are recomputed, and the neighborhood's `updated_at` and `version` advance accordingly. A reservation exposes `occupied_minutes` (the minutes credited toward utilization) and the chargeback totals described in Section 3.5; each is reconciled at the moments described in Section 3, and every such reconciliation mutates the reservation. An employee's `strike_score` and `booking_privilege` are likewise derived and are re-reconciled on every strike-ledger change, as detailed in Section 3.6.

### 2.9. Monetary Precision

All monetary amounts in this system are integer counts of **cents**; there are no fractional-cent fields and no floating-point currency. Where the amenity-chargeback computation requires rounding (the per-line service-fee step and the discount step described in Section 3.5), the system rounds half up to the nearest whole cent — a value exactly halfway between two cents rounds to the larger cent. Utilization percentages are the only non-cent figures: they are decimal numbers carried to exactly 2 decimal places using the same round-half-up rule.

### 2.10. Optimistic Concurrency on Reservation Creation

Creating a reservation is the one write that may be guarded by optimistic concurrency control, because it commits against inventory whose state another writer may have just changed. When the booked resource is a desk, the create request carries `expected_seat_version`, the `version` of the target `Seat` that the client last observed; when the booked resource is a meeting room, it instead carries `expected_room_version`, the last observed `version` of the target `Room`. If the supplied value does not equal the current `version` of that seat or room — meaning another writer has advanced it since the client read it, for instance by booking the same resource or by pulling a seat out of service, leaving the client's overlap check based on a stale view — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A seat reservation is checked against the seat's live version and a room reservation against the room's live version; no other endpoint takes a version field, and endpoints other than reservation creation perform no version check.

## 3. Business Logic & Workflows

### 3.1. Building the Floor Plan

The spatial hierarchy is a strict tree. A `FacilityManager` first creates a `Site` with a `name` (non-empty, at most 120 characters) and an optional `timezone` (defaulting to `"UTC"`); a site begins in `status` `ACTIVE` and may later be `ARCHIVED`. Under a site the manager creates `Floor` records, each addressed through its parent site and recording that parentage in `site_id`. A floor is identified by its `level`, an integer that must be unique among the floors of the same site; it also accepts `workday_start_minute` and `workday_end_minute` to bound its bookable day. Those two minute bounds must satisfy: the start is zero or greater, the start is strictly less than the end, and the end is at most 1440 (the number of minutes in a day); a floor creation whose bounds violate this (treated as part of body well-formedness) is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The floor's `status` begins `ACTIVE` and may become `ARCHIVED`, and its `capacity_minutes` is computed at creation as the end minute minus the start minute.

Within a floor the manager lays out `Neighborhood` zones, each holding its parent in `floor_id` and a `name` that must be non-empty and unique among neighborhoods of that floor. A neighborhood may declare a `team_code` (defaulting to null, meaning the zone is open to all teams) and a `capacity_cap_pct`, an integer percentage from 1 to 100 inclusive that defaults to 100, capping the share of the zone's seats that may be reserved on any one date. A freshly created neighborhood starts with `seat_count` and `effective_cap_seats` both at zero.

Desks live inside a neighborhood. A `Seat` records its zone in `neighborhood_id` and a `label` that must be non-empty and unique among the seats of that neighborhood; it may be flagged a standing desk through the boolean `is_standing` (default false). A new seat enters inventory in `status` `AVAILABLE`. Meeting rooms hang directly off the floor: a `Room` records its `floor_id`, a `label` unique among the rooms of that floor, a `seats_capacity` integer of at least 1, and a `turnover_buffer_minute` (default 15, at least 0) that reserves cleaning time after each room booking. A room also begins `AVAILABLE`.

Creating a floor whose `level` collides with an existing floor of the same site, a neighborhood whose `name` collides within its floor, a seat whose `label` collides within its neighborhood, or a room whose `label` collides within its floor, is rejected with `ERR_DUPLICATE` (HTTP 409). The same `ERR_DUPLICATE` guards the global uniqueness of employee email described in Section 3.6.

### 3.2. Seat Inventory Lifecycle

A seat moves through an inventory lifecycle independent of any single booking, and only a `FacilityManager` drives it. From `AVAILABLE`, a seat may be taken `OUT_OF_SERVICE`; already-placed future reservations on it survive, but the seat is no longer bookable. An `OUT_OF_SERVICE` seat may be restored to `AVAILABLE`. From `AVAILABLE`, a seat may also be `RETIRED`, but only when no reservation on that seat is currently in the `BOOKED` or `CHECKED_IN` state; retirement is terminal. Retiring a seat decrements its neighborhood's `seat_count` and recomputes the neighborhood's `effective_cap_seats`. Attempting a transition from a state that does not permit it — for example taking an already `OUT_OF_SERVICE` seat out of service, or retiring a seat with live bookings — is rejected with `ERR_INVALID_STATE` (HTTP 409). Rooms carry the same three-value inventory vocabulary (`AVAILABLE`, `OUT_OF_SERVICE`, `RETIRED`) on their own `status` field.

### 3.3. Capacity Policy

Each floor may be governed by a `CapacityPolicy`, created or replaced by a `FacilityManager` and recording its floor in `floor_id`. It carries three knobs. `max_active_reservations_per_employee` (default 1, at least 1) caps how many non-terminal reservations a single employee may simultaneously hold on that floor for one date. `grace_minutes` (default 30, at least 0) is how long after a reservation's start an un-checked-in booking remains before it becomes releasable as a no-show. `enforce_team_zoning` (default true) decides whether team-coded neighborhoods restrict who may book their seats. The capacity policy is consulted at reservation time, as Section 3.4 describes; in the absence of an explicit policy on a floor, the documented defaults apply.

### 3.4. Reserving a Seat or a Room

An `Employee` creates a reservation by declaring whom it is for in `employee_id` (which must equal the acting `X-User-ID`), the `resource_type` it targets (one of `SEAT` or `ROOM`), the `booking_date`, and the half-open occupation window `start_minute` to `end_minute`. The window is half-open: it covers `start_minute` up to but not including `end_minute`. Exactly one of `seat_id` and `room_id` is supplied: a `SEAT` reservation must carry `seat_id` and leave `room_id` null, and a `ROOM` reservation must carry `room_id` and leave `seat_id` null. A `resource_type`/`seat_id`/`room_id` combination that violates this exclusive selector — a `SEAT` without a seat, a `ROOM` without a room, or both set — is rejected with `ERR_RESOURCE_TARGET_MISMATCH` (HTTP 422). A new reservation enters `occupancy_status` `BOOKED` and `billing_status` `NONE`.

Several gates guard the create, beyond the universal authentication, authorization, existence, and well-formedness checks of Section 2. The window must be valid and inside the floor's working day: `start_minute` must be strictly less than `end_minute`, and both must lie within the floor's `[workday_start_minute, workday_end_minute]` window; a window that inverts or falls outside the workday is rejected with `ERR_OUTSIDE_WORKDAY` (HTTP 422). The booked seat or room must be `AVAILABLE` at booking time — neither `OUT_OF_SERVICE` nor `RETIRED` — failing which the request is rejected with `ERR_RESOURCE_NOT_BOOKABLE` (HTTP 409). The acting employee's `booking_privilege` must be `ACTIVE`; a `SUSPENDED` employee attempting to book is rejected with `ERR_BOOKING_SUSPENDED` (HTTP 409). For a `SEAT` reservation, if the floor's policy enforces team zoning and the seat's neighborhood declares a non-null `team_code`, the acting employee's `team_code` must equal that value, or the booking is rejected with `ERR_TEAM_ZONING_VIOLATION` (HTTP 409). The employee must not already hold the policy's `max_active_reservations_per_employee` count of non-terminal (`BOOKED` or `CHECKED_IN`) reservations on the same floor and `booking_date`; exceeding it yields `ERR_RESERVATION_LIMIT_REACHED` (HTTP 409).

Overlap is enforced per resource against the existing committed schedule on the same `booking_date`. For a `SEAT`, the requested window must not intersect any existing non-terminal reservation or any active visitor pass on that seat; because windows are half-open, two bookings that merely touch at an endpoint (one ending exactly where the next begins) do not conflict, while any genuine overlap is rejected with `ERR_SEAT_DOUBLE_BOOKED` (HTTP 409). For a `ROOM`, the geometry is widened by the room's `turnover_buffer_minute`: the requested window with the turnover buffer appended after it must not intersect any existing non-terminal reservation on that room, and a conflict is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). A `SEAT` booking additionally faces the neighborhood capacity gate described in Section 3.9, which can fail with `ERR_NEIGHBORHOOD_CAPACITY_FULL` (HTTP 409). The optimistic-concurrency version check of Section 2.10 also applies here.

On a successful create, the reservation's `checkin_deadline_minute` is computed as `start_minute` plus the governing policy's `grace_minutes` — the minute-of-day past which an un-checked-in booking becomes a no-show. The booking holds the seat or room window for the date; a `SEAT` booking consumes neighborhood capacity for that date as covered in Section 3.9. As described in Section 2.10, committing a `SEAT` reservation advances the booked seat's `version` by one, and committing a `ROOM` reservation advances the booked room's `version` by one.

### 3.5. Amenities and the Chargeback Calculation

While a reservation is open, an `Employee` may attach amenity request lines to it — a monitor, parking, catering, and the like. Each `AmenityRequest` records its parent in `reservation_id`, an `amenity_code` (a non-empty catalog code), a `unit_price_cents` (an integer of at least 0), and a `quantity` (an integer of at least 1); its `line_total_cents` is computed as `unit_price_cents` multiplied by `quantity`. A new line begins in `line_status` `REQUESTED`. Adding the first line to a reservation whose `billing_status` is `NONE` advances that reservation to `billing_status` `PROVISIONAL`; adding any line is permitted only while the reservation's `occupancy_status` is `BOOKED` or `CHECKED_IN`, and an attempt to add a line to a reservation in any other occupancy state is rejected with `ERR_INVALID_STATE` (HTTP 409).

A `FacilityManager` reviews each line: from `REQUESTED` a line may be `APPROVED` or `DENIED`. Approval additionally requires the parent reservation's `occupancy_status` to still be `BOOKED` or `CHECKED_IN`; approving a line whose parent reservation has left those states is rejected with `ERR_INVALID_STATE` (HTTP 409). Denial carries no such parent-state requirement. An `Employee` may instead `CANCELLED` their own line, from either `REQUESTED` or `APPROVED`; cancelling an `APPROVED` line is forbidden once the parent reservation has reached `COMPLETED`, since the chargeback is by then frozen, and such an attempt is rejected with `ERR_AMENITY_LOCKED` (HTTP 409). Approving or denying a line whose `line_status` is not `REQUESTED` is rejected with `ERR_INVALID_STATE` (HTTP 409), as is any other transition attempted from the wrong line state. Approve and deny are `FacilityManager`-only; cancel of a line is the owning employee's. Every line change — creation of a subsequent line, approval, denial, or cancellation — re-derives the parent reservation's running `provisional_chargeback_cents`.

The chargeback amount is computed by a single aggregation that runs in a **pinned order**, and two variants of it exist. Both variants operate on a selected set of amenity lines and produce a whole-cent total through the following steps, in this exact sequence:

1. For each line in the selected set, take its line amount, which is `unit_price_cents` multiplied by `quantity`.
2. The subtotal is the sum of those line amounts.
3. For each individual line amount, compute a service fee of that amount multiplied by the service-fee rate of 0.085 (8.5 percent), rounding the per-line result half up to a whole cent. The rounding happens per line, before any summing.
4. The total fee is the sum of those per-line rounded fees.
5. The pre-discount total is the subtotal plus the total fee.
6. A volume discount percentage is selected from the pre-discount total: a pre-discount total of at most 499 cents earns 0 percent; a pre-discount total from 500 through 999 cents inclusive earns 5 percent; a pre-discount total of 1000 cents or more earns 10 percent.
7. The discount amount is the pre-discount total multiplied by that discount percentage divided by 100, rounded half up to a whole cent.
8. The final chargeback is the pre-discount total minus the discount amount.

The two rounding points are step 3 (each line's fee) and step 7 (the discount); all intermediate amounts are whole cents. The order matters because the discount tier is keyed on the pre-discount total, which already includes the fee, so the fee must be computed before the discount is selected. The **provisional** variant selects every line whose `line_status` is `REQUESTED` or `APPROVED`, and its result is written to `provisional_chargeback_cents`; it is recomputed on each line change while the reservation is open. The **final** variant selects only lines whose `line_status` is `APPROVED` (any line still merely `REQUESTED` at completion is excluded), and its result is frozen into `final_chargeback_cents` at completion and never recomputed thereafter. A reservation that never accrues a line keeps both totals at 0.

### 3.6. Employees, Strikes, and Booking Privilege

A `FacilityManager` creates an `Employee` with an `email` (non-empty, globally unique, stored lowercased), a `full_name`, and a `team_code` that is matched against neighborhood team codes for zoning. A duplicate email is rejected with `ERR_DUPLICATE` (HTTP 409). An employee record begins in `status` `ACTIVE` (which may later be `ARCHIVED`), with `strike_score` at 0 and `booking_privilege` `ACTIVE`.

The `strike_score` is a derived figure driven entirely by a strike ledger of `NoShowEvent` rows. Each event records its `employee_id`, the `reservation_id` that produced it, a `kind` of either `NO_SHOW` or `GOOD_CHECKIN`, and a `delta`. A `NO_SHOW` event carries a delta of positive 10 (the strike weight); a `GOOD_CHECKIN` event carries a delta of negative 3 (the good-behavior credit). The score is recomputed by summing the deltas of all of the employee's ledger rows created strictly after the employee's most recent reinstatement (or all rows if the employee has never been reinstated), then flooring the result at 0 — accumulated good behavior can pull the score down but never below zero. The `booking_privilege` is then derived from the floored score: it is `SUSPENDED` when the score is at least 30 (the suspend threshold), and `ACTIVE` when the score is below 30. Each recompute mutates the employee record per Section 2.8. Because a `NO_SHOW` adds 10 and a `GOOD_CHECKIN` removes 3, a suspended employee can recover privilege over time by checking in to subsequent bookings, since each good check-in credit lowers the running score.

A `FacilityManager` may also reinstate an employee directly. Reinstatement sets a new reinstatement baseline so that all prior ledger rows are excluded from future sums, recomputes `strike_score` to 0, and returns `booking_privilege` to `ACTIVE`. The employee's strike ledger is itself readable as a list, and the events produced by a single reservation are likewise readable, both restricted to `FacilityManager` and `Analyst`.

### 3.7. The Reservation Occupancy Lifecycle

A reservation carries two independent status dimensions. The `occupancy_status` dimension tracks the booking lifecycle through `BOOKED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW_RELEASED`, and `CANCELLED`, of which the last three are terminal. The `billing_status` dimension, covered in Section 3.5 and 3.8, tracks chargeback through `NONE`, `PROVISIONAL`, `FINALIZED`, and `VOID`, and evolves on its own schedule. The two are deliberately decoupled.

When a reservation is in state `BOOKED`, its owning `Employee` may check in. Check-in is permitted only when the reservation is `BOOKED`, when the acting employee owns it, when the logical clock's current minute-of-day is at or before the reservation's `checkin_deadline_minute` (the grace window has not expired), and when the booked seat or room is still `AVAILABLE` (it has not been pulled `OUT_OF_SERVICE`). A check-in attempt from the wrong occupancy state is rejected with `ERR_INVALID_STATE`, a check-in attempted after the grace window has expired (the clock's current minute-of-day strictly greater than `checkin_deadline_minute`) is likewise rejected with `ERR_INVALID_STATE` (HTTP 409), a check-in attempted while the logical clock has not been set is also rejected with `ERR_INVALID_STATE` (HTTP 409), and a check-in against a no-longer-available resource with `ERR_RESOURCE_NOT_BOOKABLE`. These occupancy-state, grace-window, and clock-set checks are evaluated in that order, ahead of the resource-availability check. A successful check-in advances `occupancy_status` from `BOOKED` to `CHECKED_IN` and has three further effects: it creates a `CheckIn` child whose `checked_in_at_minute` is the clock's current minute-of-day and whose `within_grace` flag is true (true exactly when `checked_in_at_minute` is at or before `checkin_deadline_minute`); it appends a `GOOD_CHECKIN` `NoShowEvent` of delta negative 3 for the employee, then recomputes the employee's `strike_score` and re-derives `booking_privilege`; and it sets the reservation's `occupied_minutes` to `end_minute` minus `start_minute`.

From `CHECKED_IN`, the owning employee may complete the reservation. Completion is allowed only from `CHECKED_IN` by the owner. It advances `occupancy_status` to `COMPLETED`, releases the held seat or room window for the date (decrementing neighborhood occupancy for that date in the seat case), and sets `occupied_minutes` to `end_minute` minus `start_minute`. If at completion the reservation's `billing_status` is `PROVISIONAL`, completion also advances `billing_status` to `FINALIZED` and freezes `final_chargeback_cents` using the final variant of the chargeback calculation, over approved lines only.

The owning employee may cancel a reservation that is `BOOKED` or `CHECKED_IN`. Cancellation advances `occupancy_status` to `CANCELLED`, frees the held seat or room window (decrementing neighborhood occupancy for the date), and runs the void cascade of Section 3.8; when cancelling from `CHECKED_IN`, `occupied_minutes` is reset to 0. A voluntary cancellation carries no strike — this is the deliberate difference from a no-show release. A transition attempted from an occupancy state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.8. No-Show Release and the Void Cascade

A reservation that is still `BOOKED` after its grace window lapses is a no-show. There are two ways it reaches release. A `FacilityManager` may force-release a specific grace-expired reservation, or the system no-show sweep may release it in bulk. In both paths the precondition is the same: the reservation must be `BOOKED` and the logical clock's current minute-of-day must be strictly greater than the reservation's `checkin_deadline_minute` (the grace window has expired). A force-release whose target is not `BOOKED`, or whose grace window has not yet expired, or that is attempted while the logical clock has not been set, is rejected with `ERR_INVALID_STATE` (HTTP 409). The sweep, driven by a `FacilityManager`, scans for every `BOOKED` reservation whose grace has expired at the current clock — optionally narrowed to a single `booking_date` — releases each one, and reports how many it released and their ids; the sweep response `data` object carries `released_count` (an integer) and `released_reservation_ids` (an array of the released reservation ids in creation order). A sweep attempted while the logical clock has not been set is rejected with `ERR_INVALID_REQUEST` (HTTP 422), and a sweep whose optional `booking_date` is supplied but is not a valid YYYY-MM-DD date is likewise rejected with `ERR_INVALID_REQUEST`.

Releasing a no-show advances `occupancy_status` from `BOOKED` to `NO_SHOW_RELEASED` and triggers a depth-three cascade. First, the held seat or room window is freed so the slot can be re-booked, decrementing neighborhood occupancy for the date. Second, a `NO_SHOW` `NoShowEvent` of delta positive 10 is appended for the employee, the employee's `strike_score` is recomputed, and `booking_privilege` is re-derived; if the recomputed score reaches the suspend threshold of 30, the employee's privilege flips to `SUSPENDED` and that employee's subsequent reservation creates are rejected with `ERR_BOOKING_SUSPENDED`. Third, every `AmenityRequest` of the reservation that is in `REQUESTED` or `APPROVED` is moved to `CANCELLED`, after which the reservation's `billing_status` is set to `VOID` and its `provisional_chargeback_cents` is reset to 0.

The same void cascade fires on a voluntary cancellation (Section 3.7): the reservation's `REQUESTED` and `APPROVED` amenity lines are moved to `CANCELLED`, `billing_status` becomes `VOID`, and `provisional_chargeback_cents` resets to 0 — the only difference from a no-show release is that cancellation appends no strike event. In billing terms, both a no-show release and a cancellation drive `billing_status` to `VOID`, whereas an orderly completion drives it to `FINALIZED`; both `FINALIZED` and `VOID` are terminal billing states.

### 3.9. Neighborhood Capacity Gating

Seat bookings draw down a per-date capacity budget for their neighborhood. The budget, `effective_cap_seats`, is the seat count of the neighborhood (seats whose `status` is not `RETIRED`) multiplied by the neighborhood's `capacity_cap_pct`, divided by 100, rounded up to the next whole seat. At booking time the system counts the distinct seats already reserved in that neighborhood on the requested `booking_date` — distinct `seat_id` values across reservations whose `occupancy_status` is `BOOKED` or `CHECKED_IN`. If the seat being booked is already among those distinct reserved seats, no additional capacity is consumed (the same seat does not count twice). Otherwise the booking is allowed only when the count of distinct reserved seats plus one is at most `effective_cap_seats`; the boundary case where that sum exactly equals `effective_cap_seats` is allowed. A booking that would push the distinct count past the cap is rejected with `ERR_NEIGHBORHOOD_CAPACITY_FULL`. This budget is per date: a different `booking_date` carries an entirely independent count.

### 3.10. The Visitor Desk

A `Receptionist` runs visitor passes, which hold a desk for a sponsored guest. A `VisitorPass` records the sponsoring host in `host_employee_id`, the assigned desk in `seat_id`, the guest's `visitor_name` (non-empty), the `booking_date`, and the half-open visit window `start_minute` to `end_minute` (start strictly less than end). A new pass begins in `status` `REQUESTED`, holding the seat window subject to the same seat-overlap check as a reservation: the requested window must not intersect any non-terminal reservation or active visitor pass on that seat and date, or it is rejected with `ERR_SEAT_DOUBLE_BOOKED`. A visitor pass holds (is "active" for) the seat window exactly while its `status` is `REQUESTED`, `APPROVED`, or `CHECKED_IN`; a `CHANGES_REQUESTED`, `COMPLETED`, or `CANCELLED` pass holds no window and is ignored by overlap checks. The window must also lie within the floor's workday, failing which the pass is rejected with `ERR_OUTSIDE_WORKDAY`, and the seat must be bookable (not `OUT_OF_SERVICE` or `RETIRED`), failing which it is rejected with `ERR_RESOURCE_NOT_BOOKABLE`.

The pass follows a cyclic host-review loop. From `REQUESTED`, the host employee — whose `id` must equal the acting `X-User-ID` — may request changes, moving the pass to `CHANGES_REQUESTED` and freeing the held seat window so it can be amended. From `CHANGES_REQUESTED`, the receptionist resubmits an amended pass, optionally supplying a new `start_minute`, `end_minute`, or `booking_date`; this returns the pass to `REQUESTED` and re-holds a seat window for the amended visit, re-running the overlap check (excluding the pass itself) on the new window and, when the seat's floor resolves, the workday-window check as well; a conflicting amended window is rejected with `ERR_SEAT_DOUBLE_BOOKED` and an amended window that inverts or falls outside the workday with `ERR_OUTSIDE_WORKDAY`. This `REQUESTED` to `CHANGES_REQUESTED` to `REQUESTED` cycle may repeat any number of rounds. From `REQUESTED`, the host may instead approve the pass: approval is permitted only when the host owns it and the seat window is free of any overlapping reservation or other visitor pass on the date (the pass itself excluded), and it locks the seat window and moves the pass to `APPROVED`; an approval whose window now conflicts is rejected with `ERR_SEAT_DOUBLE_BOOKED`. From `APPROVED`, the receptionist checks the visitor in, moving the pass to `CHECKED_IN`. From `CHECKED_IN`, the receptionist completes the visit, moving it to `COMPLETED` and freeing the seat window. At any point while the pass is `REQUESTED`, `CHANGES_REQUESTED`, or `APPROVED`, the receptionist may cancel it, moving it to `CANCELLED` and freeing the seat window. `COMPLETED` and `CANCELLED` are terminal. Any visitor-pass transition attempted from a status that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.11. Utilization Analytics

A `FacilityManager` or `Analyst` may request a floor's utilization for a given `date`, optionally choosing a `mode`. The report computes a per-seat occupancy percentage and a floor-wide average. The per-seat denominator is the floor's `capacity_minutes` (its `workday_end_minute` minus `workday_start_minute`). For each seat on the floor whose `status` is not `RETIRED`, the booked minutes are the sum, across reservations on that seat whose `booking_date` equals the requested date and whose `occupancy_status` falls in the variant's counted set, of each such reservation's window length `end_minute` minus `start_minute` (the window length is used directly, irrespective of the reservation's stored `occupied_minutes` field, so a still-`BOOKED` reservation counted by the planned variant contributes its full window); the seat's percentage is the booked minutes divided by `capacity_minutes`, multiplied by 100, rounded half up to 2 decimal places. The floor utilization percentage is the mean of those per-seat percentages — each already rounded to 2 decimal places — then itself rounded half up to 2 decimal places. A floor with zero non-retired seats reports a floor utilization of 0.00 with no division performed.

Two variants diverge on which reservations count toward a seat's booked minutes. The **planned** variant (the default, also selected by `mode` `PLANNED`) counts occupancy for reservations whose `occupancy_status` is `BOOKED`, `CHECKED_IN`, or `COMPLETED`, capturing forward-looking demand. The **realized** variant (selected by `mode` `REALIZED`) counts only `CHECKED_IN` and `COMPLETED` reservations, excluding bookings that were never checked in, and so generally reports a lower number. The response carries `floor_utilization_pct`, the floor's `capacity_minutes`, a per-seat `seat_breakdown` array, the `mode` evaluated, and the `date` requested; each `seat_breakdown` element is an object with `seat_id`, `booked_minutes` (the seat's summed counted minutes as an integer), and `seat_utilization_pct` (the seat's percentage), and the breakdown is ordered by seat creation. The `mode` query parameter, when supplied, must be exactly `PLANNED` or `REALIZED` (defaulting to `PLANNED` when omitted), and a missing or non-string `date` query parameter, or a `mode` outside those two values, is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that fetch, list, or transition the state of an existing resource (including state-machine actions and the clock controls) return `200 OK`. All endpoints are mounted under `/workplace`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/workplace/sites` | Create a site | FacilityManager |
| GET | `/workplace/sites/{id}` | Fetch a site | FacilityManager, Analyst, Receptionist, Employee |
| POST | `/workplace/sites/{id}/floors` | Create a floor under a site | FacilityManager |
| GET | `/workplace/sites/{id}/floors` | List floors of a site | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/floors/{id}` | Fetch a floor | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/floors/{id}/utilization` | Computed planned vs realized utilization for a date | FacilityManager, Analyst |
| POST | `/workplace/floors/{id}/capacity-policy` | Create/replace the floor's capacity policy | FacilityManager |
| GET | `/workplace/floors/{id}/capacity-policy` | List the floor's capacity policy | FacilityManager, Analyst |
| POST | `/workplace/floors/{id}/neighborhoods` | Create a neighborhood on a floor | FacilityManager |
| GET | `/workplace/floors/{id}/neighborhoods` | List neighborhoods of a floor | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/neighborhoods/{id}` | Fetch a neighborhood | FacilityManager, Analyst, Receptionist, Employee |
| POST | `/workplace/neighborhoods/{id}/seats` | Create a seat in a neighborhood | FacilityManager |
| GET | `/workplace/neighborhoods/{id}/seats` | List seats of a neighborhood | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/seats/{id}` | Fetch a seat | FacilityManager, Analyst, Receptionist, Employee |
| POST | `/workplace/seats/{id}/out-of-service` | Mark a seat out of service | FacilityManager |
| POST | `/workplace/seats/{id}/restore` | Restore a seat to available | FacilityManager |
| POST | `/workplace/seats/{id}/retire` | Retire a seat permanently | FacilityManager |
| POST | `/workplace/floors/{id}/rooms` | Create a meeting room on a floor | FacilityManager |
| GET | `/workplace/floors/{id}/rooms` | List rooms of a floor | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/rooms/{id}` | Fetch a room | FacilityManager, Analyst, Receptionist, Employee |
| POST | `/workplace/employees` | Create an employee | FacilityManager |
| GET | `/workplace/employees/{id}` | Fetch an employee | FacilityManager, Analyst, Receptionist, Employee |
| GET | `/workplace/employees/{id}/no-show-events` | List an employee's strike ledger | FacilityManager, Analyst |
| POST | `/workplace/employees/{id}/reinstate` | Clear strike history and reinstate privilege | FacilityManager |
| POST | `/workplace/reservations` | Create a seat or room reservation | Employee |
| GET | `/workplace/reservations/{id}` | Fetch a reservation | FacilityManager, Analyst, Employee |
| GET | `/workplace/reservations` | List/filter reservations | FacilityManager, Analyst, Employee |
| POST | `/workplace/reservations/{id}/check-in` | Employee checks in within grace | Employee |
| POST | `/workplace/reservations/{id}/complete` | Employee completes the booking | Employee |
| POST | `/workplace/reservations/{id}/cancel` | Employee cancels the reservation | Employee |
| POST | `/workplace/reservations/{id}/release` | Force-release a grace-expired no-show | FacilityManager |
| GET | `/workplace/reservations/{id}/check-ins` | List check-ins of a reservation | FacilityManager, Analyst, Employee |
| GET | `/workplace/reservations/{id}/no-show-events` | List no-show events produced by a reservation | FacilityManager, Analyst |
| POST | `/workplace/reservations/{id}/amenities` | Add an amenity request line | Employee |
| GET | `/workplace/reservations/{id}/amenities` | List amenity requests of a reservation | FacilityManager, Analyst, Employee |
| GET | `/workplace/amenity-requests/{id}` | Fetch an amenity request | FacilityManager, Analyst, Employee |
| POST | `/workplace/amenity-requests/{id}/approve` | Approve an amenity line | FacilityManager |
| POST | `/workplace/amenity-requests/{id}/deny` | Deny an amenity line | FacilityManager |
| POST | `/workplace/amenity-requests/{id}/cancel` | Cancel an amenity line | Employee |
| POST | `/workplace/visitor-passes` | File a visitor pass holding a seat window | Receptionist |
| GET | `/workplace/visitor-passes/{id}` | Fetch a visitor pass | FacilityManager, Receptionist, Employee, Analyst |
| GET | `/workplace/visitor-passes` | List visitor passes | FacilityManager, Receptionist, Analyst |
| POST | `/workplace/visitor-passes/{id}/request-changes` | Host requests changes | Employee |
| POST | `/workplace/visitor-passes/{id}/resubmit` | Receptionist resubmits an amended pass | Receptionist |
| POST | `/workplace/visitor-passes/{id}/approve` | Host approves the pass and locks the seat | Employee |
| POST | `/workplace/visitor-passes/{id}/check-in` | Receptionist checks in the visitor | Receptionist |
| POST | `/workplace/visitor-passes/{id}/complete` | Receptionist completes the visit | Receptionist |
| POST | `/workplace/visitor-passes/{id}/cancel` | Receptionist cancels the pass | Receptionist |
| POST | `/workplace/_clock/set` | Set the simulated current local date and minute-of-day | FacilityManager |
| POST | `/workplace/_clock/advance-no-show-sweep` | Run the no-show sweep for grace-expired bookings | FacilityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_RESOURCE_TARGET_MISMATCH` | 422 |
| `ERR_OUTSIDE_WORKDAY` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RESOURCE_NOT_BOOKABLE` | 409 |
| `ERR_BOOKING_SUSPENDED` | 409 |
| `ERR_TEAM_ZONING_VIOLATION` | 409 |
| `ERR_RESERVATION_LIMIT_REACHED` | 409 |
| `ERR_SEAT_DOUBLE_BOOKED` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_NEIGHBORHOOD_CAPACITY_FULL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_AMENITY_LOCKED` | 409 |
