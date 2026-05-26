# Federal Student Loan Servicing API — Product Requirements Document

## 1. Introduction

The Federal Student Loan Servicing API is the system of record for the full life of a federally backed student loan, from the day a school disburses funds to the moment the loan is paid in full, discharged, or rehabilitated out of default. It must reconcile three audiences whose interests do not always align: borrowers, who request income-driven repayment plans, deferments, and forbearances against an evolving picture of their household finances; loan servicers, who certify income evidence and qualifying employment, post and reverse payments, and shepherd applications for public-service loan forgiveness; and collections agents, who declare default once delinquency crosses statutory thresholds and oversee the rehabilitation pathway back to active repayment.

Because borrower-level financial outcomes depend on the precise order in which payments are applied, interest accrues, and statuses change, the system is built around two non-negotiable disciplines. First, every loan-altering event is journaled — every status transition is preserved as an auditable record, and every monetary movement is expressed in integer cents so that no rounding mistake silently widens or narrows a balance. Second, the system uses optimistic concurrency for the two operations where rival writers can otherwise quietly clobber each other: filing a new repayment plan against a loan and approving a discharge application. This document specifies the resources, lifecycles, calculations, and access rules that together define the contract this API must implement.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Unless an individual workflow in §3 overrides a behavior, the principles below govern.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which they act. A request that omits either header, or whose values are malformed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted to perform the requested operation under the role matrix is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks always run first, before any existence or business validation.

Three roles exist, spelled exactly as follows: `LoanServicer`, `Borrower`, and `CollectionsAgent`. The `Borrower` role is entity-backed — when `X-User-Role` is `Borrower`, the value of `X-User-ID` is the `id` of the acting `Borrower` entity, and ownership checks on any resource that references a borrower compare that resource's `borrower_id` field (directly, or transitively via a parent `Loan`) to `X-User-ID`. The `LoanServicer` and `CollectionsAgent` roles are opaque operator identities not tied to any persisted entity. The server may record their identifier (for example, as `actor_role` on a `StatusChange` row written by a transition they trigger) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned and defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the count of items to skip from the beginning of the result set and defaults to 0.

All list endpoints return resources sorted by `created_at` in ascending order unless the endpoint's description in §4 explicitly states otherwise. Each list response embeds `limit`, `offset`, `total_count`, and `has_more` in the `meta` block of the envelope.

### 2.4. Common Resource Properties and Auditability

Every resource other than `StatusChange` carries four common fields: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix and is immutable. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation. The `version` field is an integer starting at 1 on creation and incrementing by 1 on every mutation that produces a new persisted state for the resource. `StatusChange` is the audit-log exception: it carries only `id` and `created_at`, and it has neither `updated_at` nor `version` because it is append-only.

For every state transition described in §3, the touched resource's `version` advances and its `updated_at` is refreshed. When a transition has cascading side effects on a second resource (for example, a default declaration that supersedes the loan's active repayment plan, or a discharge approval that reverses still-pending payments), each affected resource independently bumps its own `version` and its own `updated_at`. The `Loan` entity additionally carries `status_change_at`, which records the UTC instant of its most recent status transition; this is distinct from `updated_at`, which advances on any mutation including financial mutations that do not change `status`.

### 2.5. Optimistic Concurrency Control

Two write paths use optimistic concurrency control because both can be reached by parallel reviewers or competing writers whose snapshots may have drifted.

Creating a `RepaymentPlan` requires the client to supply `expected_loan_version` in the request body, carrying the client's last observed `version` of the target `Loan`. The server compares this value to the loan's current `version`; if another writer (for instance, an earlier plan creation that has already taken effect) has advanced the loan's `version` since the client last read it, the create is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412), preventing the client from inserting a plan against a loan state it has not actually observed.

Approving a `DischargeApplication` requires the client to supply `expected_application_version` in the request body, carrying the reviewer's last observed `version` of the target application. If another reviewer has already advanced the application's `version` — by beginning a review, denying it, or annotating it — the approve is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). No other endpoint accepts a `version` field; endpoints not enumerated here treat any incoming version field as an unknown input under the general request-shape validation.

### 2.6. Monetary Precision and Rounding

All monetary quantities — principal balances, accrued interest, capitalized interest, payment amounts, and computed monthly payments — are stored and exchanged as integer cents. The system performs all rounding using the round-half-up convention. Two calculations specify precisely where the rounding happens, and the placement is part of the contract rather than an incidental detail:

For monthly-payment computation, the divide-by-twelve step that converts an annual figure to a monthly figure is performed first; the rounding to integer cents is performed only after that division. No earlier rounding is permitted.

For daily interest accrual, each day's fractional accrual is rounded to integer cents before being added to `accrued_interest_cents`. The system does not accumulate fractional accrual across multiple days and then round at the end of a window; per-day rounding is mandated.

### 2.7. Validation Ordering

When multiple validations could fire for a single request, the server evaluates them in this fixed order so that the error returned is always the most specific applicable one:

1. Authentication header presence (`ERR_UNAUTHENTICATED`).
2. Role authorization under the operation's role matrix (`ERR_UNAUTHORIZED`).
3. Existence of any path-referenced `Loan` (`ERR_LOAN_NOT_FOUND`).
4. Existence of any path-referenced `Borrower` (`ERR_BORROWER_NOT_FOUND`).
5. Existence of any other path-referenced resource — `RepaymentPlan`, `Payment`, `DischargeApplication`, `IncomeCertification`, or `QualifyingEmployment` (`ERR_RESOURCE_NOT_FOUND`).
6. State preconditions of the requested transition (`ERR_INVALID_STATE`).
7. Plan-already-active conflict on plan activation (`ERR_PLAN_ALREADY_ACTIVE`).
8. Business-safety guards on discharge approval — the veteran check (`ERR_NOT_VETERAN`) and the PSLF payment-count check (`ERR_PSLF_INSUFFICIENT_PAYMENTS`) — both evaluated before any general business-constraint check.
9. Business constraints specific to a transition (`ERR_DEFAULT_THRESHOLD_NOT_MET`, `ERR_REHABILITATION_NOT_QUALIFIED`).
10. Optimistic-concurrency version checks (`ERR_STALE_LOAN_VERSION`, `ERR_STALE_APPLICATION_VERSION`).
11. Temporal constraints (`ERR_INVALID_PERIOD`, `ERR_FUTURE_PAYMENT`).
12. Fiscal range constraints on payment posting (`ERR_PAYMENT_AMOUNT_OUT_OF_RANGE`).
13. General request shape — required fields and enum membership (`ERR_INVALID_REQUEST`).

For the discharge-approval endpoint specifically, this means the veteran and PSLF guards run before the optimistic-concurrency check. For repayment-plan creation, business-safety and business-constraint checks do not apply; the order collapses to existence, then state, then optimistic concurrency, then request shape.

### 2.8. Nested Resource Resolution

Where an endpoint's path embeds multiple resource identifiers — for example, a status-change listing scoped to a particular loan — the server resolves them left to right, surfacing the first missing resource with its specific not-found error (the loan-scoped error variant for the loan segment, the generic resource-not-found for downstream segments). Ownership for the `Borrower` role then layers on top: a borrower may retrieve only resources whose `borrower_id`, directly or via the resource's parent `Loan`, equals `X-User-ID`.

### 2.9. The Server Clock

The server maintains a logical UTC clock that drives time-sensitive computations — interest accrual, delinquency aging, and the temporal validity of payments. An administrative test-driving capability allows a `LoanServicer` to advance this clock to a supplied instant by sending a `to_iso8601` value; advancing the clock triggers a flat recomputation of `interest_accrual` for every loan and refreshes `delinquency_days` across the population.

## 3. Business Logic & Workflows

### 3.1. Borrowers and the Evidence Base for Income-Driven Repayment

A borrower is the central counterparty of the system. They are created with a legal `full_name`, the last four digits of their Social Security number stored as `ssn_last4` for audit display only (the field never participates in business decisions), and an `is_veteran` flag that marks eligibility to later file a total-permanent-disability discharge application; `is_veteran` defaults to false when the field is not supplied at creation.

The borrower also exposes two computed views into the most recent income evidence on file: `current_agi_cents` and `current_family_size`. Both are derived from the latest `IncomeCertification` belonging to that borrower whose `status` is `CERTIFIED`. When multiple certifications could qualify, selection is by `effective_date` descending, with ties broken by `created_at` descending; if no `CERTIFIED` certification exists for the borrower, both computed fields are null. These two views matter because they are the inputs to every income-driven monthly-payment calculation downstream.

A borrower files an income certification by submitting their `agi_cents` (Adjusted Gross Income in cents, which must be at least 0), their tax-household `family_size` (which must be at least 1), the two-letter US `state_code` that selects the appropriate poverty-guideline table, and an `effective_date` from which the certification is valid. Certifications are created in `SUBMITTED` status and remain there until a `LoanServicer` certifies them, advancing them to `CERTIFIED`. The certification lifecycle also recognizes `REJECTED` and `EXPIRED` terminal values, used when a servicer refuses the submission or when a newer certification has aged it out. The full enumeration of certification statuses is therefore `SUBMITTED`, `CERTIFIED`, `REJECTED`, and `EXPIRED`.

The act of certification has a downstream consequence: when a `LoanServicer` advances an `IncomeCertification` from `SUBMITTED` to `CERTIFIED`, the server walks every `RepaymentPlan` belonging to any loan of that borrower whose `status` is `PENDING` or `ACTIVE` and whose `effective_date` is on or before this certification's `effective_date`, and it recomputes each such plan's `monthly_payment_cents` against the freshly certified income figures.

Qualifying employment evidence supports the PSLF pathway and is captured separately. A borrower files a `QualifyingEmployment` record with `employer_name`, an `employer_type` drawn from the enumeration `GOVERNMENT`, `NONPROFIT_501C3`, `OTHER_NONPROFIT`, or `PRIVATE_NONQUALIFYING`, and an inclusive `period_start` and `period_end`. The end of the employment window must be strictly later than the start; a submission whose `period_end` is on or before `period_start` is rejected with `ERR_INVALID_PERIOD`. Employment records, like certifications, begin in `SUBMITTED` and advance to `CERTIFIED` when a servicer accepts them; `REJECTED` is the third possible status. When a servicer transitions a `QualifyingEmployment` from `SUBMITTED` to `CERTIFIED`, the server recomputes `pslf_qualifying_payment_count` on every loan belonging to that borrower so that the count reflects the newly certified employment window.

### 3.2. Originating a Loan and the Pre-Repayment Lifecycle

A loan is created by a `LoanServicer` against an existing borrower. The create payload contains `borrower_id`, the loan's `loan_type` from the enumeration `DIRECT_SUB`, `DIRECT_UNSUB`, or `DIRECT_PLUS`, the disbursed `principal_cents` (which must be at least 100), the annual `interest_rate_bps` expressed in basis points (where 533 represents 5.33%; the value must be at least 1 and at most 2000), and the `disbursement_date`. On creation, the loan enters `ORIGINATED` status, `principal_balance_cents` is initialized to `principal_cents`, both `accrued_interest_cents` and `capitalized_interest_cents` are zero, and `last_accrual_date` is set to `disbursement_date` so that interest begins accruing from the day of disbursement forward.

The loan then walks a status machine whose full enumeration is `ORIGINATED`, `IN_SCHOOL`, `GRACE`, `REPAYMENT`, `DEFERMENT`, `FORBEARANCE`, `DEFAULT`, `PAID_OFF`, and `DISCHARGED`. The terminal statuses are `PAID_OFF` and `DISCHARGED`. Each transition is reachable only from the specific from-state declared below; an attempt to invoke a transition from any other from-state is rejected with `ERR_INVALID_STATE`. Each transition writes a `StatusChange` row capturing `from_status`, `to_status`, the `reason_code` named below, the `actor_role` that initiated the transition (the role string from `X-User-Role`), and the `effective_at` UTC instant; each transition also advances `Loan.status_change_at` to the same instant and increments `Loan.version`.

Before classes end, a `LoanServicer` walks the loan from `ORIGINATED` to `IN_SCHOOL` (recorded with `reason_code` `GRACE_AUTO_START`, as in-school status is treated as a pre-grace deferment for subsidy-accounting purposes), and from `IN_SCHOOL` to `GRACE` upon graduation (also `GRACE_AUTO_START`). When the grace period ends, the servicer transitions the loan from `GRACE` to `REPAYMENT` with `reason_code` `GRACE_AUTO_END`. Only after a loan has reached `REPAYMENT` are borrower-initiated lifecycle controls available.

The interest-subsidy rule is `loan_type`-dependent and matters for any day-by-day accrual replay. While the loan is in `IN_SCHOOL`, `GRACE`, or `DEFERMENT`, a `DIRECT_SUB` loan accrues no interest at all; the same loan in `FORBEARANCE` does accrue. `DIRECT_UNSUB` and `DIRECT_PLUS` loans accrue interest in every status — there is no subsidy window for them.

### 3.3. Interest Accrual and Capitalization

Interest accrual is the system's most pervasive computation: it runs implicitly on every `Loan` status transition and explicitly whenever the test-driving clock capability advances the server clock. Conceptually, the engine replays every calendar day in the half-open window beginning at the loan's `last_accrual_date` (inclusive) and ending at the current server clock (exclusive). For each such day, the engine computes a daily rate by dividing `interest_rate_bps` by ten thousand and then by 365, giving the fraction of principal that accrues per day. It then asks a single boolean question per day: is this day subsidized for this loan? The answer is yes when the loan is `DIRECT_SUB` and the loan's status on that calendar day is `IN_SCHOOL`, `GRACE`, or `DEFERMENT`; otherwise the answer is no. On a subsidized day the accrual is zero. On any other day the day's accrual is the current `principal_balance_cents` multiplied by the daily rate, rounded half-up to integer cents before being added to `accrued_interest_cents`. Once the window has been fully replayed, `last_accrual_date` is advanced to the current server clock.

The mandated order is essential: per-day rounding occurs before summation, status changes mid-window switch subsidy on or off on the correct calendar day, and the engine does not sum fractional accruals across the window and then round at the end — the latter would produce different integer-cent results for the same inputs and is not the chosen interpretation.

Capitalization is the other moving part of the interest model. When a loan returns from `DEFERMENT` to `REPAYMENT` or from `FORBEARANCE` to `REPAYMENT` (both transitions invoked by a `LoanServicer` after the borrower-initiated pause ends), the value currently held in `accrued_interest_cents` is added to `principal_balance_cents`, the same amount is added to the running `capitalized_interest_cents` tally, and `accrued_interest_cents` is reset to zero. The two resume transitions are recorded with `reason_code` `RESUME_REPAYMENT` and share the same capitalization mechanic; from the borrower's standpoint, the practical effect is that paused interest becomes principal going forward.

### 3.4. Borrower-Initiated Pauses and the Resume Path

From `REPAYMENT`, a `Borrower` may pause their obligation in one of two ways. A deferment is requested directly against the loan, transitioning it from `REPAYMENT` to `DEFERMENT`; the resulting `StatusChange` carries `reason_code` `DEFERMENT_REQUEST`. Forbearance is requested similarly, transitioning the loan from `REPAYMENT` to `FORBEARANCE` with `reason_code` `FORBEARANCE_REQUEST`. The two pauses differ in their interest-subsidy implications, which §3.3 describes in detail, and in nothing else lifecycle-wise: both pause required payments, and both can only be initiated from the `REPAYMENT` from-state. Either pause is closed out by a `LoanServicer` returning the loan to `REPAYMENT` via the resume action; the resume transition is the capitalization moment, and is reachable from either `DEFERMENT` or `FORBEARANCE`. An attempt to resume a loan that is not currently in one of those two paused states fails with `ERR_INVALID_STATE`.

### 3.5. Repayment Plans, Pricing, and Plan Supersession

A repayment plan is the contract that tells the borrower what they owe each month. Each plan binds to a single loan by `loan_id`, declares its `plan_type` from the enumeration `STANDARD`, `IBR`, `PAYE`, or `SAVE`, and carries an `effective_date` marking when it becomes the live plan. Plans live through a status sequence of `PENDING`, `ACTIVE`, `SUPERSEDED`, or `COMPLETED`, with `SUPERSEDED` and `COMPLETED` as terminal states. The `superseded_by_plan_id` field is populated only on supersession to point at the replacement plan, with one exception described below.

A `LoanServicer` creates a plan against a loan that is in `REPAYMENT`. The create request must carry `loan_id`, `plan_type`, `effective_date`, and `expected_loan_version`; the last of these is the optimistic-concurrency token discussed in §2.5, and a mismatch yields `ERR_STALE_LOAN_VERSION`. A successful creation places the plan in `PENDING`, increments `Loan.version` by one, and computes the plan's `monthly_payment_cents` immediately so that the figure is visible from the moment of creation. Activation is a separate explicit action by a `LoanServicer`, advancing the plan from `PENDING` to `ACTIVE`. Activation has three preconditions: the plan must currently be `PENDING`, the parent loan must be in `REPAYMENT`, and no other plan with the same `loan_id` may already be `ACTIVE`. The third precondition is the source of `ERR_PLAN_ALREADY_ACTIVE`; the first surfaces as `ERR_INVALID_STATE`.

When activating a new plan implicitly displaces the prior `ACTIVE` plan for the same loan (which occurs via the create-then-activate sequence with `expected_loan_version` correctly matched), the previously `ACTIVE` plan is transitioned to `SUPERSEDED` and its `superseded_by_plan_id` is set to the new plan's `id`. Each touched plan independently increments its own `version`. A separate, distinguishable supersession path fires as a cascade when the parent loan declares default: in that case the previously `ACTIVE` plan is also moved to `SUPERSEDED`, but `superseded_by_plan_id` is left null to record that no replacement plan replaced it — the supersession was statutory, not competitive. A third terminal path closes out the active plan when the loan reaches `PAID_OFF`: the plan transitions from `ACTIVE` to `COMPLETED` automatically, with its `version` incrementing on that transition.

The monthly-payment figure itself depends on the plan type and, for income-driven plans, on the latest certified income evidence pinned at the moment of computation. The pinned inputs are: `agi` taken from the borrower's `current_agi_cents`, `family_size` taken from `current_family_size`, the `state_code` of the very same certification that supplied those two values, the plan's own `plan_type`, the loan's current outstanding `principal_balance_cents` plus the running `capitalized_interest_cents` (this sum is the principal figure used by the standard amortization variant), and the loan's `interest_rate_bps`.

For the three income-driven plan types, the engine first looks up the borrower's annual poverty line by `state_code`. The applicable per-region constants are: in the contiguous 48 states, a one-person base of $15,580 (held internally as `1558000` cents) and an additional $5,480 (`548000` cents) per additional family member; in Alaska, a base of $19,470 (`1947000` cents) and $6,860 (`686000` cents) per additional member; in Hawaii, a base of $17,910 (`1791000` cents) and $6,300 (`630000` cents) per additional member. The poverty line for the borrower is the base plus the per-member amount multiplied by the family size minus one.

The engine then computes annual discretionary income as the borrower's `agi` minus a multiplier times the poverty line, clipped to zero when the subtraction would otherwise be negative. The multiplier is 1.50 for `IBR` and `PAYE`, and 2.25 for `SAVE`. From discretionary income, the annual obligation is 15% under `IBR`, 10% under `PAYE`, and 10% under `SAVE`. Dividing the annual obligation by 12 yields the monthly amount in fractional cents; that figure is rounded half-up to integer cents and stored as `monthly_payment_cents`. The evaluation order is fixed: discretionary income is computed before rate selection, the rate is applied to discretionary income, the division by twelve is performed after rate selection, and rounding is performed only after the division.

For `STANDARD`, the engine ignores discretionary income and instead amortizes the principal figure (current `principal_balance_cents` plus `capitalized_interest_cents`) over 120 months using the loan's `interest_rate_bps`. Specifically, the monthly rate is `interest_rate_bps` divided by ten thousand and then by twelve; the monthly payment in fractional cents is the principal multiplied by the monthly rate divided by one minus one plus the monthly rate raised to the power negative one hundred and twenty; that fractional figure is rounded half-up to integer cents to produce `monthly_payment_cents`.

The monthly-payment figure is recomputed in three situations: when a `RepaymentPlan` is created, when a plan transitions from `PENDING` to `ACTIVE`, and whenever a new `CERTIFIED` `IncomeCertification` for the same borrower has an `effective_date` on or after the plan's own `effective_date` (the §3.1 cascade).

### 3.6. Posting and Reversing Payments

A payment originates against a single loan and carries a `loan_id`, an `amount_cents` of at least 1, and a `payment_date`. Posting is open to both `Borrower` (against their own loan) and `LoanServicer`. The submitted `payment_date` must be on or before the current server clock — a payment dated in the future is rejected with `ERR_FUTURE_PAYMENT`. The amount itself must not exceed the total outstanding obligation, defined as `principal_balance_cents` plus `accrued_interest_cents`; a value below 1 cent or above that ceiling is rejected with `ERR_PAYMENT_AMOUNT_OUT_OF_RANGE`. This range check applies both at payment creation and again at the moment a `LoanServicer` applies the payment.

A successful create places the payment in `PENDING`. The payment's `repayment_plan_id` is resolved server-side at posting time to whichever plan is currently `ACTIVE` for the loan; clients do not supply it. The fields `principal_applied_cents` and `interest_applied_cents` are left untouched until the payment is applied. The full payment status enumeration is `PENDING`, `APPLIED`, and `REVERSED`, with `APPLIED` and `REVERSED` as terminal states.

Application is the work of a `LoanServicer` and is permitted only when the payment is currently `PENDING` and the parent loan's `status` is `REPAYMENT` or `DEFAULT`. The `DEFAULT` permission exists specifically so that rehabilitation-counter payments can be applied against a defaulted loan. On application, the engine allocates `amount_cents` by a strict waterfall: cents are applied first to `accrued_interest_cents` until that bucket is exhausted, then to `principal_balance_cents`. The actual splits are recorded as `interest_applied_cents` and `principal_applied_cents`; allocation is capped so that neither bucket can become negative. The `is_pslf_qualifying` flag on the payment is then evaluated against the predicate set described in §3.7. Once allocation completes, if the loan's `principal_balance_cents` and `accrued_interest_cents` have both reached zero, the loan auto-transitions from `REPAYMENT` to `PAID_OFF`, writing a `StatusChange` with `reason_code` `PAY_OFF`. The payment's `version` increments by one; mutating side effects on the loan increment `Loan.version` independently.

Reversal exists in two flavors. The first is an explicit reversal by a `LoanServicer` of a payment that is currently `APPLIED`. In this case, `principal_applied_cents` and `interest_applied_cents` are subtracted back from the loan's `principal_balance_cents` and `accrued_interest_cents` respectively — the compensating motion that preserves the system's reversal invariant. That invariant is: within any single loan-status window, the quantity `principal_balance_cents` plus `accrued_interest_cents` plus the sum across `APPLIED` payments of `principal_applied_cents` plus `interest_applied_cents` is constant. Reversal moves the payment to `REVERSED`, recomputes `pslf_qualifying_payment_count` for the loan (because `REVERSED` payments are excluded from the count), and increments both `Payment.version` and `Loan.version`. The second flavor is a cascade rather than an explicit action: when a loan transitions to `DISCHARGED` (see §3.9), every payment for that loan that was still `PENDING` is set to `REVERSED`. Cascade-reversed payments are recorded with `reversed_by_payment_id` left null because no counter-payment originated the reversal; explicitly counter-posted reversals point at the reversing payment record via that field.

### 3.7. PSLF Qualifying Payments

Public Service Loan Forgiveness depends on the loan's `pslf_qualifying_payment_count`, an integer derived from the borrower's payment, employment, and status histories. The count is recomputed whenever any payment transitions between `PENDING`, `APPLIED`, and `REVERSED`; whenever a `QualifyingEmployment` becomes `CERTIFIED`; and whenever an `IncomeCertification` becomes `CERTIFIED`. Reads of the count off the loan are guaranteed to reflect the latest such recomputation.

A payment p contributes to the count for its loan if and only if all six predicates below hold simultaneously. First, p's `status` must be `APPLIED`. Second, p's `loan_id` must equal the loan in question. Third, p's `amount_cents` must be at least the floor of the active plan's `monthly_payment_cents` at the moment of `payment_date` — meaning at least one whole-cent unit short of the full scheduled payment is not enough. Fourth, there must exist a `QualifyingEmployment` belonging to the loan's borrower whose `status` is `CERTIFIED`, whose `employer_type` is either `GOVERNMENT` or `NONPROFIT_501C3`, and whose employment window (the closed interval from `period_start` to `period_end`, inclusive at both ends) contains p's `payment_date`. Fifth, the loan's status on the calendar day of p's `payment_date` must have been `REPAYMENT` — payments dated while the loan was in `IN_SCHOOL`, `GRACE`, `DEFERMENT`, `FORBEARANCE`, or `DEFAULT` do not count toward PSLF. Sixth, the `RepaymentPlan` that was `ACTIVE` for the loan at p's `payment_date` must have had a `plan_type` of `IBR`, `PAYE`, `SAVE`, or `STANDARD`. The scan order over payments is by `payment_date` ascending with ties broken by `created_at` ascending so that the result is deterministic.

The same predicate set determines the `is_pslf_qualifying` boolean stored on each payment at the moment of `PENDING` to `APPLIED` transition. The PSLF discharge pathway requires `pslf_qualifying_payment_count` to be at least 120.

### 3.8. Default, Delinquency, and the Path Back

The loan's `delinquency_days` field is a computed integer derived against the current server clock: the count of days the oldest still-owed scheduled payment has been past due. When no past-due payment exists, the value is zero. A `CollectionsAgent` may declare default by transitioning a loan from `REPAYMENT` to `DEFAULT`; the transition requires `delinquency_days` to be at least 270, and an attempt to declare default with a lower count is rejected with `ERR_DEFAULT_THRESHOLD_NOT_MET`. The resulting `StatusChange` carries `reason_code` `DEFAULT_DECLARATION`. The transition also fires a cascade against any `RepaymentPlan` for that loan whose `status` is `ACTIVE`: each such plan is moved from `ACTIVE` to `SUPERSEDED`, has its `superseded_by_plan_id` set to null to mark the supersession as statutory rather than competitive, and has its `version` incremented independently of the loan's increment.

The rehabilitation pathway is the way back. A `CollectionsAgent` initiates the rehabilitate transition only when the loan's `status` is `DEFAULT`, and the transition's business precondition is that the loan must have at least 9 payments with `status` `APPLIED` whose `payment_date` is strictly later than the `effective_at` of the most recent `StatusChange` carrying `reason_code` `DEFAULT_DECLARATION`. When that count is less than 9, the transition is rejected with `ERR_REHABILITATION_NOT_QUALIFIED`. On success, the loan returns to `REPAYMENT` and a `StatusChange` is written with `reason_code` `REHABILITATION_COMPLETE`.

### 3.9. Discharge Applications: Veterans and PSLF

A `Borrower` may file a discharge application against one of their loans. The submission carries `loan_id`, the requested `discharge_type` from the enumeration `VETERAN_TOTAL_DISABILITY` or `PSLF`, and an optional `review_notes` field for the reviewer's record. The application is created in `SUBMITTED`. Its full lifecycle enumeration is `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, and `DENIED`, with `APPROVED` and `DENIED` as terminal states.

A `LoanServicer` begins review by transitioning the application from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW`, the reviewer chooses one of two terminal paths.

Denial moves the application from `UNDER_REVIEW` to `DENIED` and persists any supplied `review_notes` on the application; the `version` advances and `updated_at` refreshes.

Approval is the high-consequence path and has the strictest precondition stack. It is requested by a `LoanServicer`, and the request body must carry `expected_application_version` to guard against stale-reviewer races (§2.5). The application must currently be in `UNDER_REVIEW`. Two business-safety predicates then apply depending on `discharge_type`, and they are checked before the optimistic-concurrency token: when `discharge_type` is `VETERAN_TOTAL_DISABILITY`, the borrower's `is_veteran` must be true, and a false value rejects with `ERR_NOT_VETERAN`; when `discharge_type` is `PSLF`, the loan's `pslf_qualifying_payment_count` must be at least 120, and a lower value rejects with `ERR_PSLF_INSUFFICIENT_PAYMENTS`. On a successful approve, `review_notes` is persisted, the application's `status` advances to `APPROVED`, and a two-step cascade fires. First, the parent loan transitions from `REPAYMENT` to `DISCHARGED`, with `principal_balance_cents` and `accrued_interest_cents` both being set to zero, and a `StatusChange` is written with `reason_code` `DISCHARGE_APPROVED`. Second, that loan transition itself triggers the cascade that moves every payment for the loan whose `status` is `PENDING` to `REVERSED`. Each entity touched by the cascade — the discharge application, the loan, the affected payments — increments its own `version`.

### 3.10. The Status-Change Audit Trail

Every loan status transition produces a `StatusChange` row. The row captures the `loan_id`, the `from_status` and `to_status` involved, the `reason_code` drawn from the enumeration `GRACE_AUTO_START`, `GRACE_AUTO_END`, `DEFERMENT_REQUEST`, `FORBEARANCE_REQUEST`, `RESUME_REPAYMENT`, `DEFAULT_DECLARATION`, `REHABILITATION_COMPLETE`, `PAY_OFF`, and `DISCHARGE_APPROVED`, the `actor_role` that initiated the transition, and the UTC `effective_at` instant. Listings of these rows for a loan return them in ascending order — first by `effective_at`, then by `created_at` as the tiebreaker. Because `StatusChange` is purely append-only, it carries `id` and `created_at` but no `updated_at` and no `version`.

## 4. Endpoint Definitions

New resource creation returns HTTP 201. State transitions, retrievals, and listings return HTTP 200. Error responses use the HTTP status declared per error in §5. Request bodies, response bodies, and side effects are not summarized in this table; they are described in the relevant workflow narrative in §3 and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /loan-servicing/borrowers | Create a borrower | LoanServicer |
| GET | /loan-servicing/borrowers/{id} | Retrieve a borrower (computed AGI/family-size fields included) | LoanServicer, Borrower, CollectionsAgent |
| GET | /loan-servicing/borrowers | List borrowers | LoanServicer |
| POST | /loan-servicing/loans | Create a loan in ORIGINATED status | LoanServicer |
| GET | /loan-servicing/loans/{id} | Retrieve a loan (computed fields included) | LoanServicer, Borrower, CollectionsAgent |
| GET | /loan-servicing/loans | List loans, optionally filtered by borrower | LoanServicer, CollectionsAgent |
| POST | /loan-servicing/loans/{id}/enter-school | Transition ORIGINATED to IN_SCHOOL | LoanServicer |
| POST | /loan-servicing/loans/{id}/graduate | Transition IN_SCHOOL to GRACE | LoanServicer |
| POST | /loan-servicing/loans/{id}/start-repayment | Transition GRACE to REPAYMENT | LoanServicer |
| POST | /loan-servicing/loans/{id}/request-deferment | Transition REPAYMENT to DEFERMENT (borrower-initiated) | Borrower |
| POST | /loan-servicing/loans/{id}/request-forbearance | Transition REPAYMENT to FORBEARANCE (borrower-initiated) | Borrower |
| POST | /loan-servicing/loans/{id}/resume-repayment | Transition DEFERMENT or FORBEARANCE back to REPAYMENT (capitalizes accrued interest) | LoanServicer |
| POST | /loan-servicing/loans/{id}/declare-default | Transition REPAYMENT to DEFAULT | CollectionsAgent |
| POST | /loan-servicing/loans/{id}/rehabilitate | Transition DEFAULT to REPAYMENT | CollectionsAgent |
| GET | /loan-servicing/loans/{id}/status-changes | List a loan's status-change history (ASC by effective_at then created_at) | LoanServicer, Borrower, CollectionsAgent |
| POST | /loan-servicing/repayment-plans | Create a repayment plan in PENDING status | LoanServicer |
| POST | /loan-servicing/repayment-plans/{id}/activate | Transition PENDING to ACTIVE (supersedes any prior ACTIVE plan for the same loan) | LoanServicer |
| GET | /loan-servicing/repayment-plans/{id} | Retrieve a repayment plan | LoanServicer, Borrower |
| GET | /loan-servicing/repayment-plans | List repayment plans (filterable by loan_id and/or superseded_by_plan_id) | LoanServicer, Borrower |
| POST | /loan-servicing/income-certifications | File an income certification (SUBMITTED) | Borrower |
| POST | /loan-servicing/income-certifications/{id}/certify | Transition SUBMITTED to CERTIFIED | LoanServicer |
| GET | /loan-servicing/income-certifications/{id} | Retrieve an income certification | LoanServicer, Borrower |
| GET | /loan-servicing/income-certifications | List income certifications (filter by borrower) | LoanServicer, Borrower |
| POST | /loan-servicing/qualifying-employments | File a qualifying-employment record (SUBMITTED) | Borrower |
| POST | /loan-servicing/qualifying-employments/{id}/certify | Transition SUBMITTED to CERTIFIED | LoanServicer |
| GET | /loan-servicing/qualifying-employments/{id} | Retrieve a qualifying-employment record | LoanServicer, Borrower |
| GET | /loan-servicing/qualifying-employments | List qualifying-employment records (filter by borrower) | LoanServicer, Borrower |
| POST | /loan-servicing/payments | Post a payment (PENDING) | Borrower, LoanServicer |
| POST | /loan-servicing/payments/{id}/apply | Transition PENDING to APPLIED (waterfall to interest then principal; may auto-trigger PAID_OFF) | LoanServicer |
| POST | /loan-servicing/payments/{id}/reverse | Transition APPLIED to REVERSED (compensating reversal) | LoanServicer |
| GET | /loan-servicing/payments/{id} | Retrieve a payment | LoanServicer, Borrower |
| GET | /loan-servicing/payments | List payments (filter by loan_id, repayment_plan_id, and/or reversed_by_payment_id) | LoanServicer, Borrower |
| POST | /loan-servicing/discharge-applications | File a discharge application (SUBMITTED) | Borrower |
| POST | /loan-servicing/discharge-applications/{id}/begin-review | Transition SUBMITTED to UNDER_REVIEW | LoanServicer |
| POST | /loan-servicing/discharge-applications/{id}/approve | Transition UNDER_REVIEW to APPROVED (cascades loan to DISCHARGED, then cascades PENDING payments to REVERSED) | LoanServicer |
| POST | /loan-servicing/discharge-applications/{id}/deny | Transition UNDER_REVIEW to DENIED | LoanServicer |
| GET | /loan-servicing/discharge-applications/{id} | Retrieve a discharge application | LoanServicer, Borrower |
| GET | /loan-servicing/discharge-applications | List discharge applications (filter by loan) | LoanServicer, Borrower |
| POST | /loan-servicing/_clock/set_current_utc | Test-driving: advance the server clock to a supplied UTC instant; triggers interest-accrual recomputation | LoanServicer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_LOAN_NOT_FOUND | 404 |
| ERR_BORROWER_NOT_FOUND | 404 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_PLAN_ALREADY_ACTIVE | 409 |
| ERR_NOT_VETERAN | 422 |
| ERR_PSLF_INSUFFICIENT_PAYMENTS | 422 |
| ERR_DEFAULT_THRESHOLD_NOT_MET | 422 |
| ERR_REHABILITATION_NOT_QUALIFIED | 422 |
| ERR_STALE_LOAN_VERSION | 412 |
| ERR_STALE_APPLICATION_VERSION | 412 |
| ERR_INVALID_PERIOD | 422 |
| ERR_FUTURE_PAYMENT | 422 |
| ERR_PAYMENT_AMOUNT_OUT_OF_RANGE | 422 |
| ERR_INVALID_REQUEST | 400 |
