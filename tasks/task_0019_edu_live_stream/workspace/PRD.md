# Edu Live Stream API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Edu Live Stream API, the back-end service that powers an online education platform built around live, instructor-led courses. The platform sits at the intersection of three operational concerns: a structured publishing pipeline that takes a course from instructor draft through academic review to public listing; a teaching surface that schedules live classes against shared rooms and instructor calendars, captures student attendance, and runs an iterative assignment-grading loop; and a fiscal surface that handles enrolment payments, tracks learning progress against time- and content-based thresholds, and produces refunds whose amount depends on when in a student's journey the request is made and approved.

The product distinguishes itself from a generic LMS by treating these surfaces as a single integrated state machine. Delisting a published course does not just hide it — it cancels every scheduled live class for that course, flips affected students into an at-risk learning posture, and re-prices any pending refund requests that touch those students. A student's progress is computed two different ways from the same telemetry (chapter completions versus accumulated watch duration) and the two results may legitimately disagree; the system must hold both numbers and apply a deterministic tie-break. A refund is computed twice as well — once when the student requests it, then again when the academic administrator approves it — because progress and attendance can both move in the interim.

The audience for this document is the engineering team responsible for the REST service. It defines the entities the system stores, the role-based access model, the state transitions and their preconditions, the calculation rules with their constants and rounding behaviour, and the full error catalogue. Wherever a numeric threshold or a formula appears, it is the contract; wherever a state name appears in `UPPERCASE`, the spelling is the contract.

## 2. Global Specifications & System-Wide Principles

This section collects the cross-cutting rules that apply to every endpoint in the API. Endpoint-specific business logic is in §3; this section establishes the structural and system-wide contracts that everything in §3 builds on.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller. The `X-User-ID` header identifies the acting user; `X-User-Role` declares the operational capacity in which they are acting. Requests that omit either header, or that send a value that is empty or otherwise invalid, are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Requests whose role is syntactically valid but is not authorised for the targeted endpoint are rejected with `ERR_FORBIDDEN_ROLE`.

The system recognises exactly four roles, spelled exactly as follows: `Instructor`, `TeachingAssistant`, `Student`, and `AcademicAdmin`. The first three are tied to persisted entities; the last is an opaque operator identity.

When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor` entity. Ownership checks on any resource that references an `Instructor` (most importantly a `Course`, where ownership is recorded in `instructor_id`, and a `LiveClass`, where the lead or substitute instructor is similarly recorded in `instructor_id`) compare the resource's foreign-key field to `X-User-ID`. A mismatch surfaces as `ERR_FORBIDDEN_NOT_OWNER`.

When `X-User-Role` is `TeachingAssistant`, `X-User-ID` is also the `id` of an `Instructor` entity — teaching assistants are physically stored as `Instructor` rows. Their TA scope is granted by being named in a `ClassGroup`'s `ta_instructor_id` field; they do not own `Course` resources but may act on submissions and announcements in groups where they are the assigned TA.

When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` entity. Ownership checks on any resource that references a `Student` (most importantly an `Enrollment`, whose owning student is recorded in `student_id`) compare the resource's foreign-key field to `X-User-ID`.

When `X-User-Role` is `AcademicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditLogEntry` when the scaffolded transition writes it) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled by two query parameters. The `limit` parameter caps the number of items returned; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; it defaults to 0 and has no upper bound beyond the size of the underlying collection.

Unless explicitly overridden, every list endpoint returns its items sorted by `created_at` in ascending order. Paginated responses include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

The mutable, top-level resources of the system — `Course`, `Chapter`, `Instructor`, `Student`, `Enrollment`, `ClassGroup`, `LiveClass`, `LeaveRequest`, `Assignment`, `Submission`, and `RefundRequest` — each carry the following system-managed fields:

- `id` (string): a server-minted UUID, written without any type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the row is first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation that changes any other field on the resource.
- `version` (integer): a monotonic counter that starts at the resource's creation value and increments by one on every mutation. It is used for the optimistic concurrency control mechanism described in §2.5.

A handful of entities are append-only or immutable snapshots and therefore carry only `id` and `created_at`; both `updated_at` and `version` are absent for them. Those entities are: `SyllabusRevision` (an immutable revision snapshot), `Announcement` (an immutable post), `Attendance` (an append-only check-in event), `WatchSession` (append-only video telemetry), `AuditLogEntry` (append-only audit row), and `Clock` (the singleton test-driving clock).

### 2.5. Optimistic Concurrency Control

Endpoints that modify a resource by its identifier accept an optional `version` value in the request body. When present, the server compares it to the current `version` of the target row and rejects the request with `ERR_STALE_DATA` if they differ. When the field is omitted, the server processes the mutation without an OCC check. A successful mutation refreshes `updated_at` and increments `version` by one, so a follow-up call submitting the previous `version` value will fail.

### 2.6. Hierarchical Path Resolution

Many endpoints embed multiple identifiers in their URL path — for example a chapter is addressed as a child of its course, a refund is addressed by its own id but cascades down to its enrollment. When a request targets a nested resource, the server validates each identifier in left-to-right order and returns the not-found error of the first identifier that fails to resolve. If the parent course in `/courses/{courseId}/chapters` does not exist, the response is `ERR_COURSE_NOT_FOUND` regardless of whether the chapter id would also be missing. The corresponding 404 error ids are: `ERR_COURSE_NOT_FOUND`, `ERR_CHAPTER_NOT_FOUND`, `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_LIVE_CLASS_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`, `ERR_LEAVE_NOT_FOUND`, and `ERR_CLASS_GROUP_NOT_FOUND`.

### 2.7. Course Posture and Cascading Consistency

Every `Course` carries two related but distinct enumerated fields. The persisted `status` follows the publishing lifecycle and takes the values `DRAFT`, `UNDER_REVIEW`, `PUBLISHED`, `REJECTED`, and `DELISTED`. A derived `posture` summarises the course's operational openness for the rest of the system and takes the values `OPEN`, `RESTRICTED`, and `FROZEN`. A newly created course starts at `status = DRAFT` and `posture = RESTRICTED`. Approval moves `posture` to `OPEN`; delisting moves it to `FROZEN`. Several runtime checks key off `posture` rather than `status`, so any transition that mutates `status` must recompute and persist `posture` in the same write.

When a parent state change has consequences on dependent rows — most prominently the depth-three delist cascade described in §3 — every dependent row that is rewritten in the cascade is treated as a real mutation: its `updated_at` is refreshed and its `version` is incremented in the same transaction that rewrites the parent, so subsequent OCC-aware callers will see the cascade's effect.

### 2.8. Validation Priority

When multiple validation rules apply to the same request, the server evaluates them in the following order and returns the first failure it encounters: (1) presence and validity of the `X-User-ID` and `X-User-Role` headers, surfacing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission for the targeted endpoint, surfacing `ERR_FORBIDDEN_ROLE`; (3) existence of every path-resource in left-to-right order, surfacing the appropriate 404 from §2.6; (4) ownership for entity-backed roles, surfacing `ERR_FORBIDDEN_NOT_OWNER`; (5) the source entity is in the required state for the requested transition, surfacing the relevant state error such as `ERR_COURSE_NOT_UNDER_REVIEW`, `ERR_SUBMISSION_NOT_UNDER_REVIEW`, `ERR_REFUND_NOT_PENDING`, `ERR_LIVE_CLASS_NOT_LIVE`, `ERR_LIVE_CLASS_NOT_SCHEDULED`, `ERR_LEAVE_NOT_PENDING`, `ERR_COURSE_NOT_PUBLISHED`, `ERR_COURSE_NOT_REJECTED`, or `ERR_SUBMISSION_NOT_SUBMITTED` / `ERR_SUBMISSION_NOT_AWAITING_REVISION`; (6) the parent course's `posture` permits the operation, surfacing `ERR_COURSE_FROZEN`; (7) plagiarism block on grading, surfacing `ERR_PLAGIARISM_BLOCKED`; (8) room overlap on live-class scheduling, surfacing `ERR_ROOM_CONFLICT`; (9) instructor availability on live-class scheduling, surfacing `ERR_INSTRUCTOR_UNAVAILABLE`; (10) check-in window timing, surfacing `ERR_CHECKIN_WINDOW_CLOSED`; (11) class group capacity, surfacing `ERR_CLASS_GROUP_FULL`; (12) submission revision cap, surfacing `ERR_REVISION_CAP_REACHED`; (13) submission payload format match, surfacing `ERR_PAYLOAD_FORMAT_MISMATCH`; (14) submission timing relative to the assignment's `due_ts`, surfacing `ERR_SUBMISSION_PAST_DUE`; (15) refund idempotency, surfacing `ERR_REFUND_ALREADY_REQUESTED`; (16) refund pricing inputs, surfacing `ERR_INVALID_PRICING`; and (17) the score range on grading, surfacing `ERR_SCORE_OUT_OF_RANGE`.

This ordering matters in practice. For example, if a `Course` is `FROZEN` and the caller is also not the owner, the ownership error fires first because ownership is priority 4 and posture is priority 6.

### 2.9. Monetary Values, Progress Precision, and Rounding

All monetary amounts in the system are stored and exchanged as integer cents — never as decimals or strings. The course catalogue's `list_price_cents`, the per-enrollment `paid_amount_cents`, the deduction constants, and both the provisional and final refund amounts (`provisional_amount_cents`, `final_amount_cents`) are integers. Whenever a percentage is multiplied by a cent value, the product is rounded half-up to the nearest integer cent before any further deductions are subtracted. The same round-half-up rule is the canonical rounding mode for any other rounding step that the calculations in §3 invoke.

Progress percentages (`chapter_completion_percent`, `watch_duration_percent`, `progress_percent`, and the `provisional_progress_percent` snapshot recorded on a refund request) are stored as numbers with one decimal place, rounded half-up. Comparisons against the at-risk thresholds use strict inequality directions exactly as written.

### 2.10. Audit Logging and the Test-Driving Clock

A subset of operations leave an immutable footprint in `AuditLogEntry`. Each entry records the `actor_role` (one of `INSTRUCTOR`, `TEACHING_ASSISTANT`, `STUDENT`, or `ACADEMIC_ADMIN`), the `actor_id` taken directly from the `X-User-ID` header that drove the operation, the `action` (one of `ENROLLMENT_CREATED`, `ENROLLMENT_GROUPED`, `ENROLLMENT_WITHDRAWN`, `REFUND_REQUESTED`, `REFUND_APPROVED`, or `REFUND_REJECTED`), the `subject_type` (one of `ENROLLMENT` or `REFUND_REQUEST`), the `subject_id` of the affected row, and a `detail` JSON snapshot capturing the relevant before/after fields for the action.

The system also maintains a logical clock — the singleton `Clock` entity with a single `now_ts` field expressed in Unix seconds — which is the wall-clock value that all time-gated checks (refund time-window, at-risk evaluation, check-in window) read. The clock can be advanced by a privileged test-driving capability that accepts a body containing a `seconds` increment. Advancing the clock re-evaluates the at-risk alert across every enrollment as a side effect.

## 3. Business Logic & Workflows

### 3.1. The Course Publishing Lifecycle

A `Course` is the system's central organising entity. An `Instructor` creates one by submitting a `title`, the foreign-key `instructor_id` identifying the lead instructor, the catalogue `list_price_cents`, and an optional `discount_percent` that defaults to zero when omitted. The newly created course lands in `status = DRAFT` with `posture = RESTRICTED`. The price must be at least zero and the discount, if supplied, must lie between zero and eighty inclusive; values outside that range cause `ERR_INVALID_PRICING`. While a course is in `DRAFT` (or, after a rejection, back in `DRAFT`) the owning instructor may freely modify the `title`, `list_price_cents`, and `discount_percent` and may also add `Chapter` rows that describe the syllabus.

Each chapter is created with a `title`, a one-based `ordinal` whose value must be unique within its parent course (recorded internally as `course_id`), an authoritative `video_duration_seconds` length that must be strictly greater than zero, and an optional `required_for_completion` flag that defaults to true. A chapter whose `required_for_completion` is false is treated as bonus material and is excluded from the chapter-completion progress numerator. The `total_chapters` and `total_video_seconds` aggregates on the parent course are computed automatically from the chapter set, and the parent course's `enrollment_count` is the count of `Enrollment` rows whose status is in the set comprising `ACTIVE`, `AT_RISK`, `COMPLETED`, and `REFUND_PENDING`.

Once the syllabus is satisfactory, the instructor submits the course for academic review, transitioning `status` from `DRAFT` to `UNDER_REVIEW`. Submitting requires that the caller is the course owner (`ERR_FORBIDDEN_NOT_OWNER`), that at least one chapter exists with `required_for_completion` set to true (`ERR_COURSE_NO_CHAPTERS`), and that the pricing fields are within their valid ranges (`ERR_INVALID_PRICING`). The submission also writes a fresh `SyllabusRevision` row whose `revision_number` is the current maximum for this course plus one — the very first revision is therefore numbered one — and whose `outline` array, `pricing_snapshot_cents`, and `discount_snapshot_percent` are captured at the moment of submission. The outline must contain at least one ordered entry of `chapter_title` and `learning_objectives`. A `SyllabusRevision` is, after creation, immutable.

An `AcademicAdmin` then reviews the under-review course. Approval transitions the course from `UNDER_REVIEW` to `PUBLISHED` and is rejected with `ERR_COURSE_NOT_UNDER_REVIEW` if the course is in any other status. On approval, the system pins the latest `SyllabusRevision`'s id onto the course's `published_syllabus_revision_id` field — this is the version-pinning step that lets the system reconstruct exactly which syllabus a `PUBLISHED` course made public — and recomputes the course's `posture` to `OPEN`. Rejection by an `AcademicAdmin` instead transitions `UNDER_REVIEW` to `REJECTED`; the same `ERR_COURSE_NOT_UNDER_REVIEW` guards the source state. From `REJECTED`, the owning instructor can return the course to `DRAFT` (rejected with `ERR_FORBIDDEN_NOT_OWNER` if the caller is not the owner, and with `ERR_COURSE_NOT_REJECTED` if the course is not in `REJECTED`); this completes the revert leg of the branching publishing shape.

Delisting is the heaviest operation in the lifecycle. An `AcademicAdmin` may delist only a course whose `status` is `PUBLISHED`; otherwise the request fails with `ERR_COURSE_NOT_PUBLISHED`. A delist transitions `status` to the terminal `DELISTED` and triggers a depth-three cascade in a single transaction. First, every `LiveClass` belonging to this course that is currently in `SCHEDULED` is moved to `CANCELLED` with the reason `COURSE_DELISTED`. Second, those cancellations themselves cascade: for every enrollment whose `learning_status` was `ACTIVE` and whose attendance window overlaps a now-cancelled live class, `learning_status` flips to `AT_RISK`. Third, every enrollment that flipped to `AT_RISK` in step two has any associated `PENDING` `RefundRequest` re-priced — its `provisional_amount_cents` is recomputed against the now-frozen course context. Finally, the course's `posture` is recomputed to `FROZEN`. Each cascaded row is treated as a real mutation per §2.7, refreshing `updated_at` and incrementing `version`. While the course is `FROZEN`, several operations are blocked with `ERR_COURSE_FROZEN`, including starting a live class, creating a new enrollment, and approving a refund. In a race where delist and live-class start fire concurrently against a `PUBLISHED` course, the system serialises on the course's status: if delist commits first, the start sees a frozen course and is rejected with `ERR_COURSE_FROZEN`; if start commits first, the live class proceeds and the cascade does not include it.

### 3.2. Instructors, Students, Class Groups, and Announcements

`Instructor` rows are registered by an `AcademicAdmin` and carry a public `display_name`, a unique contact `email`, a free-form `bio`, and an `availability_windows` array. Each window is a closed interval of Unix seconds — represented as a pair of `start_ts` and `end_ts` values — during which this instructor may be scheduled to teach. Either the owning instructor or an `AcademicAdmin` may later replace the entire `availability_windows` array.

`Student` rows are similarly simple, carrying only a public `display_name` and a unique contact `email`. A student row may be registered either by an `AcademicAdmin` or by the prospective student (self-registration).

A `Course` may organise its enrollments into one or more `ClassGroup`s. Either the owning instructor or an `AcademicAdmin` creates a class group with a human-readable `name` (for example, "Cohort-A"), a strictly positive `capacity`, and an optional `ta_instructor_id` that names the assigned teaching assistant. A `ClassGroup` carries a derived `enrolled_count` equal to the number of enrollments whose `class_group_id` matches this group and whose `learning_status` is anything other than `WITHDRAWN`. An attempt to assign an enrollment into a class group whose `enrolled_count` already equals its `capacity` fails with `ERR_CLASS_GROUP_FULL`.

A `Student` may enrol in a `PUBLISHED` course; the request body carries the `student_id` of the enrolling student. If the parent course is not in `PUBLISHED`, the request fails with `ERR_COURSE_NOT_PUBLISHED`; if the parent course is `FROZEN`, it fails with `ERR_COURSE_FROZEN`. On success, the system computes the `paid_amount_cents` from the course's catalogue inputs (see §3.6), records the moment of successful enrollment in `enrolled_at` as an ISO 8601 UTC timestamp (this is the anchor against which the time-based refund tier is later evaluated), initialises both axes of the enrollment status — `payment_status` to `PAID` and `learning_status` to `ACTIVE` — leaves `class_group_id` null until grouping, and appends an `AuditLogEntry` whose `action` is `ENROLLMENT_CREATED`. Either the course owner or an `AcademicAdmin` may subsequently move an enrollment into a class group by submitting an `enrollment_id`; this writes the `class_group_id` foreign key onto the enrollment and appends an `AuditLogEntry` whose `action` is `ENROLLMENT_GROUPED`.

Group-scoped communications are posted by an instructor or a teaching assistant as `Announcement` rows under a particular class group. Each announcement records the system-set `class_group_id`, the denormalised `course_id`, the `author_role` (one of `INSTRUCTOR` or `TEACHING_ASSISTANT`), the `author_id` of the posting instructor, and a non-empty `body` taken from the request payload. Posting an announcement also emits an external broadcast event for the integration with the IM subsystem; the event name is `im.message.broadcast`. Announcements are immutable once posted.

The full set of `Enrollment` fields combines the foreign keys (`course_id`, `student_id`, `class_group_id`), the dual-axis status (`payment_status`, `learning_status`), the price the student actually paid (`paid_amount_cents`), the `enrolled_at` anchor, the derived progress fields (`chapter_completion_percent`, `watch_duration_percent`, `progress_percent`, see §3.4), the derived `attendance_count`, and the `refund_amount_cents` field, which is null until a refund on this enrollment reaches `APPROVED` and afterwards equals the corresponding refund's `final_amount_cents`. The two axes are independent: `payment_status` ranges over `PAID`, `REFUND_PENDING`, `REFUNDED`, while `learning_status` ranges over `ACTIVE`, `AT_RISK`, `COMPLETED`, `WITHDRAWN`. A refund approval flips both axes (see §3.7).

### 3.3. Live Class Scheduling, Attendance, and Leave

Within a course, a `LiveClass` is the unit of synchronous instruction. The owning instructor schedules a live class by submitting an optional `chapter_id` (which may be null for general review sessions), the `instructor_id` of the teacher (usually the lead but possibly a substitute for makeup classes), a logical `room_id` shared across all courses on the platform, the inclusive `start_ts` and exclusive `end_ts` of the session in Unix seconds (where `end_ts` must be strictly greater than `start_ts`), and an optional `recording_playback_enabled` flag whose default is true. The newly created live class lands with `status = SCHEDULED`. The `original_live_class_id` field is null for primary classes; it is populated automatically when the row is created as a makeup (see below).

Two interval checks gate scheduling. The first is the room-overlap check, evaluated under half-open interval semantics with a ten-minute post-buffer. The candidate live class occupies the half-open interval that starts at its `start_ts` (inclusive) and ends at its `end_ts` (exclusive). Every existing live class on the same `room_id` whose `status` is either `SCHEDULED` or `LIVE` (regardless of which course owns it, because rooms are global) occupies an interval that starts at its own `start_ts` (inclusive) and ends ten minutes — that is, six hundred seconds — after its own `end_ts` (exclusive). The candidate conflicts with any of these occupied intervals if and only if the candidate's `start_ts` is strictly less than the occupied end and the candidate's `end_ts` is strictly greater than the occupied start; any such conflict is rejected with `ERR_ROOM_CONFLICT`. Concurrent creation calls targeting the same room with overlapping windows serialise to one survivor on the same overlap rule; the loser sees `ERR_ROOM_CONFLICT`.

The second is the instructor-availability check, evaluated under closed-interval containment with no buffer. The candidate is admitted if and only if the instructor's `availability_windows` array contains some window such that the window's `start_ts` is less than or equal to the candidate's `start_ts` and the candidate's `end_ts` is less than or equal to the window's `end_ts`. Both endpoints are inclusive — a candidate whose `end_ts` is exactly equal to a window's `end_ts` is allowed. Failure returns `ERR_INSTRUCTOR_UNAVAILABLE`.

Starting a live class advances `status` from `SCHEDULED` to `LIVE`. The transition requires the parent course's `posture` to be `OPEN` (otherwise `ERR_COURSE_FROZEN`), the call to be made by the live class's owning instructor (`ERR_FORBIDDEN_NOT_OWNER`), and the current `now_ts` to be no earlier than ten minutes before the class's `start_ts` — that is, `now_ts` must be at least `start_ts` minus six hundred seconds; an earlier attempt is rejected with `ERR_LIVE_CLASS_TOO_EARLY`. The transition generates a six-digit alphanumeric `checkin_code` and persists it on the row; the code is then required for any code-based check-in.

Ending a live class advances `status` from `LIVE` to `ENDED`; if the live class is not currently `LIVE`, the call fails with `ERR_LIVE_CLASS_NOT_LIVE`. The end transition has two side effects. First, every enrollment that has no `Attendance` row for this live class receives an autofilled `Attendance` row with `mark = ABSENT`. Second, when `recording_playback_enabled` is true, the chapter referenced by `chapter_id` gains a virtual playback record whose contribution is then included in the `watch_duration_percent` calculation; when it is false, no playback contribution is generated.

A live class can also be rescheduled while `SCHEDULED`. The reschedule call accepts a new `room_id`, `start_ts`, and `end_ts`; the new triple must pass both the room-overlap check and the instructor-availability check exactly as described above (failures return `ERR_ROOM_CONFLICT` and `ERR_INSTRUCTOR_UNAVAILABLE` respectively). The original row's `status` advances to `RESCHEDULED` and is retained for audit; a new `LiveClass` row — the makeup class — is created with the new triple, and its `original_live_class_id` is set to the original row's `id`. Calling reschedule on a class that is not `SCHEDULED` fails with `ERR_LIVE_CLASS_NOT_SCHEDULED`.

A live class can also reach `CANCELLED` from either `SCHEDULED` or `LIVE`, but only as the cascade side effect of a course delist; there is no direct cancel endpoint.

A `Student` records attendance for a live class by submitting a `checkin_method` (one of `TIME_WINDOW`, `CODE`, `FACE`, or `LEAVE`), the `checkin_ts` at which the check-in occurred (which is null only when the resulting mark would be `ABSENT` or `EXCUSED`), and an optional `code_provided` containing the raw code string when the method is `CODE`. The resulting `Attendance` row's `mark` is derived from the relationship between `checkin_ts` and the live class's `start_ts`. Let the difference, in seconds, between `checkin_ts` and `start_ts` be the check-in delta. If the delta is less than negative nine hundred — that is, the student is checking in more than fifteen minutes before the class starts — the check-in is rejected with `ERR_CHECKIN_WINDOW_CLOSED`. If the delta is less than or equal to zero (on time or early but within the fifteen-minute lead) the mark is `ATTENDED`. If the delta is strictly greater than zero and less than or equal to one thousand eight hundred — that is, between one and one thousand eight hundred seconds late, inclusive — the mark is `LATE`; the integer-second boundary at delta equal to one thousand eight hundred yields `LATE`, and delta equal to one thousand eight hundred and one yields `ERR_CHECKIN_WINDOW_CLOSED`. Any greater delta is rejected with `ERR_CHECKIN_WINDOW_CLOSED`; for those students, an `ABSENT` row is autofilled when the live class transitions to `ENDED`. A student check-in that races with the instructor's end-class call serialises on `LiveClass.status`: either an `Attendance` row is committed with mark `LATE` (or `ATTENDED`, if the delta places the student within the on-time window) before the end commits, or the end commits first and an `ABSENT` row is autofilled. Once the live class is `ENDED`, no new check-in is accepted — the late check-in attempt sees `ERR_LIVE_CLASS_NOT_LIVE`.

A `Student` who cannot attend a scheduled live class may file a `LeaveRequest` against the corresponding `enrollment_id` and `live_class_id` with a non-empty `reason`. The request lands in `status = PENDING`. A `TeachingAssistant` for that class group may approve the leave request: approval requires the request to still be `PENDING` (`ERR_LEAVE_NOT_PENDING`) and the target live class to still be `SCHEDULED` (`ERR_LIVE_CLASS_ALREADY_STARTED`); on success, the request advances to `APPROVED` and the system writes an `Attendance` row for the (`live_class_id`, `enrollment_id`) pair with `mark = EXCUSED` and `checkin_method = LEAVE`. The same teaching assistant may instead reject the leave request, advancing it to `REJECTED`; rejection also requires the request to still be `PENDING`. A `LeaveRequest`'s terminal states are `APPROVED` and `REJECTED`.

The derived `attendance_count` on an `Enrollment` is the number of `Attendance` rows that point to this enrollment whose `mark` is either `ATTENDED` or `LATE` — `EXCUSED` and `ABSENT` rows do not contribute.

### 3.4. Watch Sessions and the Two Progress Variants

A `Student` reports playback telemetry by creating a `WatchSession` against an enrolment, submitting the `chapter_id` watched and the `seconds_watched` for that session (which must be strictly greater than zero). `WatchSession` rows are append-only; the `enrollment_id` foreign key is filled by the server from the path parameter.

The system computes two independent progress numbers from the same telemetry — this is the dual-variant calculation that distinguishes the platform.

The first number, `chapter_completion_percent`, is the chapter-centric variant. The system collects the set of required chapters — those `Chapter` rows belonging to the enrolled course whose `required_for_completion` is true — and counts how many of them have been completed by this enrollment. A required chapter counts as completed when the sum of `seconds_watched` across all `WatchSession` rows for that enrollment and that chapter is at least equal to the chapter's `video_duration_seconds`. If the required-chapter set is empty, `chapter_completion_percent` is zero. Otherwise it is one hundred multiplied by the number of completed required chapters, divided by the total number of required chapters, rounded half-up to one decimal place.

The second number, `watch_duration_percent`, is the duration-centric variant. The system again restricts attention to required chapters. For each such chapter it computes the smaller of the chapter's total watched seconds and that chapter's `video_duration_seconds` — the cap prevents a learner from inflating their number by re-watching one chapter many times. The system then sums those capped values across all required chapters and divides by the sum of `video_duration_seconds` over the same set; if that sum is zero, `watch_duration_percent` is zero. Otherwise the ratio is multiplied by one hundred and rounded half-up to one decimal place.

The two variants can legitimately disagree on the same telemetry: a learner who has watched ninety-nine percent of one required chapter and zero of another will see a `chapter_completion_percent` of zero and a `watch_duration_percent` of roughly forty-nine point five. The single combined `progress_percent` exposed on the enrollment is the larger of the two; ties resolve to `chapter_completion_percent`.

These three numbers are recomputed whenever a `WatchSession` is created, whenever a `Submission` reaches `GRADED`, and whenever an enrollment is read. Every such recomputation runs in this fixed order: first `chapter_completion_percent`, then `watch_duration_percent`, then `progress_percent` from the maximum-with-tiebreak. Only after all three have been updated does the at-risk evaluation in §3.5 run.

### 3.5. The At-Risk Alert and Learning Status Flips

After progress is recomputed, the system evaluates whether the enrollment should flip its `learning_status` between `ACTIVE` and `AT_RISK`. Three thresholds drive this evaluation: a progress threshold of thirty percent, an attendance threshold of seventy percent, and a tenure threshold of fourteen days. The evaluation runs whenever progress changes (a new `WatchSession`, a `Submission` reaching `GRADED`), whenever an `Attendance` row is appended, and whenever the test-driving clock advances.

The number of days since enrolment is the floor of (`now_ts` minus `enrolled_at` expressed in seconds) divided by eighty-six thousand four hundred. The attendance rate is the count of `Attendance` rows for this enrollment whose `mark` is `ATTENDED` or `LATE`, divided by the count of `LiveClass` rows of the same course whose `status` is `LIVE` or `ENDED` and whose `start_ts` is at most `now_ts`; if that denominator is zero the rate is taken to be one. A floating-point risk score is then computed as zero point six multiplied by the difference between the progress threshold and the current `progress_percent`, plus zero point four multiplied by the difference between the attendance threshold and one hundred times the attendance rate. Boundaries are exact: the comparisons are strict, so a value exactly equal to a threshold does not satisfy a strict inequality.

`learning_status` flips from `ACTIVE` to `AT_RISK` if and only if the days-since-enrolment is at least fourteen and either the current `progress_percent` is strictly less than thirty percent or the risk score is strictly greater than zero. It flips back from `AT_RISK` to `ACTIVE` if and only if `progress_percent` is at least thirty percent and the risk score is at most zero. The transition is a system action and is also reachable via a privileged sweep capability that an `AcademicAdmin` may invoke to force the at-risk evaluation across all enrolments.

When all chapters with `required_for_completion` set to true have a completion mark for an enrollment, the system flips `learning_status` from `ACTIVE` to `COMPLETED` and emits an external `certificate.issued` event, recorded in `AuditLogEntry` for traceability.

### 3.6. Catalogue Pricing at Enrolment Time

When a `Student` enrols in a course, the system computes `paid_amount_cents` from three inputs that interact non-linearly: the course's `list_price_cents`, the course's `discount_percent`, and the course's `status`. If the course's `status` is anything other than `PUBLISHED`, the request is rejected with `ERR_COURSE_NOT_PUBLISHED`. Otherwise the effective discount percentage is the supplied `discount_percent` clamped to lie between zero and eighty inclusive — values below zero become zero, values above eighty become eighty. The raw cent amount is `list_price_cents` multiplied by (one hundred minus the effective percentage), divided by one hundred. The result is rounded half-up to the nearest integer cent and stored as the enrolment's `paid_amount_cents`.

### 3.7. Refunds: Provisional at Request, Final at Approval

A `Student` who has paid for an enrolment may file a `RefundRequest` against it. The request body may carry an optional `materials_kit_count` defaulting to zero, capturing the number of physical material kits the student has already received. The transition requires that the caller owns the enrolment (`ERR_FORBIDDEN_NOT_OWNER`) and that the enrolment's `payment_status` is currently `PAID` (`ERR_REFUND_ALREADY_REQUESTED`). The system serialises concurrent refund requests on the same enrolment so that at most one non-terminal `RefundRequest` exists at a time; the second-arriving request sees `ERR_REFUND_ALREADY_REQUESTED`.

On creation, the refund request is born `PENDING`. The system sets `requested_at` to the current `now_ts` (this is the time anchor for the time-window in the provisional calculation), denormalises the `course_id`, snapshots `Enrollment.progress_percent` into `provisional_progress_percent` rounded half-up to one decimal, computes `provisional_amount_cents` via the provisional refund calculation described below, flips the enrolment's `payment_status` from `PAID` to `REFUND_PENDING`, and appends an `AuditLogEntry` whose `action` is `REFUND_REQUESTED`.

The provisional refund calculation is forward-looking: it locks in the student's circumstances at the moment of request. Let `paid` be the `paid_amount_cents` of the enrolment. Let `progress` be the enrolment's `progress_percent` snapshot at `requested_at`. Let `days_elapsed` be the floor of (`requested_at` minus `enrolled_at`, expressed in seconds) divided by eighty-six thousand four hundred — this converts the elapsed wall-clock to whole days. Let `attended_count` be the number of `Attendance` rows for this enrolment whose `mark` is `ATTENDED` or `LATE` as of `requested_at`. Let `kits` be the supplied `materials_kit_count`.

The refund ratio is determined by walking the following tiered table top-to-bottom and stopping at the first match. If `days_elapsed` is at most seven and `progress` is at most five percent, the ratio is one (full refund). Otherwise, if `days_elapsed` is at most thirty and `progress` is at most thirty percent, the ratio is zero point seven. Otherwise, if `progress` is at most sixty percent, the ratio is zero point three. Otherwise, the ratio is zero. The gross refund in cents is `paid` multiplied by this ratio, rounded half-up to the nearest integer cent (this rounding is applied before any deductions). The materials deduction is `kits` multiplied by five thousand cents — that is, fifty dollars per kit. The services deduction is `attended_count` multiplied by one thousand five hundred cents — that is, fifteen dollars per attended live class. The provisional amount is the gross minus both deductions, with a floor of zero (the system never produces a negative refund).

An `AcademicAdmin` then resolves the pending refund. Approval transitions the request from `PENDING` to `APPROVED`. Approval requires the request to still be `PENDING` (`ERR_REFUND_NOT_PENDING`) and the parent course's `posture` to be `RESTRICTED` or `OPEN` (`ERR_COURSE_FROZEN` if the course has been frozen by a delist in the interim). On approval, the system runs the final refund calculation: the same tier table, the same constants, the same rounding order, but with the inputs re-snapshotted at approval time. Specifically, `progress` is the enrolment's current `progress_percent` at approval time (not at `requested_at`); `days_elapsed` is recomputed against the approval timestamp; and `attended_count` is the count of attendance rows whose `created_at` is at or before the approval timestamp. The result is written to `final_amount_cents`, and the enrolment's `refund_amount_cents` is set to that same value. The enrolment's `payment_status` flips from `REFUND_PENDING` to `REFUNDED`, the enrolment's `learning_status` flips to `WITHDRAWN`, an external `payment.refund.requested` event is emitted, and an `AuditLogEntry` whose `action` is `REFUND_APPROVED` is appended. Because the inputs are re-snapshotted, the final amount may legitimately differ from the provisional amount even when the formula and constants are identical: if a learner watched another lecture or attended another live class between request and approval, both `progress` and `attended_count` will have moved. For data that has not changed between the two moments, the two amounts must agree, but the system always recomputes.

Rejection by an `AcademicAdmin` instead transitions the request to `REJECTED`. Rejection requires the request to still be `PENDING` (`ERR_REFUND_NOT_PENDING`) and the body to carry a non-empty `rejection_reason` (`ERR_REFUND_REJECTION_REASON_REQUIRED`). The enrolment's `payment_status` reverts from `REFUND_PENDING` back to `PAID`, and an `AuditLogEntry` whose `action` is `REFUND_REJECTED` is appended. Concurrent approve and reject calls on the same `PENDING` request serialise on `RefundRequest.status`: exactly one transition wins; the other sees `ERR_REFUND_NOT_PENDING`.

### 3.8. Assignments and the Cyclic Submission Loop

An `Instructor` publishes an `Assignment` under a course by submitting an optional `chapter_id` (which may be null for course-wide assignments), a `title`, a `format` (one of `TEXT`, `FILE`, or `CODE`), a `due_ts` in Unix seconds, and a strictly positive `max_score`. A newly published assignment lands with `status = PUBLISHED`; assignments may also exist in `DRAFT` and `CLOSED` over their lifetime.

A `Student` submits to an assignment by creating a `Submission` with the owning `enrollment_id` (the assignment is identified through the path, and the submission internally records that target as `assignment_id`) and the appropriate payload field for the assignment's `format`. When `format` is `TEXT` the body must contain `payload_text` and the other two payload fields must be null; when `format` is `FILE` the body must contain `payload_file_url`; when `format` is `CODE` the body must contain `payload_code`. A mismatch — wrong field set, missing field, or multiple payload fields populated simultaneously — is rejected with `ERR_PAYLOAD_FORMAT_MISMATCH`. The submission must arrive strictly before the assignment's `due_ts`; an attempt at or after the due time is rejected with `ERR_SUBMISSION_PAST_DUE`. On success, the submission lands with `status = SUBMITTED` and `revision_count = 0`, and the system computes a `plagiarism_score` (a number between zero and one inclusive) against the new payload.

Either the course owner or the relevant teaching assistant (the instructor whose `id` equals the `ta_instructor_id` of the relevant class group) may move a submission from `SUBMITTED` to `UNDER_REVIEW` to begin grading; the source state is required to be `SUBMITTED` (`ERR_SUBMISSION_NOT_SUBMITTED`). From `UNDER_REVIEW`, the same actor has two ways to leave the review state.

The first is to request a revision, which transitions `UNDER_REVIEW` back into `REVISION_REQUESTED`. Requesting a revision requires the submission to still be `UNDER_REVIEW` (`ERR_SUBMISSION_NOT_UNDER_REVIEW`), a non-empty `feedback` body (`ERR_FEEDBACK_REQUIRED`), and a current `revision_count` strictly less than the revision cap of three (`ERR_REVISION_CAP_REACHED` — the cap is reached when `revision_count` equals three). Requesting a revision delivers the feedback to the student, recorded as an external `im.message.send` event.

After receiving a revision request, the student resubmits by replacing the submission's payload. The transition is from `REVISION_REQUESTED` back to `SUBMITTED` and is gated by three preconditions: the submission must currently be `REVISION_REQUESTED` (`ERR_SUBMISSION_NOT_AWAITING_REVISION`), the caller must own the underlying enrolment (`ERR_FORBIDDEN_NOT_OWNER`), and the new payload must again pass the `format`-match check (`ERR_PAYLOAD_FORMAT_MISMATCH`) and the `due_ts` deadline (`ERR_SUBMISSION_PAST_DUE`). On success, `revision_count` increments by one and `plagiarism_score` is recomputed against the new payload. This closes the cyclic loop `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED`, which can iterate up to three times before the cap is reached.

The second exit from `UNDER_REVIEW` is the terminal grade transition. Grading is restricted to the course owner (a teaching assistant cannot grade, only request a revision), advances the submission to `GRADED`, and is gated by four preconditions: the submission must still be `UNDER_REVIEW` (`ERR_SUBMISSION_NOT_UNDER_REVIEW`); the supplied `score` must lie within the closed range from zero to the assignment's `max_score` (`ERR_SCORE_OUT_OF_RANGE`); a non-empty `feedback` must be supplied (`ERR_FEEDBACK_REQUIRED`); and the `plagiarism_score` must be strictly less than the system's plagiarism block threshold unless the request body sets the `override_plagiarism` flag to true (`ERR_PLAGIARISM_BLOCKED`). On success, the system recomputes the enrolment's progress as in §3.4 (a graded submission contributes to milestone-checking through quiz-score aggregation), which may in turn flip the enrolment's `learning_status`. Two concurrent grade calls on the same submission serialise on the submission's status: the first wins, the second sees `ERR_SUBMISSION_NOT_UNDER_REVIEW`.

### 3.9. Listings, Audit Retrieval, and the Test-Driving Capability

Public listings of `Course`, `SyllabusRevision`, and `Chapter` are open to any caller and follow the §2.3 pagination contract. Course listing accepts an optional `status` filter; chapter listing is parent-scoped under the course id in the path. An `AcademicAdmin` may list `RefundRequest` rows, with optional filters by `status` and `enrollment_id`, and may list `AuditLogEntry` rows, with optional filters by `subject_type`, `subject_id`, and `action`.

An `AcademicAdmin` can also drive system time forward via a privileged test-driving capability that accepts a body containing a single `seconds` increment; the call atomically advances the singleton `Clock`'s `now_ts` and re-evaluates the at-risk alert across all enrolments. A second privileged capability forces the at-risk evaluation to run without advancing the clock; it has no body and produces `learning_status` flips for any enrolments whose evaluation has gone stale.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including state transitions on existing rows, replacements of nested arrays, and approvals or rejections of pending workflows — return `200 OK`. Where an endpoint creates a fresh row as a side effect of acting on an existing one (for example, the leave-approval endpoint that materialises an `Attendance` row), the status code follows the primary resource being acted upon, not the side-effect row.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/courses` | Create a course in DRAFT | Instructor |
| GET    | `/courses` | List courses with optional status filter | Any |
| GET    | `/courses/{courseId}` | Get a specific course | Any |
| PATCH  | `/courses/{courseId}` | Update title or pricing while DRAFT or REJECTED | Instructor |
| POST   | `/courses/{courseId}/submit-for-review` | Move a course from DRAFT to UNDER_REVIEW | Instructor |
| POST   | `/courses/{courseId}/approve` | Move a course from UNDER_REVIEW to PUBLISHED | AcademicAdmin |
| POST   | `/courses/{courseId}/reject` | Move a course from UNDER_REVIEW to REJECTED | AcademicAdmin |
| POST   | `/courses/{courseId}/return-to-draft` | Move a course from REJECTED back to DRAFT | Instructor |
| POST   | `/courses/{courseId}/delist` | Move a course from PUBLISHED to DELISTED with depth-3 cascade | AcademicAdmin |
| GET    | `/courses/{courseId}/syllabus-revisions` | List syllabus revisions for a course | Any |
| POST   | `/courses/{courseId}/chapters` | Add a chapter to a DRAFT or REJECTED course | Instructor |
| GET    | `/courses/{courseId}/chapters` | List chapters of a course | Any |
| POST   | `/instructors` | Register an instructor | AcademicAdmin |
| GET    | `/instructors/{instructorId}` | Get an instructor profile | Any |
| PATCH  | `/instructors/{instructorId}/availability` | Replace an instructor's availability windows | Instructor, AcademicAdmin |
| POST   | `/students` | Register a student | AcademicAdmin, Student |
| POST   | `/courses/{courseId}/enrollments` | Enrol a student in a PUBLISHED course | Student |
| GET    | `/enrollments/{enrollmentId}` | Get an enrollment including derived progress | Student, Instructor, TeachingAssistant, AcademicAdmin |
| POST   | `/courses/{courseId}/class-groups` | Create a class group under a course | Instructor, AcademicAdmin |
| POST   | `/class-groups/{classGroupId}/assign-enrollment` | Move an enrollment into a class group | Instructor, AcademicAdmin |
| POST   | `/class-groups/{classGroupId}/announcements` | Post an announcement to a class group | Instructor, TeachingAssistant |
| POST   | `/courses/{courseId}/live-classes` | Schedule a live class for a course | Instructor |
| POST   | `/live-classes/{liveClassId}/start` | Move a live class from SCHEDULED to LIVE | Instructor |
| POST   | `/live-classes/{liveClassId}/end` | Move a live class from LIVE to ENDED | Instructor |
| POST   | `/live-classes/{liveClassId}/reschedule` | Reschedule a SCHEDULED live class, creating a makeup row | Instructor |
| POST   | `/live-classes/{liveClassId}/check-in` | Record a student check-in and derive its attendance mark | Student |
| POST   | `/leave-requests` | File a leave request against a scheduled live class | Student |
| POST   | `/leave-requests/{leaveRequestId}/approve` | Approve a pending leave request | TeachingAssistant |
| POST   | `/leave-requests/{leaveRequestId}/reject` | Reject a pending leave request | TeachingAssistant |
| POST   | `/courses/{courseId}/assignments` | Publish an assignment for a course | Instructor |
| POST   | `/assignments/{assignmentId}/submissions` | Create a submission for an assignment | Student |
| PUT    | `/submissions/{submissionId}/payload` | Resubmit after a revision request | Student |
| POST   | `/submissions/{submissionId}/start-review` | Move a submission from SUBMITTED to UNDER_REVIEW | Instructor, TeachingAssistant |
| POST   | `/submissions/{submissionId}/request-revision` | Move a submission from UNDER_REVIEW to REVISION_REQUESTED | Instructor, TeachingAssistant |
| POST   | `/submissions/{submissionId}/grade` | Move a submission from UNDER_REVIEW to GRADED | Instructor |
| POST   | `/enrollments/{enrollmentId}/watch-sessions` | Log a watch session for an enrollment | Student |
| POST   | `/enrollments/{enrollmentId}/refund-requests` | File a refund request against an enrollment | Student |
| POST   | `/refund-requests/{refundRequestId}/approve` | Approve a pending refund request | AcademicAdmin |
| POST   | `/refund-requests/{refundRequestId}/reject` | Reject a pending refund request | AcademicAdmin |
| GET    | `/refund-requests` | List refund requests with optional filters | AcademicAdmin |
| GET    | `/audit-logs` | List audit log entries with optional filters | AcademicAdmin |
| POST   | `/_clock/advance` | Advance the logical clock and re-run at-risk evaluation | AcademicAdmin |
| POST   | `/_sweep/at-risk` | Force the at-risk evaluation to run | AcademicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_COURSE_NOT_FOUND` | 404 |
| `ERR_CHAPTER_NOT_FOUND` | 404 |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_LIVE_CLASS_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_REFUND_NOT_FOUND` | 404 |
| `ERR_LEAVE_NOT_FOUND` | 404 |
| `ERR_CLASS_GROUP_NOT_FOUND` | 404 |
| `ERR_COURSE_NO_CHAPTERS` | 409 |
| `ERR_COURSE_NOT_UNDER_REVIEW` | 409 |
| `ERR_COURSE_NOT_REJECTED` | 409 |
| `ERR_COURSE_NOT_PUBLISHED` | 409 |
| `ERR_COURSE_FROZEN` | 409 |
| `ERR_INVALID_PRICING` | 400 |
| `ERR_LIVE_CLASS_NOT_LIVE` | 409 |
| `ERR_LIVE_CLASS_NOT_SCHEDULED` | 409 |
| `ERR_LIVE_CLASS_TOO_EARLY` | 409 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_INSTRUCTOR_UNAVAILABLE` | 409 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 |
| `ERR_LEAVE_NOT_PENDING` | 409 |
| `ERR_LIVE_CLASS_ALREADY_STARTED` | 409 |
| `ERR_SUBMISSION_NOT_SUBMITTED` | 409 |
| `ERR_SUBMISSION_NOT_UNDER_REVIEW` | 409 |
| `ERR_SUBMISSION_NOT_AWAITING_REVISION` | 409 |
| `ERR_REVISION_CAP_REACHED` | 409 |
| `ERR_PAYLOAD_FORMAT_MISMATCH` | 400 |
| `ERR_SUBMISSION_PAST_DUE` | 409 |
| `ERR_SCORE_OUT_OF_RANGE` | 400 |
| `ERR_FEEDBACK_REQUIRED` | 400 |
| `ERR_PLAGIARISM_BLOCKED` | 403 |
| `ERR_REFUND_ALREADY_REQUESTED` | 409 |
| `ERR_REFUND_NOT_PENDING` | 409 |
| `ERR_REFUND_REJECTION_REASON_REQUIRED` | 400 |
| `ERR_CLASS_GROUP_FULL` | 409 |
| `ERR_STALE_DATA` | 409 |
