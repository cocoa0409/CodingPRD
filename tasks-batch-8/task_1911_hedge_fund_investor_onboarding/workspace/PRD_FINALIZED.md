# Hedge Fund Investor Onboarding API — Product Requirements Document

## 1. Introduction

Fund administrators running hedge fund operations face an unusually demanding onboarding problem. Each prospective investor must be vetted through AML/KYC screening, proven eligible to purchase restricted securities under accredited investor or qualified purchaser rules, committed to a capital amount with a hard funding deadline, and — only after all of that clears — admitted into the fund's series/lot accounting structure so that incentive fees can be tracked fairly across investors who entered at different NAV points. Layered on top of this are side letters whose negotiated terms (fee rebates, liquidity windows, information rights) must be honored per-investor, most-favored-nation clauses that must be tracked and elected against, and a redemption process that respects lockup periods, advance-notice windows, fund-level gates, and outright suspension.

This document describes an API that automates that entire lifecycle for a hedge fund administrator. It governs the registration of investors, the verification of their identity and accreditation, the intake and funding of capital commitments, the creation of capital accounts under series accounting, the administration of side letters and MFN elections, the processing of redemption requests through notice/lockup/gate rules, and the generation of periodic investor statements.

The system is built around a strict segregation of duties: `FundAdmin` staff control fund configuration and subscription acceptance, `ComplianceOfficer` staff control KYC and accreditation decisions, `TransferAgent` staff record wire receipts and assist with document intake, `PortfolioManager` staff observe but never mutate, and `Investor` actors operate only on their own records. Every rule in this document is enforced against a logical server clock (never wall-clock time) so that deadlines, lockups, notice windows, and attestation expiry are fully testable and deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `FundAdmin`, `ComplianceOfficer`, `TransferAgent`, `PortfolioManager`, and `Investor`. Failure to provide both headers in a well-formed shape results in `ERR_UNAUTHENTICATED`. When the headers are present but the role is not permitted to invoke the requested operation, the system rejects the call with `ERR_FORBIDDEN`.

Role identity works differently for the `Investor` role than for the four staff roles. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor` record; ownership checks on any resource that references an `Investor` compare that resource's `investor_id` foreign-key field to `X-User-ID`. An `Investor` may only read or mutate their own investor record, their own KYC cases, their own accreditation attestations, their own subscriptions, their own side letters, their own capital accounts, their own redemption requests, and their own statements; attempts to act on another investor's resources are rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `FundAdmin`, `ComplianceOfficer`, `TransferAgent`, or `PortfolioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Logical Server Clock

Every time-dependent rule in this system — funding deadlines, lockup expiry, redemption notice windows, attestation staleness, attestation expiry sweeps — reads from a single logical clock, never from wall-clock time. Before any client has set it, the logical clock is exactly `2026-08-01T00:00:00Z`. A `FundAdmin` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`. Advancing the clock re-runs two side-effect sweeps: any `AccreditationAttestation` whose `expires_at_utc` has been passed transitions to `EXPIRED` (with the downstream effects described in §3.4), and any KYC-related expiry bookkeeping is re-evaluated. Because deadlines and lockups all consult this same clock, advancing it can change which transitions are permitted on the very next request.

### 2.5. Common Resource Properties and Hierarchical Mutation

All primary resources in the system — `Fund`, `ShareClass`, `NavPeriod`, `Series`, `Investor`, `KycCase`, `AccreditationAttestation`, `Subscription`, `SideLetter`, `MfnClause`, `CapitalAccount`, `SeriesLot`, `RedemptionRequest`, and `InvestorStatement` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, updated upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by 1 on every modification to the resource.

Mutations that cascade — for example, when accepting a subscription bumps `Fund.total_net_assets_cents` and increments `Fund.version`, or when executing a side letter increments `Subscription.version` — are each considered full mutations of the mutated resource and therefore refresh `updated_at` and bump `version` on each touched record independently.

### 2.6. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers (for example, a subscription nested under a fund, or a series lot nested under a capital account nested under an investor), the system validates the existence of each identifier in sequential, left-to-right order. The request is rejected immediately with `ERR_NOT_FOUND` corresponding to the first identifier in the path that does not correspond to an existing resource; the system does not proceed to validate identifiers further to the right once an earlier one has failed. This principle extends to creation and modification operations: the parent's existence is confirmed before any child validation, and the child's existence under that parent is confirmed before any business rule runs. A request naming a `share_class_id` that does not belong to the fund in the path, or a `subscription_id` whose `investor_id` does not match the investor in the path, is likewise `ERR_NOT_FOUND`.

### 2.7. Monetary Precision, Rounding, and Basis Points

All monetary amounts in the system are carried as integer cents in fields whose names end in `_cents` (e.g., `commitment_amount_cents`, `funded_amount_cents`, `total_net_assets_cents`, `current_balance_cents`, `settled_amount_cents`). Rates, fees, and thresholds that would naturally be fractions of a percent are carried as integer basis points (`management_fee_bps`, `performance_fee_bps`, `hurdle_rate_bps`, `fee_rebate_bps`, `equalization_factor_bps`), so that 100 basis points is 1% and 5 basis points is 0.05%.

Rounding rules are pinned per calculation and are not interchangeable. The series equalization factor is expressed as an integer number of basis points, rounded half-up exactly once at the very end of the computation — intermediate values retain full precision and are never rounded early. The redemption gate proration uses six-decimal fixed-point arithmetic for `gate_applied_pct` and integer cents for `settled_amount_cents`, with a floor-per-line-then-distribute-remainder rounding order (never round-per-line-to-nearest). The late funding fee accrues with per-day round-half-up rounding summed across days — not summed-then-rounded — and the order is pinned because the two orders disagree on odd funded amounts.

### 2.8. Optimistic Concurrency Control

Three write operations in the system are guarded by optimistic concurrency control against a parent entity's `version`. In each case the request must carry an explicit expected-version field, the server compares it to the parent entity's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not accept any version field.

First, accepting a subscription (the `FundAdmin` action that transitions a funded subscription into `ACCEPTED` and creates its capital account) requires the request to carry `expected_fund_version` equal to the fund's current `version`. If another writer has advanced the fund's version since the client last observed it — most commonly by accepting a different subscription, which adds to `Fund.total_net_assets_cents` and thereby re-prices the series NAV the current acceptance relies on — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412).

Second, finalizing a NAV period requires the request to carry `expected_fund_version` equal to the fund's current `version`. Finalization freezes per-series equalization factors against the fund's net assets at a particular version; if the version has advanced since the client last read the fund, the cached total is stale and the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be re-issued with a fresh value.

Third, executing a side letter requires the request to carry `expected_subscription_version` equal to the subscription's current `version`. Execution supersedes prior letters and re-prices fee terms whose validity depends on the subscription state observed at drafting; if the subscription's version has advanced since the client last read it, the execute is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Validation Ordering

When multiple validation rules apply to the same endpoint, the server evaluates them in a fixed priority order and returns the first failure encountered. The order is: authentication (`ERR_UNAUTHENTICATED`) first, then role authorization (`ERR_FORBIDDEN`), then parent resource existence (`ERR_NOT_FOUND` on the left-most missing path identifier), then child resource existence (`ERR_NOT_FOUND`), then state validity (`ERR_INVALID_STATE`), then the business rules attached to the specific endpoint (sanctions, suspension, attestation staleness, deadlines, lockup, notice, minimum investment, class openness, capacity thresholds, clause retirement, document completeness, supersession validity, series matching, open NAV period, amount positivity, balance sufficiency), and only then the optimistic-concurrency check (`ERR_STALE_VERSION`). The OCC check therefore runs after all other validations on the three guarded endpoints — a request that fails a business rule surfaces that rule's error, not the stale-version error, even if the version is also stale.

## 3. Business Logic & Workflows

### 3.1. Fund and Share Class Setup

A `FundAdmin` begins by creating a `Fund` with its `fund_name`, `domicile`, `gate_threshold_pct` (the investor-level gate — the maximum percent of fund net assets that may be redeemed in a single period, expressed as a decimal fraction such as 0.25 for 25%), `lockup_months_default`, `notice_days_default`, and `fiscal_year_end_month` (an integer 1–12). The fund's `suspension_status` starts as `NOT_SUSPENDED`, its `current_nav_period_id` starts as null because no NAV period is open yet, and its `total_net_assets_cents` starts at 0.

Under a fund, the `FundAdmin` creates one or more `ShareClass` records. Each share class is owned by exactly one fund via its `fund_id`, and carries a ticker-style `class_code` (e.g., 'A1', 'B-INST'), `min_initial_investment_cents`, `min_additional_investment_cents`, `management_fee_bps`, `performance_fee_bps`, `hurdle_rate_bps` (an annualized hurdle in basis points, where 0 means no hurdle), `high_water_mark_required` (a boolean indicating whether the incentive fee requires high-water mark recovery), `lockup_months` (the hard lockup measured from subscription funding date), `notice_days` (the redemption notice days required before the redemption effective date), and `redemption_frequency` (one of `MONTHLY`, `QUARTERLY`, `SEMI_ANNUAL`, `ANNUAL`). Each share class also exposes two system-managed flags — `is_open_for_subscription` and `is_open_for_redemption` — both of which default to true and may be flipped to false by a `FundAdmin` to close the class to new subscriptions or to redemptions respectively. Closing a class to subscriptions blocks new subscription submissions with `ERR_CLASS_CLOSED`; closing it to redemptions blocks redemption approvals.

At any time, the `FundAdmin` may suspend all redemptions on a fund, which sets `suspension_status` to `SUSPENDED`, or resume them, which returns it to `NOT_SUSPENDED`. Suspension blocks redemption approvals with `ERR_REDEMPTIONS_SUSPENDED` until lifted.

### 3.2. Investor Registration and KYC Verification

An investor enters the system when a `FundAdmin` or `TransferAgent` registers an `Investor` with `legal_name`, `investor_type` (one of `INDIVIDUAL`, `JOINT`, `CORPORATION`, `TRUST`, `PARTNERSHIP`, `LLC`, `EMPLOYEE_BENEFIT_PLAN`), `tax_id`, `email`, `residence_country` (an ISO 3166 country of tax residence), and `is_us_person` (a boolean that drives whether the accredited-investor or qualified-purchaser verification path applies). New investors start with `kyc_status` set to `NOT_STARTED`, `accreditation_status` set to `UNVERIFIED`, and `aggregate_unfunded_commitment_cents` at 0.

KYC verification proceeds through `KycCase` records opened under the investor. A `ComplianceOfficer` or `FundAdmin` opens a case by providing a `risk_rating` (one of `LOW`, `MEDIUM`, `HIGH`, `PROHIBITED`), plus the screening flags `pep_hit`, `sanctions_hit`, and `adverse_media_hit`. Each case receives a `case_sequence` (1-based within the investor) and starts in `OPEN`, then immediately auto-transitions to `AWAITING_DOCUMENTS`, at which point the system populates `required_documents` from the combination of `investor_type` and `risk_rating`. Opening a case also updates the investor's `kyc_status` to `DOCUMENTS_PENDING`.

The investor (or a `TransferAgent` on their behalf) submits documents one at a time by providing a `document_type` and `document_reference`. Each submission appends to the case's `submitted_documents`. The transition from `AWAITING_DOCUMENTS` to `IN_REVIEW` is gated on document completeness: the set of submitted document types must cover every entry in `required_documents`. An attempt to advance the case before the required set is fully submitted is rejected with `ERR_INCOMPLETE_DOCUMENTS`. Once the last required document arrives, the case moves to `IN_REVIEW`.

A `ComplianceOfficer` then resolves the case. Approving a case from `IN_REVIEW` requires that `sanctions_hit` be false — a sanctions hit blocks approval outright with `ERR_SANCTIONS_HIT` — and that either `pep_hit` be false or the case's `risk_rating` be `LOW`. A case with `sanctions_hit` true, or with `pep_hit` true at a non-`LOW` risk rating, auto-transitions from `IN_REVIEW` to `ESCALATED`, and the only way out of `ESCALATED` is a senior override: a `ComplianceOfficer` approving with the `senior_override` flag set to true in the payload. An approve attempted on an `ESCALATED` case without the `senior_override` flag is rejected: with `ERR_SANCTIONS_HIT` when the case's `sanctions_hit` is true, and with `ERR_INVALID_STATE` otherwise. Rejecting a case (from `AWAITING_DOCUMENTS`, `IN_REVIEW`, or `ESCALATED`) sets the case's `rejection_reason`, marks the investor's `kyc_status` as `REJECTED`, and transitions every non-terminal `Subscription` belonging to that investor to `REJECTED`. Approving a case from either `IN_REVIEW` or `ESCALATED` sets the investor's `kyc_status` to `APPROVED` and, as a cascade, transitions any of that investor's subscriptions currently sitting in `KYC_HOLD` into `COMPLIANCE_APPROVED`.

### 3.3. Accreditation Attestation and Expiry

In parallel with KYC, an investor (or `TransferAgent`) submits `AccreditationAttestation` records claiming a tier — `attestation_tier` is one of `ACCREDITED` or `QUALIFIED_PURCHASER` — supported by an `evidence_type` (one of `INCOME_STATEMENT`, `NET_WORTH_CERT`, `CPA_LETTER`, `LICENSED_PROFESSIONAL`, `ENTITY_ASSETS`), an `evidence_document_id` referencing the evidence artifact, and an `attested_at_utc` timestamp recording when the investor signed. Each new attestation starts in `PENDING_REVIEW`. Its `expires_at_utc` is computed as `attested_at_utc` plus 365 days.

A `ComplianceOfficer` verifies an attestation from `PENDING_REVIEW`. Verification requires that `evidence_document_id` be present and that `attested_at_utc` fall within the past 90 days at verify time — an attestation signed more than 90 days ago is rejected with `ERR_STALE_ATTESTATION`. Successful verification transitions the attestation to `VERIFIED` and upgrades the investor's `accreditation_status` to the attestation's tier if that tier is higher than the investor's current one. A `ComplianceOfficer` may instead reject the attestation, providing a `rejection_reason`.

Attestations expire automatically. When the logical clock passes an attestation's `expires_at_utc`, the attestation transitions from `VERIFIED` to `EXPIRED`, the investor's `accreditation_status` is recomputed to the next-highest still-valid tier (or to `UNVERIFIED` if no valid attestation remains), and any subscription for that investor currently in `KYC_HOLD` or `COMPLIANCE_APPROVED` reverts to `KYC_HOLD` — a re-verification gate that forces the administrator to re-confirm accreditation before accepting the subscription.

### 3.4. Subscription Intake, Funding, and Acceptance

A subscription joins an investor to a share class. An `Investor`, `TransferAgent`, or `FundAdmin` creates a `Subscription` under a fund by supplying the `investor_id`, the `share_class_id`, the `commitment_amount_cents`, and the `funding_deadline_utc`. The subscription starts in `DRAFT` with `funded_amount_cents` at 0, `late_fees_accrued_cents` at 0, and no `effective_series_id`.

The submit transition (from `DRAFT` to `SUBMITTED`) is invoked by the investor or a transfer agent and enforces three checks: the investor's `kyc_status` must not be `REJECTED` (else `ERR_KYC_REJECTED`), the target share class must have `is_open_for_subscription` true (else `ERR_CLASS_CLOSED`), and `commitment_amount_cents` must be at least the share class's `min_initial_investment_cents` (else `ERR_BELOW_MIN_INVESTMENT`). As a side effect of submission, if the investor has no `KycCase` currently in `OPEN` or `IN_REVIEW`, a new one is created. If the investor's `kyc_status` is anything other than `APPROVED` at submission time — that is, if it is `NOT_STARTED`, `DOCUMENTS_PENDING`, or `UNDER_REVIEW` — the subscription auto-transitions from `SUBMITTED` to `KYC_HOLD`, where it waits for the KYC cascade described in §3.2 to move it to `COMPLIANCE_APPROVED` once the investor's latest `KycCase` reaches `APPROVED` and a verified accreditation attestation at the tier appropriate to the share class exists.

When the investor's `kyc_status` is already `APPROVED`, a `ComplianceOfficer` may instead transition the subscription directly from `SUBMITTED` to `COMPLIANCE_APPROVED`. That direct approval requires the investor's `kyc_status` to be `APPROVED`, the investor's latest `AccreditationAttestation` to be in `VERIFIED` status, and the latest `KycCase` to have both `sanctions_hit` and `pep_hit` false — otherwise the case belongs on the escalated path described in §3.2. A `ComplianceOfficer` may also reject a subscription from `COMPLIANCE_APPROVED` with a `rejection_reason`, which transitions it to `REJECTED` and triggers recomputation of the investor's `aggregate_unfunded_commitment_cents`.

Once a subscription reaches `COMPLIANCE_APPROVED`, a `TransferAgent` records wire receipts against it. Each funding receipt supplies an `amount_cents` and a `received_at_utc`. The amount must be positive — zero or negative amounts are rejected with `ERR_INVALID_AMOUNT`. The receipt must also arrive on or before the subscription's `funding_deadline_utc` as measured by the logical clock; a receipt after the deadline is rejected with `ERR_FUNDING_DEADLINE_PASSED`. Each accepted receipt adds `amount_cents` to the subscription's `funded_amount_cents` and recomputes the investor's `aggregate_unfunded_commitment_cents` (which sums, across all the investor's subscriptions in `ACCEPTED` or `FUNDING_PARTIAL` status, each subscription's commitment minus its funded amount). A receipt that leaves the total funded below the commitment transitions the subscription from `COMPLIANCE_APPROVED` to `FUNDING_PARTIAL` (or keeps it in `FUNDING_PARTIAL` when further partial receipts arrive); a receipt that brings the funded total equal to or above the remaining commitment transitions the subscription from `COMPLIANCE_APPROVED` (or from `FUNDING_PARTIAL`) directly to `FUNDED`, at which point `funded_amount_cents` equals `commitment_amount_cents`.

The final acceptance step transitions a `FUNDED` subscription to `ACCEPTED` and is performed by a `FundAdmin`. Acceptance enforces two guards. First, the fund must have an open NAV period — `Fund.current_nav_period_id` must not be null — else the acceptance is rejected with `ERR_NO_OPEN_NAV_PERIOD`. Second, the request must carry `expected_fund_version` matching the fund's current `version`, per the OCC rule in §2.8. Acceptance also enforces a referential rule on `effective_series_id`: when the request nominates a specific series, that series must be an `OPEN` series of the subscription's share class, else the acceptance is rejected with `ERR_SERIES_MISMATCH`. On success, acceptance creates a `CapitalAccount` keyed to (investor, share class, subscription) with `current_balance_cents` initialized to the funded amount, `high_water_mark_cents` initialized to the same starting balance, `accrued_performance_fee_cents` at 0, and `equalization_deposit_cents` at 0; creates a `SeriesLot` under the current open `Series` of the share class (minting a new series if none is open), with the lot's `series_id` set to that series, plus `shares`, `cost_basis_cents` equal to the funded amount, `current_value_cents` equal to the funded amount, and `equalization_credit_cents` at 0; sets the account's `locked_until_utc` from the funding timestamp plus the share class's `lockup_months` per the lockup rule below; adds the funded amount to `Fund.total_net_assets_cents`; and increments `Fund.version` by 1.

The lockup horizon is computed from the funding event that transitions the subscription to `FUNDED`, not from the first partial funding. When several partial fundings span a period, the lockup is measured from the final funding that completes the commitment. Calendar-month arithmetic applies with end-of-month clamping: a funding on January 31 with a one-month lockup yields a `locked_until_utc` of the last day of February. The same recomputation runs on any subsequent funding receipt that advances the funded total.

If the funding deadline passes with a subscription still in `FUNDING_PARTIAL`, a `FundAdmin` may cancel it. Cancellation transitions the subscription from `FUNDING_PARTIAL` to `CANCELLED`, accrues a late funding fee onto `late_fees_accrued_cents`, and recomputes the investor's `aggregate_unfunded_commitment_cents`. The late fee accrues at 5 basis points per day on the funded amount, computed as follows: count the integer number of days between the `funding_deadline_utc` and the cancellation date; for each day, multiply `funded_amount_cents` by the daily rate of 0.0005 and round the result half-up to integer cents; sum those per-day rounded amounts across all days late. The per-day rounding order is pinned — rounding each day then summing produces a different total than summing then rounding for odd funded amounts, and the former is the specified behavior.

### 3.5. Side Letters and MFN Elections

Side letters capture negotiated terms that deviate from a fund's base share class terms. A `FundAdmin` creates a `SideLetter` under a fund by supplying the `subscription_id`, the `terms_document_id`, and optionally a `supersedes_side_letter_id` pointing at a prior letter this one replaces. The new letter starts in `DRAFT`. When `supersedes_side_letter_id` is provided, it must reference an `EXECUTED` side letter owned by the same investor as the new letter's subscription; otherwise creation is rejected with `ERR_INVALID_SUPERSESSION`. For MFN sweep purposes, the letter denormalizes `investor_id` and `share_class_id` from its parent subscription. A new letter's `mfn_election_active` starts false and its `elected_clause_ids` starts empty.

Execution transitions the letter from `DRAFT` to `EXECUTED` and is performed by a `FundAdmin`. The parent subscription must be in `ACCEPTED` status, and the request must carry `expected_subscription_version` matching the subscription's current `version` per the OCC rule in §2.8. When the letter names a `supersedes_side_letter_id`, the prior letter transitions to `SUPERSEDED` as part of the same operation, and any MFN clauses elected on the prior letter are re-evaluated against the new letter. Execution increments `Subscription.version` by 1.

The MFN clause library is maintained per fund. A `FundAdmin` publishes `MfnClause` records with a `clause_tag` (one of `FEE_REBATE`, `LIQUIDITY`, `INFORMATION_RIGHTS`, `CAPACITY_RIGHTS`, `CO_INVEST`), the `clause_text`, a `capacity_threshold_cents` (the minimum commitment at which the clause becomes electable, where 0 means electable by all), a `fee_rebate_bps` (used only for `FEE_REBATE` clauses, else 0), and a `notice_days_reduction` (used only for `LIQUIDITY` clauses, else 0). Clauses start in `ACTIVE` status; a `FundAdmin` may retire one, transitioning it to `RETIRED`, after which it can no longer be newly elected.

Once a side letter is `EXECUTED`, the investor elects MFN clauses onto it one at a time by naming a `mfn_clause_id`. Election is guarded by two checks: the named clause must still be in `ACTIVE` status (a retired clause is rejected with `ERR_CLAUSE_RETIRED`), and the subscription's `commitment_amount_cents` must be at least the clause's `capacity_threshold_cents` (otherwise the election is rejected with `ERR_BELOW_CAPACITY_THRESHOLD`). The first election flips `mfn_election_active` to true; subsequent elections amend the existing election by appending to `elected_clause_ids`. Each election recomputes the effective fee on the investor's capital account per the MFN fee rule below. A `FundAdmin` may terminate an executed letter, transitioning it to `TERMINATED`; termination clears `elected_clause_ids` and reverts the capital account's fee schedule to the base share class terms.

The effective fee under an elected MFN `FEE_REBATE` clause set is computed as follows. The base fee in basis points is the sum of the share class's `management_fee_bps` and `performance_fee_bps`. Eligible rebate clauses are those whose `capacity_threshold_cents` is at most the subscription's `commitment_amount_cents`. The total rebate is the sum of the `fee_rebate_bps` across eligible clauses, capped at one-half of the base fee (that is, the rebate may not exceed 50% of the base). The effective fee in basis points is the base fee minus the capped total rebate. This recomputation runs when a letter is executed with an elected rebate clause, when a new clause is elected, and when a letter is terminated.

### 3.6. NAV Periods, Series Accounting, and Equalization

A `FundAdmin` opens a `NavPeriod` under a fund by supplying a `period_end_utc`. Only one period may be `OPEN` at a time per fund. Each period receives a monotonically increasing `period_index` starting at 1, plus a `period_start_utc` (inclusive) and `period_end_utc` (exclusive). Opening a period sets the fund's `current_nav_period_id` to the new period's id. When a subscription is accepted during a period, the system mints a `Series` under the relevant share class if none is currently open: the series carries the `share_class_id`, the `nav_period_id` of its issuance period, a `series_index` monotonically increasing within the share class starting at 1, and an `opening_nav_per_share_cents` equal to the NAV per share at issuance. The series starts in `OPEN` with `equalization_factor_bps` at 0.

Finalizing a NAV period is a `FundAdmin` action guarded by OCC against the fund. The request must supply the period's `gross_return_bps` (a fund-level gross return in basis points that may be negative) and an `expected_fund_version` matching the fund's current `version`. Finalization transitions the period from `OPEN` to `NAV_FINALIZED`, applies the gross return to each capital account, accrues the management fee, and — for each `OPEN` series of each share class of the fund — computes the series equalization factor and transitions the series to `FINALIZED`, locking the factor. Finalization increments `Fund.version` by 1.

The series equalization factor is computed per series from that series's `opening_nav_per_share_cents` (call it the opening NAV), the closing NAV per share for the period, the share class's `hurdle_rate_bps`, the share class's `performance_fee_bps`, and the number of days in the period. The gross return is the excess of closing over opening, divided by the opening. The hurdle return is the hurdle rate (expressed as a fraction, so `hurdle_rate_bps` divided by 10,000) multiplied by the fraction of the year the period spans (days in the period divided by 365). If the gross return is at or below the hurdle return — including any period where the closing NAV is below the opening NAV — the equalization factor is 0. Otherwise, the excess return is the gross return minus the hurdle return; the incentive is the excess return multiplied by the performance fee rate (that is, `performance_fee_bps` divided by 10,000); and the `equalization_factor_bps` is that incentive re-expressed as basis points of the opening NAV, rounded half-up to an integer exactly once at the very end — intermediate values carry full precision and are never rounded early. A provisional variant of this factor may be computed on intra-period estimates (for example, a mid-month flash NAV) for what-if projections, but only the final variant — computed once at finalize time against actual closing NAV — is persisted to the series and locked.

Closing a NAV period transitions it from `NAV_FINALIZED` to `CLOSED` and is a `FundAdmin` action. Closure requires that every `RedemptionRequest` in `APPROVED` or `PARTIALLY_APPROVED` status for the period has been resolved to `SETTLED`. Closure crystallizes the performance fee against the high-water mark for each capital account, generates one `InvestorStatement` per active capital account, auto-opens a new `NavPeriod` and updates the fund's `current_nav_period_id` to it, and increments `Fund.version` by 1.

Series themselves roll forward once they are no longer needed for equalization. When a later NAV period closes and a series in `FINALIZED` has `equalization_factor_bps` equal to 0, the series transitions from `FINALIZED` to `ROLLED`; every `OUTSTANDING` `SeriesLot` under that series is rolled into the share class's lead series (the one with `series_index` 1), each rolled lot's `status` becomes `ROLLED`, and a new lot is created under the lead series.

### 3.7. Redemption Requests: Notice, Lockup, Gates, and Settlement

An investor (or `TransferAgent` on their behalf) submits a `RedemptionRequest` under a fund by naming the `capital_account_id` to redeem from, the `requested_amount_cents` (or alternatively `requested_shares`; the two are mutually exclusive), and the `requested_effective_period_id`. The system stamps `notice_given_at_utc` from the logical clock at receipt. The requested amount must not exceed the capital account's `current_balance_cents`, else the request is rejected with `ERR_INSUFFICIENT_BALANCE`. New requests start in `PENDING` with `gate_applied_pct` at 0 and `settled_amount_cents` at 0.

A `FundAdmin` approves a request from `PENDING`. Approval enforces, in priority order after the global checks: the capital account's `locked_until_utc` must be at or before the current logical time (otherwise `ERR_LOCKUP_NOT_EXPIRED`); the notice given must satisfy the notice requirement (otherwise `ERR_INSUFFICIENT_NOTICE`); the fund's `suspension_status` must be `NOT_SUSPENDED` (otherwise `ERR_REDEMPTIONS_SUSPENDED`); and the share class's `is_open_for_redemption` must be true. Approval transitions the request to `APPROVED` and sets the capital account's `status` to `REDEMPTION_PENDING`. A `FundAdmin` may instead reject a pending request with a `rejection_reason`, transitioning it to `REJECTED`.

The notice requirement is measured in integer days. The required notice is the share class's `notice_days` minus the sum of `notice_days_reduction` across the investor's applicable elected `LIQUIDITY` clauses, floored at 0 — when the sum of reductions is at least the base `notice_days`, the required notice is 0 and any notice satisfies it. The actual notice is the integer number of days between `notice_given_at_utc` and the requested effective period's `period_end_utc`. The boundary operator is inclusive: an actual notice exactly equal to the required notice is valid.

At period close, if the sum of approved redemption amounts for the fund exceeds the fund-level gate — the product of `gate_threshold_pct` and `Fund.total_net_assets_cents` — the gate binds and each approved request transitions from `APPROVED` to `PARTIALLY_APPROVED`. When the gate binds, the request's `effective_period_id` may be pushed later than the originally nominated `requested_effective_period_id`, since only a portion settles in the requested period and the remainder rolls forward. The gate pool in cents is the floor of the threshold times the net assets. When the total approved amount is at or below the pool, every request settles in full with `gate_applied_pct` at 0 and `settled_amount_cents` equal to `requested_amount_cents`. When the total exceeds the pool, each request's `gate_applied_pct` is one minus the ratio of the pool to the total approved, held as a six-decimal fixed-point value; each request's preliminary settlement is the floor of (its requested amount times the pool, divided by the total approved); and the leftover cents in the pool are then distributed one cent at a time to the requests with the largest remainder, where the remainder for a request is its requested amount times the pool minus its preliminary settlement times the total approved. Ties in the remainder distribution are broken by `requested_amount_cents` descending, then `notice_given_at_utc` ascending, then the capital account's `created_at` ascending. The deferred remainder of each gated request auto-creates a new `PENDING` redemption request for the next period, preserving the original notice date.

Settlement itself happens as part of NAV period close. For a request that was `APPROVED` without a gate binding, `settled_amount_cents` is the full `requested_amount_cents`; the capital account's `current_balance_cents` is reduced by that amount, the fund's `total_net_assets_cents` is reduced by the same amount, and the investor statement for the period records the outflow under `distributions_cents`. For a request that was `PARTIALLY_APPROVED`, the per-request settlement follows the `gate_applied_pct` computation above, and the deferred portion spawns a fresh `PENDING` request for the next period. Settlement transitions the request from either `APPROVED` or `PARTIALLY_APPROVED` to `SETTLED`.

An investor may cancel a pending request before the notice deadline — that is, while the current logical time is still earlier than the requested effective period's `period_end_utc` minus the share class's `notice_days`. Cancellation transitions the request from `PENDING` to `CANCELLED`. After that cutoff the request is locked in.

### 3.8. Investor Statements

Each NAV period close generates one `InvestorStatement` per active capital account. The statement records the `capital_account_id`, the `nav_period_id`, the `opening_balance_cents` at period start, the `closing_balance_cents` at period end, the `contributions_cents` (new contributions received in the period, starting at 0), the `distributions_cents` (redemptions and distributions paid in the period, starting at 0), the `management_fee_cents` charged, the `performance_fee_cents` crystallized, and starts in `DRAFT`. Statements transition to `FINALIZED` as part of period close. A `TransferAgent` or `FundAdmin` marks a statement delivered, which stamps `delivered_at_utc` from the logical clock and transitions the statement to `DELIVERED`.

## 4. Endpoint Definitions

Operations that create new resources (a fund, a share class, a NAV period, an investor, a KYC case, an attestation, a subscription, a funding receipt, a side letter, an MFN clause, a redemption request) return a `201 Created` status code. Operations that modify an existing resource (submit, approve, reject, accept, cancel, execute, elect-mfn, terminate, retire, finalize, close, deliver, suspend, resume) return a `200 OK` status code. All list and single-resource fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical server clock | FundAdmin |
| POST | `/funds` | Create a new hedge fund | FundAdmin |
| GET | `/funds` | List funds (paginated) | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/funds/{id}` | Get a single fund | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/funds/{id}/suspend-redemptions` | Suspend all redemptions for the fund | FundAdmin |
| POST | `/funds/{id}/resume-redemptions` | Resume redemptions | FundAdmin |
| POST | `/funds/{id}/share-classes` | Create a share class under a fund | FundAdmin |
| GET | `/funds/{id}/share-classes` | List share classes of a fund | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/funds/{id}/share-classes/{id}` | Get a single share class | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/funds/{id}/share-classes/{id}/close-subscription` | Close a class to new subscriptions | FundAdmin |
| POST | `/funds/{id}/share-classes/{id}/close-redemption` | Close a class to redemptions | FundAdmin |
| POST | `/funds/{id}/nav-periods` | Open a new NAV period | FundAdmin |
| GET | `/funds/{id}/nav-periods` | List NAV periods of a fund | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/funds/{id}/nav-periods/{id}` | Get a single NAV period | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| POST | `/funds/{id}/nav-periods/{id}/finalize` | Finalize NAV for the period (OCC-guarded) | FundAdmin |
| POST | `/funds/{id}/nav-periods/{id}/close` | Close the period: settle redemptions, crystallize fees, generate statements, open next period | FundAdmin |
| GET | `/funds/{id}/share-classes/{id}/series` | List series under a share class | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/funds/{id}/share-classes/{id}/series/{id}` | Get a single series | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| POST | `/investors` | Register a new investor | FundAdmin, TransferAgent |
| GET | `/investors` | List investors | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/investors/{id}` | Get a single investor | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/investors/{id}/kyc-cases` | Open a new KYC case | ComplianceOfficer, FundAdmin |
| GET | `/investors/{id}/kyc-cases` | List KYC cases for investor | FundAdmin, ComplianceOfficer |
| GET | `/investors/{id}/kyc-cases/{id}` | Get a single KYC case | FundAdmin, ComplianceOfficer, Investor |
| POST | `/investors/{id}/kyc-cases/{id}/documents` | Submit a KYC document | Investor, TransferAgent |
| POST | `/investors/{id}/kyc-cases/{id}/approve` | Approve KYC case | ComplianceOfficer |
| POST | `/investors/{id}/kyc-cases/{id}/reject` | Reject KYC case | ComplianceOfficer |
| POST | `/investors/{id}/accreditations` | Submit an accreditation attestation | Investor, TransferAgent |
| GET | `/investors/{id}/accreditations` | List attestations for investor | FundAdmin, ComplianceOfficer, Investor |
| GET | `/investors/{id}/accreditations/{id}` | Get a single attestation | FundAdmin, ComplianceOfficer, Investor |
| POST | `/investors/{id}/accreditations/{id}/verify` | Verify attestation | ComplianceOfficer |
| POST | `/investors/{id}/accreditations/{id}/reject` | Reject attestation | ComplianceOfficer |
| POST | `/funds/{id}/subscriptions` | Create a new subscription | Investor, TransferAgent, FundAdmin |
| GET | `/funds/{id}/subscriptions` | List subscriptions for a fund | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/funds/{id}/subscriptions/{id}` | Get a single subscription | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/funds/{id}/subscriptions/{id}/submit` | Submit subscription for review | Investor, TransferAgent |
| POST | `/funds/{id}/subscriptions/{id}/compliance-approve` | Compliance approves subscription | ComplianceOfficer |
| POST | `/funds/{id}/subscriptions/{id}/compliance-reject` | Compliance rejects subscription | ComplianceOfficer |
| POST | `/funds/{id}/subscriptions/{id}/fundings` | Record a funding wire receipt | TransferAgent |
| POST | `/funds/{id}/subscriptions/{id}/accept` | Accept funded subscription (OCC-guarded) | FundAdmin |
| POST | `/funds/{id}/subscriptions/{id}/cancel` | Cancel subscription after deadline miss | FundAdmin |
| POST | `/funds/{id}/side-letters` | Create a new side letter | FundAdmin |
| GET | `/funds/{id}/side-letters` | List side letters of a fund | FundAdmin, ComplianceOfficer, PortfolioManager |
| GET | `/funds/{id}/side-letters/{id}` | Get a single side letter | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| POST | `/funds/{id}/side-letters/{id}/execute` | Execute side letter (OCC-guarded) | FundAdmin |
| POST | `/funds/{id}/side-letters/{id}/elect-mfn` | Investor elects an MFN clause | Investor |
| POST | `/funds/{id}/side-letters/{id}/terminate` | Terminate side letter | FundAdmin |
| POST | `/funds/{id}/mfn-clauses` | Publish a new MFN clause | FundAdmin |
| GET | `/funds/{id}/mfn-clauses` | List MFN clauses of a fund | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| GET | `/funds/{id}/mfn-clauses/{id}` | Get a single MFN clause | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| POST | `/funds/{id}/mfn-clauses/{id}/retire` | Retire an MFN clause | FundAdmin |
| GET | `/investors/{id}/capital-accounts` | List capital accounts of an investor | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/investors/{id}/capital-accounts/{id}` | Get a single capital account | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/investors/{id}/capital-accounts/{id}/lots` | List series lots of a capital account | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/funds/{id}/redemptions` | Submit a redemption request | Investor, TransferAgent |
| GET | `/funds/{id}/redemptions` | List redemption requests for a fund | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/funds/{id}/redemptions/{id}` | Get a single redemption request | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/funds/{id}/redemptions/{id}/approve` | Approve redemption request | FundAdmin |
| POST | `/funds/{id}/redemptions/{id}/reject` | Reject redemption request | FundAdmin |
| POST | `/funds/{id}/redemptions/{id}/cancel` | Investor cancels redemption request | Investor |
| GET | `/investors/{id}/capital-accounts/{id}/statements` | List statements for a capital account | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/investors/{id}/capital-accounts/{id}/statements/{id}` | Get a single statement | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| POST | `/investors/{id}/capital-accounts/{id}/statements/{id}/deliver` | Mark statement delivered | TransferAgent, FundAdmin |
| GET | `/share-classes/{id}` | Flat fetch of a share class by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/nav-periods/{id}` | Flat fetch of a NAV period by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/series/{id}` | Flat fetch of a series by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/kyc-cases/{id}` | Flat fetch of a KYC case by id | FundAdmin, ComplianceOfficer, Investor |
| GET | `/accreditations/{id}` | Flat fetch of an accreditation attestation by id | FundAdmin, ComplianceOfficer, Investor |
| GET | `/subscriptions/{id}` | Flat fetch of a subscription by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/side-letters/{id}` | Flat fetch of a side letter by id | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| GET | `/mfn-clauses/{id}` | Flat fetch of an MFN clause by id | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| GET | `/capital-accounts/{id}` | Flat fetch of a capital account by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/series-lots/{id}` | Flat fetch of a series lot by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/redemptions/{id}` | Flat fetch of a redemption request by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/statements/{id}` | Flat fetch of an investor statement by id | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/share-classes` | Filtered list of share classes | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |
| GET | `/nav-periods` | Filtered list of NAV periods | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/series` | Filtered list of series | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/kyc-cases` | Filtered list of KYC cases | FundAdmin, ComplianceOfficer |
| GET | `/accreditations` | Filtered list of accreditation attestations | FundAdmin, ComplianceOfficer, Investor |
| GET | `/subscriptions` | Filtered list of subscriptions | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/side-letters` | Filtered list of side letters | FundAdmin, ComplianceOfficer, PortfolioManager |
| GET | `/mfn-clauses` | Filtered list of MFN clauses | FundAdmin, ComplianceOfficer, PortfolioManager, Investor |
| GET | `/capital-accounts` | Filtered list of capital accounts | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/series-lots` | Filtered list of series lots | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/redemptions` | Filtered list of redemption requests | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager |
| GET | `/statements` | Filtered list of investor statements | FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_KYC_REJECTED` | 422 |
| `ERR_SANCTIONS_HIT` | 422 |
| `ERR_INCOMPLETE_DOCUMENTS` | 422 |
| `ERR_STALE_ATTESTATION` | 422 |
| `ERR_CLASS_CLOSED` | 422 |
| `ERR_BELOW_MIN_INVESTMENT` | 422 |
| `ERR_FUNDING_DEADLINE_PASSED` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_NO_OPEN_NAV_PERIOD` | 422 |
| `ERR_SERIES_MISMATCH` | 422 |
| `ERR_LOCKUP_NOT_EXPIRED` | 422 |
| `ERR_INSUFFICIENT_NOTICE` | 422 |
| `ERR_REDEMPTIONS_SUSPENDED` | 422 |
| `ERR_INSUFFICIENT_BALANCE` | 422 |
| `ERR_INVALID_SUPERSESSION` | 422 |
| `ERR_CLAUSE_RETIRED` | 422 |
| `ERR_BELOW_CAPACITY_THRESHOLD` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
