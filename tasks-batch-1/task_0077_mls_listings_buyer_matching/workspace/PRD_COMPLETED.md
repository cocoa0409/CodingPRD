# MLS Listings & Buyer Matching API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the MLS Listings & Buyer Matching API, a back-end platform that coordinates a residential real-estate transaction from the moment a property is listed to the moment its commission is settled at closing. The defining characteristic of the domain is that two professionals sit on opposite sides of every deal: a sell-side agent who owns the property listing and a buy-side agent who represents a prospective purchaser. The platform must keep these two perspectives cleanly segregated — the same individual may act as the listing agent on one property and the buyer's agent on another, but never represent both sides of a single property — while still letting them meet in the structured, turn-based negotiation that an offer and its counters represent.

Real-estate transactions are rarely linear. A single property may attract several competing offers at once; an accepted offer may collapse weeks later when an inspection turns up defects or an appraisal comes in low; and a property can return to the open market after a contingency fails. The API therefore models a property's life as a state machine with cascading consequences: accepting one offer freezes its rivals, opens the buyer's contingencies, and locks the negotiated price, whereas a failed contingency unwinds the deal and reopens the listing. Showing appointments are governed by physical lockboxes with mandatory cleaning-and-travel buffers between visits, and the financial outcome — who is owed what at closing — is computed by a deterministic commission waterfall.

Because several writers may legitimately race to act on the same property, the platform applies optimistic concurrency control at the points where double-committing a property would be catastrophic. The remainder of this document defines the global contracts that every endpoint honors (Section 2), the business workflows that drive the listing, showing, offer, contingency, and commission lifecycles (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request that mutates state, and every request that reads a protected resource, must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The API recognizes exactly three roles, spelled precisely as follows: `ListingAgent`, `BuyerAgent`, and `Anonymous`.

When a request to a protected operation omits either header, or supplies an `X-User-ID` that does not resolve to a registered `Agent` for the agent roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The unauthenticated/anonymous surface — creating brokerages, registering agents, registering buyers, and all `GET` reads — does not require authentication headers.

The `ListingAgent` and `BuyerAgent` roles are both **entity-backed by the `Agent` record**: when `X-User-Role` is `ListingAgent`, the value of `X-User-ID` is the `id` of the acting `Agent`, and ownership checks on any sell-side resource compare the listing's `listing_agent_id` against `X-User-ID`. Likewise, when `X-User-Role` is `BuyerAgent`, `X-User-ID` is the `id` of the acting `Agent`, and ownership checks on a buy-side resource compare that resource's `buyer_agent_id` against `X-User-ID`. The same physical `Agent` may present as `ListingAgent` on one property and as `BuyerAgent` on another; the role header, not the identity, selects the side. The `Anonymous` role is an **opaque operator identifier** not tied to any persisted entity: it is the unauthenticated surface used for system setup (creating brokerages, registering agents, suspending agents, advancing the test clock) and for public reads. The server does not compare an `Anonymous` `X-User-ID` to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint explicitly states otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching records across the whole collection and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation, and `updated_at` is an ISO 8601 UTC timestamp recording the most recent modification. The `version` field is an integer that starts at its initial value of 1 on creation and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in Section 2.6.

The following resources carry the full quartet of `id`, `created_at`, `updated_at`, and `version`: `Brokerage`, `Agent`, `Listing`, `Lockbox`, `ShowingAppointment`, `Offer`, `Contingency`, and `CommissionLedger`. Two resources are append-only records and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: the `Buyer` record and the `CounterRound` record. A `CounterRound`, once written, is immutable; the negotiation history is never rewritten.

### 2.5. Hierarchical Consistency and Automatic Propagation

Several operations mutate more than one resource at once, and a parent's state is frequently a function of its children. When a child changes in a way that satisfies or violates a parent's state criteria, the server transitions the parent automatically — no separate client request is required on the parent. Each such automatic transition is itself a mutation of the parent: it refreshes the parent's `updated_at` and increments its `version`. For example, resolving the final outstanding contingency on an accepted offer drives the listing forward without the listing agent calling any listing endpoint, and that movement bumps the listing's `version`. Implementers must treat every cascade described in Section 3 as carrying these bookkeeping side effects unless stated otherwise.

When a request targets a nested resource, the server validates the path identifiers from left to right and rejects the first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404). Foreign-key references supplied in a request body are validated after the path identifiers, also yielding `ERR_NOT_FOUND` when a referenced record does not exist. This left-to-right discipline means, for instance, that a request against a lockbox under a non-existent listing fails on the listing before the lockbox is ever consulted.

### 2.6. Optimistic Concurrency Control on the Listing

Two operations in the system can be raced by independent writers in a way that would corrupt the property's state, and both are guarded by optimistic concurrency control keyed on the target `Listing`'s `version`.

The first is **accepting an offer**. The request body for an offer acceptance must include `expected_listing_version`, carrying the `version` of the parent listing that the acting agent last observed. If that value does not equal the listing's current `version`, the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the mechanism that resolves a multiple-offer situation: from a listing's `ACTIVE` state, two distinct offers may each be independently eligible for acceptance, but the first successful acceptance drives the listing to `UNDER_CONTRACT` and increments its `version`, so any later acceptance still carrying the previously observed version is rejected as stale rather than double-committing the property.

The second is **closing a listing**. The request body for a close must include `expected_listing_version`, again carrying the listing's last-observed `version`. If it does not match the listing's current `version`, the close is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a contingency resolution that bubbles the listing to `PENDING`, or a contingency failure that reverts it to `ACTIVE`, advances the listing's `version` between the agent's read and the close, a close carrying a now-superseded version is correctly rejected as stale. No endpoint other than these two carries a version field, and no other operation performs an OCC check.

### 2.7. Monetary Precision and the Commission Waterfall

All money in the system is represented as integer cents, never as a floating-point dollar amount. List prices, offer prices, counter prices, earnest money, budgets, incomes, and debts are all integers. The only rounding in the system occurs where a commission rate (a fractional multiplier) is applied to a cent amount; in every such case the product is rounded to the nearest whole cent using the round-half-up convention.

The commission settlement is a waterfall with a pinned rounding order. The total commission is the sale price multiplied by the listing's total commission rate, rounded half up to whole cents. The co-op (buyer-side) share is then the **already-rounded** total commission multiplied by the listing's co-op split, again rounded half up to whole cents — the co-op share is rounded off the rounded total, never off the raw product of sale price, total rate, and split. The listing-side share is the rounded total minus the rounded co-op share, so the listing side absorbs any single-cent rounding remainder and the two shares always sum exactly to the total. Section 3 specifies which fields hold each of these figures.

### 2.8. Commission Defaults and Brokerage Configuration

Commission economics originate at the brokerage and may be overridden per listing. A `Brokerage` carries a `default_total_commission_pct` (a rate strictly greater than 0 and at most 0.10) and a `default_coop_split_pct` (a fraction between 0 and 1 inclusive) describing the buyer-side share of the total. When a listing is created without an explicit `total_commission_pct`, it inherits the brokerage's `default_total_commission_pct`; when created without an explicit `coop_split_pct`, it inherits the brokerage's `default_coop_split_pct`. A listing's own `total_commission_pct`, when supplied, must be strictly greater than 0 and at most 0.10, and its `coop_split_pct`, when supplied, must be between 0 and 1 inclusive. These per-listing rates, whether explicit or inherited, are the ones the commission waterfall uses at closing.

### 2.9. Showing Windows and Lockbox Buffers

Showing appointments occupy a half-open time interval: the window runs from `start_at` up to but not including `end_at`, and `end_at` must be strictly later than `start_at`. Each lockbox declares a `turnaround_minutes` buffer — a mandatory gap, defaulting to 30 minutes, that must separate the end of one showing from the start of the next on that lockbox so the property can be reset between visits. Conflict detection for confirmation, and the temporal gating of showing completion against the server clock, are detailed in Section 3.

### 2.10. The Negotiation Turn and Side Segregation

Offers progress through a strict alternation of turns. At any moment a live offer has a `current_party` indicating which side must act next, and counter and side-specific acceptance operations are permitted only when the acting side matches `current_party`; a request from the wrong side is rejected with `ERR_NOT_YOUR_TURN` (HTTP 409). Independently of whose turn it is, the platform forbids a single agent from sitting on both sides of one property: the agent who submits an offer may not be the listing's own listing agent. The precise turn arithmetic, the dual-agency prohibition, and the budget and amount guards that accompany offer creation are specified in Section 3.

## 3. Business Logic & Workflows

### 3.1. Brokerages, Agents, and Buyers: The Participant Registry

Before any property can be listed, the participant registry must be populated. A brokerage is created on the anonymous setup surface by supplying its legal `name`, its `default_total_commission_pct`, and its `default_coop_split_pct`. Agents are then registered under a brokerage by supplying the `brokerage_id` they belong to, their `full_name`, and their `license_no` — the state real-estate license number, which must be globally unique across all agents. A registration whose `license_no` collides with an existing agent is rejected with `ERR_DUPLICATE` (HTTP 409). Every newly registered agent begins life with `status` of `ACTIVE`.

An agent's `status` is one of `ACTIVE` or `SUSPENDED`. The operator surface can suspend an agent, setting `status` to `SUSPENDED`. A suspended agent is barred from the three creation operations that bring new commercial commitments into being — creating a listing, submitting an offer, and issuing a counter — each of which is rejected with `ERR_AGENT_SUSPENDED` (HTTP 403) while the acting agent is suspended.

A buyer is registered by their representing buy-side agent (or on the anonymous surface). Buyer registration carries the `buyer_agent_id` of the representing agent, the buyer's `full_name`, their `max_budget_cents` (the stated maximum purchase budget, a non-negative integer), their `prequalified_amount_cents` (the lender's pre-qualification ceiling, a non-negative integer that defaults to 0 when omitted, where 0 signals "not prequalified"), their `monthly_income_cents` (gross monthly income, non-negative), and their `monthly_debt_cents` (existing monthly debt obligations, a non-negative integer defaulting to 0 when omitted). The income and debt figures are retained because the financing contingency's debt-to-income gate consults them later. The brokerage exposes its agents through a reverse lookup, and each agent exposes both the buyers it represents and the listings it carries on the sell side.

### 3.2. The Listing Lifecycle

A listing is the aggregate root of the transaction. A `ListingAgent` creates one by supplying the `listing_agent_id` (which must be the acting agent), the property `address`, the asking `list_price_cents` (a positive integer), and optionally a per-listing `total_commission_pct` and `coop_split_pct` that override the brokerage defaults as described in Section 2.8. A new listing begins in `DRAFT` status with an `offer_posture` of `NONE`. The `address` must be unique among all listings whose status is not `WITHDRAWN` and not `CLOSED`; a colliding address on a still-live listing is rejected with `ERR_DUPLICATE`. A listing's `status` ranges over `DRAFT`, `ACTIVE`, `UNDER_CONTRACT`, `PENDING`, `CLOSED`, and `WITHDRAWN`, with `CLOSED` and `WITHDRAWN` being terminal.

Activation moves a listing from `DRAFT` to `ACTIVE`. It may be performed only by the listing's own listing agent — a mismatch yields `ERR_NOT_LISTING_AGENT` (HTTP 403) — and only when the listing already has at least one lockbox in `INSTALLED` status; activating a listing with no installed lockbox is rejected with `ERR_NO_LOCKBOX` (HTTP 409). On activation the `offer_posture` is set to `NONE` and the listing's `version` increments by one.

Withdrawal is the listing agent's escape hatch and is available from two states. From `ACTIVE`, withdrawing transitions the listing to `WITHDRAWN`, and as a cascade every offer on the listing currently in `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED` is moved to `REJECTED`, every showing appointment on the listing's lockbox in `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`, and the listing's `version` increments. From `DRAFT`, withdrawing likewise transitions the listing to `WITHDRAWN` and increments `version`, but there are no live offers or showings to cascade. Either withdrawal is barred to anyone but the listing agent, again under `ERR_NOT_LISTING_AGENT`. Withdrawal is terminal.

Three further listing transitions are driven entirely by the system rather than by a listing-agent action, and are described where their triggers live: the advance to `UNDER_CONTRACT` on offer acceptance (Section 3.6), the bubble to `PENDING` when the last contingency clears and the revert to `ACTIVE` when a contingency fails (Section 3.7). The terminal close from `PENDING` to `CLOSED` is described in Section 3.8.

### 3.3. Lockboxes

A lockbox is installed on a listing by the listing agent and is the physical gatekeeper for showings. Installation supplies a `serial_no`, optionally an `access_mode`, and optionally a `turnaround_minutes` buffer. The `listing_id` binding is set by the system from the path. A lockbox's `access_mode` is either `APPOINTMENT_ONLY` (the default), meaning access requires a `CONFIRMED` showing appointment overlapping the access time, or `OPEN_ACCESS`. The `turnaround_minutes` value defaults to 30 and must be a non-negative integer. A lockbox's `status` is `INSTALLED` (the default on creation) or `DISABLED`, with `DISABLED` terminal. The `serial_no` must be unique among installed lockboxes; a duplicate installed serial is rejected with `ERR_DUPLICATE`.

Disabling a lockbox moves it from `INSTALLED` to `DISABLED`; a disable attempt on a lockbox not in `INSTALLED` status (for instance one already `DISABLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the parent listing's listing agent may do so, under `ERR_NOT_LISTING_AGENT` otherwise, and disabling is refused while any showing on the lockbox is in `CONFIRMED` status — that rejection is `ERR_LOCKBOX_HAS_SHOWINGS` (HTTP 409). When disabling does proceed, every showing on the lockbox still in `REQUESTED` status is cascaded to `CANCELLED`. Note that a showing may still be *requested* against a `DISABLED` lockbox, but it can never be *confirmed* — confirmation against a disabled lockbox is rejected with `ERR_LOCKBOX_DISABLED` (HTTP 409).

### 3.4. Requesting and Confirming Showings

A buy-side agent requests a showing on a lockbox by supplying the `buyer_agent_id` making the request (which must match the acting agent, under `ERR_NOT_BUYER_AGENT`), the `buyer_id` being shown the property, and the window's `start_at` and `end_at` instants. The system sets the `lockbox_id` from the path. The window must be well-formed: `end_at` strictly later than `start_at`, or the request is rejected with `ERR_BAD_TIME_WINDOW` (HTTP 422). A new showing begins in `REQUESTED` status; its `status` ranges over `REQUESTED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, the last three terminal.

Confirmation is the listing agent's action, moving a showing from `REQUESTED` to `CONFIRMED`. It is barred to anyone but the parent listing's listing agent (`ERR_NOT_LISTING_AGENT`), refused when the showing is not in `REQUESTED` status (`ERR_INVALID_STATE`, HTTP 409, checked before the lockbox state), refused when the lockbox is `DISABLED` (`ERR_LOCKBOX_DISABLED`), and refused when the proposed window collides with another confirmed showing on the same lockbox. The collision test treats each window as half-open and widens it by the lockbox's `turnaround_minutes` buffer on its end: the candidate is treated as running from its `start_at` up to `end_at` plus the buffer, and each existing `CONFIRMED` showing on the same lockbox is treated as running from its `start_at` up to its `end_at` plus the buffer. The two conflict when the candidate's start is strictly before the existing window's buffered end and the existing window's start is strictly before the candidate's buffered end; the candidate showing being confirmed is itself excluded from the comparison set. Because the intervals are half-open, two showings that abut exactly at the buffer boundary — where one window's buffered end equals the next window's start — do not conflict. A genuine overlap is rejected with `ERR_SHOWING_CONFLICT` (HTTP 409).

A buyer's agent may cancel their own showing from either `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`; only the showing's `buyer_agent_id` may cancel, otherwise `ERR_NOT_BUYER_AGENT`, and a cancel from any other (terminal) status is rejected with `ERR_INVALID_STATE` (HTTP 409). The listing agent closes out a confirmed showing in one of two ways once it is temporally over: completing it (`CONFIRMED` to `COMPLETED`) records a successful visit, while marking a no-show (`CONFIRMED` to `NO_SHOW`) records that the buyer did not appear. Both require the acting agent to be the parent listing's listing agent (`ERR_NOT_LISTING_AGENT`), both require the showing to be in `CONFIRMED` status (otherwise `ERR_INVALID_STATE`, checked before the clock gate), and both require that the server's current clock be at or after the showing's `end_at`; an attempt before the window has elapsed is rejected with `ERR_SHOWING_NOT_OVER` (HTTP 409). The server's notion of "now" is set through an administrative test-driving capability that advances the logical clock to a supplied `to_iso8601` instant; this is what makes completion and no-show gating deterministic.

### 3.5. Submitting Offers and the Multiple-Offer Posture

A buy-side agent submits an offer against a listing by supplying the `buyer_id` of the offering buyer, the `buyer_agent_id` submitting it (which must match the acting agent, under `ERR_NOT_BUYER_AGENT`), the opening `initial_price_cents` (a positive integer), the `earnest_money_cents` deposit (a non-negative integer), and an optional `requested_contingencies` array — a subset of `INSPECTION`, `APPRAISAL`, and `FINANCING` that the buyer wishes to attach. The system sets the offer's `listing_id` from the path. A new offer begins in `OPEN` status with `current_party` of `SELLER` (a fresh buyer offer awaits the seller's response first) and a `round_count` of 0. An offer's `status` ranges over `OPEN`, `SELLER_COUNTERED`, `BUYER_COUNTERED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED`; `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED` are terminal.

Several guards run at submission, and they enforce the side-segregation, suspension, budget, and amount rules together. The submitting agent must not be the listing's own listing agent — an offer whose `buyer_agent_id` equals the target listing's `listing_agent_id` is rejected with `ERR_DUAL_AGENCY_FORBIDDEN` (HTTP 422), because no agent may represent both sides of one property. The target listing must be in `ACTIVE` status to receive an offer; a submission against a listing in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409), checked after the dual-agency guard and before the suspension check. A suspended agent cannot submit at all (`ERR_AGENT_SUSPENDED`). The opening price is a budget-guarded figure: if `initial_price_cents` exceeds the buyer's `max_budget_cents`, the offer is rejected with `ERR_OVER_BUDGET` (HTTP 422). Finally, the amounts must be sane — a non-positive price, or `earnest_money_cents` greater than `initial_price_cents`, is rejected with `ERR_INVALID_AMOUNT` (HTTP 422).

A listing's `offer_posture` is a computed summary of its competitive situation, taking the value `NONE`, `SINGLE`, or `MULTIPLE`, and it is recomputed on every offer event (creation, counter, acceptance, rejection, withdrawal, expiry) and on activation. The rule counts the offers on the listing that are *live* — those in `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED`. If the listing has any offer in `ACCEPTED` status, the posture is `NONE`; otherwise, if there are no live offers the posture is `NONE`, if there is exactly one live offer the posture is `SINGLE`, and if there are two or more live offers the posture is `MULTIPLE`.

### 3.6. The Counter Negotiation Loop and Acceptance

Once an offer is open, the two sides negotiate by countering, and the negotiation is a genuine back-and-forth loop. A counter is issued by supplying a `counter_price_cents` (a positive integer) and the `actor_agent_id` of the agent issuing it. Each counter appends an immutable `CounterRound` to the offer's append-only history; the round records its `offer_id`, a 1-based `round_index` that increases monotonically within the offer, the `by_party` (`SELLER` or `BUYER`) that issued it, the `counter_price_cents`, and the `actor_agent_id`. A counter is permitted only while the parent listing is `ACTIVE` (otherwise `ERR_INVALID_STATE`, HTTP 409) and only when the issuing side matches whose turn it is (otherwise `ERR_NOT_YOUR_TURN`); a non-positive counter price is rejected with `ERR_INVALID_AMOUNT`, and a suspended agent cannot counter (`ERR_AGENT_SUSPENDED`).

The turn machinery threads through the offer's status. From `OPEN`, the seller's listing agent may counter, moving the offer to `SELLER_COUNTERED`; from `SELLER_COUNTERED`, the offer's own buyer agent may counter back, moving it to `BUYER_COUNTERED`; and from `BUYER_COUNTERED`, the listing agent may counter again, returning it to `SELLER_COUNTERED` — this is the cycle that repeats until someone accepts, rejects, or withdraws. Each counter is owned by the side whose turn it is: a seller-side counter requires the acting agent to be the listing's `listing_agent_id` (`ERR_NOT_LISTING_AGENT`), and a buyer-side counter requires the acting agent to be the offer's `buyer_agent_id` (`ERR_NOT_BUYER_AGENT`). On each counter, a new `CounterRound` is appended with `round_index` equal to the prior `round_count` plus one, the offer's `current_price_cents` is set to the new `counter_price_cents`, the `current_party` flips to the other side, and `round_count` is incremented by one.

The offer's negotiation state is a projection over its counter history, replayed in ascending `round_index` order. When an offer has no counter rounds at all, its `current_price_cents` is its `initial_price_cents` and its `current_party` is `SELLER`. When it has at least one round, the `current_price_cents` is the `counter_price_cents` of the latest round, and the `current_party` is the side opposite the latest round's `by_party` — if the latest round was issued by the `SELLER`, it is now the `BUYER`'s turn, and vice versa. The `round_count` is simply the number of rounds recorded. All counter rounds are immutable and are never filtered by status.

Acceptance ends the negotiation and is the pivotal cascade in the system. An offer may be accepted from three states, and which side may accept depends on the state. From `OPEN`, the listing agent accepts (the seller agrees to the buyer's standing terms). From `BUYER_COUNTERED`, the listing agent accepts — the seller is taking the buyer's latest counter, so this is valid only when it is the seller's turn (`current_party` is `SELLER`, otherwise `ERR_NOT_YOUR_TURN`). From `SELLER_COUNTERED`, the buyer's agent accepts — the buyer is taking the seller's latest counter, valid only when it is the buyer's turn (`current_party` is `BUYER`, otherwise `ERR_NOT_YOUR_TURN`). In every case the acting agent must hold the correct side (the listing agent under `ERR_NOT_LISTING_AGENT` for the seller-side acceptances, the offer's buyer agent under `ERR_NOT_BUYER_AGENT` for the buyer-side acceptance), the listing must be `ACTIVE` (otherwise `ERR_INVALID_STATE`), and the supplied `expected_listing_version` must match the listing's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412, as detailed in Section 2.6).

When an acceptance succeeds, the offer's `effective_price_cents` is frozen at its `current_price_cents` — the standing price at the moment of acceptance, which for a counter acceptance is the latest counter's price. The listing advances from `ACTIVE` to `UNDER_CONTRACT`: its `accepted_offer_id` is set to the accepted offer's `id`, every sibling offer on the listing still in `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED` is cascaded to `REJECTED`, the `offer_posture` is recomputed (which yields `NONE`, since the accepted offer suppresses the posture and no live competitors remain), and the listing's `version` increments. A `Contingency` is then materialized in `PENDING` status for each kind named in the offer's `requested_contingencies`. If `requested_contingencies` is empty, there is nothing to protect, so the listing immediately bubbles from `UNDER_CONTRACT` to `PENDING` in the same operation.

An offer can also be ended without acceptance. Rejecting an offer is available from `OPEN` (by the listing agent, under `ERR_NOT_LISTING_AGENT`), from `SELLER_COUNTERED` (by the buyer agent declining the seller's counter, under `ERR_NOT_BUYER_AGENT`), and from `BUYER_COUNTERED` (by the listing agent declining the buyer's counter, under `ERR_NOT_LISTING_AGENT`), in every case moving the offer to `REJECTED` and recomputing the listing's `offer_posture`. The side eligible to reject is fixed by the offer's current status as just described: a request whose role is the wrong side for that status (for example a `BuyerAgent` rejecting from `OPEN`) is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), and a reject attempt from any status outside `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Withdrawal is the buyer's prerogative and is available from `OPEN`, `SELLER_COUNTERED`, or `BUYER_COUNTERED`: the offer's buyer agent (under `ERR_NOT_BUYER_AGENT`) moves the offer to `WITHDRAWN` and the listing's `offer_posture` is recomputed.

### 3.7. Contingencies: Protecting and Unwinding the Deal

Once an offer is accepted with contingencies, each materialized `Contingency` protects the deal until it is resolved. A contingency records the `offer_id` it hangs off, its `kind` (`INSPECTION`, `APPRAISAL`, or `FINANCING`), an `appraised_value_cents` field used only by the appraisal kind (supplied on resolution, defaulting to 0), and a `status` that begins `PENDING` and ends in one of the terminal values `WAIVED`, `SATISFIED`, or `FAILED`. All contingency work is performed by the offer's buyer agent (under `ERR_NOT_BUYER_AGENT`) and is permitted only while the parent listing is `UNDER_CONTRACT` (otherwise `ERR_INVALID_STATE`).

A contingency can be **waived** outright, moving it from `PENDING` to `WAIVED`. A contingency can be **resolved**, which runs the kind's gate and lands the contingency in either `SATISFIED` or `FAILED`. For an `INSPECTION` contingency, resolution simply satisfies it. For an `APPRAISAL` contingency, the buyer's agent supplies an `appraised_value_cents`; the gate satisfies the contingency only when the appraised value is at least the offer's `effective_price_cents`, and otherwise lands it in `FAILED` (a low appraisal). For a `FINANCING` contingency, the gate is a debt-to-income test combined with a pre-qualification ceiling test, detailed below; it satisfies the contingency only when both tests pass and otherwise lands it in `FAILED`. A contingency can also be **failed** explicitly — for example when an inspection turns up defects — moving it directly from `PENDING` to `FAILED`.

The financing gate computes a back-end debt-to-income ratio. First, an estimated monthly housing payment is derived from the offer's `effective_price_cents` multiplied by a monthly payment factor of 0.005 (a crude principal-and-interest estimate per cent of price), with that product rounded half up to whole cents. The back-end ratio is then the buyer's `monthly_debt_cents` plus this estimated monthly payment, all divided by the buyer's `monthly_income_cents`; when `monthly_income_cents` is 0, the debt-to-income test is treated as failing (the ratio condition does not pass) rather than dividing by zero. The contingency passes only when two conditions both hold: the back-end ratio is at most the maximum allowed ratio of 0.43 (a ratio of exactly 0.43 passes; 0.4300001 fails), and the offer's `effective_price_cents` is at most the buyer's `prequalified_amount_cents`. If either condition is not met, the financing contingency lands in `FAILED`.

The consequences of resolution depend on the outcome. Whenever a contingency leaves `PENDING` by being satisfied or waived, the system checks whether it was the last `PENDING` contingency on the offer; if so — meaning every contingency on the accepted offer is now in `WAIVED` or `SATISFIED`, with none `PENDING` and none `FAILED` — the listing bubbles from `UNDER_CONTRACT` to `PENDING`, incrementing its `version`. A failure, by contrast, unwinds the deal: when any contingency on the accepted offer transitions to `FAILED`, the accepted offer is moved to `WITHDRAWN`, the listing reverts from `UNDER_CONTRACT` to `ACTIVE`, its `accepted_offer_id` is cleared to null, the offer's remaining `PENDING` contingencies are cascaded to `WAIVED`, the `offer_posture` is recomputed from whatever live offers remain, and the listing's `version` increments. This compensation returns the property to the open market.

### 3.8. Closing the Listing and Settling Commission

A listing reaches its happy ending when all contingencies have cleared and it sits in `PENDING`. The listing agent then closes it, supplying `expected_listing_version`. The close is barred to anyone but the listing agent (`ERR_NOT_LISTING_AGENT`), refused unless the listing is actually in `PENDING` status (otherwise `ERR_INVALID_STATE`), and refused when `expected_listing_version` does not match the listing's current `version` (`ERR_STALE_VERSION`, per Section 2.6). On a successful close, the listing moves from `PENDING` to `CLOSED`, its `final_sale_price_cents` is set to the accepted offer's `effective_price_cents`, every showing appointment on the listing's lockbox still in `REQUESTED` or `CONFIRMED` is cascaded to `CANCELLED`, the listing's `version` increments, and a `CommissionLedger` is created for the listing by running the commission split.

The `CommissionLedger` records the `listing_id` it settles, the `sale_price_cents` the commission is computed on (the listing's `final_sale_price_cents`), the `total_commission_cents`, the `coop_commission_cents`, and the `listing_side_commission_cents`. These are computed by the waterfall of Section 2.7: the `total_commission_cents` is the sale price multiplied by the listing's `total_commission_pct`, rounded half up; the `coop_commission_cents` is that already-rounded total multiplied by the listing's `coop_split_pct`, rounded half up; and the `listing_side_commission_cents` is the total minus the co-op share, so it absorbs the rounding penny and the two shares sum exactly to the total. Exactly one ledger exists per closed listing, retrievable through the listing's commission-ledger lookup, which is a paginated list endpoint returning an `array` envelope of the listing's ledgers (a single-element array once the listing is closed, an empty array before close).

### 3.9. The Net-to-Seller Sheet

At any point while a deal is forming, the listing agent can pull a provisional net-to-seller sheet to see what the seller would clear. The sheet response carries the `listing_id`, the `basis_price_cents` it was computed on, the `total_commission_cents` deducted, and the resulting `net_to_seller_cents`. There are two variants of the net-to-seller calculation that differ only in their price basis.

The **provisional** variant is what the net-sheet read returns while the listing is `ACTIVE` or `UNDER_CONTRACT`. When the listing has an `ACCEPTED` offer (i.e. it is `UNDER_CONTRACT`), the price basis is that accepted offer's `current_price_cents` (its frozen `effective_price_cents`); otherwise the basis is the *leading* live offer's `current_price_cents` — the highest `current_price_cents` among the listing's live offers, breaking ties in favor of the earliest-created offer. If the listing has no live offer and no accepted offer, all three computed fields are null: `basis_price_cents`, `total_commission_cents`, and `net_to_seller_cents` (the `listing_id` is still echoed). The **final** variant is computed at close and recorded; its price basis is the accepted offer's frozen `effective_price_cents`, which can differ from any provisional leading-offer basis because counters may have moved the number after the net-sheet was last read. In both variants the arithmetic is the same: the total commission is the basis price multiplied by the listing's `total_commission_pct`, rounded half up to whole cents, and the net to the seller is the basis price minus that total commission minus a seller-concession amount that is currently fixed at 0 cents. Only the commission product is rounded; the subtraction is exact.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or append a new distinct record to a collection (creating a brokerage, agent, buyer, listing, lockbox, showing, offer, or counter round) return `201 Created`. Operations that modify or transition an existing resource, and all read operations, return `200 OK`. The table below lists the surface; the request body, response shape, and side effects of each operation must be reconstructed from the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brokerages` | Create a brokerage | Anonymous |
| GET | `/brokerages/{id}` | Get a brokerage | Anonymous, ListingAgent, BuyerAgent |
| POST | `/agents` | Register an agent under a brokerage | Anonymous |
| GET | `/agents/{id}` | Get an agent | Anonymous, ListingAgent, BuyerAgent |
| GET | `/brokerages/{id}/agents` | List a brokerage's agents | Anonymous, ListingAgent, BuyerAgent |
| POST | `/agents/{id}/suspend` | Suspend an agent | Anonymous |
| POST | `/buyers` | Register a buyer | Anonymous, BuyerAgent |
| GET | `/buyers/{id}` | Get a buyer | Anonymous, ListingAgent, BuyerAgent |
| GET | `/agents/{id}/buyers` | List buyers represented by an agent | Anonymous, ListingAgent, BuyerAgent |
| POST | `/listings` | Create a listing (DRAFT) | ListingAgent |
| GET | `/listings/{id}` | Get a listing | Anonymous, ListingAgent, BuyerAgent |
| GET | `/listings` | List listings (filter by listing_agent_id, status) | Anonymous, ListingAgent, BuyerAgent |
| POST | `/listings/{id}/activate` | Activate a listing (DRAFT → ACTIVE) | ListingAgent |
| POST | `/listings/{id}/withdraw` | Withdraw a listing | ListingAgent |
| POST | `/listings/{id}/close` | Close a listing (PENDING → CLOSED) | ListingAgent |
| GET | `/listings/{id}/net-sheet` | Provisional net-to-seller | ListingAgent |
| GET | `/listings/{id}/commission-ledger` | Get a closed listing's commission ledger | Anonymous, ListingAgent, BuyerAgent |
| POST | `/listings/{id}/lockboxes` | Install a lockbox | ListingAgent |
| GET | `/lockboxes/{id}` | Get a lockbox | Anonymous, ListingAgent, BuyerAgent |
| GET | `/listings/{id}/lockboxes` | List a listing's lockboxes | Anonymous, ListingAgent, BuyerAgent |
| POST | `/lockboxes/{id}/disable` | Disable a lockbox (INSTALLED → DISABLED) | ListingAgent |
| POST | `/lockboxes/{id}/showings` | Request a showing | BuyerAgent |
| GET | `/showings/{id}` | Get a showing appointment | Anonymous, ListingAgent, BuyerAgent |
| GET | `/lockboxes/{id}/showings` | List showings on a lockbox | Anonymous, ListingAgent, BuyerAgent |
| GET | `/showings` | List showings across lockboxes | Anonymous, ListingAgent, BuyerAgent |
| POST | `/showings/{id}/confirm` | Confirm a showing (REQUESTED → CONFIRMED) | ListingAgent |
| POST | `/showings/{id}/cancel` | Cancel a showing | BuyerAgent |
| POST | `/showings/{id}/complete` | Complete a showing (CONFIRMED → COMPLETED) | ListingAgent |
| POST | `/showings/{id}/no-show` | Mark a showing no-show (CONFIRMED → NO_SHOW) | ListingAgent |
| POST | `/listings/{id}/offers` | Submit an offer on a listing | BuyerAgent |
| GET | `/offers/{id}` | Get an offer | Anonymous, ListingAgent, BuyerAgent |
| GET | `/listings/{id}/offers` | List offers on a listing | Anonymous, ListingAgent, BuyerAgent |
| GET | `/offers` | List offers across listings | Anonymous, ListingAgent, BuyerAgent |
| POST | `/offers/{id}/counter` | Append a counter round | ListingAgent, BuyerAgent |
| GET | `/offers/{id}/counters` | List an offer's counter rounds | Anonymous, ListingAgent, BuyerAgent |
| GET | `/counters/{id}` | Get a single counter round | Anonymous, ListingAgent, BuyerAgent |
| GET | `/counters` | List counter rounds (filter by offer_id, actor_agent_id, by_party) | Anonymous, ListingAgent, BuyerAgent |
| POST | `/offers/{id}/accept` | Accept an offer (OCC-guarded) | ListingAgent, BuyerAgent |
| POST | `/offers/{id}/reject` | Reject an offer | ListingAgent, BuyerAgent |
| POST | `/offers/{id}/withdraw` | Withdraw an offer | BuyerAgent |
| GET | `/contingencies/{id}` | Get a contingency | Anonymous, ListingAgent, BuyerAgent |
| GET | `/offers/{id}/contingencies` | List contingencies on an offer | Anonymous, ListingAgent, BuyerAgent |
| POST | `/contingencies/{id}/resolve` | Resolve a contingency (runs the gate) | BuyerAgent |
| POST | `/contingencies/{id}/waive` | Waive a contingency (PENDING → WAIVED) | BuyerAgent |
| POST | `/contingencies/{id}/fail` | Fail a contingency (PENDING → FAILED) | BuyerAgent |
| POST | `/_clock/set` | Set the server clock (test-driving) | Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_LISTING_AGENT` | 403 |
| `ERR_NOT_BUYER_AGENT` | 403 |
| `ERR_DUAL_AGENCY_FORBIDDEN` | 422 |
| `ERR_AGENT_SUSPENDED` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_YOUR_TURN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OVER_BUDGET` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_NO_LOCKBOX` | 409 |
| `ERR_LOCKBOX_DISABLED` | 409 |
| `ERR_LOCKBOX_HAS_SHOWINGS` | 409 |
| `ERR_SHOWING_CONFLICT` | 409 |
| `ERR_BAD_TIME_WINDOW` | 422 |
| `ERR_SHOWING_NOT_OVER` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_VALIDATION` | 422 |
