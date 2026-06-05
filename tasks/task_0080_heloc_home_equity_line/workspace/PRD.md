# Heloc Home Equity Line API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Home Equity Line of Credit (HELOC) servicing platform. A HELOC is a revolving credit facility secured by a lien against real property: during an initial **draw period** the borrower may advance and repay principal freely up to a committed credit limit, after which the line converts into an amortizing **repayment period**. The platform must govern the full lifecycle of such a line — from underwriting and lien recording, through variable-rate interest accrual driven by a published PRIME index plus a lender margin, through annual fee assessment, covenant monitoring, default declaration, and finally closure with release of the recorded lien.

Two concerns dominate the design. The first is **financial reconciliation**: every line carries a set of derived monetary fields (its outstanding balance, available credit, effective rate, and accrued interest) that must remain consistent with an underlying ledger of draws, payments, and fee assessments. Interest is computed two ways — a chronological daily replay of the historical ledger and a forward-looking projection — and the two must never be conflated. The second is **compliance and segregation of duties**: covenants encode the default triggers (loan-to-value, debt-service-coverage, and delinquency limits), breach of a covenant freezes the line, and a default may only be declared by a servicer who is not the officer who originated it. These rules, together with optimistic concurrency on the shared rate index, make correctness the central product requirement.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). These two checks are evaluated before any other validation.

The system recognizes exactly four roles: `LoanOfficer`, `LoanServicer`, `Borrower`, and `Auditor`.

- A `LoanOfficer` originates lines — creating borrowers, properties, HELOC applications, and covenants, and activating applications. When `X-User-Role` is `LoanOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition writes it (notably, the activating officer's identifier is retained on the line so that the later default-declaration segregation-of-duties check can compare against it) but does not compare it to any entity's `id`.
- A `LoanServicer` services active lines — publishing index rates, booking draws and reversals, posting payments, freezing and unfreezing, converting to repayment, declaring default, closing lines, evaluating and curing covenants, and advancing the billing clock. When `X-User-Role` is `LoanServicer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `declared_by_user_id` on a `DefaultEvent` when default is declared) but does not compare it to any entity's `id`.
- A `Borrower` is the obligor on a line and may post payments and read the payments and fee assessments of a line. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower` entity; ownership checks on any resource that references a `Borrower` compare the resource's borrower foreign key to `X-User-ID`.
- An `Auditor` has read-only oversight across all lines, including the default-event audit trail. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless stated otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system are top-level entities that carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, with three fractional digits, recording the last modification; it is refreshed on every mutation.
- `version` — a system-managed integer that starts at 1 and increments by 1 on every mutation of the resource. It supports optimistic concurrency control (§2.7).

One entity is an exception. A `DefaultEvent` is an immutable audit record: it carries only `id` and `created_at`. It has neither an `updated_at` nor a `version` field, because once written it is never modified. All other entities — `Property`, `Borrower`, `IndexRate`, `Heloc`, `Draw`, `Payment`, `FeeAssessment`, `Covenant`, and `LienRecord` — carry the full quartet of common fields above.

Whenever a side effect updates a derived field on an entity (for example, recomputing a line's available credit or effective rate), that update is itself a mutation: it refreshes the entity's `updated_at` and increments its `version`.

### 2.5. Monetary Values, Rates, and Rounding

All monetary amounts in the system are stored and exchanged as integer **cents**; there are no fractional cents and no floating-point money. All rates are stored as integer **basis points** (bps), where 10000 bps equals 100.00%. For instance, a PRIME index value of 8.50% is recorded as a `rate_bps` of 850, and a loan-to-value ratio of 85.00% is expressed as 8500 bps.

Wherever a calculation produces a non-integer cents or basis-point figure, the result is rounded to a whole integer using the **round half up** convention (a value of exactly one half rounds away from zero, upward). The interest-accrual calculation pins its rounding order: interest is rounded half up once per inter-event segment and only then summed across segments — segments are never summed before rounding. The covenant metrics (loan-to-value and debt-service-coverage) are each rounded half up to whole basis points before the threshold comparison is made. The payment waterfall performs no rounding at all: its allocation is exact integer-cents arithmetic.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address nested resources through multi-segment paths (for example, a covenant beneath a HELOC, or a draw beneath a HELOC). For any such request, the system validates the existence of each path-referenced resource in strict left-to-right order, rejecting the request with `ERR_NOT_FOUND` (HTTP 404) at the first path segment that does not resolve to an existing resource. A covenant addressed beneath a non-existent HELOC therefore fails on the HELOC before the covenant is ever consulted.

A distinct check governs foreign-key references supplied in a request body rather than in the path. When a create operation names another resource by id in its body — a borrower or property on HELOC creation, a covenant on default declaration, or the implied HELOC on a covenant attachment — and that reference does not resolve to an existing row, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). This body-reference check applies to HELOC creation, covenant attachment, and default declaration.

### 2.7. Optimistic Concurrency Control on the Rate Index

The PRIME index is a shared resource: a single active index value drives the effective rate of every active line, and servicers supersede it by publishing fresher values. To prevent a servicer from overwriting an index reset they have not observed, the supersede operation is guarded by optimistic concurrency control.

A request to supersede an `IndexRate` must carry `expected_indexrate_version`, a non-optional field holding the client's last observed `version` of the target `IndexRate`. If `expected_indexrate_version` does not match that `IndexRate`'s current `version` — because another servicer has already published a fresher PRIME value and advanced the row's version since the client last read it — the supersede is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and no other endpoint is subject to this check.

### 2.8. Hierarchical Consistency and Cascades

A single servicing action frequently mutates more than one entity, and every such cascade is part of the contract. Activation records a lien and flips the property to in-use. A covenant breach can freeze the line. Default declaration writes an audit event and blocks further credit. Closure cures every covenant, releases the recorded lien, and may release the property. Each of these secondary mutations independently refreshes the affected entity's `updated_at` and increments its `version`, exactly as a primary mutation would. The detailed cascade for each action is given in §3.

### 2.9. The Logical Clock

Because interest accrual, anniversary fees, draw-period boundaries, and delinquency all depend on the passage of time, the system runs on a server-controlled **logical clock** rather than wall-clock time. An administrative capability sets the current UTC instant to a supplied value for deterministic testing, and a per-line capability advances a line's billing clock forward, assessing fees and recomputing time-derived fields as it crosses anniversaries. All temporal comparisons in the business rules below are made against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Originating the Parties and the Collateral

Before a line can exist, a `LoanOfficer` establishes the borrower and the collateral property.

A **borrower** is created with a legal `full_name`, a verified gross `annual_income_cents`, an optional existing `monthly_debt_obligation_cents` (the borrower's monthly debt service excluding this HELOC, defaulting to 0 when omitted), and a `credit_score`. The credit score is a FICO figure constrained to the range 300 through 850 inclusive. A borrower also carries a `kyc_status` recording the Know-Your-Customer outcome, one of `PENDING`, `CLEARED`, or `REJECTED`; when omitted at creation it defaults to `PENDING`. The income figure must be at least 0 and the monthly debt obligation must be at least 0. A `LoanOfficer` may later amend a borrower's `kyc_status`, `annual_income_cents`, or `monthly_debt_obligation_cents`; each such amendment is a mutation that bumps the borrower's version.

A **property** is the collateral and is created with a `street_address`, an `appraised_value_cents` (the most recent appraisal, the basis for loan-to-value), an optional `senior_lien_balance_cents` (the outstanding balance of all senior first-position liens, defaulting to 0 when there are none), and a `county_fips` recording the jurisdiction in which the lien is filed. The appraised value must be at least 1, and the senior lien balance must be at least 0. A property carries a computed `status` of either `ACTIVE` (while it collateralizes a non-closed line) or `RELEASED` (once every lien against it has been released); it begins `ACTIVE`. Either a `LoanOfficer` or a `LoanServicer` may revalue a property by updating its `appraised_value_cents` or `senior_lien_balance_cents`, which bumps the property's version.

### 3.2. Publishing and Resetting the PRIME Index

A `LoanServicer` publishes a PRIME index value as an **index rate**, supplying the `rate_bps` (the index value in basis points) and the `effective_date` (the ISO 8601 UTC instant, at midnight, from which the value applies). The `index_name` may be supplied but the only value this product accepts is `PRIME`; when omitted it defaults to `PRIME`. Each index rate carries a computed `superseded` flag, false at creation, that becomes true once a newer index rate for the same `index_name` with a later `effective_date` exists. On publication of a new value, any prior index rate with the same `index_name` and an earlier `effective_date` is marked superseded.

The **active** index is the non-superseded PRIME value. Resetting the index is performed by superseding an existing index rate: the servicer publishes a fresh `rate_bps` and `effective_date` against the prior row, which creates a new PRIME `IndexRate`, sets the prior row's `superseded` to true, and recomputes the effective rate on every line currently in `DRAW`, `FROZEN`, or `REPAYMENT` — an index-reset cascade across all active lines. This supersede operation is the one OCC-guarded write in the system: it requires `expected_indexrate_version` to match the target row's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on mismatch as described in §2.7. The supersede increments the superseded row's version by 1.

Index rates may be listed and filtered by `index_name` and by `superseded`.

### 3.3. Creating and Activating a Line

A `LoanOfficer` opens a line by creating a **HELOC application**, naming the obligor through `borrower_id` and the collateral through `property_id`. The application fixes the `lien_position` (either `FIRST` or `SECOND`), the committed `credit_limit_cents` (which must be at least 100000), the lender `margin_bps` added to PRIME to form the note rate (between 0 and 2000 inclusive), and the `rate_ceiling_bps`, a lifetime cap on the effective rate that must be at least 0. The officer may also supply `annual_fee_cents`, the fee charged on each draw-period anniversary (defaulting to 5000 when omitted, and at least 0); the `origination_date`, the ISO 8601 UTC instant the line opens and the anchor for every draw and repayment boundary; the `draw_period_years`, the length of the draw period (defaulting to 10, between 1 and 15 inclusive); and the `repayment_period_years`, the length of the amortizing repayment period that follows (defaulting to 20, between 1 and 30 inclusive).

A line's `status` begins at `APPLICATION` and progresses through `DRAW`, `REPAYMENT`, `FROZEN`, `DEFAULTED`, and the terminal `CLOSED`. At creation the computed monetary fields are all zero: `current_balance_cents`, `available_credit_cents`, `current_apr_bps`, `accrued_interest_cents`, `delinquency_days`, and `anniversary_count` all start at 0.

Activation moves the line from `APPLICATION` to `DRAW` and is performed by a `LoanOfficer`. Four preconditions must hold, each guarded by its own error. The borrower's `kyc_status` must be `CLEARED`, otherwise activation fails with `ERR_KYC_NOT_CLEARED` (HTTP 409). At least one covenant of each of the three types — `MAX_CLTV`, `MIN_DSCR`, and `MAX_DELINQUENCY_DAYS` — must already be attached to the line, otherwise the request fails with `ERR_COVENANT_SET_INCOMPLETE` (HTTP 409). An active, non-superseded PRIME index rate must exist, otherwise the request fails with `ERR_NO_ACTIVE_INDEX` (HTTP 409). And if the line is being recorded in `FIRST` position, the property's `senior_lien_balance_cents` must be exactly 0, otherwise the request fails with `ERR_LIEN_POSITION_CONFLICT` (HTTP 409). Finally, the loan-to-value computed at activation must not breach the line's `MAX_CLTV` covenant.

When activation succeeds, the line's `current_apr_bps` is set to the lesser of the active PRIME `rate_bps` plus the line's `margin_bps`, and the line's `rate_ceiling_bps`; the `available_credit_cents` is set to the full `credit_limit_cents` (the balance being 0); a **lien record** is created against `property_id` with its `position` mirroring the line's `lien_position` and its `status` set to `RECORDED`; the property's `status` is set to `ACTIVE`; and the line's version is incremented by 1. The identifier of the activating officer is retained on the line for the later segregation-of-duties check.

### 3.4. Drawing and Reversing Against the Line

Once a line is in `DRAW`, a `LoanServicer` may book a **draw** — a principal advance — against it by supplying the draw `amount_cents`, which must be at least 1. A draw is permitted only while the line's status is exactly `DRAW`; an attempt to draw against a line that is `FROZEN`, `REPAYMENT`, `DEFAULTED`, or otherwise not in `DRAW` is rejected with `ERR_DRAWS_NOT_PERMITTED` (HTTP 409). The requested amount must not exceed the line's `available_credit_cents`; an over-limit advance is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 422). Each draw records a system-stamped `requested_at` timestamp, which is the chronological anchor used by interest accrual, and a `status` of either `BOOKED` (on success) or `REVERSED` (if later voided), beginning at `BOOKED`. Booking a draw debits the line's `current_balance_cents` by the advance, recomputes `available_credit_cents`, accrues chronological interest up to the present, and increments the line's version by 1. Available credit is always recomputed as the credit limit minus the current balance, floored at 0.

A booked draw may be reversed by a `LoanServicer` as a compensating action, identified by the draw beneath its line. Reversal is permitted only when the draw's `status` is `BOOKED` and the line is in either `DRAW` or `FROZEN` status. It additionally requires that the line's `current_balance_cents` be at least the draw's `amount_cents`, so that the reversal cannot drive principal below zero; a reversal that would underflow the balance is rejected with `ERR_REVERSAL_UNDERFLOW` (HTTP 422). A successful reversal credits the line's `current_balance_cents` by the draw's `amount_cents` (compensating the original debit), recomputes `available_credit_cents` as the credit limit minus the current balance floored at 0, flips the draw's `status` to `REVERSED`, increments the line's version by 1, and increments the draw's version by 1. Draws of a line may be listed and filtered by `status`.

### 3.5. Variable-Rate Interest Accrual

Interest on a line is **variable**: the effective annual rate, `current_apr_bps`, is the lesser of the active PRIME `rate_bps` plus the line's `margin_bps`, and the line's `rate_ceiling_bps`. Reading a line recomputes `available_credit_cents` and `current_apr_bps` so that the returned figures are reconciled.

Interest accrues by **chronological daily replay**. The daily rate is the `current_apr_bps` divided by 10000 (to convert basis points to a fraction) and then divided by a day-count basis of 365. The system considers the ledger of `BOOKED` draws (reversed draws are excluded) together with the payments whose `posted_at` falls on or before the as-of instant, ordering all of these events chronologically by their event timestamp ascending, breaking ties by `created_at` ascending. Walking from one event to the next, the running principal is held constant across the gap, and the interest for that segment is the running principal in cents multiplied by the daily rate multiplied by the number of days elapsed in the segment, rounded half up to whole cents. A draw raises the running principal at its `requested_at`; a payment's interest portion reduces the outstanding accrued interest at its `posted_at`. The segment amounts are summed — each already rounded — to produce the accrued figure from the last-payment anchor up to the as-of clock, which is stored as `accrued_interest_cents`. This chronological replay is performed before the waterfall on every payment, and is also what the interest quote returns as of the current clock, reporting `accrued_interest_cents` together with the `as_of` instant it was computed for.

A **forward-projected payoff** quote is a deliberately different calculation. Given an optional future `as_of` instant, it projects accrual forward from now to that instant on the **current** running principal alone, assuming no intervening draws or payments — a single segment equal to `current_balance_cents` multiplied by the daily rate multiplied by the number of days from now to the as-of instant, rounded half up to whole cents. It does not re-walk the historical ledger; it estimates a future payoff rather than reconstructing the past. The payoff quote reports `payoff_cents`, `projected_interest_cents`, and the `as_of` instant. The contrast is intentional: the chronological quote reconstructs the historical accrual, while the payoff quote projects a single forward segment.

### 3.6. Posting Payments and the Allocation Waterfall

A payment may be posted by either a `LoanServicer` or the `Borrower` who owns the line, identified by the line being paid and supplying the total remittance `amount_cents`, which must be at least 1. Each payment records a system-stamped `posted_at` timestamp (the chronological anchor for accrual) and three computed allocation buckets: `fee_applied_cents`, `interest_applied_cents`, and `principal_applied_cents`, all beginning at 0.

Before allocation, the system accrues chronological interest up to the payment's `posted_at` as described in §3.5. The remittance is then allocated across three buckets in a **pinned order**: outstanding fees first, then accrued interest, then principal. Concretely, the amount available starts at the full `amount_cents`. The fee bucket is filled first: the total fee due is the sum of `amount_cents` across all fee assessments whose `settlement_status` is `OUTSTANDING`, taken oldest-first by `created_at` ascending; `fee_applied_cents` is the lesser of the amount available and that total fee due, and the available amount is reduced by it. Next the interest bucket: `interest_applied_cents` is the lesser of the remaining available amount and the current `accrued_interest_cents`, and the available amount is reduced by it. Finally the principal bucket: `principal_applied_cents` is the lesser of the remaining available amount and the current `current_balance_cents`, and the available amount is reduced by it. If any amount remains after principal, the payment is an overpayment and is rejected with `ERR_OVERPAYMENT` (HTTP 422) — the payment is not booked. Equivalently, the remittance must not exceed the sum of outstanding fees, accrued interest, and current principal. The three buckets always sum exactly to `amount_cents`; the allocation is exact integer-cents arithmetic with no rounding. Posting a payment settles fees as the fee bucket covers them, reduces `accrued_interest_cents` and `current_balance_cents` by their respective buckets, recomputes `available_credit_cents`, resets `delinquency_days` if the past-due obligation is cleared, and increments the line's version by 1. Payments of a line may be listed.

### 3.7. Annual Fees, the Anniversary Clock, and Delinquency

A line's billing clock is advanced by a `LoanServicer` to a supplied `to_iso8601` instant. (The separate administrative clock-setting capability also takes a `to_iso8601` instant and reports the resulting `current_utc`; advancing a line returns the updated line.) Advancing the clock assesses annual fees for each newly crossed in-draw anniversary, and recomputes `delinquency_days`, `anniversary_count`, and `accrued_interest_cents`.

The annual-fee logic works as follows. The number of elapsed anniversaries is the whole number of complete years between the `origination_date` and the clock — that is, the count of days between them divided by 365 and rounded down. For each anniversary index after the line's current `anniversary_count` up to and including the newly elapsed count, and only while that index does not exceed the `draw_period_years`, a **fee assessment** of type `ANNUAL` is created in `OUTSTANDING` status with `amount_cents` equal to the line's `annual_fee_cents`. The line's `anniversary_count` is then set to the lesser of the elapsed-anniversary count and the `draw_period_years`. Annual fees are therefore assessed only for anniversaries numbered 1 through `draw_period_years`.

Each fee assessment names the line through `heloc_id` and carries a computed `fee_type` (`ANNUAL` on anniversary, or `EARLY_CLOSURE` on premature closure), a computed `amount_cents`, and a computed `settlement_status` — `OUTSTANDING` until paid, `SETTLED` once the payment waterfall has cumulatively applied at least its `amount_cents` to it, or `WAIVED` when a covenant cure waives it. A fee assessment transitions from `OUTSTANDING` to `SETTLED` automatically once the cumulative `fee_applied_cents` across payments reaches or exceeds its `amount_cents`, incrementing its version by 1. Fee assessments of a line may be listed and filtered by `fee_type` and by `settlement_status`.

### 3.8. Covenants and the Default Triggers

Every line is governed by **covenants**, each encoding one default trigger. A `LoanOfficer` attaches a covenant to a line by naming the `covenant_type` (one of `MAX_CLTV`, `MIN_DSCR`, or `MAX_DELINQUENCY_DAYS`) and a `threshold_value` (the breakpoint, expressed as basis points for the loan-to-value and debt-service-coverage covenants — for example 8500 for 85.00% — or whole days for the delinquency covenant; at least 0). A covenant's `status` begins at `SATISFIED` and moves among `SATISFIED`, `BREACHED`, and `CURED`. A single covenant may be fetched directly, and the covenants of a line may be listed and filtered by `status`.

A `LoanServicer` evaluates a covenant to test whether its metric crosses the threshold. The metric depends on the type. For a `MAX_CLTV` covenant, the combined loan-to-value in basis points is the sum of the property's `senior_lien_balance_cents` and the line's `current_balance_cents`, multiplied by 10000, divided by the property's `appraised_value_cents`, rounded half up; the covenant is breached when this figure is strictly greater than the `threshold_value`. For a `MIN_DSCR` covenant, the annual debt service is the borrower's `monthly_debt_obligation_cents` multiplied by 12, plus the line's annual interest charge (the `current_balance_cents` multiplied by the line's `current_apr_bps` divided by 10000, rounded half up); the debt-service-coverage ratio in basis points is the borrower's `annual_income_cents` multiplied by 10000 and divided by that annual debt service (which is positive), rounded half up; the covenant is breached when this ratio is strictly less than the `threshold_value`. For a `MAX_DELINQUENCY_DAYS` covenant, the covenant is breached when the line's `delinquency_days` is strictly greater than the `threshold_value`.

Evaluating a covenant from `SATISFIED` to `BREACHED` requires that the covenant currently be `SATISFIED` and that its metric cross the threshold; on breach, if the line is in `DRAW` it is transitioned from `DRAW` to `FROZEN` (a covenant breach freezes the line), the observed metric is recorded for a later default event's `observed_value`, and the covenant's version is incremented by 1. A covenant that has previously been cured can re-breach: evaluating a covenant from `CURED` to `BREACHED` requires that it currently be `CURED` and that the metric cross the threshold again, and likewise freezes a line that is in `DRAW` and increments the covenant's version by 1. Evaluation of a covenant not in a state from which a breach transition is defined is rejected as an invalid state transition.

Curing a covenant is performed by a `LoanServicer` and moves it from `BREACHED` to `CURED`. It requires that the covenant currently be `BREACHED`, that its metric no longer cross the threshold per the formulas above, and that the line not be `DEFAULTED`. Curing waives any `OUTSTANDING` `ANNUAL` fee assessment created during the breach window, transitioning each such fee to `WAIVED`, and increments the covenant's version by 1.

### 3.9. Freezing, Unfreezing, and Converting

Beyond a covenant-driven freeze, a `LoanServicer` may impose an administrative **freeze** on a line that is in `DRAW` — for example while a property revaluation is pending — moving it from `DRAW` to `FROZEN`, setting `available_credit_cents` to 0 so that no further draws are possible, and incrementing the line's version by 1. A frozen line may be **unfrozen** back from `FROZEN` to `DRAW`, but only when no covenant of that line is currently `BREACHED`; unfreezing recomputes `available_credit_cents` as the credit limit minus the current balance floored at 0 and increments the line's version by 1. A freeze is thus reversible into either a cure (back to `DRAW`) or, ultimately, a default declaration.

When the draw period has elapsed, a `LoanServicer` **converts** the line from `DRAW` to `REPAYMENT`. Conversion requires that the line currently be in `DRAW` and that the logical clock be at or after the `origination_date` plus `draw_period_years`; an attempt to convert before the draw period has elapsed is rejected with `ERR_DRAW_PERIOD_NOT_ELAPSED` (HTTP 409). Conversion sets `available_credit_cents` to 0 (no further draws are allowed), freezes the amortization baseline at the current `current_balance_cents`, and increments the line's version by 1.

### 3.10. Declaring Default

A line that has breached a covenant may be declared in **default** by a `LoanServicer`, naming the breached `covenant_id`. Default may be declared from `DRAW`, `REPAYMENT`, or `FROZEN`, moving the line to `DEFAULTED`. Three conditions gate the declaration. The line must be in one of `DRAW`, `REPAYMENT`, or `FROZEN`. The referenced covenant must currently be `BREACHED` and must belong to this line; otherwise the declaration is rejected with `ERR_NO_BREACHED_COVENANT` (HTTP 409). And the acting servicer's `X-User-ID` must not equal the identifier of the officer who activated this line — enforcing segregation of duties — otherwise the declaration is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

A successful declaration creates an immutable `DefaultEvent` recording the line's `heloc_id`, the breached `covenant_id`, a `trigger_type` mirroring the covenant's `covenant_type` for the audit trail, the `observed_value` of the computed metric at declaration (the loan-to-value or debt-service-coverage in basis points, or the delinquency in days), and the `declared_by_user_id` capturing the acting servicer's `X-User-ID`. Declaration sets the line's `available_credit_cents` to 0, blocking all future draws as a cascade, and increments the line's version by 1. No early-closure fee is assessed on default, because default is not a borrower-initiated closure. Default events may be listed for a line, and may also be listed by the covenant that triggered them.

### 3.11. Closing the Line and Early-Closure Penalties

A `LoanServicer` **closes** a line that has been paid in full, moving it from either `DRAW` or `REPAYMENT` to the terminal `CLOSED`. Closure requires that the line be in `DRAW` or `REPAYMENT`, and that both `current_balance_cents` and `accrued_interest_cents` be exactly 0; a close attempt while either is non-zero is rejected with `ERR_BALANCE_NOT_ZERO` (HTTP 409).

If the line is closed from `DRAW` while the logical clock is before the `origination_date` plus `draw_period_years`, an **early-closure** penalty is assessed as a fee assessment of type `EARLY_CLOSURE`. The penalty is tiered on how early the closure is, measured in whole years remaining in the draw period: the years remaining is the number of days between the clock and the `origination_date` plus `draw_period_years`, divided by 365 and rounded up to a whole number. The tier rate, expressed in basis points of the `credit_limit_cents`, is 200 bps when at least 8 years remain, 100 bps when between 4 and 7 years inclusive remain, 50 bps when between 1 and 3 years inclusive remain, and 0 (no early-closure fee) when 0 years remain because the draw period has effectively elapsed. The fee is the `credit_limit_cents` multiplied by the tier rate in basis points, divided by 10000, rounded half up. A line closed from `REPAYMENT` never incurs an early-closure fee, because reaching the repayment period implies the draw period has already elapsed.

Closure is blocked while any fee assessment for the line — including an `EARLY_CLOSURE` fee just assessed by this very closure — is still `OUTSTANDING`; such a close is rejected with `ERR_FEES_OUTSTANDING` (HTTP 409). All fee assessments for the line must be settled, or be settled by this closure, for it to proceed. When closure succeeds, every covenant of the line is set to `CURED`, the line's `LienRecord` is set to `RELEASED`, the property's `status` is set to `RELEASED` if no other `RECORDED` lien record still references it, and the line's version is incremented by 1. A lien record names its line through `heloc_id` and its property through `property_id`, carries a computed `position` mirroring the line's `lien_position` at recording time, and a `status` of either `RECORDED` (when filed) or `RELEASED` (on closure). Lien records may be listed both for a property and for a line.

### 3.12. State-Transition Integrity

Across all of the above, a transition is permitted only from a state in which it is defined. An attempt to drive a transition from a state that does not define it — converting a line that is not in `DRAW`, freezing a line that is not in `DRAW`, unfreezing a line that is not `FROZEN`, closing a line that is neither `DRAW` nor `REPAYMENT`, reversing a draw that is not `BOOKED`, or evaluating or curing a covenant from a state that defines no such move — is rejected with `ERR_INVALID_STATE` (HTTP 409). Body field constraints (positive amounts, enum membership, the credit-score range, and the credit-limit floor) that are violated on any create or update with a body are rejected with `ERR_INVALID_REQUEST` (HTTP 422).

The order in which these checks fire matters when several could apply to one request. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path-referenced resources left-to-right (`ERR_NOT_FOUND`), then resolution of body foreign-key references (`ERR_REFERENCE_NOT_FOUND`), then the state-transition guard (`ERR_INVALID_STATE`). Only after these do the business-specific checks apply. For default declaration in particular, the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`) is evaluated before the breached-covenant check (`ERR_NO_BREACHED_COVENANT`). For activation, the body-level field constraints and the four business preconditions — `ERR_KYC_NOT_CLEARED`, `ERR_COVENANT_SET_INCOMPLETE`, `ERR_NO_ACTIVE_INDEX`, and `ERR_LIEN_POSITION_CONFLICT` — all sit below the generic checks above.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including the state-transition operations such as activation, freeze, conversion, default declaration, closure, draw reversal, and covenant evaluation or cure — return `200 OK`. The full request and response shape of each endpoint is reconstructed from the workflow narratives in §3; the table below lists only the route, its purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/borrowers` | Create a borrower | LoanOfficer |
| GET | `/borrowers/{id}` | Fetch a borrower | LoanOfficer, LoanServicer, Auditor |
| PATCH | `/borrowers/{id}` | Update borrower KYC status or financials | LoanOfficer |
| POST | `/properties` | Create a collateral property | LoanOfficer |
| GET | `/properties/{id}` | Fetch a property | LoanOfficer, LoanServicer, Auditor |
| PATCH | `/properties/{id}` | Update appraised value or senior lien balance | LoanOfficer, LoanServicer |
| GET | `/properties/{id}/lien-records` | List lien records against this property | LoanOfficer, LoanServicer, Auditor |
| POST | `/index-rates` | Publish a PRIME index value | LoanServicer |
| GET | `/index-rates/{id}` | Fetch an index rate | LoanServicer, LoanOfficer, Auditor |
| GET | `/index-rates` | List index rates (filter by index_name, superseded) | LoanServicer, LoanOfficer, Auditor |
| POST | `/index-rates/{id}/supersede` | Publish a newer PRIME value superseding this one (OCC-guarded) | LoanServicer |
| POST | `/helocs` | Create a HELOC application | LoanOfficer |
| GET | `/helocs/{id}` | Fetch a HELOC with computed fields reconciled | LoanOfficer, LoanServicer, Auditor |
| GET | `/helocs` | List HELOCs (filter by borrower_id, property_id, status) | LoanOfficer, LoanServicer, Auditor |
| POST | `/helocs/{id}/activate` | Activate APPLICATION → DRAW; record lien, set APR | LoanOfficer |
| POST | `/helocs/{id}/convert-to-repayment` | DRAW → REPAYMENT once draw period elapsed | LoanServicer |
| POST | `/helocs/{id}/freeze` | DRAW → FROZEN administrative freeze | LoanServicer |
| POST | `/helocs/{id}/unfreeze` | FROZEN → DRAW when no covenant is breached | LoanServicer |
| POST | `/helocs/{id}/declare-default` | Declare default on a breached line | LoanServicer |
| POST | `/helocs/{id}/close` | Close a paid-in-full line; may assess early-closure fee | LoanServicer |
| GET | `/helocs/{id}/payoff-quote` | Forward-projected payoff quote | LoanOfficer, LoanServicer, Auditor |
| GET | `/helocs/{id}/interest-quote` | Chronological accrued-interest quote | LoanOfficer, LoanServicer, Auditor |
| POST | `/helocs/{id}/draws` | Book a draw against available credit | LoanServicer |
| GET | `/helocs/{id}/draws` | List draws for a HELOC (filter by status) | LoanOfficer, LoanServicer, Auditor |
| POST | `/helocs/{id}/draws/{did}/reverse` | Reverse a booked draw | LoanServicer |
| POST | `/helocs/{id}/payments` | Post a payment; waterfall fee → interest → principal | LoanServicer, Borrower |
| GET | `/helocs/{id}/payments` | List payments for a HELOC | LoanOfficer, LoanServicer, Auditor, Borrower |
| POST | `/helocs/{id}/covenants` | Attach a covenant to a HELOC | LoanOfficer |
| GET | `/helocs/{id}/covenants` | List covenants for a HELOC (filter by status) | LoanOfficer, LoanServicer, Auditor |
| GET | `/covenants/{id}` | Fetch a single covenant | LoanOfficer, LoanServicer, Auditor |
| POST | `/helocs/{id}/covenants/{cid}/evaluate` | Evaluate a covenant; may breach and freeze line | LoanServicer |
| POST | `/helocs/{id}/covenants/{cid}/cure` | Cure a breached covenant; waive in-window annual fee | LoanServicer |
| GET | `/helocs/{id}/default-events` | List default events for a HELOC | LoanServicer, Auditor |
| GET | `/helocs/{id}/fee-assessments` | List fee assessments (filter by fee_type, settlement_status) | LoanOfficer, LoanServicer, Auditor, Borrower |
| GET | `/helocs/{id}/lien-records` | List lien records for a HELOC | LoanOfficer, LoanServicer, Auditor |
| GET | `/covenants/{id}/default-events` | List default events triggered by this covenant | LoanServicer, Auditor |
| POST | `/_clock/set_current_utc` | Set the system clock for deterministic temporal tests | LoanServicer, LoanOfficer |
| POST | `/helocs/{id}/advance-clock` | Advance the line's billing clock; assess annual fees | LoanServicer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_BREACHED_COVENANT` | 409 |
| `ERR_KYC_NOT_CLEARED` | 409 |
| `ERR_COVENANT_SET_INCOMPLETE` | 409 |
| `ERR_NO_ACTIVE_INDEX` | 409 |
| `ERR_LIEN_POSITION_CONFLICT` | 409 |
| `ERR_DRAW_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_DRAWS_NOT_PERMITTED` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_BALANCE_NOT_ZERO` | 409 |
| `ERR_FEES_OUTSTANDING` | 409 |
| `ERR_REVERSAL_UNDERFLOW` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
