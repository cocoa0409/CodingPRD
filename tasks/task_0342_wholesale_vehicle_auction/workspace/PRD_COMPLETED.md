# Wholesale Vehicle Auction API — Product Requirements Document

## 1. Introduction

The Wholesale Vehicle Auction API powers a dealer-to-dealer remarketing platform of the kind operated by large physical-plus-digital auction houses. On any given sale day, hundreds of consigned vehicles flow across multiple parallel lanes; selling dealers want their reserves protected and their proceeds settled cleanly, buying dealers want a fair clearing price and a clear path to take their vehicle home, and the auction operator must keep the whole floor — intake, the block, money, titles, and the gate — consistent at every moment. This document specifies the system that coordinates those parties.

Four constituencies meet here. A selling dealer consigns vehicles and sets a hidden minimum. A buying dealer bids — live on the lane or remotely online — against a floor-plan credit line that must never be overdrawn. The auction operator runs the sale: building the run list, opening and closing the block, dropping the hammer, recording payment and title, and releasing vehicles at the gate. An independent adjudicator resolves post-sale disputes within the arbitration policy. The platform's central promise is that money, title, inventory state, and physical release stay reconciled across all of these actors even as a single hammer fall cascades into a settlement, a credit debit, and ultimately a gate pass.

Because real auctions are fast and concurrent, the specification is precise about two hard things: the exact arithmetic of fees and proceeds (computed in integer cents, with a fixed rounding discipline and dual provisional-versus-final variants), and the safe ordering of bids when several arrive against a lot whose standing price is moving. The sections that follow define the global contract first, then walk the business workflows from consignment intake through transport delivery.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. The entire API is mounted under the `/auction` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401); specifically, a header that is absent, empty, or whitespace-only is treated as missing, and an `X-User-Role` value that is not exactly one of the four recognized roles is treated as malformed — both cases yield `ERR_MISSING_AUTH_CONTEXT`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `AuctionAdmin`, `Seller`, `Buyer`, and `Arbitrator`.

`AuctionAdmin` is the auction operator. When `X-User-Role` is `AuctionAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it but does not compare it to any entity's `id`. The same opaque treatment applies to `Arbitrator`: when `X-User-Role` is `Arbitrator`, `X-User-ID` is an opaque adjudicator identifier not bound to any stored record, used only to authorize ruling on claims.

`Seller` and `Buyer` are entity-backed identities. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; any ownership-scoped operation on a resource that references a seller compares that resource's seller foreign key to `X-User-ID` (for a consignment, the `seller_id` must equal `X-User-ID`). When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership-scoped operations compare the resource's buyer foreign key to `X-User-ID` (a bid, an arbitration claim, a settlement, or a transport order carries a `buyer_id` that must equal `X-User-ID`). When an entity-backed `Seller` or `Buyer` attempts to act on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies only to the ownership-scoped write operations; read-only listing and retrieval endpoints accept the roles enumerated for each endpoint in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order — that is, oldest first.

Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a uniform set of system-managed fields. Every such resource exposes an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. Resources that may change after creation additionally expose an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that starts at its initial value and increments by one on every mutation of the resource.

One entity is deliberately append-only and therefore carries the reduced field set: a `Bid` is an immutable event. A bid record exposes only `id` and `created_at`; it has neither `updated_at` nor `version`, and it is never mutated after it is written. Every other entity in the system — sales, lanes, sellers, buyers, consignments, condition reports, lots, arbitration claims, settlements, gate passes, carriers, and transport orders — carries the full `id` / `created_at` / `updated_at` / `version` set.

Computed and system-managed fields are read-only: clients never set them directly. They are derived by the rules described throughout §3 and surface on the resource in API responses. When any such derived field changes as a side effect of an operation, that constitutes a mutation of its owning resource: `updated_at` is refreshed and `version` is incremented for the owning resource.

### 2.5. Nested and Referential Resolution Order

Several operations reference resources by identifiers in the URL path and by foreign keys in the request body. Path identifiers are validated left to right: the first identifier in the path that does not resolve to an existing resource causes immediate rejection with that resource's specific not-found error (for example, an operation addressed to a non-existent lot fails with `ERR_LOT_NOT_FOUND` before any body field is examined). Once path identifiers resolve, body foreign keys are validated, each against its own not-found error (`ERR_SALE_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_CONSIGNMENT_NOT_FOUND`, `ERR_CONDITION_REPORT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_GATE_PASS_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, and `ERR_TRANSPORT_NOT_FOUND`, as applicable). All resource not-found errors carry HTTP 404.

### 2.6. Validation Precedence

When a single request could fail several checks, the system evaluates them in a fixed precedence so that the returned error is deterministic. The order is: first, authentication context — the presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_AUTH_CONTEXT`); second, role permission for the operation (`ERR_FORBIDDEN_ROLE`); third, resource ownership for entity-backed `Seller` and `Buyer` callers (`ERR_NOT_RESOURCE_OWNER`); fourth, existence of every referenced resource, path identifiers left to right and then body foreign keys (the relevant not-found error); fifth, the target resource's state precondition for the requested transition (the transition's specific state error, all HTTP 409); sixth, cross-reference coherence between aggregates (`ERR_CROSS_SALE_REFERENCE`); seventh, temporal-window rules for lane slots and carrier pickups; and finally the remaining business-constraint, fiscal, and concurrency checks. Within the business tier the per-operation ordering is described alongside each workflow in §3. Malformed payloads — a missing required field, an unrecognized enum value, a non-positive amount where a positive one is required, or a window whose bounds are inverted — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.7. Monetary Precision and Rounding Discipline

All money in the system is represented and stored as integer cents; there are no fractional cents and no floating-point money. Wherever a calculation multiplies an amount by a percentage rate, the resulting term is rounded half up to a whole number of cents. The rounding discipline is strict and order-sensitive: each percentage-derived term is rounded to cents first, and only then are the rounded terms summed. The system never sums raw fractional terms and rounds once at the end; on prices that straddle a tier band, the two orders can differ by a cent, and only the round-each-term-then-sum order is correct. Counts (such as a lane's scheduled slots) are plain integers. Fields that are themselves input rates — for example a seller's commission rate — retain the precision supplied on input.

### 2.8. Provisional-versus-Final Calculation Principle

Three figures — the buyer's fee, the buyer's total amount due, and the seller's net proceeds — are computed twice over a lot's life. A **provisional** figure is computed the moment a sale is struck, from the hammer price. A **final** figure is recomputed later if the economics change: specifically when an arbitration ruling reduces the effective sale price. The provisional and final variants use identical formulas; they differ only in the sale-price input they consume. The provisional pass uses the frozen hammer price; the final pass uses the possibly-reduced effective sale price. Wherever §3 describes one of these figures, both the moment it is provisionally set and the moment it is finalized are specified.

### 2.9. Optimistic Concurrency on the Live Block

While a lot is taking bids, its standing price moves with each accepted bid, and each accepted bid advances the lot's `version`. To prevent a bidder from acting on a stale view of the standing price, bid placement is guarded by optimistic concurrency control on the lot. A bid-placement request must include `expected_lot_version`, carrying the `version` of the lot (the `RunListEntry`) that the client last observed. If `expected_lot_version` does not equal the lot's current `version` — because another bid was appended after the client read the lot, legitimately advancing the standing clearing price and the lot's version — the placement is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). The rejected bidder is expected to re-read the lot, observe the new standing price and version, and resubmit. This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.10. Buyer Credit as a Conserved Ledger

Each buying dealer holds a floor-plan credit line, and the system treats it as a conserved quantity. A buyer's `credit_limit_cents` is the total line. The read-only `committed_cents` is the sum of `total_due_cents` across that buyer's settlements whose `payment_status` is either `UNPAID` or `PAID` — settlements that have been reversed or written off are excluded from the sum. The read-only `available_credit_cents` is `credit_limit_cents` minus `committed_cents`; at registration, with no settlements yet, it equals `credit_limit_cents`. The invariant the system maintains at all times is that `available_credit_cents` plus `committed_cents` equals `credit_limit_cents`. Striking a sale debits the winning buyer's available credit by exactly the lot's `total_due_cents`; the compensating reversal or write-off re-credits exactly that same `total_due_cents`, so credit is conserved end to end.

### 2.11. Cascade Consistency Across Aggregates

Many of this system's operations touch more than one aggregate. A hammer creates a settlement and debits credit; a payment can clear a settlement, which in turn finalizes a lot, issues a gate pass, and settles a consignment; an arbitration ruling can unwind all of that. Each entity affected by a cascade is mutated in its own right — its derived fields recomputed, its `updated_at` refreshed, and its `version` incremented (except `Bid`, which is immutable and unversioned). The specific cascades, their preconditions, and the exact set of entities each one touches are described in the relevant §3 workflow. The principle here is only that cascades are not silent: every entity a cascade reaches is updated to a consistent state before the originating request returns.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Sale: Lanes and the Sale Lifecycle

A sale is the top-level container for a day of selling. An `AuctionAdmin` creates one by supplying a `sale_name` and a `sale_date`, and optionally a `buyer_fee_schedule_code` selecting which fee schedule applies to every lot in the sale; the schedule code is one of `STANDARD` or `PREMIUM` and defaults to `STANDARD` when omitted. A new sale begins in `DRAFT` and exposes a read-only `lane_count`, which starts at 0 and tracks the number of this sale's lanes whose status is not `ARCHIVED`.

The sale advances through a strict lifecycle: `DRAFT → OPEN → RUNNING → CLOSED → SETTLED`. Opening a sale moves it from `DRAFT` to `OPEN`; it is rejected with `ERR_SALE_NOT_IN_DRAFT` if the sale is not in `DRAFT`. Once `OPEN`, intake and run-list building are permitted. Starting a sale moves it from `OPEN` to `RUNNING`; it requires the sale to be `OPEN` (otherwise `ERR_SALE_NOT_OPEN`) and requires that at least one lane exists for the sale in `PLANNED` or `ACTIVE` status (otherwise `ERR_NO_LANES`). As a side effect of starting, every lane of the sale in `PLANNED` transitions to `ACTIVE`. Closing a sale moves it from `RUNNING` to `CLOSED`; it requires the sale to be `RUNNING` (otherwise `ERR_SALE_NOT_RUNNING`) and requires that no lot of the sale is still in `BIDDING_OPEN` (otherwise `ERR_LOTS_STILL_LIVE`); as a side effect, every lane of the sale in `ACTIVE` transitions to `CLOSED`. Settling a sale moves it from `CLOSED` to `SETTLED`, the terminal state; it requires the sale to be `CLOSED` (otherwise `ERR_SALE_NOT_CLOSED`) and requires that every settlement belonging to the sale has reached one of `CLEARED`, `VOID`, or `DEFAULTED` (otherwise `ERR_UNSETTLED_LOTS_EXIST`).

Lanes are the parallel tracks down which vehicles run. An `AuctionAdmin` creates a lane against a sale by supplying the owning `sale_id`, a `lane_number`, and the lane's operating window expressed in minutes from the sale's start: `open_minute` (inclusive) and `close_minute` (exclusive). The window must be well formed — `open_minute` is at least 0 and strictly less than `close_minute`, and `close_minute` is strictly greater than `open_minute`. The `lane_number` must be a positive integer and unique within its sale among lanes whose status is not `ARCHIVED`; a duplicate against a non-`ARCHIVED` lane is rejected with `ERR_DUPLICATE_LANE_NUMBER`, while a number previously held only by an `ARCHIVED` lane may be reused. Creating a lane recomputes the owning sale's `lane_count`. A new lane begins in `PLANNED` and exposes a read-only `scheduled_slot_count`, described in §3.4. A lane's lifecycle is `PLANNED → ACTIVE → CLOSED`, with `PLANNED → ARCHIVED` as a soft-removal terminal; `ACTIVE` and `CLOSED` are reached only by cascade from the sale's start and close. Archiving a lane is an admin action that moves it from `PLANNED` to `ARCHIVED`; it requires the lane to be `PLANNED` (otherwise `ERR_LANE_NOT_PLANNED`) and requires the lane's `scheduled_slot_count` to be 0 (otherwise `ERR_LANE_HAS_LOTS`). Archiving recomputes the owning sale's `lane_count`.

### 3.2. Dealers: Sellers and Buyers

Selling and buying dealers are registered once and reused across sales. An `AuctionAdmin` registers a seller with a `dealer_name` and an optional `seller_fee_pct` — the commission rate the house applies to that seller's hammer prices, which defaults to 0.02 and must lie between 0 and 0.10 inclusive. A seller begins `ACTIVE` and may be moved `ACTIVE → SUSPENDED` and back `SUSPENDED → ACTIVE` by an admin.

An `AuctionAdmin` registers a buyer with a `dealer_name` and a `credit_limit_cents`, the total floor-plan credit available to that dealer, which must be at least 0. On registration the buyer is `ACTIVE`, its `committed_cents` is 0, and its `available_credit_cents` equals its `credit_limit_cents`. The credit accounting that drives `committed_cents` and `available_credit_cents` is governed by §2.10. A buyer may be moved `ACTIVE → SUSPENDED` and `SUSPENDED → ACTIVE` by an admin; a suspended buyer may not place bids. Note that a buyer can also be suspended automatically as a consequence of a payment write-off, described in §3.9.

### 3.3. Consignment Intake and the Condition Report

A vehicle enters a sale as a consignment. A consignment may be created by either an `AuctionAdmin` or the owning `Seller`, supplying the `sale_id` the vehicle is consigned into, the consigning `seller_id`, the 17-character `vin`, and optionally the `title_status` indicating whether the title is in hand — one of `ABSENT` or `ON_HAND`, defaulting to `ABSENT`. A `Seller` may only consign under its own `seller_id`. The `vin` must be unique within its sale; a repeat is rejected with `ERR_DUPLICATE_VIN`. A consignment begins in `SUBMITTED` and exposes a read-only `expected_proceeds_cents` (the seller's net proceeds, provisional at hammer and final at clearing, computed per §3.8) and a `status` whose full lifecycle is `SUBMITTED → CATALOGED → RUN_LISTED → (SOLD | NO_SALE | IF_PENDING)`, with the re-run cycle `IF_PENDING → RUN_LISTED`, the settlement path `SOLD → SETTLED`, the arbitration unwind `SOLD → ARB_UNWOUND`, and the withdrawal path from either `SUBMITTED` or `CATALOGED` to `WITHDRAWN`.

Before a vehicle can be cataloged, it must be inspected. An `AuctionAdmin` attaches exactly one condition report to a consignment by supplying the `consignment_id`, the inspection `grade` (a number from 0.0 to 5.0 inclusive, in tenths), the `odometer_miles` (at least 0), and an optional `announcements` array of disclosed defects such as `FRAME_DAMAGE` or `TITLE_BRANDED`, which defaults to an empty list. The report exposes a read-only `as_is` flag that is true when the inspection `grade` is below 3.0 or the `announcements` array is non-empty, and false otherwise. The `as_is` flag matters downstream: an as-is sale is not arbitrable, and it removes the assurance fee from the seller's proceeds.

Cataloging is the admin action that prices the consignment's reserve and floor. It moves the consignment from `SUBMITTED` to `CATALOGED` and requires three things in order: the consignment must be in `SUBMITTED` (otherwise `ERR_CONSIGNMENT_NOT_SUBMITTED`); a condition report must already exist for the consignment (otherwise `ERR_CONDITION_REPORT_MISSING`); and the supplied floor must not exceed the supplied reserve (otherwise `ERR_FLOOR_ABOVE_RESERVE`). The request body supplies `reserve_price_cents` — the hidden seller minimum, at least 0, where 0 means absolute no-reserve — and `floor_price_cents`, the house proxy floor bid placed on the seller's behalf, which must be between 0 and `reserve_price_cents` inclusive. Both values are persisted onto the consignment as a side effect of cataloging.

A consignment can be withdrawn before it sells. Withdrawing is permitted to an `AuctionAdmin` or the owning `Seller` and moves the consignment to `WITHDRAWN`; it is allowed only while the consignment is in `SUBMITTED` or `CATALOGED` (otherwise `ERR_CONSIGNMENT_NOT_WITHDRAWABLE`).

### 3.4. Building the Run List and Lane Slot Scheduling

Run-listing places a cataloged vehicle into a specific lane slot so it can run on the block. An `AuctionAdmin` creates a lot (a run-list entry) by supplying the owning `sale_id`, the `consignment_id` of the cataloged vehicle, the `lane_id` of the lane it will run in, a `run_number` giving its sequence position within the lane, the run window `slot_start_minute` (inclusive) and `slot_end_minute` (exclusive), and the `starting_bid_cents` the auctioneer opens at (at least 0). Creating a lot starts it in `SCHEDULED`, cascades the referenced consignment from `CATALOGED` to `RUN_LISTED`, and recomputes the lane's `scheduled_slot_count`.

Several constraints guard lot creation, and they are checked in this order after existence resolution. Cross-aggregate coherence comes first: the lot's `lane_id` and `consignment_id` must both belong to the same sale as the lot's `sale_id`; a reference that crosses sales is rejected with `ERR_CROSS_SALE_REFERENCE`. Next comes the temporal window check: the slot interval, treated as half-open `[slot_start_minute, slot_end_minute)`, must lie entirely within the lane's operating window — `slot_start_minute` at least the lane's `open_minute` and strictly less than `slot_end_minute`, and `slot_end_minute` strictly greater than `slot_start_minute` and at most the lane's `close_minute`, a slot that falls outside this window being rejected with `ERR_LANE_SLOT_OVERLAP` — and it must not overlap the slot of any other lot in the same lane that is not `WITHDRAWN` or `PASSED`; because intervals are half-open, two slots that merely touch (the end of one equal to the start of the next, a gap of zero) do not overlap and are allowed, but any positive overlap is rejected with `ERR_LANE_SLOT_OVERLAP`. Finally, the `run_number` must be a positive integer unique within its lane; a duplicate is rejected with `ERR_DUPLICATE_RUN_NUMBER`.

A lane's `scheduled_slot_count` is, at all times, the number of lots in that lane whose status is neither `WITHDRAWN` nor `PASSED`. The count is maintained as a conserved running total: creating a lot increments it by one, and the compensating withdraw or pass of a lot decrements it by one, so the lane's active-slot count tracks exactly the set of lots still occupying a slot. This count is recomputed on lot creation, on lot withdraw, on lot pass, and is read by the lane-archive precondition.

A lot's status lifecycle is `SCHEDULED → BIDDING_OPEN → BIDDING_CLOSED → (HAMMERED | PASSED | IF_PENDING)`, with `HAMMERED → FINALIZED` and `HAMMERED → ARB_REVERSED` as the post-sale forks, the re-list cycle `IF_PENDING → SCHEDULED`, and `SCHEDULED → WITHDRAWN`. A scheduled lot may be withdrawn by an admin while it is `SCHEDULED` (otherwise `ERR_LOT_NOT_SCHEDULED`); withdrawing recomputes the lane's `scheduled_slot_count` and, if no other active lot references the consignment, cascades the consignment from `RUN_LISTED` back to `NO_SALE`.

### 3.5. Running the Block: Opening Bidding, Bids, and the Clearing Price

Opening a lot for bidding is an admin action that moves it from `SCHEDULED` to `BIDDING_OPEN`. It requires the lot to be `SCHEDULED` (otherwise `ERR_LOT_NOT_SCHEDULED`), the owning sale to be `RUNNING` (otherwise `ERR_SALE_NOT_RUNNING`), and the referenced lane to be `ACTIVE` (otherwise `ERR_LANE_NOT_ACTIVE`). On opening, the lot's standing high bid is initialized: `high_bid_cents` is set to the greater of the lot's `starting_bid_cents` and the consignment's `floor_price_cents`, and `high_bidder_id` is set to null, reflecting that only the house floor stands until a real bidder arrives.

A `Buyer` places a bid on a lot that is open for bidding. The bid body carries the bidder's `buyer_id`, the `bid_type` — `LIVE` for an exact one-shot bid or `PROXY` for an autobid up to a ceiling — the `amount_cents` (which for a `LIVE` bid is the bid amount and for a `PROXY` bid is the autobid ceiling, and must be greater than 0), the required `expected_lot_version` (see §2.9), and an optional `channel` of `LANE` or `ONLINE` that records where the bid originated and defaults to `ONLINE`. A buyer may only bid under its own `buyer_id`. Each accepted bid is appended as an immutable, `PLACED` event whose read-only `ceiling_cents` is normalized to equal its `amount_cents`; the system then recomputes the lot's standing clearing price (updating `high_bid_cents` and `high_bidder_id`) and increments the lot's `version` by one. A bid never undergoes any further transition — it is append-only, and it is the lot, not the bid, that carries the OCC `version`.

Bid acceptance enforces, in order: the lot must be `BIDDING_OPEN` (otherwise `ERR_LOT_NOT_BIDDING_OPEN`); the buyer must be `ACTIVE` (otherwise `ERR_BUYER_SUSPENDED`); the `expected_lot_version` must match the lot's current `version`, else `ERR_STALE_LOT_VERSION` per §2.9; the bid must clear the minimum increment rule (otherwise `ERR_BID_BELOW_MINIMUM`); and the buyer must have enough available credit to cover the projected total due were this bid to win (otherwise `ERR_INSUFFICIENT_CREDIT`, HTTP 402). The minimum-acceptable-bid rule is this: when a buyer high bid already stands on the lot, the new `amount_cents` must be at least the current `high_bid_cents` plus the applicable bid increment; when no buyer high bid stands yet (only the house floor), the new `amount_cents` must be at least the current `high_bid_cents`. The credit check projects what this buyer's `total_due_cents` would be if it won at the resulting standing price and requires the buyer's `available_credit_cents` to be at least that projection.

The **bid increment** is selected by a price band off a reference price, expressed in cents. For a reference price below 500000 (under $5,000), the increment is 10000 ($100). For a reference price from 500000 up to but not including 1000000 ($5,000 through $9,999.99), the increment is 25000 ($250). For a reference price of 1000000 or more (at least $10,000), the increment is 50000 ($500). The band boundaries are taken on the lower band's exclusion and the upper band's inclusion: a reference price of exactly 500000 uses 25000, and a reference price of exactly 1000000 uses 50000. Increments are exact integer cents with no rounding.

The **clearing price** is the heart of the block, recomputed after every appended bid and frozen at hammer. Begin by defining the house floor as the greater of the lot's `starting_bid_cents` and the consignment's `floor_price_cents`. Consider all bids on the lot grouped by `buyer_id`; each buyer's effective ceiling is the maximum `ceiling_cents` among that buyer's own bids. A `LIVE` bid is treated as a proxy whose ceiling equals its `amount_cents`, so every bid contributes a ceiling. Rank the buyers by effective ceiling, highest first; when two buyers tie on effective ceiling, the buyer whose qualifying maximum-ceiling bid has the earliest `created_at` ranks ahead (ties are broken only by time, never by `id`). Three cases follow. If no buyer has bid, `high_bidder_id` is null and `high_bid_cents` is the house floor. If exactly one buyer has bid, with ceiling C1, then `high_bidder_id` is that buyer and `high_bid_cents` is the lesser of C1 and the greater of the house floor and the lot's `starting_bid_cents` — that is, the single bidder need only beat the house floor, and the standing price never rises above that bidder's own ceiling. If two or more buyers have bid, with top ceiling C1 (buyer B1) and second-highest ceiling C2, then `high_bidder_id` is B1, and `high_bid_cents` is the lesser of C1 and the quantity `(second reference plus one bid increment computed on that second reference)`, where the second reference is the greater of C2 and the house floor. All amounts remain integer cents, and the increment in the two-or-more case is the one selected by the band of the second reference.

### 3.6. Closing, Hammering, and the Sale Outcome

When the auctioneer is done taking bids, an admin closes the lot, moving it from `BIDDING_OPEN` to `BIDDING_CLOSED`; this requires the lot to be `BIDDING_OPEN` (otherwise `ERR_LOT_NOT_BIDDING_OPEN`) and freezes the standing `high_bid_cents` and `high_bidder_id` so the outcome can be evaluated against a stable price.

The **sale outcome** is determined from the frozen high bid: if `high_bidder_id` is null, the outcome is `PASSED`; otherwise, if `high_bid_cents` is at least the consignment's `reserve_price_cents`, the outcome is `SOLD`; otherwise the outcome is `IF`. The reserve threshold is inclusive — a frozen high bid exactly equal to the reserve sells — and because a no-reserve consignment carries a `reserve_price_cents` of 0, any buyer high bid on it sells. The lot's read-only `outcome` field records this result and is one of `NONE`, `SOLD`, `IF`, or `PASSED`, starting at `NONE`.

From `BIDDING_CLOSED` the admin drives the lot down one of three mutually exclusive paths, each guarded by the computed outcome. Hammering moves the lot to `HAMMERED` and requires the lot to be `BIDDING_CLOSED` (otherwise `ERR_LOT_NOT_BIDDING_CLOSED`) and the outcome to compute to `SOLD`, meaning `high_bidder_id` is not null and `high_bid_cents` is at least the reserve (otherwise `ERR_OUTCOME_NOT_SOLD`). Marking a lot if-bid moves it to `IF_PENDING` and requires the lot to be `BIDDING_CLOSED` (otherwise `ERR_LOT_NOT_BIDDING_CLOSED`) and the outcome to compute to `IF`, meaning `high_bidder_id` is not null but `high_bid_cents` is below the reserve (otherwise `ERR_OUTCOME_NOT_IF`). Passing a lot moves it to `PASSED` and requires the lot to be `BIDDING_CLOSED` (otherwise `ERR_LOT_NOT_BIDDING_CLOSED`) and the outcome to compute to `PASSED`, meaning `high_bidder_id` is null (otherwise `ERR_OUTCOME_NOT_PASSED`).

The three paths carry sharply different side effects. **Hammering** also enforces cross-aggregate coherence: the settlement it creates pairs the consignment with its seller, so the settlement's `seller_id` must equal the consignment's `seller_id`; an incoherent pairing across aggregates is rejected with `ERR_CROSS_SALE_REFERENCE`. Hammering then sets the lot's `outcome` to `SOLD`, freezes `hammer_price_cents` to the standing `high_bid_cents`, and triggers the settlement cascade: it advances the consignment from `RUN_LISTED` to `SOLD` (setting the consignment's `expected_proceeds_cents` to the provisional seller-net-proceeds figure of §3.8); it creates a settlement for the lot, the winning buyer (`high_bidder_id`), and the consignment's seller, starting that settlement with `payment_status` of `UNPAID` and `title_status` of `PENDING_TITLE` and computing its provisional `sale_price_cents` (equal to `hammer_price_cents`), `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents`; and it debits the winning buyer's `available_credit_cents` by that `total_due_cents`, recomputing `committed_cents`. **Marking if-bid** sets the lot's `outcome` to `IF` and cascades the consignment from `RUN_LISTED` to `IF_PENDING`. **Passing** sets the lot's `outcome` to `PASSED`, cascades the consignment from `RUN_LISTED` to `NO_SALE`, and recomputes the lane's `scheduled_slot_count` because a passed lot leaves the active-slot set.

An if-bid lot gets a second chance. Re-listing moves a lot from `IF_PENDING` back to `SCHEDULED` and requires the lot to be `IF_PENDING` (otherwise `ERR_LOT_NOT_IF_PENDING`) and the owning sale to be `RUNNING` (otherwise `ERR_SALE_NOT_RUNNING`). Re-listing resets the lot's `high_bid_cents` to 0, `high_bidder_id` to null, and `outcome` to `NONE`, and cascades the consignment from `IF_PENDING` back to `RUN_LISTED`, so the vehicle can run again.

### 3.7. The Buyer's Fee and Total Due

When a settlement is created at hammer, the system computes the buyer's fee provisionally, and it recomputes it finally if arbitration later reduces the sale price (§2.8). The fee depends on three inputs: the settlement's `sale_price_cents`, the sale's `buyer_fee_schedule_code`, and the channel of the winning bid (the `channel` of the high bidder's maximum-ceiling bid frozen at hammer).

The base fee is a flat amount selected by price band — the band's rule applies as a flat per-band figure, never marginally across bands. Under the `STANDARD` schedule: for a sale price below 200000 (under $2,000) the base is 12500; for a sale price from 200000 up to but not including 1000000 the base is 6% of the sale price, rounded half up to cents; for a sale price of 1000000 or more the base is 4% of the sale price rounded half up to cents, plus an additional 20000. Under the `PREMIUM` schedule: for a sale price below 200000 the base is 17500; for a sale price from 200000 up to but not including 1000000 the base is 8% of the sale price rounded half up to cents; for a sale price of 1000000 or more the base is 5% of the sale price rounded half up to cents, plus an additional 25000. On top of the base, an online surcharge applies: if the winning bid's `channel` is `ONLINE`, the surcharge is 10% of the base rounded half up to cents; if the channel is `LANE`, the surcharge is 0. The `buyer_fee_cents` is the base plus the surcharge. Each percentage term is rounded to cents before any addition, in keeping with §2.7.

The buyer's `total_due_cents` is the settlement's `sale_price_cents` plus its `buyer_fee_cents`. Because `buyer_fee_cents` is itself the sum of two already-rounded integer terms (base and surcharge), the total is a sum of integer cents with no further rounding. The order is mandatory: round each percentage-derived term to cents first, then sum — never sum raw fractional terms and round once.

### 3.8. The Seller's Net Proceeds

The seller's net proceeds are computed provisionally when the consignment reaches `SOLD` at hammer and finalized when the settlement clears (or after an arbitration partial adjustment). The provisional pass uses the hammer price as the sale price; the final pass uses the settlement's `sale_price_cents`, which may have been reduced by an arbitration credit, yielding a lower commission and lower proceeds. The inputs are the sale price, the seller's `seller_fee_pct`, and the condition report's `as_is` flag.

The seller commission is the sale price multiplied by `seller_fee_pct`, rounded half up to cents, and then capped at 150000 — that is, the commission is the lesser of the rounded figure and 150000. The assurance fee, which funds the arbitration-assurance pool, is 0 when the condition report's `as_is` is true and 5000 otherwise. The seller's net proceeds are the sale price minus the seller commission minus the assurance fee, floored at 0 so the figure is never negative. The provisional result is written to the consignment's `expected_proceeds_cents` at hammer and to the settlement's `seller_proceeds_cents`; the final result is written when the settlement clears and is mirrored back onto the consignment's `expected_proceeds_cents`.

### 3.9. Settlement: Payment, Title, Clearing, and Default

A settlement is the financial record of a struck sale; it is created automatically at hammer (§3.6) and is never created directly by a client. It references the `lot_id`, the paying `buyer_id`, and the paid `seller_id`, and exposes the computed money fields `sale_price_cents`, `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents`. Its state is carried on two independent axes plus a derived rollup. The payment axis, `payment_status`, runs `UNPAID → PAID → REVERSED` with the alternative `UNPAID → WRITTEN_OFF`. The title axis, `title_status`, runs `PENDING_TITLE → TITLE_RECEIVED`. The derived `status` rolls the two axes up: it is `OPEN` while the settlement is neither paid-and-titled nor terminated; `CLEARED` once `payment_status` is `PAID` and `title_status` is `TITLE_RECEIVED`; `VOID` once `payment_status` is `REVERSED`; and `DEFAULTED` once `payment_status` is `WRITTEN_OFF`.

Recording payment is an admin action on the payment axis. It requires the settlement's `payment_status` to be `UNPAID` (otherwise `ERR_SETTLEMENT_NOT_UNPAID`) and the referenced lot to be `HAMMERED` (otherwise `ERR_LOT_NOT_HAMMERED`); it advances `payment_status` from `UNPAID` to `PAID` and recomputes the derived `status`. Recording title is an admin action on the title axis. It requires the settlement's `title_status` to be `PENDING_TITLE` (otherwise `ERR_TITLE_ALREADY_RECEIVED`); it advances `title_status` from `PENDING_TITLE` to `TITLE_RECEIVED` and recomputes the derived `status`. The two axes advance independently — payment may precede title or vice versa.

Whenever recording payment or title leaves the settlement with `payment_status` of `PAID` and `title_status` of `TITLE_RECEIVED`, the settlement clears automatically. **Clearing** is a four-deep transitive cascade: the derived `status` becomes `CLEARED`; the settlement's `seller_proceeds_cents` is recomputed as the final seller-net-proceeds figure (§3.8) and mirrored onto the consignment's `expected_proceeds_cents`; the lot cascades from `HAMMERED` to `FINALIZED`; a gate pass is auto-issued in `ISSUED` status for the settlement and buyer (§3.10); and the consignment cascades from `SOLD` to `SETTLED`.

A buyer who never pays is written off. Writing off a settlement is an admin action requiring the settlement's `payment_status` to be `UNPAID` (otherwise `ERR_SETTLEMENT_NOT_UNPAID`) and the referenced sale to be `CLOSED` (otherwise `ERR_SALE_NOT_CLOSED`). It advances `payment_status` from `UNPAID` to `WRITTEN_OFF` and sets the derived `status` to `DEFAULTED`; it re-credits the buyer's `available_credit_cents` by the settlement's `total_due_cents` (recomputing `committed_cents`); and it suspends the buyer, moving the buyer from `ACTIVE` to `SUSPENDED`.

### 3.10. Arbitration: Disputes and Unwinds

After a sale is struck and paid, the winning buyer may dispute the vehicle within the arbitration policy. A `Buyer` opens an arbitration claim by supplying the disputed `lot_id`, its own `buyer_id` (which must be the winning buyer), a `reason_code` of `UNDISCLOSED_DAMAGE`, `TITLE_DISCREPANCY`, or `MECHANICAL`, and the `claimed_cents` adjustment requested (greater than 0). A claim begins in `OPEN` status with a read-only `resolution` of `PENDING` and a read-only `approved_cents` of 0. The claim's `resolution` ultimately becomes one of `APPROVED_FULL`, `APPROVED_PARTIAL`, or `DENIED`.

An `Arbitrator` rules on a claim, moving it from `OPEN` to `RESOLVED` (the terminal state). Ruling requires the claim to be `OPEN` (otherwise `ERR_CLAIM_NOT_OPEN`) and the referenced lot's settlement to have `payment_status` of `PAID` (otherwise `ERR_SETTLEMENT_NOT_PAID`). The ruling decides the **arbitration credit** as follows, from the claimed amount, the settlement's `sale_price_cents`, the `reason_code`, and the condition report's `as_is` and `grade`. If the condition report's `as_is` is true, the sale is not arbitrable: `approved_cents` is 0 and the `resolution` is `DENIED`. Otherwise, compute the policy cap as 30% of the settlement's `sale_price_cents`, rounded half up to cents, and decide: if the `claimed_cents` is at least the sale price, the claim meets or exceeds the price and triggers a full unwind — `approved_cents` equals the sale price and the `resolution` is `APPROVED_FULL`; otherwise, if the `claimed_cents` is at most the cap, `approved_cents` equals the `claimed_cents` and the `resolution` is `APPROVED_PARTIAL`; otherwise the claim exceeds the cap and `approved_cents` equals the cap with `resolution` `APPROVED_PARTIAL`. The cap boundary is inclusive: a `claimed_cents` exactly equal to the cap is approved partial at the full claimed amount, not capped.

The ruling's economic side effects diverge by resolution branch. On `APPROVED_PARTIAL`: the settlement's `sale_price_cents` is reduced by `approved_cents`; the final `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents` are recomputed on the reduced sale price (which can drop the fee into a lower tier band, changing the fee); and the buyer is re-credited by the difference between the old total due and the new total due. On `APPROVED_FULL`: the settlement is unwound — it cascades to the void path described next. On `DENIED`: there is no economic change. In all branches the ruling sets the claim's `approved_cents` and `resolution`.

A full-approval unwind voids the settlement. The settlement's `payment_status` moves from `PAID` to `REVERSED` and its derived `status` becomes `VOID`; the buyer's `available_credit_cents` is re-credited by the full `total_due_cents` (recomputing `committed_cents`), fully returning the committed amount; the lot cascades from `HAMMERED` to `ARB_REVERSED`; the consignment cascades from `SOLD` to `ARB_UNWOUND`, with its `expected_proceeds_cents` set to 0; and if a gate pass exists for the settlement in `ISSUED` status, it is voided, moving from `ISSUED` to `VOID`. The settlement-void, buyer re-credit, and gate-pass-void steps above are unconditional (the gate-pass step being gated only on a gate pass existing in `ISSUED` status), but the lot and consignment cascades are each gated on their source state: the lot is moved to `ARB_REVERSED` only if it is currently `HAMMERED`, and the consignment is moved to `ARB_UNWOUND` with its `expected_proceeds_cents` set to 0 only if it is currently `SOLD`. In particular, when the settlement has already cleared before the full-approval ruling — so the lot is `FINALIZED`, the consignment is `SETTLED`, and a gate pass stands `ISSUED` — the settlement is still voided, the buyer still re-credited, and the gate pass still voided, but the lot remains `FINALIZED` and the consignment remains `SETTLED` with its `expected_proceeds_cents` left unchanged (not zeroed).

### 3.11. Releasing the Vehicle: Gate Passes and Transport

A gate pass authorizes physical release of a cleared vehicle. It is never created directly; it is auto-issued in `ISSUED` status when a settlement clears (§3.9), referencing the originating `settlement_id` and the releasing `buyer_id`. A gate pass moves `ISSUED → REDEEMED` on redemption or `ISSUED → VOID` when its settlement is voided by a full-approval arbitration unwind. Redeeming a gate pass is an admin action requiring the gate pass to be `ISSUED` (otherwise `ERR_GATE_PASS_NOT_ISSUED`) and requiring that a transport order exists for the same settlement in `DISPATCHED` status (otherwise `ERR_NO_DISPATCHED_TRANSPORT`).

Transport moves the vehicle off the lot. Carriers are registered once by an `AuctionAdmin` with a `carrier_name` and an optional `turnaround_buffer_minutes` — the mandatory buffer the carrier needs between two of its pickups, at least 0, defaulting to 30. A carrier begins `ACTIVE` and may be moved `ACTIVE → SUSPENDED` and back by an admin.

A transport order books a carrier to move a settled vehicle. It may be created by an `AuctionAdmin` or the owning `Buyer`, supplying the `settlement_id` whose vehicle is being moved, the booked `carrier_id`, and the pickup window in absolute minutes-of-day: `pickup_start_minute` (inclusive) and `pickup_end_minute` (inclusive), with `pickup_start_minute` at least 0 and strictly less than `pickup_end_minute`, and `pickup_end_minute` strictly greater than `pickup_start_minute`. A `Buyer` may only book under its own `buyer_id` ownership, where the order's owning buyer is the referenced settlement's `buyer_id`; because that ownership is derived from the settlement, the referenced `settlement_id` and `carrier_id` are resolved for existence first, and only then is the buyer-ownership check applied (a `Buyer` whose `X-User-ID` does not equal the settlement's `buyer_id` is rejected with `ERR_NOT_RESOURCE_OWNER`). The pickup window is validated against the carrier's other commitments: treating each pickup window as a closed interval, the new window must keep a gap of at least the carrier's `turnaround_buffer_minutes` from every other non-`CANCELLED` transport order on the same carrier; a window that does not preserve that buffered closed-interval separation is rejected with `ERR_CARRIER_WINDOW_CONFLICT`. A transport order begins in `REQUESTED` and runs `REQUESTED → DISPATCHED → DELIVERED`, with `REQUESTED → CANCELLED` as the early-exit path.

Dispatching is an admin action moving the order from `REQUESTED` to `DISPATCHED`; it requires the order to be `REQUESTED` (otherwise `ERR_TRANSPORT_NOT_REQUESTED`), the referenced settlement to be `CLEARED` (otherwise `ERR_SETTLEMENT_NOT_CLEARED`), and the carrier to be `ACTIVE` (otherwise `ERR_CARRIER_SUSPENDED`). Delivering is an admin action moving the order from `DISPATCHED` to `DELIVERED`; it requires the order to be `DISPATCHED` (otherwise `ERR_TRANSPORT_NOT_DISPATCHED`). Cancelling is permitted to an `AuctionAdmin` or the owning `Buyer` and moves the order from `REQUESTED` to `CANCELLED`; it requires the order to be `REQUESTED` (otherwise `ERR_TRANSPORT_NOT_REQUESTED`).

### 3.12. Discovering Related Records

Because the model is a flat set of peer collections joined by foreign keys carried in bodies, reverse navigation is provided through filtered list endpoints rather than nested paths. A lot's bids are discovered by listing bids filtered by `lot_id`; a buyer's bids by listing bids filtered by `buyer_id`. Consignments can be filtered by `sale_id`, `seller_id`, or `status`; lots by `sale_id`, `consignment_id`, `lane_id`, or `status`; condition reports by `consignment_id`; settlements by `lot_id`, `buyer_id`, `seller_id`, or `status`; gate passes by `settlement_id`, `buyer_id`, or `status`; transport orders by `settlement_id`, `carrier_id`, or `status`; lanes by `sale_id` or `status`; and arbitration claims by `lot_id`, `buyer_id`, or `status`. Sales, sellers, buyers, and carriers can be filtered by `status`. All list endpoints honor the pagination and sort rules of §2.3.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition — return `200 OK`. Read operations return `200 OK`. All endpoints are mounted under the `/auction` prefix shown in the table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/auction/sales` | Create a sale (DRAFT) | AuctionAdmin |
| GET | `/auction/sales` | List sales | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/sales/{saleId}` | Get a sale | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/sales/{saleId}/open` | Open a sale | AuctionAdmin |
| POST | `/auction/sales/{saleId}/start` | Start a sale; activate lanes | AuctionAdmin |
| POST | `/auction/sales/{saleId}/close` | Close a sale; close lanes | AuctionAdmin |
| POST | `/auction/sales/{saleId}/settle` | Settle a sale | AuctionAdmin |
| POST | `/auction/lanes` | Create a lane (PLANNED) | AuctionAdmin |
| GET | `/auction/lanes` | List/filter lanes | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/lanes/{laneId}` | Get a lane | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/lanes/{laneId}/archive` | Archive an empty lane | AuctionAdmin |
| POST | `/auction/sellers` | Register a selling dealer | AuctionAdmin |
| GET | `/auction/sellers` | List sellers | AuctionAdmin, Seller |
| GET | `/auction/sellers/{sellerId}` | Get a seller | AuctionAdmin, Seller |
| POST | `/auction/sellers/{sellerId}/suspend` | Suspend a seller | AuctionAdmin |
| POST | `/auction/sellers/{sellerId}/reinstate` | Reinstate a seller | AuctionAdmin |
| POST | `/auction/buyers` | Register a buying dealer | AuctionAdmin |
| GET | `/auction/buyers` | List buyers | AuctionAdmin, Buyer |
| GET | `/auction/buyers/{buyerId}` | Get a buyer | AuctionAdmin, Buyer |
| POST | `/auction/buyers/{buyerId}/suspend` | Suspend a buyer | AuctionAdmin |
| POST | `/auction/buyers/{buyerId}/reinstate` | Reinstate a buyer | AuctionAdmin |
| POST | `/auction/consignments` | Consign a vehicle (SUBMITTED) | AuctionAdmin, Seller |
| GET | `/auction/consignments` | List/filter consignments | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/consignments/{consignmentId}` | Get a consignment | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/consignments/{consignmentId}/catalog` | Catalog; set reserve/floor | AuctionAdmin |
| POST | `/auction/consignments/{consignmentId}/withdraw` | Withdraw a consignment | AuctionAdmin, Seller |
| POST | `/auction/condition-reports` | Attach a condition report | AuctionAdmin |
| GET | `/auction/condition-reports` | List/filter condition reports | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/condition-reports/{conditionReportId}` | Get a condition report | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/lots` | Run-list a consignment into a slot | AuctionAdmin |
| GET | `/auction/lots` | List/filter lots | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/lots/{lotId}` | Get a lot | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/lots/{lotId}/open-bidding` | Open bidding on a lot | AuctionAdmin |
| POST | `/auction/lots/{lotId}/close-bidding` | Close bidding on a lot | AuctionAdmin |
| POST | `/auction/lots/{lotId}/hammer` | Hammer a lot SOLD; create settlement | AuctionAdmin |
| POST | `/auction/lots/{lotId}/mark-if` | Mark a lot IF | AuctionAdmin |
| POST | `/auction/lots/{lotId}/pass` | Pass a lot | AuctionAdmin |
| POST | `/auction/lots/{lotId}/relist` | Re-list an if-bid lot | AuctionAdmin |
| POST | `/auction/lots/{lotId}/withdraw` | Withdraw a scheduled lot | AuctionAdmin |
| POST | `/auction/lots/{lotId}/bids` | Place a LIVE or PROXY bid | Buyer |
| GET | `/auction/bids` | List/filter bids | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/bids/{bidId}` | Get a bid | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/arbitration-claims` | Open an arbitration claim | Buyer |
| GET | `/auction/arbitration-claims` | List/filter claims | AuctionAdmin, Buyer, Arbitrator |
| GET | `/auction/arbitration-claims/{claimId}` | Get a claim | AuctionAdmin, Buyer, Arbitrator |
| POST | `/auction/arbitration-claims/{claimId}/rule` | Rule on a claim | Arbitrator |
| GET | `/auction/settlements` | List/filter settlements | AuctionAdmin, Seller, Buyer, Arbitrator |
| GET | `/auction/settlements/{settlementId}` | Get a settlement | AuctionAdmin, Seller, Buyer, Arbitrator |
| POST | `/auction/settlements/{settlementId}/record-payment` | Record payment received | AuctionAdmin |
| POST | `/auction/settlements/{settlementId}/record-title` | Record title received | AuctionAdmin |
| POST | `/auction/settlements/{settlementId}/write-off` | Write off an unpaid settlement | AuctionAdmin |
| GET | `/auction/gate-passes` | List/filter gate passes | AuctionAdmin, Buyer |
| GET | `/auction/gate-passes/{gatePassId}` | Get a gate pass | AuctionAdmin, Buyer |
| POST | `/auction/gate-passes/{gatePassId}/redeem` | Redeem a gate pass | AuctionAdmin |
| POST | `/auction/carriers` | Register a transport carrier | AuctionAdmin |
| GET | `/auction/carriers` | List carriers | AuctionAdmin, Buyer |
| GET | `/auction/carriers/{carrierId}` | Get a carrier | AuctionAdmin, Buyer |
| POST | `/auction/carriers/{carrierId}/suspend` | Suspend a carrier | AuctionAdmin |
| POST | `/auction/transport-orders` | Book transport (REQUESTED) | AuctionAdmin, Buyer |
| GET | `/auction/transport-orders` | List/filter transport orders | AuctionAdmin, Buyer |
| GET | `/auction/transport-orders/{transportOrderId}` | Get a transport order | AuctionAdmin, Buyer |
| POST | `/auction/transport-orders/{transportOrderId}/dispatch` | Dispatch a transport order | AuctionAdmin |
| POST | `/auction/transport-orders/{transportOrderId}/deliver` | Deliver a transport order | AuctionAdmin |
| POST | `/auction/transport-orders/{transportOrderId}/cancel` | Cancel a transport order | AuctionAdmin, Buyer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_LANE_NOT_FOUND` | 404 Not Found |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_BUYER_NOT_FOUND` | 404 Not Found |
| `ERR_CONSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONDITION_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_BID_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GATE_PASS_NOT_FOUND` | 404 Not Found |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSPORT_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_SALE_NOT_OPEN` | 409 Conflict |
| `ERR_SALE_NOT_RUNNING` | 409 Conflict |
| `ERR_SALE_NOT_CLOSED` | 409 Conflict |
| `ERR_NO_LANES` | 409 Conflict |
| `ERR_LOTS_STILL_LIVE` | 409 Conflict |
| `ERR_UNSETTLED_LOTS_EXIST` | 409 Conflict |
| `ERR_LANE_NOT_PLANNED` | 409 Conflict |
| `ERR_LANE_HAS_LOTS` | 409 Conflict |
| `ERR_LANE_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_LANE_NUMBER` | 409 Conflict |
| `ERR_CONSIGNMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CONDITION_REPORT_MISSING` | 409 Conflict |
| `ERR_FLOOR_ABOVE_RESERVE` | 409 Conflict |
| `ERR_CONSIGNMENT_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_DUPLICATE_VIN` | 409 Conflict |
| `ERR_CROSS_SALE_REFERENCE` | 409 Conflict |
| `ERR_LANE_SLOT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_RUN_NUMBER` | 409 Conflict |
| `ERR_LOT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_LOT_NOT_BIDDING_OPEN` | 409 Conflict |
| `ERR_LOT_NOT_BIDDING_CLOSED` | 409 Conflict |
| `ERR_LOT_NOT_IF_PENDING` | 409 Conflict |
| `ERR_LOT_NOT_HAMMERED` | 409 Conflict |
| `ERR_OUTCOME_NOT_SOLD` | 409 Conflict |
| `ERR_OUTCOME_NOT_IF` | 409 Conflict |
| `ERR_OUTCOME_NOT_PASSED` | 409 Conflict |
| `ERR_BUYER_SUSPENDED` | 409 Conflict |
| `ERR_BID_BELOW_MINIMUM` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_CLAIM_NOT_OPEN` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAID` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_UNPAID` | 409 Conflict |
| `ERR_TITLE_ALREADY_RECEIVED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_CLEARED` | 409 Conflict |
| `ERR_GATE_PASS_NOT_ISSUED` | 409 Conflict |
| `ERR_NO_DISPATCHED_TRANSPORT` | 409 Conflict |
| `ERR_CARRIER_SUSPENDED` | 409 Conflict |
| `ERR_CARRIER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRANSPORT_NOT_REQUESTED` | 409 Conflict |
| `ERR_TRANSPORT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
</content>
</invoke>
