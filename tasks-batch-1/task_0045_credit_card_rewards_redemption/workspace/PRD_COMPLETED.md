# Credit Card Rewards & Redemption API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Credit Card Rewards & Redemption API, a back-end service that runs the points economy behind a credit-card rewards program. The platform models the full arc of how rewards come into existence and how they leave it: a purchase is recorded, provisionally valued, and either posted or declined; a posting mints redeemable points into a dated lot, advances the account's spending toward its tier and signup-bonus milestones, and may trigger a one-time bonus grant; and points eventually flow out as statement credit, as transfers to airline and hotel partners, or as forfeiture when a lot ages out or an account closes.

Two characteristics make this domain demanding. First, points are a **conserved quantity** — every point that is minted is later redeemed, clawed back, expired, or forfeited, and the system must keep the per-account ledger identity exact at all times, never inventing or losing a fraction of a point. Second, the program is a **pricing engine layered over a finite pool**: the value of a purchase depends on fixed cashback categories, rotating quarterly categories that the cardholder must activate, the account's current spending tier, and a per-quarter bonus cap, while the value of a redemption depends on whether it is statement credit or a partner transfer and at what ratio. Because the redeemable balance is finite and several actors can draw it down, redemption creation is guarded by optimistic concurrency control so that a client cannot over-redeem against a stale view of the balance.

The remainder of this document defines the global contract (authentication, response envelope, pagination, precision, concurrency, and cross-cutting consistency rules) in Section 2, the business workflows in Section 3, the endpoint surface in Section 4, and the error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as follows: `ProgramAdmin`, `Cardholder`, and `RewardsOps`.

Each role is permitted only a defined set of operations. When an authenticated caller invokes an operation that their role is not allowed to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A `ProgramAdmin` operates the rewards program itself: it manages the catalog (card products, cashback categories, quarterly categories, and transfer partners), opens, activates, and closes accounts, and records, posts, declines, and refunds transactions. A `RewardsOps` operator runs back-office review and the period-close epoch: it confirms, rejects, and reverses redemptions, and it runs the expiry-and-signup-window sweep. A `Cardholder` is the account owner: it requests redemptions, activates quarterly categories, may close its own account, and reads its own resources.

The `Cardholder` role is **entity-backed**: when `X-User-Role` is `Cardholder`, the `X-User-ID` value is the `id` of the acting `CardAccount`. Any ownership check on a resource that references a `CardAccount` compares that resource's account foreign key to `X-User-ID`. Concretely, when a `Cardholder` requests a redemption, activates a quarterly category, closes an account, or reads an account-scoped resource, the `card_account_id` involved must equal `X-User-ID`; otherwise the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403). The other two roles are **opaque**: when `X-User-Role` is `ProgramAdmin` or `RewardsOps`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server may accept and record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip before collecting the page; it defaults to 0 when omitted and has a minimum of 0. A `limit` or `offset` that is non-integer or outside its allowed range is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list endpoints return their items sorted by creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count` (the total number of matching items before paging), and `has_more` (true when items remain beyond the current page).

### 2.4. Common Resource Properties and Resource Identity

Most resources in this system carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification. The `version` field is an integer that begins at 1 and increments by one with every mutation of the resource; it is the value used for optimistic concurrency control described in §2.7.

One entity is the exception: a **PointsLot** is a minimal, system-minted record that carries only `id` and `created_at`. A PointsLot has neither an `updated_at` field nor a `version` field. Although its `remaining_points` and `status` do change over the course of clawbacks, consumption, and expiry, the lot is not a client-versioned resource and is never the target of an optimistic-concurrency check. All other entities — CardProduct, CashbackCategory, QuarterlyCategory, TransferPartner, CardAccount, Transaction, Redemption, and CategoryActivation — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Nested Path Resolution and Resource Existence

The entities of this system are addressed as flat, top-level collections; relationships are expressed through foreign-key fields in request bodies rather than through nested URL segments. Whenever a request names a resource — whether by a path identifier or by a foreign-key field in its body — that resource must exist. Path and referenced identifiers are validated left to right, in the order they appear, and the first identifier that does not resolve to an existing resource (a `CardAccount`, `Transaction`, `Redemption`, `CardProduct`, `TransferPartner`, or `QuarterlyCategory`) causes the request to be rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before any later check runs. A request to an unknown route or with an unsupported method on a known path is likewise answered with `ERR_RESOURCE_NOT_FOUND` (HTTP 404).

### 2.6. Points Conservation and Ledger Integrity

Points are whole units throughout the system; there is never a fractional point, and no points operation rounds. The platform treats the per-account points supply as a strictly conserved quantity and enforces two invariants on every points-mutating event (transaction post and refund, redemption confirm and reverse, the close-period expiry sweep, and account close).

The first invariant is the **balance identity**. For any account at any instant, take the sum of `original_points` across all of its PointsLot rows (the points ever minted), subtract the points consumed by confirmed redemptions (net of any restored by reversals), subtract the points that were in lots at the moment those lots expired, and subtract the points clawed back when source transactions were refunded; the result must equal the account's `points_balance`. Equivalently, `points_balance` is always the sum of `remaining_points` over the account's PointsLot rows that are still in `ACTIVE` status, and it is recomputed on every mint, consumption, clawback, and expiry. The second invariant is the **reversal identity**: when a confirmed redemption that consumed `points_requested` points is later reversed, the sum of `remaining_points` across exactly the lots recorded for that redemption must increase by precisely that same `points_requested`, and the account's `points_balance` must show a net change of exactly plus that amount. The two invariants conserve different quantities — one the account-wide redeemable balance, the other the per-redemption restored quantity — and both must hold simultaneously.

Whenever a counter or balance would be driven below zero by a subtraction (for example, a refund clawback against an account whose points have already been partly spent, or a spend counter decremented by a refund), the value is floored at zero rather than allowed to go negative.

### 2.7. Optimistic Concurrency Control on Redemption Creation

Because an account's redeemable balance is a finite pool that more than one actor may draw down, the creation of a redemption is guarded by optimistic concurrency control against the owning `CardAccount`. A request to create a redemption must include `expected_card_account_version`, carrying the `version` of the target `CardAccount` that the client last observed. This field is mandatory and must be an integer of at least 1. If `expected_card_account_version` does not equal the account's current `version` at the moment the redemption is created — because some other writer (another redemption that drew down the balance, or a refund that clawed points back) has advanced the account's `version` since the client last read it — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). This prevents a client from creating a redemption against a `points_balance` it has not actually observed. No other endpoint takes a version field; the optimistic-concurrency guard applies to redemption creation alone.

### 2.8. State Propagation and the version / updated_at Contract

Almost every state transition and cascade in this system ultimately settles on a `CardAccount`, and each such settlement is a mutation of that account: it refreshes the account's `updated_at` and increments its `version` by one. Recording a transaction, posting it, declining it, refunding it, creating a redemption, confirming it, rejecting it, reversing it, activating an account, and closing an account each bump the affected `CardAccount.version` by exactly one. The period-close epoch increments the `version` of each `CardAccount` it actually touches. Retiring a product increments that `CardProduct.version`; suspending a partner increments that `TransferPartner.version`. These automatic, server-driven mutations occur without any separate client request against the secondary resource — the cascade described in §3 is what advances the version. This is also the mechanism that makes the optimistic-concurrency guard of §2.7 meaningful: any operation that changes an account's points position has already advanced its `version`, so a client holding a pre-change version will be correctly rejected.

### 2.9. Points-Earning Precision and Basis-Point Arithmetic

Earn rates and multipliers are expressed in **basis points** (bps), where 100 bps means a one-times rate, i.e., one point per cent of spend. The points-earning computation multiplies all of its basis-point factors together first and divides only once, applying a single floor (round-down to a whole number of points) at the very end. Per-step rounding is forbidden: rounding at each intermediate division would diverge from rounding once at the end, and only end-rounding is correct. The full earning formula and its inputs are detailed in §3.5.

Redemption values are likewise integers. A statement-credit redemption is valued exactly (no rounding loss). A partner-transfer redemption floors the fractional partner units (round-down). The redemption-value formula is detailed in §3.8.

### 2.10. Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order, and the first failure determines the error returned. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role permission for the operation, yielding `ERR_FORBIDDEN_ROLE`; (3) for `Cardholder`-owned operations, ownership of the account, yielding `ERR_NOT_ACCOUNT_OWNER`; (4) existence of all path and foreign-key resources, yielding `ERR_RESOURCE_NOT_FOUND`; (5) presence and primitive-type/enum correctness of the request body, yielding `ERR_INVALID_REQUEST`; (6) the conditional partner-field shape rule for redemptions, yielding `ERR_PARTNER_FIELD_MISMATCH`; (7) the target resource being in the correct state for the operation, yielding `ERR_INVALID_STATE`; (8) cross-product referential integrity, yielding `ERR_CROSS_PRODUCT_MISMATCH`; (9) uniqueness constraints, yielding `ERR_DUPLICATE_ACTIVATION`; (10) temporal range of the transaction time, yielding `ERR_TEMPORAL_OUT_OF_RANGE`; (11) the minimum-transfer floor for partner transfers, yielding `ERR_BELOW_MIN_TRANSFER`; (12) the optimistic-concurrency version match on redemption creation, yielding `ERR_STALE_ACCOUNT_VERSION`; and finally (13) sufficiency of redeemable points, yielding `ERR_INSUFFICIENT_POINTS`. Earlier checks take precedence over later ones, so, for example, an authentication failure is reported before a role failure, and a non-existent referenced resource is reported before any business-constraint check.

## 3. Business Logic & Workflows

### 3.1. Configuring the Rewards Program: Products, Categories, and Partners

The rewards program begins with a **CardProduct**, the reward-program definition that a `ProgramAdmin` creates. A product is given a `name` (1 to 100 characters), a `base_earn_rate_bps` (the base earn rate in basis points of points per cent, at least 0 and no more than 1000, applied to all spend that earns no category or quarterly bonus), a `signup_bonus_points` grant (at least 0), a `signup_bonus_spend_threshold_cents` (the cumulative qualifying posted spend in cents the account must reach to earn that bonus, at least 1), a `signup_bonus_window_days` (the number of days from account opening during which qualifying spend counts, at least 1 and no more than 365), a `tier_thresholds` list, and a `points_expiry_months` value (the whole number of months a points lot lives before expiring, at least 1 and no more than 120). A product is created in `status` `ACTIVE`; the `status` enumerates `ACTIVE` and `RETIRED`. Retiring a product moves its `status` to `RETIRED` so that no new account may open under it, while leaving existing accounts untouched.

The `tier_thresholds` value is an ordered, ascending list of 0 to 4 annual-spend breakpoints. Each element has a `min_annual_spend_cents` (the spend in cents at which the tier is reached) and a `tier_multiplier_bps` (the multiplier in basis points that then applies to the whole of subsequent earning). The `min_annual_spend_cents` values must be strictly ascending across the list, and the first element's `min_annual_spend_cents` must be at least 1. There is an implicit tier 0 below the first breakpoint, representing zero spend with a multiplier of 100 bps.

A **CashbackCategory** is a fixed bonus category attached to a product. A `ProgramAdmin` creates one by supplying the `card_product_id` it belongs to (the product must exist), a `code` (an UPPER_SNAKE merchant-category label such as DINING, GROCERY, GAS, TRAVEL, or OTHER, unique among the cashback categories of that product), and an `earn_multiplier_bps` (the multiplier that replaces the base rate for matched transactions, at least 100 and no more than 1000). Its `status` enumerates `ACTIVE` and `DISABLED`, defaulting to `ACTIVE`; only an `ACTIVE` fixed category earns its bonus. Creating a second cashback category with a `code` already used on the same product is rejected with `ERR_DUPLICATE_ACTIVATION` (HTTP 409).

A **QuarterlyCategory** is a rotating bonus category that the cardholder must activate to benefit from. A `ProgramAdmin` creates one with the `card_product_id` it belongs to, a `code` (UPPER_SNAKE, such as GROCERY, GAS, or ONLINE), a `quarter_label` in the format `YYYY-Qn` (matching a four-digit year, a hyphen, the letter Q, and a quarter digit 1 through 4, such as `2026-Q3`), a `window_start` and `window_end` (UTC instants bounding the quarter; `window_start` must be strictly earlier than `window_end`), an `earn_multiplier_bps` (at least 100 and no more than 1000), and a `bonus_cap_cents` (the maximum spend in cents per account per quarter that earns the quarterly multiplier, at least 1). The pair of `card_product_id` and `quarter_label` must be unique; a duplicate is rejected with `ERR_DUPLICATE_ACTIVATION` (HTTP 409). The window boundary is inclusive at the start and exclusive at the end: spend whose transaction time is at or after `window_end` does not earn the quarterly bonus.

A **TransferPartner** is an airline or hotel program that points may be transferred into. A `ProgramAdmin` creates one with a `name` (1 to 100 characters), a `partner_type` enumerating `AIRLINE` and `HOTEL`, a transfer ratio expressed as a `transfer_ratio_num` and a `transfer_ratio_den` (each at least 1), and a `min_transfer_points` floor (at least 1) on a single transfer. Its `status` enumerates `ACTIVE` and `SUSPENDED`, defaulting to `ACTIVE`; transfers are accepted only by an `ACTIVE` partner. Suspending a partner moves its `status` to `SUSPENDED`.

### 3.2. Opening and Activating an Account

A `ProgramAdmin` opens a **CardAccount** by supplying the `card_product_id` it is opened under and a `cardholder_name` (1 to 100 characters). The referenced product must be `ACTIVE` at open time; opening an account under a `RETIRED` product is rejected with `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422). On creation the account records `opened_at` as the server clock at that instant — this timestamp anchors both the signup-bonus window and the annual tier-spend year. A new account starts in `status` `PENDING`; the account `status` enumerates `PENDING`, `ACTIVE`, and `CLOSED`. Its computed ledgers all begin at zero: `points_balance` (the redeemable points), `pending_points` (the provisional points from not-yet-posted transactions), `qualifying_spend_cents` (cumulative posted qualifying spend in the signup window), `annual_spend_cents` (cumulative posted net spend in the tier year), and `current_tier_index` (0). The `signup_bonus_status` begins at `NOT_QUALIFIED`; it enumerates `NOT_QUALIFIED`, `EARNED`, and `EXPIRED_UNQUALIFIED`.

Activation moves an account from `PENDING` to `ACTIVE`. A `ProgramAdmin` activates it; the account must currently be in `PENDING` status and the referenced `CardProduct` must be `ACTIVE`. After activation the account is eligible to record transactions, request redemptions, and activate categories; `opened_at` is unchanged, since it was set at creation. An account may only transact, redeem, or activate categories while `ACTIVE`; attempting any of these against an account in the wrong state is rejected with `ERR_INVALID_STATE` (HTTP 409).

Closing an account moves it from `ACTIVE` to the terminal `CLOSED` state and may be performed by either a `ProgramAdmin` or the `Cardholder` who owns it. Closing is permitted only when the account is `ACTIVE` and there is **no** redemption for the account currently in `PENDING` status; a close attempted with a pending redemption outstanding is rejected with `ERR_INVALID_STATE` (HTTP 409). Closing forfeits all unredeemed points: every `ACTIVE` PointsLot of the account transitions to `EXPIRED` with its `remaining_points` zeroed, and the account's `points_balance` is recomputed to 0. This forfeiture is a sink in the conserved-quantity ledger of §2.6.

### 3.3. Recording a Purchase and Provisional Points

A `ProgramAdmin` records a purchase as a **Transaction** by supplying the `card_account_id` (which must reference an `ACTIVE` account), an `amount_cents` (the purchase amount in cents, at least 1), a `category_code` (an UPPER_SNAKE merchant-category code such as DINING, GROCERY, GAS, ONLINE, or OTHER, matched against the product's cashback and quarterly categories), and a `transacted_at` instant. The `transacted_at` must be no earlier than the account's `opened_at` and no later than the current server clock; a value before opening or in the future is rejected with `ERR_TEMPORAL_OUT_OF_RANGE` (HTTP 422). The transaction `status` enumerates `PENDING`, `POSTED`, `DECLINED`, and `REFUNDED`, and a new transaction begins `PENDING`.

At creation the system computes the **provisional** points figure for the transaction using the same earning formula described in §3.5, but it does not yet credit redeemable points or mint a lot. Instead, the provisional figure is added to the account's `pending_points`, a ledger kept distinct from `points_balance`. The transaction's `earned_points` field remains 0 and its `quarterly_bonus_applied_cents` field remains 0 while the transaction is still `PENDING`; these settle only at posting.

Each transaction reaches one of two outcomes from `PENDING`, both driven by a `ProgramAdmin`. Posting advances the transaction from `PENDING` to `POSTED`. Declining advances it from `PENDING` to `DECLINED`: the transaction's provisional contribution is removed from the account's `pending_points`, no lot is minted, and no spend counter is touched. Both posting and declining require the transaction to currently be `PENDING`.

### 3.4. Posting a Transaction: Lot Mint, Tier Re-derivation, and the Signup-Bonus Cascade

Posting a `PENDING` transaction is the central earning event, and it is permitted only when the transaction is `PENDING` and its owning account is `ACTIVE`. Posting computes the transaction's `earned_points` and `quarterly_bonus_applied_cents` via the earning formula of §3.5, evaluated against the account's `current_tier_index` **as it stands before this transaction's own spend is added**. The cascade then proceeds in order:

First, when the computed `earned_points` is greater than 0, the system mints a new **PointsLot** of `lot_type` `EARN`, with `original_points` and `remaining_points` both set to the earned amount, and an `expires_at` equal to the lot's creation time plus the product's `points_expiry_months` whole calendar months (advancing the month and year and keeping the day-of-month, but clamping the day down to the last valid day of the target month when it would otherwise overflow — e.g. Jan 31 plus one month yields Feb 28/29). The transaction's provisional contribution is moved out of the account's `pending_points`, and the lot's points are added into the account's `points_balance`. Second, when `transacted_at` falls within the tier year, the `amount_cents` is added to the account's `annual_spend_cents`, and `current_tier_index` is re-derived (see §3.6). Third, when `transacted_at` falls within the signup window, the `amount_cents` is added to the account's `qualifying_spend_cents`, which may trigger the signup-bonus grant (see §3.7).

A **PointsLot** is the unit of minted points and is never created by a direct client request; it appears only as a side effect of posting (an `EARN` lot) or of the signup-bonus grant (a `SIGNUP_BONUS` lot). A lot records the `card_account_id` that owns it and a `source_transaction_id` naming the `POSTED` transaction that minted it (the `source_transaction_id` is absent for the signup-bonus lot). Its `lot_type` enumerates `EARN` and `SIGNUP_BONUS`. Its `original_points` (at least 1) is the amount minted at creation, and its `remaining_points` is that original amount less whatever has since been consumed by redemption and clawed back by refund; `remaining_points` is what drives the account's `points_balance`. Its `status` enumerates `ACTIVE`, `CONSUMED`, `EXPIRED`, and `CLAWED_BACK`: a lot becomes `CONSUMED` when its `remaining_points` reaches 0 through redemption, `EXPIRED` through the sweep or account close, and `CLAWED_BACK` when its source transaction is refunded.

Refunding reverses a posted transaction. A `ProgramAdmin` may refund a transaction only while it is `POSTED`, moving it to the terminal `REFUNDED` state. The refund claws back the `EARN` PointsLot minted by that transaction — the lot being clawed back whether it is still `ACTIVE` or has already become `CONSUMED` (a lot already `EXPIRED` or `CLAWED_BACK` is left untouched): the lot's `status` becomes `CLAWED_BACK` and its `remaining_points` is set to 0. If that lot's points had already been partly redeemed, the shortfall (the points that can no longer be reclaimed from the lot) is taken from the account's `points_balance`, down to a floor of 0 so the balance never goes negative; in practice the `points_balance` is simply recomputed afterward as the sum of `remaining_points` over the account's `ACTIVE` lots, which excludes the now-clawed-back lot. The refund then subtracts the `amount_cents` from the account's `annual_spend_cents` (floored at 0) and re-derives `current_tier_index`, which may demote the tier; and it subtracts the `amount_cents` from the account's `qualifying_spend_cents` (floored at 0) within the signup window. The account's `points_balance` is recomputed afterward. This refund cascade compensates the posting cascade and respects the conservation rules of §2.6.

### 3.5. The Points-Earning Calculation

When a transaction is posted (and, with the provisional caveat of §3.3, when it is first recorded), points are computed from four stages over the transaction's `amount_cents`, its `category_code`, its `transacted_at`, the account's product, and the account's `current_tier_index` snapshot taken before this transaction's spend is added. All factors are in basis points, and the result is rounded down to whole points exactly once at the end.

**Stage one — per-cent base multiplier.** The system looks for an `ACTIVE` `CashbackCategory` whose `code` equals the transaction's `category_code` and whose `card_product_id` is the account's product (there is at most one). If such a fixed category exists, the per-cent multiplier in basis points is that category's `earn_multiplier_bps`; otherwise it is the product's `base_earn_rate_bps`. The category multiplier replaces the base rate; it does not stack with it.

**Stage two — quarterly bonus eligibility and cap allocation.** The system looks for a `QuarterlyCategory` whose `code` equals the `category_code`, whose `card_product_id` is the account's product, and whose window contains the transaction time, meaning `window_start` is at or before `transacted_at` and `transacted_at` is strictly before `window_end`. The quarterly bonus applies only if such a category exists **and** the account has an `ACTIVE` `CategoryActivation` for it whose `activated_at` is at or before `transacted_at`. When both hold, the system determines the remaining quarterly cap: it sums the `quarterly_bonus_applied_cents` of the account's already-`POSTED` transactions in that same quarterly category — meaning those whose `category_code` equals the category's `code` and whose own `transacted_at` falls within that category's `[window_start, window_end)` window — that received a positive quarterly bonus, processed in ascending `transacted_at` order and then ascending `created_at` order, and subtracts that used amount from the category's `bonus_cap_cents`, flooring the remaining cap at 0. The cents of this transaction that earn the quarterly multiplier — recorded as the transaction's `quarterly_bonus_applied_cents` — is the smaller of the transaction's `amount_cents` and that remaining cap. When no quarterly category applies or the account has not activated it, `quarterly_bonus_applied_cents` is 0.

**Stage three — tier multiplier.** The tier multiplier in basis points is the `tier_multiplier_bps` of the product's `tier_thresholds` element selected by the account's `current_tier_index` under the 1-based mapping of §3.6 (index `k` selects `tier_thresholds[k-1]`), or 100 for the implicit tier 0 (index 0). This multiplier applies to the whole transaction, on top of the category and quarterly multipliers.

**Stage four — combine and round once.** Let the bonus cents be the `quarterly_bonus_applied_cents` from stage two. The base part is the amount of cents that did not receive the quarterly bonus (the `amount_cents` minus the bonus cents) multiplied by the stage-one per-cent multiplier in basis points. The quarterly part is the bonus cents multiplied by the quarterly category's `earn_multiplier_bps` (and is 0 when no quarterly category applies). The system adds the base part and the quarterly part, multiplies that sum by the tier multiplier in basis points, and then divides by 1,000,000 (the product of three basis-point denominators of 100 each — one for the category-or-quarterly multiplier, one for the tier multiplier, and one converting cents-times-bps into points), taking the floor of that single division to yield `earned_points`. No intermediate result is rounded; the floor is applied only at this final step.

This calculation has two variants. The **provisional** variant runs at transaction creation: it uses this exact formula but adds the result to `pending_points` rather than `points_balance`, mints no lot, and leaves the row's `earned_points` at 0. The **posted** variant runs at posting: the result is written to `earned_points`, a PointsLot is minted, and the points move from `pending_points` into `points_balance`.

### 3.6. Spending Tiers and the Tier Year

The account's `annual_spend_cents` accumulates posted net spend within the current tier year, the window beginning at `opened_at` and running for 365 days. The `current_tier_index` is 1-based over the `tier_thresholds` list: index 0 is the implicit tier 0, and index `k` (for `k` from 1 to the list length) corresponds to `tier_thresholds[k-1]`. It is the largest `k` such that `tier_thresholds[k-1].min_annual_spend_cents` is at or below `annual_spend_cents`, and it is 0 whenever the account's spend is below the first breakpoint. The index is re-derived on every posting (which adds spend) and every refund (which subtracts spend and may therefore demote the tier). Because the earning formula reads `current_tier_index` as it stands before the current transaction's own spend is added, the spend from a single posting raises the tier for subsequent transactions, not for itself.

### 3.7. Signup-Bonus Qualification

The account's `qualifying_spend_cents` accumulates the `amount_cents` of posted transactions whose `transacted_at` falls within the signup window. That window begins at `opened_at` (inclusive) and ends at `opened_at` plus the product's `signup_bonus_window_days` days (exclusive); a transaction whose time is exactly at that upper boundary, to the millisecond, is outside the window. On each posting that updates `qualifying_spend_cents`, the system grants the signup bonus when all of the following hold: the account's `signup_bonus_status` is still `NOT_QUALIFIED`; the `qualifying_spend_cents` has reached at least the product's `signup_bonus_spend_threshold_cents` (reaching the threshold exactly qualifies); and the current time is still before the window's exclusive upper bound. When granted, the account's `signup_bonus_status` becomes `EARNED`, a `SIGNUP_BONUS` PointsLot is minted with `original_points` and `remaining_points` both equal to the product's `signup_bonus_points` and an `expires_at` of its creation time plus the product's `points_expiry_months` months, and that many points are added to the account's `points_balance`. When the product's `signup_bonus_points` is 0, the status still becomes `EARNED` but no lot is minted (a lot always carries `original_points` of at least 1) and the balance is unchanged. The bonus is granted at most once over the life of an account.

If the window passes without the threshold ever being met, the bonus does not lapse silently within a transaction; instead the period-close epoch (§3.10) marks the account's `signup_bonus_status` as `EXPIRED_UNQUALIFIED`.

### 3.8. Requesting and Resolving a Redemption

A `Cardholder` requests a **Redemption** against its own `ACTIVE` account. The request supplies the `card_account_id` (which must equal `X-User-ID` for the owner check), a `redemption_type` enumerating `STATEMENT_CREDIT` and `POINTS_TRANSFER`, a `points_requested` count (at least 1), a `transfer_partner_id` that is conditional on the type, and the `expected_card_account_version` for the optimistic-concurrency guard of §2.7. The redemption `status` enumerates `PENDING`, `CONFIRMED`, `REJECTED`, and `REVERSED`, and a new redemption begins `PENDING`. Creating a redemption reserves no points yet but does validate the balance and the version; a freshly created redemption carries `redeemed_value` of 0 and an empty `lots_consumed` list, both of which settle only at confirmation. Creating a redemption also bumps the owning account's `version` (per §2.8), even though no lots are consumed yet.

The `transfer_partner_id` must be present exactly when `redemption_type` is `POINTS_TRANSFER` and must be absent when it is `STATEMENT_CREDIT`; supplying it for a statement credit, or omitting it for a points transfer, is rejected with `ERR_PARTNER_FIELD_MISMATCH` (HTTP 422). For a points transfer, the referenced `TransferPartner` must be `ACTIVE`; a transfer to a `SUSPENDED` partner is rejected with `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422). For a points transfer, `points_requested` must be at least the partner's `min_transfer_points`; falling below that floor is rejected with `ERR_BELOW_MIN_TRANSFER` (HTTP 422). At create time, and again when the redemption is confirmed, `points_requested` must not exceed the account's `points_balance`; an insufficient balance is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422).

A `RewardsOps` operator resolves a pending redemption. Confirming advances the redemption from `PENDING` to `CONFIRMED`; it is permitted only when the redemption is `PENDING`, the owning account is `ACTIVE`, and the account's `points_balance` is at least the `points_requested` (re-checked here as noted above). Confirmation consumes `points_requested` from the account's `ACTIVE` PointsLot rows in FIFO order — ordered by ascending `expires_at`, breaking ties by ascending `created_at` — decrementing each touched lot's `remaining_points`, and records the ordered `lots_consumed` list, each element naming the `points_lot_id` drawn from and the `points_taken` from it. Any lot whose `remaining_points` reaches 0 transitions to `CONSUMED`. The redemption's output value is then computed into `redeemed_value` (see below), and the account's `points_balance` is recomputed. Rejecting instead advances the redemption from `PENDING` to the terminal `REJECTED` state, consuming no lots and changing no balance.

The `redeemed_value` is computed at confirmation from the type. For a `STATEMENT_CREDIT`, the value in cents is the `points_requested` valued at a flat one cent per point — that is, `points_requested` times 1, exactly, with no rounding loss. For a `POINTS_TRANSFER`, the value in partner units is `points_requested` multiplied by the partner's `transfer_ratio_num`, divided by its `transfer_ratio_den`, with the fractional remainder floored away (round-down); the same points spend can therefore yield a different value across partners, and fractional partner units are forfeited.

Reversing compensates a confirmed redemption. A `RewardsOps` operator may reverse a redemption only while it is `CONFIRMED`, moving it to the terminal `REVERSED` state. The reversal restores points to the exact lots recorded in `lots_consumed`: each such lot's `remaining_points` is increased by the `points_taken` originally recorded for it. A lot whose `status` had become `CONSUMED` returns to `ACTIVE` if it has not since expired; if it has expired — meaning its `status` is already `EXPIRED` or its `expires_at` is at or before the current clock — the restored points instead spill into a fresh restoration lot. That restoration lot is minted `ACTIVE` with `original_points` and `remaining_points` both equal to the restored `points_taken`, a `created_at` of the current clock, the same `lot_type` and `source_transaction_id` as the original lot, and an `expires_at` that matches the original lot's `expires_at` (so it may already be past expiry and will be swept on the next period close). The account's `points_balance` is recomputed, with a net change of exactly plus the `points_requested` — the reversal identity of §2.6.

### 3.9. Activating a Quarterly Category

A `Cardholder` activates a rotating quarterly category for its account by creating a **CategoryActivation**, supplying the `card_account_id` (which must equal `X-User-ID`) and the `quarterly_category_id`. The owning account must be `ACTIVE`. The referenced `QuarterlyCategory` must belong to the account's product — its `card_product_id` must equal the account's `card_product_id` — and a mismatch is rejected with `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422). There may be at most one `ACTIVE` activation for a given pairing of `card_account_id` and `quarterly_category_id`; a second is rejected with `ERR_DUPLICATE_ACTIVATION` (HTTP 409). On creation the activation records `activated_at` as the server clock at that instant. A CategoryActivation is effectively append-only: its `status` enumerates only `ACTIVE`, and creation is its single transition. Once activated, subsequent transactions in that category, within the quarter window and with `transacted_at` at or after the `activated_at`, earn the quarterly bonus multiplier as described in §3.5.

### 3.10. The Period-Close Epoch

A `RewardsOps` operator runs the period-close epoch as a back-office operation, evaluated as of the current server clock. The epoch performs two sweeps. First, every `ACTIVE` PointsLot whose `expires_at` is at or before the current clock transitions to `EXPIRED`, forfeiting its `remaining_points`. Second, every account whose signup-bonus window has passed without the threshold being met has its `signup_bonus_status` set to `EXPIRED_UNQUALIFIED`. Each account whose balance or signup status the epoch actually changes has its `points_balance` recomputed and its `version` incremented. The operation reports a summary giving the `expired_lot_count` (the number of lots forfeited), the `expired_points` (the total points forfeited), and the `signup_windows_expired` (the number of accounts marked expired-unqualified).

So that windows, expiry, and tier years can be exercised deterministically, an administrative test-driving capability lets a `ProgramAdmin` or `RewardsOps` set the logical server clock to a supplied instant given as `to_iso8601`. This capability sits outside the public business surface and drives `opened_at`, `transacted_at` window inclusion, and the expiry sweep.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions such as activating, closing, posting, declining, refunding, confirming, rejecting, reversing, retiring, and suspending — return a `200 OK` status code. List and fetch operations return `200 OK`.

Beyond the filter dimensions named in the table below, each list endpoint also accepts an optional `status` query parameter that restricts results to rows with that exact `status` (where the entity has a `status`); a filter value matching no rows yields an empty page rather than an error. In addition, the list endpoints accept these entity-specific filters: products by `status`; cashback categories by `card_product_id` and `status`; quarterly categories by `card_product_id` and `quarter_label`; transfer partners by `partner_type` and `status`; accounts by `card_product_id` and `status`; transactions by `card_account_id` and `status`; points lots by `card_account_id`, `source_transaction_id`, and `status`; redemptions by `card_account_id`, `transfer_partner_id`, and `status`; and category activations by `card_account_id`, `quarterly_category_id`, and `status`. All such filters are applied as exact equality and combine conjunctively.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a card product (reward-program definition) | ProgramAdmin |
| GET | `/products/{id}` | Fetch a card product | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/products` | List card products | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/products/{id}/retire` | Retire a product so no new accounts may open under it | ProgramAdmin |
| POST | `/cashback-categories` | Create a fixed cashback category for a product | ProgramAdmin |
| GET | `/cashback-categories/{id}` | Fetch a cashback category | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/cashback-categories` | List cashback categories, filterable by product | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/quarterly-categories` | Create a rotating quarterly bonus category for a product | ProgramAdmin |
| GET | `/quarterly-categories/{id}` | Fetch a quarterly category | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/quarterly-categories` | List quarterly categories, filterable by product | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/transfer-partners` | Create an airline/hotel transfer partner | ProgramAdmin |
| GET | `/transfer-partners/{id}` | Fetch a transfer partner | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/transfer-partners` | List transfer partners | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/transfer-partners/{id}/suspend` | Suspend a partner so it no longer accepts transfers | ProgramAdmin |
| POST | `/accounts` | Open a card account under a product (starts PENDING) | ProgramAdmin |
| GET | `/accounts/{id}` | Fetch a card account incl. computed balances/tier/signup status | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/accounts` | List card accounts, filterable by product | ProgramAdmin, RewardsOps |
| POST | `/accounts/{id}/activate` | Activate a PENDING account | ProgramAdmin |
| POST | `/accounts/{id}/close` | Close an ACTIVE account; forfeits all unredeemed points | ProgramAdmin, Cardholder |
| POST | `/transactions` | Record a purchase (starts PENDING); computes provisional points | ProgramAdmin |
| GET | `/transactions/{id}` | Fetch a transaction | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/transactions` | List transactions, filterable by account | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/transactions/{id}/post` | Post a PENDING transaction; mints a lot, updates spend/tier, may grant signup bonus | ProgramAdmin |
| POST | `/transactions/{id}/decline` | Decline a PENDING transaction; releases provisional points | ProgramAdmin |
| POST | `/transactions/{id}/refund` | Refund a POSTED transaction; claws back its lot, reverses spend, may demote tier | ProgramAdmin |
| GET | `/points-lots/{id}` | Fetch a single points lot | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/points-lots` | List points lots, filterable by account or source transaction | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/redemptions` | Request a redemption (statement credit or points transfer) | Cardholder |
| GET | `/redemptions/{id}` | Fetch a redemption | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/redemptions` | List redemptions, filterable by account or partner | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/redemptions/{id}/confirm` | Confirm a PENDING redemption; consumes points FIFO, computes value | RewardsOps |
| POST | `/redemptions/{id}/reject` | Reject a PENDING redemption | RewardsOps |
| POST | `/redemptions/{id}/reverse` | Reverse a CONFIRMED redemption; restores consumed points | RewardsOps |
| POST | `/category-activations` | Activate a quarterly category for an account | Cardholder |
| GET | `/category-activations/{id}` | Fetch a single category activation | ProgramAdmin, Cardholder, RewardsOps |
| GET | `/category-activations` | List category activations, filterable by account | ProgramAdmin, Cardholder, RewardsOps |
| POST | `/_clock/set_current_utc` | Test-driving: set the server clock to a fixed UTC instant | ProgramAdmin, RewardsOps |
| POST | `/close-period` | Forfeit expired lots and mark unmet signup windows expired | RewardsOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PARTNER_FIELD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CROSS_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVATION` | 409 Conflict |
| `ERR_TEMPORAL_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_BELOW_MIN_TRANSFER` | 422 Unprocessable Entity |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_INSUFFICIENT_POINTS` | 422 Unprocessable Entity |
