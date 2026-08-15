# Fund Administration & Expense Accrual API — Product Requirements Document

## 1. Introduction

A fund administrator sits at the operational center of the registered-fund complex. Every business day, each share class of each fund must have its books brought current: portfolio positions valued under a documented pricing hierarchy, expenses accrued under the fund's day-count convention, expense caps tested and waivers booked against them, income retained and distributed to shareholders, and quantity breaks against custodian and broker statements worked through to resolution. On top of that daily cycle sit the periodic obligations — adviser and administrator fee invoicing, regulatory filings against statutory deadlines, performance reporting versus a benchmark, audit support, and the fiscal-year close that locks the books against further revision.

This document specifies the Fund Administration & Expense Accrual API, the system of record for that operating model. The API is built around a set of peer entities — funds, share classes, securities, positions, price observations, daily accounting records, expense accruals, waiver agreements and their ledger entries, distributions, reconciliation breaks, fee invoices, and regulatory filings — joined by references rather than nested creation paths. Four operator roles share the work under a segregation-of-duties regime in which preparation and approval of the same resource never rest with the same user. Every temporal rule evaluates against a server-maintained logical clock rather than wall-clock time, accounting records are produced under two pricing variants (a provisional view and a final-priced view), and every mutation — including the cascades it triggers into other records — commits atomically within its request.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The system recognizes exactly four roles: `FundAccountant`, `FundController`, `PricingCommittee`, and `ComplianceOfficer`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles divide the work as follows. A `FundAccountant` is the daily operations preparer: security master data, price submissions, accounting-record creation, manual accruals, capital activity, distribution declarations, reconciliation-break recording, and fee-invoice preparation. A `FundController` holds approval and control authority: fund and share-class setup, accounting-record finalization and reopening, waiver agreements and recoupments, distribution payment and cancellation, break resolution and escalation, fee-invoice approval and payment, filing approval, and the fiscal-year close. A `PricingCommittee` member governs valuation: approving price observations and issuing fair-value overrides. A `ComplianceOfficer` is the regulatory reporting preparer: creating filings, submitting them for review, filing them, and amending them — approval of a filing is reserved to the `FundController`.

For all four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources the operator prepares or approves — as `created_by_user_id` on accounting records and fee invoices, as `prepared_by_user_id` on regulatory filings, and as `approved_by_user_id` on approved invoices and filings — and uses those stored identifiers for the segregation-of-duties comparisons described in §2.7, but it never compares `X-User-ID` to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the host wall clock rather than the logical clock of §2.4.
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
- Requests to undefined paths, and requests using an undefined method on a defined path, are rejected with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-numeric `limit` or `offset` falls back to its default, and out-of-range values are clamped into the allowed range rather than rejected. Filter query parameters match by exact equality on the named field.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties on the timestamp broken in insertion order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Every temporal rule in this document — whether a price may be captured for a given date, when a distribution becomes payable, when a reconciliation break escalates, whether a filing is late, whether a waiver ledger entry remains recoupable, whether an agreement is still active, whether a fiscal year may be closed — evaluates against a server-maintained logical clock, never against wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the host's wall clock.

An operator-facing, test-driving capability — available to all four roles — advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The clock moves strictly forward: a request whose target instant is not strictly after the current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422).

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock of §2.4, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format and taken from the same logical clock, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation — including mutations caused by cascade recomputation rather than by a direct client write.

Waiver ledger entries are the single exception to this convention: a ledger entry carries only `id` and `created_at`; both `updated_at` and `version` are absent, because ledger entries are immutable once booked. Clients must never send system-managed fields (`id`, `created_at`, `updated_at`, `version`) in a request body; a body containing them is rejected as malformed.

### 2.6. Monetary Precision and Rounding Conventions

All monetary values in the system are decimals rounded to exactly 2 decimal places using round-half-up. Per-share figures — the accounting record's NAV per share and a distribution's per-share income — use 4 decimal places, also round-half-up. Observed security prices are stored exactly as quoted, with no rounding applied at submission or at selection time. Monetary inputs — a position's `cost_basis_total`, an income posting's or a recoupment's `amount` — are likewise accepted and stored exactly as supplied; the rounding rules above govern computed values. The annualized expense ratio used by the expense-cap test is rounded to 4 decimal places, round-half-up. Position and share quantities are kept exactly as entered, without rounding.

Two rounding orders are pinned and non-negotiable. Position market values are rounded to 2 decimal places per position before they are summed into a gross asset value — summing raw products and rounding once at the end yields different cents and is non-conformant. A distribution's per-share amount is rounded to 4 decimal places before it is multiplied back over the share count to obtain the payable total. In fee computation, average daily net assets is kept unrounded until the final fee multiplication.

### 2.7. Segregation of Duties

Preparation and approval of the same resource never rest with the same user. Three operations enforce this rule: finalizing an accounting record, approving a fee invoice, and approving a regulatory filing. On each, the caller's `X-User-ID` must differ from the identifier of the user who prepared the resource — the accounting record's `created_by_user_id`, the invoice's `created_by_user_id`, or the filing's `prepared_by_user_id`. A caller who prepared the resource is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A successful approval records the approver's identifier in the resource's `approved_by_user_id`.

### 2.8. Optimistic Concurrency Control

Finalizing an accounting record is the only operation guarded by optimistic concurrency control. The finalization request must carry `expected_nav_record_version`, a non-optional field holding the record's `version` as last observed by the client. If the supplied value does not match the record's current `version`, the request is rejected with `ERR_STALE_NAV_VERSION` (HTTP 412); the client must re-read the record and resubmit against the fresh version. This guard exists because an accounting record's version advances whenever the record is recomputed — a manually added accrual, a newly submitted or approved price, a fair-value override cascade, a break resolution or reopening, a distribution reinvestment — so a client may legitimately hold a stale snapshot at finalize time and would otherwise finalize numbers it never saw. No other endpoint accepts a version field; mutations elsewhere proceed without an OCC check.

### 2.9. Request Validation Pipeline

Every request is validated in a fixed order, and the first failing check determines the error response — later checks never mask earlier ones. The order is:

1. Authentication headers — missing or invalid headers yield `ERR_UNAUTHENTICATED` (HTTP 401).
2. Path resolution — every identifier in the URL path must resolve to an existing resource, validated left to right; the first unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404). References carried in the request body (such as `fund_id`, `share_class_id`, `security_id`, or `position_id` on the create endpoints) must likewise resolve to existing resources; an unresolvable body reference yields the same `ERR_NOT_FOUND` (HTTP 404), checked after the schema-level body-shape checks of step 4.
3. Role authorization against the endpoint's authorized roles — `ERR_FORBIDDEN_ROLE` (HTTP 403).
4. Request-body shape — required fields present, no unknown fields (system-managed fields such as `id`, `created_at`, `updated_at`, and `version` included), correct types and enum values, and numeric ranges respected (a price greater than zero, a creation quantity greater than zero, a counterparty quantity of zero or more, a cap rate greater than zero, an annual accrual rate greater than zero, a recovery window of one to thirty-six months, period and effectiveness end dates not before their start dates, positive amounts, positive share counts where supplied, and a well-formed clock timestamp) — `ERR_VALIDATION` (HTTP 400).
5. State eligibility of the target resource for the requested transition — `ERR_INVALID_STATE` (HTTP 409); a recoupment attempted against an agreement whose derived status is no longer `ACTIVE` instead yields `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409).
6. The optimistic-concurrency check on accounting-record finalization — `ERR_STALE_NAV_VERSION` (HTTP 412).
7. Segregation of duties — `ERR_SOD_VIOLATION` (HTTP 403).
8. Compliance gates — `ERR_BREAK_ESCALATED_BLOCKS` and `ERR_FISCAL_CLOSE_BLOCKED` (both HTTP 409).
9. Temporal rules against the logical clock — the `ERR_PRICE_DATE_FUTURE`, `ERR_PERIOD_NOT_ENDED`, `ERR_DISTRIBUTION_NOT_PAYABLE`, `ERR_RECOUP_WINDOW_EXPIRED`, and `ERR_CLOCK_REGRESSION` family (HTTP 422).
10. Uniqueness and business-constraint checks — duplicate tickers, non-sequential accounting dates, duplicate price sources, reserved price sources, missing prices, unapproved prices, non-estimable accrual dates, system-managed accrual categories, overlapping cap agreements, non-contiguous fee periods, absent final records, zero-variance breaks, misordered distribution dates, and reopen guards.
11. Fiscal checks, evaluated last — shares outstanding, redemption size, recoupment balance, and distributable income.

### 2.10. Derived State and Immediate Consistency

Every mutation, together with every cascade it triggers, commits atomically within its request: a price approval that recomputes several estimated records, a break resolution that moves a position and rebuilds the class's books, a finalization that posts accruals and books a waiver entry — each of these either fully succeeds or fully fails, with no intermediate state visible. Records touched by a cascade undergo real mutations: their derived fields are recomputed, their `updated_at` refreshes, and their `version` increments by one. Certain values are never stored at all and are instead derived on read — most notably a waiver agreement's `status`, which reads `ACTIVE` while the logical clock date is on or before the agreement's last covered day and `EXPIRED` thereafter, and its `recoverable_balance`, which is the running sum of undrawn waiver amounts on its ledger.

## 3. Business Logic & Workflows

### 3.1. Establishing Funds, Share Classes, and Capital Activity

A `FundController` onboards a fund by supplying its `fund_name`, a `ticker` that must be unique across all funds (a duplicate is rejected with `ERR_TICKER_ALREADY_EXISTS`, HTTP 409), a `base_currency` of `USD`, `EUR`, or `GBP`, a `fiscal_year_end` expressed as a month-and-day such as 12-31 (02-29 is accepted), and the `adviser_name`. Two fee parameters ride on the fund profile. The `admin_fee_bps` is the administrator's annual fee in basis points of net assets and must be greater than zero. The `adviser_fee_tiers` are an ordered, non-empty list of marginal fee tiers, each pairing an `up_to_net_assets` ceiling with a `rate_bps`; ceilings must ascend, and exactly one tier — the last — carries a null ceiling, marking it unbounded. The fund's `day_count_convention`, either `ACT_365` or `ACT_360`, drives the daily expense-accrual divisor described in §3.5. A newly created fund has never been through a fiscal-year close, so its `last_closed_fiscal_year_end` is null until the first close completes.

Share classes come next, again created by a `FundController`. Each class references its fund via `fund_id` and carries a `class_ticker` that must be unique within that fund (violations surface as the same `ERR_TICKER_ALREADY_EXISTS`), plus a `distribution_frequency` of `DAILY`, `MONTHLY`, `QUARTERLY`, or `ANNUALLY`. A class is born with `shares_outstanding` of zero and `retained_income` of zero — no shares exist and no income has been retained until capital activity says otherwise. The share-class listing can be filtered by `fund_id`.

From that point on, a `FundAccountant` records capital activity against a class. Each activity names an `activity_type`, an `activity_date`, and — depending on the type — a `shares` count or an `amount`. A `SUBSCRIPTION` or `REDEMPTION` missing `shares`, or an `INCOME_POSTING` missing `amount`, is rejected with `ERR_VALIDATION` (HTTP 400); an inapplicable field supplied anyway — an `amount` on a share activity, or `shares` on an income posting — is accepted and ignored. A `SUBSCRIPTION` increases the class's `shares_outstanding` by the supplied `shares`, which must be greater than zero when supplied. A `REDEMPTION` decreases `shares_outstanding` by the supplied `shares`; redeeming exactly all outstanding shares is allowed, but a redemption larger than the current `shares_outstanding` is rejected with `ERR_REDEMPTION_EXCEEDS_SHARES` (HTTP 422). An `INCOME_POSTING` requires an `amount` greater than zero and adds it to the class's `retained_income`, the undistributed-income balance that later funds distribution declarations. Every recorded activity mutates the class, incrementing its `version` by one.

### 3.2. Security Master Data and Daily Price Capture

Before any portfolio can be valued, a `FundAccountant` registers the security master. A security is created with a `security_identifier` (a CUSIP or SEDOL; no uniqueness check is applied), a free-text `description`, an `asset_class` of `EQUITY`, `FIXED_INCOME`, `CASH_EQUIVALENT`, or `DERIVATIVE`, a `default_pricing_level` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3` recording the valuation-hierarchy level the security is expected to price at, and a `currency` of `USD`, `EUR`, or `GBP`.

Positions are opened per share class — the administrator keeps each class's portfolio sleeve separately — by a `FundAccountant` supplying the `share_class_id`, the `security_id`, a `quantity` greater than zero, a `cost_basis_total` accepted and stored exactly as supplied, and the `opened_date`. A new position is `OPEN`. After creation, a position's `quantity` is never edited directly; it changes only through reconciliation-break resolution (§3.8). The positions listing can be filtered by `share_class_id`, `security_id`, or `status`.

Daily price capture is the `FundAccountant`'s final setup act. Submitting a price observation takes the `security_id`, the `price_date` the price is for, the `price` itself (greater than zero, stored exactly as quoted), a `source`, and the observation's `pricing_level`. The `price_date` must not lie after the logical clock date — a future-dated price is rejected with `ERR_PRICE_DATE_FUTURE` (HTTP 422). Manual submissions may use the sources `EXCHANGE_CLOSE`, `PRICING_SERVICE`, or `BROKER_QUOTE`; the `FAIR_VALUE_COMMITTEE` source is reserved to the fair-value override flow, and a manual create naming it is rejected with `ERR_OVERRIDE_SOURCE_RESERVED` (HTTP 422). At most one observation that has not been `OVERRIDDEN` may exist for a given security, date, and source; a second live observation for the same triple is rejected with `ERR_DUPLICATE_PRICE_SOURCE` (HTTP 409). A fresh observation lands in `SUBMITTED` status with its `is_fair_value_override` flag false, and its arrival recomputes the `ESTIMATED` accounting record — if one exists — of every class holding that security on the observation's `price_date`, incrementing each such record's `version`. A security's observation history can be listed with optional `price_date` and `status` filters.

### 3.3. Price Governance: Approval, Fair-Value Override, and the Valuation Hierarchy

Valuation governance belongs to the `PricingCommittee`. Approval moves a `SUBMITTED` observation to `APPROVED` and recomputes the `ESTIMATED` accounting record (if any) of each class holding the security on the observation's `price_date`, incrementing that record's `version` by one.

The fair-value override is the committee's heavier instrument and may be applied to an observation in either `SUBMITTED` or `APPROVED` status. Overriding supersedes the original observation, which moves to the terminal `OVERRIDDEN` status, and creates a brand-new observation in its place: the new observation carries the reserved `FAIR_VALUE_COMMITTEE` source, an `is_fair_value_override` flag of true, an immediate `APPROVED` status, the same `security_id` and `price_date` as the original, a `price` equal to the supplied `override_price`, and the supplied `pricing_level`. What happens next depends on the state of the affected books. If some holding class's accounting record for that `price_date` is `FINAL` and is that class's latest record, the override forces the correction cascade described in §3.6. If the record is still `ESTIMATED`, it is simply recomputed in place with the new selected price, its `version` incrementing. A `REOPENED` record is not touched by the cascade.

Both the daily computation and the preview fields rely on one price-selection rule. For a given security and date, the candidate set is the observations matching that security and date whose status is eligible under the pricing variant in use. Candidates are ranked as follows: an observation created by fair-value override always wins over non-override observations; among what remains, the lower pricing level wins — `LEVEL_1` beats `LEVEL_2`, which beats `LEVEL_3`; and within an identical level, the most recently created observation wins. An observation's `id` is never consulted in selection, ranking, or tie-breaking. If the candidate set is empty under the record's variant, that security has no selected price. The two variants differ only in eligibility: the `PROVISIONAL` variant — used while a record is `ESTIMATED` and for the `provisional_nav_per_share` preview — admits both `SUBMITTED` and `APPROVED` observations, so unapproved quotes are admissible; the `FINAL_PRICED` variant — used once a record is `FINAL` or `REOPENED`, and for the `final_nav_per_share` preview — admits `APPROVED` observations only, so identical positions can price differently once merely-submitted rows drop out.

### 3.4. Building the Daily Accounting Record

Each business day, a `FundAccountant` creates the class's accounting record by supplying its `share_class_id` and the `accounting_date`. Three guards stand in front of creation. The `accounting_date` must be strictly later than every existing record for that class — anything else is rejected with `ERR_NAV_DATE_NOT_SEQUENTIAL` (HTTP 409). Every `OPEN` position of the class must have at least one price observation of any status for its security on the `accounting_date`; a held security with no observation at all blocks creation with `ERR_MISSING_PRICE` (HTTP 422). (`CLOSED` positions are exempt from this check and from valuation entirely.) And, as the fiscal check evaluated last in the pipeline, the class must actually have shares outstanding — creating a record while `shares_outstanding` is zero is rejected with `ERR_NO_SHARES_OUTSTANDING` (HTTP 422). The new record is born `ESTIMATED`, and the creator's identifier is captured in `created_by_user_id` for the segregation-of-duties check at finalize time.

Creation immediately computes the record under the `PROVISIONAL` variant. For every `OPEN` position of the class, the position's market value is its `quantity` multiplied by its security's selected price, rounded to two decimal places per position first; the `gross_asset_value` is the sum of those per-position values; a position whose security has no selected price under the record's variant contributes nothing to the sum. The `expense_accrual_total` is the sum of `accrued_amount` over the class's accrual rows for the `accounting_date` whose status is `ESTIMATED` or `POSTED`. The `total_net_assets` is the gross asset value minus the accrual total, rounded to two decimal places. The `nav_per_share` is the total net assets divided by the class's `shares_outstanding`, rounded to four decimal places. Alongside the headline figure, the record carries two what-if previews: `provisional_nav_per_share`, the per-share NAV under the `PROVISIONAL` variant, and `final_nav_per_share`, the per-share NAV under the `FINAL_PRICED` variant — the latter is null whenever any held security lacks an `APPROVED` observation for the `accounting_date`, and the former is likewise null whenever any held security lacks a `SUBMITTED` or `APPROVED` observation for that date. When the class's `shares_outstanding` is zero at computation time — possible only through redemption after creation, since creation requires shares — `nav_per_share` and both previews are null. The record's `pricing_variant_used` reads `PROVISIONAL` while the record is `ESTIMATED` and `FINAL_PRICED` once it has reached `FINAL` or `REOPENED`. Accounting records can be listed with `share_class_id`, `status`, and `accounting_date` filters.

One expense accrual never needs manual entry: creating the accounting record automatically generates the class's `ADMIN_FEE` accrual row for the same date, computed per the daily accrual rule of §3.5 with its annual rate taken from the fund's `admin_fee_bps`.

### 3.5. Expense Accruals, Waiver Agreements, and the Expense-Cap Test

Every accrual row — whether the automatic `ADMIN_FEE` row or a manually added one — accrues by the same daily rule. The row's `base_net_assets` is the `total_net_assets` of the class's `FINAL` accounting record bearing the greatest `accounting_date` strictly before the accrual's date; when no such `FINAL` record exists — which is the case for the class's first-ever record — the base is instead the current `gross_asset_value` of the `ESTIMATED` record being built. The `accrued_amount` is the base multiplied by the row's `annual_rate_bps`, divided by ten thousand, divided by the day count, with the result rounded to two decimal places half-up. The day count is 365 for an `ACT_365` fund and 360 for an `ACT_360` fund, so an identical base and rate accrue less per day under `ACT_365` than under `ACT_360` — a base of 52,340.00 at 10 basis points accrues 0.14 per day under `ACT_365` but 0.15 under `ACT_360`. All accrual rows of a class on a given date share one base.

Beyond the automatic administration-fee row, a `FundAccountant` may book additional accruals manually, supplying the `share_class_id`, an `accrual_date`, a `category`, and an `annual_rate_bps` greater than zero. The `accrual_date` must match an existing `ESTIMATED` accounting record for the class — otherwise the create is rejected with `ERR_NO_ESTIMABLE_NAV` (HTTP 422) — and the category must be one of `CUSTODY_FEE`, `AUDIT_FEE`, `LEGAL_FEE`, or `OTHER`; `ADMIN_FEE` rows are system-managed and a manual create in that category is rejected with `ERR_CATEGORY_SYSTEM_MANAGED` (HTTP 422). Booking a manual accrual recomputes the matching `ESTIMATED` record — its `expense_accrual_total`, `total_net_assets`, and `nav_per_share` — and increments that record's `version` by one. Accruals can be listed with `share_class_id`, `accrual_date`, `category`, and `status` filters.

Expense-cap protection is contractual, and a `FundController` establishes it per class as a waiver agreement: the `share_class_id`, a `cap_bps` greater than zero expressing the annualized net expense cap in basis points, an `effective_from` first covered day, an `effective_to` last covered day that must not precede it (the interval is closed — both endpoint days are covered), and a `recovery_window_months` of one to thirty-six months over which waived amounts remain recoupable. Two agreements of the same class whose closed day-intervals intersect may not both be live: a new agreement whose interval overlaps another `ACTIVE` agreement of the class — and a shared endpoint day counts as overlap — is rejected with `ERR_CAP_AGREEMENT_OVERLAP` (HTTP 409), so at most one agreement covers a class on any given day. The agreement's `status` is derived, never stored: `ACTIVE` while the logical clock date is on or before `effective_to`, `EXPIRED` thereafter. Its `recoverable_balance` is the sum of `remaining_amount` over the agreement's `WAIVER` ledger entries. Every agreement representation — the create response, the get, and the list — carries the derived `status` and `recoverable_balance`. Agreements can be listed filtered by `share_class_id`, and each agreement exposes its ledger through a dedicated listing.

The cap itself is tested whenever an accounting record is finalized (§3.6), and again on the recompute leg of a fair-value override that strikes a `FINAL` record — in the override case only when the struck record is the class's first record (§3.6). The evaluation order is pinned to break the apparent circle between accruals, net assets, and the cap: prices are selected first; per-position market values produce the `gross_asset_value`; accruals are computed from their base; `total_net_assets` follows; then `nav_per_share`; and only then is the cap ratio evaluated — always against the accrual base, never against total net assets. When the accrual base is zero or negative, the test is skipped and no waiver is booked. With `A` as the record's `expense_accrual_total` and `B` as the accrual base (`base_net_assets`, shared by all of the class's rows on that date), the annualized expense ratio in basis points is `A` multiplied by 365, divided by `B`, multiplied by ten thousand, rounded to four decimal places half-up. The ratio is compared against the covering `ACTIVE` agreement's `cap_bps`, and a breach exists only when the ratio is strictly greater than the cap — a ratio exactly equal to the cap is not a breach. On a breach, the waiver amount is the smaller of `A` and the excess ratio — the ratio minus `cap_bps`, divided by ten thousand, multiplied by `B`, divided by 365 — rounded to two decimal places half-up. When that waiver amount is positive, the system books a `WAIVER` ledger entry on the agreement: its `amount` is the waiver amount, its `entry_date` is the record's `accounting_date`, its `expires_at` is the entry date advanced by the agreement's `recovery_window_months` (keeping the same day-of-month, clamped to the month end when the target month is shorter), and its `remaining_amount` starts equal to its `amount`. Booking the entry updates the agreement's `recoverable_balance`, but the waiver lives on the agreement ledger only — it does not change the triggering record's `total_net_assets`.

Waived amounts can later be clawed back. A `FundController` posts a recoupment against an agreement by supplying an `amount` greater than zero and a `recoup_date`. The agreement's derived status must be `ACTIVE`; recouping from an expired agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). Eligible funding sources are the agreement's `WAIVER` ledger entries whose `remaining_amount` exceeds zero and whose `expires_at` falls on or after the `recoup_date` — the window is inclusive, so a recoupment dated exactly on an entry's `expires_at` may still draw from it. When no entry is eligible, the request fails with `ERR_RECOUP_WINDOW_EXPIRED` (HTTP 422); when the requested `amount` exceeds the sum of eligible remaining balances, it fails with `ERR_RECOUP_AMOUNT_EXCEEDS_BALANCE` (HTTP 422). The draw proceeds oldest-first — by `entry_date` ascending, ties broken by `created_at` ascending — taking from each entry the smaller of its remaining balance and the amount still outstanding, until the request is satisfied. Exactly one `RECOUPMENT` entry is then created, carrying the requested `amount`, an `entry_date` equal to the `recoup_date`, a null `expires_at`, and a `remaining_amount` of zero; the agreement's `recoverable_balance` recomputes, and the agreement's `version` increments by one. Ledger entries — each referencing its `waiver_agreement_id`, with an `entry_type` of `WAIVER` or `RECOUPMENT` and a positive `amount` (the computed waiver amount at two decimals, or the requested recoupment amount exactly as supplied) — are the one resource family without `updated_at` or `version`, per §2.5.

### 3.6. Finalizing, Reopening, and Correcting the NAV

Finalization is the `FundController`'s sign-off, moving a record from `ESTIMATED` to `FINAL` — or, after a correction, from `REOPENED` back to `FINAL`; requesting it from any other state is an `ERR_INVALID_STATE` (HTTP 409). The request is guarded three ways, in pipeline order. It must carry `expected_nav_record_version` equal to the record's current `version`, per §2.8 — a mismatch is rejected with `ERR_STALE_NAV_VERSION` (HTTP 412), which happens readily in practice because price submissions, approvals, manual accruals, and cascades all advance the record's version between the preparer's last read and the controller's sign-off. The caller must not be the user who created the record, per §2.7 — a preparer finalizing their own work is rejected with `ERR_SOD_VIOLATION` (HTTP 403). And pricing must be clean: no security held in an `OPEN` position may still have a `SUBMITTED` observation outstanding on the `accounting_date`, and every such security must have at least one `APPROVED` observation for that date — either failure is rejected with `ERR_PRICE_NOT_APPROVED` (HTTP 409).

A successful finalization recomputes every computed field under the `FINAL_PRICED` variant and flips `pricing_variant_used` accordingly; moves the date's accrual rows from `ESTIMATED` to `POSTED`, so they are included in the record's `expense_accrual_total` as posted; runs the expense-cap test of §3.5, which on breach books a `WAIVER` ledger entry and updates the agreement's `recoverable_balance`; and increments the record's `version` by one. A first-record accrual row whose `accrued_amount` is recomputed during the same finalization or a reopening advances its own `version` once for the recomputation and once for the status flip.

Corrections flow the other way. A `FundController` may reopen a `FINAL` record, moving it to `REOPENED`, but only the class's latest record — the one with the greatest `accounting_date` — is eligible, anything older being rejected with `ERR_NAV_NOT_LATEST` (HTTP 409); and only while the fiscal year remains open, meaning no fiscal-year close has been recorded yet or the record's `accounting_date` falls after the fund's `last_closed_fiscal_year_end` — a record inside a closed year is rejected with `ERR_NAV_LOCKED_FISCAL_CLOSED` (HTTP 409). Reopening returns the date's accrual rows from `POSTED` to `ESTIMATED`, recomputes the record under the `FINAL_PRICED` variant, and increments its `version`.

The price-override cascade is the system's second correction path, and it needs no separate request against the record: when a fair-value override (§3.3) lands on an observation whose `price_date` equals the accounting date of a holding class's `FINAL` record that is also that class's latest record, the record is forced from `FINAL` to `REOPENED` and recomputed under `FINAL_PRICED` with the newly selected price, its `version` incrementing; unlike the reopen endpoint, the cascade leaves the date's accrual rows in `POSTED` status. If that record is the class's first record — the case where the accrual base is the record's own `gross_asset_value` — its accrual rows are recomputed as part of the cascade, and that recomputation re-runs the expense-cap test, which may book a further `WAIVER` ledger entry and update the agreement's `recoverable_balance`. The same base dependency explains why reopening re-prices accruals on a first record: when the base is the record's own gross asset value rather than a prior `FINAL` record's net assets, any recompute of the record flows through to `accrued_amount`.

### 3.7. Declaring and Paying Distributions

When income is to be paid out, a `FundAccountant` declares a distribution for a class, supplying the `share_class_id` and four dates: the `declaration_date`, the `ex_date`, the `record_date`, and the `payable_date`. The dates must observe a strict ordering — the declaration date strictly before the ex-dividend date, the ex-dividend date on or before the record date, and the record date on or before the payable date — with any violation rejected as `ERR_DISTRIBUTION_DATE_ORDER` (HTTP 422). Two business guards follow: the class's latest accounting record must be `FINAL` (otherwise `ERR_NAV_NOT_FINAL`, HTTP 409), and the class must hold distributable income — a declaration while `retained_income` is zero or negative is rejected with `ERR_NO_DISTRIBUTABLE_INCOME` (HTTP 422), the fiscal check evaluated last.

Declaration takes two snapshots from the class at that moment: `distributable_amount` copies `retained_income`, and `shares_snapshot` copies `shares_outstanding`. From these snapshots the payable arithmetic is fixed, per-share first: the `income_per_share` is the `distributable_amount` divided by the `shares_snapshot`, rounded to four decimal places half-up; the `total_amount` is then that rounded per-share figure multiplied back over the `shares_snapshot`, rounded to two decimal places half-up. Multiplying first and rounding the total once is non-conformant — it produces a different payable. A class retaining 51.00 over 100,000 shares, for instance, yields an `income_per_share` of 0.0005 and a `total_amount` of 50.00, not 51.00. The new distribution stands in `DECLARED` status, and distributions can be listed with `share_class_id` and `status` filters.

Payment belongs to the `FundController` and moves a `DECLARED` distribution to `PAID` — from any other state the request is an `ERR_INVALID_STATE`. The logical clock date must be on or after the `payable_date`; paying early is rejected with `ERR_DISTRIBUTION_NOT_PAYABLE` (HTTP 422). On payment, the class's `retained_income` decreases by the `total_amount` and the distribution's `paid_at` is set to the logical-clock timestamp. Payment carries one optional flag: with `reinvest` set to true, the payout is reinvested in new shares. Reinvestment requires a `FINAL` accounting record for the class with an `accounting_date` on or before the `payable_date` — none qualifying means `ERR_NAV_NOT_FINAL` — and the `reinvested_shares` are then the `total_amount` divided by the `nav_per_share` of the `FINAL` record with the greatest `accounting_date` on or before the `payable_date`, rounded to four decimal places half-up. The class's `shares_outstanding` increases by the `reinvested_shares`, and that share-count mutation recomputes the class's latest `ESTIMATED` record, if one exists, incrementing its `version`. Without reinvestment — or before payment — `reinvested_shares` remains null, and `paid_at` is likewise null until payment.

A `FundController` may instead cancel a `DECLARED` distribution, moving it to `CANCELLED`. Cancellation moves no balances: `retained_income` and `shares_outstanding` are untouched, exactly compensating the declaration's snapshots.

### 3.8. Custodian and Broker Reconciliation

Positions are held with outside parties, and statements disagree with the books often enough to need a formal break process. A `FundAccountant` records a break by supplying the `fund_id` (carried on the break as a denormalized scope for the escalation sweep and the filing gates), the `position_id`, a `break_type` of `CUSTODIAN_POSITION` or `BROKER_POSITION`, the statement's `break_date`, and the `counterparty_quantity` per the statement, which may be zero but never negative. At creation the break snapshots the position's current `quantity` into `book_quantity` and computes the `variance` as the counterparty quantity minus the book quantity. A break with zero variance is pointless and is rejected with `ERR_NO_VARIANCE` (HTTP 422). The break stands `OPEN`, and breaks can be listed with `fund_id`, `position_id`, and `status` filters.

Resolution is a `FundController` action available from either `OPEN` or `ESCALATED`, moving the break to `RESOLVED` with a `resolution_type` of `NO_CHANGE` or `ADJUST_POSITION`. Under `NO_CHANGE` the books stand. Under `ADJUST_POSITION`, the break first captures the position's current `quantity` into `prior_book_quantity`, then sets the position's `quantity` to the `counterparty_quantity`; if that result is exactly zero, the position auto-closes, moving from `OPEN` to `CLOSED` (a nonzero adjusted quantity never reopens an already-`CLOSED` position — only reopening the break restores `OPEN`), and closed positions drop out of accounting-record valuation and out of the missing-price and price-approval checks entirely. Either way the position mutation recomputes the holding class's latest `ESTIMATED` record if one exists — `gross_asset_value`, the accrual amounts where the first-record base rule applies, then `expense_accrual_total`, `total_net_assets`, and `nav_per_share` — incrementing that record's `version` by one.

A resolution can be walked back: reopening a `RESOLVED` break (again a `FundController` action) returns it to `OPEN` with full compensation. If the break's `resolution_type` was `ADJUST_POSITION`, the position's `quantity` is restored to the captured `prior_book_quantity` — and a position that had auto-closed returns from `CLOSED` to `OPEN` when the restored quantity is above zero — and the `resolution_type` is cleared to null. The restoration triggers the same recompute cascade on the class's latest `ESTIMATED` record, bumping its `version`. The compensating invariant is exact: resolving with `ADJUST_POSITION` followed by reopening leaves the position's `quantity` precisely equal to its pre-resolution value.

Breaks left untouched do not age gracefully. A `FundController` runs the escalation sweep, which moves every `OPEN` break whose `break_date` is more than five days before the logical clock date to `ESCALATED` — a break exactly five days old is not escalated — incrementing each escalated break's `version` by one and returning an `escalated_count` of how many breaks moved. Escalation has teeth: while any break of a fund stands `ESCALATED`, approval and filing of that fund's regulatory filings are blocked with `ERR_BREAK_ESCALATED_BLOCKS` (HTTP 409), and the fiscal-year close refuses to run (§3.9).

### 3.9. Fees, Filings, Performance Reporting, and the Fiscal-Year Close

Periodic adviser and administrator compensation runs through fee invoices, prepared by a `FundAccountant` with the `fund_id`, a `fee_type` of `ADVISER` (billed on the fund's tiered schedule) or `ADMINISTRATOR` (billed flat at the fund's `admin_fee_bps`), and a `period_start` and `period_end` bounding an inclusive day range, with `period_end` not before `period_start`. Invoice periods for the same fund and fee type must tile contiguously: when a prior invoice in `DRAFT`, `APPROVED`, or `PAID` exists, the new `period_start` must be exactly one day after the latest `period_end` among those prior invoices, otherwise the create is rejected with `ERR_FEE_PERIOD_NOT_CONTIGUOUS` (HTTP 409).

The fee computation starts from the period's day count — the inclusive count of calendar dates from `period_start` through `period_end`. For each calendar date, the fund's total net assets are the sum of `total_net_assets` over the `FINAL` accounting records of all the fund's classes on that date; dates with no `FINAL` record are excluded from both the numerator and the denominator, and if no date in the period has any `FINAL` record at all, the create fails with `ERR_NO_FINAL_NAV_IN_PERIOD` (HTTP 422). The `average_daily_net_assets` is the sum of those daily fund totals divided by the number of contributing dates, kept unrounded until the final multiplication. For an `ADVISER` invoice, the gross fee walks the fund's `adviser_fee_tiers` marginally in ascending order: each tier contributes the portion of the average falling between the previous tier's ceiling (zero for the first tier) and its own `up_to_net_assets` — the last tier, whose ceiling is null, being unbounded — floored at zero, multiplied by that tier's `rate_bps`. For an `ADMINISTRATOR` invoice, the gross is simply the average multiplied by the fund's `admin_fee_bps`. Either way, the `gross_fee` is the aggregated rate-units divided by ten thousand, multiplied by the day count, divided by 365, rounded to two decimal places half-up. The `waiver_offset` is the sum of `amount` over `WAIVER` ledger entries whose `entry_date` falls inside the period across all agreements of the fund's classes, and the `net_fee` is the gross fee minus the waiver offset, floored at zero and rounded to two decimal places half-up. The invoice is born `DRAFT` with the preparer's identifier in `created_by_user_id`; invoices can be listed with `fund_id`, `fee_type`, and `status` filters. Approval, by a `FundController`, enforces segregation of duties against `created_by_user_id` (`ERR_SOD_VIOLATION`), records the approver in `approved_by_user_id`, and moves the invoice from `DRAFT` to `APPROVED`; payment then moves it from `APPROVED` to `PAID`.

Regulatory filings follow a parallel prepare-then-approve discipline. A `ComplianceOfficer` creates a filing with the `fund_id`, a `filing_type` of `N_PORT`, `N_CEN`, `ANNUAL_REPORT`, or `SEMI_ANNUAL_REPORT`, and the reporting `period_end`; the system derives the `filing_deadline` as sixty days after `period_end` for `N_PORT`, `ANNUAL_REPORT`, and `SEMI_ANNUAL_REPORT`, and seventy-five days after for `N_CEN`. The filing begins `DRAFT` with the creator recorded in `prepared_by_user_id`, `filed_at` null, and `filed_after_deadline` false, and filings can be listed with `fund_id`, `filing_type`, and `status` filters. Submitting for review — a `ComplianceOfficer` action available from `DRAFT` or `AMENDED` — moves the filing to `PENDING_REVIEW` without changing `prepared_by_user_id`. Approval is reserved to the `FundController` and carries three gates: the caller must differ from `prepared_by_user_id` (`ERR_SOD_VIOLATION`); no reconciliation break of the fund may stand `ESCALATED` (`ERR_BREAK_ESCALATED_BLOCKS`); and the `period_end` must be strictly before the logical clock date (`ERR_PERIOD_NOT_ENDED`, HTTP 422). Approval sets `approved_by_user_id` and moves the filing to `APPROVED`. Filing, again a `ComplianceOfficer` action and again blocked while any fund break stands `ESCALATED`, moves the filing to `FILED`, stamps `filed_at` with the logical-clock timestamp, and recomputes `filed_after_deadline`, which is true exactly when the latest filing date falls strictly after the `filing_deadline`. A filed report can later be amended: amending moves `FILED` to `AMENDED`, clears `approved_by_user_id`, and the amendment cycle re-enters at `PENDING_REVIEW` through a fresh submit-for-review.

Performance reporting answers how a class did over a window. Given required query parameters `from_date`, `to_date`, and `benchmark_return_pct` — a missing or malformed one is rejected with `ERR_VALIDATION` (HTTP 400) — the report anchors on two records: the begin record is the class's `FINAL` accounting record with the smallest `accounting_date` on or after `from_date`, and the end record is the `FINAL` record with the largest `accounting_date` on or before `to_date`; if either is absent the request fails with `ERR_NO_FINAL_NAV_IN_PERIOD`. The `distributions_per_share_total` is the sum of `income_per_share` over the class's `PAID` distributions whose `payable_date` falls after the begin record's `accounting_date` and on or before the end record's `accounting_date`. The `period_return_pct` is the sum of the end record's `nav_per_share` and the distributions-per-share total, divided by the begin record's `nav_per_share`, minus one, multiplied by one hundred, rounded to four decimal places half-up; the `excess_return_pct` is the `period_return_pct` minus the `benchmark_return_pct`, likewise rounded to four decimal places half-up. The response carries `begin_nav_per_share`, `end_nav_per_share`, `distributions_per_share_total`, `period_return_pct`, `benchmark_return_pct`, and `excess_return_pct`.

The trial balance is the audit-support read over a fund. Given a required `as_of_date` query parameter — a missing or malformed one is rejected with `ERR_VALIDATION` (HTTP 400) — each share class of the fund contributes its `FINAL` accounting record with the greatest `accounting_date` on or before that date — a class with no such record contributes zero — and the response sums across classes: `total_market_value` is the sum of `gross_asset_value`, `total_accrued_expenses` is the sum of `expense_accrual_total`, and `total_net_assets` is the sum of the records' `total_net_assets`. If no class of the fund has any `FINAL` record on or before the `as_of_date`, the read fails with `ERR_NO_FINAL_NAV_IN_PERIOD`. The response echoes the `as_of_date` alongside the three totals.

The fiscal-year close is the `FundController`'s final act of the fund's year. The request supplies a `fiscal_year_end_date`, which must be a well-formed date matching the fund's `fiscal_year_end` month-and-day — a mismatch is rejected with `ERR_VALIDATION` (HTTP 400). Three blockers then stand in the way, evaluated in the order listed and ahead of the clock check, each surfacing as `ERR_FISCAL_CLOSE_BLOCKED` (HTTP 409): every accounting record of the fund's classes falling in the fiscal year must be `FINAL`; no break of the fund may stand `OPEN` or `ESCALATED`; and every regulatory filing whose `period_end` lies in the fiscal year must be `FILED`. The fiscal year is the closed interval from the day after the previous year's fiscal-year-end date — the same month-and-day one year earlier, with February 29 read as February 28 when the earlier year is not a leap year — through the `fiscal_year_end_date`. Finally, the close date must not lie after the logical clock date — a close dated after the clock is rejected with `ERR_PERIOD_NOT_ENDED`. A successful close records the date in the fund's `last_closed_fiscal_year_end`, and from that moment the closed year's accounting records can no longer be reopened — the lock enforced through `ERR_NAV_LOCKED_FISCAL_CLOSED` in §3.6.

## 4. Endpoint Definitions

Operations that create a new resource — a fund, share class, security, position, price observation, accounting record, accrual, waiver agreement, recoupment ledger entry, distribution, reconciliation break, fee invoice, regulatory filing, or the new observation produced by a fair-value override — return a `201 Created` status code. Operations that modify an existing resource — state transitions, approvals, payments, the escalation sweep, and the clock adjustment — return a `200 OK` status code. Request payloads, response payloads, and side effects are specified in the §3 narratives; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funds` | Create a fund | FundController |
| GET | `/funds/{fund_id}/trial-balance` | Trial balance aggregated from each class's latest FINAL record on or before a date | All roles |
| POST | `/funds/{fund_id}/fiscal-year-close` | Close a fiscal year and lock its records against reopening | FundController |
| POST | `/share-classes` | Create a share class for a fund | FundController |
| GET | `/share-classes/{share_class_id}` | Get a share class | All roles |
| GET | `/share-classes` | List share classes, optionally filtered by fund | All roles |
| POST | `/share-classes/{share_class_id}/capital-activity` | Record a subscription, redemption, or income posting | FundAccountant |
| GET | `/share-classes/{share_class_id}/performance` | Period return versus a supplied benchmark | All roles |
| POST | `/securities` | Create a security | FundAccountant |
| GET | `/securities/{security_id}` | Get a security | All roles |
| GET | `/securities/{id}/prices` | List a security's price observations | All roles |
| POST | `/positions` | Open a position for a share class | FundAccountant |
| GET | `/positions/{position_id}` | Get a position | All roles |
| GET | `/positions` | List positions, optionally filtered by class, security, or status | All roles |
| POST | `/price-observations` | Submit a price observation | FundAccountant |
| POST | `/price-observations/{price_observation_id}/approve` | Approve a submitted observation | PricingCommittee |
| POST | `/price-observations/{price_observation_id}/override` | Supersede an observation with a fair-value committee price | PricingCommittee |
| POST | `/nav-records` | Create the daily accounting record for a class, with its automatic ADMIN_FEE accrual | FundAccountant |
| GET | `/nav-records/{nav_record_id}` | Get an accounting record | All roles |
| GET | `/nav-records` | List accounting records, optionally filtered by class, status, or date | All roles |
| POST | `/nav-records/{nav_record_id}/finalize` | Finalize an ESTIMATED or REOPENED record (OCC-guarded; preparer may not finalize) | FundController |
| POST | `/nav-records/{nav_record_id}/reopen` | Reopen the class's latest FINAL record, while the fiscal year is open | FundController |
| POST | `/expense-accruals` | Manually add a non-ADMIN_FEE accrual to an ESTIMATED record's date | FundAccountant |
| GET | `/expense-accruals/{expense_accrual_id}` | Get an accrual | All roles |
| GET | `/expense-accruals` | List accruals, optionally filtered by class, date, category, or status | All roles |
| POST | `/waiver-agreements` | Create an expense-cap agreement for a class | FundController |
| GET | `/waiver-agreements` | List waiver agreements, optionally filtered by class | All roles |
| GET | `/waiver-agreements/{waiver_agreement_id}` | Get an agreement, including derived status and recoverable balance | All roles |
| POST | `/waiver-agreements/{waiver_agreement_id}/recoupments` | Recoup previously waived amounts oldest-first | FundController |
| GET | `/waiver-agreements/{id}/ledger` | List the agreement's waiver and recoupment ledger entries | All roles |
| POST | `/distributions` | Declare a distribution from snapshots of income and shares | FundAccountant |
| GET | `/distributions/{distribution_id}` | Get a distribution | All roles |
| GET | `/distributions` | List distributions, optionally filtered by class or status | All roles |
| POST | `/distributions/{distribution_id}/pay` | Pay a DECLARED distribution, optionally reinvesting into new shares | FundController |
| POST | `/distributions/{distribution_id}/cancel` | Cancel a DECLARED distribution with no balance movement | FundController |
| POST | `/reconciliation-breaks` | Record a custodian or broker position break | FundAccountant |
| GET | `/reconciliation-breaks/{reconciliation_break_id}` | Get a break | All roles |
| GET | `/reconciliation-breaks` | List breaks, optionally filtered by fund, position, or status | All roles |
| POST | `/reconciliation-breaks/{reconciliation_break_id}/resolve` | Resolve a break with no change or a position adjustment | FundController |
| POST | `/reconciliation-breaks/{reconciliation_break_id}/reopen` | Reopen a RESOLVED break, compensating its position adjustment | FundController |
| POST | `/reconciliation-breaks/escalate-overdue` | Sweep OPEN breaks more than five days old into ESCALATED | FundController |
| POST | `/fee-invoices` | Create an adviser or administrator fee invoice for a contiguous period | FundAccountant |
| GET | `/fee-invoices/{fee_invoice_id}` | Get a fee invoice | All roles |
| GET | `/fee-invoices` | List fee invoices, optionally filtered by fund, type, or status | All roles |
| POST | `/fee-invoices/{fee_invoice_id}/approve` | Approve a DRAFT invoice (approver differs from preparer) | FundController |
| POST | `/fee-invoices/{fee_invoice_id}/pay` | Pay an APPROVED invoice | FundController |
| POST | `/regulatory-filings` | Create a regulatory filing; the deadline derives from the filing type | ComplianceOfficer |
| GET | `/regulatory-filings/{regulatory_filing_id}` | Get a filing | All roles |
| GET | `/regulatory-filings` | List filings, optionally filtered by fund, type, or status | All roles |
| POST | `/regulatory-filings/{regulatory_filing_id}/submit-review` | Submit a DRAFT or AMENDED filing for review | ComplianceOfficer |
| POST | `/regulatory-filings/{regulatory_filing_id}/approve` | Approve a PENDING_REVIEW filing (gated on breaks and period end) | FundController |
| POST | `/regulatory-filings/{regulatory_filing_id}/file` | File an APPROVED filing; lateness derives against the deadline | ComplianceOfficer |
| POST | `/regulatory-filings/{regulatory_filing_id}/amend` | Amend a FILED filing, reopening the review cycle | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving capability) | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_NAV_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_BREAK_ESCALATED_BLOCKS` | 409 Conflict |
| `ERR_FISCAL_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_PRICE_DATE_FUTURE` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTION_NOT_PAYABLE` | 422 Unprocessable Entity |
| `ERR_RECOUP_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_TICKER_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NAV_DATE_NOT_SEQUENTIAL` | 409 Conflict |
| `ERR_DUPLICATE_PRICE_SOURCE` | 409 Conflict |
| `ERR_OVERRIDE_SOURCE_RESERVED` | 422 Unprocessable Entity |
| `ERR_MISSING_PRICE` | 422 Unprocessable Entity |
| `ERR_PRICE_NOT_APPROVED` | 409 Conflict |
| `ERR_NO_ESTIMABLE_NAV` | 422 Unprocessable Entity |
| `ERR_CATEGORY_SYSTEM_MANAGED` | 422 Unprocessable Entity |
| `ERR_CAP_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_FEE_PERIOD_NOT_CONTIGUOUS` | 409 Conflict |
| `ERR_NO_FINAL_NAV_IN_PERIOD` | 422 Unprocessable Entity |
| `ERR_NO_VARIANCE` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTION_DATE_ORDER` | 422 Unprocessable Entity |
| `ERR_NAV_NOT_FINAL` | 409 Conflict |
| `ERR_NAV_NOT_LATEST` | 409 Conflict |
| `ERR_NAV_LOCKED_FISCAL_CLOSED` | 409 Conflict |
| `ERR_NO_SHARES_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_REDEMPTION_EXCEEDS_SHARES` | 422 Unprocessable Entity |
| `ERR_RECOUP_AMOUNT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_NO_DISTRIBUTABLE_INCOME` | 422 Unprocessable Entity |
