# Carpool & Vanpool Matching API — Product Requirements Document

## 1. Introduction

Commuters who share rides save money and unlock high-occupancy-vehicle (HOV) lanes, and the employers who sponsor them can offset cost through pre-tax commuter benefits and subsidy budgets. This document specifies the backend API for a platform that ties those incentives together: it lets driving members form recurring carpools and vanpools, lets riders discover and join a pool that fits their corridor and schedule, books finite seats on individual trips, and settles the per-seat cost-share once a trip actually runs.

The platform is, at heart, a seat-allocation and pricing engine operating under tight financial controls. Every trip exposes a fixed number of seats that are reserved, committed, and released as riders book and cancel; every reservation carries a provisional cost-share at booking time and a finalized cost-share at completion, and the gap between the two is where occupancy discounts, HOV subsidies, and employer matches are reconciled. Layered on top are the trust and safety mechanics — a reliability score that penalizes no-shows and late cancellations, a guaranteed-ride-home (GRH) safety net with per-event and annual caps, and an employer subsidy ledger that must never be overdrawn.

This specification is written for the engineers who will implement the service. It describes the entities and their lifecycles, the precise arithmetic of cost-share and subsidy, the concurrency guarantees that keep the last seat from being double-sold, and the validation order that determines which error a malformed request receives. Where a rule affects more than one entity, the cascade is described in full so that a single operation's side effects are unambiguous.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the liveness probe must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four operational roles plus an anonymous caller: `PlatformOps`, `ProgramAdmin`, `Driver`, and `Rider`. When a role is present and well-formed but is not permitted to invoke the requested operation — or is an ownership-scoped role acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

`PlatformOps` is the operational superuser: it provisions programs and members, runs the simulation clock and the periodic batch, and may drive any business state transition for support purposes. When `X-User-Role` is `PlatformOps`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `ProgramAdmin` administers employer programs: it owns the program lifecycle, registers members under a program, and adjudicates GRH claims. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

`Driver` and `Rider` are both entity-backed by `Member`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references that driving member — a `Vehicle` via `owner_member_id`, a `Pool` via `driver_member_id`, and the trips and reservations beneath those pools — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references the riding member — a `MatchRequest`, `Membership`, `Reservation`, or `GuaranteedRideHome` via its `rider_member_id` — compare that field to `X-User-ID`. A `Driver` creating a pool must therefore supply a `driver_member_id` equal to `X-User-ID`, and a `Rider` reserving a seat must supply a `rider_member_id` equal to `X-User-ID`; a mismatch is an ownership failure surfaced as `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless explicitly stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted. The `updated_at` field carries the same format and is refreshed on every mutation. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation; it is the basis for optimistic concurrency control (§2.6). All of `EmployerProgram`, `Member`, `Vehicle`, `Pool`, `MatchRequest`, `Membership`, `Trip`, `Reservation`, and `GuaranteedRideHome` carry the full set: `id`, `created_at`, `updated_at`, and `version`.

Two resources are append-only audit records and are immutable after creation: a `SubsidyLedgerEntry` and a `ReliabilityEvent` carry only `id` and `created_at`. Neither has an `updated_at` field and neither has a `version` field — once written, they are never modified.

### 2.5. Reconciliation, Cascades, and Derived Fields

A great many fields in this system are derived: they are never written directly by a client but are recomputed from the rows they summarize. When any operation changes a row that feeds a derived field, the system recomputes that field synchronously, within the same request, before returning. There is no eventual consistency and no background settling: every cascade described in §3 completes before the triggering request responds.

When a parent resource transitions in a way that invalidates its children, the propagation runs immediately and each affected child runs its own side effects in turn. Suspending or closing a pool, for example, cancels its future scheduled trips, and each trip cancellation in turn cancels its reservations and reverses their money — a multi-level cascade that finishes inside the one request. Every resource the cascade touches has its `updated_at` refreshed and, where it carries a `version`, its `version` incremented by one. A derived-field recomputation that lands on a versioned resource is itself a mutation: recomputing `seats_reserved` on a `Trip` advances `Trip.version`, and recomputing `committed_seat_count` on a `Pool` advances `Pool.version`.

### 2.6. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency on the parent they consume capacity from; no other endpoint takes a version field.

A reservation create must carry `expected_trip_version` as a non-optional field whose value is the client's last observed `version` of the target `Trip`. If that value does not equal the trip's current `version` — for instance because another writer has already created a reservation that consumed the remaining seat and advanced `Trip.version` through the `seats_reserved` recompute — the create is rejected with `ERR_STALE_TRIP_VERSION` at HTTP 412, so a client can never book against a seat-availability view it has not observed.

A membership create must carry `expected_pool_version` as a non-optional field whose value is the client's last observed `version` of the target `Pool`. If that value does not equal the pool's current `version` — for instance because another writer has already committed the last recurring seat and advanced `Pool.version` through the `committed_seat_count` recompute — the create is rejected with `ERR_STALE_POOL_VERSION` at HTTP 412, so a client can never join against a capacity view it has not observed.

### 2.7. Money, Precision, and Rounding

All monetary amounts are stored and exchanged as integer cents; the system never carries fractional cents. The two percentage configuration fields — `hov_discount_pct` and `employer_match_pct` — are fractions in the inclusive range from 0.0 to 1.0 and preserve their input precision. Where a calculation multiplies cents by a fraction or by a distance, the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly at the half rounds up). The reliability score is the one non-cent quantity: it is carried to one decimal place, also round-half-up. The precise order in which each formula rounds — which factors are rounded before others are applied — is pinned per calculation in §3 and must be followed exactly, because rounding in the wrong order produces off-by-one-cent divergences that the test suite checks.

### 2.8. Validation Order and Request Pipeline

When a request could fail more than one check, the checks are evaluated in a fixed priority so that the returned `error_id` is deterministic. Authentication comes first: a missing or malformed header pair yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation, or an ownership-scoped role acting on a resource it does not own, yields `ERR_FORBIDDEN`. Existence is third: every path-referenced resource and every foreign-key reference in the body must resolve, validated left to right, or the request fails with `ERR_NOT_FOUND`. Request well-formedness is fourth: required fields must be present, enum values must be members of their set, and numeric ranges must hold (for example `latest_departure_min` must be at least `earliest_departure_min`, and `seat_count` must be at least 1), failing which the request is rejected with `ERR_INVALID_REQUEST`. Fifth comes the optimistic-concurrency check of §2.6 (`ERR_STALE_TRIP_VERSION` on reservation create, `ERR_STALE_POOL_VERSION` on membership create). Sixth, the target resource's own state must permit the requested transition, or the request fails with `ERR_INVALID_STATE`. Seventh, any cross-entity precondition — a parent that must itself be in a particular state — is checked and, if unmet, surfaced as `ERR_DEPENDENCY_NOT_READY`. The remaining business rules described throughout §3 (reliability gate, scheduling overlaps, seat and capacity limits, GRH caps, wallet funding) are evaluated after these structural checks.

### 2.9. Nested Path Validation

Endpoint paths are flat — each resource is addressed by its own collection and `id`, with no nested ownership chains in the URL. Where a path carries an `id`, that resource must exist or the request fails with `ERR_NOT_FOUND` before any body validation runs. Where a body carries foreign-key references, those are resolved left to right in declaration order; the first reference that does not resolve produces `ERR_NOT_FOUND`. List endpoints that accept a filter (for example a `pool_id`, `rider_member_id`, `member_id`, `reservation_id`, `employer_program_id`, `driver_member_id`, `vehicle_id`, `matched_pool_id`, or `trip_id` filter) return only the rows whose corresponding foreign key matches, paginated per §2.3.

### 2.10. The Simulation Clock and Periodic Batch

Because cost caps, GRH allowances, and request expiry are time-bucketed, the platform reads "now" from a controllable logical clock rather than the wall clock. A `PlatformOps` operator can set the clock to an absolute instant by supplying `now_iso8601`. The clock month and clock year derived from this instant define the windows over which `month_benefit_used_cents`, `grh_year_used_cents`, and `grh_year_event_count` accumulate; when the clock crosses into a new month, a member's monthly benefit usage resets, and when it crosses into a new year, the annual GRH counters reset. A `PlatformOps` operator can also run the periodic batch, which expires stale match requests as described in §3.

## 3. Business Logic & Workflows

### 3.1. Employer Programs and the Subsidy Budget

Everything that moves money is anchored to an **employer program**. A `ProgramAdmin` (or `PlatformOps`) creates one by supplying the sponsoring `employer_name`, the HOV subsidy fraction `hov_discount_pct`, the employer match fraction `employer_match_pct`, the per-member monthly pre-tax cap `monthly_benefit_cap_cents`, the GRH controls `grh_annual_cap_cents` and `grh_per_event_cap_cents`, and the overall `subsidy_budget_cents`. The optional `grh_max_events_per_year` defaults to 4 approved GRH events per member per calendar year when omitted. A new program is born `ACTIVE` with `subsidy_consumed_cents` at 0; that consumed figure is derived as the signed sum of every `SubsidyLedgerEntry.amount_cents` recorded against the program, so it rises with each debit and falls with each credit.

A program's `status` is a two-state gate: `ACTIVE` or `FROZEN`. Freezing is permitted only when the program is currently `ACTIVE`, and unfreezing only when it is currently `FROZEN`; either transition increments the program's `version` by one. While a program is `FROZEN`, no new subsidy may be granted: any subsidy that would otherwise be computed during a trip completion collapses to zero (no debit is appended), and an attempt to approve a GRH claim against a frozen program is blocked at the cross-entity gate with `ERR_DEPENDENCY_NOT_READY`. The complete ledger of a program — every `SubsidyLedgerEntry` whose `employer_program_id` points at it — is retrievable as a list for `ProgramAdmin` and `PlatformOps`.

### 3.2. Members, Vehicles, and Wallets

A `ProgramAdmin` or `PlatformOps` registers a **member** under a program by supplying the `employer_program_id`, the member's `full_name`, and their corridor zones `home_zone` and `work_zone`. The `can_drive` flag defaults to false and marks whether the member may own pools and drive trips; `wallet_balance_cents` is the member's prepaid balance and defaults to 0. A freshly registered member starts with `reliability_score` at 100.0 and every derived counter at zero: `completed_trip_count`, `no_show_count`, `month_benefit_used_cents`, `grh_year_used_cents`, and `grh_year_event_count`. The first three of those counters are themselves derived — `completed_trip_count` is the number of this member's reservations whose `reservation_status` is `COMPLETED`, and `no_show_count` is the number whose `reservation_status` is `NO_SHOW`. An operator may top up or debit a member's wallet through an adjustment that adds `amount_cents` to `wallet_balance_cents`, with the floor that the wallet may never go below zero.

A driving member registers a **vehicle** by supplying its `owner_member_id`, a `plate`, and a `seat_capacity` (the number of passenger seats excluding the driver, at least 1). The `hov_eligible` flag defaults to true and records whether the vehicle is registered for HOV-lane use. A member's reliability and wallet are read back through the member profile, and the persisted `reliability_score` can be fetched directly; supplying the `mode` query value `provisional` returns the what-if variant described in §3.8, while `confirmed` (the default) returns the stored score.

### 3.3. Forming a Pool and Joining It

A `Driver` (or `PlatformOps`) creates a **pool** — a recurring shared route — by supplying the subsidizing `employer_program_id`, the operating `driver_member_id`, the `vehicle_id`, the `kind` (either `CARPOOL` or `VANPOOL`), the `origin_zone` and `dest_zone` corridor codes, the service `departure_days` (a subset of the seven weekday codes), the fixed `base_cost_cents` shared per trip, and the marginal `per_mile_cents`. At creation the pool's `seat_capacity` is copied from the linked vehicle's `seat_capacity`, `committed_seat_count` starts at 0, and the pool enters the `FORMING` state. The driver supplied on the pool must be a member whose `can_drive` is true and must own the referenced vehicle; otherwise creation is rejected with `ERR_VALIDATION_DRIVER_REQUIRED`. The `committed_seat_count` is derived as the sum of `recurring_seats` across this pool's memberships whose `status` is `ACTIVE`.

A pool's lifecycle is cyclic between operation and pause. Activating a `FORMING` pool requires that at least one `ACTIVE` membership exists (so `committed_seat_count` is at least 1), that the linked vehicle exists, and that the owning program is `ACTIVE`; the pool moves to `ACTIVE` and its `version` increments. An `ACTIVE` pool may be suspended by its `Driver`, by a `ProgramAdmin`, or by `PlatformOps`: it moves to `SUSPENDED`, every one of its `SCHEDULED` trips whose `departure_at` is in the future is cancelled (each such trip cancellation running its own reservation cascade described in §3.5), and the pool's `version` increments. A `SUSPENDED` pool may be reactivated back to `ACTIVE` provided the owning program is `ACTIVE`; no past trips are restored, and the `version` increments. A pool reaches the terminal `CLOSED` state by close, permitted from `ACTIVE` only when no trip of the pool is in `BOARDING` or `IN_TRANSIT`, and permitted unconditionally from `SUSPENDED`; closing ends every `ACTIVE` membership of the pool (each moving to `ENDED`), cancels every `SCHEDULED` future trip, and increments the pool's `version`.

Riders join a pool as recurring members. A `Rider` (or `PlatformOps`) creates a **membership** by supplying the `pool_id`, the `rider_member_id` (equal to `X-User-ID` for a rider acting on their own behalf), the OCC guard `expected_pool_version`, and an optional `recurring_seats` that defaults to 1 and must be at least 1. The membership is born `ACTIVE`, the pool's `committed_seat_count` is recomputed (advancing `Pool.version` per §2.5), and the membership create is subject to the stale-pool-version rejection of §2.6. A rider may not hold two live memberships on the same pool: a create that would duplicate an existing `ACTIVE` membership for that rider on that pool is rejected with `ERR_MEMBERSHIP_DUPLICATE`. Joining is also bounded by capacity — the recurring seats requested plus the pool's existing `committed_seat_count` must not exceed the pool's `seat_capacity`, or the create is rejected with `ERR_POOL_CAPACITY_EXCEEDED`. A membership can later be ended (by the joining rider, the pool's driver, or `PlatformOps`), moving its `status` to `ENDED` and recomputing the pool's `committed_seat_count`.

### 3.4. Matching a Rider to a Pool

A `Rider` (or `PlatformOps`) opens a **match request** by supplying the `rider_member_id`, the desired `origin_zone` and `dest_zone`, the `needed_days` they must travel, and the acceptable departure window expressed as minutes after local midnight: `earliest_departure_min` and `latest_departure_min`, each at least 0 and below 1440, with the later bound at least the earlier. A new request is `OPEN`, with `matched_pool_id` and `match_score` unset.

Running the matcher advances an `OPEN` request to `MATCHED` by selecting the single best eligible pool. A candidate pool qualifies only if **all** of the following hold: the pool's `status` is `ACTIVE`; the pool's `employer_program_id` equals the requesting member's `employer_program_id`; the pool's `origin_zone` equals the request's `origin_zone` and the pool's `dest_zone` equals the request's `dest_zone`; the set of the request's `needed_days` is a subset of the pool's `departure_days`; the pool's `committed_seat_count` is strictly less than its `seat_capacity` (a recurring seat is free); and the pool's `id` is not in this request's exclusion set of previously rejected pools. Each qualifying candidate is scored as ten times the number of needed days, plus one times the seat room (the pool's `seat_capacity` minus its `committed_seat_count`), plus five hundredths times the driving member's `reliability_score`, with that weighted sum rounded half-up to two decimal places. The matcher picks the highest score; ties are broken first by the higher driver `reliability_score` and then by the earliest pool `created_at` — never by pool `id`. On selection, the request's `matched_pool_id` is set to the chosen pool, its `match_score` is set to that pool's score, and the request moves to `MATCHED`. If no candidate qualifies, the request stays `OPEN` and the matcher returns `ERR_NO_MATCH_FOUND`.

From `MATCHED`, the rider has three moves. Rejecting clears `matched_pool_id` and `match_score`, returns the request to `OPEN`, and records the rejected pool in the exclusion set so a later match never re-selects it. Confirming requires that the request is `MATCHED`, that the matched pool's `status` is `ACTIVE`, and that the matched pool's `committed_seat_count` plus one does not exceed its `seat_capacity`; it creates an `ACTIVE` membership for the rider on the matched pool with `recurring_seats` of 1, recomputes the matched pool's `committed_seat_count` (adding the one new seat), and moves the request to the terminal `CONFIRMED` state. The cross-entity gate on confirm — the matched pool not being `ACTIVE` — surfaces as `ERR_DEPENDENCY_NOT_READY`, and a confirm that would breach the pool's `seat_capacity` is rejected with `ERR_POOL_CAPACITY_EXCEEDED`. Cancelling a request from either `OPEN` or `MATCHED` moves it to the terminal `CANCELLED` state. Finally, the periodic batch run by `PlatformOps` sweeps every still-`OPEN` request whose `created_at` is more than fourteen days before the current clock and moves it to the terminal `EXPIRED` state.

### 3.5. Scheduling Trips and the Cancellation Cascade

A `Driver` (or `PlatformOps`) schedules a **trip** instance against a pool by supplying the `pool_id`, the `departure_at` timestamp, the planned `duration_min` (at least 1 minute), the one-way `distance_miles` (greater than 0), and an optional `hov_lane_used` flag. A new trip is `SCHEDULED`, its `seats_reserved` starts at 0, and its `hov_lane_used` defaults at scheduling time to the vehicle's `hov_eligible` value. The trip's `total_cost_cents` is computed at scheduling as the pool's `base_cost_cents` plus the per-mile product — the pool's `per_mile_cents` multiplied by the trip's `distance_miles`, that single product rounded half-up to the nearest whole cent before the base is added. A new trip may not collide with an existing one on the same pool: its travel window, the half-open interval from `departure_at` up to but not including `departure_at` plus `duration_min`, must not overlap the window of any non-`CANCELLED` trip of that pool, with no buffer applied; an overlap is rejected with `ERR_TRIP_WINDOW_OVERLAP`. The derived `seats_reserved` is the sum of `seat_count` over this trip's reservations whose `reservation_status` is `RESERVED`, `CHECKED_IN`, or `COMPLETED`.

The trip then runs a linear lifecycle. Opening boarding moves a trip from `SCHEDULED` to `BOARDING` and requires the owning pool to be `ACTIVE` — a pool that is not `ACTIVE` blocks the operation with `ERR_DEPENDENCY_NOT_READY`. Departing moves a trip from `BOARDING` to `IN_TRANSIT`; as a side effect, every reservation still in `RESERVED` at that moment is cascaded to `NO_SHOW`, and each such no-show runs the no-show side effects below. Completing moves a trip from `IN_TRANSIT` to `COMPLETED`; this is the settlement event detailed in §3.6.

Cancelling a trip is permitted from `SCHEDULED` (by a `Driver`, `ProgramAdmin`, `PlatformOps`, or the system as part of a pool cascade) and from `BOARDING` (by a `Driver`, `ProgramAdmin`, or `PlatformOps`). Cancelling from `SCHEDULED` cascades every `RESERVED` reservation to `CANCELLED`; cancelling from `BOARDING` cascades every `RESERVED` or `CHECKED_IN` reservation to `CANCELLED`. Each cascaded reservation cancellation is a system-driven cancel that carries no reliability penalty (the fault is the driver's or the system's): if the reservation's `payment_status` was `CHARGED`, the charged amount is refunded to the rider's wallet; if a subsidy debit had been recorded for that reservation, a compensating `SubsidyLedgerEntry` credit with reason `TRIP_CANCELLED` is appended and the program's `subsidy_consumed_cents` is recomputed; and the trip's `seats_reserved` is recomputed as seats are released.

### 3.6. Reserving a Seat, Checking In, and No-Shows

A `Rider` (or `PlatformOps`) reserves seats on a trip by supplying the `trip_id`, the `rider_member_id`, the OCC guard `expected_trip_version`, an optional `seat_count` (default 1, at least 1), and an optional `pay_now` flag choosing whether to charge immediately. A reservation is born with `reservation_status` of `RESERVED` and `payment_status` of `PENDING` — the two axes evolve independently, one governing the seat lifecycle and the other the money lifecycle. On create, the system computes `estimate_cost_share_cents` and `estimate_subsidy_cents` for the reservation (§3.7), recomputes the trip's `seats_reserved`, and increments the trip's `version` by one. When `pay_now` is set, the rider's wallet is charged the `estimate_cost_share_cents` and `payment_status` becomes `CHARGED`; the wallet must be able to cover that charge, or the reservation is rejected with `ERR_INSUFFICIENT_WALLET`. The `final_cost_share_cents`, `final_subsidy_cents`, and `net_charge_cents` fields remain 0 until the trip completes.

Reserving carries several guards beyond the OCC check of §2.6. The reserving trip must be `SCHEDULED` and its owning pool `ACTIVE`, a cross-entity gate whose failure is `ERR_DEPENDENCY_NOT_READY`. A rider whose stored (confirmed) `reliability_score` is below 70.0 may not create a new reservation and is turned away with `ERR_RELIABILITY_TOO_LOW`. A reservation must not double-book the rider: the new reservation may not put the rider on two trips whose travel windows, each expanded on both sides by the rider buffer of fifteen minutes (a closed interval), overlap — a clash is rejected with `ERR_RIDER_DOUBLE_BOOKED`. And the seats must fit: the trip's current `seats_reserved` plus the requested `seat_count` must not exceed the seat capacity of the trip's pool, or the reservation is rejected with `ERR_SEATS_EXHAUSTED`.

A `Driver` (or `PlatformOps`) checks a rider in while the owning trip is `BOARDING`, moving the reservation's `reservation_status` from `RESERVED` to `CHECKED_IN`. A no-show — produced either by the depart cascade or by an explicit driver action against a `RESERVED` reservation whose trip is `BOARDING` or `IN_TRANSIT` — moves `reservation_status` to `NO_SHOW`; if `payment_status` was `CHARGED`, the `estimate_cost_share_cents` is retained as a no-show penalty and `payment_status` becomes `SETTLED`, otherwise `payment_status` is left unchanged. Each no-show recomputes the member's `no_show_count`, appends a `ReliabilityEvent` of type `NO_SHOW`, recomputes the member's `reliability_score`, and recomputes the trip's `seats_reserved` as the seat is released.

A rider, the trip's driver, or `PlatformOps` may cancel a `RESERVED` reservation while the owning trip is `SCHEDULED` or `BOARDING`. The reservation moves to `CANCELLED`; if `payment_status` was `CHARGED`, the `estimate_cost_share_cents` is refunded to the rider wallet and `payment_status` becomes `REFUNDED`, otherwise `payment_status` becomes `REFUNDED` with no money moved. If a subsidy debit had previously been recorded for this reservation, a `SubsidyLedgerEntry` credit of the negative `estimate_subsidy_cents` with reason `RESERVATION_CANCELLED` is appended, and both the program's `subsidy_consumed_cents` and the member's `month_benefit_used_cents` are recomputed. The trip's `seats_reserved` is recomputed as the seat is released. Crucially, a rider-initiated cancel that happens while the trip is already `BOARDING` is a late cancellation: it appends a `ReliabilityEvent` of type `LATE_CANCEL` and recomputes the rider's `reliability_score`. A cancel while the trip is still `SCHEDULED` carries no such penalty.

### 3.7. Cost-Share and Subsidy Arithmetic

The per-trip cost is shared across the riders aboard, with a discount for fuller pools, and then partially subsidized by HOV and employer-match layers. This arithmetic runs twice for every reservation: an **estimate** at reservation create (populating `estimate_cost_share_cents` and `estimate_subsidy_cents`) and a **final** settlement at trip completion (populating `final_cost_share_cents` and `final_subsidy_cents`).

Consider the cost-share first. Let the trip total be the trip's `total_cost_cents`, and let N be the number of cost-sharing seats in the inclusion set. The occupancy tier factor depends on N: when N is at least 4 the factor is 0.80 (the full-vanpool discount), when N is exactly 3 the factor is 0.90, and when N is 2 or fewer the factor is 1.00. The driver's seat is free and never counted. The per-seat raw amount is the trip total multiplied by the tier factor, divided by N — kept as a real number, not yet rounded. This reservation's share is the per-seat raw amount multiplied by this reservation's `seat_count`, rounded half-up to whole cents exactly once. The evaluation order is pinned: derive the tier factor from N first, then divide by N, then multiply by `seat_count`, and only then round once — the per-seat raw amount is never rounded before being multiplied by `seat_count`. The two variants differ only in what fills the inclusion set. For the estimate, N is forward-looking: the sum of `seat_count` over the trip's reservations that are `RESERVED` or `CHECKED_IN`, including the reservation being created. For the final, N is the actuals: the sum of `seat_count` over only those reservations whose `reservation_status` is `COMPLETED` — riders who actually rode. Because no-shows and cancellations shrink the final inclusion set, the per-seat share rises and the final cost-share can diverge upward from the estimate.

The subsidy is a layered waterfall applied to a single rider's cost-share. Let cs be that rider's cost-share (estimate or final, matching the variant), let hov be the trip's `hov_lane_used`, and let the owning pool's program supply `hov_discount_pct` and `employer_match_pct`. The HOV layer is, when hov is true, the cost-share multiplied by `hov_discount_pct` and rounded half-up to whole cents; when hov is false the HOV layer is 0. The employer-match layer is the cost-share minus the HOV layer, multiplied by `employer_match_pct`, rounded half-up to whole cents. Each layer is rounded to cents on its own before the two are summed — the system never multiplies the cost-share by the sum of the two fractions and rounds once. The raw subsidy is the HOV layer plus the match layer. That raw subsidy is then capped by the monthly waterfall: the applied subsidy is the smallest of the raw subsidy, the member's remaining monthly benefit (the program's `monthly_benefit_cap_cents` minus the member's `month_benefit_used_cents`, floored at 0), and the cost-share itself. Finally a program-budget guard applies: if the owning program's `status` is `FROZEN`, or if the program's `subsidy_consumed_cents` plus the applied subsidy would exceed the program's `subsidy_budget_cents`, the subsidy collapses to 0 and no debit is appended. The estimate variant reads `month_benefit_used_cents` before any final debit and uses the scheduling-time `hov_lane_used`; the final variant uses `final_cost_share_cents` and the `hov_lane_used` value finalized at completion, so if the HOV lane was ultimately not used the HOV layer collapses to 0 and the final subsidy diverges from the estimate.

Trip completion is where the final figures land. Completing an `IN_TRANSIT` trip first finalizes `hov_lane_used` from the request body (the `hov_lane_used` field is required on completion) and recomputes the trip's `total_cost_cents`. Then, for each `CHECKED_IN` reservation, the reservation moves to `COMPLETED`, its `final_cost_share_cents` is recomputed under the final cost-share variant, its `final_subsidy_cents` is recomputed under the final subsidy variant, its `net_charge_cents` is set to the final cost-share minus the final subsidy floored at 0, that net charge is taken from the rider's wallet, and its `payment_status` moves from `PENDING` or `CHARGED` to `SETTLED`. For each finalized reservation a `SubsidyLedgerEntry` debit equal to the `final_subsidy_cents` with reason `RESERVATION_FINALIZED` is appended, after which the program's `subsidy_consumed_cents` and the member's `month_benefit_used_cents` are recomputed. For each completed reservation a `ReliabilityEvent` of type `COMPLETION` is appended and the member's `completed_trip_count` and `reliability_score` are recomputed. Finally the driving member's `wallet_balance_cents` is credited by the sum of `final_cost_share_cents` across the completed reservations.

### 3.8. Reliability Scoring

Each member carries a `reliability_score` in the range from 0 to 100, recomputed every time a `ReliabilityEvent` is appended for that member. The score is recency-agnostic: it starts from a base of 100 and adds a fixed weight per event by type. A `COMPLETION` event contributes `weight_delta` of +2.0, a `NO_SHOW` event contributes −15.0, a `LATE_CANCEL` event contributes −6.0, and a `GRH_OVERUSE` event contributes −4.0. The raw score is 100 plus the sum of every event's `weight_delta`; that raw value is clamped to the range from 0.0 to 100.0 after all deltas are summed, and only then rounded half-up to one decimal place. Each `ReliabilityEvent` records the `member_id` it affects, optionally the `reservation_id` that produced it, its `event_type`, and its `weight_delta`; events are retrievable individually and as a list filterable by `member_id` or `reservation_id`.

The persisted score — the one consulted by the reservation reliability gate of §3.6 — is the confirmed variant, counting only realized events. A provisional what-if variant is available on demand: it takes the persisted events and additionally treats each of the member's currently `RESERVED` (not yet ridden) reservations as an expected `COMPLETION` worth +2.0, summing those pending bonuses into the raw before the same clamp and one-decimal rounding. The provisional variant is never persisted and diverges upward from the confirmed score while pending reservations exist; it is surfaced only through the reliability read when the `mode` query value is `provisional`.

### 3.9. Guaranteed Ride Home

The guaranteed-ride-home safety net reimburses a member who had to pay out of pocket for an alternate ride. A `Rider` (or `PlatformOps`) files a **GRH claim** by supplying the `rider_member_id`, the reimbursing `employer_program_id`, the out-of-pocket `claimed_fare_cents`, a `reason_code` (one of `ILLNESS`, `OVERTIME`, `EMERGENCY`, or `DRIVER_CANCEL`), and optionally the `trip_id` of the disrupted trip. A new claim is `REQUESTED`, with `reimbursed_cents` at 0.

Adjudication is a branch. A `ProgramAdmin` or `PlatformOps` approves a `REQUESTED` claim only when the reimbursing program is `ACTIVE` (a frozen or otherwise non-active program blocks approval with `ERR_DEPENDENCY_NOT_READY`), the member's `grh_year_event_count` is strictly below the program's `grh_max_events_per_year`, and the member's `grh_year_used_cents` is strictly below the program's `grh_annual_cap_cents`; approval moves the claim to `APPROVED` and moves no money. A breach of the event-count cap is rejected with `ERR_GRH_EVENT_CAP`, and a breach of the annual cap with `ERR_GRH_ANNUAL_CAP`. Alternatively, a `REQUESTED` claim may be denied: the adjudicator sets `denial_reason` from the request body (one of `ANNUAL_CAP`, `EVENT_CAP`, or `NOT_ELIGIBLE`) and the claim moves to the terminal `DENIED` state with no money moved and no ledger entry.

Reimbursing an `APPROVED` claim settles the money. The `reimbursed_cents` is computed as the smallest of the `claimed_fare_cents`, the program's `grh_per_event_cap_cents`, and the member's remaining annual allowance (the program's `grh_annual_cap_cents` minus the member's `grh_year_used_cents`, floored at 0) — the claim draws first against the per-event cap and is then further clipped by the annual remainder, so the smaller binding cap wins. The member's `wallet_balance_cents` is credited by `reimbursed_cents`, a `SubsidyLedgerEntry` debit of `reimbursed_cents` with reason `GRH_REIMBURSED` is appended, the program's `subsidy_consumed_cents` is recomputed, and the member's `grh_year_used_cents` and `grh_year_event_count` are recomputed. If, after this reimbursement, the member's `grh_year_event_count` equals the program's `grh_max_events_per_year`, a `ReliabilityEvent` of type `GRH_OVERUSE` is appended and the member's `reliability_score` is recomputed. The claim then moves to the terminal `REIMBURSED` state.

### 3.10. The Subsidy Ledger as the Money Trail

Every movement of program subsidy is recorded as an append-only `SubsidyLedgerEntry`. Each entry names the `employer_program_id` whose budget it moves, the `member_id` it applies to, optionally the `reservation_id` that produced it, a signed `amount_cents` (a positive `DEBIT` consumes budget, a negative `CREDIT` returns it), an `entry_type` of `DEBIT` or `CREDIT`, and a `reason` drawn from `RESERVATION_FINALIZED`, `RESERVATION_CANCELLED`, `TRIP_CANCELLED`, or `GRH_REIMBURSED`. The program's derived `subsidy_consumed_cents` is exactly the signed sum of `amount_cents` across its entries, which is why a debit at finalization or GRH reimbursement raises it and a credit at cancellation lowers it. Ledger entries are retrievable individually and as a list filterable by `member_id`, `reservation_id`, or `employer_program_id`, available to `ProgramAdmin` and `PlatformOps`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. The simulation-clock and batch operations also return `200 OK`. The request body, response body, and side effects of each endpoint are governed by the narratives in §3 above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employer-programs` | Create an employer commuter program | ProgramAdmin, PlatformOps |
| GET | `/employer-programs/{id}` | Get an employer program | ProgramAdmin, PlatformOps, Driver, Rider |
| POST | `/employer-programs/{id}/freeze` | Freeze a program so no new subsidy debits occur | ProgramAdmin, PlatformOps |
| POST | `/employer-programs/{id}/unfreeze` | Unfreeze a frozen program | ProgramAdmin, PlatformOps |
| GET | `/employer-programs/{id}/ledger` | List subsidy ledger entries for a program | ProgramAdmin, PlatformOps |
| POST | `/members` | Register a member (rider and/or driver) | ProgramAdmin, PlatformOps |
| GET | `/members/{id}` | Get a member profile with derived counters and score | ProgramAdmin, PlatformOps, Driver, Rider |
| GET | `/members` | List members; filterable by employer_program_id | ProgramAdmin, PlatformOps |
| GET | `/members/{id}/reliability` | Get a member's reliability score (confirmed or provisional) | ProgramAdmin, PlatformOps, Driver, Rider |
| POST | `/members/{id}/wallet/adjustments` | Operator wallet top-up/debit adjustment | PlatformOps, ProgramAdmin |
| POST | `/vehicles` | Register a vehicle for a driving member | Driver, PlatformOps |
| GET | `/vehicles/{id}` | Get a vehicle | Driver, PlatformOps, ProgramAdmin, Rider |
| GET | `/vehicles` | List vehicles; filterable by owner_member_id | Driver, PlatformOps, ProgramAdmin |
| POST | `/pools` | Create a pool (FORMING) owned by the driving member | Driver, PlatformOps |
| GET | `/pools/{id}` | Get a pool | Driver, PlatformOps, ProgramAdmin, Rider |
| GET | `/pools` | List pools; filterable by employer_program_id, driver_member_id, vehicle_id | Driver, PlatformOps, ProgramAdmin, Rider |
| POST | `/pools/{id}/activate` | Activate a FORMING or reactivate a SUSPENDED pool | Driver, ProgramAdmin, PlatformOps |
| POST | `/pools/{id}/suspend` | Suspend an ACTIVE pool; cancels its future scheduled trips | Driver, ProgramAdmin, PlatformOps |
| POST | `/pools/{id}/close` | Close a pool permanently | Driver, PlatformOps |
| POST | `/match-requests` | Create a rider match request (OPEN) | Rider, PlatformOps |
| GET | `/match-requests/{id}` | Get a match request | Rider, PlatformOps, ProgramAdmin |
| GET | `/match-requests` | List match requests; filterable by rider_member_id, matched_pool_id | Rider, PlatformOps, ProgramAdmin |
| POST | `/match-requests/{id}/match` | Run the matcher: select the best eligible pool | Rider, PlatformOps |
| POST | `/match-requests/{id}/reject` | Reject the matched pool and exclude it from future matches | Rider, PlatformOps |
| POST | `/match-requests/{id}/confirm` | Confirm the matched pool; creates a membership | Rider |
| POST | `/match-requests/{id}/cancel` | Cancel an OPEN or MATCHED match request | Rider, PlatformOps |
| POST | `/memberships` | Join a pool as a recurring rider (OCC-guarded on pool version) | Rider, PlatformOps |
| GET | `/memberships/{id}` | Get a membership | Rider, Driver, PlatformOps, ProgramAdmin |
| GET | `/memberships` | List memberships; filterable by pool_id, rider_member_id | Rider, Driver, PlatformOps, ProgramAdmin |
| POST | `/memberships/{id}/end` | End an active membership | Rider, Driver, PlatformOps |
| POST | `/trips` | Schedule a trip instance for a pool | Driver, PlatformOps |
| GET | `/trips/{id}` | Get a trip | Driver, PlatformOps, ProgramAdmin, Rider |
| GET | `/trips` | List trips; filterable by pool_id | Driver, PlatformOps, ProgramAdmin, Rider |
| POST | `/trips/{id}/open-boarding` | Open boarding on a SCHEDULED trip (requires pool ACTIVE) | Driver, PlatformOps |
| POST | `/trips/{id}/depart` | Depart a BOARDING trip; RESERVED riders become NO_SHOW | Driver, PlatformOps |
| POST | `/trips/{id}/complete` | Complete an IN_TRANSIT trip; finalize cost-share, subsidy, payments | Driver, PlatformOps |
| POST | `/trips/{id}/cancel` | Cancel a SCHEDULED or BOARDING trip; refund and reverse subsidy | Driver, ProgramAdmin, PlatformOps |
| POST | `/reservations` | Reserve seat(s) on a trip (OCC-guarded on trip version) | Rider, PlatformOps |
| GET | `/reservations/{id}` | Get a reservation | Rider, Driver, PlatformOps, ProgramAdmin |
| GET | `/reservations` | List reservations; filterable by trip_id, rider_member_id | Rider, Driver, PlatformOps, ProgramAdmin |
| POST | `/reservations/{id}/check-in` | Check a rider in on a BOARDING trip | Driver, PlatformOps |
| POST | `/reservations/{id}/no-show` | Mark a RESERVED rider as a no-show | Driver, PlatformOps |
| POST | `/reservations/{id}/cancel` | Cancel a RESERVED reservation; refund and reverse subsidy | Rider, Driver, PlatformOps |
| POST | `/grh-claims` | Submit a guaranteed-ride-home claim (REQUESTED) | Rider, PlatformOps |
| GET | `/grh-claims/{id}` | Get a GRH claim | Rider, ProgramAdmin, PlatformOps |
| GET | `/grh-claims` | List GRH claims; filterable by rider_member_id, employer_program_id, trip_id | Rider, ProgramAdmin, PlatformOps |
| POST | `/grh-claims/{id}/approve` | Approve a REQUESTED claim (checks event + annual caps) | ProgramAdmin, PlatformOps |
| POST | `/grh-claims/{id}/reimburse` | Reimburse an APPROVED claim; credits wallet, debits subsidy | ProgramAdmin, PlatformOps |
| POST | `/grh-claims/{id}/deny` | Deny a REQUESTED claim with a denial reason | ProgramAdmin, PlatformOps |
| GET | `/reliability-events/{id}` | Get a single reliability event | ProgramAdmin, PlatformOps, Driver, Rider |
| GET | `/reliability-events` | List reliability events; filterable by member_id, reservation_id | ProgramAdmin, PlatformOps, Driver, Rider |
| GET | `/subsidy-ledger-entries/{id}` | Get a single subsidy ledger entry | ProgramAdmin, PlatformOps |
| GET | `/subsidy-ledger-entries` | List subsidy ledger entries; filterable by member_id, reservation_id, employer_program_id | ProgramAdmin, PlatformOps |
| POST | `/_clock/set` | Test-driving: set the simulation clock to an absolute instant | PlatformOps |
| POST | `/_batch/run` | Test-driving: run the periodic batch (expires stale OPEN match requests) | PlatformOps |
| GET | `/healthz` | Liveness probe (no auth) | ProgramAdmin, PlatformOps, Driver, Rider, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_TRIP_VERSION` | 412 |
| `ERR_STALE_POOL_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPENDENCY_NOT_READY` | 409 |
| `ERR_RELIABILITY_TOO_LOW` | 409 |
| `ERR_TRIP_WINDOW_OVERLAP` | 409 |
| `ERR_RIDER_DOUBLE_BOOKED` | 409 |
| `ERR_SEATS_EXHAUSTED` | 409 |
| `ERR_POOL_CAPACITY_EXCEEDED` | 409 |
| `ERR_GRH_EVENT_CAP` | 409 |
| `ERR_GRH_ANNUAL_CAP` | 409 |
| `ERR_INSUFFICIENT_WALLET` | 402 |
| `ERR_NO_MATCH_FOUND` | 422 |
| `ERR_VALIDATION_DRIVER_REQUIRED` | 422 |
| `ERR_PROGRAM_BUDGET_EXHAUSTED` | 409 |
| `ERR_MEMBERSHIP_DUPLICATE` | 409 |
