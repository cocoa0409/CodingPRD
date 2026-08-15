# Dual Enrollment Concurrent Credit API — Product Requirements Document

## 1. Introduction

Community-college dual-credit programs live in the seam between two institutions that do not naturally agree with one another. A high school runs on its own academic calendar with its own add, drop, and withdraw windows; the college runs on a separate calendar with its own deadlines, its own grading conventions, and its own transcript. A single student sitting in a single classroom is simultaneously enrolled at both, and every administrative action — confirming a seat, recording a grade, processing a refund — has to reconcile those two worlds without allowing either to drift out of sync.

This document specifies the Dual Enrollment & Concurrent Credit API operated by a community college's dual-credit office. The system governs the full lifecycle of a dual-credit section: partner high schools and the terms they run on, instructor credentialing for college credit, seat allocation against offering capacity, tuition responsibility split among state, district, and family, grade posting onto two transcripts with two different GPA scales, and articulation of completed credit toward receiving institutions. A logical clock, settable only by the administrator, drives every deadline and window check so that the behavior of the system is deterministic under test.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their capacity. The declared role names are exactly `DualCreditAdmin`, `HsCoordinator`, `Instructor`, `CredentialReviewer`, `CollegeRegistrar`, and `Bursar`; `Any` appears in the endpoint table as a marker meaning every declared role may call that endpoint, not as a role a caller may present. A request missing either header, or presenting a role that is not one of the declared names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five of the six working roles treat `X-User-ID` as an opaque operator identifier not tied to any persisted entity: `DualCreditAdmin`, `HsCoordinator`, `CredentialReviewer`, `CollegeRegistrar`, and `Bursar`. The server may record these identifiers where the workflow says so — notably `CredentialApplication.reviewed_by`, which is stamped with the acting `CredentialReviewer`'s `X-User-ID` when a review is claimed — but it does not compare them against any entity's `id`. `Instructor` is the exception. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor` entity, and ownership checks compare resource foreign keys to it: an instructor may only create or resubmit a `CredentialApplication` whose `instructor_id` equals their `X-User-ID` (else `ERR_NOT_RESOURCE_OWNER`, HTTP 403), and may only submit a grade for an offering whose `instructor_id` equals their `X-User-ID` (else `ERR_NOT_OFFERING_INSTRUCTOR`, HTTP 403). A reviewer's decision call — approve, deny, or request-revision — likewise requires the caller's `X-User-ID` to equal the application's `reviewed_by`, failing with `ERR_NOT_RESOURCE_OWNER` when it does not.

Segregation of duties is enforced on credentialing decisions: the reviewer's `X-User-ID` must differ from the application's `instructor_id`, so a person may never approve, deny, or send back their own credential application. Violating this is rejected with `ERR_CREDENTIAL_SELF_APPROVAL` (HTTP 403). The `Bursar` role is likewise segregated from `DualCreditAdmin`: the administrator who authors funding agreements never records payments against them, and the bursar who records payments never authors the funding terms.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be at least 0. Out-of-range pagination parameters are rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). All list endpoints return resources sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Two-Calendar Discipline

Dual credit is defined by the fact that two academic calendars run in parallel. Every `CourseOffering` references a pair of `AcademicTerm` records: one whose `institution_type` is `COLLEGE` and one whose `institution_type` is `HIGH_SCHOOL`. The college term's deadlines govern college-side actions; the high school term's deadlines govern the high school side; and any enrollment action must respect the stricter of the two. Three effective deadlines are derived from the pair by taking the earlier instant in each case: the effective add deadline is the earlier of `college_term.add_deadline` and `hs_term.add_deadline`; the effective drop deadline is the earlier of `college_term.drop_deadline` and `hs_term.drop_deadline`; the effective withdraw deadline is the earlier of `college_term.withdraw_deadline` and `hs_term.withdraw_deadline`. Deadline boundaries are inclusive — an action taken at exactly the deadline instant passes, and an action taken after it fails. The two referenced terms must also both be in status `OPEN` for enrollment confirmation or offering opening; otherwise the request fails with `ERR_TERM_NOT_OPEN` (HTTP 409).

Every `AcademicTerm` enforces an internal date ordering at creation, exposed on the resource as the system-maintained `date_ordering` invariant note: `start_date` strictly precedes `add_deadline`, which is at or before `drop_deadline`, which is at or before `withdraw_deadline`, which is at or before `end_date`. A violation is a malformed request rejected with `ERR_VALIDATION` (HTTP 400). Terms are also non-overlapping within an institution calendar: a new term whose half-open interval from `start_date` (inclusive) to `end_date` (exclusive) overlaps an existing term of the same `institution_type` — and, for `HIGH_SCHOOL` terms, the same `high_school_id` — is rejected with `ERR_TERM_OVERLAP` (HTTP 409). Two terms whose intervals merely touch, one's `end_date` equal to the other's `start_date`, do not conflict.

### 2.5. The Seat Ledger and Capacity Invariant

Seat accounting on a `CourseOffering` is exact integer arithmetic. The computed `seats_taken` is the count of `Enrollment` records on that offering whose status is `REGISTERED`; no other enrollment status consumes a seat. The computed `seats_available` is `capacity` minus `seats_taken`. The two sum to `capacity` at all times, so a reader who knows any two of the three numbers can derive the third. A confirm, a drop, a withdraw, a reinstate, or a waitlist promotion each moves `seats_taken` by exactly one, and each such move increments the offering's `version`.

### 2.6. Common Resource Properties

Most resources in the system carry four standard fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on any mutation; and `version`, an integer that increments by 1 on every mutation. A cascade that mutates a parent as a side effect — for example, a confirm that consumes a seat on the offering — is itself a mutation of that parent and so increments its `version` and refreshes its `updated_at`.

Three resources are deliberately lighter-weight and carry only `id` and `created_at`, with no `updated_at` and no `version`: `Prerequisite`, `PlacementRecord`, and `Payment`. These records are created once and never transition through a lifecycle, so the system omits the mutation-tracking fields from them.

### 2.7. Money, Percentages, and Rounding Discipline

All monetary amounts are integer cents. The tuition rate lives on `FundingAgreement.tuition_cents_per_credit` and is at least 1 cent per credit; the state's subsidy per credit is `state_rate_cents_per_credit` and may be 0; the district's maximum contribution per enrollment is `district_cap_cents` and may be 0. Payment and refund amounts are always integers of cents, never fractional.

Where a proportional share must be computed, the system uses round-half-up at exactly the steps named in the refund settlement rules — no more, no fewer. Refund percentages are integer percents drawn from the closed set 0, 50, and 100. GPA values are different in kind: they are computed to three decimal places with round-half-up. Transfer credit hours are expressed to one decimal place.

### 2.8. Optimistic Concurrency Control

Two write endpoints require optimistic concurrency control against the `CourseOffering` parent, and both use the same field. The enrollment-confirm operation and the enrollment-reinstate operation each require the request body to carry `expected_offering_version`, holding the `version` of the offering as the client last observed it. If another writer has advanced the offering's `version` since that read — because a seat was consumed or released by an intervening confirm, drop, withdraw, reinstate, or waitlist promotion — the client's view of `seats_available` is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; only these two seat-allocating writes are OCC-guarded.

### 2.9. Nested Resource Retrieval

Requests that carry resource identifiers in the path validate them left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. After the path is fully resolved, body-supplied foreign keys are validated in their declared input order, again with `ERR_NOT_FOUND` on the first miss. An operation on an enrollment therefore never reports a stale-version or business rule failure for an enrollment that does not exist; existence always precedes every other check.

### 2.10. Validation Ordering

Every endpoint applies its checks in a fixed priority order, so that when several rules are violated the same one always surfaces first. The auth checks come first: presence and validity of `X-User-ID` and `X-User-Role` (priority 1), then role authorization (priority 2), then entity-backed ownership and segregation-of-duties (priority 3). Next come request-shape validation (priority 4) — required fields, types, enum members, numeric ranges, term date ordering — and pagination parameters (also priority 4, for list endpoints). Existence of referenced resources is priority 5. State-machine preconditions and the OCC stale-version check are priority 6. Business safety checks — student eligibility and school suspension — are priority 7. Business temporal checks — add/drop/withdraw windows, term-end for grading, term and articulation overlap — are priority 8. Business referential checks — terms open, term type and school match, prerequisites, placement, funding agreement, instructor credentialing — span priorities 9 through 14. Business constraint checks — duplicate enrollment, prerequisite edge rules, duplicate funding agreement — are priority 15. Business fiscal checks — seats available, overpayment, refund due — are priority 16.

Within the confirm chain specifically, the priority-9-through-14 referential checks run in this sub-order: both terms `OPEN` first, then prerequisite satisfaction, then placement-record presence, then placement-score sufficiency, then funding agreement existence. The instructor-credentialing check at priority 14 applies only to opening an offering, not to confirming an enrollment.

## 3. Business Logic & Workflows

### 3.1. Partner Schools, Terms, and the Catalog

A `DualCreditAdmin` onboards a partner high school by creating a `HighSchool` with a `name` and a `district_code`. The school's `status` starts at `ACTIVE`. Suspension is the terminal lifecycle action on a school: the administrator moves it from `ACTIVE` to `SUSPENDED`, an action invalid in any other state and rejected with `ERR_INVALID_STATE` (HTTP 409). Suspending a school does not modify any existing enrollment; it blocks only future enrollment confirmations, which fail with `ERR_SCHOOL_SUSPENDED` (HTTP 409) when the student's school is `SUSPENDED`.

The administrator also authors `AcademicTerm` records. A college term has `institution_type` `COLLEGE` and a null `high_school_id`; a high school term has `institution_type` `HIGH_SCHOOL` and a non-null `high_school_id` pointing at the owning school. Supplying a `high_school_id` for a `COLLEGE` term, or omitting it for a `HIGH_SCHOOL` term, is a malformed request rejected with `ERR_VALIDATION`. Each term carries `name`, `start_date`, `end_date`, `add_deadline`, `drop_deadline`, and `withdraw_deadline`, subject to the date-ordering and overlap rules of §2.4. A new term's `status` is `SCHEDULED`. The administrator moves a term from `SCHEDULED` to `OPEN` via open-registration (invalid in any other state, rejected with `ERR_TERM_INVALID_STATE`, HTTP 409), and from `OPEN` to `CLOSED` via close-registration (same error on a state mismatch). Closing a term has a cascade: every `WAITLISTED` enrollment whose offering is tied to this term — through either its `college_term_id` or its `hs_term_id` — transitions to `EXPIRED`, retaining its `waitlist_seq`, which is never reused. `PENDING_VERIFICATION` enrollments are not cancelled by close-registration; they remain, but any later confirm attempt against them fails the terms-OPEN check with `ERR_TERM_NOT_OPEN`. Term transitions increment the term's `version`.

The catalog course is the unit of credit. The administrator creates a `Course` with `course_code`, `title`, `college_credit_hours` (an integer at least 1), `hs_credit_units` (a positive number), `placement_exam_code`, and `min_placement_score` (an integer at least 0; 0 means the course imposes no placement requirement and `placement_exam_code` is ignored). A course's `status` starts at `ACTIVE` and moves terminally to `RETIRED` via retire (any other starting state fails with `ERR_INVALID_STATE`). A `RETIRED` course cannot be used for new offerings.

### 3.2. Prerequisites and Placement Records

A `Prerequisite` is a directed edge in a graph over courses, from `course_id` (the course imposing the requirement) to `requires_course_id` (the course that must already be satisfied). The set of edges forms a directed acyclic graph, and the administrator's creation calls are the only way edges enter it. Edge creation applies three rules in a fixed sub-order: a self-edge — `course_id` equal to `requires_course_id` — is rejected first with `ERR_SELF_PREREQUISITE` (HTTP 400); an exact duplicate edge is rejected next with `ERR_DUPLICATE_PREREQUISITE` (HTTP 409); and an edge that would close a cycle, detected by depth-first reachability from `requires_course_id` back to `course_id`, is rejected last with `ERR_PREREQUISITE_CYCLE` (HTTP 409). Each edge carries an optional `min_grade` defaulting to `C`, one of `A`, `B`, or `C`; the grade ordering is `A` above `B` above `C` above `D` above `F`, and only `A`, `B`, or `C` can satisfy any `min_grade`.

A `PlacementRecord` captures one sitting of a placement exam for one student, created by a `HsCoordinator` with `student_id`, `exam_code`, `score` (an integer at least 0), and `taken_at`. The system computes `expires_at` as `taken_at` plus 730 days. A record at or past its `expires_at` is invisible to the placement check.

### 3.3. Instructor Credentialing

An `Instructor` is created by a `DualCreditAdmin` with a `full_name` and the `high_school_id` of their employing school. Before an instructor may teach a course for college credit, they must hold an approved credential for that specific course. The instructor initiates this by creating a `CredentialApplication` with `instructor_id` (which must equal their own `X-User-ID`), `course_id`, and a free-text `qualification_summary`. The application's `status` starts at `SUBMITTED` with `reviewed_by` null.

A `CredentialReviewer` claims an application by moving it from `SUBMITTED` to `UNDER_REVIEW` via begin-review (any other starting state fails with `ERR_CREDENTIAL_APPLICATION_INVALID_STATE`, HTTP 409). The claim stamps `reviewed_by` with the reviewer's `X-User-ID` and increments the application's `version`. From `UNDER_REVIEW`, three decisions are possible, each restricted to the review owner — the caller's `X-User-ID` must equal `reviewed_by`, else `ERR_NOT_RESOURCE_OWNER` — and each subject to segregation of duties, so the caller's `X-User-ID` must differ from `instructor_id`, else `ERR_CREDENTIAL_SELF_APPROVAL`. The ownership and segregation checks on these decision calls apply whatever the application's current `status`, and per the ordering of §2.10 they surface ahead of the state-machine precondition: because a `SUBMITTED` application's `reviewed_by` is null and so equals no caller, an approve, deny, or request-revision call against a `SUBMITTED` application fails with `ERR_NOT_RESOURCE_OWNER`. Approve moves the application to the terminal `APPROVED` state and records an optional `decision_reason` when supplied. Deny moves it to the terminal `DENIED` state. Request-revision moves it to `NEEDS_REVISION` and records an optional `decision_reason`. From `NEEDS_REVISION`, the applicant — the `Instructor` whose `X-User-ID` equals `instructor_id`, else `ERR_NOT_RESOURCE_OWNER` — resubmits, returning the application to `SUBMITTED` and clearing `reviewed_by` to null, releasing the prior review ownership.

### 3.4. Standing Up a Section

A `CourseOffering` is a section of a course taught at a high school under a pair of calendars. The administrator creates one with `course_id`, `college_term_id`, `hs_term_id`, `high_school_id`, `instructor_id`, `capacity` (an integer at least 1), and an optional `delivery_mode` defaulting to `HS_CAMPUS`, one of `HS_CAMPUS`, `COLLEGE_CAMPUS`, or `ONLINE`. The referenced `college_term_id` must point to a term whose `institution_type` is `COLLEGE`, and `hs_term_id` to a term whose `institution_type` is `HIGH_SCHOOL`; a mismatch in either is rejected with `ERR_TERM_TYPE_MISMATCH` (HTTP 409). The high school term's `high_school_id` must also equal the offering's own `high_school_id`; a mismatch is rejected with `ERR_TERM_SCHOOL_MISMATCH` (HTTP 409). A new offering's `status` is `DRAFT`, `seats_taken` is 0, and `seats_available` equals `capacity`.

The administrator opens an offering by moving it from `DRAFT` to `OPEN` — the only valid origin state, else `ERR_OFFERING_INVALID_STATE` (HTTP 409). Opening requires both referenced terms to be `OPEN` (else `ERR_TERM_NOT_OPEN`), the course to be `ACTIVE` (else `ERR_INVALID_STATE`), and an `APPROVED` `CredentialApplication` to exist matching the offering's `instructor_id` and `course_id` (else `ERR_INSTRUCTOR_NOT_CREDENTIALED`, HTTP 409). From `OPEN`, the administrator advances the offering to `IN_SESSION` via start-session. From `IN_SESSION`, the administrator begins grading, moving to `GRADING`; this requires the logical clock to read at or after the college term's `end_date`, and is rejected with `ERR_TERM_NOT_ENDED` (HTTP 409) when the college term has not yet ended.

Cancellation is available from `DRAFT` and from `OPEN` — any other origin state fails with `ERR_OFFERING_INVALID_STATE` — and drives the offering to the terminal `CANCELLED` state. The cascade is conditional on each enrollment's status: `PENDING_VERIFICATION` enrollments become `CANCELLED`; `WAITLISTED` enrollments become `CANCELLED`; `REGISTERED` enrollments become `DROPPED` (an administrative drop, not a student-initiated one), and each such dropped enrollment's `Invoice` is voided with `refund_pct` set to 100 and the refund estimate fields computed per the estimate rules of §3.7, with `refund_status` set to `DUE` if the sum of its payments is greater than zero and `NONE` otherwise. `DROPPED`, `COMPLETED`, `CANCELLED`, and `EXPIRED` enrollments are untouched. Cancel increments the offering's `version`.

### 3.5. The Enrollment Lifecycle: Confirm, Waitlist, Drop, Withdraw, Reinstate

A `HsCoordinator` registers a `Student` with `full_name`, `high_school_id`, and `grade_level` (an integer from 9 to 12). The student's `status` starts at `ELIGIBLE`, and both `college_gpa` and `hs_gpa` start at 0.000. Suspending a student — moving `ELIGIBLE` to `SUSPENDED`, invalid in any other state and rejected with `ERR_INVALID_STATE` — does not modify existing enrollments but blocks future confirmations with `ERR_STUDENT_NOT_ELIGIBLE` (HTTP 409).

The coordinator creates an `Enrollment` with `student_id` and `offering_id`; it starts in `PENDING_VERIFICATION` and consumes no seat. Creating an enrollment is rejected with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409) when an enrollment for the same `student_id` and `offering_id` already exists in `PENDING_VERIFICATION`, `REGISTERED`, or `WAITLISTED`. Confirming an enrollment is the heaviest validation chain in the system. The request carries `expected_offering_version` per §2.8, and the checks run in this order: the enrollment is in `PENDING_VERIFICATION` (else `ERR_ENROLLMENT_INVALID_STATE`, HTTP 409); the offering's current `version` matches `expected_offering_version` (else `ERR_STALE_VERSION`, HTTP 412); the offering is `OPEN` (else `ERR_OFFERING_INVALID_STATE`); the student is `ELIGIBLE` and has `grade_level` at least 11 (else `ERR_STUDENT_NOT_ELIGIBLE`); the student's school is `ACTIVE` (else `ERR_SCHOOL_SUSPENDED`); the logical clock reads at or before the earlier of the two terms' `add_deadline` values (else `ERR_ADD_WINDOW_CLOSED`, HTTP 409); both terms are `OPEN` (else `ERR_TERM_NOT_OPEN`); every prerequisite of the offering's course is satisfied (else `ERR_PREREQUISITE_NOT_MET`, HTTP 409); placement requirements are met (else `ERR_PLACEMENT_MISSING` or `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409); and a `FundingAgreement` exists for the offering's `high_school_id` and `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409).

Prerequisite satisfaction means: for every `Prerequisite` row of the course, there exists a `TranscriptEntry` whose `institution` is `COLLEGE` and `status` is `POSTED`, belonging to an enrollment of this student on an offering of `requires_course_id`, with a grade at or above `min_grade`. Placement, checked only when the course's `min_placement_score` is greater than 0, means: among the student's non-expired `PlacementRecord` rows for the course's `placement_exam_code`, there is at least one (else `ERR_PLACEMENT_MISSING`); the latest such record — ordered by `taken_at` descending, then `created_at` descending — has a `score` at least the course's `min_placement_score` (else `ERR_PLACEMENT_SCORE_INSUFFICIENT`). An expired newer record does not mask an older still-valid record; the older record is the one evaluated.

If every check passes and at least one seat is free, the enrollment moves to `REGISTERED`: `seats_taken` increases by 1, the offering's `version` increments, and an `Invoice` is created per §3.7 with `status` `ISSUED` and `refund_status` `NONE`. If every check passes but `seats_available` is 0, the same request does not fail; it lands the enrollment in `WAITLISTED` instead. The system assigns `waitlist_seq` as one more than the maximum existing `waitlist_seq` for the offering, starting at 1 for the first waitlisted enrollment; the sequence is per-offering monotonic and never reused. No invoice is created for a `WAITLISTED` enrollment. Confirm increments the enrollment's `version` in either outcome.

From `REGISTERED`, the coordinator may drop the enrollment while the logical clock reads at or before the earlier of the two terms' `drop_deadline` values (else `ERR_DROP_WINDOW_CLOSED`, HTTP 409; an attempt from any status other than `REGISTERED` is `ERR_ENROLLMENT_INVALID_STATE`). Drop moves the enrollment to `DROPPED`, decrements `seats_taken` by 1, and increments the offering's `version`. It also settles the enrollment's invoice per §3.7 with `refund_pct` set to 100. A dropped enrollment never produces a `TranscriptEntry`. Finally, drop fires the waitlist promotion of §3.6 when its conditions hold.

Withdraw is the alternative to drop once the drop window has closed. The coordinator may withdraw a `REGISTERED` enrollment only when the logical clock reads strictly after the earlier of the two `drop_deadline` values — a withdraw attempted while the drop window is still open is rejected with `ERR_ENROLLMENT_INVALID_STATE`, because drop must be used instead — and at or before the earlier of the two `withdraw_deadline` values (else `ERR_WITHDRAW_WINDOW_CLOSED`, HTTP 409). Withdraw moves the enrollment to `WITHDRAWN`, sets `grade` to `W`, stamps `withdrawn_at` with the current logical-clock timestamp, decrements `seats_taken` by 1, and increments the offering's `version`. The invoice is settled per §3.7 with a `refund_pct` of 50 when the clock reads at or before the college term's `drop_deadline` and 0 otherwise — note that the college calendar alone governs the 50-percent compensation even though the high school calendar may have been what forced the withdraw, which is the cross-calendar mismatch window. The same waitlist promotion rule as drop then applies.

A `CollegeRegistrar` may reinstate a `WITHDRAWN` enrollment, moving it back to `REGISTERED`. The request carries `expected_offering_version` per §2.8, and reinstate requires: the enrollment in `WITHDRAWN` (else `ERR_ENROLLMENT_INVALID_STATE`); the offering's current `version` matching `expected_offering_version` (else `ERR_STALE_VERSION`); the offering in `OPEN` or `IN_SESSION` (else `ERR_OFFERING_INVALID_STATE`); the logical clock at or before the college term's `end_date` (else `ERR_WITHDRAW_WINDOW_CLOSED`); and at least one free seat (else `ERR_NO_SEATS_AVAILABLE`, HTTP 409). Reinstate clears `grade` to null and `withdrawn_at` to null, increments `seats_taken` by 1, increments the offering's `version`, and creates a brand-new `Invoice` per §3.7 — the previous invoice keeps its own state and refund fields.

The coordinator may also cancel a waitlist entry outright, moving `WAITLISTED` to `CANCELLED` (any other origin state fails with `ERR_ENROLLMENT_INVALID_STATE`).

### 3.6. Waitlist Promotion

A seat released by a drop or a withdraw fires a promotion only when the offering's `status` is `OPEN`; a seat released while the offering is `IN_SESSION` or later simply stays free. When the condition holds and at least one `WAITLISTED` enrollment exists for the offering, the system promotes the one holding the minimum `waitlist_seq`. Promotion moves that enrollment to `REGISTERED`, increments `seats_taken` by 1, increments the offering's `version` again (on top of the increment from the drop or withdraw that released the seat), and creates a new `Invoice` for the promoted enrollment per §3.7. An empty waitlist is a no-op, not an error. Because `waitlist_seq` is assigned as maximum-plus-one, ties are impossible by construction.

### 3.7. Tuition Allocation, Refunds, and the Invoice Ledger

A `FundingAgreement` authored by the administrator fixes tuition responsibility for one school in one college term. It carries `high_school_id`, `college_term_id`, `funding_model` (one of `STATE_PROGRAM`, `DISTRICT_CONTRACT`, or `FAMILY_RESPONSIBLE`), `tuition_cents_per_credit`, an optional `state_rate_cents_per_credit` defaulting to 0, and an optional `district_cap_cents` defaulting to 0. A system-enforced `uniqueness` rule caps this at one agreement per school and college-term pair; a second creation for the same pair is rejected with `ERR_DUPLICATE_FUNDING_AGREEMENT` (HTTP 409).

When an enrollment reaches `REGISTERED` — by confirm, by waitlist promotion, or by reinstate — an `Invoice` is created. The gross `tuition_total_cents` is the course's `college_credit_hours` multiplied by the agreement's `tuition_cents_per_credit`. The total is then allocated across three payer buckets in waterfall order. Bucket 1 is the state: when the agreement's `funding_model` is `STATE_PROGRAM` and the offering's `delivery_mode` is `HS_CAMPUS`, `state_amount_cents` is the smaller of `tuition_total_cents` and `state_rate_cents_per_credit` multiplied by `college_credit_hours`; in every other case `state_amount_cents` is 0. The first remainder is `tuition_total_cents` minus `state_amount_cents`. Bucket 2 is the district: when the agreement's `funding_model` is `FAMILY_RESPONSIBLE` the district bucket is skipped entirely and `district_amount_cents` is 0; otherwise `district_amount_cents` is the smaller of the first remainder and `district_cap_cents`. Bucket 3 is the family, which takes the remainder: `family_amount_cents` is the first remainder minus `district_amount_cents`. The three buckets always sum to `tuition_total_cents`. The invoice records its own `enrollment_id` and the `funding_agreement_id` used for the allocation, tracks what has actually been collected per payer — `paid_state_cents`, `paid_district_cents`, and `paid_family_cents`, each starting at 0 — and its `status` starts at `ISSUED` with `refund_status` `NONE`. A `Payment` recorded against the invoice carries the invoice's `invoice_id` taken from the path.

A `Bursar` records a payment against one payer bucket by creating a `Payment` under the invoice with `payer` (one of `STATE`, `DISTRICT`, or `FAMILY`), `amount_cents` (an integer greater than 0), and an optional `note`. The payment is rejected with `ERR_INVOICE_INVALID_STATE` (HTTP 409) when the invoice is not in `ISSUED` or `PARTIALLY_PAID` — a `VOIDED` invoice cannot take payments — and with `ERR_OVERPAYMENT` (HTTP 409) when the payment would push the payer's running paid total above that payer's billed share. A successful payment adds `amount_cents` to the corresponding paid bucket and increments the invoice's `version`. When the cumulative paid total across all three buckets is greater than 0 but less than `tuition_total_cents`, the invoice's `status` moves to `PARTIALLY_PAID`; when the cumulative total equals `tuition_total_cents`, it moves to `PAID`.

Refund is a two-stage discipline. The estimate variant fires at drop or withdraw and is stored on the invoice: `refund_pct` is set per the refund percentage rules — 100 on drop; on withdraw, 50 when the clock reads at or before the college term's `drop_deadline` and 0 otherwise — and the estimate fields are computed only when the percentage is greater than 0. `refund_estimate_cents` is `tuition_total_cents` multiplied by `refund_pct` and divided by 100, rounded half-up. `est_state_refund_cents` is `state_amount_cents` multiplied by `refund_pct` and divided by 100, rounded half-up. `est_district_refund_cents` is `district_amount_cents` multiplied by `refund_pct` and divided by 100, rounded half-up. `est_family_refund_cents` is the remainder — `refund_estimate_cents` minus `est_state_refund_cents` minus `est_district_refund_cents` — pinning the family bucket to absorb any rounding drift. When `refund_pct` is 100 the invoice's `status` moves to `VOIDED`; when it is 50 the status is unchanged. `refund_status` is set to `DUE` when the percentage is greater than 0 and the sum of payments on the invoice is greater than 0, and `NONE` otherwise. The estimate variant is provisional and based on billed shares, so it overstates the refund when payers have underpaid.

The settled variant fires when the `Bursar` processes the refund, moving `refund_status` from `DUE` to `PROCESSED` (any other starting value is rejected with `ERR_REFUND_NOT_DUE`, HTTP 409, including a second refund call on an already-processed invoice). The settled `refund_paid_cents` is computed from amounts actually paid, not billed shares: it is the rounded state refund plus the rounded district refund plus a family remainder, where the rounded state refund is `paid_state_cents` multiplied by the percentage and divided by 100 rounded half-up, the rounded district refund is `paid_district_cents` multiplied by the percentage and divided by 100 rounded half-up, and the family remainder is `paid_state_cents` plus `paid_district_cents` plus `paid_family_cents`, multiplied by the percentage and divided by 100 and rounded half-up, minus the rounded state refund, minus the rounded district refund. When the invoice is fully paid the settled amount equals the estimate; when partially paid the settled amount is at most the estimate and the two diverge.

### 3.8. Grading, Finalization, and Transcript Posting

Once an offering reaches `GRADING`, the `Instructor` of record — the caller's `X-User-ID` must equal the offering's `instructor_id`, else `ERR_NOT_OFFERING_INSTRUCTOR` — records a final letter `grade` on each `REGISTERED` enrollment. The grade must be one of `A`, `B`, `C`, `D`, or `F`; `W` is never set through grade submission, only through withdraw. Grade submission increments the enrollment's `version`.

A `CollegeRegistrar` finalizes the offering, moving it from `GRADING` to the terminal `FINALIZED` state (any other origin state is `ERR_OFFERING_INVALID_STATE`). Finalize requires every `REGISTERED` enrollment on the offering to carry a non-null `grade`; if any is ungraded the request fails with `ERR_GRADES_MISSING` (HTTP 409). On success, every `REGISTERED` enrollment moves to `COMPLETED`, and transcript entries are created per the posting rules: a `COMPLETED` enrollment produces one `COLLEGE` entry whose `credit_value` is the course's `college_credit_hours` and one `HIGH_SCHOOL` entry whose `credit_value` is the course's `hs_credit_units`, both in `PENDING` status with the grade copied from the enrollment. A `WITHDRAWN` enrollment always produces a `COLLEGE` `PENDING` entry with grade `W`, and produces a `HIGH_SCHOOL` `PENDING` entry with grade `W` only when its `withdrawn_at` is strictly after the high school term's `drop_deadline` — a withdraw that happened before the high school's drop deadline leaves no record on the high school transcript. `DROPPED`, `CANCELLED`, and `EXPIRED` enrollments produce no entries. Finalize increments the offering's `version`.

A `TranscriptEntry` carries `enrollment_id`, `institution`, `grade`, `credit_value`, `grade_points`, and `status` starting at `PENDING`. The registrar posts an entry, moving it from `PENDING` to `POSTED` (any other origin state is `ERR_TRANSCRIPT_ENTRY_INVALID_STATE`, HTTP 409), and the student's GPA for that entry's institution is recomputed. The registrar may also void a `POSTED` entry, moving it to `VOIDED` — used when a grade is under appeal or correction — and the GPA is recomputed again with the voided entry excluded from both numerator and denominator. Posting an entry refreshes the owning student's `updated_at`.

The GPA recompute runs over all of the student's `POSTED` entries only; `PENDING` and `VOIDED` entries are excluded. Each entry's `grade_points` is the quality-point value for its institution and grade multiplied by its `credit_value`. The college variant writes `college_gpa` and uses a 4.0 scale — `A` is 4, `B` is 3, `C` is 2, `D` is 1, `F` is 0 — with `W` excluded from numerator and denominator entirely, so a `W` does not move the college GPA. The college GPA is the sum of `grade_points` over `POSTED` `COLLEGE` entries with grades `A` through `F`, divided by the sum of those entries' `credit_value`. The high school variant writes `hs_gpa` and uses a dual-credit weighted 5.0 scale — `A` is 5, `B` is 4, `C` is 3, `D` is 2, `F` is 0, `W` is 0 — with `W` included at 0 points and its `credit_value` counted in the denominator, so a `W` drags the high school GPA down. The high school GPA is the sum of `grade_points` over `POSTED` `HIGH_SCHOOL` entries with grades `A` through `F` or `W`, divided by the sum of those entries' `credit_value`. When the eligible set is empty the GPA is 0.000. Both GPAs are rounded half-up to three decimal places.

### 3.9. Articulation and Transfer Evaluation

An `ArticulationAgreement` records how a receiving institution grants credit for a course. The administrator creates one with `course_id`, `target_institution` (the receiving institution's name), `transfer_credit_hours` (a positive number, which may differ from the course's `college_credit_hours`), an optional `min_grade_for_transfer` defaulting to `C` (one of `A`, `B`, or `C`), `effective_from`, and `effective_to`. The active window is a closed interval — the agreement is active when the logical clock reads at or after `effective_from` and at or before `effective_to`. Unlike terms, articulation windows for the same `course_id` and `target_institution` pair conflict even when they merely touch: a new agreement whose closed window overlaps an existing agreement's closed window is rejected with `ERR_ARTICULATION_WINDOW_OVERLAP` (HTTP 409).

Transfer evaluation is a computed read over a `COMPLETED` enrollment — any other enrollment status fails with `ERR_ENROLLMENT_INVALID_STATE` — taking a `target_institution` query parameter. It finds the `ArticulationAgreement` matching the enrollment's course and the target institution whose window contains the current logical-clock instant. The read returns an `eligible` flag alongside the two credit readings. The enrollment is eligible when such an agreement exists and the enrollment's grade meets `min_grade_for_transfer` under the ordering `A` above `B` above `C`; `F` and `W` are never eligible. The read returns two readings of the same completed course: the articulated reading, `articulated_credit_hours`, is the agreement's `transfer_credit_hours` when eligible and 0 otherwise; the native reading, `native_credit_hours`, is the course's `college_credit_hours` when eligible and 0 otherwise; and `credit_loss_hours` is `native_credit_hours` minus `articulated_credit_hours`, the delta between the two readings whenever the target grants fewer hours than the college awarded. Hours are reported to one decimal place.

### 3.10. The Logical Clock

Every deadline, window, expiry, and active-interval check in the system reads a server-side logical clock, never wall-clock time. The clock's startup default is exactly `2026-08-01T00:00:00Z`, and before any set call it reads that default. A `DualCreditAdmin` advances the clock by supplying a `to_iso8601` instant; the capability responds with `now_iso8601` echoing the clock's new reading. This is the only way time moves in the system, and it is what makes every temporal rule above deterministic.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource, drive a state transition, or record a payment against an existing invoice return `200 OK`. The sole exception is payment creation, which returns `201 Created` because it adds a new `Payment` resource to the ledger.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dual-credit/high-schools` | Create a partner high school | DualCreditAdmin |
| GET | `/dual-credit/high-schools` | List high schools | Any |
| GET | `/dual-credit/high-schools/{schoolId}` | Get one high school | Any |
| POST | `/dual-credit/high-schools/{schoolId}/suspend` | Suspend a high school | DualCreditAdmin |
| POST | `/dual-credit/terms` | Create an academic term | DualCreditAdmin |
| GET | `/dual-credit/terms` | List terms | Any |
| GET | `/dual-credit/terms/{termId}` | Get one term | Any |
| POST | `/dual-credit/terms/{termId}/open-registration` | Open registration on a term | DualCreditAdmin |
| POST | `/dual-credit/terms/{termId}/close-registration` | Close registration on a term | DualCreditAdmin |
| POST | `/dual-credit/students` | Register a student | HsCoordinator |
| GET | `/dual-credit/students` | List students | Any |
| GET | `/dual-credit/students/{studentId}` | Get one student | Any |
| POST | `/dual-credit/students/{studentId}/suspend` | Suspend a student | DualCreditAdmin |
| POST | `/dual-credit/courses` | Create a catalog course | DualCreditAdmin |
| GET | `/dual-credit/courses` | List courses | Any |
| GET | `/dual-credit/courses/{courseId}` | Get one course | Any |
| POST | `/dual-credit/courses/{courseId}/retire` | Retire a course | DualCreditAdmin |
| POST | `/dual-credit/prerequisites` | Create a prerequisite edge | DualCreditAdmin |
| GET | `/dual-credit/prerequisites` | List prerequisite edges | Any |
| GET | `/dual-credit/prerequisites/{prereqId}` | Get one prerequisite edge | Any |
| POST | `/dual-credit/placement-records` | Record a placement exam result | HsCoordinator |
| GET | `/dual-credit/placement-records` | List placement records | Any |
| GET | `/dual-credit/placement-records/{recordId}` | Get one placement record | Any |
| POST | `/dual-credit/instructors` | Create an instructor | DualCreditAdmin |
| GET | `/dual-credit/instructors` | List instructors | Any |
| GET | `/dual-credit/instructors/{instructorId}` | Get one instructor | Any |
| POST | `/dual-credit/credential-applications` | Apply for credentialing on a course | Instructor |
| GET | `/dual-credit/credential-applications` | List credential applications | Any |
| GET | `/dual-credit/credential-applications/{appId}` | Get one credential application | Any |
| POST | `/dual-credit/credential-applications/{appId}/begin-review` | Claim an application for review | CredentialReviewer |
| POST | `/dual-credit/credential-applications/{appId}/approve` | Approve a credential application | CredentialReviewer |
| POST | `/dual-credit/credential-applications/{appId}/deny` | Deny a credential application | CredentialReviewer |
| POST | `/dual-credit/credential-applications/{appId}/request-revision` | Request revision on an application | CredentialReviewer |
| POST | `/dual-credit/credential-applications/{appId}/resubmit` | Resubmit a revised application | Instructor |
| POST | `/dual-credit/offerings` | Create a course offering | DualCreditAdmin |
| GET | `/dual-credit/offerings` | List offerings | Any |
| GET | `/dual-credit/offerings/{offeringId}` | Get one offering | Any |
| POST | `/dual-credit/offerings/{offeringId}/open` | Open an offering for enrollment | DualCreditAdmin |
| POST | `/dual-credit/offerings/{offeringId}/start-session` | Move an offering into session | DualCreditAdmin |
| POST | `/dual-credit/offerings/{offeringId}/begin-grading` | Begin grading on an offering | DualCreditAdmin |
| POST | `/dual-credit/offerings/{offeringId}/finalize` | Finalize an offering and post transcripts | CollegeRegistrar |
| POST | `/dual-credit/offerings/{offeringId}/cancel` | Cancel an offering | DualCreditAdmin |
| POST | `/dual-credit/enrollments` | Create an enrollment | HsCoordinator |
| GET | `/dual-credit/enrollments` | List enrollments | Any |
| GET | `/dual-credit/enrollments/{enrollmentId}` | Get one enrollment | Any |
| POST | `/dual-credit/enrollments/{enrollmentId}/confirm` | Confirm an enrollment | HsCoordinator |
| POST | `/dual-credit/enrollments/{enrollmentId}/drop` | Drop an enrollment | HsCoordinator |
| POST | `/dual-credit/enrollments/{enrollmentId}/withdraw` | Withdraw an enrollment | HsCoordinator |
| POST | `/dual-credit/enrollments/{enrollmentId}/reinstate` | Reinstate a withdrawn enrollment | CollegeRegistrar |
| POST | `/dual-credit/enrollments/{enrollmentId}/cancel-waitlist` | Cancel a waitlist entry | HsCoordinator |
| POST | `/dual-credit/enrollments/{enrollmentId}/submit-grade` | Submit a final grade | Instructor |
| GET | `/dual-credit/enrollments/{enrollmentId}/transfer-evaluation` | Evaluate transfer credit for a completed enrollment | Any |
| GET | `/dual-credit/transcript-entries` | List transcript entries | Any |
| GET | `/dual-credit/transcript-entries/{entryId}` | Get one transcript entry | Any |
| POST | `/dual-credit/transcript-entries/{entryId}/post` | Post a transcript entry | CollegeRegistrar |
| POST | `/dual-credit/transcript-entries/{entryId}/void` | Void a transcript entry | CollegeRegistrar |
| POST | `/dual-credit/funding-agreements` | Create a funding agreement | DualCreditAdmin |
| GET | `/dual-credit/funding-agreements` | List funding agreements | Any |
| GET | `/dual-credit/funding-agreements/{agreementId}` | Get one funding agreement | Any |
| GET | `/dual-credit/invoices` | List invoices | Any |
| GET | `/dual-credit/invoices/{invoiceId}` | Get one invoice | Any |
| POST | `/dual-credit/invoices/{invoiceId}/payments` | Record a payment against an invoice | Bursar |
| GET | `/dual-credit/payments` | List payment events | Any |
| GET | `/dual-credit/payments/{paymentId}` | Get one payment event | Any |
| POST | `/dual-credit/invoices/{invoiceId}/refund` | Settle a refund on an invoice | Bursar |
| POST | `/dual-credit/articulation-agreements` | Create an articulation agreement | DualCreditAdmin |
| GET | `/dual-credit/articulation-agreements` | List articulation agreements | Any |
| GET | `/dual-credit/articulation-agreements/{agreementId}` | Get one articulation agreement | Any |
| POST | `/dual-credit/_clock/set_current_utc` | Set the server's logical clock | DualCreditAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_OFFERING_INSTRUCTOR` | 403 |
| `ERR_CREDENTIAL_SELF_APPROVAL` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERM_INVALID_STATE` | 409 |
| `ERR_TERM_NOT_OPEN` | 409 |
| `ERR_OFFERING_INVALID_STATE` | 409 |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 |
| `ERR_CREDENTIAL_APPLICATION_INVALID_STATE` | 409 |
| `ERR_INVOICE_INVALID_STATE` | 409 |
| `ERR_TRANSCRIPT_ENTRY_INVALID_STATE` | 409 |
| `ERR_GRADES_MISSING` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STUDENT_NOT_ELIGIBLE` | 409 |
| `ERR_SCHOOL_SUSPENDED` | 409 |
| `ERR_ADD_WINDOW_CLOSED` | 409 |
| `ERR_DROP_WINDOW_CLOSED` | 409 |
| `ERR_WITHDRAW_WINDOW_CLOSED` | 409 |
| `ERR_TERM_NOT_ENDED` | 409 |
| `ERR_TERM_OVERLAP` | 409 |
| `ERR_ARTICULATION_WINDOW_OVERLAP` | 409 |
| `ERR_TERM_TYPE_MISMATCH` | 409 |
| `ERR_TERM_SCHOOL_MISMATCH` | 409 |
| `ERR_PREREQUISITE_NOT_MET` | 409 |
| `ERR_PLACEMENT_MISSING` | 409 |
| `ERR_PLACEMENT_SCORE_INSUFFICIENT` | 409 |
| `ERR_NO_FUNDING_AGREEMENT` | 409 |
| `ERR_DUPLICATE_FUNDING_AGREEMENT` | 409 |
| `ERR_INSTRUCTOR_NOT_CREDENTIALED` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_SELF_PREREQUISITE` | 400 |
| `ERR_DUPLICATE_PREREQUISITE` | 409 |
| `ERR_PREREQUISITE_CYCLE` | 409 |
| `ERR_NO_SEATS_AVAILABLE` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_REFUND_NOT_DUE` | 409 |
