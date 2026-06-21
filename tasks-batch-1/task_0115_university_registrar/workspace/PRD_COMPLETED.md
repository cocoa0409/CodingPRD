# University Registrar API — Product Requirements Document

## 1. Introduction

Universities live or die by the integrity of their registration machinery. A single term touches thousands of students, each holding a personal registration window, a credit-hour ceiling, a tangle of prerequisites, and a tuition account that must reconcile to the penny. The University Registrar API exists to make that machinery dependable and auditable: it governs the academic catalog, the per-term lifecycle of course sections and their seats, the appointment windows that stagger registration by priority, and the full enrollment journey from a student's first registration attempt through grading, transcript, and degree audit.

The system is deliberately strict about who may do what and when. Registrars own the catalog and the calendar; advisors grant appointments, enter grades, and manage advising holds; bursars manage financial holds and read refunds; students act only on their own registrations. Layered over this are the temporal rules that distinguish a clean drop from a graded withdrawal, the quota rules that route a registration to a seat or a waitlist, and the concurrency rules that keep two students from claiming the same last seat on stale information. Every financial consequence — a tuition charge, a full or partial refund, a balance owed — flows automatically from these transitions so that the books never drift from the academic record.

This document specifies the contract an implementation must honor: the entities and their fields, the parallel state machines that drive enrollment and grading, the calculations behind refunds and GPA, the validation order that decides which error a rejected request receives, and the role-based access controls that bound every operation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the request is made. The role value must be one of exactly four recognized roles: `Student`, `Advisor`, `Registrar`, and `Bursar`. If `X-User-Role` is missing or is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are present and the role is recognized but that role is not permitted to perform the requested operation under the access-control matrix, the request is rejected with `ERR_FORBIDDEN`.

These roles are peers, not a hierarchy. A `Registrar` owns the catalog and calendar — terms, programs, courses, course requirements, instructors, sections, the section and term lifecycles, student-record creation, and the test-driving clock. An `Advisor` grants enrollment appointments, enters final grades, and places or clears advising holds. A `Bursar` places and clears financial holds and reads refund records. A `Student` registers, drops, withdraws, and swaps — but only against their own enrollments — and reads their own academic records.

The acting principal's identity is tied to persisted entities for exactly one role. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any enrollment or swap request compare the resource's `student_id` foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `Advisor`, `Registrar`, or `Bursar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and authorization but does not compare it to any entity's `id` for ownership purposes.

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

List endpoints accept two query parameters to control paging. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and a supplied value must fall between a minimum of 1 and a maximum of 100 inclusive. The `offset` parameter sets the number of leading items to skip; when omitted it defaults to 0, and a supplied value must be zero or greater. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending — oldest first. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the total number of matching items before paging and `has_more` indicates whether any items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field, also an ISO 8601 UTC timestamp with three fractional digits, is refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins optimistic concurrency control (§2.5).

`Term`, `Student`, `Course`, `Instructor`, `Section`, `EnrollmentAppointment`, `Enrollment`, `Hold`, and `SwapRequest` all carry the full common set — `id`, `created_at`, `updated_at`, and `version`. Three entities are immutable after creation and therefore carry only `id` and `created_at`, with both `updated_at` and `version` absent: `Program`, `CourseRequirement`, and `RefundTransaction`. A `RefundTransaction`, for example, is a permanent ledger record and is never edited once written.

A crucial consequence of versioning concerns derived fields. When a transition recomputes a derived field on a resource — for instance updating a `Section`'s `seats_taken`, a `Student`'s `gpa` or `tuition_owed_cents`, or an `EnrollmentAppointment`'s `enrolled_credit_hours` — and that recomputation actually changes the stored value, the recomputation is itself a mutation: the affected resource's `updated_at` is refreshed and, where the entity carries a `version`, its `version` increments. A recomputation that yields a value identical to the one already stored is not treated as a mutation and bumps neither `updated_at` nor `version`, avoiding spurious version drift. This is why a single enrollment can advance a section's `version` even though the client only created an enrollment.

### 2.5. Optimistic Concurrency Control on Section Seats

Registering for a section is the one write that contends for a scarce resource — a seat — so it is guarded by optimistic concurrency control. A registration request must carry `expected_section_version` holding the `version` of the target `Section` that the client last observed. The server compares this value against the section's current `version` at evaluation time. If they differ — meaning another writer has advanced the section's `version` since the client last read it, for example by taking what the client believed was an available seat — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client from acting on a stale view of seat availability and being silently routed to an outcome it did not anticipate. The atomic swap (§3.10) likewise carries `expected_section_version` for the section it adds into and applies the same `ERR_STALE_VERSION` (412) guard; apart from registration and swap, no operation accepts or requires a version field.

### 2.6. Temporal Evaluation and the Logical Clock

Many rules in this system depend on the current instant relative to a term's deadlines. All such comparisons are made against a server-maintained logical clock rather than wall-clock time. An administrative test-driving capability lets a `Registrar` set the server's current UTC instant by supplying a `now_iso8601` value; the call returns `200 OK` with a `data` object echoing the accepted instant as `{ "now_iso8601": <value> }`, and every subsequent deadline and window comparison — appointment opening, add deadline, drop deadline, withdraw deadline — uses that instant until it is changed again. A `now_iso8601` that does not parse as an ISO 8601 instant is rejected with `ERR_VALIDATION`. All boundary comparisons in this document are stated in terms of this logical "now".

### 2.7. Monetary Values, Credit Hours, and Precision

All tuition and refund amounts are integer counts of cents; there are no fractional cents. Where a refund computation produces a non-integer cent value, it is rounded half up to the nearest whole cent. Tuition for an enrollment is the course's credit hours multiplied by the term's per-credit cost in cents, and that charge is frozen at the moment a seat is first taken so that later changes to a term's per-credit cost never retroactively alter a settled charge.

GPA is the one non-integer figure exposed by the system; it is reported on a 4.0 scale rounded half up to exactly two decimal places. Credit hours — earned, completed, enrolled, and required — are always whole integers.

### 2.8. Hierarchical Existence Checks and Reverse-Reachability Reads

When a request references resources by path or body, the server validates their existence left to right in a fixed order — `Term`, then `Student`, then `Section`, then `Course`, then `Enrollment`, then `Hold` — and returns `ERR_NOT_FOUND` on the first reference that does not resolve, before applying any business rule. A request that names a non-existent term and an otherwise-valid section fails on the term.

The API also exposes collection reads that walk a foreign key in reverse: the sections of a term, course, or instructor; the enrollments of a term, section, or student; the courses and students of a program; the requirement edges of a course; a student's holds, appointments, swap requests, and refunds; and the refunds of an enrollment. These are read-only projections and apply the same pagination and ordering rules as any other list endpoint.

### 2.9. Cascades and Derived-Field Reconciliation

Several operations mutate more than one entity. A drop releases a seat and may immediately promote a waitlisted student into it; a section cancellation drops every enrollment on that section and credits refunds; a swap creates one enrollment and drops another. The governing principle is that every such secondary effect runs to completion within the same operation and reconciles all affected derived fields — a section's `seats_taken` and `waitlist_count`, a student's `tuition_owed_cents`, `gpa`, `earned_credit_hours`, and `academic_standing`, and an appointment's `enrolled_credit_hours` — so that no resource is left describing a state the system has already moved past. The specific cascades are detailed in §3 alongside the workflows that trigger them.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog and the Term Calendar

A `Registrar` lays the groundwork before any student can register. A **Program** is created with a `name`, a `required_credit_hours` total needed to graduate, and an optional `min_gpa` that defaults to 2.0 when not supplied; a program is a permanent reference record. A **Course** is created with a `code` (a unique catalog code such as CS101), a `title`, an integer `credit_hours` that must be zero or greater, and a `program_id` naming the owning program. Every course is offerable when created — its `is_active` flag starts `true` — and a retired course is one whose `is_active` is `false`.

Courses carry their academic dependencies as **CourseRequirement** edges. Each requirement names the `course_id` that carries the requirement and the `required_course_id` that must be satisfied, plus a `requirement_type` of either `PREREQUISITE` or `COREQUISITE`. A `PREREQUISITE` must be completed before the term; a `COREQUISITE` must be taken in the same term. A requirement also carries `min_grade_points`, the minimum grade points on a 0.0–4.0 scale that the required course's grade must reach for a `PREREQUISITE` to count as satisfied; when omitted it defaults to 1.0. A requirement edge, once written, is immutable.

An **Instructor** is created with a `full_name`, a unique `email`, and an optional `gap_minutes` buffer (defaulting to 0, and never negative) that governs how close together two of that instructor's sections may sit on a shared day; zero means back-to-back adjacency is allowed.

A **Term** anchors the calendar. It is created with a `name`, a `registration_opens_at` instant (the earliest any appointment window may begin), an `add_deadline`, a `drop_deadline`, a `withdraw_deadline`, a `per_credit_cost_cents` tuition rate, and two optional refund fractions: `refund_full_pct`, the fraction refunded for drops at or before the drop deadline (default 1.0), and `refund_partial_pct`, the fraction refunded for drops after the drop deadline but at or before the withdraw deadline (default 0.5). A new term begins in `PLANNING`.

A term advances through its lifecycle by a registrar's request that names the target state in a `to_status` field, moving `PLANNING → REGISTRATION_OPEN → IN_SESSION → CLOSED`, with `CLOSED` terminal. Opening registration — the `PLANNING → REGISTRATION_OPEN` transition — requires that at least one section already exists for the term; an attempt with no sections is rejected with `ERR_TERM_HAS_NO_SECTIONS`. The `REGISTRATION_OPEN → IN_SESSION` transition cascades no registration-status changes; from that point the add, drop, and withdraw deadlines gate enrollment transitions purely by the clock. The `IN_SESSION → CLOSED` transition likewise changes no registrations: each enrollment that is still `ENROLLED` with `grade_status` still `UNGRADED` remains `ENROLLED`, awaiting grade entry. A transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.2. Sections, Seats, and the Instructor Conflict Rule

A **Section** is the offering students actually register for. A `Registrar` creates one with a `term_id`, a `course_id`, an `instructor_id`, a `section_code` (unique within a given term and course), a `seat_capacity` of at least 1, an optional `waitlist_capacity` (default 0, never negative), and a meeting schedule: a `meeting_days` day code such as MWF or TR, a `meeting_start_min` expressed as minutes from midnight in the range 0 through 1439, and a `meeting_end_min` in the range 1 through 1440 that must exceed `meeting_start_min`. A new section opens with `status` `OPEN`, `seats_taken` 0, and `waitlist_count` 0. The computed `seats_taken` is the count of enrollments on the section in `ENROLLED` status; the computed `waitlist_count` is the count in `WAITLISTED` status.

At section-create time the system enforces an instructor double-booking rule against the instructor's other non-`CANCELLED` sections in the same term. Two sections conflict when they share at least one day letter in their `meeting_days` and their meeting windows are not separated by the instructor's required buffer. Concretely, using the instructor's `gap_minutes`, the new section conflicts with an existing one when the new section's start is earlier than the existing section's end plus the buffer, and the existing section's start is earlier than the new section's end plus the buffer — so even two windows that do not overlap but sit closer than the buffer are in conflict. A violation is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`. Note that this buffered geometry is specific to instructors; the student schedule conflict described later uses plain overlap with no buffer.

A section's lifecycle is `OPEN | CLOSED | CANCELLED`, with `CANCELLED` terminal, and every transition is driven by a registrar. Closing a section (`OPEN → CLOSED`) blocks new registrations but leaves existing `ENROLLED` and `WAITLISTED` entries untouched; reopening (`CLOSED → OPEN`) simply restores availability. Cancelling a section — from either `OPEN` or `CLOSED` — triggers a substantial cascade and is described in §3.6. A section transition requested from a state that does not define it is rejected with `ERR_INVALID_STATE`.

### 3.3. Students, Appointments, and the Registration Gate

A **Student** record is created by a `Registrar` with a `full_name`, a unique `email`, a `program_id` naming the degree program, and an optional `completed_credit_hours` (default 0) capturing transfer or prior-term credit at registration time. On creation, a student's `gpa` is 0.00, `academic_standing` is `GOOD`, and `earned_credit_hours` equals `completed_credit_hours`. Several student fields are computed and evolve as the student's record changes: `earned_credit_hours` is `completed_credit_hours` plus the credits from this system's enrollments that carry a passing final grade; `gpa` is the cumulative grade-point average over graded enrollments; `academic_standing` is derived from that GPA; and `tuition_owed_cents` is the running balance the student owes.

Before a student may register in a term, an **EnrollmentAppointment** must grant them a window. An appointment — which a `Registrar` or an `Advisor` may grant — names a `term_id` and a `student_id`, a `priority_tier` (an integer of at least 1, where a lower number registers earlier and 1 is highest priority), a `window_opens_at` instant at or after which the student may begin registering, and a `max_credit_hours` cap (at least 1) on the student's total enrolled-plus-waitlisted credit hours in that term. The appointment's computed `enrolled_credit_hours` starts at 0 and tracks the sum of `credit_hours` over the student's `ENROLLED` and `WAITLISTED` enrollments in that term — waitlisted credits count against the cap.

A student's eligibility to register hinges on holds. A **Hold** is placed on a student by a `Bursar` or an `Advisor` and names the `student_id`, a `hold_type` of `FINANCIAL` (the bursar's domain) or `ADVISING` (the advisor's domain), and a free-text `reason`. A hold begins `ACTIVE` and blocks the student's future registration. A hold is cleared by the appropriate office, moving `ACTIVE → CLEARED`; a `FINANCIAL` hold may be cleared only by a `Bursar` and an `ADVISING` hold only by an `Advisor`, and a mismatch is rejected with `ERR_HOLD_WRONG_CLEARER`. A student's registration is unblocked only once they have zero `ACTIVE` holds.

### 3.4. Registering for a Section: Enrolled or Waitlisted

A `Student` registers by submitting a `term_id`, a `section_id`, and the `expected_section_version` they last observed. A new enrollment is born in `REQUESTED` and is immediately evaluated; depending on seat availability it resolves to `ENROLLED` or `WAITLISTED`, both within the same request. An enrollment also records the owning `student_id`, and its computed fields — `tuition_charged_cents`, `refund_cents`, `waitlist_position`, `grade_points` — populate as it moves through its lifecycle.

The evaluation applies a sequence of gates, each tied to a specific rejection. The student must own the request (`X-User-ID` equal to the enrollment's `student_id`, else `ERR_NOT_RESOURCE_OWNER`). The student must have zero `ACTIVE` holds, or the request is rejected with `ERR_REGISTRATION_HOLD`. The term must be `REGISTRATION_OPEN` and the current instant at or before the term's `add_deadline`, else `ERR_ADD_WINDOW_CLOSED`. An `EnrollmentAppointment` must exist for the student and term and the current instant must be at or after its `window_opens_at`, else `ERR_APPOINTMENT_NOT_OPEN`. The section's `status` must be `OPEN`, else `ERR_SECTION_NOT_OPEN`. The student must not already hold a non-terminal enrollment in the same section, else `ERR_DUPLICATE_ENROLLMENT`.

Academic dependencies are then checked. Every `PREREQUISITE` requirement of the section's course must be satisfied by the student's prior graded history, else `ERR_PREREQUISITE_NOT_MET`; a prerequisite counts as satisfied when the student holds a graded, non-`W` enrollment in the required course from a prior or closed term whose grade points meet or exceed the requirement's `min_grade_points`. Every `COREQUISITE` requirement must be satisfied by a same-term enrollment in the required course whose `registration_status` is `ENROLLED`, `WAITLISTED`, or `REQUESTED`, else `ERR_COREQUISITE_NOT_MET`. The section's meeting window must not overlap any of the student's other `ENROLLED` sections on a shared day, else `ERR_TIME_CONFLICT`; this student-schedule check uses half-open overlap with adjacency allowed — one section ending exactly when another begins is not a conflict, and no buffer applies. Adding the section's `credit_hours` to the appointment's current `enrolled_credit_hours` must not exceed the appointment's `max_credit_hours`, else `ERR_CREDIT_LIMIT_EXCEEDED`. The supplied `expected_section_version` must match the section's current `version`, else `ERR_STALE_VERSION`.

Only after all of the above does seat routing occur. If the section's `seats_taken` is below its `seat_capacity`, the enrollment becomes `ENROLLED`: the section's `seats_taken` increments by one and its `version` increments by one; `tuition_charged_cents` is set to the course's `credit_hours` times the term's `per_credit_cost_cents`; and the student's `tuition_owed_cents` and the appointment's `enrolled_credit_hours` are recomputed. If instead the section is full (`seats_taken` equals `seat_capacity`), the enrollment is routed to the waitlist — but only if the section's `waitlist_count` is below its `waitlist_capacity`, else the request is rejected with `ERR_WAITLIST_FULL`. On a successful waitlisting the section's `waitlist_count` and `version` each increment by one, the enrollment's `waitlist_position` is assigned as the new `waitlist_count` after the increment, the appointment's `enrolled_credit_hours` is recomputed (waitlisted credits count toward the cap), and no tuition is charged — `tuition_charged_cents` stays 0 while waitlisted. A waitlisted enrollment's `waitlist_position` is its 1-based rank among the section's `WAITLISTED` enrollments ordered by `created_at` ascending, and is null whenever the enrollment is not waitlisted.

### 3.5. Dropping, Withdrawing, and Waitlist Promotion

A `Student` may release a seat in two ways, distinguished by the calendar. A **drop** is permitted while the term is `REGISTRATION_OPEN` or `IN_SESSION` and the current instant is at or before the term's `drop_deadline`; a drop attempted after the drop deadline is rejected with `ERR_DROP_WINDOW_CLOSED`. Dropping moves an `ENROLLED` enrollment to `DROPPED`: the section's `seats_taken` decrements by one and its `version` increments by one; a refund transaction is credited and the enrollment's `refund_cents` is set; and the student's `tuition_owed_cents` and the appointment's `enrolled_credit_hours` are recomputed. A `WAITLISTED` enrollment may also be dropped, which decrements the section's `waitlist_count` by one, increments the section's `version`, renumbers the remaining waitlist positions, and recomputes the appointment's `enrolled_credit_hours`; no refund is involved because a waitlisted enrollment was never charged.

A **withdraw** applies after the full-refund window. It is permitted when the current instant is after the term's `drop_deadline` and at or before its `withdraw_deadline`, and the term is `REGISTRATION_OPEN` or `IN_SESSION`; outside that window the request is rejected with `ERR_WITHDRAW_WINDOW_CLOSED`. Withdrawing moves an `ENROLLED` enrollment to `WITHDRAWN`: the section's `seats_taken` decrements and its `version` increments, a partial refund is credited and `refund_cents` is set, a transcript `W` mark is recorded (carrying no grade points and excluded from GPA), and the student's `tuition_owed_cents` and the appointment's `enrolled_credit_hours` are recomputed.

Whenever a seat is released by an `ENROLLED → DROPPED` or `ENROLLED → WITHDRAWN` transition and a seat is now available, the head of that section's waitlist is promoted. The system selects the `WAITLISTED` enrollment with the lowest `waitlist_position` — equivalently the earliest `created_at` — and promotes it to `ENROLLED`. This system promotion increments the section's `seats_taken` by one, decrements its `waitlist_count` by one, and increments its `version` by one; sets the promoted enrollment's `tuition_charged_cents` to the course's `credit_hours` times the term's `per_credit_cost_cents`; recomputes that promoted student's `tuition_owed_cents`; and renumbers the `waitlist_position` of the remaining waitlisted entries. Both drop and withdraw trigger this promotion. A drop, a withdraw, or a grade entry requested against an enrollment whose current state does not define that transition is rejected with `ERR_INVALID_STATE`.

### 3.6. Section Cancellation Cascade

When a `Registrar` cancels a section — from `OPEN` or `CLOSED` to `CANCELLED` — the system unwinds every enrollment on it. Each `ENROLLED` enrollment is moved to `DROPPED` with the drop attributed to a section cancellation; that cascaded drop credits a full refund regardless of the clock — past every deadline, the institution caused the cancellation, so the full refund fraction applies — and decrements the section's `seats_taken`. Each `WAITLISTED` enrollment is likewise moved to `DROPPED`, but with no refund because no tuition was ever charged. For every cascaded drop, the owning student's `tuition_owed_cents` and that student's `EnrollmentAppointment.enrolled_credit_hours` are recomputed. Because the section itself is terminating, the full-refund drops in this cascade are not gated by the drop deadline the way a student-initiated drop is.

### 3.7. Refund Calculation

Every drop or withdraw that releases a charged seat produces a **RefundTransaction**, a permanent record naming the `enrollment_id`, the credited `student_id`, the `refund_tier` applied, the `amount_cents` credited, and the `triggered_by` cause (`DROP`, `WITHDRAW`, or `SECTION_CANCEL`). The refund is computed from the enrollment's frozen `tuition_charged_cents` — the amount fixed when the seat was taken, never recomputed from the live per-credit cost — multiplied by a fraction determined by tier.

The tier is chosen as follows. If the refund was triggered by a section cancellation, the tier is `FULL` and the fraction is the term's `refund_full_pct`, regardless of the clock. Otherwise, if the current instant is at or before the term's `drop_deadline` — an inclusive boundary — the tier is `FULL` and the fraction is `refund_full_pct`. Otherwise, if the current instant is at or before the term's `withdraw_deadline`, the tier is `PARTIAL` and the fraction is `refund_partial_pct`. Otherwise the tier is `NONE` and the fraction is zero. The credited amount is the frozen charge multiplied by the chosen fraction, rounded half up to whole cents. Thus a drop within the full-refund window nets the student to zero owed for that enrollment; a late withdraw leaves them owing the charge minus the partial refund; and a section-cancellation drop always returns the full charge even past every deadline.

### 3.8. Grading, GPA, and Academic Standing

Grade entry is a parallel axis that advances independently of registration status. Every enrollment carries a `grade_status` of `UNGRADED` or `GRADED` alongside its `registration_status`. An `Advisor` enters a final `letter_grade` on an enrollment while the term is `IN_SESSION` or `CLOSED`. The enrollment's `registration_status` must be `ENROLLED` and the term must be `IN_SESSION` or `CLOSED`; either condition unmet rejects the request with `ERR_INVALID_STATE` (a non-`ENROLLED` enrollment and a term outside the grading window are both `ERR_INVALID_STATE`, evaluated before the already-graded and grade-validity checks). The `grade_status` must still be `UNGRADED`, or the request is rejected with `ERR_ALREADY_GRADED`. The submitted `letter_grade` must be one of `A`, `B`, `C`, `D`, or `F` — the `W` mark is produced only by a withdrawal, never by grade entry — and any other value is rejected with `ERR_INVALID_GRADE`. On success the `grade_status` advances `UNGRADED → GRADED` while `registration_status` stays `ENROLLED`; the enrollment's `grade_points` are set from the letter grade on a 4.0 scale where `A` is 4.0, `B` is 3.0, `C` is 2.0, `D` is 1.0, and `F` is 0.0 (grade points are null until graded); and the student's `gpa`, `earned_credit_hours`, and `academic_standing` are recomputed.

Cumulative GPA is a credit-hour-weighted average over the student's graded enrollments. The considered set is every enrollment whose `grade_status` is `GRADED` and whose `letter_grade` is one of `A`, `B`, `C`, `D`, or `F`; withdrawals carrying a `W` and ungraded enrollments are excluded entirely. For each considered enrollment, multiply its `grade_points` by its course's `credit_hours` to get its quality points; sum the quality points across the considered set, sum the course credit hours across the considered set, and divide the total quality points by the total credit hours, rounding half up to two decimal places. If the total credit hours is zero, the GPA is 0.00. An `F` contributes zero quality points but its credit hours still enter the denominator (failed but attempted), whereas a `W` enters neither numerator nor denominator.

Academic standing follows from cumulative GPA: `GOOD` when the GPA is at least 2.00, `WARNING` when the GPA is at least 1.00 but below 2.00, and `PROBATION` when the GPA is below 1.00. A student with zero graded credits is `GOOD`. The student's `earned_credit_hours` is `completed_credit_hours` plus the credit hours of every enrollment that carries a passing final grade.

### 3.9. Tuition Balance, Transcript, and Degree Audit

A student's `tuition_owed_cents` is reconciled on every enrollment charge, drop, withdrawal, or refund credit. It is the sum of the frozen `tuition_charged_cents` over the student's enrollments that were ever charged — those whose `registration_status` is `ENROLLED`, `WITHDRAWN`, or `DROPPED` — minus the sum of the `amount_cents` of all that student's refund transactions. A waitlisted enrollment contributes nothing because it was never charged. A full-refund drop therefore nets to zero for that enrollment; a partial withdraw nets to the charge minus the partial refund; and an enrolled student with no refund owes the full charge.

A student's **transcript** is a computed view of their graded enrollments reporting `cumulative_gpa`, `term_gpa`, `earned_credit_hours`, and the individual graded `lines`. Each entry in `lines` is the full serialized enrollment object of a graded, `A`–`F` enrollment, and the lines are ordered by `created_at` ascending. The reported `earned_credit_hours` is always the student's cumulative stored value and is not narrowed by a term scope. When scoped to a single term by a `term_id` query parameter, the `term_gpa` uses the same credit-hour-weighted formula but restricts the considered set to enrollments in that term and `lines` is likewise restricted to graded enrollments in that term; the `cumulative_gpa` spans every term. Without a `term_id`, `term_gpa` equals `cumulative_gpa` and `lines` covers every graded enrollment.

A student's **degree audit** evaluates progress against their program. It reports the program's `required_credit_hours`, the student's `earned_credit_hours`, the `credits_remaining` (the required total minus earned, never below zero), a `gpa_ok` flag that is true when the student's cumulative `gpa` is at least the program's `min_gpa`, the `is_complete` flag that is true only when no credits remain and the GPA requirement is met, and the set of `satisfied_course_ids` — the courses for which the student holds a graded enrollment with a grade of `D` or better (grade points of at least 1.0), reported as a list of distinct course ids sorted in ascending lexicographic order. A course passed with `D` or better counts as satisfied; an `F` or a `W` does not.

### 3.10. Atomic Swap Requests

A `Student` may exchange one section for another atomically through a **SwapRequest**, which avoids the trap of dropping a held seat only to find the desired section full. A swap names the `student_id`, the `term_id`, the `drop_enrollment_id` (the enrollment to give up), the `add_section_id` (the section to enroll into), and the `expected_section_version` of that target section. The request is evaluated in a single call and resolves to `COMMITTED` or `ABORTED`; a successful commit records the new enrollment's id in the computed `added_enrollment_id`, which is null while the request is `PENDING` or `ABORTED`.

The add leg is evaluated first against the full set of registration preconditions. The student must own the swap (else `ERR_NOT_RESOURCE_OWNER`) and have zero `ACTIVE` holds (else `ERR_REGISTRATION_HOLD`). The term must be `REGISTRATION_OPEN` with the current instant at or before its `add_deadline` (else `ERR_ADD_WINDOW_CLOSED`), and an appointment must be open for the student (else `ERR_APPOINTMENT_NOT_OPEN`). The `drop_enrollment_id` must be an `ENROLLED` enrollment owned by the student in this term, or the request fails with `ERR_INVALID_STATE`. The `add_section_id` must be an `OPEN` section with `seats_taken` below `seat_capacity`, else `ERR_SECTION_FULL`. All prerequisites and corequisites of the add section's course must be satisfied (else `ERR_PREREQUISITE_NOT_MET` or `ERR_COREQUISITE_NOT_MET`), the credit-limit check against `max_credit_hours` must pass (else `ERR_CREDIT_LIMIT_EXCEEDED`), and there must be no meeting-time conflict between the add section and the student's other `ENROLLED` sections once the drop is applied (else `ERR_TIME_CONFLICT`).

If every add-leg precondition holds, the swap `COMMITS`: the system creates the added enrollment (born `REQUESTED`, then `ENROLLED`) on the add section, setting `added_enrollment_id`, incrementing the add section's `seats_taken`, and charging tuition; the successful add then drives the `drop_enrollment` to `DROPPED`, which credits its refund and decrements the old section's `seats_taken`; and the seat released on the old section promotes that section's head `WAITLISTED` enrollment to `ENROLLED`. If any add-leg precondition fails, the swap `ABORTS`: the `drop_enrollment` is left untouched and still `ENROLLED`, no seat counts change, and the failing error is returned to the caller. The add-then-drop ordering is what makes the exchange safe — the old seat is never surrendered unless the new one is secured.

### 3.11. Validation Order

When several conditions could reject one request, the order in which they are checked determines which error the client receives, and that order is fixed. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Then body well-formedness on mutating endpoints — required fields present with correct types and enum values among their legal members — yields `ERR_VALIDATION`, and on list endpoints an out-of-range `limit` or negative `offset` yields `ERR_PAGINATION_INVALID`. Existence checks follow, yielding `ERR_NOT_FOUND` on the first unresolved reference in the left-to-right order of §2.8. Resource ownership for a student acting on an enrollment or swap is checked next, yielding `ERR_NOT_RESOURCE_OWNER`. State validity — whether the requested transition is defined from the target's current state — comes next with `ERR_INVALID_STATE`.

Only after those structural gates do the business rules for registration apply, and they too are ordered: the hold check (`ERR_REGISTRATION_HOLD`), then the add-window check (`ERR_ADD_WINDOW_CLOSED`), then the appointment-open check (`ERR_APPOINTMENT_NOT_OPEN`), then the section-open check (`ERR_SECTION_NOT_OPEN`), then the duplicate-enrollment check (`ERR_DUPLICATE_ENROLLMENT`), then prerequisites (`ERR_PREREQUISITE_NOT_MET`), then corequisites (`ERR_COREQUISITE_NOT_MET`), then the time-conflict check (`ERR_TIME_CONFLICT`), then the credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`), then the section-version OCC check (`ERR_STALE_VERSION`), and finally — only when the section is full — the waitlist-capacity check (`ERR_WAITLIST_FULL`). The window checks specific to release operations sit alongside these: a drop's `ERR_DROP_WINDOW_CLOSED` and a withdraw's `ERR_WITHDRAW_WINDOW_CLOSED`. Grade entry applies `ERR_INVALID_GRADE` and `ERR_ALREADY_GRADED`; clearing a hold applies `ERR_HOLD_WRONG_CLEARER`; opening a term applies `ERR_TERM_HAS_NO_SECTIONS`; the add leg of a swap applies `ERR_SECTION_FULL`; and section creation applies `ERR_INSTRUCTOR_DOUBLE_BOOKED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or that modify an existing resource (including lifecycle transitions and grade entry) return `200 OK`. Request and response bodies are reconstructed from the workflow narratives in §3; the table below lists only method, path, purpose, and the roles permitted to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/terms` | Create a term | Registrar |
| GET | `/terms/{id}` | Get a term | Registrar, Advisor, Student, Bursar |
| POST | `/terms/{id}/status` | Advance term lifecycle | Registrar |
| GET | `/terms/{id}/sections` | List sections offered in a term | Registrar, Advisor, Student, Bursar |
| GET | `/terms/{id}/enrollments` | List enrollments in a term | Registrar, Advisor, Bursar |
| GET | `/terms/{id}/appointments` | List appointments in a term | Registrar, Advisor |
| POST | `/programs` | Create a degree program | Registrar |
| GET | `/programs/{id}` | Get a program | Registrar, Advisor, Student, Bursar |
| GET | `/programs/{id}/students` | List students in a program | Registrar, Advisor |
| GET | `/programs/{id}/courses` | List courses owned by a program | Registrar, Advisor, Student, Bursar |
| POST | `/courses` | Create a catalog course | Registrar |
| GET | `/courses/{id}` | Get a course | Registrar, Advisor, Student, Bursar |
| POST | `/courses/{id}/requirements` | Add a prerequisite/corequisite edge | Registrar |
| GET | `/courses/{id}/requirements` | List requirement edges for a course | Registrar, Advisor, Student, Bursar |
| GET | `/courses/{id}/sections` | List sections of a course | Registrar, Advisor, Student, Bursar |
| POST | `/instructors` | Create an instructor | Registrar |
| GET | `/instructors/{id}` | Get an instructor | Registrar, Advisor, Student, Bursar |
| GET | `/instructors/{id}/sections` | List sections taught by an instructor | Registrar, Advisor, Student, Bursar |
| POST | `/sections` | Create a section offering | Registrar |
| GET | `/sections/{id}` | Get a section | Registrar, Advisor, Student, Bursar |
| POST | `/sections/{id}/status` | Transition a section (with cancellation cascade) | Registrar |
| GET | `/sections/{id}/enrollments` | List enrollments on a section | Registrar, Advisor, Student, Bursar |
| POST | `/students` | Create a student record | Registrar |
| GET | `/students/{id}` | Get a student | Registrar, Advisor, Student, Bursar |
| GET | `/students/{id}/enrollments` | List a student's enrollments | Registrar, Advisor, Student, Bursar |
| GET | `/students/{id}/holds` | List a student's holds | Registrar, Advisor, Student, Bursar |
| GET | `/students/{id}/transcript` | Computed transcript with GPA | Registrar, Advisor, Student, Bursar |
| GET | `/students/{id}/degree-audit` | Computed degree audit | Registrar, Advisor, Student |
| GET | `/students/{id}/swap-requests` | List a student's swap requests | Registrar, Advisor, Student |
| GET | `/students/{id}/appointments` | List a student's appointments | Registrar, Advisor, Student |
| GET | `/students/{id}/refunds` | List a student's refund transactions | Registrar, Bursar, Student |
| POST | `/appointments` | Grant an enrollment appointment | Registrar, Advisor |
| GET | `/appointments/{id}` | Get an appointment | Registrar, Advisor, Student |
| POST | `/enrollments` | Register for a section | Student |
| GET | `/enrollments/{id}` | Get an enrollment | Registrar, Advisor, Student, Bursar |
| POST | `/enrollments/{id}/drop` | Drop an enrollment | Student |
| POST | `/enrollments/{id}/withdraw` | Withdraw from an enrollment | Student |
| POST | `/enrollments/{id}/grade` | Enter a final grade | Advisor |
| GET | `/enrollments/{id}/refunds` | List refunds for an enrollment | Registrar, Bursar, Student |
| POST | `/holds` | Place a hold on a student | Bursar, Advisor |
| POST | `/holds/{id}/clear` | Clear a hold | Bursar, Advisor |
| POST | `/swap-requests` | Atomic add-then-drop swap | Student |
| GET | `/swap-requests` | List swap requests by filter | Registrar, Advisor |
| GET | `/swap-requests/{id}` | Get a swap request outcome | Registrar, Advisor, Student |
| POST | `/_clock/set` | Set the server's current UTC instant (test-driving) | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REGISTRATION_HOLD` | 403 Forbidden |
| `ERR_ADD_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DROP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_WITHDRAW_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_OPEN` | 409 Conflict |
| `ERR_SECTION_NOT_OPEN` | 409 Conflict |
| `ERR_SECTION_FULL` | 409 Conflict |
| `ERR_WAITLIST_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_COREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TIME_CONFLICT` | 409 Conflict |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_GRADE` | 422 Unprocessable Entity |
| `ERR_ALREADY_GRADED` | 409 Conflict |
| `ERR_HOLD_WRONG_CLEARER` | 403 Forbidden |
| `ERR_TERM_HAS_NO_SECTIONS` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
