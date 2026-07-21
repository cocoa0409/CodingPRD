# Self-Funded TPA API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Self-Funded & Captive Plan Third-Party Administrator (TPA) API. The platform administers employer-sponsored, self-funded health plans on behalf of their sponsors: it registers plans and the stop-loss (reinsurance) coverage that caps their exposure, enrolls members, adjudicates and reprices medical claims against network and out-of-network pricing rules, tracks per-member deductible and out-of-pocket accumulators, funds and disburses claim payments through check-runs, recognizes specific and aggregate stop-loss reimbursements, and produces year-end provider 1099 reporting.

The system's defining characteristic is that money and eligibility must reconcile at every step. A single claim adjudication reprices billed charges, allocates member cost-share through a deductible-and-coinsurance waterfall, advances several running accumulators, and may cascade into a specific stop-loss reimbursement — all as one atomic operation. Downstream, releasing a check-run debits a shared funding balance under optimistic concurrency control and, upon payment, feeds provider year-to-date totals that later drive tax reporting. Because the same underlying dollars flow through claims, funds, reinsurance recoveries, and reports, the API enforces strict separation of duties across administrator, claims-examiner, fund-manager, and auditor roles, and it treats every computed balance as a derived field that must remain consistent with the events that produced it.

Every monetary figure in this system is denominated and stored in integer **cents**. There are no floating-point currency amounts anywhere in the persisted model or the API surface.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This authentication check is the very first gate applied to any request, before any other consideration.

The system recognizes exactly four roles, spelled precisely as follows: `TPAAdmin`, `ClaimsExaminer`, `FundManager`, and `Auditor`. Once a request is authenticated, the system verifies that the declared role is permitted to perform the requested operation; if it is not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Broadly, a `TPAAdmin` configures plans, providers, members, stop-loss policies, and lasers, and drives the system's logical clock; a `ClaimsExaminer` submits, pends, denies, adjudicates, and reverses claims; a `FundManager` opens and funds accounts and manages check-runs; and an `Auditor` performs read-only reporting plus 1099 generation. Aggregate settlement is shared between `TPAAdmin` and `Auditor`. Every role may perform all GET reads. The precise authorization for each endpoint is given in the endpoint table in Section 4.

For all four roles, `X-User-ID` is an **opaque operator identifier** and is not tied to any persisted entity: the server never compares it to any resource's `id` for ownership purposes. It may, however, be recorded where the workflow calls for it. Specifically, when a `ClaimsExaminer` pends a claim, the server records that examiner's `X-User-ID` on the claim as `pended_by_user_id`, and later uses that recorded value to enforce separation of duties at adjudication time — but this is a stored audit value, not an ownership key.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from the server's wall-clock (real) time and therefore independent of the logical clock of Section 2.8.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Both parameters are optional on every list endpoint. A supplied `limit` below 1 or above 100 is clamped into that range rather than rejected, and a negative `offset` is floored to 0; a `limit` or `offset` that is not an integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order, ties being broken by the order in which the resources were created. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in this system — plans, providers, members, stop-loss policies, lasers, claims, fund accounts, check-runs, stop-loss reimbursements, and 1099 forms — is a first-class resource carrying a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set from the logical clock (Section 2.8) when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed from the logical clock (Section 2.8) on every mutation of the resource.
- `version`: an integer that starts at 1 and increments by one on every mutation of the resource. It is the basis for the optimistic concurrency control described below.

Whenever the server mutates a resource — including mutations to purely computed fields such as a member's accumulators, a provider's `ytd_paid_cents`, or a fund account's balance — it refreshes that resource's `updated_at` and increments its `version`. These derived-field updates are genuine mutations, not silent side edits.

### 2.5. Optimistic Concurrency Control

The system protects the shared plan funding balance from lost updates using optimistic concurrency control (OCC) keyed on the `version` of the `FundAccount`. Releasing a check-run is the single guarded write. The release request must carry `expected_fund_account_version`, which is the `version` of the target fund account that the client last observed. Before the release is applied, the server compares `expected_fund_account_version` against the fund account's current `version`. If they do not match — because another check-run has already been released against the same fund, or a deposit has posted, since the client last read it — the release is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from disbursing against a funding view it no longer holds. This is purely a stale-version check on the parent fund account; it does not depend on any assumption about requests arriving at the same time. No other endpoint takes a version field, and endpoints outside of check-run release perform no OCC check.

### 2.6. Monetary Values and Precision

All amounts are integer cents; there are no fractional cents and no floating-point currency values. Where a calculation multiplies a cents amount by a ratio — a PPO discount or a coinsurance share — the product is rounded to a whole number of cents using the **round-half-up** method (a result with a fractional part of exactly one-half rounds up to the next whole cent). The specific point at which rounding is applied is fixed per calculation and is described with each formula in Section 3; for repricing in particular, rounding happens on each line item before the lines are summed, never on the sum. Ratios supplied as input, such as `ppo_discount_pct` and `plan_coinsurance_pct`, are values between 0 and 1 inclusive and retain their input precision.

### 2.7. Request Validation and Error Precedence

When more than one rule could reject a request, the system applies them in a fixed order of precedence and returns the error for the first rule that fails. The precedence ladder, from highest to lowest, is:

1. **Authentication** — headers present and valid, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role may perform the operation, else `ERR_UNAUTHORIZED`.
3. **Existence** — every resource referenced by a path identifier or a request-body foreign key exists (see the not-found codes below).
4. **Well-formedness and state** — the request body is well-formed and the target entity is in a state that permits the transition. A malformed body (missing required field, wrong type or enum value, or a negative amount where a non-negative one is required) yields `ERR_VALIDATION` (HTTP 400); a target entity in the wrong state yields `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is named for that operation.
5. **Concurrency** — the fund-account OCC check on check-run release, else `ERR_STALE_VERSION`.
6. **Separation-of-duties and duplicate safety** — the segregation check and the duplicate-claim check at adjudication.
7. **Referential business rules** — for example, a laser's member belonging to the policy's plan.
8. **Window/overlap business constraints** — stop-loss policy period overlap and laser window overlap.
9. **Temporal eligibility** — member coverage eligibility and plan run-out windows at adjudication.
10. **Fiscal sufficiency** — funding sufficiency for a release and the aggregate attachment threshold for settlement.

Existence is checked left to right along the URL. When a path names a nested or referenced resource, the system validates each identifier in order and returns the not-found error for the first one that does not resolve before looking at anything deeper. The existence codes are: `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_STOP_LOSS_POLICY_NOT_FOUND`, `ERR_LASER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FUND_ACCOUNT_NOT_FOUND`, `ERR_CHECK_RUN_NOT_FOUND`, `ERR_REIMBURSEMENT_NOT_FOUND`, and `ERR_FORM_1099_NOT_FOUND`, each returned with HTTP 404. For example, submitting a claim that names a non-existent member fails with `ERR_MEMBER_NOT_FOUND`, and generating a 1099 for a non-existent provider fails with `ERR_PROVIDER_NOT_FOUND`.

### 2.8. The Logical Clock

Time in this system is a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly moved it stays at that default and never falls back to real time. A `TPAAdmin` may advance the clock to a supplied instant by providing a `to_iso8601` value to the administrative clock-setting capability. The logical clock is the reference for every time-sensitive rule: the run-out window after plan termination, the `paid_at` stamped on a claim when its check-run releases, the `released_at` stamped on a check-run, and the calendar year used to bucket payments for 1099 reporting all read from this clock; the `created_at` and `updated_at` on every resource likewise read from it. Client-supplied date and datetime strings — service dates, coverage and policy windows, termination dates, and the clock target — are persisted and echoed back exactly as submitted, without reformatting or normalization.

## 3. Business Logic & Workflows

### 3.1. Plan Configuration and Lifecycle

A `TPAAdmin` establishes a self-funded plan by supplying the sponsor's identity and the benefit design: `sponsor_name`, `sponsor_tax_id`, the plan-year boundaries `plan_year_start` and `plan_year_end`, the per-member annual `individual_deductible_cents` and `oop_max_cents`, and the plan's coinsurance share `plan_coinsurance_pct` (a value from 0 to 1 giving the fraction the plan pays after the deductible is met — for example, 0.80 means the plan pays 80 percent). The admin may also set `run_out_days`, the number of days after termination during which claims incurred before termination may still be adjudicated; when omitted it defaults to 90 days. A newly created plan begins in `ACTIVE` status, with `terminated_at` unset.

A plan's lifecycle runs `ACTIVE → TERMINATED → CLOSED`. Terminating an `ACTIVE` plan — a `TPAAdmin` action — requires the plan to currently be `ACTIVE`; it records the supplied `termination_date` onto the plan's `terminated_at` and moves the plan to `TERMINATED`, which opens the run-out window. Closing a plan moves it from `TERMINATED` to the terminal `CLOSED` state, and is only permitted once the run-out window has fully elapsed — that is, when the current logical-clock time is strictly later than `terminated_at` plus `run_out_days` days. A close attempted while the plan is not `TERMINATED`, or while the run-out window has not yet elapsed, is rejected with `ERR_INVALID_STATE`.

### 3.2. Providers, Members, and Accumulators

A `TPAAdmin` registers a provider with its `name`, its taxpayer identification `tax_id` (used later to aggregate payments for 1099 reporting), its `npi`, and whether it participates in the PPO network via the `in_network` flag. In-network providers may carry a `ppo_discount_pct`, the repricing discount from 0 to 1 applied to their billed charges; when omitted it defaults to 0. Each provider also maintains a computed `ytd_paid_cents`, the cumulative plan-paid amount disbursed to that provider through released check-runs in the current tax year, which begins at 0 and moves only as check-runs release and void.

Members are enrolled under a plan by a `TPAAdmin`, who provides the owning `plan_id`, the member's `first_name` and `last_name`, and the `coverage_effective_date` when coverage begins. An optional `coverage_term_date` may be supplied; when omitted (null) the coverage is open-ended. A new member starts `ACTIVE`. Each member carries four running accumulators, all starting at 0: `deductible_met_cents` (deductible satisfied this plan year), `oop_met_cents` (out-of-pocket satisfied this plan year), `member_plan_paid_ytd_cents` (cumulative plan-paid across this member's adjudicated claims, the basis for specific stop-loss), and `spec_reimbursed_cents` (specific stop-loss already recognized for this member). Terminating a member's coverage is a `TPAAdmin` action available only while the member is `ACTIVE`; it records the supplied `termination_date` onto the member's `coverage_term_date` and moves the member to `TERMINATED`. Members may be listed and filtered by `plan_id`.

### 3.3. Stop-Loss Policies and Lasers

Stop-loss (reinsurance) coverage caps the plan's exposure. A `TPAAdmin` creates a policy under a `plan_id` with a `carrier_name`, a `contract_basis` of either `PAID` or `INCURRED` (which governs how the aggregate settlement counts claims), the policy period bounded by `effective_date` and `expiry_date`, the per-member `specific_deductible_cents` (the individual attachment point), and the plan-wide `aggregate_attachment_cents`. The policy also tracks two computed running totals, both starting at 0: `total_specific_reimbursed_cents` and `total_aggregate_reimbursed_cents`. A policy is created in `DRAFT` status and follows the lifecycle `DRAFT → ACTIVE → SETTLED`.

Activating a policy is only permitted from `DRAFT`, and enforces that its period does not overlap any other `ACTIVE` policy on the same plan. The period is treated as the half-open interval running from `effective_date` inclusive up to but not including `expiry_date`; two policies conflict when these half-open intervals overlap, but adjacency is allowed — one policy's `expiry_date` may equal the next policy's `effective_date`. A conflicting activation is rejected with `ERR_POLICY_PERIOD_OVERLAP`. Once activated the policy is `ACTIVE`; the transition to `SETTLED` occurs through aggregate settlement, described in Section 3.7.

A **laser** raises the specific deductible carved out for one high-cost member under a reinsurance policy. A `TPAAdmin` carves a laser by supplying the `stop_loss_policy_id`, the `member_id`, the raised `laser_deductible_cents`, and the laser window bounded by `effective_date` and `expiry_date`. A laser may only be carved on a policy that is currently `ACTIVE`; carving against a `DRAFT` or `SETTLED` policy is rejected with `ERR_POLICY_NOT_ACTIVE`. The laser's member must belong to the same plan as the laser's policy; a mismatch is rejected with `ERR_LASER_MEMBER_MISMATCH` (HTTP 422). A new laser window may not overlap an existing laser for the same policy-and-member pair; here the window is treated as a closed interval from `effective_date` through `expiry_date` inclusive, and even touching endpoints conflict — the new laser's `effective_date` must be strictly greater than the prior laser's `expiry_date`, otherwise the request is rejected with `ERR_LASER_WINDOW_OVERLAP`. Lasers may be listed and filtered by `stop_loss_policy_id` and/or `member_id`.

### 3.4. Claim Intake, Repricing, and Member Cost-Share

A `ClaimsExaminer` submits a claim naming the `member_id`, the `provider_id`, the `service_date` on which the service was incurred, and the `billed_lines` — an array of line items, each an object carrying a `billed_cents` amount and an optional `description`. The `billed_lines` array must be present and non-empty; an absent or empty array is rejected with `ERR_VALIDATION`, and each line is stored and echoed as an object with both `billed_cents` and `description`, the `description` defaulting to null when omitted. An optional `ucr_amount_cents` may accompany the claim, giving the usual-customary-reasonable cap used when repricing out-of-network services. On submission the server computes `billed_total_cents` as the sum of `billed_cents` across all `billed_lines`, and the claim begins in `SUBMITTED` status. Claims may be listed and filtered by `member_id`, `provider_id`, and/or `status`.

A submitted claim may be **pended** for review by a `ClaimsExaminer`, moving it `SUBMITTED → PENDED` and recording the pending examiner's `X-User-ID` onto `pended_by_user_id`. A claim may be **denied** from either `SUBMITTED` or `PENDED`, moving it to the terminal `DENIED` state and recording the supplied `denial_reason`.

**Adjudication** is the pivotal operation and may be reached from `SUBMITTED`, from `PENDED`, or again from `REVERSED` (a revision loop). A `ClaimsExaminer` performs it. Beyond the state check, adjudication enforces several guards. When adjudicating a `PENDED` claim, the acting examiner's `X-User-ID` must differ from the `pended_by_user_id` recorded when it was pended; if the same user attempts both, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). No adjudication may proceed if another claim already in `ADJUDICATED` or `PAID` status shares the same `member_id`, `provider_id`, `service_date`, and `billed_total_cents`; such a twin is rejected as `ERR_DUPLICATE_CLAIM`. The member must be `ACTIVE` and the `service_date` must fall on or after the member's `coverage_effective_date` and, when a `coverage_term_date` is set, on or before it (an open-ended coverage imposes no upper bound); otherwise the claim is rejected with `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 422). If the plan is `TERMINATED`, the claim may still be adjudicated only when its `service_date` is on or before the plan's `terminated_at` and the current logical-clock time is on or before `terminated_at` plus `run_out_days` days; a claim incurred after termination, or adjudicated after the run-out window has passed, is rejected with `ERR_RUN_OUT_CLOSED` (HTTP 422). These guards follow the global precedence of Section 2.7: the state check first, then separation-of-duties and duplicate detection, then eligibility and run-out.

Once the guards pass, adjudication reprices the claim to an `allowed_amount_cents`. **Repricing depends on the provider's network status.** For an in-network provider, each line's allowed amount is the line's `billed_cents` multiplied by one minus the provider's `ppo_discount_pct`, rounded half-up to whole cents, and the `allowed_amount_cents` is the sum of those per-line rounded results — the rounding is applied to each line before summing, not to the total. For an out-of-network provider, the PPO discount is ignored entirely and the `allowed_amount_cents` is the lesser of the claim's `billed_total_cents` and its `ucr_amount_cents`. When no `ucr_amount_cents` was supplied (it is null), no cap applies and the `allowed_amount_cents` is simply the `billed_total_cents`.

Immediately after repricing, the system allocates the member's cost-share through a fixed **deductible → coinsurance → out-of-pocket-cap** waterfall, reading the member's accumulators at their pre-claim values. First, the remaining deductible is the plan's `individual_deductible_cents` minus the member's current `deductible_met_cents`, floored at 0; the `deductible_applied_cents` is the lesser of the `allowed_amount_cents` and that remaining deductible. The amount left after the deductible is the `allowed_amount_cents` minus `deductible_applied_cents`. The `member_coinsurance_cents` is that after-deductible amount multiplied by one minus the plan's `plan_coinsurance_pct` (the member's share is whatever the plan does not pay), rounded half-up to whole cents. The uncapped member responsibility is `deductible_applied_cents` plus `member_coinsurance_cents`. This is then capped by the remaining out-of-pocket room — the plan's `oop_max_cents` minus the member's current `oop_met_cents`, floored at 0 — so the `member_responsibility_cents` is the lesser of the uncapped responsibility and that remaining room. Finally, `plan_paid_cents` is the `allowed_amount_cents` minus `member_responsibility_cents`.

Adjudication then advances the member's accumulators: `deductible_met_cents` increases by `deductible_applied_cents`, `oop_met_cents` increases by `member_responsibility_cents`, and `member_plan_paid_ytd_cents` increases by `plan_paid_cents`. A successful adjudication moves the claim to `ADJUDICATED` and, as its final step, runs the specific stop-loss cascade described next.

### 3.5. Specific Stop-Loss Cascade and Claim Reversal

After the member's accumulators are updated, adjudication cascades into a **specific stop-loss** evaluation for that member. The system first selects the governing policy: the member's plan's stop-loss policy that is `ACTIVE` and whose half-open period (from `effective_date` inclusive up to but not including `expiry_date`) contains the claim's `service_date`, breaking any tie by the earliest `created_at`. Within that policy it then looks for an applicable laser — a laser for this member under that policy whose closed window (from `effective_date` through `expiry_date` inclusive) contains the `service_date`, again breaking ties by earliest `created_at`. The governing specific deductible is the laser's `laser_deductible_cents` when such a laser exists, otherwise the policy's `specific_deductible_cents`.

The eligible excess is the member's `member_plan_paid_ytd_cents` minus that governing specific deductible, floored at 0. The new reimbursement is that eligible excess minus the member's `spec_reimbursed_cents` already recognized. Only when the new reimbursement is strictly greater than 0 does the cascade create a `SPECIFIC` stop-loss reimbursement for the amount of the new reimbursement, tagged with the originating `claim_id` and `member_id`; it then adds that amount to both the member's `spec_reimbursed_cents` and the policy's `total_specific_reimbursed_cents`. A stop-loss reimbursement records its `stop_loss_policy_id`, its `reimbursement_type` (here `SPECIFIC`), and its `amount_cents`; its `basis_note` is left unset for specific reimbursements. Reimbursements may be listed and filtered by `stop_loss_policy_id` and/or `claim_id`.

An `ADJUDICATED` claim may be **reversed** by a `ClaimsExaminer` — for example, to correct an error — moving it `ADJUDICATED → REVERSED`. Reversal is only allowed from `ADJUDICATED`; a claim that has already been paid must first have its payment undone by voiding its check-run, and a reverse attempted on any other state is rejected with `ERR_INVALID_STATE`. Reversal is fully compensating: it decrements the member's `deductible_met_cents` by the claim's `deductible_applied_cents`, its `oop_met_cents` by the `member_responsibility_cents`, and its `member_plan_paid_ytd_cents` by the `plan_paid_cents`. If the original adjudication had created a `SPECIFIC` reimbursement from this claim, reversal also decrements the member's `spec_reimbursed_cents` and the policy's `total_specific_reimbursed_cents` by that reimbursement's amount. Only these running totals are unwound; the originating `SPECIFIC` reimbursement record itself is retained, not deleted. A `REVERSED` claim may be re-adjudicated (`REVERSED → ADJUDICATED`) under the same eligibility, run-out, and duplicate guards, re-running the full repricing, cost-share, accumulator, and specific-stop-loss cascade.

### 3.6. Funding, Check-Runs, and Disbursement

A `FundManager` opens a funding account for a plan by supplying its `plan_id`. The account is created `ACTIVE` with `balance_cents`, `total_deposited_cents`, and `total_disbursed_cents` all at 0. Depositing employer funds is a `FundManager` action that supplies an `amount_cents`; it increases both the `balance_cents` and the `total_deposited_cents` by that amount and increments the account's `version`. Fund accounts may be listed and filtered by `plan_id`.

Claims are paid in batches called check-runs. A `FundManager` drafts a check-run naming the `fund_account_id` and the `claim_ids` to include; the server computes the check-run's `total_amount_cents` as the sum of `plan_paid_cents` across the included claims — a claim that has not yet been adjudicated, whose `plan_paid_cents` is still null, contributes 0 to this sum — and the check-run begins in `DRAFT`. A claim may not appear in more than one live check-run: if any of the supplied `claim_ids` already belongs to a check-run that is `DRAFT` or `RELEASED`, the draft is rejected with `ERR_CLAIM_ALREADY_IN_CHECK_RUN`. A fund account's check-runs may be listed.

**Releasing** a `DRAFT` check-run — a `FundManager` action carrying `expected_fund_account_version` — disburses it. Every included claim must be `ADJUDICATED`; if any is not, the release is rejected with `ERR_CLAIM_NOT_ADJUDICATED`. The supplied `expected_fund_account_version` must match the fund account's current `version`, else `ERR_STALE_VERSION` as described in Section 2.5. The fund's `balance_cents` must be at least the check-run's `total_amount_cents`; if it is short, the release is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402). In precedence terms these are evaluated in the order state (claims adjudicated), then concurrency (stale version), then fiscal sufficiency (insufficient funds). On a successful release the check-run moves `DRAFT → RELEASED`, its `released_at` is stamped with the current clock, and each included claim moves `ADJUDICATED → PAID` with its `paid_at` stamped to the current clock. As a cascade, each newly paid claim increases its provider's `ytd_paid_cents` by that claim's `plan_paid_cents`. The fund's `balance_cents` is reduced by the `total_amount_cents`, its `total_disbursed_cents` is increased by the same amount, and its `version` is incremented by one.

**Voiding** a check-run is a `FundManager` action with two forms. Voiding a `DRAFT` check-run (`DRAFT → VOIDED`) simply discards the draft: no funds move and no claim changes state. Voiding a `RELEASED` check-run (`RELEASED → VOIDED`) is fully compensating: each included claim moves `PAID → ADJUDICATED` and its `paid_at` is cleared; each such claim's provider has its `ytd_paid_cents` decreased by that claim's `plan_paid_cents`; the fund's `balance_cents` is increased by the `total_amount_cents` and its `total_disbursed_cents` decreased by the same amount; and the fund's `version` is incremented by one. `VOIDED` is terminal for a check-run.

### 3.7. Aggregate Settlement

When a plan's total net claims cross its aggregate attachment point, the plan recovers from the reinsurer through aggregate settlement. Either a `TPAAdmin` or an `Auditor` may settle an `ACTIVE` policy; settling a policy that is not `ACTIVE` is rejected with `ERR_POLICY_NOT_ACTIVE`. Settlement counts qualifying claims according to the policy's `contract_basis`. On an `INCURRED` basis, the qualifying claims are those in `ADJUDICATED` or `PAID` status whose `service_date` falls within the policy period, inclusive of both the `effective_date` and the `expiry_date` — regardless of when they were paid. On a `PAID` basis, the qualifying claims are only those in `PAID` status whose `paid_at` falls within that same inclusive window — so a run-out claim paid after the period's expiry is excluded.

The gross plan-paid is the sum of `plan_paid_cents` over the qualifying claims. The net plan-paid is that gross minus the policy's `total_specific_reimbursed_cents` (specific recoveries already recognized are netted out). The excess is the net plan-paid minus the policy's `aggregate_attachment_cents`, floored at 0. The new aggregate reimbursement is that excess minus the policy's `total_aggregate_reimbursed_cents` already recognized. If the new aggregate amount is zero or negative — the attachment has not been exceeded net of prior recoveries — settlement is rejected with `ERR_AGGREGATE_NOT_REACHED` (HTTP 422). Otherwise the system creates an `AGGREGATE` stop-loss reimbursement for the new aggregate amount, recording the settlement `contract_basis` (`PAID` or `INCURRED`) in its `basis_note` and leaving its `claim_id` and `member_id` unset, increments the policy's `total_aggregate_reimbursed_cents` by the new amount, and moves the policy `ACTIVE → SETTLED`.

### 3.8. Provider Reporting and 1099 Generation

At year end an `Auditor` generates a provider 1099 by supplying the `provider_id` and the `tax_year`. The form's `total_paid_cents` is the sum of `plan_paid_cents` over all claims for that provider that are in `PAID` status and whose `paid_at` falls in the given calendar `tax_year`. The form is marked `reportable` when its `total_paid_cents` is at least the reporting threshold of 60,000 cents — that is, 600.00 US dollars — where exactly 600.00 dollars is itself reportable. Forms may be listed and filtered by `provider_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state transitions and deposits, return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a self-funded plan | TPAAdmin |
| GET | `/plans/{id}` | Fetch a plan | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/plans/{id}/terminate` | Terminate a plan, opening the run-out window | TPAAdmin |
| POST | `/plans/{id}/close` | Close a plan after run-out elapses | TPAAdmin |
| POST | `/providers` | Register a provider | TPAAdmin |
| GET | `/providers/{id}` | Fetch a provider | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/members` | Enroll a member | TPAAdmin |
| GET | `/members/{id}` | Fetch a member | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/members` | List members (filter by plan) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/members/{id}/terminate` | Terminate member coverage | TPAAdmin |
| POST | `/stop-loss-policies` | Create a stop-loss policy | TPAAdmin |
| GET | `/stop-loss-policies/{id}` | Fetch a stop-loss policy | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/stop-loss-policies` | List stop-loss policies (filter by plan) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/stop-loss-policies/{id}/activate` | Activate a policy | TPAAdmin |
| POST | `/stop-loss-policies/{id}/settle-aggregate` | Run aggregate settlement | TPAAdmin, Auditor |
| POST | `/lasers` | Carve out a member laser | TPAAdmin |
| GET | `/lasers/{id}` | Fetch a laser | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/lasers` | List lasers (filter by policy and/or member) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/claims` | Submit a claim | ClaimsExaminer |
| GET | `/claims/{id}` | Fetch a claim | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/claims` | List claims (filter by member, provider, status) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/claims/{id}/adjudicate` | Adjudicate and reprice a claim | ClaimsExaminer |
| POST | `/claims/{id}/pend` | Pend a claim for review | ClaimsExaminer |
| POST | `/claims/{id}/deny` | Deny a claim | ClaimsExaminer |
| POST | `/claims/{id}/reverse` | Reverse an adjudicated claim | ClaimsExaminer |
| POST | `/fund-accounts` | Open a plan funding account | FundManager |
| GET | `/fund-accounts/{id}` | Fetch a fund account | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/fund-accounts` | List fund accounts (filter by plan) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/fund-accounts/{id}/deposit` | Deposit employer funds | FundManager |
| POST | `/check-runs` | Draft a check-run over adjudicated claims | FundManager |
| GET | `/check-runs/{id}` | Fetch a check-run | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/fund-accounts/{id}/check-runs` | List a fund account's check-runs | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/check-runs/{id}/release` | Release a check-run (OCC on fund) | FundManager |
| POST | `/check-runs/{id}/void` | Void a check-run | FundManager |
| GET | `/stop-loss-reimbursements/{id}` | Fetch a reimbursement | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/stop-loss-reimbursements` | List reimbursements (filter by policy and/or claim) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/form-1099s/generate` | Generate a provider 1099 for a tax year | Auditor |
| GET | `/form-1099s/{id}` | Fetch a 1099 | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| GET | `/form-1099s` | List 1099s (filter by provider) | TPAAdmin, ClaimsExaminer, FundManager, Auditor |
| POST | `/_clock/set_current_utc` | Set the logical clock | TPAAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_STOP_LOSS_POLICY_NOT_FOUND` | 404 |
| `ERR_LASER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_FUND_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_CHECK_RUN_NOT_FOUND` | 404 |
| `ERR_REIMBURSEMENT_NOT_FOUND` | 404 |
| `ERR_FORM_1099_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLAIM_NOT_ADJUDICATED` | 409 |
| `ERR_CLAIM_ALREADY_IN_CHECK_RUN` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_LASER_MEMBER_MISMATCH` | 422 |
| `ERR_POLICY_PERIOD_OVERLAP` | 409 |
| `ERR_LASER_WINDOW_OVERLAP` | 409 |
| `ERR_MEMBER_NOT_ELIGIBLE` | 422 |
| `ERR_RUN_OUT_CLOSED` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_AGGREGATE_NOT_REACHED` | 422 |
