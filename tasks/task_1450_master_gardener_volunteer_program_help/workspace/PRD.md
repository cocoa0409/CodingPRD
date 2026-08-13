# Master Gardener Program API — Product Requirements Document

## 1. Introduction

County extension Master Gardener programs run on volunteer labor, yet they are administered like compliance regimes: a class of applicants is selected each year, trainees must finish a course before they may serve, active volunteers owe annual service and continuing-education hours, and every credited hour must survive audit. This document specifies the Master Gardener Volunteer Program & Help Desk API, which supports that full annual operating loop — recruiting and selecting applicants, training them into volunteers, staffing help-desk and outreach shifts, logging the gardening questions those shifts field, referring difficult cases to subject-matter specialists, approving community projects, rotating volunteers through demonstration-garden beds, and adjudicating each volunteer's annual recertification.

The design is compliance-first. Every hour that counts toward recertification flows through an adjudicated credit ledger that keeps provisional and official totals side by side; recertification itself is a calendar-gated event that closes a program cycle and cascades consequences — deactivation, strike bookkeeping, recognition recalculation — across every related record. Because coordinators, volunteers, and specialists share one data store, the API also pins down an optimistic-concurrency protocol, a deterministic logical clock that drives every time-gated rule, and a fixed request-validation order so all clients observe identical behavior.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly three roles. A `ProgramCoordinator` is extension program staff and administers cycles, admissions, training, credit decisions, shifts, referral assignment, project review, garden rotation, and the logical clock. A `Volunteer` is a master gardener volunteer (or trainee) who logs their own hours, staffs shifts, logs and desk-answers inquiries, and proposes their own community projects. A `Specialist` is a subject-matter expert who receives plant and pest diagnosis referrals. An authenticated caller whose role is not listed for an endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a `Volunteer` compare the resource's foreign-key field to `X-User-ID` — the `volunteerId` path segment on self-service credit entries, a signup's `volunteer_id`, an inquiry's `volunteer_id`, and a project's `organizer_volunteer_id`. When `X-User-Role` is `Specialist`, `X-User-ID` is the `id` of the acting `Specialist`; ownership checks compare a referral's `specialist_id` to `X-User-ID`. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `approved_by_user_id` on a `CommunityProject` when a coordinator approves the project — but does not compare it to any entity's `id`. Any entity-backed identity mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a page contains: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope — `limit`, `offset`, `total_count`, and `has_more` — so clients can page deterministically through a full result set.

### 2.4. Common Resource Properties

All thirteen resource types — `ProgramCycle`, `Application`, `Volunteer`, `TrainingEnrollment`, `CreditEntry`, `RecertificationRecord`, `Shift`, `ShiftSignup`, `Inquiry`, `DiagnosisReferral`, `Specialist`, `CommunityProject`, and `RotationAssignment` — carry the same four system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation, including mutations driven by system cascades and recomputed derived fields.

This convention gives every resource a uniform audit trail and makes every mutation visible to optimistic concurrency control where that protocol applies (§2.8).

### 2.5. The Logical Clock

All time-gated rules in this system — recertification windows, shift signup and cancellation windows, shift completion, inquiry logging windows, rotation week boundaries, referral SLA deadlines, and rolling performance windows — read a single server-side logical clock, never the host wall clock. Before any client call, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance.

A `ProgramCoordinator`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`. Every rule below that phrases a condition as "the logical clock" is evaluated against this value at request time.

### 2.6. Cycle Posture as a Write Gate

A `ProgramCycle` moves through four states — `DRAFT`, `OPEN`, `RECERTIFICATION`, and terminal `CLOSED` — and the cycle's posture gates most writes in the system. Three posture rules apply globally. First, credit-entry writes (creation, approval, rejection, revocation), shift creation, community-project creation, and training enrollment creation, progress, and completion all require the target cycle to be `OPEN`; against any other posture they fail with `ERR_CYCLE_NOT_OPEN` (HTTP 409). Second, application creation, scoring, decision, and waitlist promotion require the cycle to be `DRAFT` or `OPEN`; against `RECERTIFICATION` or `CLOSED` they fail with `ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS` (HTTP 409). Third, cycle configuration edits are permitted only while the cycle is `DRAFT` or `OPEN`; attempted against `RECERTIFICATION` or `CLOSED` they fail with `ERR_CYCLE_NOT_EDITABLE` (HTTP 409).

### 2.7. Hours, Quarter-Hour Quantum, and Rounding

Hours are the currency of the program, and they are accounted on a strict quarter-hour quantum. Claimed `hours` on a credit entry must be a positive multiple of 0.25 and may not exceed 12.0 on a single entry. Cycle-level `hour_requirement` and `ce_requirement` are likewise multiples of 0.25 (the hour requirement must be positive; the continuing-education requirement may be zero). Computed hour totals and recognition figures are stored at two decimal places using round-half-up. Effective recertification requirements are rounded half-up to the nearest quarter-hour. Composite application scores are rounded half-up to one decimal place. Specialist performance scores are integers. Timestamps are compared at second precision on ISO 8601 UTC values, while garden-rotation weeks are compared at day granularity.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. A `PUT /program-cycles/{cycleId}` request, the cycle configuration edit, must carry `expected_cycle_version`, a non-optional field holding the cycle's `version` the client last observed; if another permitted update has advanced the cycle's version since then, the edit is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). A `PUT /projects/{projectId}` request, the project amendment, must likewise carry `expected_project_version`, and a mismatch with the project's current `version` — whether advanced by a prior accepted amendment or by a state transition such as submission — is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). A `PATCH /specialists/{specialistId}` request, the capacity or availability update, must carry `expected_specialist_version`, and a mismatch with the specialist's current `version` is rejected with `ERR_STALE_SPECIALIST_VERSION` (HTTP 412). In each case the client is prevented from overwriting a configuration base it has not observed. A successful guarded write increments the parent resource's `version` by exactly one. Endpoints not named here take no version field at all.

### 2.9. Request Validation Order and Nested Path Resolution

Every request is validated in a fixed sequence of tiers, and the first failing tier produces the response; later tiers are never consulted once an earlier tier fails. The sequence is: (1) identity headers are present and the role is declared — failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the caller's role is authorized for the endpoint — `ERR_FORBIDDEN`; (3) schema validation of required fields, types, enum membership, and static ranges — `ERR_INVALID_REQUEST` (HTTP 400) for missing fields, wrong types, invalid enum members, or malformed values, `ERR_INVALID_FIELD_VALUE` (HTTP 422) for static range and quantum violations, and `ERR_MISSING_KIND_FIELDS` (HTTP 422) for kind-dependent field failures; (4) existence — path identifiers and referenced body identifiers (`cycle_id`, `volunteer_id`, `source_id`, `specialist_id`, `follow_up_of_id`, `new_volunteer_id`) must resolve to existing resources — `ERR_NOT_FOUND` (HTTP 404); (5) entity-backed ownership — `ERR_NOT_RESOURCE_OWNER`; (6) optimistic-concurrency version match — the stale-version errors of §2.8; (7) parent cycle posture — the three errors of §2.6; (8) target-resource state — the family of transition-guard errors detailed per workflow in §3, where, when both the target resource's own state and a related resource's state fail at this tier, the target resource's own state error is returned first; (9) segregation of duties — `ERR_SEGREGATION_OF_DUTIES`; (10) uniqueness, capacity, and overlap conflicts — the duplicate, fullness, conflict, and limit error families; (11) clock and window rules — `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` at HTTP 422 and the remaining window errors at HTTP 409; and (12) cross-entity reference consistency — `ERR_SPECIALTY_MISMATCH`, `ERR_PROJECT_NOT_CREDITABLE`, `ERR_SHIFT_KIND_NOT_HELP_DESK`, `ERR_NO_SHIFT_SIGNUP`, and `ERR_FOLLOW_UP_TARGET_NOT_CLOSED`.

Where a request path nests one resource beneath another — signups and inquiries beneath shifts, credit entries beneath volunteers — identifiers resolve strictly left to right: the request is rejected with `ERR_NOT_FOUND` for the first identifier in the path that does not resolve, before any later identifier or body validation runs.

### 2.10. Cascading Consistency and Derived-Field Reconciliation

The system maintains immediate consistency: every side effect of an operation is visible in the same response and in all follow-up reads. Derived fields — a cycle's `accepted_count` and `enrolled_count`, a shift's `filled_count`, a specialist's `open_referral_count`, `answered_count`, `late_referral_count`, and `returned_count`, a record's provisional and official totals, and a volunteer's recognition fields — are recomputed on every triggering event rather than accumulated loosely, so a read always reflects the full event history. Cascades propagate automatically: closing a cycle finalizes records, flips volunteer statuses, cancels signups, voids entries, and drops enrollments in one run, and cancelling a shift releases its signups without further client action. Each such reconciliation is a mutation of the owning resource, refreshing its `updated_at` and incrementing its `version` per §2.4.

## 3. Business Logic & Workflows

### 3.1. The Program Year: Cycle Setup, Admissions, and the Waitlist

A `ProgramCoordinator` opens a new program year by creating a `ProgramCycle` with a human-readable `year_label` such as "2026", an inclusive `start_date` and `end_date` (the end date must fall on or after the start date), an `admission_capacity` of at least one, an `hour_requirement` that is a positive multiple of 0.25, a `ce_requirement` that is a multiple of 0.25 and may be zero, a `training_module_count` of at least one, a `training_pass_quiz_average` between 0 and 100, a `training_capacity` of at least one, and a `recert_opens_at` instant marking the earliest moment the recertification phase may begin. The coordinator may also supply `priority_counties`, a list of county names that earn an admissions bonus; it defaults to an empty list. A new cycle begins in `DRAFT` with `accepted_count` and `enrolled_count` at zero and `version` at 1. The cycle list may be filtered by `status`.

While the cycle remains `DRAFT` or `OPEN`, the coordinator may edit its configuration — `admission_capacity`, `hour_requirement`, `ce_requirement`, `training_capacity`, `recert_opens_at`, and `priority_counties` are the editable fields — under the optimistic-concurrency protocol of §2.8. Opening the cycle moves `DRAFT → OPEN` and is valid only from `DRAFT` (otherwise `ERR_INVALID_CYCLE_STATE`). Opening has a provisioning side effect: for every volunteer currently `ACTIVE` who has no recertification record for this cycle, a `PENDING` `RecertificationRecord` is created and its totals recomputed.

Later, beginning recertification moves `OPEN → RECERTIFICATION`. That transition requires the cycle to be `OPEN` (`ERR_INVALID_CYCLE_STATE` otherwise) and the logical clock to be at or past `recert_opens_at` (otherwise `ERR_RECERT_WINDOW_NOT_OPEN`). Once the cycle enters `RECERTIFICATION`, all credit-entry writes for that cycle — creation, approval, rejection, and revocation — freeze, and any further attempt fails with `ERR_CYCLE_NOT_OPEN`. Closing the cycle is described in §3.8.

Admissions run against `DRAFT` or `OPEN` cycles. A coordinator submits an `Application` carrying the target `cycle_id` plus the applicant's `applicant_name`, `email`, `county` of residence, and self-reported `prior_gardening_years` of experience (zero or more); the application begins in `SUBMITTED`. Scoring records the reviewer's `essay_score` and `interview_score`, each an integer from 0 to 100, and is permitted only while the application is `SUBMITTED` (otherwise `ERR_APPLICATION_NOT_SUBMITTED`) and the parent cycle is still `DRAFT` or `OPEN` (otherwise `ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS`). Scoring computes the `composite_score` — previously null — and moves the application `SUBMITTED → SCORED`. The application list may be filtered by `cycle_id` and `status`.

The composite score is computed in exactly this order. First the weighted component: the essay contributes forty percent of its score and the interview contributes sixty percent. Second, an experience bonus is added from `prior_gardening_years`: ten or more years earns eight points, five through nine years earns five points, two through four years earns three points, and fewer than two years earns nothing. Third, a county bonus of four points is added when the application's `county` appears in the cycle's `priority_counties`, and zero otherwise. The weighted total plus both bonuses is rounded half-up to one decimal place, and the `composite_score` is the lesser of one hundred and that rounded total — a hard cap, never exceeded.

Decisions are taken on `SCORED` applications via a `decision` of `ACCEPT`, `WAITLIST`, or `REJECT`. Like submission and scoring, decisions and waitlist promotion require the parent cycle to be `DRAFT` or `OPEN`, failing with `ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS` otherwise. Acceptance requires a free seat: when the cycle's `accepted_count` has reached its `admission_capacity`, the attempt fails with `ERR_NO_SEATS_AVAILABLE`. A successful acceptance increments `accepted_count` by one, stamps the application's `decided_at` — null until the first decide or promote transition — and creates the `Volunteer`: status `TRAINEE`, `full_name` and `email` copied from the application, and `application_id` pointing back to it. A new volunteer's counters start clean: `consecutive_shortfall_cycles` and `no_show_strikes` at zero, `lifetime_base_hours` and `recognition_points` at 0.0, and `recognition_tier` at `BRONZE`. Waitlisting moves `SCORED → WAITLISTED` and stamps `decided_at`; rejection moves `SCORED → REJECTED`, terminal, and stamps `decided_at`. A `WAITLISTED` application may later be accepted — the same seat check, counter increment, volunteer creation, and `decided_at` stamp apply — or rejected, which is terminal. Invoking a decision on an application in any other state, including a terminal one, fails with `ERR_APPLICATION_NOT_SCORED`.

Waitlisted applications may also be promoted in bulk through a coordinator-driven promotion action on the cycle. The seat check runs first: if `accepted_count` has reached `admission_capacity`, the promotion fails with `ERR_NO_SEATS_AVAILABLE` before any candidate is examined. With a seat free, the candidate set is the cycle's `WAITLISTED` applications; an empty set fails with `ERR_WAITLIST_EMPTY`. Candidates are ranked by `composite_score` descending with ties broken by `created_at` ascending, and the top-ranked application is promoted to `ACCEPTED` with the same side effects as a direct acceptance.

### 3.2. Training and Activation

An accepted applicant becomes a `TRAINEE` volunteer and must complete the cycle's training course. A coordinator creates a `TrainingEnrollment` from a `cycle_id` and a `volunteer_id`; the referenced volunteer must currently be a `TRAINEE`, the cycle must be `OPEN` (otherwise `ERR_CYCLE_NOT_OPEN`), and two capacity guards apply — a volunteer may hold at most one `ENROLLED` enrollment per cycle (a duplicate fails with `ERR_DUPLICATE_ENROLLMENT`), and a cycle whose `enrolled_count` has reached its `training_capacity` accepts no more trainees (`ERR_TRAINING_FULL`). A new enrollment starts `ENROLLED` with `modules_completed` at 0, `quiz_average` at 0.0, and `completed_at` unset, and its creation increments the cycle's `enrolled_count` by one. The enrollment list may be filtered by `cycle_id`, `volunteer_id`, and `status`; the volunteer list by `status` and `application_id`.

Progress is recorded by a coordinator through repeated updates carrying the running `modules_completed` count and the running `quiz_average` (0 to 100). Progress updates require the enrollment to be `ENROLLED` (otherwise `ERR_ENROLLMENT_NOT_ENROLLED`) and the cycle `OPEN`.

Completion finalizes the course. The same two gates apply — `ENROLLED` status and an `OPEN` cycle — and then the thresholds decide the outcome: if `modules_completed` is at least the cycle's `training_module_count` and `quiz_average` is at least the cycle's `training_pass_quiz_average`, the enrollment becomes `COMPLETED`; otherwise it becomes `FAILED`. Both outcomes are valid results of finalization and neither is an error. Either way, `completed_at` is stamped and the cycle's `enrolled_count` is decremented by one. A `COMPLETED` enrollment cascades the volunteer `TRAINEE → ACTIVE`, and that activation provisions a `PENDING` `RecertificationRecord` for the enrollment's cycle when the cycle is `OPEN` and no record yet exists for the pair, with totals initialized to 0.0. A `FAILED` enrollment leaves the volunteer a `TRAINEE`; because no `ENROLLED` duplicate remains, a fresh enrollment may be created for a retry. Enrollments can also reach `DROPPED` — a terminal state entered only through the system cascade when the volunteer withdraws or is deactivated — which likewise decrements `enrolled_count`.

### 3.3. Crediting Service and Continuing Education

Active volunteers log their own hours through self-service credit entries created under their own volunteer path; the `volunteer_id` of the path must match the caller's `X-User-ID` (otherwise `ERR_NOT_RESOURCE_OWNER`), the volunteer must be `ACTIVE` (otherwise `ERR_VOLUNTEER_NOT_ACTIVE`), and the target cycle must be `OPEN` (otherwise `ERR_CYCLE_NOT_OPEN`). The payload carries the `cycle_id` the hours credit toward, an `entry_kind` of `SERVICE` or `CONTINUING_ED`, the `activity_date` the hours were worked, the claimed `hours`, and optionally `activity_type`, `provider`, `title`, `source_type`, `source_id`, and a free-text `note`. The entry begins in `PENDING`: an omitted `source_type` defaults to `NONE`; `source_id`, `note`, and the kind-dependent fields default to null; and `decided_at` stays null until adjudication. The volunteer's provisional totals refresh on the next evaluation or read.

Kind-dependent fields are enforced strictly: a `SERVICE` entry must supply an `activity_type` of `HELP_DESK`, `OUTREACH`, `GARDEN`, `PROJECT`, or `OTHER`, and `activity_type` is forbidden on any other kind; a `CONTINUING_ED` entry must supply both the `provider` name and the course `title`. Violations fail with `ERR_MISSING_KIND_FIELDS`. Claimed `hours` must be a positive multiple of 0.25 no greater than 12.0, and `activity_date` must fall inside the cycle's inclusive `start_date`-to-`end_date` window; a date outside the window fails with `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` (HTTP 422). Manual entries may declare a `source_type` of `NONE` or `PROJECT` only — the `SHIFT` and `ROTATION` values are reserved for system-generated entries, and supplying one manually is another `ERR_MISSING_KIND_FIELDS` failure. A `source_id` is required whenever `source_type` is not `NONE`; it is a polymorphic reference resolved through `source_type` — a project id for `PROJECT`, a shift id for `SHIFT`, a rotation-assignment id for `ROTATION` — and is not a canonical foreign key. A `PROJECT`-sourced entry must reference a project in `APPROVED` or `CLOSED` status, otherwise `ERR_PROJECT_NOT_CREDITABLE`. The credit-entry list may be filtered by `volunteer_id`, `cycle_id`, `entry_kind`, `status`, `source_type`, and `source_id`.

Adjudication is the coordinator's work. Approval of a `PENDING` entry (otherwise `ERR_ENTRY_NOT_PENDING`) against an `OPEN` cycle moves it to `APPROVED`, stamps `decided_at`, and recomputes both the volunteer-cycle record totals and the volunteer's recognition fields. Rejection takes an optional `reason`, moves `PENDING → REJECTED` under the same two gates, stamps `decided_at`, and recomputes record totals; rejected entries count toward neither provisional nor official totals. Revocation is the compensating action for approval: it requires an `APPROVED` entry (otherwise `ERR_ENTRY_NOT_APPROVED`), takes a mandatory `reason`, moves the entry `APPROVED → VOIDED` against an `OPEN` cycle, stamps `decided_at`, and recomputes record totals and recognition fields, so the official totals lose the revoked hours. Entries also reach `VOIDED` through system cascades — a project close voids its `PENDING` project-sourced entries, and volunteer deactivation voids every `PENDING` entry the volunteer holds — and each cascade recomputes the affected records.

Record totals are defined per volunteer-and-cycle pair and come in two variants. The provisional variant includes undecided work: `provisional_service_hours` sums the `hours` of `SERVICE` entries in `PENDING` or `APPROVED` status, and `provisional_ce_hours` does the same for `CONTINUING_ED` entries, with no caps of any kind. The official variant counts only adjudicated work: `official_ce_hours` sums `APPROVED` `CONTINUING_ED` hours, and `official_service_hours` sums `APPROVED` `SERVICE` hours with one carve-out — project-sourced hours are truncated per project under the cap described below, while all non-project approved service hours count in full. `REJECTED` and `VOIDED` entries count toward neither variant. The provisional figure is therefore always at least as large as the official one on identical entry data, and only the official variant is consulted when recertification is decided at cycle close. The `GOLD` outreach multiplier of §3.8 never applies to record totals; it feeds recognition points only. All totals are stored at two decimal places, round half-up.

The per-project cap applies a waterfall inside the official variant. For one volunteer and one project, the volunteer's `APPROVED` entries sourced from that project are processed in chronological order — `activity_date` ascending, ties broken by `created_at` ascending — against the project's `max_creditable_hours_per_volunteer`. A running total starts at zero; each entry contributes the smaller of its own `hours` and the headroom remaining under the cap, which is zero once the cap is exhausted; the running total grows by each counted contribution, and hours beyond the cap are silently not credited. The project's contribution to `official_service_hours` is the final running total.

### 3.4. Shifts, Signups, and Attendance

Help-desk and outreach coverage is organized as shifts. A coordinator creates a `Shift` with a `cycle_id` (the cycle must be `OPEN`, otherwise `ERR_CYCLE_NOT_OPEN`), a `kind` of `HELP_DESK` or `OUTREACH`, a `location` naming the physical or virtual venue, a `start_time` and an `end_time` strictly after it, and a `capacity` between 1 and 20 inclusive. A new shift starts `OPEN` with `filled_count` zero. One venue cannot host two overlapping shifts: for shifts at the same `location` that are not `CANCELLED`, the half-open intervals from `start_time` up to but not including `end_time` must not intersect — a new shift starting before an existing shift ends while the existing shift starts before the new shift ends is a conflict rejected with `ERR_SHIFT_LOCATION_CONFLICT`. Back-to-back scheduling, where the new shift starts exactly when the existing one ends, is allowed. The shift list may be filtered by `cycle_id`, `kind`, `location`, and `status`.

Volunteers sign themselves up: the payload's `volunteer_id` must match the caller's `X-User-ID`, the volunteer must be `ACTIVE` (otherwise `ERR_VOLUNTEER_NOT_ACTIVE`), and the shift must be `OPEN` — attempts against `FULL`, `COMPLETED`, or `CANCELLED` shifts all fail with `ERR_SHIFT_NOT_OPEN`. The logical clock must be strictly earlier than the shift's `start_time`; a signup at or after start fails with `ERR_SIGNUP_WINDOW_CLOSED`. The strike gate follows: a volunteer whose `no_show_strikes` has reached three is blocked with `ERR_NO_SHOW_LIMIT_REACHED` — two strikes still passes, exactly three blocks, and strikes never reset across the volunteer's lifetime. A volunteer may hold at most one `SIGNED_UP` signup per shift (a duplicate fails with `ERR_DUPLICATE_SIGNUP`), and the volunteer's existing schedule is checked for adjacency conflicts: a new shift conflicts with any shift the volunteer is `SIGNED_UP` for unless one of the two starts at or after the other ends plus a buffer — thirty minutes when the two shifts are at different locations, zero when they share a location. A cross-location gap of exactly thirty minutes passes; twenty-nine minutes fails; same-location back-to-back passes. Violations are rejected with `ERR_SIGNUP_SCHEDULE_CONFLICT`. A successful signup is created `SIGNED_UP` under the shift — its `shift_id` is the shift in whose collection it is created — with `signed_up_at` stamped and `completed_entry_id` null; it increments the shift's `filled_count` by one and flips the shift `OPEN → FULL` automatically the moment `filled_count` reaches `capacity`. The signup list may be filtered by `shift_id`, `volunteer_id`, `status`, and `completed_entry_id`.

A signup may be cancelled by the volunteer themself or by a coordinator while it is `SIGNED_UP` (otherwise `ERR_SIGNUP_NOT_SIGNED_UP`); the explicit cancellation action additionally requires the logical clock to be strictly before the shift's `start_time`, failing with `ERR_CANCELLATION_WINDOW_CLOSED` at or after start. Cancellation decrements the shift's `filled_count` by one, and a `FULL` shift reverts to `OPEN`. System cascades — shift cancellation, volunteer deactivation, volunteer withdrawal — cancel signups without any clock precondition, and when the cancellation originates from the shift's own cancellation the revert is skipped because the shift is terminal.

Shift completion and cancellation are coordinator actions. Marking a shift completed requires it to be `OPEN` or `FULL` (otherwise `ERR_INVALID_SHIFT_STATE`) and the logical clock to be at or past `end_time` (otherwise `ERR_SHIFT_NOT_ENDED`), moving it to terminal `COMPLETED`. Cancelling a shift requires `OPEN` or `FULL` (otherwise `ERR_SHIFT_NOT_CANCELLABLE`) and moves it to terminal `CANCELLED`: every `SIGNED_UP` signup cascades to `CANCELLED` and `filled_count` is set to zero, with no `FULL → OPEN` revert firing because the shift is terminal.

Attendance is reconciled after the shift completes. Both post-shift actions require the signup to be `SIGNED_UP` (otherwise `ERR_SIGNUP_NOT_SIGNED_UP`) and the parent shift to be `COMPLETED` (otherwise `ERR_SHIFT_NOT_COMPLETED`). Marking a signup completed mints a `PENDING` `CreditEntry` on the volunteer's ledger: the volunteer taken from the signup, the cycle taken from the shift, `entry_kind` `SERVICE`, `activity_type` `HELP_DESK` when the shift's `kind` is `HELP_DESK` and `OUTREACH` otherwise, `activity_date` set to the date portion of the shift's `start_time`, `hours` computed by the quarter-hour pipeline below, `source_type` `SHIFT`, and `source_id` the shift's id; the signup's `completed_entry_id` is set to the minted entry. Marking a no-show instead moves the signup to terminal `NO_SHOW` and increments the volunteer's `no_show_strikes` by one, moving the volunteer closer to the three-strike signup block.

Credited hours for a completed shift are computed per shift entry at mint time: the shift's duration in whole minutes is divided by fifteen and rounded half-up to a whole count of quarter-hour units, and that count is multiplied by one quarter hour. Volunteer totals then sum the already-rounded per-entry values; summing raw minutes across shifts and rounding once is explicitly not the rule, and the two orders diverge — a 100-minute shift and a 70-minute shift yield 3.00 credited hours under per-entry rounding but 2.75 under sum-then-round.

### 3.5. Inquiries and the Specialist Referral Loop

While staffing a help-desk shift, a volunteer logs the questions the public brings in. Creating an `Inquiry` under a shift requires the shift's `kind` to be `HELP_DESK` (otherwise `ERR_SHIFT_KIND_NOT_HELP_DESK`) and requires the logging volunteer — identified by the payload's `volunteer_id`, which must match the caller's `X-User-ID` — to hold a `SIGNED_UP` or `COMPLETED` signup on that shift (otherwise `ERR_NO_SHIFT_SIGNUP`). The logical clock must sit inside the shift window, at or after `start_time` and strictly before `end_time`; logging outside the window fails with `ERR_OUTSIDE_SHIFT_WINDOW`. That window check is waived for follow-ups: an inquiry carrying `follow_up_of_id` continues an earlier inquiry, which must already be `CLOSED` (otherwise `ERR_FOLLOW_UP_TARGET_NOT_CLOSED`). The payload also carries a one-line `subject`, the `contact_name` of the person asking, and the `details` of the question. A new inquiry starts `LOGGED` with `category` unset, `resolution` `NONE`, `answer_text` and `resolved_at` null, and `follow_up_of_id` absent unless supplied. The inquiry list may be filtered by `shift_id`, `volunteer_id`, `status`, `category`, and `follow_up_of_id`.

A coordinator triages a `LOGGED` inquiry (otherwise `ERR_INQUIRY_NOT_LOGGED`) by setting its `category` to one of `PLANT_ID`, `PEST`, `PLANT_DISEASE`, `SOIL`, or `GENERAL`, moving it `LOGGED → TRIAGED`. From there the desk may settle the question directly: the logging volunteer — and only that volunteer, enforced by ownership (`ERR_NOT_RESOURCE_OWNER`) — answers a `TRIAGED` inquiry (otherwise `ERR_INQUIRY_NOT_TRIAGED`) with `answer_text`, moving it `TRIAGED → CLOSED` with `resolution` `ANSWERED_AT_DESK` and `resolved_at` stamped.

Harder questions go to a specialist. A coordinator creates a `DiagnosisReferral` on a `TRIAGED` inquiry — referral requires triage, so an untriaged inquiry fails with `ERR_INQUIRY_NOT_TRIAGED` — and an inquiry may have at most one referral in `OPEN`, `IN_REVIEW`, or `RETURNED` status at a time; a second attempt fails with `ERR_REFERRAL_ALREADY_OPEN`, because a `RETURNED` referral must be reassigned rather than replaced. The coordinator may nominate an explicit `specialist_id` with an optional `note`, or omit it and let the system select. An explicit specialist must have `open_referral_count` below their `max_concurrent_referrals` (otherwise `ERR_SPECIALIST_AT_CAPACITY`) and a `specialty` equal to the inquiry's `category` or `GENERAL` (otherwise `ERR_SPECIALTY_MISMATCH`). Creation moves the inquiry `TRIAGED → REFERRED`, increments the assignee's `open_referral_count` by one, sets the referral's `due_at` to the logical clock plus forty-eight hours, and starts `reassignment_count` at zero with status `OPEN`; the referral's audit fields — `last_specialist_id`, `diagnosis_text`, `return_reason`, `answered_at`, `answered_by_specialist_id`, `returned_at`, and `returned_by_specialist_id` — remain null until the corresponding events set them.

Auto-selection follows a fixed selector. Candidates are specialists whose `accepting_referrals` flag is true and whose `open_referral_count` is strictly below `max_concurrent_referrals`. Specialty matching is two-tiered: first only specialists whose `specialty` equals the inquiry's `category` are considered; if that pool is empty, specialists with `specialty` `GENERAL` are considered as a fallback; if both pools are empty, creation fails with `ERR_NO_SPECIALIST_AVAILABLE`. On reassignment, the referral's `last_specialist_id` is removed from the candidate pool before ranking. Ranking is by `open_referral_count` ascending, then `rolling_score` descending, then `created_at` ascending, and the top-ranked specialist is assigned.

The specialist registry is coordinator-maintained: registering a `Specialist` takes a `name`, a `specialty` from the same five-value enumeration as inquiry categories, a `max_concurrent_referrals` quota of at least one, and an optional `accepting_referrals` flag that defaults to true. Counters (`open_referral_count`, `answered_count`, `late_referral_count`, `returned_count`) start at zero and both performance scores at 100.0. Capacity and availability edits are optimistic-concurrency-guarded per §2.8. The specialist list may be filtered by `specialty` and `accepting_referrals`; the referral list by `inquiry_id`, `specialist_id`, `last_specialist_id`, `answered_by_specialist_id`, `returned_by_specialist_id`, and `status`.

The assigned specialist drives the referral through its work loop. Starting review requires the referral to be `OPEN` (otherwise `ERR_REFERRAL_NOT_OPEN`) and the caller to be the assignee (`ERR_NOT_RESOURCE_OWNER`), moving it `OPEN → IN_REVIEW`. Answering requires `IN_REVIEW` (otherwise `ERR_REFERRAL_NOT_IN_REVIEW`) and the same ownership check; the specialist supplies `diagnosis_text`, the server stamps `answered_at` from the logical clock and `answered_by_specialist_id` with the assignee, decrements the specialist's `open_referral_count`, and increments `answered_count`. An answer is late when `answered_at` is strictly later than `due_at` — an answer exactly at `due_at` is on time — and a late answer also increments `late_referral_count`. Answering moves the referral to `ANSWERED`, its terminal state, cascades the inquiry `REFERRED → CLOSED` with `resolution` `SPECIALIST_DIAGNOSIS` and `resolved_at` stamped, and both of the specialist's performance scores are recomputed.

A specialist who cannot take the case returns it: from `IN_REVIEW`, with the same state and ownership gates, the specialist supplies a `return_reason`; the server stamps `returned_at` and `returned_by_specialist_id`, decrements `open_referral_count`, increments `returned_count`, copies the assignee into `last_specialist_id`, clears `specialist_id` to null, moves the referral to `RETURNED`, and recomputes both scores. A coordinator then reassignment-loops the referral `RETURNED → OPEN` — valid only from `RETURNED` (otherwise `ERR_REFERRAL_NOT_RETURNED`) — either by naming an explicit `specialist_id` or by re-running auto-selection; an explicit pick equal to `last_specialist_id` is rejected with `ERR_INVALID_REQUEST`, and auto-selection excludes the last specialist from the pool as described above. Reassignment increments the new assignee's `open_referral_count`, increments `reassignment_count`, and refreshes `due_at` to the logical clock plus forty-eight hours — a fresh SLA per reassignment.

Specialist performance is scored identically in structure and differently in window. Late events are referrals the specialist answered where `answered_at` was strictly later than `due_at`; returned events are referrals whose latest return was performed by the specialist — a referral returned multiple times counts only its latest return. Each late event costs five points and each return costs three. The lifetime variant, exposed as `lifetime_score`, penalizes events over all time; the rolling variant, exposed as `rolling_score`, penalizes only events whose resolution timestamp falls on or after the instant exactly ninety days before the current logical clock, and it is the rolling variant the assignment selector ranks by. Each score is the greater of zero and one hundred minus its penalty, expressed as an integer, so identical histories yield different scores whenever old resolutions fall outside the rolling window. Both fields are recomputed on every answer, every return, and every read of the specialist.

### 3.6. Community Projects

An `ACTIVE` volunteer may propose a community project against an `OPEN` cycle. Creation carries the `cycle_id`, the `organizer_volunteer_id` — which must equal the caller's `X-User-ID`, since volunteers propose only their own projects — a `title`, a scope `description`, and an `estimated_hours_per_volunteer` that must be positive and a multiple of 0.25. The project begins in `DRAFT`, with `approved_by_user_id`, `feedback`, and `max_creditable_hours_per_volunteer` all unset. The project list may be filtered by `cycle_id`, `organizer_volunteer_id`, and `status`.

While the project is `DRAFT` or `REVISION_REQUESTED` — in any other state the attempt fails with `ERR_PROJECT_NOT_EDITABLE` — the organizer may amend `title`, `description`, and `estimated_hours_per_volunteer` under the optimistic-concurrency protocol of §2.8, and may submit the project for review. Submission moves `DRAFT → UNDER_REVIEW` on first submission and `REVISION_REQUESTED → UNDER_REVIEW` on resubmission, and both paths enforce organizer ownership (`ERR_NOT_RESOURCE_OWNER`).

Review is a coordinator decision on an `UNDER_REVIEW` project; any other state fails with `ERR_PROJECT_NOT_UNDER_REVIEW`. Approval records the approving coordinator's `X-User-ID` in `approved_by_user_id` and computes the per-volunteer credit cap: `max_creditable_hours_per_volunteer` becomes the lesser of 20.0 and the project's `estimated_hours_per_volunteer` multiplied by 1.25 and rounded half-up to two decimal places, remaining null until the project is `APPROVED`. A request for revision carries `feedback` and moves the project to `REVISION_REQUESTED`, opening the resubmission loop back through amendment and submission. Rejection carries a `reason`, records it as the latest `feedback`, and moves the project to terminal `REJECTED`.

Closing an `APPROVED` project (otherwise `ERR_PROJECT_NOT_APPROVED`) is coordinator work under a segregation-of-duties rule: the caller's `X-User-ID` must differ from the project's `approved_by_user_id`, and a close attempted by the approving coordinator fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Closing cascades through the credit ledger in two links: first, every `PENDING` `CreditEntry` whose `source_type` is `PROJECT` and whose `source_id` is this project is voided; second, the `RecertificationRecord` totals of every volunteer whose entry was voided are recomputed. `CLOSED` is terminal.

Project participation feeds the credit ledger of §3.3: volunteers log `PROJECT`-sourced entries against projects that are `APPROVED` or `CLOSED`, those hours enter provisional totals in full, and the official totals count them only up to each project's `max_creditable_hours_per_volunteer` through the per-project waterfall.

### 3.7. The Demonstration Garden Rotation

Demonstration-garden beds are staffed one volunteer-week at a time. A coordinator creates a `RotationAssignment` from a `bed_code` identifying the bed, a `volunteer_id` that must reference an `ACTIVE` volunteer (otherwise `ERR_VOLUNTEER_NOT_ACTIVE`), and a `week_start` date that must be a Monday (otherwise `ERR_INVALID_FIELD_VALUE`). The assignment's `cycle_id` is derived, not supplied: it is the unique `OPEN` cycle whose inclusive `start_date`-to-`end_date` window contains `week_start`, and when no such cycle exists the creation fails with `ERR_NO_OPEN_CYCLE`. The `week_end` is computed as six days after `week_start` — the Sunday — and the bed is occupied over the closed day-granularity range from `week_start` through `week_end` inclusive. Two assignments on the same `bed_code` with status `ASSIGNED` or `COMPLETED` conflict when their closed week ranges intersect — the new week starting on or before the existing week ends while the existing week starts on or before the new week ends — and the conflict is rejected with `ERR_BED_WEEK_CONFLICT`; adjacent weeks, where the next Monday falls exactly one day after the prior week's Sunday, are disjoint and allowed. The assignment is created in `ASSIGNED` status with `actual_hours` unset and `swapped_to_id` null. The rotation list may be filtered by `bed_code`, `volunteer_id`, `cycle_id`, `status`, and `swapped_to_id`.

One volunteer may not hold a bed indefinitely: considering the volunteer's `ASSIGNED` and `COMPLETED` assignments on the same `bed_code` whose weeks form an unbroken Monday-to-Monday chain ending immediately before the new `week_start`, the chain length is the count of consecutive weeks already held — zero when no such chain exists. The new assignment is rejected with `ERR_CONSECUTIVE_WEEK_LIMIT` when the chain has reached two: a volunteer may hold at most two consecutive weeks on the same bed, and the third consecutive week fails. Weeks on other beds never count, and a gap week resets the chain.

Once the week has run, the coordinator records the outcome; both outcomes require the assignment to be `ASSIGNED` (otherwise `ERR_ASSIGNMENT_NOT_ASSIGNED`) and the logical clock to have reached the instant exactly seven days after `week_start` at 00:00:00 UTC (otherwise `ERR_WEEK_NOT_ENDED`). Completion additionally takes the `actual_hours` worked, which must lie between 0.5 and 8.0 inclusive in steps of 0.25 (otherwise `ERR_INVALID_FIELD_VALUE`), moves the assignment to `COMPLETED`, and mints a `PENDING` `CreditEntry`: the volunteer and cycle taken from the assignment, `entry_kind` `SERVICE`, `activity_type` `GARDEN`, `activity_date` set to `week_end`, `hours` equal to the reported `actual_hours`, `source_type` `ROTATION`, and `source_id` the assignment's id. Marking the week missed moves it to `MISSED` under the same state and clock gates, with no credit minted.

Before the week ends, a coordinator may swap the assignment to another volunteer: the assignment must be `ASSIGNED`, the logical clock must be strictly earlier than the seven-days-after-`week_start` instant (otherwise `ERR_SWAP_WINDOW_CLOSED`), and `new_volunteer_id` must reference an `ACTIVE` volunteer (otherwise `ERR_VOLUNTEER_NOT_ACTIVE`). The replacement assignment must pass all creation rules — the bed-week overlap check, in which `SWAPPED` and other terminal assignments do not block, and the consecutive-week limit evaluated for the new volunteer. A successful swap moves the original to `SWAPPED` and creates the replacement in `ASSIGNED` with the same `bed_code`, `week_start`, `week_end`, and derived `cycle_id`, its `volunteer_id` set to `new_volunteer_id`; the original's `swapped_to_id` points at the replacement.

### 3.8. Evaluation, Recertification, and the Year-End Close

Every `RecertificationRecord` pairs one volunteer with one cycle and begins `PENDING` whenever it is provisioned — at cycle open for each `ACTIVE` volunteer lacking one, at trainee activation, and at reactivation. A record tracks the provisional and official totals of §3.3, a `hardship_exemption` flag defaulting to false with its `exemption_reason` null until granted, the computed `effective_hour_requirement` and `effective_ce_requirement` (both null until computed), and `evaluated_at` and `finalized_at` stamps, null until an evaluation or the cycle close respectively sets them. The record list may be filtered by `volunteer_id`, `cycle_id`, and `status`.

A coordinator may evaluate a `PENDING` record at any time — evaluation of a finalized record fails with `ERR_RECORD_NOT_PENDING` — which recomputes and stores the four totals per the two-variant rule of §3.3, recomputes the effective requirements, and stamps `evaluated_at`. The effective requirements derive from the cycle's requirements and the hardship flag: each effective requirement is the corresponding cycle requirement multiplied by one-half when `hardship_exemption` is true and by one otherwise, then rounded half-up to the nearest quarter-hour. A coordinator grants the exemption on a `PENDING` record — a finalized record fails here with `ERR_RECORD_NOT_PENDING` as well — by supplying a `reason`; the grant sets `hardship_exemption` true and records `exemption_reason`, halving both effective requirements on the next computation.

Recognition accrues alongside the ledger and is recomputed on every credit approval, rejection, or revocation, on every record evaluation, and at cycle close, in a pinned three-step order. First, `lifetime_base_hours` is the sum of `official_service_hours` across all of the volunteer's records whose cycle is `CLOSED`, plus the current non-closed cycle's raw `official_service_hours` — outreach hours unmultiplied. Second, `recognition_tier` is read from that base: `GOLD` when the base has reached 40.0, otherwise `SILVER` when it has reached 20.0, otherwise `BRONZE`, with equality advancing the tier. Third, `recognition_points` is the base plus, only when the tier is `GOLD`, one quarter of the current cycle's official `SERVICE` hours whose `activity_type` is `OUTREACH`. Because the tier reads only the unmultiplied base, a volunteer who crosses the `GOLD` threshold through outreach hours still earns the bonus afterwards, but the bonus itself never feeds back into the tier.

When the coordinator closes a cycle — valid only from `RECERTIFICATION`, otherwise `ERR_INVALID_CYCLE_STATE` — the year-end adjudication runs as a four-link cascade. Link one finalizes every `PENDING` record in the cycle, processing volunteers in `created_at` ascending order: official totals are computed, each record's status is set to `RECERTIFIED` when its `official_service_hours` is at least its `effective_hour_requirement` and its `official_ce_hours` is at least its `effective_ce_requirement`, and to `SHORTFALL` otherwise, with equality passing — 40.0 hours against a 40.0 requirement recertifies while 39.75 shortfalls — and `finalized_at` stamped. Link two applies the volunteer consequences: a `RECERTIFIED` volunteer stays `ACTIVE` and has `consecutive_shortfall_cycles` reset to zero, while a `SHORTFALL` volunteer transitions `ACTIVE → INACTIVE` and has `consecutive_shortfall_cycles` incremented by one. Link three runs the deactivation cascade for each volunteer deactivated at link two: their `SIGNED_UP` signups become `CANCELLED`, their `PENDING` credit entries become `VOIDED`, and their `ENROLLED` enrollments become `DROPPED`. Link four settles shift capacity: each signup cancelled at link three decrements its shift's `filled_count` by one, and a shift that was `FULL` reverts to `OPEN`. Finally, any volunteer whose `consecutive_shortfall_cycles` reaches two at link two continues from `INACTIVE` to terminal `EXITED` within the same close run.

Volunteers may also leave the program mid-stream. Withdrawal — invoked by a coordinator or by the volunteer themself — moves a `TRAINEE`, `ACTIVE`, or `INACTIVE` volunteer to terminal `WITHDRAWN` and runs the same deactivation cascade: signups cancelled with their `filled_count` decrements and `FULL → OPEN` reverts, `PENDING` entries voided, and `ENROLLED` enrollments dropped. The reverse path is reactivation, a coordinator action valid only on an `INACTIVE` volunteer (otherwise `ERR_VOLUNTEER_NOT_INACTIVE`) and only while at least one cycle is `OPEN` (otherwise `ERR_NO_OPEN_CYCLE`). The target cycle is the `OPEN` cycle with the latest `start_date`, ties broken by `created_at` ascending; reactivation moves the volunteer `INACTIVE → ACTIVE` and provisions a fresh `PENDING` record in that cycle — none may exist for the pair — with totals initialized to 0.0. The volunteer lifecycle is thus cyclic across years: `TRAINEE` at intake, `ACTIVE ↔ INACTIVE` across recertifications and reactivations, and `EXITED` or `WITHDRAWN` as the terminal exits.

## 4. Endpoint Definitions

Operations that create a new resource — a program cycle, an application, a training enrollment, a credit entry, a shift, a signup, an inquiry, a referral, a specialist, a project, or a rotation assignment — return `201 Created`. Operations that modify an existing resource or trigger a state transition return `200 OK`; the clock-setting capability also returns `200 OK`. The table below is a navigation index only: request payloads, gating rules, validation order, and side effects are specified in §2 and §3. Rows marked "All roles" are readable by `ProgramCoordinator`, `Volunteer`, and `Specialist` alike.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramCoordinator |
| POST | `/program-cycles` | Create a program cycle (status DRAFT) | ProgramCoordinator |
| GET | `/program-cycles` | List program cycles | All roles |
| GET | `/program-cycles/{cycleId}` | Get a program cycle | All roles |
| PUT | `/program-cycles/{cycleId}` | Edit cycle configuration (OCC-guarded) | ProgramCoordinator |
| POST | `/program-cycles/{cycleId}/open` | Open the cycle (DRAFT → OPEN) | ProgramCoordinator |
| POST | `/program-cycles/{cycleId}/begin-recertification` | Move OPEN → RECERTIFICATION once the recert window opens | ProgramCoordinator |
| POST | `/program-cycles/{cycleId}/close` | Close the cycle, finalizing records and cascading statuses | ProgramCoordinator |
| POST | `/program-cycles/{cycleId}/promote-waitlisted` | Promote the top-ranked WAITLISTED application | ProgramCoordinator |
| POST | `/applications` | Submit an application to a cycle | ProgramCoordinator |
| GET | `/applications` | List applications | All roles |
| GET | `/applications/{applicationId}` | Get an application | All roles |
| POST | `/applications/{applicationId}/score` | Enter review scores and compute the composite | ProgramCoordinator |
| POST | `/applications/{applicationId}/decide` | Decide a SCORED or WAITLISTED application | ProgramCoordinator |
| GET | `/volunteers` | List volunteers | All roles |
| GET | `/volunteers/{volunteerId}` | Get a volunteer | All roles |
| POST | `/volunteers/{volunteerId}/withdraw` | Withdraw a volunteer (deactivation cascade) | ProgramCoordinator, Volunteer |
| POST | `/volunteers/{volunteerId}/reactivate` | Reactivate an INACTIVE volunteer into an OPEN cycle | ProgramCoordinator |
| POST | `/training-enrollments` | Enroll a TRAINEE volunteer in a cycle's course | ProgramCoordinator |
| GET | `/training-enrollments` | List training enrollments | All roles |
| GET | `/training-enrollments/{enrollmentId}` | Get a training enrollment | All roles |
| POST | `/training-enrollments/{enrollmentId}/progress` | Record module and quiz progress | ProgramCoordinator |
| POST | `/training-enrollments/{enrollmentId}/complete` | Finalize training (COMPLETED or FAILED) | ProgramCoordinator |
| POST | `/volunteers/{volunteerId}/credit-entries` | Log a service or continuing-education entry | Volunteer |
| GET | `/credit-entries` | List credit entries | All roles |
| GET | `/credit-entries/{entryId}` | Get a credit entry | All roles |
| POST | `/credit-entries/{entryId}/approve` | Approve a PENDING entry | ProgramCoordinator |
| POST | `/credit-entries/{entryId}/reject` | Reject a PENDING entry | ProgramCoordinator |
| POST | `/credit-entries/{entryId}/revoke` | Revoke an APPROVED entry | ProgramCoordinator |
| GET | `/recertification-records` | List recertification records | All roles |
| GET | `/recertification-records/{recordId}` | Get a recertification record | All roles |
| POST | `/recertification-records/{recordId}/evaluate` | Recompute and store totals and effective requirements | ProgramCoordinator |
| POST | `/recertification-records/{recordId}/grant-exemption` | Grant a hardship exemption | ProgramCoordinator |
| POST | `/shifts` | Create a help-desk or outreach shift | ProgramCoordinator |
| GET | `/shifts` | List shifts | All roles |
| GET | `/shifts/{shiftId}` | Get a shift | All roles |
| POST | `/shifts/{shiftId}/cancel` | Cancel an OPEN or FULL shift | ProgramCoordinator |
| POST | `/shifts/{shiftId}/complete` | Mark a shift COMPLETED once it has ended | ProgramCoordinator |
| POST | `/shifts/{shiftId}/signups` | Sign a volunteer up for a shift | Volunteer |
| GET | `/shift-signups` | List shift signups | All roles |
| GET | `/shift-signups/{signupId}` | Get a shift signup | All roles |
| POST | `/shift-signups/{signupId}/cancel` | Cancel a SIGNED_UP signup before the shift starts | ProgramCoordinator, Volunteer |
| POST | `/shift-signups/{signupId}/complete` | Mark attendance; mints the shift credit entry | ProgramCoordinator |
| POST | `/shift-signups/{signupId}/mark-no-show` | Mark a no-show; increments the strike count | ProgramCoordinator |
| POST | `/shifts/{shiftId}/inquiries` | Log a help-desk inquiry during a shift | Volunteer |
| GET | `/inquiries` | List inquiries | All roles |
| GET | `/inquiries/{inquiryId}` | Get an inquiry | All roles |
| POST | `/inquiries/{inquiryId}/triage` | Triage a LOGGED inquiry and set its category | ProgramCoordinator |
| POST | `/inquiries/{inquiryId}/answer` | Answer a TRIAGED inquiry at the desk | Volunteer |
| POST | `/inquiries/{inquiryId}/referrals` | Refer a TRIAGED inquiry to a specialist | ProgramCoordinator |
| GET | `/diagnosis-referrals` | List diagnosis referrals | All roles |
| GET | `/diagnosis-referrals/{referralId}` | Get a diagnosis referral | All roles |
| POST | `/diagnosis-referrals/{referralId}/start-review` | Assigned specialist starts review | Specialist |
| POST | `/diagnosis-referrals/{referralId}/answer` | Assigned specialist answers; closes the inquiry | Specialist |
| POST | `/diagnosis-referrals/{referralId}/return` | Assigned specialist returns the referral to the pool | Specialist |
| POST | `/diagnosis-referrals/{referralId}/reassign` | Reassign a RETURNED referral | ProgramCoordinator |
| POST | `/specialists` | Register a specialist | ProgramCoordinator |
| GET | `/specialists` | List specialists | All roles |
| GET | `/specialists/{specialistId}` | Get a specialist | All roles |
| PATCH | `/specialists/{specialistId}` | Update specialist capacity or availability (OCC-guarded) | ProgramCoordinator |
| POST | `/projects` | Propose a community project | Volunteer |
| GET | `/projects` | List community projects | All roles |
| GET | `/projects/{projectId}` | Get a community project | All roles |
| PUT | `/projects/{projectId}` | Amend a DRAFT or REVISION_REQUESTED project (OCC-guarded) | Volunteer |
| POST | `/projects/{projectId}/submit` | Submit a project for review | Volunteer |
| POST | `/projects/{projectId}/approve` | Approve an UNDER_REVIEW project | ProgramCoordinator |
| POST | `/projects/{projectId}/request-revision` | Send a project back for revision | ProgramCoordinator |
| POST | `/projects/{projectId}/reject` | Reject an UNDER_REVIEW project | ProgramCoordinator |
| POST | `/projects/{projectId}/close` | Close an APPROVED project; voids PENDING project entries | ProgramCoordinator |
| POST | `/rotation-assignments` | Assign a volunteer to a garden bed for a week | ProgramCoordinator |
| GET | `/rotation-assignments` | List rotation assignments | All roles |
| GET | `/rotation-assignments/{assignmentId}` | Get a rotation assignment | All roles |
| POST | `/rotation-assignments/{assignmentId}/complete` | Complete a rotation week; mints GARDEN credit | ProgramCoordinator |
| POST | `/rotation-assignments/{assignmentId}/mark-missed` | Mark a rotation week missed | ProgramCoordinator |
| POST | `/rotation-assignments/{assignmentId}/swap` | Swap an ASSIGNED week to another ACTIVE volunteer | ProgramCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FIELD_VALUE` | 422 Unprocessable Entity |
| `ERR_MISSING_KIND_FIELDS` | 422 Unprocessable Entity |
| `ERR_STALE_CYCLE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SPECIALIST_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_NOT_EDITABLE` | 409 Conflict |
| `ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS` | 409 Conflict |
| `ERR_NO_OPEN_CYCLE` | 409 Conflict |
| `ERR_RECERT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_CYCLE_STATE` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_SCORED` | 409 Conflict |
| `ERR_NO_SEATS_AVAILABLE` | 409 Conflict |
| `ERR_WAITLIST_EMPTY` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_ACTIVE` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_INACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_TRAINING_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_ENTRY_NOT_PENDING` | 409 Conflict |
| `ERR_ENTRY_NOT_APPROVED` | 409 Conflict |
| `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_CREDITABLE` | 409 Conflict |
| `ERR_RECORD_NOT_PENDING` | 409 Conflict |
| `ERR_SHIFT_LOCATION_CONFLICT` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_NOT_ENDED` | 409 Conflict |
| `ERR_SHIFT_NOT_COMPLETED` | 409 Conflict |
| `ERR_SHIFT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INVALID_SHIFT_STATE` | 409 Conflict |
| `ERR_SIGNUP_NOT_SIGNED_UP` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_NO_SHOW_LIMIT_REACHED` | 409 Conflict |
| `ERR_SIGNUP_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CANCELLATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SIGNUP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SHIFT_KIND_NOT_HELP_DESK` | 409 Conflict |
| `ERR_NO_SHIFT_SIGNUP` | 409 Conflict |
| `ERR_OUTSIDE_SHIFT_WINDOW` | 409 Conflict |
| `ERR_FOLLOW_UP_TARGET_NOT_CLOSED` | 409 Conflict |
| `ERR_INQUIRY_NOT_LOGGED` | 409 Conflict |
| `ERR_INQUIRY_NOT_TRIAGED` | 409 Conflict |
| `ERR_REFERRAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_NO_SPECIALIST_AVAILABLE` | 409 Conflict |
| `ERR_SPECIALIST_AT_CAPACITY` | 409 Conflict |
| `ERR_SPECIALTY_MISMATCH` | 409 Conflict |
| `ERR_REFERRAL_NOT_OPEN` | 409 Conflict |
| `ERR_REFERRAL_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_REFERRAL_NOT_RETURNED` | 409 Conflict |
| `ERR_PROJECT_NOT_EDITABLE` | 409 Conflict |
| `ERR_PROJECT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_PROJECT_NOT_APPROVED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_BED_WEEK_CONFLICT` | 409 Conflict |
| `ERR_CONSECUTIVE_WEEK_LIMIT` | 409 Conflict |
| `ERR_WEEK_NOT_ENDED` | 409 Conflict |
| `ERR_SWAP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ASSIGNED` | 409 Conflict |
