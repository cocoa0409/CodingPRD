# Auto Title Loan API — Product Requirements Document

## 1. Introduction

This document specifies the Auto Title Loan API, a regulated lending platform that originates and services short-term loans secured by a borrower's vehicle title. The platform exists to make every step of a title-lending operation defensible under examination: a vehicle is appraised, a maximum loanable principal is derived from a state-specific loan-to-value ceiling, an application is underwritten against that ceiling and the borrower's state APR cap, and — once approved — a loan is disbursed, a lien is filed with the state DMV, and an amortization schedule is generated. From that point the loan is serviced through payments, delinquency assessment, default declaration, and, where necessary, repossession, sale, and charge-off. Borrowers retain the right to cure (reinstate) or to pay in full (redeem) at defined points along the way.

Two characteristics make this domain unusually demanding. First, every monetary and rate decision is governed by a per-state regulatory profile — APR caps, LTV ceilings, rollover limits, term bounds, redemption grace periods, and which appraisal valuation basis applies — so the same vehicle and the same requested loan can be legal in one state and rejected in another. Second, a single loan carries two state dimensions that evolve independently: a payoff dimension (is the debt outstanding, redeemed, paid off, or charged off?) and a delinquency dimension (is the borrower current, delinquent, or in default?). Servicing actions ripple outward through cascading side effects that touch installments, fee balances, title liens, repossession orders, the borrower's standing, and the physical GPS / starter-interrupt device installed on the collateral. The API's job is to keep all of these consistent, auditable, and within the bounds of the controlling state's law.

The remainder of this document defines the system-wide contract (Section 2), the business logic and workflows (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API. The whole service is mounted under the `/atl` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the user's operational capacity. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles, spelled precisely as follows: `ComplianceAdmin`, `Appraiser`, `Underwriter`, `LoanServicer`, `RecoveryManager`, and `TitleClerk`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

All six roles use an opaque user identity. When `X-User-Role` is `ComplianceAdmin`, `Appraiser`, `Underwriter`, `LoanServicer`, `RecoveryManager`, or `TitleClerk`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id` for ownership purposes. The one place `X-User-ID` carries meaning beyond authorization is segregation of duties: the system retains, for each appraisal, the identity of the `Appraiser` who finalized it, and for each application it approves, the identity of the approving `Underwriter`. When an application is approved, the approving `Underwriter`'s `X-User-ID` must differ from the `X-User-ID` of the `Appraiser` who finalized the appraisal backing that application; if they are the same user, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0. A supplied `limit` or `offset` that is non-integer, or a `limit` outside `[1, 100]`, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full (pre-pagination) filtered result set and `has_more` is true exactly when `offset` plus the number of items returned in this page is less than `total_count`.

### 2.4. Common Resource Properties and Identifiers

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is first created. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that begins at 1 and increments by one on every modification of the resource.

One entity is an exception to the `updated_at` / `version` convention: the `RegulatoryProfile` is configuration data and carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. All other entities — `Borrower`, `Vehicle`, `Appraisal`, `LoanApplication`, `Loan`, `TitleLien`, `Installment`, `Payment`, `Renewal`, `RepossessionOrder`, `RepossessionAssignment`, `Device`, and `DeviceCommand` — carry the full set of common fields.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a path that embeds one or more identifiers. When a request supplies any resource identifier — whether in the path or in the body — the system resolves each one to an existing entity, evaluated left-to-right, and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. For a nested path, the outermost (leftmost) identifier is checked before any inner identifier, so a child lookup under a non-existent parent fails on the parent. Existence resolution runs after authentication and authorization but before the request body's field-level and business validations.

### 2.6. Validation Ordering and Precedence

When several checks could apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. The global order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization (`ERR_FORBIDDEN_ROLE`); (3) where applicable, segregation of duties on application approval (`ERR_SEGREGATION_OF_DUTIES`); (4) existence of every referenced identifier (`ERR_NOT_FOUND`); (5) request-body field presence, type, and enum-member validity (`ERR_INVALID_REQUEST`); (6) numeric and interval range checks, evaluated after the field-presence/type check within the same request-validation group (`ERR_VALIDATION_RANGE`); (7) state legality of the requested transition (`ERR_INVALID_STATE`); and then the domain-specific guards described throughout Section 3, in the priority order they are introduced there. Within the request-validation group, a missing-or-mistyped field is reported as `ERR_INVALID_REQUEST` and takes precedence over a range violation; a value that is correctly typed but out of range is reported as `ERR_VALIDATION_RANGE`.

The range checks at step (6) cover: `amount_cents` strictly greater than zero, `requested_principal_cents` strictly greater than zero, `monthly_income_cents` at least zero, `sale_proceeds_cents` at least zero, a recovery assignment's `window_end` strictly after its `window_start`, and a device command's `effective_end` at or after its `effective_start`. These range checks apply to the payment, application-create, borrower-create, recovery-assignment-create, sale, and device-command-create operations. The same `ERR_VALIDATION_RANGE` treatment also enforces, after the field-presence/type check, the numeric constraints stated elsewhere in Section 3 for their own create operations: on regulatory-profile-create, `max_apr_bps` greater than zero, `max_ltv_bps` greater than zero and at most 10000, `max_renewals` at least zero, `min_term_months` at least 1, `max_term_months` at least `min_term_months`, and `redemption_grace_days` at least zero; on application-create, `contract_apr_bps` greater than zero and `term_months` at least 1; on vehicle-create, `odometer_miles` at least zero; on appraisal-create, `trade_in_value_cents` greater than zero and `auction_value_cents` greater than zero and at most `trade_in_value_cents`; and on renewal-create, `new_term_months` at least 1.

### 2.7. Optimistic Concurrency Control

One write in this system is guarded by optimistic concurrency control: creating a renewal against a loan. A renewal-create request must carry an `expected_loan_version` field — it is a required input, not optional — holding the `version` of the target `Loan` that the client last observed. If `expected_loan_version` does not equal the loan's current `version`, the create is rejected with `ERR_STALE_LOAN_VERSION` at HTTP 412. Because a renewal supersedes the loan's prior term and capitalizes outstanding balances into principal, a client whose observed version has been overtaken (by another renewal, or by any cascade that bumped the loan's version) is acting on a stale view and must re-read before retrying. No other endpoint accepts or requires a version field; only the renewal-create write performs this check.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation produces a fractional cent, the rounding rule is specified per calculation in Section 3: appraisal basis valuation and the LTV-derived maximum principal are floored to whole cents; per-installment interest is rounded half up; the percentage term of a late fee is floored before the floor/cap clamp; and all balance arithmetic (payment allocation, redemption, reinstatement, renewal capitalization, and deficiency) is exact integer-cent arithmetic. Basis points are integers throughout. APR and LTV are expressed in basis points where 10000 basis points equals 100 percent (for example, 3600 basis points is an effective APR of 36.00 percent, and 5000 basis points is an LTV ceiling of 50.00 percent).

### 2.9. State Consistency, Cascades, and Versioning on Mutation

This platform's defining behavior is that one action frequently mutates several entities at once. Whenever a transition's side effects touch a related entity, that related entity is itself mutated — its `updated_at` is refreshed and its `version` increments by one — exactly as if it had been modified directly. Cascades can chain several levels deep: declaring default creates a repossession order, and the order's creation in turn issues a starter-disable command to the collateral's device. The precise cascade set for each action is given in Section 3, where each is described with the same level of detail; an implementer must apply the full set, not merely the primary transition.

### 2.10. Time and the Test Clock

All time-gated logic — installment due-date comparison, recovery timestamps, the redemption deadline, payment posting time, and device-command windows — reads a single server-held "current clock time" rather than wall-clock time. A `ComplianceAdmin` may set this clock to a supplied instant via the test-driving clock capability; the supplied value is passed as `to_iso8601` and the response (HTTP 200) echoes the new `current_utc` as an ISO 8601 UTC timestamp with three fractional digits. Before the clock has ever been set, it defaults to real wall-clock UTC time. The audit metadata timestamps `created_at` and `updated_at` (Section 2.4) always use real wall-clock UTC time and are not governed by this server-held clock; only the time-gated logic enumerated above reads it. All due-date and grace comparisons throughout Section 3 are made against this clock.

## 3. Business Logic & Workflows

### 3.1. Regulatory Profiles, Borrowers, and Collateral Vehicles

The regulatory foundation of the platform is the per-state **regulatory profile**, configured by a `ComplianceAdmin`. Each profile governs exactly one US state, identified by `state_code`, which must be unique across profiles (a create whose `state_code` duplicates an existing profile is rejected with `ERR_INVALID_STATE`) and one of `CA`, `TX`, `FL`, `VA`, or `AZ`. A profile fixes the state-mandated maximum effective APR in basis points (`max_apr_bps`, which must be greater than zero); the maximum loan-to-value ratio in basis points (`max_ltv_bps`, which must be greater than zero and at most 10000); the maximum number of rollovers permitted on a single loan (`max_renewals`, at least zero); the permitted loan term window in months (`min_term_months`, at least 1, and `max_term_months`, which must be at least `min_term_months`); the number of days after a vehicle is recovered during which the borrower may still redeem before sale is permitted (`redemption_grace_days`, at least zero); and the `valuation_basis` — one of `TRADE_IN` or `AUCTION` — that selects which appraisal value variant the LTV ceiling is measured against in that state.

A **borrower** is registered by an `Underwriter` or a `ComplianceAdmin` with a contact `email` (required and unique across borrowers; a create with a duplicate `email` is rejected with `ERR_INVALID_STATE`), a legal `full_name`, a two-letter `state_code` of residence that must be one of `CA`, `TX`, `FL`, `VA`, or `AZ` and which selects the borrower's applicable regulatory profile, and a declared gross `monthly_income_cents` (at least zero) used for ability-to-repay review. A borrower's lifecycle `status` begins at `ACTIVE` and may become `BARRED`; barring is system-driven and is described under charge-off in Section 3.7.

A **vehicle** is registered as collateral by an `Appraiser` or an `Underwriter` against an existing borrower. The request supplies the owning `borrower_id`, a `vin` (required and unique across vehicles; a create with a duplicate `vin` is rejected with `ERR_INVALID_STATE`), the `year`, `make`, and `model`, and the current `odometer_miles` (at least zero). Each vehicle tracks a `lien_state` of either `CLEAR` or `ENCUMBERED`; it begins `CLEAR` and is advanced by lien filing and release, as described in Sections 3.4 and 3.7. The vehicles owned by a borrower can be listed by reverse reference from the borrower.

### 3.2. Appraisal: Valuation, Haircut, and the LTV Ceiling

Before any money can be lent, the pledged vehicle must be valued. An `Appraiser` creates an **appraisal** in `DRAFT` status against a `vehicle_id`, supplying two valuations and a condition grade: the clean retail / trade-in valuation `trade_in_value_cents` (the optimistic, higher basis, which must be greater than zero) and the forced-sale `auction_value_cents` (the pessimistic, lower basis, which must be greater than zero and at most `trade_in_value_cents`). The appraiser also records a `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`. An appraisal's lifecycle `status` moves through `DRAFT`, `FINALIZED`, and the terminal `CONSUMED`. Appraisals for a vehicle can be listed by reverse reference from the vehicle.

Finalizing an appraisal is performed by an `Appraiser` and is permitted only when the appraisal is in `DRAFT`; an attempt to finalize an appraisal not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Finalization advances the appraisal `DRAFT → FINALIZED`, increments its `version`, and computes two derived figures that are then exposed on the appraisal.

The first computed figure is `basis_value_cents`, the post-haircut valuation. The system first selects the raw valuation according to the borrower's state valuation basis: if that state's profile names `TRADE_IN`, the raw value is `trade_in_value_cents`; if it names `AUCTION`, the raw value is `auction_value_cents`. (The borrower for this purpose is resolved through the vehicle's owner.) The borrower's state must have a configured regulatory profile for the basis and LTV to be resolved; if no profile exists for that state, finalization is rejected with `ERR_INVALID_STATE` (the same rejection applies wherever else the borrower-state profile is required — application submission, application approval, and renewal — when no profile is configured for the borrower's state). It then applies a condition haircut expressed in basis points: a grade of `EXCELLENT` applies a haircut of 0 basis points, `GOOD` applies 500 basis points, `FAIR` applies 1500 basis points, and `POOR` applies 3000 basis points. The basis value is the raw value multiplied by the quantity (10000 minus the haircut basis points), divided by 10000, with the result floored to whole cents. Because the two states differ only in which raw value they select, a `TRADE_IN` state yields a larger basis — and therefore a larger LTV ceiling — than an `AUCTION` state would for the identical vehicle and condition, while an `AUCTION` state yields the smaller basis from the lower auction value.

The second computed figure, produced immediately after the basis value, is `max_principal_cents`, the maximum loanable principal. It is the basis value multiplied by the borrower-state `max_ltv_bps`, divided by 10000, with the result floored to whole cents. This figure is the LTV ceiling that underwriting enforces against the requested principal.

### 3.3. Application Submission and Underwriting

An `Underwriter` submits a **loan application** against a borrower and a finalized appraisal. The submission carries the `borrower_id`, the `appraisal_id`, the `requested_principal_cents` (greater than zero), the lender's offered annual percentage rate `contract_apr_bps` (greater than zero), and the requested `term_months` (at least 1). An application's `status` begins at `SUBMITTED` and is terminal at either `APPROVED` or `REJECTED`. Applications can be listed and filtered by `borrower_id` or `appraisal_id`.

At submission the system computes and stores the application's `effective_apr_bps` as the lesser of `contract_apr_bps` and the borrower-state `max_apr_bps`. This cap-and-store is separate from the regulatory gate: the APR cap gate fires when `contract_apr_bps` is strictly greater than the borrower-state `max_apr_bps` — a contract rate exactly equal to the cap is allowed — and a violation is rejected with `ERR_APR_CAP_EXCEEDED`. The same submission also enforces that the requested term lies within the borrower state's permitted window, that is, `term_months` is at least `min_term_months` and at most `max_term_months`; a term outside that window is rejected with `ERR_TERM_OUT_OF_BOUNDS`. It further enforces that `requested_principal_cents` does not exceed the appraisal's `max_principal_cents` — a requested principal exactly equal to the ceiling is allowed, and only a requested principal strictly greater than the ceiling is rejected, with `ERR_LTV_EXCEEDED`. Submission does not require the appraisal to be `FINALIZED` (that requirement is enforced only at approval); however, an appraisal that has not been finalized has no computed `max_principal_cents`, so any positive `requested_principal_cents` is treated as exceeding the (absent) ceiling and the submission is rejected with `ERR_LTV_EXCEEDED` once the APR-cap and term-bounds gates have passed. The APR-cap, term-bounds, and LTV gates are all checked at submission and re-verified at approval, with the APR-cap gate evaluated first, then the term-bounds gate, then the LTV gate.

Approval is performed by an `Underwriter` and is permitted only while the application is `SUBMITTED`. Beyond segregation of duties (Section 2.1), approval requires that the referenced appraisal is in `FINALIZED` status, that the requested principal still satisfies the LTV ceiling, that the effective APR still satisfies the borrower-state cap, that the term still lies within the state window, and that the borrower's `status` is `ACTIVE`. The borrower-eligibility check is evaluated before the APR, term, and LTV gates among the business-safety checks; a `BARRED` borrower is rejected with `ERR_BORROWER_BARRED`. A request to approve an application that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

A successful approval is a cascade. The application advances `SUBMITTED → APPROVED` and its `version` increments. The backing appraisal transitions `FINALIZED → CONSUMED` (locking it from reuse by any other application) and its `version` increments. A new **loan** is created with `payoff_status` of `OUTSTANDING` and `delinquency_status` of `CURRENT`, whose `original_principal_cents` equals the application's `requested_principal_cents`. A **title lien** is created in `PENDING` for the new loan. An **installment** schedule is generated as described in Section 3.5. The collateral vehicle's `lien_state` is set to `ENCUMBERED`. Rejecting an application instead is performed by an `Underwriter` while the application is `SUBMITTED`: it advances `SUBMITTED → REJECTED`, increments the application's `version`, creates no loan, and leaves the appraisal `FINALIZED` and reusable.

### 3.4. Loan Origination Outputs: The Loan, the Lien, and Title Filing

The originated **loan** copies several fields from the application that produced it: `application_id` references the originating application, while `borrower_id` and `vehicle_id` are copied (the vehicle being taken from the appraisal on the application), the disbursed `original_principal_cents` is set at origination and is immutable thereafter, the capped `effective_apr_bps` is copied and is immutable, and `term_months` is the current contractual term (which a renewal may later reset). The loan tracks three running balances: the outstanding `principal_balance_cents`, the accrued-and-unpaid `accrued_interest_cents`, and the unpaid `fees_balance_cents` (late fees and repossession fees). It also tracks a `renewal_count` that begins at 0. The loan's two state dimensions evolve independently: `payoff_status` is one of `OUTSTANDING`, `REDEEMED`, `PAID_OFF`, or `CHARGED_OFF` and begins `OUTSTANDING`; `delinquency_status` is one of `CURRENT`, `DELINQUENT`, or `DEFAULT` and begins `CURRENT`. Loans can be fetched individually and listed with filters by `application_id`, `borrower_id`, or `vehicle_id`.

The **title lien** created at origination secures the loan. It references its `loan_id`, mirrors the encumbered collateral's identifier in a read-only `vehicle_id` copied from the loan at filing, and carries a `status` of `PENDING`, `FILED`, or the terminal `RELEASED`. A `TitleClerk` files the lien with the state DMV, supplying the required `dmv_reference` filing number. Filing advances the lien `PENDING → FILED` and increments its `version`; it is permitted only when the lien is `PENDING`, when the `dmv_reference` is supplied, and when the secured loan's `payoff_status` is `OUTSTANDING`. A filing attempt on a lien that is not `PENDING` is rejected with `ERR_INVALID_STATE`, and a filing attempt while the loan's `payoff_status` is anything other than `OUTSTANDING` is rejected with `ERR_LIEN_LOAN_NOT_OUTSTANDING`. Lien release is never requested directly; it is a system cascade triggered by payoff, redemption, or charge-off, described in Section 3.7. Liens can be fetched individually and listed by reverse reference from a loan.

### 3.5. The Amortization Schedule

When a loan is originated, the system generates its complete **installment** schedule. Each installment belongs to its loan via `loan_id`, carries a 1-based `sequence_no` that is unique within the loan, a `due_date` (an ISO 8601 UTC datetime), a scheduled `principal_due_cents`, a scheduled `interest_due_cents`, a `late_fee_cents` that is assessed only when the installment goes past due (see Section 3.6), and a `status` of `SCHEDULED`, `PAID`, `PAST_DUE`, or `WAIVED`, beginning at `SCHEDULED`. The first installment's due date is 30 days after origination, and each subsequent installment is due 30 days after the previous one. A loan's schedule can be listed by reverse reference from the loan.

The schedule is a standard amortizing schedule computed in a pinned order. Let the principal be the loan's `original_principal_cents`, the annual rate be `effective_apr_bps` divided by 10000, and the term be `term_months`. The monthly rate is that annual rate divided by 12. The level payment is the principal multiplied by the monthly rate, divided by the quantity (1 minus (1 plus the monthly rate) raised to the power of the negative term); this level payment is kept unrounded for use below. The schedule is then built installment by installment from a running balance that starts at the full principal. For each installment in sequence: the interest portion `interest_due_cents` is the running balance multiplied by the monthly rate, rounded half up to whole cents (interest is rounded per installment, before being summed anywhere). For every installment except the last, the principal portion `principal_due_cents` is the level payment rounded half up to whole cents, minus that installment's interest portion. For the final installment, the principal portion is set to the entire remaining running balance, so the final installment absorbs all rounding residue and the sum of every installment's principal equals the original principal exactly. After each installment, the running balance is reduced by that installment's principal portion.

### 3.6. Servicing: Payments, Delinquency, and the Starter-Interrupt Device

A loan in good standing is serviced by a `LoanServicer`, who posts payments, assesses delinquency, declares default, renews the loan, and manages the collateral's device.

**Payments.** A **payment** is posted against a `loan_id` with a gross `amount_cents` (greater than zero) and a `payment_type` of `REGULAR`, `REINSTATEMENT`, or `REDEMPTION`. The payment records a system `posted_at` timestamp (set to the current clock time of Section 2.10) and, after allocation, the portions applied: `principal_applied_cents`, `interest_applied_cents`, `fees_applied_cents`, and any `overpayment_cents`. A loan's payments can be listed by reverse reference from the loan. A `REGULAR` payment is allocated by a fixed waterfall in this order: fees first, then accrued interest, then principal, then overpayment. Concretely, working from a remaining amount that starts at `amount_cents`: the fees applied are the lesser of the remaining amount and `fees_balance_cents`, and the remaining amount is reduced by that; the interest applied is the lesser of the new remaining amount and `accrued_interest_cents`, and the remaining amount is reduced by that; the principal applied is the lesser of the new remaining amount and `principal_balance_cents`, and the remaining amount is reduced by that; whatever remains is the overpayment, refunded to the borrower. The loan's `fees_balance_cents`, `accrued_interest_cents`, and `principal_balance_cents` are each reduced by the corresponding applied amount. This arithmetic is exact integer cents. The semantics of `REINSTATEMENT` and `REDEMPTION` payments — and the sufficiency rule that protects them — are given in Section 3.7.

**Assessing delinquency.** A `LoanServicer` assesses delinquency on a loan, advancing `delinquency_status` from `CURRENT` to `DELINQUENT`. This is permitted only when the loan's `delinquency_status` is `CURRENT`, its `payoff_status` is `OUTSTANDING`, and at least one installment with `status` of `SCHEDULED` has a `due_date` earlier than the current clock time; if nothing is past due there is nothing to assess and the request is rejected with `ERR_INVALID_STATE`. The assessment flips every `SCHEDULED` installment whose `due_date` is earlier than the current clock time to `PAST_DUE`. It accrues interest by adding to `accrued_interest_cents` the sum of `interest_due_cents` over exactly those newly past-due installments. It assesses a late fee on each newly past-due installment and adds the total of those late fees to `fees_balance_cents`. The late fee for a single installment is computed as follows: take the installment's `principal_due_cents` multiplied by 500 basis points, divided by 10000, floored to whole cents; raise that to a floor of 1500 cents if it is lower; then cap it at 5000 cents if it is higher. In other words, the per-installment fee is the greater of 1500 cents and the floored percentage term, but never more than 5000 cents. The total assessed is the sum of the per-installment fee over all newly past-due installments. The assessment also cascades to the device, as described below, and increments the loan's `version`.

**The device and its commands.** A `LoanServicer` may register a GPS / starter-interrupt **device** on a vehicle. The device references its `vehicle_id` (which must be unique across devices) and a hardware `serial_number` (required and unique); a registration whose `vehicle_id` or `serial_number` duplicates an existing device is rejected with `ERR_INVALID_STATE`. It carries a `starter_state` of `ENABLED` or `DISABLED`, beginning `ENABLED`, and an `active_disable_count` that begins at 0 and represents the net number of unreversed disable commands; this count is an invariant target that must return to 0 when a loan is reinstated or redeemed. Devices on a vehicle can be listed by reverse reference from the vehicle. A **device command** is issued against a `device_id` with a `command_type` of `STARTER_DISABLE`, `STARTER_ENABLE`, or `LOCATE`, and an effective window bounded by `effective_start` (inclusive) and `effective_end` (inclusive), where `effective_end` must be at or after `effective_start`. A command's `status` is `ISSUED` or `REVERSED`, beginning `ISSUED`. A device's commands can be listed by reverse reference from the device.

When a `LoanServicer` issues a command through the public device-command capability, the command is gated. A `STARTER_DISABLE` command requires that the device's `starter_state` is `ENABLED`, that the vehicle's active loan — the single loan whose `vehicle_id` matches the device's `vehicle_id` and whose `payoff_status` is `OUTSTANDING` — exists and has a `delinquency_status` of either `DELINQUENT` or `DEFAULT` (otherwise rejected with `ERR_DEVICE_LOAN_NOT_DELINQUENT`, including the case where no such active loan exists for the device's vehicle), and that the requested closed window from `effective_start` to `effective_end` does not overlap any existing `ISSUED` `STARTER_DISABLE` window on the same device. Window overlap is evaluated on closed intervals, so two windows that merely touch at an endpoint count as overlapping; a collision is rejected with `ERR_COMMAND_WINDOW_OVERLAP`. A successful public `STARTER_DISABLE` advances the device `ENABLED → DISABLED`, increases `active_disable_count` by 1, and increments the device's `version`. A `STARTER_ENABLE` command is permitted only when the device's `starter_state` is `DISABLED`; it advances `DISABLED → ENABLED`, decreases `active_disable_count` by 1 (never below 0), and increments the device's `version`. The delinquency guard and the window-overlap guard apply only to public `STARTER_DISABLE` commands; `STARTER_ENABLE` and `LOCATE` are exempt from both.

The starter device is also driven by system cascades, and those cascades behave differently from public commands. When delinquency assessment occurs, if a device exists on the vehicle the system issues a `STARTER_DISABLE` command (in `ISSUED` status) with `effective_start` and `effective_end` both set to the current clock time (a zero-length window), sets the device's `starter_state` to `DISABLED`, and increases `active_disable_count` by 1; if no device is installed, no command is issued and the assessment still succeeds. These cascade-issued commands bypass the public-endpoint preconditions and are not subject to the window-overlap check, so a cascade always succeeds and applies its effect idempotently even if the device is already `DISABLED`. A prior `STARTER_DISABLE` command record remains `ISSUED` and continues to count toward the window-overlap check applied to future public commands.

### 3.7. Default, Cure, Redemption, and Payoff

The delinquency and payoff dimensions of a loan converge in this section, which covers default declaration, the two cure paths (reinstatement), the payoff paths (regular payoff and redemption), and the read-only quote that exposes the cure and payoff amounts in advance.

**Declaring default.** A `LoanServicer` declares default on a loan, advancing `delinquency_status` from `DELINQUENT` to `DEFAULT`. This is permitted only when the loan's `delinquency_status` is `DELINQUENT` and its `payoff_status` is `OUTSTANDING`; otherwise the request is rejected with `ERR_INVALID_STATE`. Declaring default creates a **repossession order** in `ORDERED` status as a cascade, and that order's creation itself issues a `STARTER_DISABLE` command to the collateral's device when one exists — a depth-three chain (default → order → device command) — with `effective_start` and `effective_end` both at the current clock time, the device's `starter_state` set to `DISABLED`, and `active_disable_count` increased by 1. The loan's `version` increments.

**Reinstatement (curing arrears).** A `REINSTATEMENT` payment cures past-due arrears and restores the loan's delinquency dimension to `CURRENT`. It is permitted only when the loan's `delinquency_status` is `DELINQUENT` or `DEFAULT`; a `REINSTATEMENT` payment against a `CURRENT` loan is rejected with `ERR_INVALID_STATE`. The reinstatement amount is the cure amount only: the sum of past-due principal (the sum of `principal_due_cents` over installments whose `status` is `PAST_DUE`), past-due interest (the sum of `interest_due_cents` over those same `PAST_DUE` installments), the current `fees_balance_cents`, and — only when the loan's `delinquency_status` is `DEFAULT` — a flat repossession recovery fee of 25000 cents. It deliberately excludes principal that is not yet due. A `REINSTATEMENT` payment must fully cover this computed reinstatement amount; a payment that does not cover it in full is rejected with `ERR_INSUFFICIENT_PAYMENT` (no partial cures). When a `DELINQUENT` loan is reinstated, the system reduces `principal_balance_cents` by the past-due principal, reduces `accrued_interest_cents` by the past-due interest, sets `fees_balance_cents` to 0 (the cure exactly retires arrears and fees, and there is no repossession fee while merely `DELINQUENT`), sets all `PAST_DUE` installments to `PAID`, and advances `delinquency_status` `DELINQUENT → CURRENT`. If a device exists, a `STARTER_ENABLE` command is issued (in `ISSUED` status) with `effective_start` and `effective_end` at the current clock time, the device's `starter_state` set to `ENABLED`, and `active_disable_count` decreased by 1 (never below 0), compensating the prior disable; the prior `STARTER_DISABLE` record stays `ISSUED` and still counts toward window-overlap checks. On the resulting payment record (for both the `DELINQUENT` and `DEFAULT` cures), `principal_applied_cents` is the past-due principal, `interest_applied_cents` is the past-due interest, `fees_applied_cents` is the remainder of the computed reinstatement amount (the pre-cure `fees_balance_cents` plus, in the `DEFAULT` case, the 25000-cent repossession recovery fee), and `overpayment_cents` is the paid `amount_cents` minus the computed reinstatement amount. The loan's `version` increments.

When a `DEFAULT` loan is reinstated, the same cure runs, but with the repossession dimension unwound: it reduces `principal_balance_cents` by the past-due principal and `accrued_interest_cents` by the past-due interest, sets `fees_balance_cents` to 0 (the cure retires arrears, fees, and the repossession recovery), transitions any active repossession order in `ORDERED`, `ASSIGNED`, or `RECOVERED` status to `CANCELLED` as a cascade (no active order is required to exist, and if none does the cancellation cascade is a no-op), sets all `PAST_DUE` installments to `PAID`, advances `delinquency_status` `DEFAULT → CURRENT`, and issues a `STARTER_ENABLE` command that sets the device's `starter_state` to `ENABLED` and resets `active_disable_count` to 0. The loan's `version` increments.

**Regular payoff.** When a `REGULAR` payment's waterfall allocation (Section 3.6) drives the loan's `principal_balance_cents`, `accrued_interest_cents`, and `fees_balance_cents` all to zero, the loan's payoff dimension advances `OUTSTANDING → PAID_OFF` as a system transition. This payoff cascades: the title lien transitions `FILED → RELEASED`, which in turn sets the collateral vehicle's `lien_state` to `CLEAR` (a depth-two chain), and every remaining `SCHEDULED` installment is set to `WAIVED`. The lien-release cascade fires only for a lien currently in `FILED`; a lien still in `PENDING` (never filed) is left unchanged and the vehicle's `lien_state` is not cleared by it. The loan's `version` increments.

**Redemption (full payoff to reclaim the vehicle).** A `REDEMPTION` payment pays the full redemption amount and advances the loan's payoff dimension `OUTSTANDING → REDEEMED`. It is permitted only when the loan's `payoff_status` is `OUTSTANDING`; a `REDEMPTION` payment against a loan whose `payoff_status` is not `OUTSTANDING` is rejected with `ERR_INVALID_STATE`. The redemption amount is everything owed plus repossession cost recovery when a repossession has been opened: the sum of `principal_balance_cents`, `accrued_interest_cents`, and `fees_balance_cents`, plus a flat 25000-cent repossession recovery fee when the loan has a repossession order in `ORDERED`, `ASSIGNED`, or `RECOVERED` status (and excluding that fee when no active repossession order exists). A `REDEMPTION` payment must fully cover this computed redemption amount; a payment that does not cover it in full is rejected with `ERR_INSUFFICIENT_PAYMENT`. Redemption cascades: the title lien transitions `FILED → RELEASED` and the vehicle's `lien_state` is set to `CLEAR`, any active repossession order transitions to `CANCELLED`, and (when a device exists) a `STARTER_ENABLE` command is issued that sets the device's `starter_state` to `ENABLED` and resets the device's `active_disable_count` to 0. On the resulting payment record, `principal_applied_cents` is the pre-payment `principal_balance_cents`, `interest_applied_cents` is the pre-payment `accrued_interest_cents`, `fees_applied_cents` is the pre-payment `fees_balance_cents` plus the repossession recovery fee component included in the redemption amount, and `overpayment_cents` is the paid `amount_cents` minus the computed redemption amount; all three balances are then set to 0. The loan's `version` increments.

**The payoff quote.** A `LoanServicer`, `Underwriter`, or `ComplianceAdmin` may read a loan's computed `redemption_amount_cents` and `reinstatement_amount_cents` together through the read-only payoff-quote capability, which applies the same redemption and reinstatement formulas described above without mutating anything.

### 3.8. Renewal: Rollover and Capitalization

A `LoanServicer` rolls a loan over by creating a **renewal**, which extends the term and capitalizes outstanding balances into principal. The renewal request carries the `loan_id`, the required `expected_loan_version` (the OCC guard described in Section 2.7), and the `new_term_months` (at least 1) that supersedes the loan's prior term. The renewal records two computed amounts and a system ordinal: `rolled_fees_cents`, `new_principal_cents`, and `renewal_index` (the 1-based ordinal of this renewal on the loan, which equals the loan's `renewal_count` after the renewal). A loan's renewals can be listed by reverse reference from the loan.

Renewal is guarded in a specific order. The loan must be in a renewable state: its `payoff_status` must be `OUTSTANDING`, because a `REDEEMED`, `PAID_OFF`, or `CHARGED_OFF` loan cannot be renewed; a non-renewable state is rejected with `ERR_INVALID_STATE`. The `expected_loan_version` must equal the loan's current `version`, or the create is rejected with `ERR_STALE_LOAN_VERSION` at HTTP 412. The rollover limit must not be reached: a renewal is barred once the loan's `renewal_count` is at or above the borrower-state `max_renewals`, in which case the create is rejected with `ERR_RENEWAL_LIMIT_REACHED`.

On a successful renewal the capitalization runs in exact integer cents: `rolled_fees_cents` is the sum of the loan's current `accrued_interest_cents` and `fees_balance_cents`; `new_principal_cents` is the loan's current `principal_balance_cents` plus `rolled_fees_cents`. The loan is then updated so that `principal_balance_cents` becomes `new_principal_cents`, `accrued_interest_cents` becomes 0, `fees_balance_cents` becomes 0, `term_months` becomes `new_term_months`, and `renewal_count` increases by 1. The loan's `version` increments.

### 3.9. Repossession: Assignment, Recovery, Sale, and Charge-Off

A defaulted loan's collateral is recovered and disposed of by a `RecoveryManager` through the **repossession order** opened when default was declared (Section 3.7). A repossession order may also be opened directly by a `RecoveryManager` against a loan: the order references its `loan_id`, mirrors the collateral's identifier in a read-only `vehicle_id` copied from the loan at order creation, and carries a `status` of `ORDERED`, `ASSIGNED`, `RECOVERED`, the terminal `SOLD`, or the terminal `CANCELLED`. A direct open is rejected with `ERR_LOAN_NOT_IN_DEFAULT` if the referenced loan's `delinquency_status` is not `DEFAULT`, and rejected with `ERR_ACTIVE_REPO_EXISTS` if a non-terminal repossession order already exists for the loan; a successful direct open creates the order in `ORDERED` and issues a `STARTER_DISABLE` command to the vehicle's device. Across the assign, recover, and (for the directly-opened path) order-creation actions, the referenced loan's `delinquency_status` must be `DEFAULT`, or the action is rejected with `ERR_LOAN_NOT_IN_DEFAULT`. Repossession orders can be fetched individually and listed by reverse reference from a loan.

Before a recovery agent can act, a `RecoveryManager` attaches a **repossession assignment** — a field-agent recovery window — to an order. The assignment references its `repossession_order_id`, an `agent_name`, and a half-open recovery window bounded by `window_start` (inclusive) and `window_end` (exclusive), where `window_end` must be strictly after `window_start`. An assignment window must not overlap another assignment window on the same order; because the interval is half-open, two windows that merely touch at an endpoint are allowed (the adjacency does not count as overlap), but any true overlap is rejected with `ERR_ASSIGNMENT_WINDOW_OVERLAP`. Assignments on an order can be listed by reverse reference from the order.

The order then advances through its lifecycle. A `RecoveryManager` assigns the order, advancing `ORDERED → ASSIGNED`; this requires the order to be `ORDERED` (otherwise `ERR_INVALID_STATE`), then the loan to be in `DEFAULT` (otherwise `ERR_LOAN_NOT_IN_DEFAULT`), and then at least one assignment to exist for the order (otherwise `ERR_INVALID_STATE`), and it increments the order's `version`. A `RecoveryManager` records recovery, advancing `ASSIGNED → RECOVERED`; this requires the order to be `ASSIGNED` and the loan to be in `DEFAULT`, sets `recovered_at` to the current clock time, sets the `redemption_deadline` to `recovered_at` plus the borrower-state `redemption_grace_days` days, and increments the order's `version`. Finally a `RecoveryManager` sells the recovered collateral, advancing `RECOVERED → SOLD`; this requires the order to be `RECOVERED`, the supplied `sale_proceeds_cents` (gross auction proceeds, at least zero), and the current clock time to be at or after the `redemption_deadline` (the redemption grace must have elapsed; a sale attempted before the deadline is rejected with `ERR_REDEMPTION_GRACE_ACTIVE`). The sale computes the order's `deficiency_cents`, increments the order's `version`, and cascades the loan to charge-off as described below. An attempt to advance an order from a state out of which the requested transition is not defined is rejected with `ERR_INVALID_STATE`. Separately, when a redemption or reinstatement intervenes, an order in `ORDERED`, `ASSIGNED`, or `RECOVERED` is transitioned to `CANCELLED` as a system cascade, with no deficiency recorded and the collateral returned; the order's `version` increments.

The deficiency on sale is computed in exact integer cents and floored at zero. The total owed is the sum of the loan's `principal_balance_cents`, `accrued_interest_cents`, and `fees_balance_cents`, plus the flat 25000-cent repossession recovery fee. The net proceeds are the supplied `sale_proceeds_cents` minus a fixed sale cost of 30000 cents, floored at zero. The `deficiency_cents` is the total owed minus the net proceeds, floored at zero; any surplus (net proceeds exceeding the total owed) is returned to the borrower rather than recorded as a negative deficiency.

Selling the collateral charges off the loan: the loan's payoff dimension advances `OUTSTANDING → CHARGED_OFF` as a cascade. This records the `deficiency_cents` on the order, transitions the title lien `FILED → RELEASED` and sets the vehicle's `lien_state` to `CLEAR`, and sets the originating borrower's `status` to `BARRED` — a borrower whose collateral was sold at a charge-off is barred from having any new application approved, which is the eligibility gate enforced in Section 3.3. The loan's `version` increments.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including the action endpoints that drive state transitions and the test clock — return `200 OK`. All endpoints are mounted under the `/atl` prefix except the test-driving clock.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/atl/regulatory-profiles` | Create a state regulatory profile | ComplianceAdmin |
| GET | `/atl/regulatory-profiles` | List regulatory profiles, optionally filtered by `state_code` | ComplianceAdmin, Underwriter, Appraiser, LoanServicer, RecoveryManager, TitleClerk |
| POST | `/atl/borrowers` | Register a borrower | Underwriter, ComplianceAdmin |
| GET | `/atl/borrowers/{id}` | Fetch a borrower | Underwriter, ComplianceAdmin, LoanServicer, Appraiser |
| GET | `/atl/borrowers/{id}/vehicles` | List vehicles owned by a borrower | Underwriter, ComplianceAdmin, Appraiser, LoanServicer |
| POST | `/atl/vehicles` | Register a collateral vehicle for a borrower | Appraiser, Underwriter |
| GET | `/atl/vehicles/{id}` | Fetch a vehicle | Appraiser, Underwriter, LoanServicer, RecoveryManager, TitleClerk |
| GET | `/atl/vehicles/{id}/appraisals` | List appraisals for a vehicle | Appraiser, Underwriter |
| GET | `/atl/vehicles/{id}/devices` | List devices installed on a vehicle | LoanServicer, RecoveryManager, Appraiser |
| POST | `/atl/appraisals` | Create a DRAFT appraisal | Appraiser |
| GET | `/atl/appraisals/{id}` | Fetch an appraisal including computed values | Appraiser, Underwriter |
| POST | `/atl/appraisals/{id}/finalize` | Finalize a DRAFT appraisal | Appraiser |
| POST | `/atl/applications` | Submit a loan application against a finalized appraisal | Underwriter |
| GET | `/atl/applications` | List applications, optionally filtered by `borrower_id` or `appraisal_id` | Underwriter, ComplianceAdmin |
| GET | `/atl/applications/{id}` | Fetch an application | Underwriter, ComplianceAdmin |
| POST | `/atl/applications/{id}/approve` | Approve a submitted application; originates loan, lien, schedule | Underwriter |
| POST | `/atl/applications/{id}/reject` | Reject a submitted application | Underwriter |
| GET | `/atl/loans/{id}` | Fetch a loan with balances and both state dimensions | Underwriter, ComplianceAdmin, LoanServicer, RecoveryManager, TitleClerk |
| GET | `/atl/loans` | List loans, optionally filtered by `application_id`, `borrower_id`, or `vehicle_id` | Underwriter, ComplianceAdmin, LoanServicer, RecoveryManager, TitleClerk |
| GET | `/atl/loans/{id}/installments` | List a loan's amortization schedule | Underwriter, ComplianceAdmin, LoanServicer |
| GET | `/atl/loans/{id}/payoff-quote` | Read computed redemption and reinstatement amounts | LoanServicer, Underwriter, ComplianceAdmin |
| POST | `/atl/loans/{id}/assess-delinquency` | Assess delinquency: flip past-due installments, charge late fees, disable starter | LoanServicer |
| POST | `/atl/loans/{id}/declare-default` | Declare default, opening a repossession order | LoanServicer |
| POST | `/atl/loans/{id}/payments` | Post a payment (REGULAR / REINSTATEMENT / REDEMPTION) | LoanServicer |
| POST | `/atl/loans/{id}/renewals` | Roll over / renew a loan (OCC-guarded) | LoanServicer |
| GET | `/atl/loans/{id}/renewals` | List a loan's renewals | LoanServicer, ComplianceAdmin |
| GET | `/atl/loans/{id}/payments` | List a loan's payments | LoanServicer, ComplianceAdmin, Underwriter |
| GET | `/atl/title-liens/{id}` | Fetch a title lien | TitleClerk, Underwriter, ComplianceAdmin, LoanServicer |
| GET | `/atl/loans/{id}/title-liens` | List title liens for a loan | TitleClerk, Underwriter, ComplianceAdmin, LoanServicer |
| POST | `/atl/title-liens/{id}/file` | File the lien with the DMV | TitleClerk |
| POST | `/atl/repossession-orders` | Open a repossession order against a defaulted loan | RecoveryManager |
| GET | `/atl/repossession-orders/{id}` | Fetch a repossession order | RecoveryManager, LoanServicer, ComplianceAdmin |
| GET | `/atl/loans/{id}/repossession-orders` | List repossession orders for a loan | RecoveryManager, LoanServicer, ComplianceAdmin |
| POST | `/atl/repossession-orders/{id}/assignments` | Attach a field-agent recovery window | RecoveryManager |
| GET | `/atl/repossession-orders/{id}/assignments` | List assignments for a repossession order | RecoveryManager, ComplianceAdmin |
| POST | `/atl/repossession-orders/{id}/assign` | Advance a repossession order to ASSIGNED | RecoveryManager |
| POST | `/atl/repossession-orders/{id}/recover` | Record physical recovery | RecoveryManager |
| POST | `/atl/repossession-orders/{id}/sell` | Sell recovered collateral after grace elapses | RecoveryManager |
| POST | `/atl/devices` | Register a GPS / starter-interrupt device on a vehicle | LoanServicer |
| GET | `/atl/devices/{id}` | Fetch a device with starter state and disable count | LoanServicer, RecoveryManager, ComplianceAdmin |
| POST | `/atl/devices/{id}/commands` | Issue a device command within an effective window | LoanServicer |
| GET | `/atl/devices/{id}/commands` | List commands issued to a device | LoanServicer, RecoveryManager, ComplianceAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's current UTC clock | ComplianceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_LOAN_VERSION` | 412 |
| `ERR_LOAN_NOT_IN_DEFAULT` | 409 |
| `ERR_LIEN_LOAN_NOT_OUTSTANDING` | 409 |
| `ERR_DEVICE_LOAN_NOT_DELINQUENT` | 409 |
| `ERR_APR_CAP_EXCEEDED` | 422 |
| `ERR_TERM_OUT_OF_BOUNDS` | 422 |
| `ERR_RENEWAL_LIMIT_REACHED` | 409 |
| `ERR_REDEMPTION_GRACE_ACTIVE` | 409 |
| `ERR_COMMAND_WINDOW_OVERLAP` | 409 |
| `ERR_ASSIGNMENT_WINDOW_OVERLAP` | 409 |
| `ERR_LTV_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_PAYMENT` | 422 |
| `ERR_ACTIVE_REPO_EXISTS` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_BORROWER_BARRED` | 403 |
