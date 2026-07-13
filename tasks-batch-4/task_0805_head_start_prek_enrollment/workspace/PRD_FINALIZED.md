# Head Start & Pre-K Enrollment API — Product Requirements Document

## 1. Introduction

The Head Start & Pre-K Enrollment API is the system of record for a federally funded early-childhood program's intake, selection, and compliance obligations. Grantee programs operate under fixed, federally funded slot ceilings and must fill those slots according to a priority-driven selection policy that weighs household economic need, categorical eligibility, homelessness, disability, program-year age, and sibling continuity. Because seats are scarce and demand routinely exceeds supply, the program cannot simply admit applicants first-come-first-served: it must place eligible children on a waitlist, rank them by a reproducible priority score, and generate time-limited offers whenever capacity opens.

Beyond intake, the program carries continuing federal responsibilities for every enrolled child: attendance and average-daily-attendance (ADA) tracking, chronic-absence flagging, health and immunization compliance, family-engagement home visits, and a documented kindergarten transition. At the close of the reporting cycle, the program must aggregate these facts into a Program Information Report (PIR). This document specifies the entities, lifecycle state machines, calculations, validation rules, endpoints, and error semantics that together implement these obligations. It is written for the engineering team that will build the service and is the sole authoritative description of required behavior.

Throughout, the system favors deterministic, auditable computation. Slot capacity is derived from live accounting rather than mutable counters; eligibility and priority are recomputed at well-defined moments; time-sensitive rules (offer expiry, age determination, session windows) evaluate against a server-controlled logical clock so that the program's behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles, spelled precisely as `ProgramAdmin`, `EnrollmentSpecialist`, `FamilyServicesWorker`, and `Family`. If either header is absent or `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Three of the four roles carry an opaque identity. When `X-User-Role` is `ProgramAdmin`, `EnrollmentSpecialist`, or `FamilyServicesWorker`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The fourth role is entity-backed: when `X-User-Role` is `Family`, `X-User-ID` is the `id` of the acting `Family`. For operations that a guardian performs on their own household's records, ownership is checked by comparing the owning `Family` of the target resource — the `family_id` on the associated `Application` — to `X-User-ID`. If a `Family` acts on an application, offer, or enrollment that its household does not own, the request is rejected with `ERR_NOT_OWNER`. This ownership check applies to a guardian submitting or withdrawing an application, accepting or declining an offer, and withdrawing an enrollment when acting as `Family`.

`ProgramAdmin` administers programs, cohorts, selection runs, offer expiry, administrative disenrollment, transition completion, PIR generation, and the logical clock. `EnrollmentSpecialist` handles family intake, applications, eligibility verification, and waitlisting. `FamilyServicesWorker` records attendance, health screenings, and home visits, and may draft transition plans. `Family` acts only on its own household's applications, offers, and enrollment.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a common set of system-managed properties. Each such resource has an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recorded when the resource is first created; an `updated_at` timestamp, refreshed on every mutation; and a `version`, an integer that starts at its initial value and increments by one on each mutation. `version` supports optimistic concurrency control where the system requires it (see §2.6).

There is one deliberate exception. `AttendanceRecord` resources are immutable append-only facts and carry only `id` and `created_at`; they have neither an `updated_at` field nor a `version` field. Every other entity — `Program`, `AgeCohort`, `Family`, `Application`, `Offer`, `Enrollment`, `HealthScreening`, `HomeVisit`, `TransitionPlan`, and `PIRReport` — carries the full common-field set. When a derived field on a resource changes as a side effect of another operation (for example, a cohort's slot accounting), that counts as a mutation of the resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Cohort Slot Accounting and Capacity Consistency

An `AgeCohort` never stores its occupancy as a free-standing mutable counter. Its `filled_slots` is the count of `Enrollment` records for that cohort whose `status` is `ACTIVE`. Its `reserved_slots` is the count of `Offer` records for that cohort whose `status` is `PENDING`. Its `available_slots` is `funded_slots` minus `filled_slots` minus `reserved_slots`, and by construction of the accounting it is never negative. Its `selection_status` is a pure function of that arithmetic: `OPEN` when `available_slots` is greater than zero, otherwise `FULL`. A cohort read always recomputes these four fields from live data before returning them.

Because occupancy is derived, any operation that changes the population of active enrollments or pending offers changes the cohort's derived accounting, and each such change is a mutation of the cohort: it increments `AgeCohort.version` by one and refreshes the cohort's `updated_at`. Concretely, a selection run that generates offers, the acceptance of an offer, the decline or expiry of an offer, the withdrawal of an application that had a pending offer, and the withdrawal, disenrollment, or transition-completion of an enrollment all shift slot accounting and therefore each advance `AgeCohort.version` by one. When slot accounting drops `available_slots` to zero the cohort's `selection_status` becomes `FULL`, which blocks further selection; when a freed slot lifts `available_slots` back above zero the `selection_status` returns to `OPEN`. These `OPEN` and `FULL` states are recomputed by the system rather than set by any explicit client request against the cohort.

### 2.6. Optimistic Concurrency Control on Offer Acceptance

Accepting an offer commits a slot in the target `AgeCohort` and mutates that cohort's slot accounting, so it is guarded by optimistic concurrency control. An acceptance request must carry `expected_cohort_version`, a non-optional field whose value is the client's last observed `version` of the offer's `AgeCohort`. If `expected_cohort_version` does not equal the cohort's current `version` — because another writer has advanced it since the client last read the cohort, whether by committing another acceptance or by freeing a slot through a decline, expiry, or withdrawal — the acceptance is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a guardian from committing against a stale view of remaining capacity. No other endpoint takes a version field; only offer acceptance participates in this check.

### 2.7. Numeric Precision and Rounding

All ratio and rate values are computed to four decimal places using the round-half-up convention. This governs an application's `income_ratio`; an enrollment's `ada_rate`, `annualized_ada_rate`, and `unexcused_absence_rate`; and a report's `avg_ada_rate`. Priority scores are whole integers with no fractional component. Monetary quantities are carried as integer cent values and are not rounded further. Where a rate's denominator would be zero (for instance, before any instructional attendance has been recorded), the rate is defined to be zero rather than undefined.

### 2.8. The Logical Clock

All time-sensitive determinations — offer expiry, age-at-cutoff computation, and home-visit and session-window comparisons — evaluate against a server-controlled logical clock rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any set operation it holds this default and never falls back to real time. An administrative test-driving capability lets a `ProgramAdmin` advance the clock to a supplied `to_iso8601` instant, after which all deadline, expiry, and age computations use that instant.

### 2.9. Nested Resource Retrieval and Referential Validation

Several endpoints address a resource nested under a parent (for example, the attendance records, health screenings, home visits, or transition plans belonging to an enrollment). For any request whose path contains resource identifiers, the system validates each identifier left-to-right and rejects the request at the first identifier that does not resolve, returning the resource-specific not-found error for that identifier. The same principle governs foreign keys supplied in a request body: every referenced `program_id`, `cohort_id`, `family_id`, `enrollment_id`, and `application_id` must resolve to an existing resource, and the system returns the not-found error matching the resource that failed to resolve — `ERR_PROGRAM_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_HEALTH_SCREENING_NOT_FOUND`, `ERR_HOME_VISIT_NOT_FOUND`, or `ERR_TRANSITION_PLAN_NOT_FOUND` — as appropriate.

### 2.10. Request Validation and Evaluation Order

When more than one rule could reject a request, the system evaluates them in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing header or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. For guardian-owned operations, ownership is checked third, yielding `ERR_NOT_OWNER` when the acting `Family` does not own the target. The existence of every path identifier and body foreign key is checked fourth, yielding the appropriate not-found error. State-precondition checks follow (in the order: eligibility-verification-requires-submitted, waitlist-requires-eligible, accept-or-decline-requires-pending-offer, sub-resource-creation-requires-active-enrollment, and the invalid-state checks for transition-plan completion, offer expiry, and home-visit completion). Business rules follow those (duplicate application, age band, offer expiry timing, home-visit overlap, home-visit-during-session, transition prerequisites, empty eligible pool, and the stale-version check). Structural body validation — required fields present and well-typed, enum values within their declared domains, and numeric fields within declared bounds — is evaluated last and, when it fails, yields `ERR_VALIDATION` with HTTP status 400.

## 3. Business Logic & Workflows

### 3.1. Programs, Cohorts, and the Slot Ledger

A `ProgramAdmin` establishes a grantee program by supplying its `name`, its `program_type` (one of `HEAD_START`, `PRE_K`, or `EARLY_HEAD_START`), the `funded_enrollment` total (the count of federally funded slots across the program, which must be zero or greater), the `age_cutoff_date` (the program-year age-determination date in `YYYY-MM-DD` form, against which each child's age in months is computed), and `total_instructional_days` (the number of funded instructional days in the program year, which must be greater than zero and serves as the denominator for the annualized attendance variant). The administrator may also supply `ada_chronic_threshold_pct`, the unexcused-absence fraction at or above which an enrollment is flagged chronically absent; when omitted it defaults to 0.10, meaning a ten-percent unexcused-absence rate.

Within a program, a `ProgramAdmin` defines one or more age cohorts. A cohort names its parent program through `program_id` and carries an `age_band` (one of `INFANT`, `TODDLER`, `PRESCHOOL_3`, or `PRESCHOOL_4`), a `funded_slots` capacity (zero or greater), the inclusive age bounds `min_age_months` and `max_age_months` (the lowest and highest child age in whole months admitted to the cohort), and the daily instructional session times `session_start` and `session_end` (each a 24-hour `HH:MM` time of day, with the session interval treated as `[session_start, session_end)`). On creation, if `funded_slots` is greater than zero the cohort's `selection_status` derives to `OPEN`. The cohort's occupancy fields — `filled_slots`, `reserved_slots`, `available_slots`, and `selection_status` — are the live-derived accounting described in §2.5 and are recomputed on every read of the cohort. Cohorts may be listed for a program or across the system.

### 3.2. Family Intake and Application Drafting

An `EnrollmentSpecialist` or a `Family` opens a household record by providing the `guardian_name`, the `household_size` (the number of persons in the household, at least one, which drives the poverty threshold), the self-declared `annual_income_cents` (gross annual household income in cents, zero or greater), and the `categorical_eligibility` value (one of `NONE`, `TANF`, `SSI`, `SNAP`, or `FOSTER` — a categorical program enrollment that confers eligibility independent of income). The household may also declare `homeless_status`, a McKinney-Vento homeless determination that defaults to false and, when true, confers categorical eligibility and the highest priority weight.

Against that household, an `EnrollmentSpecialist` or a `Family` drafts an application by supplying `program_id`, `cohort_id` (the age cohort the child is applying to), `family_id` (the household whose economic data drives eligibility), `child_first_name`, `child_last_name`, and `child_dob` (the child's date of birth in `YYYY-MM-DD` form). The optional `child_has_iep` flag records whether the child has an active IEP/IFSP disability determination and defaults to false. A newly created application begins in `DRAFT`. At this stage the system-managed fields `verified_income_cents`, `status`, `eligibility_category`, `income_ratio`, `age_months_at_cutoff`, `priority_points`, `submitted_at`, and `waitlisted_at` are not yet populated by intake; `verified_income_cents` in particular remains null until eligibility is verified.

### 3.3. Eligibility Determination and Priority Scoring

Submitting a draft application, an action an `EnrollmentSpecialist` or a `Family` performs, advances it from `DRAFT` to `SUBMITTED`. Submission is refused unless the application is currently in `DRAFT`. Two business guards apply. First, no other non-terminal application may already exist for the same `family_id` and `child_dob` within the same `program_id`; a collision is rejected with `ERR_DUPLICATE_APPLICATION`. Second, the child's computed `age_months_at_cutoff` must fall inside the target cohort's inclusive age band — that is, at least `min_age_months` and at most `max_age_months` — otherwise the submission is rejected with `ERR_AGE_OUT_OF_BAND`. On submission the system computes `age_months_at_cutoff` as the number of complete months between `child_dob` and the program's `age_cutoff_date`, sets `submitted_at` to the current clock instant (which becomes the primary waitlist tie-break key), and computes `income_ratio`, `eligibility_category`, and a provisional `priority_points`.

Eligibility rests on a household's position relative to the Federal Poverty Level (FPL). The FPL threshold for a household is a base of 1,508,000 cents (fifteen thousand eighty dollars) plus 536,000 cents (five thousand three hundred sixty dollars) for each additional household member beyond the first — that is, the base plus the increment multiplied by one less than `household_size`. The income used is the verified income once verification has occurred, and otherwise the declared `annual_income_cents`. The `income_ratio` is that income divided by the household's FPL threshold, rounded half-up to four decimals. The `eligibility_category` is then decided by strict precedence: if `homeless_status` is true the category is `HOMELESS`; otherwise if `categorical_eligibility` is anything other than `NONE` the category is `CATEGORICAL`; otherwise if `income_ratio` is at most 1.00 the category is `INCOME`; otherwise it is `OVER_INCOME`.

The `priority_points` score is a weighted sum capped at a maximum of 90 points. The categorical component is the larger of two quantities: 40 points if the household is homeless (otherwise 0), and the points for the declared categorical program — 35 for `FOSTER`, 30 for `TANF`, 30 for `SSI`, 20 for `SNAP`, and 0 for `NONE`. The income component is tiered on `income_ratio`: 25 points when the ratio is at most 0.50, otherwise 18 points when it is at most 0.75, otherwise 10 points when it is at most 1.00, otherwise 0 points. A disability component adds 15 points when `child_has_iep` is true. An age-priority component adds 10 points when the program's `program_type` is `HEAD_START` and the target cohort's `age_band` is `PRESCHOOL_4`. A sibling component adds 5 points when at least one other `ACTIVE` enrollment exists in the same family (that is, when the count of active enrollments whose application shares this `family_id` is one or more). The raw total is the sum of these five components, and `priority_points` is that raw total or 90, whichever is smaller.

Verifying eligibility, an action reserved to an `EnrollmentSpecialist`, is permitted only when the application is in `SUBMITTED`; otherwise it is rejected with `ERR_APPLICATION_NOT_SUBMITTED`. The specialist supplies `verified_income_cents`, which the system records and then uses to recompute `income_ratio` and `eligibility_category` and to recompute `priority_points` using the verified variant. Because the verified income can differ from the declared income, the tiered income band can shift and the verified score can differ from the provisional one, and the category can cross the 100%-of-FPL boundary. When the recomputed `eligibility_category` is anything other than `OVER_INCOME`, the application advances from `SUBMITTED` to `ELIGIBLE`. When the recomputed category is `OVER_INCOME` — income over 100% of FPL with neither a categorical nor a homeless basis — the application advances from `SUBMITTED` to the terminal `INELIGIBLE` state.

### 3.4. Waitlisting and Selection Runs

Placing an application on the waitlist, an `EnrollmentSpecialist` action, advances it from `ELIGIBLE` to `WAITLISTED` and stamps `waitlisted_at` with the current clock. Waitlisting requires the application to be in `ELIGIBLE`; otherwise it is rejected with `ERR_APPLICATION_NOT_ELIGIBLE`.

A `ProgramAdmin` runs a selection cycle against a cohort to fill open seats. The run requires at least one eligible `WAITLISTED` application in that cohort's pool; against an empty eligible pool it is rejected with `ERR_NO_ELIGIBLE_APPLICANTS`. The run ranks the eligible `WAITLISTED` pool by `priority_points` in descending order, breaking ties by earliest `submitted_at` and then by earliest `created_at`, and selects the top applications up to the number of currently available slots. Selection proceeds only while the cohort's `selection_status` is `OPEN` (equivalently, while `available_slots` is greater than zero). For each selected application the system creates an `Offer` in `PENDING` status, stamps its `offered_at` with the current clock and its `offer_expires_at` at `offered_at` advanced by the fixed offer window of `OFFER_WINDOW_DAYS` (14) days, and advances the application from `WAITLISTED` to `OFFERED`. Each created offer raises the cohort's `reserved_slots` (recomputed) and increments `AgeCohort.version` by one.

### 3.5. Offers and Enrollment Creation

An offer carries `application_id`, `cohort_id` (the cohort whose slot it reserves), a `status` (one of `PENDING`, `ACCEPTED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`), and the `offered_at` and `offer_expires_at` timestamps. A `Family` responds to its own household's offer.

Accepting an offer advances it from `PENDING` to `ACCEPTED` and drives the associated application from `OFFERED` to `ENROLLED`. Acceptance requires the offer to be `PENDING`; an accept or decline against a non-pending offer is rejected with `ERR_OFFER_NOT_PENDING`. Acceptance also requires the current clock to be strictly before `offer_expires_at`; at or after that instant the acceptance is rejected with `ERR_OFFER_EXPIRED`. Finally, acceptance carries the `expected_cohort_version` optimistic-concurrency field and is rejected with `ERR_STALE_VERSION` (HTTP 412) if that value does not equal the cohort's current `version`, as described in §2.6. On a successful acceptance the system creates an `Enrollment` with `status` `ACTIVE` and `health_compliance_status` `PENDING`, stamps its `enrolled_at` with the current clock, records the enrollment's `application_id` and `cohort_id`, raises the cohort's `filled_slots` (recomputed, +1) and lowers its `reserved_slots` (recomputed, −1), and increments `AgeCohort.version` by one.

Declining an offer, also a `Family` action, advances the offer from `PENDING` to `DECLINED` and returns the application from `OFFERED` to `WAITLISTED`, so the application re-enters the waitlist pool; the cohort's `reserved_slots` is recomputed downward and `AgeCohort.version` increments by one. Expiring an offer, a `ProgramAdmin` action, is permitted only while the offer is `PENDING` and the current clock is at or after `offer_expires_at`; it advances the offer from `PENDING` to `EXPIRED`, returns the application from `OFFERED` to `WAITLISTED`, recomputes the cohort's `reserved_slots` downward, and increments `AgeCohort.version` by one. An offer expiry attempted against a non-`PENDING` offer is rejected with `ERR_INVALID_STATE`.

An application may also be withdrawn while it is in any non-terminal state, an action available to a `Family` (on its own household) and, for the pre-offer stages, to an `EnrollmentSpecialist`. Withdrawal advances the application to the terminal `WITHDRAWN` state. If the withdrawn application held a `PENDING` offer, that offer is driven to `WITHDRAWN`, the cohort's `reserved_slots` is recomputed downward, and `AgeCohort.version` increments by one; withdrawal from stages with no outstanding offer has no cohort side effect.

### 3.6. Attendance and Average Daily Attendance

A `FamilyServicesWorker` records a day's attendance for an enrollment by supplying `enrollment_id`, the `attendance_date` (the calendar date in `YYYY-MM-DD` form), a `status` of `PRESENT`, `ABSENT_EXCUSED`, or `ABSENT_UNEXCUSED`, and an `instructional_day` flag that defaults to true and marks whether the date counts toward the attendance denominators. Attendance may only be recorded while the enrollment is `ACTIVE`; otherwise the request is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. Recording attendance recomputes the enrollment's derived attendance fields, which are likewise recomputed whenever the enrollment is read.

Only instructional days enter the ADA denominators. The count of present days is the number of the enrollment's attendance records that are on instructional days with `status` `PRESENT`; the elapsed instructional days is the number of the enrollment's attendance records on instructional days regardless of disposition; and the unexcused days is the number on instructional days with `status` `ABSENT_UNEXCUSED`. The period-to-date `ada_rate` is present days divided by elapsed instructional days, rounded half-up to four decimals, or zero when no instructional days have been recorded. The `annualized_ada_rate` is present days divided by the program's `total_instructional_days`, rounded half-up to four decimals, and therefore yields a different value from `ada_rate` for the same attendance because it uses the full funded-year denominator. The `unexcused_absence_rate` is unexcused days divided by elapsed instructional days, rounded half-up to four decimals, or zero when no instructional days have been recorded. The `chronic_absence` flag is true exactly when `unexcused_absence_rate` is at least the program's `ada_chronic_threshold_pct`.

### 3.7. Health and Immunization Compliance

Every enrollment carries a health-compliance dimension, `health_compliance_status`, that evolves independently of its lifecycle `status`. It begins at `PENDING` when the enrollment is created and may become `COMPLIANT`, `NON_COMPLIANT`, or `EXEMPT`. A `FamilyServicesWorker` creates a required screening for an enrollment by supplying `enrollment_id`, a `screening_type` of `IMMUNIZATION`, `PHYSICAL`, or `DENTAL`, and a `due_date` in `YYYY-MM-DD` form; the screening begins with `status` `DUE`. A screening may only be created while the enrollment is `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE` is returned. A screening's own `status` is one of `DUE`, `UP_TO_DATE`, `OVERDUE`, or `EXEMPT`, and its `completed_date` remains null until it is marked `UP_TO_DATE`.

A `FamilyServicesWorker` updates a screening's `status` and may supply a `completed_date`. Each such update recomputes the owning enrollment's `health_compliance_status` from the full set of that enrollment's screenings, driving the health dimension across its transitions: the enrollment becomes `COMPLIANT` when every one of its screenings is `UP_TO_DATE` or `EXEMPT` and at least one `IMMUNIZATION` screening exists; it becomes `NON_COMPLIANT` when any `IMMUNIZATION` screening is `OVERDUE` (whether the enrollment was previously `PENDING` or `COMPLIANT`); it returns from `NON_COMPLIANT` to `COMPLIANT` when no `IMMUNIZATION` screening remains `OVERDUE` and all screenings are `UP_TO_DATE` or `EXEMPT`; and it moves from `PENDING` to `EXEMPT` when the enrollment's `IMMUNIZATION` screening is marked `EXEMPT` on medical or religious grounds.

### 3.8. Family-Engagement Home Visits and Kindergarten Transition

A `FamilyServicesWorker` schedules a family-engagement home visit for an enrollment by supplying `enrollment_id`, a `scheduled_date` in `YYYY-MM-DD` form, and the visit window times `window_start` and `window_end` (each 24-hour `HH:MM`, with the visit interval on the scheduled date treated as `[window_start, window_end)`). A home visit may only be scheduled while the enrollment is `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE` is returned. A new visit begins in `SCHEDULED`; over its lifecycle a home visit's `status` is one of `SCHEDULED`, `COMPLETED`, `MISSED`, or `CANCELLED`. The system assigns each new visit a `visit_number` — the 1-based ordinal among the enrollment's home visits ordered by `scheduled_date`, then `window_start`, then `created_at`. Two temporal guards apply at scheduling. The proposed window may not overlap an existing non-cancelled home visit for the same enrollment on the same `scheduled_date`; because the interval is half-open, windows that merely touch at a boundary do not overlap, but any genuine overlap is rejected with `ERR_HOME_VISIT_OVERLAP`. The proposed window also may not intersect the child's cohort daily session window `[session_start, session_end)` as a time-of-day comparison, evaluated regardless of the calendar date; an intersection is rejected with `ERR_VISIT_DURING_SESSION`. Marking a home visit completed, another `FamilyServicesWorker` action, advances it from `SCHEDULED` to `COMPLETED` and requires the visit to be `SCHEDULED`; against a non-`SCHEDULED` visit it is rejected with `ERR_INVALID_STATE`. Each completed visit counts toward the enrollment's transition prerequisite.

A kindergarten transition plan is drafted for an enrollment by a `FamilyServicesWorker` or a `ProgramAdmin`, who supplies `enrollment_id`, the `target_school` (the receiving kindergarten or elementary school name), and a planned `transition_date` in `YYYY-MM-DD` form. A transition plan may only be created while the enrollment is `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE` is returned; the plan begins in `DRAFT`. Completing a transition plan is a `ProgramAdmin` action that requires the plan to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and further requires the linked enrollment to be `ACTIVE` with `health_compliance_status` `COMPLIANT` and to have at least two `COMPLETED` home visits; if the health status is not `COMPLIANT` or fewer than two completed home visits exist, completion is rejected with `ERR_TRANSITION_PREREQ_NOT_MET`. On successful completion the plan advances from `DRAFT` to `COMPLETED` and drives the enrollment from `ACTIVE` to the terminal `COMPLETED_TRANSITION`, which lowers the cohort's `filled_slots` (recomputed) and increments `AgeCohort.version` by one.

### 3.9. Enrollment Closure and PIR Reporting

An active enrollment can end in three ways. A `Family` (on its own household), an `EnrollmentSpecialist`, or a `ProgramAdmin` may withdraw an active enrollment, advancing it from `ACTIVE` to the terminal `WITHDRAWN` state; this also drives the enrollment's linked application (through `application_id`) to `WITHDRAWN`, lowers the cohort's `filled_slots`, and increments `AgeCohort.version` by one. A `ProgramAdmin` may administratively disenroll an active enrollment, optionally supplying a `reason`; disenrollment advances the enrollment from `ACTIVE` to the terminal `DISENROLLED` state, lowers the cohort's `filled_slots`, and increments `AgeCohort.version` by one. The third path, transition completion, is described in §3.8. All three require the enrollment to be `ACTIVE` when initiated.

At reporting time a `ProgramAdmin` generates a Program Information Report snapshot for a program by supplying `program_id` and a `reporting_period` label (for example, `2025-2026`). The report begins in `DRAFT` and its `status` is one of `DRAFT` or `SUBMITTED`. At creation the system fixes the reporting pool as every enrollment in the program whose `status` is `ACTIVE` or `COMPLETED_TRANSITION`, and computes the aggregate counts against that pool. The `total_enrolled` is the size of the pool. The `income_eligible_count`, `categorical_count`, and `homeless_count` are the counts of pool enrollments whose application's `eligibility_category` is `INCOME`, `CATEGORICAL`, and `HOMELESS`, respectively. The `immunization_compliant_count` is the count of pool enrollments whose `health_compliance_status` is `COMPLIANT`. The `avg_ada_rate` is computed with a mandatory rounding order: each pool enrollment's `ada_rate` is first rounded to four decimals, those rounded values are then averaged, and the mean is finally rounded half-up to four decimals; this per-enrollment-round-then-average order is required and differs from dividing summed present days by summed instructional days, which is explicitly not used. When the pool is empty, `avg_ada_rate` is zero.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`. Endpoints that modify an existing resource — including the lifecycle transitions driven by submit, verify, waitlist, accept, decline, expire, withdraw, disenroll, complete, and screening updates — return `200 OK`, as do read endpoints. The logical-clock set operation returns `200 OK`. All request and response bodies, side effects, and preconditions are specified in §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a program | ProgramAdmin |
| GET | `/programs/{id}` | Fetch a program | All roles |
| GET | `/programs` | List programs | All roles |
| POST | `/cohorts` | Create an age cohort under a program | ProgramAdmin |
| GET | `/cohorts/{id}` | Fetch a cohort with live slot accounting | All roles |
| GET | `/cohorts` | List cohorts, optionally filtered by program | All roles |
| POST | `/cohorts/{id}/run-selection` | Run a waitlist selection cycle and generate offers | ProgramAdmin |
| POST | `/families` | Create a family household record | EnrollmentSpecialist, Family |
| GET | `/families/{id}` | Fetch a family | All roles |
| POST | `/applications` | Create a DRAFT application | EnrollmentSpecialist, Family |
| GET | `/applications/{id}` | Fetch an application | All roles |
| GET | `/applications` | List applications with filters | All roles |
| POST | `/applications/{id}/submit` | Submit an application; compute eligibility and provisional priority | EnrollmentSpecialist, Family |
| POST | `/applications/{id}/verify-eligibility` | Verify income; recompute eligibility and verified priority | EnrollmentSpecialist |
| POST | `/applications/{id}/waitlist` | Place an ELIGIBLE application on the waitlist | EnrollmentSpecialist |
| POST | `/applications/{id}/withdraw` | Withdraw an application from consideration | EnrollmentSpecialist, Family |
| GET | `/offers/{id}` | Fetch an offer | All roles |
| GET | `/offers` | List offers with filters | All roles |
| POST | `/offers/{id}/accept` | Accept an offer; create the enrollment (OCC-guarded) | Family |
| POST | `/offers/{id}/decline` | Decline an offer; application returns to the waitlist | Family |
| POST | `/offers/{id}/expire` | Expire a PENDING offer whose window has passed | ProgramAdmin |
| GET | `/enrollments/{id}` | Fetch an enrollment with live ADA fields | All roles |
| GET | `/enrollments` | List enrollments with filters | All roles |
| POST | `/enrollments/{id}/withdraw` | Withdraw an active enrollment | EnrollmentSpecialist, ProgramAdmin, Family |
| POST | `/enrollments/{id}/disenroll` | Administratively disenroll an active enrollment | ProgramAdmin |
| POST | `/attendance-records` | Record a day's attendance for an enrollment | FamilyServicesWorker |
| GET | `/enrollments/{id}/attendance-records` | List attendance records for an enrollment | All roles |
| POST | `/health-screenings` | Create a required health screening for an enrollment | FamilyServicesWorker |
| PATCH | `/health-screenings/{id}` | Update a screening's status; may flip health compliance | FamilyServicesWorker |
| GET | `/enrollments/{id}/health-screenings` | List health screenings for an enrollment | All roles |
| POST | `/home-visits` | Schedule a family-engagement home visit | FamilyServicesWorker |
| POST | `/home-visits/{id}/complete` | Mark a home visit completed | FamilyServicesWorker |
| GET | `/enrollments/{id}/home-visits` | List home visits for an enrollment | All roles |
| POST | `/transition-plans` | Create a kindergarten transition plan | FamilyServicesWorker, ProgramAdmin |
| POST | `/transition-plans/{id}/complete` | Complete a transition plan | ProgramAdmin |
| GET | `/enrollments/{id}/transition-plans` | List transition plans for an enrollment | All roles |
| POST | `/pir-reports` | Generate a PIR report snapshot for a program | ProgramAdmin |
| GET | `/pir-reports/{id}` | Fetch a PIR report | ProgramAdmin, EnrollmentSpecialist |
| GET | `/pir-reports` | List PIR reports, optionally by program | ProgramAdmin, EnrollmentSpecialist |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_COHORT_NOT_FOUND` | 404 |
| `ERR_FAMILY_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_HEALTH_SCREENING_NOT_FOUND` | 404 |
| `ERR_HOME_VISIT_NOT_FOUND` | 404 |
| `ERR_TRANSITION_PLAN_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 |
| `ERR_APPLICATION_NOT_ELIGIBLE` | 409 |
| `ERR_OFFER_NOT_PENDING` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_AGE_OUT_OF_BAND` | 422 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_HOME_VISIT_OVERLAP` | 409 |
| `ERR_VISIT_DURING_SESSION` | 409 |
| `ERR_TRANSITION_PREREQ_NOT_MET` | 409 |
| `ERR_NO_ELIGIBLE_APPLICANTS` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
