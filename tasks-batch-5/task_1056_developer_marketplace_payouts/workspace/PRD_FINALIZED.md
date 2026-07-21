# Developer Marketplace Payouts API — Product Requirements Document

## 1. Introduction

A developer marketplace earns its trust twice: once when a buyer's money moves, and again — weeks later — when the developer's share of that money lands in a bank account. Between those two moments sits everything this system is responsible for: a listing that had to be reviewed and approved, a price that had to be legal in the buyer's country, a tax split that had to be extracted from a tax-inclusive sticker price, a revenue-share rate that depends on how much the developer has ever earned, refunds and card-network disputes that reach backwards into money already accrued, trust-and-safety takedowns that can freeze a payout mid-flight, and an annual tax form that must report exactly what was paid and nothing else.

This document specifies the marketplace's back-office API. It is deliberately a *ledger* system rather than a balance system: every movement of a developer's money is recorded as an individual, signed entry, and the roll-up figures shown on a developer account are always derivable from those entries. Two conservation identities anchor the design. Per purchase, the platform fee, the developer's net share and the extracted tax must add up to the gross the buyer paid; once a purchase has been refunded in full, the entries attached to it must sum to exactly zero. Per developer, the unsettled ledger position must always equal the account's reported accrual minus its reported negative balance — before a chargeback is lost, and again after that chargeback is reversed, with both sides restored to their pre-dispute values.

Six kinds of actor share the surface, and the boundaries between them are enforced, not advisory. The operator who opens a policy case is not permitted to decide it. The finance operator who assembles and submits a payout batch is not permitted to approve it. These separations exist because the operations they guard move money irreversibly, and because a marketplace that cannot demonstrate them cannot be audited.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors and Role-Based Access Control

Every request to this API — without exception, including reads — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is absent, or if `X-User-Role` carries a value that is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are well-formed but the named role does not appear in the authorised-role list published for that endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `Developer`, `ReviewAgent`, `PolicyOfficer`, `FinanceOps`, `PlatformAdmin` and `StorefrontService`.

A `Developer` is the owner of a developer account: it creates listings and pricing plans, publishes approved listings, retires plans and appeals policy decisions taken against it. A `ReviewAgent` is a store reviewer who claims submitted review rounds for triage and records their outcome. A `PolicyOfficer` is a trust-and-safety operator who opens, investigates and decides policy cases, and who moves listings and developer accounts in and out of suspension. `FinanceOps` is the payments operator: it decides and executes refunds, works card-network disputes, sets payout holds, and drives payout batches from creation through calculation, submission and disbursement — but it may never approve a batch. `PlatformAdmin` is the marketplace administrator: it configures tax jurisdictions and revenue-share tiers, opens, verifies, terminates and re-profiles developer accounts, approves payout batches, issues annual tax forms and drives the logical clock. `StorefrontService` is the storefront backend, which records purchases, captures or voids them, and files refund requests and inbound network disputes.

Only one role is tied to a persisted entity. When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `Developer` record; ownership checks on any resource that references a `Developer` compare that resource's owning developer identifier to `X-User-ID`. Concretely, a `Developer` caller may act on an `App` only when the app's `developer_id` equals `X-User-ID`; on a `PricingPlan` only when the plan's owning app's `developer_id` equals `X-User-ID`; on a `PolicyCase` only when the case's `developer_id` equals `X-User-ID`; and on a `Developer` record only when its `id` equals `X-User-ID`. A violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `ReviewAgent`, `PolicyOfficer`, `FinanceOps`, `PlatformAdmin` or `StorefrontService`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow calls for an audit trail — as `triaged_by_user_id` and by comparison for review decisions, as `decided_by_user_id` on a refund or a policy case, as `opened_by_user_id` on a policy case, and as `submitted_by_user_id` and `approved_by_user_id` on a payout batch — but it never compares it to any entity's `id`.

Two separations of duty are enforced on top of role membership. A `PolicyOfficer` whose `X-User-ID` equals the `opened_by_user_id` recorded on a policy case may not decide that case, and may not decide an appeal against it; both attempts are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Separately, payout-batch approval is reserved to `PlatformAdmin` and is unavailable to the `FinanceOps` operator who calculated and submitted the batch; that separation is expressed through the role lists in §4 rather than through a dedicated error.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, must be an integer of at least 1, and may not exceed 100. `offset` controls the starting position: it defaults to 0 when omitted and must be an integer of at least 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Results on every list endpoint are returned in ascending `created_at` order unless that endpoint's narrative says otherwise. The `meta` object of a list response carries `limit` and `offset` as applied, `total_count` giving the number of records matching the filters before pagination was applied, and `has_more`, which is true exactly when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps and Versioning

Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix and no embedded meaning, and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional digits. Client-supplied identifiers are never accepted as the `id` of a new resource.

Most resources additionally carry an `updated_at` timestamp in the same format and an integer `version`. The `version` of a resource begins at 1 when the resource is created and advances by exactly 1 on every mutation of that resource, with `updated_at` refreshed at the same moment. This applies to `Developer`, `App`, `ReviewSubmission`, `PricingPlan`, `Purchase`, `Refund`, `Chargeback`, `PolicyCase`, `PayoutBatch`, `PayoutLine` and `TaxForm1099` records.

Three resource types are deliberately immutable reference data or append-only records and therefore carry **only** `id` and `created_at` — they expose neither `updated_at` nor `version`, and those two fields must be absent from their representations entirely: `TaxJurisdiction`, `RevenueShareTier` and `LedgerEntry`.

### 2.5. The Logical Clock

Time in this system is logical, not wall-clock. Every window evaluation, expiry test and time stamp that the business rules depend on — capture instants, dispute receipt instants, refund windows, representment windows, payout period boundaries and risk-scoring windows — reads the server's logical clock. Before the clock has ever been set, it reads exactly `2026-07-01T00:00:00Z`, and it never falls back to real wall-clock time. A `PlatformAdmin` may move the clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`. Envelope fields such as `api_request_timestamp` are not governed by the logical clock.

### 2.6. Money, Basis Points and Rounding Discipline

All monetary amounts in this API are integers denominated in the minor unit of their currency — cents — and every field carrying money is named with a `_cents` suffix. Rates are expressed in **basis points**, where 10,000 basis points is one hundred percent; a field carrying a rate is named with a `_bps` suffix.

Wherever a computation produces a fractional number of cents, the result is rounded half-up to a whole cent: a value whose fractional part is exactly one half rounds away from zero to the next whole cent. Where a rule fixes the *order* in which rounding is applied relative to summation, that order is part of the specification and is stated with the rule; rounding at a different point in the sequence produces a different, incorrect answer whenever more than one component is involved.

Tax is extracted from tax-inclusive prices rather than added to tax-exclusive ones. Given a jurisdiction whose VAT rate is a number of basis points, the tax contained in a tax-inclusive amount is that amount multiplied by the rate and divided by the sum of 10,000 and the rate, rounded half-up to a whole cent.

### 2.7. Optimistic Concurrency on Listing and Account Writes

Two write operations in this system take a decision against a view of a parent record that may have moved underneath the caller, and both are therefore guarded by optimistic concurrency. In each case the client must send the `version` it last observed on the parent, and the server compares it against the parent's current `version`.

Attaching a pricing plan to a listing requires the request body to carry `expected_app_version`, a non-optional field holding the client's last observed `version` of the target `App`. If that value does not equal the app's current `version`, the request is rejected with `ERR_STALE_APP_VERSION` (HTTP 412). The guard exists because a new plan legitimately supersedes the prior plan of the same kind by extending the effective-window chain; a writer working from an out-of-date view of the listing would append behind a window it never saw.

Setting or clearing a developer's payout hold requires the request body to carry `expected_developer_version`, a non-optional field holding the client's last observed `version` of the target `Developer`. If that value does not equal the developer's current `version`, the request is rejected with `ERR_STALE_DEVELOPER_VERSION` (HTTP 412). Hold decisions are taken against an observed ledger position, and any cascade that moved the account's negative balance in the meantime invalidates that position.

No other endpoint in this API accepts a version field, and none of them may be rejected for a version mismatch.

### 2.8. Validation Precedence

When a single request would fail several checks, the rejection that is returned is fixed and not implementation-dependent. Checks are evaluated in the following order, and the first one that fails determines the response:

1. **Authentication.** Headers present and `X-User-Role` a declared role — otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorisation.** The acting role appears in the endpoint's authorised-role list in §4 — otherwise `ERR_UNAUTHORIZED`.
3. **Resource ownership.** On every endpoint a `Developer` may call, `X-User-ID` matches the owning developer of the targeted resource — otherwise `ERR_NOT_RESOURCE_OWNER`.
4. **Separation of duties.** On a policy-case decision and on a policy-case appeal decision, the acting officer differs from the officer who opened the case — otherwise `ERR_SEGREGATION_OF_DUTIES`.
5. **Existence.** Every resource named in the URL path exists, validated left to right, so that the outermost missing segment is the one reported. The error identifier names the missing resource type: `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`, `ERR_REVIEW_SUBMISSION_NOT_FOUND`, `ERR_PRICING_PLAN_NOT_FOUND`, `ERR_TAX_JURISDICTION_NOT_FOUND`, `ERR_REVENUE_SHARE_TIER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND`, `ERR_POLICY_CASE_NOT_FOUND`, `ERR_PAYOUT_BATCH_NOT_FOUND`, `ERR_PAYOUT_LINE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404.
6. **Request shape.** On every write endpoint: each required field is present and of the declared type, each enum-typed value is a declared member of that enumeration, monetary inputs such as `price_cents` and `amount_cents` are strictly greater than zero, `line_items` is a non-empty array whose objects each carry a `sku`, a `unit_price_cents` strictly greater than zero and a `quantity` strictly greater than zero, and uniqueness holds for `external_order_ref` across all purchases and for `network_case_ref` across all chargebacks. A failure here is `ERR_INVALID_REQUEST` (HTTP 400).
7. **Pagination shape.** On every list endpoint, `limit` and `offset` are within their declared bounds — otherwise `ERR_INVALID_PAGINATION`.
8. **Optimistic concurrency.** The stale-version guards of §2.7 — `ERR_STALE_APP_VERSION` on pricing-plan creation, then `ERR_STALE_DEVELOPER_VERSION` on a payout-hold write.
9. **State legality.** The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (HTTP 409). Where a transition additionally requires the owning account to be `ACTIVE`, that check follows immediately (`ERR_DEVELOPER_NOT_ACTIVE`), then the refundability check on a purchase (`ERR_PURCHASE_NOT_REFUNDABLE`).
10. **Business safety.** Purchasability of the listing and plan (`ERR_APP_NOT_PURCHASABLE`), then the payout-hold guard on batch approval (`ERR_DEVELOPER_PAYOUT_HELD`).
11. **Referential business checks.** Jurisdiction configuration (`ERR_JURISDICTION_NOT_CONFIGURED`), then plan-to-app agreement (`ERR_PLAN_APP_MISMATCH`).
12. **Temporal business checks.** Pricing-window spacing (`ERR_PRICING_WINDOW_CONFLICT`), then payout-period overlap (`ERR_BATCH_PERIOD_OVERLAP`), then the refund window (`ERR_REFUND_WINDOW_EXPIRED`), then the representment window (`ERR_REPRESENTMENT_WINDOW_EXPIRED`).
13. **Fiscal and remaining business checks.** Refund headroom (`ERR_REFUND_EXCEEDS_REMAINING`), then pricing-period coherence (`ERR_INVALID_PRICING`), then the tax-identity precondition on verification (`ERR_TAX_ID_REQUIRED`), then the uniqueness of an annual form (`ERR_TAX_FORM_EXISTS`) and of a jurisdiction (`ERR_JURISDICTION_EXISTS`).

### 2.9. Cascades, Ledger Integrity and Derived Roll-Ups

Several operations in this system mutate more than one record. A cascade is never partial: when an operation is accepted, every downstream effect described for it in §3 is applied within the same request, and each mutated record has its own `updated_at` refreshed and its own `version` advanced. When a cascade re-enters a state machine — a policy decision that delists a listing, a delisting that suspends an account, a suspension that freezes payout lines, frozen lines that force a batch's totals to be recomputed — the downstream transition carries all of *its* declared effects too, recursively.

The developer-level money figures are **derived**, never independently maintained. `unpaid_accrual_cents` is recomputed after every ledger movement as the sum of `amount_cents` over that developer's `LedgerEntry` rows whose `settled` flag is false; `negative_balance_cents` is the non-negative amount the developer owes the marketplace, and it is populated whenever that recomputed sum comes out below zero, in which case the accrual figure is clamped to 0 and the magnitude of the shortfall is carried in the negative balance instead. When that recomputed sum instead comes out at or above zero, the accrual figure simply takes the sum and any negative balance already carried is left untouched by the recompute: a debt the developer owes is discharged only by the recovery step of the payout waterfall (§3.9) or by the explicit full recompute of the negative balance that chargeback reversal performs (§3.7). `lifetime_revenue_base_cents` is the running sum of `revenue_base_cents` over that developer's purchases whose `payment_status` is `CAPTURED`. These identities are what make the annual and per-batch numbers reproducible from the ledger alone.

## 3. Business Logic & Workflows

### 3.1. Configuring the Marketplace: Jurisdictions and Tiers

Before a single purchase can be recorded, a `PlatformAdmin` must describe the tax landscape. A tax jurisdiction is registered with a `country_code` — an ISO-3166 alpha-2 code — a `vat_rate_bps` between 0 and 3000 inclusive, and a `marketplace_facilitator` flag. The flag decides who is legally on the hook for the VAT: when it is true, the marketplace itself remits the tax and the developer never sees it; when it is false, the developer remits it and the marketplace passes the tax through to the developer as part of the payout. At most one jurisdiction may exist per country; a second registration for the same `country_code` is rejected with `ERR_JURISDICTION_EXISTS`. Jurisdictions are reference data: they carry `id` and `created_at` only.

The revenue-share ladder is registered separately. Each `RevenueShareTier` carries a human-readable `label`, a `min_cumulative_base_cents` giving the inclusive lower bound of a developer's lifetime commissionable revenue at which the tier begins to apply, and a `developer_share_bps` giving the developer's share in basis points — strictly greater than 0 and at most 10,000. Tiers, like jurisdictions, carry only `id` and `created_at`.

Tier selection is deterministic and is the same procedure everywhere it is used. Given a base amount, the candidate tiers are those whose `min_cumulative_base_cents` is less than or equal to that base amount. If no tier qualifies — including the case where no tiers have been registered at all — the developer's share is the marketplace default of 70 percent, that is, 7,000 basis points. Otherwise the candidates are ordered by `min_cumulative_base_cents` from highest to lowest; where two candidates share the same threshold, the one with the higher `developer_share_bps` wins; where they still tie, the one created earliest wins. The `developer_share_bps` of the first candidate under that ordering is the selected rate.

### 3.2. Opening, Verifying and Ending a Developer Account

A developer account is opened by a `PlatformAdmin` with a `legal_name` — the payee name that will be printed on the annual tax form — an `email`, a `country_code` of tax residence given as two uppercase letters, and optionally `tax_id_provided`. That last flag defaults to false, and false means the account is in backup withholding: every payout line it later generates will have tax withheld. New accounts begin at `PENDING_VERIFICATION`, with `payout_hold` and `risk_watch` both false, with `policy_strike_count`, `lifetime_revenue_base_cents`, `unpaid_accrual_cents`, `negative_balance_cents`, `carryover_cents` and `risk_score` all at 0, and with `risk_variant` at `STANDARD`.

Verification moves an account `PENDING_VERIFICATION → ACTIVE`, and it is refused unless `tax_id_provided` is already true — an attempt against an account with no tax identification on file is rejected with `ERR_TAX_ID_REQUIRED`. A `PlatformAdmin` may separately record the outcome of a tax-identity check at any time by supplying a fresh `tax_id_provided` value with an optional `reason`; clearing it puts the account back into backup withholding for all *future* payout lines without disturbing lines already calculated.

Suspension is a trust-and-safety action taken by a `PolicyOfficer` with a `reason`, and it is the third link of the takedown cascade described in §3.8. An `ACTIVE → SUSPENDED` move sets `payout_hold` to true, sets `risk_watch` to true — which switches risk scoring to its accelerated window and sets `risk_variant` to `ACCELERATED` — and then reaches into payouts: every payout line of that developer that is still `PAYABLE` and belongs to a batch in `CALCULATED` or `PENDING_APPROVAL` flips `PAYABLE → HELD_DEVELOPER` with its `payout_amount_cents` forced to 0. Each line that flips forces its owning batch to recompute `total_payable_cents` and `total_withholding_cents` over the lines that remain `PAYABLE`.

Reinstatement by a `PolicyOfficer`, also carrying a `reason`, moves the account `SUSPENDED → ACTIVE`, clears `risk_watch` and recomputes the risk score under the standard variant. It clears `payout_hold` **only** when `negative_balance_cents` is exactly 0; an account that still owes the marketplace comes back active but stays held. Payout lines that were already flipped to `HELD_DEVELOPER` are *not* restored — the money they represented is not resurrected by reinstatement.

Termination by a `PlatformAdmin`, with a `reason`, is available from `PENDING_VERIFICATION`, from `ACTIVE` and from `SUSPENDED`, and is refused only when the account is already `TERMINATED`. From `PENDING_VERIFICATION` the account simply becomes `TERMINATED`. From `ACTIVE` or from `SUSPENDED` it additionally delists every listing of that developer that is not already `DELISTED`, with each delisting carrying its own full set of effects. `TERMINATED` is final.

A payout hold may also be set or cleared directly by `FinanceOps` with a boolean `hold`, the mandatory `expected_developer_version` of §2.7 and an optional `reason`. The account exposes a computed summary read reporting `developer_id`, `unpaid_accrual_cents`, `negative_balance_cents`, `carryover_cents`, `lifetime_revenue_base_cents`, `risk_score`, `risk_variant` and `payout_hold` — the ledger position and risk posture in one place. Account lists may be narrowed by `status` and by `country_code`.

### 3.3. Listings: Draft, Review Rounds, Approval and Publication

A `Developer` creates a listing by supplying its own `developer_id`, a public `name`, a `category` drawn from `PRODUCTIVITY`, `GAMES`, `FINANCE`, `HEALTH` and `DEVELOPER_TOOLS`, and `listed_countries`, an array of ISO-3166 alpha-2 codes where the listing will be offered. The listing begins at `DRAFT` with `review_round` and `policy_strike_count` at 0. Listing metadata may be edited afterwards by its owner, supplying any of `name`, `category` or `listed_countries`; an edit made while the listing sits at `CHANGES_REQUESTED` also moves it `CHANGES_REQUESTED → DRAFT`, on the logic that the developer has begun responding to the reviewer's notes.

Submitting for review is permitted from `DRAFT` and from `CHANGES_REQUESTED`, is restricted to the owning developer, and additionally requires that at least one pricing plan with status `ACTIVE` already exists on the listing — a listing with nothing to sell is not reviewable. A successful submission moves the listing to `IN_REVIEW`, increments `review_round` by 1, and opens a `ReviewSubmission` in status `SUBMITTED` whose `app_id` names the listing, whose `round_number` equals the listing's `review_round` at that moment, and which carries the developer's `submitted_notes`. Because `CHANGES_REQUESTED → IN_REVIEW` is available without limit, a listing may cycle through review rounds any number of times, each round producing its own submission record with its own increasing `round_number`.

A `ReviewAgent` claims a submission for work, moving it `SUBMITTED → IN_TRIAGE` and stamping `triaged_by_user_id` with the acting `X-User-ID`. Only a submission already in `IN_TRIAGE` may be decided; the decision carries an `outcome` of either `PASSED` or `REJECTED` together with a `decision_reason`, which is stored on the submission. A `PASSED` decision moves the submission `IN_TRIAGE → PASSED` and simultaneously drives the listing `IN_REVIEW → APPROVED`. A `REJECTED` decision moves the submission `IN_TRIAGE → REJECTED` and drives the listing `IN_REVIEW → CHANGES_REQUESTED`, returning the ball to the developer. Both submission outcomes are terminal for that round; a further attempt at the listing requires a fresh submission. Submissions may be listed marketplace-wide or per listing, filtered by `app_id` and by `status`.

Publication is the owning developer's move and takes an `APPROVED` listing to `LIVE`. It is refused with `ERR_DEVELOPER_NOT_ACTIVE` unless the owning account is in status `ACTIVE` at that moment — an approved listing belonging to a suspended developer cannot go on sale.

Once live, a listing can be suspended by a `PolicyOfficer` with a `reason`, moving `LIVE → SUSPENDED`; a suspended listing rejects new purchases with `ERR_APP_NOT_PURCHASABLE`. The same officer can bring it back, `SUSPENDED → LIVE`, provided the owning account is `ACTIVE` — otherwise `ERR_DEVELOPER_NOT_ACTIVE` again. Suspension and reinstatement form a cycle that may repeat indefinitely.

Delisting is the end of the road and is reachable from `DRAFT`, from `APPROVED`, from `LIVE` and from `SUSPENDED` — from any state except `DELISTED` itself. It is performed by a `PolicyOfficer` with a `reason`, and it also arrives as a cascade from a developer termination or from an upheld policy case. Whatever the origin, the effects are identical: the listing becomes `DELISTED`; every pricing plan of that listing whose status is `ACTIVE` moves to `RETIRED`; the listing's `policy_strike_count` and the owning developer's `policy_strike_count` each increment by 1; and when the developer's resulting strike count reaches three or more while that developer is `ACTIVE`, the developer is carried `ACTIVE → SUSPENDED` with every one of that transition's own effects, including the freezing of payout lines and the recomputation of batch totals. Listings can be browsed marketplace-wide with filters on `developer_id`, on `status` and on `category`.

### 3.4. Pricing Plans and the Effective-Window Chain

A pricing plan is attached to a listing by its owner and priced in one of three monetisation models named by `kind`: `ONE_TIME`, `SUBSCRIPTION` or `IAP`. Every plan carries a `price_cents` strictly greater than zero — a tax-inclusive list price in minor units — a `currency` given as an ISO-4217 code, and a `country_code` naming the jurisdiction whose tax rules will govern purchases made against it. A plan for a country with no registered jurisdiction is rejected with `ERR_JURISDICTION_NOT_CONFIGURED`.

The `billing_period_months` field defaults to 0 and is where the three models diverge. For a `SUBSCRIPTION` plan it must be at least 1, naming the renewal period in months. For a `ONE_TIME` plan and for an `IAP` plan it must be exactly 0. Either violation — a subscription with a zero period, or a one-time or in-app-purchase plan with a non-zero one — is rejected with `ERR_INVALID_PRICING`.

Each plan occupies a closed effective window running from `effective_from` to `effective_to` inclusive, both ISO 8601 UTC instants, and `effective_from` may not be later than `effective_to`. Successive plans of the same `kind` on the same listing form a chain rather than a set: a new plan must begin at least twenty-four hours after the inclusive end of every existing plan of that `kind` on that listing that is not `RETIRED`. Exactly twenty-four hours after the prior window's end is acceptable; anything closer, or any overlap, is rejected with `ERR_PRICING_WINDOW_CONFLICT` — as is an inverted window whose start falls after its end. Plans of *different* kinds on the same listing are unconstrained relative to one another. Because creating a plan mutates the listing's `version` (and because the window chain is only meaningful against a fully observed history), plan creation is guarded by the `expected_app_version` check of §2.7.

A new plan is born `ACTIVE`. Its owner may retire it explicitly, moving `ACTIVE → RETIRED`, and delisting the parent listing retires every `ACTIVE` plan on it. A retired plan can no longer be transacted against, and a retired plan no longer blocks the effective window of a successor of the same kind. Plans may be listed per listing or marketplace-wide, filtered by `app_id`, by `kind` and by `status`.

### 3.5. Purchases: Recording, the Tax Split, and Capture

The storefront records a completed checkout by naming the `app_id` and the `pricing_plan_id` transacted on, the `buyer_country_code` of the buyer, a storefront `external_order_ref` that must be unique across all purchases, and a `line_items` array. Each element of `line_items` is an object with a `sku`, a `unit_price_cents` strictly greater than zero and a `quantity` strictly greater than zero, and at least one element must be present. A purchase may only be recorded when the listing is `LIVE` and the referenced plan's status is `ACTIVE`; otherwise the storefront receives `ERR_APP_NOT_PURCHASABLE`. The referenced plan must belong to the referenced listing, or the request is rejected with `ERR_PLAN_APP_MISMATCH`. At creation the purchase copies `developer_id` from the listing's owner and resolves `tax_jurisdiction_id` from `buyer_country_code`; if no jurisdiction is registered for that country the purchase is refused with `ERR_JURISDICTION_NOT_CONFIGURED`.

The tax split runs once, at creation, before any share calculation. Let the governing rate be the `vat_rate_bps` of the resolved jurisdiction. **The rounding order here is pinned and is part of the contract.** Working through `line_items` in the order supplied in the request body, each line's gross is its `unit_price_cents` multiplied by its `quantity`, and that line's tax is the line gross multiplied by the rate and divided by the sum of ten thousand and the rate, rounded half-up to a whole cent *at that point*. `gross_cents` is then the sum of the line grosses and `tax_cents` is the sum of the already-rounded per-line taxes. Summing the line grosses first and rounding once at the end is explicitly *not* the rule, and yields a different `tax_cents` whenever more than one line item is present. The commissionable base, `revenue_base_cents`, is `gross_cents` less `tax_cents`.

Who remits that tax follows the jurisdiction's posture. When the jurisdiction is a marketplace facilitator, `tax_remitter` is `MARKETPLACE` and `developer_tax_remittance_cents` is 0 — the marketplace keeps the tax and pays it to the authority. When it is not, `tax_remitter` is `DEVELOPER` and `developer_tax_remittance_cents` equals `tax_cents`, an amount that will later be passed through to the developer so the developer can remit it.

A purchase carries two independent status dimensions on the same record, and neither constrains the other. The money-movement dimension, `payment_status`, runs over `AUTHORIZED`, `CAPTURED`, `VOIDED`, `PARTIALLY_REFUNDED`, `REFUNDED` and `CHARGED_BACK`; the developer-ledger dimension, `settlement_status`, runs over `UNSETTLED`, `ACCRUED`, `PAID` and `CLAWED_BACK`. A purchase may be `PARTIALLY_REFUNDED` while still `ACCRUED`, or `CAPTURED` while already `PAID`. New purchases begin `AUTHORIZED` and `UNSETTLED`.

An authorised purchase may be voided by the storefront, moving `AUTHORIZED → VOIDED` on the payment dimension. `settlement_status` stays `UNSETTLED`, no ledger entry is written, and `VOIDED` is terminal for the payment dimension.

Capture is where the developer's money starts to exist. Moving `AUTHORIZED → CAPTURED` stamps `captured_at` with the current logical clock and runs the revenue share in its **provisional** variant: the tier is selected from the developer's `lifetime_revenue_base_cents` *as it stands just before this capture is folded in*, so a purchase that itself crosses a tier boundary is booked at the lower rate. The chosen rate is stored as `provisional_share_bps`; `provisional_developer_net_cents` is `revenue_base_cents` multiplied by that rate and divided by ten thousand, rounded half-up to a whole cent; and `platform_fee_cents` is `revenue_base_cents` less `provisional_developer_net_cents`. Those three figures together with `tax_cents` satisfy the per-purchase identity: platform fee plus developer net plus tax equals `gross_cents`.

Capture then moves the settlement dimension `UNSETTLED → ACCRUED`, adds this purchase's `revenue_base_cents` to the developer's `lifetime_revenue_base_cents`, and writes ledger entries. An entry of `entry_type` `ACCRUAL` is created with `amount_cents` equal to `provisional_developer_net_cents`. When `tax_remitter` is `DEVELOPER`, a second entry of `entry_type` `TAX_PASSTHROUGH` is created with `amount_cents` equal to `developer_tax_remittance_cents`. The developer's `unpaid_accrual_cents` is then recomputed from the unsettled ledger, and the risk score is recomputed. Purchases may be listed with filters on `app_id`, `pricing_plan_id`, `developer_id`, `tax_jurisdiction_id`, `payment_status` and `settlement_status`; a read of one purchase exposes both dimensions and the full computed split, including `refunded_gross_cents`, which starts at 0.

### 3.6. Refunds: Request, Decision, Execution

A refund is filed by the storefront against a captured purchase with an `amount_cents` strictly greater than zero — a tax-inclusive gross figure — and a `reason` drawn from `BUYER_REQUEST`, `FRAUD`, `POLICY` and `DUPLICATE`. Two guards apply at filing time. The purchase's `payment_status` must be `CAPTURED` or `PARTIALLY_REFUNDED`; a purchase that is `AUTHORIZED`, `VOIDED`, already fully `REFUNDED` or `CHARGED_BACK` is not refundable and the request is rejected with `ERR_PURCHASE_NOT_REFUNDABLE`. And the request must arrive while the logical clock is at or before the purchase's `captured_at` plus thirty days — exactly thirty days after capture is still in time, later is rejected with `ERR_REFUND_WINDOW_EXPIRED`. Finally, `amount_cents` may not exceed the purchase's `gross_cents` less its `refunded_gross_cents`, or the request is rejected with `ERR_REFUND_EXCEEDS_REMAINING`. A filed refund is born `REQUESTED`.

`FinanceOps` decides a requested refund with an `outcome` of `APPROVED` or `DENIED` and an optional `note`, moving it `REQUESTED → APPROVED` or `REQUESTED → DENIED` and stamping `decided_by_user_id` with the acting `X-User-ID`. `DENIED` is terminal.

Execution moves an approved refund `APPROVED → EXECUTED` and is the point at which money actually reverses. It re-checks refundability: the linked purchase's `payment_status` must still be `CAPTURED` or `PARTIALLY_REFUNDED`, or the execution is rejected with `ERR_PURCHASE_NOT_REFUNDABLE`. The reversal split then runs, and it has two branches.

The ordinary branch, taken when this refund does *not* close out the purchase, computes `tax_reversal_cents` as the refund's `amount_cents` multiplied by the jurisdiction's `vat_rate_bps` and divided by the sum of ten thousand and that rate, rounded half-up to a whole cent. The remainder of the refund after that tax portion is removed is the refund base, and `developer_net_reversal_cents` is that refund base multiplied by the purchase's `provisional_share_bps` and divided by ten thousand, rounded half-up to a whole cent.

The closing branch is a **full-refund clamp** and is taken when the purchase's `refunded_gross_cents` plus this refund's `amount_cents` exactly equals the purchase's `gross_cents`. In that case the closing refund absorbs every remaining cent rather than recomputing proportionally: `tax_reversal_cents` is the purchase's `tax_cents` less the sum of `tax_reversal_cents` over all previously executed refunds on that purchase, and `developer_net_reversal_cents` is the purchase's `provisional_developer_net_cents` less the sum of `developer_net_reversal_cents` over all previously executed refunds on that purchase. This is what makes the per-purchase ledger close at exactly zero: once the closing refund has executed, the `amount_cents` of every ledger entry attached to that purchase sums to 0, and `refunded_gross_cents` equals `gross_cents`.

Execution then raises `refunded_gross_cents` by the refund's `amount_cents` and drives the payment dimension. If the resulting `refunded_gross_cents` is still below `gross_cents`, the purchase moves `CAPTURED → PARTIALLY_REFUNDED`. If it now equals `gross_cents`, the purchase moves `CAPTURED → REFUNDED` or `PARTIALLY_REFUNDED → REFUNDED` according to where it stood. In every case a ledger entry of `entry_type` `REFUND_REVERSAL` is written whose `amount_cents` is the negative of `developer_net_reversal_cents`, the developer's `unpaid_accrual_cents` is recomputed, and the risk score is recomputed. The settlement dimension is deliberately untouched by a refund — a partially refunded purchase remains `ACCRUED` — which is the clearest demonstration that the two dimensions move independently. Refunds may be listed filtered by `purchase_id` and by `status`.

### 3.7. Chargebacks: Representment, Loss and the Compensating Reversal

An inbound network dispute is recorded by the storefront against a purchase with a `network_case_ref` that must be unique across all chargebacks and a disputed `amount_cents` strictly greater than zero. The dispute is born `RECEIVED` with `received_at` stamped from the logical clock and `clawback_cents` at 0.

`FinanceOps` may contest a received dispute by supplying an `evidence_ref`, moving it `RECEIVED → REPRESENTED`. The representment window is short: the logical clock must be strictly before `received_at` plus seven days. At exactly seven days the window has closed, and the attempt is rejected with `ERR_REPRESENTMENT_WINDOW_EXPIRED`.

Resolution records the network's verdict with an `outcome`, and is available from `RECEIVED` and from `REPRESENTED` alike. A `WON` outcome moves the dispute to `WON` and does nothing else at all — no ledger movement, and neither dimension of the purchase changes. `WON` is terminal.

A `LOST` outcome is the head of the chargeback cascade. The dispute moves to `LOST`; the purchase's `payment_status` moves to `CHARGED_BACK` from `CAPTURED` or from `PARTIALLY_REFUNDED`, and its `settlement_status` moves to `CLAWED_BACK`. The amount reversed, `clawback_cents`, is the purchase's `provisional_developer_net_cents` less the sum of `developer_net_reversal_cents` over the executed refunds already booked on that purchase, floored at 0 — so a purchase that was never refunded gives back the whole provisional net, and a purchase that was partly refunded gives back only what the developer still holds. A ledger entry of `entry_type` `CLAWBACK` is written whose `amount_cents` is the negative of `clawback_cents`. The developer's `unpaid_accrual_cents` is then recomputed from the unsettled ledger, and when that recomputation comes out negative the shortfall is moved: `negative_balance_cents` becomes the magnitude of the negative accrual, `unpaid_accrual_cents` is set to 0, and `payout_hold` is set to true. The risk score is recomputed. A dispute lost against a purchase whose `settlement_status` was already `PAID` follows the same shape on the settlement dimension, `PAID → CLAWED_BACK`, with the clawback entry written unsettled so that it drives the accrual negative and therefore the negative balance positive — the marketplace recovers money it has already paid out of future earnings.

Reversal is the compensating action, taken with a `reason` when the network overturns its own decision, and it is available only from `LOST`. The dispute moves `LOST → REVERSED`; a ledger entry of `entry_type` `CLAWBACK_REVERSAL` is written whose `amount_cents` is the positive `clawback_cents`; the purchase's `payment_status` returns to `CAPTURED` when its `refunded_gross_cents` is 0 and to `PARTIALLY_REFUNDED` otherwise; the `settlement_status` returns to `ACCRUED`; and `unpaid_accrual_cents`, `negative_balance_cents` and `payout_hold` are all recomputed from the ledger, as is the risk score with its `risk_variant`. This is the one recompute that also brings `negative_balance_cents` back down: unlike the ordinary ledger recompute of §2.9, it sets the negative balance to 0 whenever the unsettled sum no longer comes out below zero. The test of a correct reversal is arithmetic: the developer's accrual less the developer's negative balance must equal the sum of `amount_cents` over that developer's unsettled ledger entries, both before the dispute was lost and again after it has been reversed, with both sides returned to their pre-dispute values. Disputes may be listed filtered by `purchase_id` and by `status`.

### 3.8. Trust and Safety: Policy Cases, Strikes and the Takedown Cascade

A `PolicyOfficer` opens a case against a listing by naming the `app_id`, a `category` drawn from `FRAUD`, `IP_INFRINGEMENT`, `MALWARE`, `CONTENT` and `PAYMENT_ABUSE`, and a `severity` of `LOW`, `MEDIUM` or `HIGH`. The case copies `developer_id` from the listing's owner, records `opened_by_user_id` as the acting `X-User-ID`, and begins at `OPEN`.

Moving a case `OPEN → INVESTIGATING` does more than change its own state: it sets the owning developer's `risk_watch` to true and `risk_variant` to `ACCELERATED`, switching that developer's risk scoring to the thirty-day trailing window for as long as the watch stands.

An investigated case is decided with an `outcome` and a `rationale`, and — per §2.1 — the deciding officer may not be the officer who opened it. A `DISMISSED` outcome moves the case `INVESTIGATING → DISMISSED`, stamps `decided_by_user_id`, and clears `risk_watch` back to false, but only when no other policy case belonging to that developer remains in `OPEN`, `INVESTIGATING` or `APPEALED`. `DISMISSED` is terminal.

An `UPHELD` outcome moves the case `INVESTIGATING → UPHELD`, stamps `decided_by_user_id`, and fires the full takedown cascade: the linked listing is driven to `DELISTED` with every one of that transition's effects — plans retired, both strike counters incremented — and, when the developer's resulting `policy_strike_count` reaches three or more while the account is `ACTIVE`, the account is carried `ACTIVE → SUSPENDED`, which in turn holds its payouts, flips its `PAYABLE` lines in `CALCULATED` and `PENDING_APPROVAL` batches to `HELD_DEVELOPER`, and forces those batches to recompute their totals. Five records deep, in one request.

The developer may appeal an upheld case by supplying an `appeal_statement`, moving it `UPHELD → APPEALED`. Only the developer named on the case may appeal it. An appeal is decided by a `PolicyOfficer` — again never the officer who opened the case — with an `outcome` and a `rationale`. A `DENIED` appeal returns the case `APPEALED → UPHELD`, and because appeal is available again from `UPHELD`, a case may be appealed and re-upheld any number of times. A `GRANTED` appeal moves the case `APPEALED → REINSTATED` and decrements both the listing's `policy_strike_count` and the developer's `policy_strike_count` by 1, each floored at 0. The listing itself stays `DELISTED`; restoring a delisted listing is out of scope for this system. `REINSTATED` is terminal. Cases may be listed filtered by `app_id`, by `developer_id`, by `status` and by `category`.

Risk scoring runs off this same material and is recomputed at every event that could move it: a capture, a refund execution, a dispute resolution, a dispute reversal, a case entering investigation, a case decision, a developer suspension and a developer reinstatement. The scored set is that developer's purchases whose `payment_status` is `CAPTURED`, `PARTIALLY_REFUNDED`, `REFUNDED` or `CHARGED_BACK`; purchases still `AUTHORIZED` and purchases `VOIDED` never enter the score at all. When `risk_watch` is false the variant is `STANDARD` and the scored set spans every such purchase for all time, so old refunds keep depressing the score indefinitely. When `risk_watch` is true the variant is `ACCELERATED` and the scored set is additionally clipped to purchases whose `captured_at` is at or after the current logical clock minus thirty days — the same underlying data therefore yields a different score.

The denominator is the sum of `gross_cents` over the scored set. If that denominator is 0, both the refund rate and the chargeback rate are taken as 0. Otherwise the refund rate is the sum of `refunded_gross_cents` over the scored set divided by that denominator, and the chargeback rate is the sum of `gross_cents` over only those scored purchases whose `payment_status` is `CHARGED_BACK`, divided by the same denominator. The strike factor is the developer's `policy_strike_count` divided by three, capped at 1. The weighted sum is forty times the refund rate plus forty times the chargeback rate plus twenty times the strike factor; `risk_score` is that sum rounded half-up to a whole number and then capped at 100, and `risk_variant` records which variant produced it.

### 3.9. Payout Batches: Calculation, the Waterfall, Approval and Disbursement

`FinanceOps` opens a batch by naming a `payout_currency` and a half-open earnings window running from an inclusive `period_start` to an exclusive `period_end`. `period_start` must fall strictly before `period_end`, and the window may not intersect the window of any existing batch in the same currency whose status is anything other than `FAILED`. Windows that merely touch — where a previous batch's `period_end` is exactly the new batch's `period_start` — are accepted, since the half-open convention means no instant belongs to both. Any true intersection, or an inverted window, is rejected with `ERR_BATCH_PERIOD_OVERLAP`. A new batch opens at `OPEN` with `line_count`, `total_payable_cents`, `total_withholding_cents` and `total_reserve_cents` all 0.

Calculation moves the batch `OPEN → CALCULATED` and materialises one payout line per eligible developer. A developer's **eligible purchases** are those with `settlement_status` of `ACCRUED` whose `captured_at` falls at or after `period_start` and strictly before `period_end`, and whose pricing plan's `currency` equals the batch's `payout_currency`. Before the waterfall runs, the revenue share is re-evaluated in its **final** variant: for each developer, a single rate is selected once from that developer's `lifetime_revenue_base_cents` *as it stands at calculation time* — that is, after every capture in the window has already landed — and stored on the line as `final_share_bps`. Each eligible purchase's final net is its `revenue_base_cents` multiplied by `final_share_bps` and divided by ten thousand, rounded half-up to a whole cent, and `tier_trueup_cents` is the sum over the eligible purchases of that final net less the purchase's `provisional_developer_net_cents`. That sum may be negative. The provisional-versus-final contrast is the point: at capture the boundary-crossing purchase was rated at the lower tier; at calculation it and all its predecessors in the window are re-rated at the tier the developer actually reached, and the difference is booked as the true-up.

The waterfall then runs once per eligible developer, in a **pinned order**. It looks circular — withholding is a rate on what is payable, while payable is what remains after withholding — and the order below resolves it: withholding is always taken on the balance *after recovery*, never on the final payable amount.

1. `gross_earnings_cents` is the sum of the final nets over the eligible purchases, plus the sum of `developer_tax_remittance_cents` over those same purchases, minus the sum of `developer_net_reversal_cents` over the executed refunds booked against those purchases, plus the developer's current `carryover_cents`.
2. `reserve_cents` is a chargeback reserve of five percent — five hundred basis points — taken on `gross_earnings_cents` when that figure is positive and on zero when it is not, rounded half-up to a whole cent.
3. The balance after reserve is `gross_earnings_cents` less `reserve_cents`.
4. `recovery_cents` is the smaller of two quantities: the balance after reserve when that balance is positive (and zero when it is not), and the developer's `negative_balance_cents`. This is how the marketplace recovers what it is owed.
5. The balance after recovery is the balance after reserve less `recovery_cents`.
6. `withholding_cents` is 0 when the developer's `tax_id_provided` is true. Otherwise it is twenty-four percent — two thousand four hundred basis points — of the balance after recovery when that balance is positive and of zero when it is not, rounded half-up to a whole cent.
7. The payable amount is the balance after recovery less `withholding_cents`.
8. If that payable amount falls below the fifty-dollar minimum payout — five thousand cents — the line's `status` is `HELD_BELOW_MINIMUM`, its `payout_amount_cents` is 0, and its `carryover_added_cents` is the payable amount when positive and 0 when not, deferring the money into the next batch. Otherwise the line's `status` is `PAYABLE`, its `payout_amount_cents` is the payable amount, and its `carryover_added_cents` is 0. A payable amount exactly equal to five thousand cents clears the minimum and is paid.

Rounding half-up to whole cents is applied inside this waterfall at the reserve step and at the withholding step, and nowhere else. Each line records `payout_batch_id`, `developer_id` and every intermediate figure. When calculation finishes, the batch's `line_count` is the number of lines created, `total_payable_cents` is the sum of `payout_amount_cents` over lines whose status is `PAYABLE`, `total_withholding_cents` is the sum of `withholding_cents` over those same `PAYABLE` lines, and `total_reserve_cents` is the sum of `reserve_cents` over *all* lines in the batch regardless of status. When no developer is eligible, the batch still reaches `CALCULATED` with `line_count` 0 and all three totals 0.

Submission moves the batch `CALCULATED → PENDING_APPROVAL` and records `submitted_by_user_id`. Approval is reserved to `PlatformAdmin`, moves the batch `PENDING_APPROVAL → APPROVED`, and records `approved_by_user_id`. Approval is refused when any line in the batch whose status is `PAYABLE` belongs to a developer whose `payout_hold` is true, in which case the response is `ERR_DEVELOPER_PAYOUT_HELD`.

Disbursement carries an `outcome`. A `SUCCEEDED` disbursement moves the batch `APPROVED → PAID` and every `PAYABLE` line `PAYABLE → PAID`. For each paid line the system writes the ledger entries the waterfall produced — of `entry_type` `PAYOUT`, `RESERVE`, `RECOVERY`, `WITHHOLDING` and `CARRYOVER` — marks every swept ledger entry with `settled` true and its `payout_line_id` set to the paying line, and moves each swept purchase `ACCRUED → PAID` on its settlement dimension. The developer's `negative_balance_cents` is reduced by the line's `recovery_cents`, and the developer's `carryover_cents` is set from the line's `carryover_added_cents`. A `FAILED` disbursement instead moves the batch `APPROVED → FAILED`, stores the supplied `failure_reason`, and moves every `PAYABLE` line `PAYABLE → FAILED`; no ledger entry is created and no purchase's settlement dimension moves. Retry brings a failed batch back, `FAILED → PENDING_APPROVAL`, clearing `failure_reason` and returning every `FAILED` line `FAILED → PAYABLE` for a second approval and disbursement attempt. Batches may be listed filtered by `status` and by `payout_currency`; lines may be listed per batch filtered by `status`, or across batches filtered by `payout_batch_id`, by `developer_id` and by `status`.

### 3.10. Reading the Ledger, App Analytics and the Annual Form

Every ledger entry is an append-only record carrying the `developer_id` whose balance it moves, a `purchase_id` that is null for entries not tied to a purchase, a `payout_line_id` that stays null until the entry is swept into a payout, an `entry_type` drawn from `ACCRUAL`, `TAX_PASSTHROUGH`, `TIER_TRUEUP`, `REFUND_REVERSAL`, `CLAWBACK`, `CLAWBACK_REVERSAL`, `RESERVE`, `RECOVERY`, `WITHHOLDING`, `PAYOUT` and `CARRYOVER`, a signed `amount_cents` where a positive value credits the developer and a negative value debits, a `settled` flag that is false until the entry has been swept into a paid line, and a short human-readable `memo`. Entries may be read individually, listed marketplace-wide or listed for a single developer, filtered by `developer_id`, `purchase_id`, `payout_line_id`, `entry_type` and `settled`.

A listing's sales roll-up is computed on demand from that listing's purchases whose `payment_status` is `CAPTURED`, `PARTIALLY_REFUNDED`, `REFUNDED` or `CHARGED_BACK`; purchases still `AUTHORIZED` and purchases `VOIDED` are excluded. The roll-up reports the `app_id` alongside `gross_cents`, `tax_cents`, `revenue_base_cents` and `refunded_gross_cents` as the sums of the like-named purchase fields, `developer_net_cents` as the sum of `provisional_developer_net_cents`, `unit_count` as the total of `quantity` across every line item of every scored purchase, and `refund_rate_bps` as the summed `refunded_gross_cents` multiplied by ten thousand and divided by the summed `gross_cents`, rounded half-up to a whole number. When the summed `gross_cents` is 0 the refund rate is reported as 0 rather than raising a division error, so a listing with no captured purchase yields every field 0.

The annual form is generated by a `PlatformAdmin` naming a `developer_id` and a `tax_year`, and at most one form may exist per developer and year — a second attempt is rejected with `ERR_TAX_FORM_EXISTS`. The roll-up considers only that developer's payout lines whose status is `PAID` and whose owning batch's `period_start` falls within the named `tax_year` as a UTC calendar year; lines that are `PAYABLE`, `HELD_BELOW_MINIMUM`, `HELD_DEVELOPER` or `FAILED` are excluded entirely. `reportable_cents` is the sum over those lines of `payout_amount_cents` plus `withholding_cents` — the gross reportable payout before backup withholding was taken — and `withheld_cents` is the sum of `withholding_cents` alone. `threshold_cents` records the six-hundred-dollar reporting threshold applied, that is, sixty thousand cents. The form's `status` is `ISSUABLE` when `reportable_cents` is greater than or equal to that threshold — exactly sixty thousand cents is issuable — and `NOT_REQUIRED` otherwise. Forms may be listed filtered by `developer_id`, by `tax_year` and by `status`.

## 4. Endpoint Definitions

Every path below is mounted on the running server exactly as written. Creating a new resource returns HTTP 201; every other successful operation, including state transitions and computed reads, returns HTTP 200. Request and response payloads are not restated here — they are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/api/tax-jurisdictions` | Register a country's VAT rate and facilitator posture | PlatformAdmin |
| GET | `/api/tax-jurisdictions` | List configured tax jurisdictions | PlatformAdmin, FinanceOps, StorefrontService |
| GET | `/api/tax-jurisdictions/{tax_jurisdiction_id}` | Read one tax jurisdiction | PlatformAdmin, FinanceOps, StorefrontService |
| POST | `/api/revenue-share-tiers` | Register a revenue-share tier breakpoint | PlatformAdmin |
| GET | `/api/revenue-share-tiers` | List revenue-share tiers | PlatformAdmin, FinanceOps, Developer |
| GET | `/api/revenue-share-tiers/{revenue_share_tier_id}` | Read one revenue-share tier | PlatformAdmin, FinanceOps, Developer |
| POST | `/api/developers` | Open a developer account | PlatformAdmin |
| GET | `/api/developers` | List developer accounts | PlatformAdmin, FinanceOps, PolicyOfficer |
| GET | `/api/developers/{developer_id}` | Read one developer account with risk and ledger roll-ups | PlatformAdmin, FinanceOps, PolicyOfficer, Developer |
| POST | `/api/developers/{developer_id}/verify` | Verify a pending account | PlatformAdmin |
| POST | `/api/developers/{developer_id}/suspend` | Suspend a developer account | PolicyOfficer |
| POST | `/api/developers/{developer_id}/reinstate` | Return a suspended account to active | PolicyOfficer |
| POST | `/api/developers/{developer_id}/terminate` | Terminate an account and delist its listings | PlatformAdmin |
| POST | `/api/developers/{developer_id}/payout-holds` | Set or clear the payout hold under optimistic concurrency | FinanceOps |
| POST | `/api/developers/{developer_id}/tax-profile` | Record the outcome of a tax-identity check | PlatformAdmin |
| GET | `/api/developers/{developer_id}/summary` | Computed ledger position and risk posture | PlatformAdmin, FinanceOps, Developer |
| POST | `/api/apps` | Create a draft app listing | Developer |
| GET | `/api/apps` | List app listings | Developer, ReviewAgent, PolicyOfficer, PlatformAdmin, FinanceOps, StorefrontService |
| GET | `/api/apps/{app_id}` | Read one app listing | Developer, ReviewAgent, PolicyOfficer, PlatformAdmin, FinanceOps, StorefrontService |
| PATCH | `/api/apps/{app_id}` | Edit listing metadata | Developer |
| POST | `/api/apps/{app_id}/submit-for-review` | Open a new review round on a listing | Developer |
| POST | `/api/apps/{app_id}/publish` | Publish an approved listing | Developer |
| POST | `/api/apps/{app_id}/suspend` | Suspend a live listing | PolicyOfficer |
| POST | `/api/apps/{app_id}/reinstate` | Return a suspended listing to live | PolicyOfficer |
| POST | `/api/apps/{app_id}/delist` | Permanently delist a listing | PolicyOfficer |
| GET | `/api/apps/{app_id}/analytics` | Computed sales roll-up for a listing | Developer, PlatformAdmin, FinanceOps |
| GET | `/api/apps/{app_id}/review-submissions` | List the review rounds opened against a listing | Developer, ReviewAgent, PolicyOfficer, PlatformAdmin |
| GET | `/api/apps/{app_id}/pricing-plans` | List the pricing plans of a listing | Developer, ReviewAgent, PlatformAdmin, FinanceOps, StorefrontService |
| POST | `/api/apps/{app_id}/pricing-plans` | Attach a pricing plan to a listing | Developer |
| GET | `/api/review-submissions` | List review submissions | ReviewAgent, PolicyOfficer, PlatformAdmin, Developer |
| GET | `/api/review-submissions/{review_submission_id}` | Read one review submission | ReviewAgent, PolicyOfficer, PlatformAdmin, Developer |
| POST | `/api/review-submissions/{review_submission_id}/triage` | Claim a submitted round for triage | ReviewAgent |
| POST | `/api/review-submissions/{review_submission_id}/decision` | Record the review outcome | ReviewAgent |
| GET | `/api/pricing-plans` | List pricing plans across listings | Developer, PlatformAdmin, FinanceOps, StorefrontService |
| GET | `/api/pricing-plans/{pricing_plan_id}` | Read one pricing plan | Developer, PlatformAdmin, FinanceOps, StorefrontService |
| POST | `/api/pricing-plans/{pricing_plan_id}/retire` | Retire an active pricing plan | Developer |
| POST | `/api/purchases` | Record a storefront purchase and compute the tax split | StorefrontService |
| GET | `/api/purchases` | List purchases | StorefrontService, PlatformAdmin, FinanceOps, Developer |
| GET | `/api/purchases/{purchase_id}` | Read one purchase with both status dimensions | StorefrontService, PlatformAdmin, FinanceOps, Developer |
| POST | `/api/purchases/{purchase_id}/capture` | Capture an authorized purchase | StorefrontService |
| POST | `/api/purchases/{purchase_id}/void` | Void an authorized purchase before capture | StorefrontService |
| POST | `/api/purchases/{purchase_id}/refunds` | Request a refund against a captured purchase | StorefrontService |
| GET | `/api/refunds` | List refunds | StorefrontService, FinanceOps, PlatformAdmin, Developer |
| GET | `/api/refunds/{refund_id}` | Read one refund | StorefrontService, FinanceOps, PlatformAdmin, Developer |
| POST | `/api/refunds/{refund_id}/decide` | Approve or deny a requested refund | FinanceOps |
| POST | `/api/refunds/{refund_id}/execute` | Execute an approved refund | FinanceOps |
| POST | `/api/purchases/{purchase_id}/chargebacks` | Record an inbound network dispute | StorefrontService |
| GET | `/api/chargebacks` | List chargebacks | StorefrontService, FinanceOps, PlatformAdmin, Developer |
| GET | `/api/chargebacks/{chargeback_id}` | Read one chargeback | StorefrontService, FinanceOps, PlatformAdmin, Developer |
| POST | `/api/chargebacks/{chargeback_id}/represent` | Contest a received dispute | FinanceOps |
| POST | `/api/chargebacks/{chargeback_id}/resolve` | Record the network's decision | FinanceOps |
| POST | `/api/chargebacks/{chargeback_id}/reverse` | Credit back a reversed clawback | FinanceOps |
| POST | `/api/policy-cases` | Open a policy or fraud case against a listing | PolicyOfficer |
| GET | `/api/policy-cases` | List policy cases | PolicyOfficer, PlatformAdmin, Developer |
| GET | `/api/policy-cases/{policy_case_id}` | Read one policy case | PolicyOfficer, PlatformAdmin, Developer |
| POST | `/api/policy-cases/{policy_case_id}/investigate` | Move an open case into investigation | PolicyOfficer |
| POST | `/api/policy-cases/{policy_case_id}/decide` | Decide an investigated case | PolicyOfficer |
| POST | `/api/policy-cases/{policy_case_id}/appeal` | Appeal an upheld case | Developer |
| POST | `/api/policy-cases/{policy_case_id}/appeal-decision` | Decide an appeal | PolicyOfficer |
| POST | `/api/payout-batches` | Open a payout batch for a currency and window | FinanceOps |
| GET | `/api/payout-batches` | List payout batches | FinanceOps, PlatformAdmin |
| GET | `/api/payout-batches/{payout_batch_id}` | Read one payout batch with its totals | FinanceOps, PlatformAdmin |
| POST | `/api/payout-batches/{payout_batch_id}/calculate` | Run the final share and the payout waterfall | FinanceOps |
| POST | `/api/payout-batches/{payout_batch_id}/submit` | Submit a calculated batch for approval | FinanceOps |
| POST | `/api/payout-batches/{payout_batch_id}/approve` | Approve a submitted batch | PlatformAdmin |
| POST | `/api/payout-batches/{payout_batch_id}/pay` | Disburse an approved batch | FinanceOps |
| POST | `/api/payout-batches/{payout_batch_id}/retry` | Return a failed batch for another attempt | FinanceOps |
| GET | `/api/payout-batches/{payout_batch_id}/lines` | List the lines materialised for a batch | FinanceOps, PlatformAdmin |
| GET | `/api/payout-lines` | List payout lines across batches | FinanceOps, PlatformAdmin, Developer |
| GET | `/api/payout-lines/{payout_line_id}` | Read one payout line with every waterfall step | FinanceOps, PlatformAdmin, Developer |
| GET | `/api/ledger-entries` | List ledger entries | FinanceOps, PlatformAdmin, Developer |
| GET | `/api/ledger-entries/{ledger_entry_id}` | Read one ledger entry | FinanceOps, PlatformAdmin, Developer |
| GET | `/api/developers/{developer_id}/ledger-entries` | List a developer's ledger entries | FinanceOps, PlatformAdmin, Developer |
| POST | `/api/tax-forms` | Generate the annual 1099 roll-up for a developer | PlatformAdmin |
| GET | `/api/tax-forms` | List generated 1099 forms | PlatformAdmin, FinanceOps, Developer |
| GET | `/api/tax-forms/{tax_form_id}` | Read one 1099 form | PlatformAdmin, FinanceOps, Developer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DEVELOPER_NOT_FOUND` | 404 |
| `ERR_APP_NOT_FOUND` | 404 |
| `ERR_REVIEW_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_PRICING_PLAN_NOT_FOUND` | 404 |
| `ERR_TAX_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_REVENUE_SHARE_TIER_NOT_FOUND` | 404 |
| `ERR_PURCHASE_NOT_FOUND` | 404 |
| `ERR_REFUND_NOT_FOUND` | 404 |
| `ERR_CHARGEBACK_NOT_FOUND` | 404 |
| `ERR_POLICY_CASE_NOT_FOUND` | 404 |
| `ERR_PAYOUT_BATCH_NOT_FOUND` | 404 |
| `ERR_PAYOUT_LINE_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_TAX_FORM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_STALE_APP_VERSION` | 412 |
| `ERR_STALE_DEVELOPER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEVELOPER_NOT_ACTIVE` | 409 |
| `ERR_PURCHASE_NOT_REFUNDABLE` | 409 |
| `ERR_APP_NOT_PURCHASABLE` | 409 |
| `ERR_DEVELOPER_PAYOUT_HELD` | 409 |
| `ERR_PRICING_WINDOW_CONFLICT` | 409 |
| `ERR_BATCH_PERIOD_OVERLAP` | 409 |
| `ERR_TAX_FORM_EXISTS` | 409 |
| `ERR_JURISDICTION_EXISTS` | 409 |
| `ERR_JURISDICTION_NOT_CONFIGURED` | 422 |
| `ERR_PLAN_APP_MISMATCH` | 422 |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 |
| `ERR_REPRESENTMENT_WINDOW_EXPIRED` | 422 |
| `ERR_REFUND_EXCEEDS_REMAINING` | 422 |
| `ERR_INVALID_PRICING` | 422 |
| `ERR_TAX_ID_REQUIRED` | 422 |
