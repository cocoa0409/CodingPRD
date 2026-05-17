# Retirement 401(k) Plan Management API — Product Requirements Document

## 1. Introduction

This document specifies the Retirement 401(k) Plan Management API, a system that administers the full operational lifecycle of an employer-sponsored 401(k) plan. The system is responsible for plan configuration, participant enrollment and lifecycle, pay-period contribution posting (with formula-driven employer matching under either a Safe Harbor or tiered match arrangement), vesting computation under either cliff or graded schedules, plan loans, hardship withdrawals, and age-based required minimum distributions.

Three operational realities shape the design. First, every dollar that flows through the system is regulated — annual contribution caps, vesting rules, loan caps, hardship suspension periods, and RMD due dates all have legally consequential effects and must be enforced exactly, not approximated. Second, the workflows mix participant-initiated actions (loan requests, hardship requests, deferral elections) with operator-driven steps (contribution posting by payroll, approval by plan administrators, regulatory close-out by compliance officers); a well-defined segregation of duties prevents any single actor from compromising the audit trail. Third, time itself is a controlled variable: the system runs against a per-plan logical clock that operators advance explicitly, so that loan defaults, RMD lapses, and hardship-suspension expirations are reproducible rather than tied to wall-clock drift.

The reader should treat this PRD as the single source of truth for the API's external contract. Field names, state-transition triggers, calculation formulas, validation rules, and error identifiers all appear here in the form the implementation must honor.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All requests to the API must carry two mandatory headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the role under which the action is being performed. A request that omits either header, or whose header values are malformed, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request that presents valid headers but invokes an endpoint the role is not authorized to use is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles, spelled as follows: `PlanAdministrator`, `PayrollProcessor`, `ComplianceOfficer`, and `Participant`.

The semantics of `X-User-ID` differ by role:

- When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `PayrollProcessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` resource. Ownership checks on any participant-scoped operation compare the resource's `participant_id` (or the `participantId` in the URL path) to `X-User-ID`; the participant may act only on themselves.

In addition to role-level authorization, the system enforces **segregation of duties**: even when an operator legitimately holds two role headers across separate calls, the same `X-User-ID` may not perform two adjacent steps in the same workflow on the same plan. Concretely, the same `X-User-ID` may not both request a loan (as a `Participant`) and later approve it (as a `PlanAdministrator`); may not both request a hardship withdrawal and later approve it; and may not both post a `ContributionRecord` (as a `PayrollProcessor`) and later approve a loan against the resulting balance (as a `PlanAdministrator`) within the same plan year. Violations of these constraints are rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned and defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of rows to skip from the beginning of the result set and defaults to 0.

Unless an endpoint declares otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Most primary resources — `Plan`, `Participant`, `Loan`, `HardshipWithdrawal`, and `RMDSchedule` — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID. The identifier carries no type prefix; it is the bare UUID string.
- `created_at` (string): ISO 8601 UTC timestamp with three fractional digits, captured at the moment the row is persisted.
- `updated_at` (string): ISO 8601 UTC timestamp with three fractional digits. Updated on every mutation, including state transitions and computed-field refreshes that originate from server-driven cascades.
- `version` (integer): monotonic counter starting at 1 (or 0, per the implementation's chosen initial value, as long as it strictly increases) and incremented by exactly one on every mutation of the resource. Used for optimistic concurrency control (see §2.10).

Three entity types are immutable ledger or audit rows and therefore carry only `id` and `created_at`; they do not expose `updated_at` and do not expose `version`. Those entities are `ContributionRecord` (the per-pay-period posting), `VestingSnapshot` (the audit row materialized when the vested balance is sampled), `LoanRepayment` (the per-installment posting), and `PlanClock` (the per-plan singleton clock row). Implementations must not emit `updated_at` or `version` on these entities, and the OCC mechanism does not apply to them.

### 2.5. Nested Resource Retrieval and Path Validation

Many endpoints take multiple path identifiers. When validating a path, the server walks the identifiers left to right: first `planId`, then `participantId`, then the leaf identifier (`loanId`, `withdrawalId`, or `scheduleId`, as applicable). The first identifier that does not resolve to an existing resource determines the rejection code: `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_HARDSHIP_NOT_FOUND`, or `ERR_RMD_NOT_FOUND` respectively. A non-existent participant under a non-existent plan must surface as `ERR_PLAN_NOT_FOUND`, not as `ERR_PARTICIPANT_NOT_FOUND`.

### 2.6. Validation Priority

When a single request triggers multiple potential rejections, the server evaluates checks in a fixed priority order and returns the first one that fails. The order is: (1) the user-context header check, returning `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the role authorization and segregation-of-duties check, returning `ERR_INSUFFICIENT_PERMISSIONS`; (3) left-to-right path existence as described in §2.5; (4) the plan-level state gate (the parent `Plan` must be in `ACTIVE` status for any participant-side mutation — enrollment, participant activation, contribution posting, loan request, loan approval, loan rejection, loan repayment, hardship request, hardship approve/deny, RMD scheduling, RMD fulfillment, and deferral updates), returning `ERR_PLAN_NOT_ACTIVE`; (5) the participant-state gate, returning `ERR_PARTICIPANT_NOT_IN_VALID_STATE` when the participant's `status` does not permit the requested operation; (6) the target-resource-state gate, returning a state-specific code (`ERR_LOAN_NOT_REQUESTED`, `ERR_HARDSHIP_NOT_REQUESTED`, `ERR_RMD_NOT_SCHEDULED`) when the leaf resource is not in the state required for the requested transition; then (7) the business rules (uniqueness, suspension, loan caps, vested-balance availability, annual limits, RMD eligibility, RMD uniqueness, RMD fulfillment constraints); and finally (8) the OCC version match. This ordering matters: a missing header always wins over a permission problem; a permission problem always wins over a not-found; a not-found always wins over a state error; a plan-not-active error always wins over a participant-state error; and an OCC mismatch is only reported if every other check would have passed.

### 2.7. Plan Clock and Time-Driven Transitions

The system does not consult the operating system's wall clock during normal operation. Every plan owns a singleton `PlanClock` resource that stores a `current_date` in `YYYY-MM-DD` format. The clock row is created exactly once, when a plan first transitions from `DRAFT` to `ACTIVE`; at that moment its `current_date` is initialized to today's UTC date — the only time a real wall-clock value enters the system. Thereafter, the clock advances solely through the admin-only clock-advance capability described in §3, which accepts a new `new_date` and walks every time-gated transition. Calls that supply a `new_date` that is not strictly greater than the current `current_date` are rejected with `ERR_CLOCK_NOT_MONOTONIC`.

Every date-dependent business rule — loan default detection, RMD overdue cascades, hardship suspension expiration, vesting service-year computation — reads from `PlanClock.current_date`, never from the host clock. This makes time itself a deterministic input to the API.

### 2.8. Hierarchical Consistency and Cascading Effects

When a single operation mutates more than one entity, the system performs every cascade as part of the same logical commit, and every mutated resource receives a fresh `updated_at` together with a `version` increment of one (subject to the exclusions in §2.4 for ledger-style entities).

Approving a hardship withdrawal is the primary multi-hop cascade. The first hop sets `approved_amount_cents` on the `HardshipWithdrawal` to the smaller of `requested_amount_cents` and the participant's `vested_balance_cents_at_request`, then debits the participant's `total_account_balance_cents` by that approved amount. The second hop, executed in the same commit, transitions the participant from `ACTIVE` to `SUSPENDED` and sets `deferral_suspended_until` to the plan clock's current date plus 180 days. The third hop is a forward-looking guarantee rather than an immediate mutation: any subsequent attempt to post a `ContributionRecord` for the same participant while the suspension window is open is rejected with `ERR_DEFERRAL_SUSPENDED` (no row is created and no participant-balance change occurs).

Plan freeze is a similar cross-aggregate event: when the plan transitions from `ACTIVE` to `FROZEN`, every participant whose status is currently `ENROLLED` or `ACTIVE` is flipped to `SUSPENDED` and their `deferral_suspended_until` is set to `9999-12-31` (a sentinel meaning indefinite suspension). Each flipped participant's `updated_at` and `version` are bumped.

Terminating an `ACTIVE` participant triggers a depth-two cascade: in addition to setting the participant's status to `TERMINATED`, the system walks that participant's `RMDSchedule` rows and flips every row whose status is still `SCHEDULED` and whose `due_date` is earlier than `PlanClock.current_date` to `MISSED`. Each flipped RMD row's `updated_at` and `version` are bumped.

The clock-advance capability is, structurally, the largest cascade source. A single advance walks every loan, every RMD schedule, and every participant in scope and applies the time-gated transitions described in §3.

### 2.9. Precision and Rounding

All monetary values are integer cents — there are no fractional cents anywhere in the persisted model or the response payload. Wherever a calculation produces a non-integer cents value through division or rate multiplication, the result is rounded using the **round half up** method to a whole cent. Summations of stored integer cents are exact and require no rounding. Vested percentage is stored to one decimal place.

### 2.10. Optimistic Concurrency Control

Mutation endpoints whose target entity carries a `version` field accept an optional `version` value in the request body. When the client supplies `version`, the server compares it to the resource's current version: if the values match, the mutation proceeds and `version` is incremented; if the values differ, the request is rejected with `ERR_STALE_DATA`. When the client omits `version`, no concurrency check is performed and the mutation proceeds against whatever the current state happens to be. The OCC check is the lowest-priority check in §2.6 — every other validation must have passed first.

OCC does not apply to ledger-style entities (`ContributionRecord`, `VestingSnapshot`, `LoanRepayment`, `PlanClock`), which expose neither `updated_at` nor `version`.

### 2.11. Plan Configuration Variants

A `Plan` is configured along two orthogonal axes: how the employer match is computed, and how vested ownership accrues over time. Both axes are pinned at plan creation and read identically by all downstream calculations.

The match axis is named by `match_formula_type` and takes one of two exact values: `SAFE_HARBOR_BASIC` or `TIERED`. When `match_formula_type` is `TIERED`, the request must also supply a non-empty `tiered_brackets` array, in which each element is an object with `employee_deferral_pct_up_to` (the upper percentage bound of that band) and `match_rate_pct` (the percentage of the employee's deferral within that band that the employer matches), with the brackets ordered ascending by `employee_deferral_pct_up_to`. When `match_formula_type` is `SAFE_HARBOR_BASIC`, any supplied `tiered_brackets` value is ignored. A plan whose configuration is inconsistent with its declared formula (for example, `TIERED` with an empty bracket list) is rejected at create time with `ERR_INVALID_PLAN_CONFIG`.

The vesting axis is named by `vesting_schedule_type` and takes one of two exact values: `CLIFF` or `GRADED`. When `vesting_schedule_type` is `CLIFF`, the request must supply `cliff_years` (the integer number of completed service years required for full vesting), which must be at least 1. When `vesting_schedule_type` is `GRADED`, the request must supply `graded_percentages` — an array of exactly seven integers each in the closed range zero through one hundred, strictly non-decreasing across positions zero through six, and terminating at exactly 100 in position six. The seven entries correspond, in order, to the vested percentage for zero, one, two, three, four, five, and six or more completed service years. Configurations that violate any of these structural rules are rejected with `ERR_INVALID_PLAN_CONFIG`.

A plan also carries `rmd_age`, the integer age at which a participant first becomes subject to required minimum distributions. When the client omits `rmd_age` at create time, the server applies a default of 73.

### 2.12. Vesting Epoch and Lazy Refresh

A plan owns a monotonic counter named `current_vesting_epoch` that starts at zero and advances by exactly one each time an administrator invokes the advance-vesting-epoch capability. Each participant carries two related fields: `vested_pct_snapshot`, the most recently computed vested percentage, and `vesting_epoch_at_snapshot`, the plan's `current_vesting_epoch` value at the moment that snapshot was last refreshed.

Refresh is **lazy**: any read of a participant (e.g., a single-participant GET) compares `vesting_epoch_at_snapshot` against the plan's `current_vesting_epoch`, and if they differ, the system recomputes the vested percentage per §3 and writes the result back to `vested_pct_snapshot` together with the now-matching `vesting_epoch_at_snapshot`. The loan-default cascade additionally writes `vesting_epoch_at_snapshot = -1` so that the next read forces a recompute regardless of the plan's current epoch value.

### 2.13. Concurrency Resolution

The system is internally consistent: when two requests race for the same resource, one of them commits and the other is rejected with a specific error.

- When two `PlanAdministrator` users approve two pending loan requests for the same participant simultaneously, at most one `Loan` per participant may exist in `REQUESTED` or `ACTIVE` status. The serialization point is the loan-status transition from `REQUESTED` to `ACTIVE`: the first writer wins; the second is rejected with `ERR_LOAN_ALREADY_OUTSTANDING`.
- When a hardship approval and a loan approval fire for the same participant simultaneously and both pass their balance checks independently, whichever commits second observes that the first has already mutated `total_account_balance_cents` or moved the participant into `SUSPENDED`; the loser is rejected with `ERR_INSUFFICIENT_VESTED_BALANCE`. The serialization point is the debit against `total_account_balance_cents`.
- When two `PayrollProcessor` users post a `ContributionRecord` for the same participant with an identical `pay_period_end` simultaneously, the pay-period uniqueness invariant — that no two rows may share the pair (`participant_id`, `pay_period_end`) — is enforced at insertion: the first writer commits; the second is rejected with `ERR_DUPLICATE_PAY_PERIOD`.
- When an RMD fulfillment and a plan freeze fire simultaneously while an `RMDSchedule` is past its `due_date`, the serialization point is the plan-status transition from `ACTIVE` to `FROZEN`. If the freeze commits first, the fulfillment is rejected with `ERR_PLAN_FROZEN`; if the fulfillment commits first, the freeze fails its precondition (no `SCHEDULED` overdue RMDs) and is rejected with `ERR_FREEZE_PRECONDITION_VIOLATED`.

## 3. Business Logic & Workflows

### 3.1. Plan Lifecycle

A `PlanAdministrator` initiates the system by creating a `Plan`. The creation payload supplies the human-readable `plan_name`, the integer `plan_year` (for example 2026, used during annual contribution limit checks), the match configuration (`match_formula_type` and, when applicable, `tiered_brackets`), the vesting configuration (`vesting_schedule_type` and, when applicable, `cliff_years` or `graded_percentages`), and optionally `rmd_age`. The newly created plan starts with `status` of `DRAFT` and `current_vesting_epoch` of zero.

Activation, performed by a `PlanAdministrator`, advances the plan from `DRAFT` to `ACTIVE`. Activation requires that `match_formula_type` and `vesting_schedule_type` are populated, and that the corresponding variant fields are coherent: if the match is `TIERED`, `tiered_brackets` must be non-empty; if vesting is `CLIFF`, `cliff_years` must be at least 1; if vesting is `GRADED`, `graded_percentages` must have length 7 and its position-six entry must equal 100. A configuration that violates these rules at activation time is rejected with `ERR_INVALID_PLAN_CONFIG`. An attempt to activate a plan whose current `status` is anything other than `DRAFT` is rejected with `ERR_PLAN_NOT_DRAFT`. A successful activation creates the singleton `PlanClock` row for this plan with `current_date` set to today's UTC date.

Freezing the plan, also performed by a `PlanAdministrator`, advances `status` from `ACTIVE` to `FROZEN`. `FROZEN` is terminal — the plan never leaves it. Freeze is rejected with `ERR_FREEZE_PRECONDITION_VIOLATED` whenever any of three preconditions is unmet: no `Loan` may be in `ACTIVE` status with `outstanding_principal_cents` greater than zero; no `HardshipWithdrawal` may be in `REQUESTED` status; and no `RMDSchedule` may be in `SCHEDULED` status with a `due_date` earlier than `PlanClock.current_date`. A successful freeze, as described in §2.8, flips every participant currently in `ENROLLED` or `ACTIVE` to `SUSPENDED` and sets each such participant's `deferral_suspended_until` to `9999-12-31`. Any participant-side mutation attempted after the plan has reached `FROZEN` is rejected with `ERR_PLAN_FROZEN`.

A separate administrator capability, the advance-vesting-epoch action, increments `current_vesting_epoch` by exactly one. It does not eagerly recompute any vested percentage; instead, as described in §2.12, downstream reads observe the epoch mismatch and refresh `vested_pct_snapshot` lazily.

The plan clock is advanced by the admin-only clock-advance capability, which accepts a payload containing `new_date`. The new date must satisfy `new_date > PlanClock.current_date`, otherwise the request is rejected with `ERR_CLOCK_NOT_MONOTONIC`. Each successful advance walks the in-scope state machines and applies the following time-gated automatic transitions in a single commit: every `Loan` whose `status` is `ACTIVE`, whose `next_due_date` plus 90 days is earlier than the new `current_date`, and whose `outstanding_principal_cents` is greater than zero, is moved to `DEFAULTED` (with the cascade described in §3.5); every `RMDSchedule` whose `status` is `SCHEDULED` and whose `due_date` is earlier than the new `current_date` is moved to `MISSED`; and every `Participant` whose `status` is `SUSPENDED` and whose `deferral_suspended_until` is earlier than the new `current_date` is restored to `ACTIVE` with `deferral_suspended_until` reset to null. Plan-year boundary crossings during a single advance do not eagerly recompute vested percentages; the next read does so lazily.

### 3.2. Participant Enrollment and Lifecycle

Within an `ACTIVE` plan, a `PlanAdministrator` enrolls a participant by supplying the external payroll identifier `employee_external_id` (which must be unique within the plan), the date of birth `date_of_birth` and hire date `hire_date` (both in `YYYY-MM-DD` form), the gross annual compensation `annual_compensation_cents`, and the initial deferral election `elected_deferral_pct` (a percentage of pay between zero and one hundred inclusive, with up to two decimal places of precision). The newly enrolled participant has `status` of `ENROLLED`, with the computed fields `deferral_suspended_until` initialized to null, `vested_pct_snapshot` initialized to zero, `vesting_epoch_at_snapshot` initialized to zero, `cumulative_employee_contribution_cents` initialized to zero, `cumulative_employer_match_cents` initialized to zero, and `total_account_balance_cents` initialized to zero.

A `PayrollProcessor` activates the enrolled participant, transitioning `status` from `ENROLLED` to `ACTIVE`. Activation requires the parent plan to be in `ACTIVE` status; otherwise the request is rejected with `ERR_PLAN_NOT_ACTIVE`.

Termination of a participant is performed by a `PlanAdministrator` and is permitted from either `ACTIVE` or `SUSPENDED`; both paths transition the participant to the terminal `TERMINATED` state. The precondition for either path is the same: the participant must have no `Loan` in `ACTIVE` status, otherwise the request is rejected with `ERR_PARTICIPANT_NOT_IN_VALID_STATE`. When the source state is `ACTIVE`, the cascade described in §2.8 fires: the system flips every `RMDSchedule` of that participant whose `status` is `SCHEDULED` and whose `due_date` is earlier than `PlanClock.current_date` to `MISSED`.

A participant transitions automatically between `ACTIVE` and `SUSPENDED` under two system-driven triggers. The first is the system-driven `ACTIVE → SUSPENDED` transition, which fires automatically when a `HardshipWithdrawal` for the participant moves from `REQUESTED` to `APPROVED`; its side effect, as detailed in §2.8, is to set `deferral_suspended_until` to `PlanClock.current_date + 180 days`. The second is the system-driven `SUSPENDED → ACTIVE` transition, which fires automatically during a clock-advance when the new `current_date` is strictly greater than the participant's `deferral_suspended_until`; its side effect is to reset `deferral_suspended_until` to null.

Either the participant themselves or a `PayrollProcessor` may update `elected_deferral_pct` through the deferral-update capability. The new value must be in the range zero through one hundred inclusive; otherwise the request is rejected with `ERR_INVALID_REQUEST`.

A read of a single participant returns `total_account_balance_cents` and the participant's current vested balance. The participant's `vested_pct_snapshot` is lazily refreshed on read when `vesting_epoch_at_snapshot` is not equal to the plan's `current_vesting_epoch`, per §2.12.

### 3.3. Contribution Posting and the Employer Match

A `PayrollProcessor` posts a pay-period contribution against an `ACTIVE` participant under an `ACTIVE` plan. The request body supplies `pay_period_end` (the period-ending date in `YYYY-MM-DD` form) and `gross_pay_cents` (the integer gross pay for that period). The system computes both `employee_amount_cents` and `employer_match_cents` and persists the resulting `ContributionRecord` (an immutable ledger entry whose `status` is `POSTED` from the moment of insertion). A request that fails validation does not produce a row; it is rejected with the appropriate error code and no `ContributionRecord` is created.

**Employee deferral.** The eligible deferral percentage is the smaller of the participant's currently elected `elected_deferral_pct` and one hundred. The employee amount is the gross pay multiplied by the eligible deferral percentage divided by one hundred, then rounded half up to the nearest whole cent. The resulting integer is then subject to the year-to-date cap described below.

**Employer match — Safe Harbor Basic variant.** When the plan's `match_formula_type` is `SAFE_HARBOR_BASIC`, the match is computed as a two-tier rule on the eligible deferral percentage: the first tier covers the first three percentage points of deferral and is matched at one hundred percent (a one-for-one match); the second tier covers the next two percentage points (deferral above three points and up to and including five points) and is matched at fifty percent. Specifically, let *tier1_pct* be the smaller of the eligible deferral percentage and 3.0; let *tier2_pct* be the smaller of (a) zero or the eligible deferral percentage minus 3.0, whichever is larger, and (b) 2.0. The match percentage of pay is *tier1_pct* multiplied by 1.0 plus *tier2_pct* multiplied by 0.5. The employer match amount in cents is the gross pay multiplied by that match percentage divided by one hundred, then rounded half up to a whole cent. Under this variant, any supplied `tiered_brackets` value on the plan is ignored entirely.

**Employer match — Tiered variant.** When the plan's `match_formula_type` is `TIERED`, the system walks `tiered_brackets` in ascending order of `employee_deferral_pct_up_to`. For each bracket, the band width in deferral percentage points is the bracket's `employee_deferral_pct_up_to` minus the previous bracket's upper bound (or zero for the first bracket), floored at zero. The applied deferral percentage points within that band is the smaller of the remaining un-allocated eligible deferral and that band width. The contribution to the running match percentage of pay from that band is the applied points multiplied by the bracket's `match_rate_pct` divided by one hundred. The remaining deferral is reduced by the applied points and the previous-bracket upper bound is set to the current bracket's `employee_deferral_pct_up_to`. The walk terminates early when the remaining deferral reaches zero. The employer match amount in cents is the gross pay multiplied by the resulting match percentage divided by one hundred, then rounded half up to a whole cent. The same `gross_pay_cents` and `elected_deferral_pct` inputs intentionally produce a different `employer_match_cents` under `TIERED` than under `SAFE_HARBOR_BASIC`.

**Annual limit enforcement.** Two annual constants govern the system, fixed across all plans for the current plan-year context: the employee annual contribution limit is $23,500 (that is, 2,350,000 cents), and the employer annual match limit is $46,000 (that is, 4,600,000 cents). Before the new row is persisted, the system computes the participant's year-to-date employee total as the sum of `employee_amount_cents` over all of that participant's existing `ContributionRecord` rows whose `pay_period_end` falls in the same calendar year as the new row's `pay_period_end`. The same year-to-date sum is computed on the employer side from `employer_match_cents`. The proposed employee amount is then compared: if the year-to-date employee total plus the proposed employee amount would exceed the employee annual limit, the entire request is rejected with `ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED` and no row is created. The proposed employer amount is treated asymmetrically: if the year-to-date employer total plus the proposed employer amount would exceed the employer annual limit, the employer side is **silently capped** (never rejected) at the larger of zero and the employer annual limit minus the year-to-date employer total, and the capped value is what is persisted in `employer_match_cents`.

**Pay-period uniqueness.** No two `ContributionRecord` rows may share the pair (`participant_id`, `pay_period_end`). A duplicate request is rejected with `ERR_DUPLICATE_PAY_PERIOD`.

**Deferral suspension gate.** A contribution post is rejected with `ERR_DEFERRAL_SUSPENDED` whenever the participant's `deferral_suspended_until` is non-null and `PlanClock.current_date` is less than or equal to `deferral_suspended_until`. (Because freeze sets `deferral_suspended_until` to `9999-12-31`, contributions cannot post on frozen plans even via the participant-state path; in practice, frozen plans also fail the higher-priority `ERR_PLAN_NOT_ACTIVE` check first.)

**Side effects on success.** On successful posting, the participant's `cumulative_employee_contribution_cents` is increased by the (capped) `employee_amount_cents`, the participant's `cumulative_employer_match_cents` is increased by the (capped) `employer_match_cents`, and `total_account_balance_cents` is updated to reflect both deltas.

A list of `ContributionRecord` rows is available to `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor`, and the owning `Participant`; the list endpoint accepts an optional `year` query parameter to scope results.

### 3.4. Vesting Computation and Snapshots

The vested percentage is a function of the participant's elapsed service and the plan's vesting variant. Service is measured in completed integer years: starting from the participant's `hire_date` and reading the plan's `current_date` from `PlanClock`, the system computes the number of days between the two dates and divides by 365 with integer floor division to obtain the completed service-year count.

**Cliff variant.** When `vesting_schedule_type` is `CLIFF`, the vested percentage is a step function on completed service years. If the completed service years is greater than or equal to `cliff_years`, the vested percentage is 100.0; otherwise it is 0.0. The threshold uses greater-than-or-equal on the integer service-year count — a participant whose service is exactly `cliff_years` is fully vested, not partially vested.

**Graded variant.** When `vesting_schedule_type` is `GRADED`, the vested percentage is read from `graded_percentages` by index. The index is the smaller of the completed service-year count and 6, clamping participants with seven or more completed service years to position six of the array. The vested percentage is the integer at that position interpreted as a float (for example, an array entry of 60 produces a vested percentage of 60.0). Under this variant the vested percentage never reaches one hundred before position six unless an earlier array entry has already been set to 100.

**Vested balance.** The vested balance in cents is the participant's `total_account_balance_cents` multiplied by the vested percentage divided by one hundred, then rounded half up to a whole cent.

**Vesting snapshots.** Either a `PlanAdministrator`, a `ComplianceOfficer`, or the owning `Participant` may materialize a `VestingSnapshot` for a participant. The materialization runs the vested-percent calculation against the current plan state and appends an immutable row carrying `vesting_epoch` (set to the plan's `current_vesting_epoch` at materialization), `service_years_completed` (set to the floor-divided service-year count), `vested_pct` (set to the computed vested percentage stored to one decimal place), and `vested_balance_cents` (set to the rounded vested balance). Snapshots are append-only and never mutated after creation.

### 3.5. Plan Loans

A `Participant` requests a loan against their own participant record. The request payload supplies `requested_amount_cents` and `term_months`, where `term_months` must be a whole number in the closed range one through sixty; an out-of-range value is rejected with `ERR_LOAN_TERM_INVALID`. A successful request produces a `Loan` row in `REQUESTED` status with `outstanding_principal_cents` set provisionally to `requested_amount_cents` (it is not yet debited from the participant's balance).

The maximum loan amount the participant may borrow is the result of a three-step calculation. First, the system reads the participant's current vested balance, computed as `total_account_balance_cents` multiplied by the current vested percentage divided by one hundred and rounded half up. Second, it computes the IRS-style cap as the smaller of (a) the integer floor of the vested balance divided by two — that is, fifty percent of the vested balance — and (b) the absolute loan cap, which is fixed at $50,000 (that is, 5,000,000 cents). Third, it reduces that cap by the **highest outstanding principal observed on this participant's loans during the preceding 365 days**. To compute that highest-outstanding figure, the system walks every loan belonging to this participant whose `status` was `ACTIVE` at any time in the last 365 days — that is, every loan whose `origination_date` is on or after `PlanClock.current_date` minus 365 days, plus every loan with `status` of `ACTIVE` that has any `LoanRepayment` row whose `posted_on` is on or after `PlanClock.current_date` minus 365 days — and takes the maximum `outstanding_principal_cents` observed during that window. For currently `ACTIVE` loans the current `outstanding_principal_cents` is what counts; for loans that reached `SATISFIED` within the window the maximum outstanding observed during the window is what counts (equivalently, the original `approved_amount_cents` minus any payments made before the window started). If the participant has no qualifying loans, this figure is zero. The maximum loan amount is then the larger of zero and the IRS-style cap minus that highest-outstanding figure. The constant 365 governs both the origination-date check and the repayment-date check.

The loan-cap check is applied twice: once at the time the loan is requested, and again at the time it is approved. If `requested_amount_cents` exceeds the maximum loan amount at either check, the request is rejected with `ERR_LOAN_EXCEEDS_MAX`.

**One outstanding loan per participant.** A new loan request is rejected with `ERR_LOAN_ALREADY_OUTSTANDING` if the participant already has another `Loan` in `REQUESTED` or `ACTIVE` status. The same rejection applies at approval time when a sibling loan has reached `ACTIVE` first — this is the explicit serialization point described in §2.13 for two simultaneous approvals.

**Approval.** Approval is performed by a `PlanAdministrator` and transitions the loan from `REQUESTED` to `ACTIVE`. The preconditions are that the participant's `status` is either `ACTIVE` or `SUSPENDED`, that `requested_amount_cents` is less than or equal to the current max-loan amount, and that the participant has no other `Loan` in `REQUESTED` or `ACTIVE` (the one-outstanding rule re-evaluated). An attempt to approve a loan whose `status` is anything other than `REQUESTED` is rejected with `ERR_LOAN_NOT_REQUESTED`. On a successful approval, the system pins `approved_amount_cents` to `requested_amount_cents` exactly (the loan is either approved in full or rejected entirely), sets `origination_date` to the plan clock's current date, sets `next_due_date` to the origination date plus 30 days, and computes `monthly_payment_cents` as `approved_amount_cents` divided by `term_months` rounded half up to a whole cent. Because of rounding, the sum of `term_months` equal payments may differ from `approved_amount_cents` by up to a few cents; the **last** installment absorbs the rounding remainder so that the total of all payments equals `approved_amount_cents` exactly. The counter `payments_made` is initialized to zero.

**Rejection.** Rejection is also performed by a `PlanAdministrator` and transitions the loan from `REQUESTED` to `REJECTED`, which is terminal. Rejection has no preconditions beyond the state being `REQUESTED` (otherwise `ERR_LOAN_NOT_REQUESTED`) and produces no side effects.

**Repayment posting.** A `Participant` or a `PayrollProcessor` posts a repayment against an `ACTIVE` loan by supplying `payment_amount_cents`. The repayment produces an immutable `LoanRepayment` row whose owning loan is identified through `loan_id` (the row also carries its `plan_id` and `participant_id` for addressability), whose `principal_cents` equals `payment_amount_cents` (no interest split is tracked at the row level), whose `posted_on` is set to the plan clock's current date, and whose `status` is `POSTED`. The loan's `outstanding_principal_cents` is decremented by `payment_amount_cents`; if this would drive the value negative, the request is rejected with `ERR_LOAN_OVERPAYMENT` and no row is created. The loan's `next_due_date` is advanced by 30 days, and `payments_made` is incremented by one. When `outstanding_principal_cents` reaches exactly zero after this repayment, the loan transitions automatically from `ACTIVE` to `SATISFIED` (which is terminal) in the same commit.

**Default cascade.** A loan transitions automatically from `ACTIVE` to `DEFAULTED` during clock-advance whenever the loan's `next_due_date` plus 90 days is earlier than the new `current_date` and `outstanding_principal_cents` is greater than zero. The default cascade has two hops. The first hop applies a synthetic deemed-distribution debit: the participant's `total_account_balance_cents` is reduced by `outstanding_principal_cents`. The second hop marks the participant's vested snapshot as stale: `vesting_epoch_at_snapshot` is set to -1 so that the next read of the vested balance is forced to recompute regardless of the plan's current epoch. After both hops, the loan's `outstanding_principal_cents` is set to zero. `DEFAULTED` is terminal.

A list of loans is available to `PlanAdministrator`, `ComplianceOfficer`, and the owning `Participant`, and accepts an optional `status` query parameter for filtering.

### 3.6. Hardship Withdrawals

A `Participant` requests a hardship withdrawal against their own record by supplying `requested_amount_cents` and `hardship_reason_code`, where the reason code is one of `MEDICAL`, `EDUCATION`, `PRIMARY_RESIDENCE`, `FUNERAL`, or `EVICTION`. The resulting `HardshipWithdrawal` row is created in `REQUESTED` status. At the moment of creation, the system snapshots the participant's vested balance at the time — `vested_balance_cents_at_request`, computed as `total_account_balance_cents` multiplied by the current vested percentage divided by one hundred and rounded half up to a whole cent — and freezes that value on the row; it is immutable thereafter.

A `ComplianceOfficer` approves or denies a pending hardship request, transitioning it from `REQUESTED` to either `APPROVED` or `DENIED` (both terminal). An attempt to approve or deny a hardship whose `status` is anything other than `REQUESTED` is rejected with `ERR_HARDSHIP_NOT_REQUESTED`. Denial has no preconditions and no side effects beyond the state change.

Approval enforces three preconditions: the participant's `status` is `ACTIVE` or `SUSPENDED`; `vested_balance_cents_at_request` is greater than zero (otherwise `ERR_INSUFFICIENT_VESTED_BALANCE`); and the participant has no `Loan` in `REQUESTED` status (an outstanding loan request must be resolved before a hardship can be approved, otherwise `ERR_PARTICIPANT_NOT_IN_VALID_STATE`). Equivalently, the same insufficient-vested-balance code is also raised at the request endpoint when `requested_amount_cents` is not positive or when the snapshotted vested balance is zero. On approval, the three-hop cascade described in §2.8 fires: `approved_amount_cents` is pinned to the smaller of `requested_amount_cents` and `vested_balance_cents_at_request`, the participant's `total_account_balance_cents` is reduced by that approved amount, the participant transitions from `ACTIVE` to `SUSPENDED` (via the system-driven participant transition) with `deferral_suspended_until` set to the plan clock's current date plus 180 days, and any subsequent `ContributionRecord` post in the suspension window is rejected with `ERR_DEFERRAL_SUSPENDED`. A denial sets `approved_amount_cents` to zero and produces no side effects.

A list of hardship withdrawals is available to `PlanAdministrator`, `ComplianceOfficer`, and the owning `Participant`, and accepts an optional `status` query parameter.

### 3.7. Required Minimum Distributions

A `ComplianceOfficer` schedules a required minimum distribution for a participant by supplying `rmd_year`, the calendar year to which the distribution applies. The scheduling logic first computes the participant's attained age in that year as `rmd_year` minus the year component of `date_of_birth`. If the attained age is strictly less than the plan's `rmd_age`, the request is rejected with `ERR_RMD_NOT_YET_REQUIRED`. A request that would create a second `RMDSchedule` for the same (`participant_id`, `rmd_year`) pair is rejected with `ERR_DUPLICATE_RMD_YEAR`.

On a successful schedule, the system records `prior_year_end_balance_cents` as a snapshot of the participant's current `total_account_balance_cents` (this is the implementation's stand-in for the prior December 31 balance under plan-clock semantics, since the system has no independent year-end balance source). It then reads the `distribution_period_factor` for the attained age from the uniform lifetime table: age 73 maps to 26.5, age 74 to 25.5, age 75 to 24.6, age 76 to 23.7, age 77 to 22.9, age 78 to 22.0, age 79 to 21.1, age 80 to 20.2. The `required_amount_cents` is `prior_year_end_balance_cents` divided by `distribution_period_factor`, rounded half up to a whole cent.

The `due_date` follows a first-year exception. A first-year RMD is one where the attained age equals the plan's `rmd_age` and no prior `RMDSchedule` row exists for that participant. For a first-year RMD, the due date is April 1 of the year following `rmd_year` (formatted as `YYYY-04-01` with the year being `rmd_year + 1`). For every later-year RMD, the due date is December 31 of `rmd_year` (formatted as `YYYY-12-31`).

The newly created row's `status` is `SCHEDULED`, with `distributed_amount_cents` initialized to zero.

**Fulfillment.** A `ComplianceOfficer` fulfills a pending RMD by supplying `distributed_amount_cents` in the request body. Fulfillment requires that the schedule's `status` is `SCHEDULED` (otherwise `ERR_RMD_NOT_SCHEDULED`), that the supplied `distributed_amount_cents` is greater than or equal to the calculated `required_amount_cents` (otherwise `ERR_RMD_UNDERPAID`), and that `PlanClock.current_date` is less than or equal to `due_date` (otherwise `ERR_RMD_PAST_DUE`). On success, the schedule transitions from `SCHEDULED` to `FULFILLED` (terminal), the participant's `total_account_balance_cents` is reduced by `distributed_amount_cents`, and `distributed_amount_cents` is persisted on the schedule row.

**Missed cascades.** A `SCHEDULED` RMD transitions automatically to `MISSED` (terminal) under two distinct cascade paths. The first is the time-driven path during a clock-advance: whenever the new `current_date` is strictly greater than `due_date` and the row is still in `SCHEDULED`, the row is flipped to `MISSED`. The second is the termination-driven path: when a `PlanAdministrator` terminates an `ACTIVE` participant in the same request that the cascade fires, every `SCHEDULED` RMD row for that participant whose `due_date` is earlier than `PlanClock.current_date` is flipped to `MISSED`. Both cascades produce identical end-states on the row; the only difference is which trigger caused them.

A list of RMD schedules is available to `PlanAdministrator`, `ComplianceOfficer`, and the owning `Participant`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/plans` root. Operations that create a new resource — a `Plan`, a participant, a contribution record, a vesting snapshot, a loan, a loan repayment, a hardship withdrawal, or an RMD schedule — return `201 Created`. Operations that modify an existing resource — state transitions, deferral updates, clock advances, and vesting-epoch advances — return `200 OK`. Read operations return `200 OK`. Side effects, request bodies, and response bodies are documented in §3; this table summarizes the surface only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/plans` | Create a draft `Plan` | `PlanAdministrator` |
| GET    | `/plans` | List plans | `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor` |
| GET    | `/plans/{planId}` | Get a plan | `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor` |
| POST   | `/plans/{planId}/activate` | Transition plan from `DRAFT` to `ACTIVE`; create `PlanClock` | `PlanAdministrator` |
| POST   | `/plans/{planId}/freeze` | Transition plan from `ACTIVE` to `FROZEN`; suspend all participants | `PlanAdministrator` |
| POST   | `/plans/{planId}/advance-vesting-epoch` | Increment `current_vesting_epoch` by one | `PlanAdministrator` |
| POST   | `/plans/{planId}/_clock/advance` | Advance `PlanClock.current_date` to `new_date`; drive time-gated transitions | `PlanAdministrator` |
| POST   | `/plans/{planId}/participants` | Enroll a participant | `PlanAdministrator` |
| GET    | `/plans/{planId}/participants` | List participants (supports `status` filter) | `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor` |
| GET    | `/plans/{planId}/participants/{participantId}` | Get a participant (lazy vesting refresh) | `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor` |
| POST   | `/plans/{planId}/participants/{participantId}/activate` | Transition participant from `ENROLLED` to `ACTIVE` | `PayrollProcessor` |
| POST   | `/plans/{planId}/participants/{participantId}/terminate` | Transition participant from `ACTIVE` or `SUSPENDED` to `TERMINATED` | `PlanAdministrator` |
| PATCH  | `/plans/{planId}/participants/{participantId}/deferral` | Update `elected_deferral_pct` | `Participant`, `PayrollProcessor` |
| POST   | `/plans/{planId}/participants/{participantId}/contribution-records` | Post a pay-period contribution | `PayrollProcessor` |
| GET    | `/plans/{planId}/participants/{participantId}/contribution-records` | List a participant's contribution records (supports `year` filter) | `PlanAdministrator`, `ComplianceOfficer`, `PayrollProcessor`, `Participant` |
| POST   | `/plans/{planId}/participants/{participantId}/vesting-snapshots` | Materialize an immutable vested-balance snapshot | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| GET    | `/plans/{planId}/participants/{participantId}/vesting-snapshots` | List vesting snapshots | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| POST   | `/plans/{planId}/participants/{participantId}/loans` | Request a loan | `Participant` |
| GET    | `/plans/{planId}/participants/{participantId}/loans` | List participant loans (supports `status` filter) | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| GET    | `/plans/{planId}/participants/{participantId}/loans/{loanId}` | Get a loan | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| POST   | `/plans/{planId}/participants/{participantId}/loans/{loanId}/approve` | Transition loan from `REQUESTED` to `ACTIVE` | `PlanAdministrator` |
| POST   | `/plans/{planId}/participants/{participantId}/loans/{loanId}/reject` | Transition loan from `REQUESTED` to `REJECTED` | `PlanAdministrator` |
| POST   | `/plans/{planId}/participants/{participantId}/loans/{loanId}/repayments` | Post a loan repayment | `Participant`, `PayrollProcessor` |
| POST   | `/plans/{planId}/participants/{participantId}/hardship-withdrawals` | Request a hardship withdrawal | `Participant` |
| GET    | `/plans/{planId}/participants/{participantId}/hardship-withdrawals` | List hardship withdrawals (supports `status` filter) | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| POST   | `/plans/{planId}/participants/{participantId}/hardship-withdrawals/{withdrawalId}/approve` | Transition hardship from `REQUESTED` to `APPROVED` | `ComplianceOfficer` |
| POST   | `/plans/{planId}/participants/{participantId}/hardship-withdrawals/{withdrawalId}/deny` | Transition hardship from `REQUESTED` to `DENIED` | `ComplianceOfficer` |
| POST   | `/plans/{planId}/participants/{participantId}/rmd-schedules` | Create a `SCHEDULED` RMD row for `rmd_year` | `ComplianceOfficer` |
| GET    | `/plans/{planId}/participants/{participantId}/rmd-schedules` | List RMD schedules | `PlanAdministrator`, `ComplianceOfficer`, `Participant` |
| POST   | `/plans/{planId}/participants/{participantId}/rmd-schedules/{scheduleId}/fulfill` | Transition RMD from `SCHEDULED` to `FULFILLED`; debit balance | `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_HARDSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_RMD_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_FROZEN` | 409 Conflict |
| `ERR_FREEZE_PRECONDITION_VIOLATED` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_IN_VALID_STATE` | 409 Conflict |
| `ERR_LOAN_NOT_REQUESTED` | 409 Conflict |
| `ERR_HARDSHIP_NOT_REQUESTED` | 409 Conflict |
| `ERR_RMD_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DUPLICATE_PAY_PERIOD` | 409 Conflict |
| `ERR_DEFERRAL_SUSPENDED` | 409 Conflict |
| `ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOAN_ALREADY_OUTSTANDING` | 409 Conflict |
| `ERR_LOAN_EXCEEDS_MAX` | 422 Unprocessable Entity |
| `ERR_LOAN_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_LOAN_TERM_INVALID` | 400 Bad Request |
| `ERR_INSUFFICIENT_VESTED_BALANCE` | 422 Unprocessable Entity |
| `ERR_RMD_NOT_YET_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RMD_YEAR` | 409 Conflict |
| `ERR_RMD_UNDERPAID` | 422 Unprocessable Entity |
| `ERR_RMD_PAST_DUE` | 422 Unprocessable Entity |
| `ERR_STALE_DATA` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PLAN_CONFIG` | 400 Bad Request |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 Unprocessable Entity |
