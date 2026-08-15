# Corporate Income Tax Provision API — Product Requirements Document

## 1. Introduction

The corporate tax department lives inside a compressed calendar: every fiscal year, the provision team must reconcile GAAP book income to taxable income, measure deferred taxes, assess valuation allowances, reserve for uncertain positions, compute and defend an effective tax rate, schedule estimated payments across jurisdictions, file returns, and survive audits — all under segregation-of-duties controls that external auditors scrutinize line by line. Today this work sprawls across spreadsheets whose provenance cannot be reconstructed, and quarter-end close depends on individuals remembering which version of which schedule was the one that went into the 10-Q.

This document specifies a REST API that systematizes that lifecycle. The API tracks a fiscal **TaxYear** from `OPEN` through `PROVISION_LOCKED`, `RETURNS_FILED`, and `CLOSED`; maintains the book-to-tax difference population and the deferred tax rollforward it feeds; governs valuation allowance assessments with a strict preparer/approver split; measures and discloses uncertain tax positions; generates quarterly estimated payment schedules under either the prior-year safe-harbor or the current-year annualized method; manages filings and extensions per jurisdiction; and drives notice response and audit case work through to closure. A logical clock under test-harness control triggers the sweeps that mark payments late, notices overdue, and statutes of limitation lapsed.

The design treats derived state as a first-class concern: effective tax rates, deferred balances, UTP reserves, and return-to-provision adjustments are recomputed eagerly as source records mutate, so any read reflects the provision as it stands at that moment. Optimistic concurrency on the tax year's `version` protects the two write paths whose cascades would otherwise silently overwrite a colleague's work.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string that is not one of the declared roles, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). An empty or whitespace-only header value counts as missing. A request whose role is declared but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The declared roles, spelled exactly, are: `TaxAccountant`, `TaxManager`, `TaxDirector`, `Auditor`, and `PlatformAdmin`.

- A `TaxAccountant` is the staff tax accountant: identifies book-to-tax differences and uncertain tax positions, logs notices, opens filings, prepares returns, and records estimated payments.
- A `TaxManager` reviews and locks differences, prepares valuation allowance assessments, measures, discloses, and settles uncertain tax positions, schedules payments, responds to notices, and runs audit cases.
- A `TaxDirector` locks the provision, files returns, approves valuation allowances (subject to the segregation-of-duties rule), resolves extensions, and closes the year.
- An `Auditor` has read-only access to every resource and no write operations.
- A `PlatformAdmin` is a test-harness operator controlling only the logical clock; it has no business-surface access.

For all five roles, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `BookTaxDifference`, `reviewed_by_user_id` on a reviewed difference, `prepared_by_user_id` on a `ValuationAllowance`, or `approved_by_user_id` on an approved assessment — but it never compares `X-User-ID` to any entity's `id`. The single place where the identifier's value matters is segregation of duties on valuation allowance approval, where the approver's `X-User-ID` is compared against the preparer's recorded identifier.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range values are clamped into range (limit into 1–100, offset to at least 0), and unparseable values fall back to the defaults. List responses order by `created_at` ascending, with ties keeping creation order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Resource Identity and Common Properties

Every resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp of the same format refreshed on every mutation, and a `version` integer that starts at 1 and increments on mutation. The `TaxYear`'s `version` is load-bearing beyond bookkeeping: it anchors the optimistic concurrency rules described in §2.8.

Date fields throughout the API (`period_start_date`, `period_end_date`, `original_due_date`, `due_date`, `received_on`, `response_due_on`, `measured_on`, `filed_on`, `opened_on`, `exam_period_start`, `exam_period_end`, `extended_due_date`, `settled_amount_cents`'s companions, and the like) are ISO 8601 `YYYY-MM-DD` strings. Every date-valued rule compares against the **date portion** of the logical clock. Calendrical arithmetic on these dates is pinned: adding months clamps the day to the target month's last day (January 31 plus one month is February 28 or 29), and adding years maps February 29 to February 28 in a non-leap target year.

Monetary amounts are integer cents everywhere — fields ending in `_cents` — and rates and percentages are integer basis points (fields ending in `_bp` or `_pct_bp`), so 21.00% is expressed as 2100 basis points and 100% as 10000.

### 2.5. Precision and Rounding

All money arithmetic produces integer cents. Wherever a calculation involves a fractional product, exactly one **round half up** is applied at the step the relevant rule names — no intermediate rounding, no double rounding. Effective tax rates are integer basis points, again with a single round half up at the final division. Threshold comparisons are exact: the UTP recognition threshold uses a strictly-greater-than comparison, and the late-payment sweep condition is strict, so an exactly-fully-paid quarter owes zero penalty.

### 2.6. Validation Priority Order

When a single request violates more than one rule, the lowest priority number wins and determines the response's `error_id`. The order is fixed:

1. **Authentication context** — `X-User-Role` and `X-User-ID` present and the role declared (`ERR_MISSING_AUTH_CONTEXT`).
2. **Authorization** — the caller's role is listed for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence** — path identifiers exist, validated left to right, and body foreign-key references (`tax_year_id`, `jurisdiction_id`, `audit_case_id`) resolve to existing resources (`ERR_NOT_FOUND`).
4. **State transition legality** — the target entity is in a state from which the requested transition exists; recording a payment on an already-`PAID` quarter surfaces `ERR_PAYMENT_ALREADY_SETTLED`, and every other illegal transition surfaces `ERR_INVALID_STATE_TRANSITION`.
5. **Tax-year posture** — creating differences, filings, or valuation allowances, and the difference and valuation-allowance lifecycle actions, require the year to be `OPEN` (`ERR_TAX_YEAR_NOT_OPEN`); marking a filing ready and filing it require `PROVISION_LOCKED` or later but never `CLOSED` — filing admits exactly `PROVISION_LOCKED` or `RETURNS_FILED`, and §3.7 pins the mark-ready posture per filing state (`ERR_TAX_YEAR_NOT_LOCKED`).
6. **Segregation of duties** — the valuation allowance approver must not be its preparer (`ERR_SEGREGATION_OF_DUTIES`).
7. **Uniqueness and interval constraints** — duplicate jurisdiction codes, duplicate quarters, audit period overlaps, quarter interval overlaps and gaps (see §2.9).
8. **Deadline discipline and date-range sanity** — extension window missed (`ERR_EXTENSION_WINDOW_MISSED`), filing deadline passed (`ERR_FILING_DEADLINE_PASSED`), and malformed date ranges (`ERR_DATE_RANGE_INVALID`).
9. **Cross-entity readiness** — lock-provision's unresolved items (`ERR_UNRESOLVED_PROVISION_ITEMS`), unfiled returns at mark-returns-filed (`ERR_UNFILED_RETURNS`), undisclosed UTPs at file time (`ERR_UTP_UNDISCLOSED`), the return-not-ready gate on disclosure (`ERR_RETURN_NOT_READY`), and unresolved notices at audit close (`ERR_UNRESOLVED_NOTICES`).
10. **Amount sanity** — monetary inputs positive or nonnegative where each rule requires (`ERR_INVALID_AMOUNT`), record-payment not exceeding the scheduled amount (`ERR_OVERPAYMENT`), and probability inputs within range (`ERR_PROBABILITY_OUT_OF_RANGE`).
11. **Structural well-formedness** — required fields present, enum values valid, integer types correct (`ERR_INVALID_REQUEST`). This check is deliberately last: a structurally malformed but authenticated request against a valid resource still reports domain errors first when both apply. Undeclared extra fields in a request body are ignored, never rejected.

### 2.7. The Logical Clock and Its Sweeps

The server runs on a logical clock whose startup default is exactly 2026-08-01T00:00:00Z; the clock never falls back to wall-clock time. A `PlatformAdmin`-only capability advances the clock by setting it to a supplied `to_iso8601` instant, and the sweep side effects described below run synchronously inside that request. The clock may be set to any well-formed instant — including one earlier than its current value; a missing or malformed `to_iso8601` is `ERR_INVALID_REQUEST`. The logical clock governs business dates and date-valued rules only: `created_at`, `updated_at`, and `api_request_timestamp` remain server wall-clock timestamps. The response reports the new `current_utc` together with the lists `late_payment_ids`, `overdue_notice_ids`, and `lapsed_position_ids` naming every entity the sweeps transitioned, each list in creation order.

Three sweeps run on each advance:

- **Estimated payments**: any quarter in `SCHEDULED` or `PARTIALLY_PAID` whose `due_date` has passed and whose `paid_amount_cents` is strictly less than `scheduled_amount_cents` transitions to `LATE` and is assessed its one-time penalty (§3.5).
- **Notices**: any notice in `RECEIVED` or `UNDER_REVIEW` whose `response_due_on` has passed transitions to `OVERDUE`.
- **Uncertain tax positions**: any position in `DISCLOSED` lapses to `LAPSED` once the clock date is more than three years past the `filed_on` date of the `FILED` or `ACCEPTED` filing sharing its `tax_year_id` and `jurisdiction_id` (when several such filings exist, the latest `filed_on` governs); lapsing recomputes the year's `utp_liability_cents` and `forecast_etr_bp`.

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints take an optimistic-concurrency field, both keyed on the parent `TaxYear`'s `version`:

- **Creating a valuation allowance** requires the request to carry `expected_tax_year_version` matching the target year's current `version`. Creating legitimately supersedes any existing `DRAFT` or `SUBMITTED` assessment for the year, so a writer working from a stale year view would silently supersede an assessment it never saw; the stale-version check forces a re-read first. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Filing a return** requires the request to carry `expected_tax_year_version` matching the parent year's current `version`. Filing legitimately recomputes the return-to-provision adjustment and re-spreads remaining estimated payments, so a filer working from a stale year view would compute downstream amounts from superseded inputs; the stale-version check forces a re-read first. A mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here take no version field. The stale-version check is evaluated immediately after the tax-year posture check (§2.6 item 5) and before the deadline, cross-entity readiness, amount, and structural checks; an `expected_tax_year_version` that is missing or not an integer is a structural `ERR_INVALID_REQUEST`.

### 2.9. Interval Semantics for Quarters and Audit Periods

Quarter intervals on estimated payments use **closed-interval** semantics: both `period_start_date` and `period_end_date` are inclusive. Two manual quarters of the same `tax_year_id` and `jurisdiction_id` pair may not overlap, and because the intervals are closed, a new quarter whose start equals an existing quarter's end collides (`ERR_QUARTER_OVERLAP`). Manual quarters must also be exactly contiguous with no gaps: quarter 1 must start on the tax year's `period_start_date`, and any quarter with `quarter_index` greater than 1 must start the day after the highest existing quarter's `period_end_date` for the pair (`ERR_QUARTER_GAP`) — creating the pair's first quarter with a `quarter_index` greater than 1 is likewise a gap error.

Audit examination periods use **half-open** semantics: `exam_period_start` is inclusive and `exam_period_end` is exclusive, so a new audit whose start equals an existing non-closed audit's end for the same jurisdiction is legal adjacency, while any true intersection is rejected with `ERR_AUDIT_PERIOD_OVERLAP`.

### 2.10. Cascades, Freezing, and the Year Lifecycle

Derived fields on `TaxYear` are recomputed eagerly, atomically within the triggering request. `current_provision_cents` is continuously maintained while the year is `OPEN` — recomputed on filing creation, difference lock or reject, and jurisdiction creation — and freezes at lock-provision, which also copies the per-jurisdiction components onto each filing's `estimated_liability_cents`. `deferred_expense_cents`, `net_deferred_asset_cents`, `valuation_allowance_cents`, `utp_liability_cents`, `return_to_provision_adjustment_cents`, `forecast_etr_bp`, and `actual_etr_bp` recompute as their source records mutate, per the rules in §3. Rejected differences never produce deferred tax items and never enter any calculation's input set. Once the year leaves `OPEN`, writes that the posture rule (§2.6, item 5) gates on `OPEN` are rejected, which is what makes the frozen provision trustworthy.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Year: Tax Years and Jurisdictions

A `TaxManager` or `TaxDirector` opens the cycle by creating a `TaxYear` with a `fiscal_year_label` (for example, "FY2026"; no uniqueness is enforced on the label), the `period_start_date` and `period_end_date` bracketing the fiscal year, the `enacted_federal_rate_bp` statutory federal rate in basis points, and `pretax_book_income_cents`, which must be greater than zero — this guard means later rate divisions are always safe. `prior_year_total_tax_cents`, the prior year's consolidated actual tax, is optional and defaults to 0; it is the basis for safe-harbor estimated payments. The end date must be after the start date, otherwise the create is rejected with `ERR_DATE_RANGE_INVALID`. A new year starts in status `OPEN` with every computed money field and both ETR fields at 0.

Jurisdictions are reference data, likewise creatable by `TaxManager` or `TaxDirector`. Each carries a unique `code` such as `US-FED` or `US-CA` (a duplicate code is rejected with `ERR_DUPLICATE_JURISDICTION_CODE`), a display `name`, a `level` of `FEDERAL`, `STATE`, or `FOREIGN`, a `statutory_rate_bp` between 0 and 10000, and an `apportionment_pct_bp` between 0 and 10000 expressing the share of book income apportioned to it. The statutory return due date is captured as `return_due_month` (1 through 12) and `return_due_day` (1 through 31) of the year after period end, and `extension_months` — defaulting to 6 — is the number of months an extension adds to the original due date. A value outside any of these declared ranges is a structural `ERR_INVALID_REQUEST`.

### 3.2. Book-to-Tax Differences and the Deferred Tax Rollforward

A `TaxAccountant` identifies a book-to-tax difference against an `OPEN` year by supplying `tax_year_id`, an optional `jurisdiction_id` (book-level differences may be jurisdiction-agnostic), a free-text `description`, the `book_amount_cents` (positive for expense, negative for income recognized in books), the `tax_amount_cents` (positive for deduction, negative for income recognized for tax), and a `difference_type` of `TEMPORARY` or `PERMANENT`. The server computes `difference_cents` as `book_amount_cents` minus `tax_amount_cents` — an exact integer subtraction, no rounding — where a positive value means book expense exceeds the tax deduction: an unfavorable addback now that becomes a future deduction later, hence an asset when temporary. The new record lands in status `IDENTIFIED`, with `created_by_user_id` captured from the caller's `X-User-ID`.

Review is a `TaxManager` motion. Reviewing an `IDENTIFIED` difference moves it to `REVIEWED` and records `reviewed_by_user_id` from the caller's header; every lifecycle action on a difference requires the parent year to still be `OPEN`, else `ERR_TAX_YEAR_NOT_OPEN`. A reviewed difference has three exits. Returning it for rework cycles it back to `IDENTIFIED` and clears `reviewed_by_user_id` to null. Rejecting it moves it to `REJECTED`, terminal: rejected differences never produce deferred items and never enter any calculation input set. Locking it — a motion shared by `TaxManager` and `TaxDirector` — moves it to `LOCKED` and fires the deferred-tax cascade.

The cascade runs in hops, all within the locking request. Hop 1: when the locked difference is `TEMPORARY` with a nonzero `difference_cents`, the server upserts a `DeferredTaxItem` whose `source_difference_id` points back to the difference — `item_kind` is `ASSET` when `difference_cents` is positive (a future deduction) and `LIABILITY` when negative; `movement_cents` is the absolute value of `difference_cents` multiplied by the parent year's `enacted_federal_rate_bp` and divided by 10000, rounded half up exactly once to integer cents, always a nonnegative magnitude; and `closing_balance_cents` is the item's `opening_balance_cents` plus `movement_cents`. The `opening_balance_cents` (defaulting to 0) is the prior-year closing balance carried into the line, and the rollforward invariant opening plus movement equals closing holds always. A `TEMPORARY` difference whose `difference_cents` is exactly zero produces no item at all, and `PERMANENT` differences never do. Hop 2: the parent year's `deferred_expense_cents` — the sum of `LIABILITY` movements minus the sum of `ASSET` movements across the year's items, negative meaning a net benefit — and `net_deferred_asset_cents` — the sum of `ASSET` closing balances minus the sum of `LIABILITY` closing balances, gross before any valuation allowance — recompute. Hop 3a: `forecast_etr_bp` recomputes, since the forecast variant consumes `deferred_expense_cents`. Hop 3b: if the year has a valuation allowance assessment in `DRAFT` or `SUBMITTED`, its `allowance_amount_cents` recomputes against the updated deferred-asset pool (§3.3). Deferred tax items are system-generated and read-only; they are listed and fetched, with filters on `tax_year_id`, `source_difference_id`, and `item_kind`, but never written directly.

### 3.3. Valuation Allowance Assessment

A `TaxManager` prepares a valuation allowance for an `OPEN` year by supplying `tax_year_id`, the `more_likely_than_not` conclusion (whether some deferred tax asset is more likely than not realizable), `projected_taxable_income_cents` and `reversing_dtl_cents` — both nonnegative, the positive-evidence income sources (a negative value is `ERR_INVALID_AMOUNT`) — and an optional `assessment_note` narrative. The request must also carry `expected_tax_year_version` per §2.8. The server computes `allowance_amount_cents` immediately: it takes the total gross deferred tax asset — the sum of `closing_balance_cents` across the year's `ASSET` deferred items — and, if `more_likely_than_not` is false, sets the allowance equal to that total gross asset (a full allowance). If `more_likely_than_not` is true, it computes an income-support figure by multiplying `projected_taxable_income_cents` by the year's `enacted_federal_rate_bp`, dividing by 10000, and rounding half up to integer cents; the realizable amount is the smaller of the total gross deferred tax asset and the sum of `reversing_dtl_cents` plus the income support; the allowance is then the total gross deferred tax asset minus the realizable amount, floored at zero. The creator's header value lands in `prepared_by_user_id`; `approved_by_user_id` stays null until approval.

Creating an assessment supersedes any existing `DRAFT` or `SUBMITTED` assessment for the same year — those move to `SUPERSEDED` — and bumps the parent year's `version`. An `APPROVED` assessment is never superseded by a bare create; only a subsequent approval displaces it.

The review loop is short: the preparer submits a `DRAFT` (moving it to `SUBMITTED`, again only while the year is `OPEN`), and a `TaxDirector` either returns it — cycling `SUBMITTED` back to `DRAFT` with no precondition beyond the §2.6 item 5 requirement that the year still be `OPEN` — or approves it. Approval enforces segregation of duties: the approving `X-User-ID` must differ from the recorded `prepared_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the year must still be `OPEN`. On approval, any other `APPROVED` assessment for the same year transitions to `SUPERSEDED`; the year's `valuation_allowance_cents` becomes the newly approved `allowance_amount_cents` (0 whenever no assessment is `APPROVED`); `forecast_etr_bp` recomputes; and the year's `version` increments. While an assessment sits in `DRAFT` or `SUBMITTED`, every deferred-item upsert recomputes its `allowance_amount_cents` against the live pool; once `APPROVED`, the amount is frozen.

### 3.4. Uncertain Tax Positions: Measure, Disclose, Settle, Lapse

A `TaxAccountant` identifies an uncertain tax position with `tax_year_id`, `jurisdiction_id`, a `description` of the position taken on the return, and `position_amount_cents`, the tax benefit claimed, which must be positive (`ERR_INVALID_AMOUNT` otherwise). Unlike the other artifacts, positions may be identified while the year is `OPEN`, `PROVISION_LOCKED`, or `RETURNS_FILED`; identifying one once the year is `CLOSED` is rejected with `ERR_TAX_YEAR_NOT_OPEN`. The new position is `IDENTIFIED`, starting with `recognized_benefit_cents` and `liability_cents` 0, `disclosure_required` false, `interest_accrued_cents` 0, and `cumulative_probability_bp`, `measured_on`, and `settled_amount_cents` null.

Measurement is a `TaxManager` action carrying `cumulative_probability_bp` — the cumulative probability that the full benefit is sustained, in basis points, which must lie between 0 and 10000 inclusive or the request is rejected with `ERR_PROBABILITY_OUT_OF_RANGE`. Recognition uses a strict threshold: when `cumulative_probability_bp` is strictly greater than 5000, `recognized_benefit_cents` equals the full `position_amount_cents`; at exactly 5000 or below, nothing is recognized. `liability_cents` — the unrecognized tax benefit reserve — is `position_amount_cents` minus `recognized_benefit_cents`, and `disclosure_required` is true exactly when `liability_cents` is greater than zero. The clock date is stamped into `measured_on`. Measurement from `IDENTIFIED` moves the position to `MEASURED`, and re-measurement is a self-loop `MEASURED → MEASURED` that recomputes the same outputs and refreshes `measured_on`; both forms recompute the parent year's `utp_liability_cents` — the sum of `liability_cents` across the year's positions in `MEASURED` or `DISCLOSED` — and `forecast_etr_bp`, and both increment the year's `version`.

Interest accrues on the unrecognized benefit: `interest_accrued_cents` is `liability_cents` multiplied by 500 basis points per annum (5%), divided by 10000, scaled by the number of whole calendar months from `measured_on` to the clock date (floored, never below zero) divided by 12, with a single round half up applied to the final product. A whole month is counted only once the clock date reaches the monthly anniversary of `measured_on` (so 2026-08-01 to 2026-12-15 is four whole months); interest is zero before the first measurement and whenever `liability_cents` is zero. The accrual is a pure function of `liability_cents`, `measured_on`, and the clock date, so it applies unchanged after settlement or lapse — those transitions do not clear `liability_cents`. Interest is recomputed on every read and every mutation.

Disclosure moves a `MEASURED` position to `DISCLOSED`, but only when a filing exists for the same `tax_year_id` and `jurisdiction_id` in `READY`, `FILED`, or `ACCEPTED` — a cross-aggregate gate that rejects with `ERR_RETURN_NOT_READY` otherwise. From `DISCLOSED`, a `TaxManager` settles the position by supplying `settled_amount_cents` (nonnegative; a negative value is `ERR_INVALID_AMOUNT`), moving it to `SETTLED` and releasing the reserve: settled positions drop out of `utp_liability_cents`, `forecast_etr_bp` recomputes, and the year's `version` increments. Alternatively, the clock sweep lapses a `DISCLOSED` position once the clock date passes the third anniversary of the `filed_on` date of the `FILED` or `ACCEPTED` filing sharing its year and jurisdiction — `LAPSED` positions likewise drop out of the reserve and trigger the same recompute and version bump. `SETTLED` and `LAPSED` are terminal.

### 3.5. Estimated Payments: Scheduling, Paying, Penalties

Estimated payments exist per quarter, per `tax_year_id` and `jurisdiction_id` pair, with `quarter_index` running 1 through 4 and unique within the pair (a duplicate is `ERR_DUPLICATE_QUARTER`). There are two creation paths.

**Generated schedules.** A `TaxManager` requests a full four-quarter schedule for a pair by supplying `tax_year_id`, `jurisdiction_id`, and a `method` of `PRIOR_YEAR_SAFE_HARBOR` or `CURRENT_YEAR_ANNUALIZED`. Generation requires zero existing payments for the pair — `ERR_DUPLICATE_QUARTER` otherwise. The four quarters tile the fiscal year in three-month intervals starting at `period_start_date`, each with `due_date` set 15 days after its `period_end_date`. The annual estimate depends on the method: under `PRIOR_YEAR_SAFE_HARBOR`, it is the year's `prior_year_total_tax_cents` multiplied by the jurisdiction's `apportionment_pct_bp` divided by 10000, then multiplied by 10000 basis points (100% of prior-year tax) divided by 10000, rounded half up to integer cents — a conservative fixed obligation that is immune to later re-spreads. Under `CURRENT_YEAR_ANNUALIZED`, it is `pretax_book_income_cents` multiplied by `apportionment_pct_bp` divided by 10000, then multiplied by `statutory_rate_bp` divided by 10000, rounded half up — the pay-as-you-go view. The per-quarter amounts follow a pinned rounding order: working in ascending `quarter_index`, each quarter's cumulative target is the annual estimate times the quarter number divided by 4, kept as an exact unrounded rational; each quarter's `base_scheduled_amount_cents` is the cumulative target minus the sum of the previously assigned quarters, rounded half up. Each quarter is therefore rounded against the exact cumulative target — never a quarter of the annual estimate rounded four times, since the two orders diverge by cents. All four are created in `SCHEDULED` with `paid_amount_cents` 0 and `penalty_cents` 0. Generation returns HTTP 201 with `response_type` "array", the four created payments in `data` in ascending `quarter_index`, and no pagination fields in `meta`.

**Manual creation.** A `TaxManager` may instead create a single quarter with a client-supplied `scheduled_amount_cents`, along with `quarter_index`, `period_start_date`, `period_end_date`, `due_date`, and `method`; the supplied amount also becomes the immutable `base_scheduled_amount_cents` anchor. Manual creation enforces quarter uniqueness, closed-interval non-overlap, and exact contiguity per §2.9; a `quarter_index` outside 1 through 4 is a structural `ERR_INVALID_REQUEST`, a negative `scheduled_amount_cents` is `ERR_INVALID_AMOUNT`, and a `due_date` earlier than `period_start_date` is a date-range error (`ERR_DATE_RANGE_INVALID`) — a `due_date` after `period_end_date` is permitted, just as generated schedules place it 15 days past the period end.

Recording payments is a `TaxAccountant` action carrying `amount_cents`, added to `paid_amount_cents`. From `SCHEDULED` or `PARTIALLY_PAID`, a payment that brings the paid total exactly to `scheduled_amount_cents` transitions the quarter to `PAID`; a payment that lands strictly between zero and the remaining balance transitions a `SCHEDULED` quarter to `PARTIALLY_PAID` and keeps a `PARTIALLY_PAID` quarter `PARTIALLY_PAID`. From `LATE`, only a payment bringing the paid total exactly to `scheduled_amount_cents` is accepted (completing the quarter to `PAID`); a smaller payment from `LATE` is rejected with `ERR_INVALID_STATE_TRANSITION`. A payment that would push the paid total above the scheduled amount is rejected with `ERR_OVERPAYMENT`, a non-positive amount with `ERR_INVALID_AMOUNT`, and any record-payment attempt on an already-`PAID` quarter with `ERR_PAYMENT_ALREADY_SETTLED` rather than the generic state error.

Reversing a payment is a `TaxManager` compensating action, also carrying `amount_cents`, subtracted from `paid_amount_cents`. No reversal is defined from `SCHEDULED` (`ERR_INVALID_STATE_TRANSITION`). From `PARTIALLY_PAID`, the reversal amount must be positive and no more than the paid total (`ERR_INVALID_AMOUNT` otherwise); when the paid total returns to zero the quarter returns to `SCHEDULED`. From `PAID`, the amount must be positive and strictly less than the paid total, landing the quarter in `PARTIALLY_PAID`. From `LATE`, the amount must be positive and no more than the paid total; the penalty already assessed is never refunded, a reversal that leaves a positive paid balance moves the quarter to `PARTIALLY_PAID`, and when the paid total returns to zero the quarter stays `LATE` — status `LATE` with zero paid — until the next sweep re-evaluates it. The record/reverse pair conserves `paid_amount_cents` across the two motions.

The lateness sweep is the only path into `LATE`: when the clock date passes `due_date` and `paid_amount_cents` is strictly less than `scheduled_amount_cents`, the quarter transitions to `LATE` and is assessed, exactly once, `penalty_cents` equal to the shortfall (`scheduled_amount_cents` minus `paid_amount_cents`) multiplied by 400 basis points (4%) and divided by 10000, rounded half up to integer cents. Because the sweep's condition is strict, a quarter paid to exactly its scheduled amount is `PAID` and never enters `LATE`; a penalty once assessed is never refunded, even by later payments or reversals — from `LATE`, recording the exact remaining balance still completes the quarter to `PAID` with `penalty_cents` untouched.

### 3.6. The Current Tax Stack and Effective Tax Rate Reconciliation

Two cross-cutting calculations ride on the year's records and are worth stating before the filing workflow that depends on them.

**Current tax stack.** While the year is `OPEN`, `current_provision_cents` is continuously maintained — recomputed on filing creation, difference lock or reject, and jurisdiction creation — and it is 0 whenever the year has no filings at all. The evaluation order is pinned because state tax is federally deductible, which makes the dependency look circular; the server resolves it by fixed sequence. First, `perm_total` is the sum of `difference_cents` across the year's `LOCKED` differences of `PERMANENT` type. Second, for each jurisdiction of `level` `STATE` or `FOREIGN` that has at least one filing in the year, the state component is the sum of `pretax_book_income_cents` and `perm_total`, multiplied by that jurisdiction's `apportionment_pct_bp` and by its `statutory_rate_bp`, divided by 100 million (10^8), rounded half up exactly once after the full product — no intermediate rounding. Third, the federal base is `pretax_book_income_cents` plus `perm_total` minus the sum of all state components. Fourth, when a `FEDERAL` jurisdiction has at least one filing in the year, the federal component is the federal base multiplied by `enacted_federal_rate_bp` and divided by 10000, rounded half up once after the deduction, and the component is attributed to every `FEDERAL` jurisdiction holding a filing in the year; otherwise the federal component is 0. Fifth, `current_provision_cents` is the sum of all state components plus the federal component — and jurisdictions with no filing in the year contribute nothing (an empty filing set yields 0).

**Effective tax rates.** Both rates are integer basis points with a single round half up at the final division, and both are recomputed on every difference lock, valuation allowance approval or recompute, position measure, settle or lapse, and filing file or reject. The forecast variant — the in-year planning view, always maintained — sets forecast total tax to `current_provision_cents` plus `deferred_expense_cents` plus `utp_liability_cents` plus `valuation_allowance_cents`, then `forecast_etr_bp` is that total multiplied by 10000 and divided by `pretax_book_income_cents`, rounded half up. The actual variant — the as-filed view, meaningful once filings exist — replaces the current-provision estimate and the UTP reserve with the sum of `return_tax_liability_cents` across the year's filings in `FILED` or `ACCEPTED`: actual total tax is that sum plus `deferred_expense_cents` plus `valuation_allowance_cents`, and `actual_etr_bp` is that total multiplied by 10000 and divided by `pretax_book_income_cents`, rounded half up. Identical underlying data yields a different rate whenever filed liabilities diverge from the estimate and reserve. Because `pretax_book_income_cents` is validated positive at creation, both divisions are always safe.

### 3.7. Filings, Extensions, and Return-to-Provision True-Up

A `TaxAccountant` opens a filing slot for a `tax_year_id` and `jurisdiction_id` pair while the year is `OPEN`, supplying the statutory `original_due_date`. Nothing enforces one slot per pair — multiple filings may be opened for the same `tax_year_id` and `jurisdiction_id`. The filing starts in status `PENDING` with `extension_status` `NONE`, `return_tax_liability_cents` null, and `is_late` false; its jurisdiction thereby enters the current-tax-stack input set and `current_provision_cents` recomputes. `estimated_liability_cents` stays 0 until lock-provision assigns the per-jurisdiction estimate from the stack. `filed_on` and `extended_due_date` are null until their respective events.

Filings carry **two parallel state dimensions** on one row: `status` (the lifecycle) and `extension_status` (`NONE`, `REQUESTED`, `GRANTED`, `DENIED`). Extension motions are legal only while `status` is `PENDING` or `READY`, and they never change `status`. A `TaxAccountant` requests an extension on or before `original_due_date` — after it, `ERR_EXTENSION_WINDOW_MISSED` — provided `extension_status` is still `NONE`, moving it to `REQUESTED`. A `TaxDirector` then resolves the request with a `decision` of `GRANTED` or `DENIED`; `extension_status` becomes the decision, and when granted, `extended_due_date` is computed by adding the jurisdiction's `extension_months` to `original_due_date`.

Marking a filing ready is a `TaxAccountant` motion attaching `return_tax_liability_cents`, which must be positive (`ERR_INVALID_AMOUNT`). From `PENDING`, the parent year must be `PROVISION_LOCKED`, otherwise `ERR_TAX_YEAR_NOT_LOCKED`. From `AMENDED` — the re-entry that completes the reject/amend/refile cycle — the parent year may be `PROVISION_LOCKED` or `RETURNS_FILED`. Both forms land in `READY`.

Filing is a `TaxDirector` motion carrying `expected_tax_year_version` (§2.8) and guarded by three checks: the OCC version match, a deadline check against the effective due date — `extended_due_date` when the extension is `GRANTED`, else `original_due_date` — past which filing is rejected with `ERR_FILING_DEADLINE_PASSED`, and a UTP gate requiring every disclosure-required position sharing the filing's `tax_year_id` and `jurisdiction_id` to be in `DISCLOSED`, `SETTLED`, or `LAPSED`, else `ERR_UTP_UNDISCLOSED`. On success the filing moves `READY → FILED`, `filed_on` is set to the clock date, and `is_late` is computed as true exactly when `filed_on` is after the effective due date. Filing fires the return-to-provision cascade: hop 1 recomputes the year's `return_to_provision_adjustment_cents` as the sum, across the year's filings in `FILED` or `ACCEPTED`, of each filing's `return_tax_liability_cents` minus its `estimated_liability_cents` — a full recompute each time, idempotent across reject/amend/refile cycles — and recomputes `actual_etr_bp`. Hop 2 re-spreads the filing's own delta across the jurisdiction's remaining payments: taking the filing's `return_tax_liability_cents` minus `estimated_liability_cents` (zero when the filing was already counted with the same liability), the server collects the jurisdiction's payments of the year in status `SCHEDULED` with method `CURRENT_YEAR_ANNUALIZED`, ordered by ascending `quarter_index`; when that set is non-empty, a base delta is the filing's delta divided by the number of such payments, rounded half up; every payment except the last receives the base delta, and the last payment — the highest `quarter_index` — receives the delta minus the base delta times one less than the count, so the spread sums exactly to the delta; each affected payment's `scheduled_amount_cents` is recomputed **from base** as `base_scheduled_amount_cents` plus its assigned delta, keeping the operation idempotent. Quarters on the `PRIOR_YEAR_SAFE_HARBOR` method and quarters already `PARTIALLY_PAID`, `LATE`, or `PAID` are never re-spread. The year's `version` increments.

From `FILED`, a `TaxManager` accepts the return (`ACCEPTED`, terminal) or rejects it. Rejection moves the filing to `REJECTED` with a `rejection_reason`, which must be a non-empty string (`ERR_INVALID_REQUEST`), drops it out of the filed set — `return_to_provision_adjustment_cents` and `actual_etr_bp` recompute and the year's `version` increments — and opens the amendment path: a `TaxAccountant` amends a `REJECTED` filing with a corrected positive `return_tax_liability_cents`, moving it to `AMENDED`, from which marking it ready again re-enters `READY`.

### 3.8. Locking the Provision and Closing the Year

Three `TaxDirector` motions drive the year itself. Locking the provision (`OPEN → PROVISION_LOCKED`) is permitted only when every difference of the year is terminal — `LOCKED` or `REJECTED` — when some valuation allowance of the year is `APPROVED`, and when no position of the year is still `IDENTIFIED`; a breach of any leg is `ERR_UNRESOLVED_PROVISION_ITEMS`. The lock assigns `estimated_liability_cents` on each filing of the year from the current tax stack's per-jurisdiction components, snapshots `current_provision_cents` (it continues to be exposed but is frozen thereafter, since difference locks and valuation allowance changes are blocked once the year is not `OPEN`), recomputes `forecast_etr_bp`, and increments the year's `version`.

Marking returns filed (`PROVISION_LOCKED → RETURNS_FILED`) requires every filing of the year to be `FILED` or `ACCEPTED`, otherwise `ERR_UNFILED_RETURNS`, and increments the version. Closing the year (`RETURNS_FILED → CLOSED`, terminal) requires every audit case of the year to be `CLOSED_AGREED` or `CLOSED_NO_CHANGE`, and every notice either joined via its `audit_case_id` to an audit case of the year or standing alone in a jurisdiction that has a filing in the year to be `RESOLVED`; a breach of either leg is `ERR_UNRESOLVED_NOTICES`; the version increments again.

### 3.9. Notices and Audit Cases

A `TaxAccountant` logs an incoming notice with `jurisdiction_id`, an optional `audit_case_id` (notices may stand alone), a `notice_type` of `INFORMATION_REQUEST`, `AUDIT_OPENING`, `PROPOSED_ADJUSTMENT`, or `PENALTY_ASSESSMENT`, the `received_on` date, and the `response_due_on` deadline, which must not precede `received_on` (`ERR_DATE_RANGE_INVALID`). The notice lands in `RECEIVED`. A `TaxManager` assigns it for review (`RECEIVED → UNDER_REVIEW`) and later responds — supplying a non-empty `response_text`, which is stored — moving it to `RESPONDED`; resolving a responded notice (`RESPONDED → RESOLVED`) is terminal. The clock sweep moves a `RECEIVED` or `UNDER_REVIEW` notice to `OVERDUE` once the clock date passes `response_due_on`. A late response is permitted: responding from `OVERDUE` also moves the notice to `RESPONDED`, and the `OVERDUE` sojourn remains visible in `updated_at` history.

Audit cases belong to a `TaxManager`. Opening one requires `tax_year_id`, `jurisdiction_id`, and the half-open examination interval `exam_period_start` (inclusive) to `exam_period_end` (exclusive); the end must be after the start (`ERR_DATE_RANGE_INVALID`), and the interval must not overlap any non-closed audit of the same jurisdiction per the half-open rule of §2.9 (`ERR_AUDIT_PERIOD_OVERLAP`). The case opens in `UNDER_EXAMINATION` with `opened_on` stamped from the clock. Proposing an adjustment attaches `proposed_adjustment_cents` (nonnegative) and moves the case to `ADJUSTMENT_PROPOSED`; negotiating moves it to `NEGOTIATING`; revising the proposal cycles `NEGOTIATING → ADJUSTMENT_PROPOSED` with a revised nonnegative `proposed_adjustment_cents` — the negotiation loop. Closing takes an `outcome`: `NO_CHANGE` from `UNDER_EXAMINATION` lands in `CLOSED_NO_CHANGE`, while `AGREED` from `ADJUSTMENT_PROPOSED` or `NEGOTIATING` lands in `CLOSED_AGREED` and requires `agreed_adjustment_cents` present and nonnegative, which is then recorded. Closing an already-closed case, or naming an `outcome` with no declared transition from the current state, is `ERR_INVALID_STATE_TRANSITION`; a negative proposed or agreed adjustment is `ERR_INVALID_AMOUNT`. Every close path requires all notices linked via `audit_case_id` to be `RESOLVED`, otherwise `ERR_UNRESOLVED_NOTICES`.

## 4. Endpoint Definitions

All endpoints are mounted under the prefixes shown. Creating a new resource returns HTTP 201 with the created resource in `data`; modifications and action endpoints return HTTP 200 with the updated resource. List endpoints return HTTP 200 with an array. Error responses follow §2.2 with the codes of §5. The optional list-endpoint filters are exact-match query parameters: book-tax-differences — `tax_year_id`, `jurisdiction_id`, `status`, `difference_type`; deferred-tax-items — `tax_year_id`, `source_difference_id`, `item_kind`; valuation-allowances — `tax_year_id`, `status`; uncertain-tax-positions, filings, and audits — `tax_year_id`, `jurisdiction_id`, `status`; estimated-payments — `tax_year_id`, `jurisdiction_id`, `status`, `method`; notices — `jurisdiction_id`, `audit_case_id`, `status`, `notice_type`. A request to an undeclared path, or to a declared path with an unsupported method, receives the standard error envelope with `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock; run the late/overdue/lapse sweeps synchronously | PlatformAdmin |
| POST | `/tax/tax-years` | Create a fiscal year under provision | TaxManager, TaxDirector |
| GET | `/tax/tax-years/{taxYearId}` | Get one TaxYear with all computed fields and version | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/tax-years/{taxYearId}/lock-provision` | OPEN → PROVISION_LOCKED; freeze provision, stamp per-jurisdiction estimates onto filings | TaxDirector |
| POST | `/tax/tax-years/{taxYearId}/mark-returns-filed` | PROVISION_LOCKED → RETURNS_FILED | TaxDirector |
| POST | `/tax/tax-years/{taxYearId}/close` | RETURNS_FILED → CLOSED | TaxDirector |
| POST | `/tax/jurisdictions` | Create a taxing jurisdiction (reference data) | TaxManager, TaxDirector |
| GET | `/tax/jurisdictions/{jurisdictionId}` | Get one Jurisdiction | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/book-tax-differences` | Identify a book-to-tax difference | TaxAccountant |
| GET | `/tax/book-tax-differences` | List differences with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/book-tax-differences/{differenceId}` | Get one BookTaxDifference | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/book-tax-differences/{differenceId}/review` | IDENTIFIED → REVIEWED | TaxManager |
| POST | `/tax/book-tax-differences/{differenceId}/return-for-rework` | REVIEWED → IDENTIFIED (rework loop) | TaxManager |
| POST | `/tax/book-tax-differences/{differenceId}/lock` | REVIEWED → LOCKED; fires the deferred-tax cascade | TaxManager, TaxDirector |
| POST | `/tax/book-tax-differences/{differenceId}/reject` | REVIEWED → REJECTED | TaxManager |
| GET | `/tax/deferred-tax-items` | List deferred tax rollforward lines with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/deferred-tax-items/{deferredItemId}` | Get one DeferredTaxItem | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/valuation-allowances` | Create a valuation allowance assessment (OCC on TaxYear version) | TaxManager |
| GET | `/tax/valuation-allowances` | List valuation allowances with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/valuation-allowances/{allowanceId}` | Get one ValuationAllowance | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/valuation-allowances/{allowanceId}/submit` | DRAFT → SUBMITTED | TaxManager |
| POST | `/tax/valuation-allowances/{allowanceId}/approve` | SUBMITTED → APPROVED; segregation of duties enforced | TaxDirector |
| POST | `/tax/valuation-allowances/{allowanceId}/return` | SUBMITTED → DRAFT (rework loop) | TaxDirector |
| POST | `/tax/uncertain-tax-positions` | Identify an uncertain tax position | TaxAccountant |
| GET | `/tax/uncertain-tax-positions` | List UTPs with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/uncertain-tax-positions/{positionId}` | Get one UTP; interest recomputed against the clock on read | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/uncertain-tax-positions/{positionId}/measure` | IDENTIFIED → MEASURED (or re-measure); applies the >50% threshold | TaxManager |
| POST | `/tax/uncertain-tax-positions/{positionId}/disclose` | MEASURED → DISCLOSED; requires a READY/FILED/ACCEPTED filing for the pair | TaxManager |
| POST | `/tax/uncertain-tax-positions/{positionId}/settle` | DISCLOSED → SETTLED; releases the reserve | TaxManager |
| POST | `/tax/estimated-payments/generate-schedule` | Generate all four quarterly payments for a (year, jurisdiction) pair | TaxManager |
| POST | `/tax/estimated-payments` | Manually create one quarterly payment with client-supplied amount | TaxManager |
| GET | `/tax/estimated-payments` | List estimated payments with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/estimated-payments/{paymentId}` | Get one EstimatedPayment | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/estimated-payments/{paymentId}/record-payment` | Record a payment; transitions to PARTIALLY_PAID or PAID; never overpays | TaxAccountant |
| POST | `/tax/estimated-payments/{paymentId}/reverse-payment` | Compensating reversal; never refunds an assessed penalty | TaxManager |
| POST | `/tax/filings` | Open a return filing slot for a (year, jurisdiction) pair | TaxAccountant |
| GET | `/tax/filings` | List filings with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/filings/{filingId}` | Get one Filing | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/filings/{filingId}/mark-ready` | PENDING or AMENDED → READY; attaches the return's tax liability | TaxAccountant |
| POST | `/tax/filings/{filingId}/file` | READY → FILED; OCC on TaxYear version; fires the RTP cascade | TaxDirector |
| POST | `/tax/filings/{filingId}/accept` | FILED → ACCEPTED (terminal) | TaxManager |
| POST | `/tax/filings/{filingId}/reject` | FILED → REJECTED; drops out of the RTP filed set | TaxManager |
| POST | `/tax/filings/{filingId}/amend` | REJECTED → AMENDED; attaches the corrected liability | TaxAccountant |
| POST | `/tax/filings/{filingId}/request-extension` | extension_status NONE → REQUESTED while PENDING/READY | TaxAccountant |
| POST | `/tax/filings/{filingId}/resolve-extension` | extension_status REQUESTED → GRANTED or DENIED | TaxDirector |
| POST | `/tax/notices` | Log an incoming jurisdiction notice | TaxAccountant |
| GET | `/tax/notices` | List notices with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/notices/{noticeId}` | Get one TaxNotice | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/notices/{noticeId}/assign-review` | RECEIVED → UNDER_REVIEW | TaxManager |
| POST | `/tax/notices/{noticeId}/respond` | UNDER_REVIEW or OVERDUE → RESPONDED | TaxManager |
| POST | `/tax/notices/{noticeId}/resolve` | RESPONDED → RESOLVED (terminal) | TaxManager |
| POST | `/tax/audits` | Open an audit for a (year, jurisdiction) pair | TaxManager |
| GET | `/tax/audits` | List audits with optional filters | TaxAccountant, TaxManager, TaxDirector, Auditor |
| GET | `/tax/audits/{auditId}` | Get one AuditCase | TaxAccountant, TaxManager, TaxDirector, Auditor |
| POST | `/tax/audits/{auditId}/propose-adjustment` | UNDER_EXAMINATION → ADJUSTMENT_PROPOSED | TaxManager |
| POST | `/tax/audits/{auditId}/negotiate` | ADJUSTMENT_PROPOSED → NEGOTIATING | TaxManager |
| POST | `/tax/audits/{auditId}/revise-adjustment` | NEGOTIATING → ADJUSTMENT_PROPOSED with a revised amount | TaxManager |
| POST | `/tax/audits/{auditId}/close` | Close with outcome NO_CHANGE or AGREED; linked notices must be RESOLVED | TaxManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_PAYMENT_ALREADY_SETTLED` | 409 |
| `ERR_TAX_YEAR_NOT_OPEN` | 409 |
| `ERR_TAX_YEAR_NOT_LOCKED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_JURISDICTION_CODE` | 409 |
| `ERR_DUPLICATE_QUARTER` | 409 |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 |
| `ERR_QUARTER_OVERLAP` | 409 |
| `ERR_QUARTER_GAP` | 422 |
| `ERR_EXTENSION_WINDOW_MISSED` | 422 |
| `ERR_FILING_DEADLINE_PASSED` | 422 |
| `ERR_DATE_RANGE_INVALID` | 422 |
| `ERR_UNRESOLVED_PROVISION_ITEMS` | 422 |
| `ERR_UNFILED_RETURNS` | 422 |
| `ERR_UTP_UNDISCLOSED` | 422 |
| `ERR_RETURN_NOT_READY` | 422 |
| `ERR_UNRESOLVED_NOTICES` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_PROBABILITY_OUT_OF_RANGE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
