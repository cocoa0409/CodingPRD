# Ev Charging Network API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the EV Charging Network API, the backend that coordinates electric-vehicle charging across a Charge Point Operator's physical estate. The platform sits at the intersection of three concerns that rarely stay still at the same time: the physical reality of stations reporting their state over OCPP, the financial reality of pricing energy and time against driver wallets and roaming partners, and the engineering reality of a shared grid circuit that can only deliver so many kilowatts at once. A single charging session touches all three — it draws metered energy from a stall, it competes with its neighbors for a finite power budget, and at the moment it stops it must be priced, charged, and (when the driver is roaming) queued for settlement with an external e-mobility service provider.

The API is therefore organized around a small number of long-lived resources — sites, stalls, drivers, tariffs, reservations, charging sessions, and settlement batches — whose lifecycles are driven partly by human actors and partly by the stations themselves. Charging sessions are deliberately modeled along two independent axes: a physical charging dimension that tracks whether power is actually flowing, and a financial billing dimension that tracks whether the session has been priced, settled, or reversed. Dynamic load balancing continuously redistributes the site's circuit budget among the sessions that are actively charging, and an optional demand-charge-avoidance mode lets an operator cap aggregate draw below the raw circuit ceiling to dodge peak-demand utility penalties. The sections that follow define the global contract every endpoint obeys, then walk the business logic site by site, session by session, and batch by batch.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply uniformly across every endpoint. All resources are mounted under the `/api` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which the principal is acting. The system recognizes exactly three roles, spelled precisely as follows: `CPOOperator`, `Driver`, and `StationController`. If either header is missing, or if `X-User-Role` does not name one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to invoke the requested endpoint per the role matrix in §4, the request is rejected with `ERR_FORBIDDEN`.

The three roles are peers, each owning a distinct slice of the domain. A `CPOOperator` is the Charge Point Operator: it owns sites, stalls, tariffs, eMSP registrations, and driver records; it runs manual load balancing; and it operates the entire roaming-settlement lifecycle. When `X-User-Role` is `CPOOperator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it against any entity's `id` for ownership purposes. A `StationController` is the OCPP station-firmware actor that posts telemetry — status notifications and meter values — and drives the physical charging transitions. When `X-User-Role` is `StationController`, `X-User-ID` is likewise an opaque actor identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

A `Driver` represents an actual EV driver. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity. Ownership is enforced on driver-scoped resources: a `Driver` may only act on a `Reservation` or `ChargingSession` that it owns, meaning the resource's `driver_id` must equal the caller's `X-User-ID`. A `Driver` attempting to create a reservation whose `driver_id` is not its own, or to confirm, check in, or cancel another driver's reservation, or to start a session whose `driver_id` is not its own, or to stop or abort another driver's session, is rejected with `ERR_FORBIDDEN`. (A `StationController` starting a session is not subject to this driver-ownership check, since its `X-User-ID` is an opaque actor identifier.)

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0; it must be at least 0 and has no upper bound. A `limit` or `offset` that is not a valid integer, or that falls outside its permitted bounds, on a list endpoint is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order, with creation order (the order in which the resources were minted) as the tiebreaker when two `created_at` timestamps are equal — for example under a frozen test clock. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system — sites, stalls, drivers, eMSPs, tariffs, reservations, charging sessions, settlement batches, settlement line items, and load-allocation snapshots — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification. The `version` field is an integer that begins at its initial value of `1` when the resource is created and increments by one on every mutation of that resource; it is the basis for optimistic concurrency control described in §2.9.

One resource is deliberately immutable after creation: a `MeterEvent`, the OCPP meter sample, carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because a meter reading, once recorded, is never modified.

Whenever a derived or computed field changes as a side effect of some operation — for example a site's `allocated_total_kw`, a driver's `wallet_balance_cents`, or an eMSP's `receivable_balance_cents` — that change is a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations in this domain do not touch a single resource in isolation; they ripple across the stall–session–site graph. The system applies every such cascade immediately and synchronously within the triggering request, and each affected resource independently records the mutation by refreshing its `updated_at` and incrementing its `version`.

The deepest cascade originates at a stall. When a `StationController` reports a station as faulted and a stall moves to `FAULTED` while one of its sessions is in `PREPARING`, `CHARGING`, or `SUSPENDED`, the system forces that session's `charging_status` to `SUSPENDED`, sets the session's `allocated_power_kw` to 0, and then re-runs the site load-balance computation with a trigger reason of `SESSION_SUSPEND` so the freed power flows to the remaining charging sessions — a three-level chain from stall to session to site. Settlement cascades run two levels deep, from a batch down to its line items and then onward to each line item's underlying session, as detailed in §3.7. In every case the secondary effects are as much a part of the contract as the primary state change; an implementation that performs the headline transition but skips a downstream recompute is incorrect.

### 2.6. Nested Resource Retrieval and Existence Checks

Several endpoints address resources nested beneath a parent — a site's stalls, a site's tariffs, a site's load-allocation snapshots, a session's meter events, a batch's line items. For any request, every identifier referenced in the path or body — `site_id`, `stall_id`, `driver_id`, `tariff_id`, `reservation_id`, `session_id`, `batch_id`, or `emsp_id` — must reference an existing resource, and these are validated left to right. The first identifier that does not resolve causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any later identifier or business rule is evaluated.

### 2.7. Validation Order

When a single endpoint is guarded by several checks, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: first, authentication — the presence of valid `X-User-ID` and `X-User-Role` headers naming a known role (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, existence of every referenced identifier, left to right (`ERR_NOT_FOUND`); fourth, resource ownership for an entity-backed `Driver` acting on a session or reservation it does not own (`ERR_FORBIDDEN`); fifth, request-body schema conformance — required fields present, types valid, and enum values within their declared sets (`ERR_INVALID_REQUEST`); and sixth, for any state-transition endpoint, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Domain-specific business checks — stall availability, reservation windows, connector matching, tariff windows, meter monotonicity, settleability, wallet sufficiency, empty-batch locking, and stale-version rejection — are evaluated after these six and are described alongside the workflows they guard in §3.

### 2.8. Monetary Precision and Rounding

All monetary amounts are integer cents. Where a calculation produces a fractional cent before it is stored — for example a commission derived from a percentage, or a tiered energy cost — the result is rounded half up to a whole cent. Energy quantities in kilowatt-hours are kept to three decimal places before the final cents rounding is applied. Power allocations in kilowatts are expressed to one decimal place, as described in §3.4.

### 2.9. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's last-observed `version`. These are the only two endpoints that take a version field; no other endpoint accepts or requires one.

The first is reservation creation. A request to create a reservation must carry `expected_stall_version`, and its value must equal the target stall's current `version`. If another writer has advanced the stall's version since the client last read it — for instance by creating a reservation that legitimately occupies an overlapping window on the same stall — the client's view of stall availability is stale, and the create is rejected with `ERR_STALE_VERSION` at HTTP 412.

The second is batch settlement. A request to settle a settlement batch must carry `expected_settlementbatch_version`, and its value must equal the target batch's current `version`. If another writer has added or reversed a line item since the client last read the batch — advancing the batch's version and changing its total — the client's view of the settlement total is stale, and the settle is rejected with `ERR_STALE_VERSION` at HTTP 412.

## 3. Business Logic & Workflows

### 3.1. Sites, Stalls, and the Physical Estate

A `CPOOperator` lays out the physical network by first creating a **Site**. A site is created with a human-readable `name`, which must be non-empty, and a `circuit_limit_kw` greater than zero that represents the total grid circuit power budget shared by every stall at the site. The operator also supplies a `demand_charge_threshold_kw`, the breakpoint used for demand-charge avoidance; it must be greater than zero and may not exceed `circuit_limit_kw`, and a request that supplies a threshold larger than the circuit limit is rejected with `ERR_OVER_CIRCUIT_LIMIT`. Two optional inputs round out the site: `allocation_policy`, the load-balancing variant selector, which is one of `PROPORTIONAL` or `PRIORITY` and defaults to `PROPORTIONAL`; and `demand_avoidance_armed`, a boolean defaulting to false that, when true, makes the load balancer cap aggregate allocation at `demand_charge_threshold_kw` instead of `circuit_limit_kw`. A site also exposes two computed read-only fields: `allocated_total_kw`, the sum of `allocated_power_kw` across the site's sessions whose `charging_status` is `CHARGING`, recomputed on every load-balance run; and `active_session_count`, the number of the site's sessions whose `charging_status` is one of `PREPARING`, `CHARGING`, or `SUSPENDED`. Fetching a site returns these computed values alongside the inputs.

Under a site, the operator creates **Stalls**. A stall is created with the owning `site_id`, a `connector_type` that is one of `CCS`, `CHADEMO`, `J1772`, or `NACS`, and a `max_power_kw` greater than zero that is the hardware power ceiling of that stall. An optional `reservation_priority` integer, defaulting to 100 and required to be at least 1, ranks the stall in the `PRIORITY` allocation waterfall — a lower number means higher priority. Each stall also carries an OCPP-reported posture in its `ocpp_status` field, which is one of `AVAILABLE`, `OCCUPIED`, `FAULTED`, or `UNAVAILABLE` and starts at `AVAILABLE`.

A stall's posture is cyclic and driven mostly by telemetry. When a session is created on a stall, the stall moves `AVAILABLE → OCCUPIED`. When that session finishes or is aborted, the system returns the stall `OCCUPIED → AVAILABLE`. Separately, a `StationController` posts OCPP status notifications, each carrying a `reported_status`, that drive the stall directly. A station reporting a fault (`reported_status` of `FAULTED`) while the stall is `AVAILABLE` or `OCCUPIED` moves it to `FAULTED`; a station reporting `AVAILABLE` while the stall is `FAULTED` recovers it `FAULTED → AVAILABLE`; and a station reporting `UNAVAILABLE` can take an `AVAILABLE` stall out of service, moving it `AVAILABLE → UNAVAILABLE`. Any other reported posture from the current state — including a `reported_status` of `OCCUPIED`, which is system-driven by session create/finish and is never an accepted StatusNotification transition — is rejected with `ERR_INVALID_STATE`. The fault transition is the cascade root described in §2.5: if a session on the faulting stall is mid-flight, that session is forced to `SUSPENDED`, its power is released, and the site rebalances. Every one of these posture changes increments the stall's `version`.

### 3.2. Drivers, Wallets, and Roaming Partners

A `CPOOperator` registers a **Driver** with an `email` that must be unique and non-empty, a `full_name` display name, and a `home_emsp_id` naming the e-mobility service provider that bills the driver when roaming; a registration whose `email` duplicates an existing driver's is rejected with `ERR_INVALID_REQUEST`. The `home_emsp_id` must reference an existing eMSP, validated for existence as a referenced identifier (`ERR_NOT_FOUND`). A driver carries a prepaid `wallet_balance_cents`, a system-managed integer starting at 0 that is debited whenever one of the driver's home (non-roaming) sessions is rated. The operator may top up or correct a wallet directly by submitting an `amount_cents` adjustment, which may be positive or negative; the adjustment increments `wallet_balance_cents`, but any adjustment that would drive the balance below zero is rejected with `ERR_NEGATIVE_WALLET`.

The operator also registers the roaming partners themselves. An **eMSP** is created with a `name` that must be non-empty and a `commission_pct` — the share of each roaming session's cost the CPO retains before remitting the remainder to the partner — which must be at least 0 and strictly less than 1. Each eMSP carries a computed `receivable_balance_cents`: the net amount, in cents, the eMSP currently owes the CPO, equal to the sum of `net_amount_cents` across the eMSP's line items whose `status` is `PENDING` (those still in an open or locked batch). It is increased by a line item's net on add, decreased by the batch total on settle (collected), and decreased by a reversed line item's net on reopen, so settled and reversed line items contribute nothing; it is recomputed whenever a line item is added, settled, or reversed.

### 3.3. Tariffs and the Two Pricing Modes

Pricing is governed by **Tariffs**, each created by a `CPOOperator` for a specific `site_id` and `connector_type` (again one of `CCS`, `CHADEMO`, `J1772`, or `NACS`). A tariff declares a `pricing_mode` of either `ENERGY_BASED` or `TIME_BASED`, which selects the cost variant for any session priced by it. An optional flat `session_fee_cents` connection fee, defaulting to 0 and required to be at least 0, is added to every session under the tariff regardless of mode.

For energy pricing, a tariff defines three tiers. The `energy_tier_1_max_kwh` is the upper bound in kWh of the first tier and must be greater than zero; `energy_tier_2_max_kwh` is the upper bound of the second tier and must be strictly greater than `energy_tier_1_max_kwh`, with the third tier covering everything above it. Each tier has a per-kWh rate in cents, each at least 0: `energy_rate_t1_cents`, `energy_rate_t2_cents`, and `energy_rate_t3_cents`. For time pricing, the tariff defines `time_rate_cents_per_min`, the per-charging-minute rate in cents, at least 0. Independently of mode, two fields govern idle occupancy: `idle_grace_minutes`, the number of post-charge idle minutes allowed before an idle fee accrues, defaulting to 0 and at least 0; and `idle_fee_cents_per_min`, the per-minute idle fee charged for idle minutes strictly beyond the grace, defaulting to 0 and at least 0.

A tariff is bounded by an effective window: `effective_from` is the inclusive start and `effective_to` is the inclusive end, which must be greater than or equal to `effective_from`. If a tariff is submitted with `energy_tier_2_max_kwh` less than or equal to `energy_tier_1_max_kwh`, or with `effective_to` earlier than `effective_from`, the request is rejected with `ERR_TARIFF_INVALID_TIERS`. Furthermore, no two tariffs for the same `site_id` and `connector_type` combination may have overlapping effective windows; the interval is treated as closed, so windows that merely touch at an endpoint are permitted, but any genuine overlap is rejected with `ERR_TARIFF_WINDOW_OVERLAP`.

### 3.4. Dynamic Load Balancing and Demand-Charge Avoidance

Every site continuously rations its circuit budget among the sessions that are actively charging. A load-balance run is triggered whenever a session begins charging, suspends, or stops, whenever a faulting stall forces a session to suspend, and whenever an operator manually requests a rebalance. Each run produces a **LoadAllocation** snapshot recording the `site_id` it covers, the `trigger_reason` (one of `SESSION_START`, `SESSION_STOP`, `SESSION_SUSPEND`, or `MANUAL_REBALANCE`), the `policy_used` (`PROPORTIONAL` or `PRIORITY`), the ceiling `cap_kw` enforced for the run, the `allocated_total_kw` actually distributed, and the `session_count` of charging sessions that received an allocation.

The run begins by choosing the cap: it is the site's `demand_charge_threshold_kw` when `demand_avoidance_armed` is true, and the site's `circuit_limit_kw` otherwise. The candidate set is exactly the site's sessions whose `charging_status` is `CHARGING`; sessions that are preparing, suspended, or terminal are excluded. Each candidate requests the smaller of its stall's `max_power_kw` and the cap. Let the sum of all candidate requests be the total demand.

Under the `PROPORTIONAL` policy, if the total demand is less than or equal to the cap, every candidate receives its full request. Otherwise the cap is split pro rata: each candidate's raw share is the cap multiplied by that candidate's request divided by the total demand, and each raw share is then truncated downward to a whole multiple of 0.1 kW. Truncation leaves a leftover equal to the cap minus the sum of the truncated allocations; this leftover is handed out in 0.1 kW units to candidates ordered first by ascending stall `reservation_priority`, then by ascending `created_at`, then by ascending creation order — distributed one 0.1 kW unit at a time in repeated passes over that ordered list, skipping any candidate whose allocation has already reached its own request, and stopping once the leftover is exhausted or no candidate can still accept a unit. Under the `PRIORITY` policy the cap is filled by a strict waterfall: candidates are sorted by ascending stall `reservation_priority` and then ascending `created_at`, and each in turn is granted the smaller of its request and the power still remaining, with the remaining budget reduced by each grant. A lower-priority candidate may therefore receive zero kilowatts for an input set under which it would have received a positive proportional share. Under either policy the sum of the allocations never exceeds the cap, and every allocation is expressed to one decimal place of a kilowatt.

The result of a run is written back to the participating sessions as their `allocated_power_kw` — which is zero for any session not currently charging — and the site's `allocated_total_kw` is recomputed accordingly. A manual rebalance returns the resulting snapshot to the operator, and an operator can list a site's historical snapshots.

### 3.5. Reservations: Holding a Stall

A `Driver` may reserve a stall ahead of arrival. Creating a **Reservation** requires the `stall_id` of the stall to hold, the `driver_id` of the reserving driver, a `window_start` marking the inclusive start of the hold window, and a `window_end` marking the exclusive end, which must be strictly after `window_start`. An optional `hold_fee_cents` deposit, defaulting to 0 and at least 0, is charged on confirmation, refunded if the reservation is consumed, and forfeited on a no-show. Because reservation creation contends with other writers for stall availability, it is the optimistic-concurrency endpoint of §2.9: the request must carry `expected_stall_version`, and a mismatch with the stall's current `version` is rejected with `ERR_STALE_VERSION` at HTTP 412. A reservation tracks its lifecycle in its `status` field, one of `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, `CONSUMED`, `NO_SHOW`, `CANCELLED`, or `EXPIRED`, starting at `REQUESTED`.

The reservation lifecycle forks. From `REQUESTED`, the driver confirms the hold, moving it `REQUESTED → CONFIRMED`; confirmation charges the deposit by debiting the driver's `wallet_balance_cents` by `hold_fee_cents` and increments the reservation's `version`. Confirmation is blocked if another `CONFIRMED` or `CHECKED_IN` reservation already holds the same stall over a window that collides within the turnaround buffer: the windows are treated as half-open from start up to end, each extended at its tail end by a fixed reservation buffer of 15 minutes, and two reservations collide when this reservation's `window_start` is strictly before the other's buffer-extended `window_end` and the other's `window_start` is strictly before this reservation's buffer-extended `window_end`, so that windows separated by at least the buffer do not collide; a collision is rejected with `ERR_RESERVATION_OVERLAP`. This overlap check is evaluated before the deposit charge: only once it passes does the deposit debit proceed, and if that debit would drive the driver's `wallet_balance_cents` below zero the confirmation is rejected with `ERR_INSUFFICIENT_WALLET_HOLD`. From `CONFIRMED`, the driver checks in, moving the reservation `CONFIRMED → CHECKED_IN`; check-in is permitted only when the current clock lies within the window from `window_start` up to but not including `window_end`, and only when the stall's `ocpp_status` is `AVAILABLE` or `OCCUPIED`. A check-in attempted outside that window is rejected with `ERR_RESERVATION_WINDOW_CLOSED`.

The two terminal branches diverge in their financial effect. When a checked-in reservation's session completes, the system carries the reservation `CHECKED_IN → CONSUMED` and refunds the deposit by crediting the driver's `wallet_balance_cents` by `hold_fee_cents` — branch A, the fulfilled path. If instead the clock reaches or passes `window_end` (current clock greater than or equal to `window_end`) while the reservation is still `CONFIRMED` with no check-in, the system carries it `CONFIRMED → NO_SHOW`, and the deposit is forfeited: the wallet was already debited at confirmation and is deliberately not credited back — branch B, the no-show path, whose side-effect set is the mirror image of the consumed path. A driver may also cancel: cancelling a `REQUESTED` reservation moves it `REQUESTED → CANCELLED` with no fee movement, because the hold was never charged, while cancelling a `CONFIRMED` reservation moves it `CONFIRMED → CANCELLED` and refunds the already-charged deposit by crediting `wallet_balance_cents` by `hold_fee_cents`; both cancellations increment the reservation's `version`. Finally, if the clock passes `window_start` (current clock strictly greater than `window_start`) while the reservation is still `REQUESTED` and was never confirmed, the system expires it `REQUESTED → EXPIRED` with no fee movement; at the exact `window_start` instant the reservation is not yet expired and may still be confirmed.

### 3.6. The Charging Session: Two Independent Dimensions

A charging session is the heart of the system, and it carries two independent state dimensions. The physical `charging_status` is one of `PREPARING`, `CHARGING`, `SUSPENDED`, `FINISHING`, `COMPLETED`, or `ABORTED`, starting at `PREPARING`. The financial `billing_status` is one of `UNBILLED`, `RATED`, `SETTLED`, or `REVERSED`, starting at `UNBILLED`, and it evolves independently of the physical dimension.

**Starting a session.** A `Driver` or a `StationController` starts a session on a stall by supplying the `stall_id` and the `driver_id`, optionally a `reservation_id` that the session honors (null for walk-up sessions), and an optional `is_roaming` boolean defaulting to false. Starting requires the target stall's `ocpp_status` to be `AVAILABLE`; a start against a stall in any other posture is rejected with `ERR_STALL_NOT_AVAILABLE`. On a successful start, the system resolves the session's `tariff_id` by finding the tariff matching the stall's `site_id` and `connector_type` whose effective window — inclusive of both `effective_from` and `effective_to` — contains the session start clock; should more than one tariff match (possible only at a shared touching endpoint instant), the one with the earliest `created_at`, and then the earliest creation order, is chosen. If no such tariff exists the start is rejected with `ERR_NO_ACTIVE_TARIFF`, and if the stall's `connector_type` does not match the resolved tariff's connector the start is rejected with `ERR_CONNECTOR_MISMATCH`. When `is_roaming` is true, the session's `emsp_id` is set from the driver's `home_emsp_id`; for home sessions it stays null. Starting marks the stall `AVAILABLE → OCCUPIED`, increments the stall's `version`, and leaves the session in `PREPARING`.

**Metering.** A `StationController` posts OCPP meter samples against a session as **MeterEvents**, each carrying the `session_id`, a cumulative lifetime `meter_kwh` reading that must be at least 0 and monotonically non-decreasing within the session, a `sampled_at` OCPP timestamp, and a `reading_context` of `TRANSACTION_BEGIN`, `SAMPLE_PERIODIC`, or `TRANSACTION_END`. A `meter_kwh` below 0 is rejected with `ERR_INVALID_REQUEST` as a body-validation failure, while a reading below the session's prior (most recent) reading — a reading equal to the prior is permitted — is rejected with `ERR_METER_REGRESSION`. Each accepted sample recomputes the session's `energy_delivered_kwh`, which is the latest recorded meter reading minus the session's starting meter reading (the `meter_kwh` of the session's first recorded meter event), and posting a meter event refreshes the session's `updated_at` and increments its `version`.

**Charging and suspending.** A `StationController` begins charging, which advances the session `PREPARING → CHARGING`; this transition requires the session's `charging_status` to be `PREPARING`, the stall's `ocpp_status` to be `OCCUPIED`, and a `TRANSACTION_BEGIN` meter event to already exist for the session. Beginning charging sets the session's `allocated_power_kw` via a site load-balance run with trigger reason `SESSION_START`, recomputes the site's `allocated_total_kw` and `active_session_count`, creates a load-allocation snapshot, and increments the session's `version`. A station may suspend an actively charging session, advancing it `CHARGING → SUSPENDED`; suspension sets `allocated_power_kw` to 0, re-runs load balancing with trigger reason `SESSION_SUSPEND` so the freed power is redistributed to the remaining charging sessions, recomputes the site's `allocated_total_kw`, begins accruing idle time, and increments the session's `version`. The same begin-charging action resumes a suspended session, advancing it `SUSPENDED → CHARGING`; resuming requires the session to be `SUSPENDED` and the stall to be `OCCUPIED`, stops the idle accrual by freezing `idle_minutes` at the elapsed whole minutes spent suspended, re-runs load balancing with trigger reason `SESSION_START`, and increments the session's `version`.

**Stopping.** A `Driver` or `StationController` stops a session. A stop is defined from either `CHARGING` or `SUSPENDED` and requires a `TRANSACTION_END` meter event to exist for the session; it advances the physical dimension to `FINISHING`. The stop computes the session's three measured quantities — `energy_delivered_kwh`, `charging_minutes` (the whole minutes spent in `CHARGING`, start to stop, excluding suspended idle minutes), and `idle_minutes` (the whole minutes spent in `SUSPENDED` before the stop) — sets `allocated_power_kw` to 0, and re-runs site load balancing with trigger reason `SESSION_STOP` over the remaining charging sessions. Within the same request the physical dimension auto-advances `FINISHING → COMPLETED`. That completion drives the financial dimension `UNBILLED → RATED`: the session-cost calculation of §3.8 sets `total_cost_cents` and `idle_fee_cents`. For a home session (`is_roaming` false) the driver's `wallet_balance_cents` is debited by `total_cost_cents`; the wallet sufficiency is checked before that debit and before the `FINISHING → COMPLETED` and `UNBILLED → RATED` transitions are committed, so if the debit would drive the wallet below zero the rating is rejected with `ERR_INSUFFICIENT_WALLET` and neither the wallet debit, the `COMPLETED`/`RATED` transitions, nor the reservation-consume and stall-release effects below take place. Roaming sessions (`is_roaming` true) are never wallet-debited at rating and so are never subject to this check. If the session honored a reservation that is `CHECKED_IN`, that reservation is carried to `CONSUMED` (with the deposit refund of §3.5). Finally the stall is returned to `AVAILABLE` (`OCCUPIED → AVAILABLE`).

**Aborting.** Before any power flows, a `Driver` or `StationController` may abort a `PREPARING` session, advancing it `PREPARING → ABORTED`; aborting returns the stall to `AVAILABLE`, rates no cost so `billing_status` stays `UNBILLED`, and increments the session's `version`.

**Cost preview.** A computed read previews the session cost and idle fee for the current meter state without rating the session, exposing what `total_cost_cents` and the idle-occupancy fee would be if the session stopped now. The preview returns the full session resource object (the same shape as fetching the session), with its `total_cost_cents` and `idle_fee_cents` fields replaced by the previewed values; it does not persist these values onto the session, mutate the session's `updated_at`/`version`, or change its `billing_status`. The previewed minutes include any time elapsed in the currently-running charging or suspended dimension up to the current clock.

The session also exposes the resolved `tariff_id`, the optional `reservation_id` and `emsp_id`, the `is_roaming` flag, and the computed `allocated_power_kw` (which is zero unless the session is `CHARGING`). Sessions can be listed and filtered by `driver_id`, `stall_id`, `reservation_id`, `tariff_id`, or `emsp_id`.

### 3.7. Roaming Settlement

Roaming sessions are reconciled with their eMSP through **Settlement Batches**. A `CPOOperator` opens a batch for a given `emsp_id`; the batch tracks its `status` (one of `OPEN`, `LOCKED`, `SETTLED`, or `DISPUTED`, starting at `OPEN`), a computed `line_item_count`, and a computed `total_amount_cents`.

Into an open batch the operator adds **Settlement Line Items**, each referencing a `batch_id` and the `session_id` being settled. The batch must be `OPEN`; an attempt to add a line item to a batch in any other status is rejected with `ERR_INVALID_STATE`, evaluated before the settleability and duplicate checks below. A line item may be added only for a session whose `billing_status` is `RATED`, whose `is_roaming` is true, and whose `emsp_id` matches the batch's `emsp_id`, and the session must not already appear in another line item; a session that fails any of the settleability conditions is rejected with `ERR_SESSION_NOT_SETTLEABLE`, and a session that already appears in a non-reversed line item is rejected with `ERR_DUPLICATE_LINE_ITEM`, with the settleability check evaluated before the duplicate check. On add, the line item copies the session's `total_cost_cents` into `gross_amount_cents`, computes `commission_cents` as the gross multiplied by the eMSP's `commission_pct` rounded half up to whole cents, and derives `net_amount_cents` as the gross minus the commission — the amount remitted to the eMSP. Adding a line item recomputes the batch's `total_amount_cents` and `line_item_count` and increments the eMSP's `receivable_balance_cents` by the line item's `net_amount_cents`. A line item tracks its own `status`, one of `PENDING`, `SETTLED`, or `REVERSED`, starting at `PENDING`. Line items can be fetched individually, listed within their batch, and listed across batches filtered by `session_id`.

The batch lifecycle is linear with a revert loop. The operator locks a batch, moving it `OPEN → LOCKED`; locking requires the batch to be `OPEN` and to hold at least one line item — an attempt to lock a batch with zero line items is rejected with `ERR_EMPTY_BATCH` — and it freezes `total_amount_cents` by recomputing the round-then-sum of member net amounts described in §3.8, then increments the batch's `version`. From `LOCKED` the operator settles the batch, moving it `LOCKED → SETTLED` under the optimistic-concurrency rule of §2.9 (the request must carry `expected_settlementbatch_version` matching the batch's current `version`, else `ERR_STALE_VERSION` at HTTP 412). Settling cascades two levels: each member line item moves `PENDING → SETTLED`, and each of those line items' sessions has its `billing_status` carried `RATED → SETTLED`; the eMSP's `receivable_balance_cents` is decremented by `total_amount_cents` because the receivable has now been collected; and the batch's `version` increments.

A locked batch can instead be disputed, moving it `LOCKED → DISPUTED` and incrementing its `version`, with no other effect. A disputed batch is reopened back to `OPEN`: reopening reverses every line item still `PENDING`, moving each `PENDING → REVERSED` and carrying each reversed line item's session `billing_status` `RATED → REVERSED`; the eMSP's `receivable_balance_cents` is decremented by each reversed line item's `net_amount_cents` so the receivable returns exactly to its pre-add value with no drift; `total_amount_cents` and `line_item_count` are recomputed over the remaining pending and settled line items; and the batch's `version` increments. The same compensation also governs the session billing dimension directly: a session whose line item moves `PENDING → SETTLED` carries `billing_status` `RATED → SETTLED`, and a session whose line item moves `PENDING → REVERSED` carries `billing_status` `RATED → REVERSED` and decrements the eMSP's `receivable_balance_cents` by that line item's `net_amount_cents`. Settlement batches can be listed and filtered by `emsp_id`.

### 3.8. Pricing Calculations

**Session cost.** At the moment a session is rated (the `UNBILLED → RATED` step inside the stop), its `total_cost_cents` is computed from the resolved tariff, using the variant selected by the tariff's `pricing_mode`. Both variants share two common components. The idle-occupancy fee is computed first: the billable idle minutes equal the session's `idle_minutes` minus the tariff's `idle_grace_minutes`, floored at zero, so that idle minutes equal to the grace produce no fee and the fee applies strictly beyond the grace; the `idle_fee_cents` then equals those billable idle minutes multiplied by `idle_fee_cents_per_min`. The flat `session_fee_cents` is the second shared component.

The variable component depends on the mode. Under `TIME_BASED`, the variable cost is the session's `charging_minutes` multiplied by `time_rate_cents_per_min`, and the energy tiers are ignored entirely. Under `ENERGY_BASED`, the `charging_minutes` are ignored and the energy delivered is priced across the three tiers: let the energy delivered be the session's `energy_delivered_kwh`; the first-tier quantity is the smaller of that energy and `energy_tier_1_max_kwh`; the second-tier quantity is the energy in excess of `energy_tier_1_max_kwh`, floored at zero, but capped at the width of tier two, which is `energy_tier_2_max_kwh` minus `energy_tier_1_max_kwh`; and the third-tier quantity is the energy in excess of `energy_tier_2_max_kwh`, floored at zero. The energy cost is the first-tier quantity times `energy_rate_t1_cents`, plus the second-tier quantity times `energy_rate_t2_cents`, plus the third-tier quantity times `energy_rate_t3_cents`, with that sum rounded half up to whole cents. Because the two modes price the same physical session by different bases, an identical session yields a different total under each mode. The final `total_cost_cents` is the variable cost plus `idle_fee_cents` plus `session_fee_cents`. Kilowatt-hours are kept to three decimal places before the cents rounding.

**Idle-occupancy fee.** The idle fee is also surfaced on its own through the cost-preview read. It is the billable idle minutes — the session's `idle_minutes` minus the tariff's `idle_grace_minutes`, floored at zero — multiplied by `idle_fee_cents_per_min`, in whole cents. The grace is inclusive: when `idle_minutes` is less than or equal to `idle_grace_minutes` the fee is exactly zero, and only when `idle_minutes` strictly exceeds the grace does the fee equal the excess minutes times the per-minute rate.

**Roaming settlement total.** The batch total is computed by a round-then-sum order, and this order is significant. For each line item at add time, the commission is the session's `total_cost_cents` multiplied by the eMSP's `commission_pct` rounded half up to whole cents, and the net is the gross minus that already-rounded commission, so every per-line net is itself a whole-cent integer. The batch's `total_amount_cents` is then the plain integer sum of the net amounts of the batch's line items whose `status` is `PENDING` or `SETTLED`; reversed line items are excluded. This round-then-sum order — rounding each line's commission to whole cents before deriving and summing the nets — can differ by a cent from a sum-then-round order, and the round-then-sum order is the only sanctioned one.

### 3.9. Test-Driving the Clock

Several transitions are time-gated: reservation windows open and close, tariffs become effective and expire, and confirmed reservations turn into no-shows when their windows pass. To make these deterministic under test, an operator-only capability sets the server's current UTC clock to a supplied `to_iso8601` instant; this endpoint returns an empty `data` object rather than a resource. Advancing the clock does not itself mutate any reservation; instead, on the next observation of a reservation, the system may drive a still-`REQUESTED` reservation past its `window_start` to `EXPIRED`, and a still-`CONFIRMED` reservation past its `window_end` to `NO_SHOW`. An observation occurs when a reservation is fetched (single or list) or when a confirm or cancel action runs against it. The check-in action is deliberately exempt: it does not apply this lazy no-show transition first, so a past-window check-in is rejected with `ERR_RESERVATION_WINDOW_CLOSED` rather than being treated as a no-show.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions and computed reads, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/sites` | Create a charging site with a power budget and load-balancing policy | CPOOperator |
| GET | `/api/sites/{id}` | Fetch a site with computed allocation and active-session counts | CPOOperator, Driver, StationController |
| GET | `/api/sites` | List sites | CPOOperator, Driver |
| POST | `/api/sites/{id}/rebalance` | Manually re-run dynamic load balancing for the site | CPOOperator |
| GET | `/api/sites/{id}/load-allocations` | List the site's load-allocation snapshots | CPOOperator |
| GET | `/api/sites/{id}/stalls` | List stalls under a site | CPOOperator, Driver, StationController |
| GET | `/api/sites/{id}/tariffs` | List tariffs for a site, optionally filterable by `connector_type` | CPOOperator, Driver |
| POST | `/api/stalls` | Create a stall under a site | CPOOperator |
| GET | `/api/stalls/{id}` | Fetch a stall | CPOOperator, Driver, StationController |
| POST | `/api/stalls/{id}/ocpp-status` | Post an OCPP StatusNotification; drives stall posture | StationController |
| POST | `/api/drivers` | Register a driver with a home eMSP and wallet | CPOOperator |
| GET | `/api/drivers/{id}` | Fetch a driver with wallet balance | CPOOperator, Driver |
| GET | `/api/drivers` | List drivers, filterable by home eMSP | CPOOperator |
| POST | `/api/drivers/{id}/wallet/adjustments` | Credit or debit a driver's prepaid wallet | CPOOperator |
| POST | `/api/emsps` | Register a roaming e-mobility service provider | CPOOperator |
| GET | `/api/emsps/{id}` | Fetch an eMSP with computed receivable balance | CPOOperator |
| POST | `/api/tariffs` | Create a tariff for a site and connector with an effective window | CPOOperator |
| GET | `/api/tariffs/{id}` | Fetch a tariff | CPOOperator, Driver |
| POST | `/api/reservations` | Request a stall reservation for a window | Driver |
| GET | `/api/reservations/{id}` | Fetch a reservation | CPOOperator, Driver |
| GET | `/api/reservations` | List reservations, filterable by stall or driver | CPOOperator, Driver |
| POST | `/api/reservations/{id}/confirm` | Confirm a requested reservation; charges hold fee | Driver |
| POST | `/api/reservations/{id}/check-in` | Check in within the reservation window | Driver |
| POST | `/api/reservations/{id}/cancel` | Cancel a requested or confirmed reservation | Driver |
| POST | `/api/sessions` | Start a charging session on a stall | Driver, StationController |
| GET | `/api/sessions/{id}` | Fetch a session with computed energy, minutes, and cost | CPOOperator, Driver, StationController |
| GET | `/api/sessions` | List charging sessions, filterable by driver, stall, reservation, tariff, or eMSP | CPOOperator, Driver, StationController |
| POST | `/api/sessions/{id}/meter-events` | Post an OCPP MeterValues sample; enforces monotonic meter | StationController |
| GET | `/api/sessions/{id}/meter-events` | List a session's meter events | CPOOperator, Driver, StationController |
| POST | `/api/sessions/{id}/begin-charging` | Start or resume charging; runs load balancing | StationController |
| POST | `/api/sessions/{id}/suspend` | Suspend charging; frees power and redistributes | StationController |
| POST | `/api/sessions/{id}/stop` | Stop the session; computes cost and rates it | Driver, StationController |
| POST | `/api/sessions/{id}/abort` | Abort a preparing session; releases the stall, no cost | Driver, StationController |
| GET | `/api/sessions/{id}/cost-preview` | Preview the session cost and idle fee without rating | CPOOperator, Driver, StationController |
| POST | `/api/settlement-batches` | Open a settlement batch for an eMSP | CPOOperator |
| GET | `/api/settlement-batches/{id}` | Fetch a settlement batch with computed total | CPOOperator |
| GET | `/api/settlement-batches` | List settlement batches, filterable by eMSP | CPOOperator |
| POST | `/api/settlement-batches/{id}/line-items` | Add a rated roaming session to the batch | CPOOperator |
| GET | `/api/settlement-batches/{id}/line-items` | List a batch's line items | CPOOperator |
| GET | `/api/settlement-line-items` | List settlement line items, filterable by session | CPOOperator |
| GET | `/api/settlement-line-items/{id}` | Fetch a single settlement line item | CPOOperator |
| POST | `/api/settlement-batches/{id}/lock` | Lock a non-empty open batch; freezes the total | CPOOperator |
| POST | `/api/settlement-batches/{id}/settle` | Settle a locked batch; cascades line items and sessions | CPOOperator |
| POST | `/api/settlement-batches/{id}/dispute` | Mark a locked batch disputed | CPOOperator |
| POST | `/api/settlement-batches/{id}/reopen` | Reopen a disputed batch; reverses outstanding line items | CPOOperator |
| POST | `/api/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | CPOOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALL_NOT_AVAILABLE` | 409 |
| `ERR_RESERVATION_WINDOW_CLOSED` | 409 |
| `ERR_CONNECTOR_MISMATCH` | 409 |
| `ERR_TARIFF_WINDOW_OVERLAP` | 409 |
| `ERR_RESERVATION_OVERLAP` | 409 |
| `ERR_NO_ACTIVE_TARIFF` | 409 |
| `ERR_METER_REGRESSION` | 409 |
| `ERR_SESSION_NOT_SETTLEABLE` | 409 |
| `ERR_INSUFFICIENT_WALLET` | 402 |
| `ERR_INSUFFICIENT_WALLET_HOLD` | 402 |
| `ERR_EMPTY_BATCH` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NEGATIVE_WALLET` | 402 |
| `ERR_DUPLICATE_LINE_ITEM` | 409 |
| `ERR_TARIFF_INVALID_TIERS` | 422 |
| `ERR_OVER_CIRCUIT_LIMIT` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
