# Reverse Mortgage HECM Servicing API — Product Requirements Document

## 1. Introduction

A Home Equity Conversion Mortgage (HECM) is the FHA-insured reverse mortgage that lets homeowners aged sixty-two and older convert part of their home equity into loan proceeds without monthly principal-and-interest payments. Unlike a forward mortgage, a HECM grows rather than shrinks over time: interest and mortgage-insurance premium (MIP) compound onto the balance month after month, and the borrower's obligation is settled only when a maturity event — death, permanent vacancy, sale, or an uncured property-charge default — renders the loan due and payable. This service implements the servicing back office for such a portfolio: a system that originates HECM loans against HUD's principal-limit-factor (PLF) tables, governs the draw lifecycle for each draw type, accrues balance growth on a regulated schedule, enforces the annual occupancy certification, administers life-expectancy property-charge set-asides (LESA), and drives the regulated due-and-payable, deferral, and resolution machinery that closes out a loan under the FHA non-recourse guarantee.

The product exists because HECM servicing is unforgiving in its sequencing and its arithmetic. A loan cannot be drawn against once it has matured; a non-borrowing spouse may defer due-and-payable status only after a borrower's death and only when HUD's eligibility conditions are met; a property charge may be paid from a set-aside only while that pool retains funds; and every cent of balance movement must reconcile against an append-only ledger so that a HUD auditor can re-derive the outstanding balance at any time. The system models a simulated clock per lender so that anniversaries, certification due dates, and accrual periods can be advanced deterministically for testing and automation. Throughout, monetary quantities are held in integer cents and computed under pinned rounding rules, because the difference between rounding each accrual period and rounding a single projected figure is itself a legally meaningful distinction between a posted balance and a forward-looking payoff quote.

This document specifies the complete HTTP contract, the cross-cutting principles that govern every resource, and the business workflows that tie the entities together. Section 2 fixes the global contract — authentication, the response envelope, pagination, and the system-wide invariants. Section 3 narrates the business logic: origination, the draw and accrual lifecycle, occupancy and property-charge administration, and the maturity-to-resolution disposition path. Sections 4 and 5 summarize the endpoints and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing. Once the headers are validated, the system checks that the caller's role is permitted to invoke the requested endpoint; a recognized role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `ServicerOps`, `ComplianceOfficer`, `Borrower`, `HudAuditor`, and `System`.

- `ServicerOps` is the loan-servicing back office. It creates lenders, principal-limit-factor rows, borrowers, and loans; originates loans; posts accrual; manages the disbursement lifecycle; creates and reverses property-charge payments; and opens occupancy certifications. When `X-User-Role` is `ServicerOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `ComplianceOfficer` handles HUD/FHA compliance decisions: recording and acknowledging maturity events, opening and terminating non-borrowing-spouse deferrals, and driving resolutions. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Borrower` is the loan borrower acting in self-service: requesting draws and self-certifying occupancy. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`; ownership checks on any resource that references a `Borrower` compare the resource's borrower foreign-key field to `X-User-ID`.
- `HudAuditor` is a read-only HUD/FHA auditor that additionally may invoke the ledger reconcile/recompute action. When `X-User-Role` is `HudAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `System` is the automation actor for the simulated clock and the occupancy and property-charge sweeps. When `X-User-Role` is `System`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

All collection (list) endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

List endpoints return results sorted by `created_at` in ascending order (oldest first). The `meta` block of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter before the limit/offset window is applied and `has_more` is true when records remain beyond the current window.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` that is a UUID with no type prefix; clients never supply it. Most resources also carry timestamp and version metadata. The `created_at` field is the ISO 8601 UTC instant of creation with three fractional digits; `updated_at` is the ISO 8601 UTC instant of the most recent mutation, likewise with three fractional digits; and `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation that changes the resource.

Two entities are leaner. The `PrincipalLimitFactor` and the `LedgerEntry` are append-only reference rows: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version`. A `LedgerEntry`, in particular, is never modified after it is posted — corrections are expressed as new compensating entries, never as edits.

It is important to distinguish the audit `version` described here from the simulated wall-clock time. The simulated clock is a per-lender value, `clock_utc`, advanced only through the clock-setting capability described in §3; it is not the same thing as a resource's `updated_at`.

### 2.5. Monetary Representation, Precision, and Rounding

All monetary amounts in this system are integer counts of cents — there are no fractional cents and no floating-point currency fields anywhere in the contract. Field names that end in `_cents` are always whole-cent integers.

Wherever a computation produces a fractional cent, the result is rounded half up to the nearest whole cent (a value exactly halfway between two cents rounds to the larger magnitude). This rounding rule is applied at the specific step each calculation in §3 designates, because — as the accrual and payoff-quote rules make explicit — rounding each period and then accumulating produces a different final cent figure than accumulating and then rounding once. The scheduled-payment calculation is the sole exception to half-up rounding: it floors to whole cents so that the servicer never schedules a payment stream that overpays the available principal.

### 2.6. Two Independent Loan State Axes

A `Loan` evolves along two completely independent state dimensions that live on the same record. The first axis, `servicing_status`, tracks day-to-day compliance and takes the values `CURRENT`, `DELINQUENT_OCCUPANCY`, and `DELINQUENT_PROPERTY_CHARGE`. The second axis, `disposition_status`, tracks the loan's position in the maturity-to-closeout lifecycle and takes the values `ACTIVE`, `DUE_AND_PAYABLE`, `DEFERRED`, `IN_RESOLUTION`, and `TERMINATED`. A loan reaches its terminal condition when `disposition_status` becomes `TERMINATED`.

These axes move independently. A loan may be `DELINQUENT_OCCUPANCY` on the servicing axis while remaining `ACTIVE` on the disposition axis; conversely, a maturity event advances the disposition axis to `DUE_AND_PAYABLE` without disturbing the servicing axis. Some operations examine both axes at once — for instance, approving or disbursing a draw requires the loan to be `ACTIVE` on the disposition axis and `CURRENT` on the servicing axis simultaneously.

### 2.7. Hierarchical Consistency and Mutation Semantics

Whenever an operation changes a resource, the system refreshes that resource's `updated_at` to the current real-world instant and increments its `version` by 1. When a single operation cascades across more than one resource — as many do in this domain — each affected resource that carries version metadata has its own `updated_at` refreshed and its own `version` incremented. The cascades themselves are enumerated in the workflow narratives of §3; the principle here is only that a cascade is a true mutation of every resource it touches, not a silent side change.

### 2.8. Filtered Retrieval and Path Resolution

The topology is flat: loans, borrowers, disbursements, set-asides, payments, certifications, maturity events, deferrals, resolutions, and ledger entries are peer collections reached by their own identifiers and linked by foreign keys rather than by nested URLs. When an endpoint names a resource by an `id` in its path, that identifier is resolved before the request body is considered; if any referenced resource — whether named in the path or in the body — does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404). When more than one identifier is present, they are resolved left to right, so the leftmost unresolved identifier is the one reported.

List endpoints accept optional filter parameters that narrow the returned collection. Loans may be filtered by `lender_id`, `borrower_id`, or `non_borrowing_spouse_id`; principal-limit-factor rows by `lender_id` and `expected_rate_bps`; borrowers, set-asides, maturity events, ledger entries, and resolutions by `lender_id` or `loan_id` as applicable; property-charge payments by `loan_id` or `lesa_set_aside_id`; disbursements and occupancy certifications by `loan_id` and by `status`; and non-borrowing-spouse deferrals by `loan_id`, `borrower_id`, or `maturity_event_id`.

### 2.9. Optimistic Concurrency on the Credit Line

The available line of credit is a finite, growing pool, and approving a credit-line draw consumes part of it. To prevent an approver from acting on a stale view of that pool, approval of a disbursement is guarded by optimistic concurrency control on the loan. A disbursement-approve request must carry `expected_loan_version`, a non-optional field whose value is the client's last observed `version` of the target `Loan`. If `expected_loan_version` does not equal the loan's current `version` — for example because a prior approve against the same loan has already debited the available line and advanced the loan's `version` since the client last read it — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the loan and retry. A successful approve increments the loan's `version` by 1. No other endpoint takes a version field; only disbursement approval is OCC-guarded.

### 2.10. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: first, the user-context header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, the role-permission check (`ERR_FORBIDDEN_FOR_ROLE`); third, existence of every referenced resource id, resolved left to right (`ERR_NOT_FOUND`); fourth, request-body well-formedness — required fields present, enumerations valid, monetary amounts strictly greater than zero, a `TERM` loan carrying `tenure_term_months`, a `SHORT_SALE` resolution carrying `appraised_at_resolution_cents` (`ERR_INVALID_REQUEST`); and fifth, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after all five of these pass does the system evaluate the domain-specific business rules described in §3, which are themselves ordered relative to one another wherever more than one can apply to the same endpoint.

## 3. Business Logic & Workflows

### 3.1. Portfolio Setup: Lenders, Factor Tables, and the Simulated Clock

Before any loan can exist, a servicer establishes a lender. A `ServicerOps` operator creates one by supplying the servicer's display `name` and the FHA national HECM lending limit, `hud_lending_limit_cents`, which must be greater than zero and which functions as the ceiling on every loan's maximum claim amount. On creation the lender's simulated clock, `clock_utc`, is initialized to `1970-01-01T00:00:00.000Z`. That clock is a per-lender simulated current UTC instant expressed in ISO 8601 with three fractional digits, and it is the reference point for every age computation, anniversary, certification due date, and accrual posting in the system.

The clock advances only through an explicit clock-setting capability, available to `System` and to `ServicerOps`, which accepts the target lender's `lender_id` and a `to_iso8601` instant and assigns it to that lender's `clock_utc`. Advancing the clock additionally runs an occupancy-delinquency sweep, described in §3.6, that lapses any certification whose due date has passed. The clock-setting operation returns the updated lender and does not change resource versions other than the lender's own.

A lender also owns a principal-limit-factor table. Each row is registered by `ServicerOps` and consists of the owning `lender_id`, an `age` (the youngest-borrower age the factor applies to, between 62 and 150 inclusive), an `expected_rate_bps` bucket (the expected-rate bucket in basis points the factor applies to, at least 0 — for example 500 represents 5.00%), and a `factor_micros` value (the principal-limit factor expressed in micros, where 0.5230 is stored as 523000, constrained between 1 and 1000000 inclusive). These rows are the lookup table consulted at origination. Factor rows are reference data: each carries only an `id` and `created_at`, with no `updated_at` and no `version`. They may be retrieved individually or listed and filtered by `lender_id` and `expected_rate_bps`.

### 3.2. Borrowers and Loan Creation

A `ServicerOps` operator records each person on a loan as a borrower. A borrower is created with the owning `lender_id`, a legal `full_name`, and a `birthdate` in `YYYY-MM-DD` form. Two boolean flags distinguish a non-borrowing spouse from a borrower of record: `is_non_borrowing_spouse` (defaulting to false) marks the person as a non-borrowing spouse rather than a borrower, and `nbs_qualifies` (defaulting to false) records whether that spouse satisfied HUD's eligibility conditions — married at origination, occupying the property as a principal residence, and named on the loan. Every borrower begins with `occupancy_status` set to `OCCUPYING`; this enumeration also admits `VACATED` and `DECEASED`, and is later moved by occupancy certifications and maturity events rather than set directly by the client.

A loan is created in a pre-origination state by `ServicerOps`. The creation payload names the owning `lender_id` and the `borrower_id` of the youngest borrower of record, and may optionally name a `non_borrowing_spouse_id` that is expected to reference a borrower whose `is_non_borrowing_spouse` flag is true (the loan-creation endpoint only verifies that the referenced borrower exists, resolving it with `ERR_NOT_FOUND` if absent, and does not itself re-check the `is_non_borrowing_spouse` flag at creation). It carries the `appraised_value_cents` (the appraised property value at origination, greater than zero), the `expected_rate_bps` (the expected interest rate at origination in basis points, at least 0, which both selects the factor bucket and drives balance growth), and the `draw_type`. The draw type is one of `LUMP_SUM`, `LINE_OF_CREDIT`, `TENURE`, or `TERM`; it is fixed at origination and never changes thereafter. Three further inputs are optional: `annual_mip_rate_bps` (the ongoing annual mortgage-insurance-premium rate in basis points, at least 0, defaulting to 50, which is HUD's 0.50%), `tenure_term_months` (required only for a `TERM` loan, where it is the number of monthly-payment months and must be at least 1), and `initial_financed_costs_cents` (closing costs plus initial MIP financed into the loan, at least 0, defaulting to 0).

At creation the loan's `disposition_status` is `ACTIVE` pending origination, its `servicing_status` is `CURRENT`, its `origination_date` is null, and every monetary balance is zero. The computed fields — `max_claim_amount_cents`, `principal_limit_factor_micros`, `gross_principal_limit_cents`, `lesa_set_aside_cents`, `net_principal_limit_cents`, `principal_balance_cents`, `available_line_of_credit_cents`, `monthly_payment_cents`, and `months_elapsed` — remain at their defaults until origination posts. A loan records the `lender_id` exactly as supplied in the creation payload (this is expected to be the lender of the borrower's portfolio); the server stores the supplied `lender_id` verbatim and does not derive or override it from the borrower's own `lender_id`.

### 3.3. Pre-Origination LESA Configuration

If a loan is to carry a life-expectancy set-aside, the set-aside is created before origination by `ServicerOps`. A LESA names the `loan_id` it funds, a `funding_mode` of either `FULLY_FUNDED` or `PARTIALLY_FUNDED`, the `annual_property_charge_cents` (estimated annual property charges — taxes plus insurance — used to size the set-aside, greater than zero), and a `life_expectancy_years` horizon (the HUD life-expectancy set-aside horizon in whole years, at least 1). On creation its `status` is `FUNDED`; the alternative status is `EXHAUSTED`. Its computed fields — `initial_amount_cents` (the total carved from the principal limit), `drawn_cents` (the cumulative amount paid out, a conserved-pool counter starting at 0), and `remaining_cents` (the pool residual) — are resolved when the loan originates, not when the LESA is created. Set-asides may be retrieved individually or listed and filtered by `loan_id`.

The sizing of the set-aside is keyed off the estimated charges and the funding mode, never off the loan's net limit, and the evaluation order is pinned so that the set-aside is sized first and only then carved out of the gross principal limit. Under `FULLY_FUNDED` mode — where the servicer pays the property charges directly — the `initial_amount_cents` is the `annual_property_charge_cents` multiplied by the `life_expectancy_years` horizon, carving the full horizon from the principal limit. Under `PARTIALLY_FUNDED` mode — a semi-annual disbursement model in which the borrower receives funds to pay charges — the `initial_amount_cents` is the `annual_property_charge_cents` multiplied by the `life_expectancy_years` horizon, that product then divided by 2 and rounded half up to whole cents. The two modes consume identical inputs and produce a different `initial_amount_cents`: the fully-funded amount is exactly twice the partially-funded amount before rounding.

### 3.4. Origination: Principal Limit, Carve-Out, and Initial Advance

Origination is the event that turns a pre-origination loan into a serviced asset, performed by `ServicerOps`. It is permitted only while the loan is still in its pre-origination state — that is, while `origination_date` is null; attempting to originate a loan that already has an `origination_date` set is rejected with `ERR_ALREADY_ORIGINATED` (HTTP 409). The draw type supplied at creation must be valid, and a `TERM` loan must carry a `tenure_term_months` of at least 1, or the request fails with `ERR_INVALID_REQUEST`. The regulatory age floor is enforced here: the youngest borrower's age, computed as the whole number of years between the borrower's `birthdate` and the date portion of the lender's `clock_utc` (flooring to whole years), must be at least 62; if it is below 62, origination is rejected with `ERR_BORROWER_UNDER_AGE` (HTTP 422).

Origination computes the principal limit in a fixed sequence. First, the `max_claim_amount_cents` is the smaller of the loan's `appraised_value_cents` and the lender's `hud_lending_limit_cents`. Next, the principal-limit factor is resolved from the lender's factor table by matching on the loan's `expected_rate_bps` bucket and on the borrower's age, where the age used for the lookup is the borrower's age but never more than 90 — ages above 90 use the age-90 factor row. If the table contains a row for exactly that age, it is chosen; otherwise the chosen row is the one with the greatest `age` value that is still less than or equal to the borrower's (capped) age. The resolved row's `factor_micros` becomes the loan's `principal_limit_factor_micros`. If no factor row matches the loan's `expected_rate_bps` and the borrower's age at origination, origination is rejected with `ERR_PLF_NOT_FOUND` (HTTP 422). The `gross_principal_limit_cents` is then the `max_claim_amount_cents` multiplied by the resolved `principal_limit_factor_micros`, that product divided by 1,000,000, with the single multiply-and-divide step rounded half up to whole cents.

If a LESA exists for the loan, its `initial_amount_cents` is computed per §3.3 and copied onto the loan as `lesa_set_aside_cents`; absent a LESA, `lesa_set_aside_cents` stays 0. The conserved-capacity baseline, `net_principal_limit_cents`, is the `gross_principal_limit_cents` less the `lesa_set_aside_cents` less the `initial_financed_costs_cents`. The initial advance is then posted: `principal_balance_cents` is set to the `initial_financed_costs_cents`, recorded as an `ADVANCE` ledger entry. Finally `origination_date` is set to the date portion of the lender's `clock_utc`, `months_elapsed` is set to 0, and the loan settles to `disposition_status` `ACTIVE` and `servicing_status` `CURRENT`.

How the remaining capacity is expressed depends on the draw type, and this is the point at which the four draw types diverge. For a `LINE_OF_CREDIT` loan, the entire `net_principal_limit_cents` becomes the `available_line_of_credit_cents` — an undrawn, growing pool — while `principal_balance_cents` reflects only the initial financed costs. For a `LUMP_SUM` loan, the borrower draws the full net principal limit at origination: `available_line_of_credit_cents` stays 0 and the `principal_balance_cents` becomes the initial financed costs plus a net-principal-limit advance; the gross limit is identical to the line-of-credit case but the available figure differs. For a `TENURE` or a `TERM` loan, the `monthly_payment_cents` is computed by the scheduled-payment calculation below, and `available_line_of_credit_cents` remains 0.

The scheduled-payment calculation sizes the recurring monthly disbursement for tenure and term loans. The available principal is the loan's `net_principal_limit_cents`. The monthly rate is the `expected_rate_bps` divided by 10,000 and then by 12 — note that MIP is deliberately excluded from this rate base. The number of payment months depends on the draw type: for a `TENURE` loan, the count is the quantity (100 minus the borrower's age) multiplied by 12, reflecting HUD's practice of paying until the borrower reaches age 100 — and here the borrower's age is the actual age at origination (not capped at 90 as it is for the PLF-table lookup), so a borrower already at or beyond 100 yields a non-positive count for which the `monthly_payment_cents` is 0; for a `TERM` loan, the count is the loan's `tenure_term_months`. If the monthly rate is zero, the `monthly_payment_cents` is the available principal divided by the number of payment months, floored to whole cents. Otherwise the `monthly_payment_cents` is the available principal multiplied by the monthly rate and divided by the quantity (1 minus the value of (1 plus the monthly rate) raised to the power of the negative number of payment months), with the final figure floored to whole cents so the schedule never overpays the principal.

### 3.5. The Disbursement Lifecycle

A draw against a loan is modeled as a disbursement. A disbursement is requested — by `ServicerOps` or by the `Borrower` of the loan — with the `loan_id`, the `kind`, and the `requested_amount_cents` (the amount the borrower wishes to draw, greater than zero). The `kind` is one of `INITIAL` (the origination advance), `LINE_DRAW` (an ad hoc credit-line draw), or `SCHEDULED` (a tenure or term monthly payment). A new disbursement begins in `REQUESTED` status; the lifecycle's other statuses are `APPROVED`, `DISBURSED`, `REJECTED`, and `VOIDED`. Its `approved_amount_cents` starts at 0. Disbursements may be retrieved individually or listed and filtered by `loan_id` and by `status`.

From `REQUESTED`, a draw forks. A `ServicerOps` operator may reject it, which moves it to `REJECTED` and leaves `approved_amount_cents` at 0. Alternatively the operator may approve it, advancing it from `REQUESTED` to `APPROVED`. Approval is the most heavily guarded transition in the system, and its checks are evaluated in the following order once the universal header, role, existence, body, and state checks of §2.10 have passed. First, the loan must be drawable — `disposition_status` `ACTIVE` and `servicing_status` `CURRENT` at the same time — or the approval is rejected with `ERR_LOAN_NOT_DRAWABLE` (HTTP 409). Second, a draw whose `kind` is `LINE_DRAW` requires the loan's `draw_type` to be `LINE_OF_CREDIT`; otherwise the request fails with `ERR_DRAW_TYPE_MISMATCH` (HTTP 409). Third, the `requested_amount_cents` must be less than or equal to the loan's `available_line_of_credit_cents` — drawing exactly the full available line is allowed, and only a request strictly greater than the line is rejected, with `ERR_INSUFFICIENT_LINE` (HTTP 422). Fourth, the optimistic-concurrency guard of §2.9 applies: the `expected_loan_version` supplied with the approve must equal the loan's current `version`, failing which the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). On a successful approve, `approved_amount_cents` is set equal to `requested_amount_cents` and the loan's `version` is incremented by 1.

From `APPROVED`, a `ServicerOps` operator disburses the draw, moving it to `DISBURSED`, which is permitted only while the loan's `disposition_status` is `ACTIVE`; otherwise the request fails with `ERR_LOAN_NOT_DRAWABLE`. Disbursing adds the `approved_amount_cents` to the loan's `principal_balance_cents` (posted as an `ADVANCE` ledger entry) and subtracts the same `approved_amount_cents` from the loan's `available_line_of_credit_cents`, so that balance and remaining line stay conserved against each other.

A disbursed draw may later be voided by `ServicerOps`, moving it from `DISBURSED` to `VOIDED`, but only while the loan's `disposition_status` is `ACTIVE`; otherwise the void is rejected with `ERR_INVALID_STATE`. A void is a compensating reversal: the `approved_amount_cents` is subtracted back out of the `principal_balance_cents` (posted as a `REVERSAL` ledger entry) and added back to the `available_line_of_credit_cents`, restoring the conserved principal-capacity invariant to where it stood before the disbursement.

Two further routes into `VOIDED` exist, both driven by the system rather than by an operator, and both fire as a cascade when a loan becomes due and payable (see §3.7). A disbursement still in `REQUESTED` and a disbursement still in `APPROVED` are each voided automatically — but only because they have not yet been disbursed — with `approved_amount_cents` set to 0. A draw already in `DISBURSED` is not swept by this cascade; it represents money already advanced.

### 3.6. Accrual, Line Growth, and the Forward-Looking Payoff Quote

A HECM balance grows each month it is serviced. A `ServicerOps` operator or the `System` posts accrual for a loan by supplying `number_of_months`, the count of whole servicing months to post in this run. The posting compounds month by month, and the order of operations is pinned because it changes the final cents: each per-month component is rounded to whole cents first, then added to the balance, and that rounded balance is the base for the next month — rounding per period and then accumulating, not accumulating and then rounding.

For each month in the run the system computes two components from the current `principal_balance_cents`. The interest component is the current `principal_balance_cents` multiplied by the quantity (`expected_rate_bps` divided by 10,000, then divided by 12), rounded half up to whole cents. The MIP component is the current `principal_balance_cents` multiplied by the quantity (`annual_mip_rate_bps` divided by 10,000, then divided by 12), rounded half up to whole cents. The sum of the interest component and the MIP component is added to `principal_balance_cents`, recorded as two separate ledger entries — one `INTEREST_ACCRUAL` and one `MIP_ACCRUAL`. In the same month, the `available_line_of_credit_cents` grows by the current `available_line_of_credit_cents` multiplied by the combined monthly growth rate — where the combined monthly rate is the sum of `expected_rate_bps` and `annual_mip_rate_bps`, divided by 10,000 and then by 12 — rounded half up to whole cents. After each month is posted, `months_elapsed` increases by 1; over the full run it rises by the supplied `number_of_months`.

A forward-looking payoff quote answers a different question and never mutates anything. Any of `ServicerOps`, `ComplianceOfficer`, `HudAuditor`, or the loan's `Borrower` may request one, optionally supplying `number_of_months` to project ahead; when `number_of_months` is omitted it defaults to 0, which projects no growth and yields the current balance, and a supplied `number_of_months` must be a non-negative integer (a negative value is rejected with `ERR_INVALID_REQUEST`). Unlike posted accrual, the quote projects the balance forward as a single compounded figure computed once at the end: the projected balance is the current `principal_balance_cents` multiplied by the quantity (1 plus the combined monthly rate) raised to the power of `number_of_months`, the whole product rounded half up to whole cents (accumulate-then-round). Because of this single-rounding treatment, for the same loan and the same number of months the quote's projected figure will generally differ in cents from what posting that many months of accrual would yield. The quote response reports the `loan_id`, the `projected_balance_cents`, the `lesser_of_payoff_cents` (the non-recourse lesser-of figure described in §3.9, computed against the projected balance with the basis value being the loan's original `appraised_value_cents`), and the `deficiency_cents` implied by that projection (the projected balance less `lesser_of_payoff_cents`).

### 3.7. Annual Occupancy Certification and the Servicing Axis

HUD requires the borrower to attest annually that the property remains the principal residence. A `ServicerOps` operator opens an occupancy certification by naming the `loan_id` and the `certification_year` — the 1-based whole-year index since origination, at least 1. On creation the certification's `status` is `PENDING`, its `certified_at` is null, and its `due_date` is computed by the system as the loan's origination anniversary for that year: the `origination_date` advanced by `certification_year` years. Because that due date is keyed off the `origination_date`, a certification may be opened only after the loan has originated; opening one against a loan whose `origination_date` is still null is rejected with `ERR_INVALID_STATE` (HTTP 409). At most one certification may exist per loan per certification year, and a new year's annual window may not overlap an existing certification's window; an attempt to open an overlapping certification is rejected with `ERR_CERT_PERIOD_OVERLAP` (HTTP 409). Certifications may be retrieved individually or listed and filtered by `loan_id` and by `status`. A certification cycles through `PENDING`, `DELINQUENT`, and `CERTIFIED` over the life of the loan; the statuses it admits are exactly those three.

A certification lapses when its deadline passes uncertified. This happens in either of two equivalent ways: the clock-advance sweep of §3.1 moves any `PENDING` certification whose `due_date` is now earlier than the new clock date to `DELINQUENT`, and a `ServicerOps` operator or the `System` may also mark a past-due pending certification delinquent directly — both require that the certification is still `PENDING` and that the date portion of the lender's `clock_utc` is strictly later than the `due_date`. When a certification lapses to `DELINQUENT`, the system cascades onto the loan's servicing axis: a loan whose `servicing_status` is `CURRENT` flips to `DELINQUENT_OCCUPANCY`. This cascade does not disturb the disposition axis.

Certifying recovers the loan. The loan's `Borrower` — or a `ServicerOps` operator acting on the borrower's behalf — certifies a certification, which is defined from both `PENDING` and `DELINQUENT`, moving it to `CERTIFIED`, and is permitted only while the loan's `disposition_status` is not `TERMINATED`; otherwise the certify is rejected with `ERR_INVALID_STATE`. A certification submitted on or before its `due_date` certifies directly from `PENDING`; once the clock has passed the due date the certification is `DELINQUENT` and certifying recovers it from there. Certifying records `certified_at` as the lender's current `clock_utc`. It then performs a bubble-up cascade: if the loan's `servicing_status` is `DELINQUENT_OCCUPANCY` and no other certification on that loan remains `DELINQUENT`, the loan's `servicing_status` returns to `CURRENT`. If another delinquent certification still exists, the servicing axis stays `DELINQUENT_OCCUPANCY`.

### 3.8. Property Charges and the LESA Pool

Where a set-aside funds a loan's property charges, each charge paid from the pool is recorded as a property-charge payment by `ServicerOps`. A payment names the `loan_id`, the `lesa_set_aside_id` of the pool it draws from, a `charge_type` of either `PROPERTY_TAX` or `HAZARD_INSURANCE`, a half-open coverage window given by `coverage_start` (inclusive) and `coverage_end` (exclusive) in `YYYY-MM-DD` form, and an `amount_cents` (the amount drawn from the pool, greater than zero). A new payment's `status` is `POSTED`; the alternative is `REVERSED`. Payments may be retrieved individually or listed and filtered by `loan_id` and by `lesa_set_aside_id`.

Three business checks guard a payment, beyond the universal validations. The referenced set-aside must be `FUNDED` rather than `EXHAUSTED`, and it must belong to the same loan as the payment; a payment against an exhausted pool or against a pool belonging to a different loan is rejected with `ERR_LESA_EXHAUSTED` (HTTP 409). The coverage window must not overlap an existing `POSTED` payment of the same `charge_type` on the same loan; because the window is half-open, two payments are adjacent and allowed when one window's `coverage_end` equals the next window's `coverage_start`, and only a genuine overlap is rejected, with `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409). And the `amount_cents` may not exceed the set-aside's `remaining_cents`, since the pool cannot be overdrawn; an amount greater than the residual is rejected with `ERR_LESA_OVERDRAW` (HTTP 422).

Posting a payment moves money out of the pool and onto the loan. The set-aside's `drawn_cents` increases by the `amount_cents`, its `remaining_cents` decreases by the same `amount_cents` (where `remaining_cents` is always the `initial_amount_cents` less the `drawn_cents`), and once `remaining_cents` reaches 0 the set-aside's `status` flips to `EXHAUSTED`. In the same operation the loan's `principal_balance_cents` increases by the `amount_cents`, recorded as a `LESA_DRAW` ledger entry.

A posted payment may be reversed by `ServicerOps`, moving it from `POSTED` to `REVERSED`. Reversal is a compensating restoration of the pool: the set-aside's `drawn_cents` decreases by the `amount_cents`, its `remaining_cents` increases by the same `amount_cents`, and its `status` returns to `FUNDED`. The loan's `principal_balance_cents` decreases by the `amount_cents`, recorded as a `REVERSAL` ledger entry.

### 3.9. Maturity, Due-and-Payable, and the Disposition Path

A maturity event ends the loan's active life. A `ComplianceOfficer` or a `ServicerOps` operator records one by naming the `loan_id`, the `event_type` — one of `BORROWER_DEATH`, `PERMANENT_VACANCY`, `SALE_OF_PROPERTY`, or `TAX_INSURANCE_DEFAULT` — and the `event_date` in `YYYY-MM-DD` form. A new event's `status` is `RECORDED`; it later becomes `ACKNOWLEDGED`. Maturity events may be retrieved individually or listed and filtered by `loan_id`.

Recording a maturity event cascades onto the loan when the loan is `ACTIVE` on the disposition axis. The loan's `disposition_status` advances from `ACTIVE` to `DUE_AND_PAYABLE`. Every disbursement on the loan still in `REQUESTED` or `APPROVED` — that is, every draw not yet `DISBURSED` — is voided as part of this cascade, with its `approved_amount_cents` reset to 0; draws already `DISBURSED` are left untouched. The loan's `available_line_of_credit_cents` is frozen to 0, because no further credit may be drawn once the loan is due and payable. There is one further conditional cascade: when the `event_type` is `TAX_INSURANCE_DEFAULT` and the loan's set-aside has a `remaining_cents` of 0 (the pool is exhausted), the loan's `servicing_status` flips to `DELINQUENT_PROPERTY_CHARGE` on the independent servicing axis.

Once a loan is due and payable, a `ComplianceOfficer` acknowledges the maturity event, moving it from `RECORDED` to `ACKNOWLEDGED`; acknowledgement records the due-and-payable notice issuance through the event's `updated_at`, and is permitted only while the loan's `disposition_status` is `DUE_AND_PAYABLE` or `DEFERRED`.

### 3.10. Non-Borrowing-Spouse Deferral

The death of a borrower need not force immediate closeout when an eligible non-borrowing spouse remains in the home. A `ComplianceOfficer` opens a non-borrowing-spouse deferral by naming the `loan_id`, the `borrower_id` of the eligible spouse, and the `maturity_event_id` of the death event that opened eligibility. Deferrals may be retrieved individually or listed and filtered by `loan_id`, `borrower_id`, or `maturity_event_id`.

Three conditions gate the deferral, each carrying its own error. The triggering maturity event's `event_type` must be `BORROWER_DEATH`, because only a death opens deferral eligibility; any other event type is rejected with `ERR_DEFERRAL_NOT_ELIGIBLE` (HTTP 422). The named spouse must be a qualifying non-borrowing spouse — both `is_non_borrowing_spouse` and `nbs_qualifies` true on that borrower — or the request is rejected with `ERR_NBS_NOT_QUALIFIED` (HTTP 422). And the loan must be `DUE_AND_PAYABLE` to enter deferral; from any other disposition the request fails with `ERR_INVALID_STATE`. Furthermore, a loan that already has an `ACTIVE` deferral cannot have another opened, and this same guard prevents starting a resolution while an active deferral stands: such an attempt is rejected with `ERR_DEFERRAL_ACTIVE` (HTTP 409). When more than one of these guards could fire on a single deferral-open request, they are evaluated in this fixed order after the universal §2.10 checks pass: first the active-deferral guard (`ERR_DEFERRAL_ACTIVE`), then the due-and-payable state guard (`ERR_INVALID_STATE`), then the death-event eligibility guard (`ERR_DEFERRAL_NOT_ELIGIBLE`), and last the spouse-qualification guard (`ERR_NBS_NOT_QUALIFIED`).

When a deferral is opened, its `status` is `ACTIVE`, its `period_start` is set to the triggering maturity event's `event_date`, and its `period_end` is null while active. The loan's `disposition_status` moves from `DUE_AND_PAYABLE` to `DEFERRED`, which freezes the disposition while the spouse remains. The only other status a deferral takes is `TERMINATED`.

When the deferral ends — the spouse dies or moves out — a `ComplianceOfficer` terminates it, which requires the deferral to be `ACTIVE`. Termination sets the deferral's `status` to `TERMINATED` and its `period_end` to the date portion of the lender's `clock_utc`, and it cascades onto the loan, moving the `disposition_status` from `DEFERRED` back to `DUE_AND_PAYABLE` so the closeout path re-opens.

### 3.11. Resolution: Payoff, Short Sale, and Foreclosure

A due-and-payable loan is closed out through a resolution, opened by a `ComplianceOfficer`. A resolution names the `loan_id`, the `path` — one of `PAYOFF`, `SHORT_SALE`, or `FORECLOSURE` — and, for a short sale, the `appraised_at_resolution_cents` (the re-appraised value at resolution, greater than zero, required for the short-sale deficiency math). A `SHORT_SALE` resolution submitted without `appraised_at_resolution_cents` is rejected with `ERR_INVALID_REQUEST`. A resolution may be opened only while the loan's `disposition_status` is `DUE_AND_PAYABLE`; an `ACTIVE` non-borrowing-spouse deferral on the loan blocks it with `ERR_DEFERRAL_ACTIVE` as described in §3.10, and this active-deferral guard is checked before the disposition-state guard, so a `DEFERRED` loan still carrying its active deferral reports `ERR_DEFERRAL_ACTIVE` rather than `ERR_INVALID_STATE`; from any other disposition (with no active deferral) the request fails with `ERR_INVALID_STATE`. Resolutions may be retrieved individually or listed and filtered by `loan_id`.

Opening a resolution sets its `status` to `INITIATED` — the other statuses being `SETTLED` and `CANCELLED` — moves the loan's `disposition_status` from `DUE_AND_PAYABLE` to `IN_RESOLUTION`, and computes the non-recourse lesser-of figures. The FHA non-recourse guarantee means the borrower or estate never owes more than 95% of the property's value, with any shortfall absorbed by FHA insurance. The basis value is the `appraised_at_resolution_cents` when the path is `SHORT_SALE` and otherwise the loan's original `appraised_value_cents`. The capped amount is 95% of that basis value — that is, the basis value multiplied by 95 and divided by 100 — rounded half up to whole cents. The `payoff_amount_cents` is the smaller of the loan's `principal_balance_cents` and that capped amount, and the `deficiency_cents` is the `principal_balance_cents` less the `payoff_amount_cents` (the portion absorbed by FHA insurance, which is 0 whenever the balance does not exceed the cap).

Settlement is terminal and is performed by a `ComplianceOfficer` on an `INITIATED` resolution while the loan is `IN_RESOLUTION`; a `SHORT_SALE` resolution still requires `appraised_at_resolution_cents` to be present at settle, failing with `ERR_INVALID_REQUEST` otherwise. Settling recomputes the lesser-of figures per the elected path, and the three paths diverge in their deficiency treatment. On the `PAYOFF` branch the balance is considered satisfied and `deficiency_cents` is 0, while the `payoff_amount_cents` is still set to the smaller of the balance and 95% of the loan's original `appraised_value_cents` (that original value multiplied by 95, divided by 100, rounded half up to whole cents). On the `SHORT_SALE` branch the `payoff_amount_cents` is the smaller of the balance and 95% of the `appraised_at_resolution_cents` (that re-appraised value multiplied by 95, divided by 100, rounded half up to whole cents), and the `deficiency_cents` is the balance less that `payoff_amount_cents`. On the `FORECLOSURE` branch the `payoff_amount_cents` is the smaller of the balance and 95% of the loan's original `appraised_value_cents` (that original value multiplied by 95, divided by 100, rounded half up to whole cents), and the `deficiency_cents` is the balance less that `payoff_amount_cents`. Settlement sets the resolution's `status` to `SETTLED`, moves the loan's `disposition_status` to `TERMINATED` (its terminal condition), and sets the loan's `available_line_of_credit_cents` to 0.

A resolution may instead be cancelled by a `ComplianceOfficer` while it is `INITIATED`, which sets its `status` to `CANCELLED` and re-opens the loan by moving its `disposition_status` from `IN_RESOLUTION` back to `DUE_AND_PAYABLE`.

### 3.12. The Append-Only Ledger and Audit Recompute

Every movement of the loan balance is recorded as a ledger entry, and the ledger is append-only: entries are written but never edited. Each `LedgerEntry` belongs to a `loan_id` and carries an `entry_type` of `ADVANCE`, `INTEREST_ACCRUAL`, `MIP_ACCRUAL`, `LESA_DRAW`, or `REVERSAL`; a polymorphic `source_ref_id` pointing at the originating disbursement or property-charge-payment identifier (null for system accruals and likewise null for the `ADVANCE` entries posted by origination itself — both the initial-financed-costs advance and, on a `LUMP_SUM` loan, the net-principal-limit advance — since those advances have no originating disbursement record); a signed `amount_cents` applied to the balance, where a positive value increases the balance; a `balance_after_cents` capturing the `principal_balance_cents` immediately after the entry posted; and a `posted_month_index` equal to the loan's `months_elapsed` when the entry was posted (0 at origination). Ledger entries may be listed and filtered by `loan_id` or retrieved one at a time by id for audit purposes.

A HUD auditor — or a `ServicerOps` operator — may invoke an audit recompute on a loan, which re-derives the `principal_balance_cents` from the ledger stream and reconciles it against the stored value. The derivation walks the loan's ledger entries in posting (creation) order, accumulating each entry's signed `amount_cents` into a running balance; at every entry the entry's stored `balance_after_cents` must equal that running balance, and after the last entry the running balance must equal the loan's stored `principal_balance_cents`. If either of those checks fails — a `balance_after_cents` that does not match the running total, or a final derived balance that does not match the stored `principal_balance_cents` — the operation reports `ERR_LEDGER_INCONSISTENT` (HTTP 409). The `available_line_of_credit_cents` is not ledger-tracked and so is not independently re-derived; it is carried at its stored value. On success the operation mutates nothing and returns the loan unchanged.

## 4. Endpoint Definitions

Creating a brand-new resource returns HTTP 201; every other successful operation — retrievals, list queries, state transitions, originations, accrual postings, and all other mutations on existing resources — returns HTTP 200. The table below summarizes the contract; the request and response details, side effects, and validation rules for each endpoint live in the §3 narratives above and the §2 principles. The clock-setting capability is a test/automation control that advances a lender's simulated time and runs the occupancy sweep.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/lenders` | Create a lender / servicer with the FHA lending limit | ServicerOps |
| GET | `/lenders/{lenderId}` | Get a lender | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| POST | `/loans/_clock/set` | Set the simulated current UTC for a lender; runs occupancy-delinquency sweep | System, ServicerOps |
| POST | `/principal-limit-factors` | Register a PLF table row | ServicerOps |
| GET | `/principal-limit-factors/{plfId}` | Get a PLF row | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/principal-limit-factors` | List PLF rows; filter by lender_id, expected_rate_bps | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/borrowers` | Create a borrower or non-borrowing spouse | ServicerOps |
| GET | `/borrowers/{borrowerId}` | Get a borrower | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| GET | `/borrowers` | List borrowers; filter by lender_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/loans` | Create a HECM loan in pre-origination state | ServicerOps |
| GET | `/loans/{loanId}` | Get a loan with all computed fields | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| GET | `/loans` | List loans; filter by lender_id, borrower_id, non_borrowing_spouse_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/loans/{loanId}/originate` | Originate the loan: principal limit, LESA carve, initial advance, line / scheduled payment | ServicerOps |
| POST | `/loans/{loanId}/post-accrual` | Post N months of compounding interest + MIP accrual and grow the line | ServicerOps, System |
| GET | `/loans/{loanId}/payoff-quote` | Forward-looking payoff quote (does not mutate) | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| POST | `/disbursements` | Request a disbursement (draw) against a loan | ServicerOps, Borrower |
| GET | `/disbursements/{disbursementId}` | Get a disbursement | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| GET | `/disbursements` | List disbursements; filter by loan_id, status | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| POST | `/disbursements/{disbursementId}/approve` | Approve a requested disbursement (OCC-guarded) | ServicerOps |
| POST | `/disbursements/{disbursementId}/disburse` | Disburse an approved disbursement | ServicerOps |
| POST | `/disbursements/{disbursementId}/reject` | Reject a requested disbursement | ServicerOps |
| POST | `/disbursements/{disbursementId}/void` | Void a disbursed draw (compensating reversal) | ServicerOps |
| POST | `/lesa-set-asides` | Create a property-charge set-aside (LESA) for a loan | ServicerOps |
| GET | `/lesa-set-asides/{lesaId}` | Get a LESA set-aside | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| GET | `/lesa-set-asides` | List LESA set-asides; filter by loan_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/property-charge-payments` | Pay a property charge from the LESA pool | ServicerOps |
| GET | `/property-charge-payments/{paymentId}` | Get a property-charge payment | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/property-charge-payments` | List property-charge payments; filter by loan_id, lesa_set_aside_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/property-charge-payments/{paymentId}/reverse` | Reverse a posted property-charge payment | ServicerOps |
| POST | `/occupancy-certifications` | Open a borrower occupancy certification for a certification_year | ServicerOps |
| GET | `/occupancy-certifications/{certId}` | Get an occupancy certification | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| GET | `/occupancy-certifications` | List occupancy certifications; filter by loan_id, status | ServicerOps, ComplianceOfficer, HudAuditor, Borrower |
| POST | `/occupancy-certifications/{certId}/certify` | Borrower attests continued occupancy | Borrower, ServicerOps |
| POST | `/occupancy-certifications/{certId}/mark-delinquent` | Mark a past-due PENDING certification delinquent | ServicerOps, System |
| POST | `/maturity-events` | Record a maturity event leading to due-and-payable | ComplianceOfficer, ServicerOps |
| GET | `/maturity-events/{eventId}` | Get a maturity event | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/maturity-events` | List maturity events; filter by loan_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/maturity-events/{eventId}/acknowledge` | Compliance acknowledges and issues the due-and-payable notice | ComplianceOfficer |
| POST | `/nbs-deferrals` | Open a non-borrowing-spouse deferral against a due-and-payable loan | ComplianceOfficer |
| GET | `/nbs-deferrals/{deferralId}` | Get an NBS deferral | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/nbs-deferrals` | List NBS deferrals; filter by loan_id, borrower_id, maturity_event_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/nbs-deferrals/{deferralId}/terminate` | Terminate an active deferral; due-and-payable re-opens | ComplianceOfficer |
| POST | `/resolutions` | Open a resolution (payoff / short-sale / foreclosure) for a due-and-payable loan | ComplianceOfficer |
| GET | `/resolutions/{resolutionId}` | Get a resolution | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/resolutions` | List resolutions; filter by loan_id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/resolutions/{resolutionId}/settle` | Settle a resolution (terminal); recomputes deficiency per path | ComplianceOfficer |
| POST | `/resolutions/{resolutionId}/cancel` | Cancel a resolution; loan returns to due-and-payable | ComplianceOfficer |
| GET | `/ledger-entries` | List append-only ledger entries; filter by loan_id | ServicerOps, ComplianceOfficer, HudAuditor |
| GET | `/ledger-entries/{ledgerEntryId}` | Get a single append-only ledger entry by id | ServicerOps, ComplianceOfficer, HudAuditor |
| POST | `/loans/{loanId}/recompute` | Audit recompute: re-derive balance from the ledger and reconcile | HudAuditor, ServicerOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_ORIGINATED | 409 |
| ERR_BORROWER_UNDER_AGE | 422 |
| ERR_PLF_NOT_FOUND | 422 |
| ERR_LOAN_NOT_DRAWABLE | 409 |
| ERR_DRAW_TYPE_MISMATCH | 409 |
| ERR_INSUFFICIENT_LINE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_LESA_EXHAUSTED | 409 |
| ERR_LESA_OVERDRAW | 422 |
| ERR_COVERAGE_WINDOW_OVERLAP | 409 |
| ERR_CERT_PERIOD_OVERLAP | 409 |
| ERR_DEFERRAL_NOT_ELIGIBLE | 422 |
| ERR_NBS_NOT_QUALIFIED | 422 |
| ERR_DEFERRAL_ACTIVE | 409 |
| ERR_LEDGER_INCONSISTENT | 409 |
| ERR_INVALID_PAGINATION | 400 |
