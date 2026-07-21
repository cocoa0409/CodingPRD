# Business Brokerage API — Product Requirements Document

## 1. Introduction

The Business Brokerage API is the transactional backbone for a main-street mergers-and-acquisitions marketplace, where advisors take privately held small businesses to market and shepherd them through to a closed sale. A single deal spans a long, multi-party journey: a broker lists a business and prices it through a Confidential Information Memorandum, qualified buyers sign confidentiality agreements to access a due-diligence data room, offers are negotiated through rounds of letters of intent, an SBA lender underwrites the acquisition financing, and an escrow agent finally settles the funds and pays commission. Each of these participants sees only their slice of the transaction, yet the platform must keep every party's view mutually consistent as money is committed, encumbered, released, and ultimately disbursed.

This document specifies the complete behavioral contract for that platform. It governs the entity lifecycles (listings, valuations, deals, offers, loans, escrow), the conserved financial quantities that must never drift (buyer committed capital, escrowed trust balances, broker commission ledgers), and the cascading side effects that ripple across aggregates whenever a deal advances or collapses. Because the negotiation is inherently concurrent — several buyers may pursue the same business at once — the API also defines the concurrency-control and serialization rules that decide which offer wins and how losing parties are unwound. The intent is a lossless specification: every calculation, threshold, state guard, and cascade an implementer must build is described here in prose.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply uniformly across every endpoint. All resources are mounted under the `/brokerage` path prefix.

### 2.1. Participants and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which they are acting. A request that omits either header, or that carries a value the server cannot recognize as valid, is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `Broker`, `Seller`, `Buyer`, `Lender`, and `EscrowAgent`.

Three of these roles are **entity-backed**, meaning `X-User-ID` is the identifier of a persisted actor and is used for ownership checks:

- When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker`; ownership checks on any resource that references a broker compare the resource's `broker_id` to `X-User-ID` (a broker owns the listings and deals they created).
- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; the seller owns the listing side of a deal, and ownership checks on offer-side actions compare the `seller_id` of the listing behind the offer to `X-User-ID`.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; a buyer owns the deals they pursue and signs NDAs under their own identity, so ownership checks compare the relevant `buyer_id` to `X-User-ID`.

The remaining three roles are **opaque operator identities**. When `X-User-Role` is `PlatformAdmin`, `Lender`, or `EscrowAgent`, `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may accept and act on it but does not compare it to any entity's `id`. `PlatformAdmin` onboards the actors (brokers, sellers, buyers) but has no deal-flow authority; `Lender` decides and finalizes loan applications; `EscrowAgent` opens and closes escrow. When an entity-backed actor targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. All six roles may call every read (GET) endpoint.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter is the number of records to skip and defaults to 0 with a minimum of 0.

Unless a specific endpoint states otherwise, all list responses are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the query before the page window is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Resource Identity and Audit Fields

Every persisted resource in the system carries a standard set of server-managed properties:

- `id` — a server-minted UUID string with no type prefix, unique across the resource's collection.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at `1` on creation and increments by one on every mutation of the resource.

All entity types in this system — `Broker`, `Seller`, `Buyer`, `Listing`, `CIM`, `NDA`, `DataRoomDocument`, `ManagementMeeting`, `Deal`, `LOI`, `SBALoanApplication`, and `EscrowAccount` — carry all four of these fields. Whenever a computed field is recalculated on a resource (for example, when a buyer's capital ledger shifts or a deal's commission is populated), that recalculation is itself a mutation: it refreshes `updated_at` and increments `version`.

### 2.5. Nested Path Resolution

Many endpoints address a resource nested under a parent (for example, the CIMs, NDAs, documents, and meetings under a listing, or the LOIs, loan applications, and escrow accounts under a deal). When a path contains more than one resource identifier, the server validates existence left to right and rejects the request at the first identifier that does not resolve, returning the not-found error specific to that resource type. A request for an LOI under a non-existent deal, for instance, fails with `ERR_DEAL_NOT_FOUND` before the LOI is ever looked up. The full set of not-found codes is `ERR_BROKER_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CIM_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_LOI_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, and `ERR_ESCROW_NOT_FOUND`.

### 2.6. Validation Ordering and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is:

1. **Authentication** — headers present and valid, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for this operation per Section 2.1, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — all path resource identifiers resolve, validated left to right per Section 2.5, else the appropriate not-found error (404).
4. **Ownership** — for entity-backed actors, `X-User-ID` owns the target resource, else `ERR_NOT_RESOURCE_OWNER` (403).
5. **State** — the target resource is in a status that admits the requested transition, else the relevant state error (409), such as `ERR_DEAL_NOT_QUALIFIED`, `ERR_LOI_INVALID_STATE`, `ERR_CIM_INVALID_STATE`, `ERR_ESCROW_INVALID_STATE`, `ERR_LOAN_INVALID_STATE`, or `ERR_ESCROW_NOT_FUNDED`. A deal-lifecycle state-guard failure that has no more specific code — a `qualify` (deal not `PROSPECT`), `open-diligence` (deal not `UNDER_LOI`), `enter-financing` (deal not `DUE_DILIGENCE`), open-`escrow` (deal not `FINANCING`), `withdraw` (deal already `CLOSED` or `WITHDRAWN`), or `record-earnout-period` (deal not `CLOSED`) call against a deal in the wrong status, as well as a listing `activate` (listing not `DRAFT`) or `withdraw` (listing not `DRAFT` or `ACTIVE`) call in the wrong status — is rejected with `ERR_DEAL_INVALID_STATE` (409).
6. **Business referential** — a required related entity exists and is in the right state (409), such as `ERR_NDA_REQUIRED`, `ERR_CIM_NOT_PUBLISHED`, or `ERR_FINANCING_NOT_APPROVED`.
7. **Business constraint** — structural validity such as interval ordering and data-room non-emptiness (409), such as `ERR_INVALID_INTERVAL` or `ERR_DATA_ROOM_EMPTY`.
8. **Business temporal** — interval-occupation conflicts (409), such as `ERR_LISTING_PERIOD_OVERLAP` or `ERR_MEETING_SLOT_CONFLICT`.
9. **Business fiscal** — capital, capacity, and deposit sufficiency (402), such as `ERR_INSUFFICIENT_FUNDS` or `ERR_DEPOSIT_TOO_LOW`.

A malformed body, a missing required field, or a bad enum value is rejected with `ERR_VALIDATION` (400). Input that is well-formed but semantically invalid — for example, a conditional loan approval submitted without an approved amount — is rejected with `ERR_INVALID_REQUEST` (422).

### 2.7. Cross-Entity State Propagation

This platform is defined by cascades: a single operation frequently mutates several entities across aggregate boundaries, and each such mutation independently refreshes the affected resource's `updated_at` and increments its `version`. When a deal advances to an escrow-bearing stage, the underlying listing advances with it; when a deal collapses, the listing is re-opened and any encumbered buyer capital is released. When a seller accepts one buyer's offer, every rival deal still competing for the same listing is automatically withdrawn. The server performs these transitions on its own initiative — no explicit client request is issued against each downstream resource. The precise cascade rules are defined alongside the workflows that trigger them in Section 3; this subsection establishes only the general principle that parent and child states are kept mutually consistent at all times, and that the server never leaves a listing, deal, offer, loan, or escrow account in a state that contradicts its relatives.

### 2.8. The Buyer Capital Ledger

Each `Buyer` carries a conserved, three-part capital picture that the system maintains automatically and exposes on the buyer record. A buyer is onboarded with a declared `proof_of_funds_cents` (verified liquid funds) and a declared `net_worth_cents`. Against this, the system tracks two encumbrances. The first, `committed_capital_cents`, is the sum of the earnest deposits across the buyer's non-terminal offers — that is, offers whose status is `SUBMITTED`, `COUNTERED`, or `ACCEPTED`. It rises when an offer is submitted and falls when an offer is withdrawn or rejected. The second, `escrowed_cents`, is the sum of the trust balances across the buyer's escrow accounts whose status is `OPENED` or `FUNDED`; it rises on an escrow deposit and falls back to zero when an escrow account is cancelled and refunded. From these, the system derives a read-only `available_capital_cents`, defined as `proof_of_funds_cents` minus `committed_capital_cents` minus `escrowed_cents`. This available figure is the balance every fiscal check draws against, and the invariant is that committed and escrowed amounts always reconcile exactly to the live offers and escrow accounts that gave rise to them — no encumbrance is ever stranded after the underlying commitment ends.

### 2.9. The Broker Commission Ledger

Each `Broker` carries an `accrued_commission_cents` running total, initialized to zero at onboarding. It represents the sum of the final commissions earned across that broker's closed deals. It is a happy-path ledger: it increases by the final commission amount at the moment an escrow closes and is not decremented under normal operation. A broker is onboarded with a `firm_name` and a `license_number`.

### 2.10. Monetary Precision and Rounding

All monetary quantities are integer cents. Wherever a calculation produces a fractional cent — for example, when a percentage or a multiple is applied — the result is resolved using the round-half-up method to the nearest whole cent before it is stored or compared. Each calculation in Section 3 specifies the exact point at which rounding is applied; where a formula rounds an intermediate quantity, that intermediate is rounded before it participates in any subsequent subtraction or accumulation, rather than rounding only the final result. All threshold comparisons in the fiscal rules are inclusive unless stated otherwise.

### 2.11. Deal Versioning and Optimistic Concurrency Control

Because a buyer may re-offer on a deal and because a deal's version advances as offers move through it, offer submission is guarded by optimistic concurrency control on the deal. Submitting a new offer against a deal requires the non-optional field `expected_deal_version`, carrying the deal `version` the buyer last observed. If that value does not match the deal's current `version` — because the deal has advanced since the buyer read it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a buyer from superseding an offer they never saw: a fresh offer legitimately supersedes any live offer on the deal, so the stale-version guard is what stops a second, blind create from silently overwriting an offer the buyer was unaware of. A successful offer submission itself increments the deal's `version` by one. No other endpoint takes a version field; offer submission is the only version-guarded write.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Participants

Before any transaction can begin, the actors must exist. A `PlatformAdmin` onboards a `Broker` by supplying the `firm_name` and `license_number`; the new broker's `accrued_commission_cents` starts at zero. A `PlatformAdmin` onboards a `Seller` with a `full_name` and `email`. A `PlatformAdmin` onboards a `Buyer` with a `full_name`, `email`, `proof_of_funds_cents`, and `net_worth_cents`; the buyer's `committed_capital_cents` and `escrowed_cents` both start at zero, and the derived `available_capital_cents` therefore starts equal to `proof_of_funds_cents`. Broker and buyer records — including the broker's accrued-commission total and the buyer's full capital ledger — are readable by any authenticated role.

### 3.2. Listing a Business and Pricing It

A `Broker` brings a business to market by creating a **Listing**. The creation payload carries the `seller_id` of the owner, the `business_name`, an `industry_code`, the trailing financials (`annual_sde_cents` for seller's discretionary earnings and `annual_revenue_cents` for revenue), the tangible-asset figures (`ffe_value_cents` for furniture, fixtures and equipment, and `inventory_value_cents`), the `industry_multiple` used to capitalize earnings, the `asking_price_cents`, and the exclusive-engagement window bounded by `exclusive_start_date` and `exclusive_end_date`. The listing's `broker_id` is taken from `X-User-ID`, and the listing opens in `DRAFT`. The engagement window is a half-open interval running from `exclusive_start_date` up to but not including `exclusive_end_date`; the end must be strictly after the start, and a violation is rejected with `ERR_INVALID_INTERVAL`. Exclusivity is enforced per seller: a new listing whose window overlaps that of another non-`WITHDRAWN` listing for the same seller is rejected with `ERR_LISTING_PERIOD_OVERLAP`. Because the interval is half-open, two windows that merely touch — where one ends exactly when the next begins — do not overlap and are both allowed.

Pricing runs through a **Confidential Information Memorandum (CIM)**, a valuation document a broker creates against a listing. Each CIM is created in `DRAFT` and pins a `valuation_method`, which is one of `SDE_MULTIPLE` or `ASSET_BASED`. Publishing a CIM transitions it from `DRAFT` to `PUBLISHED` and, at that moment, computes its read-only `recommended_price_cents` from the chosen method against the parent listing's inputs. Under `SDE_MULTIPLE`, the recommended price is the listing's `annual_sde_cents` multiplied by its `industry_multiple`, rounded half up to whole cents — an earnings-capitalization value. Under `ASSET_BASED`, the recommended price is the sum of the listing's `ffe_value_cents` and `inventory_value_cents` — the tangible net asset value, with goodwill excluded — and for identical listing inputs this deliberately diverges from the `SDE_MULTIPLE` figure. Publishing is only permitted on a CIM in `DRAFT`; a publish attempt against a CIM that has already been published is rejected with `ERR_CIM_INVALID_STATE`.

A listing goes live only after it has been priced. **Activation** by the listing's broker transitions the listing from `DRAFT` to `ACTIVE`, and it requires that the listing already have at least one CIM in `PUBLISHED` status; otherwise activation is rejected with `ERR_CIM_NOT_PUBLISHED`. Once `ACTIVE`, the listing is markable and its confidential materials become NDA-signable. A broker may **withdraw** a listing to `WITHDRAWN` from either `DRAFT` or `ACTIVE`; withdrawal from `ACTIVE` is blocked with `ERR_LISTING_HAS_ACTIVE_ESCROW` if any deal on the listing is currently `IN_ESCROW`. Beyond these broker-initiated moves, a listing's status is driven automatically by the deals beneath it: it advances from `ACTIVE` to `UNDER_LOI` when an offer is accepted, from `UNDER_LOI` to `IN_ESCROW` when the winning deal opens escrow, and from `IN_ESCROW` to the terminal `SOLD` when that escrow closes. It is also re-opened to `ACTIVE` — from `UNDER_LOI` when the sole active deal is withdrawn before escrow (provided no deal on the listing is `IN_ESCROW` or `CLOSED`), or from `IN_ESCROW` when the winning deal is withdrawn out of escrow. These automatic listing moves are detailed alongside the deal and escrow workflows that cause them.

### 3.3. Confidentiality, the Data Room, and Management Meetings

To see a business's confidential materials, a buyer must first sign a confidentiality agreement. A `Buyer` signs an **NDA** against an `ACTIVE` listing; the NDA's `buyer_id` is taken from `X-User-ID`, its `listing_id` is the listing being unlocked, and it is created directly in the terminal `SIGNED` status. Signing against a listing that is not `ACTIVE` is rejected with `ERR_LISTING_NOT_ACTIVE`. An NDA is the key that unlocks three later gates on that listing.

Within the data room, a `Broker` or `Seller` uploads **DataRoomDocument** records, each carrying a `title` and a `doc_type` drawn from `FINANCIALS`, `LEASE`, `TAX_RETURN`, `LICENSES`, or `OTHER`. When a buyer lists the documents on a listing, the server first confirms the buyer holds a `SIGNED` NDA on that listing; a buyer without one is refused with `ERR_NDA_REQUIRED`.

A `Broker` schedules a **ManagementMeeting** between a buyer and the seller's time by supplying the `buyer_id`, a `start_at`, and an `end_at`; the meeting is created in the terminal `SCHEDULED` status against the listing whose seller time is being contended. Scheduling requires that the named buyer hold a `SIGNED` NDA on the listing, again enforced with `ERR_NDA_REQUIRED`. The `end_at` must be strictly after the `start_at`, or the request fails with `ERR_INVALID_INTERVAL`. Meeting intervals are treated as closed on both ends, and they must be buffer-separated: a new scheduled meeting is rejected with `ERR_MEETING_SLOT_CONFLICT` when the gap between it and any existing scheduled meeting on the same listing is strictly less than thirty minutes. A gap of exactly thirty minutes is permitted — the buffer boundary is inclusive of the thirty-minute separation and exclusive only of gaps narrower than it.

### 3.4. Opening and Qualifying a Deal

A **Deal** represents one buyer's pursuit of one listing. A `Broker` opens a deal by supplying the `listing_id` being pursued and the `buyer_id` pursuing it; the deal's `broker_id` is taken from `X-User-ID`, and it opens in `PROSPECT`. Deals may be listed and filtered by their `listing_id`, `buyer_id`, `broker_id`, and `status`.

Before a buyer can make an offer, the broker must **qualify** the deal, moving it from `PROSPECT` to `QUALIFIED`. Qualification runs three gates in order. First, a `SIGNED` NDA must exist matching both the deal's listing and the deal's buyer, or the request is refused with `ERR_NDA_REQUIRED`. Second, the buyer's `proof_of_funds_cents` must be at least the required down payment, which is ten percent of the listing's `asking_price_cents`, rounded half up; falling short is rejected with `ERR_INSUFFICIENT_FUNDS`. Third, the buyer's qualification capacity must be at least the listing's `asking_price_cents`, again rejected with `ERR_INSUFFICIENT_FUNDS` when short. The qualification capacity is the smallest of three ceilings: the buyer's `proof_of_funds_cents` divided by ten percent (that is, leveraged tenfold on cash) rounded half up, the buyer's `net_worth_cents` multiplied by two rounded half up, and a program cap of five million dollars (500,000,000 cents). All three comparisons are inclusive — meeting a threshold exactly is sufficient.

### 3.5. The Letter-of-Intent Negotiation

Offers on a qualified deal take the form of a **Letter of Intent (LOI)**, and the negotiation between buyer and seller is an iterative loop. Every LOI belongs to its deal, recorded through the offer's `deal_id`. A `Buyer` submits an LOI, which is created directly in `SUBMITTED` with its `round_number` set to 1. The submission payload carries the `offer_price_cents`, the `earnest_deposit_cents` the buyer will encumber while the offer is live, the total `earnout_amount_cents` proposed, the number of `earnout_periods` (which must be at least one), a `financing_contingency` boolean indicating whether the offer is contingent on SBA financing (defaulting to true), and the `expected_deal_version` for the concurrency guard described in Section 2.11. Submission is admitted only when the deal is in `QUALIFIED`; otherwise it is rejected with `ERR_DEAL_NOT_QUALIFIED`. The stale-version guard is checked next, rejecting a mismatched `expected_deal_version` with `ERR_STALE_VERSION`. Finally, the buyer's `available_capital_cents` must be at least the `earnest_deposit_cents`, or the submission is rejected with `ERR_INSUFFICIENT_FUNDS`. On success, any existing non-terminal LOI on the deal is superseded — driven to `WITHDRAWN`, which releases its own earnest — the new offer's earnest is added to the buyer's `committed_capital_cents`, and the deal's `version` increments by one.

Once an offer is on the table, the seller may respond. A `Seller` **counters** an offer that is in `SUBMITTED`, recording a `counter_price_cents`, incrementing the `round_number` by one, and moving the offer to `COUNTERED`; a counter attempted from any other status is rejected with `ERR_LOI_INVALID_STATE`. The buyer may then **revise** an offer that is in `COUNTERED`, supplying an updated `offer_price_cents` and `earnest_deposit_cents`; this clears the `counter_price_cents`, increments the `round_number` by one, and returns the offer to `SUBMITTED`. A revise is admitted only from `COUNTERED` (else `ERR_LOI_INVALID_STATE`), and the buyer must have enough `available_capital_cents` to cover the increase in earnest — that is, the new `earnest_deposit_cents` minus the old — or it is rejected with `ERR_INSUFFICIENT_FUNDS`. The buyer's `committed_capital_cents` is then adjusted by exactly that difference, whether positive or negative. This `SUBMITTED ↔ COUNTERED` cycle may repeat for as many rounds as the parties need.

The loop terminates in one of three ways. A `Seller` **accepts** an offer that is in `SUBMITTED`, provided the deal is still `QUALIFIED` and the listing is still `ACTIVE`; if either the deal is no longer `QUALIFIED` or the listing is no longer `ACTIVE` the accept is rejected with `ERR_LISTING_NOT_ACTIVE`, and an accept from a non-`SUBMITTED` offer is rejected with `ERR_LOI_INVALID_STATE`. Acceptance drives the offer to the terminal `ACCEPTED` and cascades into the deal (Section 3.6). A `Seller` may instead **reject** an offer that is in `SUBMITTED` or `COUNTERED`, moving it to the terminal `REJECTED` and releasing its earnest back to the buyer by subtracting the `earnest_deposit_cents` from `committed_capital_cents`. Finally, a `Buyer` may **withdraw** their own offer while it is in `SUBMITTED` or `COUNTERED`, moving it to the terminal `WITHDRAWN` and likewise releasing the earnest from `committed_capital_cents`; a withdraw from any other status is rejected with `ERR_LOI_INVALID_STATE`. An `ACCEPTED` offer can still be driven to `WITHDRAWN` automatically when its owning deal is withdrawn, which also releases the encumbered earnest.

### 3.6. Acceptance, Diligence, and the Race Among Rivals

Accepting an offer is the pivot of the whole transaction. When the seller accepts, the offer becomes `ACCEPTED` and the deal advances from `QUALIFIED` to `UNDER_LOI`. At that instant the deal captures a snapshot of the winning terms: its `accepted_loi_id` is set to the accepted offer, its `accepted_price_cents` is copied from the offer's `offer_price_cents`, its `earnout_total_cents` and `earnout_periods` are copied from the offer, and its `earnout_baseline_sde_cents` is snapshotted from the listing's `annual_sde_cents` to serve as the denominator of later earnout performance. The deal's `provisional_commission_cents` is computed at this moment as the brokerage commission on the `accepted_price_cents` (the commission ladder is defined in Section 3.8).

Acceptance then fans outward. The listing advances from `ACTIVE` to `UNDER_LOI`, and that listing transition in turn withdraws the competition: every **other** deal on the same listing whose status is `PROSPECT` or `QUALIFIED` is automatically driven to `WITHDRAWN`. This is the serialization point of the marketplace — the first accepted offer wins the listing, and rival pursuits that had not yet secured an accepted offer are unwound in the same operation.

With an accepted offer in hand, the broker moves the deal into due diligence: **opening diligence** advances the deal from `UNDER_LOI` to `DUE_DILIGENCE`, but only if the listing's data room holds at least one document; an empty data room blocks the transition with `ERR_DATA_ROOM_EMPTY`. The broker then moves the deal from `DUE_DILIGENCE` to `FINANCING` by **entering financing**, which carries no additional precondition.

### 3.7. SBA Financing

Acquisition financing is underwritten as an **SBALoanApplication** on the deal. A `Buyer` submits an application carrying the `requested_amount_cents`; it is created in `SUBMITTED`. A `Lender` then renders a decision, supplying an `outcome` and optionally a `decision_reason` recorded with the decision. From `SUBMITTED`, three branches are possible. An `APPROVED` decision sets the application's `approved_amount_cents` equal to the `requested_amount_cents`, moves it to `APPROVED`, and unlocks escrow. A `CONDITIONALLY_APPROVED` decision requires an `approved_amount_cents` supplied in the body — its absence is rejected with `ERR_INVALID_REQUEST` — sets `approved_amount_cents` to that supplied value, and moves the application to `CONDITIONALLY_APPROVED`, a status that does **not** unlock escrow. A `DECLINED` decision moves it to the terminal `DECLINED`. A decision attempted against an application that is no longer in `SUBMITTED` is rejected with `ERR_LOAN_INVALID_STATE`.

A conditional approval must still be resolved. From `CONDITIONALLY_APPROVED`, a `Lender` **finalizes the conditions** with an `outcome` of either `APPROVED` — which moves the application to `APPROVED` and unlocks escrow — or `DECLINED`, which moves it to the terminal `DECLINED`. Finalizing an application that is not in `CONDITIONALLY_APPROVED` is rejected with `ERR_LOAN_INVALID_STATE`. Only an application that has reached `APPROVED` (whether directly or through a finalized conditional approval) satisfies the financing gate for opening escrow.

### 3.8. Escrow, Closing, Commission, and Seller Proceeds

Escrow is opened by an `EscrowAgent` against a deal in `FINANCING`. The open payload carries the `closing_price_cents` — the final agreed price, which may re-trade away from the accepted offer price — and the `required_deposit_cents` the buyer must fund. Opening requires that the deal have an `SBALoanApplication` in `APPROVED`; without one, the open is rejected with `ERR_FINANCING_NOT_APPROVED`. On success the **EscrowAccount** is created in `OPENED`, the deal advances from `FINANCING` to `IN_ESCROW`, and the listing cascades from `UNDER_LOI` to `IN_ESCROW`.

The `Buyer` then **deposits** into escrow, supplying an `amount_cents`. A deposit is admitted only when the account is in `OPENED`, else `ERR_ESCROW_INVALID_STATE`, and the `amount_cents` must be at least the account's `required_deposit_cents`, or it is rejected with `ERR_DEPOSIT_TOO_LOW`. On success the amount is added to the account's `balance_cents`, the same amount is added to the buyer's `escrowed_cents`, and the account moves from `OPENED` to `FUNDED`.

Closing is performed by an `EscrowAgent` against a `FUNDED` account; a close attempted on an account that is not `FUNDED` is rejected with `ERR_ESCROW_NOT_FUNDED`. Closing moves the account to the terminal `CLOSED` and drives the deal from `IN_ESCROW` to the terminal `CLOSED`. At close, three financial results are computed and one cascade fires. The deal's `final_commission_cents` is computed as the brokerage commission on the escrow's `closing_price_cents`; this can differ from the provisional commission whenever the closing price re-traded away from the accepted price. The deal's `seller_net_proceeds_cents` is computed by the settlement waterfall below. The broker's `accrued_commission_cents` is increased by the `final_commission_cents`. And the listing cascades from `IN_ESCROW` to the terminal `SOLD`.

The **brokerage commission** is a marginal Lehman ladder applied to a price base in cents, using tiers each one million dollars (100,000,000 cents) wide. The first one-million-dollar slice of the base is charged at five percent, the second at four percent, the third at three percent, and the fourth at two percent; any portion of the base beyond four million dollars is charged at a flat one percent. Each slice's charge is the applicable rate applied only to the amount of the base that falls within that slice, and the charges are summed across the slices. A base of exactly one million dollars therefore consumes only the first tier. The summed commission is rounded half up to whole cents, and then floored at a minimum of fifteen thousand dollars (1,500,000 cents): if the computed commission is below that minimum, the minimum is charged instead. This same ladder produces the provisional commission at acceptance (on the `accepted_price_cents`) and the final commission at close (on the `closing_price_cents`).

The **settlement waterfall** for `seller_net_proceeds_cents` is evaluated in a pinned order off the escrow's `closing_price_cents`. First, the final commission is computed on the closing price by the ladder above. Second, an escrow fee is computed as one percent of the closing price, rounded half up. Third, the earnout holdback is the deal's `earnout_total_cents`. The seller's net proceeds are then the closing price minus the final commission, minus the rounded escrow fee, minus the earnout holdback.

### 3.9. Earnout Performance and Payments

After a deal closes, its earnout is paid out over the agreed measurement periods. A `Broker` **records an earnout period** by supplying that period's `actual_sde_cents`. For each recorded period, the system computes a performance ratio as the period's `actual_sde_cents` divided by the deal's `earnout_baseline_sde_cents`, clamped to lie between zero and a ceiling of one-and-one-half (so a wildly overperforming period is capped and a negative or zero result floors at zero). The period's payment is the deal's `earnout_total_cents` multiplied by that clamped performance ratio, divided by the deal's `earnout_periods`, and rounded half up to whole cents. That already-rounded per-period payment is then added to the deal's accumulated `earnout_paid_cents`. The rounding is applied to each period's payment before it is accumulated — the running total is a sum of rounded per-period figures, never a single rounding of an aggregate.

### 3.10. Withdrawing a Deal and Unwinding Its Commitments

A `Broker` may **withdraw** a deal to the terminal `WITHDRAWN`, optionally recording a `reason`, and the cascade depends on how far the deal had progressed. From `PROSPECT` or `QUALIFIED`, withdrawal is straightforward: the deal moves to `WITHDRAWN`, and from `QUALIFIED` any non-terminal offer on the deal is driven to `WITHDRAWN`, which releases that offer's earnest from the buyer's `committed_capital_cents`. A deal may also be withdrawn automatically as a rival when another buyer's offer is accepted on the same listing, as described in Section 3.6.

From the mid-pipeline states `UNDER_LOI`, `DUE_DILIGENCE`, or `FINANCING`, withdrawal drives the deal's accepted offer to `WITHDRAWN` (releasing its `committed_capital_cents`) and re-opens the listing from `UNDER_LOI` back to `ACTIVE`, restoring its availability, before the deal itself becomes `WITHDRAWN`.

From `IN_ESCROW`, withdrawal is permitted only while the escrow account is not yet `CLOSED`; if the escrow has already closed, the withdrawal is refused with `ERR_ESCROW_ALREADY_CLOSED`. When permitted, the escrow account is cancelled — an `OPENED` or `FUNDED` account moves to `CANCELLED`, its held `balance_cents` is released back to the buyer, that released amount is subtracted from the buyer's `escrowed_cents`, and the account's `balance_cents` is reset to zero. The accepted offer is driven to `WITHDRAWN` (releasing its `committed_capital_cents`), the listing is re-opened from `IN_ESCROW` back to `ACTIVE`, and the deal becomes `WITHDRAWN`. Through every one of these unwind paths the conservation invariants hold: no earnest remains committed and no escrowed cash remains held once the commitment that gave rise to it has ended.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. All paths are mounted under the `/brokerage` prefix. Every GET endpoint is authorized for all six roles (`PlatformAdmin`, `Broker`, `Seller`, `Buyer`, `Lender`, `EscrowAgent`), shown below as "All roles".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brokerage/brokers` | Onboard a broker | PlatformAdmin |
| POST | `/brokerage/sellers` | Onboard a seller | PlatformAdmin |
| POST | `/brokerage/buyers` | Onboard a buyer | PlatformAdmin |
| GET | `/brokerage/brokers/{id}` | Get a broker (incl. accrued commission) | All roles |
| GET | `/brokerage/buyers/{id}` | Get a buyer (incl. capital ledger) | All roles |
| POST | `/brokerage/listings` | Create a listing | Broker |
| GET | `/brokerage/listings` | List/filter listings | All roles |
| GET | `/brokerage/listings/{id}` | Get a listing | All roles |
| POST | `/brokerage/listings/{id}/activate` | Activate a listing | Broker |
| POST | `/brokerage/listings/{id}/withdraw` | Withdraw a listing | Broker |
| POST | `/brokerage/listings/{id}/cims` | Create a CIM draft | Broker |
| GET | `/brokerage/listings/{id}/cims` | List CIMs for a listing | All roles |
| POST | `/brokerage/cims/{id}/publish` | Publish a CIM | Broker |
| POST | `/brokerage/listings/{id}/ndas` | Buyer signs an NDA | Buyer |
| GET | `/brokerage/listings/{id}/ndas` | List NDAs on a listing | All roles |
| GET | `/brokerage/buyers/{id}/ndas` | List NDAs a buyer has signed | All roles |
| POST | `/brokerage/listings/{id}/documents` | Upload a data-room document | Broker, Seller |
| GET | `/brokerage/listings/{id}/documents` | List data-room documents | All roles |
| POST | `/brokerage/listings/{id}/meetings` | Schedule a management meeting | Broker |
| GET | `/brokerage/listings/{id}/meetings` | List meetings on a listing | All roles |
| GET | `/brokerage/buyers/{id}/meetings` | List meetings a buyer attends | All roles |
| POST | `/brokerage/deals` | Open a deal | Broker |
| GET | `/brokerage/deals` | List/filter deals | All roles |
| GET | `/brokerage/deals/{id}` | Get a deal | All roles |
| POST | `/brokerage/deals/{id}/qualify` | Qualify the buyer on a deal | Broker |
| POST | `/brokerage/deals/{id}/open-diligence` | Open due diligence | Broker |
| POST | `/brokerage/deals/{id}/enter-financing` | Move a deal to financing | Broker |
| POST | `/brokerage/deals/{id}/withdraw` | Withdraw a deal (cascades) | Broker |
| POST | `/brokerage/deals/{id}/record-earnout-period` | Record and pay one earnout period | Broker |
| POST | `/brokerage/deals/{id}/lois` | Submit an LOI | Buyer |
| GET | `/brokerage/deals/{id}/lois` | List LOIs on a deal | All roles |
| POST | `/brokerage/lois/{id}/counter` | Seller counters an LOI | Seller |
| POST | `/brokerage/lois/{id}/revise` | Buyer revises after a counter | Buyer |
| POST | `/brokerage/lois/{id}/accept` | Seller accepts an LOI | Seller |
| POST | `/brokerage/lois/{id}/reject` | Seller rejects an LOI | Seller |
| POST | `/brokerage/lois/{id}/withdraw` | Buyer withdraws an LOI | Buyer |
| POST | `/brokerage/deals/{id}/loan-applications` | Submit an SBA loan application | Buyer |
| GET | `/brokerage/deals/{id}/loan-applications` | List loan applications on a deal | All roles |
| POST | `/brokerage/loan-applications/{id}/decision` | Lender decides a loan application | Lender |
| POST | `/brokerage/loan-applications/{id}/finalize-conditions` | Lender resolves a conditional approval | Lender |
| POST | `/brokerage/deals/{id}/escrow` | Open escrow | EscrowAgent |
| GET | `/brokerage/deals/{id}/escrow` | List escrow accounts on a deal | All roles |
| POST | `/brokerage/escrow-accounts/{id}/deposit` | Buyer funds escrow | Buyer |
| POST | `/brokerage/escrow-accounts/{id}/close` | Close escrow (drives close cascade) | EscrowAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_INTERVAL` | 409 |
| `ERR_BROKER_NOT_FOUND` | 404 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_CIM_NOT_FOUND` | 404 |
| `ERR_DEAL_NOT_FOUND` | 404 |
| `ERR_LOI_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_ESCROW_NOT_FOUND` | 404 |
| `ERR_CIM_INVALID_STATE` | 409 |
| `ERR_CIM_NOT_PUBLISHED` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_LISTING_HAS_ACTIVE_ESCROW` | 409 |
| `ERR_LISTING_PERIOD_OVERLAP` | 409 |
| `ERR_MEETING_SLOT_CONFLICT` | 409 |
| `ERR_NDA_REQUIRED` | 409 |
| `ERR_DEAL_NOT_QUALIFIED` | 409 |
| `ERR_DATA_ROOM_EMPTY` | 409 |
| `ERR_LOI_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_FINANCING_NOT_APPROVED` | 409 |
| `ERR_ESCROW_INVALID_STATE` | 409 |
| `ERR_ESCROW_NOT_FUNDED` | 409 |
| `ERR_ESCROW_ALREADY_CLOSED` | 409 |
| `ERR_DEAL_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_DEPOSIT_TOO_LOW` | 402 |
