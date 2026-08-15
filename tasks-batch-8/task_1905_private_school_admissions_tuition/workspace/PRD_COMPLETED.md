# Private School Admissions API — Product Requirements Document

## 1. Introduction

An independent school's admission office runs on scarcity and sequence. Every academic year opens a fixed number of seats per grade and a fixed financial-aid budget, and families compete for both across structured deadline rounds: an early round and a regular round of applications, entrance testing and interviews, committee scoring and ranking, offers with expiring response windows, enrollment contracts with deposits, and — over the summer — the attrition known in the industry as melt. In parallel, the office re-enrolls its current families for the coming year, notifying them of tuition changes and honoring sibling discounts, and it paces aid commitments so the budget is not exhausted before later rounds are decided.

This document specifies the Private School Admissions API, the system of record for that entire funnel. It governs admission cycles and their grade sections; the applicant and currently-enrolled-student registries; applications from draft through decision; entrance evaluations and group test sessions; financial-aid applications with income verification, an award formula, appeals, and budget pacing; enrollment contracts and deposit collection; waitlist promotion and summer-melt cascades; and re-enrollment offers for returning students. All deadline, expiry, lapse, and melt logic reads a server-side logical clock rather than the wall clock, so operators and test drivers control time explicitly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Four roles are recognized, spelled exactly as follows: `AdmissionDirector`, `AdmissionOfficer`, `FinancialAidOfficer`, and `Parent`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_USER_CONTEXT`; header values are stripped of surrounding whitespace before use, and a whitespace-only value counts as empty. Every endpoint authorizes a fixed list of roles; a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE`.

The `AdmissionDirector` is the head of admissions and owns cycle configuration, round closes, operational sweeps, the student registry, and re-enrollment offers; this role alone may set the logical clock. The `AdmissionOfficer` runs the funnel day to day — scheduling and scoring evaluations, issuing enrollment contracts — and shares applicant and application filing with families. The `FinancialAidOfficer` verifies family income and finalizes or revises aid awards, subject to a segregation-of-duties rule: the officer who verified an aid application's income may not finalize or revise that same award. The `Parent` is the family account holder who files applications, responds to offers and awards, signs contracts, and pays deposits.

For `AdmissionDirector`, `AdmissionOfficer`, and `FinancialAidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for attribution — most notably as `verified_by_user_id` when a `FinancialAidOfficer` verifies an aid application's income — but it does not compare the value to any entity's `id`. Staff roles are unscoped in what they may read.

When `X-User-Role` is `Parent`, `X-User-ID` carries the family account identifier: every `Applicant` and `Student` the family owns records that value in its `family_id` field. Ownership checks walk a resource's chain to the owning family — an application, evaluation, aid application, or enrollment contract resolves through its applicant's `family_id`, and a re-enrollment offer through its student's `family_id` — and compare the result to `X-User-ID`. A `Parent` acting on a resource outside that family scope is rejected with `ERR_FAMILY_SCOPE_VIOLATION`, and list endpoints auto-filter a `Parent` caller's results to their own family.

Two visibility notes complete the access model. Entrance evaluations and test sessions are staff-only records: `Parent` callers cannot list or read them. Aid application list and detail are visible to `AdmissionDirector`, `FinancialAidOfficer`, and `Parent` callers (the last family-scoped), but not to `AdmissionOfficer`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, and an unparseable value falls back to the default. The `offset` parameter sets the number of items skipped and defaults to 0, with negative values clamped to 0 and an unparseable value falling back to the default. Unrecognized query parameters are ignored. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp (`created_at`) in ascending order.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Admissions Logical Clock

Every deadline, expiry, lapse, and melt comparison in the system reads a server-side logical clock — never the wall clock. The logical clock starts at exactly `2026-08-01T00:00:00Z` on every server boot, and it moves only when an `AdmissionDirector` invokes the clock-setting capability with a target instant supplied as `to_iso8601`; the capability responds with the resulting `current_utc` and mutates no entity. A target instant without an explicit offset is read as UTC, and the clock may be set to any parseable instant — backward as well as forward. Instants derived from the logical clock, and timestamp fields that echo client-supplied deadline instants, are rendered as ISO 8601 instants without fractional digits when the instant falls on a whole second and with three fractional digits otherwise. Because submission deadlines, round closes, offer expirations, contract lapses, re-enrollment lapses, and the summer-melt boundary all observe this clock, advancing it is the sole mechanism by which time-driven behavior unfolds.

### 2.5. Common Resource Properties and Identifier Discipline

All ten resources — `AdmissionCycle`, `GradeSection`, `Applicant`, `Student`, `Application`, `EntranceEvaluation`, `TestSession`, `AidApplication`, `EnrollmentContract`, and `ReenrollmentOffer` — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique per resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments by one on every mutation of the resource, including system-driven cascade mutations.

Identifiers are identity-only. An `id` never participates in ranking, selection, or tie-break decisions; wherever an ordering fallback is required — committee ranking, waitlist promotion, sibling seniority — `created_at` ascending is the only sanctioned fallback ordering.

### 2.6. Money, Cents, and Rounding Discipline

All monetary quantities in the system — tuition, awards, deposits, budgets, discounts — are integer cents; the API represents them as numbers, never strings. Final monetary values are rounded half-up to a whole cent. Where a tiered or percentage-based figure feeds a sum, the individual component is rounded half-up to a whole cent before the components are added, so stored figures always reconcile exactly. One non-monetary exception exists: the weighted component of an application's committee composite score is rounded half-up to two decimal places before integer preference points are added.

### 2.7. The Request Validation Pipeline

Every request is evaluated against a fixed pipeline of validation layers, and the first failing layer wins — later layers are never consulted once a rejection is issued. The layers run in this order:

1. **Authentication context.** Both `X-User-ID` and `X-User-Role` are present and non-empty; failure is `ERR_MISSING_USER_CONTEXT` (HTTP 400).
2. **Role authorization.** The caller's role appears in the endpoint's authorized role list; failure is `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Family scope.** On every endpoint that accepts the `Parent` role, a `Parent` caller may only touch resources whose ownership chain ends at an applicant or student whose `family_id` equals the caller's `X-User-ID`; failure is `ERR_FAMILY_SCOPE_VIOLATION` (HTTP 403). Staff roles are unscoped.
4. **Segregation of duties.** On the finalize-award and revise-award operations only, the caller's `X-User-ID` must differ from the aid application's `verified_by_user_id`; failure is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
5. **Request well-formedness.** The body is well-formed, contains all required fields (a required field present with an explicit null counts as missing, while an optional field present with a null fails its layer-6 format check), and carries no unknown fields; failure is `ERR_INVALID_REQUEST` (HTTP 400). Endpoints that declare no request-body fields do not parse the body at all, so anything sent to them is ignored.
6. **Field formats, ranges, and enums.** Enum membership, integer ranges, datetime ordering, kind-specific field presence on evaluations, and cycle deadline ordering; failure is `ERR_VALIDATION` (HTTP 422). The revise-award upper tuition band is the one exception: it is validated later, after that endpoint's segregation and state gates (see §3.4).
7. **Path resource existence.** Identifiers in the URL path are validated left to right; the first missing resource yields `ERR_NOT_FOUND` (HTTP 404).
8. **Body foreign-key existence.** Referenced resources named in the body — `applicant_id`, `cycle_id`, `grade_section_id`, `current_grade_section_id`, `application_id`, `test_session_id`, `student_id` — must exist; failure is `ERR_REFERENCE_NOT_FOUND` (HTTP 404).
9. **Optimistic concurrency.** Where an endpoint declares an expected-version field, it must equal the parent entity's current `version`; failure is `ERR_STALE_VERSION` (HTTP 412).
10. **Target state preconditions.** The invoked transition's own state gate from the relevant state machine — the various `ERR_APPLICATION_*`, `ERR_CYCLE_*`, `ERR_CONTRACT_*`, `ERR_AWARD_*`, `ERR_AID_*`, `ERR_EVALUATION_NOT_SCHEDULED`, and `ERR_REENROLL_NOT_ISSUED` codes (HTTP 409).
11. **Temporal gates.** Deadline checks against the logical clock — `ERR_ROUND_DEADLINE_PASSED`, `ERR_ROUND_STILL_OPEN`, `ERR_OFFER_EXPIRED`, and `ERR_REENROLL_WINDOW_CLOSED` (HTTP 422).
12. **Uniqueness, capacity, and overlap.** The `ERR_DUPLICATE_*`, `ERR_INTERVIEWER_SCHEDULE_CONFLICT`, `ERR_TEST_SESSION_FULL`, `ERR_EVALUATION_OUTSIDE_SESSION`, `ERR_GRADE_CYCLE_MISMATCH`, `ERR_NO_NEXT_GRADE`, and `ERR_REENROLL_ALREADY_ACCEPTED` family of constraint codes (HTTP 409).
13. **Cross-entity state.** Referential-state rules spanning entities — `ERR_CYCLE_NOT_OPEN`, `ERR_APPLICATION_TERMINAL`, `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_AID_NOT_FINALIZED`, and `ERR_AWARD_STALE_VERIFICATION` (HTTP 409).
14. **Money gates last.** Fiscal checks run after everything else: the aid pacing cap on award acceptance (`ERR_AID_PACING_CAP_EXCEEDED`, HTTP 402) and the deposit-balance cap on payments (`ERR_PAYMENT_EXCEEDS_BALANCE`, HTTP 422).

The ordering is observable behavior: a request that is both unauthenticated and stale-versioned surfaces `ERR_MISSING_USER_CONTEXT`; a well-formed request from the wrong role never reaches existence checks; a money-gate violation is reported only after every state, temporal, and constraint check has passed. Layers 3 and 4 each inspect an already-loaded resource — the path target, or a body-referenced resource on create endpoints — so each is evaluated the moment that resource is in hand: a missing path resource surfaces `ERR_NOT_FOUND`, and a missing body reference surfaces `ERR_REFERENCE_NOT_FOUND`, ahead of any scope or segregation verdict.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; endpoints not named here accept no version field at all.

Issuing a re-enrollment offer requires the request to carry `expected_student_version`, holding the `version` of the target `Student` as the client last observed it. The product semantics legitimately allow a fresh offer to supersede a prior `ISSUED` offer for the same student and cycle, so a second well-formed create would otherwise succeed on a stale view of the student — missing, for example, that an offer was just issued or answered. If the supplied value does not match the student's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.

Rescheduling an entrance evaluation requires the request to carry `expected_evaluation_version`, holding the `version` of the `EntranceEvaluation` as the client last read it. A reschedule leaves the evaluation in `SCHEDULED`, so a second sequential reschedule observes an identical state field and would itself legitimately succeed; only the stale version distinguishes the lost update. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Derived Counters, Cascades, and In-Request Consistency

Consistency is immediate: every mutation is atomic within its request, and derived counters are recomputed inside the same request that invalidates them — no background jobs, no eventual reconciliation. Each `GradeSection` maintains a live seat ledger: `seats_held` counts the section's applications in `OFFERED`, `CONTRACT_ISSUED`, or `ENROLLED`; `aid_seats_held` counts those among the held set that have a linked aid application whose `award_status` is anything other than `RELEASED`; and `seats_available` is the section's `capacity` minus `seats_held`, which can never go negative. Each `AdmissionCycle` maintains `aid_committed_cents`, the sum of `final_award_cents` over the cycle's aid applications whose `award_status` is `ACCEPTED`, and `pacing_cap_cents`, the commitment ceiling that tracks the cycle's phase. When a single operation touches several records — an offer expiring, a contract lapsing, a family melting away — all of its cascades complete within the one request: awards release, committed budget uncommits, seats free, and every record actually mutated along the way has its `updated_at` refreshed and its `version` incremented.

## 3. Business Logic & Workflows

### 3.1. Building the Admission Cycle: Deadlines, Grade Sections, and the Aid Budget

An `AdmissionDirector` begins an admission year by creating an `AdmissionCycle`. The creation payload names the `academic_year` label (for example, "2027-2028"), four deadline instants, and the cycle's financial-aid budget `aid_budget_total_cents`, which must be zero or greater. The four deadlines are `early_deadline_at`, the last instant at which `EARLY` round submissions are accepted; `regular_deadline_at`, the same boundary for the `REGULAR` round; `reenroll_response_deadline_at`, the last instant for families to respond to re-enrollment offers targeting this cycle; and `melt_deadline_at`, the summer-melt boundary after which the waitlist is expired and no further promotions occur. Each deadline is inclusive on its side of the line. Their ordering is validated at creation: the early deadline must fall strictly before the regular deadline, the regular deadline strictly before the re-enrollment response deadline, and the re-enrollment response deadline at or before the melt deadline; any other arrangement is rejected with `ERR_VALIDATION`. A new cycle starts in `DRAFT` with `aid_committed_cents` at zero.

While the cycle is in `DRAFT`, the director defines its `GradeSection` records — one per grade enrolling new students. A section is created with its `cycle_id`, a `grade_level` drawn from `K`, `G1`, `G2`, `G3`, `G4`, `G5`, `G6`, `G7`, `G8`, `G9`, `G10`, `G11`, and `G12`; a `capacity` of at least one new-enrollment seat; a gross annual `tuition_cents` of zero or more; and `max_aid_seat_pct`, the class-composition target capping the share of capacity that aid-seeking admits may hold, expressed as a number between 0 and 1 inclusive. Sections may only be created while their cycle is in `DRAFT`; attempting to add one later is rejected with `ERR_CYCLE_INVALID_STATE`. The grade-section listing supports optional filtering by `cycle_id` and `grade_level`, and the cycle listing by `status`.

Opening the cycle moves it `DRAFT` → `OPEN` and requires at least one grade section to exist; opening from any state other than `DRAFT` fails with `ERR_CYCLE_INVALID_STATE` — the state check runs first, so a non-`DRAFT` cycle that also has no sections still reports `ERR_CYCLE_INVALID_STATE` — and opening a sectionless `DRAFT` cycle fails with `ERR_CYCLE_HAS_NO_SECTIONS`. From that moment the aid pacing ceiling tracks the cycle's phase and is recomputed on every cycle status change: while `DRAFT` or `OPEN`, `pacing_cap_cents` is forty percent of `aid_budget_total_cents` rounded half-up to a whole cent (in `DRAFT` no acceptances can occur yet, so the figure is informational); at `EARLY_CLOSED` the ceiling rises to seventy-five percent of the budget on the same rounding; and at `CLOSED` and `ARCHIVED` the ceiling is the full budget. Retrieval of a single cycle always includes the computed `aid_committed_cents` and `pacing_cap_cents`.

Closing a round is how decisions are made, and it is phased. The close operation carries a `round` field in its payload. Closing the early round requires the cycle to be `OPEN` and the payload's `round` to name `EARLY`; closing the regular round requires the cycle to be `EARLY_CLOSED` and the payload to name `REGULAR`. A `round` value that does not match the cycle's current phase is rejected with `ERR_CYCLE_INVALID_STATE`, and a close invoked at or before that round's deadline is rejected with `ERR_ROUND_STILL_OPEN` — the close is only permitted once the logical clock has passed the deadline. An early close moves the cycle `OPEN` → `EARLY_CLOSED`, a regular close moves it `EARLY_CLOSED` → `CLOSED`, and each close runs the decision sweep described in §3.5 and recomputes the pacing ceiling for the new phase. Finally, a `CLOSED` cycle may be archived, moving it to the terminal `ARCHIVED` state; archiving from any other state is `ERR_CYCLE_INVALID_STATE`.

### 3.2. Registering Families and Filing Applications

Before any application exists, the child is registered as an `Applicant`. Registration records the `family_id` of the owning family account, the child's `first_name` and `last_name`, a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and an optional `legacy_parent` flag — defaulting to false — that marks a parent as an alumnus for legacy preference. Both `Parent` callers and `AdmissionOfficer` staff may register applicants, but a `Parent` caller's `family_id` must equal their own `X-User-ID`; anything else is `ERR_FAMILY_SCOPE_VIOLATION`. The applicant listing accepts an optional `family_id` filter, and `Parent` callers always see only their own family.

The office also maintains a registry of currently enrolled `Student` records. A director registers a student directly with `family_id`, `first_name`, `last_name`, and `current_grade_section_id` pointing at the section the student attends; such rows arrive with `status` `ACTIVE` and `source` `DIRECT`. Students created later by the enrollment cascade of §3.6 carry `source` `ADMISSION` instead. A student's `re_enrolled_for_cycle_id` stays null until the family accepts a re-enrollment offer, and melt never deletes a student row — it soft-deactivates it to `INACTIVE`. The student listing supports filters on `family_id`, `current_grade_section_id`, `status`, and `re_enrolled_for_cycle_id`.

With an applicant registered, a `Parent` or an `AdmissionOfficer` files an `Application` by naming the `applicant_id`, the target `cycle_id`, the `grade_section_id` applied for, and the `round` — `EARLY` or `REGULAR`. Creation is gated: the cycle must be `OPEN` (anything else is `ERR_CYCLE_NOT_OPEN`), the chosen section must belong to the given cycle (`ERR_GRADE_CYCLE_MISMATCH` when it belongs to another), every referenced resource must exist (`ERR_REFERENCE_NOT_FOUND`), and an applicant may hold only one live application per cycle — a second application for the same applicant and cycle while the first is in any non-terminal state is rejected with `ERR_DUPLICATE_APPLICATION`. A new application starts in `DRAFT`. The application listing accepts optional filters `cycle_id`, `grade_section_id`, `applicant_id`, `status`, and `family_id`.

An application's `status` walks a wide state space: `DRAFT`, `SUBMITTED`, `EVALUATION_COMPLETE`, `OFFERED`, `CONTRACT_ISSUED`, `WAITLISTED`, `ENROLLED`, and the terminal states `DENIED`, `DECLINED`, `WITHDRAWN`, `EXPIRED`, and `MELTED`.

Submission moves an application `DRAFT` → `SUBMITTED`. The application must currently be `DRAFT` (`ERR_APPLICATION_NOT_DRAFT` otherwise); the cycle's phase must still admit the application's round — an `EARLY` submission requires the cycle `OPEN`, while a `REGULAR` submission accepts a cycle that is `OPEN` or `EARLY_CLOSED`, with any other phase drawing `ERR_CYCLE_NOT_OPEN`, a gate evaluated before the deadline check so a submission violating both surfaces `ERR_CYCLE_NOT_OPEN`; and the logical clock must be at or before the round's deadline — `early_deadline_at` for `EARLY`, `regular_deadline_at` for `REGULAR` — with a late submission rejected as `ERR_ROUND_DEADLINE_PASSED`. A successful submission stamps `submitted_at` with the logical clock, a value that later feeds ranking tie-breaks; until submitted, `submitted_at` is null.

### 3.3. Entrance Testing, Interviews, and Committee Scoring

Once an application is submitted, an `AdmissionOfficer` arranges two evaluations: an entrance test and an interview. Group testing is organized into `TestSession` records created by directors or officers with a `cycle_id`, a `session_start` and `session_end` delimiting the session window (the end must be strictly after the start, else `ERR_VALIDATION`), and a `room_capacity` of at least one. A session's `booked_count` tracks how many non-cancelled test evaluations currently reference it; the test-session listing filters by `cycle_id`, and retrieval of one session includes its computed `booked_count`.

Scheduling an `EntranceEvaluation` takes the `application_id`, a `kind` of `TEST` or `INTERVIEW`, and a `scheduled_start`/`scheduled_end` window whose end must be strictly after its start. The kind-specific fields are exclusive: an `INTERVIEW` evaluation requires `interviewer_id` and forbids `test_session_id`, while a `TEST` evaluation requires `test_session_id` and forbids `interviewer_id` — mixing or omitting them is `ERR_VALIDATION`. The target application must be `SUBMITTED` or `EVALUATION_COMPLETE`; one that has not reached the submission gate is rejected with `ERR_APPLICATION_NOT_SUBMITTED`, and one in a terminal state with `ERR_APPLICATION_TERMINAL`. The application's cycle must also be in an admitting status — `OPEN` or `EARLY_CLOSED` — or the scheduling fails with `ERR_CYCLE_NOT_OPEN`. An application may carry at most one non-cancelled evaluation of each kind; a duplicate kind while the earlier one is still live draws `ERR_DUPLICATE_EVALUATION_KIND` — a guard consulted only after the application-state and cycle-status gates above, so against a closed cycle the scheduling surfaces `ERR_CYCLE_NOT_OPEN` even when a live evaluation of that kind already exists.

Two scheduling disciplines protect the calendar. For interviews, the new window must not overlap — under half-open interval semantics, where one window ending exactly when another begins is allowed — any other non-cancelled interview booked for the same `interviewer_id`; a conflict is `ERR_INTERVIEWER_SCHEDULE_CONFLICT`. For tests, the session's capacity is an aggregate headcount: the session is full when it already holds `room_capacity` non-cancelled `TEST` evaluations, regardless of how their individual windows overlap in time, and booking into a full session is `ERR_TEST_SESSION_FULL`. A test evaluation's window must also lie entirely within its session's `session_start`-to-`session_end` window, or it is rejected with `ERR_EVALUATION_OUTSIDE_SESSION`. A successfully scheduled evaluation starts in `SCHEDULED` and, for tests, adds one to the session's `booked_count`. The evaluation listing — staff-only — filters by `application_id`, `interviewer_id`, `test_session_id`, `kind`, and `status`.

Plans change, and an officer may reschedule a `SCHEDULED` evaluation, optionally replacing `scheduled_start`, `scheduled_end`, `interviewer_id`, or `test_session_id`. Rescheduling — per §2.8 — must carry `expected_evaluation_version` matching the evaluation's current `version` (a mismatch is `ERR_STALE_VERSION`, checked first), requires the evaluation to still be `SCHEDULED` (`ERR_EVALUATION_NOT_SCHEDULED` otherwise), and only then re-validates the merged window (fields not supplied keep their current values), the kind-specific field exclusions, the replacement test session's existence, and the interviewer-overlap, session-containment, and session-capacity rules excluding the evaluation itself — incrementing that version by one on success.

Scoring is the pivotal act. An officer records a `score` — an integer from 0 to 100 inclusive, anything outside drawing `ERR_VALIDATION` — on a `SCHEDULED` evaluation (`ERR_EVALUATION_NOT_SCHEDULED` otherwise), moving it to `SCORED`; the field is null until then. The moment an application's second evaluation kind reaches `SCORED`, the system computes the committee composite and advances the application `SUBMITTED` → `EVALUATION_COMPLETE`. The weighted component is sixty percent of the `TEST` score plus forty percent of the `INTERVIEW` score, rounded half-up to two decimal places. Preference points are then evaluated as integers and added after that rounding: sibling verification is resolved at this exact instant, with `sibling_verified` true if and only if an `ACTIVE` student exists whose `family_id` matches the applicant's family, worth ten points when true, and the applicant's `legacy_parent` flag is worth five points when set; the sum lands in `preference_points`, and the weighted component plus the preference points is the application's `composite_score`. Until both kinds are scored, `composite_score` is null, `preference_points` holds its default of zero, and `sibling_verified` is false.

An officer may also cancel a `SCHEDULED` evaluation, moving it to `CANCELLED`; cancelling a test frees its seat by subtracting one from the session's `booked_count`. A cancelled evaluation no longer blocks re-scheduling the same kind.

### 3.4. Financial Aid: Verification, Awarding, Appeals, and Budget Pacing

A family seeking assistance files an `AidApplication` — at most one per admission application, ever; a second filing draws `ERR_DUPLICATE_AID_APPLICATION`. The filing names the `application_id` and reports `reported_annual_income_cents` (zero or more) and `household_size` (at least one). The underlying application must be past `DRAFT` and not yet terminal: filing against a `DRAFT` application is `ERR_APPLICATION_NOT_SUBMITTED`, filing against a terminal one is `ERR_APPLICATION_TERMINAL`, and the application's cycle must still be in an admitting status or the filing is `ERR_CYCLE_NOT_OPEN`. Both `Parent` callers and `FinancialAidOfficer` staff may file. A new aid application starts with `verification_status` `SUBMITTED` and `award_status` `PROVISIONAL`, and its `provisional_award_cents` is computed immediately. The aid listing — visible to directors, aid officers, and family-scoped parents — filters by `application_id`, `award_status`, and `verification_status`.

The award formula runs in two variants from one recipe, and the evaluation order is fixed: allowance, then discretionary income, then the tiered expected family contribution, then demonstrated need, then the cap. First, a household allowance is computed as a base of 2,500,000 cents plus 750,000 cents for each member of `household_size`. Second, discretionary income is the amount by which the income figure under consideration exceeds that allowance, or zero when it does not. Third, the expected family contribution is assembled from three progressive tiers of discretionary income: twelve percent of the first 2,500,000 cents, plus twenty-two percent of the next 5,000,000 cents, plus thirty percent of whatever discretionary income remains beyond the first two tiers combined — that is, beyond the first 7,500,000 cents of discretionary income — with each tier's contribution rounded half-up to a whole cent before the three are summed. Fourth, demonstrated need is the tuition of the application's grade section minus the expected family contribution, floored at zero. Finally, the award is the smaller of demonstrated need and ninety percent of that tuition, with the percentage cap itself rounded half-up to a whole cent. The provisional variant applies this recipe to `reported_annual_income_cents` — at filing and on every income resubmission — and stores the result in `provisional_award_cents`. The final variant applies it to `verified_annual_income_cents` at finalization and stores the result in `final_award_cents`; whenever verified income differs from reported income, identical structure yields a different award. While the award remains `PROVISIONAL`, `final_award_cents` is null.

Verification is performed by a `FinancialAidOfficer` and requires `verification_status` to be `SUBMITTED` (`ERR_AID_NOT_SUBMITTED` otherwise). The officer supplies `verified_annual_income_cents` from the family's documentation; the system records it together with `verified_by_user_id` set to the caller's `X-User-ID` — both fields are null until this first verification — and moves `verification_status` to `VERIFIED`. Verification itself changes neither `provisional_award_cents` nor any `final_award_cents`.

Finalization is where the segregation-of-duties rule bites. Finalizing an award requires `verification_status` `VERIFIED` (`ERR_AID_NOT_VERIFIED` otherwise), `award_status` `PROVISIONAL` (`ERR_AWARD_LOCKED` otherwise), and a caller whose `X-User-ID` differs from the application's `verified_by_user_id` (`ERR_SEGREGATION_OF_DUTIES` otherwise — the officer who verified the income may not finalize that award). Finalization computes `final_award_cents` on the final variant and moves `award_status` `PROVISIONAL` → `OFFERED`.

The family then accepts or appeals. Acceptance requires `award_status` `OFFERED` (`ERR_AWARD_NOT_OFFERED` otherwise) and `verification_status` still `VERIFIED` — a family that resubmitted income after finalization finds its offer stale and acceptance blocked with `ERR_AWARD_STALE_VERIFICATION` until re-verified. Acceptance is also the money gate: the cycle's `aid_committed_cents` plus this award's `final_award_cents` must be less than or equal to the cycle's current `pacing_cap_cents` — equality is allowed — or acceptance is rejected with `ERR_AID_PACING_CAP_EXCEEDED` (HTTP 402). A successful acceptance moves the award to `ACCEPTED` and adds `final_award_cents` to the cycle's `aid_committed_cents`. Appeal instead requires only `award_status` `OFFERED` (`ERR_AWARD_NOT_APPEALABLE` otherwise), stores the family's `appeal_reason` — null unless an appeal was filed — and moves the award `OFFERED` → `APPEALED`.

An appealed award comes back through revision: a `FinancialAidOfficer` — again not the verifying officer, per the same `ERR_SEGREGATION_OF_DUTIES` rule — revises an award in `APPEALED` (`ERR_AWARD_NOT_APPEALED` otherwise) by supplying `revised_final_amount_cents`. The revised amount must be at least zero and at most ninety percent of the application's grade-section tuition rounded half-up to a whole cent; anything outside that band is `ERR_VALIDATION` — with non-negativity enforced among the body range checks while the upper tuition band is evaluated only after the segregation-of-duties and `APPEALED`-state gates, so an out-of-band amount on a non-`APPEALED` award surfaces `ERR_AWARD_NOT_APPEALED`. Revision sets `final_award_cents` to the revised amount and returns the award `APPEALED` → `OFFERED`, so the `OFFERED` ↔ `APPEALED` cycle may repeat.

Families may also correct their filings. Resubmitting income — open to `Parent` callers while the award is neither `ACCEPTED` nor `RELEASED` (`ERR_AWARD_LOCKED` otherwise) — replaces `reported_annual_income_cents` and `household_size` — under the same range rules as the original filing — recomputes `provisional_award_cents` on the provisional variant, and returns `verification_status` to `SUBMITTED` whether it was `VERIFIED` or already `SUBMITTED`; `verified_annual_income_cents` and `verified_by_user_id` are left untouched, overwritten only by a subsequent verification. The `award_status` itself is unchanged: an `OFFERED` award stays `OFFERED` but is now stale, since acceptance requires `verification_status` `VERIFIED`.

Awards unwind by cascade rather than by direct action. When the underlying application is declined, expired, lapsed, or melted — or withdrawn from `SUBMITTED`, `EVALUATION_COMPLETE`, `WAITLISTED`, or `CONTRACT_ISSUED` — a linked award in `PROVISIONAL`, `OFFERED`, or `APPEALED` moves to the terminal `RELEASED` with no budget impact; an award in `ACCEPTED` that releases additionally subtracts its `final_award_cents` from the cycle's `aid_committed_cents` as a compensating release. Withdrawing from `OFFERED` is the lone exception: it leaves the linked award untouched (§3.6).

### 3.5. Decision Sweeps: Round Close, Offers, and the Waitlist

Decisions are not made one application at a time; they are swept. When a director closes a round per §3.1, the decision sweep considers only that cycle's applications in that round sitting in `EVALUATION_COMPLETE` — applications waitlisted in an earlier round are not reconsidered when the later round closes. Candidates are ranked by `composite_score` descending, then `submitted_at` ascending, then `created_at` ascending; per §2.5, identifiers are never consulted.

The sweep then walks each grade section's ordered candidates independently. For the section, open seats equal its `capacity` minus its current `seats_held` — and held seats count offers, issued contracts, and enrollments across all rounds, not just the closing one. The aid-seat ceiling is the greatest integer not exceeding the section's `capacity` multiplied by its `max_aid_seat_pct`, and a candidate counts as aid-seeking when a linked aid application exists whose `award_status` is anything other than `RELEASED`. Walking from the highest-ranked candidate downward: a candidate is admitted — moved `EVALUATION_COMPLETE` → `OFFERED` — while open seats remain and, for aid-seekers, while the number of aid-seeking admits already placed in this pass remains below the aid-seat ceiling. An aid-seeking candidate skipped because the ceiling is full does not consume a seat, and the pass continues to lower-ranked candidates. A candidate not admitted is placed `WAITLISTED` while the section's waitlist band — sized equal to the section's `capacity` and counting only placements made in that pass, so applications waitlisted in earlier rounds do not consume it — is not yet full; anyone beyond both seats and band is `DENIED`.

Every newly `OFFERED` application receives an `offer_expires_at` twenty-one days out from the close clock, a `promoted_from_waitlist` of false, and an `estimated_deposit_cents` for the offer letter computed on the estimated deposit variant: the larger of 50,000 cents and ten percent of net tuition rounded half-up to a whole cent, where net tuition is the section's `tuition_cents` minus the linked aid application's `provisional_award_cents` — or minus zero when no aid application exists. The field stays null unless the application is `OFFERED`, `CONTRACT_ISSUED`, or `ENROLLED`; likewise, `offer_expires_at` is null unless the application is `OFFERED`. Each admission also adds one to the section's `seats_held` and, when the admit is aid-seeking, one to `aid_seats_held`.

Time then works on the offers, and the director's operational sweep is the checkpoint where time's effects land. A sweep against a cycle runs at the current logical clock and processes, in order: offers whose `offer_expires_at` has passed move `OFFERED` → `EXPIRED`; contracts whose `response_due_at` has passed while still `ISSUED` or `SIGNED` move to `LAPSED`; re-enrollment offers targeting this cycle whose `response_deadline_at` has passed while still `ISSUED` move to `LAPSED`; if the clock has passed the cycle's `melt_deadline_at`, every remaining `WAITLISTED` application moves to `EXPIRED`; and only then does waitlist promotion run. The sweep reports what it did via `expired_offer_count`, `lapsed_contract_count`, `lapsed_reenrollment_count`, `expired_waitlist_count`, and the `promoted_application_ids` array, which lists the promoted applications in the order the promotions were made.

Promotion is a strictly deterministic waterfall. It runs only while the cycle is `EARLY_CLOSED` or `CLOSED` and the logical clock is at or before `melt_deadline_at`; past the melt deadline the waitlist expires instead, as above. For each grade section of the cycle, taken in the sections' creation order, while `seats_available` is positive, the sweep takes the section's `WAITLISTED` applications in the same rank order — `composite_score` descending, `submitted_at` ascending, `created_at` ascending — and promotes the first candidate `WAITLISTED` → `OFFERED`, stamping `offer_expires_at` seven days from the promotion clock, setting `promoted_from_waitlist` to true, recomputing `estimated_deposit_cents` on the same estimated variant, and adding to the section's held counters exactly as a round-close admit does. Seats freed by expirations, lapses, declines, and melts processed earlier in the same sweep feed that same sweep's promotions. An empty candidate set is not an error — nothing happens. Note the asymmetry with round close: the aid-seat composition ceiling gates round-close admits only and does not apply to promotions; aid budget pressure is enforced separately at award acceptance.

An expired offer unwinds exactly like a declined one: any linked aid application releases per §3.4 — subtracting `final_award_cents` from the cycle's `aid_committed_cents` when it was `ACCEPTED` — and the section's `seats_held` decrements, with `aid_seats_held` decrementing when the application was aid-seeking.

### 3.6. Contracts, Deposits, Enrollment, and Summer Melt

An offer becomes binding paper when an `AdmissionOfficer` issues an enrollment contract. Issuance requires the application to be `OFFERED` (`ERR_APPLICATION_NOT_OFFERED` otherwise) and the logical clock to be at or before `offer_expires_at` — a belt check that catches stale offers as `ERR_OFFER_EXPIRED` even before the next sweep would expire them. If an aid application is linked to this application, its `award_status` must be `ACCEPTED`; issuing against an unfinalized, offered-but-unaccepted, or appealed award is `ERR_AID_NOT_FINALIZED`. At most one live — non-`CANCELLED`, non-`LAPSED` — contract exists per application.

Issuance creates the `EnrollmentContract` and moves the application `OFFERED` → `CONTRACT_ISSUED`. The contract snapshots `tuition_cents` from the grade section at issuance and `award_cents` from the accepted final award — zero when the family has no aid — computes `net_tuition_cents` as tuition minus award, and sets `deposit_amount_cents` on the final deposit variant: the larger of 50,000 cents and ten percent of `net_tuition_cents` rounded half-up to a whole cent. Because the final variant bases the award on the accepted figure while the offer letter's estimate used the provisional one, the two deposits diverge whenever verified income diverged from reported income; the contract's figure is the collectible one. The contract's `paid_cents` starts at zero, its `response_due_at` is set fourteen days out from the issuance clock, its `created_student_id` stays null until enrollment, and its own `status` begins at `ISSUED`. The section's `seats_held` does not change at issuance — the seat was already held by the offer. The contract listing filters by `application_id`, `status`, and `created_student_id`.

The family signs an `ISSUED` contract — signing from any other state is `ERR_CONTRACT_NOT_ISSUED` — moving it to `SIGNED`. Deposit payments then arrive against the `SIGNED` contract; paying against a contract in any other state is `ERR_CONTRACT_NOT_SIGNED`. Each payment carries an `amount_cents` — a positive integer, anything else drawing `ERR_VALIDATION` — and must not exceed the remaining deposit balance — `deposit_amount_cents` minus the `paid_cents` collected so far — or it is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422); accepted payments add to `paid_cents`. The moment `paid_cents` reaches or exceeds `deposit_amount_cents`, enrollment fires automatically inside the payment request: the contract moves `SIGNED` → `ENROLLED`, the application moves `CONTRACT_ISSUED` → `ENROLLED`, and a `Student` row is created with `source` `ADMISSION`, the `family_id`, `first_name`, and `last_name` taken from the applicant, `current_grade_section_id` set to the application's `grade_section_id`, and `status` `ACTIVE` — stored on the contract's `created_student_id`. Seats and budget stay put: the seat was already held, and the award was already committed at acceptance.

Contracts that go unanswered do not linger. When the sweep finds the logical clock past `response_due_at` on a contract still `ISSUED` or `SIGNED`, the contract moves to `LAPSED`, and the lapse cascades in one request: the application moves `CONTRACT_ISSUED` → `EXPIRED`, its linked aid application releases — uncommitting `final_award_cents` from the cycle when the award was `ACCEPTED` — and the section's held counters decrement, freeing the seat to feed that same sweep's waitlist promotion.

Families hold three explicit exits. Declining, available to a `Parent` while the application is `OFFERED` (`ERR_APPLICATION_NOT_OFFERED` otherwise), moves the application to `DECLINED`, releases any linked award — uncommitting from the cycle's budget when it was `ACCEPTED` — and frees the held seat for the next sweep's promotion. Withdrawing is broader and state-dependent. From `DRAFT`, withdrawal moves the application to `WITHDRAWN` with no further effects. From `SUBMITTED`, `EVALUATION_COMPLETE`, or `WAITLISTED`, withdrawal additionally releases any linked award — no budget impact, since no award can be `ACCEPTED` that early. From `CONTRACT_ISSUED`, withdrawal moves the linked contract — whether `ISSUED` or `SIGNED` — to `CANCELLED` (any deposit money handling is out of scope; no ledger entry is written), releases the linked award with the usual uncommit-when-accepted rule, and frees the seat. From `OFFERED`, withdrawal moves the application to `WITHDRAWN` and frees the held seat but — the lone exception to §3.4's release cascade — leaves the linked award untouched, so an award already `ACCEPTED` stays `ACCEPTED` and remains committed against the cycle's budget.

The heaviest exit is summer melt: withdrawing an application that is `ENROLLED` moves it to `MELTED` rather than `WITHDRAWN`. The melt cascade moves the linked contract to `MELTED`; forfeits the deposit — the school retains `paid_cents` and writes no refund ledger entry; releases the linked award, which is always `ACCEPTED` at enrollment, subtracting `final_award_cents` from the cycle's `aid_committed_cents`; soft-deactivates the student row named by the contract's `created_student_id` to `INACTIVE`; and frees the seat — a freed melt seat feeds promotion only while the logical clock remains at or before `melt_deadline_at`.

### 3.7. Re-enrollment and Tuition-Increase Notification

Each spring the office invites current families back. A director issues a `ReenrollmentOffer` for a student into a target, upcoming-year cycle — the student's own `status` is not gated, so an `INACTIVE` student may equally be issued an offer — supplying `student_id`, the target `cycle_id`, and — per §2.8 — `expected_student_version` carrying the student's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Issuance requires a grade section for the student's next grade to exist in the target cycle — the natural progression from the student's current grade, with `G12` students graduating and therefore having no next grade — or it fails with `ERR_NO_NEXT_GRADE`. And once a family has accepted, the matter is settled: creating any further offer for the same student and cycle while an `ACCEPTED` offer exists is `ERR_REENROLL_ALREADY_ACCEPTED` — a guard evaluated before the next-grade check, so a student with an `ACCEPTED` offer and no next grade draws `ERR_REENROLL_ALREADY_ACCEPTED`.

Issuing a new offer supersedes any prior `ISSUED` offer for the same student and cycle, moving the older one to `SUPERSEDED`, and increments the student's `version` by one — which is precisely what makes a stale `expected_student_version` detectable. The offer computes its financial figures at issuance: `prior_tuition_cents` snapshots the tuition of the student's current grade section as the increase-notification baseline; `new_tuition_cents` snapshots the tuition of the student's next-grade section in the target cycle; and `response_deadline_at` is copied from the target cycle's `reenroll_response_deadline_at`.

Sibling pricing is computed per line and summed. The family's `ACTIVE` students are ordered by `created_at` ascending — a seniority order needing no identifier tie-break, since creation timestamps are millisecond-stamped sequentially. The family's senior student — index zero — receives a `sibling_discount_cents` of zero, as does a student who is not itself among the family's `ACTIVE` students (an `INACTIVE` offer recipient is treated as index zero); each additional sibling's line receives ten percent of that line's `new_tuition_cents`, rounded half-up to a whole cent. Each line's `discounted_tuition_cents` is then its `new_tuition_cents` minus its `sibling_discount_cents`, and the family's total for the target cycle is the sum of the per-line discounted values. The rounding order is pinned: each line's discount is rounded to whole cents first, and only then are the lines summed — summing raw tuitions and rounding a single ten percent of the aggregate afterwards produces different cents and is not the rule.

The family responds with a `decision` of `ACCEPTED` or `DECLINED`. Responding requires the offer to be `ISSUED` (`ERR_REENROLL_NOT_ISSUED` otherwise) and the logical clock to be at or before `response_deadline_at` — a belt check surfacing `ERR_REENROLL_WINDOW_CLOSED` even before a sweep would lapse the offer. An acceptance moves the offer `ISSUED` → `ACCEPTED` and records the commitment on the student by setting `re_enrolled_for_cycle_id` to the offer's `cycle_id`; a decline moves the offer to `DECLINED` with no further effect. Offers the family ignores are lapsed by the operational sweep on the target cycle once the clock passes `response_deadline_at`, moving them `ISSUED` → `LAPSED`. The re-enrollment listing filters by `student_id`, `cycle_id`, `family_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource — cycles, grade sections, applicants, students, applications, evaluations, test sessions, aid applications, re-enrollment offers, and the enrollment contract produced by contract issuance — return `201 Created`. Operations that modify an existing resource, trigger state transitions, or perform reads return `200 OK`. The table below is a navigational summary only; request bodies, response payloads, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | AdmissionDirector |
| POST | `/admissions/cycles` | Create an admission cycle | AdmissionDirector |
| GET | `/admissions/cycles` | List admission cycles | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/cycles/{cycleId}` | Get one admission cycle | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/cycles/{cycleId}/open` | Open a draft cycle | AdmissionDirector |
| POST | `/admissions/cycles/{cycleId}/close-round` | Close the named round and run the decision sweep | AdmissionDirector |
| POST | `/admissions/cycles/{cycleId}/run-sweep` | Run the operational checkpoint sweep at the current logical clock | AdmissionDirector |
| POST | `/admissions/cycles/{cycleId}/archive` | Archive a closed cycle | AdmissionDirector |
| POST | `/admissions/grade-sections` | Create a grade section for a cycle | AdmissionDirector |
| GET | `/admissions/grade-sections` | List grade sections | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/grade-sections/{sectionId}` | Get one grade section | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/applicants` | Register an applicant child | Parent, AdmissionOfficer |
| GET | `/admissions/applicants` | List applicants | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/applicants/{applicantId}` | Get one applicant | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/students` | Register a currently enrolled student | AdmissionDirector |
| GET | `/admissions/students` | List students | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/students/{studentId}` | Get one student | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/applications` | Create an application | Parent, AdmissionOfficer |
| GET | `/admissions/applications` | List applications | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/applications/{applicationId}` | Get one application | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/applications/{applicationId}/submit` | Submit a draft application | Parent, AdmissionOfficer |
| POST | `/admissions/applications/{applicationId}/issue-contract` | Issue an enrollment contract for an offered seat | AdmissionOfficer |
| POST | `/admissions/applications/{applicationId}/decline` | Decline an offered seat | Parent |
| POST | `/admissions/applications/{applicationId}/withdraw` | Withdraw an application; summer melt when enrolled | Parent |
| POST | `/admissions/evaluations` | Schedule a test or interview evaluation | AdmissionOfficer |
| PATCH | `/admissions/evaluations/{evaluationId}` | Reschedule a scheduled evaluation | AdmissionOfficer |
| POST | `/admissions/evaluations/{evaluationId}/score` | Record an evaluation score | AdmissionOfficer |
| POST | `/admissions/evaluations/{evaluationId}/cancel` | Cancel a scheduled evaluation | AdmissionOfficer |
| GET | `/admissions/evaluations` | List evaluations (staff only) | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer |
| GET | `/admissions/evaluations/{evaluationId}` | Get one evaluation (staff only) | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer |
| POST | `/admissions/test-sessions` | Create a group test session | AdmissionDirector, AdmissionOfficer |
| GET | `/admissions/test-sessions` | List test sessions (staff only) | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer |
| GET | `/admissions/test-sessions/{sessionId}` | Get one test session (staff only) | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer |
| POST | `/admissions/aid-applications` | File a financial-aid application | Parent, FinancialAidOfficer |
| GET | `/admissions/aid-applications` | List aid applications | AdmissionDirector, FinancialAidOfficer, Parent |
| GET | `/admissions/aid-applications/{aidApplicationId}` | Get one aid application | AdmissionDirector, FinancialAidOfficer, Parent |
| POST | `/admissions/aid-applications/{aidApplicationId}/verify` | Verify reported income against documentation | FinancialAidOfficer |
| POST | `/admissions/aid-applications/{aidApplicationId}/resubmit-income` | Resubmit corrected income figures | Parent |
| POST | `/admissions/aid-applications/{aidApplicationId}/finalize-award` | Compute and offer the final award | FinancialAidOfficer |
| POST | `/admissions/aid-applications/{aidApplicationId}/accept-award` | Accept the offered award | Parent |
| POST | `/admissions/aid-applications/{aidApplicationId}/appeal-award` | Appeal the offered award | Parent |
| POST | `/admissions/aid-applications/{aidApplicationId}/revise-award` | Revise an appealed award | FinancialAidOfficer |
| GET | `/admissions/contracts` | List enrollment contracts | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/contracts/{contractId}` | Get one enrollment contract | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/contracts/{contractId}/sign` | Sign an issued contract | Parent |
| POST | `/admissions/contracts/{contractId}/deposit-payments` | Make a deposit payment on a signed contract | Parent |
| POST | `/admissions/reenrollment-offers` | Issue a re-enrollment offer for a student into a target cycle | AdmissionDirector |
| GET | `/admissions/reenrollment-offers` | List re-enrollment offers | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| GET | `/admissions/reenrollment-offers/{offerId}` | Get one re-enrollment offer | AdmissionDirector, AdmissionOfficer, FinancialAidOfficer, Parent |
| POST | `/admissions/reenrollment-offers/{offerId}/respond` | Accept or decline a re-enrollment offer | Parent |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FAMILY_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_HAS_NO_SECTIONS` | 409 Conflict |
| `ERR_APPLICATION_NOT_DRAFT` | 409 Conflict |
| `ERR_APPLICATION_TERMINAL` | 409 Conflict |
| `ERR_APPLICATION_NOT_OFFERED` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ISSUED` | 409 Conflict |
| `ERR_CONTRACT_NOT_SIGNED` | 409 Conflict |
| `ERR_AWARD_NOT_OFFERED` | 409 Conflict |
| `ERR_AWARD_NOT_APPEALABLE` | 409 Conflict |
| `ERR_AWARD_NOT_APPEALED` | 409 Conflict |
| `ERR_AWARD_LOCKED` | 409 Conflict |
| `ERR_AID_NOT_SUBMITTED` | 409 Conflict |
| `ERR_AID_NOT_VERIFIED` | 409 Conflict |
| `ERR_EVALUATION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_REENROLL_NOT_ISSUED` | 409 Conflict |
| `ERR_REENROLL_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_ROUND_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_ROUND_STILL_OPEN` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REENROLL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_AID_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_EVALUATION_KIND` | 409 Conflict |
| `ERR_INTERVIEWER_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_TEST_SESSION_FULL` | 409 Conflict |
| `ERR_EVALUATION_OUTSIDE_SESSION` | 409 Conflict |
| `ERR_GRADE_CYCLE_MISMATCH` | 409 Conflict |
| `ERR_NO_NEXT_GRADE` | 409 Conflict |
| `ERR_AID_NOT_FINALIZED` | 409 Conflict |
| `ERR_AWARD_STALE_VERIFICATION` | 409 Conflict |
| `ERR_AID_PACING_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
