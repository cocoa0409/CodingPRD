# Academic Advising Caseload API — Product Requirements Document

## 1. Introduction

A university advising center is an exercise in managed scarcity. A small team of advisors must be matched against a large and constantly shifting student population, balanced by major coverage and by the weight of each caseload, while the center absorbs two parallel streams of contact — scheduled appointments and a walk-in drop-in queue — without double-booking anyone. Layered on top of that traffic are the obligations that make advising a retention function rather than a reception desk: early-alert referrals from faculty that demand a disciplined outreach protocol, registration holds whose release may depend on an approved degree plan, term-by-term degree mapping, and confidential advising notes whose visibility is restricted even inside the advising team. When these concerns live in disconnected spreadsheets, at-risk students fall through the cracks between systems.

This document specifies the Academic Advising Caseload API, the backend contract for that advising center. All advising resources are mounted under the `/advising` path prefix. The API manages ten resource types — advisors, students, advisor assignments, appointments, drop-in tickets, early-alert referrals, interventions, registration holds, degree plans, and advising notes — under a role model with an ownership-gated advisor tier beneath a superset director. Every time-dependent rule in the system (check-in windows, service-level deadlines, queue dates, the close-of-day sweep) reads a server-side logical clock rather than wall-clock time, and every mutation is committed together with the recomputations it triggers, so a response never reflects a half-applied cascade.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes exactly four roles: `AdvisingDirector`, `Advisor`, `FrontDeskStaff`, and `FacultyReferrer`. A request missing either header, or carrying a role value outside these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not in the target endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting Advisor resource; ownership checks on any resource that references an Advisor compare the resource's foreign-key field — an assignment's or appointment's `advisor_id` — to `X-User-ID`. When `X-User-Role` is `AdvisingDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it (for example, as `author_user_id` on an advising note) but never compares it to any entity's `id`, and the director may perform every Advisor-gated operation without ownership restriction. When `X-User-Role` is `FrontDeskStaff`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the same is true when `X-User-Role` is `FacultyReferrer`, a peer role that files early-alert referrals and reads referral status.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-dependent rule in the API — the check-in window, service-level breach flags, queue dating, and the close-of-day sweep — reads a single server-side logical clock, never the host machine's wall clock. Before it has ever been set, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. An `AdvisingDirector` advances it through the test-driving capability at `/_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response echoes the new logical time as `current_utc`.

The logical clock has three principal consumers. A drop-in ticket's `queue_date` is the logical calendar date at the moment of intake, and it is what groups the daily queue. A referral's `is_sla_breached` flag is recomputed against the logical clock on every read and again during the daily close. And the sweep compares logical time against appointment start times and queue dates to decide what has lapsed. Resource `created_at` and `updated_at` stamps (§2.5) are likewise read from this clock, never from wall-clock time, so resources created or modified without an intervening clock advance carry identical timestamps.

### 2.5. Common Resource Properties

Every resource in the system — Advisor, Student, AdvisorAssignment, Appointment, DropInTicket, EarlyAlertReferral, Intervention, RegistrationHold, DegreePlan, and AdvisingNote alike — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed whenever the resource is modified.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

### 2.6. Nested Resource Retrieval

Registration holds, degree plans, and advising notes are student sub-resources: they are addressed beneath the path of the student who owns them. For any request whose path contains multiple identifiers, the system validates existence strictly left to right — the student `id` first, then the nested `holdId` or `planId` — and rejects the request with the 404 corresponding to the first identifier that does not resolve. A hold or plan identifier that does not exist under the path student yields `ERR_HOLD_NOT_FOUND` or `ERR_PLAN_NOT_FOUND` respectively, even if that identifier happens to exist under a different student.

Across the API, path parameters are named `id` for the student in nested routes, `advisorId`, `assignmentId`, `appointmentId`, `ticketId`, `referralId`, `interventionId`, `holdId`, and `planId`.

### 2.7. Derived Fields and Immediate Recomputation

Many fields in this API are computed rather than written. An advisor exposes three load measures — `assigned_active_count`, `weighted_load`, and `scheduled_minutes`. A student exposes `no_show_count` plus the four derived advising fields `at_risk_score`, `risk_tier`, `advising_requirement_status`, and `registration_clearance`. An appointment derives `duration_minutes` from its slot; a drop-in ticket receives a fixed `position`; a referral derives `due_at` and `is_sla_breached`; a degree plan derives `mapped_credits_total`.

All of these are recomputed eagerly whenever a triggering event occurs, and the consistency model is immediate: a mutation and every recomputation it triggers are committed together and are visible in that mutation's own response. No read ever returns a stale derived value, and no client ever needs to poll for a cascade to settle.

### 2.8. Numeric Precision and Rounding

Numeric rules differ per quantity and are fixed as follows. The at-risk score is an integer computed with integer arithmetic; it involves no rounding and is capped at a ceiling of 100. Appointment durations and scheduled-minute totals are expressed in whole minutes. Degree-plan credit mapping rounds each term's credit sum half-up to a whole number before any total is taken, and the plan's mapped total is an integer sum of those per-term integers. The retention report's rate is rendered to exactly four decimal places using round-half-up. Service-level deadlines are computed and compared at second precision on ISO 8601 timestamps.

### 2.9. Optimistic Concurrency Control

Exactly one write operation participates in optimistic concurrency control: the manual creation of an advisor assignment. That request must carry `expected_student_version`, holding the target student's `version` as the client last observed it. If the value does not match the student's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a view of the student that another writer has already advanced.

A student's `version` advances on every student update and on every assignment creation, auto-assignment, or assignment ending for that student, so a client that read the student before such an event holds a stale version and will be stopped. No other endpoint accepts a version field; in particular, the auto-assign selector does not take `expected_student_version`, because it reads live state itself when choosing an advisor.

### 2.10. Evaluation Order of Request Checks

Every request is evaluated against a fixed pipeline of checks. A failure at any step stops evaluation and produces that step's error, so when several problems coexist, the earliest step's error is the one reported:

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the four declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Request shape.** Required input fields must be present, enum values must be in their declared domains, datetimes must parse, `gpa` must lie between 0.0 and 4.0 inclusive, `max_caseload` must be at least 1, and an appointment slot must end strictly after it starts with a duration between 15 and 60 minutes inclusive. Violations yield `ERR_VALIDATION`, or `ERR_INVALID_APPOINTMENT_DURATION` for the duration rule (both HTTP 400).
3. **Role authorization.** The caller's role must appear in the endpoint's authorized role list, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
4. **Existence.** Path identifiers are validated left to right, then body-referenced identifiers such as `student_id`, `advisor_id`, and `referral_id`. The first miss produces the matching 404: `ERR_STUDENT_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND`.
5. **Stale-version guard.** On manual assignment creation only, `expected_student_version` must equal the student's current `version`, else `ERR_STALE_VERSION` (HTTP 412). This guard sits after existence and before state checks: a creation that fails both the version guard and a later eligibility check reports `ERR_STALE_VERSION`.
6. **State preconditions.** The target resource must be in the source state of the requested transition — violations yield `ERR_APPOINTMENT_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`, `ERR_REFERRAL_INVALID_STATE`, `ERR_HOLD_NOT_ACTIVE`, `ERR_PLAN_INVALID_STATE`, `ERR_ASSIGNMENT_ALREADY_ENDED`, or `ERR_INTERVENTION_ALREADY_CLOSED` — and two student-state gates apply: note creation requires the student not be `INACTIVE` (`ERR_STUDENT_INACTIVE`), and assignment creation requires the student be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`). All are HTTP 409.
7. **Ownership and confidentiality.** On ownership-gated operations, an `Advisor`-role caller must be the student's assigned advisor — meaning an `ACTIVE` assignment whose `advisor_id` equals `X-User-ID` — else `ERR_NOT_ASSIGNED_ADVISOR` (HTTP 403); `CONFIDENTIAL` note authorship carries its own restriction, else `ERR_NOTE_CONFIDENTIALITY_RESTRICTED` (HTTP 403).
8. **Capacity, uniqueness, eligibility, and overlap.** Advisor capacity and major coverage for assignment, advisor-active for manual assignment, a non-empty auto-assign pool, one active drop-in ticket per student per day, the daily queue cap, a non-empty queue on call-next, advisor schedule overlap, one non-terminal degree plan per student, and the two plan submit gates. All are HTTP 409 except `ERR_NO_ELIGIBLE_ADVISOR`, which is HTTP 422.
9. **Temporal window.** Check-in must fall inside its window, else `ERR_OUTSIDE_CHECK_IN_WINDOW` (HTTP 409); an appointment that is not `SCHEDULED` reports `ERR_APPOINTMENT_INVALID_STATE` at step 6 even when the caller is also outside the window.
10. **Cross-entity state.** Appointment booking requires the student be `ENROLLED` and the advisor be `ACTIVE`; releasing a plan-gated hold requires an approved plan (`ERR_PLAN_NOT_APPROVED`). All are HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Building the Advisor Roster: Capacity and Load Measures

An `AdvisingDirector` builds the advising roster by registering each advisor with a `full_name`, an `email`, the list of `major_codes` the advisor serves (the assignment eligibility key), and a `max_caseload` — the maximum number of `ACTIVE` assignments the advisor may carry, which must be at least 1 (`ERR_VALIDATION` otherwise). A freshly created advisor starts with `status` set to `ACTIVE` and all three load measures at zero.

Those three load measures are the center's instrument panel. `assigned_active_count` is the number of assignments naming this advisor whose status is `ACTIVE`. `weighted_load` sums, over those same active assignments, a per-student risk weight: 1 for a `LOW`-tier student, 2 for `MEDIUM`, and 3 for `HIGH`. `scheduled_minutes` totals the `duration_minutes` of the advisor's appointments that are in `SCHEDULED` or `CHECKED_IN` — exactly those two statuses count; `COMPLETED`, `CANCELLED`, and `NO_SHOW` slots are excluded. All three recompute eagerly on every triggering event and are returned on advisor reads, and the advisor directory can be filtered by `status`.

A director may later adjust an advisor's `status` or `max_caseload`. The capacity may never be set below the advisor's current `assigned_active_count` — an attempt is rejected with `ERR_VALIDATION`. Marking an advisor `INACTIVE` blocks any new assignment or appointment that would reference this advisor with `ERR_ADVISOR_NOT_ACTIVE`.

### 3.2. Student Intake, Term Rollover, and the At-Risk Score

Registration of a student — performed by an `AdvisingDirector` or a `FrontDeskStaff` operator — captures `full_name`, `email`, the declared `major_code`, the entry `cohort_year`, the student's `current_term_code` (a term code such as FA26), and `gpa`, which must lie between 0.0 and 4.0 inclusive (`ERR_VALIDATION` otherwise). An optional `advising_required_flag` declares whether an advising session is required before registration; it defaults to false. A newly created student starts with `care_status` set to `ENROLLED`, with `enrolled_term_codes` seeded to contain exactly the initial term, and with the four derived fields — `at_risk_score`, `risk_tier`, `advising_requirement_status`, and `registration_clearance` — computed immediately.

The `at_risk_score` is an integer from 0 to 100 assembled from five components. The base comes from the student's GPA band: 40 points when `gpa` is below 2.0, 25 points when it is at least 2.0 but below 2.5, and 10 points when it is 2.5 or higher. The referral boost is the single largest severity boost among the student's referrals in `OPEN`, `OUTREACH_IN_PROGRESS`, `NO_RESPONSE`, or `ESCALATED` status — 20 for `HIGH`, 12 for `MEDIUM`, 6 for `LOW` — or zero when no such referral exists; `RESPONDED` and `CLOSED` referrals contribute nothing. No-show points add 10 per recorded no-show, counting no more than three no-shows. Intervention points add 10 per `OPEN` intervention. Hold points add 8 per `ACTIVE` registration hold. The score is the sum of these five components, capped at 100.

From the score, the `risk_tier` is `HIGH` when the score is 70 or higher, `MEDIUM` when it is at least 40 but below 70, and `LOW` below 40. Whenever any recomputation lands a student in the `HIGH` tier, the system sets `advising_required_flag` to true and recomputes the student's `advising_requirement_status` and `registration_clearance` — the mechanism detailed in §3.8. The score and tier recompute on student creation and `gpa` changes, on referral intake and closure, on intervention creation and closure, on hold placement and release, and whenever an appointment is marked `NO_SHOW`.

Term rollover is a director-only update that may change `current_term_code`, `advising_required_flag`, `care_status` (one of `ENROLLED`, `ON_LEAVE`, or `INACTIVE`), or `gpa`. When the term changes while the student is `ENROLLED` and the new term is not yet listed, the system appends it to `enrolled_term_codes`, building the enrollment history that retention reporting later reads; a `gpa` change recomputes the score and tier. Every such student update increments the student's `version` by 1. The student directory supports filtering by `major_code`, `cohort_year`, `risk_tier`, and `care_status`.

### 3.3. Assigning Advisors: Manual Placement, Supersession, and the Selector Policy

Manual placement is a director operation whose payload names the `student_id`, the `advisor_id`, and the `expected_student_version` guard described in §2.9. Validation proceeds in the global order of §2.10: the student and advisor must exist (`ERR_STUDENT_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`); the version guard fires next (`ERR_STALE_VERSION`); then the student's `care_status` must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`); and finally the business eligibility checks — the advisor must be `ACTIVE` (`ERR_ADVISOR_NOT_ACTIVE`), the student's `major_code` must appear among the advisor's `major_codes` (`ERR_MAJOR_NOT_SERVED`), and the advisor must have headroom, meaning `assigned_active_count` strictly below `max_caseload`. An advisor whose count already equals the cap is at capacity, and the creation is rejected with `ERR_ADVISOR_AT_CAPACITY`.

Assignment creation follows a create-with-supersede discipline. If the student already has an `ACTIVE` assignment, that incumbent is ended as part of the same operation — its status becomes `ENDED` with `ended_reason` set to `SUPERSEDED` — and the new assignment begins `ACTIVE` with `assignment_mode` recording `MANUAL`. Both affected advisors have `assigned_active_count` and `weighted_load` recomputed, and the student's `version` increments by 1: the superseding creation is precisely the event the optimistic-concurrency guard protects later writers against. While an assignment is `ACTIVE`, its `ended_reason` is null.

The selector policy offers an alternative: auto-assignment, requested with just a `student_id` and an optional `ranking_mode`. The candidate pool contains exactly those advisors who are `ACTIVE`, serve the student's major, and have headroom; an empty pool is rejected with `ERR_NO_ELIGIBLE_ADVISOR` (HTTP 422, distinct from the 409s surrounding it). Under the default `WEIGHTED` mode, the winner is the candidate with the lowest `weighted_load`, with ties broken by lower `assigned_active_count` and then by earlier `created_at`. Under `HEADCOUNT` mode, the primary ranking is the lowest `assigned_active_count`, with ties broken by lower `weighted_load` and then by earlier `created_at`. Under either mode, if `created_at` also ties — as it does whenever the candidates were created without an intervening advance of the logical clock — the winner is the candidate whose `id` is smallest in ascending string order. The chosen advisor receives a new `ACTIVE` assignment with `assignment_mode` set to `AUTO`; the same supersede discipline applies to any incumbent, the same load recomputations fire, and the student's `version` increments by 1.

Ending an assignment is the compensating director action for correcting a placement. The target must exist (`ERR_ASSIGNMENT_NOT_FOUND`) and must be `ACTIVE`; ending an assignment that is not active is rejected with `ERR_ASSIGNMENT_ALREADY_ENDED`. A successful ending sets the status to `ENDED` with `ended_reason` set to `MANUAL_END`, recomputes the advisor's two load measures, and increments the student's `version` by 1. Assignment history — active and ended alike — can be browsed with `student_id`, `advisor_id`, and `status` filters.

### 3.4. The Appointment Book: Scheduling, Check-In, and Session Outcomes

Booking an appointment — available to `FrontDeskStaff`, an `Advisor`, or the director — takes a payload of `student_id`, `advisor_id`, the `term_code` the session counts toward, and the slot boundaries `scheduled_start_at` and `scheduled_end_at`, both ISO 8601 UTC instants. The slot is a half-open interval: it occupies the time from its start up to but not including its end. The end must be strictly after the start and the duration must be at least 15 and at most 60 minutes, else the booking fails with `ERR_INVALID_APPOINTMENT_DURATION`; the stored `duration_minutes` is the whole-minute difference between the two boundaries. The student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) and the host advisor must be `ACTIVE` (`ERR_ADVISOR_NOT_ACTIVE`) — cross-entity checks that §2.10 evaluates last.

The book cannot be double-booked. The requested interval must not intersect any existing `SCHEDULED` or `CHECKED_IN` appointment of the same advisor; because intervals are half-open, back-to-back slots that merely touch at an endpoint are allowed. A colliding request is rejected with `ERR_APPOINTMENT_OVERLAP`. A successful booking starts in `SCHEDULED`, and the host advisor's `scheduled_minutes` recomputes immediately. The appointment book can be listed with `student_id`, `advisor_id`, `status`, and `term_code` filters, and an unknown appointment reference yields `ERR_APPOINTMENT_NOT_FOUND`.

Check-in is the front desk's exclusive operation. The appointment must be `SCHEDULED` (any other status yields `ERR_APPOINTMENT_INVALID_STATE`), and the current logical time must fall inside the window running from ten minutes before the scheduled start to ten minutes after it, with both boundaries inclusive; outside that window the check-in is rejected with `ERR_OUTSIDE_CHECK_IN_WINDOW`. A successful check-in moves the appointment `SCHEDULED → CHECKED_IN` and stamps `checked_in_at` with the current logical time. A checked-in appointment continues to count toward the advisor's `scheduled_minutes`.

From there a session resolves in one of two directions. Cancellation — by `FrontDeskStaff`, an `Advisor`, or the director — is permitted only from `SCHEDULED` and moves the appointment to `CANCELLED`, removing the slot from `scheduled_minutes`. Completion is permitted only from `CHECKED_IN` and only by the appointment's own advisor — for this operation, ownership means `X-User-ID` equals the appointment's `advisor_id` — or by the director. Completion moves the appointment to `COMPLETED`, removes the slot from `scheduled_minutes`, and, when the appointment's `term_code` equals the student's `current_term_code`, recomputes the student's `advising_requirement_status` and `registration_clearance`: a completed current-term session is what satisfies the advising requirement defined in §3.8. Attempting either transition from the wrong source state yields `ERR_APPOINTMENT_INVALID_STATE`.

A student who never arrives is handled by the close-of-day sweep described in §3.9: every appointment still `SCHEDULED` whose start lies more than ten minutes in the past relative to logical time is marked `NO_SHOW`. Each such marking adds 1 to the student's `no_show_count`, recomputes the student's `at_risk_score` and `risk_tier` — and if the tier becomes `HIGH`, sets `advising_required_flag` to true and recomputes the requirement and clearance — removes the lapsed slot from the host advisor's `scheduled_minutes`, and recomputes the `weighted_load` of the student's assigned advisor when one exists. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

### 3.5. The Drop-In Counter: Daily Queue Discipline

Walk-in traffic enters through queue intake, a `FrontDeskStaff` operation carrying the `student_id` and a free-text `reason` for the visit. The ticket's `queue_date` is the logical calendar date at intake — it is what groups the day's queue — and its `position` is one more than the number of pre-existing tickets sharing that `queue_date`, counting tickets of any status. The position is fixed at creation and never changes; positions are gap-free within a day, creation order and position order always coincide, and a ticket's `id` is never consulted for ordering. A new ticket starts `QUEUED` with `called_by_advisor_id` null.

Two disciplines keep the counter orderly. A student may hold at most one active ticket — `QUEUED` or `CALLED` — per `queue_date`; a second join the same day is rejected with `ERR_STUDENT_ALREADY_HAS_ACTIVE_TICKET`. And the day itself is capped: once the `queue_date` already has 3 active tickets (counting `QUEUED` and `CALLED` together), further intake is rejected with `ERR_QUEUE_CAPACITY_REACHED`, regardless of which students are queuing.

Working the counter, an `Advisor` calls the next student: the system selects the lowest-`position` ticket that is `QUEUED` on the current logical date and moves it `QUEUED → CALLED`, stamping `called_by_advisor_id` with the calling advisor's `id` — the caller's own `X-User-ID`. When no `QUEUED` ticket exists for the current logical date, the call is rejected with `ERR_QUEUE_EMPTY`. The called visit then concludes one of two ways: the advisor or the director marks it served, moving `CALLED → SERVED`, or the student departs — recorded by `FrontDeskStaff`, an `Advisor`, or the director — which moves a ticket from `QUEUED` or `CALLED` to `LEFT`. Serving a ticket that is not `CALLED`, or recording a departure for a ticket not in `QUEUED` or `CALLED`, is rejected with `ERR_TICKET_INVALID_STATE`; an unknown ticket reference yields `ERR_TICKET_NOT_FOUND`. `SERVED` and `LEFT` are terminal.

Queue state does not leak across days. The close-of-day sweep moves every ticket still `QUEUED` whose `queue_date` predates the current logical date to `LEFT`. The ticket ledger can be listed with `student_id`, `called_by_advisor_id`, `status`, and `queue_date` filters.

### 3.6. Early-Alert Referrals and the Outreach Protocol

Early-alert intake is how the faculty raises a flag. A `FacultyReferrer` or the director files a referral with the `student_id`, a `source` of `FACULTY` or `STAFF`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a free-text `reason`. The new referral starts `OPEN` with `attempt_count` at 0, and its `due_at` is computed at creation as the creation time plus the severity's service level: 2 days for `HIGH`, 5 days for `MEDIUM`, 10 days for `LOW`, at second precision. Intake immediately recomputes the student's `at_risk_score` and `risk_tier`, because the new referral's severity boost joins the pool described in §3.2.

The `is_sla_breached` flag tracks the service level against the logical clock: it is true when the current logical time is strictly later than `due_at` and the referral is in a state other than `RESPONDED` or `CLOSED`. At the exact `due_at` instant the referral is not yet breached — the comparison is strict. The flag is recomputed on every referral read and again during the daily close, and the referral list can be filtered by `student_id`, `status`, `severity`, or `is_sla_breached`.

Outreach is the assigned advisor's (or the director's) response protocol. Each logged attempt carries an `outcome` — `NO_ANSWER` or `REACHED` — and an optional `note`. Attempts are loggable only while the referral is `OPEN`, `OUTREACH_IN_PROGRESS`, or `NO_RESPONSE`; against any other status the call is rejected with `ERR_REFERRAL_INVALID_STATE`, and an unknown referral reference yields `ERR_REFERRAL_NOT_FOUND`. Every logged attempt increments `attempt_count` by 1. A `NO_ANSWER` outcome cycles the referral through its working states: `OPEN → OUTREACH_IN_PROGRESS`, `OUTREACH_IN_PROGRESS → NO_RESPONSE`, and `NO_RESPONSE → OUTREACH_IN_PROGRESS`. A `REACHED` outcome moves the referral to `RESPONDED` from any of those three working states.

The protocol tolerates at most three attempts. When a `NO_ANSWER` would bring `attempt_count` to 3, the normal cycle does not apply: the referral is instead auto-escalated, its `attempt_count` is set to 3 as part of the same outreach call, and the escalation cascade below fires.

Escalation converts a stuck referral into a concrete intervention. The director may escalate any referral in `OPEN`, `OUTREACH_IN_PROGRESS`, or `NO_RESPONSE`, optionally attaching a `reason`; the state guard is the same `ERR_REFERRAL_INVALID_STATE`. Manual escalation and auto-escalation fire an identical four-step cascade. First, an intervention is created for the referred student with `referral_id` pointing at this referral, `intervention_type` set to `ACADEMIC_COACHING`, and status `OPEN`. Second, that creation recomputes the student's `at_risk_score` — ten points for the new `OPEN` intervention — which may flip the `risk_tier`. Third, if the tier becomes `HIGH`, the system sets `advising_required_flag` to true and recomputes `advising_requirement_status`, which becomes `REQUIRED` absent a completed current-term appointment, and `registration_clearance`, which becomes `BLOCKED`. Fourth, the student's assigned advisor, when one exists, has `weighted_load` recomputed to reflect the moved risk weight.

Closure ends the file. A referral in `RESPONDED` or `ESCALATED` may be closed by the assigned advisor or the director, moving it to `CLOSED`; closure from any other state is rejected with `ERR_REFERRAL_INVALID_STATE`. Closing recomputes the student's `at_risk_score` — when the closed referral had been supplying the maximum severity boost, that boost leaves the pool. `CLOSED` is terminal.

### 3.7. Interventions and Risk-Driven Follow-Up

Beyond the escalation cascade, interventions are also opened directly. The assigned advisor or the director creates one with the `student_id`, an optional `referral_id` linking the intervention to its originating referral (which must exist when supplied, else `ERR_REFERRAL_NOT_FOUND`), an `intervention_type` of `ACADEMIC_COACHING`, `TUTORING_REFERRAL`, `COUNSELING_REFERRAL`, or `FINANCIAL_AID_REFERRAL`, and an optional free-text `note`. A new intervention starts `OPEN` with `outcome` null.

Creation is itself a risk event. Each `OPEN` intervention contributes ten points to the student's `at_risk_score`, so creation recomputes the score and may flip the `risk_tier` to `HIGH` — which, as always, sets `advising_required_flag` to true and recomputes `advising_requirement_status` and `registration_clearance` — and the student's assigned advisor, when one exists, has `weighted_load` recomputed.

Follow-up ends with a recorded result. The assigned advisor or the director closes an intervention by supplying an `outcome` of `SUCCESSFUL` or `UNSUCCESSFUL`. Only an `OPEN` intervention may be closed — otherwise the request is rejected with `ERR_INTERVENTION_ALREADY_CLOSED`, and an unknown intervention reference yields `ERR_INTERVENTION_NOT_FOUND`. Closing records the outcome, sets the status to `CLOSED`, removes the ten-point weight from the student's score, and refreshes the assigned advisor's `weighted_load`. The intervention register supports `student_id`, `referral_id`, and `status` filters.

### 3.8. Registration Holds, Degree Plans, and Clearance to Register

A registration hold is the center's lever over enrollment. An `AdvisingDirector` places a hold under the student with a `hold_type` of `ADVISING`, `FINANCIAL`, `ACADEMIC_STANDING`, or `ADMINISTRATIVE`, and an optional `requires_approved_plan` flag that defaults to false. The new hold starts `ACTIVE`; the student's `registration_clearance` recomputes at once — any `ACTIVE` hold forces `BLOCKED` — and the `at_risk_score` gains 8 points per `ACTIVE` hold, with the usual tier consequences. A student's holds can be listed with a `status` filter.

Release is the gated reverse. It may be performed by the student's assigned advisor or by the director; any other `Advisor`-role caller is rejected with `ERR_NOT_ASSIGNED_ADVISOR`. The hold must exist under the path student (`ERR_HOLD_NOT_FOUND`) and must be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`). When the hold's `requires_approved_plan` is true, the student must have a degree plan in `APPROVED`; without one the release is rejected with `ERR_PLAN_NOT_APPROVED` — a cross-entity check that §2.10 places after the state and ownership checks, so a release that fails both ownership and the plan gate reports `ERR_NOT_ASSIGNED_ADVISOR`. A successful release moves the hold `ACTIVE → RELEASED` and cascades: `registration_clearance` recomputes and becomes `CLEARED` exactly when no `ACTIVE` holds remain and the advising requirement is not `REQUIRED`, and the released hold's 8 points leave the `at_risk_score`.

The two computed student fields behind all of this are defined as follows. `advising_requirement_status` is `NOT_REQUIRED` when `advising_required_flag` is false; otherwise it is `SATISFIED` when a `COMPLETED` appointment exists for the student in the student's `current_term_code`, and `REQUIRED` when none does. `registration_clearance` is `BLOCKED` whenever any of the student's holds is `ACTIVE`; failing that, it is `BLOCKED` when the advising requirement is `REQUIRED`; otherwise it is `CLEARED`. Both recompute on hold placement and release, on every advising-requirement recomputation, and on degree-plan approval.

The degree plan itself is the student's term-by-term map. The assigned advisor or the director creates one under the student with a `catalog_year`, a `required_credits` total (at least 1, else `ERR_VALIDATION`), and `terms`: a list of term entries, each carrying a `term_code` and a `courses` list whose entries name a `course_code` and its `credits`. A student who already has a plan in `DRAFT` or `SUBMITTED` may not open another — the attempt is rejected with `ERR_PLAN_ALREADY_ACTIVE`. All degree-plan writes by an `Advisor`-role caller require the caller to be the student's assigned advisor, with violations rejected as `ERR_NOT_ASSIGNED_ADVISOR`; an `AdvisingDirector` performs them without that restriction. A new plan starts in `DRAFT` with `mapped_credits_total` computed immediately.

That total obeys a pinned rounding order. For each term in `terms`, the system sums the course credits and rounds that term's sum half-up to a whole number; `mapped_credits_total` is then the sum of those per-term integers. Rounding each term first and then summing is mandatory — the sum-then-round alternative is rejected: two terms of 10.5 credits each map to 11 plus 11, a total of 22, under the pinned order, whereas summing first would round 21.0 to 21. While the plan remains in `DRAFT`, the advisor may revise `terms` or `required_credits`, and `mapped_credits_total` recomputes on each edit; editing a plan that is no longer `DRAFT` is rejected with `ERR_PLAN_INVALID_STATE`.

Submission moves the plan from `DRAFT` to `SUBMITTED` and is guarded by two gates beyond the state check: `mapped_credits_total` must be at least `required_credits`, else `ERR_PLAN_CREDITS_INSUFFICIENT`, and every term's rounded credit total must not exceed 18, else `ERR_PLAN_TERM_OVERLOAD`. Approval — again the assigned advisor or the director — moves `SUBMITTED → APPROVED` and recomputes the student's `registration_clearance`, since the plan gate for `requires_approved_plan` holds is now satisfiable. When the plan needs more work, returning it moves `SUBMITTED → DRAFT` and requires a `reason`. Any transition attempted from the wrong source state is rejected with `ERR_PLAN_INVALID_STATE`; `APPROVED` is terminal. An unknown plan reference under the path student yields `ERR_PLAN_NOT_FOUND`, and a student's plans can be listed with a `status` filter.

### 3.9. Advising Notes, Retention Reporting, and the Daily Close

Notes are the advising record's narrative layer. An `Advisor` or the director authors a note under the student with a `visibility` of `SHARED` or `CONFIDENTIAL` and a `body`; the body is immutable once written — the API offers no note-update capability. The system records the caller as `author_user_id`, copying the request's `X-User-ID`: the acting Advisor's `id` when the role is `Advisor`, or the opaque director identifier otherwise; it is not a foreign key. The student must not be `INACTIVE` — attempts against an inactive student are rejected with `ERR_STUDENT_INACTIVE`, while `ON_LEAVE` students may still receive notes. A `CONFIDENTIAL` note may be authored only by the student's assigned advisor or by the director; any other `Advisor`-role caller attempting one is rejected with `ERR_NOTE_CONFIDENTIALITY_RESTRICTED`. A `SHARED` note may be authored by any `Advisor` or the director.

Reading notes respects the same boundary. The note list — available to an `Advisor` or the director, with an optional `visibility` filter — is filtered server-side: `CONFIDENTIAL` notes are visible only to their author and to `AdvisingDirector` callers, while `SHARED` notes are visible to both roles.

Retention reporting is the director's outcome instrument, run with a required `variant` selector. The `COHORT_PERSISTED` variant requires `cohort_year`: the denominator counts every student of that entry cohort, and the numerator counts those among them currently `ENROLLED`. The `TERM_OVER_TERM` variant requires `from_term_code` and `to_term_code`, with `cohort_year` as an optional further filter: the pool is all students of any `care_status` whose `enrolled_term_codes` history contains the from-term — restricted to the cohort when `cohort_year` is supplied — the denominator is the pool's size, and the numerator counts pool members whose history also contains the to-term. The response carries `variant`, `cohort_year`, `numerator`, `denominator`, and `rate`, where the rate is the numerator divided by the denominator, rendered to four decimal places with round-half-up; when the denominator is 0, the rate and numerator are both reported as 0.

The daily close is the director's end-of-day sweep, and it performs two lapses at once. Every appointment still `SCHEDULED` whose start lies more than ten minutes in the past is marked `NO_SHOW`, firing the full no-show cascade of §3.4 — the incremented `no_show_count`, the risk recomputation, the possible `HIGH`-tier flag and clearance changes, and the advisor load refreshes. And every drop-in ticket still `QUEUED` from an earlier `queue_date` is marked `LEFT`. The sweep's response reports the two tallies as `no_show_marked` and `queue_expired`. The close is also one of the moments the referral `is_sla_breached` flag is refreshed against the logical clock.

## 4. Endpoint Definitions

Endpoints that create a new resource return a `201 Created` status code. Endpoints that modify an existing resource, drive a state transition, or perform an operational action return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | AdvisingDirector |
| POST | `/advising/advisors` | Create an advisor | AdvisingDirector |
| GET | `/advising/advisors` | List advisors | AdvisingDirector, Advisor, FrontDeskStaff |
| GET | `/advising/advisors/{advisorId}` | Get an advisor with computed load fields | AdvisingDirector, Advisor, FrontDeskStaff |
| PATCH | `/advising/advisors/{advisorId}` | Update advisor status or capacity | AdvisingDirector |
| POST | `/advising/students` | Register a student | AdvisingDirector, FrontDeskStaff |
| GET | `/advising/students` | List students | AdvisingDirector, Advisor, FrontDeskStaff, FacultyReferrer |
| GET | `/advising/students/{id}` | Get a student with computed risk fields | AdvisingDirector, Advisor, FrontDeskStaff |
| PATCH | `/advising/students/{id}` | Update student term, flag, care status, or GPA | AdvisingDirector |
| POST | `/advising/advisor-assignments` | Create a manual assignment (create-with-supersede, OCC) | AdvisingDirector |
| POST | `/advising/advisor-assignments/auto-assign` | Selector-policy assignment | AdvisingDirector |
| GET | `/advising/advisor-assignments` | List assignments | AdvisingDirector, Advisor, FrontDeskStaff |
| GET | `/advising/advisor-assignments/{assignmentId}` | Get an assignment | AdvisingDirector, Advisor, FrontDeskStaff |
| POST | `/advising/advisor-assignments/{assignmentId}/end` | End an ACTIVE assignment | AdvisingDirector |
| POST | `/advising/appointments` | Book an appointment | FrontDeskStaff, Advisor, AdvisingDirector |
| GET | `/advising/appointments` | List appointments | AdvisingDirector, Advisor, FrontDeskStaff |
| GET | `/advising/appointments/{appointmentId}` | Get an appointment | AdvisingDirector, Advisor, FrontDeskStaff |
| POST | `/advising/appointments/{appointmentId}/check-in` | Check in a SCHEDULED appointment | FrontDeskStaff |
| POST | `/advising/appointments/{appointmentId}/cancel` | Cancel a SCHEDULED appointment | FrontDeskStaff, Advisor, AdvisingDirector |
| POST | `/advising/appointments/{appointmentId}/complete` | Complete a CHECKED_IN appointment | Advisor, AdvisingDirector |
| POST | `/advising/dropin-tickets` | Join today's drop-in queue | FrontDeskStaff |
| GET | `/advising/dropin-tickets` | List drop-in tickets | AdvisingDirector, Advisor, FrontDeskStaff |
| GET | `/advising/dropin-tickets/{ticketId}` | Get a drop-in ticket | AdvisingDirector, Advisor, FrontDeskStaff |
| POST | `/advising/dropin-tickets/call-next` | Call the next queued ticket | Advisor |
| POST | `/advising/dropin-tickets/{ticketId}/complete` | Mark a CALLED ticket served | Advisor, AdvisingDirector |
| POST | `/advising/dropin-tickets/{ticketId}/leave` | Student leaves the queue | FrontDeskStaff, Advisor, AdvisingDirector |
| POST | `/advising/referrals` | Intake an early-alert referral | FacultyReferrer, AdvisingDirector |
| GET | `/advising/referrals` | List referrals | AdvisingDirector, Advisor, FacultyReferrer |
| GET | `/advising/referrals/{referralId}` | Get a referral | AdvisingDirector, Advisor, FacultyReferrer |
| POST | `/advising/referrals/{referralId}/outreach` | Log an outreach attempt | Advisor, AdvisingDirector |
| POST | `/advising/referrals/{referralId}/escalate` | Manually escalate a referral | AdvisingDirector |
| POST | `/advising/referrals/{referralId}/close` | Close a RESPONDED or ESCALATED referral | Advisor, AdvisingDirector |
| POST | `/advising/interventions` | Create an intervention manually | Advisor, AdvisingDirector |
| GET | `/advising/interventions` | List interventions | AdvisingDirector, Advisor |
| GET | `/advising/interventions/{interventionId}` | Get an intervention | AdvisingDirector, Advisor |
| POST | `/advising/interventions/{interventionId}/close` | Close an OPEN intervention with an outcome | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/holds` | Place a registration hold | AdvisingDirector |
| GET | `/advising/students/{id}/holds` | List a student's holds | AdvisingDirector, Advisor, FrontDeskStaff |
| POST | `/advising/students/{id}/holds/{holdId}/release` | Release an ACTIVE hold | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/degree-plans` | Create a DRAFT degree plan | Advisor, AdvisingDirector |
| GET | `/advising/students/{id}/degree-plans` | List a student's degree plans | AdvisingDirector, Advisor, FrontDeskStaff |
| GET | `/advising/students/{id}/degree-plans/{planId}` | Get a degree plan | AdvisingDirector, Advisor, FrontDeskStaff |
| PATCH | `/advising/students/{id}/degree-plans/{planId}` | Edit a DRAFT plan's terms or credits | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/degree-plans/{planId}/submit` | Submit a DRAFT plan | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/degree-plans/{planId}/approve` | Approve a SUBMITTED plan | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/degree-plans/{planId}/return` | Return a SUBMITTED plan to DRAFT | Advisor, AdvisingDirector |
| POST | `/advising/students/{id}/notes` | Add an advising note | Advisor, AdvisingDirector |
| GET | `/advising/students/{id}/notes` | List a student's notes | AdvisingDirector, Advisor |
| GET | `/advising/reports/retention` | Retention report | AdvisingDirector |
| POST | `/advising/ops/daily-close` | Close-of-day sweep | AdvisingDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_APPOINTMENT_DURATION` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_ADVISOR` | 403 Forbidden |
| `ERR_NOTE_CONFIDENTIALITY_RESTRICTED` | 403 Forbidden |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_ADVISOR_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_INTERVENTION_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STUDENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_STUDENT_INACTIVE` | 409 Conflict |
| `ERR_ADVISOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_ADVISOR_AT_CAPACITY` | 409 Conflict |
| `ERR_MAJOR_NOT_SERVED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_ADVISOR` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_ALREADY_ENDED` | 409 Conflict |
| `ERR_APPOINTMENT_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_CHECK_IN_WINDOW` | 409 Conflict |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_QUEUE_CAPACITY_REACHED` | 409 Conflict |
| `ERR_STUDENT_ALREADY_HAS_ACTIVE_TICKET` | 409 Conflict |
| `ERR_QUEUE_EMPTY` | 409 Conflict |
| `ERR_TICKET_INVALID_STATE` | 409 Conflict |
| `ERR_REFERRAL_INVALID_STATE` | 409 Conflict |
| `ERR_INTERVENTION_ALREADY_CLOSED` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_PLAN_CREDITS_INSUFFICIENT` | 409 Conflict |
| `ERR_PLAN_TERM_OVERLOAD` | 409 Conflict |
