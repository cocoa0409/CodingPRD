# Estate-Liquidation Auction API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Estate-Liquidation Auction API, a back-office and public-facing platform in the spirit of services such as MaxSold and EstateSales.net. The platform manages the full arc of an estate sale: an estate-house operator intakes a consignment, catalogs and photographs individual lots, schedules an online auction, and opens bidding to a registered public. Once bidding closes, the system determines which lots sold, assembles per-buyer invoices, collects payment, coordinates pickup windows, and finally settles the seller's payout net of the house commission. Lots that never found a buyer are donated or recycled during a cleanout phase.

The domain is defined by a handful of tightly coupled money and inventory invariants that must hold at every step. A single lot flows through a branching lifecycle that can end in a sale, a pass, a donation, or — if a buyer wins a dispute after the fact — a reversal that unwinds a completed sale and re-derives the seller's payout. Bidding is resolved with optimistic concurrency so that two buyers reading the same price cannot both believe they lead. Because the platform is the system of record for real money owed and paid, every derived figure — a lot's current high bid, a buyer's outstanding balance, an estate's gross sales — must remain reconciled with the events that produced it. This document describes those rules in full so that an implementer can reproduce them exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `Operator`, `Buyer`, and `Anonymous`. When the headers required for an operation are missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

An `Operator` is estate-house staff. The `Operator` role is an opaque operator identifier that is not tied to any persisted entity: when `X-User-Role` is `Operator`, `X-User-ID` names a staff member, and the server may record it but does not compare it to any entity's `id`. Operators manage estates, lots, photos, and pickup windows; drive the auction lifecycle; verify buyers; record pickups; and adjudicate disputes.

A `Buyer` is a registered bidder and purchaser, and this role is entity-backed. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer` entity; ownership checks on any resource that references a buyer compare that resource's buyer foreign key to `X-User-ID`. Concretely, a buyer may act only on bids, orders, and disputes that belong to them: a mismatch between `X-User-ID` and the `buyer_id` of a bid or order (or the `buyer_id` of the order behind a dispute) is rejected with `ERR_CROSS_OWNER` (HTTP 403).

The `Anonymous` role represents an unauthenticated public visitor and is likewise opaque, tied to no persisted entity. An anonymous visitor may self-register as a buyer and may perform the public catalog reads (fetching an estate, listing an estate's lots and pickup windows, fetching a lot and its photos, and reading donation records). Self-registration is the one write an anonymous visitor may perform.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound but a minimum of 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is a validation failure (`ERR_VALIDATION`, HTTP 400).

Unless a specific endpoint says otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` reflects the full number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Append-Only Records

Most primary resources — `Estate`, `Lot`, `Buyer`, `Order`, `PickupWindow`, and `Dispute` — carry a common set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp (ISO 8601 UTC, three fractional digits) fixed at creation; an `updated_at` timestamp in the same format that is refreshed on every mutation; and an integer `version` that starts at its initial value and increments by one on each mutation, supporting optimistic concurrency control.

Certain records are append-only condition or ledger entries and deliberately omit `updated_at` and `version`: `Photo`, `Bid`, `Payment`, and `Donation` each carry only an `id` and a `created_at`. They are never edited after creation, so no modification timestamp or version counter exists for them.

### 2.5. Monetary Values, Basis Points, and Rounding

All monetary amounts are stored as integer cents; there is no sub-cent representation, and bid and increment arithmetic involves no rounding because every amount is already a whole number of cents. Rates that must be applied to money — the house commission, the buyer's premium, and sales tax — are expressed in basis points, where one basis point is one ten-thousandth. To apply a basis-point rate to a cent amount, multiply the amount by the rate and divide by 10000. Whenever such a product is not a whole number of cents, it is rounded to the nearest whole cent using round-half-up (a fractional remainder of exactly one-half rounds upward). Commission, buyer's premium, and sales tax are each the rounded result of one such computation, as detailed in §3.

### 2.6. The Logical Clock and Temporal Windowing

The platform does not read wall-clock time. Instead it keeps a logical clock that an operator sets explicitly through an administrative test-driving capability that accepts a single `to_iso8601` instant and moves the clock to it. At startup, before any such call, the clock reads exactly `2026-03-01T00:00:00Z` and never falls back to real time. This logical "now" governs the two temporal features of the domain: the auction soft-close extension, and any time comparison a pickup window requires.

Pickup windows are treated as time intervals and are compared for overlap in two distinct ways depending on context. When a new window is created for an estate, its interval is treated as half-open — that is, spanning from its start up to but not including its end — so that two windows which merely touch end-to-start are considered non-overlapping. When a buyer books a window against the windows they already hold, the comparison is closed on both ends, so windows that merely touch end-to-start do collide. Both distinctions are spelled out precisely where they apply in §3.

### 2.7. Optimistic Concurrency on Bidding

Bid placement is guarded by optimistic concurrency control keyed on the lot. A request to place a bid must carry `expected_lot_version`, a non-optional field holding the `version` of the target `Lot` that the client last observed. When a bid is accepted, it supersedes the lot's standing price and increments `Lot.version` by one; a later bid that still carries the earlier `expected_lot_version` is therefore working from a stale view of the price. If `expected_lot_version` does not match the lot's current `version` at the moment the request is processed, the placement is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from bidding against a price it has not actually seen. Bid placement is the only operation that takes a version field; no other endpoint accepts one.

### 2.8. Cascading Consistency and Derived-Field Reconciliation

Many operations in this domain mutate more than one resource, and every such cascade is applied atomically within the request that triggers it. Derived figures are never left stale: a lot's `current_bid_cents`, `high_bidder_id`, `bid_count`, and `photo_count`; an order's `subtotal_cents`, `buyer_premium_cents`, `sales_tax_cents`, `total_cents`, `amount_paid_cents`, and `lot_ids`; a buyer's `gross_owed_cents`, `net_owed_cents`, and `no_show_strikes`; a pickup window's `booked_count`; and an estate's `lot_count`, `provisional_gross_cents`, `gross_sales_cents`, `commission_cents`, and `seller_payout_cents` are all reconciled the moment an event changes their inputs. When one of these mutations touches a resource that carries `version` and `updated_at`, that resource's `updated_at` is refreshed and its `version` is incremented. The estate-close settlement, dispute-driven sale reversals, and pickup no-shows are the most cascade-heavy operations and are detailed in §3.

### 2.9. Nested Resource Retrieval and Reverse-Reachability Reads

The API is a flat collection of peer resources linked by foreign keys; a resource's own path addresses it directly by `id`. Reverse relationships are read in one of two forms. Sub-resource paths list the children owned by a parent — an estate's lots, an estate's pickup windows, a lot's photos, an order's payment ledger. Filtered list paths take optional foreign-key query parameters — bids filtered by `lot_id` or `buyer_id`; orders filtered by `estate_id`, `buyer_id`, or `pickup_window_id`; disputes filtered by `order_id` or `lot_id`; donations filtered by `lot_id` or `estate_id`.

Whenever a path or body references resources by id, those references are validated left-to-right: the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated. A request naming a child under a parent that does not exist fails on the parent first.

### 2.10. Validation Ordering and Error Precedence

When more than one check could fail for a single request, the checks are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the request headers, `ERR_UNAUTHENTICATED` (401); (2) authorization of the acting role for the operation, `ERR_UNAUTHORIZED` (403); (3) structural body validation — required fields present, correct types, valid enum members, and pagination bounds — `ERR_VALIDATION` (400); (4) existence of every referenced resource, `ERR_NOT_FOUND` (404); (5) buyer ownership of the target resource, `ERR_CROSS_OWNER` (403); (6) the estate being in the status its lifecycle action requires; (7) the target resource being in a valid state for the requested transition; (8) the chosen pickup window belonging to the order's estate, `ERR_WINDOW_ESTATE_MISMATCH` (409); (9) the disputed lot being part of the order, `ERR_LOT_NOT_IN_ORDER` (409); (10) pickup-window overlap checks, `ERR_WINDOW_OVERLAP` or `ERR_PICKUP_OVERLAP` (409); (11) the bidding buyer being verified, `ERR_BUYER_NOT_VERIFIED` (409); (12) the acting buyer not being suspended, `ERR_BUYER_SUSPENDED` (409); (13) domain constraints such as the bid meeting the minimum increment or the window having capacity, `ERR_BID_TOO_LOW` or `ERR_WINDOW_FULL` (409); (14) the bidding OCC version match, `ERR_STALE_VERSION` (412); and (15) the payment covering the invoice total, `ERR_INSUFFICIENT_PAYMENT` (402). Earlier checks always mask later ones: a request that both lacks permission and carries a bad body returns the authorization error, not the validation error.

## 3. Business Logic & Workflows

### 3.1. Estate Intake and Lot Cataloging

An operator opens the pipeline by creating an estate consignment. The estate is created with the consignor's `seller_name` and `seller_email` and the scheduled auction window, given by `auction_starts_at` and `auction_ends_at`, where the close time must be strictly after the open time. Three rate and timing parameters are optional: `commission_bps`, the house commission in basis points, defaulting to 3500; `buyer_premium_bps`, the buyer's premium in basis points added to each buyer invoice, defaulting to 1750; and `soft_close_seconds`, the anti-snipe extension window in seconds, defaulting to 300. Each basis-point rate must fall within 0 through 10000 inclusive. A freshly created estate begins in `CATALOGING` status with its `extended_count` at 0 and every money field — `provisional_gross_cents`, `gross_sales_cents`, `commission_cents`, `seller_payout_cents` — and its `lot_count` at 0.

While an estate is in `CATALOGING`, the operator builds its inventory. A lot is created under an estate — the payload names the owning estate via `estate_id`, and that estate must be in `CATALOGING` — together with a `title`, a `description` capturing the condition narrative, a free-text `category`, a `condition_grade` that must be one of `A`, `B`, `C`, or `D`, and a `starting_bid_cents` opening floor that must be at least 1. A `reserve_cents` reserve is optional; when supplied the lot will only sell if its final high bid reaches the reserve, and when omitted it defaults to null, meaning any winning bid takes the lot. A new lot enters `DRAFT` status with `current_bid_cents`, `bid_count`, and `photo_count` at 0, and with `high_bidder_id`, `hammer_price_cents`, and `winning_order_id` all null. Creating a lot raises the owning estate's `lot_count`.

Each lot is documented with condition photos. A photo names the lot it documents via `lot_id` — the lot must be in `DRAFT` or `CATALOGED` — and carries an `image_url`, an optional `caption`, an optional `condition_note`, and an `is_primary` flag marking the primary catalog image, which defaults to false. Attaching a photo increments the lot's `photo_count`.

An operator advances a lot through its early lifecycle by editing it. While a lot is in `DRAFT`, its `title`, `description`, `category`, `condition_grade`, `starting_bid_cents`, and `reserve_cents` may be edited, and the same edit channel drives status changes via a `status` field. Moving a lot from `DRAFT` to `CATALOGED` requires that the owning estate still be in `CATALOGING` and that the lot already have at least one photo (its `photo_count` is 1 or more); otherwise the transition is refused. Moving a lot from `CATALOGED` to `LISTED` likewise requires the estate to be in `CATALOGING`. Any lot- or photo-creation, cataloging, or listing action attempted when the estate is not in `CATALOGING` is rejected with `ERR_ESTATE_NOT_CATALOGING` (409). An illegal lot status change — one that is not a legal transition from the lot's current state — is rejected with `ERR_INVALID_STATE` (409).

### 3.2. Buyer Registration and Verification

A prospective bidder self-registers by supplying a `display_name` and an `email`; anyone unauthenticated may do so. The new buyer enters `REGISTERED` status with `no_show_strikes` at 0 and both ledger figures, `gross_owed_cents` and `net_owed_cents`, at 0. Registration alone does not confer the right to bid. An operator promotes a buyer from `REGISTERED` to `VERIFIED`; only a verified buyer may place bids. A buyer whose conduct crosses the platform's tolerance is moved to `SUSPENDED` automatically, as described in §3.6, and a suspended buyer can neither bid nor pay.

### 3.3. Opening the Auction and Placing Bids

Once at least one lot has been listed, the operator opens bidding, transitioning the estate `CATALOGING → LIVE`. Opening requires the estate to currently be in `CATALOGING` and requires that at least one lot belonging to the estate be in `LISTED`; an attempt to open with no listed lots, or from any status other than `CATALOGING`, is rejected. As a side effect of opening, every lot of that estate that is in `LISTED` transitions `LISTED → SELLING` and has its `current_bid_cents` reset to 0. Only lots in `SELLING` accept bids.

A verified buyer places a bid on a selling lot. The bid names the lot via `lot_id` — which must be in `SELLING`, or the bid is rejected with `ERR_LOT_NOT_SELLING` (409) — the bidding `buyer_id`, which must equal `X-User-ID`, an `amount_cents` of at least 1, and the `expected_lot_version` OCC guard from §2.7. The bidder must be `VERIFIED`; a still-`REGISTERED` bidder is rejected with `ERR_BUYER_NOT_VERIFIED` (409), and a `SUSPENDED` bidder with `ERR_BUYER_SUSPENDED` (409).

Every bid must clear a minimum next amount that rises with the current price. If the lot has no accepted bids yet — its `current_bid_cents` is 0 — the minimum acceptable amount is the lot's `starting_bid_cents`. Otherwise the minimum is the current high amount plus a step determined by that current amount: for a current amount below 2500 cents the step is 100 cents; for a current amount from 2500 up to but not including 10000 cents the step is 250 cents; for a current amount from 10000 up to but not including 50000 cents the step is 1000 cents; and for a current amount of 50000 cents or more the step is 2500 cents. A bid is acceptable when its `amount_cents` is greater than or equal to this minimum next amount — an amount exactly equal to the minimum is valid. A bid below the minimum is rejected with `ERR_BID_TOO_LOW` (409).

An accepted bid becomes the lot's high bid. On acceptance the lot's `current_bid_cents` is set to the bid's `amount_cents`, its `high_bidder_id` becomes the bidding `buyer_id`, this bid's `is_winning` becomes true, and its `status` remains `ACCEPTED`; the lot's `bid_count` increases by one and the lot's `version` increments by one. The bid that previously led, if any, moves `ACCEPTED → OUTBID` and its `is_winning` becomes false. A tie can never occur, because leading requires a strictly higher amount than the standing price: if two equal amounts arrive one after another, the second fails the minimum-increment check. No random tiebreaker participates.

Bidding late in the auction extends the clock. When a bid is accepted while the logical clock reads at or after the moment `soft_close_seconds` before `auction_ends_at` and strictly before `auction_ends_at`, the estate's `auction_ends_at` is pushed forward by `soft_close_seconds` and its `extended_count` increases by one. Bids at or after `auction_ends_at` are still handled normally so long as the estate remains `LIVE`; the auction is ended by an explicit operator action, never by the clock itself. Placing a bid while the estate is not `LIVE` is rejected with `ERR_ESTATE_NOT_LIVE` (409).

### 3.4. Closing the Auction: Settlement Sweep, Order Assembly, and Provisional Gross

The operator closes bidding, transitioning the estate `LIVE → CLOSED`; closing requires the estate to currently be `LIVE`. Closing runs a settlement sweep across every lot still in `SELLING`, and then a cascade of downstream recomputations, all atomically.

For each selling lot the sweep looks at the high amount — the lot's `current_bid_cents`, which is 0 if it drew no accepted bids — and decides whether the reserve is met. The reserve is considered met when the lot's `reserve_cents` is null, or when the high amount is greater than or equal to `reserve_cents`; a bid exactly equal to the reserve sells. A lot with at least one accepted bid (its `bid_count` is 1 or more) whose reserve is met transitions `SELLING → SOLD`; every other selling lot transitions `SELLING → PASSED`. When a lot goes `SELLING → SOLD`, its `hammer_price_cents` is stamped to that high amount and its winning bid's `is_winning` is confirmed true; a passed lot keeps `hammer_price_cents` at null.

Each newly sold lot is then folded into the winning buyer's invoice for this estate. The first time a given buyer wins a lot in the estate, an `Order` is created for that buyer in `UNPAID` payment status and `PENDING` pickup status, carrying its `estate_id` and `buyer_id`; subsequent wins by the same buyer append to that same order. Each sold lot's `id` joins the order's `lot_ids`, its `winning_order_id` is set to that order, and the order's charges are recomputed. The order's `subtotal_cents` is the sum of `hammer_price_cents` over the lots in `lot_ids`. The `buyer_premium_cents` is computed once over that aggregate subtotal: multiply the subtotal by the estate's `buyer_premium_bps`, divide by 10000, and round half-up to a whole cent — the premium is emphatically not computed lot-by-lot and then summed, because rounding the aggregate once can differ by a cent from summing per-lot rounded premiums. The `sales_tax_cents` is then computed once as the subtotal plus the premium, multiplied by the sales-tax rate of 800 basis points, divided by 10000, and rounded half-up to a whole cent. The `total_cents` is the sum of `subtotal_cents`, `buyer_premium_cents`, and `sales_tax_cents`.

Every order touched by the close then refreshes its buyer's ledgers. A buyer's `gross_owed_cents` is the sum of `total_cents` across all of that buyer's orders, while their `net_owed_cents` is the sum of `total_cents` across only those of the buyer's orders whose `payment_status` is `UNPAID`; a paid or refunded order drops out of the net figure but remains in the gross figure.

Finally the close stamps the estate's provisional gross. The `provisional_gross_cents` is the sum of `current_bid_cents` over every lot that carried at least one accepted bid at close — deliberately including lots that were passed because their reserve was not met, since they still attracted a bid. This is an estimate taken before any buyer has paid.

### 3.5. Payment and Buyer Invoices

A buyer settles their invoice by paying it in full while the estate is `CLOSED` or `SETTLED`. Payment is an owner-only action: the acting buyer must own the order. The payload carries `amount_cents`, which must be greater than or equal to the order's `total_cents`; a short payment is rejected with `ERR_INSUFFICIENT_PAYMENT` (402). The paying buyer must not be `SUSPENDED`, or the payment is rejected with `ERR_BUYER_SUSPENDED` (409). Paying an order that is not in `UNPAID` payment status is rejected with `ERR_ORDER_ALREADY_PAID` (409).

A successful payment appends a `CHARGE` line to the order's payment ledger. Each `Payment` names its order via `order_id`, records its `kind` — either `CHARGE` for a buyer payment or `REFUND` for a dispute reversal — a positive `amount_cents` magnitude, and an optional `note`. The order's `amount_paid_cents` is recomputed as the sum of its `CHARGE` amounts minus the sum of its `REFUND` amounts; once `amount_paid_cents` reaches the order's `total_cents`, the order moves `UNPAID → PAID`. Because payment changes which orders are unpaid, the buyer's `gross_owed_cents` and `net_owed_cents` are recomputed as in §3.4.

### 3.6. Pickup Windows, Scheduling, and Completion

An operator publishes pickup windows for an estate. A window names its estate via `estate_id`, a `starts_at` and an `ends_at` where the end must be strictly after the start, a `capacity` of at least 1 bounding how many orders may book it, and an optional `label`; a new window opens with `booked_count` at 0. A new window may not overlap an existing window of the same estate under half-open interval semantics: the new window collides with an existing window of that estate when the new window's start is strictly before the existing window's end and the existing window's start is strictly before the new window's end. Windows that merely abut — where one's start equals the other's end — do not overlap and are allowed. An overlap is rejected with `ERR_WINDOW_OVERLAP` (409).

A buyer who has paid may book their order into a window, moving the order `PENDING → SCHEDULED` in the pickup dimension. Booking is owner-only. The order must be `PAID`, or the request is rejected with `ERR_ORDER_NOT_PAID` (409). The payload supplies the `pickup_window_id`. The chosen window must belong to the same estate as the order — its `estate_id` must equal the order's `estate_id` — or the booking is rejected with `ERR_WINDOW_ESTATE_MISMATCH` (409). The chosen window must not collide with any window the buyer already holds through another of their orders whose pickup status is `SCHEDULED` or `PICKED_UP`, evaluated under closed-interval semantics: a collision exists when the chosen window's start is less than or equal to the other window's end and the other window's start is less than or equal to the chosen window's end. Unlike window creation, abutting windows — where the chosen window's start equals another's end — do collide here, because a buyer cannot be in two places back-to-back; such a collision is rejected with `ERR_PICKUP_OVERLAP` (409). Finally the window must have room, meaning its `booked_count` is below its `capacity`, or the booking is rejected with `ERR_WINDOW_FULL` (409). On success the order's `pickup_window_id` is set and the window's `booked_count` rises by one.

A buyer may release a booked slot, moving the order `SCHEDULED → PENDING`; this owner-only action requires the order's `pickup_status` to be `SCHEDULED`, decrements the window's `booked_count` by one, and clears the order's `pickup_window_id` back to null. Cancelling or completing a pickup on an order that is not `SCHEDULED` is rejected with `ERR_PICKUP_NOT_SCHEDULED` (409).

An operator records the outcome of a scheduled pickup by supplying a `result`. When the `result` is `PICKED_UP` the order moves `SCHEDULED → PICKED_UP` and no counters change. When the `result` is `NO_SHOW` the order moves `SCHEDULED → NO_SHOW`, the window's `booked_count` is decremented by one, and the buyer's `no_show_strikes` increases by one. If that increment brings `no_show_strikes` to three, the buyer transitions `VERIFIED → SUSPENDED`.

### 3.7. Settlement and the Seller Payout

The operator settles a closed estate, transitioning it `CLOSED → SETTLED`; settlement requires the estate to currently be `CLOSED`, and a settle attempt from any other status is rejected with `ERR_ESTATE_NOT_CLOSED` (409). Settlement stamps the final money figures. The estate's `gross_sales_cents` is the sum of `hammer_price_cents` over the lots that are in `SOLD` status and whose winning order's `payment_status` is `PAID`; unpaid, reversed, or passed lots are excluded, so the final gross is always less than or equal to the provisional gross taken at close. The `commission_cents` is the gross multiplied by the estate's `commission_bps`, divided by 10000, and rounded half-up to a whole cent. The `seller_payout_cents` is the gross minus the commission. Because commission is the rounded term and the payout is the exact residual, the identity that the seller payout plus the commission equals the gross sales always holds exactly, and it is preserved whenever a later dispute reversal changes the gross (see §3.8).

### 3.8. Disputes and Sale Reversal

A buyer who has paid may dispute a specific lot they won. A dispute names the paid `order_id`, the disputed `lot_id`, and a `reason`. The dispute is owner-only against the order behind it. The disputed lot must actually be part of that order — its `lot_id` must appear in the order's `lot_ids` — or the filing is rejected with `ERR_LOT_NOT_IN_ORDER` (409). A new dispute opens in `OPEN` status with its `outcome` null.

Adjudication follows a review loop that only the operator drives forward, except for one buyer step. The operator advances the dispute `OPEN → UNDER_REVIEW`, and from `UNDER_REVIEW` may either request more information, moving it `UNDER_REVIEW → NEEDS_INFO`, or resolve it. When a dispute is in `NEEDS_INFO`, the owning buyer — and only the buyer who owns the disputed order — moves it back `NEEDS_INFO → UNDER_REVIEW`, forming a revision cycle. Each transition is requested through a `status` change, and a resolving transition may carry an optional `resolution_note`. A dispute transition requested from a status that does not permit it is rejected with `ERR_INVALID_STATE` (409). The two terminal resolutions carry equal weight and are symmetric in every respect except their ledger consequences.

When the operator rejects a dispute, it moves `UNDER_REVIEW → REJECTED` and its `outcome` is set to `SELLER_FAVOR`; nothing about the money changes. When the operator resolves a dispute in the buyer's favor, it moves `UNDER_REVIEW → RESOLVED`, its `outcome` is set to `BUYER_FAVOR`, and a four-hop cascade unwinds the sale atomically. First, the order moves `PAID → REFUNDED` and a `REFUND` `Payment` is appended equal to the disputed lot's share of the invoice — its `hammer_price_cents` plus that lot's portion of the premium and tax — and the order's `amount_paid_cents` is recomputed. Second, the disputed lot moves `SOLD → PASSED`: its `hammer_price_cents` is cleared to null, its `winning_order_id` is cleared, and its winning bid's `is_winning` becomes false. Third, the lot is removed from the order's `lot_ids`, the order's `subtotal_cents`, `buyer_premium_cents`, `sales_tax_cents`, and `total_cents` are recomputed as in §3.4, and the buyer's `gross_owed_cents` and `net_owed_cents` are recomputed. Fourth, if the estate is already `SETTLED`, its `gross_sales_cents`, `commission_cents`, and `seller_payout_cents` are re-derived from the reduced gross so that the payout-plus-commission-equals-gross identity continues to hold exactly.

### 3.9. Cleanout and Donation

The operator finishes an estate by cleaning it out, transitioning it `SETTLED → CLEANED_OUT`; cleanout requires the estate to currently be `SETTLED`, and an attempt from any other status is rejected with `ERR_ESTATE_NOT_SETTLED` (409). Cleanout disposes of every unsold lot: for each lot of the estate that is in `PASSED`, the system creates a `Donation` record and transitions the lot `PASSED → DONATED`. Each `Donation` carries the `lot_id` of the disposed lot, the `estate_id` being cleaned out, a `recipient` label defaulting to `LOCAL_CHARITY`, and a `disposition` that is `RECYCLED` when the lot's `condition_grade` is `D` and `DONATED` otherwise. Separately, before cleanout, an operator may permanently retire an individual passed lot by moving it `PASSED → WITHDRAWN`; a withdraw is only legal from `PASSED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. All lifecycle actions, state transitions, and other modifications of existing resources return `200 OK`, as do reads. The administrative clock-setting capability returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | Operator |
| POST | `/estates` | Create an estate consignment in CATALOGING | Operator |
| GET | `/estates/{id}` | Fetch one estate | Operator, Buyer, Anonymous |
| GET | `/estates/{id}/lots` | List an estate's lots (status filter, pagination) | Operator, Buyer, Anonymous |
| GET | `/estates/{id}/pickup-windows` | List an estate's pickup windows | Operator, Buyer, Anonymous |
| POST | `/estates/{id}/open` | Open bidding: CATALOGING → LIVE | Operator |
| POST | `/estates/{id}/close` | Close bidding: LIVE → CLOSED; run settlement sweep | Operator |
| POST | `/estates/{id}/settle` | Settle: CLOSED → SETTLED; stamp final payout | Operator |
| POST | `/estates/{id}/cleanout` | Cleanout: SETTLED → CLEANED_OUT; donate passed lots | Operator |
| POST | `/lots` | Create a lot in DRAFT under a CATALOGING estate | Operator |
| GET | `/lots/{id}` | Fetch one lot (exposes version for bidding) | Operator, Buyer, Anonymous |
| GET | `/lots/{id}/photos` | List a lot's photos | Operator, Buyer, Anonymous |
| PATCH | `/lots/{id}` | Edit a draft lot and drive its status transitions | Operator |
| POST | `/photos` | Attach a condition photo to a DRAFT/CATALOGED lot | Operator |
| POST | `/buyers` | Self-register a buyer in REGISTERED | Anonymous |
| GET | `/buyers/{id}` | Fetch a buyer | Operator, Buyer |
| POST | `/buyers/{id}/verify` | Verify a buyer: REGISTERED → VERIFIED | Operator |
| POST | `/bids` | Place a bid on a SELLING lot | Buyer |
| GET | `/bids/{id}` | Fetch one bid | Operator, Buyer |
| GET | `/bids` | List bids (filter by lot_id, buyer_id) | Operator, Buyer |
| GET | `/orders/{id}` | Fetch one order/invoice | Operator, Buyer |
| GET | `/orders` | List orders (filter by estate_id, buyer_id, pickup_window_id) | Operator, Buyer |
| GET | `/orders/{id}/payments` | List an order's payment ledger | Operator, Buyer |
| POST | `/orders/{id}/pay` | Pay an invoice in full: UNPAID → PAID | Buyer |
| POST | `/orders/{id}/schedule-pickup` | Book a paid order into a window: PENDING → SCHEDULED | Buyer |
| POST | `/orders/{id}/cancel-pickup` | Release a booked slot: SCHEDULED → PENDING | Buyer |
| POST | `/orders/{id}/complete-pickup` | Record pickup outcome: SCHEDULED → PICKED_UP or NO_SHOW | Operator |
| POST | `/pickup-windows` | Create a pickup window for an estate | Operator |
| POST | `/disputes` | File a dispute against a SOLD lot on a PAID order | Buyer |
| GET | `/disputes/{id}` | Fetch one dispute | Operator, Buyer |
| GET | `/disputes` | List disputes (filter by order_id, lot_id) | Operator, Buyer |
| PATCH | `/disputes/{id}` | Advance a dispute through its review lifecycle | Operator, Buyer |
| GET | `/donations/{id}` | Fetch one donation record | Operator, Buyer, Anonymous |
| GET | `/donations` | List donation records (filter by lot_id, estate_id) | Operator, Buyer, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_OWNER` | 403 Forbidden |
| `ERR_ESTATE_NOT_CATALOGING` | 409 Conflict |
| `ERR_ESTATE_NOT_LIVE` | 409 Conflict |
| `ERR_ESTATE_NOT_CLOSED` | 409 Conflict |
| `ERR_ESTATE_NOT_SETTLED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_NOT_SELLING` | 409 Conflict |
| `ERR_ORDER_ALREADY_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_PICKUP_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WINDOW_ESTATE_MISMATCH` | 409 Conflict |
| `ERR_LOT_NOT_IN_ORDER` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PICKUP_OVERLAP` | 409 Conflict |
| `ERR_BUYER_NOT_VERIFIED` | 409 Conflict |
| `ERR_BUYER_SUSPENDED` | 409 Conflict |
| `ERR_BID_TOO_LOW` | 409 Conflict |
| `ERR_WINDOW_FULL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INSUFFICIENT_PAYMENT` | 402 Payment Required |
