# Online Auction & Bidding Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Online Auction & Bidding Marketplace API, a platform that brokers transactions between sellers and buyers in the spirit of a large consumer auction site. Sellers list items either as timed auctions, fixed-price "buy now" offerings, or a hybrid of the two; buyers compete through proxy bidding, submit best-offer negotiations, watch listings of interest, and ultimately win, pay for, and receive goods. The platform sits in the middle of every transaction: it resolves competing proxy bids into a single visible price, extends auctions when last-second bidding occurs, charges sellers a tiered final-value fee on each sale, mediates disputes and returns, and tracks the reputation of every participant through buyer-to-seller and seller-to-buyer feedback.

The business challenge the API solves is one of trustworthy, deterministic mediation across many parties whose interests conflict. A bid must be honored exactly as the proxy rules dictate; an auction must not close while genuine competition continues; a seller carrying unpaid platform fees must not be allowed to flood the market with new listings; and money refunded in a dispute must reverse the platform's own fee. Because several of these effects cascade across more than one record — an auction close that mints an order which in turn raises a fee invoice, or a return that refunds a buyer and credits a fee in a single motion — the system must apply each chain immediately and consistently, never leaving a half-finished transaction behind. The sections that follow define the global contracts every endpoint shares, the business rules that govern each lifecycle, and the precise calculations that determine prices, fees, and reputation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request that mutates state or reads a non-public resource must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting account, and the `X-User-Role` header declares the capacity in which that account is acting. The platform recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Buyer`, `Seller`, and `PlatformAdmin`. When a protected endpoint receives a request whose `X-User-Role` or `X-User-ID` header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. When the role is permitted in general but the acting account is not the owner of the specific targeted resource, the request is rejected with `ERR_NOT_OWNER`.

The `Buyer` and `Seller` roles are both entity-backed. When `X-User-Role` is `Buyer`, the `X-User-ID` value is the `id` of the acting `Account`; ownership checks on any resource that references the acting buyer — a `Bid`, an `Offer`, an `Order`, or a `Dispute` — compare the resource's buyer-side foreign key (`bidder_account_id`, `buyer_account_id`, or `opener_account_id`) against `X-User-ID`. When `X-User-Role` is `Seller`, the `X-User-ID` value is likewise the `id` of the acting `Account`; ownership checks on any resource that references the seller — a `Listing`, an `Order`, or a `SellerFeeInvoice` — compare the resource's `seller_account_id` against `X-User-ID`. A single `Account` may carry both the `SELLER` and `BUYER` roles in its `roles` list and therefore act in either capacity, but the two capacities own disjoint sets of resources.

The `Anonymous` role represents an unauthenticated public reader; its `X-User-ID` is an opaque identifier not tied to any persisted entity, and the server does not compare it to any account's `id`. Anonymous callers may register a new account and may read public resources such as listings, bids, account profiles, and feedback. The `PlatformAdmin` role is also opaque: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to an account's `id`; a `PlatformAdmin` operates disputes, settles fee invoices, closes accounts, and drives the logical clock. Separately, any account whose `status` has been set to `CLOSED` is barred from performing any mutation; such an attempt is rejected with `ERR_ACCOUNT_CLOSED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — `Account`, `Listing`, `Bid`, `Offer`, `Order`, `SellerFeeInvoice`, and `Dispute` — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation, including mutations to computed fields. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control.

Three resources are deliberately lighter. A `Watch`, a `Payment`, and a `Feedback` row each carry only an `id` and a `created_at`; they have no `updated_at` and no `version`. A `Watch` is a soft-deletable toggle, a `Payment` is an append-only ledger event, and a `Feedback` is an immutable rating — none of them is ever modified in place after creation, so neither field applies. A `Watch` carries a system-managed `active` flag that is true while watching and is set to false on unwatch (a soft delete rather than a physical removal); at most one active watch may exist for a given pair of `listing_id` and `watcher_account_id`, and watching a listing that already has an inactive watch for that pair reactivates it rather than creating a duplicate.

### 2.5. Hierarchical Consistency and Cascading Effects

Several operations in this marketplace mutate more than one resource in a single, indivisible motion, and the system applies every link of such a chain immediately. When an auction closes with a met reserve, when a buyer purchases at the fixed price, or when a seller accepts an offer, the platform does not merely change the listing's `status` — it mints an `Order` and, from that order, raises a `SellerFeeInvoice`, a depth-three chain that must complete in full. Likewise, reversing a sale propagates downward: cancelling an unpaid order, fully refunding a dispute, or completing a return each credits the order's fee invoice and adjusts the seller's balance. Whenever the server mutates a resource as part of such a cascade — whether the resource is the direct target of the request or a record swept up by the chain — that resource's `updated_at` is refreshed and its `version` is incremented by one, exactly as if it had been modified by a direct request. A computed denormalized pointer such as a listing's `highest_bid_id` or `winner_account_id` is resolved to the underlying record by id and is not an ownership foreign key.

### 2.6. Reverse Lookups and Path Validation

The marketplace is a graph of peer resources linked by foreign key rather than a strict tree, so most relationships are navigated through list endpoints that filter by a foreign-key query parameter. Bids are reached by filtering on `listing_id` or `bidder_account_id`; offers by `listing_id` or `buyer_account_id`; orders by `listing_id`, `buyer_account_id`, or `seller_account_id`; watches by `listing_id` or `watcher_account_id`; feedback by `order_id`, `rater_account_id`, or `ratee_account_id`; seller-fee invoices by `order_id` or `seller_account_id`. The watch listing returns only active watches unless the `include_inactive` flag requests otherwise. When a request carries resource identifiers in its path, the server validates them left to right and rejects the first identifier that does not correspond to an existing resource with `ERR_NOT_FOUND`. This existence check (priority four) runs after authentication, role, and ownership checks but before any state or business rule is evaluated.

### 2.7. Monetary Precision and Rounding

All monetary amounts in the system are represented and stored as integer cents; field names carrying money end in `_cents`. Because amounts are integers, the bid-increment and proxy-resolution arithmetic involve no rounding at all. The only place rounding occurs is in the seller's final-value-fee computation, where intermediate tier products are real-valued: there, the exact tier products are summed first and the single resulting sum is then rounded to a whole number of cents using the round-half-up convention (a fractional half-cent rounds upward). Time-based comparisons operate on whole seconds against UTC timestamps.

### 2.8. The Seller Fee Ledger and Account Standing

Every seller carries a running ledger of what they owe the platform. The `fee_balance_cents` field on an `Account` is the sum of the `amount_cents` of all that seller's `SellerFeeInvoice` records whose `settlement_status` is `INVOICED`; invoices that have moved to `PAID` or `CREDITED` contribute zero to this outstanding balance. This balance is recomputed every time an invoice is created, settled, credited, or otherwise recomputed. From the balance the system derives the account's `standing`: the standing is `GOOD` when `fee_balance_cents` is less than or equal to the suspension threshold of 3000 cents, and `SUSPENDED` when `fee_balance_cents` is strictly greater than 3000 cents. The boundary case where the balance equals exactly 3000 cents keeps the account in `GOOD` standing. A seller's standing gates their ability to publish new listings, as described in the listing lifecycle. The `fee_balance_cents` is a conserved-quantity anchor: it always equals the sum of outstanding invoices and is never edited directly.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Each requires the client to submit the version of the parent resource it last observed, so that a write computed against a stale view is rejected rather than silently overwriting an intervening change.

Countering an offer is one such guarded write. A counter request must carry the field `expected_offer_version`, which the client sets to the `version` of the targeted `Offer` as it last read it. If a counterparty has already advanced the negotiation — legitimately moving the standing amount and bumping the offer's `version` — since the client last read the offer, the submitted `expected_offer_version` will no longer match the offer's current `version`, and the counter is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents the actor from overwriting a move they never saw.

Paying for an order is the second guarded write. A payment request must carry the field `expected_order_version`, set to the `version` of the targeted `Order` as the buyer last read it. If a cascaded side effect — such as the seller cancelling the unpaid order, or a fee recompute — has advanced the order's `version` since the buyer's checkout view was loaded, the submitted `expected_order_version` will not match the order's current `version`, and the payment is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being applied against an obsolete total. No other endpoint accepts or requires a version field.

### 2.10. Validation Ordering

When a single request could fail several checks, the platform evaluates them in a fixed priority order and reports the first failure it encounters. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`). Role permission for the operation comes second (`ERR_FORBIDDEN_ROLE`). Ownership of the targeted resource comes third (`ERR_NOT_OWNER`). Existence of every path- and body-referenced resource comes fourth, validated left to right (`ERR_NOT_FOUND`). The optimistic-concurrency version check comes fifth, on the two guarded writes (`ERR_STALE_VERSION`). Verifying that the target is in a state from which the requested transition is defined comes sixth (`ERR_INVALID_STATE`). Auction-window timing comes seventh (`ERR_AUCTION_CLOSED`). Return and dispute window timing comes eighth (`ERR_WINDOW_EXPIRED`). Self-dealing comes ninth (`ERR_SELF_TRADING`). The seller standing gate comes tenth (`ERR_SELLER_SUSPENDED`). Bid eligibility comes eleventh (`ERR_BID_TOO_LOW`). Offer-amount eligibility comes twelfth (`ERR_OFFER_INVALID`). The offer round cap comes thirteenth (`ERR_OFFER_ROUND_LIMIT`). The bid-retraction lockout comes fourteenth (`ERR_RETRACT_NOT_ALLOWED`). Feedback eligibility comes fifteenth (`ERR_FEEDBACK_NOT_ELIGIBLE`). Dispute eligibility comes sixteenth (`ERR_DISPUTE_NOT_ELIGIBLE`). Generic field-shape validation — required fields present, enums in range, integers meeting their stated constraints — comes last (`ERR_INVALID_REQUEST`). A higher-priority failure always masks a lower-priority one.

## 3. Business Logic & Workflows

### 3.1. Accounts, Reputation, and Account Closure

Anyone may register an `Account` by supplying an `email`, a `display_name`, and a `roles` list. The `email` is the login identifier and must be unique across all accounts and non-empty. The `display_name` is the public name shown on listings and feedback. The `roles` list must be non-empty and may contain `SELLER`, `BUYER`, or both. A freshly registered account starts `ACTIVE` with a `fee_balance_cents` of zero, a `feedback_score` of zero, and `standing` of `GOOD`. An account's public profile, including its `feedback_score` and `standing`, is readable by anyone.

Reputation accrues through feedback left on completed orders. The `feedback_score` of an account is its net reputation: the count of `Feedback` rows where that account is the `ratee_account_id` and the `rating` is `POSITIVE`, minus the count of rows where it is the ratee and the `rating` is `NEGATIVE`. A `NEUTRAL` rating contributes zero. There is no time window — the score is a lifetime tally — and it is recomputed in full from all of the ratee's feedback rows each time a new feedback is created.

A `PlatformAdmin` may close an account, moving its `status` from `ACTIVE` to `CLOSED`. Once an account is `CLOSED` it may still be read but may no longer perform any mutating action, and any attempt to do so is refused with `ERR_ACCOUNT_CLOSED`.

### 3.2. Creating and Publishing Listings

A `Seller` creates a listing in `DRAFT` status by supplying the `seller_account_id` (which must be their own account and must hold the `SELLER` role), a `title`, and a `format`. The format is one of three values. An `AUCTION` accepts bids only. A `BUY_NOW` is a fixed-price item only. A `HYBRID` is an auction that also offers a buy-now price, where the buy-now option disappears once the first bid arrives. For an `AUCTION` or a `HYBRID`, the seller supplies a `start_price_cents` of at least 1 — the opening price — and a `scheduled_end_at`, the UTC close time, which must fall strictly after the listing's `created_at`. The seller may submit `scheduled_end_at` in any valid ISO 8601 form, but the value the system stores and surfaces for it is the system-managed canonical ISO 8601 UTC timestamp with three fractional digits (the same form described in §2.4); the stored value therefore carries three fractional digits regardless of the fractional precision the client supplied. The same canonical three-fractional-digit form applies to the listing's `effective_end_at` whenever it is non-null. A `buy_now_price_cents` is required for both `BUY_NOW` and `HYBRID` and must be null for an `AUCTION`; for a `HYBRID` the buy-now price must be strictly greater than the start price. The `start_price_cents` and `scheduled_end_at` are ignored for a pure `BUY_NOW`. A seller may attach a hidden `reserve_price_cents`; when set it must be at least the `start_price_cents`, it is forbidden on a `BUY_NOW`, and a null value means the listing has no reserve. A seller may also set `accepts_offers` to true (it defaults to false) to allow best-offer negotiation, which is permitted only on `BUY_NOW` and `HYBRID` listings.

Publishing moves a listing from `DRAFT` to `ACTIVE`. The acting seller must own the listing, the seller's account `status` must be `ACTIVE`, and the seller's account `standing` must be `GOOD` — that is, its `fee_balance_cents` must be at most the suspension threshold of 3000 cents. A seller whose standing is `SUSPENDED` is blocked from publishing with `ERR_SELLER_SUSPENDED`. For an `AUCTION` or `HYBRID`, the `scheduled_end_at` must still be strictly after the current clock at publish time. On a successful publish the system sets `effective_end_at` equal to `scheduled_end_at` for an `AUCTION` or `HYBRID` (it remains null for a `BUY_NOW`), sets `current_price_cents` equal to `start_price_cents` for an `AUCTION` or `HYBRID`, and increments the listing's version by one. The `effective_end_at` is the true close time and is initialized to the scheduled end on publish, later pushed forward by anti-sniping extensions; `current_price_cents` is the visible auction price and is null for a pure `BUY_NOW`. A listing also tracks a computed `highest_bid_id` pointer to the current winning bid (null until the first bid), a computed `bid_count` of distinct accepted bids (starting at zero), a computed `winner_account_id`, and a computed `sold_price_cents` that remains null until the listing sells.

A seller may cancel a listing. Cancelling a `DRAFT` listing simply moves it to `CANCELLED`. Cancelling an `ACTIVE` listing is permitted only while its `bid_count` is zero — an auction that has already attracted a bid cannot be cancelled — and when it is cancelled, every `PENDING` or `COUNTERED` offer on that listing is moved to `DECLINED`; existing watches are left in place though the listing is closed. Either cancellation increments the listing's version by one. A transition requested from a state in which it is not defined is refused with `ERR_INVALID_STATE`.

### 3.3. Proxy Bidding and Price Resolution

A `Buyer` places a bid on an `ACTIVE` auction by supplying the `bidder_account_id` and a secret `max_proxy_cents`, the maximum the system is authorized to bid on their behalf. The bidder must hold the `BUYER` role and must not be the listing's seller; a self-bid is refused with `ERR_SELF_TRADING`. A bid placed once the current clock has reached the auction's `effective_end_at`, or on a terminal listing, is refused with `ERR_AUCTION_CLOSED`. Each bid carries a computed `current_price_cents` — the amount it is actually committed to right now, never exceeding its `max_proxy_cents` — and a computed `is_winning` flag that is true for exactly one bid per listing, the one the listing's `highest_bid_id` points at. A bid's `status` is `ACCEPTED` on success, `OUTBID` when superseded, or `RETRACTED` if the bidder retracts it.

Bid eligibility is checked before resolution. The very first bid on a listing must have a `max_proxy_cents` of at least the `start_price_cents`. Every subsequent bid must have a `max_proxy_cents` of at least the listing's current `current_price_cents` plus the minimum increment computed on that current price. A bid that falls short is refused with `ERR_BID_TOO_LOW`.

The minimum bid increment is a step function of the price it is measured against. For a price below 100 dollars (10000 cents) the increment is 1 dollar (100 cents). For a price from 100 dollars up to but not including 500 dollars (50000 cents) the increment is 5 dollars (500 cents). For a price from 500 dollars up to but not including 1000 dollars (100000 cents) the increment is 10 dollars (1000 cents). For a price of 1000 dollars or more the increment is 25 dollars (2500 cents). Each tier boundary belongs to the higher tier because the comparison is lower-edge inclusive: a price of exactly 50000 cents takes the 1000-cent increment, while 49999 cents takes the 500-cent increment.

When a bid is accepted, the proxy-resolution rule recomputes the standing price and winner, working chronologically. Let the incoming bid be the new bid with secret maximum `max_proxy_cents`, and let the previous winner — the bid the `highest_bid_id` currently points at — have its own secret maximum and its committed `current_price_cents`. If the incoming bid is the first bid on the listing, it becomes the winner and its `current_price_cents` is set to the `start_price_cents`. If the incoming bid's maximum is strictly greater than the previous winner's maximum, the incoming bid takes the lead: its `current_price_cents` becomes the smaller of its own maximum and the previous winner's maximum plus one increment computed on that previous maximum, the previous winner keeps its committed price but is marked `OUTBID` with its `is_winning` set to false. If the incoming bid's maximum is less than or equal to the previous winner's maximum, the incumbent holds: the previous winner stays the winner and its `current_price_cents` becomes the smaller of its own maximum and the incoming maximum plus one increment computed on the incoming maximum, while the incoming bid is recorded at its own maximum, marked `OUTBID`, with `is_winning` false. When the two maximums are exactly equal, the incumbent retains the lead by virtue of its earlier `created_at`, and the price is set to the shared maximum; the incoming bid is recorded `OUTBID` at its maximum. In every case the listing's `current_price_cents` becomes the winner's `current_price_cents`, the `highest_bid_id` points at the winner, the `bid_count` increases by one for each accepted bid, and the listing's version is incremented by one. Only `ACCEPTED` bids participate in winner selection; `OUTBID` and `RETRACTED` bids are excluded.

A bidder may retract a bid, but only outside the lockout window and only if the bid is not currently winning. Retraction is allowed only when the current time is more than the lockout interval of 12 hours (43200 seconds) before the auction's `effective_end_at`; a retraction attempted inside that final 12-hour window, or against a bid that is currently winning, is refused with `ERR_RETRACT_NOT_ALLOWED`. A successful retraction marks the bid `RETRACTED`, re-runs the proxy resolution over the remaining `ACCEPTED` bids, and increments the listing's version by one.

### 3.4. Anti-Sniping Auction Extension

To discourage last-second bidding, an accepted bid placed close to the close pushes the auction's end time forward. At the moment a qualifying bid is accepted, the system measures the seconds remaining as the difference between `effective_end_at` and the current clock. If that remaining time is at most the soft-close trigger of 5 minutes (300 seconds) and is still greater than zero, the system sets `effective_end_at` to the current clock plus the extension of 5 minutes (300 seconds); otherwise the end time is left unchanged. The boundary is inclusive: when exactly 300 seconds remain the extension fires, but when 301 seconds remain it does not. Each qualifying bid resets the window from the current clock — the new end is always the current clock plus 300 seconds, never a running sum, so successive late bids do not stack their extensions.

### 3.5. The Best-Offer Negotiation Loop

When a listing has `accepts_offers` set to true, a `Buyer` may open a negotiation by submitting an offer with a `buyer_account_id` and an `amount_cents`. The offer amount must be at least 1 cent and strictly less than the listing's `buy_now_price_cents`, and the listing must in fact accept offers; an amount out of range, a listing that does not accept offers, or a counter against a listing that does not support offers is refused with `ERR_OFFER_INVALID`. The buyer must hold the `BUYER` role and must not be the seller, or the submission is refused with `ERR_SELF_TRADING`, and an offer on a closed or terminal listing is refused with `ERR_AUCTION_CLOSED`. A new offer begins in `PENDING` status with `round_no` of 1 and `last_actor` of `BUYER`; `round_no` is the negotiation round counter and `last_actor` records who set the currently standing amount.

The negotiation proceeds as a bounded back-and-forth. Either party may counter, which moves a `PENDING` offer to `COUNTERED` or keeps an already `COUNTERED` offer in `COUNTERED`. A seller may counter only when the `last_actor` is `BUYER`; a buyer may counter only when the `last_actor` is `SELLER`. Each counter sets the offer's `amount_cents` to the new counter amount — which on a seller counter becomes the seller's asking amount — flips the `last_actor` to the party who just acted, increments `round_no` by one, and increments the offer's version by one. The loop is bounded: once `round_no` reaches the cap of 5 rounds, a further counter is refused with `ERR_OFFER_ROUND_LIMIT` (a counter is rejected when `round_no` is 5 or more). A counter is an optimistic-concurrency-guarded write requiring the `expected_offer_version` field as described in the concurrency section. A counter is also subject to the same offer-amount eligibility as the original offer.

A negotiation can end in several ways. Accepting the standing offer concludes the deal: a `PENDING` or `COUNTERED` offer is accepted by the party who did not set the standing amount — the seller accepts when `last_actor` is `BUYER`, the buyer accepts when `last_actor` is `SELLER` — moving the offer to `ACCEPTED`. Acceptance cascades into the sale of the listing, as described below. Declining moves a `PENDING` offer (declined by the seller who owns the listing) or a `COUNTERED` offer (declined by whichever party did not make the standing amount) to `DECLINED`. A buyer may withdraw their own `PENDING` offer when the `last_actor` is still `BUYER`, moving it to `WITHDRAWN`. Each of accept, decline, and withdraw increments the offer's version by one. Finally, an offer left untended expires automatically: a `PENDING` offer expires once the current clock reaches its `created_at` plus the offer time-to-live of 24 hours (86400 seconds), and a `COUNTERED` offer expires once the current clock reaches its `updated_at` plus that same 24-hour interval. Expiry moves the offer to `EXPIRED` and increments its version by one. A transition requested from a state in which it is undefined is refused with `ERR_INVALID_STATE`.

### 3.6. Closing a Sale: How a Listing Becomes an Order

A listing reaches a sale through one of four paths, and three of them converge on the same downstream cascade: an `Order` is minted and, from it, a `SellerFeeInvoice` is raised.

The first path is an auction that runs to its close. When the clock is advanced to or past a listing's `effective_end_at`, the system closes the auction. If the auction has at least one bid and either has no reserve or the highest bid's committed price is at least the `reserve_price_cents`, the listing moves through `ENDED_MET` — a transient bridge state — setting `winner_account_id` to the winning bid's `bidder_account_id` and `sold_price_cents` to the winning bid's `current_price_cents`, then cascading to create an `Order` with `source` of `AUCTION_WIN` whose `item_price_cents` is the sold price, which in turn cascades a seller fee invoice; once that order exists the listing continues to `SOLD`. If the auction has at least one bid but carries a non-null reserve that the highest bid's committed price fails to reach, the listing moves to `ENDED_RESERVE_NOT_MET` with no winner and no order. If the auction has zero bids at close, it moves to `ENDED_NO_BIDS`. Each of these closes increments the listing's version by one.

The second path is an instant fixed-price purchase. A `Buyer` may buy now on a `BUY_NOW` or `HYBRID` listing by supplying their `buyer_account_id` and an optional `shipping_cents`. For a `HYBRID` the buy-now option is available only while `bid_count` is zero — it disappears after the first bid. The buyer must hold the `BUYER` role, must not be the seller, and must have an `ACTIVE` account `status`. The listing moves to `SOLD` with `winner_account_id` set to the buyer and `sold_price_cents` set to the `buy_now_price_cents`, cascading an `Order` with `source` of `BUY_NOW` and then a seller fee invoice; the listing's version increments by one.

The third path is offer acceptance. When the standing offer on a listing is accepted, the listing — provided it is still `ACTIVE` and `accepts_offers` is true — moves to `SOLD` with `winner_account_id` set to the offer's buyer and `sold_price_cents` set to the offer's `amount_cents`; the accepted offer moves to `ACCEPTED`, an `Order` with `source` of `OFFER_ACCEPT` is created and cascades a seller fee invoice, and every other `PENDING` or `COUNTERED` offer on the same listing is moved to `DECLINED`. The listing's version increments by one. An optional `shipping_cents` may accompany the acceptance.

Every minted order copies the `listing_id`, sets `buyer_account_id` to the winning buyer, copies `seller_account_id` from the listing's seller, records the `source`, and snapshots the agreed `item_price_cents` (the winning bid amount, the buy-now price, or the accepted offer amount, respectively). The order's `shipping_cents` is the shipping charge entered at checkout and defaults to 0. The order's `total_cents` is computed as the sum of `item_price_cents` and `shipping_cents`. A new order starts with `payment_status` of `UNPAID`, `fulfillment_status` of `AWAITING_PAYMENT`, and `paid_amount_cents` of 0.

### 3.7. The Seller Fee Invoice

Each order creation cascades exactly one `SellerFeeInvoice` against the order's seller. The invoice records the `order_id`, the `seller_account_id`, a snapshot of the order's `item_price_cents` as its `gross_item_cents`, a snapshot of the applied final-value-fee rate in basis points as `fvf_rate_basis_points` (a display-only audit figure: the effective blended rate times ten thousand, rounded), and the computed `amount_cents` — the fee owed. The invoice's `settlement_status` is `INVOICED` when raised.

The fee owed is a marginal tiered final-value fee on the gross item amount, plus a flat insertion fee, then capped. The gross is sliced into three tiers, each slice taxed at its own basis-point rate. The slice from 0 up to 25000 cents is charged at 1255 basis points (12.55 percent). The slice from 25000 cents up to 75000 cents is charged at 925 basis points (9.25 percent). Any portion above 75000 cents is charged at 255 basis points (2.55 percent). For each tier, the exact product of that tier's slice in cents and its rate divided by ten thousand is computed; the rounding order is pinned to sum-then-round, meaning all of the exact tier products are summed first and only the resulting total is rounded half-up to a whole number of cents — never rounded tier by tier. The flat insertion fee of 30 cents is then added to that rounded value. Finally the total is capped: the fee owed is the smaller of the computed total and the fee cap of 75000 cents. This computed amount is stored as the invoice's `amount_cents`.

A `PlatformAdmin` may settle an outstanding invoice, moving its `settlement_status` from `INVOICED` to `PAID`. Settling recomputes the seller's `fee_balance_cents` (the now-paid invoice contributes zero) and the seller's `standing`, and increments the invoice's version by one. Separately, the system credits an invoice — moving `settlement_status` from `INVOICED` to `CREDITED` — whenever the underlying sale is unwound: when the order is cancelled before payment, when its payment is fully refunded, or when a return is completed. Crediting likewise recomputes the seller's `fee_balance_cents` (the credited invoice contributes zero) and `standing`, and increments the invoice's version by one. On a partial refund the invoice is not credited; instead its `amount_cents` is recomputed against the reduced gross and the seller's balance and standing are recomputed accordingly.

### 3.8. Payment and Fulfillment of an Order

An order advances along two independent dimensions that evolve separately on the same record: a payment dimension and a fulfillment dimension.

Payment begins with the buyer. The buyer who owns the order pays the order total while its `payment_status` is `UNPAID`. This is an optimistic-concurrency-guarded write requiring the `expected_order_version` field to match the order's current version, as described in the concurrency section. Paying appends a `Payment` event of `kind` `CHARGE` whose `amount_cents` equals the order's `total_cents`, sets `paid_amount_cents` to `total_cents`, moves `payment_status` to `PAID`, and — bubbling across into the fulfillment dimension — moves `fulfillment_status` from `AWAITING_PAYMENT` to `READY_TO_SHIP`. The order's version increments by one. The `paid_amount_cents` field is the running sum of all `CHARGE` event amounts minus all `REFUND` event amounts and is a conserved-quantity anchor for the refund invariant. Each `Payment` is an append-only event whose `amount_cents` is at least 1 cent; a `CHARGE` adds to and a `REFUND` subtracts from `paid_amount_cents`.

Fulfillment then proceeds. A seller marks the order shipped, which is permitted only when the `payment_status` is `PAID` and the `fulfillment_status` is `READY_TO_SHIP`; shipping moves `fulfillment_status` to `SHIPPED` and increments the order's version by one. The buyer then confirms delivery while the `fulfillment_status` is `SHIPPED`, moving it to `DELIVERED` and recording the delivery time, incrementing the order's version by one. The acting buyer must be the order's buyer and the acting seller must be the order's seller for their respective steps.

A seller may cancel an order only while it is unpaid — that is, while `payment_status` is `UNPAID` and `fulfillment_status` is `AWAITING_PAYMENT`. Cancellation moves `fulfillment_status` to `CANCELLED`, credits the order's seller fee invoice (no sale occurred, so the fee is reversed), and cancels the originating listing if it is not already terminal. A listing is terminal in any of the states `ENDED_MET`, `ENDED_RESERVE_NOT_MET`, `ENDED_NO_BIDS`, `SOLD`, and `CANCELLED`; only the `DRAFT` and `ACTIVE` states are non-terminal. Because a sold listing is already terminal (its status is `SOLD`), cancelling an order whose listing has reached `SOLD` leaves that listing in `SOLD` rather than transitioning it to `CANCELLED`. The order's version increments by one. Because cancellation advances the order's version, a buyer who attempts to pay against a now-cancelled order with a stale `expected_order_version` is correctly rejected by the concurrency check.

### 3.9. Returns

After delivery, a seller may complete a return, but only inside the return window. Completing a return is permitted only while the `fulfillment_status` is `DELIVERED` and the current clock is at most the return window of 14 days (1209600 seconds) past the time the order reached `DELIVERED`; a return completed after that window is refused with `ERR_WINDOW_EXPIRED`. A completed return moves `fulfillment_status` to `RETURNED` and cascades a full refund: the `payment_status` moves to `REFUNDED` with the full `paid_amount_cents` returned, and the order's seller fee invoice is credited. The order's version increments by one. The mechanics of the full refund itself — appending the refund payment event and zeroing the balance — follow the refund rules described next.

### 3.10. Disputes and Refunds

A `Buyer` may open a dispute on an order, but only when the order has been paid. Opening a dispute requires the order's `payment_status` to be `PAID`, requires the `requested_amount_cents` to be at least 1 and at most the order's `paid_amount_cents`, and allows only one `OPEN` dispute per order; a violation of any of these is refused with `ERR_DISPUTE_NOT_ELIGIBLE`. The buyer supplies the `opener_account_id` (their own account), a `reason` of `ITEM_NOT_RECEIVED`, `NOT_AS_DESCRIBED`, or `DAMAGED`, and the `requested_amount_cents`. A new dispute starts in `OPEN` status, with `resolved_amount_cents` of 0.

From `OPEN`, two paths diverge. The seller — who must be the order's seller — may respond, moving the dispute to `SELLER_RESPONDED` (an optional `message` may accompany the response). Alternatively the buyer who opened the dispute may escalate it to the platform, but a buyer may escalate an `OPEN` dispute only after the seller-response window of 72 hours (259200 seconds) has elapsed since the dispute's `created_at`; an escalation attempted before that interval has passed is refused with `ERR_WINDOW_EXPIRED`. Each of these transitions increments the dispute's version by one. After the seller has responded, the buyer may either escalate the `SELLER_RESPONDED` dispute to the platform (no waiting period applies once the seller has responded) or close it, accepting the seller's response and moving it to `CLOSED`.

Only the platform resolves an escalated dispute. A `PlatformAdmin` resolves an `ESCALATED` dispute by supplying an `approved_amount_cents`. The approved amount must not exceed the order's `paid_amount_cents`; an approved amount greater than the paid amount is refused with `ERR_REFUND_EXCEEDS_PAID`. If the approved amount is greater than zero, the dispute moves to `RESOLVED_REFUND`, its `resolved_amount_cents` is set to the approved amount, and a refund cascade fires (the depth-three chain from dispute to order payment to fee invoice). If the approved amount is exactly zero, the dispute moves to `RESOLVED_NO_REFUND`, its `resolved_amount_cents` stays 0, and the order's payment and the seller's fee invoice are left untouched. Either resolution increments the dispute's version by one.

The refund cascade itself depends on whether the refund is full or partial, measured against the order's current `paid_amount_cents`. A full refund — where the refunded amount equals the order's `paid_amount_cents` — appends a `Payment` event of `kind` `REFUND` for the full prior paid amount, sets `paid_amount_cents` to 0 (preserving the conserved-quantity invariant), moves `payment_status` to `REFUNDED`, and credits the order's seller fee invoice. A partial refund — where the refunded amount is greater than zero but strictly less than the order's `paid_amount_cents` — appends a `REFUND` payment event for the refunded amount, subtracts that amount from `paid_amount_cents`, moves `payment_status` to `PARTIALLY_REFUNDED`, and recomputes the seller fee invoice's `amount_cents` against the reduced gross (the fee is adjusted on the smaller base, not fully credited). Each refund increments the order's version by one.

### 3.11. Feedback on Completed Orders

Once an order has run its course, each party may rate the other. Feedback may be left only when the order's `fulfillment_status` is `DELIVERED` or `RETURNED`, the rater must be either the buyer or the seller of the order, and there may be at most one feedback per order per role; a violation is refused with `ERR_FEEDBACK_NOT_ELIGIBLE`. The rater supplies the `rater_account_id`, a `rating` of `POSITIVE`, `NEUTRAL`, or `NEGATIVE`, and an optional `comment` (which defaults to an empty string). The system pins the feedback's `role` from the order: it is `BUYER` when the rater is the order's buyer rating the seller, and `SELLER` when the rater is the order's seller rating the buyer. It also fixes the `ratee_account_id` to the rater's counterparty on the order. Creating a feedback recomputes the ratee account's `feedback_score` as described in the accounts section. The uniqueness constraint is on the pair of `order_id` and `role`.

### 3.12. The Logical Clock and Timed Events

Because auctions close, offers expire, and windows lapse on the passage of time, the platform exposes an administrative test-driving capability over a logical UTC clock. A `PlatformAdmin` may set the clock to an absolute timestamp by supplying a `to_iso8601` value, and may advance the clock to a supplied `to_iso8601` instant, which fires all timers that have come due. Advancing the clock closes every auction whose `effective_end_at` has been reached — cascading orders and fee invoices for the ones that sold, and routing the others to `ENDED_RESERVE_NOT_MET` or `ENDED_NO_BIDS` as their bid and reserve conditions dictate — and expires every offer whose time-to-live has elapsed. These clock controls are restricted to the `PlatformAdmin` role.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, including state transitions and soft deletes, return a `200 OK` status code. The two clock endpoints return `200 OK`. Each endpoint's request payload and the resources it mutates are described in the business-logic narratives of §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/accounts` | Register an account (buyer/seller/both) | Anonymous |
| GET    | `/accounts/{id}` | Fetch an account profile | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/accounts/{id}/feedback` | List feedback received by an account | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/accounts/{id}/invoices` | List a seller's fee invoices | Seller, PlatformAdmin |
| POST   | `/accounts/{id}/close` | Close an account | PlatformAdmin |
| POST   | `/listings` | Create a DRAFT listing | Seller |
| GET    | `/listings/{id}` | Fetch a listing with computed prices | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/listings` | List listings (filterable by seller, status) | Anonymous, Buyer, Seller, PlatformAdmin |
| POST   | `/listings/{id}/publish` | Publish a listing | Seller |
| POST   | `/listings/{id}/cancel` | Cancel a draft or bid-free listing | Seller |
| POST   | `/listings/{id}/buy-now` | Instant fixed-price purchase | Buyer |
| POST   | `/listings/{id}/bids` | Place a proxy bid | Buyer |
| GET    | `/bids/{id}` | Fetch a bid | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/bids` | List bids (filterable by listing, bidder) | Anonymous, Buyer, Seller, PlatformAdmin |
| POST   | `/bids/{id}/retract` | Retract a non-winning bid | Buyer |
| POST   | `/listings/{id}/watch` | Watch a listing | Buyer, Seller |
| GET    | `/watches/{id}` | Fetch a watch | Buyer, Seller, PlatformAdmin |
| DELETE | `/watches/{id}` | Unwatch (soft delete) | Buyer, Seller |
| GET    | `/watches` | List watches (filterable by listing, watcher) | Buyer, Seller, PlatformAdmin |
| POST   | `/listings/{id}/offers` | Submit a buyer offer | Buyer |
| GET    | `/offers/{id}` | Fetch an offer | Buyer, Seller, PlatformAdmin |
| GET    | `/offers` | List offers (filterable by listing, buyer) | Buyer, Seller, PlatformAdmin |
| POST   | `/offers/{id}/counter` | Counter an offer (OCC-guarded) | Buyer, Seller |
| POST   | `/offers/{id}/accept` | Accept the standing offer | Buyer, Seller |
| POST   | `/offers/{id}/decline` | Decline the standing offer | Buyer, Seller |
| POST   | `/offers/{id}/withdraw` | Withdraw a pending offer | Buyer |
| GET    | `/orders/{id}` | Fetch an order with totals and statuses | Buyer, Seller, PlatformAdmin |
| GET    | `/orders` | List orders (filterable by listing, buyer, seller) | Buyer, Seller, PlatformAdmin |
| POST   | `/orders/{id}/pay` | Pay the order total (OCC-guarded) | Buyer |
| POST   | `/orders/{id}/ship` | Mark an order shipped | Seller |
| POST   | `/orders/{id}/deliver` | Confirm delivery | Buyer |
| POST   | `/orders/{id}/cancel` | Cancel an unpaid order | Seller |
| POST   | `/orders/{id}/complete-return` | Complete a return after delivery | Seller |
| GET    | `/orders/{id}/invoice` | Fetch the seller-fee invoice for an order | Seller, PlatformAdmin |
| GET    | `/orders/{id}/payments` | List payment events for an order | Buyer, Seller, PlatformAdmin |
| GET    | `/seller-fee-invoices/{id}` | Fetch a seller-fee invoice | Seller, PlatformAdmin |
| GET    | `/seller-fee-invoices` | List invoices (filterable by order, seller) | Seller, PlatformAdmin |
| POST   | `/seller-fee-invoices/{id}/settle` | Settle an outstanding invoice | PlatformAdmin |
| POST   | `/orders/{id}/feedback` | Leave feedback on an order | Buyer, Seller |
| GET    | `/orders/{id}/feedback-entries` | List feedback rows tied to an order | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/feedback/{id}` | Fetch a feedback row | Anonymous, Buyer, Seller, PlatformAdmin |
| GET    | `/feedback` | List feedback (filterable by order, rater, ratee) | Anonymous, Buyer, Seller, PlatformAdmin |
| POST   | `/orders/{id}/disputes` | Open a dispute on a paid order | Buyer |
| GET    | `/disputes/{id}` | Fetch a dispute | Buyer, Seller, PlatformAdmin |
| GET    | `/disputes` | List disputes (filterable by order, opener) | Buyer, Seller, PlatformAdmin |
| POST   | `/disputes/{id}/respond` | Seller responds to a dispute | Seller |
| POST   | `/disputes/{id}/escalate` | Buyer escalates a dispute | Buyer |
| POST   | `/disputes/{id}/close` | Buyer closes a dispute | Buyer |
| POST   | `/disputes/{id}/resolve` | Admin resolves an escalated dispute | PlatformAdmin |
| POST   | `/_clock/set` | Set the system clock | PlatformAdmin |
| POST   | `/_clock/advance` | Advance the clock and fire due timers | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AUCTION_CLOSED` | 409 |
| `ERR_WINDOW_EXPIRED` | 409 |
| `ERR_SELF_TRADING` | 422 |
| `ERR_SELLER_SUSPENDED` | 422 |
| `ERR_BID_TOO_LOW` | 422 |
| `ERR_OFFER_INVALID` | 422 |
| `ERR_OFFER_ROUND_LIMIT` | 422 |
| `ERR_RETRACT_NOT_ALLOWED` | 422 |
| `ERR_FEEDBACK_NOT_ELIGIBLE` | 422 |
| `ERR_DISPUTE_NOT_ELIGIBLE` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REFUND_EXCEEDS_PAID` | 422 |
| `ERR_ACCOUNT_CLOSED` | 403 |
