# Watersports School API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Watersports School API, a back-office platform for operating a surf, sailing, windsurfing, and kayak instruction business. A school sells structured course programs that progress through ranked skill levels, schedules water sessions that depend on tide windows and weather, and certifies students who complete certification tracks. Around this teaching core sit the practical concerns of running a beachfront operation: instructor-to-student ratios that must be honoured for safety, swim-test and age gates that protect novices, liability waivers that expire, equipment that must be rented and returned without double-booking, and memberships that grant discounts and makeup credits when the school cancels a class.

The platform must reconcile two recurring tensions. The first is temporal: nearly every safety and pricing decision is read against a logical clock — a student's age, a waiver's validity, a session's tide window, and the lead time before a refund tier applies are all evaluated against "now" as the server understands it, never against wall-clock time. The second is allocative: seats in a session, instructors across a timetable, and equipment across rental windows are scarce, and the system must allocate them under concurrent demand without overbooking. The remainder of this document defines the entities, their lifecycles, the calculations that price enrollments and rentals, the validations that protect students and resources, and the precise API contract through which all of this is exercised.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. The system recognizes exactly three roles: `SchoolAdmin`, `Instructor`, and `Student`. A request missing the `X-User-Role` header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN`.

The three roles differ not only in what they may do but in how their `X-User-ID` is interpreted. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`, and an administrator has the full administrative surface over schools and every child resource. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks compare a resource's instructor reference to this value — specifically, an instructor may only start, complete, or check students into a session whose `instructor_id` equals their own `X-User-ID`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks compare the `student_id` reachable from the target resource to this value — a student may only act on enrollments, bookings, rentals, waivers, and memberships that resolve back to their own student record. A `Student` or `Instructor` who targets a resource they do not own or scope to is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses surface `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock

The server maintains a single logical clock that is the authoritative "now" for every time-dependent rule in the system. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an administrator explicitly moves it, it stays at that default and never falls back to the host's wall-clock time. An administrator advances or rewinds the clock by supplying a target instant as `to_iso8601`; the endpoint returns the resulting `current_utc`. Every age computation, waiver validity check, tide-window evaluation, rental-window check, and refund lead-time calculation reads this clock rather than real time. Because several derived fields — a student's `age_years` and `waiver_status`, a waiver's expiry, an equipment item's availability — depend on it, advancing the clock can change what subsequent reads return even with no other mutation.

### 2.5. Common Resource Properties and Versioning

Most resources in the system share a common set of system-managed fields. Each carries an `id`, a server-minted UUID used purely as identity and never prefixed with a type tag. Each carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was created. Each also carries an `updated_at` timestamp, refreshed on every mutation including cascaded mutations triggered by operations on other resources, and a `version` integer that begins at 1 on creation and increases by exactly 1 on every mutation.

One entity is deliberately leaner. A `CertificationCard` is an immutable issuance record: it carries only `id` and `created_at`, and has no `updated_at` and no `version` field at all. All other resources — schools, courses, course levels, instructors, equipment, students, waivers, memberships, enrollments, sessions, bookings, and rental agreements — carry the full `id`, `created_at`, `updated_at`, `version` quartet.

### 2.6. Optimistic Concurrency Control

Two creation operations guard a shared parent resource against the lost-update problem by requiring the client to declare the parent version it last observed. These are the only two write operations that take a version field; no other endpoint accepts one.

When booking an enrollment into a session, the request must include `expected_session_version` carrying the client's last observed `version` of the target `Session`. If the session's current `version` no longer matches — because some other writer has booked a seat and advanced the session's version since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from claiming a seat against a session view that is already stale, where the seat it believes free may already be filled.

When creating a rental agreement, the request must include `expected_equipment_version` carrying the client's last observed `version` of the target `EquipmentItem`. If the equipment item's current `version` no longer matches — because another rental create on the same item has advanced its version since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from reserving a window against a stale view in which that window may already be taken. Two further administrative toggles, setting a school's storm advisory and toggling an equipment item into or out of maintenance, also carry version fields and are described in their own subsections below; they likewise reject a version mismatch with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Hierarchical Consistency and Cascades

Many operations mutate more than one resource. Whenever an operation changes a child in a way that affects a parent's derived state, the parent is mutated in the same breath — its `updated_at` is refreshed and its `version` is incremented. Adding or removing a booking on a session, for example, is itself a mutation of that session: it recomputes the session's `enrolled_count` and `required_instructors` and increments the session's `version`. The state-machine subsections of §3 spell out, for each transition, exactly which sibling and parent resources are touched; the governing principle here is that no cascade leaves a derived field stale, and every entity a cascade touches has its `updated_at` and `version` advanced.

### 2.8. Reverse-Reachability of Flat Collections

All collections are addressed as flat, top-level lists; parent scope is never embedded in the URL path but is instead carried as a body field at creation and as an optional query filter on the corresponding list endpoint. A course belongs to a school through its `school_id`, a level to a course through its `course_id` (with `school_id` copied down from the parent course), a session to a school and level through `school_id` and `course_level_id`, and so on. The list endpoints expose these links as filters: courses can be filtered by `school_id`; levels by `course_id` or `school_id`; instructors, equipment, students, and enrollments by `school_id` (enrollments additionally by `student_id`, `course_level_id`, or `membership_id`); waivers by `student_id`; memberships by `student_id`; sessions by `school_id`, `course_level_id`, or `instructor_id`; bookings by `session_id` or `enrollment_id`; rentals by `school_id`, `student_id`, `equipment_item_id`, or `session_id`; and certification cards by `student_id`, `enrollment_id`, or `course_level_id`. When a request targets a resource by its `{id}` in the path and no such resource exists, the response is `ERR_NOT_FOUND`; likewise, when a create body names a foreign key that does not resolve to an existing resource within the same school, the create is rejected with `ERR_NOT_FOUND`.

### 2.9. Monetary Values, Rounding, and Precision

All money is held in integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up to a whole number of cents — that is, a value exactly halfway between two cents rounds to the larger. Each calculation subsection in §3 states precisely where rounding is applied, because the placement matters: some prices round once at the very end (sum-then-round) and one rounds each line first and then sums (round-per-line). Percentages such as group and membership discounts are applied as exact decimal multipliers before the rounding step; they are never pre-rounded into cents.

### 2.10. Validation Ordering

When several validations could fire on a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Existence checks follow — first that any path `{id}` resolves (`ERR_NOT_FOUND`), then that every foreign key in the body resolves within the same school (`ERR_NOT_FOUND`). Resource-ownership scoping for entity-backed roles comes next (`ERR_NOT_RESOURCE_OWNER`). Then, on the two OCC-guarded creates and the two versioned admin toggles, the optimistic-concurrency check runs (`ERR_STALE_VERSION`). Only after these do state-transition legality (`ERR_INVALID_STATE`) and the domain-specific business rules — storm closure, waivers, age, swim test, certification, prerequisites, tide windows, scheduling overlaps, capacity, makeup credits, maintenance, payment, and attendance — apply. Within those business rules the relative order is given alongside each workflow in §3; where two could both fire on the same operation, the order stated there is authoritative.

## 3. Business Logic & Workflows

### 3.1. Schools, Courses, Levels, and the Teaching Catalog

A `SchoolAdmin` stands up a school by supplying its `name` and, optionally, a `timezone` (an informational IANA label that defaults to `UTC` and does not affect any calculation). A new school opens with `storm_advisory_active` false, an `operating_status` of `OPEN`, an `open_session_count` of 0, and `version` 1. The school's `operating_status` is fully derived from its advisory flag: it reads `STORM_CLOSED` exactly when `storm_advisory_active` is true, and `OPEN` otherwise. The `open_session_count` is likewise derived — it is the number of this school's sessions whose status is `SCHEDULED`, `WEATHER_HOLD`, or `IN_PROGRESS`.

Storm advisories are set and cleared through a single administrative toggle that supplies `active` together with `expected_school_version`. The supplied `active` boolean is written to `storm_advisory_active`; `operating_status` becomes `STORM_CLOSED` when `active` is true and `OPEN` when it is false; and the school's `version` is incremented by 1. As noted in §2.6, this toggle is OCC-guarded: a mismatch between `expected_school_version` and the school's current `version` is rejected with `ERR_STALE_VERSION`.

Within a school, an administrator defines courses. A course is created with its `school_id`, a `discipline` of `SURF`, `SAIL`, `WINDSURF`, or `KAYAK`, a `title`, and a `kind` of either `LESSON` or `CERTIFICATION`. Both `discipline` and `kind` are immutable after creation, and a course begins with `status` `ACTIVE` (the other possible value being `RETIRED`). The distinction in `kind` carries weight downstream: a `CERTIFICATION` course causes a certification card to be issued when an enrollment under it completes, whereas a `LESSON` course never does.

Each course is subdivided into ranked levels. A level is created against its `course_id`, and the server copies the parent course's school down into the level's `school_id`. A level carries a `rank` (an ordinal within the course, at least 1, unique among that course's levels, with 1 denoting the beginner level), a `name`, a `max_students_per_instructor` ratio cap of at least 1, a `base_price_cents` per-session list price of at least 0, a `min_age` minimum student age in whole years of at least 0, a `requires_swim_test` flag that defaults to true, and a `required_equipment_type` of `BOARD`, `SAIL_RIG`, `KAYAK`, or `NONE`. Any level whose `rank` is greater than 1 carries an implicit prerequisite: it is the rank-1 level of the same course, and a student may only enroll in it after completing that rank-1 level (see §3.4). Simple shape violations on these inputs — a `rank` below 1, a negative price, a malformed body, a bad enum — are rejected with `ERR_VALIDATION`.

### 3.2. Instructors and Equipment

Instructors are registered by an administrator with a `school_id`, a `full_name`, and a `certified_disciplines` array drawn from the set of disciplines (`SURF`, `SAIL`, `WINDSURF`, `KAYAK`) the instructor is qualified to teach. An instructor opens with `status` `ACTIVE`, the alternative being `SUSPENDED`. The acting instructor's own `id` is the value their requests carry in `X-User-ID`.

Equipment items are added by an administrator with a `school_id`, an `equipment_type` of `BOARD`, `SAIL_RIG`, or `KAYAK` (immutable once set), a human-readable `asset_tag`, an `hourly_rate_cents` of at least 0, and a refundable `deposit_cents` of at least 0. An item's `status` is derived and starts at `AVAILABLE`; it reads `RENTED` while a rental agreement on it is in its active state, and `MAINTENANCE` while an administrator has toggled it out of service. That maintenance toggle supplies `in_maintenance` together with `expected_equipment_version`. Setting `in_maintenance` to true moves the item to `MAINTENANCE`, but only from `AVAILABLE`; setting it false returns the item to `AVAILABLE`; either way the item's `version` is incremented by 1. The toggle is OCC-guarded, so a mismatch on `expected_equipment_version` is rejected with `ERR_STALE_VERSION`.

### 3.3. Students, Swim Tests, and Waivers

A student is registered with a `school_id`, a `full_name`, and a `birthdate` (an ISO 8601 date of birth). On registration the student's `swim_test_status` is `UNTESTED` and `waiver_status` is `NONE`. The student's `age_years` is not stored as a fixed value but computed as the number of whole years from `birthdate` to the current logical-clock date, so advancing the clock past a birthday raises the reported age. A student record is the entity behind the `Student` role: the student's own `id` is what their requests carry in `X-User-ID`.

Swim competency is recorded by an administrator through a swim-test operation that supplies a `result`, moving `swim_test_status` to `PASSED` or `FAILED`. This matters at enrollment time for levels that require a passed swim test.

A waiver is a signed liability release with an expiry. Signing one supplies the `student_id`, the `signed_by` name (the guardian's name when a minor is involved), an `is_guardian` flag that defaults to false and is set true when a guardian signs for a minor, and an `expires_at` instant. A newly signed waiver has `status` `SIGNED`, and signing it recomputes the student's derived `waiver_status` to `SIGNED`. A student's `waiver_status` is one of `NONE`, `SIGNED`, `EXPIRED`, or `REVOKED`, derived solely from the student's single latest waiver — the one with the greatest `created_at` (ties broken by insertion order) — and equal to that waiver's effective status; `NONE` only when the student has no waiver at all, and the system does not fall back to any earlier waiver. Two events drive it away from `SIGNED`. First, an administrator or the student may revoke a signed waiver: this is permitted only while the waiver's `status` is `SIGNED`, moves it to `REVOKED`, and recomputes the student's `waiver_status` so that if the revoked waiver was the latest the status becomes `REVOKED` (it does not skip back to an earlier signed waiver). Second, when the logical clock reaches or passes a waiver's `expires_at`, that waiver is treated as `EXPIRED` (observed on the next read or check-in) and the student's `waiver_status` is recomputed accordingly. Attempting to revoke a waiver that is not in `SIGNED` is rejected with `ERR_INVALID_STATE`.

### 3.4. Memberships and Enrolling a Student

A membership ties a student to a discount tier and accrues makeup credits. It is created with a `student_id` and a `tier` of `BASIC` or `PREMIUM`, opening with `status` `ACTIVE` (the alternative being `CANCELLED`) and a `makeup_credit_balance` of 0. The tier governs an enrollment discount — `BASIC` grants five percent and `PREMIUM` grants fifteen percent — and applies only while the membership's `status` is `ACTIVE`. The `makeup_credit_balance` is a whole count of makeup-session credits: it rises by one each time the school cancels a booking on a member's enrollment and falls by one each time the member books a makeup session.

Enrolling a student creates a package. The request supplies the `school_id`, the `student_id`, the `course_level_id`, an optional `membership_id` (null for non-members; when supplied it must resolve to a membership belonging to that same `student_id`, otherwise the create is rejected with `ERR_NOT_FOUND`), a `planned_sessions` count of at least 1, and a `party_size` of at least 1 representing the booked group size used for the group-discount tier on the estimate. A new enrollment opens with two independent status dimensions: `progress_status` is `ACTIVE` and `payment_status` is `UNPAID`. Its `estimated_price_cents` is computed at creation (see §3.8), while `final_price_cents` and `refund_cents` remain null until the enrollment completes or is refunded, and `attended_count` starts at 0.

Enrollment is the system's most heavily gated operation, and its safety checks are evaluated in this order. First, if the school is storm-closed the enrollment is still permitted — storm closure does not block enrolling — but the remaining gates do apply. The student must have a `waiver_status` of `SIGNED`, or the enrollment is rejected with `ERR_WAIVER_REQUIRED`. The student's `age_years` must be at least the level's `min_age`, or the enrollment is rejected with `ERR_AGE_REQUIREMENT_NOT_MET`. If the level's `requires_swim_test` is true, the student's `swim_test_status` must be `PASSED`, or the enrollment is rejected with `ERR_SWIM_TEST_REQUIRED`. Finally, if the target level's `rank` is greater than 1, the student must already hold a `COMPLETED` enrollment at the rank-1 level of the same course, or the enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`.

### 3.5. The Enrollment Lifecycle: Two Independent Dimensions

An enrollment evolves along two dimensions that move independently of one another on the same record. The progress dimension (`progress_status`) runs `ACTIVE`, then either `COMPLETED` or `WITHDRAWN`. The payment dimension (`payment_status`) runs `UNPAID`, then `PAID`, then `REFUNDED`. Neither directly forces the other, but certain transitions read across the boundary as a gate.

Paying an enrollment is permitted by an administrator or the owning student. It requires that `payment_status` be `UNPAID` and that `progress_status` is not `WITHDRAWN`; it moves `payment_status` to `PAID` and leaves `progress_status` untouched. An attempt to pay from any other payment state is rejected with `ERR_INVALID_STATE`.

Withdrawing an enrollment is permitted by an administrator or the owning student and requires `progress_status` to be `ACTIVE`. It moves `progress_status` to `WITHDRAWN` and cascades: every booking on this enrollment that is `BOOKED` or `CHECKED_IN` is cancelled. Because withdrawal is student-caused, these cancellations grant no makeup credit. Each cancelled booking in turn decrements its session's `enrolled_count` and triggers a recompute of that session's `required_instructors`.

Completing an enrollment is restricted to an administrator. It requires that `progress_status` be `ACTIVE`, that `payment_status` already be `PAID` (a cross-dimension gate — an unpaid enrollment cannot complete), and that the enrollment's `attended_count` be at least its `planned_sessions`. The payment gate, when unmet, is reported as `ERR_PAYMENT_REQUIRED`; the attendance gate, when unmet, is reported as `ERR_ATTENDANCE_INCOMPLETE`; the payment requirement is evaluated before the attendance requirement. On success, `progress_status` becomes `COMPLETED`, `final_price_cents` is computed chronologically (see §3.8), and — if the parent course's `kind` is `CERTIFICATION` and no card has yet been issued for this enrollment — a certification card is issued as a cross-entity cascade (see §3.9).

Refunding closes the payment dimension. It is restricted to an administrator and requires that `payment_status` be `PAID` and that `progress_status` already be `WITHDRAWN` (the second cross-dimension gate — only a withdrawn enrollment may be refunded). On success, `payment_status` becomes `REFUNDED` and `refund_cents` is computed by the lead-time waterfall (see §3.8). A refund attempted from any other payment state, or any of these transitions attempted from an ineligible state, is rejected with `ERR_INVALID_STATE`.

### 3.6. Scheduling Sessions and the Weather Loop

A session is a single timetabled class on the water, scheduled by an administrator. Its creation supplies the `school_id`, the `course_level_id`, the lead `instructor_id`, the `starts_at` and `ends_at` instants (the end being exclusive), the `tide_window_start` and `tide_window_end` instants bounding the usable tide (the window end being exclusive), and a `capacity` of at least 1. A new session opens with `status` `SCHEDULED`, an `enrolled_count` of 0, a `required_instructors` of 0, and it increments the parent school's `open_session_count`.

Scheduling enforces four checks. The school must not be storm-closed: if `operating_status` is `STORM_CLOSED`, scheduling is rejected with `ERR_SCHOOL_STORM_CLOSED`. The lead instructor must be certified for the discipline of the level's course — that discipline must appear in the instructor's `certified_disciplines` — or the request is rejected with `ERR_INSTRUCTOR_NOT_CERTIFIED`. The tide window must fully contain the session interval, meaning `tide_window_start` is at or before `starts_at` and `ends_at` is at or before `tide_window_end`; otherwise the request is rejected with `ERR_TIDE_WINDOW_INVALID`. And the new session interval must not overlap any other non-terminal session of the same instructor: the interval runs from `starts_at` up to but not including `ends_at` (half-open), so two sessions that merely touch at an endpoint do not conflict and no buffer is added, but any genuine overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`.

A session's `status` runs `SCHEDULED`, `WEATHER_HOLD`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. The weather loop is cyclic. An administrator may place a `SCHEDULED` session on `WEATHER_HOLD`; this releases no bookings but blocks check-in and start while held. From `WEATHER_HOLD` the administrator may clear the hold back to `SCHEDULED`, provided the school is not storm-closed (`storm_advisory_active` must be false), a storm-closed school blocking the clear with `ERR_SCHOOL_STORM_CLOSED`; this reopens check-in and start, and the hold-and-clear cycle may repeat any number of times before the session starts. A hold or clear attempted from the wrong status is rejected with `ERR_INVALID_STATE`.

Starting a session, permitted to an administrator or the lead instructor, moves it from `SCHEDULED` to `IN_PROGRESS`. It requires the session to be `SCHEDULED`, the school to be `OPEN` (a storm-closed school blocks the start with `ERR_SCHOOL_STORM_CLOSED`), and the logical clock to fall within the tide window — at or after `tide_window_start` and strictly before `tide_window_end`, a clock outside that window blocking the start with `ERR_INVALID_STATE`. The school's `open_session_count` is unchanged by start, since a session in progress is still counted.

Completing a session, also permitted to an administrator or the lead instructor, moves it from `IN_PROGRESS` to `COMPLETED` and forks every still-open booking. Each booking that was `CHECKED_IN` becomes `ATTENDED`, and the owning enrollment's `attended_count` rises by one for each. Each booking that was still merely `BOOKED` becomes `NO_SHOW` and earns no attendance credit. Completion also decrements the school's `open_session_count`.

Cancelling a session is an administrator action available while the session is `SCHEDULED` or `WEATHER_HOLD`. It moves the session to `CANCELLED` and cascades in two hops: first, every non-terminal booking on the session — those in `BOOKED` or `CHECKED_IN` — is cancelled; second, for each cancelled booking whose enrollment carries an active membership, that membership's `makeup_credit_balance` rises by one, because a school-caused cancellation grants the member a makeup. Cancellation also decrements the school's `open_session_count`. Starting, completing, holding, clearing, or cancelling a session from an ineligible status is rejected with `ERR_INVALID_STATE`.

### 3.7. Booking, Check-In, and the Attendance Fork

A booking places one enrollment into one session. Creating it supplies the `session_id`, the `enrollment_id`, the mandatory `expected_session_version`, and an optional `use_makeup_credit` flag. As described in §2.6, the create is OCC-guarded against the session's `version`, rejecting a stale view with `ERR_STALE_VERSION`. The session must have room: its `enrolled_count` (the number of its bookings in `BOOKED`, `CHECKED_IN`, or `ATTENDED`) must be strictly less than its `capacity`, or the booking is rejected with `ERR_SESSION_FULL`. When `use_makeup_credit` is true, the owning enrollment's membership must have a `makeup_credit_balance` of at least 1, or the booking is rejected with `ERR_NO_MAKEUP_CREDIT`; on success the booking's `is_makeup` is set true and the membership's `makeup_credit_balance` falls by one. A successful booking opens with `status` `BOOKED`, increments the session's `enrolled_count`, recomputes the session's `required_instructors`, and increments the session's `version`.

A booking's `status` runs `BOOKED`, `CHECKED_IN`, `ATTENDED`, `NO_SHOW`, or `CANCELLED`, the last three terminal. Checking a student in, permitted to an administrator or the session's lead instructor, moves a `BOOKED` booking to `CHECKED_IN`. It requires that the booking be `BOOKED`, that the parent session be `IN_PROGRESS`, that the student (reached through the booking's enrollment) have a `waiver_status` of `SIGNED` — otherwise `ERR_WAIVER_REQUIRED` — and that the school be `OPEN`, since a storm-closed school blocks check-in with `ERR_SCHOOL_STORM_CLOSED`. A check-in attempted while the booking is not `BOOKED`, or while the parent session is not `IN_PROGRESS`, is rejected with `ERR_INVALID_STATE`; the booking-state check precedes the session-state check, and both precede the storm-closure and waiver gates (per §2.10 the storm gate is evaluated before the waiver gate).

A booking may be cancelled by an administrator or the owning student while it is `BOOKED` or `CHECKED_IN`. Cancelling moves it to `CANCELLED`, decrements its session's `enrolled_count`, recomputes that session's `required_instructors`, and increments the session's `version`. The system also cancels bookings on its own behalf as the session-cancel and enrollment-withdraw cascades described above; a session-cancel cascade grants makeup credit while an enrollment-withdraw cascade does not. The terminal attendance outcomes — `ATTENDED` versus `NO_SHOW` — are never set directly by a client; they are produced only by the system when the parent session completes, as the fork in §3.6 describes.

### 3.8. Pricing: Estimate, Final Price, Refund, Ratio, and Rental Fee

Five calculations govern the money and staffing in the system. All discounts share two helper schedules. The group-discount percentage is determined by a party count: a count of 1 or fewer attracts no discount; a count of 2 or 3 attracts ten percent; a count of 4, 5, or 6 attracts twenty percent; and a count of 7 or more attracts thirty percent. The membership percentage is zero when there is no active membership, five percent for a `BASIC` tier, and fifteen percent for a `PREMIUM` tier.

**Enrollment estimate (forward-looking, at creation).** When an enrollment is created, its `estimated_price_cents` is computed forward over the whole planned package. The gross is the `planned_sessions` count multiplied by the level's `base_price_cents`. The group discount is applied once over that gross, using the single supplied `party_size` to select the group percentage — the amount after the group discount is the gross multiplied by one minus that group percentage. The membership discount is then applied to that intermediate amount, multiplying it by one minus the membership percentage (the tier taken from the membership only when a `membership_id` is supplied and that membership's `status` is `ACTIVE`, otherwise treated as no membership). The result is rounded half up to whole cents exactly once, at the very end — this is a sum-then-round calculation, with a single rounding step.

**Enrollment final price (chronological, at completion).** When an enrollment completes, its `final_price_cents` is computed over only the sessions the student actually attended, and it diverges deliberately from the estimate in three ways: the group tier is recomputed per session from the actual attended group size, rounding is applied per line rather than once, and only `ATTENDED` bookings count. The enrollment's `ATTENDED` bookings are processed in chronological order of their session's `starts_at` ascending, breaking ties by the session's `created_at` ascending (never by id). For each attended booking, the actual attended group size of that session is the count of `ATTENDED` bookings on that same session (no-shows excluded), which selects a per-session group percentage; the line for that booking is the level's `base_price_cents` multiplied by one minus that per-session group percentage, rounded half up to whole cents. These per-line amounts are summed into a subtotal. The membership discount is then applied to the subtotal — the subtotal multiplied by one minus the membership percentage — and that result is rounded half up to whole cents once more. This is round-per-line, then sum, then a final rounding after the membership discount.

**Enrollment refund (lead-time waterfall, at refund).** When a withdrawn, paid enrollment is refunded, its `refund_cents` is set by the lead time before its earliest remaining session. Because the prerequisite withdrawal has already cancelled every booking that was `BOOKED` or `CHECKED_IN`, the remaining bookings are this enrollment's bookings that are either still in `BOOKED` or `CHECKED_IN` or were cancelled by that withdraw cascade, and whose session's `starts_at` is strictly after the current logical clock, sorted by `starts_at` ascending and then the session's `created_at` ascending. If there are no such remaining bookings, the lead time is treated as effectively infinite (which lands in the top tier). Otherwise the lead time in hours is the gap from now to the earliest remaining session's `starts_at`. The refund percentage is one hundred percent when the lead time is at least 48 hours, fifty percent when it is at least 24 hours but under 48, and zero otherwise. The refund is the enrollment's `estimated_price_cents` multiplied by that percentage, rounded half up to whole cents. The boundaries are inclusive: exactly 48 hours of lead time earns the full refund, and exactly 24 hours earns the half refund.

**Required instructors (ratio ceiling).** Whenever a booking is added to or removed from a session, and whenever a session is read, the session's `required_instructors` is recomputed as the `enrolled_count` divided by the level's `max_students_per_instructor`, rounded up to the next whole number (ceiling), with the special case that an `enrolled_count` of 0 yields 0. The boundary lands on exact multiples: when the enrolled count equals the cap exactly, one instructor is required; one student beyond the cap requires two.

**Rental fee (marginal tiered).** When a rental agreement is created, its `rental_fee_cents` is a marginal tiered charge on the rental duration. The duration in hours is the span from `starts_at` to `ends_at` in seconds, divided by 3600 and rounded up to a whole number of hours. The equipment item's `hourly_rate_cents` is the base rate. The first 2 hours are billed at the full rate; the next 6 hours (hours 3 through 8) are billed at half the rate; every hour beyond the eighth is billed at one quarter of the rate. Concretely, the first-tier hours are the lesser of the total hours and 2; the second-tier hours are the total hours beyond the first 2, capped at 6; the third-tier hours are whatever remains beyond 8. The fee is the first-tier hours times the rate, plus the second-tier hours times the rate times one half, plus the third-tier hours times the rate times one quarter, all summed and then rounded half up to whole cents once at the end. These are marginal rates applied tier by tier, not a single average rate, and the 2-hour and 8-hour boundaries are exact crossings. At creation the agreement's `deposit_held_cents` is captured from the equipment item's `deposit_cents`.

### 3.9. Equipment Rentals and Certification Cards

A rental agreement reserves one equipment item for one student over a window. Creating it supplies the `school_id`, the `student_id`, the `equipment_item_id`, the mandatory `expected_equipment_version`, the `starts_at` and `ends_at` window bounds (the end exclusive), and an optional `session_id` linking the gear to a session. The create computes `rental_fee_cents` and `deposit_held_cents` as in §3.8, opens the agreement with `status` `RESERVED`, and increments the equipment item's `version`. Beyond the OCC check, two business rules apply. The window must not collide with any non-terminal agreement on the same item, where each existing agreement reserves a closed interval running from its `starts_at` through its `ends_at` plus a one-hour turnaround buffer; the new window's own endpoints are also treated as closed for this test, so the new request collides whenever its `starts_at` is at or before an existing buffered close and its `ends_at` is at or after that existing agreement's `starts_at` — a collision against that buffered, closed interval is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. And when a `session_id` is supplied, the equipment item's `equipment_type` must equal the linked level's `required_equipment_type`, or the create is rejected with `ERR_EQUIPMENT_TYPE_MISMATCH`.

A rental's `status` runs `RESERVED`, `ACTIVE`, `RETURNED`, or `CANCELLED`, the last two terminal. Checking out a rental, permitted to an administrator or the owning student, moves it from `RESERVED` to `ACTIVE`. It requires the agreement to be `RESERVED`, the equipment item not to be in `MAINTENANCE` — a checkout against a maintenance item is rejected with `ERR_EQUIPMENT_IN_MAINTENANCE` — and the current logical clock to be at or after the agreement's `starts_at`, a clock still before `starts_at` blocking the checkout with `ERR_INVALID_STATE`. On checkout the equipment item moves to `RENTED` and its `version` is incremented. Returning the rental, again by administrator or owning student, moves it from `ACTIVE` to `RETURNED`, moves the equipment item back to `AVAILABLE` (incrementing its `version`), and releases the held deposit back to the student. Cancelling a rental, available while it is `RESERVED` or `ACTIVE`, moves it to `CANCELLED`; if it was `ACTIVE`, the equipment item is returned to `AVAILABLE` with its `version` incremented; in all cases the held deposit is released to the student. Any of these transitions attempted from an ineligible status is rejected with `ERR_INVALID_STATE`.

Certification cards are the system's permanent record of achievement and are never created directly by a client. When an enrollment under a `CERTIFICATION` course completes and no card yet exists for that enrollment, the system issues one card. The card records the `student_id`, the `enrollment_id`, the `course_level_id`, and the `discipline` copied from the course at issuance; it is assigned a `card_number` formatted as `CARD-<n>` where the serial is monotonic within the school; and its `issued_at` is stamped from the logical clock at issuance. As noted in §2.5, a certification card carries only `id` and `created_at` among the common fields. Cards may be listed and fetched but never mutated.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition operations and the administrative toggles — return `200 OK`. The reconstruction of each request body, computed field, and side effect for any endpoint below lives in the §3 narratives; this table fixes only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SchoolAdmin |
| POST | `/schools` | Create a school | SchoolAdmin |
| GET | `/schools` | List schools | SchoolAdmin, Instructor, Student |
| GET | `/schools/{id}` | Get a school | SchoolAdmin, Instructor, Student |
| POST | `/schools/{id}/storm-advisory` | Set or clear a storm advisory | SchoolAdmin |
| POST | `/courses` | Create a course | SchoolAdmin |
| GET | `/courses` | List courses | SchoolAdmin, Instructor, Student |
| GET | `/courses/{id}` | Get a course | SchoolAdmin, Instructor, Student |
| POST | `/levels` | Create a course level | SchoolAdmin |
| GET | `/levels` | List course levels | SchoolAdmin, Instructor, Student |
| GET | `/levels/{id}` | Get a course level | SchoolAdmin, Instructor, Student |
| POST | `/instructors` | Register an instructor | SchoolAdmin |
| GET | `/instructors` | List instructors | SchoolAdmin, Instructor, Student |
| GET | `/instructors/{id}` | Get an instructor | SchoolAdmin, Instructor, Student |
| POST | `/equipment` | Add an equipment item | SchoolAdmin |
| GET | `/equipment` | List equipment | SchoolAdmin, Instructor, Student |
| GET | `/equipment/{id}` | Get an equipment item | SchoolAdmin, Instructor, Student |
| POST | `/equipment/{id}/maintenance` | Toggle equipment maintenance status | SchoolAdmin |
| POST | `/students` | Register a student | SchoolAdmin, Student |
| GET | `/students` | List students | SchoolAdmin, Instructor |
| GET | `/students/{id}` | Get a student | SchoolAdmin, Instructor, Student |
| POST | `/students/{id}/swim-test` | Record a swim test result | SchoolAdmin |
| POST | `/waivers` | Sign a waiver for a student | SchoolAdmin, Student |
| GET | `/waivers` | List waivers | SchoolAdmin, Instructor, Student |
| GET | `/waivers/{id}` | Get a waiver | SchoolAdmin, Instructor, Student |
| POST | `/waivers/{id}/revoke` | Revoke a signed waiver | SchoolAdmin, Student |
| POST | `/memberships` | Create a membership | SchoolAdmin, Student |
| GET | `/memberships` | List memberships | SchoolAdmin, Instructor, Student |
| GET | `/memberships/{id}` | Get a membership | SchoolAdmin, Instructor, Student |
| POST | `/enrollments` | Enroll a student in a course level | SchoolAdmin, Student |
| GET | `/enrollments` | List enrollments | SchoolAdmin, Instructor, Student |
| GET | `/enrollments/{id}` | Get an enrollment | SchoolAdmin, Instructor, Student |
| POST | `/enrollments/{id}/pay` | Mark an enrollment paid | SchoolAdmin, Student |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment | SchoolAdmin, Student |
| POST | `/enrollments/{id}/refund` | Refund a withdrawn, paid enrollment | SchoolAdmin |
| POST | `/enrollments/{id}/complete` | Complete an enrollment | SchoolAdmin |
| POST | `/sessions` | Schedule a session | SchoolAdmin |
| GET | `/sessions` | List sessions | SchoolAdmin, Instructor, Student |
| GET | `/sessions/{id}` | Get a session | SchoolAdmin, Instructor, Student |
| POST | `/sessions/{id}/weather-hold` | Put a session on weather hold | SchoolAdmin |
| POST | `/sessions/{id}/clear-hold` | Clear a weather hold | SchoolAdmin |
| POST | `/sessions/{id}/start` | Start a session | SchoolAdmin, Instructor |
| POST | `/sessions/{id}/complete` | Complete a session | SchoolAdmin, Instructor |
| POST | `/sessions/{id}/cancel` | Cancel a session | SchoolAdmin |
| POST | `/bookings` | Book an enrollment into a session | SchoolAdmin, Student |
| GET | `/bookings` | List bookings | SchoolAdmin, Instructor, Student |
| GET | `/bookings/{id}` | Get a booking | SchoolAdmin, Instructor, Student |
| POST | `/bookings/{id}/check-in` | Check a student in for a session | SchoolAdmin, Instructor |
| POST | `/bookings/{id}/cancel` | Cancel a booking | SchoolAdmin, Student |
| POST | `/rentals` | Create an equipment rental agreement | SchoolAdmin, Student |
| GET | `/rentals` | List rentals | SchoolAdmin, Instructor, Student |
| GET | `/rentals/{id}` | Get a rental agreement | SchoolAdmin, Instructor, Student |
| POST | `/rentals/{id}/checkout` | Check out equipment | SchoolAdmin, Student |
| POST | `/rentals/{id}/return` | Return equipment | SchoolAdmin, Student |
| POST | `/rentals/{id}/cancel` | Cancel a rental | SchoolAdmin, Student |
| GET | `/certification-cards` | List certification cards | SchoolAdmin, Instructor, Student |
| GET | `/certification-cards/{id}` | Get a certification card | SchoolAdmin, Instructor, Student |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SCHOOL_STORM_CLOSED` | 409 Conflict |
| `ERR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AGE_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SWIM_TEST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TIDE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_EQUIPMENT_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_NO_MAKEUP_CREDIT` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_IN_MAINTENANCE` | 409 Conflict |
| `ERR_PAYMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_INCOMPLETE` | 422 Unprocessable Entity |
