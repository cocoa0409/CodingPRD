# Corporate Travel TMC API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Corporate Travel Management (TMC) API, the backend that a managed-travel program uses to run business travel end to end. The platform ties together several concerns that, in most organizations, live in disconnected spreadsheets and email threads: traveler profiles and their governing travel policy, a booking-and-approval workflow with segregation of duties, negotiated vendor rates and preferred-vendor economics, duty-of-care traveler tracking, the recovery and reuse of unused non-refundable tickets, savings reporting, group and VIP handling, and vendor invoice reconciliation.

The central tension the system manages is the gap between what a trip is *expected* to cost when it is submitted for approval and what it *actually* costs once real segments are ticketed. Approval routing, budget controls, and savings reporting all depend on getting these two figures right and keeping them consistent as bookings are created, exchanged, cancelled, and refunded. Because these events cascade — a cancelled trip unwinds its bookings, which release negotiated-rate capacity and mint reusable ticket credits — the API treats consistency as a first-class contract rather than a best-effort afterthought.

All monetary amounts are expressed and stored as integer cents. All time-sensitive logic is driven by a server-controlled logical clock rather than wall-clock time, so that advance-purchase windows, rate-validity windows, and credit expiry behave deterministically under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. All resources live under the `/tmc` namespace (the logical-clock control endpoint being the sole exception).

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `TravelManager`, `Traveler`, `Approver`, `FinanceOfficer`, and `System`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Traveler`; ownership checks on any resource that references a `Traveler` compare the resource's traveler foreign key (for example a `TripRequest`'s `traveler_id`) to `X-User-ID`.
- When `X-User-Role` is `Approver`, `X-User-ID` is likewise the `id` of the acting `Traveler` (an approver is a `Traveler` of managerial grade acting in an approval capacity); the segregation-of-duties check compares this `X-User-ID` against the trip's `traveler_id`.
- When `X-User-Role` is `TravelManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`.
- When `X-User-Role` is `System`, `X-User-ID` is an opaque automation identifier used for time-driven sweeps and cascaded transitions; it is not tied to any persisted entity.

`TravelManager` administers program configuration (policies, travelers, vendors, negotiated rates, group blocks), suspends and reactivates travelers, and runs maintenance sweeps. `Traveler` owns trip requests and bookings and acts only on their own resources. `Approver` advances or rejects pending trip requests but may never act on their own trip. `FinanceOfficer` handles vendor invoicing and reconciliation. `System` is the automation identity. Read operations (`GET`) across the `/tmc` namespace are available to `TravelManager`, `Traveler`, `Approver`, and `FinanceOfficer`; invoice and invoice-line reads are limited to `TravelManager` and `FinanceOfficer`.

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

List endpoints are paginated through the `limit` and `offset` query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 or above 100 is clamped into that range, and a `limit` or `offset` that is not a valid integer falls back to its default (10 and 0 respectively). `offset` is the number of items skipped from the start of the result set and defaults to 0; a negative `offset` is treated as 0.

Unless otherwise stated, list endpoints return resources sorted by their `created_at` timestamp in ascending order, with ties (resources sharing an identical `created_at`) broken by ascending order of creation. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource in this system — travel policies, travelers, vendors, negotiated rates, trip requests, bookings, group bookings, unused-ticket credits, invoices, and invoice lines — carries a standard set of server-managed fields:

- `id`: a server-minted UUID with no type prefix, unique across the resource's collection.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.8.

Whenever a derived field is recomputed as a side effect of some operation — a trip's `actual_cost_cents`, a rate's `consumed_count`, a credit's `residual_value_cents`, an invoice's `reconciled_total_cents` — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource. All top-level entities in this system carry the full set of common fields; none are creation-immutable.

### 2.5. Monetary Values, Counts, and Rounding

All fares, credits, budgets, and invoice amounts are integer cents; there are no fractional-cent values stored anywhere. Counts such as a rate's `consumed_count`, a group block's `confirmed_count`, and capacity figures are non-negative integers.

Only one calculation introduces a non-integer factor: invoice reconciliation applies a management fee of three and one-half percent (a rate of 0.035) to each matched line amount. That per-line fee is rounded to whole cents using the round-half-up convention, and the rounding is applied to each line individually **before** the lines are summed — never by summing first and rounding the total. This ordering is significant because rounding each line before summation can differ from a sum-then-round approach by a cent or two, and the per-line-first order is the pinned, correct one.

### 2.6. The Logical Clock and Maintenance Sweeps

The server maintains a single logical clock that governs every time comparison in the system: advance-purchase windows, negotiated-rate validity windows, credit expiry, and exchange cutoffs. At server startup the clock reads exactly `2026-07-01T00:00:00Z`; before any client sets it, the clock returns this default and never falls back to the host wall-clock time. An operator may advance the clock to a supplied instant, provided in the `to_iso8601` field, which is the mechanism tests use to drive time-dependent behavior.

State that becomes stale as the clock advances is not swept eagerly; it is resolved by an explicit maintenance sweep. Running the sweep transitions any `ACTIVE` or `EXHAUSTED` `NegotiatedRate` whose validity has passed — that is, where the current clock is strictly after its `valid_to` — to `EXPIRED`, and transitions any `AVAILABLE` or `PARTIALLY_USED` `UnusedTicketCredit` whose expiry has passed — where the current clock is strictly after its `expiry_date` — to `EXPIRED`. `EXPIRED` is terminal for both a rate and a credit.

### 2.7. Referential Integrity and Validation Ordering

Because the entity graph is flat — entities reference one another through foreign keys carried in request bodies rather than through nested URL paths — referential checks matter greatly. Every referenced resource id, whether it arrives as a path parameter or as a foreign key in the body, must exist; ids are validated left-to-right in the order they appear, and the first id that does not resolve yields `ERR_NOT_FOUND`.

When several checks guard the same endpoint, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The global order is: (1) presence and validity of the user-context headers (`ERR_MISSING_USER_CONTEXT`); (2) the acting role's permission for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); (3) existence of all referenced ids (`ERR_NOT_FOUND`); (4) well-formedness of the request body — required fields present, enum values legal, amounts and counts positive, and any `block_size` at least 1 (`ERR_INVALID_REQUEST`); (5) the target resource being in a state that permits the requested transition (`ERR_INVALID_STATE`); (6) the optimistic-concurrency version check on booking creation (`ERR_STALE_VERSION`); (7) segregation of duties on approvals and rejections (`ERR_SELF_APPROVAL`); (8) the owning traveler being active and, on the executive approval step, the approver's rank being sufficient (`ERR_TRAVELER_SUSPENDED`); (9) the advance-purchase window (`ERR_ADVANCE_PURCHASE_VIOLATION`); (10) the per-traveler double-booking guard (`ERR_TRAVELER_DOUBLE_BOOKED`); (11) negotiated-rate and vendor availability (`ERR_RATE_UNAVAILABLE`); (12) redeemed-credit eligibility (`ERR_CREDIT_UNAVAILABLE`); (13) the hotel nightly-rate policy cap (`ERR_POLICY_VIOLATION`); (14) group-block capacity (`ERR_VENDOR_CAPACITY_EXCEEDED`); (15) the trip-level approval gate on booking (`ERR_APPROVAL_REQUIRED`); and (16) the approver-rank gate on the executive approval step (`ERR_APPROVAL_RANK_TOO_LOW`). Not every endpoint carries every check; each check applies only where its business rule is relevant, but wherever two of these do coexist the lower-numbered one is evaluated first.

### 2.8. Optimistic Concurrency on Booking Creation

A `TripRequest` is a multi-segment container, and its derived state — its `actual_cost_cents` and the set of segments already booked against it — advances every time a segment is added. To prevent a client from creating a segment against a trip whose state it has not observed, segment creation is guarded by optimistic concurrency.

Creating a booking requires the caller to supply `expected_trip_request_version`, carrying the `version` of the target `TripRequest` that the client last read. This field is mandatory on booking creation and is not accepted on any other endpoint; endpoints outside this rule take no version field. If `expected_trip_request_version` does not match the trip's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters in the ordinary multi-segment flow: creating the first segment legitimately advances the trip (it increments the trip's `version` and moves it from `APPROVED` to `BOOKED`), so a second create that still carries the version the client read before the first segment is a stale write and is refused, because the trip's derived cost and booked-segment set are no longer the ones that second request was built against.

### 2.9. Cascading Consistency Across Entities

Several operations mutate more than one entity, and every one of those cascades is part of the contract. Suspending a traveler cancels their in-flight trip requests. Cancelling a booked trip unwinds its segments, which in turn mint ticket credits and release negotiated-rate capacity, which in turn can revive an exhausted rate. Consuming or releasing negotiated-rate capacity flips a rate between `ACTIVE` and `EXHAUSTED`. Redeeming a credit advances the credit's own lifecycle. Each of these secondary mutations refreshes `updated_at` and increments `version` on the entity it touches, exactly as a direct mutation would. The specific cascades are detailed in the workflow narratives of §3; the principle here is that no cascade is optional or best-effort — when the triggering operation succeeds, every downstream effect it names must also be applied atomically.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Policies, Travelers, Vendors, and Rates

The travel program is bootstrapped by a `TravelManager`. The foundational entity is the **travel policy**, created with a `name`, the `region` it governs, and a set of controls: the highest permitted air class `max_air_class` (one of `ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, or `FIRST`), the maximum permitted hotel nightly rate `max_hotel_nightly_cents`, the minimum whole days `advance_purchase_days` that must separate a booking's creation from segment departure, the two approval thresholds `requires_manager_approval_over_cents` and `requires_exec_approval_over_cents`, the flat `exchange_penalty_cents` charged on every ticket exchange, and `credit_validity_days`, the number of whole days an unused-ticket credit remains redeemable after it is issued.

Each **traveler** is created with a `full_name`, an `email` (unique among active travelers — a create whose `email` matches that of an existing `ACTIVE` traveler is refused with `ERR_INVALID_REQUEST`), a `grade` — one of `STANDARD`, `MANAGER`, `EXECUTIVE`, or `VIP` — the `policy_id` of the travel policy that governs them, and a `home_iata` home-airport code. A traveler's `status` begins at `ACTIVE`. A `TravelManager` may suspend an active traveler, moving `status` to `SUSPENDED`; suspension cascades, cancelling every trip request of that traveler currently in `DRAFT`, `PENDING_MANAGER`, or `PENDING_EXEC` by transitioning each to `CANCELLED`. A suspended traveler may later be reactivated, moving `status` back to `ACTIVE` with no further cascade.

A **vendor** is created with a `name`, a `vendor_type` of `AIR`, `HOTEL`, or `CAR`, an `is_preferred` flag defaulting to false, and a `capacity` giving the aggregate block capacity available to overlapping group bookings. A vendor's `status` starts at `ACTIVE`; a `TravelManager` may deactivate it, moving `status` to `INACTIVE`. Travelers, vendors, negotiated rates, trip requests, bookings, group bookings, and invoices can all be listed with optional filters — travelers by `policy_id` and `status`; vendors by `vendor_type`, `is_preferred`, and `status`.

A **negotiated rate** ties a contracted fare to a route on a specific vendor. It is created with the `vendor_id`, a `rate_code`, an `origin` and `destination` IATA pair matched exactly against booking routes, the contracted `negotiated_fare_cents`, a reference `market_fare_cents` used for savings computation, a `cap_usage_count` giving the maximum number of bookings that may consume the rate, and a validity window `valid_from`/`valid_to` (both bounds inclusive). On creation its `consumed_count` is 0 and its `status` is `ACTIVE`. The number of bookings currently consuming a rate — its `consumed_count` — is at all times the count of bookings that reference the rate through `negotiated_rate_id` and are in either `TICKETED` or `EXCHANGED` status. A rate is `ACTIVE` while its `consumed_count` is below its `cap_usage_count` and becomes `EXHAUSTED` the moment `consumed_count` reaches or exceeds `cap_usage_count`; conversely, when a cancellation or refund lowers `consumed_count` back below `cap_usage_count` and the current clock is still at or before `valid_to`, an exhausted rate returns to `ACTIVE`. Negotiated rates can be listed filtered by `vendor_id`, `origin`, `destination`, and `status`.

### 3.2. The Trip Request: Submission, Approval, and Revision

A `Traveler` opens a **trip request** in `DRAFT`, supplying the `traveler_id`, the `origin` and `destination`, the planned `depart_date` and `return_date`, a free-text `purpose`, and a `market_estimate_cents` used as a fallback cost when no negotiated rate matches the route. At creation the trip's `estimated_cost_cents` and `actual_cost_cents` are not yet meaningful (the latter defaults to 0), its `approval_level_required` defaults to `NONE`, and its `status` is `DRAFT`. Trip requests can be listed by `traveler_id` and `status`.

Submitting a `DRAFT` trip computes its provisional cost and routes it for approval. The owning traveler must be `ACTIVE` at submit time; a submit by a suspended traveler is refused with `ERR_TRAVELER_SUSPENDED`. The **provisional cost** is deliberately forward-looking and optimistic — it assumes the traveler will use the best available negotiated rate. The system gathers every negotiated rate whose `origin` and `destination` match the trip's route exactly, whose `status` is `ACTIVE`, whose vendor is itself `ACTIVE`, and whose validity window contains the current clock (that is, `valid_from` is at or before now and now is at or before `valid_to`). Those candidates are ranked by `negotiated_fare_cents` ascending, breaking ties by `created_at` ascending. If at least one candidate exists, `estimated_cost_cents` is set to the cheapest candidate's `negotiated_fare_cents`; if none exists, `estimated_cost_cents` falls back to the trip's own `market_estimate_cents`.

The resulting `approval_level_required` is derived from that estimate against the policy thresholds: if `estimated_cost_cents` is at or above `requires_exec_approval_over_cents`, the level is `EXEC`; otherwise if it is at or above `requires_manager_approval_over_cents`, the level is `MANAGER`; otherwise it is `NONE`. When the level is `NONE`, submission moves the trip straight to `APPROVED`. When the level is `MANAGER` or `EXEC`, submission moves the trip to `PENDING_MANAGER`.

Approval is performed by an `Approver`, and segregation of duties is absolute: an approver whose `X-User-ID` equals the trip's `traveler_id` is refused with `ERR_SELF_APPROVAL` on both approval and rejection, regardless of any other consideration. An approver must also be a traveler of `MANAGER`, `EXECUTIVE`, or `VIP` grade; an approver of lesser grade — or one whose `X-User-ID` resolves to no traveler — acting on the `PENDING_MANAGER` step is refused with `ERR_APPROVAL_RANK_TOO_LOW`. When a `PENDING_MANAGER` trip whose required level is `MANAGER` is approved, it advances to `APPROVED`. When a `PENDING_MANAGER` trip whose required level is `EXEC` is approved, it advances only to `PENDING_EXEC` — the manager step clears first, and a second approval is still required. Clearing that `PENDING_EXEC` step demands an approver of `EXECUTIVE` grade specifically; an approver of insufficient rank is refused with `ERR_APPROVAL_RANK_TOO_LOW`, and a successful executive approval moves the trip to `APPROVED`.

Rejection is the revision loop. An approver (again, never the trip's own traveler) may reject a trip that is in either `PENDING_MANAGER` or `PENDING_EXEC`, optionally supplying a `reason`; rejection returns the trip to `DRAFT` so the traveler can revise and resubmit. An `APPROVED` or `BOOKED` trip may be cancelled by either the owning `Traveler` or a `TravelManager`, moving it to `CANCELLED`. Cancelling an `APPROVED` trip that has no segments simply terminates it. Cancelling a `BOOKED` trip triggers the full unwind cascade described in §3.3. `CANCELLED` is terminal for a trip request.

### 3.3. Booking Segments Against a Trip

Once a trip is `APPROVED` (or already `BOOKED` from an earlier segment), the owning `Traveler` books individual **segments** against it. A booking is created with the `trip_request_id`, the `vendor_id`, an optional `negotiated_rate_id`, the `segment_type` (`AIR`, `HOTEL`, or `CAR`), the `fare_basis` (`REFUNDABLE` or `NONREFUNDABLE`), the gross `fare_cents`, the segment's `depart_datetime` and `return_datetime`, an optional `redeem_credit_id` to apply an existing credit, and the mandatory `expected_trip_request_version` described in §2.8. The booking's `traveler_id` is not supplied by the client — it is copied from the trip's owner. A new booking's `status` is `TICKETED`, and its `credit_applied_cents` and `exchange_fee_cents` both default to 0. Bookings can be listed filtered by `trip_request_id`, `traveler_id`, `vendor_id`, `negotiated_rate_id`, and `status`.

Booking creation is the most heavily guarded operation in the system, and its checks fire in the global priority order of §2.7. The trip must be in `APPROVED` or `BOOKED` — a booking attempted against a trip that has not cleared approval is refused with `ERR_APPROVAL_REQUIRED`. The owning traveler must be `ACTIVE`, failing which the create is refused with `ERR_TRAVELER_SUSPENDED`. The segment's `depart_datetime` must be at least `advance_purchase_days` whole days after the current clock; a departure sooner than that window is refused with `ERR_ADVANCE_PURCHASE_VIOLATION`. The traveler must not already hold a `TICKETED` booking whose interval overlaps this segment: intervals are treated as half-open from `depart_datetime` up to but not including `return_datetime`, so two segments that merely touch end-to-start (one ending exactly when the next begins) are permitted, but any true overlap is refused with `ERR_TRAVELER_DOUBLE_BOOKED`. If a `negotiated_rate_id` is supplied, that rate must be `ACTIVE` and within its validity window and its vendor must be `ACTIVE`, else `ERR_RATE_UNAVAILABLE`. For a `HOTEL` segment, `fare_cents` (serving as the nightly-rate proxy) must not exceed the policy's `max_hotel_nightly_cents`, else `ERR_POLICY_VIOLATION`; `AIR` and `CAR` segments carry no amount cap.

When these checks pass, the booking is created and a chain of effects follows. The trip's `version` increments by one. On the very first segment, the trip moves from `APPROVED` to `BOOKED`. The trip's `actual_cost_cents` is recomputed: it is the chronological running sum, over every booking of the trip whose status is `TICKETED` or `EXCHANGED`, of that booking's `fare_cents` less its `credit_applied_cents` (cancelled and refunded segments contribute nothing). If a `negotiated_rate_id` was supplied, the rate's `consumed_count` is recomputed as described in §3.1, and the rate flips from `ACTIVE` to `EXHAUSTED` if that brings it to its cap.

If a `redeem_credit_id` is supplied, the referenced credit is applied to this booking. The credit must be `AVAILABLE` or `PARTIALLY_USED`, must not have expired, must be owned by this traveler, and must be for the same vendor as the booking; any of these failing yields `ERR_CREDIT_UNAVAILABLE`. The amount applied, recorded as `credit_applied_cents`, is the smaller of the credit's residual value before this redemption and the booking's `fare_cents`. Applying the credit reduces its residual (see §3.5) and advances the credit's lifecycle: if residual remains, the credit becomes `PARTIALLY_USED`; if the redemption consumes the entire residual, the credit becomes `REDEEMED` and its `redeemed_by_booking_id` is set to this new booking.

### 3.4. Exchanges, Cancellations, and Refunds

A `TICKETED` booking may be **exchanged** by the owning `Traveler` for a new fare, provided the trip is `BOOKED` and the current clock is at or before the segment's `depart_datetime` — a segment cannot be exchanged after departure. The exchange payload supplies the `new_fare_cents` and may optionally supply a `new_vendor_id`, a `new_negotiated_rate_id`, a `new_depart_datetime`, and a `new_return_datetime`. The exchange moves the old booking to `EXCHANGED` and creates a fresh `TICKETED` booking carrying the new fare; the new booking inherits the old booking's `segment_type` and `fare_basis`, and takes the old booking's `vendor_id`, `negotiated_rate_id`, `depart_datetime`, and `return_datetime` for any of `new_vendor_id`, `new_negotiated_rate_id`, `new_depart_datetime`, or `new_return_datetime` not supplied, while its `credit_applied_cents` starts at 0. Wherever a credit is drawn upon during an exchange, the same credit-eligibility rule that guards booking creation applies — a credit that is not `AVAILABLE` or `PARTIALLY_USED`, has expired, is not owned by the traveler, or is for the wrong vendor causes the exchange to be refused with `ERR_CREDIT_UNAVAILABLE`.

The settlement is computed from three inputs — the old booking's `fare_cents`, the `new_fare_cents`, and the policy's `exchange_penalty_cents` (the penalty). The new booking's `exchange_fee_cents` is set to the penalty. Two mutually exclusive outcomes follow. The residual credit is the old fare minus the new fare minus the penalty, floored at zero — that is, the greater of zero and (old `fare_cents` − `new_fare_cents` − penalty). When that residual is positive (a genuine downgrade after absorbing the penalty), an `UnusedTicketCredit` of exactly that residual value is issued to the traveler (its `origin_booking_id` is the old booking and its `vendor_id` is the old booking's vendor). Separately, the amount due is the new fare plus the penalty minus the old fare, floored at zero — the greater of zero and ((`new_fare_cents` + penalty) − old `fare_cents`) — representing what the traveler owes on an upgrade. `EXCHANGED` is terminal for the old booking.

Cancelling a `TICKETED` booking splits on `fare_basis`. A `NONREFUNDABLE` booking moves to `CANCELLED` and mints an `UnusedTicketCredit` whose `face_value_cents` and initial `residual_value_cents` both equal the cancelled booking's `fare_cents`, and whose `expiry_date` is the credit's creation instant plus the policy's `credit_validity_days`. A `REFUNDABLE` booking moves to `REFUNDED` and issues no credit (its refund is handled as cash out of band). In both cases, if the booking consumed a negotiated rate, that rate's `consumed_count` is recomputed downward, which may return an `EXHAUSTED` rate to `ACTIVE`, and the trip's `actual_cost_cents` is recomputed. `CANCELLED` and `REFUNDED` are both terminal for a booking.

Cancelling a `BOOKED` trip (from §3.2) drives the deepest cascade in the system. Every non-terminal booking of the trip is cancelled or refunded according to its own `fare_basis` exactly as above. Each such cancelled `NONREFUNDABLE` booking issues its ticket credit and decrements its negotiated rate's `consumed_count`; and any negotiated rate whose `consumed_count` thereby drops below its `cap_usage_count` transitions from `EXHAUSTED` back to `ACTIVE`. The whole three-level chain — trip cancel, then per-booking termination and credit issuance, then rate release and revival — is applied as one consistent unit.

### 3.5. Unused-Ticket Credits

An **unused-ticket credit** captures the value of a cancelled non-refundable ticket so it can be reused. Its fields are all server-managed: the owning `traveler_id`, the `origin_booking_id` of the cancelled booking that produced it, the `vendor_id` it is restricted to, the `redeemed_by_booking_id` of the booking that eventually fully redeems it (null until then), the original `face_value_cents`, the current `residual_value_cents`, the `expiry_date`, and the `status`. A credit begins `AVAILABLE`. Credits can be listed filtered by `traveler_id`, `origin_booking_id`, `redeemed_by_booking_id`, and `vendor_id`, as well as `status`.

A credit's `residual_value_cents` is always its `face_value_cents` minus the total applied across every booking that has drawn on it; value is neither created nor destroyed, so face value always equals residual plus applied-to-date. As §3.3 describes, each redeeming booking applies the smaller of the residual-before and the booking's fare, and the credit moves to `PARTIALLY_USED` while residual remains or to `REDEEMED` (with `residual_value_cents` reaching 0 and `redeemed_by_booking_id` set) once residual is exhausted. A credit that is `AVAILABLE` or `PARTIALLY_USED` and whose `expiry_date` has passed is moved to `EXPIRED` by the maintenance sweep (§2.6). `REDEEMED` and `EXPIRED` are terminal.

### 3.6. Group and VIP Blocks

A `TravelManager` holds a **group block** on a vendor for a set of travelers. A group booking is created with the `vendor_id`, the `organizer_traveler_id`, the `block_size` (at least 1), and the block's `start_date` and `end_date` (both inclusive). Its `confirmed_count` starts at 0 and its `status` starts at `HELD`. Group bookings can be listed by `vendor_id`, `organizer_traveler_id`, and `status`.

Holding a block is capacity-checked against the vendor's aggregate `capacity` over overlapping blocks. Two blocks on the same vendor overlap when they share any point on their closed intervals — that is, when the first's `start_date` is at or before the second's `end_date` and the second's `start_date` is at or before the first's `end_date`. The occupied capacity is the sum of `block_size` across all blocks on the vendor that are in `HELD` or `CONFIRMED` and overlap the new block. If that occupied total plus the new block's `block_size` exceeds the vendor's `capacity`, the hold is refused with `ERR_VENDOR_CAPACITY_EXCEEDED`.

A held block may be confirmed by a `TravelManager`, supplying a `confirmed_count`; confirmation requires that `confirmed_count` not exceed the block's `block_size`, else the request is refused with `ERR_INVALID_REQUEST`, and moves the block from `HELD` to `CONFIRMED`. A `HELD` block may instead be cancelled, moving it to `CANCELLED` and releasing its held capacity back to the vendor. A `CONFIRMED` block may be released, moving it to `RELEASED` and returning its confirmed capacity to the vendor. `RELEASED` and `CANCELLED` are terminal.

### 3.7. Savings Reporting

For any vendor, an authorized operator (a `TravelManager` or `FinanceOfficer`) can pull a savings report contrasting what the program actually captured against what it could have captured. The report returns three figures: `realized_savings_cents`, `potential_savings_cents`, and a `booked_count` — the latter being the number of `TICKETED` or `EXCHANGED` bookings whose `vendor_id` is this vendor. The report body is a plain object of these three figures and carries none of the common server-managed fields.

Realized savings is chronological and counts only bookings that actually used one of this vendor's rates: over every booking in `TICKETED` or `EXCHANGED` status whose `negotiated_rate_id` is set and whose rate belongs to this vendor, it sums the rate's `market_fare_cents` minus the booking's `fare_cents`. Potential savings is forward-looking and counts every booking on this vendor whether or not a rate was applied: over every `TICKETED` or `EXCHANGED` booking whose `vendor_id` is this vendor, it sums the best market fare minus the best negotiated fare, where the best rate is the cheapest negotiated rate of this vendor matching that booking's route ranked by `negotiated_fare_cents` ascending then `created_at` ascending; a booking for which the vendor has no matching rate contributes zero.

### 3.8. Vendor Invoicing and Reconciliation

A `FinanceOfficer` records a vendor **invoice** with the `vendor_id`, a `billing_period` label, the vendor-billed `invoiced_total_cents`, and a set of `lines`. Each line is created with its `booking_id` (which may be null to represent an unmatched charge) and the vendor's `billed_amount_cents` for that line. An invoice begins in `RECEIVED` with `reconciled_total_cents` and `variance_cents` at 0; each of its lines begins with `matched_amount_cents` at 0 and `match_status` of `UNMATCHED`. Invoices can be listed by `vendor_id` and `status`; invoice lines can be listed by `invoice_id` and `booking_id`, and filtered by `match_status`. Invoice and invoice-line reads are available only to `TravelManager` and `FinanceOfficer`.

Reconciling an invoice recomputes each line and the invoice totals. For a line whose `booking_id` is null, `matched_amount_cents` is 0 and `match_status` is `UNMATCHED`. For a line that references a booking, `matched_amount_cents` is that booking's `fare_cents` minus its `credit_applied_cents` (the net contracted fare); if the line's `billed_amount_cents` equals that matched amount the `match_status` is `MATCHED`, otherwise it is `PRICE_VARIANCE`. The invoice's `reconciled_total_cents` is the sum, over all lines, of each line's matched amount plus that line's management fee, where the fee is the matched amount multiplied by the 0.035 management rate and rounded half-up to whole cents per line before the summation (§2.5). The `variance_cents` is the vendor's `invoiced_total_cents` minus the computed `reconciled_total_cents`. If the variance comes out to exactly zero, reconciliation moves the invoice from `RECEIVED` to `RECONCILED`; if the variance is non-zero, it moves the invoice to `DISPUTED`.

A `DISPUTED` invoice is resolved by a `FinanceOfficer` supplying an `adjusted_invoiced_total_cents`; the invoice's `invoiced_total_cents` is replaced with that value and the variance is recomputed. Resolution requires that the adjustment bring the variance to zero — if it does not, the resolve is refused with `ERR_INVALID_STATE` — and a successful resolution moves the invoice to `RECONCILED`. A `RECONCILED` invoice may then be marked paid, moving it to `PAID`, which is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and read operations, return `200 OK`. The `POST /tmc/bookings/{id}/exchange` operation creates a new booking resource and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | TravelManager, FinanceOfficer, System |
| POST | `/tmc/maintenance/run-sweep` | Expire past-validity rates and past-expiry credits | TravelManager, System |
| POST | `/tmc/travel-policies` | Create a travel policy | TravelManager |
| GET | `/tmc/travel-policies/{id}` | Get a travel policy | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/travelers` | Create a traveler | TravelManager |
| GET | `/tmc/travelers/{id}` | Get a traveler | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/travelers` | List travelers | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/travelers/{id}/suspend` | Suspend a traveler | TravelManager |
| POST | `/tmc/travelers/{id}/reactivate` | Reactivate a suspended traveler | TravelManager |
| POST | `/tmc/vendors` | Create a vendor | TravelManager |
| GET | `/tmc/vendors/{id}` | Get a vendor | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/vendors` | List vendors | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/vendors/{id}/deactivate` | Deactivate a vendor | TravelManager |
| GET | `/tmc/vendors/{id}/savings-report` | Realized vs potential savings for a vendor | TravelManager, FinanceOfficer |
| POST | `/tmc/negotiated-rates` | Create a negotiated rate | TravelManager |
| GET | `/tmc/negotiated-rates/{id}` | Get a negotiated rate | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/negotiated-rates` | List negotiated rates | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/trip-requests` | Create a trip request (DRAFT) | Traveler |
| GET | `/tmc/trip-requests/{id}` | Get a trip request | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/trip-requests` | List trip requests | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/trip-requests/{id}/submit` | Submit a draft trip for approval routing | Traveler |
| POST | `/tmc/trip-requests/{id}/approve` | Advance a pending trip request | Approver |
| POST | `/tmc/trip-requests/{id}/reject` | Reject a pending trip back to draft | Approver |
| POST | `/tmc/trip-requests/{id}/cancel` | Cancel an approved or booked trip | Traveler, TravelManager |
| POST | `/tmc/bookings` | Create a booking segment (OCC-guarded) | Traveler |
| GET | `/tmc/bookings/{id}` | Get a booking | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/bookings` | List bookings | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/bookings/{id}/exchange` | Exchange a ticketed booking for a new fare | Traveler |
| POST | `/tmc/bookings/{id}/cancel` | Cancel a ticketed booking | Traveler |
| POST | `/tmc/group-bookings` | Hold a group block on a vendor | TravelManager |
| GET | `/tmc/group-bookings/{id}` | Get a group booking | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/group-bookings` | List group bookings | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/group-bookings/{id}/confirm` | Confirm a held group block | TravelManager |
| POST | `/tmc/group-bookings/{id}/release` | Release a confirmed group block | TravelManager |
| POST | `/tmc/group-bookings/{id}/cancel` | Cancel a held group block | TravelManager |
| GET | `/tmc/unused-ticket-credits/{id}` | Get an unused-ticket credit | TravelManager, Traveler, Approver, FinanceOfficer |
| GET | `/tmc/unused-ticket-credits` | List unused-ticket credits | TravelManager, Traveler, Approver, FinanceOfficer |
| POST | `/tmc/invoices` | Create a vendor invoice with lines | FinanceOfficer |
| GET | `/tmc/invoices/{id}` | Get an invoice | TravelManager, FinanceOfficer |
| GET | `/tmc/invoices` | List invoices | TravelManager, FinanceOfficer |
| POST | `/tmc/invoices/{id}/reconcile` | Reconcile an invoice | FinanceOfficer |
| POST | `/tmc/invoices/{id}/resolve-dispute` | Resolve a disputed invoice | FinanceOfficer |
| POST | `/tmc/invoices/{id}/pay` | Mark a reconciled invoice paid | FinanceOfficer |
| GET | `/tmc/invoice-lines/{id}` | Get an invoice line | TravelManager, FinanceOfficer |
| GET | `/tmc/invoice-lines` | List invoice lines | TravelManager, FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SELF_APPROVAL` | 403 Forbidden |
| `ERR_TRAVELER_SUSPENDED` | 409 Conflict |
| `ERR_ADVANCE_PURCHASE_VIOLATION` | 409 Conflict |
| `ERR_TRAVELER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RATE_UNAVAILABLE` | 409 Conflict |
| `ERR_CREDIT_UNAVAILABLE` | 409 Conflict |
| `ERR_POLICY_VIOLATION` | 409 Conflict |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_APPROVAL_REQUIRED` | 409 Conflict |
| `ERR_APPROVAL_RANK_TOO_LOW` | 409 Conflict |
