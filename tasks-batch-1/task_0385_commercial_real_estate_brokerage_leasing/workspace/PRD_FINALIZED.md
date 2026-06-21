# Cre-Brokerage-Leasing API — Product Requirements Document

## 1. Introduction

Commercial real estate transactions are slow, paper-driven, and chronically ambiguous about who did what and who gets paid. A single suite can be marketed by a landlord's broker, toured by a dozen prospects' representatives, negotiated over several rounds of letters of intent, and finally leased — and at every step two firms on opposite sides of the table need a shared, authoritative view of state. This document specifies the API for a commercial brokerage and leasing platform that holds that shared view: it tracks property and space inventory, marketed listings, tenant requirements, tour scheduling against per-space availability windows, the multi-round letter-of-intent (LOI) and lease-proposal negotiation between the listing side and the tenant-representation side, the commission split that settles when a lease executes, and the market comparables ("comps") that the executed deals leave behind.

The platform serves three operating capacities. Listing-side brokers control the supply: buildings, suites, and the listings that market them. Tenant-side brokers control the demand: tenant requirements and the tours that vet candidate space. A deal is the junction where supply meets demand — co-owned by both brokers, advanced through alternating proposal rounds, and gated by the state of the listing and the requirement that it binds. Because two independent parties mutate the same deal, the system applies optimistic concurrency control to every deal-stage write, and because executing a lease ripples outward across the space, the listing, sibling deals, and the requirement, those cascades are applied atomically inside the triggering request. The sections below define the global contract first, then the business workflows, then the endpoint and error surfaces.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `BrokerageAdmin`, `ListingBroker`, and `TenantBroker`. When a syntactically valid request is made by a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles bind to identity differently. When `X-User-Role` is `BrokerageAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the administrator manages brokerages and brokers and controls the test clock, but is never a party to a deal, so the server does not compare this identifier to any entity's `id`. When `X-User-Role` is `ListingBroker`, `X-User-ID` is the `id` of the acting `Broker` (a broker whose `role` is `LISTING_BROKER`); ownership checks on any resource that references a broker on the listing side — a `Property` via its `listing_broker_id`, a `Space` through its parent property, a `Listing` via its `listing_broker_id`, or a `Deal` via its `listing_broker_id` — compare that foreign-key field to `X-User-ID`. Likewise, when `X-User-Role` is `TenantBroker`, `X-User-ID` is the `id` of the acting `Broker` (whose `role` is `TENANT_BROKER`); ownership checks on a `Requirement` via its `tenant_broker_id`, a `Tour` via its `tenant_broker_id`, or a `Deal` via its `procuring_broker_id` compare that field to `X-User-ID`. When an acting broker is authenticated and permitted by role but is not the owner or a party to the targeted resource, the mutation is rejected with `ERR_NOT_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order. Every list-based response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Two Record Shapes

Most resources in this system are full mutable records. Every full record carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits, an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on every mutation. These full records are the `Brokerage`, `Broker`, `Property`, `Space`, `Listing`, `Requirement`, `Tour`, `Deal`, and `Proposal`.

Two resources are deliberately leaner. A `CommissionSplit` is an immutable ledger row and a `Comp` is an append-only market record; both carry only `id` and `created_at`. Neither a `CommissionSplit` nor a `Comp` carries `updated_at` or `version`, because once written they are never modified.

Whenever a derived or computed field is recomputed as a side effect — a property's `available_sf`, a listing's `open_deal_count`, a requirement's `match_count`, a deal's `round_count`, `total_consideration`, or `total_commission` — the carrying resource is itself mutated: its `updated_at` advances and its `version` increments. The deal's `version` in particular advances by exactly one on each deal-stage transition described in §3, and that monotonic counter is the basis for the concurrency control in §2.8.

### 2.5. Hierarchical Consistency and Automatic State Reconciliation

The brokerage graph binds resources across aggregate boundaries: a deal's progress depends on its listing's state and its requirement's state, a space's availability depends on the tours holding it and the deals leasing it, and a property's availability is the running sum of its spaces. To keep that graph coherent, the server transitions parent and child resources automatically when their criteria are met or violated, without requiring a separate client request against each affected resource. These bubble-up and cascade reconciliations are described in detail within the workflows of §3; what matters globally is that each one independently mutates the resource it touches, refreshing that resource's `updated_at` and incrementing its `version`, and that every cascade triggered by a single request is applied atomically inside that request before the response is returned.

When a path identifies a nested resource — for example a property's spaces, or a deal's proposals — the server validates the path left to right and rejects the first identifier that does not resolve to an existing resource with `ERR_NOT_FOUND`. The same `ERR_NOT_FOUND` applies when a foreign key supplied in a request body does not resolve to an existing resource.

### 2.6. Square-Footage Accounting and Inventory Derivation

A property's `available_sf` is a derived figure, never supplied directly by a client; at creation it is 0. It is defined as the sum of `rentable_sf` over the property's child spaces whose `status` is exactly `AVAILABLE`, and it is recomputed on every space status change. Spaces in `DRAFT`, `ON_HOLD`, `UNDER_LOI`, `LEASED`, or `OFF_MARKET` are excluded from the sum. This exclusion set is what makes the figure self-correcting: when a space moves from `AVAILABLE` to `UNDER_LOI` the property's `available_sf` drops by exactly that space's `rentable_sf`, and a compensating move back from `UNDER_LOI` to `AVAILABLE` restores it by the same amount. Because both `UNDER_LOI` and `LEASED` are excluded, a space transitioning from `UNDER_LOI` to `LEASED` produces no change in `available_sf`.

A listing's `open_deal_count` is likewise derived: it is the number of the listing's child deals whose `stage` is neither `DEAD` nor `EXECUTED`, recomputed on every deal-stage change. A requirement's `match_count` is the number of listings that currently satisfy the matching predicate of §3, recomputed whenever the requirement changes or any candidate space or listing changes. A deal's `round_count` is the number of proposal rounds authored on it.

### 2.7. Monetary Calculation and Precision

All rent, consideration, and commission figures are computed with decimal arithmetic and rounded half up. Net effective rent, gross effective rent, total consideration, and commission amounts are each rounded to exactly two decimal places, and — as detailed in §3 — each calculation rounds exactly once, at the very end, after the full stream has been summed; intermediate yearly figures are never individually rounded. Rate-style fields such as `default_commission_pct`, `annual_escalation_pct`, and `co_broke_offered_pct`, and the internally derived effective commission rate, are kept at full precision and are not rounded to two places. All monetary values in response bodies are plain JSON numbers, not strings.

### 2.8. Optimistic Concurrency Control on Deals

Because a deal is co-owned by two independent brokers, every operation that advances a deal's stage is guarded by optimistic concurrency control keyed on the deal's `version`. Two write operations carry this guard explicitly as a required, non-optional input field named `expected_deal_version`, which must equal the target deal's current `version`.

The first is proposal submission. A request to author a proposal round on a deal must include `expected_deal_version` carrying the client's last observed `version` of that deal. If another writer has advanced the deal's `version` since the client last read it — for instance because the counterparty has already authored a counter-proposal, which legitimately supersedes the prior open round and flips the latest pending proposal to `COUNTERED` — then the client's view of which side now owes the next move is stale, and the submission is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412).

The second is acceptance. A request to accept a deal must include `expected_deal_version` matching the deal's current `version`. If the counterparty has just countered since the client last read the deal, a new pending proposal has superseded the one the acceptor intended to bind, so accepting against the stale version would commit the wrong terms; the request is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412). The remaining deal-stage writes — sending the lease out, executing the lease, and killing the deal — also require `expected_deal_version` to match the deal's current `version` and are rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412) on a mismatch. No endpoint outside the deal-stage writes takes a version field.

### 2.9. Uniqueness and Field Constraints

A broker's `license_no` is unique across all brokers; a second registration carrying a `license_no` already in use is rejected. A space's `suite_no` is unique within its parent property, so the pair of `property_id` and `suite_no` must be unique. Enumerated fields accept only their declared members, numeric ranges must hold, a requirement's `min_sf` must not exceed its `max_sf`, and a tour's `window_start` must be strictly before its `window_end`. Violations of any of these body-level constraints are rejected with `ERR_INVALID_REQUEST` (HTTP 422). A request body that is not even well-formed — non-JSON, or fields of the wrong primitive type — is rejected earlier with `ERR_VALIDATION` (HTTP 400), before field-level validation runs.

### 2.10. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path resource and body foreign key (`ERR_NOT_FOUND`), then ownership or party membership (`ERR_NOT_OWNER`), then body field constraints (`ERR_INVALID_REQUEST`). Only after those structural gates does the system evaluate state-level rules: first the deal optimistic-concurrency check (`ERR_STALE_DEAL_VERSION`), then whether the requested transition is even defined from the resource's current state (`ERR_INVALID_STATE`), and then the business preconditions specific to each workflow — negotiation side, listing negotiability, requirement activity, space availability, tour-window conflicts, tour clock gates, withdrawal and close guards, and broker suspension — as those workflows describe in §3. A consequence of this ordering is that a stale deal version surfaces as `ERR_STALE_DEAL_VERSION` before any "wrong side" or "invalid state" reasoning is applied.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Firms, Brokers, and Inventory

Everything begins with a `BrokerageAdmin`, who is the only capacity that may create a `Brokerage` and register the brokers under it. A brokerage is created with a `name`, a `side` declaring which side or sides of the market the firm operates — one of `LISTING`, `TENANT_REP`, or `DUAL` — and an optional `default_commission_pct` expressing the firm's default total commission rate as a fraction of total lease consideration. When omitted, `default_commission_pct` defaults to 0.06 (six percent); it must be greater than 0 and at most 0.15.

A `Broker` is registered under a firm by supplying that firm's identifier as `brokerage_id`, the broker's `full_name`, a `license_no`, and a `role` of `LISTING_BROKER`, `TENANT_BROKER`, or `ADMIN`. Every broker carries a `status` that the system manages, starting `ACTIVE`; the administrator may move a broker from `ACTIVE` to `SUSPENDED`, and a `SUSPENDED` broker is barred from opening deals or authoring proposals as described later in this section.

A `ListingBroker` builds out supply. A `Property` is created with the controlling broker's identifier as `listing_broker_id`, a `name`, a `market` submarket code that must be non-empty, an `asset_class` of `OFFICE`, `RETAIL`, `INDUSTRIAL`, or `FLEX`, and a `total_sf` rentable area of at least 1. The property's `available_sf` is derived and starts at 0. Within a property, the listing broker carves out suites: a `Space` is created with its parent `property_id`, a `suite_no` label that must be unique within that property, a `rentable_sf` of at least 1, and an `asking_rent_psf_yr` (the asking annual base rent per square foot) that must be greater than 0. Two optional asking-package terms round out a space: `free_rent_months`, defaulting to 0 and bounded between 0 and 24 inclusive, and `ti_allowance_psf`, the tenant-improvement allowance per square foot, defaulting to 0 and never negative.

### 3.2. Bringing Space to Market: The Space and Listing Lifecycles

A newly created space begins in `DRAFT` and is invisible to the market. The listing broker publishes it, moving it from `DRAFT` to `AVAILABLE`, which is allowed only when the space has a `rentable_sf` of at least 1 and an `asking_rent_psf_yr` greater than 0; publication recomputes the parent property's `available_sf` so the now-`AVAILABLE` suite counts toward it. A space that has been pulled from the market can be re-published the same way, moving from `OFF_MARKET` back to `AVAILABLE` and again recomputing the property's `available_sf`. Withdrawing a space moves it from `AVAILABLE` to `OFF_MARKET`; this is permitted only when none of the property's listings sits in `UNDER_NEGOTIATION` and no space is `UNDER_LOI`, and when it succeeds it cascades every child listing that is in `DRAFT` or `ACTIVE` to `WITHDRAWN` and recomputes `available_sf`. The terminal state for a space is `LEASED`.

A `Listing` markets one suite. It is created with the `space_id` of the suite, the `listing_broker_id` of record, a marketed `term_months` of at least 1 month, an optional `annual_escalation_pct` (annual base-rent escalation as a fraction, defaulting to 0.03 and bounded between 0 and 0.20 inclusive), and an optional `co_broke_offered_pct` — the fraction of the total commission the listing side offers the procuring side on a co-broke deal — defaulting to 0.5 and bounded between 0 and 1 inclusive. A listing starts in `DRAFT`. Activating it moves it from `DRAFT` to `ACTIVE`, which requires the parent space to be `AVAILABLE` (otherwise `ERR_SPACE_NOT_AVAILABLE`), and on success recomputes `match_count` for every requirement that the now-active listing matches. A listing's `open_deal_count` and `status` evolve under the deal workflow: the first child deal that advances to `LOI_DRAFT` bubbles the listing from `ACTIVE` to `UNDER_NEGOTIATION`, and when its `open_deal_count` later returns to 0 with no deal executed it reverts from `UNDER_NEGOTIATION` back to `ACTIVE`.

Withdrawing a listing is permitted from `DRAFT` or `ACTIVE` and moves it to the terminal `WITHDRAWN` state. From `DRAFT` the withdrawal has no further effect. From `ACTIVE` it is blocked when any child deal sits in `LOI_ACCEPTED` or `LEASE_OUT`, in which case it is rejected with `ERR_LISTING_HAS_LIVE_DEAL`; when allowed, it cascades every child deal that is not already `EXECUTED` or `DEAD` to `DEAD` and recomputes `match_count` for the affected requirements. A listing also reaches the terminal `EXECUTED` state by cascade when one of its child deals executes, as described in §3.6.

### 3.3. Tenant Requirements and the Matching Predicate

A `TenantBroker` opens demand by creating a `Requirement` on behalf of a prospect. It carries the broker's `tenant_broker_id`, a `tenant_name`, a target `market` submarket code that must be non-empty, a required `asset_class`, a `min_sf` of at least 1, a `max_sf` that must be at least `min_sf`, and a `max_rent_psf_yr` — the maximum acceptable asking base rent per square foot per year — that must be greater than 0. A requirement starts `OPEN`, and its `match_count` is computed at creation.

A listing matches a requirement only when every one of the following holds at once: the listing's `status` is either `ACTIVE` or `UNDER_NEGOTIATION`; the market of the listing's property equals the requirement's `market`; the asset class of that property equals the requirement's `asset_class`; the suite's `rentable_sf` is at least the requirement's `min_sf` and at most its `max_sf`, with both bounds inclusive; and the suite's `asking_rent_psf_yr` is at most the requirement's `max_rent_psf_yr`, again inclusive. The requirement's `match_count` is the count of listings satisfying all of these clauses simultaneously. Because the predicate depends on listing status, space size, and asking rent, `match_count` is recomputed when the requirement is created or updated, when a space is published or withdrawn, and when a listing is activated or withdrawn. A tenant broker can read the live matches as a list of the listings currently satisfying the predicate.

A requirement's `status` advances through the tour and deal workflows. The first tour for the requirement that reaches `CONFIRMED` bubbles it from `OPEN` to `TOURING`; if every tour subsequently leaves `CONFIRMED` and no deal is open, it reverts from `TOURING` back to `OPEN`. The first deal on the requirement to reach `LOI_DRAFT` bubbles it to `NEGOTIATING` — from either `OPEN` or `TOURING` — and if its only open deal then dies it reverts from `NEGOTIATING` back to `OPEN`. The terminal states are `PLACED`, reached by cascade when a deal on the requirement executes, and `CLOSED_LOST`. The tenant broker may close a requirement, moving it from `OPEN` or `TOURING` to `CLOSED_LOST`, but only when no deal on it sits in `LOI_ACCEPTED`, `LEASE_OUT`, or `EXECUTED`; otherwise the close is rejected with `ERR_REQUIREMENT_HAS_LIVE_DEAL`. A successful close cascades every tour for that requirement that is in `REQUESTED` or `CONFIRMED` to `CANCELLED`.

### 3.4. Scheduling Tours Against Space Availability

A `TenantBroker` requests a `Tour` of a suite for a search by supplying the `requirement_id` it serves, the broker's `tenant_broker_id`, the `space_id` of the suite, and the tour window as `window_start` and `window_end`, both ISO 8601 UTC instants, where the window is the half-open interval that includes `window_start` and excludes `window_end` and where `window_start` must be strictly before `window_end`. A new tour starts in `REQUESTED` with `holds_space` false. The requirement it attaches to must be in `OPEN`, `TOURING`, or `NEGOTIATING`, or the request is rejected with `ERR_REQUIREMENT_NOT_ACTIVE`.

Confirmation is the listing side's prerogative: a `ListingBroker` confirms a tour, moving it from `REQUESTED` to `CONFIRMED`, and may pass an optional `hold` flag in the request to hold the space for the showing. Confirmation requires the space to be in `AVAILABLE` or `ON_HOLD`; a space that is `LEASED`, `OFF_MARKET`, or `UNDER_LOI` causes rejection with `ERR_SPACE_NOT_AVAILABLE`. Confirmation then runs two distinct overlap checks against existing `CONFIRMED` tours. The first protects the suite: against any other `CONFIRMED` tour on the same space, each existing confirmed window is expanded by a thirty-minute turnover buffer on both ends, and the candidate window conflicts when its start is earlier than that existing window's end plus thirty minutes and its end is later than that existing window's start minus thirty minutes; a window that merely touches a buffered edge does not conflict, and a conflict is rejected with `ERR_TOUR_WINDOW_CONFLICT`. The second protects the broker's own calendar: against any other `CONFIRMED` tour run by the same `tenant_broker_id` on any space, the half-open windows conflict with no buffer at all — the candidate conflicts when its start is earlier than the existing tour's end and its end is later than the existing tour's start, so two tours that are exactly back to back (the candidate beginning at the instant another ends) do not conflict, and a conflict is rejected with `ERR_BROKER_DOUBLE_BOOKED`.

When a confirmation carries `hold` set to true, it sets `holds_space` true, transitions the space from `AVAILABLE` to `ON_HOLD` while recording the holding tour's identifier in the space's `held_by_tour_id`, and bubbles the requirement from `OPEN` to `TOURING`. A held tour relinquishes its space whenever it leaves `CONFIRMED`. Completing a tour moves it from `CONFIRMED` to `COMPLETED` and is gated by the clock — it requires the server's current time to be at or after `window_start`, failing otherwise with `ERR_TOUR_NOT_STARTED`. Marking a no-show, the listing side's action, moves the tour from `CONFIRMED` to `NO_SHOW` and requires the current time to be at or after `window_end`, failing otherwise with `ERR_TOUR_NOT_ENDED`. A tour may be cancelled from `REQUESTED` or `CONFIRMED`. Whenever a held tour completes, cancels, or is marked no-show, the space reverts from `ON_HOLD` to `AVAILABLE`, its `held_by_tour_id` is cleared, `holds_space` is set false, and the property's `available_sf` is recomputed. The terminal tour states are `COMPLETED`, `CANCELLED`, and `NO_SHOW`. The server's clock used for these gates can be set by a `BrokerageAdmin` test-driving capability that accepts a target instant as `to_iso8601`.

### 3.5. Opening and Negotiating a Deal

A `Deal` is the junction binding a marketed listing to a tenant requirement, and either party broker may open it by supplying the `listing_id` and the `requirement_id`. At open time the listing must be non-terminal — its `status` must not be `WITHDRAWN` or `EXECUTED`, and a `DRAFT` listing is explicitly allowed because full negotiability is enforced only when the first proposal is authored — while the requirement must be active in `OPEN`, `TOURING`, or `NEGOTIATING`, failing with `ERR_REQUIREMENT_NOT_ACTIVE` otherwise. The acting broker must not be `SUSPENDED`, or the open is rejected with `ERR_BROKER_SUSPENDED`. On creation the deal enters `PROSPECT`, and the system stamps `listing_broker_id` from the listing's broker of record, `procuring_broker_id` from the requirement's tenant broker, and the computed `is_co_broke` flag, which is true exactly when those two brokers belong to different brokerages. The `procuring_broker_id` equals the `listing_broker_id` only when `is_co_broke` is false.

Negotiation proceeds through proposal rounds. A proposal is authored against a deal with a `from_side` of `LISTING` or `TENANT`, a year-one `base_rent_psf_yr` greater than 0, a proposed `term_months` of at least 1, and the optional package terms `free_rent_months` (default 0, bounded 0 to 24 inclusive), `ti_allowance_psf` (default 0, never negative), and `annual_escalation_pct` (default 0.03, bounded 0 to 0.20 inclusive). Every proposal submission also carries `expected_deal_version` for the concurrency guard of §2.8. A proposal's `outcome` is system-managed and starts `PENDING`, and the round's net effective rent is computed and stored on it as `net_effective_rent_psf_yr` as §3.7 defines.

The first proposal on a deal advances it from `PROSPECT` to `LOI_DRAFT`. This is allowed only when the authoring broker is not `SUSPENDED` (`ERR_BROKER_SUSPENDED`), the listing's `status` is `ACTIVE` or `UNDER_NEGOTIATION` (`ERR_LISTING_NOT_NEGOTIABLE`), the requirement's `status` is `OPEN`, `TOURING`, or `NEGOTIATING` (`ERR_REQUIREMENT_NOT_ACTIVE`), `expected_deal_version` matches the deal's `version` (`ERR_STALE_DEAL_VERSION`), and the author is on the side they claim — a `LISTING` proposal must come from the deal's `listing_broker_id` and a `TENANT` proposal from its `procuring_broker_id`, failing otherwise with `ERR_WRONG_SIDE`. The first proposal creates a new round with `outcome` `PENDING`, increments `round_count`, bubbles the listing from `ACTIVE` to `UNDER_NEGOTIATION` and the requirement to `NEGOTIATING`, and increments the deal's `version` by one.

Each subsequent proposal is a counter from the opposite side and drives the deal from `LOI_DRAFT` to `LOI_COUNTERED`, and thereafter loops `LOI_COUNTERED` to `LOI_COUNTERED` for every further round. A counter requires that its `from_side` be opposite to the side of the latest `PENDING` proposal (`ERR_WRONG_SIDE`) and that `expected_deal_version` match the deal's `version` (`ERR_STALE_DEAL_VERSION`). Each counter flips the latest `PENDING` proposal to `COUNTERED`, creates a new `PENDING` proposal, increments `round_count`, and increments the deal's `version` by one. The negotiation history of a deal, readable as the list of its proposals, records this alternating ladder of rounds.

### 3.6. Accepting, Leasing Out, and Executing

Acceptance closes the negotiation. A deal is accepted from `LOI_DRAFT` or `LOI_COUNTERED`, moving it to `LOI_ACCEPTED`, and the request carries `from_side` and `expected_deal_version`. The acceptor must be the side that did not author the latest `PENDING` proposal (`ERR_WRONG_SIDE`), the parent space must be in `AVAILABLE` or `ON_HOLD` (`ERR_SPACE_NOT_AVAILABLE`), and `expected_deal_version` must match the deal's `version` (`ERR_STALE_DEAL_VERSION`). Acceptance flips the latest `PENDING` proposal to `ACCEPTED`, records its identifier in the deal's `accepted_proposal_id`, computes `total_consideration` and `total_commission`, transitions the space to `UNDER_LOI` as a cross-entity cascade, completes the holding tour (moving it to `COMPLETED`) if one exists, and increments the deal's `version` by one. A move into `UNDER_LOI` from `AVAILABLE` decrements the property's `available_sf` by that space's `rentable_sf`; a move into `UNDER_LOI` from `ON_HOLD` additionally clears the space's `held_by_tour_id`.

A `ListingBroker` then sends the lease out for signature, moving the deal from `LOI_ACCEPTED` to `LEASE_OUT`; this requires the space to be `UNDER_LOI` and `expected_deal_version` to match (`ERR_STALE_DEAL_VERSION`), and it increments the deal's `version` by one. Finally the listing broker executes the lease, moving the deal from `LEASE_OUT` to the terminal `EXECUTED`; this likewise requires the space to be `UNDER_LOI` and `expected_deal_version` to match, and it increments the deal's `version` by one. Execution is the climactic cascade: it writes the `CommissionSplit` ledger rows for the `LISTING` and `PROCURING` sides as §3.8 describes, transitions the space from `UNDER_LOI` to the terminal `LEASED`, transitions the listing from `UNDER_NEGOTIATION` to the terminal `EXECUTED`, drives every sibling deal on that listing whose `stage` is neither `EXECUTED` nor `DEAD` to `DEAD`, transitions the requirement from `NEGOTIATING` to the terminal `PLACED`, cancels every other tour of that requirement still in `REQUESTED` or `CONFIRMED`, and appends a `Comp` market record. The appended comp stamps the executed deal's `effective_rent_psf_yr` (copied from the accepted proposal's net effective rent), the `market` copied from the property at execution time, the executed `term_months`, the `space_id` of the leased suite, the `deal_id` of the executing deal, and the server clock value as `executed_at`. Recomputing `available_sf` on the `UNDER_LOI` to `LEASED` move yields no change, since both statuses are excluded from the figure.

A deal may be killed from `PROSPECT`, `LOI_DRAFT`, `LOI_COUNTERED`, or `LOI_ACCEPTED`, moving it to the terminal `DEAD`; the kill requires `expected_deal_version` to match (`ERR_STALE_DEAL_VERSION`). Killing from `LOI_DRAFT` or `LOI_COUNTERED` rejects every `PENDING` proposal, bubbles the listing back from `UNDER_NEGOTIATION` to `ACTIVE` when its `open_deal_count` returns to 0, bubbles the requirement back to `OPEN` when this was its only open deal, and increments the deal's `version`. Killing from `LOI_ACCEPTED` is a compensating cascade: it rejects the accepted proposal, clears `accepted_proposal_id`, resets `total_consideration` and `total_commission` to 0, returns the space from `UNDER_LOI` to `AVAILABLE` and recomputes the property's `available_sf`, bubbles the listing back to `ACTIVE` when `open_deal_count` is 0 and the requirement back to `OPEN`, and increments the deal's `version`. Killing from `PROSPECT` simply terminates the deal and increments its `version`. Across all of these, a write that targets a transition not defined from the deal's current stage is rejected with `ERR_INVALID_STATE`.

### 3.7. Net Effective Rent and Total Consideration

Whenever a proposal is created, the system computes its `net_effective_rent_psf_yr` — the per-square-foot-per-year rent after amortizing free rent and the tenant-improvement allowance across the term, against an escalated gross rent stream. The evaluation order is pinned. First determine the number of whole lease-years the term touches by dividing `term_months` by 12 and rounding up to the next whole number. Then build the gross stream per square foot by walking those years from the first (year index zero) to the last: for each year the applicable rate is `base_rent_psf_yr` multiplied by one plus `annual_escalation_pct` raised to the power of that year's index, and the rate contributes for the fraction of the year actually within the term — twelve-twelfths for every full year and, for a final partial year, the number of remaining months over twelve. Summing those yearly contributions gives the gross total per square foot. From that, subtract a free-rent credit equal to `base_rent_psf_yr` multiplied by `free_rent_months` divided by twelve — the credit is always valued at the year-one base rate, never at an escalated rate — and subtract `ti_allowance_psf`. Divide the resulting net total per square foot by the term expressed in years (`term_months` divided by twelve), and round that single quotient half up to two decimal places. The rounding happens exactly once, at the end. A gross effective rent is the same figure computed without the free-rent and tenant-improvement subtractions — the gross total per square foot divided by the term in years, rounded half up to two decimal places — and the spread between gross and net is the concession value; this gross variant is reported for comparison but is not stored.

Total consideration is computed when a deal is accepted and stored on the deal as `total_consideration`. It is the gross base-rent dollars the tenant contracts to pay over the term from the accepted proposal — free rent and tenant-improvement allowance are deliberately not netted out of consideration. Using the accepted proposal's terms and the parent space's `rentable_sf`, determine the whole lease-years by dividing the proposal's `term_months` by twelve and rounding up. Walk each year from the first: the year's rate is the proposal's `base_rent_psf_yr` times one plus the proposal's `annual_escalation_pct` raised to that year's index, and the year contributes that rate times the space's `rentable_sf` times the in-term month fraction (twelve-twelfths for full years, remaining months over twelve for the final partial year). Sum every year's dollar contribution and round the single total half up to two decimal places — one rounding, after the full sum. Until a deal reaches `LOI_ACCEPTED`, both `total_consideration` and `total_commission` are 0.

### 3.8. Commission Rate and the Split Ledger

The total commission is computed when a deal is accepted and stored on the deal as `total_commission`. The system first derives the effective commission rate. It starts from the listing broker's brokerage `default_commission_pct`. If the accepted proposal's `term_months` is at least 120 months — that is, a ten-year-or-longer lease — a one-percentage-point large-deal discount is applied by subtracting 0.01 from that base rate; otherwise the base rate stands. The resulting rate is then floored so it never falls below 0.03 (three percent): the effective rate is the larger of the discounted rate and 0.03. This rate is kept at full precision. The deal's `total_commission` is then `total_consideration` multiplied by that effective rate, rounded half up to two decimal places.

At execution the commission is allocated into `CommissionSplit` ledger rows, one for each side, each carrying the settling `deal_id`, the payee `broker_id`, a `side` of `LISTING` or `PROCURING`, and a dollar `amount`. For a co-broke deal — one where `is_co_broke` is true because the listing and procuring brokers belong to different brokerages — the procuring side's `amount` is `total_commission` multiplied by the listing's `co_broke_offered_pct`, rounded half up to two decimal places, and the listing side's `amount` is the remainder: `total_commission` minus the procuring amount, taken as a residual rather than independently rounded, so that the two amounts sum to `total_commission` exactly. For an in-house deal — one where `is_co_broke` is false because both sides belong to the same brokerage — the listing side receives the entire commission (`total_commission` rounded half up to two decimal places) and a `PROCURING` row is still written with an `amount` of 0.00 for ledger completeness. In every case the `LISTING` and `PROCURING` amounts together equal `total_commission` exactly; this conserved-quantity invariant is the integrity check on the split.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the test-clock control — return a `200 OK` status code. All list and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brokerages` | Create a brokerage firm | BrokerageAdmin |
| GET | `/brokerages/{brokerageId}` | Get a brokerage | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/brokers` | Register a broker under a brokerage | BrokerageAdmin |
| GET | `/brokers/{brokerId}` | Get a broker | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/brokers` | List brokers; filter by `brokerage_id` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/brokers/{brokerId}/suspend` | Suspend a broker | BrokerageAdmin |
| POST | `/properties` | Create a property | ListingBroker |
| GET | `/properties/{propertyId}` | Get a property (includes computed `available_sf`) | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/properties/{propertyId}/spaces` | List spaces under a property | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/properties` | List properties; filter by `listing_broker_id`, `market` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/spaces` | Create a space within a property | ListingBroker |
| GET | `/spaces/{spaceId}` | Get a space | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/spaces` | List/search spaces; filter by `property_id`, `status`, `held_by_tour_id` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/spaces/{spaceId}/publish` | Publish a space to market | ListingBroker |
| POST | `/spaces/{spaceId}/withdraw` | Withdraw a space from market | ListingBroker |
| POST | `/listings` | Create a listing for an available space | ListingBroker |
| GET | `/listings/{listingId}` | Get a listing (includes computed `open_deal_count`) | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/listings` | List/search listings; filter by `space_id`, `listing_broker_id`, `status` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/listings/{listingId}/activate` | Activate a listing | ListingBroker |
| POST | `/listings/{listingId}/withdraw` | Withdraw a listing | ListingBroker |
| POST | `/requirements` | Create a tenant requirement | TenantBroker |
| GET | `/requirements/{requirementId}` | Get a requirement (includes computed `match_count`) | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/requirements` | List requirements; filter by `tenant_broker_id`, `status` | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/requirements/{requirementId}/matches` | List listings currently matching this requirement | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/requirements/{requirementId}/close` | Close a requirement as lost | TenantBroker |
| POST | `/tours` | Request a tour of a space for a requirement | TenantBroker |
| GET | `/tours/{tourId}` | Get a tour | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/tours` | List tours; filter by `requirement_id`, `space_id`, `tenant_broker_id`, `status` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/tours/{tourId}/confirm` | Confirm a tour; optionally hold the space | ListingBroker |
| POST | `/tours/{tourId}/complete` | Complete a confirmed tour | TenantBroker |
| POST | `/tours/{tourId}/cancel` | Cancel a tour | TenantBroker |
| POST | `/tours/{tourId}/no-show` | Mark a confirmed tour as a no-show | ListingBroker |
| POST | `/deals` | Open a deal binding a listing to a requirement | ListingBroker, TenantBroker |
| GET | `/deals/{dealId}` | Get a deal (includes computed `round_count`, `total_consideration`, `total_commission`) | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/deals` | List/pipeline deals; filter by `listing_id`, `requirement_id`, `listing_broker_id`, `procuring_broker_id`, `accepted_proposal_id`, `stage` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/deals/{dealId}/proposals` | Submit an LOI/lease proposal round | ListingBroker, TenantBroker |
| GET | `/deals/{dealId}/proposals` | List proposals for a deal | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/proposals/{proposalId}` | Get a single proposal | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/proposals` | List proposals; filter by `deal_id`, `from_side`, `outcome` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/deals/{dealId}/accept` | Accept the latest pending proposal | ListingBroker, TenantBroker |
| POST | `/deals/{dealId}/lease-out` | Send the lease out for signature | ListingBroker |
| POST | `/deals/{dealId}/execute` | Execute the lease | ListingBroker |
| POST | `/deals/{dealId}/kill` | Kill a deal | ListingBroker, TenantBroker |
| GET | `/commission-splits/{splitId}` | Get a single commission split row | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/commission-splits` | List commission splits; filter by `deal_id`, `broker_id` | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/comps/{compId}` | Get a single market comp | BrokerageAdmin, ListingBroker, TenantBroker |
| GET | `/comps` | List market comps; filter by `space_id`, `deal_id`, `market` | BrokerageAdmin, ListingBroker, TenantBroker |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock for temporal tests | BrokerageAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_DEAL_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WRONG_SIDE` | 409 |
| `ERR_LISTING_NOT_NEGOTIABLE` | 409 |
| `ERR_REQUIREMENT_NOT_ACTIVE` | 409 |
| `ERR_SPACE_NOT_AVAILABLE` | 409 |
| `ERR_TOUR_WINDOW_CONFLICT` | 409 |
| `ERR_BROKER_DOUBLE_BOOKED` | 409 |
| `ERR_TOUR_NOT_STARTED` | 409 |
| `ERR_TOUR_NOT_ENDED` | 409 |
| `ERR_LISTING_HAS_LIVE_DEAL` | 409 |
| `ERR_REQUIREMENT_HAS_LIVE_DEAL` | 409 |
| `ERR_BROKER_SUSPENDED` | 409 |
| `ERR_VALIDATION` | 400 |
