# Mortgage Servicing API — Product Requirements Document

## 1. Introduction

The Mortgage Servicing API is the system of record for the post-origination life of a residential mortgage. Once a loan has been booked, the system manages the routine cash flow (monthly payment posting, the escrow account that pays property tax and hazard insurance, and the private mortgage insurance premium), the annual escrow analysis that resets the escrow component for the year ahead, and the loss-mitigation paths that come into play when a borrower falls behind: forbearance, PMI removal, foreclosure, and HAMP-style pre-foreclosure mediation.

Each of these workflows carries its own regulatory clock, its own segregation-of-duties expectations, and its own accounting invariants. The escrow account must be reconciled with RESPA-style cushions; payments must be allocated in a deterministic waterfall whose order changes under foreclosure reinstatement; PMI may only be removed when loan-to-value drops below the appropriate threshold and the borrower has the required payment history; foreclosure cannot be filed until the statutory Notice-Of-Intent window has expired, an auction cannot be scheduled until the case has been on file long enough, and a mediation case can re-extend a modification offer many times before either succeeding or failing into court. The API encodes these rules so that downstream systems — borrower portal, attorney intake, regulatory reporting — observe a single consistent state.

This document specifies the resource model, the state machines and their cascades, the calculations (amortization, payment waterfall, escrow projection, LTV evaluation, reinstatement quote, HAMP modified payment, forbearance cure balance), the validation priority, the role matrix, and the complete set of error identifiers a client may receive.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING` and HTTP 401. If both headers are present but the acting role is not permitted to call the endpoint per the RBAC matrix in §4, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

The system recognises exactly six roles, spelled as follows: `Borrower`, `Servicer`, `LossMitigationUnderwriter`, `PmiUnderwriter`, `ForeclosureAttorney`, and `PlatformAdmin`.

`Borrower` is an entity-backed identity: when `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`. Ownership checks on any resource that references a `Borrower` compare the resource's `borrower_id` (directly on `Loan`, transitively through `Loan` for `Payment`, `EscrowAnalysis`, `Disbursement`, `ForbearancePlan`, `PmiRemovalRequest`, `ForeclosureCase`, and `MediationCase`) to `X-User-ID`. A borrower who attempts to operate on a loan whose `borrower_id` does not equal their `X-User-ID` is treated as forbidden (`ERR_FORBIDDEN`).

The remaining five roles — `Servicer`, `LossMitigationUnderwriter`, `PmiUnderwriter`, `ForeclosureAttorney`, and `PlatformAdmin` — are opaque operator identities not tied to any persisted entity. For these roles, `X-User-ID` is recorded for audit but is never compared to a resource's `id`. The server may, however, use that opaque identifier to enforce segregation of duties between sequential steps performed by the same operator: a single `X-User-ID` cannot both extend a mediation offer and accept the same offer on the same `MediationCase`, and a single `X-User-ID` cannot both post the curing payment batch and finalise the same `ForbearancePlan` as `COMPLETED`. A second-step attempt by the first-step operator is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0 and has no upper bound beyond the underlying collection size. List results are always sorted by `created_at` in ascending order so that pagination is stable across calls. For every list response, the `meta` block carries `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring `limit` and `offset`), and `has_more` (true when more records exist beyond the current window).

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional seconds (for example `2025-05-24T10:30:00.123Z`). All resources except `EscrowAnalysis` additionally carry an `updated_at` timestamp (same format) that is refreshed on every server-side mutation of the resource, and an integer `version` that starts at 1 on creation and increases by exactly 1 on each mutation. `EscrowAnalysis` is an immutable snapshot once it has been finalised, and therefore exposes only `id` and `created_at`; it has neither `updated_at` nor `version`.

Money values are always carried as integer cent counts, with field names ending in `_cents`. Interest rates and loan-to-value ratios are carried as integer basis points (one hundredth of a percent), with field names ending in `_bps`; for example, `interest_rate_bps` of 625 means 6.25% annual nominal interest, and `evaluated_ltv_bps` of 7800 means an LTV of 78.00%. Date-only quantities (`origination_date`, `received_date`, `analysis_date`, `start_date`, `end_date`, `scheduled_date`, `next_due_date`, `auction_date`) are stored as ISO 8601 timestamps at UTC midnight.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that operate on an existing `Loan`, `ForbearancePlan`, `ForeclosureCase`, or `MediationCase` accept an optional `version` field in the request body. When the caller supplies `version`, the server compares it against the persisted `version` on the target resource at commit time; a mismatch is rejected with `ERR_CONCURRENT_UPDATE` and HTTP 409. When the caller omits `version`, the optimistic check is skipped and the request applies last-writer-wins. On every successful mutation, the server increments `version` by 1 and refreshes `updated_at`.

Beyond bare `version` checks, several specific races have named outcomes. When two servicers post payments to the same loan at the same moment, both payments are eventually `POSTED` — the allocations are applied serially in order of `received_date` then `created_at`, balances reflect both, and only the loser whose `version` precondition fails on the `Loan` row receives `ERR_CONCURRENT_UPDATE`. When two finalisation attempts target two different `PROVISIONAL` `EscrowAnalysis` records on the same loan, exactly one wins; the other is rejected with `ERR_ESCROW_ANALYSIS_CONFLICT` and HTTP 409 so that `monthly_escrow_payment_cents` is set deterministically. When the `PmiUnderwriter` approves a PMI removal while the `Servicer` is concurrently posting a payment that breaks the twenty-four-month on-time history requirement, first-writer-wins on `Loan.version`: if the payment commits first, the approve is rejected with `ERR_PMI_HISTORY_INSUFFICIENT` (re-validated at commit time); if the approve commits first, the subsequent payment posts without disturbing `pmi_status`. When two `ForeclosureAttorney` operators try to open a `ForeclosureCase` on the same `Loan` simultaneously, the second attempt is rejected with `ERR_FORECLOSURE_CASE_EXISTS` and HTTP 409. When extending an offer races with completing a different already-accepted offer on the same `MediationCase`, the second extend is rejected with `ERR_INVALID_STATE` and HTTP 409. When a borrower-initiated reinstatement payment races against an attorney scheduling the auction, first-writer-wins on `ForeclosureCase.status`: if reinstatement commits first (and the payment amount meets or exceeds the quote), the schedule-auction attempt is rejected with `ERR_INVALID_STATE`; if scheduling commits first, reinstatement remains allowed up to the cut-off of five days before `auction_date`.

### 2.6. Validation Priority

When multiple validation conditions could reject the same request, the system evaluates them in a fixed order so the returned `error_id` is deterministic. The order is: (1) `X-User-Role` header presence and value among the declared roles, then (2) `X-User-ID` header presence — both surface as `ERR_AUTH_MISSING`; then (3) the RBAC check that the acting role may call the endpoint, surfacing as `ERR_FORBIDDEN`; then (4) the segregation-of-duties check for sequential mediation and forbearance steps performed by the same operator, surfacing as `ERR_SEGREGATION_OF_DUTIES`; then (5) left-to-right resolution of the `loan_id` path parameter (`ERR_LOAN_NOT_FOUND`); then (6) resolution of any nested resource id under its declared parent (`ERR_RESOURCE_NOT_FOUND`); then (7) `Loan.posture`-level admissibility of the requested operation and (8) the source-state precondition on the entity being acted upon (both surface as `ERR_INVALID_STATE`); then (9) the optimistic concurrency check (`ERR_CONCURRENT_UPDATE`). Only after these nine gates do the business-level checks fire: regulatory windows (priorities 10–13), referential exclusivity (priorities 14–16), constraint and eligibility (priorities 17–22), temporal cut-offs (priorities 23–24), and fiscal sanity (priorities 25–27). The full ordering is binding: for example, an attempt to file a foreclosure on a non-existent loan returns `ERR_LOAN_NOT_FOUND`, not `ERR_NOI_WINDOW_NOT_ELAPSED`, because existence is checked before any business window.

### 2.7. Nested Resource Path Resolution

URL paths that nest a resource under one or more parents are validated left to right. For a request to a path of the form `/loans/{loan_id}/payments/{id}/reverse`, the server first resolves `loan_id` and returns `ERR_LOAN_NOT_FOUND` if it does not exist, then resolves the `Payment` `id` and additionally verifies that the payment's `loan_id` matches the path parent; failure of the latter step returns `ERR_RESOURCE_NOT_FOUND`. The same rule applies to nested `EscrowAnalysis`, `Disbursement`, `ForbearancePlan`, `PmiRemovalRequest`, `ForeclosureCase`, and `MediationCase` endpoints.

### 2.8. Money, Rounding, and Precision

All monetary computations are performed in whole cents and exposed through fields ending in `_cents`. Whenever a calculation produces a fractional cent result, the system rounds half-up to the nearest whole cent, and the rounding is applied a single time at the formula's final output rather than at intermediate steps — unless the calculation explicitly calls for `ceil()` or `floor()` (notably the RESPA cushion, the new monthly escrow, the affordability floor, and the LTV evaluation, all of which use directional rounding as described in §3). Per-installment interest within the payment waterfall is computed as the floor of the principal balance times the monthly rate so cents-of-interest never round up against the borrower. Loan-to-value ratios are computed in basis points using integer arithmetic with `floor()` so the borrower is never granted PMI removal by a rounding artefact.

### 2.9. Time, Sweeps, and the Logical Clock

The system is fully deterministic against a server-side logical clock, advanced only through the platform-admin test-driving capability described in §3.7. When the clock advances by some number of days, the system re-evaluates time-gated transitions in a fixed order in a single pass: first any `ForbearancePlan` that crosses `end_date` is moved to `COMPLETED` or `BREACHED`, then every loan's `delinquency_days` is recomputed and `posture` is re-derived (which may cascade to `DELINQUENT` or `DEFAULT`), then `Disbursement` records whose `scheduled_date` has been reached are paid or failed based on the current escrow balance, then any `ForeclosureCase` in `AUCTION_SCHEDULED` whose `auction_date` has been reached is closed as sold, and finally any `MediationCase` in `OPEN` whose case has aged past the ninety-day failure window is failed. A separate sweep capability runs the same evaluation pipeline without advancing the clock.

### 2.10. Cascades, Version Bumps, and `updated_at`

State machines in this system are highly interconnected and cascades are routine. When an operation mutates a primary entity, every secondary entity it touches receives its own `updated_at` refresh and `version` increment (where it carries those fields). Posting a payment that fully cures a delinquency on a `Loan`, for example, may transition the `Loan` from `DELINQUENT` to `CURRENT`; in turn, if the loan was `REINSTATED` and the payment is fully on time, the loan transitions to `CURRENT` (a depth-three cascade from `Payment` creation through `Loan.posture`). Every entity whose state changes during such a cascade is updated atomically with the triggering operation — there is no partial-commit intermediate state visible to readers.

## 3. Business Logic & Workflows

### 3.1. Booking a Loan and the Borrower Hardship Affidavit

A new mortgage enters the system in two steps. First, a `Servicer` or `PlatformAdmin` creates the `Borrower` record by supplying `full_name` (non-empty, at most 200 characters) and `email`. The borrower's `hardship_attested_at` field begins as null; later, when a borrower formally attests to financial hardship — a precondition for both forbearance and pre-foreclosure mediation — the hardship-attestation capability stamps `hardship_attested_at` to the current server time. The attestation step accepts no body; either the `Borrower` themselves or a `Servicer` on their behalf may invoke it.

Second, the `Servicer` originates the loan by supplying `borrower_id`, `origination_date`, `original_principal_cents` (at least 100,000, i.e. at least one thousand dollars), `original_appraised_value_cents` (strictly positive, used as the LTV denominator for automatic PMI termination), `interest_rate_bps` (a fixed-rate value between 1 and 5000 basis points), `term_months` (between 60 and 480 inclusive), and optionally `pmi_monthly_cents` and `monthly_escrow_payment_cents`. Upon creation, the server computes `scheduled_payment_cents` from the standard amortization formula, initialises `principal_balance_cents` to `original_principal_cents`, initialises `escrow_balance_cents` to zero, sets `next_due_date` to the `origination_date` plus one month, sets `posture` to `CURRENT`, and sets `pmi_status` to `ACTIVE` when `pmi_monthly_cents` is greater than zero or to `REMOVED` otherwise.

The amortization formula determining `scheduled_payment_cents` is the standard mortgage payment. Let the monthly rate equal `interest_rate_bps` divided by 10,000 divided by 12, let `n` be `term_months`, and let `P` be `original_principal_cents` at origination (or, for a loan modification driven by an accepted HAMP offer, the current `principal_balance_cents` net of any principal forbearance). If the monthly rate is zero, the payment is `P` divided by `n`, rounded up to whole cents. Otherwise, the payment is `P` multiplied by the monthly rate, multiplied by one-plus-monthly-rate raised to the `n`th power, divided by the quantity one-plus-monthly-rate raised to the `n`th power minus one, with the final result rounded half-up to whole cents — a single rounding at the output, with no per-month rounding. The same formula is reused at loan-modification time with the post-modification rate, remaining term, and remaining principal as inputs.

### 3.2. Posting Payments and the Allocation Waterfall

A `Borrower` posts a payment against their own loan, or a `Servicer` posts on the borrower's behalf, by supplying `received_date`, `amount_cents` (which must be strictly positive — otherwise the request is rejected with `ERR_PAYMENT_AMOUNT_INVALID`), and an optional `version` for the optimistic-concurrency check on `Loan`. A loan in the `PAID_OFF` terminal posture cannot receive further payments and the attempt is rejected with `ERR_INVALID_STATE`; a loan with an open `ForeclosureCase` (in `NOI_ISSUED`, `MEDIATION_OPEN`, `FILED`, or `AUCTION_SCHEDULED`) also rejects ordinary payments with `ERR_INVALID_STATE`, with one exception — a payment whose `amount_cents` meets or exceeds the case's `reinstatement_quote_cents` is permitted through as the reinstatement path described in §3.6.

Each accepted payment is recorded with `status` `POSTED`, and the system runs the allocation waterfall to populate `allocation_late_fee_cents`, `allocation_interest_cents`, `allocation_principal_cents`, `allocation_escrow_cents`, and `allocation_suspense_cents`. The waterfall starts from the total `amount_cents` as a remaining budget and pays line items in priority order; each step takes the smaller of the remaining budget and the demand for that step, and the budget is decremented accordingly. The line items, in order, are: outstanding late fees (where late fees accrue at five thousand cents per late month — that is fifty dollars — capped at twenty-five thousand cents, computed as the integer-floor of `delinquency_days` divided by 30, multiplied by the per-month late fee, capped at the cap); then accrued interest on past-due principal and interest installments, where per-installment interest is the floor of the per-installment principal balance times the monthly rate, summed across all installments due as of `received_date`; then the past-due principal portion of those installments; then the past-due escrow portion; and finally any residual is parked in suspense as `allocation_suspense_cents`. Suspense funds do not advance `next_due_date` — only when an installment's principal plus interest plus escrow has been fully covered does `next_due_date` move forward by one month for that installment.

Installments are processed oldest-first by due date; ties are broken by `created_at` ascending. Once allocations are written, `Loan.principal_balance_cents` is decremented by `allocation_principal_cents`, `Loan.escrow_balance_cents` is incremented by `allocation_escrow_cents`, `next_due_date` is advanced one month per fully satisfied installment, `delinquency_days` is recomputed as the integer-day-floor of (today minus `next_due_date`, with zero when the result is negative), and `Loan.posture` is re-derived (which may move it from `DELINQUENT` back to `CURRENT`). If the loan was in `REINSTATED` posture and this is the first fully-on-time payment posted after reinstatement — meaning `received_date` is on or before `next_due_date` at the time of posting — `Loan.posture` advances from `REINSTATED` to `CURRENT`. If the principal is fully retired (`principal_balance_cents` reaches zero) while the loan is `CURRENT` and `escrow_balance_cents` is non-negative, `Loan.posture` transitions to `PAID_OFF`; in that moment, every `SCHEDULED` `Disbursement` of type `PROPERTY_TAX` or `HAZARD_INSURANCE` is cancelled (status `CANCELED`), while any `SURPLUS_REFUND` disbursements remain.

The reinstatement variant of the waterfall is the same line items in the same order, with two changes: foreclosure costs (`ForeclosureCase.foreclosure_costs_cents`) are paid first, ahead of late fees; and the inclusion set is all past-due installments together with `foreclosure_costs_cents`, settled in a single transaction. This variant is selected automatically when the loan has an open `ForeclosureCase` and `amount_cents` is at least the case's `reinstatement_quote_cents`.

A posted payment can later be reversed by a `Servicer` — typically to correct a misapplied payment. Reversal is only permitted while the loan is not `PAID_OFF` and only against a payment whose `status` is still `POSTED`; otherwise the attempt is rejected with `ERR_INVALID_STATE`. On reversal, `Payment.status` becomes `REVERSED`, `reversed_at` is stamped to now, `Loan.principal_balance_cents` is incremented back by `allocation_principal_cents`, `Loan.escrow_balance_cents` is decremented by `allocation_escrow_cents`, `next_due_date` rolls back by the number of installments the payment had satisfied, and `delinquency_days` is recomputed. The fundamental invariant preserved across posting and reversal is that the current `principal_balance_cents` plus the sum of `allocation_principal_cents` across all `POSTED` payments equals `original_principal_cents` minus any principal forbearance granted by an accepted loan modification.

### 3.3. The Escrow Account, Annual Analysis, and Tax/Insurance Disbursements

The escrow account funds two recurring obligations on behalf of the borrower: property tax and hazard insurance. The `Servicer` schedules each such obligation by creating a `Disbursement` with `type` (either `PROPERTY_TAX`, `HAZARD_INSURANCE`, or — for system-issued surplus refunds — `SURPLUS_REFUND`), a `scheduled_date` (UTC midnight), and `amount_cents` (strictly positive). Disbursements begin in status `SCHEDULED`.

When the logical clock advances past a disbursement's `scheduled_date`, the system attempts to pay it. If `Loan.escrow_balance_cents` is at least the disbursement's `amount_cents`, the disbursement transitions to `PAID`, `paid_at` is stamped, and `Loan.escrow_balance_cents` is decremented by `amount_cents`. If the balance is insufficient, the disbursement transitions to `FAILED` with `failure_reason` set to `INSUFFICIENT_ESCROW`; the resulting escrow shortage becomes a factor the next escrow analysis must amortise. A `Servicer` may retry a `FAILED` disbursement at any later time — the retry succeeds (transitioning the disbursement to `PAID`, stamping `paid_at`, clearing `failure_reason`, and decrementing the balance by `amount_cents`) only when escrow once again has sufficient funds; otherwise the retry is rejected with `ERR_INSUFFICIENT_ESCROW`. A `Servicer` may also cancel any `SCHEDULED` disbursement; cancellation transitions the disbursement to `CANCELED`. Once a loan reaches `PAID_OFF`, any still-`SCHEDULED` tax or insurance disbursement is cancelled automatically while pending surplus refunds remain.

The annual escrow analysis is the mechanism by which the monthly escrow component is reset. A `Servicer` initiates an analysis by supplying `analysis_date` and `starting_balance_cents`; the loan must not be in `PAID_OFF` posture (an attempt there is rejected with `ERR_INVALID_STATE`); `analysis_date` must be on or after `Loan.origination_date`, and `starting_balance_cents` must equal the current `Loan.escrow_balance_cents`. A mismatch on either side is rejected with `ERR_ESCROW_BASELINE_MISMATCH`. The newly created `EscrowAnalysis` begins in status `PROVISIONAL`, and the server immediately computes its derived numbers.

The projection looks forward 365 days from `analysis_date`. `projected_disbursements_cents` is the sum of `amount_cents` across every `Disbursement` in status `SCHEDULED` with `type` `PROPERTY_TAX` or `HAZARD_INSURANCE` whose `scheduled_date` falls in the half-open window from `analysis_date` up to but not including `analysis_date` plus 365 days, plus — only when `pmi_status` is `ACTIVE` — twelve times `pmi_monthly_cents`; `SURPLUS_REFUND` disbursements are excluded. The two-month RESPA-style cushion `required_cushion_cents` equals the ceiling of `projected_disbursements_cents` divided by 12, multiplied by 2. `shortage_cents` is the greater of zero and `required_cushion_cents` minus `starting_balance_cents`. `surplus_cents` is the greater of zero and `starting_balance_cents` minus the quantity `required_cushion_cents` plus `projected_disbursements_cents`. `new_monthly_escrow_cents` is the ceiling of `projected_disbursements_cents` plus `shortage_cents`, divided by 12. Each output field is computed independently with at most one `ceil()` applied to it; there is no intermediate rounding inside a single field's computation. A `PROVISIONAL` analysis never mutates `Loan.monthly_escrow_payment_cents` and never emits a disbursement.

To make the analysis effective, the `Servicer` finalises it. Finalisation is only permitted when the source analysis is still `PROVISIONAL` and no other `FINALIZED` `EscrowAnalysis` on the loan has an `analysis_date` greater than or equal to this analysis's `analysis_date` — otherwise the request is rejected with `ERR_INVALID_STATE`. The projection is recomputed at commit time from the current disbursement set (which may have changed since the `PROVISIONAL` snapshot was created), the `EscrowAnalysis` transitions to `FINALIZED`, `finalized_at` is stamped, and `Loan.monthly_escrow_payment_cents` is overwritten with the freshly computed `new_monthly_escrow_cents`. Any prior `FINALIZED` analysis on the same loan transitions to `SUPERSEDED`, as does any other `PROVISIONAL` analysis on the same loan whose finalisation is pre-empted by this one. Surpluses are not amortised into the monthly payment; instead, when `surplus_cents` strictly exceeds five thousand cents (i.e. exceeds fifty dollars), the system creates a new `Disbursement` of type `SURPLUS_REFUND` with `amount_cents` equal to `surplus_cents`, `scheduled_date` thirty days in the future, and `status` `SCHEDULED`.

### 3.4. The Delinquency Ladder and the Forbearance Branch

Loan posture is the cross-cutting summary of where the loan sits in its life. A newly originated loan is `CURRENT`. When a clock advance lifts `delinquency_days` to at least 1 and there is no `ForbearancePlan` in status `ACTIVE` covering the loan, the system transitions `Loan.posture` from `CURRENT` to `DELINQUENT`. A subsequent payment that brings `delinquency_days` back to zero transitions the loan from `DELINQUENT` to `CURRENT`. When delinquency reaches at least 120 days and no `ACTIVE` plan covers the loan, the system transitions the loan from `DELINQUENT` to `DEFAULT` — the gate that admits foreclosure.

A `LossMitigationUnderwriter` may interrupt this ladder by approving a `ForbearancePlan`. Plan creation accepts `start_date`, `months` (between 1 and 12 inclusive), and `repayment_method` (one of `LUMP_SUM`, `REPAYMENT_PLAN_12M`, or `DEFERRAL`). The borrower must have a non-null `hardship_attested_at` — otherwise the request is rejected with `ERR_HARDSHIP_AFFIDAVIT_MISSING`. The loan must not already have another plan in status `ACTIVE` — otherwise the request is rejected with `ERR_FORBEARANCE_PLAN_EXISTS`. The loan must be in `CURRENT` or `DELINQUENT` posture so that forbearance can pre-empt a delinquency rather than try to reverse a default. And the `start_date` must be on or before `Loan.next_due_date`, since the plan cannot start in the future of arrears — otherwise the request is rejected with `ERR_FORBEARANCE_DATE_INVALID`. On creation, `end_date` is computed as `start_date` plus `months` months (exclusive upper bound), `total_paused_cents` is set to `months` multiplied by the sum of `Loan.scheduled_payment_cents` and `Loan.monthly_escrow_payment_cents`, and `Loan.posture` cascades to `FORBEARANCE` while `next_due_date` is frozen until the plan's `end_date`.

The `LossMitigationUnderwriter` may also cancel an `ACTIVE` plan before its `end_date`; cancellation transitions the plan to `CANCELED` and `Loan.posture` reverts to `DELINQUENT` or `CURRENT` based on the recomputed `delinquency_days`. An attempt to cancel after `end_date` is rejected with `ERR_INVALID_STATE`.

After the plan's `end_date`, the loan's repayment treatment depends on `repayment_method` and is captured in the continuously evaluated `cure_balance_cents`. The cure balance begins at `total_paused_cents` once `end_date` passes and is reduced, payment by payment, by every `POSTED` `Payment` whose `received_date` is on or after `end_date`, processed in `received_date` then `created_at` order. For each such payment, the amount applied to cure is the smaller of the remaining cure balance and the sum of `allocation_principal_cents`, `allocation_interest_cents`, and `allocation_escrow_cents` for that payment, and the cure balance is decremented accordingly; the cure balance is floored at zero. Under `LUMP_SUM`, a single payment must satisfy the cure within thirty days of `end_date`. Under `REPAYMENT_PLAN_12M`, the cure is spread over twelve months with a per-month minimum equal to the ceiling of `total_paused_cents` divided by twelve. Under `DEFERRAL`, `cure_balance_cents` is immediately zero upon the `COMPLETED` transition and `total_paused_cents` is added to `principal_balance_cents` (deferred to maturity, with no interest accrual on the deferred amount). When the clock advances past `end_date` and `cure_balance_cents` is zero, the plan transitions to `COMPLETED` and `Loan.posture` returns to `CURRENT`. When the clock advances at least thirty days past `end_date` and `cure_balance_cents` is still strictly positive, the plan transitions to `BREACHED` and `Loan.posture` cascades to `DEFAULT`.

### 3.5. PMI Removal: Borrower Request and Automatic Termination

Private mortgage insurance is carried on the loan as `pmi_monthly_cents` and tracked through `pmi_status` (`ACTIVE`, `REMOVAL_REQUESTED`, `REMOVED`, or `AUTO_TERMINATED`). A request to remove PMI is filed against a loan whose `pmi_status` is currently `ACTIVE`; an attempt against any other status is rejected with `ERR_INVALID_STATE`. The request body carries `trigger`, which is either `BORROWER_REQUEST` (initiated by the borrower with new appraisal evidence) or `AUTO_TERMINATION` (initiated by the servicer when scheduled amortization is expected to have crossed the regulatory threshold). For `BORROWER_REQUEST`, the body must also carry `current_appraised_value_cents` (strictly positive); for `AUTO_TERMINATION`, `current_appraised_value_cents` is ignored.

The system computes `evaluated_ltv_bps` immediately on filing. For `AUTO_TERMINATION`, the basis value is `original_appraised_value_cents`; for `BORROWER_REQUEST`, the basis value is the supplied `current_appraised_value_cents`. `evaluated_ltv_bps` is the floor of `principal_balance_cents` multiplied by 10,000, divided by that basis value — yielding an integer basis-point figure (so 7800 corresponds to 78.00%). Filing transitions `Loan.pmi_status` to `REMOVAL_REQUESTED` and the `PmiRemovalRequest` is created with `decision` `PENDING`.

A `PmiUnderwriter` resolves the request by approving or denying. Approval is only permitted when the request's `decision` is still `PENDING`, when the LTV threshold is met (`evaluated_ltv_bps` no greater than 8000 for `BORROWER_REQUEST`, or no greater than 7800 for `AUTO_TERMINATION` — otherwise the request is rejected with `ERR_PMI_LTV_TOO_HIGH`), and — for `BORROWER_REQUEST` only — when `Loan.posture` is `CURRENT` and there is no `POSTED` `Payment` whose `received_date` was later than its scheduled due date within the last 24 scheduled months. Failure of either branch of the history check is rejected with `ERR_PMI_HISTORY_INSUFFICIENT`. On approval, the request's `decision` becomes `APPROVED`, `Loan.pmi_status` becomes `REMOVED` for `BORROWER_REQUEST` or `AUTO_TERMINATED` for `AUTO_TERMINATION`, `Loan.pmi_monthly_cents` is set to zero, and the next finalised escrow analysis will accordingly drop PMI from the projected disbursements. Denial requires only that the request still be `PENDING`; the body carries `denial_reason` (one of `LTV_TOO_HIGH`, `PAYMENT_HISTORY_INSUFFICIENT`, or `LOAN_NOT_CURRENT`), the request's `decision` becomes `DENIED`, `denial_reason` is recorded on the request, and `Loan.pmi_status` reverts to `ACTIVE`.

### 3.6. Foreclosure: NOI, Mediation, Filing, Auction, Reinstatement

When a loan reaches `DEFAULT` posture and no other open `ForeclosureCase` already covers it, a `ForeclosureAttorney` may open a new `ForeclosureCase` by supplying `loan_id` and an optional `foreclosure_costs_cents` (initial accumulated legal and filing cost, defaulting to zero). The case is created in status `NOI_ISSUED`, `noi_sent_at` is stamped to now (starting the regulatory clock), and `Loan.posture` cascades to `FORECLOSURE`. At most one open case per loan is permitted — an open case is one whose `status` is in the set `NOI_ISSUED`, `MEDIATION_OPEN`, `FILED`, or `AUCTION_SCHEDULED`; a second-opening attempt is rejected with `ERR_FORECLOSURE_CASE_EXISTS`.

The 30-day NOI window is the borrower's last opportunity to request pre-foreclosure mediation. A request originating from the `Borrower` themselves or from a `Servicer` against a case in `NOI_ISSUED` status, within 30 days of `noi_sent_at`, and where the `Borrower.hardship_attested_at` is non-null, advances the case to `MEDIATION_OPEN` and creates a `MediationCase` in status `REQUESTED`. A mediation request after the 30-day NOI window is rejected with `ERR_MEDIATION_WINDOW_CLOSED`. A mediation request when the borrower has not attested hardship is rejected with `ERR_HARDSHIP_AFFIDAVIT_MISSING`. At most one active `MediationCase` (any status not in `FAILED`, `OFFER_REJECTED`, or `COMPLETED`) may exist per `ForeclosureCase`; a second attempt is rejected with `ERR_MEDIATION_ALREADY_OPEN`.

If no mediation request lands inside the 30-day NOI window, the `ForeclosureAttorney` may file the case in court. Filing requires the case to be in `NOI_ISSUED` status, requires at least 30 days to have elapsed since `noi_sent_at` (an earlier attempt is rejected with `ERR_NOI_WINDOW_NOT_ELAPSED`), and requires that no mediation case in a non-terminal status (anything other than `FAILED`, `OFFER_REJECTED`, or `COMPLETED`) currently exists on the case. On filing, the case status becomes `FILED` and `filed_at` is stamped. After the case has been on file for at least 60 days, the attorney may schedule an auction by supplying `auction_date`. The proposed `auction_date` must be at least 30 days in the future (statutory notice); failure of either the 60-day or the 30-day rule is rejected with `ERR_AUCTION_NOTICE_VIOLATION`. On success, the case advances to `AUCTION_SCHEDULED` and `auction_date` is recorded. When the logical clock subsequently reaches `auction_date`, the case is closed as sold (`CLOSED_SOLD`); `Loan.posture` remains `FORECLOSURE` for posting purposes.

At any open stage of the case (`NOI_ISSUED`, `MEDIATION_OPEN`, `FILED`, or `AUCTION_SCHEDULED`) the borrower may reinstate by paying the full quote. The reinstatement quote is computed on demand: `reinstatement_quote_cents` equals the sum, over every past-due installment from `next_due_date` up to today, of (the installment's principal-and-interest payment plus its escrow payment), plus the outstanding late-fee accrual (as defined in §3.2), plus the case's `foreclosure_costs_cents`, plus any escrow shortage produced by previously-failed disbursements (modelled as the maximum of zero and the negative of `escrow_balance_cents`). The reinstatement endpoint accepts `payment_amount_cents`; if it is less than `reinstatement_quote_cents` (re-checked at commit time so racing late fees and freshly-failed disbursements are correctly reflected), the request is rejected with `ERR_REINSTATEMENT_INSUFFICIENT`. If the case is already `AUCTION_SCHEDULED`, reinstatement must be attempted strictly more than 5 days before `auction_date`; an attempt inside the 5-day cut-off is rejected with `ERR_REINSTATEMENT_CUTOFF`. On a successful reinstatement, the server creates a `Payment` whose `amount_cents` is `payment_amount_cents` (which runs through the foreclosure-reinstatement variant of the allocation waterfall), the case status becomes `CLOSED_REINSTATED`, `Loan.posture` becomes `REINSTATED`, `delinquency_days` is set to zero, and `next_due_date` is advanced past every paid arrears installment. If reinstatement occurs while the case is in `MEDIATION_OPEN`, any still-open `MediationCase` auto-transitions to `FAILED`. After reinstatement, the first fully-on-time payment posted advances `Loan.posture` from `REINSTATED` to `CURRENT`.

### 3.7. Pre-Foreclosure Mediation: the HAMP-Style Negotiation Loop

A newly created `MediationCase` begins in status `REQUESTED` and carries `foreclosure_case_id` as the back-reference to its parent `ForeclosureCase` (exactly one active mediation per case). The `LossMitigationUnderwriter` opens it for negotiation, transitioning it from `REQUESTED` to `OPEN` (stamping `opened_at`) — but only when the `ForeclosureCase.status` is still `MEDIATION_OPEN`. From `OPEN` (or, in the cyclic-revision case, from `OFFER_REJECTED`), the underwriter extends a modification offer by supplying any of `offered_new_rate_bps`, `offered_term_extension_months`, and `offered_principal_forbearance_cents`. The `offered_new_rate_bps` must be strictly positive when supplied (null is allowed to mean "no rate change"); `offered_term_extension_months` must be at least zero; `offered_principal_forbearance_cents` defaults to zero.

The system computes `target_payment_cents` from a HAMP-style waterfall applied in a fixed order: first subtract `offered_principal_forbearance_cents` from `principal_balance_cents` to obtain the remaining principal; then derive the new monthly rate from `offered_new_rate_bps` (falling back to the loan's current `interest_rate_bps` when the offer leaves it unchanged), divided by 10,000 and then divided by 12; then derive the new term as the original `term_months` minus the months elapsed since `origination_date`, plus `offered_term_extension_months`. With those inputs, `target_payment_cents` is the ceiling of (remaining principal multiplied by new monthly rate, multiplied by one-plus-new-monthly-rate raised to the new-term power, divided by the quantity one-plus-new-monthly-rate raised to the new-term power minus one). A single ceiling at the final output, no intermediate rounding.

Two guards apply at extension time. The affordability floor requires that `target_payment_cents` is at least the ceiling of remaining principal divided by the new term (i.e. would never produce negative amortization); a violation is rejected with `ERR_HAMP_AFFORDABILITY_FLOOR`. The reduction guard requires that `target_payment_cents` is strictly less than the loan's current `scheduled_payment_cents` (a modification offer that does not reduce the payment is not a HAMP-style offer at all); a violation is rejected with `ERR_HAMP_NOT_A_REDUCTION`. On success, the `MediationCase` transitions to `OFFER_EXTENDED` and `target_payment_cents` is recorded on the case.

From `OFFER_EXTENDED`, the offer may be accepted (transitioning to `OFFER_ACCEPTED`) — invoked by the `Borrower` themselves or by a `Servicer` on the borrower's behalf — or rejected (transitioning to `OFFER_REJECTED`, carrying a `rejection_reason` of `DTI_TOO_HIGH`, `AFFORDABILITY_FLOOR`, or `BORROWER_REFUSED`). After rejection, the underwriter may extend a revised offer (cycling back to `OFFER_EXTENDED` with `target_payment_cents` recomputed) — but only when the rejection reason was not `BORROWER_REFUSED`, and only while the case is still in `MEDIATION_OPEN` on the parent `ForeclosureCase`. The underwriter may also formally fail the mediation from `OFFER_REJECTED` — manually, or automatically when the rejection reason is `BORROWER_REFUSED` or when 60 days have elapsed since `noi_sent_at`. Either way the case becomes `FAILED`, and if the NOI window has now expired the parent `ForeclosureCase` cascades from `MEDIATION_OPEN` to `FILED`, stamping `filed_at`. A `MediationCase` left in `OPEN` without an extended offer for 90 days since `noi_sent_at` is also auto-failed on clock advance.

When the borrower accepts the offer, completing the mediation is the underwriter's responsibility. Completion is permitted only from `OFFER_ACCEPTED`; otherwise it is rejected with `ERR_INVALID_STATE`. The system re-computes `target_payment_cents` at commit time using the loan's `principal_balance_cents` as of the cascade commit (which may have changed if payments were posted between extension and completion). If the recomputed value diverges from the stored `target_payment_cents` by more than 100 cents, the completion is rejected with `ERR_HAMP_STALE_OFFER`. Otherwise, the `MediationCase` transitions to `COMPLETED`, the parent `ForeclosureCase` cascades to `CLOSED_MODIFIED`, and the `Loan` itself is modified: `Loan.scheduled_payment_cents` becomes the recomputed target, `Loan.interest_rate_bps` becomes `offered_new_rate_bps` when that field is non-null, `Loan.term_months` is extended by `offered_term_extension_months`, and finally `Loan.posture` returns to `CURRENT`. The completion step is the segregation-of-duties pivot: the underwriter who extended the most recent offer must not be the same `X-User-ID` that accepted it; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 3.8. Operational Test-Driving: Clock Advance and Sweep

To support deterministic testing and batch processing, the `PlatformAdmin` role has two infrastructure capabilities. The first advances the server's logical clock by a supplied number of `days` and triggers all time-gated transitions in the deterministic order described in §2.9: forbearance completions and breaches first, then delinquency recomputation and posture re-derivation, then disbursement maturations, then auction closings, then mediation timeouts. The second runs the same sweep evaluation without advancing the clock (equivalent to `days` equal to zero) — used to flush any state that has fallen out of sync after a manual fix-up. Both return an empty data payload; their effect is purely in the cascades they trigger across the entities described in the preceding subsections.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`; endpoints that mutate or read an existing resource return HTTP 200. Error responses follow the standard envelope and the HTTP status codes catalogued in §5. The summary table below lists method, path, a one-line description, and the roles authorised to call each endpoint; the request body, response body, validation behaviour, and side effects are reconstructed from §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/borrowers` | Create a borrower. | `Servicer`, `PlatformAdmin` |
| POST | `/borrowers/{id}/hardship-attestation` | Record borrower hardship affidavit submission. | `Servicer`, `Borrower` |
| GET | `/borrowers/{id}` | Fetch a borrower. | `Servicer`, `PlatformAdmin`, `Borrower` |
| POST | `/loans` | Originate (book) a loan. | `Servicer`, `PlatformAdmin` |
| GET | `/loans/{id}` | Fetch a loan with all derived fields. | `Servicer`, `PlatformAdmin`, `Borrower`, `LossMitigationUnderwriter`, `PmiUnderwriter`, `ForeclosureAttorney` |
| GET | `/loans` | List loans with pagination and filters (`posture`, `pmi_status`, `borrower_id`). | `Servicer`, `PlatformAdmin` |
| POST | `/loans/{id}/payments` | Post a payment; runs the allocation waterfall; cascades posture. | `Servicer`, `Borrower` |
| POST | `/loans/{loan_id}/payments/{id}/reverse` | Reverse a posted payment. | `Servicer` |
| GET | `/loans/{id}/payments` | List payments on a loan (filter by `status`). | `Servicer`, `PlatformAdmin`, `Borrower` |
| POST | `/loans/{id}/escrow-analyses` | Create a `PROVISIONAL` escrow analysis. | `Servicer` |
| POST | `/loans/{loan_id}/escrow-analyses/{id}/finalize` | Finalize an escrow analysis; updates `monthly_escrow_payment_cents` and may emit a `SURPLUS_REFUND` disbursement. | `Servicer` |
| GET | `/loans/{id}/escrow-analyses` | List escrow analyses including `SUPERSEDED` (filter by `status`). | `Servicer`, `Borrower` |
| POST | `/loans/{id}/disbursements` | Schedule a tax or insurance disbursement. | `Servicer` |
| POST | `/loans/{loan_id}/disbursements/{id}/retry` | Retry a `FAILED` disbursement. | `Servicer` |
| POST | `/loans/{loan_id}/disbursements/{id}/cancel` | Cancel a `SCHEDULED` disbursement. | `Servicer` |
| GET | `/loans/{id}/disbursements` | List disbursements (filter by `status`, `type`). | `Servicer`, `Borrower`, `PlatformAdmin` |
| POST | `/loans/{id}/forbearance-plans` | Create and activate a forbearance plan. | `LossMitigationUnderwriter` |
| POST | `/loans/{loan_id}/forbearance-plans/{id}/cancel` | Cancel an `ACTIVE` forbearance plan before `end_date`. | `LossMitigationUnderwriter` |
| GET | `/loans/{id}/forbearance-plans` | List forbearance plans on a loan (filter by `status`). | `Servicer`, `LossMitigationUnderwriter`, `Borrower` |
| POST | `/loans/{id}/pmi-removal-requests` | File a PMI removal request. | `Servicer`, `Borrower` |
| POST | `/loans/{loan_id}/pmi-removal-requests/{id}/approve` | Underwriter approves removal. | `PmiUnderwriter` |
| POST | `/loans/{loan_id}/pmi-removal-requests/{id}/deny` | Underwriter denies removal. | `PmiUnderwriter` |
| POST | `/foreclosure-cases` | Open a foreclosure case (issues NOI). | `ForeclosureAttorney` |
| GET | `/foreclosure-cases/{id}/quote` | Compute current reinstatement quote (read-only). | `Servicer`, `Borrower`, `ForeclosureAttorney` |
| POST | `/foreclosure-cases/{id}/file` | File foreclosure in court (after NOI window). | `ForeclosureAttorney` |
| POST | `/foreclosure-cases/{id}/schedule-auction` | Schedule the foreclosure `auction_date`. | `ForeclosureAttorney` |
| POST | `/foreclosure-cases/{id}/reinstate` | Borrower pays full reinstatement quote (`payment_amount_cents`); case closes; loan reinstated. | `Servicer`, `Borrower` |
| GET | `/foreclosure-cases` | List foreclosure cases (filter by `status`, `loan_id`). | `ForeclosureAttorney`, `Servicer`, `PlatformAdmin` |
| POST | `/foreclosure-cases/{id}/mediation-cases` | Borrower requests pre-foreclosure mediation. | `Servicer`, `Borrower` |
| POST | `/mediation-cases/{id}/open` | Underwriter opens the mediation for negotiation. | `LossMitigationUnderwriter` |
| POST | `/mediation-cases/{id}/extend-offer` | Underwriter extends a HAMP-style modification offer. | `LossMitigationUnderwriter` |
| POST | `/mediation-cases/{id}/accept-offer` | Borrower accepts the extended offer. | `Borrower`, `Servicer` |
| POST | `/mediation-cases/{id}/reject-offer` | Borrower/underwriter rejects the offer with `rejection_reason`. | `Borrower`, `Servicer`, `LossMitigationUnderwriter` |
| POST | `/mediation-cases/{id}/complete` | Finalize an accepted offer; modifies loan; closes case as modified. | `LossMitigationUnderwriter` |
| POST | `/mediation-cases/{id}/fail` | End mediation in failure (manual cutoff). | `LossMitigationUnderwriter` |
| GET | `/mediation-cases/{id}` | Fetch a mediation case. | `LossMitigationUnderwriter`, `Servicer`, `Borrower`, `ForeclosureAttorney` |
| POST | `/_clock/advance` | Advance the server's logical clock by `days` and run time-gated transitions. | `PlatformAdmin` |
| POST | `/_sweep/run` | Run the periodic batch sweep without advancing the clock. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONCURRENT_UPDATE` | 409 |
| `ERR_ESCROW_ANALYSIS_CONFLICT` | 409 |
| `ERR_FORBEARANCE_PLAN_EXISTS` | 409 |
| `ERR_FORECLOSURE_CASE_EXISTS` | 409 |
| `ERR_MEDIATION_ALREADY_OPEN` | 409 |
| `ERR_NOI_WINDOW_NOT_ELAPSED` | 422 |
| `ERR_AUCTION_NOTICE_VIOLATION` | 422 |
| `ERR_MEDIATION_WINDOW_CLOSED` | 422 |
| `ERR_HARDSHIP_AFFIDAVIT_MISSING` | 422 |
| `ERR_REINSTATEMENT_CUTOFF` | 422 |
| `ERR_PMI_LTV_TOO_HIGH` | 422 |
| `ERR_PMI_HISTORY_INSUFFICIENT` | 422 |
| `ERR_HAMP_NOT_A_REDUCTION` | 422 |
| `ERR_HAMP_AFFORDABILITY_FLOOR` | 422 |
| `ERR_HAMP_STALE_OFFER` | 422 |
| `ERR_ESCROW_BASELINE_MISMATCH` | 422 |
| `ERR_PAYMENT_AMOUNT_INVALID` | 422 |
| `ERR_REINSTATEMENT_INSUFFICIENT` | 422 |
| `ERR_INSUFFICIENT_ESCROW` | 422 |
| `ERR_FORBEARANCE_DATE_INVALID` | 422 |
