# Convention Housing Bureau Operations API — Product Requirements Document

## 1. Introduction

A convention housing bureau sits between three parties who each keep their own books: the client association that owns the convention, the hotels that hold rooms for it, and the thousands of delegates who book those rooms. Today that intermediation runs on spreadsheets and email. Room blocks are negotiated property by property with no guarantee that commission, rebate and cutoff terms match the contract the association signed; VIP and exhibitor allotments are carved by hand and nobody can prove who approved them; rogue housing companies cold-call the attendee list and the bureau finds out weeks later; and when the event ends, the commission invoice the bureau issues rarely agrees with the pickup report the hotel files. Every one of those failures is a cash failure, and most of them are only visible after the attrition penalty deadline has already passed.

This document specifies the Convention Housing Bureau Operations API, the system of record that replaces that patchwork. The API is mounted under `/housing`. It treats the room block as what it economically is — a finite, dated pool of room-nights that is contracted once, carved into segregated allotments, committed by attendee reservations, reduced under contractual reduction rights, and finally released, reported and billed. Every movement of a room-night is attributable, every approval has a named second pair of eyes, and every monetary figure is derived from a pinned formula rather than from whoever last edited the workbook.

Two design commitments run through the whole specification and are worth stating up front. First, **time is explicit**: cutoff dates, attrition deadlines, arrival dates and event end dates are all evaluated against a server-side logical clock, never against wall-clock time, so that a full housing cycle can be driven deterministically. Second, **money never floats**: rates, rebates, commissions and penalties are integers denominated in cents, and every rounding step states both its position in the evaluation order and its direction.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for every endpoint: authentication, the response envelope, pagination, resource identity, the logical clock, arithmetic discipline, the block inventory invariant, concurrency protection, duty segregation, and the order in which a request's failure modes are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which that principal is acting. Six roles are recognised, spelled exactly as follows: `BureauCoordinator`, `BureauController`, `HotelManager`, `EventOrganizer`, `Attendee`, and `ComplianceOfficer`. If either header is missing, or if `X-User-Role` is not one of these six strings, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the headers are well formed but the declared role is not listed among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (403).

Three of the six roles are **entity-backed**, meaning `X-User-ID` is the `id` of a persisted resource and ownership checks compare a foreign-key field on the target resource to that value:

- When `X-User-Role` is `HotelManager`, `X-User-ID` is the `id` of the acting `Hotel`; ownership checks on any resource that references a `Hotel` compare the resource's foreign-key field to `X-User-ID`. For a housing block this means the block's `hotel_id`; for a reservation, a pickup report, a rooming-list batch or a commission invoice it means the `hotel_id` of the `HotelBlock` the resource hangs from.
- When `X-User-Role` is `EventOrganizer`, `X-User-ID` is the `id` of the acting `Event`; ownership checks compare the target block's `event_id` to `X-User-ID`.
- When `X-User-Role` is `Attendee`, `X-User-ID` is the `id` of the acting `Attendee`; ownership checks on a reservation compare the reservation's `attendee_id` to `X-User-ID`.

The remaining three roles are **opaque operator identities**. When `X-User-Role` is `BureauCoordinator`, `BureauController`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit trail — as `requested_by_user_id` on a sub-block or an attrition reduction, and as `approved_by_user_id` when the same kind of resource is approved — but it never compares it to any entity's `id`.

A violation of an ownership check yields `ERR_NOT_RESOURCE_OWNER` (403). Ownership is enforced only on the write operations enumerated in §2.10 step 6; read endpoints are not ownership-scoped.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10 when absent, may not be smaller than 1, and may not be larger than 100. `offset` is the number of items to skip; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (400).

Unless a specific endpoint declares a different ordering, list endpoints return their items sorted by `created_at` in ascending order. Four endpoints declare a different ordering and are called out where they are described: the portal hotel list is ordered by `distance_to_venue_miles` ascending and then by `name` ascending; a block's transmission history is ordered by `batch_seq` ascending; a block's pickup history is ordered by `as_of_date` ascending; a block's reduction requests are ordered by `effective_date` ascending and then `created_at` ascending; and a vendor's incidents are ordered by `occurred_at` ascending and then `contact_channel` ascending.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object. `total_count` is the number of items matching the filters before pagination is applied, and `has_more` is true exactly when items remain beyond the current window.

### 2.4. Resource Identity, Timestamps and Revision Counters

Every resource the API creates carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`). Most resources additionally carry:

- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the resource, including mutations the server performs on its own initiative as part of a cascade.

Two record types are append-only ledgers of fact rather than mutable resources, and they therefore carry **only** `id` and `created_at`: a rooming-list transmission batch and a hotel pickup report. Neither `updated_at` nor `version` exists on those two record types at all.

Derived fields count as mutations for this purpose. When a reservation is cancelled and the parent sub-block's `committed_rooms`, `available_rooms` and `inventory_status` are recomputed as a consequence, the sub-block's `updated_at` is refreshed and its `version` increases; the same holds for the event-level aggregates `total_contracted_room_nights`, `total_confirmed_room_nights`, `commission_collected_cents` and `housing_posture` on the owning `Event`.

### 2.5. The Logical Housing Clock

Every date gate in this system — reservation cutoffs, the attrition-rights deadline, no-show arrival checks, and post-event closure — reads a single server-side **logical clock** rather than real wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is repositioned it holds that value and never falls back to real time. A `BureauCoordinator` repositions it by supplying a `to_iso8601` instant, and the response reports both the new `current_utc` and the `previous_utc` it replaced. Repositioning the clock changes no entity state and runs no sweeps: nothing is opened, cut off, closed or released as a side effect of moving time.

Calendar dates are compared against the clock at midnight UTC. A gate phrased "strictly before date D" is satisfied when the clock reads earlier than D at `00:00:00Z`; a gate phrased "at or after date D" is satisfied when the clock reads D at `00:00:00Z` or any later instant. Two consequences deserve emphasis, because they are the boundaries the bureau argues about most: a block may be opened only while the clock is strictly before the block's `cutoff_date` at midnight UTC, and a block-reduction request must arrive strictly before the event's `attrition_deadline_date` at midnight UTC — a request filed at exactly that midnight is already too late.

### 2.6. Room-Night Arithmetic, Money and Rounding Discipline

Nights, not days, are the unit of housing inventory. A stay from a check-in date to a check-out date occupies the **half-open** interval of nights beginning on the check-in date and ending on the night before the check-out date; the number of nights it occupies is the number of whole days between the two dates. A departure on a given date and an arrival on that same date therefore do not compete for the same night. The event's own `night_count` is derived the same way: it is the number of whole days from `event_start_date` to `event_end_date`, and it is the number of billable nights in the official housing window.

All money is expressed as an integer number of cents; there are no fractional cents anywhere in the API. Rates that are fractions — `commission_pct`, `standard_commission_pct`, `room_tax_pct`, `room_tax_pct_snapshot`, `reduction_rights_pct` — are decimal numbers and preserve the precision they were supplied with. Wherever a computation produces a non-integral cent or room-night figure, it is rounded to a whole number using the **round half up** rule: a fractional part of exactly one half rounds away from zero, upward. Room and room-night counts are always integers.

Rounding **position** is part of the contract, not an implementation detail, and each formula in §3 states where its rounding step falls. The single most consequential instance is the taxed nightly amount on a reservation: the nightly rate is taxed and rounded to whole cents *first*, and only then multiplied by the number of nights. Summing untaxed nights and taxing the sum is a different and incorrect computation that produces a different total.

### 2.7. The Block Inventory Invariant

A contracted housing block is a closed room-per-night ledger, and the system holds that ledger balanced at all times. For any contracted block, the current `contracted_rooms_per_night` always equals the sum of three quantities: the `unassigned_rooms_per_night` still available to carve, the `released_rooms_per_night` permanently handed back to the hotel, and the total `allotted_rooms` across every sub-block of the block whose `approval_status` is `PENDING_APPROVAL`, `APPROVED`, or `RELEASED`. Sub-blocks whose `approval_status` is `REJECTED` contribute nothing, because rejection returns their rooms to the pool and zeroes their allotment.

Rooms move between the three buckets and never appear or vanish. Carving a sub-block moves rooms out of `unassigned_rooms_per_night` (or, for a nested carve, out of the parent sub-block's `allotted_rooms`). Rejecting a sub-block moves them back the way they came. Releasing rooms moves them from a sub-block's `allotted_rooms` into that sub-block's `released_rooms` and into the block's `released_rooms_per_night`. Exercising a reduction shrinks `contracted_rooms_per_night` itself and simultaneously draws the same number of rooms out of `unassigned_rooms_per_night` and sub-block allotments, so the identity survives the reduction. The cutoff sweep converts every unsold room — sub-block headroom and unassigned inventory alike — into `released_rooms_per_night`. The invariant holds before and after each of these operations.

Separately, `original_contracted_rooms_per_night` is a snapshot frozen at contract signature and is never touched afterwards; it is the base against which reduction rights are measured, so that a block cannot be reduced, and then reduced again against the already-shrunken figure.

### 2.8. Stale-Block Protection on Terms Submissions and Carves

Two write operations target a `HotelBlock` whose *content* the caller must have read before writing, and where no state precondition can catch a write computed against a figure the caller never re-read. Both are therefore protected by optimistic concurrency control on the block's `version`.

A terms submission — `POST /housing/hotel-blocks/{id}/terms` — requires a non-optional `expected_hotel_block_version` field in its payload, carrying the client's last observed `version` of the target `HotelBlock`. If that value does not equal the block's current `version`, the submission is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412). This check is what stops a coordinator from overwriting terms they never saw: a terms submission legitimately supersedes the previously submitted rate, commission, rebate, cutoff and reduction rights, and the block is in `DRAFT` or `CHANGES_REQUESTED` either way, so no state precondition would object.

A sub-block carve — `POST /housing/hotel-blocks/{id}/sub-blocks` — likewise requires a non-optional `expected_hotel_block_version` carrying the client's last observed `version` of the parent `HotelBlock`, and a mismatch against the block's current `version` is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412). Carving is additive and would legitimately succeed from the same block state, so the stale-version check is the only thing that stops a carve sized against an `unassigned_rooms_per_night` figure that has since moved.

No other endpoint takes a version field. Every other write is guarded by its own state, ownership, temporal and fiscal preconditions, and callers must not send `expected_hotel_block_version` to them.

### 2.9. Segregation of Duties

Four decisions in this system require a second pair of eyes, and the system refuses to let one person be both pairs. On sub-block approval, on sub-block rejection, on attrition-reduction approval and on attrition-reduction rejection, the acting `X-User-ID` must differ from the `requested_by_user_id` recorded on the target resource when it was filed. If they are equal, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Where an approval succeeds, the acting identifier is persisted as `approved_by_user_id` on the resource, giving an auditable requester/approver pair; on a rejection the resource simply moves to its rejected state and `approved_by_user_id` remains null.

The requesting and approving capacities are also split across roles: a `BureauCoordinator` files sub-block carves and reduction requests, while only a `BureauController` may approve or reject them, reverse posted commission cash, or write off a disputed invoice. An `EventOrganizer` may also file a sub-block carve for its own event, and the same segregation rule applies to whatever identifier that carve recorded.

### 2.10. Request Evaluation Order and Nested Path Resolution

When a single request could fail several checks at once, the first failure in the following order is the one reported. This ordering is normative: a request that violates step 8 and step 18 simultaneously must return step 8's error.

1. **Header authentication.** Both `X-User-ID` and `X-User-Role` present, and the role one of the six declared names. Otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Role authorization.** The acting role appears in the endpoint's authorised list. Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Request shape.** Every required field present; every enum value inside its declared set; constrained integers non-negative; `check_out_date` strictly later than `check_in_date`; `occupants` between 1 and 4 inclusive; `limit` between 1 and 100 inclusive; `offset` at least 0; and `eligibility_code` supplied exactly when `segment` is not `GENERAL` and omitted (or null) exactly when it is `GENERAL`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint.
4. **Resource existence**, validated left-to-right with path identifiers resolved before body identifiers. The first unresolvable identifier decides the error: `ERR_EVENT_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`, `ERR_HOTEL_BLOCK_NOT_FOUND`, `ERR_SUB_BLOCK_NOT_FOUND` (for a path sub-block id, a body `sub_block_id`, or a body `parent_sub_block_id`), `ERR_ATTENDEE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_REDUCTION_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` — all 404.
5. **Uniqueness.** `ERR_EVENT_CODE_DUPLICATE` (409) when a registered event already uses the supplied `code`; `ERR_ATTENDEE_EMAIL_DUPLICATE` (409) when another attendee of the same `event_id` already uses the supplied `email`; `ERR_DUPLICATE_INCIDENT` (409) when an incident already exists with the same vendor, `attendee_id`, `contact_channel` and `occurred_at`.
6. **Ownership.** `ERR_NOT_RESOURCE_OWNER` (403) on exactly nine write operations: `POST /housing/hotel-blocks/{id}/request-changes`, `POST /housing/hotel-blocks/{id}/contract`, `POST /housing/hotel-blocks/{id}/pickup-reports`, `POST /housing/hotel-blocks/{id}/sub-blocks`, `PATCH /housing/reservations/{id}`, `POST /housing/reservations/{id}/cancel`, `POST /housing/reservations/{id}/no-show`, `POST /housing/commission-invoices/{id}/payments`, and `POST /housing/commission-invoices/{id}/dispute`.
7. **Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (403) on exactly four operations: `POST /housing/sub-blocks/{id}/approve`, `POST /housing/sub-blocks/{id}/reject`, `POST /housing/attrition-reductions/{id}/approve`, and `POST /housing/attrition-reductions/{id}/reject`.
8. **Own-state transition legality** — the target resource is in a state from which the requested transition exists. This covers block terms/request-changes/contract/open/cutoff/close, sub-block approve/reject/release, reservation change/cancel/no-show, reduction approve/reject/exercise, vendor confirm/clear, and invoice payment/reversal/dispute/adjust. The error is the one belonging to the resource family: `ERR_INVALID_BLOCK_STATE`, `ERR_BLOCK_NOT_OPEN`, `ERR_INVALID_SUB_BLOCK_STATE`, `ERR_RESERVATION_NOT_MODIFIABLE`, `ERR_INVALID_REDUCTION_STATE`, `ERR_INVALID_VENDOR_STATE`, or `ERR_INVOICE_NOT_PAYABLE` — all 409.
9. **Cross-entity state gates.** `ERR_HOTEL_SUSPENDED` (409) when a block contract is attempted while the property's `standing` is `SUSPENDED`, and `ERR_NO_APPROVED_SUB_BLOCK` (409) when a block open is attempted with no sub-block in `APPROVED`.
10. **Optimistic concurrency.** `ERR_STALE_BLOCK_VERSION` (412) on the terms submission and the sub-block carve, per §2.8.
11. **Logical-clock gates on the block lifecycle and reservation writes.** `ERR_CUTOFF_PASSED` (409) when a block open, a reservation booking or a reservation change is attempted while the clock has reached the block's `cutoff_date` at midnight UTC; `ERR_CUTOFF_NOT_REACHED` (409) when the cutoff sweep is attempted before it; `ERR_EVENT_NOT_ENDED` (409) when a block close is attempted before the clock reaches `event_end_date` at midnight UTC.
12. **Reduction window.** `ERR_REDUCTION_WINDOW_CLOSED` (409) when a reduction request is filed at or after the event's `attrition_deadline_date` at midnight UTC.
13. **Housing-risk hold.** `ERR_ATTENDEE_HOUSING_RISK_HOLD` (409) on a reservation booking or a reservation change whose guest has `housing_risk_flag` set to true.
14. **Event posture.** `ERR_EVENT_NOT_ACCEPTING_HOUSING` (409) on a sub-block carve while the event's `housing_posture` is `CLOSED`.
15. **Sub-block eligibility.** `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH` (422) on a reservation booking.
16. **Stay window.** `ERR_INVALID_STAY_WINDOW` (422) on a reservation booking or change.
17. **Attendee stay overlap.** `ERR_ATTENDEE_STAY_OVERLAP` (409) on a reservation booking or change.
18. **Sub-block night capacity.** `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED` (409) on a reservation booking or change.
19. **Carve inventory.** `ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED` (409) on a sub-block carve.
20. **Reduction-rights headroom.** `ERR_REDUCTION_RIGHTS_EXCEEDED` (422) on a reduction request.
21. **Release headroom.** `ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS` (409) on a sub-block release.
22. **Payment and write-off ceiling.** `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (422) on an invoice payment or an invoice adjustment.
23. **Reversal ceiling.** `ERR_REVERSAL_EXCEEDS_PAID` (422) on a commission payment reversal.
24. **Non-empty transmission set.** `ERR_NO_TRANSMITTABLE_RESERVATIONS` (422) on a rooming-list transmission.
25. **Transmission type legality.** `ERR_INVALID_TRANSMISSION_TYPE` (409) on a rooming-list transmission.
26. **Terms standardization.** `ERR_TERMS_NOT_STANDARDIZED` (422) on a block contract.
27. **Negotiation rounds.** `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (409) on a terms submission.
28. **Pickup report ordering.** `ERR_PICKUP_REPORT_OUT_OF_ORDER` (422) on a pickup report filing.
29. **Pickup report availability.** `ERR_PICKUP_REPORT_REQUIRED` (422) on a commission invoice issued on the `HOTEL_REPORTED` basis.
30. **Invoice uniqueness.** `ERR_INVOICE_ALREADY_EXISTS` (409) on a second commission invoice for the same block.
31. **Variance tolerance.** `ERR_VARIANCE_WITHIN_TOLERANCE` (422) on an invoice dispute.

Nested paths follow the same left-to-right discipline. For a path such as `/housing/hotel-blocks/{id}/sub-blocks`, the block identifier is resolved before anything in the body is examined, so a carve aimed at a non-existent block returns `ERR_HOTEL_BLOCK_NOT_FOUND` and never `ERR_SUB_BLOCK_NOT_FOUND` for a bad `parent_sub_block_id` in the same request.

### 2.11. Event Housing Posture

Each event exposes a derived `housing_posture` that summarises, in one enum, whether the bureau is currently able to place attendees. Its four values are `PLANNING`, `OPEN`, `RESTRICTED`, and `CLOSED`. It is recomputed whenever any housing block of the event changes status, and whenever a sub-block allotment or a reservation changes the event's available inventory.

The derivation reads two groups of the event's blocks and one sum. The **open group** is the blocks whose `status` is `OPEN`. The **ended group** is the blocks whose `status` is `CUTOFF_PASSED` or `CLOSED`. The **available room count** is the sum of `available_rooms` over every sub-block whose `approval_status` is `APPROVED` and whose parent block is in the open group. From these:

- If the open group is empty and the ended group is also empty, the posture is `PLANNING`. An event whose blocks are all still in `DRAFT`, `TERMS_SUBMITTED`, `CHANGES_REQUESTED` or `CONTRACTED` — and an event with no blocks at all — is therefore in `PLANNING`.
- Otherwise, if the open group is non-empty and the available room count is greater than zero, the posture is `OPEN`.
- Otherwise, if the open group is non-empty and the available room count is exactly zero, the posture is `RESTRICTED`.
- Otherwise — that is, when the open group is empty but the ended group is not — the posture is `CLOSED`.

A `CLOSED` posture is the one that bites operationally: no new inventory may be carved on an event that has reached it, and such an attempt is rejected with `ERR_EVENT_NOT_ACCEPTING_HOUSING`. `RESTRICTED` is informational — it tells the organizer that blocks are open but every approved allotment is full on its peak night.

## 3. Business Logic & Workflows

### 3.1. Program Setup: The Event, Its Properties, and the Delegate Roster

A housing program begins when a `BureauCoordinator` registers the convention itself. The registration payload carries the convention's `name`, between 1 and 160 characters, and a bureau-facing `code` of between 3 and 16 uppercase characters that must be unique across all registered events — a collision is rejected with `ERR_EVENT_CODE_DUPLICATE`. The official housing window is delimited by `event_start_date` and `event_end_date`, both ISO calendar dates, with the end date required to be strictly later than the start date. Three further dates and rates encode the standardization the bureau will enforce on every property: `cutoff_date`, the single reservation cutoff every housing block must match; `attrition_deadline_date`, the last date on which block-reduction rights may be requested; `standard_commission_pct`, a decimal fraction greater than zero and at most 0.25 below which no block may be contracted; and `standard_rebate_per_room_night_cents`, a non-negative integer floor on the per-room-night rebate.

Upon registration the server derives `night_count` from the housing window, sets `housing_posture` to `PLANNING`, and initialises three running aggregates to zero. `total_contracted_room_nights` accumulates the `contracted_room_nights` of every block of the event whose `status` is `CONTRACTED`, `OPEN`, `CUTOFF_PASSED` or `CLOSED` — blocks still in negotiation contribute nothing. `total_confirmed_room_nights` accumulates the `room_nights` of every reservation whose `reservation_status` is `CONFIRMED`, across every sub-block of every block of the event. `commission_collected_cents` accumulates the `paid_cents` of every commission invoice raised against any block of the event. All three are re-derived, not incrementally patched, whenever an operation described below says they are recomputed.

Participating properties are registered separately. Each `Hotel` records a `name`, a `distance_to_venue_miles` of at least zero — this is the ranking key of the attendee-facing property list, which is returned ordered by that distance ascending and then by `name` ascending — a `room_tax_pct` that is at least zero and strictly less than one, representing the combined occupancy and city tax charged on top of the negotiated rate, and a `total_rooms` count of at least one describing the physical inventory of the property. The property's bureau `standing` is an enum with the values `ACTIVE` and `SUSPENDED`; it may be supplied at registration and defaults to `ACTIVE`. A `BureauCoordinator` may later suspend or reinstate a property by submitting a new `standing`, which bumps the hotel's `version`; the property list can be filtered by `standing`. Only an `ACTIVE` property may sign a block contract, which is why suspension is the bureau's lever of last resort mid-negotiation.

Delegates reach the portal through an import performed by a `BureauCoordinator`. An `Attendee` record carries the `event_id` it is registered for, an `email` that must be unique within that event — a duplicate is rejected with `ERR_ATTENDEE_EMAIL_DUPLICATE` — a `full_name` that will be transmitted on the rooming list, the upstream `registration_id`, and an `attendee_type` drawn from `GENERAL`, `VIP`, `STAFF` and `EXHIBITOR`. An optional `eligibility_codes` array, defaulting to empty, records the segregated allotments this delegate may book into. Three counters start at their zero values and are only ever moved by the workflows in §3.5 and §3.8: `warning_count` at 0, `housing_risk_flag` at false, and `no_show_strikes` at 0. The attendee roster can be listed for an event and filtered by `housing_risk_flag`, which is how the bureau pulls the list of poacher-warned delegates that need a phone call.

Finally, because every date gate in the system reads the logical clock described in §2.5, a coordinator-only test-driving capability repositions that clock to a supplied `to_iso8601` instant and reports the resulting `current_utc` alongside the `previous_utc` it displaced.

### 3.2. Block Assembly: Terms Negotiation and Contracting

A housing block is the junction of one event and one property, and it is assembled by a `BureauCoordinator` in `DRAFT`. The assembly payload names the `event_id` and the `hotel_id`, states the `contracted_rooms_per_night` the bureau intends to hold (at least one), and proposes the commercial terms: a `negotiated_nightly_rate_cents` of at least one cent, pre-tax, which is the figure quoted to attendees; a `commission_pct` greater than zero and at most 0.25; a `rebate_per_room_night_cents` of at least zero; a `cutoff_date`; and a `reduction_rights_pct` between zero and 0.50 inclusive, expressing the fraction of the originally contracted rooms-per-night the bureau may later strike without penalty. The new block starts with `revision_round` at 0, `unassigned_rooms_per_night` and `released_rooms_per_night` at 0, `attrition_liability_cents` at 0, and `confirmation_number` null; its `contracted_room_nights` is the product of `contracted_rooms_per_night` and the event's `night_count`, and is re-derived whenever either factor moves. Blocks can be listed and filtered by `event_id`, `hotel_id` and `status`.

Negotiation is a bounded cycle. Submitting terms advances the block `DRAFT → TERMS_SUBMITTED`, and resubmitting after the hotel pushes back advances it `CHANGES_REQUESTED → TERMS_SUBMITTED`; both are coordinator actions and both are protected by the stale-block check of §2.8. A submission overwrites `negotiated_nightly_rate_cents`, `commission_pct`, `rebate_per_room_night_cents`, `cutoff_date` and `reduction_rights_pct` wholesale from the payload — there is no partial merge — increases `revision_round` by one, and bumps the block's `version`. The cycle is capped at three submissions in total: a submission is accepted only while `revision_round` is strictly less than 3, so the fourth attempt on the same block is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. Attempting a submission from any status other than `DRAFT` or `CHANGES_REQUESTED` is rejected with `ERR_INVALID_BLOCK_STATE`.

The hotel side of the negotiation is driven by the `HotelManager` that owns the property, and only while the block sits in `TERMS_SUBMITTED`; from any other status both hotel-side actions are rejected with `ERR_INVALID_BLOCK_STATE`. Bouncing the terms back moves the block `TERMS_SUBMITTED → CHANGES_REQUESTED` and bumps its `version`; a manager acting on a block whose `hotel_id` is not their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`.

Signing the block is the same manager's other option, and it is where standardization is finally enforced. The transition `TERMS_SUBMITTED → CONTRACTED` succeeds only when the property's `standing` is `ACTIVE` — otherwise `ERR_HOTEL_SUSPENDED` — and only when all three standardization conditions hold simultaneously: the block's `commission_pct` is greater than or equal to the event's `standard_commission_pct`, the block's `rebate_per_room_night_cents` is greater than or equal to the event's `standard_rebate_per_room_night_cents`, and the block's `cutoff_date` is exactly equal to the event's `cutoff_date`. Any one of the three failing rejects the signature with `ERR_TERMS_NOT_STANDARDIZED`. The signature payload may carry an optional `confirmation_number`, the hotel-side contract reference, which is recorded on the block. On success the server snapshots `original_contracted_rooms_per_night` from the current `contracted_rooms_per_night`, initialises `unassigned_rooms_per_night` to that same figure so the whole block is available to carve, recomputes the event's `total_contracted_room_nights` and `housing_posture`, and bumps the block's `version`.

### 3.3. Segregated Inventory: Sub-Block Carves and Controller Approval

Contracted inventory is not booked directly; it is carved into **sub-blocks**, each reserved for one audience segment. A carve is filed either by a `BureauCoordinator` or by the `EventOrganizer` whose `event_id` matches the block's — any other organizer is rejected with `ERR_NOT_RESOURCE_OWNER`. The carve payload states the `segment`, one of `GENERAL`, `VIP`, `STAFF` and `EXHIBITOR`; the `allotted_rooms` to set aside per night, at least one on creation; an `eligibility_code` that a delegate must carry in order to book there; an optional `parent_sub_block_id`; and the mandatory `expected_hotel_block_version` from §2.8. The `eligibility_code` and the `segment` are coupled: the code must be present for every segment other than `GENERAL` and must be null or absent for `GENERAL`, and violating that pairing is a malformed request rejected with `ERR_INVALID_REQUEST`. Carving is also gated on the event's posture: while `housing_posture` is `CLOSED`, no further inventory may be carved and the request is rejected with `ERR_EVENT_NOT_ACCEPTING_HOUSING`.

Where the rooms come from depends on `parent_sub_block_id`. A **direct carve**, with no parent named, draws from the block's `unassigned_rooms_per_night` and succeeds only when `allotted_rooms` is less than or equal to that figure. A **nested carve**, with a parent named — the mechanism by which a VIP allotment is cut out of the staff allotment — draws from the parent sub-block's own allotment and succeeds only when `allotted_rooms` is less than or equal to the parent's `available_rooms`. Either way, exceeding the source is rejected with `ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED`, and on success the rooms are debited from the source: `unassigned_rooms_per_night` falls by `allotted_rooms` on a direct carve, and the parent's `allotted_rooms` falls by the same amount on a nested one. Every carve is stamped with a `carve_seq` drawn from a single monotonic one-based global counter, which becomes the deterministic within-segment ordering key of the reduction waterfall described in §3.7 and guarantees that no two sub-blocks can ever tie. The identifier in `X-User-ID` is recorded as `requested_by_user_id`, and the parent block's `version` is bumped.

Approval depends on the segment, and this is the asymmetry to hold onto. A `GENERAL` carve needs no segregated-block review: it is created with `approval_status` already `APPROVED` in the very request that carves it, and `approved_by_user_id` stays null because no human approved it. Every other segment is created with `approval_status` `PENDING_APPROVAL` and waits for a `BureauController`. Controller approval moves the sub-block `PENDING_APPROVAL → APPROVED`, records the acting `X-User-ID` as `approved_by_user_id`, recomputes the event's `housing_posture`, and bumps the sub-block's `version`; it requires that the parent block's `status` be `CONTRACTED` or `OPEN`, and it enforces the segregation rule of §2.9 against `requested_by_user_id`. Controller rejection moves it `PENDING_APPROVAL → REJECTED`, a terminal state, and unwinds the carve completely: the rooms go back where they came from — added to the block's `unassigned_rooms_per_night` when `parent_sub_block_id` is null, or added back to the parent sub-block's `allotted_rooms` when it is not — and the rejected sub-block's own `allotted_rooms` is set to 0. Rejection bumps both the sub-block's `version` and the block's `version`, and, like approval, it enforces segregation of duties. Approving or rejecting a sub-block that is not in `PENDING_APPROVAL` is rejected with `ERR_INVALID_SUB_BLOCK_STATE`.

Occupancy on a sub-block is a **peak-night** figure, not a running total. For each night in the event's housing window — every night from `event_start_date` up to but not including `event_end_date` — the server counts the reservations of that sub-block whose `reservation_status` is `CONFIRMED` and whose stay covers that night, meaning the night falls on or after the reservation's `check_in_date` and strictly before its `check_out_date`. `committed_rooms` is the largest of those per-night counts. `available_rooms` is `allotted_rooms` minus `committed_rooms`. `inventory_status` is the enum `FULL` when `available_rooms` is exactly zero and `OPEN` otherwise. Only `CONFIRMED` reservations occupy inventory: `WAITLISTED`, `CANCELLED` and `NO_SHOW` rows count for nothing. These three derived values are re-evaluated on every reservation creation, date change, cancellation, waitlisting and no-show, and whenever `allotted_rooms` itself moves.

Unsold rooms can be handed back to the hotel before the cutoff by a `BureauCoordinator`, who names the number of `rooms` to give up. The release is admissible only when `rooms` is less than or equal to `allotted_rooms` minus `committed_rooms`; anything larger would strand a confirmed guest and is rejected with `ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS`. A release requires the sub-block to be in `APPROVED` — from `PENDING_APPROVAL`, `REJECTED` or `RELEASED` it is rejected with `ERR_INVALID_SUB_BLOCK_STATE` — and it has two symmetric branches. A **partial release**, where `rooms` is smaller than `allotted_rooms`, leaves the sub-block in `APPROVED` (an `APPROVED → APPROVED` self-transition): `allotted_rooms` falls by `rooms`, the sub-block's own `released_rooms` rises by `rooms`, and the block's `released_rooms_per_night` rises by `rooms`. A **full release**, where `rooms` equals `allotted_rooms`, additionally requires `committed_rooms` to be exactly zero — otherwise the same `ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS` applies — and moves the sub-block `APPROVED → RELEASED`, which is terminal: `released_rooms` rises by `rooms`, `allotted_rooms` is set to 0, and the block's `released_rooms_per_night` rises by `rooms`. Both branches bump the sub-block's `version` and the block's `version`. Sub-blocks can be listed and filtered by `hotel_block_id`, `parent_sub_block_id`, `segment` and `approval_status`.

### 3.4. Opening the Portal and Taking Reservations

A block reaches the attendee portal when a `BureauCoordinator` opens it, advancing it `CONTRACTED → OPEN`; an open attempted from any status other than `CONTRACTED` is rejected with `ERR_INVALID_BLOCK_STATE`. Two further gates guard that step. At least one sub-block of the block must already be in `APPROVED`, since an open block with nothing bookable is a support ticket waiting to happen; otherwise the request is rejected with `ERR_NO_APPROVED_SUB_BLOCK`. And the logical clock must still be strictly before the block's `cutoff_date` at midnight UTC; a block whose cutoff has already arrived can never be opened, and the attempt is rejected with `ERR_CUTOFF_PASSED`. Opening recomputes the event's `housing_posture` and bumps the block's `version`.

Booking is performed by the delegate themselves or by a `BureauCoordinator` acting on their behalf, and the payload is deliberately small: the `sub_block_id` to draw the room from, the `attendee_id` of the guest of record, the `check_in_date`, the `check_out_date`, and an optional `occupants` count that defaults to 1 and must lie between 1 and 4 inclusive. A delegate booking for someone else — an `attendee_id` other than their own `X-User-ID` — is rejected with `ERR_NOT_RESOURCE_OWNER`. Structurally, the target sub-block's parent block must be in `OPEN`, and a booking into a sub-block whose block is in any other status is rejected with `ERR_BLOCK_NOT_OPEN`; the target sub-block itself must be in `APPROVED`, and a booking into a `PENDING_APPROVAL`, `REJECTED` or `RELEASED` sub-block is rejected with `ERR_INVALID_SUB_BLOCK_STATE`. The logical clock must be strictly before the block's `cutoff_date` at midnight UTC, or the booking is rejected with `ERR_CUTOFF_PASSED`.

Eligibility is where segregation earns its keep. For a sub-block whose `segment` is anything other than `GENERAL`, the guest's `attendee_type` must equal that `segment` and the sub-block's `eligibility_code` must appear among the guest's `eligibility_codes`; independently of segment, the guest's `event_id` must equal the `event_id` of the block the sub-block hangs from. Any of those three conditions failing rejects the booking with `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH`. A `GENERAL` sub-block imposes no segment or code requirement, but the same-event requirement still applies.

Three further checks constrain the dates, and they use three deliberately different geometries. First, the **stay window**: `check_in_date` must be no earlier than one day before the event's `event_start_date`, and `check_out_date` must be no later than one day after the event's `event_end_date`; a stay outside that widened window is rejected with `ERR_INVALID_STAY_WINDOW`. Second, the **attendee overlap check**, which stops one delegate holding two rooms across the same trip anywhere in the event — every property, every block, every sub-block. Each of that attendee's other reservations whose `reservation_status` is `CONFIRMED` or `WAITLISTED` is inflated by a one-day shoulder buffer at each end, producing a low bound one day before its `check_in_date` and a high bound one day after its `check_out_date`, and both bounds are treated as **inclusive**. The candidate stay is accepted against that existing stay only when the candidate's `check_out_date` falls strictly before the low bound, or the candidate's `check_in_date` falls strictly after the high bound; in every other case the two collide and the booking is rejected with `ERR_ATTENDEE_STAY_OVERLAP`. Because the interval is closed and buffered, a same-day hotel switch — checking out of one property and into another on the same date — collides, and so does a one-day gap. Third, the **night capacity admission test**, which uses the half-open geometry of §3.3 instead: for every night the candidate stay would occupy, the count of `CONFIRMED` reservations already covering that night, plus one for the candidate, must be less than or equal to the sub-block's `allotted_rooms`. A single night that fails rejects the whole booking with `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED`. Note the asymmetry that follows from the two geometries: a departure and an arrival on the same date do not compete for a night in the capacity test, but they do collide in the same-attendee overlap test.

Bookings are also blocked on the guest's standing. If the delegate's `housing_risk_flag` is true, no reservation may be opened or changed for them until a controller clears the flag, and the attempt is rejected with `ERR_ATTENDEE_HOUSING_RISK_HOLD`.

A reservation that survives every check is stamped with an `intake_seq` drawn from a single monotonic one-based global counter — the deterministic ordering key used to waitlist during the reduction cascade (highest first) and to promote off the waitlist (lowest first), so that no two reservations can ever tie. The commercial terms are then **snapshotted and frozen**: `quoted_nightly_rate_cents` copies the block's current `negotiated_nightly_rate_cents` and `room_tax_pct_snapshot` copies the property's current `room_tax_pct`. Later terms revisions on the block never re-price an existing reservation. `room_nights` is the number of whole days between `check_in_date` and `check_out_date`. `total_room_charge_cents` is then computed with the rounding order pinned: the taxed nightly amount is the `quoted_nightly_rate_cents` multiplied by one plus `room_tax_pct_snapshot`, **rounded half up to whole cents at that point**, and the stay total is that whole-cent nightly amount multiplied by `room_nights`. The reservation is created with `reservation_status` `CONFIRMED`, `transmission_status` `NOT_TRANSMITTED`, `eligibility_review_required` false and `no_show_billed_cents` 0; the sub-block's occupancy figures, the event's `total_confirmed_room_nights` and the event's `housing_posture` are all recomputed. Reservations can be listed and filtered by `sub_block_id`, `attendee_id`, `reservation_status` and `transmission_status`, the last two being genuinely independent axes.

### 3.5. Change Management: Modifications, Cancellations, Promotions and No-Shows

Reservations carry **two independent status axes**. `reservation_status` tracks occupancy and runs `CONFIRMED`, `WAITLISTED`, `CANCELLED` and `NO_SHOW`, with `CANCELLED` and `NO_SHOW` terminal. `transmission_status` tracks the rooming list and runs `NOT_TRANSMITTED`, `TRANSMITTED` and `CHANGE_PENDING`, with no terminal value at all. The two evolve independently, and the combination that surprises people is the legitimate one: a `CANCELLED` reservation can sit in `CHANGE_PENDING` and later become `TRANSMITTED` again, because the hotel still needs to be told the room went away.

A delegate or a `BureauCoordinator` may change a stay by supplying any of `check_in_date`, `check_out_date` and `occupants`. The change is refused with `ERR_RESERVATION_NOT_MODIFIABLE` when the reservation has already reached a terminal `reservation_status` or when its parent block has reached `CLOSED`, and with `ERR_CUTOFF_PASSED` when the logical clock has reached the block's `cutoff_date` at midnight UTC. A delegate changing another delegate's reservation is rejected with `ERR_NOT_RESOURCE_OWNER`, and a guest under a housing-risk hold cannot change a stay at all. The date checks of §3.4 — stay window, buffered attendee overlap (which excludes the reservation being changed from its own comparison set), and night-capacity admission — all apply again. On success `room_nights` and `total_room_charge_cents` are recomputed **at the original snapshotted rate and tax**, never at the block's current terms; the sub-block's occupancy figures and the event's `total_confirmed_room_nights` are recomputed; a reservation sitting in `TRANSMITTED` moves `TRANSMITTED → CHANGE_PENDING` so the delta reaches the hotel in the next batch; and the reservation's `version` is bumped.

Cancellation, available to the delegate who owns the stay and to a `BureauCoordinator`, moves the reservation `CONFIRMED → CANCELLED`. It requires the parent block to be in `OPEN` or `CUTOFF_PASSED`; from any other block status, or from a reservation that is not `CONFIRMED`, the attempt is rejected with `ERR_RESERVATION_NOT_MODIFIABLE`. If the reservation was `TRANSMITTED`, it moves `TRANSMITTED → CHANGE_PENDING`, because a retraction must still reach the hotel. The sub-block's `committed_rooms`, `available_rooms` and `inventory_status` and the event's `total_confirmed_room_nights` are recomputed, and the reservation's `version` is bumped.

Cancellation is also the only trigger for **waitlist promotion**, and the promotion is strictly bounded to one. Among the reservations of the same sub-block whose `reservation_status` is `WAITLISTED`, the server considers those for which every night of the stay — from `check_in_date` up to but not including `check_out_date` — now has spare capacity in the sub-block after the cancellation has been accounted for. Of those promotable candidates it promotes exactly one, the one with the **lowest** `intake_seq`, moving it `WAITLISTED → CONFIRMED`; at most one promotion happens per cancellation, even when several candidates would fit. The promoted reservation moves `TRANSMITTED → CHANGE_PENDING` if it had been transmitted, and the sub-block's `committed_rooms` and the event's `total_confirmed_room_nights` are recomputed again to account for it. Its `version` is bumped.

No-shows are reported by the property, not by the bureau. The `HotelManager` that owns the block moves a reservation `CONFIRMED → NO_SHOW`, and four conditions must hold: the reservation is in `CONFIRMED`, the parent block's `status` is exactly `CUTOFF_PASSED`, the block's `hotel_id` equals the acting `X-User-ID`, and the logical clock has reached the reservation's `check_in_date` at midnight UTC. A manager who does not own the block is rejected with `ERR_NOT_RESOURCE_OWNER`; the other three failures are reported as `ERR_RESERVATION_NOT_MODIFIABLE`. On success the guest is billed for exactly one night: `no_show_billed_cents` is the taxed nightly amount — `quoted_nightly_rate_cents` multiplied by one plus `room_tax_pct_snapshot`, rounded half up to whole cents — multiplied by the single billed no-show night. The guest's `no_show_strikes` rises by one, the sub-block's occupancy is recomputed because a `NO_SHOW` row leaves the committed set, and the event's `total_confirmed_room_nights` is recomputed. Crucially, **no waitlist promotion runs on a no-show**: the room was physically held, so the freed allotment is not offered onward. The reservation's `version` is bumped.

### 3.6. Reporting Outward: Rooming Lists, Pickup Snapshots and Pace Analysis

The hotel learns who is arriving through **rooming-list transmissions**, batched by a `BureauCoordinator`. Each batch declares a `transmission_type` of `INITIAL`, `CHANGE` or `FINAL`, and the type is validated against the block's history and status: `INITIAL` is admissible only when the block has never transmitted before, `CHANGE` only when at least one prior transmission exists, and `FINAL` only when the block's `status` is `CUTOFF_PASSED` or `CLOSED`. A type that does not fit is rejected with `ERR_INVALID_TRANSMISSION_TYPE`.

The batch's contents are computed, not chosen. Across every sub-block of the block regardless of that sub-block's `approval_status`, a reservation joins the batch when its `transmission_status` is `NOT_TRANSMITTED` or `CHANGE_PENDING`, **and** its `reservation_status` is `CONFIRMED`, `CANCELLED` or `NO_SHOW`, **and** it is not the case that the reservation is `CANCELLED` or `NO_SHOW` while still `NOT_TRANSMITTED` — a stay the hotel was never told about needs no retraction. `WAITLISTED` reservations are never transmitted under any circumstance. The resulting set is ordered by `created_at` ascending and then by `intake_seq` ascending, which is a total order because `intake_seq` is unique, and those identifiers are recorded on the batch as `included_reservation_ids` with their count in `reservation_count`. The batch's `batch_seq` is one more than the number of transmissions the block already has, and `transmitted_at` records the logical clock at the moment of transmission as an ISO 8601 UTC instant with three fractional digits; the batch also records the `hotel_block_id` it belongs to. Every included reservation moves to `transmission_status` `TRANSMITTED` — `NOT_TRANSMITTED → TRANSMITTED` for a first-time stay, `CHANGE_PENDING → TRANSMITTED` for a delta re-entering a `CHANGE` or `FINAL` batch — and each such reservation's `version` is bumped. If the computed set is empty, nothing is transmitted and the request is rejected with `ERR_NO_TRANSMITTABLE_RESERVATIONS`. Transmission history for a block is readable in `batch_seq` ascending order; because these batches are immutable records of fact, they carry only `id` and `created_at` and have neither `updated_at` nor `version`.

Running the other way, the property tells the bureau how the block is filling by filing **pickup reports**. Each report is a cumulative snapshot, filed by the owning `HotelManager` against a `hotel_block_id`, carrying an `as_of_date`, the cumulative `reported_rooms_picked_up` (distinct rooms the hotel shows booked in the block), the cumulative `reported_room_nights`, the cumulative `reported_gross_revenue_cents` of pre-tax room revenue the hotel attributes to the block — all three at least zero — and a `source` enum whose only permitted value is `HOTEL`, which is also its default. Reports are append-only and immutable, so like transmissions they carry only `id` and `created_at`. Their sequence is strictly increasing: an `as_of_date` that is not strictly later than the latest existing report's `as_of_date` for that block is rejected with `ERR_PICKUP_REPORT_OUT_OF_ORDER`. Filing a report changes nothing else — no block status moves, no vendor is touched — but it silently redefines what "latest report" means for both the pace analysis below and any subsequent hotel-reported invoice. History is readable in `as_of_date` ascending order.

**Pace analysis** turns that report history into two deliberately different projections, so the bureau can show the organizer what the trend says and what the contract says at the same time. The reports of the block are read in `as_of_date` ascending order, which is a total order because the dates strictly increase. When fewer than two reports exist, no extrapolation is possible: both projections equal the latest `reported_room_nights` and `pace_variance_room_nights` is 0 (with no report at all, `report_count`, `latest_reported_room_nights`, `days_remaining_to_cutoff`, both projections and the variance are all 0). With at least two reports, let the first, the last and the second-to-last report be identified by that ordering. `days_remaining_to_cutoff` is the number of whole days from the last report's `as_of_date` to the block's `cutoff_date`.

- The **forward-looking projection** measures average pace across the whole observed window: the difference in `reported_room_nights` between the last and the first report, divided by the number of whole days between their `as_of_date` values, gives an average daily pace; that pace multiplied by `days_remaining_to_cutoff` is added to the last report's `reported_room_nights`, and the sum is rounded half up to a whole number of room nights to give `forward_looking_projection_room_nights`. This is the contractual pace figure.
- The **chronological run rate** measures only the most recent consecutive pair: the difference in `reported_room_nights` between the last and the second-to-last report, divided by the number of whole days between their `as_of_date` values, gives the latest daily rate; that rate multiplied by `days_remaining_to_cutoff` is added to the last report's `reported_room_nights`, and the sum is rounded half up to give `chronological_run_rate_projection_room_nights`. This is the operational figure the bureau shows the organizer, and it moves whenever pickup accelerates or decelerates late in the window.

`pace_variance_room_nights` is the chronological run-rate projection minus the forward-looking projection, and it is the number the bureau argues about. Separately, `pace_target_room_nights` is the block's `contracted_room_nights` multiplied by the pace target ratio of 80 percent, rounded half up to whole room nights. The boolean `on_pace` is true exactly when `forward_looking_projection_room_nights` is greater than or equal to `pace_target_room_nights` — the contractual projection decides it, never the run rate. The analysis response also echoes the `hotel_block_id`, the `report_count`, and the `latest_reported_room_nights` it worked from.

### 3.7. Attrition Management: Reduction Rights and the Exercise Cascade

Every block contract sells the bureau an option: the right to strike some fraction of the rooms it committed to, without paying attrition penalty on them, provided it says so in time. That option is exercised through a three-step workflow — file, approve, exercise — and the arithmetic of the option is the `reduction_rights_pct` negotiated in §3.2.

A `BureauCoordinator` files a reduction against a `hotel_block_id`, naming the `requested_reduction_rooms` to strike from the contract (at least one), the contractual `effective_date` of the reduction, and a `justification_code` recorded for the hotel. Two gates apply. The request must arrive **strictly before** the event's `attrition_deadline_date` at midnight UTC; a request filed at exactly that midnight, or later, is rejected with `ERR_REDUCTION_WINDOW_CLOSED`. And the request must fit inside the remaining rights headroom, computed as follows: the **cap** is the block's `original_contracted_rooms_per_night` multiplied by its `reduction_rights_pct`, with the fractional part discarded — the entitlement always floors, never rounds up. The **consumed** figure is the total `requested_reduction_rooms` across every reduction already filed against the block whose `status` is `SUBMITTED`, `APPROVED` or `EXERCISED`; rows in `REJECTED` release their share and count for nothing. Headroom is the cap minus the consumed figure, and a `requested_reduction_rooms` greater than that headroom is rejected with `ERR_REDUCTION_RIGHTS_EXCEEDED`. A filed reduction starts in `status` `SUBMITTED` with the filing `X-User-ID` recorded as `requested_by_user_id`, `approved_by_user_id` null, `rooms_absorbed_from_unassigned` and `rooms_absorbed_from_sub_blocks` at 0, and `penalty_avoided_cents` null. Note that a `SUBMITTED` row already consumes headroom, so a coordinator cannot file two overlapping requests and let the controller pick.

A `BureauController` then approves or rejects, and both branches enforce the segregation rule of §2.9 against `requested_by_user_id`. Approval moves the reduction `SUBMITTED → APPROVED`, records the acting `X-User-ID` as `approved_by_user_id`, and bumps the reduction's `version`; it additionally requires the parent block's `status` to be `OPEN` or `CUTOFF_PASSED`. Rejection moves it `SUBMITTED → REJECTED`, which is terminal, returns the reserved headroom by dropping the row out of the consumed figure, and bumps the reduction's `version`. Acting on a reduction that is not in `SUBMITTED` is rejected with `ERR_INVALID_REDUCTION_STATE`.

Exercising an approved reduction is the deepest cascade in the system. A `BureauCoordinator` moves the reduction `APPROVED → EXERCISED`, which requires the parent block's `status` to be `OPEN` or `CUTOFF_PASSED` — otherwise `ERR_INVALID_BLOCK_STATE` — and requires the reduction to be in `APPROVED`, otherwise `ERR_INVALID_REDUCTION_STATE`. Four links then fire in order, and each one is a consequence of the previous:

1. The contract shrinks. The block's `contracted_rooms_per_night` falls by `requested_reduction_rooms`, its `contracted_room_nights` is re-derived from the new figure and the event's `night_count`, and the block's `version` is bumped.
2. Because the contract shrank, the same number of rooms must be found somewhere, and they are found by a **waterfall** with a pinned order. The block's `unassigned_rooms_per_night` absorbs first: the smaller of the outstanding rooms and the unassigned pool is taken out of `unassigned_rooms_per_night` and recorded on the reduction as `rooms_absorbed_from_unassigned`. Whatever remains is drawn from sub-block allotments, and only from sub-blocks whose `approval_status` is `APPROVED` — `PENDING_APPROVAL`, `REJECTED` and `RELEASED` sub-blocks are skipped entirely. Those eligible sub-blocks are visited in a fixed segment order, `GENERAL` first, then `EXHIBITOR`, then `STAFF`, then `VIP` last, and within one segment in ascending `carve_seq` order; each sub-block visited gives up the smaller of the outstanding rooms and its own `allotted_rooms`, and the walk stops the moment nothing is outstanding. The total drawn from sub-blocks is recorded as `rooms_absorbed_from_sub_blocks`, which is `requested_reduction_rooms` minus `rooms_absorbed_from_unassigned`. Because rooms are integers, no rounding remainder is possible. The segment order is a policy statement: general inventory is sacrificed before exhibitor inventory, exhibitor before staff, and VIP allotments are protected last.
3. Because a sub-block's `allotted_rooms` may now sit below its `committed_rooms`, that sub-block's over-commitment is unwound by waitlisting. Its reservations in `CONFIRMED` are moved `CONFIRMED → WAITLISTED` in **descending** `intake_seq` order — last booked, first bumped — and the process continues only until `committed_rooms` is once again less than or equal to `allotted_rooms`.
4. Because reservations left the `CONFIRMED` set, the sub-block's `committed_rooms`, `available_rooms` and `inventory_status` and the event's `total_confirmed_room_nights` are recomputed, and every affected reservation that was sitting in `TRANSMITTED` moves `TRANSMITTED → CHANGE_PENDING` so the hotel is told. Each waitlisted reservation's `version` is bumped.

Only **after** all four links have settled are the penalty figures written, and this ordering matters because the cascade changes both sides of the penalty ratio. The block's `attrition_liability_cents` is set to the post-reduction attrition penalty exposure, and the reduction's `penalty_avoided_cents` is set to the pre-reduction exposure minus the post-reduction exposure. The reduction's `version` is bumped. Reduction requests filed against a block are readable in `effective_date` ascending order and then `created_at` ascending.

**Attrition penalty exposure** is computed in six pinned steps, and the tier in step five must be selected from the ratio produced in step four — never from a ratio measured before the cascade settled.

1. The **adjusted contracted room nights** are the block's `contracted_rooms_per_night` (with every exercised reduction already applied, in `effective_date` ascending and then `created_at` ascending order) multiplied by the event's `night_count`.
2. The **actual room nights** are read after the cascade has fully settled: the sum of `room_nights` over every reservation of every sub-block of the block whose `reservation_status` is `CONFIRMED`, plus one night for each reservation whose `reservation_status` is `NO_SHOW`. `CANCELLED` and `WAITLISTED` reservations contribute nothing.
3. The **protected room nights** are the adjusted contracted room nights multiplied by the allowed pickup ratio of 80 percent, rounded half up to a whole number of room nights.
4. The **shortfall** is the protected room nights minus the actual room nights, floored at zero — it is never negative. The **shortfall ratio** is that shortfall divided by the adjusted contracted room nights, and is taken to be zero when the adjusted contracted room nights are zero.
5. The **penalty rate** is selected by tier from the shortfall ratio: 50 percent when the ratio is less than or equal to 0.10; otherwise 70 percent when the ratio is less than or equal to 0.25; otherwise 90 percent.
6. The **penalty** is the shortfall room nights multiplied by the block's `negotiated_nightly_rate_cents` multiplied by the penalty rate, rounded half up to whole cents once, at this final step.

That computation has two variants, and both are needed at exercise time. The **post-reduction** variant uses `contracted_rooms_per_night` exactly as it stands after the reduction is applied, and it is what lands in `attrition_liability_cents`. The **pre-reduction** variant exists only to fill `penalty_avoided_cents`: it adds this reduction's `requested_reduction_rooms` back into `contracted_rooms_per_night` for the purpose of steps one, three, four and six, while keeping the **same post-cascade actual room nights** from step two, so that a tier change between the two runs surfaces as avoided penalty. The difference between the two runs, pre-reduction minus post-reduction, is `penalty_avoided_cents`.

### 3.8. Poacher and Rogue-Housing Monitoring

Rogue housing companies harvest exhibitor and attendee lists and call delegates with fake block rates, and the damage lands on the bureau twice — once as a poached room-night the block never picks up, and once as a delegate whose deposit vanished. A `ComplianceOfficer` owns this workflow end to end.

The officer records a suspected vendor against an `event_id`, capturing the reported `name` of the rogue housing company, the `contact_domain` it uses to reach delegates, and a `detection_source` of `ATTENDEE_REPORT`, `HOTEL_REPORT` or `WEB_MONITORING`. The vendor starts in `status` `REPORTED` with `warning_issued_count` at 0, and with its `risk_score` and `verified_incident_count` derived immediately — which, with no incidents on file, puts the score at the base value of 10. Vendors can be listed for an event and filtered by `status`.

Individual contacts are then recorded as **poaching incidents** against the vendor. Each incident names the `attendee_id` that was contacted, the `contact_channel` used (`EMAIL`, `PHONE`, `SMS` or `WEB`), the `occurred_at` instant of the contact, a `verified` boolean stating whether the bureau confirmed the contact with the delegate, and an optional `solicited_payment` boolean, defaulting to false, recording whether the vendor asked for a card or a deposit. The combination of vendor, `attendee_id`, `contact_channel` and `occurred_at` must be unique; a repeat is rejected with `ERR_DUPLICATE_INCIDENT`. Each incident begins in `status` `RECORDED` with `warning_issued_at` and `warning_severity` both null, and the incident record also carries the `rogue_vendor_id` it belongs to. A vendor's incidents are readable in `occurred_at` ascending and then `contact_channel` ascending order, and an individual delegate's full contact history is readable as well.

Every recorded incident re-derives the vendor's score. Only incidents with `verified` set to true and `status` in `RECORDED` or `WARNING_ISSUED` are counted; dismissed incidents drop out entirely. `verified_incident_count` is the number of counted incidents. The score starts from a base of 10, adds 25 for each counted incident, adds 15 for each distinct `contact_channel` appearing among the counted incidents, and adds a further 20 if any counted incident has `solicited_payment` true — that bonus is awarded once, not per incident. The result is clamped to the range 0 through 100 inclusive and stored as `risk_score`. The clamp matters at the top: four counted verified incidents across three channels already overshoot the ceiling.

The score drives an automatic escalation. The moment a newly recorded incident pushes `risk_score` to 60 or above while the vendor is still in `REPORTED`, the vendor transitions `REPORTED → UNDER_REVIEW` inside that same request and its `version` is bumped. A single verified incident on one channel with no payment solicitation scores 50 and does not escalate; the same incident with `solicited_payment` true scores 70 and does.

From `UNDER_REVIEW` the officer has two exits, and attempting either from any other `status` is rejected with `ERR_INVALID_VENDOR_STATE`. **Confirming** the vendor moves it `UNDER_REVIEW → CONFIRMED_POACHER`, a terminal state, and requires at least one incident with `verified` true still sitting in `RECORDED`; without one the confirmation is rejected with `ERR_INVALID_VENDOR_STATE`. Confirmation then fires a three-link cascade:

1. Every incident of that vendor with `verified` true and `status` `RECORDED` moves `RECORDED → WARNING_ISSUED`, processed in `occurred_at` ascending and then `contact_channel` ascending order. Each such incident gets `warning_issued_at` set to the logical clock and a `warning_severity` of `ADVISORY` when the target delegate's `warning_count` is 0 at that moment and `URGENT` from the second warning onward — because the incidents are processed in that pinned order, two warnings to the same delegate in one confirmation come out `ADVISORY` then `URGENT`. The vendor's `warning_issued_count` rises by one per warning issued, and each incident's `version` is bumped. Incidents with `verified` false are left untouched in `RECORDED`.
2. Because a warning was issued, the target delegate's `warning_count` rises by one for each warning they receive, and when that counter reaches the housing-risk threshold of 2 the delegate's `housing_risk_flag` flips from false to true. A flagged delegate can neither open nor change housing until a `BureauController` clears the flag; until then those attempts are rejected with `ERR_ATTENDEE_HOUSING_RISK_HOLD`.
3. Because `housing_risk_flag` flipped from false to true, every reservation of that delegate whose `reservation_status` is `CONFIRMED` gets `eligibility_review_required` set to true, and any such reservation sitting in `TRANSMITTED` moves `TRANSMITTED → CHANGE_PENDING` so the hotel is warned in the next batch. Those reservations' `version` values are bumped.

The vendor's own `version` is bumped by the confirmation. **Clearing** the vendor is the other exit: it moves it `UNDER_REVIEW → CLEARED`, also terminal, and every incident of the vendor still in `RECORDED` moves `RECORDED → DISMISSED` with its `version` bumped. No warning is issued, no `warning_count` moves, no `housing_risk_flag` flips, and no delegate counter of any kind changes. The vendor's `risk_score` is then re-derived over whatever counted incidents remain — which, since dismissal removes them from the counted set, generally drops the score back toward the base — and the vendor's `version` is bumped.

### 3.9. Cutoff, Closure and Post-Event Commission Settlement

The cutoff is the moment unsold inventory reverts to the property, and a `BureauCoordinator` triggers it once the logical clock has reached the block's `cutoff_date` at midnight UTC; attempting it earlier is rejected with `ERR_CUTOFF_NOT_REACHED`, and attempting it from any status other than `OPEN` is rejected with `ERR_INVALID_BLOCK_STATE`. The sweep moves the block `OPEN → CUTOFF_PASSED` and then walks every sub-block of the block whose `approval_status` is `APPROVED`, in ascending `carve_seq` order. For each one, the released quantity is its `allotted_rooms` minus its `committed_rooms`: that quantity is added to the sub-block's `released_rooms`, the sub-block's `allotted_rooms` is set down to exactly its `committed_rooms`, and the same quantity is added to the block's `released_rooms_per_night`. The block's remaining `unassigned_rooms_per_night` is then added wholesale to `released_rooms_per_night` and set to 0. Any sub-block whose `allotted_rooms` became 0 through this sweep moves `APPROVED → RELEASED`. The event's `housing_posture` is recomputed and the block's `version` is bumped. The room-accounting identity of §2.7 holds both before and after the sweep.

Closure comes after the convention itself. A `BureauCoordinator` moves the block `CUTOFF_PASSED → CLOSED` — the block's terminal state — and this is admissible only once the logical clock has reached the event's `event_end_date` at midnight UTC; earlier attempts are rejected with `ERR_EVENT_NOT_ENDED`, and attempts from any other block status with `ERR_INVALID_BLOCK_STATE`. Closure freezes the attrition exposure: `attrition_liability_cents` is set to the post-reduction attrition penalty exposure defined in §3.7, computed against the block as it finally stands. The event's `total_confirmed_room_nights` and `housing_posture` are recomputed and the block's `version` is bumped.

Settlement is where the bureau's own revenue is finally recognised, and it hinges on a single choice. A `BureauCoordinator` issues **one** commission invoice per block — a second attempt is rejected with `ERR_INVOICE_ALREADY_EXISTS` — declaring a `basis` of either `BUREAU_CONFIRMED` or `HOTEL_REPORTED`. Both sides are always computed, whichever basis is chosen, because the reconciliation is the point.

The **bureau side** reads the bureau's own reservation ledger across every sub-block of the block. Its room nights are the sum of `room_nights` over reservations in `CONFIRMED`, plus one night for each reservation in `NO_SHOW`; `CANCELLED` and `WAITLISTED` reservations are excluded. Its pre-tax revenue is the sum, over reservations in `CONFIRMED`, of `quoted_nightly_rate_cents` multiplied by `room_nights`, plus the sum, over reservations in `NO_SHOW`, of `quoted_nightly_rate_cents` multiplied by the single billed no-show night. `bureau_confirmed_commission_cents` is that pre-tax revenue multiplied by the block's `commission_pct`, rounded half up to whole cents **once for the side** — never per reservation.

The **hotel side** reads exactly one record: the block's pickup report with the greatest `as_of_date`. `hotel_reported_commission_cents` is that report's `reported_gross_revenue_cents` multiplied by the block's `commission_pct`, rounded half up to whole cents once. When the block has no pickup report at all, `hotel_reported_commission_cents` is null.

The declared `basis` then selects the billed figures. On `BUREAU_CONFIRMED`, `commission_due_cents` takes `bureau_confirmed_commission_cents` and `billable_room_nights` takes the bureau room-night total — so rooms the hotel failed to attribute to the block are still billed. On `HOTEL_REPORTED`, `commission_due_cents` takes `hotel_reported_commission_cents` and `billable_room_nights` takes the latest report's `reported_room_nights` — so unattributed rooms silently disappear from the bill and surface only as variance. Because that basis is meaningless without a report, issuing on `HOTEL_REPORTED` against a block with no pickup report is rejected with `ERR_PICKUP_REPORT_REQUIRED`. `rebate_due_cents`, the money owed to the organizer, is the block's `rebate_per_room_night_cents` multiplied by `billable_room_nights`. `variance_cents` is the signed difference `bureau_confirmed_commission_cents` minus `hotel_reported_commission_cents`, and is null when no pickup report exists. The invoice is created in `status` `ISSUED` with `paid_cents` and `written_off_cents` at 0, records the `hotel_block_id` it bills, and its `outstanding_cents` is `commission_due_cents` minus `paid_cents` minus `written_off_cents` — which at issuance is simply `commission_due_cents`, and which is re-derived after every cash or write-off movement.

Collection is a **cyclic** axis, not a one-way ratchet. The owning `HotelManager` remits cash by naming an `amount_cents` and an optional `reference`; a manager who does not own the block is rejected with `ERR_NOT_RESOURCE_OWNER`. A payment is accepted only from `ISSUED`, `PARTIALLY_PAID` or `ADJUSTED`, and from `DISPUTED` or `PAID` it is rejected with `ERR_INVOICE_NOT_PAYABLE`; the `amount_cents` may not exceed `outstanding_cents`, and a larger figure is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`. A payment smaller than `outstanding_cents` moves the invoice `ISSUED → PARTIALLY_PAID`, or holds it at `PARTIALLY_PAID → PARTIALLY_PAID` if it was already part-paid. A payment exactly equal to `outstanding_cents` settles it: `ISSUED → PAID`, `PARTIALLY_PAID → PAID`, or `ADJUSTED → PAID`. From `ADJUSTED` only a payment equal to the full `outstanding_cents` is defined, so a smaller payment against an adjusted invoice is rejected with `ERR_INVOICE_NOT_PAYABLE`. Every payment raises `paid_cents` by `amount_cents`, re-derives `outstanding_cents` (which becomes exactly 0 on a settling payment), recomputes the event's `commission_collected_cents`, and bumps the invoice's `version`.

A `BureauController` can push cash back out again with a compensating reversal, naming an `amount_cents` and an optional `reference`. Reversals are accepted only from `PARTIALLY_PAID` or `PAID` — otherwise `ERR_INVOICE_NOT_PAYABLE` — and the `amount_cents` may not exceed `paid_cents`, a larger figure being rejected with `ERR_REVERSAL_EXCEEDS_PAID`. A **partial reversal**, where `amount_cents` is strictly less than `paid_cents` so that some cash remains, lowers `paid_cents` by `amount_cents`, re-derives `outstanding_cents`, and leaves or places the invoice in `PARTIALLY_PAID` — including the `PAID → PARTIALLY_PAID` direction, which is how a fully settled invoice reopens. A **full reversal**, where `amount_cents` equals `paid_cents`, sets `paid_cents` to 0 and `outstanding_cents` back to `commission_due_cents` minus `written_off_cents`, and returns the invoice to `ISSUED` from either starting point — `PARTIALLY_PAID → ISSUED` or `PAID → ISSUED`. Either way the event's `commission_collected_cents` is recomputed and the invoice's `version` is bumped.

Disputes are the hotel's remedy when the two bases disagree materially, and materiality is defined by a tolerance band. The tolerance is the greater of a floor of 5,000 cents — fifty dollars — and one percent of `bureau_confirmed_commission_cents` rounded half up to whole cents. The owning `HotelManager` may dispute only from `ISSUED` or `PARTIALLY_PAID`, with any other status rejected as `ERR_INVOICE_NOT_PAYABLE`, and only when the absolute value of `variance_cents` is **strictly greater** than that tolerance; a variance inside the band, and equally a `variance_cents` that is null because the block never filed a pickup report, is rejected with `ERR_VARIANCE_WITHIN_TOLERANCE`. A successful dispute moves the invoice `ISSUED → DISPUTED` or `PARTIALLY_PAID → DISPUTED` and bumps its `version`; no disputing identity is stored, the dispute is asserted through `status` alone.

A `BureauController` resolves the dispute by writing off part of the balance, naming a `write_off_cents` that may not exceed `outstanding_cents` — a larger figure is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`. The adjustment is admissible only from `DISPUTED`, otherwise `ERR_INVOICE_NOT_PAYABLE`. It raises `written_off_cents` by `write_off_cents`, re-derives `outstanding_cents`, moves the invoice `DISPUTED → ADJUSTED`, and bumps its `version`. From `ADJUSTED` the hotel settles the remainder, closing the loop. Because `commission_collected_cents` on the event tracks `paid_cents` and not `commission_due_cents`, a written-off variance never inflates the organizer's view of collected commission.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — registering an event or a property, assembling a block, carving a sub-block, importing a delegate, taking a reservation, transmitting a rooming-list batch, filing a pickup report, filing a reduction request, recording a rogue vendor or an incident, or issuing the commission invoice — return `201 Created`. Every operation that mutates an existing resource, including all state transitions, all cash movements and the logical-clock repositioning, returns `200 OK`. Read operations return `200 OK`.

In the table below, **All roles** means all six of `BureauCoordinator`, `BureauController`, `HotelManager`, `EventOrganizer`, `Attendee` and `ComplianceOfficer`. Request and response payloads are intentionally not repeated here; the field-level contract for each operation is given in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/housing/events` | Register an event the bureau will house | BureauCoordinator |
| GET    | `/housing/events/{id}` | Read one event including derived posture and aggregate room-night counters | All roles |
| POST   | `/housing/hotels` | Register a participating hotel property | BureauCoordinator |
| GET    | `/housing/hotels/{id}` | Read one hotel | All roles |
| GET    | `/housing/hotels` | List hotels for the attendee portal, ordered by distance to venue then name | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| PATCH  | `/housing/hotels/{id}/standing` | Suspend or reinstate a property | BureauCoordinator |
| POST   | `/housing/hotel-blocks` | Assemble a draft housing block on a hotel for an event | BureauCoordinator |
| GET    | `/housing/hotel-blocks/{id}` | Read one housing block with its current inventory accounting | All roles |
| GET    | `/housing/hotel-blocks` | List housing blocks, filterable by event, hotel and status | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| POST   | `/housing/hotel-blocks/{id}/terms` | Submit or resubmit standardized block terms | BureauCoordinator |
| POST   | `/housing/hotel-blocks/{id}/request-changes` | Hotel bounces the submitted terms back to the bureau | HotelManager |
| POST   | `/housing/hotel-blocks/{id}/contract` | Hotel signs the block; standardization and hotel standing are enforced here | HotelManager |
| POST   | `/housing/hotel-blocks/{id}/open` | Open the block on the attendee reservation portal | BureauCoordinator |
| POST   | `/housing/hotel-blocks/{id}/cutoff` | Pass the cutoff: release every unsold room back to the hotel | BureauCoordinator |
| POST   | `/housing/hotel-blocks/{id}/close` | Close the block post-event and freeze the attrition liability | BureauCoordinator |
| GET    | `/housing/hotel-blocks/{id}/pickup-pace` | Pace analysis: both projection variants side by side | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| POST   | `/housing/hotel-blocks/{id}/sub-blocks` | Carve a segregated sub-block out of the block or a parent sub-block | BureauCoordinator, EventOrganizer |
| GET    | `/housing/sub-blocks/{id}` | Read one sub-block with its committed/available room accounting | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| GET    | `/housing/sub-blocks` | List sub-blocks; filter by block, parent sub-block, segment or approval status | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| POST   | `/housing/sub-blocks/{id}/approve` | Approve a segregated sub-block | BureauController |
| POST   | `/housing/sub-blocks/{id}/reject` | Reject a segregated sub-block and return its rooms to inventory | BureauController |
| POST   | `/housing/sub-blocks/{id}/release` | Release unsold sub-block rooms back to the hotel before cutoff | BureauCoordinator |
| POST   | `/housing/attendees` | Import a registered attendee into the housing portal | BureauCoordinator |
| GET    | `/housing/attendees/{id}` | Read one attendee including poacher-warning counters | All roles |
| GET    | `/housing/attendees` | List attendees of an event, optionally only the poacher-warned ones | BureauCoordinator, BureauController, EventOrganizer, ComplianceOfficer |
| GET    | `/housing/attendees/{id}/poaching-incidents` | Every rogue-vendor contact recorded against this attendee | BureauCoordinator, BureauController, EventOrganizer, ComplianceOfficer |
| POST   | `/housing/reservations` | Attendee portal booking into a specific sub-block | Attendee, BureauCoordinator |
| GET    | `/housing/reservations/{id}` | Read one reservation with both status axes and the quoted rate | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| GET    | `/housing/reservations` | List reservations; filter by sub-block, attendee or either status axis | BureauCoordinator, BureauController, EventOrganizer, HotelManager, Attendee |
| PATCH  | `/housing/reservations/{id}` | Change management: move the stay dates or occupant count | Attendee, BureauCoordinator |
| POST   | `/housing/reservations/{id}/cancel` | Cancel a reservation; frees inventory and may promote one waitlisted stay | Attendee, BureauCoordinator |
| POST   | `/housing/reservations/{id}/no-show` | Hotel reports a no-show after the arrival date | HotelManager |
| POST   | `/housing/hotel-blocks/{id}/rooming-lists` | Transmit the rooming list batch for a block | BureauCoordinator |
| GET    | `/housing/hotel-blocks/{id}/rooming-lists` | Transmission history of a block, ordered by batch sequence | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| POST   | `/housing/hotel-blocks/{id}/pickup-reports` | Hotel files a cumulative pickup snapshot for the block | HotelManager |
| GET    | `/housing/hotel-blocks/{id}/pickup-reports` | Pickup report history of a block, ordered by as-of date | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| POST   | `/housing/attrition-reductions` | File a block-reduction request against the contractual reduction rights | BureauCoordinator |
| GET    | `/housing/attrition-reductions/{id}` | Read one reduction request | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| GET    | `/housing/hotel-blocks/{id}/attrition-reductions` | Reduction requests filed against a block | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| POST   | `/housing/attrition-reductions/{id}/approve` | Approve the reduction | BureauController |
| POST   | `/housing/attrition-reductions/{id}/reject` | Reject the reduction and return the rights headroom | BureauController |
| POST   | `/housing/attrition-reductions/{id}/exercise` | Exercise the reduction: shrink the contract and cascade through sub-blocks and reservations | BureauCoordinator |
| POST   | `/housing/rogue-vendors` | Record a suspected rogue housing company | ComplianceOfficer |
| GET    | `/housing/rogue-vendors/{id}` | Read one rogue vendor with its risk score | BureauCoordinator, BureauController, EventOrganizer, ComplianceOfficer |
| GET    | `/housing/rogue-vendors` | List rogue vendors of an event | BureauCoordinator, BureauController, EventOrganizer, ComplianceOfficer |
| POST   | `/housing/rogue-vendors/{id}/incidents` | Record a poaching contact against an attendee | ComplianceOfficer |
| GET    | `/housing/rogue-vendors/{id}/incidents` | Incidents recorded against a vendor | BureauCoordinator, BureauController, EventOrganizer, ComplianceOfficer |
| POST   | `/housing/rogue-vendors/{id}/confirm` | Confirm the vendor as a poacher and warn every verified contacted attendee | ComplianceOfficer |
| POST   | `/housing/rogue-vendors/{id}/clear` | Clear the vendor; recorded incidents are dismissed and no warnings are issued | ComplianceOfficer |
| POST   | `/housing/hotel-blocks/{id}/commission-invoice` | Issue the post-event commission and rebate invoice on the chosen basis | BureauCoordinator |
| GET    | `/housing/commission-invoices/{id}` | Read one commission invoice with both bases and the variance | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| GET    | `/housing/hotel-blocks/{id}/commission-invoices` | The invoice issued for a block (at most one) | BureauCoordinator, BureauController, EventOrganizer, HotelManager |
| POST   | `/housing/commission-invoices/{id}/payments` | Hotel remits commission cash against the invoice | HotelManager |
| POST   | `/housing/commission-invoices/{id}/payment-reversals` | Reverse previously posted commission cash | BureauController |
| POST   | `/housing/commission-invoices/{id}/dispute` | Hotel disputes the invoice when the reconciliation variance exceeds tolerance | HotelManager |
| POST   | `/housing/commission-invoices/{id}/adjust` | Write off part of a disputed invoice | BureauController |
| POST   | `/housing/_clock/set_current_utc` | Reposition the server's logical clock | BureauCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOTEL_NOT_FOUND` | 404 Not Found |
| `ERR_HOTEL_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_SUB_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_ATTENDEE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_REDUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_CODE_DUPLICATE` | 409 Conflict |
| `ERR_ATTENDEE_EMAIL_DUPLICATE` | 409 Conflict |
| `ERR_DUPLICATE_INCIDENT` | 409 Conflict |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_BLOCK_STATE` | 409 Conflict |
| `ERR_BLOCK_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_SUB_BLOCK_STATE` | 409 Conflict |
| `ERR_RESERVATION_NOT_MODIFIABLE` | 409 Conflict |
| `ERR_INVALID_REDUCTION_STATE` | 409 Conflict |
| `ERR_INVALID_VENDOR_STATE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_HOTEL_SUSPENDED` | 409 Conflict |
| `ERR_NO_APPROVED_SUB_BLOCK` | 409 Conflict |
| `ERR_STALE_BLOCK_VERSION` | 412 Precondition Failed |
| `ERR_CUTOFF_PASSED` | 409 Conflict |
| `ERR_CUTOFF_NOT_REACHED` | 409 Conflict |
| `ERR_EVENT_NOT_ENDED` | 409 Conflict |
| `ERR_REDUCTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ATTENDEE_HOUSING_RISK_HOLD` | 409 Conflict |
| `ERR_EVENT_NOT_ACCEPTING_HOUSING` | 409 Conflict |
| `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STAY_WINDOW` | 422 Unprocessable Entity |
| `ERR_ATTENDEE_STAY_OVERLAP` | 409 Conflict |
| `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED` | 409 Conflict |
| `ERR_REDUCTION_RIGHTS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_REVERSAL_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_NO_TRANSMITTABLE_RESERVATIONS` | 422 Unprocessable Entity |
| `ERR_INVALID_TRANSMISSION_TYPE` | 409 Conflict |
| `ERR_TERMS_NOT_STANDARDIZED` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_PICKUP_REPORT_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_PICKUP_REPORT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_VARIANCE_WITHIN_TOLERANCE` | 422 Unprocessable Entity |
