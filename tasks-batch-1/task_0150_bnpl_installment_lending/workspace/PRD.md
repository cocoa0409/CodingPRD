# Bnpl Installment Lending API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Buy-Now-Pay-Later (BNPL) Installment Lending API, a servicing platform that lets consumers finance a merchant cart over a short installment plan and lets merchants receive settlement net of a discount fee. The platform sits between three parties: borrowers who apply for and repay financing, merchants who originate the sale and bear a clawback when goods come back, and a loan servicer who decides applications, releases settlements, and runs the operational machinery that ages the book over time.

The system's hardest problems are arithmetic and timing. The same financed amount produces two entirely different repayment schedules depending on whether the borrower chose a zero-interest Pay-in-4 plan or an amortized monthly plan, and a single partial return must simultaneously reduce the borrower's outstanding principal and claw money back from a settlement the merchant may already have been paid. Layered on top of that ledger work is a compliance spine: a loan cannot activate until the borrower has accepted a Truth-in-Lending (Reg Z) disclosure, settlements are held for a configurable window before release, and the riskiest servicer actions are guarded against acting on stale data. This specification defines every entity, calculation, state transition, and guard the implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly three roles: `Servicer`, `Borrower`, and `Merchant`. A request whose `X-User-Role` is missing or is not one of these three declared roles is rejected with `ERR_UNAUTHENTICATED`. A request whose role is syntactically valid but is not permitted to perform the requested operation — or where an ownership-bound actor targets a resource it does not own — is rejected with `ERR_FORBIDDEN`.

The `Servicer` role is an operational identity: when `X-User-Role` is `Servicer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; a servicer may act on any resource within its permitted operation set. The `Borrower` role is entity-backed: when `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`, and ownership checks on any resource that references a `Borrower` compare that resource's borrower foreign key to `X-User-ID`. A borrower may read and act only on its own borrower record, applications, loans, installments, payments, and autopay mandates. Likewise, the `Merchant` role is entity-backed: when `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of the acting `Merchant`, and ownership checks on any resource that references a `Merchant` compare that resource's merchant foreign key to `X-User-ID`. A merchant may read and act only on its own merchant record, applications, loans, returns, and settlements.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. The one documented exception is the installments listing, which is ordered by `sequence_no` ascending so that a loan's schedule reads in payment order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full filtered set before the page window is applied and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and Resource Identity

Most resources — merchants, borrowers, applications, loans, installments, payments, returns, autopay mandates, and merchant settlements — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, where `created_at` records first creation and `updated_at` is refreshed on every mutation. The `version` is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7.

The `DisclosureAcceptance` record is the sole exception. It is an immutable Reg Z audit artifact and therefore carries only `id` and `created_at`; it has no `updated_at` field and no `version` field, because it is never modified after creation.

### 2.5. Mutation Semantics, Cascades, and Aggregate Reconciliation

Many operations in this system mutate more than one resource. Whenever a write changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented. Several computed roll-up fields are kept continuously reconciled rather than recomputed on read. A borrower's `outstanding_principal_cents` is the sum of `remaining_principal_cents` over that borrower's loans whose `status` is `ACTIVE` or `DELINQUENT`, and its `available_credit_cents` is `eligible_credit_limit_cents` minus `outstanding_principal_cents`, never allowed below zero. A merchant's `gross_financed_cents` is the running sum of `financed_principal_cents` across that merchant's loans whose `status` is one of `ACTIVE`, `PAID_OFF`, `DELINQUENT`, or `DEFAULTED`, and its `net_settled_cents` is the sum, over that merchant's settlement rows whose `status` is `RELEASED`, of each row's `net_settlement_cents` minus its `clawed_back_cents`. Whenever an event changes any input to these roll-ups — an activation, a payment, a return, a default, a cancel, or a settlement release — the affected borrower and merchant aggregates are recomputed immediately.

### 2.6. Money, Days, and Rounding

All monetary amounts are integer cents. All rate inputs expressed in basis points (`mdr_bps`, `apr_bps`) denote hundredths of a percent, so a value of 10000 basis points is one hundred percent. Wherever a calculation must convert a fractional intermediate into integer cents, the rounding method is round half up unless the rule explicitly calls for a floor or a cap. Days-past-due and other day counts are whole integer days obtained by taking the floor of the elapsed time divided by one day. The specific rounding direction for each computed amount is stated with that calculation in §3; where a rule says a final installment "absorbs the residual," it means the last installment is set so that the per-installment amounts sum exactly to the schedule total, leaving no rounding drift.

### 2.7. Optimistic Concurrency Control on Loan Servicer Actions

Two servicer actions on a loan are guarded by optimistic concurrency control: declaring a loan defaulted and cancelling a loan. Each of these requests must carry an `expected_loan_version` field whose value is the `version` of the target loan the client last observed. The server compares `expected_loan_version` against the loan's current `version`; if a prior writer has advanced the loan's `version` since the client read it — for example, a payment-driven posture change, a competing cancel, or a competing default — the two values no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the servicer never acts on out-of-date loan state. This guard applies only to the default and cancel actions; no other endpoint accepts or requires `expected_loan_version`.

### 2.8. Validation Ordering and Left-to-Right Resolution

When a request could fail more than one check, the checks are evaluated in a fixed priority order so the returned error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation, or an entity-backed actor that does not own the target, yields `ERR_FORBIDDEN`. Existence is checked third: every identifier in the path and every foreign-key identifier in the body must resolve to an existing resource, validated left-to-right, with the first unresolved identifier yielding `ERR_NOT_FOUND`. Request-body schema validity is checked fourth, producing `ERR_INVALID_REQUEST`. Only after those four pass does the system evaluate state-legality, then uniqueness/idempotency, then the domain-specific safety, temporal, and fiscal rules described in §3. Each of those later checks is documented in §3 next to the workflow it guards, and each names the error it raises.

## 3. Business Logic & Workflows

### 3.1. Onboarding Merchants and Borrowers

A `Servicer` registers a merchant by supplying a `display_name`, an `mdr_bps` value (the merchant discount rate in basis points applied to financed principal at settlement, constrained to at least 0 and at most 1000), and an optional `settlement_hold_days`. The hold value is the number of whole days a loan's settlement is held after activation before it may be released; it must be at least 0 and at most 30, and when omitted it defaults to 2. A newly registered merchant starts with `status` `ACTIVE`, and its computed `gross_financed_cents` and `net_settled_cents` both begin at zero. A servicer may later suspend a merchant; suspension moves the merchant's `status` to `SUSPENDED`, after which the merchant can no longer originate new applications. Merchant records are readable by the servicer and by the owning merchant.

A `Servicer` also registers a borrower, supplying `full_name`, `email`, `annual_income_cents`, and `soft_credit_score`. The email must be unique across all borrowers; reusing an email is rejected with `ERR_DUPLICATE`. Annual income is self-reported in cents and must be at least 0. The soft-pull credit score is supplied at registration and must be at least 300 and at most 850. At registration the system computes the borrower's provisional `eligible_credit_limit_cents`, which is set once and remains static thereafter. The provisional limit is derived purely from the score and income: a score below 580 yields a base limit of 0 cents; a score of at least 580 but below 670 yields a base limit of 50000 cents; a score of at least 670 but below 740 yields a base limit of 200000 cents; and a score of at least 740 yields a base limit of 500000 cents. Separately, an income cap is computed as the floor of ten percent of `annual_income_cents`. The eligible credit limit is the smaller of the base limit and the income cap. After registration the borrower's `outstanding_principal_cents` and `available_credit_cents` are computed; with no loans yet, outstanding is zero and available equals the eligible limit. Borrower records are readable by the servicer and by the owning borrower.

### 3.2. Submitting and Pricing an Application

A `Borrower` submits a financing application against a merchant by providing `borrower_id` (which must match the acting borrower), `merchant_id`, the `cart_amount_cents` they wish to finance (which must be greater than 0), and the `plan_type`. The plan type is either `PAY_IN_4` or `MONTHLY`. For a `MONTHLY` plan, `term_months` is required and must be at least 3 and at most 24; for a `PAY_IN_4` plan, `term_months` must be omitted entirely, because Pay-in-4 is fixed at four bi-weekly installments. A borrower may also offer a `requested_down_payment_cents` up front; it defaults to 0, may be 0, must be at least 0, and must be strictly less than `cart_amount_cents`. A body that violates the schema — a missing required field, a bad enum, `term_months` present for Pay-in-4 or absent for Monthly, or a requested down payment not strictly below the cart amount — is rejected with `ERR_INVALID_REQUEST`.

A submitted application starts in `SUBMITTED` status and is immediately priced on a provisional basis. The annual percentage rate, `apr_bps`, is 0 for a `PAY_IN_4` plan and is the fixed constant 1990 basis points (19.90%) for a `MONTHLY` plan. The provisional `financed_principal_cents` is `cart_amount_cents` minus the down payment under consideration (the requested down payment provisionally; the approved down payment once a decision is made). The provisional `finance_charge_cents` is the total Reg Z finance charge — the sum of interest across the schedule — and is 0 for Pay-in-4. The provisional `total_of_payments_cents` is `financed_principal_cents` plus `finance_charge_cents`. The pricing dependency is resolved in a pinned order so that the apparently circular relationship between the down payment, the financed principal, the schedule, and the finance charge is well-defined: first the down payment under consideration is fixed, then the financed principal is set to `cart_amount_cents` minus that down payment, then the installment schedule is built on that financed principal (see §3.4), then the finance charge is set to the sum of the per-installment `amount_due_cents` minus the financed principal, and finally the total of payments is set to the financed principal plus the finance charge. For Pay-in-4 the finance charge is exactly 0 and the total of payments equals the financed principal. Because the finance charge is derived from the already-rounded schedule (the schedule is built before the finance charge is summed), it equals the sum of the per-installment interest exactly. Applications are readable by the servicer, the owning borrower, and the merchant on the application; they may be listed and filtered by `borrower_id` or `merchant_id`.

### 3.3. The Servicer Decision and the Counter-Revision Loop

A `Servicer` decides a `SUBMITTED` application by supplying a `decision` of APPROVE, COUNTER, or DECLINE; the application must be in `SUBMITTED` status for any decision to be legal, and an illegal-state attempt is rejected with `ERR_INVALID_STATE`. The decision logic re-evaluates eligibility against the borrower's live credit. The borrower's available credit at decision time is the greater of zero and `eligible_credit_limit_cents` minus the current `outstanding_principal_cents`. The amount the borrower needs financed is `cart_amount_cents` minus `requested_down_payment_cents`. Four outcomes follow, distinguished as siblings of the same decision:

When the merchant on the application has `status` `SUSPENDED`, the decision takes the decline branch with `decline_reason` set to `MERCHANT_SUSPENDED`. Otherwise, when the borrower's available credit is exactly 0, the application is declined with `decline_reason` `INSUFFICIENT_CREDIT`. When available credit is positive and the needed amount is at most the available credit, the application is approved: it moves from `SUBMITTED` to `APPROVED`, and `approved_down_payment_cents` is fixed equal to `requested_down_payment_cents`. When the needed amount exceeds available credit but the cart could still fit the limit with a larger down payment — specifically when `cart_amount_cents` minus one cent is at most the available credit — the application is countered: it moves from `SUBMITTED` to `COUNTERED`, and `approved_down_payment_cents` is raised to the minimum down payment that fits the limit, namely `cart_amount_cents` minus the available credit. When even a down payment of the full cart minus one cent cannot fit the limit, the application is declined with `decline_reason` `DOWN_PAYMENT_TOO_LOW`. On both the approve and counter branches the system recomputes `apr_bps`, `financed_principal_cents`, `finance_charge_cents`, and `total_of_payments_cents` off the fixed down payment using the pinned pricing order; on the decline branch only the `decline_reason` is set.

A countered application can re-enter the pipeline through a revision loop. The owning `Borrower` revises a `COUNTERED` application by submitting a new `requested_down_payment_cents`; this is legal only while the application is in `COUNTERED` status, and the new value must be at least the countered `approved_down_payment_cents`. A successful revision writes the new requested down payment and returns the application from `COUNTERED` back to `SUBMITTED` for a fresh decision. A `Borrower` may instead withdraw an application that is in either `SUBMITTED` or `COUNTERED` status, which moves it to the terminal `WITHDRAWN` state; a withdraw attempt from any other state is rejected with `ERR_INVALID_STATE`. The terminal application states are `DECLINED`, `WITHDRAWN`, and `ACTIVATED`.

### 3.4. Reg Z Disclosure and Loan Activation

Before an approved application can become a loan, the borrower must accept the Truth-in-Lending disclosure. A `Borrower` records a disclosure acceptance against an `APPROVED` application by supplying the `application_id` and an `accepted` boolean. At creation the system snapshots the application's current figures onto the immutable acceptance record: `disclosed_apr_bps` from the application's `apr_bps`, `disclosed_finance_charge_cents` from its `finance_charge_cents`, `disclosed_total_of_payments_cents` from its `total_of_payments_cents`, and `disclosed_installment_count` as the number of scheduled installments. An acceptance with `accepted` set to false does not satisfy the gate; activation attempted without an acceptance whose `accepted` is true is rejected with `ERR_DISCLOSURE_NOT_ACCEPTED`. Disclosure records are readable by the servicer and the owning borrower and may be listed and filtered by `application_id`.

A `Borrower` activates an `APPROVED` application by supplying the `application_id`; this drives the application from `APPROVED` to the terminal `ACTIVATED` state and originates the loan. Activation requires two preconditions: an accepted disclosure must exist for the application (otherwise `ERR_DISCLOSURE_NOT_ACCEPTED`), and the borrower's `available_credit_cents` must still be at least the application's `financed_principal_cents` at the moment of activation (otherwise `ERR_INSUFFICIENT_CREDIT`). Exactly one accepted disclosure is consumed per activation; a duplicate consumption is rejected with `ERR_DUPLICATE`. On activation, a `Loan` is created in lifecycle `status` `ACTIVE` with `delinquency_status` `CURRENT`. The loan copies `application_id`, `borrower_id`, and `merchant_id`, and snapshots `financed_principal_cents`, `apr_bps`, and `finance_charge_cents` from the application. Activation then generates the installment schedule, creates a pending merchant settlement, and recomputes the borrower's `outstanding_principal_cents` and `available_credit_cents` and the merchant's `gross_financed_cents`.

The installment schedule is built from the loan's financed principal (call it the principal) and the activation date, which is the loan's `created_at` interpreted as a UTC date, by one of two variants. Under the Pay-in-4 variant (when `apr_bps` is 0), there are four bi-weekly installments. A base amount is the floor of the principal divided by four, and the residual is the principal minus four times the base. Installments one through four are due at the activation date plus 0, 14, 28, and 42 days respectively. Each of installments one through three has an `amount_due_cents` equal to the base; installment four has an `amount_due_cents` equal to the base plus the residual. Because Pay-in-4 carries zero interest, each installment's `principal_portion_cents` equals its `amount_due_cents`. Under the Monthly variant (when `apr_bps` is 1990) with `term_months` equal to N, the schedule amortizes the principal over N monthly installments. The monthly periodic rate is `apr_bps` divided by 10000 and then by 12, carried at full floating precision. When that rate is zero the level payment is the principal divided by N; otherwise the level payment is the standard amortization payment — the principal multiplied by the rate, multiplied by the quantity one plus the rate raised to the N-th power, divided by the quantity of one plus the rate raised to the N-th power minus one. Each of installments one through N minus one has an `amount_due_cents` equal to the level payment rounded half up; the final installment's `amount_due_cents` is the `total_of_payments_cents` minus the sum of the first N minus one amounts, so the last installment absorbs the residual. The per-installment principal split is derived by walking a running balance starting at the principal: for each installment in order, the interest is the running balance multiplied by the rate, rounded half up; that installment's `principal_portion_cents` is its `amount_due_cents` minus that interest; the running balance is then reduced by that principal portion. After the last installment, any leftover balance is added to the final installment's principal portion so that the principal portions sum exactly to the financed principal. Monthly installments one through N are due at the activation date plus i times 30 days for the i-th installment. Across both variants amounts are integer cents, each per-installment amount is rounded half up, and the last installment absorbs the residual so the `amount_due_cents` sum to `total_of_payments_cents` and the `principal_portion_cents` sum to `financed_principal_cents`. Each installment carries a 1-based `sequence_no` (at least 1) that is the ordering key for allocation and posture, a `due_date` as an ISO 8601 UTC datetime, its `amount_due_cents` and `principal_portion_cents`, a computed `amount_paid_cents`, a computed `late_fee_cents`, and a `status` that begins `SCHEDULED`. An installment references its owning loan through `loan_id`. Installments are readable by the servicer, owning borrower, and merchant, and may be listed and filtered by `loan_id`.

### 3.5. The Loan Ledger: Payments, Allocation, and Pay-Off

A loan tracks several computed balances. Its `remaining_principal_cents` is the financed principal minus the principal paid across `PAID` installments, floored at zero. Its `total_paid_cents` is the sum of `amount_cents` across all of the loan's payments regardless of source. Its `late_fee_accrued_cents` is the sum of `late_fee_cents` across the loan's installments that became `LATE` or `PAID` after a late fee was assessed. A loan's lifecycle `status` is one of `ACTIVE`, `PAID_OFF`, `DEFAULTED`, or `CANCELLED`, with `PAID_OFF`, `DEFAULTED`, and `CANCELLED` terminal; in parallel, its `delinquency_status` is one of `CURRENT`, `LATE`, or `DELINQUENT` and evolves independently of the lifecycle, so a loan can be `ACTIVE` and `CURRENT` or `ACTIVE` and `DELINQUENT` at the same time. Loans are readable by the servicer, owning borrower, and merchant, and may be listed and filtered by `borrower_id`, `merchant_id`, or `application_id`.

A `Borrower` pays its own loan by supplying the `loan_id`, an `amount_cents` greater than zero, and an optional `source` of `MANUAL` or `AUTOPAY` that defaults to `MANUAL`; a non-positive amount fails request validation with `ERR_INVALID_REQUEST`. The payment is allocated oldest-due-first: the loan's installments whose `status` is `SCHEDULED` or `LATE` are ordered by ascending `sequence_no`, with ties broken by `created_at` ascending and then `sequence_no` ascending. Walking that order, for each installment the amount still needed is its `amount_due_cents` minus its `amount_paid_cents`; the amount applied is the lesser of the payment money remaining and that need; the installment's `amount_paid_cents` is increased by the applied amount and the remaining payment is decreased by it; and once an installment's `amount_paid_cents` reaches its `amount_due_cents` the installment transitions to `PAID`. The resulting per-installment breakdown is recorded as the payment's `allocation`, an ordered list of installment-and-applied-amount entries. Any payment money left after every open installment is exhausted is recorded as the payment's `unapplied_cents` — an overpayment that no open installment could absorb, refunded to the borrower's balance. Allocation is pure integer arithmetic with no rounding, and late fees tracked in `late_fee_accrued_cents` are not consumed by this allocation. When an installment is fully covered and transitions to `PAID`, the loan's `remaining_principal_cents` is reduced by that installment's `principal_portion_cents` and the loan's `delinquency_status` is recomputed. If a payment drives `remaining_principal_cents` to zero and leaves no installment in `SCHEDULED` or `LATE`, the loan bubbles up from `ACTIVE` to `PAID_OFF`; on pay-off the `delinquency_status` is forced to `CURRENT`, any `ENABLED` autopay mandate on the loan is moved to `DISABLED`, and the borrower's outstanding and available credit are recomputed. Payments are readable by the servicer, owning borrower, and merchant, and may be listed and filtered by `loan_id`.

### 3.6. Aging the Book: the Clock, Late Fees, and Delinquency Posture

The platform's sense of "now" is driven by an operator clock. A `Servicer` advances the logical clock by supplying a target instant as `to_iso8601`; this sets the server's current UTC instant and drives all due-date, late-fee, delinquency, and settlement-hold evaluation. Advancing the clock returns the new `now` and the list of `transitioned_installment_ids` it moved. On each advance, every `SCHEDULED` installment whose due date plus the grace period has passed transitions to `LATE` and is assessed a late fee, and every `ACTIVE` loan's `delinquency_status` is recomputed.

An installment becomes `LATE` only when the current instant is strictly after its `due_date` plus the grace period of 10 days; an instant exactly equal to the due date plus 10 days is still on time. When an installment becomes `LATE`, its outstanding amount is its `amount_due_cents` minus its `amount_paid_cents`, and its `late_fee_cents` is set to that outstanding multiplied by the late-fee rate of five percent, rounded half up, then clamped to be at least the floor of 700 cents and at most the cap of 1500 cents. A late fee is assessed at most once per installment, so repeated clock advances do not re-charge an installment already assessed. When a fee is assessed the loan's `late_fee_accrued_cents` is recomputed and its `delinquency_status` is recomputed.

Delinquency posture is recomputed on every payment, every return, and every clock advance. The system finds the oldest unpaid installment — the one with the smallest `sequence_no` among installments whose `status` is `SCHEDULED` or `LATE`, ties broken by `created_at` ascending; if there is no such installment the `delinquency_status` is `CURRENT`. Otherwise the days-past-due is the floor of the elapsed time between now and that installment's `due_date` divided by one day, which may be negative. If the days-past-due is negative, or the oldest installment is not yet past its due date plus the grace period of 10 days, the posture is `CURRENT`. If the days-past-due is at least the delinquency threshold of 30 days, the posture is `DELINQUENT`. Otherwise — the oldest installment is `LATE` but its days-past-due is below 30 — the posture is `LATE`.

### 3.7. Autopay and the Servicer Sweep

A `Borrower` enables autopay on a loan by supplying the `loan_id`; the resulting `AutopayMandate` copies `borrower_id` from the loan and starts in `status` `ENABLED`. At most one autopay mandate may exist per loan; a second mandate on the same loan is rejected with `ERR_DUPLICATE`. A borrower may disable a mandate, moving its `status` to `DISABLED`; only `ENABLED` mandates may be charged by the servicer sweep. Mandates are readable by the servicer and owning borrower and may be listed and filtered by `loan_id` or `borrower_id`.

A `Servicer` runs the autopay sweep, an operator capability that charges every `ENABLED` autopay mandate whose loan has an installment due on or before now, oldest-due-first, for the amount of the next due installment. The sweep returns the count of mandates charged as `charged_count` and the ids of the payments it created as `payment_ids`. Each charge creates an `AUTOPAY`-sourced payment that runs through exactly the same oldest-due-first allocation and the same cascade — installment pay-off, principal reduction, posture recomputation, and possible loan pay-off — as a manual payment.

### 3.8. Merchant Settlement and the Hold Window

When a loan activates, the system creates one `MerchantSettlement` row for the merchant, copying `merchant_id` and `loan_id` and snapshotting the loan's `financed_principal_cents` into the settlement's `gross_financed_cents`. The settlement's `mdr_fee_cents` is the merchant discount fee, computed at origination as the gross financed amount multiplied by the merchant's `mdr_bps` divided by 10000, rounded half up. Its `net_settlement_cents` is the gross financed amount minus that fee. Its `clawed_back_cents` begins at 0, and its `status` begins `PENDING`. The merchant's `net_settled_cents` rollup is the sum, over that merchant's settlement rows whose `status` is `RELEASED`, of each row's `net_settlement_cents` minus its `clawed_back_cents`. Settlements are readable by the servicer and the owning merchant and may be listed and filtered by `merchant_id` or `loan_id`.

A `Servicer` releases a held settlement once the hold window has elapsed. Release moves the settlement from `PENDING` to `RELEASED` and is legal only when two preconditions hold: the current instant must be at or after the loan's `created_at` plus the merchant's `settlement_hold_days` (otherwise `ERR_SETTLEMENT_HOLD_ACTIVE`), and the loan's lifecycle `status` must be `ACTIVE` (otherwise `ERR_INVALID_STATE`, which covers the case where the loan was cancelled or defaulted while the settlement was still pending). On release the merchant's `net_settled_cents` is recomputed, adding this row's `net_settlement_cents` minus its `clawed_back_cents`. A settlement that is still `PENDING` moves to `CLAWED_BACK` when its cumulative `clawed_back_cents` reaches its `net_settlement_cents`, whether driven by a loan cancel, a loan default while still pending, or a return; because a pending settlement never contributed to the rollup, the default-or-cancel path causes no change to `net_settled_cents`. A settlement that is already `RELEASED` moves to `CLAWED_BACK` only via a return whose clawback drives `clawed_back_cents` to `net_settlement_cents`, and in that case the previously released net is reversed back out of the merchant's `net_settled_cents` (a fully clawed-back row no longer counts among `RELEASED` rows). A `RELEASED` settlement that is only partially clawed back stays `RELEASED`, with the merchant's rollup reflecting `net_settlement_cents` minus `clawed_back_cents`.

### 3.9. Partial Returns: Principal Reallocation and Settlement Clawback

A `Merchant` posts a partial return against one of its own loans by supplying the `loan_id` and a `return_amount_cents` greater than zero; the return copies `merchant_id` from the loan and starts and stays in `status` `POSTED`, which is terminal once reallocation completes. The return amount must not exceed what the loan can absorb: a return whose amount exceeds the cart amount is rejected with `ERR_INSUFFICIENT_CREDIT`. Returns are readable by the servicer, owning borrower, and merchant, and may be listed and filtered by `loan_id` or `merchant_id`.

The reallocation is performed in a pinned order. First, the `principal_reduction_cents` is the lesser of `return_amount_cents` and the loan's `remaining_principal_cents`. Second, that principal reduction is distributed across the loan's unpaid installments — those whose `status` is `SCHEDULED` or `LATE` — newest-due-first, in descending `sequence_no`, reducing each installment's outstanding (its `amount_due_cents` minus its `amount_paid_cents`) before moving to the next; an installment whose outstanding is fully covered is moved to `CANCELLED`. Third, the rounding order is pinned so that when a reduction lands mid-installment, the installment's `amount_due_cents` is reduced by the exact integer cents removed — the reduction is a single integer subtraction applied directly, never distributed pro-rata and then rounded — so the sum of reductions equals `principal_reduction_cents` exactly. Fourth, the merchant keeps its discount on returned goods but the net principal is clawed back: the MDR portion on the return is `return_amount_cents` multiplied by the merchant's `mdr_bps` divided by 10000, rounded half up, and the `settlement_clawback_cents` is the lesser of `return_amount_cents` minus that MDR portion and the settlement's remaining net (its `net_settlement_cents` minus its current `clawed_back_cents`). That clawback is added to the settlement's `clawed_back_cents`; if the cumulative clawback reaches `net_settlement_cents` the settlement moves to `CLAWED_BACK` and any previously released net is reversed out of the merchant's `net_settled_cents` as described in §3.8. Fifth, if the reallocation drives `remaining_principal_cents` to zero and leaves no installment in `SCHEDULED` or `LATE`, the loan bubbles up to `PAID_OFF`. A return recomputes the loan's delinquency posture as well.

### 3.10. Servicer Loss Actions: Default and Cancel

Two terminal servicer actions close out a troubled loan, and both are guarded by optimistic concurrency control as described in §2.7. A `Servicer` declares a loan `DEFAULTED` from `ACTIVE` by supplying `expected_loan_version`. The action is legal only when the loan's `delinquency_status` is `DELINQUENT` (otherwise `ERR_NOT_DELINQUENT`) and `expected_loan_version` matches the loan's current `version` (otherwise `ERR_STALE_VERSION` at HTTP 412). On default the loan's `version` is incremented by one, every `SCHEDULED` or `LATE` installment is written off to `WRITTEN_OFF` and excluded from remaining-principal accounting, any `ENABLED` autopay mandate is disabled, and the merchant settlement is handled by state: a still-`PENDING` settlement is clawed back in full to `CLAWED_BACK`, while an already-`RELEASED` settlement is left unchanged. The borrower's `outstanding_principal_cents` and `available_credit_cents` are then recomputed.

A `Servicer` cancels a loan from `ACTIVE` by supplying `expected_loan_version`. Cancel is legal only when no payment has yet been made on the loan — its `total_paid_cents` must be 0, otherwise `ERR_LOAN_HAS_PAYMENTS` — and when `expected_loan_version` matches the loan's current `version`, otherwise `ERR_STALE_VERSION` at HTTP 412. On cancel the loan's `version` is incremented by one, every installment is moved to `CANCELLED` (a still-`SCHEDULED` installment has its `amount_due_cents` reduced to its `amount_paid_cents` and is excluded from posture; a `LATE` installment is likewise cancelled), the merchant settlement is clawed back in full to `CLAWED_BACK`, any autopay mandate is disabled, and the borrower and merchant aggregates are recomputed. Because the cancel and default actions both end the loan and both increment its `version`, a client that read the loan before a competing servicer write will see its `expected_loan_version` rejected on the second action.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, and read operations, return `200 OK`. The two operator endpoints (the autopay sweep and the clock) return `200 OK`. Each endpoint's request and response payloads are reconstructed from the workflow narratives in §3; the table below lists only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/merchants` | Register a merchant | Servicer |
| GET | `/merchants/{id}` | Fetch a merchant (includes computed gross/net settled) | Servicer, Merchant |
| POST | `/merchants/{id}/suspend` | Suspend a merchant | Servicer |
| POST | `/borrowers` | Register a borrower; computes provisional credit limit | Servicer |
| GET | `/borrowers/{id}` | Fetch a borrower (includes computed credit fields) | Servicer, Borrower |
| POST | `/applications` | Submit a financing application | Borrower |
| GET | `/applications/{id}` | Fetch an application | Servicer, Borrower, Merchant |
| GET | `/applications` | List applications (filter by borrower or merchant) | Servicer, Borrower, Merchant |
| POST | `/applications/{id}/decision` | Decide an application (APPROVE / COUNTER / DECLINE) | Servicer |
| POST | `/applications/{id}/revise` | Revise a countered application's down payment | Borrower |
| POST | `/applications/{id}/withdraw` | Withdraw a submitted or countered application | Borrower |
| POST | `/disclosure-acceptances` | Accept or reject the Reg Z disclosure | Borrower |
| GET | `/disclosure-acceptances/{id}` | Fetch a disclosure acceptance record | Servicer, Borrower |
| GET | `/disclosure-acceptances` | List disclosure acceptances (filter by application) | Servicer, Borrower |
| POST | `/loans` | Activate an approved application into a loan | Borrower |
| GET | `/loans/{id}` | Fetch a loan | Servicer, Borrower, Merchant |
| GET | `/loans` | List loans (filter by borrower, merchant, or application) | Servicer, Borrower, Merchant |
| POST | `/loans/{id}/default` | Declare a delinquent loan defaulted (OCC-guarded) | Servicer |
| POST | `/loans/{id}/cancel` | Cancel a no-payment loan (OCC-guarded) | Servicer |
| GET | `/installments/{id}` | Fetch a single installment | Servicer, Borrower, Merchant |
| GET | `/installments` | List installments (filter by loan), ordered by sequence_no | Servicer, Borrower, Merchant |
| POST | `/payments` | Make a manual payment against a loan | Borrower |
| GET | `/payments/{id}` | Fetch a payment (includes allocation breakdown) | Servicer, Borrower, Merchant |
| GET | `/payments` | List payments (filter by loan) | Servicer, Borrower, Merchant |
| POST | `/returns` | Post a partial return on a loan | Merchant |
| GET | `/returns/{id}` | Fetch a single return | Servicer, Borrower, Merchant |
| GET | `/returns` | List returns (filter by loan or merchant) | Servicer, Borrower, Merchant |
| POST | `/autopay-mandates` | Enable autopay on an active loan | Borrower |
| GET | `/autopay-mandates` | List autopay mandates (filter by loan or borrower) | Servicer, Borrower |
| GET | `/autopay-mandates/{id}` | Fetch a single autopay mandate | Servicer, Borrower |
| POST | `/autopay-mandates/{id}/disable` | Disable an autopay mandate | Borrower |
| GET | `/merchant-settlements/{id}` | Fetch a settlement row | Servicer, Merchant |
| GET | `/merchant-settlements` | List settlements (filter by merchant or loan) | Servicer, Merchant |
| POST | `/merchant-settlements/{id}/release` | Release a held settlement after the hold window | Servicer |
| POST | `/_servicer/run_autopay_sweep` | Charge every enabled autopay mandate due | Servicer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant | Servicer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_DISCLOSURE_NOT_ACCEPTED` | 409 |
| `ERR_SETTLEMENT_HOLD_ACTIVE` | 409 |
| `ERR_NOT_DELINQUENT` | 409 |
| `ERR_LOAN_HAS_PAYMENTS` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 409 |
| `ERR_STALE_VERSION` | 412 |
