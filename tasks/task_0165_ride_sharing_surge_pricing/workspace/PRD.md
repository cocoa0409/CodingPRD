# Ride-Sharing Surge Pricing API — Product Requirements Document

## 1. Introduction

This document specifies the contract for a ride-sharing platform's dynamic surge pricing and dispatch backbone. The system has to keep three populations honest at the same time: riders, who want a predictable fare quoted before they confirm a trip; drivers, who want a clear path to higher earnings during high-demand intervals and a fair shot at airport pickups; and the platform operator, who has to keep supply and demand roughly in balance across a citywide grid without letting the surge multiplier run away during outages or rush hour.

Three numerical objects do most of the work. A geographic grid carries a live supply-and-demand-derived multiplier that is recomputed on every event that changes either side of the ratio. Each ride pins one quoted fare at request time and computes a second, chronological fare at completion — and the divergence between those two fares is what makes the dispute and refund flow non-trivial. A driver Quest is a deferred reward whose payout is settled only when the quest window closes and the platform's logical clock crosses the boundary. The remainder of this document defines the entities, transitions, and arithmetic that bind these objects together.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, indicating the principal's operational capacity. If either header is missing or malformed, the request is rejected with `ERR_AUTH_MISSING`. If the header is present and well-formed but the supplied role is not permitted to call the requested endpoint, the response is `ERR_FORBIDDEN`.

Four roles exist, spelled exactly: `Rider`, `Driver`, `PlatformAdmin`, and `DisputeOps`.

When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider` entity; ownership checks on a ride compare the resource's `rider_id` field to `X-User-ID`, and ownership checks on a dispute compare the dispute's `rider_id` field to `X-User-ID`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity; ownership checks on driver-only endpoints compare the path's driver id to `X-User-ID`, and ownership checks on a ride compare the resource's `driver_id` field to `X-User-ID`. A failed ownership check on either role yields `ERR_NOT_OWNER`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The platform may log it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `DisputeOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the platform records it for dispute-resolution audit but performs no entity ownership comparison.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum permitted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set; when omitted it defaults to 0.

Unless an endpoint explicitly states otherwise, list results are ordered by the resource's `created_at` timestamp in ascending order. The four pagination fields surfaced in the `meta` envelope are `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level entities — `GeoGrid`, `Driver`, `Rider`, `RushHourWindow`, `QuestBonus`, `Ride`, and `Dispute` — share a standard system-managed property set:

- `id` (string): a unique, server-minted UUID, free of any type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the last mutation of the resource. Every mutation — explicit `PATCH`, transition-driven side effect, or recomputation of a derived field such as `current_multiplier`, `active_driver_count`, or `open_demand_count` — refreshes `updated_at`.
- `version` (integer): a system-managed monotonic counter that begins at 1 on creation and increments by 1 on every mutation. It is the basis for optimistic concurrency control described in §2.7.

Two entity types deliberately omit `updated_at` and `version`: an `AirportQueue` row carries only `id` and `created_at`; a `HeatMapSnapshot` row likewise carries only `id` and `created_at`. Both are append-only audit-shaped records — the queue position is renumbered by deletion and re-create logic rather than in-place mutation, and a heat-map snapshot is by definition immutable once written.

### 2.5. Surge Multiplier Recomputation

The `current_multiplier` on a `GeoGrid` is a derived field. It is recomputed any time the grid's supply or demand state shifts — that is, on any event that changes its `active_driver_count` or its `open_demand_count`. It is also recomputed in bulk for every grid when the test-driving capability sweeps all surges; that sweep additionally appends one `HeatMapSnapshot` row per grid capturing the grid's `code` (recorded as `grid_code`), its `multiplier`, its `active_driver_count`, and its `open_demand_count` at the snapshot instant under a server-assigned `snapshot_at` timestamp.

The formula proceeds in three steps. **Step 1 — supply/demand ratio.** When the grid has neither an `active_driver_count` greater than zero nor any `open_demand_count`, the raw multiplier is 1.00. When `active_driver_count` is zero but `open_demand_count` is positive, the raw multiplier saturates to the `MULTIPLIER_CAP` of 3.00 (the infinite-demand boundary). Otherwise the ratio is computed as `open_demand_count` divided by `active_driver_count` and bucketed: a ratio less than or equal to 1.0 yields a raw multiplier of 1.00; greater than 1.0 and less than or equal to 2.0 yields 1.50; greater than 2.0 and less than or equal to 3.0 yields 2.00; greater than 3.0 and less than or equal to 4.0 yields 2.50; strictly greater than 4.0 yields the `MULTIPLIER_CAP` of 3.00. **Step 2 — airport surcharge.** If the grid's `is_airport` flag is true, the `AIRPORT_SURCHARGE` of 0.50 is added to the raw multiplier before any cap is applied. **Step 3 — apply cap.** The grid's `current_multiplier` is the minimum of the post-surcharge raw value and the `MULTIPLIER_CAP` of 3.00, rounded half-up to two decimal places. Each recomputation also stamps `last_surge_recomputed_at` to the current server timestamp.

A subtle but load-bearing rule: drivers in the airport queue do **not** contribute to `active_driver_count`. Joining the queue therefore decrements supply on the airport grid by one (and may push the grid's multiplier upward); leaving the queue restores supply by one.

### 2.6. Precision and Rounding

All monetary values are stored as integer cents. Whenever a calculation introduces a fractional cent — multiplying a base fare by a multiplier, or splitting a final fare into a driver share — the result is rounded half-up to a whole integer cent. The two roundings inside the final-fare flow (first the fare, then the driver's earnings) are applied in that fixed order; reversing them can produce a one-cent difference, and the implementation must follow the prescribed order.

All multiplier arithmetic carries two decimal places of precision and likewise uses round half-up. The `current_multiplier` written on a `GeoGrid` is stored to exactly two decimal places.

### 2.7. Optimistic Concurrency Control

`PATCH` endpoints that modify an existing resource accept an optional `version` field in their request body. When `version` is provided, the server compares it against the resource's current `version`; on a mismatch the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server processes the mutation without performing the version check. On every successful mutation the resource's `version` is incremented by 1.

Two concurrent `PATCH` requests modifying the same `GeoGrid` with stale `version` payloads serialize as first-writer-wins on the grid's `version`; the second writer receives `ERR_VERSION_CONFLICT`. The same OCC protection applies to `PATCH /drivers/{id}`, `PATCH /drivers/{id}/quest`, and `PATCH /rush-hour-windows/{id}`.

### 2.8. Nested Resource Retrieval and Existence Checks

Path identifiers are validated strictly left-to-right in their URL order. Whatever the endpoint, the first identifier in the path that does not reference an existing resource yields `ERR_NOT_FOUND` immediately — the server does not continue validating later identifiers. The set of identifiers covered includes `driver_id`, `ride_id`, `dispute_id`, `grid_id`, `quest_id`, and `window_id`.

Foreign-key fields supplied in request bodies — including `rider_id`, `driver_id`, `pickup_grid_code`, `dropoff_grid_code`, and `quest_id` on the create-ride, create-dispute, and patch-driver flows — are validated against the referenced collections. A foreign key that does not resolve produces `ERR_REFERENCE_NOT_FOUND`. This check applies to `POST /rides`, `POST /disputes`, and `PATCH /drivers/{id}`.

### 2.9. Validation Order

Validation runs in a fixed priority. **First**, authentication: missing or malformed headers yield `ERR_AUTH_MISSING`. **Second**, role authorization: a present-but-disallowed role yields `ERR_FORBIDDEN`. **Third**, path-id existence (left-to-right) yields `ERR_NOT_FOUND` on the first miss. **Fourth**, request-body foreign-key existence yields `ERR_REFERENCE_NOT_FOUND`. **Fifth**, driver-side ownership on ride-progress and driver-management endpoints (`POST /rides/{id}/start`, `POST /rides/{id}/complete`, `POST /drivers/{id}/go-online`, `POST /drivers/{id}/go-offline`, `POST /airport-queue/join`, and `POST /airport-queue/leave`) requires the acting `Driver.id` (i.e., `X-User-ID` under role `Driver`) to equal the resource's `driver_id` or the path id, otherwise `ERR_NOT_OWNER`. **Sixth**, rider-side ownership on `POST /rides/{id}/cancel` and on `POST /disputes` requires `X-User-ID` (under role `Rider`) to equal the resource's `rider_id`, otherwise `ERR_NOT_OWNER`. **Seventh**, state preconditions (the target resource must be in a state from which the requested transition is allowed) yield `ERR_INVALID_STATE` on any state-transition endpoint. **Eighth**, on dispute creation, the no-duplicate rule fires next: the underlying `Ride.status` must be `COMPLETED` and no `OPEN` or `APPROVED` dispute may already exist for that ride; failure yields `ERR_DISPUTE_ALREADY_EXISTS`. **Ninth**, on `POST /airport-queue/join` the target grid's `is_airport` flag must be true, otherwise `ERR_NOT_AIRPORT_GRID`. **Tenth**, also on `POST /airport-queue/join`, the joining driver's `current_grid_code` must match the request body's `grid_code`, otherwise `ERR_DRIVER_NOT_IN_GRID`. **Eleventh**, on rush-hour window creation and update the `start_minute` must be strictly less than the `end_minute` and the new window's half-open interval must not intersect any existing active window on the same `day_of_week`; failure yields `ERR_RUSH_HOUR_OVERLAP`. **Twelfth**, on quest creation and on driver quest enrollment, `window_end` must be strictly after `window_start` and no driver may be enrolled in two quests whose closed-closed windows overlap; failure yields `ERR_QUEST_WINDOW_OVERLAP`. **Thirteenth**, on dispute creation, `requested_refund_cents` must be strictly greater than zero and less than or equal to the underlying `Ride.final_fare_cents`, otherwise `ERR_REFUND_EXCEEDS_FARE`. **Fourteenth**, on dispute approve, if `approved_refund_cents` is supplied in the body it must be less than or equal to the dispute's `requested_refund_cents`, otherwise `ERR_REFUND_EXCEEDS_REQUEST`. **Fifteenth**, the optimistic-locking `version` check on `PATCH` endpoints yields `ERR_VERSION_CONFLICT` on mismatch. **Sixteenth**, generic input shape and range validation (e.g., `distance_km` must be strictly greater than zero; a multiplier value submitted in any patch body must be less than or equal to the `MULTIPLIER_CAP`) yields `ERR_INVALID_INPUT`.

The ordering is load-bearing. For example, if a rider sends a duplicate `POST /disputes` with a malformed `requested_refund_cents`, the higher-priority state and uniqueness checks fire before the fiscal validation, so the response is `ERR_DISPUTE_ALREADY_EXISTS` (not `ERR_REFUND_EXCEEDS_FARE`).

### 2.10. Concurrency Guarantees

Beyond the optimistic-locking pattern of §2.7, several specific race conditions are resolved deterministically.

Two concurrent ride-requests in a grid that holds exactly one available driver are both accepted at the creation step; both rides are written in `REQUESTED` state, but only one will progress to `ASSIGNED` (the first request wins the assignment via the driver-selection policy of §3.3). The losing ride remains in `REQUESTED` until a new driver becomes available — no error is returned at creation time.

Two simultaneous attempts to assign the same `REQUESTED` ride serialize as first-writer-wins on the ride's `status` field. Exactly one assigns; the loser receives `ERR_INVALID_STATE` because the ride is no longer in `REQUESTED`. Two simultaneous approve and reject calls on the same `OPEN` dispute serialize the same way on the dispute's `status`: exactly one wins, and the loser receives `ERR_INVALID_STATE`. Two riders trying to file a dispute against the same `COMPLETED` ride at the same time both attempt insertion, but the per-ride uniqueness constraint on disputes lets one through; the loser receives `ERR_DISPUTE_ALREADY_EXISTS`.

Two drivers calling the airport-queue join endpoint on the same airport grid at the same instant both succeed; each receives a distinct sequential `position` because positions are assigned atomically as one plus the current maximum `position` in that grid. FIFO ordering uses `joined_at`, tie-broken by `Driver.id` ascending.

## 3. Business Logic & Workflows

### 3.1. Grids, Heat Maps, and the Live Surge Picture

The geographic grid is the spatial unit of the system. A `PlatformAdmin` provisions one by supplying a grid `code` matching the pattern of the letter `G`, a hyphen, and exactly three digits (e.g., `G-001`), along with a human-readable `name`. Two booleans may also be set at creation: `is_airport`, which is false by default and marks the grid as the airport pickup zone (only one grid is expected, but the schema does not enforce uniqueness), and `rush_hour_eligible`, which is true by default and controls whether rush-hour windows apply to fares quoted or completed there. The `code` is immutable after creation and unique across all grids; only `name` and `rush_hour_eligible` may later be patched, and any such patch triggers a fresh surge recomputation for that grid.

The grid carries three derived numbers at all times: `active_driver_count`, the count of drivers in `AVAILABLE` status whose `current_grid_code` equals this grid's code; `open_demand_count`, the count of rides in `REQUESTED` status whose `pickup_grid_code` equals this grid's code; and `current_multiplier`, the surge factor, derived per §2.5 and constrained to lie between 1.00 and the `MULTIPLIER_CAP` of 3.00 inclusive. The grid also exposes `last_surge_recomputed_at` so consumers can see how stale the multiplier is.

A read-only heat map view is available to all roles via the heat-map capability of the grid resource. It returns, for each grid, the most recent `HeatMapSnapshot` row (descending by `snapshot_at`). A snapshot batch is produced by the admin-only test-driving sweep capability, which forces a fresh surge recomputation for all grids and then writes one snapshot row per grid recording the grid's `code` (under `grid_code`), its post-recomputation `multiplier`, its `active_driver_count`, and its `open_demand_count`.

### 3.2. Driver Lifecycle and the Airport Queue

A driver record is created by a `PlatformAdmin` with just a `name`; the driver starts in `OFFLINE` status, with `current_grid_code` null, `quest_id` null, `quest_completed_rides` at zero, and `total_earnings_cents` at zero. A driver brings themselves online by issuing the go-online action against their own driver id, supplying the target `grid_code` in the body; the transition advances `status` from `OFFLINE` to `AVAILABLE`, sets `current_grid_code` to that `grid_code`, increments the destination grid's `active_driver_count` by 1, and triggers a fresh surge recomputation on that grid. Going offline reverses these effects: from `AVAILABLE`, the driver returns to `OFFLINE`, the grid's `active_driver_count` is decremented by 1, the grid's multiplier is recomputed, and `current_grid_code` is set to null.

The driver lifecycle also encompasses the airport pickup queue. A driver who is `AVAILABLE` and physically located in a grid whose `is_airport` flag is true may join the queue. Three preconditions apply: the driver's current `status` must be `AVAILABLE`; their `current_grid_code` must equal the `grid_code` supplied in the request body and that grid's `is_airport` flag must be true (otherwise `ERR_NOT_AIRPORT_GRID` or `ERR_DRIVER_NOT_IN_GRID`); and the driver must not already be in any airport queue. The transition writes a new `AirportQueue` row whose `position` is one greater than the current maximum `position` in that grid and whose `joined_at` is set to the current server time; the driver's `status` advances to `IN_AIRPORT_QUEUE`; the grid's `active_driver_count` is decremented by one (queued drivers do **not** count toward supply); the grid's surge is recomputed. Leaving the queue voluntarily moves `status` back to `AVAILABLE`, deletes the driver's queue row, re-numbers the remaining rows so that each later `position` decrements by one (preserving the dense, unique 1-indexed ordering), increments the grid's `active_driver_count` by one, and recomputes the grid's surge.

The `Driver` entity carries the following enum values for `status` exactly: `OFFLINE`, `AVAILABLE`, `EN_ROUTE_PICKUP`, `ON_TRIP`, and `IN_AIRPORT_QUEUE`. Transitions into `EN_ROUTE_PICKUP` and `ON_TRIP` are system-driven side effects of ride lifecycle transitions; transitions back out of `ON_TRIP` to `AVAILABLE` are likewise a side effect of completion.

### 3.3. Rider Requests and the Dispatch of a Ride

A `Rider` is provisioned by a `PlatformAdmin` with just a `name` and starts with a `wallet_balance_cents` of zero. The rider initiates a trip by submitting a ride creation payload containing `pickup_grid_code`, `dropoff_grid_code`, and `distance_km` (which must be strictly greater than zero, otherwise `ERR_INVALID_INPUT`). The ride is created in `REQUESTED` status, its `requested_at` is set to the current server timestamp, its `driver_id` is null, its `completed_at` and `final_fare_cents` and `driver_earnings_cents` are all null, and the system runs the `quoted_fare_calculation` immediately.

The `quoted_fare_calculation` is the forward-looking variant of the fare. The base fare in cents is computed as `BASE_FARE_CENTS` (250) plus the `distance_km` multiplied by `PER_KM_CENTS` (120), with the product rounded half-up to an integer cent; that integer is pinned on the ride as `base_fare_cents`. The pickup grid's live `current_multiplier` is read once and pinned on the ride as `pickup_multiplier_snapshot`. The system then scans for the first active `RushHourWindow` whose `day_of_week` equals the day of week of the current server time and whose half-open minute interval (inclusive at `start_minute`, exclusive at `end_minute`) contains the current minute of the day in UTC, provided also that the pickup grid's `rush_hour_eligible` flag is true; if such a window matches, its `additive_bonus` is pinned on the ride as `rush_hour_bonus_snapshot`, otherwise that snapshot is pinned at 0.00. The effective multiplier is the sum of `pickup_multiplier_snapshot` and `rush_hour_bonus_snapshot`, then taken as the minimum of that sum and the `MULTIPLIER_CAP` of 3.00. The `quoted_fare_cents` is the `base_fare_cents` multiplied by that capped effective multiplier, rounded half-up to an integer cent. After creation, the grid's `open_demand_count` is incremented by one and its surge is recomputed.

Cancellation by the rider is allowed from either `REQUESTED` or `ASSIGNED`. The acting rider's id (carried in `X-User-ID` under role `Rider`) must equal the ride's `rider_id`, otherwise `ERR_NOT_OWNER`. Cancellation from `REQUESTED` decrements the pickup grid's `open_demand_count` by 1 and recomputes that grid's surge. Cancellation from `ASSIGNED` is more involved: the previously assigned driver's `status` reverts from `EN_ROUTE_PICKUP` to `AVAILABLE`, the driver's `current_grid_code` is left unchanged (they remained en route — still at their last grid), the active count of that grid is incremented by 1, and that grid's surge is recomputed. If the pickup grid's `is_airport` was true and the driver had just been popped from the head of the airport queue, the driver may explicitly re-join the queue using the join action — re-joining is not automatic.

Assignment is performed by a `PlatformAdmin` and is the bridge between `REQUESTED` and `ASSIGNED`. The state precondition is that the ride is still `REQUESTED` (otherwise `ERR_INVALID_STATE`). The driver-selection policy must be deterministic — every step (eligibility filter, ranking key, tie-break, fallback) is pinned. When the pickup grid's `is_airport` flag is true, the eligible candidate set is the airport-queue rows for that grid, ranked by `position` ascending; the head of the queue is selected (positions are unique within a grid, so no further tie-break is needed). If the airport queue is empty for that grid, the policy falls through to the non-airport branch on the same pickup grid. The non-airport branch's eligible set is drivers whose `status` equals `AVAILABLE` and whose `current_grid_code` equals the ride's `pickup_grid_code`, ranked by `updated_at` ascending (longest-idle first), with ties broken by `Driver.id` ascending; the first candidate in that ranking is selected. If no candidate exists, the request body may include `allow_neighbor_grid` set to true: in that case, the candidate set expands to drivers whose `status` equals `AVAILABLE` and whose `current_grid_code` is lexicographically adjacent to the pickup grid in the sense that the numeric portion of the two grid codes differ by exactly one (so `G-007` is adjacent to `G-006` and `G-008`). If even after the optional neighbor expansion no candidate exists, the assignment is rejected with `ERR_NO_DRIVERS_AVAILABLE`.

The assignment side effects bind the ride and the driver together. The selected driver's id is written to the ride's `driver_id`; the driver's `status` advances to `EN_ROUTE_PICKUP`; the driver's `current_grid_code` is set to the ride's `pickup_grid_code`; the pickup grid's `open_demand_count` is decremented by 1 (the ride is no longer open demand) and its `active_driver_count` is decremented by 1 (the driver is no longer free supply); the surge is recomputed on the pickup grid. If the pickup grid's `is_airport` was true, the selected driver is removed from the airport queue and the remaining queue rows are renumbered so that each later `position` decrements by one.

The driver starts the trip via the role-and-action capability that drives `ASSIGNED` to `ON_TRIP`. The acting driver's id must equal the ride's `driver_id`, otherwise `ERR_NOT_OWNER`; the ride must be in `ASSIGNED`, otherwise `ERR_INVALID_STATE`; the only side effect is that the driver's `status` advances to `ON_TRIP`.

### 3.4. Trip Completion, the Chronological Fare, and Earnings

Completion is the most arithmetically dense transition in the system. The acting driver's id must equal the ride's `driver_id`; the ride must be in `ON_TRIP`. The ride's `completed_at` is stamped to the current server timestamp. Then the `final_fare_calculation` — the chronological variant — runs: the pinned `base_fare_cents` is reused; the pickup grid's `current_multiplier` is **re-read** at the completion instant (not at request time), giving a "live" pickup multiplier; the rush-hour bonus is **re-evaluated** at the completion instant, by scanning active rush-hour windows for the day of week and minute of day at completion, and only if the pickup grid's `rush_hour_eligible` flag is true (a window that was active at request time but has since ended contributes 0.00); the live effective multiplier is the sum of the live pickup multiplier and the live bonus, taken as the minimum of that sum and the `MULTIPLIER_CAP` of 3.00; the ride's `final_fare_cents` is the `base_fare_cents` multiplied by the live effective multiplier, rounded half-up to an integer cent.

This is the forward-looking versus chronological divergence: the same ride may end up with `quoted_fare_cents` different from `final_fare_cents` whenever surge or rush-hour state moved during the trip. Both numbers persist; both are valid; their difference is what the dispute pathway in §3.7 may target.

Earnings follow immediately. The platform's fee rate, `PLATFORM_FEE_RATE`, is 0.20 — that is, the platform keeps twenty percent and the driver receives eighty percent. The ride's `driver_earnings_cents` is the `final_fare_cents` multiplied by the quantity one minus the `PLATFORM_FEE_RATE`, rounded half-up to an integer cent. The two roundings — first the fare, then the earnings — run in that fixed order; reversing them (computing driver earnings directly as base times effective multiplier times one minus fee, then rounding once) can produce a one-cent difference, and the prescribed order is the contract. The driver's lifetime `total_earnings_cents` is incremented by this ride's `driver_earnings_cents`.

The completion also returns the driver to circulation: the driver's `status` reverts from `ON_TRIP` to `AVAILABLE`; the driver's `current_grid_code` is set to the ride's `dropoff_grid_code`; the dropoff grid's `active_driver_count` is incremented by 1, and the dropoff grid's surge is recomputed.

If the driver was enrolled in a quest whose `status` was `ACTIVE` at the completion instant, the driver's `quest_completed_rides` is incremented by 1. If that increment causes `quest_completed_rides` to reach the quest's `target_ride_count`, the quest's `bonus_amount_cents` is held for payout — but it is not credited yet. The bonus is paid out only on the next system-driven transition of the quest from `ACTIVE` to `CLOSED`; see §3.6.

### 3.5. Rush-Hour Windows

A `RushHourWindow` is a recurring per-day-of-week schedule that adds an additive bonus to the surge multiplier when fares are computed. A `PlatformAdmin` creates one with a `label`, a `day_of_week` taken from the exact set `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`, a `start_minute` (inclusive minutes since midnight UTC, between 0 and 1439 inclusive), an `end_minute` (exclusive minutes since midnight UTC, strictly greater than `start_minute` and not exceeding 1440), and an `additive_bonus` (a number at least 0.00 and at most 1.00). Each window also carries an `is_active` flag that defaults to true.

Two windows on the same `day_of_week` may abut but not overlap. The intervals are half-open: a new window whose `start_minute` equals an existing window's `end_minute` is permitted (adjacency at the boundary is allowed), but any genuine intersection rejects the request with `ERR_RUSH_HOUR_OVERLAP`. The same overlap test is re-evaluated when an admin patches an existing window, because a patch that reactivates a previously inert window (flipping `is_active` from false back to true) could reintroduce an interval collision with another active window on the same day.

A rush-hour window's `additive_bonus` is added to the supply-and-demand-derived multiplier **before** the cap is applied (so the bonus does not push the effective ride multiplier above the `MULTIPLIER_CAP` of 3.00). The match itself is conditioned on the pickup grid's `rush_hour_eligible` flag being true; on a grid where that flag is false, the bonus is suppressed regardless of any matching window. Patches to a window may modify `label`, `additive_bonus`, or `is_active`; an `is_active` set to false makes the window inert without deleting the row.

### 3.6. Driver Quests and Deferred Bonus Payout

A `QuestBonus` is a deferred-payout incentive offered to drivers across a defined window. A `PlatformAdmin` creates one with a quest `name`, a `target_ride_count` (at least 1), a `bonus_amount_cents` (at least 0), a `window_start` (inclusive ISO 8601 UTC), and a `window_end` (exclusive ISO 8601 UTC strictly after `window_start`). The quest is created in `SCHEDULED` status, the initial state of its lifecycle. The quest's lifecycle enum has three values exactly: `SCHEDULED`, `ACTIVE`, and `CLOSED`. The terminal state is `CLOSED`.

Quests are time-gated. A quest transitions from `SCHEDULED` to `ACTIVE` automatically when the server clock crosses (reaches or passes) the quest's `window_start`. The transition's only side effect is to set `status` to `ACTIVE`. The clock advance is driven by an admin-only test-driving capability that pushes the logical clock to a supplied `target_timestamp`. A quest transitions from `ACTIVE` to `CLOSED` automatically when the server clock crosses (reaches or passes) the quest's `window_end`. The close transition is where bonus payouts settle: for every driver whose `quest_id` equals the closing quest's id and whose `quest_completed_rides` is greater than or equal to the quest's `target_ride_count`, the driver's `total_earnings_cents` is incremented by the quest's `bonus_amount_cents`. The payout is one-time and idempotent — if the close transition is somehow attempted twice, the payout flag prevents a second credit.

Critically, the aggregate that feeds `quest_completed_rides` counts only rides whose status is `COMPLETED`, whose `driver_id` equals the enrolled driver's id, and whose `completed_at` lies within the right-half-open interval bounded by `window_start` inclusive and `window_end` exclusive. A ride whose `completed_at` coincides exactly with `window_end` is excluded.

A driver enrolls (or unenrolls) in a quest via the patch-driver-quest capability. The body provides a `quest_id`, or null to unenroll. Enrollment is constrained: the driver must not already be enrolled in another quest whose closed-closed window overlaps the new quest's `[window_start, window_end]`. Note that the overlap semantics for quest enrollment differ from rush-hour windows: rush-hour overlap is checked with half-open intervals (adjacency at the boundary minute is fine), but quest enrollment uses fully closed intervals — a quest that starts at exactly the moment another quest ends counts as overlapping. A violation yields `ERR_QUEST_WINDOW_OVERLAP`. The same overlap check applies on quest creation itself, where `window_end` must also be strictly after `window_start`.

### 3.7. Disputes, Refunds, and the Compensating Earnings Adjustment

A `Rider` may file a dispute on a `COMPLETED` ride. The dispute creation payload contains the `ride_id`, the `reason_code` (one of `OVERCHARGE`, `DRIVER_NO_SHOW`, `ROUTE_DEVIATION`, or `OTHER`), and the `requested_refund_cents` (strictly greater than zero and at most the ride's `final_fare_cents`, otherwise `ERR_REFUND_EXCEEDS_FARE`). The acting rider's id must equal the ride's `rider_id`. Each ride may host at most one dispute over its lifetime — an attempt to file a second when an existing `OPEN` or `APPROVED` dispute is already attached yields `ERR_DISPUTE_ALREADY_EXISTS`.

Creating the dispute has cross-entity side effects: a new `Dispute` is written in `OPEN` status with the rider's id copied to the dispute's own `rider_id` field (for ownership checks downstream) and `approved_refund_cents` and `resolved_at` left null; the underlying ride's `status` moves from `COMPLETED` to `DISPUTED`. Filing therefore re-opens a ride that had appeared settled.

A `DisputeOps` operator then either approves or rejects. The state precondition on both is that the dispute's `status` is `OPEN` and the associated ride's `status` is `DISPUTED`; otherwise `ERR_INVALID_STATE`. Approval sets `Dispute.status` to `APPROVED` and writes `approved_refund_cents`: if the request body supplies `approved_refund_cents`, that value is used (it must not exceed the dispute's `requested_refund_cents`, otherwise `ERR_REFUND_EXCEEDS_REQUEST`); if omitted, the approved amount defaults to the dispute's `requested_refund_cents`. In either case, the approved amount is also capped at the ride's `final_fare_cents` as a final guard. Approval then has three further side effects: the rider's `wallet_balance_cents` is incremented by `approved_refund_cents`; the driver's `total_earnings_cents` is decremented by the driver-share equivalent of the refund — that is, the `approved_refund_cents` multiplied by the quantity one minus the `PLATFORM_FEE_RATE`, rounded half-up to an integer cent, clamped so that `total_earnings_cents` never falls below zero (this is the compensating earnings adjustment); the ride's `status` advances from `DISPUTED` to `REFUNDED`; the dispute's `resolved_at` is stamped to the current server time.

Rejection is symmetric in shape but undoes the dispute's claim. The dispute's `status` is set to `REJECTED`, the ride's `status` reverts from `DISPUTED` to `COMPLETED` (the prior state), and the dispute's `resolved_at` is stamped to the current server time. There is no compensating drift on either the rider's `wallet_balance_cents` or the driver's `total_earnings_cents` on rejection.

The combined effect is that a refunded ride takes the underlying ride to `REFUNDED` — a terminal state alongside `COMPLETED` and `CANCELED` — whereas a rejected dispute leaves the ride at `COMPLETED`. The full set of ride lifecycle states is `REQUESTED`, `ASSIGNED`, `ON_TRIP`, `COMPLETED`, `CANCELED`, `DISPUTED`, and `REFUNDED`; of these, `COMPLETED`, `CANCELED`, and `REFUNDED` are terminal in the sense that no further ride-state transitions occur after them (the dispute-driven excursion through `DISPUTED` reaches one of those terminals on resolution).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a grid, a driver, a rider, a rush-hour window, a quest, a ride, an airport-queue join row, or a dispute) return `201 Created`. Operations that modify an existing resource — including all state transitions, patches, the admin-only clock advance, and the surge-recompute sweep — return `200 OK`. Mutating side effects (recomputation of `current_multiplier`, updates to derived counts, transitions of related entities) execute atomically with the primary mutation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grids` | Create a new `GeoGrid`. | PlatformAdmin |
| GET | `/grids` | List all `GeoGrid`s with pagination. | PlatformAdmin, Driver, Rider, DisputeOps |
| GET | `/grids/{id}` | Read a single `GeoGrid` (includes `current_multiplier` and counts). | PlatformAdmin, Driver, Rider, DisputeOps |
| PATCH | `/grids/{id}` | Patch grid metadata (`name`, `rush_hour_eligible`). | PlatformAdmin |
| GET | `/grids/heatmap` | Heat-map view: latest `HeatMapSnapshot` row per `grid_code`. | PlatformAdmin, Driver, Rider, DisputeOps |
| POST | `/drivers` | Create a `Driver` record. | PlatformAdmin |
| GET | `/drivers/{id}` | Read a `Driver`. | PlatformAdmin, Driver |
| PATCH | `/drivers/{id}/quest` | Enroll or unenroll a driver from a `QuestBonus`. | Driver, PlatformAdmin |
| POST | `/drivers/{id}/go-online` | Driver transitions `OFFLINE` to `AVAILABLE` in a specific grid. | Driver |
| POST | `/drivers/{id}/go-offline` | Driver transitions `AVAILABLE` to `OFFLINE`. | Driver |
| POST | `/riders` | Create a `Rider` record. | PlatformAdmin |
| GET | `/riders/{id}` | Read a `Rider`. | PlatformAdmin, Rider |
| POST | `/rush-hour-windows` | Create a `RushHourWindow`. | PlatformAdmin |
| GET | `/rush-hour-windows` | List all `RushHourWindow`s. | PlatformAdmin, Driver, Rider, DisputeOps |
| PATCH | `/rush-hour-windows/{id}` | Patch a `RushHourWindow` (`label`, `is_active`, `additive_bonus`). | PlatformAdmin |
| POST | `/quest-bonuses` | Create a `QuestBonus` (initial `status` is `SCHEDULED`). | PlatformAdmin |
| GET | `/quest-bonuses` | List `QuestBonus`es with optional `status` filter. | PlatformAdmin, Driver |
| GET | `/quest-bonuses/{id}` | Read a single `QuestBonus`. | PlatformAdmin, Driver |
| POST | `/airport-queue/join` | Driver joins the airport pickup FIFO queue for a `grid_code`. | Driver |
| POST | `/airport-queue/leave` | Driver leaves the queue voluntarily. | Driver |
| GET | `/airport-queue` | List queue rows for a given `grid_code`, ordered by `position` ascending. | PlatformAdmin, Driver, DisputeOps |
| POST | `/rides` | Rider requests a ride; computes `quoted_fare_cents` at the `REQUESTED` instant. | Rider |
| GET | `/rides/{id}` | Read a single `Ride`. | Rider, Driver, PlatformAdmin, DisputeOps |
| GET | `/rides` | List rides with optional `status`, `rider_id`, `driver_id` filters. | PlatformAdmin, DisputeOps |
| POST | `/rides/{id}/assign` | Assign a driver to a `REQUESTED` ride per the selection policy; accepts optional `allow_neighbor_grid`. | PlatformAdmin |
| POST | `/rides/{id}/start` | Driver starts an `ASSIGNED` ride, transitioning to `ON_TRIP`. | Driver |
| POST | `/rides/{id}/complete` | Driver completes an `ON_TRIP` ride; runs the chronological fare calculation. | Driver |
| POST | `/rides/{id}/cancel` | Rider cancels a `REQUESTED` or `ASSIGNED` ride. | Rider |
| POST | `/disputes` | Rider files a dispute on a `COMPLETED` ride; ride status moves to `DISPUTED`. | Rider |
| GET | `/disputes/{id}` | Read a `Dispute`. | Rider, DisputeOps, PlatformAdmin |
| GET | `/disputes` | List disputes with optional `status`, `rider_id` filters. | DisputeOps, PlatformAdmin |
| POST | `/disputes/{id}/approve` | DisputeOps approves a dispute; applies refund credit and earnings clawback. | DisputeOps |
| POST | `/disputes/{id}/reject` | DisputeOps rejects a dispute; ride reverts to `COMPLETED`. | DisputeOps |
| POST | `/_clock/advance` | Test-only: advance the logical clock to a `target_timestamp`; triggers any time-gated transitions. | PlatformAdmin |
| POST | `/_sweep/recompute_surge` | Test-only: force a fresh surge recomputation across all grids and write a `HeatMapSnapshot` batch. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_NO_DRIVERS_AVAILABLE` | 409 Conflict |
| `ERR_NOT_AIRPORT_GRID` | 422 Unprocessable Entity |
| `ERR_DRIVER_NOT_IN_GRID` | 422 Unprocessable Entity |
| `ERR_RUSH_HOUR_OVERLAP` | 422 Unprocessable Entity |
| `ERR_QUEST_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_FARE` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_INPUT` | 422 Unprocessable Entity |
