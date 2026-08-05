# Smart-Curb & Loading-Zone Management API — Product Requirements Document

## 1. Introduction

Curb space at the edge of a busy street is one of the most contested and least-instrumented assets a city owns. A single block-face may need to serve freight loading in the morning, valet drop-off at midday, ride-hail pickups in the evening, and metered passenger parking overnight — and today those uses collide because nobody holds a live, authoritative picture of who is allowed where and when. This document specifies the Smart-Curb & Loading-Zone Management API, a system that turns the curb into a managed, bookable, and priced inventory.

The platform maintains a digital map of curb zones and their designations, issues and adjudicates permits for loading, valet, and ride-hail (TNC) operators, and lets those permit-holders reserve time-boxed delivery windows against dynamic, occupancy-aware pricing. Roadside sensors feed real-time occupancy that both drives surge pricing and settles the final charge for every reservation. When a festival, film shoot, or construction project temporarily takes the curb, the system reallocates affected zones and refunds the reservations it displaces. Enforcement officers issue citations that link back to the sensor evidence, and every charge, refund, adjustment, and fine flows into a single revenue ledger.

Because the platform governs both money and public right-of-way, its rules are strict: permits are reviewed and approved by two different people (four-eyes segregation of duties), curb redesignations are guarded against stale overwrites, and every price is computed to the cent with a fixed rounding discipline. The remainder of this document defines the global contracts every endpoint honors, the business logic behind each workflow, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that every endpoint obeys regardless of the specific workflow it serves.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Permittee`, `CurbPlanner`, `PermitApprover`, `EnforcementOfficer`, and `PlatformAdmin`.

- A `Permittee` is a curb user — a carrier, valet operator, TNC, or merchant. When `X-User-Role` is `Permittee`, `X-User-ID` is the `id` of the acting `Permittee` entity; ownership checks on any resource that references a `Permittee` compare that resource's owning permittee to `X-User-ID`. A permittee may create and drive its own permits, schedule windows, and reservations, and may pay or dispute its own citations, but may not act on resources owned by another permittee.
- A `CurbPlanner` is a curb-authority operator who manages inventory, designations, pricing, and events, and performs the reviewer step of permit approval. When `X-User-Role` is `CurbPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `reviewer_user_id` on a permit when the planner takes it under review, but does not compare it to any entity's `id`.
- A `PermitApprover` is the second-line authority that approves or denies permits. When `X-User-Role` is `PermitApprover`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `approver_user_id` on the permit but does not treat it as an entity key.
- An `EnforcementOfficer` issues citations, adjudicates disputes, marks no-shows, and may fulfill observed reservations. When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `PlatformAdmin` onboards permittees and drives the sensor feed and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may be no less than 1, and may be no greater than 100. The `offset` parameter names how many items to skip and defaults to 0, with no upper bound. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

Unless a specific endpoint states otherwise, every list is returned sorted by `created_at` in ascending order; when two resources share the same `created_at` (as happens when they are created at the same logical-clock instant), the tie is broken by their creation order, so the earlier-created resource sorts first. Each list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reflects the full number of matching resources before the page window is applied and `has_more` is true exactly when unreturned matches remain beyond the current page.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. `updated_at` is an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation of the resource. The `version` is an integer that starts at 1 on creation and increments by one on every subsequent mutation.

Three resource kinds are deliberately lightweight and carry only `id` and `created_at` — they have neither an `updated_at` nor a `version`. These are the pricing policy, the schedule window, and the ledger entry: a pricing policy is a static rate card, a schedule window is an immutable recurring authorization, and a ledger entry is an append-only financial record. All other resources — permittees, curb zones, permits, reservations, occupancy sessions, citations, and curb events — carry the full `id`, `created_at`, `updated_at`, and `version` quartet.

Whenever a server-driven reconciliation changes a resource that a client did not directly target — for example, a zone suspended by an activating event, or a reservation cancelled by a permit revocation — that resource independently has its `updated_at` refreshed and its `version` incremented, exactly as a direct mutation would.

### 2.5. Nested and Referenced Resource Resolution

Entities in this system are peers linked by foreign-key fields rather than nested under one another in the URL. Even so, a single request commonly names several resources — a path id plus one or more referenced ids in the body. The server resolves them left to right, path identifier first and then body references in the order they appear, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A reservation created against a non-existent permit therefore fails on the permit before the zone is ever examined.

### 2.6. Monetary Precision and Basis-Point Arithmetic

All money in the system is expressed as an integer number of cents; there are no fractional-cent balances. Rates and multipliers are expressed in basis points, where 10000 basis points equals a multiplier of exactly 1.0 — so a peak multiplier of 12500 basis points multiplies a figure by 1.25, and 15000 basis points multiplies by 1.5. Occupancy ratios are likewise expressed in basis points, where 5000 basis points is a ratio of 0.50 and 8000 basis points is 0.80.

Wherever a calculation produces a monetary result, the final value is rounded to a whole number of cents using round-half-up (a result whose fractional part is exactly one-half rounds away from zero, to the next higher cent). Where a rule pins a specific rounding order — most notably event refunds — that order is authoritative and is spelled out with the rule.

### 2.7. Optimistic Concurrency on Zone Redesignation

Changing a curb zone's designation or its base-rate override is an optimistic-concurrency-guarded operation. A redesignation request must carry `expected_zone_version`, a non-optional field holding the `version` of the target zone that the client last observed. If `expected_zone_version` does not equal the zone's current `version`, the write is refused with `ERR_STALE_VERSION` (HTTP 412), on the grounds that another redesignation has legitimately superseded the client's view and the client is acting on a stale copy of the zone. When the versions match, the redesignation applies and the zone's `version` increments by one. No other endpoint accepts or requires a version field; redesignation is the sole optimistic-concurrency-guarded write.

### 2.8. Zone Reallocation and Cascade Consistency

Several operations mutate more than one resource in a single logical step, and each such cascade is authoritative and complete — an implementation that performs only the primary transition is incorrect. Activating a curb event suspends its zones, cancels the confirmed reservations those zones held over the event window, refunds them, and writes the corresponding ledger entries; closing the event restores exactly the zones that event suspended. Revoking an active permit cancels and refunds that permit's future confirmed reservations. In every cascade, each touched resource independently has its `version` incremented and its `updated_at` refreshed, following the common-property rule of §2.4. The precise membership and financial effect of each cascade are defined in the workflow sections of §3.

### 2.9. Validation Ordering and Precedence

When an endpoint could fail more than one check, the checks are evaluated in a fixed precedence so that the returned `error_id` is deterministic. The order is: first authentication (`ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_UNAUTHORIZED`), then existence of every path id and referenced foreign key (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then segregation of duties on permit approval and denial (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity state gates such as zones-active and permit-active (`ERR_ZONE_NOT_ACTIVE` and `ERR_PERMIT_NOT_ACTIVE`), then temporal-overlap conflicts such as zone-capacity and exclusive-window collisions (`ERR_ZONE_CAPACITY_CONFLICT` and `ERR_SCHEDULE_WINDOW_CONFLICT`), then field-level constraint checks (`ERR_VALIDATION`), and finally the optimistic-concurrency check on redesignation (`ERR_STALE_VERSION`). Earlier checks mask later ones: a request that both targets a wrong-state resource and carries a stale version surfaces the state error, not the version error.

Field-level constraint failures — an end instant not strictly after a start, a `capacity_slots` below 1, a `day_of_week` outside 0 through 6, a minute value outside its permitted bounds — are reported as `ERR_VALIDATION` (HTTP 422). An enum field that carries a value outside its permitted set is reported as `ERR_INVALID_ENUM` (HTTP 422); this applies uniformly to every enum-membership field a client may supply — for example a bad `target_status`, `decision`, `violation_type`, `designation` (on zone creation or redesignation), `requested_designation`, or `permittee_type`. A required body field that is entirely absent is reported as `ERR_MISSING_FIELD` (HTTP 422).

### 2.10. The Revenue Ledger Principle

Every movement of money is recorded as an immutable ledger entry, and the ledger is the single source of truth for revenue. Each entry carries an `entry_type` of `CHARGE`, `REFUND`, `ADJUSTMENT`, or `FINE`, and a signed `amount_cents`: charges and fines are positive, refunds are negative, and an adjustment is signed as the settled amount minus the previously estimated amount. An entry also carries the `zone_id` it is attributed to, an optional `reservation_id` and `citation_id` linking it to its originating workflow, and a free-text `memo` explaining the reason.

The ledger is designed so that compensating flows return balances to truth: cancelling a captured reservation before it starts writes a refund equal and opposite to its charge, so that reservation's contribution to the ledger nets to zero. A zone's `revenue_accrued_cents` is not stored independently but is computed on read as the signed sum of `amount_cents` across every ledger entry whose `zone_id` is that zone.

### 2.11. Segregation of Duties

Permit adjudication enforces four-eyes control. The `CurbPlanner` who takes a permit under review is recorded as its `reviewer_user_id`; the `PermitApprover` who later approves or denies it is recorded as its `approver_user_id`. The `X-User-ID` performing the approval or denial must differ from the recorded `reviewer_user_id`. If they are equal, the action is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), guaranteeing that no single individual both reviews and adjudicates the same permit.

## 3. Business Logic & Workflows

### 3.1. Curb Inventory: Permittees, Pricing Policies, and Zones

The system's foundation is its inventory of curb space and the parties allowed to use it. A `PlatformAdmin` onboards a permittee by supplying a `legal_name`, a `contact_email`, and a `permittee_type` drawn from `CARRIER`, `VALET_OPERATOR`, `TNC`, or `MERCHANT`. A new permittee opens in `ACTIVE` standing — the only account standing in this version — with its `outstanding_fines_cents` starting at zero. That outstanding balance is computed on demand as the sum of `fine_due_cents` across the permittee's citations whose `status` is `ISSUED`, `DISPUTED`, or `UPHELD`; citations that are `PAID` or `DISMISSED` leave the open set and no longer contribute.

Before zones can be priced, a `CurbPlanner` defines a pricing policy. A policy carries a `name`, a `base_rate_cents_per_15min` giving the base charge for each 15-minute slot, a time-of-use `peak_multiplier_bps`, and a half-open peak window described by `peak_start_hour` (inclusive) and `peak_end_hour` (exclusive), both whole hours from 0 through 23 in UTC. It also carries a two-tier surge schedule: `surge_tier1_ratio_bps` with its `surge_tier1_mult_bps`, and the higher `surge_tier2_ratio_bps` with its `surge_tier2_mult_bps`. These thresholds and multipliers drive the dynamic pricing described in §3.4.

A `CurbPlanner` creates a curb zone by giving it a `name`, a `block_face` street identifier, a `length_meters` physical length, an initial `designation` from `LOADING`, `VALET`, `TNC`, `PASSENGER`, `METERED`, or `NO_STANDING`, a `capacity_slots` count that must be at least 1, and a `pricing_policy_id` binding it to a policy. An optional `base_rate_override_cents` may be supplied; when it is omitted the policy's base rate applies, and when it is present it replaces the policy base rate for reservations on that zone. A newly created zone opens with `status` of `ACTIVE`, a `sensor_occupancy_state` of `VACANT`, `revenue_accrued_cents` of zero, and `version` 1. A zone's `sensor_occupancy_state` is `OCCUPIED` exactly while it holds at least one open occupancy session and reverts to `VACANT` otherwise. Zones may be listed and filtered by `designation`, `status`, and `pricing_policy_id`, and the digital curb map presents zones — filterable by `designation` and `status` — alongside their live occupancy and pricing.

A zone's operational `status` moves among `ACTIVE`, `SUSPENDED`, and `RETIRED` under a `CurbPlanner`'s direction through a status-setting action that names a `target_status`. From `ACTIVE` a planner may move the zone to `SUSPENDED`, and from `SUSPENDED` back to `ACTIVE`. A planner may move an `ACTIVE` zone to `RETIRED` only when the zone holds no `CONFIRMED` reservation whose end instant lies in the future relative to the logical clock; if any such reservation exists the retirement is refused with `ERR_ZONE_HAS_ACTIVE_RESERVATIONS`. Retirement is reversible: a `RETIRED` zone may be reopened to `ACTIVE`. Every one of these status transitions increments the zone's `version` by one. A status change requested from a state where it is not defined — suspending an already-suspended zone, for instance — is refused with `ERR_INVALID_STATE`.

Redesignation is distinct from a status change: it alters a zone's `designation` and, if supplied, its `base_rate_override_cents`, and it is the optimistic-concurrency-guarded supersede described in §2.7. A redesignation names the new `designation`, optionally a new `base_rate_override_cents`, and the required `expected_zone_version`; on success the zone's `designation` (and override, when given) is updated and its `version` increments by one.

### 3.2. The Permit Lifecycle and Four-Eyes Approval

A permit authorizes a permittee to use specific curb zones for a specific purpose, and it travels a review loop that can cycle before it resolves. A `Permittee` drafts a permit by supplying its own `permittee_id`, a `requested_designation` from `LOADING`, `VALET`, or `TNC`, a free-text `purpose`, and a `zone_ids` list naming the zones it seeks to use. A fresh permit opens in `DRAFT` status with `version` 1.

The owning permittee submits the draft for review, moving it from `DRAFT` to `SUBMITTED`; submission requires that the acting permittee owns the permit and that the permit names at least one zone. A `CurbPlanner` then takes a `SUBMITTED` permit under review, moving it to `UNDER_REVIEW` and recording that planner's `X-User-ID` as the permit's `reviewer_user_id`. From `UNDER_REVIEW` the planner may send the permit back for revision with a `note` — this records the supplied text as `last_change_note` and returns the permit to `DRAFT`, forming the revision loop `DRAFT → SUBMITTED → UNDER_REVIEW → DRAFT` that may repeat as many times as needed.

Adjudication is reserved to a `PermitApprover` and is subject to the four-eyes rule of §2.11. Approving an `UNDER_REVIEW` permit requires that the approver's `X-User-ID` differ from the recorded `reviewer_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`) and that every zone named in `zone_ids` currently has `status` of `ACTIVE` (otherwise `ERR_ZONE_NOT_ACTIVE`); on success the permit moves to `ACTIVE` and the approver's `X-User-ID` is recorded as `approver_user_id`. Denying an `UNDER_REVIEW` permit takes a `reason`, likewise requires the approver to differ from the reviewer, records the `approver_user_id`, and moves the permit to the terminal `DENIED` state. Each of these transitions increments the permit's `version` by one, and each is defined only from `UNDER_REVIEW`; attempting it from any other state yields `ERR_INVALID_STATE`.

Revocation closes out an `ACTIVE` permit. When a `CurbPlanner` revokes a permit with a `reason`, the permit moves to the terminal `REVOKED` state and a cascade fires over that permit's future bookings: every `CONFIRMED` reservation on the permit whose start instant is later than the logical clock is moved to `CANCELLED`, and any such reservation whose payment was `CAPTURED` has its `payment_status` moved to `REFUNDED` with a compensating ledger `REFUND` entry equal to the negative of its `estimated_price_cents`. The permit's `version` increments by one as part of the revocation.

### 3.3. Authorization Windows and Turnover Buffers

A permit's authorization can be pinned to recurring time windows on specific zones. A `Permittee` attaches a schedule window to one of its own permits by supplying the `permit_id`, the `zone_id` it authorizes, a `day_of_week` from 0 (Monday) through 6 (Sunday), a `start_minute` measured inclusively as minutes from midnight, an `end_minute` measured exclusively as minutes from midnight, and an optional `exclusive` flag that defaults to false. Minute values must fall within 0 through 1440 and the day must fall within its bounds, or the window is rejected with `ERR_VALIDATION`. Windows may be listed and filtered by `permit_id` and `zone_id`.

Non-exclusive windows represent shared, aggregate use and never conflict with one another. An `exclusive` window, however, claims sole use of its zone and must respect a turnover buffer against other exclusive windows on the same `zone_id` and the same `day_of_week`. For buffer purposes each window is treated as the closed interval from its `start_minute` to its `end_minute`. The gap between a candidate window and an existing exclusive window is the larger of two differences: the candidate's `start_minute` minus the other's `end_minute`, and the other's `start_minute` minus the candidate's `end_minute`. Two exclusive windows conflict when this gap is strictly less than the turnover buffer of 15 minutes; a gap of exactly 15 minutes is permitted, and because a direct overlap produces a negative gap it is always a conflict. A conflicting insertion is refused with `ERR_SCHEDULE_WINDOW_CONFLICT`.

### 3.4. Reserving the Curb: Booking, Confirmation, and Dynamic Pricing

Delivery-window reservations are where permits, zones, and pricing meet. A `Permittee` books a reservation on one of its own permits by supplying the `permit_id`, the target `zone_id`, a `start_utc` instant (inclusive), and an `end_utc` instant (exclusive) — the window is treated as the half-open interval from `start_utc` up to but not including `end_utc`, and `end_utc` must be strictly after `start_utc`. A new reservation opens with `booking_status` of `PENDING`, `payment_status` of `UNPAID`, and `version` 1; its `estimated_price_cents`, `settled_price_cents`, and `surge_ratio_bps` are not yet set. Reservations may be listed and filtered by `permit_id`, `zone_id`, and `booking_status`.

Confirming a `PENDING` reservation is the pricing and payment moment, and it is gated. The acting permittee must own the reservation's authorizing permit; that permit must be `ACTIVE` (otherwise `ERR_PERMIT_NOT_ACTIVE`); the reserved zone must be `ACTIVE` (otherwise `ERR_ZONE_NOT_ACTIVE`); and the reservation must fit the zone's capacity. Capacity is judged by counting the `CONFIRMED` reservations on the zone whose half-open window overlaps this one; if that count is already at or above the zone's `capacity_slots`, the confirmation is refused with `ERR_ZONE_CAPACITY_CONFLICT`. On success the reservation moves from `PENDING` to `CONFIRMED`, an estimated price is computed and stamped into `estimated_price_cents` together with the `surge_ratio_bps` used to derive it, the `payment_status` moves from `UNPAID` to `CAPTURED`, a ledger `CHARGE` entry equal to the positive estimated price (carrying the `zone_id` and `reservation_id`) is appended, and the reservation's `version` increments by one.

The dynamic price is built in cents from four factors. The base is the zone's `base_rate_override_cents` when that override is set, and otherwise the policy's `base_rate_cents_per_15min`. The billable duration in minutes is divided by 15 and rounded up to the next whole number to yield the count of chargeable slots — so any partial slot is charged as a full slot. A time-of-use factor is applied from the window's start hour in UTC: if that start hour falls at or after `peak_start_hour` and strictly before `peak_end_hour`, the peak factor is `peak_multiplier_bps`, and otherwise it is 10000 basis points (no adjustment). A surge factor is then applied from occupancy: the system counts the other `CONFIRMED` reservations on the zone whose windows overlap this one (excluding the reservation being priced), multiplies that count by 10000, divides by the zone's `capacity_slots`, and rounds down to a whole number of basis points to obtain the occupancy ratio. If that ratio is at or above `surge_tier2_ratio_bps` the surge factor is `surge_tier2_mult_bps`; otherwise if it is at or above `surge_tier1_ratio_bps` the surge factor is `surge_tier1_mult_bps`; otherwise the surge factor is 10000 basis points. The price in cents is the base multiplied by the slot count, multiplied by the time-of-use factor, multiplied by the surge factor, divided by 10000 twice (once for each basis-point factor), and rounded half-up to a whole number of cents.

This computation has two variants that differ only in which duration they use. At confirmation the **estimate** variant uses the booked duration — the minutes between `start_utc` and `end_utc` — and stamps `estimated_price_cents` and `surge_ratio_bps`. At fulfillment the **settled** variant recomputes the price from the actually observed minutes (see §3.5) while reusing the very same `surge_ratio_bps` that was stamped at confirmation, and stamps `settled_price_cents`.

### 3.5. Sensor Occupancy and Reservation Settlement

Roadside sensors record when vehicles occupy the curb, and these observations both flip a zone's live occupancy and settle reservation charges. A `PlatformAdmin` drives the sensor feed: an entry event opens an occupancy session on a `zone_id`, optionally carrying the `reservation_id` the vehicle presented, stamping `entered_at` from the logical clock, setting `session_status` to `OPEN`, and flipping the zone's `sensor_occupancy_state` to `OCCUPIED`. An exit event, naming the `session_id`, closes an `OPEN` session: it stamps `exited_at` from the logical clock, computes `actual_minutes`, moves `session_status` to `CLOSED`, increments the session's `version`, and — if no other open session remains on the zone — returns the zone's `sensor_occupancy_state` to `VACANT`. The observed `actual_minutes` is the elapsed time from `entered_at` to `exited_at` measured in seconds, divided by 60 and rounded up to the next whole minute, so that a 62-second stay counts as 2 minutes while a zero-length stay counts as 0. Occupancy sessions may be listed and filtered by `zone_id`, `reservation_id`, and `session_status`.

Fulfilling a `CONFIRMED` reservation settles its final charge and may be performed by the owning `Permittee` or by an `EnforcementOfficer`. Fulfillment requires that a `CLOSED` occupancy session exists whose `reservation_id` matches this reservation; if none does, it is refused with `ERR_NO_OCCUPANCY_SESSION`. When more than one `CLOSED` session matches, the most recently created matching session (the one with the latest creation order) supplies the `actual_minutes` used for settlement. On success the reservation moves from `CONFIRMED` to `FULFILLED`, the settled price is computed with the settled variant of §3.4 using that session's `actual_minutes` and the reservation's stamped `surge_ratio_bps`, and the result is stamped into `settled_price_cents`. If the settled price differs from the previously stamped `estimated_price_cents`, a ledger `ADJUSTMENT` entry is appended whose `amount_cents` is the settled price minus the estimated price (positive when the settlement is higher, negative when lower); if the two are equal, no adjustment entry is written. The reservation's `version` increments by one.

Reservations can also end without fulfillment. Cancelling a `PENDING` reservation simply moves it to `CANCELLED`; because no charge was ever captured, its `payment_status` stays `UNPAID` and no ledger entry is written. Cancelling a `CONFIRMED` reservation is permitted only while the logical clock is still before the reservation's `start_utc`; a cancellation attempted at or after the window has begun is refused with `ERR_CANCEL_AFTER_START`. A permitted cancellation of a confirmed reservation moves it to `CANCELLED`, moves `payment_status` from `CAPTURED` to `REFUNDED`, and appends a ledger `REFUND` entry equal to the negative of `estimated_price_cents`, so the reservation's ledger contribution nets back to zero. An `EnforcementOfficer` may mark a `CONFIRMED` reservation a no-show, but only once the logical clock has reached or passed the reservation's `end_utc` and no occupancy session ever matched it; the reservation moves to `NO_SHOW`, its captured payment is forfeited with no refund, and its `version` increments. Each of these terminal transitions increments the reservation's `version` by one, and any of them attempted from a state where it is not defined yields `ERR_INVALID_STATE`.

### 3.6. Enforcement: Citations, Disputes, and Fines

Enforcement links sensor evidence to financial penalties. An `EnforcementOfficer` issues a citation by naming the `zone_id` where the violation occurred, the cited `permittee_id`, and a `violation_type` from `OVERSTAY`, `NO_PERMIT`, `UNAUTHORIZED_ZONE`, or `WRONG_DESIGNATION`, and may optionally attach the `occupancy_session_id` and `reservation_id` that evidence it. On issue the citation opens in `ISSUED` status, stamps `issued_at` from the logical clock, sets `due_at` to two weeks (14 days) after `issued_at`, and computes its base `fine_due_cents` from the violation type: an `OVERSTAY` is 7,500 cents, a `NO_PERMIT` is 15,000 cents, an `UNAUTHORIZED_ZONE` is 10,000 cents, and a `WRONG_DESIGNATION` is 5,000 cents. Citations may be listed and filtered by `zone_id`, `reservation_id`, `occupancy_session_id`, `permittee_id`, and `status`.

The cited `Permittee` may either pay or dispute. Paying an `ISSUED` citation moves it to the terminal `PAID` state, appends a ledger `FINE` entry equal to the positive `fine_due_cents` (carrying the `zone_id` and `citation_id`), and recomputes the permittee's `outstanding_fines_cents` as the paid citation leaves the open set, incrementing the citation's `version`. Disputing an `ISSUED` citation moves it to `DISPUTED` and increments its `version`, leaving the fine outstanding while adjudication is pending.

An `EnforcementOfficer` adjudicates a `DISPUTED` citation by supplying a `decision`. A `decision` of `UPHELD` moves the citation to `UPHELD` and recomputes `fine_due_cents`: if the logical clock is now past the citation's `due_at`, a 25% late penalty is applied by multiplying the base fine by 12500 basis points and rounding half-up — so a late-upheld `OVERSTAY` rises from 7,500 to 9,375 cents — while an on-time adjudication leaves the base fine unchanged. A `decision` of `DISMISSED` moves the citation to the terminal `DISMISSED` state and recomputes the permittee's `outstanding_fines_cents`, restoring the pre-issue receivable as the citation leaves the open set. Either adjudication increments the citation's `version`. A citation left in `UPHELD` may then be paid by the permittee, which — exactly as with an issued citation — appends a `FINE` ledger entry for the recomputed `fine_due_cents`, recomputes the outstanding balance, moves the citation to `PAID`, and increments its `version`. Any of these citation actions attempted from a state where it is not defined is refused with `ERR_INVALID_STATE`.

### 3.7. Curb Events and Zone Reallocation

When a festival, construction project, or film shoot temporarily commandeers the curb, a curb event models the reallocation. A `CurbPlanner` creates an event with a `name`, a planned `start_utc` and `end_utc`, and a `zone_ids` list naming the zones it will take over. A new event opens in `PLANNED` status with `total_refund_cents` of zero and `version` 1, and may be fetched thereafter.

Activating a `PLANNED` event fires the system's most far-reaching cascade. Each zone in the event's `zone_ids` that is currently `ACTIVE` is suspended by the system, moving to `SUSPENDED`. Every `CONFIRMED` reservation on those zones whose window overlaps the event window is moved to `CANCELLED_BY_EVENT`, its `payment_status` moves to `REFUNDED`, and a ledger `REFUND` entry is appended for it. The event's `total_refund_cents` is then the sum of the individual reservation refunds. Each affected reservation's refund is prorated by unused time: its total duration is the minutes between its `start_utc` and `end_utc`; if the logical clock is at or before the reservation's `start_utc` the reservation has not begun and its remaining minutes equal its full duration, but if the clock is already past its `start_utc` the remaining minutes are the minutes from the clock to its `end_utc`. That reservation's refund is its `estimated_price_cents` multiplied by its remaining minutes, divided by its total minutes, rounded half-up to whole cents. The rounding order is pinned: each reservation's refund is rounded to whole cents first and only then are the per-reservation refunds summed into `total_refund_cents` — summing the raw amounts and rounding once would give a different, incorrect result. Each appended `REFUND` entry carries the negative of that reservation's rounded refund together with its `reservation_id` and `zone_id`, and every touched zone and reservation has its `version` incremented. Activation itself increments the event's `version`.

Closing an `ACTIVE` event restores the curb: each zone that this event suspended is returned to `ACTIVE` by the system — only the zones suspended by this event, not zones a planner suspended by hand — and the event moves to `CLOSED` with its `version` incremented. A `PLANNED` event that never activated may instead be cancelled, moving it to the terminal `CANCELLED` state with its `version` incremented; since no zones were suspended, there is nothing to restore. Any event transition attempted from a state where it is not defined is refused with `ERR_INVALID_STATE`.

### 3.8. Ledger Inspection and Revenue Roll-Up

Every financial effect described above lands in the ledger, and the ledger is where a `CurbPlanner` reconstructs revenue. Individual ledger entries can be fetched and listed, filtered by `zone_id`, `reservation_id`, `citation_id`, and `entry_type`. Each entry's `entry_type`, signed `amount_cents`, `memo`, and its linking `zone_id`, `reservation_id`, and `citation_id` describe one movement of money, following the sign conventions of §2.10.

The revenue roll-up summarizes the ledger, optionally scoped to a single `zone_id`. It reports the sum of `amount_cents` over `CHARGE` entries as `total_charge_cents`, over `REFUND` entries (a non-positive figure) as `total_refund_cents`, over `ADJUSTMENT` entries as `total_adjustment_cents`, and over `FINE` entries as `total_fine_cents`. The `net_revenue_cents` is the sum of those four figures — charges plus refunds plus adjustments plus fines. When a `zone_id` filter is supplied, every sum is restricted to entries attributed to that zone, which is exactly how a zone's own `revenue_accrued_cents` is derived.

An administrative test-driving capability lets a `PlatformAdmin` advance the server's logical clock to a supplied instant by naming `to_iso8601`; the clock starts at `2026-05-01T00:00:00Z` and, until moved, reads exactly that default rather than any wall-clock time. This clock-setting call returns `200 OK` with a `data` object of the form `{ "current_utc": <the supplied to_iso8601 string, echoed verbatim> }` rather than a persisted resource. Every "now" referenced in the workflows above — reservation start and end comparisons, citation issue and due timing, occupancy stamps, and event proration — is read from this logical clock.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource return `201 Created`; endpoints that modify or transition an existing resource, including the sensor exit and all list and fetch reads, return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/curb/permittees` | Register a permittee | PlatformAdmin |
| GET | `/curb/permittees/{id}` | Get a permittee (includes computed outstanding fines) | PlatformAdmin, Permittee, EnforcementOfficer, CurbPlanner |
| POST | `/curb/pricing-policies` | Create a pricing policy | CurbPlanner |
| GET | `/curb/pricing-policies/{id}` | Get a pricing policy | CurbPlanner, Permittee |
| POST | `/curb/zones` | Create a curb zone | CurbPlanner |
| GET | `/curb/zones/{id}` | Get a curb zone | CurbPlanner, Permittee, EnforcementOfficer, PlatformAdmin |
| GET | `/curb/zones` | List curb zones (filterable) | CurbPlanner, Permittee |
| POST | `/curb/zones/{id}/redesignate` | Change a zone's designation and/or base rate (OCC-guarded) | CurbPlanner |
| POST | `/curb/zones/{id}/status` | Set a zone operational status | CurbPlanner |
| GET | `/curb/map` | Digital curb map with live occupancy and pricing | CurbPlanner, Permittee, EnforcementOfficer |
| POST | `/curb/permits` | Create a permit (DRAFT) | Permittee |
| GET | `/curb/permits/{id}` | Get a permit | Permittee, CurbPlanner, PermitApprover |
| GET | `/curb/permits` | List permits (filterable) | Permittee, CurbPlanner, PermitApprover |
| POST | `/curb/permits/{id}/submit` | Submit a permit for review | Permittee |
| POST | `/curb/permits/{id}/review` | Take a submitted permit under review | CurbPlanner |
| POST | `/curb/permits/{id}/request-changes` | Send a permit back for revision | CurbPlanner |
| POST | `/curb/permits/{id}/approve` | Approve a permit | PermitApprover |
| POST | `/curb/permits/{id}/deny` | Deny a permit | PermitApprover |
| POST | `/curb/permits/{id}/revoke` | Revoke an active permit (cascades to future reservations) | CurbPlanner |
| POST | `/curb/schedule-windows` | Attach a recurring authorization window to a permit | Permittee |
| GET | `/curb/schedule-windows/{id}` | Get a schedule window | Permittee, CurbPlanner |
| GET | `/curb/schedule-windows` | List schedule windows (filterable) | Permittee, CurbPlanner |
| POST | `/curb/reservations` | Create a delivery-window reservation (PENDING) | Permittee |
| GET | `/curb/reservations/{id}` | Get a reservation | Permittee, CurbPlanner, EnforcementOfficer |
| GET | `/curb/reservations` | List reservations (filterable) | Permittee, CurbPlanner, EnforcementOfficer |
| POST | `/curb/reservations/{id}/confirm` | Confirm a reservation: price estimate, capture payment | Permittee |
| POST | `/curb/reservations/{id}/cancel` | Cancel a reservation (refund if captured) | Permittee |
| POST | `/curb/reservations/{id}/fulfill` | Fulfill a reservation: settled price, ledger adjustment | Permittee, EnforcementOfficer |
| POST | `/curb/reservations/{id}/no-show` | Mark a confirmed reservation a no-show | EnforcementOfficer |
| POST | `/_sensor/occupancy-enter` | Sensor event: vehicle entered a zone | PlatformAdmin |
| POST | `/_sensor/occupancy-exit` | Sensor event: vehicle exited a zone | PlatformAdmin |
| GET | `/curb/occupancy-sessions/{id}` | Get an occupancy session | CurbPlanner, EnforcementOfficer |
| GET | `/curb/occupancy-sessions` | List occupancy sessions (filterable) | CurbPlanner, EnforcementOfficer |
| POST | `/curb/citations` | Issue a citation | EnforcementOfficer |
| GET | `/curb/citations/{id}` | Get a citation | EnforcementOfficer, Permittee, CurbPlanner |
| GET | `/curb/citations` | List citations (filterable) | EnforcementOfficer, Permittee, CurbPlanner |
| POST | `/curb/citations/{id}/pay` | Pay a citation | Permittee |
| POST | `/curb/citations/{id}/dispute` | Dispute a citation | Permittee |
| POST | `/curb/citations/{id}/adjudicate` | Adjudicate a disputed citation | EnforcementOfficer |
| POST | `/curb/events` | Create a curb event (PLANNED) | CurbPlanner |
| GET | `/curb/events/{id}` | Get a curb event | CurbPlanner, Permittee |
| POST | `/curb/events/{id}/activate` | Activate an event: reallocate zones, cancel and refund | CurbPlanner |
| POST | `/curb/events/{id}/close` | Close an active event: restore suspended zones | CurbPlanner |
| POST | `/curb/events/{id}/cancel` | Cancel a planned event | CurbPlanner |
| GET | `/curb/ledger-entries/{id}` | Get a ledger entry | CurbPlanner |
| GET | `/curb/ledger-entries` | List ledger entries (filterable) | CurbPlanner |
| GET | `/curb/revenue` | Revenue roll-up summary (optionally scoped to a zone) | CurbPlanner |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ZONE_NOT_ACTIVE` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_ZONE_CAPACITY_CONFLICT` | 409 |
| `ERR_SCHEDULE_WINDOW_CONFLICT` | 409 |
| `ERR_ZONE_HAS_ACTIVE_RESERVATIONS` | 409 |
| `ERR_NO_OCCUPANCY_SESSION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_CANCEL_AFTER_START` | 409 |
| `ERR_MISSING_FIELD` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
