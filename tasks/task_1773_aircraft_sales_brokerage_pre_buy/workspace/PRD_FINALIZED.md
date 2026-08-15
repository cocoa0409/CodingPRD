# Aircraft Brokerage Pre-Buy API — Product Requirements Document

## 1. Introduction

Business aircraft transactions are high-value, multi-party negotiations in which a broker coordinates sellers, buyers, escrow companies, and maintenance facilities through a tightly sequenced deal pipeline: a listing is valued against market comparables, a buyer is qualified, a letter of intent is negotiated, an earnest deposit is escrowed, a pre-buy inspection is scheduled, findings are negotiated to resolution, and the deal is finally closed with commission, settlement, registration-change paperwork, and tax-planning coordination. Each stage carries money, safety, or regulatory exposure, and a mis-sequenced step — an inspection booked before escrow funds arrive, an airworthiness finding waived away, a closing executed before logbooks are verified — is precisely the kind of mistake a brokerage cannot afford.

This document specifies the product requirements for the Aircraft Brokerage Pre-Buy API, the system of record for that pipeline. The API serves a brokerage office's peer specialists — a sell-side agent, a buy-side agent, an escrow officer, an inspection-facility scheduler, and the broker principal — and enforces the deal's invariants mechanically: valuation thresholds before a listing may go to market, fiscal gates before an offer may be submitted, optimistic concurrency on negotiation and delivery-condition updates, automatic state propagation between the listing, the letter of intent, the transaction, the escrow deposit, and the inspection bookings, and a pinned settlement computation at closing. All endpoints are mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles:

- `BrokerPrincipal` — the brokerage office principal; owns inspection-facility registration, dual-agency disclosure acknowledgments, the delivery-condition checklist, and closing.
- `ListingAgent` — the broker's sell-side agent; owns listings, valuations, comparable sales, LOI acceptance, and seller-side discrepancy responses.
- `BuyerAgent` — the broker's buy-side agent; owns buyer registration and qualification, LOI submission and withdrawal, buyer-side discrepancy resolutions, and as-is acceptance.
- `EscrowOfficer` — the escrow company officer; records deposit funding.
- `FacilityScheduler` — the inspection facility scheduler; owns the booking lifecycle and the raising of inspection findings.

Each endpoint declares the roles authorized to invoke it, and a caller whose role is not in that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). For each of the five roles — `BrokerPrincipal`, `ListingAgent`, `BuyerAgent`, `EscrowOfficer`, and `FacilityScheduler` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any resource's `id` or foreign key; party selection in workflows such as disclosure acknowledgment is driven by explicit request inputs, not by the caller's header identity.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All nine resources in the system — InspectionFacility, Listing, Buyer, ComparableSale, LOI, Transaction, EscrowDeposit, InspectionBooking, and DiscrepancyItem — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations produced by automatic cascades.

Because every mutation — client-driven or cascaded — refreshes `updated_at` and increments `version`, a client can always detect that a resource changed beneath it by re-reading these two fields.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in the system are decimal values carried to exactly two decimal places using round-half-up rounding; monetary fields on inputs (such as `asking_price_usd`, `offer_price_usd`, `deposit_amount_usd`, `sale_price_usd`, `estimated_cost_usd`, and `proposed_credit_usd`) are likewise two-decimal values. Prices and deposits must be positive: `asking_price_usd`, `offer_price_usd`, `deposit_amount_usd`, and `sale_price_usd` are each rejected unless greater than zero, while `estimated_cost_usd` may be zero but never negative. Airframe times such as `total_time_hours` are whole-hour integers and must be non-negative. Two calculations impose additional, pinned rounding order: the FINAL market valuation rounds each adjusted comparable to cents before averaging, and the commission calculation rounds once at the variant total rather than per tier; both are specified step by step in §3.2 and §3.9. Monetary values in API responses are rendered as numbers with at most two decimal places.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only endpoints that take a version field:

- Countering an LOI requires the request to carry `expected_loi_version`, a non-optional field holding the LOI's `version` as the client last observed it. If the LOI's current `version` on the server has advanced beyond the supplied value — because another counter has already landed since the client last read the LOI — the counter is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client holding a stale view can never silently overwrite the newest negotiated price.
- Updating a transaction's delivery-condition checklist requires `expected_transaction_version`, a non-optional field holding the transaction's `version` as the client last observed it. Condition updates are legitimate in every non-terminal transaction state, so the version is the only deterministic signal that the client's view (of `credits_total_usd`, `status`, or the conditions themselves) is out of date; a mismatch with the transaction's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; mutations not listed above proceed without an OCC check.

### 2.7. State Propagation: Cascades, Bubble-Ups, and Reverts

The deal pipeline is a set of peer entities — listing, LOI, transaction, escrow deposit, inspection booking, discrepancy item — joined by references rather than nesting, and the system propagates state changes across them automatically. Accepting an LOI cascades to the listing and spawns the transaction and escrow deposit; recording escrow funding bubbles up to the transaction; confirming, completing, or cancelling a booking bubbles the transaction forward or reverts it; resolving findings bubbles the transaction toward delivery; closing cascades to the escrow, the listing, and the comparable-sales ledger; termination cascades to the escrow and the listing. Consistency is immediate: every mutation and all of its cascaded effects are visible within the same request's response, and every resource mutated along the way has its `updated_at` refreshed and its `version` incremented. The exact trigger conditions and per-entity effects of each propagation are specified with the workflows in §3.

### 2.8. Validation Pipeline and Evaluation Order

Every request is validated against a fixed pipeline of checks, evaluated in the following order, and the first failing check determines the error returned:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is declared; failures return `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — the acting role appears in the endpoint's authorized-role list; failures return `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence** — every identifier in the path exists (validated left to right), and every identifier referenced in the request body exists; failures return the appropriate not-found error (HTTP 404).
4. **Request schema** — required body fields are present, types are valid, and enum values are in range; failures return `ERR_VALIDATION` (HTTP 400). A booking window whose `end_at` is not strictly after its `start_at` is rejected here with `ERR_BOOKING_WINDOW_INVALID` (HTTP 422).
5. **State preconditions**, evaluated in three sub-steps: (a) the target resource is in a state that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP 409); (b) the domain state gates — an ACTIVE listing for LOI creation and acceptance (`ERR_LISTING_NOT_ACTIVE`), a FINAL valuation for activation (`ERR_VALUATION_REQUIRED`), an escrow-funded transaction for booking creation (`ERR_TRANSACTION_NOT_FUNDED`), zero findings for as-is acceptance (`ERR_OPEN_DISCREPANCIES`), a not-yet-acknowledged party for disclosure (`ERR_ALREADY_ACKNOWLEDGED`), a proposed credit present for credit agreement (`ERR_CREDIT_NOT_PROPOSED`), and complete logbook and registration conditions for closing (`ERR_DELIVERY_CONDITIONS_INCOMPLETE`) — all HTTP 409; and (c) the OCC version match, failing with `ERR_STALE_VERSION` (HTTP 412).
6. **Business safety** — an AIRWORTHINESS-severity finding may never be waived; failures return `ERR_AIRWORTHINESS_NOT_WAIVABLE` (HTTP 422).
7. **Booking temporal conflicts** — the facility buffer rule is evaluated first (`ERR_FACILITY_SLOT_CONFLICT`, HTTP 409), then the aircraft overlap rule (`ERR_AIRCRAFT_SLOT_CONFLICT`, HTTP 409).
8. **Referential coherence** — a finding's booking must belong to the transaction under which it is raised (`ERR_BOOKING_NOT_FOR_TRANSACTION`, HTTP 422), and a dual-agency LOI must be fully acknowledged before acceptance (`ERR_DUAL_AGENCY_DISCLOSURE_PENDING`, HTTP 409).
9. **Aggregate sufficiency** — a valuation requires at least the minimum count of verified matching comparables; failures return `ERR_INSUFFICIENT_COMPARABLES` (HTTP 422).
10. **Fiscal gates** — at LOI submission, evaluated in order: the buyer must be QUALIFIED (`ERR_BUYER_NOT_QUALIFIED`, HTTP 422), then the offer must fit the buyer's qualified budget (`ERR_BUDGET_EXCEEDED`, HTTP 422), then the deposit must meet the minimum percentage (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422).

### 2.9. Identifier Resolution and Referenced Resources

The entity topology is flat: resources are peers joined by foreign-key references carried in request bodies, and only one creation path in the API is nested (raising a discrepancy item beneath its transaction). Wherever a path carries identifiers, the system validates their existence sequentially from left to right and rejects the request with the not-found error corresponding to the first identifier that does not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`, `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`, or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404. Identifiers referenced from a request body — such as `listing_id`, `buyer_id`, `transaction_id`, `facility_id`, or `inspection_booking_id` — must likewise resolve to existing resources before any business rule is evaluated, surfacing the corresponding not-found error.

## 3. Business Logic & Workflows

### 3.1. Inspection Facilities and Turnaround Buffers

A `BrokerPrincipal` registers each maintenance facility the brokerage works with by supplying a `name` and an `airport_code` identifying where the facility operates, plus an optional `turnaround_buffer_minutes`: the gap the facility requires between consecutive bookings on its schedule. The buffer is a non-negative integer number of minutes and defaults to 120 — two hours — when omitted, reflecting the standard two-hour repositioning and reset window most service centers require. The buffer value feeds directly into the facility slot-conflict rule that governs inspection scheduling in §3.7, so registering a facility with an accurate buffer is what makes downstream booking enforcement meaningful.

### 3.2. Listings, Comparable Sales, and Market Valuation

A `ListingAgent` brings an aircraft to market by creating a listing with its `tail_number`, `make`, `model`, `year`, `total_time_hours` (the airframe's total time in whole hours), its advertised `asking_price_usd`, and the `seller_name` shown to buyers — the seller is a display name only and is never a system user. A new listing starts in `DRAFT` status with `valuation_status` set to `NONE` and `market_value_estimate_usd` null, since no valuation has yet been computed.

Valuations are grounded in recorded comparable sales. A `ListingAgent` records a comparable with the sold airframe's `make`, `model`, `year`, `sale_price_usd`, `sale_date` (an ISO 8601 date, stored for reference and never used to window or filter the valuation input set), and `total_time_hours` at the time of sale, plus an optional `comp_status` of `VERIFIED` or `UNVERIFIED` that defaults to `UNVERIFIED` when omitted. Only `VERIFIED` comparables ever enter a valuation's input set. Manually recorded comparables carry a null `source_listing_id`; the field is populated only when the system itself mints a comparable at a closing, as described in §3.9. Comparable sales can be listed and filtered by `make`, `model`, or `source_listing_id` to support market research.

To value a listing, a `ListingAgent` requests a valuation with a `variant` of either `PROVISIONAL` or `FINAL`. The input set for both variants is the collection of `VERIFIED` comparable sales whose `make` and `model` exactly equal the listing's `make` and `model` — an exact string match, not a fuzzy one. If that set contains fewer than three comparables, the valuation is rejected with `ERR_INSUFFICIENT_COMPARABLES` (HTTP 422); three or more are always required.

The `PROVISIONAL` variant is the broker's quick draft estimate, usable at any time: it takes the plain arithmetic mean of the input set — the comparables' `sale_price_usd` values are summed, the sum is divided by the number of comparables, and the result is rounded half up to two decimal places, with no per-hour adjustment applied.

The `FINAL` variant adjusts each comparable for total-time difference before averaging, and its rounding order is pinned. For each comparable, an adjustment factor is computed as one minus the product of 0.00004 and the signed difference between that comparable's `total_time_hours` and the listing's `total_time_hours`; a comparable with more hours than the listing therefore produces a factor below one and is adjusted downward, while one with fewer hours produces a factor above one and is adjusted upward. Each comparable's adjusted price is its `sale_price_usd` multiplied by its own adjustment factor, and that per-comparable product is rounded half up to two decimal places first, before any aggregation. The valuation is then the sum of those already-rounded adjusted prices divided by the number of comparables, with the final quotient itself rounded half up to two decimal places. Because the per-comparable rounding happens before averaging, the FINAL variant provably diverges from the PROVISIONAL mean on the same input set.

Either run persists its result onto the listing: `market_value_estimate_usd` is set to the computed value, `valuation_status` is set to the requested `variant`, and the listing's `version` increments by one. Activation is gated on valuation rigor: a `ListingAgent` may activate a `DRAFT` listing only when its `valuation_status` is `FINAL`, moving it to `ACTIVE`; attempting activation without a FINAL-variant valuation on record is rejected with `ERR_VALUATION_REQUIRED` (HTTP 409), and a successful activation increments the listing's `version`.

### 3.3. Buyer Registration and Qualification

On the buy side, a `BuyerAgent` registers each purchaser with a `full_name` and a contact `email`. A new buyer starts with `qualification_status` set to `UNQUALIFIED`, and both `qualified_budget_usd` and `proof_of_funds_ref` are null until qualification occurs.

Qualification is the brokerage's financial vetting step: the `BuyerAgent` records the buyer's budget ceiling as `qualified_budget_usd` together with a bank reference in `proof_of_funds_ref`, moving the buyer from `UNQUALIFIED` to `QUALIFIED` and incrementing the buyer's `version`. Only a `QUALIFIED` buyer may be placed on a letter of intent, and the recorded budget ceiling becomes the hard cap enforced against every offer price, as the fiscal gates in §3.4 describe.

### 3.4. Letters of Intent: Submission, Fiscal Gates, and the Counter Loop

Negotiation begins when a `BuyerAgent` submits a letter of intent on behalf of a buyer, carrying the `listing_id` of the aircraft under negotiation, the `buyer_id` of the offering buyer, an `offer_price_usd`, a pledged `deposit_amount_usd` as earnest money, and an optional `dual_agency` flag that defaults to false and is set true when the same brokerage represents both buyer and seller. Submission requires the listing to be `ACTIVE`; an LOI against a listing in any other status is rejected with `ERR_LISTING_NOT_ACTIVE` (HTTP 409).

Three fiscal gates then guard submission, evaluated in this order. First, the referenced buyer must be `QUALIFIED`; submitting for an `UNQUALIFIED` buyer is rejected with `ERR_BUYER_NOT_QUALIFIED` (HTTP 422). Second, the `offer_price_usd` must not exceed the buyer's recorded `qualified_budget_usd`; an offer above the ceiling is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422). Third, the earnest deposit must meet the minimum: five percent of the `offer_price_usd`, computed by multiplying the offer price by 0.05 and rounding the product half up to two decimal places; a `deposit_amount_usd` equal to or greater than that minimum passes — exact equality is acceptable — while anything below it is rejected with `ERR_DEPOSIT_BELOW_MINIMUM` (HTTP 422).

A submitted LOI starts in `SUBMITTED` status, with `current_price_usd` set equal to the initial `offer_price_usd`, both `buyer_acked` and `seller_acked` false, and `disclosure_status` set to `PENDING` when `dual_agency` is true and to `NOT_REQUIRED` otherwise.

From there the price negotiates through a counter loop that either side's agent — `ListingAgent` or `BuyerAgent` — may drive. Each counter supplies a `new_price_usd` and the OCC field `expected_loi_version` described in §2.6. A counter on a `SUBMITTED` LOI moves it to `COUNTERED`, and a counter on a `COUNTERED` LOI moves it back to `SUBMITTED`; in both directions the `current_price_usd` is replaced by the supplied `new_price_usd` and the LOI's `version` increments by one. The alternation lets the parties ping-pong proposals while the version field keeps every writer honest about which price it is responding to. A `BuyerAgent` may instead withdraw a pending LOI — from either `SUBMITTED` or `COUNTERED` — moving it to `WITHDRAWN`. `ACCEPTED`, `REJECTED`, and `WITHDRAWN` are the terminal negotiation states; acceptance and the automatic rejection sweep are covered in §3.6. LOIs can be listed filtered by `listing_id`, `buyer_id`, or `status` so agents can review the negotiation pipeline for an aircraft or a client.

### 3.5. Dual-Agency Disclosure

When `dual_agency` is true, the brokerage represents both sides of the deal and must complete a written disclosure before the LOI can be accepted. The LOI carries a second, parallel state axis for this — its `disclosure_status` — which evolves independently of the negotiation status: it begins at `PENDING` for a dual-agency LOI, moves to `PARTIAL` when the first party acknowledges, and reaches `FULLY_ACKED` when the remaining party acknowledges. (A non-dual-agency LOI sits at `NOT_REQUIRED` and never moves.)

Each acknowledgment is recorded by the `BrokerPrincipal`, who supplies a `party` input selecting the buyer side or the seller side. The first acknowledgment sets `buyer_acked` or `seller_acked` true according to the supplied party and moves `disclosure_status` from `PENDING` to `PARTIAL`; the second acknowledgment sets the remaining flag and advances `disclosure_status` from `PARTIAL` to `FULLY_ACKED`. Each acknowledgment increments the LOI's `version`. Acknowledging a party that has already acknowledged — or attempting an acknowledgment on an LOI whose `dual_agency` is false, where disclosure is not required at all — is rejected with `ERR_ALREADY_ACKNOWLEDGED` (HTTP 409). The payoff of the axis comes at acceptance: accepting a dual-agency LOI whose disclosure has not reached `FULLY_ACKED` is rejected with `ERR_DUAL_AGENCY_DISCLOSURE_PENDING` (HTTP 409), as §3.6 reiterates.

### 3.6. Acceptance: Opening the Transaction and Locking the Listing

Acceptance is the pivot of the whole pipeline and is performed by the `ListingAgent` on an LOI in `SUBMITTED` or `COUNTERED` status. Two preconditions guard it: the listing must be `ACTIVE` — otherwise the acceptance is rejected with `ERR_LISTING_NOT_ACTIVE` — and, when the LOI's `dual_agency` is true, its `disclosure_status` must be `FULLY_ACKED`, otherwise the acceptance is rejected with `ERR_DUAL_AGENCY_DISCLOSURE_PENDING`.

An accepted LOI moves to `ACCEPTED` and opens the deal in a single atomic cascade. A Transaction is created with its `loi_id`, `listing_id`, and `buyer_id` copied from the LOI, its `agreed_price_usd` set to the LOI's `current_price_usd` at the moment of acceptance, and its `dual_agency` flag copied from the LOI — the flag that later selects the commission variant at closing. The transaction starts in `OPENED` status with `logbook_complete` and `registration_docs_complete` both false, `tax_planning_notes` and `termination_reason` null, `credits_total_usd` at 0, and the three closing outputs — `commission_amount_usd`, `settlement_buyer_due_usd`, and `settlement_seller_net_usd` — null until closing computes them. Alongside the transaction, an EscrowDeposit is created one-to-one: its `transaction_id` points at the new transaction, the server generates an `escrow_ref` account reference, `deposit_amount_usd` is copied from the LOI's pledged deposit, and it begins in `AWAITING_FUNDS` status with `funding_reference` null and `released_usd`, `refunded_usd`, and `forfeited_usd` all at 0.

Acceptance simultaneously locks the aircraft: the listing cascades from `ACTIVE` to `UNDER_CONTRACT`, and the same cascade runs the auto-reject sweep — every other LOI on that listing still sitting in `SUBMITTED` or `COUNTERED` is moved to `REJECTED`, ending those negotiations deterministically.

### 3.7. Escrow Funding and Pre-Buy Inspection Scheduling

With the deal opened, the `EscrowOfficer` records receipt of the buyer's wire by funding the escrow deposit with its `funding_reference`. The deposit moves from `AWAITING_FUNDS` to `FUNDED`, its `version` increments, and the transaction bubbles up from `OPENED` to `ESCROW_FUNDED` in the same request — the funding event is what arms the deal for inspection.

Only an escrow-funded aircraft may be scheduled: a `FacilityScheduler` books an inspection slot by supplying the `transaction_id` the inspection serves, the `facility_id` where it will happen, and a `start_at` and `end_at` window in ISO 8601 UTC. If the transaction is not in `ESCROW_FUNDED` status, the booking is rejected with `ERR_TRANSACTION_NOT_FUNDED` (HTTP 409). The window itself must be well-formed — an `end_at` that is not strictly after `start_at` is rejected with `ERR_BOOKING_WINDOW_INVALID` (HTTP 422) — and it must survive two conflict checks, evaluated facility first and aircraft second. The facility buffer rule rejects the booking with `ERR_FACILITY_SLOT_CONFLICT` (HTTP 409) when any other booking in `REQUESTED` or `CONFIRMED` status at the same facility has a window that — expanded by that facility's `turnaround_buffer_minutes` — intersects the requested half-open window from `start_at` up to but not including `end_at`. The aircraft rule then rejects the booking with `ERR_AIRCRAFT_SLOT_CONFLICT` (HTTP 409) when any other `REQUESTED` or `CONFIRMED` booking for the same transaction's listing strictly overlaps the requested window; because windows are half-open, adjacency — one booking's `end_at` exactly equal to another's `start_at` — does not count as an overlap and is allowed.

A new booking starts in `REQUESTED` status. The facility confirms a requested slot, moving it from `REQUESTED` to `CONFIRMED`, provided the transaction is in `ESCROW_FUNDED` or `INSPECTION_SCHEDULED`; when the transaction was still `ESCROW_FUNDED`, the confirmation bubbles it up to `INSPECTION_SCHEDULED`. Completing a confirmed slot moves it from `CONFIRMED` to `COMPLETED`, requires the transaction to be in `INSPECTION_SCHEDULED`, and bubbles the transaction up to `INSPECTION_COMPLETE` — but only when no other booking of the same transaction remains in `REQUESTED` or `CONFIRMED`. Cancelling moves a `REQUESTED` or `CONFIRMED` booking to `CANCELLED`, and when the transaction is `INSPECTION_SCHEDULED` and no other booking of the transaction remains in `REQUESTED` or `CONFIRMED`, the cancellation reverts the transaction back to `ESCROW_FUNDED`, reopening the scheduling step. `COMPLETED` and `CANCELLED` are the booking's terminal states. Bookings can be listed filtered by `transaction_id`, `facility_id`, or `status`.

### 3.8. Discrepancy Findings, Credits, and Resolution

The pre-buy inspection produces findings, and the `FacilityScheduler` raises each one as a discrepancy item beneath the transaction, supplying the `inspection_booking_id` of the booking whose inspection surfaced it, a `description`, a `severity` of `AIRWORTHINESS` or `NON_AIRWORTHINESS`, and the facility's `estimated_cost_usd` to rectify — a non-negative two-decimal amount. The referenced booking must belong to the transaction under which the finding is raised; a booking from a different transaction is rejected with `ERR_BOOKING_NOT_FOR_TRANSACTION` (HTTP 422). Each finding starts in `RAISED` status with `proposed_credit_usd`, `credit_amount_usd`, and `resolution` all null. The very first finding raised on a transaction moves it from `INSPECTION_COMPLETE` to `DISCREPANCY_NEGOTIATION`, formally opening the airworthiness-and-cosmetic negotiation phase.

The seller side answers each raised finding through the `ListingAgent`. Countering moves the item from `RAISED` to `COUNTERED` and may optionally carry a `proposed_credit_usd` — the seller's counter-proposed price reduction — and a free-text `repair_offer_note`. Alternatively, the seller may commit to repair the finding before delivery: committing moves the item from `RAISED` or `COUNTERED` to `RESOLVED` with its `resolution` recorded as `REPAIR`.

The buyer side answers through the `BuyerAgent`. Agreeing to the seller's credit moves a `COUNTERED` item to `RESOLVED` with `resolution` recorded as `CREDIT` and `credit_amount_usd` set to the previously proposed `proposed_credit_usd`; attempting it when no credit was proposed — when `proposed_credit_usd` is still null — is rejected with `ERR_CREDIT_NOT_PROPOSED` (HTTP 409). Waiving moves a `RAISED` or `COUNTERED` item to `RESOLVED` with `resolution` recorded as `WAIVED`, but only for `NON_AIRWORTHINESS` findings: an airworthiness item may never be waived, and the attempt is rejected with `ERR_AIRWORTHINESS_NOT_WAIVABLE` (HTTP 422). `RESOLVED` is the finding's terminal state.

Every resolution recomputes the transaction's `credits_total_usd`, which is the sum of `credit_amount_usd` over the transaction's resolved items whose `resolution` is `CREDIT` — repairs and waivers contribute nothing. And when a resolution leaves every item of the transaction in `RESOLVED`, the transaction bubbles up from `DISCREPANCY_NEGOTIATION` to `DELIVERY_PENDING` with the recomputed credits in place. Findings can be listed filtered by `transaction_id`, `inspection_booking_id`, or `status`.

### 3.9. Delivery Conditions, Closing Settlement, and Termination

As the deal approaches delivery, the `BrokerPrincipal` maintains the delivery-condition checklist, which may be updated in any non-terminal transaction state. Each update may set any of `logbook_complete` (complete logbooks verified), `registration_docs_complete` (import/export and registration-change documents complete), and `tax_planning_notes` (closing and tax-planning coordination notes), and must carry the `expected_transaction_version` OCC field from §2.6; each applied update increments the transaction's `version`. A buyer who is satisfied with a clean inspection may instead short-circuit the discrepancy phase entirely: accepting the aircraft as-is, by the `BuyerAgent`, moves the transaction from `INSPECTION_COMPLETE` to `DELIVERY_PENDING`, but only while zero discrepancy items exist for the transaction — otherwise it is rejected with `ERR_OPEN_DISCREPANCIES` (HTTP 409). Per §3.8 the first finding moves the transaction into `DISCREPANCY_NEGOTIATION`, so the zero-findings gate is what an as-is attempt meets in that state: an attempt on a `DISCREPANCY_NEGOTIATION` transaction is rejected with `ERR_OPEN_DISCREPANCIES`, not `ERR_INVALID_STATE`. An as-is attempt from any other state besides `INSPECTION_COMPLETE` and `DISCREPANCY_NEGOTIATION` — including a terminal state — is rejected with `ERR_INVALID_STATE`; a successful as-is acceptance increments the transaction's `version`.

Closing, performed by the `BrokerPrincipal` on a `DELIVERY_PENDING` transaction, is the fiscal climax. It requires both `logbook_complete` and `registration_docs_complete` to be true; closing with either condition unmet is rejected with `ERR_DELIVERY_CONDITIONS_INCOMPLETE` (HTTP 409). Closing runs two calculations in a pinned order — commission first, then settlement — and persists their outputs. The commission base is the transaction's `agreed_price_usd` minus its `credits_total_usd`. The tiered sole-agency amount applies a rate of six percent to the portion of the base up to five million US dollars and a rate of four percent to any portion of the base above five million; both tier components are computed at full precision, summed, and the tiered total is rounded half up to two decimal places. When the transaction's `dual_agency` is false, `commission_amount_usd` is that tiered total. When `dual_agency` is true — both sides represented by this brokerage — a buyer-side fee of two percent of the entire base is added on top of the tiered amount, and the combined figure is rounded half up to two decimal places; the dual-agency variant therefore diverges from sole agency on an identical price and credits. Settlement then follows: `settlement_buyer_due_usd` is the `agreed_price_usd` minus the `credits_total_usd` minus the escrow's `deposit_amount_usd`, and `settlement_seller_net_usd` is the `agreed_price_usd` minus the just-computed `commission_amount_usd`.

A successful closing cascades outward. The escrow deposit moves from `FUNDED` to `RELEASED` with `released_usd` set to the full `deposit_amount_usd` disbursed to the seller. The listing moves from `UNDER_CONTRACT` to `SOLD`, its terminal state, and the same cascade mints a market comparable from the closing: a new `VERIFIED` comparable sale whose `make`, `model`, `year`, and `total_time_hours` are copied from the listing, whose `sale_price_usd` is the transaction's `agreed_price_usd`, whose `sale_date` is the closing request's date, and whose `source_listing_id` is the sold listing's id — feeding tomorrow's valuations with today's evidence. The transaction itself moves to `CLOSED`, terminal, with its `version` incremented by the closing.

Not every deal survives. The `BrokerPrincipal` or the `ListingAgent` may terminate an open transaction, recording the supplied `reason` in `termination_reason`, and the escrow's disposition depends on how far the deal had progressed. Termination from `OPENED`, `ESCROW_FUNDED`, `INSPECTION_SCHEDULED`, `INSPECTION_COMPLETE`, or `DISCREPANCY_NEGOTIATION` refunds the buyer: a `FUNDED` escrow moves to `REFUNDED` with `refunded_usd` set to the full `deposit_amount_usd` (terminating from `OPENED` may find the escrow still `AWAITING_FUNDS`, in which case no escrow transition occurs at all). Termination from `DELIVERY_PENDING` forfeits the deposit to the seller: the escrow moves from `FUNDED` to `FORFEITED` with `forfeited_usd` set to the full `deposit_amount_usd`. In every termination the listing cascades from `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the transaction's `version` increments. `CLOSED` and `TERMINATED` are the transaction's terminal states; any further transition attempt on a terminal resource is rejected with `ERR_INVALID_STATE`.

Throughout its life the escrow deposit obeys a strict reconciliation invariant, evaluated on every transition — funding, release, refund, forfeiture — and on every read: the sum of `released_usd`, `refunded_usd`, and `forfeited_usd` equals exactly the `deposit_amount_usd` when the escrow is terminal (`RELEASED`, `REFUNDED`, or `FORFEITED`) and exactly zero while it is non-terminal. A terminal escrow disposes of precisely the deposited amount through precisely one channel, and a forward funding followed by a compensating refund leaves the buyer's net funds unchanged. Escrow deposits can be listed filtered by `transaction_id`, and transactions can be listed filtered by `loi_id`, `listing_id`, `buyer_id`, or `status` for pipeline review.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, condition updates, valuation runs, acknowledgments — and all retrieval operations return `200 OK`. Request bodies, computed fields, and cascaded effects for each endpoint are specified in §2 and §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/inspection-facilities` | Register an inspection facility (MRO) | BrokerPrincipal |
| POST | `/api/listings` | Create an aircraft listing (starts DRAFT) | ListingAgent |
| GET | `/api/listings/{id}` | Get listing details | All roles |
| POST | `/api/listings/{id}/valuation` | Run market-comparables valuation with the requested variant | ListingAgent |
| POST | `/api/listings/{id}/activate` | Activate a DRAFT listing (requires FINAL valuation) | ListingAgent |
| POST | `/api/buyers` | Register a buyer (starts UNQUALIFIED) | BuyerAgent |
| POST | `/api/buyers/{id}/qualify` | Qualify a buyer with budget ceiling and proof-of-funds reference | BuyerAgent |
| POST | `/api/comparable-sales` | Record a market comparable sale | ListingAgent |
| GET | `/api/comparable-sales` | List comparable sales, optionally filtered (supports limit/offset pagination) | All roles |
| GET | `/api/comparable-sales/{id}` | Get one comparable sale | All roles |
| POST | `/api/lois` | Submit a letter of intent for an ACTIVE listing on behalf of a QUALIFIED buyer | BuyerAgent |
| GET | `/api/lois` | List LOIs with filters (supports limit/offset pagination) | All roles |
| GET | `/api/lois/{id}` | Get one LOI | All roles |
| POST | `/api/lois/{id}/counter` | Counter the in-force price; alternates SUBMITTED ↔ COUNTERED; OCC-guarded | ListingAgent, BuyerAgent |
| POST | `/api/lois/{id}/accept` | Accept an LOI; opens Transaction + EscrowDeposit and locks the listing | ListingAgent |
| POST | `/api/lois/{id}/withdraw` | Buyer withdraws a pending LOI | BuyerAgent |
| POST | `/api/lois/{id}/disclosure/ack` | Record one party's dual-agency disclosure acknowledgment | BrokerPrincipal |
| GET | `/api/transactions` | List transactions with filters (supports limit/offset pagination) | All roles |
| GET | `/api/transactions/{id}` | Get one transaction | All roles |
| PATCH | `/api/transactions/{id}/delivery-conditions` | Update delivery-condition checklist (logbooks, registration docs, tax notes); OCC-guarded; any non-terminal state | BrokerPrincipal |
| POST | `/api/transactions/{id}/accept-as-is` | Buyer accepts the aircraft with zero findings (INSPECTION_COMPLETE → DELIVERY_PENDING) | BuyerAgent |
| POST | `/api/transactions/{id}/terminate` | Terminate an open deal; escrow refunded before DELIVERY_PENDING, forfeited at DELIVERY_PENDING | BrokerPrincipal, ListingAgent |
| POST | `/api/transactions/{id}/close` | Close the deal: computes commission + settlement, releases escrow, sells listing, records comparable | BrokerPrincipal |
| GET | `/api/escrow-deposits` | List escrow deposits with filters | All roles |
| GET | `/api/escrow-deposits/{id}` | Get one escrow deposit | All roles |
| POST | `/api/escrow-deposits/{id}/fund` | Record receipt of the deposit wire | EscrowOfficer |
| POST | `/api/inspection-bookings` | Book an inspection slot for a funded transaction at a facility | FacilityScheduler |
| GET | `/api/inspection-bookings` | List inspection bookings with filters | All roles |
| GET | `/api/inspection-bookings/{id}` | Get one inspection booking | All roles |
| POST | `/api/inspection-bookings/{id}/confirm` | Facility confirms a requested slot | FacilityScheduler |
| POST | `/api/inspection-bookings/{id}/complete` | Facility marks the inspection done | FacilityScheduler |
| POST | `/api/inspection-bookings/{id}/cancel` | Cancel a requested/confirmed slot | FacilityScheduler |
| POST | `/api/transactions/{id}/discrepancy-items` | Raise a pre-buy inspection finding on a transaction | FacilityScheduler |
| GET | `/api/discrepancy-items` | List discrepancy items with filters | All roles |
| GET | `/api/discrepancy-items/{id}` | Get one discrepancy item | All roles |
| POST | `/api/discrepancy-items/{id}/counter` | Seller counters a raised finding, optionally proposing a price credit | ListingAgent |
| POST | `/api/discrepancy-items/{id}/commit-repair` | Seller commits to repair the finding before delivery | ListingAgent |
| POST | `/api/discrepancy-items/{id}/agree-credit` | Buyer accepts the seller's proposed price credit | BuyerAgent |
| POST | `/api/discrepancy-items/{id}/waive` | Buyer waives a non-airworthiness finding | BuyerAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_BUYER_NOT_FOUND` | 404 Not Found |
| `ERR_COMPARABLE_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_LOI_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_ESCROW_DEPOSIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_DISCREPANCY_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LISTING_NOT_ACTIVE` | 409 Conflict |
| `ERR_VALUATION_REQUIRED` | 409 Conflict |
| `ERR_TRANSACTION_NOT_FUNDED` | 409 Conflict |
| `ERR_OPEN_DISCREPANCIES` | 409 Conflict |
| `ERR_ALREADY_ACKNOWLEDGED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AIRWORTHINESS_NOT_WAIVABLE` | 422 Unprocessable Entity |
| `ERR_FACILITY_SLOT_CONFLICT` | 409 Conflict |
| `ERR_AIRCRAFT_SLOT_CONFLICT` | 409 Conflict |
| `ERR_BOOKING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_BOOKING_NOT_FOR_TRANSACTION` | 422 Unprocessable Entity |
| `ERR_DUAL_AGENCY_DISCLOSURE_PENDING` | 409 Conflict |
| `ERR_INSUFFICIENT_COMPARABLES` | 422 Unprocessable Entity |
| `ERR_CREDIT_NOT_PROPOSED` | 409 Conflict |
| `ERR_BUYER_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DELIVERY_CONDITIONS_INCOMPLETE` | 409 Conflict |
