# Auction House API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auction House API, the transactional backbone of an antiques and estate-sale auction business that runs live, online, and timed sales side by side. The platform must carry an object from the moment it arrives on a consignor's estate — through appraisal, cataloging, and the fall of the hammer — all the way to a paid buyer invoice and a disbursed seller payout. Along the way it enforces the pricing rules that make an auction house solvent: tiered buyer's premiums, escalating bid increments, storage accrual on unclaimed goods, and seller commissions.

The domain is unforgiving of ambiguity because money changes hands at every step and multiple parties act on the same object at once. A live paddle bid and an online bid may land on the same lot; an appraiser may overturn a sale weeks later on authenticity grounds, unwinding an invoice line, a hammer, and a seller statement in one cascade. The API therefore treats every mutation as a precisely ordered, versioned event, and models the buyer invoice as two independent axes — how much has been paid, and how the goods will be released — so that payment and fulfillment never block one another artificially. This specification defines the entities, their lifecycles, the exact arithmetic of every fee, and the validation order that keeps the ledger honest.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `AuctionStaff`, `Appraiser`, `SettlementOfficer`, `Consignor`, and `Bidder`.

Three of these are operational roles whose identity is opaque. When `X-User-Role` is `AuctionStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `Appraiser`, and when `X-User-Role` is `SettlementOfficer`: in each case the identifier names a staff operator, not a stored record. `AuctionStaff` owns venue, principal, sale, catalog, sale-running, and fulfillment operations; `Appraiser` values consignments and adjudicates authenticity disputes; `SettlementOfficer` approves and disburses seller payouts.

The other two roles are entity-backed principals who may act only on their own resources. When `X-User-Role` is `Consignor`, `X-User-ID` is the `id` of the acting `Consignor`; any ownership check on a resource that references a consignor compares the resource's `consignor_id` to `X-User-ID`. When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Bidder`; ownership checks compare a resource's `bidder_id` to `X-User-ID` — this binds a `Bidder` to the bids, invoices, and disputes they own. When an entity-backed principal targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check guards bid placement, invoice payment, dispute filing, and consignment submission by a `Consignor`.

All read (GET) endpoints are available to every one of the five roles.

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

All list endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order; ties among items sharing the same `created_at` are broken by ascending order of original creation (insertion) sequence. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource in the system — `Consignor`, `Bidder`, `Saleroom`, `Auction`, `Consignment`, `Lot`, `Bid`, `Invoice`, `InvoiceLine`, `Settlement`, and `Dispute` — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment of creation.

All of these resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` starts at 1 and increments by exactly one each time the resource is modified — including modifications the server performs on its own initiative during a cascade. Whenever a computed field on a resource changes (for example a lot's `current_high_bid_cents`, or an invoice's `total_due_cents`), that counts as a mutation of the owning resource and both refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation can produce a fractional cent — specifically the buyer's premium on an invoice line and the seller's commission on a settlement — the result is rounded to a whole number of cents using the round-half-up method (a value ending in exactly one-half cent rounds up to the next cent). Rounding is applied at the precise points named in §3; subtotals that merely add already-rounded amounts introduce no further rounding.

### 2.6. The Logical Clock

Storage fees and dispute timing depend on elapsed time, so the server maintains a single logical clock rather than reading wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until it is explicitly advanced; before any adjustment it never falls back to real-world time. An administrative test-driving capability sets the clock to a supplied instant `to_iso8601`. Every time-dependent computation in this specification — days in storage, window overlaps — reads this logical clock.

### 2.7. Cascading Consistency and Hierarchical Recomputation

A single business action frequently mutates several entities at once, and the specification requires every secondary effect to be applied, not just the primary transition. When a lot is hammered, the winning bid, the losing bids, the lot itself, a buyer invoice, and a new invoice line all change together. When an authenticity dispute is upheld, the invoice line, its invoice totals, the lot, and any draft seller statement all recompute in one cascade. Each entity touched during a cascade independently refreshes its `updated_at` and increments its `version` as described in §2.4; the detailed cascades are specified in §3.

For any request whose URL contains a resource identifier, and for any body that names a foreign resource, the server validates existence left to right: the path identifier is resolved first, then each referenced foreign key in turn. The first identifier that does not resolve produces the corresponding not-found error (HTTP 404) before any later resolution or business rule is attempted. Each resource type has its own not-found code: an unresolved saleroom yields `ERR_SALEROOM_NOT_FOUND`, a consignor `ERR_CONSIGNOR_NOT_FOUND`, a bidder `ERR_BIDDER_NOT_FOUND`, an auction `ERR_AUCTION_NOT_FOUND`, a consignment `ERR_CONSIGNMENT_NOT_FOUND`, a lot `ERR_LOT_NOT_FOUND`, a bid `ERR_BID_NOT_FOUND`, an invoice `ERR_INVOICE_NOT_FOUND`, an invoice line `ERR_INVOICE_LINE_NOT_FOUND`, a settlement `ERR_SETTLEMENT_NOT_FOUND`, and a dispute `ERR_DISPUTE_NOT_FOUND`.

### 2.8. Optimistic Concurrency on Bid Placement

Bidding is the one operation guarded by optimistic concurrency control. Placing a bid on a lot requires the request to carry `expected_lot_version`, the `version` of the target `Lot` that the bidder last observed. When a competing bid is accepted, it supersedes the prior high bid and increments the lot's `version`; a bidder still holding the older version is therefore working from a stale view of the current high bid and an outdated increment baseline. If `expected_lot_version` does not equal the lot's current `version`, the bid is rejected with `ERR_STALE_VERSION` (HTTP 412) and no bid is created. Bid placement is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.9. Request Validation Order

Checks are applied in a fixed priority order so that failures surface deterministically. The server evaluates them in this sequence: (1) authentication headers present and recognized, else `ERR_UNAUTHENTICATED`; (2) the acting role is permitted for the endpoint, else `ERR_UNAUTHORIZED`; (3) required body fields are present with correct types, valid enum membership, and satisfied range/positivity constraints, else `ERR_VALIDATION`; (4) every path identifier and body foreign key resolves, validated left to right, else the matching not-found error; (5) for entity-backed principals acting on their own resource, `X-User-ID` matches the owning foreign key, else `ERR_NOT_RESOURCE_OWNER`; (6) the bid-placement optimistic-concurrency check on `expected_lot_version`, else `ERR_STALE_VERSION`; (7) the target resource is in the correct state for the transition, else the applicable state error; and finally the endpoint-specific business rules described throughout §3. Where several business rules apply to one endpoint, their relative order is stated alongside the workflow that owns them.

## 3. Business Logic & Workflows

### 3.1. Principals, Venues, and Bidder Standing

Operations staff register the participants and the physical stage on which a sale runs. A `Saleroom` is registered with a `name`, a `location`, and a `capacity`, where capacity must be a positive seat count. A `Consignor` — the seller or estate — is registered with a `display_name`, an `email`, and an optional `payout_method` describing how proceeds are disbursed; `payout_method` is one of `CHECK`, `ACH`, or `STORE_CREDIT`, and defaults to `CHECK` when omitted.

A `Bidder` — the buyer — is registered with a `display_name`, an `email`, a `paddle_number`, and an optional `deposit_cents`. The `paddle_number` is a non-empty bidding identifier that must be globally unique across all bidders; registering a paddle already held by another bidder is rejected with `ERR_DUPLICATE_PADDLE` (HTTP 409). The refundable `deposit_cents` on file, which gates high-value bidding, must be zero or greater and defaults to 0. Every new bidder begins with `status` `ACTIVE`. Operations staff may later suspend a bidder, moving `status` from `ACTIVE` to `SUSPENDED`; suspension is permitted only while the bidder is `ACTIVE`, and suspending a bidder that is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). A suspended bidder is blocked from placing bids, as described in §3.4.

### 3.2. Consignment Intake and Appraisal

A consignment is the intake agreement for a batch of goods from one seller. It may be submitted either by operations staff acting on the seller's behalf or by the seller themselves; when a `Consignor` submits their own intake, the supplied `consignor_id` must equal `X-User-ID`, or the request is refused for lack of ownership. A consignment records its `consignor_id`, a `commission_rate` that is at least 0 and strictly less than 1, a pre-sale `estimate_low_cents` of zero or more, an `estimate_high_cents` that is at least the low estimate, and a scheduled estate-inspection window bounded by `intake_window_start` and `intake_window_end`, where the end must be strictly after the start.

The inspection window occupies the consignor over its closed interval, and no two consignments for the same seller may sit too close together. When submitting a consignment, if any other consignment for the same `consignor_id` has an intake window nearer than the mandatory buffer of 60 minutes (`INTAKE_BUFFER_MINUTES`) — measured against the closed intervals plus that buffer — the submission is rejected with `ERR_INTAKE_WINDOW_CONFLICT` (HTTP 409).

A newly submitted consignment enters `SUBMITTED`. An `Appraiser` then records a valuation, supplying `appraised_low_cents`, `appraised_high_cents`, and optional `appraisal_notes`; this is permitted only while the consignment is in `SUBMITTED` (otherwise `ERR_INVALID_STATE`), it sets those three appraisal fields, and it advances the consignment `SUBMITTED → APPRAISED`. Operations staff then render a decision by supplying an `outcome`: an `outcome` of `ACCEPT` moves an `APPRAISED` consignment to `ACCEPTED` and makes it eligible to supply lots, while an `outcome` of `DECLINE` moves it to `DECLINED`. A decision is permitted only while the consignment is `APPRAISED`; attempting it in any other state yields `ERR_CONSIGNMENT_NOT_APPRAISED` (HTTP 409). Both `ACCEPTED` and `DECLINED` are terminal.

### 3.3. Scheduling Sales and Cataloging Lots

An `Auction` is a sale scheduled into a saleroom. It is created with a `title`, a `sale_type` of `LIVE`, `ONLINE`, or `TIMED`, a `saleroom_id` naming the venue, and a `scheduled_start` and `scheduled_end` where the end is strictly after the start. The sale occupies the saleroom across the half-open interval from `scheduled_start` up to but not including `scheduled_end`. If another auction in the same `saleroom_id` overlaps that half-open interval, the creation is rejected with `ERR_SALEROOM_DOUBLE_BOOKED` (HTTP 409); because the interval is half-open, a sale that begins exactly when another ends is allowed.

An auction begins `SCHEDULED`. Operations staff open it (`SCHEDULED → OPEN`), after which its lots may be opened for bidding, and later close it (`OPEN → CLOSED`), after which no further lots in that sale may be opened. Opening requires the auction to be `SCHEDULED` and closing requires it to be `OPEN`; a transition attempted from the wrong state yields `ERR_INVALID_STATE`. `CLOSED` is terminal.

A `Lot` is cataloged from an accepted consignment into a sale. It carries a `consignment_id`, an `auction_id`, a `title`, a `category` label, a confidential `reserve_cents` of zero or more (the minimum hammer below which the lot cannot be sold), a `starting_bid_cents` that is strictly positive (the minimum acceptable first bid), a lot `estimate_low_cents` and an `estimate_high_cents` that is at least the low estimate, and a positive `lot_number` giving its ordinal position in the sale. Cataloging requires the referenced consignment to be in `ACCEPTED`; otherwise the request is rejected with `ERR_CONSIGNMENT_NOT_ACCEPTED` (HTTP 409). A new lot enters `CATALOGED`, and its computed fields begin empty: `current_high_bid_cents` is 0, and `current_high_bid_id`, `hammer_price_cents`, and `winning_bid_id` are all null.

Operations staff open a cataloged lot for bidding, advancing `sale_status` from `CATALOGED` to `OPEN`. This is permitted only when the lot is `CATALOGED` (otherwise `ERR_INVALID_STATE`) and its auction (`auction_id`) is currently `OPEN`; if the auction is not open, the request is rejected with `ERR_AUCTION_NOT_OPEN` (HTTP 409).

### 3.4. Bidding: Increments, Deposits, and Supersession

A `Bidder` places a bid against a lot by supplying `bidder_id`, a `bid_type` of `ABSENTEE`, `LIVE`, or `ONLINE`, an `amount_cents` that is strictly positive, and the `expected_lot_version` described in §2.8. The `bidder_id` must equal `X-User-ID`. A bid may only be placed while the lot is in `OPEN`; a bid against a lot in any other `sale_status` is rejected with `ERR_LOT_NOT_OPEN` (HTTP 409).

Once the lot's state is confirmed, the bidder's standing is checked: a `SUSPENDED` bidder may not bid, and the attempt is rejected with `ERR_BIDDER_SUSPENDED` (HTTP 403). The bid amount is then measured against the lot's next minimum acceptable bid. When the lot has no bids yet — `current_high_bid_cents` equal to 0 — the next minimum bid is the lot's `starting_bid_cents`. Otherwise, an increment is added to the current high according to escalating bands: when the current high is below 10,000 cents the increment is 1,000 cents; when it is at least 10,000 but below 100,000 cents the increment is 5,000 cents; when it is at least 100,000 but below 1,000,000 cents the increment is 10,000 cents; and when it is 1,000,000 cents or more the increment is 50,000 cents. The next minimum bid is the current high plus that increment. A bid is accepted only if `amount_cents` is greater than or equal to this next minimum bid; a bid below it is rejected with `ERR_BID_TOO_LOW` (HTTP 409).

Finally, high-value bids demand a deposit on file. When `amount_cents` is at least the high-value threshold of 1,000,000 cents (`HIGH_VALUE_LOT_CENTS`), the placing bidder's `deposit_cents` must be at least 100,000 cents (`MIN_DEPOSIT_FOR_HIGH_VALUE_CENTS`); if the deposit falls short, the bid is rejected with `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402). These checks apply in the order given: the stale-version guard first, then lot state, then bidder suspension, then the minimum-increment check, then the deposit gate.

An accepted bid is created in `status` `ACTIVE`. Placing it supersedes the prior high bid — the previous highest `ACTIVE` bid transitions `ACTIVE → OUTBID` — and the lot's `current_high_bid_cents` and `current_high_bid_id` are updated to reflect the new high, incrementing the lot's `version` by one. A bidder may also retract an `ACTIVE` bid before the lot is hammered; retraction is permitted only while the bid is `ACTIVE` and its lot is still `OPEN` (otherwise `ERR_INVALID_STATE` for a non-active bid, or `ERR_LOT_NOT_OPEN` for a lot no longer open), and it may be performed by any bidder or by operations staff — the server does not verify that the acting bidder owns the retracted bid. Retraction moves the bid `ACTIVE → RETRACTED`; if the retracted bid was the current high, the lot's `current_high_bid_cents` and `current_high_bid_id` are recomputed over the remaining `ACTIVE` bids (falling back to 0 and null when none remain) and the lot's `version` is incremented by one.

### 3.5. The Fall of the Hammer and Buy-Ins

When operations staff hammer an open lot, the lot must be in `OPEN`, or the request is rejected with `ERR_LOT_NOT_OPEN`. Two further conditions guard the sale: at least one `ACTIVE` bid must exist on the lot, else `ERR_NO_BIDS` (HTTP 409); and the lot's `current_high_bid_cents` must be at least its `reserve_cents`, else `ERR_RESERVE_NOT_MET` (HTTP 409).

The winner is the `ACTIVE` bid with the greatest `amount_cents`; ties are broken in favor of the earliest `created_at`, and the bid's `id` is never used as a tie-break input. Hammering advances the lot `OPEN → HAMMERED`, transitions the winning bid `ACTIVE → WINNING`, transitions every other `ACTIVE` bid on the lot `ACTIVE → OUTBID`, and records `hammer_price_cents` (the winner's `amount_cents`) and `winning_bid_id` (the winner's `id`) on the lot.

The hammer then cascades into billing. The system finds or creates the buyer's `Invoice` for this sale, keyed by the winner's `bidder_id` and the lot's `auction_id`; when the invoice is created (the first hammer for that buyer in that auction), its `storage_start_at` is set to the current logical clock and its `storage_fee_cents` is fixed at 0. A new `InvoiceLine` is created against that invoice, recording the `invoice_id`, the `lot_id`, the `hammer_price_cents` copied from the lot, the `buyers_premium_cents` computed for this line, and the `line_total_cents` equal to the line's hammer price plus its premium; a line begins in `status` `ACTIVE`.

The buyer's premium is a progressive, tiered charge on a single line's hammer price. Twenty-five percent applies to the first 300,000 cents of hammer price; twenty percent applies to the portion of hammer price above 300,000 cents and up to 2,000,000 cents; and fifteen percent applies to any portion above 2,000,000 cents. The three portions are summed, and the result is rounded once, using round-half-up, to whole cents to yield the line's `buyers_premium_cents`.

After the line is created, the invoice totals recompute: `hammer_subtotal_cents` becomes the sum of `hammer_price_cents` over the invoice's non-void (`ACTIVE`) lines, and `premium_subtotal_cents` becomes the sum of the already-rounded `buyers_premium_cents` over those same lines — because each line's premium was rounded when the line was created, summing introduces no further rounding. The `total_due_cents` is then `hammer_subtotal_cents` plus `premium_subtotal_cents` plus `storage_fee_cents` plus `shipping_fee_cents`. The invoice's `payment_status` is refreshed against the new total, and the invoice's `version` is incremented by one; the lot's `version` is likewise incremented by one for the hammer.

Not every lot sells. When operations staff pass a lot — an unsold or bought-in lot whose reserve was not met or that drew no bids — the lot must be `OPEN` (otherwise `ERR_LOT_NOT_OPEN`). Passing advances the lot `OPEN → PASSED`, transitions every `ACTIVE` bid on the lot `ACTIVE → OUTBID`, and creates no invoice and no invoice line. Both `PASSED` and `RESCINDED` are terminal lot states.

### 3.6. Buyer Settlement: Payments, Storage, and Release

A buyer's `Invoice` tracks two independent axes. The `payment_status` axis — `UNPAID`, `PARTIALLY_PAID`, or `PAID`, beginning at `UNPAID` — is entirely separate from the `fulfillment_status` axis — `PENDING`, `READY`, `PICKED_UP`, or `SHIPPED`, beginning at `PENDING`. An invoice also carries `amount_paid_cents` and `total_refunded_cents`, both starting at 0.

Payments move the payment axis. A payment supplies an `amount_cents` that must be strictly positive, applied by the owning bidder or by operations staff; when a bidder pays, the invoice's `bidder_id` must equal `X-User-ID`. The payment must not exceed the remaining balance: if `amount_paid_cents` plus the new `amount_cents` would exceed `total_due_cents`, the payment is rejected with `ERR_OVERPAYMENT` (HTTP 409). Otherwise the new amount is added to `amount_paid_cents`, and `payment_status` is set to `PAID` when `amount_paid_cents` equals `total_due_cents`, to `PARTIALLY_PAID` when it is above 0 but below the total, and to `UNPAID` when it is 0; the invoice's `version` is incremented by one.

Readying an invoice moves the fulfillment axis and finalizes the storage charge. Operations staff supply a `fulfillment_method` of `PICKUP` or `SHIP`, and an optional `shipping_fee_cents`. Readying is permitted only while `fulfillment_status` is `PENDING`. It sets `fulfillment_method` to the supplied method; sets `shipping_fee_cents` to the supplied amount when the method is `SHIP` and to 0 when the method is `PICKUP`; finalizes `storage_fee_cents` using the current clock; recomputes `total_due_cents`; refreshes `payment_status` against the new total (so an invoice paid in full before storage and shipping were added may revert to `PARTIALLY_PAID`); advances `fulfillment_status` `PENDING → READY`; and increments the invoice's `version` by one.

The storage fee rewards prompt collection. Elapsed storage is the number of whole days between the invoice's `storage_start_at` and the current logical clock, counting only complete 24-hour days. The first seven days (`FREE_STORAGE_DAYS`) are free: chargeable days are the elapsed whole days minus seven, never less than zero. The final `storage_fee_cents` is the chargeable days multiplied by 500 cents per day (`DAILY_STORAGE_CENTS`). Thus exactly seven days elapsed yields no charge, while the eighth day yields one day's charge of 500 cents. This final accrual is computed at ready time; at hammer time the storage fee is instead held at 0 as a provisional grace amount, regardless of the clock, because the item has only just sold.

Releasing the goods completes fulfillment. Operations staff fulfill an invoice only when its `fulfillment_status` is `READY` (otherwise `ERR_INVALID_STATE`) and its `payment_status` is `PAID`; an unpaid or partially paid invoice cannot be released, and the attempt is rejected with `ERR_INVOICE_NOT_PAID` (HTTP 409). Fulfillment sets `fulfillment_status` to `PICKED_UP` when the chosen `fulfillment_method` is `PICKUP` and to `SHIPPED` when it is `SHIP`, and increments the invoice's `version` by one.

### 3.7. Seller Settlement and Payout

A `Settlement` is the seller-payout statement for one consignment, created by a settlement officer or operations staff. It references its `consignment_id` and reports `gross_hammer_cents`, `seller_commission_cents`, `net_payout_cents`, and `lot_count`, all beginning at 0, and begins in `status` `DRAFT`.

The payout arithmetic aggregates the consignment's sold lots. The `gross_hammer_cents` is the sum of `hammer_price_cents` over the consignment's lots whose `sale_status` is `HAMMERED`, excluding any lot that has been rescinded. The `seller_commission_cents` is the gross hammer multiplied by the consignment's `commission_rate`, rounded half-up to whole cents. The `net_payout_cents` is the gross hammer minus the commission, and `lot_count` is the number of `HAMMERED` (non-rescinded) lots included.

This computation has two variants. At creation and on interim recomputes it is provisional: the gross counts every lot that is `HAMMERED` at that moment, including lots whose authenticity dispute is still `OPEN` or `UNDER_REVIEW`. At approval it is final: the gross counts only lots that remain `HAMMERED` after any upheld dispute has rescinded its lot, so an upheld dispute lowers the final gross relative to the provisional figure.

A settlement officer approves a draft statement, advancing it `DRAFT → APPROVED`. Approval is permitted only while the settlement is `DRAFT`, and it additionally requires that every invoice which includes a non-void line for one of this consignment's `HAMMERED` lots has `payment_status` equal to `PAID`; if any such invoice is unpaid, approval is rejected with `ERR_INVOICES_UNPAID` (HTTP 409). Approval recomputes the gross, commission, net payout, and lot count using the final variant and increments the settlement's `version` by one. The officer then pays an approved settlement, advancing it `APPROVED → PAID` and disbursing the proceeds via the consignor's `payout_method`, again incrementing the settlement's `version` by one; paying requires the settlement to be `APPROVED`. `PAID` is terminal.

### 3.8. Authenticity Disputes and Rescission

A `Bidder` who has bought a lot may challenge its authenticity by raising a `Dispute` against the purchased line, supplying the `invoice_line_id` and a `reason`. The buyer must own the line: the `bidder_id` on the line's invoice must equal `X-User-ID`. A line may carry only one live dispute at a time — if an `OPEN` or `UNDER_REVIEW` dispute already exists for that line, the new filing is rejected with `ERR_LINE_ALREADY_DISPUTED` (HTTP 409). A dispute is created in `status` `OPEN`, and its `bidder_id` is copied from the line's invoice; its `resolution_notes` are null until resolved and its `refund_cents` begins at 0.

An `Appraiser` adjudicates. Reviewing a dispute advances it `OPEN → UNDER_REVIEW` and is permitted only while it is `OPEN`. From `UNDER_REVIEW`, the appraiser may request further provenance, optionally supplying a `note`, which bounces the dispute back `UNDER_REVIEW → OPEN` so the buyer can respond — this is the cyclic path that lets a dispute move between `OPEN` and `UNDER_REVIEW` more than once. From `UNDER_REVIEW`, the appraiser resolves the dispute by supplying an `outcome` and optional `resolution_notes`. Resolution requires the dispute to be `UNDER_REVIEW`; a transition attempted from any other state yields `ERR_INVALID_STATE`.

A resolution `outcome` of `REJECTED` moves the dispute `UNDER_REVIEW → REJECTED`, records the `resolution_notes`, and makes no change to the line, lot, invoice, or settlement. A resolution `outcome` of `UPHELD` requires the challenged line's `status` to still be `ACTIVE` (otherwise the request is rejected with `ERR_INVALID_STATE`, HTTP 409), moves the dispute `UNDER_REVIEW → UPHELD`, and triggers the system's most far-reaching cascade. First, the dispute's `refund_cents` is set to the line's `line_total_cents` and its `resolution_notes` are recorded. The line is voided, transitioning its `status` `ACTIVE → VOID`. The line's invoice then recomputes: its `total_refunded_cents` grows by the line's `line_total_cents`, its `hammer_subtotal_cents`, `premium_subtotal_cents`, and `total_due_cents` are recomputed over the remaining non-void lines, its `payment_status` is refreshed, and its `version` is incremented by one. The line's lot is rescinded, transitioning `sale_status` `HAMMERED → RESCINDED` and incrementing the lot's `version` by one. Finally, if a `DRAFT` settlement exists for that lot's consignment, its `gross_hammer_cents`, `seller_commission_cents`, `net_payout_cents`, and `lot_count` are recomputed to exclude the now-rescinded lot, incrementing the settlement's `version` by one. Both `UPHELD` and `REJECTED` are terminal dispute states.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify or act upon an existing resource return `200 OK`. All GET reads are available to every role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | AuctionStaff |
| POST | `/salerooms` | Register a saleroom / venue | AuctionStaff |
| POST | `/consignors` | Register a consignor (seller) | AuctionStaff |
| POST | `/bidders` | Register a bidder (buyer) | AuctionStaff |
| POST | `/bidders/{id}/suspend` | Suspend a bidder | AuctionStaff |
| POST | `/auctions` | Create a sale scheduled into a saleroom | AuctionStaff |
| POST | `/auctions/{id}/open` | Open a scheduled sale | AuctionStaff |
| POST | `/auctions/{id}/close` | Close an open sale | AuctionStaff |
| GET | `/auctions/{id}` | Read a single auction | All roles |
| GET | `/auctions` | List auctions (filter by saleroom or status) | All roles |
| POST | `/consignments` | Submit a consignment intake | AuctionStaff, Consignor |
| POST | `/consignments/{id}/appraise` | Record a valuation | Appraiser |
| POST | `/consignments/{id}/decision` | Accept or decline an appraised consignment | AuctionStaff |
| GET | `/consignments/{id}` | Read a single consignment | All roles |
| GET | `/consignments` | List consignments (filter by consignor or status) | All roles |
| POST | `/consignments/{id}/settlement` | Create the seller-payout statement | SettlementOfficer, AuctionStaff |
| POST | `/lots` | Catalog a lot from an accepted consignment | AuctionStaff |
| POST | `/lots/{id}/open` | Open a cataloged lot for bidding | AuctionStaff |
| POST | `/lots/{id}/hammer` | Hammer the lot; pick winner and cascade billing | AuctionStaff |
| POST | `/lots/{id}/pass` | Pass / buy-in an unsold lot | AuctionStaff |
| GET | `/lots/{id}` | Read a single lot | All roles |
| GET | `/lots` | List lots (filter by consignment, auction, or status) | All roles |
| POST | `/lots/{id}/bids` | Place an absentee/live/online bid | Bidder |
| POST | `/bids/{id}/retract` | Retract an active bid | Bidder, AuctionStaff |
| GET | `/bids/{id}` | Read a single bid | All roles |
| GET | `/bids` | List bids (filter by lot, bidder, or status) | All roles |
| POST | `/invoices/{id}/payments` | Apply a payment to an invoice | Bidder, AuctionStaff |
| POST | `/invoices/{id}/ready` | Mark invoice ready; finalize storage and shipping | AuctionStaff |
| POST | `/invoices/{id}/fulfill` | Release the goods (pickup or ship) | AuctionStaff |
| GET | `/invoices/{id}` | Read a single invoice | All roles |
| GET | `/invoices` | List invoices (filter by bidder, auction, or payment status) | All roles |
| GET | `/invoice-lines/{id}` | Read a single invoice line | All roles |
| GET | `/invoice-lines` | List invoice lines (filter by invoice or lot) | All roles |
| POST | `/settlements/{id}/approve` | Approve a draft settlement | SettlementOfficer |
| POST | `/settlements/{id}/pay` | Disburse an approved settlement | SettlementOfficer |
| GET | `/settlements/{id}` | Read a single settlement | All roles |
| GET | `/settlements` | List settlements (filter by consignment or status) | All roles |
| POST | `/disputes` | Raise an authenticity dispute against a line | Bidder |
| POST | `/disputes/{id}/review` | Start reviewing a dispute | Appraiser |
| POST | `/disputes/{id}/request-info` | Bounce a dispute back for more provenance | Appraiser |
| POST | `/disputes/{id}/resolve` | Uphold or reject a dispute | Appraiser |
| GET | `/disputes/{id}` | Read a single dispute | All roles |
| GET | `/disputes` | List disputes (filter by invoice line, bidder, or status) | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SALEROOM_NOT_FOUND` | 404 |
| `ERR_CONSIGNOR_NOT_FOUND` | 404 |
| `ERR_BIDDER_NOT_FOUND` | 404 |
| `ERR_AUCTION_NOT_FOUND` | 404 |
| `ERR_CONSIGNMENT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVOICE_LINE_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_PADDLE` | 409 |
| `ERR_AUCTION_NOT_OPEN` | 409 |
| `ERR_LOT_NOT_OPEN` | 409 |
| `ERR_CONSIGNMENT_NOT_ACCEPTED` | 409 |
| `ERR_CONSIGNMENT_NOT_APPRAISED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BIDDER_SUSPENDED` | 403 |
| `ERR_INSUFFICIENT_DEPOSIT` | 402 |
| `ERR_BID_TOO_LOW` | 409 |
| `ERR_RESERVE_NOT_MET` | 409 |
| `ERR_NO_BIDS` | 409 |
| `ERR_SALEROOM_DOUBLE_BOOKED` | 409 |
| `ERR_INTAKE_WINDOW_CONFLICT` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_INVOICE_NOT_PAID` | 409 |
| `ERR_INVOICES_UNPAID` | 409 |
| `ERR_LINE_ALREADY_DISPUTED` | 409 |
