# Warehouse-Club Membership API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Warehouse-Club Membership API, the back-office system that powers a Costco/Sam's-Club-style membership warehouse. The platform manages the full membership relationship — from anonymous signup and payment, through tier selection (basic versus executive), household and add-on cardholders, term renewal and lapse, to cancellation with a prorated refund. Layered on top of membership is the in-club commerce engine: register transactions that snapshot member-only pricing, apply stacked instant-savings and manufacturer-rebate promotions, accrue and cap the executive 2%-style reward, and reconcile returns made either with a receipt or under the club's no-receipt lookup policy.

The system is, at heart, two cooperating engines. A **pricing engine** computes line-level discounts, transaction nets, reward accrual, and refund amounts under a strictly pinned evaluation order, because instant savings, manufacturer rebates, and rewards depend on one another in a way that is only well-defined when sequenced. A **reward ledger** treats executive reward as a conserved fiscal quantity: every accrual, reversal, redemption, and per-term expiry is recorded as a signed ledger movement, and the membership's derived reward balances are always reconcilable from those movements. Because terms roll, caps reset, and clerks act on data they read moments earlier, the system also enforces optimistic concurrency on the membership term to prevent a renewal or cancellation from acting on a stale view.

The API serves five kinds of callers — club administrators who seed configuration, members who own and manage their own memberships, register clerks who ring up sales, service-desk clerks who process returns, and anonymous prospects who can do nothing but sign up. All time-sensitive behavior (promotion windows, term expiry, auto-renewal, no-receipt eligibility) is driven by a logical clock that administrators advance for test-driving rather than by wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply across the entire API. Most of it is contract-level: response shape, pagination, identifier and timestamp conventions, precision, and concurrency control.

### 2.1. User and Role-Based Access Control

Every request other than membership signup must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ClubAdmin`, `Member`, `RegisterClerk`, `ServiceDeskClerk`, and `Anonymous`. If either header is missing or `X-User-Role` is not one of the known roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). The sole exception is membership signup, which is anonymous-allowed and may be called without authenticating. When a recognized caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The roles differ in how `X-User-ID` binds to data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Membership`; ownership checks on any resource that references a membership compare that resource's `membership_id` to `X-User-ID`, so a member operates only on their own membership, cards, payments, returns, ledger, and fee events. When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the administrator has a full operational override across all member and clerk operations and additionally owns configuration (seeding plans, products, instant savings), the logical clock, and the list-all-memberships view. When `X-User-Role` is `RegisterClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the register clerk opens transactions, adds lines, and finalizes or voids sales. When `X-User-Role` is `ServiceDeskClerk`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity; the service-desk clerk creates returns and approves or rejects them. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity, and the only thing this principal may do is sign up a new membership.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.11) rather than wall-clock time.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip, defaults to 0, has a minimum of 0, and has no upper bound (an offset past the end yields an empty page). A `limit` or `offset` that is non-integer or outside its allowed bounds is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, every list is returned sorted by `created_at` in ascending order, with ties broken by ascending `id`. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Identifiers, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID (version 4, lowercase, hyphenated) with no type prefix and is used for identity only. Every resource also carries a `created_at` timestamp in ISO 8601 UTC with three fractional digits, stamped from the logical clock (§2.11) at creation; `updated_at` and every `*_utc` timestamp are likewise stamped from the logical clock.

Most resources additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that starts at its initial value and increments by one on each mutation. These mutation-tracking fields are present on `Membership`, `HouseholdCard`, `Transaction`, `TransactionLine`, `Return`, and `Payment`. The configuration and audit resources — `MembershipPlan`, `Product`, `InstantSaving`, `RewardLedgerEntry`, and `FeeEvent` — are not mutation-tracked: they carry only `id` and `created_at`, and have neither `updated_at` nor `version`.

When a derived field on a membership changes as a side effect of some other operation (for example, when finalize bumps `reward_accrued_cents`, or a cascade recomputes `household_card_count`), that counts as a mutation of the membership: its `updated_at` is refreshed and its `version` increments.

### 2.5. Left-to-Right Resource Resolution

Several endpoints address a resource through a path identifier and also reference further resources in the request body. The server validates referenced identifiers in a fixed left-to-right order: the membership first, then the targeted transaction, return, or card, then any product. The request is rejected at the first identifier that does not resolve, using that identifier's not-found code: `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND` — all HTTP 404. The system never reports a downstream not-found before resolving the upstream identifier.

### 2.6. Validation Ordering

When several checks guard one operation, they are evaluated in a fixed priority so that the earliest applicable failure is the one reported. The global order is: (1) user-context authentication, yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) role authorization, yielding `ERR_INSUFFICIENT_PERMISSIONS`; (3) existence of every referenced identifier, yielding the appropriate 404 from §2.5; (4) request well-formedness — required body fields present and correctly typed, such as a `qty` that is an integer of at least 1 or a `tier` drawn from the allowed enum — yielding `ERR_INVALID_REQUEST` (HTTP 400); (5) optimistic-concurrency version match on renew and cancel, yielding `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412); (6) the target resource being in the correct state for the requested transition, yielding `ERR_MEMBERSHIP_NOT_ACTIVE`, `ERR_TRANSACTION_NOT_OPEN`, `ERR_RETURN_NOT_PENDING`, or `ERR_CARD_NOT_ACTIVE` (all HTTP 409); and then the operation-specific business rules described in §3. Authentication is always checked before authorization, existence before well-formedness, the concurrency check before the state check, and all of those before domain-specific business validation.

### 2.7. Money and Precision

All monetary amounts in the system are integer cents — fees, prices, discounts, refunds, and reward amounts alike — and are represented as integers in the API. Per-unit discount amounts are whole cents and are multiplied by unit counts without any fractional rounding.

Two calculations divide and therefore require an explicit rounding rule. Reward accrual on a finalized transaction is floored to whole cents before the per-term cap is applied. Refund proration — both the receipted-return refund and the cancellation refund — uses **block rounding**: the system multiplies by the quantity being prorated and only then floor-divides by the denominator, rather than computing a per-unit value, rounding it, and summing. Block rounding avoids per-unit rounding drift and is mandatory wherever a prorated cents amount is produced.

### 2.8. The Reward as a Conserved Quantity

Executive reward is tracked as a ledger of signed movements on the `RewardLedgerEntry` resource. Each entry records its owning `membership_id`, an `entry_type` that is one of `ACCRUAL`, `REVERSAL`, `REDEMPTION`, or `EXPIRY`, a signed `amount_cents`, the `source_transaction_id` that caused it (null for an `EXPIRY` entry), and the `term_start_utc` of the term it belongs to, because both the cap and expiry are scoped to a single term. An `ACCRUAL` is positive and is the reward earned net of the cap; a `REVERSAL`, `REDEMPTION`, and `EXPIRY` are negative. Wherever a term boundary (renewal, clock-driven auto-renewal, lapse, or cancellation) expires the term's reward, the unredeemed reward is the membership's `reward_accrued_cents` minus its `reward_redeemed_cents`, and an `EXPIRY` entry carrying the negative of that amount is written only when the unredeemed reward is strictly positive; when there is no unredeemed reward to expire, no `EXPIRY` entry is written. When the ledger is replayed it is processed in `created_at` ascending order.

A membership exposes two derived reward figures. `reward_accrued_cents` is the sum of executive reward accrued in the current term, capped at the plan's annual reward cap, and is 0 for a basic plan. `reward_redeemed_cents` is the executive reward redeemed against fees in the current term. The available reward a member can still spend is `reward_accrued_cents` minus `reward_redeemed_cents`. These figures, together with the per-term expiry, keep accrual, redemption, reversal, and expiry in balance across the term.

### 2.9. Membership Fee Accounting

Every charge or refund against a membership is recorded as a `FeeEvent` carrying the owning `membership_id`, a `kind` that is one of `SIGNUP`, `RENEWAL`, `ADDON`, or `CANCEL_REFUND`, a signed `amount_cents` (charges positive, a `CANCEL_REFUND` negative), and the `term_start_utc` the fee applies to. The membership's derived `fees_paid_cents` is the total of membership and add-on fees collected for the current term, net of any cancellation refunds.

### 2.10. Optimistic Concurrency on the Membership Term

Renewing and cancelling a membership are the two operations that roll or close the current term, and both are guarded by optimistic concurrency on the membership's `version`. Each of these two requests must carry `expected_membership_version` as a required, non-optional field whose value is the `version` the client last observed on the target membership. Before the version is compared, renew and cancel first apply any pending clock-driven term-boundary transition (§2.11) to the membership, so the `version` checked against is the one reflecting that transition; if `expected_membership_version` does not then equal the membership's current `version`, the request is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412) and nothing else is mutated.

For renewal, this rejection captures the case where another writer has already renewed the membership — which legitimately rolls the term forward and resets the per-term reward cap — so the current writer's view of the term is stale. For cancellation, it captures the case where the membership was renewed or otherwise mutated after the client read it, making the prorated cancel refund the client computed stale. No other endpoint takes a version field; only renew and cancel are version-guarded.

### 2.11. The Logical Clock

All time-dependent behavior reads a server-controlled logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-set call it stays at that default and never falls back to wall-clock time. An administrator advances the clock by supplying a target instant as `to_iso8601`. Promotion windows, term expiry, auto-renewal evaluation, the no-receipt eligibility window, and every `*_utc` timestamp the system stamps are all measured against this clock. Advancing the clock may, on subsequent reads, surface a membership crossing its term boundary into lapse or auto-renewal as described in §3.

## 3. Business Logic & Workflows

### 3.1. Plans, Products, and Promotions

Before any selling happens, a `ClubAdmin` seeds configuration. A **membership plan** fixes the economics of a tier and is immutable once created. It carries a `tier` that is either `BASIC` or `EXECUTIVE`, an `annual_fee_cents` of at least 0, a `reward_rate_bps` (the executive reward accrual rate in basis points, at least 0), a `reward_cap_cents` (the annual cap on accrued executive reward, at least 0), a `max_household_cards` (the number of household cards allowed beyond the primary, at least 0, defaulting to 1), and an `addon_fee_cents` (the per-card fee for paid add-on cards beyond the included allowance, at least 0). A basic plan earns no reward: for tier `BASIC` both `reward_rate_bps` and `reward_cap_cents` must be 0, and `reward_rate_bps` defaults to 0. Attempting to create a `BASIC` plan with a nonzero `reward_rate_bps`, or any plan with an out-of-enum tier or a missing required field, is rejected with `ERR_INVALID_REQUEST`.

A **product** carries a `sku` that must be unique across all products, a `list_price_cents` (the non-member shelf price, at least 0), a `member_price_cents` (the member-only price, at least 0 and never above the list price), a `member_only` flag (default false) marking items purchasable only on an active membership, a `per_member_limit` (max units a membership may buy of this product per term, at least 0, where 0 means unlimited, default 0), a `department` drawn from `GENERAL`, `GAS`, `PHARMACY`, and `OPTICAL`, and a `reward_eligible` flag (default true) controlling whether spend on the product accrues executive reward. Creating a product whose `sku` already exists is rejected with `ERR_PRODUCT_SKU_DUPLICATE` (HTTP 409); a `member_price_cents` greater than `list_price_cents` is rejected with `ERR_INVALID_PRICE` (HTTP 400).

A **promotion** is an `InstantSaving` row attached to a product via `product_id`. Its `kind` is either `INSTANT_SAVINGS` or `MANUFACTURER_REBATE`, it carries a per-unit `amount_cents` of at least 0 (default 0), a half-open active window running from an inclusive `window_start_utc` to an exclusive `window_end_utc`, and a `max_units` that caps how many units per transaction line the discount may apply to (at least 0, where 0 means unlimited, default 0). A promotion whose `window_end_utc` is at or before its `window_start_utc` is rejected with `ERR_INVALID_PROMO_WINDOW` (HTTP 400).

### 3.2. Signing Up and Activating a Membership

Anyone — including an unauthenticated `Anonymous` caller — may sign up a membership by supplying the chosen `plan_id`, the `primary_member_name` (a non-empty string), and optionally `auto_renew` (whether the membership renews automatically at period end, default true). The `plan_id` is resolved for existence before the body fields are checked for well-formedness, so an unknown `plan_id` yields `ERR_PLAN_NOT_FOUND` even when other fields are malformed. Signup creates a `Membership` in `PENDING_PAYMENT` status; the primary member is tracked on the membership itself and no household card is auto-created for them. The membership records its `plan_id`, exposes a lifecycle `status` of `PENDING_PAYMENT`, `ACTIVE`, `EXPIRED`, or `CANCELLED`, and carries the current-term boundaries `term_start_utc` and `term_end_utc` plus the derived `reward_accrued_cents`, `reward_redeemed_cents`, `fees_paid_cents`, and `household_card_count`.

Activation happens through payment. Settling a payment requires the `membership_id`, the `purpose` (`SIGNUP` or `RENEWAL`), the `outcome` (`PENDING`, `SUCCEEDED`, or `FAILED`), and an optional `redeem_reward_cents`. A payment records its computed `amount_cents` — the plan's `annual_fee_cents` net of any reward redemption applied at payment time; reward redemption is applied only on `RENEWAL` payments, so a `SIGNUP` payment ignores `redeem_reward_cents` and its `amount_cents` is always the full `annual_fee_cents`. A `SUCCEEDED` payment with purpose `SIGNUP` against a membership in `PENDING_PAYMENT` drives the system activation that moves it to `ACTIVE`: the server sets `term_start_utc` to the current clock instant and `term_end_utc` to 365 days later, records a `FeeEvent` of kind `SIGNUP` for the plan's annual fee against that term, and recomputes `fees_paid_cents`. A `SIGNUP` payment on a membership that is not in `PENDING_PAYMENT`, or a `RENEWAL` payment on a membership that is neither `EXPIRED` nor `ACTIVE`, is rejected with `ERR_PAYMENT_PURPOSE_MISMATCH` (HTTP 409).

A `SUCCEEDED` payment with purpose `RENEWAL` against an `EXPIRED` membership reinstates it: the membership returns from `EXPIRED` to `ACTIVE`, a `FeeEvent` of kind `RENEWAL` is recorded for the payment's `amount_cents` (the annual fee net of any applied redemption), `term_start_utc` rolls to the current clock instant with `term_end_utc` 365 days later, and the reward counters reset to 0 for the fresh term. A `SUCCEEDED` `RENEWAL` payment against an `ACTIVE` membership does not roll the term or change status; it merely records the payment (which later qualifies the membership for clock-driven auto-renewal per §3.3) and, if `redeem_reward_cents` is supplied, applies the redemption against the current term's available reward.

### 3.3. Renewing, Lapsing, and Cancelling

A `Member` (or a `ClubAdmin` acting on their behalf) renews an `ACTIVE` membership, which is a cyclic transition that keeps the membership `ACTIVE` while rolling its term and resetting the per-term reward cap. Renewal must carry `expected_membership_version` matching the membership's current `version` (per §2.10) and may carry an optional `redeem_reward_cents`. On success the system records a `FeeEvent` of kind `RENEWAL` for the annual fee net of any reward redemption against the new term, writes a `RewardLedgerEntry` of type `EXPIRY` that zeroes any unredeemed reward carried from the prior term, rolls `term_start_utc` to the old `term_end_utc` and sets `term_end_utc` to 365 days after that new start, resets `reward_accrued_cents` and `reward_redeemed_cents` to 0 for the new term, and increments the membership `version` by one. Renewing a membership that is not `ACTIVE` is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`.

When the logical clock advances at or past a membership's `term_end_utc`, one of two things happens automatically. If `auto_renew` is false, the membership lapses: it moves from `ACTIVE` to `EXPIRED`, a `RewardLedgerEntry` of type `EXPIRY` zeroes the term's unredeemed reward, `reward_accrued_cents` is recomputed to 0, and every household card still in `ACTIVE` status cascades to `REVOKED`. If `auto_renew` is true and at least one `SUCCEEDED` `RENEWAL` payment exists for the membership (the existence of any such payment qualifies; it is not scoped to a particular term), the membership stays `ACTIVE` across the boundary with the same side effects as a manual renewal — a `RENEWAL` `FeeEvent` for the plan's full `annual_fee_cents` (no reward redemption is applied during clock-driven auto-renewal), an `EXPIRY` of the prior term's reward, the term roll with the new `term_start_utc` set to the prior `term_end_utc`, a reset of both `reward_accrued_cents` and `reward_redeemed_cents` to 0, and a `version` increment.

A `Member` (or a `ClubAdmin`) cancels an `ACTIVE` membership, which is terminal and moves it to `CANCELLED`. Cancellation also carries `expected_membership_version` and is OCC-guarded exactly as renewal is. On success the system computes the prorated cancel refund (see §3.7), records a `FeeEvent` of kind `CANCEL_REFUND` carrying the negative of that refund against the current term, writes a `RewardLedgerEntry` of type `EXPIRY` zeroing unredeemed reward, cascades every `ACTIVE` household card to `REVOKED`, recomputes `fees_paid_cents` and `reward_accrued_cents`, and increments the membership `version` by one. Cancelling a non-`ACTIVE` membership is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`.

### 3.4. Household and Add-On Cards

A `Member` adds a household card by supplying the owning `membership_id`, the `cardholder_name` (a non-empty string), and the `card_kind` (`INCLUDED` or `PAID_ADDON`); a `card_kind` outside that pair is rejected with `ERR_CARD_KIND_INVALID` (HTTP 400). Adding a card does not require the membership to be `ACTIVE`; any `ADDON` `FeeEvent` it records is stamped against the membership's current `term_start_utc` (which is null while the membership is still in `PENDING_PAYMENT`). A card is created in `ACTIVE` status and records a computed `fee_charged_cents`. The fee depends on the kind against the plan's allowance, evaluated against the count of cards currently in `ACTIVE` status for the membership. An `INCLUDED` card is free, but only while the active-card count is below the plan's `max_household_cards`; if the active-card count is already at or above `max_household_cards`, creating another `INCLUDED` card is rejected with `ERR_HOUSEHOLD_CARD_LIMIT` (HTTP 409). A `PAID_ADDON` card always carries `fee_charged_cents` equal to the plan's `addon_fee_cents` and records a `FeeEvent` of kind `ADDON` for that amount; it is not subject to the included-card limit. Adding a card recomputes the membership's `household_card_count`, which is the number of cards in `ACTIVE` status.

A card may be revoked explicitly by the member while it is `ACTIVE`, moving it from `ACTIVE` to `REVOKED` and recomputing the membership's `household_card_count`; revoking a card that is not `ACTIVE` is rejected with `ERR_CARD_NOT_ACTIVE`. Cards are also revoked automatically as the cascade when their membership lapses or is cancelled, as described in §3.3.

### 3.5. Ringing Up a Sale

A `RegisterClerk` opens a transaction for a membership by supplying its `membership_id`; the membership must be `ACTIVE` or the open is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. The transaction starts in `OPEN` status with zeroed totals and tracks its owning `membership_id` and computed `gross_cents`, `instant_savings_cents`, `rebate_cents`, `net_cents`, `reward_accrued_cents`, and `finalized_at_utc` (the logical-clock instant stamped at finalization, null until then).

While the transaction is `OPEN`, the clerk adds lines, each supplying a `product_id` and a `qty` of at least 1. A line records its owning `transaction_id`, the `product_id`, the `qty`, a snapshotted `unit_price_cents`, the computed `line_instant_savings_cents` and `line_rebate_cents`, and a `returned_qty` (units of this line returned so far, default 0). Adding a line is permitted only while the transaction is `OPEN` (otherwise `ERR_TRANSACTION_NOT_OPEN`) and only while the owning membership is `ACTIVE` (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`). If the product is `member_only` and the owning membership is not `ACTIVE`, the line is rejected with `ERR_MEMBER_ONLY_PRODUCT` (HTTP 403); because the owning-membership-`ACTIVE` state check (priority 6) is evaluated first and rejects with `ERR_MEMBERSHIP_NOT_ACTIVE`, this member-only rejection is in practice unreachable on the add-line path. When the product carries a positive `per_member_limit`, the requested `qty` plus the units of that product already purchased by this membership in the current term — counting the lines of every `OPEN` transaction the membership owns plus the lines of its `FINALIZED` transactions whose `finalized_at_utc` is at or after the membership's current `term_start_utc` — must not exceed `per_member_limit`; otherwise the line is rejected with `ERR_PURCHASE_LIMIT_EXCEEDED` (HTTP 409). A `per_member_limit` of 0 imposes no cap.

The line's `unit_price_cents` is snapshotted at add time: it is `member_price_cents` when the owning membership is `ACTIVE`, otherwise `list_price_cents`. The line's gross is that unit price times `qty`. Line discounts are then applied in a strictly pinned order — instant savings first, then manufacturer rebate. For each `INSTANT_SAVINGS` promotion on the product whose half-open window contains the current clock instant, the discounted units are the line `qty` when the promotion's `max_units` is 0, otherwise the smaller of `qty` and `max_units`, and that promotion contributes its `amount_cents` times those units; the summed instant savings are then clamped so they cannot exceed the line gross, giving `line_instant_savings_cents`. The base after instant savings is the gross minus that clamped instant amount. For each `MANUFACTURER_REBATE` promotion active at the current instant, the discounted units are computed the same way (full `qty` when `max_units` is 0, else the smaller of `qty` and `max_units`) and the promotion contributes its `amount_cents` times those units; the summed rebate is then clamped so it cannot exceed the post-instant base, giving `line_rebate_cents`. The line net is the gross minus the clamped instant savings minus the clamped rebate. After each line add the transaction totals are recomputed: `gross_cents` is the sum of line grosses, `instant_savings_cents` the sum of line instant savings, `rebate_cents` the sum of line rebates, and `net_cents` the gross minus instant savings minus rebate, floored at 0.

### 3.6. Finalizing, Voiding, and Reward Accrual

A `RegisterClerk` finalizes an `OPEN` transaction that has at least one line, moving it from `OPEN` to `FINALIZED`; finalizing an empty transaction is rejected with `ERR_EMPTY_TRANSACTION` (HTTP 409), finalizing a non-`OPEN` transaction with `ERR_TRANSACTION_NOT_OPEN`, and finalizing under a membership that is not `ACTIVE` with `ERR_MEMBERSHIP_NOT_ACTIVE`. Finalization stamps `finalized_at_utc` to the current clock instant and computes the transaction's executive reward accrual.

Reward accrual earns nothing on a basic plan: when the plan's tier is not `EXECUTIVE`, the transaction accrues 0. On an executive plan, the reward base is the sum of the net amounts of the lines whose product is `reward_eligible`. The raw reward is that base multiplied by the plan's `reward_rate_bps` and divided by 10000, floored to whole cents before any cap is applied. The per-term cap is then enforced forward against the membership's already-accrued reward: the remaining cap room is the plan's `reward_cap_cents` minus the membership's current `reward_accrued_cents`, and the amount actually accrued by this transaction is the raw reward but never more than the remaining room and never below 0. When the raw reward would push the term's accrual past `reward_cap_cents`, the accrued amount is clipped to the remaining room so the transaction accrues less than rate-times-base (the capped variant); when the term's accrual stays at or below the cap after this transaction, the accrued amount is the full floored rate-times-base (the uncapped variant). The accrued amount is recorded on the transaction's `reward_accrued_cents`, added to the membership's `reward_accrued_cents`, and written as a `RewardLedgerEntry` of type `ACCRUAL` with the positive accrued amount, the `source_transaction_id` set to this transaction, and `term_start_utc` set to the membership's current term start.

A `RegisterClerk` may instead void an `OPEN` transaction, moving it from `OPEN` to `VOIDED`. A void writes no ledger entries because the transaction was never finalized, and its lines remain for audit. Voiding a non-`OPEN` transaction is rejected with `ERR_TRANSACTION_NOT_OPEN`.

### 3.7. Returns: Receipted and No-Receipt

A `ServiceDeskClerk` creates a return by supplying the `membership_id`, the `product_id`, the `qty` of at least 1, and optionally the `transaction_id` of the original purchase. The return records a `lookup_mode` of `RECEIPTED`, `NO_RECEIPT_LOOKUP`, or `DENIED`, a `status` of `PENDING`, `APPROVED`, or `REJECTED`, a computed `refund_cents`, and a computed `reward_reversal_cents`. When `transaction_id` is provided, the return is receipted; the original line for the given `product_id` is the matching line on that transaction, and its already-returned units plus the requested `qty` must not exceed its purchased `qty`, or creation is rejected with `ERR_RETURN_QTY_EXCEEDS_PURCHASED` (HTTP 409). If the transaction has no line for that product, the purchased quantity is treated as 0 and creation is likewise rejected with `ERR_RETURN_QTY_EXCEEDS_PURCHASED`.

When `transaction_id` is omitted, the no-receipt lookup policy applies. The return is allowed only when the membership has at least one `FINALIZED` transaction containing the product whose finalization is recent enough: measuring whole days as the floor of the elapsed time between the current clock instant and the transaction's `finalized_at_utc`, that age must be at most 90 days (inclusive). Among the qualifying transactions, the most recent one — ordered by `finalized_at_utc` descending, then by `created_at` ascending — sets the return's `lookup_mode` to `NO_RECEIPT_LOOKUP`. If no transaction qualifies within the 90-day window, the `lookup_mode` is `DENIED` and creation is rejected with `ERR_NO_RECEIPT_LOOKUP_DENIED` (HTTP 409).

A return is resolved by a `ServiceDeskClerk` who approves or rejects it while it is `PENDING`; acting on a non-`PENDING` return is rejected with `ERR_RETURN_NOT_PENDING`. Approval requires that the return not be in `DENIED` lookup mode, and for a receipted return additionally requires that the original transaction be `FINALIZED` — a non-`FINALIZED` (or missing) original transaction is rejected with `ERR_TRANSACTION_NOT_OPEN` (HTTP 409) — and that the line's returned-so-far units plus the return `qty` not exceed the line's `qty` (again `ERR_RETURN_QTY_EXCEEDS_PURCHASED`). On approval the system computes the refund and any reward reversal, moving the return to `APPROVED`.

For a receipted approval the refund proration uses block rounding: the refund is the line's total net multiplied by the returned `qty` and then floor-divided by the line's purchased `qty`. When the plan is executive and the product is `reward_eligible`, the reward originally accrued on that line is prorated to the returned units the same way — the line's attributable accrual multiplied by the returned `qty`, floor-divided by the line's `qty` — to give `reward_reversal_cents`; otherwise the reward reversal is 0. The line's attributable accrual is reconstructed from the transaction's recorded `reward_accrued_cents` (the post-cap amount) prorated by this line's reward-eligible net over the sum of reward-eligible line nets in the transaction, using block rounding (transaction accrual times this line's net, floor-divided by the total reward-eligible net); it is 0 when the transaction accrued nothing or the total reward-eligible net is 0. The reversal is subtracted from the membership's `reward_accrued_cents`, a `RewardLedgerEntry` of type `REVERSAL` carrying the negative reversal is written when the reversal is positive, the original line's `returned_qty` is incremented by the returned units, and the membership's `reward_accrued_cents` is recomputed. A no-receipt approval instead refunds at the current member price — the product's `member_price_cents` times `qty`, reflecting the lowest-price policy — and claws back no reward, so its `reward_reversal_cents` is 0. The same product and quantity therefore refund different amounts under a receipted versus a no-receipt return.

Rejecting a return sets its `refund_cents` and `reward_reversal_cents` to 0, writes no ledger entries, and moves it to `REJECTED`.

### 3.8. Reward Redemption and the Cancel Refund

A member may apply available executive reward against a renewal fee by passing `redeem_reward_cents` on a `RENEWAL` payment or on a renewal. The available reward is the membership's `reward_accrued_cents` minus its `reward_redeemed_cents` for the current term. The amount actually applied is the requested `redeem_reward_cents`, but never more than the available reward, never more than the plan's `annual_fee_cents`, and never below 0. The payment's `amount_cents` is the annual fee minus the applied amount, the applied amount is added to the membership's `reward_redeemed_cents`, and a `RewardLedgerEntry` of type `REDEMPTION` carrying the negative applied amount is written when the applied amount is positive. If the requested `redeem_reward_cents` exceeds the available reward for the current term, the request is rejected with `ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE` (HTTP 422).

The cancellation refund, computed when an `ACTIVE` membership is cancelled, is the prorated unused fraction of the current term's annual fee. The term is 365 days. The elapsed days are the whole days between `term_start_utc` and the current clock instant, taken as the floor of the elapsed duration in whole days. The remaining days are 365 minus the elapsed days, but never below 0. The gross refund applies block rounding: the plan's `annual_fee_cents` multiplied by the remaining days and then floor-divided by 365. Because reward already redeemed against this term's fee is not refundable, the net refund is the gross refund minus the membership's `reward_redeemed_cents`, never below 0. At the boundaries, cancelling on the same day as activation leaves all 365 days remaining and refunds the full annual fee (less any redeemed reward), while cancelling once 365 or more days have elapsed leaves no days remaining and refunds nothing.

### 3.9. Reading Memberships, Ledgers, and Fees

A membership read recomputes and returns the derived reward, fee, and household-card fields so callers always see a reconciled view. Reward ledger entries can be listed and filtered by `membership_id`, by `source_transaction_id`, or by `entry_type`, giving full reverse-reachability from a transaction to the movements it caused. Fee events can be listed and filtered by `membership_id` or by `kind`. Members see only their own membership, cards, payments, returns, ledger entries, and fee events, while a `ClubAdmin` can list all memberships.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act on an existing resource, including the clock-set capability and the state-transition actions, return `200 OK`. The logical-clock endpoint is an administrative test-driving capability that advances the clock to a supplied `to_iso8601` instant.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ClubAdmin |
| POST | `/plans` | Create a membership plan | ClubAdmin |
| GET | `/plans` | List membership plans | ClubAdmin, Member, RegisterClerk, ServiceDeskClerk |
| GET | `/plans/{planId}` | Get a plan | ClubAdmin, Member, RegisterClerk, ServiceDeskClerk |
| POST | `/memberships` | Sign up a new membership | Anonymous, ClubAdmin |
| GET | `/memberships/{membershipId}` | Get a membership | ClubAdmin, Member, RegisterClerk, ServiceDeskClerk |
| GET | `/memberships` | List memberships | ClubAdmin |
| POST | `/memberships/{membershipId}/renew` | Renew or reinstate a membership | Member, ClubAdmin |
| POST | `/memberships/{membershipId}/cancel` | Cancel a membership with prorated refund | Member, ClubAdmin |
| POST | `/payments` | Settle a signup or renewal payment | Member, ClubAdmin |
| GET | `/payments` | List payments | ClubAdmin, Member |
| POST | `/household-cards` | Add a household card | Member, ClubAdmin |
| GET | `/household-cards` | List household cards | ClubAdmin, Member |
| GET | `/household-cards/{cardId}` | Get a household card | ClubAdmin, Member |
| POST | `/household-cards/{cardId}/revoke` | Revoke a household card | Member, ClubAdmin |
| POST | `/products` | Create a product | ClubAdmin |
| GET | `/products` | List products | ClubAdmin, Member, RegisterClerk, ServiceDeskClerk |
| GET | `/products/{productId}` | Get a product | ClubAdmin, Member, RegisterClerk, ServiceDeskClerk |
| POST | `/instant-savings` | Create an instant saving or manufacturer rebate | ClubAdmin |
| GET | `/instant-savings` | List instant savings | ClubAdmin, RegisterClerk, Member, ServiceDeskClerk |
| POST | `/transactions` | Open a transaction | RegisterClerk, ClubAdmin |
| GET | `/transactions/{transactionId}` | Get a transaction | ClubAdmin, RegisterClerk, Member, ServiceDeskClerk |
| GET | `/transactions` | List transactions | ClubAdmin, RegisterClerk, Member, ServiceDeskClerk |
| POST | `/transactions/{transactionId}/lines` | Add a line to an open transaction | RegisterClerk, ClubAdmin |
| GET | `/transactions/{transactionId}/lines` | List lines of a transaction | ClubAdmin, RegisterClerk, Member, ServiceDeskClerk |
| POST | `/transactions/{transactionId}/finalize` | Finalize a transaction | RegisterClerk, ClubAdmin |
| POST | `/transactions/{transactionId}/void` | Void a transaction | RegisterClerk, ClubAdmin |
| POST | `/returns` | Create a return | ServiceDeskClerk, ClubAdmin |
| GET | `/returns/{returnId}` | Get a return | ClubAdmin, ServiceDeskClerk, Member |
| GET | `/returns` | List returns | ClubAdmin, ServiceDeskClerk, Member |
| POST | `/returns/{returnId}/approve` | Approve a return | ServiceDeskClerk, ClubAdmin |
| POST | `/returns/{returnId}/reject` | Reject a return | ServiceDeskClerk, ClubAdmin |
| GET | `/reward-ledger` | List reward ledger entries | ClubAdmin, Member |
| GET | `/fee-events` | List fee events | ClubAdmin, Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_MEMBERSHIP_VERSION` | 412 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_TRANSACTION_NOT_OPEN` | 409 |
| `ERR_RETURN_NOT_PENDING` | 409 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_ONLY_PRODUCT` | 403 |
| `ERR_PURCHASE_LIMIT_EXCEEDED` | 409 |
| `ERR_HOUSEHOLD_CARD_LIMIT` | 409 |
| `ERR_NO_RECEIPT_LOOKUP_DENIED` | 409 |
| `ERR_RETURN_QTY_EXCEEDS_PURCHASED` | 409 |
| `ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE` | 422 |
| `ERR_EMPTY_TRANSACTION` | 409 |
| `ERR_PRODUCT_SKU_DUPLICATE` | 409 |
| `ERR_PAYMENT_PURPOSE_MISMATCH` | 409 |
| `ERR_INVALID_PROMO_WINDOW` | 400 |
| `ERR_INVALID_PRICE` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_CARD_KIND_INVALID` | 400 |
