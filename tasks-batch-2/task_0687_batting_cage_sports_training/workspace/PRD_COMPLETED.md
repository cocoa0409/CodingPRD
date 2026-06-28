# Batting Cage & Sports-Training API — Product Requirements Document

## 1. Introduction

The Batting Cage & Sports-Training API is the operational backbone of a multi-resource sports-training complex. A single venue rents out cages, pitching tunnels, and practice lanes; sells coaching lessons; takes team rental blocks and birthday-party packages; runs leagues and clinics; and maintains a fleet of pitching machines that wear down with use and must be serviced. The product's job is to keep these overlapping demands on a finite set of physical lanes from colliding — in time, in money, and in safety — while giving members a flexible mix of pay-as-you-go tokens, hourly walk-up pricing, and minutes-based memberships.

Three pressures shape every rule in this specification. The first is **temporal exclusivity**: a lane is a physical thing, and no two reservations may occupy it at the same time, including a configurable idle buffer between sessions. The second is **dual-variant pricing**: every booking is quoted optimistically when it is requested and then re-priced — sometimes differently — when it is actually confirmed, because rates and peak-hour windows are re-read at confirm time. The third is **operational safety and wear**: liability waivers must be current, machines that have thrown too many pitches must be pulled from service, and lanes under maintenance must shed their bookings and, when severe enough, push the whole facility into a restricted or closed posture.

This document specifies the complete contract: the entities and their lifecycles, the calculations that price and gate each booking, the validation order that decides which error a bad request earns, and the optimistic-concurrency rules that keep two writers from double-booking a lane or over-filling a program. All times in the system are UTC ISO 8601 instants driven by a controllable logical clock, so that temporal behavior is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `FacilityManager`, `FrontDesk`, `Member`, and `Instructor`. When a request is authenticated but the acting role is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide along ownership lines. A `FacilityManager` owns facility configuration — creating facilities, lanes, machines, instructors, and programs; opening and resolving maintenance windows; closing programs; rejecting bookings; voiding waivers; and advancing the operational epoch. A `FrontDesk` operator runs the desk: registering members, topping up wallets, checking bookings in and completing them, and requesting, confirming, and cancelling bookings on a member's behalf. A `Member` is a patron acting on their own resources, and an `Instructor` is a coach with read-only capability in this version of the system.

Two roles are **opaque operator identities**. When `X-User-Role` is `FacilityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `FrontDesk`: when `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity `id`.

The other two roles are **entity-backed**. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's `member_id` foreign-key field to `X-User-ID`. A member signing their own waiver must pass their own identifier as `member_id` so that `X-User-ID` equals `member_id`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an `Instructor` compare the resource's `instructor_id` foreign-key field to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A request whose pagination parameters fall outside these bounds, or which is otherwise malformed at the query-parameter or path-parameter level (for example, a non-integer limit or a malformed UUID), is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Here `total_count` is the count of all matching resources before pagination, and `has_more` is true exactly when `offset` plus `limit` is strictly less than `total_count`. The `offset` parameter has no upper bound beyond being a non-negative integer; only `limit` is bounded to the range 1 through 100.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `Facility`, `Lane`, `PitchingMachine`, `MaintenanceWindow`, `Member`, `Instructor`, `Booking`, `Program`, and `Enrollment` — carries a system-managed `id`, formatted as a UUID with no type prefix and used for identity only, along with a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when the resource was first created. These resources also carry an `updated_at` timestamp, refreshed on every mutation including cascaded changes, and a `version` integer that begins at 1 and increases by exactly one on every mutation of that resource. The `version` field is the basis for optimistic concurrency control described in §2.8.

The `Waiver` resource is the sole exception: a waiver is immutable once written, so it carries only an `id` and a `created_at` timestamp. A `Waiver` has no `updated_at` field and no `version` field at all.

Several fields are **derived** — the server computes them and clients never set them directly. On a `Facility`, the `posture`, `open_incident_count`, and `epoch_index` are server-maintained. On a `Lane`, the `maint_status` is derived. On a `PitchingMachine`, both `pitch_count` and `status` are derived. On a `Member`, the `token_balance`, `monthly_member_minutes_used`, `no_show_strikes`, and `waiver_ok` are all derived. On a `Booking`, the `duration_minutes`, `quoted_cost_cents`, `final_cost_cents`, and `token_cost` are computed, and `status` is system-managed. On a `Program`, `enrolled_count` and `status` are derived. On an `Enrollment`, `charged_cents` and `status` are server-maintained. On a `Waiver`, `signed_at` is stamped by the server from the logical clock and `expires_at` is computed from it.

### 2.5. The Logical Clock and Temporal Determinism

All time-sensitive behavior in the system reads a single server-side **logical clock** rather than wall-clock time. The clock can be set to any arbitrary ISO 8601 UTC instant by supplying a `to_iso8601` value to the test-driving clock capability. Before any clock has been set, the server's startup default is `2026-04-01T00:00:00Z`, and the clock never falls back to wall-clock time. Waiver validity, refund cut-offs, check-in windows, no-show sweeps, and the peak-pricing window all read this clock.

Reservations and maintenance windows model time as **half-open intervals** `[start, end)` — the start instant is included and the end instant is excluded. Two such intervals overlap when each begins strictly before the other ends. Facility daily hours are expressed as minute offsets from midnight UTC: `open_minute` is inclusive and `close_minute` is exclusive, with `close_minute` required to be greater than `open_minute`, and both constrained to the range from 0 through 1440. The `timezone` field on a facility is an IANA timezone string kept for informational purposes only; all instants the system reasons about are UTC.

### 2.6. The Operational Epoch and Run-Ops Sweep

The facility tracks a monotonic `epoch_index`, beginning at 0 when the facility is created and increasing by exactly one each time an operator advances the epoch. Advancing the epoch is a single sweep operation performed by a `FacilityManager`. During the sweep, every booking that is still `CONFIRMED` whose end instant is at or before the current clock and which was never checked in is transitioned to `NO_SHOW`, and the responsible member's `no_show_strikes` is increased by one for each such booking. After the no-show sweep, every member's `monthly_member_minutes_used` is reset to 0 and every member's `no_show_strikes` is reset to 0, and the lane, machine, posture, and waiver-derived fields are recomputed. The sweep is the epoch boundary across which membership minutes and strikes are cleared.

### 2.7. Hierarchical Consistency and Cascades

The complex is organized as a hierarchy with the `Facility` as the aggregate root. Lanes, machines, maintenance windows, members, instructors, bookings, programs, and enrollments all hang beneath a facility and carry its identifier in their `facility_id`. Whenever an operation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented; when an operation cascades into a second resource, that second resource is independently mutated the same way, refreshing its own `updated_at` and bumping its own `version`.

Several derived states propagate upward. A lane's `maint_status` is a function of the open maintenance windows on it; a facility's `posture` is a function of how many of its lanes are closed; and a program's `status` is a function of how many members are currently enrolled. Whenever an underlying fact changes — a window opens or resolves, a booking is confirmed or cancelled, an enrollment is created or withdrawn — the server recomputes the dependent derived fields and re-evaluates the parent's state so that the hierarchy stays internally consistent at all times.

### 2.8. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a shared parent.

Confirming a booking requires the client to supply `expected_lane_version`, carrying the `version` of the target `Lane` as the client last observed it. If another writer has advanced the lane's `version` since then — for example, by confirming an overlapping booking that legitimately occupies part of the interval — the client's view of the lane's occupancy is stale, and the confirm is rejected with `ERR_STALE_LANE_VERSION` at HTTP 412. This stale-version check is evaluated before the temporal-overlap test, so a stale lane yields a deterministic rejection rather than a conflict error. The `expected_lane_version` field is required on confirm and is not an optional input; an omitted or non-integer `expected_lane_version` is a malformed request reported as `ERR_INVALID_REQUEST` at well-formedness priority, not as a stale-version conflict.

Creating an enrollment requires the client to supply `expected_program_version`, carrying the `version` of the target `Program` as the client last observed it. If another writer has advanced the program's `version` since then — for example, by taking the last open seat — the client's view of remaining capacity is stale, and the create is rejected with `ERR_STALE_PROGRAM_VERSION` at HTTP 412. The `expected_program_version` field is required on enrollment creation; an omitted or non-integer `expected_program_version` is a malformed request reported as `ERR_INVALID_REQUEST` at well-formedness priority, not as a stale-version conflict. No other endpoint accepts a version field; only these two operations participate in optimistic concurrency control.

### 2.9. Nested Resource Retrieval and Existence Ordering

Requests are validated against the resource hierarchy in a strict left-to-right order along the path. When a path or body references resources — for example, an enrollment listed under a program, or a booking that names a lane, member, and machine — the server confirms each referenced resource exists within facility scope in path order. The first identifier that does not resolve produces `ERR_NOT_FOUND` before any later identifier is examined and before any business rule runs. This ordering means a missing parent is reported as not-found before the system ever looks for the child.

### 2.10. Monetary Precision and Rounding

All monetary amounts are integer **cents**; there are no fractional-cent values stored anywhere in the system. Where a calculation multiplies a rate by a fractional number of hours, the rule is to round each price component to whole cents using the round-half-up method, and then to sum the rounded components. This per-component rounding order is mandatory: each component (the lane portion, the coaching portion, the machine surcharge, and the party portion) is rounded to whole cents first, the rounded components are summed into a gross amount, and only then is the membership-tier discount applied, with the discounted result rounded half-up once more to whole cents. Rounding the summed total in a single step is the wrong order and produces different cents in fractional cases.

Token conversions and refunds are integers as well. Converting a cent amount into tokens always rounds **up** to the next whole token, and converting a refund of cents back into wallet tokens always rounds **down** to the nearest whole token, as detailed in the workflows of §3.

### 2.11. The Validation Order

When a request fails more than one rule, the system reports the failure of the highest-priority rule, evaluated in the following fixed order. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Existence is third: a referenced resource that does not exist within facility scope, validated left-to-right in the path, yields `ERR_NOT_FOUND`. Request well-formedness is fourth: a malformed body — a missing required field, a bad enum value, an end instant that is not strictly after the start instant, a duration that is not a positive whole multiple of the slot length, or a `lane_count` that does not equal one plus the number of entries in `team_lane_ids` — yields `ERR_INVALID_REQUEST`. State validity is fifth: a target resource that is not in a legal state for the requested transition yields `ERR_INVALID_STATE`.

From there the business rules apply in this order: waiver currency (sixth), facility posture (seventh), no-show strikes (eighth), resource availability (ninth), lane time conflict (tenth), facility open hours (eleventh), booking-shape referential rules (twelfth), funds and minutes (thirteenth), program capacity (fourteenth), and finally the optimistic-concurrency stale-version check (fifteenth). The fifteenth-priority numbering governs the program stale-version check on enrollment creation (evaluated after program capacity); the lane stale-version check on confirm is instead evaluated, per §2.8, immediately after resource availability and before the lane time-conflict test rather than at the very end. The specific trigger conditions and error codes for each of these business rules are described alongside the workflows they guard in §3; the priority numbering here is what determines which single error a multiply-invalid request receives.

## 3. Business Logic & Workflows

### 3.1. Establishing the Facility and Its Resources

Everything begins with a `FacilityManager` creating a **Facility**, the aggregate root. A facility is given a `name` and may optionally specify a `timezone` (defaulting to `UTC`), an `open_minute` (defaulting to 480, i.e. 08:00 UTC), a `close_minute` (defaulting to 1320, i.e. 22:00 UTC), a `token_price_cents` (the price in cents of one token sold through a wallet top-up, defaulting to 500 and required to be at least 1), and an `hourly_rate_cents` (the per-lane base rate per sixty minutes charged to non-member open-slot bookings, defaulting to 4000 and required to be zero or greater). A newly created facility opens with `posture` set to `OPEN`, `epoch_index` at 0, and `open_incident_count` at 0.

Beneath the facility, the manager installs **Lanes**. A lane belongs to a facility through its `facility_id` and is described by a human `label` such as "Cage 1", a `kind` that is one of `CAGE`, `TUNNEL`, or `LANE`, and an optional `buffer_minutes` (defaulting to 0 and required to be zero or greater) that specifies the idle gap that must be left after each booking before the next booking may start on that lane. A lane may also override the facility's hourly pricing with its own `hourly_rate_cents`; when this lane-level override is null, the lane inherits the facility rate. A lane is born `AVAILABLE` in its `maint_status`.

A **PitchingMachine** is equipment installed on a single lane — one machine per lane. It carries its owning `facility_id` and the `lane_id` of the lane it sits on, and a `model` that is one of `WHEEL`, `ARM`, or `SOFT_TOSS`, which determines the per-booking machine surcharge tier. A new machine starts `OPERATIONAL` with a `pitch_count` of 0. The wear logic that drives a machine through `DEGRADED` and `OUT_OF_SERVICE` is described in §3.6.

The manager also registers the people. An **Instructor** carries a `facility_id`, a `full_name`, a coaching `rate_cents_per_hour` (the coaching fee per sixty minutes, required to be zero or greater, added on top of lane cost for lessons), and an `active` flag that defaults to true; an inactive instructor cannot be assigned to new lessons. A **Member** carries a `facility_id`, a `full_name`, and a membership `tier` that is one of `NONE`, `BRONZE`, or `GOLD`, defaulting to `NONE`, where `NONE` means pay-per-use only. A newly registered member starts with a `token_balance` of 0, `no_show_strikes` of 0, and `waiver_ok` false. Either a `FacilityManager` or a `FrontDesk` operator may register a member and top up a member's wallet; a top-up adds the supplied number of `tokens` to the member's `token_balance`.

### 3.2. Waivers and the Right to Play

Before a member may set foot in a confirmed booking, they must have a current liability **Waiver**. Signing a waiver creates an immutable record naming the `facility_id` and the signing member's `member_id`; the server stamps `signed_at` from the logical clock and computes `expires_at` as exactly 365 days after `signed_at`. A waiver's `status` is `SIGNED` on creation, and only a `SIGNED` waiver counts; a `FacilityManager` may later set a waiver's `status` to `VOID`, which removes it from consideration. A `Member`, `FrontDesk`, or `FacilityManager` may sign a waiver, but a member acting on their own behalf must pass their own identifier as `member_id`.

A member's `waiver_ok` flag is derived, not stored by hand. The system looks at the member's `SIGNED` waivers and selects the one with the greatest `signed_at`; if two share the same `signed_at`, the tie is broken by the greatest `created_at`, with no further tie-break on `id`. The member's `waiver_ok` is true exactly when such a `SIGNED` waiver exists and the current clock is strictly earlier than that waiver's `expires_at`. At the boundary instant where the clock equals `expires_at`, the waiver is treated as expired and `waiver_ok` is false. Signing a waiver recomputes the member's `waiver_ok` (typically to true), and voiding one recomputes it as well.

### 3.3. Maintenance, Lane Health, and Facility Posture

Lanes go out of service through **MaintenanceWindows**, append-only intervals opened by a `FacilityManager`. A window names its `facility_id` and `lane_id`, a `start_utc` and an exclusive `end_utc` (which must be strictly after `start_utc`), and a `severity` of either `ROUTINE` or `CRITICAL`. A window's `status` is `OPEN` when created and becomes `RESOLVED` once the manager resolves it; a `RESOLVED` window no longer gates its lane.

A lane's `maint_status` is recomputed from its open windows. If any `OPEN` window on the lane has `CRITICAL` severity, the lane is `CLOSED`; otherwise, if any `OPEN` window on the lane has `ROUTINE` severity, the lane is `UNDER_MAINTENANCE`; otherwise the lane is `AVAILABLE`. Opening a `ROUTINE` window on a lane that has no `CRITICAL` open window moves the lane from `AVAILABLE` to `UNDER_MAINTENANCE`, and while a lane has any open window, new bookings whose interval overlaps that window are blocked. Opening a `CRITICAL` window moves the lane to `CLOSED` regardless of whether it was `AVAILABLE` or already `UNDER_MAINTENANCE`. A `CRITICAL` window carries a powerful cascade: every booking on that lane in `CONFIRMED` or `CHECKED_IN` status whose interval overlaps the window is cascade-cancelled to `CANCELLED`, and each such cancellation refunds the payer exactly as a normal cancel would, releasing tokens or restoring membership minutes; the facility's `open_incident_count` is then recomputed, which may shift the facility's posture.

Resolving a window sets it to `RESOLVED` and recomputes the lane's `maint_status`. When the last open window on a lane is resolved, the lane returns to `AVAILABLE` from either `UNDER_MAINTENANCE` or `CLOSED`; if that lane had a machine installed, the machine's `pitch_count` is reset to 0 and its status recomputed to `OPERATIONAL`; and the facility's `open_incident_count` is recomputed, which may relax the facility's posture.

A facility's `posture` is a derived gate over its lane incidents. The `open_incident_count` is the number of lanes under the facility whose `maint_status` is `CLOSED`. When that count is at least the close threshold of 2, the posture is `CLOSED`; when the count is at least 1 but below 2, the posture is `RESTRICTED`; when the count is 0, the posture is `OPEN`. A `RESTRICTED` posture blocks the creation of large-footprint `PARTY` and `TEAM_BLOCK` bookings while still allowing `OPEN_SLOT` and `LESSON` bookings; a `CLOSED` posture blocks confirmation of all booking kinds and all program enrollment facility-wide. The posture transitions follow these counts mechanically: `OPEN` becomes `RESTRICTED` when one incident appears (count at least 1 and below 2), `RESTRICTED` becomes `CLOSED` when incidents reach the threshold (count at least 2), `CLOSED` falls back to `RESTRICTED` when incidents drop below the threshold but remain at least 1, and both `RESTRICTED` and `CLOSED` return to `OPEN` once the incident count reaches 0. A booking or enrollment forbidden by the current posture is rejected with `ERR_FACILITY_POSTURE_BLOCK`.

### 3.4. Requesting a Booking and the Forward-Looking Quote

The **Booking** is the central temporal entity, and it is polymorphic over its `kind`, which is one of `OPEN_SLOT`, `LESSON`, `TEAM_BLOCK`, or `PARTY`. A booking is requested by a `Member` (on their own behalf) or by a `FrontDesk` operator. The request names the `facility_id`, the `lane_id` of the primary reserved lane, the `member_id` of the booking member (who is also the payer), the `kind`, and a `pay_mode` that is one of `TOKEN`, `HOURLY`, or `MEMBERSHIP`, which pins the pricing variant. It also supplies a `start_utc` and an exclusive `end_utc`. Optionally it may name an `instructor_id` (the coach, required when the kind is `LESSON` and otherwise null), a `machine_id` (an optional pitching machine; null means none), a `lane_count` (lanes occupied, defaulting to 1), a list of `team_lane_ids` (extra lanes beyond the primary for a team block, empty otherwise), and a `party_guests` headcount (guest count for party pricing, defaulting to 0 and required to be zero or greater).

A booking's `duration_minutes` is the whole-minute difference between `end_utc` and `start_utc`, and it must be a positive whole multiple of the ten-minute slot length; a request whose duration is not a positive multiple of ten minutes is malformed. The `lane_count` must equal one plus the number of entries in `team_lane_ids`. A request that is malformed in any of these structural ways — missing required field, bad enum, an end instant not strictly after the start, a duration that is not a positive multiple of the slot, or a `lane_count` that disagrees with the team-lane list — is rejected with `ERR_INVALID_REQUEST`.

Requesting a booking does not charge, occupy, or confirm anything; it places the booking in `REQUESTED` status and stamps a provisional `quoted_cost_cents` using the **forward-looking** quote. The quote works in cents as follows. The lane base rate is the lane's own `hourly_rate_cents` if that override is set, otherwise the facility's `hourly_rate_cents`. The number of hours is the duration in minutes divided by sixty (kept exact and applied to cents). The lane portion is the base lane rate multiplied by the hours and by the `lane_count`, rounded half-up to whole cents. The coaching portion, applied only when the kind is `LESSON`, is the instructor's `rate_cents_per_hour` multiplied by the hours, rounded half-up to whole cents; for any other kind the coaching portion is zero. The machine portion, applied only when a `machine_id` is supplied, is a flat per-booking surcharge keyed on the machine's current `model`: 800 cents for `WHEEL`, 1200 cents for `ARM`, and 300 cents for `SOFT_TOSS`; with no machine the machine portion is zero. The party portion, applied only when the kind is `PARTY`, is a base of 15000 cents plus 1200 cents for each guest in `party_guests`; for any other kind the party portion is zero. The four rounded portions are summed into a gross amount. The membership-tier discount is then applied as a fraction of the gross — 0 for `NONE`, one-tenth for `BRONZE`, and one-quarter for `GOLD` — and `quoted_cost_cents` is the gross multiplied by one minus that discount fraction, rounded half-up once to whole cents. The forward-looking nature of the quote means it reads the lane rate, the member's tier, and the machine's model tier exactly as they stand at request time, and it never applies the peak-hour surcharge described in §3.5.

Until the booking is confirmed its `final_cost_cents` and `token_cost` are 0; both are computed only at confirm time. At request time the booking shape and resource availability are also checked: the machine, if named, must not be `OUT_OF_SERVICE`, and each occupied lane's current `maint_status` must be `AVAILABLE` — this reads the lane's present `maint_status`, which reflects any `OPEN` window on the lane, so a lane carrying any open window is unavailable regardless of whether the booked interval overlaps that window — failing which the request is rejected with `ERR_RESOURCE_UNAVAILABLE`. A `LESSON` without an active instructor, a `MEMBERSHIP` pay mode on a member whose tier is `NONE`, or a `PARTY` with a `party_guests` count below 1 is rejected with `ERR_BOOKING_SHAPE_INVALID`. A request is within the facility's open hours only when its start's minute-of-day is at or after `open_minute` and its end's minute-of-day is at or before `close_minute` (an end falling exactly at midnight is treated as minute 1440 of the same day), and the interval does not span across a UTC day boundary; a request whose interval falls outside this open hours window `[open_minute, close_minute)` on its day is rejected with `ERR_OUTSIDE_HOURS`.

### 3.5. Confirming a Booking: the Chronological Charge and Peak Pricing

Confirmation is where money and lane time actually change hands. A `Member` or `FrontDesk` operator confirms a `REQUESTED` booking, advancing it from `REQUESTED` to `CONFIRMED`, and the confirm request must carry `expected_lane_version` as described in §2.8. Confirmation runs the full gate of business validations, in the priority order of §2.11, before it commits.

Those gates, in order, are as follows, following the priority order of §2.11. The member's `waiver_ok` must be true, or the confirm is rejected with `ERR_WAIVER_REQUIRED`; this waiver gate is evaluated before the posture gate. The facility posture must permit this booking kind — `RESTRICTED` blocks `PARTY` and `TEAM_BLOCK`, `CLOSED` blocks every kind — or the confirm is rejected with `ERR_FACILITY_POSTURE_BLOCK`. The member's `no_show_strikes` must be strictly below the maximum of 3, or the confirm is rejected with `ERR_TOO_MANY_STRIKES`. The named machine, if any, must not be `OUT_OF_SERVICE`, and each occupied lane's current `maint_status` must be `AVAILABLE` — this gate reads the lane's present `maint_status`, which reflects any `OPEN` window on the lane, so a lane carrying any open window is unavailable regardless of whether the booked interval overlaps that window — or the confirm is rejected with `ERR_RESOURCE_UNAVAILABLE`. The stale-lane-version check of §2.8 is then evaluated, before the temporal-overlap test below. The booked interval plus the lane's `buffer_minutes` must not overlap any `CONFIRMED` or `CHECKED_IN` booking, nor any `OPEN` maintenance window, on each occupied lane — the buffer is an idle gap required after each booking before the next may start, applied as closed-interval adjacency — or the confirm is rejected with `ERR_LANE_TIME_CONFLICT`. The interval must fall within the facility's open hours, or the confirm is rejected with `ERR_OUTSIDE_HOURS`. The booking shape must remain valid (active instructor for a lesson, non-`NONE` tier for membership, at least one guest for a party), or it is rejected with `ERR_BOOKING_SHAPE_INVALID`. Finally the funds gate: for a `TOKEN` booking the member's `token_balance` must be at least the computed token cost, and for a `MEMBERSHIP` booking the member's projected `monthly_member_minutes_used` plus this booking's duration times `lane_count` must not exceed the monthly cap of 1200 minutes, or the confirm is rejected with `ERR_INSUFFICIENT_FUNDS`.

When the gates pass, confirmation computes `final_cost_cents` via the **chronological** charge. The chronological charge re-reads the lane rate as it stands at confirm time — so a maintenance-driven or manual rate change between request and confirm shifts the charge — and it adds a peak-hour multiplier that the forward-looking quote deliberately ignored. The charge determines whether the booking is in the peak window by looking at the start instant's minute-of-day: a start at or after 1020 minutes (17:00 UTC) and strictly before 1260 minutes (21:00 UTC) is a peak booking, and the peak multiplier is 1.5; outside that window the multiplier is 1.0. The lane portion is the base lane rate multiplied by the hours, by the `lane_count`, and by the peak multiplier, rounded half-up to whole cents. The coaching, machine, and party portions are computed exactly as in the forward-looking quote (coaching only for `LESSON`, the flat `model`-keyed machine surcharge only when a machine is named, the 15000-cent base plus 1200 cents per guest only for `PARTY`), each rounded half-up to whole cents. The four portions are summed, the membership-tier discount fraction (0, one-tenth, or one-quarter) is applied, and `final_cost_cents` is the discounted gross rounded half-up once to whole cents. Because the quote never applies the peak multiplier, a peak-hour hourly or token booking ends with `final_cost_cents` greater than its `quoted_cost_cents`; an off-peak booking ends with the two equal unless the lane rate changed between request and confirm.

Confirmation then settles payment and occupies time. When `pay_mode` is `TOKEN`, the booking's `token_cost` is the `final_cost_cents` divided by the facility's `token_price_cents`, rounded **up** to the next whole token — and for any booking whose `final_cost_cents` is above zero the token cost is never less than 1 — and that many tokens are subtracted from the member's `token_balance`. When `pay_mode` is `MEMBERSHIP`, the member's `monthly_member_minutes_used` is increased by the booking's `duration_minutes` multiplied by its `lane_count`. In every case the lane interval `[start, end)` is marked occupied for future overlap checks, and the confirmation increments the parent `Lane`'s `version` by one. A `FacilityManager` may instead **reject** a `REQUESTED` booking, moving it from `REQUESTED` to `REJECTED`; rejection applies no charge because charging happens only on confirmation, and the quote is simply discarded.

### 3.6. Check-In, Completion, and Machine Wear

Once confirmed, a booking is checked in by a `FrontDesk` operator, advancing it from `CONFIRMED` to `CHECKED_IN`. Check-in is permitted only while the clock falls within the window beginning 30 minutes before the booking's `start_utc` and ending at its `end_utc` — that is, from `start_utc` minus the early-check-in allowance of 30 minutes up to but not including `end_utc`; a check-in attempted outside this window is rejected with `ERR_INVALID_STATE`. This window check is applied first, and only then is the member's `waiver_ok` re-evaluated; the member's `waiver_ok` must still be true at check-in, or the request is rejected with `ERR_WAIVER_REQUIRED`. Completion is the next step: a `FrontDesk` operator completes a `CHECKED_IN` booking, advancing it from `CHECKED_IN` to `COMPLETED`, and completion is permitted only when the clock is at or after the booking's `start_utc`; a completion attempted before `start_utc` is rejected with `ERR_INVALID_STATE`.

Completion is where machines wear. If the booking named a `machine_id`, completion increases that machine's `pitch_count` by 1000 pitches per session and recomputes the machine's `status` from the new count. A machine's `status` is purely a threshold over `pitch_count`: at a count of at least 10000 the machine is `OUT_OF_SERVICE`; otherwise at a count of at least 5000 the machine is `DEGRADED`; otherwise it is `OPERATIONAL`. The boundaries are inclusive — a machine that reaches exactly 5000 pitches (for example after five completed sessions of 1000 pitches each) flips to `DEGRADED` at 5000 rather than at 5001, and a machine that reaches exactly 10000 (for example after ten completed sessions) flips to `OUT_OF_SERVICE` at 10000. A `DEGRADED` machine may still be used by new bookings with no extra surcharge beyond its model tier, but once a machine is `OUT_OF_SERVICE`, any booking creation referencing that `machine_id` is rejected until the count is reset to 0 by resolving the lane's maintenance. As noted in §3.3, resolving the last open window on a lane resets the installed machine's `pitch_count` to 0 and returns its `status` to `OPERATIONAL`.

### 3.7. Cancellation, No-Shows, and Refunds

A `Member`, a `FrontDesk` operator, or the system may cancel a booking that is in `REQUESTED` or `CONFIRMED` status, moving it to `CANCELLED`. The financial consequences depend on what the booking was. A booking cancelled from `REQUESTED` was never charged, so there is nothing to refund. A booking cancelled from `CONFIRMED` under `TOKEN` pay mode triggers the **time-sensitive refund waterfall**: the system computes the whole minutes from the current clock to the booking's `start_utc`; if that is at least the refund cut-off of 120 minutes, the full `token_cost` is refunded to the member's `token_balance`; otherwise the facility keeps a forfeit equal to the `token_cost` multiplied by one-half, rounded **up** to a whole token, and the member is refunded the `token_cost` minus that forfeit. A booking cancelled from `CONFIRMED` under `MEMBERSHIP` pay mode restores the member's minutes fully — the booking's `duration_minutes` times `lane_count` is subtracted back from `monthly_member_minutes_used`, with no forfeit. In every cancellation the occupied lane interval is released. The same cancel path is what the `CRITICAL`-maintenance cascade of §3.3 invokes when it cancels overlapping confirmed bookings, so those cascade-cancelled bookings are refunded by the identical rules.

A confirmed booking that is never checked in becomes a no-show. During the run-ops sweep of §2.6, any booking still `CONFIRMED` whose `end_utc` is at or before the current clock is transitioned from `CONFIRMED` to `NO_SHOW`; this increases the member's `no_show_strikes` by one, applies no refund (the token cost or membership minutes are forfeited), and releases the lane interval. Accumulated strikes are what the eighth-priority confirm gate checks: once a member's `no_show_strikes` reaches the maximum of 3, further confirmations are blocked with `ERR_TOO_MANY_STRIKES` until the next epoch boundary clears the strikes.

### 3.8. Programs, Enrollment, and Withdrawal

Leagues and clinics are modeled as **Programs**, created by a `FacilityManager`. A program names its `facility_id` and the `lane_id` reserved for each of its sessions, a `kind` that is either `LEAGUE` or `CLINIC`, a `capacity` (the maximum number of enrolled members, required to be at least 1), a flat `price_cents` charged per member at enrollment (required to be zero or greater), and a first-session interval given as `session_start_utc` and an exclusive `session_end_utc` (which must be strictly after the start). A new program opens with `status` `OPEN` and `enrolled_count` 0. A program's `enrolled_count` is the number of its enrollments in `ENROLLED` status, and its `status` is `FULL` when the enrolled count equals capacity, `CLOSED` when a manager has explicitly closed it, and `OPEN` otherwise. A `FacilityManager` may close a program, moving it from `OPEN` or `FULL` to `CLOSED`; existing `ENROLLED` enrollments stay enrolled, but new enrollment is blocked.

Enrolling a member creates an **Enrollment**, the junction between a member and a program, performed by a `Member` (enrolling self) or a `FrontDesk` operator. The enrollment is created against a specific program identified by `program_id` in the path; the request names the `member_id` and must carry `expected_program_version` as described in §2.8. An enrollment records its owning `facility_id` and the `program_id` of the program it joins. Enrollment is allowed only when the program has an open seat — its `enrolled_count` is below `capacity` and its `status` is not `CLOSED` — and the member is not already `ENROLLED` in that program; a request that violates any of these is rejected with `ERR_PROGRAM_FULL`. A `CLOSED` facility posture also blocks enrollment with `ERR_FACILITY_POSTURE_BLOCK`. A successful enrollment is born `ENROLLED`, records `charged_cents` equal to the program's `price_cents`, increases the program's `enrolled_count` by one, flips the program from `OPEN` to `FULL` if the new count reaches capacity, and increments the parent `Program`'s `version` by one. When the enrolled count reaches capacity the program transitions `OPEN → FULL` and any further enrollment is rejected with `ERR_PROGRAM_FULL`.

Withdrawal reverses an enrollment. A `Member` (on their own enrollment) or a `FacilityManager` may withdraw an `ENROLLED` enrollment, moving it to `WITHDRAWN`. Withdrawal decreases the program's `enrolled_count` by one and, if the program was `FULL`, returns it from `FULL` to `OPEN`. The member is refunded not in cents but in wallet tokens: the `charged_cents` is converted to tokens by dividing by the facility's `token_price_cents` and rounding **down** to the nearest whole token, and that many tokens are added to the member's `token_balance`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action such as confirming, checking in, completing, cancelling, resolving, closing, or withdrawing, as well as wallet top-ups and epoch advances — return a `200 OK` status code. Enrolling a member into a program creates a new enrollment resource and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/facilities` | Create a facility (posture OPEN, epoch 0) | FacilityManager |
| GET | `/v1/facilities` | List facilities | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/facilities/{facility_id}` | Get a facility including computed posture and incident count | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/facilities/{facility_id}/run-ops` | Advance the epoch: no-show sweep, reset member minutes and strikes, recompute derived fields | FacilityManager |
| POST | `/v1/lanes` | Create a lane | FacilityManager |
| GET | `/v1/lanes/{lane_id}` | Get a lane including computed maint_status | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/lanes` | List lanes; filter by facility_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/machines` | Install a pitching machine on a lane | FacilityManager |
| GET | `/v1/machines/{machine_id}` | Get a machine including computed status and pitch_count | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/machines` | List machines; filter by facility_id and/or lane_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/maintenance` | Open a maintenance window (ROUTINE or CRITICAL) | FacilityManager |
| GET | `/v1/maintenance/{window_id}` | Get a maintenance window | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/maintenance` | List maintenance windows; filter by facility_id and/or lane_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/maintenance/{window_id}/resolve` | Resolve a maintenance window | FacilityManager |
| POST | `/v1/members` | Register a member | FacilityManager, FrontDesk |
| GET | `/v1/members/{member_id}` | Get a member including wallet, minutes, strikes, waiver status | FacilityManager, FrontDesk, Member |
| GET | `/v1/members` | List members; filter by facility_id | FacilityManager, FrontDesk |
| POST | `/v1/members/{member_id}/wallet/top-up` | Add tokens to a member's wallet | FacilityManager, FrontDesk |
| POST | `/v1/waivers` | Sign a waiver for a member | FacilityManager, FrontDesk, Member |
| GET | `/v1/waivers/{waiver_id}` | Get a waiver | FacilityManager, FrontDesk, Member |
| GET | `/v1/waivers` | List waivers; filter by member_id and/or facility_id | FacilityManager, FrontDesk, Member |
| POST | `/v1/waivers/{waiver_id}/void` | Void a signed waiver | FacilityManager |
| POST | `/v1/instructors` | Create an instructor | FacilityManager |
| GET | `/v1/instructors/{instructor_id}` | Get an instructor | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/instructors` | List instructors; filter by facility_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/bookings` | Request a booking (REQUESTED; computes forward-looking quote) | Member, FrontDesk |
| GET | `/v1/bookings/{booking_id}` | Get a booking including quoted/final cost and token cost | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/bookings` | List bookings; filter by facility_id, lane_id, member_id, instructor_id, machine_id, team_lane_ids, status | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/bookings/{booking_id}/confirm` | Confirm a booking (OCC on lane; chronological charge) | Member, FrontDesk |
| POST | `/v1/bookings/{booking_id}/reject` | Reject a requested booking | FacilityManager |
| POST | `/v1/bookings/{booking_id}/check-in` | Check in a confirmed booking | FrontDesk |
| POST | `/v1/bookings/{booking_id}/complete` | Complete a checked-in booking | FrontDesk |
| POST | `/v1/bookings/{booking_id}/cancel` | Cancel a requested or confirmed booking | Member, FrontDesk |
| POST | `/v1/programs` | Create a league/clinic program | FacilityManager |
| GET | `/v1/programs/{program_id}` | Get a program including enrolled count and status | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/programs` | List programs; filter by facility_id and/or lane_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/programs/{program_id}/close` | Close a program to new enrollment | FacilityManager |
| POST | `/v1/programs/{program_id}/enrollments` | Enroll a member into a program (OCC on program) | Member, FrontDesk |
| GET | `/v1/programs/{program_id}/enrollments` | List enrollments of a program; filter by member_id | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/enrollments/{enrollment_id}` | Get an enrollment | FacilityManager, FrontDesk, Member, Instructor |
| GET | `/v1/enrollments` | List enrollments; filter by facility_id, program_id, member_id | FacilityManager, FrontDesk, Member, Instructor |
| POST | `/v1/enrollments/{enrollment_id}/withdraw` | Withdraw an enrollment | Member, FacilityManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied instant | FacilityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_FACILITY_POSTURE_BLOCK` | 422 Unprocessable Entity |
| `ERR_TOO_MANY_STRIKES` | 422 Unprocessable Entity |
| `ERR_RESOURCE_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_LANE_TIME_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_HOURS` | 422 Unprocessable Entity |
| `ERR_BOOKING_SHAPE_INVALID` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_PROGRAM_FULL` | 409 Conflict |
| `ERR_STALE_LANE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
