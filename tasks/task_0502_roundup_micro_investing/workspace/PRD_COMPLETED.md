# Round-Up Micro-Investing & Robo-Advisor API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a round-up micro-investing and robo-advisory platform in the spirit of consumer apps such as Acorns and Stash. The product turns everyday card spending into investment principal: each purchase on a linked funding card generates a small round-up to the next whole dollar, optionally amplified by a per-card multiplier, and those round-ups accumulate until a sweep moves them into investable cash. On top of that core loop, the platform layers recurring scheduled contributions, brand-funded "found money" rebates, a referral bonus program, and a robo-advisor that allocates each account's holdings into a risk-tiered model portfolio and flags drift when the holdings wander too far from target.

The system is, at heart, a ledger-reconciliation engine wrapped around a pricing engine. Money flows through cash buffers, tax lots, and a transaction ledger that must reconcile exactly — credits and debits are conserved, derived balances are recomputed from their underlying rows rather than tracked independently, and every fee and rebate is computed by a pinned, deterministic rule. Accounts evolve along two independent dimensions at once: an identity/compliance dimension (KYC) that gates investing, and a billing dimension that governs subscription charges. Investments are organized into tax-advantaged and taxable buckets — including custodial (UTMA) and retirement (IRA) buckets with their own eligibility and contribution-cap rules — and withdrawals consume tax lots under a selectable lot-selection method that determines realized gains.

Because real-world correctness here depends on ordering, thresholds, and conservation, this specification is precise about evaluation order, rounding direction, boundary inclusivity, and the exact state under which each operation is permitted. Implementers should treat every threshold and every cascade described below as load-bearing.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. The flat resource topology means each entity owns a top-level collection (for example, accounts, buckets, orders, and tax lots each live under their own root path); there is no single shared resource prefix, and the API is mounted at the server root.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Investor`, `CustodialGuardian`, and `PlatformAdmin`.

If the `X-User-Role` header (or the `X-User-ID` header) is absent on a protected endpoint, the request is rejected with `ERR_MISSING_AUTH`. Both headers are in fact required on every endpoint, including those a present role token allows for all four roles: `X-User-Role` must be present and must be one of the four recognized roles, and `X-User-ID` must be non-empty for whichever role is declared (including `Anonymous` and `PlatformAdmin`, whose ids are opaque). This authentication check is the highest-priority guard and runs before anything else. There is no truly header-free public surface: account registration still requires the `Anonymous` role token (and its opaque `X-User-ID`), and the configuration reads still require one of `PlatformAdmin`, `Investor`, or `CustodialGuardian` — so a header-less or unrecognized-role caller is rejected with `ERR_MISSING_AUTH`, and a header-present caller whose role is not on the endpoint's allowed list is rejected with `ERR_FORBIDDEN_ROLE`. If the headers are present but the declared role is not permitted to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity ties `X-User-ID` to resource ownership as follows. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. When `X-User-Role` is `CustodialGuardian`, `X-User-ID` is likewise the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`, and a guardian's reach is additionally narrowed to custodial (UTMA) buckets as described later. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the only thing an anonymous caller may do is register a new account or read public configuration. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept it for audit purposes but never compares it to any entity's `id`.

When an `Investor` or `CustodialGuardian` acts on a resource, that caller must own the owning `Account` — that is, the resource's owning-account identifier must equal `X-User-ID`. A caller who is otherwise authenticated and role-permitted but is acting on an account they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside the inclusive range from 1 to 100, or whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every entity carries a server-minted `id`: a UUID with no type prefix, used purely as identity. Every entity also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation. In this domain, every entity additionally carries an `updated_at` (an ISO 8601 UTC timestamp, refreshed on any mutation) and a `version` (an integer that starts at its initial value and increments by one on every mutation of the resource). All entities in this system expose all four of these system fields; none are version-free.

The `version` field is also the substrate for optimistic concurrency control, described in §2.8. Whenever a transition's side effects mention incrementing an entity's `version`, that increment is in addition to refreshing `updated_at`. Derived/computed fields are recomputed in place rather than stored independently of their sources; recomputing a derived balance on an entity is itself a mutation that refreshes `updated_at` and increments `version` on the entity that owns the balance — and, for a bucket's computed views, only when at least one of the recomputed values actually changes. One carve-out applies: an account's `pending_roundup_cents`, although derived, is recomputed in place without bumping the owning account's `version` or `updated_at`; the account version advances solely through the explicit Account transitions enumerated in §3.2 and §3.5 (verify-kyc, restrict, charge-subscription, mark-past-due, sweep, close), so creating or cancelling a round-up accrual leaves the account version unchanged.

### 2.5. Monetary Representation, Precision, and Rounding

All monetary and rate quantities in this system are integers expressed in whole cents (and, for fee and drift rates, in basis points). There are no floating-point currency values anywhere in the API. Where a calculation divides — for instance, applying a basis-point fee or prorating a half-month subscription — the rounding direction is specified explicitly per calculation in §3 and must be followed exactly. Two directions appear in this system: flooring (truncating toward zero for non-negative operands), used for fee withholding, percentage rebates, market-value derivation, and per-asset weight; and ceiling (rounding up to the next whole cent), used only for the first-cycle subscription proration. Round-up amounts use modular arithmetic and require no rounding. Because every quantity is already an integer number of cents or basis points, there is no separate two-decimal display rule; values are returned as integers.

### 2.6. The Conservation Principle for Cash and Ledger

Cash on an account is conserved through a `CashTransaction` ledger. When the platform credits or debits an account's cash, it may record a corresponding `CashTransaction` whose signed `amount_cents` (positive for credits, negative for debits) matches the change applied to `cash_balance_cents`, and whose `tx_type` names the economic event — drawn from the catalogue `SUBSCRIPTION_FEE`, `MANAGEMENT_FEE`, `REFERRAL_BONUS`, `FOUND_MONEY`, `WITHDRAW_PROCEEDS`, `SWEEP_DEBIT`, or `CONTRIBUTION_DEPOSIT`. In practice, ledger rows are written only by the four flows that §3 explicitly enumerates a row for: the subscription charge (`SUBSCRIPTION_FEE`, negative), referral qualification (one `REFERRAL_BONUS` per side, positive), found-money confirmation (`FOUND_MONEY`, positive), and withdraw settlement (`WITHDRAW_PROCEEDS`, positive). The remaining catalogue values are reserved and currently unused: an invest settlement's cash debit and a sweep's cash credit adjust `cash_balance_cents` directly without writing any ledger row, so no `MANAGEMENT_FEE`, `SWEEP_DEBIT`, or `CONTRIBUTION_DEPOSIT` row is ever produced. A ledger row carries a `status` of `PENDING`, `CONFIRMED`, or `VOID`; every row written by the settlement and billing flows described in §3 is created already `CONFIRMED`. An account's `cash_balance_cents` is the settled, un-invested cash buffer; it is never allowed to go negative, and any operation that would drive it below zero is instead floored at zero with the shortfall recorded as described in §3.

Three account balances are derived and must be kept reconciled with their underlying rows rather than tracked free-hand: `pending_roundup_cents` always equals the sum of `effective_amount_cents` over the account's round-up accruals that are still in `PENDING` status; `lifetime_invested_cents` is the cumulative settled invest-order principal across all of the account's buckets; and `referral_credits_cents` is the cumulative referral bonus cash granted to the account, which is itself folded into `cash_balance_cents`. The account also tracks `months_billed`, the count of confirmed subscription-fee charges.

### 2.7. KYC Compliance Gate and Plan Entitlements

Investing is gated on identity verification. An account's `kyc_status` is one of `PENDING_KYC`, `VERIFIED`, or `RESTRICTED`. Three operations require the owning account to be `VERIFIED`: submitting an invest order, running a sweep, and confirming a found-money reward. Any of these attempted while the account is not `VERIFIED` is rejected with `ERR_KYC_NOT_VERIFIED`.

A subscription plan governs what an account may do. Each `SubscriptionPlan` carries a `tier` (`LITE`, `PERSONAL`, or `FAMILY`), a flat `monthly_fee_cents`, two capability flags `allows_custodial` and `allows_ira`, and a `management_fee_bps` charged on invested principal. A `ModelPortfolio` carries a `risk_tier` from 1 (conservative) to 5 (aggressive). These entitlements surface at bucket-opening time: a bucket whose type the account's plan does not permit is refused with `ERR_BUCKET_NOT_ALLOWED_BY_PLAN`, as detailed in §3.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a fresh view of a parent entity by echoing that parent's last-observed `version`. These are the only two endpoints in the system that take a version field; every other endpoint omits it entirely and performs no OCC check.

First, submitting an order requires `expected_bucket_version` in the request body, carrying the client's last observed `version` of the target `Bucket`. If the bucket's current `version` has advanced beyond that value — because a prior submit, settle, or freeze on the same bucket legitimately bumped it — the submit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a bucket whose state it has not observed.

Second, running a sweep requires `expected_account_version` in the request body, carrying the client's last observed `version` of the target `Account`. If the account's current `version` has advanced beyond that value — because a prior sweep or subscription charge mutated `cash_balance_cents` and bumped the account version — the sweep is rejected with `ERR_STALE_VERSION` (HTTP 412), so the caller cannot sweep against a stale view of available cash. In both cases the rule is a stale-version guard: the supplied expected version must equal the parent's live `version`, and any mismatch is the rejection condition.

### 2.9. Validation Ordering and Nested Resolution

When several checks could fire on a single request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. The order is: first, presence of the authentication headers (`ERR_MISSING_AUTH`); second, that the role is permitted for the endpoint (`ERR_FORBIDDEN_ROLE`); third, resource ownership for owner-scoped writes (`ERR_NOT_RESOURCE_OWNER`); fourth, existence of every referenced id, resolved left-to-right through the path and then the body so the first unresolved id reported is `ERR_NOT_FOUND`; fifth, structural validity of the body — required fields present, correctly typed, and enums within their domain (`ERR_INVALID_REQUEST`); sixth, pagination bounds on list endpoints (`ERR_INVALID_PAGINATION`); seventh, that the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`). Domain-specific business rules — bucket-type permission, the KYC gate, plan entitlements, temporal windows, fiscal sufficiency, and the like — are evaluated after these structural guards, and the optimistic-concurrency stale-version check sits among them as a state-category guard. Where one endpoint is subject to several business rules, the per-endpoint ordering is called out in the relevant §3 narrative.

### 2.10. The Logical Clock

Time in this system is a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and until an explicit set call moves it, it stays at that default and never falls back to wall-clock. A `PlatformAdmin` may advance the clock to a supplied instant by passing `to_iso8601`. Every time-sensitive computation in the system — a found-money reward's `eligible_at`, a recurring contribution's `next_run_at`, the lot acquisition timestamp `acquired_at`, and the referral redemption window — reads this logical clock.

## 3. Business Logic & Workflows

### 3.1. Platform Configuration: Plans, Portfolios, and Offers

Before investors arrive, a `PlatformAdmin` seeds the catalog. A subscription plan is created by supplying its `tier`, `monthly_fee_cents`, `allows_custodial`, `allows_ira`, and `management_fee_bps`; the `monthly_fee_cents` must be zero or greater, and `management_fee_bps` lies between 0 and 100 inclusive. Each tier is unique — there is exactly one plan row per `tier` value — and attempting to create a second plan for an already-used tier is rejected with `ERR_DUPLICATE_TIER`. A plan begins life with `status` of `ACTIVE` and may later be `RETIRED`.

A model portfolio is created with a `risk_tier`, a human-readable `name`, a `target_allocation`, and a `drift_band_bps`. The `risk_tier` is an integer from 1 to 5 and is unique across portfolios; a duplicate `risk_tier` is rejected with `ERR_DUPLICATE_TIER`. The `target_allocation` is a map from asset class to an integer target weight expressed as a whole percent, and those weights must sum to exactly 100; any other sum is rejected with `ERR_ALLOCATION_SUM`. The `drift_band_bps` is the per-asset drift tolerance, in basis points, that the holdings may stray from target before a rebalance is flagged, and it must be zero or greater. A portfolio also begins `ACTIVE` and may be `RETIRED`.

A found-money offer ties a partner brand rebate to an active window. It is created with a `brand_name`, a `rebate_mode` of either `PERCENT` or `FLAT`, a `max_rebate_cents`, a `min_spend_cents`, a `hold_days`, an `active_from`, and an `active_until`. When `rebate_mode` is `PERCENT`, the offer must carry a `rebate_percent_bps` (the rebate rate in basis points of qualifying spend, between 0 and 10000 inclusive); when `rebate_mode` is `FLAT`, it must carry a `rebate_flat_cents` (a fixed rebate amount, zero or greater). The `max_rebate_cents` caps percent-mode rewards and is zero or greater; `min_spend_cents` is the minimum qualifying spend, zero or greater; and `hold_days` is the number of days, zero or greater, a reward stays pending before it may be confirmed. The active window is half-open: `active_from` is inclusive, `active_until` is exclusive, and `active_until` must be strictly greater than `active_from`. A new offer's window must not overlap the window of any existing `ACTIVE` offer of the same `brand_name`; because the interval is half-open, two windows that merely touch at a boundary — where one offer's `active_until` equals another's `active_from` — do not overlap and are allowed, but any genuine overlap is rejected with `ERR_OFFER_WINDOW_OVERLAP`. An offer carries a `status` of `ACTIVE` or `PAUSED`, beginning `ACTIVE`.

### 3.2. Account Registration and the Two-Dimensional Lifecycle

An anonymous caller registers an account by supplying an `email`, a `full_name`, a `plan_id`, a `model_portfolio_id`, and optionally a `sweep_threshold_cents`. The `email` must be unique across accounts; a registration whose `email` duplicates an existing account's is rejected with `ERR_INVALID_REQUEST`. The referenced `plan_id` and `model_portfolio_id` must resolve to existing entities, and an unresolved id is reported as `ERR_NOT_FOUND`. The `sweep_threshold_cents` is the cash-buffer level at or above which a sweep will auto-invest; it must be at least 100 cents and, when omitted, defaults to 500 cents. A freshly registered account starts with `kyc_status` of `PENDING_KYC`, `billing_status` of `TRIAL`, and `cash_balance_cents` of zero. Its derived balances — `pending_roundup_cents`, `lifetime_invested_cents`, and `referral_credits_cents` — start at zero, and `months_billed` starts at zero.

An account evolves along two independent dimensions. The first is the identity dimension carried by `kyc_status`. A `PlatformAdmin` marks an account verified, moving it from `PENDING_KYC` to `VERIFIED`; this is permitted only while the account is currently `PENDING_KYC`, and it bumps the account version. A `PlatformAdmin` may instead restrict an account, moving it to `RESTRICTED` from either `PENDING_KYC` or `VERIFIED`. Restricting an account cascades downward: every bucket of that account whose `status` is `OPEN` is set to `FROZEN`, and the account version is bumped. `RESTRICTED` is terminal for the identity dimension.

The second dimension is the billing dimension carried by `billing_status`, which is independent of `kyc_status` and may be `TRIAL`, `ACTIVE`, `PAST_DUE`, or `CLOSED`. Charging the monthly subscription fee is a `PlatformAdmin` action permitted when the account is `TRIAL` or `ACTIVE`; it advances `billing_status` to `ACTIVE` (a `TRIAL` account becomes `ACTIVE`; an `ACTIVE` account stays `ACTIVE`). The charge runs the subscription-fee computation described in §3.3, writes a confirmed subscription-fee ledger row, debits cash by the computed fee, increments `months_billed` by one, and bumps the account version. A separate `PlatformAdmin` action marks an `ACTIVE` account `PAST_DUE`; this is permitted only when the account is currently `ACTIVE` and its `cash_balance_cents` is strictly less than the plan's `monthly_fee_cents`, and it bumps the account version. Charging the subscription fee against a `PAST_DUE` account brings it back to `ACTIVE`, but only when the account is currently `PAST_DUE` and its `cash_balance_cents` is at least the plan's `monthly_fee_cents`; that charge likewise runs the fee computation, writes the ledger row, debits cash, increments `months_billed`, and bumps the version.

Closing an account is an `Investor` action. It is permitted from `TRIAL`, `ACTIVE`, or `PAST_DUE`, and only when every bucket of the account is already `CLOSED`; an attempt to close while any bucket is not `CLOSED` is rejected with `ERR_ACCOUNT_HAS_OPEN_BUCKETS`. Closing moves `billing_status` to the terminal `CLOSED` state, cascades down by setting every recurring contribution of the account whose `status` is `ACTIVE` to `CANCELLED`, and bumps the account version.

### 3.3. Subscription Billing Mechanics

The subscription fee charged on a billing transition is not always the full plan fee. The computation reads the account's `months_billed` before it is incremented and branches on whether this is the account's first-ever charge. In the steady-state variant — applicable whenever `months_billed` is at least 1 — the fee equals the plan's full `monthly_fee_cents`. In the first-cycle variant — applicable exactly when `months_billed` is 0, that is, on the first charge leaving `TRIAL` — the fee is a half-month proration: the plan's `monthly_fee_cents` multiplied by one and divided by two, rounded up to the next whole cent. Because the transition back from `PAST_DUE` to `ACTIVE` only ever happens after at least one prior charge, that path always uses the full fee.

The fee, once computed, drives the side effects uniformly: a `CashTransaction` of type `SUBSCRIPTION_FEE` is created with a negative `amount_cents` equal to the fee, the account's `cash_balance_cents` is debited by that fee (floored at zero, with any shortfall recorded rather than driving the balance negative), `months_billed` is incremented by one, and the account version is bumped.

### 3.4. Linked Cards and the Round-Up Engine

An `Investor` links a funding card by supplying the owning `account_id`, the card's `last_four`, and optionally a `roundup_multiplier`. The multiplier must be one of 1, 2, 3, or 10; supplying any other value is rejected with `ERR_INVALID_MULTIPLIER`, and when omitted the multiplier defaults to 1. A card carries a `status` of `LINKED`, `PAUSED`, or `UNLINKED`, beginning `LINKED`. The same investor may later update a card's `roundup_multiplier` or its `status`; changing the multiplier to a value outside the permitted set is again rejected with `ERR_INVALID_MULTIPLIER`.

A round-up accrual records the round-up generated by a single card purchase. An `Investor` creates one by supplying the owning `account_id`, the `linked_card_id` whose transaction generated the round-up, and the raw `purchase_amount_cents`, which must be at least 1. The system then computes two frozen amounts. The `base_roundup_cents` is the number of cents needed to reach the next whole dollar: it is 100 minus the purchase amount's remainder when divided by 100, with that result itself taken modulo 100 — so a purchase that is already an exact multiple of 100 cents (a whole-dollar purchase) yields a `base_roundup_cents` of 0. The `effective_amount_cents` is the `base_roundup_cents` multiplied by the multiplier read from the referenced card at accrual time; for a whole-dollar purchase the base is 0, so the effective amount is 0 regardless of the multiplier. Both values are captured once at creation and frozen on the accrual row. Creating the accrual increases the owning account's `pending_roundup_cents` by the new `effective_amount_cents`. A fresh accrual starts in `PENDING` status.

A `PENDING` accrual can leave that state in one of two ways. An `Investor` may cancel it — permitted only while it is `PENDING` — which moves it to the terminal `CANCELLED` state and decrements the account's `pending_roundup_cents` by that accrual's `effective_amount_cents` (a derived recompute). Alternatively the accrual is consumed by a sweep, as described next.

### 3.5. Sweeping Round-Ups and Threshold Auto-Invest

A sweep collects an account's pending round-ups into cash and, when the buffer is full enough, automatically invests it. The sweep is invokable by either a `PlatformAdmin` or the owning `Investor`, requires the owning account to be `VERIFIED` (otherwise `ERR_KYC_NOT_VERIFIED`), and — per §2.8 — carries `expected_account_version` for the optimistic-concurrency check.

The computation proceeds in two pinned steps. In the gather step, the system takes every round-up accrual of the account currently in `PENDING` status, sums their already-frozen `effective_amount_cents`, sets each of those accruals to the terminal `SWEPT` status, and credits the account's `cash_balance_cents` by that swept total. The rounding order here is deliberate and load-bearing: the swept total is the sum of each accrual's individually-frozen effective amount — round-per-accrual at accrual time, then sum at sweep time — and the system must not re-derive the total from raw purchase amounts and round once. Each accrual that moves to `SWEPT` correspondingly reduces the account's `pending_roundup_cents` by its `effective_amount_cents`.

In the threshold step, the system compares the account's post-sweep `cash_balance_cents` against its `sweep_threshold_cents`. If the post-sweep cash is at or above the threshold — the comparison is inclusive at the threshold — the system auto-creates and immediately settles an invest order, with `source` of `SWEEP`, into the account's primary taxable bucket for an amount equal to the entire post-sweep cash balance, running it through the invest-settlement described in §3.7. The "primary taxable bucket" is the account's earliest-created bucket whose `bucket_type` is `TAXABLE` and whose `status` is `OPEN` (earliest by creation order). The auto-invest order is created directly in `SUBMITTED` status and immediately driven to `SETTLED`, bypassing the draft/submit/OCC path; like any invest settlement it withholds the management fee, opens a tax lot, debits the full gross from cash, and adds the net principal to `lifetime_invested_cents`. If the post-sweep cash is below the threshold, or if the account has no OPEN `TAXABLE` bucket to invest into, the cash is swept but no invest order is created and the cash simply sits in the buffer. Running a sweep bumps the account version exactly once, regardless of whether any accruals were pending or whether an auto-invest fired.

### 3.6. Buckets: Taxable, Custodial, and Retirement

A bucket is an investing container of one of three types: `TAXABLE`, `UTMA`, or `IRA`. An `Investor` opens taxable and retirement buckets; a `CustodialGuardian` opens custodial buckets. A bucket is created by supplying the owning `account_id`, a `bucket_type`, and, for custodial buckets, a `beneficiary_name` naming the minor beneficiary. A UTMA bucket created without a `beneficiary_name` is rejected with `ERR_BENEFICIARY_REQUIRED`. Plan entitlements gate creation: opening a `UTMA` bucket requires the account's plan to set `allows_custodial`, and opening an `IRA` bucket requires the plan to set `allows_ira`; a bucket whose type the plan does not permit is rejected with `ERR_BUCKET_NOT_ALLOWED_BY_PLAN`. A `CustodialGuardian` may act only on buckets whose `bucket_type` is `UTMA`; a guardian acting on a non-UTMA bucket, or an investor reaching into a bucket scope they are not permitted, is rejected with `ERR_BUCKET_TYPE_NOT_PERMITTED`.

A bucket exposes several computed views over its tax lots. `invested_principal_cents` is the sum of remaining cost basis across the bucket's `OPEN` tax lots; `market_value_cents` is the sum of those open lots' `market_value_cents`; `ytd_ira_contributed_cents`, meaningful only for IRA buckets, is the running total of settled invest-order net principal placed into the bucket — accumulated as a simple monotonic sum that starts at 0 and is incremented by each invest settlement's net principal, never reset by any year boundary (the logical clock exposes no contribution-year reset); `total_drift_bps` and the boolean `needs_rebalance` capture how far the holdings have drifted from the model target, as computed in §3.8. A bucket carries a `status` of `OPEN`, `FROZEN`, or `CLOSED`, beginning `OPEN`; a `FROZEN` bucket blocks new invest and withdraw orders.

A bucket's status moves under both manual and cascade control. A `PlatformAdmin` freezes an `OPEN` bucket — permitted only when it is `OPEN` — moving it to `FROZEN` and bumping the bucket version; the same freeze also happens as the cascade from restricting the account (§3.2). A `PlatformAdmin` unfreezes a `FROZEN` bucket back to `OPEN`, permitted only when it is `FROZEN` and the owning account is `VERIFIED`, bumping the bucket version. An `Investor` or `CustodialGuardian` closes a bucket, permitted only when the bucket is `OPEN`, it has no tax lot in `OPEN` status, and it has no order in `DRAFT` or `SUBMITTED` status; a close attempt while open lots or non-terminal orders remain is rejected with `ERR_BUCKET_NOT_EMPTY`. A successful close moves the bucket to the terminal `CLOSED` state and bumps the bucket version.

### 3.7. Orders: The Invest and Withdraw Lifecycle

An order is the unit of investing and divesting. It is created in `DRAFT` status by an `Investor` or `CustodialGuardian` who supplies the owning `account_id`, the target `bucket_id`, the `order_kind` (`INVEST` or `WITHDRAW`), an optional `source`, the `requested_amount_cents` (the requested principal for an invest, or the proceeds target for a withdraw, at least 1), and, for withdrawals, a `lot_selection_method`. The `source` records the origin of an invest and is one of `SWEEP`, `RECURRING`, `FOUND_MONEY`, `REFERRAL`, or `MANUAL`, defaulting to `MANUAL` when omitted; the same field and default apply to both order kinds — a supplied `source` is stored verbatim and is not coerced to `MANUAL` for withdrawals, and a value outside the enum is rejected with `ERR_INVALID_REQUEST`. The `lot_selection_method` is one of `FIFO`, `HIFO`, or `SPEC_ID`; it is optional even for a withdrawal, defaulting to `FIFO` when omitted on a withdraw, and a value outside the enum is rejected with `ERR_INVALID_REQUEST`. On an `INVEST` order `lot_selection_method` is not applicable: it is stored verbatim if a value is supplied and otherwise stored as `null` rather than defaulted. An order tracks computed outcomes — `settled_amount_cents`, `realized_gain_cents` (defaulting to 0), and `management_fee_cents` (defaulting to 0) — and carries a `status` of `DRAFT`, `SUBMITTED`, `SETTLED`, `REJECTED`, or `CANCELLED`.

Submitting an order is an `Investor` or `CustodialGuardian` action that moves it from `DRAFT` to `SUBMITTED`. It is permitted only when the order is `DRAFT`, the target bucket is `OPEN`, and the owning account is `VERIFIED`; a non-verified account here yields `ERR_KYC_NOT_VERIFIED`. The submit also carries `expected_bucket_version` for the optimistic-concurrency check of §2.8 and bumps the order version. From `DRAFT`, the order may instead be cancelled by an `Investor` or `CustodialGuardian` — permitted only while `DRAFT` — moving it to the terminal `CANCELLED` state and bumping the order version.

A `PlatformAdmin` settles a `SUBMITTED` order, optionally supplying `spec_lot_ids` for specific-identification withdrawals. Settlement is permitted only when the order is `SUBMITTED` and the target bucket is `OPEN`. For an invest, the account's `cash_balance_cents` must be at least the order's `requested_amount_cents`, otherwise `ERR_INSUFFICIENT_CASH`. For a withdrawal, the market value of the selected open lots must cover the requested proceeds, otherwise `ERR_INSUFFICIENT_LOTS`. A successful settle runs the appropriate settlement computation (below), recomputes the bucket's `invested_principal_cents`, `market_value_cents`, `total_drift_bps`, and `needs_rebalance`, moves the order to the terminal `SETTLED` state, and bumps the order version. Alternatively a `PlatformAdmin` may reject a `SUBMITTED` order — permitted only while `SUBMITTED` — moving it to the terminal `REJECTED` state and bumping the order version; because a submitted order holds no funds, the reject reverses no ledger.

For an invest settlement, the evaluation order is pinned and load-bearing. The gross is the order's `requested_amount_cents`. The `management_fee_cents` withheld is the gross multiplied by the plan's `management_fee_bps`, divided by 10000, floored. The net principal is the gross minus that fee. The order's `settled_amount_cents` is set to the net principal. The system then opens a new tax lot whose `cost_basis_cents` and `remaining_basis_cents` are both the net principal, debits the account's `cash_balance_cents` by the full gross (the entire gross leaves cash; the fee is withheld to the platform), and increases the account's `lifetime_invested_cents` by the net principal. This cash debit is applied directly to `cash_balance_cents`; an invest settlement writes no `CashTransaction` ledger row (neither a `MANAGEMENT_FEE` row for the withheld fee nor any debit row for the gross). The opened lot's `unit_gain_ratio_bps` is 0 at open, so its `market_value_cents` equals the net principal until a valuation is injected. The order's `management_fee_cents` is set to the withheld fee and its `realized_gain_cents` to 0. The fiscal-sufficiency check precedes the cap check: if `cash_balance_cents` is below the full gross the settle is rejected with `ERR_INSUFFICIENT_CASH` before any IRA-cap evaluation. When the target bucket is an IRA, the net principal additionally accumulates into the bucket's `ytd_ira_contributed_cents`; before that accumulation, the system checks the IRA annual contribution cap — the running `ytd_ira_contributed_cents` plus this net principal must not exceed 700000 cents (seven thousand dollars), and a settle that would breach the cap is rejected with `ERR_IRA_CAP_EXCEEDED`.

For a withdraw settlement, the system targets the requested proceeds against the bucket's open lots in an order set by the lot-selection method. Under `FIFO`, lots are taken by oldest `acquired_at` first, breaking ties by oldest `created_at`. Under `HIFO`, lots are taken by highest `unit_gain_ratio_bps` first, then by oldest `acquired_at`, then by oldest `created_at`. Under `SPEC_ID`, lots are consumed in the explicit `spec_lot_ids` order supplied with the request; if no explicit list is supplied, the system falls back to oldest `acquired_at` first. Starting from the proceeds target and walking the chosen lots while proceeds still remain to be raised: each lot's market value is its `remaining_basis_cents` multiplied by the quantity 10000 plus its `unit_gain_ratio_bps`, divided by 10000, floored; the amount taken from the lot is the smaller of that lot market value and the still-remaining target; the basis consumed is that lot's `remaining_basis_cents` multiplied by the amount taken, divided by the lot's market value, floored; the realized gain accrued from the lot is the amount taken minus the basis consumed; the lot's `remaining_basis_cents` is reduced by the basis consumed, and if it reaches 0 the lot is marked `DEPLETED`; the running proceeds increase by the amount taken and the remaining target decreases by the amount taken. Rounding is applied per lot — floor the per-lot market value and floor the per-lot basis consumed — and then summed, rather than rounded once at the end. When the walk completes, the order's `settled_amount_cents` is the total proceeds realized and `realized_gain_cents` is the summed realized gain; the proceeds are credited to the account's `cash_balance_cents` through a `WITHDRAW_PROCEEDS` cash transaction. Because `HIFO` consumes the highest-appreciation lots first, it minimizes realized gain relative to `FIFO` on identical inventory, whereas `FIFO` consumes the oldest cost basis first.

Tax lots are read-only artifacts of settlement. Each lot records its owning `bucket_id`, the `open_order_id` of the invest order that opened it, its `cost_basis_cents` at open (at least 1), its `remaining_basis_cents` after partial sells, its signed `unit_gain_ratio_bps` (the per-lot appreciation in basis points, defaulting to 0 at open), its derived `market_value_cents` (the remaining basis adjusted by the gain ratio), its `acquired_at` (the logical-clock instant the opening invest settled, which is also the FIFO/HIFO ordering key), and a `status` of `OPEN` or `DEPLETED`. Because no business endpoint sets appreciation, a `PlatformAdmin` injects a per-lot `unit_gain_ratio_bps` on an `OPEN` lot through a sanctioned market-data capability that simulates a feed; doing so recomputes that lot's `market_value_cents` and the owning bucket's `market_value_cents`, `total_drift_bps`, and `needs_rebalance`.

### 3.8. Portfolio Drift and Rebalance Flagging

The robo-advisor measures how far a bucket's holdings have drifted from its model portfolio's targets. The total market value of the bucket is the sum of its `OPEN` tax lots' `market_value_cents`. When that total is zero — an empty bucket with no open lots — the `total_drift_bps` is 0 and `needs_rebalance` is false by definition. Otherwise, for each asset class in the model's `target_allocation`, the actual weight in basis points is the market value of the bucket's open lots tagged to that class, multiplied by 10000, divided by the total market value, floored; the target in basis points is that class's whole-percent target weight multiplied by 100; and the per-asset drift is the absolute difference between the actual weight and the target. Because no entity field or endpoint ever tags a tax lot to a specific asset class, the entire open-lot market value of the bucket is attributed to a single implicit class — the first key of the model's `target_allocation` in insertion order — so that first class carries an actual weight of 10000 bps and every other class carries 0. The classes are iterated in `target_allocation` insertion order. The bucket's `total_drift_bps` is the maximum of these per-asset drifts across all asset classes; for a single-class 100% allocation this maximum is 0. The bucket `needs_rebalance` exactly when its `total_drift_bps` is strictly greater than the model portfolio's `drift_band_bps`.

### 3.9. Recurring Contributions

An `Investor` schedules a recurring contribution by supplying the owning `account_id`, the per-run `amount_cents` (at least 100), a `cadence` of `DAILY`, `WEEKLY`, or `MONTHLY`, and a `run_day_index` — the zero-based calendar day-of-cycle on which the run fires. On creation the system sets `next_run_at` from the current logical clock advanced by the cadence's fixed duration — `DAILY` adds one day, `WEEKLY` adds seven days, and `MONTHLY` adds thirty days — and renders it as an ISO 8601 UTC timestamp; it starts `runs_completed` at 0 and sets `status` to `ACTIVE`. The schedule is a stored record only: no endpoint ever fires a run, so `next_run_at` and `runs_completed` are never subsequently advanced, and no `CONTRIBUTION_DEPOSIT` cash transaction is ever produced. A schedule's day must not collide with an existing active schedule on the same account: a new `ACTIVE` contribution's `run_day_index` must not fall within a plus-or-minus-one inclusive buffer of any existing `ACTIVE` contribution's `run_day_index` on the same account — that is, the closed buffered interval from one less than to one more than an existing day is reserved — and a collision is rejected with `ERR_CONTRIBUTION_DAY_COLLISION`. A contribution carries a `status` of `ACTIVE`, `PAUSED`, or `CANCELLED`. An `Investor` may cancel a contribution, moving it from `ACTIVE` or `PAUSED` to the terminal `CANCELLED` state; closing the owning account also cancels every still-`ACTIVE` contribution as a cascade (§3.2).

### 3.10. Found-Money Rewards

A found-money reward turns qualifying brand spend into a cash rebate. An `Investor` earns one by supplying the owning `account_id`, the `offer_id` of the offer that produced it, and the `qualifying_spend_cents` that triggered it (at least 1). The reward's rebate is computed and captured at earn time. First, the qualifying spend must reach the offer's `min_spend_cents`: a spend below that minimum is rejected with `ERR_MIN_SPEND_NOT_MET`. When the offer's `rebate_mode` is `FLAT`, the `rebate_amount_cents` is simply the offer's `rebate_flat_cents`, independent of the spend (the minimum-spend gate still applies). When the offer's `rebate_mode` is `PERCENT`, the raw rebate is the qualifying spend multiplied by the offer's `rebate_percent_bps`, divided by 10000, floored; the captured `rebate_amount_cents` is the smaller of that raw rebate and the offer's `max_rebate_cents`, so the cap binds whenever the floored percentage rebate would exceed it. The reward's `eligible_at` is set to the current logical clock plus the offer's `hold_days` days. A fresh reward starts in `PENDING` status.

A `PlatformAdmin` confirms a `PENDING` reward after its hold elapses. Confirmation is permitted only when the reward is `PENDING`, the current logical clock is at or after the reward's `eligible_at`, and the owning account is `VERIFIED`. A confirm attempted before `eligible_at` is rejected with `ERR_HOLD_PERIOD_ACTIVE`, and one attempted against a non-verified account with `ERR_KYC_NOT_VERIFIED`. Confirmation moves the reward to the terminal `CONFIRMED` state, credits the account's `cash_balance_cents` by the reward's `rebate_amount_cents`, and writes a `FOUND_MONEY` cash transaction whose positive `amount_cents` equals that rebate — the credit to cash, the ledger amount, and the captured rebate are conserved and equal. Alternatively a `PlatformAdmin` reverses a `PENDING` reward — permitted only while `PENDING` — moving it to the terminal `REVERSED` state with no ledger effect.

### 3.11. Referrals and Bonus Qualification

A referral rewards both parties when a referred investor starts investing. An `Investor` issues a referral by supplying their own `referrer_account_id`, a unique `code`, and a `bonus_cents` (at least 1) to be paid to each side on qualification; a duplicate `code` is rejected with `ERR_DUPLICATE_TIER`. A new referral starts in `ISSUED` status and carries a `referred_account_id` that is set only on redemption.

Another investor redeems an `ISSUED` referral by supplying their own `referred_account_id`. Redemption is permitted only while the referral is `ISSUED`, the redeeming account is not the referrer, and the current logical clock is still before thirty days after the referral's `created_at`. A redeemer who is the referrer is rejected with `ERR_SELF_REFERRAL`; a redemption attempted after the thirty-day window has elapsed is rejected with `ERR_REFERRAL_WINDOW`. A successful redemption moves the referral to `REDEEMED` and records the redeeming account as the `referred_account_id`. A redeemer who has not yet qualified may release the redemption — permitted only while `REDEEMED` — which returns the referral to `ISSUED` and clears `referred_account_id` to null, freeing the code for another account to redeem.

A `PlatformAdmin` qualifies a `REDEEMED` referral once the referred account has demonstrably begun investing: qualification is permitted only while the referral is `REDEEMED` and the referred account's `lifetime_invested_cents` is at least 500 cents. A qualify against a referral not in `REDEEMED`, and a qualify whose referred account has not yet reached 500 cents of `lifetime_invested_cents`, are both rejected with `ERR_INVALID_STATE`. Qualification moves the referral to the terminal `QUALIFIED` state and pays both sides: it credits the referrer account's `cash_balance_cents` by `bonus_cents`, credits the referred account's `cash_balance_cents` by `bonus_cents`, increases each account's derived `referral_credits_cents` by `bonus_cents`, and writes two `REFERRAL_BONUS` cash transactions, one per side, each with a positive `amount_cents` equal to the bonus.

Two terminal exits close out an `ISSUED` referral that never qualifies. A `PlatformAdmin` expires an `ISSUED` referral — permitted only while `ISSUED` and the current logical clock is at or after thirty days from the referral's `created_at` — moving it to the terminal `EXPIRED` state; an expire attempted before the window has elapsed is rejected with `ERR_REFERRAL_WINDOW`. The issuing `Investor` revokes an `ISSUED` referral — permitted only while `ISSUED` and the acting account is the referrer — moving it to the terminal `REVOKED` state.

### 3.12. Reading Resources and Reverse Lookups

All entities are individually readable by id, and the read-by-id endpoints validate the path identifier left-to-right and return `ERR_NOT_FOUND` for an id that does not resolve. Read-by-id is owner-scoped exactly like the writes of §2.1: when an `Investor` or `CustodialGuardian` reads an account-owned resource (account, card, accrual, contribution, bucket, order, tax lot, reward, or referral) whose owning account is not their own `X-User-ID`, the read is rejected with `ERR_NOT_RESOURCE_OWNER` after the id resolves. List endpoints support filtering as a reverse-reachability mechanism. In addition to any explicit query filters, a list requested by an `Investor` or `CustodialGuardian` is implicitly narrowed to only the caller's own resources — those whose owning account (or, for referrals, `referrer_account_id`; for tax lots, the lot's owning bucket's account) equals `X-User-ID` — whereas a `PlatformAdmin` sees the unfiltered collection subject only to the explicit filters; `total_count` reflects the post-scoping, post-filter set. Accounts may be listed by a `PlatformAdmin`, filtered by `plan_id`, `model_portfolio_id`, `kyc_status`, or `billing_status`. An account's cash transactions are listed filtered by `tx_type` and `status`. Linked cards are listed filtered by `account_id` and `status`. Round-up accruals are listed filtered by `account_id`, `linked_card_id`, and `status`. Recurring contributions are listed filtered by `account_id` and `status`. Buckets are listed filtered by `account_id`, `bucket_type`, and `status`. Orders are listed filtered by `account_id`, `bucket_id`, `status`, and `order_kind`. Tax lots are listed filtered by `bucket_id`, `open_order_id`, and `status`. Found-money rewards are listed filtered by `account_id`, `offer_id`, and `status`. Referrals are listed filtered by `referrer_account_id`, `referred_account_id`, and `status`. All list endpoints honor the pagination and sort rules of §2.3.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that read a resource, list resources, or modify an existing resource (including state transitions and administrative actions) return a `200 OK` status code. The complete request bodies, computed outcomes, and side effects for each endpoint are described in §3 and §2; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/subscription-plans` | Create a subscription plan tier | PlatformAdmin |
| GET | `/subscription-plans/{id}` | Read a subscription plan | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/model-portfolios` | Create a risk-tiered model portfolio | PlatformAdmin |
| GET | `/model-portfolios/{id}` | Read a model portfolio | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/found-money-offers` | Create a found-money brand offer | PlatformAdmin |
| GET | `/found-money-offers/{id}` | Read a found-money offer | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/accounts/register` | Register a new investor account | Anonymous |
| GET | `/accounts/{id}` | Read an account with computed balances | PlatformAdmin, Investor, CustodialGuardian |
| GET | `/accounts` | List accounts | PlatformAdmin |
| POST | `/accounts/{id}/verify-kyc` | Mark KYC verified | PlatformAdmin |
| POST | `/accounts/{id}/restrict` | Restrict account; cascade-freeze open buckets | PlatformAdmin |
| POST | `/accounts/{id}/billing/charge-subscription` | Charge the monthly subscription fee | PlatformAdmin |
| POST | `/accounts/{id}/billing/mark-past-due` | Flag an account past due | PlatformAdmin |
| POST | `/accounts/{id}/sweep` | Sweep pending round-ups and auto-invest above threshold | PlatformAdmin, Investor |
| POST | `/accounts/{id}/close` | Close an account | Investor |
| GET | `/accounts/{id}/cash-transactions` | List an account's cash transactions | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/linked-cards` | Link a funding card | Investor |
| GET | `/linked-cards/{id}` | Read a linked card | PlatformAdmin, Investor |
| GET | `/linked-cards` | List linked cards | PlatformAdmin, Investor |
| PATCH | `/linked-cards/{id}` | Update multiplier or pause/unlink a card | Investor |
| POST | `/roundup-accruals` | Record a card-purchase round-up accrual | Investor |
| GET | `/roundup-accruals/{id}` | Read a round-up accrual | PlatformAdmin, Investor |
| GET | `/roundup-accruals` | List round-up accruals | PlatformAdmin, Investor |
| POST | `/roundup-accruals/{id}/cancel` | Cancel a pending accrual | Investor |
| POST | `/recurring-contributions` | Create a recurring contribution schedule | Investor |
| GET | `/recurring-contributions/{id}` | Read a recurring contribution | PlatformAdmin, Investor |
| GET | `/recurring-contributions` | List recurring contributions | PlatformAdmin, Investor |
| POST | `/recurring-contributions/{id}/cancel` | Cancel a recurring contribution | Investor |
| POST | `/buckets` | Open an investing bucket | Investor, CustodialGuardian |
| GET | `/buckets/{id}` | Read a bucket with computed drift and valuations | PlatformAdmin, Investor, CustodialGuardian |
| GET | `/buckets` | List buckets | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/buckets/{id}/freeze` | Freeze a bucket | PlatformAdmin |
| POST | `/buckets/{id}/unfreeze` | Unfreeze a bucket | PlatformAdmin |
| POST | `/buckets/{id}/close` | Close an empty bucket | Investor, CustodialGuardian |
| POST | `/orders` | Create a draft invest/withdraw order | Investor, CustodialGuardian |
| GET | `/orders/{id}` | Read an order | PlatformAdmin, Investor, CustodialGuardian |
| GET | `/orders` | List orders | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/orders/{id}/submit` | Submit a draft order | Investor, CustodialGuardian |
| POST | `/orders/{id}/settle` | Settle a submitted order | PlatformAdmin |
| POST | `/orders/{id}/reject` | Reject a submitted order | PlatformAdmin |
| POST | `/orders/{id}/cancel` | Cancel a draft order | Investor, CustodialGuardian |
| GET | `/tax-lots/{id}` | Read a tax lot | PlatformAdmin, Investor, CustodialGuardian |
| GET | `/tax-lots` | List tax lots | PlatformAdmin, Investor, CustodialGuardian |
| POST | `/found-money-rewards` | Earn a found-money reward | Investor |
| GET | `/found-money-rewards/{id}` | Read a found-money reward | PlatformAdmin, Investor |
| GET | `/found-money-rewards` | List found-money rewards | PlatformAdmin, Investor |
| POST | `/found-money-rewards/{id}/confirm` | Confirm a pending reward after hold | PlatformAdmin |
| POST | `/found-money-rewards/{id}/reverse` | Reverse a pending reward | PlatformAdmin |
| POST | `/referrals` | Issue a referral code | Investor |
| GET | `/referrals/{id}` | Read a referral | PlatformAdmin, Investor |
| GET | `/referrals` | List referrals | PlatformAdmin, Investor |
| POST | `/referrals/{id}/redeem` | Redeem a referral code | Investor |
| POST | `/referrals/{id}/release-redemption` | Release a redeemed referral back to issued | Investor |
| POST | `/referrals/{id}/qualify` | Qualify a redeemed referral and pay both sides | PlatformAdmin |
| POST | `/referrals/{id}/expire` | Expire an issued referral past its window | PlatformAdmin |
| POST | `/referrals/{id}/revoke` | Revoke an issued referral | Investor |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/_lots/{id}/set_valuation` | Inject a per-lot appreciation rate | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BUCKET_TYPE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_KYC_NOT_VERIFIED` | 409 Conflict |
| `ERR_BUCKET_NOT_ALLOWED_BY_PLAN` | 409 Conflict |
| `ERR_BENEFICIARY_REQUIRED` | 400 Bad Request |
| `ERR_HOLD_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_REFERRAL_WINDOW` | 409 Conflict |
| `ERR_SELF_REFERRAL` | 409 Conflict |
| `ERR_MIN_SPEND_NOT_MET` | 409 Conflict |
| `ERR_INSUFFICIENT_CASH` | 409 Conflict |
| `ERR_INSUFFICIENT_LOTS` | 409 Conflict |
| `ERR_IRA_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_MULTIPLIER` | 400 Bad Request |
| `ERR_ALLOCATION_SUM` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BUCKET_NOT_EMPTY` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_BUCKETS` | 409 Conflict |
| `ERR_DUPLICATE_TIER` | 409 Conflict |
| `ERR_OFFER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CONTRIBUTION_DAY_COLLISION` | 409 Conflict |
