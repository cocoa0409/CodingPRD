# Donor-Advised Fund Administration API — Product Requirements Document

## 1. Introduction

A donor-advised fund (DAF) program — modelled here on the Fidelity Charitable style of giving — lets a donor make an irrevocable charitable contribution today, take the associated tax deduction immediately, and then recommend grants out of the fund to qualified public charities over time while the contributed assets are invested. This API backs the operational core of such a program: it records sponsor configuration, takes in cash, securities, and crypto gifts and values them at fair market value, vets recipient organizations for 501(c)(3) eligibility, allocates uninvested cash across investment pools, lets donors recommend grants that a separate grant officer approves and pays, accrues quarterly administration fees, enforces minimum-grant and inactivity policy, and finally winds an account down through a succession or legacy plan when the donor's giving is complete.

The defining tension of the domain is that money entering the fund is **irrevocable** — once a contribution settles, the donor no longer owns it and cannot get it back — while everything downstream (which charity, how much, when) remains a *recommendation* that the sponsor is legally obligated to vet. The system therefore reads as a compliance-and-audit ledger first and a portfolio system second: every cash movement is double-checked against a running ledger, charity eligibility is re-verified at each gate of the grant lifecycle, and duties are segregated so that the person who recommends a grant can never be the person who approves or pays it. This document specifies the entities, state machines, valuation and allocation calculations, validation order, endpoints, and error contract that together make those guarantees auditable.

The intended readers are the engineers building the service. Section 2 fixes the cross-cutting contracts — response envelope, pagination, identity, precision, concurrency, and the ledger invariants — that every endpoint must honour. Section 3 narrates the business workflows in domain terms. Sections 4 and 5 give the endpoint and error-code summary tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the acting user, and `X-User-Role`, naming the role under which the call is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). If the headers are present but the named role is not permitted to invoke the requested endpoint (per the authorization column in Section 4), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

There are exactly five roles, spelled as follows:

- **`SponsorAdmin`** — the sponsoring program's operator. Creates sponsors, investment pools, NAV periods, and donor accounts; advances the fiscal quarter; and drives account wind-down and succession execution.
- **`ComplianceOfficer`** — vets recipient charities for grant eligibility, recording approve, watchlist, and revoke decisions.
- **`ContributionAdmin`** — settles and values irrevocable contributions and mints the IRS substantiation receipts.
- **`DonorAdvisor`** — the account owner. Records contributions, recommends grants, rebalances investment pools, and sets up succession plans.
- **`GrantOfficer`** — approves, schedules, rejects, and pays grants. By segregation of duties, a grant officer may never act on a grant they themselves recommended.

The identity semantics differ by ownership. The `DonorAdvisor` role is the only owner-scoped role: when `X-User-Role` is `DonorAdvisor`, `X-User-ID` is matched against a donor account's `primary_advisor_user_id` to decide ownership. Concretely, for owner-scoped actions — cancelling a grant, executing or cancelling a rebalance order, and creating or confirming a succession plan — the acting `DonorAdvisor`'s `X-User-ID` must equal the `primary_advisor_user_id` of the account the action targets; otherwise the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403). Although `DonorAdvisor` is owner-scoped through this foreign-key comparison rather than through a persisted DonorAdvisor entity, the value is still an opaque operator identifier: the server stores it where a transition writes it (for example as `recommended_by_user_id` and `approved_by_user_id` on a grant) but does not treat it as the `id` of any persisted entity.

The other four roles — `SponsorAdmin`, `ComplianceOfficer`, `ContributionAdmin`, and `GrantOfficer` — are **opaque** operator roles. When `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for instance, the `recommended_by_user_id` and `approved_by_user_id` fields a grant transition writes are exactly such recorded operator ids) but never compares it against an entity's `id` for ownership. The one place these operator ids carry behavioural weight is segregation of duties on grants, described in Section 3.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested `limit` is clamped into that range. `offset` defaults to 0 and represents the number of leading records to skip. Every list endpoint returns results sorted by `created_at` in ascending order (oldest first) before pagination is applied. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when more records remain beyond the current page).

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` that is a UUID with no type prefix; clients never supply it. Most resources additionally carry `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at 1 on creation and increments by one on every mutation of that resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every state change or field mutation.

Two resources are append-only audit records and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`, because they are written once and never mutated: the `SubstantiationReceipt` (the IRS letter minted when a contribution settles) and the `LedgerEntry` (a single posted cash-balance movement). All other resources — `Sponsor`, `InvestmentPool`, `NavPeriod`, `Charity`, `DonorAccount`, `Contribution`, `PoolAllocation`, `GrantRecommendation`, `SuccessionPlan`, and `RebalanceOrder` — carry the full `id`/`created_at`/`updated_at`/`version` set.

### 2.5. Nested Reference Resolution and Existence Checks

The topology is flat: resources live as peer collections and reference one another through foreign-key fields in request bodies rather than through nested URL paths. Whenever an endpoint names a resource in its URL path, that path identifier is resolved first; whenever a request body names a foreign-key resource (for example a `donor_account_id`, `charity_id`, `investment_pool_id`, `source_pool_id`, or `target_pool_id`), those references are resolved after the path, in left-to-right order as they appear. Any path-referenced or body-referenced resource that does not exist causes `ERR_NOT_FOUND` (HTTP 404). A request for a substantiation receipt id that does not exist returns `ERR_RECEIPT_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored as integer cents, and all unit quantities as scaled integers — securities and crypto quantities as `quantity_milli` (the real quantity multiplied by 1000), and pool holdings as `units_micro` (real units multiplied by 1,000,000). Calculations that must reduce to whole cents use one of two rounding disciplines, and the choice is part of the contract for each calculation, never interchangeable: **round half up** (round to the nearest cent, with exact halves going up) is used for securities valuation, for valuing a pool allocation, and for the per-allocation admin fee; **floor** (round down toward zero) is used for crypto valuation and for the number of pool units bought; and **ceiling** (round up) is used for the number of pool units surrendered on a redemption. Where a calculation sums several rounded sub-results, the rounding happens at the step named in Section 3 and is not deferred to the total.

### 2.7. The Cash Ledger and Derived-Balance Reconciliation

Every donor account maintains a single uninvested-cash figure, `cash_balance_cents`, and a complete audit trail of the movements that produced it. Each posted movement is a `LedgerEntry` recording the affected account (`donor_account_id`), an `entry_type` drawn from `CONTRIBUTION_SETTLED`, `POOL_BUY`, `POOL_REDEEM`, `GRANT_PAID`, `ADMIN_FEE`, and `LEGACY_DISBURSEMENT`, a `signed_amount_cents` giving the cash-balance delta the entry applied (positive is a credit, negative is a debit), the source entity type in `ref_entity` (such as `Contribution`, `GrantRecommendation`, or `RebalanceOrder`) and its id in `ref_id`, and the `quarter_index` of the sponsor fiscal clock when the entry was posted. The ledger is append-only: entries are never edited or deleted.

Three account figures are **derived** and must be recomputed whenever any input to them changes — `invested_value_cents`, `committed_grants_cents`, and `grantable_balance_cents`. `invested_value_cents` is the sum, over every `ACTIVE` pool allocation the account holds, of that allocation's value (see Section 3 for how an allocation is valued from its `units_micro` and its pool's `nav_per_unit_cents`). `committed_grants_cents` is the sum of `amount_cents` over every grant recommendation on the account whose status is `SUBMITTED`, `APPROVED`, or `SCHEDULED`. `admin_fee_accrued_cents` accumulates unpaid admin fees swept at quarter close. The settled grantable balance, `grantable_balance_cents`, equals `cash_balance_cents` plus `invested_value_cents` minus `committed_grants_cents` minus `admin_fee_accrued_cents`. Whenever an operation changes cash, investments, commitments, or accrued fees, the affected account's derived figures are recomputed in that same operation so the stored values always reconcile with the ledger.

### 2.8. Hierarchical State Consistency and Cascades

State changes that touch more than one resource must apply every effect atomically. When a charity is revoked, every grant recommendation still in `SCHEDULED` status that references that charity is automatically driven to `CANCELLED`, and each affected account's `committed_grants_cents` and `grantable_balance_cents` are recomputed to release the freed commitment. When a grant is paid, the account's pool allocations are redeemed, the cash balance is debited, ledger entries are appended, and the derived balances are recomputed — all as one operation. Any resource a cascade mutates has its `updated_at` refreshed and its `version` incremented as part of the same operation, exactly as a direct mutation would. The specific cascades and their ordering live in Section 3 with the workflows that trigger them.

### 2.9. Optimistic Concurrency on Grant Submission

Submitting a new grant recommendation is guarded by optimistic concurrency control on the target donor account. A grant-submission request must include `expected_account_version`, carrying the `version` of the donor account that the client last observed. The server compares it against the account's current `version`: if another writer has advanced the account's version since the client last read it — for instance by submitting another grant that raised `committed_grants_cents` and so consumed grantable balance — the submitting client's view of the grantable balance is stale, and the submission is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) rather than silently over-committing the fund. When `expected_account_version` matches the account's current `version`, the submission proceeds, the grant is recorded, and the account's `version` is incremented by one as part of recording the new commitment. No other endpoint takes a version field; grant submission is the only optimistic-concurrency-guarded write.

### 2.10. The Sponsor Fiscal Clock

Time in this system is quantized into sponsor fiscal quarters, tracked by `current_quarter_index` on the sponsor, which begins at 0 when the sponsor is created. There is no wall-clock dependence: quarters advance only when the sponsor's quarter is closed, which increments `current_quarter_index` by one and runs the per-account fee accrual and inactivity evaluation described in Section 3. Quarter indices appearing on other resources — a grant's `paid_quarter_index`, an account's `last_grant_paid_quarter`, a receipt's `issued_quarter_index`, a ledger entry's `quarter_index`, and a NAV period's or recurring grant's window bounds — are all expressed against this same fiscal clock.

## 3. Business Logic & Workflows

### 3.1. Sponsor Setup, Investment Pools, and NAV Pricing Windows

A `SponsorAdmin` begins by creating a `Sponsor`, which represents the DAF program itself. The create call supplies the program `name` and the sponsor's own IRS `ein`, and may optionally set policy parameters: `minimum_grant_cents` (the smallest single grant the program will permit, defaulting to 5000 cents, i.e. fifty dollars), `inactivity_quarters` (how many quarters an account may go without a paid grant before it becomes inactivity-eligible, defaulting to 8), and `admin_fee_bps_default` (the default annual administration-fee rate in basis points, defaulting to 50). The sponsor's fiscal clock, `current_quarter_index`, is initialized to 0 at creation.

The same operator creates `InvestmentPool` resources, each tied to a sponsor by `sponsor_id` and described by a `name`, a `risk_tier` that must be one of `CONSERVATIVE`, `BALANCED`, or `GROWTH`, a starting net-asset-value `nav_per_unit_cents`, and a pool-specific annual fee rate `fee_bps`. A pool's `nav_per_unit_cents` must be greater than zero; a non-positive NAV is rejected at creation with `ERR_POOL_NAV_INVALID`. A pool starts with `status` of `OPEN`. A pool may later be closed, transitioning its `status` to `CLOSED`; a `CLOSED` pool accepts no new buy allocations, though existing allocations remain and can still be redeemed. Pools can be listed and filtered by their `sponsor_id` and `status` to recover all pools under a sponsor.

Pricing history for a pool is captured by `NavPeriod` records, each naming its pool through `investment_pool_id`, a `nav_per_unit_cents` effective during the window, and the window bounds `from_quarter` and `to_quarter`. A NAV period window is **half-open**: it covers quarters from `from_quarter` inclusive up to but not including `to_quarter`. A new NAV period begins with `status` of `ACTIVE` (the alternative being `SUPERSEDED`). Two windows on the same pool collide only when they genuinely overlap: a new window running from `from_quarter` (call it the new start) up to its `to_quarter` (the new end) overlaps an existing `ACTIVE` period only if the existing start is strictly less than the new end **and** the new start is strictly less than the existing end. Because the interval is half-open, two windows that merely touch at a boundary — where one window's `to_quarter` equals the other's `from_quarter` — do **not** collide. When a genuine overlap with any `ACTIVE` NAV period on the same pool is detected, the create is rejected with `ERR_NAV_PERIOD_OVERLAP`. NAV periods can be listed and filtered by `investment_pool_id` and `status`.

### 3.2. Recipient Charities and the Vetting Lifecycle

Before any money can leave the fund, the recipient organization must be vetted. A `Charity` is registered — by a `ComplianceOfficer` or a `SponsorAdmin` — under a sponsor via `sponsor_id`, with a `legal_name`, the recipient's `ein`, an `ntee_code` (its National Taxonomy of Exempt Entities classification), and an optional `is_private_foundation` flag that defaults to false. A charity's `ein` must be unique among the non-`REVOKED` charities under the same sponsor; registering a charity whose EIN is already held by a non-revoked charity under that sponsor is rejected with `ERR_DUPLICATE_CHARITY_EIN`. A newly registered charity starts in `status` `PENDING_VETTING`. Charities can be listed and filtered by `sponsor_id`, `status`, and `ein`.

Only a `ComplianceOfficer` records a vetting decision. A vetting call carries a `decision` and an optional `vetting_note`, and the recorded note is stored on the charity's `vetting_note` field. The decision drives the state machine across four states — `PENDING_VETTING`, `VETTED`, `WATCHLISTED`, and `REVOKED`:

- An **APPROVE** decision moves a charity from `PENDING_VETTING` to `VETTED`, or from `WATCHLISTED` back to `VETTED`. Approval is only permitted when the charity is not a private foundation: if `is_private_foundation` is true, approval is rejected with `ERR_INELIGIBLE_GRANTEE`, because private foundations are not eligible DAF grantees. On a successful approval the `status` becomes `VETTED` and the `vetting_note` is set from the request.
- A **WATCHLIST** decision moves a charity from `PENDING_VETTING` to `WATCHLISTED`, or from `VETTED` to `WATCHLISTED`, setting `status` to `WATCHLISTED` and recording the `vetting_note`. Watchlisting a previously `VETTED` charity has a downstream consequence: because grant payout re-checks that the charity is `VETTED` at pay time, a charity that has been moved to `WATCHLISTED` can no longer have grants paid out to it until it is approved again.
- A **REVOKE** decision moves a charity from `VETTED` to `REVOKED`, or from `WATCHLISTED` to `REVOKED`, setting `status` to `REVOKED`. Revocation cascades: every grant recommendation in `SCHEDULED` status that references this charity is transitioned to `CANCELLED`, and on each affected account the committed amount is released by recomputing `committed_grants_cents` and then `grantable_balance_cents`.

`REVOKED` is terminal — no decision moves a charity out of it. Recording a decision that would re-enter the charity's current state (for example, approving a charity that is already `VETTED`) is rejected with `ERR_INVALID_STATE`.

### 3.3. Irrevocable Contributions and Fair-Market Valuation

A contribution is the act of giving an asset to the fund. A `DonorAdvisor` or a `ContributionAdmin` records a `Contribution` against an account via `donor_account_id`, naming the `asset_type` as one of `CASH`, `SECURITIES`, or `CRYPTO`, and supplying the pricing inputs appropriate to that type. For a cash gift, `cash_amount_cents` carries the amount and must be positive. For a securities or crypto gift, `ticker` names the instrument and `quantity_milli` carries the quantity multiplied by 1000. Securities pricing supplies the gift-date `high_price_cents` and `low_price_cents` per share, and for thinly-traded names a `closing_price_cents` per share together with the `thinly_traded` flag (default false). Crypto pricing supplies `spot_price_cents`, the spot price per whole unit at gift time. A new contribution starts with `status` `PENDING` and a null `fair_market_value_cents`. Contributions can be listed and filtered by `donor_account_id`, `status`, and `asset_type`.

Recording the gift does not yet move money; settlement does. Only a `ContributionAdmin` settles a contribution, and settlement is irreversible. Before settling, three preconditions are checked: the target account must be in `status` `ACTIVE` — settling against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`; the pricing inputs required by the asset type must all be present — a cash gift needs `cash_amount_cents`, a securities gift needs `high_price_cents` and `low_price_cents` (or `closing_price_cents` when `thinly_traded` is true), and a crypto gift needs `spot_price_cents`; a missing required input is rejected with `ERR_VALUATION_INPUT_MISSING`; and for a securities gift the `quantity_milli` must represent whole shares, meaning it must be evenly divisible by 1000 — a `quantity_milli` not divisible by 1000 is rejected with `ERR_VALUATION_QUANTITY_INVALID`.

When those checks pass, the contribution's fair market value is computed and stamped into `fair_market_value_cents`, where it becomes irrevocable. The valuation depends on the asset type:

- For a **cash** gift, the fair market value is simply `cash_amount_cents`.
- For a **securities** gift, first derive the share count by dividing `quantity_milli` by 1000. The standard valuation (the **MEAN_HIGH_LOW** variant, used when `thinly_traded` is false) multiplies the share count by the average of the gift-date high and low — that is, by the sum of `high_price_cents` and `low_price_cents` divided by 2 — and rounds the result half up to whole cents. For a thinly-traded name (the **CLOSING_PRICE** variant, used when `thinly_traded` is true), the share count is instead multiplied by `closing_price_cents` and rounded half up to whole cents. The two variants can differ for the same shares whenever the high and low straddle the close.
- For a **crypto** gift, derive the quantity by dividing `quantity_milli` by 1000, multiply it by `spot_price_cents`, and take the floor — crypto valuations are rounded down to whole cents.

Settlement then cascades through the ledger. The fair market value is added to the account's `cash_balance_cents`. A `LedgerEntry` of `entry_type` `CONTRIBUTION_SETTLED` is appended with `signed_amount_cents` equal to the positive fair market value, and the account's `grantable_balance_cents` is recomputed. Finally a `SubstantiationReceipt` — the IRS letter — is minted for the donor: it records the `contribution_id` and `donor_account_id`, a sponsor-minted sequential `receipt_number`, a `deductible_value_cents` frozen equal to the contribution's `fair_market_value_cents` at settlement, a human-readable `asset_description` for the IRS letter, and the `issued_quarter_index` taken from the sponsor's current fiscal quarter at issuance. The contribution's `status` becomes `SETTLED`, which is terminal — attempting to settle an already-settled contribution is rejected with `ERR_INVALID_STATE`. A `ContributionAdmin` may instead reject a `PENDING` contribution, moving its `status` to `REJECTED` with no valuation, no ledger entry, and no receipt; `REJECTED` is likewise terminal.

### 3.4. Opening Accounts, Investing Cash, and Rebalancing Pools

A `DonorAccount` is the fund itself. It is opened — by a `SponsorAdmin` or a `DonorAdvisor` — under a sponsor via `sponsor_id`, with a donor-chosen `account_name` and the `primary_advisor_user_id` naming the `DonorAdvisor` who owns it. A new account starts in `status` `ACTIVE` with `cash_balance_cents`, `invested_value_cents`, `committed_grants_cents`, `admin_fee_accrued_cents`, and `grantable_balance_cents` all initialized to 0, and `last_grant_paid_quarter` null. Accounts can be listed and filtered by `sponsor_id` and `status`. A single account read returns the account with its computed balances; a dedicated summary view also returns the account but lets the caller switch the grantable-balance variant via the `projection` query parameter, described below.

Uninvested cash is put to work by moving it into investment pools through a `RebalanceOrder`. A `DonorAdvisor` creates a draft order naming the account via `donor_account_id`, a `source_pool_id` and a `target_pool_id` (either of which may be null), the cash-equivalent `amount_cents` to move (which must be positive), and an optional `target_pct_bps` carrying the donor's target weight for the target allocation in basis points. A null `source_pool_id` means the cash is coming from the account's uninvested cash (a **buy**); a null `target_pool_id` means the proceeds go back to uninvested cash (a **redeem-to-cash**). The order is created in `status` `DRAFT`. Orders can be listed and filtered by `donor_account_id` and `status`.

Executing a draft order is owner-scoped: the acting `DonorAdvisor`'s `X-User-ID` must equal the account's `primary_advisor_user_id`, or the request is rejected with `ERR_NOT_ACCOUNT_OWNER`. When a target pool is named, that pool must be `OPEN`; buying into a `CLOSED` pool is rejected with `ERR_POOL_CLOSED`. For a buy (no source pool), the account's `cash_balance_cents` must be at least the `amount_cents`; insufficient cash is rejected with `ERR_INSUFFICIENT_CASH`. For a redeem (a source pool is named), the source allocation's invested value must be at least the `amount_cents`; an under-funded redemption is rejected with `ERR_INSUFFICIENT_POOL_UNITS`.

The unit arithmetic on execution is deliberately asymmetric so the fund is never short. Units are tracked on a `PoolAllocation`, the junction between an account (`donor_account_id`) and a pool (`investment_pool_id`), holding `units_micro` (units multiplied by 1,000,000), the donor's `target_pct_bps`, and a `status` of `ACTIVE` or `LIQUIDATED`. On a **buy**, the number of micro-units added is the floor of the `amount_cents` multiplied by 1,000,000 and divided by the target pool's `nav_per_unit_cents` — flooring so the fund never credits a fractional unit beyond the cash paid; those micro-units are added to the target allocation's `units_micro` (creating the target allocation lazily if the account does not yet hold one), and `cash_balance_cents` is reduced by `amount_cents`, with a `LedgerEntry` of `entry_type` `POOL_BUY` appended. On a **redeem-to-cash**, the number of micro-units surrendered is the ceiling of the `amount_cents` multiplied by 1,000,000 and divided by the source pool's `nav_per_unit_cents` — ceiling so enough units are surrendered to fully cover the cash withdrawn; those micro-units are subtracted from the source allocation's `units_micro` and recorded on the order as `source_units_redeemed_micro` (a buy records the added micro-units on `target_units_bought_micro`), `cash_balance_cents` is increased by `amount_cents`, and a `LedgerEntry` of `entry_type` `POOL_REDEEM` is appended. The subtraction never drives `units_micro` below 0: when the ceiling number of surrendered micro-units would exceed the allocation's current `units_micro` — which happens precisely when redeeming an allocation's full invested value, because the ceiling can surrender slightly more units than the allocation literally holds — the resulting `units_micro` is clamped up to 0 rather than left negative, and the recorded `source_units_redeemed_micro` is still the full ceiling figure. Because the buy branch floors and the redeem branch ceils, the operation is not symmetric — buying then redeeming the same amount can leave residual units behind. After either leg, the account's `invested_value_cents` and `grantable_balance_cents` are recomputed. An allocation whose `units_micro` reaches 0 after a redemption — whether by landing exactly at 0 or by being clamped up to 0 from an over-surrender — has its `status` set to `LIQUIDATED`. Allocations can be listed and filtered by `donor_account_id`, `investment_pool_id`, and `status`.

An owner may also cancel a draft order, moving its `status` to `CANCELLED` with no balance change; cancellation is owner-scoped under the same `ERR_NOT_ACCOUNT_OWNER` check. An order that is not in `DRAFT` cannot be executed or cancelled — an out-of-state transition is rejected with `ERR_INVALID_STATE`.

A single allocation is valued by dividing its `units_micro` by 1,000,000 and multiplying by its pool's `nav_per_unit_cents`, rounded half up to whole cents; the account's `invested_value_cents` is the sum of that valuation over all `ACTIVE` allocations. The account's settled grantable balance is its `cash_balance_cents` plus this `invested_value_cents` minus `committed_grants_cents` minus `admin_fee_accrued_cents`. The summary view exposes two readings of this figure through the `projection` query parameter. The default reading (the **SETTLED** variant, used when no `projection` is supplied) counts only settled contributions, which are already folded into cash and investments, and excludes pending contributions entirely. The **PROJECTED** variant (used when `projection` equals `PROJECTED`) takes the same settled grantable balance and adds, for every contribution on the account still in `PENDING` status, a provisional value computed by applying the same fair-market-value formula to that pending contribution's current pricing inputs; the projected figure therefore exceeds the settled figure by the sum of those pending provisional valuations.

### 3.5. Recommending Grants and the Segregation of Duties

A grant flows from a donor's recommendation through approval, scheduling, and payment — and the donor who recommends it never approves or pays it. A `DonorAdvisor` submits a `GrantRecommendation` naming the account via `donor_account_id` and the recipient via `charity_id`, with the `amount_cents` to grant and an optional `is_anonymous` flag (default false) that, when true, instructs the sponsor to remit without disclosing the donor account's identity to the charity. The submission may carry a free-text `purpose`, and a `recurrence` of either `ONE_TIME` (the default) or `RECURRING`; a recurring grant occupies a fiscal-quarter window bounded by `effective_from_quarter` and `effective_to_quarter`. The submitter's `X-User-ID` is recorded as `recommended_by_user_id`, the segregation-of-duties anchor, and `approved_by_user_id` and `paid_quarter_index` start null. The grant amount must be at least the sponsor's `minimum_grant_cents`; a smaller amount is rejected with `ERR_BELOW_MINIMUM_GRANT`. Submission is the optimistic-concurrency-guarded write of Section 2.9: it requires `expected_account_version` matching the account's current `version`, failing with `ERR_STALE_ACCOUNT_VERSION` on a mismatch, and on success records the grant in `status` `SUBMITTED`, recomputes the account's `committed_grants_cents` and `grantable_balance_cents`, and increments the account's `version` by one. Grants can be listed and filtered by `donor_account_id`, `charity_id`, and `status`. A grant moves across the states `SUBMITTED`, `APPROVED`, `SCHEDULED`, `PAID`, `REJECTED`, and `CANCELLED`.

A `GrantOfficer` approves a `SUBMITTED` grant. Approval is gated by three checks. First, segregation of duties: the approving officer's `X-User-ID` must differ from the grant's `recommended_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, the recipient charity must currently be `VETTED`, or the request is rejected with `ERR_CHARITY_NOT_VETTED`. Third, the donor account must be in `status` `ACTIVE` or `INACTIVE` — approval is permitted for an inactive account but not for one winding down or closed; an account outside that set is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. On success the grant's `status` becomes `APPROVED` and the officer's `X-User-ID` is recorded as `approved_by_user_id`.

A `GrantOfficer` may instead reject a `SUBMITTED` grant. Rejection is also subject to segregation of duties — the rejecting officer's `X-User-ID` must differ from `recommended_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`. On rejection the grant's `status` becomes `REJECTED` and the account's `committed_grants_cents` and `grantable_balance_cents` are recomputed to release the amount. Separately, the account owner — the `DonorAdvisor` whose `X-User-ID` equals the account's `primary_advisor_user_id`, else `ERR_NOT_ACCOUNT_OWNER` — may cancel a grant that is still in `SUBMITTED`, `APPROVED`, or `SCHEDULED`, moving its `status` to `CANCELLED` and recomputing `committed_grants_cents` and `grantable_balance_cents`. `REJECTED`, `CANCELLED`, and `PAID` are terminal, and a transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.6. Scheduling, Recurring-Grant Windows, and Payout

A `GrantOfficer` schedules an `APPROVED` grant, advancing its `status` to `SCHEDULED`. Scheduling re-verifies eligibility and funding. The charity must still be `VETTED`, failing with `ERR_CHARITY_NOT_VETTED`. The account must have enough total value to cover the grant: the sum of `cash_balance_cents` and `invested_value_cents` must be at least the grant's `amount_cents`, or the request is rejected with `ERR_INSUFFICIENT_GRANTABLE_BALANCE`. For a `RECURRING` grant, the requested window must not overlap an existing one. Recurring windows are **closed** intervals: a window runs from `effective_from_quarter` inclusive through `effective_to_quarter` inclusive. The new window collides with an existing `SCHEDULED` `RECURRING` grant to the same charity from the same account when the existing window's start is at most the new window's end **and** the new window's start is at most the existing window's end — so, because the interval is closed, windows that merely touch at a boundary (for example one ending at quarter 5 and another beginning at quarter 5) **do** collide, which is the opposite of the half-open rule that governs NAV periods. On such a collision scheduling is rejected with `ERR_RECURRING_GRANT_OVERLAP`.

A `GrantOfficer` pays a `SCHEDULED` grant, advancing its `status` to `PAID`. Payment re-checks two conditions, because time may have passed since scheduling: the charity must still be `VETTED` — re-checked precisely because a watchlist or revoke decision may have intervened — failing with `ERR_CHARITY_NOT_VETTED`; and the sum of `cash_balance_cents` and `invested_value_cents` must still be at least the `amount_cents`, failing with `ERR_INSUFFICIENT_GRANTABLE_BALANCE`.

Payment then runs the **payout waterfall** to raise cash and debit the grant. First compute the shortfall: the amount needed is the grant's `amount_cents` minus the account's current `cash_balance_cents`. If that shortfall is zero or negative, no pool redemption is needed. Otherwise the account's `ACTIVE` pool allocations that still hold units (those with `units_micro` greater than 0) are processed in a fixed order — by `target_pct_bps` descending, and within equal target weight by `created_at` ascending (never by id). Walking allocations in that order while a shortfall remains: value the current allocation by dividing its `units_micro` by 1,000,000, multiplying by its pool's `nav_per_unit_cents`, and rounding half up; take from it the smaller of that allocation value and the remaining shortfall; redeem from that allocation the ceiling of the taken amount multiplied by 1,000,000 and divided by the pool's `nav_per_unit_cents` micro-units; credit the taken amount to `cash_balance_cents`; and reduce the remaining shortfall by the taken amount. An allocation drawn down to `units_micro` of 0 has its `status` set to `LIQUIDATED`. Once the cash balance covers the grant, the grant amount is subtracted from `cash_balance_cents`. Because for the redeem legs the cash credited equals the invested value debited at each allocation's NAV, the sum of cash and invested value is unchanged by redemption itself; the only net reduction is the grant debit, which equals exactly the `amount_cents`.

The payout cascade appends, for each pool drawn down, a `LedgerEntry` of `entry_type` `POOL_REDEEM`, and one `LedgerEntry` of `entry_type` `GRANT_PAID` with `signed_amount_cents` equal to the negative `amount_cents`. The account's `committed_grants_cents` and then `grantable_balance_cents` are recomputed. The grant's `paid_quarter_index` is set to the sponsor's `current_quarter_index`, and the account's `last_grant_paid_quarter` is updated to the same value — recording that a paid grant occurred this quarter clears the inactivity countdown. If the account was `INACTIVE`, paying a grant transitions it back to `ACTIVE`.

### 3.7. The Quarterly Close: Fee Accrual and Inactivity

A `SponsorAdmin` closes a sponsor quarter to advance the fiscal clock. Closing increments the sponsor's `current_quarter_index` by one and then, for each donor account under the sponsor, accrues that quarter's administration fee and re-evaluates the inactivity policy.

The **quarterly admin fee** is computed per account by summing rounded per-allocation fees, and the rounding order is pinned: round each allocation's fee first, then sum — never sum first and round once. For a single `ACTIVE` allocation, first value it by dividing its `units_micro` by 1,000,000, multiplying by its pool's `nav_per_unit_cents`, and rounding half up to whole cents. The per-allocation quarterly fee is then that invested value multiplied by the pool's `fee_bps` and divided by 40,000 — where 40,000 is the basis-point scale of 10,000 multiplied by the 4 quarters in a year — and rounded half up to whole cents. The account's fee for the quarter is the sum of those per-allocation fees over all of its `ACTIVE` allocations. That sum is added to the account's `admin_fee_accrued_cents`, a `LedgerEntry` of `entry_type` `ADMIN_FEE` is appended with `signed_amount_cents` equal to the negative fee, and the account's `grantable_balance_cents` is recomputed.

The **inactivity policy** is evaluated next. An account that is currently `ACTIVE` becomes `INACTIVE` when two conditions both hold: it has been inactive long enough — either it has never had a paid grant (its `last_grant_paid_quarter` is null) or the sponsor's `current_quarter_index` minus its `last_grant_paid_quarter` is at least the sponsor's `inactivity_quarters` — and it still has a positive grantable balance (`grantable_balance_cents` greater than 0). An account flagged `INACTIVE` is queued for required-distribution outreach but still accepts grant recommendations; as noted above, paying any grant on it transitions it back to `ACTIVE`.

### 3.8. Succession, Wind-Down, and the Legacy Split

A donor plans for the eventual end of their giving through a `SuccessionPlan`, created by the account owner (the `DonorAdvisor` whose `X-User-ID` equals the account's `primary_advisor_user_id`, else `ERR_NOT_ACCOUNT_OWNER`) against an account via `donor_account_id`. The `plan_type` is either `SUCCESSOR_ADVISOR` — naming a `successor_user_id` who will take over advising — or `LEGACY_GRANTS` — naming a list of `beneficiaries`, each a charity (by `charity_id`) and a `share_bps` weight in basis points. For a `LEGACY_GRANTS` plan the beneficiaries' `share_bps` must sum to exactly 10,000 (a full 100%); any other total is rejected with `ERR_SHARE_BPS_NOT_100`. A new plan begins in `status` `DRAFT`. The owner later confirms a draft plan, moving its `status` to `CONFIRMED`; confirmation is required before an account can be wound down. Plans can be listed and filtered by `donor_account_id`, `plan_type`, and `status`. A plan reaches `EXECUTED` only through succession execution, below.

A `SponsorAdmin` moves an account into wind-down. Wind-down is permitted from `ACTIVE` or `INACTIVE`, and requires that a `CONFIRMED` `LEGACY_GRANTS` succession plan already exist for the account; without one, the request is rejected with `ERR_NO_CONFIRMED_SUCCESSION`. On success the account's `status` becomes `WIND_DOWN`, after which no new contributions are accepted.

A `SponsorAdmin` then executes the succession to close the account. Execution requires that the account be in `WIND_DOWN` — calling it on an account in any other state is rejected with `ERR_ACCOUNT_NOT_IN_WIND_DOWN`; that no grant remains in `SUBMITTED`, `APPROVED`, or `SCHEDULED` — outstanding grants block the close with `ERR_PENDING_GRANTS_BLOCK_CLOSE`; and that every charity named as a `LEGACY_GRANTS` beneficiary is currently `VETTED` — an unvetted beneficiary blocks the close with `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED`. When those hold, all of the account's pool allocations are liquidated to cash, leaving a residual equal to the account's grantable balance (which, with all allocations liquidated and no commitments remaining, equals `cash_balance_cents`).

That residual is apportioned across the legacy beneficiaries by a **largest-remainder** split that conserves every cent. For each beneficiary, the floor share is the floor of the residual multiplied by that beneficiary's `share_bps` and divided by 10,000. The leftover — the residual minus the sum of all floor shares — is then distributed one extra cent at a time to beneficiaries ordered by the fractional part of (residual multiplied by `share_bps` divided by 10,000) descending, with ties broken by the beneficiary charity row's `created_at` ascending. The sum of the final shares therefore equals the residual exactly — no cent is created or destroyed. For each beneficiary, a `LedgerEntry` of `entry_type` `LEGACY_DISBURSEMENT` is appended with `signed_amount_cents` equal to the negative of that beneficiary's share, and the account's `cash_balance_cents` is drained to 0. Finally the succession plan's `status` becomes `EXECUTED` and the account's `status` becomes `CLOSED`. The conserved invariant holds: the sum of the legacy disbursements equals the residual. `CLOSED` is the terminal account state.

### 3.9. Reading the Ledger and Substantiation Records

The audit trail is read-only to clients. Individual ledger entries can be retrieved by id, and the full ledger can be listed and filtered by `donor_account_id` and `entry_type` to reconstruct any account's complete cash history. Substantiation receipts are likewise retrievable by id and can be listed and filtered by `contribution_id` and `donor_account_id`; a request for a receipt id that does not exist returns `ERR_RECEIPT_NOT_FOUND`.

### 3.10. Ordering of Validation Checks

When several validations could apply to one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication comes first: a missing or malformed `X-User-ID`/`X-User-Role` (`ERR_MISSING_USER_CONTEXT`) is detected before anything else, then role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`). Next, existence: every path-referenced and then body-referenced foreign-key resource must exist (`ERR_NOT_FOUND`), validated left-to-right with path identifiers before body foreign keys. After existence comes owner-scope: for owner-scoped `DonorAdvisor` actions, the caller must own the account (`ERR_NOT_ACCOUNT_OWNER`). Then the generic state check: the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`). Only after those structural checks do the business rules apply — the account-active gate (`ERR_ACCOUNT_NOT_ACTIVE`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), grantee eligibility (`ERR_INELIGIBLE_GRANTEE`), charity-vetted (`ERR_CHARITY_NOT_VETTED`), minimum-grant (`ERR_BELOW_MINIMUM_GRANT`), valuation-input presence (`ERR_VALUATION_INPUT_MISSING`) and whole-share quantity (`ERR_VALUATION_QUANTITY_INVALID`), pool-open (`ERR_POOL_CLOSED`), legacy-share total (`ERR_SHARE_BPS_NOT_100`), the interval-overlap rules (`ERR_NAV_PERIOD_OVERLAP`, `ERR_RECURRING_GRANT_OVERLAP`), the succession gates (`ERR_NO_CONFIRMED_SUCCESSION`, `ERR_PENDING_GRANTS_BLOCK_CLOSE`, `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED`, `ERR_ACCOUNT_NOT_IN_WIND_DOWN`), the funding checks (`ERR_INSUFFICIENT_CASH`, `ERR_INSUFFICIENT_POOL_UNITS`, `ERR_INSUFFICIENT_GRANTABLE_BALANCE`), and the duplicate-EIN check (`ERR_DUPLICATE_CHARITY_EIN`). The grant-submission stale-version check (`ERR_STALE_ACCOUNT_VERSION`) guards that one write. Generic body-shape problems — a missing required field, an invalid enum value, a non-positive amount, or a non-positive `nav_per_unit_cents` — surface as `ERR_INVALID_REQUEST` on any write endpoint.

## 4. Endpoint Definitions

All endpoints are mounted under the `/daf` prefix. A request that creates a brand-new resource returns HTTP 201; a request that reads or modifies an existing resource (including all state transitions and computed reads) returns HTTP 200. Error responses carry the HTTP status listed in Section 5. The table below summarizes each endpoint; request and response bodies are not repeated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/daf/sponsors` | Create a sponsor (DAF program) | SponsorAdmin |
| GET | `/daf/sponsors/{sponsorId}` | Get a sponsor | SponsorAdmin, ComplianceOfficer, ContributionAdmin, GrantOfficer, DonorAdvisor |
| POST | `/daf/sponsors/{sponsorId}/close_quarter` | Advance fiscal quarter; accrue admin fees; evaluate inactivity | SponsorAdmin |
| POST | `/daf/pools` | Create an investment pool | SponsorAdmin |
| GET | `/daf/pools/{poolId}` | Get an investment pool | SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/pools` | List investment pools | SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/pools/{poolId}/close` | Close a pool to new buy allocations | SponsorAdmin |
| POST | `/daf/nav-periods` | Create a NAV pricing window | SponsorAdmin |
| GET | `/daf/nav-periods/{navPeriodId}` | Get a NAV period | SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/nav-periods` | List NAV periods | SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/charities` | Register a recipient charity | ComplianceOfficer, SponsorAdmin |
| GET | `/daf/charities/{charityId}` | Get a charity | ComplianceOfficer, SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/charities` | List charities | ComplianceOfficer, SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/charities/{charityId}/vet` | Record a vetting decision | ComplianceOfficer |
| POST | `/daf/accounts` | Open a donor account | SponsorAdmin, DonorAdvisor |
| GET | `/daf/accounts/{accountId}` | Get a donor account with computed balances | SponsorAdmin, DonorAdvisor, GrantOfficer, ContributionAdmin, ComplianceOfficer |
| GET | `/daf/accounts` | List donor accounts | SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/accounts/{accountId}/summary` | Computed account summary; `projection` switches the grantable variant | SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/accounts/{accountId}/wind-down` | Move account to WIND_DOWN | SponsorAdmin |
| POST | `/daf/accounts/{accountId}/execute-succession` | Liquidate residual to legacy beneficiaries; close account | SponsorAdmin |
| POST | `/daf/contributions` | Record an irrevocable contribution | DonorAdvisor, ContributionAdmin |
| GET | `/daf/contributions/{contributionId}` | Get a contribution | SponsorAdmin, DonorAdvisor, ContributionAdmin |
| GET | `/daf/contributions` | List contributions | SponsorAdmin, DonorAdvisor, ContributionAdmin |
| POST | `/daf/contributions/{contributionId}/settle` | Settle and value a contribution; mint substantiation | ContributionAdmin |
| POST | `/daf/contributions/{contributionId}/reject` | Reject a PENDING contribution | ContributionAdmin |
| GET | `/daf/receipts/{receiptId}` | Get a substantiation receipt | SponsorAdmin, DonorAdvisor, ContributionAdmin |
| GET | `/daf/receipts` | List substantiation receipts | SponsorAdmin, DonorAdvisor, ContributionAdmin |
| GET | `/daf/allocations/{allocationId}` | Get a pool allocation | SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/allocations` | List pool allocations | SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/rebalance-orders` | Create a draft rebalance order | DonorAdvisor |
| GET | `/daf/rebalance-orders/{orderId}` | Get a rebalance order | SponsorAdmin, DonorAdvisor |
| GET | `/daf/rebalance-orders` | List rebalance orders | SponsorAdmin, DonorAdvisor |
| POST | `/daf/rebalance-orders/{orderId}/execute` | Execute the rebalance; buy/redeem pool units | DonorAdvisor |
| POST | `/daf/rebalance-orders/{orderId}/cancel` | Cancel a draft rebalance order | DonorAdvisor |
| POST | `/daf/grants` | Submit a grant recommendation (OCC-guarded) | DonorAdvisor |
| GET | `/daf/grants/{grantId}` | Get a grant recommendation | SponsorAdmin, DonorAdvisor, GrantOfficer |
| GET | `/daf/grants` | List grant recommendations | SponsorAdmin, DonorAdvisor, GrantOfficer |
| POST | `/daf/grants/{grantId}/approve` | Approve a submitted grant | GrantOfficer |
| POST | `/daf/grants/{grantId}/reject` | Reject a submitted grant | GrantOfficer |
| POST | `/daf/grants/{grantId}/schedule` | Schedule an approved grant | GrantOfficer |
| POST | `/daf/grants/{grantId}/pay` | Pay a scheduled grant | GrantOfficer |
| POST | `/daf/grants/{grantId}/cancel` | Account owner cancels a non-terminal grant | DonorAdvisor |
| POST | `/daf/succession-plans` | Create a succession plan | DonorAdvisor |
| GET | `/daf/succession-plans/{planId}` | Get a succession plan | SponsorAdmin, DonorAdvisor |
| GET | `/daf/succession-plans` | List succession plans | SponsorAdmin, DonorAdvisor |
| POST | `/daf/succession-plans/{planId}/confirm` | Confirm a draft succession plan | DonorAdvisor |
| GET | `/daf/ledger-entries/{ledgerEntryId}` | Get a ledger entry | SponsorAdmin, DonorAdvisor, GrantOfficer, ComplianceOfficer |
| GET | `/daf/ledger-entries` | List ledger entries | SponsorAdmin, DonorAdvisor, GrantOfficer, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_ACCOUNT_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INELIGIBLE_GRANTEE` | 409 |
| `ERR_CHARITY_NOT_VETTED` | 409 |
| `ERR_BELOW_MINIMUM_GRANT` | 422 |
| `ERR_VALUATION_INPUT_MISSING` | 422 |
| `ERR_VALUATION_QUANTITY_INVALID` | 422 |
| `ERR_POOL_NAV_INVALID` | 422 |
| `ERR_POOL_CLOSED` | 409 |
| `ERR_SHARE_BPS_NOT_100` | 422 |
| `ERR_NAV_PERIOD_OVERLAP` | 409 |
| `ERR_RECURRING_GRANT_OVERLAP` | 409 |
| `ERR_NO_CONFIRMED_SUCCESSION` | 409 |
| `ERR_PENDING_GRANTS_BLOCK_CLOSE` | 409 |
| `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED` | 409 |
| `ERR_ACCOUNT_NOT_IN_WIND_DOWN` | 409 |
| `ERR_INSUFFICIENT_CASH` | 409 |
| `ERR_INSUFFICIENT_POOL_UNITS` | 409 |
| `ERR_INSUFFICIENT_GRANTABLE_BALANCE` | 409 |
| `ERR_DUPLICATE_CHARITY_EIN` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
