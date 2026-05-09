# Driving School API — Product Requirements Document

## 1. Introduction

A modern driving school must reconcile three competing pressures every day: regulatory officers demand precise hour records and stage-completion attestations, students demand flexibility in when they can practice, and instructors demand sane schedules with rest. This document specifies the back-of-house API that holds these constituencies together. It governs the lifecycle of a student from initial walk-in through final examination, the calendars of instructors and vehicles, the budget gates of the package the student paid for, and the complaint-handling workflow that keeps customer relationships repairable.

The audience for this document is the engineer building the implementation. Wherever a rule reads as bureaucratic — "instructor calendars use closed intervals", "the late-cancellation fee uses tiered pricing with strict-less-than cliffs" — the bureaucracy is intentional. These are the disambiguations that distinguish a passing implementation from a failing one. Where the document introduces a numeric threshold or a state-name pair, it is asserting a contract with the test suite: the threshold is exact, and the state names are canonical.

A note on time. The system is designed to be **test-driven** in the literal sense: a logical clock, exposed through a clock-advance capability, is the single source of "now". Every fee tier, every check-in window, every cycle reset, every no-show sweep reads from this clock. The implementation must use the logical clock — never wall-clock time — for all such checks.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP 400. If the role is present but lacks permission for the requested operation per the role-to-endpoint matrix described throughout §3 and summarised in §4, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` and HTTP 403.

Five role names are recognised, spelled exactly as follows: `Admin`, `Student`, `Instructor`, `Examiner`, `ComplaintHandler`. Two of these roles are **entity-backed**, and three are **opaque**. The distinction is what `X-User-ID` means, and how ownership checks are performed.

When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` row; ownership checks on any resource that references a `Student` (such as a `PracticeAppointment`, a `SimulatorSession`, an `ExamAppointment`, or a `Complaint`) compare the resource's `student_id` to `X-User-ID`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor` row; ownership checks at check-in and check-out compare the appointment's `instructor_id` to `X-User-ID`.

When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, on `AuditLog.actor_id`) but does not compare it to any entity's `id`. The same holds for `Examiner`: `X-User-ID` is an opaque examiner identifier, recorded on `ExamAppointment.examiner_id` only when the booking explicitly supplies it. The same holds for `ComplaintHandler`: `X-User-ID` is an opaque handler identifier; the server records it on `Complaint.assigned_handler_id` when an `Admin` performs the assignment, and later compares the acting `ComplaintHandler`'s `X-User-ID` to that stored value at escalation, resolution, or rejection time.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to `10`, must be at least `1`, and must not exceed `100`; the `offset` parameter defaults to `0`. List results are sorted by `created_at` ascending. The pagination block in the response `meta` carries four fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp with the same format and a monotonically increasing integer `version` field that begins at 1 on creation and increments by 1 on every server-side mutation; both `updated_at` and `version` are refreshed every time the resource is mutated, including when state changes are driven by side-effects of a different resource's transition.

Three entities are exceptions because they are immutable or append-only: a `CoursePackage` is configuration that never changes after creation and therefore carries only `id` and `created_at` — no `updated_at`, no `version`. A `TrainingHourRecord` is an append-only audit row produced as a side-effect of practice check-out, and it likewise carries only `id` and `created_at`. An `AuditLog` row is similarly append-only and carries only `id` and `created_at`. Where this document references an `updated_at` or `version` for one of these entities, it is an error in the document; in practice, the test suite never asks for those fields on these three entities.

### 2.5. Optimistic Concurrency Control

Every mutating endpoint on a resource that carries `version` (i.e., everything except `CoursePackage`, `TrainingHourRecord`, and `AuditLog`) accepts an optional `version` field in the request body. When supplied, the server compares the supplied value against the resource's current `version`; on mismatch, the request is rejected with `ERR_STALE_DATA` and HTTP 409, the resource is unmodified, and no side-effects fire. When the `version` field is omitted from the request body, the OCC check is skipped entirely and the operation proceeds. On any successful mutation, `version` is incremented by 1 and `updated_at` is refreshed.

### 2.6. Precision and Rounding

All monetary amounts are integer cents — there are no fractional cents anywhere in the system. The late-cancellation tier calculation rounds toward zero (floor) when applying its tier percentage to a base price; see §3 for the full formula. GPS distances are reported in kilometres rounded to two decimal places, and the GPS validation threshold is **inclusive at exactly 5.00** — a distance of `5.00` km validates, a distance of `4.99` km does not. Practice minutes are integer minutes derived from the difference between `scheduled_end_at` and `scheduled_start_at` in seconds divided by 60 with floor division.

### 2.7. Nested Resource Retrieval and Path Validation

Every endpoint that takes path parameters validates them left to right. A request to act on a complaint whose path id does not resolve receives `ERR_COMPLAINT_NOT_FOUND` and HTTP 404 before any body validation runs. The same pattern applies to `ERR_STUDENT_NOT_FOUND`, `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_PRACTICE_NOT_FOUND`, `ERR_EXAM_NOT_FOUND`, and `ERR_SIMULATOR_NOT_FOUND`. Body shape errors (a missing required field, a type mismatch) yield `ERR_INVALID_REQUEST` with HTTP 400 only after auth and existence checks pass.

### 2.8. Validation Priority

When several rules guard the same endpoint, they are evaluated in a fixed priority order so that the first failure is the one reported, and that order is identical across every endpoint that the rules apply to. From highest priority to lowest:

1. **Auth headers present** — checked first; missing or empty `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission** — `ERR_INSUFFICIENT_PERMISSIONS` when the role is not authorised for the operation.
3. **Path-resource existence** — left-to-right; e.g., `ERR_STUDENT_NOT_FOUND`, `ERR_PRACTICE_NOT_FOUND`, etc.
4. **Ownership** — for entity-backed roles, the resource's owner foreign key must equal `X-User-ID`; failures yield `ERR_FORBIDDEN_NOT_OWNER`, `ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR`, or `ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER` as appropriate.
5. **State** — the resource is in the correct state for the operation (e.g., `ERR_APPOINTMENT_NOT_CANCELLABLE`, `ERR_EXAM_NOT_BOOKABLE`, `ERR_COMPLAINT_NOT_ASSIGNABLE`).
6. **Cross-entity referential integrity** — e.g., an instructor's `vehicle_qualifications` must include the booking vehicle's `vehicle_type` (`ERR_INSTRUCTOR_NOT_QUALIFIED`); the vehicle's `vehicle_type` must be compatible with the student's `training_stage` (`ERR_VEHICLE_TYPE_MISMATCH`); the exam's `prerequisite_stage` must match the student's `training_stage` (`ERR_PREREQUISITE_STAGE_NOT_MET`); a complaint with `INSTRUCTOR_CONDUCT` category requires Admin handler (`ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN`); a complaint at `level` 3 requires Admin handler (`ERR_LEVEL3_REQUIRES_ADMIN`).
7. **Temporal conflicts** — instructor calendar overlap, vehicle calendar overlap, and check-in window violations (`ERR_INSTRUCTOR_TIME_CONFLICT`, `ERR_VEHICLE_TIME_CONFLICT`, `ERR_OUTSIDE_CHECK_IN_WINDOW`).
8. **Instructor safety** — daily and weekly working-minute caps and the rest-day rule (`ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED`, `ERR_INSTRUCTOR_WEEKLY_LIMIT_EXCEEDED`, `ERR_INSTRUCTOR_NEEDS_REST`).
9. **Cycle-bounded counters and limits** — reschedule-per-cycle, exam retake limit, complaint escalation limit, and stage minimum hours (`ERR_RESCHEDULE_LIMIT_EXCEEDED`, `ERR_RETAKE_LIMIT_EXCEEDED`, `ERR_ESCALATION_LIMIT_REACHED`, `ERR_STAGE_MIN_HOURS_NOT_MET`).
10. **Package balance gates** — practice minutes, exam attempts, and other fiscal preconditions (`ERR_INSUFFICIENT_PACKAGE_BALANCE`, `ERR_NO_EXAM_ATTEMPTS_REMAINING`).

This priority is canonical: an unauthenticated request to a non-existent appointment receives the auth error, never the not-found error. A correctly authenticated student attempting to cancel another student's appointment receives the ownership error, never the state error. A correctly authenticated, correctly owning student attempting to cancel an already-cancelled appointment receives the state error, never the temporal error. And so on down the list.

### 2.9. Concurrency and Serialisation

Five well-known races are explicitly serialised. Two simultaneous practice bookings for the same instructor at overlapping times serialise to exactly one winner; the loser receives `ERR_INSTRUCTOR_TIME_CONFLICT` because the instructor's calendar is enforced as **closed intervals** — a request whose `scheduled_start_at` equals an existing booking's `scheduled_end_at` is rejected as adjacent-overlap. Two simultaneous practice bookings for the same vehicle at overlapping times — or within the 15-minute cleaning buffer described in §3 — serialise to exactly one winner; the loser receives `ERR_VEHICLE_TIME_CONFLICT`. A cancel and a check-in racing on the same `BOOKED` practice appointment serialise to exactly one winner; whichever loses sees the appointment in its new status and receives `ERR_APPOINTMENT_NOT_CANCELLABLE`. Two simultaneous record-result calls on the same `BOOKED` exam serialise to exactly one winner that lands a terminal state; the loser receives `ERR_EXAM_NOT_BOOKABLE`. Two simultaneous assign-handler calls on the same `OPEN` complaint serialise to exactly one winner that moves the complaint to `IN_REVIEW`; the loser receives `ERR_COMPLAINT_NOT_ASSIGNABLE`.

### 2.10. Audit Logging

Every state-changing operation produces an `AuditLog` row with `actor_role`, `actor_id`, `entity_type`, `entity_id`, `action`, and `occurred_at`. The `action` field takes one of: `CREATE`, `UPDATE`, `CANCEL`, `CHECK_IN`, `CHECK_OUT`, `RESCHEDULE`, `RECORD_RESULT`, `SUBMIT_HOURS`, `NO_SHOW_SWEEP`, `ESCALATE`, `RESOLVE`, `REJECT`, `ASSIGN_HANDLER`. The `actor_role` and `actor_id` come from the request's `X-User-Role` and `X-User-ID`; `occurred_at` is the logical-clock timestamp in ISO 8601 UTC. The audit-log listing capability supports filtering by query parameters `entity_type` and `entity_id`, plus pagination via `limit` and `offset`.

## 3. Business Logic & Workflows

### 3.1. The Student Onboarding Lifecycle

A student record is created at `PENDING_VERIFICATION`, holding only the inputs `full_name`, `id_number`, and `id_card_country` together with the system-managed defaults — `id_verified` is `false`, `medical_cert_status` is `PENDING`, `enrollment_status` is `PENDING_VERIFICATION`, `training_stage` is `THEORY`, `no_show_count_this_cycle` and `reschedule_count_this_cycle` are both 0, `has_passed_theory` and `has_passed_basic_practical` are both `false`, and `suspension_reason` is null. Onboarding then walks four stages.

**Identity verification** advances `enrollment_status` from `PENDING_VERIFICATION` to `PENDING_MEDICAL`. The verifying call is admin-only and requires `id_number` and `id_card_country` to be present on the student row; the side-effect sets `id_verified` to `true`. If the student is not at `PENDING_VERIFICATION` when this is invoked, the request is rejected with `ERR_STUDENT_NOT_AT_PENDING_STATE`.

**Medical-certificate validation** advances `enrollment_status` from `PENDING_MEDICAL` to `PENDING_PACKAGE`. The body carries `medical_cert_expires_on`, an ISO 8601 date that must be strictly after the logical clock; an expired or same-day expiry is rejected with `ERR_MEDICAL_CERT_EXPIRED`. The side-effect sets `medical_cert_status` to `VALID`.

**Course-package selection** advances `enrollment_status` from `PENDING_PACKAGE` to `PENDING_CONTRACT`. The body carries `course_package_id`, which must resolve to an existing package; otherwise the request is rejected with `ERR_PACKAGE_NOT_FOUND`. The side-effect stores `course_package_id` on the student.

**Contract signing** advances `enrollment_status` from `PENDING_CONTRACT` to `ACTIVE`. The student's `medical_cert_status` is rechecked against the logical clock at this point — if the underlying date has slipped past expiry between submission and signing, the request is rejected with `ERR_MEDICAL_CERT_EXPIRED`. On success, the side-effects are: `contract_signed_at` is set to the logical clock; `cycle_start_date` is set to the logical clock; `training_stage` is set to `THEORY`; and a synchronous payment-event log records `PACKAGE_PAID` for the package's `total_price_cents`.

**Suspension and reinstatement.** An admin may suspend an `ACTIVE` student at any time; the side-effect sets `suspension_reason` to `ADMIN_ACTION`, and `enrollment_status` becomes `SUSPENDED`. An admin may reinstate a `SUSPENDED` student; the side-effect clears `suspension_reason` and `enrollment_status` returns to `ACTIVE`. There is also an automatic suspension path described in §3.4 (no-show threshold breach), which sets `suspension_reason` to `NO_SHOW_THRESHOLD_BREACH` and additionally cascades to mass-cancel future bookings.

**Completion.** When a student passes their `FINAL_TEST` (see §3.5), their `training_stage` advances to `COMPLETED`, and `enrollment_status` cascades from `ACTIVE` to `COMPLETED` in the same operation. As an additional side-effect of that cascade, every `TrainingHourRecord` row for this student whose `authority_submission_status` is `PENDING` is bulk-transitioned to `SUBMITTED` with `submitted_at` set to the logical clock.

### 3.2. Operational Resources: Instructors, Vehicles, Course Packages

Instructors are managed by Admin. A new `Instructor` row carries `full_name`, `license_number`, and `vehicle_qualifications` — an array of vehicle types the instructor is qualified to teach, drawn from the four allowed values `MANUAL_C1`, `AUTO_C2`, `TRUCK_B2`, and `MOTORCYCLE_E`. The instructor's `status` starts at `ACTIVE`. Suspension flips `status` to `SUSPENDED`; reinstatement flips it back. Instructors also carry a `last_rest_date` (the most recent calendar date with no booked practice for them) and two computed fields: `working_minutes_today` and `working_minutes_this_week`, both summed in the provisional manner described in §3.6.

Vehicles carry a `plate_number`, a `vehicle_type` (one of the four enumerations above), and a `status` whose initial value is `ACTIVE`. An admin may move a vehicle to `MAINTENANCE` and back to `ACTIVE`. A retired vehicle (`RETIRED`) is permanently out of service. A vehicle whose `status` is not `ACTIVE` cannot be used as the subject of a practice booking, nor can a check-in proceed on a practice whose vehicle has slipped out of `ACTIVE` between booking and check-in — the latter case yields `ERR_VEHICLE_NOT_ACTIVE`.

Course packages are immutable configuration: each `CoursePackage` carries `name`, `total_minutes`, `total_price_cents`, `included_simulator_sessions`, `included_exam_attempts`, `per_minute_overage_price_cents`, and `per_simulator_session_overage_price_cents`. Once created, a package never changes, and it is referenced by `course_package_id` on every student that subscribes to it.

### 3.3. Practice Booking — The Heart of the Calendar

A `PracticeAppointment` is the central operational artefact. The booking payload carries `student_id`, `instructor_id`, `vehicle_id`, `training_stage`, `scheduled_start_at`, `scheduled_end_at`, and an optional `reschedule_of_id` whose meaning is explained in §3.4. The booking computes `scheduled_minutes` as the integer-floor of `(scheduled_end_at − scheduled_start_at)` in seconds divided by 60, snapshots `vehicle_type` from the chosen vehicle so that subsequent vehicle changes do not retroactively re-classify the practice, and stamps `status` to `BOOKED`.

A great many gates fire at booking time. The student must be `ACTIVE` (otherwise `ERR_STUDENT_NOT_ACTIVE`). The instructor must be `ACTIVE` (otherwise `ERR_INSTRUCTOR_NOT_ACTIVE`). The vehicle must be `ACTIVE` (otherwise `ERR_VEHICLE_NOT_ACTIVE`). The body's `training_stage` must equal the student's current `training_stage` at booking time. The vehicle's `vehicle_type` must be in the instructor's `vehicle_qualifications` set (otherwise `ERR_INSTRUCTOR_NOT_QUALIFIED`). The vehicle's `vehicle_type` must be compatible with the student's `training_stage`: a student whose `training_stage` is `THEORY` cannot book a `MOTORCYCLE_E` or a `TRUCK_B2` vehicle (`ERR_VEHICLE_TYPE_MISMATCH`).

Calendar conflict checks then apply, and the two calendars use deliberately different semantics. The **instructor calendar is enforced as closed intervals** `[a, b]`: a proposed booking `[c, d]` conflicts with an existing booking `[a, b]` whenever `a` is at or before `d` and `c` is at or before `b`. Adjacency is treated as a conflict — a request whose `scheduled_start_at` equals an existing booking's `scheduled_end_at` (or vice versa) is rejected with `ERR_INSTRUCTOR_TIME_CONFLICT`. The **vehicle calendar is enforced as half-open intervals** `[a, b)` plus a 15-minute cleaning buffer: a proposed booking `[c, d)` conflicts with an existing booking `[a, b)` whenever the open intervals overlap, and additionally whenever the gap between the earlier interval's end and the later interval's start is shorter than 15 minutes. Adjacent vehicle bookings are not in themselves a conflict, but vehicle bookings within 15 minutes of each other are. Vehicle conflicts yield `ERR_VEHICLE_TIME_CONFLICT`.

Instructor safety gates then apply. The provisional sum of `(scheduled_end_at − scheduled_start_at)` in minutes for this instructor's practices in `BOOKED`, `IN_PROGRESS`, or `COMPLETED` falling on the logical clock's calendar date in UTC, plus the proposed booking's minutes, must not exceed an 8-hour daily ceiling (480 minutes); otherwise `ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED`. The same provisional sum across the calendar week (Monday 00:00 UTC through Sunday 23:59:59 UTC) plus the proposed booking's minutes must not exceed a 40-hour weekly ceiling (2400 minutes); otherwise `ERR_INSTRUCTOR_WEEKLY_LIMIT_EXCEEDED`. And the **rest-day rule** requires that the instructor have at least one rest day per week: count the distinct calendar dates in the proposed booking's ISO week (Monday-to-Sunday containing `scheduled_start_at`) on which this instructor has at least one practice in `BOOKED`, `IN_PROGRESS`, or `COMPLETED` status, including the proposed booking's own date in that count; if the resulting set of distinct working dates equals 7, the booking is rejected with `ERR_INSTRUCTOR_NEEDS_REST`.

Cycle-bound and fiscal gates close out the priority list. If this booking would push the student's `reschedule_count_this_cycle` past the per-cycle cap — see §3.4 — the booking is rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`. Finally, the package balance gate: the student's `minutes_remaining_provisional`, computed as the package's `total_minutes` minus the sum of `scheduled_minutes` over this student's practices in `BOOKED`, `IN_PROGRESS`, or `COMPLETED` (excluding `CANCELLED` and `NO_SHOW`), minus the proposed practice's `scheduled_minutes`, must be at least zero; otherwise `ERR_INSUFFICIENT_PACKAGE_BALANCE`. The provisional figure has a sibling, `minutes_remaining_final`, computed as the package's `total_minutes` minus the sum of `recorded_minutes` over this student's practices that are in `COMPLETED` status with `gps_validated` true; this is the figure used for end-of-cycle authority reporting and is always at or above `minutes_remaining_provisional` in steady state — they diverge only when there are pending `BOOKED`/`IN_PROGRESS` rows or `COMPLETED` rows whose `gps_validated` is false. There is no automatic overage for practice — a booking that would draw the package below zero is simply refused.

When all gates pass, the practice is persisted at `BOOKED`, an `AuditLog` row is written with action `CREATE`, and the response carries the new appointment.

### 3.4. Cancellation, No-Show, and Rescheduling

A `BOOKED` practice may be cancelled by an Admin or by the owning Student. The cancellation transition sets `cancelled_at` to the logical clock, sets `cancellation_actor_role` to the acting `X-User-Role` (`Admin` or `Student`), and computes `late_cancellation_fee_cents` according to a tiered schedule. If the practice is not in `BOOKED`, the cancel is rejected with `ERR_APPOINTMENT_NOT_CANCELLABLE`. A Student attempting to cancel another student's appointment is rejected with `ERR_FORBIDDEN_NOT_OWNER` before the state check fires.

The fee schedule. Compute the signed difference `delta_seconds = scheduled_start_at − clock_now` and convert to floating-point hours `delta_hours = delta_seconds / 3600.0`. Compute the base session price as `scheduled_minutes` multiplied by the package's `per_minute_overage_price_cents`. The tier percentage is selected by strict-less-than cliffs: when `delta_hours` is at or below zero the tier is 100 percent; when `delta_hours` is strictly greater than zero but strictly less than 2, the tier is also 100 percent; when `delta_hours` is at or above 2 but strictly less than 24, the tier is 50 percent; when `delta_hours` is at or above 24, the tier is 0 percent. (At exactly 2 hours the tier is 50; at exactly 24 hours the tier is 0.) The final `late_cancellation_fee_cents` is the floor of `base_session_price_cents * tier_pct / 100` — fee precision is integer cents with floor.

The **no-show sweep** is the system actor's path from `BOOKED` to `NO_SHOW`. When the sweep capability runs, it scans for `BOOKED` practices whose `scheduled_end_at + NO_SHOW_GRACE_MINUTES` (15 minutes) is strictly before the logical clock and transitions each to `NO_SHOW`. The transition computes `no_show_fee_cents` as 100 percent of the base session price — that is, `scheduled_minutes` multiplied by the package's `per_minute_overage_price_cents`, with no tier reduction. An `AuditLog` row is written with action `NO_SHOW_SWEEP`. After the no-show transition lands, the system recomputes the student's `no_show_count_this_cycle` (the count of this student's practices in `NO_SHOW` status whose `scheduled_start_at` is at or after `cycle_start_date`); if that count equals 3 and the student is currently `ACTIVE`, the system cascades the student to `SUSPENDED` with `suspension_reason` set to `NO_SHOW_THRESHOLD_BREACH`, and as a further cascade every other `BOOKED` practice for this student is auto-cancelled with `cancellation_actor_role` recorded as `system` and `late_cancellation_fee_cents` of zero. The same sweep also transitions expired `BOOKED` `ExamAppointment` rows (computed against `scheduled_at + 60 + NO_SHOW_GRACE_MINUTES`) and expired `BOOKED` `SimulatorSession` rows (computed against `scheduled_end_at + NO_SHOW_GRACE_MINUTES`) to `NO_SHOW`.

The **cycle reset** is the second thing the same sweep does. For each student whose `enrollment_status` is `ACTIVE` or `SUSPENDED` and whose `cycle_start_date` is at least 30 calendar days (UTC) before the logical clock's date, the system advances `cycle_start_date` to the logical clock's date. Because `no_show_count_this_cycle` and `reschedule_count_this_cycle` are computed from records whose timestamps are at or after `cycle_start_date`, advancing the cycle implicitly resets both counters to zero. An `AuditLog` row is written for each such student.

**Rescheduling.** The reschedule capability atomically cancels a `BOOKED` practice and creates a new `BOOKED` practice in the same operation. The body carries `new_scheduled_start_at`, `new_scheduled_end_at`, and optional `new_instructor_id` and `new_vehicle_id` — when omitted, the new booking inherits the corresponding instructor/vehicle from the cancelled one. The cancellation half of the operation does not charge a late-cancellation fee — `late_cancellation_fee_cents` is set to zero on the cancelled row regardless of which tier the timing would otherwise place it in — but it does record `cancellation_actor_role` and increments the student's `reschedule_count_this_cycle`. The new `BOOKED` row is created with `reschedule_of_id` pointing at the cancelled row. If the student's `reschedule_count_this_cycle` is already at the per-cycle cap of 3, the operation is rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`. Both halves of the operation share an `AuditLog` action pair: `CANCEL` on the original, then `CREATE` and `RESCHEDULE` on the new one.

### 3.5. Practice Sessions, Hour Tracking, and Exam Progression

**Check-in.** When the student arrives, the assigned instructor checks in. The check-in is rejected with `ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR` if the acting `Instructor`'s `X-User-ID` does not match the appointment's `instructor_id`. If the appointment is not in `BOOKED`, the request is rejected with `ERR_APPOINTMENT_NOT_CHECK_INNABLE`. The check-in window is itself a precondition: the logical clock must be at or after `scheduled_start_at − 15 minutes` and strictly before `scheduled_end_at`; otherwise the check-in is rejected with `ERR_OUTSIDE_CHECK_IN_WINDOW`. The vehicle's `status` is rechecked at check-in time and must still be `ACTIVE` (`ERR_VEHICLE_NOT_ACTIVE`). On success, the appointment advances to `IN_PROGRESS`, `check_in_at` is stamped to the logical clock, and an `AuditLog` row is written with action `CHECK_IN`.

**Check-out.** The same instructor closes the session. The body carries `gps_track_distance_km`, the GPS-recorded driving distance for the session in kilometres rounded to two decimal places. If the appointment is not in `IN_PROGRESS`, the request is rejected with `ERR_APPOINTMENT_NOT_CHECK_OUTTABLE`. On success, the appointment advances to `COMPLETED`, `check_out_at` is stamped to the logical clock, `gps_validated` becomes `true` exactly when `gps_track_distance_km` is at or above the 5.00 km threshold (so 5.00 km validates, 4.99 km does not), and `recorded_minutes` becomes `scheduled_minutes` if `gps_validated` is true and 0 otherwise. As a side-effect of the same operation, a new `TrainingHourRecord` row is appended carrying `student_id`, `source_appointment_id`, `training_stage`, `minutes_recorded`, `gps_validated`, `authority_submission_status` of `PENDING`, and (initially) no `submitted_at`. An `AuditLog` row is written with action `CHECK_OUT`.

**Hour reporting.** A read of the student's hour totals returns three things. First, `totals` — a per-stage map for `THEORY`, `BASIC`, and `HIGHWAY` summing `minutes_recorded` from this student's `TrainingHourRecord` rows for that stage. Second, `totals_validated` — the same per-stage map but restricted to records whose `gps_validated` is `true`. Third, `records` — the `TrainingHourRecord` rows themselves. Submitting hours to the authority is an admin-only batch capability that flips every one of this student's `TrainingHourRecord` rows whose `authority_submission_status` is `PENDING` to `SUBMITTED` and stamps `submitted_at` to the logical clock; one `AuditLog` row with action `SUBMIT_HOURS` covers the operation.

**Exam booking.** An `ExamAppointment` carries `student_id`, `exam_type` (one of `THEORY_TEST`, `BASIC_TEST`, `FINAL_TEST`), `scheduled_at` (the start time; exams are 60 minutes by definition), `examiner_id`, plus the computed fields `passing_score`, `retake_index`, and `prerequisite_stage`. Booking is admin-only. The exam's `prerequisite_stage` is derived from `exam_type`: `THEORY_TEST` requires the student to be at `THEORY`, `BASIC_TEST` at `BASIC`, `FINAL_TEST` at `HIGHWAY`. If the student's `training_stage` does not match the prerequisite, or if the exam is `FINAL_TEST` and `has_passed_basic_practical` is false, the booking is rejected with `ERR_PREREQUISITE_STAGE_NOT_MET`. The `passing_score` is computed from `exam_type`: `THEORY_TEST` requires at least 90, `BASIC_TEST` at least 80, `FINAL_TEST` at least 85. The `retake_index` is the 1-based ordinal among this student's prior `ExamAppointment` rows of the same `exam_type` in any of `BOOKED`, `PASSED`, `FAILED`, `NO_SHOW`, or `CANCELLED` status, assigned at creation time; if assigning would exceed 3 (i.e., the proposed exam would be the 4th attempt at this `exam_type`), the booking is rejected with `ERR_RETAKE_LIMIT_EXCEEDED`.

A second precondition fires at booking time: the **stage minimum hours check**. The stage being attested by the exam is mapped from `exam_type`: `THEORY_TEST` attests `THEORY`, `BASIC_TEST` attests `BASIC`, `FINAL_TEST` attests `HIGHWAY`. The required minutes for that stage are: 0 for `THEORY`, 600 for `BASIC`, and 480 for `HIGHWAY`. The attested minutes are computed as the sum of `minutes_recorded` across this student's `TrainingHourRecord` rows whose `training_stage` equals the attested stage and whose `gps_validated` is `true`. If the attested minutes are strictly less than the required minutes, the booking is rejected with `ERR_STAGE_MIN_HOURS_NOT_MET`. The student's `exam_attempts_remaining` is computed as the package's `included_exam_attempts` minus the count of this student's `ExamAppointment` rows in `BOOKED`, `PASSED`, `FAILED`, or `NO_SHOW` (counting `CANCELLED` does not consume an attempt for this calculation). When `exam_attempts_remaining` is zero at booking time, the booking is rejected with `ERR_NO_EXAM_ATTEMPTS_REMAINING`.

**Recording exam results.** The result-recording capability is examiner-only. The body carries `score`, an integer in 0–100. If the exam is not in `BOOKED`, the request is rejected with `ERR_EXAM_NOT_BOOKABLE`. When `score` is at or above `passing_score`, the exam transitions from `BOOKED` to `PASSED`, and the side-effects cascade onto the student. If `exam_type` is `THEORY_TEST`, `has_passed_theory` becomes `true` and `training_stage` advances from `THEORY` to `BASIC`. If `exam_type` is `BASIC_TEST`, `has_passed_basic_practical` becomes `true` and `training_stage` advances from `BASIC` to `HIGHWAY`. If `exam_type` is `FINAL_TEST`, `training_stage` advances from `HIGHWAY` to `COMPLETED` and the student's `enrollment_status` cascades from `ACTIVE` to `COMPLETED` in the same operation, additionally bulk-submitting all `PENDING` `TrainingHourRecord` rows for this student to `SUBMITTED` as described in §3.1. When `score` is strictly less than `passing_score`, the exam transitions from `BOOKED` to `FAILED` and no student-side cascade fires. In either branch, an `AuditLog` row is written with action `RECORD_RESULT`. An admin may instead cancel a `BOOKED` exam, transitioning it to `CANCELLED`.

**Exam no-show.** The same sweep that handles practice no-show also handles exam no-show: any `BOOKED` exam whose `scheduled_at + 60 + NO_SHOW_GRACE_MINUTES` has elapsed becomes `NO_SHOW`, with an `AuditLog` row recorded for action `NO_SHOW_SWEEP`.

### 3.6. Simulator Sessions and Per-Session Billing

A `SimulatorSession` carries `student_id`, `scheduled_start_at`, `scheduled_end_at`, `status`, `charged_to_package`, and `overage_cents`. Booking is allowed for an Admin or the owning Student. At booking time, the system recomputes `simulator_sessions_remaining` for the student as the package's `included_simulator_sessions` minus the count of this student's `SimulatorSession` rows in `BOOKED` or `COMPLETED` status — counted **before** the new session is persisted. If `simulator_sessions_remaining` is strictly greater than zero, `charged_to_package` is `true` and `overage_cents` is 0; otherwise `charged_to_package` is `false` and `overage_cents` equals the package's `per_simulator_session_overage_price_cents`. After the new session is persisted, `simulator_sessions_remaining` is recomputed and may decrement to zero or remain at zero.

The session's lifecycle is short. An admin marks the session `COMPLETED` after the logical clock has reached or passed `scheduled_start_at`. Either the owning student or an admin may cancel a `BOOKED` session, transitioning it to `CANCELLED`; if the session is not in `BOOKED`, the request is rejected with `ERR_SIMULATOR_NOT_BOOKED`. An expired `BOOKED` session — `scheduled_end_at + NO_SHOW_GRACE_MINUTES` strictly before the logical clock — is transitioned to `NO_SHOW` by the sweep capability described in §3.4.

For end-of-cycle informational accounting, the cycle invoice overage total is the sum of `overage_cents` across this student's `SimulatorSession` rows in `COMPLETED` whose `charged_to_package` is `false` and whose `created_at` is at or after `cycle_start_date`. The per-session amount is rounded with floor before summing — the order is **round-per-session, then sum**, never the reverse. (In practice every `overage_cents` is already an integer, so floor is identity here, but the order is fixed for future invariance.)

### 3.7. Complaints and Multi-Level Response

A `Complaint` carries `student_id`, an optional `instructor_id` (used only when `category` is `INSTRUCTOR_CONDUCT`, and null otherwise), `category` (one of `SCHEDULING`, `INSTRUCTOR_CONDUCT`, `BILLING`, `FACILITY`, `OTHER`), `description`, `level` (initial 1, incremented on each escalation up to a maximum of 3), `status` (initial `OPEN`), `assigned_handler_id`, `assigned_handler_role`, `response_text`, `resolution_summary`, `escalated_at`, and `resolved_at`. Filing a complaint is allowed for a Student (only with `student_id` matching their `X-User-ID`) or for an Admin.

The lifecycle has four phases: `OPEN`, `IN_REVIEW`, optionally `ESCALATED` then back to `IN_REVIEW`, and finally `RESOLVED` or `REJECTED`.

**Assignment.** An admin assigns a handler to an `OPEN` complaint, transitioning it to `IN_REVIEW`. The body carries `handler_id` and `handler_role`. Two referential checks fire here. First, when the complaint's `category` is `INSTRUCTOR_CONDUCT`, `handler_role` must be `Admin` — handing an instructor-conduct complaint to a `ComplaintHandler` is rejected with `ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN`. Second, for any complaint whose current `level` is 3, `handler_role` must be `Admin` — escalated tier-3 complaints are admin-only and a `ComplaintHandler` assignment is rejected with `ERR_LEVEL3_REQUIRES_ADMIN`. Both checks apply at the initial `OPEN → IN_REVIEW` assignment and, equally, at any subsequent `ESCALATED → IN_REVIEW` re-assignment. Side-effects: `assigned_handler_id` and `assigned_handler_role` are set from the body, and an `AuditLog` row is written with action `ASSIGN_HANDLER`. If the complaint's `status` is not in {`OPEN`, `ESCALATED`} at this point, the request is rejected with `ERR_COMPLAINT_NOT_ASSIGNABLE`.

**Escalation.** A `ComplaintHandler` or an `Admin` may escalate an `IN_REVIEW` complaint to `ESCALATED`. The acting handler's `X-User-ID` must equal the complaint's `assigned_handler_id`; otherwise `ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER`. If the complaint's current `level` is already 3, escalation is rejected with `ERR_ESCALATION_LIMIT_REACHED`. Side-effects: `level` increments by 1; `status` becomes `ESCALATED`; `escalated_at` is set to the logical clock; both `assigned_handler_id` and `assigned_handler_role` are cleared so that an admin must re-assign. An `AuditLog` row is written with action `ESCALATE`. If the complaint is not in `IN_REVIEW`, the request is rejected with `ERR_COMPLAINT_NOT_RESOLVABLE`.

**Resolution and rejection.** A `ComplaintHandler` or an `Admin` may move an `IN_REVIEW` complaint to `RESOLVED` (with body `response_text` and `resolution_summary` written onto the complaint, plus `resolved_at` set to the logical clock) or to `REJECTED` (with body `response_text` only, plus `resolved_at` set). In either case the acting handler's `X-User-ID` must equal `assigned_handler_id` (`ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER`), and the complaint must be in `IN_REVIEW` (`ERR_COMPLAINT_NOT_RESOLVABLE`). Audit actions are `RESOLVE` and `REJECT` respectively.

### 3.8. Time Control and Sweep Capabilities

Two admin-only, test-driving capabilities round out the system. The clock-advance capability accepts a body with `minutes` and advances the logical clock by that many minutes; no records are mutated as a direct consequence. The sweep capability is the system actor that performs all four time-driven jobs in a single pass: practice no-show transitions (computed against `scheduled_end_at + NO_SHOW_GRACE_MINUTES`), exam no-show transitions (computed against `scheduled_at + 60 + NO_SHOW_GRACE_MINUTES`), simulator no-show transitions (computed against `scheduled_end_at + NO_SHOW_GRACE_MINUTES`), and cycle resets. Together, they make every time-dependent rule in this document deterministic and replayable.

### 3.9. Read Endpoints and Audit Trail

All entity read endpoints respect the same ownership rules as the corresponding mutation endpoints: a `Student` may read only their own profile, their own appointments, their own simulator sessions, their own exams, their own complaints, and their own training-hour totals; an `Instructor` may read only their own profile and the practice appointments where they are the assigned instructor. An `Admin` may read anything. Audit logs are admin-only and accept query-string filters `entity_type` and `entity_id` along with pagination.

## 4. Endpoint Definitions

POST endpoints that create a new resource return HTTP 201; POST endpoints that mutate an existing resource return HTTP 200; GET endpoints return HTTP 200. Error responses use the HTTP statuses listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /students | Enroll a student (`PENDING_VERIFICATION`) | Admin |
| GET | /students/{id} | Get student | Admin, Student |
| POST | /students/{id}/verify-identity | Identity verification (`PENDING_VERIFICATION → PENDING_MEDICAL`) | Admin |
| POST | /students/{id}/submit-medical-cert | Validate medical cert (`PENDING_MEDICAL → PENDING_PACKAGE`) | Admin |
| POST | /students/{id}/select-package | Select course package (`PENDING_PACKAGE → PENDING_CONTRACT`) | Admin |
| POST | /students/{id}/sign-contract | Sign contract & pay (`PENDING_CONTRACT → ACTIVE`) | Admin |
| POST | /students/{id}/suspend | Admin suspend (`ACTIVE → SUSPENDED`) | Admin |
| POST | /students/{id}/reinstate | Reinstate (`SUSPENDED → ACTIVE`) | Admin |
| GET | /students/{id}/training-hours | Per-stage hour totals plus the `TrainingHourRecord` rows | Admin, Student |
| POST | /students/{id}/submit-hours-to-authority | Submit all `PENDING` `TrainingHourRecord` rows | Admin |
| POST | /instructors | Create instructor | Admin |
| GET | /instructors/{id} | Get instructor | Admin, Instructor |
| POST | /instructors/{id}/suspend | Suspend instructor (`ACTIVE → SUSPENDED`) | Admin |
| POST | /instructors/{id}/reinstate | Reinstate instructor (`SUSPENDED → ACTIVE`) | Admin |
| POST | /vehicles | Create vehicle | Admin |
| GET | /vehicles/{id} | Get vehicle | Admin |
| POST | /vehicles/{id}/set-maintenance | Move vehicle to `MAINTENANCE` | Admin |
| POST | /vehicles/{id}/restore-active | Restore vehicle to `ACTIVE` | Admin |
| POST | /course-packages | Create course package | Admin |
| GET | /course-packages/{id} | Get course package | Admin, Student |
| POST | /practice-appointments | Book a practice slot | Admin, Student |
| GET | /practice-appointments/{id} | Get practice appointment | Admin, Student, Instructor |
| POST | /practice-appointments/{id}/cancel | Cancel a `BOOKED` appointment | Admin, Student |
| POST | /practice-appointments/{id}/check-in | Instructor check-in (`BOOKED → IN_PROGRESS`) | Instructor, Admin |
| POST | /practice-appointments/{id}/check-out | Instructor check-out (`IN_PROGRESS → COMPLETED`) | Instructor, Admin |
| POST | /practice-appointments/{id}/reschedule | Atomic cancel + new booking | Admin, Student |
| POST | /exam-appointments | Book an exam | Admin |
| GET | /exam-appointments/{id} | Get exam appointment | Admin, Student, Examiner |
| POST | /exam-appointments/{id}/record-result | Record exam result (`BOOKED → PASSED` or `BOOKED → FAILED`) | Examiner |
| POST | /exam-appointments/{id}/cancel | Cancel exam (`BOOKED → CANCELLED`) | Admin |
| POST | /simulator-sessions | Book a simulator session | Admin, Student |
| POST | /simulator-sessions/{id}/cancel | Cancel simulator (`BOOKED → CANCELLED`) | Admin, Student |
| POST | /simulator-sessions/{id}/complete | Mark simulator complete (`BOOKED → COMPLETED`) | Admin |
| POST | /complaints | File a complaint | Student, Admin |
| GET | /complaints/{id} | Get complaint | Admin, Student, ComplaintHandler |
| POST | /complaints/{id}/assign-handler | Assign handler (`OPEN → IN_REVIEW` or `ESCALATED → IN_REVIEW`) | Admin |
| POST | /complaints/{id}/escalate | Escalate (`IN_REVIEW → ESCALATED`) | ComplaintHandler, Admin |
| POST | /complaints/{id}/resolve | Resolve (`IN_REVIEW → RESOLVED`) | ComplaintHandler, Admin |
| POST | /complaints/{id}/reject | Reject (`IN_REVIEW → REJECTED`) | ComplaintHandler, Admin |
| GET | /audit-logs | List audit logs (filterable by `entity_type` and `entity_id`) | Admin |
| POST | /_clock/advance | Advance the logical clock by `minutes` | Admin |
| POST | /_sweep/run | Run all time-driven sweeps | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_INSTRUCTOR_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_PRACTICE_NOT_FOUND | 404 |
| ERR_EXAM_NOT_FOUND | 404 |
| ERR_SIMULATOR_NOT_FOUND | 404 |
| ERR_COMPLAINT_NOT_FOUND | 404 |
| ERR_FORBIDDEN_NOT_OWNER | 403 |
| ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR | 403 |
| ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER | 403 |
| ERR_INSTRUCTOR_NOT_QUALIFIED | 400 |
| ERR_VEHICLE_TYPE_MISMATCH | 400 |
| ERR_PREREQUISITE_STAGE_NOT_MET | 400 |
| ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN | 400 |
| ERR_LEVEL3_REQUIRES_ADMIN | 400 |
| ERR_STUDENT_NOT_ACTIVE | 409 |
| ERR_STUDENT_NOT_AT_PENDING_STATE | 409 |
| ERR_INSTRUCTOR_NOT_ACTIVE | 409 |
| ERR_VEHICLE_NOT_ACTIVE | 409 |
| ERR_APPOINTMENT_NOT_CANCELLABLE | 409 |
| ERR_APPOINTMENT_NOT_CHECK_INNABLE | 409 |
| ERR_APPOINTMENT_NOT_CHECK_OUTTABLE | 409 |
| ERR_EXAM_NOT_BOOKABLE | 409 |
| ERR_SIMULATOR_NOT_BOOKED | 409 |
| ERR_COMPLAINT_NOT_ASSIGNABLE | 409 |
| ERR_COMPLAINT_NOT_RESOLVABLE | 409 |
| ERR_MEDICAL_CERT_EXPIRED | 409 |
| ERR_INSTRUCTOR_TIME_CONFLICT | 409 |
| ERR_VEHICLE_TIME_CONFLICT | 409 |
| ERR_OUTSIDE_CHECK_IN_WINDOW | 409 |
| ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED | 403 |
| ERR_INSTRUCTOR_WEEKLY_LIMIT_EXCEEDED | 403 |
| ERR_INSTRUCTOR_NEEDS_REST | 403 |
| ERR_RESCHEDULE_LIMIT_EXCEEDED | 409 |
| ERR_RETAKE_LIMIT_EXCEEDED | 409 |
| ERR_ESCALATION_LIMIT_REACHED | 409 |
| ERR_STAGE_MIN_HOURS_NOT_MET | 409 |
| ERR_INSUFFICIENT_PACKAGE_BALANCE | 402 |
| ERR_NO_EXAM_ATTEMPTS_REMAINING | 402 |
| ERR_STALE_DATA | 409 |
