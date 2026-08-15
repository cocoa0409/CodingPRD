# Bareboat & Crewed Yacht Charter Brokerage API — Product Requirements Document

## 1. Introduction

Charter brokerage is a business of interlocking promises: an operator commits a yacht's calendar, a client commits funds sight unseen, and two brokers — the central agent who holds the listing and the retail broker who brings the client — split a commission only if the deal closes cleanly. Between signature and settlement lie weeks of provisioning spend against an Advance Provisioning Allowance (APA), port permits that arrive late or not at all, insurance certificates that must be verified before anyone signs, and the ever-present possibility of cancellation with its penalty arithmetic. This document specifies an API that runs that entire lifecycle as a single, auditable system of record.

The platform covers yacht listings and their availability calendars across operators, client qualification through a sailing resume, the charter request negotiation between client side and central agent, the charter agreement created at acceptance, an escrow account holding the charter fee, APA, damage deposit, and crew gratuity in separate buckets, itinerary planning with per-leg port permits, and the two ways a deal ends: completion with full settlement, or cancellation with a tiered penalty, broker commission on the retained amount, and calendar release. Throughout, the design favors explicit state machines, snapshot-on-acceptance semantics, and ledger-style escrow movements over mutable balances, so that any dispute — over money, dates, or who promised what — can be reconstructed from the record alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. The platform recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Operator`, `Client`, `RetailBroker`, and `CentralAgent`.

Role identity is resolved in one of two ways. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting Operator, and ownership checks on any resource that references an Operator — above all a yacht's `operator_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client, compared against the `client_id` carried by charter requests and agreements. When `X-User-Role` is `RetailBroker` or `CentralAgent`, `X-User-ID` is the `id` of the acting Broker, and that broker's `broker_type` must admit the declared role: `RETAIL_BROKER` or `BOTH` for the `RetailBroker` role, `CENTRAL_AGENT` or `BOTH` for the `CentralAgent` role. Deal-scoped ownership then compares the broker's `id` against the `retail_broker_id` of a request or agreement (for a retail broker) or against a yacht's `listing_central_agent_id` and an agreement's `central_agent_id` (for a central agent).

A request that is missing either header, carries a role string outside the five declared roles, presents an entity-backed `X-User-ID` that references no existing entity of the declared type, or presents a broker whose `broker_type` does not admit the declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated caller who attempts an operation not open to their role, or who violates an ownership rule — an operator touching another operator's yacht, a non-party acting on a request or agreement, an offer issued by a broker who is not the listing central agent — is rejected with `ERR_FORBIDDEN` (HTTP 403). Read access is deliberately broad: every GET endpoint in this document is available to all five roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless a more specific ordering is stated for a particular collection, all list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how much of the collection remains unread.

### 2.4. Common Resource Properties

Nearly every resource in the system carries a standard envelope of system-managed fields. The `id` is a server-minted UUID with no type prefix — never a human-chosen slug. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits; `updated_at` follows the same format and is refreshed on every mutation. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it is the linchpin of the optimistic concurrency rules in §2.10.

Two ledger-style resources are deliberately slimmer. An `EscrowMovement` and a `CommissionStatement` each carry only `id` and `created_at`: both `updated_at` and `version` are absent, because movements and statements are posted once and never modified afterward.

### 2.5. The Logical Clock

Time inside the platform is governed by a logical clock, not by wall-clock time. On server startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never silently falls back to wall-clock time afterward. A `PlatformAdmin` may advance the clock through the admin-only capability mounted at `POST /_clock/set_current_utc`, supplying the target instant in the `to_iso8601` field; the response echoes the new reading as `current_utc`. Every date-sensitive rule in this document — offer expiry, embarkation and completion gates, cancellation penalty timing, permit expiry — reads this clock and nothing else.

Setting the clock triggers one eager sweep: every port permit in `GRANTED` status whose `valid_until` date is earlier than the new clock date transitions to `EXPIRED`, and each affected itinerary leg re-evaluates its permit roll-up (§3.6), which can flip a leg from `PERMITTED` back to `PLANNED`. Offer expiry is explicitly not part of this sweep: a charter request whose offer has lapsed is transitioned to `EXPIRED` lazily, only when the client side next attempts to counter or accept it.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values are integer cents — charter fees, deposits, APA amounts, gratuities, expenses, escrow balances, and commissions alike. Wherever a calculation introduces a division or a fractional multiplication, the result is rounded half-up to whole cents, and the rounding is applied at each rounding step in the order the relevant rule pins down, never once at the end of a chain of operations. Two non-cent representations coexist with this convention: `apa_pct` is an exact decimal fraction (for example 0.30), and `retail_pct_bps` is an integer count of basis points, where 10,000 basis points make the whole. Percentages quoted in prose — "ten percent", "half" — always resolve to an exact factor applied to integer cents with round-half-up at the stated step.

### 2.7. The Charter Calendar: Half-Open Intervals and the Turnaround Buffer

Every charter, block, and validity window in the system is expressed with `YYYY-MM-DD` calendar dates. Charter intervals and availability blocks are half-open: the interval covers `start_date` up to but not including `end_date`, written as [start_date, end_date). The length of a charter in whole days — its charter days — is the simple day-count difference between `end_date` and `start_date`, and `end_date` must be strictly later than `start_date`.

Two distinct calendar rejections guard a yacht's schedule, and both are enforced at the same three moments: when an operator creates a manual availability block, when a charter request is submitted, and when an offer is accepted. A true half-open overlap — the requested interval and an `ACTIVE` block on the same yacht share at least one day — is rejected with `ERR_AVAILABILITY_CONFLICT` (HTTP 409). Even without overlap, the yard needs one full turnaround day between bookings: if the requested interval is disjoint from an `ACTIVE` block but abuts it with a gap of zero days — less than the one-day turnaround buffer — the request is rejected with `ERR_TURNAROUND_BUFFER_VIOLATION` (HTTP 409). A gap of one day or more passes the buffer check.

### 2.8. The Agreement's Two State Axes

A `CharterAgreement` carries two independent state fields. The lifecycle axis, `status`, walks from `PENDING_SIGNATURES` through `SIGNED`, `IN_PREP`, and `UNDERWAY`, and terminates in one of `COMPLETED`, `CANCELLED`, or `VOIDED`. The funds axis, `funds_status`, walks from `UNFUNDED` through `DEPOSIT_HELD` to `FULLY_FUNDED`, and terminates in `SETTLED` (after passing through `SETTLING`) or `REFUNDED` (after passing through `REFUNDING`).

The two axes evolve independently except at four pinned gates. Funding actions require the lifecycle axis to be `SIGNED`. Starting preparation requires the funds axis to be `FULLY_FUNDED`. Cancelling the agreement drives the funds axis into `REFUNDING` and ultimately `REFUNDED`. Completing the charter drives the funds axis into `SETTLING` and ultimately `SETTLED`. Away from these gates, neither axis may be inferred from the other, and implementations must track them as separate fields.

### 2.9. Cascades, Versioning, and Cross-Entity Consistency

Consistency in this system is immediate: every mutation is fully applied before its response is rendered, so the response body and any subsequent read reflect the change. Mutations frequently cascade across entity boundaries, and every cascade hop is part of the same atomic operation. Whenever a resource is mutated — directly or as a cascade hop — its `updated_at` is refreshed and its `version` increments by one. The yacht's `version`, in particular, advances on every change to its calendar: listing or delisting the yacht, creating or releasing a block, and the system-created charter block all increment it, because any of these invalidates a calendar view a client may be holding.

Two cascades dominate the design and are specified hop-by-hop in §3.8 and §3.9: the completion cascade, which reconciles the APA, releases every escrow bucket, writes the commission statement, and settles the funds axis; and the cancellation cascade, which computes the penalty, refunds the client, pays the retained amount out to operator and brokers, closes the escrow, releases the charter block, and finally cancels the source request. Escrow closure is the hinge of both cascades — downstream hops fire only when the escrow reaches `CLOSED`.

Where an endpoint path nests one resource under another (for example a yacht's availability blocks or an agreement's expenses), identifiers in the path are validated strictly left to right: the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and body-level foreign keys such as `yacht_id`, `client_id`, `listing_central_agent_id`, and `retail_broker_id` are likewise checked for existence before business rules run.

### 2.10. Optimistic Concurrency Control

Three write operations carry an explicit optimistic-concurrency guard; no other endpoint takes a version field.

First, countering an offer on a charter request requires the request body to carry `expected_charter_request_version`, holding the request `version` the caller last observed. If the request's current `version` differs — because the central agent has since posted a fresh offer with different terms, or any other write has advanced it — the counter is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the request and counter against the current version.

Second, accepting an offer requires the same `expected_charter_request_version` field with the same semantics and the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. Accepting terms the client has not observed is never legitimate: if the version has advanced since the client last read the offer, the acceptance is refused and the client must re-read before accepting.

Third, creating a manual availability block on a yacht requires `expected_yacht_version` in the request body, carrying the yacht `version` the operator last observed. A mismatch with the yacht's current `version` — for example because an accepted charter has meanwhile system-created a charter block on that calendar — is rejected with `ERR_STALE_VERSION` (HTTP 412), and the operator must re-read the calendar before adding the block.

### 2.11. The Validation Pipeline

Every request is validated in a fixed category pipeline, and an earlier failure masks all later checks. The pipeline runs in this order:

1. **Authentication** — headers present, role declared, entity-backed identity resolvable, broker type admitting the role; failures surface as `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is listed for the endpoint and the caller owns or is a party to the target; failures surface as `ERR_FORBIDDEN`.
3. **Existence** — every path identifier, validated left to right, and every body foreign key; failures surface as `ERR_NOT_FOUND`.
4. **State validity** — the target is in a from-state with a declared transition for the trigger, covering wrong-from-state, already-terminal resources, a duplicate signature on an agreement, a manual release attempted on a `CHARTER` block, a second insurance certificate while one is still `PENDING` or `VERIFIED`, and a void attempted after a signature exists; failures surface as `ERR_INVALID_STATE`. At this same tier sit the cross-entity state gates: the yacht must be `LISTED` when a request is submitted (`ERR_YACHT_NOT_LISTED`), and for the signing action specifically, the verified-insurance gate (`ERR_INSURANCE_NOT_VERIFIED`) is evaluated here, ahead of all lower-priority business checks.
5. **Business safety** — operator standing (`ERR_OPERATOR_SUSPENDED`), client qualification (`ERR_CLIENT_NOT_QUALIFIED`), resume class (`ERR_RESUME_CLASS_INSUFFICIENT`), segregation of duties (`ERR_BROKER_CONFLICT_OF_INTEREST`), verified insurance (`ERR_INSURANCE_NOT_VERIFIED`), and granted permits (`ERR_PERMIT_NOT_GRANTED`).
6. **Temporal and calendar rules** — availability conflicts (`ERR_AVAILABILITY_CONFLICT`), turnaround adjacency (`ERR_TURNAROUND_BUFFER_VIOLATION`), offer expiry (`ERR_OFFER_EXPIRED`), leg windows (`ERR_LEG_OUTSIDE_CHARTER_WINDOW`), permit containment (`ERR_PERMIT_WINDOW_INSUFFICIENT`), and clock-dependent action timing (`ERR_INVALID_REQUEST`).
7. **Field-level constraints** — required fields present, types and enum members valid, dates well-formed and ordered, amounts positive, manual block types restricted (`ERR_INVALID_REQUEST`), plus capacity (`ERR_CAPACITY_EXCEEDED`), duration (`ERR_CHARTER_DURATION_INVALID`), duplicate requests (`ERR_DUPLICATE_ACTIVE_REQUEST`), negotiation rounds (`ERR_NEGOTIATION_ROUND_LIMIT`), gratuity minimums (`ERR_GRATUITY_BELOW_MINIMUM`), and insurance coverage and window checks (`ERR_INSURANCE_COVERAGE_INSUFFICIENT`, `ERR_INSURANCE_WINDOW_INVALID`).
8. **Fiscal rules** — funding tranche sequencing (`ERR_FUNDING_TRANCHE_OUT_OF_ORDER`), exact tranche amounts (`ERR_FUNDING_AMOUNT_MISMATCH`), APA spend caps (`ERR_ESCROW_INSUFFICIENT`), and damage-claim caps (`ERR_DEPOSIT_CLAIM_EXCEEDS_HELD`).

Where several checks of one endpoint sit at the same tier, their relative order is stated alongside the workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Marketplace: Operators, Brokers, and Clients

A `PlatformAdmin` seeds the marketplace. Registering an operator takes a display `name` and a `home_port`; the operator starts life `ACTIVE`. Suspending an operator flips it to `SUSPENDED`, and while suspended the operator is barred from four activities: listing a yacht, creating an availability block, having a charter request submitted against one of its yachts, and having an offer issued on such a request — each rejected with `ERR_OPERATOR_SUSPENDED`. Delisting is pointedly not on that list: a suspended operator may still pull a yacht off the market. Reactivation returns the operator to `ACTIVE`.

Brokers are registered with a `display_name`, a `license_no`, and a `broker_type` of `CENTRAL_AGENT`, `RETAIL_BROKER`, or `BOTH`. The type is an admittance rule, not a label: the `CentralAgent` role requires `CENTRAL_AGENT` or `BOTH`, and the `RetailBroker` role requires `RETAIL_BROKER` or `BOTH`. A `BOTH` broker may wear either hat across the marketplace but never both hats on one deal — the segregation-of-duties rule of §3.3 enforces this at request creation.

Clients are registered with a `full_name` and an `email`, and their `qualification_status` starts `UNVERIFIED`. To charter bareboat, a client must qualify through a sailing resume. The client — and only the client, with the caller's identity compared to the client's `id` on pain of `ERR_FORBIDDEN` — submits the resume by declaring a `resume_class` of `NONE`, `COASTAL`, `OFFSHORE`, or `OCEAN` together with their `skippered_hours`; the submission stamps `resume_submitted_at` — null until this first submission — with the current logical time and moves the client from `UNVERIFIED` to `PENDING_REVIEW`. A `PlatformAdmin` then reviews the submission, recording an `outcome` of `QUALIFIED` or `REJECTED`, which settles the client into the corresponding state. Rejection is not the end of the road: a `REJECTED` client may resubmit a revised resume, which re-enters `PENDING_REVIEW` and overwrites `resume_class`, `skippered_hours`, and `resume_submitted_at` with the new declarations. Resume classes rank in the order `NONE` below `COASTAL` below `OFFSHORE` below `OCEAN`, and this ordering drives the bareboat gate in §3.3. A client's record — qualification state and resume class included — is readable by every role.

### 3.2. Yacht Listings and the Availability Calendar

An operator brings a yacht to the platform by creating the listing themselves; the yacht's `operator_id` is set from the authenticated operator, never from the payload. The listing payload carries the yacht's `name`, its `charter_type` (`BAREBOAT` or `CREWED`), its `home_port`, the guest capacity `capacity_berths`, the `weekly_base_rate_cents` that feeds every quote, a `min_charter_days` floor on charter length, the `required_resume_class` a bareboat client must hold, the refundable `security_deposit_cents`, the `pricing_mode` (`PRO_RATA` or `WEEKLY_PLUS_DAILY`) that selects the quote variant, and the `listing_central_agent_id` — which must reference a broker whose `broker_type` is `CENTRAL_AGENT`, the broker who will hold the listing and issue offers. A new yacht starts in `DRAFT`.

Listing the yacht moves it from `DRAFT` to `LISTED` (and a previously `DELISTED` yacht may be listed again by the same path). Only the owning operator may list, and the operator must be `ACTIVE` — a suspended operator's listing attempt is rejected with `ERR_OPERATOR_SUSPENDED`. Delisting moves `LISTED` to `DELISTED` and is deliberately asymmetric: it requires ownership but not operator good standing, and it is blocked with `ERR_INVALID_STATE` only while the yacht is referenced by a live deal — any charter request in `SUBMITTED`, `OFFERED`, or `COUNTERED` (a `DRAFT` request does not block), or any agreement in `PENDING_SIGNATURES`, `SIGNED`, `IN_PREP`, or `UNDERWAY`. Both listing and delisting increment the yacht's `version` by one. The yacht collection can be browsed with optional `operator_id`, `status`, `pricing_mode`, and `listing_central_agent_id` filters, and a single yacht is readable by all roles.

Between charters, an operator shapes the calendar with manual availability blocks. Creating one takes a `block_type` of `MAINTENANCE` or `OPERATOR_HOLD` — the third block type, `CHARTER`, is reserved for the system and a manual creation naming it is rejected as `ERR_INVALID_REQUEST` — plus the half-open interval's `start_date` and `end_date`, with `end_date` strictly after `start_date`. The creation is guarded twice over: the operator must be `ACTIVE` (`ERR_OPERATOR_SUSPENDED` otherwise), and the body must carry `expected_yacht_version` matching the yacht's current `version` per §2.10, so an operator working from a stale calendar view is stopped with `ERR_STALE_VERSION` before the calendar rules of §2.7 run. A created block starts `ACTIVE`, its `charter_agreement_id` is null, and the yacht's `version` increments by one because the calendar has changed.

Releasing a manual block is the owning operator's call and moves the block from `ACTIVE` to `RELEASED`, again incrementing the yacht's `version`. A `CHARTER` block refuses manual release with `ERR_INVALID_STATE` — it is released only by the cancellation cascade of §3.9, the same cascade that fills its `charter_agreement_id` at creation. A yacht's blocks, `ACTIVE` and `RELEASED` alike, can be listed with an optional `status` filter; the blocks linked to a specific agreement — the single `CHARTER` block, at most one `ACTIVE`, plus its released history — can likewise be read under the agreement with a `status` filter.

### 3.3. Charter Requests and the Negotiation Round

A charter request is opened either by a client directly or by a retail broker on the client's behalf. When the caller is a `Client`, the payload's `client_id` must be the caller's own `id`, and `retail_broker_id` is optional — omitted, it stays null. When the caller is a `RetailBroker`, `retail_broker_id` is set to the caller and `client_id` selects the represented client. Either way, segregation of duties is enforced at creation, ahead of the field-level gates: the deal's retail broker — caller or supplied — must differ from the yacht's `listing_central_agent_id`, or the creation is rejected with `ERR_BROKER_CONFLICT_OF_INTEREST`. This is where a `BOTH` broker is stopped from standing on both sides of one deal.

The request names the `yacht_id`, a half-open charter window through `start_date` and `end_date` with `end_date` strictly later, and a `guests_count`. The party size must be at least one and no more than the yacht's `capacity_berths` — a party exactly equal to capacity passes, and anything larger is rejected with `ERR_CAPACITY_EXCEEDED`. The charter's length in whole days must reach the yacht's `min_charter_days`, or creation fails with `ERR_CHARTER_DURATION_INVALID`. A duplicate guard also applies at creation: the same client asking for the same yacht over half-open-overlapping dates is rejected with `ERR_DUPLICATE_ACTIVE_REQUEST` if an earlier request of theirs is still live — that is, in `DRAFT`, `SUBMITTED`, `OFFERED`, or `COUNTERED`. The new request starts in `DRAFT` with `round_count` at zero and the commercial fields `quoted_charter_fee_cents`, `apa_pct`, `gratuity_pledged_cents`, and `retail_pct_bps` all null until the first offer; `offer_expires_at` is likewise null outside the `OFFERED` state. The request collection supports optional `client_id`, `yacht_id`, `retail_broker_id`, `rebooked_from_request_id`, and `status` filters, covering every reverse lookup a deal party needs.

Submitting the request — by the client or the retail broker on the deal, others drawing `ERR_FORBIDDEN` — moves it from `DRAFT` to `SUBMITTED` through an ordered battery of gates. The yacht must currently be `LISTED`, else `ERR_YACHT_NOT_LISTED`. The operator must be `ACTIVE`, else `ERR_OPERATOR_SUSPENDED`. For a `BAREBOAT` yacht, two qualification gates follow: the client's `qualification_status` must be `QUALIFIED`, else `ERR_CLIENT_NOT_QUALIFIED`, and the client's `resume_class` must rank at or above the yacht's `required_resume_class` on the `NONE`-to-`OCEAN` ladder, else `ERR_RESUME_CLASS_INSUFFICIENT`; a `CREWED` yacht skips both gates, since a professional crew carries the vessel. The calendar rules of §2.7 then run against the requested window, rejecting overlaps with `ERR_AVAILABILITY_CONFLICT` and buffer adjacency with `ERR_TURNAROUND_BUFFER_VIOLATION`, and finally the duplicate guard runs again — submission is the second of its three enforcement points — surfacing `ERR_DUPLICATE_ACTIVE_REQUEST` for an overlapping live request by the same client on the same yacht.

With the request `SUBMITTED`, the deal's central agent — the broker matching the yacht's `listing_central_agent_id`, anyone else drawing `ERR_FORBIDDEN` — issues an offer. The first offer requires the operator to be `ACTIVE` (`ERR_OPERATOR_SUSPENDED`); a re-offer after a counter moves from `COUNTERED` back to `OFFERED` under the same ownership rule but does not re-check the operator's standing. Each offer computes or overrides four commercial terms. The charter fee: unless the offer carries a positive `quoted_charter_fee_cents` override, the fee is quoted from the yacht's `weekly_base_rate_cents` and the charter length in whole days. Under the `PRO_RATA` variant, every day costs exactly one seventh of the week — the fee is the weekly base rate multiplied by the number of charter days, divided by seven, rounded half-up to whole cents. Under `WEEKLY_PLUS_DAILY`, each complete seven-day week is charged at the full weekly rate, and each remaining day beyond the last complete week is charged at the industry's short-week daily rate — the weekly base rate divided by six, rounded half-up to whole cents — so spare days are dearer than pro-rata days, and identical dates at an identical weekly rate quote strictly higher whenever at least one spare day exists. The APA fraction: an `apa_pct` override locks as given; otherwise the tiered default keys on the quoted fee — a quoted fee strictly below 2,000,000 cents (twenty thousand dollars) locks `apa_pct` at 0.30, while a fee at or above the threshold locks 0.25, so a quote of exactly 2,000,000 cents lands in the 0.25 tier. The gratuity: `gratuity_pledged_cents` rides along with the offer, and for a `CREWED` yacht it must be at least ten percent of the quoted charter fee, rounded half-up to whole cents — a smaller pledge is rejected with `ERR_GRATUITY_BELOW_MINIMUM` — while a `BAREBOAT` offer accepts any non-negative pledge, zero included. Finally `retail_pct_bps` fixes the retail broker's share of the commission in basis points. Issuing the offer transitions the request to `OFFERED`, locks all four terms onto it, stamps `offer_expires_at` at exactly seven days after the offer moment, and increments the request's `version` by one.

The client side answers an offer in one of three ways, each requiring the same party ownership as submission. A counter moves `OFFERED` to `COUNTERED` through a fixed check order: the caller must be a party; the request must be `OFFERED`; the payload's `expected_charter_request_version` must equal the request's current `version`, else `ERR_STALE_VERSION`; then the lazy expiry check — if the logical clock has passed `offer_expires_at`, the request transitions to `EXPIRED` and the counter is rejected with `ERR_OFFER_EXPIRED`; then the round cap — `round_count` must still be below the four-round negotiation limit, and a counter at the cap is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`. A successful counter increments `round_count` by one, clears `offer_expires_at` back to null, and increments `version` by one; the client side may optionally attach `counter_charter_fee_cents` to signal the price it is holding out for, leaving the formal terms to the central agent's next offer. Acceptance mirrors the counter's ordering — party, `OFFERED` state, the `expected_charter_request_version` match with the same `ERR_STALE_VERSION` rejection, then the same lazy expiry — and adds one final gate: the calendar rules of §2.7 run once more against the yacht's current blocks, so an overlap found at acceptance is `ERR_AVAILABILITY_CONFLICT` and a buffer adjacency is `ERR_TURNAROUND_BUFFER_VIOLATION`. Acceptance transitions the request from `OFFERED` to `ACCEPTED`, increments its `version`, and fires the creation cascade of §3.4; the response carries the newly created agreement. Declining needs no version field and no calendar check: it moves `OFFERED` to `DECLINED` and increments the request's `version`.

Three states end a request: `DECLINED`, `EXPIRED`, and `CANCELLED`. From any of them the client side may rebook — a fresh request in `DRAFT` for the same client, built from a payload of `yacht_id`, `start_date`, `end_date`, `guests_count`, and optionally `retail_broker_id`, with the new request's `rebooked_from_request_id` pointing back at the terminal request it descends from (null on any request not born of a rebook). The duplicate guard's third enforcement point is here: rebooking into an overlapping live request by the same client on the same yacht is rejected with `ERR_DUPLICATE_ACTIVE_REQUEST`.

### 3.4. Acceptance: The Agreement Snapshot and Its Signatures

Acceptance is the heaviest moment in the system: one action creates three resources and bumps two versions. The cascade's first hop creates the `CharterAgreement` in `PENDING_SIGNATURES` with `funds_status` `UNFUNDED`, freezing the deal by snapshot. Onto the agreement go the source `charter_request_id`; the `client_id` and `retail_broker_id` from the request (the latter may be null); the `yacht_id`; the `operator_id` read off the yacht; the `central_agent_id` read off the yacht's `listing_central_agent_id`; the `start_date` and `end_date` of the charter window; the agreed commercials — `charter_fee_cents` from the request's quoted fee, `apa_pct`, `gratuity_pledged_cents` (zero for a bareboat charter unless the offer pledged one), and `retail_pct_bps`; the yacht's `security_deposit_cents`; and the yacht's `pricing_mode`, kept for audit even though no further quoting occurs. The second hop creates the agreement's `EscrowAccount`, `OPEN` with every held bucket at zero. The third hop creates the charter's `AvailabilityBlock` — `block_type` `CHARTER`, status `ACTIVE`, covering the charter's half-open window, linked back to the new agreement through its `charter_agreement_id` — and increments the yacht's `version` by one. The request itself increments its own `version` as it lands in `ACCEPTED`.

At the same moment the funding schedule is computed and stored, in a pinned evaluation order. The charter fee is already locked from the accepted offer. The APA fraction resolves next — the offer's override if one was given, else the tier keyed on the locked fee. The APA amount `apa_amount_cents` is then the charter fee multiplied by the APA fraction, rounded half-up to whole cents. The signing tranche's charter part is half the charter fee, rounded half-up — and because the half is rounded up, an odd charter fee donates its odd cent to the signing tranche, leaving the final tranche the remainder. The amount due at signing, `signing_due_cents`, is that signing charter part plus the full `security_deposit_cents`. The final tranche, `final_due_cents`, is the charter fee minus the signing charter part, plus the full `apa_amount_cents`, plus the full `gratuity_pledged_cents`. The total a client will ever fund is exactly the sum of the two tranches.

Before money moves, the agreement must be signed. Signing requires a `VERIFIED` insurance certificate on the agreement — without one the attempt is rejected with `ERR_INSURANCE_NOT_VERIFIED`, a gate evaluated at the state-validity tier as §2.11 describes — and it requires the two parties to sign exactly once each: the client caller must be the agreement's `client_id`, the central agent caller the agreement's `central_agent_id`, and the same party signing twice is rejected with `ERR_INVALID_STATE`. The first signature merely records `client_signed_at` or `central_agent_signed_at` and leaves the agreement in `PENDING_SIGNATURES`; the transition to `SIGNED` fires when the second distinct signature lands and both timestamps are set, incrementing the agreement's `version`. An unsigned agreement can still be killed cleanly: the central agent may void it, but only while neither signature has been recorded — once any signature exists, voiding is rejected with `ERR_INVALID_STATE`. Voiding moves the agreement to `VOIDED`, releases the charter block (`ACTIVE` to `RELEASED`, incrementing the yacht's `version` by one), and cancels the source request from `ACCEPTED` to `CANCELLED` — the same terminal hop the cancellation cascade uses. Agreements are readable individually — both state axes, the computed funding schedule, and the penalty fields included — and the collection supports optional filters on `charter_request_id`, `client_id`, `yacht_id`, `operator_id`, `retail_broker_id`, `central_agent_id`, `status`, and `funds_status`.

### 3.5. Funding the Escrow

A `SIGNED` agreement is funded by the client side — the client or the retail broker — in two tranches, in order. The `SIGNING` tranche requires the funds axis to be `UNFUNDED`; the `FINAL` tranche requires `DEPOSIT_HELD`. Funding out of order — `FINAL` before `SIGNING`, or `SIGNING` twice — is rejected with `ERR_FUNDING_TRANCHE_OUT_OF_ORDER`, and the sequencing check runs before the amount check. Each funding call names a `tranche` and an `amount_cents`, and the amount must equal the computed due for that tranche to the cent — `signing_due_cents` for `SIGNING`, `final_due_cents` for `FINAL` — or the call is rejected with `ERR_FUNDING_AMOUNT_MISMATCH`; an unrecognized tranche name is a plain `ERR_INVALID_REQUEST`. Funding an agreement whose lifecycle axis is not `SIGNED` is rejected with `ERR_INVALID_STATE`.

Each tranche posts `CLIENT_FUND` movements into the escrow's buckets. The signing tranche posts a `CLIENT_FUND` against the `CHARTER_FEE` bucket for the signing charter part — half the fee, rounded half-up — and a `CLIENT_FUND` against the `DEPOSIT` bucket for the full security deposit, and moves the funds axis from `UNFUNDED` to `DEPOSIT_HELD`. The final tranche posts the remainder of the fee into `CHARTER_FEE`, the full `apa_amount_cents` into `APA`, and — only when the pledged gratuity is greater than zero — the full pledge into `GRATUITY`, moving the funds axis to `FULLY_FUNDED`. Every funding call increments the agreement's `version` by one and returns the updated escrow account.

The escrow itself is a bucketed ledger, not a balance. It holds `held_charter_fee_cents`, `held_apa_cents`, `held_deposit_cents`, and `held_gratuity_cents`, each starting at zero; `total_funded_cents` accumulates every `CLIENT_FUND` movement, and `total_released_cents` accumulates every outward movement — the three `RELEASE_TO_OPERATOR`, `RELEASE_TO_CENTRAL_AGENT`, and `RELEASE_TO_RETAIL_BROKER` types plus `REFUND_TO_CLIENT`. Each movement also names the `bucket` it debits or credits — `CHARTER_FEE`, `APA`, `DEPOSIT`, or `GRATUITY` — an always-positive `amount_cents`, a human-readable `memo` (a tranche name, a settlement line), and its owning `escrow_account_id`. The escrow's own `status` — `OPEN`, `SETTLING`, `CLOSED` — is driven only by the settlement and cancellation cascades, never directly; closure carries a hard invariant, `total_funded_cents` equal to `total_released_cents` with every held bucket at zero. The account is readable through its agreement (an array of length zero or one, since the escrow exists only from acceptance onward) or directly by `id`, and its movements are listed in posted, chronological order with optional `movement_type` and `bucket` filters.

### 3.6. Insurance, Itinerary, and Port Permits

No signatures happen without insurance. The central agent submits a certificate for the agreement with the `insurer_name`, the `policy_no`, a `coverage_amount_cents`, and a closed coverage window from `valid_from` to `valid_until`. Two constraint checks guard the filing: the coverage must be at least the agreement's `charter_fee_cents`, else `ERR_INSURANCE_COVERAGE_INSUFFICIENT`; and the window must contain the charter window on closed bounds — `valid_from` on or before the agreement's `start_date`, `valid_until` on or after its `end_date` — else `ERR_INSURANCE_WINDOW_INVALID`. A malformed window with `valid_from` after `valid_until` is rejected earlier as `ERR_INVALID_REQUEST`. So is a duplicate filing of a livelier sort: while any certificate for the agreement is still `PENDING` or `VERIFIED`, submitting another is rejected with `ERR_INVALID_STATE`. A new certificate starts `PENDING`; a `PlatformAdmin` then verifies it, recording an `outcome` of `VERIFIED` or `REJECTED`. Only a `VERIFIED` certificate opens the signing gate of §3.4, and after a rejection the central agent may file a replacement. The certificates of an agreement are listable with an optional `status` filter.

In parallel, the central agent builds the itinerary. Appending a leg is allowed while the agreement is in `PENDING_SIGNATURES`, `SIGNED`, or `IN_PREP`, and takes a `port_name`, an `arrival_date`, and a `departure_date`; the server assigns `seq_no` as one plus the count of legs the agreement already has, and the leg starts `PLANNED`. The leg's dates must sit inside the charter window on closed bounds — arrival on or after the agreement's `start_date`, departure on or after arrival and on or before the agreement's `end_date` — or the append is rejected with `ERR_LEG_OUTSIDE_CHARTER_WINDOW`. Legs are listed in `seq_no` order.

Each leg then needs its port permits, and every permit is tied to exactly one leg through its `itinerary_leg_id`. The central agent requests a permit for a leg with the `port_authority_ref` and a closed validity window from `valid_from` to `valid_until` (`valid_from` after `valid_until` is `ERR_INVALID_REQUEST`); the permit starts `REQUESTED`. A `PlatformAdmin` decides the application: a grant is containment-validated — the permit's closed window must contain the leg's closed window, `valid_from` on or before the leg's `arrival_date` and `valid_until` on or after its `departure_date`, else `ERR_PERMIT_WINDOW_INSUFFICIENT` — while a denial needs no such check. A denied permit is not dead: the central agent may resubmit it with a fresh `valid_from` and `valid_until`, returning it from `DENIED` to `REQUESTED`. Permits also age out on the logical clock: when the clock date passes a granted permit's `valid_until`, the permit moves from `GRANTED` to `EXPIRED` in the sweep of §2.5. A leg's permits are listable with an optional `status` filter.

The leg's own status is a pure roll-up of its permits, re-evaluated whenever one of them changes. A leg is `PERMITTED` exactly when it has at least one `GRANTED` permit and zero `REQUESTED` permits; `DENIED` and `EXPIRED` permits neither qualify nor block. Two events can therefore flip a `PERMITTED` leg back to `PLANNED`: its last `GRANTED` permit expiring, and a fresh `REQUESTED` permit being created on it. Conversely, a grant that leaves a leg with at least one `GRANTED` and no `REQUESTED` permits flips it from `PLANNED` to `PERMITTED`.

### 3.7. Departure Readiness, Expenses, and the APA Position

With signatures done, funding complete, and permits in hand, the operator drives the departure. Starting preparation moves the agreement from `SIGNED` to `IN_PREP` and is gated in a fixed order: the caller must own the yacht (`ERR_FORBIDDEN` otherwise); every itinerary leg of the agreement must be `PERMITTED` — a single leg still `PLANNED`, whether for want of any permit or because a permit is still `REQUESTED`, was `DENIED`, or has `EXPIRED`, fails the gate with `ERR_PERMIT_NOT_GRANTED`; and the funds axis must be `FULLY_FUNDED`, else `ERR_ESCROW_INSUFFICIENT`. Embarkation then moves `IN_PREP` to `UNDERWAY`, but only once the logical clock date has reached the charter's `start_date`; earlier is `ERR_INVALID_REQUEST`. Each step increments the agreement's `version`.

While the agreement is in `IN_PREP` or `UNDERWAY`, the operator records spend against it: provisioning drawdowns as expenses in the `APA` bucket and damage claims in the `DAMAGE_CLAIM` bucket, each with a `description` and a positive `amount_cents`, linked to the agreement and starting life `PENDING`. An expense recorded outside those two states finds no transition and is rejected with `ERR_INVALID_STATE`. The client side reviews each pending entry with an `outcome`: approval requires the agreement to be in `IN_PREP` or `UNDERWAY` (else `ERR_INVALID_STATE`) and is capped against the matching escrow bucket — approving an `APA` expense must not push the total of already-approved APA expenses plus this amount beyond `held_apa_cents` (`ERR_ESCROW_INSUFFICIENT`), and approving a `DAMAGE_CLAIM` must not push the approved damage total beyond `held_deposit_cents` (`ERR_DEPOSIT_CLAIM_EXCEEDS_HELD`) — while rejection needs no such check. An approved expense is not final until settlement: the client side may dispute it, reopening `APPROVED` to `DISPUTED` while the agreement is in `IN_PREP` or `UNDERWAY`, and a disputed amount leaves the APA's final position until it is resolved. Resolution belongs to the central agent, who settles a `DISPUTED` expense with an `outcome` of `APPROVED` — re-validating the same bucket caps, with the same two error codes — or `REJECTED`. An agreement's expenses are listable with optional `bucket` and `status` filters.

At any moment, the agreement's APA position is readable as a computed side-by-side view of two variants over the same fields. The view returns `held_apa_cents` straight from the escrow. The provisional variant, a forward-looking projection of committed spend, reports `provisional_apa_committed_cents` as the sum of the agreement's APA expenses in `PENDING` or `APPROVED` — `DISPUTED` and `REJECTED` are excluded — and `projected_apa_return_cents` as the held APA minus that committed sum. The final variant, the settlement basis used at completion, counts approved spend only: `final_apa_spent_cents` sums the agreement's `APPROVED` APA expenses, and `final_apa_return_cents` is the held APA minus that sum. Because the provisional variant admits pending expenses and the final does not, any pending expense makes the committed total strictly greater and the projected return strictly smaller than their final counterparts.

### 3.8. Completion and Settlement

When the charter has run its course, the operator or the central agent completes it — but only once the logical clock date has reached the agreement's `end_date`, else `ERR_INVALID_REQUEST`, and only a caller who owns the yacht or is the central agent, else `ERR_FORBIDDEN`. Completion moves the lifecycle axis from `UNDERWAY` to `COMPLETED` and fires a four-hop cascade.

The first hop flips the funds axis from `FULLY_FUNDED` to `SETTLING` and locks the books: every expense still `PENDING` or `DISPUTED` is auto-rejected, and the APA's final position — approved spend only — becomes the settlement basis. The second hop posts the settlement movements and moves the escrow from `OPEN` to `SETTLING`: a `RELEASE_TO_OPERATOR` from the `APA` bucket for the final approved spend; a `REFUND_TO_CLIENT` from `APA` for the held APA minus that spend; a `RELEASE_TO_OPERATOR` from `GRATUITY` for the entire held gratuity; the deposit settlement — a `RELEASE_TO_OPERATOR` from `DEPOSIT` for the approved damage claims, capped so it never exceeds the held deposit, and a `REFUND_TO_CLIENT` from `DEPOSIT` for the remainder, the two always summing exactly to the held deposit; and the charter-fee split — a `RELEASE_TO_OPERATOR` from `CHARTER_FEE` for the fee minus the total commission, a `RELEASE_TO_RETAIL_BROKER` for the retail share, and a `RELEASE_TO_CENTRAL_AGENT` for the central share.

The commission behind that split is tiered on the charter fee: fifteen percent when the fee is below 1,000,000 cents, eighteen percent when it is at least 1,000,000 and at most 4,999,999 cents, and twenty percent when it reaches 5,000,000 cents. Rounding order is pinned and non-negotiable: first the total commission is computed — the fee multiplied by the tier rate, rounded half-up to whole cents — then the retail share is the total multiplied by the agreement's `retail_pct_bps` and divided by ten thousand, rounded half-up to whole cents; the central share is never rounded independently but is simply the total minus the retail share, so the two shares always reconcile to the cent. The third hop fires once every required movement is posted: it writes the `CommissionStatement` with `basis` `CHARTER_FEE`, the `basis_amount_cents` equal to the charter fee, and the `commission_total_cents`, `retail_share_cents`, and `central_share_cents` exactly as computed; then it closes the escrow — `SETTLING` to `CLOSED` — leaving every held bucket at zero and the funding and release totals equal. The fourth hop settles the funds axis from `SETTLING` to `SETTLED`. The agreement's `version` increments once for the whole completion. An agreement's commission statements — zero or one of them, created here or by the cancellation of §3.9 — are listable under the agreement.

### 3.9. Cancellation, Penalties, and the Refund Cascade

Any deal party — the client, the retail broker, or the central agent — may cancel an agreement while it is in `PENDING_SIGNATURES`, `SIGNED`, or `IN_PREP`, optionally attaching a `reason`; anyone else draws `ERR_FORBIDDEN`. Cancellation first computes the penalty. The `days_before_start` is the whole-day difference between the agreement's `start_date` and the current logical clock date, and both it and the `cancellation_penalty_cents` — null on the agreement until a cancellation occurs — are computed and recorded at this moment. The penalty tier keys off that notice: ninety days or more before start costs ten percent of the charter fee; sixty to eighty-nine days costs thirty percent — so a cancellation exactly sixty days out lands in the thirty-percent tier while fifty-nine days lands in the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and twenty-nine days or fewer costs the full fee. The `cancellation_penalty_cents` is the charter fee multiplied by the tier percentage, rounded half-up to whole cents.

What the operator actually retains is capped by what the escrow holds: the retained amount is the smaller of the penalty and the held charter fee. The cascade then unwinds the money. The funds axis — from whichever of `UNFUNDED`, `DEPOSIT_HELD`, or `FULLY_FUNDED` it sits in — moves to `REFUNDING`, and the escrow moves from `OPEN` to `SETTLING` as its movements post: the client is refunded the held charter fee minus the retained amount, the entire held APA, the entire held gratuity, and the held deposit less any approved damage claims; when anything is retained, a penalty commission of twenty percent of the retained amount, rounded half-up, is carved off — the operator's release from the `CHARTER_FEE` bucket is the retained amount minus that commission, while the retail broker receives the retail share of the penalty commission (the commission multiplied by `retail_pct_bps` over ten thousand, rounded half-up) and the central agent receives the residual central share, the same pinned rounding order as §3.8 with `basis` `CANCELLATION_PENALTY`. For a cancellation from `IN_PREP`, approved damage claims are settled out of the deposit first — the operator receiving the approved total capped at the held deposit — before the client's deposit refund is computed, exactly as at completion. When every movement has posted, a `CommissionStatement` with `basis` `CANCELLATION_PENALTY` is written if and only if the retained amount is greater than zero, its `basis_amount_cents` equal to the retained penalty; the escrow closes — every held bucket at zero, funded equal to released — and the funds axis settles into `REFUNDED`.

Cancellation from `PENDING_SIGNATURES` runs the identical cascade with one natural emptiness: nothing has been funded yet, every held bucket is zero, so the retained amount is zero, no refund or release movements post, and no commission statement is written — yet the penalty fields are still computed and recorded, the escrow still closes, and the downstream hops still fire.

Those downstream hops return the yacht to the market and close the loop on the request. Escrow closure releases the agreement's `CHARTER` block from `ACTIVE` to `RELEASED` — the only way such a block is ever released — incrementing the yacht's `version` by one, and that release in turn transitions the source charter request from `ACCEPTED` to `CANCELLED`, incrementing its `version` as well. The agreement's own `version` increments once for the cancellation. From there the client side's path forward is the rebook flow of §3.3: a new draft request for the same client, chained to the cancelled one through `rebooked_from_request_id`.

## 4. Endpoint Definitions

The status code convention is uniform: operations that create a new stand-alone resource or add a distinct resource to a collection return `201 Created`; operations that modify an existing resource, drive a state transition, or merely read return `200 OK`. Accepting an offer returns `201` because it creates the charter agreement, even though it is triggered against an existing request. All GET endpoints are open to every declared role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps expired permits | PlatformAdmin |
| POST | `/operators` | Create an operator (starts ACTIVE) | PlatformAdmin |
| POST | `/operators/{id}/suspend` | Suspend an operator | PlatformAdmin |
| POST | `/operators/{id}/reactivate` | Reactivate a suspended operator | PlatformAdmin |
| POST | `/brokers` | Create a broker | PlatformAdmin |
| POST | `/clients` | Create a client (starts UNVERIFIED) | PlatformAdmin |
| GET | `/clients/{id}` | Read a client | Any |
| POST | `/clients/{id}/resume/submit` | Submit or resubmit a sailing resume | Client |
| POST | `/clients/{id}/resume/review` | Review a submitted resume | PlatformAdmin |
| POST | `/yachts` | Create a yacht listing (starts DRAFT) | Operator |
| GET | `/yachts/{id}` | Read a yacht | Any |
| GET | `/yachts` | List yachts with optional filters | Any |
| POST | `/yachts/{id}/list` | List a DRAFT or DELISTED yacht | Operator |
| POST | `/yachts/{id}/delist` | Delist a LISTED yacht | Operator |
| GET | `/yachts/{id}/availability-blocks` | List a yacht's availability blocks | Any |
| POST | `/yachts/{id}/availability-blocks` | Create a MAINTENANCE or OPERATOR_HOLD block (OCC-guarded) | Operator |
| POST | `/availability-blocks/{id}/release` | Release a manual block | Operator |
| POST | `/charter-requests` | Create a charter request (DRAFT) | Client, RetailBroker |
| GET | `/charter-requests/{id}` | Read a charter request | Any |
| GET | `/charter-requests` | List charter requests with optional filters | Any |
| POST | `/charter-requests/{id}/submit` | Submit a DRAFT request | Client, RetailBroker |
| POST | `/charter-requests/{id}/offer` | Issue an offer from SUBMITTED or COUNTERED | CentralAgent |
| POST | `/charter-requests/{id}/counter` | Counter the current offer (OCC; round cap 4) | Client, RetailBroker |
| POST | `/charter-requests/{id}/accept` | Accept the current offer (OCC); creates the agreement, escrow, and CHARTER block | Client, RetailBroker |
| POST | `/charter-requests/{id}/decline` | Decline the current offer | Client, RetailBroker |
| POST | `/charter-requests/{id}/rebook` | Rebook from a terminal request into a fresh DRAFT | Client, RetailBroker |
| GET | `/charter-agreements/{id}` | Read a charter agreement | Any |
| GET | `/charter-agreements` | List charter agreements with optional filters | Any |
| POST | `/charter-agreements/{id}/sign` | Record one countersignature; the second transitions to SIGNED | Client, CentralAgent |
| POST | `/charter-agreements/{id}/void` | Void an unsigned agreement; releases the CHARTER block and cancels the request | CentralAgent |
| POST | `/charter-agreements/{id}/fund` | Fund one escrow tranche (SIGNING then FINAL) at the exact computed amount | Client, RetailBroker |
| POST | `/charter-agreements/{id}/start-prep` | Move SIGNED to IN_PREP (permit and funding gates) | Operator |
| POST | `/charter-agreements/{id}/embark` | Move IN_PREP to UNDERWAY on or after start_date | Operator |
| POST | `/charter-agreements/{id}/complete` | Complete the charter; runs the settlement cascade | Operator, CentralAgent |
| POST | `/charter-agreements/{id}/cancel` | Cancel from PENDING_SIGNATURES, SIGNED, or IN_PREP; runs the cancellation cascade | Client, RetailBroker, CentralAgent |
| GET | `/charter-agreements/{id}/escrow` | Read the agreement's escrow account (array of length 0–1) | Any |
| GET | `/escrow-accounts/{id}` | Read an escrow account by id | Any |
| GET | `/escrow-accounts/{id}/movements` | List escrow movements in posted order | Any |
| POST | `/charter-agreements/{id}/expenses` | Record an APA expense or damage claim (PENDING) | Operator |
| GET | `/charter-agreements/{id}/expenses` | List an agreement's expense entries | Any |
| POST | `/expenses/{id}/review` | Approve or reject a PENDING expense (bucket caps on approve) | Client, RetailBroker |
| POST | `/expenses/{id}/dispute` | Dispute an APPROVED expense | Client, RetailBroker |
| POST | `/expenses/{id}/resolve` | Resolve a DISPUTED expense (caps re-validated on APPROVED) | CentralAgent |
| GET | `/charter-agreements/{id}/apa-position` | Read the provisional and final APA positions side by side | Any |
| POST | `/charter-agreements/{id}/insurance-certificates` | Submit an insurance certificate | CentralAgent |
| GET | `/charter-agreements/{id}/insurance-certificates` | List an agreement's insurance certificates | Any |
| POST | `/insurance-certificates/{id}/verify` | Verify or reject a PENDING certificate | PlatformAdmin |
| POST | `/charter-agreements/{id}/itinerary-legs` | Append an itinerary leg (seq_no auto-assigned) | CentralAgent |
| GET | `/charter-agreements/{id}/itinerary-legs` | List an agreement's legs in seq_no order | Any |
| GET | `/itinerary-legs/{id}` | Read an itinerary leg | Any |
| POST | `/itinerary-legs/{id}/permits` | Request a port permit for a leg | CentralAgent |
| GET | `/itinerary-legs/{id}/permits` | List a leg's permits | Any |
| POST | `/port-permits/{id}/decide` | Grant (containment-validated) or deny a REQUESTED permit | PlatformAdmin |
| POST | `/port-permits/{id}/resubmit` | Resubmit a DENIED permit with a new validity window | CentralAgent |
| GET | `/charter-agreements/{id}/commission-statements` | List an agreement's commission statements (0–1 entries) | Any |
| GET | `/charter-agreements/{id}/availability-blocks` | List the availability blocks linked to an agreement | Any |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OPERATOR_SUSPENDED` | 422 |
| `ERR_YACHT_NOT_LISTED` | 409 |
| `ERR_CLIENT_NOT_QUALIFIED` | 422 |
| `ERR_RESUME_CLASS_INSUFFICIENT` | 422 |
| `ERR_BROKER_CONFLICT_OF_INTEREST` | 422 |
| `ERR_INSURANCE_NOT_VERIFIED` | 422 |
| `ERR_PERMIT_NOT_GRANTED` | 422 |
| `ERR_AVAILABILITY_CONFLICT` | 409 |
| `ERR_TURNAROUND_BUFFER_VIOLATION` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_LEG_OUTSIDE_CHARTER_WINDOW` | 422 |
| `ERR_PERMIT_WINDOW_INSUFFICIENT` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_CHARTER_DURATION_INVALID` | 422 |
| `ERR_DUPLICATE_ACTIVE_REQUEST` | 409 |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 409 |
| `ERR_GRATUITY_BELOW_MINIMUM` | 422 |
| `ERR_INSURANCE_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_INSURANCE_WINDOW_INVALID` | 422 |
| `ERR_FUNDING_TRANCHE_OUT_OF_ORDER` | 422 |
| `ERR_FUNDING_AMOUNT_MISMATCH` | 422 |
| `ERR_ESCROW_INSUFFICIENT` | 422 |
| `ERR_DEPOSIT_CLAIM_EXCEEDS_HELD` | 422 |
