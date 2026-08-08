# WIOA Workforce & Job-Training API — Product Requirements Document

## 1. Introduction

The WIOA Workforce & Job-Training API provides the system of record for a public workforce "One-Stop" center operating under the Workforce Innovation and Opportunity Act. Front-line staff use it to intake jobseekers, determine their eligibility, build individualized career plans, purchase occupational training from an Eligible Training Provider List (ETPL) using Individual Training Account (ITA) vouchers, disburse supportive-service payments, broker on-the-job-training (OJT) contracts with partnering employers, refer participants to open jobs, and ultimately report federally-mandated performance outcomes.

The domain is unusually demanding because two very different concerns are intertwined. On one side is a workflow-orchestration problem: a participant travels through parallel eligibility and enrollment tracks, a career plan cycles in and out of revision, and a single exit event fans out into a chain of cascading closures. On the other side is a ledger-reconciliation problem: a finite ITA training budget and a finite per-participant supportive-service allowance must each be conserved to the cent as dollars move between "available", "obligated", and "expended" buckets, with every forward commitment matched by an exact compensating release when work is cancelled. This document specifies both concerns precisely, so that fund balances never drift and workflow state never advances out of order.

All amounts are handled in integer cents and all timestamps are governed by a server-controlled logical clock, ensuring that fiscal totals and exit-driven outcomes are deterministic and independently reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint of the API, which is mounted under `/wioa`.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the call is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes four operational roles plus one read pseudo-role:

- `StateAdmin` — the state/local board operator who owns local areas, the ETPL (training providers and their programs), and the logical clock.
- `CaseManager` — the front-line worker who owns participant intake, eligibility, enrollment, exit, career plans, and ITA vouchers.
- `FiscalOfficer` — the fiscal authority who approves, pays, and voids supportive-service payments and who posts ITA disbursements and OJT reimbursements. This role exists to enforce a segregation of duties: a `CaseManager` requests a supportive-service payment, but only a `FiscalOfficer` may approve or pay it.
- `BusinessServicesRep` — the employer-facing worker who owns employers, OJT contracts, and job referrals and placements.
- `Any` — a pseudo-role meaning that any one of the four authenticated roles may perform the operation; it is used exclusively for read (GET) endpoints.

Referring a participant to an employer is a shared write operation available to both `BusinessServicesRep` and `CaseManager`; all other write operations belong to exactly one role as enumerated in the endpoint table of §4.

Each of the four real roles has an **opaque** identity. When `X-User-Role` is `StateAdmin`, `CaseManager`, `FiscalOfficer`, or `BusinessServicesRep`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`, and ownership of a resource is never inferred from `X-User-ID`. The `Any` pseudo-role is likewise opaque and confers read access only.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order, with ties (records sharing an identical `created_at`, as commonly occurs while the logical clock is held fixed) broken by ascending creation order — the order in which the resources were persisted. Every list response includes the `limit`, `offset`, `total_count`, and `has_more` fields inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources are "common-field" resources and carry a standard set of system-managed properties:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; it is refreshed on every mutation.
- `version` — an integer that begins at 1 on creation and increments by one on every mutation of the resource. It supports optimistic concurrency control as described in §2.8.

Every entity in this system carries these four properties **except** the `ITADisbursement`, which is an immutable ledger record. An `ITADisbursement` carries only `id` and `created_at`; it has no `updated_at` and no `version`, because once posted it is never modified.

Foreign-key references between resources are expressed as string fields holding the target resource's `id` (for example a participant's `local_area_id`, a career plan's `participant_id`, or a disbursement's `voucher_id`). These reference fields are assigned by the server from the URL context or request body, never invented by the client where marked as system-sourced.

### 2.5. Monetary Values, Rates, and Rounding

Every monetary quantity in the system — budgets, caps, authorized costs, disbursements, reimbursements, and supportive payments — is stored and transported as an integer number of cents. There is no sub-cent representation; all fund arithmetic is exact integer arithmetic on cents.

Two calculations produce a cent value from a rate and must round using the **round-half-up** convention to a whole cent:

- The mileage reimbursement rate is **65.5 cents per whole mile**. When a mileage payment is computed, each individual trip's mileage is multiplied by this rate and rounded half-up to a whole cent *before* the trips are summed (see §3.5).
- The OJT reimbursement gross figure is the contract's reimbursement fraction multiplied by the hourly wage and the hours worked, rounded half-up to a whole cent *before* the obligation-remaining cap is applied (see §3.6).

Performance rates (credential and placement rates) are pure ratios, not money. They are rounded half-up to four decimal places. Whenever a rate's denominator is zero, the rate is defined to be exactly 0.0 rather than an error or an undefined value.

### 2.6. The Logical Clock and Temporal Semantics

The server maintains a single logical clock that supplies every system-set timestamp — a participant's `exit_date`, a job referral's `placement_date`, and the `created_at`/`updated_at` fields of all resources. On startup the clock reads exactly `2026-05-01T00:00:00Z`; until an administrator advances it, that default is used verbatim and the machine wall-clock is never consulted. An administrator-only test-driving capability sets the clock to a supplied instant expressed in the `to_iso8601` field.

Training periods and OJT contract periods are treated as **half-open intervals**. A voucher's period runs from its `planned_start_date` (inclusive) up to but not including its `planned_end_date`; an OJT contract's period runs from its `start_date` (inclusive) up to but not including its `end_date`. Two half-open periods overlap when the first starts strictly before the second ends and the second starts strictly before the first ends. Consequently two back-to-back periods where one ends at exactly the instant the next begins do **not** overlap and are permitted. For any period-bearing create, the end instant must be strictly after the start instant.

### 2.7. Dual-Pool Fund Conservation

The system maintains two entirely separate conserved pools of money, and every fund-moving operation must preserve the invariant of its pool exactly.

The **ITA training pool** lives on the `LocalArea`. At creation the area's `ita_budget_total_cents` is an immutable ceiling; `ita_budget_available_cents` is initialized to that total, and both `ita_budget_obligated_cents` and `ita_budget_expended_cents` start at zero. At all times after every voucher transition, the sum of `ita_budget_available_cents`, `ita_budget_obligated_cents`, and `ita_budget_expended_cents` equals `ita_budget_total_cents`. A forward obligation that moves an amount out of available and into obligated, paired with a later compensating cancellation of a never-disbursed voucher that moves the same amount back from obligated into available, restores `ita_budget_available_cents` to its pre-obligation value with zero drift.

The **supportive-service pool** lives on each `Participant` and is a distinct pool from the ITA budget. At intake, a participant's `supportive_available_cents` is initialized to the owning area's `supportive_annual_cap_cents`, and both `supportive_obligated_cents` and `supportive_expended_cents` start at zero. At all times after every supportive-payment transition, the sum of `supportive_available_cents`, `supportive_obligated_cents`, and `supportive_expended_cents` equals that initialized annual cap. A forward approval that moves an amount from available into obligated, paired with a compensating void from the approved state that moves the same amount back from obligated into available, restores `supportive_available_cents` with zero drift.

Every mutation that moves money on the `LocalArea` ledger also increments the area's `version` (this is the concurrency anchor of §2.8); supportive-pool movements mutate the participant and follow the ordinary `updated_at`/`version` refresh rules of §2.4.

### 2.8. Optimistic Concurrency Control on the ITA Budget

Obligating an ITA voucher draws its authorized cost down from the shared `LocalArea` ITA pool, so the obligation endpoint is guarded by optimistic concurrency control against the area's `version`. The obligate request must include `expected_local_area_version` carrying the client's last-observed `version` of the owning `LocalArea`. If that value does not match the area's current `version` at obligation time — because some other obligation, disbursement, completion, or cancellation has advanced the area's version since the client last read the budget — the request is rejected with `ERR_STALE_LOCAL_AREA_VERSION` and HTTP status 412. This prevents a client from committing an obligation against a budget snapshot it has not actually observed, since the pool may already have been drawn down. This OCC check is evaluated **last**, after every other precondition on obligation has passed. No other endpoint accepts or requires a version field.

### 2.9. Cascading State Propagation

Certain operations mutate more than one resource; every cascade below happens atomically as part of the triggering operation, and each mutated resource has its own `updated_at` refreshed and `version` incremented.

**Participant exit cascade.** When a participant exits, the exit itself sets `enrollment_status` to `EXITED`, records `exit_date` from the logical clock, and records `exit_exclusion`. It then closes work in a chain: every `CareerPlan` of that participant currently in `ACTIVE` or `UNDER_REVISION` transitions to `CLOSED`; as each plan closes, every `ITAVoucher` of the participant that references that plan and is currently `OBLIGATED` transitions to `CANCELLED`, and the un-expended remainder of each such voucher is released back into the area's available budget. Separately (as a fan-out, not part of that closure chain), every `SupportiveServicePayment` of the participant in `REQUESTED` or `APPROVED` status transitions to `VOIDED`, restoring any obligated supportive dollars.

**Provider suspension cascade.** When a training provider is suspended, every `TrainingProgram` offered by that provider transitions from `ACTIVE` to `SUSPENDED`; as each program is suspended, every `ITAVoucher` referencing that program that is still in `DRAFT` transitions to `CANCELLED`. Draft vouchers hold no obligation, so no funds move during this cascade.

### 2.10. Validation Ordering and Nested-Path Resolution

Across all endpoints, validations are applied in a fixed priority order so that the reported error is deterministic. Header presence and validity is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400). Role authorization is checked next (`ERR_FORBIDDEN_FOR_ROLE`, 403). Then the existence of the path resource and of every referenced foreign-key resource is checked, validated left-to-right along the URL so that the first identifier in the path that does not resolve produces `ERR_NOT_FOUND` (404) before any deeper lookup is attempted. Then request-body well-formedness is checked (`ERR_INVALID_REQUEST`, 400): required fields present, enum values recognized, amounts and mileage strictly positive, dates parseable, and the period end strictly after its start. Only after all of these do the state, referential, temporal, and fiscal business rules run, in the endpoint-specific order described in §3. The single OCC check runs last of all.

## 3. Business Logic & Workflows

### 3.1. Local Areas and the Eligible Training Provider List

A `StateAdmin` establishes the operating context by creating a `LocalArea`, supplying its `name`, its `program_year`, the immutable `ita_budget_total_cents` ceiling for that program year, the per-voucher `ita_individual_cap_cents` authorization policy, and the per-participant `supportive_annual_cap_cents` policy. At creation the area's available ITA budget equals its total, its obligated and expended balances are zero, and its `version` is 1.

The same administrator maintains the ETPL. Registering a training provider under an area records the provider's `name` and its owning `local_area_id`, and starts its `etpl_status` at `APPLIED`. Approving the provider advances `etpl_status` from `APPLIED` to `ELIGIBLE`; approval is rejected with `ERR_INVALID_STATE` unless the provider is currently `APPLIED`. Suspending an eligible provider advances `etpl_status` from `ELIGIBLE` to `SUSPENDED` (rejected with `ERR_INVALID_STATE` unless currently `ELIGIBLE`) and triggers the provider-suspension cascade of §2.9.

A provider offers one or more programs. Adding a program records its offering `provider_id`, its `name`, its `cip_code` (the Classification of Instructional Programs code), its full `total_cost_cents`, its `credential_type` (one of `DEGREE`, `CERTIFICATE`, `LICENSE`, or `NONE`), and whether it is on the local `in_demand` occupation list (defaulting to true when omitted). A program's `status` begins at `ACTIVE` and only ever moves to `SUSPENDED`, and it does so solely as part of its provider's suspension cascade — a program's status mirrors provider suspension and is not directly settable.

### 3.2. Participant Intake, Eligibility, and Enrollment

A `CaseManager` intakes a jobseeker into a specific area, which fixes the participant's `local_area_id`. Intake captures the participant's `full_name`, their `funding_stream` (one of `ADULT`, `DISLOCATED_WORKER`, or `YOUTH`), and three boolean flags each defaulting to false: `veteran` status, `low_income` status, and the `basic_skills_deficient` flag noted during the intake assessment. Intake initializes the supportive pool by setting `supportive_available_cents` to the area's annual supportive cap. At intake `credential_attained` and `msg_attained` are both initialized to false, `exit_date` is null, and `exit_exclusion` is false; these advance only later through voucher completion (§3.4) and participant exit (§3.8).

At intake the system computes the participant's `priority_of_service`, which is either `PRIORITY` or `NON_PRIORITY`. The rule is evaluated in order: if the funding stream is `ADULT` and the participant is a veteran, is low-income, or is basic-skills-deficient, the priority is `PRIORITY`; otherwise, if the participant is a veteran (regardless of funding stream, since veterans receive priority of service across all streams), the priority is `PRIORITY`; otherwise the priority is `NON_PRIORITY`. This value is computed once at intake and does not change afterward.

A participant carries two independent status dimensions that advance on their own triggers. The eligibility dimension, `eligibility_status`, starts at `PENDING`. Recording an eligibility determination supplies a `decision`; a determination of eligible advances `eligibility_status` from `PENDING` to `ELIGIBLE`, and a determination of ineligible advances it from `PENDING` to `INELIGIBLE`. Either determination is rejected with `ERR_INVALID_STATE` unless the participant is currently `PENDING`. `INELIGIBLE` is terminal.

The enrollment dimension, `enrollment_status`, starts at `NOT_ENROLLED`. Enrolling a participant advances it from `NOT_ENROLLED` to `ENROLLED`, but the enrollment is guarded across dimensions: it is rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the eligibility dimension is already `ELIGIBLE`, and rejected with `ERR_INVALID_STATE` unless the enrollment dimension is currently `NOT_ENROLLED`. The exit workflow and its cascade are described in §3.8.

### 3.3. Career Planning

A `CaseManager` builds an individualized career plan for a participant, which sets the plan's `participant_id`. Creating a plan records the `goal_occupation` (the target occupation or SOC goal), the `service_track` (one of `TRAINING`, `JOB_READY`, or `OJT`), and whether a supportive-service need is documented in the plan via `supportive_need_documented` (defaulting to false). A new plan starts with `status` of `DRAFT` and `revision_count` of 0.

The plan follows a cyclic lifecycle. Activating a `DRAFT` plan advances its `status` to `ACTIVE`; activation is rejected with `ERR_INVALID_STATE` unless the plan is `DRAFT`, and rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the owning participant's eligibility is `ELIGIBLE`. Requesting a revision on an `ACTIVE` plan advances its `status` to `UNDER_REVISION` (rejected with `ERR_INVALID_STATE` unless `ACTIVE`). Approving a revision returns an `UNDER_REVISION` plan to `ACTIVE` and increments `revision_count` by one (rejected with `ERR_INVALID_STATE` unless `UNDER_REVISION`). The `ACTIVE ↔ UNDER_REVISION` cycle may repeat any number of times. A plan reaches `CLOSED` only through the participant-exit cascade of §2.9, never by direct request; `CLOSED` is terminal.

### 3.4. ITA Vouchers: Obligation, Disbursement, Completion, and Cancellation

A `CaseManager` funds a participant's training with an Individual Training Account voucher. Creating a voucher under a participant fixes its `participant_id` and records the `program_id` of the ETPL program to be funded, the `career_plan_id` of the plan authorizing the training, the `authorized_cost_cents` to be committed, and the training window's `planned_start_date` and `planned_end_date`. A new voucher starts in `DRAFT` with both `amount_obligated_cents` and `amount_expended_cents` at zero and `credential_earned` initialized to false. At creation, the authorized cost may not exceed the referenced program's `total_cost_cents`; a request that violates this is malformed and rejected with `ERR_INVALID_REQUEST`.

Obligating a `DRAFT` voucher commits funds and is the most heavily-guarded transition in the system. Its preconditions are evaluated in this order, each with its own error: the voucher must be `DRAFT` (`ERR_INVALID_STATE`); the participant's enrollment must be `ENROLLED` (`ERR_PARTICIPANT_NOT_ENROLLED`); the referenced career plan's status must be `ACTIVE` (`ERR_NO_ACTIVE_CAREER_PLAN`); the referenced program's status must be `ACTIVE` (`ERR_PROGRAM_NOT_ELIGIBLE`); the voucher's training period must not overlap the half-open training period of any other `OBLIGATED` voucher of the same participant (`ERR_TRAINING_PERIOD_OVERLAP`); the authorized cost must not exceed the area's `ita_individual_cap_cents` (`ERR_ITA_CAP_EXCEEDED`); the authorized cost must not exceed the area's `ita_budget_available_cents` (`ERR_ITA_BUDGET_EXCEEDED`); and finally the OCC check on `expected_local_area_version` (`ERR_STALE_LOCAL_AREA_VERSION`, 412) described in §2.8. On success the voucher moves to `OBLIGATED`, its `amount_obligated_cents` is set to its `authorized_cost_cents`, the area's available budget decreases by that amount while its obligated budget increases by the same amount, and the area's `version` increments by one.

A `FiscalOfficer` posts training disbursements against an `OBLIGATED` voucher. A disbursement records its parent `voucher_id`, a strictly positive `amount_cents`, and an optional `note`. The disbursed amount may not exceed the voucher's remaining unexpended obligation — that is, `amount_obligated_cents` minus `amount_expended_cents` — otherwise the post is rejected with `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION`. On success a new immutable disbursement record is created, the voucher's `amount_expended_cents` increases by the disbursed amount, the area's obligated budget decreases by that amount while its expended budget increases by the same amount, and the area's `version` increments by one. A voucher tracks two figures with deliberately different algorithms: `amount_obligated_cents` is a forward-looking commitment fixed at the full authorized cost the moment the voucher is obligated, while `amount_expended_cents` is the chronological running sum of the voucher's posted disbursement amounts taken in creation order. The two figures coincide only when the voucher has been fully disbursed.

Completing an `OBLIGATED` voucher records the training outcome. The request supplies `credential_earned`; on completion the voucher's `credential_earned` is set from the request and its `status` moves to `COMPLETED` (rejected with `ERR_INVALID_STATE` unless `OBLIGATED`). The un-expended remainder — obligated minus expended — is released: the area's obligated budget decreases by the remainder while its available budget increases by the same amount, and the area's `version` increments by one. Completion also stamps the owning participant: `credential_attained` is set to the voucher's `credential_earned`, and `msg_attained` (measurable skill gain) is set to true.

Cancelling a voucher is permitted from either `DRAFT` or `OBLIGATED` (rejected with `ERR_INVALID_STATE` from any other state) and moves it to `CANCELLED`. Cancelling a `DRAFT` voucher moves no funds. Cancelling an `OBLIGATED` voucher releases its un-expended remainder exactly as completion does — obligated down, available up by that remainder, area `version` incremented — and the area's `version` increments only when funds actually move. A voucher may also reach `CANCELLED` without a direct request: a `DRAFT` voucher is cancelled by the provider-suspension cascade, and an `OBLIGATED` voucher is cancelled (with the same remainder release) by the career-plan-close cascade, both described in §2.9.

### 3.5. Supportive-Service Payments

Supportive-service payments help a participant meet incidental costs of participation, and they enforce a strict segregation of duties. A `CaseManager` requests a payment for a participant, which fixes its `participant_id`; approval, payment, and voiding are reserved to a `FiscalOfficer`.

A request records a `service_type` — one of `MILEAGE`, `CHILDCARE`, `TOOLS`, or `OTHER` — and starts in `REQUESTED`. For the non-mileage types (`CHILDCARE`, `TOOLS`, `OTHER`), the request supplies `amount_cents`, which must be strictly positive, and the payment's `computed_amount_cents` is simply that amount. For `MILEAGE`, the request instead supplies `trips`, an array where each element is a whole number of miles greater than zero; the payment's `computed_amount_cents` is derived by multiplying each trip's mileage by the 65.5-cents-per-mile rate, rounding each trip's product half-up to a whole cent, and then summing those per-trip rounded cents. The rounding order is pinned: each trip is rounded before the sum is taken, which can differ from rounding a single summed product. In the stored payment the input field not applicable to the chosen `service_type` is null: a `MILEAGE` payment carries its `trips` array with `amount_cents` null, while a `CHILDCARE`, `TOOLS`, or `OTHER` payment carries its `amount_cents` with `trips` null. A malformed request — a non-positive amount, a non-positive or non-integer trip mileage, or a missing required field — is rejected with `ERR_INVALID_REQUEST`.

Approving a `REQUESTED` payment is a `FiscalOfficer` action that obligates supportive funds. It is rejected with `ERR_INVALID_STATE` unless the payment is `REQUESTED`; rejected with `ERR_NO_ACTIVE_CAREER_PLAN` unless the participant has a career plan that is currently `ACTIVE` and whose `supportive_need_documented` flag is true; and rejected with `ERR_SUPPORTIVE_CAP_EXCEEDED` unless the payment's `computed_amount_cents` is at most the participant's `supportive_available_cents`. On success the payment moves to `APPROVED`, the participant's available supportive balance decreases by the computed amount, and the obligated balance increases by the same amount. Paying an `APPROVED` payment (rejected with `ERR_INVALID_STATE` unless `APPROVED`) moves it to `PAID`, decreases the participant's obligated balance by the computed amount, and increases the expended balance by the same amount.

Voiding a payment is permitted from `REQUESTED` or `APPROVED` (rejected with `ERR_INVALID_STATE` from any other state) and moves it to `VOIDED`. Voiding a `REQUESTED` payment moves no funds, since a requested payment holds no obligation. Voiding an `APPROVED` payment is a compensating reversal: the participant's obligated balance decreases by the computed amount and the available balance increases by the same amount. Both `PAID` and `VOIDED` are terminal. Payments may also be voided automatically by the participant-exit cascade of §2.9.

### 3.6. Employer Partnerships and On-the-Job Training

A `BusinessServicesRep` registers an employer partner under an area, fixing the employer's `local_area_id` and recording its `name`, its `size` (either `SMALL` for fewer than 50 employees or `LARGE`), and its `max_concurrent_ojt_slots`, the aggregate cap on how many of the employer's OJT contract periods may be simultaneously active.

Creating an OJT contract under an employer records the `participant_id` of the trainee, the `reimbursement_rate` (the fraction of wages the program will reimburse), the trainee's `wage_cents_per_hour`, the `planned_hours`, the total `obligated_amount_cents` reimbursement ceiling, and the contract's `start_date` and `end_date`. The reimbursement rate must be greater than zero and may not exceed the employer's size ceiling — 0.75 for a `SMALL` employer and 0.50 for a `LARGE` employer; a rate above the applicable ceiling is rejected with `ERR_OJT_RATE_EXCEEDED`. A new contract starts in `DRAFT` with `amount_expended_cents` at zero.

Activating a `DRAFT` contract advances its `status` to `ACTIVE`. It is rejected with `ERR_INVALID_STATE` unless the contract is `DRAFT`; rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the trainee's eligibility is `ELIGIBLE` and enrollment is `ENROLLED`; and rejected with `ERR_OJT_CAPACITY_EXCEEDED` when the employer is already at capacity. Capacity is evaluated as an interval-stabbing count: among the employer's currently-`ACTIVE` contracts whose half-open period overlaps this contract's half-open period, activation is refused if that overlapping count is already at or above `max_concurrent_ojt_slots`. This is an aggregate simultaneous-occupancy limit, not a pairwise ban — up to the cap number of periods may overlap at once, and adjacency where one period ends exactly when another begins is not an overlap.

A `FiscalOfficer` posts reimbursements against an `ACTIVE` contract by supplying `hours_worked`. The gross reimbursement is the contract's `reimbursement_rate` multiplied by its `wage_cents_per_hour` and by the supplied hours worked, rounded half-up to a whole cent. The amount actually reimbursed is the lesser of that gross figure and the contract's remaining obligation — `obligated_amount_cents` minus `amount_expended_cents` — and the contract's `amount_expended_cents` increases by that reimbursed amount. Completing an `ACTIVE` contract moves it to `COMPLETED`, and terminating an `ACTIVE` contract moves it to `TERMINATED`; each is rejected with `ERR_INVALID_STATE` unless the contract is `ACTIVE`. Both `COMPLETED` and `TERMINATED` are terminal.

### 3.7. Job Referrals and Placement

Referring a participant to an open job fixes the referral's `participant_id` and records the target `employer_id`, the `job_title`, and an optional advertised `offered_wage_cents_per_hour`. This is the one shared write: both a `BusinessServicesRep` and a `CaseManager` may create a referral. A new referral starts in `REFERRED`, with `placement_wage_cents_per_hour` and `placement_date` unset.

A `BusinessServicesRep` records the outcome. Placing a referral sets the confirmed `placement_wage_cents_per_hour` from the request when supplied (the field is optional and remains null when omitted) and stamps `placement_date` from the logical clock, moving `status` to `PLACED`. Placement is rejected with `ERR_INVALID_STATE` unless the referral is `REFERRED`, and rejected with `ERR_PARTICIPANT_NOT_ENROLLED` unless the participant's enrollment is either `ENROLLED` or `EXITED` (placement is meaningful even after exit, which is how post-exit employment outcomes are captured). Rejecting a referral moves `status` to `REJECTED` (rejected with `ERR_INVALID_STATE` unless `REFERRED`). Both `PLACED` and `REJECTED` are terminal.

### 3.8. Participant Exit and Performance Reporting

A `CaseManager` exits an enrolled participant, optionally supplying `exit_exclusion` (defaulting to false) to mark the participant as excluded from WIOA performance denominators. Exit is rejected with `ERR_INVALID_STATE` unless enrollment is `ENROLLED`. On success `enrollment_status` becomes `EXITED`, `exit_date` is stamped from the logical clock, `exit_exclusion` is recorded, and the full cascade of §2.9 runs: the participant's `ACTIVE` and `UNDER_REVISION` career plans close, their `OBLIGATED` vouchers cancel with remainder release, and their `REQUESTED`/`APPROVED` supportive payments void with fund restoration.

Performance is reported per area through a computed summary. Let the exiters be the area's participants whose enrollment is `EXITED`; `exiter_count` is their total number. Among exiters, `excluded_count` is the number with `exit_exclusion` true, and the included exiters are those with `exit_exclusion` false, of which `included_count` is the number. `credential_count` is the number of included exiters whose `credential_attained` is true, and `placement_count` is the number of included exiters who have at least one job referral in `PLACED` status. The summary reports two credential rates over different denominators: the `raw_credential_rate` is `credential_count` divided by `exiter_count`, and the `adjusted_credential_rate` is `credential_count` divided by `included_count`. The `placement_rate` is `placement_count` divided by `included_count`. Each rate is rounded half-up to four decimal places, and whenever the relevant denominator is zero the rate is reported as exactly 0.0.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that read a resource, drive a state transition, or otherwise modify an existing resource return `200 OK`. The one exception among mutations is posting a disbursement, which creates a new `ITADisbursement` record and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wioa/_clock/set_current_utc` | Set the server logical clock | StateAdmin |
| POST | `/wioa/local-areas` | Create a local workforce area | StateAdmin |
| GET | `/wioa/local-areas/{id}` | Get a local area (ITA budget ledger + version) | Any |
| GET | `/wioa/local-areas/{id}/participants` | List participants of a local area | Any |
| GET | `/wioa/local-areas/{id}/performance-summary` | Computed WIOA performance summary | Any |
| POST | `/wioa/local-areas/{id}/participants` | Intake a participant | CaseManager |
| GET | `/wioa/participants/{id}` | Get a participant | Any |
| POST | `/wioa/participants/{id}/determine-eligibility` | Record an eligibility determination | CaseManager |
| POST | `/wioa/participants/{id}/enroll` | Enroll an eligible participant | CaseManager |
| POST | `/wioa/participants/{id}/exit` | Exit a participant (triggers cascade) | CaseManager |
| POST | `/wioa/participants/{id}/career-plans` | Create a career plan for a participant | CaseManager |
| GET | `/wioa/participants/{id}/career-plans` | List a participant's career plans | Any |
| GET | `/wioa/career-plans/{id}` | Get a career plan | Any |
| POST | `/wioa/career-plans/{id}/activate` | Activate a DRAFT plan | CaseManager |
| POST | `/wioa/career-plans/{id}/request-revision` | Move an ACTIVE plan into revision | CaseManager |
| POST | `/wioa/career-plans/{id}/approve-revision` | Return an UNDER_REVISION plan to ACTIVE | CaseManager |
| POST | `/wioa/local-areas/{id}/training-providers` | Register a training provider | StateAdmin |
| GET | `/wioa/training-providers/{id}` | Get a training provider | Any |
| GET | `/wioa/training-providers` | List training providers | Any |
| POST | `/wioa/training-providers/{id}/approve` | Approve a provider onto the ETPL | StateAdmin |
| POST | `/wioa/training-providers/{id}/suspend` | Suspend a provider (cascades) | StateAdmin |
| POST | `/wioa/training-providers/{id}/programs` | Add a program to a provider | StateAdmin |
| GET | `/wioa/training-programs/{id}` | Get a training program | Any |
| GET | `/wioa/training-providers/{id}/programs` | List a provider's programs | Any |
| POST | `/wioa/participants/{id}/ita-vouchers` | Create a DRAFT ITA voucher | CaseManager |
| GET | `/wioa/ita-vouchers/{id}` | Get an ITA voucher | Any |
| GET | `/wioa/ita-vouchers` | List ITA vouchers | Any |
| POST | `/wioa/ita-vouchers/{id}/obligate` | Obligate a DRAFT voucher (OCC; draws budget) | CaseManager |
| POST | `/wioa/ita-vouchers/{id}/disburse` | Post a disbursement against a voucher | FiscalOfficer |
| GET | `/wioa/ita-vouchers/{id}/disbursements` | List disbursements against a voucher | Any |
| POST | `/wioa/ita-vouchers/{id}/complete` | Complete training; record credential/MSG | CaseManager |
| POST | `/wioa/ita-vouchers/{id}/cancel` | Cancel a DRAFT or OBLIGATED voucher | CaseManager |
| POST | `/wioa/participants/{id}/supportive-services` | Request a supportive-service payment | CaseManager |
| GET | `/wioa/supportive-services/{id}` | Get a supportive-service payment | Any |
| GET | `/wioa/participants/{id}/supportive-services` | List a participant's supportive payments | Any |
| POST | `/wioa/supportive-services/{id}/approve` | Approve a REQUESTED payment | FiscalOfficer |
| POST | `/wioa/supportive-services/{id}/pay` | Pay an APPROVED payment | FiscalOfficer |
| POST | `/wioa/supportive-services/{id}/void` | Void a REQUESTED/APPROVED payment | FiscalOfficer |
| POST | `/wioa/local-areas/{id}/employers` | Register an employer partner | BusinessServicesRep |
| GET | `/wioa/employers/{id}` | Get an employer | Any |
| GET | `/wioa/employers` | List employers | Any |
| POST | `/wioa/employers/{id}/ojt-contracts` | Create an OJT contract | BusinessServicesRep |
| GET | `/wioa/ojt-contracts/{id}` | Get an OJT contract | Any |
| GET | `/wioa/ojt-contracts` | List OJT contracts | Any |
| POST | `/wioa/ojt-contracts/{id}/activate` | Activate a DRAFT OJT contract | BusinessServicesRep |
| POST | `/wioa/ojt-contracts/{id}/reimburse` | Post an employer reimbursement | FiscalOfficer |
| POST | `/wioa/ojt-contracts/{id}/complete` | Complete an ACTIVE OJT contract | BusinessServicesRep |
| POST | `/wioa/ojt-contracts/{id}/terminate` | Terminate an ACTIVE OJT contract | BusinessServicesRep |
| POST | `/wioa/participants/{id}/job-referrals` | Refer a participant to an employer | BusinessServicesRep, CaseManager |
| GET | `/wioa/job-referrals/{id}` | Get a job referral | Any |
| GET | `/wioa/job-referrals` | List job referrals | Any |
| POST | `/wioa/job-referrals/{id}/place` | Record a placement | BusinessServicesRep |
| POST | `/wioa/job-referrals/{id}/reject` | Record a non-hire | BusinessServicesRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PARTICIPANT_NOT_ELIGIBLE` | 409 |
| `ERR_PARTICIPANT_NOT_ENROLLED` | 409 |
| `ERR_NO_ACTIVE_CAREER_PLAN` | 409 |
| `ERR_PROGRAM_NOT_ELIGIBLE` | 409 |
| `ERR_OJT_RATE_EXCEEDED` | 409 |
| `ERR_TRAINING_PERIOD_OVERLAP` | 409 |
| `ERR_OJT_CAPACITY_EXCEEDED` | 409 |
| `ERR_ITA_CAP_EXCEEDED` | 409 |
| `ERR_ITA_BUDGET_EXCEEDED` | 409 |
| `ERR_SUPPORTIVE_CAP_EXCEEDED` | 409 |
| `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION` | 409 |
| `ERR_STALE_LOCAL_AREA_VERSION` | 412 |
