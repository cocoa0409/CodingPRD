# Parent-Teacher Conference Scheduling API — Product Requirements Document

## 1. Introduction

Twice a year, the school front office faces the same logistical crunch: hundreds of families need short conferences with teachers, siblings need back-to-back slots so parents are not camping in the hallway, some families need interpreters, and every no-show wastes a seat another family wanted. The Parent-Teacher Conference Scheduling API exists to run that entire season programmatically. An administrator defines a conference window, generates a per-teacher slot grid, opens booking to families, and then shepherds the window through lock, conference day, attendance marking, and archival. Families self-serve their own bookings within guardrails; front office staff retain override powers; teachers manage their own availability; interpreters accept or decline the assignments offered to them.

The API is mounted under `/conf` and is organized into twelve resources: conference windows, teachers, families, students, student-teacher links, time slots, bookings, interpreters, interpreter requests, waitlist entries, attendance records, and outreach tasks. All time-gated behavior — booking open and close instants, cancellation cutoffs, offer expiry, automatic no-show detection — evaluates against a server-held logical clock so that an entire season can be rehearsed deterministically. Capacity quotas, channel constraints, sibling compactness scoring, waitlist prioritization, interpreter fatigue and capacity limits, and strike-based family restriction are enforced by the server rather than by convention.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles: `SchoolAdmin`, `FrontOfficeStaff`, `Teacher`, `FamilyGuardian`, and `Interpreter`. A request whose headers are missing or whose role is not one of these five is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but is not listed among the roles permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the marker identity on an attendance record) but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `FrontOfficeStaff`. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting Teacher; ownership checks on any resource that references a teacher — a slot's `teacher_id`, a booking's `teacher_id` — compare that field to `X-User-ID`. When `X-User-Role` is `FamilyGuardian`, `X-User-ID` is the `id` of the acting Family, and ownership checks compare the resource's `family_id` to `X-User-ID`. When `X-User-Role` is `Interpreter`, `X-User-ID` is the `id` of the acting Interpreter, and ownership checks on an interpreter request compare the request's `interpreter_id` to `X-User-ID`. An entity-backed caller acting on a resource it does not own is rejected with `ERR_FORBIDDEN`, even when the role itself is otherwise permitted on that endpoint.

In terms of capability, a `SchoolAdmin` holds a superset of `FrontOfficeStaff` operations and additionally drives the window lifecycle, teacher and interpreter management, slot generation, ops runs, and the logical clock. A `FrontOfficeStaff` operator registers families and students, manages student-teacher links, books on behalf of families — bypassing the family cancellation cutoff and the family-restriction block that constrain guardians — assigns interpreters, marks attendance, and works the outreach queue. A `Teacher` sees their own schedule, blocks and unblocks their own slots, and marks attendance for their own bookings. A `FamilyGuardian` registers students under their own family, books, cancels, and reschedules their own family's conferences within the cutoff, and joins, claims, declines, and withdraws waitlist entries for their own family. An `Interpreter` views their own assignments and accepts or declines them.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Slot listings — the slots of a window and the slots of a teacher — are the exception: they sort by `start_at` ascending, with ties broken by `created_at` ascending.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-gated rule in this document — booking open and close instants, cancellation cutoffs, offer expiry, automatic no-show detection — evaluates against a server-held logical clock, never against wall-clock time. Before any call that sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `SchoolAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the response reports the new reading as `current_utc`. Once set, the clock holds that reading until it is set again; it never falls back to wall-clock time.

### 2.5. Common Resource Properties

All primary resources — conference windows, teachers, families, students, time slots, bookings, interpreters, interpreter requests, waitlist entries, and outreach tasks — include a standard set of system-managed fields:

- **`id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource. This field backs optimistic concurrency control.

Two resources deviate from this convention. A **StudentTeacherLink** and an **AttendanceRecord** carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Optimistic Concurrency Control

Three write operations require the caller to supply the version of the resource they last observed, and are rejected when that observation is stale:

1. Updating a conference window's configuration requires the request to carry `expected_window_version` equal to the window's current `version`. The window's version advances on every configuration edit, on every slot-generation run, and on every lifecycle transition, so a client that read the window before another writer acted holds a stale number. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. Running slot generation for a window likewise requires `expected_window_version`. Because generation destroys and recreates the slot grid, the caller must have observed the window's current version; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
3. Rescheduling a booking requires `expected_booking_version` equal to the booking's current `version`. A prior reschedule already produces a successor booking and advances the old booking's version, so a client holding an older read is acting on a superseded record; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. Endpoints not named above process mutations without an OCC check.

### 2.7. Validation Order and Nested Resource Resolution

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic:

1. **Authentication first.** Presence of the `X-User-ID` and `X-User-Role` headers and membership of the role in the five declared roles; failures yield `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** Whether the caller's role is listed for the endpoint; failures yield `ERR_FORBIDDEN` (403).
3. **Entity-backed ownership.** A `FamilyGuardian` acts only on their own family, students, bookings, and waitlist entries; a `Teacher` only on their own slots and bookings; an `Interpreter` only on their own requests; failures yield `ERR_FORBIDDEN` (403).
4. **Body well-formedness.** Required fields present, types valid, enum members valid, ranges valid — `grade_level` between 0 and 12 inclusive, positive minute and cap values where required; failures yield `ERR_VALIDATION` (422).
5. **Path resolution.** Path parameters are validated left to right; the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (404) before any later segment is examined.
6. **Optimistic concurrency.** `expected_window_version` or `expected_booking_version` must equal the entity's current `version`; failures yield `ERR_STALE_VERSION` (412).
7. **Window-state gate.** Whether the window's `status` permits the operation at all — booking, cancellation, rescheduling, and waitlist join need `BOOKING_OPEN`; publish needs `DRAFT`; opening booking needs `PUBLISHED`; locking needs `BOOKING_OPEN`; starting needs `LOCKED`; completing needs `IN_PROGRESS`; archiving needs `COMPLETED`; slot generation needs `PUBLISHED`; slot block and unblock need `PUBLISHED` or `BOOKING_OPEN`; attendance marking needs `IN_PROGRESS` or `COMPLETED`; failures yield `ERR_INVALID_WINDOW_STATE` (409).
8. **Entity-state gate.** Whether the target entity's own state permits the transition — a slot must be `OPEN` for booking, `BLOCKED` for unblock, an entry `OFFERED` for claim, a booking `CONFIRMED` (or `NO_SHOW` for staff reschedule), a request `ASSIGNED` for accept or decline; this tier also carries the dedicated state rejections `ERR_FAMILY_RESTRICTED`, `ERR_TEACHER_INACTIVE`, `ERR_SLOT_NOT_AVAILABLE`, `ERR_NO_ACTIVE_OFFER`, `ERR_WINDOW_GRID_LOCKED`, and `ERR_SLOTS_ALREADY_BOOKED` where they apply; otherwise failures yield `ERR_INVALID_STATE` (409).
9. **Interpreter fatigue.** The longest zero-gap run of assignments including the candidate must not exceed the interpreter's `max_consecutive_minutes`; failures yield `ERR_INTERPRETER_FATIGUE` (422).
10. **Temporal gates.** Clock-relative checks: opening booking before `booking_open_at` yields `ERR_BOOKING_WINDOW_NOT_OPEN`; locking before `booking_close_at` yields `ERR_BOOKING_WINDOW_NOT_CLOSED`; a family cancel or reschedule past the cutoff yields `ERR_CANCELLATION_CUTOFF`; a claim after the offer deadline yields `ERR_OFFER_EXPIRED`; a malformed day range yields `ERR_INVALID_DAY_WINDOW`; a family cross-booking gap violation yields `ERR_FAMILY_SCHEDULE_CONFLICT`; an interpreter interval overlap yields `ERR_INTERPRETER_OVERLAP`.
11. **Uniqueness and format rules.** Duplicate bookings (`ERR_DUPLICATE_BOOKING`), duplicate waitlist entries (`ERR_DUPLICATE_WAITLIST_ENTRY`), duplicate student-teacher links (`ERR_DUPLICATE_TEACHER_LINK`), channel incompatibilities (`ERR_CHANNEL_NOT_ALLOWED`), uncovered interpreter languages (`ERR_LANGUAGE_NOT_COVERED`), and a second live interpreter request on one booking (`ERR_ALREADY_HAS_INTERPRETER_REQUEST`).
12. **Referential integrity.** Body-referenced identifiers must exist (`ERR_NOT_FOUND`); the student must be `ENROLLED` (`ERR_STUDENT_NOT_BOOKABLE`); a student-teacher link must exist — and for `ELEMENTARY` windows must be the homeroom link (`ERR_TEACHER_NOT_LINKED`).
13. **Capacity.** Teacher daily caps (`ERR_TEACHER_DAY_FULL`), the family window cap (`ERR_FAMILY_LIMIT_REACHED`), interpreter per-window capacity (`ERR_INTERPRETER_CAPACITY_EXCEEDED`), and the auto-assign empty-pool rejection (`ERR_NO_ELIGIBLE_INTERPRETER`).
14. **Archive guard last.** Archiving is refused while any outreach task of the window is open (`ERR_OPEN_OUTREACH_TASKS`).

The practical consequence of this ordering is that a caller always learns the most fundamental problem first: a missing header masks everything else, a stale version is reported before any state complaint, and capacity rejections surface only after the booking is otherwise valid.

### 2.8. Live Window Counters and Mutation Semantics

A conference window carries a set of computed counters that give an at-a-glance read on inventory and demand. `slots_total_count` is the number of non-`RETIRED` time slots in the window; `slots_open_count`, `slots_held_count`, and `slots_booked_count` count slots in `OPEN`, `HELD`, and `BOOKED` status respectively; `bookings_confirmed_count` counts bookings in `CONFIRMED` status in the window; `waitlist_waiting_count` counts waitlist entries in `WAITING` status in the window. These counters are recomputed by every operation that can change them — slot generation, blocking and unblocking, booking creation, cancellation, rescheduling, waitlist promotion, claims, declines, withdrawals, the window lock, and the deactivation, restriction, and withdrawal cascades — so a read of the window always reflects the current state of its children.

Every mutation of a resource increments that resource's `version` by exactly one and refreshes its `updated_at`. Window lifecycle transitions, configuration edits, slot-generation runs, and ops checkpoints each increment the window's `version`; booking actions increment the booking's `version`; slot block and unblock increment the slot's `version`; and so on for every entity that carries a `version`.

### 2.9. Precision, Rounding, and Units

Percentages and scores reported by this API — utilization percentages, attendance rates, waitlist priority scores, family risk scores, and compactness scores — are numbers rounded half-up to exactly 2 decimal places. Durations and capacities (`slot_length_minutes`, `buffer_minutes`, `travel_minutes`, `assigned_minutes`, `committed_minutes`, and their derived sums) are whole minutes expressed as integers. Slot boundaries and other datetimes are exact to the second. Interpreter pay is computed in integer cents, with rounding applied per assignment before any summation, as detailed in §3.7.

## 3. Business Logic & Workflows

### 3.1. Configuring and Publishing a Conference Window

Everything begins with the **ConferenceWindow**, the seasonal container for all conference activity. A `SchoolAdmin` creates one by supplying a human-readable `name` such as "Fall Conferences", a `term_label` such as "2026-FALL", and a `format` of either `ELEMENTARY` or `SECONDARY` — the format drives the booking rules later, since elementary families book a single homeroom conference while secondary families book per teacher. The geometry of the grid comes from `slot_length_minutes` (the length of each conference, which must be positive), `buffer_minutes` (the gap between consecutive slots for a teacher, which may be zero), and `travel_minutes` (the separation a family needs between two consecutive bookings when switching channel, which may also be zero). The days themselves arrive as `day_windows`, an array of entries each pairing a `date` with `start_at` and `end_at` ISO datetimes. Two instants govern family access: `booking_open_at`, when open-booking becomes allowed, and `booking_close_at`, when locking becomes allowed. Finally, the administrator sets quotas and policy knobs: `teacher_daily_conf_cap` (the maximum number of `CONFIRMED` bookings a teacher may hold on one day, which must be positive), and the optional `family_conf_cap` (default 8), `cancel_cutoff_hours` (default 24), `waitlist_offer_ttl_hours` (default 24), `no_show_strike_threshold` (default 3), and `auto_no_show_grace_hours` (default 24). A new window is born in `DRAFT` status with `ops_run_index` at 0, every counter at 0, and `version` at 1.

Publication moves the window from `DRAFT` to `PUBLISHED`. The administrator may publish only when `day_windows` is non-empty and every entry ends strictly after it starts — a day range whose `end_at` does not fall after its `start_at` is rejected with `ERR_INVALID_DAY_WINDOW` — and when the slot length is positive and the buffer and travel values are non-negative. Publication increments the window's `version`.

Configuration edits after creation are allowed but increasingly constrained. While the window is in `DRAFT`, every field may be edited. Once slots exist, the grid fields — `slot_length_minutes`, `buffer_minutes`, and `day_windows` — are frozen, and any attempt to change them is rejected with `ERR_WINDOW_GRID_LOCKED`; the remaining fields, including `name`, `booking_open_at`, `booking_close_at`, `teacher_daily_conf_cap`, `family_conf_cap`, `cancel_cutoff_hours`, `waitlist_offer_ttl_hours`, `no_show_strike_threshold`, `auto_no_show_grace_hours`, and `travel_minutes`, stay editable. The `term_label` and `format` are fixed at creation and can never be edited. Every edit requires `expected_window_version` per §2.6 and increments the window's `version`.

### 3.2. Generating the Slot Grid and Managing Inventory

Once a window is `PUBLISHED`, a `SchoolAdmin` generates its slot inventory. Generation slices each entry of `day_windows` into per-teacher **TimeSlot** rows. Eligible teachers are those in `ACTIVE` status whose `grade_band` matches the window's `format`, plus teachers whose `grade_band` is `BOTH`, which matches either format. For each day window and each eligible teacher, a cursor starts at the day's `start_at`; while the cursor plus `slot_length_minutes` falls on or before the day's `end_at`, a slot is emitted spanning from the cursor to the cursor plus the slot length — a slot may end exactly at the day window's end. The cursor then advances by the slot length plus `buffer_minutes`, and after every fourth slot placed for that teacher on that day, the cursor advances an additional fifteen minutes of break before the next slot is considered. Each emitted slot records the window as its `window_id`, the teacher as its `teacher_id`, the day window's date in `YYYY-MM-DD` form as its `day_label`, and a `start_at` and `end_at` that delimit a half-open interval — the start instant belongs to the slot, the end instant does not. The slot's `channel_allowed` is derived from the teacher's channel flags: `EITHER` when the teacher supports both channels, `IN_PERSON` when only in-person is supported, and `VIRTUAL` when only virtual is supported; a teacher who supports neither channel is skipped entirely and produces no inventory. Every generated slot is born `OPEN`. Generation requires `expected_window_version` per §2.6, requires the window to be `PUBLISHED` (otherwise `ERR_INVALID_WINDOW_STATE`), recomputes the window's slot counters, and increments the window's `version`.

Regeneration is possible but guarded. When slots already exist, a fresh generation run is allowed only while no booking references any slot of the window; the moment any booking exists, regeneration is refused with `ERR_SLOTS_ALREADY_BOOKED`. A permitted regeneration retires the entire existing grid — every slot moves to `RETIRED`, and `RETIRED` slots never reopen — and then builds a fresh grid from the current configuration.

Day to day, individual slots can be held back from families. Blocking a slot moves it from `OPEN` to `BLOCKED`; the slot must currently be `OPEN` (otherwise `ERR_SLOT_NOT_AVAILABLE`), the window must be `PUBLISHED` or `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`), and a `Teacher` caller may block only their own slots (otherwise `ERR_FORBIDDEN`), while staff may block any slot. The caller may attach an optional free-text `reason`. Unblocking reverses the move from `BLOCKED` back to `OPEN` under the same window-state gate, with a slot that is not currently `BLOCKED` rejected with `ERR_INVALID_STATE`. When an unblock lands while the window is `BOOKING_OPEN`, the waitlist promotion selector runs immediately on the freed slot, so it may move straight from `BLOCKED` through `OPEN` to `HELD` without ever being visible as bookable. Both actions recompute the window's `slots_open_count` (and `slots_held_count` when a promotion fires) and increment the slot's `version`.

### 3.3. Roster Management: Teachers, Families, Students, and Links

A **Teacher** record carries a `full_name`, a contact `email`, a `grade_band` of `ELEMENTARY`, `SECONDARY`, or `BOTH`, and a `subjects` array used for secondary staffing. Scheduling-relevant defaults matter: `room_location` defaults to null, `supports_in_person` defaults to true, `supports_virtual` defaults to false, and `daily_conf_cap_override` defaults to null — when set, the override replaces the window's `teacher_daily_conf_cap` for that teacher alone. A teacher is born `ACTIVE` with `version` 1. Staff may later update `full_name`, `room_location`, `supports_in_person`, `supports_virtual`, and `daily_conf_cap_override`; the teacher list may be filtered by `status` and `grade_band`, and a teacher's slots may be listed with optional `window_id` and `status` filters.

Deactivating a teacher — moving them from `ACTIVE` to `INACTIVE` — is a heavy cascade. Every slot of that teacher in a window still in `PUBLISHED` or `BOOKING_OPEN` whose status is `OPEN` or `BLOCKED` moves to `RETIRED`. Every `CONFIRMED` booking on that teacher's slots in those windows is cancelled with `cancel_reason` set to `TEACHER_INACTIVE`, and the freed slots move to `RETIRED` rather than reopening — those seats are gone for good. Interpreter requests in `REQUESTED` or `ASSIGNED` status on the cancelled bookings move to `CANCELLED`, and each cancellation of an `ASSIGNED` request subtracts its `assigned_minutes` from the interpreter's `committed_minutes`. Waitlist entries in `WAITING` or `OFFERED` status for that teacher move to `WITHDRAWN`, and an entry that was holding a slot releases it — the `HELD` slot moves to `RETIRED`, not back to `OPEN`. Every affected window's counters are recomputed. Reactivation from `INACTIVE` back to `ACTIVE` performs no restoration: retired slots stay retired, and the slot grid must be regenerated to recreate inventory.

A **Family** is registered by staff with a `primary_guardian_name`, an `email`, an optional `phone` (default null), and a `preferred_language` ISO code that defaults to "en". A family is born `ACTIVE` with both strike fields at 0 and `version` 1. Contact fields — `primary_guardian_name`, `email`, `phone`, `preferred_language` — may be updated later; a `FamilyGuardian` caller may read and update only their own family record.

Students are registered under a family by staff or by the family's own guardian, supplying a `full_name` and a `grade_level` between 0 and 12 inclusive, where 0 denotes kindergarten. A new student's `enrollment_status` is `ENROLLED`, and the student's `family_id` ties the record to its owning family. Withdrawing a student moves them from `ENROLLED` to `WITHDRAWN` — a terminal state — and cascades: every `CONFIRMED` booking of the student whose slot starts after the logical clock is cancelled with `cancel_reason` set to `STUDENT_WITHDRAWN`, each freed slot moves from `BOOKED` to `OPEN`, running the waitlist promotion sweep when the window is `BOOKING_OPEN` and simply opening otherwise; interpreter requests in `REQUESTED` or `ASSIGNED` status on those bookings move to `CANCELLED` with the usual committed-minutes decrement for `ASSIGNED` ones; and the student's waitlist entries in `WAITING` or `OFFERED` status move to `WITHDRAWN`, with an offered entry releasing its `HELD` slot back to `OPEN` and re-running promotion.

The **StudentTeacherLink** records that a student is taught by a teacher, created by staff with a `teacher_id` on a student identified in the path; the link's `student_id` is taken from that path. A link may be flagged `is_homeroom` (default false) — the flag that matters for elementary booking — and `required_conference` (default false), which marks a counselor-mandated conference and feeds waitlist priority. Only one link may exist per student-teacher pair; a second attempt is rejected with `ERR_DUPLICATE_TEACHER_LINK`. Links may be removed, a deletion that returns no content. Links carry no `updated_at` or `version`, per §2.5. A student's links and a teacher's links are each listable in their own right.

### 3.4. Opening Booking and Taking a Slot

With a grid in place, opening booking moves the window from `PUBLISHED` to `BOOKING_OPEN`. Two gates guard the transition, evaluated under the ordering of §2.7: the window must actually have inventory — `slots_total_count` greater than zero, meaning generation has run, otherwise `ERR_INVALID_WINDOW_STATE` — and the logical clock must have reached `booking_open_at`, otherwise `ERR_BOOKING_WINDOW_NOT_OPEN`. Opening increments the window's `version`.

From that moment, a **Booking** can be created against any `OPEN` slot. A `FamilyGuardian` books self-service; `FrontOfficeStaff` or `SchoolAdmin` may book on a family's behalf. The request names the `slot_id` and `student_id`, picks a `channel` of `IN_PERSON` or `VIRTUAL`, and may optionally carry an `interpreter_language`. The booking's `window_id` and `teacher_id` are derived from the slot, and its `family_id` is derived from the student's owning family — a guardian may only book for a student of their own family, otherwise `ERR_FORBIDDEN`. The recorded `booked_by_role` is `FAMILY_SELF` for a guardian booking and `FRONT_OFFICE` when staff book on behalf.

Creation is gated by a battery of checks, surfaced in the order of §2.7. The window must be `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`). The slot must be `OPEN` (otherwise `ERR_SLOT_NOT_AVAILABLE`), the teacher `ACTIVE` (otherwise `ERR_TEACHER_INACTIVE`), and the student `ENROLLED` (otherwise `ERR_STUDENT_NOT_BOOKABLE`). A guardian caller's family must be `ACTIVE` — a `RESTRICTED` family loses self-service booking and waitlist join, and the attempt is rejected with `ERR_FAMILY_RESTRICTED`; staff booking on behalf bypass this restriction. A student-teacher link must exist between the student and the slot's teacher, and for an `ELEMENTARY` window that link must be the homeroom link — `is_homeroom` set — otherwise `ERR_TEACHER_NOT_LINKED`. Duplicates are refused with `ERR_DUPLICATE_BOOKING`: a student may hold at most one `CONFIRMED` booking with a given teacher per window, and in an `ELEMENTARY` window at most one `CONFIRMED` booking in the window altogether. The requested `channel` must be compatible with the slot's `channel_allowed` and the teacher's channel support flags, otherwise `ERR_CHANNEL_NOT_ALLOWED`. Two caps apply: the teacher's `CONFIRMED` bookings on the slot's `day_label` must still be below the effective daily cap — the smaller of the window's `teacher_daily_conf_cap` and the teacher's `daily_conf_cap_override` when the override is set — otherwise `ERR_TEACHER_DAY_FULL`; and the family's `CONFIRMED` bookings in the window must be below `family_conf_cap`, otherwise `ERR_FAMILY_LIMIT_REACHED`.

The final guard is the family gap rule, which keeps a family's schedule physically attendable. The candidate booking is checked against every other booking of the same family in the same window whose status is `CONFIRMED`, `COMPLETED`, or `NO_SHOW`. The separation required between two bookings depends on their channels: zero minutes when both are `VIRTUAL`; the window's `buffer_minutes` when both are `IN_PERSON`; and the window's `travel_minutes` when the two channels differ. The pair conflicts unless the candidate starts at or after the existing booking's slot end plus the required separation, or the existing booking starts at or after the candidate's slot end plus the required separation — a separation exactly equal to the requirement is allowed. A violation is rejected with `ERR_FAMILY_SCHEDULE_CONFLICT`. Because equal or overlapping starts always conflict, two bookings of one family can never share a start time.

A successful create moves the slot from `OPEN` to `BOOKED`, stores the booking in `CONFIRMED` status with `version` 1, and — when `interpreter_language` was supplied — automatically creates an interpreter request in `REQUESTED` status for the booking. The family's compactness score and the window's counters are recomputed. The booking list may be filtered by `window_id`, `family_id`, `student_id`, `teacher_id`, `slot_id`, `rescheduled_from_booking_id`, and `status`.

Sibling logistics are quantified by `family_compactness_score`, a value stored on every booking of a family in a window and recomputed after every booking mutation — creation, cancellation, rescheduling, or waitlist claim — for that family-window pair. To compute it, take the family's bookings in the window with status `CONFIRMED`, `COMPLETED`, or `NO_SHOW`, sorted by slot start ascending; ties cannot occur because the gap rule forbids equal starts. Each adjacent pair contributes points based on the gap in minutes between the earlier slot's end and the later slot's start: a gap of at most fifteen minutes contributes 1 point; a gap longer than fifteen but at most forty-five minutes contributes 3 points; any longer gap contributes 8 points. The contribution doubles when the two bookings use different channels. The score is the sum over all adjacent pairs, rounded half-up to two decimal places, and a family with a single qualifying booking scores 0.00. Lower scores indicate tighter, more convenient family schedules.

### 3.5. Cancellations and Rescheduling

Cancellation moves a booking from `CONFIRMED` to `CANCELLED`. The window must be `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`). A `FamilyGuardian` caller must own the booking's family (otherwise `ERR_FORBIDDEN`) and may cancel only while the logical clock is no later than `cancel_cutoff_hours` hours before the slot's `start_at` — once that cutoff instant has passed, the family attempt is rejected with `ERR_CANCELLATION_CUTOFF`. Staff callers bypass the cutoff entirely. The caller may attach an optional free-text `reason`; the system records the coded `cancel_reason` as `FAMILY_REQUEST` for a guardian cancellation and `STAFF_REQUEST` for a staff cancellation. Cancellation frees the slot from `BOOKED` back to `OPEN`, and since the window is `BOOKING_OPEN` the promotion selector runs on it immediately. Any open interpreter request on the booking — `REQUESTED`, `ASSIGNED`, or `CONFIRMED` — moves to `CANCELLED`, and one that was `ASSIGNED` subtracts its `assigned_minutes` from the interpreter's `committed_minutes`. The family's compactness score and the window's counters are recomputed, and the booking's `version` increments.

Rescheduling is a create-with-supersede operation. For a `CONFIRMED` booking, the request must carry `expected_booking_version` matching the booking's current `version` per §2.6 — a mismatch is rejected with `ERR_STALE_VERSION`. A `FamilyGuardian` reschedules only while the window is `BOOKING_OPEN` and only while the logical clock is no later than `cancel_cutoff_hours` hours before the old slot's start (otherwise `ERR_CANCELLATION_CUTOFF`); staff may reschedule while the window is `BOOKING_OPEN` and may also reschedule while it is `IN_PROGRESS`. The request names a `new_slot_id` and may optionally carry a new `channel`. The new slot must be `OPEN`, must belong to the same window, and must pass the full booking validation battery from §3.4 — link, duplicate, caps, family gap, and channel rules all re-run against the new slot.

A successful reschedule writes the old booking to `RESCHEDULED` with `cancel_reason` set to `RESCHEDULED` and increments the old booking's `version`; the old slot moves from `BOOKED` to `OPEN` and runs the promotion sweep. In the same operation a successor booking is created in `CONFIRMED` status with `version` 1 and its `rescheduled_from_booking_id` pointing at the old booking, while the new slot moves from `OPEN` to `BOOKED`. Any open interpreter request on the old booking moves to `CANCELLED`, and when the old booking carried a non-null `interpreter_language`, a fresh interpreter request in `REQUESTED` status is auto-created for the successor. Compactness and window counters are recomputed.

Staff can also recover a no-show: a booking in `NO_SHOW` status may be rescheduled by `FrontOfficeStaff` or `SchoolAdmin` while the window is `IN_PROGRESS` or `COMPLETED`. The same `expected_booking_version` check applies, the new slot must be `OPEN`, in the same window, and starting after the logical clock, and the booking validations re-run. The successor-creation side effects mirror the `CONFIRMED` reschedule exactly, with one deliberate asymmetry: the existing `NO_SHOW` attendance record and the strike it caused are not removed — the family keeps the mark on its record even though it gets a second seat.

### 3.6. The Waitlist: Joining, Promotion, Offers, and Claims

When the right slot is gone, a family joins the waitlist. Creating a **WaitlistEntry** takes a `window_id`, a `student_id`, a `teacher_id`, and a `channel_pref` of `IN_PERSON`, `VIRTUAL`, or `EITHER`. The window must be `BOOKING_OPEN`; a guardian caller joins only for their own family and only while that family is `ACTIVE` (otherwise `ERR_FAMILY_RESTRICTED`, which staff callers bypass); the student must be `ENROLLED` and linked to the teacher per the same rules as booking. At most one entry in `WAITING` or `OFFERED` status may exist per student-teacher-window combination, and no entry may be created at all when a `CONFIRMED` booking already exists for that student-teacher pair in that window — either situation is rejected with `ERR_DUPLICATE_WAITLIST_ENTRY`. The entry's `family_id` is derived from the student's family. A new entry is born `WAITING` with `offers_made_count` at 0 and its `priority_score` computed at creation; the window's `waitlist_waiting_count` is recomputed.

The `priority_score` decides who gets offered a freed seat first. It starts from a base of 100 points. A link flagged `required_conference` adds 50 points. Sibling presence adds 15 points per sibling of the student — another student with the same `family_id` — who holds a `CONFIRMED` booking in the same window, counting at most two siblings for a maximum of 30 points. Attendance risk subtracts 10 points per whole point of the family's `attendance_risk_strict`, with the strict score rounded down to a whole number and capped at five points, a maximum penalty of 50. Patience adds 5 points per full 24-hour period elapsed between the entry's `created_at` and the logical clock, capped at four periods for a maximum of 20 points. If the total would be negative it is floored at zero, and the result is rounded half-up to two decimal places. The score is recomputed at entry creation, at every ops checkpoint, when a sibling booking is confirmed, and when the family's risk changes.

The promotion selector runs whenever a slot transitions into `OPEN` while the window is `BOOKING_OPEN` — an unblock, a cancellation, a reschedule-away, a cascade release — and also as part of the ops checkpoint sweep. Its candidate pool is the `WAITING` entries whose `teacher_id` and `window_id` match the slot, excluding any entry whose `declined_slot_ids` already contains this slot, and requiring channel compatibility: an `EITHER` preference is compatible with any slot, an `IN_PERSON` preference requires the slot's `channel_allowed` to be `IN_PERSON` or `EITHER`, and a `VIRTUAL` preference likewise requires `VIRTUAL` or `EITHER`. Candidates are ranked by `priority_score` descending, ties broken by `created_at` ascending, and final ties by the entry's `created_seq` — a server-assigned, strictly increasing global creation sequence. The selector walks the ranking top-down, skips any candidate whose booking preconditions would fail on this slot (link, duplicate, caps, and the family gap rule), and offers the slot to the first candidate that passes every check; when the pool is empty or every candidate fails, the slot simply stays `OPEN`.

An offer moves the entry from `WAITING` to `OFFERED` and the slot from `OPEN` to `HELD` in the same sweep. The entry records the slot as its `offered_slot_id`, sets `offer_expires_at` to the logical clock plus the window's `waitlist_offer_ttl_hours`, and increments `offers_made_count` by one.

Claiming converts the offer into a real booking. The entry must be `OFFERED` (otherwise `ERR_NO_ACTIVE_OFFER`), the logical clock must be on or before `offer_expires_at` — the deadline is inclusive, so a claim at exactly the expiry instant succeeds and a strictly later one is rejected with `ERR_OFFER_EXPIRED` — and a guardian caller must own the entry's family. The booking validations from §3.4 re-run against the offered slot, including the channel rule for the optional `channel` input; an optional `interpreter_language` auto-creates an interpreter request just as in direct booking. A successful claim creates the booking in `CONFIRMED` status, moves the slot from `HELD` to `BOOKED`, moves the entry from `OFFERED` to `CLAIMED` — a terminal state — and recomputes compactness and window counters. Because claim creates a new booking resource, it answers with the creation status code.

Declining releases the offer. When an `OFFERED` entry is declined by the family or by staff — or when the ops checkpoint finds `offer_expires_at` strictly before the logical clock — the entry's fate depends on how many offers it has already consumed: while `offers_made_count` is below 2 the entry returns to `WAITING`, but at exactly 2 offers the entry moves to `EXHAUSTED` instead. Either way, the declined slot is appended to `declined_slot_ids`, `offered_slot_id` and `offer_expires_at` are cleared, and the slot moves from `HELD` back to `OPEN` with the promotion sweep re-run — the declining entry is ineligible for that same slot ever again, so the sweep necessarily considers other candidates. Withdrawal is the family's or staff's explicit exit: an entry in `WAITING` or `OFFERED` moves to `WITHDRAWN` (an offered withdrawal releases its `HELD` slot to `OPEN` and re-runs promotion), optionally carrying a free-text `reason`, and the window's `waitlist_waiting_count` is recomputed. The waitlist may be browsed with filters on `window_id`, `family_id`, `student_id`, `teacher_id`, `offered_slot_id`, and `status`.

One more mass transition arrives at window lock: every entry still `WAITING` or `OFFERED` moves to `EXPIRED`, and an offered entry's `HELD` slot returns to `OPEN` without any promotion — the window is locking, so no new offers are made.

### 3.7. Interpreter Coverage: Requests, Assignment, Fatigue, and Pay

An **Interpreter** profile holds a `full_name`, a non-empty `languages` array of ISO codes, channel flags `supports_in_person` and `supports_virtual` (both default true), a fatigue cap `max_consecutive_minutes` (the longest allowed run of back-to-back assigned minutes, which must be positive), a `base_minutes_per_window` capacity base (positive), and an `hourly_rate_cents` pay rate that may be zero for volunteers. An interpreter is born `ACTIVE` with `committed_minutes` at 0. The `committed_minutes` figure is computed as the sum of `assigned_minutes` over the interpreter's requests in `ASSIGNED` or `CONFIRMED` status whose window is neither `COMPLETED` nor `ARCHIVED`. Staff may later update any of `full_name`, `languages`, `max_consecutive_minutes`, `base_minutes_per_window`, `hourly_rate_cents`, `supports_in_person`, `supports_virtual`, and `status`; the interpreter list may be filtered by `status` and by `language`.

An **InterpreterRequest** attaches language coverage to one booking. Most are created automatically: any booking created or claimed with a non-null `interpreter_language` spawns a request in `REQUESTED` status. Staff may also create one manually by naming a `booking_id` and a `language`; the booking must be `CONFIRMED`, and at most one non-terminal request may exist per booking — a second live request is rejected with `ERR_ALREADY_HAS_INTERPRETER_REQUEST`. At creation the request copies `channel_required` from the booking's `channel`, denormalizes the booking's `window_id`, sets `assigned_minutes` to the underlying slot's length, leaves `interpreter_id` null, and starts with an empty `declined_interpreter_ids` list.

Assignment moves a request from `REQUESTED` to `ASSIGNED` and is performed by staff. The checks run under the §2.7 ordering: the request must be `REQUESTED` and its booking still `CONFIRMED` (both otherwise `ERR_INVALID_STATE`); the chosen interpreter must be `ACTIVE` (otherwise `ERR_INVALID_STATE`). The interpreter's `languages` must contain the request's `language` (otherwise `ERR_LANGUAGE_NOT_COVERED`), and the interpreter must support the required channel — `supports_in_person` for an `IN_PERSON` request, `supports_virtual` for a `VIRTUAL` one (otherwise `ERR_CHANNEL_NOT_ALLOWED`). The candidate must not collide with the interpreter's other work: its half-open interval — start instant included, end instant excluded — must not intersect the interval of any other `ASSIGNED` or `CONFIRMED` assignment of that interpreter, with back-to-back assignments where one starts exactly when the other ends explicitly allowed; a collision is rejected with `ERR_INTERPRETER_OVERLAP`. Fatigue is also enforced: take every `ASSIGNED` or `CONFIRMED` assignment of the interpreter across all windows that are not `ARCHIVED`, add the candidate, sort the intervals by start ascending with ties broken by `created_at` ascending, and merge them into runs wherever the next interval begins exactly when the previous one ends — zero gap. The length of a run is the sum of its minutes, and the assignment is allowed only when the longest resulting run does not exceed `max_consecutive_minutes`; otherwise the rejection is `ERR_INTERPRETER_FATIGUE`. Finally comes per-window capacity, evaluated in a pinned order: first the interpreter's committed minutes in this window — the sum of `assigned_minutes` over their `ASSIGNED` and `CONFIRMED` requests here; then a break allowance of ten minutes for each full block of forty-five committed minutes, ignoring any remainder; then the capacity itself, `base_minutes_per_window` minus the allowance, floored at zero; then headroom, the capacity minus the committed minutes. The assignment is allowed only when the committed minutes plus the new `assigned_minutes` do not exceed the capacity, otherwise `ERR_INTERPRETER_CAPACITY_EXCEEDED`. Because the allowance depends on the committed minutes, this evaluation order must not be reversed.

The assignment call may name an explicit `interpreter_id`, or omit it to invoke the auto-selector. The auto-selector's candidate pool is every `ACTIVE` interpreter who covers the language, supports the required channel, and does not appear in the request's `declined_interpreter_ids`. Candidates are ranked by `committed_minutes` ascending, then `created_at` ascending, then the interpreter's `created_seq` — the server-assigned, strictly increasing global creation sequence — ascending. The selector walks that ranking and offers the assignment to the first candidate who passes the overlap, fatigue, and capacity checks; when no candidate passes, the request is rejected with `ERR_NO_ELIGIBLE_INTERPRETER`. A successful assignment sets `interpreter_id` and adds `assigned_minutes` to the interpreter's `committed_minutes`.

The assigned interpreter then answers for themselves. Accepting — `ASSIGNED` to `CONFIRMED` — is permitted only to the interpreter whose `id` matches the request's `interpreter_id` (otherwise `ERR_FORBIDDEN`) and only from `ASSIGNED` status (otherwise `ERR_INVALID_STATE`). Declining moves the request from `ASSIGNED` back to `REQUESTED` under the same ownership rule, optionally carrying a free-text `reason`: the interpreter's `id` is appended to `declined_interpreter_ids` — which excludes them from future auto-assignment for this request — `interpreter_id` is cleared back to null, and the interpreter's `committed_minutes` lose the request's `assigned_minutes`.

Cancellation of a request by staff — or by the system cascades described elsewhere in this section — moves it from `REQUESTED`, `ASSIGNED`, or `CONFIRMED` to `CANCELLED`, optionally with a free-text `reason`. When the cancelled request was `ASSIGNED`, the interpreter's `committed_minutes` are decremented by `assigned_minutes`. A `CONFIRMED` request that is cancelled retains its committed minutes for pay purposes: those minutes stay committed until the window reaches `COMPLETED` or `ARCHIVED`, matching the computed definition of `committed_minutes`.

Deactivating an interpreter — `ACTIVE` to `INACTIVE` — bounces every `ASSIGNED` request of that interpreter back to `REQUESTED`, clearing `interpreter_id` and decrementing `committed_minutes` accordingly; `CONFIRMED` requests are honored and left unchanged. Reactivation from `INACTIVE` to `ACTIVE` has no side effects.

Interpreter pay is estimated per window. For each of the interpreter's `CONFIRMED` requests in the window, the billable units are the request's `assigned_minutes` divided by fifteen and rounded up to a whole number of units; the pay for that assignment is the units times fifteen minutes times the interpreter's `hourly_rate_cents` divided by sixty, rounded half-up to a whole number of cents. The estimate `pay_estimate_cents` is the integer sum of those per-assignment amounts. The rounding order is pinned — round each assignment first, then sum; totalling minutes first and rounding once would yield a different total and is not used.

If the window locks while a request is still `REQUESTED`, the request moves to `UNFILLED`, and the system opens an outreach task of kind `LANGUAGE_ACCESS` for the family so the front office can follow up.

### 3.8. Conference Day: Lock, Attendance, Strikes, and Restriction

Locking moves the window from `BOOKING_OPEN` to `LOCKED` and is allowed once the logical clock has reached `booking_close_at` — an earlier attempt is rejected with `ERR_BOOKING_WINDOW_NOT_CLOSED`. The lock is a housekeeping sweep: interpreter requests still `REQUESTED` move to `UNFILLED` with the language-access outreach described in §3.7; waitlist entries still `WAITING` or `OFFERED` move to `EXPIRED`, with offered entries releasing their `HELD` slots back to `OPEN` and no further promotion after lock; the window's counters are recomputed; and the window's `version` increments. Starting conferences moves the window from `LOCKED` to `IN_PROGRESS`, and when the day is done, completion moves it from `IN_PROGRESS` to `COMPLETED`; each transition increments the window's `version`.

Attendance is recorded per booking while the window is `IN_PROGRESS` or `COMPLETED` (otherwise `ERR_INVALID_WINDOW_STATE`), and never before the slot has started — the logical clock must have reached the slot's `start_at`, otherwise the mark is rejected with `ERR_INVALID_STATE`. A `Teacher` marks only their own bookings (the booking's `teacher_id` must match the caller), while `FrontOfficeStaff` and `SchoolAdmin` mark any booking. The mark supplies an `outcome` and an optional `note`, and produces an **AttendanceRecord** holding the `booking_id`, the `outcome`, the `marked_by_role`, and the `marked_by_user_id` — the caller's `X-User-ID`, or the literal string "system" when the ops checkpoint marks automatically. Attendance records carry no `updated_at` or `version`, per §2.5, and the record list may be filtered by `booking_id` and `outcome`.

The four outcomes drive three different booking transitions. `ATTENDED` and `LATE` both move the booking from `CONFIRMED` to `COMPLETED` and recompute the family's risk scores. `EXCUSED` moves the booking from `CONFIRMED` to `EXCUSED` and recomputes the weighted risk score — an excused absence weighs 0.25 — but records no strike. `NO_SHOW` moves the booking from `CONFIRMED` to `NO_SHOW` and fires the full strike cascade below.

Three numbers track a family's attendance reliability, all recomputed after every attendance record created for a booking of that family and reported rounded half-up to two decimal places. The strict variant, stored as `attendance_risk_strict`, is simply the lifetime count of the family's `NO_SHOW` records across every booking in every window, weighted at 1.0 each — it ignores strike clears entirely. The weighted variant, stored as `attendance_risk_score`, counts each `NO_SHOW` at 1.0, each `LATE` at 0.5, and each `EXCUSED` at 0.25 over the same lifetime record set; a family with one no-show, one late arrival, and one excused absence therefore reads 1.00 on the strict scale and 1.75 on the weighted scale. The third number, `no_show_strike_count`, is the lifetime `NO_SHOW` count minus the family's `strikes_cleared_total`, floored at zero.

Strikes carry teeth. After each `NO_SHOW` record — manual or automatic — the strike count is recomputed, and when the family is `ACTIVE` and the recomputed count has reached the `no_show_strike_threshold` of the window whose booking was marked, the family moves from `ACTIVE` to `RESTRICTED`. The boundary is exact: a count equal to the threshold restricts, while one short of it does not. Restriction cascades immediately. Every `CONFIRMED` booking of the family in any window whose slot starts after the logical clock is cancelled with `cancel_reason` set to `FAMILY_RESTRICTED`, and each freed slot moves from `BOOKED` to `OPEN`, with the promotion sweep run per slot when the window is `BOOKING_OPEN` and the slot simply opening otherwise. Interpreter requests in `REQUESTED` or `ASSIGNED` status on those bookings move to `CANCELLED`, with `ASSIGNED` ones returning their `assigned_minutes` to the interpreter's `committed_minutes`. The family's waitlist entries in `WAITING` or `OFFERED` status move to `WITHDRAWN`, an offered entry releasing its `HELD` slot to `OPEN` and re-running promotion. While `RESTRICTED`, the family's self-service booking and waitlist join are blocked with `ERR_FAMILY_RESTRICTED`; staff may still act on the family's behalf.

The way back is the clear-strikes action, available to `FrontOfficeStaff` and `SchoolAdmin`. It moves the family from `RESTRICTED` to `ACTIVE`, adds the current `no_show_strike_count` into `strikes_cleared_total` — so the strike count recomputes to zero — and increments the family's `version`. The two risk scores are deliberately untouched by the clear: they ignore clears and keep their historical memory.

The ops checkpoint is the administrator's batched housekeeping run over a window. It increments the window's `ops_run_index` by one and performs three sweeps. First, offer expiry: every `OFFERED` waitlist entry whose `offer_expires_at` is strictly before the logical clock follows the decline path of §3.6 — back to `WAITING` while `offers_made_count` is below 2, to `EXHAUSTED` at 2 — with the released slot returned to `OPEN` and the promotion sweep re-run. Second, automatic no-show: while the window is `IN_PROGRESS` or `COMPLETED`, every `CONFIRMED` booking whose slot end plus the window's `auto_no_show_grace_hours` lies at or before the logical clock is marked `NO_SHOW` exactly as if marked by hand, with the attendance record's `marked_by_role` and `marked_by_user_id` recorded as "system", and the full strike cascade — risk recomputation, the `NO_SHOW_FOLLOW_UP` outreach task, and possible family restriction — fires for each. Third, every `WAITING` entry's `priority_score` is refreshed. The checkpoint increments the window's `version`.

### 3.9. Follow-Up Outreach, Reporting, and Utilization Summaries

An **OutreachTask** is the front office's unit of follow-up work. Two kinds are created by the system — a `NO_SHOW_FOLLOW_UP` task whenever a booking is marked `NO_SHOW`, and a `LANGUAGE_ACCESS` task whenever an interpreter request goes `UNFILLED` at lock — and staff may also create tasks manually by naming a `family_id`, a `kind` of `NO_SHOW_FOLLOW_UP`, `RESCHEDULE_ASSIST`, or `LANGUAGE_ACCESS`, and optionally a `booking_id`, a `window_id`, and a free-text `note`. For a manual task, the supplied `window_id` is copied onto the task for archive-guard scoping; when neither a booking nor a window context is supplied, the task's `window_id` stays null. A task is born `OPEN` with `attempts_count` at 0.

Working a task is deliberately simple. Recording a contact attempt moves an `OPEN` task to `CONTACTED` — a task not in `OPEN` or `CONTACTED` is rejected with `ERR_INVALID_STATE` — and each attempt, whether from `OPEN` or from `CONTACTED` itself, increments `attempts_count` by one; an optional `note` may accompany the attempt. Resolving moves a task from `OPEN` or `CONTACTED` to `RESOLVED` with an optional `note`; dismissing moves it to `DISMISSED` with an optional free-text `reason`. Both `RESOLVED` and `DISMISSED` are terminal. The task list may be filtered by `family_id`, `window_id`, `booking_id`, `status`, and `kind`.

Tasks gate the final window transition. Archiving moves the window from `COMPLETED` to `ARCHIVED`, and it is refused while any outreach task of that window is still `OPEN` or `CONTACTED` — the attempt is rejected with `ERR_OPEN_OUTREACH_TASKS` until the queue is worked down. Archival increments the window's `version` and ends the lifecycle: `ARCHIVED` is terminal.

The window's attendance report aggregates the season's outcomes. It echoes the `window_id` and reports per-status booking counts — `bookings_confirmed`, `bookings_completed`, `bookings_no_show`, `bookings_excused`, `bookings_cancelled`, and `bookings_rescheduled` — together with two rates: `attendance_rate_pct` is one hundred times the number of `COMPLETED` bookings divided by the sum of `COMPLETED` and `NO_SHOW` bookings, rounded half-up to two decimal places, and `no_show_rate_pct` substitutes the `NO_SHOW` count in the numerator under the same denominator and rounding; when no booking has reached `COMPLETED` or `NO_SHOW`, both rates report 0.00. The report closes with `open_outreach_tasks`, the count of the window's tasks still in `OPEN` or `CONTACTED` status.

A teacher's utilization summary answers how full one teacher's grid is in a given window — the `window_id` query parameter is required. It counts the teacher's slots in that window with status `OPEN`, `BLOCKED`, `HELD`, or `BOOKED` as `bookable_slots` — `RETIRED` slots are excluded — and reports the `BOOKED` subset as `booked_slots`, the `HELD` subset as `held_slots`, the `OPEN` subset as `open_slots`, and the teacher's `WAITING` waitlist entries in the window as `waiting_entries`, echoing the `teacher_id` and `window_id`. The `booked_utilization_pct` is one hundred times the booked count divided by the bookable count, rounded half-up to two decimal places, and reports 0.00 when there are no bookable slots. The `projected_utilization_pct` is forward-looking: it adds the held count plus half the waiting entries rounded up to a whole number to the booked count before dividing by the same bookable count — one hundred times that quotient, rounded half-up to two decimal places — so the projection is strictly larger than the booked figure whenever held slots or expected claims exist.

An interpreter's summary, also keyed by a required `window_id`, exposes the capacity arithmetic of §3.7 directly: `committed_minutes_in_window`, the `break_allowance_minutes`, the resulting `capacity_minutes`, and the remaining `headroom_minutes`, alongside `confirmed_assignments` — the count of the interpreter's `CONFIRMED` requests in the window — and the `pay_estimate_cents` computed by the per-assignment rounding rule, with the `interpreter_id` and `window_id` echoed.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a window, teacher, family, student, student-teacher link, booking, interpreter, interpreter request, waitlist entry, or outreach task — return a `201 Created` status code; the waitlist claim also returns `201 Created` because it creates the booking it produces. Operations that modify an existing resource, drive a state transition, or read data return a `200 OK` status code. Removing a student-teacher link returns `204 No Content` with no response body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/conf/_clock/set_current_utc` | Set the logical clock | SchoolAdmin |
| POST | `/conf/windows` | Create a conference window (status DRAFT) | SchoolAdmin |
| GET | `/conf/windows` | List windows with filters and pagination | All five roles |
| GET | `/conf/windows/{id}` | Get one window | All five roles |
| PATCH | `/conf/windows/{id}` | Update window configuration (OCC via expected_window_version) | SchoolAdmin |
| POST | `/conf/windows/{id}/publish` | Publish a draft window | SchoolAdmin |
| POST | `/conf/windows/{id}/generate-slots` | Generate or regenerate the slot grid (OCC) | SchoolAdmin |
| POST | `/conf/windows/{id}/open-booking` | Open the window for booking | SchoolAdmin |
| POST | `/conf/windows/{id}/lock` | Lock the window; unfill requests and expire waitlist entries | SchoolAdmin |
| POST | `/conf/windows/{id}/start` | Move the window to in progress | SchoolAdmin |
| POST | `/conf/windows/{id}/complete` | Complete the window | SchoolAdmin |
| POST | `/conf/windows/{id}/archive` | Archive the window | SchoolAdmin |
| POST | `/conf/windows/{id}/run-ops` | Run the ops checkpoint sweeps | SchoolAdmin |
| GET | `/conf/windows/{id}/slots` | List slots of a window with filters | All five roles |
| GET | `/conf/windows/{id}/attendance-report` | Computed attendance report for the window | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/teachers` | Create a teacher | SchoolAdmin |
| GET | `/conf/teachers` | List teachers | All five roles |
| GET | `/conf/teachers/{id}` | Get one teacher | All five roles |
| PATCH | `/conf/teachers/{id}` | Update a teacher; deactivation runs the cascade | SchoolAdmin |
| GET | `/conf/teachers/{id}/slots` | List slots of a teacher | SchoolAdmin, FrontOfficeStaff, Teacher |
| GET | `/conf/teachers/{id}/teacher-links` | List links of a teacher | SchoolAdmin, FrontOfficeStaff, Teacher |
| GET | `/conf/teachers/{id}/summary` | Teacher utilization summary (window_id required) | SchoolAdmin, FrontOfficeStaff, Teacher |
| POST | `/conf/families` | Register a family | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/families/{id}` | Get one family (guardian limited to own id) | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| PATCH | `/conf/families/{id}` | Update family contact fields (guardian limited to own id) | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/families/{id}/clear-strikes` | Clear no-show strikes and restore the family to ACTIVE | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/families/{id}/students` | List students of a family | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/families/{id}/students` | Register a student under a family | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| GET | `/conf/students/{id}` | Get one student | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/students/{id}/withdraw` | Withdraw a student with cancellation cascade | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/students/{id}/teacher-links` | List links of a student | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/students/{id}/teacher-links` | Link a student to a teacher | SchoolAdmin, FrontOfficeStaff |
| DELETE | `/conf/teacher-links/{id}` | Remove a student-teacher link | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/slots/{id}` | Get one slot | All five roles |
| POST | `/conf/slots/{id}/block` | Block an open slot (Teacher limited to own slots) | SchoolAdmin, FrontOfficeStaff, Teacher |
| POST | `/conf/slots/{id}/unblock` | Unblock a slot; promotion may immediately hold it | SchoolAdmin, FrontOfficeStaff, Teacher |
| POST | `/conf/bookings` | Book an open slot, self-service or on behalf | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| GET | `/conf/bookings` | List bookings with filters | SchoolAdmin, FrontOfficeStaff, Teacher, FamilyGuardian |
| GET | `/conf/bookings/{id}` | Get one booking (scoped for Teacher and FamilyGuardian) | SchoolAdmin, FrontOfficeStaff, Teacher, FamilyGuardian |
| POST | `/conf/bookings/{id}/cancel` | Cancel a confirmed booking | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/bookings/{id}/reschedule` | Reschedule a booking with successor creation (OCC) | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/bookings/{id}/attendance` | Mark attendance for a booking | SchoolAdmin, FrontOfficeStaff, Teacher |
| POST | `/conf/interpreters` | Create an interpreter | SchoolAdmin |
| GET | `/conf/interpreters` | List interpreters | SchoolAdmin, FrontOfficeStaff, Interpreter |
| GET | `/conf/interpreters/{id}` | Get one interpreter (Interpreter limited to own id) | SchoolAdmin, FrontOfficeStaff, Interpreter |
| PATCH | `/conf/interpreters/{id}` | Update an interpreter; deactivation bounces assignments | SchoolAdmin |
| GET | `/conf/interpreters/{id}/summary` | Interpreter capacity and pay summary (window_id required) | SchoolAdmin, FrontOfficeStaff, Interpreter |
| POST | `/conf/interpreter-requests` | Manually request an interpreter for a booking | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/interpreter-requests` | List interpreter requests with filters | SchoolAdmin, FrontOfficeStaff, Interpreter, FamilyGuardian |
| GET | `/conf/interpreter-requests/{id}` | Get one interpreter request | SchoolAdmin, FrontOfficeStaff, Interpreter, FamilyGuardian |
| POST | `/conf/interpreter-requests/{id}/assign` | Assign an interpreter explicitly or via auto-selector | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/interpreter-requests/{id}/accept` | Accept an assignment (assigned interpreter only) | Interpreter |
| POST | `/conf/interpreter-requests/{id}/decline` | Decline an assignment (assigned interpreter only) | Interpreter |
| POST | `/conf/interpreter-requests/{id}/cancel` | Cancel an interpreter request | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/waitlist-entries` | Join the waitlist for a student-teacher pair in a window | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| GET | `/conf/waitlist-entries` | List waitlist entries with filters | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| GET | `/conf/waitlist-entries/{id}` | Get one waitlist entry | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/waitlist-entries/{id}/claim` | Claim an offered slot and create the booking | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/waitlist-entries/{id}/decline-offer` | Decline the current offer | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| POST | `/conf/waitlist-entries/{id}/withdraw` | Withdraw a waitlist entry | SchoolAdmin, FrontOfficeStaff, FamilyGuardian |
| GET | `/conf/attendance-records` | List attendance records with filters | SchoolAdmin, FrontOfficeStaff, Teacher, FamilyGuardian |
| GET | `/conf/attendance-records/{id}` | Get one attendance record | SchoolAdmin, FrontOfficeStaff, Teacher, FamilyGuardian |
| GET | `/conf/outreach-tasks` | List outreach tasks with filters | SchoolAdmin, FrontOfficeStaff |
| GET | `/conf/outreach-tasks/{id}` | Get one outreach task | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/outreach-tasks` | Create a manual outreach task for a family | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/outreach-tasks/{id}/contact` | Record a contact attempt | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/outreach-tasks/{id}/resolve` | Resolve a task | SchoolAdmin, FrontOfficeStaff |
| POST | `/conf/outreach-tasks/{id}/dismiss` | Dismiss a task | SchoolAdmin, FrontOfficeStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_WINDOW_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FAMILY_RESTRICTED` | 409 Conflict |
| `ERR_TEACHER_INACTIVE` | 409 Conflict |
| `ERR_SLOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_NO_ACTIVE_OFFER` | 409 Conflict |
| `ERR_BOOKING_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_BOOKING_WINDOW_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_CANCELLATION_CUTOFF` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_DAY_WINDOW` | 422 Unprocessable Entity |
| `ERR_FAMILY_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_INTERPRETER_OVERLAP` | 409 Conflict |
| `ERR_INTERPRETER_FATIGUE` | 422 Unprocessable Entity |
| `ERR_INTERPRETER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LANGUAGE_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_INTERPRETER` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BOOKING` | 409 Conflict |
| `ERR_DUPLICATE_WAITLIST_ENTRY` | 409 Conflict |
| `ERR_DUPLICATE_TEACHER_LINK` | 409 Conflict |
| `ERR_CHANNEL_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ALREADY_HAS_INTERPRETER_REQUEST` | 409 Conflict |
| `ERR_STUDENT_NOT_BOOKABLE` | 422 Unprocessable Entity |
| `ERR_TEACHER_NOT_LINKED` | 422 Unprocessable Entity |
| `ERR_TEACHER_DAY_FULL` | 422 Unprocessable Entity |
| `ERR_FAMILY_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_WINDOW_GRID_LOCKED` | 409 Conflict |
| `ERR_SLOTS_ALREADY_BOOKED` | 409 Conflict |
| `ERR_OPEN_OUTREACH_TASKS` | 409 Conflict |
