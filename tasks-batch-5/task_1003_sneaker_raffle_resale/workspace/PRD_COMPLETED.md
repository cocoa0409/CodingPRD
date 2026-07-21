# Sneaker Raffle Resale API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Sneaker Raffle Resale API, a marketplace platform in the spirit of StockX and GOAT that unifies two very different economic mechanics under one contract. On one side sits a **primary drop** business: limited-release sneakers are offered through a fairness-weighted raffle in which far more entrants compete than there are pairs to allocate, and the platform must arbitrate that scarcity while actively resisting bot-driven and duplicate entries. On the other side sits a **secondary resale** business: authenticated sellers list pairs at a fixed ask or expose them to buyer bids, physical items are shipped in for condition and box grading before they ever reach a buyer, and money moves through a tiered commission and payout ledger that must reconcile provisional estimates against final settled amounts.

The two halves are deliberately intertwined. A raffle win becomes an order, a resale match becomes an order, and every order eventually threads through payment capture, seller payout, reputation recomputation, and — when something goes wrong — a dispute and clawback. The platform therefore behaves as both a quota allocator and a pricing engine simultaneously, and the rules below describe how release scheduling, raffle draws, consignment authentication, bid-ask matching, buyer verification, and dispute resolution compose into a single consistent system. Because the platform operates on a controlled logical clock rather than wall-clock time, every time-sensitive rule — entry windows, purchase windows, cooldowns, dispute deadlines, and trailing-24-hour limits — is evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as `Buyer`, `Seller`, `Authenticator`, `PlatformAdmin`, and `CustomerService`.

- A `Buyer` enters raffles, claims wins, places bids, buys listings, verifies received orders, and files disputes.
- A `Seller` creates and reprices listings, matches listings to buyer bids, and ships sold items in for authentication.
- An `Authenticator` receives physical items, schedules inspection slots, and records inspection verdicts and grades.
- A `PlatformAdmin` is the operator role that manages accounts, SKUs, authenticators, releases, the entire draw lifecycle, order shipment, and the logical clock.
- A `CustomerService` agent resolves disputes.

Identity binding differs by role, and this binding is what ties `X-User-ID` to resource ownership. When `X-User-Role` is `Buyer` or `Seller`, `X-User-ID` is the `id` of the acting `Account`; ownership checks compare the relevant account foreign key on the target resource (for example a listing's `seller_account_id` or a bid's `buyer_account_id`) against `X-User-ID`, and a mismatch on an ownership-restricted operation is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Authenticator`, `X-User-ID` is the `id` of the acting `Authenticator` entity. When `X-User-Role` is `PlatformAdmin` or `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before collection begins and defaults to 0. A supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100; a supplied `offset` below 0 is clamped up to 0; and a `limit` or `offset` that is absent, blank, or not parseable as an integer falls back to its default.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — `Account`, `Sku`, `Release`, `RaffleEntry`, `Authenticator`, `ConsignmentItem`, `Listing`, `Bid`, `Order`, and `Dispute` — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC value with three fractional digits. All ten of these entities are fully mutable and additionally carry an `updated_at` timestamp (an ISO 8601 UTC value refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on each mutation. Whenever any of a resource's fields change — including system-computed fields such as counters, statuses, ledger balances, or derived scores — that resource's `updated_at` is refreshed and its `version` is incremented. There are no immutable entities in this system; each of the ten entity types exposes all four common fields.

The platform runs on a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until an operator explicitly advances it, every time comparison uses that default; the server never falls back to real-world time. An operator may set the clock to a supplied `to_iso8601` instant, and all subsequent time-based rules — entry and purchase windows, release cooldowns, account tenure, trailing-24-hour purchase counts, and dispute deadlines — are evaluated against the current logical clock value.

### 2.5. Monetary Values, Scores, and Precision

All monetary amounts in the system are stored and returned as **integer cents**; there are no fractional cents. Where a calculation multiplies a cent amount by a rate and therefore produces a non-integer intermediate value, that value is rounded to a whole number of cents using the **round half up** convention (a value ending in exactly one-half cent rounds away from zero to the next whole cent). Reputation and grading scores are the only non-integer stored values: `trust_score` is a number in the inclusive range from 0.0 to 1.0, and the two grade scores and the fairness score are rounded to **four decimal places**, again using round half up on the summed total. Each calculation section in §3 states its own rounding boundary explicitly; where a formula composes several rounded sub-results, the order of rounding is pinned and must be followed exactly, because rounding an intermediate before combining it produces a different result than rounding the combination.

### 2.6. Optimistic Concurrency Control on Repricing

A `Listing` remains repriceable for as long as it is `ACTIVE`, which means a naive reprice would always succeed and could silently overwrite a price change the seller never observed. To prevent that lost update, repricing is guarded by optimistic concurrency control on the listing's `version`. A reprice request must carry `expected_listing_version` as a required field holding the `version` the seller last read for that listing. If `expected_listing_version` does not equal the listing's current `version`, the reprice is rejected with `ERR_STALE_VERSION` and HTTP status 412, because the listing has been superseded since the seller last observed it. Repricing is not the only operation guarded by an expected-version field: the draw (via `expected_release_version` against the release's `version`) and the listing-match (via `expected_listing_version` against the listing's `version`) also require a client-supplied expected-version field and likewise reject a mismatch with `ERR_STALE_VERSION` (412); no other endpoint accepts or requires one.

### 2.7. Parallel Status Axes and Cross-Entity Cascades

An `Order` is unusual in that it tracks **two independent status dimensions on the same row**: a `payment_status` axis and a `fulfillment_status` axis. These advance separately. A fulfillment event does not by itself move the payment axis, and a payment event does not by itself move the fulfillment axis, except where a rule in §3 explicitly couples them. Readers must not assume that advancing one axis implies anything about the other.

Many operations mutate more than one entity at once, and every such cascade must complete as part of the triggering operation. When a physical item is received, its linked order's fulfillment advances. When an inspection passes or fails, both the item and its order change, and a failure additionally penalizes the seller's account. When a buyer verifies an order, the seller's ledger balance, completed-sales counter, and seller level all recompute in sequence (the trust score has no defined recompute formula in this system and is therefore left unchanged). When a dispute is refunded, that same chain reverses. These secondary effects are as much a part of the operation's contract as the primary state change; §3 enumerates each cascade in full, and none of them may be omitted or deferred.

### 2.8. Validation Ordering and Existence Resolution

For any request, checks are applied in a fixed precedence so that the returned error is deterministic. Authentication is evaluated first: absent or malformed headers yield `ERR_UNAUTHENTICATED` (401). Authorization is evaluated next: a role not permitted for the operation yields `ERR_UNAUTHORIZED` (403). Existence of referenced resources is resolved third, and where a request names several resources the checks proceed in resource order, each with its own dedicated code: a missing account yields `ERR_ACCOUNT_NOT_FOUND`, a missing SKU yields `ERR_SKU_NOT_FOUND`, a missing release yields `ERR_RELEASE_NOT_FOUND`, a missing raffle entry yields `ERR_RAFFLE_ENTRY_NOT_FOUND`, a missing consignment item yields `ERR_CONSIGNMENT_NOT_FOUND`, a missing authenticator yields `ERR_AUTHENTICATOR_NOT_FOUND`, a missing listing yields `ERR_LISTING_NOT_FOUND`, a missing bid yields `ERR_BID_NOT_FOUND`, a missing order yields `ERR_ORDER_NOT_FOUND`, and a missing dispute yields `ERR_DISPUTE_NOT_FOUND` — all HTTP 404.

Only after existence is confirmed does the system validate the request body's shape: a missing required field, an invalid enum value, a non-positive integer where a positive value is required, or a time window whose start is not strictly before its end all yield `ERR_VALIDATION` (422). After body validation come the optimistic-concurrency check (`ERR_STALE_VERSION`, 412) where applicable, then state and status checks (HTTP 409), then business-safety checks such as account verification and self-dealing (HTTP 403), then temporal-window checks, referential checks, quota constraints, and finally fiscal checks. In every case the earliest failing check in this ladder is the one reported. The specific trigger condition for each of these business errors lives with the workflow it guards in §3.

### 2.9. Unit Conservation Across a Release

A `Release` maintains a strict inventory identity at all times. Its `available_units` is always exactly its `allocated_quantity` minus its `reserved_units` minus its `sold_units`; this equality is an invariant that every release-affecting operation must preserve. Units move between the reserved and sold pools as winners claim, and freed units return to the available pool when unclaimed reservations expire at settlement, but the three pools together always sum back to the original allocation. Any operation that touches these counters must adjust them so the identity continues to hold.

## 3. Business Logic & Workflows

### 3.1. Catalog, Accounts, and Authentication Centers

The operator seeds the catalog before any commerce occurs. A `PlatformAdmin` onboards an `Account` by supplying an `email` (unique contact address) and a `full_name` (the holder's legal name, used later for buyer verification). A freshly created account begins life with `verification_status` of `UNVERIFIED`, a `trust_score` of 0.5, a `completed_sales_count` of 0, a `seller_level` of `STANDARD`, a `balance_cents` payout ledger of 0, and a `strikes` counter of 0. Buyer and seller participation in the marketplace is gated on verification: an operator later marks an account's `verification_status` as `VERIFIED` once know-your-customer review passes, and only then may that account enter raffles, buy, or match.

A `Sku` describes a shoe model and is created with a `style_code` (the manufacturer style code), a display `name`, a `brand`, and a `retail_price_cents` MSRP that must be greater than zero. Its `release_category` is either `LIMITED`, meaning the model is drop-and-raffle gated, or `GENERAL`, meaning it is openly tradable; when omitted at creation the category defaults to `GENERAL`.

An `Authenticator` represents an authentication center or staff member, created with a `name`, a `location_code` facility identifier, and an optional `daily_capacity` — an informational ceiling on inspections per day that must be at least 1 and defaults to 8 when omitted. Accounts, SKUs, and authenticators are all readable by every role; creation of any of them is reserved to the operator.

### 3.2. Scheduling a Drop and Opening the Entry Window

A `PlatformAdmin` schedules a drop by creating a `Release` against a `sku_id`, declaring an `allocated_quantity` of at least one pair, a `release_price_cents` (the fixed price a winner pays, greater than zero), and four window timestamps: `entry_opens_at` and `entry_closes_at` bound the raffle entry window, while `purchase_opens_at` and `purchase_closes_at` bound the later claim window. The entry window is inclusive of its open instant and exclusive of its close; the same half-open convention applies to the purchase window. A new release must not crowd another drop of the same SKU: the interval spanning from its `entry_opens_at` through its `purchase_closes_at` must stay at least 24 hours clear of the corresponding span of any non-cancelled release of that same SKU, and a violation is rejected with `ERR_RELEASE_WINDOW_OVERLAP`. A release is born in `SCHEDULED` status with `entry_count`, `winner_count`, `reserved_units`, and `sold_units` all at zero.

The release lifecycle is driven entirely by the operator through a series of transitions. Moving a release from `SCHEDULED` to `OPEN` requires that the logical clock has reached or passed `entry_opens_at`; once open, the release accepts raffle entries. Opening a release that is not in `SCHEDULED` status is rejected with `ERR_RELEASE_NOT_OPEN` (the status check is applied before the clock check), and opening before the clock has reached `entry_opens_at` is rejected with `ERR_VALIDATION`. Releases are readable individually and as a list; the list view may be narrowed by `sku_id` and by `status`, and honors the standard `limit` and `offset` parameters.

A verified `Buyer` joins a drop by entering the raffle, which snapshots a new `RaffleEntry` referencing the `release_id` and the entrant's `account_id`. Entry is fenced by several conditions evaluated together: the release must be `OPEN` or the attempt is rejected with `ERR_RELEASE_NOT_OPEN`; the acting account must be `VERIFIED` or the attempt is rejected with `ERR_ACCOUNT_NOT_VERIFIED`; the account's tenure — the number of whole days between its `created_at` and the current logical clock — must be at least 3 days or the attempt is rejected with `ERR_BOT_FLAGGED` as a bot heuristic; the logical clock must fall within the entry window, at or after `entry_opens_at` and strictly before `entry_closes_at`, or the attempt is rejected with `ERR_ENTRY_WINDOW_CLOSED`; and the account must not already hold an entry for this release or the attempt is rejected with `ERR_DUPLICATE_ENTRY`. A successful entry increments the release's `entry_count` by one and computes the entry's fairness and bot-risk figures as described next.

At entry time the system computes a `bot_risk_score` for the entry as follows: count how many entries this same account has created for the same SKU within the trailing 24 hours measured against the logical clock, subtract 2 from that count, take the larger of that difference and 0, multiply by 0.2, and take the smaller of the result and 1.0. The entry's `bot_flag` is set to true when its `bot_risk_score` is at least 0.6, and flagged entries are excluded from the draw entirely; otherwise `bot_flag` is false. The entry also captures a `fairness_score` snapshot. First derive a tenure factor from the account's tenure in whole days: the factor is 1.0 when tenure is at least 30 days, 0.5 when tenure is at least 7 days but below 30, and 0.0 below 7 days. Then combine three weighted terms at full precision — one-half of the account's `trust_score`, plus three-tenths of the tenure factor, plus two-tenths of the quantity (one minus the entry's `bot_risk_score`) — and round the summed total half up to four decimal places to obtain the `fairness_score`. Each new entry starts with `result` of `PENDING`, a `claim_status` of `NONE`, and a null `claim_deadline`.

### 3.3. The Fairness-Weighted Draw, Settlement, and Cancellation

Closing entries and running the draw advances a release from `OPEN` to `DRAWN`. The operator triggers the draw with an `expected_release_version` that must equal the release's current `version`; the logical clock must have reached or passed `entry_closes_at`; and at least one **eligible** entry must exist, where an entry is eligible when its `result` is `PENDING` and its `bot_flag` is false. If no eligible entry exists the draw is rejected with `ERR_NO_ELIGIBLE_ENTRIES`. Attempting to draw a release that is not `OPEN` — including drawing one that has already been drawn — is rejected with `ERR_RELEASE_NOT_DRAWN`. These conditions are evaluated in a fixed order that (for the draw specifically) applies the release-status check before the version guard: the `expected_release_version` field must be present and an integer (else `ERR_VALIDATION`), then the release must be `OPEN` (else `ERR_RELEASE_NOT_DRAWN`, 409), then `expected_release_version` must equal the current `version` (else `ERR_STALE_VERSION`, 412), then the clock must have reached `entry_closes_at` (a clock that has not is rejected with `ERR_VALIDATION`), and finally at least one eligible entry must exist.

The allocation itself is a strict ranked waterfall over integer unit counts. Take every eligible entry, rank them by `fairness_score` in descending order, breaking ties by `created_at` in ascending order — the resource `id` is never used as a tiebreaker — and take the top entries up to the smaller of `allocated_quantity` and the number of eligible entries. Each entry so selected has its `result` set to `WON`; every other eligible entry has its `result` set to `LOST`. Each newly won entry receives a `claim_deadline` equal to the release's `purchase_closes_at`. The release's `winner_count` is set to the number of winners, its `reserved_units` is increased by that winner count, and its `version` is incremented by one.

Settlement closes the purchase window and advances a release from `DRAWN` to `SETTLED`; it requires the logical clock to have reached or passed `purchase_closes_at`. Settling a release that is not in `DRAWN` status is rejected with `ERR_RELEASE_NOT_DRAWN` (checked before the clock), and settling before the clock has reached `purchase_closes_at` is rejected with `ERR_VALIDATION`. At settlement, every entry that won but never claimed — that is, every `WON` entry whose `claim_status` is still `NONE` — has its `claim_status` set to `EXPIRED` as a compensating release of its reservation. The release's `reserved_units` is decreased by the number of expired winners, and those freed units return to `available_units`, preserving the unit-conservation identity.

Cancellation is available to the operator from two points. Cancelling a `SCHEDULED` release simply moves it to `CANCELLED`, after which no entries can be created. Cancelling an `OPEN` release also moves it to `CANCELLED` but additionally cascades down: every entry still in `PENDING` has its `result` set to `LOST`. Cancelling a release from any other state — `DRAWN`, `SETTLED`, or already `CANCELLED` — is rejected with `ERR_RELEASE_NOT_OPEN`. Both `SETTLED` and `CANCELLED` are terminal states for a release.

### 3.4. Claiming a Win

A winning `Buyer` converts their win into a purchase by claiming the entry, which keeps the entry in `WON` while flipping its `claim_status` from `NONE` to `CLAIMED`. A claim requires that the parent release is in `DRAWN` status — otherwise `ERR_RELEASE_NOT_DRAWN` — and that the entry actually won: claiming an entry whose `result` is not `WON` is rejected with `ERR_ENTRY_NOT_WON`. The logical clock must fall inside the purchase window, at or after `purchase_opens_at` and strictly before `purchase_closes_at`, or the claim is rejected with `ERR_PURCHASE_WINDOW_CLOSED`. The entry must not already have been claimed: a `claim_status` other than `NONE` is rejected with `ERR_ENTRY_ALREADY_CLAIMED`.

A successful claim sets the entry's `claim_status` to `CLAIMED` and creates a raffle `Order`. That order has `source_type` of `RAFFLE`, its `raffle_entry_id` pointing back at the claimed entry, a `sale_price_cents` equal to the release's `release_price_cents`, and — because the platform itself sells the new pair — a null `seller_account_id` with no linked `listing_id` or `bid_id`. Claiming also moves one unit from the reserved pool to the sold pool: the release's `reserved_units` is decreased by one and its `sold_units` is increased by one, again conserving total units.

### 3.5. Resale Listings, Bids, and Matching

On the secondary market a `Seller` publishes a resale ask by creating a `Listing` for a `sku_id` and their own `seller_account_id`, declaring the pair's `size` (a US size string), its `condition` (one of `DEADSTOCK`, `VNDS`, or `USED`), a `pricing_mode`, and an `ask_price_cents` greater than zero, with an optional `expires_at` beyond which the listing lapses (a null expiry means good-till-cancelled). When `pricing_mode` is `FIXED`, the listing is buy-now only; when it is `BID_ASK`, the listing may additionally be matched against standing buyer bids. A listing opens in `ACTIVE` status. A seller may later reprice an `ACTIVE` listing by supplying a `new_ask_price_cents` together with the `expected_listing_version` guard of §2.6; a successful reprice overwrites `ask_price_cents` with the new value and increments the listing's `version`. Repricing, buying, or matching a listing that is not `ACTIVE` is rejected with `ERR_LISTING_NOT_ACTIVE`. Listings are readable individually and as a filtered list narrowed by `sku_id`, `seller_account_id`, and `status`.

Independently, a `Buyer` places a `Bid` naming a `sku_id`, their own `buyer_account_id`, a requested `size`, and an `amount_cents` greater than zero, with an optional `expires_at`. A bid opens in `OPEN` status and is readable individually or through a list filtered by `sku_id`, `buyer_account_id`, and `status`.

A verified buyer can buy a listing outright at its ask. Buying is fenced by several conditions: the acting account must be `VERIFIED` or the buy is rejected with `ERR_ACCOUNT_NOT_VERIFIED`; the buyer must not be the listing's own seller — a `buyer_account_id` equal to the listing's `seller_account_id` is rejected with `ERR_SELF_PURCHASE`; and the buyer must be within their per-SKU purchase limit. That limit caps a buyer at fewer than two completed fixed-price buys of the same SKU within the trailing 24-hour window measured against the logical clock; a buyer who already has two such buys in that window is rejected with `ERR_PURCHASE_LIMIT_REACHED`. The count is taken over `Order`s whose `source_type` is `FIXED` for that buyer and SKU whose creation instant falls strictly after the point 24 hours before the current clock, counted irrespective of the order's later `payment_status` or `fulfillment_status`. The listing's `ERR_LISTING_NOT_ACTIVE` status check (409) precedes the verification (`ERR_ACCOUNT_NOT_VERIFIED`), self-purchase (`ERR_SELF_PURCHASE`), and purchase-limit (`ERR_PURCHASE_LIMIT_REACHED`) checks. A successful buy advances the listing from `ACTIVE` to `MATCHED`, increments its `version`, and creates an `Order` with `source_type` of `FIXED`, its `listing_id` set, a `sale_price_cents` equal to the listing's `ask_price_cents`, and provisional fees and payout computed as in §3.7.

Alternatively, the listing's own seller may match it against a specific standing bid, transitioning the listing from `ACTIVE` to `MATCHED` under the same optimistic-concurrency guard: the match supplies the `bid_id` to pair with and an `expected_listing_version` that must equal the listing's current `version`, failing which the match is rejected with `ERR_STALE_VERSION`. The nominated bid must exist, the acting account must be `VERIFIED` or the match is rejected with `ERR_ACCOUNT_NOT_VERIFIED`, and the bid's buyer must not be the listing's seller or the match is rejected with `ERR_SELF_PURCHASE`. The bid must reference the same SKU and size as the listing — a `bid_id` whose bid has a different `sku_id` or `size` than the listing is rejected with `ERR_SKU_MISMATCH` — and the bid's `amount_cents` must be at least the listing's `ask_price_cents`, failing which the match is rejected with `ERR_BID_BELOW_ASK`. A successful match sets the bid's status from `OPEN` to `MATCHED`, moves the listing to `MATCHED` and increments its `version`, and creates an `Order` with `source_type` of `BID_MATCH`, both its `listing_id` and `bid_id` set, and a `sale_price_cents` equal to the bid's `amount_cents`. `MATCHED` is terminal for both listings and bids.

### 3.6. Consignment Intake, Inspection, and Grading

Every resale order — whether `FIXED` or `BID_MATCH` — requires the physical pair to be shipped in and authenticated before it can reach the buyer; raffle orders skip this path entirely because the platform ships a brand-new pair directly. The `Seller` opens authentication by creating a `ConsignmentItem` referencing the resale `order_id`, their `seller_account_id`, and the `sku_id`, and declaring the item's condition up front: a `declared_condition_grade` (one of `DEADSTOCK`, `VNDS`, or `USED`), a `declared_box_grade` (one of `PERFECT`, `GOOD`, `DAMAGED`, or `MISSING`), and a boolean `declared_accessories_complete` indicating whether all extra laces and tags are present. The item begins in `INTAKE_PENDING` status with a null `authenticator_id`, and at intake the system computes its `declared_grade_score` from the declared fields.

The grade score combines three weighted components at full precision and then rounds the total. A condition value is drawn from the grade — 1.0 for `DEADSTOCK`, 0.85 for `VNDS`, 0.6 for `USED` — a box value is drawn from the box grade — 1.0 for `PERFECT`, 0.8 for `GOOD`, 0.5 for `DAMAGED`, 0.0 for `MISSING` — and an accessories value is 1.0 when accessories are complete and 0.0 otherwise. Multiply the condition value by 0.6, the box value by 0.25, and the accessories value by 0.15, sum the three products, and round that sum half up to four decimal places. The `declared_grade_score` uses the declared fields; the `authenticated_grade_score` computed later uses the authenticator-verified fields.

An `Authenticator` walks each item through a short lifecycle, and each transition must start from the correct status or it is rejected with `ERR_CONSIGNMENT_NOT_RECEIVED`. Confirming physical receipt moves the item from `INTAKE_PENDING` to `RECEIVED` and, as a cross-entity effect, advances the linked order's `fulfillment_status` from `AWAITING_SHIPMENT` to `IN_AUTHENTICATION` (the order's `payment_status` stays `AUTHORIZED`, since the two axes move independently). Scheduling an inspection moves the item from `RECEIVED` to `UNDER_AUTHENTICATION`, recording the assigned `authenticator_id`, an `inspection_window_start` (inclusive), and an `inspection_window_end` (exclusive). The requested slot is a half-open interval and must not overlap any other `UNDER_AUTHENTICATION` item's slot on the same authenticator; back-to-back slots that merely touch at an endpoint are allowed, but a genuine overlap is rejected with `ERR_AUTHENTICATOR_UNAVAILABLE`. The named authenticator must exist, or the request is rejected with `ERR_AUTHENTICATOR_NOT_FOUND`.

Completing an inspection records a verdict and forks the item into one of two terminal outcomes. When the `inspection_result` is `PASS`, the item moves from `UNDER_AUTHENTICATION` to `AUTHENTICATED`: the authenticator's verified findings — `authenticated_condition_grade`, `authenticated_box_grade`, and `authenticated_accessories_complete` — are recorded, the `authenticated_grade_score` is computed from those verified fields, and the linked order's `fulfillment_status` advances to `AUTHENTICATED`. When the `inspection_result` is `FAIL`, the item moves from `UNDER_AUTHENTICATION` to `REJECTED`, and the divergent cascade differs sharply from the pass branch: the linked order's `fulfillment_status` is set to `FAILED_AUTH` and its `payment_status` is set to `VOIDED`, and the shipping seller's `Account.strikes` counter is incremented by one. Both `AUTHENTICATED` and `REJECTED` are terminal for the item.

### 3.7. Shipping, Buyer Verification, and Payout Settlement

Once an order is ready to ship, a `PlatformAdmin` ships it to the buyer. For a resale order the order must be in fulfillment status `AUTHENTICATED` and its linked consignment item must have reached `AUTHENTICATED`; if no consignment item exists for the order, or the linked item has not reached `AUTHENTICATED`, the shipment is rejected with `ERR_ITEM_NOT_AUTHENTICATED`, and this linked-item check is applied before the order-fulfillment-state check. For a raffle order, which never passes through authentication, shipment proceeds directly from `AWAITING_SHIPMENT`. An order in any other fulfillment state for this operation is rejected with `ERR_ORDER_STATE_INVALID`. Shipping advances the order's `fulfillment_status` to `SHIPPED_TO_BUYER` and stamps a `dispute_deadline` equal to the current logical clock plus a fixed dispute window of 3 days.

Buyer charges are computed once, at order creation, and are the same regardless of source. Shipping is a flat `shipping_fee_cents` fixed at 1500 cents. The `payment_processing_fee_cents` is charged on the pre-fee subtotal, never on the grand total: form the subtotal as `sale_price_cents` plus `shipping_fee_cents`, multiply that subtotal by 0.029, add a flat 30 cents, and round the result half up to whole cents. The `buyer_total_cents` is then the exact integer sum of `sale_price_cents`, `shipping_fee_cents`, and `payment_processing_fee_cents`. Every new order also starts with `payment_status` of `AUTHORIZED` and `fulfillment_status` of `AWAITING_SHIPMENT`.

The platform commission — the `transaction_fee_cents` — is a tiered fee computed both provisionally at order creation and finally at buyer verification, and the two computations can differ. The base commission rate is chosen from the seller's `seller_level` at the moment of evaluation: 0.09 for `STANDARD`, 0.07 for `PRO`, and 0.05 for `ELITE`. When the order's `sale_price_cents` is at least 50000 cents (that is, 500 dollars), the effective rate is the base rate reduced by 0.01; otherwise the effective rate equals the base rate. Multiply `sale_price_cents` by the effective rate and round half up to whole cents to get a raw fee, then clamp that raw fee to lie between a floor of 500 cents and a ceiling of 10000 cents — raise it to 500 if it falls below, lower it to 10000 if it rises above. The provisional variant reads `seller_level` as it stands at creation; the final variant re-reads `seller_level` as it stands at verification, so a seller who levels up between the two events pays a different final fee than the provisional estimate implied.

Seller payout is likewise computed in a provisional and a final variant, and the nested rounding order is pinned: the transaction fee is rounded to whole cents first (as above) and only then subtracted, and the resulting net is never rounded again. At order creation the `provisional_payout_cents` is the `sale_price_cents` minus the provisional `transaction_fee_cents`, with no downgrade deduction because the item has not yet been inspected — the `downgrade_adjustment_cents` is forced to 0 at this stage. The final settlement happens when the buyer verifies the order.

Buyer verification advances an order from `SHIPPED_TO_BUYER` to `VERIFIED`; attempting to verify an order not in `SHIPPED_TO_BUYER` is rejected with `ERR_ORDER_STATE_INVALID`, and verification requires the order's `payment_status` to be `AUTHORIZED` — a `payment_status` other than `AUTHORIZED` is likewise rejected with `ERR_ORDER_STATE_INVALID`. Verification first advances the payment axis to `CAPTURED`. It then computes the `downgrade_adjustment_cents`: rank the shoe conditions with `DEADSTOCK` as 3, `VNDS` as 2, and `USED` as 1, and if the authenticated condition ranks strictly below the declared condition — that is, the authenticator downgraded the pair — the adjustment is 0.15 times `sale_price_cents` rounded half up to whole cents; otherwise the adjustment is 0. The `final_payout_cents` is then `sale_price_cents` minus the final `transaction_fee_cents` minus the `downgrade_adjustment_cents`, and it diverges from the provisional figure whenever a downgrade applies or the seller's level changed between creation and verification. For a resale order (`FIXED` or `BID_MATCH`), verification then cascades through the seller's `Account`: the `final_payout_cents` is added to the seller's `balance_cents`, the seller's `completed_sales_count` is incremented by one, and the seller's `seller_level` is recomputed from that new count; the seller's `trust_score` has no defined recompute formula and is left unchanged. The seller level is derived purely from `completed_sales_count`: `STANDARD` for a count from 0 up to but not including 5, `PRO` for a count from 5 up to but not including 20, and `ELITE` for a count of 20 or more. A raffle order, sold by the platform with no seller account, credits no ledger on verification.

### 3.8. Disputes and Refund Clawback

A `Buyer` who received a problematic order may file a `Dispute` referencing the `order_id`, a `filed_by_account_id` that must equal the order's `buyer_account_id`, and a `reason` that is one of `NOT_AS_DESCRIBED`, `NOT_RECEIVED`, or `INAUTHENTIC`. Disputes are only accepted against an order whose `fulfillment_status` is `SHIPPED_TO_BUYER` or `VERIFIED`; filing against an order in any other fulfillment state is rejected with `ERR_ORDER_NOT_DISPUTABLE`. The filing must also be timely: the logical clock must be at or before the order's `dispute_deadline`, and a clock past that deadline is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`. A new dispute opens in `OPEN` status with a null `resolution_note`.

A `CustomerService` agent resolves an open dispute by supplying an `outcome` of either `REFUND` or `DENY` and an optional `resolution_note` capturing the decision. Resolving a dispute that is not `OPEN` is rejected with `ERR_DISPUTE_ALREADY_RESOLVED`. A `DENY` outcome moves the dispute to `RESOLVED_DENIED` and changes nothing else — no ledger movement and no order change. A `REFUND` outcome moves the dispute to `RESOLVED_REFUND` and reverses the sale: the order's `payment_status` is set to `REFUNDED`, and for a resale order (`FIXED` or `BID_MATCH`) the clawback cascade mirrors the verification credit in reverse — the order's `final_payout_cents` is subtracted from the seller's `balance_cents`, the seller's `completed_sales_count` is decremented by one, and the seller's `seller_level` is recomputed from the reduced count while the `trust_score` is left unchanged. This clawback cascade is applied only when the order carries a recorded (non-null) `final_payout_cents` — that is, when it had already been verified; a `REFUND` outcome on a resale order that was never verified still sets the order's `payment_status` to `REFUNDED` but touches no seller account. Both `RESOLVED_REFUND` and `RESOLVED_DENIED` are terminal for a dispute. Disputes are readable individually and through a list filtered by `order_id`, `filed_by_account_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource — including lifecycle transitions and the logical-clock setter — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/accounts` | Create an account | PlatformAdmin |
| GET | `/accounts/{id}` | Fetch an account | Buyer, Seller, Authenticator, PlatformAdmin, CustomerService |
| POST | `/accounts/{id}/verify` | Mark an account verified | PlatformAdmin |
| POST | `/skus` | Create a SKU | PlatformAdmin |
| GET | `/skus/{id}` | Fetch a SKU | Buyer, Seller, Authenticator, PlatformAdmin, CustomerService |
| POST | `/authenticators` | Register an authentication center/staff | PlatformAdmin |
| GET | `/authenticators/{id}` | Fetch an authenticator | Authenticator, PlatformAdmin, CustomerService |
| POST | `/releases` | Schedule a drop for a SKU | PlatformAdmin |
| GET | `/releases/{id}` | Fetch a release | Buyer, Seller, Authenticator, PlatformAdmin, CustomerService |
| GET | `/releases` | List releases | Buyer, Seller, Authenticator, PlatformAdmin, CustomerService |
| POST | `/releases/{id}/open` | Open the raffle entry window | PlatformAdmin |
| POST | `/releases/{id}/draw` | Run the fairness-weighted draw | PlatformAdmin |
| POST | `/releases/{id}/settle` | Close the purchase window; expire unclaimed winners | PlatformAdmin |
| POST | `/releases/{id}/cancel` | Cancel a scheduled/open release | PlatformAdmin |
| POST | `/releases/{id}/enter` | Enter the raffle | Buyer |
| GET | `/raffle-entries/{id}` | Fetch a raffle entry | Buyer, PlatformAdmin, CustomerService |
| GET | `/raffle-entries` | List raffle entries | Buyer, PlatformAdmin, CustomerService |
| POST | `/raffle-entries/{id}/claim` | Claim a won entry, creating a raffle order | Buyer |
| POST | `/listings` | Create a resale ask | Seller |
| GET | `/listings/{id}` | Fetch a listing | Buyer, Seller, PlatformAdmin, CustomerService |
| GET | `/listings` | List listings | Buyer, Seller, PlatformAdmin, CustomerService |
| POST | `/listings/{id}/reprice` | Reprice an active listing | Seller |
| POST | `/listings/{id}/buy` | Buy-now at the ask | Buyer |
| POST | `/listings/{id}/match` | Match a listing to a buyer bid | Seller |
| POST | `/bids` | Place a buyer bid on a SKU/size | Buyer |
| GET | `/bids/{id}` | Fetch a bid | Buyer, Seller, PlatformAdmin, CustomerService |
| GET | `/bids` | List bids | Buyer, Seller, PlatformAdmin, CustomerService |
| GET | `/orders/{id}` | Fetch an order | Buyer, Seller, PlatformAdmin, CustomerService |
| GET | `/orders` | List orders | Buyer, Seller, PlatformAdmin, CustomerService |
| POST | `/orders/{id}/ship-to-buyer` | Ship the pair to the buyer | PlatformAdmin |
| POST | `/orders/{id}/verify` | Buyer verifies receipt; capture and settle | Buyer |
| POST | `/consignment-items` | Ship a sold item in for authentication | Seller |
| GET | `/consignment-items/{id}` | Fetch a consignment item | Seller, Authenticator, PlatformAdmin, CustomerService |
| GET | `/consignment-items` | List consignment items | Seller, Authenticator, PlatformAdmin, CustomerService |
| POST | `/consignment-items/{id}/receive` | Confirm physical receipt | Authenticator |
| POST | `/consignment-items/{id}/schedule-inspection` | Book an inspection slot | Authenticator |
| POST | `/consignment-items/{id}/complete-inspection` | Record verdict and authenticated grades | Authenticator |
| POST | `/disputes` | File a dispute on a shipped/verified order | Buyer |
| GET | `/disputes/{id}` | Fetch a dispute | Buyer, PlatformAdmin, CustomerService |
| GET | `/disputes` | List disputes | Buyer, PlatformAdmin, CustomerService |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (refund clawback or deny) | CustomerService |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_SKU_NOT_FOUND` | 404 |
| `ERR_RELEASE_NOT_FOUND` | 404 |
| `ERR_RAFFLE_ENTRY_NOT_FOUND` | 404 |
| `ERR_CONSIGNMENT_NOT_FOUND` | 404 |
| `ERR_AUTHENTICATOR_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RELEASE_NOT_OPEN` | 409 |
| `ERR_RELEASE_NOT_DRAWN` | 409 |
| `ERR_ENTRY_NOT_WON` | 409 |
| `ERR_ENTRY_ALREADY_CLAIMED` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_CONSIGNMENT_NOT_RECEIVED` | 409 |
| `ERR_ITEM_NOT_AUTHENTICATED` | 409 |
| `ERR_ORDER_STATE_INVALID` | 409 |
| `ERR_ORDER_NOT_DISPUTABLE` | 409 |
| `ERR_DISPUTE_ALREADY_RESOLVED` | 409 |
| `ERR_ACCOUNT_NOT_VERIFIED` | 403 |
| `ERR_BOT_FLAGGED` | 403 |
| `ERR_SELF_PURCHASE` | 403 |
| `ERR_RELEASE_WINDOW_OVERLAP` | 409 |
| `ERR_ENTRY_WINDOW_CLOSED` | 422 |
| `ERR_PURCHASE_WINDOW_CLOSED` | 422 |
| `ERR_AUTHENTICATOR_UNAVAILABLE` | 409 |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 |
| `ERR_SKU_MISMATCH` | 422 |
| `ERR_DUPLICATE_ENTRY` | 409 |
| `ERR_PURCHASE_LIMIT_REACHED` | 409 |
| `ERR_NO_ELIGIBLE_ENTRIES` | 422 |
| `ERR_BID_BELOW_ASK` | 422 |
