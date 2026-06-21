# Pension DB Administration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Pension / Defined-Benefit Plan Administration API, a back-office system that carries an employer-sponsored defined-benefit plan and its participants through the full benefit lifecycle: census intake and service-credit accrual, the actuarial funded-status filings that gate plan operations, the participant's retirement election and the survivor-annuity or lump-sum form they choose, the qualified-domestic-relations split that may carve a share of that benefit to an alternate payee, and finally the recurring monthly payment with its cost-of-living growth.

Defined-benefit administration is unforgiving because its numbers come from two very different worlds and the two must never be mixed. A plan is either a **final-average-pay** plan, where the monthly benefit is a multiplier applied to a participant's highest-paid years, or a **cash-balance** plan, where a hypothetical account grows by pay credits and interest credits and is then annuitized — and the same endpoint must produce the right figure for whichever variant the plan was created under. Layered on top is a compliance regime: a plan that is underfunded restricts or freezes the very lump-sum and termination operations an administrator might want to run, an actuary's certification of one year's filing can silently supersede an earlier one and shift the whole plan's posture, and a person who drafts an election may never be the person who approves it.

The API is consumed by three segregated office roles — a plan sponsor who funds and terminates, an enrolled actuary who certifies funded status, and a third-party benefits administrator who runs the day-to-day census, elections, splits, and payments. The sections below fix the response contract and the cross-cutting funded-status, precision, and concurrency rules first, then walk the business workflows where the detailed accrual, reduction, valuation, and allocation rules live.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting user, and `X-User-Role`, the operational capacity under which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and well-formed but the caller's role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows: `PlanSponsor`, `PlanActuary`, and `BenefitsAdministrator`. The `PlanSponsor` is the employer that creates plans, files PBGC premiums, and begins plan termination; it does not administer individual benefits or certify actuarial filings. The `PlanActuary` is the enrolled actuary who drafts and certifies funded-status filings and prepares premium filings; it does not administer benefits or approve elections. The `BenefitsAdministrator` is the third-party administrator that manages the census, compensation and service credit, elections, QDROs, payments, and COLA.

All three roles use an **opaque** identity model: in each case `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server does not compare it to any entity's `id`. The server does, however, record it where a workflow requires it — specifically, when a `BenefitsAdministrator` submits an election the server captures that operator's `X-User-ID` as the election's `submitted_by_user_id`, and that recorded value is later compared against the `X-User-ID` of whoever attempts approval to enforce segregation of duties. No role's `X-User-ID` ever functions as a foreign key into the data model; it is purely an actor stamp.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, every list response is sorted by the resource's creation timestamp in ascending order. The envelope's `meta` object on list responses carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a common set of server-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, refreshed on every mutation. The `version` field is an integer that begins at 1 and increments by one on each mutation of the resource; it underpins the optimistic-concurrency mechanism described in §2.7.

Two entities are deliberately lighter-weight. A `ServiceCreditAdjustment` is an append-only event and a `SpousalConsent` is an immutable record of a witnessed waiver; both carry only `id` and `created_at`. Neither one carries `updated_at` and neither carries `version`, because once written they are never modified in place.

### 2.5. Funded-Status Posture and Its Gating Effects

Every plan carries a derived `funding_posture` of `OPEN`, `RESTRICTED`, or `FROZEN`. The posture is never set directly by a client; it is recomputed from the plan's actuarial filings and it governs which benefit operations the plan will permit. A newly created plan, having no certified filing yet, is `OPEN`. Once filings are certified, the posture is driven exclusively by the certified filing with the greatest `plan_year`, whose identifier the plan exposes as `latest_certified_filing_id`. This pointer is not a stored foreign key; it is the computed reference to whichever certified filing currently drives posture, and it is `null` when no filing has been certified. When two certified filings tie on `plan_year`, the one with the greater `created_at` is treated as latest.

The posture is read from that driving filing's `aftap_pct` — its Adjusted Funding Target Attainment Percentage — against two thresholds. When the attainment percentage is at least 0.80 the posture is `OPEN`. When it is at least 0.60 but below 0.80 the posture is `RESTRICTED`, signalling benefit restrictions under which lump sums are limited. When it is below 0.60 the posture is `FROZEN`, under which lump sums and accruals are frozen. The two consequences that posture enforces are concentrated in two places: a `FROZEN` plan refuses to accept a lump-sum election for submission, and a `RESTRICTED` plan refuses voluntary standard termination; both refusals carry `ERR_FUNDING_RESTRICTED`. The precise trigger conditions for each gate are stated alongside their workflows in §3.

### 2.6. Precision, Rounding, and Monetary Representation

Monetary quantities in this system are stored as integer cents, and every field whose name ends in `_cents` is an integer count of cents rather than a decimal currency amount. Wherever a calculation divides or multiplies cents, the result is rounded to the nearest whole cent using the round-half-up convention unless the rule explicitly states a different treatment. Two computations deviate from round-half-up and say so where they are defined: credited service is rounded **down** to the nearest half-year before adjustments are applied, and the net participant amount at payment setup is **floored at zero** rather than allowed to go negative.

Ratio and fraction fields follow their own stated precision. The `aftap_pct` and `relative_value_pct` ratios are rounded to four decimal places. The `vested_pct` fraction is rounded to two decimal places. These rounding rules are restated in context in §3 so that each calculation's output precision is unambiguous at the point the calculation is described.

### 2.7. Optimistic Concurrency on Filing Certification

Certifying a plan-year filing is the one operation in this system that mutates the plan's own `version`, and it is therefore guarded by optimistic concurrency. The certify request must carry `expected_plan_version` as a required field whose value is the plan `version` the actuary last observed. If that value does not equal the plan's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The intent is to catch the case where another certification has already run since the actuary read the plan — that earlier certification legitimately superseded prior filings and re-derived the plan's posture, so the actuary's view of which filing is latest, and of the plan generally, is now stale. A successful certification increments the plan's `version` by one, which is precisely why a second actuary holding the old number is turned away. No other endpoint in the system accepts a version field; certification alone takes `expected_plan_version`.

### 2.8. Hierarchical Consistency and Cascades

When an operation changes one resource in a way that logically forces a change elsewhere, the server performs the dependent change itself rather than waiting for a separate client request. Each such dependent mutation independently refreshes that resource's `updated_at` and increments its `version`. The major cascades are these: recording a participant's death terminates that participant's in-pay benefit; commencing an election creates a payment and retires the participant; certifying a later filing supersedes an earlier certified one and re-derives the plan's posture; and beginning plan termination terminates the plan's active payments. The exact preconditions and downstream effects of each cascade live with their workflow in §3; the principle here is simply that these secondary effects are automatic and that each one is a real mutation with the usual version and timestamp bookkeeping.

### 2.9. Nested Resource Retrieval and Path Validation

Several endpoints address a resource through a path that names a parent and then a child — for example, listing the compensation rows under a particular participant, or certifying a filing under a particular plan. The server validates the identifiers in such a path strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A filing under a non-existent plan therefore fails on the plan before the filing is ever consulted. This left-to-right existence check runs ahead of any business rule on the targeted resource.

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Role authorization is checked next, yielding `ERR_FORBIDDEN`. Then path-referenced existence is checked left to right, yielding `ERR_NOT_FOUND`. Then the request body is checked for well-formedness — required fields present, enum values legal, amounts non-negative, dates in ISO-8601 form — yielding `ERR_INVALID_REQUEST` (HTTP 422). Then per-parent uniqueness is checked on creates, yielding `ERR_DUPLICATE_RESOURCE` (HTTP 409). Only after these structural checks does the system evaluate state-machine legality (`ERR_INVALID_STATE`, HTTP 409) and then the domain-specific business rules described in §3. Where a single workflow stacks several business rules, the order among them is stated with that workflow.

Uniqueness applies per the resource's natural scope: a plan's `ein_psn` is unique across all plans; a participant's `ssn_last4` is unique within its plan; an annual compensation row's `plan_year` is unique per participant; a plan-year filing's `plan_year` is unique per plan; and a premium filing's `premium_year` is unique per plan. A create that would violate any of these yields `ERR_DUPLICATE_RESOURCE`.

## 3. Business Logic & Workflows

### 3.1. Establishing the Plan and Its Benefit Variant

A `PlanSponsor` opens the system by creating a `PensionPlan`. The create payload supplies the plan's legal name as `plan_name`, the combined employer-EIN-and-plan-number key as `ein_psn`, and the variant selector `benefit_formula_type`, which is one of `FINAL_AVERAGE_PAY` or `CASH_BALANCE` and permanently pins which benefit calculation the plan uses. The sponsor may also supply `normal_retirement_age`, the retirement age in whole years that defaults to 65, and `cola_pct`, the annual cost-of-living adjustment expressed as a fraction (for instance 0.02 for two percent) that defaults to 0.0. The remaining rate inputs are variant-specific: `fap_accrual_rate` is the benefit multiplier per year of service used by final-average-pay plans and is ignored on cash-balance plans, while `cb_pay_credit_rate` (the annual pay credit as a fraction of compensation) and `cb_interest_crediting_rate` (the annual interest credit fraction) are used by cash-balance plans and ignored on final-average-pay plans. A new plan is created with `status` of `ACTIVE`, `funding_posture` of `OPEN`, and `version` equal to 1.

The plan's `status` axis is simple: it is `ACTIVE` until the sponsor begins a standard termination, after which it is `TERMINATING`. Termination is a `PlanSponsor` capability that moves the plan from `ACTIVE` to `TERMINATING`. It is refused when the plan's `funding_posture` is `RESTRICTED` — a restricted plan cannot be voluntarily standard-terminated — and that refusal carries `ERR_FUNDING_RESTRICTED`. When termination does proceed, it has a hard downstream effect: every `BenefitPayment` under the plan that is currently `IN_PAY` or `SUSPENDED` is cascaded to `TERMINATED`, and no new election may thereafter be submitted under the plan.

### 3.2. Census, Compensation, and Credited Service

A `BenefitsAdministrator` populates the census by adding a `Participant`. The create payload names the owning plan through `plan_id` and supplies the participant's `ssn_last4` (the last four digits of the SSN, unique within the plan), `date_of_birth`, and `hire_date`, all dates in ISO-8601 form. Service credit accrues from the hire date forward. A new participant starts with `employment_status` of `ACTIVE` and, before any service has accrued, `vesting_status` of `UNVESTED`.

A participant carries **two independent status axes** that never gate one another. The employment axis runs `ACTIVE → TERMINATED → RETIRED`, with `DECEASED` reachable from any of those. The vesting axis runs `UNVESTED → PARTIALLY_VESTED → FULLY_VESTED` and is recomputed purely from credited service. The two are genuinely orthogonal: a `TERMINATED` participant may already be `FULLY_VESTED`, and an `ACTIVE` participant may still be `UNVESTED`. Termination of employment is a `BenefitsAdministrator` action that moves a participant from `ACTIVE` to `TERMINATED`; it is allowed only from `ACTIVE` (otherwise `ERR_INVALID_STATE`), and the supplied `termination_date` must be on or after the participant's `hire_date` (otherwise `ERR_INVALID_REQUEST`). Recording death is a `BenefitsAdministrator` action that moves the participant to `DECEASED` from `ACTIVE`, `TERMINATED`, or `RETIRED`, and as a cascade drives every `IN_PAY` benefit payment for that participant to `TERMINATED`. The participant does not reach `RETIRED` by a direct call; that transition happens only as a side effect of an election commencing, described in §3.4.

Credited service is captured in the computed `credited_service_years` field, a whole-plus-fractional count of years. It is computed by measuring from `hire_date` to a measurement date: for a participant who has reached `TERMINATED`, the measurement date is the `termination_date`, and the value is frozen there; for everyone else it is the system as-of date of 2025-01-01. The raw elapsed span is the number of days between hire and measurement divided by 365.25, then truncated **down** to the nearest half-year. To that rounded elapsed figure the system adds the signed sum of every `ServiceCreditAdjustment` recorded for the participant, and the final `credited_service_years` is the larger of zero and that total — it never goes negative. Each time credited service is recomputed — on participant creation, on termination, on a new compensation row, and on a new service adjustment — the vesting axis is recomputed from it.

A `ServiceCreditAdjustment` is an append-only correction that a `BenefitsAdministrator` records against a participant. It names the participant through `participant_id`, classifies itself through `adjustment_kind` (one of `MILITARY_BUYBACK`, `BREAK_IN_SERVICE`, or `PRIOR_SERVICE_GRANT`), and carries `delta_service_years`, a signed change in half-year increments — positive for a grant, negative for a break. Because it is an event rather than an editable record, the adjustment's `applied` flag is always true at creation and the row simply feeds the next credited-service recompute. Note the ordering: the elapsed span is rounded down to a half-year *first*, and the adjustment deltas are added *after* that rounding, with the floor at zero applied last.

The vesting recompute reads `credited_service_years` and applies a graded 3-to-7 schedule, writing both `vested_pct` and `vesting_status`. When credited service is below 3 years the participant is `UNVESTED` with a vested fraction of 0.00. When it is at least 3 years but below 7 years the participant is `PARTIALLY_VESTED`, and the vested fraction is 0.20 multiplied by the quantity (the whole-year floor of credited service, minus 2). When credited service is 7 years or more the participant is `FULLY_VESTED` with a vested fraction of 1.00. The `vested_pct` is rounded to two decimal places.

### 3.3. Recognized Compensation and the Two Benefit Bases

Compensation feeds the benefit formula, and a `BenefitsAdministrator` records it one year at a time as an `AnnualCompensation` row. The payload names the participant through `participant_id`, the calendar year through `plan_year` (unique per participant), and the gross W-2 figure through `gross_comp_cents`. On creation the system computes `capped_comp_cents` as the lesser of `gross_comp_cents` and the IRC annual compensation limit, which is 33,000,000 cents (that is, $330,000). The capped figure, not the gross, is the compensation that benefit formulas recognize. Adding a compensation row recomputes the participant's final-average-pay figure and cash-balance account as appropriate.

For a final-average-pay plan, the participant's `final_average_pay_cents` is the average of the highest three *consecutive* plan years by `capped_comp_cents`. The system orders the participant's compensation rows by `plan_year` ascending; when there are at least three rows it considers every window of three consecutive years, takes the window whose summed capped compensation is greatest (breaking ties toward the earliest starting `plan_year`), and divides that sum by three, rounding half-up to whole cents. When there are fewer than three rows it averages all the rows that exist — the sum of their capped compensation divided by the row count, rounded half-up. This figure is recomputed whenever compensation rows change and is also confirmed at election submission for final-average-pay plans.

For a cash-balance plan, the participant instead carries a `cash_balance_account_cents` — a running hypothetical account built from pay credits (each year's capped compensation multiplied by the plan's pay-credit rate) accumulated and interest-credited forward to the benefit commencement date. This account is the basis the cash-balance benefit formula annuitizes.

### 3.4. The Retirement Election: Form, Reduction, and Valuation

The heart of the system is the `BenefitElection`. A `BenefitsAdministrator` drafts one against a participant; the draft payload names the participant through `participant_id`, picks the `payment_form` (one of `SINGLE_LIFE`, `JOINT_AND_SURVIVOR`, or `LUMP_SUM`), and sets the elected `annuity_start_date`. For a joint-and-survivor form the payload additionally requires `js_survivor_pct` — the survivor continuation fraction, which must be 0.50, 0.75, or 1.00 — and `spouse_date_of_birth`, the contingent annuitant's date of birth; both are ignored for the other forms. A drafted election also records the denormalized owning-plan id `plan_id`, copied from the participant. A fresh election has `status` of `DRAFT`.

The election machine branches on form and carries a revision loop. Submitting a `DRAFT` election is a `BenefitsAdministrator` action that first enforces a stack of eligibility gates, evaluated in the following order. The participant's `employment_status` must be `TERMINATED`, or the submission is rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE`. The participant's `vesting_status` must be `FULLY_VESTED`, or the submission is rejected with `ERR_PARTICIPANT_NOT_VESTED`. For a `LUMP_SUM` form, the plan's `funding_posture` must not be `FROZEN`, or the submission is rejected with `ERR_FUNDING_RESTRICTED`. Finally, the `annuity_start_date` must imply an attained age of at least 55 — the early-retirement age — or the submission is rejected with `ERR_BENEFIT_NOT_AVAILABLE`.

When those gates pass, submission moves the election to `SUBMITTED` and runs the benefit math, stamping the submitting operator's `X-User-ID` into `submitted_by_user_id`. It computes the single-life accrued monthly benefit into `gross_accrued_monthly_cents`, then the form-adjusted amount into `js_reduced_monthly_cents`, and for a `LUMP_SUM` form it additionally computes `lump_sum_value_cents` and `relative_value_pct`. After landing in `SUBMITTED`, the form dictates routing: a `JOINT_AND_SURVIVOR` or `LUMP_SUM` election is automatically advanced by the system from `SUBMITTED` to `SPOUSAL_CONSENT_PENDING`, because those forms require spousal consent; a `SINGLE_LIFE` election (the default qualified joint-and-survivor-equivalent form that needs no waiver) stays at `SUBMITTED` awaiting direct approval.

**Computing `gross_accrued_monthly_cents` (dual variant).** This figure is keyed on the plan's `benefit_formula_type`. For a `FINAL_AVERAGE_PAY` plan it is the product of `final_average_pay_cents`, the plan's `fap_accrual_rate`, the participant's `credited_service_years`, and the participant's `vested_pct`, all divided by 12, rounded half-up to whole cents. For a `CASH_BALANCE` plan it is the participant's `cash_balance_account_cents` multiplied by `vested_pct`, divided by the annuity conversion factor of 12.0, then divided by 12, rounded half-up to whole cents.

**Computing `js_reduced_monthly_cents` (the survivor reduction).** For a `SINGLE_LIFE` or `LUMP_SUM` form there is no reduction and this equals `gross_accrued_monthly_cents`. For a `JOINT_AND_SURVIVOR` form the system first takes the participant's and spouse's attained ages in whole years as of the `annuity_start_date` and forms the age difference as the participant's age minus the spouse's age (which may be negative). It then builds a reduction factor starting from a base of 1.00, subtracting the product of `js_survivor_pct` and a survivor load of 0.12, and subtracting the product of the age difference and an age-difference load of 0.005 per year the participant is older than the spouse. The factor is clamped to lie within 0.70 and 1.00 inclusive. The reduced amount is `gross_accrued_monthly_cents` multiplied by that clamped factor, rounded half-up to whole cents.

**Computing `lump_sum_value_cents` and `relative_value_pct` (dual basis, LUMP_SUM only).** Both figures value the same single-life monthly benefit on two different bases. The system first annualizes the benefit as `gross_accrued_monthly_cents` multiplied by 12. The annuity comparator present value is that annual amount multiplied by the straight-life annuity factor of 12.5, rounded half-up to whole cents — call this the comparator present value. The lump-sum value applies a 417(e) segment factor selected by the participant's attained whole-year age at the `annuity_start_date`: at age 65 or above the factor is 12.4; at age 60 through 64 it is 11.9; at age 55 through 59 it is 10.8. The `lump_sum_value_cents` is the annual amount multiplied by the selected segment factor, rounded half-up to whole cents. The `relative_value_pct` is `lump_sum_value_cents` divided by the comparator present value, rounded to four decimal places. Because the 55-through-59 segment factor is materially smaller than the comparator factor, a lump sum elected in that age band produces a relative value below the floor and will fail the relative-value test at approval.

Approval is the segregation-of-duties checkpoint and it has two entry paths. A `SINGLE_LIFE` election is approved directly from `SUBMITTED`; this path requires only that the approver's `X-User-ID` differ from the recorded `submitted_by_user_id`, or it is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `JOINT_AND_SURVIVOR` or `LUMP_SUM` election is approved from `SPOUSAL_CONSENT_PENDING`, and that path enforces three checks in order: there must exist a `SpousalConsent` for the election with `waives_qjsa` equal to true, or the approval is rejected with `ERR_SPOUSAL_CONSENT_REQUIRED`; then, for a `LUMP_SUM` form, the `relative_value_pct` must be at least the relative-value floor of 0.95, or the approval is rejected with `ERR_RELATIVE_VALUE_FAILED`; and in both cases the approver's `X-User-ID` must differ from `submitted_by_user_id`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either path lands the election in `APPROVED`.

A spousal consent is recorded by a `BenefitsAdministrator` as a `SpousalConsent` linked to the election. Its payload carries `consenting_spouse_dob` (which must match the election's `spouse_date_of_birth`), a `notary_reference` string evidencing the witnessed signature, and the boolean `waives_qjsa`, which is true when the spouse waives the qualified joint-and-survivor annuity so a non-QJSA form may proceed.

An `APPROVED` election can be re-opened for revision by a `BenefitsAdministrator`, moving it from `APPROVED` back to `DRAFT` and clearing the computed benefit fields so the election can be revised and resubmitted; re-opening is allowed only while no `BenefitPayment` has yet been created for the election (otherwise `ERR_INVALID_STATE`). An election may also be rejected by a `BenefitsAdministrator` from either `SUBMITTED` or `SPOUSAL_CONSENT_PENDING`, moving it to the terminal `REJECTED` state.

Commencement is the final election step and it is rich in consequences. A `BenefitsAdministrator` commences an `APPROVED` election, moving it to the terminal `COMMENCED` state. Before it may proceed, every `QdroAward` for the participant must be in `QUALIFIED` or `REJECTED` state — none may still be `DRAFT` or `SUBMITTED` — or the request is rejected with `ERR_QDRO_PENDING`. The `annuity_start_date` need not be on or before the current date; commencement may be prospective. Commencement creates a `BenefitPayment` in `PENDING_SETUP` with its `base_monthly_cents` computed by the payment-setup rule (which nets out qualified QDRO carve-outs, §3.5), and it cascades the participant from `TERMINATED` to `RETIRED`.

### 3.5. QDRO Splits and the Carve-Out to an Alternate Payee

A qualified domestic relations order may divert part of a participant's benefit to an alternate payee, modeled as a `QdroAward`. A `BenefitsAdministrator` drafts one against a participant; the payload names the participant through `participant_id`, classifies the recipient through `alternate_payee_kind` (one of `SPOUSE`, `FORMER_SPOUSE`, or `CHILD`), and chooses a `split_method`. A `PERCENTAGE` split carves a marital-share fraction supplied as `award_pct` (a value greater than 0 and at most 1); a `SHARED_INTEREST` split carves a fixed monthly amount supplied as `award_fixed_monthly_cents`. The award also records the denormalized `plan_id` from the participant. A fresh award has `status` of `DRAFT`.

The award machine carries an amend loop. Submitting a `DRAFT` award for qualification review is a `BenefitsAdministrator` action; it requires that a `PERCENTAGE` award carry an `award_pct` in the interval greater than 0 and at most 1, and that a `SHARED_INTEREST` award carry an `award_fixed_monthly_cents` greater than 0 — a violation of either yields `ERR_INVALID_REQUEST` — and it moves the award to `SUBMITTED`. Qualifying a `SUBMITTED` award is the action that locks in the split; it requires that no `COMMENCED` election yet exist for the participant (otherwise `ERR_QDRO_TOO_LATE`) and, for a `PERCENTAGE` split, that the cumulative `award_pct` of already-`QUALIFIED` percentage awards plus this award's `award_pct` not exceed 1.0 (otherwise `ERR_QDRO_OVER_ALLOCATED`); on success it moves the award to the terminal `QUALIFIED` state and computes its `alternate_payee_monthly_cents`. A `SUBMITTED` award may instead be rejected by a `BenefitsAdministrator`, moving it to `REJECTED`; a `REJECTED` award may be re-opened for amendment, moving it from `REJECTED` back to `DRAFT` and clearing `alternate_payee_monthly_cents` so the order can be corrected and resubmitted.

**Computing the carve-outs and the participant's net.** When awards are qualified, the carve to each alternate payee is computed by walking the participant's `QUALIFIED` awards in order of their `created_at` ascending (and never by `id`; ties break on `created_at` and then on `plan_year`). The walk starts from the election's `js_reduced_monthly_cents` as the base and tracks a running remaining amount initialized to that base. For each award in order: a `PERCENTAGE` award carves `award_pct` of the *original* base (not of the remaining amount), rounded half-up to whole cents; a `SHARED_INTEREST` award carves the lesser of its `award_fixed_monthly_cents` and the current remaining amount. The carve is written to that award's `alternate_payee_monthly_cents` and subtracted from the running remaining amount.

The participant's own monthly figure at payment setup is computed when the election commences. The `base_monthly_cents` on the new payment is the election's `js_reduced_monthly_cents` minus the sum of `alternate_payee_monthly_cents` across the participant's `QUALIFIED` awards, with the result floored at zero so it never goes negative.

### 3.6. Funded-Status Filings and the Actuary's Certification

Funded status is established through the `PlanYearFiling`, which a `PlanActuary` drafts. The create payload names the plan through `plan_id`, the year through `plan_year` (unique per plan), and supplies `plan_assets_cents` (the actuarial value of plan assets) and `funding_target_cents` (the present value of accrued liabilities). On creation the filing is `DRAFT` and its `aftap_pct` is computed as `plan_assets_cents` divided by `funding_target_cents`, rounded to four decimal places.

Certifying a `DRAFT` filing is the `PlanActuary` capability that activates it. The certify request carries `expected_plan_version` for the optimistic-concurrency check of §2.7, and it requires that the filing's `funding_target_cents` be greater than zero (otherwise `ERR_INVALID_REQUEST`). On success the filing moves to `CERTIFIED`, its `aftap_pct` is (re)computed, and the plan's `funding_posture` is re-derived from this and any prior certified filings per the threshold rules in §2.5. The plan's `latest_certified_filing_id` is set to this filing when it carries the greatest `plan_year` among certified filings, and the plan's `version` is incremented by one. Certifying a filing also supersedes any earlier certified filing: when a newly certified filing carries a `plan_year` greater than or equal to that of an existing `CERTIFIED` filing, the older one is moved by the system to the terminal `SUPERSEDED` state and the plan's posture is re-derived from the superseding filing.

### 3.7. PBGC Premium Filings

The plan owes the PBGC an annual premium, captured as a `PbgcPremiumFiling`. Either a `PlanActuary` or a `PlanSponsor` may create one; the payload names the plan through `plan_id`, the year through `premium_year` (unique per plan), the headcount through `participant_count`, and the unfunded vested benefits through `unfunded_vested_benefits_cents`. On creation the system computes the premium in three parts. The `flat_rate_premium_cents` is `participant_count` multiplied by the flat rate of 10,100 cents per participant (that is, $101 a head). The `variable_rate_premium_cents` is the variable-rate charge on unfunded vested benefits subject to a statutory per-participant cap: the system first multiplies `unfunded_vested_benefits_cents` by the variable rate of 0.0052 and rounds half-up to whole cents, then takes the lesser of that figure and the cap, which is `participant_count` multiplied by 65,200 cents per participant. The cap is applied **after** the rate is computed, never before. The `total_premium_cents` is the sum of `flat_rate_premium_cents` and `variable_rate_premium_cents`.

### 3.8. Paying the Benefit: Setup, Suspension, and COLA

A `BenefitPayment` comes into being when an election commences and begins in `PENDING_SETUP`. It records its lineage through `election_id`, `participant_id`, and `plan_id`, and carries the computed `base_monthly_cents` from payment setup along with `current_monthly_cents` (the amount actually being paid) and a `cola_applied_count` that begins at 0.

Activating a `PENDING_SETUP` payment is a `BenefitsAdministrator` action that begins payment, moving it to `IN_PAY`. Activation requires that the owning election be in `COMMENCED` state (otherwise `ERR_INVALID_STATE`) and that the participant's `employment_status` be `RETIRED` (otherwise `ERR_PARTICIPANT_NOT_ELIGIBLE`); on success it sets `current_monthly_cents` equal to `base_monthly_cents`. An `IN_PAY` payment can be suspended by a `BenefitsAdministrator`, moving it to `SUSPENDED`, and a `SUSPENDED` payment can be resumed, moving it back to `IN_PAY`; this suspend/resume cycle has no further side effects.

Applying a cost-of-living adjustment is a `BenefitsAdministrator` action permitted only while the payment is `IN_PAY` — it is a self-transition that keeps the payment in `IN_PAY`. It requires that the payment currently be `IN_PAY` (otherwise `ERR_INVALID_STATE`) and that the plan's `cola_pct` be greater than zero (otherwise `ERR_NO_COLA_CONFIGURED`). Each application grows `current_monthly_cents` by setting it to its current value multiplied by the quantity (1 plus the plan's `cola_pct`), rounded half-up to whole cents, and increments `cola_applied_count` by one. Because each adjustment compounds on the already-grown amount, repeated COLAs build on one another.

A payment leaves the system as `TERMINATED`. This happens by cascade rather than by direct call: when the participant is recorded `DECEASED`, or when the plan begins `TERMINATING`, every `IN_PAY` or `SUSPENDED` payment for that participant or plan is driven to the terminal `TERMINATED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that transition or otherwise modify an existing resource return `200 OK`. List and retrieval operations return `200 OK`. The request body, computed outputs, and side effects of each endpoint are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a pension plan | PlanSponsor |
| GET | `/plans/{planId}` | Get a pension plan | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/{planId}/terminate` | Begin standard plan termination | PlanSponsor |
| POST | `/plans/participants` | Add a participant to the census | BenefitsAdministrator |
| GET | `/plans/participants/{participantId}` | Get a participant | PlanSponsor, PlanActuary, BenefitsAdministrator |
| GET | `/plans/participants` | List participants | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/participants/{participantId}/terminate` | Record employment termination | BenefitsAdministrator |
| POST | `/plans/participants/{participantId}/record-death` | Record participant death | BenefitsAdministrator |
| POST | `/plans/compensation` | Add an annual compensation record | BenefitsAdministrator |
| GET | `/plans/participants/{id}/compensation` | List a participant's compensation rows | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/service-adjustments` | Record a credited-service adjustment | BenefitsAdministrator |
| GET | `/plans/participants/{id}/service-adjustments` | List a participant's service-credit adjustments | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/filings` | Create a 5500/AFTAP draft filing | PlanActuary |
| GET | `/plans/filings/{filingId}` | Get a plan-year filing | PlanSponsor, PlanActuary, BenefitsAdministrator |
| GET | `/plans/filings` | List plan-year filings | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/filings/{filingId}/certify` | Certify the filing (OCC on plan version) | PlanActuary |
| POST | `/plans/premiums` | Create a PBGC premium filing draft | PlanActuary, PlanSponsor |
| GET | `/plans/premiums/{premiumId}` | Get a PBGC premium filing | PlanSponsor, PlanActuary, BenefitsAdministrator |
| GET | `/plans/premiums` | List PBGC premium filings | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/elections` | Draft a retirement benefit election | BenefitsAdministrator |
| GET | `/plans/elections/{electionId}` | Get a benefit election | PlanSponsor, PlanActuary, BenefitsAdministrator |
| GET | `/plans/participants/{id}/elections` | List a participant's elections | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/submit` | Submit the election for review | BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/approve` | Approve the election | BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/reject` | Reject the election | BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/reopen` | Re-open an approved election for revision | BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/commence` | Commence the benefit | BenefitsAdministrator |
| POST | `/plans/elections/{electionId}/spousal-consent` | Record a notarized spousal consent | BenefitsAdministrator |
| GET | `/plans/elections/{id}/spousal-consent` | List spousal consents for an election | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/qdros` | Draft a QDRO award | BenefitsAdministrator |
| GET | `/plans/participants/{id}/qdros` | List a participant's QDRO awards | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/qdros/{qdroId}/submit` | Submit a QDRO for qualification review | BenefitsAdministrator |
| POST | `/plans/qdros/{qdroId}/qualify` | Qualify the QDRO | BenefitsAdministrator |
| POST | `/plans/qdros/{qdroId}/reject` | Reject the QDRO as defective | BenefitsAdministrator |
| POST | `/plans/qdros/{qdroId}/amend` | Re-open a rejected QDRO for amendment | BenefitsAdministrator |
| GET | `/plans/payments/{paymentId}` | Get a benefit payment | PlanSponsor, PlanActuary, BenefitsAdministrator |
| GET | `/plans/payments` | List benefit payments | PlanSponsor, PlanActuary, BenefitsAdministrator |
| POST | `/plans/payments/{paymentId}/activate` | Activate a pending payment | BenefitsAdministrator |
| POST | `/plans/payments/{paymentId}/suspend` | Suspend an in-pay benefit | BenefitsAdministrator |
| POST | `/plans/payments/{paymentId}/resume` | Resume a suspended benefit | BenefitsAdministrator |
| POST | `/plans/payments/{paymentId}/apply-cola` | Apply one COLA increase | BenefitsAdministrator |

The participant list endpoint accepts the optional query parameters `plan_id`, `employment_status`, and `vesting_status`. The filing list accepts `plan_id` and `status`. The premium list accepts `plan_id` and `premium_year`. The election sub-resource list accepts `status`, as does the QDRO sub-resource list. The benefit-payment list accepts `election_id`, `participant_id`, `plan_id`, and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PARTICIPANT_NOT_ELIGIBLE` | 409 |
| `ERR_PARTICIPANT_NOT_VESTED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_FUNDING_RESTRICTED` | 409 |
| `ERR_SPOUSAL_CONSENT_REQUIRED` | 409 |
| `ERR_RELATIVE_VALUE_FAILED` | 409 |
| `ERR_QDRO_TOO_LATE` | 409 |
| `ERR_QDRO_OVER_ALLOCATED` | 409 |
| `ERR_QDRO_PENDING` | 409 |
| `ERR_BENEFIT_NOT_AVAILABLE` | 409 |
| `ERR_NO_COLA_CONFIGURED` | 409 |
| `ERR_STALE_VERSION` | 412 |
