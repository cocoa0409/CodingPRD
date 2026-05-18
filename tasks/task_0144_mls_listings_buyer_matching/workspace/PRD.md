# MLS Listings and Buyer Matching API — Product Requirements Document

## 1. Introduction

Residential real-estate transactions are fundamentally multi-party negotiations conducted on top of shared inventory. A listing agent puts a property on the Multiple Listing Service (MLS), buyer agents bring qualified buyers, showings get scheduled and physically gated by a lockbox, and offers move through a back-and-forth of counter and rebound until either one is accepted or the listing expires. Once an offer is accepted the listing enters a contingent period during which inspection, appraisal, and financing checks may either close the deal or pull it back to market. Each closed sale produces a co-operative commission split — a fixed pool of money that flows to the listing brokerage and the buyer's brokerage, and then through each side to the individual agent.

This document specifies the MLS Listings and Buyer Matching API, a backend service that coordinates these workflows for two peer agent roles and a small operational admin role. The API is responsible for the integrity of the offer chain (multiple offers on a single listing must serialize to exactly one acceptance), for the temporal correctness of expirations (offer deadlines, counter deadlines, contingency deadlines, and a 180-day listing lifetime), for the physical-safety gate that the lockbox represents around showings, and for the dual-variant commission arithmetic that is computed once at acceptance (provisional) and once at close (final). It also exposes a deterministic, weighted buyer-listing matching score so each side can discover promising counterparts.

All endpoints in this service are mounted under `/listings` and its sibling resource paths. The contract is designed so that two agents acting simultaneously on the same listing produce a well-defined winner and a well-defined error code on the loser's side; race conditions are not silent.

## 2. Global Specifications and System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-Role` identifies the caller's role, and `X-User-ID` identifies the calling principal. If either header is missing the request is rejected with `ERR_AUTH_MISSING` and HTTP 401. If `X-User-ID` cannot be resolved to a valid principal for the supplied `X-User-Role`, or the role spelling itself is not one of the recognized values, the request is rejected with `ERR_AUTH_INVALID` and HTTP 401. If the headers resolve but the role lacks permission to call the endpoint per the RBAC matrix, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

There are exactly three roles, each spelled exactly as shown:

- `ListingAgent` — represents the seller side of a transaction; creates and edits listings, manages the lockbox, approves showings, issues counters, and accepts, rejects, or closes offers. When `X-User-Role` is `ListingAgent`, `X-User-ID` is the `id` of the acting `Agent` record, and ownership checks on any listing-side action compare the `Listing`'s `listing_agent_id` to `X-User-ID`. Agents whose `agent_role` is `LISTING_AGENT` or `DUAL_AGENT` are valid `ListingAgent` callers.
- `BuyerAgent` — represents the buyer side; registers buyers, requests showings, submits offers, rebounds counters, withdraws offers, and manages contingencies. When `X-User-Role` is `BuyerAgent`, `X-User-ID` is likewise the `id` of the acting `Agent`, and ownership checks on any buyer-side action compare the `Buyer`'s `buyer_agent_id` to `X-User-ID`. Agents whose `agent_role` is `BUYER_AGENT` or `DUAL_AGENT` are valid `BuyerAgent` callers.
- `MlsAdmin` — an operational role used for onboarding agents, advancing the logical clock, running the sweep, and reading cross-cutting reports. When `X-User-Role` is `MlsAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept any non-empty value as long as the role permits the requested operation; no comparison to an `Agent.id` is performed.

When a listing-side action is invoked by a `ListingAgent` whose `id` is not the listing's `listing_agent_id`, or a buyer-side action is invoked by a `BuyerAgent` whose `id` is not the buyer's `buyer_agent_id`, the request is rejected with `ERR_FORBIDDEN_NOT_OWNER` and HTTP 403. This ownership check runs after generic role permission and after path-resource existence.

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, has a minimum of 1, and is capped at 100; values outside this range are rejected as validation errors. The `offset` parameter defaults to 0 and must be non-negative. The four pagination fields surfaced in the response `meta` object are `limit`, `offset`, `total_count`, and `has_more`, with `has_more` set to `true` whenever the next page would still contain at least one row. Unless an endpoint description explicitly states otherwise — for example, the buyer-matching endpoints which sort by score — list endpoints return rows sorted by `created_at` ascending, with ties broken by `id` ascending.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, generated as a UUID with no resource-type prefix, and a server-minted `created_at` timestamp emitted as an ISO 8601 UTC string with three fractional digits. Resources whose records are mutable additionally carry an `updated_at` timestamp in the same format and an integer `version` counter that begins at 1 on creation and increments by exactly 1 on every successful mutation; `Agent`, `Listing`, `Buyer`, `Lockbox`, `ShowingAppointment`, `Offer`, and `Contingency` all carry the full quartet. Two record types are exceptions because they are immutable once written: `Counter` rows and `CommissionSplit` rows carry only `id` and `created_at`. They have neither `updated_at` nor `version` because their content does not change after the row is emitted — a counter is settled by rebound or expiration of the counter, not by editing the row, and a commission split is a snapshot of arithmetic done at a particular state transition.

### 2.5. Nested Resource Hierarchy and Path Resolution

Resource paths reflect ownership. A counter, a contingency, a showing, or an offer always sits beneath a listing, and an admin or agent fetching such a child supplies the parent listing identifier in the path. The server validates path resources left to right: it first resolves the listing, then the offer (or showing, contingency, or lockbox) within that listing, and finally any further nesting. If any segment of the path does not resolve — or resolves to a row whose parent foreign key does not match the path's earlier segment — the response is `ERR_NOT_FOUND` with HTTP 404. Existence checks run after authentication and role-permission checks but before any state checks.

### 2.6. Optimistic Concurrency Control

Mutating endpoints that take resource state and transform it — `PATCH /listings/{id}`, `PATCH /buyers/{id}`, and `PATCH /agents/{id}` — accept a `version` field in the request body. If the supplied `version` does not equal the stored `version` of the target row, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. A caller who omits the `version` field from these PATCH bodies skips the optimistic check, accepting whatever the current row state is. Action endpoints such as withdraw, close, accept, counter, rebound, reject, satisfy, waive, and fail do not consume a `version` field except where the endpoint table indicates one as input; their concurrency is governed by the entity's state machine and by the specific concurrency rules in §2.10. Every successful mutation refreshes `updated_at` and increments `version` by 1 on the directly mutated row, and likewise on each cascaded row that the operation touches.

### 2.7. Precision, Rounding, and Money

Money values are stored and exchanged as integer whole-cent amounts. Whenever a monetary computation calls for rounding — a commission term computed from a percentage, for example — the rule is **round half up** to the nearest whole cent. Percentage fields such as `co_op_pct`, `total_commission_pct`, and `brokerage_split_pct` are decimal fractions stored with up to four decimal places. The two scoring values produced for buyer-listing matches are quoted to **two decimal places, round half up**, and the rounding is applied exactly once to the final weighted sum, not to the per-factor components, with one local exception called out in §3.4 for the feature-fit subscore.

### 2.8. Lockbox Discipline as a Safety Gate

The lockbox is a physical-safety gate, not just a record. Exactly one lockbox is associated with any listing at a time, identified by its `serial_number`, which is unique across all lockboxes regardless of status. A lockbox's `access_code` is a server-minted 6-digit numeric string; it is regenerated on every successful access grant and on every re-arm. The `code_rotated_at` timestamp records the most recent regeneration. A lockbox is in one of `ARMED`, `DISARMED`, or `RETIRED`. Approving a showing requires the lockbox to be `ARMED`; if it is not, the approval fails with `ERR_LOCKBOX_NOT_ARMED`. Asking to arm a box that is already `ARMED`, or to retire a box that is still `ARMED`, or to disarm a box that is already `DISARMED` — or any other request that finds the lockbox in the wrong state for its transition — is rejected with `ERR_LOCKBOX_STATE`.

### 2.9. Temporal Windows, the Logical Clock, and the Sweep

Several deadlines drive deferred actions: an offer's `expires_at`, a counter's `counter_expires_at`, a contingency's `deadline_at`, and the 180-day listing lifetime measured from the listing's `created_at`. The server maintains a logical clock; an admin-only capability advances that clock to a supplied `to` instant. After advancement, an admin-only sweep capability scans all time-gated rows and applies their auto-transitions in deterministic order so that two contingencies maturing in the same sweep, or a contingency and an offer maturing together, settle in a reproducible sequence. The sweep traverses entity types in the order `Contingency`, then `Offer`, then `Counter`, then `ShowingAppointment`, then `Listing`; within each type it processes rows in `(created_at, id)` ascending order. The sweep response reports counts of `expired_offers`, `expired_counters`, `failed_contingencies`, `expired_listings`, and `no_show_showings` for the run.

### 2.10. Concurrency Outcomes

Five concurrency scenarios are first-writer-wins, and the loser receives a specific error:

1. Two `ListingAgent` callers attempting to accept different offers on the same listing at the same instant: at most one offer reaches `ACCEPTED`; the loser, finding the listing now `UNDER_CONTRACT`, is rejected with `ERR_LISTING_ALREADY_UNDER_CONTRACT`.
2. A `ListingAgent` accepting an offer while the `BuyerAgent` simultaneously withdraws that same offer: exactly one operation succeeds. If the withdraw lands first, the accept finds the offer no longer in `SUBMITTED` status and is rejected with `ERR_OFFER_NOT_SUBMITTED`; if the accept lands first, the withdraw likewise finds the offer no longer in `SUBMITTED` status and is rejected with the same `ERR_OFFER_NOT_SUBMITTED`.
3. Two `BuyerAgent` callers approving overlapping showings on the same listing simultaneously: at most one `SCHEDULED` showing can occupy any half-open interval; the second to commit sees the overlap and is rejected with `ERR_SHOWING_TIME_OVERLAP`.
4. Two `PATCH /listings/{id}` requests with the same stored `version`: only the request whose `version` matches the row at the moment of write succeeds; the loser sees `ERR_VERSION_CONFLICT`.
5. Two contingencies on the same accepted offer reaching their `deadline_at` in the same sweep: the sweep processes contingencies in `(created_at, id)` ascending order, the first one to fail triggers the listing's return to `ACTIVE` via the cascade in §3.7, and the second contingency, finding the listing already returned to `ACTIVE` and cascade-failed by the earlier one, is recorded as `FAILED` via the cascade rather than via a fresh trigger and reports `ERR_CONTINGENCY_ALREADY_FAILED` if a redundant fresh-trigger call arrives.

### 2.11. State Vocabulary

Each mutable entity has a fixed set of state strings, written in uppercase: a `Listing` is one of `ACTIVE`, `UNDER_CONTRACT`, `SOLD`, `WITHDRAWN`, or `EXPIRED`. An `Offer` is one of `SUBMITTED`, `COUNTERED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, or `EXPIRED`. A `Counter` is one of `OPEN`, `REBOUND`, `EXPIRED`, or `WITHDRAWN`. A `ShowingAppointment` is one of `REQUESTED`, `SCHEDULED`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`. A `Contingency` is one of `PENDING`, `SATISFIED`, `WAIVED`, or `FAILED`. A `Lockbox` is one of `ARMED`, `DISARMED`, or `RETIRED`. An `Agent` is one of `ACTIVE` or `SUSPENDED`. A `Buyer` is one of `ACTIVE`, `SOLD`, or `WITHDRAWN`. A `CommissionSplit` row carries a `variant` of either `PROVISIONAL` or `FINAL`. The `agent_role` field on `Agent` is one of `LISTING_AGENT`, `BUYER_AGENT`, or `DUAL_AGENT`, and the `kind` field on `Contingency` is one of `INSPECTION`, `APPRAISAL`, or `FINANCING`.

State checks run after authentication, role permission, ownership, and existence — so a request to act on an entity in the wrong state for the requested transition is rejected with `ERR_INVALID_STATE` and HTTP 409 unless a more specific error code (such as `ERR_OFFER_NOT_SUBMITTED`, `ERR_LISTING_ALREADY_UNDER_CONTRACT`, `ERR_LOCKBOX_STATE`, or `ERR_LOCKBOX_NOT_ARMED`) applies. The validation order across an action endpoint is therefore: authentication missing → authentication invalid → role forbidden → resource not found → not the owner → state-specific errors → time/business-window errors → schema-fiscal errors.

## 3. Business Logic and Workflows

### 3.1. Agent Onboarding and Editing

A new agent is brought onto the platform by an `MlsAdmin` operator who supplies the agent's `full_name`, `brokerage_name`, the side of the transaction the agent represents in `agent_role` (one of `LISTING_AGENT`, `BUYER_AGENT`, or `DUAL_AGENT`), and the state-issued `license_number` (which must be unique across active agents). An optional `brokerage_split_pct` may be supplied; if omitted, the agent's split defaults to 0.70 — that is, seventy percent of the side's commission flows to the agent and the remainder to the brokerage. The split is stored to four decimal places, must be strictly greater than zero, and must not exceed 1.0.

A newly registered agent's `status` is `ACTIVE`. An admin may later edit the agent's `brokerage_split_pct` or move them between `ACTIVE` and `SUSPENDED` via the admin-only edit capability, supplying the current `version` for optimistic concurrency. Other fields are immutable after registration. Both editable changes refresh the agent's `updated_at` and increment `version` by 1.

### 3.2. Bringing a Listing to Market

A `ListingAgent` puts a property on the market by supplying their own agent identifier as `listing_agent_id`, a human-readable `address_line`, a five-digit `zip_code` used downstream as the geography filter for buyer matching, an integer asking price in cents `list_price_cents`, the number of `bedrooms` as a whole number between 0 and 20 inclusive, the number of `bathrooms` as a non-negative number up to 20 in multiples of 0.5, an array of amenity tags in `features` (such as `POOL`, `GARAGE`, `FIREPLACE`), the buyer-side commission fraction `co_op_pct`, and the combined commission fraction `total_commission_pct`. The server requires that `listing_agent_id` equal `X-User-ID`; a `ListingAgent` cannot list property on behalf of another agent.

Listing fields are validated as a group: the asking price must be at least 1,000,000 cents (ten thousand US dollars), the buyer-side co-op fraction must lie between 0 and 0.06 inclusive, and the combined commission fraction must be at least as large as the co-op fraction and no greater than 0.10. If any of these is violated the listing is rejected with `ERR_INVALID_LISTING_FIELDS`. The `zip_code` must be exactly 5 digits. On success the listing is created in `ACTIVE` status with no accepted offer (`accepted_offer_id` is null) and a `showing_count` of zero, and the response carries the listing's server-minted `id`, `created_at`, and starting `version`.

After creation a `ListingAgent` may edit the listing's `list_price_cents`, `features`, `co_op_pct`, and `total_commission_pct` through the listing edit capability, which consumes a `version` for optimistic concurrency. The same fiscal constraints apply on edit as on creation; mismatched versions are rejected with `ERR_VERSION_CONFLICT`. A listing in `ACTIVE` status may be withdrawn from the market — but only if no offer on it is currently in `SUBMITTED` status; submitted offers must first be either rejected or allowed to expire, otherwise the withdraw is rejected as an invalid state. Withdrawing transitions the listing from `ACTIVE` to `WITHDRAWN`, cancels every open showing on the listing (each `REQUESTED` or `SCHEDULED` row transitions to `CANCELLED`), and disarms the attached lockbox (taking it from `ARMED` to `DISARMED`).

If a listing remains in `ACTIVE` status at the moment the logical clock advances to or past 180 days after its `created_at`, the next sweep auto-transitions it from `ACTIVE` to `EXPIRED`: every open showing on it is cancelled, every offer still in `SUBMITTED` status becomes `EXPIRED`, every `OPEN` counter becomes `EXPIRED`, and the attached lockbox is disarmed.

### 3.3. Buyer Profile and Editing

A `BuyerAgent` creates a buyer profile by supplying their own identifier as `buyer_agent_id`, the buyer's `full_name`, the upper bound the buyer is willing to pay in `max_price_cents`, the lower bound they will consider in `min_price_cents`, the minimum number of bedrooms required as `min_bedrooms` (0 to 20), the minimum number of bathrooms required as `min_bathrooms` (multiples of 0.5), a non-empty array `desired_zips` of five-digit ZIPs the buyer wants, and an array `desired_features` of tags the buyer prefers. The lower bound must not exceed the upper bound, and the desired-ZIP array may not be empty. Either violation triggers `ERR_INVALID_BUYER_FIELDS`. The server enforces that `buyer_agent_id` equal `X-User-ID`.

Buyer profiles begin in `ACTIVE` status and can be edited by the originating `BuyerAgent` to change any of the preference fields, including switching the buyer's `status` between `ACTIVE` and `WITHDRAWN`. Edits consume a `version` and otherwise apply the same field-validity rules as creation. The buyer's `status` becomes `SOLD` automatically when an offer they made closes, as part of the listing close cascade (see §3.6).

### 3.4. Buyer-Listing Matching

Either side may query for ranked candidates from the other side. A buyer-side request lists candidate listings for a given buyer; a listing-side request lists candidate buyers for a given listing. Both queries draw from active rows only — a candidate must have `status` of `ACTIVE` to enter the pool — and both rank by a single matching score in the range 0 to 100.

The score is a weighted sum of four sub-fits. The price-fit subscore is 100 when the listing's `list_price_cents` lies between the buyer's `min_price_cents` and `max_price_cents` inclusive. If the listing's price exceeds the buyer's maximum, the subscore decays linearly over a band equal to ten percent of the buyer's maximum: the amount by which the listing exceeds the maximum is divided by that band (or by 1 if the band would otherwise be zero), multiplied by 100, and subtracted from 100, with the result clipped at zero. The mirrored decay applies when the listing's price is below the buyer's minimum, using ten percent of the minimum as the band. The location-fit subscore is 100 when the listing's `zip_code` appears in the buyer's `desired_zips` array, and 0 otherwise. The bedroom-bathroom subscore is 100 when both the listing's `bedrooms` are at least the buyer's `min_bedrooms` and the listing's `bathrooms` are at least the buyer's `min_bathrooms`; it is 50 when exactly one of the two thresholds is met; it is 0 when neither is. The feature-fit subscore is 100 when the buyer's `desired_features` array is empty (no preference); otherwise it is the size of the overlap between `desired_features` and the listing's `features` divided by the size of `desired_features`, multiplied by 100, locally rounded half-up to four decimal places before entering the weighted sum.

Once the four subscores are computed, they are combined with fixed weights of 0.40 for price fit, 0.25 for location fit, 0.20 for bedroom-bathroom fit, and 0.15 for feature fit, in that order. The weighted sum is then rounded half-up to two decimal places exactly once, producing the final score. Candidates whose score is strictly less than 50 are excluded from the result. Survivors are sorted by score descending, with ties broken by `created_at` ascending and then by `id` ascending. The response is the ranked array (carrying the candidate's identifier — `listing_id` on the buyer-side query, `buyer_id` on the listing-side query — and the score), and an empty pool returns an empty array with HTTP 200, not an error.

### 3.5. Showings and the Lockbox

A `BuyerAgent` requests a showing by supplying their own identifier as `buyer_agent_id`, the `buyer_id` they intend to show, a `start_at`, and an `end_at`. The window must be at least 15 minutes and no more than 4 hours long, with `end_at` strictly after `start_at`, and `start_at` must be strictly in the future at the moment the request is made; otherwise the request is rejected with `ERR_INVALID_SHOWING_WINDOW`. The newly created appointment is in `REQUESTED` status.

A `ListingAgent` approves the showing, transitioning it from `REQUESTED` to `SCHEDULED`. Approval has three independent preconditions: the listing must be `ACTIVE`, the attached lockbox must be `ARMED`, and no other `SCHEDULED` showing on the same listing may occupy a time interval that overlaps `[start_at, end_at)` — these are half-open intervals, so an appointment whose `end_at` equals another's `start_at`, or whose `start_at` equals another's `end_at`, is adjacent and allowed. A lockbox that is not `ARMED` causes `ERR_LOCKBOX_NOT_ARMED`; a colliding interval causes `ERR_SHOWING_TIME_OVERLAP`. On approval the server vends the lockbox's current `access_code` in the response body, stamps the appointment's `lockbox_access_granted_at` with the current logical time, and refreshes `showing_count` on the listing — `showing_count` always equals the number of showings on the listing whose status is `SCHEDULED` or `COMPLETED`.

Mounting a lockbox on an `ACTIVE` listing is a `ListingAgent` action that takes a unique `serial_number` and creates the lockbox row in `ARMED` status; the server mints the initial `access_code` and records `code_rotated_at`. Arming a lockbox that is `DISARMED` (only valid while the listing is `ACTIVE`) rotates the `access_code` to a new server-minted 6-digit string and updates `code_rotated_at`. Disarming a lockbox that is `ARMED` is permitted at any time; retiring a `DISARMED` lockbox terminates its lifecycle and is permitted any time. The implicit transitions are equally important: when a listing transitions from `ACTIVE` to `WITHDRAWN`, or from `ACTIVE` to `EXPIRED` via the sweep, the attached lockbox is disarmed by cascade. When a listing transitions from `UNDER_CONTRACT` to `SOLD`, the attached lockbox is retired by cascade — moving directly from `ARMED` (the state required for showings under the contingent listing) to `RETIRED`.

Once a showing is `SCHEDULED`, three things can happen. If `now()` reaches or passes `end_at` without the access code having been vended (`lockbox_access_granted_at` is still null), the sweep records the appointment as `NO_SHOW` and decrements `showing_count` (since the row had previously been counted as `SCHEDULED`). If the buyer agent completes the showing, the appointment transitions from `SCHEDULED` to `COMPLETED` — completion requires that the access code was previously vended (`lockbox_access_granted_at` is not null) and that `now()` is at or past `end_at`. And either side may cancel a `SCHEDULED` appointment any time strictly before `start_at`; the row becomes `CANCELLED` and `showing_count` is decremented. A `REQUESTED` (never-approved) appointment may likewise be cancelled by either side at any time, with no effect on `showing_count` (it was never included).

### 3.6. Offers, Counters, and the Negotiation Chain

A `BuyerAgent` submits an offer by supplying the `buyer_id`, a positive `offer_price_cents`, an `earnest_money_cents` deposit, an optional `estimated_seller_concessions_cents` (defaulting to 0), and an `expires_at` deadline. For round-1 offers the `parent_counter_id` is null; for rebound offers it is set to the counter being responded to (see below). The earnest money and the estimated concessions must each be no greater than the offer price; either violation triggers `ERR_INVALID_OFFER_FISCAL`. The `expires_at` deadline must be strictly in the future at the moment of submission; otherwise the submission is rejected with `ERR_OFFER_EXPIRED`. New offers begin in `SUBMITTED` status with `round_no` of 1, except rebound offers which carry the incremented round number described below.

Once an offer is `SUBMITTED`, four outcomes are possible:

- **Acceptance by the listing agent.** Accepting transitions the offer from `SUBMITTED` to `ACCEPTED` and drives the listing from `ACTIVE` to `UNDER_CONTRACT`. Acceptance requires that the listing be `ACTIVE`, the offer be `SUBMITTED`, and the offer's `expires_at` be strictly in the future; if the deadline has passed, `ERR_OFFER_EXPIRED` is returned. The cascade is the single most consequential action in the system. The accepted offer's `id` is recorded on the listing as `accepted_offer_id`. All other offers on the same listing whose status was `SUBMITTED` are reclassified as `REJECTED` — this is the multiple-offer auto-rejection. Every `OPEN` counter tied to any of those just-rejected offers transitions to `WITHDRAWN`. The accepted offer's `provisional_net_to_seller_cents` is computed using the provisional variant of the offer net-to-seller calculation in §3.8, and a `CommissionSplit` row with `variant` of `PROVISIONAL` is emitted using the commission-split calculation in §3.8.
- **Counter by the listing agent.** Issuing a counter on a `SUBMITTED` offer transitions the offer from `SUBMITTED` to `COUNTERED` and creates a new `Counter` row in `OPEN` status. The counter carries an immutable `counter_price_cents`, an immutable `counter_concessions_cents` adjustment, and a `counter_expires_at` deadline that must be strictly in the future. The original offer's `expires_at` must likewise be strictly in the future, and the listing must still be `ACTIVE`. The `Counter` row's `offer_id` points to the offer being countered.
- **Rejection by the listing agent.** Rejecting a `SUBMITTED` offer transitions it directly to `REJECTED`. Any `OPEN` counter previously tied to this offer (which would be the case only if a rejection followed an offer–rebound–counter cycle — see below) transitions to `WITHDRAWN`.
- **Withdrawal by the buyer agent.** A `BuyerAgent` may withdraw their own offer while it is still `SUBMITTED`. The offer transitions from `SUBMITTED` to `WITHDRAWN`, and any `OPEN` counter tied to that offer transitions to `WITHDRAWN`. Withdrawing an offer that is no longer `SUBMITTED` returns `ERR_OFFER_NOT_SUBMITTED`; in particular, a `ListingAgent`'s simultaneous accept races the withdraw, and whichever lands first leaves the other to see `ERR_OFFER_NOT_SUBMITTED`.

Any attempt to act on an offer that is no longer in `SUBMITTED` status — accept, counter, reject, or withdraw — yields `ERR_OFFER_NOT_SUBMITTED`. A separate, more specific error code applies in one race: when two listing agents (or the same listing agent operating on two siblings) attempt to accept on a listing that has just transitioned to `UNDER_CONTRACT`, the loser receives `ERR_LISTING_ALREADY_UNDER_CONTRACT` rather than the generic invalid-state error. An offer that is still `SUBMITTED` at the moment the logical clock reaches its `expires_at` is auto-transitioned to `EXPIRED` by the sweep, and any `OPEN` counter tied to it transitions to `WITHDRAWN`.

Rebounding closes the loop and makes the offer chain cyclic. A `BuyerAgent` rebounds an open counter by submitting a fresh offer in response. The rebound action requires the parent offer to be in `COUNTERED` status, an `OPEN` counter to exist on that offer (whose `id` becomes the new offer's `parent_counter_id`), and the current logical time to be strictly less than the counter's `counter_expires_at`; a rebound past the counter deadline is rejected with `ERR_COUNTER_EXPIRED`. The action takes the buyer's new `offer_price_cents`, new `earnest_money_cents`, an optional new `estimated_seller_concessions_cents`, and a new `expires_at`. The result is two writes: the original counter transitions from `OPEN` to `REBOUND`, and a new `Offer` row is created with `status` of `SUBMITTED`, its `parent_counter_id` set to the just-rebounded counter, and its `round_no` set to the previous offer's `round_no` plus 1. The previous offer remains in `COUNTERED` — it does not revisit `SUBMITTED` — but the negotiation chain as a whole has advanced one round. A counter that reaches its `counter_expires_at` while still `OPEN` is auto-transitioned to `EXPIRED` by the sweep.

### 3.7. The Contingent Period and the Path to Close

Once a listing is `UNDER_CONTRACT`, the buyer agent may attach one or more contingencies to the accepted offer through the contingencies endpoint. Each contingency carries an `offer_id` (which must equal the listing's `accepted_offer_id`), a `kind` of `INSPECTION`, `APPRAISAL`, or `FINANCING`, and a `deadline_at` by which the contingency must be `SATISFIED` or `WAIVED`. The deadline must be strictly after the accepted offer's acceptance time and strictly in the future at the moment of creation; either violation yields `ERR_CONTINGENCY_DEADLINE_INVALID`. A new contingency is `PENDING`.

A `PENDING` contingency may be marked `SATISFIED` by the `BuyerAgent` provided the listing is still `UNDER_CONTRACT` and the current logical time is strictly less than the contingency's `deadline_at`; or `WAIVED` by the `BuyerAgent` provided only that the listing is still `UNDER_CONTRACT` (waiving is allowed even past the deadline, since waiving is the buyer's explicit decision to forgo the protection); or `FAILED` either explicitly by the `BuyerAgent` or implicitly by the sweep once the logical clock reaches or passes the contingency's `deadline_at` while the contingency is still `PENDING`.

A failed contingency cascades. The accepted offer is withdrawn (its `status` becomes `WITHDRAWN`); every other `PENDING` contingency on the same offer is transitioned to `FAILED`; the listing's `accepted_offer_id` is cleared back to null; and the listing transitions from `UNDER_CONTRACT` back to `ACTIVE`. No new `CommissionSplit` row is emitted by this cascade — the previously-emitted `PROVISIONAL` row remains in storage but the listing's `updated_at` refresh signals that it is now stale relative to the listing's current state. When two contingencies on the same accepted offer reach their deadlines in the same sweep, the sweep processes them in `(created_at, id)` ascending order; the first to fail drives the rebound cascade above, the second is recorded as `FAILED` by the sibling-fail side-effect of that cascade rather than by a fresh trigger, and any explicit redundant fail call on the second after it has already been cascade-failed returns `ERR_CONTINGENCY_ALREADY_FAILED`.

Closing a listing is the listing agent's explicit move from `UNDER_CONTRACT` to `SOLD`. The action requires that every `Contingency` attached to the accepted offer be in `SATISFIED` or `WAIVED` status (a `PENDING` or `FAILED` contingency blocks the close as an invalid state). On close, the buyer who made the accepted offer has their `status` set to `SOLD`, a `CommissionSplit` row with `variant` of `FINAL` is emitted using the commission-split calculation in §3.8, every showing on the listing whose status was `REQUESTED` or `SCHEDULED` is cancelled, and the attached lockbox is retired.

### 3.8. Commission Splits and Net-to-Seller

Two distinct snapshots of the commission split are emitted during a successful sale. The `PROVISIONAL` snapshot is computed at the moment the listing transitions from `ACTIVE` to `UNDER_CONTRACT` — i.e., at offer acceptance — and captures the buyer agent's identity and `brokerage_split_pct` as of that moment, so that subsequent agent edits do not retroactively alter the row. The `FINAL` snapshot is computed at the moment the listing transitions from `UNDER_CONTRACT` to `SOLD` — i.e., at close — and uses each agent's `brokerage_split_pct` as it stands at close. If an agent's brokerage split changed between acceptance and close, the `FINAL` row diverges from the `PROVISIONAL` row even though the sale price is identical; the `PROVISIONAL` row is not retroactively updated, and both rows coexist in storage.

Both variants follow the same pinned arithmetic. The inputs are the accepted offer's `offer_price_cents` (recorded on the snapshot as `sale_price_cents`), the listing's `total_commission_pct` and `co_op_pct`, and each side's agent `brokerage_split_pct`. The steps run in this order, and no step may be reordered. First, the gross commission in whole cents, `gross_commission_cents`, is the sale price multiplied by the total commission fraction, with the result rounded half-up to a whole cent. Second, the buyer-side portion `buyer_side_cents` is the sale price multiplied by the co-op fraction, rounded half-up to a whole cent. Third, the listing-side portion `listing_side_cents` is the gross commission minus the buyer-side portion — a residual assignment that guarantees the two side totals add up exactly to the gross, with no penny drift; the listing side is **never** computed independently from the total fraction minus the co-op fraction. Fourth, the listing agent's take `listing_agent_cents` is the listing-side portion multiplied by the listing agent's `brokerage_split_pct`, rounded half-up; the listing brokerage's take `listing_brokerage_cents` is the residual `listing_side_cents - listing_agent_cents`. Symmetrically, the buyer agent's take `buyer_agent_cents` is the buyer-side portion multiplied by the buyer agent's `brokerage_split_pct`, rounded half-up; and the buyer brokerage's take `buyer_brokerage_cents` is the residual `buyer_side_cents - buyer_agent_cents`.

The provisional net-to-seller, stored on the accepted offer as `provisional_net_to_seller_cents`, is calculated at acceptance time as the offer's `offer_price_cents` minus the offer's `estimated_seller_concessions_cents`, minus the buyer-side commission obtained by multiplying `offer_price_cents` by the listing's `co_op_pct` and rounding half-up to a whole cent, minus the listing-side commission obtained by multiplying `offer_price_cents` by the difference between the listing's `total_commission_pct` and `co_op_pct` and rounding half-up to a whole cent. This is the forward-looking estimate visible at acceptance.

At close, the same net-to-seller arithmetic is recomputed using actuals. The sale price is again the accepted offer's `offer_price_cents`, but the seller-concessions term is replaced by the sum of `counter_concessions_cents` taken from every `Counter` row along the negotiation chain that reached the accepted offer (only counters in `REBOUND` status are summed, ordered by `created_at` ascending), capped so that the cumulative actual concessions cannot exceed the offer price; and the commission deductions are taken from the `FINAL` `CommissionSplit` row — `buyer_side_cents` for the buyer-side deduction and `listing_side_cents` for the listing-side deduction. The two variants can therefore differ because actual concessions may exceed the original estimate and because any change to `brokerage_split_pct` between acceptance and close shifts how commission is distributed (though not the totals, except where the rounding residual moves).

### 3.9. The Admin Sweep in Operation

The admin clock-advance capability takes a target instant `to` in ISO 8601 form and moves the server's logical clock to that instant, returning the resulting `now`. The admin sweep capability then traverses the time-gated rows in the entity order `Contingency`, `Offer`, `Counter`, `ShowingAppointment`, `Listing`, and within each type in `(created_at, id)` ascending order. Within each pass it applies exactly the auto-transitions defined above: a `PENDING` contingency whose `deadline_at` is in the past becomes `FAILED` (with the listing rebound cascade); a `SUBMITTED` offer whose `expires_at` is in the past becomes `EXPIRED` (with associated `OPEN` counters becoming `WITHDRAWN`); an `OPEN` counter whose `counter_expires_at` is in the past becomes `EXPIRED`; a `SCHEDULED` showing whose `end_at` is in the past but whose `lockbox_access_granted_at` is still null becomes `NO_SHOW` (and `showing_count` is decremented); and an `ACTIVE` listing whose `created_at` is at least 180 days before `now()` becomes `EXPIRED` (with the full open-showings, submitted-offers, and lockbox-disarm cascade). The sweep response surfaces the count of rows transitioned in each of those five categories.

## 4. Endpoint Definitions

All endpoints in the table below are mounted at the system root. New resource creation returns HTTP 201; non-create successful operations return HTTP 200. List endpoints return 200 with an empty array when no rows match. Path resources are validated left-to-right, and authorization runs before any state or business check.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/agents` | Register a new agent. | `MlsAdmin` |
| GET | `/agents/{id}` | Fetch an agent. | `ListingAgent`, `BuyerAgent`, `MlsAdmin` |
| PATCH | `/agents/{id}` | Edit an agent's brokerage split or status (OCC). | `MlsAdmin` |
| POST | `/listings` | Create a new active listing. | `ListingAgent` |
| GET | `/listings/{id}` | Fetch a listing. | `ListingAgent`, `BuyerAgent`, `MlsAdmin` |
| GET | `/listings` | List listings with optional filters. | `ListingAgent`, `BuyerAgent`, `MlsAdmin` |
| PATCH | `/listings/{id}` | Edit price, features, commission rates, or status (OCC). | `ListingAgent` |
| POST | `/listings/{id}/withdraw` | Withdraw an `ACTIVE` listing from market. | `ListingAgent` |
| POST | `/listings/{id}/close` | Close an `UNDER_CONTRACT` listing (mark `SOLD`). | `ListingAgent` |
| GET | `/listings/{id}/buyer-matches` | Ranked candidate buyers for this listing. | `ListingAgent`, `MlsAdmin` |
| POST | `/buyers` | Register a buyer profile. | `BuyerAgent` |
| GET | `/buyers/{id}` | Fetch a buyer. | `BuyerAgent`, `MlsAdmin` |
| PATCH | `/buyers/{id}` | Edit buyer preferences (OCC). | `BuyerAgent` |
| GET | `/buyers/{id}/matches` | Ranked candidate listings for this buyer. | `BuyerAgent`, `MlsAdmin` |
| POST | `/listings/{listing_id}/lockbox` | Mount a lockbox on an `ACTIVE` listing. | `ListingAgent` |
| POST | `/listings/{listing_id}/lockbox/arm` | Arm (or re-arm) the lockbox; rotates `access_code`. | `ListingAgent` |
| POST | `/listings/{listing_id}/lockbox/disarm` | Disarm the lockbox. | `ListingAgent` |
| POST | `/listings/{listing_id}/lockbox/retire` | Retire a `DISARMED` lockbox. | `ListingAgent` |
| POST | `/listings/{listing_id}/showings` | Request a showing window. | `BuyerAgent` |
| POST | `/listings/{listing_id}/showings/{id}/approve` | Approve a requested showing. | `ListingAgent` |
| POST | `/listings/{listing_id}/showings/{id}/complete` | Report a scheduled showing as completed. | `BuyerAgent` |
| POST | `/listings/{listing_id}/showings/{id}/cancel` | Cancel a `REQUESTED` or `SCHEDULED` showing. | `ListingAgent`, `BuyerAgent` |
| POST | `/listings/{listing_id}/offers` | Submit a new offer or a rebound offer. | `BuyerAgent` |
| GET | `/listings/{listing_id}/offers` | List offers on a listing. | `ListingAgent`, `MlsAdmin` |
| POST | `/listings/{listing_id}/offers/{id}/accept` | Listing agent accepts an offer. | `ListingAgent` |
| POST | `/listings/{listing_id}/offers/{id}/reject` | Listing agent rejects an offer. | `ListingAgent` |
| POST | `/listings/{listing_id}/offers/{id}/withdraw` | Buyer agent withdraws their own offer. | `BuyerAgent` |
| POST | `/listings/{listing_id}/offers/{id}/counter` | Listing agent issues a counter. | `ListingAgent` |
| POST | `/listings/{listing_id}/offers/{id}/rebound` | Buyer agent rebounds an open counter. | `BuyerAgent` |
| POST | `/listings/{listing_id}/contingencies` | Attach a contingency to the accepted offer. | `BuyerAgent` |
| POST | `/listings/{listing_id}/contingencies/{id}/satisfy` | Mark a contingency `SATISFIED`. | `BuyerAgent` |
| POST | `/listings/{listing_id}/contingencies/{id}/waive` | Waive a contingency. | `BuyerAgent` |
| POST | `/listings/{listing_id}/contingencies/{id}/fail` | Fail a contingency; cascades the listing back to `ACTIVE`. | `BuyerAgent` |
| GET | `/listings/{listing_id}/commission-splits` | Return all `CommissionSplit` rows for a listing. | `ListingAgent`, `MlsAdmin` |
| POST | `/_clock/advance` | Advance the server's logical clock. | `MlsAdmin` |
| POST | `/_sweep/run` | Run the deferred-action sweep. | `MlsAdmin` |

The list-listings endpoint accepts the optional query parameters `status`, `zip_code`, `min_price_cents`, `max_price_cents`, `limit`, and `offset`. The list-offers endpoint accepts the optional query parameters `status`, `limit`, and `offset`. The commission-splits endpoint accepts the optional query parameters `variant`, `limit`, and `offset`. The match endpoints accept `limit` and `offset`. The clock-advance body carries a `to` field.

## 5. Error Code Catalogue

The trigger conditions for each error are described inline in §2 and §3. The table below records only the canonical identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_ALREADY_UNDER_CONTRACT` | 409 |
| `ERR_OFFER_NOT_SUBMITTED` | 409 |
| `ERR_LOCKBOX_STATE` | 409 |
| `ERR_LOCKBOX_NOT_ARMED` | 409 |
| `ERR_SHOWING_TIME_OVERLAP` | 409 |
| `ERR_COUNTER_EXPIRED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_CONTINGENCY_ALREADY_FAILED` | 409 |
| `ERR_CONTINGENCY_DEADLINE_INVALID` | 422 |
| `ERR_INVALID_LISTING_FIELDS` | 422 |
| `ERR_INVALID_BUYER_FIELDS` | 422 |
| `ERR_INVALID_OFFER_FISCAL` | 422 |
| `ERR_INVALID_SHOWING_WINDOW` | 422 |
