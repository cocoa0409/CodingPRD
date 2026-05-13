# Shared Bicycle Operation System API — Product Requirements Document

## 1. Introduction

The Shared Bicycle Operation System exists to keep a metropolitan bicycle fleet usable, financially solvent, and visible to its operators. A single platform threads together five concerns that, in legacy systems, were almost always handled by separate teams: deploying and tracking bikes across a constellation of regions, billing riders by the minute with multiple coverage layers, enforcing geographic policy with electronic fences, dispatching maintenance and reallocation against a moving target of supply and demand, and writing down losses honestly so that the long-term economics of the program are auditable.

The product is built around the conviction that every meaningful action — an operator shelving a bike, a rider locking up outside a parking zone, an admin clawing back a disputed fare — must move money, change state, and emit an audit trail in one indivisible step. Field staff, riders, and dispatchers all touch the same domain model through the same API, and the API is the only contract: there is no implicit, human-driven workflow that the system trusts to complete behind the scenes. As a consequence the rules below are unusually rigid about ordering, posture-driven gating, and concurrency — these are not implementation choices, they are domain commitments.

This document specifies the HTTP API mounted under `/regions` and its sibling top-level paths (`/bikes`, `/riders`, `/rides`, `/workorders`, `/transfers`, `/geofences`, `/loss-records`, `/audit-logs`, and the test-driving paths `/_clock`, `/_sweep`, `/_events`).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either is missing or malformed, the request is rejected with `ERR_MISSING_AUTH` and HTTP 401. If both headers are present but the role is not one of the four enumerated roles, or if the caller is permitted to call the endpoint as a role but is not the resource owner the endpoint demands, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403.

There are exactly four roles, spelled as follows: `Rider`, `Operator`, `FieldStaff`, and `Admin`.

When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider` entity; ownership checks on any resource that references a `Rider` compare the resource's foreign-key field (for instance, `Ride.rider_id`) to `X-User-ID`. A rider may read and act only on their own `Ride` records and only on their own `Rider` record.

When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `assigned_operator_id` on a `WorkOrder` after assignment, or as `actor_id` on `AuditLog`) but does not compare it to any entity's `id`. The same opaque-identifier semantics apply when `X-User-Role` is `FieldStaff` or `Admin`: `X-User-ID` is recorded on `AuditLog.actor_id` and similar bookkeeping fields, but is never matched against an entity primary key.

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

List endpoints accept two query-string parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and must be at most 100; `offset` defaults to 0 and must be at least 0. Lists are always sorted by `created_at` ascending — there is no caller-selected sort order. The `meta` object on a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when there are further records beyond the current window.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every entity has a server-minted `id` rendered as a UUID with no type prefix. Most entities — `Region`, `Bike`, `Rider`, `Ride`, `WorkOrder`, `TransferOrder` — additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and a monotonically increasing integer `version` that starts at 1 on creation and increments by exactly one on every mutation. The two write-once entities `Geofence`, `LossRecord`, and the append-only entity `AuditLog` carry only `id` and `created_at`; both `updated_at` and `version` are absent on those three.

`Geofence` instead carries a `revision` field with the same monotonically-increasing-on-mutation semantics — it starts at 1 and increments on every shape or active-flag mutation.

Optimistic concurrency control is enforced on every `PATCH` endpoint. Any caller may include a `version` field in the request body; when present, the server compares it to the current server-side `version` for that entity and rejects the write with `ERR_VERSION_CONFLICT` (HTTP 409) on mismatch. Omitting `version` from the request body skips the optimistic check entirely — the write proceeds against whatever the current version is.

### 2.5. Monetary and Ratio Precision

All monetary fields are integer cents: `wallet_balance_cents`, `in_zone_return_reward_cents`, `out_of_zone_penalty_cents`, `base_fare_cents`, `penalty_cents`, `reward_cents`, `final_fare_cents`, `new_final_fare_cents`, `amount_cents`, `financial_impact_cents`. No fractional rounding ever occurs because every per-minute rate, cap, penalty, and reward is itself a whole number of cents; settlement arithmetic preserves integer values throughout. The order of arithmetic within a single ride settlement is fixed and material: per-minute charge, then segment sum, then daily-cap clamp, then penalty added on top of the (possibly capped) base, with the reward credited separately to the wallet rather than netted against the fare.

For the read-only loss-rate analytics, the underlying ratio is held as floating-point internally; values exposed at the API boundary are rounded to four decimal places using half-up rounding. Comparison of integer minutes against the per-work-order `sla_minutes` threshold uses strict greater-than — a duration exactly equal to `sla_minutes` is not a breach.

### 2.6. The Deterministic Clock

Time in this system is exclusively measured in whole minutes by `Region.clock_minutes`, a server-controlled integer that starts at 0 on region creation and advances only when an admin invokes the clock-advance test-driving capability. Every time-stamp interesting to the business — `start_minute`, `end_minute`, `opened_minute`, `resolved_minute`, `dispatched_minute`, `completed_minute`, `last_motion_minute`, `monthly_pass_expires_minute`, `clock_minute` on audit entries — is a snapshot of `clock_minutes` taken at the moment of the relevant event. The clock-advance capability accepts a single non-negative integer `minutes` parameter and returns the new `clock_minutes`. No business logic ever reads wall-clock time.

### 2.7. Density Posture and Region Counts

A region's `density_posture` is one of three values — `LOW`, `NORMAL`, or `HIGH` — derived from the region's `available_count` against two configured thresholds. The posture is `LOW` when `available_count` is less than or equal to `low_density_threshold`, `HIGH` when `available_count` is greater than or equal to `high_density_threshold`, and `NORMAL` otherwise. The inclusive boundaries on both ends are deliberate: equal to the low threshold is `LOW`, equal to the high threshold is `HIGH`. `low_density_threshold` must be at least 0; `high_density_threshold` must be strictly greater than `low_density_threshold`.

`deployed_count` is the count of bikes in the region whose `shelf_state` is `ON_SHELF`, irrespective of `status`. `available_count` is the count of bikes in the region whose `shelf_state` is `ON_SHELF` AND whose `status` is `AVAILABLE`. Both counts are recomputed on every event that could plausibly shift them — bike on-shelf, off-shelf, scrap, recall, recall release, ride start, ride end, fault open, fault resolve, work-order cancellation, transfer dispatch, transfer complete, and transfer cancel from in-transit. `density_posture` is recomputed in the same step, immediately after the counts change.

### 2.8. Hierarchical Nested Resource Paths

Nested paths — for instance, paths that mention both a `region_id` and a `bike_id`, or both a `region_id` and a `geofence_id` — are validated left-to-right. The server first resolves the leftmost path parameter; if that resource is missing it returns `ERR_NOT_FOUND` (HTTP 404) without examining downstream parameters. Only after the parent resource is confirmed does the server check the next parameter. The same `ERR_NOT_FOUND` is used regardless of which segment fails.

### 2.9. Audit Trail

Every state-changing action that mutates money, fleet state, geofence configuration, or external-system synchronization writes an entry to the append-only `AuditLog`. Each entry records `actor_role` (copied from `X-User-Role`), `actor_id` (copied from `X-User-ID`), `event_kind` (`BILLING_ADJUSTMENT`, `OPS_ACTION`, or `EXTERNAL_SYNC`), an `action` label drawn from a small vocabulary (`RIDE_FARE_ADJUST`, `FENCE_ACTIVATE`, `TRANSFER_DISPATCH`, `PAYMENT_SYNC`, `RIDE_UNLOCK`, `BIKE_ON_SHELF`, `BIKE_OFF_SHELF`, `BIKE_SCRAP`, `WORKORDER_ASSIGN`, `WORKORDER_RESOLVE`, `BIKE_FAULT_OPEN`, `BIKE_RECALL`, `TRANSFER_COMPLETE`, `RIDE_DISPUTE_OPEN`), the `subject_type` (the entity-class name, such as `Ride`, `Bike`, `Geofence`), the targeted entity's `subject_id`, a JSON snapshot of the relevant fields `before` the change (an empty object for create-only events) and `after` the change, and the `clock_minute` at the moment of the write.

### 2.10. Validation Ordering

Validation across all endpoints follows a fixed priority order. The cheapest, most universal checks happen first; the most domain-specific checks happen last. Auth header presence is checked first, then role permission, then existence of path-referenced resources (left-to-right), then existence of body-referenced foreign keys, then resource-state legality, then domain-specific business preconditions (open-work-order presence, forbidden-zone location, transfer-kind posture matching, polygon shape, fare-adjustment bounds, dispute window, single-active-ride uniqueness, regional quota), then payment-capacity checks at unlock and at settlement, then the optimistic-concurrency check on `PATCH`, and finally generic field-type/enum/range validation. When two checks could both fire against the same request, the one earlier in this list wins — for example, a missing auth header surfaces as `ERR_MISSING_AUTH` even when the body would also have failed schema validation. Within the business-safety band, a compliance check that is logically prior in the workflow takes precedence: at on-shelf time, `ERR_QUOTA_EXCEEDED` and `ERR_BIKE_HAS_OPEN_WORKORDER` and `ERR_BATTERY_TOO_LOW` are all live, evaluated in the order quota → open-work-order → battery.

### 2.11. Cross-Aggregate Consistency

The system is immediately consistent across aggregates. When a single operation shifts state on more than one entity — every ride start, ride end, transfer dispatch, transfer complete, scrap, recall, fault open, fault resolve — every mutation lands within the same logical transaction. `updated_at` and `version` advance on each mutated entity; `Region.deployed_count`, `Region.available_count`, and `Region.density_posture` are reconciled before the response is returned. Cascading effects (a transfer complete that drives a destination region from `LOW` to `NORMAL` or to `HIGH`, and which in turn auto-cancels other planned replenishment transfers) all settle in the same step.

## 3. Business Logic & Workflows

### 3.1. Region Configuration and the Fleet's Geographic Frame

A region is the unit of geographic accounting. An admin sets it up by providing a unique `name`, a positive `deployment_quota` capping how many bikes may ever be `ON_SHELF` in the region at once, a non-negative `low_density_threshold`, a strictly larger `high_density_threshold`, and the two policy amounts that drive end-of-ride incentives: `in_zone_return_reward_cents` (credited to a rider's wallet when their ride ends inside an `ALLOWED_PARKING` fence in this region) and `out_of_zone_penalty_cents` (surcharged onto the fare when their ride ends in a `RESTRICTED` fence). Both incentives default to 0 when the region is created without them. Once created, the region's `clock_minutes` begins at 0 and its `density_posture` starts at `NORMAL` (because both `deployed_count` and `available_count` start at 0, and the inclusive `<=` rule against `low_density_threshold` may make the initial posture `LOW` only when `low_density_threshold` is at least 0 — which the constraint requires). Updates to thresholds, quota, or incentive amounts are accepted through the region-update capability described in §4 and may include an OCC `version`; on success the posture is recomputed against the new thresholds.

Geofences are the second half of the geographic frame. An admin defines a fence inside a specific region by providing a `label`, a `kind` (`ALLOWED_PARKING`, `RESTRICTED`, or `FORBIDDEN`), an ordered `polygon` of at least 3 and at most 32 `{lat, lng}` vertices, and an optional `active` flag (defaulting to `true`). A polygon with fewer than 3 or more than 32 vertices, with any duplicate vertex, or whose edges self-intersect is rejected with `ERR_INVALID_POLYGON` (HTTP 422). The same validation guards every later mutation of the fence — polygon updates, `kind` changes, and `active` toggling — and any such mutation increments `revision` by one. Listing geofences within a region is filterable by `kind` and `active`.

### 3.2. Bikes from Warehouse to Street

A bike is registered to the platform with its `model` (`STANDARD` or `E_BIKE`), its globally-unique `lock_id`, and an optional `battery_pct`. New bikes start with `shelf_state` of `OFF_SHELF`, `region_id` null, `status` of `AVAILABLE` (which is only operationally meaningful once shelf state advances), `lock_state` of `LOCKED`, and `fault_categories` an empty array. A standard bike's `battery_pct` is always 100; an e-bike has whatever the registrar provided. `battery_pct` must lie in the closed range 0 to 100.

Bringing a bike on-shelf into a specific region is the operator's act of putting it onto the street. Three preconditions guard the transition. The region's `deployed_count` plus one must not exceed `deployment_quota` — otherwise `ERR_QUOTA_EXCEEDED`. The bike must not have any `WorkOrder` whose `status` is `OPEN` or `ASSIGNED` — otherwise `ERR_BIKE_HAS_OPEN_WORKORDER`. And for an `E_BIKE`, `battery_pct` must be at least 20 — otherwise `ERR_BATTERY_TOO_LOW`. On success the bike's `shelf_state` becomes `ON_SHELF`, `status` is set to `AVAILABLE`, `region_id` is set to the path-supplied region, both `deployed_count` and `available_count` are recomputed, and `density_posture` is recomputed; if the posture crosses from `LOW` to `NORMAL` or from `HIGH` to `NORMAL`, the change is recorded as an `OPS_ACTION` audit entry under the `BIKE_ON_SHELF` action.

Taking a bike off-shelf — the same shelf endpoint with the opposite `action` — is only legal when the bike is not currently `IN_USE`; otherwise `ERR_BIKE_IN_USE`. The bike's `shelf_state` flips back to `OFF_SHELF`; on re-shelf, `status` defaults back to `AVAILABLE`.

A bike's GPS, battery percentage, and lock state are updated by field staff through the bike-update capability described in §4. The accepted body fields are `battery_pct`, `last_lat`, `last_lng`, `lock_state`, and the OCC `version`. Whenever `last_lat` or `last_lng` change, the bike's `last_motion_minute` is set to the region's current `clock_minutes`.

A list operation against a region returns the bikes in that region, filterable by `status` and `shelf_state`.

### 3.3. Riders, Wallets, and the Three Coverage Layers

Riders are registered with a display `name`. On creation, `wallet_balance_cents` starts at 0, `monthly_pass_expires_minute` starts at 0 (i.e., no active pass), `free_minutes_remaining` starts at 0, and `status` starts at `ACTIVE`. A rider whose `status` is `SUSPENDED` cannot unlock a bike — `ERR_RIDER_SUSPENDED`.

There are three independent levers an admin or rider can pull against the wallet. Admin top-up credits an `amount_cents` directly into `wallet_balance_cents` and writes a `BILLING_ADJUSTMENT` audit entry. Monthly-pass purchase debits the rider's wallet by `MONTHLY_PASS_PRICE_CENTS` and sets `monthly_pass_expires_minute` to the current `clock_minutes` plus 43200 minutes — exactly thirty days of platform time. Free-minute grant adds `minutes` to `free_minutes_remaining`. The wallet may never go negative: a settlement that would push it below zero is rejected with `ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT` (HTTP 402).

### 3.4. Unlock, Ride, and the Mechanics of Fare Computation

A rider initiates a ride by submitting a `rider_id` and a `bike_id`. Several preconditions are evaluated, and each owns a distinct error identifier. The bike must be `ON_SHELF` — otherwise `ERR_BIKE_OFF_SHELF`. The bike's `status` must be `AVAILABLE` — otherwise `ERR_BIKE_NOT_AVAILABLE`. The bike's current location must not fall inside any `FORBIDDEN` active `Geofence` in its `region_id` — otherwise `ERR_BIKE_IN_FORBIDDEN_ZONE`. The rider must be `ACTIVE` and must have no other `ACTIVE` `Ride` — otherwise `ERR_RIDER_HAS_ACTIVE_RIDE`. And the rider must have payment capacity to begin: either `monthly_pass_expires_minute` is strictly greater than the current `clock_minutes` (the pass is active), or `wallet_balance_cents` is at least 100 cents — `MIN_UNLOCK_BALANCE_CENTS`, the minimum unlock balance — otherwise `ERR_INSUFFICIENT_BALANCE` (HTTP 402).

On success the bike transitions `AVAILABLE → IN_USE` and `LOCKED → UNLOCKED`, a new `Ride` is created with `status` `ACTIVE`, `start_minute` set to the current `clock_minutes`, `region_id` frozen to the bike's current region at unlock time (and not updated even if the bike crosses a regional boundary mid-ride), and the bike's `current_ride_id` is wired to the new `Ride.id`. The region's `available_count` decrements and `density_posture` is recomputed. An audit entry tagged `RIDE_UNLOCK` is written.

Locking up and ending the ride is the rider supplying an `end_lat` and `end_lng`. The ride must still be `ACTIVE` — otherwise `ERR_RIDE_NOT_ACTIVE` — and the end coordinates must not fall inside any `FORBIDDEN` active `Geofence` in the bike's `region_id` — otherwise `ERR_END_IN_FORBIDDEN_ZONE`. On success the system runs the fare settlement, advancing the ride from `ACTIVE → SETTLED` and the bike from `IN_USE → AVAILABLE`.

The settlement formula is the heart of the system. Let `duration` be the larger of `end_minute - start_minute` and 1 — the minimum billed duration is one whole minute, so a zero-minute trip is treated as one minute. The rider's `free_minutes_remaining` is consumed first: `applied_free_minutes` is the smaller of `free_minutes_remaining` and `duration`. Whatever remains after free coverage is examined against the monthly pass: the pass is considered active if `monthly_pass_expires_minute` is strictly greater than `end_minute`, and the pass covers minutes **only on `STANDARD` bikes** — it never covers any minute on an `E_BIKE`. If the pass is active and the bike is `STANDARD`, all remaining minutes after free coverage are pass-covered (recorded in `pass_covered_minutes`); otherwise `pass_covered_minutes` is 0. The remainder after free and pass coverage is `chargeable_minutes`.

Per-minute rates are tiered by model. A `STANDARD` bike charges 30 cents per minute for the first 30 chargeable minutes (`PER_MIN_RATE_STD_CENTS`, with the segment threshold `SEGMENT_BREAK_MIN` of 30) and 50 cents per minute beyond (`PER_MIN_OVER_RATE_STD_CENTS`); an `E_BIKE` charges 60 cents per minute for the first 30 chargeable minutes (`PER_MIN_RATE_EBIKE_CENTS`) and 100 cents per minute beyond (`PER_MIN_OVER_RATE_EBIKE_CENTS`). Concretely: the first-segment portion is the smaller of `chargeable_minutes` and 30; the over-segment portion is whatever is left after the first 30, or zero if `chargeable_minutes` is at most 30. `base_fare_cents` is the sum of the first-segment portion multiplied by the model's per-minute rate plus the over-segment portion multiplied by the model's over rate.

A daily cap is then applied. The cap for a `STANDARD` bike is 1500 cents (`DAILY_CAP_STD_CENTS`); for an `E_BIKE` it is 3000 cents (`DAILY_CAP_EBIKE_CENTS`). If `base_fare_cents` is greater than or equal to the applicable cap, it is clamped to the cap and the ride's `settlement_variant` is recorded as `DAILY_CAP`; otherwise `base_fare_cents` is left as computed and the variant is `PER_MINUTE`.

The geofence at the end location is then resolved: the active fence kinds in the bike's `region_id` are tested against `end_lat` and `end_lng`, producing `end_fence_kind` of `ALLOWED_PARKING`, `RESTRICTED`, or `NONE` (`FORBIDDEN` cannot appear here because it was blocked upstream). If `end_fence_kind` is `RESTRICTED`, `penalty_cents` is set to the region's `out_of_zone_penalty_cents`; otherwise `penalty_cents` is 0. If `end_fence_kind` is `ALLOWED_PARKING`, `reward_cents` is set to the region's `in_zone_return_reward_cents`; otherwise `reward_cents` is 0. `final_fare_cents` is the (possibly capped) `base_fare_cents` plus `penalty_cents` — the reward is **not** netted in, it is credited separately to the wallet.

Side effects on the rider's wallet are applied in fixed order: `free_minutes_remaining` is reduced by `applied_free_minutes`, then `wallet_balance_cents` is reduced by `final_fare_cents`, then `wallet_balance_cents` is increased by `reward_cents`. The wallet must not be driven negative by the debit; if it would be, the entire end-of-ride action is rejected with `ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT`. The ride's `payment_event_id` is minted as an idempotency token to be forwarded to the payment system, and a payment-sync entry is written to `AuditLog` with `event_kind` `EXTERNAL_SYNC`.

### 3.5. Mid-Ride Fault Reports and the Penalty Waiver

A rider who hits trouble in the middle of a ride reports it by providing `end_lat`, `end_lng`, and a fault `category` (one of `FLAT_TIRE`, `BRAKE`, `LOCK_FAILURE`, `BATTERY_SWAP`, `CHARGING`, `OTHER`). The ride must still be `ACTIVE`. On success the ride is auto-ended through the same settlement formula above, with one critical exception: `penalty_cents` is forced to 0 regardless of what `end_fence_kind` turns out to be, because the fault rendered the bike unusable and the rider should not be punished for parking it where they could. `reward_cents` is still credited if the rider managed to reach an `ALLOWED_PARKING` fence. The ride advances `ACTIVE → SETTLED`. The bike does **not** become `AVAILABLE`: it transitions `IN_USE → FAULT`, the rider's `category` is appended to `fault_categories`, and a new `WorkOrder` is opened with `cause` `USER_REPORT`, `status` `OPEN`, and `opened_minute` set to the current `clock_minutes`. Because the bike was `IN_USE` rather than `AVAILABLE`, the region's `available_count` is **not** decremented further by this transition.

A rider can also report a fault on a bike they are not riding — for instance, after walking up to a parked bike and discovering the brake is dead. Only `category` is supplied. The bike must be `ON_SHELF` and `AVAILABLE`. On success the bike's `status` is flipped from `AVAILABLE → FAULT` (locking it out of new rides — this is fault-bike isolation), the `category` is appended to `fault_categories`, a new `WorkOrder` is opened with `cause` `USER_REPORT`, `status` `OPEN`, and the appropriate `opened_minute`, and the region's `available_count` decrements with `density_posture` recomputed accordingly. An audit entry tagged `BIKE_FAULT_OPEN` is written.

### 3.6. Work Order Lifecycle and SLA Accounting

Operators (and admins on their behalf) can create work orders directly, providing the `bike_id`, the originating `cause` (one of `USER_REPORT`, `LONG_STATIONARY`, `LOCK_ABNORMAL`, `LOW_BATTERY`, or `RECALL`), a `category`, and an `sla_minutes` allowance. Newly created work orders start with `status` `OPEN`, `opened_minute` set to the region's current `clock_minutes`, and `region_id` set to the bike's region at creation. The bike's `status` is flipped to `FAULT` (if not already).

Assignment is the operator's act of routing a work order to a specific field operator. The work order must be `OPEN` — otherwise `ERR_WORKORDER_NOT_OPEN`. An `assigned_operator_id` must be supplied — its absence yields `ERR_OPERATOR_REQUIRED` (HTTP 422). On success the work order advances `OPEN → ASSIGNED` and `assigned_operator_id` is recorded. Resolution requires the work order to be `ASSIGNED` — otherwise `ERR_WORKORDER_NOT_ASSIGNED` — and a `resolution_note` is required at this point. On resolve, the work order moves `ASSIGNED → RESOLVED`, `resolved_minute` is set to the current `clock_minutes`, the matching `category` is cleared from the bike's `fault_categories`, and if the bike's `fault_categories` is now empty AND no other `OPEN` or `ASSIGNED` work order exists for the bike, the bike's `status` flips `FAULT → AVAILABLE` and the region's counts and `density_posture` are recomputed. Otherwise the bike remains `FAULT`. Cancellation of an `OPEN` work order moves it `OPEN → CANCELLED`; if it was the only open work order for that bike and the `fault_categories` would consequently become empty, the bike flips `FAULT → AVAILABLE`.

`sla_breached` is a computed attribute, read freshly on every retrieval and at resolve time. For a `RESOLVED` work order, breach is `true` when `resolved_minute - opened_minute` is strictly greater than `sla_minutes`. For a `CANCELLED` work order, breach is always `false` — cancelled work orders never breach. For an `OPEN` or `ASSIGNED` work order, breach is `true` when the current `clock_minutes` minus `opened_minute` is strictly greater than `sla_minutes`. A duration exactly equal to `sla_minutes` is never a breach, in any state. The work-order list supports filtering by `status`, `region_id`, and `sla_breached`.

### 3.7. Recall and Release-Recall

Sometimes an operator needs to pull a bike out of the rideable pool without opening a fault — for instance, ahead of a scheduled software push. Recalling a bike requires its `status` to be `AVAILABLE` (otherwise `ERR_BIKE_NOT_AVAILABLE`) and requires that the bike not be currently part of an active ride (otherwise `ERR_BIKE_IN_USE`). On success the bike's `status` is set to `RECALL` (locking it out of new rides), the region's `available_count` decrements, and `density_posture` is recomputed. An audit entry tagged `BIKE_RECALL` is written. Release-recall is the inverse: the bike's `status` must be `RECALL` (otherwise `ERR_BIKE_NOT_IN_RECALL`), and the bike must have no `OPEN` or `ASSIGNED` work orders (otherwise `ERR_BIKE_HAS_OPEN_WORKORDER`). On success the bike returns to `AVAILABLE` and the region's counts and posture are recomputed.

### 3.8. Cross-Region Transfers and the Cascade

Planning a transfer requires the source and destination region ids as `from_region_id` and `to_region_id`, plus a non-empty ordered list of `bike_ids` to move. The plan itself is created with `status` `PLANNED`. The transfer's `kind` is computed and frozen at plan time from the density postures of the two regions: it is `REPLENISH` if the destination region's `density_posture` is `LOW` at plan time, `CLEARANCE` if the source region's `density_posture` is `HIGH` at plan time, and if neither holds the plan is rejected.

Dispatching a `PLANNED` transfer requires four preconditions to hold simultaneously. The transfer must still be `PLANNED` (otherwise `ERR_TRANSFER_NOT_PLANNED`). Every bike in `bike_ids` must currently have `region_id` equal to `from_region_id`, `status` equal to `AVAILABLE`, and `shelf_state` equal to `ON_SHELF` — any failure across the set yields `ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER`. The transfer's frozen `kind` must still match current postures at dispatch time: `REPLENISH` requires the destination's `density_posture` to still be `LOW`; `CLEARANCE` requires the source's `density_posture` to still be `HIGH` — otherwise `ERR_TRANSFER_KIND_MISMATCH`. And the destination's `deployed_count` plus the number of `bike_ids` must not exceed `deployment_quota` — otherwise `ERR_QUOTA_EXCEEDED`. On success each bike's `shelf_state` becomes `OFF_SHELF` with `region_id` set to null, the source region's counts and `density_posture` are recomputed (cascade hop 1), the transfer advances `PLANNED → IN_TRANSIT`, and `dispatched_minute` is set to the current `clock_minutes`.

Completing an `IN_TRANSIT` transfer drops the bikes at the destination. The transfer must still be `IN_TRANSIT` (otherwise `ERR_TRANSFER_NOT_IN_TRANSIT`). On success each bike's `region_id` is set to `to_region_id`, `shelf_state` to `ON_SHELF`, and `status` to `AVAILABLE`. The destination region's counts and `density_posture` are recomputed (cascade hop 2). And then — this is the third-order cascade hop, where the system actively prevents over-replenishment — if the destination region's `density_posture` flips from `LOW` to `NORMAL` or from `LOW` to `HIGH`, any other `PLANNED` `TransferOrder` whose `to_region_id` is this same destination region and whose `kind` is `REPLENISH` is automatically transitioned to `CANCELLED` (cascade hop 3). The completing transfer advances `IN_TRANSIT → COMPLETED`, `completed_minute` is set to the current `clock_minutes`, and a `TRANSFER_COMPLETE` audit entry is written.

Cancellation has two flavors. Cancelling a `PLANNED` transfer simply moves it `PLANNED → CANCELLED` with no bike movement. Cancelling an `IN_TRANSIT` transfer restores each bike's `region_id` to `from_region_id`, `shelf_state` to `ON_SHELF`, and `status` to `AVAILABLE`, then recomputes the source region's counts and `density_posture`.

### 3.9. Anomaly Sweep and Automatic Work-Order Generation

The platform exposes an admin-only test-driving sweep capability that walks every bike with `status` `AVAILABLE` and opens work orders for three independent conditions. A bike whose `clock_minutes - last_motion_minute` is at least `LONG_STATIONARY_THRESHOLD_MIN` (1440 minutes — one day) gets a work order with `cause` `LONG_STATIONARY`. A bike whose `battery_pct` is at most `LOW_BATTERY_THRESHOLD_PCT` (20%) gets a work order with `cause` `LOW_BATTERY`. A bike whose `lock_state` is `UNKNOWN` and whose `shelf_state` is `ON_SHELF` gets a work order with `cause` `LOCK_ABNORMAL`. Each generated work order opens with `status` `OPEN`, `opened_minute` set to the current `clock_minutes`, and a sensible `sla_minutes` value supplied by configuration; the corresponding bike has its `status` flipped to `FAULT` and the region's `available_count` and `density_posture` are recomputed. The sweep returns the `opened_count`.

### 3.10. Disputes, Adjustments, and Voids

A rider who believes their fare was wrong opens a dispute on a `SETTLED` ride by submitting a `reason`. The ride must currently be `SETTLED` (otherwise `ERR_RIDE_NOT_SETTLED`), and the dispute must be opened within `DISPUTE_WINDOW_MINUTES` of the ride's `end_minute` — that is, the current `clock_minutes` minus `end_minute` must not exceed 1440 minutes (one day). Past that window the dispute is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. On success the ride advances `SETTLED → DISPUTED` and a `BILLING_ADJUSTMENT` audit entry with action `RIDE_DISPUTE_OPEN` is written. No money moves at this step.

An admin resolves a dispute by submitting a `new_final_fare_cents` — the corrected total. The ride must be `DISPUTED` (otherwise `ERR_RIDE_NOT_DISPUTED`), and `new_final_fare_cents` must not be greater than the ride's current `final_fare_cents` — fare cannot be increased through adjustment (otherwise `ERR_ADJUSTMENT_EXCEEDS_FARE`). On success the difference (current `final_fare_cents` minus `new_final_fare_cents`) is credited back to the rider's `wallet_balance_cents`, the ride's `final_fare_cents` is updated to the new value, `settlement_variant` is unchanged, the ride moves `DISPUTED → SETTLED`, a `BILLING_ADJUSTMENT` audit entry is written carrying both the old and new `final_fare_cents` in `before` and `after`, and a payment-system `EXTERNAL_SYNC` audit entry is emitted.

Voiding a ride is the admin's escape valve for a clearly-bogus unlock. The ride must be `ACTIVE` (otherwise `ERR_RIDE_NOT_ACTIVE`). On success the ride moves `ACTIVE → VOIDED`, `final_fare_cents` is set to 0, the bike returns to `AVAILABLE`, and no money moves at all.

### 3.11. Loss Records, Loss Rate, and Scrap

When a bike is lost — stolen, irreparably damaged, or abandoned — an admin records the event by supplying a `bike_id` (the underlying bike must currently be `ON_SHELF` or `OFF_SHELF`; a bike that is already `SCRAPPED` may not be the subject of a fresh loss record), a `cause` (one of `THEFT`, `DAMAGE`, `ABANDONED`), a `responsibility` attribution (one of `RIDER`, `OPERATOR`, `UNKNOWN`), an optional `responsible_party_id` (which is the `Rider.id` when `responsibility` is `RIDER`, an opaque operator id when `responsibility` is `OPERATOR`, and null when `UNKNOWN`), and a strictly positive `financial_impact_cents`. The record is created with `scrapped` initially `false`.

Scrap is a separate admin step. It requires that an unscrapped `LossRecord` referencing the bike already exist (otherwise `ERR_NO_LOSS_RECORD`), and (when the bike is currently `ON_SHELF`) the bike must not be `IN_USE`. On success the bike's `shelf_state` becomes `SCRAPPED` (a terminal state), the matching `LossRecord.scrapped` is set to `true`, the region's counts and `density_posture` are recomputed (the scrapped bike no longer counts toward `deployed_count`), and a `BIKE_SCRAP` audit entry is written.

The region-level loss-rate read is admin-only and computes two ratios on demand. `loss_count` is the count of `LossRecord` rows whose `region_id` matches the path region. `deployed_lifetime` is the count of `Bike` rows whose `region_id` is the path region (identical bike ids are never double-counted), including bikes that may currently have `region_id` null if any of their prior shelf history was `ON_SHELF` in this region. If `deployed_lifetime` is 0, both reported ratios are 0.0. Otherwise, `provisional_loss_rate` is `loss_count` divided by `deployed_lifetime` and counts every loss record regardless of `responsibility`; `attributed_loss_rate` is the count of loss records whose `responsibility` is not `UNKNOWN`, divided by the same `deployed_lifetime`. The two ratios differ exactly when at least one loss record carries `responsibility` `UNKNOWN`. Both values are rounded to four decimal places half-up at the API boundary. An `anomaly` flag is reported as `true` when `provisional_loss_rate` is strictly greater than the threshold `ANOMALY_RATE_THRESHOLD` of 0.05.

### 3.12. External-System Synchronization

The platform emits external-system events to a payment processor, an instant-messaging system, and a mapping system at three points: on every ride end (success or fault-driven), on every fare adjustment, and on every monthly-pass purchase. Each emission writes an `AuditLog` entry with `event_kind` `EXTERNAL_SYNC` capturing the `payment_event_id` (where applicable), the targeted `subject_type` and `subject_id`, and a JSON `payload` in the `after` snapshot. An admin-only test-driving emission capability accepts a `target_system`, `subject_type`, `subject_id`, and `payload` and writes the same kind of audit entry without otherwise mutating state — this exists strictly to exercise the sync pipeline.

### 3.13. Concurrency Serialization

Five concurrency races are explicitly serialized.

Two riders attempting to unlock the same `AVAILABLE` bike at the same moment: at most one ride is created, the bike transitions `AVAILABLE → IN_USE` exactly once, and the loser sees the post-state (bike no longer `AVAILABLE`) and is rejected with `ERR_BIKE_NOT_AVAILABLE` (HTTP 409). First-writer-wins on `Bike.status`.

A rider's end-of-ride and an admin's void on the same `ACTIVE` ride: exactly one succeeds, and the loser — whichever request lost the race on `Ride.status` — is rejected with `ERR_RIDE_NOT_ACTIVE` (HTTP 409), because by then the ride is no longer `ACTIVE`. First-writer-wins on `Ride.status`.

Two operators attempting to assign the same `OPEN` work order: exactly one assignment lands, and the loser sees the post-state and is rejected with `ERR_WORKORDER_NOT_OPEN` (HTTP 409). First-writer-wins on `WorkOrder.status`.

A bike-update attempt with a stale `version` in the body: the stale write is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). This is the optimistic concurrency check; if `version` is omitted from the body entirely, the check is skipped and the write proceeds.

Two transfer dispatches that reference the same `bike_id`: only the first dispatch can move the bike — the second observes the bike's `region_id` and `shelf_state` already updated and fails with `ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER` (HTTP 409). First-writer-wins on `Bike.region_id` and `Bike.shelf_state`.

## 4. Endpoint Definitions

All listed endpoints follow the system-wide envelope and pagination conventions defined in §2. By status-code convention, endpoints that create a brand-new resource return HTTP 201; endpoints that mutate or read an existing resource return HTTP 200; error responses follow the standard error envelope with the appropriate HTTP status from §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /regions | Create a region with quota and density thresholds | Admin |
| GET | /regions/{region_id} | Read region with computed counts and density_posture | Admin, Operator, FieldStaff, Rider |
| GET | /regions/{region_id}/loss-rate | Read provisional and attributed loss rates | Admin |
| PATCH | /regions/{region_id} | Update region thresholds, quota, reward/penalty | Admin |
| POST | /regions/{region_id}/geofences | Create a geofence in a region | Admin |
| PATCH | /geofences/{geofence_id} | Mutate geofence shape or active flag (dynamic fence adjustment) | Admin |
| GET | /regions/{region_id}/geofences | List geofences in region (filterable by kind, active) | Admin, Operator, FieldStaff, Rider |
| POST | /bikes | Register a bike (OFF_SHELF by default; no region assigned) | Admin |
| GET | /bikes/{bike_id} | Read a bike | Admin, Operator, FieldStaff, Rider |
| PATCH | /bikes/{bike_id} | Update bike fields (battery_pct, lock_state, GPS) | Admin, Operator, FieldStaff |
| POST | /regions/{region_id}/bikes/{bike_id}/shelf | On-shelf or off-shelf workflow within a region | Operator, Admin |
| POST | /bikes/{bike_id}/recall | Mark bike RECALL (locks out new rides) | Operator, Admin |
| POST | /bikes/{bike_id}/release-recall | Release recall: RECALL→AVAILABLE if no open work order | Operator, Admin |
| POST | /bikes/{bike_id}/fault-report | User-reported fault (outside of an active ride) | Rider, Operator |
| POST | /bikes/{bike_id}/scrap | Scrap a bike (terminal). Requires an unscrapped LossRecord. | Admin |
| GET | /regions/{region_id}/bikes | List bikes in region (filterable by status, shelf_state) | Admin, Operator, FieldStaff, Rider |
| POST | /riders | Register a rider | Admin |
| GET | /riders/{rider_id} | Read rider including wallet, pass, free minutes | Rider, Admin |
| POST | /riders/{rider_id}/wallet/credit | Top up wallet (admin or platform funding action) | Admin |
| POST | /riders/{rider_id}/monthly-pass | Purchase a monthly pass | Rider |
| POST | /riders/{rider_id}/free-minutes/grant | Admin grants free minutes (promo) | Admin |
| POST | /rides | QR-unlock: start ride on a specific bike | Rider |
| GET | /rides/{ride_id} | Read ride incl. computed fare components when SETTLED | Rider, Admin |
| POST | /rides/{ride_id}/end | End-of-ride lock: settles fare, applies penalty/reward | Rider |
| POST | /rides/{ride_id}/fault-report | Rider reports fault during ride; auto-ends ride with waived penalty | Rider |
| POST | /rides/{ride_id}/dispute | Open billing dispute on a SETTLED ride | Rider |
| POST | /rides/{ride_id}/adjust | Admin reduces ride fare to new amount; difference refunded | Admin |
| POST | /rides/{ride_id}/void | Admin voids an ACTIVE ride (corrects bogus unlock) | Admin |
| POST | /workorders | Create a work order for a bike | Operator, Admin |
| POST | /workorders/{workorder_id}/assign | Assign work order to operator | Operator, Admin |
| POST | /workorders/{workorder_id}/resolve | Resolve work order | Operator |
| POST | /workorders/{workorder_id}/cancel | Cancel an OPEN work order | Operator, Admin |
| GET | /workorders | List work orders (filterable by status, region_id, sla_breached) | Operator, Admin |
| POST | /transfers | Plan a cross-region transfer | Operator, Admin |
| POST | /transfers/{transfer_id}/dispatch | Dispatch a planned transfer | Operator |
| POST | /transfers/{transfer_id}/complete | Complete an in-transit transfer | Operator |
| POST | /transfers/{transfer_id}/cancel | Cancel a planned or in-transit transfer | Operator, Admin |
| POST | /loss-records | Record bicycle loss with responsibility attribution | Admin |
| GET | /loss-records | List loss records (filter by region_id, cause) | Admin |
| GET | /audit-logs | List audit log entries (filter by event_kind, subject_type, subject_id, actor_role) | Admin |
| POST | /_clock/advance | Advance global clock_minutes by a non-negative integer minutes | Admin |
| POST | /_sweep/run | Run automatic anomaly sweep | Admin |
| POST | /_events/emit | Emit an external system sync event | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_POLYGON | 422 |
| ERR_QUOTA_EXCEEDED | 409 |
| ERR_BIKE_NOT_AVAILABLE | 409 |
| ERR_BIKE_IN_USE | 409 |
| ERR_BIKE_OFF_SHELF | 409 |
| ERR_BIKE_HAS_OPEN_WORKORDER | 409 |
| ERR_BIKE_IN_FORBIDDEN_ZONE | 409 |
| ERR_END_IN_FORBIDDEN_ZONE | 409 |
| ERR_BATTERY_TOO_LOW | 409 |
| ERR_RIDER_SUSPENDED | 403 |
| ERR_RIDER_HAS_ACTIVE_RIDE | 409 |
| ERR_INSUFFICIENT_BALANCE | 402 |
| ERR_INSUFFICIENT_BALANCE_AT_SETTLEMENT | 402 |
| ERR_RIDE_NOT_ACTIVE | 409 |
| ERR_RIDE_NOT_SETTLED | 409 |
| ERR_RIDE_NOT_DISPUTED | 409 |
| ERR_ADJUSTMENT_EXCEEDS_FARE | 422 |
| ERR_DISPUTE_WINDOW_CLOSED | 409 |
| ERR_WORKORDER_NOT_OPEN | 409 |
| ERR_WORKORDER_NOT_ASSIGNED | 409 |
| ERR_OPERATOR_REQUIRED | 422 |
| ERR_TRANSFER_NOT_PLANNED | 409 |
| ERR_TRANSFER_NOT_IN_TRANSIT | 409 |
| ERR_TRANSFER_KIND_MISMATCH | 409 |
| ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER | 409 |
| ERR_NO_LOSS_RECORD | 409 |
| ERR_BIKE_NOT_IN_RECALL | 409 |
