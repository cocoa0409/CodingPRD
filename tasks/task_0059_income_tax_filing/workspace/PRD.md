# Income Tax Filing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Income Tax Filing API, a backend service that models the end-to-end preparation, computation, electronic filing, and amendment of a personal income tax return in the style of consumer tax-preparation software. A filer assembles a return for a given tax year by importing income documents — W-2 wage statements and the family of 1099 forms (nonemployee compensation, interest, dividends, and brokerage proceeds) — attaching supplemental schedules, declaring dependents, and claiming refundable and nonrefundable tax credits. The service then aggregates this raw data into a coherent tax computation: total income, adjusted gross income, taxable income after the elected deduction, bracket tax, credit allowances net of phase-outs, payments already made through withholding and quarterly estimates, and finally the balance the filer owes or is refunded.

The system is fundamentally a **ledger-reconciliation engine wrapped in a compliance workflow**. Every monetary figure is carried in integer cents, and the relationships between figures must reconcile exactly — a corrected return's adjustment must sum back to the original, and a payment ledger must remain conserved across a reject-and-reopen revision cycle. Layered on top of this arithmetic core is a strict authorization and lifecycle discipline: a return moves through draft, computed, and filed states; only the taxpayer who owns a return may sign and transmit it for e-filing; an external acknowledgement actor records the IRS accept/reject outcome; and a filed return may later be superseded by a 1040X amendment. Because multiple actors may act on the same return, the service uses optimistic concurrency control on the operations that freeze financial snapshots, ensuring no client transmits or amends against a figure it never observed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `Taxpayer`, `Preparer`, and `IrsGateway`. When an authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `Taxpayer` is the filer who owns the return and its children. When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `Taxpayer` entity; ownership checks on any resource that references a `Taxpayer` compare the resource's owning taxpayer (a return's `taxpayer_id`, or an amendment's `taxpayer_id`) to `X-User-ID`. The `Taxpayer` is the only role that may sign and transmit an e-file submission, create a 1040X amendment, and file that 1040X.

The `Preparer` is a paid preparer acting on a taxpayer's behalf. When `X-User-Role` is `Preparer`, `X-User-ID` is likewise the `id` of the represented `Taxpayer` entity; the same ownership checks apply, comparing the resource's owning taxpayer to `X-User-ID`. A `Preparer` may build and compute a return and manage its children, but by segregation of duties may not sign or transmit an e-file, nor create or file a 1040X — those attempts are denied with `ERR_FORBIDDEN_ROLE`.

The `IrsGateway` is an external acknowledgement actor. When `X-User-Role` is `IrsGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The gateway's sole mutating capability is recording an accept or reject acknowledgement on a transmitted submission.

For any operation that targets a specific return or amendment owned by a taxpayer, if the acting `Taxpayer` or `Preparer` `X-User-ID` does not match the owning taxpayer, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless otherwise stated, list endpoints return resources sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource in this system — `Taxpayer`, `TaxReturn`, `IncomeDocument`, `Schedule`, `Dependent`, `CreditClaim`, `EstimatedTaxPayment`, `EFilingSubmission`, and `AmendedReturn` — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Each of these resources additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by one with each subsequent mutation. The `version` field underpins the optimistic concurrency control described in §2.8.

### 2.5. Monetary Values, Cents, and Rounding

All money in this system is represented as **integer cents** — there are no fractional cents and no floating-point money anywhere in the model. Every amount field (income box amounts, withholding, deductions, credits, payments, balances, penalties) is a signed or unsigned integer count of cents, and every arithmetic step in the computations of §3 is performed in integer cents. Where a calculation introduces a fraction — a percentage of a figure, a prorated phase-out — the result is taken to the nearest cent by **rounding down (floor)** unless a specific computation pins a different order. The bracket-tax computation and the per-credit phase-outs each pin their rounding order explicitly in §3; those pinned orders are part of the contract and must be honored exactly, because rounding before versus after an intermediate step can shift a final figure by a cent.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource nested beneath a return, such as a return's income documents, schedules, dependents, or credit claims, or address an e-file submission or amendment by id. The system validates path-referenced resources left to right and rejects the first identifier that does not resolve. A path that names a `TaxReturn`, `EFilingSubmission`, or `AmendedReturn` id that does not exist is rejected with `ERR_RETURN_NOT_FOUND` (HTTP 404). Separately, when a request body names a foreign-key target — a `taxpayer_id`, a `return_id`, or an `original_return_id` — that does not resolve to an existing entity, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.7. Hierarchical Consistency and the Compute Invalidation Rule

A `TaxReturn` is the aggregate root; its `IncomeDocument`, `Schedule`, `Dependent`, and `CreditClaim` children, together with the `EstimatedTaxPayment` rows that reference it, are the inputs to its computation. Whenever a child is added or an income document, schedule, dependent, or credit claim is created on a return that is currently in `READY` status, that mutation invalidates the prior computation: the return is reset to `DRAFT`, its `updated_at` is refreshed, and its `version` is incremented by one. This is the cross-entity dependency rule that ties children to the freshness of the return's computed figures. Every operation that mutates a return — whether a direct edit, a compute, an e-file transmission, an acknowledgement-driven transition, or an amendment cascade — refreshes the return's `updated_at` and increments its `version`.

### 2.8. Optimistic Concurrency Control

Two write operations freeze or supersede a financial snapshot and therefore require the client to prove it is acting on a current view of the target return. Both require a non-optional `expected_return_version` field in the request body, carrying the `version` of the `TaxReturn` the client last observed.

The first is transmitting a return for e-filing. A transmission request must carry `expected_return_version` equal to the target return's current `version`. If a compute or any other writer has advanced the return's `version` since the client last read it — which may have changed `balance_due_cents`, making the snapshot the e-file would freeze stale — the transmission is rejected with `ERR_STALE_RETURN_VERSION` (HTTP 412).

The second is creating a 1040X amendment. The create request must carry `expected_return_version` equal to the current `version` of the original return being amended. If another amendment has already advanced the original return's `version` (for instance by moving it toward `AMENDED` and superseding the prior corrected figures), the creator's view is stale and the create is rejected with `ERR_STALE_RETURN_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: presence and validity of the headers (`ERR_UNAUTHENTICATED`). Then role permission for the operation (`ERR_FORBIDDEN_ROLE`). Then resource ownership for taxpayer-owned returns and amendments (`ERR_NOT_RESOURCE_OWNER`). Then existence of path-referenced resources (`ERR_RETURN_NOT_FOUND`), followed by existence of body foreign-key targets (`ERR_FK_NOT_FOUND`). Then request-body well-formedness — required fields present, enum values in range, and money fields satisfying their declared sign and bound constraints (`ERR_INVALID_REQUEST`, HTTP 422). Then state-machine legality of the requested transition (`ERR_INVALID_STATE`, HTTP 409). After these, the domain-specific business checks of §3 apply — child uniqueness, the income-document and Schedule A requirements for compute, the computed-and-current requirement for e-file, the optimistic-concurrency version match, the already-filed guard, the original-must-be-filed guard, the estimated-payment period overlap, and the correction-window overlap — each surfacing its own error as described in the workflow that owns it. Auth header validity, role permission, and existence checks apply to all operations; the foreign-key existence check applies to every creation endpoint that names a foreign key.

## 3. Business Logic & Workflows

### 3.1. Registering Taxpayers and Opening a Return

The journey begins with a `Taxpayer` record, registered by providing an `email` that serves as the login identity and must be unique across taxpayers and non-empty, a legal `full_name` for the return, and a default `filing_status` that is one of `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, or `HEAD_OF_HOUSEHOLD`. Two further inputs capture the prior tax year for safe-harbor purposes: `prior_year_agi_cents`, the prior-year adjusted gross income in cents, and `prior_year_total_tax_cents`, the prior-year total tax liability in cents; both default to 0 if omitted and both feed the estimated-tax safe-harbor variants of §3.7.

A return is opened against a taxpayer by supplying that taxpayer's `taxpayer_id`, the `tax_year` (an integer that must be at least 2020), and the `filing_status` for this particular return. The caller may also set `deduction_method`, which is either `STANDARD` or `ITEMIZED` and defaults to `STANDARD`. A newly created return begins life in `DRAFT` status with `version` 1, and all of its computed money fields — `total_income_cents`, `agi_cents`, `taxable_income_cents`, `tax_before_credits_cents`, `total_credits_cents`, `tax_after_credits_cents`, `total_payments_cents`, and `balance_due_cents` — start at 0, with `computed_at` null until the first successful computation. Return-level fields may later be edited: a taxpayer or preparer may change `deduction_method` or `filing_status` on a return, and may set a `reopen` flag to reopen a rejected return (described in §3.6). Returns can be fetched individually or listed, and the list may be filtered by `taxpayer_id` and by `status`.

### 3.2. Assembling Income Documents and Schedules

Income enters the return as `IncomeDocument` records, each created against its parent return and carrying a `doc_type` — one of `W2`, `1099_NEC`, `1099_INT`, `1099_DIV`, or `1099_B` — and a `payer_name` as printed on the form. The principal money box, `box_amount_cents`, holds W-2 box-1 wages, 1099-NEC nonemployee compensation, 1099-INT interest, or 1099-DIV ordinary dividends, and must be at least 0. Federal income tax withheld on the document is recorded in `federal_withholding_cents`, which defaults to 0 and must be at least 0. A 1099-DIV may also report `qualified_dividends_cents`, a subset of the box amount that defaults to 0, must be at least 0, and may not exceed `box_amount_cents`; it is ignored unless the document is a 1099-DIV. A 1099-B carries `proceeds_cents` (gross proceeds) and `cost_basis_cents` (cost basis), each defaulting to 0 and each at least 0, together with `holding_long_term`, a boolean defaulting to false that is true when the lot was held longer than one year; these three are ignored for any document that is not a 1099-B. Income documents can be listed for a return.

Supplemental detail is captured as `Schedule` records, each created against its return with a `schedule_type` that is one of `A` (itemized deductions), `B` (interest and dividends), `C` (business profit and loss), `D` (capital gains), or `E` (rental and royalty). At most one schedule of each type may exist on a return; attempting to add a second schedule of a type already present is rejected with `ERR_DUPLICATE_CHILD` (HTTP 409). A schedule carries `gross_amount_cents`, the schedule-specific gross figure — total itemized deductions for A, gross receipts for C, gross rents for E — which defaults to 0 and must be at least 0, and `expense_amount_cents`, the deductible expenses for C and E, which defaults to 0, must be at least 0, and is ignored for A, B, and D. Each schedule also exposes a computed `net_amount_cents`, recomputed on every compute as described in §3.5. Schedules can be listed for a return.

Dependents are added as `Dependent` records on the return, each with a `full_name`, an `age_years` (the dependent's whole-year age at year end, at least 0), and an `is_student` flag defaulting to false that marks a qualifying full-time student and bears on education-credit eligibility. Each dependent also carries a computed `qualifies_ctc` flag, defaulting to false, set true exactly when the dependent's `age_years` is less than 17 at year end; this flag drives the per-child count for the Child Tax Credit. Dependents can be listed for a return.

### 3.3. Claiming Credits

A filer declares an intended credit as a `CreditClaim` on the return, naming a `credit_type` that is one of `EITC`, `CTC`, or `AOTC`, with at most one claim of each type per return; a second claim of a type already present is rejected with `ERR_DUPLICATE_CHILD` (HTTP 409). The claimed figure is `claimed_amount_cents`, the amount asserted before any eligibility test or phase-out is applied; it defaults to 0 and must be at least 0. Two computed fields are filled in during compute: `allowed_amount_cents`, the amount actually allowed after eligibility, per-child or per-student caps, and AGI phase-out; and `refundable_cents`, the portion of the allowed amount that is refundable. The Earned Income Tax Credit is fully refundable, the American Opportunity Tax Credit is forty percent refundable, and the Child Tax Credit is treated here as wholly nonrefundable (its refundable portion is 0). Credit claims can be listed for a return. The exact allowance arithmetic for each credit is given in §3.5.

### 3.4. Recording Estimated Tax Payments

Quarterly estimated payments are recorded as `EstimatedTaxPayment` records that reference their return through `return_id`. Each names a `quarter` — one of `Q1`, `Q2`, `Q3`, or `Q4` — with at most one payment per quarter per return (a second payment for a quarter already recorded on the same return is rejected with `ERR_DUPLICATE_CHILD`, HTTP 409), an `amount_cents` that must be strictly greater than 0, and a `paid_on` date in ISO 8601. Each payment also declares the income period it covers with `period_start` and `period_end` in ISO 8601, where `period_end` must be strictly after `period_start`. The period is treated as a half-open interval that includes the start and excludes the end. A new payment's period may not overlap the half-open period of any existing payment on the same return; two periods that merely touch at a shared endpoint — where an existing payment's `period_end` equals the new payment's `period_start` — do not overlap and are allowed, while any genuine overlap is rejected with `ERR_PAYMENT_PERIOD_OVERLAP` (HTTP 409).

On creation, each payment's `on_time` flag is computed: it is true when `paid_on` is on or before the statutory due date for its quarter, and false otherwise. The due dates are fixed: Q1 is due at the final instant of April 15, 2025 (UTC); Q2 at the final instant of June 16, 2025; Q3 at the final instant of September 15, 2025; and Q4 at the final instant of January 15, 2026. The `on_time` flag drives the underpayment-penalty computation of §3.7. Recording a payment increments the referenced return's `version` by one. Payments can be fetched individually or listed, and the list may be filtered by `return_id`.

### 3.5. The Compute: From Raw Data to Balance Due

Computing a return is the heart of the system and is performed by the taxpayer or preparer. A compute is only permitted when the return holds at least one income document; an attempt to compute a return with no income documents is rejected with `ERR_NO_INCOME_DOCUMENTS` (HTTP 409). When the return's `deduction_method` is `ITEMIZED`, a Schedule A must be present at compute time; otherwise the compute is rejected with `ERR_ITEMIZED_REQUIRES_SCHEDULE_A` (HTTP 409). A compute on a `DRAFT` return advances it to `READY`; a compute on a return already in `READY` recomputes in place and leaves it `READY`. Compute is idempotent in the sense that re-running it on the same children yields the same figures, and it is re-runnable to pick up edits made while the return is still `READY`. Every compute uses all `IncomeDocument`, `Schedule`, `CreditClaim`, `Dependent`, and `EstimatedTaxPayment` rows whose `return_id` is this return — children have no lifecycle of their own and are never filtered by status. Each compute sets `computed_at` to the current time and increments the return's `version` by one.

The compute proceeds in a pinned order. **First, the capital-gain step recomputes Schedule D.** Over all 1099-B documents on the return, the raw net is the sum of each document's `proceeds_cents` minus its `cost_basis_cents`, combining short-term and long-term lots together. If that raw net is zero or positive, Schedule D's `net_amount_cents` is that raw net. If it is negative, the net loss is limited so it is no more negative than negative three hundred thousand cents — that is, a net loss is capped at a deductible maximum of three thousand dollars, and any loss beyond that is not deducted. Schedule D is materialized or refreshed whenever 1099-B documents exist, and the result is written onto that schedule's `net_amount_cents`. This step involves only subtraction and the loss cap; no rounding is performed.

**Next, each schedule's net is set.** For Schedule C and Schedule E, `net_amount_cents` is `gross_amount_cents` minus `expense_amount_cents` and may be negative. For Schedule A, the net equals its `gross_amount_cents` (the total itemized deductions). For Schedule B, the net is 0. Schedule D's net is the capital-gain figure just computed. Each dependent's `qualifies_ctc` is also refreshed here per the under-17 rule of §3.2.

**Then income is aggregated.** Wages is the sum of `box_amount_cents` over W-2 documents; nonemployee compensation is the sum over 1099-NEC documents; interest is the sum over 1099-INT documents; dividends is the sum over 1099-DIV documents. To these are added the net of Schedule C, the net of Schedule E, and the net of Schedule D, each taken as 0 if that schedule does not exist. The sum of all seven terms is `total_income_cents`. Because no above-the-line adjustments are modeled, `agi_cents` is `total_income_cents` floored at 0 (never negative).

**Credits are then allowed**, before tax-after-credits is settled, using `agi_cents` from the aggregation just completed. The detailed credit arithmetic is given immediately below; it sets each claim's `allowed_amount_cents` and `refundable_cents`.

**The deduction and bracket tax follow.** When `deduction_method` is `STANDARD`, the deduction is the standard-deduction figure for the return's `filing_status`: fifteen hundred thousand cents ($15,000.00) for `SINGLE`, three million cents ($30,000.00) for `MARRIED_JOINT`, fifteen hundred thousand cents ($15,000.00) for `MARRIED_SEPARATE`, and two million two hundred fifty thousand cents ($22,500.00) for `HEAD_OF_HOUSEHOLD`; under the standard method, Schedule A is ignored even if present. When `deduction_method` is `ITEMIZED`, the deduction is Schedule A's `gross_amount_cents` (equivalently its net). Taxable income, `taxable_income_cents`, is `agi_cents` minus the deduction, floored at 0. The same income data therefore yields a different taxable income, and hence a different balance, depending on which deduction method is elected.

Bracket tax, `tax_before_credits_cents`, applies marginal tiered rates to `taxable_income_cents` according to the filing status. For `SINGLE` and `MARRIED_SEPARATE`, the first tier is 10% on taxable income up to 1,160,000 cents, the second tier is 12% on the portion above 1,160,000 and up to 4,715,000 cents, and the third tier is 22% on any portion above 4,715,000 cents. For `MARRIED_JOINT`, the first tier is 10% up to 2,320,000 cents, the second tier is 12% on the portion above 2,320,000 and up to 9,430,000 cents, and the third tier is 22% above 9,430,000 cents. `HEAD_OF_HOUSEHOLD` uses the same tier structure as `SINGLE`. The rounding order here is pinned: the tax for each tier is computed and **rounded down to the nearest whole cent before the tiers are summed** — round per tier first, then add — and the sum is `tax_before_credits_cents`.

**Tax after credits** combines the allowed credits with the bracket tax. Sum the nonrefundable portion of every claim — that is, each claim's `allowed_amount_cents` minus its `refundable_cents` — and call it the nonrefundable total; sum each claim's `refundable_cents` for the refundable total; and note that `total_credits_cents` is the sum of every claim's `allowed_amount_cents`. The bracket tax is first reduced by the nonrefundable total but not below 0, and then the refundable total is subtracted from that floored result. Thus `tax_after_credits_cents` is bracket tax minus nonrefundable credits floored at 0, minus refundable credits — and it may go negative when refundable credits exceed the remaining tax.

**Payments and balance close the computation.** `total_payments_cents` is the sum of `federal_withholding_cents` over all income documents plus the sum of `amount_cents` over all estimated payments on the return. `balance_due_cents` is `tax_after_credits_cents` minus `total_payments_cents`: a positive figure is owed by the filer, a negative figure is a refund owed to the filer.

The credit allowance, run during the credit step above, works claim by claim. For the **Child Tax Credit**, count the dependents whose `age_years` is less than 17 (their `qualifies_ctc` is true); the allowed amount is the smaller of the CTC claim's `claimed_amount_cents` and that child count multiplied by two hundred thousand cents ($2,000.00 per qualifying child). The CTC is treated as nonrefundable, so its `refundable_cents` is 0. For the **American Opportunity Tax Credit**, first form a base equal to the smaller of the AOTC claim's `claimed_amount_cents` and the count of student dependents (those with `is_student` true) multiplied by two hundred fifty thousand cents ($2,500.00 per student). Then apply the AGI phase-out: if `agi_cents` is at most eight million cents ($80,000.00), the allowed amount is the full base with no proration; if `agi_cents` is at least nine million cents ($90,000.00), the allowed amount is 0; otherwise the allowed amount is the base multiplied by the quantity (nine million cents minus `agi_cents`) divided by (nine million cents minus eight million cents), with the result rounded down to the nearest cent. The AOTC's refundable portion is then forty percent of that already-floored allowed amount, again rounded down to the nearest cent — the rounding order is pinned so that the refundable portion is computed from the floored allowed amount, not from the unfloored base. For the **Earned Income Tax Credit**, which is fully refundable, first cap the claim at a band maximum keyed to the number of qualifying children counted for the CTC: the EITC maximum is 60,000 cents for zero such children, 396,000 cents for one, and 655,000 cents for two or more. The capped figure is the smaller of the EITC claim's `claimed_amount_cents` and that band maximum. Then compute the excess of `agi_cents` over two million cents ($20,000.00), taking 0 if AGI is at or below that threshold; reduce the capped figure by twenty-one percent of that excess rounded down to the nearest cent, and floor the result at 0. The EITC allowed amount is fully refundable, so its `refundable_cents` equals its `allowed_amount_cents`.

### 3.6. Electronic Filing and the Reject-and-Reopen Loop

Once a return is computed and current, the taxpayer signs and transmits it for e-filing — an action reserved to the `Taxpayer` role; a `Preparer` attempting it is denied with `ERR_FORBIDDEN_ROLE`. The transmission carries a `signature_pin`, the self-select PIN the taxpayer signs with, and the `expected_return_version` required by the optimistic-concurrency rule of §2.8. Transmission is only allowed from `READY`: the return's `computed_at` must reflect the current children with no edit since the last compute. If the return is `DRAFT` (its compute is stale or absent), the transmission is rejected with `ERR_RETURN_NOT_COMPUTED` (HTTP 409); if the return is not in a state from which transmission is defined, the broader state guard yields `ERR_INVALID_STATE` (HTTP 409). A return may not be transmitted twice while a non-`REJECTED` submission already exists for it — a second attempt is rejected with `ERR_ALREADY_EFILED` (HTTP 409). A successful transmission creates an `EFilingSubmission` in `TRANSMITTED` status with `snapshot_balance_due_cents` frozen from the return's current `balance_due_cents` for audit, and increments the return's `version` by one. The submission also carries an `ack_code` (the IRS acknowledgement or reject-reason code, null until set by the gateway) and a `superseded_by_amendment` flag (defaulting to false, described in §3.7). Submissions can be fetched individually or listed, optionally filtered by `return_id`.

The external `IrsGateway` records the outcome by acknowledging a submission with an `outcome` of either `ACCEPTED` or `REJECTED` and an `ack_code`. Acknowledgement is only defined when the submission is in `TRANSMITTED`; otherwise it is rejected with `ERR_INVALID_STATE`. When the outcome is `ACCEPTED`, the submission moves `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version` increments, and the parent return is driven `READY → FILED` with the return's `version` incremented. When the outcome is `REJECTED`, the submission moves `TRANSMITTED → REJECTED`, its `ack_code` is set from the request, its `version` increments, and the parent return is driven `READY → REJECTED` with the return's `version` incremented. These two branches are symmetric in everything but their target states and the parent transition they trigger.

A rejected return enters the revision loop. The taxpayer or preparer reopens it by editing the return with the `reopen` flag set true while the return is in `REJECTED`, which moves it `REJECTED → DRAFT` and increments its `version`. The filer then corrects the children, recomputes (advancing `DRAFT → READY`), and re-transmits. This loop is payment-neutral by invariant: across a reopen and the compensating recompute, when no income document and no estimated payment is added or removed in between, `total_payments_cents` must be left exactly unchanged from its value before rejection. Concretely, `total_payments_cents` always equals the sum of `federal_withholding_cents` over the income documents plus the sum of `amount_cents` over the estimated payments, and that identity must hold with zero drift across the reopen-and-recompute cycle.

### 3.7. Amendments, the Estimated-Tax Projection, and the Supersession Cascade

After a return is filed, the taxpayer may correct it with a 1040X amendment. Creating an amendment is reserved to the `Taxpayer` role and names the `original_return_id` of the prior return being amended, the `taxpayer_id`, the `corrected_balance_due_cents` (the recomputed, signed balance due on the corrected figures), and the closed correction window it covers via `correction_period_start` and `correction_period_end` in ISO 8601, where the window is inclusive of both endpoints. The create also carries `expected_return_version` for the optimistic-concurrency check of §2.8. The amendment may only target an original return currently in `FILED` status — not `DRAFT`, `READY`, or `AMENDED` — and a violation is rejected with `ERR_ORIGINAL_NOT_FILED` (HTTP 409). Two amendments on the same `original_return_id` may not have correction windows that overlap, and because the window is closed, windows that merely touch at a shared endpoint — where an existing amendment's end equals the new amendment's start — do count as overlap; any such conflict is rejected with `ERR_CORRECTION_WINDOW_OVERLAP` (HTTP 409). A created amendment begins in `DRAFT` status, and its creation increments the original return's `version` by one. Amendments can be fetched individually or listed, filtered by `original_return_id` or by `taxpayer_id`. Each amendment carries a computed `delta_cents`, defaulting to 0 until filing.

Filing the 1040X is again reserved to the `Taxpayer` and is only defined when the amendment is in `DRAFT` and the original return is still `FILED` (the cross-entity guard reuses `ERR_ORIGINAL_NOT_FILED`). Filing triggers a three-hop cascade. First, the amendment delta is computed: `delta_cents` is set to `corrected_balance_due_cents` minus the original return's frozen `balance_due_cents`, and the amendment moves `DRAFT → FILED` with its `version` incremented. Second, the original return is driven `FILED → AMENDED`, refreshing its `updated_at` and incrementing its `version`. Third, that `AMENDED` transition cascades to the original return's `ACCEPTED` e-file submission, setting that submission's `superseded_by_amendment` flag to true and incrementing its `version` — marking the superseded submission for audit. This identity must hold exactly after filing: the original's frozen `balance_due_cents` plus the amendment's `delta_cents` equals the amendment's `corrected_balance_due_cents`, reconstructing the corrected balance with zero drift.

Separately, at any time a taxpayer or preparer may request an **estimated-tax status projection** for a return, a read-only computation that reports the required annual estimated payment as `required_annual_cents`, the on-time coverage as `covered_cents`, the shortfall as `shortfall_cents`, the penalty as `penalty_cents`, and which safe harbor was used as `safe_harbor_used`. The required annual estimated payment is the lesser of two safe harbors. The current-year safe harbor is ninety percent of the return's `tax_after_credits_cents`, rounded down to the nearest cent. The prior-year safe harbor is the taxpayer's `prior_year_total_tax_cents` multiplied by a rate, rounded down: that rate is one hundred percent normally, but one hundred ten percent when the taxpayer's `prior_year_agi_cents` is strictly greater than fifteen million cents ($150,000.00 prior-year AGI). The required annual amount is the smaller of the current-year and prior-year figures; when the current-year figure is the lesser (or equal), the current-year safe harbor governs, and when the prior-year figure is strictly smaller, the prior-year safe harbor governs — identical current-year figures can yield a different required amount, and therefore a different penalty, depending on which harbor binds. Coverage is the sum of `amount_cents` over only the estimated payments whose `on_time` flag is true, plus the sum of `federal_withholding_cents` over all income documents (withholding is always treated as timely). The shortfall is the required annual amount minus the coverage, floored at 0. The penalty is eight percent of that shortfall, rounded down to the nearest cent. The same underpayment-penalty computation also runs as part of freezing the snapshot at e-file transmission.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that fetch, list, or modify an existing resource — including the compute, the estimated-tax-status projection, the acknowledgement, and the 1040X file action — return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/taxpayers` | Register a taxpayer | Taxpayer, Preparer |
| GET | `/taxpayers/{id}` | Fetch a taxpayer | Taxpayer, Preparer |
| POST | `/tax-returns` | Create a draft return for a taxpayer | Taxpayer, Preparer |
| GET | `/tax-returns/{id}` | Fetch a return with computed fields | Taxpayer, Preparer |
| GET | `/tax-returns` | List returns, filterable by taxpayer and status | Taxpayer, Preparer |
| PATCH | `/tax-returns/{id}` | Edit return-level fields or reopen a rejected return | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/compute` | Compute income, credits, tax, payments, and balance | Taxpayer, Preparer |
| GET | `/tax-returns/{id}/estimated-tax-status` | Required estimated tax, coverage, and underpayment penalty | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/income-documents` | Add an income document to a return | Taxpayer, Preparer |
| GET | `/tax-returns/{id}/income-documents` | List income documents for a return | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/schedules` | Add a schedule to a return | Taxpayer, Preparer |
| GET | `/tax-returns/{id}/schedules` | List schedules for a return | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/dependents` | Add a dependent to a return | Taxpayer, Preparer |
| GET | `/tax-returns/{id}/dependents` | List dependents for a return | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/credit-claims` | Claim a tax credit on a return | Taxpayer, Preparer |
| GET | `/tax-returns/{id}/credit-claims` | List credit claims for a return | Taxpayer, Preparer |
| POST | `/estimated-tax-payments` | Record a quarterly estimated tax payment | Taxpayer, Preparer |
| GET | `/estimated-tax-payments/{id}` | Fetch a single estimated tax payment | Taxpayer, Preparer |
| GET | `/estimated-tax-payments` | List estimated tax payments, filterable by return | Taxpayer, Preparer |
| POST | `/tax-returns/{id}/efile` | Transmit the return for e-filing | Taxpayer |
| GET | `/efilings/{id}` | Fetch an e-file submission | Taxpayer, Preparer, IrsGateway |
| GET | `/efilings` | List e-file submissions, filterable by return | Taxpayer, Preparer, IrsGateway |
| POST | `/efilings/{id}/acknowledge` | Record an accept or reject acknowledgement | IrsGateway |
| POST | `/amended-returns` | Create a 1040X amendment draft against a filed return | Taxpayer |
| GET | `/amended-returns/{id}` | Fetch a 1040X amendment | Taxpayer, Preparer |
| GET | `/amended-returns` | List amendments, filterable by original return or taxpayer | Taxpayer, Preparer |
| POST | `/amended-returns/{id}/file` | File the 1040X; compute delta and mark the original amended | Taxpayer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_CHILD` | 409 |
| `ERR_NO_INCOME_DOCUMENTS` | 409 |
| `ERR_ITEMIZED_REQUIRES_SCHEDULE_A` | 409 |
| `ERR_RETURN_NOT_COMPUTED` | 409 |
| `ERR_STALE_RETURN_VERSION` | 412 |
| `ERR_ALREADY_EFILED` | 409 |
| `ERR_ORIGINAL_NOT_FILED` | 409 |
| `ERR_PAYMENT_PERIOD_OVERLAP` | 409 |
| `ERR_CORRECTION_WINDOW_OVERLAP` | 409 |
