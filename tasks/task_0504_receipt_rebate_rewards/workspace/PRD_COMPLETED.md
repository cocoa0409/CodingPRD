# Receipt-Rebate Rewards API — Product Requirements Document

## 1. Introduction

This document specifies a cashback and receipt-rebate rewards platform in the spirit of Rakuten and Ibotta. Members earn money back on their purchases in two complementary ways: by following an affiliate link before shopping online, and by uploading a photographed receipt for an in-store purchase. The platform tracks each merchant's cashback rates, attributes purchases to the channel that drove them, holds rewards through a return window, and ultimately lets members withdraw their accumulated balance through PayPal, a mailed check, or a gift card.

The business challenge the system solves is reconciliation under uncertainty. A reward is not real money the moment it is earned — a shopper may return the goods, an offer may expire, or a receipt may turn out to be fraudulent. Every reward therefore moves through a deliberate lifecycle, from a provisional pending state, through a matured available balance, into a reserved-and-paid settlement, with compensating reversals available at each stage. A member's wallet balances are never stored as authoritative numbers; they are continuously **derived** from the underlying log of reward claims, with an append-only ledger maintained alongside as an audit mirror. Layered on top are referral incentives, weekly activity streak bonuses, per-method withdrawal thresholds, and a "double-dip" guard that prevents a member from being paid twice for the same shopping trip.

The remainder of this document defines the global contracts every endpoint obeys (Section 2), the detailed business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). Implementers should treat Section 2 as precise, non-negotiable structural contract and Section 3 as the authoritative source of business behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting principal, and `X-User-Role`, one of the four recognized role names. The recognized roles are exactly `PlatformAdmin`, `ReviewAgent`, `FinanceAdmin`, and `Member`. If `X-User-Role` is missing or does not name one of these four roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are peers, each owning a distinct slice of the platform. A `PlatformAdmin` configures merchants and offers and may seed members, click-throughs, receipt scans, reward claims, and referrals on behalf of operations. A `ReviewAgent` reviews uploaded receipts — starting review, approving, and rejecting. A `FinanceAdmin` runs the payout pipeline: member verification and suspension, forced maturation, return clawbacks, cash-out processing and settlement, and referral payouts. A `Member` is the end user who clicks affiliate links, uploads receipts, owns reward claims, and requests cash-outs against their own wallet.

Three of these roles are operator identities. When `X-User-Role` is `PlatformAdmin`, `ReviewAgent`, or `FinanceAdmin`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`. The `Member` role, by contrast, is entity-backed: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` row, and ownership checks compare a resource's member foreign key to `X-User-ID`. Concretely, when a `Member` requests a cash-out, the `member_id` in the request must equal `X-User-ID`; likewise, when a `Member` self-registers, records a click, uploads a receipt, files a reward claim, or sends a referral invite, the `member_id` (or `referrer_member_id`) they supply must be the member they themselves own. A `Member` may read their own members record, ledger entries, bonus streak, reward claims, cash-outs, referrals, receipt scans, and click-throughs.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and may not be negative. A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400). Each list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, where `total_count` is the number of matching records before pagination and `has_more` is true when records remain beyond the current page. Unless an endpoint explicitly states otherwise, list results are sorted by `created_at` in ascending order (oldest first).

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by one on each mutation that changes the resource.

Three entity types are append-only and therefore carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version`. These are the `ClickThrough` (an affiliate-click event), the `LedgerEntry` (an audit-log line), and the `ReturnEvent` (a reported return). All other entities — `Merchant`, `Offer`, `Member`, `ReceiptScan`, `RewardClaim`, `CashOut`, `Referral`, and `BonusStreak` — carry the full set of common fields including `updated_at` and `version`.

### 2.5. Monetary Precision and the Cents Convention

All monetary amounts are integer counts of cents; the system never stores fractional cents. Cashback rates are expressed in **basis points**, where 100 basis points equal one percent and 10,000 basis points equal 100 percent. Wherever a percentage of a purchase is computed, the result is floored (truncated toward zero) to whole cents, and where a calculation sums a percentage component with a flat component, each percentage component is floored on its own **before** any sum is taken (per-component floor, then add). The lone exception that rounds rather than floors is the streak bonus, which rounds each week's accrual half-up to the nearest cent before summing (detailed in Section 3). Wallet-balance aggregation involves no rounding at all — it is an exact sum of integer cents.

### 2.6. The Derived-Wallet Principle

A `Member`'s wallet figures are never authoritative stored numbers; they are derived on demand from that member's `RewardClaim` rows. Five balance fields are reported on the member record: `pending_balance_cents` is the sum of `amount_cents` over the member's claims in `PENDING`; `available_balance_cents` is the sum of `amount_cents` over claims in `AVAILABLE` only (it deliberately excludes reserved claims); `reserved_balance_cents` is the sum of `amount_cents` over claims in `RESERVED`; `net_cashoutable_cents` equals `available_balance_cents` (the unreserved available total is the only money a new cash-out may draw against, so a reserved claim shrinks the drawable amount even while the gross available figure is unchanged); and `lifetime_paid_cents` is the sum of `amount_cents` over claims in `PAID`. There also exists a gross available view — the sum of `amount_cents` over claims in either `AVAILABLE` or `RESERVED` — which is the gross figure including amounts already reserved by an open cash-out; the per-member balance fields reported to the user use the unreserved figures described above.

Alongside these derived figures the system maintains an append-only `LedgerEntry` log, one entity per member-affecting event, as an **audit mirror** — it records what happened but is not itself the source of the balance numbers. Every `LedgerEntry` carries a `member_id`, an `entry_type`, a signed `amount_cents`, and optional references `reward_claim_id`, `cashout_id`, and `referral_id` pointing at whichever entity occasioned it. The eight entry types are `CLAIM_PENDING`, `CLAIM_MATURED`, `CLAIM_CLAWBACK`, `CLAIM_EXPIRED`, `CASHOUT_DEBIT`, `CASHOUT_REVERSAL`, `REFERRAL_BONUS`, and `STREAK_BONUS`. The sign convention is fixed: `CLAIM_PENDING` and `CLAIM_MATURED` are informational and carry the claim's positive `amount_cents` but represent no net wallet move at maturity (maturity merely shifts a claim from pending to available); `REFERRAL_BONUS` and `STREAK_BONUS` are positive; `CLAIM_CLAWBACK`, `CLAIM_EXPIRED`, and `CASHOUT_DEBIT` are negative; and `CASHOUT_REVERSAL` is positive.

### 2.7. State Propagation, Versioning, and Cascades

Many operations touch more than one entity. Whenever a state transition or computed change mutates an entity, that entity's `version` increments by one and its `updated_at` is refreshed (except on the append-only entities, which never mutate). When an operation cascades — for example, approving a receipt spawns a reward claim, or settling a cash-out moves several claims at once — each entity touched along the cascade is mutated independently, and the precise cascade steps for each workflow are spelled out in Section 3. The wallet balances described in Section 2.6 are recomputed implicitly from the claim rows after any cascade, so they always reflect the current claim states.

### 2.8. Optimistic Concurrency on Cash-Out Creation

Cash-out creation is the one write that is guarded by optimistic concurrency on the member's wallet. A request to create a cash-out must carry `expected_member_version`, the `version` of the owning `Member` that the client last observed. Because creating a cash-out reserves available claims and is computed against the member's `net_cashoutable_cents`, the platform must be sure the client's view of the wallet is current. If another writer has advanced the member's `version` since the client last read it — by maturing, clawing back, or expiring a claim, by opening a competing cash-out, or by any other member-mutating action — then `expected_member_version` will no longer match the member's current `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This forces the client to re-read the member before reserving, so it never overwrites a wallet state it has not observed. No other endpoint accepts or requires a version field.

### 2.9. Reference Resolution and Path Validation

Path-referenced resources are validated left to right: for a nested path, each segment's resource must exist before the next is considered, and the first missing one yields `ERR_NOT_FOUND` (HTTP 404). Foreign keys supplied in a request body — namely `merchant_id`, `offer_id`, `member_id`, `reward_claim_id`, `click_through_id`, and `receipt_scan_id` — must resolve to existing rows; an unresolvable body reference yields `ERR_REFERENCE_NOT_FOUND` (HTTP 422). This body-FK resolution check applies to creating click-throughs, receipt scans, reward claims, cash-outs, return events, offers, and referrals.

### 2.10. The Logical Clock

The platform runs on a logical clock rather than wall-clock time, so that time-dependent transitions can be exercised deterministically. At server startup the clock reads `2026-01-01T00:00:00Z`, which is before all default fixtures, and it never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant via the field `to_iso8601`. Advancing the clock fires every due time-based transition: pending claims whose maturation instant has been reached become available, available claims whose expiry instant has been reached expire, invited referrals past their expiry deadline expire, and offers past their `expires_at` become `EXPIRED`. Each maturation triggered this way also recomputes the affected member's bonus streak.

### 2.11. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Then path existence is checked, yielding `ERR_NOT_FOUND` for a missing path resource. Then body foreign-key resolution is checked, yielding `ERR_REFERENCE_NOT_FOUND`. Then body well-formedness is checked — required fields present, enum values valid, and integers non-negative where constrained — yielding `ERR_VALIDATION` (HTTP 400). Only after these structural checks pass does the system evaluate state validity (yielding `ERR_INVALID_STATE`, HTTP 409, when the target resource is not in a state from which the requested transition is legal), then the optimistic-concurrency check on cash-out creation (`ERR_STALE_VERSION`), and finally the domain-specific business rules described throughout Section 3. In short, identity precedes existence, existence precedes shape, shape precedes state, and state precedes business policy.

## 3. Business Logic & Workflows

### 3.1. Configuring Merchants and Offers

Everything begins with a merchant. A `PlatformAdmin` creates a merchant by supplying its `name`, its `online_rate_bps` (the base cashback rate, in basis points, for online click-attributed purchases), and its `instore_rate_bps` (the base rate for in-store receipt-attributed purchases). Both rate fields accept basis-point values from 0 through 10,000 inclusive. Three further settings are optional with defaults. The `attribution_window_hours` is the number of hours after a click during which an online purchase may still be tied to that click; it must be at least 1 and defaults to 168 (one week). The `double_dip_allowed` flag defaults to false; when false, a single qualifying purchase may earn either a click-attributed reward or a receipt-rebate reward but not both, and when true the two may stack. The `maturity_hold_days` is the number of days a reward claim stays pending before auto-maturing — the return window — and must be at least 0, defaulting to 30. A newly created merchant has `status` `ACTIVE`. A `PlatformAdmin` may later disable a merchant, moving its `status` to `DISABLED`; a disabled merchant rejects new claims, receipts, and clicks with `ERR_MERCHANT_DISABLED` (HTTP 409). Merchants are readable by all four roles, and the merchant list may be filtered by `status`.

Offers live under a merchant and are also created by a `PlatformAdmin`. An offer's `merchant_id` names the merchant it belongs to, and its `offer_type` is one of two kinds. A `LINKED` offer attaches a `bonus_rate_bps` (extra basis points, 0 through 10,000, stacked on the merchant's online base rate, default 0) and is rewarded through the online channel. A `RECEIPT_REBATE` offer attaches a flat `rebate_cents` (the rebate amount in cents per qualifying receipt, at least 0, default 0) and is rewarded when a scanned receipt is approved. Either kind may set a `min_spend_cents` floor (the minimum purchase amount in cents required for the offer to apply, at least 0, default 0). Every offer carries an activation instant `starts_at` and an expiry instant `expires_at`, both ISO 8601 UTC. A freshly created offer has `status` `ACTIVE`; when the logical clock crosses `expires_at` the offer becomes `EXPIRED`. Offers are readable by all roles and may be listed filtered by `merchant_id`, `offer_type`, or `status`.

### 3.2. Member Onboarding, Verification, and Suspension

A member self-registers (or is seeded by a `PlatformAdmin`) by supplying an `email` (the member's identifying address; while emails are expected to be distinct, uniqueness is not enforced on registration — a duplicate email is accepted and yields a separate member row) and optionally a `referred_by_member_id` naming the referrer who invited them. A new member starts with `account_status` `ACTIVE`, `verification_status` `UNVERIFIED`, and all wallet balances at zero. If the member registers with a `referred_by_member_id` and there is a matching outstanding referral invite addressed to that member's email from that referrer, the referral advances from `INVITED` to `SIGNED_UP` (see Section 3.7). Members are readable by all four roles via the single-member read, while the members list — filterable by `referred_by_member_id`, `account_status`, or `verification_status` — is restricted to `PlatformAdmin` and `FinanceAdmin`.

A member carries two **independent** status dimensions that evolve on the same record. The verification dimension moves `UNVERIFIED` to `VERIFIED` when a `FinanceAdmin` verifies the member. The account dimension moves `ACTIVE` to `SUSPENDED` when a `FinanceAdmin` suspends the member, and back from `SUSPENDED` to `ACTIVE` when a `FinanceAdmin` reinstates them. Each of verify, suspend, and reinstate increments the member's `version` by one. The two dimensions gate operations as a product of both: for example, paying out a cash-out requires the account dimension to be `ACTIVE` and the verification dimension to be `VERIFIED` simultaneously. Suspending a member is deliberately gentle toward money already in flight — any of the member's claims that are `RESERVED` and locked by a cash-out in `REQUESTED` status are left intact, and that cash-out may still be processed to completion.

### 3.3. Earning Online: Clicks and Click-Attributed Claims

The online earning path starts with an affiliate click. A `Member` (or a `PlatformAdmin` on their behalf) records a click-through by supplying the `member_id` who clicked and the `merchant_id` they clicked through to, plus optionally the `offer_id` of the `LINKED` offer in context at click time. The server stamps `clicked_at` from the current logical clock; the click-through is an append-only event carrying only its `id` and `created_at` beyond these fields.

When the member completes an online purchase, a click-attributed reward claim is filed by supplying the `member_id`, the `merchant_id`, the `click_through_id` of the qualifying click, the `purchase_amount_cents` (the qualifying spend, at least 0), and optionally the `offer_id` of a linked offer to apply. For the claim to be online-attributable, a click-through must exist for that member and merchant whose `clicked_at` falls within the merchant's `attribution_window_hours` before the claim; if no such qualifying click exists within the window, the claim is rejected with `ERR_ATTRIBUTION_WINDOW_EXPIRED` (HTTP 409). The created claim is fixed to `ONLINE` attribution and begins life in `PENDING`. If an `offer_id` is supplied, that offer must be `ACTIVE` and the current clock must fall within its `starts_at` and `expires_at` window, inclusive; otherwise the claim is rejected with `ERR_OFFER_INACTIVE` (HTTP 409). These business checks are evaluated in the order: merchant-disabled (`ERR_MERCHANT_DISABLED`) first, then the supplied offer's active-window (`ERR_OFFER_INACTIVE`), then the attribution-window (`ERR_ATTRIBUTION_WINDOW_EXPIRED`) — so when more than one is unsatisfiable the earlier one in this list is the error returned. Creating an online claim emits a ledger entry of type `CLAIM_PENDING`, and the claim's maturation and expiry instants are computed at creation as described in Section 3.5.

The online reward amount, locked into `amount_cents` at creation and never recomputed afterward, is built from the merchant's online rate and any linked-offer bonus. Begin with the merchant's `online_rate_bps` as the base. If an offer is present, it is a `LINKED` offer, and `purchase_amount_cents` is at least the offer's `min_spend_cents`, then the effective rate is the base plus the offer's `bonus_rate_bps`; otherwise the effective rate is just the base. The effective rate is then capped at no more than the combined-rate ceiling of 5,000 basis points (a hard 50.00% cap). Finally, `amount_cents` is `purchase_amount_cents` multiplied by the capped rate in basis points, divided by 10,000, with the result floored to whole cents. The online variant uses only rates and bonus basis points; it ignores any `rebate_cents`.

### 3.4. Earning In Store: Receipt Scans and Their Review

The in-store earning path is mediated by receipt review. A `Member` (or `PlatformAdmin`) uploads a receipt by supplying the `member_id`, the `merchant_id` the receipt is from, the `offer_id` of the `RECEIPT_REBATE` offer being claimed, the `purchase_total_cents` (the receipt grand total, at least 0), and the `purchased_at` instant printed on the receipt. A new receipt scan begins in `SUBMITTED`.

A `ReviewAgent` drives the receipt through its lifecycle. Moving a receipt from `SUBMITTED` to `IN_REVIEW` (starting review) requires that the referenced offer be `ACTIVE` and that the current clock fall within the offer's `starts_at` and `expires_at` window, inclusive; if not, the transition is rejected with `ERR_OFFER_INACTIVE`. From `IN_REVIEW` the reviewer may reject the receipt, moving it to `REJECTED` and recording the optional `review_note`; a rejected receipt is not terminal — it may be re-reviewed, transitioning `REJECTED` back to `IN_REVIEW` (subject to the same offer-active precondition as the first start-review). The reviewer may instead approve the receipt, moving `IN_REVIEW` to `APPROVED`, the one terminal state of the receipt machine. The optional `review_note` may also be recorded on approval.

Approval is guarded by three preconditions, evaluated in this order: first, the receipt's `purchase_total_cents` must be at least the offer's `min_spend_cents`, else `ERR_MIN_SPEND_NOT_MET` (HTTP 409); then the member's `account_status` must be `ACTIVE`, else `ERR_MEMBER_SUSPENDED` (HTTP 409); then, if the merchant's `double_dip_allowed` is false, there must be no existing non-clawed-back reward claim with `ONLINE` attribution for the same member and merchant whose underlying click's `clicked_at` is within 24 hours of the receipt's `purchased_at`, else `ERR_DOUBLE_DIP_BLOCKED` (HTTP 409). (The start-review transition itself is also subject to the offer-active rule above, so `ERR_OFFER_INACTIVE` can surface both at start-review and at approve.) When all three approval preconditions pass, approval cascades in two steps: step one creates a new reward claim for this member, merchant, and offer with `IN_STORE` attribution, beginning in `PENDING`, whose `amount_cents` is computed by the in-store variant below; step two emits a `CLAIM_PENDING` ledger entry for that new claim. The receipt's `reward_claim_id` is then set to the new claim's `id`. Receipt scans are readable by all four roles and may be listed filtered by `member_id`, `merchant_id`, `offer_id`, `reward_claim_id`, or `status`.

The in-store reward amount, again locked at creation, combines a percentage component with a flat rebate. Compute the percentage component as `purchase_amount_cents` multiplied by the merchant's `instore_rate_bps`, divided by 10,000, floored to whole cents. Then determine the flat component: if the offer's `offer_type` is `RECEIPT_REBATE` and `purchase_amount_cents` is at least the offer's `min_spend_cents`, the flat component is the offer's `rebate_cents`; otherwise it is 0. The reward `amount_cents` is the sum of the flat component and the floored percentage component, but capped so it never exceeds `purchase_amount_cents` — that is, take the smaller of the sum and the purchase amount. The in-store variant uses the in-store rate plus the flat rebate; it ignores any linked `bonus_rate_bps`. (For an in-store claim spawned from a receipt, `purchase_amount_cents` is the receipt's purchase total.)

### 3.5. The Reward Claim Lifecycle: Maturation, Reservation, Payment, and Expiry

A reward claim — whether born online, in store, or as a referral bonus — carries a `member_id`, a `merchant_id`, an optional `offer_id`, an optional `click_through_id` (for online attribution) and an optional `receipt_scan_id` (for in-store attribution), an `attribution` of `ONLINE` or `IN_STORE`, the `purchase_amount_cents` it was computed from, the locked `amount_cents`, and a `status`. It also carries two computed instants: `matures_at` is `created_at` plus the merchant's `maturity_hold_days`, and `expires_at` is `matures_at` plus the platform-wide available-claim expiry window (a fixed number of days that an available claim may remain uncashed before it expires; this window is 90 days). An optional `cashout_id` records which cash-out has reserved or paid the claim, and is null until reserved. Reward claims are readable by all four roles and may be listed filtered by `member_id`, `merchant_id`, `offer_id`, `click_through_id`, `receipt_scan_id`, `cashout_id`, or `status`.

A claim begins `PENDING` — provisional, inside the return window. Once the logical clock reaches the claim's `matures_at`, the claim matures to `AVAILABLE`. Maturation may fire automatically when the clock advances, or a `FinanceAdmin` may force it for a pending claim that has already reached `matures_at`; the forced path is idempotent with the clock-driven one. The forced-maturation endpoint rejects a claim already in a terminal state (`PAID`, `CLAWED_BACK`, or `EXPIRED`) with `ERR_CLAIM_ALREADY_TERMINAL`, and rejects a claim that is non-terminal but not maturable — one not in `PENDING` (e.g. already `AVAILABLE` or `RESERVED`), or one still `PENDING` whose `matures_at` the clock has not yet reached — with `ERR_INVALID_STATE`. Maturation emits a `CLAIM_MATURED` ledger entry carrying the positive `amount_cents`, shifts the value from the member's pending balance into the available balance, and recomputes the owning member's bonus streak, since a newly available claim may extend the member's weekly streak. A claim that matures becomes part of `net_cashoutable_cents` and thus eligible for cash-out.

An `AVAILABLE` claim that is never cashed out eventually expires: when the clock reaches its `expires_at` and the claim is still `AVAILABLE` (unreserved), it transitions to `EXPIRED`, a terminal state, emitting a `CLAIM_EXPIRED` ledger entry for the negative `amount_cents` and reducing the member's available balance by `amount_cents`. When a cash-out reserves a claim, the claim moves `AVAILABLE` to `RESERVED`, its `cashout_id` is set to the reserving cash-out, the member's reserved balance rises and `net_cashoutable_cents` falls correspondingly. The reservation precondition is that the claim is `AVAILABLE` and not already reserved by another cash-out. From `RESERVED` a claim follows its cash-out's fate (Section 3.6): if the cash-out is paid the claim moves `RESERVED` to `PAID` (terminal), decreasing reserved balance and increasing `lifetime_paid_cents`; if the cash-out fails the claim reverts `RESERVED` to `AVAILABLE`, its `cashout_id` is cleared, reserved balance falls and `net_cashoutable_cents` rises again.

### 3.6. Cashing Out: Reservation, Thresholds, Processing, and Settlement

When a member wishes to withdraw, they request a cash-out, an operation reserved to the `Member` role acting on their own wallet. The request supplies the `member_id`, the `method` (one of `PAYPAL`, `CHECK`, or `GIFT_CARD`), the `requested_amount_cents` (the gross amount to withdraw, at least 1), and `expected_member_version` for the concurrency check of Section 2.8 (this supplied `expected_member_version` is also retained on the created cash-out and echoed back as a field of the cash-out resource). The member must not be suspended: if `account_status` is `SUSPENDED`, creation is rejected with `ERR_MEMBER_SUSPENDED`. Two threshold checks then apply, both inclusive at their boundaries. The requested amount must be at least the per-method minimum — 500 cents ($5.00) for `PAYPAL`, 2,500 cents ($25.00) for `CHECK`, and 1,000 cents ($10.00) for `GIFT_CARD`; a request exactly at the minimum is allowed, and one below it is rejected with `ERR_BELOW_CASHOUT_MINIMUM` (HTTP 422). The requested amount must also be no greater than the member's `net_cashoutable_cents`; an amount exceeding it is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 422).

A new cash-out begins in `REQUESTED`. On creation it reserves the member's `AVAILABLE` claims, oldest by `created_at` first, accumulating until the reserved claims sum to at least `requested_amount_cents`; each reserved claim moves to `RESERVED` and has its `cashout_id` set, and the member's `version` increments by one. If no set of available claims can sum to `requested_amount_cents`, the creation is rejected with `ERR_CASHOUT_NOT_RESERVABLE` (HTTP 409). The cash-out's `fee_cents` and `net_payout_cents` are computed at creation by the fee schedule below.

A `FinanceAdmin` runs the rest of the pipeline. Processing moves a cash-out `REQUESTED` to `PROCESSING`, and requires that the member's `account_status` be `ACTIVE` (else `ERR_MEMBER_SUSPENDED`) and `verification_status` be `VERIFIED` (else `ERR_MEMBER_NOT_VERIFIED`, HTTP 409). Settlement moves a `PROCESSING` cash-out to one of two outcomes via a supplied `outcome` field. When `outcome` is `PAID`, the cash-out becomes `PAID` (its terminal state), a `CASHOUT_DEBIT` ledger entry is emitted for the negative `requested_amount_cents`, every claim whose `cashout_id` equals this cash-out moves `RESERVED` to `PAID`, the member's reserved balance falls, and `lifetime_paid_cents` rises. When `outcome` is `FAILED`, the cash-out becomes `FAILED`, every claim it reserved reverts `RESERVED` to `AVAILABLE` with its `cashout_id` cleared, and the member's reserved balance falls while `net_cashoutable_cents` rises. A `FAILED` cash-out is not terminal: a `FinanceAdmin` may retry it, transitioning `FAILED` to `REQUESTED`, provided the member's `net_cashoutable_cents` is at least the cash-out's `requested_amount_cents` at retry time (else `ERR_INSUFFICIENT_BALANCE`); retry re-reserves available claims up to `requested_amount_cents`, oldest `created_at` first, moving each `AVAILABLE` to `RESERVED`, raising reserved balance and lowering `net_cashoutable_cents`. Cash-outs are readable by `PlatformAdmin`, `FinanceAdmin`, and the owning `Member`, and may be listed filtered by `member_id`, `status`, or `method`.

The fee and payout are computed at cash-out creation with the evaluation order pinned to keep the figures well-defined. Step one selects the fee tier keyed on the gross `requested_amount_cents` (never on the net): for `PAYPAL` and `GIFT_CARD` the flat portion is 0, while for `CHECK` the flat portion is 200 cents. For `PAYPAL` and `GIFT_CARD` a percentage tier also applies — if `requested_amount_cents` is at least the large-cash-out threshold of 5,000 cents ($50.00) the percentage rate is 0 (large cash-outs are fee-free), otherwise the percentage rate is the small-cash-out rate of 200 basis points (2.00%); for `CHECK` the percentage rate is 0. Step two computes `fee_cents` as the flat portion plus the floor of `requested_amount_cents` multiplied by the percentage basis points divided by 10,000. Step three computes `net_payout_cents` as `requested_amount_cents` minus `fee_cents`. Because the tier is keyed strictly on the gross requested amount and not on the net, the fee and payout are order-independent under this pinning.

### 3.7. Referrals and the Invite Lifecycle

A member grows the platform by inviting others. A `Member` (or `PlatformAdmin`) creates a referral by supplying the `referrer_member_id` who sends the invite and the `referee_email` the invite is addressed to, optionally overriding the `referee_qualifying_cents` (the cumulative reward the referee must reach to qualify, at least 0, default 1,000) and the `bonus_cents` (the bonus paid out when the referral is rewarded, at least 0, default 500). A new referral begins `INVITED`. A referral may not be created for a `referee_email` that already has a referral past the invited stage — if one already exists in `SIGNED_UP`, `QUALIFIED`, or `REWARDED`, creation is rejected with `ERR_DUPLICATE_REFERRAL` (HTTP 409).

The referral then advances through its branching lifecycle. When a member registers naming this referrer and with an email matching `referee_email`, and no other referral for that email is already past invited, the referral moves `INVITED` to `SIGNED_UP` and its `referee_member_id` is set to the new member. When that referee's cumulative qualifying reward — the sum of their reward cents in `AVAILABLE` plus `PAID` — reaches `referee_qualifying_cents`, the referral moves `SIGNED_UP` to `QUALIFIED`. A `FinanceAdmin` then rewards a qualified referral: rewarding requires the referral's `status` to be `QUALIFIED` (else `ERR_REFERRAL_NOT_QUALIFIED`, HTTP 409) and moves it `QUALIFIED` to `REWARDED`. Rewarding cascades in three steps: step one creates a reward claim for the **referrer** with `ONLINE` attribution, `amount_cents` equal to the referral's `bonus_cents`, and status `AVAILABLE` (already matured, not pending) — because this bonus claim is not tied to any merchant or shopping event, its `merchant_id`, `offer_id`, `click_through_id`, and `receipt_scan_id` are all null, its `purchase_amount_cents` is 0, its `matures_at` is the current clock instant, and its `expires_at` is null (a referral bonus claim never expires); step two emits a `REFERRAL_BONUS` ledger entry for that positive `bonus_cents`; step three raises the referrer's available balance by `bonus_cents`. Separately, a referral that is never accepted expires: when the clock reaches the referral's creation instant plus the platform-wide referral expiry window (a fixed number of days an invite may remain unaccepted; this window is 30 days) while it is still `INVITED`, it transitions `INVITED` to `EXPIRED`. Both `REWARDED` and `EXPIRED` are terminal. Referrals are readable by `PlatformAdmin`, `FinanceAdmin`, and the owning `Member`, and may be listed filtered by `referrer_member_id` or `referee_member_id`.

### 3.8. Weekly Activity Streaks and Their Bonus

The platform rewards consistent activity through a per-member bonus streak, one `BonusStreak` record per member, keyed on `member_id`. It tracks `current_streak_weeks` (consecutive weekly periods in which the member earned at least one available or paid claim, default 0), `longest_streak_weeks` (the maximum `current_streak_weeks` ever reached, default 0), `last_activity_week_index` (the week index of the most recent qualifying claim), and `pending_streak_bonus_cents` (the streak bonus accrued but not yet credited, default 0). A week is the Monday-through-Sunday UTC period; the week index is the number of whole weeks since the Monday epoch of 1970-01-05 — that is, the floor of the number of days since that Monday divided by seven. The `current_streak_weeks` is the count of consecutive week indexes, ending at the latest qualifying week, in which the member had at least one claim reach `AVAILABLE`. A week counts as qualifying based on the week-index at which a claim matured to `AVAILABLE`, recorded once at maturation; that week stays qualifying permanently even if the claim later leaves `AVAILABLE` (becoming `RESERVED`, `PAID`, `EXPIRED`, or `CLAWED_BACK`). The streak is recomputed whenever one of the member's claims matures from `PENDING` to `AVAILABLE`, since a newly available claim may extend the streak.

The streak bonus uses per-week rounding then summing, in that pinned order. For each week in the current streak, that week's bonus in cents is the base of 25 cents multiplied by the quantity (1 plus 0.5 times the week's position in the streak minus 1) — so the first week earns the plain base, the second week earns the base grown by 50%, the third by an additional 50% of base, and so on, each additional consecutive week adding 50% of the base to that week's bonus — and that per-week figure is rounded half-up to whole cents. The `pending_streak_bonus_cents` is the sum of those rounded per-week bonuses, recomputed in full on each maturation. The rounding order is pinned: round each week's bonus to whole cents first, then sum; summing first and rounding once would differ by up to a cent per week. This accrued figure is reported on the bonus-streak record but is never automatically credited to the wallet: no operation moves it into a balance and no `STREAK_BONUS` ledger entry is emitted, so the `STREAK_BONUS` entry type is reserved and remains unused. The bonus streak is readable by `PlatformAdmin`, `FinanceAdmin`, and the owning `Member`.

### 3.9. Returns, Clawbacks, and Their Cascades

When a member returns purchased goods, a `FinanceAdmin` reports it as a return event against the affected reward claim, supplying the `reward_claim_id` and the `returned_amount_cents` (the amount returned, at least 1). The server stamps `reported_at` from the current logical clock and computes the `clawback_cents` to reverse. A return may not be filed against a claim already in a terminal state — a claim in `PAID`, `CLAWED_BACK`, or `EXPIRED` rejects the return with `ERR_CLAIM_ALREADY_TERMINAL` (HTTP 409) — and the `returned_amount_cents` may not exceed the claim's `purchase_amount_cents`, else `ERR_RETURN_EXCEEDS_PURCHASE` (HTTP 422).

The clawback reverses the proportional share of the reward. The proportion is `returned_amount_cents` divided by the claim's `purchase_amount_cents`, clamped to the range 0 through 1, and `clawback_cents` is the claim's `amount_cents` multiplied by that proportion, rounded up (ceiling) so the platform never under-claws. A full return — where `returned_amount_cents` is at least the claim's `purchase_amount_cents` — claws back the entire `amount_cents`, so that the original reward credit and the clawback debit cancel exactly to zero.

Reporting a return moves the claim to `CLAWED_BACK` (terminal) and emits a `CLAIM_CLAWBACK` ledger entry for the negative `clawback_cents`, with the precise cascade depending on the claim's state at the time. A return against a `PENDING` claim (before maturity) moves it `PENDING` to `CLAWED_BACK` and reduces the member's pending balance by `clawback_cents`. A return against an `AVAILABLE` claim (matured but not yet reserved) moves it `AVAILABLE` to `CLAWED_BACK` and reduces the member's available balance by `clawback_cents`. A return against a `RESERVED` claim — one locked by a cash-out still in `REQUESTED` or `PROCESSING` — is the most far-reaching: the claim moves `RESERVED` to `CLAWED_BACK`, and then three cross-entity cascade steps follow. Step one transitions the owning cash-out to `FAILED`. Step two reverts every other claim that cash-out had reserved from `RESERVED` back to `AVAILABLE`. Step three recomputes the member's reserved and available balances accordingly. Return events are an append-only record carrying only their `id` and `created_at` beyond the fields above, are readable by `PlatformAdmin`, `FinanceAdmin`, and `Member`, and may be listed filtered by `reward_claim_id`.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2 and the validation ordering of Section 2.11. Creating a new resource returns HTTP 201 with the created resource in `data`; reads and state-changing actions on an existing resource return HTTP 200 with the affected resource (the clock-set capability returns 200 with an empty object). List endpoints return 200 with an array. Request bodies, response bodies, and side effects for each endpoint are defined by the narratives of Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/merchants` | Create a merchant configuration | PlatformAdmin |
| GET | `/merchants/{id}` | Get a merchant | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| GET | `/merchants` | List merchants (paginated) | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| POST | `/merchants/{id}/disable` | Disable a merchant (rejects new claims) | PlatformAdmin |
| POST | `/offers` | Create an offer under a merchant | PlatformAdmin |
| GET | `/offers/{id}` | Get an offer | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| GET | `/offers` | List offers; filter by merchant_id, offer_type, status | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| POST | `/members` | Register a member | PlatformAdmin, Member |
| GET | `/members/{id}` | Get a member (includes computed wallet balances) | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| GET | `/members` | List members; filter by referred_by_member_id, account_status, verification_status | PlatformAdmin, FinanceAdmin |
| POST | `/members/{id}/verify` | Mark a member VERIFIED | FinanceAdmin |
| POST | `/members/{id}/suspend` | Suspend a member | FinanceAdmin |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | FinanceAdmin |
| GET | `/members/{id}/ledger-entries` | List a member's ledger entries | PlatformAdmin, FinanceAdmin, Member |
| GET | `/ledger-entries` | List ledger entries; filter by member_id, reward_claim_id, cashout_id, referral_id, entry_type | PlatformAdmin, FinanceAdmin, Member |
| GET | `/ledger-entries/{id}` | Get a single ledger entry | PlatformAdmin, FinanceAdmin, Member |
| GET | `/members/{id}/bonus-streak` | Get the member's bonus streak | PlatformAdmin, FinanceAdmin, Member |
| POST | `/clickthroughs` | Record an affiliate click | Member, PlatformAdmin |
| GET | `/clickthroughs/{id}` | Get a click-through event | PlatformAdmin, FinanceAdmin, Member |
| GET | `/clickthroughs` | List click-throughs; filter by member_id, merchant_id, offer_id | PlatformAdmin, FinanceAdmin, Member |
| POST | `/receipt-scans` | Upload a receipt to claim a receipt-rebate offer | Member, PlatformAdmin |
| GET | `/receipt-scans/{id}` | Get a receipt scan | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| GET | `/receipt-scans` | List receipt scans; filter by member_id, merchant_id, offer_id, reward_claim_id, status | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| POST | `/receipt-scans/{id}/start-review` | Move a receipt to in-review (also resubmit from rejected) | ReviewAgent |
| POST | `/receipt-scans/{id}/approve` | Approve a receipt; cascades creation of an in-store reward claim | ReviewAgent |
| POST | `/receipt-scans/{id}/reject` | Reject a receipt | ReviewAgent |
| POST | `/reward-claims` | Create an online (click-attributed) reward claim | Member, PlatformAdmin |
| GET | `/reward-claims/{id}` | Get a reward claim | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| GET | `/reward-claims` | List reward claims; filter by member_id, merchant_id, offer_id, click_through_id, receipt_scan_id, cashout_id, status | PlatformAdmin, ReviewAgent, FinanceAdmin, Member |
| POST | `/reward-claims/{id}/mature` | Force a pending matured claim to available | FinanceAdmin |
| POST | `/return-events` | Report a return against a reward claim | FinanceAdmin |
| GET | `/return-events` | List return events; filter by reward_claim_id | PlatformAdmin, FinanceAdmin, Member |
| GET | `/return-events/{id}` | Get a single return event | PlatformAdmin, FinanceAdmin, Member |
| POST | `/cashouts` | Request a cash-out; reserves available claims; OCC on member version | Member |
| GET | `/cashouts/{id}` | Get a cash-out | PlatformAdmin, FinanceAdmin, Member |
| GET | `/cashouts` | List cash-outs; filter by member_id, status, method | PlatformAdmin, FinanceAdmin, Member |
| POST | `/cashouts/{id}/process` | Move a cash-out to processing (requires member active and verified) | FinanceAdmin |
| POST | `/cashouts/{id}/settle` | Settle a processing cash-out (outcome paid or failed) | FinanceAdmin |
| POST | `/cashouts/{id}/retry` | Retry a failed cash-out | FinanceAdmin |
| POST | `/referrals` | Create a referral invite | Member, PlatformAdmin |
| GET | `/referrals/{id}` | Get a referral | PlatformAdmin, FinanceAdmin, Member |
| GET | `/referrals` | List referrals; filter by referrer_member_id, referee_member_id, status | PlatformAdmin, FinanceAdmin, Member |
| POST | `/referrals/{id}/reward` | Pay out a qualified referral | FinanceAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a fixed UTC instant | PlatformAdmin, FinanceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_OFFER_INACTIVE | 409 |
| ERR_DOUBLE_DIP_BLOCKED | 409 |
| ERR_ATTRIBUTION_WINDOW_EXPIRED | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_MEMBER_NOT_VERIFIED | 409 |
| ERR_MIN_SPEND_NOT_MET | 409 |
| ERR_BELOW_CASHOUT_MINIMUM | 422 |
| ERR_INSUFFICIENT_BALANCE | 422 |
| ERR_MERCHANT_DISABLED | 409 |
| ERR_CLAIM_ALREADY_TERMINAL | 409 |
| ERR_RETURN_EXCEEDS_PURCHASE | 422 |
| ERR_REFERRAL_NOT_QUALIFIED | 409 |
| ERR_DUPLICATE_REFERRAL | 409 |
| ERR_VALIDATION_PAGINATION | 400 |
| ERR_CASHOUT_NOT_RESERVABLE | 409 |
