# Food-Hall & Shared-Vendor Management API — Product Requirements Document

## 1. Introduction

A food hall is a single venue where many independent vendors operate stalls under one roof, sharing a common seating area, a shared point-of-sale (POS) terminal, and a common event space. The operator of the venue must keep a great deal in balance at once: which vendor holds which stall and under what rent terms, whether each stall is currently cleared by the health authority to trade, where shared-POS orders should be routed, how limited seats and common-area capacity are allocated between everyday dining and marketing events, and how each vendor's rent — a blend of fixed base rent and a percentage of sales — is settled at the end of a period.

This document specifies the REST API that governs that entire operation. It covers vendor onboarding and turnover, stall leasing and license management, shared-POS order routing, seating and common-area capacity, health permits and inspections, marketing events and footfall, and the rent-settlement ledger. The system is deliberately interdependent: a failed inspection can cascade through a stall's permit, its operating posture, its live orders, and the seats those orders were holding, all within a single request. The requirements below define each entity's lifecycle, the precise arithmetic of rent and deposits, and the order in which the system validates every request.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `HallManager`, `Vendor`, `HealthInspector`, and `POSOperator`.

- A `HallManager` is the venue operator. `X-User-ID` for a `HallManager` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The `HallManager` owns food halls, stalls, vendors, leases, settlements, and marketing events.
- A `Vendor` is a stall operator. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor` entity. Ownership checks compare `X-User-ID` to the relevant vendor foreign key on the target resource: for accepting, fulfilling, or rejecting an order, the acting vendor must equal the `current_vendor_id` of the order's stall; for disputing a settlement, the acting vendor must equal the `vendor_id` of the settlement's lease. A mismatch is an `ERR_UNAUTHORIZED`.
- A `HealthInspector` issues and revokes permits and conducts inspections. `X-User-ID` for a `HealthInspector` is an opaque identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `POSOperator` runs the shared-POS terminal, placing orders and managing seating. `X-User-ID` for a `POSOperator` is likewise an opaque identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource in this system — food halls, vendors, stalls, leases, health permits, inspections, orders, seating allocations, marketing events, and settlements — carries a standard set of system-managed fields:

- `id`: a server-minted UUID with no type prefix, unique across the system.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value on creation and increments by exactly one on every mutation. It is the basis for optimistic concurrency control described in §2.8.

Whenever a rule below says a resource's state or a derived field changes, that mutation refreshes the resource's `updated_at` and increments its `version`, even when the change is triggered indirectly by a cascade rather than by a direct client request on that resource. A recomputation of a stall's `operational_posture`, `current_lease_id`, or `current_vendor_id` that actually changes the stored value is such a mutation.

### 2.5. The Logical Clock

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it, every time-dependent operation reads exactly this default; the server never falls back to real wall-clock time. A `HallManager` may advance the clock by supplying a target instant in the `to_iso8601` field; the response reports the new value as `current_utc`. The logical clock is the source of truth for an order's `placed_at`, an inspection's `conducted_at`, a permit's `issued_on`, the "today" used in deposit refunds, and any date comparison in lease terms and settlement periods.

### 2.6. Operational Posture and Compliance Gating

Every stall carries a computed compliance gate, `operational_posture`, which is one of `OPEN`, `RESTRICTED`, or `SUSPENDED`. It is never supplied by a client; the server derives it from the stall's active lease, that lease's vendor status, the stall's latest health permit, and the stall's latest conducted inspection. The posture is recomputed on any lease, vendor, permit, or inspection change that touches the stall, and it is read when an order is routed. A freshly created stall has no lease and therefore begins at `SUSPENDED`.

The posture is determined as follows. Identify the stall's lease that is currently in `ACTIVE` status (there is at most one), the stall's most recently created health permit (by `created_at`), and the stall's most recently conducted inspection (the one with the greatest `conducted_at`, ties broken by the earlier `created_at`). Then:

- If the stall has no `ACTIVE` lease, the posture is `SUSPENDED`.
- Otherwise, if the vendor on that active lease is not in `ACTIVE` status, the posture is `SUSPENDED`.
- Otherwise, if the stall has no health permit, or its latest permit is not in `ISSUED` status, the posture is `SUSPENDED`.
- Otherwise, if the latest conducted inspection exists and its `result` is `FAIL`, the posture is `SUSPENDED`.
- Otherwise, if the latest conducted inspection exists and its `result` is `CONDITIONAL`, the posture is `RESTRICTED`.
- Otherwise, the posture is `OPEN`.

Because posture is derived from four independent inputs, a change to any of them can flip it, and a flip to `SUSPENDED` can cascade further into live orders and seating, as described in §3.3 and §3.5. These cascades run synchronously within the request that triggered them.

### 2.7. Monetary Precision and the Rent Ledger

All money is stored and returned as integer cents. Wherever a calculation produces a fractional cent, the system rounds half up to the nearest whole cent. Rent is computed in a strict round-then-sum order: the prorated base component and the percentage-rent component are each rounded to a whole cent independently, and only then are the two already-rounded integers added together. The system never keeps the two components as unrounded reals and rounds their sum once.

Each lease maintains a running ledger field, `outstanding_balance_cents`, which starts at 0 and records finalized rent charged minus any rent later voided. Finalizing a settlement debits this balance by the settlement's total rent, and voiding a finalized settlement credits it back by exactly the same amount, so that a finalize followed by a void leaves the balance where it started. A lease's `security_deposit_cents` is held separately; any deposit refund computed at termination is reported on the response and is never applied to `outstanding_balance_cents`.

### 2.8. Optimistic Concurrency Control on Settlement Creation

Creating a settlement is guarded by optimistic concurrency control against the target lease. The create request must carry `expected_lease_version`, holding the `version` of the lease the client last observed. If that value does not match the lease's current `version`, the request is rejected with `ERR_STALE_LEASE_VERSION` and HTTP status 412. On a successful create the endpoint bumps the lease's `version`, so a subsequent create issued off the earlier, now-stale view of the lease will fail this check. This exists because a new provisional settlement legitimately supersedes any prior provisional settlement for the same lease and period; without the version check, a create issued from a stale view of the lease would silently discard the sales and version state an earlier create already committed. No other endpoint takes a version field.

### 2.9. Nested Resource Retrieval and Existence Validation

A handful of read endpoints reach child resources through a stall in their path — a stall's permits and a stall's inspections, for example. For any path that names a resource by its identifier, the system validates existence left to right and rejects the first identifier that does not resolve, before evaluating anything downstream. A missing resource yields the specific not-found error for that resource type: `ERR_FOOD_HALL_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_STALL_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SEATING_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`. The generic `ERR_NOT_FOUND` covers any path or foreign-key resource that has no more specific code. The same existence rule applies to foreign keys carried in a create request body — a `food_hall_id`, `stall_id`, `vendor_id`, `lease_id`, or `order_id` that does not resolve is rejected as not found.

### 2.10. Request Validation Ordering

When several checks could reject a request, the system evaluates them in a fixed priority order and returns the first failure it encounters:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers must be present and well-formed, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The acting role must be permitted for the operation, and for the ownership-scoped `Vendor` role, `X-User-ID` must own the target resource where ownership is required, else `ERR_UNAUTHORIZED` (403).
3. **Path existence.** Every resource named in the path must exist, validated left to right, else the appropriate not-found code (404).
4. **Foreign-key existence.** Every foreign key in the request body must reference an existing resource, else a not-found code (404).
5. **Well-formedness.** The body must be well-formed: required fields present, enum values legal, numeric ranges satisfied, and ordering constraints met. General violations return `ERR_INVALID_REQUEST` (422). A degenerate time interval on a seating allocation or event window — where the start is not strictly before the end — returns `ERR_INTERVAL_INVALID` (422). A lease whose `end_date` is not strictly after its `start_date`, or whose `rent_cap_cents` is below its `base_rent_cents`, returns `ERR_LEASE_TERM_INVALID` (422).
6. **Concurrency.** On settlement creation, `expected_lease_version` must match the lease's current `version`, else `ERR_STALE_LEASE_VERSION` (412).
7. **State precondition.** The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409). Domain-specific state failures use their own codes: `ERR_VENDOR_NOT_ACTIVE` when activating a lease whose vendor is not `ACTIVE`, `ERR_STALL_SUSPENDED` when routing an order to a `SUSPENDED` stall, and `ERR_SETTLEMENT_NOT_PROVISIONAL` when finalizing or disputing a settlement that is not `PROVISIONAL` or voiding a settlement that is not `FINALIZED`.
8. **Health gate.** On lease activation, the stall's latest health permit must be `ISSUED`, else `ERR_PERMIT_NOT_ISSUED` (409).
9. **Referential business rules.** On lease activation, the stall must not already carry another `ACTIVE` lease, else `ERR_STALL_ALREADY_LEASED` (409); on order placement, the stall must belong to the order's hall, else `ERR_STALL_NOT_IN_HALL` (409).
10. **Temporal windows.** An order must be placed within operating hours (else `ERR_OUTSIDE_OPERATING_HOURS`, 409); a scheduled event must respect the inter-event buffer (else `ERR_EVENT_TIME_CONFLICT`, 409); a lease term must not overlap another active lease's term on the same stall (else `ERR_LEASE_TERM_CONFLICT`, 409).
11. **Capacity.** A seating request must keep concurrent seats within capacity (else `ERR_SEATING_CAPACITY_EXCEEDED`, 409); an event's `reserved_capacity` must not exceed the hall's common-area capacity (else `ERR_COMMON_AREA_CAPACITY_EXCEEDED`, 409).

## 3. Business Logic & Workflows

### 3.1. Establishing the Venue: Food Halls, Stalls, and Vendor Onboarding

The venue itself is a food hall, created by a `HallManager` with a display `name`, a `total_seating_capacity` of at least one shared seat, a `common_area_capacity` of at least one for standing and event occupancy, and daily operating bounds. Operating bounds are given as minutes from UTC midnight: `hall_open_minutes` must be at least 0 and strictly less than `hall_close_minutes`, which may not exceed 1440. A food hall also carries `event_buffer_minutes`, the mandatory setup-and-teardown gap required between two scheduled marketing events on its common area; this is at least 0 and defaults to 60 when omitted at creation.

A stall is a physical trading spot inside a hall. Creating one requires the `food_hall_id` it sits in, a human `stall_code` label such as "A-12", a `size_sqft` footprint of at least one square foot, and its own daily hours `open_minutes` and `close_minutes`, subject to the same ordering as the hall (opening at least 0 and strictly before closing, closing no later than 1440). A stall also exposes three derived fields the client never sets directly: its `operational_posture`, described in §2.6, and mirrors of its current tenancy, `current_lease_id` and `current_vendor_id`. On creation a stall is vacant — it has no lease — so its `current_lease_id` and `current_vendor_id` are null and its posture is `SUSPENDED`.

Vendors move through an onboarding and turnover lifecycle. A `HallManager` registers a vendor applicant with its `legal_name` and `contact_email`; the new vendor starts in `APPLIED` status. Completing onboarding advances the vendor from `APPLIED` to `ACTIVE`; this is permitted only while the vendor is `APPLIED`. An `ACTIVE` vendor may be suspended, moving it to `SUSPENDED`, and a `SUSPENDED` vendor may be reinstated back to `ACTIVE` — the two states form a cycle, so a vendor can be suspended and reinstated any number of times. Suspending a vendor is a significant event with wide cascade effects, detailed in §3.5. Reinstating a vendor recomputes the `operational_posture` of every stall that vendor currently occupies, which may return those stalls to `OPEN` or `RESTRICTED`. A vendor leaving the hall for good (turnover) is modeled by terminating that vendor's leases rather than by a distinct terminal vendor state.

### 3.2. Leasing a Stall: Terms, Activation, Renewal, and Termination

A lease binds one vendor to one stall under a set of rent terms. A `HallManager` drafts a lease by supplying the `stall_id`, the `vendor_id`, a `start_date` and `end_date` (each `YYYY-MM-DD`, inclusive, with the end strictly after the start), and the commercial terms: a fixed monthly `base_rent_cents` of at least 0, a `percentage_rate` between 0 and 1 inclusive applied to sales above a threshold, a `natural_breakpoint_cents` of at least 0 above which percentage rent begins, a `rent_cap_cents` ceiling that must be at least the base rent, and a refundable `security_deposit_cents` of at least 0. A new lease begins in `DRAFT` status and also carries the system-managed `outstanding_balance_cents`, which starts at 0. A draft binds terms only; it does not yet occupy the stall.

Activating a lease moves it from `DRAFT` to `ACTIVE` and is the moment a vendor takes possession of a stall. Activation is permitted only when the lease is in `DRAFT`; it further requires that the leasing vendor is currently `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`), that the stall's latest health permit is `ISSUED` (otherwise `ERR_PERMIT_NOT_ISSUED`), that no other lease on the same stall is already `ACTIVE` (otherwise `ERR_STALL_ALREADY_LEASED`), and that no other `ACTIVE` lease on that stall has a term overlapping the interval from `start_date` to `end_date` (otherwise `ERR_LEASE_TERM_CONFLICT`). On success the system sets the stall's `current_lease_id` and `current_vendor_id` to this lease and its vendor and recomputes the stall's `operational_posture`.

An `ACTIVE` lease can be renewed in place: renewal keeps the lease `ACTIVE` (an `ACTIVE`-to-`ACTIVE` self-loop) and extends its term. The request supplies a `new_end_date`, which must be strictly later than the lease's current `end_date`; the lease's `end_date` is extended to that value. Terminating an `ACTIVE` lease moves it to the terminal `TERMINATED` status, which is permitted only while the lease is `ACTIVE`. Termination clears the stall's `current_lease_id` and `current_vendor_id`, leaving it vacant, and recomputes the stall's posture, which becomes `SUSPENDED` because the stall now has no active lease. Termination also computes a deposit refund and returns it on the response as `deposit_refund_cents`.

The refund is computed against the current logical date. If that date is on or after the lease's `end_date`, the vendor receives the full `security_deposit_cents` back — a natural, at-or-after-expiry termination forfeits nothing. Otherwise the termination is early: let the remaining days be the inclusive count of days from the current logical date through the `end_date`, and the term days be the inclusive count of days from the `start_date` through the `end_date`. The forfeited amount is the deposit multiplied by remaining days, divided by term days, rounded half up to a whole cent; the refund is the deposit minus that forfeited amount. This figure is a settlement of the deposit only and is never posted to `outstanding_balance_cents`.

### 3.3. Health Permits and Inspections

A stall trades only under a valid health permit. A `HealthInspector` creates a permit for a stall by supplying the `stall_id`, the external `permit_number` from the health authority, and an `expires_on` date; the permit begins in `PENDING` status. Issuing a permit moves it from `PENDING` to `ISSUED`, permitted only while it is `PENDING`; issuance stamps the permit's `issued_on` with the current logical date and recomputes the posture of the permit's stall. A `HealthInspector` may revoke a permit that is currently `ISSUED` or `SUSPENDED`, moving it to the terminal `REVOKED` status and recomputing the stall's posture, which falls to `SUSPENDED` because the stall no longer has a valid permit.

Inspections drive a stall's hygiene standing. A `HealthInspector` schedules an inspection with the `stall_id` and a planned `scheduled_for` datetime; it starts in `SCHEDULED` status. Conducting the inspection moves it to the terminal `CONDUCTED` status and is permitted only while it is `SCHEDULED`. At conduct time the inspector supplies a hygiene `score` between 0 and 100, the system stamps `conducted_at` from the logical clock, and it derives the `result`: `PASS` when the score is at least 85, `CONDITIONAL` when the score is at least 70 but below 85, and `FAIL` when the score is below 70.

The result branches. A `FAIL` triggers a cascade: the stall's latest `ISSUED` health permit is driven to `SUSPENDED`; that permit suspension recomputes the stall's `operational_posture` to `SUSPENDED`; that posture flip then auto-rejects the stall's live orders (those in `ROUTED` or `ACCEPTED` status), moving each to `REJECTED`; and each such rejected order releases its `RESERVED` seating allocation, moving it to `RELEASED` and freeing those seats. A `PASS` moves in the opposite direction: if the stall's latest permit is currently `SUSPENDED`, it is restored to `ISSUED` and the posture is recomputed; the permit's `SUSPENDED`-to-`ISSUED` restoration and its inspection-driven suspension together form a cycle that is driven entirely by inspection outcomes. A `CONDITIONAL` result changes no permit but recomputes the posture, which resolves to `RESTRICTED`.

### 3.4. Stall Compliance Grade

Beyond the live posture gate, a stall can be graded on its recent hygiene history through a computed read available to a `HallManager` or a `HealthInspector`, parameterized by a `method` of either `LATEST` or `WEIGHTED`. The grade is built from the stall's `CONDUCTED` inspections ordered from most to least recently conducted — by `conducted_at` descending, ties broken by `created_at` descending — keeping at most the three newest.

Under `LATEST`, the score is simply the newest conducted inspection's `score`. Under `WEIGHTED`, the score is a weighted average of the retained inspections applied newest to oldest: with a single inspection the weight is 1.0; with two inspections the weights are 0.6 and 0.4; with three the weights are 0.5, 0.3, and 0.2; the score is the sum of each weight times its inspection's `score`, rounded half up to a whole number. For an identical inspection history the two methods can yield a different score and grade. The resulting letter `grade` is `A` when the score is at least 90, otherwise `B` at 80 or above, otherwise `C` at 70 or above, otherwise `D` at 60 or above, otherwise `F`. The read returns the `stall_id`, the `method` used, the computed `score`, and the `grade`.

### 3.5. Shared-POS Ordering and Routing

Diners order through a shared POS operated by a `POSOperator`, and each order is auto-routed to a stall on placement. Placing an order supplies the `food_hall_id`, the target `stall_id`, a `gross_amount_cents` of at least one cent representing the order's gross sales value, and an `item_count` of at least one line item. The `status` `PLACED` is transient: a successful placement stamps `placed_at` from the logical clock and lands the order in `ROUTED` status in the same request.

Routing enforces three conditions. The stall must belong to the order's hall — its `food_hall_id` must equal the order's `food_hall_id` — otherwise the order is rejected with `ERR_STALL_NOT_IN_HALL`. The stall's `operational_posture` must not be `SUSPENDED`, otherwise it is rejected with `ERR_STALL_SUSPENDED`; a `RESTRICTED` or `OPEN` stall accepts orders. Finally the order must fall within operating hours: the order's placed time, taken as its minute of the UTC day, must be at or after the later of the stall's `open_minutes` and the hall's `hall_open_minutes`, and strictly before the earlier of the stall's `close_minutes` and the hall's `hall_close_minutes`; otherwise it is rejected with `ERR_OUTSIDE_OPERATING_HOURS`.

Once routed, an order is worked by the stall's vendor, and each of these actions is authorized only for the vendor whose `id` equals the stall's `current_vendor_id`. Accepting a routed order advances it from `ROUTED` to `ACCEPTED`. Fulfilling an accepted order advances it from `ACCEPTED` to `FULFILLED`, at which point its sales count toward the final settlement variant. A vendor may reject an order that is in either `ROUTED` or `ACCEPTED` status, moving it to the terminal `REJECTED` status; rejection releases any `RESERVED` seating allocation whose `order_id` points at that order, moving the allocation to `RELEASED` and returning its seats to the hall.

Suspending a vendor propagates through this same machinery. When a `HallManager` suspends an `ACTIVE` vendor, then for every stall whose `current_vendor_id` is that vendor, the stall's `operational_posture` is recomputed and falls to `SUSPENDED` because the vendor is no longer `ACTIVE`; each such flip to `SUSPENDED` auto-rejects that stall's `ROUTED` and `ACCEPTED` orders, moving them to `REJECTED`; and each rejected order releases its `RESERVED` seating allocation to `RELEASED`, freeing those seats.

### 3.6. Shared Seating and Capacity

The common seating area is a shared, capacity-limited pool managed by a `POSOperator`. A seating allocation reserves seats for a window: the request supplies the `food_hall_id`, an optional `order_id` linking the reservation to an order (omitted for walk-in holds), a `seats` count of at least one, and a half-open window from `start_time` (inclusive) to `end_time` (exclusive), where the end must be strictly after the start. A new allocation begins in `RESERVED` status and occupies its seats across the window; releasing it moves it to the terminal `RELEASED` status and frees those seats back to capacity.

Capacity is evaluated over the requested window against `total_seating_capacity`. Two windows on the same hall overlap when one starts strictly before the other ends and the other starts strictly before the first ends; two windows that merely touch — one ending exactly when the other begins — do not overlap. The concurrent seat load for a requested window is the sum of `seats` across all `RESERVED` allocations on the same hall whose windows overlap the requested window. The request is admitted only when that concurrent load plus the requested `seats` is at most `total_seating_capacity`; equality is admitted. A request that would push the total above capacity is rejected with `ERR_SEATING_CAPACITY_EXCEEDED`. A release always frees exactly the seats it held, so capacity is conserved: seats freed by a release, an order rejection, or a posture cascade become immediately available to new reservations in that window.

### 3.7. Marketing Events and the Common Area

A `HallManager` promotes footfall by staging marketing events in the hall's common area. Creating an event supplies the `food_hall_id`, an event `name`, a window from `start_time` (inclusive) to `end_time` (inclusive) with the end strictly after the start, a `reserved_capacity` of at least one occupant, and an `expected_footfall` of at least zero projecting the additional visitors the event will draw. A new event begins in `PLANNED` status.

Scheduling an event moves it from `PLANNED` to `SCHEDULED` and commits the common-area slot. It is permitted only while the event is `PLANNED`, and it enforces two constraints. The event's `reserved_capacity` must not exceed the hall's `common_area_capacity`, otherwise it is rejected with `ERR_COMMON_AREA_CAPACITY_EXCEEDED`. The event must also respect the inter-event buffer: treating each event window as a closed interval and dilating it by the hall's `event_buffer_minutes` on both sides, a candidate event conflicts with an existing `SCHEDULED` event on the same hall when the candidate's start is strictly before that event's end plus the buffer and that event's start is strictly before the candidate's end plus the buffer. A gap of exactly the buffer length between the two windows is admitted; a smaller gap is a conflict and is rejected with `ERR_EVENT_TIME_CONFLICT`.

An event may be cancelled, moving it to the terminal `CANCELLED` status. A `PLANNED` or `SCHEDULED` event can be cancelled; cancelling a `SCHEDULED` event frees its common-area slot so that it no longer blocks the buffer check for other events.

### 3.8. Rent Settlement

Rent blends a fixed base with a percentage of sales, reconciled per lease and period through a settlement. A `HallManager` creates a settlement for a `lease_id` over a period bounded by `period_start` and `period_end` (each `YYYY-MM-DD`, inclusive, with the start no later than the end), and must include `expected_lease_version` carrying the lease `version` the client last read, as required by the concurrency rule in §2.8. A new settlement begins in `PROVISIONAL` status with its rent figures computed under the provisional variant. Creating a settlement also marks any prior `PROVISIONAL` settlement for the same lease and period as `SUPERSEDED`, and it increments the lease's `version`; the superseded settlement is a system-driven transition out of `PROVISIONAL`.

The settlement's four computed money fields — `gross_sales_cents`, `base_rent_charged_cents`, `percentage_rent_cents`, and `total_rent_cents` — are derived, never client-supplied. Gross sales for the period is the sum of `gross_amount_cents` over the orders routed to the lease's stall whose `placed_at` calendar date falls within `period_start` through `period_end` inclusive and whose `status` is in the variant's counted set. The variant differs by lifecycle stage: at creation, the provisional variant counts orders in either `ACCEPTED` or `FULFILLED` status, capturing in-flight accepted sales; at finalize, the final variant counts only `FULFILLED` orders, so accepted-but-unfulfilled and rejected sales drop out, which changes gross sales and therefore the percentage rent and total.

The base component, `base_rent_charged_cents`, is prorated by the lease's active days in the period. Let period days be the inclusive count of days from `period_start` through `period_end`. Let active days be the inclusive count of days in the overlap between the settlement period and the lease term — that is, from the later of `period_start` and the lease's `start_date` through the earlier of `period_end` and the lease's `end_date` — and zero if that overlap is empty. The base charged is `base_rent_cents` multiplied by active days, divided by period days, rounded half up to a whole cent. The percentage component, `percentage_rent_cents`, is `percentage_rate` multiplied by the greater of zero and (gross sales minus `natural_breakpoint_cents`), rounded half up to a whole cent — percentage rent applies only to sales strictly above the breakpoint. The `total_rent_cents` is the lesser of `rent_cap_cents` and the sum of the base and percentage components. The evaluation order is pinned: compute gross sales, then round the base independently, then round the percentage rent independently, then add the two already-rounded integers, then clamp with the cap.

Finalizing a settlement moves it from `PROVISIONAL` to the terminal `FINALIZED` status and is permitted only while it is `PROVISIONAL`. Finalize recomputes `gross_sales_cents`, `percentage_rent_cents`, and `total_rent_cents` under the final variant and then debits the lease ledger by adding the settlement's `total_rent_cents` to the lease's `outstanding_balance_cents`, which increments the lease's `version`. A terminated lease may still be settled and finalized; there is no state gate on the lease at finalize time.

The lease's vendor may contest a settlement: disputing moves a `PROVISIONAL` settlement to `DISPUTED`, permitted only while it is `PROVISIONAL` and only for the vendor whose `id` equals the settlement's lease's `vendor_id`. A `HallManager` resolves a dispute, returning the settlement from `DISPUTED` back to `PROVISIONAL`; the `PROVISIONAL`-to-`DISPUTED`-to-`PROVISIONAL` path forms a cycle. Finally, a `FINALIZED` settlement may be voided, moving it to the terminal `VOIDED` status; voiding is permitted only while the settlement is `FINALIZED`, and it credits the lease ledger by subtracting the settlement's `total_rent_cents` from the lease's `outstanding_balance_cents` (incrementing the lease's `version`), exactly reversing the debit that finalize applied.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, the ledger movements, and the logical-clock setter — return `200 OK`. Request bodies, response bodies, and side effects are not restated here; they are governed by the narratives in §3 and the principles in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | HallManager |
| POST | `/food-halls` | Create a food hall venue | HallManager |
| GET | `/food-halls/{id}` | Fetch a food hall | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/vendors` | Register a vendor applicant | HallManager |
| GET | `/vendors/{id}` | Fetch a vendor | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/vendors/{id}/activate` | Activate an applied vendor | HallManager |
| POST | `/vendors/{id}/suspend` | Suspend an active vendor (cascades posture, orders, seating) | HallManager |
| POST | `/vendors/{id}/reinstate` | Reinstate a suspended vendor | HallManager |
| POST | `/stalls` | Create a stall in a hall | HallManager |
| GET | `/stalls/{id}` | Fetch a stall (includes computed posture) | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/stalls` | List stalls, optionally filtered by hall and/or posture | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/stalls/{id}/permits` | List a stall's health permits | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/stalls/{id}/inspections` | List a stall's inspections | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/stalls/{id}/compliance-grade` | Computed compliance grade under LATEST or WEIGHTED | HallManager, HealthInspector |
| POST | `/leases` | Create a draft lease | HallManager |
| GET | `/leases/{id}` | Fetch a lease | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/leases` | List leases filtered by stall, vendor, and/or status | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/leases/{id}/activate` | Activate a draft lease | HallManager |
| POST | `/leases/{id}/renew` | Renew an active lease (extend end date) | HallManager |
| POST | `/leases/{id}/terminate` | Terminate an active lease; returns deposit refund | HallManager |
| POST | `/permits` | Create a pending health permit | HealthInspector |
| GET | `/permits/{id}` | Fetch a health permit | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/permits/{id}/issue` | Issue a pending permit | HealthInspector |
| POST | `/permits/{id}/revoke` | Revoke an issued or suspended permit | HealthInspector |
| POST | `/inspections` | Schedule an inspection for a stall | HealthInspector |
| GET | `/inspections/{id}` | Fetch an inspection | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/inspections/{id}/conduct` | Conduct an inspection; sets result and cascades | HealthInspector |
| POST | `/orders` | Place and auto-route a shared-POS order | POSOperator |
| GET | `/orders/{id}` | Fetch an order | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/orders` | List orders filtered by stall, hall, and/or status | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/orders/{id}/accept` | Accept a routed order | Vendor |
| POST | `/orders/{id}/fulfill` | Fulfill an accepted order | Vendor |
| POST | `/orders/{id}/reject` | Reject a routed or accepted order; releases seating | Vendor |
| POST | `/seating-allocations` | Reserve shared seats for a window | POSOperator |
| GET | `/seating-allocations/{id}` | Fetch a seating allocation | HallManager, POSOperator |
| GET | `/seating-allocations` | List seating allocations filtered by hall and/or order | HallManager, POSOperator |
| POST | `/seating-allocations/{id}/release` | Release a reservation; frees seats | POSOperator |
| POST | `/marketing-events` | Create a planned common-area event | HallManager |
| GET | `/marketing-events/{id}` | Fetch a marketing event | HallManager, Vendor, HealthInspector, POSOperator |
| GET | `/marketing-events` | List marketing events filtered by hall | HallManager, Vendor, HealthInspector, POSOperator |
| POST | `/marketing-events/{id}/schedule` | Schedule a planned event (capacity and buffer) | HallManager |
| POST | `/marketing-events/{id}/cancel` | Cancel a planned or scheduled event | HallManager |
| POST | `/settlements` | Create a provisional settlement (requires OCC) | HallManager |
| GET | `/settlements/{id}` | Fetch a settlement | HallManager, Vendor |
| GET | `/settlements` | List settlements filtered by lease | HallManager, Vendor |
| POST | `/settlements/{id}/finalize` | Finalize a settlement; debits the lease ledger | HallManager |
| POST | `/settlements/{id}/dispute` | Dispute a provisional settlement | Vendor |
| POST | `/settlements/{id}/resolve-dispute` | Resolve a disputed settlement | HallManager |
| POST | `/settlements/{id}/void` | Void a finalized settlement; credits the lease ledger | HallManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FOOD_HALL_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_STALL_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SEATING_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INTERVAL_INVALID` | 422 |
| `ERR_LEASE_TERM_INVALID` | 422 |
| `ERR_STALE_LEASE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VENDOR_NOT_ACTIVE` | 409 |
| `ERR_STALL_SUSPENDED` | 409 |
| `ERR_SETTLEMENT_NOT_PROVISIONAL` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_STALL_ALREADY_LEASED` | 409 |
| `ERR_STALL_NOT_IN_HALL` | 409 |
| `ERR_OUTSIDE_OPERATING_HOURS` | 409 |
| `ERR_EVENT_TIME_CONFLICT` | 409 |
| `ERR_LEASE_TERM_CONFLICT` | 409 |
| `ERR_SEATING_CAPACITY_EXCEEDED` | 409 |
| `ERR_COMMON_AREA_CAPACITY_EXCEEDED` | 409 |
