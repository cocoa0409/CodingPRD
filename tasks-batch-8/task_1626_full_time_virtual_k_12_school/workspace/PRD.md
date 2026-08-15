# Full-Time Virtual K-12 School API — Product Requirements Document

## 1. Introduction

Public virtual schools operate under a funding and compliance model unlike any brick-and-mortar district: state dollars follow the student's district of residence, attendance must be evidenced through live online instruction and platform engagement rather than a physical roll call, and state-mandated assessments must still be proctored in person at physical sites. Operating such a school means reconciling enrollment caps negotiated with each funding district, interstate teacher certification rules, special-education service obligations, and truancy law — all against a student body that may withdraw, and thereby trigger funding proration, on any day of the school year.

This document specifies the Full-Time Virtual K-12 School API, the system of record for one such school. The API governs the complete operational lifecycle: residency-based enrollment eligibility under per-district funding caps; enrollment terms and the withdrawal-time proration that determines how many days of per-pupil funding the school may claim; device and internet stipends with issuance, return, and forfeiture handling; daily synchronous-attendance capture and rolling truancy determination; teacher registration and assignment under certification and caseload constraints; proctored assessment windows, test-site capacity, and seat booking; and online delivery of special-education services. All resources are mounted under the `/vks` prefix. The audience is the engineering team building the service; every rule stated below is normative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly six roles, spelled as follows: `PlatformAdmin`, `EnrollmentOfficer`, `FinanceOfficer`, `AcademicDirector`, `ProctorCoordinator`, and `SpecialEdCoordinator`.

For every one of these roles — `PlatformAdmin`, `EnrollmentOfficer`, `FinanceOfficer`, `AcademicDirector`, `ProctorCoordinator`, and `SpecialEdCoordinator` — the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server never compares it against any resource's `id`; authorization in this system is purely role-based, and there are no per-resource ownership checks.

Each role carries a distinct portfolio. A `PlatformAdmin` holds the superset of permissions: it alone manages districts and the logical clock, and it shares in several registration and read operations. An `EnrollmentOfficer` handles student applications, residency verification, enrollment, withdrawal, re-enrollment, attendance recording, and the excusing of absences. A `FinanceOfficer` issues device and internet stipends and processes their returns; it cannot enroll students or manage teachers. An `AcademicDirector` registers teachers and manages teacher-to-student assignments; it cannot touch stipends or proctoring. A `ProctorCoordinator` schedules assessment windows, registers test sites, and books and marks proctor assignments. A `SpecialEdCoordinator` schedules, delivers, marks missed, cancels, and reschedules special-education service sessions.

A request missing either header, carrying an empty `X-User-ID`, or naming a role outside the six above is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return: if not provided it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. Many list endpoints additionally accept resource-specific filters — for example `state_code` on district and test-site lists, or `enrollment_status` on the student list; each filter is described alongside its workflow in §3.

### 2.4. Common Resource Properties

Every resource in the system — districts, students, enrollment terms, stipends, teachers, teacher assignments, attendance records, assessment windows, test sites, proctor assignments, and service deliveries — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T00:00:00.000Z`), set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed whenever any property of the resource changes.
- `version` (integer): a system-managed integer that increments with every modification to the resource — including the state transitions and derived-field recomputations described throughout §3.

Date-valued fields such as birthdays, term boundaries, and attendance days are represented as ISO 8601 dates at midnight UTC unless a field is described as carrying a full timestamp.

### 2.5. The Logical School Clock

The system runs on a logical clock rather than wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to real wall-clock time. Every automatic transition, every derived date — enrollment term start dates, withdrawal end dates, stipend return deadlines — and every temporal validation is evaluated against this logical clock.

A `PlatformAdmin` may advance the clock through a dedicated administrative capability, passing the target instant as `to_iso8601`; the response echoes the server's new position as `current_utc`. Setting the clock triggers a sweep of pending time-driven transitions: any assessment window whose `window_start` has been reached or passed moves from `SCHEDULED` to `OPEN`; any open window whose `window_end` is now strictly in the past moves from `OPEN` to `CLOSED`, cascading its still-booked seats to no-shows as §3.7 describes; and any device stipend still awaiting hardware return whose `return_due_date` has passed is forfeited, as §3.4 describes.

### 2.6. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for requests that target nested resources. When an endpoint path contains one or more resource identifiers — including nested shapes such as a student's stipends or a window's bookings — the system validates the existence of each identifier in sequential, left-to-right order along the path. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, before any business rule is evaluated.

### 2.7. Validation Cascade and Error Precedence

Every request is validated against an ordered cascade, and the first failing check determines the response — later checks are not evaluated once an earlier one has failed. The cascade order is:

1. **Authentication.** The `X-User-Role` header must be present and hold one of the six declared roles, and `X-User-ID` must be present and non-empty; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** The acting role must appear in the endpoint's authorized role list; otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. **Path existence.** Every identifier in the path must resolve to an existing entity, validated left to right; otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **Body references.** Every foreign-key field in the request body — `district_of_residence_id`, `teacher_id`, `student_id`, `test_site_id`, `assessment_window_id`, and `provider_id` — must resolve to an existing entity; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **State admissibility.** The target entity must be in a state that admits the requested transition. This stage also covers the enrollment-dependent creation rules: scheduling a special-education session, issuing a stipend, creating a teacher assignment, and booking a proctored seat each require the referenced student to be `ENROLLED`. Violations yield `ERR_INVALID_STATE` (HTTP 409).
6. **Concurrency.** On the two optimistic-concurrency-guarded writes described in §2.9, a stale client view is rejected with `ERR_STALE_VERSION` (HTTP 412).
7. **Business rules.** Certification, capacity, temporal, uniqueness, funding-cap, and special-education rules, each paired with its own error code in §3. Where several business rules guard the same endpoint, their relative order is stated with the workflow — certification always reports ahead of capacity, and seat availability ahead of window timing.
8. **Input shape.** Only after all of the above pass does the server validate structural input: required fields present, enum values within their declared sets, and numeric ranges honored. Violations yield `ERR_INVALID_REQUEST` (HTTP 400).

This ordering is normative: a request that is both unauthorized and malformed is answered with `ERR_UNAUTHORIZED`, and a request against a missing resource with a stale version is answered with `ERR_NOT_FOUND`.

### 2.8. Funding Arithmetic and Precision

All monetary quantities are integer cents, never fractional: the district's per-pupil `funding_rate_cents`, a stipend's `amount_cents` and `clawback_cents`, and the student's aggregate `funding_claim_cents` are all integers. Day counts, minute counts, check-in counts, seat counts, and caseload counts are likewise integers. No rounding is applied anywhere in the funding pipeline: each term's claim is formed by multiplying integer days by the integer cent rate, and the per-term results are then summed (§3.3). Boolean determinations such as the truancy flag are derived from inclusive integer thresholds, stated with their workflows.

### 2.9. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

The first guarded write is student enrollment. The request must carry `expected_student_version`, holding the student's `version` as the client last observed it. If the value does not match the student's current `version` — because a residency verification, a withdrawal, or any other mutation has advanced the record since the client read it — the enrollment is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never enrolls a student record it has not observed.

The second guarded write is proctored-seat booking. The request must carry `expected_test_site_version`, holding the test site's `version` as the client last observed it. A mismatch with the site's current `version` — for example because another booking or a cancellation has moved `seats_booked` since the client read the site — is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Derived Fields and Reconciliation

A number of fields are maintained exclusively by the server and are never accepted from clients: attendance determinations, the truancy counters `truancy_unexcused_count` and `truancy_flag`, the funding totals `funding_days_claimed` and `funding_claim_cents`, a term's `claimable_days` and `proration_mode`, a stipend's `issued_at`, `return_due_date`, and `clawback_cents`, a teacher's `current_caseload`, and a site's `seats_booked`. Each derived value is recomputed at the event described with its workflow in §3, and each recomputation is a mutation of the owning record that refreshes its `updated_at`. The funding claim in particular is re-derived on read whenever the underlying term days or the district's funding rate have changed, so readers always see the claim valued at the rate in effect at computation time.

## 3. Business Logic & Workflows

### 3.1. Districts and the Per-Pupil Funding Framework

Every funding relationship begins with a district. A `PlatformAdmin` registers each district with its `district_code` — the unique code assigned by the state, which must be unique across all districts and is immutable once registered — together with the district's `state_code` (a two-letter uppercase US state code), its `funding_rate_cents`, and its `enrollment_cap`. The funding rate is the per-pupil daily amount, in cents, that the school claims from that district for each claimable day of a resident student's enrollment, and it must be at least one cent. The cap is the maximum number of resident students whose funding the district will cover in a school year: a non-negative integer, where zero is a legitimate registration meaning the district funds no students at all.

District records are readable by every role, and the district list can be filtered by `state_code`. A district registered with an `enrollment_cap` of zero simply refuses every residency verification and enrollment attempted against it, as the next subsection describes.

### 3.2. Application, Residency Verification, and Enrollment

An `EnrollmentOfficer` — or a `PlatformAdmin` acting in that capacity — opens a student application with the child's `legal_name`, `date_of_birth` (an ISO 8601 date at midnight UTC), `grade_level`, and `district_of_residence_id`; a `special_education_flag` may be supplied and defaults to `false` when omitted. Grade placement runs from 0, meaning kindergarten, through 12, and anything outside that range is rejected with `ERR_INVALID_REQUEST`. The referenced district must exist, or the request fails with `ERR_NOT_FOUND`. A fresh application lands in `APPLIED` status: `residency_verified_at` is null, `funding_days_claimed` and `funding_claim_cents` are zero, and the truancy counters `truancy_unexcused_count` and `truancy_flag` start at zero and false. The student directory is listable by all roles and can be filtered by `district_of_residence_id`, `enrollment_status`, and `truancy_flag`.

Residency verification, performed by an `EnrollmentOfficer`, moves a student from `APPLIED` to `ELIGIBLE`. Three conditions gate the move: the district referenced by the student's `district_of_residence_id` must still exist (`ERR_NOT_FOUND` otherwise), the student must currently be `APPLIED` (any other status is `ERR_INVALID_STATE`), and the district of residence must still have an open slot. A district has an open slot while the number of its students currently in `ELIGIBLE` or `ENROLLED` status is strictly less than its `enrollment_cap`; attempting to verify one more student once that count has reached the cap is rejected with `ERR_DISTRICT_CAP_REACHED`. On success the server stamps `residency_verified_at` with the current logical-clock time and increments the student's `version`.

Enrollment, again an `EnrollmentOfficer` action, admits a student into active status — from `ELIGIBLE` to `ENROLLED`, and, on the re-enrollment path described below, from `REENROLL_PENDING` to `ENROLLED`. Enrollment is one of the two optimistic-concurrency-guarded writes in the system (§2.9): the request must carry `expected_student_version` matching the student's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Three gates guard the transition, evaluated in order: the student's status must admit enrollment (`ERR_INVALID_STATE`), the supplied version must match (`ERR_STALE_VERSION`), and the district must still have an open slot under the same cap rule as verification (`ERR_DISTRICT_CAP_REACHED`).

A successful enrollment opens a new **enrollment term**: an `EnrollmentTerm` is created for the student with `term_start_date` set to the current logical-clock date and `term_status` set to `ACTIVE`; `term_end_date` and `proration_mode` remain null while the term is open, and `claimable_days` starts at zero. Entering `ENROLLED` also resets the student's rolling truancy window — `truancy_unexcused_count` returns to zero and `truancy_flag` clears — and the student's `version` increments. Terms are readable per student or individually by `PlatformAdmin`, `EnrollmentOfficer`, and `FinanceOfficer`. A term's `term_status` is always one of `ACTIVE`, `WITHDRAWN`, or `COMPLETED`; enrollment creates `ACTIVE` terms, and withdrawal, covered next, moves the open term to `WITHDRAWN`.

When a withdrawn family wishes to return, an `EnrollmentOfficer` can move a `WITHDRAWN` student to `REENROLL_PENDING` — a request against any other status fails with `ERR_INVALID_STATE` — which records the intent to return and increments the student's `version`. A subsequent enrollment call then moves the student from `REENROLL_PENDING` back to `ENROLLED` under exactly the same three gates as a first enrollment, opening a fresh `ACTIVE` term. Prior terms remain on the student's record and continue to contribute their computed days to the funding totals described next.

### 3.3. Withdrawal, Proration, and the District Funding Claim

Withdrawal is the most consequential operation in the system. An `EnrollmentOfficer` withdraws a student by supplying a `withdrawal_reason` — one of `MOVED_DISTRICT`, `RETURN_TO_BRICK_AND_MORTAR`, `HOMESCHOOL`, `DROPOUT`, or `ADMINISTRATIVE`; a missing or unrecognized reason is rejected with `ERR_INVALID_REQUEST`. The student must be `ENROLLED` and their current term must be `ACTIVE`, or the request fails with `ERR_INVALID_STATE`. On success the student becomes `WITHDRAWN` — the terminal enrollment status — and a single atomic cascade runs.

First, the books are closed on the open term. The term's `term_status` becomes `WITHDRAWN`, and its `term_end_date` is set to the day before the withdrawal: the current logical-clock date minus one day. Both endpoints of the claimable span are therefore inclusive school days. The recorded reason then selects the proration variant deterministically: `DROPOUT` and `ADMINISTRATIVE` map to `DAILY_ATTENDANCE`, while `MOVED_DISTRICT`, `RETURN_TO_BRICK_AND_MORTAR`, and `HOMESCHOOL` map to `CALENDAR_ELAPSED`, and the chosen variant is stored on the term as `proration_mode`. Under `CALENDAR_ELAPSED`, the term's `claimable_days` is the count of calendar days from `term_start_date` through `term_end_date` inclusive — never less than zero — regardless of what the attendance record shows. Under `DAILY_ATTENDANCE`, `claimable_days` counts only those days within that same inclusive span on which the student has an attendance record marked `PRESENT` or `PARTIAL`; days marked `ABSENT_UNEXCUSED` or `ABSENT_EXCUSED`, and days with no record at all, are excluded. Day arithmetic is integer arithmetic with no rounding. Should the recorded `withdrawal_reason` be corrected before the term is finalized, the mode selection and the claimable-day computation are re-evaluated under the corrected reason.

With the term's days settled, the student's funding totals are recomputed. `funding_days_claimed` becomes the sum of `claimable_days` across all of the student's terms, whatever their status. `funding_claim_cents` is computed per term first — each term's `claimable_days` multiplied by the district's `funding_rate_cents` as it stands at computation time — and the per-term amounts are then summed into the student's total. The alternative order, summing days across terms and multiplying once, is expressly forbidden, and all arithmetic remains in integer cents. The same recomputation runs whenever any term's `claimable_days` changes or a new term is created, and when a district's rate has changed the claim is re-derived on read at the current rate.

The cascade then reaches every open obligation attached to the student. Each `DEVICE` stipend still `ISSUED` flips to `RETURN_REQUESTED`, with `return_due_date` set thirty days out from the current logical-clock date. Each `INTERNET` stipend still `ISSUED` is forfeited on the spot — `FORFEITED` with `clawback_cents` set to zero, because internet stipends are never clawed back. Every teacher assignment still `ASSIGNED` for the student ends: its `assignment_status` becomes `ENDED`, its `ended_at` is stamped from the clock, and the affected teacher's `current_caseload` drops by one. Every proctor booking still `BOOKED` in the student's name is `CANCELLED`, releasing the seat so the site's `seats_booked` drops by one. Every special-education session still `SCHEDULED` is `CANCELLED`. Each cascaded record is itself mutated — its `version` increments and its `updated_at` refreshes — and the student's own `version` increments as part of the same operation.

### 3.4. Device and Internet Stipends

Stipends fund the hardware and connectivity a virtual student needs at home. A `FinanceOfficer` requests a stipend for a student by supplying the `student_id`, a `stipend_type` of `DEVICE` or `INTERNET`, and the `amount_cents` to be disbursed — a non-negative integer, with anything negative rejected as `ERR_INVALID_REQUEST`. A new request sits in `REQUESTED` status with `issued_at` null and `clawback_cents` zero; `return_due_date` is null at creation and remains null throughout the life of an internet stipend, since connectivity funding has no hardware to recover.

Issuance, also a `FinanceOfficer` action, moves a stipend from `REQUESTED` to `ISSUED`. Two state-level conditions apply first: the stipend itself must be `REQUESTED`, and the student it belongs to must currently be `ENROLLED` — violations of either are `ERR_INVALID_STATE`. Only after those pass does the uniqueness rule apply: no other stipend for the same student and the same `stipend_type` may be in `REQUESTED`, `ISSUED`, or `RETURN_REQUESTED`, so a second live stipend of one type is rejected with `ERR_DUPLICATE_ACTIVE_STIPEND`. Successful issuance stamps `issued_at` from the logical clock and increments the stipend's `version`.

The return pipeline for hardware begins when a student withdraws: as §3.3 describes, withdrawal moves every issued device stipend to `RETURN_REQUESTED` with a thirty-day return deadline. When the family sends the device back, a `FinanceOfficer` marks the stipend returned, moving it from `RETURN_REQUESTED` to `RETURNED` with `clawback_cents` set to zero and the `version` incremented. If instead the logical-clock date moves past the `return_due_date` while the stipend is still `RETURN_REQUESTED`, the stipend is forfeited automatically: its `issue_status` becomes `FORFEITED`, `clawback_cents` is set to the full `amount_cents` originally issued, and the stipend's `version` increments. `RETURNED` and `FORFEITED` are the terminal stipend states. A student's stipends are listable by `PlatformAdmin`, `FinanceOfficer`, and `EnrollmentOfficer`, with an `issue_status` filter available.

### 3.5. Attendance, Engagement, and Truancy

Attendance in a virtual school is evidenced, not observed. An `EnrollmentOfficer` — or a `PlatformAdmin` — records each school day with the `student_id`, the `attendance_date` (an ISO 8601 date at midnight UTC), the day's `synchronous_minutes` spent in live class sessions, and the day's `engagement_check_ins`, the count of engagement events such as logins, LMS activity, and assignment submissions. Both counts are non-negative integers; negative values are rejected with `ERR_INVALID_REQUEST`.

From these two inputs the server derives the day's `attendance_status` at creation time. A day with at least 240 synchronous minutes — a full four-hour instructional day — and at least 2 engagement check-ins is `PRESENT`. Failing that, a day with at least 120 synchronous minutes (a half day of live instruction) or at least 2 check-ins is `PARTIAL`. Anything else is `ABSENT_UNEXCUSED`. All thresholds are inclusive: exactly 240 minutes with exactly 2 check-ins earns `PRESENT`, and exactly 120 minutes with no check-ins at all still earns `PARTIAL`. The fourth status value, `ABSENT_EXCUSED`, is never assigned at creation — it is reachable only through the excusal flow below — and a record's `excused_reason` stays null until an excusal writes it.

Truancy is tracked on a rolling window over the student's record history. The window covers the ten most recent school days on which the student has an attendance record — recency is measured by count of records, not by calendar span — and the window's cutoff is the date of the tenth most recent record, inclusive. A student with fewer than ten records simply has every record inside the window. `truancy_unexcused_count` is the number of `ABSENT_UNEXCUSED` records falling within the window, and the boolean `truancy_flag` follows an inclusive threshold: when the count reaches 3 unexcused days the flag turns true — exactly three unexcused days in the window constitutes truancy — and it returns to false whenever the count is below that. Recording a new day that comes out `ABSENT_UNEXCUSED` immediately recomputes both values, and enrollment resets them, as §3.2 notes.

Excusal converts an absence to an excused one. An `EnrollmentOfficer` supplies a free-text `excused_reason`, and the record moves to `ABSENT_EXCUSED` — a transition admitted from `PRESENT`, from `PARTIAL`, and from `ABSENT_UNEXCUSED` alike, and rejected with `ERR_INVALID_STATE` from any other status. The reason is stored on the record, the record's `version` increments, and the student's truancy counters are recomputed. Excusing an `ABSENT_UNEXCUSED` record drops the window count by one and can clear `truancy_flag` when the count falls below the threshold; excusing a `PRESENT` or `PARTIAL` record leaves the unexcused count unchanged, since those statuses never contributed to it. A student's attendance history is listable by `PlatformAdmin` and `EnrollmentOfficer` with an `attendance_status` filter.

### 3.6. Teacher Registration, Certification, and Caseload

An `AcademicDirector` — or a `PlatformAdmin` — registers each teacher with a `full_name`, a `certification_state_codes` array listing the two-letter codes of the states in which the teacher holds a valid K-12 teaching certificate, and a `caseload_cap` of at least one. The teacher's `current_caseload` is never written directly: it is the count of that teacher's assignments currently in `ASSIGNED` status. A teacher's `teacher_status` begins `ACTIVE` — its only other value is `INACTIVE` — and records whether the teacher is currently employable for assignment.

Assigning a teacher to a student is an `AcademicDirector` action naming the `teacher_id`, the `student_id`, and a `subject` of `ELA`, `MATH`, `SCIENCE`, `SOCIAL_STUDIES`, or `SPECIAL_ED`. The checks run in a fixed order. The referenced teacher and student must exist (`ERR_NOT_FOUND`). The student must be `ENROLLED` (`ERR_INVALID_STATE`). Interstate certification comes next: the `state_code` of the student's district of residence must appear among the teacher's `certification_state_codes`, or the request fails with `ERR_TEACHER_NOT_CERTIFIED_IN_STATE` — and because this certification check runs ahead of the caseload check, an uncertified teacher is reported as uncertified even when the caseload is also full. Capacity is the final gate: the teacher's `current_caseload` plus the proposed assignment must not exceed the `caseload_cap`, so filling the cap exactly is allowed while one assignment beyond it is rejected with `ERR_CASELOAD_EXCEEDED`. A successful assignment starts in `ASSIGNED` status with `assigned_at` stamped from the logical clock and `ended_at` null for as long as the assignment remains live; the teacher's `current_caseload` rises by one.

Ending an assignment, again an `AcademicDirector` action, moves it from `ASSIGNED` to `ENDED` — the terminal assignment state — stamping `ended_at` from the clock, dropping the teacher's `current_caseload` by one, and incrementing the assignment's `version`. Student withdrawal ends every live assignment of that student through the same mechanics, as §3.3's cascade describes. Assignment listings exist per teacher and per student, and both accept an `assignment_status` filter.

### 3.7. Proctored Assessments: Windows, Sites, and Seat Booking

State-mandated testing pulls virtual students back into physical rooms, and three record types coordinate it. A `ProctorCoordinator` — or a `PlatformAdmin` — schedules an **assessment window** with an `assessment_name`, a `subject` of `ELA`, `MATH`, or `SCIENCE`, and the `window_start` and `window_end` instants; the end must be strictly after the start, or the request is `ERR_INVALID_REQUEST`. A new window is `SCHEDULED`. When the logical clock reaches or passes `window_start`, the window moves automatically from `SCHEDULED` to `OPEN`; when the clock moves strictly past `window_end`, the window moves from `OPEN` to `CLOSED`, and every proctor assignment still `BOOKED` at that moment is marked `NO_SHOW`. Both automatic moves increment the window's `version`. `CLOSED` is the terminal window state, and the window list accepts a `window_status` filter.

Test sites are the physical counterpart. A `ProctorCoordinator` — or a `PlatformAdmin` — registers each site with its `site_name`, the `state_code` where it is located, and a `seat_capacity` of at least one proctored seat per window. A site's `seats_booked` is derived: the count of proctor assignments currently `BOOKED` at that site. The site list can be filtered by `state_code`.

Booking a seat is a `ProctorCoordinator` action carrying the `student_id`, the `assessment_window_id`, the `test_site_id`, and — as the system's second optimistic-concurrency guard (§2.9) — `expected_test_site_version`, which must match the site's current `version`. A site whose version has advanced since the client last read it rejects the booking with `ERR_STALE_VERSION` (HTTP 412). The remaining checks run in order after existence of all three referenced records is confirmed (`ERR_NOT_FOUND`): the student must be `ENROLLED` (`ERR_INVALID_STATE`); the version must match; a seat must be free — `seats_booked` plus the new booking must not exceed `seat_capacity`, so the final seat may be taken but never one more, with overflow rejected as `ERR_NO_SEAT_AVAILABLE`; and the window must be bookable, which means `SCHEDULED` or `OPEN` — booking ahead of a window's opening is expressly allowed, while booking against a `CLOSED` window fails with `ERR_ASSESSMENT_WINDOW_NOT_OPEN`. A successful booking lands in `BOOKED` status with `booked_at` stamped from the clock, raises the site's `seats_booked` by one, and increments the site's `version`.

From `BOOKED` there are exactly three exits, and all three landing states — `COMPLETED`, `NO_SHOW`, and `CANCELLED` — are terminal. A `ProctorCoordinator` marks a booking completed — `completed_at`, null since booking, is stamped from the clock — only while its window is `OPEN`; completion attempts against a window in any other state are rejected with `ERR_ASSESSMENT_WINDOW_NOT_OPEN`. Cancelling a booking releases the seat, dropping the site's `seats_booked` by one; student withdrawal cancels all of the student's outstanding bookings through the same release, per §3.3. The third exit is the window-close sweep described above, which strands unclaimed bookings as `NO_SHOW`. Each of these moves increments the assignment's `version`. Bookings are listable per window, per site, and per student, and each list accepts an `assignment_status` filter.

### 3.8. Special-Education Service Delivery

Students with an active IEP receive their related services online, and each session is tracked as a **service delivery**. A `SpecialEdCoordinator` schedules a session with the `student_id`, a `service_type` of `SPEECH_THERAPY`, `OCCUPATIONAL_THERAPY`, `COUNSELING`, or `RESOURCE_ROOM`, the `scheduled_at` instant, a `duration_minutes` of at least fifteen, and the `provider_id` of the teacher or related-service provider who will deliver it. Validation runs in order: the referenced student and provider must exist (`ERR_NOT_FOUND`); the student must be `ENROLLED` (`ERR_INVALID_STATE`); the provider's `certification_state_codes` must include the `state_code` of the student's district of residence, or the request fails with `ERR_PROVIDER_NOT_CERTIFIED_IN_STATE`; and the student's `special_education_flag` must be true, or the request fails with `ERR_NOT_SPECIAL_ED_STUDENT`. The certification rule reports ahead of the flag rule, so an out-of-state provider is named as such even when the student is also not flagged. A new session is `SCHEDULED` with `delivered_at` null.

Four actions move a session through its life, all performed by a `SpecialEdCoordinator`. Marking a session delivered moves it from `SCHEDULED` to `DELIVERED` and stamps `delivered_at` from the clock; the student must still be `ENROLLED` at that moment, or the action fails with `ERR_INVALID_STATE`. Marking a session missed moves it from `SCHEDULED` to `MISSED`, but only once the logical clock has moved strictly past the end of the scheduled session — the `scheduled_at` instant plus the planned `duration_minutes`; an earlier attempt is rejected with `ERR_MARK_MISSED_TOO_EARLY`. Cancelling moves a `SCHEDULED` session to `CANCELLED`, and student withdrawal cancels all of the student's scheduled sessions through the same transition, per §3.3. A `MISSED` session can be brought back: rescheduling takes a new `scheduled_at` that must lie strictly in the future relative to the logical clock — anything else is `ERR_SCHEDULE_TIME_IN_PAST` — writes the new time over the old, and returns the session to `SCHEDULED`. Each of these transitions increments the delivery's `version`. `DELIVERED` and `CANCELLED` are terminal; `MISSED` is not, since rescheduling reopens it. Sessions are listable per student and per provider, and both lists accept a `delivery_status` filter.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the administrative clock setting — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vks/_clock/set_current_utc` | Set the server's logical clock and fire pending time-driven transitions | PlatformAdmin |
| POST | `/vks/districts` | Register a district | PlatformAdmin |
| GET | `/vks/districts/{id}` | Fetch a district by id | PlatformAdmin, EnrollmentOfficer, FinanceOfficer, AcademicDirector, ProctorCoordinator, SpecialEdCoordinator |
| GET | `/vks/districts` | List districts with pagination | PlatformAdmin, EnrollmentOfficer, FinanceOfficer, AcademicDirector, ProctorCoordinator, SpecialEdCoordinator |
| POST | `/vks/students` | Create a student application | EnrollmentOfficer, PlatformAdmin |
| GET | `/vks/students/{id}` | Fetch a student by id | PlatformAdmin, EnrollmentOfficer, FinanceOfficer, AcademicDirector, ProctorCoordinator, SpecialEdCoordinator |
| GET | `/vks/students` | List students with pagination | PlatformAdmin, EnrollmentOfficer, FinanceOfficer, AcademicDirector, ProctorCoordinator, SpecialEdCoordinator |
| POST | `/vks/students/{id}/verify-residency` | Verify residency and move the student from APPLIED to ELIGIBLE | EnrollmentOfficer |
| POST | `/vks/students/{id}/enroll` | Enroll a student (ELIGIBLE or REENROLL_PENDING to ENROLLED); OCC-guarded on the student version | EnrollmentOfficer |
| POST | `/vks/students/{id}/withdraw` | Withdraw a student, cascading stipends, assignments, bookings, and sessions, and compute funding proration | EnrollmentOfficer |
| POST | `/vks/students/{id}/request-reenrollment` | Move a WITHDRAWN student to REENROLL_PENDING | EnrollmentOfficer |
| GET | `/vks/students/{id}/enrollment-terms` | List the enrollment terms of a student | PlatformAdmin, EnrollmentOfficer, FinanceOfficer |
| GET | `/vks/enrollment-terms/{id}` | Fetch one enrollment term | PlatformAdmin, EnrollmentOfficer, FinanceOfficer |
| POST | `/vks/stipends` | Request a stipend for a student | FinanceOfficer |
| GET | `/vks/stipends/{id}` | Fetch one stipend | PlatformAdmin, FinanceOfficer, EnrollmentOfficer |
| GET | `/vks/students/{id}/stipends` | List the stipends of a student | PlatformAdmin, FinanceOfficer, EnrollmentOfficer |
| POST | `/vks/stipends/{id}/issue` | Issue a REQUESTED stipend | FinanceOfficer |
| POST | `/vks/stipends/{id}/mark-returned` | Mark a RETURN_REQUESTED device stipend as returned | FinanceOfficer |
| POST | `/vks/teachers` | Register a teacher | AcademicDirector, PlatformAdmin |
| GET | `/vks/teachers/{id}` | Fetch a teacher | PlatformAdmin, AcademicDirector, SpecialEdCoordinator, EnrollmentOfficer |
| GET | `/vks/teachers` | List teachers with pagination | PlatformAdmin, AcademicDirector, SpecialEdCoordinator, EnrollmentOfficer |
| POST | `/vks/teacher-assignments` | Assign a teacher to a student for a subject | AcademicDirector |
| GET | `/vks/teacher-assignments/{id}` | Fetch one teacher assignment | PlatformAdmin, AcademicDirector |
| GET | `/vks/teachers/{id}/teacher-assignments` | List the assignments of a teacher | PlatformAdmin, AcademicDirector |
| GET | `/vks/students/{id}/teacher-assignments` | List the teacher assignments of a student | PlatformAdmin, AcademicDirector, EnrollmentOfficer |
| POST | `/vks/teacher-assignments/{id}/end` | End an ASSIGNED teacher assignment | AcademicDirector |
| POST | `/vks/attendance` | Record a daily attendance entry; the daily status is derived by the server | EnrollmentOfficer, PlatformAdmin |
| GET | `/vks/attendance/{id}` | Fetch one attendance record | PlatformAdmin, EnrollmentOfficer |
| GET | `/vks/students/{id}/attendance` | List the attendance records of a student | PlatformAdmin, EnrollmentOfficer |
| POST | `/vks/attendance/{id}/excuse` | Excuse an absence | EnrollmentOfficer |
| POST | `/vks/assessment-windows` | Schedule an assessment window | ProctorCoordinator, PlatformAdmin |
| GET | `/vks/assessment-windows/{id}` | Fetch an assessment window | PlatformAdmin, ProctorCoordinator, EnrollmentOfficer |
| GET | `/vks/assessment-windows` | List assessment windows with pagination | PlatformAdmin, ProctorCoordinator, EnrollmentOfficer |
| POST | `/vks/test-sites` | Register a proctoring test site | ProctorCoordinator, PlatformAdmin |
| GET | `/vks/test-sites/{id}` | Fetch a test site | PlatformAdmin, ProctorCoordinator |
| GET | `/vks/test-sites` | List test sites with pagination | PlatformAdmin, ProctorCoordinator |
| POST | `/vks/proctor-assignments` | Book a proctored seat for a student at a site within a window; OCC-guarded on the site version | ProctorCoordinator |
| GET | `/vks/proctor-assignments/{id}` | Fetch one proctor assignment | PlatformAdmin, ProctorCoordinator |
| GET | `/vks/assessment-windows/{id}/proctor-assignments` | List proctor assignments for a window | PlatformAdmin, ProctorCoordinator |
| GET | `/vks/test-sites/{id}/proctor-assignments` | List proctor assignments at a site | PlatformAdmin, ProctorCoordinator |
| GET | `/vks/students/{id}/proctor-assignments` | List proctor assignments of a student | PlatformAdmin, ProctorCoordinator, EnrollmentOfficer |
| POST | `/vks/proctor-assignments/{id}/mark-completed` | Mark a BOOKED assignment completed (window must be OPEN) | ProctorCoordinator |
| POST | `/vks/proctor-assignments/{id}/cancel` | Cancel a BOOKED assignment and release the seat | ProctorCoordinator |
| POST | `/vks/service-deliveries` | Schedule an online special-education service session | SpecialEdCoordinator |
| GET | `/vks/service-deliveries/{id}` | Fetch one service delivery | PlatformAdmin, SpecialEdCoordinator |
| GET | `/vks/students/{id}/service-deliveries` | List the service deliveries of a student | PlatformAdmin, SpecialEdCoordinator, EnrollmentOfficer |
| GET | `/vks/teachers/{id}/service-deliveries` | List the service deliveries where the given teacher is the provider | PlatformAdmin, SpecialEdCoordinator, AcademicDirector |
| POST | `/vks/service-deliveries/{id}/mark-delivered` | Mark a SCHEDULED session as DELIVERED | SpecialEdCoordinator |
| POST | `/vks/service-deliveries/{id}/mark-missed` | Mark a SCHEDULED session as MISSED, only after its scheduled end has passed | SpecialEdCoordinator |
| POST | `/vks/service-deliveries/{id}/cancel` | Cancel a SCHEDULED session | SpecialEdCoordinator |
| POST | `/vks/service-deliveries/{id}/reschedule` | Reschedule a MISSED session to a future time | SpecialEdCoordinator |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API can return. The conditions that trigger each error are described with their workflows in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DISTRICT_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_TEACHER_NOT_CERTIFIED_IN_STATE` | 422 Unprocessable Entity |
| `ERR_PROVIDER_NOT_CERTIFIED_IN_STATE` | 422 Unprocessable Entity |
| `ERR_CASELOAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_SEAT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_TIME_IN_PAST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_STIPEND` | 422 Unprocessable Entity |
| `ERR_NOT_SPECIAL_ED_STUDENT` | 422 Unprocessable Entity |
| `ERR_MARK_MISSED_TOO_EARLY` | 422 Unprocessable Entity |
