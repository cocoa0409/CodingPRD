# Real Estate Pre-Licensing School API — Product Requirements Document

## 1. Introduction

State real-estate commissions do not let just anyone teach pre-licensing or continuing-education courses. A school must be licensed, every course must be approved state by state, every instructor must hold a state approval, and every clock hour a student sits must be verifiable — because a certificate issued against an unapproved course, or a credit report filed late, puts real licenses at risk. Schools that run this on spreadsheets discover the gaps at audit time, after certificates have already gone out.

This document specifies a state-approved real estate pre-licensing and continuing-education platform. It covers the full regulatory loop: school registration and licensing by the commission; course catalog management with state-by-state approval applications, denials, resubmissions, and a renewal cycle; instructor approval on the same cycle; course offerings with seat capacity, calendar windows, and instructor rest-day rules; student enrollment with a pinned tuition computation, payment capture, withdrawal, and a dual-track refund policy (published tier schedule versus statutory pro-rata, with the student always receiving the greater); seat-time tracking under a daily credit cap; proctored final examinations under a strict segregation-of-duties rule; certificate issuance with school-scoped yearly numbering; continuing-education credit reporting to the licensing authority with late fees and a correction/amendment cycle; multi-state course equivalency grants that suspend and resume automatically with the home-state approval; and school pass-rate surveillance that places a school on probation when its first-time pass rate falls below its floor.

Because the commission audits every decision after the fact, every mutation in the system appends to an append-only audit trail, and the system maintains its own logical clock so that regulatory windows — approval validity, completion deadlines, reporting deadlines, no-show cutoffs, pass-rate windows — are deterministic rather than wall-clock dependent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the acting user's identifier) and `X-User-Role` (the acting role). Seven role names are recognized, spelled exactly: `StateCommission`, `SchoolDirector`, `Registrar`, `ComplianceOfficer`, `Instructor`, `Proctor`, `Student`. A request missing either header, presenting an undeclared role, or — for the entity-backed roles — presenting an `X-User-ID` that does not reference an existing entity of the backing type is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the role is valid but not on the endpoint's authorized list, the rejection is `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Three roles are entity-backed. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks compare a resource's student reference to `X-User-ID`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; the instructor may record or void attendance and score exams only where `X-User-ID` equals the offering's `instructor_id`. When `X-User-Role` is `Proctor`, `X-User-ID` is likewise the `id` of an `Instructor` entity — specifically the instructor assigned as proctor on the exam attempt, so proctor-scoped operations compare the attempt's `proctor_instructor_id` to `X-User-ID`.

The four staff roles are opaque. When `X-User-Role` is `StateCommission`, `Registrar`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on audit events but does not compare it to any entity's `id`. `SchoolDirector` is also opaque in that sense — no director entity is persisted — but the creating director's `X-User-ID` is recorded as `director_user_id` on the `School`, and every subsequent director operation is scoped: a `SchoolDirector` may act only on schools whose `director_user_id` equals `X-User-ID`, and on resources descending from those schools. A scope mismatch of any flavor is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 and must lie between 1 and 100, both inclusive; `offset` defaults to 0 and must be greater than or equal to 0. Values outside these bounds are rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a subsection states otherwise, list endpoints sort by `created_at` ascending; the audit trail in particular is always returned in `created_at` ascending order.

### 2.4. The Logical Clock and the Regulatory Sweep

The system keeps a logical UTC clock. All rule dates in this document are ISO calendar dates (YYYY-MM-DD), and the word "today" always means the calendar date of the logical clock in UTC — never wall-clock time. At server startup, before any adjustment, the clock reads exactly `2026-08-01T00:00:00Z`. A `ComplianceOfficer` may set the clock to a supplied `to_iso8601` instant through an admin-only test-driving capability, which confirms the new reading as `current_utc`; from that point on, every piece of date arithmetic described below evaluates against the new clock.

A second `ComplianceOfficer`-only capability runs the regulatory sweep, which advances the regulatory epoch in a pinned order, and returns a run summary containing `approvals_expired`, `instructor_approvals_expired`, `grants_suspended`, `offerings_advanced`, `enrollments_expired`, `attempts_no_show`, and `schools_evaluated`. The sweep's five phases execute in exactly this sequence: first, course approvals and instructor approvals whose `valid_until` is 30 days or fewer away (while still in the future or today) move from `APPROVED` to `EXPIRING`, and approvals already past `valid_until` move from `EXPIRING` to `EXPIRED`, with each expired course approval cascading its equivalency grants from `ACTIVE` to `SUSPENDED`; second, `PUBLISHED` offerings whose `start_date` is today or earlier move to `IN_SESSION`, and `IN_SESSION` offerings whose `end_date` is before today move to `COMPLETED`; third, non-terminal enrollments whose `deadline_date` is before today move to `EXPIRED`; fourth, exam attempts still `SCHEDULED` more than 24 hours after their `scheduled_at` instant move to `NO_SHOW`; fifth, each school's first-attempt pass rate over the trailing 90-day window is evaluated and its posture updated. Each entity advances at most one state hop per sweep run — a single sweep never moves the same entity twice — and every transition the sweep performs appends an audit event.

### 2.5. Common Resource Properties, Invariants, and Optimistic Concurrency

Every persisted entity except the audit trail carries `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID used for identity only, with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource, including mutations caused by cascades originating elsewhere. `version` is an integer starting at 1 and incrementing by 1 on every mutation. The `AuditEvent` trail is the exception: audit events carry only `id` and `created_at` — they are immutable, so both `updated_at` and `version` are absent.

Three write operations are guarded by optimistic concurrency control. The offering update capability (`PUT /offerings/{id}`) requires a non-optional `expected_offering_version` field carrying the client's last observed `version` of the offering; if another writer has advanced the offering's version since the client last read it, the update is rejected with `ERR_STALE_OFFERING_VERSION` (HTTP 412) rather than silently overwriting that change. Creating an equivalency grant requires `expected_course_version` matching the course's current `version`, because grant creation supersedes existing grants and the client must have observed the latest grant state; a mismatch is rejected with `ERR_STALE_COURSE_VERSION` (HTTP 412). Creating an amendment against an acknowledged credit report requires `expected_credit_report_version` matching that report's current `version`; a mismatch is rejected with `ERR_STALE_CREDIT_REPORT_VERSION` (HTTP 412). Endpoints not listed here do not take a version field.

A successful update or amendment-creation under these guards increments the guarded parent's `version` by 1.

### 2.6. Validation Pipeline and Error Precedence

A single request may violate several rules at once; rejections follow a fixed precedence, and the first matching rule's error is the one returned. The evaluation order is:

1. **Authentication context.** Headers present, role declared, entity-backed identity resolvable — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The role appears on the endpoint's authorized list — otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Request shape.** Required fields present, unknown fields rejected, enum values within their declared sets (`ERR_INVALID_ENUM`), integers within range, ISO dates parseable — otherwise `ERR_INVALID_REQUEST`, or the more specific shape errors `ERR_ATTENDANCE_MINUTES_INVALID` (attendance `minutes` outside 1 through 1440 inclusive) and `ERR_SCORE_OUT_OF_RANGE` (`score_pct` outside 0 through 100 inclusive). Pagination bounds also fail here with `ERR_INVALID_PAGINATION_PARAMETERS`.
4. **Existence.** Path identifiers are resolved left to right, each producing its resource-specific not-found error (`ERR_SCHOOL_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_INSTRUCTOR_APPROVAL_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_ATTENDANCE_RECORD_NOT_FOUND`, `ERR_EXAM_ATTEMPT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, `ERR_CREDIT_REPORT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`), and body-supplied foreign references — `school_id`, `course_id`, `offering_id`, `student_id`, `instructor_id`, `proctor_instructor_id` — must each reference an existing entity.
5. **Scope and stale versions.** Ownership and scope checks (`ERR_FORBIDDEN_SCOPE`) run first; immediately after scope, the three OCC-guarded endpoints evaluate their `expected_*_version` field against the parent's current version (`ERR_STALE_OFFERING_VERSION`, `ERR_STALE_COURSE_VERSION`, `ERR_STALE_CREDIT_REPORT_VERSION`) — before any state or business rule.
6. **State gates.** The target resource, and any gated cross-entity parents, must be in a valid state for the operation: school `LICENSED` where required (`ERR_SCHOOL_NOT_LICENSED`; operating on a `REVOKED` school yields `ERR_SCHOOL_TERMINAL`), course `ACTIVE` where required (`ERR_COURSE_NOT_ACTIVE`), offering `PUBLISHED` for enrollment (`ERR_OFFERING_NOT_OPEN`), enrollment in a withdrawable, payable, voidable, certificate-issuable, or attempt-schedulable state (`ERR_ENROLLMENT_STATE_INVALID`), enrollment `SEAT_TIME_MET` for attempt creation (`ERR_SEAT_TIME_NOT_MET`), attempt in the correct lifecycle state (`ERR_EXAM_ATTEMPT_STATE_INVALID`), approval in the correct state for decide, resubmit, or renew (`ERR_APPROVAL_STATE_INVALID`), refund request in the correct state for approve, deny, or pay (`ERR_REFUND_STATE_INVALID`), credit report in the correct state for submit, acknowledge, reject, revise, or amendment (`ERR_REPORT_STATE_INVALID`), grant `ACTIVE` or `SUSPENDED` for revocation (`ERR_GRANT_STATE_INVALID`), course activation requiring at least one approved approval (`ERR_COURSE_NOT_APPROVED_ANYWHERE`), and course retirement requiring no open offerings (`ERR_COURSE_HAS_OPEN_OFFERINGS`). All of these are HTTP 409.
7. **Regulatory safety.** School posture must be `GOOD_STANDING` for course-approval submissions, approval renewals, and offering publication (`ERR_SCHOOL_ON_PROBATION`), and segregation of duties must hold between proctor and instructor of record (`ERR_PROCTOR_IS_INSTRUCTOR`). Both are HTTP 422.
8. **Temporal windows and overlaps.** Offering windows, schedule conflicts, attendance windows, report windows and report-period overlaps, renewal windows, and validity windows — detailed in §3 and carried by `ERR_INVALID_OFFERING_WINDOW`, `ERR_STUDENT_SCHEDULE_CONFLICT`, `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`, `ERR_PROCTOR_SCHEDULE_CONFLICT`, `ERR_ATTENDANCE_OUT_OF_WINDOW`, `ERR_REPORT_WINDOW_INVALID`, `ERR_REPORT_PERIOD_OVERLAP`, `ERR_APPROVAL_RENEWAL_WINDOW_CLOSED`, and `ERR_INVALID_VALIDITY_WINDOW`.
9. **Referenced-entity state coherence.** Course authorized in the delivery state (`ERR_COURSE_NOT_AUTHORIZED_IN_STATE`), instructor approved in the delivery state (`ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE`), grant source approval `APPROVED` (`ERR_SOURCE_APPROVAL_NOT_APPROVED`) — within this tier the pinned evaluation order is course authorization first, then instructor approval, then grant source approval.
10. **Uniqueness, capacity, and count limits.** Duplicate identifiers and license numbers, approval singletons, full offerings, exhausted exam attempts, capacity below enrollment, same-state grants, and invalid manual withdrawal reasons: `ERR_DUPLICATE_SCHOOL_CODE`, `ERR_DUPLICATE_COURSE_CODE`, `ERR_DUPLICATE_STUDENT_EMAIL`, `ERR_DUPLICATE_INSTRUCTOR_LICENSE`, `ERR_APPROVAL_ALREADY_EXISTS`, `ERR_OFFERING_FULL`, `ERR_EXAM_ATTEMPTS_EXHAUSTED`, `ERR_CAPACITY_BELOW_ENROLLED`, `ERR_GRANT_SAME_STATE`, and `ERR_WITHDRAWAL_REASON_INVALID`.
11. **Fiscal exactness.** Payment amounts must equal the pinned charge exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`).

### 2.7. Monetary Precision and Rounding Conventions

All money is integer cents. Credit hours are numbers rounded per reporting line to the nearest 0.5 hour, with halves rounded up, before any summation. Basis-point rates — the school's pass-rate floor, observed pass rates, and the enrollment completion fraction — are integers where 10000 represents 100 percent, computed with round-half-up. Dates and durations are integer days. Wherever a calculation below pins a rounding step (the scholarship cap's floor, the statutory daily rate's pre-multiplication rounding, the completion fraction's half-up integer), that pinned step is part of the contract and rounding elsewhere produces a different, non-conformant result.

### 2.8. The Append-Only Audit Trail

Every mutating operation in the system — actor-driven or sweep-driven — appends an `AuditEvent`. Each event records `entity_type` (the name of the mutated resource's type, for example an enrollment), `entity_id` (the mutated resource's `id`; this is a polymorphic reference resolved through `entity_type`, not a foreign key), `event_type` (a mutation name such as a creation event, `STATUS_CHANGE`, or `CASCADED_REVOCATION`), `actor_role` and `actor_id` (the acting request's `X-User-Role` and `X-User-ID`, with the literal value "system" for sweep and cascade events), and `detail`, a payload object carrying, where relevant, the prior status, the new status, and an optional note. Events are immutable once written — the trail has no update or delete capability — and are readable by all four staff roles, filterable by `entity_type`, `entity_id`, and `event_type`. Because cascades refresh `updated_at` and bump `version` on every resource they touch, the trail is the authoritative record of which change was direct and which was downstream.

## 3. Business Logic & Workflows

### 3.1. Founding a School: Registration, Licensing, and Pass-Rate Surveillance

A school enters the system when a `SchoolDirector` registers it with its legal `school_name`, a `school_code`, the `home_state_code` of its primary licensure state, and optionally a `pass_rate_threshold_bps`. The `school_code` must be globally unique across all schools — it will later form the prefix of every certificate number the school issues — and a duplicate is rejected with `ERR_DUPLICATE_SCHOOL_CODE`. The pass-rate floor is expressed in basis points and must lie between 0 and 10000 inclusive; when omitted it defaults to 6000, meaning sixty percent. The registering director's `X-User-ID` is recorded as `director_user_id` and thereafter scopes every director operation on that school. A new school starts with `status` `PROVISIONAL` and `posture` `GOOD_STANDING`, with `last_evaluation_attempt_count` at 0 and `last_evaluation_first_attempt_pass_rate_bps` null until the first evaluation.

The school's `status` dimension is actor-driven by the `StateCommission`: licensing moves `PROVISIONAL` to `LICENSED`; suspension moves `LICENSED` to `SUSPENDED`; reinstatement returns `SUSPENDED` to `LICENSED`; revocation moves any of `PROVISIONAL`, `LICENSED`, or `SUSPENDED` to the terminal `REVOKED`. Only a `LICENSED` school may create courses or publish offerings — attempts against a `PROVISIONAL` or `SUSPENDED` school are rejected with `ERR_SCHOOL_NOT_LICENSED`, and operations against a `REVOKED` school with `ERR_SCHOOL_TERMINAL`.

The `posture` dimension is system-derived and cycles between `GOOD_STANDING` and `PROBATION` during the sweep's fifth phase. The evaluation window is the trailing 90 days ending today, both dates inclusive. Within it, the first-attempt set comprises the school's exam attempts with `attempt_number` equal to 1 that reached `SCORED` with a `scored_at` date inside the window; `NO_SHOW` and `INVALIDATED` attempts are excluded. The school's `first_attempt_pass_rate_bps` is the count of `PASSED` outcomes in that set multiplied by 10000 and divided by the set's size, rounded half-up to an integer; when the set is empty the rate is null. A parallel `all_attempts_pass_rate_bps` is computed identically over all scored attempts in the window, retakes included. Posture changes only when the first-attempt set holds at least 10 entries: below the floor — strictly below; a rate exactly equal to `pass_rate_threshold_bps` does not trigger probation — the school's `posture` becomes `PROBATION`, and at or above the floor it becomes `GOOD_STANDING`. When fewer than 10 first attempts exist in the window, posture is left untouched, a small-sample suppression that makes probation sticky across quiet quarters. Every evaluation refreshes `last_evaluation_attempt_count` and `last_evaluation_first_attempt_pass_rate_bps` with the observed values. A probation reading guards the regulatory surface: while `posture` is `PROBATION`, new course-approval applications, approval renewals, and offering publication are rejected with `ERR_SCHOOL_ON_PROBATION`.

Staff may also read the pass-rate computation on demand — a summary carrying `window_start`, `window_end`, `first_attempt_count`, `first_attempt_pass_rate_bps`, `all_attempt_count`, `all_attempts_pass_rate_bps`, and the school's current `posture`. This read is available to `StateCommission`, `SchoolDirector`, and `ComplianceOfficer` and never mutates posture; only the sweep does that.

### 3.2. Course Catalog and State Approval

Within a licensed school, a `SchoolDirector` builds the catalog. Each course carries a `course_code` unique within its school (duplicates rejected with `ERR_DUPLICATE_COURSE_CODE`), a `title`, a `course_type` of either `PRE_LICENSING` or `CONTINUING_ED`, the state-mandated `required_seat_minutes` (strictly greater than 0), catalog `tuition_cents` (at least 0), the inclusive minimum final-exam score `pass_score_pct` (1 through 100), and `completion_deadline_days`, the number of days after an offering's `end_date` by which an enrollment must complete (at least 1). Two inputs carry defaults: `max_exam_attempts`, the maximum number of non-`INVALIDATED` exam attempts per enrollment, defaults to 2 and must be at least 1; and `ce_credit_hours`, the continuing-education hours granted on completion, defaults to 0 — only courses with `ce_credit_hours` greater than 0 ever appear on credit reports. Courses are born `DRAFT`.

Before a course can activate, at least one of its approval applications must stand `APPROVED`; activation without one fails with `ERR_COURSE_NOT_APPROVED_ANYWHERE`. Retirement moves `ACTIVE` to the terminal `RETIRED`, but only when no offering of the course remains in `DRAFT`, `PUBLISHED`, or `IN_SESSION` — otherwise `ERR_COURSE_HAS_OPEN_OFFERINGS`. Courses may be listed filtered by `school_id`, `status`, or `course_type`.

Course approval is a per-state affair handled by the `ComplianceOfficer`. Submitting an application for a `state_code` creates a `CourseApproval` in `PENDING` with `application_round` 1; only one application may exist per course-and-state pair, a duplicate drawing `ERR_APPROVAL_ALREADY_EXISTS`. The `StateCommission` then decides by supplying a `decision` of approve or deny. An approval decision requires the payload's `valid_from` and `valid_until` calendar dates with `valid_until` no earlier than `valid_from`; missing or inverted windows are rejected with `ERR_INVALID_VALIDITY_WINDOW`. An approve decision stamps `valid_from`, `valid_until`, and `decided_at` and moves the application to `APPROVED`; a deny stamps `decided_at` and moves it to `DENIED`. A denied application is not dead: resubmission by the `ComplianceOfficer` returns `DENIED` to `PENDING`, increments `application_round` by 1, and clears `decided_at` to null.

Approvals age on the sweep. An `APPROVED` application whose `valid_until` is 30 or fewer days away (and not yet passed) moves to `EXPIRING`; once today passes `valid_until`, `EXPIRING` becomes the terminal `EXPIRED`. Renewal is available from either state: from `EXPIRING` at any time, and from `EXPIRED` only as a late renewal within 30 days after `valid_until` — past that window the attempt fails with `ERR_APPROVAL_RENEWAL_WINDOW_CLOSED`. Renewal moves the application to `RENEWAL_PENDING`, from which the commission decides again. Approving a renewal increments `application_round` by 1, stamps the new validity window, and returns the application to `APPROVED`; denying a renewal stamps `decided_at` and moves it to `EXPIRED`.

Approval of a course in its home state has a second effect: every equivalency grant of that course keyed on that state with status `SUSPENDED` resumes to `ACTIVE`. Symmetrically, when an approval lapses to `EXPIRED` — by sweep or by a denied renewal — every equivalency grant of that course and state standing `ACTIVE` is suspended.

Those equivalency grants are how a course approved in one state earns recognition in another. A grant is created by the `ComplianceOfficer` with the `course_id`, the `home_state_code` where the course holds its direct approval, and the `recognized_state_code` doing the recognizing. The two states must differ (`ERR_GRANT_SAME_STATE`), and the course's approval in the home state must stand `APPROVED` (`ERR_SOURCE_APPROVAL_NOT_APPROVED`). Creation is OCC-guarded per §2.5: the request must carry `expected_course_version`, a mismatch with the course's current `version` is rejected with `ERR_STALE_COURSE_VERSION` (HTTP 412), and a successful creation increments the course's `version` by 1. Creating a grant for a course-home-recognized triple that already has a grant in `ACTIVE` or `SUSPENDED` supersedes it — the older grant moves to `SUPERSEDED`. New grants stand `ACTIVE`.

Grants track their source approval automatically. When the home-state course approval lapses to `EXPIRED` — through the sweep or a denied renewal — each grant keyed on it moves from `ACTIVE` to `SUSPENDED`; when the approval returns to `APPROVED` through an approved renewal, each `SUSPENDED` grant resumes to `ACTIVE`. A suspended grant does not satisfy the publication gate of §3.4. Revocation by the `StateCommission` or the `ComplianceOfficer` moves a grant from `ACTIVE` or `SUSPENDED` to the terminal `REVOKED` — any other state draws `ERR_GRANT_STATE_INVALID`. Grants may be listed filtered by `course_id`, `recognized_state_code`, or `status`.

### 3.3. Instructor Roster and Credentialing

The `Registrar` maintains the instructor roster. Registration records the employing school, the instructor's `full_name`, and the state-issued `license_number`, which must be unique within the school — duplicates are rejected with `ERR_DUPLICATE_INSTRUCTOR_LICENSE`. Instructors may be listed filtered by `school_id`.

Instructor credentialing mirrors course approval exactly, on a separate track. The `Registrar` files an instructor-approval application for a `state_code`, creating an `InstructorApproval` in `PENDING` with `application_round` 1, singleton per instructor-and-state (`ERR_APPROVAL_ALREADY_EXISTS`). The commission's decision follows the same contract as course approvals — approve requires a well-formed `valid_from` / `valid_until` window (`ERR_INVALID_VALIDITY_WINDOW`), stamps the window and `decided_at`, and moves to `APPROVED`; deny stamps `decided_at` and moves to `DENIED`. Resubmission by the `Registrar` returns `DENIED` to `PENDING`, increments `application_round` by 1, and clears `decided_at`. The sweep ages instructor approvals on the same rules as course approvals — `APPROVED` to `EXPIRING` inside the 30-day runway, `EXPIRING` to `EXPIRED` past `valid_until` — and the `Registrar` renews from `EXPIRING`, or from `EXPIRED` within the same 30-day late window (`ERR_APPROVAL_RENEWAL_WINDOW_CLOSED`), into `RENEWAL_PENDING`, where an approving decision increments `application_round` and re-stamps the window and a denying decision sends the application to `EXPIRED`. Unlike course approvals, instructor approvals carry no equivalency side effects.

### 3.4. Scheduling an Offering: Windows, Rest Days, and Publication Gates

With an active course and a credentialed instructor, the `SchoolDirector` schedules a `CourseOffering` by supplying the `course_id`, the `instructor_id` of the instructor of record, the `state_code` in which the offering is delivered and credited, the `start_date` and `end_date` calendar dates, the seat `capacity` (at least 1), and a `delivery_mode` of `IN_PERSON` or `DISTANCE`. The window must be well formed: `end_date` no earlier than `start_date`, and `start_date` no earlier than today — otherwise `ERR_INVALID_OFFERING_WINDOW`. Creating the course's offering also enforces the instructor's rest-day rule (see below) and requires the course to be `ACTIVE` (`ERR_COURSE_NOT_ACTIVE`). A new offering stands `DRAFT` with `enrolled_count` 0 and `seats_available` equal to `capacity`.

The instructor rest-day rule protects teaching quality across an instructor's calendar: for every non-`CANCELLED` offering the instructor already holds, the new window must leave one full rest day between windows. A conflict exists unless the new `start_date` is at least two days after the existing offering's `end_date`, or the existing offering's `start_date` is at least two days after the new `end_date`; otherwise the create is rejected with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`. Concretely, an existing offering ending 2026-09-10 blocks a new start on 2026-09-11 but permits 2026-09-12.

Publication is the regulatory checkpoint. Publishing a `DRAFT` offering enforces five gates, and their precedence follows the global validation pipeline: the school must be `LICENSED` (`ERR_SCHOOL_NOT_LICENSED`), the school's posture must be `GOOD_STANDING` (`ERR_SCHOOL_ON_PROBATION`), the course must be `ACTIVE` (`ERR_COURSE_NOT_ACTIVE`), the course must be authorized in the offering's `state_code` — either by an `APPROVED` course approval for that state or by an `ACTIVE` equivalency grant recognizing the course there, otherwise `ERR_COURSE_NOT_AUTHORIZED_IN_STATE` — and the instructor must hold an `APPROVED` instructor approval in that state, otherwise `ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE`. A published offering opens for enrollment. From `PUBLISHED` the sweep moves the offering to `IN_SESSION` when today reaches `start_date`, and from `IN_SESSION` to `COMPLETED` once today passes `end_date`.

A `SchoolDirector` may reschedule or resize an offering while it is `DRAFT` or `PUBLISHED`, updating `start_date`, `end_date`, or `capacity` — each optional, with the unchanged fields left intact. The update re-validates the window rules and the instructor rest-gap rule against the new dates, and the new capacity may not fall below the offering's current `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`). This is the OCC-guarded offering write described in §2.5: the request must carry `expected_offering_version`, and a mismatch with the offering's current `version` is rejected with `ERR_STALE_OFFERING_VERSION` (HTTP 412). A successful update increments the offering's `version` by 1.

Cancellation is available from `DRAFT`, `PUBLISHED`, or `IN_SESSION`; cancelling an offering in any other state is rejected with `ERR_OFFERING_NOT_CANCELLABLE`. Cancelling a `DRAFT` offering merely records the status change. Cancelling a `PUBLISHED` or `IN_SESSION` offering triggers a three-level cascade. First, every enrollment of the offering whose `academic_status` is `ENROLLED`, `IN_PROGRESS`, `SEAT_TIME_MET`, or `EXAM_PASSED` moves to `WITHDRAWN` with `withdrawal_reason` `SCHOOL_CANCELLED` and `withdrawn_at` set to now — including `EXAM_PASSED` enrollments, which cannot yet hold a certificate because issuance requires the `EXAM_PASSED` state and is blocked once `WITHDRAWN`. Second, for each such enrollment whose `payment_status` is `PAID`, a refund request is auto-created in `PENDING` with `reason` `SCHOOL_CANCELLED` and the scheduled, statutory, and granted amounts all equal to the enrollment's `paid_cents`; enrollments still `PENDING` on payment flip to `VOIDED` instead. Third, the offering's `enrolled_count` and `seats_available` are recomputed, each withdrawal decrementing the count. The cascade writes a `CASCADED_CANCELLATION` audit event on the offering and a `STATUS_CHANGE` event per enrollment.

### 3.5. Enrollment, Tuition, and Seat Accounting

The `Registrar` registers students with the school, a `full_name`, an `email` unique within the school case-insensitively (`ERR_DUPLICATE_STUDENT_EMAIL`), and the `license_goal_state` the student seeks licensure in. Students may be listed filtered by `school_id` or `email`; a `Student`-role caller may read only its own record.

Enrollment is open to the `Registrar` on behalf of any student, and to a `Student` self-enrolling. The request carries the `offering_id` and optionally a `student_id` and a `scholarship_cents` amount (at least 0, defaulting to 0). For a `Student` caller, `student_id` defaults to the caller's `X-User-ID`, and when supplied it must equal it — self-service may not enroll others; the `Registrar` supplies `student_id` explicitly. Enrollment requires the offering to be `PUBLISHED` (`ERR_OFFERING_NOT_OPEN`) with at least one seat free — `seats_available` at least 1, else `ERR_OFFERING_FULL` — and enforces the student's schedule-integrity rule: the student must not already hold an enrollment whose `academic_status` is not one of `WITHDRAWN`, `FAILED`, or `EXPIRED` and whose offering window overlaps the new one under half-open semantics. Windows that merely touch are allowed — a new offering starting the day an existing one ends, or ending the day the existing one starts, is adjacent rather than overlapping; any strict overlap is rejected with `ERR_STUDENT_SCHEDULE_CONFLICT`.

Creation fixes the enrollment's financial shape once, for its lifetime. The charge computation runs in a pinned order: first, the applied scholarship is the lesser of the requested `scholarship_cents` and half of the course's `tuition_cents` rounded down to a whole cent — the scholarship never covers more than half the tuition; second, the discounted tuition is `tuition_cents` minus that applied scholarship; third, the registration fee is 2500 cents when the discounted tuition is at least 100000 cents, and 1500 cents otherwise — note the fee tier keys on the discounted tuition, not on the final total; fourth, `charge_total_cents` is the discounted tuition plus the registration fee. For example, a 50000-cent tuition with a 30000-cent scholarship applies a 25000-cent scholarship cap, yields 25000 discounted, attracts the 1500-cent fee, and totals 26500 cents; a 150000-cent tuition with no scholarship totals 152500 cents. The result is pinned as the enrollment's `charge_total_cents` and never recomputed.

The new enrollment starts with `academic_status` `ENROLLED` and `payment_status` `PENDING` — two parallel dimensions that evolve independently. `enrolled_at` records the clock timestamp of creation, `paid_cents` starts at 0, `retained_cents` tracks what the school keeps after refunds, `verified_seat_minutes` and `creditable_seat_minutes` start empty, and `deadline_date` is computed as the offering's `end_date` plus the course's `completion_deadline_days`. The offering's `enrolled_count` and `seats_available` are recomputed, and they obey a standing invariant: `enrolled_count` is the count of the offering's enrollments whose `academic_status` is not one of `WITHDRAWN`, `FAILED`, or `EXPIRED`, and `seats_available` is `capacity` minus `enrolled_count`, so capacity always equals enrolled seats plus available seats. This recomputation runs on every event that moves an enrollment into or out of the active set — creation, withdrawal, expiry, failure, the cancellation cascade, and capacity updates.

Payment capture is exact-amount only: the request's `amount_cents` must equal the pinned `charge_total_cents`, with any difference rejected as `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful capture moves `payment_status` from `PENDING` to `PAID` and sets `paid_cents` to `amount_cents`. Refund amounts are never client-supplied — they are always system-computed, and a client-supplied amount on any refund path is rejected as an unknown field.

Manual withdrawal is available to the `Registrar`, or to the `Student` on its own enrollment, from any of `ENROLLED`, `IN_PROGRESS`, or `SEAT_TIME_MET`. The supplied `reason` must be `VOLUNTARY` or `ADMINISTRATIVE` — the third value, `SCHOOL_CANCELLED`, is produced only by the offering-cancellation cascade and is rejected on manual withdrawal with `ERR_WITHDRAWAL_REASON_INVALID` (HTTP 400). An optional `effective_date` may pin the withdrawal date. Withdrawal sets `withdrawn_at` to now (or to `effective_date` when supplied), records the `withdrawal_reason`, moves `academic_status` to `WITHDRAWN`, recomputes the offering's seat accounting — and then branches on payment. If `payment_status` is `PAID`, a `RefundRequest` is auto-created in `PENDING` with the enrollment's `completion_fraction_bps` frozen into `completion_fraction_bps_at_withdrawal` and its scheduled, statutory, and granted amounts computed. If `payment_status` is still `PENDING`, it flips to `VOIDED` and no refund request is created. At most one refund request ever exists per enrollment. The sweep separately expires enrollments: any enrollment in `ENROLLED`, `IN_PROGRESS`, `SEAT_TIME_MET`, or `EXAM_PASSED` whose `deadline_date` is before today moves to the terminal `EXPIRED`.

### 3.6. Seat Time Under the Daily Cap

Seat time is recorded by the offering's instructor of record — the `Instructor` caller's `X-User-ID` must equal the offering's `instructor_id`, and the server stores it as `recorded_by_instructor_id` — against enrollments whose `academic_status` is `ENROLLED`, `IN_PROGRESS`, or `SEAT_TIME_MET`. Each `AttendanceRecord` carries a `session_date`, which must lie within the offering's window from `start_date` through `end_date` inclusive (`ERR_ATTENDANCE_OUT_OF_WINDOW`), and `minutes` attended, between 1 and 1440 inclusive (`ERR_ATTENDANCE_MINUTES_INVALID`). Records are created `VERIFIED`. The first verified record moves the enrollment from `ENROLLED` to `IN_PROGRESS`.

Two seat-minute totals are maintained on the enrollment, and they diverge by design. `verified_seat_minutes` is the raw, uncapped sum of `minutes` over the enrollment's `VERIFIED` records. `creditable_seat_minutes` applies the daily credit cap of 480 minutes: the enrollment's `VERIFIED` records are processed in chronological order — `session_date` ascending, ties broken by `created_at` ascending — keeping a running per-calendar-day total, and each record is credited the lesser of its own `minutes` and the headroom remaining under that day's cap (never less than zero). The creditable total is the sum of those credited values; `VOID` records are excluded from both sums. So a single 500-minute session day contributes 500 to the verified total but only 480 to the creditable one, and the two fields diverge whenever any day exceeds the cap. Both totals are recomputed in full after every record creation or void.

From the creditable total the system derives `completion_fraction_bps`: the creditable minutes multiplied by 10000, divided by the course's `required_seat_minutes`, and rounded half-up to an integer basis-point value — which may exceed 10000 when a student attends beyond the requirement. When a recomputation brings `creditable_seat_minutes` to at least `required_seat_minutes` — equality qualifies — the enrollment moves from `IN_PROGRESS` to `SEAT_TIME_MET`.

Voiding is the instructor's correction mechanism: a record's status flips from `VERIFIED` to `VOID`, the totals are recomputed, and if the creditable total drops back below the requirement the enrollment regresses from `SEAT_TIME_MET` to `IN_PROGRESS` — the seat-time dimension loops rather than ratchets. Voiding is forbidden once the enrollment has reached `EXAM_PASSED` or `COMPLETED` (`ERR_ENROLLMENT_STATE_INVALID`); by then the seat-time question is settled.

### 3.7. Proctored Final Examinations and Segregation of Duties

Once an enrollment stands `SEAT_TIME_MET`, the `Registrar` schedules a proctored final-exam attempt, supplying the `scheduled_at` instant and the `proctor_instructor_id` of the assigned proctor. Scheduling from any other academic state fails with `ERR_SEAT_TIME_NOT_MET`. Segregation of duties is absolute: the proctor must not be the offering's instructor of record — a `proctor_instructor_id` equal to the offering's `instructor_id` is rejected with `ERR_PROCTOR_IS_INSTRUCTOR` — and the proctor must not already hold another attempt in `SCHEDULED` or `PROCTORED` on the same calendar date (`ERR_PROCTOR_SCHEDULE_CONFLICT`). Attempt throughput is capped: `exam_attempts_used` counts the enrollment's attempts in `SCHEDULED`, `PROCTORED`, `SCORED`, or `NO_SHOW` — `INVALIDATED` attempts consume no slot — and scheduling is rejected when that count already equals the course's `max_exam_attempts` (`ERR_EXAM_ATTEMPTS_EXHAUSTED`). With the default maximum of 2, attempt number 2 is allowed and a third is refused. The new attempt's `attempt_number` is `exam_attempts_used` plus 1, and it starts `SCHEDULED`. Attempts may be browsed globally by staff with filters on `proctor_instructor_id`, `enrollment_id`, and `status`.

On exam day the assigned proctor verifies the candidate — verification requires the caller's `X-User-ID` to equal the attempt's `proctor_instructor_id` (`ERR_FORBIDDEN_SCOPE`) — moving the attempt from `SCHEDULED` to `PROCTORED` and stamping `verified_at`. Scoring belongs to the instructor of record alone: the caller's `X-User-ID` must equal the offering's `instructor_id` (`ERR_FORBIDDEN_SCOPE`), the attempt must be `PROCTORED` (verifying requires `SCHEDULED`, scoring requires `PROCTORED`, and any other state draws `ERR_EXAM_ATTEMPT_STATE_INVALID`), and the supplied `score_pct` must lie between 0 and 100 inclusive (`ERR_SCORE_OUT_OF_RANGE`). Scoring stamps `scored_at`, moves the attempt to `SCORED`, and computes `outcome`: `PASSED` when `score_pct` is at least the course's `pass_score_pct` — the threshold is inclusive — otherwise `FAILED`. A pass moves the enrollment from `SEAT_TIME_MET` to `EXAM_PASSED`. A fail moves it from `SEAT_TIME_MET` to the terminal `FAILED` only when the attempt just consumed the last allowed slot — `exam_attempts_used` equal to `max_exam_attempts`; otherwise the student may sit another attempt. Attempts abandoned without invalidation are swept: an attempt still `SCHEDULED` more than 24 hours after its `scheduled_at` moves to `NO_SHOW`, which does consume a slot.

Invalidation is the disciplinary path, available to the assigned `Proctor` or a `SchoolDirector` from any of `SCHEDULED`, `PROCTORED`, or `SCORED`, with the `reason` recorded as `invalidation_reason`. Invalidating a `SCHEDULED` or `PROCTORED` attempt simply frees its slot. Invalidating a `SCORED` attempt whose `outcome` was `PASSED` unwinds the academic record: the enrollment regresses from `EXAM_PASSED` back to `SEAT_TIME_MET` — or from `COMPLETED` back to `SEAT_TIME_MET`, a rare exit from the apex state — and, when the regression leaves a `COMPLETED` enrollment, the cascade continues: the enrollment's certificate moves from `ACTIVE` to `REVOKED` with `revoked_reason` `EXAM_INVALIDATED`, and that revocation in turn fires the credit-report amendment drafting described in §3.8. The regression makes the enrollment exam-eligible again; seat time is presumed intact because voiding is closed past `EXAM_PASSED`.

### 3.8. Certificates and Credit Reporting to the Licensing Authority

Certificate issuance is the `Registrar`'s act on an enrollment standing `EXAM_PASSED` — any other state fails with `ERR_ENROLLMENT_STATE_INVALID` — and at most one certificate ever exists per enrollment. Issuance mints the certificate's `certificate_number` from the school's `school_code`, the issue calendar year, and a four-digit zero-padded sequence: the sequence is the count of all certificates the school has ever issued in that calendar year plus one, with `ACTIVE` and `REVOKED` certificates both counted and numbers never reused — a revocation never frees a number. The certificate pins `credit_hours_pinned` from the course's `ce_credit_hours` at issuance, records the clock date as `issue_date`, and stands `ACTIVE`; the enrollment advances from `EXAM_PASSED` to `COMPLETED`. `COMPLETED` is an apex but not a terminal state — exam invalidation regresses it as described above.

Revocation is available to the `StateCommission` and the `SchoolDirector`, and to the system through the exam-invalidation cascade, with the `reason` recorded as `revoked_reason` and the clock timestamp as `revoked_at`. Revoking a certificate cascades into the reporting layer: for every credit report in `ACKNOWLEDGED` whose `line_items` reference the revoked certificate and which does not already have a `DRAFT` or `SUBMITTED` amendment, the system auto-creates an amendment report in `DRAFT` whose `amendment_of_id` points at the acknowledged report, whose lines are the revoked certificate's lines with their credit hours negated, and whose `total_credit_hours` is therefore negative.

The `ComplianceOfficer` files the school's continuing-education credit reports. A base report is created for a school with a `period_start` and `period_end` — the end must not precede the start (`ERR_REPORT_WINDOW_INVALID`) — and an optional `reason`. Base reports of one school must not overlap: any other base report whose closed period intersects the new one, touching endpoints included — one report's `period_end` exactly equal to another's `period_start` is already a conflict — is rejected with `ERR_REPORT_PERIOD_OVERLAP`. At creation the report snapshots its `line_items`: one line per certificate of the school standing `ACTIVE` at creation time with `issue_date` inside the period, both ends inclusive, and `credit_hours_pinned` greater than 0. Each line carries the certificate as `certificate_id`, its enrollment, its student, and a `credit_hours` value rounded to the nearest half hour with halves rounded up; `total_credit_hours` is the sum of the per-line rounded values — rounding per line first and then summing is the pinned order, since summing raw hours and rounding once yields different results. Lines are ordered by certificate `issue_date` ascending, ties broken by certificate `created_at` ascending. The report's `reporting_deadline_date` is `period_end` plus 30 calendar days, and its `submission_count` starts at 0. Reports are born `DRAFT`.

Submission by the `ComplianceOfficer` moves `DRAFT` to `SUBMITTED`, stamps `submitted_at` with the clock timestamp, increments `submission_count` by 1, and computes lateness: `late_days` is the number of days by which the submit calendar date falls after `reporting_deadline_date`, floored at zero, so submitting exactly on the deadline day yields zero late days and no fee. When at least one late day exists, `late_fee_cents` is 5000 cents plus 1000 cents per late day, capped at 50000 cents — the cap binds from 45 late days upward, where the formula reaches the cap exactly. The `StateCommission` then acknowledges the report — `SUBMITTED` to the terminal `ACKNOWLEDGED` — or rejects it with a `reason`, moving it to `REJECTED`. Rejection opens the correction cycle: revision by the `ComplianceOfficer` returns `REJECTED` to `DRAFT`, clears `submitted_at` to null, and recomputes `line_items` and `total_credit_hours` from current certificate states, ready to be submitted again; `submission_count` only ever increases. Every state-gated step on this cycle — submit requiring `DRAFT`, acknowledge and reject requiring `SUBMITTED`, revise requiring `REJECTED`, and amendments requiring `ACKNOWLEDGED` — rejects out-of-state calls with `ERR_REPORT_STATE_INVALID`.

Amendments are the `ComplianceOfficer`'s standing correction tool against an `ACKNOWLEDGED` report. An amendment requires a `reason` and is OCC-guarded per §2.5: the request must carry `expected_credit_report_version`, and a mismatch with the parent report's current `version` is rejected with `ERR_STALE_CREDIT_REPORT_VERSION` (HTTP 412), while a successful amendment increments the parent report's `version` by 1. The new report is a `DRAFT` whose `amendment_of_id` points at the parent, and its lines are the parent's lines whose certificates stand `REVOKED` at amendment time, with their already-rounded credit hours negated — negated as stored, without re-rounding. Reports may be listed filtered by `school_id`, `status`, or `amendment_of_id`.

### 3.9. Refund Adjudication: Published Schedule versus Statutory Pro-Rata

Every refund request arises from a withdrawal — manual or cascaded — of a `PAID` enrollment, and carries the withdrawal's `reason` copied from the enrollment's `withdrawal_reason`, the frozen `completion_fraction_bps_at_withdrawal`, and three computed amounts. The two refund philosophies are computed independently and the student always receives the greater.

The published schedule, `scheduled_refund_cents`, branches on the withdrawal reason first. A `SCHOOL_CANCELLED` withdrawal refunds the full `paid_cents` — one hundred percent, no administrative fee. For `ADMINISTRATIVE` and `VOLUNTARY` withdrawals, a tier percentage is chosen by the frozen completion fraction, with boundaries inclusive on the lower refund tier: a fraction of at most 1000 basis points — ten percent of the seat requirement completed — refunds 90 percent of the amount paid; at most 2500 basis points refunds 75 percent; at most 5000 basis points refunds 50 percent; beyond 5000 basis points refunds nothing. The tiered amount is the paid amount multiplied by the tier percentage, rounded half-up to integer cents before any fee step. For `ADMINISTRATIVE` withdrawals that tiered amount is the refund, the administrative fee waived. For `VOLUNTARY` withdrawals a 5000-cent administrative fee is subtracted from the tiered amount, floored at zero.

The statutory rule, `statutory_refund_cents`, is a daily pro-rata with pinned nested rounding. The offering's total days are its `end_date` minus its `start_date` in days plus one. The elapsed days are the withdrawal calendar date minus `start_date` in days plus one, clamped between zero and the total days. The daily rate is `paid_cents` divided by the total days, rounded half-up to integer cents first — this rounding happens before the multiplication, and rounding only at the end is non-conformant. Earned cents are the daily rate multiplied by the elapsed days, an exact integer multiplication with no further rounding. The statutory refund is `paid_cents` minus the earned cents minus a 1000-cent statutory administrative fee, floored at zero. The ordering matters in practice: 50000 cents paid over a 3-day offering with 2 days elapsed yields a daily rate of 16667 cents, earned 33334, and a statutory refund of 15666 — rounding only at the end would produce 15667. The granted amount, `granted_refund_cents`, is the larger of the scheduled and statutory refunds; to see the philosophies diverge, a 50000-cent payment withdrawn voluntarily at a 1000-basis-point fraction schedules 40000 cents but statutes 29000 — the student receives 40000.

Adjudication is deliberately split across roles. A `SchoolDirector` approves a `PENDING` request, stamping `decided_at`, or denies it with a supplied `denial_reason` — a denial without the reason fails with `ERR_INVALID_REQUEST` — also stamping `decided_at`; a denial leaves the enrollment's `payment_status` at `PAID`, and approve or deny from any other state fails with `ERR_REFUND_STATE_INVALID`. Payout is the `Registrar`'s act on an `APPROVED` request — again, any other state fails with `ERR_REFUND_STATE_INVALID` — stamping `paid_at` and settling the enrollment's books: `retained_cents` becomes `paid_cents` minus `granted_refund_cents`, preserving the invariant that the paid amount always equals retained plus granted, and `payment_status` moves to `REFUNDED` when the granted amount equals the full `paid_cents`, otherwise to `PARTIALLY_REFUNDED`. Students may read their own refund requests; staff may list them filtered by `enrollment_id` or `status`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201 and the created resource; endpoints that modify an existing resource, and all reads, respond with 200. All responses use the envelope of §2.2; list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical UTC clock (starts at 2026-08-01T00:00:00Z before any call) | ComplianceOfficer |
| POST | /_admin/run-regulatory-sweep | Advance the regulatory epoch through the five pinned sweep phases | ComplianceOfficer |
| POST | /schools | Register a school (PROVISIONAL, GOOD_STANDING) | SchoolDirector |
| GET | /schools | List schools | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /schools/{id} | Get a school | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| POST | /schools/{id}/license | License a PROVISIONAL school | StateCommission |
| POST | /schools/{id}/suspend | Suspend a LICENSED school | StateCommission |
| POST | /schools/{id}/reinstate | Reinstate a SUSPENDED school | StateCommission |
| POST | /schools/{id}/revoke | Revoke a school's license (terminal) | StateCommission |
| GET | /schools/{id}/pass-rate-summary | Computed pass-rate summary over the trailing 90-day window (read-only) | StateCommission, SchoolDirector, ComplianceOfficer |
| POST | /courses | Create a course (DRAFT) in a LICENSED director-scoped school | SchoolDirector |
| GET | /courses | List courses | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /courses/{id} | Get a course | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| POST | /courses/{id}/activate | Activate a DRAFT course (requires an APPROVED approval) | SchoolDirector |
| POST | /courses/{id}/retire | Retire an ACTIVE course with no open offerings | SchoolDirector |
| POST | /courses/{id}/approvals | Submit a course-approval application to a state (singleton per course+state) | ComplianceOfficer |
| GET | /courses/{id}/approvals | List approval applications of a course | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /approvals/{id} | Get a single course-approval application | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| POST | /approvals/{id}/decide | Commission decision on a PENDING or RENEWAL_PENDING application | StateCommission |
| POST | /approvals/{id}/resubmit | Resubmit a DENIED application (round + 1) | ComplianceOfficer |
| POST | /approvals/{id}/renew | Renew an EXPIRING application, or late-renew an EXPIRED one within 30 days | ComplianceOfficer |
| POST | /instructors | Register an instructor | Registrar |
| GET | /instructors | List instructors | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /instructors/{id} | Get an instructor | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| POST | /instructors/{id}/approvals | Submit an instructor-approval application (singleton per instructor+state) | Registrar |
| GET | /instructors/{id}/approvals | List approval applications of an instructor | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /instructor-approvals/{id} | Get a single instructor-approval application | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| POST | /instructor-approvals/{id}/decide | Commission decision on an instructor application | StateCommission |
| POST | /instructor-approvals/{id}/resubmit | Resubmit a DENIED instructor application | Registrar |
| POST | /instructor-approvals/{id}/renew | Renew an EXPIRING instructor approval, or late-renew an EXPIRED one within 30 days | Registrar |
| POST | /offerings | Create a course offering (DRAFT); validates window and instructor rest gap | SchoolDirector |
| GET | /offerings | List offerings | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| GET | /offerings/{id} | Get an offering | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| PUT | /offerings/{id} | Reschedule/resize a DRAFT or PUBLISHED offering (OCC-guarded) | SchoolDirector |
| POST | /offerings/{id}/publish | Publish a DRAFT offering (state authorization + instructor approval + probation gate) | SchoolDirector |
| POST | /offerings/{id}/cancel | Cancel an offering; cascades withdrawals and 100% refund requests | SchoolDirector |
| POST | /students | Register a student | Registrar |
| GET | /students | List students | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /students/{id} | Get a student (Student role: self only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| POST | /enrollments | Enroll a student in a PUBLISHED offering; computes and pins the charge | Registrar, Student |
| GET | /enrollments | List enrollments (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| GET | /enrollments/{id} | Get an enrollment (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| POST | /enrollments/{id}/withdraw | Withdraw an enrollment; auto-creates a refund request when PAID | Registrar, Student |
| POST | /enrollments/{id}/pay | Capture full payment equal to the pinned charge | Registrar, Student |
| POST | /enrollments/{id}/attendance-records | Record a verified seat-time session (offering's instructor only) | Instructor |
| GET | /enrollments/{id}/attendance-records | List attendance records of an enrollment | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Instructor, Student |
| POST | /attendance-records/{id}/void | Void an attendance record (excluded from sums; may regress seat time) | Instructor |
| POST | /enrollments/{id}/exam-attempts | Schedule a proctored final-exam attempt (requires SEAT_TIME_MET) | Registrar |
| GET | /enrollments/{id}/exam-attempts | List exam attempts of an enrollment | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| GET | /exam-attempts | List exam attempts, filterable by proctor | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |
| GET | /exam-attempts/{id} | Get an exam attempt | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Proctor |
| POST | /exam-attempts/{id}/verify | Assigned proctor verifies the candidate | Proctor |
| POST | /exam-attempts/{id}/score | Offering's instructor scores a PROCTORED attempt | Instructor |
| POST | /exam-attempts/{id}/invalidate | Invalidate an attempt; SCORED-PASSED invalidation cascades | Proctor, SchoolDirector |
| POST | /enrollments/{id}/certificate | Issue the completion certificate (requires EXAM_PASSED) | Registrar |
| GET | /certificates | List certificates (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| GET | /certificates/{id} | Get a certificate (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| POST | /certificates/{id}/revoke | Revoke a certificate; cascades amendment drafting on ACKNOWLEDGED reports | StateCommission, SchoolDirector |
| GET | /refund-requests | List refund requests (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| GET | /refund-requests/{id} | Get a refund request (Student role: own only) | StateCommission, SchoolDirector, Registrar, ComplianceOfficer, Student |
| POST | /refund-requests/{id}/approve | Approve a PENDING refund request | SchoolDirector |
| POST | /refund-requests/{id}/deny | Deny a PENDING refund request | SchoolDirector |
| POST | /refund-requests/{id}/pay | Pay an APPROVED refund; settles enrollment retained amount | Registrar |
| POST | /credit-reports | Create a base CE credit report (DRAFT; line snapshot computed) | ComplianceOfficer |
| GET | /credit-reports | List credit reports | StateCommission, SchoolDirector, ComplianceOfficer |
| GET | /credit-reports/{id} | Get a credit report | StateCommission, SchoolDirector, ComplianceOfficer |
| POST | /credit-reports/{id}/submit | Submit a DRAFT report; computes late days and late fee | ComplianceOfficer |
| POST | /credit-reports/{id}/acknowledge | Acknowledge a SUBMITTED report (terminal) | StateCommission |
| POST | /credit-reports/{id}/reject | Reject a SUBMITTED report | StateCommission |
| POST | /credit-reports/{id}/revise | Return a REJECTED report to DRAFT for correction | ComplianceOfficer |
| POST | /credit-reports/{id}/amendments | Create an amendment against an ACKNOWLEDGED report (OCC-guarded) | ComplianceOfficer |
| POST | /equivalency-grants | Create an equivalency grant; supersedes existing same-key grants (OCC-guarded) | ComplianceOfficer |
| GET | /equivalency-grants | List equivalency grants | StateCommission, SchoolDirector, ComplianceOfficer |
| GET | /equivalency-grants/{id} | Get an equivalency grant | StateCommission, SchoolDirector, ComplianceOfficer |
| POST | /equivalency-grants/{id}/revoke | Revoke an ACTIVE or SUSPENDED grant (terminal) | StateCommission, ComplianceOfficer |
| GET | /audit-events | List append-only audit events | StateCommission, SchoolDirector, Registrar, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_SCOPE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_INVALID_PAGINATION_PARAMETERS | 400 |
| ERR_ATTENDANCE_MINUTES_INVALID | 400 |
| ERR_SCORE_OUT_OF_RANGE | 400 |
| ERR_WITHDRAWAL_REASON_INVALID | 400 |
| ERR_SCHOOL_NOT_FOUND | 404 |
| ERR_COURSE_NOT_FOUND | 404 |
| ERR_APPROVAL_NOT_FOUND | 404 |
| ERR_INSTRUCTOR_NOT_FOUND | 404 |
| ERR_INSTRUCTOR_APPROVAL_NOT_FOUND | 404 |
| ERR_OFFERING_NOT_FOUND | 404 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_ATTENDANCE_RECORD_NOT_FOUND | 404 |
| ERR_EXAM_ATTEMPT_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_REFUND_REQUEST_NOT_FOUND | 404 |
| ERR_CREDIT_REPORT_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_SCHOOL_NOT_LICENSED | 409 |
| ERR_SCHOOL_TERMINAL | 409 |
| ERR_COURSE_NOT_ACTIVE | 409 |
| ERR_COURSE_NOT_APPROVED_ANYWHERE | 409 |
| ERR_COURSE_HAS_OPEN_OFFERINGS | 409 |
| ERR_OFFERING_NOT_OPEN | 409 |
| ERR_OFFERING_NOT_CANCELLABLE | 409 |
| ERR_ENROLLMENT_STATE_INVALID | 409 |
| ERR_SEAT_TIME_NOT_MET | 409 |
| ERR_EXAM_ATTEMPT_STATE_INVALID | 409 |
| ERR_APPROVAL_STATE_INVALID | 409 |
| ERR_REFUND_STATE_INVALID | 409 |
| ERR_REPORT_STATE_INVALID | 409 |
| ERR_GRANT_STATE_INVALID | 409 |
| ERR_INVALID_OFFERING_WINDOW | 422 |
| ERR_STUDENT_SCHEDULE_CONFLICT | 409 |
| ERR_INSTRUCTOR_SCHEDULE_CONFLICT | 409 |
| ERR_PROCTOR_SCHEDULE_CONFLICT | 409 |
| ERR_ATTENDANCE_OUT_OF_WINDOW | 422 |
| ERR_REPORT_WINDOW_INVALID | 422 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_APPROVAL_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_INVALID_VALIDITY_WINDOW | 422 |
| ERR_SCHOOL_ON_PROBATION | 422 |
| ERR_PROCTOR_IS_INSTRUCTOR | 422 |
| ERR_COURSE_NOT_AUTHORIZED_IN_STATE | 422 |
| ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE | 422 |
| ERR_SOURCE_APPROVAL_NOT_APPROVED | 422 |
| ERR_DUPLICATE_SCHOOL_CODE | 409 |
| ERR_DUPLICATE_COURSE_CODE | 409 |
| ERR_DUPLICATE_STUDENT_EMAIL | 409 |
| ERR_DUPLICATE_INSTRUCTOR_LICENSE | 409 |
| ERR_APPROVAL_ALREADY_EXISTS | 409 |
| ERR_OFFERING_FULL | 409 |
| ERR_EXAM_ATTEMPTS_EXHAUSTED | 409 |
| ERR_CAPACITY_BELOW_ENROLLED | 409 |
| ERR_GRANT_SAME_STATE | 409 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_STALE_OFFERING_VERSION | 412 |
| ERR_STALE_COURSE_VERSION | 412 |
| ERR_STALE_CREDIT_REPORT_VERSION | 412 |
