# Loyalty Rewards API — Product Requirements Document

## 1. Introduction

This document specifies the Loyalty Rewards platform — a points-based engagement system that lets a retailer reward members for what they spend, refer, and celebrate. At its heart the platform is a **points ledger**: every event that touches a member's balance (an eligible purchase, a redeemed catalog reward, a partner-points transfer, a birthday or referral grant, an expiration sweep) produces an immutable ledger entry, and a member's spendable balance is never stored as a single mutable number but is always re-derived from the lots that back it. This append-only discipline is what lets the program guarantee point conservation across compensating actions such as a cancelled redemption or a reversed partner transfer.

Layered on top of the ledger is a **pricing engine**. Members earn at a base rate that is then amplified by their tier and by any live bonus-point promotion; they burn points against a catalog whose costs are discounted for higher tiers; and they convert loyalty points into a partner's currency at a tier-dependent ratio. Because the same underlying member can occupy different tiers at different moments — and because a redemption is quoted at one moment and fulfilled at another — several quantities in the system exist in two distinct variants (a provisional one and a final one) that the platform must reconcile. The program operator configures tiers, promotions, rewards, partners, and expiration policy; members operate their own ledgers; partner operators settle and reverse the transfers routed to their accounts. The remainder of this document defines the contracts, cross-cutting principles, and business workflows that govern these interactions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across the entire API. Individual workflow rules are developed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request that omits or malforms either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as `ProgramAdmin`, `Member`, `PartnerOperator`, and `Anonymous`.

A `ProgramAdmin` is the operator of the loyalty program. The identity carried in `X-User-ID` for a `ProgramAdmin` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it but never compares it to any entity's `id`. Administrators configure tiers, promotions, rewards, and partners; activate and close programs; run maintenance sweeps and fulfillment; grant birthday rewards; and revoke referrals.

A `Member` acts on their own ledger. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a `Member` compare that resource's owning member foreign key (for example, the `member_id` of a redemption, lot, transaction, purchase event, or partner transfer) to `X-User-ID`. A member acting on a resource that belongs to a different member is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

A `PartnerOperator` is a partner's operator who settles or reverses the partner-points transfers routed to their own partner account. When `X-User-Role` is `PartnerOperator`, `X-User-ID` is the `id` of the acting `PartnerAccount` entity; ownership checks on transfer and blackout resources compare the relevant `partner_account_id` to `X-User-ID`, and acting on another partner's resource is likewise rejected with `ERR_NOT_RESOURCE_OWNER`.

The `Anonymous` role is reserved for unauthenticated negative-path testing and holds no business operations; an `Anonymous` caller attempting any protected operation is treated as lacking permission.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` is below 1 or above 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422).

Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity Semantics

Most resources in the system carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was first created. The `updated_at` field is the ISO 8601 UTC timestamp of the resource's most recent modification, and `version` is an integer that begins at its initial value and increments by one on every mutation of the resource. These last two fields are what optimistic concurrency control (Section 2.9) and hierarchical reconciliation (Section 2.5) rely upon.

Two entities are deliberately leaner. A `PointsTransaction` is an append-only ledger row: once written it is never modified, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`. A `RedemptionLine` is likewise a child record fixed at the moment its parent redemption is quoted; it too carries only `id` and `created_at`, with no `updated_at` and no `version`. Every other entity — `LoyaltyProgram`, `Tier`, `Member`, `PointsLot`, `Promotion`, `CatalogReward`, `Redemption`, `Referral`, `PartnerAccount`, `TransferBlackout`, `PartnerTransfer`, and `PurchaseEvent` — carries the full complement of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Ledger Integrity, Derived Balances, and Reconciliation

The platform treats a member's point balance as a derived quantity, never a stored counter. A member's `available_points` is the sum of the `remaining_points` of every one of that member's `PointsLot` records that is in the `ACTIVE` status. A member's `projected_points` is the same sum minus the `remaining_points` of those `ACTIVE` lots whose `expires_at` is at or before the current clock time — that is, lots that are past expiry but have not yet been swept. A member's `lifetime_earned_points` is the sum of the `points_delta` of that member's ledger rows whose `type` is one of `EARN_PURCHASE`, `EARN_BONUS`, `BIRTHDAY`, `REFERRAL`, or `TRANSFER_IN_REVERSAL` — the positive-delta earn and reversal rows. A member's `qualifying_points_window` is the sum of the `qualifying_points` of that member's `EARN_PURCHASE` ledger rows whose `created_at` falls within the trailing qualifying window (Section 3.4). All four of these computed quantities, together with `current_tier_code`, are recomputed whenever a ledger mutation occurs and are also refreshed when a member is read.

Whenever an operation mutates a resource, the server stamps a new `updated_at` on it and increments its `version`. This applies to the resources directly named by a request and to any resource the server adjusts as a downstream consequence — for example, every operation that posts, burns, expires, or refunds points re-derives the affected member's balances and, where the scaffolded workflow says so, advances that member's `version`. When the server transitions a resource automatically as a consequence of the clock advancing (a promotion ending, a lot expiring, a pending referral aging out), that transition is itself a mutation and is stamped accordingly.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a multi-segment path — for instance a member's lots, a program's tiers, or a partner's blackouts. For any such request the server validates the path identifiers from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. A request for the blackouts of a non-existent partner therefore fails on the partner before the server ever looks at blackouts. This left-to-right existence check is part of a broader ordering: existence of referenced resources (path or body) is verified before any body-shape or business rule is applied, so an invalid container is always reported before deeper validation runs.

### 2.7. Precision, Rounding, and Integer Discipline

Points are integers; the program never stores fractional points on a member's ledger. Two distinct rounding disciplines govern how integers are produced from real-valued arithmetic, and they are not interchangeable.

For **earn-side and conversion-side** calculations — the points minted by a purchase, the tier-qualifying contribution of a purchase, and the partner points produced by a transfer — the platform forms the full real-valued product first and then takes the floor (rounds down to the nearest whole number) exactly once, at the end. Intermediate multipliers are never rounded.

For **redemption costs**, the platform rounds half up. The rounding is applied **per line** — each line's real-valued cost is rounded half up to a whole number of points — and only then are the rounded line totals summed. This round-then-sum order is load-bearing: summing the raw real-valued line costs and rounding the total once would differ by as much as one point, and that alternative is explicitly not used.

### 2.8. Program, Member, and Partner Operating Gates

Several operations are gated on the operating status of the objects they touch. A `LoyaltyProgram` moves through `DRAFT`, `ACTIVE`, and `CLOSED`. Member registration, purchase posting, redemption creation, and partner transfers are permitted only while the owning program is `ACTIVE`; attempting any of them against a program that is not `ACTIVE` is rejected with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409).

A `Member` is either `ACTIVE` or `SUSPENDED`. While a member is `SUSPENDED`, that member's earn (purchase posting), redemption confirmation, and partner transfers are rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409). A `PartnerAccount` is either `ACTIVE` or `PAUSED`; a new partner transfer against a `PAUSED` partner is rejected with `ERR_PARTNER_PAUSED` (HTTP 409).

When a state-transition endpoint is invoked against a target that is not in a state from which that transition is legal — a redemption, referral, partner transfer, promotion, points lot, or transfer blackout in the wrong state — the request is rejected with `ERR_INVALID_STATE` (HTTP 409), except where a more specific code is named for that transition (for example program activation, below).

### 2.9. Optimistic Concurrency Control on Member Version

Two write operations carry an optimistic-concurrency guard keyed to the member's `version`, because both size their effect against the member's current balance and tier and must not act on a stale view.

When a member confirms a quoted redemption, the request must carry `expected_member_version` holding the `version` of the `Member` the client last observed. The server compares it to the member's current `version` just before the burn is written. If another posted mutation — a prior burn, a partner transfer, a grant, or an expiration — has advanced the member's `version` since the client read it, the confirmation is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), because the `available_points` the client used to size this redemption no longer reflects the ledger. This guard is evaluated last, immediately before the write, after all other checks have passed.

Submitting a partner transfer likewise requires `expected_member_version` to match the member's current `version`. Because the transfer's `partner_points` depend on the member's current tier and the burn depends on `available_points`, an advance of the member's `version` since the client's last read means another posted ledger mutation has occurred and the client's basis is stale; the submission is then rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), again checked last, just before the write. No other endpoint takes a version field; operations not described here perform no OCC check.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Configuration of Tiers, Rewards, Partners, and Policy

A `ProgramAdmin` brings a program into existence in the `DRAFT` status by supplying a display `name` and the program-wide economic policy: a `base_earn_rate` (points earned per whole dollar of eligible spend), a `point_value_cents` (the cash value of one point in cents, used for partner-transfer floor reasoning), a `lot_expiration_months` (the number of months after a lot's creation at which its unspent balance expires), an optional `qualifying_window_months` (the trailing window over which qualifying points are summed for tier evaluation, defaulting to 12 months when omitted), a `birthday_reward_points` amount, the `referral_referrer_points` and `referral_referee_points` granted when a referral completes, and the `referral_min_qualifying_cents` threshold a single purchase must reach to complete a pending referral. At creation, `base_earn_rate`, `point_value_cents`, and any tier's `transfer_ratio` must each be strictly greater than zero, and any tier's `earn_multiplier` must be at least 1.0; a configuration value violating these bounds is rejected with `ERR_INVALID_RATE` (HTTP 422). The program's `status` defaults to `DRAFT`.

Activation moves a program from `DRAFT` to `ACTIVE` and is the gate that unlocks member, earn, redeem, and transfer operations. Activation is legal only from `DRAFT`; invoking it on a program that is already `ACTIVE` or already `CLOSED` is rejected with the specific code `ERR_PROGRAM_ALREADY_ACTIVE` (HTTP 409) rather than the generic invalid-state code. Closing a program is legal from either `DRAFT` or `ACTIVE` and drives the program to the terminal `CLOSED` status, after which member, earn, redeem, and transfer operations are refused under the program gate of Section 2.8.

Tiers are defined under a program by a `ProgramAdmin`. Each tier carries the parent `program_id`, a `code` drawn from the set `STANDARD`, `SILVER`, `GOLD`, and `PLATINUM`, a `qualify_threshold` (the minimum cumulative qualifying points over the trailing window required to hold the tier), an `earn_multiplier` applied to redeemable earn for members at that tier, a `transfer_ratio` governing loyalty-to-partner conversion at that tier, and an integer `rank` that orders tiers so that a higher rank denotes a higher tier. Within one program both `code` and `rank` must be unique, and the `STANDARD` tier is special: it must have a `qualify_threshold` of 0, a `rank` of 0, and an `earn_multiplier` of 1.0. A tier whose `code` or `rank` collides with an existing tier in the program, or a `STANDARD` tier whose threshold or rank is not 0, is rejected with `ERR_DUPLICATE_TIER` (HTTP 409).

Catalog rewards are added under a program with a `name`, a `point_cost` (the base cost of one unit, which must be strictly positive), an optional `tier_discount_pct` (a fractional discount on `point_cost` extended to higher tiers, defaulting to 0.0 and constrained to be at least 0 and strictly less than 1), and a `stock` count of units available for redemption (at least 0). A reward's `status` defaults to `ACTIVE`; an administrator may later discontinue it, moving it to `DISCONTINUED`.

Partner accounts are registered under a program with a `name`, a `transfer_block_size` (loyalty points may only be transferred in whole multiples of this size, at least 1), and a `min_transfer_points` floor (the minimum loyalty points per single transfer, at least 0). A partner's `status` defaults to `ACTIVE` and can be paused and resumed (Section 3.8).

### 3.2. Enrolling Members and the Referral Linkage

Member registration is a self-service action available to both a `Member` and a `ProgramAdmin`, permitted only while the program is `ACTIVE`. A registrant supplies the `program_id`, an `email` (which must be unique within the program), a `full_name`, a `birth_month_day` expressed as a two-part month-day string in `MM-DD` form, and optionally a `referred_by_member_id` naming the member who invited them. A registration whose `email` already belongs to a member of that program is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A new member starts in `ACTIVE` status, with `current_tier_code` resolved to `STANDARD`, a `last_birthday_grant_year` of null until the first birthday grant, and a `referred_by_member_id` of null when the registrant is organic.

When `referred_by_member_id` is supplied, registration also resolves an outstanding invitation: the server locates the `PENDING` `Referral` in this program whose `referrer_member_id` equals the supplied `referred_by_member_id` and whose `referee_email` equals the new member's `email`, and sets that referral's `referee_member_id` to the newly created member's id. The referral remains `PENDING` at this point — the linkage merely binds the invited member to the invitation; completion happens later, when that member makes a qualifying purchase (Section 3.6).

A member read recomputes and returns the member's derived balances and tier as described in Section 2.5. Administrators may suspend an `ACTIVE` member, driving them to `SUSPENDED`, and may reactivate a `SUSPENDED` member back to `ACTIVE`; the suspension gate of Section 2.8 governs what a suspended member may not do.

### 3.3. Earning Points: Purchases, Multipliers, and the Single Floor

The earn workflow begins when a purchase is recorded against a member. Both a `Member` and a `ProgramAdmin` may post a purchase, supplying the `member_id`, the `eligible_amount_cents` (the eligible spend in cents that earns points, which must be at least 0; a negative amount is rejected with `ERR_NEGATIVE_AMOUNT`, HTTP 422), and an optional `occurred_at` timestamp that defaults to the current clock time when omitted. The purchase is gated on the program being `ACTIVE` and the member being `ACTIVE`.

Recording a purchase mints redeemable points. The redeemable earn is computed from four factors: the dollar amount of eligible spend (the eligible cents divided by 100), the program's `base_earn_rate`, the member's tier multiplier (the `earn_multiplier` of the tier named by the member's `current_tier_code`, resolved *before* this earn is applied), and a promotion multiplier (the `bonus_multiplier` of the single promotion that applies to this purchase, or 1.0 when no promotion applies). These four factors are multiplied together at full real precision and the floor is taken exactly once at the very end to yield the integer `earned_points`; no intermediate multiplier is ever rounded. The minted points become a new `EARN_PURCHASE` `PointsLot` for the member, and an `EARN_PURCHASE` `PointsTransaction` is appended recording the positive `points_delta`. Posting a purchase recomputes the member's tier and balances and advances the member's `version` by one.

Distinct from redeemable earn is the purchase's tier-qualifying contribution. The `qualifying_points` of a purchase measure base spend only: they are the eligible dollars (eligible cents divided by 100) multiplied by the program's `base_earn_rate`, with the floor taken once — and they deliberately exclude both the tier multiplier and the promotion multiplier. This same value is stamped on the `PurchaseEvent.qualifying_points` field and carried on the resulting `EARN_PURCHASE` ledger row's `qualifying_points`, while every non-`EARN_PURCHASE` ledger row carries a `qualifying_points` of 0. The purchase event also records, for traceability only, the `applied_promotion_id` of the promotion that covered it (null when none applied) and a `posted` flag that is true once the points have been minted (always true on creation; it defaults to false only as the pre-mint initial value). A purchase by a member who has an outstanding invitation may complete a pending referral as a side effect, detailed in Section 3.6.

### 3.4. Tier Qualification over the Trailing Window

A member's tier is derived, not assigned. The platform measures qualifying points over a trailing window: starting from the current clock time and looking back by the program's `qualifying_window_months`, it sums the `qualifying_points` of the member's `EARN_PURCHASE` ledger rows whose `created_at` is at or after that window start, and this sum is the member's `qualifying_points_window`. The member's `current_tier_code` is then the `code` of the tier with the highest `rank` whose `qualify_threshold` is at or below the member's `qualifying_points_window`. The comparison is inclusive: a member whose window total exactly equals a tier's `qualify_threshold` qualifies for that tier. Because ranks are unique within a program, ties cannot arise; where reasoning about ordering is needed, the higher `rank` wins. Tier is recomputed on every purchase posting and on every expiration sweep, so that both earning and the passage of time can move a member between tiers.

### 3.5. Birthday Rewards

A `ProgramAdmin` may grant a member their birthday reward, which mints a `BIRTHDAY` `PointsLot` of exactly the program's `birthday_reward_points`, appends a `BIRTHDAY` `PointsTransaction`, records the calendar year of the grant on the member's `last_birthday_grant_year`, recomputes the member's balances, and advances the member's `version` by one. Two guards constrain the grant. First, it is allowed at most once per calendar year: a second grant in a year for which `last_birthday_grant_year` already records a grant is rejected with `ERR_BIRTHDAY_ALREADY_GRANTED` (HTTP 409). Second, it is allowed only on the member's actual birthday: the month-day of the current clock time must equal the member's `birth_month_day`, and a grant requested on any other day is rejected with `ERR_NOT_BIRTHDAY` (HTTP 409).

### 3.6. Referrals: Invitation, Completion, and Revert

A referral begins as an invitation created by a `Member` or a `ProgramAdmin`, supplying the `program_id`, the `referrer_member_id` of the inviting member, and the `referee_email` the invitation is addressed to. Two checks guard creation. The `referee_email` must differ from the referrer's own email — a self-referral is rejected with `ERR_SELF_REFERRAL` (HTTP 409). And the `referee_email` must not already belong to a registered member of the program at the time the invitation is created; an invitation to an already-enrolled address is rejected with `ERR_REFEREE_EXISTS` (HTTP 409). A new referral starts in `PENDING` status with a null `referee_member_id` and a null `completed_at`; the `referee_member_id` is filled in later when the invited person registers and names the referrer (Section 3.2).

A pending referral completes automatically — driven by the system rather than by a direct caller — when the bound referee posts a purchase whose `eligible_amount_cents` is at or above the program's `referral_min_qualifying_cents`. Completion is permitted only when the referral is still `PENDING`, its `referee_member_id` is set (the referee has registered), and both the referee and the referrer are `ACTIVE` members. On completion the platform mints a `REFERRAL` `PointsLot` of the program's `referral_referrer_points` to the referrer and appends a `REFERRAL` `PointsTransaction` for them; mints a `REFERRAL` `PointsLot` of the program's `referral_referee_points` to the referee and appends a `REFERRAL` `PointsTransaction` for them; sets the referral's `completed_at` to the current clock time; recomputes balances for both members; and moves the referral to the terminal `COMPLETED` status.

Two terminal exits leave the ledger untouched. A pending referral that has aged beyond the program's `lot_expiration_months` since its creation is moved to `EXPIRED` during an expiration sweep once the clock has reached or passed that point — no points are granted and no ledger entry is written. A `ProgramAdmin` may revoke a still-`PENDING` referral, moving it to `REVOKED`, again with no points granted and no ledger change. Both expiry and revocation are legal only from `PENDING`. The referrals in which a given member participates can be listed for that member and narrowed by a `role` filter that selects whether the member appears as the referrer or as the referee.

### 3.7. Redeeming Catalog Rewards: Quote, Confirm, Fulfill, and Cancel

A redemption is the burn-side lifecycle, and it is deliberately a two-cost story. A `Member` or `ProgramAdmin` opens a redemption by quoting it against a program that is `ACTIVE`, supplying the burning `member_id` and a set of `lines`, each line naming a `reward_id` and a `quantity` of at least 1. A redemption submitted with no lines is rejected with `ERR_EMPTY_REDEMPTION` (HTTP 422), and a line whose `quantity` is below 1 is rejected with `ERR_INVALID_QUANTITY` (HTTP 422). Each line must reference a reward that is `ACTIVE` and belongs to the member's own program; a line pointing at a `DISCONTINUED` reward or one outside the member's program is rejected with `ERR_REWARD_UNAVAILABLE` (HTTP 409).

For every line the platform computes a `line_cost_points`. The applicable discount on a line is the reward's `tier_discount_pct` when the member's tier is at `GOLD` rank or higher (that is, when the tier's `rank` is at least 2, the rank assigned to `GOLD`), and 0.0 otherwise. The line's cost is then the line `quantity` multiplied by the reward's `point_cost` multiplied by one minus the applicable discount, with the result rounded half up to a whole number of points. The redemption's `quoted_cost_points` is the sum of these per-line rounded costs — rounded per line first, then summed, per Section 2.7. The quote reserves `quoted_cost_points` against the member's balance, and the redemption's `redemption_id` ties each `RedemptionLine` back to its parent; a new redemption begins in `QUOTED` status with a null `final_cost_points`.

Confirmation is performed by the `Member` (or a `ProgramAdmin` acting for them) and is legal only from `QUOTED`. It requires the program-and-member gates of Section 2.8, that the member's `available_points` be at least the `quoted_cost_points` (a shortfall is rejected with `ERR_INSUFFICIENT_POINTS`, HTTP 409), and the optimistic-concurrency guard of Section 2.9 carried in `expected_member_version`. On confirmation the platform burns `quoted_cost_points` from the member's lots in first-in-first-out order — oldest `created_at` first, breaking ties between identical timestamps by lot id ascending — decrementing each consumed lot's `remaining_points` and moving a lot to `EXHAUSTED` the moment its `remaining_points` reaches 0. One `REDEEM` `PointsTransaction` (with a negative `points_delta` and `ref_redemption_id` set to this redemption) is appended per consumed lot, the member's balances are recomputed, the member's `version` is advanced by one, and the redemption moves from `QUOTED` to `CONFIRMED`. A lot whose `expires_at` is at or before the current clock time is not burnable until it is swept; the FIFO burn skips such past-expiry lots, and the internal guard against drawing from one is `ERR_LOT_EXPIRED` (HTTP 409).

Fulfillment is performed by a `ProgramAdmin` and is legal only from `CONFIRMED`. It requires that every line's reward still be `ACTIVE` and that every line's reward have `stock` at least the line `quantity`; insufficient stock at fulfillment is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). Fulfillment recomputes the cost as a *final* variant, re-resolving the member's `current_tier_code` at fulfillment time and recomputing each line's discount from that tier; the result is `final_cost_points`. If the member crossed the `GOLD` rank boundary between quote and fulfillment, the discount toggles and `final_cost_points` will differ from `quoted_cost_points`. When `final_cost_points` is less than `quoted_cost_points`, the platform refunds the difference by minting a refund lot (sourced as an `EARN_BONUS` lot) of `quoted_cost_points` minus `final_cost_points` and appending an `EARN_BONUS` `PointsTransaction`. When `final_cost_points` is greater than `quoted_cost_points`, the platform burns the shortfall — the extra points beyond what was already reserved — in FIFO order with additional `REDEEM` rows. Fulfillment then decrements each line's reward `stock` by the line `quantity`, recomputes the member's balances, and moves the redemption to the terminal `FULFILLED` status.

Cancellation may be performed by the `Member` or a `ProgramAdmin` and has two distinct shapes depending on the redemption's state. Cancelling from `QUOTED` is clean: no points were ever burned in the quoted state, so there is nothing to refund, and the redemption simply moves to the terminal `CANCELLED` status. Cancelling from `CONFIRMED` is a compensating action: because the confirm already burned `quoted_cost_points`, cancellation mints a single compensating `EARN_BONUS` `PointsLot` of `quoted_cost_points` back to the member and appends a compensating `EARN_BONUS` `PointsTransaction` (with a positive `points_delta` and `ref_redemption_id` set to this redemption), recomputes the member's balances to restore point conservation, and moves the redemption to `CANCELLED`. Both cancellation paths require the redemption to be in a cancellable state and otherwise yield the invalid-state rejection of Section 2.8.

### 3.8. Partner Transfers: Conversion, Compensation, and Blackouts

A partner transfer converts a member's loyalty points into a partner's currency. A `Member` (or a `ProgramAdmin` acting for them) submits a transfer against an `ACTIVE` program, supplying the `member_id`, the `partner_account_id`, the `loyalty_points` to spend (which must be strictly positive), and the optimistic-concurrency `expected_member_version` of Section 2.9. The `loyalty_points` must be a positive whole multiple of the partner's `transfer_block_size` and must be at least the partner's `min_transfer_points`; a value violating either constraint is rejected with `ERR_INVALID_TRANSFER_BLOCK` (HTTP 422). The submission is gated on the member being `ACTIVE`, the partner being `ACTIVE` (a paused partner yields `ERR_PARTNER_PAUSED`), and the member's `available_points` being at least the `loyalty_points` (a shortfall yields `ERR_INSUFFICIENT_POINTS`).

The number of partner points credited is derived in a pinned order. First the member's `current_tier_code` is resolved through the trailing-window tier evaluation of Section 3.4; then the conversion ratio is taken as the `transfer_ratio` of that tier; then the `partner_points` is the `loyalty_points` multiplied by that ratio, with the floor taken once. The qualifying window is not re-derived from this transfer — a transfer burns redeemable points but contributes zero qualifying points — so the member's tier cannot change as a result of computing the conversion. A submitted transfer burns `loyalty_points` from the member's lots in FIFO order (recording `TRANSFER_OUT` ledger rows referencing the transfer through `ref_transfer_id`), recomputes the member's balances, advances the member's `version` by one, and enters `SUBMITTED` status.

A submitted transfer reaches its terminal `SETTLED` status when the partner's operator settles it; settlement is legal only from `SUBMITTED` and only while the partner account is `ACTIVE`, after which the partner credits the converted points externally. Alternatively, a submitted transfer may be reversed by the `PartnerOperator` or a `ProgramAdmin`; reversal is legal only from `SUBMITTED` and is a compensating action that mints a `TRANSFER_IN_REVERSAL` `PointsLot` of the original `loyalty_points` back to the member, appends a `TRANSFER_IN_REVERSAL` `PointsTransaction` (referencing the transfer through `ref_transfer_id`), recomputes the member's balances, and moves the transfer to the terminal `REVERSED` status — restoring the member's net minted-minus-burned loyalty points to their pre-transfer value.

Partner availability is controlled in two ways. An administrator may pause an `ACTIVE` partner (moving it to `PAUSED`, after which new transfers are refused with `ERR_PARTNER_PAUSED`) and resume a `PAUSED` partner back to `ACTIVE`. Independently, transfer blackouts model maintenance windows. A blackout is scheduled on a partner by a `ProgramAdmin` or `PartnerOperator` with the parent `partner_account_id`, a `starts_at`, and an `ends_at`, and it represents a closed interval in which both ends are inclusive. Its `ends_at` must be at or after its `starts_at`; a blackout whose `ends_at` is before its `starts_at` is rejected with `ERR_INVALID_WINDOW` (HTTP 422). A new blackout must keep clear of every existing `SCHEDULED` blackout on the same partner by a sixty-minute buffer on each side: the new interval conflicts when its `starts_at` is at or before an existing blackout's `ends_at` extended forward by sixty minutes, and at the same time the existing blackout's `starts_at` pulled back by sixty minutes is at or before the new interval's `ends_at`. A conflicting or within-buffer schedule is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409). A new blackout's `status` defaults to `SCHEDULED`, and an administrator or partner operator may cancel a `SCHEDULED` blackout, moving it to the terminal `CANCELLED` status and excluding it from future overlap checks. At transfer submit time, a transfer is refused with `ERR_TRANSFER_BLACKED_OUT` (HTTP 409) when any `SCHEDULED` blackout on the partner covers the current clock time, where coverage is the closed interval — the clock time at or after `starts_at` and at or before `ends_at`.

### 3.9. Expiration Sweeps and the Maintenance Clock

The platform runs on a logical clock that an administrator can drive directly for testing: one capability sets the current UTC instant to a supplied `to_iso8601` value, and another advances the clock forward by a supplied number of `months`. Both report the resulting `now`.

An expiration sweep, run by a `ProgramAdmin`, reconciles the program against the clock. The sweep collects every `PointsLot` that is `ACTIVE`, whose `expires_at` is at or before the current clock time, and whose `remaining_points` is still above 0, and processes those candidate lots in ascending `created_at` order (breaking ties between equal timestamps by lot id ascending). For each such lot it appends an `EXPIRE` `PointsTransaction` whose `points_delta` is the negative of the lot's `remaining_points`, sets that lot's `remaining_points` to 0, and moves the lot to the terminal `EXPIRED` status; after processing it recomputes the affected members' balances. A lot's `expires_at` is itself set at minting to its `created_at` advanced by the program's `lot_expiration_months`. The same sweep also ages out referrals: any `PENDING` referral whose creation is older than the program's `lot_expiration_months` relative to the clock is moved to `EXPIRED` with no ledger effect. Separately, a lot reaches the terminal `EXHAUSTED` status — distinct from `EXPIRED` — the moment a burn drives its `remaining_points` to exactly 0, at which point it no longer contributes to the member's `available_points`.

A `PointsLot` records, for each lot, the owning `member_id`, the `source_type` (one of `EARN_PURCHASE`, `EARN_BONUS`, `BIRTHDAY`, `REFERRAL`, or `TRANSFER_IN_REVERSAL`), a `source_id` carrying the originating event's id for traceability only (never a decision input, and null where not applicable), the `original_points` minted into the lot at creation (always strictly positive), the `remaining_points` (the original amount less cumulative burned and expired points, floored at 0), the `expires_at`, and the lot `status`. Every ledger row — a `PointsTransaction` — records the `member_id`, the `lot_id` it minted or drew from (null for pure aggregate corrections), the `type` (one of `EARN_PURCHASE`, `EARN_BONUS`, `BIRTHDAY`, `REFERRAL`, `REDEEM`, `TRANSFER_OUT`, `EXPIRE`, or `TRANSFER_IN_REVERSAL`), the signed `points_delta`, the `qualifying_points` contribution (nonzero only for `EARN_PURCHASE`), and the cross-references `ref_redemption_id` and `ref_transfer_id` set on the rows that pertain to a redemption or a transfer respectively.

### 3.10. Promotions and Promotion Selection

A bonus-point promotion is scheduled under a program by a `ProgramAdmin` with the parent `program_id`, a display `name`, a `bonus_multiplier` (the multiplier stacked onto redeemable earn while the window is live, at least 1.0), an inclusive-start `starts_at`, an exclusive-end `ends_at`, and an optional `min_eligible_cents` floor (the minimum purchase eligible amount for the promotion to apply, defaulting to 0). A promotion's window is half-open: it covers a purchase whose moment is at or after `starts_at` and strictly before `ends_at`. The `ends_at` must be strictly after the `starts_at`; otherwise the schedule is rejected with `ERR_INVALID_WINDOW` (HTTP 422). A new promotion's half-open window must not overlap any non-`CANCELLED` promotion in the program; adjacency is allowed (one window's `ends_at` may equal another's `starts_at`), and two windows overlap exactly when the new `starts_at` is strictly before the existing `ends_at` and the existing `starts_at` is strictly before the new `ends_at`. An overlapping schedule is rejected with `ERR_PROMOTION_OVERLAP` (HTTP 409). A new promotion's `status` defaults to `SCHEDULED`.

Promotions advance through their lifecycle against the clock. A refresh capability, run by a `ProgramAdmin`, moves a `SCHEDULED` promotion to `ACTIVE` once the clock is within its window (at or after `starts_at` and strictly before `ends_at`) and moves an `ACTIVE` promotion to the terminal `ENDED` status once the clock has reached or passed its `ends_at`. An administrator may also cancel a promotion that is `SCHEDULED` or `ACTIVE`, moving it to the terminal `CANCELLED` status; cancellation stops the promotion from applying to future purchases but leaves already-earned points untouched. When a purchase is being priced, the promotion that applies is the single promotion whose window covers the purchase moment and whose `min_eligible_cents` floor is satisfied by the purchase's `eligible_amount_cents`; its `bonus_multiplier` becomes the promotion multiplier in the earn calculation of Section 3.3, and its id is recorded on the purchase's `applied_promotion_id`. When no promotion qualifies, the promotion multiplier is 1.0 and `applied_promotion_id` is null.

### 3.11. Validation Ordering across an Endpoint

When several checks could fire on a single request, they are evaluated in a fixed priority order so that the rejection a caller sees is deterministic. Authentication comes first: the presence of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`) is checked before role permission (`ERR_FORBIDDEN`), which is checked before resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`). Existence of every path- and body-referenced resource (`ERR_NOT_FOUND`), validated left to right, comes next. Then come request-shape checks — required body fields present and well-typed, enums within their domains, `birth_month_day` in `MM-DD` form, timestamps in ISO form (`ERR_INVALID_REQUEST`), pagination bounds (`ERR_VALIDATION_LIMIT`), configuration-rate bounds (`ERR_INVALID_RATE`), non-negative purchase amounts (`ERR_NEGATIVE_AMOUNT`), non-empty redemptions (`ERR_EMPTY_REDEMPTION`), and per-line quantity (`ERR_INVALID_QUANTITY`) — followed by uniqueness and configuration conflicts (`ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_TIER`) and temporal-window conflicts (`ERR_PROMOTION_OVERLAP`, `ERR_BLACKOUT_OVERLAP`).

After shape and conflict checks, state and business gates apply in order: the program-active gate (`ERR_PROGRAM_NOT_ACTIVE`), the target-state gate for the requested transition (`ERR_INVALID_STATE`), the member-active gate (`ERR_MEMBER_NOT_ACTIVE`), the partner-active gate (`ERR_PARTNER_PAUSED`), the transfer-blackout gate (`ERR_TRANSFER_BLACKED_OUT`), the internal past-expiry lot guard (`ERR_LOT_EXPIRED`), the transfer-block constraint (`ERR_INVALID_TRANSFER_BLOCK`), reward availability (`ERR_REWARD_UNAVAILABLE`), fulfillment stock (`ERR_INSUFFICIENT_STOCK`), and then the fiscal sufficiency check that the member's `available_points` covers the `quoted_cost_points` at confirm or the `loyalty_points` at transfer submit (`ERR_INSUFFICIENT_POINTS`). The birthday guards (`ERR_BIRTHDAY_ALREADY_GRANTED` before `ERR_NOT_BIRTHDAY`) and the referral-creation guards (`ERR_SELF_REFERRAL` before `ERR_REFEREE_EXISTS`) apply on their respective endpoints. The optimistic-concurrency check on `expected_member_version` (`ERR_STALE_MEMBER_VERSION`) is evaluated last on confirm and transfer submit, immediately before the write, so that a stale-version rejection is never masked by a check that would otherwise have run after it.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, run a maintenance action, or read data return `200 OK`. The request and response payloads for each operation are described in the Section 3 workflow that governs it; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a loyalty program | ProgramAdmin |
| POST | `/programs/{id}/activate` | Activate a program | ProgramAdmin |
| POST | `/programs/{id}/close` | Close a program | ProgramAdmin |
| GET | `/programs/{id}` | Get a program | ProgramAdmin, Member, PartnerOperator |
| GET | `/programs` | List programs | ProgramAdmin |
| POST | `/programs/{id}/tiers` | Define a tier | ProgramAdmin |
| GET | `/programs/{id}/tiers` | List a program's tiers | ProgramAdmin, Member |
| POST | `/programs/{id}/promotions` | Schedule a bonus-point promotion | ProgramAdmin |
| GET | `/programs/{id}/promotions` | List a program's promotions | ProgramAdmin, Member |
| POST | `/promotions/{id}/cancel` | Cancel a promotion | ProgramAdmin |
| POST | `/programs/{id}/refresh-promotions` | Advance promotion lifecycle against the clock | ProgramAdmin |
| POST | `/programs/{id}/rewards` | Add a catalog reward | ProgramAdmin |
| GET | `/programs/{id}/rewards` | List a program's rewards | ProgramAdmin, Member |
| POST | `/rewards/{id}/discontinue` | Discontinue a reward | ProgramAdmin |
| POST | `/programs/{id}/partners` | Register a partner account | ProgramAdmin |
| POST | `/partners/{id}/pause` | Pause a partner account | ProgramAdmin |
| POST | `/partners/{id}/resume` | Resume a paused partner account | ProgramAdmin |
| GET | `/partners/{id}` | Get a partner account | ProgramAdmin, Member, PartnerOperator |
| GET | `/programs/{id}/partners` | List a program's partners | ProgramAdmin, Member, PartnerOperator |
| POST | `/members` | Register a member | ProgramAdmin, Member |
| GET | `/members/{id}` | Get a member with computed balances and tier | ProgramAdmin, Member |
| GET | `/members` | List members, filterable by program or referrer | ProgramAdmin |
| POST | `/members/{id}/suspend` | Suspend a member | ProgramAdmin |
| POST | `/members/{id}/reactivate` | Reactivate a suspended member | ProgramAdmin |
| POST | `/members/{id}/birthday-grant` | Grant birthday reward points | ProgramAdmin |
| GET | `/members/{id}/lots` | List a member's points lots | ProgramAdmin, Member |
| GET | `/transactions/{id}` | Get a single ledger transaction | ProgramAdmin, Member |
| GET | `/transactions` | List ledger transactions, filterable | ProgramAdmin, Member |
| POST | `/purchase-events` | Record an eligible purchase | ProgramAdmin, Member |
| GET | `/purchase-events/{id}` | Get a purchase event | ProgramAdmin, Member |
| GET | `/purchase-events` | List purchase events, filterable | ProgramAdmin, Member |
| POST | `/redemptions` | Quote a catalog redemption | ProgramAdmin, Member |
| GET | `/redemptions/{id}` | Get a redemption | ProgramAdmin, Member |
| GET | `/members/{id}/redemptions` | List a member's redemptions | ProgramAdmin, Member |
| GET | `/redemptions/{id}/lines` | List a redemption's lines | ProgramAdmin, Member |
| GET | `/redemption-lines/{id}` | Get a single redemption line | ProgramAdmin, Member |
| GET | `/redemption-lines` | List redemption lines, filterable | ProgramAdmin, Member |
| POST | `/redemptions/{id}/confirm` | Confirm a quoted redemption | Member, ProgramAdmin |
| POST | `/redemptions/{id}/fulfill` | Fulfill a confirmed redemption | ProgramAdmin |
| POST | `/redemptions/{id}/cancel` | Cancel a redemption | Member, ProgramAdmin |
| POST | `/referrals` | Create a referral invitation | ProgramAdmin, Member |
| GET | `/referrals/{id}` | Get a referral | ProgramAdmin, Member |
| GET | `/referrals` | List referrals, filterable by program | ProgramAdmin |
| GET | `/members/{id}/referrals` | List referrals where a member is referrer or referee | ProgramAdmin, Member |
| POST | `/referrals/{id}/revoke` | Revoke a pending referral | ProgramAdmin |
| POST | `/partner-transfers` | Submit a partner-points transfer | Member, ProgramAdmin |
| GET | `/partner-transfers/{id}` | Get a partner transfer | ProgramAdmin, Member, PartnerOperator |
| GET | `/members/{id}/partner-transfers` | List a member's partner transfers | ProgramAdmin, Member |
| GET | `/partners/{id}/transfers` | List a partner's transfers | ProgramAdmin, PartnerOperator |
| POST | `/partner-transfers/{id}/settle` | Settle a submitted transfer | PartnerOperator |
| POST | `/partner-transfers/{id}/reverse` | Reverse a submitted transfer | PartnerOperator, ProgramAdmin |
| POST | `/partners/{id}/blackouts` | Schedule a transfer-blackout interval | ProgramAdmin, PartnerOperator |
| GET | `/blackouts/{id}` | Get a transfer blackout | ProgramAdmin, PartnerOperator |
| GET | `/partners/{id}/blackouts` | List a partner's transfer blackouts | ProgramAdmin, PartnerOperator |
| POST | `/blackouts/{id}/cancel` | Cancel a scheduled transfer blackout | ProgramAdmin, PartnerOperator |
| POST | `/programs/{id}/sweep-expirations` | Expire due lots and stale pending referrals | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the system clock (test-driving) | ProgramAdmin |
| POST | `/_clock/advance` | Advance the system clock by months (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_TIER` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_PROMOTION_OVERLAP` | 409 |
| `ERR_BLACKOUT_OVERLAP` | 409 |
| `ERR_TRANSFER_BLACKED_OUT` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_PARTNER_PAUSED` | 409 |
| `ERR_LOT_EXPIRED` | 409 |
| `ERR_INVALID_TRANSFER_BLOCK` | 422 |
| `ERR_REWARD_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_BIRTHDAY_ALREADY_GRANTED` | 409 |
| `ERR_NOT_BIRTHDAY` | 409 |
| `ERR_SELF_REFERRAL` | 409 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_EMPTY_REDEMPTION` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_NEGATIVE_AMOUNT` | 422 |
| `ERR_REFEREE_EXISTS` | 409 |
| `ERR_INVALID_RATE` | 422 |
| `ERR_VALIDATION_LIMIT` | 422 |
| `ERR_PROGRAM_ALREADY_ACTIVE` | 409 |
