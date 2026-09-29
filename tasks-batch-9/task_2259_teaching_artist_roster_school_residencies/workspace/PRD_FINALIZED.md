# Teaching Artist Residencies API — Product Requirements Document

## 1. Introduction

An arts education organization places professional teaching artists into public school classrooms for multi-session residencies. Today that work is spread across a recruitment spreadsheet, a shared school calendar, a curriculum binder of state arts standards, an invoice inbox, and a grant-reporting workbook that nobody trusts by March. The consequences are concrete: an artist whose fingerprint clearance lapsed mid-term keeps teaching; a residency contracted for twenty sessions quietly delivers fourteen because nobody tracked the make-up credits; a funder receives a students-served figure that double-counts children who attended six sessions each.

This API is the system of record that closes those gaps. It governs the full arc of a teaching artist's relationship with the organization — application, juried portfolio review, teaching demonstration, child-safety screening, roster placement, probation and retirement — and the full arc of a school residency — scoping and budgeting, curriculum alignment to state arts standards, session-by-session scheduling against real school calendars, substitute coverage and make-up policy, per-session artist payment with travel and materials reimbursement, evaluation through rubrics and surveys, and finally certified reporting to funders.

Two design commitments shape everything that follows. First, **child safety and segregation of duties are structural, not procedural**: no artist reaches a classroom without a complete, unexpired screening set, and no single operator can both produce and bless a payment or a funder report. Second, **every residency carries two conserved quantities** — a session obligation and a money budget — that the server must keep balanced after every single request, so that a program director can always answer "how many sessions do we still owe this school, and how much of the budget is truly left?" without a reconciliation exercise.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API surface. Every endpoint is mounted at the service root; there is no additional URL prefix.

### 2.1. Operator Identity and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. If either header is absent, or if `X-User-Role` is not one of the six recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the acting role is not permitted to invoke the requested operation, the rejection is `ERR_UNAUTHORIZED`. The same code covers two role-shaped mismatches inside otherwise-permitted operations: submitting a voucher review on a track the acting role does not own, and attaching an evaluation of a type the acting role is not allowed to record.

The six roles are `ProgramDirector`, `RosterCoordinator`, `CurriculumSpecialist`, `TeachingArtist`, `SchoolLiaison`, and `FiscalOfficer`.

- A `ProgramDirector` owns school partnerships and the residency lifecycle, closes the program side of voucher review, and opens and compiles funder reports. It may never close the fiscal side of a voucher, and may never certify a report.
- A `RosterCoordinator` runs recruitment and the roster and owns the schedule: applicant intake, portfolio panels, demonstration outcomes, screening results, session creation, substitute coverage, and cancellations.
- A `CurriculumSpecialist` owns curriculum alignment against state arts standards and observation-rubric evaluation.
- A `TeachingArtist` is a rostered artist acting as themselves.
- A `SchoolLiaison` is the host school acting as itself.
- A `FiscalOfficer` holds fiscal control: it closes the fiscal side of voucher review, voids disbursements, and certifies compiled funder reports. It cannot compile a report at all.

Identity binding differs by role, and this is what ties `X-User-ID` to resource ownership:

- When `X-User-Role` is `TeachingArtist`, `X-User-ID` is the `id` of the acting `TeachingArtist`; ownership checks on any resource that references a `TeachingArtist` compare the resource's artist reference to `X-User-ID` — specifically a session's `assigned_artist_id`, a lesson plan's `author_artist_id`, and a voucher's `teaching_artist_id`.
- When `X-User-Role` is `SchoolLiaison`, `X-User-ID` is the `id` of the acting `SchoolPartner`; ownership checks compare the host school of the residency behind the addressed resource — its `school_partner_id` — to `X-User-ID`.
- When `X-User-Role` is `ProgramDirector`, `RosterCoordinator`, `CurriculumSpecialist`, or `FiscalOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `demo_evaluator_user_id` on a `TeachingArtist`, as `reviewer_user_id` on a `LessonPlan`, as `fiscal_reviewed_by` or `program_reviewed_by` on a `PaymentVoucher`, or as `compiled_by_user_id` on a `FunderReport` — but never compares it to any entity's `id`.

An ownership violation by one of the two entity-backed roles is rejected with `ERR_ACTOR_NOT_RESOURCE_OWNER`. That check guards exactly eight operations: session confirmation, session delivery, session cancellation, attaching a session evaluation, lesson plan creation, lesson plan revision resubmission, voucher creation, and voucher submission.

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

List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` skips a number of leading records and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending.

Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Record Identity, Timestamps, and the Logical Clock

Primary resources — school partners, teaching artists, arts standards, residencies, lesson plans, sessions, payment vouchers, and funder reports — carry a common set of server-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation, including mutations that only change derived fields.
- `version` (integer): a counter that increments by one on every mutation of the row.

Four record types are append-only observations rather than living resources, and they carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: calendar blackout windows, portfolio reviews, background screenings, and evaluation records.

Every date and datetime comparison in this specification — clearance expiry, program-year membership, reporting-period membership, and the moment written into a lesson plan's `aligned_on` — reads a server-side **logical clock** rather than real wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `ProgramDirector` may move it by supplying a `to_iso8601` instant to the clock-control capability; moving the clock mutates no entity and fires no cascade.

### 2.5. Money, Rounding, and Basis Points

All money in the system is an integer number of cents. There are no fractional cents and no floating-point money fields anywhere in the API.

Wherever rounding is required, the method is **round half up** — a value exactly halfway between two candidates rounds away from zero. The precision differs by quantity and is stated with each rule, but the defaults are: money rounds to whole cents; portfolio composite scores, portfolio means, and rubric composites round to two decimal places; a residency's evaluation index rounds to one decimal place; reliability figures are whole **basis points**, where 10000 basis points means every attributable session was delivered and 0 means none was; and school demographic shares (`frl_pct`, `ell_pct`, `iep_pct`) are supplied as fractions between 0.00 and 1.00 inclusive with two decimals.

Two rounding orders are load-bearing and pinned. First, the artist session fee applies round-half-up at **each** intermediate step described in §3.7, not only to the final figure. Second, travel reimbursement is rounded **per session** and only then summed onto a voucher; summing raw mileage across sessions and rounding once produces a different — and wrong — total.

### 2.6. Version Stamping and Stale-Write Rejection

Three write operations are optimistically concurrency-controlled against a parent row's `version`. In each case the version field is a **required** input, not an optional hint, and the request is rejected outright when the value does not equal the parent's current `version`.

- Session creation must carry `expected_residency_version`, matching the current `version` of the residency named by `residency_id`. A mismatch is rejected with `ERR_STALE_RESIDENCY_VERSION` and HTTP 412. Scheduling a second session against a version the client read earlier is otherwise perfectly legal product behaviour — two distinct sessions may coexist — so no state precondition catches it. The stale version is the only signal that the client planned against an out-of-date session ledger, encumbrance figure, or staffing picture.
- Session reassignment must carry `expected_session_version`, matching the current `version` of the addressed session. A mismatch is rejected with `ERR_STALE_SESSION_VERSION` and HTTP 412. A reassignment supersedes whatever artist assignment the client last observed; against a stale version the transition would still succeed under the state machine and would silently overwrite a newer substitute.
- Voucher review must carry `expected_payment_voucher_version`, matching the current `version` of the addressed voucher. A mismatch is rejected with `ERR_STALE_VOUCHER_VERSION` and HTTP 412. Because the two review tracks are independent, a reviewer closing the program track from the same observed version that another reviewer used to close the fiscal track would legitimately succeed under the state machine; the version check forces the second reviewer to re-read the voucher — and therefore the first track's outcome and the recomputed total — before closing their own track.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.7. Cascade Discipline and Derived-Field Reconciliation

Many fields in this system are **derived**: they are never supplied by a client and are always recomputed by the server from the rows they summarize. A school partner's `partnership_health` and `open_residency_count`, a residency's `staffing_status`, all of its session-ledger counters and money counters, its `earned_to_date_cents`, `projected_cost_cents` and `evaluation_index`, an artist's `portfolio_review_count`, `portfolio_mean_composite`, `clearance_status`, `clearance_expires_on`, `lifetime_delivered_count`, `no_show_count`, both reliability figures and `roster_tier_effective`, a lesson plan's `covered_strands` and `revision_round`, a session's `makeup_eligible`, `makeup_consumed` and money fields, a portfolio review's `composite_score` and `recommendation`, a screening's `superseded` flag, an evaluation's `rubric_composite`, and every computed metric on a voucher or funder report all fall into this category.

Reconciliation is immediate and transitive. A single request may legitimately mutate several rows: each mutated row has its `updated_at` refreshed and its `version` incremented, even when the only thing that changed was a derived counter. The server is also entitled to move a row through a state transition on its own — the roster axis of an artist activating when vetting completes, a session vacating when its artist is suspended, a voucher approving when its second review track passes, a compiled funder report falling back to draft when new delivery lands inside its period — without any client request naming that row.

Two cascades are long enough to deserve names, and both are specified in full in §3.

**Cascade A** begins when an artist's roster standing drops to `SUSPENDED` (whether by director action or as the automatic consequence of a failed screening) and runs four links: the roster axis moves to `SUSPENDED`; every one of that artist's `PLANNED` or `CONFIRMED` sessions is vacated; every residency touched by that vacating has its vacated-session count and staffing status recomputed, and loses its lead artist reference if the suspended artist held it; and every school owning one of those residencies has its partnership health recomputed.

**Cascade B** begins when a confirmed or planned session is cancelled for an artist-side reason and runs four links: the session terminates as an artist cancellation and issues a make-up credit; the artist's no-show counter and both reliability figures are recomputed; a reliability figure that has fallen below the probation floor moves the artist from `ACTIVE` to `PROBATION`; and entering `PROBATION` caps the artist's effective fee tier, which in turn re-projects the cost of every residency holding an open session of that artist.

### 2.8. Nested Resource Retrieval and Path Validation

Several read and write paths address a child record through its parent — a school's blackout calendar, an artist's portfolio reviews or screenings, a session's evaluations. For any request whose path contains identifiers, the server resolves them strictly left to right and rejects on the **first** identifier that does not resolve, before evaluating anything else about the request. A request for the evaluations of a session that does not exist fails with `ERR_SESSION_NOT_FOUND`; a request for the blackout windows of a school that does not exist fails with `ERR_SCHOOL_PARTNER_NOT_FOUND`. The not-found code always names the entity type of the unresolved identifier: `ERR_SCHOOL_PARTNER_NOT_FOUND`, `ERR_TEACHING_ARTIST_NOT_FOUND`, `ERR_RESIDENCY_NOT_FOUND`, `ERR_LESSON_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or `ERR_FUNDER_REPORT_NOT_FOUND`.

Identifiers supplied in a request **body** are resolved in the same style and with the same codes, once path resolution has succeeded and the payload has passed type and range checking. This covers `school_partner_id`, `lead_artist_id` and `teaching_artist_id`, `residency_id`, `lesson_plan_id`, `assigned_artist_id`, `substitute_artist_id`, `makeup_for_session_id`, every element of `session_ids`, and every element of `scope_residency_ids`. A standards reference is the one exception in kind rather than in ordering: every element of `standard_codes` must equal the `code` of an existing arts standard, and an element that matches none is rejected with `ERR_UNKNOWN_STANDARD_CODE` at HTTP 422.

When a child record is created under a parent path, the parent link is taken from the path and never from the body. A blackout window's `school_partner_id`, a portfolio review's and a screening's `teaching_artist_id`, and an evaluation record's `session_id` are all set this way.

### 2.9. The Order in Which a Request Is Rejected

A single request can violate many rules at once, and the response must be deterministic. Checks are therefore evaluated in a fixed global order, and the **first** violated check decides the response. From highest priority to lowest:

1. Header presence and role validity — `ERR_UNAUTHENTICATED`.
2. The acting role is permitted on the endpoint — `ERR_UNAUTHORIZED`.
3. Path identifiers resolve, left to right — the entity-specific not-found codes.
4. Required body fields are present, and every supplied value satisfies its declared type, enum domain, numeric range, date or time format, and array constraints including non-emptiness and absence of duplicates — `ERR_INVALID_REQUEST`.
5. Body-supplied identifiers resolve, and every standards code resolves — the entity-specific not-found codes, or `ERR_UNKNOWN_STANDARD_CODE`.
6. Resource ownership for the two entity-backed roles — `ERR_ACTOR_NOT_RESOURCE_OWNER`.
7. The supplied parent version matches the parent's current `version` — `ERR_STALE_RESIDENCY_VERSION`, `ERR_STALE_SESSION_VERSION`, or `ERR_STALE_VOUCHER_VERSION`.
8. The target row is in a state from which the requested transition is declared, on the addressed axis, with a legal reason or decision value for that transition — `ERR_INVALID_STATE_TRANSITION`.
9. The child-safety screening gate: the artist involved is vetted and cleared — `ERR_ARTIST_NOT_CLEARED`.
10. Clearance is still valid on the session date — `ERR_CLEARANCE_EXPIRED`.
11. The artist's roster standing permits the operation — `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`.
12. The school's partnership health gate — `ERR_PARTNERSHIP_INTAKE_SUSPENDED` or `ERR_PARTNERSHIP_HEALTH_GATE`.
13. Curriculum linkage completeness — `ERR_NO_ALIGNED_LESSON_PLAN` or `ERR_STANDARDS_COVERAGE_INCOMPLETE`.
14. Evaluation and voucher-claim linkage — `ERR_EVALUATION_MISSING` or `ERR_SESSION_ALREADY_VOUCHERED`.
15. Funder-report linkage — `ERR_RESIDENCY_NOT_FINALIZED`.
16. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.
17. Capability tagging match between residency and artist — `ERR_DISCIPLINE_MISMATCH`, `ERR_GRADE_BAND_MISMATCH`, or `ERR_LANGUAGE_CAPABILITY_MISSING`.
18. Vetting and adaptation gate counters — `ERR_INSUFFICIENT_PORTFOLIO_REVIEWS`, `ERR_PORTFOLIO_THRESHOLD_NOT_MET`, `ERR_DEMO_ATTEMPT_LIMIT_REACHED`, `ERR_ADAPTATION_ROUND_LIMIT`, or `ERR_RELIABILITY_BELOW_FLOOR`.
19. Uniqueness and shape constraints — `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_STANDARD_CODE`, `ERR_DUPLICATE_SEQUENCE_NO`, `ERR_DUPLICATE_REVIEWER`, `ERR_MAKEUP_CREDIT_UNAVAILABLE`, or `ERR_SESSION_UNDERDELIVERED`.
20. The cancellation reason is permitted for the acting role — `ERR_CANCEL_REASON_NOT_PERMITTED`.
21. The classroom-teacher collaboration expectation — `ERR_CO_PLANNING_INCOMPLETE`.
22. Term and period containment — `ERR_SESSION_OUTSIDE_RESIDENCY_TERM` or `ERR_VOUCHER_PERIOD_MISMATCH`.
23. School calendar blackout — `ERR_CALENDAR_BLACKOUT`.
24. Artist resource occupation — `ERR_ARTIST_SCHEDULE_CONFLICT` or `ERR_TRAVEL_BUFFER_VIOLATION`.
25. School resource occupation — `ERR_SCHOOL_CAPACITY_EXCEEDED`.
26. Session allotment availability — `ERR_SESSION_ALLOTMENT_EXHAUSTED`.
27. Residency budget sufficiency — `ERR_RESIDENCY_BUDGET_EXCEEDED`.

Ordering matters in practice. A suspension that has already emptied a session's artist reference surfaces as a clearance or roster failure rather than as a scheduling conflict; a stale parent version surfaces before any business rule, so a client acting on an out-of-date read learns that fact first rather than receiving a misleading business rejection.

### 2.10. Child Safety as a Standing Gate

Screening is not a one-time onboarding step; it is a condition that must hold at the moment of every assignment and on the date each class is taught. Three screening types are required for a complete clearance set: `STATE_CRIMINAL`, `FBI_FINGERPRINT`, and `CHILD_ABUSE_REGISTRY`. An artist is cleared only when a current, non-superseded `CLEARED` result exists for **each** of those three types.

The screening gate — the artist involved must have vetting completed and clearance current — guards six operations: session creation, session confirmation, session reassignment, lead-artist assignment on a residency, moving a residency from draft to approved, and reinstating an artist onto the active roster. In all six, the rejection is `ERR_ARTIST_NOT_CLEARED` at HTTP 403.

The date-of-service gate is separate and narrower. Four operations additionally require that the artist's clearance still cover the session's own date, inclusive of the expiry date itself: session creation, session confirmation, session reassignment, and session delivery. A session dated after the clearance lapses is rejected with `ERR_CLEARANCE_EXPIRED` at HTTP 409, even though the artist may be cleared as of today.

### 2.11. Segregation of Duties

Three separations of duty are enforced structurally, and all three share the rejection code `ERR_SEGREGATION_OF_DUTIES` at HTTP 409.

The operator who records a teaching demonstration outcome — pass or fail — must not be any of the panelists who scored that artist's portfolio; the server compares the acting `X-User-ID` against every `reviewer_user_id` on that artist's portfolio reviews. The two review tracks on a payment voucher must be closed by different operator identifiers, so once one track is closed, the operator who closed it may not close the other. And the operator who certifies a funder report must differ from the operator who compiled the snapshot being certified.

### 2.12. The Two Conserved Quantities of a Residency

Each residency maintains two ledgers that the server must keep balanced after **every** request, not merely at end of term.

The **session obligation ledger** partitions the contracted allotment across five buckets: `sessions_unscheduled_count` (allotment not yet turned into a session row), `sessions_open_count` (sessions that are `PLANNED`, `CONFIRMED`, or `VACATED`), `sessions_delivered_count` (sessions that are `DELIVERED`), `sessions_forfeited_count` (cancelled sessions that earned no make-up credit, plus allotment written off at completion), and `makeup_credits_outstanding` (cancelled sessions that earned a make-up credit which has not yet been consumed). The sum of those five buckets always equals `contracted_session_count`. Cancelling a make-up-eligible session moves one unit from the open bucket to the outstanding-credit bucket; creating the make-up session moves it back to the open bucket. Neither leg ever changes `contracted_session_count`.

Alongside the counters, `vacated_session_count` reports how many of this residency's sessions currently sit in `VACATED` — a subset of the open bucket, tracked separately because it drives staffing status.

The **money ledger** partitions the budget across three accounts: `encumbered_cents`, the sum of the amounts currently held by this residency's sessions; `disbursed_cents`, the sum of `total_cents` over this residency's `APPROVED` vouchers; and `available_cents`, which is `budget_cents` less encumbered less disbursed. Available plus encumbered plus disbursed always equals `budget_cents`. Approving a voucher moves its total from encumbered to disbursed; voiding that voucher moves exactly the same total back from disbursed to encumbered and restores each claimed session's held amount to what it was payable at. Neither leg ever changes `budget_cents`.

Any operation that would drive `available_cents` below zero is refused rather than allowed to overdraw, with `ERR_RESIDENCY_BUDGET_EXCEEDED`. That guard applies to four operations: session confirmation, session reassignment, session delivery, and voucher submission.

## 3. Business Logic & Workflows

### 3.1. Recruiting the Roster: Portfolio, Demonstration, and Screening

A `RosterCoordinator` opens an applicant file by supplying the artist's `full_name`, an `email` that must be unique across the roster — a repeat address is refused with `ERR_DUPLICATE_EMAIL` — and the capability tags that will later decide what the artist may teach. Capability is three-dimensional: a `primary_discipline` drawn from `VISUAL_ARTS`, `DANCE`, `MUSIC`, `THEATER`, `MEDIA_ARTS`, and `LITERARY_ARTS`; an optional `secondary_disciplines` array drawn from the same six values and defaulting to empty; a non-empty `grade_bands` array whose elements come from `K_2`, `G3_5`, `G6_8`, and `G9_12`; and a non-empty `languages` array of lowercase two-letter ISO 639-1 codes, which must contain `en` or the instruction language of any residency the artist is later assigned to. Intake may also set a juried `roster_tier_assigned` of `APPRENTICE`, `TEACHING_ARTIST`, or `MASTER`; when omitted it defaults to `TEACHING_ARTIST`.

Every artist row carries **two independent lifecycle axes**, and confusing them is the most common modelling error in this domain. The recruitment axis, `vetting_status`, starts at `APPLIED` and ranges over `APPLIED`, `PORTFOLIO_REVIEW`, `DEMO_SCHEDULED`, `DEMO_FAILED`, `DEMO_PASSED`, `SCREENING_PENDING`, `CLEARED`, `DECLINED`, and `SCREEN_FAILED`, of which `DECLINED` and `SCREEN_FAILED` are terminal. The assignability axis, `roster_status`, starts at `NOT_LISTED` and ranges over `NOT_LISTED`, `ACTIVE`, `PROBATION`, `SUSPENDED`, and `RETIRED`, of which `RETIRED` is terminal. At intake the new row also gets `roster_tier_effective` equal to `roster_tier_assigned`, and both reliability figures — `reliability_bps_rolling` and `reliability_bps_program_year` — seeded at 10000 basis points. Every other derived field starts empty rather than at a guessed value: `portfolio_review_count`, `demo_attempt_count`, `lifetime_delivered_count` and `no_show_count` all begin at zero; `portfolio_mean_composite`, `demo_rubric_score`, `demo_evaluator_user_id` and `clearance_expires_on` all begin null; and `clearance_status` begins at `NONE`.

Advancing the recruitment axis is a `RosterCoordinator` capability that names the destination in a `to_vetting_status` field and may carry `demo_rubric_score` or `decline_reason` depending on where it is headed. The first hop, `APPLIED → PORTFOLIO_REVIEW`, requires only that the artist still be in `APPLIED`.

While the file sits in `PORTFOLIO_REVIEW`, panelists score it. Each portfolio review is recorded against the artist by a `RosterCoordinator` or a `CurriculumSpecialist` and carries the panelist's own `reviewer_user_id` plus three scores on a one-to-five scale in tenth-point steps: `artistic_quality_score`, `pedagogical_clarity_score`, and `cultural_responsiveness_score`. A given `reviewer_user_id` may score a given artist only once; a repeat is refused with `ERR_DUPLICATE_REVIEWER`. The panel weights artistic quality at forty percent (a factor of 0.40), pedagogical clarity at thirty-five percent (0.35), and cultural responsiveness at twenty-five percent (0.25): the review's `composite_score` is the sum of each score multiplied by its weight, rounded half up to two decimal places. That composite yields a `recommendation` of `ADVANCE` when it is at least 3.50, and `DECLINE` otherwise. Portfolio reviews are immutable observations; none of them is ever filtered out of a roll-up, and their order is irrelevant.

Each new review re-derives two artist-level figures. `portfolio_review_count` is the number of distinct `reviewer_user_id` values that have scored this artist, and `portfolio_mean_composite` is the arithmetic mean of `composite_score` across **all** of the artist's reviews, rounded half up to two decimal places; the mean is null while the artist has no reviews at all.

Scheduling the teaching demonstration — the `PORTFOLIO_REVIEW → DEMO_SCHEDULED` hop, which is also legal out of `DEMO_FAILED` — is where the panel's verdict bites. At least two distinct reviewers must have scored the portfolio, or the request is refused with `ERR_INSUFFICIENT_PORTFOLIO_REVIEWS`. The rounded `portfolio_mean_composite` must be at least 3.50 — a mean of exactly 3.50 passes — or the refusal is `ERR_PORTFOLIO_THRESHOLD_NOT_MET`. And the artist must have used fewer than two demonstration attempts, or the refusal is `ERR_DEMO_ATTEMPT_LIMIT_REACHED`. Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`. Coming out of `DEMO_FAILED` for a re-demonstration round, only the attempt-limit check applies, and in addition to bumping the attempt counter the server clears the previous outcome by setting both `demo_rubric_score` and `demo_evaluator_user_id` back to null. Because each entry into `DEMO_SCHEDULED` consumes an attempt and the limit is two, the demonstration cycle `DEMO_SCHEDULED → DEMO_FAILED → DEMO_SCHEDULED` can run at most twice in total.

The demonstration outcome is recorded on the same capability, and the two branches are symmetric. Moving `DEMO_SCHEDULED → DEMO_PASSED` requires a `demo_rubric_score` to be present and to lie between 1.0 and 5.0 inclusive — its absence or an out-of-range value is an `ERR_INVALID_REQUEST` — and that score must be at least 3.5, compared at one decimal place; the acting operator must not appear as a `reviewer_user_id` on any of this artist's portfolio reviews, on pain of `ERR_SEGREGATION_OF_DUTIES`. Moving `DEMO_SCHEDULED → DEMO_FAILED` likewise requires a `demo_rubric_score` to be present, and that score is below 3.5; the same segregation-of-duties check applies unchanged. Both branches persist the supplied score into `demo_rubric_score` and stamp `demo_evaluator_user_id` with the acting operator's identifier.

A file can be turned away from either review stage. `PORTFOLIO_REVIEW → DECLINED` requires the artist to currently be in either `PORTFOLIO_REVIEW` or `DEMO_FAILED`, and `DEMO_FAILED → DECLINED` carries no further precondition; both accept a `decline_reason` and both are terminal on the recruitment axis.

A passed demonstration moves to `DEMO_PASSED → SCREENING_PENDING` with no further precondition, and the file then waits on background screening. A `RosterCoordinator` records each screening result against the artist with a `screening_type` of `STATE_CRIMINAL`, `FBI_FINGERPRINT`, or `CHILD_ABUSE_REGISTRY`, an `outcome` of `CLEARED` or `FAILED`, the `effective_on` date the result took effect, an `expires_on` date that is required when the outcome is cleared and must be null when it failed, and an optional `adjudication_note`. When present, `expires_on` must fall strictly after `effective_on`, and it is treated as inclusive: the expiry date itself is still covered.

Recording a screening re-derives the artist's clearance window. For each of the three required types, the server picks that artist's latest row of the type — ordering by `effective_on` descending and breaking ties on `created_at` ascending, then taking the first — and marks every other row of that type with `superseded` set to true. If any required type has no row at all, or the latest row of any required type failed, then `clearance_status` is `NONE` and `clearance_expires_on` is null. Otherwise `clearance_expires_on` is the **earliest** `expires_on` among those three latest rows, and `clearance_status` is `CLEARED` when that date is on or after the current logical-clock date and `EXPIRED` when it is earlier. Clearance is re-evaluated on every read of the artist as well as at confirmation and delivery time, so a window can lapse without anybody touching the row.

With the window complete, `SCREENING_PENDING → CLEARED` becomes available. Its single precondition is that clearance genuinely holds — a non-superseded cleared result for every one of the three required types, with the earliest expiry on or after today — or the request is refused with `ERR_ARTIST_NOT_CLEARED`. Reaching `CLEARED` on the recruitment axis fires an automatic transition on the roster axis, moving `roster_status` from `NOT_LISTED` to `ACTIVE`, and recomputes `roster_tier_effective`.

A failed screening is the sharp edge of the recruitment story. Recording an outcome of `FAILED` drives the recruitment axis to `SCREEN_FAILED` from either `SCREENING_PENDING` or `CLEARED`, and in both cases the first link of Cascade A fires immediately: the roster axis is forced to `SUSPENDED`. When the failure arrives on an artist who was already `CLEARED`, the server additionally resets `clearance_status` to `NONE` and `clearance_expires_on` to null. Everything downstream of the roster suspension — vacated sessions, residency staffing, school health — follows exactly as described in §3.2, because it is the same cascade.

The roster is searchable by capability and lifecycle state: a `discipline`, `grade_band`, `language`, `vetting_status`, or `roster_status` filter may be supplied, alone or in combination. An artist's screenings and portfolio reviews are each listable under the artist.

### 3.2. Roster Standing, Reliability, and the Effective Fee Tier

A `ProgramDirector` moves the roster axis by naming a `to_roster_status`, optionally with a `reason`. The reachable moves are `ACTIVE → PROBATION`, `PROBATION → ACTIVE`, `ACTIVE → SUSPENDED`, `PROBATION → SUSPENDED`, `SUSPENDED → ACTIVE`, and retirement from `ACTIVE`, `PROBATION`, or `SUSPENDED`. Anything else on this axis is an `ERR_INVALID_STATE_TRANSITION`.

**Reliability** is what puts an artist on probation, and it is computed twice from the same underlying data in two deliberately different ways. The input set is the artist's *terminal, artist-attributable* sessions: rows where the artist is either the currently assigned artist or the recorded vacated artist, and whose status is `DELIVERED` or `CANCELLED_ARTIST`. A `CANCELLED_SCHOOL` session is never the artist's fault and is excluded from both figures. The set is ordered by `session_date` descending, breaking ties on `created_at` descending. Each session in the set is credited one if it was delivered and zero otherwise; the figure in basis points is 10000 multiplied by the number of credited sessions, divided by the number of sessions in the set, rounded half up to a whole number — and it is defined as zero when the set is empty.

The two variants differ only in which sessions enter the set. `reliability_bps_rolling` uses the **four most recent** rows of that ordered list, regardless of program year, and it is the only figure that can trigger probation. `reliability_bps_program_year` uses **every** terminal session whose `session_date` falls in the current program year — the twelve months from the first of July of one year through the thirtieth of June of the next, whichever such span contains the logical clock date — with no cap on count; it feeds tier promotion and funder reporting. Whenever more than four terminal sessions exist within the program year, the two figures diverge on identical data.

**Effective tier** is recomputed at artist creation, on every delivered session, and on every roster-axis transition. If the artist is on `PROBATION`, `roster_tier_effective` is the lower of `roster_tier_assigned` and `TEACHING_ARTIST`, comparing tiers by their rank in the ascending order `APPRENTICE`, then `TEACHING_ARTIST`, then `MASTER` — never by alphabetical string order. Otherwise, if the artist has at least 25 lifetime delivered sessions in `lifetime_delivered_count` **and** a program-year reliability of at least 9500 basis points, the effective tier is promoted to `MASTER`. Failing both of those, the effective tier is simply the assigned tier.

Moving `ACTIVE → PROBATION` — whether a director does it directly or Cascade B does it automatically — requires the artist to currently be `ACTIVE`, and it applies the probation tier cap described above, which in turn re-projects `projected_cost_cents` on every residency that holds an open session of this artist.

Coming back the other way, `PROBATION → ACTIVE` is gated on two conditions: the rolling reliability figure must be at least 8000 basis points, or the request is refused with `ERR_RELIABILITY_BELOW_FLOOR`; and clearance must currently hold, or the refusal is `ERR_ARTIST_NOT_CLEARED`. Reinstatement lifts the probation cap and recomputes the effective tier. Because probation is reversible, the `ACTIVE → PROBATION → ACTIVE` cycle may run any number of times.

Suspension carries no preconditions from either `ACTIVE` or `PROBATION`, and both branches fire the identical three remaining links of **Cascade A**. Link two: every session of this artist whose status is `PLANNED` or `CONFIRMED` moves to `VACATED`, with the artist's identifier copied from `assigned_artist_id` into `vacated_artist_id` and `assigned_artist_id` set to null; each session that was `CONFIRMED` also releases its held amount, subtracting the session's held cents from the residency's `encumbered_cents`, zeroing the session's own held amount, and recomputing `available_cents`. Link three: for every residency touched by link two, `vacated_session_count` gains one and `staffing_status` is recomputed, and if the suspended artist was that residency's `lead_artist_id`, the lead reference is cleared to null so the residency reads `LEAD_VACANT`. Link four: every school owning one of those residencies has its `partnership_health` recomputed.

Reinstatement out of `SUSPENDED` requires two things: clearance must hold, or the refusal is `ERR_ARTIST_NOT_CLEARED`; and the recruitment axis must itself read `CLEARED`, or the refusal is `ERR_INVALID_STATE_TRANSITION`. Reinstatement recomputes the effective tier — and, importantly, it does **not** re-staff the sessions the suspension vacated. Those sessions stay `VACATED` until somebody reassigns them.

Retirement is terminal. From `ACTIVE` or from `PROBATION` it requires that the artist hold no session in `PLANNED` or `CONFIRMED`, or the request is refused with `ERR_ARTIST_HAS_OPEN_SESSIONS`. From `SUSPENDED` there is no such precondition, because the suspension already vacated those sessions.

### 3.3. School Partnerships, Calendars, and Partnership Health

A `ProgramDirector` registers a school partner with a `name` between 1 and 120 characters, the `district_name` it belongs to, a human-readable `grade_span` label such as `K-8`, a `concurrent_session_capacity` of at least 1 describing how many arts-capable rooms the school has, a `total_enrollment` of at least 1, and three demographic shares of enrollment used later for funder reach: `frl_pct` for free or reduced lunch, `ell_pct` for English-language learners, and `iep_pct` for students on individualized education programs, each a fraction from 0.00 to 1.00 inclusive at two decimals. A newly registered school starts with `partnership_health` of `HEALTHY` and `open_residency_count` of zero.

**Partnership health** is derived, never set. The server looks at the school's residencies whose status is `DRAFT`, `APPROVED`, `ACTIVE`, or `SUSPENDED` — residencies that are `COMPLETED`, `CLOSED`, or `CANCELLED` never affect health at all. If any residency in that set is `SUSPENDED`, health reads `INTAKE_SUSPENDED`. Otherwise, if any residency in that set has a `staffing_status` of `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`. Otherwise health reads `HEALTHY`. The size of that same set is published as `open_residency_count`. Health is recomputed on any residency status change or staffing change at the school.

Health is a gate, not a label. `INTAKE_SUSPENDED` blocks three things at that school: creating a new residency, moving a residency from `DRAFT` to `APPROVED`, and creating a session — all refused with `ERR_PARTNERSHIP_INTAKE_SUSPENDED` at HTTP 403. `WATCH` is narrower: it blocks session creation only, and only when the target residency's `staffing_status` is not `STAFFED` and the requested `session_type` is not `MAKEUP`; that refusal is `ERR_PARTNERSHIP_HEALTH_GATE`, also at HTTP 403. In other words, a school on watch may still receive make-up sessions and may still schedule into a fully staffed residency.

School calendars are expressed as blackout windows. A `RosterCoordinator` or the school's own `SchoolLiaison` adds a window with a `blackout_type` of `HOLIDAY`, `TESTING_WINDOW`, `PROFESSIONAL_DEVELOPMENT`, or `CLOSURE`, a `start_date`, an `end_date` no earlier than the start, and an optional free-text `note` that defaults to null. Both dates are ISO 8601 calendar dates and the interval is **closed at both ends**: the end date is itself blacked out. Adding a window never retroactively cancels sessions that are already on the books; it takes effect on the next session creation and on the next confirmation, both of which refuse a date inside any of the school's windows with `ERR_CALENDAR_BLACKOUT`.

### 3.4. Scoping a Residency and Driving Its Lifecycle

A residency is the contract between the organization and one school for one arc of instruction, and either a `ProgramDirector` or a `RosterCoordinator` may scope one. The payload names the host school through `school_partner_id`, gives the residency a `title`, and fixes the artistic and instructional frame: a `discipline` from the same six-value domain as artist disciplines, a `grade_band` from `K_2`, `G3_5`, `G6_8`, or `G9_12`, and an `instruction_language` as a lowercase two-letter code that defaults to `en`. It fixes the scale of the commitment with a `contracted_session_count` between 1 and 60 and a `session_length_minutes` between 30 and 120 that must be a multiple of 5. It fixes the money with a `budget_cents` of at least 1 and an optional `materials_stipend_cents` earmark that defaults to zero and is informational only — actual per-session materials reimbursement is capped independently, as §3.7 explains. It fixes the collaboration frame with a `collaboration_expectation` of `CO_TEACH`, `OBSERVE`, or `PLANNING_ONLY` and an optional `co_planning_hours_required` between 0 and 20 hours that the classroom teacher owes across the residency, defaulting to zero. It fixes curriculum ambition with a non-empty `required_strands` array drawn from `CREATING`, `PERFORMING`, `RESPONDING`, and `CONNECTING`. It fixes the calendar with a `term_start_date` and a `term_end_date` no earlier than the start, both inclusive bounds on session dates. And it fixes the reporting base with an `enrolled_student_count` of at least 1, the unduplicated headcount that funder reporting will draw on.

A freshly scoped residency has a `status` of `DRAFT`, a `staffing_status` of `LEAD_VACANT`, and every ledger counter and money field at zero. Creating it recomputes the host school's `open_residency_count` and `partnership_health`. Residencies are listable with `school_partner_id`, `lead_artist_id`, `status`, and `staffing_status` filters.

Assigning the lead artist is a separate step available to a `ProgramDirector` or a `RosterCoordinator`, which names a `teaching_artist_id` and writes it into `lead_artist_id`. The nominated artist must be vetted and cleared (`ERR_ARTIST_NOT_CLEARED`), must have a `roster_status` of `ACTIVE` (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`), and must be capable of the work: the residency's discipline must appear among the artist's primary and secondary disciplines, the residency's grade band must appear in the artist's `grade_bands`, and the residency's instruction language must appear in the artist's `languages` — refused respectively with `ERR_DISCIPLINE_MISMATCH`, `ERR_GRADE_BAND_MISMATCH`, and `ERR_LANGUAGE_CAPABILITY_MISSING`, all at HTTP 422. Assignment recomputes `staffing_status`, recomputes the school's `partnership_health`, and re-projects `projected_cost_cents`. The same capability replaces an existing lead.

**Staffing status** follows a strict precedence with no ties. If `lead_artist_id` is null, `staffing_status` is `LEAD_VACANT`. Otherwise, if at least one of the residency's sessions is `VACATED`, it is `AT_RISK`. Otherwise it is `STAFFED`. `LEAD_VACANT` outranks `AT_RISK`, which outranks `STAFFED`. It is recomputed on lead assignment, on session vacating, reassignment, or cancellation, and on artist suspension.

The residency lifecycle itself is driven by a `ProgramDirector` naming a `to_status`, optionally with a `reason`. The `status` domain is `DRAFT`, `APPROVED`, `ACTIVE`, `SUSPENDED`, `COMPLETED`, `CLOSED`, and `CANCELLED`; `CLOSED` and `CANCELLED` are terminal.

`DRAFT → APPROVED` is the moment the commitment becomes real, and it has three preconditions: a lead artist must be assigned, or the transition is refused with `ERR_INVALID_STATE_TRANSITION`; that lead artist must have a `vetting_status` of `CLEARED` and a `roster_status` of `ACTIVE`, or the refusal is `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`; and the host school's `partnership_health` must not be `INTAKE_SUSPENDED`, or the refusal is `ERR_PARTNERSHIP_INTAKE_SUSPENDED`. Approval initializes the allotment by setting `sessions_unscheduled_count` to `contracted_session_count`, and initializes the money ledger by setting `available_cents` to `budget_cents` with `encumbered_cents` and `disbursed_cents` both at zero.

`APPROVED → ACTIVE` is gated on curriculum readiness and is described from the curriculum side in §3.5: at least one lesson plan of this residency must be `ALIGNED`, or the transition is refused with `ERR_NO_ALIGNED_LESSON_PLAN`; and the union of `covered_strands` across all of this residency's `ALIGNED` plans must include every entry of `required_strands`, or the refusal is `ERR_STANDARDS_COVERAGE_INCOMPLETE`.

`ACTIVE → SUSPENDED` takes a `reason` and is destructive by design. Every session of the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED` is driven to `CANCELLED_SCHOOL` with a `cancel_reason` of `RESIDENCY_DESCOPED` and `makeup_eligible` set to false; each one releases whatever it was holding against the money ledger and adds one to `sessions_forfeited_count`. The host school's `partnership_health` is then recomputed, which — because a suspended residency is present — yields `INTAKE_SUSPENDED`.

`SUSPENDED → ACTIVE` brings the residency back, and its one precondition is that `staffing_status` must not be `LEAD_VACANT`, or the resume is refused with `ERR_INVALID_STATE_TRANSITION`. Resuming recomputes the school's `partnership_health`. The `ACTIVE → SUSPENDED → ACTIVE` cycle may repeat.

`ACTIVE → COMPLETED` requires that `sessions_open_count` be exactly zero — no `PLANNED`, `CONFIRMED`, or `VACATED` session may remain — or the request is refused with `ERR_RESIDENCY_HAS_OPEN_SESSIONS`. Completion runs a forfeiture sweep that writes off everything still owed: `sessions_forfeited_count` gains the sum of `sessions_unscheduled_count` and `makeup_credits_outstanding`; every unconsumed make-up credit is closed out by setting `makeup_consumed` to true on the cancelled origin session that issued it and driving `makeup_credits_outstanding` to zero; and `sessions_unscheduled_count` is set to zero. The five-bucket session obligation identity of §2.12 still holds after the sweep — the units simply moved into the forfeited bucket.

`COMPLETED → CLOSED` is the accounting close. No payment voucher of this residency may be in `DRAFT` or `SUBMITTED`, and `encumbered_cents` must be exactly zero; either violation is refused with `ERR_RESIDENCY_HAS_OPEN_VOUCHERS`. Closing archives the curriculum: every lesson plan of the residency whose status is `SUBMITTED`, `CHANGES_REQUESTED`, or `ALIGNED` becomes `ARCHIVED`.

`DRAFT → CANCELLED` takes a `reason` and is available only before approval; it requires `sessions_open_count` to be zero and archives every lesson plan of the residency. Both `CLOSED` and `CANCELLED` are terminal: no further status move is declared from either.

Reading a residency exposes both cost-outlook figures side by side. `earned_to_date_cents` is the chronological, backward-looking figure: the sum of `payable_cents` over this residency's `DELIVERED` sessions, at the actual fees and reimbursements recorded at delivery, with real prorated minutes and real mileage. It is the only figure a payment voucher may draw against. `projected_cost_cents` is the forward-looking figure the program director watches against `budget_cents`: it starts from `earned_to_date_cents`, adds a full-length fee projection for every session of the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED`, and then adds one lead projection for each remaining unscheduled allotment unit and each outstanding make-up credit — that is, `sessions_unscheduled_count` plus `makeup_credits_outstanding` lead projections. Cancelled sessions of either kind are excluded from both figures.

A projection for an existing open session evaluates the session fee rules of §3.7 with delivered minutes taken to be the residency's full `session_length_minutes`, using the session's own assigned artist — or, when the session is `VACATED` and therefore has no assigned artist, using the residency's lead artist. A **lead projection** evaluates the same fee rules for a hypothetical regular, non-substitute, full-length session of this residency taught by the residency's lead artist with the lead premium applied; when `lead_artist_id` is null, the lead projection is instead evaluated at the `TEACHING_ARTIST` tier multiplier with no lead premium and no language premium. Because the projected figure includes work not yet performed, it differs from the earned figure whenever any allotment remains. Both are recomputed on session confirmation, reassignment, cancellation, and delivery, on voucher approval and voiding, on lead-artist assignment, and on any artist tier change.

### 3.5. Curriculum Alignment to State Arts Standards

The standards catalog is maintained by a `ProgramDirector` or a `CurriculumSpecialist`. Each arts standard carries a `code` of 3 to 24 characters that must be unique across the catalog — a repeat is refused with `ERR_DUPLICATE_STANDARD_CODE` — a `discipline` from the six-value discipline domain, a `grade_band` from the four-value band domain, a `strand` of `CREATING`, `PERFORMING`, `RESPONDING`, or `CONNECTING`, and the standard's `description` text. The catalog is browsable with `discipline`, `grade_band`, and `strand` filters.

A lesson plan is submitted against a residency by the artist who wrote it or by a `RosterCoordinator` on their behalf. The payload names the `residency_id`, gives the plan a `title`, places it in the arc with a `session_sequence_no` between 1 and 60 that must be unique among that residency's plans — a collision is refused with `ERR_DUPLICATE_SEQUENCE_NO` — lists the standards it covers in a non-empty `standard_codes` array whose elements must each match an existing standard's `code` and must contain no duplicates, and may carry a `materials_list` and an `adaptation_summary`, both defaulting to null. Authorship is recorded rather than supplied: `author_artist_id` becomes the acting `X-User-ID` when a `TeachingArtist` submits the plan, and otherwise becomes the residency's `lead_artist_id`. A new plan starts with a `status` of `SUBMITTED` and a `revision_round` of zero, and the server derives `covered_strands` as the distinct set of `strand` values on the standards resolved from `standard_codes`. Plans are listable with `residency_id`, `author_artist_id`, and `status` filters, and a plan read exposes `reviewer_note`, `reviewer_user_id`, and `aligned_on` alongside its coverage.

Plan status ranges over `SUBMITTED`, `CHANGES_REQUESTED`, `ALIGNED`, and the terminal `ARCHIVED`. A `CurriculumSpecialist` reviews a plan by supplying a `decision` — `ALIGN` or `REQUEST_CHANGES` — and, for a change request, a `reviewer_note`.

`SUBMITTED → ALIGNED` under an `ALIGN` decision checks the plan's standards against the residency's frame. Every code in `standard_codes` must resolve to a catalog row, or the review is refused with `ERR_UNKNOWN_STANDARD_CODE`. Every resolved standard's `discipline` must equal the residency's `discipline`, or the refusal is `ERR_DISCIPLINE_MISMATCH`. Every resolved standard's `grade_band` must equal the residency's `grade_band`, or the refusal is `ERR_GRADE_BAND_MISMATCH`. And `covered_strands` must be non-empty. Note carefully what is *not* required here: a single plan need not cover every entry of the residency's `required_strands`. Strand completeness is a residency-level question, evaluated at activation over the union of all the residency's aligned plans. Aligning a plan stamps `aligned_on` with the current logical-clock instant and records the acting operator in `reviewer_user_id`.

`SUBMITTED → CHANGES_REQUESTED` under a `REQUEST_CHANGES` decision requires that `revision_round` be less than 3, or the review is refused with `ERR_ADAPTATION_ROUND_LIMIT`. It adds one to `revision_round`, stores the supplied `reviewer_note`, and records the acting operator in `reviewer_user_id`.

A plan that has already been aligned can be pulled back. `ALIGNED → CHANGES_REQUESTED` requires the same round-limit headroom — `revision_round` below 3, else `ERR_ADAPTATION_ROUND_LIMIT` — and additionally requires that no session naming this plan as its `lesson_plan_id` has reached `DELIVERED`, or the pull-back is refused with `ERR_INVALID_STATE_TRANSITION`. It adds one to `revision_round`, clears `aligned_on` back to null, and records the supplied `reviewer_note` and the acting operator's `reviewer_user_id` exactly as the other change-request branch does. Pulling a plan back does not itself change the residency's `staffing_status`, but if the residency has no other aligned plan whose strands cover `required_strands`, activation of that residency becomes blocked again.

The artist answers a change request by resubmitting an adaptation, which drives `CHANGES_REQUESTED → SUBMITTED`. Either the authoring `TeachingArtist` or a `RosterCoordinator` may do this; when a `TeachingArtist` acts, their `X-User-ID` must equal the plan's `author_artist_id`, or the request is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`. The round limit applies here too: `revision_round` must be below 3, else `ERR_ADAPTATION_ROUND_LIMIT`. The payload must carry an `adaptation_summary` describing what changed, and may replace `standard_codes`, `title`, or `materials_list`; when `standard_codes` is supplied, `covered_strands` is recomputed from the newly resolved standards. Because each change request consumes one round and the limit is 3, the `SUBMITTED → CHANGES_REQUESTED → SUBMITTED` adaptation cycle is bounded at three rounds.

Finally, plans are archived by the residency rather than by a reviewer. When a residency reaches `CLOSED` or `CANCELLED`, each of its plans in `ALIGNED`, `SUBMITTED`, or `CHANGES_REQUESTED` transitions to `ARCHIVED`.

### 3.6. Scheduling Sessions Across School Calendars

Only a `RosterCoordinator` may put a session on the calendar. The payload names the `residency_id` and the `assigned_artist_id`, fixes the `session_date` as an ISO 8601 calendar date, fixes the local time window with a `start_time` and `end_time` in 24-hour `HH:MM` form where the start must be a multiple of 5 minutes and the end must be strictly after the start, and carries the `expected_residency_version` described in §2.6. It may set a `session_type` of `REGULAR` or `MAKEUP`, defaulting to `REGULAR`; it may name the `lesson_plan_id` the session will teach; and for a make-up session it names the cancelled session whose credit it consumes through `makeup_for_session_id`. A new session is created in `PLANNED` status with `vacated_artist_id`, `payment_voucher_id`, and `cancel_reason` null; with its own held amount `encumbered_cents` at zero, that field being an integer that is never null; with the four delivery measurements `students_present_count`, `minutes_delivered`, `travel_miles`, and `materials_spend_cents` and the four computed money figures `fee_cents`, `travel_reimbursement_cents`, `materials_reimbursement_cents`, and `payable_cents` all null rather than zero, because none of them has been measured yet — those eight fields are populated only by the delivery report of §3.7, so a session that never reaches `DELIVERED` keeps them null; and with `is_substitute` false, `co_planning_completed` false, `makeup_eligible` false, and `makeup_consumed` false.

Session status ranges over `PLANNED`, `CONFIRMED`, `VACATED`, and the three terminal values `DELIVERED`, `CANCELLED_SCHOOL`, and `CANCELLED_ARTIST`. The schedule is searchable with `residency_id`, `assigned_artist_id`, `vacated_artist_id`, `lesson_plan_id`, `makeup_for_session_id`, `payment_voucher_id`, and `status` filters plus a `session_date_from` and `session_date_to` date range.

Creation runs the widest gauntlet of checks in the system. The assigned artist must be vetted and cleared (`ERR_ARTIST_NOT_CLEARED`), must still be covered on the session's own date (`ERR_CLEARANCE_EXPIRED`), and must have a `roster_status` of `ACTIVE` (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`). The school's partnership health gate of §3.3 applies. The artist must be capable of the residency's discipline, grade band, and instruction language, with the three capability codes of §3.4. The `session_date` must fall inside the closed interval from `term_start_date` to `term_end_date`, or the request is refused with `ERR_SESSION_OUTSIDE_RESIDENCY_TERM`. And the allotment must support the request: a `REGULAR` session requires `sessions_unscheduled_count` to be at least 1, or the refusal is `ERR_SESSION_ALLOTMENT_EXHAUSTED`; a `MAKEUP` session requires `makeup_credits_outstanding` to be at least 1 together with a matching origin session, and a make-up request that names a session which is not an unconsumed, make-up-eligible cancellation of the **same** residency — or which omits `makeup_for_session_id` altogether — is refused with `ERR_MAKEUP_CREDIT_UNAVAILABLE`.

Three independent resources must also be free, and this is where the interval arithmetic matters. A session occupies the **half-open** local interval running from its `start_time` up to but not including its `end_time`, on its `session_date`. Only sessions in `PLANNED`, `CONFIRMED`, or `DELIVERED` block anything; `VACATED` and cancelled sessions never block. When rechecking on a reassignment, the candidate session itself is excluded from the blocking set.

- **The artist** is checked pairwise against each of their other blocking sessions on the same date. If the two half-open intervals overlap, the request is refused with `ERR_ARTIST_SCHEDULE_CONFLICT`. If they do not overlap but the two sessions belong to residencies at *different* schools and the gap between the intervals is less than 45 minutes, the refusal is `ERR_TRAVEL_BUFFER_VIOLATION`. The gap is the non-negative distance between the two intervals, so two sessions that abut exactly — gap of zero — are permitted at the same school and rejected at different schools.
- **The school** is checked as an aggregate capacity rather than pairwise. Take the sorted set of all start and end instants of the candidate session together with every blocking session of the **same school** on that date. At each such boundary instant, count how many of those intervals contain it, remembering that an interval ending exactly at that instant does not count. If that count anywhere exceeds the school's `concurrent_session_capacity`, the request is refused with `ERR_SCHOOL_CAPACITY_EXCEEDED`.
- **The school calendar** is checked as a closed date interval: if any blackout window of the school has a `start_date` on or before the `session_date` and an `end_date` on or after it, the refusal is `ERR_CALENDAR_BLACKOUT`.

Creating the session updates the residency's ledger: a `REGULAR` session subtracts one from `sessions_unscheduled_count`, while a `MAKEUP` session leaves that counter alone and instead sets `makeup_consumed` to true on its origin session and subtracts one from `makeup_credits_outstanding`. Either way `sessions_open_count` gains one, `projected_cost_cents` is recomputed, and the residency's `version` increments.

**Confirmation** is the classroom teacher's commitment, performed by the host school's `SchoolLiaison` or by a `RosterCoordinator`, and it carries just two fields: the `classroom_teacher_name` who will collaborate, and a boolean `co_planning_completed`. The `PLANNED → CONFIRMED` transition has seven preconditions. The residency must be `ACTIVE`, or the refusal is `ERR_INVALID_STATE_TRANSITION`. The session must have an `assigned_artist_id` and that artist must be vetted and cleared, or the refusal is `ERR_ARTIST_NOT_CLEARED`. That artist's `roster_status` must be `ACTIVE`, or the refusal is `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`. The artist's `clearance_expires_on` must be on or after the `session_date`, inclusive, or the refusal is `ERR_CLEARANCE_EXPIRED`. The session must name a `lesson_plan_id` whose plan is `ALIGNED`, or the refusal is `ERR_NO_ALIGNED_LESSON_PLAN`. When the residency's `collaboration_expectation` is `CO_TEACH`, the supplied `co_planning_completed` must be true, or the refusal is `ERR_CO_PLANNING_INCOMPLETE`; the `OBSERVE` and `PLANNING_ONLY` expectations impose no such requirement. And the `session_date` must not fall inside any blackout window of the residency's school, or the refusal is `ERR_CALENDAR_BLACKOUT`.

Confirmation persists both supplied fields and then **encumbers** the money it expects to owe. The server evaluates the session fee rules of §3.7 as though the artist had taught the full `session_length_minutes`, writes that amount into the session's own `encumbered_cents`, adds it to the residency's `encumbered_cents`, and recomputes `available_cents`. If that would drive `available_cents` below zero, the transition is refused with `ERR_RESIDENCY_BUDGET_EXCEEDED` instead. Confirmation also recomputes `projected_cost_cents` and increments both the session's and the residency's `version`.

### 3.7. Delivery, Substitute Coverage, and Cancellation

Only the artist who holds the session may report its delivery: the acting `X-User-ID` must equal `assigned_artist_id`, or the request is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`. The report carries four measurements — `students_present_count` as the headcount actually in the room, `minutes_delivered` as the minutes actually taught, `travel_miles` as the one-way-adjusted reimbursable mileage at one decimal place, and `materials_spend_cents` as out-of-pocket materials spend.

`CONFIRMED → DELIVERED` has four preconditions beyond ownership. The residency must be `ACTIVE`, or the refusal is `ERR_INVALID_STATE_TRANSITION`. At least half the scheduled length must have been taught — `minutes_delivered` must be at least the residency's `session_length_minutes` multiplied by one half and rounded **up** to a whole minute — or the refusal is `ERR_SESSION_UNDERDELIVERED` at HTTP 422. The artist's clearance must still cover the `session_date`, inclusive, or the refusal is `ERR_CLEARANCE_EXPIRED`. And the money must be there: the amount by which the session's final payable figure exceeds what the session was already holding must not exceed the residency's `available_cents`, or the refusal is `ERR_RESIDENCY_BUDGET_EXCEEDED`.

**The session fee.** The artist's `fee_cents` is built in a pinned sequence of steps, with round-half-up applied at each step, not only at the end.

1. Start from the base rate for the residency's `discipline`: 11,000 cents for `VISUAL_ARTS`, 12,000 for `DANCE`, 12,500 for `MUSIC`, 11,500 for `THEATER`, 13,000 for `MEDIA_ARTS`, and 10,500 for `LITERARY_ARTS`.
2. Multiply by the grade-band factor for the residency's `grade_band` and round: 1.00 for `K_2`, 1.05 for `G3_5`, 1.10 for `G6_8`, and 1.15 for `G9_12`.
3. Multiply that graded amount by the factor for the artist's `roster_tier_effective` and round: 0.90 for `APPRENTICE`, 1.00 for `TEACHING_ARTIST`, and 1.20 for `MASTER`. The effective tier is read at the moment of the call, which for a delivery means the tier the artist held going in — the session being reported is not yet part of `lifetime_delivered_count` when the tier is read.
4. Compute a lead premium of ten percent (a factor of 0.10) of that tiered amount, rounded, but only when the session's `assigned_artist_id` equals the residency's `lead_artist_id`; otherwise the premium is zero.
5. Compute a language premium of a flat 1,500 cents, but only when the residency's `instruction_language` is something other than `en` **and** that language appears in the artist's `languages`; otherwise it is zero.
6. Add the tiered amount, the lead premium, and the language premium together.
7. If the session's `is_substitute` flag is true, multiply that sum by 0.85 and round; otherwise multiply by 1.00 and round.
8. **Cap before prorating** — this order is load-bearing. Clamp the result into the band from 9,000 cents to 19,000 cents: take the larger of the result and 9,000, then take the smaller of that and 19,000.
9. Round `minutes_delivered` **up** to the next whole 5-minute block to get billed minutes, then form the proration factor as billed minutes divided by the residency's `session_length_minutes`, capped at 1.00 so overtime is never paid.
10. Multiply the clamped amount by the proration factor and round half up. That is `fee_cents`.

Prorating before capping would produce a different — and wrong — number whenever the uncapped fee exceeds 19,000 cents and the artist taught less than the full scheduled length.

**Reimbursements.** The first 10.0 miles of each session's travel are absorbed by the organization. Billable miles are `travel_miles` less 10.0, floored at zero, and `travel_reimbursement_cents` is billable miles multiplied by 67 cents per mile, rounded half up. `materials_reimbursement_cents` is the lesser of the reported `materials_spend_cents` and a per-session cap of 2,500 cents — the residency's `materials_stipend_cents` earmark does not raise or lower that cap. The session's `payable_cents` is the sum of `fee_cents`, `travel_reimbursement_cents`, and `materials_reimbursement_cents`. Each session's reimbursement is rounded on its own before any voucher sums it.

Delivery then cascades. The money held by the session is swapped for the real figure: the residency's `encumbered_cents` gains the difference between `payable_cents` and what the session was holding, the session's `encumbered_cents` becomes `payable_cents`, and `available_cents` is recomputed. The residency's `sessions_open_count` loses one, `sessions_delivered_count` gains one, and both `earned_to_date_cents` and `projected_cost_cents` are recomputed. The artist's `lifetime_delivered_count` gains one, both reliability figures are recomputed, and `roster_tier_effective` is recomputed — which is how the twenty-fifth delivery can promote an artist to `MASTER`. The residency's `evaluation_index` is recomputed. And every funder report currently in `COMPILED` whose `scope_residency_ids` contains this residency and whose reporting period contains this `session_date` is pushed back to `DRAFT` with an `invalidated_reason` of `SCOPE_DELIVERY_CHANGED`. Both the session's and the residency's `version` increment.

**Substitute coverage** is a `RosterCoordinator` capability that names a `substitute_artist_id` alongside the `expected_session_version` of §2.6, and it exists in two symmetric forms.

The first form recovers a session that Cascade A emptied: `VACATED → CONFIRMED`. The substitute must have a `vetting_status` of `CLEARED` and a `roster_status` of `ACTIVE`, or the request is refused with `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`; must match the residency's discipline, grade band, and instruction language, with the three capability codes; and must be free of scheduling conflict under the artist, school-capacity, and buffer rules of §3.6, yielding `ERR_ARTIST_SCHEDULE_CONFLICT` or `ERR_TRAVEL_BUFFER_VIOLATION` as appropriate. On success, `assigned_artist_id` becomes the substitute and `is_substitute` becomes true; the session re-encumbers at the substitute rate, its held amount being the full-length fee computed with the substitute factor applied, after which the residency's `encumbered_cents` and `available_cents` are recomputed; the residency's `vacated_session_count` loses one and `staffing_status` is recomputed; and the owning school's `partnership_health` is recomputed. Both versions increment.

The second form swaps the artist without ever vacating the slot: `CONFIRMED → CONFIRMED`. The `substitute_artist_id` must differ from the current `assigned_artist_id`, or the request is refused with `ERR_INVALID_REQUEST`. Otherwise the capability, roster, clearance, and interval preconditions are exactly those of the first form, and the version check is the same. On success, the outgoing artist's identifier is copied into `vacated_artist_id`, `assigned_artist_id` becomes the substitute, and `is_substitute` becomes true; the held amount is swapped for the substitute-rate figure and the residency's `encumbered_cents`, `available_cents`, and `projected_cost_cents` are recomputed. Both versions increment. Either form may push `available_cents` negative in principle, and in that case the swap is refused with `ERR_RESIDENCY_BUDGET_EXCEEDED`.

**Cancellation** is available to a `SchoolLiaison`, a `RosterCoordinator`, or a `TeachingArtist`, and carries a `cancel_reason` and an optional `note`. Which reasons a role may use is itself a rule: a `SchoolLiaison` may use `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, or `LOW_ENROLLMENT`; a `TeachingArtist` may use `ARTIST_ILLNESS` only, and only on their own session; a `RosterCoordinator` may use any reason except `RESIDENCY_DESCOPED`, which is reserved for the system's own descoping sweep. A reason outside the acting role's permitted set — or any client use of `RESIDENCY_DESCOPED` — is refused with `ERR_CANCEL_REASON_NOT_PERMITTED` at HTTP 403, and an artist reaching for somebody else's session is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`.

The reason also decides whether the school gets the session back. `makeup_eligible` becomes true when the reason is `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or `ARTIST_NO_SHOW`, and false when it is `LOW_ENROLLMENT` or `RESIDENCY_DESCOPED`.

School-side cancellation — reasons `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, or `LOW_ENROLLMENT` — drives the session to `CANCELLED_SCHOOL` from `PLANNED`, from `CONFIRMED`, or from `VACATED`, and the three branches differ only in what they have to unwind. From `PLANNED` there is nothing held, so the effects are just the eligibility flag and the ledger move: `sessions_open_count` loses one, and `makeup_credits_outstanding` gains one when the session was make-up-eligible while `sessions_forfeited_count` gains one when it was not. From `CONFIRMED` the same ledger move happens, preceded by releasing the held amount — the residency's `encumbered_cents` loses the session's held cents, the session's held amount is zeroed, and `available_cents` is recomputed — and followed by recomputing `projected_cost_cents`. From `VACATED` there is again nothing held, but the staffing picture changes: `sessions_open_count` loses one, `vacated_session_count` also loses one, `staffing_status` is recomputed, and the owning school's `partnership_health` is recomputed, alongside the same eligibility-driven credit-or-forfeit move. All three branches increment both the session's and the residency's `version`.

Artist-side cancellation — reasons `ARTIST_ILLNESS` or `ARTIST_NO_SHOW` — drives the session to `CANCELLED_ARTIST` from `CONFIRMED` or from `PLANNED`, and this is **Cascade B**. Link one terminates the session as an artist cancellation with `makeup_eligible` true, releases whatever it was holding, subtracts one from `sessions_open_count`, and adds one to `makeup_credits_outstanding`; the `PLANNED` branch is identical except that there is no held amount to release. Link two, caused by the artist-cancellation outcome, adds one to the artist's `no_show_count` when and only when the reason was `ARTIST_NO_SHOW`, and recomputes both `reliability_bps_rolling` and `reliability_bps_program_year`. Link three, caused by the rolling figure falling below 8000 basis points once the artist has at least four terminal sessions on record, moves the artist's `roster_status` from `ACTIVE` to `PROBATION`. Link four, caused by entering probation, caps `roster_tier_effective` at the lower of `roster_tier_assigned` and `TEACHING_ARTIST` and re-projects `projected_cost_cents` for every residency holding an open session of that artist. Both versions increment.

### 3.8. Paying the Artist: Vouchers and the Two-Track Review

A payment voucher is opened by the payee artist themselves or by a `RosterCoordinator`, and it spans three aggregates at once: it names a `teaching_artist_id` as payee, a `residency_id` as the account being charged, and a non-empty, duplicate-free `session_ids` array listing the delivered sessions being claimed. It also fixes the pay period with a `period_start` and a `period_end` no earlier than the start, both inclusive. When a `TeachingArtist` opens the voucher, the named payee must be themselves, or the request is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`. Every claimed session must belong to the named residency and the named artist. Creation already applies three of the linkage rules that submission will re-apply: a session already claimed by a different voucher is refused with `ERR_SESSION_ALREADY_VOUCHERED`; a claimed session lacking an `OBSERVATION_RUBRIC` evaluation with all three rubric scores is refused with `ERR_EVALUATION_MISSING`; and a claimed session whose `session_date` falls outside the closed period from `period_start` to `period_end` is refused with `ERR_VOUCHER_PERIOD_MISMATCH`. A new voucher starts with a `status` of `DRAFT`, both review tracks at `PENDING`, and its `void_reason` null; each claimed session gets its `payment_voucher_id` pointed at the new voucher.

Voucher money is pure aggregation over the claimed sessions, with no further rounding: `session_fee_subtotal_cents` is the sum of their `fee_cents`, `travel_reimbursement_cents` is the sum of their per-session travel figures — already rounded individually, which is why summing raw mileage first would give a different answer — `materials_reimbursement_cents` is the sum of their per-session materials figures, and `total_cents` is those three subtotals added together. Vouchers are listable with `teaching_artist_id`, `residency_id`, `session_ids`, and `status` filters.

Voucher status ranges over `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, and the terminal `VOIDED`. Alongside `status`, two **independent review axes** run in parallel once the voucher is submitted: `fiscal_review_status` and `program_review_status`, each of which reads `PENDING`, `PASSED`, or `FAILED`, with `fiscal_reviewed_by` and `program_reviewed_by` recording who closed each.

Submission, by the payee artist or a `RosterCoordinator`, takes no payload and drives `DRAFT → SUBMITTED`. Four preconditions apply. Every session in `session_ids` must be `DELIVERED`, or the submission is refused with `ERR_INVALID_STATE_TRANSITION`. Every one of them must carry at least one evaluation record of type `OBSERVATION_RUBRIC` with all three rubric scores present, or the refusal is `ERR_EVALUATION_MISSING`. Every one of their `session_date` values must fall inside the closed pay period from `period_start` to `period_end`, or the refusal is `ERR_VOUCHER_PERIOD_MISMATCH` at HTTP 422. And `total_cents` must not exceed the residency's `encumbered_cents`, or the refusal is `ERR_RESIDENCY_BUDGET_EXCEEDED`. Submission sets both review tracks to `PENDING` and recomputes the three subtotals and `total_cents`.

A rejected voucher can be corrected and resubmitted, driving `REJECTED → SUBMITTED`. All four preconditions above apply unchanged, plus one more: every session in `session_ids` must have a `payment_voucher_id` that is either null or this same voucher, or the resubmission is refused with `ERR_SESSION_ALREADY_VOUCHERED`. Resubmission resets both tracks to `PENDING` **and** clears both `fiscal_reviewed_by` and `program_reviewed_by` back to null, and re-points every claimed session's `payment_voucher_id` at this voucher. The `SUBMITTED → REJECTED → SUBMITTED` cycle is therefore unbounded in count.

Review closes one track at a time. The reviewer supplies a `review_track` of `FISCAL` or `PROGRAM`, a `decision` of `PASS` or `FAIL`, an optional `note`, and the `expected_payment_voucher_version` of §2.6. The fiscal track may be closed only by a `FiscalOfficer` and the program track only by a `ProgramDirector`; a role reaching for the other track is refused with `ERR_UNAUTHORIZED`. The addressed track must still be `PENDING`, or the request is refused with `ERR_INVALID_STATE_TRANSITION`. And when the *other* track is already closed, the acting `X-User-ID` must differ from that track's recorded reviewer, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`.

A `PASS` that closes only the first of the two tracks leaves the voucher in `SUBMITTED`: the addressed track becomes `PASSED`, its reviewer field records the acting operator, and the voucher's `version` increments. Nothing moves on the money ledger yet. When a `PASS` closes the **second** track, so that both `fiscal_review_status` and `program_review_status` read `PASSED`, the join fires automatically and the voucher becomes `APPROVED`. Approval moves money: the residency's `disbursed_cents` gains `total_cents`, its `encumbered_cents` loses the sum of the held amounts of the claimed sessions, each of those sessions has its held amount zeroed, and `available_cents` is recomputed — leaving the money identity of §2.12 intact. Both the voucher's and the residency's `version` increment.

A `FAIL` on either track sends the voucher to `REJECTED`, and its side effects deliberately differ from the pass branch. The addressed track becomes `FAILED` with its reviewer field recorded, while the other track keeps whatever value it already had. Every claimed session has its `payment_voucher_id` cleared to null so the sessions can be claimed again by a corrected voucher. Crucially, the encumbrances are **not** released: the work was still delivered and is still owed, so the money stays committed. The voucher's `version` increments.

Voiding is a `FiscalOfficer` capability that records a `void_reason` and is reachable from two places. `APPROVED → VOIDED` requires the residency not to be `CLOSED`, or the void is refused with `ERR_INVALID_STATE_TRANSITION`, and it is a true compensating action: the residency's `disbursed_cents` loses `total_cents`, its `encumbered_cents` gains exactly that same `total_cents`, each claimed session's held amount is restored to its `payable_cents`, and `available_cents` is recomputed, so that the money identity holds with precisely the values it had before approval. Each claimed session's `payment_voucher_id` is cleared to null. Both the voucher's and the residency's `version` increment. `REJECTED → VOIDED` has no precondition and no ledger effect at all — a rejected voucher never disbursed anything — and merely increments the voucher's `version`.

### 3.9. Program Evaluation and Funder Reporting

Evidence of learning is attached to sessions after they are delivered. A `CurriculumSpecialist` may attach an observation rubric; the host school's `SchoolLiaison` may attach a teacher survey or a student-work sample. Each record names its `evaluation_type` — `OBSERVATION_RUBRIC`, `TEACHER_SURVEY`, or `STUDENT_WORK_SAMPLE` — and the `evaluator_user_id` of whoever produced it. Type and role must agree, and a mismatch is refused with `ERR_UNAUTHORIZED`; a `SchoolLiaison` acting on a session whose residency is not at their own school is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`.

The payload fields are type-exclusive, and the constraint runs both ways. An `OBSERVATION_RUBRIC` record requires all three of `rubric_engagement_score`, `rubric_craft_score`, and `rubric_standards_evidence_score`, each a whole number from 1 to 4, and must leave `teacher_survey_score` and `student_work_artifact_count` null. A `TEACHER_SURVEY` record requires `teacher_survey_score`, a whole number from 1 to 5, and must leave all three rubric scores and the artifact count null. A `STUDENT_WORK_SAMPLE` record requires `student_work_artifact_count`, a whole number of at least 0, and must leave the three rubric scores and the survey score null. Violations of these shape rules are `ERR_INVALID_REQUEST`. For an observation rubric the server derives `rubric_composite` as the three rubric scores added together, divided by three, rounded half up to two decimal places; for the other two types `rubric_composite` stays null. Evaluations of a session are listable under it, optionally filtered by `evaluation_type`.

**The residency evaluation index** is recomputed whenever an evaluation is attached and whenever a session is delivered, and it looks only at evaluation records attached to that residency's `DELIVERED` sessions — evidence on cancelled sessions is excluded entirely. Three components are formed:

- The observation mean is the mean of `rubric_composite` across the observation-rubric records, rounded half up to two decimals; it is null when there are none.
- The survey mean is the mean of `teacher_survey_score` across the teacher-survey records, rounded half up to two decimals; it is null when there are none.
- The artifact rate is the total `student_work_artifact_count` across the student-work-sample records divided by the total `students_present_count` across those delivered sessions, capped at 1, and kept at full precision rather than rounded; it is null when there is no student-work-sample record or when the summed headcount is zero.

Each surviving component is normalized to a zero-to-one scale — the observation mean by dividing by 4, the survey mean by dividing by 5, and the artifact rate as it already stands — and carries a nominal weight of 0.50, 0.30, and 0.20 respectively. **Missing components do not count as zero.** They drop out, and the weights of the surviving components are renormalized by dividing each by the sum of the surviving weights. `evaluation_index` is then 100 multiplied by the weighted sum of the surviving normalized values, rounded half up to one decimal place, on a scale from 0.0 to 100.0. When no component survives at all, `evaluation_index` is null.

**Funder reports** are opened by a `ProgramDirector` with a `funder_name`, a `grant_code`, a reporting period given as `period_start` and `period_end` with the end no earlier than the start, a non-empty and duplicate-free `scope_residency_ids` array, and a `headcount_basis` of `UNDUPLICATED` or `ENCOUNTERS` that selects between two ways of counting the same children. A new report has a `status` of `DRAFT`, every computed metric at zero, and `compiled_by_user_id`, `certified_by_user_id`, `attestation_text`, and `invalidated_reason` all null. Reports are listable with `grant_code`, `status`, and `scope_residency_ids` filters.

Compiling the snapshot is also a `ProgramDirector` capability, takes no payload, and works both as `DRAFT → COMPILED` and as a recompile in place from `COMPILED → COMPILED`. On the first form every entry of `scope_residency_ids` must resolve to a residency, or the compile is refused with `ERR_RESIDENCY_NOT_FOUND`; the recompile-in-place form carries no precondition. Either form recomputes every metric, stamps `compiled_by_user_id` with the acting operator, and — on the `DRAFT → COMPILED` form — clears `invalidated_reason` back to null.

The metrics are computed as follows. Within the report's scope, a residency's *delivered-in-period* sessions are those whose status is `DELIVERED` and whose `session_date` falls inside the closed interval from `period_start` to `period_end`. A residency **qualifies** when it has at least one such session. `sessions_delivered_total` is the total number of delivered-in-period sessions across the scope.

`students_served` follows the chosen basis. Under `UNDUPLICATED` it is the sum of `enrolled_student_count` over the *qualifying* residencies — each residency's roll counted exactly once, so a child who attends six sessions counts once. Under `ENCOUNTERS` it is the sum of `students_present_count` over every delivered-in-period session of every residency in scope, so the same child counts once per session attended; on identical data the encounters figure is strictly larger than the unduplicated figure whenever any residency delivered more than one session in the period.

Demographic reach is computed per residency and only then summed, and it uses the same per-residency served figure that the chosen basis implies: `enrolled_student_count` under `UNDUPLICATED`, and the residency's own summed `students_present_count` over its delivered-in-period sessions under `ENCOUNTERS`. For each qualifying residency, that served figure is multiplied by the host school's `frl_pct`, `ell_pct`, and `iep_pct` in turn and each product is rounded half up to a whole student; the per-residency results are then summed into `frl_students_reached`, `ell_students_reached`, and `iep_students_reached`.

Cost is where evaluation order is easy to get wrong. `direct_cost_cents` is the sum of `total_cents` over payment vouchers that are `APPROVED`, whose `residency_id` is in the report's scope, and whose own `period_end` falls inside the report's closed reporting period. The indirect rate is then chosen from a bracket keyed on **direct cost alone**, never on total spend: 15 percent (a factor of 0.15) when direct cost is below 500,000 cents, 12 percent (0.12) when it is below 1,500,000 cents, and 10 percent (0.10) at or above that. `indirect_cost_cents` is direct cost multiplied by that rate, rounded half up to whole cents. `total_spend_cents` is direct cost plus indirect cost. And `cost_per_student_cents` is total spend divided by `students_served`, rounded half up — defined as zero when `students_served` is zero, so an empty scope yields zeros rather than a division failure.

A compiled snapshot goes stale on its own. Whenever a session inside one of the scope residencies reaches `DELIVERED` with a `session_date` inside the reporting period, every affected report in `COMPILED` falls back to `DRAFT` with `invalidated_reason` set to `SCOPE_DELIVERY_CHANGED`; the computed metrics keep their last compiled values until somebody recompiles. The `DRAFT → COMPILED → DRAFT` cycle can therefore repeat indefinitely as delivery continues.

Certification is the `FiscalOfficer`'s act and the last word on a report. It supplies a `certifier_user_id` and the `attestation_text` to be captured, and drives `COMPILED → CERTIFIED`. Three preconditions apply: every residency in `scope_residency_ids` must have a `status` of `COMPLETED` or `CLOSED`, or the request is refused with `ERR_RESIDENCY_NOT_FINALIZED`; the supplied `certifier_user_id` must differ from the report's `compiled_by_user_id`, or the refusal is `ERR_SEGREGATION_OF_DUTIES`; and `invalidated_reason` must be null, so a stale snapshot cannot be certified — that too is refused with `ERR_RESIDENCY_NOT_FINALIZED`. Certification writes the supplied certifier into `certified_by_user_id` and persists `attestation_text`. `CERTIFIED` is terminal.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created object in `data`. Reads and operations that modify an existing resource return HTTP 200 with the affected object in `data`; the clock-control capability returns HTTP 200 with an empty `data` object. Rejections follow the error envelope of §2.2 with the status code listed in §5. Every GET endpoint below is available to all six roles.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/school-partners` | Register a school partner | ProgramDirector |
| GET | `/school-partners/{id}` | Read a school partner including its computed partnership health | All six roles |
| POST | `/school-partners/{id}/calendar-blackouts` | Add a closed-interval blackout window to a school calendar | RosterCoordinator, SchoolLiaison |
| GET | `/school-partners/{id}/calendar-blackouts` | List the blackout windows of a school | All six roles |
| POST | `/teaching-artists` | Intake a teaching artist applicant with discipline, grade-band and language capability tags | RosterCoordinator |
| GET | `/teaching-artists/{id}` | Read a teaching artist including both state axes and all computed roster metrics | All six roles |
| GET | `/teaching-artists` | Search the roster by capability tags and lifecycle state | All six roles |
| POST | `/teaching-artists/{id}/vetting` | Advance the vetting axis; also records the teaching-demonstration outcome | RosterCoordinator |
| POST | `/teaching-artists/{id}/roster-status` | Move the roster axis (probation, suspension, reinstatement, retirement) | ProgramDirector |
| POST | `/teaching-artists/{id}/portfolio-reviews` | Record one panelist's portfolio scores | RosterCoordinator, CurriculumSpecialist |
| GET | `/teaching-artists/{id}/portfolio-reviews` | List the portfolio reviews of an artist | All six roles |
| POST | `/teaching-artists/{id}/screenings` | Record a background screening result | RosterCoordinator |
| GET | `/teaching-artists/{id}/screenings` | List the screenings of an artist | All six roles |
| POST | `/arts-standards` | Add a state arts standard to the alignment catalog | ProgramDirector, CurriculumSpecialist |
| GET | `/arts-standards` | Browse the arts standards catalog | All six roles |
| POST | `/residencies` | Scope a school residency (session count, budget, collaboration expectation, required strands, term) | ProgramDirector, RosterCoordinator |
| GET | `/residencies/{id}` | Read a residency with both cost-outlook variants and both ledgers | All six roles |
| GET | `/residencies` | List residencies | All six roles |
| POST | `/residencies/{id}/lead-artist` | Assign or replace the lead teaching artist of a residency | ProgramDirector, RosterCoordinator |
| POST | `/residencies/{id}/status` | Drive the residency lifecycle (approve, activate, suspend, resume, complete, close, cancel) | ProgramDirector |
| POST | `/lesson-plans` | Submit a lesson plan aligned to state arts standards | TeachingArtist, RosterCoordinator |
| GET | `/lesson-plans/{id}` | Read a lesson plan with its covered strands and review history fields | All six roles |
| GET | `/lesson-plans` | List lesson plans | All six roles |
| POST | `/lesson-plans/{id}/review` | Curriculum review decision: align the plan or request adaptation | CurriculumSpecialist |
| POST | `/lesson-plans/{id}/revisions` | Resubmit an adapted lesson plan after a change request | TeachingArtist, RosterCoordinator |
| POST | `/sessions` | Schedule a residency session (REGULAR draws the contracted allotment, MAKEUP consumes a make-up credit) | RosterCoordinator |
| GET | `/sessions/{id}` | Read a session with its interval, ledger and payment fields | All six roles |
| GET | `/sessions` | Search the schedule | All six roles |
| POST | `/sessions/{id}/confirm` | Classroom teacher confirms the session and the co-planning expectation | SchoolLiaison, RosterCoordinator |
| POST | `/sessions/{id}/reassign` | Substitute coverage: swap in another rostered artist | RosterCoordinator |
| POST | `/sessions/{id}/cancel` | Cancel a session; the reason decides whether a make-up credit is issued or the session is forfeited | SchoolLiaison, RosterCoordinator, TeachingArtist |
| POST | `/sessions/{id}/deliver` | The assigned artist reports delivery: headcount, minutes taught, travel miles and materials spend | TeachingArtist |
| POST | `/sessions/{id}/evaluations` | Attach an observation rubric, teacher survey or student-work sample to a delivered session | CurriculumSpecialist, SchoolLiaison |
| GET | `/sessions/{id}/evaluations` | List the evaluations of a session | All six roles |
| POST | `/payment-vouchers` | Open a payment voucher for delivered sessions in a pay period | TeachingArtist, RosterCoordinator |
| GET | `/payment-vouchers/{id}` | Read a voucher with both review tracks and all money subtotals | All six roles |
| GET | `/payment-vouchers` | List vouchers | All six roles |
| POST | `/payment-vouchers/{id}/submit` | Submit a voucher for the two-track review | TeachingArtist, RosterCoordinator |
| POST | `/payment-vouchers/{id}/review` | Close one review track (fiscal or program); the join approves the voucher when both pass | FiscalOfficer, ProgramDirector |
| POST | `/payment-vouchers/{id}/void` | Void a voucher, reversing its disbursement | FiscalOfficer |
| POST | `/funder-reports` | Open a funder report over a set of residencies and a reporting period | ProgramDirector |
| GET | `/funder-reports/{id}` | Read a funder report with its compiled metrics | All six roles |
| GET | `/funder-reports` | List funder reports | All six roles |
| POST | `/funder-reports/{id}/compile` | Compile the reporting snapshot: students served, demographic reach and cost per student | ProgramDirector |
| POST | `/funder-reports/{id}/certify` | Certify a compiled report for submission to the funder | FiscalOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock, which every date comparison in this specification reads | ProgramDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ACTOR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SCHOOL_PARTNER_NOT_FOUND` | 404 |
| `ERR_TEACHING_ARTIST_NOT_FOUND` | 404 |
| `ERR_RESIDENCY_NOT_FOUND` | 404 |
| `ERR_LESSON_PLAN_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_VOUCHER_NOT_FOUND` | 404 |
| `ERR_FUNDER_REPORT_NOT_FOUND` | 404 |
| `ERR_UNKNOWN_STANDARD_CODE` | 422 |
| `ERR_STALE_RESIDENCY_VERSION` | 412 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_VOUCHER_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_ARTIST_NOT_CLEARED` | 403 |
| `ERR_CLEARANCE_EXPIRED` | 409 |
| `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER` | 409 |
| `ERR_ARTIST_HAS_OPEN_SESSIONS` | 409 |
| `ERR_RELIABILITY_BELOW_FLOOR` | 409 |
| `ERR_PARTNERSHIP_INTAKE_SUSPENDED` | 403 |
| `ERR_PARTNERSHIP_HEALTH_GATE` | 403 |
| `ERR_NO_ALIGNED_LESSON_PLAN` | 409 |
| `ERR_STANDARDS_COVERAGE_INCOMPLETE` | 409 |
| `ERR_DISCIPLINE_MISMATCH` | 422 |
| `ERR_GRADE_BAND_MISMATCH` | 422 |
| `ERR_LANGUAGE_CAPABILITY_MISSING` | 422 |
| `ERR_EVALUATION_MISSING` | 409 |
| `ERR_SESSION_ALREADY_VOUCHERED` | 409 |
| `ERR_RESIDENCY_NOT_FINALIZED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INSUFFICIENT_PORTFOLIO_REVIEWS` | 409 |
| `ERR_PORTFOLIO_THRESHOLD_NOT_MET` | 409 |
| `ERR_DEMO_ATTEMPT_LIMIT_REACHED` | 409 |
| `ERR_ADAPTATION_ROUND_LIMIT` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_STANDARD_CODE` | 409 |
| `ERR_DUPLICATE_SEQUENCE_NO` | 409 |
| `ERR_DUPLICATE_REVIEWER` | 409 |
| `ERR_MAKEUP_CREDIT_UNAVAILABLE` | 409 |
| `ERR_SESSION_UNDERDELIVERED` | 422 |
| `ERR_CO_PLANNING_INCOMPLETE` | 409 |
| `ERR_CANCEL_REASON_NOT_PERMITTED` | 403 |
| `ERR_SESSION_OUTSIDE_RESIDENCY_TERM` | 409 |
| `ERR_VOUCHER_PERIOD_MISMATCH` | 422 |
| `ERR_CALENDAR_BLACKOUT` | 409 |
| `ERR_ARTIST_SCHEDULE_CONFLICT` | 409 |
| `ERR_TRAVEL_BUFFER_VIOLATION` | 409 |
| `ERR_SCHOOL_CAPACITY_EXCEEDED` | 409 |
| `ERR_SESSION_ALLOTMENT_EXHAUSTED` | 409 |
| `ERR_RESIDENCY_BUDGET_EXCEEDED` | 409 |
| `ERR_RESIDENCY_HAS_OPEN_SESSIONS` | 409 |
| `ERR_RESIDENCY_HAS_OPEN_VOUCHERS` | 409 |
