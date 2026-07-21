# Rare & Used Bookstore API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform for a rare and second-hand bookshop that also operates a book-scouting desk. The business spans a full antiquarian workflow: books arrive in intake lots (from buybacks, consignments, outright purchases, or a fair), are graded for condition and first-edition status, appraised against comparable sales, listed simultaneously to an online catalog and a physical shop shelf, sold, packed, and shipped. Alongside inventory, the shop runs two running money ledgers per customer — a store-credit balance funded by buyback offers and spent against orders, and a consignor-payable balance that accrues when consigned stock sells.

The platform's central difficulty is reconciliation: valuations, payouts, order totals, and both ledgers must remain internally consistent as items move through their lifecycle, and every confirming sale must be perfectly reversible by a later refund. A second concern is that several resources compete for scarce, time-bounded capacity — booth tables at a fair and packing stations in the back room — so the system arbitrates overlapping reservations. Because staff often work the same records at the same time, the platform also protects a handful of mutable resources with optimistic concurrency so that a stale edit is refused rather than silently overwriting an intervening change.

The audience for this document is the engineering team building the REST API. It defines the resource model, the state machines that govern each resource, the exact arithmetic behind every derived value, the validation order, and the endpoint and error contracts.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` does not name one of the roles defined below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four roles exist, spelled exactly as follows: `Patron`, `Appraiser`, `StoreClerk`, and `Manager`.

When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` entity; ownership checks on any resource that references a `Patron` compare the resource's patron foreign-key field to `X-User-ID`. A `Patron` is a consignor, buyer, or seller who reads their own records and browses catalog inventory but performs no state-changing operations. When `X-User-Role` is `Appraiser`, `StoreClerk`, or `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, within a `provenance` event's `actor_role`) but never compares it to any entity's `id`. An `Appraiser` grades items and issues appraisals. A `StoreClerk` runs front-of-house work — intake, listing creation, catalog edits, booth reservations, sale drafting, and packing. A `Manager` holds back-office authority — lot settlement and rejection, the consignment lifecycle, buyback acceptance and voiding, fair creation, and sale confirmation and refund. The precise operation-to-role mapping is given in the §4 endpoint table's Authorized Role(s) column.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0 and its minimum is 0. Results are returned sorted by `created_at` in ascending order. When a list endpoint responds, its `meta` object carries `limit`, `offset`, `total_count` (the number of records matching the query before the page window is applied), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` in UUID form, with no type prefix. Every resource also carries a `created_at` timestamp. All resources in this system additionally carry an `updated_at` timestamp and an integer `version`. Timestamps are ISO 8601 UTC values with three fractional digits. A resource's `version` starts at its creation value and increases by one on each mutation that the narrative below designates as version-bumping; `updated_at` is refreshed whenever the resource is mutated. Where a computation or cascade changes a resource, the same rule applies — the touched resource's `updated_at` moves forward and, where specified, its `version` increments.

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored as integer cents. Wherever a calculation in this document calls for rounding, the method is round half up (a fractional cent of exactly one-half rounds away from zero to the next whole cent). Each calculation section below states precisely where rounding is applied; in particular, order totals round each line item independently before summation rather than rounding the sum, and this ordering is mandatory because the two approaches can differ by whole cents.

### 2.6. Optimistic Concurrency Control

Three mutating operations are guarded by optimistic concurrency, each keyed to the current `version` of a parent resource. In every case the client must submit the version it last observed, and if that value does not equal the resource's current `version` the write is refused with `ERR_STALE_VERSION` (HTTP 412), signalling that another writer has advanced the resource since the client last read it.

- Issuing an appraisal against a book item requires `expected_book_item_version` to equal that `BookItem`'s current `version`. A new appraisal legitimately supersedes the item's prior issued appraisal; if another writer has already issued one and advanced the item's `version`, the submitting client's view is stale and the create is refused with `ERR_STALE_VERSION`.
- Amending a consignment agreement requires `expected_consignment_agreement_version` to equal that `ConsignmentAgreement`'s current `version`. If another writer has already amended the agreement and advanced its `version`, the current amendment rests on stale terms and is refused with `ERR_STALE_VERSION`.
- Updating a catalog listing requires `expected_catalog_listing_version` to equal that `CatalogListing`'s current `version`. A client carrying a version older than the listing's current `version` has not seen an intervening change and is refused with `ERR_STALE_VERSION`.

Operations not named above do not take a version field.

### 2.7. Nested Paths and Referential Integrity

Several resources are addressed through nested paths — booth slots under a fair, book items under an intake lot, appraisals, listings, and shipments under their parent. Path identifiers are validated left to right: each id in the path must resolve to an existing resource before the next is considered, and the first that does not resolve produces the matching not-found error — `ERR_PATRON_NOT_FOUND`, `ERR_INTAKE_LOT_NOT_FOUND`, `ERR_BOOK_ITEM_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_FAIR_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND` (all HTTP 404). Foreign-key fields supplied in a request body are validated the same way: a `consignor_id`, `book_item_id`, `patron_id`, `fair_event_id`, `sale_order_id`, or `intake_lot_id` that names a non-existent resource yields the corresponding not-found error (HTTP 404).

### 2.8. Validation Order and Priority Conflicts

When more than one rule could reject a request, the checks run in a fixed priority order and the first failure determines the response. The order is: (1) presence and validity of the user-context headers; (2) the caller's permission to invoke the endpoint; (3) existence of every id named in the path, left to right; (4) existence of every foreign key carried in the request body; (5) request-body well-formedness — required fields present, enum fields within their allowed sets, numeric amounts non-negative, and, for any window, its end strictly after its start (`ERR_INVALID_REQUEST`, or `ERR_INVALID_WINDOW` for the window ordering, both HTTP 400); (6) the target resource being in a state that permits the requested transition; then the domain-specific business checks. Two conflict pairs are pinned explicitly so that the reported error is deterministic:

- On sale-order confirmation, the state check that every line item's book is `LISTED` (yielding `ERR_ITEM_NOT_LISTED`) outranks the referential check that a consigned line's agreement is `ACTIVE` (yielding `ERR_CONSIGNMENT_NOT_ACTIVE`). If both fail, the item-not-listed error is reported.
- On booth-slot reservation, the temporal overlap check (yielding `ERR_BOOTH_SLOT_CONFLICT`) outranks the aggregate-capacity check (yielding `ERR_FAIR_CAPACITY_EXCEEDED`). If both fail, the overlap error is reported.

### 2.9. Store-Credit and Consignor-Payable Ledgers

Each `Patron` carries two derived money balances, both reported on the patron record and both maintained so that they can never fall below zero. The `store_credit_cents` balance equals the sum of `credit_amount_cents` across the patron's `ACCEPTED` buyback offers, minus the sum of `store_credit_applied_cents` across the patron's `CONFIRMED` sale orders. The `consignor_payable_cents` balance equals the sum of consignor payouts accrued over consigned line items on `CONFIRMED` sale orders whose consigned book's `consignor_id` is that patron. These are compensating ledgers: any buyback acceptance immediately undone by its void returns `store_credit_cents` to its exact prior value, and any sale confirmation immediately undone by its refund returns both `store_credit_cents` and `consignor_payable_cents` to their exact prior values. The mutation events that move these balances are described in the workflow narratives of §3.

### 2.10. Cascading State Propagation

Many operations touch more than one resource inside a single request, and all such cascades complete atomically before the response is returned. When a lot is rejected, its books are withdrawn and their live appraisals voided in a chained cascade; when a sale confirms, each sold book pulls its listing to sold and, where consigned, settles its agreement and accrues a payout; when a sale is refunded, every one of those effects is reversed exactly. Each resource that a cascade mutates has its `updated_at` refreshed, and any `version`-bearing resource that the narrative marks as bumped has its `version` incremented as part of the same transaction.

## 3. Business Logic & Workflows

### 3.1. Patrons and Their Two Ledgers

A `Patron` represents any counterparty to the shop — a person or dealer who consigns, buys, or sells. Registration captures a `display_name` and an `email`, and may optionally include a `default_commission_pct`, the fractional commission (a value between 0 and 1) the shop applies to that consignor's agreements when an agreement omits its own rate; when not supplied it defaults to 0.30. Email addresses must be unique across all patrons; a registration whose `email` matches an existing patron is rejected with `ERR_DUPLICATE_EMAIL`. On creation a patron begins with `status` of `ACTIVE`, a `store_credit_cents` of 0, and a `consignor_payable_cents` of 0. Reading a patron returns the record including both live ledger balances. The two balances move only through the buyback and sale-order flows described later, and each is held at or above zero at all times.

### 3.2. Intake Lots and Their Books

Stock enters the shop as an `IntakeLot`. Opening a lot records its `acquisition_channel` — one of `BUYBACK`, `CONSIGNMENT`, `PURCHASE`, or `FAIR` — and, for consigned or bought-in stock, an optional `consignor_id` naming the `Patron` the lot was taken from; shop-purchase lots leave it null, and when present it must reference an existing patron. A new lot opens in `DRAFT` with an `item_count` of 0.

Books are intaken into a `DRAFT` lot one at a time. Each `BookItem` records a `title`, an `author`, and a `comp_median_cents` (the median comparable-sale price that anchors valuation), and may optionally carry a `printing_number` (defaulting to 1) and a `stated_first_edition` flag (defaulting to false). On intake the item is created in `INTAKE` status, its `consignor_id` is copied from the lot, the lot's `item_count` is incremented by one, and a `provenance` entry of event type `INTAKE` is appended. The `provenance` field is an append-only log; each entry records an `event_type`, an optional `note`, the `actor_role`, and the timestamp `at`. At intake the item's `condition_grade` is null (any value supplied at create is ignored), its `is_first_edition` is false, and its `appraised_value_cents` is null.

A lot leaves `DRAFT` by one of two manager actions. Settling a lot moves it to `SETTLED`; it requires the lot to hold at least one book (otherwise `ERR_EMPTY_LOT`) and every book whose `intake_lot_id` is this lot to be in `APPRAISED` status (otherwise `ERR_LOT_ITEMS_NOT_APPRAISED`). Rejecting a lot moves it to `REJECTED` and drives a two-hop cascade: first, every book in the lot that is not already `SOLD` transitions to `WITHDRAWN`; second, for each such withdrawn book, every appraisal with that `book_item_id` still in `ISSUED` status is set to `VOIDED` and the book's `appraised_value_cents` is cleared to null. Each withdrawn book also receives a `provenance` entry of event type `WITHDRAWN`. Book items are discoverable by listing them and filtering on `intake_lot_id`, `consignor_id`, or `status`; the lot record itself only reports its rolled-up `item_count`.

### 3.3. Grading and Appraisal of Book Items

Grading is an `Appraiser` action available only while a book is in `INTAKE`; attempting it in any other state is rejected with `ERR_ITEM_NOT_GRADED`. The grade payload supplies a `condition_grade`, one of `POOR`, `GOOD`, `VERY_GOOD`, `FINE`, or `AS_NEW`, which is written onto the item. Grading also fixes the item's first-edition determination: `is_first_edition` becomes true only when the item was marked as a stated first edition and its stated printing is an early enough impression — specifically, `stated_first_edition` is true and `printing_number` is at most 1. A stated first edition with printing number 1 is therefore a first edition; the same book stated at printing number 2 is not. The transition carries the item from `INTAKE` to `GRADED` and appends a `provenance` entry of event type `GRADED`.

Once a book is `GRADED`, an `Appraiser` may issue an appraisal; issuing is also permitted against an already-`APPRAISED` item, in which case the new appraisal supersedes the prior one. Attempting to appraise an item that is neither `GRADED` nor `APPRAISED` is rejected with `ERR_ITEM_NOT_GRADED`. The request names a `basis` — either `FAIR_MARKET` or `RETAIL_REPLACEMENT` — and, because this write is concurrency-guarded, an `expected_book_item_version` matching the item's current `version`. The appraisal computes two valuation variants from identical inputs. Let the comparable base be the item's `comp_median_cents` and the condition multiplier be drawn from the grade — `POOR` maps to 0.4, `GOOD` to 0.7, `VERY_GOOD` to 1.0, `FINE` to 1.4, and `AS_NEW` to 1.8. A first-edition premium of 0.5 applies as a multiplicative uplift when `is_first_edition` is true, and is 0 otherwise, so the premium factor is one plus that premium. The `fair_market_value_cents` is the comparable base multiplied by the condition multiplier and by the premium factor, rounded half up to whole cents. The `retail_replacement_value_cents` is the same product additionally multiplied by a retail markup of 1.6, rounded half up to whole cents; because the markup exceeds one, the retail variant is strictly larger than the fair-market variant for positive inputs. The `final_value_cents` is set to the fair-market variant when `basis` is `FAIR_MARKET`, and to the retail-replacement variant when `basis` is `RETAIL_REPLACEMENT`.

Issuing an appraisal creates it in `ISSUED` status, sets any prior `ISSUED` appraisal for the same book to `SUPERSEDED` so the newest becomes the authoritative valuation, moves the book from `GRADED` to `APPRAISED` (an already-`APPRAISED` item stays `APPRAISED`), copies the new `final_value_cents` into the item's `appraised_value_cents`, and increments the book's `version` by one. A `provenance` entry of event type `APPRAISED` is appended on the first issue only. Appraisals for a book can be listed in reverse by its identifier.

### 3.4. Catalog Listings and the Two Sales Channels

A `StoreClerk` publishes an appraised book by creating its `CatalogListing`, supplying a `list_price_cents`. Listing creation requires the book to be in `APPRAISED` status (otherwise `ERR_ITEM_NOT_APPRAISED`) and enforces a one-to-one relationship: a book may have at most one catalog listing and at most one consignment agreement, so a second listing attempt is rejected with `ERR_DUPLICATE_LISTING`. Creating the listing moves the book from `APPRAISED` to `LISTED` and appends a `provenance` entry of event type `LISTED`. A book's listing is retrievable by the book's identifier, returned as an array of zero or one.

A listing carries two independent status axes. The `online_status` axis governs the web channel and takes values `DRAFT`, `LIVE`, `SOLD`, or `DELISTED`; the `shop_status` axis governs the physical shelf and takes values `DRAFT`, `ON_SHELF`, `SOLD`, or `PULLED`. Both begin at `DRAFT`. A clerk edits a listing to change its `list_price_cents` and to advance either axis independently — bringing the online axis from `DRAFT` to `LIVE`, or the shelf axis from `DRAFT` to `ON_SHELF` — and each such edit leaves the other axis unchanged, increments the listing's `version` by one, and must carry an `expected_catalog_listing_version` matching the listing's current `version`. A `sold_channel` field, either `ONLINE` or `SHOP`, remains null until a sale records which axis carried the transaction. The two axes settle automatically at sale time: a confirmed online sale sets `online_status` to `SOLD`, records `sold_channel` as `ONLINE`, and sets `shop_status` to `PULLED` so the physical copy leaves the shelf; a confirmed shop sale sets `shop_status` to `SOLD`, records `sold_channel` as `SHOP`, and sets `online_status` to `DELISTED` so the online copy is withdrawn. A refund reverses this, restoring the sold axis to its pre-sale live value and clearing `sold_channel`.

### 3.5. Consignment Agreements

When the shop takes stock on consignment, a `Manager` proposes a `ConsignmentAgreement` binding one `Patron` (the consignor, named by `patron_id`) to one `BookItem` (named by `book_item_id`, one agreement per book). The proposal sets a `commission_pct` — the fraction of a sale the shop retains — and may set a `fee_model` (defaulting to `GROSS_COMMISSION`) and a `flat_fee_cents` (defaulting to 0). Because a book carries at most one agreement, a duplicate proposal is rejected with `ERR_DUPLICATE_LISTING`. A new agreement opens in `PROPOSED` with `amendment_no` at 0.

An agreement is negotiated cyclically. Amending it keeps it in, or returns it to, `AMENDED` status and is permitted only while it is `PROPOSED` or `AMENDED` (otherwise `ERR_AGREEMENT_NOT_AMENDABLE`); it also requires an `expected_consignment_agreement_version` matching the current `version`. An amendment updates any of `commission_pct`, `fee_model`, or `flat_fee_cents` from the payload, increments `amendment_no` by one, and increments the agreement's `version` by one. Activating an agreement moves it to `ACTIVE` and requires the referenced book to be in `APPRAISED` or `LISTED` status (otherwise `ERR_ITEM_NOT_APPRAISED`); activation appends a `provenance` entry of event type `CONSIGNED` to the book. An `ACTIVE` agreement settles to `SETTLED` automatically when its consigned book sells on a confirmed order, and a refund of that order returns it from `SETTLED` to `ACTIVE`. Agreements are listable and filterable by `patron_id`, `book_item_id`, or `status`.

When a consigned book sells, the consignor's payout is accrued into the consignor's `consignor_payable_cents`. The payout depends on the agreement's fee model and is computed from the consigned line item's gross `sale_price_cents` (before any discount) and the agreement's terms. Under `GROSS_COMMISSION`, the payout is the gross sale price multiplied by one minus the `commission_pct`, rounded half up to whole cents, and the `flat_fee_cents` is ignored. Under `NET_COMMISSION`, the `flat_fee_cents` is first subtracted from the gross sale price and the remainder is multiplied by one minus the `commission_pct`, then rounded half up to whole cents; because the flat fee is removed before commission, the net model yields a smaller payout than the gross model for the same sale.

### 3.6. Buyback Offers and Store Credit

The shop buys books back for store credit through a `BuybackOffer`. A `StoreClerk` or `Manager` creates an offer naming the selling `Patron` by `patron_id`, an `offer_value_cents`, and optionally the `book_item_id` of the book being bought. Every offer is created in `PENDING`, but an offer whose `offer_value_cents` is at most 5000 auto-approves on creation — its `auto_approved` flag is set true and its status becomes `AUTO_APPROVED`. The boundary is inclusive on the lower side: an offer of exactly 5000 cents auto-approves, while 5001 cents remains `PENDING`. Offers can be listed and filtered by `patron_id`, `book_item_id`, or `status`.

A `Manager` accepts an offer that is `PENDING` or `AUTO_APPROVED` (otherwise `ERR_OFFER_NOT_ACCEPTABLE`). Acceptance moves the offer to `ACCEPTED`, sets its `credit_amount_cents` equal to the `offer_value_cents`, and adds that credit to the seller's `store_credit_cents`. When the offer names a book, a `provenance` entry of event type `BUYBACK` is appended to it. A `Manager` may later void an `ACCEPTED` offer (otherwise `ERR_OFFER_NOT_VOIDABLE`); voiding moves it to `VOIDED` and reverses the credit, subtracting the offer's `credit_amount_cents` from the seller's `store_credit_cents`. Because a ledger may never go negative, a void is refused with `ERR_CREDIT_ALREADY_SPENT` when the seller's current `store_credit_cents` is below the offer's `credit_amount_cents` — the credit has already been spent and cannot be clawed back. A void that passes this check reverses the acceptance exactly.

### 3.7. Fairs and Booth Reservations

The shop exhibits at book fairs. A `Manager` creates a `FairEvent` with a `name` and a `table_capacity`, the maximum number of display slots that may be occupied across overlapping reservations at any instant; a new fair starts with `reserved_display_count` at 0. Staff then reserve `BoothSlot` records against the fair, each naming a `booth_table` (the physical table it occupies), a `window_start` (inclusive) and `window_end` (exclusive) bounding the occupation, and an optional `display_item_count` (defaulting to 1) for how many display slots the reservation consumes. A slot's window must be well-formed — `window_end` strictly after `window_start`, else `ERR_INVALID_WINDOW` — and every slot is created directly in `RESERVED`.

Two guards apply to a reservation, in the priority order fixed in §2.8. The overlap guard treats windows as half-open: a new slot conflicts with an existing slot on the same `fair_event_id` and same `booth_table` when the existing slot starts before the new slot ends and the new slot starts before the existing slot ends; touching intervals, where one window's end equals the other's start, do not overlap. A conflict is rejected with `ERR_BOOTH_SLOT_CONFLICT`. The capacity guard sums the `display_item_count` of all existing slots on the same `fair_event_id` whose window overlaps the new window (half-open), adds the new slot's `display_item_count`, and rejects the reservation with `ERR_FAIR_CAPACITY_EXCEEDED` when that total exceeds the fair's `table_capacity`. The fair's `reserved_display_count` reflects the total display slots held by currently reserved booth slots and is updated as reservations are made. Booth slots for a fair are listable by the fair's identifier.

### 3.8. Sale Orders: Drafting, Confirmation, and Refund

A sale is drafted as a `SaleOrder` by a `StoreClerk` or `Manager`. The draft records a `channel` — `ONLINE` or `SHOP` — a `line_items` array with one entry per book sold, an optional `buyer_patron_id` (null for a walk-in cash sale; when present it must reference an existing patron), an optional `tax_pct` (defaulting to 0.08), and an optional `store_credit_applied_cents` (the credit the buyer elects to spend, defaulting to 0). Each entry in `line_items` names a `book_item_id`, a `sale_price_cents`, and a `discount_pct`. A new order is created in `DRAFT`, and its totals are computed immediately.

The order total is computed line by line, and the rounding order is mandatory: for each line, take its `sale_price_cents`, apply its discount by multiplying by one minus the line's `discount_pct`, then apply tax by multiplying by one plus the order's `tax_pct`, and round that line amount half up to whole cents. The `subtotal_cents` is the sum of these already-rounded per-line amounts — the amounts are rounded before they are summed, never after. The `total_cents` is the `subtotal_cents` less the `store_credit_applied_cents`, floored at 0 so it is never negative. These totals are recomputed on confirmation as well as at draft time.

Confirming an order is a `Manager` action that moves it from `DRAFT` to `CONFIRMED`, subject to four checks evaluated in the order fixed in §2.8: the `line_items` array must be non-empty (otherwise `ERR_EMPTY_ORDER`); every line's book must be in `LISTED` status (otherwise `ERR_ITEM_NOT_LISTED`); for any consigned line, that book's `ConsignmentAgreement` must be `ACTIVE` (otherwise `ERR_CONSIGNMENT_NOT_ACTIVE`); and the `store_credit_applied_cents` must not exceed the buyer's current `store_credit_cents` (otherwise `ERR_INSUFFICIENT_STORE_CREDIT`, HTTP 402). As noted in §2.8, the item-not-listed state check outranks the consignment-not-active referential check when both would fail. Confirmation then drives a three-hop cascade within the single request: each line's book transitions from `LISTED` to `SOLD`; each newly sold book pulls its catalog listing's sold axis to `SOLD` according to the order channel (settling the other axis to `PULLED` or `DELISTED` as described in §3.4); and each consigned book's agreement moves from `ACTIVE` to `SETTLED`, accruing its consignor payout into the consignor's `consignor_payable_cents`. In the same transaction the buyer's `store_credit_cents` is reduced by the `store_credit_applied_cents`, and the consignor-payable balance rises by the sum of consignment payouts over the consigned lines.

Refunding is a `Manager` action permitted only on a `CONFIRMED` order (otherwise `ERR_ORDER_NOT_CONFIRMED`); it moves the order to `REFUNDED` and compensates every effect of confirmation exactly. Each line's book returns from `SOLD` to `LISTED`, each listing's sold axis is restored to its pre-sale live value with `sold_channel` cleared, and each consigned agreement returns from `SETTLED` to `ACTIVE`. The buyer's `store_credit_cents` is increased by the `store_credit_applied_cents` and the `consignor_payable_cents` is decreased by the same sum of consignment payouts that confirmation accrued, so a confirm-then-refund pair leaves both ledgers exactly where they began.

### 3.9. Shipping and Packing

After an order is confirmed, a `StoreClerk` packs it into a `Shipment`. The shipment records the `sale_order_id` of the order, a `packing_station_label` (the logical station occupied while packing), a `weight_grams`, a shipping `zone` (an integer 1 through 4), a `pack_start` (inclusive) and `pack_end` (exclusive) bounding the packing slot, and optionally a `declared_value_cents` (defaulting to 0) and an `insured` flag (defaulting to false). The packing window must be well-formed — `pack_end` strictly after `pack_start`, else `ERR_INVALID_WINDOW` — and every shipment is created in `PACKED`.

Packing stations enforce an idle buffer of 15 minutes between shipments on the same `packing_station_label`. A new shipment is accepted only when it is clear of every other shipment on that same station by at least the buffer — that is, either the new packing slot's `pack_start` is at least 15 minutes at or after the other shipment's `pack_end`, or the other shipment's `pack_start` is at least 15 minutes at or after the new slot's `pack_end`. Being exactly the buffer apart is accepted; any closer overlap is rejected with `ERR_PACKING_SLOT_CONFLICT`.

The `shipping_cost_cents` is computed as carriage plus insurance. Carriage starts from a per-zone base — 500 cents for zone 1, 800 for zone 2, 1200 for zone 3, and 1800 for zone 4. Weight over the first 500 grams is billable: subtract 500 grams from `weight_grams`, taking the excess as 0 if the weight is at or under 500 grams, then divide that billable excess by 250 grams and round up to a whole number of steps. Carriage is the zone base plus 150 cents per step, then clamped to lie between a floor of 500 cents and a cap of 6000 cents — values below the floor are raised to 500, values above the cap are lowered to 6000. Insurance is 0 when the shipment is not insured. When it is insured, insurance is the `declared_value_cents` multiplied by an insurance rate of 0.02, rounded half up to whole cents, then held between a minimum of 200 cents and a maximum of 5000 cents — a computed value below 200 is raised to 200 and one above 5000 is lowered to 5000. The final `shipping_cost_cents` is the clamped carriage plus this insurance. An order's shipment is retrievable by the order's identifier, returned as an array of zero or one.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; retrieving a resource returns HTTP 200; operations that modify an existing resource (state transitions, listing edits) return HTTP 200. Request bodies, response payloads, and side effects for each endpoint are specified in the §3 workflow narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/patrons` | Register a patron (consignor / buyer / seller) | StoreClerk, Manager |
| GET | `/patrons/{id}` | Get a patron including derived ledger balances | Patron, Appraiser, StoreClerk, Manager |
| POST | `/intake-lots` | Open an intake lot | StoreClerk, Manager |
| GET | `/intake-lots/{id}` | Get an intake lot | Patron, Appraiser, StoreClerk, Manager |
| POST | `/intake-lots/{id}/book-items` | Intake a book item into the lot | StoreClerk |
| POST | `/intake-lots/{id}/settle` | Settle a fully-appraised lot | Manager |
| POST | `/intake-lots/{id}/reject` | Reject a lot (cascade withdraws books, voids appraisals) | Manager |
| GET | `/book-items/{id}` | Get a book item including its provenance log | Patron, Appraiser, StoreClerk, Manager |
| GET | `/book-items` | List and filter book items | Patron, Appraiser, StoreClerk, Manager |
| POST | `/book-items/{id}/grade` | Grade condition and determine first edition | Appraiser |
| POST | `/book-items/{id}/appraisals` | Issue an appraisal (supersedes prior; OCC on book version) | Appraiser |
| GET | `/book-items/{id}/appraisals` | List appraisals for a book item | Patron, Appraiser, StoreClerk, Manager |
| POST | `/book-items/{id}/listing` | Create the catalog listing (requires the book appraised) | StoreClerk |
| GET | `/book-items/{id}/listing` | Get the book's catalog listing (array of 0..1) | Patron, Appraiser, StoreClerk, Manager |
| POST | `/consignment-agreements` | Propose a consignment agreement for a book | Manager |
| GET | `/consignment-agreements/{id}` | Get a consignment agreement | Patron, Appraiser, StoreClerk, Manager |
| GET | `/consignment-agreements` | List and filter consignment agreements | Patron, Appraiser, StoreClerk, Manager |
| POST | `/consignment-agreements/{id}/amend` | Amend terms (cyclic; OCC on agreement version) | Manager |
| POST | `/consignment-agreements/{id}/activate` | Activate the agreement | Manager |
| PATCH | `/catalog-listings/{id}` | Update listing price and/or a channel axis (OCC on listing version) | StoreClerk |
| POST | `/buyback-offers` | Create a buyback offer (auto-approves at/under limit) | StoreClerk, Manager |
| GET | `/buyback-offers/{id}` | Get a buyback offer | Patron, Appraiser, StoreClerk, Manager |
| GET | `/buyback-offers` | List and filter buyback offers | Patron, Appraiser, StoreClerk, Manager |
| POST | `/buyback-offers/{id}/accept` | Accept an offer, issuing store credit | Manager |
| POST | `/buyback-offers/{id}/void` | Void an accepted offer, reversing store credit | Manager |
| POST | `/fair-events` | Create a fair/show | Manager |
| GET | `/fair-events/{id}` | Get a fair/show | Patron, Appraiser, StoreClerk, Manager |
| POST | `/fair-events/{id}/booth-slots` | Reserve a booth slot (overlap + capacity checks) | StoreClerk, Manager |
| GET | `/fair-events/{id}/booth-slots` | List booth slots for a fair | Patron, Appraiser, StoreClerk, Manager |
| POST | `/sale-orders` | Draft a sale order (computes subtotal/total) | StoreClerk, Manager |
| GET | `/sale-orders/{id}` | Get a sale order | Patron, Appraiser, StoreClerk, Manager |
| POST | `/sale-orders/{id}/confirm` | Confirm the order (cascade + both ledger invariants) | Manager |
| POST | `/sale-orders/{id}/refund` | Refund a confirmed order (full compensation) | Manager |
| POST | `/sale-orders/{id}/shipment` | Pack/ship a confirmed order (shipping cost + packing buffer) | StoreClerk |
| GET | `/sale-orders/{id}/shipment` | Get the order's shipment (array of 0..1) | Patron, Appraiser, StoreClerk, Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_WINDOW | 400 |
| ERR_PATRON_NOT_FOUND | 404 |
| ERR_INTAKE_LOT_NOT_FOUND | 404 |
| ERR_BOOK_ITEM_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_LISTING_NOT_FOUND | 404 |
| ERR_OFFER_NOT_FOUND | 404 |
| ERR_FAIR_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_ITEM_NOT_GRADED | 409 |
| ERR_ITEM_NOT_APPRAISED | 409 |
| ERR_ITEM_NOT_LISTED | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_NOT_CONFIRMED | 409 |
| ERR_AGREEMENT_NOT_AMENDABLE | 409 |
| ERR_OFFER_NOT_ACCEPTABLE | 409 |
| ERR_OFFER_NOT_VOIDABLE | 409 |
| ERR_EMPTY_LOT | 409 |
| ERR_LOT_ITEMS_NOT_APPRAISED | 409 |
| ERR_EMPTY_ORDER | 409 |
| ERR_CONSIGNMENT_NOT_ACTIVE | 409 |
| ERR_BOOTH_SLOT_CONFLICT | 409 |
| ERR_FAIR_CAPACITY_EXCEEDED | 409 |
| ERR_PACKING_SLOT_CONFLICT | 409 |
| ERR_INSUFFICIENT_STORE_CREDIT | 402 |
| ERR_CREDIT_ALREADY_SPENT | 402 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_DUPLICATE_LISTING | 409 |
| ERR_STALE_VERSION | 412 |
