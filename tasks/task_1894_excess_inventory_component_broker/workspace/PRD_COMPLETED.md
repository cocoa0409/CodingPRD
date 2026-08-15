# Excess Inventory Component Broker API — Product Requirements Document

## 1. Introduction

Independent electronics component brokers operate in the gap between two chronic industry problems: manufacturers and contract assemblers sit on excess inventory they cannot easily liquidate, and downstream buyers cannot source constrained or discontinued parts through franchised channels at any price. This document specifies the API for a brokerage platform that closes that gap. It governs the complete trade lifecycle — intake of seller buy offers, broker acceptance under a broker-owned or consignment acquisition model, incoming inspection with counterfeit screening, physical custody in storage bins, market-facing listings, escrowed customer orders, settlement under age- and volatility-aware pricing, and post-delivery returns with full escrow refunds.

Because the broker routinely stands between a seller and a customer with money and goods in motion, the platform treats funds, custody, and provenance as first-class concerns. Customers fund one hundred percent of a provisional price into escrow before fulfillment begins; consignment proceeds are split between broker fee and seller payout under a pinned rounding order; every lot's carrying value is tracked simultaneously on a straight-line depreciation basis and on a mark-to-market basis fed by market price intelligence; and any suspicion of counterfeit material freezes listing activation and order placement until an inspector clears the lot. The sections below define every behavioral contract the implementation must satisfy.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (401). The system recognizes exactly five roles: `BrokerOps`, `Inspector`, `FinanceAdmin`, `Seller`, and `Customer`. Every operation names the roles permitted to invoke it; a caller whose role is not in that list is rejected with `ERR_FORBIDDEN_ROLE` (403).

These roles divide the workflow along a deliberate segregation-of-duties line. `BrokerOps` is the operations desk: offer review and acceptance, receiving, lot conversion, listing management, fulfillment, consignment administration, market-price capture, and clock control. `Inspector` owns quality: recording inspection outcomes, raising counterfeit-suspect flags, and controlling quarantine. `FinanceAdmin` is deliberately separated from operations and alone may settle delivered orders and issue approved refunds — the staff who move the goods never release the money. `Seller` and `Customer` are entity-backed trading counterparties rather than staff.

Identity semantics differ between these two groups. When `X-User-Role` is `BrokerOps`, `Inspector`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting Seller, and ownership checks on any resource that references a Seller compare the resource's seller foreign key to `X-User-ID` — a Seller submits and cancels only their own buy offers and reads only their own seller record and offer history. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; placing orders, funding escrow, cancelling, opening return cases, and order-scoped reads are all restricted to resources whose customer reference equals `X-User-ID`. An entity-backed caller acting on a resource it does not own is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403).

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

Requests to an undefined path, or to a defined path with an unsupported method, are rejected in the same envelope with `ERR_INVALID_REQUEST` (404 and 405 respectively); an unexpected server failure is answered with `ERR_INTERNAL` (500).

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, and a supplied value below 1 is raised to 1 while a value above 100 is lowered to 100. `offset` sets the number of items skipped: it defaults to 0, and a negative value is raised to 0. A `limit` or `offset` that does not parse as an integer is rejected with `ERR_INVALID_REQUEST` (400), and the `meta` fields echo the effective clamped values. Unless an endpoint states otherwise, list responses sort by `created_at` in ascending order, with ties broken in the order the resources were created, earliest first. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. The Logical Clock and Server-Stamped Timestamps

Every timestamp the server stamps onto a resource — `created_at`, `updated_at`, a lot's `received_at`, a snapshot's `observed_at` — reads a logical clock, never the wall clock. At startup, before any clock-control call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z. Every timestamp the server emits — the stamped fields above, the envelope's `api_request_timestamp`, client-supplied instants the server echoes back such as an agreement's `effective_from` and `effective_to`, and the clock call's `current_utc` — is serialized in a single canonical form: ISO 8601 UTC with exactly three fractional digits, so a whole-second instant renders with `.000` and the startup clock therefore appears in responses as `2026-08-01T00:00:00.000Z`. A `BrokerOps`-only clock-control capability sets the logical clock to a supplied `to_iso8601` instant — any parseable instant is accepted, with no requirement that it be later than the current reading — and answers with the now-current time as `current_utc`. Anywhere a client supplies an ISO 8601 instant — `to_iso8601` here or an agreement's `effective_from` and `effective_to` — a value without an explicit offset is interpreted as UTC, any offset is normalized to UTC, and an unparseable value is rejected with `ERR_INVALID_REQUEST` (400).

Advancing the clock is not a passive read of time. The call sweeps the consignment book: every agreement still `ACTIVE` whose `effective_to` falls at or before the new current time transitions to `EXPIRED`, every `ACTIVE` listing on each expired agreement's lot cascades to `PAUSED`, and each affected lot's posture is recomputed (once per expired agreement when several expire on the same lot). Business readers should assume that time-sensitive rules — agreement windows, lot age, market-observation windows — all evaluate against this logical clock.

### 2.5. Common Resource Properties

Sellers, customers, storage bins, buy offers, lots, consignment agreements, listings, sales orders, and return cases share four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation, including system-driven changes such as a lot posture recomputation. `version` is an integer starting at one that increments by one on every mutation, and it underpins the optimistic concurrency control described in §2.9.

Two resources deliberately break this pattern. A market price snapshot and an escrow entry are immutable records written once and never modified: each carries `id` and `created_at` only, and both `updated_at` and `version` are absent from their representations.

### 2.6. Money, Integer Cents, and Rounding Discipline

Every monetary amount in the platform is an integer number of cents — asking prices, agreed prices, escrow balances, carrying values, fees, payouts, refunds, and credit limits alike; no dollars-and-decimals representation appears anywhere in the API. Where a calculation must round, it rounds half-up to the nearest whole cent, and each pricing rule in §3 names the exact step at which that single rounding occurs — no monetary calculation rounds twice. Comparisons that gate pricing, most notably the market-volatility threshold of §3.7, are evaluated on exact ratios with no rounding applied before the comparison. Quantities and bin capacities are likewise exact integers.

### 2.7. Lot Posture: Derived Status and the Quarantine Override

A lot's `status` is never set directly by a client; with a single exception it is derived from the lot's own counters and listing attachments. The derivation recomputes whenever `qty_available`, `qty_reserved`, `qty_sold`, or `qty_returned` mutates, whenever a listing on the lot is activated, paused, or withdrawn, and whenever a quarantine action lands, and it applies a fixed order of checks. If the lot has been manually quarantined, the status is `QUARANTINED`. Otherwise, if `qty_available` is zero and `qty_reserved` is zero and the sum of `qty_sold` and `qty_returned` is greater than zero, the lot is `DEPLETED`. Otherwise, if `qty_available` is zero, the lot is `FULLY_RESERVED`. Otherwise, if any listing on the lot is `ACTIVE`, the lot is `LISTED`. In every remaining case the lot is `IN_STOCK`. Because each recompute is a mutation of the lot, it refreshes the lot's `updated_at` and increments its `version`.

### 2.8. The Escrow Ledger

Every sales order owns an append-only escrow ledger. Each movement of funds writes an escrow entry carrying the owning order reference, a system-stamped `entry_type`, a signed `amount_cents`, and a human-readable `note`. Five entry types exist. `DEPOSIT` entries are positive and accumulate customer funds into escrow. `CUSTOMER_REFUND`, `BROKER_FEE`, `SELLER_PAYOUT`, and `BROKER_REVENUE` entries are negative and disburse funds out of escrow. Entries are never edited and never deleted, and the ledger always reads chronologically by `created_at` ascending, with entries stamped at the same instant reading in the order they were written. This ledger is the audit trail behind the order's `escrow_funded_cents` figure and behind every movement in a seller's balance.

### 2.9. Optimistic Concurrency Control on Listing Repricing

Exactly one write operation in the platform is guarded by optimistic concurrency control: repricing a listing. A reprice request must carry `expected_listing_version`, a non-optional field holding the listing `version` the client last observed. If that value no longer matches the listing's current `version` — because another write has advanced the listing since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is applied. A successful reprice increments the listing's `version` by one. No other endpoint accepts a version field; every other write proceeds without an optimistic-concurrency check.

### 2.10. Identifier Resolution and Validation Precedence

Requests are validated against a fixed precedence ladder, so a request violating several rules always surfaces the earliest failure rather than an arbitrary one. First comes authentication: missing or invalid identity headers yield `ERR_UNAUTHENTICATED`. Second, role authorization: a role outside the endpoint's permitted list yields `ERR_FORBIDDEN_ROLE`. Third, entity-backed ownership: a Seller or Customer touching a resource outside their ownership scope yields `ERR_FORBIDDEN_OWNERSHIP`. An ownership comparison decidable from the request alone — the caller's `X-User-ID` against an identifier carried in the path or body — is evaluated at this rung; an ownership comparison that requires the target resource's stored fields is evaluated immediately after that resource's existence check below, so a request naming an unknown resource surfaces its 404 before any ownership question. Fourth, existence: every identifier in the path and every foreign key referenced in the request body must resolve to a real resource, with path identifiers checked left to right, then foreign keys in the request body checked in the order the endpoint's narrative names them, and the first unresolved identifier producing its specific 404 — `ERR_SELLER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_STORAGE_BIN_NOT_FOUND`, `ERR_BUY_OFFER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND`, or `ERR_RETURN_CASE_NOT_FOUND`, according to the resource type. Fifth, the listing staleness check, `ERR_STALE_VERSION`. Sixth, state eligibility: the target resource must sit in a valid source state for the requested transition, failing with `ERR_INVALID_STATE` or with one of the specific state guards introduced in §3. Seventh, counterfeit and provenance safety (`ERR_COUNTERFEIT_SUSPECTED`, `ERR_PROVENANCE_DOCUMENT_REQUIRED`). Eighth, consignment window rules. Ninth, structural constraints: bin capacity, available quantity, the asking-price floor, escrow overpayment, consignment seller matching, fee range, and bin-code uniqueness. Tenth and last, fiscal guards: customer credit sufficiency and the strict positivity of monetary and quantity inputs. A malformed payload — a missing required field, a value of the wrong type, or an unknown enum value — is rejected with `ERR_INVALID_REQUEST` (400); this payload-shape validation is evaluated immediately after role authorization and before every later rung, so it surfaces ahead of ownership, existence, state, and business-rule failures.

## 3. Business Logic & Workflows

### 3.1. Counterparty Onboarding: Sellers, Customers, and Storage Bins

`BrokerOps` registers each selling counterparty with a legal `name`, a `contact_email`, and optionally `payout_terms_days`, the seller's net payment terms in days, which defaults to 30 and is informational only — no settlement behavior reads it. Two computed balances track what the broker owes the seller over time: `account_balance_cents`, the unpaid consignment proceeds currently owed, and `total_payouts_cents`, the lifetime sum of seller payouts across every settled order for lots originating from that seller. Both open at zero, and §3.7 describes the single event that grows them.

Customer registration captures a `name`, a `contact_email`, a `credit_limit_cents` establishing the maximum open-order exposure the broker will extend — it may be zero but never negative — and an optional `urgency_tier` of `STANDARD`, `PRIORITY`, or `CRITICAL`, defaulting to `STANDARD`, which drives the provisional price premium defined in §3.6. The customer's `open_order_exposure_cents` starts at zero and is maintained by the system as orders open and close. A `BrokerOps` or `FinanceAdmin` operator may read any customer record; a `Customer` may read their own.

Storage bins are the platform's physical custody unit. Each bin carries a human-readable `bin_code` that must be unique across all bins — a duplicate submission is rejected with `ERR_DUPLICATE_BIN_CODE` — and a `capacity_units` greater than zero. Two computed counters describe occupancy: `occupied_units`, the total component units currently stored in the bin, and `available_units`, the remaining free space. §3.3 defines both precisely.

Across every creation endpoint, monetary and quantity inputs must be strictly positive wherever a positive value is required; a zero or negative amount is rejected with `ERR_INVALID_AMOUNT`.

### 3.2. The Buy Offer Pipeline: Review, Receipt, and Inspection

Sourcing begins when a `Seller` submits a buy offer for excess inventory, passing a `seller_id` equal to their own identity, the manufacturer part number `mpn`, the `quantity` of units offered, and the per-unit `ask_price_per_unit_cents`. A `provenance_doc_url` pointing at provenance documentation may be attached at submission or deferred until inspection. The new offer enters `PENDING_REVIEW`.

Adjudication belongs to `BrokerOps`. Accepting the offer records the broker-agreed `agreed_unit_price_cents` per unit and the `acquisition_mode` — `BROKER_OWNED` when the broker buys the position outright, `CONSIGNMENT` when the parts remain the seller's property until sold — and moves the offer to `ACCEPTED`. Rejecting moves it to `REJECTED`. The seller may instead withdraw a still-pending offer themselves, moving it to `CANCELLED`; cancel is restricted to the offering seller. All three of these decisions are available only from `PENDING_REVIEW`, and indeed every pipeline action is state-guarded — invoking one against an offer in the wrong state is rejected with `ERR_INVALID_STATE`.

When the parts physically arrive, `BrokerOps` records receipt and the offer moves from `ACCEPTED` to `UNDER_INSPECTION`, entering the inspection queue. An `Inspector` then records the inspection `outcome`. A passing outcome demands provenance documentation: either the offer's `provenance_doc_url` is already set, or the inspection payload itself supplies a `provenance_doc_url`, which is then recorded onto the offer; when neither is present the pass is rejected with `ERR_PROVENANCE_DOCUMENT_REQUIRED`. A successful pass moves the offer to `INSPECTION_PASSED` and records `inspection_result` as `PASS`. Three failure outcomes exist — `FAIL_COUNTERFEIT` for suspected counterfeit material, `FAIL_DAMAGED` for physically damaged goods, and `FAIL_DOCUMENTATION` for inadequate paperwork — and any of them moves the offer to `INSPECTION_FAILED`, records that outcome in `inspection_result`, and preserves the inspector's `failure_note`. Until inspection completes, `inspection_result` remains `NONE`.

Failed-inspection goods go back to the seller at the broker's direction. `BrokerOps` initiates the return, moving the offer from `INSPECTION_FAILED` to `RETURN_PENDING`, and later records the physical ship-back, moving it from `RETURN_PENDING` to `RETURNED`. Because the broker never took ownership of returned goods, the seller's `account_balance_cents` is left untouched by the entire return flow. `REJECTED`, `CANCELLED`, `CONVERTED`, and `RETURNED` are the offer's terminal states; the path into `CONVERTED` runs through the lot conversion of §3.3. Sellers can follow their own pipeline through the buy-offer read and the per-seller offer history, both restricted to their own identity.

### 3.3. Lot Conversion, Physical Custody, and Carrying Value

Once an offer has passed inspection, `BrokerOps` converts it into a physical lot by naming a target bin through `storage_bin_id`. Conversion is an admission decision against bin capacity: the offer's `quantity` must fit within the bin's `available_units`. An exact fit is admitted; one unit over is rejected with `ERR_BIN_CAPACITY_EXCEEDED`. Occupancy is defined precisely — `occupied_units` is the sum of `qty_available` plus `qty_reserved` across every non-`DEPLETED` lot assigned to the bin, and `available_units` is `capacity_units` minus that occupancy — and it is recomputed whenever lot quantities mutate.

A successful conversion creates the Lot, answers with the new resource, and moves the offer to `CONVERTED`. The lot carries `buy_offer_id` pointing back to its originating offer, copies the `mpn`, copies the offer's acquisition mode into its own `storage_mode`, and records `quantity_received` as the offered quantity. It opens with `qty_available` equal to the full received quantity and `qty_reserved`, `qty_sold`, and `qty_returned` all at zero, sets `cost_basis_per_unit_cents` to the agreed unit price, stamps `received_at` from the logical clock, opens with `is_counterfeit_suspect` false, and starts in `IN_STOCK`. From that moment the lot's `status` follows the posture derivation of §2.7 — a lot only leaves `IN_STOCK` through listing activation, reservation pressure, quarantine, or depletion.

The broker tracks each lot's carrying value on two bases simultaneously, and both are exposed whenever a lot is read. The straight-line basis, `carrying_value_straight_line_cents`, decays the cost of on-hand units over a 365-day horizon: it is the per-unit `cost_basis_per_unit_cents` multiplied by the on-hand unit count — `qty_available` plus `qty_reserved` — then multiplied by the fraction of the horizon remaining, which is one minus the number of whole days elapsed since `received_at` divided by 365, floored at zero so a lot a full year old or older carries nothing, with the final figure rounded half-up to a whole cent. The market basis, `carrying_value_market_cents`, ignores age entirely: it takes the most recent market price snapshot for the lot's `mpn` — the snapshot with the greatest `observed_at`, ties broken by the greatest `created_at`, with any further tie going to the later-recorded snapshot — multiplies its `spot_price_cents` by the broker haircut of 0.85 and by the on-hand unit count, and rounds half-up to a whole cent; when no snapshot exists for the part number, the market-basis value is null. The two bases generally disagree, and both refresh as age advances and as new snapshots arrive. Lots may be browsed in a list, optionally filtered by `buy_offer_id` or `storage_bin_id`.

Counterfeit risk is managed at lot granularity. An `Inspector` may flag a lot as counterfeit-suspect at any time, whatever the lot's current status, which sets `is_counterfeit_suspect` to true without changing the lot's status; the flag alone blocks listing activation and new order creation against the lot, both failing with `ERR_COUNTERFEIT_SUSPECTED`. When containment is required, the inspector quarantines the lot, optionally attaching a `quarantine_note` in the request payload — the note is accepted but not persisted, and no representation of the lot carries it. Quarantine is permitted only while the suspect flag is set and the lot is not `DEPLETED`; an attempt that fails either condition is rejected with `ERR_INVALID_STATE`. Quarantine forces the lot's status to `QUARANTINED` regardless of the posture derivation and withdraws every `ACTIVE` listing on the lot, each moving to `WITHDRAWN`; open orders on the lot remain in place, but they cannot be fulfilled and cannot be settled while the quarantine stands, both attempts failing with `ERR_LOT_QUARANTINED`. Releasing the quarantine is valid only on a `QUARANTINED` lot: it clears the suspect flag and recomputes the base posture, which cannot be `LISTED` at that moment — quarantine withdrew every listing, and activation was impossible while the flag stood — so the lot ordinarily lands back on `IN_STOCK`.

### 3.4. Consignment Agreements and Market Price Intelligence

A lot acquired under `CONSIGNMENT` cannot be advertised until a consignment agreement is in force. `BrokerOps` creates the agreement by naming the consigning `seller_id`, the `lot_id`, a broker fee `broker_fee_bps` expressed in basis points of the final settlement total, and a window running from `effective_from`, inclusive, to `effective_to`, exclusive — a half-open interval. Creation enforces four rules. The lot's `storage_mode` must be `CONSIGNMENT`, otherwise the creation fails with `ERR_LOT_NOT_CONSIGNMENT`. The named seller must be the seller of the lot's originating buy offer, otherwise `ERR_CONSIGNMENT_SELLER_MISMATCH`. The window must open before it closes — `effective_from` strictly earlier than `effective_to` — otherwise `ERR_CONSIGNMENT_WINDOW_INVALID`. And the window must not overlap any other `ACTIVE` agreement on the same lot under half-open semantics — two windows that merely touch, one ending exactly when the other begins, do not overlap — otherwise `ERR_CONSIGNMENT_WINDOW_OVERLAP`. The fee itself must sit between 1 and 5000 basis points inclusive, otherwise `ERR_INVALID_FEE_BPS`. A new agreement starts in `ACTIVE`.

An agreement ends in two ways, and both produce the same cascade. `BrokerOps` may terminate an agreement, which requires it to be `ACTIVE` — termination in any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE` — and moves it to `TERMINATED`. Alternatively the clock sweep of §2.4 expires an agreement whose window has closed, moving it from `ACTIVE` to `EXPIRED`. Either way, every `ACTIVE` listing on the agreement's lot is paused to `PAUSED` and the lot's posture is recomputed, so a consignment lot whose coverage lapses silently falls off the market until a fresh window is in place. Agreements can be listed with optional `seller_id` and `lot_id` filters.

Market price intelligence feeds pricing throughout the platform. `BrokerOps` records an observation as a snapshot carrying the part number `mpn`, the observed `spot_price_cents` per unit — strictly positive — and a `source` label such as a distributor feed or a trade-desk note; the server stamps `observed_at` from the logical clock at the moment of recording. Recording a snapshot is a propagating event: the mark-to-market carrying value of every lot with a matching `mpn` is recomputed, and so is the recommended price of every `ACTIVE` listing sitting on those lots. Snapshot history is queryable with an optional `mpn` filter and — as the platform's deliberate exception to the default sort — is returned newest first, ordered by `observed_at` descending with `created_at` descending as the tie-breaker and any remaining tie broken in favor of the later-recorded snapshot.

### 3.5. Listing Lifecycle and Price Governance

A listing advertises a lot at an `asking_price_per_unit_cents`. `BrokerOps` creates it in `DRAFT` against a `lot_id`, and the system immediately computes `recommended_price_per_unit_cents`: the most recent snapshot for the lot's part number — greatest `observed_at`, ties broken by greatest `created_at`, with any further tie going to the later-recorded snapshot — marked up by ten percent and rounded half-up to a whole cent, or null when no snapshot exists for that part number. The asking price itself is governed by a cost floor at every stage of life: it must never fall below eighty percent of the lot's `cost_basis_per_unit_cents`, rounded down to a whole cent. The floor is checked when the listing is created, again whenever it is repriced, and once more at every activation; any violation is rejected with `ERR_ASKING_BELOW_COST_FLOOR`.

Activation moves a listing from `DRAFT` to `ACTIVE`, or from `PAUSED` back to `ACTIVE`, under a battery of preconditions evaluated in the precedence order of §2.10. The lot's posture must be `IN_STOCK`, failing with `ERR_LOT_NOT_IN_STOCK` — and because any other `ACTIVE` listing on the lot would already have made the posture `LISTED`, this one check also enforces the platform's rule of at most one `ACTIVE` listing per lot. The lot must not be counterfeit-suspect, failing with `ERR_COUNTERFEIT_SUSPECTED`. When the lot is consigned, an `ACTIVE` consignment agreement whose window contains the current clock time must exist — the current instant must be at or after `effective_from` and strictly before `effective_to` — failing with `ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT`. Finally, the asking price must satisfy the cost floor. A successful activation recomputes the lot's posture from `IN_STOCK` to `LISTED`.

Pausing moves an `ACTIVE` listing to `PAUSED` and recomputes the lot's posture, which falls back to `IN_STOCK` when no other `ACTIVE` listing remains on the lot. Withdrawing is permanent: a listing in `DRAFT`, `ACTIVE`, or `PAUSED` may move to `WITHDRAWN`, whether through an explicit `BrokerOps` withdrawal or automatically when its lot is quarantined. The remaining terminal state, `SOLD_OUT`, is reached only from `ACTIVE` and only by the system, at the moment the underlying lot becomes `DEPLETED` through order settlement or refund issuance. Invoking any of these listing actions from an incompatible state — pausing a draft, withdrawing a sold-out listing, and so on — is rejected with `ERR_INVALID_STATE`.

Repricing is the platform's single optimistic-concurrency-guarded write, as specified in §2.9. It is available only while the listing is `DRAFT` or `PAUSED` — attempts against any other listing state are rejected with `ERR_INVALID_STATE` — and the request must carry `expected_listing_version` alongside the new `asking_price_per_unit_cents`. Because the staleness check outranks state eligibility on the precedence ladder, a stale reprice surfaces `ERR_STALE_VERSION` even when the listing's state would also have been a problem. A successful reprice applies the floor check to the new price, increments the listing's `version` by one, and refreshes its `updated_at`. Listings are broadly browsable — `BrokerOps`, `Inspector`, `FinanceAdmin`, and `Customer` may all read them, with an optional `lot_id` filter — since customers need market visibility before placing orders.

### 3.6. Order Placement, Provisional Pricing, and Escrow Funding

A `Customer` places an order against a listing by passing their own `customer_id`, the `listing_id`, and a strictly positive `quantity`. Admission runs the precedence ladder of §2.10: the listing must be `ACTIVE`, failing with `ERR_LISTING_NOT_ACTIVE`; the underlying lot must not be counterfeit-suspect, failing with `ERR_COUNTERFEIT_SUSPECTED`; the `quantity` must not exceed the lot's `qty_available`, failing with `ERR_QUANTITY_EXCEEDS_AVAILABLE`; and the customer's credit must absorb the new exposure, as defined below.

Provisional pricing applies at creation. The customer's urgency tier sets a premium over the listing's asking price: zero percent for `STANDARD`, ten percent for `PRIORITY`, and twenty-five percent for `CRITICAL`. The `provisional_unit_price_cents` is the listing's `asking_price_per_unit_cents` increased by that premium, rounded half-up to a whole cent; `provisional_total_cents` is that unit price multiplied by the `quantity`; and `required_escrow_cents` equals the provisional total, because the broker demands one hundred percent of the provisional price in escrow before any work begins. Two snapshots are frozen onto the order at creation: `urgency_tier_snapshot` captures the customer's tier so that a later tier change never reprices an open order, and `consignment_fee_bps_snapshot` captures the `broker_fee_bps` of the consignment agreement that is `ACTIVE` and current at that moment — null for broker-owned lots.

Creation moves physical units immediately: the lot's `qty_available` decreases and its `qty_reserved` increases by the ordered quantity, and the posture recomputes — an order that drains the last available unit pushes the lot to `FULLY_RESERVED`. The new order opens in `PENDING_ESCROW`.

The credit guard is exact integer arithmetic. A customer's `open_order_exposure_cents` is the sum of `required_escrow_cents` over all of their orders sitting in `PENDING_ESCROW`, `ESCROW_FUNDED`, `FULFILLING`, `SHIPPED`, `DELIVERED`, or `REFUND_PENDING`; orders that have settled, cancelled, or refunded no longer count. Admission requires the existing exposure plus the new order's `required_escrow_cents` to be no more than `credit_limit_cents` — exact equality is admitted, and one cent over is rejected with `ERR_INSUFFICIENT_CUSTOMER_CREDIT` (402). Exposure is recomputed on every order creation, cancellation, settlement, and refund issuance.

The customer funds escrow with deposits of `amount_cents` against an order whose `escrow_funded_cents` starts at zero. Each deposit must be strictly positive — a violation yields `ERR_INVALID_AMOUNT` — and each is booked as a positive `DEPOSIT` entry in the order's ledger while the order remains in `PENDING_ESCROW`; a deposit against an order that has left that state, such as a cancelled one, is rejected with `ERR_INVALID_STATE`. Partial deposits are welcome, but the running `escrow_funded_cents` may never exceed `required_escrow_cents`: a deposit that would overshoot the requirement is rejected with `ERR_ESCROW_OVERPAYMENT`. The deposit that brings the funded total to exactly the required amount moves the order from `PENDING_ESCROW` to `ESCROW_FUNDED`.

Cancellation is available to the owning customer and to `BrokerOps` from either pre-fulfillment state. Cancellation in either state releases the reservation — the lot's `qty_reserved` decreases and its `qty_available` increases by the order quantity, the posture recomputes, and the customer's exposure is recalculated — and whenever the order carries a positive funded balance it additionally books a `CUSTOMER_REFUND` entry returning every funded cent, the entry's amount being the negative of `escrow_funded_cents`; this refund applies equally to an `ESCROW_FUNDED` order and to a `PENDING_ESCROW` order that has received partial deposits. Either way the order lands in `CANCELLED`, and a reservation released while an `ACTIVE` listing still covers the lot restores the lot to `LISTED`, while a release with no active listing restores `IN_STOCK`.

Order and ledger reads are scoped. `BrokerOps` and `FinanceAdmin` may list all orders, optionally filtered by `customer_id` or `listing_id`, and may read any order, its escrow ledger, and its return cases. A `Customer` reads only their own orders, the escrow ledger of their own orders, and their own return cases.

### 3.7. Fulfillment, Settlement, and Proceeds Allocation

A funded order walks a deliberate fulfillment chain under `BrokerOps` control. Fulfillment begins by moving the order from `ESCROW_FUNDED` to `FULFILLING` — a step blocked while the lot is quarantined, failing with `ERR_LOT_QUARANTINED`, with the order's own state guard evaluated before the quarantine guard. Shipment then moves `FULFILLING` to `SHIPPED`, and delivery confirmation moves `SHIPPED` to `DELIVERED`. Each step is state-guarded: requesting any of them out of sequence is rejected with `ERR_INVALID_STATE`.

Settlement belongs to `FinanceAdmin` alone. It requires the order in `DELIVERED` and the lot out of quarantine, checked in that order — a quarantined lot blocks settlement with `ERR_LOT_QUARANTINED`, just as it blocked fulfillment — and it reprices the order finally. The final price starts from the order's own `provisional_unit_price_cents` and applies two independent discounts. The age discount is driven by the number of whole days between the lot's `received_at` and the settlement instant, partial days discarded: no discount while the lot is at most 89 days old, five percent when the age is 90 through 179 days, and twelve percent at 180 days or beyond. The volatility dampener looks at the market over the trailing thirty-day window — snapshots for the lot's `mpn` whose `observed_at` falls strictly after the instant thirty days (2,592,000 seconds) before settlement and at or before the settlement instant. Volatility is zero when fewer than two snapshots exist in that window; otherwise it is the spread between the highest and the lowest `spot_price_cents` in the window, divided by the lowest, compared exactly with no rounding before the comparison. Only when that ratio is strictly greater than 0.20 does a three percent dampener apply — a ratio of exactly 0.20 triggers nothing. The `final_unit_price_cents` is the provisional unit price reduced by the age discount and then by the volatility dampener, with a single round half-up to whole cents at that unit-price step; `final_total_cents` is the final unit price multiplied by the quantity; and `customer_refund_cents` is `provisional_total_cents` minus `final_total_cents`. Because the provisional price knew nothing of age or volatility, the final equals the provisional only when both adjustments come out zero. All three final figures remain null until the order actually settles.

Settlement then allocates funds through the escrow ledger. When the customer is owed money back — `customer_refund_cents` above zero — a `CUSTOMER_REFUND` entry books the negative of that amount. What happens to the remaining final total depends on the lot's storage mode. For a `BROKER_OWNED` lot the broker keeps everything: a single `BROKER_REVENUE` entry books the negative of `final_total_cents`, and no split occurs. For a `CONSIGNMENT` lot the proceeds split under a pinned rounding order that implementations must follow exactly: first the broker fee is computed as `final_total_cents` multiplied by the order's `consignment_fee_bps_snapshot` and divided by ten thousand, rounded half-up to a whole cent; then the seller payout is the exact remainder of `final_total_cents` after subtracting that fee. The payout is never computed by independently rounding the seller's percentage share, because the two orders of operation diverge on half-cent boundaries, and the fee basis is always the pinned snapshot captured at order creation, never whatever the agreement might say at settlement time. A `BROKER_FEE` entry books the negative of the fee and a `SELLER_PAYOUT` entry books the negative of the payout; recording that payout also increases the seller's `account_balance_cents` and `total_payouts_cents` by the payout amount.

Settlement moves units as well: the lot's `qty_reserved` decreases and its `qty_sold` increases by the order quantity, and the posture recomputes. When that recompute leaves no available and no reserved units with sold or returned units present, the lot becomes `DEPLETED`, and any `ACTIVE` listing still attached to it cascades to `SOLD_OUT`. The customer's exposure is recomputed one last time for the order, and the order reaches its terminal `SETTLED` state.

### 3.8. Returns and Refund Issuance

Post-delivery disputes open as return cases. A `Customer` opens a case against one of their own orders — and only while that order is `DELIVERED`, failing with `ERR_ORDER_NOT_DELIVERED` otherwise — supplying the `sales_order_id` and a `reason` of `COUNTERFEIT_SUSPECTED`, `DAMAGED`, `WRONG_PART`, or `FAILED_INCOMING_INSPECTION`. The case opens in `OPENED`. `BrokerOps` picks it up, moving it to `UNDER_REVIEW`, and from there decides its fate: rejection moves the case to `REJECTED` and records the reviewer's `rejection_note`, while approval requires the order to still be `DELIVERED` at approval time — again failing with `ERR_ORDER_NOT_DELIVERED` when it is not — sets the case's `refund_amount_cents` to the order's full `escrow_funded_cents`, moves the case to `APPROVED`, and pushes the order itself from `DELIVERED` to `REFUND_PENDING`. Every review action is state-guarded, and an action against a case in the wrong state is rejected with `ERR_INVALID_STATE`.

Money movement waits for finance. `FinanceAdmin` issues the refund against an `APPROVED` case, which books a `CUSTOMER_REFUND` escrow entry for the negative of `refund_amount_cents`, moves the order from `REFUND_PENDING` to `REFUNDED`, returns the units to the lot's books by decreasing `qty_reserved` and increasing `qty_returned` by the order quantity, recomputes the lot posture and the customer's exposure, and closes the case as `REFUND_ISSUED`. `REJECTED` and `REFUND_ISSUED` are the case's terminal states. Because refund issuance drains reservations exactly as settlement does, it participates in the same posture cascades — including driving a lot to `DEPLETED` and its remaining `ACTIVE` listing to `SOLD_OUT` when the counters line up.

## 4. Endpoint Definitions

Operations that create a new resource — registering a seller, customer, or storage bin, submitting a buy offer, converting a passed offer into a lot, recording a market price snapshot, opening a consignment agreement, creating a listing, placing an order, or opening a return case — answer `201 Created`. Operations that read or modify an existing resource, including every state transition and the clock-control call, answer `200 OK`. Request payloads, response payloads, and side effects are defined by the narratives of §2 and §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps expired consignment agreements | BrokerOps |
| POST | `/sellers` | Register a seller | BrokerOps |
| GET | `/sellers/{id}` | Get a seller, including computed balances | BrokerOps, FinanceAdmin, Seller |
| GET | `/sellers/{id}/buy-offers` | List a seller's buy offers (Seller restricted to own id) | BrokerOps, Inspector, Seller |
| POST | `/customers` | Register a customer | BrokerOps |
| GET | `/customers/{id}` | Get a customer, including computed open-order exposure | BrokerOps, FinanceAdmin, Customer |
| POST | `/storage-bins` | Create a storage bin | BrokerOps |
| GET | `/storage-bins/{id}` | Get a storage bin, including computed occupancy | BrokerOps, Inspector |
| POST | `/buy-offers` | Seller submits a buy offer for excess inventory | Seller |
| GET | `/buy-offers/{id}` | Get a buy offer (Seller restricted to own offers) | BrokerOps, Inspector, Seller |
| POST | `/buy-offers/{id}/accept` | Accept an offer at an agreed unit price and acquisition mode | BrokerOps |
| POST | `/buy-offers/{id}/reject` | Reject a pending offer | BrokerOps |
| POST | `/buy-offers/{id}/cancel` | Seller cancels their own pending offer | Seller |
| POST | `/buy-offers/{id}/receive` | Record physical receipt; offer enters inspection | BrokerOps |
| POST | `/buy-offers/{id}/inspect` | Record the inspection outcome; PASS requires provenance documentation | Inspector |
| POST | `/buy-offers/{id}/convert-to-lot` | Convert a passed offer into a physical lot in a storage bin | BrokerOps |
| POST | `/buy-offers/{id}/initiate-return` | Start the seller return of failed-inspection goods | BrokerOps |
| POST | `/buy-offers/{id}/mark-returned` | Record failed goods shipped back to the seller | BrokerOps |
| GET | `/lots` | List lots, optionally filtered by buy offer and/or storage bin | BrokerOps, Inspector, FinanceAdmin |
| GET | `/lots/{id}` | Get a lot, including posture status, quantities, and both carrying-value bases | BrokerOps, Inspector, FinanceAdmin |
| POST | `/lots/{id}/flag-counterfeit-suspect` | Flag a lot as counterfeit suspect (no status change) | Inspector |
| POST | `/lots/{id}/quarantine` | Quarantine a suspect lot; its ACTIVE listings are withdrawn | Inspector |
| POST | `/lots/{id}/release-quarantine` | Release a quarantined lot; clears the suspect flag and recomputes posture | Inspector |
| POST | `/market-price-snapshots` | Record a market spot-price observation; recomputes dependent values | BrokerOps |
| GET | `/market-price-snapshots` | List snapshots, optionally filtered by part number, newest first | BrokerOps, Inspector, FinanceAdmin |
| POST | `/consignment-agreements` | Create a consignment agreement window for a CONSIGNMENT lot | BrokerOps |
| GET | `/consignment-agreements` | List agreements, optionally filtered by seller and/or lot | BrokerOps, FinanceAdmin |
| GET | `/consignment-agreements/{id}` | Get a consignment agreement | BrokerOps, FinanceAdmin |
| POST | `/consignment-agreements/{id}/terminate` | Terminate an active agreement; ACTIVE listings on its lot are paused | BrokerOps |
| POST | `/listings` | Create a DRAFT listing for a lot | BrokerOps |
| GET | `/listings` | List listings, optionally filtered by lot | BrokerOps, Inspector, FinanceAdmin, Customer |
| GET | `/listings/{id}` | Get a listing | BrokerOps, Inspector, FinanceAdmin, Customer |
| PATCH | `/listings/{id}` | Reprice a DRAFT or PAUSED listing (OCC-guarded) | BrokerOps |
| POST | `/listings/{id}/activate` | Activate a DRAFT or PAUSED listing | BrokerOps |
| POST | `/listings/{id}/pause` | Pause an ACTIVE listing | BrokerOps |
| POST | `/listings/{id}/withdraw` | Permanently withdraw a listing | BrokerOps |
| POST | `/sales-orders` | Place an order against an ACTIVE listing; computes provisional pricing and escrow requirement | Customer |
| GET | `/sales-orders` | List orders, optionally filtered by customer and/or listing | BrokerOps, FinanceAdmin |
| GET | `/sales-orders/{id}` | Get an order (Customer restricted to own orders) | BrokerOps, FinanceAdmin, Customer |
| POST | `/sales-orders/{id}/escrow/deposit` | Fund escrow; reaching exactly the requirement transitions the order | Customer |
| POST | `/sales-orders/{id}/fulfill` | Begin fulfillment of a funded order | BrokerOps |
| POST | `/sales-orders/{id}/ship` | Mark an order shipped | BrokerOps |
| POST | `/sales-orders/{id}/deliver` | Mark an order delivered | BrokerOps |
| POST | `/sales-orders/{id}/settle` | Settle a delivered order: final pricing, refund delta, proceeds split | FinanceAdmin |
| POST | `/sales-orders/{id}/cancel` | Cancel a pre-fulfillment order; releases the reservation and refunds deposits | Customer, BrokerOps |
| GET | `/sales-orders/{id}/escrow-entries` | Read an order's append-only escrow ledger, chronological | BrokerOps, FinanceAdmin, Customer |
| POST | `/return-cases` | Open a return case on a DELIVERED order | Customer |
| GET | `/return-cases/{id}` | Get a return case | BrokerOps, FinanceAdmin, Customer |
| GET | `/sales-orders/{id}/return-cases` | List return cases for an order | BrokerOps, FinanceAdmin, Customer |
| POST | `/return-cases/{id}/start-review` | Start reviewing an open return case | BrokerOps |
| POST | `/return-cases/{id}/approve` | Approve a return; sets the refund to the order's funded escrow | BrokerOps |
| POST | `/return-cases/{id}/reject` | Reject a return case | BrokerOps |
| POST | `/return-cases/{id}/issue-refund` | Issue the approved refund; order refunded, units move reserved to returned | FinanceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_BIN_NOT_FOUND` | 404 Not Found |
| `ERR_BUY_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_SALES_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LISTING_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_IN_STOCK` | 409 Conflict |
| `ERR_LOT_QUARANTINED` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_CONSIGNMENT` | 409 Conflict |
| `ERR_CONSIGNMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT` | 409 Conflict |
| `ERR_COUNTERFEIT_SUSPECTED` | 422 Unprocessable Entity |
| `ERR_PROVENANCE_DOCUMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CONSIGNMENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_QUANTITY_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_ASKING_BELOW_COST_FLOOR` | 422 Unprocessable Entity |
| `ERR_ESCROW_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_CONSIGNMENT_SELLER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_FEE_BPS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BIN_CODE` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CUSTOMER_CREDIT` | 402 Payment Required |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INTERNAL` | 500 Internal Server Error |
