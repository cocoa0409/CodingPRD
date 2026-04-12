# Meeting Room API — Product Requirements Document

## 1. Introduction

Modern organizations face a persistent challenge: the efficient allocation of shared meeting spaces across teams with competing schedules, varying authority levels, and differing resource requirements. A room that sits empty due to a no-show wastes valuable real estate; a double-booked conference room disrupts critical decision-making. This document specifies the requirements for a Meeting Room Management API designed to bring order to this chaos through structured reservation workflows, automated conflict detection, and transparent cost accounting.

The system supports the full booking lifecycle — from tentative reservation through check-in and completion — while accommodating recurring meeting series, premium room approval chains, waitlist-based slot recovery, and automated no-show detection. Three distinct roles govern access: employees who book standard rooms for daily collaboration, managers who approve premium room reservations and can override scheduling conflicts, and facility administrators who maintain the room inventory, trigger operational housekeeping, and audit all booking mutations. Every state change is captured in an immutable audit trail, ensuring full accountability across the organization.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes three roles with exact spellings: `employee`, `manager`, and `facility_admin`. Any request missing either header or presenting an unrecognized role value is rejected with `ERR_AUTH_REQUIRED`. When a user attempts an operation outside the scope of their role — for instance, an `employee` trying to approve a premium booking — the system responds with `ERR_FORBIDDEN`.

### 2.2. API Response Structure

#### Standard Success Response

All successful API responses adhere to the following JSON envelope:

```json
{
  "meta": {
    "api_request_id": "req_rm_7f3a9b2e4d01",
    "api_request_timestamp": "2026-04-12T14:05:32.871Z",
    "limit": 20,
    "offset": 0,
    "total_count": 47,
    "has_more": true
  },
  "response_type": "array",
  "data": []
}
```

#### Standard Error Response

All error responses (4xx status codes) use this envelope:

```json
{
  "meta": {
    "api_request_id": "req_rm_c8d12e5f9a03",
    "api_request_timestamp": "2026-04-12T14:06:11.204Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_TIME_CONFLICT",
    "message": "The requested time slot overlaps with an existing confirmed booking on this room."
  }
}
```

The `api_request_id` is a server-generated unique identifier for every request. The `api_request_timestamp` is an ISO 8601 UTC timestamp with exactly three fractional digits. The `response_type` field distinguishes between `"object"` for single-resource responses, `"array"` for list responses, and `"error"` for failures. The `data` field carries the business payload: a resource object, an array of resource objects, or an empty object for successful operations with no return body. For error responses, `data` contains `error_id` (a machine-readable identifier) and `message` (a human-readable explanation). Pagination fields — `limit`, `offset`, `total_count`, and `has_more` — appear in the `meta` object only for list endpoint responses.

### 2.3. Pagination

List endpoints accept two query parameters for pagination: `limit` controls the maximum number of items returned per page, defaulting to 20, with a minimum of 1 and a maximum of 100; `offset` controls the number of items to skip, defaulting to 0. All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified. The response `meta` object for list endpoints always includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Temporal Conflict Detection and Half-Open Intervals

Scheduling correctness is the backbone of the meeting room system. Two bookings are considered to overlap if and only if one starts before the other ends and the other starts before the first ends — formally, when `booking_a.start_time < booking_b.end_time AND booking_b.start_time < booking_a.end_time`. The system uses half-open interval semantics: the start time is inclusive and the end time is exclusive. This design permits back-to-back bookings where one meeting ends at the exact moment the next begins. Only bookings in `CONFIRMED` or `CHECKED_IN` status occupy a time slot; `TENTATIVE` and `PENDING_APPROVAL` bookings are speculative and do not block the room.

### 2.5. Room Tiers and the Approval Workflow

Rooms are classified into two tiers: `STANDARD` and `PREMIUM`. This distinction governs the booking confirmation path. A booking for a `STANDARD` room proceeds automatically from `TENTATIVE` to `CONFIRMED` upon creation, provided no time conflict exists with already-confirmed or checked-in bookings. A booking for a `PREMIUM` room, however, transitions from `TENTATIVE` to `PENDING_APPROVAL`, requiring explicit managerial sign-off before confirmation. This two-track workflow ensures that high-value spaces receive appropriate oversight while routine rooms remain frictionless.

### 2.6. Common Resource Properties and Versioning

All primary resources — Rooms, Bookings, Series, and Waitlist entries — include a standard set of system-managed fields. The `id` field is a system-generated UUID string. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits (e.g., `2026-04-12T09:15:00.000Z`), recording creation and last-modification times respectively. The `version` field is a system-managed integer that starts at 1 and increments on every mutation to the resource. AuditLog entries, being immutable after creation, carry only `id` and `timestamp` — they omit `updated_at` and `version`.

### 2.7. Optimistic Concurrency Control

Mutation operations on resources support optimistic concurrency through an optional `version` field in the request body. When provided, the server compares the supplied version against the resource's current version; a mismatch results in rejection with `ERR_VERSION_CONFLICT`. Omitting the version field bypasses this check entirely, allowing the mutation to proceed unconditionally. This mechanism safeguards against lost updates in concurrent environments while remaining unobtrusive for clients that do not require strict ordering guarantees.

### 2.8. Cost Precision and Rounding

All monetary values in the system are expressed in integer cents. The booking cost calculation produces an integer result. When intermediate per-minute rates produce fractional values, the system accumulates them and applies round-half-up rounding once at the very end to yield the final `cost_cents` value. Segment-level rounding is explicitly avoided; the summation of all minute-level rates is rounded only after the complete interval has been processed.

### 2.9. Cascading State Propagation

When a room transitions to `MAINTENANCE` or `DECOMMISSIONED`, the system must reconcile all dependent resources to maintain consistency. Transitioning a room to maintenance cancels all future bookings that have not yet been checked in — including those in `TENTATIVE`, `PENDING_APPROVAL`, and `CONFIRMED` states — and notifies affected waitlist entries. Decommissioning is more severe: it is blocked entirely if any booking is currently in the `CHECKED_IN` state (yielding `ERR_ROOM_HAS_ACTIVE_BOOKINGS`), and upon success, all future non-terminal bookings are cancelled and all `WAITING` waitlist entries are expired. Both transitions update `updated_at` and increment `version` on the room. Every cascaded state change produces its own audit log entry.

### 2.10. Audit Trail Integrity

Every mutation to a booking, room, series, or waitlist entry generates an immutable audit log record. Each record captures the `actor_id` and `actor_role` of the user who initiated the change, the `action` performed (such as `booking.created` or `booking.confirmed`), the `resource_type` and `resource_id` of the affected entity, and a `details` object containing before-and-after state snapshots. Audit logs are append-only; they cannot be modified or deleted after creation.

## 3. Business Logic & Workflows

### 3.1. Room Provisioning and Configuration

A `facility_admin` provisions a new room by supplying a `name` (which must be unique across the system — a duplicate triggers `ERR_ROOM_NAME_TAKEN`), a `capacity` indicating maximum occupants, a `floor` number, and a `tier` designation of either `STANDARD` or `PREMIUM`. Optionally, the administrator may attach a list of `amenities` — tags such as `PROJECTOR`, `WHITEBOARD`, `VIDEO_CONF`, or `PHONE` — to help users find appropriately equipped spaces. Upon creation, the room enters the `ACTIVE` state with its `ops_run_index` initialized to zero.

Pricing configuration is set at room creation and can be adjusted later. The `hourly_rate_cents` establishes the base cost per hour. For rooms that experience heavier demand during business hours, the administrator may configure a `peak_multiplier` (defaulting to 1.0 if omitted), along with `peak_hours_start` and `peak_hours_end` in HH:MM 24-hour format (for example, `09:00` and `17:00`). During peak hours, the effective per-minute rate is the base rate divided by sixty, then multiplied by the peak factor. Outside peak hours, the standard per-minute rate applies. Listing rooms supports filtering by `status`, `tier`, `min_capacity`, `floor`, and `amenity`.

### 3.2. The Booking Lifecycle

Booking a room begins when any authenticated user creates a reservation by specifying the `room_id`, a `title` for the meeting, the `start_time` and `end_time` as ISO 8601 timestamps, and the expected `attendee_count`. The `organizer_id` is automatically set from the `X-User-ID` header. Before the booking is accepted, the system enforces several temporal guards: the `end_time` must be strictly after the `start_time` (otherwise `ERR_INVALID_TIME_RANGE`), the duration must span at least a quarter of an hour (`ERR_BOOKING_TOO_SHORT`), and cannot exceed eight hours (`ERR_BOOKING_TOO_LONG`). Furthermore, the `start_time` must lie in the future (`ERR_BOOKING_IN_PAST`), and the `attendee_count` must not exceed the room's `capacity` (`ERR_CAPACITY_EXCEEDED`). The room must be in the `ACTIVE` state; attempts to book a room under `MAINTENANCE` or `DECOMMISSIONED` are rejected with `ERR_ROOM_NOT_ACTIVE`.

Upon passing validation, the booking is created in the `TENTATIVE` state. What happens next depends on the room's `tier`. For a `STANDARD` room, the system immediately checks for time conflicts against existing `CONFIRMED` and `CHECKED_IN` bookings on that room. If the slot is clear, the booking auto-transitions to `CONFIRMED` and its `cost_cents` is computed. If a conflict is detected, the request is rejected with `ERR_TIME_CONFLICT`. For a `PREMIUM` room, the booking transitions to `PENDING_APPROVAL` regardless of slot availability — the conflict check is deferred to the moment of managerial approval.

Once a booking reaches `CONFIRMED`, the occupant may check in. Check-in is permitted within a window starting fifteen minutes before `start_time` and lasting through `end_time`. Attempting to check in outside this window is rejected with `ERR_CHECKIN_WINDOW`. Upon successful check-in, the booking moves to `CHECKED_IN` and the `checked_in_at` timestamp is recorded. Early departure is supported via check-out, which transitions the booking from `CHECKED_IN` to `COMPLETED`, releasing the room for subsequent use.

Cancellation is available from the `TENTATIVE`, `PENDING_APPROVAL`, or `CONFIRMED` states. Any user with at least `employee` privileges may cancel a booking. When a booking is cancelled, the time slot is released, and the waitlist promotion algorithm evaluates whether a waiting entry can be promoted into the freed slot. If the cancelled booking belongs to a recurring series, only that individual occurrence is cancelled — the series itself remains intact.

Bookings can be listed with optional filters for `room_id`, `organizer_id`, `status`, `start_after`, and `start_before`.

### 3.3. Premium Room Approval and Rejection

When a booking targets a `PREMIUM` room, it enters `PENDING_APPROVAL` and awaits action from a `manager` or `facility_admin`. Approval transitions the booking to `CONFIRMED`, but only after the system re-validates for time conflicts at that moment — the slot may have been taken by another booking in the interim, and if so, the approval is rejected with `ERR_TIME_CONFLICT`. Upon confirmation, the `cost_cents` is calculated based on the booking's duration and the room's pricing configuration. The booking must also reference a room that is still `ACTIVE`; if the room has since entered `MAINTENANCE` or been `DECOMMISSIONED`, the approval fails.

Rejection is the alternative outcome. A `manager` or `facility_admin` rejects a pending booking by providing a `rejection_reason`, which is recorded on the booking. The booking transitions to `CANCELLED`, and any waitlist entries covering the same room and overlapping time are evaluated for promotion.

### 3.4. Recurring Series Management

For meetings that repeat on a predictable cadence, the system supports recurring booking series. An authenticated user creates a series by specifying the target `room_id`, a `title`, the `recurrence_rule` (one of `DAILY`, `WEEKLY`, or `BIWEEKLY`), the `start_time` as an HH:MM time-of-day, the `duration_minutes` for each occurrence, the `attendee_count`, and the bounding `series_start_date` and `series_end_date` in YYYY-MM-DD format. The `series_end_date` must be after the `series_start_date` (`ERR_INVALID_SERIES_RANGE`), and the resulting date range must produce at least one booking occurrence (`ERR_EMPTY_SERIES`).

Upon creation, the system generates individual Booking records for each occurrence within the date range. Every generated booking carries a `series_id` linking it back to the parent series. Each booking follows the normal confirmation flow: for `STANDARD` rooms, occurrences that do not conflict are immediately confirmed with cost computed, while those that would overlap existing confirmed bookings are created as `TENTATIVE` and flagged. For `PREMIUM` rooms, all occurrences enter `PENDING_APPROVAL`. The series tracks the `total_bookings` count of generated occurrences. The same temporal validations apply to each occurrence: minimum fifteen minutes, maximum eight hours, attendee count within capacity, and the room must be `ACTIVE`.

Cancelling an entire series transitions the series `status` from `ACTIVE` to `CANCELLED` and cancels all future bookings in the series that are still in `TENTATIVE`, `PENDING_APPROVAL`, or `CONFIRMED` states. Bookings that have already reached `COMPLETED`, `NO_SHOW`, or `CANCELLED` are left untouched. Freed slots trigger waitlist promotions for each affected time window.

### 3.5. Waitlist Mechanics and Slot Recovery

When a desired time slot is unavailable, users can join a waitlist by specifying the `room_id`, a `title`, the desired `start_time` and `end_time`, and the expected `attendee_count`. The same temporal and capacity validations apply: the room must be `ACTIVE`, the time range must be valid and in the future, and the attendee count must fit the room. Additionally, a duplicate waitlist entry — matching the same `requester_id`, `room_id`, and exact time window — is rejected with `ERR_DUPLICATE_WAITLIST`. The `requester_id` is derived from the `X-User-ID` header.

Each new waitlist entry receives a `position` reflecting its place in the queue for that room and time slot, following first-in-first-out ordering. When a slot becomes available — through cancellation, rejection of a pending approval, or a no-show — the system initiates waitlist promotion. The algorithm identifies all `WAITING` entries for the same room whose requested `start_time` and `end_time` are fully contained within the freed slot. These candidates are sorted by `position` in ascending order. The first entry whose `attendee_count` does not exceed the room's `capacity` and whose promoted booking would not overlap with any remaining `CONFIRMED` or `CHECKED_IN` bookings is selected. Only one promotion occurs per triggering event.

Upon promotion, the waitlist entry transitions from `WAITING` to `PROMOTED`, and a new `TENTATIVE` booking is automatically created from the waitlist entry's parameters. This booking then follows the standard confirmation flow based on the room's tier. Remaining waitlist entries for the same slot are re-positioned to close the gap left by the promoted entry.

Waitlist entries can be cancelled by the requester (or a manager or facility admin) via a DELETE request, transitioning the entry to `CANCELLED` and re-positioning remaining entries. The entry must be in the `WAITING` state; otherwise the request fails with `ERR_INVALID_WAITLIST_STATE`. Listing waitlist entries supports filtering by `room_id`, `requester_id`, and `status`.

### 3.6. Booking Cost Computation

Cost calculation occurs when a booking is confirmed — either automatically for standard rooms or upon managerial approval for premium rooms. The algorithm divides the booking interval from `start_time` to `end_time` into minute-by-minute segments. For each minute, the system determines whether it falls within the room's peak window (the half-open interval from `peak_hours_start` to `peak_hours_end`). Peak minutes are charged at the room's `hourly_rate_cents` divided by sixty and then multiplied by the `peak_multiplier`. Off-peak minutes use the base rate divided by sixty without any multiplier.

Consider a booking from 08:00 to 10:00 on a room with a base rate of 6000 cents per hour, a peak multiplier of 1.5, and peak hours from 09:00 to 17:00. The first sixty minutes (08:00-09:00) are off-peak at 100 cents per minute, totaling 6000. The next sixty minutes (09:00-10:00) are peak at 150 cents per minute, totaling 9000. The final `cost_cents` is the rounded result of summing all minute-level rates: 15000 cents. When a booking falls entirely outside the peak window, the computation simplifies to the duration in minutes multiplied by the base hourly rate divided by sixty. When it falls entirely within the peak window, the peak multiplier is applied uniformly. The critical edge case arises when a booking straddles the peak boundary — the system must split at the boundary and apply different rates to each segment, rounding only after summing all segments.

### 3.7. Operational Housekeeping and No-Show Detection

A `facility_admin` triggers operational housekeeping on a room by invoking the run_ops endpoint. Each invocation increments the room's `ops_run_index` monotonically. The operation performs two sweeps across the room's active bookings and waitlist entries.

First, no-show detection: for every `CONFIRMED` booking on this room whose `start_time` plus a fifteen-minute grace period has elapsed without a check-in, the system transitions the booking to `NO_SHOW`. This reflects the policy that occupants who fail to arrive within a quarter hour of their scheduled start forfeit their reservation. Each no-show frees the associated time slot and triggers waitlist promotion.

Second, waitlist expiry: for every `WAITING` entry whose `start_time` has already passed, the system transitions the entry to `EXPIRED`. There is no point in holding a slot request for a time that has already gone by.

Both sweeps produce audit log entries for every state transition. The resulting promotions from no-show-freed slots follow the standard waitlist promotion algorithm described in the previous section.

### 3.8. Room Lifecycle Management

Rooms progress through three states: `ACTIVE`, `MAINTENANCE`, and `DECOMMISSIONED`. Only a `facility_admin` may trigger these transitions via the room update endpoint. A room begins in the `ACTIVE` state upon creation and can move to `MAINTENANCE` at any time. Returning a room from `MAINTENANCE` to `ACTIVE` makes it available for new bookings again.

Decommissioning is a terminal action available from either `ACTIVE` or `MAINTENANCE`. Before the system permits decommissioning, it verifies that no booking is currently in the `CHECKED_IN` state on that room; if one exists, the transition is blocked with `ERR_ROOM_HAS_ACTIVE_BOOKINGS`. Upon successful decommissioning, all future non-terminal bookings are cancelled, and all `WAITING` waitlist entries are expired. A `DECOMMISSIONED` room cannot return to any other state.

Updating room properties such as `name`, `capacity`, `amenities`, `tier`, `hourly_rate_cents`, `peak_multiplier`, `peak_hours_start`, or `peak_hours_end` is permitted at any time by a facility admin. Reducing a room's capacity does not retroactively cancel existing bookings that exceed the new limit — it only prevents new bookings from exceeding it.

## 4. Endpoint Definitions

Resource creation endpoints return `201 Created`. All other successful operations — including state transitions, approvals, rejections, cancellations, and check-ins — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/rooms` | Create a new meeting room | facility_admin |
| GET | `/rooms` | List all rooms with optional filters | employee, manager, facility_admin |
| GET | `/rooms/{room_id}` | Get room details | employee, manager, facility_admin |
| PUT | `/rooms/{room_id}` | Update room details | facility_admin |
| POST | `/rooms/{room_id}/run_ops` | Run operations housekeeping on a room | facility_admin |
| POST | `/bookings` | Create a new booking | employee, manager, facility_admin |
| GET | `/bookings` | List bookings with optional filters | employee, manager, facility_admin |
| GET | `/bookings/{booking_id}` | Get booking details | employee, manager, facility_admin |
| POST | `/bookings/{booking_id}/approve` | Approve a pending premium booking | manager, facility_admin |
| POST | `/bookings/{booking_id}/reject` | Reject a pending premium booking | manager, facility_admin |
| POST | `/bookings/{booking_id}/check-in` | Check in to a confirmed booking | employee, manager, facility_admin |
| POST | `/bookings/{booking_id}/check-out` | Check out of a booking (early release) | employee, manager, facility_admin |
| POST | `/bookings/{booking_id}/cancel` | Cancel a booking | employee, manager, facility_admin |
| POST | `/series` | Create a recurring booking series | employee, manager, facility_admin |
| GET | `/series/{series_id}` | Get series details including linked bookings | employee, manager, facility_admin |
| POST | `/series/{series_id}/cancel` | Cancel entire series | employee, manager, facility_admin |
| POST | `/waitlist` | Join the waitlist for a room and time slot | employee, manager, facility_admin |
| GET | `/waitlist` | List waitlist entries with optional filters | employee, manager, facility_admin |
| DELETE | `/waitlist/{waitlist_id}` | Cancel a waitlist entry | employee, manager, facility_admin |
| GET | `/audit-logs` | List audit log entries with optional filters | facility_admin |
| GET | `/audit-logs/{log_id}` | Get a single audit log entry | facility_admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_BAD_REQUEST` | 400 Bad Request |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_WAITLIST_NOT_FOUND` | 404 Not Found |
| `ERR_SERIES_NOT_FOUND` | 404 Not Found |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_ROOM_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_BOOKING_STATE` | 409 Conflict |
| `ERR_INVALID_WAITLIST_STATE` | 409 Conflict |
| `ERR_INVALID_SERIES_STATE` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_BOOKING_TOO_SHORT` | 400 Bad Request |
| `ERR_BOOKING_TOO_LONG` | 400 Bad Request |
| `ERR_BOOKING_IN_PAST` | 400 Bad Request |
| `ERR_CHECKIN_WINDOW` | 400 Bad Request |
| `ERR_TIME_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 400 Bad Request |
| `ERR_ROOM_HAS_ACTIVE_BOOKINGS` | 409 Conflict |
| `ERR_DUPLICATE_WAITLIST` | 409 Conflict |
| `ERR_INVALID_SERIES_RANGE` | 400 Bad Request |
| `ERR_EMPTY_SERIES` | 400 Bad Request |
| `ERR_ROOM_NAME_TAKEN` | 409 Conflict |
