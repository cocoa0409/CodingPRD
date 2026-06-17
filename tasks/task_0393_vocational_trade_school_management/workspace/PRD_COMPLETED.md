# Vocational / Trade School Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Vocational / Trade School Management API, a back-office system that runs the full operational spine of a clock-hour trade school: program and cohort configuration, student admission and enrollment agreements, attendance and clock-hour tracking, satisfactory-academic-progress (SAP) reviews, tuition and Title-IV aid disbursement, withdrawal refunds, externship and clinical placement, licensure-exam readiness, and placement-rate reporting.

The hardest problems in this domain are reconciliation problems. A single enrollment agreement is the meeting point of three ledgers that must always agree: a clock-hour ledger fed by attendance and externship hours, an aid ledger fed by scheduled draws, and a refund ledger that unwinds the other two when a student withdraws. Each posting, excusal, void, release, return, and settlement re-derives a cascade of computed fields, and several of those re-derivations cross entity boundaries — voiding one attendance row changes a student's pace, which changes their SAP standing, which can gate graduation. Because regulators audit these numbers, the system favors deterministic, immediately-consistent recomputation over eventual convergence: every mutation that touches a derived figure recomputes it synchronously and stamps a new version on the affected aggregate.

The API is operated by four staff roles working from a shared term clock. Programs and the clock are configured by administrators; registrars own admission and the agreement lifecycle; financial-aid officers own money in and money out; academic advisors own everything attendance- and outcome-related. The sections below define the shared contracts first, then the business logic, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. All resource collections are mounted under the `/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADER`. If the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `SystemAdmin`, `Registrar`, `FinancialAidOfficer`, and `AcademicAdvisor`. `SystemAdmin` owns program configuration and the deterministic term clock. `Registrar` owns student admission, cohort management, and the enrollment-agreement lifecycle. `FinancialAidOfficer` owns aid disbursement and refund computation and settlement. `AcademicAdvisor` owns attendance, SAP reviews, externships, licensure exams, placement outcomes, and leave-of-absence handling. Any authenticated role may perform read (GET) operations and may read the placement report.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and record it for audit purposes but never compares it to the `id` of any stored resource; there is no resource-ownership check that resolves `X-User-ID` against a row. Authorization is therefore purely role-based: the declared `X-User-Role` either is or is not on the permitted-role list for the requested operation.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All entities in this system are mutable aggregates and additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at its initial value of 1 on creation and increments by one on every mutation. The `version` field is the basis for the optimistic-concurrency mechanism described in §2.7. There are no immutable, version-less resources in this system; the `SystemClock` singleton, the `Program`, the `Cohort`, the `Student`, the `ExternshipSite`, the `EnrollmentAgreement`, the `AttendanceEntry`, the `SapStanding`, the `AidDisbursement`, the `RefundCase`, the `ExternshipAssignment`, the `LicensureExamAttempt`, and the `PlacementOutcome` all carry `id`, `created_at`, `updated_at`, and `version`.

When a computed field is re-derived as a side effect of any operation — for example, a clock-hour rollup on an agreement, or an `active_assignment_count` on a site — that re-derivation is itself a mutation of the affected aggregate: it refreshes that aggregate's `updated_at` and increments its `version`. A single client request can therefore advance the `version` of more than one resource (for instance, completing an externship advances both the agreement and the site).

### 2.5. Nested Reference Resolution and Validation Ordering

This system uses a flat resource topology: every collection lives directly under `/v1`, and cross-entity links are carried as foreign-key fields inside request and entity bodies rather than as nested URL segments. Even so, a single request frequently names several resources at once — a path id plus one or more body ids. All such identifiers are resolved left-to-right, path identifier(s) first and then body identifiers in the order they are documented, and the first identifier that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` before any later identifier or business rule is evaluated.

Across the whole API, validation proceeds in a fixed priority order so that the same failing request always produces the same error. The order is: (1) authentication-header presence and well-formedness, failing with `ERR_MISSING_AUTH_HEADER`; (2) role authorization, failing with `ERR_UNAUTHORIZED`; (3) existence of every referenced id, failing with `ERR_NOT_FOUND`; (4) request-body well-formedness — required fields present, enums drawn from their legal sets, numbers within their ranges — failing with `ERR_INVALID_REQUEST`; (5) the optimistic-concurrency version check on the one endpoint that requires it, failing with `ERR_STALE_VERSION`; (6) the state-machine precondition that the target resource is in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE`; and then (7 and beyond) the operation-specific business rules described in §3. Authentication is checked before authorization, existence before body validity, the version check before any state check, and the state check before business reconciliation — this last ordering is what guarantees the version check on refund settlement runs before any clawback math is attempted.

### 2.6. Precision, Rounding, and Hour Arithmetic

Clock hours and the various pace, completion, and attendance ratios are held as exact decimal quantities and exact ratios internally; the system does not pre-round them. Where a ratio is compared against a configured threshold, the comparison is an exact "greater than or equal to" comparison, so a value that lands exactly on the threshold satisfies it.

Two computed quantities are explicitly stored at four decimal places using round-half-up: a SAP review's `measured_pace_pct`, and the `placement_rate_pct` reported by the placement report. Every monetary figure is an integer count of cents and is never rounded as cents, because cents are already the smallest unit. Where a monetary figure is the product of a tuition amount and a fraction (the earned-tuition and aid-return calculations), the multiplication is performed once on the full amount and then rounded half-up to a whole number of cents — sum-then-round, never per-term or per-draw rounding.

### 2.7. Optimistic Concurrency on Refund Settlement

Exactly one endpoint in this system takes a client-supplied version: the settlement of a refund case. Settling a refund case requires the request body to carry `expected_agreement_version`, the `version` of the parent `EnrollmentAgreement` that the client last observed. The check is mandatory; the field is not optional on this endpoint. Settlement proceeds only when `expected_agreement_version` equals the agreement's current `version`. If any other writer has advanced the agreement's `version` since the client read it — a later aid release, an aid return, an attendance recompute, or a withdrawal cascade — the settlement is rejected with `ERR_STALE_VERSION` and HTTP status 412. A refund case is computed against a snapshot of the agreement's ledger and disbursement state; if that snapshot is stale, the clawback amounts would no longer reconcile, so the stale settlement is refused and the case must instead be reversed and recomputed against the current state. No other endpoint accepts or requires a version field, with the single exception that a student update may optionally carry `expected_student_version` (see §3.2).

### 2.8. Cascades and Hierarchical Consistency

Several operations mutate more than one entity, and every one of those secondary effects is part of the contract. Enrolling an agreement increments the parent cohort's `enrolled_count` and bumps the cohort's `version`. Withdrawing an agreement decrements the cohort's `enrolled_count`, bumps the cohort's `version`, and terminates every still-active externship assignment of that agreement, each termination decrementing its host site's `active_assignment_count` and bumping the site's `version`. Releasing or returning an aid draw, posting or excusing or voiding an attendance row, completing an externship, and resolving an appeal each recompute the agreement's affected rollups and bump the agreement's `version`. These propagations are immediate and synchronous: by the time a response is returned, every dependent figure already reflects the change. The `enrolled_count` of a cohort counts agreements in `ENROLLED`, `LEAVE_OF_ABSENCE`, and `GRADUATED`, so graduating a student does not free a seat. A site's `active_assignment_count` counts assignments in `PLACED` and `IN_PROGRESS`.

## 3. Business Logic & Workflows

### 3.1. Program Configuration and the Term Clock

Everything in the school is timed against a single deterministic clock. The `SystemClock` is a singleton holding `current_term_index`, a non-negative integer term counter that starts at 0 and advances only when an administrator drives it forward. Advancing the clock supplies a target `to_term_index`, which must be greater than or equal to the current value; the clock then sets `current_term_index` to that target. The clock never moves backward and never advances on its own.

A `Program` is the academic template. An administrator creates one with a `name`, a `credential_type` that is one of `DIPLOMA`, `CERTIFICATE`, or `ASSOCIATE`, and the hour requirements that define graduation. `required_clock_hours` is the total clock hours required to graduate and must be an integer greater than 0. `required_theory_hours` is the portion of those that must be classroom/theory hours and must be at least 0 and at most `required_clock_hours`. `required_externship_hours` is the portion that must be externship/clinical hours; the sum of `required_theory_hours` and `required_externship_hours` must not exceed `required_clock_hours`. The sticker price `tuition_cents` is the full-program tuition in cents and must be an integer of at least 0. Three policy ratios may be supplied or left to default: `sap_warning_min_pace_pct` (the minimum completion-pace below which a SAP review yields a warning, default 0.667, greater than 0 and at most 1); `sap_probation_min_pace_pct` (the floor below which a review enters the probation/dismissal track, default 0.5, greater than 0 and strictly less than `sap_warning_min_pace_pct` which is itself at most 1); and `licensure_min_attendance_pct` (the minimum cumulative attendance fraction for licensure eligibility, default 0.9, greater than 0 and at most 1).

A program's `status` advances through `DRAFT`, then `OPEN`, then `CLOSED`. A newly created program is `DRAFT`. Opening it moves `DRAFT → OPEN`; closing it moves `OPEN → CLOSED`. A `CLOSED` program accepts no new cohorts. Both lifecycle moves are administrator-only capabilities.

### 3.2. Students and Admission

A `Student` record carries a `full_name`, an `email`, and the boolean admission prerequisite `hs_diploma_verified`, which records whether the ability-to-benefit / high-school-diploma requirement has been verified and defaults to false when omitted. Email is unique on a case-insensitive basis; an attempt to create a student whose email collides (ignoring case) with an existing student is rejected with `ERR_DUPLICATE_KEY`.

A registrar may update a student to flip the admission flag once a diploma is verified, or to correct the `full_name`. The update accepts `hs_diploma_verified`, `full_name`, and an optional `expected_student_version`. This is the only place outside refund settlement where a client may pass a version; when `expected_student_version` is supplied it must equal the student's current `version` or the update is rejected as stale. Each successful update increments the student's `version` by one.

### 3.3. Cohorts and the Enrollment Agreement Lifecycle

A `Cohort` is a dated delivery of a program. A registrar creates one against an `OPEN` program by supplying `program_id`, a human `code`, a `start_term_index` (the term the cohort begins, an integer of at least 0), an `end_term_index` (the term the cohort ends, which must be strictly greater than `start_term_index` and marks the exclusive end of the half-open `[start_term_index, end_term_index)` interval), and a `seat_capacity` (the maximum number of occupied seats, an integer greater than 0). Creating a cohort requires the referenced program to be `OPEN`; otherwise the request is rejected with `ERR_PROGRAM_NOT_OPEN`. A cohort tracks a computed `enrolled_count` that begins at 0. Its `status` moves `FORMING → RUNNING → COMPLETED`.

Starting a cohort moves it `FORMING → RUNNING`; it requires the cohort to currently be `FORMING` (else `ERR_INVALID_STATE`), the parent program to be `OPEN` (else `ERR_PROGRAM_NOT_OPEN`), and the clock's `current_term_index` to have reached at least the cohort's `start_term_index` (else `ERR_COHORT_NOT_STARTED`). Completing a cohort moves it `RUNNING → COMPLETED`; it requires the cohort to be `RUNNING` (else `ERR_INVALID_STATE`) and that no agreement of the cohort is still in `ENROLLED` or `LEAVE_OF_ABSENCE` (else `ERR_OPEN_AGREEMENTS_EXIST`). A `COMPLETED` cohort locks new enrollment.

An `EnrollmentAgreement` is the central aggregate of the system. A registrar drafts one by supplying `student_id`, `cohort_id`, the contracted tuition `contract_tuition_cents` (an integer of at least 0, which may differ from the program sticker), an optional `scheduled_aid_cents` (the total aid awarded over the program, defaulting to 0, at least 0 and at most `contract_tuition_cents`), and `cancellation_window_term_index` (the last term, inclusive, during which a buyer's-remorse cancellation earns a full refund; it must be at least the cohort's `start_term_index`). At creation the agreement copies `program_id` from the cohort, begins in `DRAFTED`, and seeds its `ledger_balance_cents` equal to `contract_tuition_cents`. The agreement also exposes a set of computed fields described where they are produced: `theory_hours_completed`, `externship_hours_completed`, `clock_hours_completed`, `scheduled_hours_to_date`, `attendance_pct`, `completion_pct`, `disbursed_aid_cents`, `ledger_balance_cents`, `sap_standing` (mirroring the latest SAP review, `GOOD` when none exists, one of `GOOD`, `WARNING`, `PROBATION`, `DISMISSED`), `licensure_eligible`, and `withdrawal_term_index` (null until withdrawal). When a draft is created, the cohort referenced must share the same program scope the registrar intends; the agreement always copies its `program_id` from the cohort, and the scope check fires only when the request body optionally carries a `program_id` that does not equal the cohort's `program_id`, in which case the draft is rejected with `ERR_SCOPE_MISMATCH` (when no `program_id` is supplied in the body, no scope mismatch is possible).

The agreement's `status` machine is the spine of the system: `DRAFTED → ENROLLED`, with `ENROLLED ↔ LEAVE_OF_ABSENCE`, leading to `GRADUATED`; `ENROLLED` or `LEAVE_OF_ABSENCE → WITHDRAWN`; and `DRAFTED → CANCELLED`. Enrolling a drafted agreement requires the agreement to be `DRAFTED` (else `ERR_INVALID_STATE`), the student's `hs_diploma_verified` to be true (else `ERR_ADMISSION_PREREQ_UNMET`), the cohort to be in `FORMING` or `RUNNING` (else `ERR_COHORT_CLOSED`), and the cohort's `enrolled_count` to be strictly less than its `seat_capacity` (else `ERR_COHORT_FULL`); on success the agreement moves to `ENROLLED`, the cohort's `enrolled_count` increases by 1, and the cohort's `version` increments by 1. Cancelling a drafted agreement requires it to be `DRAFTED` (else `ERR_INVALID_STATE`) and moves it to `CANCELLED` with no side effects. Starting a leave of absence requires the agreement to be `ENROLLED` (else `ERR_INVALID_STATE`) and its `sap_standing` to be anything other than `DISMISSED` (else `ERR_SAP_DISMISSED`), moving it to `LEAVE_OF_ABSENCE`. Returning from leave requires the agreement to be `LEAVE_OF_ABSENCE` (else `ERR_INVALID_STATE`) and moves it back to `ENROLLED`.

Withdrawal is available from either `ENROLLED` or `LEAVE_OF_ABSENCE`; from any other state it fails with `ERR_INVALID_STATE`. On withdrawal the agreement's `withdrawal_term_index` is recorded as the clock's `current_term_index`, the cohort's `enrolled_count` decreases by 1 and its `version` increments by 1, and every externship assignment of the agreement that is in `PLACED` or `IN_PROGRESS` is cascaded to `TERMINATED`, each cascade decrementing its host site's `active_assignment_count` by 1 and incrementing the site's `version`.

### 3.4. Attendance and Clock-Hour Rollups

Attendance is the clock-hour ledger. An advisor posts an `AttendanceEntry` against an agreement by supplying `agreement_id`, the `term_index` in which the session occurred (an integer of at least 0), a `kind` of either `THEORY` or `EXTERNSHIP`, `scheduled_hours` (the hours scheduled, a number greater than 0), and `attended_hours` (the hours actually attended, at least 0 and at most `scheduled_hours`; an entry whose attended hours exceed scheduled is malformed and rejected with `ERR_INVALID_REQUEST`). Posting requires the parent agreement to be in `ENROLLED` or `LEAVE_OF_ABSENCE`; otherwise the post is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. A new entry begins `POSTED`. Each posting recomputes the agreement's rollups and attendance and increments the agreement's `version`.

An entry's `status` is one of `POSTED`, `EXCUSED`, or `VOIDED`. Excusing an entry moves it `POSTED → EXCUSED`: it requires the entry to be `POSTED` (else `ERR_INVALID_STATE`) and the parent agreement to be in `ENROLLED` or `LEAVE_OF_ABSENCE` (else `ERR_AGREEMENT_NOT_ACTIVE`); the side effect forces the row's `attended_hours` to 0 while the row stays in the attendance denominator, dropping the agreement's `clock_hours_completed` by the row's prior attended hours, recomputing the rollups, and incrementing the agreement's `version`. Voiding an entry moves it to `VOIDED` from either `POSTED` or `EXCUSED`: it requires the entry to currently be `POSTED` or `EXCUSED` (else `ERR_INVALID_STATE`) and the parent agreement to be in `ENROLLED` or `LEAVE_OF_ABSENCE` (else `ERR_AGREEMENT_NOT_ACTIVE`). A voided row is excluded from every sum and from the denominator. Voiding a `POSTED` row therefore removes it from both the completed sums and the denominator, then recomputes the rollups and `attendance_pct` and bumps the agreement's `version`; voiding an already-`EXCUSED` row (whose attended hours are already 0) removes it from the denominator, recomputes `attendance_pct`, and bumps the agreement's `version`.

The rollups are pure aggregations over the agreement's attendance rows. `theory_hours_completed` is the sum of `attended_hours` over the agreement's rows whose `kind` is `THEORY` and whose `status` is `POSTED`. `externship_hours_completed` is the same sum restricted to `kind` `EXTERNSHIP` and `status` `POSTED`. `clock_hours_completed` is `theory_hours_completed` plus `externship_hours_completed`. `scheduled_hours_to_date` — the attendance denominator — is the sum of `scheduled_hours` over the agreement's rows whose `status` is `POSTED` or `EXCUSED`. `completion_pct` is `clock_hours_completed` divided by the program's `required_clock_hours`. In all of these, `VOIDED` rows are excluded from every sum, and `EXCUSED` rows contribute their `scheduled_hours` to the denominator only (their attended hours having been forced to 0). The `attendance_pct` is `clock_hours_completed` divided by `scheduled_hours_to_date`; as a boundary rule, when `scheduled_hours_to_date` is 0 the `attendance_pct` is exactly 1.0 rather than a division by zero. Hours and ratios are kept as exact values and compared against thresholds with "greater than or equal to" semantics.

### 3.5. Satisfactory Academic Progress and Appeals

A `SapStanding` is a point-in-time progress review. An advisor runs one by supplying `agreement_id` and the `checkpoint_term_index` (the term at which the review is taken, an integer of at least 0). The review snapshots and stores `measured_pace_pct`, `measured_attendance_pct`, and a frozen `standing`, and it sets the agreement's mirror `sap_standing` to that standing while incrementing the agreement's `version`. Running a review never auto-withdraws a student even when the resulting standing is `DISMISSED`; the only path from `DISMISSED` to withdrawal is a denied appeal, described below.

The pace number measures progress against where the schedule says the student should be. Let the cohort term span be the cohort's `end_term_index` minus its `start_term_index` (always greater than 0). The elapsed fraction is `checkpoint_term_index` minus the cohort's `start_term_index`, divided by that span, then clamped to lie between a floor of 0.0 and a cap of 1.0. The expected hours are the elapsed fraction multiplied by the program's `required_clock_hours`. When the expected hours are 0, `measured_pace_pct` is exactly 1.0; otherwise `measured_pace_pct` is `clock_hours_completed` divided by the expected hours. The review also captures `measured_attendance_pct` as the agreement's current `attendance_pct` at review time. `measured_pace_pct` is stored to four decimal places using round-half-up.

The standing classification keys off this review's stored `measured_pace_pct` (the value already rounded to four decimal places, used directly as the comparison input against the two pace policy ratios), the program's two pace policy ratios, and the chain of prior standings. Let the prior standing be the `standing` of the agreement's most recent SAP review before this one, treated as `GOOD` if there is none. If `measured_pace_pct` is at least `sap_warning_min_pace_pct`, the standing is `GOOD` (a pace exactly equal to the warning threshold is `GOOD`). Otherwise, if `measured_pace_pct` is at least `sap_probation_min_pace_pct`, the standing is `WARNING`. Otherwise — the pace is below the probation floor — the result depends on history: if the prior standing was either `WARNING` or `PROBATION`, the standing escalates straight to `DISMISSED`, because a consecutive sub-floor review is a repeat offense; but if the prior standing was `GOOD`, this first sub-floor review yields `PROBATION` rather than `DISMISSED`. These two branches must be treated with equal weight: a first offense lands on `PROBATION`, a repeat offense lands on `DISMISSED`.

`appeal_status` is a parallel dimension on the same review row, independent of the frozen `standing`, cycling `NONE → APPEALED → {APPEAL_GRANTED, APPEAL_DENIED}` and defaulting to `NONE`. Filing an appeal moves `appeal_status` `NONE → APPEALED`: it requires `appeal_status` to currently be `NONE` (else `ERR_INVALID_STATE`) and the review's `standing` to be `PROBATION` or `DISMISSED` (else `ERR_SAP_NOT_APPEALABLE`); appeals are meaningful only on a probation or dismissal standing. Resolving an appeal requires `appeal_status` to be `APPEALED` (else `ERR_INVALID_STATE`) and a body `decision` that is either `GRANT` or `DENY`. A `GRANT` moves `appeal_status` to `APPEAL_GRANTED`; if this review is the agreement's latest SapStanding and its `standing` is `DISMISSED`, the agreement's mirror `sap_standing` is recomputed to `PROBATION` (the grant overturns dismissal down to probation) and the agreement's `version` increments. A `DENY` moves `appeal_status` to `APPEAL_DENIED`; if this review is the agreement's latest SapStanding and its `standing` is `DISMISSED`, the parent agreement is cascade-withdrawn — its `withdrawal_term_index` is set to the clock's `current_term_index`, the cohort's `enrolled_count` decreases by 1 and the cohort's `version` increments, every `PLACED` or `IN_PROGRESS` externship assignment of the agreement is terminated with the corresponding site `active_assignment_count` decrements and site `version` increments, and the agreement's `version` increments.

### 3.6. Aid Disbursement and the Tuition Ledger

Tuition flows in through scheduled aid draws. A financial-aid officer schedules an `AidDisbursement` against an agreement by supplying `agreement_id`, a `disbursement_index` (the 1-based ordinal of this draw in the agreement's schedule, an integer of at least 1 and unique within the agreement; a collision is rejected with `ERR_DUPLICATE_KEY`), a `planned_amount_cents` (the planned draw amount in cents, an integer greater than 0), and a `required_clock_hours_gate` (the cumulative clock hours the student must have completed before this draw may release, an integer of at least 0). A scheduled draw also carries a computed `amount_cents` that is 0 until release. Its `status` moves `SCHEDULED → RELEASED → RETURNED`, with `SCHEDULED → CANCELLED` as an alternate terminal path.

Releasing a draw moves it `SCHEDULED → RELEASED` and is gated by four conditions checked beyond the basic state check: the draw must be `SCHEDULED` (else `ERR_INVALID_STATE`); the parent agreement must be in `ENROLLED` or `LEAVE_OF_ABSENCE` (else `ERR_AGREEMENT_NOT_ACTIVE`); the agreement's `clock_hours_completed` must have reached at least this draw's `required_clock_hours_gate` (else `ERR_DISBURSEMENT_GATE_UNMET`); every lower-index draw of the agreement must already be `RELEASED`, unless this is index 1 (else `ERR_DISBURSEMENT_OUT_OF_ORDER`); and the sum of already-`RELEASED` amounts plus this draw's `planned_amount_cents` must not exceed the agreement's `scheduled_aid_cents` (else `ERR_AID_OVER_AWARD`). On release the draw's `amount_cents` is set to `planned_amount_cents`, the agreement's `disbursed_aid_cents` and `ledger_balance_cents` are recomputed, and the agreement's `version` increments. Cancelling a scheduled draw requires it to be `SCHEDULED` (else `ERR_INVALID_STATE`) and moves it to `CANCELLED`. A draw moves `RELEASED → RETURNED` only as a system cascade from a settled refund (see §3.7), never by direct client action.

The tuition ledger is a simple aggregation. The agreement's `disbursed_aid_cents` is the sum of `amount_cents` over the agreement's draws whose `status` is `RELEASED` (scheduled, returned, and cancelled draws are excluded). The agreement's `ledger_balance_cents` is `contract_tuition_cents` minus `disbursed_aid_cents`. A positive balance means the student still owes; a balance of 0 or below means tuition is fully covered by aid. These are integer-cent quantities and are never rounded.

### 3.7. Withdrawal Refunds and Aid Clawback

When a student withdraws, a financial-aid officer computes a `RefundCase` against the now-`WITHDRAWN` agreement by supplying `agreement_id`, the refund `method` (either `PRO_RATA` or `STATE_TABLE`), and the `withdrawal_term_index` used by the refund math (an integer of at least the cohort's `start_term_index`). The case computes and stores four monetary figures — `tuition_earned_cents` (tuition the school retains), `tuition_refund_cents`, `aid_return_cents` (unearned aid returned to the aid source), and `student_refund_cents` (cash returned to the student after aid return) — and begins in `COMPUTED`. Its `status` forks `COMPUTED → SETTLED` or `COMPUTED → REVERSED`.

The earned-tuition figure depends on the method, but both methods share a buyer's-remorse short circuit. Let the cohort span be the cohort's `end_term_index` minus its `start_term_index`, and let elapsed be the `withdrawal_term_index` minus the cohort's `start_term_index`. If the `withdrawal_term_index` is at or before the agreement's `cancellation_window_term_index`, the school retains nothing and `tuition_earned_cents` is 0 regardless of method. Otherwise, the `PRO_RATA` method earns by actual progress: the earned fraction is `clock_hours_completed` divided by the program's `required_clock_hours`, capped at 1.0, and `tuition_earned_cents` is that fraction multiplied by `contract_tuition_cents`, rounded half-up once to whole cents. The `STATE_TABLE` method earns by scheduled time instead of actual hours: compute the term fraction as elapsed divided by the span, then read a stepped retain rate — a term fraction at or below 0.10 retains 0.00, at or below 0.25 retains 0.25, at or below 0.50 retains 0.50, at or below 0.75 retains 0.75, and anything above 0.75 retains 1.00 — and `tuition_earned_cents` is that retain rate multiplied by `contract_tuition_cents`, rounded half-up once to whole cents. Because the two methods key off different inputs, the same agreement generally yields a different refund under each. In both methods the rounding is applied a single time to the product of `contract_tuition_cents` and the fraction, never per term. The `tuition_refund_cents` is `contract_tuition_cents` minus `tuition_earned_cents`, floored at 0. The `student_refund_cents` is `tuition_refund_cents` minus `aid_return_cents`, floored at 0.

The aid return is the portion of disbursed aid attributable to unearned tuition. The earned program fraction is `clock_hours_completed` divided by the program's `required_clock_hours`, capped at 1.0; the unearned fraction is 1.0 minus that. The aggregate `aid_return_cents` is the agreement's `disbursed_aid_cents` multiplied by the unearned fraction, rounded half-up once to whole cents, and then capped so it never exceeds `disbursed_aid_cents`.

Settling a refund case applies the clawback and is the system's one optimistic-concurrency-guarded operation. It requires the case to be `COMPUTED` (else `ERR_INVALID_STATE`), the parent agreement to be `WITHDRAWN` (else `ERR_AGREEMENT_NOT_WITHDRAWN`), no other refund case of the agreement to be already `SETTLED` (else `ERR_REFUND_ALREADY_SETTLED`; settlement requires exactly one computed case and no prior settled case), and the body `expected_agreement_version` to equal the agreement's current `version` (else `ERR_STALE_VERSION`, HTTP 412, checked before any reconciliation as described in §2.7). On settlement the case moves to `SETTLED` and the clawback cascade runs: the agreement's `RELEASED` aid draws are returned in descending `disbursement_index` order (latest draw first), and for each draw the system returns the smaller of the remaining amount to recover and that draw's `amount_cents`, transitions it `RELEASED → RETURNED`, reduces its `amount_cents` by the clawed-back share, and recomputes the agreement's `disbursed_aid_cents` and `ledger_balance_cents`; the cascade continues until the full `aid_return_cents` is consumed. The per-draw shares are integer cents whose remainder lands on the lowest-index drawn-against draw, and the iteration order is strictly by `disbursement_index` descending, never by id. The agreement's `version` increments on settlement. Reversing a computed case requires it to be `COMPUTED` (else `ERR_INVALID_STATE`) and moves it to `REVERSED` with no side effects, freeing the agreement for a fresh recomputation.

### 3.8. Externship Sites and Placements

An `ExternshipSite` is a clinical or externship host. It is created by an advisor or administrator with a `name` and a `daily_slot_capacity` (the maximum number of concurrently active assignments occupying overlapping term windows, an integer greater than 0). A site tracks a computed `active_assignment_count` starting at 0 and a `status` that moves `ACTIVE → SUSPENDED`. A new site is `ACTIVE`; suspending it moves it to `SUSPENDED`, and a `SUSPENDED` site rejects new placements.

An `ExternshipAssignment` links an agreement to a site and so spans two aggregates. An advisor places a student by supplying `agreement_id`, `site_id`, a `start_term_index` (inclusive start of the externship window, an integer of at least 0), an `end_term_index` (exclusive end, which must be strictly greater than `start_term_index`, defining the half-open window `[start_term_index, end_term_index)`), and `planned_hours` (the hours this assignment is expected to contribute, a number greater than 0). The assignment also carries a computed `verified_hours` that is credited only on completion. Its `status` moves `PLACED → IN_PROGRESS → COMPLETED`, with `PLACED` or `IN_PROGRESS → TERMINATED` as an alternate path.

Placement enforces several conditions in addition to creation well-formedness. The target site must be `ACTIVE`; placing at a suspended site is rejected with `ERR_SITE_SUSPENDED`. A site is not bound to any program or cohort scope, so this endpoint performs no site-to-agreement scope check and never raises `ERR_SCOPE_MISMATCH`: placing an agreement at any existing `ACTIVE` site is permitted. The requested window must not overlap any existing non-terminal assignment of the same agreement, because a student cannot be at two externships at once; an overlap is rejected with `ERR_EXTERNSHIP_WINDOW_CONFLICT`, and because windows are half-open `[start_term_index, end_term_index)`, a closed-interval touch where one window's end equals the next window's start does not count as overlap. Site capacity is also enforced: the count of the site's `PLACED` and `IN_PROGRESS` assignments whose windows intersect the requested window must be strictly less than the site's `daily_slot_capacity` (else `ERR_SITE_CAPACITY_EXCEEDED`), and here too a closed-interval touch where end equals start is not an intersection. On a successful placement the new assignment is `PLACED`, the site's `active_assignment_count` increases by 1, and the site's `version` increments.

Beginning an externship moves it `PLACED → IN_PROGRESS`: it requires the assignment to be `PLACED` (else `ERR_INVALID_STATE`), the clock's `current_term_index` to have reached at least the assignment's `start_term_index` (else `ERR_EXTERNSHIP_NOT_STARTED`), and the parent agreement to be `ENROLLED` (else `ERR_AGREEMENT_NOT_ACTIVE`). Completing an externship moves it `IN_PROGRESS → COMPLETED`: it requires the assignment to be `IN_PROGRESS` (else `ERR_INVALID_STATE`) and a body `actual_hours` greater than 0 (else `ERR_INVALID_REQUEST`). On completion the assignment's `verified_hours` is set to `actual_hours`, the system creates an attendance entry on the agreement of `kind` `EXTERNSHIP` and `status` `POSTED` with both `scheduled_hours` and `attended_hours` equal to `actual_hours` and `term_index` equal to the clock's `current_term_index`, the agreement's externship and clock-hour rollups and `attendance_pct` are recomputed, the agreement's `version` increments, the site's `active_assignment_count` decreases by 1, and the site's `version` increments. Terminating an externship from either `PLACED` or `IN_PROGRESS` (else `ERR_INVALID_STATE`) moves it to `TERMINATED`, decrements the site's `active_assignment_count` by 1, and increments the site's `version`.

### 3.9. Graduation, Licensure Readiness, and Placement Reporting

Graduation is the gated capstone of the agreement lifecycle and is a registrar action that moves an agreement `ENROLLED → GRADUATED`. It enforces, beyond the state check that the agreement is `ENROLLED` (else `ERR_INVALID_STATE`), a sequence of academic and fiscal gates: the agreement's `sap_standing` must be `GOOD` or `WARNING` (else `ERR_SAP_NOT_SATISFACTORY`); the agreement's `clock_hours_completed` must have reached at least the program's `required_clock_hours` (else `ERR_CLOCK_HOURS_UNMET`); its `theory_hours_completed` must have reached at least the program's `required_theory_hours` (else `ERR_THEORY_HOURS_UNMET`); its `externship_hours_completed` must have reached at least the program's `required_externship_hours` (else `ERR_EXTERNSHIP_HOURS_UNMET`); and the agreement's `ledger_balance_cents` must be 0 or below (else `ERR_BALANCE_OUTSTANDING`). On graduation the cohort's `enrolled_count` is unchanged because a graduate still occupies a seat, and the agreement's `licensure_eligible` is recomputed.

Licensure eligibility is a derived boolean that the system recomputes on graduation, whenever a licensure exam attempt is recorded, and whenever a clock-hour rollup runs on an `ENROLLED` or `GRADUATED` agreement. An agreement is graduation-ready when its `clock_hours_completed` is at least the program's `required_clock_hours`, its `theory_hours_completed` is at least the program's `required_theory_hours`, and its `externship_hours_completed` is at least the program's `required_externship_hours`. The agreement's `licensure_eligible` is true when it is graduation-ready, its `attendance_pct` is at least the program's `licensure_min_attendance_pct` (an attendance fraction exactly equal to the threshold is eligible, since the comparison is "greater than or equal to"), and its `sap_standing` is `GOOD` or `WARNING`.

A `LicensureExamAttempt` records a single exam sitting. An advisor supplies `agreement_id`, an `attempt_index` (the 1-based ordinal of the sitting, an integer of at least 1 and unique per agreement; a collision is rejected with `ERR_DUPLICATE_KEY`), a `scaled_score` (the reported scaled score, an integer between 0 and 1000 inclusive), and a `passing_score` (the cut score, an integer between 0 and 1000 inclusive). The system computes `result` as `PASS` when `scaled_score` is at least `passing_score`, and `FAIL` otherwise. Recording an attempt requires the agreement to be `ENROLLED` or `GRADUATED`; an attempt against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. Recording an attempt recomputes the agreement's `licensure_eligible` and increments the agreement's `version`.

A `PlacementOutcome` records what became of a graduate. An advisor supplies `agreement_id`, an `outcome_term_index` (the term the outcome was recorded, an integer of at least 0), an `outcome_type` that is one of `EMPLOYED_IN_FIELD`, `EMPLOYED_RELATED`, `CONTINUING_EDUCATION`, or `NOT_PLACED`, and an `employer_name` that is required unless the `outcome_type` is `NOT_PLACED` or `CONTINUING_EDUCATION`. The system computes `counts_as_placed` as true exactly when the `outcome_type` is `EMPLOYED_IN_FIELD` or `EMPLOYED_RELATED`; this flag is the placement-rate numerator. Recording a placement outcome requires the agreement to be `GRADUATED`; an outcome against an agreement in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`.

The placement report for a program is a read capability available to registrars, advisors, and administrators. The placeable count is the number of the program's agreements whose status is `GRADUATED`. The placed count is the number of those graduated agreements whose latest placement outcome counts as placed: for each graduated agreement, take its placement outcome with the greatest `outcome_term_index`, breaking ties by the later `created_at`, and count it if that latest outcome's `counts_as_placed` is true. The `placement_rate_pct` is the placed count divided by the placeable count, or 0.0 when there are no placeable (graduated) agreements rather than a division by zero; the rate is stored to four decimal places using round-half-up. The report returns the `program_id`, the `graduated_count`, the `placed_count`, and the `placement_rate_pct`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read a resource or drive a state transition or other modification on an existing resource return a `200 OK` status code. All paths are mounted under the `/v1` prefix. Every list endpoint accepts the `limit` and `offset` pagination query parameters described in §2.3 in addition to the filters noted in the description column.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/v1/clock` | Read the current academic-term clock | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/clock/advance` | Advance the term clock to `to_term_index` | SystemAdmin |
| POST | `/v1/programs` | Create a program (DRAFT) | SystemAdmin |
| GET | `/v1/programs` | List programs (filter: `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/programs/{id}` | Get a program | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/programs/{id}/open` | Open a program (DRAFT → OPEN) | SystemAdmin |
| POST | `/v1/programs/{id}/close` | Close a program (OPEN → CLOSED) | SystemAdmin |
| GET | `/v1/programs/{id}/placement-report` | Computed placement-rate report for a program | Registrar, AcademicAdvisor, SystemAdmin |
| POST | `/v1/cohorts` | Create a cohort under an OPEN program (FORMING) | Registrar |
| GET | `/v1/cohorts` | List cohorts (filters: `program_id`, `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/cohorts/{id}` | Get a cohort | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/cohorts/{id}/start` | Start a cohort (FORMING → RUNNING) | Registrar |
| POST | `/v1/cohorts/{id}/complete` | Complete a cohort (RUNNING → COMPLETED) | Registrar |
| POST | `/v1/students` | Create a student | Registrar |
| GET | `/v1/students` | List students (filter: `email`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/students/{id}` | Get a student | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| PATCH | `/v1/students/{id}` | Update a student's admission flag or name | Registrar |
| POST | `/v1/externship-sites` | Create an externship/clinical site (ACTIVE) | AcademicAdvisor, SystemAdmin |
| GET | `/v1/externship-sites` | List externship sites (filter: `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/externship-sites/{id}` | Get an externship site | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/externship-sites/{id}/suspend` | Suspend a site (ACTIVE → SUSPENDED) | AcademicAdvisor, SystemAdmin |
| POST | `/v1/enrollment-agreements` | Draft an enrollment agreement (DRAFTED) | Registrar |
| GET | `/v1/enrollment-agreements` | List agreements (filters: `student_id`, `cohort_id`, `program_id`, `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/enrollment-agreements/{id}` | Get an agreement with all computed rollups | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/enrollment-agreements/{id}/enroll` | Enroll a drafted agreement (DRAFTED → ENROLLED) | Registrar |
| POST | `/v1/enrollment-agreements/{id}/cancel` | Cancel a drafted agreement (DRAFTED → CANCELLED) | Registrar |
| POST | `/v1/enrollment-agreements/{id}/start-loa` | Start a leave of absence (ENROLLED → LEAVE_OF_ABSENCE) | AcademicAdvisor |
| POST | `/v1/enrollment-agreements/{id}/return-from-loa` | Return from leave (LEAVE_OF_ABSENCE → ENROLLED) | AcademicAdvisor |
| POST | `/v1/enrollment-agreements/{id}/graduate` | Graduate an agreement (ENROLLED → GRADUATED) | Registrar |
| POST | `/v1/enrollment-agreements/{id}/withdraw` | Withdraw an agreement (ENROLLED/LEAVE_OF_ABSENCE → WITHDRAWN) | Registrar |
| POST | `/v1/attendance-entries` | Post a clock-hour attendance session (POSTED) | AcademicAdvisor |
| GET | `/v1/attendance-entries` | List attendance entries (filters: `agreement_id`, `status`, `kind`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/attendance-entries/{id}` | Get an attendance entry | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/attendance-entries/{id}/excuse` | Excuse an attendance entry (POSTED → EXCUSED) | AcademicAdvisor |
| POST | `/v1/attendance-entries/{id}/void` | Void an attendance entry (POSTED/EXCUSED → VOIDED) | AcademicAdvisor |
| POST | `/v1/sap-standings` | Run a SAP review at a checkpoint term | AcademicAdvisor |
| GET | `/v1/sap-standings` | List SAP standings (filters: `agreement_id`, `standing`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/sap-standings/{id}` | Get a SAP standing | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/sap-standings/{id}/appeal` | File an appeal (NONE → APPEALED) | AcademicAdvisor |
| POST | `/v1/sap-standings/{id}/resolve-appeal` | Resolve an appeal (APPEALED → APPEAL_GRANTED/APPEAL_DENIED) | AcademicAdvisor |
| POST | `/v1/aid-disbursements` | Schedule an aid disbursement draw (SCHEDULED) | FinancialAidOfficer |
| GET | `/v1/aid-disbursements` | List aid disbursements (filters: `agreement_id`, `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/aid-disbursements/{id}` | Get an aid disbursement | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/aid-disbursements/{id}/release` | Release a scheduled draw (SCHEDULED → RELEASED) | FinancialAidOfficer |
| POST | `/v1/aid-disbursements/{id}/cancel` | Cancel a scheduled draw (SCHEDULED → CANCELLED) | FinancialAidOfficer |
| POST | `/v1/refund-cases` | Compute a refund case for a WITHDRAWN agreement (COMPUTED) | FinancialAidOfficer |
| GET | `/v1/refund-cases` | List refund cases (filters: `agreement_id`, `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/refund-cases/{id}` | Get a refund case | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/refund-cases/{id}/settle` | Settle a computed refund (COMPUTED → SETTLED) with OCC | FinancialAidOfficer |
| POST | `/v1/refund-cases/{id}/reverse` | Reverse a computed refund (COMPUTED → REVERSED) | FinancialAidOfficer |
| POST | `/v1/externship-assignments` | Place a student at a site for a term window (PLACED) | AcademicAdvisor |
| GET | `/v1/externship-assignments` | List assignments (filters: `agreement_id`, `site_id`, `status`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/externship-assignments/{id}` | Get an externship assignment | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/externship-assignments/{id}/begin` | Begin an externship (PLACED → IN_PROGRESS) | AcademicAdvisor |
| POST | `/v1/externship-assignments/{id}/complete` | Complete an externship (IN_PROGRESS → COMPLETED) | AcademicAdvisor |
| POST | `/v1/externship-assignments/{id}/terminate` | Terminate an externship (PLACED/IN_PROGRESS → TERMINATED) | AcademicAdvisor |
| POST | `/v1/licensure-exam-attempts` | Record a licensure exam sitting (PASS/FAIL) | AcademicAdvisor |
| GET | `/v1/licensure-exam-attempts` | List exam attempts (filters: `agreement_id`, `result`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/licensure-exam-attempts/{id}` | Get a licensure exam attempt | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| POST | `/v1/placement-outcomes` | Record a placement outcome for a graduated agreement | AcademicAdvisor |
| GET | `/v1/placement-outcomes` | List placement outcomes (filters: `agreement_id`, `outcome_type`) | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |
| GET | `/v1/placement-outcomes/{id}` | Get a placement outcome | Registrar, FinancialAidOfficer, AcademicAdvisor, SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_COHORT_NOT_STARTED` | 409 Conflict |
| `ERR_COHORT_CLOSED` | 409 Conflict |
| `ERR_COHORT_FULL` | 409 Conflict |
| `ERR_OPEN_AGREEMENTS_EXIST` | 409 Conflict |
| `ERR_ADMISSION_PREREQ_UNMET` | 422 Unprocessable Entity |
| `ERR_SCOPE_MISMATCH` | 409 Conflict |
| `ERR_SAP_DISMISSED` | 409 Conflict |
| `ERR_SAP_NOT_SATISFACTORY` | 422 Unprocessable Entity |
| `ERR_SAP_NOT_APPEALABLE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLOCK_HOURS_UNMET` | 422 Unprocessable Entity |
| `ERR_THEORY_HOURS_UNMET` | 422 Unprocessable Entity |
| `ERR_EXTERNSHIP_HOURS_UNMET` | 422 Unprocessable Entity |
| `ERR_BALANCE_OUTSTANDING` | 402 Payment Required |
| `ERR_DISBURSEMENT_GATE_UNMET` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_OUT_OF_ORDER` | 409 Conflict |
| `ERR_AID_OVER_AWARD` | 402 Payment Required |
| `ERR_AGREEMENT_NOT_WITHDRAWN` | 409 Conflict |
| `ERR_REFUND_ALREADY_SETTLED` | 409 Conflict |
| `ERR_SITE_SUSPENDED` | 409 Conflict |
| `ERR_EXTERNSHIP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EXTERNSHIP_NOT_STARTED` | 409 Conflict |
