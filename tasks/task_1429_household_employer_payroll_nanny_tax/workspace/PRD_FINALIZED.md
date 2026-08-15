# Household Employer Payroll API — Product Requirements Document

## 1. Introduction

Household employers — families who hire nannies, housekeepers, caregivers, and other domestic staff — occupy an awkward corner of the U.S. payroll landscape. They are employers in the eyes of the IRS and their state's labor department, yet they lack the payroll departments, tax counsel, and HR infrastructure that even a ten-person business takes for granted. The result is predictable: families misclassify employees as independent contractors, miss new-hire reporting windows, underpay overtime for live-in staff (where state rules diverge from the familiar 40-hour weekly trigger), fall behind on quarterly estimated deposits, and arrive in March without the W-2s and Schedule H figures their accountants demand.

This document specifies the Household Employer Payroll & Nanny Tax Service API, a system in the spirit of HomePay that walks a household from onboarding through year-end tax reporting. The service maintains per-state labor rule packs, governs the employee-versus-contractor determination, enforces the pay-frequency floor each state imposes, calculates gross-to-net paychecks with hourly, daily, and fluctuating-workweek overtime variants, tracks FICA coverage thresholds that flip retroactively mid-year, computes safe-harbor estimated deposit requirements, manages workers' compensation posture, and produces the year-end W-2 / Schedule H package.

Two architectural decisions shape every workflow that follows. First, **all money is integer cents** and **all durations are integer minutes** — there is no floating-point currency anywhere in the system, and rounding rules are pinned per calculation. Second, **the server maintains a logical clock** distinct from wall time: filings, deposits, policy sweeps, and new-hire reporting deadlines are all evaluated against this logical clock, never against the host's wall clock. The API is mounted under `/household-payroll`.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. The role header must be one of exactly four role names, spelled as follows:

- `PayrollAdmin`
- `ComplianceOfficer`
- `HouseholdClient`
- `Worker`

Requests missing either header, or carrying a role not in this list, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted on the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles divide into two identity kinds.

When `X-User-Role` is `PayrollAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The same is true when `X-User-Role` is `ComplianceOfficer`: the id is opaque. The server does record such an id where a transition demands it (for example, `prepared_by_user_id` on `QuarterlyFiling`, which captures the calling `PayrollAdmin`'s id so that the segregation-of-duties check can later compare it to the submitter's id), but it never compares an opaque id to any entity's `id`.

When `X-User-Role` is `HouseholdClient`, `X-User-ID` is the `id` of the acting `HouseholdEmployer`; ownership checks on any resource that references a `HouseholdEmployer` compare the resource's foreign-key field (typically `employer_id` reached through the URL path or a parent worker) to `X-User-ID`. When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `DomesticWorker`; ownership checks on any resource that references a `DomesticWorker` (timesheets, leave requests, the worker's own paychecks) compare the resource's `worker_id` or the path's worker identifier to `X-User-ID`. A mismatch on either entity-backed role yields `ERR_FORBIDDEN` (HTTP 403).

The segregation-of-duties rule deserves explicit statement: the `X-User-ID` that prepares a quarterly filing may not be the `X-User-ID` that submits it. An attempt to submit with the same id is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This rule operates purely on opaque id comparison; the two roles involved are `PayrollAdmin` (prepare) and `ComplianceOfficer` (submit).

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

All list endpoints accept two query parameters, `limit` and `offset`. The default `limit` is **10**, with a minimum of **1** and a maximum of **100**; the default `offset` is **0**. List responses order their results by `created_at` ascending, oldest first. The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when further results exist beyond the current page.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` formatted as a bare UUID — no type prefix, no namespace decoration. All entities except `StateRulePack` and `TaxDeposit` also carry `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that increments by exactly 1 on every mutation of the resource. `StateRulePack` and `TaxDeposit` are the two exceptions: they carry `id` and `created_at` only — `updated_at` and `version` are absent on both, because neither entity is ever mutated after creation and neither participates in optimistic concurrency control.

### 2.5. The Logical Clock and Date Discipline

The server keeps a logical clock that determines "today" for every time-aware rule in the system: new-hire reporting deadlines, filing quarter closures, deposit due dates, policy coverage windows, and year attribution of wages. The logical clock's default value, before any client has set it, is exactly **2026-08-01T00:00:00Z** — it never silently falls back to wall-clock time. A privileged `PayrollAdmin` capability advances the clock to a supplied `to_iso8601` instant; each such advance triggers the policy sweep that moves `BOUND` policies to `ACTIVE` once their `coverage_start` is reached and moves `ACTIVE` policies to `EXPIRED` once their `coverage_end` has passed, recomputing `compliance_posture` on every affected employer.

Date intervals come in two shapes, and the shape is part of the contract. **Half-open intervals** — used by timesheet periods and pay-run periods — include `period_start` and exclude `period_end`, written `[period_start, period_end)`. **Closed intervals** — used by leave requests and workers' compensation coverage windows — include both `start_date` and `end_date` (or both `coverage_start` and `coverage_end`). Adjacent half-open intervals (one's `period_end` equal to the next's `period_start`) never overlap; back-to-back closed intervals (one's `end_date` one day before the next's `start_date`) never overlap either. A malformed interval — `period_end` not after `period_start`, or `end_date` before `start_date` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Money, Minutes, and Rounding

All currency amounts are integer cents. All durations are integer minutes. Whenever a calculation must round, the rule is **round half-up** to the precision the specific calculation names: cents for monetary lines, exactly four decimal places for the fluctuating-workweek effective rate, integer minutes for leave accrual. The rounding point inside each formula is pinned — for withholding lines, every line is rounded half-up to cents **first** and only then summed to compute net pay; summing exact unrounded values and rounding once at the end is forbidden because it yields different cents. Overtime and double-time multipliers are exact ratios: 1.5x for overtime and 2.0x for double time.

A critical divisibility rule is enforced at agreement creation: `hourly_rate_cents` must be divisible by 60 with no remainder, so that the per-minute straight-time rate is always an exact integer number of cents. A violation is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control against a parent entity's `version`.

Creating a `StateRegistration` for an employer requires the request to carry `expected_employer_version`, set to the `version` the client last observed on the parent `HouseholdEmployer`. The server compares the supplied value to the employer's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from building a registration on a stale view of the employer (for example, after another registration's activation has flipped the employer's `status` and recomputed its posture).

Creating an `EmploymentAgreement` for a worker requires the request to carry `expected_worker_version`, set to the `version` the client last observed on the parent `DomesticWorker`. Because agreement creation supersedes the worker's current `ACTIVE` agreement, a mismatch against the worker's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — the supersede target may itself have changed since the client last read the worker.

No other endpoint takes an expected-version field. Successful creation under either rule increments the parent entity's `version` by 1 as a side effect.

### 2.8. Validation Ordering Across the Pipeline

Every endpoint applies the same validation pipeline, and the order in which checks fire determines which error a client sees when several problems coexist. The pipeline evaluates, in this exact order:

1. **Authentication** — both headers present and the role recognized; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted on the endpoint, and for entity-backed roles the `X-User-ID` matches the owning employer or worker; failure yields `ERR_FORBIDDEN` (or `ERR_SEGREGATION_OF_DUTIES` on the filing-submit path, which is a per-endpoint variant of the same authorization family).
3. **Existence** — path identifiers resolve left-to-right: the employer must resolve before the worker nested beneath it, the worker before the timesheet, the pay run before the paycheck, and so on through registrations, filings, policies, deposits, leave requests, and year-end packages. The first unresolved segment yields `ERR_NOT_FOUND`.
4. **Request shape** — required fields present, types correct, enum members valid, ISO dates well-formed and ordered, and `hourly_rate_cents` divisible by 60; failure yields `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency** — on the two endpoints that take an expected-version field, the version comparison runs here, before any state-machine evaluation; failure yields `ERR_STALE_VERSION`.
6. **State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`.
7. **Business safety** — compliance posture and workers' compensation coverage gates on pay-run finalize; failures yield `ERR_EMPLOYER_RESTRICTED` or `ERR_WORKERS_COMP_REQUIRED` respectively.
8. **Business temporal** — overlap checks on timesheets, leave requests, and pay runs; the new-hire reporting window at worker activation; the quarter-closure rule on filing prepare; the not-in-the-future rule on deposit `remitted_on`. Failures yield `ERR_TIMESHEET_OVERLAP`, `ERR_LEAVE_OVERLAP`, `ERR_PAYRUN_OVERLAP`, `ERR_NEW_HIRE_REPORT_LATE`, `ERR_QUARTER_NOT_CLOSED`, or `ERR_INVALID_REQUEST` as appropriate.
9. **Business referential** — referenced `StateRulePack` must exist (`ERR_STATE_RULES_MISSING`), covering `ACTIVE` agreement (`ERR_NO_ACTIVE_AGREEMENT`), required registrations active (`ERR_REGISTRATION_INACTIVE`), four accepted filings at year-end (`ERR_FILINGS_INCOMPLETE`).
10. **Business constraint** — pay-frequency floors, period-span matching, contractor-not-payable, minimum wage, and the various duplicate/uniqueness rules; failures yield `ERR_PAY_FREQUENCY_NONCOMPLIANT`, `ERR_PERIOD_LENGTH_MISMATCH`, `ERR_CONTRACTOR_NOT_PAYABLE`, `ERR_BELOW_MIN_WAGE`, or the relevant duplicate error.
11. **Business fiscal** — leave balance sufficiency, deposit amount against the safe-harbor requirement, year-end SSN completeness; failures yield `ERR_INSUFFICIENT_LEAVE_BALANCE`, `ERR_DEPOSIT_BELOW_REQUIRED`, or `ERR_MISSING_SSN`.

### 2.9. The Employer Compliance Posture

Every `HouseholdEmployer` carries a computed `compliance_posture` field with three values: `CLEAR`, `ATTENTION`, or `RESTRICTED`. The posture is recomputed fresh on every employer read and after every mutation anywhere in the employer's subgraph — worker activations and terminations, timesheet approvals, pay-run events, policy binds and lapses, deposit creation, filing acceptances and rejections, and clock-driven policy sweeps.

The posture is `RESTRICTED` when any `ACTIVE` worker's work-state rule pack has `workers_comp_required` set to true and no `WorkersCompPolicy` in `BOUND` or `ACTIVE` status has a `[coverage_start, coverage_end]` window that covers the logical-clock current date. Otherwise, the posture is `ATTENTION` when any `TaxDeposit` of the employer has `late_days` greater than 0, or any `QuarterlyFiling` of the employer is in `REJECTED` status. Otherwise the posture is `CLEAR`. A `RESTRICTED` posture blocks pay-run finalization outright with `ERR_EMPLOYER_RESTRICTED` — the system will not issue wages while a mandated workers' compensation obligation is uncovered.

### 2.10. Status Codes and Hierarchy Traversal

New resources are returned with HTTP **201**; modifications to existing resources, including all state transitions, are returned with HTTP **200**. Nested URLs are validated strictly left-to-right: `/household-payroll/employers/{eid}/workers/{wid}` requires the employer identified by `{eid}` to exist first, then the worker identified by `{wid}` to exist and belong to that employer; the first segment that fails to resolve yields `ERR_NOT_FOUND` and no further segments are examined.

---

## 3. Business Logic & Workflows

### 3.1. Configuring the Jurisdiction: State Rule Packs

Before any household can be onboarded, a `PayrollAdmin` must seed the relevant labor law via a state rule pack. Each pack is created for exactly one `state_code`, unique across the system — a duplicate create is rejected with `ERR_DUPLICATE_RULE_PACK` (HTTP 409). The pack captures the state's minimum pay frequency floor `min_pay_frequency` (one of `WEEKLY`, `BIWEEKLY`, `SEMIMONTHLY`, `MONTHLY`), the overtime thresholds `weekly_ot_threshold_minutes` (typically 2400, the 40-hour weekly trigger), `daily_ot_threshold_minutes` (for example 480 for an 8-hour daily trigger; 0 disables daily overtime), and `daily_dt_threshold_minutes` (for example 720 for a 12-hour double-time trigger; 0 disables double time). Live-in eligibility flags `live_in_weekly_ot_eligible` and `live_in_daily_ot_eligible` govern whether `LIVE_IN` workers earn weekly overtime or daily overtime/double time at all in that state — many states exempt live-in domestic staff from one or both.

The pack also pins `min_wage_cents` (the state minimum hourly wage in cents), `sit_rate` (the state income-tax withholding rate as a decimal, 0 in no-income-tax states), `suta_rate` and `suta_wage_base_cents` (the employer-paid state unemployment rate and its per-worker annual wage base cap in cents), `workers_comp_required` (whether the state mandates coverage for household employers), `new_hire_report_days` (the statutory window from `hire_date` within which the new-hire report must be filed), and `pay_stub_required` (whether an itemized stub must be delivered every payday).

Rule packs may be listed with an optional `state_code` filter, paginated via `limit` and `offset`. Because packs are immutable configuration, the entity carries no `version` field and no `updated_at`.

### 3.2. Onboarding the Household Employer

A `PayrollAdmin` onboards a household by supplying `legal_name`, `primary_state_code`, `fein`, `pay_frequency`, and optionally `prior_year_schedule_h_cents`. The primary state must already have a rule pack — otherwise the create is rejected with `ERR_STATE_RULES_MISSING` (HTTP 422). The `fein` is the nine-digit federal employer identification number. The `pay_frequency` must be at least as frequent as the primary state's `min_pay_frequency` — the ordering, from most to least frequent, is `WEEKLY`, then `BIWEEKLY`, then `SEMIMONTHLY`, then `MONTHLY`; choosing a frequency less frequent than the floor is rejected with `ERR_PAY_FREQUENCY_NONCOMPLIANT` (HTTP 422). `prior_year_schedule_h_cents` defaults to 0 when omitted and feeds the safe-harbor leg of the estimated-payment calculation.

A new employer is born with `status` set to `ONBOARDING` and `compliance_posture` initialized to `CLEAR`. The employer remains in `ONBOARDING` until the system observes its first `StateRegistration` reach `ACTIVE`, at which point the employer automatically transitions `ONBOARDING → ACTIVE` and its `version` increments by 1. A `ComplianceOfficer` may suspend an `ACTIVE` employer — a transition to `SUSPENDED` that blocks pay-run creation and finalization for the duration. Reinstatement from `SUSPENDED` back to `ACTIVE` is also a `ComplianceOfficer` action, but it is gated: reinstatement fails with `ERR_REGISTRATION_INACTIVE` (HTTP 422) if any `StateRegistration` for the employer's primary state remains in a non-`ACTIVE` status. Either action against an employer in the wrong from-state is rejected with `ERR_INVALID_STATE` (HTTP 409). Reinstatement recomputes the employer's `compliance_posture`.

### 3.3. Registering with State Agencies

Each employer must register with three categories of state agency per state in which it employs workers: `SIT_WITHHOLDING`, `SUTA`, and `NEW_HIRE_DIRECTORY`. A `PayrollAdmin` opens a registration against an employer by supplying `state_code` and `agency` together with the OCC field `expected_employer_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A duplicate registration — one for the same (employer, `state_code`, `agency`) triple that is not in a terminal state — is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP 409).

A new registration is born `DRAFT`. A `PayrollAdmin` then submits it — stamping `submitted_at` with the logical clock's current instant — transitioning it `DRAFT → SUBMITTED`. Activation moves it `SUBMITTED → ACTIVE` and captures `agency_account_number` from the request body; until activation the account number is null. Activation also fires two cascading effects: the employer's `compliance_posture` is recomputed, and if this is the employer's first registration to reach `ACTIVE`, the employer's `status` flips `ONBOARDING → ACTIVE` and its `version` increments by 1. Registrations may be listed per employer with optional `state_code` and `status` filters.

Registration gating reappears downstream in two places. Activating a worker requires the employer to hold an `ACTIVE` registration with `agency` equal to `NEW_HIRE_DIRECTORY` for the worker's `work_state_code`. Finalizing a pay run requires `ACTIVE` registrations in both `SIT_WITHHOLDING` and `SUTA` for every member worker's work state. Either failure surfaces `ERR_REGISTRATION_INACTIVE` (HTTP 422).

### 3.4. Bringing a Worker On Board: Classification, Agreements, Activation

A `HouseholdClient` adds a domestic worker to its own household by supplying `full_name`, optionally `ssn`, `work_state_code`, `hire_date`, and `work_arrangement` (`LIVE_IN` or `LIVE_OUT`). The work state must have a rule pack; otherwise the create is rejected with `ERR_STATE_RULES_MISSING`. A new worker starts with `status` set to `ONBOARDING` and `classification` set to `UNDETERMINED`. The `ssn` may be deferred — it is not required at create time — but every worker who has an `ISSUED` paycheck in the reporting year must have a non-null `ssn` before the year-end package can be finalized.

**Classification.** A `HouseholdClient` runs the employee-versus-contractor questionnaire by submitting `classification_answers`, a list of `{question_key, answer}` pairs retained verbatim on the worker for audit. The determination is a deterministic four-question score. One point is awarded for each of the following answers: `controls_schedule` answered `WORKER`; `supplies_own_tools` answered `WORKER`; `hires_own_substitutes` answered `ALLOWED`; `paid_by` answered `PROJECT_NOT_HOURS`. All four question keys are required — a missing key is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A score of at least 3 classifies the worker as `CONTRACTOR`; otherwise the worker is `EMPLOYEE`. A successful classify moves the worker `ONBOARDING → CLASSIFIED`; re-running the questionnaire on an already-`CLASSIFIED` worker is a self-loop that overwrites `classification` and replaces `classification_answers`. Classifying a worker not in `ONBOARDING` or `CLASSIFIED` is rejected with `ERR_INVALID_STATE`.

**Agreements.** Before a worker can be activated, an `ACTIVE` `EmploymentAgreement` covering `hire_date` must exist. A `HouseholdClient` creates an agreement by supplying `hourly_rate_cents`, `pay_method`, `effective_from`, and the OCC field `expected_worker_version`; `guaranteed_minutes_per_week` and `fit_withholding_cents_per_period` are optional and default to 0. The `hourly_rate_cents` must be at least the work-state pack's `min_wage_cents` (otherwise `ERR_BELOW_MIN_WAGE`, HTTP 422) and must divide evenly by 60 (otherwise `ERR_INVALID_REQUEST`). The `pay_method` is either `HOURLY` or `GUARANTEED_SALARY_FWW` — the fluctuating-workweek variant under which the weekly guarantee covers all straight-time minutes and overtime is paid as a 0.5x premium on the derived effective rate. Creating an agreement automatically supersedes the worker's prior `ACTIVE` agreement, if one exists: the prior agreement's `effective_to` is set to the new agreement's `effective_from` minus one day, its `superseded_by_id` points at the new agreement, and its `status` becomes `SUPERSEDED`. A new agreement's `effective_to` is null (open-ended) until a future agreement supersedes it. The parent's `version` increments by 1 on creation. Agreements are listed per worker with an optional `status` filter; a separate read exposes the (zero-or-one-element) list of agreements a given agreement superseded.

**Activation.** Activation moves the worker `CLASSIFIED → ACTIVE` and is performed by the `HouseholdClient` supplying `new_hire_report_date`. Four preconditions are evaluated in pipeline order. The worker must be in `CLASSIFIED` status (else `ERR_INVALID_STATE`). The classification must be `EMPLOYEE` — a `CONTRACTOR` may not be put on payroll (else `ERR_CONTRACTOR_NOT_PAYABLE`, HTTP 422). An `ACTIVE` agreement covering `hire_date` must exist (else `ERR_NO_ACTIVE_AGREEMENT`, HTTP 422). The employer must hold an `ACTIVE` `NEW_HIRE_DIRECTORY` registration for the worker's `work_state_code` (else `ERR_REGISTRATION_INACTIVE`). Finally, the new-hire reporting window is enforced: `new_hire_report_date` must fall on or after `hire_date`, must fall on or before `hire_date` plus the pack's `new_hire_report_days`, and must not lie after the logical-clock current date; a violation yields `ERR_NEW_HIRE_REPORT_LATE` (HTTP 422).

**Termination.** A `HouseholdClient` terminates an `ACTIVE` worker. The system stamps `termination_date` with the logical-clock current date, transitions every `ACTIVE` agreement for the worker to `TERMINATED`, and leaves the worker's `DRAFT` timesheets editable and `SUBMITTED` timesheets still approvable. Terminating a worker not in `ACTIVE` is rejected with `ERR_INVALID_STATE`.

### 3.5. Timesheets and the Approval Cascade

A `Worker` records time by creating a `Timesheet` against their own worker id, supplying `period_start`, `period_end`, and a list of per-day `entries` each carrying `work_date` and `worked_minutes`. The period is a half-open interval `[period_start, period_end)`. Each entry's `work_date` must lie inside that interval and must be unique within the timesheet. The timesheet's `total_worked_minutes` is computed as the sum of its entries' `worked_minutes`. Creating a timesheet requires the worker's `status` to be `CLASSIFIED` or `ACTIVE`, and requires an `ACTIVE` agreement whose `[effective_from, effective_to]` covers the timesheet's period — otherwise `ERR_NO_ACTIVE_AGREEMENT`. The new timesheet's half-open interval must not overlap any other non-`LOCKED` timesheet of the same worker; adjacency (one's `period_end` equal to another's `period_start`) is allowed, but a true overlap is rejected with `ERR_TIMESHEET_OVERLAP` (HTTP 409).

A new timesheet is born `DRAFT`. The `Worker` submits it, transitioning `DRAFT → SUBMITTED` and stamping `submitted_at` with the logical clock's current instant; submission requires `total_worked_minutes` to be strictly greater than 0 (otherwise `ERR_INVALID_REQUEST`). Each re-submission after a rejection refreshes `submitted_at` to the new logical-clock instant. A `HouseholdClient` may reject a `SUBMITTED` timesheet, returning it to `DRAFT` with no other side effects; or may approve it.

Approval is the highest-fan-out event in the timesheet lifecycle, transitioning `SUBMITTED → APPROVED`. Approval requires the worker to be in `ACTIVE` status (otherwise `ERR_INVALID_STATE`) and requires that no `FINALIZED` `PayRun` covers the timesheet's period for this worker (also `ERR_INVALID_STATE`). When approval succeeds, three cascades fire in the same request. First, the worker's `ytd_approved_minutes` increases by `total_worked_minutes` and `accrued_leave_minutes` is recomputed (see §3.7). Second, every `PayRun` in `CALCULATED` status whose `[period_start, period_end)` covers this timesheet's period flips its `recalc_status` from `CURRENT` to `STALE`. Third, each such `STALE` pay run's member paychecks that are still in `CALCULATED` status have `basis_stale` set to true. The stale markers are the serialization point that prevents a pay run from being finalized against timesheet data the run has not absorbed.

A timesheet in `APPROVED` moves to `LOCKED` automatically when a pay run's calculate step runs over a period that exactly covers the timesheet's period; the timesheet's `pay_run_id` is then set to the calculating pay run's `id`. `LOCKED` is terminal.

### 3.6. Pay Runs, Gross Pay Variants, and Finalization

A `PayrollAdmin` opens a pay run for an employer by supplying `period_start`, `period_end`, and `pay_date`. The employer's `status` must be `ACTIVE` — creating a pay run against a `SUSPENDED` employer is rejected with `ERR_INVALID_STATE`. The half-open period must not overlap any other non-terminal pay run of the same employer (otherwise `ERR_PAYRUN_OVERLAP`, HTTP 409), and the period's span must match the employer's `pay_frequency` exactly: 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, the `[1, 16)` or `[16, 1st-of-next-month)` half-months for `SEMIMONTHLY`, or a calendar month for `MONTHLY`. A mismatched span is rejected with `ERR_PERIOD_LENGTH_MISMATCH` (HTTP 422). A new pay run is born `OPEN` with `recalc_status` set to `CURRENT`.

**Calculation.** A `PayrollAdmin` runs calculation against an `OPEN` pay run, or against a `CALCULATED` pay run whose `recalc_status` is `STALE`; any other from-state is rejected with `ERR_INVALID_STATE`. Calculation creates one `Paycheck` (status `CALCULATED`) per worker whose `status` is `ACTIVE` on `period_start` and who has an `ACTIVE` agreement covering the period; paychecks are created in worker `created_at` ascending order — never by worker `id`. Any `APPROVED` timesheet that exactly covers the pay-run period is transitioned to `LOCKED` and linked via `pay_run_id`. After computation, `recalc_status` is set to `CURRENT` and the pay run's `total_gross_cents`, `total_net_cents`, and `total_employer_tax_cents` are recomputed as sums over member paychecks whose `status` is not `VOIDED`. Re-calculation of a `STALE` run recomputes member paychecks from the currently approved timesheets, clears `basis_stale` on each, and resets `recalc_status` to `CURRENT`.

Each paycheck's `basis` is determined by whether an `APPROVED`-or-`LOCKED` timesheet exactly covers the pay-run period for the worker: `TIMESHEET` when one does, `GUARANTEE_FALLBACK` when none does. The paycheck copies `pay_method` from the governing agreement. The provisional figure `provisional_gross_cents` is always computed on the guarantee basis — guaranteed minutes for the period multiplied by the straight-time per-minute rate, with no overtime and no timesheet data — regardless of which `basis` the paycheck ultimately uses.

**Hourly gross with overtime extraction.** For paychecks whose `pay_method` is `HOURLY`, gross is computed by a pinned three-stage extraction. The per-minute straight-time rate is `hourly_rate_cents` divided by 60 — an integer, guaranteed by the agreement-create validation. First, **daily extraction**: for each timesheet entry, when the pack's `daily_dt_threshold_minutes` is greater than 0, the double-time portion is the number of worked minutes above that threshold, floored at zero; when `daily_ot_threshold_minutes` is greater than 0, the daily-overtime portion is the portion of worked minutes between the daily OT threshold and the daily DT threshold (treating the DT threshold as unbounded when it is 0); the remainder of the entry's minutes accumulate into regular time. Second, **weekly extraction**: the weekly overtime portion is the number of regular-time minutes remaining after daily extraction that exceeds the pack's `weekly_ot_threshold_minutes`, floored at zero; those minutes are moved from regular into overtime. Third, **guarantee top-up**: the period's guaranteed minutes equal `guaranteed_minutes_per_week` multiplied by the number of weeks in the period (1 for `WEEKLY`, 2 for `BIWEEKLY`, 2 for `SEMIMONTHLY`, 4 for `MONTHLY`); `guarantee_top_up_minutes` is the excess of that guarantee over total worked minutes, floored at zero, paid at straight time and excluded from overtime bases. The straight-time minutes that survive both extraction stages are stored as `regular_minutes`. Final gross for a `TIMESHEET`-basis paycheck is the per-minute rate multiplied by the sum of `regular_minutes` and `guarantee_top_up_minutes`, plus the 1.5x per-minute rate — itself rounded half-up to cents per minute **before** being multiplied by the overtime minutes — multiplied by `overtime_minutes`, plus twice the per-minute rate multiplied by `double_minutes`. On `GUARANTEE_FALLBACK` basis, `regular_minutes` are the period's guaranteed minutes, overtime and double minutes are zero, and gross is the per-minute rate times `regular_minutes`.

**Live-in exemption variant.** The daily and weekly extraction stages are skipped entirely for a worker whose `work_arrangement` is `LIVE_IN` unless the corresponding pack flag — `live_in_daily_ot_eligible` for daily extraction, `live_in_weekly_ot_eligible` for weekly extraction — is true. The same timesheet therefore yields a different gross for a `LIVE_IN` worker versus a `LIVE_OUT` worker in states that exempt live-in staff.

**Fluctuating-workweek gross.** For paychecks whose `pay_method` is `GUARANTEED_SALARY_FWW`, the computation follows a pinned four-step order (the dependency looks circular but is not — the order is fixed and never iterated). First, total worked minutes are taken from the covering timesheet when the basis is `TIMESHEET`, or from the period's guaranteed minutes when the basis is `GUARANTEE_FALLBACK`. Second, overtime minutes are the portion of total worked minutes above the pack's `weekly_ot_threshold_minutes`, floored at zero, when overtime is eligible for the worker's arrangement — daily thresholds never apply under FWW — and zero otherwise. Third, `fww_effective_rate_cents_per_minute` is the weekly guarantee pay (`guaranteed_minutes_per_week` times the per-minute straight rate) multiplied by the number of weeks in the period, divided by total worked minutes, and rounded half-up to exactly four decimal places. Fourth, the premium is half of `fww_effective_rate_cents_per_minute` multiplied by overtime minutes, rounded half-up to cents. Final gross is the weekly guarantee pay times weeks-in-period plus the premium; `provisional_gross_cents` is the weekly guarantee pay times weeks-in-period with no premium.

**Withholding and net.** After gross, each paycheck's `withholding_lines` and `employer_tax_lines` are computed. Every line is rounded half-up to integer cents **before** any summation, and `net_pay_cents` is `gross_cents` minus the sum of the rounded withholding lines. Lines whose computed amount is 0 are omitted from the lines arrays. FICA coverage at calculate time is evaluated on the projected year-to-date figure: the worker is treated as covered when `cash_wages_ytd_cents` plus the gross of this run's already-calculated paychecks for the same worker plus this paycheck's `gross_cents` is at least 280000 cents (the FICA coverage threshold — $2,800 of cash wages in the calendar year). When covered, the FICA base of this check includes the retroactive catch-up: this check's `gross_cents` plus the gross of earlier `ISSUED` checks this year whose FICA base was zero at the time they were issued. Within coverage, Social Security is further capped: the SS base is the lesser of `gross_cents` and the room remaining under the SS wage base of 17610000 cents ($176,100) after `ss_wages_paid_ytd_cents`, with the catch-up portion included in that base. The employee lines are: `SS_EE` at 6.2% of the SS base; `MEDICARE_EE` at 1.45% of all FICA wages including catch-up, uncapped; `ADDL_MEDICARE_EE` at 0.9% applied only to the portion of FICA wages that pushes year-to-date FICA wages above 20000000 cents ($200,000); `SIT_EE` at the pack's `sit_rate` times `gross_cents`; and `FIT_EE` as the flat `fit_withholding_cents_per_period` from the agreement. Employer lines, not deducted from net, are `SS_ER` at 6.2% of the same SS base, `MEDICARE_ER` at 1.45% of the FICA base, `FUTA_ER` at 0.6% of the FUTA base when FUTA applies year-to-date, and `SUTA_ER` at the pack's `suta_rate` times the SUTA base. The provisional variant computes these lines over `provisional_gross_cents`; the final variant computes them over `gross_cents`, so identical inputs produce different `net_pay_cents` whenever worked minutes diverge from the guarantee.

**Finalization.** A `PayrollAdmin` finalizes a `CALCULATED` pay run. The preconditions fire in pipeline order: the run must be in `CALCULATED` (else `ERR_INVALID_STATE`); `recalc_status` must be `CURRENT` (else `ERR_PAYRUN_STALE`, HTTP 409); the employer's `status` must be `ACTIVE` (else `ERR_INVALID_STATE`); the employer's `compliance_posture` must not be `RESTRICTED` (else `ERR_EMPLOYER_RESTRICTED`, HTTP 409); for every member worker whose work-state pack has `workers_comp_required` true, a `WorkersCompPolicy` in `BOUND` or `ACTIVE` must cover `pay_date` (else `ERR_WORKERS_COMP_REQUIRED`, HTTP 422); and `ACTIVE` `SIT_WITHHOLDING` and `SUTA` registrations must exist for every member worker's work state (else `ERR_REGISTRATION_INACTIVE`). On success, member paychecks transition `CALCULATED → ISSUED`; `deposit_status` moves `PENDING → SENT`; `stub_status` moves `PENDING → DELIVERED`, or `PENDING → NOT_REQUIRED` when the work-state pack's `pay_stub_required` is false. Worker YTD fields advance per the FICA and FUTA calculations below; `TaxLiabilityAccount` rows for the year of `pay_date` are lazily created in the fixed order `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER` — all five, even when a line amount is 0 — and their `accrued_cents` incremented by the paycheck's line amounts. The employer's `compliance_posture` is recomputed.

**Voiding.** A `PayrollAdmin` may void an `ISSUED` paycheck whose parent pay run is `FINALIZED`. (Voiding a `CALCULATED` paycheck is not supported — recalculate the run instead.) Voiding transitions the paycheck `ISSUED → VOIDED`; `deposit_status` moves to `REVERSAL_PENDING` when it was `SENT`. The parent pay run's totals are recomputed over non-`VOIDED` paychecks (the compensating invariant is that `total_net_cents` equals the sum of non-`VOIDED` `net_pay_cents`). The worker's `cash_wages_ytd_cents`, `ss_wages_paid_ytd_cents`, and `futa_wages_ytd_cents` are decremented by this paycheck's contribution, and `fica_covered` is re-evaluated; if coverage is lost, accrued FICA lines for the year's checks are reversed through `TaxLiabilityAccount`. Account `accrued_cents` are decremented per line, `balance_cents` recomputed, and the employer's `compliance_posture` recomputed.

### 3.7. Paid Leave: Accrual, Request, Approval, Cancellation

Paid leave accrues against approved time. On every timesheet approval, the worker's `ytd_approved_minutes` — the sum of `total_worked_minutes` over `APPROVED` or `LOCKED` timesheets in the logical clock's calendar year — is incremented, and `accrued_leave_minutes` is recomputed as the smaller of: the integer floor of `ytd_approved_minutes` divided by 30 (one hour of leave earned per 30 hours worked, so the 29th worked minute of a 30-minute unit earns nothing), and the annual cap of 2400 minutes (40 hours). `used_leave_minutes` is the sum of `requested_minutes` over `APPROVED` leave requests, and `available_leave_minutes` is the difference.

A `Worker` requests leave against their own worker id, supplying `start_date`, `end_date` (a closed interval, both endpoints inclusive), and `requested_minutes`, which must be strictly greater than 0. The request requires the worker to be in `ACTIVE` status, and `requested_minutes` must not exceed `available_leave_minutes` — otherwise `ERR_INSUFFICIENT_LEAVE_BALANCE` (HTTP 422). The closed interval must not overlap any `REQUESTED` or `APPROVED` leave of the same worker; back-to-back intervals (another leave's `end_date` one day before this request's `start_date`) are allowed, but a true overlap is rejected with `ERR_LEAVE_OVERLAP` (HTTP 409). A new leave request is born `REQUESTED`.

A `HouseholdClient` approves a `REQUESTED` leave — the approval re-checks `available_leave_minutes` against `requested_minutes` and rejects with `ERR_INSUFFICIENT_LEAVE_BALANCE` if the balance has dropped since creation — incrementing `used_leave_minutes` by `requested_minutes` and recomputing `available_leave_minutes`. A `HouseholdClient` may instead deny a `REQUESTED` leave, transitioning it to `DENIED` with no balance effects. A `Worker` cancels their own leave from either `REQUESTED` or `APPROVED`; cancelling an `APPROVED` leave decrements `used_leave_minutes` by `requested_minutes` — `accrued_leave_minutes` is untouched and `available_leave_minutes` returns to its pre-approval value. `DENIED` and `CANCELLED` are terminal.

### 3.8. FICA Retroactive Coverage and FUTA / SUTA Wage Bases

FICA coverage for household employees flips retroactively when cumulative year-to-date cash wages cross the 280000-cent threshold. The coverage test is exact — at least 280000 triggers — and is evaluated in `pay_date` ascending order, with `created_at` ascending as tiebreaker. At pay-run calculate time, coverage for a check is projected: `cash_wages_ytd_cents` plus this check's `gross_cents` (plus same-run earlier checks for the worker) reaches the threshold. At finalize, the computed lines are applied: `cash_wages_ytd_cents` advances by gross; when this check is the crossing check, **all** wages paid this year become FICA wages — including earlier checks whose FICA base was zero at issue — with their gross withheld on this check as the catch-up base, still capped by the remaining SS wage-base room. `ss_wages_paid_ytd_cents` and `futa_wages_ytd_cents` advance by the applied bases. The worker's `fica_covered` flag is the persistent form of the same test, re-evaluated at every finalize and at every void.

FUTA applies for a quarter when the household's total cash wages with `pay_date` inside the quarter reach 100000 cents ($1,000) — the boundary is exact, at-least triggers. Once any quarter of the year applies, FUTA accrues for the whole year. Per worker per year, the FUTA base on a check is the lesser of `gross_cents` and the room remaining under the FUTA wage base of 700000 cents ($7,000) after `futa_wages_ytd_cents`; the FUTA employer line is that base times 0.6%, rounded half-up to cents. SUTA follows the same shape per worker per year against the pack's `suta_wage_base_cents` and `suta_rate`, with the per-worker `suta_wages_paid_ytd` accumulator tracked inside the `TaxLiabilityAccount` accrual.

### 3.9. Tax Liability Accounts, Deposits, and the Safe-Harbor Requirement

Each employer carries one `TaxLiabilityAccount` per (`tax_year`, `tax_type`) pair, with `tax_type` one of `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER`. Accounts are created lazily at pay-run finalize in the fixed order `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER` — all five, even when the line amount for a type is 0. `accrued_cents` is the chronological sum of finalized paycheck line amounts for the type and year, with voided paychecks subtracting. `balance_cents` is `accrued_cents` plus `penalty_cents` minus `deposited_cents`.

The `projected_annual_cents` field is a forward-looking variant computed as `accrued_cents` plus the per-period average times the number of remaining pay periods in the tax year, where the per-period average is `accrued_cents` divided by the count of the employer's `FINALIZED` pay runs with `pay_date` in the year (floored at 1 to avoid division by zero), and the total periods per year derive from `pay_frequency`: 52 for `WEEKLY`, 26 for `BIWEEKLY`, 24 for `SEMIMONTHLY`, 12 for `MONTHLY`. Before the first finalized paycheck of the year, `projected_annual_cents` is 0. The per-period average is kept at four decimal places until the installment rounding step.

A `PayrollAdmin` records a tax deposit by supplying `tax_year`, `quarter` (1–4), `amount_cents`, and `remitted_on`. The deposit's `due_date` is computed from the quarter — April 15, June 15, September 15, or January 15 of the following year. `remitted_on` must not lie after the logical-clock current date (otherwise `ERR_INVALID_REQUEST`). At creation, the system captures `required_amount_cents` from the safe-harbor requirement (below) and rejects the deposit with `ERR_DEPOSIT_BELOW_REQUIRED` (HTTP 422) when `amount_cents` falls short. `late_days` is the number of whole days by which `remitted_on` exceeds `due_date`, floored at zero.

The **late-deposit penalty** is tiered over the *required* amount (not the remitted amount): 0 days late, no penalty; 1 through 5 days late, 2% of `required_amount_cents`; 6 through 15 days late, 5%; 16 or more days late, 10%. Each tier's figure is rounded half-up to integer cents. The boundaries are exact: 5 days late is the 2% tier, 6 days late is the 5% tier. The full penalty of every late deposit for the year lands on the `FICA_ER` account's `penalty_cents`; every other account's `penalty_cents` is always 0.

The deposit's `amount_cents` is then allocated across the year's accounts by a waterfall in the fixed order `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER`, each account's `deposited_cents` filled up to its balance; the portion left over after every account reaches zero is recorded as `unapplied_cents`. Deposit creation also recomputes the employer's `compliance_posture` — a deposit with `late_days` greater than 0 forces the posture to at least `ATTENTION`.

The **safe-harbor deposit requirement** follows a pinned six-step evaluation. First, the per-period average is the accrued-to-date sum of `FICA_EE`, `FICA_ER`, and `FUTA_ER` divided by the number of periods elapsed — the count of the employer's `FINALIZED` pay runs with `pay_date` in the tax year — with the divisor floored at 1. Second, `projected_annual` is the accrued sum plus the per-period average times the number of remaining periods. Third, the safe-harbor cap is the smaller of `projected_annual` and 110% of `prior_year_schedule_h_cents` rounded half-up — when `prior_year_schedule_h_cents` is greater than 0; otherwise the cap is `projected_annual`. Fourth, the annual required amount equals the cap when the cap is at least 100000 cents ($1,000), and 0 otherwise. Fifth, the quarterly installment is the annual required divided by 4, rounded half-up to cents. Sixth, the `required_amount_cents` for quarter *q* is the installment times *q* minus the year's already-deposited total, floored at zero. The same requirement drives the `estimated_federal_payment_cents` figure computed at filing prepare time.

### 3.10. Quarterly Filings and Segregation of Duties

A `PayrollAdmin` opens a `QuarterlyFiling` for an employer by supplying `tax_year` and `quarter` (1–4); a duplicate filing for the same (employer, `tax_year`, `quarter`) is rejected with `ERR_DUPLICATE_FILING` (HTTP 409). A new filing is born `OPEN`.

Preparation is a `PayrollAdmin` action that requires the logical-clock current date to be strictly after the last day of the filing quarter — preparing on or before quarter close is rejected with `ERR_QUARTER_NOT_CLOSED` (HTTP 422). Preparation works from either `OPEN` or `REJECTED` status (any other from-state yields `ERR_INVALID_STATE`) and recomputes the filing's figures from the current ledger: `total_cash_wages_cents` (household cash wages with `pay_date` inside the quarter over `ISSUED` paychecks), `futa_applies` (whether `total_cash_wages_cents` reaches the 100000-cent FUTA quarterly trigger — the boundary is exact), `futa_due_cents` and `suta_due_cents` (quarterly accruals over per-worker remaining wage bases), and `estimated_federal_payment_cents` (the safe-harbor quarterly figure). The `prepared_by_user_id` is stamped with the calling `X-User-ID` and `prepared_at` with the logical clock's current instant; re-preparation after a rejection overwrites both.

Submission is a `ComplianceOfficer` action moving `PREPARED → SUBMITTED`, gated by segregation of duties: the calling `X-User-ID` must differ from `prepared_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `ComplianceOfficer` then either accepts the filing (`SUBMITTED → ACCEPTED`, terminal) or rejects it (`SUBMITTED → REJECTED`). Both acceptance and rejection recompute the employer's `compliance_posture` — any `REJECTED` filing forces the posture to at least `ATTENTION`. The `REJECTED` status loops back: preparation may be re-run from `REJECTED`, restoring the filing to `PREPARED` with fresh figures and a fresh `prepared_by_user_id`.

### 3.11. Workers' Compensation Policies

A `PayrollAdmin` quotes a policy for an employer by supplying `state_code` (which must have a rule pack, otherwise `ERR_STATE_RULES_MISSING`), `policy_number`, `coverage_start`, and `coverage_end` — a closed interval, both endpoints inclusive, with `coverage_end` on or after `coverage_start`. A new policy is born `QUOTED`.

Binding a policy (`QUOTED → BOUND`) is a `PayrollAdmin` action that recomputes the employer's `compliance_posture`. From `BOUND`, the policy advances to `ACTIVE` automatically when the logical clock reaches `coverage_start`; the sweep runs on every clock-set operation. From `ACTIVE`, the policy advances to `EXPIRED` automatically once the logical clock passes `coverage_end`. A `PayrollAdmin` may lapse a policy from either `BOUND` or `ACTIVE`; the lapse recomputes the employer's posture and may force it to `RESTRICTED` when the state mandates coverage and no other `BOUND` or `ACTIVE` policy covers today. `LAPSED` and `EXPIRED` are terminal. Both the bind-sweep and the expiry sweep recompute posture on every affected employer.

### 3.12. Year-End Packages: W-2s and Schedule H

A `PayrollAdmin` opens a `YearEndPackage` for an employer by supplying `tax_year`; a duplicate package for the same (employer, `tax_year`) is rejected with `ERR_DUPLICATE_YEAR_END_PACKAGE` (HTTP 409). A new package is born `DRAFT`.

Finalization is a `ComplianceOfficer` action with three preconditions: the package must be in `DRAFT` (else `ERR_INVALID_STATE`); all four `QuarterlyFiling` records for the (employer, `tax_year`) must exist and be `ACCEPTED` (else `ERR_FILINGS_INCOMPLETE`, HTTP 422); and every worker with an `ISSUED` paycheck in `tax_year` must have a non-null `ssn` (else `ERR_MISSING_SSN`, HTTP 422). On success the package transitions `DRAFT → FINALIZED` (terminal) and computes three outputs.

`schedule_h_total_cents` is the sum of the year's `FICA_EE` accrued, `FICA_ER` accrued, and `FUTA_ER` accrued, plus the total of `FIT_EE` lines withheld across the year's `ISSUED` paychecks. `w2_lines` is a per-worker array over workers with `ISSUED` paychecks in the year, each entry carrying `worker_id`, `wages_cents` (sum of gross), `ss_wages_cents` (sum of SS bases), `ss_tax_cents` (sum of `SS_EE` lines), `medicare_tax_cents` (sum of `MEDICARE_EE` and `ADDL_MEDICARE_EE`), `sit_cents` (sum of `SIT_EE`), and `fit_cents` (sum of `FIT_EE`). `underpayment_penalty_applies` is true when the year's total deposits fall short of the smaller of two legs — 90% of `schedule_h_total_cents` rounded half-up, or 110% of `prior_year_schedule_h_cents` rounded half-up — with the second leg dropped entirely when `prior_year_schedule_h_cents` is 0.

---

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP **201** with the created resource in `data`. Endpoints that modify an existing resource — including all state transitions, sweeps, and approvals — return HTTP **200** with the updated resource in `data`. List endpoints return HTTP **200** with `response_type` set to `array` and pagination fields in `meta`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/household-payroll/_clock/set_current_utc` | Set the server logical clock; runs policy sweeps | PayrollAdmin |
| POST | `/household-payroll/employers` | Onboard a household employer | PayrollAdmin |
| GET | `/household-payroll/employers/{id}` | Read one employer | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/suspend` | Suspend an employer | ComplianceOfficer |
| POST | `/household-payroll/employers/{id}/reinstate` | Reinstate a suspended employer | ComplianceOfficer |
| POST | `/household-payroll/state-rule-packs` | Create a state rule pack | PayrollAdmin |
| GET | `/household-payroll/state-rule-packs` | List rule packs, optional `state_code` filter | PayrollAdmin, ComplianceOfficer, HouseholdClient, Worker |
| POST | `/household-payroll/employers/{id}/registrations` | Open a state agency registration (OCC on employer version) | PayrollAdmin |
| POST | `/household-payroll/registrations/{id}/submit` | Submit a DRAFT registration | PayrollAdmin |
| POST | `/household-payroll/registrations/{id}/activate` | Activate a SUBMITTED registration with account number | PayrollAdmin |
| GET | `/household-payroll/employers/{id}/registrations` | List an employer's registrations | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/workers` | Add a domestic worker | HouseholdClient |
| GET | `/household-payroll/workers/{id}` | Read one worker | PayrollAdmin, ComplianceOfficer, HouseholdClient, Worker |
| GET | `/household-payroll/employers/{id}/workers` | List an employer's workers | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/workers/{id}/classify` | Run the classification questionnaire | HouseholdClient |
| POST | `/household-payroll/workers/{id}/activate` | Activate a CLASSIFIED EMPLOYEE | HouseholdClient |
| POST | `/household-payroll/workers/{id}/terminate` | Terminate an ACTIVE worker | HouseholdClient |
| POST | `/household-payroll/workers/{id}/agreements` | Create an agreement, superseding the prior ACTIVE one (OCC on worker version) | HouseholdClient |
| GET | `/household-payroll/workers/{id}/agreements` | List a worker's agreements | PayrollAdmin, ComplianceOfficer, HouseholdClient, Worker |
| GET | `/household-payroll/agreements/{id}` | Read one agreement | PayrollAdmin, ComplianceOfficer, HouseholdClient, Worker |
| GET | `/household-payroll/agreements/{id}/superseded` | List the agreement this one superseded | PayrollAdmin, ComplianceOfficer, HouseholdClient, Worker |
| POST | `/household-payroll/workers/{id}/timesheets` | Create a DRAFT timesheet | Worker |
| POST | `/household-payroll/timesheets/{id}/submit` | Submit a DRAFT timesheet | Worker |
| POST | `/household-payroll/timesheets/{id}/approve` | Approve a SUBMITTED timesheet | HouseholdClient |
| POST | `/household-payroll/timesheets/{id}/reject` | Reject a SUBMITTED timesheet back to DRAFT | HouseholdClient |
| GET | `/household-payroll/timesheets/{id}` | Read one timesheet | PayrollAdmin, HouseholdClient, Worker |
| GET | `/household-payroll/workers/{id}/timesheets` | List a worker's timesheets | PayrollAdmin, HouseholdClient, Worker |
| POST | `/household-payroll/employers/{id}/pay-runs` | Create an OPEN pay run | PayrollAdmin |
| GET | `/household-payroll/pay-runs/{id}` | Read one pay run | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| GET | `/household-payroll/employers/{id}/pay-runs` | List an employer's pay runs | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/pay-runs/{id}/calculate` | (Re)calculate paychecks; locks covering timesheets | PayrollAdmin |
| POST | `/household-payroll/pay-runs/{id}/finalize` | Issue paychecks and accrue tax liabilities | PayrollAdmin |
| GET | `/household-payroll/pay-runs/{id}/paychecks` | List a pay run's paychecks | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| GET | `/household-payroll/pay-runs/{id}/timesheets` | List timesheets locked into a pay run | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| GET | `/household-payroll/paychecks/{id}` | Read one paycheck | PayrollAdmin, HouseholdClient, Worker |
| POST | `/household-payroll/paychecks/{id}/void` | Void an ISSUED paycheck | PayrollAdmin |
| GET | `/household-payroll/workers/{id}/paychecks` | List a worker's paychecks | PayrollAdmin, HouseholdClient, Worker |
| POST | `/household-payroll/workers/{id}/leave-requests` | Request paid leave | Worker |
| POST | `/household-payroll/leave-requests/{id}/approve` | Approve a leave request | HouseholdClient |
| POST | `/household-payroll/leave-requests/{id}/deny` | Deny a leave request | HouseholdClient |
| POST | `/household-payroll/leave-requests/{id}/cancel` | Cancel a REQUESTED or APPROVED leave | Worker |
| GET | `/household-payroll/workers/{id}/leave-requests` | List a worker's leave requests | PayrollAdmin, HouseholdClient, Worker |
| GET | `/household-payroll/employers/{id}/tax-accounts` | List an employer's tax liability accounts | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/deposits` | Record a tax deposit | PayrollAdmin |
| GET | `/household-payroll/employers/{id}/deposits` | List an employer's deposits | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/quarterly-filings` | Open a quarterly filing | PayrollAdmin |
| POST | `/household-payroll/quarterly-filings/{id}/prepare` | Compute filing amounts | PayrollAdmin |
| POST | `/household-payroll/quarterly-filings/{id}/submit` | Submit a PREPARED filing | ComplianceOfficer |
| POST | `/household-payroll/quarterly-filings/{id}/accept` | Agency accepts a SUBMITTED filing | ComplianceOfficer |
| POST | `/household-payroll/quarterly-filings/{id}/reject` | Agency rejects a SUBMITTED filing | ComplianceOfficer |
| GET | `/household-payroll/employers/{id}/quarterly-filings` | List an employer's quarterly filings | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/workers-comp-policies` | Quote a workers' comp policy | PayrollAdmin |
| POST | `/household-payroll/workers-comp-policies/{id}/bind` | Bind a QUOTED policy | PayrollAdmin |
| POST | `/household-payroll/workers-comp-policies/{id}/lapse` | Lapse a BOUND or ACTIVE policy | PayrollAdmin |
| GET | `/household-payroll/employers/{id}/workers-comp-policies` | List an employer's workers' comp policies | PayrollAdmin, ComplianceOfficer, HouseholdClient |
| POST | `/household-payroll/employers/{id}/year-end-packages` | Open a year-end package | PayrollAdmin |
| POST | `/household-payroll/year-end-packages/{id}/finalize` | Finalize the package | ComplianceOfficer |
| GET | `/household-payroll/employers/{id}/year-end-packages` | List an employer's year-end packages | PayrollAdmin, ComplianceOfficer, HouseholdClient |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PAYRUN_STALE` | 409 |
| `ERR_EMPLOYER_RESTRICTED` | 409 |
| `ERR_WORKERS_COMP_REQUIRED` | 422 |
| `ERR_TIMESHEET_OVERLAP` | 409 |
| `ERR_LEAVE_OVERLAP` | 409 |
| `ERR_PAYRUN_OVERLAP` | 409 |
| `ERR_NEW_HIRE_REPORT_LATE` | 422 |
| `ERR_QUARTER_NOT_CLOSED` | 422 |
| `ERR_STATE_RULES_MISSING` | 422 |
| `ERR_NO_ACTIVE_AGREEMENT` | 422 |
| `ERR_REGISTRATION_INACTIVE` | 422 |
| `ERR_FILINGS_INCOMPLETE` | 422 |
| `ERR_CONTRACTOR_NOT_PAYABLE` | 422 |
| `ERR_PERIOD_LENGTH_MISMATCH` | 422 |
| `ERR_PAY_FREQUENCY_NONCOMPLIANT` | 422 |
| `ERR_BELOW_MIN_WAGE` | 422 |
| `ERR_DUPLICATE_RULE_PACK` | 409 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_DUPLICATE_FILING` | 409 |
| `ERR_DUPLICATE_YEAR_END_PACKAGE` | 409 |
| `ERR_INSUFFICIENT_LEAVE_BALANCE` | 422 |
| `ERR_DEPOSIT_BELOW_REQUIRED` | 422 |
| `ERR_MISSING_SSN` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
