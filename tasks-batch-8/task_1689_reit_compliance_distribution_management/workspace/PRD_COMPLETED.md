# REIT Compliance & Distribution Management API — Product Requirements Document

## 1. Introduction

A publicly traded real estate investment trust lives or dies by its compliance calendar. Four times a year the compliance team must prove the trust's asset mix and income mix still qualify it for conduit treatment; twice a year it must prove no five individuals collectively control it; once a year it must compute the minimum distribution it owes shareholders, declare and characterize that dividend correctly against earnings and profits, and close the year without leaving a deficiency on the books. When any one of these tests fails, the trust enters a suspended posture and a cascade of downstream actions — most visibly dividend declarations — must halt until the breach is remediated.

This document specifies a REIT compliance and distribution management service that operationalizes that calendar. The platform models the trust itself, its asset holdings, quarterly income items, quarterly asset- and income-test reports, shareholder concentration snapshots, the annual distribution requirement, dividend declarations, earnings-and-profits adjustments, asset sales subject to prohibited-transaction analysis, and the board-facing compliance disclosures that bind them all together. Three roles — a compliance officer who runs the daily books, a tax director who owns the fiscal ledger and final sign-off, and a board director who approves dividends and disclosures — share a single ledger but are deliberately separated by duty so that no single operator can both initiate and authorize a sensitive transition.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. The role header must match one of the declared role names exactly; the id header identifies the acting operator. A request missing either header (an empty header value counts as missing), or carrying an `X-User-Role` outside the declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`.

The declared role set is:

- `ComplianceOfficer` — a member of the public REIT compliance team. Owns data entry (assets, quarters, income items, shareholders, snapshots, positions), locks the quarterly asset and income test reports, finalizes the half-year ownership snapshots, declares and pays dividends, drafts and submits disclosures, and runs prohibited-transaction analysis on sales.
- `TaxDirector` — the tax authority on the engagement. Registers the REIT itself, posts E&P adjustments, closes the distribution requirement at year-end, confirms analyzed asset sales, and unfreezes shareholders whose ownership-limit violation has been remediated.
- `BoardDirector` — a member of the board. Approves dividends and approves or rejects compliance disclosures, providing the segregation-of-duties counterweight to the `ComplianceOfficer`.

All three roles carry an **opaque** identity model. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `declared_by_officer_id` on a `DividendDeclaration` or `submitted_by_officer_id` on a `ComplianceDisclosure`) but does not compare it to any entity's `id`. The same holds for `TaxDirector`: `X-User-ID` is opaque, never matched against a stored entity row, though it may be recorded on entities the role touches. `BoardDirector` is likewise opaque — its identifier is captured into `approved_by_director_id` and `decided_by_director_id` when the director acts, purely so the segregation-of-duties check can later compare that stored identifier against the next actor's `X-User-ID`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock UTC independently of the logical clock in §2.7.
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

Requests to unknown paths, and requests using an unsupported method on a known path, are surfaced as `ERR_NOT_FOUND` (HTTP 404) in this envelope. An unexpected server failure is surfaced as HTTP 500 in the same envelope with `error_id` `ERR_VALIDATION`.

### 2.3. Pagination

List endpoints accept two optional query parameters: `limit` and `offset`. When omitted, `limit` defaults to 10 and `offset` defaults to 0; a non-integer value falls back to its default, and out-of-range values are clamped rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0. Results are returned in `created_at` ascending order with `id` ascending as the tie-break. The `meta` block of a list response carries four pagination fields — `limit`, `offset`, `total_count`, and `has_more` — so callers can page deterministically through the full set; `total_count` counts every matching row (not just the returned page), and `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted entity shares the same identity envelope. Each resource has an `id`, a server-minted UUID with no type prefix. Each carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, and `updated_at` in the same format; both are stamped from the logical clock described in §2.7. Each carries `version`, an integer that starts at 1 on creation and increments by one on every mutation that touches the row — including mutations triggered by a cascade from another entity. Two system-maintained writes are exempt from the version-increment rule and are called out where they occur: the quarter gross-income-total refresh (§3.2) updates only `updated_at`, and the per-position concentration write at snapshot finalize (§3.4) changes neither `version` nor `updated_at`. The `version` field is the backbone of the optimistic concurrency control described below; readers rely on it to detect that another writer has moved the entity since they last observed it.

### 2.5. Monetary Precision and Percentage Rounding

All money amounts are stored as integer cents; there is no fractional-cent arithmetic anywhere in the system. Calculations that yield a money amount — the 90% distribution requirement, the three-way dividend characterization, the prohibited-transaction tax — all produce integer cents, with any rounding resolved by round-half-up to whole cents.

All percentage ratios — the 75% asset test, the 20% TRS concentration limit, the 75% and 95% income tests, the 50% five-or-fewer concentration cap, and per-holder concentration percentages — are computed to four decimal places using round-half-up. Threshold comparisons are inclusive at the stated boundary unless otherwise noted: a qualifying percentage of exactly 75.0000 passes the 75% test, a TRS concentration of exactly 20.0000 passes the concentration limit, a top-five individual concentration of exactly 50.0000 passes the 5/50 test. Anything strictly outside the boundary fails.

### 2.6. Optimistic Concurrency Control on Fiscally Sensitive Creates

Two create operations mutate the REIT's fiscal baseline in ways that make a stale client view dangerous: drafting an E&P adjustment and drafting a dividend declaration. Both therefore require the caller to supply `expected_reit_version`, a non-optional input carrying the `version` of the parent `Reit` as the client last observed it; a missing or non-integer `expected_reit_version` fails payload validation with `ERR_VALIDATION`. If the supplied value does not equal the REIT's current `version` at write time — because, for instance, another writer has since posted an adjustment or locked a report and legitimately advanced the version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not take a version field.

### 2.7. The Logical Clock

A test-driving capability lets operators advance the logical clock. Before any call to set it, the logical clock reads exactly 2026-08-01T00:00:00Z, and the system must never fall back to wall-clock time. Setting the clock takes a single input, `to_iso8601`, and returns the new `current_utc`. A missing or empty `to_iso8601` yields `ERR_VALIDATION`; a supplied value is normalized to millisecond precision (three fractional digits), and a non-empty value that does not match the ISO 8601 UTC shape is stored verbatim. Advancing the clock has no other side effect on entity state.

### 2.8. Path Resolution and Foreign-Key Existence

When a request URL contains multiple path parameters, each id is validated left-to-right: the first id must resolve before the second is examined, and so on. A path id that does not resolve to an existing entity yields `ERR_NOT_FOUND`. Body-supplied foreign keys — `reit_id`, `quarter_id`, `snapshot_id`, `shareholder_id`, `asset_holding_id` — are validated the same way: each must resolve to an existing entity of the correct type, and a miss yields `ERR_NOT_FOUND` as well.

### 2.9. Validation Priority Ordering

When several validation rules could fire on the same request, they are evaluated in a fixed order so the caller sees a deterministic error. Authentication (`ERR_UNAUTHENTICATED`) comes first, then role authorization (`ERR_UNAUTHORIZED`), then path-id existence (`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_NOT_FOUND`), then payload shape and enum/range checks (`ERR_VALIDATION`), then uniqueness (`ERR_DUPLICATE`), then state-machine legality (`ERR_INVALID_STATE`), then snapshot emptiness (`ERR_SNAPSHOT_EMPTY`), then quarter-or-snapshot openness (`ERR_QUARTER_LOCKED`), then cross-REIT referential consistency (`ERR_CROSS_REIT_REFERENCE`), then date sanity (`ERR_INVALID_DATE_RANGE`), then quarter interval overlap (`ERR_QUARTER_OVERLAP`), then the suspended-REIT posture gate (`ERR_REIT_SUSPENDED`), then the 5/50 block (`ERR_FIVE_FIFTY_BLOCKED`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the posted-requirement precondition (`ERR_REQUIREMENT_NOT_POSTED`), then OCC staleness (`ERR_STALE_VERSION`), and finally the open-declarations precondition on year close (`ERR_DECLARATIONS_OPEN`). A request that fails more than one rule surfaces the one with the earliest position in this list.

### 2.10. Uniqueness Constraints

Six uniqueness constraints are enforced across the domain. A REIT's `ticker` must be unique across all registered REITs. A quarter's `label` must be unique within its owning REIT. Each quarter supports at most one asset test report and at most one income test report. A shareholder snapshot's `snapshot_date` must be unique within its REIT. A distribution requirement's `taxable_year` must be unique within its REIT. Violating any of these yields `ERR_DUPLICATE`.

### 2.11. The Compliance Kill-Switch

When an asset test report or income test report locks with a failing ratio, the consequence is not local. The report transitions to `BREACHED`, its quarter locks, the parent REIT transitions to `SUSPENDED`, and — because a suspended REIT may not pay dividends — every `DividendDeclaration` of that REIT still sitting in `PENDING_APPROVAL` or `APPROVED` is auto-voided in the same sweep. Declarations already in `DECLARED` or `PAID` are left untouched; the kill-switch only cancels dividends that have not yet been executed. Every entity touched by the cascade — report, quarter, REIT, and each auto-voided declaration — has its `version` incremented by one. A later passing quarter does not automatically un-suspend the REIT; remediation is a business decision, not a system transition.

## 3. Business Logic & Workflows

### 3.1. Onboarding the REIT and Loading the Book of Assets

A `TaxDirector` onboards a new trust by registering it with a `legal_name`, an exchange `ticker`, a `charter_ownership_limit_pct`, and a `taxable_year_start`. The ownership limit is the charter-imposed per-person concentration cap — a value such as 9.8 — and must lie strictly between 0 and 50.0; a value outside that open interval is rejected with `ERR_VALIDATION`. On creation the REIT's `status` is set to `ACTIVE`, its `current_ep_balance_cents` and `dividend_distribution_deficit_cents` are both initialized to 0, and `five_fifty_blocked` is initialized to false.

Once the REIT exists, a `ComplianceOfficer` loads its book of assets. Each asset is registered with the owning `reit_id`, a human-readable `asset_name`, an `asset_class` of `REAL_ESTATE`, `QUALIFYING_SECURITY`, or `NON_QUALIFYING`, a `held_by_trs` flag indicating whether the asset sits inside a taxable REIT subsidiary, an `is_dealer_inventory` flag marking property held primarily for sale to customers in the ordinary course, an `acquisition_date`, and a current `value_cents`, which must be an integer of zero or more. New assets arrive in `HELD` status. While an asset remains `HELD`, the officer may amend its `value_cents`, `asset_class`, `held_by_trs`, or `is_dealer_inventory` — each amendment increments the asset's `version` by one. Once an asset has flipped to `SOLD` it is no longer mutable through this channel: a PATCH against a non-`HELD` asset is rejected with `ERR_INVALID_STATE`, and this status check runs before any field-level validation of the payload.

### 3.2. Opening Quarters and Accruing Income

The compliance calendar is organized around quarters. A `ComplianceOfficer` opens a quarter by supplying the owning `reit_id`, a calendar `label` such as 2026-Q1, a `period_start`, and a `period_end`. Two date rules guard quarter creation. First, `period_end` must not precede `period_start`; an inverted range yields `ERR_INVALID_DATE_RANGE`. Second, the new quarter's closed interval must not intersect any existing quarter of the same REIT — adjacency is permitted (an existing quarter may end the day before the new one begins), but sharing even a single calendar day is a conflict and yields `ERR_QUARTER_OVERLAP`. A fresh quarter opens in `OPEN` status with both `gross_asset_total_cents` and `gross_income_total_cents` initialized to 0. The income total is a live aggregate, recomputed as underlying income data changes; the asset total is not maintained continuously — it stays 0 until an asset test report lock freezes the swept gross asset total onto the quarter (§3.3).

Income accrues into open quarters. Recording an income item takes the owning `reit_id`, the `quarter_id` it accrues to, an `income_class` of `RENTS`, `MORTGAGE_INTEREST`, or `NON_QUALIFYING`, an `amount_cents` that must be at least 0, a `source_is_trs` flag, and an `accrued_at` date. The `income_class` determines which income test the item counts toward: `RENTS` qualifies for both the 75% and the 95% test, `MORTGAGE_INTEREST` qualifies only for the 95% test, and `NON_QUALIFYING` counts toward neither. The quarter referenced by `quarter_id` must belong to the same REIT as the `reit_id` on the item; a mismatch is a cross-REIT reference and is rejected with `ERR_CROSS_REIT_REFERENCE`. Income items may only be created against a quarter that is still `OPEN`, and an existing item may be amended (its `amount_cents` or `income_class` updated) only while its quarter remains `OPEN`; either operation against a locked quarter is rejected with `ERR_QUARTER_LOCKED`. Every create or amendment recomputes the quarter's `gross_income_total_cents`; this refresh updates the quarter's `updated_at` but does not increment the quarter's `version`. The `accrued_at` field is stored for record-keeping only — it feeds no computed aggregate or ordering (chronological E&P replay is driven by adjustments' `effective_date`, per §3.7).

### 3.3. Quarterly Asset and Income Test Reports

At quarter-end the `ComplianceOfficer` asks for a test report. Two report types exist, each scoped to a single `(reit_id, quarter_id)` pair. An asset test report measures the 75% asset test and the TRS concentration limit; an income test report measures the 75% and 95% income tests. Each quarter supports at most one report of each type; a second request of the same type for the same quarter yields `ERR_DUPLICATE`. No cross-REIT consistency check is applied between the report's `reit_id` and `quarter_id`. Reports are created in `DRAFT` status and carry no computed numbers until locked.

Locking is the decisive act. When the officer locks an asset test report, the system sweeps every `AssetHolding` of the report's REIT whose status is `HELD` — assets already `SOLD` are excluded — and computes two ratios. The `qualifying_75_pct` is the percentage of total held asset value whose `asset_class` is `REAL_ESTATE` or `QUALIFYING_SECURITY`, computed to four decimal places round-half-up. The `trs_concentration_pct` is the percentage of total held asset value where `held_by_trs` is true, same precision. The empty-set rule applies: a REIT with no held assets has a `qualifying_75_pct` of 0.0000 and therefore fails the 75% test, and likewise a `trs_concentration_pct` of 0.0000. The `test_75_passed` boolean is true when `qualifying_75_pct` is at least 75.0000 (the boundary is inclusive). The `trs_test_passed` boolean is true when `trs_concentration_pct` is at most 20.0000 — again inclusive, so a concentration of 20.0001 breaches.

If both ratios pass, the report transitions `DRAFT → LOCKED`, the four computed values are persisted, the swept gross asset total is written onto the quarter's `gross_asset_total_cents`, the parent quarter transitions to `LOCKED`, and both the report's and the quarter's `version` increment by one. Locking the quarter cascades down to income data too — once a quarter is `LOCKED`, income items in it can no longer be created or amended. If either ratio fails, the report transitions `DRAFT → BREACHED`, the ratios and booleans are persisted, the quarter still locks, and the compliance kill-switch described in §2.11 fires: the REIT goes `SUSPENDED`, every `PENDING_APPROVAL` or `APPROVED` dividend is auto-voided, and the `version` of the report, the quarter, the REIT, and each auto-voided declaration all increment by one. A lock request against a report not in `DRAFT` is rejected with `ERR_INVALID_STATE`; one against a report whose quarter is already `LOCKED` is rejected with `ERR_QUARTER_LOCKED`.

Income test reports follow the same shape with different inputs. The lock sweeps every `IncomeItem` whose `quarter_id` matches the report's quarter — regardless of `source_is_trs` — and sums their `amount_cents` into a total. The `qualifying_75_pct` is the percentage of that total attributable to `RENTS`; the `qualifying_95_pct` is the percentage attributable to `RENTS` plus `MORTGAGE_INTEREST`. Both are four-decimal round-half-up. The empty-set rule applies here too: zero income yields 0.0000 on both ratios and fails both tests. The `test_75_passed` boolean requires at least 75.0000; `test_95_passed` requires at least 95.0000. Pass transitions `DRAFT → LOCKED` with the sweep total written onto the quarter's `gross_income_total_cents`, quarter lock, and the same version bumps; fail transitions `DRAFT → BREACHED` and fires the same kill-switch.

### 3.4. Shareholder Concentration Snapshots and the 5/50 Test

Twice a year — on the last day of each taxable-year half — the compliance team must demonstrate that five or fewer individuals do not collectively hold more than half the trust. A `ComplianceOfficer` registers each holder of record with the owning `reit_id`, a `display_name`, and a `holder_type` of `INDIVIDUAL` or `ENTITY`. Only `INDIVIDUAL` holders count toward the five-or-fewer test; `ENTITY` holders do not. New shareholders start in `ACTIVE` status.

The snapshot itself is created in `DRAFT` against a `snapshot_date` that must fall on a half-year last day — June 30 or December 31 of some year — and a `total_shares_outstanding` strictly greater than 0. A `snapshot_date` that is not a half-year last day is rejected with `ERR_INVALID_DATE_RANGE`. A fresh snapshot carries `top5_individual_pct` and `five_fifty_passed` as null and `violator_shareholder_ids` as an empty list until finalized. While the snapshot is in `DRAFT`, the officer adds one position per holder, each carrying the `snapshot_id`, the `shareholder_id`, and the `shares_held` (zero or more). The shareholder named by `shareholder_id` must belong to the same REIT as the snapshot; a mismatch yields `ERR_CROSS_REIT_REFERENCE`. Positions may only be added while the snapshot is in `DRAFT`; attempting to add one to a `FINALIZED` snapshot yields `ERR_QUARTER_LOCKED`. A fresh position carries `concentration_pct` null until the snapshot is finalized.

Finalizing the snapshot freezes the picture. The finalize operation requires the snapshot to be in `DRAFT` and to have at least one position — a finalize request against an empty snapshot is rejected with `ERR_SNAPSHOT_EMPTY`, and one against a snapshot already `FINALIZED` is rejected with `ERR_INVALID_STATE`. On finalize, the system computes each position's `concentration_pct` as the position's `shares_held` divided by the snapshot's `total_shares_outstanding`, multiplied by 100, rounded half-up to four decimal places; this write persists `concentration_pct` on each position without incrementing the position's `version` or changing its `updated_at`. It then identifies the individual holders — those whose `holder_type` is `INDIVIDUAL` — sorts them by `shares_held` descending with ties broken by the shareholder's `created_at` ascending (never by `id`), and takes the first five, or all of them when fewer than five individuals hold positions. The `top5_individual_pct` is the sum of those top-five concentration percentages, again rounded half-up to four decimals. The `five_fifty_passed` boolean is true when that sum is at most 50.0000, inclusive. In parallel, the system computes `violator_shareholder_ids`: every position — of either holder type, so an `ENTITY` holder can be a violator even though it never counts toward the five-or-fewer test — whose `concentration_pct` strictly exceeds the REIT's `charter_ownership_limit_pct`, ordered by `shares_held` descending with the same `created_at` ascending tie-break.

The finalize cascade is wide. Every shareholder appearing in `violator_shareholder_ids` transitions `ACTIVE → FROZEN`, with the shareholder's `version` incrementing by one. The REIT's `five_fifty_blocked` flag is set to the negation of `five_fifty_passed` — a failing snapshot sets it true, and a later passing snapshot clears it, so the flag always reflects the most recent finalized snapshot covering a half-year end. When the flag's value flips, the REIT's `version` increments by one. The snapshot itself transitions `DRAFT → FINALIZED` and its `version` increments by one. While `five_fifty_blocked` is true, dividend approval and dividend declaration are both rejected with `ERR_FIVE_FIFTY_BLOCKED` until a later snapshot clears the block.

A shareholder frozen by the finalize cascade can be remediated. A `TaxDirector` may unfreeze a holder currently in `FROZEN` status, returning it to `ACTIVE` and incrementing its `version` by one. Unfreezing a holder who is not `FROZEN` is rejected with `ERR_INVALID_STATE`.

### 3.5. The Annual Distribution Requirement

Once a taxable year's numbers are known, a `ComplianceOfficer` creates a distribution requirement by supplying the `reit_id`, the four-digit `taxable_year`, the `taxable_income_cents` (REIT taxable income before the dividends-paid deduction), and the `net_capital_gain_cents` for the year. `taxable_year` is accepted as any integer, `taxable_income_cents` may be any integer (negative values are legitimate), and `net_capital_gain_cents` must be zero or more. Each REIT supports one requirement per taxable year; a duplicate yields `ERR_DUPLICATE`. The requirement opens in `DRAFT` with `required_amount_cents`, `distributed_amount_cents`, and `deficiency_cents` all initialized to 0.

Posting the requirement is what turns inputs into an obligation. When the officer posts a `DRAFT` requirement, the system computes `required_amount_cents` as 90% of the excess of `taxable_income_cents` over `net_capital_gain_cents`. If that excess is zero or negative, the requirement floors at 0 — there is no negative requirement. Otherwise the 90% figure is rounded half-up to whole cents. The computed value is persisted on the requirement, and the REIT's `dividend_distribution_deficit_cents` is set equal to it, becoming the visible obligation the dividend workflow must retire. Both the requirement's and the REIT's `version` increment by one. Posting a requirement not in `DRAFT` yields `ERR_INVALID_STATE`.

The requirement lives in `POSTED` while dividends accumulate against it. At year-end a `TaxDirector` closes it, but only when every sibling dividend for the same `(reit_id, taxable_year)` has reached a terminal state of `PAID` or `VOID`; a close request with any declaration still in `PENDING_APPROVAL`, `APPROVED`, or `DECLARED` is rejected with `ERR_DECLARATIONS_OPEN`, and one against a requirement not in `POSTED` yields `ERR_INVALID_STATE`. On close, the `deficiency_cents` is frozen as the greater of zero or the excess of `required_amount_cents` over `distributed_amount_cents`. If the frozen deficiency is positive, the REIT's `dividend_distribution_deficit_cents` is set to that amount as a persisted obligation; if the requirement was fully satisfied, the REIT's deficit resets to 0. The requirement transitions `POSTED → CLOSED` and both its and the REIT's `version` increment by one.

### 3.6. Dividend Declaration and Characterization

Drafting a dividend is a `ComplianceOfficer` action and is one of the two OCC-guarded creates described in §2.6. The payload carries the `reit_id`, the `taxable_year` the dividend counts against, the gross `amount_cents` (strictly greater than 0), a `declaration_date`, a `record_date`, a `payable_date`, and the `expected_reit_version` pinning the REIT version the client last observed. Two date rules apply: `record_date` must not precede `declaration_date`, and `payable_date` must not precede `record_date`; a violation yields `ERR_INVALID_DATE_RANGE`. The REIT must be `ACTIVE` — drafting against a suspended REIT yields `ERR_REIT_SUSPENDED`. On create the declaration lands in `PENDING_APPROVAL` with `ordinary_cents`, `capital_gain_cents`, and `return_of_capital_cents` initialized to 0 and `declared_by_officer_id` and `approved_by_director_id` null, and the REIT's `version` increments by one.

From `PENDING_APPROVAL` a `BoardDirector` approves. Approval requires the declaration to be in `PENDING_APPROVAL`, the REIT to be `ACTIVE`, and `five_fifty_blocked` to be false. The director's `X-User-ID` is captured into `approved_by_director_id`, the declaration transitions `PENDING_APPROVAL → APPROVED`, and its `version` increments by one. Note the precise shape of the segregation-of-duties rule here: because the creating officer is not tracked on the declaration, approval does **not** check the approver against the creator. The forbidden pairing is approve-then-declare by the same identifier, enforced on the next transition.

Declaration is the fiscal event. A `ComplianceOfficer` declares a dividend that is in `APPROVED`, against a REIT that is `ACTIVE`, with `five_fifty_blocked` false, with their own `X-User-ID` different from the declaration's `approved_by_director_id` — a same-identifier attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` — and with a `POSTED` `DistributionRequirement` existing for the same `(reit_id, taxable_year)`. A missing or unposted requirement yields `ERR_REQUIREMENT_NOT_POSTED`. When all preconditions hold, the system characterizes the dividend.

Characterization follows a strict waterfall in integer cents, with no fractional rounding anywhere. The first bucket is ordinary income: `ordinary_cents` is the lesser of the dividend's `amount_cents` and the REIT's `current_ep_balance_cents` clamped below at zero — a negative E&P balance clamps the ordinary bucket to 0. The remainder after ordinary income then flows into the capital-gain bucket. The capital-gain pool is the `net_capital_gain_cents` of the `POSTED` requirement minus the sum of `capital_gain_cents` already characterized on sibling declarations for the same `(reit_id, taxable_year)` that are in `DECLARED` or `PAID` status. `capital_gain_cents` is the lesser of the post-ordinary remainder and that pool clamped below at zero. Whatever remains after both buckets is `return_of_capital_cents`. The evaluation order is pinned — ordinary first, then capital gain, then return of capital — and the E&P balance is debited immediately by `ordinary_cents`.

Beyond characterization, the declare transition syncs the ledger. The officer's `X-User-ID` is captured into `declared_by_officer_id`. The requirement's `distributed_amount_cents` is recomputed as the sum of `amount_cents` over all declarations for the year in `DECLARED` or `PAID` status, and its `deficiency_cents` is recomputed as the greater of zero or the excess of `required_amount_cents` over that distributed total. The REIT's `dividend_distribution_deficit_cents` is set to the recomputed deficiency of the `POSTED` requirement. The declaration transitions `APPROVED → DECLARED`, and the `version` of the declaration, the REIT, and the requirement each increment by one.

Payment is the quiet transition. A `ComplianceOfficer` pays a declaration that is in `DECLARED`; no E&P change occurs because the allocation already happened at declare time, and the requirement's amounts are unchanged. The declaration transitions `DECLARED → PAID` and its `version` increments by one. Voiding is available while the declaration is in `PENDING_APPROVAL` or `APPROVED`; a void request against any other status — including a `PAID` declaration — is rejected with `ERR_INVALID_STATE`. A voided declaration transitions to `VOID` and its `version` increments by one.

### 3.7. Earnings & Profits Adjustments

The E&P ledger is maintained through explicit adjustment entries. A `TaxDirector` drafts an adjustment with the owning `reit_id`, the `quarter_id` it accrues to, a `kind`, an `amount_cents`, an `effective_date`, and the OCC field `expected_reit_version` — this is the second of the two stale-version-guarded creates. The `kind` must be one of `TAXABLE_INCOME`, `DISALLOWED_DEDUCTION`, or `FEDERAL_TAX`; the sign convention is that all three carry a non-negative `amount_cents`, with `TAXABLE_INCOME` and `DISALLOWED_DEDUCTION` accruing positive E&P and `FEDERAL_TAX` accruing negative E&P (subtracted at replay). The referenced quarter must belong to the same REIT as the `reit_id` on the adjustment — otherwise `ERR_CROSS_REIT_REFERENCE` — and must be `OPEN`, both at create time and at post time; a create or post against a locked quarter yields `ERR_QUARTER_LOCKED`. A fresh adjustment lands in `DRAFT`, and creating one increments the REIT's `version` by one.

Posting folds the adjustment into the running balance. When the director posts a `DRAFT` adjustment, the system recomputes the REIT's `current_ep_balance_cents` by chronological replay: walk every `POSTED` adjustment for the REIT ordered by `effective_date` ascending with `created_at` ascending as the tie-break (never `id`), adding `amount_cents` for `TAXABLE_INCOME` and `DISALLOWED_DEDUCTION` and subtracting for `FEDERAL_TAX`, then subtract the sum of `ordinary_cents` over all declarations for the REIT in `DECLARED` or `PAID` status. The balance may go negative — that is a legitimate deficit E&P position, and it is what clamps the ordinary bucket of dividend characterization to zero. The adjustment transitions `DRAFT → POSTED`, and both its and the REIT's `version` increment by one. The declare transition also re-runs this same replay after debiting `ordinary_cents`, so the E&P balance is always current after a dividend declaration.

Two read variants expose the balance. The default is the live running balance just described. The frozen year-end view, selected by passing an `as_of` query parameter set to a taxable year's last day, replays only adjustments whose `effective_date` falls on or before that boundary and ignores later adjustments entirely — no late-arrival inclusion — so the same ledger yields a smaller balance whenever late accruals exist. The response carries `ep_balance_cents` and a `variant` string — `current_ep_view` for the default live balance, `frozen_year_end_view` when `as_of` is supplied. The frozen variant filters only adjustments; the ordinary-income debits of `DECLARED`/`PAID` dividends are still subtracted in full, regardless of the `as_of` boundary.

### 3.8. Asset Sales and Prohibited-Transaction Analysis

Selling an asset is a three-step workflow designed to catch dealer-property abuses. A `ComplianceOfficer` drafts a sale with the `reit_id`, the `asset_holding_id` being sold, a `sale_price_cents` strictly greater than 0, a `basis_cents` of zero or more, and a `sale_date`. The referenced asset must belong to the same REIT as the sale — a mismatch yields `ERR_CROSS_REIT_REFERENCE`. A fresh sale lands in `DRAFT` with `holding_period_months`, `is_prohibited`, and `prohibited_tax_cents` null until analyzed; drafting does not require the asset to be `HELD`.

Analysis runs the prohibited-transaction test. Analyzing a sale not in `DRAFT`, or one whose underlying asset is no longer `HELD`, is rejected with `ERR_INVALID_STATE`. When the officer analyzes a `DRAFT` sale whose underlying asset is still `HELD`, the system computes `holding_period_months` as the floor of the day count between the asset's `acquisition_date` and the `sale_date` divided by 30 — a whole-calendar-month figure. The `is_prohibited` flag is true when the asset is dealer inventory (`is_dealer_inventory` true) and the holding period is less than 24 months — the 24-month boundary is a safe harbor, so a holding period of 24 months or more is safe. When the sale is prohibited and the gain — the excess of `sale_price_cents` over `basis_cents` — is positive, the `prohibited_tax_cents` equals that gain in full: a 100% tax on net gain. Otherwise the tax is 0. All three computed values are persisted, the sale transitions `DRAFT → ANALYZED`, and its `version` increments by one.

Confirmation is a `TaxDirector` act and requires the sale to be in `ANALYZED` (any other status yields `ERR_INVALID_STATE`) and the REIT to be `ACTIVE` — confirming against a suspended REIT is rejected with `ERR_REIT_SUSPENDED`. On confirm the underlying asset flips `HELD → SOLD` (removing it from subsequent asset tests), the sale transitions `ANALYZED → CONFIRMED`, and both the sale's and the asset's `version` increment by one. When the sale was flagged prohibited, the sale row carries the `prohibited_tax_cents` as a `FEDERAL_TAX`-like charge, but the system posts nothing automatically and recomputes nothing else. A sale may be voided while in `DRAFT` or `ANALYZED`; a void against any other status yields `ERR_INVALID_STATE`.

### 3.9. Compliance Disclosures and the Board Review Loop

Every locked or finalized artifact — asset test report, income test report, ownership snapshot, distribution requirement, or confirmed asset sale — can be wrapped in a board-facing disclosure. A `ComplianceOfficer` drafts a disclosure with the `reit_id`, a `disclosure_type` of `ASSET_TEST`, `INCOME_TEST`, `FIVE_FIFTY`, `DISTRIBUTION`, or `PROHIBITED_TRANSACTION`, a `reference_id` pointing at the specific report, snapshot, requirement, or sale being disclosed, a `title`, and a `body`. The `reference_id` is polymorphic: its expected entity type is implied by the `disclosure_type`. A fresh disclosure lands in `DRAFT` with `revision_count` 0 and null `submitted_by_officer_id` and `decided_by_director_id`.

Submitting a disclosure moves it `DRAFT → SUBMITTED` and captures the officer's `X-User-ID` into `submitted_by_officer_id`; a submit against a disclosure not in `DRAFT` is rejected with `ERR_INVALID_STATE`, and this state check runs before the reference is resolved. Reference integrity is enforced at submit time: the `reference_id` must resolve to an existing entity of the type implied by `disclosure_type`, and that entity must be in a terminal or locked state — `LOCKED` or `BREACHED` for the two test report types, `FINALIZED` for snapshots, `POSTED` or `CLOSED` for requirements, `CONFIRMED` for asset sales. A reference that is missing yields `ERR_NOT_FOUND`; one that resolves but is still in a non-terminal state yields `ERR_INVALID_STATE`. The referenced entity is not checked for membership in the disclosure's REIT. The disclosure's `version` increments by one.

A `BoardDirector` then decides. Approving moves `SUBMITTED → APPROVED`; rejecting marks the decision `REJECTED` and returns the disclosure to `DRAFT` for revision — the rejection is a revision loop, not a terminal state. Both decisions are segregation-of-duties guarded: the director's `X-User-ID` must differ from the disclosure's `submitted_by_officer_id`, and a same-identifier attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. Either decision captures the director's id into `decided_by_director_id` and increments the disclosure's `version` by one. A rejection additionally increments `revision_count` by one, tracking how many times this disclosure has made the round trip back to draft. Once a rejected disclosure has been revised, the officer may submit it again and the loop repeats. Approving or rejecting a disclosure not in `SUBMITTED` yields `ERR_INVALID_STATE`.

### 3.10. Previewing Dividend Characterization

Before committing to a declaration, a `ComplianceOfficer` or `TaxDirector` may preview how a hypothetical dividend would be characterized. The preview takes its inputs as query parameters — a required integer `amount_cents`, a required integer `taxable_year`, and an optional `mode` defaulting to `WATERFALL`; a missing or non-integer `amount_cents` or `taxable_year`, or a `mode` outside `WATERFALL` and `PRO_RATA`, yields `ERR_VALIDATION`. It returns `ordinary_cents`, `capital_gain_cents`, `return_of_capital_cents`, and the `mode` echoed back. For both modes the capital-gain pool is taken from the `POSTED` requirement for the same `(reit_id, taxable_year)` when one exists, otherwise from any requirement for that pair whatever its status, and is 0 when no requirement exists; the pool is net of capital gain already characterized on `DECLARED`/`PAID` sibling declarations, as in §3.6. The default mode is the waterfall described in §3.6 — ordinary income keyed to the REIT's current E&P balance first (conduit theory), then the capital-gain pool, then return of capital. The alternative `PRO_RATA` mode reports what the characterization would be under a pro-rata allocation: `ordinary_cents` becomes the gross amount multiplied by the ratio of the clamped E&P balance to the sum of the clamped E&P balance and the clamped capital-gain pool, rounded half-up to whole cents (or 0 when that denominator is zero), `capital_gain_cents` becomes the remainder capped at the pool, and return of capital absorbs whatever is left. The two variants share inputs but yield different cents whenever both the ordinary and capital-gain buckets are partially binding — the waterfall fills ordinary to the brim before touching capital gain, while pro-rata splits proportionally. The preview is a pure read: it mutates nothing and advances no versions.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources and action endpoints return HTTP 200. The logical-clock endpoint also returns 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/reits` | Register a REIT | TaxDirector |
| GET | `/reit-compliance/reits/{id}` | Fetch a REIT with computed compliance fields | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/reits` | List REITs (paginated) | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/reits/{id}/ep-balance` | Computed read: current E&P balance; optional `as_of` selects the frozen year-end variant | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/reits/{id}/dividend-characterization-preview` | Computed read: preview dividend characterization under WATERFALL (default) or PRO_RATA | ComplianceOfficer, TaxDirector |
| POST | `/reit-compliance/asset-holdings` | Register an asset | ComplianceOfficer |
| GET | `/reit-compliance/asset-holdings/{id}` | Fetch an asset | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/asset-holdings` | List assets; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| PATCH | `/reit-compliance/asset-holdings/{id}` | Update value/flags while HELD | ComplianceOfficer |
| POST | `/reit-compliance/quarters` | Open a compliance quarter | ComplianceOfficer |
| GET | `/reit-compliance/quarters/{id}` | Fetch a quarter | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/quarters` | List quarters; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/income-items` | Accrue a gross income item into an OPEN quarter | ComplianceOfficer |
| GET | `/reit-compliance/income-items/{id}` | Fetch an income item | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/income-items` | List income items; filterable by `reit_id` or `quarter_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| PATCH | `/reit-compliance/income-items/{id}` | Amend amount/class while quarter OPEN | ComplianceOfficer |
| POST | `/reit-compliance/asset-test-reports` | Create a DRAFT 75% asset test report | ComplianceOfficer |
| GET | `/reit-compliance/asset-test-reports/{id}` | Fetch an asset test report | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/asset-test-reports` | List asset test reports; filterable by `reit_id` or `quarter_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/asset-test-reports/{id}/lock` | Lock the report; cascade quarter lock and possible REIT suspension | ComplianceOfficer |
| POST | `/reit-compliance/income-test-reports` | Create a DRAFT income test report | ComplianceOfficer |
| GET | `/reit-compliance/income-test-reports/{id}` | Fetch an income test report | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/income-test-reports` | List income test reports; filterable by `reit_id` or `quarter_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/income-test-reports/{id}/lock` | Lock the report; cascade quarter lock and possible REIT suspension | ComplianceOfficer |
| POST | `/reit-compliance/shareholders` | Register a shareholder | ComplianceOfficer |
| GET | `/reit-compliance/shareholders/{id}` | Fetch a shareholder | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/shareholders` | List shareholders; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/shareholders/{id}/unfreeze` | Remediate an ownership-limit violation (FROZEN to ACTIVE) | TaxDirector |
| POST | `/reit-compliance/shareholder-snapshots` | Create a DRAFT ownership snapshot for a half-year end | ComplianceOfficer |
| GET | `/reit-compliance/shareholder-snapshots/{id}` | Fetch a snapshot | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/shareholder-snapshots` | List snapshots; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/shareholder-snapshots/{id}/finalize` | Finalize: compute concentrations, 5/50 result, violator cascade | ComplianceOfficer |
| POST | `/reit-compliance/shareholder-positions` | Add a holder position to a DRAFT snapshot | ComplianceOfficer |
| GET | `/reit-compliance/shareholder-positions/{id}` | Fetch a position | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/shareholder-positions` | List positions; filterable by `snapshot_id` or `shareholder_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/distribution-requirements` | Create a DRAFT 90% distribution requirement | ComplianceOfficer |
| GET | `/reit-compliance/distribution-requirements/{id}` | Fetch a requirement | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/distribution-requirements` | List requirements; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/distribution-requirements/{id}/post` | Post: compute required amount and push deficit onto the REIT | ComplianceOfficer |
| POST | `/reit-compliance/distribution-requirements/{id}/close` | Close the year; freeze deficiency | TaxDirector |
| POST | `/reit-compliance/dividend-declarations` | Draft a dividend (OCC-guarded) | ComplianceOfficer |
| GET | `/reit-compliance/dividend-declarations/{id}` | Fetch a declaration | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/dividend-declarations` | List declarations; filterable by `reit_id` or `taxable_year` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/dividend-declarations/{id}/approve` | Board approval | BoardDirector |
| POST | `/reit-compliance/dividend-declarations/{id}/declare` | Execute declaration: characterize, debit E&P, ledger-sync | ComplianceOfficer |
| POST | `/reit-compliance/dividend-declarations/{id}/pay` | Mark paid | ComplianceOfficer |
| POST | `/reit-compliance/dividend-declarations/{id}/void` | Void while PENDING_APPROVAL or APPROVED | ComplianceOfficer |
| POST | `/reit-compliance/ep-adjustments` | Draft an E&P adjustment (OCC-guarded) | TaxDirector |
| GET | `/reit-compliance/ep-adjustments/{id}` | Fetch an adjustment | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/ep-adjustments` | List adjustments; filterable by `reit_id` or `quarter_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/ep-adjustments/{id}/post` | Post: fold into chronological E&P replay | TaxDirector |
| POST | `/reit-compliance/asset-sales` | Draft an asset sale | ComplianceOfficer |
| GET | `/reit-compliance/asset-sales/{id}` | Fetch a sale | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/asset-sales` | List sales; filterable by `reit_id` or `asset_holding_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/asset-sales/{id}/analyze` | Run prohibited-transaction analysis | ComplianceOfficer |
| POST | `/reit-compliance/asset-sales/{id}/confirm` | Confirm sale: flips AssetHolding to SOLD | TaxDirector |
| POST | `/reit-compliance/asset-sales/{id}/void` | Void while DRAFT or ANALYZED | ComplianceOfficer |
| POST | `/reit-compliance/compliance-disclosures` | Draft a disclosure against a locked/finalized reference | ComplianceOfficer |
| GET | `/reit-compliance/compliance-disclosures/{id}` | Fetch a disclosure | ComplianceOfficer, TaxDirector, BoardDirector |
| GET | `/reit-compliance/compliance-disclosures` | List disclosures; filterable by `reit_id` | ComplianceOfficer, TaxDirector, BoardDirector |
| POST | `/reit-compliance/compliance-disclosures/{id}/submit` | Submit for board review | ComplianceOfficer |
| POST | `/reit-compliance/compliance-disclosures/{id}/approve` | Board approves disclosure | BoardDirector |
| POST | `/reit-compliance/compliance-disclosures/{id}/reject` | Board rejects disclosure back to DRAFT | BoardDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUARTER_LOCKED` | 409 |
| `ERR_CROSS_REIT_REFERENCE` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_QUARTER_OVERLAP` | 409 |
| `ERR_REIT_SUSPENDED` | 409 |
| `ERR_FIVE_FIFTY_BLOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REQUIREMENT_NOT_POSTED` | 409 |
| `ERR_DECLARATIONS_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SNAPSHOT_EMPTY` | 422 |
