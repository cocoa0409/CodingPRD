# Community College Contract Training API — Product Requirements Document

## 1. Introduction

A community college's workforce division sells customized contract training to regional employers. The commercial motion is long and collaborative: a coordinator assesses an employer's skill gaps, assembles a tailored curriculum, quotes a price, survives a negotiation loop, secures a signature, schedules cohorts of employees through venue-bound sessions, staffs those sessions with credentialed instructors, and finally reports employment outcomes back to the employer. Running alongside that motion is a second pipeline built on public money: state training grants can offset a share of eligible training cost, but only when applications are filed inside statutory windows, awards are reserved against a finite appropriation, and reimbursement is claimed against actual completion evidence rather than estimates.

This document specifies the REST API that backs both pipelines. Three tensions shape the design. First, money appears twice — once on the employer-facing invoice and once in the grant ledger — and the two views must never disagree. Second, compliance is not advisory: an instructor may not be confirmed to teach a session unless their credentials provably cover the curriculum, and the person who proposes a staffing decision may never be the one who approves it. Third, the lifecycle is long-lived, so quotes expire, assessments are revised mid-negotiation, and clients holding a stale view of an agreement or a cohort must be stopped from overwriting decisions they never observed. All resources are mounted under the `/ct` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are accepted, the caller's role must be listed among the roles authorized for the target endpoint, and any entity-backed ownership rule must hold; a failure here is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Seven roles exist. `CollegeAdmin` is the workforce-division administrator: it owns configuration (grant programs, venues, instructors), approves needs assessments and outcome reports, and is the only role allowed to set the logical clock. `WorkforceCoordinator` runs the employer pipeline — assessments, agreements, quotes, cohorts, sessions, rosters — proposes instructor assignments, and submits and claims grant applications. `CredentialOfficer` is the compliance gate for instructor credentialing: it confirms assignments and issues completion credentials. `GrantOfficer` is the state grant counterpart: it reviews, returns, approves, and denies applications and marks reimbursements paid. `EmployerContact` is the employer-side signatory: it negotiates and signs agreements for the employer it belongs to, and its read access is scoped to its own employer. `BillingClerk` generates, issues, settles, and voids cohort invoices. `Instructor` delivers sessions and closes attendance. All roles may call every read endpoint.

Identity binding differs by role. When `X-User-Role` is `EmployerContact`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's foreign-key field — on a training agreement, its `employer_id` — to `X-User-ID`. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; the attendance-closure check compares the `instructor_id` of a `CONFIRMED` or `COMPLETED` assignment on the session to `X-User-ID`. For the remaining five roles — `CollegeAdmin`, `WorkforceCoordinator`, `CredentialOfficer`, `GrantOfficer`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proposed_by_user_id` or `approved_by_user_id` on an instructor assignment) but does not compare it to any entity's `id`.

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

Every list endpoint accepts the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A `limit` below 1, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST`; a `limit` above 100 is clamped to 100 rather than rejected. List results are always sorted by `created_at` ascending. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every resource in the system carries four server-managed common properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` refreshes on every mutation. `version` is an integer maintained per resource: it starts at one when the resource is created and increments by one on every mutation of that resource, whether the mutation comes from a direct call or from a cascade, and it anchors the optimistic-concurrency rules of §2.6.

### 2.5. The Logical Clock

Quote expiry, grant windows, claim deadlines, employer dormancy, and credential expiry all read a single logical clock rather than wall-clock time. Before any clock call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A `CollegeAdmin` advances it through a test-driving capability that accepts a `to_iso8601` instant and responds with the current time as `now`; advancing the clock runs the dormancy and grant-expiry sweeps described in §3.9.

### 2.6. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, and both use the same rejection.

- The quote-revision endpoint (`POST /ct/training-agreements/{id}/revise`) requires the request body to carry `expected_agreement_version`, holding the caller's last-observed `version` of the agreement. If that value does not match the agreement's current `version` — because another writer has advanced it since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from overwriting a quote round it never saw.
- The grant-application creation endpoint (`POST /ct/cohorts/{id}/grant-applications`) requires the request body to carry `expected_cohort_version`, holding the caller's last-observed `version` of the cohort. A mismatch with the cohort's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Because award math is computed from cohort state — the roster size and the agreement quote — a writer whose view of the cohort predates the latest roster or schedule mutation would otherwise compute against superseded inputs.

Endpoints not named here do not accept a version field.

### 2.7. Monetary Precision and Rounding Discipline

All money is integer cents. Where a computation produces a fraction, the rounding rule is round half up to whole cents, applied exactly where each rule says it is applied and nowhere else. The quote applies a single rounding immediately after the rush uplift. Invoice lines round each component per line and then sum whole-cent line totals; rounding the sum of unrounded lines is expressly forbidden because it yields a different cent total. Grant share ceilings use the whole-cent floor of the relevant product. Percentages that surface on resources — `attendance_pct` on a participant and `placement_pct` on an outcome report — are rounded half up to two decimal places, and threshold comparisons are made against the rounded value, not the raw quotient. Instructor `committed_hours` values are running sums of the underlying session `hours` figures and keep those figures' precision (session `hours` are derived to six decimal places, per §3.4).

### 2.8. Request Validation Pipeline and Nested Path Resolution

Incoming requests are validated in a fixed priority order, and the first failing check produces the error response. The order is:

1. Presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization and entity-backed ownership (`ERR_FORBIDDEN_FOR_ROLE`).
3. Existence of every path identifier, validated left-to-right along the URL — on a nested path such as an employer's child resource, the employer is verified first, then the child, and the first missing link produces `ERR_NOT_FOUND`.
4. Request-body shape: required fields present, types valid, enum values inside their domain, `end_at` strictly after `start_at`, recorded attendance hours no greater than the session's `hours`, counts positive, and resource identifiers carried in the body — such as `needs_assessment_id`, `campus_venue_id`, `venue_id`, `program_id`, or `instructor_id` — resolving to existing records (`ERR_INVALID_REQUEST`).
5. Generic state legality: the target entity must be in a state from which the requested transition exists (`ERR_INVALID_STATE`), which also covers duplicate transitions and terminal lockdown — with one exception: an operation that targets a training agreement already in `COMPLETED` or `CANCELLED` is rejected with `ERR_AGREEMENT_TERMINAL` as §3.2 states, not with `ERR_INVALID_STATE`.
6. Cross-entity state gates: `ERR_AGREEMENT_NOT_SIGNED`, `ERR_ASSESSMENT_NOT_APPROVED`, `ERR_COHORT_NOT_CREDENTIALED`, `ERR_GRANT_PROGRAM_NOT_OPEN`, `ERR_AGREEMENT_TERMINAL`, `ERR_INVOICE_VARIANT_NOT_ALLOWED`, `ERR_SESSION_NOT_PLANNED`, `ERR_ATTENDANCE_ALREADY_CLOSED`, and `ERR_INVOICE_NOT_PAYABLE`.
7. Credential compliance and duty segregation at assignment confirmation: `ERR_CREDENTIAL_EXPIRED`, `ERR_CREDENTIAL_MISMATCH`, `ERR_SEGREGATION_OF_DUTIES`.
8. Temporal windows and overlaps: `ERR_QUOTE_EXPIRED`, `ERR_GRANT_WINDOW_CLOSED`, `ERR_INSTRUCTOR_DOUBLE_BOOKED`, `ERR_VENUE_OVERLAP`.
9. Reference integrity: `ERR_STALE_ASSESSMENT`, `ERR_STALE_VERSION`, `ERR_DUPLICATE_PARTICIPANT`, `ERR_DELIVERY_MODE_MISMATCH`, and the referential uses of `ERR_INVALID_REQUEST` (a duplicate open application per cohort and program, or a cohort count that has reached the agreement's ceiling).
10. Capacity and threshold constraints: `ERR_BELOW_MIN_ENROLLMENT`, `ERR_VENUE_CAPACITY_EXCEEDED`, `ERR_NO_COMPLETERS`.
11. Fiscal capacity: `ERR_GRANT_CAPACITY_EXCEEDED`.

Because of this ordering, a request that fails both an earlier and a later check always reports the earlier one: a call with a missing role header and a stale version reports `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, never `ERR_STALE_VERSION`.

### 2.9. Delivery Modes, Venues, and Scheduling Integrity

Delivery happens either at the employer's premises or at a college facility, and venues are typed to match. A venue's `kind` is either `EMPLOYER_SITE` or `CAMPUS_LAB`; the delivery modes `ON_SITE` and `ON_CAMPUS` line up with them, so `ON_CAMPUS` delivery requires a `CAMPUS_LAB` venue and `ON_SITE` delivery requires an `EMPLOYER_SITE` venue. Any inconsistency between a cohort's mode and its agreement's mode, or between a session's venue kind and its cohort's mode, is rejected with `ERR_DELIVERY_MODE_MISMATCH`.

Venue bookings follow closed-interval semantics with a turnover buffer. Each venue carries `turnover_buffer_minutes`, fixed at thirty minutes, as the required gap between consecutive bookings. Only bookings in `PLANNED` or `HELD` status count as existing bookings; a cancelled session frees its venue. A new session conflicts with an existing booking of the same venue when the buffer-extended windows intersect — the new session's `start_at` falls before the existing booking's `end_at` plus the buffer and the existing booking's `start_at` falls before the new session's `end_at` plus the buffer; the boundaries are open, so starting exactly at the end of the buffer — precisely thirty minutes after the previous end — or ending exactly the buffer before the next booking's start is allowed. Conflicts are rejected with `ERR_VENUE_OVERLAP`. A venue's seat `capacity` is enforced for `CAMPUS_LAB` venues at cohort launch time, and its `hourly_cost_cents` feeds the campus-delivery term of the quote.

### 2.10. The Grant Fund Ledger

Each grant program is a fund pool with four ledger figures: `reserved_cents`, `committed_cents`, `reimbursed_cents`, and `available_cents`, all in whole cents against the program's `appropriation_cents`. The reserved figure is the sum of `reserved_cents` over the program's applications in `APPROVED` status; the committed figure is the sum of `committed_cents` over applications in `CLAIMED`; the reimbursed figure is the sum of `reimbursed_cents` over applications in `PAID`. The available figure is whatever remains: the appropriation minus reserved, minus committed, minus reimbursed. These definitions imply a standing invariant — available plus reserved plus committed plus reimbursed always equals the appropriation — so an approval followed by its compensating release (a withdrawal or an expiry) leaves the four-figure tuple unchanged.

### 2.11. Parallel Status Dimensions and Cascade Consistency

Training agreements and cohorts each carry two independent status dimensions. An agreement's `contract_status` walks `DRAFT`, `QUOTED`, `NEGOTIATING`, `SIGNED`, `IN_DELIVERY`, and the terminal `COMPLETED` or `CANCELLED`, while its `billing_status` walks `UNBILLED`, `PARTIALLY_BILLED`, and `SETTLED`; the two evolve independently. A cohort's `delivery_status` walks `SCHEDULED`, `LAUNCHED`, `IN_PROGRESS`, `DELIVERED`, and the terminal `CREDENTIALED` or `CANCELLED`, while its `billing_status` walks `UNBILLED`, `INVOICED`, and `PAID`, again independently. Cancellations propagate down the hierarchy — agreement to cohort, cohort to session, session to assignment — and sideways into grant applications and invoices; whenever a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments exactly as a direct mutation would.

## 3. Business Logic & Workflows

### 3.1. Employer Onboarding and Needs Assessment

A `CollegeAdmin` or a `WorkforceCoordinator` opens a commercial relationship by creating an employer record from its `legal_name`, `industry_code`, and `contact_email`. New employers start as `PROSPECT`, with both rollup figures — `lifetime_billed_cents` and `follow_on_pipeline_cents` — at zero. The employer's `status` later moves to `ACTIVE` on the first signature of any of its agreements, can fall to `DORMANT` through the clock sweep of §3.9, and returns to `ACTIVE` on any subsequent signature.

Against an employer, a `WorkforceCoordinator` drafts a needs assessment carrying a `title`, a list of `skill_gaps`, a list of `target_roles`, and the customized `curriculum_modules` — each module a code, an hours figure, and a list of `required_credential_codes` that will later drive instructor matching. The assessment starts in `DRAFT` with `revision_round` at zero. Submission by a `WorkforceCoordinator` moves it to `SUBMITTED` and requires the curriculum to be non-empty; submitting an assessment with no modules is rejected with `ERR_INVALID_REQUEST`.

Review belongs to a `CollegeAdmin`. Approval moves the assessment from `SUBMITTED` to `APPROVED` and stamps `approved_at` with the current time. Requesting revision instead moves it to `REVISION_REQUESTED` — the request may carry explanatory `notes` — and increments `revision_round` by one, tracking the number of completed revision cycles. A revised assessment returns from `REVISION_REQUESTED` to `SUBMITTED` through the same submission action, under the same non-empty-curriculum rule (`ERR_INVALID_REQUEST`), so the loop can repeat until approval.

### 3.2. Quoting, Negotiation, and Signature

With an approved assessment in hand, a `WorkforceCoordinator` creates a training agreement under the employer. The creation payload names the `needs_assessment_id` it builds on — which must reference an assessment of the same employer (otherwise `ERR_INVALID_REQUEST`) — along with the `pricing_model` (`PER_PARTICIPANT` or `FLAT_COHORT`), the `delivery_mode` (`ON_SITE` or `ON_CAMPUS`), the estimated scale as `est_participant_count` and `est_delivery_hours`, the `target_start_date`, the maximum cohort count `max_cohorts`, and, for campus delivery, an optional `campus_venue_id`. At creation the server pins `assessment_version_pinned` to the assessment's current `version`, starts `negotiation_round` at zero, leaves `quoted_total_cents` at zero until the first quote, and sets `contract_status` to `DRAFT` and `billing_status` to `UNBILLED`.

Quoting moves the agreement from `DRAFT` to `QUOTED` and is gated on approval: if the linked assessment is not `APPROVED`, the attempt fails with `ERR_ASSESSMENT_NOT_APPROVED`. A successful quote stamps `quote_issued_at` with the current time and sets `quote_expires_at` thirty days later. The quoted total is computed from the agreement's own estimates — the quote is forward-looking and reads no cohort or session rows — in a pinned evaluation order: tuition and materials first, then the delivery-mode adjustment, then the rush uplift with its single rounding, then the floor.

Under `PER_PARTICIPANT`, tuition is tiered and marginal: each of the first ten estimated participants costs 45,000 cents of tuition, each of the next fifteen — participants eleven through twenty-five — costs 40,000 cents, and every estimated participant beyond the twenty-fifth costs 35,000 cents. Materials then add 7,500 cents per estimated participant, and the per-participant base is the sum of the tiered tuition and the materials. Under `FLAT_COHORT`, the base is instead a flat 480,000 cents that covers up to twelve participants, plus 38,000 cents for each estimated participant beyond the twelfth. Identical inputs produce different totals under the two models.

The delivery mode then adjusts the base. An `ON_SITE` agreement adds a flat surcharge of 25,000 cents. An `ON_CAMPUS` agreement instead adds the product of `est_delivery_hours` and the `hourly_cost_cents` of the campus venue referenced through `campus_venue_id`; when no campus venue was referenced, that term is zero. When fewer than fourteen days separate the quote date from the `target_start_date`, a rush uplift applies: the mode-adjusted base is increased by ten percent, with the product rounded half up to whole cents — the quote's only rounding step. Finally, the floor applies: `quoted_total_cents` is the greater of the rush-adjusted base and 150,000 cents.

Negotiation is a cycle between the employer and the coordinator. An `EmployerContact` requests changes, moving the agreement from `QUOTED` to `NEGOTIATING`; if the quote has already lapsed — the current time is later than `quote_expires_at` — the request fails with `ERR_QUOTE_EXPIRED`. A `WorkforceCoordinator` then revises: the revision call must carry `expected_agreement_version` matching the agreement's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.6. A successful revision moves the agreement from `NEGOTIATING` back to `QUOTED`, increments `negotiation_round` by one, recomputes `quoted_total_cents` through the same pricing rule from whatever revised inputs were supplied — any of `est_participant_count`, `est_delivery_hours`, `pricing_model`, `delivery_mode`, or `target_start_date` may be resent — re-issues the quote window with a fresh `quote_issued_at` and a `quote_expires_at` thirty days out, and increments the agreement's `version` by one.

Signature closes the loop. Signing is an `EmployerContact` action with three gates, evaluated within the pipeline of §2.8: the caller's `X-User-ID` must equal the agreement's `employer_id` (otherwise `ERR_FORBIDDEN_FOR_ROLE`); the quote must still be within its window (otherwise `ERR_QUOTE_EXPIRED`); and the pinned assessment must still be current — `assessment_version_pinned` equal to the assessment's present `version`, with the assessment still `APPROVED` — otherwise the sign fails with `ERR_STALE_ASSESSMENT`. A successful signature moves the agreement from `QUOTED` to `SIGNED`, stamps `signed_at`, and flips the employer from `PROSPECT` or `DORMANT` to `ACTIVE`. When a mid-negotiation curriculum revision has moved the assessment forward, a `WorkforceCoordinator` can re-pin instead: refreshing the pin is allowed while the agreement is in `DRAFT`, `QUOTED`, or `NEGOTIATING`, requires the assessment to be `APPROVED` (otherwise `ERR_ASSESSMENT_NOT_APPROVED`), and sets `assessment_version_pinned` to the assessment's current `version`.

Two automatic transitions complete the contract dimension. The agreement moves from `SIGNED` to `IN_DELIVERY` the moment its first child cohort launches. It moves from `IN_DELIVERY` to `COMPLETED` when an outcome report of the agreement is accepted while every cohort sits in a terminal delivery state — `CREDENTIALED` or `CANCELLED` — and on that same transition the agreement's `billing_status` becomes `SETTLED` when every non-`CANCELLED` cohort has been paid. Operations that target an agreement already in `COMPLETED` or `CANCELLED` are rejected with `ERR_AGREEMENT_TERMINAL`.

### 3.3. Grant Programs and Applications: From Request to Reimbursement

A `CollegeAdmin` configures each state program with a unique `code` (a duplicate code is rejected with `ERR_INVALID_REQUEST`), a display `name`, the fiscal-year `appropriation_cents`, the `max_share_pct` ceiling on the fraction of eligible cost the grant will cover, the per-trainee award ceiling `cap_per_trainee_cents`, the `application_window_end` after which submissions stop, and the `claim_deadline_days` within which an approved award must be claimed. A new program opens in `OPEN` status with all three ledger sums at zero and `available_cents` equal to the full appropriation, and thereafter obeys the ledger invariant of §2.10. The same administrator may suspend a program (`OPEN` to `SUSPENDED`), reopen it (`SUSPENDED` back to `OPEN`), or close it; closing is allowed from either `OPEN` or `SUSPENDED` but only while nothing is encumbered — both the reserved and committed figures must be zero, otherwise the close is rejected with `ERR_INVALID_STATE`. `CLOSED` is terminal.

Applications are filed per cohort. A `WorkforceCoordinator` creates one by naming the `program_id` and the `requested_cents`, and the create call must carry `expected_cohort_version` matching the cohort's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.6, and creation itself increments the cohort's `version` by one. The cohort must be in `SCHEDULED`, `LAUNCHED`, or `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), and at most one open application may exist per cohort and program — open meaning any of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `RETURNED`, `APPROVED`, or `CLAIMED`; a duplicate is rejected with `ERR_INVALID_REQUEST`. A new application starts in `DRAFT`.

Submission — from `DRAFT`, and again from `RETURNED` for resubmission — requires the program to be `OPEN` (otherwise `ERR_GRANT_PROGRAM_NOT_OPEN`) and the current time to be no later than the program's `application_window_end` (otherwise `ERR_GRANT_WINDOW_CLOSED`); each submission stamps `submitted_at` with the latest submission time and lands the application in `SUBMITTED`. A `GrantOfficer` then takes it into `UNDER_REVIEW`, and from there may return it for changes — optionally with `notes` — which cycles it to `RETURNED` for another submission round.

Approval is the reservation point. A `GrantOfficer` approving an application under review first checks that the cohort has not been `CANCELLED` (otherwise `ERR_INVALID_STATE`). The provisional award is then computed on estimated inputs: `provisional_award_cents` is the smallest of three figures — the application's own `requested_cents`, the whole-cent floor of the agreement's `quoted_total_cents` multiplied by the program's `max_share_pct`, and the program's `cap_per_trainee_cents` multiplied by the cohort's `enrolled_count`. If that award exceeds the program's `available_cents`, approval fails with `ERR_GRANT_CAPACITY_EXCEEDED`. On success the application's `reserved_cents` is set to the award, the program's reserved figure increases by the award and its available figure decreases by the same amount, `decided_at` is stamped, and `claim_by` is set to `decided_at` plus the program's `claim_deadline_days`. Denial instead moves the application from `UNDER_REVIEW` to the terminal `DENIED`, stamping `decided_at`, and may carry a `reason`.

Claiming converts the reservation into a commitment against actuals. A `WorkforceCoordinator` may claim only once the cohort has reached `CREDENTIALED` (otherwise `ERR_COHORT_NOT_CREDENTIALED`) and only while the current time is no later than `claim_by` (otherwise `ERR_GRANT_WINDOW_CLOSED`). The final award is recomputed: `final_award_cents` is the smallest of the `requested_cents`, the whole-cent floor of the cohort's `FINAL` invoice gross multiplied by `max_share_pct` — where the relevant invoice is the most recently created of the cohort's `FINAL`-variant invoices in `DRAFT`, `ISSUED`, or `PAID`, and the gross term counts as zero when no such invoice exists — and `cap_per_trainee_cents` multiplied by the cohort's `completer_count`. The program's reserved figure is then reduced by the application's reservation while its available figure grows by the difference between that reservation and the final award; on the application, `committed_cents` becomes the final award and `reserved_cents` returns to zero; the program's committed figure increases by the final award, and `claimed_at` is stamped. Because the final basis uses delivered results, it diverges from the provisional award whenever participants dropped or sessions were cancelled.

Disbursement is the last step: a `GrantOfficer` marks a claimed application paid, moving it from `CLAIMED` to `PAID`; the program's committed figure decreases by the application's committed amount and its reimbursed figure increases by the same amount, while on the application `reimbursed_cents` takes over the committed value and `committed_cents` returns to zero. `PAID` is terminal, as are `DENIED`, `EXPIRED`, and `WITHDRAWN`; the latter two arise from the sweeps and cascades of §3.9.

### 3.4. Cohort Setup, Session Planning, and Rosters

Once an agreement exists, a `WorkforceCoordinator` plans cohorts beneath it. Creating a cohort requires the agreement to be in `QUOTED`, `NEGOTIATING`, `SIGNED`, or `IN_DELIVERY` (otherwise `ERR_INVALID_STATE`); the number of existing cohorts — counted across every status, `CANCELLED` included — must still be below the agreement's `max_cohorts` (a create that would reach the ceiling is rejected with `ERR_INVALID_REQUEST`); and the cohort's `delivery_mode` must equal the agreement's (otherwise `ERR_DELIVERY_MODE_MISMATCH`). The payload also carries `min_enrollment`, the `start_date` and `end_date`, and an optional `venue_id` for the primary delivery venue. A new cohort starts with `delivery_status` `SCHEDULED` and `billing_status` `UNBILLED`, with `enrolled_count` and `completer_count` both at zero.

Sessions are then planned against a still-`SCHEDULED` cohort — planning against a cohort that has moved on is rejected with `ERR_INVALID_STATE`. Each session names a `venue_id` and a window from `start_at` to `end_at`; the end must be strictly after the start (otherwise `ERR_INVALID_REQUEST`), the venue's `kind` must match the cohort's delivery mode (otherwise `ERR_DELIVERY_MODE_MISMATCH`), and the venue's turnover-buffer rule of §2.9 applies (otherwise `ERR_VENUE_OVERLAP`). The server derives `hours` as the length of the window in hours, rounded to six decimal places, and starts the session in `PLANNED` with `attendance_closed` false; planning a session is a schedule mutation of the cohort itself, refreshing the cohort's `updated_at` and incrementing its `version` per §2.4.

Rosters fill in parallel. Enrolling a participant takes the employer-side `external_employee_ref` and the person's `full_name`; the cohort must still be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and the same `external_employee_ref` may not be held by another `ENROLLED` participant of the same cohort (otherwise `ERR_DUPLICATE_PARTICIPANT`). Each enrollment starts the participant's `completion_status` at `ENROLLED`, with `attended_hours` and `attendance_pct` at zero, and increments the cohort's `enrolled_count` by one. A `WorkforceCoordinator` may also drop an `ENROLLED` participant, moving them to `DROPPED` and decrementing `enrolled_count` by one.

### 3.5. Staffing Sessions: Assignments, Credential Gates, and Duty Segregation

Instructors are registered by a `CollegeAdmin` with a `full_name`, a list of `credentials` — each a code with an `expires_on` date — and an `hourly_rate_cents` bill rate per contact hour; a new instructor starts `ACTIVE` with `committed_hours` at zero. Deactivation (`ACTIVE` to `INACTIVE`) is blocked while the instructor holds `CONFIRMED` assignments on `PLANNED` sessions — those must be released first, otherwise the attempt fails with `ERR_INVALID_STATE` — and reactivation returns an `INACTIVE` instructor to `ACTIVE`.

Staffing a session is a two-signature act. A `WorkforceCoordinator` proposes an instructor for a session by naming the `instructor_id`; the session must still be `PLANNED` (otherwise `ERR_INVALID_STATE`), the new assignment starts in `PROPOSED`, and the server records the caller in `proposed_by_user_id`. Confirmation belongs exclusively to a `CredentialOfficer`, and it is where the compliance gates live. Six conditions must hold: the confirmer's `X-User-ID` must differ from `proposed_by_user_id` — the proposer may never confirm their own proposal, and a self-confirmation is rejected with `ERR_SEGREGATION_OF_DUTIES`; no credential required by the cohort's curriculum may be expired at the session's start (otherwise `ERR_CREDENTIAL_EXPIRED`); the computed `match_score` must be at least 80 (otherwise `ERR_CREDENTIAL_MISMATCH`); the instructor must be `ACTIVE` (otherwise `ERR_INVALID_STATE`); the session's window must not overlap, under half-open semantics, any other session on which the same instructor holds a `CONFIRMED` assignment — windows that merely touch, the previous `end_at` equalling the next `start_at`, are allowed, and a true overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`; and the session must still be `PLANNED` (a session-state violation surfaces through the `ERR_SESSION_NOT_PLANNED` gate of §2.8, with generic invalid transitions falling to `ERR_INVALID_STATE`).

The `match_score` itself is a weighted coverage measure. The required set is the union of `required_credential_codes` across the `curriculum_modules` of the assessment backing the cohort's agreement. Each required code contributes a weight read from the instructor's `credentials`: zero when the instructor holds no credential with that code; zero when the credential's `expires_on` falls before the session's `start_at` — the expiry case that independently blocks confirmation with `ERR_CREDENTIAL_EXPIRED`; one half when the credential expires on or after `start_at` but within thirty days of it; and one when `expires_on` lies at least thirty days beyond `start_at`. The score is one hundred times the sum of the weights divided by the number of required codes, rounded half up to an integer percent, and a curriculum with no required codes scores 100 by convention. A successful confirmation persists the computed `match_score`, records the confirmer in `approved_by_user_id`, moves the assignment from `PROPOSED` to `CONFIRMED`, and increases the instructor's `committed_hours` by the session's `hours`.

Release unwinds a staffing decision: a `WorkforceCoordinator` or `CredentialOfficer` may release an assignment from `PROPOSED` without preconditions, or from `CONFIRMED` while the session is still `PLANNED` (otherwise `ERR_INVALID_STATE`); releasing from `CONFIRMED` decreases the instructor's `committed_hours` by the session's `hours`. Throughout, `committed_hours` is not a free-running counter but a defined quantity — the sum of `hours` over the instructor's `CONFIRMED` assignments on `PLANNED` sessions — so a confirm followed by its compensating release leaves it unchanged.

### 3.6. Delivery, Attendance, and Completion Credentialing

Launch is the point of no return for planning. A `WorkforceCoordinator` launches a `SCHEDULED` cohort only when four gates pass: the agreement is `SIGNED` or `IN_DELIVERY` (otherwise `ERR_AGREEMENT_NOT_SIGNED`); `enrolled_count` is at least `min_enrollment` — the boundary itself passes, so an exactly-full floor launches, and a shortfall is rejected with `ERR_BELOW_MIN_ENROLLMENT`; every `PLANNED` session holds at least one `CONFIRMED` assignment (otherwise `ERR_CREDENTIAL_MISMATCH`); and every `CAMPUS_LAB` venue engaged by the cohort — its primary venue and each of its sessions' venues — has a `capacity` of at least `enrolled_count` (otherwise `ERR_VENUE_CAPACITY_EXCEEDED`). A launched cohort lands in `LAUNCHED`, and when it is the agreement's first launch the agreement moves from `SIGNED` to `IN_DELIVERY`.

Attendance closes per session, by the `Instructor` who actually taught it. The cohort must be `LAUNCHED` or `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`); the caller's `X-User-ID` must equal the `instructor_id` of a `CONFIRMED` or `COMPLETED` assignment on that session (otherwise `ERR_FORBIDDEN_FOR_ROLE`) — admitting a `COMPLETED` assignment is what lets the instructor who taught the session re-invoke closure and observe the already-closed rejection below; and attendance must not already be closed — invoking closure on a session already `HELD` returns the specialized `ERR_ATTENDANCE_ALREADY_CLOSED`, while invoking it on a `CANCELLED` session returns the generic `ERR_INVALID_STATE`, a check that fires before the ownership comparison. The `attendance` payload is a list of per-participant entries pairing `external_employee_ref` with `attended_hours`, and no entry may exceed the session's `hours` (otherwise `ERR_INVALID_REQUEST`); entries naming an `external_employee_ref` that is not on the cohort's roster are ignored.

A successful closure sets `attendance_closed` to true, moves the session from `PLANNED` to `HELD`, and adds each entry's `attended_hours` to the listed participant's cumulative `attended_hours`. The cascade continues outward: every `CONFIRMED` assignment on the session moves to `COMPLETED` and the instructor's `committed_hours` decreases by the session's `hours`; the cohort moves from `LAUNCHED` to `IN_PROGRESS` on its first `HELD` session; and when every session of the cohort sits in `HELD` or `CANCELLED` with at least one `HELD`, the cohort moves from `IN_PROGRESS` to `DELIVERED` and completion is evaluated.

Completion evaluation runs over every still-`ENROLLED` participant of the delivered cohort. The denominator is the sum of `hours` across the cohort's `HELD` sessions; each participant's `attendance_pct` is one hundred times their `attended_hours` divided by that sum, rounded half up to two decimal places. A participant with zero attended hours becomes `NO_SHOW`; a participant whose rounded percentage is at least 80.00 — the boundary itself qualifies — becomes `COMPLETED`; anyone positive but below the threshold becomes `DROPPED`. The cohort's `completer_count` is then recomputed as the number of `COMPLETED` participants.

Credentialing is the final delivery step: a `CredentialOfficer` issues completion credentials against a `DELIVERED` cohort, which requires at least one completer — a `completer_count` of zero is rejected with `ERR_NO_COMPLETERS`. The cohort moves to the terminal `CREDENTIALED`, and every `COMPLETED` participant receives a `credential_code` of the form `CTC-<cohort start_date yyyymmdd>-<external_employee_ref>`, binding the credential to the cohort's start date and the employer-side reference.

### 3.7. Invoicing, Grant Offsets, and Settlement

Billing is per cohort, in two variants, and belongs to the `BillingClerk`. Generating an invoice takes a `variant` — `PROVISIONAL` or `FINAL` — and the variant must fit the cohort's delivery state: `PROVISIONAL` requires `LAUNCHED` or `IN_PROGRESS`, while `FINAL` requires `DELIVERED` or `CREDENTIALED`; a mismatch is rejected with `ERR_INVOICE_VARIANT_NOT_ALLOWED`; the variant gate is evaluated before the open-invoice rule that follows. At most one open invoice — one in `DRAFT` or `ISSUED` — may exist per cohort at a time (otherwise `ERR_INVALID_STATE`). A new invoice starts in `DRAFT`, is stamped with both its `cohort_id` and a denormalized `agreement_id`, and carries computed `lines`, `gross_cents`, `grant_offset_cents`, and `net_due_cents`.

The gross is built line by line, one line per in-scope session, and each line records its `session_id`, `instruction_cents`, `materials_cents`, and `line_cents`. Scope and attendance basis depend on the variant: a `FINAL` invoice reads only `HELD` sessions and counts, per session, the participants whose recorded `attended_hours` for that session are greater than zero; a `PROVISIONAL` invoice reads only `PLANNED` sessions and counts the cohort's whole `enrolled_count` on every line. Either way, the instruction component is the session's `hours` multiplied by the `hourly_rate_cents` of the instructor on the session's `COMPLETED`-or-`CONFIRMED` assignment — when the session has no such assignment, generation fails with `ERR_INVALID_STATE`, and when it has several, the earliest-created one supplies the instructor — multiplied again by a load factor of 1.15, rounded half up to whole cents; the materials component is the attendee count multiplied by 7,500 cents, rounded half up to whole cents; and the line total is the sum of the two rounded components. The invoice's `gross_cents` is then the integer sum of the line totals: rounding happens per line and only per line, because rounding a sum of unrounded lines produces a different cent figure and is forbidden.

The grant offset applies after the gross, in a pinned three-step order that removes any circular reading. Step one computes the gross as above. Step two locates the cohort's application in `APPROVED`, `CLAIMED`, or `PAID` — the most recently created one, when several qualify; the award basis is the `final_award_cents` when the application is `CLAIMED` or `PAID` and the `provisional_award_cents` when it is `APPROVED`, and `grant_offset_cents` is the smallest of three ceilings — the award basis, the whole-cent floor of `gross_cents` multiplied by the program's `max_share_pct`, and the program's `cap_per_trainee_cents` multiplied by the headcount basis, which is the cohort's `completer_count` for a `FINAL` invoice and its `enrolled_count` for a `PROVISIONAL` one. When no such application covers the cohort, the offset is zero. Step three sets `net_due_cents` to the gross minus the offset. The offset never feeds back into the gross; the three steps run exactly once, in this order.

The invoice lifecycle then drives both billing dimensions. Issuing moves an invoice from `DRAFT` to `ISSUED`, flips the cohort's `billing_status` from `UNBILLED` to `INVOICED`, and, on the agreement, moves an `UNBILLED` `billing_status` to `PARTIALLY_BILLED`. Marking paid is allowed only from `ISSUED` — any other state is rejected with `ERR_INVOICE_NOT_PAYABLE` — and moves the invoice to `PAID`, the cohort's `billing_status` to `PAID`, adds the invoice's `net_due_cents` to the employer's `lifetime_billed_cents`, and settles the agreement: when every non-`CANCELLED` cohort of the agreement is `PAID`, the agreement's `billing_status` becomes `SETTLED`. Voiding moves a `DRAFT` or `ISSUED` invoice to `VOID`; voiding an `ISSUED` invoice also returns the cohort's `billing_status` from `INVOICED` to `UNBILLED` (the agreement's `billing_status` is left unchanged), while attempting to void a `PAID` or already-`VOID` invoice is rejected with `ERR_INVALID_STATE`. Employer rollups stay consistent with these flows: `lifetime_billed_cents` is, at all times, the sum of `net_due_cents` over the employer's `PAID` invoices only — `DRAFT`, `ISSUED`, and `VOID` are excluded.

### 3.8. Outcome Reporting and Agreement Completion

Once delivery is underway, a `WorkforceCoordinator` files an outcome report against the agreement — the agreement must have reached `IN_DELIVERY`, otherwise the create fails with `ERR_INVALID_STATE`. The report captures `completers_employed_90d`, the count of completers verified employed ninety days after credentialing; `satisfaction_avg`, the employer's average satisfaction score from 0 to 5; and `follow_on_opportunity_cents`, the estimated value of any follow-on training pipeline identified. It starts in `DRAFT`.

Submission requires the book to be closed: every cohort of the agreement must sit in a terminal delivery state, `CREDENTIALED` or `CANCELLED`, otherwise the submit is rejected with `ERR_OUTCOME_INCOMPLETE`. A successful submit moves the report from `DRAFT` to `SUBMITTED` and computes `placement_pct`: the total completers are the sum of `completer_count` over the agreement's `CREDENTIALED` cohorts, and the percentage is one hundred times `completers_employed_90d` divided by that total, rounded half up to two decimal places. A total of zero completers makes the computation undefined and the submit fails with `ERR_INVALID_REQUEST`.

Acceptance belongs to a `CollegeAdmin` and closes the engagement. Accepting moves the report from `SUBMITTED` to the terminal `ACCEPTED`, adds its `follow_on_opportunity_cents` to the employer's `follow_on_pipeline_cents` — which is, at all times, the sum of that figure over the employer's `ACCEPTED` reports only, `DRAFT` and `SUBMITTED` excluded — and, when every cohort is terminal, moves the agreement from `IN_DELIVERY` to `COMPLETED`, settling the agreement's `billing_status` to `SETTLED` when every non-`CANCELLED` cohort has been paid.

### 3.9. Cancellation Cascades and Clock-Driven Sweeps

Cancellation unwinds the hierarchy link by link. A `WorkforceCoordinator` or `CollegeAdmin` may cancel an agreement from `DRAFT`, `QUOTED`, or `NEGOTIATING` with no further effect, landing it in the terminal `CANCELLED`. Cancelling from `SIGNED` fires the full cascade: every child cohort in `SCHEDULED`, `LAUNCHED`, or `IN_PROGRESS` moves to `CANCELLED` (link 1); each such cohort cancellation moves its `PLANNED` sessions to `CANCELLED` (link 2); each such session cancellation moves its assignments in `PROPOSED` or `CONFIRMED` to `RELEASED`, decrementing the instructor's `committed_hours` by the session's `hours` for the `CONFIRMED` ones (link 3); each such cohort cancellation also moves its grant applications in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `RETURNED` to `WITHDRAWN`, while `APPROVED` applications first release their `reserved_cents` back to the program and then move to `WITHDRAWN` (link 2'); and each such cohort whose `billing_status` is `INVOICED` has its open `DRAFT` or `ISSUED` invoice voided (link 2''). Cancelling from `IN_DELIVERY` fires the same chain with two carve-outs: `CREDENTIALED` cohorts are terminal and untouched, and `HELD` sessions are likewise left in place.

A cohort can also be cancelled directly, by a `WorkforceCoordinator` or `CollegeAdmin`, from `SCHEDULED` or `LAUNCHED`, firing the same cascade set — `PLANNED` sessions cancelled; `PROPOSED` and `CONFIRMED` assignments released with the `committed_hours` decrement for confirmed ones; pending grant applications withdrawn with `APPROVED` reservations released to the program; and any open `DRAFT` or `ISSUED` invoice voided, returning an `INVOICED` cohort to `UNBILLED`. A cohort in `IN_PROGRESS` — one with a `HELD` session — cannot be cancelled directly; the attempt is rejected with `ERR_INVALID_STATE`, and such a cohort is only ever cancelled as part of the agreement cascade. A single session can be cancelled from `PLANNED` by a `WorkforceCoordinator`, releasing its `PROPOSED` and `CONFIRMED` assignments with the same hours decrement. Cancelling a session is likewise a schedule mutation of its cohort — the cohort's `updated_at` refreshes and its `version` increments — and it re-runs the delivery-progression rule of §3.6, so an `IN_PROGRESS` cohort whose sessions are then all `HELD` or `CANCELLED` with at least one `HELD` moves to `DELIVERED` and has completion evaluated at that point. Every cascade mutation refreshes `updated_at` and bumps `version` per §2.4 and §2.11.

The logical clock of §2.5 drives the two remaining transitions. When the clock advances, the dormancy sweep moves an `ACTIVE` employer to `DORMANT` if no cohort of any of its agreements reached `CREDENTIALED` within the trailing 365 days and none of its agreements sits in `QUOTED`, `NEGOTIATING`, `SIGNED`, or `IN_DELIVERY`. The grant-expiry sweep moves an `APPROVED` application whose `claim_by` has passed to the terminal `EXPIRED`, releasing its reservation: the program's reserved figure decreases by the application's `reserved_cents`, the available figure increases by the same amount, and the application's `reserved_cents` is zeroed.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201; reads, state transitions, modifications, and the clock operation respond with 200. Unless otherwise noted in §3, a create or mutation returns the affected resource in the response's `data` field. The request and response shapes of each endpoint are defined by the workflows of §3; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /ct/_clock/set_current_utc | Set the logical clock; advancing it runs the dormancy and grant-expiry sweeps | CollegeAdmin |
| POST | /ct/employers | Create an employer in `PROSPECT` status | CollegeAdmin, WorkforceCoordinator |
| GET | /ct/employers/{id} | Get an employer | All roles |
| GET | /ct/employers/{id}/needs-assessments | List an employer's needs assessments, paginated | All roles |
| GET | /ct/employers/{id}/training-agreements | List an employer's training agreements, paginated | All roles |
| POST | /ct/employers/{id}/needs-assessments | Create a needs assessment in `DRAFT` | WorkforceCoordinator |
| GET | /ct/needs-assessments/{id} | Get a needs assessment | All roles |
| POST | /ct/needs-assessments/{id}/submit | Submit an assessment (`DRAFT` or `REVISION_REQUESTED` to `SUBMITTED`) | WorkforceCoordinator |
| POST | /ct/needs-assessments/{id}/approve | Approve an assessment (`SUBMITTED` to `APPROVED`) | CollegeAdmin |
| POST | /ct/needs-assessments/{id}/request_revision | Request revision (`SUBMITTED` to `REVISION_REQUESTED`) | CollegeAdmin |
| POST | /ct/employers/{id}/training-agreements | Create an agreement in `DRAFT`, pinned to the assessment's current version | WorkforceCoordinator |
| GET | /ct/training-agreements/{id} | Get a training agreement | All roles |
| GET | /ct/training-agreements | List agreements with optional filters `needs_assessment_id`, `employer_id`, `contract_status`, paginated | All roles |
| POST | /ct/training-agreements/{id}/quote | Generate the initial quote (`DRAFT` to `QUOTED`) | WorkforceCoordinator |
| POST | /ct/training-agreements/{id}/revise | Revise the quote (`NEGOTIATING` to `QUOTED`); OCC-guarded | WorkforceCoordinator |
| POST | /ct/training-agreements/{id}/negotiate | Request changes (`QUOTED` to `NEGOTIATING`) | EmployerContact |
| POST | /ct/training-agreements/{id}/sign | Sign the agreement (`QUOTED` to `SIGNED`); activates the employer | EmployerContact |
| POST | /ct/training-agreements/{id}/cancel | Cancel the agreement (`DRAFT`, `QUOTED`, `NEGOTIATING`, `SIGNED`, or `IN_DELIVERY` to `CANCELLED`) with full cascade | WorkforceCoordinator, CollegeAdmin |
| POST | /ct/training-agreements/{id}/refresh_assessment_pin | Re-pin the assessment version while in `DRAFT`, `QUOTED`, or `NEGOTIATING` | WorkforceCoordinator |
| GET | /ct/training-agreements/{id}/cohorts | List an agreement's cohorts, paginated | All roles |
| GET | /ct/training-agreements/{id}/outcome-reports | List an agreement's outcome reports, paginated | All roles |
| POST | /ct/grant-programs | Create a grant program in `OPEN` with available equal to the appropriation | CollegeAdmin |
| GET | /ct/grant-programs/{id} | Get a grant program | All roles |
| POST | /ct/grant-programs/{id}/suspend | Suspend a program (`OPEN` to `SUSPENDED`) | CollegeAdmin |
| POST | /ct/grant-programs/{id}/reopen | Reopen a program (`SUSPENDED` to `OPEN`) | CollegeAdmin |
| POST | /ct/grant-programs/{id}/close | Close a program (`OPEN` or `SUSPENDED` to `CLOSED`) when nothing is reserved or committed | CollegeAdmin |
| POST | /ct/cohorts/{id}/grant-applications | Create a grant application in `DRAFT` for a cohort; OCC-guarded on the cohort | WorkforceCoordinator |
| GET | /ct/grant-applications/{id} | Get a grant application | All roles |
| GET | /ct/grant-applications | List applications with optional filters `program_id`, `cohort_id`, `status`, paginated | All roles |
| GET | /ct/cohorts/{id}/grant-applications | List a cohort's grant applications, paginated | All roles |
| POST | /ct/grant-applications/{id}/submit | Submit an application (`DRAFT` or `RETURNED` to `SUBMITTED`) | WorkforceCoordinator |
| POST | /ct/grant-applications/{id}/start_review | Start review (`SUBMITTED` to `UNDER_REVIEW`) | GrantOfficer |
| POST | /ct/grant-applications/{id}/return | Return an application for changes (`UNDER_REVIEW` to `RETURNED`) | GrantOfficer |
| POST | /ct/grant-applications/{id}/approve | Approve and reserve funds (`UNDER_REVIEW` to `APPROVED`) | GrantOfficer |
| POST | /ct/grant-applications/{id}/deny | Deny an application (`UNDER_REVIEW` to `DENIED`) | GrantOfficer |
| POST | /ct/grant-applications/{id}/claim | Claim reimbursement (`APPROVED` to `CLAIMED`); computes the final award | WorkforceCoordinator |
| POST | /ct/grant-applications/{id}/mark_paid | Mark reimbursed (`CLAIMED` to `PAID`) | GrantOfficer |
| POST | /ct/instructors | Create an instructor in `ACTIVE` status | CollegeAdmin |
| GET | /ct/instructors/{id} | Get an instructor | All roles |
| POST | /ct/instructors/{id}/deactivate | Deactivate an instructor (`ACTIVE` to `INACTIVE`) | CollegeAdmin |
| POST | /ct/instructors/{id}/reactivate | Reactivate an instructor (`INACTIVE` to `ACTIVE`) | CollegeAdmin |
| POST | /ct/venues | Create a venue with a thirty-minute default turnover buffer | CollegeAdmin |
| GET | /ct/venues/{id} | Get a venue | All roles |
| POST | /ct/training-agreements/{id}/cohorts | Create a cohort in `SCHEDULED` under the agreement | WorkforceCoordinator |
| GET | /ct/cohorts/{id} | Get a cohort | All roles |
| GET | /ct/cohorts | List cohorts with optional filters `venue_id`, `agreement_id`, `delivery_status`, paginated | All roles |
| POST | /ct/cohorts/{id}/launch | Launch a cohort (`SCHEDULED` to `LAUNCHED`) | WorkforceCoordinator |
| POST | /ct/cohorts/{id}/cancel | Cancel a cohort (`SCHEDULED` or `LAUNCHED` to `CANCELLED`) with cascade | WorkforceCoordinator, CollegeAdmin |
| POST | /ct/cohorts/{id}/issue_credentials | Issue completion credentials (`DELIVERED` to `CREDENTIALED`) | CredentialOfficer |
| GET | /ct/cohorts/{id}/sessions | List a cohort's sessions, paginated | All roles |
| GET | /ct/cohorts/{id}/participants | List a cohort's participants, paginated | All roles |
| GET | /ct/cohorts/{id}/invoices | List a cohort's invoices, paginated | All roles |
| POST | /ct/cohorts/{id}/sessions | Plan a session on a `SCHEDULED` cohort; venue kind and turnover rules enforced | WorkforceCoordinator |
| GET | /ct/sessions/{id} | Get a session | All roles |
| GET | /ct/sessions | List sessions with optional filters `venue_id`, `cohort_id`, `status`, paginated | All roles |
| POST | /ct/sessions/{id}/cancel | Cancel a `PLANNED` session, releasing its assignments | WorkforceCoordinator |
| POST | /ct/sessions/{id}/close_attendance | Close attendance (`PLANNED` to `HELD`) with the per-participant attendance payload | Instructor |
| GET | /ct/sessions/{id}/instructor-assignments | List a session's instructor assignments, paginated | All roles |
| POST | /ct/sessions/{id}/instructor-assignments | Propose an instructor for a session (assignment starts `PROPOSED`) | WorkforceCoordinator |
| GET | /ct/instructor-assignments/{id} | Get an instructor assignment | All roles |
| GET | /ct/instructor-assignments | List assignments with optional filters `instructor_id`, `session_id`, `status`, paginated | All roles |
| POST | /ct/instructor-assignments/{id}/confirm | Confirm a proposed assignment (`PROPOSED` to `CONFIRMED`); credential, segregation, and overlap gates | CredentialOfficer |
| POST | /ct/instructor-assignments/{id}/release | Release an assignment (`PROPOSED` or `CONFIRMED` to `RELEASED`) | WorkforceCoordinator, CredentialOfficer |
| POST | /ct/cohorts/{id}/participants | Enroll a participant on a `SCHEDULED` cohort | WorkforceCoordinator |
| GET | /ct/participants/{id} | Get a participant | All roles |
| POST | /ct/participants/{id}/drop | Drop an `ENROLLED` participant (`ENROLLED` to `DROPPED`) | WorkforceCoordinator |
| POST | /ct/cohorts/{id}/invoices | Generate an invoice for a cohort; variant gates on delivery state; grant offset applied | BillingClerk |
| GET | /ct/invoices/{id} | Get an invoice | All roles |
| GET | /ct/invoices | List invoices with optional filters `agreement_id`, `cohort_id`, `status`, paginated | All roles |
| POST | /ct/invoices/{id}/issue | Issue an invoice (`DRAFT` to `ISSUED`) | BillingClerk |
| POST | /ct/invoices/{id}/mark_paid | Mark an invoice paid (`ISSUED` to `PAID`) | BillingClerk |
| POST | /ct/invoices/{id}/void | Void an invoice (`DRAFT` or `ISSUED` to `VOID`) | BillingClerk |
| POST | /ct/training-agreements/{id}/outcome-reports | Create an outcome report in `DRAFT`; the agreement must be `IN_DELIVERY` | WorkforceCoordinator |
| GET | /ct/outcome-reports/{id} | Get an outcome report | All roles |
| POST | /ct/outcome-reports/{id}/submit | Submit a report (`DRAFT` to `SUBMITTED`); requires all cohorts terminal | WorkforceCoordinator |
| POST | /ct/outcome-reports/{id}/accept | Accept a report (`SUBMITTED` to `ACCEPTED`); completes the agreement | CollegeAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_AGREEMENT_NOT_SIGNED | 409 |
| ERR_AGREEMENT_TERMINAL | 409 |
| ERR_ASSESSMENT_NOT_APPROVED | 409 |
| ERR_STALE_ASSESSMENT | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_DELIVERY_MODE_MISMATCH | 409 |
| ERR_BELOW_MIN_ENROLLMENT | 409 |
| ERR_VENUE_CAPACITY_EXCEEDED | 409 |
| ERR_CREDENTIAL_EXPIRED | 409 |
| ERR_CREDENTIAL_MISMATCH | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_INSTRUCTOR_DOUBLE_BOOKED | 409 |
| ERR_VENUE_OVERLAP | 409 |
| ERR_DUPLICATE_PARTICIPANT | 409 |
| ERR_ATTENDANCE_ALREADY_CLOSED | 409 |
| ERR_SESSION_NOT_PLANNED | 409 |
| ERR_COHORT_NOT_CREDENTIALED | 409 |
| ERR_GRANT_PROGRAM_NOT_OPEN | 409 |
| ERR_GRANT_WINDOW_CLOSED | 409 |
| ERR_GRANT_CAPACITY_EXCEEDED | 409 |
| ERR_INVOICE_VARIANT_NOT_ALLOWED | 409 |
| ERR_INVOICE_NOT_PAYABLE | 409 |
| ERR_NO_COMPLETERS | 409 |
| ERR_OUTCOME_INCOMPLETE | 409 |
