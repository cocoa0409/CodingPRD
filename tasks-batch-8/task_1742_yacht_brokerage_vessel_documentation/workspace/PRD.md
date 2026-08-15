# Yacht Brokerage API — Product Requirements Document

## 1. Introduction

A yacht brokerage desk lives or dies on paperwork discipline. Between the moment a seller signs a central listing agreement and the moment title transfers, a single deal touches MLS syndication feeds, buyer offers carrying survey and sea-trial contingencies, earnest-money escrow with hard acceptance deadlines, lien searches and payoffs, federal Coast Guard documentation or state titling, multi-state sales and use tax with offshore-delivery exemptions, and a closing statement on which several independently compensated parties rely. When any one of those artifacts is wrong — a stale price pushed to a listing portal, a deposit released before the statement is approved, a preferred ship mortgage overlooked in the payoff waterfall — the desk absorbs real financial and legal exposure.

This document specifies the API that backs such a desk, in the style of a YachtWorld central-agency operation. The service governs the full deal arc: brokerage and agent onboarding, vessel registration with its documentation mode, listing agreements and their syndication lifecycle, a cyclic offer negotiation with counter-offer chains, contingency management with a fixed cure window, trust-account escrow under segregation of duties, and a pinned-order closing calculation pipeline that produces the settlement figures, the tax assessments, and the title transfer. Because multiple roles act on the same deal at different times — listing side, selling side, escrow desk, closing desk — optimistic concurrency control, a strictly ordered validation pipeline, and an append-only audit trail are treated as first-class requirements rather than afterthoughts.

The API is mounted under `/yacht` and is consumed by back-office operators and licensed agents alike. Section 2 defines the system-wide contracts every endpoint honors; Section 3 walks the business workflows in deal order and carries the fine-grained rules; Sections 4 and 5 consolidate the endpoint and error references.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-identified caller whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist, spelled exactly as follows:

- **PlatformAdmin** — back-office operator. Registers brokerages and agents, onboards clients and vessels, drives the logical clock, reads every resource, and is the sole consumer of the audit-event query. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on audit events) but never compares it to an entity `id`.
- **ListingAgent** — the seller-side broker agent: owns listing agreements and their lifecycle, accepts, rejects, and counters offers, renegotiates cures on objected contingencies, approves closing statements, records and releases liens, files documentation records, and forfeits deposits on buyer default. When `X-User-Role` is `ListingAgent`, `X-User-ID` is the `id` of the acting `BrokerAgent`; ownership checks on any resource that references a `BrokerAgent` compare the resource's foreign-key field to `X-User-ID`.
- **SellingAgent** — the buyer-side broker agent: submits offers, counters back on countered offers, withdraws its own offers, drives contingency outcomes, and collapses an accepted offer when an objection goes unresolved. When `X-User-Role` is `SellingAgent`, `X-User-ID` is likewise the `id` of the acting `BrokerAgent`, and ownership checks — most notably the withdrawal rule, which demands that the acting agent match the offer's `selling_agent_id` — compare resource foreign keys against it.
- **ClosingOfficer** — the settlement officer: drafts, builds, reopens, voids, and disburses closing statements, drafts and executes title transfers, and releases cleared escrow into the closing. When `X-User-Role` is `ClosingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it may be recorded on audit events but is never compared to an entity `id`.
- **EscrowOfficer** — the trust-account operator: records escrow entries, marks deposits cleared, voids uncashed entries, and refunds cleared funds to buyers. When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it may be recorded on audit events but is never compared to an entity `id`.

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

List endpoints paginate through two query parameters: `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0. Every list response sorts by `created_at` ascending, and the `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a caller can always tell how many records exist in total and whether another page follows.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is identified by an `id` — a server-minted UUID with no type prefix — and carries `created_at` and `updated_at` timestamps rendered as ISO 8601 UTC strings with three fractional digits. Resources additionally carry a `version`: an integer that increments by exactly one on every mutation of that resource, with `updated_at` refreshed at the same instant. Two resource kinds are deliberately leaner: a `SyndicationEvent` and a `DomainEvent` each carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because both are append-only records that never mutate after creation.

Nested URLs are resolved strictly left to right. When a path names a vessel and then a lien beneath it, the vessel is validated first and the lien second; the first path segment that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404) before any deeper segment is examined. Foreign keys named in a request body — a `listing_id`, `buyer_id`, `selling_agent_id`, `vessel_id`, or similar — are likewise resolved after the path and rejected with `ERR_NOT_FOUND` when they point at nothing.

### 2.5. The Logical Clock and Automated Expiry Sweeps

The service keeps a logical clock rather than reading wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and until an operator advances it the clock never falls back to real time. A PlatformAdmin-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Advancing the clock is not a passive read: each advance runs the automated expiry sweeps — listing expiry at `end_date`, offer expiry past `acceptance_deadline`, and contingency expiry past `deadline` or past the objection cure window — so the state of the book after a clock move always reflects every deadline that the new instant has crossed.

### 2.6. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control, and each names the expected version as a non-optional input field:

- Accepting an offer requires `expected_offer_version` carrying the caller's last-observed `version` of that offer.
- Countering an offer likewise requires `expected_offer_version` against the offer being countered.
- Building a closing statement requires `expected_offer_version` against the accepted offer whose figures the statement pins.
- Approving a closing statement requires `expected_statement_version` against the statement itself.

When the supplied value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A stale acceptance must not silently bind a round the caller has not observed; a stale approval must not bless figures that a reopen has since recomputed; a stale build must not pin a superseded offer snapshot. Endpoints not listed here take no version field at all.

### 2.7. Monetary Representation, Precision, and Rounding

All money is integer cents — prices, deposits, commissions, taxes, fees, lien amounts, and settlement totals alike. Whenever a calculation produces a fractional cent, the result is rounded half-up to whole cents, and the rounding happens at the labelled step the rule assigns it to, never later and never earlier. Several calculations are sensitive to step order: the gross commission is rounded before it is split between sides, the proration per-day figure is rounded before it is multiplied by days, and escrow interest is rounded per ledger entry before entries are summed. Two rounding policies, `PER_LINE_THEN_SUM` and `SUM_THEN_PER_LINE`, are electable on a closing statement and are pinned once the statement is built and immutable thereafter.

### 2.8. Validation Pipeline and Error Ordering

Every request passes through a fixed pipeline of checks, and the order is observable contract. Identity headers are examined first (`ERR_UNAUTHENTICATED`), then the role's permission on the endpoint (`ERR_FORBIDDEN`), then path-referenced resources resolved left to right (`ERR_NOT_FOUND`), then body-referenced foreign keys (`ERR_NOT_FOUND`). Only after existence is settled does the server ask whether the target resource's current state permits the requested transition, rejecting with `ERR_INVALID_STATE` (HTTP 409), and only after that does it perform the optimistic-concurrency comparison of §2.6, rejecting a mismatch with `ERR_STALE_VERSION` (HTTP 412).

The business-rule band then runs in its pinned relative order, which matters wherever several rules guard the same operation. On escrow deposit recording, the anti-structuring ceiling is evaluated before the sufficiency floor, so an out-of-band deposit surfaces `ERR_DEPOSIT_EXCESSIVE` rather than `ERR_DEPOSIT_INSUFFICIENT` when both could plausibly be argued. On closing-statement approval, the stale-version check precedes the segregation-of-duties check, so a caller holding an old version hears `ERR_STALE_VERSION` before any `ERR_SEGREGATION_VIOLATION` question is asked. On vessel intake, the hull-number uniqueness check precedes documentation coherence, so a duplicate `hin` answers `ERR_DUPLICATE_RESOURCE` (HTTP 409) before any `ERR_DOC_MODE_MISMATCH` analysis. On offer submission, the deadline sanity check precedes the listing-acceptance check, so a backdated `acceptance_deadline` answers `ERR_INVALID_DEADLINE` before the listing's status is considered. Request-shape validation runs last of all: a missing required field, an enum value outside its declared membership, or a field of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and unknown fields in a payload are ignored rather than rejected.

### 2.9. Segregation of Duties and the Audit Trail

Two walls run through the deal arc. On the closing statement, the desk that builds is not the desk that approves: building is ClosingOfficer work, approval is ListingAgent work, and an approval attempted by the same role that built the statement is rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403). On the trust account, recording, clearing, voiding, and refunding belong to the EscrowOfficer, releasing funds into a closing belongs to the ClosingOfficer, and forfeiting a deposit to the seller belongs to the ListingAgent — three roles deliberately split so no single operator can both hold and direct the money.

Every meaningful mutation appends a `DomainEvent` to an append-only audit log queryable by PlatformAdmin. Each event records `aggregate_type` (the entity name of the mutated aggregate), `aggregate_id` (its `id`), `event_type` (the transition or calculation name, such as OFFER_COUNTERED or CLOSING_BALANCED), `actor_role` (the `X-User-Role` of the mutating call), `actor_id` (its `X-User-ID`), and a `payload` snapshot of the before-and-after fields relevant to the event. The log can be filtered by `aggregate_type` and `aggregate_id`. Named events raised along the deal arc include BROKERAGE_REGISTERED at brokerage registration, LISTING_ACTIVATED and LISTING_SUSPENDED on the listing lifecycle, LISTING_REACTIVATED when a collapsed deal kicks the listing back to market, and OFFER_COUNTERED on each round of the counter chain.

## 3. Business Logic & Workflows

### 3.1. Desk Onboarding: Brokerages, Agents, and Clients

Before a deal can exist, the desk itself must be registered. A PlatformAdmin registers each brokerage house with its `legal_name`, the `home_state_code` of its principal office — one of FL, CA, WA, NY, TX, RI, MD, NC, SC, MA, GA, or NJ, a choice that drives the default use-tax table — the `escrow_account_ref` of its trust account at the bank, its state-issued yacht-and-ship broker `license_no`, and optionally a `default_commission_tier_code` that defaults to STANDARD when omitted and otherwise names PREMIER or BOUTIQUE. Registration appends a BROKERAGE_REGISTERED event to the audit log.

Agents are then onboarded under a house by a PlatformAdmin, each record carrying the employing `brokerage_id`, the agent's `full_name`, an individual salesperson `license_no`, and a `split_pct_basis` — the agent's personal share of the house-side commission expressed in basis points, at least 0 and at most 9000, with the remainder retained by the house. An agent arrives in status ACTIVE; moving an agent to SUSPENDED blocks that agent from activating listings and from being named on new listings and new offers until reinstated.

Clients of the desk are registered by a PlatformAdmin, a ListingAgent, or a SellingAgent. Each client record declares a `kind` — SELLER, BUYER, or BOTH — plus the `full_name` exactly as it should appear on closing instruments, a `residency_state_code` drawn from the twelve supported states or the value NON_US (residency drives the use-tax credit lookup at closing), the `tax_id_last4` used for 8300 and finCEN cross-checks, and an `is_entity_buyer` flag, defaulting to false, that marks LLC and corporate buyers and affects the signatory rules applied to the warranty of title at closing.

### 3.2. Vessel Registration, Documentation, and Lien Search

A PlatformAdmin or ListingAgent registers each vessel with its `hin` — a Hull Identification Number of exactly twelve uppercase alphanumeric characters, globally unique across every vessel the desk has ever registered, so a duplicate submission is rejected with `ERR_DUPLICATE_RESOURCE` — plus the builder's `make`, the `model` designation, the `year_built` (which may not be later than the current clock year), the `length_overall_ft`, and the `current_location_state_code` recording where the vessel physically lies. Length matters beyond description: vessels measuring at least 26.0 feet meet the net-tonnage proxy that drives eligibility for federal documentation.

Every vessel declares a `documentation_mode` of USCG or STATE, and the paperwork must cohere with that election on both registration and later update. A USCG vessel must carry its `uscg_official_no` — a six-to-seven-digit string — and must not carry a state title number in its place; a STATE vessel must carry its `state_title_no`, while on a documented vessel that field serves only as an optional decal reference. A submission whose numbers contradict its mode is rejected with `ERR_DOC_MODE_MISMATCH` (HTTP 422). Descriptive upkeep — `make`, `model`, `current_location_state_code`, `state_title_no`, `uscg_official_no` — may be corrected later by a PlatformAdmin or ListingAgent, each correction bumping the vessel's `version`. A freshly registered vessel starts with `liens_status` CLEAN.

Against each vessel the desk files documentation instruments: a `record_kind` of USCG_COD for the Certificate of Documentation, STATE_TITLE for a state certificate of title, or ABSTRACT for a USCG abstract-of-title search, each with its `instrument_no` and `issue_date`. Records arrive VALID; filing a newer record of the same kind on the same vessel supersedes the prior one, flipping it to SUPERSEDED, and a successful closing eventually flips the operative record to TRANSFERRED (REVOKED marks an instrument withdrawn from reliance). An ABSTRACT is trustworthy only when fresh: its `issue_date` must fall within thirty days of the closing to support one.

The lien search is recorded on the vessel by a ListingAgent or ClosingOfficer. Each discovered encumbrance is filed with the `lienholder_name`, an `instrument_type` — PREFERRED_MORTGAGE for a USCG preferred ship mortgage, UCC1 for a state UCC filing, or MECHANIC for a yard or mechanic's lien — the face `amount_cents`, and a `priority_rank` where 1 is paid first and ties break by the lien's `created_at` ascending. Two disciplines apply: a PREFERRED_MORTGAGE may only be recorded on a USCG-documented vessel, and filing one against a state-titled boat is rejected with `ERR_LIEN_INSTRUMENT_MISMATCH` (HTTP 422); and a preferred mortgage must outrank every non-mortgage lien in the ordering. Recording any lien flips the vessel's `liens_status` from CLEAN to ENCUMBERED and bumps the vessel's `version`. Each lien starts RECORDED with `payoff_amount_cents` at zero until the closing waterfall computes it; a lienholder who files a release without payment lets a ListingAgent or ClosingOfficer mark the lien RELEASED by supplying a non-empty `release_ref`, and whenever the last open encumbrance clears — by release or by full satisfaction — the vessel's `liens_status` is recomputed to CLEAN.

### 3.3. Listing Agreements and MLS Syndication

A ListingAgent drafts a listing agreement by naming the listing-side `brokerage_id`, the `listing_agent_id` (who must belong to that brokerage), the `seller_id` (whose client `kind` must include SELLER), and the `vessel_id`, then the commercial terms: an `agreement_type` of CENTRAL for an exclusive central agency with sole selling rights or OPEN for a non-exclusive arrangement, the asking `list_price_cents` (this desk carries a USD 1,000,000 floor, so the price must be at least 100000000 cents), the `start_date` and `end_date` of the mandate, an optional `commission_tier_code` of STANDARD, PREMIER, or BOUTIQUE that overrides the brokerage default when present, and an optional `protection_period_days` — the post-expiry window, defaulting to 90 days and never outside 0 to 180, during which previously introduced buyers still earn the desk its commission. The `end_date` must sit strictly after `start_date`; a mandate that fails this is rejected with `ERR_INVALID_DEADLINE` (HTTP 422). A vessel may carry only one non-terminal listing at a time, so drafting a second agreement while one stands in DRAFT, ACTIVE, SUSPENDED, or UNDER_CONTRACT is rejected with `ERR_DUPLICATE_RESOURCE`. New agreements begin life in DRAFT, and the listing collection can be browsed filtered by `status`, `vessel_id`, `seller_id`, `brokerage_id`, or `listing_agent_id`.

Activation moves a listing from DRAFT to ACTIVE — and later, from SUSPENDED back to ACTIVE — but only when the acting agent's brokerage matches the listing's `brokerage_id`, the agent is ACTIVE, the seller's kind includes SELLER, no other agreement on the same vessel stands in DRAFT, ACTIVE, SUSPENDED, or UNDER_CONTRACT, and the clock has not yet reached `end_date`. Activation bumps the listing's `version` and raises a LISTING_ACTIVATED event; suspension from ACTIVE to SUSPENDED raises LISTING_SUSPENDED and stops new offers; reactivation from SUSPENDED again requires the clock to precede `end_date`. A seller walking away lets the agent cancel from ACTIVE or SUSPENDED, provided no offer on the listing stands ACCEPTED: the listing becomes CANCELLED, its `syndication_status` flips to WITHDRAWN, and every offer on it still PENDING or COUNTERED is swept to EXPIRED. When the clock reaches `end_date`, the sweep expires an ACTIVE or SUSPENDED listing to EXPIRED with the same WITHDRAWN and offer-expiry cascades. CLOSED, EXPIRED, and CANCELLED are terminal.

Syndication tracks whether the outside world sees the current price. A new listing's `syndication_status` is NOT_SENT. Pushing the listing to a `channel` — YACHTWORLD, BOATS_COM, BOATTRADER, or DENISON_MLS — records a `SyndicationEvent` whose `payload_price_cents` must equal the listing's current `list_price_cents` and whose listing must be ACTIVE; a push at any other price or on a non-active listing is rejected with `ERR_SYNDICATION_STALE_PRICE` (HTTP 422). Each event captures the channel's acknowledgement as an `outcome` of ACKED or REJECTED and stamps `sent_at` from the server clock; an ACKED outcome moves the listing's `syndication_status` to SYNDICATED, while a REJECTED outcome is recorded without advancing it. When the seller re-prices the boat, the agent's price-change action writes the new `list_price_cents`, flips `syndication_status` to STALE until a fresh push goes out, and bumps the listing's `version`.

### 3.4. Offer Submission and the Counter-Offer Chain

A SellingAgent submits a buyer's offer with the `listing_id` it targets, the `buyer_id` (whose `kind` must include BUYER), the `selling_agent_id` representing the buyer (who may hail from a different brokerage than the listing side), the `offer_price_cents` (which must be greater than zero), the `deposit_pct_basis` earnest-money election in basis points of the offer price — at least 1000, a ten-percent floor, and at most 10000 — the `acceptance_deadline` by which the seller must respond, the `settlement_state_code` naming the closing state that drives tax situs unless offshore delivery is elected, an optional `offshore_delivery` flag defaulting to false, and an optional `parent_offer_id` when the offer continues an existing negotiation chain. The `acceptance_deadline` must lie strictly in the future at submission, failing which the offer is rejected with `ERR_INVALID_DEADLINE`; the listing must be ACTIVE, or UNDER_CONTRACT under the kick-out rule, failing which the offer is rejected with `ERR_LISTING_NOT_ACCEPTING` (HTTP 409). A fresh offer arrives PENDING with `round_no` 1 — or one more than its parent's round when `parent_offer_id` is set — and the offers collection can be browsed filtered by `listing_id`, `buyer_id`, `selling_agent_id`, `parent_offer_id`, or `status`.

While an offer stands PENDING and the clock has not passed its `acceptance_deadline`, the listing side answers in one of three ways, each closed off with `ERR_DEADLINE_PASSED` (HTTP 422) once the deadline slips by. Rejection moves the offer to REJECTED. Acceptance — guarded by the OCC field `expected_offer_version` — moves the offer to ACCEPTED and, in the same breath, the listing from ACTIVE to UNDER_CONTRACT; acceptance also requires the vessel's encumbrance picture to be resolvable, so on an ENCUMBERED vessel acceptance stands only when a lien payoff plan can be computed. Acceptance is what creates the deal's contingencies: SURVEY and SEA_TRIAL arrive with a `deadline` ten days out from the clock, DOCUMENTATION twenty-one days out, and FINANCING only when the offer's payload requested one. Countering — the ListingAgent's third answer — flips the original offer to COUNTERED, bumps its `version`, mints a child offer in PENDING whose `parent_offer_id` links back to the original and whose `round_no` is one higher, and raises an OFFER_COUNTERED event; the counter payload carries `expected_offer_version` along with the revised `offer_price_cents`, `deposit_pct_basis`, and `acceptance_deadline`. The chain is cyclic: the buyer's side answers a counter by countering the child in turn, flipping that child from COUNTERED and minting a grandchild in PENDING at the next round, and so on until someone accepts, rejects, or walks.

The buyer side retains its own exits. Withdrawal moves a PENDING offer to WITHDRAWN, but only when the acting SellingAgent's identity matches the offer's `selling_agent_id` — no agent may withdraw another desk's offer. Independently, the clock sweep expires any offer still PENDING or COUNTERED once the clock passes its `acceptance_deadline`, and a listing's expiry or cancellation sweeps every such open offer on it to EXPIRED in the same motion. REJECTED, EXPIRED, WITHDRAWN, CLOSED, and FAILED are the offer's terminal states.

### 3.5. Contingencies and the Cure Window

Contingencies attach to the accepted offer, each with a `kind` of SURVEY, SEA_TRIAL, FINANCING, or DOCUMENTATION, a `deadline`, and a lifecycle that starts at OPEN. The buyer's side drives each one: marking it satisfied moves it to SATISFIED, waiving moves it to WAIVED, and objecting — which demands a non-empty `objection_note` recording the deficiency found — moves it to OBJECTED and starts a five-day cure clock. Satisfaction, waiver, and objection are all available only while the contingency is OPEN, the clock has not passed its `deadline`, and the parent offer still stands ACCEPTED.

An objection is not the end of the road. Within five days of the objection, the listing side can agree a cure, moving the contingency from OBJECTED back to OPEN with a fresh deadline supplied as `new_deadline` in the payload — which must itself lie after the current clock, failing which the attempt is rejected with `ERR_INVALID_DEADLINE`. If the five-day cure window elapses with no cure agreed, the clock sweep moves the contingency from OBJECTED to EXPIRED; the same sweep expires an OPEN contingency whose `deadline` passes unactioned. Either form of expiry is what arms the deal's kick-out: once at least one contingency on the accepted offer stands OBJECTED with its objection unresolved for at least five days, or has already EXPIRED, the selling side may collapse the deal, moving the offer from ACCEPTED to FAILED. That collapse cascades — the listing is kicked back from UNDER_CONTRACT to ACTIVE with a LISTING_REACTIVATED event, the offer's `version` bumps, and every cleared deposit on the offer becomes obligated toward refund. Conversely, a deal can only march toward closing when every contingency on it stands SATISFIED or WAIVED; attempting to build the closing statement, or to disburse it, with contingencies anywhere outside those two states is rejected with `ERR_CONTINGENCY_UNRESOLVED` (HTTP 409).

### 3.6. Escrow Trust Accounting

Earnest money moves through the desk's trust account as a ledger. An EscrowOfficer records each entry against an offer with an `entry_type`, an `amount_cents`, and a `value_date` naming the day funds are expected to clear. In the ordinary workflow the desk posts DEPOSIT rows — buyer earnest money in — while the outflow directions RELEASE, REFUND, and FORFEIT materialize through the corresponding release, refund, and forfeit actions rather than being posted directly; amounts are recorded as positive cents, with outflows applied against the running balance. Every entry arrives PENDING.

The size of a deposit is policed at recording time. The required deposit is the offer's `offer_price_cents` multiplied by its `deposit_pct_basis` and divided by ten thousand, rounded half-up to whole cents. A DEPOSIT entry must be at least that required amount — an exactly-equal amount is acceptable — and anything short is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422). As an anti-structuring guard, no single DEPOSIT entry may exceed twice the required amount; a larger one is rejected with `ERR_DEPOSIT_EXCESSIVE` (HTTP 422), and per the pipeline order the excessive ceiling is evaluated before the sufficiency floor.

Entries then move under a three-role discipline. Clearing applies to DEPOSIT entries only: once the clock reaches such an entry's `value_date`, the EscrowOfficer marks it CLEARED — funds have arrived — and that action runs the provisional interest accrual described below; while the clock still precedes the `value_date`, the same desk may instead void the entry to VOIDED. Release into the closing is the ClosingOfficer's action and moves a CLEARED entry to DISBURSED, but only while the parent offer stands ACCEPTED and its closing statement stands APPROVED. Refund is the EscrowOfficer's action, moving a CLEARED entry to REFUNDED whenever the parent offer stands FAILED, WITHDRAWN, EXPIRED, or REJECTED — the obligation the offer-collapse cascade of §3.5 creates. Forfeiture is the ListingAgent's action, moving a CLEARED deposit to FORFEITED when the offer stands FAILED and every contingency on it stands SATISFIED or WAIVED — the buyer defaulted with no live contingency to hide behind. Release, refund, and forfeiture all demand a CLEARED entry; attempting any of them against an entry in any other state is rejected with `ERR_ESCROW_NOT_CLEARED` (HTTP 409). DISBURSED, REFUNDED, FORFEITED, and VOIDED are terminal.

Trust money earns its keep while it waits. Each cleared deposit accrues provisional simple interest from its `value_date` to the current clock at an annual rate of 1.00 percent on an actual/360 day-count basis: the entry's `amount_cents` times the rate times the days elapsed, divided by 360, rounded half-up per entry, with the per-entry figures then summed. When the closing statement is built, the accrual is recomputed as final interest at 1.25 percent on an actual/365 basis. The two variants legitimately diverge for identical inputs, and the final figure supersedes the provisional one on the closing statement's prorations, where the interest is credited to the buyer.

### 3.7. Building the Closing Statement

Once a deal's contingencies are resolved, settlement begins with the ClosingOfficer drafting a closing statement for the accepted offer, supplying the `offer_id` and a `rounding_mode` election of PER_LINE_THEN_SUM or SUM_THEN_PER_LINE that is pinned when the statement is built and immutable afterward. A statement may only be drafted for an offer standing ACCEPTED — any other offer state is rejected with `ERR_OFFER_NOT_ACCEPTED` (HTTP 409) — and each offer supports exactly one statement, so a second draft for the same offer is rejected with `ERR_DUPLICATE_RESOURCE`. The draft starts in DRAFT, and the statements collection can be browsed filtered by `offer_id` or `status`.

Building the statement — the ClosingOfficer's action carrying `expected_offer_version` against the pinned offer — requires the parent offer to stand ACCEPTED, every contingency on it SATISFIED or WAIVED, and every lien on the vessel to have its `payoff_amount_cents` computed; it then runs the full calculation pipeline, writes every computed field, creates the tax assessment rows the outcome implies, moves the statement from DRAFT to BALANCED, and bumps its `version`. The statement's `gross_price_cents` is a snapshot of the offer's `offer_price_cents` taken at build time, and the pipeline's evaluation order is pinned — commission first, then tax, then prorations, then the lien waterfall, then the settlement totals — because later figures drink from earlier ones.

Commission comes first and depends on the gross price alone. Under the STANDARD schedule the tier rate is ten percent when `gross_price_cents` is below USD 5,000,000, eight percent when it is at least USD 5,000,000 and below USD 20,000,000, and six percent when it reaches USD 20,000,000; `commission_cents` is the gross price multiplied by that rate, rounded half-up to whole cents before any split, with the step order pinned. When the selling agent's brokerage is the listing brokerage — an in-house deal — the listing side keeps everything: `listing_side_cents` equals `commission_cents` and `selling_side_cents` is zero. Otherwise the deal is co-brokered: `selling_side_cents` is half of `commission_cents` rounded half-up, and `listing_side_cents` is the remainder, computed by subtraction and never re-rounded, so the invariant that the two sides sum exactly to `commission_cents` always holds. The schedule code comes from the listing's `commission_tier_code` when set, falling back to the brokerage's `default_commission_tier_code`; under PREMIER each tier rate is multiplied by 1.10 — eleven, 8.8, and 6.6 percent — with the price thresholds unchanged, while BOUTIQUE applies a flat five percent of the gross price and bypasses tier selection entirely. Within each side, the named agent's personal share follows that agent's `split_pct_basis` with the house retaining the remainder; those per-agent figures are informational, and the side totals above are the authoritative numbers.

Tax is computed second, off the gross price and never off the commission. Unless an exemption applies, the situs is the offer's `settlement_state_code` and the taxable `basis_cents` equals `gross_price_cents`; the uncapped tax is the basis multiplied by the situs rate, rounded half-up once, and the assessment's `amount_cents` is the smaller of that uncapped figure and the situs cap — landing exactly on the cap whenever the uncapped figure reaches or exceeds it. The statutory rates are FL 6 percent, CA 7.25 percent, WA 6.5 percent, NY 4 percent, TX 6.25 percent, RI 7 percent, MD 6 percent, NC 4.75 percent, SC 6 percent, MA 6.25 percent, GA 4 percent, and NJ 6.625 percent; only Florida caps the bill, at USD 18,000, and South Carolina, at USD 30,000 — every other supported state applies its rate without a practical ceiling. Each assessment row carries its `closing_statement_id`, an `assessment_kind` of SALES_TAX or USE_TAX, the `situs_state_code` claiming the tax, the computed `basis_cents` and `amount_cents`, an `exemption_code`, and a status that begins at ASSESSED. When the buyer elected `offshore_delivery` and the assessment's `exemption_code` is OFFSHORE_DELIVERY, the basis and amount are both zero — `tax_cents` on the statement is likewise zero — and the assessment is recorded directly as EXEMPT for audit; a NONRESIDENT_REMOVAL code covers vessels removed from the state within the statutory days, and NONE marks an ordinary taxable delivery. When the buyer's `residency_state_code` differs from the situs and the home state grants credit, a separate USE_TAX assessment for the home state is computed as the home rate applied to the basis minus the sales tax already collected, floored at zero.

Prorations are computed third, off the clock. Slip fees prorate day by day across the closing month: the monthly slip fee is USD 4,500, and the per-day credit to the seller is that fee divided by the number of days in the closing month as the calendar at the closing date dictates, rounded half-up to whole cents first. `prorations_cents` is that rounded per-day figure multiplied by the number of days remaining in the month counting the closing day itself, after which a flat fuel credit of USD 750 is added with no further rounding — multiplying before rounding is forbidden, because the reversed order yields different cents. The figure is signed, with a credit to the seller positive.

The lien waterfall runs fourth. The payoff pool is `gross_price_cents` minus `commission_cents` minus `tax_cents` plus `prorations_cents`, with a negative pool treated as zero. Liens standing RECORDED are paid in `priority_rank` order, 1 first, ties broken by `created_at` ascending; each lien is allocated the smaller of the remaining pool and its face `amount_cents`, the allocation is written to the lien's `payoff_amount_cents`, and the arithmetic is exact with no rounding. A lien paid to its full face becomes SATISFIED, and when the last open encumbrance clears the vessel's `liens_status` is recomputed to CLEAN; a lien allocated strictly between nothing and its face becomes PARTIALLY_SATISFIED, the vessel stays ENCUMBERED, the shortfall surfaces as `ERR_WATERFALL_SHORTFALL` (HTTP 422), and a closing in that posture cannot proceed to disbursement; a lien allocated nothing stays RECORDED. The sum of the payoff allocations across the satisfied liens is the statement's `lien_payoff_total_cents`.

Settlement totals come last. `seller_net_cents` is the gross price minus the commission minus the tax minus `lien_payoff_total_cents` plus the prorations. `buyer_due_cents` is the gross price plus the tax minus `escrow_applied_cents`, where `escrow_applied_cents` is the sum of `amount_cents` over the offer's DEPOSIT entries standing CLEARED. Computing the seller net before the waterfall pool exists is forbidden — the pool must exist before any lien pays out.

Two fee schedules round out the settlement picture, estimated forward-looking and finalized at build. For a USCG-documented vessel the documentation fee is a flat USD 133.00 plus USD 4.00 per foot of `length_overall_ft`, the length first rounded half-up to a whole number of feet. For a state-titled vessel the title transfer fee is 0.15 percent of the gross price, rounded half-up and capped per state: USD 2,500 in CA, USD 2,250 in WA, and USD 2,000 in every other supported state. Before an offer is accepted, the provisional variant prices these fees off the listing's `list_price_cents`; the final variant, computed when the statement is built, prices them off the statement's `gross_price_cents`.

### 3.8. Approval, Disbursement, and Title Transfer

A balanced statement is not yet a blessed one. Approval is the ListingAgent's action, guarded by `expected_statement_version`, and it enforces the segregation wall of §2.9: the role that built the statement may not be the role that approves it, and a same-role attempt is rejected with `ERR_SEGREGATION_VIOLATION`. Approval moves the statement from BALANCED to APPROVED and bumps its `version`. When figures need to change, the ClosingOfficer reopens an APPROVED statement back to BALANCED — allowed only while no escrow entry on the offer has yet been DISBURSED — which re-runs all five calculations afresh; and a statement standing DRAFT or BALANCED may be voided to VOIDED, with the voiding of a BALANCED statement also voiding every tax assessment attached to it (their status becomes VOIDED). DISBURSED and VOIDED are the statement's terminal states.

Title work proceeds in parallel. The ClosingOfficer drafts one title transfer per statement, naming the `vessel_id` — which must equal the vessel of the offer's listing — the seller as `from_client_id`, the buyer as `to_client_id`, and a `warranty_of_title` election: FULL, warranting the vessel free and clear; QUITCLAIM, warranting nothing; or SPECIAL, warranting only against the grantor's own acts. Where the buyer is an LLC or corporation — the client record's `is_entity_buyer` flag — the entity's signatory rules govern who executes the warranty instrument. Executing the transfer requires the statement to stand APPROVED; a FULL warranty additionally requires the vessel's `liens_status` to be CLEAN, and attempting a full warranty on an encumbered vessel is rejected with `ERR_TITLE_ENCUMBERED` (HTTP 422); and the paperwork must be in order — a VALID USCG_COD documentation record for a documented vessel, a VALID STATE_TITLE record for a state-titled one. Execution stamps `executed_at` from the clock and moves the transfer from DRAFT to EXECUTED. Should the deal unwind before money moves, the ClosingOfficer may revoke an executed transfer — possible only while the statement has not been DISBURSED — moving it to REVOKED; RECORDED and REVOKED are terminal. The transfers collection can be browsed filtered by `closing_statement_id`, `vessel_id`, `from_client_id`, `to_client_id`, or `status`.

Disbursement is the deal's point of no return, and it is gated hard. The ClosingOfficer may disburse only when the statement stands APPROVED, every CLEARED DEPOSIT entry on the offer has been released to DISBURSED, the title transfer stands EXECUTED, every contingency stands SATISFIED or WAIVED, and the vessel's `liens_status` is CLEAN — an encumbered vessel at this gate is rejected with `ERR_LIENS_OUTSTANDING` (HTTP 422), and a waterfall that left a lien PARTIALLY_SATISFIED surfaces `ERR_WATERFALL_SHORTFALL`. A successful disbursement moves the statement to DISBURSED and fans out across the whole deal in one motion: the offer moves from ACCEPTED to CLOSED, the listing moves from UNDER_CONTRACT to CLOSED, the title transfer moves from EXECUTED to RECORDED with its attached documentation records flipping to TRANSFERRED, and every tax assessment on the statement is marked FILED, remitted to the state. The statement's `version` bumps, and the deal is done.

## 4. Endpoint Definitions

Status codes follow one rule set: creating a new resource answers 201, while reads, modifications, and lifecycle actions answer 200 — including the offer counter action, which answers 201 because it mints the child offer. Request and response bodies, side effects, and preconditions are specified in §2 and §3; this table is the routing and authorization reference only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /yacht/brokerages | Register a brokerage house | PlatformAdmin |
| GET | /yacht/brokerages/{id} | Fetch one brokerage | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/agents | Onboard a broker agent under a brokerage | PlatformAdmin |
| GET | /yacht/agents/{id} | Fetch one agent | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| GET | /yacht/agents | List agents, filterable by brokerage | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/clients | Register a client (seller/buyer) | PlatformAdmin, ListingAgent, SellingAgent |
| GET | /yacht/clients/{id} | Fetch one client | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/vessels | Register a vessel with documentation mode (USCG or STATE) | PlatformAdmin, ListingAgent |
| GET | /yacht/vessels/{id} | Fetch one vessel | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| PUT | /yacht/vessels/{id} | Update vessel descriptive fields | PlatformAdmin, ListingAgent |
| GET | /yacht/vessels/{id}/liens | List liens recorded against a vessel | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/vessels/{id}/liens | Record a discovered lien on the vessel (lien search result) | ListingAgent, ClosingOfficer |
| POST | /yacht/liens/{id}/release | Mark a lien released by lienholder filing | ListingAgent, ClosingOfficer |
| GET | /yacht/vessels/{id}/documentation-records | List documentation records (COD, state title, abstract) for a vessel | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/vessels/{id}/documentation-records | File a documentation record; filing a same-kind record supersedes the prior VALID one | ListingAgent, ClosingOfficer |
| POST | /yacht/listings | Draft a listing agreement | ListingAgent |
| GET | /yacht/listings/{id} | Fetch one listing | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| GET | /yacht/listings | List listings with filters and pagination | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/listings/{id}/activate | Activate a DRAFT or SUSPENDED listing | ListingAgent |
| POST | /yacht/listings/{id}/suspend | Suspend an ACTIVE listing (no new offers) | ListingAgent |
| POST | /yacht/listings/{id}/cancel | Cancel a listing with no ACCEPTED offer | ListingAgent |
| PUT | /yacht/listings/{id}/price | Change list price; marks syndication STALE | ListingAgent |
| POST | /yacht/listings/{id}/syndication-events | Push listing to an MLS channel; payload price must equal current list price | ListingAgent |
| GET | /yacht/listings/{id}/syndication-events | List syndication pushes for a listing | PlatformAdmin, ListingAgent, SellingAgent |
| GET | /yacht/listings/{id}/offers | List offers on a listing | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/offers | Submit a buyer offer on a listing | SellingAgent |
| GET | /yacht/offers/{id} | Fetch one offer | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| GET | /yacht/offers | List offers with filters and pagination | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/offers/{id}/accept | Seller side accepts a PENDING offer (OCC-guarded) | ListingAgent |
| POST | /yacht/offers/{id}/reject | Seller side rejects a PENDING offer | ListingAgent |
| POST | /yacht/offers/{id}/counter | Counter a PENDING offer; creates child offer in PENDING with round_no+1 (OCC-guarded) | ListingAgent, SellingAgent |
| POST | /yacht/offers/{id}/withdraw | Buyer side withdraws its own PENDING offer | SellingAgent |
| POST | /yacht/offers/{id}/fail | Collapse an ACCEPTED offer after unresolved contingency objection (kick-out) | SellingAgent |
| GET | /yacht/offers/{id}/contingencies | List contingencies on an offer | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/contingencies/{id}/satisfy | Buyer side marks a contingency satisfied | SellingAgent |
| POST | /yacht/contingencies/{id}/waive | Buyer side waives a contingency | SellingAgent |
| POST | /yacht/contingencies/{id}/object | Buyer side objects to a contingency finding | SellingAgent |
| POST | /yacht/contingencies/{id}/renegotiate | Seller side agrees a cure; contingency returns to OPEN with new deadline | ListingAgent |
| POST | /yacht/offers/{id}/escrow-entries | Record an escrow ledger entry (DEPOSIT in; RELEASE/REFUND/FORFEIT are action endpoints) | EscrowOfficer |
| GET | /yacht/offers/{id}/escrow-entries | List escrow entries for an offer | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/escrow-entries/{id}/clear | Mark a PENDING deposit cleared (funds arrived) | EscrowOfficer |
| POST | /yacht/escrow-entries/{id}/void | Void a PENDING entry before its value date | EscrowOfficer |
| POST | /yacht/escrow-entries/{id}/release | Release cleared funds to closing disbursement | ClosingOfficer |
| POST | /yacht/escrow-entries/{id}/refund | Refund cleared funds to buyer on failed/withdrawn offer | EscrowOfficer |
| POST | /yacht/escrow-entries/{id}/forfeit | Forfeit cleared deposit to seller on buyer default | ListingAgent |
| POST | /yacht/closing-statements | Create a DRAFT closing statement for an ACCEPTED offer | ClosingOfficer |
| GET | /yacht/closing-statements/{id} | Fetch a closing statement with all computed fields | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| GET | /yacht/closing-statements | List closing statements, filterable by offer | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/closing-statements/{id}/build | Run all calculations and balance the statement (OCC on offer version) | ClosingOfficer |
| POST | /yacht/closing-statements/{id}/approve | Listing-side approval of a balanced statement (OCC on statement version; segregation of duties) | ListingAgent |
| POST | /yacht/closing-statements/{id}/reopen | Reopen an APPROVED statement for rebalancing | ClosingOfficer |
| POST | /yacht/closing-statements/{id}/void | Void a DRAFT or BALANCED statement | ClosingOfficer |
| POST | /yacht/closing-statements/{id}/disburse | Final disbursement; closes offer and listing; records title transfer | ClosingOfficer |
| GET | /yacht/closing-statements/{id}/tax-assessments | List tax assessments attached to a statement | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/closing-statements/{id}/title-transfers | Draft a title transfer with warranty-of-title election | ClosingOfficer |
| GET | /yacht/title-transfers/{id} | Fetch one title transfer | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| GET | /yacht/title-transfers | List title transfers with filters | PlatformAdmin, ListingAgent, SellingAgent, ClosingOfficer, EscrowOfficer |
| POST | /yacht/title-transfers/{id}/execute | Execute signatures on the transfer instrument | ClosingOfficer |
| POST | /yacht/title-transfers/{id}/revoke | Revoke an executed transfer before disbursement | ClosingOfficer |
| GET | /yacht/domain-events | Audit log query | PlatformAdmin |
| POST | /_clock/set_current_utc | Set the logical server clock (test-driving endpoint). Default startup clock is exactly 2026-08-01T00:00:00Z; before any set_current_utc call the clock reads this fixed default and never falls back to wall-clock time | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each code are specified in the narratives of §2 and §3; this catalogue is the lookup reference only.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_VIOLATION | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_DOC_MODE_MISMATCH | 422 |
| ERR_INVALID_DEADLINE | 422 |
| ERR_DEADLINE_PASSED | 422 |
| ERR_LIEN_INSTRUMENT_MISMATCH | 422 |
| ERR_LISTING_NOT_ACCEPTING | 409 |
| ERR_TITLE_ENCUMBERED | 422 |
| ERR_DEPOSIT_INSUFFICIENT | 422 |
| ERR_DEPOSIT_EXCESSIVE | 422 |
| ERR_ESCROW_NOT_CLEARED | 409 |
| ERR_LIENS_OUTSTANDING | 422 |
| ERR_SYNDICATION_STALE_PRICE | 422 |
| ERR_CONTINGENCY_UNRESOLVED | 409 |
| ERR_OFFER_NOT_ACCEPTED | 409 |
| ERR_WATERFALL_SHORTFALL | 422 |
