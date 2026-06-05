# Corporate LMS & Compliance Training API — Product Requirements Document

## 1. Introduction

Regulated enterprises live and die by their ability to prove that every employee has completed the training their role demands, on time, and that those completions are still valid today. This document specifies the Corporate Learning Management & Compliance Training API: the system of record that turns a catalog of courses and curricula into rule-driven assignments, tracks each learner's progress through quizzes and SCORM/xAPI content runtimes, issues and ages out certifications, accrues continuing-education units, and surfaces an overdue-escalation feed and compliance dashboard to the managers who answer for their teams.

The platform is built around a deterministic, auditable model of time. Rather than reading the wall clock, the system advances a single logical clock under explicit operator control, so that recurrence windows, due-date overdue checks, certificate expiry, and escalation tiers all evolve reproducibly. The lifecycle of a single required course flows from an automated assignment sweep, through a learner starting and attempting the material, to a passing grade that mints a certificate and credits the employee — and, for recurring courses, eventually back to a fresh cycle when the certificate ages out. Curricula (learning paths) compose courses into ordered, weighted steps whose collective progress and pass/fail state roll up from their children. Throughout, the API maintains hard invariants on continuing-education totals and compliance counts so that what a manager sees on a dashboard always reconciles with the underlying certificates and completions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a numeric threshold or precision rule is stated here, it holds everywhere unless a workflow in Section 3 explicitly refines it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `ComplianceAdmin`, `Manager`, and `Learner`. If `X-User-Role` is missing or is not one of these three values, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The `X-User-ID` header is likewise required for the entity-backed roles (`Learner` and `Manager`) on every operation; the only requests that tolerate a missing `X-User-ID` are reads of the public course and learning-path catalogs and reads of the logical clock. A missing `X-User-ID` where one is required is also an `ERR_UNAUTHENTICATED` (HTTP 401). When a request is well-authenticated but the acting role is not permitted to perform the operation, or an ownership/scope check fails, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The three roles form a read-scope hierarchy and divide write authority by ownership:

- A `ComplianceAdmin` is an opaque operator identifier not tied to any persisted entity. The server does not compare `X-User-ID` to any employee's `id` for this role. A `ComplianceAdmin` owns all catalog configuration (courses, prerequisites, learning paths, steps), assignment rules and their sweeps, enrollment reopens and waivers, certificate revocation, escalation runs, and the test clock, and has read access to everything.
- When `X-User-Role` is `Manager`, `X-User-ID` is the `id` of the acting `Employee`. Manager scope is the set of that employee's direct and indirect reports along the `manager_id` reporting line; ownership checks on report-scoped resources compare the resource's owning employee against the manager's report set. A `Manager` reviews dashboards, enrollments, certificates, and the escalation feed for their reports and may acknowledge escalation events, but cannot mutate catalog or learner content.
- When `X-User-Role` is `Learner`, `X-User-ID` is the `id` of the acting `Employee`. Ownership checks on any enrollment, quiz attempt, or tracking session compare the resource's `employee_id` (directly, or through the owning enrollment) to `X-User-ID`. A `Learner` may start their own enrollments, submit attempts, drive tracking sessions, self-enroll into courses and paths, and read their own data.

These three authentication and authorization checks are evaluated ahead of everything else, in a fixed order: first the `X-User-Role` presence-and-validity check, then the `X-User-ID` presence check for entity-backed roles, then the role-permission check for the operation. Only after all three pass does the system look at the resources the request names.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock's current `current_utc` (the deterministic clock of §2.5) rather than the host wall clock.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100 rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless a workflow states otherwise, list endpoints return their resources sorted by `created_at` in ascending order, with ties broken deterministically by ascending `id`. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id`, a UUID with no type prefix. The full top-level resources — employees, courses, course prerequisites, learning paths, path steps, assignment rules, enrollments, path enrollments, certificates, tracking sessions, and the clock state — additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version`. The `version` begins at 1 on creation and increments by one on every mutation of that resource; `updated_at` is refreshed to the logical clock on every such mutation. Two entity types are append-only audit records and deliberately carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: a `QuizAttempt` (an immutable record of one submission) and an `EscalationEvent` (an immutable entry in the overdue log).

### 2.5. The Logical Clock and Deterministic Time

All time-dependent behavior reads a single deterministic clock rather than the host wall clock. The clock is a singleton resource exposing `current_utc`, the system's notion of "now" as an ISO 8601 UTC instant; at process boot it is initialized to `2025-01-01T00:00:00.000Z` until a `ComplianceAdmin` first advances it. A `ComplianceAdmin` advances it by supplying a new `current_utc`; reading the clock is open to all roles and does not require `X-User-ID`. Due dates, certificate expiry instants, overdue-day counts, escalation tiers, and recurrence windows are all computed against `current_utc`. Setting the clock increments the clock state's `version`.

### 2.6. Nested Resource Retrieval and Existence Ordering

When a path names a resource by id, that resource's existence is checked before any business rule runs. Paths that nest identifiers (for example, an enrollment's quiz attempts or tracking sessions, or a path's steps) are validated left-to-right: the first identifier in the path that does not resolve to an existing row causes an immediate `ERR_NOT_FOUND` (HTTP 404), before the system attempts to locate anything deeper. Foreign keys carried in a request body — a `course_id`, `learning_path_id`, `employee_id`, `prerequisite_course_id`, or `manager_id` — are likewise resolved against existing rows, and an unresolved body FK is also `ERR_NOT_FOUND`. Existence checks for path identifiers run ahead of body-FK checks. Both run after the authentication and authorization checks of §2.1 and before the field-shape validation described next.

### 2.7. Request Shape and Input Validation

After authentication, authorization, and existence have passed, write endpoints validate the shape of their payload: required fields must be present and well-typed, enum-valued fields must hold one of their declared values, raw quiz scores and reported scores must fall within 0 to 100 inclusive, and fields that the domain requires to be positive integers (such as `max_attempts`, `recurrence_months`, and `sequence_index`) must be positive. A violation here is `ERR_INVALID_REQUEST` (HTTP 400). The "authorization" that precedes this shape validation is the role-permission check of §2.1; the separate per-resource ownership/scope check (which compares the resource's owning employee against `X-User-ID`) runs after shape validation, so on the learner writes that both name an existing resource and carry a body — recording a quiz attempt and committing a tracking session — a malformed body is rejected as `ERR_INVALID_REQUEST` before a non-owner is turned away as `ERR_UNAUTHORIZED`. The same code covers the structural rule that an assignment rule must set exactly one of `course_id` or `learning_path_id`. Department values are drawn from `ENGINEERING`, `SALES`, `FINANCE`, `HR`, and `OPERATIONS`; a job role is one of `IC`, `MANAGER`, or `DIRECTOR`. A course's `content_type` is `SCORM` or `XAPI`.

### 2.8. Precision and Rounding

Two families of values are decimal. Continuing-education amounts (`ceu_credits` on a course, `ceu_credited` on a certificate, and the rolled-up `total_ceu_earned` on an employee) and percentage/score aggregates (a path enrollment's `progress_pct` and an employee's `compliance_score`) are all carried to exactly two decimal places using the round-half-up convention. Where a calculation prescribes a specific order of rounding — notably path progress, which rounds once after forming the aggregate ratio rather than rounding each step — that order is binding and is spelled out with the calculation in Section 3. Quiz scores and derived grades (`score`, `best_score`, `latest_score`, `final_grade`, `passing_score`) are whole integers in the range 0 to 100 and are never rounded. Overdue day counts and escalation tiers are whole integers.

### 2.9. Optimistic Concurrency on Quiz Submission

Recording a quiz attempt against an enrollment is guarded by optimistic concurrency control on the enrollment's `version`. A quiz-attempt submission must carry `expected_enrollment_version` as a required field whose value is the `version` of the target `Enrollment` that the client last observed. If that value does not equal the enrollment's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), and no attempt is recorded. This protects against a client recording an attempt against a cycle it has not seen: when a recurrence reset (which legitimately supersedes the prior cycle, advancing `cycle_index` and `version`) or an earlier attempt has already advanced the enrollment, the stale writer is turned away rather than recording its attempt against the wrong cycle. This version check is evaluated before the business check for remaining attempts, so a stale submission against a `FAILED` enrollment yields `ERR_STALE_VERSION` and not the attempts-exhausted error. The terminate operation on a tracking session may optionally carry `expected_enrollment_version`; when it is supplied, the same version comparison and the same `ERR_STALE_VERSION` rejection apply before the session's score is promoted to an attempt. No other endpoint takes a version field, and endpoints that do not list one perform no concurrency check.

### 2.10. Cascading Reconciliation and Conserved Quantities

Many operations touch more than one resource. When an enrollment completes, fails, is waived, or is reset, the system independently mutates each affected resource — bumping its `version` and refreshing its `updated_at` — and propagates the consequences upward to any owning path enrollment and outward to the holder's employee record. Two quantities on an `Employee` are conserved invariants that must always equal their definitional aggregates after any certificate is issued, revoked, or expired. The first, `total_ceu_earned`, equals the sum of `ceu_credited` across that employee's certificates that are currently `ACTIVE`. The second, `compliant_required_count`, equals the number of that employee's required enrollments that are `COMPLETED` and whose linked certificate is `ACTIVE`. Issuing a certificate adds its `ceu_credited` to `total_ceu_earned` and, when the underlying enrollment is required, increases `compliant_required_count` by one; revoking or expiring a certificate subtracts the same `ceu_credited` and, when required, decreases `compliant_required_count` by one. These forward and compensating adjustments are described in context with the workflows that trigger them in Section 3.

## 3. Business Logic & Workflows

### 3.1. People and the Catalog

A `ComplianceAdmin` registers each learner as an `Employee` by supplying a unique work `email` (compared case-insensitively for uniqueness), a `full_name`, a `department`, and a `job_role`. An optional `manager_id` points to another employee and forms the self-referential reporting line; it is left null for the top of a chain. A duplicate `email` is refused with `ERR_DUPLICATE`. On creation, the three computed compliance fields are seeded deterministically: `total_ceu_earned` starts at 0, `compliant_required_count` at 0, and `compliance_score` at 100. Every employee is created in the single-valued `ACTIVE` `status` and participates in assignment sweeps. The employee list can be filtered by `manager_id` to walk a reporting line and by `department`.

Courses are the unit of certifiable learning. Creating a `Course` requires a catalog `code` (unique, case-sensitive), a `title`, a `content_type` of `SCORM` or `XAPI`, and a `passing_score` — the inclusive integer threshold in 0 to 100 at or above which an attempt passes. Several inputs default when omitted: `max_attempts` defaults to 3 (the number of quiz attempts allowed per enrollment cycle, and it must be a positive integer), `ceu_credits` defaults to 0 (the nominal, non-negative two-decimal continuing-education award), `grading_policy` defaults to `HIGHEST_SCORE` (the alternative is `LATEST_ATTEMPT`), `ceu_policy` defaults to `STANDARD` (the alternative is `SCORE_WEIGHTED`), and `is_recurring` defaults to false. When `is_recurring` is true the course's certificate ages out and the enrollment recurs; `recurrence_months` then sets the validity-and-recurrence interval and must be a positive integer. A course is born `DRAFT`. A duplicate `code` is `ERR_DUPLICATE`.

A course may declare that other courses must be completed first. A `ComplianceAdmin` adds a prerequisite edge to a course by supplying the `prerequisite_course_id`; the dependent course is the one named in the path and is recorded as the edge's `course_id`. The prerequisite graph is a directed acyclic graph: adding an edge that would close a cycle across the existing `CoursePrerequisite` edges is rejected with `ERR_PREREQUISITE_CYCLE`. Prerequisite edges can be listed by the dependent's `course_id` or by the dependency's `prerequisite_course_id`, and fetched individually by their own id.

Publishing a course moves it from `DRAFT` to `PUBLISHED`, and only a `ComplianceAdmin` may do so. The course must currently be `DRAFT`, or the transition is refused as `ERR_INVALID_STATE`. If the course is recurring, its `recurrence_months` must be a positive integer at publish time, or the publish fails with `ERR_RECURRENCE_CONFIG_INVALID`. Every course named as a prerequisite must itself already be `PUBLISHED`, or the publish fails with `ERR_PREREQUISITE_NOT_PUBLISHED`. Publishing increments the course's `version`. Enrollment is only permitted against a `PUBLISHED` course. Archiving moves a `PUBLISHED` course to the terminal `ARCHIVED` state, again `ComplianceAdmin`-only; the course must be `PUBLISHED` (else `ERR_INVALID_STATE`) and there must be no enrollment for it still in `NOT_STARTED` or `IN_PROGRESS` (else `ERR_COURSE_HAS_OPEN_ENROLLMENTS`). Archiving increments the course's `version`.

### 3.2. Curricula: Learning Paths and Their Steps

A `LearningPath` bundles courses into an ordered curriculum. A `ComplianceAdmin` creates one with a unique case-sensitive `code` and a `title`; an `enforce_sequence` flag defaults to true and governs whether learners must walk the steps in order. A path begins `DRAFT`, and a duplicate `code` is `ERR_DUPLICATE`. Steps are added one at a time: each `PathStep` carries the owning `learning_path_id`, names a `course_id`, and is positioned by a 1-based `sequence_index` that must be unique within the path (a collision is `ERR_DUPLICATE`). A step is mandatory unless `is_mandatory` is set false (it defaults to true); mandatory steps drive both path completion and the progress weighting, and a positive integer `weight` (default 1) sets a step's contribution to progress — `weight` is ignored for non-mandatory steps. A path's steps can be listed under the path, and the step collection can also be filtered globally by `course_id` (to find every path that includes a given course) or by `learning_path_id`, with individual steps fetchable by id.

Publishing a path, a `ComplianceAdmin`-only transition from `DRAFT` to `PUBLISHED`, runs four gates in turn: the path must be `DRAFT` (else `ERR_INVALID_STATE`); it must contain at least one `PathStep` (else `ERR_PATH_EMPTY`); every step's `course_id` must reference a `PUBLISHED` course (else `ERR_PATH_STEP_COURSE_NOT_PUBLISHED`); and the set of `sequence_index` values must be the contiguous run 1 through N with no gaps and no duplicates (else `ERR_PATH_SEQUENCE_INVALID`). Publishing increments the path's `version`, and path enrollment is allowed only against a `PUBLISHED` path. Archiving a `PUBLISHED` path to terminal `ARCHIVED` requires that it be `PUBLISHED` (else `ERR_INVALID_STATE`) and that no `PathEnrollment` for it remain `NOT_STARTED` or `IN_PROGRESS` (else `ERR_PATH_HAS_OPEN_ENROLLMENTS`); it increments the path's `version`.

### 3.3. Rule-Based Assignment and Sweeps

Rather than enrolling employees one by one, a `ComplianceAdmin` defines an `AssignmentRule` that targets a population and a learning artifact over a window of time. A rule names a `target_department` (one of the five departments or `ANY`) and a `target_job_role` (`IC`, `MANAGER`, `DIRECTOR`, or `ANY`), and points at exactly one of a `course_id` or a `learning_path_id` — setting neither or both is `ERR_INVALID_REQUEST`. A `due_in_days` (a non-negative integer) sets how far past assignment the resulting due date falls, and `effective_from` and `effective_to` (ISO 8601 UTC instants) bound the rule's effective window inclusively, with `effective_to` required to be at or after `effective_from`. A new rule is created `ACTIVE`. To keep targeting unambiguous, two `ACTIVE` rules aimed at the same target — the same combination of `target_department`, `target_job_role`, and the chosen `course_id` or `learning_path_id` — may not have overlapping windows; if a new rule's closed `[effective_from, effective_to]` interval intersects an existing `ACTIVE` rule's window for that same target, the creation is refused with `ERR_ASSIGNMENT_RULE_OVERLAP`. Rules can be listed and filtered by `course_id`, `learning_path_id`, or `status`, and fetched by id.

Applying a rule is a sweep run by a `ComplianceAdmin`. The sweep walks every `ACTIVE` employee whose `department` and `job_role` match the rule's target (where `ANY` matches all), in ascending `created_at` order (ties broken by ascending `id`), and for each match it creates one course `Enrollment` or, for a path-targeted rule, one `PathEnrollment`, stamping the new record's `assignment_rule_id` with the rule's id and setting its `due_date` to `current_utc` plus `due_in_days`. Employees already in an open cycle for that artifact are skipped, so a rule can be re-applied without producing duplicates; for a course-targeted rule an open cycle is an existing `Enrollment` for that employee and course whose `status` is `NOT_STARTED`, `IN_PROGRESS`, `FAILED`, or `EXPIRED` (only a `COMPLETED` or `WAIVED` enrollment frees the slot), and for a path-targeted rule it is an existing `PathEnrollment` for that employee and path whose `status` is `NOT_STARTED`, `IN_PROGRESS`, or `FAILED`. The sweep responds with the list of `created_enrollment_ids`, the list of `created_path_enrollment_ids`, and a `created_count`.

### 3.4. The Enrollment Lifecycle

An `Enrollment` ties one learner to one course. It can be created by a `ComplianceAdmin` or self-created by a `Learner` by naming the `employee_id` and `course_id`; `is_required` defaults to true (only required enrollments count toward compliance), and an optional `due_in_days` sets the due date to `current_utc` plus that many days, defaulting to 30 days when omitted. The new enrollment starts `NOT_STARTED` with `cycle_index` 1 and the system-set fields seeded — `best_score` and `latest_score` null, `final_grade` null, `attempts_used` 0, `escalation_tier` 0, `certificate_id` null, `path_enrollment_id` null (set only when the enrollment is a step of a path enrollment), and `assignment_rule_id` null (set only by a rule sweep). A second open-cycle enrollment for the same `employee_id` and `course_id` is a duplicate and is refused with `ERR_DUPLICATE`, where an open cycle is any existing enrollment for that pair whose `status` is `NOT_STARTED`, `IN_PROGRESS`, `FAILED`, or `EXPIRED`; a `COMPLETED` or `WAIVED` enrollment does not block a new one. Enrollments can be listed and filtered by `employee_id`, `course_id`, `assignment_rule_id`, `path_enrollment_id`, or `status`, subject to manager and learner read scopes, and fetched by id.

A `Learner` starts their own enrollment, advancing it from `NOT_STARTED` to `IN_PROGRESS`. The enrollment must be `NOT_STARTED` (else `ERR_INVALID_STATE`); the acting learner must own it, meaning `X-User-ID` equals the enrollment's `employee_id` (else `ERR_UNAUTHORIZED`); the course must be `PUBLISHED` (else `ERR_COURSE_NOT_PUBLISHED`); every prerequisite course for this course must already hold an `ACTIVE` certificate for this employee (else `ERR_PREREQUISITE_NOT_MET`); and, when the enrollment is a step of a path whose `enforce_sequence` is true, the immediately prior step's enrollment must be `COMPLETED` (else `ERR_PATH_STEP_LOCKED`). On success the enrollment becomes `IN_PROGRESS`, its `version` increments, and if the owning path enrollment was still `NOT_STARTED`, it bubbles up to `IN_PROGRESS`.

### 3.5. Quiz Attempts, Grading, and Certification

Once an enrollment is `IN_PROGRESS`, the `Learner` records progress by submitting a quiz attempt carrying a raw `score` (0 to 100 inclusive) and the `expected_enrollment_version` described in §2.9. Each submission appends an immutable `QuizAttempt` recording the `enrollment_id`, the `cycle_index` in force at submission, an `attempt_number` (1-based within the cycle, equal to `attempts_used` after the attempt is counted), the raw `score`, and a computed `passed` flag that is true exactly when the `score` is at or above the owning course's `passing_score`. After recording, the enrollment's `best_score` (the highest attempt score in the current cycle), `latest_score` (the most recent attempt's score by `created_at`, breaking ties by the greatest `attempt_number` since same-cycle attempts share the logical-clock timestamp), and `attempts_used` (the count of attempts in the current cycle) are recomputed.

The state-transition gate for a submission is precise: an attempt is only accepted against an enrollment that is `IN_PROGRESS` or `FAILED`; submissions against `NOT_STARTED`, `COMPLETED`, `EXPIRED`, or `WAIVED` enrollments are rejected with `ERR_INVALID_STATE`. For an enrollment that passes that gate, the `expected_enrollment_version` check runs next, and only then the remaining-attempts business check: the cycle must still have an attempt available, meaning the enrollment is `IN_PROGRESS` with `attempts_used` below the course's `max_attempts`. A submission against a `FAILED` enrollment — whose cycle attempts are already exhausted — fails this check with `ERR_ATTEMPTS_EXHAUSTED`; the enrollment must first be reopened or recurrence-reset. Because the version check precedes the attempts check, a stale submission against a `FAILED` enrollment surfaces as `ERR_STALE_VERSION` rather than `ERR_ATTEMPTS_EXHAUSTED`.

A passing attempt drives the enrollment from `IN_PROGRESS` to `COMPLETED`. The attempt is appended, the score aggregates recomputed, and the recorded `final_grade` is set per the course's grading policy: under `HIGHEST_SCORE` the `final_grade` is the maximum `score` among the current cycle's attempts; under `LATEST_ATTEMPT` it is the score of the attempt with the greatest `created_at`, breaking ties by the greatest `attempt_number`. The two policies diverge whenever the last attempt is not the best. On completion the system issues a `Certificate` in `ACTIVE` status, computes its `ceu_credited`, and stores the certificate's id on the enrollment's `certificate_id` as a back-pointer (the canonical link being the certificate's `enrollment_id`). It then credits the holder: `ceu_credited` is added to the employee's `total_ceu_earned`, and when the enrollment `is_required`, the employee's `compliant_required_count` rises by one, after which the employee's `compliance_score` is recomputed. If the enrollment is part of a path, the path enrollment's `progress_pct` is re-evaluated and the path may bubble to `COMPLETED`. The enrollment's `version` increments.

The `ceu_credited` figure follows the course's CEU policy applied to the course's nominal `ceu_credits`. Under `STANDARD`, the full `ceu_credits` is awarded, rounded to two decimal places half-up. Under `SCORE_WEIGHTED`, the award is `ceu_credits` scaled by a band multiplier chosen from the certifying enrollment's `final_grade`: a grade of 90 or more takes the full multiplier of 1.00, a grade of at least 80 but below 90 takes 0.75, and any other passing grade below 80 takes 0.50; the multiplier is applied to `ceu_credits` first and the product is then rounded to two decimal places half-up. The score-weighted variant equals the standard variant exactly when `final_grade` is 90 or above, and falls below it otherwise.

A failing attempt only ends the enrollment when it is the last attempt. The attempt fails when its `score` is below the course's `passing_score`. If counting this attempt brings `attempts_used` up to the course's `max_attempts` — that is, the attempt just recorded is the final one — the enrollment transitions from `IN_PROGRESS` to `FAILED`, the score aggregates and `final_grade` are recomputed in the same way, and if the enrollment is a mandatory step of a path, the path enrollment bubbles to `FAILED`. A failing attempt that does not exhaust the allowance leaves the enrollment `IN_PROGRESS`. Either way the enrollment's `version` increments.

A `ComplianceAdmin` can reopen a `FAILED` enrollment for a fresh try, moving it back to `IN_PROGRESS`. The enrollment must be `FAILED` (else `ERR_INVALID_STATE`) and its course must be `PUBLISHED` (else `ERR_COURSE_NOT_PUBLISHED`). Reopening stays within the same `cycle_index` but resets the cycle for a clean retry: `attempts_used` returns to 0 and `best_score`, `latest_score`, and `final_grade` are cleared to null. Prior attempts retain their original `cycle_index`, but new attempts restart their `attempt_number` at 1. If a path enrollment had failed because of this step, it bubbles back to `IN_PROGRESS`. The enrollment's `version` increments.

A `ComplianceAdmin` may waive an enrollment that is `NOT_STARTED`, `IN_PROGRESS`, `FAILED`, or `EXPIRED`, moving it to the terminal `WAIVED` state; a waive attempted from any other state is `ERR_INVALID_STATE`. When the waived enrollment is part of a path, the path enrollment's `progress_pct` is re-evaluated treating waived mandatory steps as satisfied. The enrollment's `version` increments.

### 3.6. SCORM and xAPI Tracking Sessions

Independently of, or alongside, direct quiz submission, a `Learner` records runtime activity through a `TrackingSession`. Opening a session against an `IN_PROGRESS` enrollment creates it in `INITIALIZED` status, copies the `content_type` (`SCORM` or `XAPI`) from the course, and stamps `started_at` with `current_utc`. The owning enrollment must be `IN_PROGRESS` (else `ERR_INVALID_STATE`), and at most one session per enrollment may be non-`TERMINATED` at a time — opening a second while one is still `INITIALIZED` or `RUNNING` is refused with `ERR_SESSION_ALREADY_OPEN`. A session's `enrollment_id`, `terminated_at` (null while open), `lesson_status`, `progress_pct`, and `reported_score` round out its shape; at open these are seeded to `lesson_status` null, `progress_pct` 0, `reported_score` null, and `terminated_at` null. Sessions can be listed under their enrollment, filtered by `status`.

Committing runtime data moves a session from `INITIALIZED` to `RUNNING` on the first commit and then self-loops on `RUNNING` for subsequent commits, each accumulating data. A commit sets `lesson_status` — one of `INCOMPLETE`, `COMPLETED`, `PASSED`, or `FAILED`, mapped from the SCORM `cmi.core.lesson_status` or the xAPI verb — and updates `progress_pct` (which must lie in 0 to 100) and an optional `reported_score` (which, when present, must lie in 0 to 100). The session must be `RUNNING` (or, on the first commit, transitioning out of `INITIALIZED`) for a commit to be accepted (else `ERR_INVALID_STATE`); each commit increments the session's `version`.

Terminating a `RUNNING` session is the cross-aggregate bridge into grading. Termination requires the session to be `RUNNING` (else `ERR_INVALID_STATE`) and sets `terminated_at` to `current_utc`, which must be strictly after `started_at`; the session becomes `TERMINATED` and its `version` increments. If the session carries a `reported_score`, that score is promoted into a `QuizAttempt` on the enrollment and the full enrollment grading cascade of §3.5 runs against it — driving the enrollment to `COMPLETED` on a passing score or to `FAILED` on a failing score at the last attempt, with all the same certificate, CEU, and path consequences. The promotion fires only when the enrollment is `IN_PROGRESS` with `attempts_used` still below the course's `max_attempts`; if the enrollment cannot accept an attempt (it is not `IN_PROGRESS`, or its attempts are already exhausted), the session still becomes `TERMINATED` but no `QuizAttempt` is recorded and the enrollment is left unchanged. A session that carries no `reported_score` likewise terminates without touching the enrollment. The terminate request may carry `expected_enrollment_version`; when present, the optimistic concurrency check of §2.9 is applied before the promotion.

### 3.7. Path Enrollments and Rolled-Up Progress

A `PathEnrollment` enrolls one learner into a whole curriculum. It is created by a `ComplianceAdmin` or a `Learner` naming the `employee_id` and `learning_path_id`, with an optional `due_in_days` setting `due_date` to `current_utc` plus that many days, defaulting to 60 days. Creation fans out one child `Enrollment` per `PathStep`, each with its `path_enrollment_id` set to bind it to the parent. The path enrollment begins `NOT_STARTED` with `progress_pct` 0. Path enrollments can be listed and filtered by `employee_id`, `learning_path_id`, `assignment_rule_id`, or `status`, and fetched by id; reading one recomputes its `progress_pct`.

A path enrollment's state is compound — it is derived from its children rather than driven directly. When any child enrollment first moves from `NOT_STARTED` to `IN_PROGRESS`, a `NOT_STARTED` path enrollment bubbles up to `IN_PROGRESS`. When a child enrollment reaches `COMPLETED` and, with it, every mandatory step's child enrollment is now `COMPLETED` or `WAIVED`, the path enrollment recomputes its progress to 100 and bubbles to the terminal `COMPLETED`; until every mandatory step is satisfied it stays `IN_PROGRESS`. When a mandatory step's child enrollment reaches `FAILED`, the path enrollment bubbles to `FAILED`; if that offending child is later reopened so it is no longer `FAILED`, a `FAILED` path enrollment bubbles back to `IN_PROGRESS`. Each of these bubble transitions increments the path enrollment's `version`.

Progress is a weighted measure over the mandatory steps. Let the mandatory steps of the path be those with `is_mandatory` true, and let the total weight be the sum of their `weight` values. A mandatory step counts as satisfied — contributing its full `weight` — exactly when the learner's child enrollment for that step's course is `COMPLETED` or `WAIVED`; otherwise it contributes nothing. The progress percentage is the earned weight divided by the total weight, multiplied by 100, and rounded once to two decimal places half-up. The rounding order is binding: form the single ratio of earned to total weight, scale to a percentage, and round that one result — never round each step's contribution and sum the rounded pieces. When the total weight is 0, `progress_pct` is 0.

### 3.7.1. Prerequisite Gating Across Courses and Steps

Two gating mechanisms layer on top of the start transition of §3.4 and deserve emphasis because each guards a distinct concern. The course-prerequisite gate is satisfied only when, for the course being started, every prerequisite course recorded as a `CoursePrerequisite` edge has an `ACTIVE` certificate held by this same employee; absent that, starting is refused with `ERR_PREREQUISITE_NOT_MET`. Separately, the path-sequence gate applies only to enrollments that are steps of a path whose `enforce_sequence` is true: such a step may be started only after the immediately preceding step's child enrollment has reached `COMPLETED`, and a premature start is refused with `ERR_PATH_STEP_LOCKED`. The two gates are independent — a step can clear its path-sequence gate yet still fail the course-prerequisite gate, and vice versa.

### 3.8. Certificates, Expiry, and Recurrence

A `Certificate` is minted automatically when a required or optional enrollment completes; it is never created directly. It records the holder's `employee_id`, the certified `course_id`, the completing `enrollment_id`, the computed `ceu_credited`, an `issued_at` timestamp, and an `expires_at` instant. For a recurring course, `expires_at` is `issued_at` plus the course's `recurrence_months`; for a non-recurring course, `expires_at` is null and the certificate never expires. A certificate is born `ACTIVE`. Certificates can be listed and filtered by `employee_id`, `course_id`, `enrollment_id`, or `status`, and fetched by id.

A `ComplianceAdmin` may revoke an `ACTIVE` certificate, moving it to the terminal `REVOKED` state; a revoke from any other state is `ERR_INVALID_STATE`. Revocation compensates the conserved quantities of §2.10: the certificate's `ceu_credited` is subtracted from the holder's `total_ceu_earned`, and when the linked enrollment `is_required` the holder's `compliant_required_count` falls by one, after which the holder's `compliance_score` is recomputed. Revocation increments the certificate's `version`.

Certificate aging and the recurrence reset are driven by the escalation sweep against the logical clock. When `current_utc` advances strictly past a certificate's non-null `expires_at`, the sweep moves that `ACTIVE` certificate to `EXPIRED` and applies the same compensation as a revoke — subtracting `ceu_credited` from the holder's `total_ceu_earned` and, when the linked enrollment is required, decrementing `compliant_required_count`; the certificate's `version` increments. For a recurring course, the certificate's expiry then drives a recurrence reset of the linked enrollment: that `COMPLETED` enrollment, whose course `is_recurring` and whose certificate was `ACTIVE` and is now past its `expires_at`, returns to `NOT_STARTED` to start a new compliance cycle. The reset advances `cycle_index` by one, clears `certificate_id` to null, sets a fresh `due_date` of `current_utc` plus the course's `recurrence_months`, and clears `final_grade`, `attempts_used`, `best_score`, and `latest_score`; the employee's `compliance_score` is recomputed and the enrollment's `version` increments. Because a recurrence reset legitimately advances the enrollment's `version` and `cycle_index`, any quiz attempt a client tries to record against the superseded cycle with a stale `expected_enrollment_version` is turned away under §2.9.

### 3.9. Overdue Escalation and the Manager Dashboard

The escalation sweep, run by a `ComplianceAdmin`, reconciles everything time-dependent in one pass against `current_utc`. It expires overdue enrollments: an enrollment still `NOT_STARTED` or `IN_PROGRESS` whose `due_date` is strictly before `current_utc` is moved to `EXPIRED`, incrementing its `version`. It expires certificates past their `expires_at` and applies the recurrence resets described in §3.8. And for every overdue enrollment it recomputes the escalation tier and, when that tier is at least 1, appends an immutable `EscalationEvent`. The sweep returns four lists: `expired_enrollment_ids`, `expired_certificate_ids`, `reset_enrollment_ids`, and `escalation_event_ids`.

The escalation tier is a threshold function of how overdue an enrollment is. The number of whole `days_overdue` is the difference between `current_utc` and the enrollment's `due_date`, measured in days and floored to a whole number. When `days_overdue` is 0 or less the `escalation_tier` is 0 (on track — the due instant itself is on track); from 1 through 7 days the tier is 1; from 8 through 30 days the tier is 2; beyond 30 days the tier is 3. The `escalation_tier` reported for an enrollment is a pure derived value of its `days_overdue` against the current `current_utc` and does not depend on the enrollment's `status`: an enrollment that is `COMPLETED`, `EXPIRED`, `WAIVED`, or in any other state still carries the tier its `days_overdue` lands in, so a `COMPLETED` enrollment whose `due_date` has passed reports the corresponding nonzero tier rather than 0. (This per-enrollment tier value is distinct from the sweep's event emission above, which only walks and emits `EscalationEvent`s for the `NOT_STARTED`/`IN_PROGRESS` enrollments it expires.) Each `EscalationEvent` records the overdue `enrollment_id`, the learner's `employee_id` (denormalized for dashboard queries), the learner's `manager_id` at escalation time (null when none), the `tier` reached, the `days_overdue` at that moment, and an `acknowledged` flag that starts false. Escalation events can be listed and filtered by `enrollment_id`, `employee_id`, `manager_id`, `acknowledged`, or `tier`, and fetched by id. A `Manager` acknowledges an event for one of their reports, setting `acknowledged` to true; a `ComplianceAdmin` may acknowledge as well.

The employee compliance dashboard recomputes `compliance_score`, `total_ceu_earned`, and `compliant_required_count` and returns the refreshed `Employee` resource (the same full employee object shape, carrying these three computed fields; no separate overdue-summary structure is emitted), and is readable by a `ComplianceAdmin`, the employee's `Manager`, and the `Learner` themselves. The `compliance_score` is a weighted figure clamped to the range 0 to 100. Take this employee's required enrollments — those with `is_required` true, counting only the latest cycle — and let n be their count. When n is 0 the score is exactly 100.00. Otherwise, let the compliant count be the number of those required enrollments that are `COMPLETED` with a linked `ACTIVE` certificate; the base is the compliant count divided by n, times 100. From that base subtract an overdue penalty: for each of those required enrollments — every one of them, whatever its `status`, including the `COMPLETED` ones counted as compliant above — multiply its current `escalation_tier` (the status-agnostic derived value defined just above, computed from `days_overdue` against `current_utc`) by a per-tier penalty of 5 points and sum across the enrollments. The score is the base minus the total penalty, clamped to lie between 0 and 100, and rounded to two decimal places half-up.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource (including state transitions and sweeps) return `200 OK`. All endpoints honor the authentication, authorization, existence, and validation ordering described in Section 2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employees` | Create an employee | ComplianceAdmin |
| GET | `/employees/{id}` | Get one employee | ComplianceAdmin, Manager, Learner |
| GET | `/employees` | List employees (filter by manager_id, department) | ComplianceAdmin, Manager |
| GET | `/employees/{id}/dashboard` | Compliance dashboard for an employee | ComplianceAdmin, Manager, Learner |
| POST | `/courses` | Create a course (DRAFT) | ComplianceAdmin |
| GET | `/courses/{id}` | Get one course | ComplianceAdmin, Manager, Learner |
| GET | `/courses` | List courses (catalog) | ComplianceAdmin, Manager, Learner |
| POST | `/courses/{id}/publish` | Publish a course | ComplianceAdmin |
| POST | `/courses/{id}/archive` | Archive a course | ComplianceAdmin |
| POST | `/courses/{id}/prerequisites` | Add a prerequisite edge | ComplianceAdmin |
| GET | `/course-prerequisites` | List prerequisite edges (filter by course_id, prerequisite_course_id) | ComplianceAdmin, Manager, Learner |
| GET | `/course-prerequisites/{id}` | Get one prerequisite edge | ComplianceAdmin, Manager, Learner |
| POST | `/learning-paths` | Create a learning path (DRAFT) | ComplianceAdmin |
| GET | `/learning-paths/{id}` | Get one learning path | ComplianceAdmin, Manager, Learner |
| POST | `/learning-paths/{id}/steps` | Add an ordered step to a path | ComplianceAdmin |
| GET | `/learning-paths/{id}/steps` | List a path's steps | ComplianceAdmin, Manager, Learner |
| POST | `/learning-paths/{id}/publish` | Publish a path | ComplianceAdmin |
| POST | `/learning-paths/{id}/archive` | Archive a path | ComplianceAdmin |
| GET | `/path-steps` | List path steps (filter by course_id, learning_path_id) | ComplianceAdmin, Manager, Learner |
| GET | `/path-steps/{id}` | Get one path step | ComplianceAdmin, Manager, Learner |
| POST | `/assignment-rules` | Create an assignment rule | ComplianceAdmin |
| GET | `/assignment-rules` | List assignment rules (filter by course_id, learning_path_id, status) | ComplianceAdmin, Manager |
| GET | `/assignment-rules/{id}` | Get one assignment rule | ComplianceAdmin, Manager |
| POST | `/assignment-rules/{id}/apply` | Sweep: enroll all matching employees | ComplianceAdmin |
| POST | `/enrollments` | Enroll an employee into a course | ComplianceAdmin, Learner |
| GET | `/enrollments` | List enrollments (filter by employee_id, course_id, assignment_rule_id, path_enrollment_id, status) | ComplianceAdmin, Manager, Learner |
| GET | `/enrollments/{id}` | Get one enrollment | ComplianceAdmin, Manager, Learner |
| POST | `/enrollments/{id}/start` | Learner starts an enrollment | Learner |
| POST | `/enrollments/{id}/quiz-attempts` | Record a quiz attempt | Learner |
| GET | `/enrollments/{id}/quiz-attempts` | List an enrollment's quiz attempts (filter by cycle_index) | ComplianceAdmin, Manager, Learner |
| POST | `/enrollments/{id}/reopen` | Reopen a FAILED enrollment | ComplianceAdmin |
| POST | `/enrollments/{id}/waive` | Waive an enrollment | ComplianceAdmin |
| POST | `/enrollments/{id}/tracking-sessions` | Open a tracking session | Learner |
| GET | `/enrollments/{id}/tracking-sessions` | List tracking sessions (filter by status) | ComplianceAdmin, Manager, Learner |
| PATCH | `/tracking-sessions/{id}/commit` | Commit runtime data | Learner |
| POST | `/tracking-sessions/{id}/terminate` | Terminate a session; may drive the enrollment | Learner |
| POST | `/path-enrollments` | Enroll an employee into a learning path | ComplianceAdmin, Learner |
| GET | `/path-enrollments` | List path enrollments (filter by employee_id, learning_path_id, assignment_rule_id, status) | ComplianceAdmin, Manager, Learner |
| GET | `/path-enrollments/{id}` | Get one path enrollment | ComplianceAdmin, Manager, Learner |
| GET | `/certificates` | List certificates (filter by employee_id, course_id, enrollment_id, status) | ComplianceAdmin, Manager, Learner |
| GET | `/certificates/{id}` | Get one certificate | ComplianceAdmin, Manager, Learner |
| POST | `/certificates/{id}/revoke` | Revoke a certificate | ComplianceAdmin |
| POST | `/escalations/run` | Run the escalation/expiry/recurrence sweep | ComplianceAdmin |
| GET | `/escalation-events` | List escalation events (filter by enrollment_id, employee_id, manager_id, acknowledged, tier) | ComplianceAdmin, Manager, Learner |
| GET | `/escalation-events/{id}` | Get one escalation event | ComplianceAdmin, Manager, Learner |
| POST | `/escalation-events/{id}/acknowledge` | Acknowledge an escalation event | ComplianceAdmin, Manager |
| POST | `/_clock/set` | Set the deterministic system clock | ComplianceAdmin |
| GET | `/_clock` | Read the deterministic clock | ComplianceAdmin, Manager, Learner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_RECURRENCE_CONFIG_INVALID` | 409 Conflict |
| `ERR_PREREQUISITE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_COURSE_HAS_OPEN_ENROLLMENTS` | 409 Conflict |
| `ERR_PATH_EMPTY` | 409 Conflict |
| `ERR_PATH_STEP_COURSE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PATH_SEQUENCE_INVALID` | 409 Conflict |
| `ERR_PATH_HAS_OPEN_ENROLLMENTS` | 409 Conflict |
| `ERR_COURSE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PREREQUISITE_NOT_MET` | 409 Conflict |
| `ERR_PATH_STEP_LOCKED` | 409 Conflict |
| `ERR_ATTEMPTS_EXHAUSTED` | 409 Conflict |
| `ERR_SESSION_ALREADY_OPEN` | 409 Conflict |
| `ERR_ASSIGNMENT_RULE_OVERLAP` | 409 Conflict |
| `ERR_PREREQUISITE_CYCLE` | 409 Conflict |
