# Groundwater Sustainability & Well Metering Program API — Product Requirements Document

## 1. Introduction

California's groundwater sustainability agencies carry a statutory obligation to bring their basins into balance. Under that mandate, the agency must know who is pumping, from which well, in what quantity, and against which allocation — and it must be able to impose a price signal, suspend market activity, and report annually to the state when basin conditions deteriorate. This document specifies the Groundwater Sustainability & Well Metering Program API: the system of record for water-user accounts, registered wells, monthly extraction reporting, an allocation-and-credit ledger, an inter-account transfer market, monitoring-well telemetry, penalty assessments with a formal appeals channel, and the annual report submitted to the state regulator.

The program is built around a small number of strongly-typed resources whose state machines interlock. A water user cannot activate a production well until a meter is installed; an extraction report cannot be verified until a well is active; a transfer cannot settle while the basin's official condition is `CRITICAL`; and an overdraft of an account's effective allocation can cascade — at the moment a report is verified — into an automatic penalty assessment. Domestic wells are exempt from the metering requirement by design, and an independent appeals officer — never the same person who assessed a penalty — decides challenges. Throughout, the API enforces segregation of duties, optimistic concurrency on account updates, and a server-driven logical clock that governs reporting deadlines, transfer expiry, and water-year rollover.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting party, and `X-User-Role` names their operational capacity. Five roles are recognized, spelled exactly as follows: `WellOwner`, `WaterMaster`, `EnforcementOfficer`, `AppealsOfficer`, and `StateRegulator`. A request missing either header, or presenting a role string outside this declared set, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400). A request whose role is well-formed but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `WellOwner` role is entity-backed: when `X-User-Role` is `WellOwner`, `X-User-ID` is the `id` of the acting `WaterUserAccount`, and ownership checks on any resource that references a `WaterUserAccount` compare the resource's foreign-key field to `X-User-ID`. A `WellOwner`-scoped write whose target resource's owning account does not match the caller's `X-User-ID` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This ownership rule applies to registering a well, installing a meter, decommissioning a well as its owner, submitting or resubmitting an extraction report, proposing a transfer, accepting or cancelling a transfer as the counterparty owner, and paying or appealing a penalty assessment.

The remaining four roles are opaque: when `X-User-Role` is `WaterMaster`, `EnforcementOfficer`, `AppealsOfficer`, or `StateRegulator`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it — for example, as `assessed_by` on a `PenaltyAssessment` when an `EnforcementOfficer` files the assessment, or as `decided_by` when an `AppealsOfficer` rules on an appeal — but it never compares such an `X-User-ID` to any entity's `id` for ownership purposes. Segregation of duties is nevertheless enforced between these two opaque identities: the `AppealsOfficer` who decides an appeal must not be the same `X-User-ID` that filed the assessment.

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

Endpoints returning lists are paginated via two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Every list response sorts by `created_at` ascending; ties are broken by request-arrival order — that is, the order in which the server accepted the create calls. `id` is never used for ordering, ranking, or any other business decision. The `meta` block of a paginated list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Seven of the eight top-level resources — `WaterUserAccount`, `Well`, `ExtractionReport`, `TransferOrder`, `BasinConditionSnapshot`, `PenaltyAssessment`, and `AnnualStateReport` — share a common set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources (for example, when verifying an extraction report advances both the report's `version` and the owning account's `version`). `MonitoringReading` is the single exception: it is an append-only event log and carries only `id` and `created_at`. It has no `updated_at` and no `version`, and no update or delete endpoint exists for it.

### 2.5. The Logical Clock and the Water Year

The server maintains a logical clock that governs every time-dependent rule in the program: report deadlines, transfer expiry, monitoring-reading recency, appeal windows, and water-year rollover. Before any operator sets it, the clock defaults to `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time. A WaterMaster-only test-driving capability advances the clock by supplying `to_iso8601`; the response echoes the new instant as `current_utc`. Setting the clock also triggers an expiry sweep: every `TransferOrder` still in `PROPOSED` status whose `expires_at` is strictly before the new time transitions to `EXPIRED`, and each such expiry releases the seller's reservation. An account's `current_water_year` is stamped from the logical clock's calendar year at account creation and advances only via the year-close operation.

### 2.6. Precision, Rounding, and Monetary Representation

Acre-feet quantities (`base_allocation_af`, `reported_af`, `quantity_af`, `overdraft_af`, and the various computed allocation and ledger fields) are stored at 3 decimal places using round-half-up. Monetary amounts are always integer cents; when a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent at the per-record step. Basin-condition percentages and mean depths use 2 decimal places, round-half-up. Critically, annual totals are never re-derived from aggregate volumes: the sum of pumping fees reported to the state is the sum of already-rounded per-report fees, never a fresh rounding of aggregate acre-feet multiplied by a rate.

### 2.7. The Official Basin Condition as Derived Posture

The basin's official condition is not a stored field on any single record; it is a derived selector computed from the latest `PUBLISHED` `BasinConditionSnapshot`. Among snapshots whose `status` is `PUBLISHED`, the selector takes the one with the greatest `computed_at`; ties break by `created_at` descending. If no snapshot has ever been published, the official condition defaults to `NORMAL`. This selector drives three cross-cutting concerns: the curtailment factor applied to allocations, the fee and penalty multipliers applied at verification and assessment time, and the suspension of the transfer market. A derived snapshot condition of `CRITICAL` suspends all settlement activity and retroactively expires every still-open proposal.

### 2.8. Validation Order and Nested Retrieval

All requests pass through a consistent validation pipeline, and the order matters because earlier failures mask later ones. Authentication context is checked first (`ERR_MISSING_AUTH_CONTEXT`, then `ERR_FORBIDDEN_ROLE`, then `ERR_OWNERSHIP_MISMATCH`), then request shape (`ERR_INVALID_REQUEST` — covering missing or mistyped fields, enum membership, range violations such as `month` outside 1 through 12 or `quantity_af` not strictly positive, conditional-field violations such as `minimum_threshold_ft` present on a non-`MONITORING` well or `overdraft_af` present on a non-`OVERDRAFT` assessment, and a monitoring `measured_at` that falls after the logical clock), then path and body identifier existence (left-to-right for path ids, yielding the appropriate `ERR_ACCOUNT_NOT_FOUND`, `ERR_WELL_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, or `ERR_ANNUAL_REPORT_NOT_FOUND`), then the target resource's from-state preconditions (the various `ERR_INVALID_*_STATE` and `ERR_*_NOT_ACTIVE` codes), and only then the business-constraint, business-safety, and business-fiscal rules described in §3. When an operation path contains nested resource identifiers — for example, the readings collection of a specific well — path identifiers are validated left-to-right, so a request against a non-existent well id surfaces `ERR_WELL_NOT_FOUND` before any child collection is consulted.

### 2.9. Optimistic Concurrency Control on Account Updates

Mutations to a `WaterUserAccount` — specifically, the endpoint that updates `base_allocation_af` and/or `status` — require the request to carry `expected_account_version`, a non-optional input field carrying the client's last observed `version` of the account. If the account's current `version` has advanced since that observation — for instance because a report-verification cascade legitimately moved `extracted_af_ytd` and `pending_extraction_af` forward — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the writer from overwriting a state it never saw. Endpoints not named here do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Onboarding Water Users and Registering Wells

A `WaterMaster` onboards each participant by creating a `WaterUserAccount` with the holder's legal name as `holder_name`, an `account_type` drawn from `AGRICULTURAL`, `MUNICIPAL`, `INDUSTRIAL`, or `DOMESTIC`, and a strictly positive `base_allocation_af` expressed in acre-feet at 3-decimal precision. The account begins in `ACTIVE` status, its `current_water_year` is stamped from the logical clock's calendar year, and every computed ledger counter — `extracted_af_ytd`, `pending_extraction_af`, `credit_balance_af`, `transfer_out_af_ytd`, `transfer_reserved_af`, and `penalty_balance_cents` — initializes to 0.

A `WellOwner` then registers wells under their own account by supplying `account_id`, a `well_type` of `PRODUCTION`, `MONITORING`, or `DOMESTIC`, a free-text `location_description`, and — conditionally — `minimum_threshold_ft`. The threshold field is required if and only if the well is `MONITORING`, and it must be absent for `PRODUCTION` and `DOMESTIC` wells; presenting it on the wrong type is rejected with `ERR_INVALID_REQUEST`. The owning account must be `ACTIVE`, or registration fails with `ERR_ACCOUNT_NOT_ACTIVE`. Newly registered wells start in `REGISTERED` status with `meter_serial` unset (null). `well_type` is immutable once recorded.

### 3.2. Metering, the Domestic Exemption, and Well Activation

Production wells must be metered before they can pump legally. The owner of a `REGISTERED` production well records meter installation by supplying a `meter_serial`; the well transitions `REGISTERED` → `METER_INSTALLED` and the serial is stamped. Attempting installation on a well that is not `PRODUCTION` is rejected with `ERR_INVALID_WELL_TYPE`, and attempting it on a well no longer in `REGISTERED` status is rejected with `ERR_INVALID_WELL_STATE`.

Activation is a `WaterMaster` action with two distinct paths. For a `PRODUCTION` well, activation requires the well to be in `METER_INSTALLED` and advances it to `ACTIVE`. For `DOMESTIC` and `MONITORING` wells — which are exempt from the metering requirement — activation moves directly from `REGISTERED` to `ACTIVE` with no meter installed; attempting to activate a `PRODUCTION` well straight from `REGISTERED` is rejected with `ERR_INVALID_WELL_STATE`. In both paths, the owning account must be `ACTIVE` at activation time, or the request fails with `ERR_ACCOUNT_NOT_ACTIVE`. Decommissioning is available from any non-terminal status (`REGISTERED`, `METER_INSTALLED`, or `ACTIVE`) to either the owner or a `WaterMaster`; the well lands in `DECOMMISSIONED`. When a monitoring well is decommissioned it is excluded from future basin-condition input sets, though historical extraction reports against it remain verifiable records.

### 3.3. Monthly Extraction Reporting and the Revision Loop

The owner of an `ACTIVE` `PRODUCTION` well submits a monthly extraction report carrying `well_id`, `water_year`, `month`, and `reported_af`. The `water_year` must equal the owning account's `current_water_year` (a mismatch yields `ERR_REPORT_YEAR_MISMATCH`), `month` must be an integer between 1 and 12 inclusive, and `reported_af` must be non-negative at 3-decimal precision. At most one report may exist per well, water year, and month across all statuses — duplicates are rejected with `ERR_DUPLICATE_REPORT`. Submitting against a well that is not `ACTIVE` yields `ERR_WELL_NOT_ACTIVE`; submitting against a non-`PRODUCTION` well yields `ERR_INVALID_WELL_TYPE`. A new report lands in `SUBMITTED` status, its `late_flag` is computed at submission (true exactly when the logical clock has reached the 16th 00:00:00 UTC of the month following the reported `(water_year, month)` — month 12 wraps to January of the following year — so a submission at any instant on the 15th through 23:59:59 is not late), and the reported volume is added to the account's `pending_extraction_af`.

A `WaterMaster` then either verifies or disputes the report. Verification requires `SUBMITTED` status — anything else is `ERR_INVALID_REPORT_STATE` — and triggers the deepest cascade in the system. The reported volume moves from `pending_extraction_af` into `extracted_af_ytd`. A pumping fee is stamped onto the report's `fee_cents`: the fee equals `reported_af` multiplied by the base rate of 3000 cents per acre-foot, then multiplied by the basin-condition multiplier in force at the verification instant — 1.00 under `NORMAL`, 1.10 under `WATCH`, and 1.25 under `CRITICAL` — with the per-report result rounded half-up to integer cents. Verification then runs an overdraft-crossing check: the account's overdraft volume is the amount by which `extracted_af_ytd`, after subtracting the effective allocation and the credit balance and adding back `transfer_out_af_ytd`, exceeds zero. If the overdraft was zero or negative before this verification and is strictly positive after it, the system auto-creates a `PenaltyAssessment` with `reason` `OVERDRAFT`, the report's `water_year`, an `overdraft_af` equal to the computed overdraft, and `assessed_by` set to the literal string `system`, and the new penalty's `amount_cents` is debited into the account's `penalty_balance_cents`. Both the report's `version` and the owning account's `version` increment.

Dispute instead moves the report `SUBMITTED` → `DISPUTED` and removes the reported volume from `pending_extraction_af`. The owner may then amend and resubmit: resubmission requires `DISPUTED` status, the report's `water_year` must still equal the account's `current_water_year` (else `ERR_REPORT_YEAR_MISMATCH`), and the payload carries the new `reported_af`. Resubmission replaces the reported volume, increments `amendment_count` by 1, recomputes `late_flag` against the current logical clock, adds the new volume back into `pending_extraction_af`, and returns the report to `SUBMITTED`. A report may cycle `SUBMITTED` → `DISPUTED` → `SUBMITTED` any number of times until it is finally verified; `VERIFIED` is terminal. `fee_cents` remains null until verification.

### 3.4. The Transfer Market: Proposal, Acceptance, Settlement

A `WellOwner` proposes a transfer by naming `seller_account_id`, `buyer_account_id`, `quantity_af` in acre-feet, an agreed `unit_price_cents` per acre-foot (informational only — the agency does not clear payments, and the value may be zero), and a half-open coverage window from `effective_start_date` to `effective_end_date` (both `YYYY-MM-DD`; the end date must be strictly after the start date; the window covers the start date and excludes the end date). The seller and buyer must differ (`ERR_SELF_TRANSFER`), both parties' accounts must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the proposal passes through three independent gates evaluated in the order stated here. First, the buyer inbound-window rule: no two transfer orders with the same `buyer_account_id` and a status of `PROPOSED`, `ACCEPTED`, or `SETTLED` may have overlapping half-open windows; adjacency — where an existing order's `effective_end_date` equals the new order's `effective_start_date` — is permitted, and a true overlap is rejected with `ERR_TRANSFER_WINDOW_OVERLAP`. Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`. Third, basin-wide monthly capacity: for every calendar month the new order's window intersects, the aggregate `quantity_af` across all orders in `PROPOSED`, `ACCEPTED`, or `SETTLED` whose windows intersect that same month, plus the new order's `quantity_af`, must not exceed 5000 acre-feet; a month whose running total reaches exactly 5000 is allowed, but any excess is rejected with `ERR_MONTHLY_TRANSFER_CAP_EXCEEDED`.

A created order lands in `PROPOSED`, its `expires_at` is stamped at creation time plus 72 hours, and the seller's `transfer_reserved_af` increases by `quantity_af` — a reservation against double-selling that blocks the same water from being committed twice. The owner of the buyer account accepts a `PROPOSED` order, moving it to `ACCEPTED`; the owner of the seller account cancels a `PROPOSED` order, moving it to `CANCELLED` and releasing the reservation. Any other from-state for accept or cancel is `ERR_INVALID_TRANSFER_STATE`. Independently, the logical-clock sweep expires any `PROPOSED` order once the clock passes its `expires_at`, also releasing the reservation.

Settlement and rejection are `WaterMaster` actions against `ACCEPTED` orders (any other from-state yields `ERR_INVALID_TRANSFER_STATE`). Rejection moves the order to `REJECTED` and releases the seller's reservation. Settlement performs two preconditions before committing: the official basin condition must not be `CRITICAL` (settlement during `CRITICAL` is rejected with `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED`), and the seller's settled-variant available water — computed with the order being settled first removed from `transfer_reserved_af`, so its own reservation does not count against it — must be at least `quantity_af`, failing which the settle is rejected with `ERR_SETTLE_INSUFFICIENT_WATER`. On a successful settle, the seller's `transfer_reserved_af` decreases by `quantity_af`, the seller's `transfer_out_af_ytd` increases by `quantity_af`, the buyer's `credit_balance_af` increases by `quantity_af`, `settled_at` is stamped from the logical clock, and the `version` of the order and of both accounts increments by 1.

### 3.5. Monitoring Wells and Basin Condition Snapshots

A `WaterMaster` records depth readings against `ACTIVE` `MONITORING` wells by supplying `well_id`, `measured_at` (an ISO 8601 UTC instant that must not be after the logical clock, or the request fails with `ERR_INVALID_REQUEST`), `depth_to_water_ft` (strictly positive, 2-decimal precision; larger values indicate a worse condition), and `collector_name`. A reading submitted against a non-`MONITORING` well is rejected with `ERR_INVALID_WELL_TYPE`, and against a well that is not `ACTIVE` with `ERR_WELL_NOT_ACTIVE`. Readings are append-only and feed the basin-condition evaluation.

When a `WaterMaster` requests a new snapshot, the system first discards any existing `DRAFT` snapshot (the prior draft transitions to `DISCARDED` and its `version` increments), then computes a fresh `DRAFT` snapshot from current monitoring data. The input set consists of every well whose `well_type` is `MONITORING` and whose `status` is `ACTIVE`, taking each well's latest reading by `measured_at` descending (ties broken by `created_at` descending), but only if that reading's `measured_at` falls within 90 days of the logical clock; wells with no eligible reading are excluded. `eligible_well_count` is the number of wells that survive this filter. The snapshot computes two variants in parallel.

The official, gating variant is threshold-breach: `breached_well_count` is the number of eligible wells whose latest reading's `depth_to_water_ft` is strictly greater than their `minimum_threshold_ft`, and `breach_pct` is one hundred times `breached_well_count` divided by `eligible_well_count`, rounded half-up to 2 decimal places. The snapshot's `condition` is `CRITICAL` when `breach_pct` is at least 50, `WATCH` when it is at least 25 but below 50, and `NORMAL` otherwise — a value of exactly 50.00 lands on `CRITICAL`, and exactly 25.00 lands on `WATCH`. The published variant is the rolling mean: `rolling_mean_depth_ft` is the arithmetic mean of the latest eligible depths, rounded half-up to 2 decimal places, and `mean_condition` is `CRITICAL` when the mean is at least 120.00 feet, `WATCH` when it is at least 100.00 but below 120.00, and `NORMAL` otherwise. When no wells are eligible, `condition` is `NORMAL` while `breach_pct`, `rolling_mean_depth_ft`, and `mean_condition` are all null. The new snapshot's `computed_at` is stamped from the logical clock.

Publishing is a separate `WaterMaster` step that requires the snapshot to be in `DRAFT` (anything else yields `ERR_INVALID_SNAPSHOT_STATE`). Publication makes the snapshot the new candidate for the official-condition selector. Critically, when a published snapshot's `condition` is `CRITICAL`, every transfer order still in `PROPOSED` immediately transitions to `EXPIRED` — a market-wide suspension — and each such expiry releases its seller's reservation by decreasing `transfer_reserved_af` by the order's `quantity_af`.

### 3.6. Penalties, Appeals, and the Segregation of Duties

Penalty assessments originate in two ways. The automatic path is the overdraft cascade described in §3.3. The manual path is an `EnforcementOfficer` filing an assessment against an account by supplying `account_id`, a `reason` of `OVERDRAFT`, `LATE_REPORT`, or `UNMETERED_PUMPING`, the `water_year` the violation belongs to, and — conditionally — `overdraft_af`. The conditional field is required if and only if `reason` is `OVERDRAFT`, must be absent otherwise (`ERR_INVALID_REQUEST`), and when present must equal the computed overdraft volume at 3-decimal comparison or the filing is rejected with `ERR_OVERDRAFT_AMOUNT_MISMATCH`.

The penalty amount in `amount_cents` depends on the reason. For `LATE_REPORT` the fee is a flat 10000 cents; for `UNMETERED_PUMPING` it is a flat 50000 cents; flat fees are never multiplied by the basin-condition multiplier. For `OVERDRAFT`, the amount is computed from the overdraft volume through a two-tier schedule. The first tier covers the portion of the overdraft up to ten percent of the account's `base_allocation_af` (the tier-1 limit itself rounded half-up to 3 decimals) and is priced at 10000 cents per acre-foot; any overdraft above that limit falls into the second tier at 25000 cents per acre-foot. The sum of the two tier charges is then multiplied by the official-condition multiplier in force at the assessment-creation instant — 1.00, 1.10, or 1.25 for `NORMAL`, `WATCH`, `CRITICAL` respectively — and the final amount is rounded half-up to integer cents. The overdraft volume itself is the settled-basis figure: the greater of zero and `extracted_af_ytd` minus the effective allocation minus `credit_balance_af` plus `transfer_out_af_ytd`, rounded half-up to 3 decimals. A new assessment starts in `ASSESSED` status, `assessed_by` is stamped from the caller's `X-User-ID` (or the literal `system` for the auto-created cascade), and the account's `penalty_balance_cents` increases by `amount_cents`.

The account owner may pay an assessment while it is in `ASSESSED`, `UPHELD`, or `REDUCED` — any other status yields `ERR_INVALID_ASSESSMENT_STATE`. Payment from `ASSESSED` or `UPHELD` debits `penalty_balance_cents` by `amount_cents` and stamps `paid_amount_cents` equal to `amount_cents`; payment from `REDUCED` debits by `reduced_amount_cents` and stamps `paid_amount_cents` equal to `reduced_amount_cents`. The owner may instead appeal an `ASSESSED` assessment by supplying `grounds`, provided the logical clock has not passed 30 days after the assessment's `created_at` — filing exactly at the deadline is allowed, and strictly later filings are rejected with `ERR_APPEAL_WINDOW_CLOSED`. A successful appeal moves the assessment to `APPEALED`.

Decisions belong to an `AppealsOfficer` and require `APPEALED` status. Segregation of duties is enforced: the decider's `X-User-ID` must differ from the assessment's `assessed_by`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The `outcome` field selects among three branches, each of which stamps `decided_by`. `UPHELD` leaves `penalty_balance_cents` unchanged. `OVERTURNED` debits `penalty_balance_cents` by the full `amount_cents` — a full refund. `REDUCED` requires a `reduced_amount_cents` value that is strictly greater than zero and strictly less than `amount_cents` (any other value, or its absence, fails with `ERR_INVALID_REQUEST`); it debits `penalty_balance_cents` by the difference between `amount_cents` and `reduced_amount_cents` — a partial refund — and records the reduced figure on the assessment. `PAID` and `OVERTURNED` are terminal.

### 3.7. Year-End Close and the Annual State Report

A `WaterMaster` closes a water year by supplying `water_year`. The close is blocked while any extraction report in `SUBMITTED` or `DISPUTED` status exists for the closing year across any account — such a request fails with `ERR_CLOSE_YEAR_UNRESOLVED_REPORTS`. For every account whose `status` is `ACTIVE` or `SUSPENDED` and whose `current_water_year` equals the closing year, the close computes a carryover credit on the settled basis (pending, unverified extraction does not reduce the carryover): the unused volume is the greater of zero and the effective allocation minus `extracted_af_ytd` minus `transfer_out_af_ytd`, rounded half-up to 3 decimals, and the carryover grant is the smaller of that unused volume and twenty-five percent of `base_allocation_af`, again rounded half-up to 3 decimals. The grant is added to `credit_balance_af` (which therefore survives the year boundary), `extracted_af_ytd`, `pending_extraction_af`, and `transfer_out_af_ytd` reset to zero, `current_water_year` advances by one, and the account's `version` increments. The close response reports `closed_water_year`, the number of accounts rolled as `accounts_rolled`, and the aggregate grant as `total_carryover_af`. The carryover computation uses the same effective allocation as the rest of the system — including the curtailment factor when the official basin condition is `CRITICAL`.

Once a year has been closed, a `WaterMaster` generates the `AnnualStateReport` for it by supplying `water_year`. Generating against a year that has not been closed fails with `ERR_WATER_YEAR_NOT_CLOSED`; a second report for the same year fails with `ERR_ANNUAL_REPORT_EXISTS`. The generated report aggregates the year's activity: `total_extracted_af` is the sum of `reported_af` over all `VERIFIED` extraction reports of that water year across all accounts, rounded half-up to 3 decimals; `verified_report_count` counts the same set; `total_pumping_fees_cents` is the sum of `fee_cents` over that same set — the sum of the per-report rounded fees, never recomputed from `total_extracted_af`; `overdraft_assessment_count` counts penalty assessments with `reason` `OVERDRAFT` for the year; `penalties_assessed_cents` sums `amount_cents` over all of the year's penalty assessments regardless of status; and `penalties_collected_cents` sums `paid_amount_cents` over the year's assessments whose status is `PAID`. The report also captures basin condition at generation time: `final_basin_condition` and `avg_depth_ft` are the `condition` and `rolling_mean_depth_ft` of the official-condition selector snapshot — the latest `PUBLISHED` snapshot by `computed_at`, tie-broken by `created_at` descending — and both are null when no snapshot has ever been published. A new annual report starts in `DRAFT`.

The `WaterMaster` submits a `DRAFT` report to the state, moving it to `SUBMITTED` (any other from-state yields `ERR_INVALID_ANNUAL_REPORT_STATE`), and a `StateRegulator` acknowledges a `SUBMITTED` report, moving it to `ACKNOWLEDGED`, which is terminal.

### 3.8. Account Suspension, Closure, and Effective Allocation

A `WaterMaster` manages account posture through the account-update operation, which requires `expected_account_version` per §2.9 and may adjust `base_allocation_af` and/or `status`. An `ACTIVE` account may be suspended (`ACTIVE` → `SUSPENDED`) and later reinstated (`SUSPENDED` → `ACTIVE`); either transition increments the account's `version` by 1. Closure — the transition to the terminal `CLOSED` status — is permitted from either `ACTIVE` or `SUSPENDED` but carries two preconditions: no transfer order may exist with this account as `buyer_account_id` in `ACCEPTED` status, and no penalty assessment for this account may be in `APPEALED` status — either violation is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. A successful close cascades: every well of the account that is not already `DECOMMISSIONED` transitions to `DECOMMISSIONED`; every outbound transfer order in `PROPOSED` transitions to `CANCELLED` with its reservation released, and every outbound order in `ACCEPTED` transitions to `REJECTED` with its reservation released; and the account's `version` increments by 1.

The effective allocation referenced throughout this document is itself a derived figure, never stored: it equals `base_allocation_af` multiplied by a curtailment factor, rounded half-up to 3 decimals. The curtailment factor is 0.80 while the official basin condition is `CRITICAL` and 1.00 otherwise, with the official condition taken from the selector of §2.7 at each point of use. Effective allocation feeds the available-water computations, the overdraft penalty basis, and the carryover credit, so a shift in basin posture immediately reprices every account's headroom.

Available water itself has two variants used in different places. The forward-looking variant, used only for the seller-sufficiency gate at transfer proposal, equals the effective allocation plus `credit_balance_af`, minus `extracted_af_ytd`, minus `pending_extraction_af` (which counts only `SUBMITTED` reports of the account's current water year — `VERIFIED` and `DISPUTED` reports are excluded from this counter), minus `transfer_out_af_ytd`, minus `transfer_reserved_af`. The settled variant, used at settlement re-check, as the overdraft basis, and at year-end carryover, is identical except that `pending_extraction_af` is not subtracted — only verified extraction counts against it.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below summarizes the HTTP contract; request payloads, computed fields, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/water-user-accounts` | Onboard a water user account; `current_water_year` set from the logical clock's calendar year | WaterMaster |
| GET | `/water-user-accounts` | List accounts; filterable by `status` and `account_type` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| GET | `/water-user-accounts/{accountId}` | Get one account including computed ledger fields | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| PATCH | `/water-user-accounts/{accountId}` | Update `base_allocation_af` and/or `status` under optimistic concurrency | WaterMaster |
| POST | `/wells` | Register a well under an `ACTIVE` account | WellOwner |
| GET | `/wells` | List wells; filterable by `account_id`, `well_type`, `status` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| GET | `/wells/{wellId}` | Get one well | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/wells/{wellId}/install-meter` | Record meter installation on a `REGISTERED` `PRODUCTION` well | WellOwner |
| POST | `/wells/{wellId}/activate` | Activate a well (metered path for `PRODUCTION`; exemption path for `DOMESTIC`/`MONITORING`) | WaterMaster |
| POST | `/wells/{wellId}/decommission` | Decommission a non-terminal well | WellOwner, WaterMaster |
| POST | `/extraction-reports` | Submit a monthly extraction report for an `ACTIVE` `PRODUCTION` well | WellOwner |
| GET | `/extraction-reports` | List extraction reports; filterable by `well_id`, `status`, `water_year` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| GET | `/extraction-reports/{reportId}` | Get one extraction report | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/extraction-reports/{reportId}/verify` | Verify a `SUBMITTED` report (stamps fee; may trigger the overdraft cascade) | WaterMaster |
| POST | `/extraction-reports/{reportId}/dispute` | Dispute a `SUBMITTED` report | WaterMaster |
| POST | `/extraction-reports/{reportId}/resubmit` | Amend and resubmit a `DISPUTED` report | WellOwner |
| POST | `/transfer-orders` | Propose a water transfer from seller to buyer | WellOwner |
| GET | `/transfer-orders` | List transfer orders; filterable by `seller_account_id`, `buyer_account_id`, `status` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| GET | `/transfer-orders/{transferId}` | Get one transfer order | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/transfer-orders/{transferId}/accept` | Buyer accepts a `PROPOSED` order | WellOwner |
| POST | `/transfer-orders/{transferId}/cancel` | Seller cancels a `PROPOSED` order | WellOwner |
| POST | `/transfer-orders/{transferId}/settle` | Agency settles an `ACCEPTED` order (blocked while the basin is `CRITICAL`) | WaterMaster |
| POST | `/transfer-orders/{transferId}/reject` | Agency rejects an `ACCEPTED` order | WaterMaster |
| POST | `/monitoring-readings` | Record a depth reading for an `ACTIVE` `MONITORING` well | WaterMaster |
| GET | `/wells/{id}/monitoring-readings` | List readings of a well | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/basin-condition-snapshots` | Compute a new `DRAFT` snapshot from current monitoring data; supersedes any existing `DRAFT` | WaterMaster |
| GET | `/basin-condition-snapshots` | List snapshots; filterable by `status` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/basin-condition-snapshots/{snapshotId}/publish` | Publish a `DRAFT` snapshot; publishing `CRITICAL` suspends the transfer market | WaterMaster |
| POST | `/penalty-assessments` | Manually assess a penalty (flat fees or a verified `OVERDRAFT` amount) | EnforcementOfficer |
| GET | `/penalty-assessments` | List penalty assessments; filterable by `account_id`, `status`, `reason` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| GET | `/penalty-assessments/{assessmentId}` | Get one penalty assessment | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/penalty-assessments/{assessmentId}/pay` | Pay an `ASSESSED`/`UPHELD`/`REDUCED` assessment | WellOwner |
| POST | `/penalty-assessments/{assessmentId}/appeal` | Appeal an `ASSESSED` assessment within 30 days of creation | WellOwner |
| POST | `/penalty-assessments/{assessmentId}/decide` | Decide an `APPEALED` assessment; decider must differ from assessor | AppealsOfficer |
| POST | `/annual-state-reports` | Generate the `DRAFT` annual report for a closed water year | WaterMaster |
| GET | `/annual-state-reports` | List annual state reports; filterable by `water_year`, `status` | WellOwner, WaterMaster, EnforcementOfficer, AppealsOfficer, StateRegulator |
| POST | `/annual-state-reports/{reportId}/submit` | Submit a `DRAFT` annual report to the state | WaterMaster |
| POST | `/annual-state-reports/{reportId}/acknowledge` | State regulator acknowledges a `SUBMITTED` annual report | StateRegulator |
| POST | `/admin/close-water-year` | Close a water year; applies carryover credit to each account in the closing year | WaterMaster |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock; sweeps expired `PROPOSED` transfer orders | WaterMaster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_WELL_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_ANNUAL_REPORT_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_WELL_STATE` | 409 |
| `ERR_WELL_NOT_ACTIVE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_INVALID_TRANSFER_STATE` | 409 |
| `ERR_INVALID_ASSESSMENT_STATE` | 409 |
| `ERR_INVALID_SNAPSHOT_STATE` | 409 |
| `ERR_INVALID_ANNUAL_REPORT_STATE` | 409 |
| `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_WELL_TYPE` | 422 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_REPORT_YEAR_MISMATCH` | 422 |
| `ERR_SELF_TRANSFER` | 422 |
| `ERR_TRANSFER_WINDOW_OVERLAP` | 409 |
| `ERR_CLOSE_YEAR_UNRESOLVED_REPORTS` | 409 |
| `ERR_WATER_YEAR_NOT_CLOSED` | 409 |
| `ERR_ANNUAL_REPORT_EXISTS` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_OVERDRAFT_AMOUNT_MISMATCH` | 422 |
| `ERR_INSUFFICIENT_AVAILABLE_WATER` | 422 |
| `ERR_MONTHLY_TRANSFER_CAP_EXCEEDED` | 422 |
| `ERR_SETTLE_INSUFFICIENT_WATER` | 422 |
