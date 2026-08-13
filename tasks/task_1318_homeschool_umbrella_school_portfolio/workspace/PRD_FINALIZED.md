# Homeschool Umbrella School API — Product Requirements Document

## 1. Introduction

Families schooling their children at home operate under a patchwork of statutory obligations: filing a notice of intent with their district, keeping an approved curriculum plan on record, documenting instructional days and minutes, submitting a year-end portfolio for review, sitting standardized tests in designated grade years, and — for high schoolers — accumulating transcripted credit toward a diploma. A state-recognized umbrella school exists to absorb that administrative burden, and this API is its operating backbone. It governs the full arc of the school year, from the director's creation of an academic calendar through family onboarding, enrollment activation, day-by-day recordkeeping, portfolio and testing cycles, co-op class registration with its fee ledger, graduation adjudication, and the final compliance report filed with the state.

Two design pressures shape everything that follows. First, the system is audit-driven: nearly every number it reports (days counted, minutes credited, credits earned, fees owed) is a derived value recomputed from primary records, and several of those derivations exist in paired "provisional" and "certified" variants so that mid-year warnings and year-end findings can be held to different evidentiary standards. Second, the system is deadline-driven: a single logical clock governs filing windows, registration deadlines, refund tiers, delinquency aging, and an end-of-year compliance sweep that can promote, demote, or restore every enrollment's standing in one pass. Implementers should read §2 for the system-wide contracts and §3 for the workflows those contracts serve.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request carries `X-User-ID` to identify the acting party and `X-User-Role` to declare the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_AUTH_HEADER` (HTTP 400). The platform recognizes six roles, spelled exactly as follows: `Parent`, `Reviewer`, `Registrar`, `AcademicDirector`, `StateAuditor`, and `System`. Each endpoint admits a defined set of roles (§4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity is resolved in two distinct ways. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`, minted when the family self-registers; ownership checks on any resource trace the resource's family chain — a family directly, or a student, enrollment, notice, plan, portfolio, registration, credit, or application resolved up to its root family — and compare that owning family's `id` to `X-User-ID`. Every student record carries its owning family's identifier as `family_id`, which is the link this comparison follows for the whole subtree. A parent therefore can never read or mutate another family's subtree: any such attempt fails with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `Reviewer`, `Registrar`, `AcademicDirector`, or `StateAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reviewer_id` on a curriculum plan or evaluation, as `verified_by` on an attendance entry, or as `evaluated_by` on a graduation application — but never compares it to any entity's `id` for ownership. `System` is an internal actor reserved for sweep-driven and cascade transitions; it is never a legitimate `X-User-Role` on an incoming API call, and no endpoint admits it.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and any supplied value must be at least 1 and at most 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — earliest-created first. Because the logical clock (§2.4) can hold a single instant across many creations, several resources may share an identical `created_at`; ties are broken by the order in which the server created the records, earliest-created first, and entity identifiers are never consulted for ordering.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All temporal reasoning in the system — filing windows, registration deadlines, refund tiers, delinquency aging, sweep eligibility — is evaluated against a single logical clock, never against wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly advanced, every request observes that exact instant. Every server-stamped timestamp on any resource (`created_at`, `updated_at`, `filed_at`, `submitted_at`, `activated_at`, and their kin) derives from this clock.

An `AcademicDirector`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The clock moves forward only; it never moves backward and never falls back to wall-clock time.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource.

Any mutation — including system-driven recomputation of derived counters — updates `updated_at` and increments `version` on the mutated resource. One entity deviates from this convention: an `Evaluation` is immutable once written, so it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from evaluation rows, and the `reviewer_id` recorded on an evaluation can never change.

### 2.6. Nested Resource Retrieval

Requests that address nested resources are validated strictly left-to-right along the path: the existence of each path identifier is confirmed in order, parent segment before child segment, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. A request targeting an attendance entry under a non-existent enrollment therefore fails on the enrollment segment before the entry is ever consulted. This ordering guarantee is part of the contract and applies uniformly to reads, creations, and transitions.

### 2.7. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, each keyed to the version of a parent resource the client has already observed.

Creating a co-op enrollment — the operation that registers a student into a co-op class — requires the request body to carry `expected_coop_class_version`, the client-side observation of the class's current `version`. Because every successful registration mutates the class's `seats_taken`, a client deciding between a confirmed seat and a waitlist position from an outdated seat count would act on fiction; if `expected_coop_class_version` does not match the class's current `version`, the registration is rejected with `ERR_STALE_VERSION` (HTTP 412).

Amending an approved curriculum plan requires the request body to carry `expected_curriculum_plan_version`, the client-side observation of the plan's current `version`. An amendment supersedes the currently approved subject list, so amending from a stale view would silently overwrite a newer approved revision; a mismatch with the plan's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field.

### 2.8. Request Validation Pipeline Ordering

Every request is evaluated against a fixed pipeline of checks, and the order is part of the contract — when several problems coexist, the earliest check in the pipeline determines the error the caller sees.

1. Header presence and shape: `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_AUTH_HEADER`.
2. Role admissibility: the declared role must be permitted for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. Parent ownership: for `Parent` callers, the target must belong to the caller's own family subtree, else `ERR_OWNERSHIP_MISMATCH`.
4. Path existence: identifiers are validated left-to-right, else `ERR_NOT_FOUND`.
5. Body well-formedness: required fields present, types correct, enum members valid, and scalar ranges respected — instructional `minutes` between 1 and 720 inclusive, `composite_percentile` between 1 and 99 inclusive, `grade_level` between 0 and 12 inclusive, capacities at least 1, and window ends after their starts — else `ERR_INVALID_REQUEST`.
6. State feasibility: the target resource's current state must permit the operation. Bare invalid transitions surface as `ERR_INVALID_STATE_TRANSITION`; the named state gates — `ERR_ACADEMIC_YEAR_NOT_OPEN`, `ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_EXAM_SESSION_NOT_OPEN`, `ERR_COOP_CLASS_NOT_OPEN`, `ERR_ATTENDANCE_ENTRY_LOCKED`, `ERR_TRANSCRIPT_SEALED`, the five uniqueness guards `ERR_NOTICE_ALREADY_OPEN`, `ERR_PLAN_ALREADY_EXISTS`, `ERR_PORTFOLIO_ALREADY_EXISTS`, `ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS`, `ERR_REPORT_ALREADY_OPEN`, and the report-timing guard `ERR_REPORT_YEAR_NOT_CLOSED` — are also evaluated at this stage.
7. Stale-version rejection: the optimistic-concurrency checks of §2.7, else `ERR_STALE_VERSION`.
8. Standing and duty gates: compliance-standing blocks (`ERR_ENROLLMENT_NONCOMPLIANT`), reviewer conflict-of-interest (`ERR_REVIEWER_CONFLICT_OF_INTEREST`), and segregation-of-duties rules (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`).
9. Temporal windows: `ERR_ATTENDANCE_DATE_OUT_OF_RANGE`, `ERR_PORTFOLIO_WINDOW_CLOSED`, and `ERR_EXAM_REGISTRATION_DEADLINE_PASSED`.
10. Structural and aggregate constraints: `ERR_ATTENDANCE_DUPLICATE_DATE`, `ERR_PLAN_MISSING_CORE_SUBJECT`, `ERR_COOP_SCHEDULE_OVERLAP`, `ERR_EXAM_SCHEDULE_CONFLICT`, `ERR_EXAM_SESSION_FULL`, `ERR_COOP_GRADE_INELIGIBLE`, `ERR_EXAM_GRADE_MISMATCH`, `ERR_EVALUATION_SCORE_OUTCOME_MISMATCH`, `ERR_CREDIT_HOURS_INSUFFICIENT`, `ERR_GRADUATION_REQUIREMENTS_UNMET`, `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED`, and `ERR_TESTING_REQUIREMENT_UNMET`.
11. Referential prerequisites: activation's demands for an acknowledged notice and an approved plan, `ERR_NOTICE_NOT_ACKNOWLEDGED` and `ERR_PLAN_NOT_APPROVED`.
12. Fiscal gates, always last: `ERR_FEES_OVERDUE` and `ERR_FEES_UNSETTLED`.

Two consequences worth internalizing: a malformed body surfaces `ERR_INVALID_REQUEST` before any state question is examined, and an overdue family balance can never mask an earlier failure — a stale-version rejection or a state conflict always reports first.

### 2.9. Instructional Time, Scheduling Conventions, and Numeric Precision

Times of day are expressed throughout the API as integer minutes after midnight. A start time ranges from 0 to 1439 inclusive; an end time must be strictly after its start and at most 1440. Meeting and sitting windows are half-open intervals — a window occupies its start instant up to but not including its end instant — so two windows on the same weekday that merely touch, one ending exactly when the other begins, do not conflict; genuine intersection is required for `ERR_COOP_SCHEDULE_OVERLAP`. Standardized testing imposes a stricter separation: two same-date sittings for one student must keep a buffer of at least thirty minutes between their windows, and a gap of exactly thirty minutes is permitted.

Instructional recordkeeping uses two integer constants. A calendar day qualifies as an instructional day once its recorded total reaches 240 minutes (four hours), and no single day ever contributes more than 600 minutes (ten hours) of credited time, however much was logged. Progress counters are exact integers — days and minutes, with no rounding of any kind.

Monetary amounts are integer cents. Fees are rounded per enrollment line using round-half-up to whole cents, and the family ledger is always the sum of those individually rounded lines — the family total itself is never rounded as a whole. Credit values are exact to one decimal place. The official GPA is rounded half-up to two decimal places.

### 2.10. The Compliance Standing Dimension

Every enrollment carries two independent state dimensions. Its `enrollment_status` tracks the student's lifecycle — `REGISTERED`, `ACTIVE`, `COMPLETED`, `WITHDRAWN`, `GRADUATED` — while its `compliance_standing` tracks regulatory posture: `GOOD_STANDING`, `PROBATION`, or `NONCOMPLIANT`, beginning at `GOOD_STANDING`. The two evolve independently: a student can be `ACTIVE` and simultaneously on `PROBATION`.

Standing is recomputed absolutely by the end-of-year compliance sweep (§3.9), which can lower or restore standing, and it can also be forced by discrete events — a finally rejected portfolio, a no-showed required test — each of which drives the enrollment to `NONCOMPLIANT`. Entering `NONCOMPLIANT` is never silent: it fires the co-op cascade described in §3.7, dropping the student's confirmed co-op seats with full refunds. While a director override is in effect the enrollment's `standing_locked` flag is true and the sweep leaves the enrollment untouched. Several business gates consult standing directly — co-op registration, exam registration, and graduation approval all refuse a `NONCOMPLIANT` enrollment with `ERR_ENROLLMENT_NONCOMPLIANT`.

### 2.11. Hierarchical Consistency and Cascading Resolution

The resource hierarchy is kept coherent by automatic cascades rather than by client choreography. When an enrollment is withdrawn, every artifact hanging beneath it — its notice of intent, curriculum plan, portfolio, test registrations, and co-op enrollments — is resolved in the same act (§3.2). When a co-op class is cancelled, its rosters are dropped or cancelled and every affected family ledger is credited without further calls (§3.7). When a diploma is issued, the student's transcript seals and the final-year enrollment graduates as one transaction (§3.8). When the state accepts a compliance report, the academic year itself advances to `REPORTED` (§3.9). Each resource touched by a cascade is independently mutated: its `updated_at` refreshes and its `version` increments per §2.5. Wherever a seat is released — by drop, withdrawal, cancellation, or standing action — the waitlist machinery of §3.7 runs against the freed class before the cascade is considered complete.

## 3. Business Logic & Workflows

### 3.1. The Academic Year and the School Calendar

Every school year begins on the desk of an `AcademicDirector`, who creates the academic year by supplying a `label` (a human-readable tag such as 2026-2027, unique across all years), the instructional window `start_date` and `end_date` (both ISO calendar dates, the end on or after the start), and the year's four statutory instants: `notice_filing_deadline` for notices of intent, `portfolio_due_date` as the portfolio soft deadline, `state_report_due_date` for the annual compliance report, and `mid_year_date` for the mid-year progress checkpoint. Four policy parameters may be overridden at creation: `testing_grades`, the grade levels (0 for kindergarten through 12) in which standardized testing is mandatory, defaulting to grades 3, 5, 8, and 11; `required_instructional_days`, defaulting to 180; `required_minutes_elementary`, the certified minutes required of grades K–5, defaulting to 54,000 (nine hundred hours); and `required_minutes_secondary`, the certified minutes required of grades 6–12, defaulting to 59,400 (nine hundred ninety hours).

A new year is `PLANNING`. Opening it — the transition from `PLANNING` to `OPEN` — is permitted only while the logical clock still reads before the year's `end_date`; an attempt to open a year whose final instructional date has already passed is refused with `ERR_ACADEMIC_YEAR_NOT_OPEN`. Closing the year, `OPEN` → `CLOSED`, requires the opposite: the logical clock must read at or past `end_date`, else the transition is rejected with `ERR_INVALID_STATE_TRANSITION`. Closing changes no enrollment states by itself — the compliance sweep performs the standing recompute. The year reaches its terminal state `REPORTED` only when the state auditor accepts the year's compliance report (§3.9).

The year acts as the roster root: its enrollment listing can be filtered by `enrollment_status` and `compliance_standing`, while its exam-session and co-op-class listings accept a `status` filter, and its compliance-report listing is always unfiltered beyond pagination.

### 3.2. Family Onboarding, Students, and Enrollment

A family enters the system by self-registration: a `Parent` caller creates the family account with a `display_name` and the `district_code` of the family's district of residence. The `id` of the newly created family becomes that parent's `X-User-ID` for every subsequent call. The family's fee ledger starts clean — `fee_balance_cents` at zero, `fee_status` at `CURRENT`, and `oldest_unpaid_charge_at` null. Reading a family back, listing its students, or reading its ledger is available to staff roles, while a parent may do so only for their own family `id`.

The parent then adds each student with a `full_name` and `date_of_birth`. A student record is born unsealed: `transcript_sealed` is false, `sealed_at` is null, and `diploma_number` is null until a diploma is issued.

Enrolling a student into an academic year takes a payload containing the `academic_year_id` and the `grade_level` — 0 for kindergarten through 12, immutable once the enrollment exists. The new enrollment opens with `enrollment_status` `REGISTERED`, `compliance_standing` `GOOD_STANDING`, `standing_locked` false, and all four progress counters — `provisional_days_counted`, `provisional_minutes_credited`, `certified_days_counted`, `certified_minutes_credited` — at zero. Whether the student must sit a standardized test is decided at this moment: `testing_required` is true exactly when the chosen `grade_level` is a member of the year's `testing_grades`, and `testing_satisfied` begins false. A student's enrollment history can be listed and narrowed by `academic_year_id`.

Activation — `REGISTERED` → `ACTIVE`, performed by a `Registrar` — is the year's first compliance checkpoint, and it enforces three prerequisites: the academic year must be `OPEN` (else `ERR_ACADEMIC_YEAR_NOT_OPEN`); a notice of intent for the enrollment must stand `ACKNOWLEDGED` (else `ERR_NOTICE_NOT_ACKNOWLEDGED`); and the enrollment's curriculum plan must be `APPROVED` (else `ERR_PLAN_NOT_APPROVED`). A successful activation stamps `activated_at` and increments the enrollment's `version`.

Withdrawal unwinds everything. A `Parent` of the owning family, or a `Registrar`, may withdraw an enrollment in `REGISTERED` or `ACTIVE`, optionally attaching a `reason`; the enrollment lands in the terminal state `WITHDRAWN` with `withdrawn_at` stamped and its `version` incremented. The same act cascades downward: any notice of intent in `DRAFT`, `FILED`, `ACKNOWLEDGED`, or `RETURNED` moves to `WITHDRAWN`; the curriculum plan, whatever its non-archived state, moves to `ARCHIVED`; a portfolio in `DRAFT`, `SUBMITTED`, or `REMEDIATION_REQUIRED` moves to `WITHDRAWN`; every test registration still `REGISTERED` is `CANCELLED` and its exam session's `seats_taken` is decremented; and every confirmed co-op enrollment is dropped as `PARENT_INITIATED` — running the refund waterfall of §3.7 and releasing seats that may trigger waitlist promotions — while every waitlisted co-op enrollment is simply `CANCELLED`. The other terminal enrollment state, `GRADUATED`, is reached only through diploma issuance (§3.8).

### 3.3. Notices of Intent and Curriculum Plan Approval

State law begins with the notice of intent. A `Parent` creates the enrollment's notice with the `district_code` it will be filed under; only one open notice may exist per enrollment — a notice standing in `DRAFT`, `FILED`, or `RETURNED` blocks the creation of another with `ERR_NOTICE_ALREADY_OPEN`. The notice begins as `DRAFT`. Filing it with the state, a parent action, moves it to `FILED` and stamps `filed_at`. From there the `Registrar` either acknowledges it — `FILED` → `ACKNOWLEDGED`, stamping `acknowledged_at` — or returns it, `FILED` → `RETURNED`, recording the supplied `returned_reason`. A returned notice is not the end: the parent refiles it, moving `RETURNED` → `FILED`, which refreshes `filed_at`, clears `returned_reason` to null, and increments `refile_count`; each filing also increments the notice's `version`. Withdrawal of the enrollment drags any notice in `DRAFT`, `FILED`, `ACKNOWLEDGED`, or `RETURNED` into the terminal state `WITHDRAWN`.

In parallel, the family assembles the curriculum plan. Exactly one plan may exist per enrollment — a second attempt is refused with `ERR_PLAN_ALREADY_EXISTS` — and it is created as `DRAFT` from the parent's proposed `subjects` list. Submission, a parent action, requires the plan to cover all five core subjects — `READING`, `WRITING`, `MATH`, `SCIENCE`, and `SOCIAL_STUDIES` — and a submission missing any of them fails with `ERR_PLAN_MISSING_CORE_SUBJECT`; success moves `DRAFT` → `SUBMITTED`. A `Reviewer` then decides the plan's fate with a `decision` of `APPROVE` or `REQUEST_REVISION` and optional `notes`: approval moves `SUBMITTED` → `APPROVED`, a revision request moves `SUBMITTED` → `REVISION_REQUESTED`, and either way the reviewer is recorded as `reviewer_id` and the notes stored as `review_notes`. No one may review their own child's plan — a reviewer whose `X-User-ID` equals the enrollment's family id is rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`. The family resubmits a revised plan (`REVISION_REQUESTED` → `SUBMITTED`), which increments `revision_count`, and the review cycle repeats. Submitting, reviewing, and amending each increment the plan's `version`.

Plans sometimes change mid-year. The parent may amend an `APPROVED` plan, replacing its `subjects` wholesale; the request must carry `expected_curriculum_plan_version` matching the plan's current `version` — the optimistic-concurrency contract of §2.7, with `ERR_STALE_VERSION` on mismatch — and the amended subject list must again include all five core subjects, else `ERR_PLAN_MISSING_CORE_SUBJECT`. A valid amendment moves the plan to `AMENDMENT_REVIEW` with the new subjects in place. A reviewer then brings it back: `AMENDMENT_REVIEW` → `APPROVED` on approval or `AMENDMENT_REVIEW` → `REVISION_REQUESTED` on a revision request, recording `reviewer_id` either way, after which the resubmission cycle applies as before. When the enrollment is withdrawn, a plan in any state other than `ARCHIVED` is moved to the terminal state `ARCHIVED`.

### 3.4. Attendance Recordkeeping and Instructional Progress

Day-by-day instruction is the raw evidence of the year. A `Parent` logs an instructional day for an `ACTIVE` enrollment — attempts against an enrollment in any other status fail with `ERR_ENROLLMENT_NOT_ACTIVE` — by supplying the `entry_date` and the day's `minutes`, between 1 and 720. The date must fall within the academic year's `start_date` and `end_date` inclusive and must not lie in the future of the logical clock, else the entry is refused with `ERR_ATTENDANCE_DATE_OUT_OF_RANGE`. At most one non-voided entry may exist for an enrollment on a given date; a duplicate is rejected with `ERR_ATTENDANCE_DUPLICATE_DATE`. New entries are `RECORDED`.

Corrections and verification follow a graded trust model. While an entry is `RECORDED`, the parent may correct its `minutes`; once it has left that state, corrections are locked and fail with `ERR_ATTENDANCE_ENTRY_LOCKED`. A `Reviewer` verifies a recorded entry — `RECORDED` → `VERIFIED` — and is remembered as `verified_by`. Voiding is shared: the parent may void a `RECORDED` entry, while only a `Registrar` may void a `VERIFIED` one — a parent's attempt to void a verified entry meets `ERR_ATTENDANCE_ENTRY_LOCKED`. `VOIDED` is terminal, and voided rows vanish from every progress computation.

Every attendance mutation — creation, minutes correction, verification, voiding — recomputes instructional progress on the parent enrollment, in two parallel variants. Entries that are not `VOIDED` are grouped by `entry_date`; each date's logged minutes are summed; a date counts as a qualifying day when its total reaches 240 minutes; and each date contributes its total capped at 600 minutes to the credited-minutes sum. The **provisional** variant draws from both `RECORDED` and `VERIFIED` entries and lands on `provisional_days_counted` and `provisional_minutes_credited`; it powers the mid-year probation check of §3.9. The **certified** variant draws from `VERIFIED` entries only and lands on `certified_days_counted` and `certified_minutes_credited`; it powers the year-end noncompliance findings. Identical raw logs therefore yield smaller certified totals whenever any entry remains unverified — verification is what converts provisional evidence into certified evidence.

### 3.5. Portfolio Submission and Reviewer Evaluation

Each enrollment accumulates exactly one portfolio — creating a second is refused with `ERR_PORTFOLIO_ALREADY_EXISTS` — opened as `DRAFT` with `attempt_count` at zero. Submission is a parent action with two guards: the enrollment must be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`), and the logical clock must read no later than the end of the year's final instructional day — submission after that date is refused with `ERR_PORTFOLIO_WINDOW_CLOSED`. The first submission moves `DRAFT` → `SUBMITTED` and sets `attempt_count` to 1; a resubmission after remediation moves `REMEDIATION_REQUIRED` → `SUBMITTED` and increments `attempt_count`. Either way `submitted_at` is refreshed and the portfolio's `version` increments.

Evaluation belongs to the `Reviewer`, who records an `overall_outcome` of `ACCEPTED`, `REMEDIATION_REQUIRED`, or `REJECTED`, a `subject_scores` array carrying one `{ subject, score }` pair for each of the five core subjects with integer scores from 0 to 4, and optional `notes`. The conflict-of-interest rule applies here as to plans: a reviewer who is the student's own parent is rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`. Every evaluation is written as an immutable row tied to the portfolio via `portfolio_id`, capturing the acting `reviewer_id` and an `attempt_number` equal to the portfolio's `attempt_count` at the moment of evaluation; evaluation rows carry only `id` and `created_at`, with no `updated_at` or `version`.

The outcome drives the portfolio's state. `ACCEPTED` is lawful only when every subject score is at least 2 — a mismatch is rejected with `ERR_EVALUATION_SCORE_OUTCOME_MISMATCH` — and lands the portfolio in `ACCEPTED` with `decided_at` stamped. `REMEDIATION_REQUIRED` is available only while the portfolio has seen fewer than three attempts and returns it to `REMEDIATION_REQUIRED` for another cycle. `REJECTED` lands the portfolio in `REJECTED` with `decided_at` stamped — and the same fate befalls a portfolio whose reviewer requests remediation on its third attempt: remediation at `attempt_count` 3 is a forced rejection. Both `ACCEPTED` and `REJECTED` are terminal.

Rejection is never a private event. A finally or forcibly rejected portfolio drives the enrollment's `compliance_standing` to `NONCOMPLIANT`, firing the standing cascade of §3.7 — confirmed co-op enrollments dropped with full `SCHOOL_STANDING` refunds, waitlisted ones cancelled, freed seats offered to the waitlist. If the enrollment is withdrawn instead, a portfolio still in `DRAFT`, `SUBMITTED`, or `REMEDIATION_REQUIRED` moves to the terminal state `WITHDRAWN`.

### 3.6. Standardized Testing: Sessions, Registration, and Scoring

Whether a given enrollment must test is settled at enrollment creation (§3.2): `testing_required` holds when the grade is a member of the year's `testing_grades`. Satisfaction is earned, not assumed: `testing_satisfied` flips true once the enrollment has a registration that reached `SCORED` with `passed` true, or one that was `EXCUSED`.

The `Registrar` builds the testing calendar by creating exam sessions for a year, each with a `test_name` (IOWA, STANFORD10, and the like), a `session_date`, a sitting window `start_minutes` to `end_minutes` in minutes after midnight (the end strictly after the start and at most 1440), a `capacity` of at least 1, a `registration_deadline`, the `target_grades` allowed to register, and an optional `location` label. A session is born `SCHEDULED` with `seats_taken` at zero. Opening registration — `SCHEDULED` → `REGISTRATION_OPEN` — requires the year to be `OPEN`, else `ERR_ACADEMIC_YEAR_NOT_OPEN`. The registrar later closes registration (`REGISTRATION_OPEN` → `REGISTRATION_CLOSED`) and, after the sitting, marks it administered (`REGISTRATION_CLOSED` → `ADMINISTERED`, the terminal state).

A `Parent` registers an enrollment for a session with a payload containing the `enrollment_id`. Five gates apply: the session must be `REGISTRATION_OPEN` (else `ERR_EXAM_SESSION_NOT_OPEN`); the logical clock must read at or before the session's `registration_deadline` (else `ERR_EXAM_REGISTRATION_DEADLINE_PASSED`); the enrollment's `grade_level` must be a member of `target_grades` (else `ERR_EXAM_GRADE_MISMATCH`); the enrollment must not be `NONCOMPLIANT` (else `ERR_ENROLLMENT_NONCOMPLIANT`); and the session must have a free seat — `seats_taken` counts registrations in `REGISTERED`, `ATTENDED`, `NO_SHOW`, `EXCUSED`, or `SCORED`, and when it has reached `capacity` the registration fails with `ERR_EXAM_SESSION_FULL`, there being no waitlist for exams. A sixth check protects the student's own day: the new sitting must keep a thirty-minute buffer against every other session of the same student on the same date holding a registration in `REGISTERED`, `ATTENDED`, or `SCORED` — a gap under thirty minutes conflicts as `ERR_EXAM_SCHEDULE_CONFLICT`, while exactly thirty minutes is allowed. A successful registration is `REGISTERED`, is linked to its sitting through the recorded `exam_session_id`, increments the session's `seats_taken` by one, and increments the session's `version`.

Plans change: the parent, or the registrar, may cancel a registration while its session is still `SCHEDULED`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`, moving it to the terminal state `CANCELLED` and decrementing the session's `seats_taken` by one.

Once the session is `ADMINISTERED` — attendance recording against a session in any other state fails with `ERR_EXAM_SESSION_NOT_OPEN` — the registrar records each registration's `attendance_outcome`. `ATTENDED` moves the registration to `ATTENDED` and awaits a score. `EXCUSED` requires an `exemption_note` (omitting it is `ERR_INVALID_REQUEST`) and moves the registration to the terminal state `EXCUSED`, which itself satisfies the testing requirement and triggers a recompute of `testing_satisfied`. `NO_SHOW` is terminal and, when the enrollment's `testing_required` is true, drives the enrollment's standing to `NONCOMPLIANT` with the full co-op cascade of §3.7.

Scoring completes the cycle: the registrar records the `composite_percentile`, an integer from 1 to 99 (anything else is `ERR_INVALID_REQUEST`), moving `ATTENDED` → `SCORED`. A percentile of at least 23 passes — 22 fails, 23 passes — and the result is stored on `passed`; `testing_satisfied` is then recomputed, a passing score satisfying the requirement.

### 3.7. Co-op Classes, Fees, and the Family Ledger

The co-op program is where the school becomes a marketplace, and where the family ledger lives. A `Registrar` defines a class for the year with a `title`, a free-text `subject` label, an eligible grade band `grade_min` to `grade_max` (each 0 to 12, the maximum at least the minimum), a weekly meeting described by `meeting_day` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`) and the window `meeting_start_minutes` to `meeting_end_minutes` (end strictly after start, at most 1440), the session span `start_date` to `end_date` (end on or after start), a `capacity` of at least 1, and two price components: the discountable `fee_base_cents` and the non-discountable `materials_fee_cents`, each at least zero. The class is born `DRAFT` with `seats_taken` at zero, where `seats_taken` counts co-op enrollments in `CONFIRMED` or `COMPLETED`.

Opening the class — `DRAFT` → `OPEN` — requires the year to be `OPEN`, else `ERR_ACADEMIC_YEAR_NOT_OPEN`, and increments the class's `version`. From there the calendar takes over: the compliance sweep advances an `OPEN` class to `IN_SESSION` once its start date arrives, and an `IN_SESSION` class to the terminal state `COMPLETED` once its end date has passed, moving every still-`CONFIRMED` enrollment to `COMPLETED` with it. A registrar may instead cancel a class from `OPEN` or `IN_SESSION`; cancellation drops every `CONFIRMED` enrollment with `drop_reason` `SCHOOL_CANCEL` and a full refund — `refund_cents` equal to the entire `fee_cents`, no administrative fee, materials included — crediting each family ledger, cancels every `WAITLISTED` enrollment (which was never charged), recomputes `seats_taken` to zero, and increments the class's `version`.

Registration is a parent action whose payload carries the `enrollment_id` and the OCC field `expected_coop_class_version`; per §2.7, a value that no longer matches the class's current `version` is rejected with `ERR_STALE_VERSION`, because the confirmed-versus-waitlisted outcome depends on the live seat count. Registration then passes through its gates: the class must be `OPEN` (else `ERR_COOP_CLASS_NOT_OPEN`); the enrollment's `grade_level` must fall within the class's grade band (else `ERR_COOP_GRADE_INELIGIBLE`); the weekly meeting window must not intersect, on the same `meeting_day`, the window of any other class in which the student holds a `CONFIRMED` enrollment — windows are half-open, so touching endpoints are allowed — else `ERR_COOP_SCHEDULE_OVERLAP`; a `NONCOMPLIANT` enrollment is refused with `ERR_ENROLLMENT_NONCOMPLIANT`; and a family whose `fee_status` is `OVERDUE` may not take on new charges, refused with `ERR_FEES_OVERDUE`. The new co-op enrollment lands `CONFIRMED` when the class still has a free seat, otherwise `WAITLISTED`, and the roster link back to the class is recorded as `coop_class_id`.

Fees are computed per enrollment line at the moment of confirmation. An early-bird discount of ten percent applies when the co-op enrollment was created at least thirty days before the class's first session date. A sibling discount of fifteen percent applies when another co-op enrollment, belonging to an enrollment of the same family in the same academic year, already stands `CONFIRMED` or `COMPLETED` and was created before this one — the comparison is made on creation timestamps and never consults entity identifiers; records stamped at the same instant are ordered by the sequence in which the server persisted them, and any record already persisted when the fee is computed counts as created before the line being priced. The two discounts add, capped at a combined twenty-five percent, and the result is recorded as `discount_pct_applied`. The charged `fee_cents` is the base fee scaled by the undiscounted remainder, rounded half-up to whole cents, plus the full `materials_fee_cents`; per §2.9 each line is rounded individually and the family ledger sums rounded lines. A `WAITLISTED` line carries a `fee_cents` of zero until promoted.

Confirmation moves money: the family's `fee_balance_cents` is debited by the line's `fee_cents`, the class's `seats_taken` increments, and the class's `version` increments. A positive balance represents money owed to the school, a negative one a family credit. Whenever the balance moves from exactly zero to positive, `oldest_unpaid_charge_at` is stamped with that instant; whenever a refund or payment returns the balance to exactly zero, `oldest_unpaid_charge_at` clears to null. The family's `fee_status` is `OVERDUE` when a positive balance has aged more than thirty days past `oldest_unpaid_charge_at`, and `CURRENT` otherwise. Families settle up through ledger payments — a parent paying against their own family, or a registrar recording one — with an `amount_cents` that subtracts from the balance, clears `oldest_unpaid_charge_at` if the balance lands exactly on zero, recomputes `fee_status`, and increments the family's `version`. The ledger read exposes `fee_balance_cents`, `fee_status`, and `oldest_unpaid_charge_at`.

A parent may drop a confirmed seat; the enrollment moves `CONFIRMED` → `DROPPED` with `drop_reason` `PARENT_INITIATED`, and the refund waterfall determines `refund_cents`: dropping before the class's start date refunds the line total minus a 2,500-cent administrative fee, floored at zero; dropping within fourteen days after the start date refunds half of the line total above the materials fee, rounded half-up; dropping later refunds nothing. By contrast, school-initiated losses — a class cancellation (`SCHOOL_CANCEL`) or a standing-driven drop (`SCHOOL_STANDING`) — always refund the full `fee_cents`, materials included, with no administrative fee. Any drop credits the family ledger by `refund_cents`, decrements `seats_taken` by one, increments the class's `version`, and runs waitlist promotion against the freed seat.

Waitlist promotion is deterministic. Candidates are the class's `WAITLISTED` enrollments whose underlying enrollment is still `ACTIVE`, whose standing is not `NONCOMPLIANT`, whose grade falls within the class's band, and whose weekly window does not overlap the student's other `CONFIRMED` classes. They are ranked by the co-op enrollment's own creation time, earliest first, with ties broken by the candidate enrollment's creation time, earliest first — identifiers are never consulted. Exactly one candidate is promoted per freed seat, and the selection re-runs after each promotion while seats remain; an empty candidate set is a no-op. Promotion stamps `promoted_at`, computes the fee using the co-op enrollment's original creation time for early-bird eligibility, debits the family ledger, and increments the class's `seats_taken` and `version`.

Finally, the standing cascade ties this section to §2.10: when an enrollment's `compliance_standing` becomes `NONCOMPLIANT` — by sweep, by forced portfolio rejection, by a no-showed required test, or by director override — every one of its `CONFIRMED` co-op enrollments is dropped with `drop_reason` `SCHOOL_STANDING` at a full refund, every `WAITLISTED` one is `CANCELLED`, and each freed seat triggers promotion on its class.

### 3.8. Course Credits, the Transcript, and Graduation

High-school families build the transcript one course at a time. A `Parent` plans a course credit with a `subject` — one of `ENGLISH`, `MATH`, `SCIENCE`, `SOCIAL_STUDIES`, `FOREIGN_LANGUAGE`, `FINE_ARTS`, `PHYS_ED`, or `ELECTIVE` — a free-text `course_title`, `planned_hours` of at least 1, and an optional `is_lab` flag defaulting to false. The credit begins `PLANNED`.

Completion is the parent's declaration that the work happened: the request carries `completed_hours` and a `letter_grade` of `A`, `B`, `C`, `D`, or `F`. Completion requires at least 60 reported hours — 59 is refused with `ERR_CREDIT_HOURS_INSUFFICIENT` — and an enrollment in `ACTIVE` or `COMPLETED` status (else `ERR_ENROLLMENT_NOT_ACTIVE`). The earned `credit_value` is the number of whole sixty-hour blocks in the reported hours, multiplied by one-half credit, with no cap: 60 hours earns 0.5 credits, 119 hours still 0.5, 120 hours earns 1.0, and 240 hours earns 2.0. The credit lands `COMPLETED`.

The registrar then verifies: a `decision` of `APPROVE` moves `COMPLETED` → `VERIFIED`, while `REJECT` moves it to the terminal state `REJECTED`; optional `notes` may accompany the decision. Posting — `VERIFIED` → `POSTED` — writes the credit to the transcript, stamps `posted_at`, and recomputes the transcript's derived values; it is possible only while the student's transcript remains unsealed, a sealed transcript refusing with `ERR_TRANSCRIPT_SEALED`. A posted credit can still be revoked — `POSTED` → `REVOKED`, terminal — with the supplied `reason` stored as `revoked_reason`; revocation is likewise blocked by a sealed transcript with `ERR_TRANSCRIPT_SEALED`, and revoked credits are excluded from every transcript derivation, which is recomputed on the spot.

The transcript read is a computed view, not a stored document. It reports `official_credits_total`, the sum over the student's `POSTED` credits across all enrollments; `projected_credits_total`, the same sum over `POSTED`, `VERIFIED`, and `COMPLETED` credits; `subject_credits_official`, the per-subject official bucket totals; and `gpa_official`, the grade-point average over `POSTED` credits — `A` worth 4 points, `B` 3, `C` 2, `D` 1, `F` 0 — computed as the sum of each credit's points times its `credit_value`, divided by the sum of those credit values, rounded half-up to two decimal places, and null when no posted credits exist. The view also surfaces the student's `transcript_sealed` flag and `diploma_number`.

Graduation begins when the parent applies for a student, naming the final year's `academic_year_id`; the application is born `SUBMITTED`, and a student may hold only one active application — a second attempt while one stands `SUBMITTED` or `APPROVED` fails with `ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS`. Staff can list applications filtered by `academic_year_id` or `student_id`.

Evaluation belongs to the `AcademicDirector`, who supplies a `decision` of `APPROVE` or `DENY` with optional `notes`. Denial simply lands the application in the terminal state `DENIED`. Approval runs the full criteria chain, in the pipeline order of §2.8 — duty gates first, fiscal gates last: the evaluating director must not be the reviewer who accepted the final-year portfolio — the `reviewer_id` of the latest `ACCEPTED` evaluation on that portfolio — else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; the final-year enrollment's standing must not be `NONCOMPLIANT`, else `ERR_ENROLLMENT_NONCOMPLIANT`; the official credit audit must pass — at least 22.0 total posted credits, with at least 4.0 in `ENGLISH` and at least 3.0 each in `MATH`, `SCIENCE`, and `SOCIAL_STUDIES`, each credit counting only toward its own subject bucket and never cross-allocated — else `ERR_GRADUATION_REQUIREMENTS_UNMET`; the final-year portfolio must stand `ACCEPTED`, else `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED`; the testing requirement must be either absent or satisfied, else `ERR_TESTING_REQUIREMENT_UNMET`; and the family's `fee_balance_cents` must be exactly zero, else `ERR_FEES_UNSETTLED`. Success lands the application `APPROVED`; either decision records the director as `evaluated_by` and the notes as `decision_notes`.

Diploma issuance is a deliberate second signature: a director issues the diploma for an `APPROVED` application, but the issuer must differ from the application's `evaluated_by`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Issuance moves the application to the terminal state `DIPLOMA_ISSUED` with `diploma_issued_at` stamped; assigns the student a `diploma_number` composed of the literal prefix `DIP-`, the start year of the graduating academic year, and a zero-padded three-digit sequence beginning at 001 in issuance order within that year; seals the transcript — `transcript_sealed` true, `sealed_at` stamped — which blocks any further credit posting or revocation; and moves the final-year enrollment, the one whose year matches the application's `academic_year_id`, from `ACTIVE` or `COMPLETED` to `GRADUATED`.

### 3.9. The Compliance Sweep, Standing Overrides, and State Reporting

The sweep is the year's great reconciliation, invoked by an `AcademicDirector` and safe to run repeatedly. On each run it recomputes the standing of every enrollment of the year whose `enrollment_status` is `REGISTERED`, `ACTIVE`, or `COMPLETED` and whose `standing_locked` is false — an absolute recompute from current data, so recovery is as possible as demotion — and it increments the academic year's own `version`.

The recompute weighs two classes of violation. **Hard violations**: the `notice_filing_deadline` has passed and no notice of the enrollment stands `ACKNOWLEDGED`; the year's `end_date` has passed and the enrollment's `testing_required` is true while `testing_satisfied` remains false; the year's `end_date` has passed and either `certified_days_counted` falls short of `required_instructional_days` or `certified_minutes_credited` falls short of the applicable minute floor — `required_minutes_elementary` for grades K–5, `required_minutes_secondary` for grades 6–12; or a portfolio of the enrollment stands `REJECTED`. **Soft violations**: the `portfolio_due_date` has passed but the year has not yet ended and no portfolio of the enrollment stands `ACCEPTED`; or the `mid_year_date` has passed but the year has not yet ended and doubling `provisional_days_counted` still falls short of `required_instructional_days` — the mid-year pace check. Any hard violation drives the enrollment to `NONCOMPLIANT`; otherwise any soft violation yields `PROBATION`; otherwise the enrollment rests at `GOOD_STANDING` — including enrollments recovering from `NONCOMPLIANT` once their hard violations clear but soft ones remain, or returning all the way to good standing. Locked enrollments are skipped entirely. Every entry into `NONCOMPLIANT`, from any prior standing, fires the co-op cascade of §3.7.

The sweep also settles the year's lifecycle bookkeeping. An `ACTIVE` enrollment whose recomputed standing is anything but `NONCOMPLIANT` — probationary students included — moves to `COMPLETED` once the clock has passed the year's `end_date`. Co-op classes advance by date: `OPEN` to `IN_SESSION` when the start date arrives, `IN_SESSION` to `COMPLETED` after the end date, completing their confirmed rosters.

Directors can overrule the machinery. A standing override carries the target `standing` and a `reason`; it sets the enrollment's `compliance_standing` to the target — any of `GOOD_STANDING`, `PROBATION`, or `NONCOMPLIANT`, from any current standing — sets `standing_locked` true so future sweeps leave it alone, fires the co-op cascade when the target is `NONCOMPLIANT`, and increments the enrollment's `version`. Clearing the override unlocks the enrollment, immediately recomputes its standing from current data by the same derivation, and increments `version` again.

What remains is the report to the state. Once the year stands `CLOSED` — generation against a year in any other state fails with `ERR_REPORT_YEAR_NOT_CLOSED` — the director generates the year's compliance report, of which at most one may be open at a time: an existing report in `DRAFT`, `SUBMITTED`, or `REJECTED` blocks generation with `ERR_REPORT_ALREADY_OPEN`. Generation snapshots the year at the `generated_at` instant: `total_enrollments` counts the year's enrollments not `WITHDRAWN` at that moment, `compliant_count` those among them in `GOOD_STANDING`, and `noncompliant_enrollment_ids` lists the identifiers of the rest, ordered by each enrollment's creation time, earliest first — ties on an identical creation timestamp broken by the order in which the server created the enrollments, never by identifier. The report opens as `DRAFT`.

Submission, a director action, moves `DRAFT` → `SUBMITTED` — or, after a state rejection, `REJECTED` → `SUBMITTED` — stamping `submitted_at` and computing the `late` flag: submission after the year's `state_report_due_date` is late, while submission exactly at that instant is not. A resubmission recomputes both the lateness flag and the entire snapshot from current enrollment state. Adjudication then belongs to the `StateAuditor`: acceptance moves `SUBMITTED` → `ACCEPTED` — terminal — and carries the academic year itself to `REPORTED`; rejection moves `SUBMITTED` → `REJECTED` and stores the supplied `reason` as `rejection_reason`, opening the way for a corrected resubmission.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone resource or a new member of a collection — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. Where the Authorized Role(s) column reads "All roles", every API-facing role (`Parent`, `Reviewer`, `Registrar`, `AcademicDirector`, `StateAuditor`) may call the endpoint; otherwise the admitted roles are listed exactly. Request payloads, preconditions, and side effects for each operation are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/academic-years` | Create an academic year (status `PLANNING`) | AcademicDirector |
| GET | `/academic-years/{id}` | Get one academic year | All roles |
| POST | `/academic-years/{id}/open` | Open the year (`PLANNING` → `OPEN`) | AcademicDirector |
| POST | `/academic-years/{id}/close` | Close the year (`OPEN` → `CLOSED`) | AcademicDirector |
| POST | `/academic-years/{id}/run-compliance-sweep` | Run the compliance sweep for the year | AcademicDirector |
| GET | `/academic-years/{id}/enrollments` | List enrollments of a year | Reviewer, Registrar, AcademicDirector, StateAuditor |
| GET | `/academic-years/{id}/exam-sessions` | List exam sessions of a year | All roles |
| GET | `/academic-years/{id}/coop-classes` | List co-op classes of a year | All roles |
| GET | `/academic-years/{id}/compliance-reports` | List compliance reports of a year | Registrar, AcademicDirector, StateAuditor |
| POST | `/families` | Self-register a family account | Parent |
| GET | `/families/{id}` | Get one family (parents limited to their own) | Parent, Registrar, AcademicDirector, StateAuditor |
| GET | `/families/{id}/students` | List students of a family | Parent, Registrar, AcademicDirector, StateAuditor |
| GET | `/families/{id}/ledger` | Read the family's computed fee ledger | Parent, Registrar, AcademicDirector, StateAuditor |
| POST | `/families/{id}/ledger-payments` | Record a fee payment against the ledger | Parent, Registrar |
| POST | `/families/{id}/students` | Add a student to a family | Parent |
| GET | `/students/{id}` | Get one student | All roles |
| GET | `/students/{id}/enrollments` | List enrollments of a student | All roles |
| GET | `/students/{id}/transcript` | Read the student's computed transcript | All roles |
| GET | `/students/{id}/graduation-applications` | List graduation applications of a student | Parent, Registrar, AcademicDirector, StateAuditor |
| POST | `/students/{id}/enrollments` | Enroll a student in an academic year | Parent |
| GET | `/enrollments/{id}` | Get one enrollment with computed progress fields | All roles |
| POST | `/enrollments/{id}/activate` | Activate an enrollment (`REGISTERED` → `ACTIVE`) | Registrar |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment with full cascade | Parent, Registrar |
| POST | `/enrollments/{id}/standing-overrides` | Director override of compliance standing | AcademicDirector |
| POST | `/enrollments/{id}/standing-overrides/clear` | Clear the standing override and recompute | AcademicDirector |
| GET | `/enrollments/{id}/notices` | List notices of intent of an enrollment | All roles |
| GET | `/enrollments/{id}/curriculum-plans` | List the enrollment's curriculum plans (0 or 1) | All roles |
| GET | `/enrollments/{id}/attendance-entries` | List attendance entries of an enrollment | All roles |
| GET | `/enrollments/{id}/portfolios` | List the enrollment's portfolios (0 or 1) | All roles |
| GET | `/enrollments/{id}/course-credits` | List course credits of an enrollment | All roles |
| GET | `/enrollments/{id}/test-registrations` | List test registrations of an enrollment | All roles |
| GET | `/enrollments/{id}/coop-enrollments` | List co-op enrollments of an enrollment | All roles |
| POST | `/enrollments/{id}/notices` | Create a notice of intent (`DRAFT`) | Parent |
| GET | `/notices/{id}` | Get one notice | All roles |
| POST | `/notices/{id}/file` | File (or refile) the notice with the state | Parent |
| POST | `/notices/{id}/acknowledge` | Acknowledge a filed notice | Registrar |
| POST | `/notices/{id}/return` | Return a filed notice with a reason | Registrar |
| POST | `/enrollments/{id}/curriculum-plans` | Create the enrollment's curriculum plan (`DRAFT`) | Parent |
| GET | `/curriculum-plans/{id}` | Get one curriculum plan | All roles |
| POST | `/curriculum-plans/{id}/submit` | Submit or resubmit a plan for review | Parent |
| POST | `/curriculum-plans/{id}/review` | Reviewer decision on a submitted or amended plan | Reviewer |
| POST | `/curriculum-plans/{id}/amend` | Amend an approved plan (optimistic concurrency) | Parent |
| POST | `/enrollments/{id}/attendance-entries` | Log one instructional day (`RECORDED`) | Parent |
| GET | `/attendance-entries/{id}` | Get one attendance entry | All roles |
| PATCH | `/attendance-entries/{id}` | Correct minutes on a `RECORDED` entry | Parent |
| POST | `/attendance-entries/{id}/verify` | Verify a recorded entry | Reviewer |
| POST | `/attendance-entries/{id}/void` | Void an entry (parent: `RECORDED`; registrar: also `VERIFIED`) | Parent, Registrar |
| POST | `/enrollments/{id}/portfolios` | Create the enrollment's portfolio (`DRAFT`) | Parent |
| GET | `/portfolios/{id}` | Get one portfolio | All roles |
| POST | `/portfolios/{id}/submit` | Submit or resubmit the portfolio | Parent |
| POST | `/portfolios/{id}/evaluations` | Record a reviewer evaluation of the portfolio | Reviewer |
| GET | `/portfolios/{id}/evaluations` | List evaluations of a portfolio | All roles |
| GET | `/evaluations/{id}` | Get one evaluation | All roles |
| POST | `/academic-years/{id}/exam-sessions` | Create an exam session (`SCHEDULED`) | Registrar |
| GET | `/exam-sessions/{id}` | Get one exam session | All roles |
| POST | `/exam-sessions/{id}/open-registration` | Open registration (`SCHEDULED` → `REGISTRATION_OPEN`) | Registrar |
| POST | `/exam-sessions/{id}/close-registration` | Close registration (`REGISTRATION_OPEN` → `REGISTRATION_CLOSED`) | Registrar |
| POST | `/exam-sessions/{id}/administer` | Mark the session administered | Registrar |
| GET | `/exam-sessions/{id}/registrations` | List registrations of a session | All roles |
| POST | `/exam-sessions/{id}/registrations` | Register an enrollment for the session | Parent |
| GET | `/test-registrations/{id}` | Get one test registration | All roles |
| POST | `/test-registrations/{id}/cancel` | Cancel a registration, freeing the seat | Parent, Registrar |
| POST | `/test-registrations/{id}/record-attendance` | Record `ATTENDED`, `NO_SHOW`, or `EXCUSED` | Registrar |
| POST | `/test-registrations/{id}/record-score` | Score an attended registration | Registrar |
| POST | `/enrollments/{id}/course-credits` | Plan a course credit (`PLANNED`) | Parent |
| GET | `/course-credits/{id}` | Get one course credit | All roles |
| POST | `/course-credits/{id}/complete` | Declare completion with hours and grade | Parent |
| POST | `/course-credits/{id}/verify` | Registrar verification of a completed credit | Registrar |
| POST | `/course-credits/{id}/post` | Post a verified credit to the transcript | Registrar |
| POST | `/course-credits/{id}/revoke` | Revoke a posted credit | Registrar |
| POST | `/academic-years/{id}/coop-classes` | Create a co-op class (`DRAFT`) | Registrar |
| GET | `/coop-classes/{id}` | Get one co-op class | All roles |
| POST | `/coop-classes/{id}/open` | Open the class (`DRAFT` → `OPEN`) | Registrar |
| POST | `/coop-classes/{id}/cancel` | Cancel the class with full-refund cascade | Registrar |
| GET | `/coop-classes/{id}/enrollments` | List co-op enrollments of a class | All roles |
| POST | `/coop-classes/{id}/enrollments` | Register an enrollment into the class (optimistic concurrency) | Parent |
| GET | `/coop-enrollments/{id}` | Get one co-op enrollment | All roles |
| POST | `/coop-enrollments/{id}/drop` | Drop a confirmed seat (refund waterfall) | Parent |
| POST | `/students/{id}/graduation-applications` | Apply for graduation for a final year | Parent |
| GET | `/graduation-applications/{id}` | Get one graduation application | Parent, Registrar, AcademicDirector, StateAuditor |
| GET | `/graduation-applications` | List graduation applications | Registrar, AcademicDirector, StateAuditor |
| POST | `/graduation-applications/{id}/evaluate` | Director decision on an application | AcademicDirector |
| POST | `/graduation-applications/{id}/issue-diploma` | Issue the diploma and seal the transcript | AcademicDirector |
| POST | `/academic-years/{id}/compliance-reports` | Generate the year's compliance report snapshot | AcademicDirector |
| GET | `/compliance-reports/{id}` | Get one compliance report | Registrar, AcademicDirector, StateAuditor |
| POST | `/compliance-reports/{id}/submit` | Submit (or resubmit) the report to the state | AcademicDirector |
| POST | `/compliance-reports/{id}/accept` | Accept the report (year becomes `REPORTED`) | StateAuditor |
| POST | `/compliance-reports/{id}/reject` | Reject the report with a reason | StateAuditor |
| POST | `/_clock/set_current_utc` | Advance the logical clock | AcademicDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACADEMIC_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ATTENDANCE_ENTRY_LOCKED` | 409 Conflict |
| `ERR_TRANSCRIPT_SEALED` | 409 Conflict |
| `ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_NOTICE_ALREADY_OPEN` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PORTFOLIO_ALREADY_EXISTS` | 409 Conflict |
| `ERR_REPORT_YEAR_NOT_CLOSED` | 409 Conflict |
| `ERR_REPORT_ALREADY_OPEN` | 409 Conflict |
| `ERR_NOTICE_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_REVIEWER_CONFLICT_OF_INTEREST` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_ATTENDANCE_DATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_PORTFOLIO_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_EXAM_REGISTRATION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_DUPLICATE_DATE` | 409 Conflict |
| `ERR_PLAN_MISSING_CORE_SUBJECT` | 422 Unprocessable Entity |
| `ERR_COOP_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_EXAM_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_EXAM_SESSION_FULL` | 422 Unprocessable Entity |
| `ERR_EXAM_SESSION_NOT_OPEN` | 409 Conflict |
| `ERR_COOP_CLASS_NOT_OPEN` | 409 Conflict |
| `ERR_COOP_GRADE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EXAM_GRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVALUATION_SCORE_OUTCOME_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOURS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_GRADUATION_REQUIREMENTS_UNMET` | 422 Unprocessable Entity |
| `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_TESTING_REQUIREMENT_UNMET` | 422 Unprocessable Entity |
| `ERR_FEES_OVERDUE` | 422 Unprocessable Entity |
| `ERR_FEES_UNSETTLED` | 422 Unprocessable Entity |
