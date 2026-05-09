# Online Auction API — Product Requirements Document

## 1. Introduction

Online auction marketplaces fail when a single ambiguity slips through: two bidders ratcheting at the last second, a winner who walks away from payment, a proxy that overshoots its ceiling, a buyer who claims the item arrived broken. This document specifies the contract for the Online Auction service — a system that runs lots from listing through bidding, settlement, payment, and (where necessary) dispute arbitration, and that synchronises with external payment, identity-verification, and logistics systems through a small set of event-ingestion endpoints.

The service is owned by a platform operator who registers sellers and bidders, credits bidder wallets, and exercises override authority over risk and lifecycle edge cases. Sellers list lots and pick scheduling and pricing parameters. Bidders place bids manually or delegate them to a proxy with a private maximum. The platform handles the fiddly parts: increment ladders, deposit holds, soft-close extensions, tiered commissions, runner-up flows after a default, multi-stage dispute review, refund-induced commission reversal, and a risk engine that combines chronic and acute signals to restrict or suspend abusive accounts.

Two design constraints shape the rest of this document. First, **all monetary values are integer cents** — there is no decimal type in the API surface. Second, **time is deterministic**. Tests advance a logical system clock instead of waiting for wall-clock time; transitions that depend on `now()` (auction start, auction close, payment deadline expiry, runner-up window expiry) are evaluated whenever the clock moves.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must include two headers: `X-User-ID` (the acting principal's identifier) and `X-User-Role` (one of the five role names enumerated below). A request missing either header, or carrying an empty value, or naming a role outside the recognised set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP status 400. A request whose role lacks permission to invoke the endpoint is rejected with `ERR_ROLE_FORBIDDEN` and HTTP status 403.

The five roles are `Seller`, `Bidder`, `ArbitratorOps`, `PlatformAdmin`, and `Anonymous`. They split into two identity families:

- **Entity-backed roles.** When `X-User-Role` is `Seller`, the `X-User-ID` value is the `id` of the acting `Seller`; ownership checks on a lot compare `Lot.seller_id` to `X-User-ID`. When `X-User-Role` is `Bidder`, the `X-User-ID` value is the `id` of the acting `Bidder`; ownership checks on a bid, an auto-bid proxy, a deposit, a runner-up acceptance, or a dispute compare the resource's `bidder_id` (or, for runner-up acceptance, the `Bidder.id` referenced by `Lot.runner_up_bid_id`'s `bidder_id`, and for dispute filing, `Lot.winning_bidder_id`) to `X-User-ID`.
- **Opaque-identity roles.** When `X-User-Role` is `ArbitratorOps`, `PlatformAdmin`, or `Anonymous`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may record it (specifically, the `ArbitratorOps` value is captured into `Dispute.arbitrator_user_id` when review begins, and a dispute filer's `X-User-ID` — entity-backed in practice but treated as opaque at write time — is captured into `Dispute.filer_user_id`) but does not enforce equality with an `id` lookup.

When the role passes the role-permission check (priority 2) but the acting principal is not the resource's owner under the rules above, the request is rejected with `ERR_IDENTITY_MISMATCH` and HTTP status 403.

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

List endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, has a minimum of 1, and a maximum of 100; values outside that range are rejected as `ERR_INVALID_REQUEST`. `offset` defaults to 0 and is non-negative. Results are ordered by `created_at` ascending unless an endpoint's narrative says otherwise (the per-lot bid listing is the one exception — it is sorted by `placed_at` descending). Each list response's `meta` block carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource is keyed by an `id` value: a server-minted UUID with no type prefix. The acting principal never supplies an `id` on creation. All datetime fields use ISO 8601 UTC strings with three fractional digits.

Most entities — `Seller`, `Bidder`, `Lot`, `AutoBidProxy`, `Deposit`, `Invoice`, and `Dispute` — additionally carry `created_at`, `updated_at`, and a monotonically increasing integer `version` that starts at 1. `updated_at` is refreshed on every mutation, including cascaded side-effects triggered by other workflows (so a deposit released as a side-effect of a bidder suspension has its `updated_at` and `version` advanced, not just the suspended bidder's). The lone exception is `Bid`, which carries only `id` and `created_at` — `updated_at` and `version` are absent on bid resources, since a placed bid is immutable apart from server-driven status changes (and even those do not bump a `version` on the bid itself, which has none).

Optimistic concurrency control is opt-in. A mutation request body may include a `version` field. If supplied and the integer does not match the current server-side `version` of the target resource, the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — this is the OCC-failure signal in the §5 catalogue. Omit the `version` field to skip the check entirely. On every successful mutation (including cascade-driven mutations) the resource's `version` is incremented by one.

### 2.5. Path Hierarchy and Existence Validation

When an endpoint nests resources in its URL — for example, a dispute under a lot, a proxy under a lot, or a dispute resolution under a lot and a dispute — path parameters are validated left-to-right against existence. The leftmost unresolved id triggers the family-specific not-found error: `ERR_SELLER_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PROXY_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_DISPUTE_NOT_FOUND`. All seven respond with HTTP 404. Tests routinely supply random UUIDs for an inner segment to verify that the outer segment is checked first.

### 2.6. Validation Priority

When a single request triggers multiple checks, they are evaluated in a fixed order so that the same input always produces the same error. The order, from earliest to latest, is: (1) the user-context header check `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the role-permission check `ERR_ROLE_FORBIDDEN`; (3) the path-existence cascade producing one of the not-found errors; (4) the state check producing `ERR_LOT_INVALID_STATE`, `ERR_LOT_NOT_LIVE`, `ERR_BID_INVALID_STATE`, `ERR_PROXY_INVALID_STATE`, `ERR_INVOICE_NOT_ISSUED`, or `ERR_DISPUTE_INVALID_STATE`; (5) the bidder-status safety check `ERR_BIDDER_RESTRICTED`; (6) the affiliation safety check `ERR_SHILL_AFFILIATION`; (7) the cross-entity ownership check `ERR_IDENTITY_MISMATCH`; (8) the bid-increment check `ERR_BID_BELOW_MIN_INCREMENT`; (9) the strict-greater check `ERR_BID_NOT_HIGHER`; (10) the proxy creation checks `ERR_PROXY_MAX_TOO_LOW` and `ERR_PROXY_ALREADY_ACTIVE`; (11) the temporal checks `ERR_LOT_DURATION_TOO_SHORT`, `ERR_LOT_START_IN_PAST`, `ERR_RUNNER_UP_WINDOW_EXPIRED`, and `ERR_DISPUTE_WINDOW_EXPIRED`; (12) the temporal-overlap check `ERR_PHYSICAL_ITEM_TIME_OVERLAP`; (13) the deposit-funding check `ERR_INSUFFICIENT_DEPOSIT_FUNDS`; and (14) the dispute-resolution amount check `ERR_INVALID_REFUND_AMOUNT`. Generic body-shape errors — missing required fields, type mismatches, out-of-range scalars — surface as `ERR_INVALID_REQUEST` and are treated as preceding the priority-3 path-existence cascade (a malformed body never proceeds to a database lookup).

The relative ordering matters at every step: a `Seller`-affiliated `Bidder` placing a bid on a lot in `DRAFT` status receives `ERR_LOT_NOT_LIVE` first (priority 4 wins over priority 6); a suspended bidder placing a bid on a `LIVE` lot receives `ERR_BIDDER_RESTRICTED`, not `ERR_BID_BELOW_MIN_INCREMENT`, even if the amount is also wrong; and a request that fails both `ERR_BID_BELOW_MIN_INCREMENT` and `ERR_BID_NOT_HIGHER` surfaces only the first, since the increment check is evaluated before the strict-greater check.

### 2.7. Precision and Rounding

The system reasons about money as integer cents only. The bid-increment ladder, deposit calculation, and soft-close window all work on integer cents directly, with no rounding. The buyer-premium and seller-commission calculations multiply the integer hammer price by a decimal rate and **floor-truncate** the product to integer cents. The default-partial-refund split also floor-truncates after multiplying the integer deposit amount by the partial-refund rate. The commission-reversal calculation is the only place where rounding direction matters: it computes a refund-to-buyer-total ratio in `Decimal` arithmetic, quantises that ratio to four decimal places using `ROUND_HALF_UP`, multiplies the original `seller_commission_cents` by the quantised ratio, and quantises the product to integer cents using `ROUND_HALF_UP`. Doing the rounding in any other order produces a different value at the cents boundary; the order is fixed. The `Bidder.risk_score` is held in IEEE-754 double precision and is rounded half-up to one decimal place when stored.

### 2.8. Cascade Semantics and Cross-Entity Side Effects

Several operations mutate more than one entity in a single transaction. The system always applies the full cascade — partial application is not permitted. The three structurally most consequential cascades are:

- The **bidder-suspend cascade** triggered when a `Bidder` enters `SUSPENDED`. Hop one withdraws every `Bid` of theirs whose `status` is `ACTIVE` or `WINNING` to `WITHDRAWN_BY_RISK`. Hop two recomputes `current_winner_bid_id`, `current_winner_bidder_id`, `current_price_cents`, and `runner_up_bid_id` on every `Lot` whose former winner was this bidder, using the lot-current-state aggregation rule. Every `AutoBidProxy` of theirs in `ACTIVE` is moved to `CANCELLED`. Hop three releases every still-`HELD` `Deposit` of theirs on lots that are still `LIVE` or `SCHEDULED` to `RELEASED` with `terminal_reason = BIDDER_RISK_WITHDRAWN`, crediting the wallet by the deposit's `amount_cents`. Each affected resource has its `updated_at` refreshed and its `version` incremented; computed counters (`held_deposit_cents`, `withdrawal_count`, `bid_count`) are likewise refreshed.
- The **lot-close cascade** triggered when a `LIVE` `Lot` reaches `effective_end_at`. If the reserve is met, the lot moves to `SOLD`; the `Bid` referenced by `current_winner_bid_id` becomes `WINNING`; every other `ACTIVE` bid on the lot becomes `OUTBID`; an `Invoice` is created with `status = PENDING` and immediately auto-advances to `ISSUED` in the same transaction, with `buyer_premium_cents` and `seller_commission_cents` computed at issuance; and every `HELD` `Deposit` on the lot whose `bidder_id` is not the winner is `RELEASED` with `terminal_reason = LOSING_BIDDER` and `refund_amount_cents` equal to the deposit's `amount_cents`. If the reserve is not met, the lot moves to `UNSOLD` and every `HELD` deposit on the lot is `RELEASED` with `terminal_reason = LOSING_BIDDER`.
- The **refund cascade** triggered when a `Dispute` resolves with outcome `REFUND` and the `Lot` transitions `DISPUTED → REFUNDED`. Hop one moves the `Invoice` to `REVERSED` and writes `refund_amount_cents` from the dispute's `resolution_refund_amount_cents`. Hop two computes `commission_reversal_amount_cents` per the commission-reversal rule. Hop three recomputes the seller's `gross_proceeds_cents` and `net_proceeds_cents` so that `net_proceeds_cents` is reduced by the just-computed reversal amount. The buyer's `Deposit` for the lot is moved to `RELEASED` with `terminal_reason = DISPUTE_REFUND`.

Cascades on `RELIST` and on the runner-up-accept and runner-up-decline paths are described alongside the lifecycle narratives in §3.

### 2.9. Deterministic System Clock

Because the auction lifecycle has multiple time-driven transitions — `SCHEDULED → LIVE`, `LIVE → SOLD` or `LIVE → UNSOLD`, `SOLD → DEFAULTED` on payment-deadline expiry, `REOFFERED → UNSOLD` on runner-up-window expiry — the system runs against a logical clock that is advanced explicitly. When the clock moves, every time-gated transition whose threshold is now in the past is evaluated and applied, in the order: `SCHEDULED → LIVE` first (for lots whose `scheduled_start_at` has passed), then `LIVE → SOLD`/`UNSOLD` for lots whose `effective_end_at` has passed, then `SOLD → DEFAULTED` for lots whose `payment_deadline_at` has passed without a `PAID` `Invoice`, and finally `REOFFERED → UNSOLD` for lots whose `runner_up_acceptance_deadline_at` has passed without an accept or decline. The capability to advance the clock is admin-only and exists for testability — it is not a public-facing operation.

### 2.10. Concurrency Resolution

When two requests race against the same logical resource, exactly one wins and the loser receives a deterministic error. Five scenarios are explicitly specified:

- Two bid placements on the same lot, both clearing the increment ladder at the moment they were prepared, are serialised by `Lot.id`. Both bids may be persisted; the higher amount wins. Ties on amount are broken by the earlier server-side `placed_at`. The losing bid's `status` becomes `OUTBID`, and the winner's becomes `ACTIVE` (or `WINNING` when applicable). If the second-processed request's amount is no longer strictly greater than the now-current price, that request is rejected with `ERR_BID_NOT_HIGHER` (HTTP 409); if it is still strictly greater, both succeed.
- Two simultaneous auto-bid-proxy creations from the same bidder on the same lot serialise with first-writer-wins on the `(bidder_id, lot_id)` uniqueness key; the loser is rejected with `ERR_PROXY_ALREADY_ACTIVE` (HTTP 409).
- Two simultaneous publishes for distinct lots that share a `physical_item_serial` and have overlapping `[scheduled_start_at, effective_end_at)` intervals serialise first-writer-wins; the loser is rejected with `ERR_PHYSICAL_ITEM_TIME_OVERLAP` (HTTP 409).
- Two simultaneous payment-confirmed events for the same invoice serialise on the `ISSUED → PAID` transition; exactly one wins, and the loser is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409) because the invoice has, by then, already left `ISSUED`.
- A dispute resolve call and a clock-driven `SOLD → DEFAULTED` auto-transition for the same lot serialise on `Lot.status`; whichever lands first wins, and the other is rejected with `ERR_LOT_INVALID_STATE` (HTTP 409).

### 2.11. Risk and Affiliation Controls

A `Bidder` whose `affiliated_seller_id` matches a lot's `seller_id` may not place bids on that lot or create proxies for that lot; the request is rejected with `ERR_SHILL_AFFILIATION` (HTTP 403). Whenever a `Bidder.status` value is `RESTRICTED` or `SUSPENDED`, the bidder may not place bids, create proxies, accept a runner-up offer, or file disputes; such requests are rejected with `ERR_BIDDER_RESTRICTED` (HTTP 403). Both rules are enforced everywhere the action set lists them — the safety gates are not endpoint-local exceptions.

### 2.12. Domain Vocabulary

A few enum values referenced by callers are fixed:

- `Lot.category` is one of `ART`, `COLLECTIBLE`, `ELECTRONICS`, `JEWELRY`, `REAL_ESTATE`, or `VEHICLE`. The buyer-premium calculation assigns a category-conditional surcharge to `JEWELRY` only.
- `Lot.condition` is one of `NEW`, `LIKE_NEW`, `USED_GOOD`, `USED_FAIR`, or `FOR_PARTS`.
- `Lot.status` is one of `DRAFT`, `SCHEDULED`, `LIVE`, `SOLD`, `UNSOLD`, `REOFFERED`, `DEFAULTED`, `DISPUTED`, `REFUNDED`, `RELISTED`, or `CANCELLED`. The terminal members are `REFUNDED`, `RELISTED`, and `CANCELLED`; all others can still re-enter the lifecycle.
- `Bid.status` is one of `ACTIVE`, `WINNING`, `OUTBID`, `WITHDRAWN_BY_RISK`. `Bid.source` is `MANUAL` or `PROXY`.
- `AutoBidProxy.status` is one of `ACTIVE`, `EXHAUSTED`, `CANCELLED`; the latter two are terminal.
- `Deposit.status` is one of `HELD`, `RELEASED`, `FORFEITED`, `PARTIAL_REFUND`. `Deposit.terminal_reason` is one of `LOSING_BIDDER`, `WINNER_PAID`, `WINNER_DEFAULT_REOFFER_FILLED`, `WINNER_DEFAULT_NO_REOFFER`, `BIDDER_RISK_WITHDRAWN`, or `DISPUTE_REFUND`, and is `null` while the deposit is `HELD`.
- `Invoice.status` is one of `PENDING`, `ISSUED`, `PAID`, `REVERSED`. `REVERSED` is terminal.
- `Dispute.filed_by` is `BIDDER` or `SELLER`. `Dispute.status` is one of `FILED`, `UNDER_REVIEW`, `RESOLVED_REFUND`, `RESOLVED_RELIST`, `RESOLVED_DENIED`. `Dispute.resolution_outcome` is `REFUND`, `RELIST`, or `DENIED`, and is `null` until resolution.
- `Bidder.status` is one of `ACTIVE`, `RESTRICTED`, `SUSPENDED`. `Seller.status` is one of `ACTIVE`, `SUSPENDED`.

## 3. Business Logic & Workflows

### 3.1. Listing, Scheduling, and the Physical-Item Slot

A `Seller` creates a lot by submitting `seller_id`, `title` (1 to 200 characters), `category`, `condition`, `physical_item_serial`, `reserve_price_cents`, `starting_bid_cents`, `scheduled_start_at`, and `scheduled_end_at`. The lot is born in `DRAFT` status with `effective_end_at` left null and `current_price_cents` initialised to `starting_bid_cents` minus one (a placeholder so the first qualifying bid simply has to clear `starting_bid_cents`); `extension_count` starts at 0 and `bid_count` at 0. The body's `seller_id` must equal the `Seller`'s own `X-User-ID`; otherwise the request is rejected with `ERR_IDENTITY_MISMATCH`.

Publishing — the act that moves a lot from `DRAFT` to `SCHEDULED` — is the lifecycle gate that runs the schedule and slot-uniqueness checks. The interval between `scheduled_start_at` and `scheduled_end_at` must be at least one hour, expressed in seconds as a difference of at least 3600; a shorter interval produces `ERR_LOT_DURATION_TOO_SHORT`. The `scheduled_start_at` must be strictly after the current logical clock at the moment of publish; a start time at or before `now()` produces `ERR_LOT_START_IN_PAST`. The `starting_bid_cents` must be at least 1 and no greater than `reserve_price_cents`. And — the most consequential gate — no other lot may already hold the same `physical_item_serial` over an overlapping time window. The "active" status set for this comparison is `SCHEDULED`, `LIVE`, `SOLD`, `REOFFERED`, `DEFAULTED`, and `DISPUTED`; lots in `DRAFT`, `UNSOLD`, `REFUNDED`, `RELISTED`, or `CANCELLED` do not block. The intervals are half-open: lot A's `[scheduled_start_at, effective_end_at)` overlaps lot B's `[scheduled_start_at, scheduled_end_at)` if and only if A's interval starts strictly before B's ends and A's interval ends strictly after B's starts. Adjacency — A ending exactly at B's start — is therefore permitted. A violation produces `ERR_PHYSICAL_ITEM_TIME_OVERLAP`. On a successful publish, `effective_end_at` is initialised to `scheduled_end_at`.

A still-unstarted lot — one in `DRAFT` or `SCHEDULED` — may be cancelled by its owning `Seller`, which terminates the lot in `CANCELLED` with no further side-effects. Cancellation outside `DRAFT` and `SCHEDULED` is rejected with `ERR_LOT_INVALID_STATE`. When the logical clock crosses `scheduled_start_at`, the lot moves from `SCHEDULED` to `LIVE` automatically — the system does not require any actor to perform this transition.

### 3.2. Bid Mechanics, the Increment Ladder, and Soft-Close

A bid is a single integer field — `amount_cents` — carried in the placement payload by an `ACTIVE` `Bidder`. The lot must be in `LIVE` status: a bid attempt on a non-`LIVE` lot is rejected with `ERR_LOT_NOT_LIVE`. The bidder may not be affiliated with the lot's seller (priority 6) and may not be `RESTRICTED` or `SUSPENDED` (priority 5). Once those gates pass, two amount checks fire in order. The first compares `amount_cents` to the ladder-derived minimum; the second compares it to the current price for the strict-greater requirement.

The minimum-required-bid is computed from the **bid-increment ladder**, a tiered table whose key is the lot's `current_price_cents` (the *base* for the next bid, not the new bid's amount). The tiers, in order:

1. When the base is below 10000 cents (that is, below 100 dollars), the increment is 500 cents.
2. When the base is at least 10000 cents and below 100000 cents (between 100 and 1000 dollars), the increment is 1000 cents.
3. When the base is at least 100000 cents and below 1000000 cents (between 1000 and 10000 dollars), the increment is 5000 cents.
4. When the base is at least 1000000 cents and below 10000000 cents (between 10000 and 100000 dollars), the increment is 10000 cents.
5. When the base is at least 10000000 cents (at or above 100000 dollars), the increment is 50000 cents.

Tier lookup uses **strict less-than** against each tier's upper bound: a base price of exactly 10000 cents falls into the second tier (1000 cents step), not the first; a base of 9999 cents falls into the first tier (500 cents step). When the lot's `bid_count` is zero the minimum-required-bid is simply `starting_bid_cents`; otherwise it is `current_price_cents` plus the tier-derived increment. A submitted `amount_cents` less than the minimum-required-bid is rejected with `ERR_BID_BELOW_MIN_INCREMENT` (HTTP 422). Even if the increment check passes, a bid amount that is not strictly greater than `current_price_cents` (the duplicate-amount race case described in §2.10) is rejected with `ERR_BID_NOT_HIGHER` (HTTP 409).

A first qualifying bid by a given bidder on a given lot also creates a `Deposit` record. The required hold is 10% of the lot's `reserve_price_cents`, **floor-truncated** to integer cents on the percentage step, then clamped to a minimum of 500 cents and a maximum of 1000000 cents — concretely, the formula is the larger of 500 cents and the smaller of 1000000 cents and the floor-truncated 10% of the reserve. The fiscal precondition (priority 13) is that the bidder's `wallet_balance_cents` minus their existing `held_deposit_cents` is at least the new required deposit; on a lot for which the bidder already holds a `HELD` `Deposit`, no second deposit is calculated and no funds are re-checked. A funding gap produces `ERR_INSUFFICIENT_DEPOSIT_FUNDS` (HTTP 402). When the deposit is created, its `amount_cents` is captured at that moment and is immutable thereafter; the bid record's `deposit_id` references it. Subsequent bids by the same bidder on the same lot reuse the same `Deposit`. The bidder's `held_deposit_cents` is recomputed as the sum of `amount_cents` over all of that bidder's `HELD` deposits.

A successful placement updates the lot's aggregate state — `current_price_cents`, `current_winner_bid_id`, `current_winner_bidder_id`, `runner_up_bid_id`, `bid_count`, and `has_met_reserve` — by re-running the **lot-current-state aggregation**: take all bids on the lot whose `status` is `ACTIVE` or `WINNING`, sort them by `amount_cents` descending and break ties by `placed_at` ascending, and read the top entry as the new winner; the runner-up is the highest-ranked entry whose `bidder_id` differs from the winner's, with `null` when all eligible bids belong to a single bidder. The `bid_count` counts bids on the lot whose `status` is in `ACTIVE`, `WINNING`, or `OUTBID`, and `has_met_reserve` is true exactly when `current_price_cents` is at least `reserve_price_cents`.

A bid placed within the last minute of the auction triggers a **soft-close extension**. Specifically, if the seconds remaining to `effective_end_at` are at most 60 and strictly greater than zero, the lot's `effective_end_at` is advanced by 120 seconds, the lot's `extension_count` is incremented by one, and the just-placed `Bid`'s `triggered_extension` is set to true. The 60-second boundary is inclusive: at exactly 60 seconds remaining the extension fires, at 61 seconds it does not. Successive last-minute bids each fire their own extension.

The per-lot bid listing returns bids sorted by `placed_at` descending (most recent first); it does not redact the `bidder_id` of any bid.

### 3.3. Auto-Bid Proxies and Multi-Proxy Conflict

A `Bidder` may delegate ratchet-up bidding to an `AutoBidProxy` by submitting a single `max_amount_cents` against the lot — the bidder's secret ceiling. Creation requires the bidder to be `ACTIVE` and unaffiliated with the lot's seller, and the supplied `max_amount_cents` to be at least the lot's `starting_bid_cents` and at least the current minimum-required-bid (otherwise `ERR_PROXY_MAX_TOO_LOW`, HTTP 422). Only one `ACTIVE` proxy is permitted per `(bidder_id, lot_id)`; a second creation, even from a serialised race, is rejected with `ERR_PROXY_ALREADY_ACTIVE` (HTTP 409). The deposit-funding rule from §3.2 applies: a first qualifying placement (which can be a proxy emission) creates the deposit hold.

Proxy resolution runs in two situations — the moment a proxy is created and the moment any bid is placed on the lot — and behaves as follows. On creation, if the lot has no current winner, or if the bidder is not currently winning, the proxy emits an immediate `Bid` of exactly the current minimum-required-bid, with `source = PROXY` and `proxy_id` referencing the new proxy; the proxy's `last_executed_amount_cents` and `bids_emitted_count` are updated. After any later bid, every `ACTIVE` proxy on the lot whose owner is not the new winner emits a counter-bid, again at the post-bid minimum-required-bid. When two proxies are bidding against each other, this iteration walks them upward through the ladder until one proxy's next required emission would exceed its `max_amount_cents`; that proxy is moved to `EXHAUSTED` (`ERR_PROXY_INVALID_STATE` blocks any later operation) and the other proxy continues to hold the winner slot. A proxy whose owner becomes the winner stops emitting until challenged again. Every emission re-runs the lot-current-state aggregation and may itself trigger a soft-close extension whose `triggered_extension` flag belongs to the emitted `Bid`.

A `Bidder` may cancel their own still-`ACTIVE` proxy, moving it to `CANCELLED`. A proxy is also cancelled by the system whenever the parent `Lot` reaches a terminal-or-closed status or the owning `Bidder` is suspended. Cancellation outside `ACTIVE` produces `ERR_PROXY_INVALID_STATE`. The proxy read endpoint returns the full record to the proxy's owner (and to operators) but masks `max_amount_cents` for any other reader.

### 3.4. Auction Close, Settlement, and Commission

When the logical clock passes a `LIVE` lot's `effective_end_at`, the system fires the lot-close cascade described in §2.8. If `has_met_reserve` is true, the lot transitions to `SOLD`: `hammer_price_cents` is set to `current_price_cents`, `winning_bidder_id` to `current_winner_bidder_id`, `hammer_at` to the current logical clock value, and `payment_deadline_at` to `hammer_at` plus the platform's payment-deadline window in seconds. The bid identified by `current_winner_bid_id` is moved to `WINNING`; every other `ACTIVE` bid on the lot is moved to `OUTBID`. An `Invoice` is created in `PENDING` and immediately auto-advances to `ISSUED` in the same transaction; at issuance the `Invoice` snapshots `lot_id`, `buyer_id` (the winning bidder), `seller_id`, and `hammer_price_cents`, and computes the three composed monetary fields described below. Every `HELD` `Deposit` on the lot whose `bidder_id` is not the winner is `RELEASED` with `terminal_reason = LOSING_BIDDER` and `refund_amount_cents` set to the deposit's `amount_cents`. If `has_met_reserve` is false, the lot transitions to `UNSOLD`; every `HELD` deposit on the lot — including the would-be winner's — is `RELEASED` with `terminal_reason = LOSING_BIDDER`.

Three monetary fields are computed at issuance and stored on the `Invoice`. The **buyer premium** uses the average-rate model: the entire `hammer_price_cents` is multiplied by a single tiered rate (not a marginal-tier rate). The base rate is 15% when the hammer is at most 100000 cents, 12% when it is at most 1000000 cents, and 10% otherwise — the upper bounds are inclusive, so a hammer of exactly 100000 cents falls into the 15% tier and a hammer of 100001 cents into the 12% tier. The base rate is then increased by 2 percentage points if `Lot.category` is `JEWELRY`, and decreased by 1 percentage point if the winning bidder's `identity_verified` is true; the `JEWELRY` surcharge and verified-bidder discount stack independently and additively. The final premium is the floor-truncation of the hammer multiplied by the effective rate, raised to a minimum of 100 cents — so even a microscopic hammer pays at least one dollar of premium. The result is stored as `buyer_premium_cents`. The **seller commission** uses the same average-rate, single-rate-applies-to-entire-hammer model with a different ladder: 10% when the hammer is at most 500000 cents, 8% when it is at most 5000000 cents, and 5% otherwise; the floor-truncated product is stored as `seller_commission_cents`. From these the `Invoice` records `buyer_total_cents` as the sum of `hammer_price_cents` and `buyer_premium_cents`, `seller_payout_cents` as the difference between `hammer_price_cents` and `seller_commission_cents`, and `platform_take_cents` as the sum of `buyer_premium_cents` and `seller_commission_cents`.

Payment is recorded by the external payment system through an event ingestion: arriving with an `invoice_id` and a `paid_at`, the event moves the `Invoice` from `ISSUED` to `PAID` provided `paid_at` is at or before `payment_deadline_at`; the `Invoice.paid_at` is captured. As side-effects, the buyer's `Deposit` on the lot is `RELEASED` with `terminal_reason = WINNER_PAID` and `refund_amount_cents` equal to the deposit's `amount_cents` (so paid winners get their full deposit back), and the seller's `gross_proceeds_cents` and `net_proceeds_cents` each increase by the invoice's `seller_payout_cents`. A payment-confirmed event for an `Invoice` not in `ISSUED` — already `PAID`, already `REVERSED`, or still `PENDING` — is rejected with `ERR_INVOICE_NOT_ISSUED`.

A winner who fails to pay before `payment_deadline_at` (whether the platform admin applies the manual-default override or the clock simply passes the deadline with the invoice not in `PAID`) drives the lot from `SOLD` to `DEFAULTED`. The defaulter's `Bidder.acute_score` is increased by 20 and `risk_score` is recomputed; the chronic side of the score (which is driven by `withdrawal_count` and `dispute_loss_count`) is unaffected — `dispute_loss_count` does not move on a default. From `DEFAULTED` the system inspects whether `runner_up_bid_id` is non-null at the moment of the default. If a runner-up exists, the lot moves immediately to `REOFFERED`, and `runner_up_acceptance_deadline_at` is set to the current logical clock value plus the runner-up acceptance-window duration in seconds. If no runner-up exists, the lot moves immediately to `UNSOLD`: the defaulter's `Deposit` (the one whose `bidder_id` is the defaulter and `lot_id` is this lot) is moved to `FORFEITED` with `terminal_reason = WINNER_DEFAULT_NO_REOFFER`, `refund_amount_cents = 0`, and `forfeit_amount_cents` equal to the deposit's `amount_cents`; the `Invoice` is moved to `REVERSED` with `refund_amount_cents = 0`.

While the lot is `REOFFERED`, the runner-up — the `Bidder` referenced by `Lot.runner_up_bid_id`'s `bidder_id` — may accept or decline. Accepting before `runner_up_acceptance_deadline_at` and while the bidder is `ACTIVE` moves the lot back to `SOLD`: `winning_bidder_id` is updated to the runner-up, `hammer_price_cents` becomes the runner-up bid's `amount_cents`, the runner-up bid's `status` becomes `WINNING` and `Lot.current_winner_bid_id` updates accordingly (the previously `WINNING` bid that belonged to the defaulter retains the `WINNING` status flag on its own row, but the lot no longer points at it), the original `Invoice` is moved to `REVERSED` with `refund_amount_cents = 0`, a fresh `Invoice` is created with `status = ISSUED`, and `payment_deadline_at` is set to the current logical clock value plus the payment-deadline window. The defaulter's `Deposit` is moved to `PARTIAL_REFUND` with `terminal_reason = WINNER_DEFAULT_REOFFER_FILLED`: its `refund_amount_cents` is the floor-truncation of the deposit's `amount_cents` multiplied by 0.50 (the 50% partial-refund rate that applies when the reoffer is filled), and its `forfeit_amount_cents` is the deposit's `amount_cents` minus that refund. The runner-up's own `Deposit` remains `HELD` and continues to back the new `Invoice`. Declining — or letting the runner-up window elapse, evaluated whenever the clock advances — moves the lot from `REOFFERED` to `UNSOLD`: the defaulter's `Deposit` is moved to `FORFEITED` with `terminal_reason = WINNER_DEFAULT_NO_REOFFER` and `refund_amount_cents = 0`, the runner-up's `Deposit` is `RELEASED` with `terminal_reason = LOSING_BIDDER`, and the (replacement) `Invoice` is moved to `REVERSED` with `refund_amount_cents = 0`. A runner-up acceptance after the deadline produces `ERR_RUNNER_UP_WINDOW_EXPIRED` (HTTP 409).

Attempts to invoke any of the close-or-settlement actions outside the appropriate state — defaulting a lot that is not `SOLD`, accepting or declining a runner-up offer on a lot that is not `REOFFERED` — are rejected with `ERR_LOT_INVALID_STATE`.

### 3.5. Disputes, Arbitration, and the Refund Cascade

After a lot is `SOLD`, paid, and physically delivered (the logistics system having reported a `delivered_at`), the buyer may file a dispute. Filing requires `Invoice.status` to be `PAID`, `Lot.delivered_at` to be non-null, the current logical clock to be at or before `delivered_at` plus the dispute-window duration in seconds, and the filer's `X-User-ID` to equal `Lot.winning_bidder_id` (a non-winner filing produces `ERR_IDENTITY_MISMATCH`). The filing payload supplies `filed_by` (`BIDDER` or `SELLER`; buyer-filed disputes use `BIDDER`), `reason` (1 to 500 characters), `evidence` (an array of items each shaped as `{ url, kind }`), and `claimed_refund_amount_cents` (an integer in the inclusive range from 0 to `Invoice.buyer_total_cents`). On filing, a `Dispute` is created with `status = FILED`, `evidence` is stored, `filer_user_id` snapshots the filer's `X-User-ID`, `filed_at` records the current logical clock value, and the `Lot` transitions from `SOLD` to `DISPUTED`. A filing after the dispute window — defined precisely as `now() > delivered_at + DISPUTE_WINDOW_SECONDS` — is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`.

An `ArbitratorOps` operator picks up a `FILED` dispute by starting review, which moves it to `UNDER_REVIEW`: `arbitrator_user_id` snapshots the operator's `X-User-ID` and `review_started_at` is recorded. Starting review on any other dispute status — already `UNDER_REVIEW`, already terminal — is rejected with `ERR_DISPUTE_INVALID_STATE`. Resolution requires `UNDER_REVIEW` and accepts an `outcome` and an optional `resolution_refund_amount_cents`. The amount rule (priority 14) is exact: when `outcome` is `REFUND`, `resolution_refund_amount_cents` is required, must be strictly greater than 0, and must be at most `Invoice.buyer_total_cents`; when `outcome` is `RELIST` or `DENIED`, the field must be 0 or omitted (any non-zero supplied value produces `ERR_INVALID_REFUND_AMOUNT`, HTTP 422). The dispute's `resolution_outcome` records the chosen outcome and `resolved_at` records the clock value.

The three outcomes drive divergent cascades on the parent `Lot`:

- **`REFUND`** moves the `Dispute` to `RESOLVED_REFUND` and the `Lot` from `DISPUTED` to `REFUNDED` via the refund cascade described in §2.8: the original `Invoice` becomes `REVERSED` with `Invoice.refund_amount_cents` set to the dispute's `resolution_refund_amount_cents`; the `commission_reversal_amount_cents` is computed by the **commission-reversal rule**, which divides `resolution_refund_amount_cents` by `Invoice.buyer_total_cents` to produce a `Decimal` ratio rounded half-up to four decimal places, multiplies the original `seller_commission_cents` by that quantised ratio, and rounds the product half-up to integer cents (the rounding order is fixed — applying any other order produces a different cents value); the seller's `gross_proceeds_cents` and `net_proceeds_cents` are recomputed so that `net_proceeds_cents` is reduced by the freshly computed reversal amount; and the buyer's `Deposit` on the lot is `RELEASED` with `terminal_reason = DISPUTE_REFUND`.
- **`RELIST`** moves the `Dispute` to `RESOLVED_RELIST` and the `Lot` from `DISPUTED` to `RELISTED` (a terminal status). The original `Invoice` becomes `REVERSED` with `refund_amount_cents` set to the full `buyer_total_cents`, and `commission_reversal_amount_cents` set to the original `seller_commission_cents` in full (the ratio is exactly 1.0000, so no rounding is needed). The platform creates a fresh `Lot` in `DRAFT` that copies `title`, `category`, `condition`, `physical_item_serial`, `reserve_price_cents`, and `starting_bid_cents` from the original; the new lot's `relisted_from_lot_id` is set to the original lot's `id`; the new lot's `scheduled_start_at` and `scheduled_end_at` remain null until the seller publishes it. The buyer's `Deposit` on the original lot is `RELEASED` with `terminal_reason = DISPUTE_REFUND`.
- **`DENIED`** moves the `Dispute` to `RESOLVED_DENIED` and the `Lot` back from `DISPUTED` to `SOLD`; the `Invoice` remains `PAID` and no refund is issued. The filer's `dispute_loss_count` is incremented by one and their `risk_score` is recomputed.

### 3.6. Risk, Restriction, and Reinstatement

Every `Bidder` carries a `risk_score` in the closed range from 0 to 100, recomputed whenever any of its inputs change: a bid status flip to `WITHDRAWN_BY_RISK`, a dispute resolution involving the bidder, an account-takeover alert, a payment default, a shill-pattern sweep flag flipping, or a manual reinstatement. The score combines a **chronic** component and an **acute** component.

The chronic component is computed as `withdrawal_count` multiplied by 8.0 plus `dispute_loss_count` multiplied by 12.0, capped at 100.0. The acute component sums three penalties: 30.0 if `shill_pattern_detected` is true, 20.0 if `account_takeover_alert` is true, and 20.0 multiplied by the count of recorded payment defaults since the bidder's last reinstatement. The `risk_score` is the lesser of 100.0 and the sum of the chronic and acute components, stored after rounding half-up to one decimal place. Two thresholds apply: a `risk_score` of at least 70.0 moves the bidder's `status` to `RESTRICTED`, and a `risk_score` of at least 90.0 moves it to `SUSPENDED`. The acute side is what makes the score volatile: after a `PlatformAdmin` reinstatement, the acute side is cleared to zero and the score reverts to the chronic-only reading (which, on its own, can still cross the 70.0 threshold and re-restrict — the chronic count does not reset on reinstate).

A `RESTRICTED` `Bidder` cannot place new bids or create new auto-bid proxies; their existing `ACTIVE` proxies remain on the lot but are blocked from emitting new bids while they are restricted. A `SUSPENDED` `Bidder` triggers the bidder-suspend cascade described in §2.8. The administrator-driven restrictions are exposed as three separate operator capabilities — manually moving a bidder to `RESTRICTED`, manually moving them to `SUSPENDED` (which also runs the cascade), and reinstating them to `ACTIVE` (which clears `acute_score`, recomputes `risk_score` from the chronic side, and clears both `account_takeover_alert` and `shill_pattern_detected`). The system itself moves a bidder to `RESTRICTED` or `SUSPENDED` whenever a recompute crosses the corresponding threshold upward — these are not exclusive to operator action.

Two external risk channels feed the acute score. An identity-system event recording an account-takeover alert flips the bidder's `account_takeover_alert` to true, includes `ACUTE_PENALTY_TAKEOVER` (20.0) in the acute total, recomputes `risk_score`, and may itself cross a threshold and cascade. An abnormal-bid-pattern detection sweep — invoked by the platform — examines the last 30 seconds of system clock for `Bid` records (the velocity window) and flags any bidder who placed strictly more than 3 bids on a single lot within that window: their `shill_pattern_detected` becomes true, the acute total includes `ACUTE_PENALTY_SHILL` (30.0), `risk_score` is recomputed, and the sweep response returns the array of flagged `bidder_id` values. The identity-verification event ingestion does not affect the risk score; it merely flips `Bidder.identity_verified` to true (and does not retroactively recompute past invoices' buyer premiums).

### 3.7. Operator and Test-Driving Capabilities

A `PlatformAdmin` is the only role permitted to register sellers and bidders, and is the sole writer for wallet credit. Seller registration accepts `display_name`, mints a `Seller` with `status = ACTIVE`, and initialises `total_lots_listed`, `gross_proceeds_cents`, and `net_proceeds_cents` to zero. Bidder registration accepts `display_name` and the optional `affiliated_seller_id`, and mints a `Bidder` with `status = ACTIVE`, `identity_verified = false`, `wallet_balance_cents = 0`, `risk_score = 0`, `chronic_score = 0`, `acute_score = 0`, `withdrawal_count = 0`, `dispute_loss_count = 0`, `shill_pattern_detected = false`, and `account_takeover_alert = false`. Wallet credit accepts an `amount_cents` of at least 1 and adds it to the bidder's `wallet_balance_cents`.

Three additional capabilities exist for the test harness and for synchronisation with adjacent systems. The clock-advance capability accepts a `seconds` value and moves the logical clock forward by that many seconds, evaluating every time-gated transition described in §2.9. The payment-confirmed ingestion described in §3.4 accepts `invoice_id` and `paid_at`. The logistics-delivered ingestion accepts `lot_id` and `delivered_at`, recording the delivery timestamp on the lot and opening the dispute window. The identity-verified ingestion accepts `bidder_id` and `verified_at` and flips `Bidder.identity_verified` to true. The account-takeover ingestion accepts `bidder_id` and is described in §3.6. The shill-detection sweep takes no input and is described in §3.6.

`Anonymous` callers may read public lot data (the lot detail, the lot list with its `status`, `category`, and `seller_id` filters and `limit`/`offset` pagination, the per-lot bid list, and the seller record). They may not invoke any mutation, and any mutation attempt resolves to `ERR_ROLE_FORBIDDEN`.

## 4. Endpoint Definitions

All endpoints return JSON bodies following the §2.2 envelope. New resource creation returns HTTP 201; successful modification (including state transitions, cascades, ingestion events, and clock advances) returns HTTP 200. Read endpoints return 200.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/sellers` | Register a `Seller`. | `PlatformAdmin` |
| GET | `/sellers/{sellerId}` | Read a `Seller`. | `PlatformAdmin`, `Seller`, `Bidder`, `ArbitratorOps`, `Anonymous` |
| POST | `/bidders` | Register a `Bidder`. | `PlatformAdmin` |
| GET | `/bidders/{bidderId}` | Read a `Bidder`. | `PlatformAdmin`, `Bidder`, `ArbitratorOps` |
| POST | `/bidders/{bidderId}/wallet/credit` | Credit a bidder's wallet. | `PlatformAdmin` |
| POST | `/bidders/{bidderId}/restrict` | Move a bidder to `RESTRICTED`. | `PlatformAdmin` |
| POST | `/bidders/{bidderId}/suspend` | Move a bidder to `SUSPENDED` and run the bidder-suspend cascade. | `PlatformAdmin` |
| POST | `/bidders/{bidderId}/reinstate` | Restore a bidder to `ACTIVE`. | `PlatformAdmin` |
| POST | `/lots` | Create a `Lot` in `DRAFT`. | `Seller` |
| GET | `/lots/{lotId}` | Read a `Lot`. | `PlatformAdmin`, `Seller`, `Bidder`, `ArbitratorOps`, `Anonymous` |
| GET | `/lots` | List lots filtered by `status`, `category`, and `seller_id`. | `PlatformAdmin`, `Seller`, `Bidder`, `ArbitratorOps`, `Anonymous` |
| POST | `/lots/{lotId}/publish` | Move a `Lot` from `DRAFT` to `SCHEDULED`. | `Seller` |
| POST | `/lots/{lotId}/cancel` | Cancel a `Lot` in `DRAFT` or `SCHEDULED`. | `Seller` |
| POST | `/lots/{lotId}/bids` | Place a manual bid on a `LIVE` `Lot`. | `Bidder` |
| GET | `/lots/{lotId}/bids` | List bids for a `Lot` sorted by `placed_at` descending. | `PlatformAdmin`, `Seller`, `Bidder`, `ArbitratorOps`, `Anonymous` |
| POST | `/lots/{lotId}/auto-bid-proxies` | Create an `AutoBidProxy` on a `LIVE` `Lot`. | `Bidder` |
| GET | `/lots/{lotId}/auto-bid-proxies/{proxyId}` | Read an `AutoBidProxy` (`max_amount_cents` is masked for non-owners). | `PlatformAdmin`, `Bidder`, `ArbitratorOps` |
| POST | `/lots/{lotId}/auto-bid-proxies/{proxyId}/cancel` | Cancel an `ACTIVE` `AutoBidProxy`. | `Bidder` |
| POST | `/lots/{lotId}/winner/default` | Manually move a `SOLD` `Lot` to `DEFAULTED`. | `PlatformAdmin` |
| POST | `/lots/{lotId}/runner-up/accept` | Runner-up accepts the offer on a `REOFFERED` `Lot`. | `Bidder` |
| POST | `/lots/{lotId}/runner-up/decline` | Runner-up declines the offer on a `REOFFERED` `Lot`. | `Bidder` |
| GET | `/lots/{lotId}/invoice` | Read a `Lot`'s `Invoice`. | `PlatformAdmin`, `Seller`, `Bidder`, `ArbitratorOps` |
| POST | `/lots/{lotId}/disputes` | File a dispute on a `SOLD` `Lot` whose `Invoice` is `PAID`. | `Bidder` |
| POST | `/lots/{lotId}/disputes/{disputeId}/start-review` | Move a `Dispute` to `UNDER_REVIEW`. | `ArbitratorOps` |
| POST | `/lots/{lotId}/disputes/{disputeId}/resolve` | Resolve a `Dispute` with `REFUND`, `RELIST`, or `DENIED`. | `ArbitratorOps` |
| POST | `/_clock/advance` | Advance the logical clock by `seconds`. | `PlatformAdmin` |
| POST | `/_events/payment-confirmed` | Ingest a payment-confirmed event. | `PlatformAdmin` |
| POST | `/_events/identity-verified` | Ingest an identity-verified event. | `PlatformAdmin` |
| POST | `/_events/logistics-delivered` | Ingest a logistics-delivered event. | `PlatformAdmin` |
| POST | `/_events/account-takeover-alert` | Ingest an account-takeover alert. | `PlatformAdmin` |
| POST | `/_sweep/risk-monitor` | Run the abnormal-bid-pattern detection sweep. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_IDENTITY_MISMATCH` | 403 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_BIDDER_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_PROXY_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_LOT_NOT_LIVE` | 409 |
| `ERR_BID_INVALID_STATE` | 409 |
| `ERR_PROXY_INVALID_STATE` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_DISPUTE_INVALID_STATE` | 409 |
| `ERR_BIDDER_RESTRICTED` | 403 |
| `ERR_SHILL_AFFILIATION` | 403 |
| `ERR_BID_BELOW_MIN_INCREMENT` | 422 |
| `ERR_BID_NOT_HIGHER` | 409 |
| `ERR_PROXY_MAX_TOO_LOW` | 422 |
| `ERR_PROXY_ALREADY_ACTIVE` | 409 |
| `ERR_INVALID_REFUND_AMOUNT` | 422 |
| `ERR_LOT_DURATION_TOO_SHORT` | 422 |
| `ERR_LOT_START_IN_PAST` | 422 |
| `ERR_PHYSICAL_ITEM_TIME_OVERLAP` | 409 |
| `ERR_RUNNER_UP_WINDOW_EXPIRED` | 409 |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_DEPOSIT_FUNDS` | 402 |
