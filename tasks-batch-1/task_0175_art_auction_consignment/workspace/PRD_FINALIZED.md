# Art Auction Consignment API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Art Auction Consignment API, the back-office system of record for a fine-art auction house. The platform follows a work of art from the moment it is taken in on consignment through cataloging, the live sale in the room, and the financial settlement that follows the fall of the hammer. It is at heart a pricing engine bolted to a reconciliation ledger: the same hammer figure must drive a tiered buyer's premium charged to the winning bidder, a marginal-rate droit de suite resale royalty owed to the artist, and a commission-and-withholding calculation that determines what the consignor is finally paid.

The business problem the API solves is the reconciliation of competing obligations that all hinge on a single number. When a lot is knocked down, the house owes money to several parties at once and must collect from one. Buyers expect a transparent premium computed against a published schedule; living artists (and their estates within the resale-royalty term) are entitled to a statutory royalty that the house withholds and remits to a collecting society; and consignors must be paid their net proceeds promptly, but only after the buyer has actually settled. The system must hold these obligations consistent under concurrent operation — the auctioneer recording a knock-down while a late bid lands, the finance desk issuing an invoice while a second clerk attempts the same — and must be able to unwind a sale cleanly when a transaction falls through.

Accordingly, the API models two independent lifecycles on each lot: the **sale outcome** (whether the lot is cataloged, open, sold, bought in, or withdrawn) and the **financial settlement** (whether it has been invoiced, statemented, settled, or not yet entered settlement at all). These two dimensions advance on their own clocks, and the settlement cascade only begins once the sale outcome is final. Everything below is written so that an engineer can reconstruct the precise contract from the narrative alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which that principal is acting. If `X-User-Role` is missing or is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes six roles, spelled exactly as follows: `SaleAdministrator`, `Auctioneer`, `FinanceOfficer`, `Seller`, `Bidder`, and `Viewer`.

A `SaleAdministrator` runs house operations — premium schedules, sellers, bidders, consignments, lot cataloging, and paddle registration. An `Auctioneer` runs the live sale — going live, opening and knocking down lots, buying in, and recording or retracting bids. A `FinanceOfficer` owns settlement and payout — invoices, payments, statements, disbursements, and sale reversal. A `Viewer` has read-only operational and audit access.

Three of these roles are opaque operator identities and three (in two cases) are entity-backed. When `X-User-Role` is `SaleAdministrator`, `Auctioneer`, `FinanceOfficer`, or `Viewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` compare the resource's owning seller foreign key to `X-User-ID` (a consignment via its `seller_id`, and any lot, statement, royalty, or payout reached through that consignment). When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Bidder`; ownership checks compare the resource's owning bidder foreign key to `X-User-ID` (a paddle registration via its `bidder_id`, an invoice via its `bidder_id`, and a bid via the bidder behind its paddle registration). When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object on list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; clients never supply it. Most resources additionally carry the standard system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation, including mutations applied as cascaded side effects of an operation on another resource. `created_at` is fixed at creation; `updated_at` advances to reflect the moment of the most recent change.

One entity is the exception. A `PremiumSchedule` is immutable after creation and carries only `id` and `created_at`; it has neither `updated_at` nor `version`. All other entities — `Seller`, `Bidder`, `AuctionSale`, `Consignment`, `Lot`, `PaddleRegistration`, `Bid`, `Invoice`, `ResaleRoyalty`, `SellerStatement`, and `Payout` — carry the full `created_at`, `updated_at`, and `version` set.

### 2.5. Money, Rates, and Rounding

Every monetary amount in the system is stored and exchanged as an integer number of cents; there are no fractional-cent fields and no floating amounts in request or response bodies. Every amount belonging to a sale is denominated in that sale's `currency`, an ISO 4217 code fixed when the sale is created; every lot price and bid amount in a sale shares that currency.

Rates are expressed in basis points, where one basis point is one hundredth of one percent — so 2600 basis points means 26.00 percent and 1000 basis points means 10.00 percent. Wherever a rate is applied to a cents amount, the system computes the exact rational product and converts to integer cents using the **round half up** convention (a value of exactly one half rounds up). The precise point at which rounding occurs differs by calculation and is stated in §3 for each; the governing rule throughout is that intermediate slices are accumulated at full precision and rounding is applied once, never tier by tier, except where a value was already rounded at an earlier accrual.

### 2.6. Parallel Lifecycles and the Settlement Cascade

A `Lot` is unusual in carrying two independent state fields. Its `sale_status` tracks the room outcome and moves through `CATALOGED`, `OPEN`, `SOLD`, `BOUGHT_IN`, and `WITHDRAWN`. Its `settlement_status` tracks the financial lifecycle and moves through `NONE`, `INVOICED`, `STATEMENTED`, and `SETTLED`. The two dimensions advance independently, with one hard ordering rule: `settlement_status` may leave `NONE` only after `sale_status` has reached `SOLD`. Other entities follow simpler lifecycles: an `AuctionSale` runs `CATALOGING` → `PUBLISHED` → `LIVE` → `CLOSED`; a `Consignment` runs `DRAFT` ↔ `ACTIVE` with either able to reach `TERMINATED`; an `Invoice` runs `ISSUED` to `PAID` or `VOID`; a `ResaleRoyalty` runs `ACCRUED` to `REMITTED` or `REVERSED`; a `SellerStatement` runs `PENDING` to `PAID` or `REVERSED`; and a `Payout` is created directly in its terminal `DISBURSED` state.

When one operation must change several resources, every affected resource is mutated in full: each gets its `version` incremented by 1 and its `updated_at` refreshed. These cascades are described in the workflow narratives of §3, but the principle is uniform: a single client action may legitimately bump the versions of a parent and one or more children in the same transaction. Computed roll-up counters — `lot_count` on both `AuctionSale` and `Consignment` — are recomputed whenever the set of non-withdrawn lots beneath them changes.

### 2.7. Nested Resource Retrieval and Path Validation

Many resources are addressed through paths that name a parent before a child or a collection. When a path contains more than one resource identifier, the system validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request for the lots of a sale that does not exist fails on the sale before the lot collection is ever consulted. This left-to-right discipline governs reads, creations, and transitions alike, and existence checks on path identifiers precede the body and business-rule checks described below.

Several relationships are denormalized rather than path-nested and are discovered through filtered lists. A lot's winning paddle is recorded on the lot as `winning_paddle_registration_id` and resolved by reading that registration directly; it is not a relational parent and never requires child enumeration. Invoices, statements, royalties, payouts, bids, and paddle registrations are reached through their reverse-reachability list endpoints (for example, a bidder's invoices, a lot's bids, a consignment's statements) rather than by nesting.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the lot they act upon, and each requires a version field in its request body that is not optional.

Knocking a lot down requires `expected_lot_version` carrying the client's last observed `version` of the target `Lot`. If that value does not match the lot's current `version` — for instance because a further bid was accepted on the lot after the auctioneer read it, advancing the lot's version and raising the standing high — the knock-down is rejected with `ERR_STALE_VERSION` (HTTP 412), so the auctioneer cannot record a hammer against a stale view of the winning amount.

Issuing the buyer invoice for a sold lot likewise requires `expected_lot_version` carrying the client's last observed `version` of the target `Lot`. This OCC check is evaluated only after the lot's single-entity state precondition (sale_status `SOLD` and settlement_status `NONE`) and the cross-entity sale-`CLOSED` dependency have both passed, in the fixed order of §2.9. So a second invoice attempt on a lot whose first invoice already advanced its settlement dimension out of `NONE` (the existing invoice legitimately superseding the second attempt) fails the single-entity precondition first and is rejected with `ERR_INVALID_STATE` (HTTP 409), not `ERR_STALE_VERSION`. The version check fires only when those preconditions still hold but the supplied `expected_lot_version` does not match the lot's current `version` — for instance because a concurrent operation bumped the lot's version while leaving it `SOLD`/`NONE` — in which case the invoice creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Beyond these two OCC-guarded creates, several transition endpoints accept a version field for the resource they mutate so that callers can detect lost updates on simple state changes — `expected_consignment_version`, `expected_auction_sale_version`, `expected_bidder_version`, `expected_paddle_registration_version`, `expected_bid_version`, `expected_invoice_version`, and `expected_seller_statement_version`. Each of these likewise carries the client's last observed `version` of the named resource. A request whose supplied version does not match the resource's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints that take none of these version fields perform no concurrency check.

### 2.9. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the `X-User-Role` header comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`). Existence checks follow: path-referenced resources first, validated left to right (`ERR_NOT_FOUND`), then body foreign-key references (`ERR_FK_NOT_FOUND`). Next come well-formedness of the request body (`ERR_INVALID_REQUEST`) and, on list endpoints, pagination range (`ERR_VALIDATION_PAGINATION`). After that the system checks the single-entity state precondition for the requested transition (`ERR_INVALID_STATE`), then the cross-entity dependency guard (`ERR_DEPENDENCY_NOT_READY`), then the optimistic-concurrency version match (`ERR_STALE_VERSION`). The remaining domain rules follow in this order: paddle and bidder eligibility (`ERR_PADDLE_INELIGIBLE`), lot-term and estimate validity (`ERR_INVALID_LOT_TERMS`), minimum-bid threshold (`ERR_BID_TOO_LOW`), uniqueness (`ERR_DUPLICATE`), and finally fiscal limits on credit and payment (`ERR_CREDIT_LIMIT_EXCEEDED`). The practical consequence is that, for example, a malformed body surfaces before a state-precondition failure, and a stale-version rejection surfaces before an eligibility or credit-limit rejection on the same request.

## 3. Business Logic & Workflows

### 3.1. Intake: Sellers, Bidders, and Premium Schedules

The reference data of the house is established first. A `SaleAdministrator` registers a consignor as a `Seller`, supplying the `legal_name`, the contact `email`, the residence `country_code` (an ISO 3166-1 alpha-2 code that affects payout withholding), and the disbursement account reference `payout_iban`. The `email` must be unique among sellers. The same administrator registers a `Bidder` with `legal_name`, `email` (unique among bidders), and `country_code`, and may optionally set the `credit_limit_cents`, which defaults to 0. A bidder's `credit_limit_cents` is the maximum unsettled exposure permitted across all of that bidder's open invoices; a limit of 0 means the bidder may not purchase anything until it is raised. Each new bidder begins with `status` of `ACTIVE` and an `outstanding_balance_cents` of 0; the balance is a computed figure equal to the sum of `total_due_cents` over the bidder's invoices that are in `ISSUED` status, and it ties off as those invoices flip to `PAID` or `VOID`.

A bidder's `status` is one of `ACTIVE` or `SUSPENDED`; a `SUSPENDED` bidder may neither register paddles nor place bids. A `SaleAdministrator` may adjust a bidder after the fact, changing the `credit_limit_cents`, flipping the `status` between `ACTIVE` and `SUSPENDED`, or both, supplying `expected_bidder_version` to guard the change; a successful adjustment increments the bidder's `version` by 1.

The buyer's-premium tariff is captured as a `PremiumSchedule`, created by a `SaleAdministrator` with a human-readable `name` and an ordered array of `tiers`. Each tier is an object with an `upper_bound_cents` and a `rate_bps`. The tiers describe marginal bands applied to a hammer price: the `upper_bound_cents` is the exclusive upper edge of the band, and the final, open-topped band carries `upper_bound_cents` of null. The array must be sorted ascending by `upper_bound_cents` with the open (null) tier last, and each `rate_bps` is a basis-point rate. A premium schedule, once created, is never edited.

### 3.2. Consignment Agreements and Their Lifecycle

Before any artwork can be cataloged, the house and the consignor agree commercial terms in a `Consignment`. A `SaleAdministrator` creates one in `DRAFT` status, naming the consignor through `seller_id` and setting `seller_commission_bps`, the commission rate in basis points charged on the hammer price, which must lie between 0 and 5000 inclusive. The administrator may also set `unsold_fee_cents`, a flat fee charged to the seller for each lot that fails to meet its reserve and is bought in; it defaults to 0. The consignment also exposes a computed `lot_count` equal to the number of its non-withdrawn lots.

A consignment moves among three states, `DRAFT`, `ACTIVE`, and `TERMINATED`. Activation — countersigning the agreement — advances it from `DRAFT` to `ACTIVE`, and is permitted only when the consignment is currently `DRAFT` and the `Seller` named by `seller_id` exists; a `DRAFT`-only precondition violated here yields `ERR_INVALID_STATE`. Activation increments the consignment's `version` by 1. Only while `ACTIVE` may lots attach to the consignment under its commission terms.

An `ACTIVE` consignment may be reverted to `DRAFT` for amendment. Reverting is permitted only when the consignment is `ACTIVE` (otherwise `ERR_INVALID_STATE`) and only when none of its lots has a `sale_status` in `OPEN`, `SOLD`, or `BOUGHT_IN` — that is, only when every attached lot is still `CATALOGED` or already `WITHDRAWN`, because a lot that has gone to the room or beyond cannot have its terms rewritten. The revert increments the consignment's `version` by 1.

Termination ends the agreement and may be applied from either `DRAFT` or `ACTIVE`. It is permitted only when the consignment is in one of those two states and when none of its lots is `OPEN` or `SOLD`; a violation of the state precondition yields `ERR_INVALID_STATE`. On termination, every lot under the consignment that is still `CATALOGED` is cascaded from `CATALOGED` to `WITHDRAWN`, each such lot's `version` incremented by 1, and both that lot's `AuctionSale` `lot_count` and the consignment's own `lot_count` recomputed; the consignment's `version` is then incremented by 1. `TERMINATED` is terminal and blocks any further lot attachment.

### 3.3. Building the Catalog: Auction Sales and Lots

A sale is organized as an `AuctionSale`, created by a `SaleAdministrator` with a `title`, a scheduled start `sale_date_utc` (ISO 8601 UTC), a settlement `currency`, and `buyers_premium_schedule_id` referencing the `PremiumSchedule` whose tiers apply to every lot in the sale. A new sale opens in `CATALOGING` with a `lot_count` of 0; that `lot_count` counts the sale's lots whose `sale_status` is not `WITHDRAWN`.

Within a sale in `CATALOGING`, the administrator catalogs each artwork as a `Lot`. The lot's `auction_sale_id` is taken from the path and never supplied in the body. The body names the governing `consignment_id`, the catalog position `lot_number`, the artwork `title`, the `artist_name`, and the boolean `artist_alive` — true when the artist is living or died within the resale-royalty term, which is the gate for droit de suite. It also carries the pre-sale `low_estimate_cents` and `high_estimate_cents` and the confidential `reserve_cents`, the minimum acceptable hammer; a reserve of 0 means no reserve. A new lot is created with `sale_status` of `CATALOGED` and `settlement_status` of `NONE`, its `hammer_price_cents` 0, and its `winning_paddle_registration_id` null until it sells. Cataloging recomputes both the sale's `lot_count` and the consignment's `lot_count`.

Several conditions are enforced at catalog time. The estimates must be ordered so that the low estimate is greater than 0 and no greater than the high estimate, and the high estimate is at least the low estimate; the reserve must not exceed the low estimate. Any of these orderings being violated yields `ERR_INVALID_LOT_TERMS`. The `lot_number` must be unique among the non-withdrawn lots of the same sale; a collision yields `ERR_DUPLICATE`. A lot may attach only under a consignment that permits it, and a referenced consignment that does not resolve yields `ERR_FK_NOT_FOUND`.

The sale itself advances through a guarded pipeline. Publishing the catalog moves the sale from `CATALOGING` to `PUBLISHED`; it requires the sale to be in `CATALOGING` (otherwise `ERR_INVALID_STATE`) and requires at least one non-withdrawn lot to exist (otherwise `ERR_LOTS_REQUIRED`), and it increments the sale's `version` by 1. Each sale transition is guarded by `expected_auction_sale_version`. Going live moves the sale from `PUBLISHED` to `LIVE`; it requires the sale to be `PUBLISHED`, cascades every lot in the sale whose `sale_status` is `CATALOGED` from `CATALOGED` to `OPEN` (each such lot's `version` incremented by 1), and increments the sale's `version` by 1. Closing the sale moves it from `LIVE` to `CLOSED`; it requires the sale to be `LIVE` (otherwise `ERR_INVALID_STATE`) and requires that no lot in the sale remains `OPEN` — every lot must already have been knocked down to `SOLD` or `BOUGHT_IN`, or withdrawn — failing which the close is rejected with `ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS`; a successful close increments the sale's `version` by 1.

A single `CATALOGED` lot may also be withdrawn directly by a `SaleAdministrator` while it is still `CATALOGED`, supplying `expected_lot_version`. Withdrawal moves the lot's `sale_status` from `CATALOGED` to `WITHDRAWN`, recomputes the sale's and consignment's `lot_count`, and increments the lot's `version` by 1.

### 3.4. Registering to Bid: Paddles

To bid in a sale, a bidder must hold a paddle for it. A `SaleAdministrator` creates a `PaddleRegistration` naming the `auction_sale_id` and the `bidder_id`, optionally specifying the `registration_type` and a `max_absentee_bid_cents`. The `registration_type` is one of `FLOOR`, `ABSENTEE`, or `PHONE`, defaulting to `FLOOR`; it describes how the bidder participates. The system assigns the `paddle_number` itself: numbers run sequentially per sale, beginning at 1 and incrementing by 1 in registration `created_at` order, and are unique within a sale. A new registration is created with `status` of `ACTIVE`; a registration's `status` is one of `ACTIVE` or `REVOKED`, and a `REVOKED` paddle can neither place nor win bids. A `SaleAdministrator` may revoke a registration, supplying `expected_paddle_registration_version`, which moves its `status` to `REVOKED` and increments its `version` by 1.

The `max_absentee_bid_cents` is the ceiling the house may execute on an absentee bidder's behalf. It is required and must be greater than 0 when the `registration_type` is `ABSENTEE`, and it must be 0 for `FLOOR` and `PHONE` registrations; the default value is 0. A registration that violates this absentee rule is rejected with `ERR_INVALID_LOT_TERMS`. Registration is blocked entirely for a `SUSPENDED` bidder, which is rejected with `ERR_PADDLE_INELIGIBLE`. A given bidder may hold only one paddle per sale; attempting to register the same bidder a second time for the same sale is rejected with `ERR_DUPLICATE`.

### 3.5. The Room: Opening, Bidding, Knock-Down, and Retraction

Once a sale is `LIVE`, the auctioneer works the lots. A lot reaches `OPEN` either through the bulk cascade when the sale goes live or by opening a single lot explicitly; opening a single lot is permitted only when that lot is `CATALOGED` and the lot's sale is `LIVE`, and it advances the lot's `sale_status` from `CATALOGED` to `OPEN` and increments the lot's `version` by 1. The cross-entity requirement that the sale be `LIVE` is enforced as a dependency guard, and a failure of it is reported as `ERR_DEPENDENCY_NOT_READY`; a lot that is not in `CATALOGED` fails the single-entity precondition with `ERR_INVALID_STATE`.

A bid is placed on an `OPEN` lot by an `Auctioneer` (recording a bid called in the room or by phone) or by a `Bidder` (acting on its own paddle). The bid body names the `paddle_registration_id` and the `amount_cents`, and may carry a `bid_channel` of `FLOOR`, `ABSENTEE`, or `PHONE`, defaulting to `FLOOR`. The channel of the individual bid must be consistent with the paddle's `registration_type` — a floor paddle bids on the floor channel, a phone paddle on the phone channel, an absentee paddle on the absentee channel — and a mismatch, like a bid placed through a suspended bidder or a revoked paddle, is rejected with `ERR_PADDLE_INELIGIBLE`. Placing a bid requires the sale to be `LIVE` and the lot to be `OPEN`; either dependency failing yields `ERR_DEPENDENCY_NOT_READY`. A successful bid is created with `status` `ACCEPTED`, recomputes the lot's standing high and minimum next bid, and increments the lot's `version` by 1 — which is precisely the mutation that can leave an auctioneer's earlier view of the lot stale and so arm the knock-down concurrency guard.

The standing-high bid on a lot is the bid with the greatest `amount_cents` among the lot's bids whose `status` is `ACCEPTED` (a `RETRACTED` bid is excluded from this computation, and a `WINNING` bid exists only after knock-down); should two accepted bids tie on `amount_cents` — reachable only through retraction-and-rebid edge cases — the tie is broken in favor of the earliest `created_at`, never by identifier.

The minimum a new bid must clear depends on where the current standing high sits. Let the standing high be the greatest `amount_cents` among the lot's bids whose status is `ACCEPTED` or `WINNING`, or zero if there are none. The required increment is banded: a standing high of at least 0 and below 1,000.00 (that is, below 100000 cents) requires an increment of 50.00 (5000 cents); a standing high of at least 1,000.00 and below 5,000.00 (100000 up to but not including 500000 cents) requires 100.00 (10000 cents); a standing high of at least 5,000.00 and below 20,000.00 (500000 up to but not including 2000000 cents) requires 250.00 (25000 cents); and a standing high of 20,000.00 or more (at least 2000000 cents) requires 1,000.00 (100000 cents). Band edges are half-open: a value exactly equal to a band's upper figure falls into the next band up. When there is a standing high, the minimum next bid is that standing high plus the increment for its band. When there is no standing high yet, the opening bid must be at least the starting floor of 50.00 (5000 cents). A bid whose `amount_cents` is below the lot's minimum next bid — or below the opening floor for a first bid — is rejected with `ERR_BID_TOO_LOW`.

A bidder's credit is checked before a bid is accepted: a bid, together with the projected `total_due_cents` it would generate if it went on to win, may not push the bidder's `outstanding_balance_cents` plus that projected total over the bidder's `credit_limit_cents`; exceeding it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

An `Auctioneer` may retract an `ACCEPTED` bid, supplying `expected_bid_version`; retraction sets the bid's `status` to `RETRACTED`, recomputes the lot's standing high, and increments the bid's `version` by 1.

Knocking a lot down resolves it. The action is permitted only when the lot is `OPEN` (otherwise `ERR_INVALID_STATE`) and its sale is `LIVE` (a dependency failure yielding `ERR_DEPENDENCY_NOT_READY`), and it requires `expected_lot_version` to match the lot's current `version` as described in §2.8. The fork turns on the reserve. If at least one `ACCEPTED` bid exists and the standing-high accepted bid's `amount_cents` is at least the lot's `reserve_cents`, the lot is sold: its `sale_status` moves from `OPEN` to `SOLD`, its `hammer_price_cents` is set to that standing-high amount, the standing-high accepted bid's `status` is set to `WINNING` (that bid's `version` incremented by 1), the lot's `winning_paddle_registration_id` is set to the winning bid's `paddle_registration_id`, and the lot's `version` is incremented by 1. If instead no accepted bid exists, or the standing-high accepted bid is below the reserve, the lot is bought in: its `sale_status` moves from `OPEN` to `BOUGHT_IN`, its `hammer_price_cents` stays 0, no winning bid is set, and the lot's `version` is incremented by 1. Knock-down does not itself create any invoice or royalty; the lot's `settlement_status` stays `NONE` until the buyer is invoiced. An `Auctioneer` may also explicitly buy in an `OPEN` lot — moving it from `OPEN` to `BOUGHT_IN` and incrementing its `version` by 1 — supplying `expected_lot_version` for that action as well.

### 3.6. Buyer Settlement: Invoicing and Payment

After the sale has `CLOSED`, the finance desk collects from the winning buyers. Issuing the invoice for a sold lot is a `FinanceOfficer` action permitted only when the lot's `sale_status` is `SOLD`, its `settlement_status` is `NONE`, and the lot's sale is `CLOSED`; the SOLD/NONE single-entity precondition failing yields `ERR_INVALID_STATE`, while the requirement that the sale be `CLOSED` is a cross-entity dependency reported as `ERR_DEPENDENCY_NOT_READY`. The request must carry `expected_lot_version` matching the lot's current `version`, as in §2.8.

Issuing the invoice creates an `Invoice` in `ISSUED` status for the lot. The invoice snapshots the lot through its `lot_id` and records `hammer_price_cents` from the lot at invoice time. It carries the denormalized winning `paddle_registration_id` copied from the lot's `winning_paddle_registration_id`, and the buyer's `bidder_id` resolved from that winning registration. The system computes the tiered `buyers_premium_cents` and the `total_due_cents`, and sets `amount_paid_cents` to 0.

The buyer's premium is a marginal-tier charge on the hammer. Take the invoice's `hammer_price_cents` as the base and the tiers of the `PremiumSchedule` referenced by the lot's sale through its `buyers_premium_schedule_id`, read in ascending order of `upper_bound_cents` with the open (null) tier last. Each tier's `rate_bps` applies only to the portion of the hammer that falls within that tier's band — the slice between the previous tier's upper bound and this tier's upper bound (with the open tier's band running up to the full hammer). For each band, the slice width is the hammer capped at the band's top minus the previous band's top, never less than zero, and the band's contribution is that slice multiplied by the band's `rate_bps` divided by 10000. These contributions are accumulated as an exact rational across all bands the hammer reaches, and only the summed total is rounded — once, half up — to give `buyers_premium_cents`. Rounding must not be applied tier by tier, because rounding each band and then summing can differ from the pinned method by a cent at band boundaries. The invoice's `total_due_cents` is then the `hammer_price_cents` plus the `buyers_premium_cents`.

Issuing the invoice also recomputes the winning bidder's `outstanding_balance_cents` so that it includes the new invoice's `total_due_cents`. And if the lot's `artist_alive` is true, the same action accrues the resale royalty described in §3.7; if the artist is not within scope, no royalty row is created. The invoice action finally sets the lot's `settlement_status` to `INVOICED` and increments the lot's `version` by 1.

Payments are recorded against an invoice by a `FinanceOfficer`, supplying the cash `amount_cents` and `expected_invoice_version`. A payment's `amount_cents` must be greater than 0 and must not exceed the invoice's remaining due (its `total_due_cents` less its current `amount_paid_cents`); a payment of zero or less, or one that overshoots the remaining due, is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. A payment may be recorded only while the invoice is `ISSUED`. Each payment increases the invoice's `amount_paid_cents` by the payment amount and increments the invoice's `version` by 1. A partial payment — one that does not bring `amount_paid_cents` up to `total_due_cents` — leaves the invoice in `ISSUED` and does not touch the bidder's outstanding balance, because the balance ties off only at full settlement. When a payment brings `amount_paid_cents` to at least `total_due_cents`, the invoice's `status` moves to `PAID` and the bidder's `outstanding_balance_cents` is decreased by that invoice's `total_due_cents`.

### 3.7. The Artist's Royalty: Droit de Suite

When a royalty-eligible lot is invoiced, the house accrues a droit de suite resale royalty as a `ResaleRoyalty` tied to the lot through its `lot_id`. The royalty's base is the hammer, snapshotted as `hammer_price_cents` — not the buyer's total. The royalty is borne by the seller: its `bearer` is always `SELLER` under this house's policy, meaning it is withheld from the seller's statement. A royalty is created in `ACCRUED` status, and its `royalty_cents` is computed as below.

Eligibility has two conditions, both required: the lot's `artist_alive` must be true, and the hammer must be at least the royalty floor of 1,000.00 (100000 cents). If either condition fails the royalty is zero and no `ResaleRoyalty` row is created at all. When eligible, the royalty is a marginal-tier charge on the hammer with five bands: the slice of the hammer from 0 up to 50,000.00 (5000000 cents) is charged at 400 basis points (4.00 percent); the slice from 50,000.00 up to 200,000.00 (5000000 to 20000000 cents) at 300 basis points (3.00 percent); the slice from 200,000.00 up to 350,000.00 (20000000 to 35000000 cents) at 100 basis points (1.00 percent); the slice from 350,000.00 up to 500,000.00 (35000000 to 50000000 cents) at 50 basis points (0.50 percent); and any portion above 500,000.00 (50000000 cents) at 25 basis points (0.25 percent). As with the buyer's premium, each band's contribution is the slice within that band multiplied by its rate, the contributions are accumulated as an exact rational across all bands, and the summed total is rounded once, half up, to integer cents to give a raw royalty figure. That raw figure is then capped: the final `royalty_cents` is the smaller of the raw royalty and the absolute per-lot cap of 12,500.00 (1250000 cents).

A royalty's `status` is one of `ACCRUED`, `REMITTED`, or `REVERSED`. It is created `ACCRUED`, becomes `REMITTED` when the seller statement that withholds it is disbursed, and becomes `REVERSED` if the underlying sale is reversed. Each of those transitions increments the royalty's `version` by 1.

### 3.8. Seller Settlement: Statements, Disbursement, and Royalty Remittance

A consignor is paid only after the buyer has settled. Generating the seller statement for a lot is a `FinanceOfficer` action permitted only when the lot's `settlement_status` is `INVOICED` (otherwise `ERR_INVALID_STATE`) and the lot's `Invoice` is `PAID` — the buyer has settled in full — a cross-entity guard whose failure is reported as `ERR_DEPENDENCY_NOT_READY`. The action creates a `SellerStatement` in `PENDING` status, tied to the lot through `lot_id`, with its `consignment_id` resolved from the lot and its `hammer_price_cents` snapshotted from the lot. It then advances the lot's `settlement_status` from `INVOICED` to `STATEMENTED` and increments the lot's `version` by 1.

The statement's figures are evaluated in a pinned order. First, the `seller_commission_cents` is the lot's `hammer_price_cents` multiplied by the governing consignment's `seller_commission_bps`, divided by 10000, rounded once half up to integer cents. Second, the `resale_royalty_withheld_cents` is read: it is the lot's `ResaleRoyalty` `royalty_cents` when a royalty row exists for the lot with `bearer` of `SELLER` and a status other than `REVERSED`, and 0 otherwise (this withheld royalty was already rounded at accrual and is not rounded again). Third, the `net_payable_cents` is the `hammer_price_cents` less the `seller_commission_cents` less the `resale_royalty_withheld_cents`. The net payable is guaranteed to be non-negative and must never be negative: because the commission rate is capped at 5000 basis points and the royalty schedule and its cap keep commission plus royalty below the hammer for any hammer at or above the royalty floor, the subtraction never drops below zero.

Disbursing a statement settles the lot and is a `FinanceOfficer` action permitted only when the lot's `settlement_status` is `STATEMENTED` and the statement's own `status` is `PENDING`; it supplies `expected_seller_statement_version`. Disbursement is a depth-three cascade on a single action: it creates a `Payout` in `DISBURSED` status whose `amount_cents` is a snapshot of the statement's `net_payable_cents` and whose `seller_statement_id` names the statement being disbursed; it sets the statement's `status` to `PAID` (incrementing that statement's `version` by 1); if the lot's `ResaleRoyalty` exists and is `ACCRUED`, it sets that royalty's `status` to `REMITTED` (incrementing the royalty's `version` by 1), marking the moment the withheld royalty is remitted to the collecting society; and it advances the lot's `settlement_status` from `STATEMENTED` to `SETTLED` (incrementing the lot's `version` by 1). A `Payout` is created directly in its terminal `DISBURSED` state.

### 3.9. Unwinding a Sale: Reversal and Compensation

A sale can fall through, and the finance desk must be able to unwind it. Reversing a sold lot is a `FinanceOfficer` action supplying `expected_lot_version`. It compensates the financial trail and rolls the lot's settlement dimension back: the lot's `ISSUED` `Invoice` becomes `VOID`, and because that invoice no longer counts, the buyer's `outstanding_balance_cents` is decreased by the invoice's `total_due_cents` (the voided invoice's `version` incremented by 1); the lot's `ACCRUED` `ResaleRoyalty`, if any, becomes `REVERSED` (its `version` incremented by 1); and the lot's `PENDING` `SellerStatement`, if any, becomes `REVERSED` (its `version` incremented by 1). The lot's `settlement_status` returns to `NONE` and the lot's `version` is incremented by 1.

Reversal is only safe before money has left the house. If the lot's seller statement has already been disbursed — that is, the statement is already `PAID` — the entire reverse-sale is rejected with `ERR_STATEMENT_ALREADY_PAID` and no side effects fire; an already-`PAID` statement is never silently reversed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions that act on a resource named in the path — return `200 OK`. The two settlement creates that mint a brand-new resource as their primary result (issuing an invoice and disbursing a payout, as well as generating a statement) return `201 Created`. The request body, computed fields, and side effects of each endpoint are described in the narratives of §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/premium-schedules` | Create a tiered buyer's-premium schedule | SaleAdministrator |
| GET | `/premium-schedules/{id}` | Read a premium schedule | SaleAdministrator, FinanceOfficer, Auctioneer, Viewer |
| POST | `/sellers` | Register a consignor | SaleAdministrator |
| GET | `/sellers/{id}` | Read a seller | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| POST | `/bidders` | Register a bidder | SaleAdministrator |
| GET | `/bidders/{id}` | Read a bidder (includes computed outstanding balance) | SaleAdministrator, FinanceOfficer, Bidder, Viewer |
| PATCH | `/bidders/{id}` | Adjust a bidder's credit limit or suspend/reactivate | SaleAdministrator |
| GET | `/bidders/{id}/invoices` | List a bidder's invoices | SaleAdministrator, FinanceOfficer, Bidder, Viewer |
| GET | `/bidders/{id}/paddle-registrations` | List a bidder's paddle registrations | SaleAdministrator, FinanceOfficer, Bidder, Viewer |
| POST | `/consignments` | Create a consignment agreement (DRAFT) | SaleAdministrator |
| GET | `/consignments/{id}` | Read a consignment | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/consignments` | List consignments, filterable by seller | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| POST | `/consignments/{id}/activate` | Countersign a consignment (DRAFT to ACTIVE) | SaleAdministrator |
| POST | `/consignments/{id}/revert-to-draft` | Revert an ACTIVE consignment to DRAFT | SaleAdministrator |
| POST | `/consignments/{id}/terminate` | Terminate a consignment; cascade CATALOGED lots to WITHDRAWN | SaleAdministrator |
| POST | `/auction-sales` | Create an auction sale (CATALOGING) | SaleAdministrator |
| GET | `/auction-sales/{id}` | Read an auction sale | SaleAdministrator, FinanceOfficer, Auctioneer, Seller, Bidder, Viewer |
| GET | `/auction-sales` | List auction sales, filterable by premium schedule | SaleAdministrator, FinanceOfficer, Auctioneer, Viewer |
| POST | `/auction-sales/{id}/publish` | Publish the catalog (CATALOGING to PUBLISHED) | SaleAdministrator |
| POST | `/auction-sales/{id}/open-bidding` | Go live (PUBLISHED to LIVE); cascade CATALOGED lots to OPEN | Auctioneer |
| POST | `/auction-sales/{id}/close` | Close the sale (LIVE to CLOSED) | Auctioneer |
| POST | `/auction-sales/{id}/lots` | Catalog a lot in a sale | SaleAdministrator |
| GET | `/lots/{id}` | Read a lot (both state dimensions, hammer, winning paddle) | SaleAdministrator, FinanceOfficer, Auctioneer, Seller, Bidder, Viewer |
| GET | `/auction-sales/{id}/lots` | List lots in a sale | SaleAdministrator, FinanceOfficer, Auctioneer, Seller, Bidder, Viewer |
| GET | `/lots` | List lots, filterable by consignment | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| POST | `/lots/{id}/withdraw` | Withdraw a CATALOGED lot | SaleAdministrator |
| POST | `/lots/{id}/open` | Open a single CATALOGED lot while the sale is LIVE | Auctioneer |
| POST | `/lots/{id}/knock-down` | Knock down an OPEN lot; SOLD or BOUGHT_IN | Auctioneer |
| POST | `/lots/{id}/buy-in` | Explicitly buy in an OPEN lot | Auctioneer |
| POST | `/lots/{id}/reverse-sale` | Reverse a sold lot's financials (compensation) | FinanceOfficer |
| POST | `/lots/{id}/bids` | Place a bid on an OPEN lot | Auctioneer, Bidder |
| GET | `/bids/{id}` | Read a bid | SaleAdministrator, FinanceOfficer, Auctioneer, Bidder, Viewer |
| GET | `/lots/{id}/bids` | List bids on a lot | SaleAdministrator, FinanceOfficer, Auctioneer, Bidder, Viewer |
| GET | `/bids` | List bids, filterable by paddle registration or lot | SaleAdministrator, FinanceOfficer, Auctioneer, Bidder, Viewer |
| POST | `/bids/{id}/retract` | Retract an ACCEPTED bid | Auctioneer |
| POST | `/paddle-registrations` | Register a paddle for a bidder in a sale | SaleAdministrator |
| GET | `/paddle-registrations/{id}` | Read a paddle registration | SaleAdministrator, FinanceOfficer, Auctioneer, Bidder, Viewer |
| GET | `/auction-sales/{id}/paddle-registrations` | List paddle registrations for a sale | SaleAdministrator, FinanceOfficer, Auctioneer, Viewer |
| POST | `/paddle-registrations/{id}/revoke` | Revoke a paddle registration | SaleAdministrator |
| POST | `/lots/{id}/invoice` | Issue the buyer invoice for a SOLD lot (OCC-guarded) | FinanceOfficer |
| GET | `/invoices/{id}` | Read an invoice | SaleAdministrator, FinanceOfficer, Bidder, Viewer |
| GET | `/lots/{id}/invoices` | List a lot's invoices | SaleAdministrator, FinanceOfficer, Bidder, Viewer |
| POST | `/invoices/{id}/payments` | Record a cash payment against an invoice | FinanceOfficer |
| POST | `/lots/{id}/statement` | Generate the seller statement for a fully-paid lot | FinanceOfficer |
| GET | `/seller-statements/{id}` | Read a seller statement | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/lots/{id}/seller-statements` | List a lot's seller statements | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/consignments/{id}/seller-statements` | List statements under a consignment | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| POST | `/seller-statements/{id}/disburse` | Disburse a PENDING statement: create payout, remit royalty, settle lot | FinanceOfficer |
| GET | `/payouts/{id}` | Read a payout | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/seller-statements/{id}/payouts` | List payouts for a statement | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/lots/{id}/resale-royalties` | List a lot's resale royalties | SaleAdministrator, FinanceOfficer, Seller, Viewer |
| GET | `/resale-royalties/{id}` | Read a resale royalty | SaleAdministrator, FinanceOfficer, Seller, Viewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPENDENCY_NOT_READY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PADDLE_INELIGIBLE` | 409 |
| `ERR_INVALID_LOT_TERMS` | 422 |
| `ERR_BID_TOO_LOW` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS` | 409 |
| `ERR_LOTS_REQUIRED` | 409 |
| `ERR_STATEMENT_ALREADY_PAID` | 409 |
| `ERR_VALIDATION_PAGINATION` | 400 |
