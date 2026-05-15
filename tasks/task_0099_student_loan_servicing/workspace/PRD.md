# Fed Student Loan Servicing API — Product Requirements Document

## 1. Introduction

The federal student loan servicing landscape places a unique reconciliation burden on whoever holds the master ledger: every dollar that moves between a borrower and the government must be allocated against a portfolio of heterogeneous loans, each carrying its own interest clock, subsidy treatment, repayment plan, and compliance posture. A single late month can cascade through delinquency, default, and collections; a single approved Public Service Loan Forgiveness (PSLF) application can wipe out six figures of debt; a single misapplied payment can silently strip away years of qualifying credit. The cost of "almost right" is not a customer-service ticket — it is a regulator's audit finding.

This document specifies the contract for a back-office servicing platform that supports the major federal Direct Loan products, Income-Driven Repayment (IDR) plans, hardship relief (deferment and forbearance), PSLF and Veteran Total and Permanent Disability (TPD) discharge programs, and the collections lifecycle from delinquency through rehabilitation. The platform is operated by segregated roles — origination, certification, approval, and collections — under strict duties separation, and it exposes a deterministic simulation clock so that time-gated transitions (grace exit, default declaration, rehab completion, recertification) can be exercised end-to-end. Where rules conflict, fiscal correctness and statutory eligibility outrank operator convenience.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the liveness probe must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the system's declared roles. When either header is missing or empty the request is rejected with `ERR_AUTH_REQUIRED`. When the supplied role is not one of the recognized role names, or when the role is recognized but is not permitted to invoke the requested endpoint per the role/endpoint matrix, the response is `ERR_FORBIDDEN`.

The system declares six roles: `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover`, `CollectionsOfficer`, `Borrower`, and `SystemTest`.

- A `ServicerAdmin` originates loans, configures borrowers, and runs administrative actions such as advancing the simulation clock. `X-User-ID` for a `ServicerAdmin` is an opaque operator identifier not tied to any persisted entity; the server records who acted on a discharge application via `reviewed_by` and who recorded a collections action via `recorded_by`, but it does not compare the operator id to any borrower record.
- A `ServicerCertifier` certifies employment certifications and hardship requests, and may move a discharge application out of `SUBMITTED`. `X-User-ID` is likewise opaque; the certifier's id is captured in `reviewed_by` on the certifications and hardship requests they act on.
- A `ServicerApprover` is the only role permitted to approve or reject a discharge application that is `UNDER_REVIEW`. Their `X-User-ID` is opaque and is captured in `reviewed_by` on the discharge application they act on. Segregation of duties (described below in §2.4) requires that this id differ from the certifier id on the supporting employment evidence.
- A `CollectionsOfficer` records collections actions, garnishments, and rehab payments. The operator id is opaque and is stored as `recorded_by` on each `CollectionsAction`.
- A `Borrower` is the end user, and is the only role whose identity is entity-backed. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower` record; ownership checks on any nested resource (loan, plan, payment, hardship request, discharge application, employment certification) compare that resource's `borrower_id` field to `X-User-ID`, and a borrower may not read or mutate another borrower's resources.
- A `SystemTest` role is reserved for test fixtures: it may advance the simulation clock and probe `/_health`. Its `X-User-ID` is opaque and is not tied to any persisted entity.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be an integer of at least 1, and must not exceed 100. `offset` defaults to 0 and must be at least 0. Any value outside these bounds is rejected with `ERR_PAGINATION_INVALID`. Results are sorted by `created_at` in ascending order. The `meta` object on a list response includes `limit`, `offset`, `total_count`, and `has_more` — `total_count` reports the total number of records that match the filter set ignoring pagination, and `has_more` is `true` when `offset + limit < total_count`.

### 2.4. Resource Identity, Audit Stamps, and Optimistic Concurrency

Every persisted resource is assigned a server-minted `id` that is a UUID string with no type prefix. Resources whose lifecycle includes mutation — `Borrower`, `Loan`, `RepaymentPlan`, `HardshipRequest`, `DischargeApplication`, and `EmploymentCertification` — additionally carry three system fields: `created_at` (the ISO 8601 UTC timestamp with three fractional digits at which the resource was inserted), `updated_at` (refreshed on every mutation), and `version` (an integer that starts at 1 on creation and increments by 1 on every successful mutation). Resources that are immutable once written — `Payment`, `CollectionsAction`, and the singleton `ClockState` — carry only `id` and `created_at`; neither `updated_at` nor `version` is present on those records.

Mutating endpoints that update one of the versioned resources may accept an optional `version` field in the request body. When the caller supplies `version`, the server compares it to the resource's current version, and on mismatch rejects the request with `ERR_VERSION_CONFLICT`. When `version` is omitted the optimistic-concurrency check is skipped and the latest stored version is used. A successful mutation always increments `version` by 1 and refreshes `updated_at` to the current clock value.

### 2.5. Money, Rates, and Rounding

All monetary quantities in this system are integers expressed in cents — there are no fractional cents anywhere in storage. Interest rates are likewise represented as integer basis points (`interest_rate_bps`), where one basis point is one hundredth of one percent of an annual rate; for example, a 5.00% annual rate is stored as 500 basis points.

Whenever a calculation produces a non-integer cent result — interest accrual, amortization, share-of-pool — the result is rounded half-up to the nearest integer cent before it is written to a field. The rounding step is the **final** step of the calculation; intermediate sums are kept in their natural precision (cents and ratios) until the rounding point is reached. The exact rounding point for each calculation is pinned in §3, because different rounding orders (per-loan-per-call vs. per-day vs. after-summing) produce materially different ledger values.

### 2.6. The Simulation Clock and Chronological Side Effects

Time is not implicit in this system: there is a server-controlled simulation clock, exposed as a singleton `ClockState` whose only field is `now`. Advancing the clock is the trigger for the entire chronological side-effect cascade — daily interest accrual, grace-period exit, delinquency aging, automatic default, deferment and forbearance auto-exit at their requested end date, and rehab completion when nine qualifying payments accumulate inside a ten-month window. Advancing the clock is an administrative action: the request body carries a single `to` field, an ISO 8601 UTC timestamp; the new value of `now` is set to `to` and every loan whose status places it in the accruing set has its interest re-accrued from `last_accrual_at` to the new `now` in a single per-loan rounding step.

### 2.7. Nested Resource Path Resolution

Every nested endpoint validates its path parameters strictly from left to right. The `{borrower_id}` segment is resolved first: if no borrower with that `id` exists the response is `ERR_BORROWER_NOT_FOUND`. The remaining nested id — whichever of `{loan_id}`, `{plan_id}`, `{request_id}`, `{application_id}`, or `{certification_id}` is present — is then resolved against that borrower; if the sub-resource does not exist, or exists but belongs to a different borrower, the response is `ERR_RESOURCE_NOT_FOUND`. Foreign-key fields in the request body — `included_loan_ids`, `applied_loan_ids`, `approved_loan_ids` — receive the same scoped check: any element that does not reference an existing loan owned by the path borrower triggers `ERR_LOAN_NOT_FOUND`.

### 2.8. Validation Ordering

When multiple validations apply to the same request, they are evaluated in the priority order spelled out below, and the first failure short-circuits the rest. The order matters: tests will assert that, when a request would fail several validations at once, the error returned is the one with the lowest priority number from the list. The order is: authentication header presence (`ERR_AUTH_REQUIRED`); then role recognition and role-endpoint authorization (`ERR_FORBIDDEN`); then existence of the `{borrower_id}` segment (`ERR_BORROWER_NOT_FOUND`); then existence of any nested id (`ERR_RESOURCE_NOT_FOUND`); then existence of any request-body foreign keys (`ERR_LOAN_NOT_FOUND`); then state-machine eligibility of the target resource (`ERR_INVALID_STATE`); then business-safety checks (segregation of duties — `ERR_SOD_VIOLATION` — and veteran-eligibility — `ERR_VETERAN_INELIGIBLE`); then business-referential checks (PSLF employment evidence — `ERR_PSLF_NO_EMPLOYMENT_EVIDENCE` — and PSLF payment-count threshold — `ERR_PSLF_INSUFFICIENT_PAYMENTS`); then business-temporal checks (`ERR_BAD_DATE_WINDOW`, `ERR_FORBEARANCE_CAP_EXCEEDED`); then business-referential and business-constraint checks specific to plans and rehab (`ERR_PLAN_LOAN_INELIGIBLE`, `ERR_AGI_NOT_CERTIFIED`, `ERR_PLAN_CONFLICT`, `ERR_REHAB_ALREADY_USED`, `ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL`); then fiscal-shape checks (`ERR_AMOUNT_INVALID`); then optimistic-concurrency (`ERR_VERSION_CONFLICT`); finally pagination input shape (`ERR_PAGINATION_INVALID`).

### 2.9. Segregation of Duties

The discharge process is the system's most consequential write — it can zero out balances totalling six or seven figures — and is therefore protected by an explicit duty-segregation rule. The `ServicerApprover` whose `X-User-ID` accompanies the request that moves a `DischargeApplication` to `APPROVED` must not equal any `ServicerCertifier`'s `X-User-ID` recorded as `reviewed_by` on an `EmploymentCertification` that is in `APPROVED` status for this borrower. When the two ids match, the request is rejected with `ERR_SOD_VIOLATION` — and per §2.8 this safety check fires before the PSLF qualifying-count check or the veteran-eligibility check, so an approver who is also the certifier cannot accidentally discover whether their borrower would otherwise have been eligible.

### 2.10. Concurrency and Serialization Guarantees

The system serializes mutations that race on the same resource. Five named scenarios merit specific guarantees:

- When two activate calls land at nearly the same time on two different plans whose `included_loan_ids` overlap on at least one loan for the same borrower, the server preserves the invariant that at most one `ACTIVE` plan covers any given loan. The first writer wins on `effective_from` per included loan; the second activation is rejected with `ERR_PLAN_CONFLICT`.
- When a borrower payment lands on a loan that is at the 270-day delinquency threshold while the system is also about to declare default, the first writer wins on the loan's `status`. If the payment commits first and cures `days_past_due`, the default declaration is skipped entirely. If the default declaration commits first, the incoming payment is allocated against the now-defaulted loan and does not trigger auto-rehab — rehab requires an explicit `REHAB_AGREEMENT_OPEN` collections action. The losing operation that finds the loan already in the contrary state is rejected with `ERR_INVALID_STATE`.
- When two `ServicerApprover` operators try to approve the same `DischargeApplication` simultaneously, exactly one approval wins. The loser observes the application has already moved out of `UNDER_REVIEW` and receives `ERR_INVALID_STATE`.
- When a hardship-request approval races with a payment that cures delinquency on the same loan, the first writer wins on `Loan.status`. Whichever transition no longer holds its preconditions becomes a no-op (if its preconditions have been satisfied incidentally) or is rejected with `ERR_INVALID_STATE`.
- When two `PATCH` calls update the same `HardshipRequest`, the OCC check applies: a stale `version` value loses with `ERR_VERSION_CONFLICT`. The same OCC rule governs every other `PATCH` endpoint that accepts `version?` in its body.

### 2.11. Side-Effect Cascades and Aggregate Reconciliation

Several state transitions in §3 reach beyond a single entity. Whenever a `Loan` mutates — its principal, accrued interest, or status changes — the borrower's `aggregate_principal_balance_cents` and `aggregate_interest_balance_cents` are recomputed as the sums of `principal_balance_cents` and `accrued_interest_cents` across that borrower's non-terminal loans. A loan that has reached either of the two terminal statuses (`PAID_OFF` or `DISCHARGED`) drops out of the aggregate. Every cascaded mutation bumps the owning resource's `version` by 1 and refreshes its `updated_at`; this is the serialization point that drives `ERR_VERSION_CONFLICT` for any concurrent PATCH that captured an older version.

## 3. Business Logic & Workflows

### 3.1. Borrower Origination and Demographic Maintenance

A borrower record is created by a `ServicerAdmin` once the operator has collected enough identifying material to attribute future loans. The payload carries the borrower's legal name (`full_name`), the last four digits of their Social Security number (`ssn_last4`, which must be exactly four numeric characters), `family_size` (an integer of at least 1, defaulting to 1 if omitted), and `state_code` (a two-letter US state code). Three further fields may be supplied at origination or filled in later: `adjusted_gross_income_cents` (the most recently certified Adjusted Gross Income in cents, a non-negative integer that defaults to 0), `agi_certified_at` (the timestamp when AGI was last certified, defaulting to absent), and `veteran_status` (defaulting to `NONE` if not supplied, otherwise drawn from the enumeration `NONE`, `VETERAN`, or `TPD_VETERAN`, where `TPD_VETERAN` denotes a borrower with a total and permanent VA disability rating).

Borrower demographics may be updated either by the borrower themselves (on their own record) or by a `ServicerAdmin`. The update payload carries any subset of `family_size`, `state_code`, `adjusted_gross_income_cents`, and `veteran_status`, plus an optional `version`. When `adjusted_gross_income_cents` is included in an update and its value differs from the stored value, the server stamps `agi_certified_at` to the current clock — this is the implicit re-certification event that resets the 365-day recertification window used by IDR plan activation.

The two aggregate fields `aggregate_principal_balance_cents` and `aggregate_interest_balance_cents` are server-computed and reflect the live sum of `principal_balance_cents` and `accrued_interest_cents` respectively across the borrower's non-terminal loans.

### 3.2. Loan Origination and the In-School to Repayment Lifecycle

A loan is originated by a `ServicerAdmin` against a specific borrower. The payload carries `loan_type` (one of `DIRECT_SUBSIDIZED`, `DIRECT_UNSUBSIDIZED`, or `DIRECT_PLUS`), `original_principal_cents` (a positive integer), `interest_rate_bps` (a positive integer, capped at 2000 basis points — that is, twenty percent annual), and `disbursement_date`, the date funds were paid out. At origination the loan enters `IN_SCHOOL` with `status_entered_at` and `last_accrual_at` set to the current clock; `principal_balance_cents` is initialized to `original_principal_cents`; `accrued_interest_cents` and `capitalized_interest_cents` both start at 0; `days_past_due` is 0; `last_payment_due_at` is absent; `qualifying_pslf_payment_count` is 0.

Separating the loan from school — the act that ends the in-school deferment — is an administrative action performed by a `ServicerAdmin`. The default behaviour transitions the loan from `IN_SCHOOL` to `GRACE`, sets `status_entered_at` and `last_accrual_at` to `now`, and starts the loan's grace clock. Interest accrual during `GRACE` depends on the loan type: a `DIRECT_SUBSIDIZED` loan accrues no interest during grace because it sits in the federal subsidy window; both `DIRECT_UNSUBSIDIZED` and `DIRECT_PLUS` continue to accrue interest day by day. A request body may supply `skip_grace` as `true` to bypass the grace period entirely; this option is restricted to `DIRECT_PLUS` loans and transitions the loan directly from `IN_SCHOOL` to `REPAYMENT`, capitalizing any accrued interest and setting `last_payment_due_at` to the first day of the next month at or after `now`. Any attempt to transition a loan that is not currently `IN_SCHOOL` is rejected with `ERR_INVALID_STATE`.

When the simulation clock crosses the boundary of 180 days past `status_entered_at` for a loan in `GRACE`, the system automatically transitions the loan from `GRACE` to `REPAYMENT`. At this point the unsubsidized loan types — `DIRECT_UNSUBSIDIZED` and `DIRECT_PLUS` — have their `accrued_interest_cents` capitalized: the accrued amount is added to `principal_balance_cents`, the same amount is added to `capitalized_interest_cents`, and `accrued_interest_cents` is reset to 0. `DIRECT_SUBSIDIZED` loans carry no accrued interest out of grace because they were not accruing during the grace window. In all three cases, `last_payment_due_at` is set to the first day of the calendar month at or after `now`.

### 3.3. Daily Interest Accrual on the Simulation Clock

Each call advancing the simulation clock recomputes interest for every loan whose status is in the accruing set: `GRACE`, `REPAYMENT`, `DELINQUENT`, `DEFERMENT`, `FORBEARANCE`, or `REHABILITATION`. The number of days that have elapsed since the loan's `last_accrual_at` is computed as the floor of the difference between the new `now` and `last_accrual_at` in days. A subsidy filter then applies: a `DIRECT_SUBSIDIZED` loan accrues nothing while it is in `GRACE` or in `DEFERMENT` (any deferment kind — in-school, unemployment, economic hardship, or military), because the federal subsidy pays the interest in those windows. For every other accruing loan, the daily rate is computed as `interest_rate_bps` divided by 10000 and then divided by 365; the accrued amount for the call is the loan's current `principal_balance_cents` multiplied by that daily rate and by the elapsed-day count, rounded half-up to integer cents at that moment, and added to `accrued_interest_cents`. The rounding is performed **once per loan per clock-advance call** — neither per day individually nor after summing across loans. The loan's `last_accrual_at` is then advanced to the new `now`.

Two further side-effects ride on the clock-advance call. First, for any loan in `DELINQUENT`, `days_past_due` is recomputed as the floor of the elapsed days between the new `now` and `last_payment_due_at`; if the recomputed value reaches at least 270, the loan immediately progresses to default per §3.6. Second, for any loan in `DEFERMENT` or `FORBEARANCE` whose owning hardship request's `requested_to` has been crossed, the loan auto-exits back to `REPAYMENT` (described in §3.5).

### 3.4. Payments and the Allocation Waterfall

A payment is recorded against a borrower, not against a loan: the request payload carries `amount_cents` (a positive integer; zero or negative is rejected with `ERR_AMOUNT_INVALID`), an optional `source` defaulting to `BORROWER` (otherwise one of `EMPLOYER`, `ADMINISTRATIVE_WAGE_GARNISHMENT`, or `TREASURY_OFFSET`), and an optional `received_at` defaulting to the current clock. A `Borrower` may submit payments only with `source = BORROWER`; a `CollectionsOfficer` is the only role permitted to submit payments with `source` in `ADMINISTRATIVE_WAGE_GARNISHMENT` or `TREASURY_OFFSET`; a `ServicerAdmin` may submit payments with any source.

The allocation is computed by walking the borrower's non-terminal loans — every loan whose status is not `PAID_OFF` and not `DISCHARGED` — in a deterministic priority order: highest `interest_rate_bps` first, ties broken by the earliest `disbursement_date`, and remaining ties broken by lexicographic ascending order on the loan's `id`. Two allocation modes exist:

- **Standard mode** applies when `source` is `BORROWER` or `EMPLOYER`. The walker iterates every non-terminal loan in priority order. Within each loan, the per-loan order is also pinned: outstanding late fees first (there are no fee fields in this system, so the per-loan fee bucket is always zero and is skipped), then `accrued_interest_cents`, then `principal_balance_cents`. As each bucket is satisfied, the corresponding loan field is decremented and the consumed amount is recorded in the `allocations` array as a per-loan record carrying the loan's `id`, `fees_cents` (always 0 in this system), `interest_cents`, and `principal_cents`.
- **Targeted-collections mode** applies when `source` is `ADMINISTRATIVE_WAGE_GARNISHMENT` or `TREASURY_OFFSET`. The walker considers only loans whose status is `DEFAULT`, in the same priority order and with the same per-loan interest-before-principal ordering. Loans not in `DEFAULT` receive zero allocation.

The total `amount_cents` is consumed in integer cents — no fractional cents are ever created, because the input is integer cents. If, after every eligible loan has been zeroed in the chosen mode, the input amount is still positive, the residual is returned to the borrower as a refund recorded against the highest-priority loan's allocation record.

When the allocation reduces a loan's `principal_balance_cents` and `accrued_interest_cents` simultaneously to zero, that loan transitions to `PAID_OFF` with `status_entered_at` set to `now`. When the allocation cures past-due installments — meaning `days_past_due` is brought back to 0 because the months' worth of installments has been satisfied — a loan in `DELINQUENT` transitions back to `REPAYMENT`, with `days_past_due` set to 0 and `last_payment_due_at` advanced by the number of installments now satisfied.

After allocation, the system performs the live PSLF qualification check (described in §3.8) and stamps `pslf_qualifying` on the new payment to record whether it counts as a qualifying payment for any covered loan.

### 3.5. Hardship Relief: Deferment and Forbearance

A hardship request captures a borrower's plea for temporary relief: a deferment (which may carry a federal subsidy on subsidized loans) or a forbearance (which never carries a subsidy). The submission payload carries `kind` (one of `DEFERMENT_IN_SCHOOL`, `DEFERMENT_UNEMPLOYMENT`, `DEFERMENT_ECONOMIC_HARDSHIP`, `DEFERMENT_MILITARY`, `FORBEARANCE_GENERAL`, or `FORBEARANCE_MANDATORY`), the requested window's `requested_from` and `requested_to` timestamps, and the `applied_loan_ids` array naming the subset of borrower loans this hardship applies to. Submission is rejected with `ERR_BAD_DATE_WINDOW` if `requested_to` is not strictly after `requested_from` or if `requested_from` is in the past relative to `now`. Submission also snapshots the borrower's lifetime tally of general-forbearance days into `cumulative_forbearance_days_at_request` for use by the 36-month cap check at approval time.

Approval is performed by a `ServicerCertifier` who patches the request to `APPROVED`; rejection by the same role moves it to `REJECTED` with a `rejection_reason`; the borrower themselves may cancel a request that is still in `SUBMITTED` to move it to `CANCELLED`. The approval check enforces three preconditions on top of the standard state guard: (a) every loan in `applied_loan_ids` must not be in `DEFAULT`; (b) if `kind` is `DEFERMENT_IN_SCHOOL` and any applied loan is `DIRECT_PLUS`, the approval is rejected with `ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL` because in-school deferment is statutorily restricted to subsidized and unsubsidized direct loans; and (c) if `kind` is `FORBEARANCE_GENERAL`, the borrower's lifetime cumulative general-forbearance days plus the number of days in the requested window must be at most 1095 (that is, three years total across the borrower's lifetime), with violation reported as `ERR_FORBEARANCE_CAP_EXCEEDED`.

A successful approval transitions each applied loan into the appropriate state. From `REPAYMENT`, a `DEFERMENT_*` approval moves the loan to `DEFERMENT`; a `FORBEARANCE_*` approval moves it to `FORBEARANCE`. From `DELINQUENT`, a `FORBEARANCE_*` approval also moves the loan to `FORBEARANCE` and additionally cures the delinquency by resetting `days_past_due` to 0. In both cases `status_entered_at` is set to `now`. Subsidy semantics apply during the relief period: a `DIRECT_SUBSIDIZED` loan in `DEFERMENT` does not accrue interest (federal subsidy pays it), while `DIRECT_UNSUBSIDIZED` and `DIRECT_PLUS` loans continue to accrue; in `FORBEARANCE` all three loan types continue to accrue interest, with no subsidy ever applying.

When the simulation clock crosses `requested_to`, the auto-exit fires: a loan in `DEFERMENT` returns to `REPAYMENT`, capitalizing accrued interest on `DIRECT_UNSUBSIDIZED` and `DIRECT_PLUS` (so accrued is added to principal and to `capitalized_interest_cents`, then zeroed) while `DIRECT_SUBSIDIZED` carries zero accrued forward. A loan in `FORBEARANCE` returns to `REPAYMENT` capitalizing accrued interest on every loan type. In both auto-exits, `last_payment_due_at` is set to the first day of the calendar month at or after `now`.

### 3.6. Delinquency, Default, Rehabilitation

Delinquency aging is computed by the clock-advance simulation: a loan in `REPAYMENT` whose `now` is past its `last_payment_due_at` and whose installment is unpaid transitions to `DELINQUENT`, with `days_past_due` computed as the floor of elapsed days since `last_payment_due_at`. A payment that fully cures past-due installments returns the loan to `REPAYMENT` per §3.4. When `days_past_due` reaches at least 270, the loan auto-transitions from `DELINQUENT` to `DEFAULT`. Default has three side-effects beyond the status change itself: first, any `accrued_interest_cents` is capitalized into `principal_balance_cents` and added to `capitalized_interest_cents`, then `accrued_interest_cents` is zeroed; second, a `CollectionsAction` of `kind` `DEFAULT_DECLARATION` with `amount_cents` 0 is appended to the loan's collections history; third, any `ACTIVE` `RepaymentPlan` whose `included_loan_ids` contains the defaulted loan is cascaded to `TERMINATED`, and every other non-defaulted loan that was previously covered by that terminated plan is moved to `REPAYMENT` with `last_payment_due_at` set to the first day of the calendar month at or after `now`. This three-level cascade — from the defaulted loan to its plan to its sibling loans — is the deepest implicit propagation in the system and is the reason a default declaration is rejected with `ERR_INVALID_STATE` if the loan has already left `DELINQUENT` due to an intervening payment.

Once a loan is in `DEFAULT`, the only path back to repayment is loan rehabilitation, opened by a `CollectionsOfficer`. Opening a rehab agreement is a `CollectionsAction` of `kind` `REHAB_AGREEMENT_OPEN`. The opening is permitted only when the loan is currently in `DEFAULT` and has never previously completed a rehabilitation — that is, no prior `CollectionsAction` of `kind` `REHAB_COMPLETED` exists for this loan; the lifetime-one rule violation is reported as `ERR_REHAB_ALREADY_USED`. Opening sets `status_entered_at` to `now` (resetting the rehab clock) and moves the loan from `DEFAULT` to `REHABILITATION`. Subsequent rehab payments are recorded as `CollectionsAction` rows of `kind` `REHAB_PAYMENT_RECORDED`. When the clock-advance sees nine such `REHAB_PAYMENT_RECORDED` actions within the prior 10 consecutive months — measured against `occurred_at` — the loan auto-transitions from `REHABILITATION` back to `REPAYMENT`. The rehab completion appends a `CollectionsAction` of `kind` `REHAB_COMPLETED`, clears `days_past_due` to 0, and removes the default flag from the active collections set. The conservation invariant is that `principal_balance_cents + accrued_interest_cents + lifetime paid amount` is unchanged across the rehab cycle, because `REHAB_PAYMENT_RECORDED` amounts flow into the waterfall as payments.

Other collections kinds also exist as `CollectionsAction` rows: a `WAGE_GARNISHMENT_ORDER` and a `TREASURY_OFFSET_APPLIED` action each create an implicit `Payment` whose `source` matches the action `kind`, allocated per the targeted-collections mode of the waterfall in §3.4. Every `CollectionsAction` captures the acting operator's `X-User-ID` into `recorded_by`, plus its own `amount_cents` (defaulting to 0 for non-financial kinds) and `occurred_at` (defaulting to the current clock).

### 3.7. Repayment Plans and the Monthly Payment Calculation

A repayment plan is the unit that ties one or more loans to a payment schedule. A `Borrower` or a `ServicerAdmin` creates a plan in `PENDING` by supplying `plan_type` (one of `STANDARD_10`, `IBR`, `PAYE`, or `SAVE`) and `included_loan_ids` (the loans to be enrolled). At create time the plan is `PENDING` with `effective_from`, `certified_agi_cents`, `certified_family_size`, `monthly_payment_cents`, and `recertification_due_at` all zero or absent. A pending plan may be cancelled by the borrower, moving it from `PENDING` to `TERMINATED`.

Activating a plan is the heart of the IDR machinery. Activation checks four things in addition to the standard guards: every loan in `included_loan_ids` must belong to this borrower; every such loan must currently be in `REPAYMENT` or `GRACE` (loans in `DEFAULT` block activation, reported as `ERR_PLAN_LOAN_INELIGIBLE`); for IDR plan types — `IBR`, `PAYE`, and `SAVE` — the borrower's `adjusted_gross_income_cents` must be present and `agi_certified_at` must be within the last 365 days (the recertification window); and no loan in `included_loan_ids` may already be covered by another `ACTIVE` plan for this same borrower. Failure of any of the second through fourth checks yields `ERR_PLAN_LOAN_INELIGIBLE`, `ERR_AGI_NOT_CERTIFIED`, and `ERR_PLAN_CONFLICT` respectively. On success the plan transitions from `PENDING` to `ACTIVE`, `effective_from` is set to `now`, and an IDR plan snapshots the borrower's `adjusted_gross_income_cents` and `family_size` into the plan's `certified_agi_cents` and `certified_family_size` (a `STANDARD_10` plan sets both to 0). The `recertification_due_at` for IDR plans is set to 365 days past `now`; for `STANDARD_10` it is left absent. Finally, `monthly_payment_cents` is computed per the calculation below. If the activation of this new plan touches any loan that is already covered by another `ACTIVE` plan for the same borrower, the older plan is cascaded to `SUPERSEDED` and the new plan's activation proceeds — its loans' monthly payments are recomputed under the new plan.

The monthly payment computation begins by assembling the pool: the sum, across every loan in `included_loan_ids` whose status is `REPAYMENT` or `GRACE`, of `principal_balance_cents` plus `accrued_interest_cents`. Loans in any other status — `DEFAULT`, `DEFERMENT`, `FORBEARANCE`, `PAID_OFF`, `DISCHARGED` — are excluded from the pool. Pool aggregation is in integer cents; accrued interest is included in the pool **before** amortization, and the rounding step is the very last operation. A pool-weighted interest rate is computed in basis points, as the sum across pool loans of `interest_rate_bps` times `(principal_balance_cents + accrued_interest_cents)`, divided by the pool principal (or by 1 if the pool is zero, to avoid division-by-zero).

For `STANDARD_10`, the schedule is a level-payment fully amortizing schedule over 120 months. The monthly rate is the weighted basis-point rate divided by 10000 and then divided by 12. When the monthly rate is zero, the monthly payment is the pool divided by 120. Otherwise it is computed using the standard amortization formula: the pool multiplied by the monthly rate multiplied by one-plus-monthly-rate raised to the 120th power, divided by one-plus-monthly-rate raised to the 120th power minus one. The result is rounded half-up to integer cents to produce `monthly_payment_cents`.

For IDR plans, the schedule is computed off discretionary income rather than off principal. The poverty line in cents for the borrower's `family_size` is read from the 2024 federal poverty-guidelines table, which has three regional partitions: the 48 contiguous states plus the District of Columbia, Alaska, and Hawaii. The 48-state-plus-DC table reads $15,060 (1,506,000 cents) for family size 1, $20,340 for size 2, $25,620 for size 3, $30,900 for size 4, and $36,180 for size 5. The Alaska table reads $18,820 (1,882,000 cents) for size 1, $25,420 for size 2, $32,020 for size 3, $38,620 for size 4, and $45,220 for size 5. The Hawaii table reads $17,320 (1,732,000 cents) for size 1, $23,400 for size 2, $29,480 for size 3, $35,560 for size 4, and $41,640 for size 5. The poverty multiplier depends on plan type — 1.50 for `IBR`, 1.50 for `PAYE`, 2.25 for `SAVE`. Discretionary income is computed as `adjusted_gross_income_cents` minus the multiplier times the poverty line, with the result clamped at zero from below (never negative). The annual payment is discretionary income multiplied by the plan-type income fraction — 0.15 for `IBR`, 0.10 for `PAYE`, 0.05 for `SAVE`. The annual payment is divided by 12 and the result is rounded half-up to integer cents. A floor then applies: for `IBR` and `PAYE`, if the rounded value is 0 and the pool is positive, the monthly payment is raised to 500 cents (a $5 minimum); for `SAVE`, there is **no** floor — a true $0 payment is permitted when discretionary income is 0.

### 3.8. Employment Certification and PSLF Qualification

Public Service Loan Forgiveness rests on a borrower's record of qualifying employment with qualifying employers. The borrower submits an `EmploymentCertification` carrying `employer_name`, `employer_type` (one of `GOVERNMENT`, `NONPROFIT_501C3`, `OTHER_NONPROFIT_QUALIFYING`, or `PRIVATE_NON_QUALIFYING`), and a window of `period_start` and `period_end`; the certification is rejected at submission with `ERR_BAD_DATE_WINDOW` if `period_start` is not strictly less than `period_end`. A `ServicerCertifier` then reviews the submission: approval requires `employer_type` to be one of the three qualifying values (`GOVERNMENT`, `NONPROFIT_501C3`, or `OTHER_NONPROFIT_QUALIFYING`) — a `PRIVATE_NON_QUALIFYING` certification cannot be approved. The certifier's `X-User-ID` is stamped into `reviewed_by`. Rejection records a free-text `rejection_reason`.

Approving an `EmploymentCertification` retroactively re-runs the PSLF qualification recount across the borrower's entire payment history. The recount, also triggered when a discharge application moves from `UNDER_REVIEW` to `APPROVED`, walks every `Payment` the borrower has ever made in ascending `received_at` order, and for each per-loan record in the payment's `allocations` array determines whether the (payment, loan) pair counts as a qualifying payment for PSLF. Five conditions must all hold: (1) the loan's `loan_type` is one of `DIRECT_SUBSIDIZED`, `DIRECT_UNSUBSIDIZED`, or `DIRECT_PLUS`; (2) the payment's `received_at` falls within an `APPROVED` `EmploymentCertification`'s window for this borrower, inclusive on both endpoints — `period_start` is at or before `received_at` and `received_at` is at or before `period_end`; (3) at the time of `received_at` the borrower had an `ACTIVE` `RepaymentPlan` of type `STANDARD_10`, `IBR`, `PAYE`, or `SAVE` covering the loan; (4) the sum of that allocation's `principal_cents` and `interest_cents` is at least the per-loan scheduled-monthly share, where the share is computed as the plan's `monthly_payment_cents` multiplied by the loan's share of the pool and rounded half-up to integer cents (the share-then-round mode is pinned — summing then rounding would yield different counts); and (5) the loan's status at the moment of `received_at` was not `DEFAULT` and not `DELINQUENT`. Each qualifying (payment, loan) increments the loan's `qualifying_pslf_payment_count` by 1. The threshold for PSLF discharge is 120 qualifying payments per loan.

### 3.9. Discharge Applications

A discharge application is the borrower's request to have specified loans forgiven, either through PSLF or through the Veteran Total and Permanent Disability program. Submission is performed by the borrower (or by a `ServicerAdmin` acting on their behalf) and carries `program` set to either `PSLF` or `VETERAN_TPD`; the application enters `SUBMITTED`. From `SUBMITTED`, a `ServicerCertifier` may move the application to `UNDER_REVIEW` or directly reject it; from `UNDER_REVIEW`, a `ServicerApprover` is the only role permitted to approve or reject. Moving a PSLF application from `SUBMITTED` to `UNDER_REVIEW` requires that at least one `EmploymentCertification` for this borrower is already in `APPROVED` status — otherwise the certifier's transition is rejected with `ERR_PSLF_NO_EMPLOYMENT_EVIDENCE`.

Approving an application (moving from `UNDER_REVIEW` to `APPROVED`) requires the approver to supply `approved_loan_ids`. Every loan in `approved_loan_ids` must belong to this borrower and must currently be in `REPAYMENT`, `DELINQUENT`, or `FORBEARANCE`; loans in `DEFAULT` must be rehabilitated first, and loans in `PAID_OFF` or `DISCHARGED` are ineligible. The approver's `X-User-ID` is stamped into the application's `reviewed_by` field, and per §2.9 may not equal any `ServicerCertifier`'s id recorded as `reviewed_by` on any of this borrower's `APPROVED` `EmploymentCertification` records (segregation of duties; `ERR_SOD_VIOLATION`).

For a PSLF approval, the qualification check (§3.8) must yield `qualifying_pslf_payment_count` of at least 120 for **every** loan in `approved_loan_ids`; failure for any loan is reported as `ERR_PSLF_INSUFFICIENT_PAYMENTS`. For a `VETERAN_TPD` approval, the borrower's `veteran_status` must be `TPD_VETERAN`; failure is reported as `ERR_VETERAN_INELIGIBLE`. The veteran eligibility path is independent of PSLF — it does not look at employment certifications, and an eligible `TPD_VETERAN` may also have loans in `DELINQUENT` or `FORBEARANCE` discharged in the same approval. Approval cascades to every loan in `approved_loan_ids`: each transitions to `DISCHARGED`, `principal_balance_cents` and `accrued_interest_cents` are zeroed, `status_entered_at` is set to `now`, and the application captures the pre-discharge sums into `discharged_principal_cents` and `discharged_interest_cents`. The borrower's `aggregate_principal_balance_cents` and `aggregate_interest_balance_cents` are then recomputed.

### 3.10. Risk Score and Collections Summary Reads

Two computed reads are exposed for operator-facing dashboards. The first is an IDR recertification drift risk score, returned for any borrower. It combines three subscores, each independently clamped to the integer range 0 through 100. The delinquency subscore is the minimum of 100 and the maximum `days_past_due` across the borrower's loans. The forbearance-burden subscore is the minimum of 100 and the borrower's cumulative forbearance days divided by 1095 and multiplied by 100. The recertification-overdue subscore is computed from the elapsed days since `agi_certified_at`: when `agi_certified_at` is absent, the elapsed-days value is 9999; the days-overdue figure is the maximum of 0 and elapsed-minus-365 (so the subscore counts only days past the 365-day window); and the subscore itself is the minimum of 100 and days-overdue divided by 365 multiplied by 100. The composite is 0.5 times the delinquency subscore plus 0.3 times the forbearance-burden subscore plus 0.2 times the recertification-overdue subscore. The composite is then clamped again to the range 0 through 100 (so the order is **subscore-clamp first**, then weighted sum, then composite-clamp; reversing the order yields different results when subscores would exceed 100 individually). Finally the composite is rounded half-up to an integer.

The second computed read is the collections aging summary, returned for a closed inclusive window bounded by query parameters `start` and `end` against the borrower's `CollectionsAction` rows. The summary aggregates: the sum of `amount_cents` across actions whose `kind` is `WAGE_GARNISHMENT_ORDER` and whose `occurred_at` falls in `[start, end]`; the sum of `amount_cents` across actions whose `kind` is `TREASURY_OFFSET_APPLIED` and whose `occurred_at` falls in `[start, end]`; and the count of `REHAB_PAYMENT_RECORDED` actions whose `occurred_at` is at or after `now` minus 304 days (the system's approximation of "the last ten months"). Tie-breaking on equal `occurred_at` is by insertion order.

## 4. Endpoint Definitions

The API is mounted under the borrower-scoped prefix. Endpoints that create a new resource respond with HTTP 201; endpoints that read, mutate, or delete an existing resource respond with HTTP 200. Error responses use the HTTP status documented in the §5 catalogue.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| GET    | `/_health` | Liveness probe | `SystemTest`, `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover`, `CollectionsOfficer`, `Borrower` |
| POST   | `/_clock/advance` | Advance the simulation clock and trigger chronological side effects | `ServicerAdmin`, `SystemTest` |
| POST   | `/borrowers` | Create a borrower record | `ServicerAdmin` |
| GET    | `/borrowers` | List borrowers (paginated) | `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}` | Fetch borrower with computed aggregates | `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover`, `CollectionsOfficer`, `Borrower` |
| PATCH  | `/borrowers/{borrower_id}` | Update borrower demographics or AGI | `ServicerAdmin`, `Borrower` |
| POST   | `/borrowers/{borrower_id}/loans` | Originate a loan (initial status `IN_SCHOOL`) | `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}/loans` | List the borrower's loans | `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover`, `CollectionsOfficer`, `Borrower` |
| GET    | `/borrowers/{borrower_id}/loans/{loan_id}` | Get loan details with current balances | `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover`, `CollectionsOfficer`, `Borrower` |
| POST   | `/borrowers/{borrower_id}/loans/{loan_id}/separate` | Separate the loan from school (`IN_SCHOOL` → `GRACE` or `REPAYMENT`) | `ServicerAdmin` |
| POST   | `/borrowers/{borrower_id}/loans/{loan_id}/collections` | Append a `CollectionsAction` | `CollectionsOfficer` |
| POST   | `/borrowers/{borrower_id}/payments` | Record a payment and run the allocation waterfall | `Borrower`, `ServicerAdmin`, `CollectionsOfficer` |
| GET    | `/borrowers/{borrower_id}/payments` | List payments | `Borrower`, `ServicerAdmin`, `CollectionsOfficer` |
| GET    | `/borrowers/{borrower_id}/payments/{payment_id}` | Get a payment with its `allocations` | `Borrower`, `ServicerAdmin`, `CollectionsOfficer` |
| POST   | `/borrowers/{borrower_id}/plans` | Create a draft repayment plan (`PENDING`) | `Borrower`, `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}/plans` | List the borrower's plans | `Borrower`, `ServicerAdmin`, `ServicerCertifier` |
| GET    | `/borrowers/{borrower_id}/plans/{plan_id}` | Get a plan with current `monthly_payment_cents` | `Borrower`, `ServicerAdmin`, `ServicerCertifier` |
| POST   | `/borrowers/{borrower_id}/plans/{plan_id}/activate` | Activate a plan | `Borrower`, `ServicerAdmin` |
| DELETE | `/borrowers/{borrower_id}/plans/{plan_id}` | Cancel a `PENDING` plan (`PENDING` → `TERMINATED`) | `Borrower`, `ServicerAdmin` |
| POST   | `/borrowers/{borrower_id}/hardship-requests` | Submit a deferment or forbearance request | `Borrower`, `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}/hardship-requests` | List hardship requests | `Borrower`, `ServicerAdmin`, `ServicerCertifier` |
| PATCH  | `/borrowers/{borrower_id}/hardship-requests/{request_id}` | Approve or reject a hardship request | `ServicerCertifier` |
| DELETE | `/borrowers/{borrower_id}/hardship-requests/{request_id}` | Cancel a `SUBMITTED` hardship request | `Borrower` |
| POST   | `/borrowers/{borrower_id}/discharge-applications` | Submit a discharge application | `Borrower`, `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}/discharge-applications` | List discharge applications | `Borrower`, `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover` |
| PATCH  | `/borrowers/{borrower_id}/discharge-applications/{application_id}` | Move a discharge application through review states | `ServicerCertifier`, `ServicerApprover` |
| POST   | `/borrowers/{borrower_id}/employment-certifications` | Submit an employment certification | `Borrower`, `ServicerAdmin` |
| GET    | `/borrowers/{borrower_id}/employment-certifications` | List employment certifications | `Borrower`, `ServicerAdmin`, `ServicerCertifier`, `ServicerApprover` |
| PATCH  | `/borrowers/{borrower_id}/employment-certifications/{certification_id}` | Approve or reject an employment certification | `ServicerCertifier` |
| GET    | `/borrowers/{borrower_id}/risk-score` | Return the IDR recertification drift score | `ServicerAdmin`, `ServicerCertifier`, `CollectionsOfficer` |
| GET    | `/borrowers/{borrower_id}/collections-summary` | Return the collections aging summary | `CollectionsOfficer`, `ServicerAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_BORROWER_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_BAD_DATE_WINDOW` | 400 |
| `ERR_AMOUNT_INVALID` | 400 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_PLAN_CONFLICT` | 409 |
| `ERR_PLAN_LOAN_INELIGIBLE` | 422 |
| `ERR_AGI_NOT_CERTIFIED` | 422 |
| `ERR_VETERAN_INELIGIBLE` | 422 |
| `ERR_PSLF_NO_EMPLOYMENT_EVIDENCE` | 422 |
| `ERR_PSLF_INSUFFICIENT_PAYMENTS` | 422 |
| `ERR_FORBEARANCE_CAP_EXCEEDED` | 422 |
| `ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL` | 422 |
| `ERR_REHAB_ALREADY_USED` | 422 |
