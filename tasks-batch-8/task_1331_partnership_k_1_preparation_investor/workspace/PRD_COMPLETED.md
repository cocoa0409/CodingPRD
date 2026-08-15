# Partnership K-1 Administration API — Product Requirements Document

## 1. Introduction

Partnership tax administration sits where a legal agreement meets a ledger. Every fiscal year, a fund must translate its partnership agreement into numbers: a management fee comes off the top of ordinary income, the remaining income and gains are allocated across partners whose ownership stakes may have shifted mid-year, book capital accounts and outside tax basis are maintained side by side for every partner, states demand composite filings on behalf of non-resident partners, and foreign partners trigger quarterly federal withholding. The visible product of all of this work is one Schedule K-1 per partner, delivered against a statutory deadline — and occasionally amended after delivery, with the investor informed.

This document specifies the Partnership K-1 Administration API, a system operated by fund tax administrators that manages the full lifecycle from fund configuration through allocation, review, K-1 generation, delivery, amendment, and investor support. All resources are mounted under `/funds`. The design enforces segregation of duties between preparation and approval roles, keeps an append-only capital event ledger with two parallel balance interpretations (book capital and tax basis), propagates staleness through dependent artifacts whenever underlying ownership changes, and stamps every timestamp from a controllable logical clock so that deadline-sensitive behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the user's operational capacity. The system recognizes exactly five roles: `FundTaxAdmin`, `TaxPreparer`, `TaxReviewer`, `InvestorServicesRep`, and `Investor`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_MISSING_AUTH_CONTEXT`. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The five roles form a segregation-of-duties model. A `FundTaxAdmin` is the fund tax administrator operations lead and owns fund, tax-year, and partner configuration, ownership transfers, filing outcomes, and the logical clock. A `TaxPreparer` prepares capital events, allocation runs, special allocations, composite filings, withholding accruals and remittances, K-1 packages, and amendments — and never approves their own work. A `TaxReviewer` is the independent reviewer who approves tax years, locks allocation runs, approves or rejects special allocations, approves K-1 packages, returns or issues amendments, and reconciles withholding. An `InvestorServicesRep` handles investor-facing operations: delivering K-1 packages, reporting bounces, resending, and managing support tickets. An `Investor` is an individual partner who reads their own data, acknowledges K-1 delivery, and opens or reopens tickets for their own account.

When `X-User-Role` is `FundTaxAdmin`, `TaxPreparer`, `TaxReviewer`, or `InvestorServicesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `proposed_by_user_id` on a special allocation, `approved_by_user_id` on a K-1 package, or `answered_by_user_id` on a ticket, where a transition writes it — but does not compare it to any entity's `id`. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Partner`; ownership checks on any resource that references a partner compare the resource's `partner_id` field to `X-User-ID`. Consequently an `Investor` may read only their own partner record, their own K-1 packages, and their own tickets; may acknowledge delivery only of a package whose `partner_id` equals their `X-User-ID`; and may open or reopen tickets only where the ticket's `partner_id` equals their `X-User-ID`. Violations of these ownership rules are rejected with `ERR_FORBIDDEN_FOR_ROLE`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and out-of-range values are clamped to the nearest bound rather than rejected. The `offset` parameter sets the number of items skipped and defaults to 0, with negative values clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties resolved by creation order (earliest-created first). The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is still below `total_count`.

### 2.4. Common Resource Properties

Every resource in the system — funds, tax years, partners, capital account events, ownership transfers, allocation runs, allocation lines, special allocations, composite filings, withholding records, K-1 packages, K-1 amendments, and investor tickets — carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, stamped from the logical clock at creation and at every later modification. The `version` is a system-managed integer starting at 1 at creation that increments with every modification to the resource, including modifications caused by automatic cascades; a cascade that mutates a parent or child resource refreshes that resource's `updated_at` and increments its `version` independently of any client request.

### 2.5. The Logical Clock

The server keeps a logical clock that is the sole source of time. At startup, before any adjustment, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `FundTaxAdmin` may advance it through the clock-set capability by supplying a `to_iso8601` instant; the supplied instant replaces the clock value unconditionally (a missing or unparsable value is rejected with `ERR_INVALID_REQUEST`), and the response reports the new `current_utc`. Every server-stamped timestamp — `created_at`, `updated_at`, `delivered_at`, `filed_at`, and `computed_at` — and every clock-derived computation — ticket `due_at` and `is_escalated`, K-1 `is_late`, withholding months-late, and the day-of-year used by provisional projections — reads this logical clock. After the clock moves, clock-derived fields are recomputed lazily on the next read.

### 2.6. Monetary Precision and Basis-Point Conventions

All monetary values are stored and transported as integer cents. Rounding is round half-up to whole cents, applied exactly at the per-partner or per-step points each calculation names; intermediate quantities such as proration weights are carried as exact rational numbers with no intermediate rounding, and only final per-partner money amounts are rounded. Ownership shares, tax rates, and fee rates are expressed in basis points, where ten thousand basis points equal one hundred percent — for example, a value of 800 expresses an eight percent annual hurdle. Deadline and lateness judgments compare timestamps at second precision.

### 2.7. Optimistic Concurrency Control

Exactly one write operation participates in optimistic concurrency control: creating an allocation run. The request must carry `expected_tax_year_version` as a non-optional input field, holding the client’s last observed `version` of the target tax year. If the tax year’s current `version` has advanced beyond what the client observed, the create is rejected with `ERR_STALE_TAX_YEAR_VERSION` (HTTP 412), preventing the client from superseding state it never saw — creating a run legitimately supersedes any existing `COMPUTED` or `STALE` run of that tax year, so a stale view must not silently discard a run the client never observed. Within the §2.8 pipeline this check fires immediately after path existence and before every later check. No other endpoint accepts a version field.

### 2.8. Request Validation Order

Every request is evaluated against a fixed validation pipeline and is rejected with the first failing check in the order below; later checks never mask earlier ones.

1. Authentication context — the `X-User-ID` and `X-User-Role` headers are present and the role is recognized, else `ERR_MISSING_AUTH_CONTEXT`.
2. Role authorization — the role is permitted for the endpoint and, for the entity-backed `Investor`, the `X-User-ID` equals the `partner_id` of the accessed resource on partner-scoped reads, acknowledgements, and ticket creation or reopening, else `ERR_FORBIDDEN_FOR_ROLE`. Where the ownership comparison needs the loaded resource (K-1 packages and tickets), the resource is resolved first, so a nonexistent identifier yields `ERR_NOT_FOUND` rather than `ERR_FORBIDDEN_FOR_ROLE`; for partner records and ticket creation the comparison is made directly against the identifier in the path or body and fires first.
3. Request well-formedness — required fields are present, enum values are valid, and integer and date ranges are sane: basis-point shares between one and ten thousand inclusive, basis-point rates (hurdle, catch-up, carry, foreign-ownership cap, management-fee rate, fee discount, and composite rate) between zero and ten thousand inclusive, quarter between one and four, event amounts non-zero, `effective_from` strictly before `effective_to`, and `settlement_date` on or after `effective_date`, else `ERR_INVALID_REQUEST`.
4. Path existence — every identifier in the path resolves to an existing resource, validated left to right, else `ERR_NOT_FOUND`. Identifiers referenced in the request body (such as `fund_id`, `partner_id`, `tax_year_id`, or `k1_package_id`) must likewise resolve to existing resources, else `ERR_NOT_FOUND`.
5. State-transition legality — the requested transition is declared from the resource’s current state, else `ERR_INVALID_STATE_TRANSITION`.
6. Segregation of duties — on special-allocation approval and rejection, K-1 package approval, and amendment issuance, the approver’s or issuer’s `X-User-ID` must differ from the proposer, preparer, or submitter recorded on the resource, else `ERR_SEGREGATION_OF_DUTIES`.
7. Foreign-ownership projection — a transfer confirmation’s projected aggregate foreign ownership must remain within the fund cap, else `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED`.
8. Tax-year window rules — transfer confirmation with an `effective_date` in a `COMPLETED` tax year, capital events with an `effective_date` in a `COMPLETED` tax year, transfer settlement attempted before its `settlement_date`, special-allocation approval after the year has been `ALLOCATED`, `FINAL` run computation or run locking while the year is `OPEN` or `COMPLETED`, and composite filing while the year is `OPEN` or `BOOKS_CLOSED` are rejected with `ERR_TAX_YEAR_WINDOW_CLOSED` or `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`.
9. Interval overlap — special-allocation half-open windows per tax year, partner, and category, and transfer closed windows per transferor, else `ERR_SPECIAL_ALLOCATION_OVERLAP` or `ERR_TRANSFER_WINDOW_OVERLAP`.
10. Uniqueness — one tax year per fund and calendar year, one composite filing per state per tax year, one withholding record per partner, tax year, and quarter, at most one non-`ISSUED` amendment per K-1 package, at most one generation set of non-`SUPERSEDED` K-1 packages per tax year, and a fund `ein` unique across funds, else the corresponding duplicate error (`ERR_DUPLICATE_TAX_YEAR`, `ERR_DUPLICATE_COMPOSITE_FILING`, `ERR_DUPLICATE_WITHHOLDING_ACCRUAL`, `ERR_AMENDMENT_ALREADY_ACTIVE`, `ERR_K1_ALREADY_GENERATED`, or `ERR_INVALID_REQUEST` for a duplicate `ein`).
11. Cross-fund referential consistency — referenced partners and tax years belong to the same fund, transferor differs from transferee, reversal targets exist and are not mirrors, and a capital event’s `effective_date` falls inside the referenced tax year’s calendar year, else `ERR_CROSS_FUND_REFERENCE`, `ERR_SAME_PARTNER_TRANSFER`, `ERR_REVERSAL_OF_REVERSAL`, or `ERR_INVALID_REQUEST`. This check guards capital-event creation and reversal, transfer creation, special-allocation creation, composite-filing creation, withholding accruals, amendment creation, and ticket creation.
12. Ledger guards — a distribution may not exceed current book capital, a remittance may not exceed the remaining accrued amount, and a transferred share may not exceed the transferor’s current ownership, else `ERR_DISTRIBUTION_EXCEEDS_CAPITAL`, `ERR_REMIT_EXCEEDS_ACCRUED`, or `ERR_INSUFFICIENT_OWNERSHIP`.
13. Allocation prerequisites — a locked, non-stale `FINAL` run is required for K-1 generation, K-1 package approval, tax-year submit-review and approval, and composite filing, else `ERR_ALLOCATION_NOT_LOCKED` or `ERR_ALLOCATION_STALE`.
14. Aggregate bounds — approved special-allocation shares per category at lock time, and apportionment shares per tax year at filing creation, must not exceed ten thousand basis points, else `ERR_SPECIAL_ALLOCATION_OVERFLOW` or `ERR_APPORTIONMENT_OVERFLOW`.
15. Non-empty input sets — allocation computation and books closing require at least one active partner, withholding accrual requires at least one foreign active partner, composite filing requires a non-empty included-partner set, and withdrawal requires an exactly zero book capital balance, else `ERR_NO_ALLOCABLE_PARTNERS`, `ERR_NO_FOREIGN_PARTNERS`, `ERR_COMPOSITE_PARTNER_INELIGIBLE`, or `ERR_PARTNER_CAPITAL_NOT_ZERO`.

### 2.9. The Append-Only Capital Ledger

Each partner’s capital history is an append-only stream of capital account events; nothing is ever removed from the stream. Corrections do not edit history — reversing an event appends a mirror event carrying the negated amount, and both the original and the mirror remain in the stream forever. All derived balances are produced by replaying the full stream in chronological order, and the replay runs over every event the partner has: posted originals, reversed originals, and posted mirrors alike. Two parallel readings of the same stream are maintained — book capital and tax basis — whose precise rules appear in §3.2.

### 2.10. Staleness, Supersession, and Cascade Consistency

Dependent artifacts track the inputs they were computed from. An allocation run snapshots ownership and balances at lock time; a K-1 package snapshots a locked run. Because only `COMPUTED` or `STALE` runs are superseded, several `LOCKED` `FINAL` runs of one tax year may coexist; wherever the workflows below refer to the year's locked `FINAL` run, they mean the `LOCKED` `FINAL` run with the highest `run_seq`. When ownership moves — a transfer settling into a tax year — or when a tax year’s books are reopened, the year’s `LOCKED` run automatically becomes `STALE`, and every K-1 package of that year still in `REVIEWED` or `APPROVED` preparation reverts to `GENERATED`. Creating a newer allocation run for a tax year automatically supersedes the year’s older `COMPUTED` or `STALE` runs. Issuing an amendment supersedes the delivered package, creates a replacement package of the next generation, and opens an investor-communication ticket. Bubble-up transitions keep parents aligned with their children: locking a `FINAL` run moves a `BOOKS_CLOSED` tax year to `ALLOCATED`; the last outstanding package delivery moves an `APPROVED` tax year to `COMPLETED`; and issuing an amendment moves a `COMPLETED` tax year back to `APPROVED`. Each of these automatic mutations refreshes `updated_at` and increments `version` on every resource it touches.

## 3. Business Logic & Workflows

### 3.1. Fund Configuration and Tax-Year Setup

A `FundTaxAdmin` establishes a fund by supplying its `legal_name` and `ein` — the employer identification number must be unique across funds, and a duplicate is rejected with `ERR_INVALID_REQUEST`. The fund’s economics are fixed at creation through its waterfall and fee configuration: `waterfall_hurdle_rate_bps` is the preferred-return annual hurdle in basis points (a value of 800 means eight percent), `waterfall_catchup_bps` caps the general partner’s catch-up as a basis-point share of the preferred pool actually paid (2000 means twenty percent), `waterfall_carry_bps` is the general partner’s carried-interest share of the residual tier, `foreign_ownership_cap_pct_bps` is the maximum aggregate foreign-partner ownership share of total active ownership (an inclusive upper bound, so 5000 permits exactly fifty percent), `management_fee_rate_bps` is the annual management fee charged against total active capital commitments, `fee_discount_threshold_cents` is the gross ordinary income level strictly below which a fee discount applies, and `fee_discount_bps` is the size of that discount (5000 halves the fee).

Within a fund, a `FundTaxAdmin` opens a tax year by providing the `fund_id`, the calendar `year`, and three fund-level income totals: `gross_ordinary_income_cents` before the management fee, `capital_gain_cents`, and `interest_income_cents`. The flag `federal_extension_filed` records whether a Form 7004 extension was filed and defaults to false. Only one tax year may exist per fund and calendar year; a duplicate is rejected with `ERR_DUPLICATE_TAX_YEAR`.

Two derived amounts are computed once, at tax-year creation, in a pinned top-down order that is never iterated, because the discount test depends on gross income while the fee reduces net income. First, the fee base is the sum of `capital_commitment_cents` over the fund’s partners whose status is `ACTIVE` at creation time. Second, the gross fee is that base multiplied by `management_fee_rate_bps` and divided by ten thousand, rounded half-up to integer cents. Third, the discount applies if and only if `gross_ordinary_income_cents` is strictly below `fee_discount_threshold_cents` — income exactly equal to the threshold receives no discount. Fourth, `management_fee_cents` is, when the discount applies, the gross fee multiplied by ten thousand minus `fee_discount_bps` and divided by ten thousand, rounded half-up; otherwise it is the gross fee unchanged. Fifth, `net_ordinary_income_cents` is `gross_ordinary_income_cents` minus `management_fee_cents`.

Creation also fixes the year’s delivery deadline: `k1_delivery_deadline` is March 15 of the year following the tax year at 23:59:59 UTC, moving to September 15 of that following year at 23:59:59 UTC when `federal_extension_filed` is true. A new tax year begins in `OPEN` status. The tax-year list may be filtered by `fund_id` and `status`.

### 3.2. Partner Admission and the Capital Event Ledger

A `FundTaxAdmin` admits a partner with the fund’s `fund_id`, the partner’s `legal_name`, a `partner_type` of `US_INDIVIDUAL`, `US_ENTITY`, `TAX_EXEMPT`, `FOREIGN_INDIVIDUAL`, or `FOREIGN_ENTITY`, a `partner_class` of `GENERAL` or `LIMITED`, a two-letter `residency_state` (or `XX` for foreign partners) — exactly two uppercase alphabetic characters, else `ERR_INVALID_REQUEST` — an `ownership_pct_bps` share at admission (ten thousand being one hundred percent), a `capital_commitment_cents` total commitment, and an `admission_date` in ISO year-month-day form. A newly admitted partner starts `ACTIVE` with all computed balances at zero. The derived flag `is_foreign` is true exactly when the `partner_type` is `FOREIGN_INDIVIDUAL` or `FOREIGN_ENTITY`. Each partner record also carries three computed ledger readings — `capital_account_balance_cents` (book capital), `tax_basis_cents` (outside basis), and `excess_distribution_gain_cents` — plus `current_ownership_pct_bps`, the ownership share after applying every `SETTLED` transfer whose `effective_date` is on or before the current clock date — zero while the partner's `admission_date` is still in the future relative to the clock. The partner list may be filtered by `fund_id`, `status`, and `partner_type`.

Once admitted, a partner’s capital history is written as capital account events, posted by a `TaxPreparer` with the `partner_id`, the `tax_year_id`, an `event_type` of `CONTRIBUTION`, `DISTRIBUTION`, `ALLOCATION_SHARE`, `TRANSFER_IN`, `TRANSFER_OUT`, or `ADJUSTMENT`, a signed non-zero `amount_cents`, an `effective_date`, and an optional `memo` that defaults to null. The referenced partner and tax year must belong to the same fund, else `ERR_CROSS_FUND_REFERENCE`; the `effective_date` must fall inside the referenced tax year’s calendar year, else the request is rejected as `ERR_INVALID_REQUEST`; and an `effective_date` landing in a `COMPLETED` tax year — the tax year of the partner’s fund whose calendar year contains the date — is rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`. A `DISTRIBUTION` may not exceed the partner’s current `capital_account_balance_cents` — a distribution exactly equal to the balance is allowed and leaves exactly zero — and an excessive distribution is rejected with `ERR_DISTRIBUTION_EXCEEDS_CAPITAL`. Each event receives a `sequence_no`, a per-partner monotonically increasing integer assigned in creation order starting at one, and begins life `POSTED`. Posting an event replays the partner’s ledger, updates the partner’s computed balances, and increments the partner’s `version`.

The replay walks the partner’s complete event stream — posted originals, reversed originals, and posted mirrors, since nothing is ever removed — ordered by `effective_date` ascending and then `sequence_no` ascending. Events fall into two sign classes: `CONTRIBUTION`, `TRANSFER_IN`, `ALLOCATION_SHARE`, and `ADJUSTMENT` are positive-class and add their `amount_cents`; `DISTRIBUTION` and `TRANSFER_OUT` are negative-class and subtract theirs. The book-capital reading is a plain signed sum over the ordered stream with no floor; it can go negative only transiently, because distributions beyond the current balance are rejected. The tax-basis reading replays the same ordered stream but skips `ADJUSTMENT` events entirely — they are book-only Section 704(b) revaluations — running a basis that starts at zero: a positive-class event adds its amount; a negative-class event whose amount fits within the running basis subtracts it; and a negative-class event whose amount exceeds the running basis spills the excess into `excess_distribution_gain_cents` and floors the basis at zero. A contribution posted after such a flooring rebuilds the basis from zero. Consequently identical event streams yield a `tax_basis_cents` different from `capital_account_balance_cents` whenever a distribution has exceeded the running basis.

Correction is by reversal, performed by a `TaxPreparer`, and only an original event in `POSTED` status may be reversed. Reversing a mirror — an event whose `reverses_event_id` is set — is rejected with `ERR_REVERSAL_OF_REVERSAL`, and reversing an already-`REVERSED` event is rejected with `ERR_INVALID_STATE_TRANSITION`. Reversal creates a mirror event sharing the original’s `partner_id`, `tax_year_id`, and `event_type`, carrying the negation of the original’s `amount_cents`, the original’s `effective_date`, an optional `memo` taken from the reversal request body (null when omitted, not copied from the original), a `reverses_event_id` pointing at the original, and `POSTED` status; the original then becomes `REVERSED`. Both remain in the replay stream, so the partner’s balances are recomputed by full chronological replay, and both the original event’s `version` and the partner’s `version` increment. The event list may be filtered by `partner_id`, `tax_year_id`, and `reverses_event_id`.

A partner exits the fund when a `FundTaxAdmin` withdraws them. Withdrawal requires the partner’s `capital_account_balance_cents` to be exactly zero cents, else `ERR_PARTNER_CAPITAL_NOT_ZERO`, and requires that no K-1 package of the partner is in `GENERATED`, `REVIEWED`, or `APPROVED` preparation, else `ERR_INVALID_STATE_TRANSITION`. A successful withdrawal moves the partner from `ACTIVE` to `WITHDRAWN` — the terminal state — and increments the partner’s `version`.

### 3.3. Ownership Transfers

Mid-year ownership changes are modeled as ownership transfers, proposed by a `FundTaxAdmin` with the `fund_id`, the `transferor_partner_id`, the `transferee_partner_id`, the transferred share `pct_bps`, an `effective_date` on which economic ownership passes, and a `settlement_date` that must not fall before the `effective_date` (a settlement date earlier than the effective date is rejected as `ERR_INVALID_REQUEST`). The two partners must belong to the stated fund — cross-fund references are rejected with `ERR_CROSS_FUND_REFERENCE` — and must be distinct, else `ERR_SAME_PARTNER_TRANSFER`. A proposal begins `PROPOSED` with `transferred_capital_cents` still null.

Confirmation moves a transfer from `PROPOSED` to `CONFIRMED` and re-verifies the full battery of transfer checks. Both partners must exist in the same fund and be distinct, and both must be `ACTIVE`, else `ERR_INVALID_STATE_TRANSITION`. The projected aggregate foreign-partner ownership share after the transfer must not exceed the fund’s `foreign_ownership_cap_pct_bps` — because the cap is inclusive, a projection landing exactly on it passes — and an excess is rejected with `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED`. The tax year containing the `effective_date` must not be `COMPLETED`, else `ERR_TAX_YEAR_WINDOW_CLOSED`. The closed interval running from `effective_date` through `settlement_date` must not intersect any other `PROPOSED`, `CONFIRMED`, or `SETTLED` transfer of the same transferor, and sharing an endpoint date counts as overlap, else `ERR_TRANSFER_WINDOW_OVERLAP`. Finally, `pct_bps` must not exceed the transferor’s `current_ownership_pct_bps` — transferring the entire current share is permitted — else `ERR_INSUFFICIENT_OWNERSHIP`. Confirmation increments the transfer’s `version`.

Settlement moves a `CONFIRMED` transfer to `SETTLED` and is allowed only once the current clock date has reached the `settlement_date`; settling earlier is rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`. At settlement the system computes `transferred_capital_cents`: the transferor’s book capital balance as of the `effective_date`, multiplied by `pct_bps` and divided by the transferor’s ownership share in basis points that was in effect during the proration segment immediately before the `effective_date` (that is, the share in effect on the day before the `effective_date`), rounded half-up to integer cents; when that prior share is zero, `transferred_capital_cents` is zero. Settlement then cascades in four hops. First, a `TRANSFER_OUT` capital account event is created on the transferor and a `TRANSFER_IN` event on the transferee, each for `transferred_capital_cents` with the transfer’s `effective_date` and with `tax_year_id` naming the tax year of the fund whose calendar year contains the `effective_date` (null when no such tax year exists). Second, because those events enter the replay stream, both partners’ `capital_account_balance_cents`, `tax_basis_cents`, and `current_ownership_pct_bps` are recomputed. Third, every `LOCKED` allocation run whose tax year contains the `effective_date` transitions to `STALE`, since the recompute invalidated its proration inputs. Fourth, every K-1 package of such a tax year whose preparation is `REVIEWED` or `APPROVED` reverts to `GENERATED`. The transfer’s `version` and both partners’ `version` increment.

A transfer may also be cancelled, moving from `PROPOSED` or `CONFIRMED` to `CANCELLED`, with no preconditions and no side effects. The transfer list may be filtered by `fund_id`, `transferor_partner_id`, `transferee_partner_id`, and `status`.

### 3.4. Proration, Special Allocations, and the Allocation Engine

Allocation rests on day-weighted ownership. The tax year runs from January 1 through December 31 and is always normalized to 365 days, even in leap years. A partner whose `admission_date` is on or before January 1 holds their `ownership_pct_bps` for the whole year; a partner admitted later holds zero until the `admission_date` and their full share from that date inclusive. Settled transfers are then applied in `effective_date` ascending order, ties broken by the transfer’s `created_at` and then by creation order: from the `effective_date` inclusive onward, the transferor’s share decreases by `pct_bps` and the transferee’s share increases by the same amount. An admission taking effect on the same date as a transfer applies before that transfer. Each partner’s day-weighted share is the sum over the year’s day-segments of the basis-point share in effect during a segment multiplied by the number of days in that segment, and the ownership weight used downstream is that sum divided by 365, carried as an exact rational number with no intermediate rounding — only final per-partner money amounts are rounded. A transfer effective on January 1 applies for the whole year; one effective on December 31 applies for exactly one day. The proration considers the fund’s partners whose status is `ACTIVE` at the moment the run is computed, together with every `SETTLED` transfer of the fund whose `effective_date` falls inside the tax year.

A `TaxPreparer` computes a new allocation run by supplying the `tax_year_id`, a `run_kind` of `PROVISIONAL` or `FINAL`, and `expected_tax_year_version` per the optimistic-concurrency rule of §2.7 — a stale tax-year view is rejected with `ERR_STALE_TAX_YEAR_VERSION` (HTTP 412). Computation requires at least one `ACTIVE` partner, else `ERR_NO_ALLOCABLE_PARTNERS`. Each run receives a `run_seq`, a per-tax-year increasing sequence starting at one, and a `computed_at` timestamp read from the logical clock. Creating the run automatically supersedes any existing `COMPUTED` or `STALE` run of the same tax year — those become `SUPERSEDED` — and increments the tax year’s `version`. The run records the category totals it actually allocated as `ordinary_total_cents`, `capital_gain_total_cents`, and `interest_total_cents`.

The two run kinds differ in timing and inputs. A `PROVISIONAL` run is allowed while the tax year is `OPEN` or `BOOKS_CLOSED` — computing one in any later status is likewise rejected with `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`; it ignores all special allocations and annualizes each stored category total — the tax year’s net ordinary income, capital gain, and interest as persisted at compute time — by multiplying by 365 and dividing by the current day-of-year of the logical clock, rounding half-up to integer cents, with the day-of-year clamped between one and 365. A `FINAL` run requires the tax year to be `BOOKS_CLOSED`, `ALLOCATED`, `UNDER_REVIEW`, or `APPROVED` — computing a `FINAL` run while the year is `OPEN` or `COMPLETED` is rejected with `ERR_TAX_YEAR_NOT_BOOKS_CLOSED` — and it uses the stored totals as-is while applying the tax year’s `APPROVED` special allocations whose half-open windows intersect the tax year.

Special allocations direct a fixed share of one category to one partner. A `TaxPreparer` proposes one with the `tax_year_id`, `partner_id`, `category` (`ORDINARY`, `CAPITAL_GAIN`, or `INTEREST`), a `target_pct_bps` share of the category total, and a half-open effective window from `effective_from` inclusive to `effective_to` exclusive; the `effective_to` must fall strictly after `effective_from`. The referenced partner and tax year must belong to the same fund, else `ERR_CROSS_FUND_REFERENCE`. A proposal begins `PROPOSED` with `proposed_by_user_id` recorded from the proposer’s `X-User-ID`. Approval by a `TaxReviewer` enforces three conditions, in this order: the approver’s `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the tax year must be `OPEN` or `BOOKS_CLOSED`, approval after the year is `ALLOCATED` being rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`; and the half-open window must not intersect any other `PROPOSED` or `APPROVED` special allocation with the same tax year, partner, and category — windows that merely touch, one’s `effective_to` equal to the other’s `effective_from`, do not overlap — else `ERR_SPECIAL_ALLOCATION_OVERLAP`. Both approval and rejection record `reviewed_by_user_id`; rejection likewise requires a reviewer different from the proposer. The special-allocation list may be filtered by `tax_year_id`, `partner_id`, `category`, and `status`.

Within a run, each category total is distributed to partners tier by tier, rounding half-up to integer cents at every per-partner assignment; after rounding, any residual cents are distributed to the partner with the largest unrounded share in that tier, with ties broken by earlier `admission_date`, then by earlier partner `created_at`, and then by creation order — never by identifier. If every participant’s proration weight is zero, the split falls back to equal weights for all participants. For every category, the run’s allocation lines sum to exactly the category total, so no cents drift.

For `ORDINARY` and `INTEREST`, two tiers apply. In the special tier — `FINAL` runs only — each applicable `APPROVED` special allocation, processed in order of its `created_at` ascending, assigns its partner the category total multiplied by `target_pct_bps` and divided by ten thousand, rounded half-up, and each assignment is subtracted from the remaining pool. In the pro-rata tier, the remaining pool is split across the non-special partners by their proration weights renormalized over that group.

`CAPITAL_GAIN` follows a waterfall, and special allocations never apply to it. The preferred tier computes each `LIMITED` partner’s preferred need as the fund’s `waterfall_hurdle_rate_bps` multiplied by the partner’s beginning capital and divided by ten thousand; the preferred pool is the smaller of the capital-gain total and the sum of all preferred needs, and if the pool falls short, each `LIMITED` partner is scaled down pro rata — their need multiplied by the pool and divided by the sum of needs, rounded. The catch-up tier caps itself at the preferred pool multiplied by `waterfall_catchup_bps` and divided by ten thousand, rounded half-up; the catch-up pool is the smaller of the capital-gain total remaining after the preferred pool and that cap, and it goes entirely to `GENERAL` partners split by their renormalized weights. When the capital-gain total is zero or negative, the preferred and catch-up pools are both zero and the entire total falls through to the residual tier; likewise, when no `GENERAL` partner participates, the catch-up tier is skipped and its would-be pool remains in the residual. The residual tier takes whatever capital gain remains after the preferred and catch-up pools: the limited-partner pool is that remainder multiplied by ten thousand minus `waterfall_carry_bps` and divided by ten thousand, rounded half-up, split over `LIMITED` partners by renormalized weight, and the general-partner pool is the remainder minus the limited-partner pool, split over `GENERAL` partners by renormalized weight; when only one of the two classes participates, the entire remainder goes to that class.

Beginning capital, which drives the preferred tier, is each partner’s book-capital replay over that partner’s events with an `effective_date` on or before January 1 of the tax year, excluding `ALLOCATION_SHARE` events — this breaks what would otherwise be a circular dependency between the preferred return and the current year’s allocation.

Each partner-and-category pair of a run yields one allocation line carrying the `run_id`, the `partner_id`, the `category`, an `amount_cents` that may be negative for losses, and an `applied_mechanism` naming the dominant mechanism that produced the line — `PRO_RATA`, `SPECIAL`, `PREFERRED`, `CATCHUP`, or `RESIDUAL`. For `ORDINARY` and `INTEREST` the line is `SPECIAL` when the partner received a special-tier assignment in that category and `PRO_RATA` otherwise. For `CAPITAL_GAIN` the dominant mechanism is the waterfall tier contributing the largest absolute amount to the line, with ties (including all-zero lines) resolved in favor of `PREFERRED`, then `CATCHUP`, then `RESIDUAL`. Lines can be listed per run, or per partner across runs, and the run list itself may be filtered by `tax_year_id` and `status`.

### 3.5. Locking, Review, and the Tax-Year Approval Cycle

The tax year moves through `OPEN`, `BOOKS_CLOSED`, `ALLOCATED`, `UNDER_REVIEW`, `APPROVED`, and `COMPLETED`. Closing the books, performed by a `FundTaxAdmin`, moves the year from `OPEN` to `BOOKS_CLOSED` and requires at least one `ACTIVE` partner in the fund, else `ERR_NO_ALLOCABLE_PARTNERS`; it increments the tax year’s `version`.

Locking an allocation run is a `TaxReviewer` action with three preconditions. Only a `FINAL` run can be locked — locking a `PROVISIONAL` run is rejected with `ERR_INVALID_STATE_TRANSITION`. The tax year must be `BOOKS_CLOSED`, `ALLOCATED`, `UNDER_REVIEW`, or `APPROVED`, else `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`. And for each category, the sum of `target_pct_bps` across the tax year’s `APPROVED` special allocations must not exceed ten thousand basis points, else `ERR_SPECIAL_ALLOCATION_OVERFLOW`. A successful lock moves the run from `COMPUTED` to `LOCKED` and posts one `ALLOCATION_SHARE` capital account event per allocated partner — that is, per partner with lines in the run, even when the summed amount is exactly zero: the partner on the line, the run’s tax year, an `amount_cents` equal to the sum of that partner’s line amounts across all categories (which may be negative for losses), an `effective_date` of December 31 of the tax year, and a `memo` carrying the run’s id. Those events enter the capital replay and raise or lower each partner’s book capital and tax basis. If the tax year was `BOOKS_CLOSED`, it bubbles up to `ALLOCATED`; in any other state its status is unchanged. Both the run’s `version` and the tax year’s `version` increment.

With a locked run in place, a `TaxPreparer` submits the year for review, moving it from `ALLOCATED` to `UNDER_REVIEW`; the submission requires that a `LOCKED` `FINAL` run exists for the year, else `ERR_ALLOCATION_NOT_LOCKED`. A `TaxReviewer` then approves the year, moving it from `UNDER_REVIEW` to `APPROVED`; approval requires that the year’s locked `FINAL` run is not `STALE`, else `ERR_ALLOCATION_STALE`. Each transition increments the tax year’s `version`.

Completion is automatic: once at least one K-1 package exists for the year and every non-`SUPERSEDED` package has reached preparation `DELIVERED`, the year moves from `APPROVED` to `COMPLETED` and its `version` increments. `COMPLETED` is quiescent rather than absorbing — issuing a K-1 amendment for a package of the year reopens it to `APPROVED`, because the replacement package has not yet been delivered.

Reopening is the deliberate counterpart. A `FundTaxAdmin` may move an `APPROVED` year back to `BOOKS_CLOSED`, but only while no K-1 package of the year currently stands at preparation `DELIVERED` (a previously delivered package that has since been `SUPERSEDED` does not block reopening), else `ERR_K1_ALREADY_GENERATED`. Reopening cascades: the year’s `LOCKED` run becomes `STALE` as the first hop, and — as the second hop caused by that staleness — every package of the year in `REVIEWED` or `APPROVED` preparation reverts to `GENERATED`. The tax year’s `version` increments.

Staleness itself is always system-driven: a `LOCKED` run becomes `STALE` when an ownership transfer settles into its tax year or when the year is reopened, and in both cases packages snapshotting that run in `REVIEWED` or `APPROVED` preparation revert to `GENERATED`. Separately, creating a newer run for the same tax year moves any older `COMPUTED` or `STALE` run to `SUPERSEDED`, the run’s terminal state.

### 3.6. State Composite Filings

For non-resident partners, the fund files composite state returns. A `TaxPreparer` creates a filing — one per state per tax year — with the `tax_year_id`, the two-letter `state_code` (exactly two uppercase alphabetic characters, else `ERR_INVALID_REQUEST`), the `apportionment_pct_bps` share of fund income apportioned to that state, the state’s `composite_rate_bps`, and a `min_income_cents` minimum state-source income for inclusion. A second filing for the same state in the same tax year is rejected with `ERR_DUPLICATE_COMPOSITE_FILING`, and the sum of `apportionment_pct_bps` across all of a tax year’s filings must not exceed ten thousand — a sum of exactly ten thousand is allowed — else `ERR_APPORTIONMENT_OVERFLOW`. A new filing begins `DRAFT`; when a `LOCKED` `FINAL` run already exists at creation, the included partners and totals are computed immediately, and otherwise the totals remain zero until filing.

Eligibility is decided per partner against the year’s locked `FINAL` run, using each partner’s allocated total — the sum of that partner’s line amounts across all categories in the run. Four conditions must all hold: the partner is not foreign, because foreign partners are withheld federally and never composited — they are silently excluded from eligibility, and an explicitly empty result errors only at filing time; the partner’s `residency_state` differs from the filing’s `state_code`, since residents file individually; the partner is `ACTIVE`; and the partner’s rounded state-source income is at least `min_income_cents`, with income exactly equal to the minimum included.

The rounding order is pinned per-partner-then-sum, and the alternative of summing first and rounding once is forbidden because it yields different cents. Each eligible partner’s state-source income is their allocated total multiplied by `apportionment_pct_bps` and divided by ten thousand, rounded half-up; each partner’s composite tax is their state-source income multiplied by `composite_rate_bps` and divided by ten thousand, again rounded half-up. The filing’s `total_state_source_income_cents` and `total_composite_tax_cents` are the sums of those rounded per-partner values over the included partners, and `included_partner_ids` lists the included partners sorted by partner `created_at` ascending.

Filing, performed by a `TaxPreparer`, moves the filing from `DRAFT` to `FILED` and enforces three prerequisites: the tax year must be `ALLOCATED`, `UNDER_REVIEW`, `APPROVED`, or `COMPLETED`, else `ERR_TAX_YEAR_NOT_BOOKS_CLOSED`; a `LOCKED` `FINAL` run must exist, else `ERR_ALLOCATION_NOT_LOCKED`, and must not be `STALE`, else `ERR_ALLOCATION_STALE`; and the recomputed `included_partner_ids` must be non-empty, else `ERR_COMPOSITE_PARTNER_INELIGIBLE`. Filing recomputes `included_partner_ids`, `total_state_source_income_cents`, and `total_composite_tax_cents` from the locked run and stamps `filed_at` from the logical clock.

A `FundTaxAdmin` records the state’s response through the `outcome` input. An outcome of `ACCEPTED` moves the filing from `FILED` to `ACCEPTED`, its terminal state. An outcome of `REJECTED` returns the filing to `DRAFT`, resets `filed_at` to null, and leaves the filing free to be corrected and re-filed. The filing list may be filtered by `tax_year_id`, `state_code`, and `status`.

### 3.7. Foreign Partner Withholding

Foreign partners are subject to quarterly withholding on effectively connected taxable income. A `TaxPreparer` bulk-accrues one quarter at a time by supplying the `tax_year_id`, a `quarter` from one to four, and a `method` of `SAFE_HARBOR` or `CURRENT_ACTUAL`; the call creates one withholding record per foreign partner with `ACTIVE` status in the tax year’s fund. Only one record may exist per partner, tax year, and quarter — a second accrual for an existing triple is rejected with `ERR_DUPLICATE_WITHHOLDING_ACCRUAL` — and if the tax year has no foreign `ACTIVE` partners at all, the bulk call fails with `ERR_NO_FOREIGN_PARTNERS`. A `CURRENT_ACTUAL` accrual additionally requires a `LOCKED`, non-`STALE` `FINAL` run for the year, else `ERR_ALLOCATION_NOT_LOCKED` or `ERR_ALLOCATION_STALE`; a `SAFE_HARBOR` accrual has no such requirement. The response carries the created records as an array ordered by partner `created_at` ascending. Each record carries the `partner_id`, `tax_year_id`, `quarter`, `method`, the `annual_ecti_cents` income basis used by the method, the applicable `rate_bps`, the computed `accrued_cents`, a `remitted_cents` starting at zero, a `due_date`, a `penalty_cents` starting at zero, and an initial status of `ACCRUED`. The rate is thirty-seven hundred basis points for a `FOREIGN_INDIVIDUAL` and twenty-one hundred for a `FOREIGN_ENTITY`. Quarterly due dates fall on April 15 for the first quarter, June 15 for the second, September 15 for the third, and December 15 for the fourth, all within the tax year itself.

Under `CURRENT_ACTUAL`, the partner’s annual effectively connected taxable income is the sum of that partner’s allocation line amounts across all categories in the year’s `LOCKED` `FINAL` run, and this annual figure is stored in `annual_ecti_cents`. The quarterly base for each of the first three quarters is the annual amount divided by four and rounded down to a whole cent, while the fourth quarter’s base is the annual amount minus three times that floored quarter, so any division remainder lands in the fourth quarter. Each quarter’s `accrued_cents` is its base multiplied by `rate_bps` and divided by ten thousand, rounded half-up.

Under `SAFE_HARBOR`, the basis is the prior year: the system sums `accrued_cents` over the partner’s withholding records whose tax year is the immediately preceding year, in any status, taking zero when no such records exist, and stores that prior-year total in `annual_ecti_cents`. Each quarter’s `accrued_cents` is then the prior-year total multiplied by one hundred and ten percent and divided by four, rounded half-up to integer cents — identical for all four quarters. The two methods diverge whenever the current year’s allocation differs from one hundred and ten percent of last year’s withholding.

Remittances are posted by a `TaxPreparer` with an `amount_cents`, which must be a positive integer, else `ERR_INVALID_REQUEST`. The cumulative `remitted_cents` plus the new amount must not exceed `accrued_cents`, else `ERR_REMIT_EXCEEDS_ACCRUED`. A partial remittance moves the record from `ACCRUED` to `PARTIALLY_REMITTED`, and further partial remittances keep it there while the cumulative total remains below the accrued amount; a remittance that completes the accrued amount exactly moves the record to `REMITTED` with `remitted_cents` equal to `accrued_cents`.

Reconciliation, a `TaxReviewer` action, closes a record from `ACCRUED`, `PARTIALLY_REMITTED`, or `REMITTED` into the terminal `RECONCILED` state and computes `penalty_cents`. The underpayment is `accrued_cents` minus `remitted_cents`, floored at zero. The months late are the complete calendar months between the `due_date` and the current clock date: twelve times the difference in calendar years plus the difference in calendar months, reduced by one when the clock’s day-of-month is earlier than the due date’s day-of-month, and never below zero — remitting or reconciling on or before the due date yields zero months late. The effective months are the months late capped at five, and the penalty is the underpayment multiplied by five hundred basis points per month and by the effective months, divided by ten thousand, and rounded half-up to integer cents. A record fully remitted by its due date therefore reconciles with a zero penalty. The withholding list may be filtered by `partner_id`, `tax_year_id`, `quarter`, and `status`.

### 3.8. K-1 Generation, Delivery, and Amendment

Once a tax year is `APPROVED`, a `TaxPreparer` generates K-1 packages in bulk for the year by supplying the `tax_year_id`. Generation requires the year to be `APPROVED` — any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — and requires a `LOCKED` `FINAL` run that is not `STALE`, else `ERR_ALLOCATION_NOT_LOCKED` or `ERR_ALLOCATION_STALE`. At most one generation set of non-`SUPERSEDED` packages may exist per tax year, so a second generation over live packages is rejected with `ERR_K1_ALREADY_GENERATED`. One package is created per `ACTIVE` partner, and the packages are created and returned in partner `created_at` ascending order. Each package is generation one — `generation` set to 1 and `supersedes_k1_id` null — with `run_id` pointing at the locked run, preparation `GENERATED`, delivery `PENDING`, and a `line_snapshot` that freezes the partner’s `ordinary_cents`, `capital_gain_cents`, `interest_cents`, `capital_beginning_cents`, and `capital_ending_cents` from the locked run and the capital replay — the beginning figure is the book-capital replay over that partner’s events with an `effective_date` on or before January 1 of the tax year and the ending figure the replay over events on or before December 31, each across all event types including `ALLOCATION_SHARE`. Two cascades follow creation: for every foreign partner receiving a package, a fourth-quarter `CURRENT_ACTUAL` withholding record is accrued — skipped silently when such a record already exists for that partner, tax year, and quarter — and every `DRAFT` composite filing of the tax year recomputes its totals now that per-partner income is snapshotted.

A K-1 package carries two independent state dimensions. The `prep_status` dimension — `GENERATED`, `REVIEWED`, `APPROVED`, `DELIVERED`, and terminal `SUPERSEDED` — governs content approval. The `delivery_status` dimension — `PENDING`, `SENT`, `ACKNOWLEDGED`, and `BOUNCED` — governs transmission. The two move independently except that delivery moves both in a single transition.

A `TaxPreparer` submits a generated package for review, moving preparation from `GENERATED` to `REVIEWED`; the snapshot run must still be `LOCKED` and not `STALE`, else `ERR_ALLOCATION_STALE`, and `submitted_by_user_id` records the submitter’s `X-User-ID`. A `TaxReviewer` then approves the package, moving preparation from `REVIEWED` to `APPROVED`, with the conditions evaluated in this order: the approver’s `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the snapshot run must remain `LOCKED` and not `STALE`, else `ERR_ALLOCATION_STALE`; and the tax year must be `APPROVED`, else `ERR_INVALID_STATE_TRANSITION`. Approval records `approved_by_user_id`.

Delivery is performed by an `InvestorServicesRep` supplying a `delivery_method` of `PORTAL`, `MAIL`, or `EMAIL`. From preparation `APPROVED` with delivery `PENDING`, it moves preparation to `DELIVERED` and delivery to `SENT`, stamps `delivered_at` from the logical clock, records the `delivery_method`, and recomputes `is_late`: the package is late when `delivered_at` falls strictly after the tax year’s `k1_delivery_deadline`, while delivery exactly at the deadline timestamp is on time. When the delivery leaves every non-`SUPERSEDED` package of the tax year in preparation `DELIVERED`, the year bubbles up from `APPROVED` to `COMPLETED`.

After sending, the investor acknowledges receipt — delivery moves from `SENT` to `ACKNOWLEDGED`, a terminal delivery state — and only the partner themselves may do this: the `Investor` actor’s `X-User-ID` must equal the package’s `partner_id`, else `ERR_FORBIDDEN_FOR_ROLE`. Alternatively, an `InvestorServicesRep` may report the delivery as bounced with an optional `reason` — accepted but not persisted on the package — moving delivery from `SENT` to `BOUNCED`, and may later resend with an optional new `delivery_method`, moving delivery from `BOUNCED` back to `SENT` while refreshing `delivered_at` and recomputing `is_late` (an omitted `delivery_method` leaves the previously recorded method in place).

When a delivered K-1 turns out to be wrong, a `TaxPreparer` opens an amendment against it by supplying the `k1_package_id` and a `reason` of `ALLOCATION_CHANGE`, `PARTNER_DATA_FIX`, `STATE_REAPPORTIONMENT`, or `LATE_K1_CORRECTION`. The target package’s preparation must be `DELIVERED`, else `ERR_K1_NOT_DELIVERED`, and at most one amendment not yet `ISSUED` may exist per package, else `ERR_AMENDMENT_ALREADY_ACTIVE`. The amendment begins `OPENED` with `opened_by_user_id` recorded. A `TaxPreparer` starts preparation, moving it to `IN_PREP`, and later submits it for review, moving it to `IN_REVIEW` and recording `prepared_by_user_id`. A `TaxReviewer` may return it to preparation — `IN_REVIEW` back to `IN_PREP` — and this revision loop may cycle any number of times.

Issuance is the terminal step, taken by a `TaxReviewer` whose `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Issuing cascades in three hops. First, the amended package’s preparation becomes `SUPERSEDED`. Second, a replacement package is created with `generation` one higher than the amended package, `supersedes_k1_id` pointing at the amended package, preparation `GENERATED`, delivery `PENDING`, and a `line_snapshot` recomputed from the current `LOCKED` run — or, when no `LOCKED` `FINAL` run exists at issuance, with the amended package’s `line_snapshot` and `run_id` carried over unchanged; the amendment’s `new_k1_package_id` is set to the replacement’s id. Third, an investor ticket with category `AMENDED_K1_QUESTION`, subject “Amended K-1 issued”, and status `OPEN` is auto-created for the package’s partner and tax year as investor communication. If the tax year had been `COMPLETED`, it returns to `APPROVED` because the replacement is not yet delivered. The amendment ends `ISSUED` with `issued_by_user_id` recorded. The package list may be filtered by `partner_id`, `tax_year_id`, `supersedes_k1_id`, `run_id`, and `prep_status`, and the amendments of a single package can be listed on the package itself.

### 3.9. Investor Support Tickets

Investor tax questions are tracked as tickets, opened by an `Investor` or an `InvestorServicesRep` with the `partner_id`, an optional `tax_year_id` that may be null for general questions, a `category` of `ALLOCATION_QUESTION`, `WITHHOLDING_QUESTION`, `DELIVERY_ISSUE`, `AMENDED_K1_QUESTION`, or `STATE_FILING_QUESTION`, and a short `subject`. An `Investor` may open tickets only for their own account — the `partner_id` must equal their `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE` — and the referenced partner and tax year must belong to the same fund. Each ticket’s `due_at` is its `created_at` plus a service-level window of twenty-four hours for `AMENDED_K1_QUESTION` tickets and seventy-two hours for every other category. A ticket’s `is_escalated` flag starts false and becomes true when the current clock passes `due_at` while the ticket stands `OPEN` or `REOPENED`.

Answering, done by an `InvestorServicesRep` or a `TaxPreparer` supplying `answer_text`, moves a ticket from `OPEN` — or from `REOPENED` — to `ANSWERED`, recording `answer_text` and `answered_by_user_id`; a re-answer overwrites both, and escalation is recomputed. Reopening, done by an `InvestorServicesRep` or by the owning `Investor` — whose `X-User-ID` must equal the ticket’s `partner_id`, else `ERR_FORBIDDEN_FOR_ROLE`, with an optional `reason` that is accepted but not persisted — moves an `ANSWERED` ticket to `REOPENED`, and escalation is recomputed against the original `due_at`. Closing, done by an `InvestorServicesRep`, moves an `ANSWERED` ticket to `CLOSED`, the terminal state. The ticket list may be filtered by `partner_id`, `tax_year_id`, `status`, and `category`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes creating funds, tax years, partners, capital events (and the mirror event produced by a reversal), transfers, allocation runs, special allocations, composite filings, withholding accruals, K-1 generation, amendments, and tickets. Operations that act on an existing resource without creating a new one — state transitions such as close-books, submit-review, approve, lock, confirm, settle, remit, reconcile, deliver, acknowledge, and the clock set — return `200 OK`. Request and response payloads for each endpoint are as narrated in §3; this table is deliberately a summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funds` | Create a fund with waterfall and fee config | FundTaxAdmin |
| GET | `/funds/{fundId}` | Get a fund | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep, Investor |
| POST | `/funds/tax-years` | Create a tax year; computes management fee and net ordinary income | FundTaxAdmin |
| GET | `/funds/tax-years/{taxYearId}` | Get a tax year | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep, Investor |
| GET | `/funds/tax-years` | List tax years | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep |
| POST | `/funds/tax-years/{taxYearId}/close-books` | Move a tax year from `OPEN` to `BOOKS_CLOSED` | FundTaxAdmin |
| POST | `/funds/tax-years/{taxYearId}/submit-review` | Move a tax year from `ALLOCATED` to `UNDER_REVIEW` | TaxPreparer |
| POST | `/funds/tax-years/{taxYearId}/approve` | Move a tax year from `UNDER_REVIEW` to `APPROVED` | TaxReviewer |
| POST | `/funds/tax-years/{taxYearId}/reopen` | Reopen an `APPROVED` tax year back to `BOOKS_CLOSED`; run goes stale and in-flight K-1s revert | FundTaxAdmin |
| POST | `/funds/partners` | Admit a partner | FundTaxAdmin |
| GET | `/funds/partners/{partnerId}` | Get a partner (Investor: own record only) | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep, Investor |
| GET | `/funds/partners` | List partners | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep |
| POST | `/funds/partners/{partnerId}/withdraw` | Withdraw a partner with zero book capital | FundTaxAdmin |
| POST | `/funds/capital-events` | Post a capital account event | TaxPreparer |
| GET | `/funds/capital-events/{eventId}` | Get a capital account event | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/capital-events` | List capital account events | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/capital-events/{eventId}/reverse` | Reverse a posted event by creating its mirror | TaxPreparer |
| POST | `/funds/transfers` | Propose an ownership transfer | FundTaxAdmin |
| GET | `/funds/transfers/{transferId}` | Get an ownership transfer | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/transfers` | List ownership transfers | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/transfers/{transferId}/confirm` | Confirm a proposed transfer after cap, window, and overlap checks | FundTaxAdmin |
| POST | `/funds/transfers/{transferId}/settle` | Settle a confirmed transfer; cascades to events, balances, runs, and K-1s | FundTaxAdmin |
| POST | `/funds/transfers/{transferId}/cancel` | Cancel a proposed or confirmed transfer | FundTaxAdmin |
| POST | `/funds/allocation-runs` | Compute a new allocation run; supersedes older computed or stale runs | TaxPreparer |
| GET | `/funds/allocation-runs/{runId}` | Get an allocation run | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/allocation-runs` | List allocation runs | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/allocation-runs/{runId}/lock` | Lock a computed `FINAL` run | TaxReviewer |
| GET | `/funds/allocation-runs/{id}/lines` | List the allocation lines of a run | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/partners/{id}/allocation-lines` | List the allocation lines of a partner across runs | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/special-allocations` | Propose a special allocation | TaxPreparer |
| GET | `/funds/special-allocations/{saId}` | Get a special allocation | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/special-allocations` | List special allocations | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/special-allocations/{saId}/approve` | Approve a proposed special allocation | TaxReviewer |
| POST | `/funds/special-allocations/{saId}/reject` | Reject a proposed special allocation | TaxReviewer |
| POST | `/funds/composite-filings` | Create a draft composite filing for one state | TaxPreparer |
| GET | `/funds/composite-filings/{cfId}` | Get a composite filing | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/composite-filings` | List composite filings | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/composite-filings/{cfId}/file` | File a draft; recomputes totals from the locked run | TaxPreparer |
| POST | `/funds/composite-filings/{cfId}/record-outcome` | Record the state's accepted or rejected outcome | FundTaxAdmin |
| POST | `/funds/withholding-accruals` | Bulk-accrue quarterly withholding for all foreign active partners of a tax year | TaxPreparer |
| GET | `/funds/withholding-records/{wrId}` | Get a withholding record | FundTaxAdmin, TaxPreparer, TaxReviewer |
| GET | `/funds/withholding-records` | List withholding records | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/withholding-records/{wrId}/remit` | Remit against accrued withholding | TaxPreparer |
| POST | `/funds/withholding-records/{wrId}/reconcile` | Compute the penalty and close the record | TaxReviewer |
| POST | `/funds/k1-generation` | Bulk-generate K-1 packages for all active partners from the locked `FINAL` run | TaxPreparer |
| GET | `/funds/k1-packages/{k1Id}` | Get a K-1 package (Investor: own only) | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep, Investor |
| GET | `/funds/k1-packages` | List K-1 packages | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep |
| POST | `/funds/k1-packages/{k1Id}/submit-review` | Submit a generated package for review | TaxPreparer |
| POST | `/funds/k1-packages/{k1Id}/approve` | Approve a reviewed package | TaxReviewer |
| POST | `/funds/k1-packages/{k1Id}/deliver` | Deliver an approved package to the investor | InvestorServicesRep |
| POST | `/funds/k1-packages/{k1Id}/acknowledge` | Acknowledge receipt of a delivered package | Investor |
| POST | `/funds/k1-packages/{k1Id}/report-bounced` | Report a delivery as bounced | InvestorServicesRep |
| POST | `/funds/k1-packages/{k1Id}/resend` | Resend a bounced package | InvestorServicesRep |
| POST | `/funds/k1-amendments` | Open an amendment on a delivered K-1 package | TaxPreparer |
| GET | `/funds/k1-packages/{id}/amendments` | List the amendments of a K-1 package | FundTaxAdmin, TaxPreparer, TaxReviewer |
| POST | `/funds/k1-amendments/{amendmentId}/start-prep` | Start preparing an opened amendment | TaxPreparer |
| POST | `/funds/k1-amendments/{amendmentId}/submit-review` | Submit a prepared amendment for review | TaxPreparer |
| POST | `/funds/k1-amendments/{amendmentId}/return-to-prep` | Return an amendment to preparation | TaxReviewer |
| POST | `/funds/k1-amendments/{amendmentId}/issue` | Issue an amendment; supersedes the original and creates the replacement package and investor ticket | TaxReviewer |
| POST | `/funds/tickets` | Open an investor tax question ticket | Investor, InvestorServicesRep |
| GET | `/funds/tickets/{ticketId}` | Get a ticket (Investor: own partner's only) | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep, Investor |
| GET | `/funds/tickets` | List tickets | FundTaxAdmin, TaxPreparer, TaxReviewer, InvestorServicesRep |
| POST | `/funds/tickets/{ticketId}/answer` | Answer an open or reopened ticket | InvestorServicesRep, TaxPreparer |
| POST | `/funds/tickets/{ticketId}/reopen` | Reopen an answered ticket | Investor, InvestorServicesRep |
| POST | `/funds/tickets/{ticketId}/close` | Close an answered ticket | InvestorServicesRep |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FundTaxAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_TAX_YEAR_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED` | 409 |
| `ERR_TAX_YEAR_WINDOW_CLOSED` | 409 |
| `ERR_TAX_YEAR_NOT_BOOKS_CLOSED` | 409 |
| `ERR_SPECIAL_ALLOCATION_OVERLAP` | 409 |
| `ERR_TRANSFER_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_TAX_YEAR` | 409 |
| `ERR_DUPLICATE_COMPOSITE_FILING` | 409 |
| `ERR_DUPLICATE_WITHHOLDING_ACCRUAL` | 409 |
| `ERR_AMENDMENT_ALREADY_ACTIVE` | 409 |
| `ERR_K1_ALREADY_GENERATED` | 409 |
| `ERR_CROSS_FUND_REFERENCE` | 409 |
| `ERR_SAME_PARTNER_TRANSFER` | 422 |
| `ERR_REVERSAL_OF_REVERSAL` | 422 |
| `ERR_DISTRIBUTION_EXCEEDS_CAPITAL` | 422 |
| `ERR_REMIT_EXCEEDS_ACCRUED` | 422 |
| `ERR_INSUFFICIENT_OWNERSHIP` | 422 |
| `ERR_ALLOCATION_NOT_LOCKED` | 409 |
| `ERR_ALLOCATION_STALE` | 409 |
| `ERR_SPECIAL_ALLOCATION_OVERFLOW` | 422 |
| `ERR_APPORTIONMENT_OVERFLOW` | 422 |
| `ERR_NO_ALLOCABLE_PARTNERS` | 422 |
| `ERR_NO_FOREIGN_PARTNERS` | 422 |
| `ERR_COMPOSITE_PARTNER_INELIGIBLE` | 422 |
| `ERR_PARTNER_CAPITAL_NOT_ZERO` | 422 |
| `ERR_K1_NOT_DELIVERED` | 409 |
