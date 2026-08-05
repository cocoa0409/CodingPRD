# Smoking-Cessation & Quitline Program API — Product Requirements Document

## 1. Introduction

Public-health quitlines coordinate a long, non-linear clinical journey: a smoker is enrolled, assessed for readiness, coached over a series of scheduled calls, supplied with nicotine-replacement therapy or medication, encouraged with financial incentives funded by an employer sponsor, and followed up at seven- and thirty-day milestones to measure abstinence. This API is the system of record for that entire journey. It manages employer-sponsored incentive programs and their shared budgets, a roster of multilingual coaches, the participants themselves, and the clinical enrollment that ties them together.

The domain is deliberately intricate. Incentive money is held in a per-employer budget that many participants draw against, so every award and every forfeiture must reconcile that budget precisely and defend it against stale concurrent writes. Quit attempts are cyclic — a participant may relapse and recommit on the same attempt — and disenrollment must cascade cleanly across quit attempts, awards, coaching calls, shipments, and referrals. Outcomes recorded at follow-up milestones drive automatic state transitions on both the quit attempt and the enrollment, and outcome reporting aggregates abstinence rates across a program cohort. This document specifies the contract an implementation must satisfy: the response envelope, the roles and their boundaries, the calculations and their exact rounding, the validation ordering, and the business workflows in full.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or a participant attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles:

- **`ProgramAdmin`** operates employer programs, coaches, the logical clock, and outcome reporting. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- **`CaseManager`** owns the clinical enrollment workflow — enrollments, readiness assessments, quit attempts, coaching calls, NRT shipments, incentive awards, referrals, and follow-up outcomes. When `X-User-Role` is `CaseManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.
- **`Participant`** is an entity-backed self-service role. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a participant compare that resource's participant linkage to `X-User-ID`. A participant may read only its own participant record, its own enrollments, and the child resources of those enrollments, and may submit only readiness assessments and quit attempts on enrollments it owns. Any attempt to reach another participant's data is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. Requests supplying values outside these bounds are rejected as malformed with `ERR_VALIDATION`.

Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources are full, versioned entities and expose a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits marking when the resource was created.
- **`updated_at`** — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- **`version`** — an integer that begins at 1 on creation and increments by one on every mutation. It underpins optimistic concurrency control where applicable.

`EmployerProgram`, `Coach`, `Participant`, `Enrollment`, `QuitAttempt`, `CoachingCall`, `NRTShipment`, `IncentiveAward`, and `Referral` all carry the full set. Two resources are append-only clinical events and carry only `id` and `created_at` — they have neither `updated_at` nor `version`: the `ReadinessAssessment` and the `FollowUpOutcome`. Any prose below that speaks of "bumping the version" or "refreshing `updated_at`" applies only to the versioned resources.

### 2.5. Request Validation Order and Nested Resource Resolution

When an endpoint path names more than one resource (for example, a quit attempt nested under an enrollment nested under a participant), the identifiers are resolved left to right. The first identifier that does not correspond to an existing resource halts processing with that resource's specific not-found error — `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_EMPLOYER_PROGRAM_NOT_FOUND`, `ERR_COACH_NOT_FOUND`, `ERR_QUIT_ATTEMPT_NOT_FOUND`, `ERR_COACHING_CALL_NOT_FOUND`, or `ERR_NRT_SHIPMENT_NOT_FOUND` — before any deeper resource or business rule is consulted.

Across the whole API, checks are evaluated in a fixed priority order, and the first check to fail determines the response:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the operation, and an entity-backed `Participant` acts only on resources it owns, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path- and body-referenced resource exists, validated left to right, else the appropriate not-found error (404).
4. **State admissibility** — the target resource is in a state that admits the requested transition, and enrollment-scoped operations require the enrollment to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE` (409).
5. **Optimistic concurrency** — where an operation carries `expected_employer_program_version`, it must equal the program's current `version`, else `ERR_STALE_VERSION` (412).
6. **Referential legality** — cross-entity reference rules such as coach-language compatibility, an existing committed quit attempt for NRT approval, and the sponsor program not being closed, else `ERR_COACH_LANGUAGE_MISMATCH`, `ERR_NO_COMMITTED_QUIT_ATTEMPT`, or `ERR_PROGRAM_CLOSED` (409).
7. **Temporal legality** — scheduling lead time and coach buffering, NRT course-interval non-overlap, and follow-up window openness, else `ERR_SCHEDULE_WINDOW_INVALID`, `ERR_COACH_DOUBLE_BOOKED`, `ERR_NRT_COURSE_OVERLAP`, or `ERR_FOLLOWUP_WINDOW_NOT_OPEN` (409).
8. **Business constraints** — readiness must pass to activate, NRT allotment must not be exhausted, and at most one follow-up outcome per milestone day, else `ERR_READINESS_NOT_MET`, `ERR_NRT_EXHAUSTED`, or `ERR_DUPLICATE_FOLLOWUP` (422).
9. **Fiscal sufficiency** — the sponsor budget must cover an award amount, else `ERR_PROGRAM_BUDGET_EXCEEDED` (402).

Independently of this ordering, a syntactically malformed body — a missing required field, a value out of range, or an invalid enum member — is rejected with `ERR_VALIDATION` (400).

### 2.6. The Logical Clock and Temporal Windows

The server keeps a logical clock rather than reading wall-clock time. Its startup default is `2026-05-01T00:00:00Z`; before any clock call, the clock reads exactly this default and never falls back to real time. A `ProgramAdmin` may advance or rewind it by supplying a `to_iso8601` instant, and the response echoes the new `current_utc`. Every "current time" comparison in the business rules below — scheduling lead time, follow-up window openness, cohort maturity, and the `recorded_at` stamped on a follow-up outcome — reads this logical clock.

Two temporal rules govern coaching calls. First, a call's `scheduled_start` must be at least `SCHEDULE_MIN_LEAD_MINUTES` — sixty minutes — after the current clock time; a start in the past or inside that one-hour lead window is rejected with `ERR_SCHEDULE_WINDOW_INVALID`. Second, each coach must have breathing room between engagements: a call occupies the half-open interval from its `scheduled_start` up to but not including `scheduled_start` plus `duration_minutes`, and every pair of a coach's calls must be separated by at least `COACH_BUFFER_MINUTES` — fifteen minutes — of clearance. Considering that coach's other calls in `SCHEDULED`, `COMPLETED`, or `NO_SHOW` status, if the requested interval overlaps an existing one, or the gap between the two intervals is strictly less than fifteen minutes, the request is rejected with `ERR_COACH_DOUBLE_BOOKED`. Calls in `CANCELED` status are ignored for this check.

NRT shipments carry their own temporal rule: a new course's date interval, from `course_start_date` through `course_end_date` inclusive, must not overlap the interval of any of the enrollment's existing shipments that are not in `CANCELED` status. An overlap is rejected with `ERR_NRT_COURSE_OVERLAP`. Follow-up outcomes may only be recorded once their window has opened, as detailed in §3.7.

### 2.7. Monetary Amounts, Rates, and Rounding

All money is expressed in integer cents; budgets, award amounts, earned totals, completion bonuses, and payouts are never fractional cents. Readiness scores are integer points with no rounding, NRT supply is whole weeks and doses are whole milligrams, and coaching-buffer arithmetic is at minute granularity.

Two computations involve a fractional rate and therefore require a defined rounding method, and in both cases the method is **round half up**. The completion bonus multiplies each award amount by `COMPLETION_BONUS_RATE` (0.075) and rounds each product to the nearest cent, half up, **before** summing — the rounding is applied per award, not to the aggregate. The outcome-report abstinence rates are percentages rounded half up to one decimal place. No fiscal figure anywhere in the system is truncated.

### 2.8. Optimistic Concurrency Control on Employer Programs

An `EmployerProgram`'s `budget_remaining_cents` is a shared pool that many enrollments draw against, so two write paths guard it with optimistic concurrency on the program's `version`.

Recording a manual incentive award debits that shared budget. The create request must carry `expected_employer_program_version` equal to the sponsor program's current `version`. If another writer — a system milestone award or an earlier manual award — has advanced the program's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client would otherwise overwrite a budget state it has not observed. A strictly sequential retry against the refreshed version may still succeed if the budget can cover it; the rejection is a genuine lost-update guard, not a state precondition.

Closing a program is guarded the same way: the close request must carry `expected_employer_program_version` matching the program's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (412). Endpoints that do not name `expected_employer_program_version` take no version field and perform no such check.

### 2.9. Budget Custody and Incentive Reconciliation

Each `EmployerProgram` holds a `budget_total_cents` set at creation and a derived `budget_remaining_cents`. The remaining budget equals the total minus the sum of `amount_cents` across every `IncentiveAward` in `EARNED` or `PAID` status that belongs to any enrollment of a participant sponsored by that program. Concretely, the balance is maintained incrementally: every time an award is created (whether a system milestone or a manual entry) the program's `budget_remaining_cents` is debited by that award's `amount_cents` and its `version` increments by one; every time an award is forfeited, the amount is credited back and the `version` increments by one again.

Before any award is created, the sponsor's `budget_remaining_cents` must be able to cover the award's `amount_cents`; a shortfall is rejected with `ERR_PROGRAM_BUDGET_EXCEEDED`. Self-pay participants — those with no sponsor — accrue no awards against any budget; a manual award naming a self-pay participant's enrollment resolves to `ERR_EMPLOYER_PROGRAM_NOT_FOUND`. Each enrollment also exposes `incentive_earned_cents`, the sum of `amount_cents` over its own awards in `EARNED` or `PAID` status, recomputed whenever those awards change.

### 2.10. Derived Enrollment Fields and Hierarchical Reconciliation

An `Enrollment` carries several fields the server keeps in sync rather than accepting from clients. `readiness_score` and `readiness_result` mirror the score and `PASS`/`FAIL` result of the latest `ReadinessAssessment`, and are null before the first assessment. `nrt_courses_used` is the count of the enrollment's shipments in `DELIVERED` status; `nrt_courses_remaining` is `nrt_courses_allotted` minus `nrt_courses_used`; and `nrt_eligibility` is `EXHAUSTED` exactly when `nrt_courses_used` is greater than or equal to `nrt_courses_allotted`, and `ELIGIBLE` otherwise. `completed_calls` counts the enrollment's coaching calls in `COMPLETED` status, and `protocol_complete` is true exactly when `completed_calls` is greater than or equal to `PROTOCOL_CALL_TARGET`.

Whenever a child event changes one of these inputs — a shipment reaching `DELIVERED` or reverting via `RETURNED`, a call reaching `COMPLETED`, an award being earned or forfeited — the server recomputes the affected enrollment fields immediately and, for any operation that debits or credits the sponsor budget, mutates the `EmployerProgram` as its own reconciliation, refreshing that program's `updated_at` and incrementing its `version`. These reconciliations happen without the client issuing a separate request against the parent.

## 3. Business Logic & Workflows

### 3.1. Employer Programs and Coaches

A `ProgramAdmin` establishes the sponsors and the coaching roster that the clinical workflow depends on. An employer program is created with a `name` and a `budget_total_cents` (which must be zero or greater), and optionally a `coaching_protocol` — `STANDARD` or `INTENSIVE`, defaulting to `STANDARD` — and a `nrt_courses_allotted` count (zero or greater, defaulting to 3) that sponsored enrollments will inherit. On creation the program's `status` is `ACTIVE`, its `budget_remaining_cents` equals `budget_total_cents`, and its `version` is 1.

A program may later be closed. Closing requires the optimistic-concurrency check of §2.8 and moves `status` from `ACTIVE` to `CLOSED`, incrementing `version`; a program that is not currently `ACTIVE` (for example, one already `CLOSED`) is rejected with `ERR_INVALID_STATE`, and this state check is evaluated before the `expected_employer_program_version` comparison. Once a program is `CLOSED`, any subsequent manual incentive award recorded against one of its participants is rejected with `ERR_PROGRAM_CLOSED`. Closing does not disturb awards already earned.

Coaches are created with a `full_name` and a `languages` array of ISO-639 codes the coach can counsel in. A coach's calendar is consulted when calls are scheduled, and the languages list gates which participants a coach may serve, as described in §3.5.

### 3.2. Participant Registration and Enrollment

A participant is registered — by a `ProgramAdmin` or a `CaseManager` — with a `full_name`, an `email`, a `primary_language` (an ISO-639 code), a baseline `cigarettes_per_day` count (zero or greater), and an optional `employer_program_id`. A participant whose `employer_program_id` names a program is sponsored by it; a participant with no such link is self-pay. The baseline `cigarettes_per_day` is later snapshotted into assessments and drives both readiness scoring and NRT dosing.

A `CaseManager` opens an enrollment for a participant. A new enrollment begins in `PENDING_ASSESSMENT`, with `participant_id` set to its owner. Every child resource of an enrollment — readiness assessments, quit attempts, coaching calls, NRT shipments, incentive awards, referrals, and follow-up outcomes — carries an `enrollment_id` that links it back to this parent. Its `nrt_courses_allotted` is copied from the sponsor program's `nrt_courses_allotted` when the participant is sponsored, and otherwise takes the self-pay default of `DEFAULT_SELF_PAY_NRT_COURSES`, which is 2. At creation `nrt_courses_used` is 0 and `nrt_eligibility` is `ELIGIBLE`. The enrollment moves through the states `PENDING_ASSESSMENT`, `ACTIVE`, `DISENROLLED`, `COMPLETED`, and `DECLINED`, of which the last three are terminal.

### 3.3. Readiness Assessment and Activation

Readiness is measured before a participant may become active. A readiness assessment — submitted by a `CaseManager` or by the owning `Participant` — supplies a `motivation_score` and a `confidence_score`, each an integer from 1 to 10, and a `prior_quit_attempts` count of zero or greater. At submission the participant's current `cigarettes_per_day` is snapshotted onto the assessment.

The assessment's `readiness_score` is computed as follows. Start from the sum of `motivation_score` and `confidence_score`. Add a prior-attempts bonus: zero when `prior_quit_attempts` is 0, one when it is 1 or 2, and two when it is 3 or more. Then subtract a dependence penalty based on the snapshotted `cigarettes_per_day`: zero when it is 10 or fewer, one when it is between 11 and 20 inclusive, and two when it is 21 or more. The assessment's `result` is `PASS` when the resulting `readiness_score` is at least `READINESS_PASS_THRESHOLD` (12), and `FAIL` otherwise. Each new assessment refreshes the enrollment's `readiness_score` and `readiness_result` to mirror the latest one.

Activation, performed by a `CaseManager`, moves the enrollment from `PENDING_ASSESSMENT` to `ACTIVE`. It requires that a readiness assessment exists and that the latest one's result is `PASS`; activating while the latest result is `FAIL` (or while none exists) is rejected with `ERR_READINESS_NOT_MET`. When the participant is sponsored, activation also earns the enrollment milestone: the system creates an `IncentiveAward` with `milestone_type` `ENROLLMENT`, `amount_cents` of 1000, `status` `EARNED`, and `source` `SYSTEM`, which debits the sponsor's `budget_remaining_cents` by 1000, increments the program's `version`, and recomputes the enrollment's `incentive_earned_cents`.

### 3.4. Quit Attempts and the Recommit Cycle

Setting a quit date creates a quit attempt, and requires the enrollment to be `ACTIVE` — a `CaseManager` or the owning `Participant` may do so. The request supplies a `quit_date` (an ISO 8601 UTC instant) and a `method` — one of `COLD_TURKEY`, `NRT_ASSISTED`, `MEDICATION`, or `GRADUAL_REDUCTION`. The new attempt starts in `COMMITTED` and is stamped with an `attempt_number`, a 1-based ordinal in creation order among the enrollment's attempts. When the participant is sponsored and this is the enrollment's first quit attempt, the quit-date milestone is earned automatically: an `IncentiveAward` with `milestone_type` `QUIT_DATE_SET`, `amount_cents` 1500, `status` `EARNED`, and `source` `SYSTEM`, debiting the budget and incrementing the program's `version`.

A `CaseManager` transitions a quit attempt by supplying a `to_status`. A quit attempt may be marked `RELAPSED` from either `COMMITTED` or `QUIT_ACHIEVED`; relapse forfeits the enrollment's `EARNED` awards whose `milestone_type` is `SEVEN_DAY_ABSTINENT` or `THIRTY_DAY_ABSTINENT`, moving each to `FORFEITED`, crediting the sponsor budget by each forfeited amount, and incrementing the program's `version` per credit. The attempt is cyclic: a `RELAPSED` attempt may recommit back to `COMMITTED`, which requires the enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and a new `quit_date` in the request, and updates the attempt's `quit_date` to that recommit value. `ABANDONED` is the attempt's only terminal state and is reached solely as a side effect of disenrollment (§3.8).

### 3.5. Coaching Calls and Protocol Completion

A `CaseManager` schedules a coaching call against an `ACTIVE` enrollment by supplying a `coach_id`, a `scheduled_start`, and a `duration_minutes` (which must be greater than zero). The call is created in `SCHEDULED` status and reserves the coach's time slot. Two gates apply before it is accepted: the chosen coach's `languages` must contain the participant's `primary_language`, else the request is rejected with `ERR_COACH_LANGUAGE_MISMATCH`; and the scheduling lead-time and coach-buffer rules of §2.6 must hold, else `ERR_SCHEDULE_WINDOW_INVALID` or `ERR_COACH_DOUBLE_BOOKED`.

A scheduled call is transitioned by a `CaseManager` supplying a `to_status`. Completing a call — moving `SCHEDULED` to `COMPLETED` — requires the enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and recomputes the enrollment's `completed_calls` and `protocol_complete`. If that completion is the one that brings `completed_calls` to exactly `PROTOCOL_CALL_TARGET` (4) and no protocol-complete award yet exists on the enrollment, the system earns the milestone for a sponsored participant: an `IncentiveAward` with `milestone_type` `PROTOCOL_COMPLETE`, `amount_cents` 2000, `status` `EARNED`, and `source` `SYSTEM`, debiting the budget and incrementing the program's `version`. Marking a call `NO_SHOW` (from `SCHEDULED`) releases the coach's slot without any incentive and leaves `completed_calls` unchanged. Canceling a call (from `SCHEDULED` to `CANCELED`) likewise releases the slot.

### 3.6. NRT and Medication Shipments

An NRT shipment is requested by a `CaseManager` against an `ACTIVE` enrollment, supplying a `medication_type` — `PATCH`, `GUM`, `LOZENGE`, `VARENICLINE`, or `BUPROPION` — a `course_start_date`, and a `course_end_date` (both date-granular ISO 8601 UTC, the end inclusive). The request must not exhaust the allotment: if the enrollment's `nrt_courses_used` is already greater than or equal to its `nrt_courses_allotted`, it is rejected with `ERR_NRT_EXHAUSTED`. The course interval must also satisfy the non-overlap rule of §2.6. The shipment is created in `REQUESTED` status, and two derived fields are computed at request time. The `weeks_supply` is 12 when the participant's `cigarettes_per_day` is 21 or more, 10 when it is between 11 and 20 inclusive, and 8 when it is 10 or fewer. The `dose_mg` applies only to a `PATCH`: it is 21 milligrams when `cigarettes_per_day` is 11 or more and 14 milligrams otherwise; for every other `medication_type` the `dose_mg` is null.

A `CaseManager` advances a shipment by supplying a `to_status`. Approval (`REQUESTED` to `APPROVED`) requires the enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and requires the enrollment to have a quit attempt in `COMMITTED` or `QUIT_ACHIEVED` (else `ERR_NO_COMMITTED_QUIT_ATTEMPT`). An approved shipment may be shipped (`APPROVED` to `SHIPPED`) and then delivered (`SHIPPED` to `DELIVERED`); delivery recomputes the enrollment's `nrt_courses_used` and `nrt_courses_remaining` to include this row and then recomputes `nrt_eligibility`, flipping it to `EXHAUSTED` when used reaches or passes the allotment. A shipment may be canceled from `REQUESTED`, `APPROVED`, or `SHIPPED` (which restores remaining courses for a non-delivered row). A delivered shipment may be returned (`DELIVERED` to `RETURNED`), which recomputes `nrt_courses_used` and `nrt_courses_remaining` dropping this row and recomputes `nrt_eligibility`, flipping it back to `ELIGIBLE` when used falls below the allotment. `DELIVERED`, `CANCELED`, and `RETURNED` are terminal.

### 3.7. Follow-Up Outcomes, Abstinence Milestones, and Completion

A follow-up outcome, recorded by a `CaseManager`, is the pivot on which abstinence milestones and enrollment completion turn. The request supplies a `day` — 7 or 30 — and an `abstinent` boolean, and the server stamps `recorded_at` from the logical clock. A milestone may not be recorded before its window opens: the current clock time must be at or after the relevant quit attempt's `quit_date` plus `day` days, else the request is rejected with `ERR_FOLLOWUP_WINDOW_NOT_OPEN`. The relevant quit attempt is the highest-`attempt_number` attempt in `COMMITTED` status for a seven-day milestone (or in `QUIT_ACHIEVED` status for a thirty-day milestone); if the enrollment has no attempt in that status, the highest-`attempt_number` attempt overall is used, and if the enrollment has no quit attempt at all — or that attempt has no `quit_date` — the window is treated as not open. At most one outcome may exist per enrollment per `day`; a repeat for the same milestone is rejected with `ERR_DUPLICATE_FOLLOWUP`.

A seven-day abstinent outcome (`day` 7, `abstinent` true) advances the highest-`attempt_number` quit attempt currently in `COMMITTED` from `COMMITTED` to `QUIT_ACHIEVED`, and for a sponsored participant earns an `IncentiveAward` with `milestone_type` `SEVEN_DAY_ABSTINENT`, `amount_cents` 2500, `status` `EARNED`, `source` `SYSTEM`, debiting the budget and incrementing the program's `version`. A thirty-day abstinent outcome (`day` 30, `abstinent` true) requires the enrollment to already have a quit attempt in `QUIT_ACHIEVED` — evidence of continuous abstinence since the seven-day milestone; absent such an attempt the request is rejected with `ERR_INVALID_STATE` — and, when sponsored, earns an `IncentiveAward` with `milestone_type` `THIRTY_DAY_ABSTINENT`, `amount_cents` 5000, `status` `EARNED`, `source` `SYSTEM`, again debiting the budget and bumping `version`. That same thirty-day success drives the enrollment from `ACTIVE` to `COMPLETED`: every `EARNED` award on the enrollment moves to `PAID` (the amounts stay committed, so `incentive_earned_cents` is unchanged), and every `OPEN` referral is closed to `CLOSED`.

A non-abstinent outcome drives a relapse. A seven-day outcome with `abstinent` false relapses the committed quit attempt (`COMMITTED` to `RELAPSED`), and a thirty-day outcome with `abstinent` false relapses the achieved attempt (`QUIT_ACHIEVED` to `RELAPSED`); in both cases the enrollment's `EARNED` seven-day and thirty-day awards are forfeited to `FORFEITED`, crediting the budget and bumping the program's `version` per credit.

### 3.8. Incentive Awards, Summaries, and the Disenrollment Cascade

Beyond the system-earned milestones, a `CaseManager` may record a manual incentive award, supplying a `milestone_type` (any of `ENROLLMENT`, `QUIT_DATE_SET`, `SEVEN_DAY_ABSTINENT`, `THIRTY_DAY_ABSTINENT`, `PROTOCOL_COMPLETE`, or `DISCRETIONARY`), an `amount_cents`, and the `expected_employer_program_version` for the optimistic-concurrency guard of §2.8. The award is created with `status` `EARNED` and `source` `MANUAL`, debits the sponsor's `budget_remaining_cents` by `amount_cents`, and increments the program's `version`. The state, concurrency, referential, and fiscal gates apply in the order of §2.5: a non-`ACTIVE` enrollment yields `ERR_ENROLLMENT_NOT_ACTIVE`, then a stale `expected_employer_program_version` yields `ERR_STALE_VERSION`, then a closed program yields `ERR_PROGRAM_CLOSED`, and finally an amount the remaining budget cannot cover yields `ERR_PROGRAM_BUDGET_EXCEEDED`.

The incentive summary reads, for a given enrollment, three figures. The `provisional_earned_cents` is the sum of `amount_cents` over the enrollment's awards in `EARNED` or `PAID` status, with `FORFEITED` awards excluded. The `completion_bonus_cents` is computed only for a completed enrollment: for each non-forfeited award it multiplies that award's `amount_cents` by `COMPLETION_BONUS_RATE` (0.075), rounds each product to the nearest cent half up, and sums those rounded per-award bonuses. The `final_payout_cents` follows one of two variants: while the enrollment is not yet `COMPLETED` the payout is provisional and equals `provisional_earned_cents` with no completion bonus; once the enrollment is `COMPLETED` — the thirty-day continuous-abstinence endpoint reached — the payout is final and equals `provisional_earned_cents` plus `completion_bonus_cents`.

Disenrollment, performed by a `CaseManager`, has two shapes depending on the enrollment's state. Disenrolling a `PENDING_ASSESSMENT` enrollment simply declines it (`PENDING_ASSESSMENT` to `DECLINED`) with no children to unwind. Disenrolling an `ACTIVE` enrollment (`ACTIVE` to `DISENROLLED`) triggers a full cascade: every quit attempt in `COMMITTED`, `QUIT_ACHIEVED`, or `RELAPSED` is abandoned to `ABANDONED`; each such abandonment forfeits the enrollment's `EARNED` awards whose `milestone_type` is `QUIT_DATE_SET`, `SEVEN_DAY_ABSTINENT`, or `THIRTY_DAY_ABSTINENT`, moving each to `FORFEITED`; each forfeiture credits the sponsor's `budget_remaining_cents` by that award's `amount_cents` and increments the program's `version`. In parallel, every coaching call in `SCHEDULED` is canceled to `CANCELED` (releasing the coach slot), every NRT shipment in `REQUESTED`, `APPROVED`, or `SHIPPED` is canceled to `CANCELED` (restoring remaining courses for non-delivered rows), and every referral in `OPEN` is closed to `CLOSED`. Finally the enrollment's `incentive_earned_cents` and `nrt_courses_used` are recomputed.

### 3.9. Referrals and Outcome Reporting

A `CaseManager` records a referral against an `ACTIVE` enrollment with a `referral_type` — `PROVIDER`, `BENEFIT`, or `PHARMACY` — and a `target_name` naming the referred provider, benefit, or pharmacy. A referral starts in `OPEN` and closes to `CLOSED` only through the enrollment-level events described above (completion or disenrollment).

Program outcome reporting, available to a `ProgramAdmin`, summarizes abstinence across a program's cohort. The cohort is every enrollment of a participant whose `employer_program_id` is this program, provided the enrollment has at least one quit attempt whose `quit_date` is set and the current clock time is at or after that quit date plus 30 days. The report returns the `cohort_size` (the number of such enrollments) together with two rates sharing that same denominator. When the cohort is empty both rates are 0.0. Otherwise the `point_prevalence_7day_rate` is 100 times the count of cohort enrollments having a seven-day abstinent outcome, divided by the cohort size, rounded half up to one decimal place; and the `continuous_30day_rate` is 100 times the count of cohort enrollments having both a seven-day abstinent outcome and a thirty-day abstinent outcome, divided by the cohort size, rounded half up to one decimal place. Because the continuous numerator counts a subset of the point-prevalence numerator, the continuous rate never exceeds the seven-day rate.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource, drive a state transition, or otherwise modify an existing resource return `200 OK`. All request and response bodies follow the envelope of §2.2; the fields each operation expects and the side effects each triggers are described in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/employer-programs` | Create an employer-sponsored incentive program | ProgramAdmin |
| GET | `/employer-programs/{id}` | Get an employer program | ProgramAdmin, CaseManager |
| POST | `/employer-programs/{id}/close` | Close a program (OCC-guarded) | ProgramAdmin |
| GET | `/employer-programs/{id}/participants` | List participants sponsored by this program | ProgramAdmin, CaseManager |
| GET | `/employer-programs/{id}/outcome-report` | Program outcome report: cohort size and abstinence rates | ProgramAdmin |
| POST | `/coaches` | Create a coach | ProgramAdmin |
| GET | `/coaches/{id}` | Get a coach | ProgramAdmin, CaseManager |
| GET | `/coaches/{id}/coaching-calls` | List calls booked with this coach | ProgramAdmin, CaseManager |
| POST | `/participants` | Register a participant | ProgramAdmin, CaseManager |
| GET | `/participants/{id}` | Get a participant (Participant may read only itself) | ProgramAdmin, CaseManager, Participant |
| GET | `/participants/{id}/enrollments` | List a participant's enrollments | ProgramAdmin, CaseManager, Participant |
| POST | `/participants/{id}/enrollments` | Create an enrollment for a participant | CaseManager |
| GET | `/enrollments/{id}` | Get an enrollment (Participant may read only its own) | ProgramAdmin, CaseManager, Participant |
| POST | `/enrollments/{id}/activate` | Activate an enrollment (requires latest readiness PASS) | CaseManager |
| POST | `/enrollments/{id}/disenroll` | Disenroll an enrollment; cascades over children | CaseManager |
| POST | `/enrollments/{id}/readiness-assessments` | Submit a readiness assessment | CaseManager, Participant |
| GET | `/enrollments/{id}/readiness-assessments` | List an enrollment's readiness assessments | ProgramAdmin, CaseManager, Participant |
| POST | `/enrollments/{id}/quit-attempts` | Set a quit date (create a quit attempt) | CaseManager, Participant |
| GET | `/enrollments/{id}/quit-attempts` | List an enrollment's quit attempts | ProgramAdmin, CaseManager, Participant |
| POST | `/quit-attempts/{id}/transition` | Transition a quit attempt (RELAPSED or recommit) | CaseManager |
| POST | `/enrollments/{id}/coaching-calls` | Schedule a coaching call | CaseManager |
| GET | `/enrollments/{id}/coaching-calls` | List an enrollment's coaching calls | ProgramAdmin, CaseManager, Participant |
| POST | `/coaching-calls/{id}/transition` | Transition a coaching call | CaseManager |
| POST | `/enrollments/{id}/nrt-shipments` | Request an NRT/medication shipment | CaseManager |
| GET | `/enrollments/{id}/nrt-shipments` | List an enrollment's NRT shipments | ProgramAdmin, CaseManager, Participant |
| POST | `/nrt-shipments/{id}/transition` | Transition a shipment | CaseManager |
| POST | `/enrollments/{id}/incentive-awards` | Record a manual/discretionary incentive award (OCC-guarded) | CaseManager |
| GET | `/enrollments/{id}/incentive-awards` | List an enrollment's incentive awards | ProgramAdmin, CaseManager, Participant |
| GET | `/enrollments/{id}/incentive-summary` | Computed incentive summary | ProgramAdmin, CaseManager, Participant |
| POST | `/enrollments/{id}/referrals` | Create a provider/benefit/pharmacy referral | CaseManager |
| GET | `/enrollments/{id}/referrals` | List an enrollment's referrals | ProgramAdmin, CaseManager, Participant |
| POST | `/enrollments/{id}/follow-up-outcomes` | Record a 7-day or 30-day follow-up outcome | CaseManager |
| GET | `/enrollments/{id}/follow-up-outcomes` | List an enrollment's follow-up outcomes | ProgramAdmin, CaseManager, Participant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_COACH_NOT_FOUND` | 404 Not Found |
| `ERR_QUIT_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_COACHING_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_NRT_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_READINESS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_COACH_LANGUAGE_MISMATCH` | 409 Conflict |
| `ERR_NO_COMMITTED_QUIT_ATTEMPT` | 409 Conflict |
| `ERR_PROGRAM_CLOSED` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_INVALID` | 409 Conflict |
| `ERR_COACH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NRT_COURSE_OVERLAP` | 409 Conflict |
| `ERR_FOLLOWUP_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_NRT_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FOLLOWUP` | 422 Unprocessable Entity |
| `ERR_PROGRAM_BUDGET_EXCEEDED` | 402 Payment Required |
