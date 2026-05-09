# Course Registration API — Product Requirements Document

## 1. Introduction

A modern research university operates across multiple campuses, with thousands of students whose enrollment plans span their home program, cross-departmental electives, and (with departmental consent) courses owned by partner programs. The Course Registration API is the system of record for that enrollment process: it accepts student registration requests, evaluates them against an interlocking lattice of academic, temporal, fiscal, and safety constraints, and emits the downstream events that academic affairs, finance, the library, and dormitory services rely on.

The system must remain trustworthy in two opposing operating modes. During the long quiet periods between terms it is a slow editorial workflow — registrars defining course catalogs, professors arranging teaching loads, students browsing recommendations. During the registration peak it becomes a contention engine: thousands of students racing for the last seats in popular offerings, professors countersigning over-limit petitions under deadline, and the registrar's office reshaping capacity in real time. The API specified here must serve both modes from a single, deterministic contract — every approval, waitlist promotion, conflict rejection, and downstream synchronization must be reproducible from inputs and the rules below, with no implementation latitude on what the rules mean.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide conventions that apply across every endpoint: authentication, response shape, pagination, hierarchical reconciliation, identifier formats, numeric precision, concurrency control, and the cross-cutting operating principles that govern the registration domain.

### 2.1. User and Role-Based Access Control

Every API call must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Requests missing or malforming either header are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). When the role is present but is not authorized for the requested endpoint per the role-to-endpoint matrix described in §4, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

The system recognizes exactly four roles: `Registrar`, `Student`, `Professor`, and `Finance`. Their identity semantics differ:

- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`. Ownership checks on any resource that references a `Student` (for example the `student_id` on an `EnrollmentRequest` or `OverLimitApplication`) compare the resource's foreign-key field to `X-User-ID`; a mismatch is rejected with `ERR_NOT_OWNER` (403). The same ownership rule scopes a `Student`'s reads of their own profile, degree plan, recommendations, sync events, and enrollment requests.
- When `X-User-Role` is `Professor`, `X-User-ID` is the `id` of the acting `Professor`. On an `OverLimitApplication`, the server compares `X-User-ID` to the application's `primary_signer_id` or `secondary_signer_id` for the current step; a mismatch is rejected with `ERR_NOT_DESIGNATED_SIGNER` (403).
- When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `Finance`, `X-User-ID` is likewise an opaque operator identifier (for example a downstream finance webhook's signed principal). It is not compared to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via the `limit` and `offset` query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0; it may not be negative. A request whose `limit` is below 1, above 100, or whose `offset` is below 0 is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (400).

Unless otherwise specified, list endpoints return resources sorted by their creation timestamp in ascending order. List responses include the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Most top-level resources — `Department`, `Campus`, `Student`, `Professor`, `Term`, `Course`, `CourseOffering`, `LabEquipment`, `EnrollmentRequest`, `OverLimitApplication`, `DepartmentAccessGrant` — carry the following four system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID. Identifiers are issued by the server; clients never provide one. The UUID has no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating the most recent modification. The system refreshes this field on any change to the resource's persisted state, including state-machine transitions and side-effect-driven mutations such as `enrolled_count` increments or `capacity` rewrites.
- `version` (integer): a monotonically increasing counter that begins at 1 on creation and is incremented by 1 on every persisted mutation. It is the basis for the optimistic concurrency check described in §2.7.

Two resources omit `updated_at` and `version` because they are immutable once written by the system: a `WaitlistEntry` and a `SyncEvent` both carry only `id` and `created_at`. A `CreditEquivalencePolicy` likewise carries only `id` and `created_at`. When a downstream concept of these entities needs to evolve (for example, a different transfer ratio between the same two programs), a new policy is created rather than the old one mutated.

### 2.5. Numeric Precision and Rounding

Three numeric domains live in this system, and each has its own precision rule:

- **Credit hours.** All credit-hour quantities — `Course.credits`, the per-student `provisional_credit_charge` and `final_credit_charge` on an `EnrollmentRequest`, the `requested_extension_credits` and `granted_credits` on an `OverLimitApplication`, and every aggregate that derives from them (the dynamic credit quota's `current_load`, the degree plan's `completed_credits`, `in_progress_credits`, `total_required_credits`, `remaining_credits`, and the cross-program `transferable_credits` figure) — are stored and returned with two decimal places, rounded half-up.
- **Scoring.** All scoring quantities are integers: the `priority_score` on an `EnrollmentRequest` and on a `WaitlistEntry`, the `fraud_score` on a `Student`, and the recommendation score in §3.8. Where a formula produces an intermediate non-integer value, the final score is truncated toward zero after summation.
- **Schedule minutes.** All clock-of-day and weekly-minute quantities are integers, including each meeting's `start_minute_of_day` and `end_minute_of_day`, the per-equipment `setup_buffer_minutes`, the `Professor.max_concurrent_teaching_minutes_per_week`, and the inter-campus values inside `Campus.commute_minutes_to`.

### 2.6. Optimistic Concurrency Control

Mutating endpoints that target a specific resource by id may include the resource's current `version` number in the request body. If `version` is supplied and does not match the server's current `version` for that resource, the request is rejected with `ERR_VERSION_CONFLICT` (409); on a successful mutation `version` is incremented by 1. If the `version` field is omitted from the body, the server processes the mutation without performing the version check, accepting the risk of a lost update. Two `Registrar` requests that race to update the same `OverLimitApplication` or the same `CourseOffering` with stale versions serialize first-writer-wins on `version`; the second writer receives `ERR_VERSION_CONFLICT`.

### 2.7. Hierarchical Consistency and Cascading State Reconciliation

The registration domain is a graph of interdependent resources: a `Term` contains `CourseOffering`s, an offering's `enrolled_count` is a function of `EnrollmentRequest`s pointing at it, a request's `financial_status` reflects whether `Finance` has settled tuition, and a `WaitlistEntry` lives or dies based on what happens upstream on its offering and on the requesting student's other enrollments. The system maintains consistency across this graph by transitioning dependent resources automatically whenever an upstream event invalidates their state — without requiring an explicit client request on each dependent resource. Each such automatic mutation refreshes the dependent resource's `updated_at` and increments its `version`. A few representative cascades:

- When a `Term` advances from `REGISTRATION_OPEN` to `REGISTRATION_CLOSED`, every `EnrollmentRequest` whose `academic_status` is still `SUBMITTED` is rejected and every `WaitlistEntry` whose `status` is still `ACTIVE` is expired.
- When a `CourseOffering` advances from `OPEN` to `CLOSED`, every `WaitlistEntry` for that offering whose `status` is still `ACTIVE` is expired and every `EnrollmentRequest` for that offering whose `academic_status` is still `SUBMITTED` is rejected.
- When a `Student` cancels an `APPROVED` enrollment, the offering's `enrolled_count` is decremented, the student's provisional credit usage is decremented by the course's `credits`, and the offering's waitlist is swept for an immediate promotion.
- When a `Term` advances to `CONCLUDED`, every `APPROVED` enrollment whose `financial_status` is `PAID` advances its `academic_status` to `SETTLED` and has `final_credit_charge` populated; every `APPROVED` enrollment whose `financial_status` is not `PAID` instead has `academic_status` rewritten to `REJECTED`.

The detailed cascade for each transition is given in §3, where it is told as part of the workflow that triggers it.

### 2.8. Nested Resource Retrieval

Endpoint paths that contain multiple resource identifiers (for example a path naming a `studentId` that owns a sub-resource) are validated left-to-right. The first identifier in the path that does not correspond to an existing resource produces the matching not-found error from the table of resource-specific not-found codes (`ERR_STUDENT_NOT_FOUND`, `ERR_PROFESSOR_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_CAMPUS_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_LAB_EQUIPMENT_NOT_FOUND`), each at HTTP 404. The check halts on the first miss; later segments are not reached.

### 2.9. Validation Ordering and Error Precedence

Several endpoints — most notably the enrollment-request submission endpoint — apply many validations to a single payload. Validations are evaluated in a fixed priority order so that a request which violates more than one rule receives a deterministic, single-cause error. The priority list is:

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400). This precedes everything; an unauthenticated request is never told why its payload is also wrong.
2. Role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403).
3. Existence of every path identifier, validated left-to-right per §2.8.
4. Lifecycle-state preconditions on the target entity (`ERR_INVALID_STATE` and the more specific subtypes such as `ERR_TERM_NOT_OPEN_FOR_REGISTRATION`, `ERR_OFFERING_NOT_OPEN`, `ERR_TERM_LOCKED_FOR_CANCEL`, `ERR_TERM_NOT_READY_FOR_CONCLUDE`, and `ERR_INVALID_STATE_FOR_SETTLE`).
5. Cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY` and the over-limit-application signer subtypes `ERR_SIGNER_NOT_IN_HOME_DEPARTMENT`, `ERR_PRIMARY_SIGNER_IS_CHAIR`, `ERR_SECONDARY_SIGNER_NOT_CHAIR`).
6. Cross-department access permission (`ERR_CROSS_DEPARTMENT_ACCESS_DENIED`, 403).
7. Prerequisite satisfaction (`ERR_PREREQUISITE_NOT_MET`, 422).
8. Time-of-week conflict against the student's existing enrollments (`ERR_TIME_CONFLICT`, 409).
9. Inter-campus commute infeasibility (`ERR_COMMUTE_INFEASIBLE`, 409).
10. Exam-week conflict (`ERR_EXAM_TIME_CONFLICT`, 409).
11. Lab equipment conflict (`ERR_LAB_EQUIPMENT_CONFLICT`, 409).
12. Credit quota (`ERR_CREDIT_QUOTA_EXCEEDED`, 402).
13. Anti-fraud rate limit (`ERR_RATE_LIMITED`, 429).
14. Instructor teaching-load cap on opening a `CourseOffering` (`ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED`, 409). This priority does not race with the enrollment-submission priorities because it gates a different endpoint.
15. Pagination limits (`ERR_INVALID_PAGINATION_PARAMETERS`, 400).
16. Optimistic concurrency check on `version` (`ERR_VERSION_CONFLICT`, 409), evaluated last among body validations on `PATCH` and `PUT` so that a payload which is otherwise unacceptable is not masked by a stale-version error.

When a single request would fail more than one priority level, the **lower-numbered** priority wins and is reported.

### 2.10. The Cross-Department Permission Matrix

Departments grant their courses to other departments' students through a `DepartmentAccessGrant`. A grant names a `source_department_id` (the department whose students gain access), a `target_department_id` (the department whose courses become enrollable by source-department students), and a `course_categories_allowed` list of free-form category strings restricting which of the target department's courses are reachable. An empty `course_categories_allowed` list is significant: it explicitly disables the grant for every category, rather than implicitly authorizing all of them. A grant carries a `bidirectional` flag; when `true`, the symmetric grant from `target_department_id` back to `source_department_id` covering the same categories is implied without a separate row. A grant has a `status` of `ACTIVE` on creation and may be moved to `REVOKED`; `REVOKED` grants no longer satisfy the cross-department access check described in §3.4.

### 2.11. Anti-Fraud and Rate-Limiting Safeguards

The system maintains a per-student `fraud_score` integer that begins at zero on creation of a `Student` and accumulates as suspicious patterns are observed. There is no decay; the score only grows. Two signals contribute to the score:

- **Rapid resubmission.** When a student submits more than ten enrollment requests in any sixty-second window — that is, when the count of the student's enrollment requests created in the prior sixty seconds, as measured at submission time, strictly exceeds ten — the student's `fraud_score` is incremented by five and the over-limit submission itself is rejected with `ERR_RATE_LIMITED` (429). The same rate limit applies to over-limit-application submissions.
- **Unauthorized-department probing.** When a student submits an enrollment request against a `CourseOffering` whose course belongs to a department other than the student's `program_department_id`, and no `ACTIVE` `DepartmentAccessGrant` covers the (student's home department → course's owning department) pair for that course's category, the student's `fraud_score` is incremented by eight in addition to the priority-6 rejection.

The `fraud_score` is then a direct input into the waitlist priority calculation in §3.5: each unit of `fraud_score` above a grace threshold of ten subtracts from the score that decides waitlist position.

### 2.12. Event-Driven Synchronization with External Systems

Several state transitions emit a `SyncEvent` for downstream consumption. A `SyncEvent` records the producing entity's type as `subject_entity` and its identifier as `subject_id`, the `event_type` from a fixed enumeration, the `target_systems` set of downstream consumers drawn from `ACADEMIC_AFFAIRS`, `FINANCE`, `LIBRARY`, and `DORMITORY`, and an event-specific `payload` object. The recognized `event_type` values and their default fan-out are:

- `ENROLLMENT_APPROVED`, fanned out to all four downstream systems.
- `ENROLLMENT_CANCELED`, fanned out to all four.
- `TUITION_BILLED`, sent only to `FINANCE`.
- `TUITION_PAID`, sent to `FINANCE`, `LIBRARY`, and `DORMITORY`.
- `OVER_LIMIT_GRANTED`, sent to `ACADEMIC_AFFAIRS` and `FINANCE`.
- `CAPACITY_REDUCED_CANCELED`, sent to all four.
- `WAITLIST_PROMOTED`, fanned out to all four (matching the underlying `ENROLLMENT_APPROVED` reach because a promotion is functionally an approval).

Reading a student's sync log returns the `SyncEvent` rows whose `subject_entity` chain traces back to that student.

### 2.13. The Logical Clock and the Periodic Sweep

Several transitions in this system are gated by wall-clock time: a `Term` advances between its lifecycle states based on `registration_open_at`, `registration_close_at`, `classes_start_at`, and `exam_window_end_at`; an `OverLimitApplication` escalates and expires based on `timeout_deadline_at`. To make these transitions reproducible under test, the system exposes two `Registrar`-only operating capabilities:

- A test-driving capability that advances the system's logical clock to a supplied `target_unix_seconds` instant. When the clock advances, all auto-transitions whose preconditions become satisfied fire in a canonical order: first any `Term` whose `clock` reaches `registration_open_at` advances `PLANNING → REGISTRATION_OPEN`; then any `Term` whose `clock` reaches `registration_close_at` advances `REGISTRATION_OPEN → REGISTRATION_CLOSED` with the cascade in §2.7; then any `OverLimitApplication` in `AWAITING_PRIMARY` whose `clock` reaches `timeout_deadline_at` escalates to `AWAITING_SECONDARY`; then any `OverLimitApplication` in `AWAITING_SECONDARY` whose `clock` reaches `timeout_deadline_at` expires; then any `Term` whose `clock` reaches `classes_start_at` advances `REGISTRATION_CLOSED → IN_SESSION`.
- A sweep capability that, on demand, runs the periodic waitlist promotion across every `OPEN` `CourseOffering` (in offering-`id` ascending order) and the `OverLimitApplication` deadline checks. For each `OPEN` offering the sweep promotes `ACTIVE` waitlist entries one at a time, in the priority order defined in §3.5, until either no `ACTIVE` entries remain or the offering's `enrolled_count` matches its `capacity`. Any over-limit applications whose `timeout_deadline_at` has fallen at or before the current clock are escalated or expired per the state machine.

A `clock` value referenced in this document refers to the system's current logical clock instant in Unix epoch seconds. `Term` boundaries use inclusive lower bounds and exclusive upper bounds throughout: a request issued exactly at `registration_open_at` is accepted; one issued exactly at `registration_close_at` is rejected.

## 3. Business Logic & Workflows

### 3.1. The Term Lifecycle and the Registration Window

A `Term` is the temporal container in which a registration cycle takes place. A `Registrar` creates a term in `PLANNING` by supplying a unique `code`, the four time anchors `registration_open_at`, `registration_close_at`, `classes_start_at`, and `exam_window_start_at`, and the closing `exam_window_end_at`. A term then passes through five lifecycle values: `PLANNING`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `IN_SESSION`, and `CONCLUDED`.

The first three transitions are time-driven and fire automatically as the logical clock reaches each anchor. The transition `PLANNING → REGISTRATION_OPEN` carries no side effects beyond the status change; from this instant, a `Student` may submit enrollment requests. The transition `REGISTRATION_OPEN → REGISTRATION_CLOSED` is the most consequential of the auto-transitions: every `EnrollmentRequest` that is still in `SUBMITTED` is moved to `REJECTED` (the rejection is recorded as having occurred because registration closed), and every `WaitlistEntry` whose `status` is still `ACTIVE` is moved to `EXPIRED`. The transition `REGISTRATION_CLOSED → IN_SESSION` again carries no side effects, and the final transition `IN_SESSION → CONCLUDED` is the only one that is operator-driven: a `Registrar` invokes the term-conclusion capability, but the request is rejected with `ERR_TERM_NOT_READY_FOR_CONCLUDE` unless the logical clock has reached `exam_window_end_at` (lower-bound inclusive). On a successful conclusion, every `APPROVED` `EnrollmentRequest` whose `financial_status` is `PAID` advances to `SETTLED` and has its `final_credit_charge` populated per the final variant of the dynamic credit quota in §3.6; symmetrically, every `APPROVED` enrollment whose `financial_status` is not `PAID` is moved to `REJECTED` (recorded as canceled because tuition was unpaid) and emits an `ENROLLMENT_CANCELED` `SyncEvent` to all four downstream systems.

### 3.2. Catalog Foundations: Departments, Campuses, Equipment, and the Course Catalog

Before any course can be offered, a `Registrar` populates the supporting catalog. A `Department` is created with a `code`, a human-readable `name`, and the `campus_id` it primarily lives on. A `Campus` is created with a `code`, a human-readable `name`, and the `commute_minutes_to` map described in §3.4. A `LabEquipment` record is created with the `campus_id` housing it, a short `name` (for display, e.g. "Spectrometer-A"), and the `setup_buffer_minutes` introduced in §3.4.

A `Course` is the catalog entry for a body of academic material. A `Registrar` creates a course by supplying a `code` (unique within the `owning_department_id`), a `title`, the `credits` value (a positive number with two-decimal precision), the `owning_department_id`, an array of `prerequisite_course_ids` whose entries each carry a referenced `course_id` plus a `mode` of either `REQUIRED` or `RECOMMENDED`, and an array of `equivalent_course_ids`.

Only `REQUIRED` prerequisite entries gate enrollment; `RECOMMENDED` entries are advisory and surface in degree-plan recommendations only. The equivalence list provides controlled substitution for prerequisite checking: if a prospective student has any course in `equivalent_course_ids` recorded on their `completed_course_ids`, the system treats the equivalent as having satisfied this course for the purpose of the prerequisite check, but **only** for prerequisite checking — equivalences do not satisfy degree-plan requirements in the gap analysis.

### 3.3. Course Offerings, Capacity, and the Instructor Teaching Load

A `CourseOffering` is a specific scheduled instance of a `Course` taught in a given `Term`. A `Registrar` creates an offering in `PLANNED` by supplying the `term_id`, `course_id`, `campus_id` where the offering meets, the `instructor_id`, the integer `base_capacity` (which is set once and immutable), the `scheduled_meetings` array, and the `requires_lab_equipment_ids` list of `LabEquipment` identifiers used during those meetings. On creation, the system populates `capacity` to equal `base_capacity` and `enrolled_count` to zero.

Each entry in `scheduled_meetings` is an object with three integer fields: `day_of_week` (with 0 representing Monday and 6 representing Sunday), `start_minute_of_day` (the minute of day on which the meeting begins, inclusive), and `end_minute_of_day` (the minute of day on which the meeting ends, exclusive). All meeting intervals are therefore half-open: a meeting that ends at minute 600 ends at the instant minute 600 begins, so a different meeting on the same day that begins at minute 600 does **not** overlap it.

When a `Registrar` opens an offering for enrollment, the system advances `PLANNED → OPEN`, but only after two preconditions hold. First, the parent `Term` must be in `REGISTRATION_OPEN`; otherwise the request fails with `ERR_TERM_NOT_OPEN_FOR_REGISTRATION` (409). Second, the instructor's accumulated teaching load — the sum across all the instructor's `OPEN` and `IN_SESSION` offerings of the per-meeting durations (each computed as `end_minute_of_day` minus `start_minute_of_day` and summed across `scheduled_meetings`) — plus the new offering's per-week meeting minutes must not strictly exceed the instructor's `max_concurrent_teaching_minutes_per_week`. If the new total would strictly exceed that cap, the request fails with `ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED` (409). The boundary case where the new total is exactly equal to the cap is permitted.

Closing an offering is the symmetric operator action: a `Registrar` advances `OPEN → CLOSED`, with no precondition. The closing carries two cascades: every `WaitlistEntry` for this offering whose `status` is still `ACTIVE` is moved to `EXPIRED`, and every `EnrollmentRequest` for this offering whose `academic_status` is still `SUBMITTED` is moved to `REJECTED`. The two further offering transitions, `CLOSED → IN_SESSION` and `IN_SESSION → CONCLUDED`, are system-driven and fire as the parent `Term` makes the corresponding transition.

A `Registrar` can also rescale an offering's capacity at any time it is `PLANNED`, `OPEN`, or `CLOSED` by supplying a new value via the elastic-scaling capability; the request body carries `new_capacity` and an optional `version`. Three branches follow:

- If `new_capacity` is greater than the current `capacity`, the offering's `capacity` is set to `new_capacity` and the system attempts to promote up to `new_capacity` minus `enrolled_count` entries from this offering's waitlist. Promotions are taken in waitlist order (described in §3.5). Each promotion advances a `WaitlistEntry` from `ACTIVE` to `PROMOTED` and the underlying `EnrollmentRequest` from `WAITLISTED` to `APPROVED`, with the same `BILLED` and `SyncEvent` side effects as a fresh approval. Each promotion is its own cascade and emits a `WAITLIST_PROMOTED` `SyncEvent`.
- If `new_capacity` is less than the current `capacity` and `new_capacity` is also less than the current `enrolled_count`, the offering is over-allocated and the system cancels (`enrolled_count` minus `new_capacity`) `APPROVED` enrollments to restore the invariant `enrolled_count ≤ capacity`. The cancellations are taken in lowest-priority order — the `EnrollmentRequest`s with the smallest `priority_score` first, with the most recently created request as the secondary tie-break — and each canceled request has its `academic_status` rewritten to `REJECTED` (recorded as cancelled because capacity was reduced), has its `financial_status` reverted to `UNBILLED` if it was `BILLED`, and emits a `CAPACITY_REDUCED_CANCELED` `SyncEvent` to all four downstream systems.
- If `new_capacity` is less than the current `capacity` but is at least as large as the current `enrolled_count`, the capacity is simply reduced and no enrollments are touched.

A capacity-reduction cascade that races a competing capacity write loses with `ERR_CAPACITY_CASCADE_RACE_RETRY` (409); the client is expected to refetch and retry. The capacity write itself participates in the optimistic concurrency check of §2.6 and reports `ERR_VERSION_CONFLICT` if a stale `version` was supplied.

### 3.4. Submitting an Enrollment Request: Conflict Detection and the Seat Decision

A `Student` submits an `EnrollmentRequest` by supplying the target `student_id` (which must equal `X-User-ID` per §2.1 — a mismatch fails with `ERR_NOT_OWNER`) and the target `offering_id`. The system stores `term_id` denormalized from the offering for query convenience. The submission immediately runs the priority-ordered validation cascade introduced in §2.9. The first six business-rule priorities — all of which precede the seat-allocation decision — are described below; the credit-quota and anti-fraud checks follow in §3.6 and §2.11, and the seat decision itself is described at the end of this subsection.

**Cross-department access (priority 6).** When the offering's course belongs to a department different from the student's `program_department_id`, an `ACTIVE` `DepartmentAccessGrant` whose `source_department_id` is the student's home department and whose `target_department_id` is the course's `owning_department_id` must exist, and the course's category must appear in `course_categories_allowed` on that grant. A grant whose `bidirectional` flag is true also satisfies this check when the source/target pair is reversed. Failure produces `ERR_CROSS_DEPARTMENT_ACCESS_DENIED` (403) and additionally increments the student's `fraud_score` per §2.11.

**Prerequisite satisfaction (priority 7).** Every `REQUIRED` entry in the course's `prerequisite_course_ids` must be satisfied. A prerequisite `course_id` is satisfied when it appears in the student's `completed_course_ids`, or when any `course_id` in the prerequisite's `equivalent_course_ids` appears there. Failure produces `ERR_PREREQUISITE_NOT_MET` (422).

**Time-of-week conflict (priority 8).** For every offering the student is already approved into or waitlisted for in the same `term_id`, the system pairs every meeting in the candidate offering's `scheduled_meetings` with every meeting in the existing offering's `scheduled_meetings` that falls on the same `day_of_week`. Two meetings overlap when each one's `start_minute_of_day` falls strictly before the other one's `end_minute_of_day`. Because intervals are half-open `[start, end)`, two meetings that meet exactly at a minute boundary do not overlap. Any overlap fails with `ERR_TIME_CONFLICT` (409).

**Commute infeasibility (priority 9).** For every same-day pairing of meetings that are *not* time-overlapping but live on different campuses, the gap between the earlier meeting's end and the later meeting's start (in minutes) must be at least the buffer recorded on the originating campus — that is, `Campus.commute_minutes_to[other_campus]` indexed by the existing offering's `campus_id`. The check uses a closed boundary on the gap: a gap exactly equal to the buffer is acceptable; a gap strictly less than the buffer fails with `ERR_COMMUTE_INFEASIBLE` (409). The map `commute_minutes_to` is not required to be symmetric across campuses; the value used is the one stored on the campus the student is travelling **from**.

**Exam-week conflict (priority 10).** Each offering implicitly claims an exam slot inside the parent term's exam window (between `exam_window_start_at` and `exam_window_end_at`) as the offering's first scheduled meeting on the exam-week day. If the candidate offering's exam slot overlaps any existing offering's exam slot on the same day in the same term, using closed intervals on both ends, the request fails with `ERR_EXAM_TIME_CONFLICT` (409).

**Lab equipment conflict (priority 11).** For every `lab_id` in the candidate offering's `requires_lab_equipment_ids`, the system looks at every `OPEN` or `IN_SESSION` offering in the same term that also requires that equipment — across all students, not just the requesting student — and pairs same-day meetings. Two meetings conflict when each one's `start_minute_of_day` falls strictly before the other one's `end_minute_of_day` plus the per-equipment `setup_buffer_minutes`. The buffer extends both meeting endpoints uniformly. Failure produces `ERR_LAB_EQUIPMENT_CONFLICT` (409).

**The seat decision.** Once all the above pass, the system makes the seat decision atomically against the offering's current `enrolled_count` and `capacity`. When `enrolled_count` is strictly less than `capacity`, the request is approved: `academic_status` is set to `APPROVED`, the offering's `enrolled_count` is incremented by one, the `provisional_credit_charge` on the request is set to the course's `credits`, the student's provisional credit usage advances by that same amount, the `financial_status` is moved to `BILLED`, an `ENROLLMENT_APPROVED` `SyncEvent` is emitted to all four downstream systems, and a `TUITION_BILLED` `SyncEvent` is emitted to `FINANCE`. When `enrolled_count` is greater than or equal to `capacity` at the instant of decision, the request is waitlisted: `academic_status` is set to `WAITLISTED`, a `priority_score` is computed per §3.5 and frozen on the request, and a `WaitlistEntry` is created on the offering. Waitlisting is a normal outcome of submission and the response is **not** an error: the request is created with HTTP 201 and the `academic_status` field signals the outcome. Two students who simultaneously submit the very last seat serialize first-writer-wins on `enrolled_count`; the loser is silently waitlisted with no client-visible error code, although the system reserves `ERR_OFFERING_FULL_RACE_LOSER_WAITLISTED` (200) as the observability tag for downstream tests. A submission against a `CourseOffering` whose `status` is anything other than `OPEN` fails the priority-4 state check with `ERR_OFFERING_NOT_OPEN` (409).

### 3.5. The Waitlist, Priority Scoring, and Promotion

A `WaitlistEntry` is created when an enrollment request is waitlisted. The entry references its parent offering via `offering_id`, references the request via `enrollment_request_id`, carries a 1-indexed `position` (recomputed on every change to the offering's waitlist set), records the `priority_score` snapshot at the moment of waitlisting, records the `queued_at` Unix-seconds timestamp used as a tie-break, and carries a `status` that begins at `ACTIVE` and ends in one of `PROMOTED`, `EXPIRED`, or `CANCELED`. Waitlist entries are immutable after creation aside from this lifecycle status and the `position` recomputation; they carry only `id` and `created_at`, not `updated_at` or `version`.

The `priority_score` recorded on the entry is computed at the moment of waitlisting from four inputs and four weights:

- A `year_factor` equal to the student's `year_in_program` capped at five (so a year-six student contributes the same five points as a year-five student).
- A `gap_count` of one if the offering's course satisfies an unmet required course in the student's degree plan, or zero otherwise.
- A `prereq_strength` equal to the count of distinct `Course` rows whose `prerequisite_course_ids` reference the candidate course (in other words, how many downstream courses this one unlocks).
- A `fraud_penalty` equal to the student's `fraud_score` minus a grace value of ten, with negative results clamped to zero. Below the grace threshold there is no penalty; above it, every additional unit of `fraud_score` reduces the priority by the fraud weight.

The score is the sum of `year_factor` weighted by ten, plus `gap_count` weighted by fifteen, plus `prereq_strength` weighted by eight, minus `fraud_penalty` weighted by two. The sum is then truncated toward zero to an integer. Inputs are sampled at the instant of waitlisting and are not recomputed retroactively if the student's `fraud_score` or the course's prerequisite graph subsequently changes.

The waitlist is ordered by `priority_score` descending — higher scores are promoted first — with `queued_at` ascending as the tie-break: among entries with identical `priority_score`, the entry that was queued earlier wins. A waitlist entry can leave `ACTIVE` along three paths. The first is system-driven promotion when an upstream event makes a seat available: either a `Student` cancels an `APPROVED` enrollment, or a `Registrar` increases capacity, or the on-demand sweep capability runs. The second is system-driven expiration when the offering closes, the term closes, or the entry is the next candidate for promotion but fails re-validation. The third is the cascade from a student cancelling their own waitlisted request, which moves the entry to `CANCELED`.

When promoting, the system re-evaluates priority levels 4 through 12 (state, time, commute, exam, lab equipment, and credit quota) for the candidate `EnrollmentRequest`. If any re-validation fails, that `WaitlistEntry` is moved to `EXPIRED` (recorded as having failed validation at promotion time) and the next entry in the priority order is tried; the cascade continues until either a promotion succeeds or the waitlist is exhausted. A successful promotion runs the same side-effect set as a fresh approval — `enrolled_count` increment, `BILLED` financial transition, `ENROLLMENT_APPROVED` and `TUITION_BILLED` events, and a `WAITLIST_PROMOTED` event on top — and the `WaitlistEntry` itself moves from `ACTIVE` to `PROMOTED`. A duplicate promotion attempt against an already-`PROMOTED` `WaitlistEntry` (for example a sweep retry that races the same entry's earlier completion) returns `ERR_PROMOTION_RACE_LOST` (409). A cancel that races a promotion on the same offering serializes first-writer-wins on `enrolled_count`; if the promotion sees post-cancel state and the seat is no longer available, the top `WaitlistEntry` simply remains `ACTIVE` and the loser is silent.

### 3.6. The Dynamic Credit Quota and Over-Limit Applications

A student's per-term credit budget is computed dynamically rather than stored. The base quota depends on the student's `year_in_program`: years one through three use eighteen, twenty, and twenty-two credits respectively; years four, five, and six all use twenty-four credits. To this base the system adds the sum of `granted_credits` across all `OverLimitApplication` rows for the same `(student_id, term_id)` pair whose `status` is `APPROVED` (and only those — applications still in `AWAITING_PRIMARY` or `AWAITING_SECONDARY` contribute zero to the provisional check, even though they may eventually be approved). The result is the effective quota.

Against this quota the system measures the student's current load. There are two variants of the calculation:

- The **provisional** variant is used at enrollment-submission time. It sums `Course.credits` across every `EnrollmentRequest` for this student in this term whose `academic_status` is `APPROVED` or `WAITLISTED`. Note that `WAITLISTED` enrollments **do** consume the provisional quota; they release it only when they reach `CANCELED`, `EXPIRED`, or `REJECTED`.
- The **final** variant is used at term conclusion to compute the `final_credit_charge` populated on each settled enrollment. It still counts only `APPROVED` over-limit applications in the extension, but the current load it measures uses `academic_status` of `APPROVED` or `SETTLED` (excluding `WAITLISTED`, which by term-close are `EXPIRED`).

The submission is rejected with `ERR_CREDIT_QUOTA_EXCEEDED` (402) when the candidate offering's `Course.credits` added to the provisional current load would strictly exceed the effective quota; equality is permitted. All credit-hour quantities — base quota, extensions, current load, the final charge, and the candidate's contribution — are computed and rounded to two decimal places using round-half-up, per §2.5.

When a student needs more than their base quota, they file an `OverLimitApplication`. The application is created in `DRAFT` by the `Student` themselves with the body fields `student_id` (which must equal `X-User-ID`), `term_id`, the positive `requested_extension_credits`, a free-text `justification`, and the two countersigners: `primary_signer_id` and `secondary_signer_id`. At creation the system validates that both signers belong to the student's home `program_department_id` — that is, each signer's `Professor.department_id` matches `program_department_id` — otherwise it fails with `ERR_SIGNER_NOT_IN_HOME_DEPARTMENT` (422). It further requires that the primary signer is **not** the chair of that department — a primary signer with `is_chair` true fails with `ERR_PRIMARY_SIGNER_IS_CHAIR` (422) — and that the secondary signer **is** the chair, that is, has `is_chair` true; otherwise the application fails with `ERR_SECONDARY_SIGNER_NOT_CHAIR` (422). A `Professor` whose `is_chair` is true must also be of `rank` `ASSOCIATE` or `FULL`; only those two ranks are eligible to chair a department. A professor's identifying information for display purposes is their `full_name`.

Once created, an application proceeds through the following transitions:

- The `Student` submits the draft, transitioning `DRAFT → AWAITING_PRIMARY`. The submission is rejected unless the parent `Term` is in `REGISTRATION_OPEN` (`ERR_TERM_NOT_OPEN_FOR_REGISTRATION`) and unless `X-User-ID` matches `student_id` (`ERR_NOT_OWNER`). On entering `AWAITING_PRIMARY`, the system writes a fresh `timeout_deadline_at` equal to the current `clock` plus the system's approval-timeout duration (the same constant in seconds is reused at every state entry).
- The primary signer signs, transitioning `AWAITING_PRIMARY → AWAITING_SECONDARY`. The request is rejected unless `X-User-ID` matches `primary_signer_id` (`ERR_NOT_DESIGNATED_SIGNER`). On entering `AWAITING_SECONDARY`, a fresh `timeout_deadline_at` is written equal to the current `clock` plus the approval-timeout duration.
- The system may also auto-escalate `AWAITING_PRIMARY → AWAITING_SECONDARY` when the logical clock reaches `timeout_deadline_at`, leaving the primary signature implicitly skipped. A fresh `timeout_deadline_at` is again written.
- The secondary signer signs, transitioning `AWAITING_SECONDARY → APPROVED`. The request is rejected unless `X-User-ID` matches `secondary_signer_id` (`ERR_NOT_DESIGNATED_SIGNER`). On entering `APPROVED`, the system populates `granted_credits` to equal `requested_extension_credits`, and emits an `OVER_LIMIT_GRANTED` `SyncEvent` to `ACADEMIC_AFFAIRS` and `FINANCE`. `EnrollmentRequest`s that were previously rejected because of `ERR_CREDIT_QUOTA_EXCEEDED` are **not** reopened — those rejections are terminal; the new quota only affects subsequent submissions.
- Either the primary signer (when in `AWAITING_PRIMARY`) or the secondary signer (when in `AWAITING_SECONDARY`) may instead reject, transitioning to `REJECTED`. The rejection is rejected unless `X-User-ID` matches the current step's designated signer (`ERR_NOT_DESIGNATED_SIGNER`). `granted_credits` remains zero.
- The system auto-expires `AWAITING_SECONDARY → EXPIRED` when the logical clock reaches `timeout_deadline_at` for that step. `granted_credits` remains zero.
- The `Student` may revise a `REJECTED` application back to `DRAFT`, allowing a fresh submission with new justification or a new requested extension. The cycle is permitted only while the parent `Term` is still in `REGISTRATION_OPEN` and only by the application's own student. Previous `granted_credits` remains zero across the cycle.

Two professors who simultaneously sign and reject the same application serialize first-writer-wins on `OverLimitApplication.status`; the loser receives `ERR_INVALID_STATE` (409) because the application has already left the `AWAITING_*` state they were targeting.

### 3.7. Cancellation and Tuition Settlement

A `Student` may cancel an `EnrollmentRequest` whose `academic_status` is `APPROVED` or `WAITLISTED`. The cancellation requires `X-User-ID` to match the request's `student_id`; otherwise it fails with `ERR_NOT_OWNER`. For a cancellation of an `APPROVED` enrollment, the parent `Term` must additionally be in `REGISTRATION_OPEN` or `REGISTRATION_CLOSED` and the logical clock must still be strictly before `classes_start_at`; once classes have begun, the cancellation fails with `ERR_TERM_LOCKED_FOR_CANCEL` (409). The cancellation of an `APPROVED` enrollment carries a substantial cascade: the offering's `enrolled_count` is decremented, the student's provisional credit usage is decremented by the course's `credits`, `financial_status` reverts from `BILLED` to `UNBILLED`, the offering's waitlist is immediately swept for promotion in priority order per §3.5, and an `ENROLLMENT_CANCELED` `SyncEvent` is emitted to all four downstream systems. For a cancellation of a `WAITLISTED` enrollment the cascade is narrower: the underlying `WaitlistEntry` advances from `ACTIVE` to `CANCELED`, no seat or credit count is affected (the request never held one), and no `ENROLLMENT_CANCELED` event is emitted because no enrollment had been announced.

Tuition settlement is the `Finance` role's only operation. Once the system has set an enrollment's `financial_status` to `BILLED` (which happens automatically on approval), `Finance` may move it to `PAID`. The transition is rejected with `ERR_INVALID_STATE_FOR_SETTLE` (409) unless the request's `academic_status` is `APPROVED` — that is, settlement is forbidden once the enrollment has reached any of `CANCELED`, `REJECTED`, or `SETTLED`. On a successful settlement, the system emits a `TUITION_PAID` `SyncEvent` to `FINANCE`, `LIBRARY`, and `DORMITORY`. A separate cascade exists from the academic side: when an `APPROVED` enrollment is cancelled, its `financial_status` reverts from `BILLED` to `UNBILLED` (this is the system-driven companion to the `Student`-driven academic transition described in the previous paragraph).

### 3.8. Degree-Plan Gap Analysis and Scheduling Recommendations

A `Student` is created by a `Registrar` with the body fields `full_name`, `program_id`, `program_department_id`, `home_campus_id` (the student's primary campus, used as the from-campus for commute-buffer lookup in §3.4), `year_in_program`, the `gpa` value (a number between 0.00 and 4.00 inclusive, two-decimal precision), and `completed_course_ids`. On creation `status` is `ENROLLED` and `fraud_score` is zero.

A student's degree plan is computed on demand. The student's `program_department_id` defines the scope: every `Course` whose `owning_department_id` equals the student's `program_department_id` is treated as a required course in the plan. Against that universe the system computes:

- `completed_credits`, the sum of `Course.credits` across every `course_id` in the student's `completed_course_ids`.
- `in_progress_credits`, the sum of `Course.credits` across every `EnrollmentRequest` for this student whose `academic_status` is `APPROVED`, `WAITLISTED`, or `SETTLED`. This is intentionally a ceiling estimate: waitlisted courses are included so a student can see the worst-case credit load they have committed to, even though a waitlisted seat may not materialize.
- `gap_courses`, the set of required course identifiers minus the student's `completed_course_ids` minus every offering's `course_id` for which the student has an enrollment in `APPROVED` or `SETTLED` (waitlisted enrollments are **not** subtracted here, because a waitlisted seat is not yet held).
- `gap_count`, the size of `gap_courses`.
- `total_required_credits`, the sum of `Course.credits` across the required-course set, and `remaining_credits`, equal to `total_required_credits` minus `completed_credits` minus `in_progress_credits`.

All credit values are rounded to two decimal places, half-up. The gap analysis is recomputed on every enrollment-status change for the student (`APPROVED`, `CANCELED`, `SETTLED`, or `REJECTED`) and on any update to `completed_course_ids`.

Alongside the gap analysis the system surfaces a per-student scheduling recommendation. The candidate set is every `OPEN` `CourseOffering` in the next open term whose `course_id` lies in `gap_courses`. For each candidate the system computes a recommendation score: one hundred points for the gap-fit (since every candidate by construction satisfies a gap, this term contributes a flat one hundred), plus thirty points multiplied by the count of downstream courses that this offering's course unlocks (the same downstream-unlock count used in §3.5's `prereq_strength`), minus fifty points multiplied by the count of time conflicts the candidate would create against the student's existing `APPROVED` enrollments in the same term. The system returns the top five candidates by recommendation score in descending order, with the offering's `id` ascending as the tie-break.

A separate read surfaces cross-program transferable credits, computed against the catalog of `CreditEquivalencePolicy` rows. For every course in the student's `completed_course_ids` that has a policy whose `source_program_id` equals the course's owning program, whose `target_program_id` equals the student's `program_id`, and whose `source_course_id` equals the course's `id`, the system computes a per-course transferable value equal to that course's `credits` multiplied by the policy's `transfer_factor`, rounded half-up to two decimal places **per course before summation**. The transferable credits figure is then the sum of those per-course rounded values. The per-course-then-sum order is pinned: rounding the sum after the multiplication would in general produce a different total in cents, and would also be sensitive to course iteration order when the rounding boundary fell exactly between two summation paths. Because the calculation is read-time, the figure surfaced through the student-facing degree plan reflects the **current** policy values; it is not frozen until term conclusion.

### 3.9. Cross-Program and Cross-Department Catalog Administration

A `Registrar` administers cross-department permissions through `DepartmentAccessGrant` rows (described in §2.10) and cross-program credit recognition through `CreditEquivalencePolicy` rows. Creating a credit equivalence policy supplies the `source_program_id` (the program the policy maps from), the `target_program_id` (the program the policy maps to), the `source_course_id`, the `target_course_id`, and a `transfer_factor` strictly between zero and one inclusive of one. The transfer factor is the multiplier applied when surfacing transferable credits per §3.8.

A `Registrar` can revoke a `DepartmentAccessGrant` at any time, advancing it from `ACTIVE` to `REVOKED`. After revocation, the cross-department check in priority 6 of §2.9 will reject any further enrollment requests that depended on that grant, but already-`APPROVED` enrollments are unaffected — revocation is forward-looking, not retroactive.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`. Operations that modify an existing resource — including state-machine transitions invoked by an operator, capacity rescaling, tuition settlement, application sign/reject/revise, and the test-driving `clock` and sweep capabilities — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/students` | Create a `Student` | Registrar |
| GET | `/students` | List `Student`s | Registrar |
| GET | `/students/{studentId}` | Get a specific `Student` | Registrar, Student (own only) |
| GET | `/students/{studentId}/degree-plan` | Compute and return degree-plan gap analysis with estimated transferable credits | Registrar, Student (own only) |
| GET | `/students/{studentId}/recommendations` | Return top recommended `CourseOffering`s for the student | Registrar, Student (own only) |
| GET | `/students/{studentId}/sync-events` | Return the student's downstream `SyncEvent` log | Registrar, Student (own only) |
| POST | `/departments` | Create a `Department` | Registrar |
| GET | `/departments/{departmentId}` | Get a specific `Department` | Registrar, Student, Professor |
| POST | `/campuses` | Create a `Campus` | Registrar |
| POST | `/professors` | Create a `Professor` | Registrar |
| POST | `/lab-equipment` | Create a `LabEquipment` record | Registrar |
| POST | `/terms` | Create a `Term` in `PLANNING` | Registrar |
| GET | `/terms/{termId}` | Get a specific `Term` | Registrar, Student, Professor |
| POST | `/terms/{termId}/conclude` | Conclude a `Term` whose exam window has passed | Registrar |
| POST | `/courses` | Create a `Course` catalog entry | Registrar |
| GET | `/courses/{courseId}` | Get a specific `Course` | Registrar, Student, Professor |
| POST | `/course-offerings` | Create a `CourseOffering` in `PLANNED` | Registrar |
| GET | `/course-offerings` | List `CourseOffering`s with optional filters by `term_id`, `course_id`, `campus_id`, `instructor_id`, and `status` | Registrar, Student, Professor |
| GET | `/course-offerings/{offeringId}` | Get a specific `CourseOffering` | Registrar, Student, Professor |
| POST | `/course-offerings/{offeringId}/open` | Transition `PLANNED` → `OPEN` | Registrar |
| POST | `/course-offerings/{offeringId}/close` | Transition `OPEN` → `CLOSED` | Registrar |
| PATCH | `/course-offerings/{offeringId}/capacity` | Rescale an offering's capacity (body carries `new_capacity` and optional `version`) | Registrar |
| GET | `/course-offerings/{offeringId}/waitlist` | List `WaitlistEntry` rows for an offering, ordered by `position` | Registrar, Student, Professor |
| POST | `/enrollment-requests` | Submit a new enrollment request | Student |
| GET | `/enrollment-requests/{requestId}` | Get a specific `EnrollmentRequest` | Registrar, Student (own only) |
| GET | `/enrollment-requests` | List `EnrollmentRequest`s with optional filters by `student_id`, `term_id`, `offering_id`, `academic_status`, and `financial_status` | Registrar, Student (own only via `student_id` filter) |
| POST | `/enrollment-requests/{requestId}/cancel` | Cancel an `APPROVED` or `WAITLISTED` request | Student |
| POST | `/enrollment-requests/{requestId}/settle-tuition` | Mark `BILLED` → `PAID` | Finance |
| POST | `/over-limit-applications` | Create an `OverLimitApplication` in `DRAFT` | Student |
| GET | `/over-limit-applications/{applicationId}` | Get a specific application | Registrar, Student, Professor |
| POST | `/over-limit-applications/{applicationId}/submit` | Transition `DRAFT` → `AWAITING_PRIMARY` | Student |
| POST | `/over-limit-applications/{applicationId}/sign` | Countersign the current step (body may carry optional `version`) | Professor |
| POST | `/over-limit-applications/{applicationId}/reject` | Reject the application from the current step (body may carry optional `version`) | Professor |
| POST | `/over-limit-applications/{applicationId}/revise` | Revise a `REJECTED` application back to `DRAFT` | Student |
| POST | `/department-access-grants` | Create a `DepartmentAccessGrant` | Registrar |
| GET | `/department-access-grants` | List grants with optional filters by `source_department_id`, `target_department_id`, and `status` | Registrar, Student |
| POST | `/department-access-grants/{grantId}/revoke` | Revoke a grant | Registrar |
| POST | `/credit-equivalence-policies` | Create a `CreditEquivalencePolicy` | Registrar |
| GET | `/credit-equivalence-policies` | List policies with optional filters by `source_program_id` and `target_program_id` | Registrar, Student |
| POST | `/_clock/advance` | Advance the system's logical clock to a supplied `target_unix_seconds` value, firing all auto-transitions whose preconditions become satisfied (test-driving capability) | Registrar |
| POST | `/_sweep/run` | Run the periodic waitlist promotion and over-limit deadline sweep | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_DESIGNATED_SIGNER` | 403 Forbidden |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROFESSOR_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPUS_NOT_FOUND` | 404 Not Found |
| `ERR_TERM_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_OFFERING_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TERM_NOT_OPEN_FOR_REGISTRATION` | 409 Conflict |
| `ERR_TERM_LOCKED_FOR_CANCEL` | 409 Conflict |
| `ERR_TERM_NOT_READY_FOR_CONCLUDE` | 409 Conflict |
| `ERR_OFFERING_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_STATE_FOR_SETTLE` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_SIGNER_NOT_IN_HOME_DEPARTMENT` | 422 Unprocessable Entity |
| `ERR_PRIMARY_SIGNER_IS_CHAIR` | 422 Unprocessable Entity |
| `ERR_SECONDARY_SIGNER_NOT_CHAIR` | 422 Unprocessable Entity |
| `ERR_CROSS_DEPARTMENT_ACCESS_DENIED` | 403 Forbidden |
| `ERR_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TIME_CONFLICT` | 409 Conflict |
| `ERR_COMMUTE_INFEASIBLE` | 409 Conflict |
| `ERR_EXAM_TIME_CONFLICT` | 409 Conflict |
| `ERR_LAB_EQUIPMENT_CONFLICT` | 409 Conflict |
| `ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED` | 409 Conflict |
| `ERR_CREDIT_QUOTA_EXCEEDED` | 402 Payment Required |
| `ERR_RATE_LIMITED` | 429 Too Many Requests |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_OFFERING_FULL_RACE_LOSER_WAITLISTED` | 200 OK |
| `ERR_PROMOTION_RACE_LOST` | 409 Conflict |
| `ERR_CAPACITY_CASCADE_RACE_RETRY` | 409 Conflict |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
