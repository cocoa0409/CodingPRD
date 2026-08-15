# Farmland Auction & Brokerage API — Product Requirements Document

## 1. Introduction

Selling farmland at auction is a packaging and valuation problem long before it is a sales event. A brokerage takes on a landowner's property, decides whether to offer it whole, split it into tracts, or allow combination bidding across tracts, and defends an asking strategy with soil-productivity-adjusted evidence drawn from recent comparable sales in the same state. Buyers must be financially qualified before they may bid; winners must put up earnest money on a strict deadline; and between award and disbursement the brokerage coordinates tenant-lease disclosures, mineral and wind rights declarations, title work, surveys, and funding — all while the seller watches a net sheet converge from provisional estimate to final settlement figures.

This document specifies the API for such a farmland auction and brokerage platform. It governs the full lifecycle from party onboarding through listing assembly, valuation, marketing, three auction methods (live, online, and sealed-bid), escrowed earnest money, and closing coordination, ending in disbursement or an orderly unwind. Several concerns cut across every workflow: a server-owned logical clock drives all deadlines and sweeps; optimistic concurrency protects listing packaging and bid placement against stale views; escrow handling follows a strict segregation of duties between the agent who records payments and the administrator who verifies them; and tiered schedules — bid increments, commission brackets, earnest-money floors — trigger rate changes at exact boundaries. All API resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare its operational capacity. The system recognizes exactly four roles: `Seller`, `BrokerAgent`, `Buyer`, and `PlatformAdmin`. A request with a missing or unrecognized header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Beyond authentication, every operation carries a role list, and several operations carry an ownership rule; a caller whose role is not permitted, or who fails the ownership check on the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the presented role. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a seller — principally a listing's `seller_id` — compare that field to `X-User-ID`. When `X-User-Role` is `BrokerAgent`, `X-User-ID` is the `id` of the acting `BrokerAgent`; ownership checks on any resource that references an agent — principally a listing's `agent_id` — compare that field to `X-User-ID`. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on any resource that references a buyer — a bid's `buyer_id`, a deposit's `buyer_id` — compare that field to `X-User-ID`, and a buyer reading another buyer's record, bid, or deposit is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — sellers, broker agents, buyers, listings, tracts, auctions, bids, earnest-money deposits, lease disclosures, rights dispositions, closing packages, and settlement statements — share a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; refreshed on every change to the resource.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource, and which anchors the optimistic concurrency rules of §2.7.

Comparable sale records are the sole exception. A `ComparableSale` is immutable once created and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock and Scheduled Sweeps

Every temporal rule in this document — auction windows, bid acceptance cutoffs, qualification expiry, deposit deadlines, forfeiture grace, comparable-sale eligibility — is evaluated against a server-owned **logical clock**, never against wall-clock time. At server start the logical clock reads exactly `2026-08-01T00:00:00Z`.

An admin-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Setting the clock is not a passive read-modify-write: it runs every pending time sweep in the system. Auctions whose `effective_end` has been reached are swept closed — to `CLOSED_PENDING_AWARD` when at least one bid stands, to `NO_SALE` when none does; buyers whose qualification expiry has been reached move from `QUALIFIED` to `EXPIRED`; deposits past their deadline move from `PENDING` to `LATE`; and deposits still unpaid past their grace period are forfeited, firing the unwind cascade described in §3.7. Clients that need deterministic behavior must drive time through this capability rather than assume real-time passage.

### 2.6. Monetary Precision and Rounding

All monetary arithmetic is performed in decimal, never binary floating point. Stored and returned monetary values are rounded half-up to exactly 2 decimal places, with one exception family: tract valuations report `estimated_value` rounded half-up to whole dollars (0 decimal places) and `value_per_acre` rounded half-up to 2 decimal places.

Rounding order is pinned wherever a calculation could drift. Per-tract closing-cost shares are each rounded half-up to 2 decimal places *before* any residual is assigned; the daily rent used in possession proration is rounded half-up to 2 decimal places *before* being multiplied by days; the combination-bid premium threshold is rounded half-up to 2 decimal places; and in the commission schedule only the final commission figure is rounded — the tier components and the kicker enter the final sum unrounded.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by mandatory optimistic concurrency checks; no other endpoint takes a version field.

Adding a tract to a listing requires the request to carry `expected_listing_version` holding the listing's `version` as the caller last observed it. Because every tract creation — and every other mutation of the listing — increments `Listing.version`, a caller whose last-read version has since advanced is acting on a stale view of the tract set and the acreage reconciliation; the request is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412).

Placing a bid requires the request to carry `expected_auction_version` holding the auction's `version` as the bidder last observed it. Every accepted bid increments `AuctionEvent.version`, so a bidder holding version N who submits `expected_auction_version` N after another accepted bid has moved the auction to N+1 is acting on a stale view of the current high bid; the request is rejected with `ERR_STALE_AUCTION_VERSION` (HTTP 412). Both fields are non-optional on their respective endpoints.

### 2.8. Validation Order and Nested Resource Retrieval

The server evaluates every request against a fixed validation pipeline, and the ordering is observable: a request that would fail two checks surfaces the earlier one. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the caller's role appears in the endpoint's role list and any ownership rule holds, else `ERR_FORBIDDEN`.
3. **Existence** — path identifiers are resolved left to right, then body reference identifiers (`seller_id`, `listing_id`, `tract_id`, `auction_id`, `closing_id`, and each element of `tract_ids`) are resolved; the first missing identifier yields `ERR_NOT_FOUND`. For nested paths, the parent is located before the child is even sought.
4. **Request schema** — required fields present, types correct, enum values valid, ranges respected: acreage figures positive, soil productivity greater than zero and at most 100, tillable acres not exceeding gross acres, monetary amounts positive where required, dates parseable; a survey waiver without consent and a qualification expiry not in the future also fail here, all as `ERR_VALIDATION`.
5. **State gates** — the target entity's state must permit the operation, else the appropriate state error (`ERR_INVALID_LISTING_STATE`, `ERR_INVALID_AUCTION_STATE`, `ERR_AUCTION_NOT_OPEN`, `ERR_INVALID_DEPOSIT_STATE`, `ERR_INVALID_CLOSING_STATE`, `ERR_INVALID_DISCLOSURE_STATE`, or `ERR_RIGHTS_LOCKED`).
6. **Optimistic concurrency** — the version checks of §2.7.
7. **Business compliance** — buyer qualification, disclosure acknowledgement, and rights declaration checks.
8. **Temporal windows** — auction window well-formedness, scheduling overlap and buffer rules, and the closing-date rule.
9. **Referential integrity** — acreage reconciliation, bid scope shape, and uniqueness rules.
10. **Fiscal checks** — bid increments and minimum floors, proof of funds, and the reserve checks.

### 2.9. Cascading State Consistency Across the Sale Chain

A listing is never an isolated record: it anchors tracts, auctions, bids, deposits, disclosures, rights, and ultimately a closing package, and the server keeps the whole chain mutually consistent without requiring clients to touch each resource. Marketing a listing offers its tracts; opening an auction locks rights declarations and re-offers previously unsold tracts; an award sells tracts, spawns deposits, and may put the listing under contract; forfeiture and termination unwind the chain in the reverse direction; disbursement settles it permanently. Each of these reconciliations mutates every entity it touches — refreshing that entity's `updated_at` and incrementing its `version` — so a client watching any single resource can detect that the chain moved. The detailed transitions and their triggers live in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding Parties and Buyer Qualification

A `PlatformAdmin` onboards every party. Creating a seller requires `full_name` and `email`. Creating a broker agent requires `full_name` and a `license_number` that is unique across agents — a duplicate license number is rejected with `ERR_DUPLICATE_RECORD`. Creating a buyer requires `full_name`, `email`, and `proof_of_funds_amount`, the verified ceiling on that buyer's bidding: no single bid `amount` may exceed it. A new buyer's `qualification_status` starts at `UNVERIFIED`.

Qualification is an administrative act. An admin qualifies a buyer by supplying `qualification_expires_at`, which the system records verbatim; the buyer moves from `UNVERIFIED` to `QUALIFIED`. The full qualification cycle has four states — `UNVERIFIED`, `QUALIFIED`, `EXPIRED`, `DISQUALIFIED` — and two system-driven edges: when the logical clock reaches or passes a qualified buyer's `qualification_expires_at`, the buyer moves from `QUALIFIED` to `EXPIRED`, and when the forfeiture cascade of §3.7 fires, the affected buyer moves to `DISQUALIFIED` whether currently `QUALIFIED` or `EXPIRED`. Re-qualification is permitted from `EXPIRED` — the admin supplies a fresh `qualification_expires_at`, which must be strictly after the logical clock, and a value not in the future is rejected with `ERR_VALIDATION` — but `DISQUALIFIED` is terminal and may never be qualified again.

Buyers may read their own record; a `Buyer` presenting another buyer's `id` is rejected with `ERR_FORBIDDEN`, while `BrokerAgent` and `PlatformAdmin` callers may read any buyer.

### 3.2. Assembling the Listing: Tracts, Acreage, and Packaging

A `BrokerAgent` creates a listing by naming the owning seller via `seller_id` and supplying a marketing `title`, the `county`, a two-letter `state_code`, the deeded `total_gross_acres`, a `packaging_strategy` of `WHOLE`, `SPLIT`, or `COMBINATION`, and the seller's `reserve_price_total` — the minimum acceptable award total for the whole listing. The listing is born in `DRAFT`, and its `agent_id` is set from the creating agent's `X-User-ID`, which thereafter defines ownership of the listing for every agent-gated operation. Listings may be browsed with optional `seller_id`, `agent_id`, and `status` filters plus the standard `limit` and `offset` parameters.

Tracts are added to a `DRAFT` listing by its agent; adding to a listing in any other state is rejected with `ERR_INVALID_LISTING_STATE`. Each tract carries `listing_id`, a `tract_number` unique within the listing (the allocation residual rules of §3.8 favor the highest `tract_number`), `gross_acres` greater than zero, `tillable_acres` no less than zero and no greater than the tract's gross acres, a `soil_productivity_index` greater than zero and no more than 100, and a `min_price` no less than zero — the per-tract minimum acceptable bid contribution. Range violations surface as `ERR_VALIDATION`. The request must also carry `expected_listing_version` per §2.7, and a stale value is rejected with `ERR_STALE_LISTING_VERSION`. Acreage is reconciled incrementally: the sum of existing tracts' gross acres plus the new tract's `gross_acres` must not exceed the listing's `total_gross_acres`, else `ERR_ACREAGE_MISMATCH`. These gates fire in the pipeline order of §2.8 — the listing state check first, then the version check, then the acreage reconciliation — so a request failing more than one surfaces the earliest. Every accepted tract creation increments the listing's `version`, and each new tract begins life `REGISTERED`.

Packaging moves the listing from `DRAFT` to `PACKAGED` and is where the strategy becomes binding. The caller must be the listing's agent, else `ERR_FORBIDDEN`. The checks run in a fixed order. First, acreage: at least one tract must exist, and the tract acreage must reconcile to `total_gross_acres` exactly — a listing with no tracts, or one whose tract sum is short of or over the total, fails with `ERR_ACREAGE_MISMATCH`. Second, the reserve floor: `reserve_price_total` must be at least 85% of the sum of the `PROVISIONAL` valuations (per §3.3) across all tracts; if any tract's comparable set is empty the check aborts with `ERR_NO_COMPARABLES`, and a reserve below the floor is rejected with `ERR_RESERVE_BELOW_FLOOR`. On success the `packaging_strategy` becomes immutable — it can never change once the listing has left `DRAFT` — and the listing's `version` increments.

Withdrawal is the seller's and agent's pre-contract escape hatch. The listing's seller (matched on `seller_id`) or its agent may withdraw from `DRAFT`, `PACKAGED`, `MARKETED`, or `AUCTION_SCHEDULED`; any other caller is rejected with `ERR_FORBIDDEN`. Withdrawal is deliberately unavailable from `UNDER_CONTRACT` and `CLOSED` — no transition exists from those states, and the attempt is rejected with `ERR_INVALID_LISTING_STATE`. The withdrawal cascade is identical from all four source states: every auction of the listing in `SCHEDULED`, `OPEN`, or `EXTENDED` moves to `CANCELLED`; every bid of those auctions in `PLACED` or `SEALED` moves to `VOIDED`; rights dispositions revert from `LOCKED` to `DECLARED`; and every tract in `REGISTERED`, `OFFERED`, or `UNSOLD` moves to `WITHDRAWN`.

### 3.3. Comparable Sales and Soil-Adjusted Valuation

Valuation evidence enters the system as `ComparableSale` records, created by a `PlatformAdmin` with `county`, `state_code`, `sale_date`, `sale_price_total`, `gross_acres` greater than zero, `tillable_acres`, and a `soil_productivity_index` greater than zero. Comparable records are immutable once created.

A tract's valuation is a computed read selected by the `variant` parameter, which takes `PROVISIONAL` or `APPRAISAL`. The comparable set for a tract is every `ComparableSale` whose `state_code` matches the state code of the tract's listing and whose `sale_date` falls inside the trailing twenty-four-month window — from the instant twenty-four months before the logical clock up to the logical clock itself, both ends inclusive. If that set is empty, the read fails with `ERR_NO_COMPARABLES`. For each comparable, a base per-acre figure is computed: the comparable's `sale_price_total` divided by its `gross_acres`, then scaled by the ratio of the tract's `soil_productivity_index` to the comparable's `soil_productivity_index`.

The `PROVISIONAL` variant applies no further adjustment: the per-acre value is the unweighted mean of the base figures across the whole comparable set, with no per-comparable rounding, and the tract's `estimated_value` is that mean multiplied by the tract's `gross_acres`, rounded half-up to whole dollars. The `APPRAISAL` variant adjusts each comparable's base figure by two factors before averaging: a tillable factor of 0.85 plus 0.30 times the tract's tillable share — its `tillable_acres` divided by its `gross_acres` — and a recency factor of 1.0 when the comparable's `sale_date` falls on or after the instant twelve months before the logical clock, and 0.97 otherwise. The adjusted figures are averaged unweighted and multiplied by the tract's `gross_acres`, again rounded half-up to whole dollars. For identical comparable data the two variants generally produce different values; both are legitimate, and the packaging reserve-floor check of §3.2 always uses the `PROVISIONAL` variant implicitly, once per tract. The valuation response reports the `tract_id`, the `variant` used, the size of the comparable set as `comparable_count`, the mean per-acre figure as `value_per_acre` rounded half-up to 2 decimal places, and `estimated_value` as a whole-dollar integer.

### 3.4. Lease Disclosures, Rights Dispositions, and Marketing

Two per-tract declarations must be settled while a listing is still being assembled, because they constrain everything downstream.

A lease disclosure records a tenant farmer's holdover rights on a tract. The listing's agent creates it with `tract_id`, `tenant_name`, `lease_start_date`, `lease_end_date`, and a positive `annual_rent`; creation is permitted only while the listing is `DRAFT` or `PACKAGED` — later attempts fail the listing state gate with `ERR_INVALID_LISTING_STATE` — and each tract supports at most one disclosure, with a second attempt rejected as `ERR_DUPLICATE_RECORD`. The disclosure begins in `DISCLOSED`. Possession of a disclosed tract may transfer no earlier than the day after `lease_end_date`, a constraint that resurfaces as a rent credit at settlement time (§3.8). After an award, the winning buyer acknowledges each in-scope disclosure: the caller must be the buyer of a `CONFIRMED_WINNER` bid whose scope contains the disclosure's tract, else `ERR_FORBIDDEN`, and the disclosure must still be `DISCLOSED`, else `ERR_INVALID_DISCLOSURE_STATE`. Acknowledgement moves it to `ACKNOWLEDGED` and records the caller in `acknowledged_by_buyer_id`. Two later events act on acknowledged disclosures: if the forfeiture cascade voids the acknowledging buyer's winning bid, the disclosure falls back from `ACKNOWLEDGED` to `DISCLOSED` and `acknowledged_by_buyer_id` is cleared to null; and when closing disbursement completes, each in-scope `ACKNOWLEDGED` disclosure moves to `POSSESSION_TRANSFERRED`.

A rights disposition declares what happens to subsurface and wind estate on a tract, via `mineral_rights` — `CONVEYED`, `RESERVED`, or `PARTIALLY_CONVEYED` — and `wind_rights` — `CONVEYED`, `RESERVED`, or `LEASED_TO_THIRD_PARTY`. The listing's agent creates it for a `tract_id` while the listing is `DRAFT`, `PACKAGED`, or `MARKETED`; one disposition per tract, with duplicates rejected as `ERR_DUPLICATE_RECORD`. While any auction of the listing is `OPEN` or `EXTENDED`, rights creation is blocked outright with `ERR_RIGHTS_LOCKED`. A disposition starts `DECLARED`; when the listing's first auction opens, every tract's disposition moves from `DECLARED` to `LOCKED`, and it stays `LOCKED` while any auction of the listing is `OPEN`, `EXTENDED`, or `AWARDED`. Rights return from `LOCKED` to `DECLARED` when an auction ends in `NO_SALE` or `CANCELLED` and no active auction of the listing remains.

Marketing moves the listing from `PACKAGED` to `MARKETED`. The caller must be the listing's agent, and every tract must carry at least one `DECLARED` rights disposition — a tract without one fails the attempt with `ERR_RIGHTS_NOT_DECLARED`. On success every tract moves from `REGISTERED` to `OFFERED`, and the listing's `version` increments.

### 3.5. Auction Scheduling, Opening, and the Soft-Close Window

With a listing `MARKETED`, its agent schedules auctions. Creation accepts a `listing_id`, a `method` of `LIVE`, `ONLINE`, or `SEALED_BID`, a `scheduled_start`, a `scheduled_end`, and optionally `soft_close_window_minutes` and `extension_minutes`, each defaulting to 5 and meaningful only for `ONLINE` auctions. The listing must be `MARKETED` or `AUCTION_SCHEDULED`, else `ERR_INVALID_LISTING_STATE`; the new auction's `agent_id` is denormalized from the listing at creation and feeds the auctioneer conflict check below.

Three temporal checks guard scheduling, evaluated in this order. First, window well-formedness: `scheduled_end` must be strictly after `scheduled_start`, the window must last at least sixty minutes, and `scheduled_start` must be no earlier than twenty-four hours after the current logical instant — any violation is `ERR_AUCTION_WINDOW_INVALID`. Second, per-listing overlap: the windows of this listing's auctions in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD` must be disjoint half-open intervals, so a new window that starts exactly when an existing window ends is permitted adjacency, while true overlap is rejected with `ERR_LISTING_AUCTION_OVERLAP`. Third, the auctioneer buffer, which compares only auctions of *other* listings sharing the same agent — same-listing spacing is governed solely by the overlap rule: against any such auction in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD`, the new window is rejected with `ERR_AUCTIONEER_SCHEDULE_CONFLICT` when it begins before the moment two hours after the existing window's end and simultaneously ends after the moment two hours before the existing window's start; because both comparisons are strict, a gap of exactly two hours on either side passes.

The first auction scheduled for a `MARKETED` listing moves the listing to `AUCTION_SCHEDULED` and increments its `version`; further auctions may be scheduled while the listing remains `AUCTION_SCHEDULED` without changing its status. A new auction begins `SCHEDULED` with `effective_end` equal to `scheduled_end`, `extension_count` at zero, and `awarded_total` null until an award is made.

Opening moves a `SCHEDULED` auction to `OPEN`. The caller must be the listing's agent, and the logical clock must have reached `scheduled_start` without yet reaching `scheduled_end` — opening outside the window is `ERR_AUCTION_WINDOW_INVALID`, and opening from any state other than `SCHEDULED` is `ERR_INVALID_AUCTION_STATE`. Three side effects fire together: the rights disposition of every tract of the listing moves from `DECLARED` to `LOCKED`; any tracts left `UNSOLD` by a prior partial award return to `OFFERED`; and the auction's `version` increments.

`ONLINE` auctions carry a soft close. A bid accepted while the logical clock sits within `soft_close_window_minutes` before `effective_end` — that is, inside the final stretch of the window — extends the auction: `effective_end` gains `extension_minutes`, `extension_count` increases by one, and the auction moves from `OPEN` to `EXTENDED`, or from `EXTENDED` to `EXTENDED` again when a further bid lands inside the current soft-close window. Regardless of method, bids are accepted only while the logical clock is strictly before `effective_end`.

When the logical clock reaches `effective_end`, the close sweep runs. With at least one bid standing in `PLACED` or `SEALED`, the auction — whether `OPEN` or `EXTENDED` — moves to `CLOSED_PENDING_AWARD`, and for a `SEALED_BID` auction every `SEALED` bid is revealed, moving to `REVEALED` with amounts becoming visible. With zero bids standing, the auction — again from either `OPEN` or `EXTENDED` — moves to `NO_SALE`, and when no other auction of the listing remains in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD`, the listing falls back from `AUCTION_SCHEDULED` to `MARKETED` with its `version` incremented, ready for a fresh scheduling round; the listing's auctions remain listable per listing throughout.

### 3.6. Bidding: Eligibility, Scope, and Price Floors

Only a `Buyer` places bids; the bid's `buyer_id` is set from the caller's `X-User-ID`. The placement payload carries the target `auction_id`, the `amount`, the `tract_ids` forming the bid's scope, and the `expected_auction_version` required by §2.7. Placement checks fire in a fixed order, so a request failing several of them surfaces the earliest: the auction must be `OPEN` or `EXTENDED`, else `ERR_AUCTION_NOT_OPEN`; the version check rejects stale views with `ERR_STALE_AUCTION_VERSION`; the bidder's `qualification_status` must be `QUALIFIED` with the logical clock strictly before `qualification_expires_at`, else `ERR_BUYER_NOT_QUALIFIED`; then scope, then sealed-bid uniqueness, then price economics, and finally proof of funds.

Scope rules bind the `tract_ids` array. It must be non-empty, every referenced tract must belong to the auction's listing, and every referenced tract must currently be `OFFERED`; beyond that, the listing's strategy shapes the scope — a `WHOLE` listing accepts only a scope covering all of its tracts, a `SPLIT` listing requires exactly one tract per bid, and a `COMBINATION` listing permits any subset, where a single-element scope is an individual tract bid and a longer scope is a combination bid. Every scope violation is `ERR_TRACT_SCOPE_INVALID`.

Price economics split by method and scope shape. A bid's `amount` must be positive. For `LIVE` and `ONLINE` auctions, a bid covering a single tract — or covering all tracts of a `WHOLE` listing — is measured against the current high for that exact scope: the highest `amount` among `PLACED` bids whose `tract_ids` set is identical, or zero when none exists. When a current high exists, the new amount must be at least the current high plus a tiered increment determined by that high: $1,000 when the high is below $100,000; $2,500 when it is at least $100,000 and below $500,000; $5,000 when it is at least $500,000 and below $1,000,000; and $10,000 when it is $1,000,000 or more. The exact boundary is accepted — an amount precisely equal to the high plus its increment stands — and anything less is rejected with `ERR_BID_BELOW_INCREMENT`. When no current high exists, the amount must instead meet the sum of `min_price` across the scope, else `ERR_BID_BELOW_MINIMUM`. Combination bids on `COMBINATION` listings face a premium rule: the amount must be at least the greater of two figures — the sum of the current per-tract highs across the scope, taken only from bids whose scope is exactly that single tract (a tract with no such bid contributes zero), increased by five percent and rounded half-up to 2 decimal places; and the sum of the scope's `min_price` values. A combination bid under that bar is rejected with `ERR_BID_BELOW_MINIMUM`. Finally, regardless of method, the `amount` must not exceed the buyer's `proof_of_funds_amount`, else `ERR_PROOF_OF_FUNDS_INSUFFICIENT`.

`SEALED_BID` auctions relax the economics and harden the confidentiality. No increment check applies; the amount need only meet the sum of `min_price` across the scope, failing which the rejection is `ERR_BID_BELOW_MINIMUM`. Each buyer may place at most one bid per sealed auction — a second is `ERR_DUPLICATE_RECORD`. A bid on a sealed auction begins `SEALED`, whereas `LIVE` and `ONLINE` bids begin `PLACED`; and a `SEALED` bid's `amount` is hidden — returned as null on both individual bid reads and bid listings — until the close sweep reveals it as `REVEALED`.

Acceptance ripples. On `LIVE` and `ONLINE` auctions, when a later bid with an identical single-tract scope and a higher amount is accepted, the previous `PLACED` high bid for that scope moves to `OUTBID`. An `ONLINE` bid accepted inside the soft-close window fires the extension of §3.5. And every accepted bid increments the auction's `version`, which is what makes the optimistic concurrency check meaningful.

Bid visibility follows ownership. A `Buyer` may read only its own bids, and the bid listing surface — filterable by `auction_id`, `buyer_id`, and `status` with the usual `limit` and `offset` — is restricted to `BrokerAgent` and `PlatformAdmin`; buyers are not permitted there at all.

### 3.7. Award, Earnest Money, and the Forfeiture Cascade

An auction in `CLOSED_PENDING_AWARD` has two exits, both reserved to the listing's agent.

The no-sale exit moves the auction to `NO_SALE`: every bid still `PLACED` or `REVEALED` is voided to `VOIDED`; the listing falls back from `AUCTION_SCHEDULED` to `MARKETED` when no other auction of the listing remains in `SCHEDULED`, `OPEN`, `EXTENDED`, or `CLOSED_PENDING_AWARD`; rights dispositions unlock from `LOCKED` to `DECLARED` under that same no-active-auction condition; and the auction's `version` increments.

The award exit runs the winner-selection algorithm. Eligibility depends on method: for `LIVE` and `ONLINE` auctions the eligible pool is bids in `PLACED`; for `SEALED_BID` auctions it is bids in `REVEALED`. An empty pool fails the award with `ERR_INVALID_AUCTION_STATE`. The selection proceeds deterministically, and entity identifiers are never used for ranking or tie-breaking — only amounts and creation timestamps. First, per-tract individual highs are established: for each tract, the eligible bid with the highest `amount` whose `tract_ids` is exactly that tract alone, ties broken toward the earliest `created_at`. Second, combination bids — eligible bids whose scope spans more than one tract — are considered in descending `amount` order, ties again broken toward the earliest `created_at`; a combination wins every tract in its scope when all of those tracts are still `OFFERED` and none has already been assigned to an earlier-winning combination, and its amount is at least the greater of the five-percent premium threshold over the sum of those tracts' individual highs (a tract with no individual high contributing zero, the threshold rounded half-up to 2 decimal places) and the sum of those tracts' `min_price` values. Third, every remaining `OFFERED` tract that has an individual high bid is won by that bid. The `awarded_total` is the sum of the winning bids' amounts, and the award stands only if it meets the listing's `reserve_price_total` — a shortfall rejects the whole award with `ERR_RESERVE_NOT_MET`. A successful award moves winning bids to `CONFIRMED_WINNER` and every other `PLACED` or `REVEALED` bid to `LOST`; tracts inside winning scopes move from `OFFERED` to `SOLD`, while `OFFERED` tracts outside every winning scope move to `UNSOLD`. When every tract of the listing is `SOLD` after the award, the listing moves from `AUCTION_SCHEDULED` to `UNDER_CONTRACT` — a partial award instead leaves the listing `AUCTION_SCHEDULED` for a later round. The auction's `version` increments.

Each winning bid immediately spawns an earnest-money deposit carrying the winning `bid_id` and a denormalized `buyer_id` copied from the bid for escrow reporting. The `amount_due` is three percent of the winning bid's amount, rounded half-up to 2 decimal places, but never less than a $10,000 floor; the `due_at` deadline is exactly forty-eight hours after the award timestamp; and `amount_received`, `amount_refunded`, `amount_forfeited`, and `amount_applied` all start at zero on a `PENDING` deposit.

Escrow payments are recorded by the agent of the listing behind the deposit's bid — any other caller, `ERR_FORBIDDEN` — and only while the deposit is `PENDING` or `LATE`; recording against any other state is `ERR_INVALID_DEPOSIT_STATE`. Each recorded payment carries an `amount` and accumulates into `amount_received`. When the cumulative received reaches at least `amount_due`, timing decides the state: if the logical clock is at or before `due_at` the deposit moves from `PENDING` to `RECEIVED`; if the payment completes the amount after `due_at`, the deposit instead becomes `LATE`. The clock sweep independently moves a still-underpaid deposit from `PENDING` to `LATE` once the clock passes `due_at`. Once `LATE`, a deposit never returns to `RECEIVED` — further payments continue to accumulate, and seller-side acceptance of late funds is expressed through verification.

Verification is the back office's exclusive act, and the segregation of duties is deliberate: payments are recorded by a `BrokerAgent`, but verification is `PlatformAdmin`-only, so the agent who recorded funds can never clear them. Verification moves a deposit from `RECEIVED` to `VERIFIED`, or from `LATE` to `VERIFIED` when late funds are accepted; from any other state it is `ERR_INVALID_DEPOSIT_STATE`.

Forfeiture punishes an empty escrow. When the logical clock passes the deposit's `due_at` by more than a further twenty-four hours of grace while the deposit is still `PENDING`, the sweep moves it to `FORFEITED`; the same sweep moves a `LATE` deposit to `FORFEITED` on the identical condition. In both cases `amount_forfeited` is set to whatever `amount_received` had accumulated, and the same five-hop unwind cascade fires: the buyer is disqualified — moving to `DISQUALIFIED` whether currently `QUALIFIED` or `EXPIRED`; that buyer's `CONFIRMED_WINNER` bid is voided to `VOIDED`; the auction hops from `AWARDED` to `NO_SALE`; the listing falls from `UNDER_CONTRACT` back to `MARKETED` with its `version` incremented; and its `SOLD` tracts return to `OFFERED`. Disclosures the disqualified buyer had acknowledged revert to `DISCLOSED` as described in §3.4.

Deposit reads follow the same ownership discipline as bids: a `Buyer` sees only deposits attached to its own bids, while agents and admins see any; listing a bid's deposits returns zero or one element, since a winning bid spawns exactly one. Only `VERIFIED` deposits can underlie a closing — the refund path runs from `VERIFIED` to `REFUNDED`, and `RECEIVED` or `LATE` deposits are never refunded; past the grace deadline they forfeit instead.

### 3.8. Closing Coordination, Settlement Statements, and Disbursement

An awarded auction converges on a closing package, created by the listing's agent with `auction_id`, a `target_closing_date`, and a `payoff_amount` no less than zero representing the seller's mortgage and lien payoff. The gates run in a fixed order: the auction must be `AWARDED`, else `ERR_INVALID_AUCTION_STATE`; the earnest-money deposit behind every winning bid must be `VERIFIED`, else `ERR_INVALID_DEPOSIT_STATE`; every lease disclosure of every tract in the winning scope must be `ACKNOWLEDGED`, else `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`; the `target_closing_date` must fall strictly after the logical clock, else `ERR_CLOSING_DATE_PAST`; and an auction supports exactly one closing package, a second attempt failing with `ERR_DUPLICATE_RECORD`. A new closing initializes three independent parallel axes — `title_status` at `NOT_ORDERED`, `survey_status` at `NOT_ORDERED`, `funding_status` at `UNFUNDED` — with `overall_status` derived at `INITIATED`.

Coordination advances one axis at a time. Each track event carries an `axis` of `TITLE`, `SURVEY`, or `FUNDING`, an `event` naming the transition, and optionally `seller_consent`. Duty is split: `TITLE` and `SURVEY` events are `BrokerAgent`-only, while `FUNDING` events are `PlatformAdmin`-only — a broker attempting a funding event is rejected with `ERR_FORBIDDEN`. The title axis walks `NOT_ORDERED` to `ORDERED` to `COMMITMENT_RECEIVED` to `CLEARED`, with `EXCEPTION_RAISED` reachable from either `ORDERED` or `COMMITMENT_RECEIVED` and a `CURE` event returning `EXCEPTION_RAISED` to `COMMITMENT_RECEIVED`. The survey axis walks `NOT_ORDERED` to `ORDERED` to `COMPLETED`, or directly from `NOT_ORDERED` to `WAIVED` via a `WAIVE` event that requires `seller_consent` to be true — a waiver without it fails as `ERR_VALIDATION`. The funding axis walks `UNFUNDED` to `FUNDS_RECEIVED` to `DISBURSED`.

The `event` string is matched against the axis's current state, and each transition accepts a fixed set of event strings — a verb form and, for most transitions, the target status itself as an alias. On the title axis: from `NOT_ORDERED`, `ORDER` or `ORDER_COMMITMENT` moves to `ORDERED`; from `ORDERED`, `RECEIVE_COMMITMENT` or `COMMITMENT_RECEIVED` moves to `COMMITMENT_RECEIVED`, and `RAISE_EXCEPTION` or `EXCEPTION_RAISED` moves to `EXCEPTION_RAISED`; from `COMMITMENT_RECEIVED`, `CLEAR` or `CLEARED` moves to `CLEARED`, and `RAISE_EXCEPTION` or `EXCEPTION_RAISED` moves to `EXCEPTION_RAISED`; from `EXCEPTION_RAISED`, `CURE` or `CURE_EXCEPTION` returns to `COMMITMENT_RECEIVED`. On the survey axis: from `NOT_ORDERED`, `ORDER` moves to `ORDERED` and `WAIVE` moves to `WAIVED`; from `ORDERED`, `COMPLETE` or `COMPLETED` moves to `COMPLETED`. On the funding axis: from `UNFUNDED`, `RECEIVE_FUNDS` or `FUNDS_RECEIVED` moves to `FUNDS_RECEIVED`; from `FUNDS_RECEIVED`, `DISBURSE` moves to `DISBURSED`. An event string not accepted for the axis's current state, or any track event on a `CLOSED` or `TERMINATED` closing, is rejected with `ERR_INVALID_CLOSING_STATE`.

The derived `overall_status` recomputes after every event. It leaves `INITIATED` for `COORDINATION` the moment any axis departs its initial value; it reaches `READY_TO_CLOSE` when `title_status` is `CLEARED` and `survey_status` is either `COMPLETED` or `WAIVED`; and it settles at `CLOSED` when the funding axis reaches `DISBURSED`.

Settlement statements price the closing, and are created with a `closing_id` and a `variant` of `PROVISIONAL` or `FINAL`. A `PROVISIONAL` statement may be created at any point before the closing is `CLOSED` — creating any statement on a `CLOSED` or `TERMINATED` closing is `ERR_INVALID_CLOSING_STATE` — while a `FINAL` statement requires the closing to be `READY_TO_CLOSE`, failing which the rejection is also `ERR_INVALID_CLOSING_STATE`, and each closing admits exactly one `FINAL`, a second failing with `ERR_DUPLICATE_RECORD`. The `variant` is the immutable input chosen at creation; the statement's own `status` mirrors the lifecycle, starting at `PROVISIONAL` or `FINAL` to match. Creating a fresh `PROVISIONAL` supersedes the prior `PROVISIONAL` for the same closing, moving it to `SUPERSEDED`; creating the `FINAL` likewise supersedes whichever `PROVISIONAL` stands.

Every statement computes the same pinned pipeline, in this order. First `gross_price` is taken from the closing's auction `awarded_total`. Second, `commission_amount` follows a marginal tier schedule on the gross — 6.0 percent of the first $250,000, 4.5 percent of the portion above $250,000 up to $750,000, 3.0 percent of the portion above $750,000 up to $2,000,000, and 1.5 percent of any portion above $2,000,000 — summed into a base commission; an over-appraisal kicker of 0.5 percent of the gross is added when the gross is at least 110 percent of the sum of `APPRAISAL` valuations across the winning-scope tracts at statement creation, the exact boundary included, and zero otherwise; and the commission is the greater of a $7,500 floor and the base plus kicker, with only this final figure rounded half-up to 2 decimal places. Tiers are evaluated first, then the kicker — which depends on the gross and the appraisals only, never on the net — then the floor. Third, `allocated_seller_costs` and `tract_allocations` split by variant, detailed below. Fourth, `rent_credit` is zero for `PROVISIONAL` and computed for `FINAL`. Fifth, `seller_net` is the `gross_price` minus the `commission_amount`, minus the `allocated_seller_costs`, minus the `payoff_amount` — copied from the closing package at computation time — minus the `rent_credit`.

Seller closing costs are built from a fixed recipe: a $1,500 flat title fee, plus 0.2 percent of the gross, plus $1,200 per tract in the winning scope, plus the seller's half of a 0.1 percent escrow charge on the gross — the total rounded half-up to 2 decimal places. A `FINAL` statement allocates that total across the scope's tracts by appraisal weight: each tract's weight is its `APPRAISAL` valuation divided by the sum of appraisals across the scope; each tract's `share` is the total multiplied by its weight, rounded half-up to 2 decimal places per tract first, in pinned order; and the residual — which may be zero, or positive or negative cents — is added to the tract with the highest `tract_number`, so the allocated shares sum to the total exactly; the allocation is never rounded as a sum. The `FINAL` statement exposes these as `tract_allocations`, a list of per-tract entries each naming a `tract_id` and its `share`. A `PROVISIONAL` statement performs no per-tract allocation at all: its `tract_allocations` is null and its `allocated_seller_costs` is a flat estimate of 0.5 percent of the gross, rounded half-up to 2 decimal places — so the two variants produce different nets on identical closing data.

The `FINAL` rent credit compensates the buyer for possession the seller holds back. For each in-scope tract carrying a lease disclosure, of any status, the possession date is the later of the `target_closing_date` and the day after `lease_end_date`. When that possession date falls after the `target_closing_date`, the credit counts the calendar days from the `target_closing_date` to the possession date — exclusive of the start, inclusive of the end; the daily rent is the disclosure's `annual_rent` divided by 365, rounded half-up to 2 decimal places before any multiplication; and the tract's credit is that daily rent times the day count, rounded half-up to 2 decimal places. The statement's `rent_credit` is the sum across tracts with disclosures, or zero when none exist, and it reduces `seller_net`.

Disbursement is the point of no return, driven by the admin-only funding event that takes `funding_status` to `DISBURSED`. It is permitted only from `READY_TO_CLOSE`, and only when a `FINAL` statement exists for the closing — both failures are `ERR_INVALID_CLOSING_STATE`. The disbursement cascade settles the whole chain at once: the listing moves from `UNDER_CONTRACT` to `CLOSED` with its `version` incremented; every `VERIFIED` deposit moves to `APPLIED_TO_CLOSING` with `amount_applied` set to its `amount_received`; the `FINAL` statement moves to `PAID`; and each in-scope `ACKNOWLEDGED` disclosure moves to `POSSESSION_TRANSFERRED`.

Termination unwinds instead. The listing's agent may terminate a closing from `INITIATED`, `COORDINATION`, or `READY_TO_CLOSE`, moving it to `TERMINATED`; terminating a `CLOSED` closing is rejected with `ERR_INVALID_CLOSING_STATE`. The termination cascade is identical from all three source states: the `VERIFIED` deposit moves to `REFUNDED` with `amount_refunded` set to its `amount_received`; the winning bid moves from `CONFIRMED_WINNER` to `VOIDED`; the auction hops from `AWARDED` to `NO_SALE`; the listing falls from `UNDER_CONTRACT` to `MARKETED`; its `SOLD` tracts return to `OFFERED`; and both `PROVISIONAL` and `FINAL` statements of the closing move to `SUPERSEDED`.

Closing packages and their statements are readable by the listing's agent, its seller, and admins; an auction's closings list returns zero or one element, since an auction admits at most one closing.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource — including all action-style state transitions — return `200 OK`. The table below is a routing summary only; request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and run all time sweeps | PlatformAdmin |
| POST | `/api/sellers` | Create a seller | PlatformAdmin |
| POST | `/api/agents` | Create a broker agent | PlatformAdmin |
| POST | `/api/buyers` | Create a buyer, starting `UNVERIFIED` | PlatformAdmin |
| GET | `/api/buyers/{id}` | Read a buyer; `Buyer` reads only its own id | PlatformAdmin, BrokerAgent, Buyer |
| POST | `/api/buyers/{id}/qualify` | Qualify a buyer and set the qualification expiry | PlatformAdmin |
| POST | `/api/listings` | Create a listing in `DRAFT`; agent taken from caller | BrokerAgent |
| GET | `/api/listings/{id}` | Read a listing | Seller, BrokerAgent, Buyer, PlatformAdmin |
| GET | `/api/listings` | List and filter listings | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/tracts` | Add a tract to a `DRAFT` listing (OCC on the listing version) | BrokerAgent |
| GET | `/api/tracts/{id}` | Read a tract | Seller, BrokerAgent, Buyer, PlatformAdmin |
| GET | `/api/listings/{id}/tracts` | List tracts of a listing | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/listings/{id}/package` | Package a `DRAFT` listing; pins strategy, enforces acreage equality and the reserve floor | BrokerAgent |
| POST | `/api/listings/{id}/market` | Market a `PACKAGED` listing; tracts become `OFFERED` | BrokerAgent |
| POST | `/api/listings/{id}/withdraw` | Withdraw a pre-contract listing with the full cascade | Seller, BrokerAgent |
| POST | `/api/comparables` | Create an immutable comparable sale record | PlatformAdmin |
| GET | `/api/tracts/{id}/valuation` | Computed valuation read for a tract, by variant | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/auctions` | Schedule an auction for a `MARKETED` or `AUCTION_SCHEDULED` listing | BrokerAgent |
| GET | `/api/auctions/{id}` | Read an auction | Seller, BrokerAgent, Buyer, PlatformAdmin |
| GET | `/api/listings/{id}/auctions` | List auctions of a listing | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/auctions/{id}/open` | Open a `SCHEDULED` auction inside its window; locks rights, re-offers unsold tracts | BrokerAgent |
| POST | `/api/auctions/{id}/award` | Award a `CLOSED_PENDING_AWARD` auction; runs winner selection and creates deposits | BrokerAgent |
| POST | `/api/auctions/{id}/no-sale` | Declare no-sale on a `CLOSED_PENDING_AWARD` auction; voids bids | BrokerAgent |
| POST | `/api/bids` | Place a bid (OCC on the auction version) | Buyer |
| GET | `/api/bids/{id}` | Read a bid; `Buyer` reads only own bids; sealed amounts are null until `REVEALED` | BrokerAgent, PlatformAdmin, Buyer |
| GET | `/api/bids` | List and filter bids | BrokerAgent, PlatformAdmin |
| POST | `/api/deposits/{id}/record-payment` | Record an escrow payment against a deposit | BrokerAgent |
| POST | `/api/deposits/{id}/verify` | Verify cleared funds on a deposit | PlatformAdmin |
| GET | `/api/deposits/{id}` | Read a deposit; `Buyer` reads only deposits of own bids | BrokerAgent, PlatformAdmin, Buyer |
| GET | `/api/bids/{id}/deposits` | List the deposit of a bid (zero or one element) | BrokerAgent, PlatformAdmin, Buyer |
| POST | `/api/disclosures` | Create a lease disclosure for a tract | BrokerAgent |
| POST | `/api/disclosures/{id}/acknowledge` | Winning buyer acknowledges a disclosure | Buyer |
| GET | `/api/tracts/{id}/disclosures` | List disclosures of a tract | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/rights` | Declare mineral and wind rights for a tract | BrokerAgent |
| GET | `/api/tracts/{id}/rights` | List rights dispositions of a tract | Seller, BrokerAgent, Buyer, PlatformAdmin |
| POST | `/api/closings` | Initiate a closing for an `AWARDED` auction | BrokerAgent |
| GET | `/api/closings/{id}` | Read a closing package | BrokerAgent, Seller, PlatformAdmin |
| GET | `/api/auctions/{id}/closings` | List closings of an auction (zero or one element) | BrokerAgent, Seller, PlatformAdmin |
| POST | `/api/closings/{id}/track-events` | Advance one closing axis (title, survey, or funding) | BrokerAgent, PlatformAdmin |
| POST | `/api/statements` | Create a settlement statement for a closing | BrokerAgent |
| GET | `/api/closings/{id}/statements` | List statements of a closing | BrokerAgent, Seller, PlatformAdmin |
| POST | `/api/closings/{id}/terminate` | Terminate a non-`CLOSED` closing with the full unwind cascade | BrokerAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_LISTING_STATE` | 409 |
| `ERR_INVALID_AUCTION_STATE` | 409 |
| `ERR_AUCTION_NOT_OPEN` | 409 |
| `ERR_INVALID_DEPOSIT_STATE` | 409 |
| `ERR_INVALID_CLOSING_STATE` | 409 |
| `ERR_INVALID_DISCLOSURE_STATE` | 409 |
| `ERR_RIGHTS_LOCKED` | 409 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_STALE_AUCTION_VERSION` | 412 |
| `ERR_BUYER_NOT_QUALIFIED` | 422 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 422 |
| `ERR_RIGHTS_NOT_DECLARED` | 422 |
| `ERR_AUCTION_WINDOW_INVALID` | 422 |
| `ERR_LISTING_AUCTION_OVERLAP` | 409 |
| `ERR_AUCTIONEER_SCHEDULE_CONFLICT` | 409 |
| `ERR_CLOSING_DATE_PAST` | 422 |
| `ERR_ACREAGE_MISMATCH` | 422 |
| `ERR_TRACT_SCOPE_INVALID` | 422 |
| `ERR_DUPLICATE_RECORD` | 409 |
| `ERR_BID_BELOW_INCREMENT` | 422 |
| `ERR_BID_BELOW_MINIMUM` | 422 |
| `ERR_PROOF_OF_FUNDS_INSUFFICIENT` | 422 |
| `ERR_RESERVE_BELOW_FLOOR` | 422 |
| `ERR_RESERVE_NOT_MET` | 422 |
| `ERR_NO_COMPARABLES` | 422 |
