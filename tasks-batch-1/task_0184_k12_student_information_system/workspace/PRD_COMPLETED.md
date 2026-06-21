# K-12 Student Information System API — Product Requirements Document

## 1. Introduction

This document specifies the K-12 Student Information System (SIS) API, the system of record a district uses to operate a school from the day a student's demographic record is created through the moment that student's membership and attendance are rolled up into the funding figures the district reports to its state. The platform unifies several historically siloed workflows — enrollment and demographics, period and daily attendance, a standards-based gradebook, discipline referral and adjudication, report cards and transcripts, master scheduling, Average Daily Attendance (ADA) funding reports, and a read-only parent portal — behind a single, consistent contract.

The system's hardest problems are reconciliation problems. A single discipline consequence can ripple through period attendance, then daily attendance, then an enrollment's count of present days, and finally the dollar-equivalent ADA a school earns; the API must keep all of those derived values exactly consistent at every step, and must be able to walk every one of those effects back if the consequence is later rescinded or its parent incident dismissed. Funding itself comes in two mutually exclusive flavors — one that pays on membership regardless of attendance, one that pays only on days a student was actually present — and the same roster can yield different totals depending on which flavor a school reports under. Layered on top of all of this is a deliberate **segregation of duties**: the teacher who refers an incident may not adjudicate it, and the officer who drafts a funding report may not certify it.

The requirements below are written for the engineers who will build the service. Section 2 fixes the system-wide contract — authentication, the response envelope, pagination, concurrency, and the cross-cutting rules that govern consistency and funding. Section 3 narrates the business workflows in the order a school actually lives them. Sections 4 and 5 enumerate the endpoints and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. The system recognizes exactly five roles: `Registrar`, `Teacher`, `Administrator`, `StateReportingOfficer`, and `Parent`. If either header is absent, or if `X-User-Role` is not one of these five known role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

All five roles are operator identities rather than persisted entities. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque staff identifier not tied to any stored record; the server may record it on the resources a registrar touches but never compares it to any entity's `id`. The same holds for `Teacher`: the value is an opaque staff identifier, and the server records it — for example, as the `teacher_user_id` of a section a teacher is assigned to, or as the `referring_user_id` a transition writes onto an incident — without ever treating it as an entity primary key. Likewise for `Administrator`, whose `X-User-ID` the server pins onto an incident as its `adjudicator_user_id` when that administrator opens review, and onto a consequence's lineage, but never resolves to a stored row. For `StateReportingOfficer`, `X-User-ID` is again an opaque identifier; the server records it as the `drafter_user_id` or `certifier_user_id` of a funding report where the relevant transition writes it, but does not compare it to any entity's `id`. Finally, when `X-User-Role` is `Parent`, `X-User-ID` is an opaque guardian identifier; rather than being matched against an entity `id`, it is checked for membership in the targeted student's guardian set (see §2.4). A parent acting through the portal who is not a linked guardian of the targeted student is rejected with `ERR_NOT_GUARDIAN_OF_STUDENT`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100 — an out-of-range value is silently clamped into that range (a `limit` below 1 becomes 1, above 100 becomes 100) rather than rejected. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0; a negative `offset` is likewise clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp, `created_at`, in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Identity, Ownership, and the Parent Portal Guardian Check

Most write operations in this system are performed by staff whose `X-User-ID` is opaque, but two checks compare an acting identity against a value recorded on a resource rather than against an entity `id`. The first is the discipline segregation of duties (§2.10). The second is the parent-portal guardian check. A registrar links a guardian to a student by supplying a `guardian_user_id`, which is added to that student's guardian set; that set is surfaced on the student record as a `guardian_user_ids` array of the linked identifiers. Thereafter, when a `Parent` reads any resource scoped to a child — the portal summary, the student record, the child's daily attendance, report cards, or discipline incidents — the server confirms that the caller's `X-User-ID` is present in the targeted student's guardian set before returning data. A parent whose identifier is not in that set receives `ERR_NOT_GUARDIAN_OF_STUDENT`. This guardian check is evaluated after authentication and role authorization but is itself an authorization concern; it is the reason a `Parent` is strictly read-only and confined to their own child.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource by an `id` embedded in the path, and some carry additional resource identifiers in the request body. All such identifiers are resolved left-to-right, path before body, before any business rule runs. A path-embedded id is resolved before the request body is even parsed, so a non-existent path resource surfaces its not-found error ahead of any body complaint; a body-embedded id, however, is resolved only after that body has been shape-validated, so a malformed, missing, mistyped, or out-of-enum body field surfaces `ERR_INVALID_REQUEST` before the body's own referenced ids are looked up. The first identifier that fails to resolve produces that resource's specific not-found error — `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_SCHEDULE_ASSIGNMENT_NOT_FOUND`, `ERR_ATTENDANCE_RECORD_NOT_FOUND`, `ERR_STANDARD_SCORE_NOT_FOUND`, `ERR_REPORT_CARD_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CONSEQUENCE_NOT_FOUND`, or `ERR_ADA_REPORT_NOT_FOUND` — each returned with HTTP 404. For example, posting a consequence under an incident that does not exist surfaces `ERR_INCIDENT_NOT_FOUND` before the body's consequence fields are examined. Malformed bodies, missing required fields, type mismatches, and unrecognized enum values are reported as `ERR_INVALID_REQUEST` with HTTP 400.

### 2.6. Common Resource Properties

Every entity in the system — School, Student, Enrollment, Course, Section, ScheduleAssignment, AttendanceRecord, DailyAttendance, StandardScore, ReportCard, DisciplineIncident, DisciplineConsequence, and AdaFundingReport — carries a system-managed `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Every one of these entities additionally carries an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on each mutation. There are no immutable, version-less entities in this system; whenever any field of a resource changes — including a derived field such as an enrollment's `present_days` or a section's `enrolled_count` — that change is a mutation that refreshes `updated_at` and increments `version`.

### 2.7. Hierarchical Consistency and Derived-Field Reconciliation

A defining characteristic of this system is that several fields are never written directly by a client but are derived and kept continuously reconciled with the records beneath them. An enrollment's `membership_days` and `present_days`, a section's `enrolled_count`, an attendance record's `present_minutes`, a daily-attendance row's `present_minutes_total`, `daily_code`, and `ada_eligible`, a report card's `overall_gpa`, `credits_earned`, and `line_items`, and a funding report's `total_ada`, `funded_enrollment_count`, and `method_used` are all of this derived character. Whenever an event changes the underlying records — a posted or corrected attendance code, a suspension cascade, a rescind, a withdrawal, a schedule drop — the server recomputes the affected derived fields immediately and in the same transaction, and each such recompute that lands on a parent resource is itself a mutation that refreshes that parent's `updated_at` and increments its `version`. The system never returns a stale derived value: a draft report card and a draft funding report compute their preview on read, while a finalized report card and a certified funding report return the values frozen at the moment of finalization or certification.

### 2.8. Precision and Rounding

ADA figures are the most precision-sensitive values in the system. Each per-enrollment ADA contribution is rounded half-up to four decimal places, and the report's `total_ada` is the sum of those already-rounded per-enrollment values, itself rounded half-up to four decimal places — the round-then-sum order is fixed and must not be reordered into a sum-then-round. Grade computations round half-up to two decimal places: a section's weighted mastery or weighted percentage (`mastery_or_percent`) is rounded to two decimals, and a report card's `overall_gpa` is rounded half-up to two decimals. Grade points are exact values drawn from the set 0.0, 1.0, 2.0, 3.0, and 4.0. Attendance minute quantities and all counts (membership days, present days, enrolled counts) are exact integers.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Finalizing a report card requires the request to carry `expected_report_card_version`, and certifying an ADA funding report requires the request to carry `expected_report_version`; in both cases the field is mandatory and carries the client's last observed `version` of the parent resource. This check runs early — after authentication and role authorization, before the transition's own business preconditions.

A report card's `version` advances whenever a standards score is upserted against any of the enrollment's sections, because that upsert reconciles the report card's derived grades. If a finalize arrives carrying an `expected_report_card_version` that no longer matches the report card's current `version`, the finalize is rejected with `ERR_STALE_VERSION` and HTTP 412 — this prevents a client from freezing `line_items` over grades it never observed. Symmetrically, a draft funding report's `version` advances each time it is recomputed against current attendance and membership; if a certify arrives carrying an `expected_report_version` that no longer matches the report's current `version`, the certify is rejected with `ERR_STALE_VERSION` and HTTP 412, preventing the officer from locking in superseded ADA totals. No other endpoint accepts or requires a version field.

### 2.10. Segregation of Duties

Two distinct workflows enforce that the person who initiates an action cannot also be the person who passes judgment on it, with the relevant identity compared against a value the system recorded earlier. In discipline, the staff member who files a referral has their `X-User-ID` stored as the incident's `referring_user_id`; the administrator who opens review or who dismisses an incident must present a different `X-User-ID`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. In state reporting, the staff member who drafts a funding report has their `X-User-ID` stored as the report's `drafter_user_id`; the officer who certifies or rejects that report must present a different `X-User-ID`, and a match is again rejected with `ERR_SEGREGATION_OF_DUTIES`. Both rejections carry HTTP 403.

### 2.11. The Deterministic School-Day Clock

The system does not read wall-clock time to decide what school day it is. Each school maintains a deterministic `current_school_day_index`, an integer that starts at 0 (meaning before the session has begun) and advances only when a registrar explicitly advances the clock. Every day-indexed operation — enrollment entry and exit, attendance posting, incident dates, suspension spans, and funding snapshots — is expressed in terms of these indices rather than against a calendar. Where a workflow in §3 names a clock-relative bound it is validated against the school's current clock value — specifically the withdrawal `exit_day_index` (which may not exceed the clock, per §3.3) and the attendance `day_index` window (per §3.5); every other day-indexed input, including an enrollment's `entry_day_index`, an incident's `incident_day_index`, a suspension's `start_day_index`, and a funding report's `as_of_day_index`, is recorded as supplied without an additional clock-range check at the time it is written. This makes the entire system reproducible: the same sequence of writes always yields the same membership, attendance, and funding figures.

### 2.12. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Header validity is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`), then left-to-right resolution of every referenced resource id (the relevant not-found error). For parent-portal reads, the guardian-ownership check (`ERR_NOT_GUARDIAN_OF_STUDENT`) follows. Next, on the two OCC-guarded transitions, the version match is checked (`ERR_STALE_VERSION`) before any state precondition. Then the target resource's state is checked for whether it permits the requested transition (the relevant state error, such as `ERR_ENROLLMENT_NOT_ACTIVE` or `ERR_INCIDENT_NOT_UNDER_REVIEW`). Only after all of these do the domain-specific business-safety, temporal, and constraint checks run — segregation of duties, the suspension cap, schedule conflicts, attendance windows, capacity, grade input, and parent-active referential checks. Within that final tier, each rule is described alongside the workflow it guards in §3.

## 3. Business Logic & Workflows

### 3.1. Establishing a School and Its Funding Posture

Everything in the system hangs off a **School**, created by a registrar with a `name` and a conventionally two-letter `state_code` (both required non-empty strings, recorded verbatim — the `state_code` length is not enforced, so any non-empty string is accepted). At creation a school also fixes its funding posture. The `ada_method` chooses between the two funding flavors and defaults to `AGGREGATE_MEMBERSHIP`; the only other accepted value is `DAYS_PRESENT`. The `minimum_daily_minutes` value — defaulting to 240 — is the instructional-minute floor a student must reach to have a day counted as present under the `DAYS_PRESENT` flavor. The `session_total_days` value, defaulting to 180, is the number of scheduled instructional days in the reporting session and serves as the denominator for every ADA calculation. A freshly created school always begins with its `current_school_day_index` at 0.

Because the system runs on the deterministic clock described in §2.11, time only moves when a registrar advances it. Advancing the clock takes a `by_days` increment, which must be between 1 and 10000 inclusive, and adds that amount to the school's `current_school_day_index`. This is a registrar-only capability and the single mechanism by which the session progresses.

### 3.2. Students, Guardians, and the Demographic Lifecycle

A **Student** is a demographic record created by a registrar under a `school_id`, carrying a statewide unique `state_student_id`, the legal `first_name` and `last_name`, a `grade_level` drawn from the set `K`, `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`, `10`, `11`, and `12`, and a `birth_date` conventionally given as an ISO `YYYY-MM-DD` date (it is required as a non-empty string and recorded verbatim — the date format itself is not validated). The `state_student_id` must be unique within the school; a collision is rejected with `ERR_DUPLICATE_STATE_STUDENT_ID`. The created student record echoes its `guardian_user_ids` as an array, empty until a guardian is linked. A new student begins life in `PROSPECTIVE` status. The `status` field tracks the demographic lifecycle and moves to `ENROLLED` once the student has an active enrollment, and to `WITHDRAWN` once the student no longer has any active enrollment.

To grant a guardian access to the parent portal, a registrar links a `guardian_user_id` to the student, adding that opaque identifier to the student's guardian set; the link endpoint responds `201 Created` and returns the updated student record (with the identifier now present in its `guardian_user_ids`). This is the value the portal's ownership check (§2.4) consults. Beyond the dedicated portal summary, a parent may also read their own child's student record, daily attendance, report cards, and discipline incidents — always subject to the guardian check. The portal summary itself gathers, for one child, the demographics, current grades, attendance present-day count, and any open incidents into a single read: the response is the full student record extended with three additional fields — a `present_days` integer (the sum of `present_days` across the student's enrollments), a `current_grades` array carrying one entry per enrollment shaped `{enrollment_id, overall_gpa, credits_earned, line_items}` computed live as a draft preview, and an `open_incidents` array of the student's discipline incidents currently in `REFERRED` or `UNDER_REVIEW` status, ordered by `created_at` ascending.

### 3.3. Enrollment and Membership Windows

A registrar enrolls a student by creating an **Enrollment** with a `student_id` and an `entry_day_index` — the school-day index, inclusive, on which membership begins — plus an optional `fte` that defaults to 1.0 and must be greater than 0 and at most 1.0 — a value outside that open-lower, closed-upper range is rejected with `ERR_INVALID_REQUEST` — and is conventionally expressed to two decimals (for example, 0.5 for a half-day kindergartener), though the number of decimal places is not itself validated and the value is stored as supplied. On creation the enrollment copies its `school_id` from the student, starts in `ACTIVE` status, drives the student's `status` to `ENROLLED`, and initializes both `membership_days` and `present_days` to 0. The `exit_day_index` is null while the enrollment remains `ACTIVE`.

An enrollment ends in one of two ways. When a registrar **withdraws** an active enrollment, the body carries the `exit_day_index` at which membership ends, treated exclusively. The withdrawal is only permitted while the enrollment is `ACTIVE`; otherwise it is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The supplied `exit_day_index` must be at least the `entry_day_index` — a smaller value yields `ERR_INVALID_EXIT_DAY` — and must not be in the future relative to the school's `current_school_day_index`; a larger value yields `ERR_EXIT_DAY_IN_FUTURE`. On a valid withdrawal the enrollment moves `ACTIVE → WITHDRAWN`, its `exit_day_index` is set from the body, and `membership_days` is recomputed as the number of session day indices d satisfying `entry_day_index` ≤ d < `exit_day_index` (because exit is exclusive, a student present through day 9 and withdrawn effective day 10 counts the days strictly below 10). Every schedule assignment of this enrollment still in `ENROLLED` status is moved to `DROPPED`, and each affected section's `enrolled_count` is decremented by one. If the student has no other active enrollment, the student's `status` becomes `WITHDRAWN`.

The second exit path is **mark-no-show**, also registrar-only and also permitted only while the enrollment is `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`). A no-show may only be declared when no attendance record with code `PRESENT` exists for the enrollment; if any present record is on file, the request is rejected with `ERR_PRESENCE_ON_RECORD`. A successful no-show moves the enrollment `ACTIVE → NO_SHOW`, sets `membership_days` and `present_days` both to 0, sets `exit_day_index` equal to `entry_day_index`, drops every `ENROLLED` schedule assignment to `DROPPED` while decrementing each section's `enrolled_count` by one, and — if the student has no other active enrollment — drives the student's `status` to `WITHDRAWN`. Both `WITHDRAWN` and `NO_SHOW` are terminal enrollment states.

### 3.4. Courses, Sections, and the Master Schedule

A registrar defines a **Course** under a `school_id` with a `course_code` that must be unique within the school — a duplicate is rejected with `ERR_DUPLICATE_COURSE_CODE` — a `title`, an optional `credit_value` that defaults to 1.0 and represents the credits a passing student earns toward the transcript, and an optional `grading_mode` that defaults to `STANDARDS`. The grading mode is the pivot for how the course is graded: `STANDARDS` grades on mastery levels, while `TRADITIONAL` grades on a weighted percentage.

From a course a registrar opens a **Section**, supplying the `course_id`, the assigned teacher's opaque `teacher_user_id`, the `period` (an integer from 1 through 8 inclusive naming the daily slot the section meets in), an optional `meeting_minutes` defaulting to 50 (the instructional minutes the section contributes on each meeting day), and an optional `capacity` defaulting to 30. The section copies its `school_id` from the course, starts `OPEN` with `enrolled_count` at 0. An `OPEN` section accepts new assignments; a `CLOSED` section rejects them. A registrar may **close** an open section (rejected with `ERR_SECTION_NOT_OPEN` if it is not currently `OPEN`), moving it `OPEN → CLOSED` with no further side effects, and may **reopen** a closed section (rejected with `ERR_SECTION_NOT_CLOSED` if it is not currently `CLOSED`), moving it `CLOSED → OPEN`.

Seating a student into a section creates a **ScheduleAssignment** from an `enrollment_id` and a `section_id`. A new assignment starts `ENROLLED`, copies the section's `period` onto itself, and increments the section's `enrolled_count` by one. Three guards apply at seating time. First, the enrollment must be `ACTIVE` and the section `OPEN`, or the create is rejected with `ERR_PARENT_NOT_ACTIVE`. Second, the seat must not create a period collision: an enrollment may not hold two `ENROLLED` assignments meeting in the same `period`, and an attempt to do so is rejected with `ERR_SCHEDULE_PERIOD_CONFLICT`. Third, the section's capacity is period-independent — the count of `ENROLLED` assignments must not exceed the section's `capacity`, and an overflow is rejected with `ERR_SECTION_CAPACITY_EXCEEDED`. A registrar may **drop** an assignment, moving its `status` `ENROLLED → DROPPED` and decrementing the section's `enrolled_count` by one. Dropping an assignment that is already `DROPPED` is idempotent rather than an error: it succeeds with `200 OK`, leaves the status `DROPPED`, and does not decrement `enrolled_count` a second time.

### 3.5. Period Attendance and the Daily Rollup

Period attendance is posted by a teacher or registrar against a `schedule_assignment_id` and a `day_index`, with a `code` drawn from `PRESENT`, `ABSENT_EXCUSED`, `ABSENT_UNEXCUSED`, and `TARDY`. The new **AttendanceRecord** copies the `enrollment_id` and `period` from the assignment, records its `source` as `TEACHER`, and begins in `RECORDED` status. Its `present_minutes` is derived: it equals the section's `meeting_minutes` when the code is `PRESENT` or `TARDY`, and 0 otherwise. The posted `day_index` must fall inside the enrollment's active window — at least the `entry_day_index`, at most the school's `current_school_day_index`, and strictly below `exit_day_index` when the enrollment is `WITHDRAWN` — or the post is rejected with `ERR_ATTENDANCE_OUTSIDE_WINDOW`. Attendance may only be posted against an enrollment that is `ACTIVE`; against a non-active enrollment the post is rejected with `ERR_PARENT_NOT_ACTIVE`.

A teacher or registrar may **correct** an existing record by supplying a replacement `code`. The prior record's `status` becomes `SUPERSEDED`, a fresh `RECORDED` record is created with the new code, and the same active-window rule applies, again surfacing `ERR_ATTENDANCE_OUTSIDE_WINDOW` when the underlying day falls outside the enrollment's window. A record's `status` is therefore either `RECORDED` (the live value) or `SUPERSEDED` (an older value replaced by a correction).

Each attendance write triggers a **daily rollup** that produces or refreshes the enrollment's **DailyAttendance** row for that `enrollment_id` and `day_index`. The rollup considers only `RECORDED` attendance records — `SUPERSEDED` rows are excluded entirely — across that enrollment's assignments. The row's `present_minutes_total` is the sum of `present_minutes` over those records, where each record contributes its section's `meeting_minutes` when its code is `PRESENT` or `TARDY` and 0 otherwise. To classify the day, the rollup also computes the expected minutes for the day as the sum of `meeting_minutes` over the enrollment's `ENROLLED` assignments whose section period has any `RECORDED` record posted that day. The derived `daily_code` is then determined as follows: if no records were posted that day the day is `ABSENT`; otherwise if `present_minutes_total` equals 0 the day is `ABSENT`; otherwise if `present_minutes_total` is at least the expected minutes and the expected minutes are greater than 0 the day is `PRESENT`; in every remaining case the day is `PARTIAL`.

### 3.6. ADA Eligibility and the Present-Day Count

Each DailyAttendance row also carries an `ada_eligible` boolean that decides whether the day counts toward funding, and this is where the two funding flavors first diverge. Under a school whose `ada_method` is `AGGREGATE_MEMBERSHIP`, a day is eligible whenever its `daily_code` is anything other than `ABSENT` — any partial presence counts, and the minute floor is ignored. Under `DAYS_PRESENT`, a day is eligible only when its `present_minutes_total` is at least the school's `minimum_daily_minutes`; a `PARTIAL` day that falls below that floor is not eligible. The boundary is inclusive on the floor: with a `minimum_daily_minutes` of 240, a `present_minutes_total` of exactly 240 is eligible while 239 is not.

From these eligible days the enrollment's `present_days` is recomputed on every rollup, suspension cascade, and rescind. It is the count of the enrollment's DailyAttendance rows whose `ada_eligible` is true and whose `day_index` falls within the enrollment's active window — at least the `entry_day_index` and strictly below the window's upper edge, where that edge is the `exit_day_index` for a `WITHDRAWN` enrollment and otherwise one past the school's `current_school_day_index`.

### 3.7. The Standards Gradebook and Report Cards

A teacher records mastery by upserting a **StandardScore** against a `schedule_assignment_id` for a given `standard_code` (a learning-standard identifier such as `MATH.6.NS.1`), with an optional `weight` defaulting to 1.0 that sets the standard's relative pull inside the section's roll-up. The upsert is keyed on the `(schedule_assignment_id, standard_code)` pair: when a score already exists for that pair its `weight` and graded value are replaced in place — a re-grade of the same standard overwrites rather than accumulating a second score — and the existing record is returned with `200 OK`; when no such score exists a new one is inserted and returned with `201 Created`. The score copies its `section_id` from the assignment. What the body must contain depends on the parent course's grading mode: when the course grades on standards, a `mastery_level` integer in the range 1 through 4 is required (1 is Beginning, 2 Developing, 3 Proficient, 4 Advanced); when the course grades traditionally, a `percentage_points` value in the range 0 through 100 is required instead. A score whose required value is missing or out of range for the course's grading mode is rejected with `ERR_INVALID_GRADE_INPUT`. Scores may only be recorded against an `ACTIVE` enrollment, with a non-active parent rejected as `ERR_PARENT_NOT_ACTIVE`. Critically, whenever a standards score is upserted and a `DRAFT` or `REOPENED` report card already exists for the enrollment, that report card's `version` increments — this is the grade-reconciliation bump that the finalize OCC check in §2.9 relies upon.

A **ReportCard** is opened by a teacher or registrar for an `enrollment_id` and a `term_label` (for example, `Q1`) and begins in `DRAFT` status. A draft computes its preview on read; a finalized card returns frozen values. The computed surface of a report card is its `overall_gpa`, its `credits_earned`, and its `line_items` array, where each line item is a per-section snapshot carrying the `section_id`, the section's `course_code`, the `grading_mode`, the computed `letter_grade`, the `grade_points`, the `mastery_or_percent` value, and a `passed` flag. A report card moves through `DRAFT`, `FINALIZED`, and `REOPENED` statuses.

### 3.8. Computing a Section Grade and a Report Card GPA

When a report card is finalized, each of the enrollment's sections is graded from its StandardScores, and the method again forks on grading mode. For a `STANDARDS` section, the weighted mastery is the sum over the section's scores of weight times `mastery_level`, divided by the sum of the weights. The letter and 4.0-scale grade points follow from that weighted mastery: a weighted mastery of at least 3.5 is an A worth 4.0; at least 3.0 but below 3.5 is a B worth 3.0; at least 2.5 but below 3.0 is a C worth 2.0; at least 2.0 but below 2.5 is a D worth 1.0; anything below 2.0 is an F worth 0.0. The section is passed when the weighted mastery is at least 2.0. For a `TRADITIONAL` section, the weighted percentage is the sum over the scores of weight times `percentage_points`, divided by the sum of the weights, and the bands are: at least 90 is an A (4.0), at least 80 a B (3.0), at least 70 a C (2.0), at least 60 a D (1.0), and below 60 an F (0.0), with the section passed when the weighted percentage is at least 60. In both modes a tie exactly on a band boundary resolves upward into the higher band, because each band is expressed as an at-least threshold. The `mastery_or_percent` recorded on the line item is the weighted mastery for a standards section or the weighted percentage for a traditional one, rounded half-up to two decimal places.

The report card's `overall_gpa` is a single credit-weighted figure across all graded sections: the sum, over every graded section, of the section's `credit_value` times its grade points, divided by the sum of those `credit_value` weights, with the divide performed exactly once at the end over the accumulated totals — never as an average of per-section GPAs — and the final quotient rounded half-up to two decimal places. Sections are accumulated in ascending `created_at` order of their schedule assignments. The `credits_earned` figure is the exact sum of `credit_value` over only the sections whose `passed` flag is true.

Finalizing is a teacher action guarded on three fronts, evaluated after the OCC version check of §2.9. The report card must be in `DRAFT` or `REOPENED` status, or the finalize is rejected with `ERR_REPORT_CARD_NOT_DRAFT`. Every `ENROLLED` schedule assignment of the enrollment must have at least one StandardScore, or the finalize is rejected with `ERR_INCOMPLETE_GRADES`. When those hold, the card moves `DRAFT → FINALIZED` (or `REOPENED → FINALIZED`), and `line_items`, `overall_gpa`, and `credits_earned` are computed and frozen. An administrator may later **reopen** a finalized card — rejected with `ERR_REPORT_CARD_NOT_FINALIZED` if it is not currently `FINALIZED` — which moves it `FINALIZED → REOPENED`, clears `line_items`, and resets `overall_gpa` to null and `credits_earned` to 0, permitting a recompute on the next finalize.

### 3.9. Discipline: Referral, Review, and Adjudication

A teacher or administrator files a **DisciplineIncident** against an `enrollment_id` with a `category` drawn from `DISRUPTION`, `FIGHTING`, `TRUANCY`, `ACADEMIC_DISHONESTY`, and `WEAPON`, a `severity` integer in the range 1 through 5, and the `incident_day_index` on which it occurred. The incident records the filer's identity as its `referring_user_id` and begins in `REFERRED` status.

Adjudication follows a due-process path enforcing segregation of duties at every gate. An administrator **opens review**, which is permitted only while the incident is `REFERRED` (otherwise `ERR_INCIDENT_NOT_REFERRED`) and only when the acting `X-User-ID` differs from the `referring_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`); a successful open moves the incident `REFERRED → UNDER_REVIEW` and pins the reviewing administrator's `X-User-ID` as the incident's `adjudicator_user_id`. The administrator may **dismiss** an incident from either the `REFERRED` or `UNDER_REVIEW` state (a dismiss from any other state is rejected with `ERR_INCIDENT_NOT_DISMISSIBLE`), again requiring the acting identity to differ from the `referring_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); a dismiss moves the incident to `DISMISSED` and rescinds any still-active consequence of the incident, reversing that consequence's attendance cascade (see §3.10). Finally the administrator may **adjudicate**, permitted only while the incident is `UNDER_REVIEW` (otherwise `ERR_INCIDENT_NOT_UNDER_REVIEW`), only when the acting `X-User-ID` equals the pinned `adjudicator_user_id` so that only the reviewer who opened the case may close it (otherwise `ERR_NOT_ASSIGNED_ADJUDICATOR`), and only once a consequence already exists for the incident (otherwise `ERR_NO_CONSEQUENCE_RECORDED`). Adjudication moves the incident `UNDER_REVIEW → ADJUDICATED`, freezing it and making its consequences immutable except via rescind. Both `ADJUDICATED` and `DISMISSED` are terminal.

### 3.10. Consequences and the Suspension Attendance Cascade

While an incident is `UNDER_REVIEW`, the administrator who is its pinned adjudicator attaches a **DisciplineConsequence** under the `incident_id`, with a `type` drawn from `WARNING`, `DETENTION`, `IN_SCHOOL_SUSPENSION`, and `OUT_OF_SCHOOL_SUSPENSION`, an optional `start_day_index` naming the first suspension day inclusive, and an optional `duration_days` that defaults to 0 and is 0 for a warning or detention. The consequence copies its `enrollment_id` from the incident and starts `ACTIVE`. Attaching a consequence requires the parent incident to be `UNDER_REVIEW` (otherwise `ERR_INCIDENT_NOT_UNDER_REVIEW`) and the acting `X-User-ID` to equal the incident's `adjudicator_user_id` (otherwise `ERR_NOT_ASSIGNED_ADJUDICATOR`). For an out-of-school suspension specifically, the `duration_days` must be at least 1 and the `start_day_index` must be at least the incident's `incident_day_index`, or the request is rejected with `ERR_INVALID_CONSEQUENCE`; additionally, a `WEAPON`-category out-of-school suspension is capped at a statutory maximum of 10 days, so a `duration_days` exceeding 10 for that category is rejected with `ERR_SUSPENSION_CAP_EXCEEDED`.

An out-of-school suspension is the system's deepest cascade. For each day index d in the span from `start_day_index` up to but not including `start_day_index` plus `duration_days`, and for each `ENROLLED` schedule assignment of the enrollment, the system writes an AttendanceRecord with code `ABSENT_EXCUSED` and `source` `SYSTEM_SUSPENSION`; any existing `RECORDED` record for that assignment and day is moved to `SUPERSEDED`. The consequence records this on its `absence_code_applied` field, which is set to `ABSENT_EXCUSED` for an out-of-school suspension and remains null for every other type — an out-of-school suspension is treated as an excused absence for ADA purposes. Each affected enrollment-and-day DailyAttendance row is then recomputed via the daily rollup, and the enrollment's `present_days` is recomputed. The full chain therefore runs from a single consequence through new attendance records, through daily attendance, to the enrollment's present-day count.

A consequence may be **rescinded** — explicitly by an administrator, or implicitly when its parent incident is dismissed. A rescind is permitted only while the consequence is `ACTIVE` (otherwise `ERR_CONSEQUENCE_NOT_ACTIVE`) and moves it `ACTIVE → RESCINDED`. The rescind reverses the cascade exactly: every `SYSTEM_SUSPENSION` record this consequence created and still holding `RECORDED` status is deleted, and for each affected assignment-and-day the most recent record that had been superseded — the latest `SUPERSEDED` record by `created_at` descending — is restored to `RECORDED`. Each affected DailyAttendance row is recomputed and the enrollment's `present_days` is recomputed. This is a true compensating action: after a rescind, the enrollment's `present_days` must return to exactly the value it held before the suspension was applied.

### 3.11. ADA Funding Reports: Drafting, Recompute, and Certification

A registrar or state reporting officer drafts an **AdaFundingReport** for a `school_id` through an `as_of_day_index` — the inclusive school-day index the report snapshots membership and attendance through. The draft starts in `DRAFT` status, records its creator's identity as `drafter_user_id`, snapshots the school's funding flavor into `method_used`, and computes its `total_ada` and `funded_enrollment_count` immediately.

The funding computation operates over every enrollment of the report's school whose `entry_day_index` is at most the `as_of_day_index` and whose status is not `NO_SHOW`. For each such enrollment, the membership span through the snapshot is the smaller of one-past-the-`as_of_day_index` and the enrollment's window upper edge (its `exit_day_index` when withdrawn, otherwise one past the current clock), minus the `entry_day_index`, clamped to be no less than 0. The eligible present count for the enrollment is the number of its present days whose `day_index` is at most the `as_of_day_index`. Here the two flavors diverge for the final time. Under `AGGREGATE_MEMBERSHIP`, an enrollment's ADA is its membership span divided by `session_total_days`, multiplied by its `fte`, rounded half-up to four decimals — the numerator is enrolled days regardless of attendance, so a fully absent but enrolled student still earns ADA. Under `DAYS_PRESENT`, an enrollment's ADA is its eligible present count divided by `session_total_days`, multiplied by its `fte`, rounded half-up to four decimals — the numerator is ADA-eligible present days, so for an identical roster and identical span the total is strictly lower whenever any eligible day is missed. The report's `total_ada` is the sum of those per-enrollment rounded ADA values, rounded half-up to four decimals (round-then-sum, per §2.8), and `funded_enrollment_count` is the number of in-scope enrollments whose ADA contribution is greater than 0.

While the report is still `DRAFT`, a registrar or officer may **recompute** it against current data — rejected with `ERR_REPORT_NOT_DRAFT` if it is no longer `DRAFT` — which refreshes `total_ada` and `funded_enrollment_count` and increments the report's `version`, the bump the certify OCC check in §2.9 relies upon. A state reporting officer **certifies** a draft, which requires (after the OCC version match) that the report be `DRAFT` (otherwise `ERR_REPORT_NOT_DRAFT`), that the acting `X-User-ID` differ from the `drafter_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), and that no in-scope enrollment is still `ACTIVE` with an `entry_day_index` at or before the `as_of_day_index` yet has zero DailyAttendance rows through the `as_of_day_index` (otherwise `ERR_ATTENDANCE_NOT_POSTED`, which guards against certifying before attendance has been entered). A successful certify moves the report `DRAFT → CERTIFIED`, records the officer's `X-User-ID` as `certifier_user_id`, and freezes `total_ada` and `funded_enrollment_count`. Alternatively the officer may **reject** a draft — again requiring `DRAFT` status (`ERR_REPORT_NOT_DRAFT`) and an acting identity differing from the `drafter_user_id` (`ERR_SEGREGATION_OF_DUTIES`) — which moves it `DRAFT → REJECTED` with no funding contribution. Both `CERTIFIED` and `REJECTED` are terminal.

### 3.12. Reading the System: Lists, Filters, and the Parent Portal

Across the system, list reads accept the filters that make sense for each collection. Students may be filtered by `school_id` and `status`; enrollments by `student_id`, `school_id`, and `status`; courses by `school_id`; sections by `course_id`, `school_id`, and `period`; schedule assignments by `enrollment_id`, `section_id`, and `status`, and a section exposes the assignments seated in it filtered by `status`. Attendance records may be filtered by `schedule_assignment_id`, `enrollment_id`, `day_index`, and `status`, and an enrollment exposes its DailyAttendance rollup rows filtered by `day_index`. Standard scores may be filtered by `schedule_assignment_id` and `section_id`. Report cards may be filtered by `enrollment_id` and `status`. Discipline incidents may be filtered by `enrollment_id` and `status`, an incident exposes its consequences filtered by `status`, and consequences may be listed across incidents filtered by `enrollment_id`, `incident_id`, and `status`. Funding reports may be filtered by `school_id` and `status`. Every list also accepts `limit` and `offset` per §2.3. All parent reads remain gated by the guardian check of §2.4.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition operations and clock advancement — return `200 OK`. The one nuance is attendance correction, which mints a new attendance record and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/schools` | Create a school (sets ADA method and clock) | Registrar |
| GET | `/schools/{id}` | Get a school | Registrar, Teacher, Administrator, StateReportingOfficer, Parent |
| POST | `/schools/{id}/clock/advance` | Advance the deterministic school-day clock | Registrar |
| POST | `/students` | Create a student demographic record | Registrar |
| GET | `/students` | List/filter students | Registrar, Administrator, Teacher, StateReportingOfficer |
| GET | `/students/{id}` | Get a student | Registrar, Administrator, Teacher, StateReportingOfficer, Parent |
| GET | `/students/{id}/portal-summary` | Parent-portal read-only summary for a guardian's child | Parent, Registrar, Administrator |
| POST | `/students/{id}/guardians` | Link a guardian to a student for portal access | Registrar |
| POST | `/enrollments` | Enroll a student (creates membership window) | Registrar |
| GET | `/enrollments` | List/filter enrollments | Registrar, Administrator, StateReportingOfficer |
| GET | `/enrollments/{id}` | Get an enrollment | Registrar, Administrator, StateReportingOfficer, Teacher |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment (sets exit, drops schedule) | Registrar |
| POST | `/enrollments/{id}/mark-no-show` | Mark an enrollment as a no-show | Registrar |
| GET | `/enrollments/{id}/daily-attendance` | List the enrollment's daily attendance rollup rows | Registrar, Administrator, StateReportingOfficer, Teacher, Parent |
| POST | `/courses` | Create a course | Registrar |
| GET | `/courses` | List/filter courses | Registrar, Administrator, Teacher |
| GET | `/courses/{id}` | Get a course | Registrar, Administrator, Teacher |
| POST | `/sections` | Create a section of a course in a period | Registrar |
| GET | `/sections` | List/filter sections | Registrar, Administrator, Teacher |
| GET | `/sections/{id}` | Get a section | Registrar, Administrator, Teacher |
| POST | `/sections/{id}/close` | Close a section to new assignments | Registrar |
| POST | `/sections/{id}/reopen` | Reopen a closed section | Registrar |
| GET | `/sections/{id}/schedule-assignments` | List schedule assignments seated in a section | Registrar, Administrator, Teacher |
| POST | `/schedule-assignments` | Seat an enrollment into a section (period-exclusive) | Registrar |
| GET | `/schedule-assignments` | List/filter schedule assignments | Registrar, Administrator, Teacher |
| GET | `/schedule-assignments/{id}` | Get a schedule assignment | Registrar, Administrator, Teacher |
| POST | `/schedule-assignments/{id}/drop` | Drop a schedule assignment | Registrar |
| POST | `/attendance-records` | Post period attendance for an assignment+day | Teacher, Registrar |
| GET | `/attendance-records` | List/filter attendance records | Teacher, Registrar, Administrator, StateReportingOfficer |
| GET | `/attendance-records/{id}` | Get an attendance record | Teacher, Registrar, Administrator, StateReportingOfficer |
| POST | `/attendance-records/{id}/correct` | Correct a period attendance code (supersedes prior) | Teacher, Registrar |
| POST | `/standard-scores` | Record/upsert a standards score for an assignment | Teacher |
| GET | `/standard-scores` | List/filter standard scores | Teacher, Registrar, Administrator |
| GET | `/standard-scores/{id}` | Get a standard score | Teacher, Registrar, Administrator |
| POST | `/report-cards` | Open a DRAFT report card for an enrollment+term | Teacher, Registrar |
| GET | `/report-cards` | List/filter report cards | Teacher, Registrar, Administrator, Parent |
| GET | `/report-cards/{id}` | Get a report card | Teacher, Registrar, Administrator, Parent |
| POST | `/report-cards/{id}/finalize` | Finalize a report card (OCC-guarded, freezes grades) | Teacher |
| POST | `/report-cards/{id}/reopen` | Reopen a finalized report card | Administrator |
| POST | `/discipline-incidents` | File a discipline incident referral | Teacher, Administrator |
| GET | `/discipline-incidents` | List/filter discipline incidents | Teacher, Administrator, Registrar, Parent |
| GET | `/discipline-incidents/{id}` | Get a discipline incident | Teacher, Administrator, Registrar, Parent |
| POST | `/discipline-incidents/{id}/begin-review` | Administrator opens review (SoD: not the referrer) | Administrator |
| POST | `/discipline-incidents/{id}/adjudicate` | Adjudicate an incident under review | Administrator |
| POST | `/discipline-incidents/{id}/dismiss` | Dismiss an incident; rescinds active consequence | Administrator |
| POST | `/discipline-incidents/{id}/consequences` | Attach a consequence to an under-review incident | Administrator |
| GET | `/discipline-incidents/{id}/consequences` | List consequences attached to an incident | Teacher, Administrator, Registrar, Parent |
| GET | `/discipline-consequences` | List/filter discipline consequences across incidents | Teacher, Administrator, Registrar, Parent |
| GET | `/discipline-consequences/{id}` | Get a discipline consequence | Teacher, Administrator, Registrar, Parent |
| POST | `/discipline-consequences/{id}/rescind` | Rescind an active consequence (reverses cascade) | Administrator |
| POST | `/ada-funding-reports` | Draft an ADA funding report snapshot through a day | Registrar, StateReportingOfficer |
| GET | `/ada-funding-reports` | List/filter ADA funding reports | Registrar, StateReportingOfficer, Administrator |
| GET | `/ada-funding-reports/{id}` | Get an ADA funding report | Registrar, StateReportingOfficer, Administrator |
| POST | `/ada-funding-reports/{id}/recompute` | Recompute a DRAFT report's totals against current data | Registrar, StateReportingOfficer |
| POST | `/ada-funding-reports/{id}/certify` | Certify a DRAFT report (OCC-guarded, SoD vs drafter) | StateReportingOfficer |
| POST | `/ada-funding-reports/{id}/reject` | Reject a DRAFT report (SoD vs drafter) | StateReportingOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_GUARDIAN_OF_STUDENT` | 403 Forbidden |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ATTENDANCE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_STANDARD_SCORE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONSEQUENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ADA_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_COURSE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_STATE_STUDENT_ID` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_EXIT_DAY` | 422 Unprocessable Entity |
| `ERR_EXIT_DAY_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_PRESENCE_ON_RECORD` | 409 Conflict |
| `ERR_PARENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SECTION_NOT_OPEN` | 409 Conflict |
| `ERR_SECTION_NOT_CLOSED` | 409 Conflict |
| `ERR_SECTION_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SCHEDULE_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_ATTENDANCE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_GRADE_INPUT` | 422 Unprocessable Entity |
| `ERR_REPORT_CARD_NOT_DRAFT` | 409 Conflict |
| `ERR_REPORT_CARD_NOT_FINALIZED` | 409 Conflict |
| `ERR_INCOMPLETE_GRADES` | 409 Conflict |
| `ERR_INCIDENT_NOT_REFERRED` | 409 Conflict |
| `ERR_INCIDENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_INCIDENT_NOT_DISMISSIBLE` | 409 Conflict |
| `ERR_NOT_ASSIGNED_ADJUDICATOR` | 403 Forbidden |
| `ERR_NO_CONSEQUENCE_RECORDED` | 409 Conflict |
| `ERR_INVALID_CONSEQUENCE` | 422 Unprocessable Entity |
| `ERR_SUSPENSION_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CONSEQUENCE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REPORT_NOT_DRAFT` | 409 Conflict |
| `ERR_ATTENDANCE_NOT_POSTED` | 409 Conflict |
