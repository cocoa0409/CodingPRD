# Portable Storage Container API — Product Requirements Document

## 1. Introduction

Portable storage rental — the model where a weatherproof container is dropped at a customer's address, filled at the customer's pace, and either kept on site, moved to a new address, or hauled back to a depot — sits at the intersection of two hard problems: a finite physical inventory that many customers compete for, and a monthly billing relationship that must keep ticking accurately while containers are delivered, held, moved, accessed, and finally returned. This document specifies the API that runs that business end to end.

The platform tracks a catalog of container sizes and contents-protection tiers, a network of depots each holding a finite pool of physical containers, and the crews and trucks that place and transport them. Around that operational core it runs a billing ledger: every delivery fee, prorated and full monthly rental cycle, protection premium, packing-supplies order, transport charge, access fee, and late fee is posted as an immutable ledger row, and customer payments settle those debits oldest-first. A single rental agreement therefore carries two state stories at once — where the container physically is in its lifecycle, and whether the customer's account is paid up — and the system must keep both correct as they evolve independently.

The intended readers are the engineers who will implement this contract. The sections below first fix the system-wide conventions (authentication, response envelope, pagination, concurrency, precision, and the cross-cutting consistency rules), then narrate the business workflows in detail, and finally enumerate the endpoints and error codes. Where a number or a rule matters, it is stated precisely; the reader should not have to guess a threshold, a rounding direction, or which entity a side effect lands on.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `DispatchOperator`, `BillingClerk`, and `PlatformAdmin`. A request that omits `X-User-Role`, carries a role outside this set, or omits `X-User-ID` where an entity-backed role requires it, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint — or which violates the ownership rule below — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Customer` role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that ultimately references a `Customer` compare that resource's owning `customer_id` to `X-User-ID`. Concretely, a `Customer` may act only on rental agreements whose `customer_id` equals their `X-User-ID`, and on the sub-resources (charges, container units, delivery jobs, move orders, access visits, packing-supply orders) of those agreements; acting on another customer's agreement is an `ERR_FORBIDDEN`.

The other three roles are opaque operator identities. When `X-User-Role` is `DispatchOperator`, `BillingClerk`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`. A `DispatchOperator` manages the inventory draw, delivery placement, transport moves, and access fulfillment. A `BillingClerk` runs the billing sweeps and finalizes closeouts but posts no inventory or logistics changes. A `PlatformAdmin` seeds the catalog, depots, inventory, crews, and trucks, and controls the test clock.

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

List endpoints are paginated with two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order.

Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching resources before pagination is applied and `has_more` is true when more items remain beyond the current page.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; it is used for identity only and never participates in a business decision. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded at creation. The server clock that stamps `created_at` is the same logical clock used for all due-date and overdue arithmetic (see §2.8), so timestamps reflect the current logical instant, not wall-clock time.

Most resources are mutable and additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version`, an integer that begins at 1 on creation and increments by exactly 1 on each mutation. The following entities are immutable after creation and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: the `ContainerModel` catalog entries and the `ProtectionPlan` tiers. Every other entity — `Depot`, `DepotInventory`, `Customer`, `RentalAgreement`, `ContainerUnit`, `Crew`, `Truck`, `DeliveryJob`, `MoveOrder`, `AccessVisit`, `PackingSupplyOrder`, and `Charge` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When the server recomputes a derived field on a resource (for example a balance or an availability count), that recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations in this system mutate more than one entity at once. The governing rule is that every cascade described in §3 must be applied completely and atomically: when an operation lists a primary effect and one or more secondary effects, all of them land together, and each mutated entity has its `updated_at` refreshed and its `version` incremented as described in §2.4.

The most important cascade is delivery activation. Completing an initial-delivery placement does not merely close the job — it flips the physical container forward, moves the rental agreement into its active life, draws the unit out of the reserved pool and into the committed pool, and posts the opening run of charges. The same all-or-nothing discipline applies to transport completion (which can shift a container's home depot and rebalance two inventory rows), to closeout finalization (which releases a unit and frees inventory), and to compensating reversals (cancelling a reserved agreement releases its unit; cancelling a scheduled move reverses its posted charge). Each of these is spelled out in §3; the principle here is that none of them is partial.

### 2.6. Inventory as a Conserved Finite Pool

Each `DepotInventory` row tracks the physical containers of one size at one depot and is the contended resource of the whole system. The row records `total_units`, the count of physical containers owned, and derives three counts that always reflect the live set of `ContainerUnit` rows drawn from it. The `reserved_units` count is the number of those units currently in `RESERVED` status. The `committed_units` count is the number in `DELIVERED`, `ON_SITE`, `IN_TRANSIT`, or `RETURNED` status — a returned unit still counts as committed until its agreement is fully closed. The `available_units` count is `total_units` minus `reserved_units` minus `committed_units`. All three are integer counts with no rounding.

These counts are conserved: every operation that moves a unit between statuses adjusts the affected counts so that the pool is never double-counted and a released unit drops out of both `reserved_units` and `committed_units`. A reserve that is later cancelled restores the pool to exactly its pre-reserve count, and a long-distance move that completes decrements the committed count on the origin inventory row and increments it on the destination row, so the global sum of units across depots is preserved.

### 2.7. Optimistic Concurrency Control

Two specific write operations against a `RentalAgreement` are guarded by optimistic concurrency control, because each acts on data the client must have read first. Both require a non-optional `expected_agreement_version` field in the request body carrying the client's last observed `version` of the target agreement.

The first is reserving a container. A reserve request must carry `expected_agreement_version` matching the target agreement's current `version`. If another writer has advanced the agreement's `version` since the client last read it, the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412); because a reserve draws a unit from the finite pool, a stale version means the operator's view of the available draw is out of date and must not be acted on.

The second is posting a payment. A payment request must likewise carry `expected_agreement_version` matching the agreement's current `version`. A late-fee sweep can post a new late-fee charge and advance the agreement's `version` between the moment a client reads the balance and the moment it pays; if the supplied `expected_agreement_version` no longer matches, the payment is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads the now-larger balance before paying.

No other endpoint takes a version field. Endpoints not named here perform their mutations without an optimistic-concurrency check.

### 2.8. The Logical Clock and Time Semantics

All time-dependent arithmetic — `created_at` stamping, `due_date` derivation, and the `days_overdue` computation — reads from a single server-held logical clock expressed as a UTC instant. An administrative test-driving capability sets this clock to a supplied `to_iso8601` instant; every subsequent `created_at`, `due_date`, and overdue calculation uses the new instant. This makes billing behavior fully deterministic: advancing the clock is how the passage of days that triggers late fees is simulated.

Scheduling windows use explicit interval conventions that the reader must respect. A delivery job window runs from `window_start` to `window_end` and is treated as half-open — the interval `[window_start, window_end)` includes the start instant but excludes the end instant, and `window_end` must be strictly after `window_start`. A move order window also runs from `window_start` to `window_end` but is treated as closed — the interval `[window_start, window_end]` includes both endpoints, so two moves that touch exactly at an endpoint are considered back-to-back and do not conflict; here too `window_end` must be strictly after `window_start`.

### 2.9. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation produces a fractional cent — a proration, a premium computed from basis points, a fuel surcharge, a tax, a percentage cap — the result is rounded half up to a whole cent. Integer counts (inventory units, day counts) involve no rounding; day counts that arise from subtracting one instant from another are taken as whole-day floors. Each calculation in §3 states its own rounding sequence; where a rule says "rounded once on the summed total," the rounding is applied a single time to the aggregate and never per component, and the reader must follow the stated order exactly.

### 2.10. Validation Order and Left-to-Right Resource Resolution

When a request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or invalid `X-User-Role` (or a missing `X-User-ID` for `Customer`) yields `ERR_UNAUTHENTICATED` before anything else is examined. Authorization is second: a role not permitted for the endpoint, or a `Customer` acting on an agreement they do not own, yields `ERR_FORBIDDEN`. Existence is third: every resource referenced in the path and in the body's foreign keys is resolved left-to-right — agreement, then customer, depot, inventory, unit, crew, truck, job, order, visit — and the first reference that does not resolve yields `ERR_NOT_FOUND`. Schema validity is fourth: required fields present, enum values in their allowed sets, integers non-negative, window ordering correct, and supply lines non-empty, otherwise `ERR_INVALID_REQUEST`.

Only after those four universal gates pass does the system evaluate referential business checks, then state-machine preconditions, then optimistic-concurrency, then the domain-specific safety and fiscal rules. The per-endpoint ordering of those later checks is described alongside each workflow in §3; the universal point here is that authentication precedes authorization precedes existence precedes schema validity precedes every business rule, so a deeper business failure can never mask a shallower one.

## 3. Business Logic & Workflows

### 3.1. Catalog, Depots, and the Physical Fleet

Before any customer can rent, a `PlatformAdmin` seeds the reference data. A container size model is created with a `size_code` (one of `C8`, `C12`, or `C16`, unique across all models), a `cubic_feet` usable volume of at least 1 (carried for display only), a `monthly_rate_cents` base monthly rate of at least 0, a `delivery_fee_cents` flat initial-delivery fee of at least 0, and a `footprint_sqft` ground footprint of at least 1 that drives placement clearance. A contents-protection tier is created with a `tier_code` (one of `NONE`, `BASIC`, `PLUS`, or `PREMIER`, unique across plans), a `base_premium_cents` fixed monthly floor component, a `rate_bps` premium rate in basis points, a `min_premium_cents` premium floor, and a `coverage_cap_cents` maximum declared value the tier will accept — and the `NONE` tier always has a `coverage_cap_cents` of 0. All of these are non-negative integers.

Depots anchor the geography. A depot is created with a `name`, a two-letter uppercase `state_code`, and a `service_radius_miles` of at least 0 that defines the local-move boundary. For each size a depot stocks, an inventory row is created naming the `depot_id` and the `size_code` (the pair `depot_id` plus `size_code` is unique per depot) and an initial `total_units` of at least 0; on creation the row's `reserved_units` and `committed_units` both start at 0 and `available_units` starts equal to `total_units`. Crews and trucks complete the fleet. A crew is created against its home `depot_id` with a `name` and an optional `setup_buffer_minutes` (defaulting to 30, at least 0) that is the mandatory teardown-and-travel buffer appended after each of that crew's delivery windows. A truck is created against its home `depot_id` with a unique non-empty `plate` and an optional `max_concurrent_containers` (defaulting to 1, at least 1) that caps how many containers it may carry across overlapping moves.

### 3.2. Customers and the Quote-to-Reservation Path

A customer is registered with a unique non-empty `email`, a `full_name`, and a two-letter uppercase `state_code`. Two ledger mirrors are exposed on the customer and explained in §3.9: `lifetime_paid_cents` and `open_balance_cents`, both starting at 0.

A rental relationship begins as a quote. Creating a rental agreement names the `customer_id`, the `depot_id` the container will be drawn from, the requested `size_code`, an optional `protection_tier_code` (defaulting to `NONE`), an optional `declared_value_cents` for the stored contents (defaulting to 0), an optional `proration_method` (one of `CALENDAR_DAY` or `FIXED_30`, defaulting to `CALENDAR_DAY`), a `site_address`, and a `site_clearance_sqft` of at least 0 attesting to the clear ground at the delivery site. A new agreement begins with `lifecycle_status` of `QUOTED` and `billing_status` of `CURRENT`; its computed fields — `delivery_anchor_date`, `monthly_premium_cents`, `balance_due_cents`, `last_charged_cycle_date`, and `days_overdue` — start unset or zero as appropriate, with `delivery_anchor_date` and `last_charged_cycle_date` null until delivery.

Reserving against a `QUOTED` agreement is the act that draws a physical container from the finite pool, and it is performed by a `DispatchOperator`. Reservation advances `lifecycle_status` from `QUOTED` to `RESERVED` and is permitted only when the agreement is `QUOTED`; an agreement in any other lifecycle state is rejected with `ERR_INVALID_STATE`. Before the draw, two business gates apply. First, the matching `DepotInventory` row for the agreement's `depot_id` and `size_code` must exist, or the request fails with `ERR_INVENTORY_ROW_MISSING`. Second, the declared value must fit the selected tier: `declared_value_cents` must be at or below the selected `ProtectionPlan`'s `coverage_cap_cents`, otherwise the reserve is rejected with `ERR_DECLARED_VALUE_OVER_CAP`. There must also be stock: if the matching inventory row's `available_units` is below 1, the reserve is rejected with `ERR_NO_INVENTORY` rather than driving the pool negative. The reserve request also carries `expected_agreement_version` and is subject to the optimistic-concurrency check of §2.7. When the reserve succeeds, the system creates one `ContainerUnit` in `RESERVED` status drawn from that inventory row (recording its `agreement_id`, its `depot_inventory_id`, a `size_code` mirroring the inventory row, and a `current_depot_id` equal to the drawing depot), increments the row's `reserved_units` by 1, recomputes `available_units`, and increments the agreement's `version`.

A `QUOTED` or `RESERVED` agreement may be cancelled by its owning `Customer`. Cancelling moves `lifecycle_status` to `CANCELLED`. When the agreement was merely `QUOTED`, the cancel is a clean abandonment. When it was `RESERVED`, the cancel is compensating: the reserved `ContainerUnit` flips to `RELEASED`, the inventory row's `reserved_units` is decremented by 1, and `available_units` is recomputed — restoring the pool to exactly the count it held before the reserve.

### 3.3. Scheduling and Completing the Initial Delivery

Once a unit is reserved, a `DispatchOperator` schedules its placement. A delivery job names the `agreement_id`, the `crew_id` performing the placement, the `container_unit_id` being delivered, an optional `job_kind` (one of `INITIAL_DELIVERY` or `REDELIVERY`, defaulting to `INITIAL_DELIVERY`), a `window_start`, and a `window_end` (strictly after the start, with the half-open semantics of §2.8). A newly scheduled job has `status` of `SCHEDULED`.

Two safety checks guard scheduling, and they are evaluated only after the universal gates of §2.10. The placement-clearance check applies to initial-delivery jobs: the agreement's `site_clearance_sqft` must be at least the `footprint_sqft` of the `ContainerModel` for the agreement's size, otherwise the job is rejected with `ERR_INSUFFICIENT_CLEARANCE`. The crew-availability check applies to all delivery jobs: the proposed window, extended at its tail by the crew's `setup_buffer_minutes`, must not overlap any other `SCHEDULED` job on the same crew. That is, treating each existing scheduled job's occupied interval as its `[window_start, window_end)` window plus the buffer minutes appended after `window_end`, the new job's similarly buffered interval must share no instant with any of them; an overlap is rejected with `ERR_CREW_WINDOW_CONFLICT`. A job that is later cancelled frees its window — a `SCHEDULED` job may be cancelled by a `DispatchOperator`, moving its `status` to `CANCELLED`, after which the crew-conflict check no longer sees it.

Completing a delivery job is the system's pivotal cascade and is performed by a `DispatchOperator`. Completion is allowed only when the job is `SCHEDULED` and the assigned container is in the status the `job_kind` expects — `RESERVED` for an `INITIAL_DELIVERY`, `IN_TRANSIT` for a `REDELIVERY`; otherwise the request is rejected with `ERR_INVALID_STATE`. The job moves `SCHEDULED` to `COMPLETED`. For an `INITIAL_DELIVERY`, completion drives the activation chain end to end: the container advances `RESERVED → DELIVERED → ON_SITE` within the one transition, the inventory row's `reserved_units` is decremented by 1 and `committed_units` incremented by 1 with `available_units` recomputed, the agreement's `delivery_anchor_date` is set to the date of the job's `window_start`, and the agreement's `lifecycle_status` advances `RESERVED → ACTIVE`. Activation also posts the opening charges and locks pricing, described in §3.4. For a `REDELIVERY`, completion is narrower: it cascades the container `IN_TRANSIT → ON_SITE` and posts no new charges.

### 3.4. Activation Billing: Delivery Fee, Proration, and Protection Premium

The moment an agreement activates, three things are billed and the protection premium is locked. The system posts a `DELIVERY_FEE` charge equal to the `delivery_fee_cents` of the `ContainerModel` for the agreement's size. It locks the monthly protection premium onto the agreement's `monthly_premium_cents` (computed as below) and posts a `PROTECTION_PREMIUM` charge for that amount. And it posts the first-cycle `RENTAL_PRORATION` charge, then sets `last_charged_cycle_date` to the `delivery_anchor_date`. After posting, the agreement's `balance_due_cents` is recomputed (§3.8) and the customer's `open_balance_cents` is recomputed (§3.9).

The protection premium is computed from the selected `ProtectionPlan`. Take the plan's `base_premium_cents` and add to it the plan's `rate_bps` multiplied by the agreement's `declared_value_cents`, divided by 10,000, with that product rounded half up to whole cents; call the sum the raw premium. The locked `monthly_premium_cents` is the larger of the raw premium and the plan's `min_premium_cents`. (Because the declared value was validated at reserve against the tier's coverage cap, it is already within bounds here.)

The first-cycle proration bills only the portion of the delivery month from the delivery day onward. Let the monthly amount be the `ContainerModel`'s `monthly_rate_cents`, let the delivery day be the day-of-month of `delivery_anchor_date`, and let the days billed be the number of calendar days in the delivery month minus the delivery day, plus one — that is, the delivery day counted inclusively through the last day of that month. The proration then depends on the agreement's `proration_method`. Under the `CALENDAR_DAY` method, the proration is the monthly amount multiplied by the days billed and divided by the actual number of days in the delivery calendar month (28, 29, 30, or 31), rounded half up to whole cents. Under the `FIXED_30` method, the proration is the monthly amount multiplied by the days billed and divided by 30 regardless of the month's true length, rounded half up to whole cents; the two methods diverge in any 31-day month and in February. Both methods are billed as a `RENTAL_PRORATION` charge. Thereafter, while the agreement is `ACTIVE`, full monthly `RENTAL_CYCLE` charges post for subsequent months as described in §3.8.

### 3.5. Holds, Resumes, and Closeout

Once active, an agreement's owning `Customer` controls its rhythm. Placing an agreement on hold suspends monthly rental-cycle billing; it advances `lifecycle_status` from `ACTIVE` to `ON_HOLD` and is permitted only when the agreement is `ACTIVE`. There is an additional fiscal gate: an agreement whose `billing_status` is `PAST_DUE` or `DELINQUENT` cannot be placed on hold, and such a request is rejected with `ERR_BILLING_NOT_CURRENT`; only an agreement whose `billing_status` is `CURRENT` may go on hold. Resuming reverses this, advancing `lifecycle_status` from `ON_HOLD` back to `ACTIVE` and allowing monthly billing to resume from the next anchor; it is permitted only when the agreement is `ON_HOLD`. The hold/resume loop may repeat any number of times.

Closeout begins when the `Customer` requests it. Requesting closeout advances `lifecycle_status` from `ACTIVE` to `CLOSING` and creates the obligation that the container be returned before the agreement can close. It is permitted only when the agreement is `ACTIVE`, and it is blocked while logistics are still open: if any move order for the agreement is `SCHEDULED` or `IN_TRANSIT`, or any delivery job for the agreement is `SCHEDULED`, the request is rejected with `ERR_OPEN_LOGISTICS`. While the agreement is `CLOSING`, a `DispatchOperator` brings the container back: returning an `ON_SITE` unit to depot advances the container `ON_SITE → RETURNED` and is permitted only when the unit is `ON_SITE` and its parent agreement is `CLOSING`; a returned unit is physically at a depot but still counts toward `committed_units` until the agreement closes.

Finalizing is a `BillingClerk` action. Closing advances `lifecycle_status` from `CLOSING` to `CLOSED`, but only when three conditions hold: the agreement is `CLOSING`, its container is `RETURNED`, and its final balance is fully settled. The fiscal gate uses the final balance variant of §3.8: if `balance_due_cents` computed under the final variant is greater than 0, the close is rejected with `ERR_OUTSTANDING_BALANCE`; if the container is not yet `RETURNED`, the close is rejected with `ERR_INVALID_STATE`. On a successful close, the container advances `RETURNED → RELEASED`, the inventory row's `committed_units` is decremented by 1 and `available_units` recomputed (restoring the pool), and the customer's `open_balance_cents` is recomputed.

### 3.6. Transport Moves: Local versus Long-Distance Pricing

While an agreement is `ACTIVE`, a `DispatchOperator` can schedule a transport move of the on-site container. A move order names the `agreement_id`, the `truck_id` hauling it, the `container_unit_id` being moved, the `origin_depot_id` that governs the local-versus-long-distance classification, a two-letter uppercase `destination_state_code`, a `distance_miles` of at least 0, a `window_start`, and a `window_end` (strictly after the start, with the closed-interval semantics of §2.8). A new move begins with `status` of `SCHEDULED`, and at creation the system classifies it and locks its price into `quoted_cost_cents`.

The move is classified `LOCAL` when its `distance_miles` is at or below the origin depot's `service_radius_miles`, and `LONG_DISTANCE` when the distance exceeds that radius; the boundary at exactly the radius is `LOCAL`. This classification is recorded as `move_class`. A `LOCAL` move's `quoted_cost_cents` is a flat base of 8,900 cents plus 350 cents for each mile of `distance_miles`, with no fuel surcharge and no tier bands. A `LONG_DISTANCE` move is priced on marginal mileage bands plus a fuel surcharge plus per-container handling. The mileage component is built from three bands, each rate applying only to the miles falling within that band: the first 500 miles are billed at 180 cents per mile; the miles above 500 and up to 1,500 are billed at 140 cents per mile; the miles above 1,500 are billed at 110 cents per mile. Summing those three band contributions gives the mileage amount. The fuel surcharge is 12 percent of that mileage amount, computed once on the summed mileage amount and rounded half up to whole cents. Per-container handling adds a flat 12,500 cents for the single container the move carries. The `quoted_cost_cents` is the sum of the mileage amount, the fuel surcharge, and the handling amount.

Capacity is checked at scheduling, after the universal gates: across the same truck, sum the containers of all `SCHEDULED` or `IN_TRANSIT` move orders whose closed `[window_start, window_end]` windows intersect the new move's window; if adding this move's one container would push that sum above the truck's `max_concurrent_containers`, the move is rejected with `ERR_TRUCK_CAPACITY_EXCEEDED`. Because move windows are closed intervals, two moves that merely touch at an endpoint do not intersect and do not count against each other. On successful creation the system posts a `MOVE` charge equal to `quoted_cost_cents` and recomputes the agreement's `balance_due_cents` — though, as §3.8 explains, the move charge does not affect the collectible balance until closeout.

Dispatching a scheduled move advances it `SCHEDULED → IN_TRANSIT`; it is permitted only when the move is `SCHEDULED`, the container is `ON_SITE`, and the parent agreement is `ACTIVE`, and it cascades the container `ON_SITE → IN_TRANSIT`. Completing an in-transit move advances it `IN_TRANSIT → COMPLETED` and cascades the container `IN_TRANSIT → ON_SITE`; when the `move_class` is `LONG_DISTANCE`, completion also sets the container's `current_depot_id` to the move's destination depot and rebalances inventory — the origin `DepotInventory` row's `committed_units` is decremented by 1 and the destination row's `committed_units` incremented by 1, preserving the global pool. Cancelling a scheduled move advances it `SCHEDULED → CANCELLED`; if a `MOVE` charge was posted at scheduling, the system posts a compensating `ADJUSTMENT` charge equal to the negative of `quoted_cost_cents` and recomputes `balance_due_cents`, so the ledger nets back to where it stood before the move.

### 3.7. Access Visits and Packing Supplies

A `Customer` may request access to stored contents. An access visit names the `agreement_id`, the `container_unit_id` being accessed, an optional `access_kind` (one of `ON_SITE` or `DEPOT_PICKUP`, defaulting to `ON_SITE`), and a `requested_for` instant. The system sets `redelivery_required` to true exactly when `access_kind` is `DEPOT_PICKUP` and false otherwise, because a depot pickup means the container leaves the site and must be brought back. A new visit has `status` of `REQUESTED`.

Fulfilling an access visit is a `DispatchOperator` action and advances it `REQUESTED → FULFILLED`; it is permitted only when the visit is `REQUESTED`, the parent agreement is `ACTIVE`, and the container is `ON_SITE`, otherwise `ERR_INVALID_STATE`. Fulfillment posts an `ACCESS_FEE` charge. When the `access_kind` is `DEPOT_PICKUP`, fulfillment also cascades the container `ON_SITE → IN_TRANSIT` and leaves `redelivery_required` true, so a subsequent `REDELIVERY` delivery job must bring it back (that redelivery completion is the cascade described in §3.3 that returns the container to `ON_SITE`). A `Customer` may cancel a still-`REQUESTED` visit, advancing it `REQUESTED → CANCELLED`.

Packing supplies are an add-on a `Customer` orders against an agreement. A packing-supply order names the `agreement_id`, a non-empty array of `lines`, and an optional `tax_rate_bps` (defaulting to 825, at least 0). Each entry in `lines` is an object with a `sku`, a `qty` of at least 1, a `unit_price_cents` of at least 0, a `bulk_threshold`, and a `bulk_pct`. The order computes three amounts. For each line, the gross is `qty` multiplied by `unit_price_cents`; if that line's `qty` is at or above its `bulk_threshold`, a bulk discount equal to the gross multiplied by the line's `bulk_pct`, rounded half up to whole cents, is subtracted, otherwise no discount applies; the line net is the gross minus that discount. The `subtotal_cents` is the sum of all the line nets. The `tax_cents` is computed exactly once on the summed subtotal — `subtotal_cents` multiplied by `tax_rate_bps` divided by 10,000, rounded half up to whole cents — and never per line. The `total_cents` is `subtotal_cents` plus `tax_cents`. A new order has `status` of `PLACED`. On placement the system posts a `PACKING_SUPPLIES` charge equal to `total_cents` and recomputes the agreement's `balance_due_cents`.

### 3.8. The Charge Ledger, Balances, and Monthly Cycles

Every billable event becomes an immutable `Charge` row recording its `agreement_id`, its `charge_type` (one of `DELIVERY_FEE`, `RENTAL_PRORATION`, `RENTAL_CYCLE`, `PROTECTION_PREMIUM`, `PACKING_SUPPLIES`, `MOVE`, `ACCESS_FEE`, `LATE_FEE`, `PAYMENT`, or `ADJUSTMENT`), a signed `amount_cents` (positive for debits the customer owes, negative for `PAYMENT` and credit `ADJUSTMENT` rows), a `due_date` (the date a debit is due, null for `PAYMENT` and `ADJUSTMENT`), and a `settled` flag.

The agreement's `balance_due_cents` is recomputed after any charge is posted or reversed, and again at close, by walking the agreement's charges in `created_at` ascending order. The balance is the sum of the in-scope debit amounts minus the sum of the credits (the credits being the negated amounts of `PAYMENT` and `ADJUSTMENT` rows). Which debits are in scope depends on the agreement's lifecycle phase, and this is the crux of the calculation. Under the provisional variant — used while `lifecycle_status` is `ACTIVE` or `ON_HOLD` — only debits of type `DELIVERY_FEE`, `RENTAL_PRORATION`, `RENTAL_CYCLE`, `PROTECTION_PREMIUM`, `PACKING_SUPPLIES`, and `ACCESS_FEE` are counted; `MOVE` and `LATE_FEE` debits are excluded because they are not collectible until closeout. Under the final variant — used while `lifecycle_status` is `CLOSING` or `CLOSED` — every posted debit is counted, including `MOVE` and `LATE_FEE`; the final balance therefore exceeds the provisional balance by exactly the sum of the `MOVE` and `LATE_FEE` debits. As the walk proceeds, a debit is marked `settled` true once the cumulative credits, applied oldest-first by `created_at`, fully cover it.

Two operator sweeps advance the billing calendar, both run by a `BillingClerk`. The monthly-cycle sweep posts the next `RENTAL_CYCLE` charge for every `ACTIVE` agreement whose `last_charged_cycle_date` precedes the current cycle, then advances that agreement's `last_charged_cycle_date` and recomputes `balance_due_cents`; the `RENTAL_CYCLE` amount is the agreement size's `monthly_rate_cents` plus the locked `monthly_premium_cents`. Agreements that are `ON_HOLD` are skipped, which is how a hold suspends monthly billing. The late-fee sweep is described next.

### 3.9. Late Fees, the Billing Dimension, and Payments

The `billing_status` dimension evolves independently of the lifecycle dimension on the same agreement row, cycling among `CURRENT`, `PAST_DUE`, and `DELINQUENT`. It is driven by the late-fee sweep, a `BillingClerk` operation that, for each agreement with an unpaid posted debit, recomputes `days_overdue` and posts late fees against the current clock.

The overdue computation looks at the oldest unsettled debit. Among the agreement's posted debit charges whose `settled` is false, find the earliest `due_date`; `days_overdue` is the whole-day floor of the current clock date minus that oldest due date, and it is 0 when every debit is settled (only debit rows enter this computation — `PAYMENT` and `ADJUSTMENT` rows are excluded). A grace period of 5 days applies: while `days_overdue` is at or below 5, the late fee is 0. Beyond the grace period, let the effective overdue days be `days_overdue` minus 5. The first 10 of those effective days are tier-one days; any effective days beyond 10 are tier-two escalation days. The gross late fee is a flat 2,500 cents, plus 200 cents for each tier-one day, plus 500 cents for each tier-two day. That gross is then capped: the cap is 50 percent of the agreement's `balance_due_cents`, rounded half up to whole cents, and the late fee charged is the smaller of the gross and the cap.

The sweep drives the billing dimension in two steps. An agreement that is `CURRENT` and whose `days_overdue` is above 5 but at or below 20 advances `CURRENT → PAST_DUE` and the sweep posts a `LATE_FEE` charge for the tier-one amount, then recomputes `balance_due_cents`. An agreement that is `PAST_DUE` and whose `days_overdue` is above 20 advances `PAST_DUE → DELINQUENT` and the sweep posts one additional `LATE_FEE` charge equal only to the incremental delta — the current total computed late fee minus the late fee already posted — then recomputes `balance_due_cents`. An agreement may re-enter `PAST_DUE` and `DELINQUENT` on a later sweep after it has returned to `CURRENT`.

Payments are how a `Customer` clears the balance. Posting a payment supplies an `amount_cents` and the `expected_agreement_version` of §2.7. The system posts a `PAYMENT` charge carrying the negative of the paid amount, then walks the debits oldest-first by `created_at` marking each `settled` as the cumulative credits cover it, and recomputes `balance_due_cents`. When the agreement is in `PAST_DUE` or `DELINQUENT` and, after applying the payment, `balance_due_cents` reaches 0, the `billing_status` returns to `CURRENT` and `days_overdue` is recomputed. Each payment also refreshes the two customer mirrors: `lifetime_paid_cents` is the sum, across all of that customer's agreements, of the absolute value of every `PAYMENT` charge, and `open_balance_cents` is the sum of `balance_due_cents` across that customer's agreements whose `lifecycle_status` is `RESERVED`, `ACTIVE`, `ON_HOLD`, or `CLOSING` — `CLOSED` and `CANCELLED` agreements drop out of `open_balance_cents`. These mirrors are likewise refreshed on delivery activation and on close.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the operator sweeps — return `200 OK`. The clock-setting and billing-sweep capabilities are administrative test-driving endpoints; reading the request and response bodies for any endpoint requires reconstructing them from the §3 narratives, as the table below lists only method, path, description, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/container-models` | Create a container size model | PlatformAdmin |
| GET | `/container-models` | List container models | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/container-models/{id}` | Get a container model | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| POST | `/protection-plans` | Create a contents-protection tier | PlatformAdmin |
| GET | `/protection-plans` | List protection plans | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/protection-plans/{id}` | Get a protection plan | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| POST | `/depots` | Create a depot | PlatformAdmin |
| GET | `/depots/{id}` | Get a depot | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| POST | `/depot-inventory` | Create an inventory row for one size at a depot | PlatformAdmin |
| GET | `/depot-inventory` | List inventory rows | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/depot-inventory/{id}` | Get an inventory row with live availability | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| POST | `/crews` | Create a delivery crew | PlatformAdmin |
| GET | `/crews/{id}` | Get a crew | PlatformAdmin, DispatchOperator |
| GET | `/crews` | List crews | PlatformAdmin, DispatchOperator |
| POST | `/trucks` | Create a transport truck | PlatformAdmin |
| GET | `/trucks/{id}` | Get a truck | PlatformAdmin, DispatchOperator |
| GET | `/trucks` | List trucks | PlatformAdmin, DispatchOperator |
| POST | `/customers` | Register a customer | PlatformAdmin, Customer |
| GET | `/customers/{id}` | Get a customer with computed ledger mirrors | PlatformAdmin, BillingClerk, Customer |
| GET | `/customers/{id}/rental-agreements` | List a customer's rental agreements | PlatformAdmin, BillingClerk, Customer |
| POST | `/rental-agreements` | Create a quote | Customer, DispatchOperator |
| GET | `/rental-agreements/{id}` | Get a rental agreement | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements` | List rental agreements | PlatformAdmin, DispatchOperator, BillingClerk |
| POST | `/rental-agreements/{id}/reserve` | Reserve a container from inventory | DispatchOperator |
| POST | `/rental-agreements/{id}/hold` | Place an active agreement on hold | Customer |
| POST | `/rental-agreements/{id}/resume` | Resume an on-hold agreement | Customer |
| POST | `/rental-agreements/{id}/request-closeout` | Begin closeout | Customer |
| POST | `/rental-agreements/{id}/close` | Finalize and close | BillingClerk |
| POST | `/rental-agreements/{id}/cancel` | Cancel a quoted or reserved agreement | Customer |
| POST | `/rental-agreements/{id}/payments` | Post a customer payment | Customer |
| GET | `/rental-agreements/{id}/charges` | List the agreement's ledger charges | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements/{id}/container-units` | List the agreement's container units | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements/{id}/delivery-jobs` | List the agreement's delivery jobs | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements/{id}/move-orders` | List the agreement's move orders | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements/{id}/access-visits` | List the agreement's access visits | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/rental-agreements/{id}/packing-supply-orders` | List the agreement's packing-supply orders | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/container-units/{id}` | Get a container unit | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/container-units` | List container units | PlatformAdmin, DispatchOperator, BillingClerk |
| POST | `/container-units/{id}/return-to-depot` | Final closeout pickup of an on-site unit | DispatchOperator |
| POST | `/delivery-jobs` | Schedule a delivery or redelivery job | DispatchOperator |
| GET | `/delivery-jobs/{id}` | Get a delivery job | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/delivery-jobs` | List delivery jobs | PlatformAdmin, DispatchOperator |
| POST | `/delivery-jobs/{id}/complete` | Complete a delivery job | DispatchOperator |
| POST | `/delivery-jobs/{id}/cancel` | Cancel a scheduled delivery job | DispatchOperator |
| POST | `/move-orders` | Schedule a transport move | DispatchOperator |
| GET | `/move-orders/{id}` | Get a move order | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/move-orders` | List move orders | PlatformAdmin, DispatchOperator |
| POST | `/move-orders/{id}/dispatch` | Dispatch a scheduled move | DispatchOperator |
| POST | `/move-orders/{id}/complete` | Complete an in-transit move | DispatchOperator |
| POST | `/move-orders/{id}/cancel` | Cancel a scheduled move | DispatchOperator |
| POST | `/access-visits` | Request access to stored contents | Customer |
| GET | `/access-visits/{id}` | Get an access visit | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| GET | `/access-visits` | List access visits | PlatformAdmin, DispatchOperator |
| POST | `/access-visits/{id}/fulfill` | Fulfill an access visit | DispatchOperator |
| POST | `/access-visits/{id}/cancel` | Cancel a requested access visit | Customer |
| POST | `/packing-supply-orders` | Place a packing-supplies order | Customer |
| GET | `/packing-supply-orders/{id}` | Get a packing-supply order | PlatformAdmin, DispatchOperator, BillingClerk, Customer |
| POST | `/_billing/run-late-sweep` | Run the late-fee sweep | BillingClerk |
| POST | `/_billing/run-monthly-cycle` | Run the monthly rental-cycle sweep | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVENTORY_ROW_MISSING` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INSUFFICIENT_CLEARANCE` | 422 |
| `ERR_DECLARED_VALUE_OVER_CAP` | 422 |
| `ERR_CREW_WINDOW_CONFLICT` | 409 |
| `ERR_TRUCK_CAPACITY_EXCEEDED` | 409 |
| `ERR_OPEN_LOGISTICS` | 409 |
| `ERR_BILLING_NOT_CURRENT` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_NO_INVENTORY` | 409 |
