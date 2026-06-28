# Test-Prep Tutoring API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Test-Prep Tutoring API, a back-end platform that runs a Kaplan/Princeton-Review-style standardized-exam preparation business. The platform manages a published catalog of courses targeting the SAT, ACT, MCAT, and LSAT exams across live, online, and self-paced formats, and it coordinates the full commercial lifecycle that surrounds those courses: scheduling instructor-led cohorts against a finite number of seats, enrolling students (including a waitlist when a cohort fills), financing tuition through installment plans, scoring diagnostic and practice tests, and adjudicating the higher-score-or-refund guarantee.

Two business tensions drive most of the rules in this document. The first is **seat scarcity**: every cohort holds a fixed number of seats, and the system must reserve, commit, release, and re-offer those seats deterministically as enrollments are created, paid, cancelled, or swept up by a cohort's conclusion. The second is **guarantee accountability**: the business promises a minimum score improvement, and when a student who has met the diagnostic, practice, and attendance prerequisites nonetheless falls short of that promised gain, the platform owes them either a refund or a free retake. Both tensions demand careful, auditable bookkeeping, which is why the platform tracks score history, attendance, payments, and guarantee state on durable resources rather than recomputing them ad hoc.

The audience for this document is the engineering team implementing the service. It is organized to present the domain rules first and the HTTP surface second: Section 2 defines system-wide contracts (authentication, response shape, pagination, concurrency, precision, and cross-cutting consistency rules), Section 3 narrates the business workflows in domain terms, Section 4 lists the endpoints, and Section 5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than public catalog reads and student self-registration must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. The system recognizes exactly four roles: `Anonymous`, `Student`, `Instructor`, and `Registrar`. If a protected endpoint receives a request with a missing header, or an `X-User-Role` value that is not one of these four role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The four roles map to identities as follows. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a student compare that resource's `student_id` (directly, or through the enrollment it belongs to) to `X-User-ID`. A `Student` may act only on enrollments it owns, on the practice attempts, installment plans, and guarantee claims that belong to those enrollments, and on its own student record; an attempt to act on another student's resource is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; instructor actions concern attendance recording and the scoring or voiding of practice attempts. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque public identifier not tied to any persisted entity; the anonymous role exists only to read the public catalog and to register a new student. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The Registrar is the operational administrator and may perform catalog, cohort, instructor, financing, activation, and guarantee-adjudication actions, and may also perform any shared operation a student could perform on a student's behalf.

Anonymous self-registration and the public catalog read endpoints (reading the course list, a single course, a course's cohorts, and a single cohort) do not require authentication headers.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip before collecting the page; it defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, so the oldest matching resource appears first; ties in `created_at` are broken by creation (insertion) order. Beyond `limit` and `offset`, list endpoints also accept optional exact-match filter query parameters that narrow results before pagination: the course list filters on `exam_type`, `format`, and `status`; the cohort lists (under a course and under an instructor) and the enrollment lists (under a cohort and under a student) filter on `status`; the practice-attempt list filters on `attempt_type` and `status`; and the installment-plan and guarantee-claim lists filter on `status`. An unrecognized or unsupplied filter parameter is simply ignored. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` is the number of resources matching the query before pagination and `has_more` indicates whether more pages remain beyond the current one.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation to the resource; it underpins the optimistic-concurrency mechanism described in §2.6.

Courses, instructors, cohorts, students, enrollments, installment plans, and guarantee claims all carry `id`, `created_at`, `updated_at`, and `version`. A `PracticeAttempt` is the one exception: it carries only `id` and `created_at`. A practice attempt has no `updated_at` and no `version` field — even though it does transition between scoring states, it is treated as an append-only analytics record for the purpose of common fields, and clients must not expect either field on it.

Recomputed fields are still mutations. When the platform recomputes a derived value such as a cohort's `seats_committed`, an instructor's `active_cohort_count`, or an enrollment's `best_practice_score`, that recomputation refreshes the owning resource's `updated_at` and increments its `version` exactly as a direct edit would.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many read endpoints reach a child collection through a parent identifier in the path — for example, the cohorts belonging to a course, the enrollments belonging to a cohort, or the practice attempts, installment plans, and guarantee claims belonging to an enrollment. For any request whose path carries an identifier, the system validates that identifier's existence before proceeding, and when more than one identifier is present it validates them strictly left to right. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`. Body foreign keys are resolved after path identifiers, also in declaration order; any unresolved reference likewise yields `ERR_NOT_FOUND`.

### 2.6. Optimistic Concurrency on Cohort Seats

Because a cohort owns a finite pool of seats, two of the enrollment operations are guarded by optimistic concurrency keyed on the parent cohort's `version`. Creating an enrollment requires the request to carry `expected_cohort_version` holding the cohort `version` the client last observed; cancelling an enrollment likewise requires `expected_cohort_version` in its body. In both cases, if the supplied value does not equal the target cohort's current `version`, the request is rejected with `ERR_STALE_VERSION` at HTTP status 412, and no seat is claimed or released. This guards the seat pool: a successful enrollment creation or cancellation advances the cohort's `version` by one, so a client still holding an older version is acting on a stale view of remaining seats and must re-read the cohort before retrying. No other endpoint takes a version field, and no endpoint outside enrollment creation and cancellation performs this check.

### 2.7. Monetary Values, Scores, and Rounding

All money is represented in integer cents; there are no fractional cents anywhere in the system, and the installment allocation described in §3.6 is engineered to conserve every cent. Where a rule multiplies a percentage against a cent amount — the percentage coupon discount of §3.3 — the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The refund computation conserves money exactly and performs no rounding.

Exam scores are integer points on each exam's own scale. A practice attempt's `scaled_score` is rounded half up to a whole number of points, and its `percentile` is an analytics figure carried to exactly one decimal place, also rounded half up. The attendance fraction used for guarantee eligibility is compared at full floating-point precision and is never rounded before comparison.

### 2.8. Cascading Consistency and the Logical Clock

Mutations and their downstream effects are applied atomically within a single request: when an operation releases a seat, promotes a waitlisted enrollment, refunds a financing plan, or completes a batch of enrollments, all of those effects either succeed together or the request fails as a whole. Each entity that a cascade touches independently has its `updated_at` refreshed and its `version` incremented. The specific cascades — seat release feeding waitlist promotion, cohort cancellation sweeping its enrollments, cohort conclusion completing its active enrollments, and installment default cancelling its enrollment — are detailed in §3.

All time-based rules read a single server **logical clock** rather than wall-clock time. The clock's startup default is `2026-04-01T00:00:00Z`; until an operator sets it, every deadline, window, and expiry comparison reads exactly that default and the server never falls back to real time. A Registrar may advance the clock by supplying a target instant in `to_iso8601`. Cohort start and conclusion gating, materials expiry, and installment-default timing all read this clock.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Courses and Cohorts

The catalog begins with a **Course**, created by a Registrar and describing one exam-preparation offering. A course names its `exam_type` — one of `SAT`, `ACT`, `MCAT`, or `LSAT` — and its delivery `format`, one of `LIVE`, `ONLINE`, or `SELF`. It carries a marketing `title` and a `list_price_cents` sticker price that must be zero or greater. The `baseline_scale_max` field records the maximum number of points on this exam's scale (for example 1600 for the SAT, 36 for the ACT, 528 for the MCAT, 180 for the LSAT) and must be strictly greater than zero; it bounds every diagnostic and practice score the course can produce. Three guarantee parameters live on the course: `guarantee_min_delta`, the score-point improvement the course promises over the diagnostic baseline (zero or greater); `required_practice_tests`, the number of completed practice tests a student must finish to keep guarantee eligibility (zero or greater); and `required_attendance_pct`, the minimum attendance fraction between 0.0 and 1.0 inclusive required for guarantee eligibility on live and online cohorts. Finally, `materials_access_days` is the number of days after activation that course materials stay reachable and must be strictly greater than zero.

A course's `status` begins at `DRAFT` on creation. Publishing it advances `DRAFT` to `PUBLISHED`, which is the precondition for scheduling any cohort beneath it. Retiring a published course advances `PUBLISHED` to `RETIRED`, after which no new cohorts may be scheduled, though existing cohorts run to their natural end.

A **Cohort** is a concrete running of a course. A Registrar creates a cohort by supplying the parent `course_id`, the `seat_capacity` (one or greater), the session window's `starts_at` (inclusive) and `ends_at` (exclusive, and required to be strictly after `starts_at`), and the `total_sessions` count of class meetings (one or greater; a self-paced cohort uses a `total_sessions` of 1). A freshly created cohort lands in `DRAFT` with no instructor — its `instructor_id` is null until assignment — and with `seats_committed` initialized to 0. The `seats_committed` figure is a derived count of the cohort's enrollments in `ACTIVE` or `COMPLETED` status, and it never exceeds `seat_capacity`. A cohort's lifecycle states are `DRAFT`, `SCHEDULED`, `IN_SESSION`, `CONCLUDED`, and `CANCELLED`, with the last two being terminal.

### 3.2. Staffing a Cohort: Instructors and Scheduling

An **Instructor** is created by a Registrar with a `full_name`, a non-empty `certified_exam_types` array (each element one of `SAT`, `ACT`, `MCAT`, or `LSAT`), and a `max_concurrent_cohorts` cap of one or greater. The instructor's `active_cohort_count` is a derived figure — the number of cohorts in `SCHEDULED` or `IN_SESSION` status to which the instructor is currently assigned — and starts at 0.

Scheduling assigns an instructor and advances a cohort from `DRAFT` to `SCHEDULED`. The instructor is taken from the `instructor_id` supplied in the request body; the server never auto-selects. This transition is gated by five checks. The cohort must currently be in `DRAFT`, or the request is rejected with `ERR_INVALID_STATE`. The parent course must be `PUBLISHED`, or the request fails with `ERR_COURSE_NOT_PUBLISHED`. The named instructor's `certified_exam_types` must contain the parent course's `exam_type`, or the request fails with `ERR_INSTRUCTOR_NOT_CERTIFIED`. The instructor must not already be at capacity — that is, the instructor's `active_cohort_count` must be strictly less than `max_concurrent_cohorts`, or the request fails with `ERR_INSTRUCTOR_OVERLOADED`. And the instructor must have no scheduling collision: no other cohort of theirs in `SCHEDULED` or `IN_SESSION` status may have a session window that overlaps this cohort's window. Overlap here uses half-open intervals: two windows conflict only when this cohort's `starts_at` is strictly before the other's `ends_at` and the other's `starts_at` is strictly before this cohort's `ends_at`. Windows that merely touch at a boundary — where one cohort's `ends_at` equals the other's `starts_at` — do not conflict, so back-to-back teaching is allowed; a genuine overlap is rejected with `ERR_INSTRUCTOR_TIME_CONFLICT`. When scheduling succeeds, the cohort's `instructor_id` is set to the supplied instructor and that instructor's `active_cohort_count` rises by one (refreshing the instructor's `updated_at` and bumping its `version`).

Starting a cohort advances `SCHEDULED` to `IN_SESSION`. It requires the cohort to be in `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and the logical clock to have reached the window opening — the current clock instant must be at or after the cohort's `starts_at`, or the request is rejected with `ERR_COHORT_WINDOW_NOT_OPEN`. Starting changes no enrollments; any waitlisted enrollments stay waitlisted.

Concluding a cohort advances `IN_SESSION` to `CONCLUDED`. It requires the cohort to be in `IN_SESSION` (otherwise `ERR_INVALID_STATE`) and the clock to have reached or passed the cohort's `ends_at`, or it fails with `ERR_COHORT_WINDOW_NOT_OPEN`. Concluding triggers two effects: every enrollment on the cohort that is currently `ACTIVE` is transitioned to `COMPLETED` — and each such completion evaluates the student's guarantee eligibility as described in §3.7 — and the assigned instructor's `active_cohort_count` is decremented by one.

Cancelling a cohort is permitted only while it is in `DRAFT` or `SCHEDULED`; from any other state the request is rejected with `ERR_INVALID_STATE`. A `DRAFT` cohort has no enrollments, so cancelling it simply moves it to `CANCELLED`. Cancelling a `SCHEDULED` cohort moves it to `CANCELLED`, cascades a cancellation onto every enrollment on the cohort whose status is `ACTIVE`, `WAITLISTED`, or `PENDING_PAYMENT` (each cancellation firing its own per-enrollment effects, including seat release and any waitlist promotion, exactly as described in §3.4), and — if an instructor was assigned — decrements that instructor's `active_cohort_count` by one.

### 3.3. Enrolling a Student and Pricing the Seat

A prospective learner first becomes a **Student** through anonymous self-registration, supplying an `email` (unique across all students; a registration whose `email` duplicates an existing student is rejected with `ERR_INVALID_REQUEST`) and a `full_name`. A new student's `diagnostic_score` is null and stays null until the student's first diagnostic practice test is scored (see §3.5).

A `Student` (or a Registrar acting for one) creates an **Enrollment** by supplying the `student_id`, the target `cohort_id`, the `expected_cohort_version` required by §2.6, and an optional `coupon_code`. The platform evaluates the request in a fixed order. After authentication, authorization, and existence resolution, it confirms the body is well-formed and its enums and ranges are valid, failing otherwise with `ERR_INVALID_REQUEST`. If a `coupon_code` is supplied, it must be either `EARLYBIRD` or `REFER50`; any other value is rejected with `ERR_INVALID_COUPON`. The student must not already hold a non-terminal enrollment — one in `PENDING_PAYMENT`, `WAITLISTED`, `ACTIVE`, or `COMPLETED` — in this same cohort, or the request fails with `ERR_DUPLICATE_ENROLLMENT`. Then a schedule-conflict check runs (described in §3.4) before the seat-versus-waitlist branch is chosen. Throughout, the `expected_cohort_version` is matched against the cohort's current `version`; a mismatch yields `ERR_STALE_VERSION`.

Pricing happens at creation and is recorded on the enrollment's `price_paid_cents`. The base is the course's `list_price_cents`. A coupon, if present, sets a discount before any installment split: the `EARLYBIRD` coupon discounts 15 percent of the list price, rounded half up to whole cents; the `REFER50` coupon discounts a flat 5000 cents regardless of list price. With no coupon the discount is zero. The net `price_paid_cents` is the base minus the discount, floored at zero so it can never go negative.

A successful creation advances the cohort's `version` by one. The enrollment's own `status` begins at `PENDING_PAYMENT`; the lifecycle states an enrollment can occupy are `PENDING_PAYMENT`, `ACTIVE`, `WAITLISTED`, `COMPLETED`, and `CANCELLED`, with `CANCELLED` terminal. Several other enrollment fields are computed over its lifetime and default as follows: `completed_practice_count` and `sessions_attended` start at 0, `best_practice_score`, `materials_expire_at`, and `waitlist_seq` start null, and `guarantee_status` starts at `PENDING`. Recording attendance (the `/enrollments/{id}/attendance` action, available to an Instructor or Registrar in any enrollment state) overwrites `sessions_attended` with the supplied integer count, which must be zero or greater (otherwise `ERR_INVALID_REQUEST`); it is an absolute set, not an increment.

### 3.4. Seat Allocation, the Waitlist, and Cancellation

Whether a new enrollment claims a seat or joins the waitlist is decided at creation time. The cohort is considered full when its `seats_committed` plus the count of outstanding non-waitlisted `PENDING_PAYMENT` holds already reaches or exceeds `seat_capacity`. If a seat is available the new enrollment lands in `PENDING_PAYMENT` holding that seat; if the cohort is full it lands in `WAITLISTED` and is assigned a `waitlist_seq` equal to one plus the highest existing `waitlist_seq` among waitlisted peers on the cohort (or 1 when none are waitlisted yet), establishing a first-come ordering by creation time.

Before that branch is even evaluated, the platform enforces a student schedule-conflict rule: a student may not enroll into a cohort whose session window overlaps the window of any other cohort in which the student already holds a non-terminal `PENDING_PAYMENT`, `WAITLISTED`, or `ACTIVE` enrollment. This overlap test is **closed-interval and buffer-inclusive** — unlike the half-open instructor test, here two windows that merely touch at a boundary do count as a conflict. A violation is rejected with `ERR_STUDENT_SCHEDULE_CONFLICT`.

Activation is the act of committing a held seat once payment has settled, and it advances a `PENDING_PAYMENT` enrollment to `ACTIVE`. A Registrar performs it. It requires the enrollment to be in `PENDING_PAYMENT` (otherwise `ERR_INVALID_STATE`); it requires that an installment plan exists for the enrollment whose `amount_paid_cents` is at least the first installment's amount, or the request fails with `ERR_PAYMENT_NOT_SETTLED`; it requires the parent cohort to be in `SCHEDULED` or `IN_SESSION`, or it fails with `ERR_COHORT_NOT_ENROLLABLE`; and it requires a free committed seat — the cohort's `seats_committed` must be strictly less than `seat_capacity`, or it fails with `ERR_COHORT_FULL`. On success the enrollment's `materials_expire_at` is set to the current clock instant plus the course's `materials_access_days` days, and the cohort's `seats_committed` is recomputed (rising by one).

Cancellation is available to the owning `Student` (or a Registrar) and, like creation, is OCC-guarded — the body must carry `expected_cohort_version` matching the cohort's current `version`, failing with `ERR_STALE_VERSION` otherwise. Cancellation is defined out of three states, and each fires its own effects. Cancelling an `ACTIVE` enrollment moves it to `CANCELLED`, recomputes the cohort's `seats_committed` downward by one to release the seat, promotes the lowest-`waitlist_seq` waitlisted enrollment on the cohort (see promotion below), and — if the enrollment has an `OPEN` installment plan — transitions that plan from `OPEN` to `REFUNDED`. Cancelling a `WAITLISTED` enrollment moves it to `CANCELLED` and clears its `waitlist_seq`; there is no seat to release and no promotion. Cancelling a `PENDING_PAYMENT` enrollment moves it to `CANCELLED`, releases its held seat and recomputes `seats_committed`, and promotes the lowest-`waitlist_seq` waitlisted enrollment if one exists. Every successful cancellation advances the cohort's `version` by one.

Waitlist promotion is the system-driven response to a freed seat. When a committed or held seat is released on a cohort, the waitlisted enrollment with the lowest `waitlist_seq` is promoted from `WAITLISTED` back to `PENDING_PAYMENT`: its `waitlist_seq` is cleared to null and it now occupies a held seat awaiting payment. Promotion is the bridge that lets a released seat immediately become reclaimable by the next student in line.

### 3.5. Diagnostics, Practice Tests, and Scoring

Score history lives on **PracticeAttempt** records, each tied to a single enrollment via `enrollment_id`. A student or instructor starts an attempt by supplying that `enrollment_id`, the `attempt_type` (either `DIAGNOSTIC` for the baseline test or `PRACTICE` for a scored practice test), the `raw_correct` count of correct items (zero or greater, and no more than `total_items`), and the `total_items` count (one or greater). A `raw_correct` below zero or a `total_items` below one is rejected with `ERR_INVALID_REQUEST`; once those type/range checks pass, a `raw_correct` exceeding `total_items` or a prospective `scaled_score` (computed as at scoring) exceeding the course's `baseline_scale_max` is rejected at creation time with `ERR_SCORE_OUT_OF_RANGE`. A new attempt is created in `STARTED` status; its terminal states are `COMPLETED` and `VOIDED`. The computed `scaled_score` and `percentile` are not populated until the attempt is scored.

Scoring an attempt is an instructor-only action that advances `STARTED` to `COMPLETED`. It requires the attempt to be in `STARTED` (otherwise `ERR_INVALID_STATE`); it requires that `raw_correct` not exceed `total_items` and that the resulting `scaled_score` not exceed the course's `baseline_scale_max`, failing with `ERR_SCORE_OUT_OF_RANGE` otherwise; and it requires the parent enrollment to be in `ACTIVE` or `COMPLETED`, or it fails with `ERR_ENROLLMENT_NOT_SCORABLE`.

The scaled score is computed from the attempt's correctness ratio and the course's scale. Form the exact ratio of `raw_correct` to `total_items` without pre-rounding, multiply that ratio by the course's `baseline_scale_max`, and round the single resulting product half up to a whole number of points — this is the `scaled_score`. It is essential to round only once at the end: rounding the ratio to an integer first and then multiplying produces a different result at boundary cases (such as a ratio of exactly one-half against an odd scale), and that approach is incorrect. The `percentile` analytics figure is computed separately: divide the `scaled_score` by the course's `baseline_scale_max`, multiply by 100, and round half up to one decimal place.

Scoring then drives two recomputations depending on the attempt type. If the attempt is a `DIAGNOSTIC` and the student's `diagnostic_score` is still null, the student's `diagnostic_score` is set to the just-computed `scaled_score` (this is how the baseline is captured for the guarantee). If the attempt is a `PRACTICE`, the enrollment's `completed_practice_count` is recomputed as the number of its `COMPLETED` `PRACTICE` attempts, and its `best_practice_score` is recomputed as the maximum `scaled_score` over those completed practice attempts (null if there are none).

An instructor may instead void a `STARTED` attempt, advancing it to `VOIDED` (it must be `STARTED`, else `ERR_INVALID_STATE`). A voided attempt records no score and is excluded from all analytics; even an attempt whose `scaled_score` was computed before voiding is excluded from `best_practice_score` and `completed_practice_count`.

The enrollment analytics read offers a provisional, advisory view that differs deliberately from the authoritative guarantee evaluation. Where the final evaluation at cohort conclusion or claim review uses `best_practice_score` (the realized best across completed practice attempts), the analytics projection instead uses the most recent completed practice attempt's `scaled_score` — the latest, not the best — projected against the student's `diagnostic_score`. Because the latest attempt may not be the best, this provisional projection can diverge from the final result and must be treated as advisory only. The analytics read returns the enrollment resource object (carrying all its usual fields, including the authoritative `best_practice_score` and `completed_practice_count`) augmented with an `analytics` sub-object holding `diagnostic_score` (from the student), `best_practice_score`, `latest_practice_score` (the most recent completed practice attempt's `scaled_score`, or null), `projected_improvement` (`latest_practice_score` minus `diagnostic_score`, or null when either is null), `completed_practice_count`, `attendance_pct` (`sessions_attended` divided by `total_sessions`, reported as the raw fraction even for `SELF`-format cohorts, or null when `total_sessions` is 0), and `latest_percentile` (the percentile of `latest_practice_score`, or null). The latest completed practice attempt is the one with the most recent creation order.

### 3.6. Financing: Installment Plans and Payments

A `Student` (or Registrar) finances an enrollment by creating an **InstallmentPlan**, supplying the enrollment's `enrollment_id` and a `num_installments` that must be one of 1, 2, 3, 4, 6, or 12. At creation the plan's `total_financed_cents` is captured from the enrollment's `price_paid_cents`, and `amount_paid_cents` starts at 0. The plan's `status` begins at `OPEN`; its terminal states are `PAID_IN_FULL`, `DEFAULTED`, and `REFUNDED`.

The plan's schedule splits `total_financed_cents` into `num_installments` integer-cent amounts that sum exactly to the total — no cent is created or lost. Compute the base per-installment amount as the total divided by the number of installments, discarding any fractional cent (the floor). The leftover remainder — the total minus the base amount multiplied by the number of installments — is a whole number of cents strictly less than the installment count; allocate those remainder cents one cent each to the earliest installments by index, lowest index first. Thus when the total divides evenly the remainder is zero and every installment is equal, and when it does not divide evenly the first installments (as many as the remainder) are exactly one cent larger than the rest, which keeps the schedule deterministic.

Recording a payment is a Registrar action that adds the supplied `amount_cents` (an integer of zero or greater, otherwise `ERR_INVALID_REQUEST`) to the plan's running `amount_paid_cents`. When that running total reaches exactly the plan's `total_financed_cents`, the plan transitions from `OPEN` to `PAID_IN_FULL`; the plan must be `OPEN` for a payment to apply (otherwise `ERR_INVALID_STATE`). A running total that overshoots `total_financed_cents` does not transition the plan and leaves it `OPEN`.

A Registrar may mark an `OPEN` plan as `DEFAULTED` when the logical clock has passed a missed installment's due date (asserted by the operator) and the plan's `amount_paid_cents` is still less than its `total_financed_cents`; the plan must be `OPEN`, and its `amount_paid_cents` must still be below `total_financed_cents` (a fully-paid `OPEN` plan cannot be defaulted) — either condition's failure is rejected with `ERR_INVALID_STATE`. Defaulting cascades: if the parent enrollment is `ACTIVE` or `PENDING_PAYMENT`, that enrollment is transitioned to `CANCELLED`, which in turn releases its seat and promotes the waitlist exactly as in §3.4.

A plan reaches `REFUNDED` only as a cascade — driven either by its parent enrollment being cancelled or by an approved refund guarantee claim — and never by a direct client request. The plan must be `OPEN` to be refunded; on refund its `status` becomes `REFUNDED` and the money returned equals the `amount_paid_cents` already collected, conserving funds so that money returned equals money collected for the enrollment.

### 3.7. The Score-Improvement Guarantee

The guarantee promises that a diligent student who falls short of the promised score gain is made whole. Each enrollment carries a `guarantee_status` that begins `PENDING` and can become `ELIGIBLE`, `INELIGIBLE`, `REFUND_ISSUED`, or `RETAKE_GRANTED`.

Eligibility is evaluated when an enrollment is completed during cohort conclusion, and re-checked when a claim is moved into review. The evaluation has four prerequisites that must all hold, plus a guarantee-miss test. First, attendance: for a `SELF`-format course attendance is ignored and considered satisfied, while for any other format the attendance fraction — the enrollment's `sessions_attended` divided by the cohort's `total_sessions` — must be at least the course's `required_attendance_pct` (the boundary value itself counts as satisfied). Second, practice volume: the enrollment's `completed_practice_count` must be at least the course's `required_practice_tests`. Third, the student must have both a recorded `diagnostic_score` and a non-null `best_practice_score`. The guarantee-miss test then compares the realized improvement — the enrollment's `best_practice_score` minus the student's `diagnostic_score` — against the course's `guarantee_min_delta`: the guarantee is considered missed only when that improvement is strictly less than `guarantee_min_delta`, so a student who meets the promised delta exactly has not missed it. When all prerequisites hold and the guarantee was missed, the enrollment's `guarantee_status` is set to `ELIGIBLE`; otherwise it is set to `INELIGIBLE`.

A `Student` (or Registrar) files a **GuaranteeClaim** by supplying the `enrollment_id` and a requested `resolution` of either `REFUND` or `RETAKE`. A new claim is created in `FILED` status; its lifecycle states are `FILED`, `UNDER_REVIEW`, `APPROVED`, and `REJECTED`, with the last two terminal.

A Registrar reviews a claim, advancing `FILED` to `UNDER_REVIEW`. The claim must be `FILED` (otherwise `ERR_INVALID_STATE`), and the parent enrollment's `guarantee_status` must be `ELIGIBLE`, or the request is rejected with `ERR_GUARANTEE_NOT_ELIGIBLE`. Moving into review records the claim's `improvement_delta` as the enrollment's `best_practice_score` minus the student's `diagnostic_score`.

Approval advances `UNDER_REVIEW` to `APPROVED` and branches on the claim's `resolution`. The claim must be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`), and the recorded `improvement_delta` must be strictly less than the course's `guarantee_min_delta`; if the student actually met or exceeded the delta the guarantee was satisfied and approval is rejected with `ERR_GUARANTEE_THRESHOLD_MET`. On a `REFUND` resolution, the claim's `refund_amount_cents` is set to the conserved refund amount, the enrollment's `guarantee_status` becomes `REFUND_ISSUED`, and the enrollment's `OPEN` installment plan (if any) cascades from `OPEN` to `REFUNDED`. The refund amount returns exactly what the student paid toward this enrollment: when an installment plan exists it equals that plan's `amount_paid_cents` (which may be less than `price_paid_cents` if installments remain; when more than one plan exists for the enrollment, the most recently created plan supplies the `amount_paid_cents`), and when no plan exists it equals the enrollment's `price_paid_cents`; this exact figure is taken with no proration and no rounding. On a `RETAKE` resolution, the enrollment's `guarantee_status` becomes `RETAKE_GRANTED`, the claim's `refund_amount_cents` stays 0, and the enrollment's `materials_expire_at` is extended by another `materials_access_days` days so the student can prepare again — the extension is measured from the existing `materials_expire_at` instant (or from the current clock instant if `materials_expire_at` was never set).

Rejection advances `UNDER_REVIEW` to `REJECTED` (the claim must be `UNDER_REVIEW`, else `ERR_INVALID_STATE`) and sets the parent enrollment's `guarantee_status` back to `INELIGIBLE`, granting neither refund nor retake.

### 3.8. Materials Access

Once an enrollment is activated, its course materials remain reachable until the enrollment's `materials_expire_at` instant. A materials read is denied — rejected with `ERR_MATERIALS_EXPIRED` — when the logical clock is at or after `materials_expire_at`, and likewise when `materials_expire_at` is still null (the enrollment was never activated, so no access window was ever granted). As noted in §3.7, a granted retake extends `materials_expire_at` by another full `materials_access_days` window, reopening access for the retake period.

### 3.9. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the most fundamental failure surfaces first. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization including resource ownership (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`, path identifiers left-to-right before body foreign keys), then request well-formedness and type/range validity (`ERR_INVALID_REQUEST`). For enrollment creation the coupon-validity check (`ERR_INVALID_COUPON`) follows request validation. State-machine legality (`ERR_INVALID_STATE`) is then checked on transition endpoints before any domain-specific business rule. Only after all of those do the business rules of the specific workflow apply — instructor certification, time conflict, and load on scheduling; clock windows on start and conclude; duplicate-enrollment and student-schedule-conflict on creation; payment-settled, cohort-enrollable, and cohort-full on activation; score range on scoring; guarantee eligibility and threshold on claim adjudication; and the OCC version match where it applies.

## 4. Endpoint Definitions

Endpoints that create a new, distinct resource return `201 Created`. Endpoints that modify an existing resource — including all state-transition actions — return `200 OK`. The full request and response shapes are determined by the workflow narratives in §3; the table below lists only method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/courses` | Create a catalog course (DRAFT) | Registrar |
| POST | `/courses/{id}/publish` | Publish a DRAFT course | Registrar |
| POST | `/courses/{id}/retire` | Retire a PUBLISHED course | Registrar |
| GET | `/courses` | List/filter catalog courses | Anonymous, Student, Instructor, Registrar |
| GET | `/courses/{id}` | Read one course | Anonymous, Student, Instructor, Registrar |
| GET | `/courses/{id}/cohorts` | List cohorts for a course | Anonymous, Student, Instructor, Registrar |
| POST | `/instructors` | Create an instructor | Registrar |
| GET | `/instructors/{id}` | Read one instructor | Registrar, Instructor |
| GET | `/instructors/{id}/cohorts` | List cohorts assigned to an instructor | Registrar, Instructor |
| POST | `/cohorts` | Create a cohort under a published course | Registrar |
| GET | `/cohorts/{id}` | Read one cohort | Anonymous, Student, Instructor, Registrar |
| POST | `/cohorts/{id}/schedule` | Assign instructor and move DRAFT to SCHEDULED | Registrar |
| POST | `/cohorts/{id}/start` | Begin a scheduled cohort | Registrar |
| POST | `/cohorts/{id}/conclude` | Conclude an in-session cohort | Registrar |
| POST | `/cohorts/{id}/cancel` | Cancel a draft/scheduled cohort | Registrar |
| GET | `/cohorts/{id}/enrollments` | List enrollments for a cohort | Registrar, Instructor |
| POST | `/students/register` | Public student self-registration | Anonymous |
| GET | `/students/{id}` | Read one student | Student, Registrar |
| GET | `/students/{id}/enrollments` | List a student's enrollments | Student, Registrar |
| POST | `/enrollments` | Enroll a student into a cohort | Student, Registrar |
| GET | `/enrollments/{id}` | Read one enrollment | Student, Instructor, Registrar |
| POST | `/enrollments/{id}/activate` | Activate a paid pending enrollment | Registrar |
| POST | `/enrollments/{id}/cancel` | Cancel an enrollment | Student, Registrar |
| POST | `/enrollments/{id}/attendance` | Record attended-session count | Instructor, Registrar |
| GET | `/enrollments/{id}/analytics` | Computed analytics read | Student, Instructor, Registrar |
| GET | `/enrollments/{id}/materials` | Access course materials | Student, Registrar |
| GET | `/enrollments/{id}/practice-attempts` | List practice attempts for an enrollment | Student, Instructor, Registrar |
| GET | `/enrollments/{id}/installment-plans` | List installment plans for an enrollment | Student, Registrar |
| GET | `/enrollments/{id}/guarantee-claims` | List guarantee claims for an enrollment | Student, Registrar |
| POST | `/practice-attempts` | Start a diagnostic or practice attempt | Student, Instructor |
| GET | `/practice-attempts/{id}` | Read one practice attempt | Student, Instructor, Registrar |
| POST | `/practice-attempts/{id}/score` | Score a STARTED attempt to COMPLETED | Instructor |
| POST | `/practice-attempts/{id}/void` | Void a STARTED attempt | Instructor |
| POST | `/installment-plans` | Create a financing plan for an enrollment | Student, Registrar |
| GET | `/installment-plans/{id}` | Read one installment plan | Student, Registrar |
| POST | `/installment-plans/{id}/payments` | Record a succeeded installment payment | Registrar |
| POST | `/installment-plans/{id}/default` | Mark an OPEN plan DEFAULTED | Registrar |
| POST | `/guarantee-claims` | File a guarantee claim for an enrollment | Student, Registrar |
| GET | `/guarantee-claims/{id}` | Read one guarantee claim | Student, Registrar |
| POST | `/guarantee-claims/{id}/review` | Move FILED to UNDER_REVIEW | Registrar |
| POST | `/guarantee-claims/{id}/approve` | Approve a claim (REFUND or RETAKE branch) | Registrar |
| POST | `/guarantee-claims/{id}/reject` | Reject a claim under review | Registrar |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_COUPON` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COURSE_NOT_PUBLISHED` | 409 |
| `ERR_INSTRUCTOR_NOT_CERTIFIED` | 409 |
| `ERR_INSTRUCTOR_TIME_CONFLICT` | 409 |
| `ERR_INSTRUCTOR_OVERLOADED` | 409 |
| `ERR_COHORT_WINDOW_NOT_OPEN` | 409 |
| `ERR_COHORT_NOT_ENROLLABLE` | 409 |
| `ERR_COHORT_FULL` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_STUDENT_SCHEDULE_CONFLICT` | 409 |
| `ERR_PAYMENT_NOT_SETTLED` | 409 |
| `ERR_ENROLLMENT_NOT_SCORABLE` | 409 |
| `ERR_SCORE_OUT_OF_RANGE` | 422 |
| `ERR_MATERIALS_EXPIRED` | 403 |
| `ERR_GUARANTEE_NOT_ELIGIBLE` | 409 |
| `ERR_GUARANTEE_THRESHOLD_MET` | 409 |
| `ERR_STALE_VERSION` | 412 |
