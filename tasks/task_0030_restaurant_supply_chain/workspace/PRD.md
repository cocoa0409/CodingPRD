# Restaurant Supply Chain API — Product Requirements Document

## 1. Introduction

A multi-store restaurant chain depends on a single central kitchen to produce dishes that travel — under tight temperature, shelf-life, and time-window constraints — to dozens of stores every day. Today, planners juggle production schedules, store managers chase ordering windows, drivers improvise around dispatch exceptions, and finance reconciles loss and cost reports after the fact. The disconnects are operationally expensive: production batches are scheduled without regard to remaining shelf life, vehicles get loaded with mixed temperature zones they cannot maintain, near-expiry inventory sits untouched until it must be discarded, and abnormal losses go uninvestigated.

This document specifies the supply-chain API that ties these workflows into one consistent system. The API drives **store-side ordering** (catalog-permissioned, window-bounded, cutoff-protected), **central-kitchen production** (recipe-based ingredient explosion, shelf-life-aware sequencing, equipment-capacity-bounded scheduling), **delivery routing** (vehicle and temperature-zone constrained, with mid-route exception recovery), **automatic replenishment** (safety-stock-driven, velocity-adjusted), **near-expiry alerting and disposal**, **loss recording with abnormal-event detection**, and **periodic cost allocation** (provisional at production, final at period close). Every state transition, calculation, and rejection is recorded in an append-only audit log, and select actions are synchronized into peripheral systems (POS, ERP, finance, logistics).

The API is mounted under `/supply-chain`. All operations are immediate-consistent within a single request — a delivery completion that must update inventory, transition the originating store order, and emit external sync events does so atomically — though synchronization with external systems is fire-and-forget through the audit log rather than awaited.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the acting user's identifier) and `X-User-Role` (the role under which the request is made). When either header is missing the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). When `X-User-Role` does not name one of the five roles defined below, the request is rejected with `ERR_INVALID_ROLE` (HTTP 401). When the role is recognized but is not authorized to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles are `PlatformAdmin`, `CentralKitchenPlanner`, `StoreManager`, `Driver`, and `FinanceController`. Their identity binding works as follows:

- When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Store`. Every store-scoped resource the manager touches — `StoreOrder`, `InventoryBatch`, `ReplenishmentRule`, `LossRecord` — carries a `store_id` field, and the server compares that field to `X-User-ID`; on mismatch the request is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Driver`, `X-User-ID` is an opaque operator identifier not tied to a persisted entity. The server compares it to `DeliveryRoute.driver_user_id` for the depart, complete, and raise-exception actions; on mismatch the request is rejected with `ERR_DRIVER_MISMATCH` (HTTP 403).
- When `X-User-Role` is `PlatformAdmin`, `CentralKitchenPlanner`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, in `actor_user_id` on `AuditLogEntry`) but does not compare it to any entity's `id`.

`PlatformAdmin` is the hierarchical override role — it owns store and vehicle creation, the test-driving clock and sweep capabilities, and the synthetic event emission endpoint. `CentralKitchenPlanner` owns the recipe catalog, ingredient master, bill-of-materials, production-batch lifecycle, and route planning and dispatch. `StoreManager` runs the store side: ordering, inventory adjustments, transfers, replenishment rules, and loss recording. `Driver` executes assigned routes. `FinanceController` approves and reverses loss records, marks investigations resolved, and runs the period-close cost allocation.

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

All list endpoints accept the query parameters `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside this band are rejected. The default `offset` is 0. List endpoints sort results by `created_at` ascending. The `meta` object on a list response includes `limit`, `offset`, `total_count` (the total number of records matching the filter), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Resource Identity and Common Properties

Every persisted resource is identified by an `id` that is a server-minted UUID (no domain prefix). Standard resources additionally carry `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at 1 on creation and increments by 1 on every successful mutation. Two entity classes are exceptions: `RecipeIngredient` and `AuditLogEntry` are immutable; they carry only `id` and `created_at`, and have neither `updated_at` nor `version`. The `OrderLine` is similarly immutable once recorded — it is appended via the order-line action, never updated, and likewise carries only `id` and `created_at`.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When the client supplies it, the server compares the value against the persisted `version`; on mismatch the request is rejected with `ERR_STALE_VERSION` (HTTP 409). When the client omits `version`, the server skips the check and applies the change unconditionally. Successful mutations bump `version` by 1 and refresh `updated_at` on the directly-targeted resource as well as on every cascaded resource the operation touches (see §2.6 below).

### 2.6. Cascade and Side-Effect Discipline

State transitions in this system frequently mutate more than one entity. The discipline is consistent across operations: every entity whose state, computed field, or stored value is changed by the operation has its `updated_at` refreshed and its `version` bumped, and a corresponding `AuditLogEntry` row is appended with the actor's role and user id captured into `actor_role` and `actor_user_id`, the relevant fields snapshot into `payload`, the affected entity class recorded in `target_type`, the affected row's id in `target_id`, the verb in `action`, and the synchronized peripheral systems listed in `external_systems`. The audit log is append-only — entries are never updated, and that is why `AuditLogEntry` carries no `version`.

A failed operation produces no side effects: no state change, no `updated_at` refresh, no audit row.

### 2.7. Nested-Resource Path Validation

URL paths with multiple segments — for example `/supply-chain/store-orders/{id}/lines` or `/supply-chain/recipes/{id}/ingredients` — are validated left-to-right. The leftmost path-referenced resource is checked first; if it does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any further checks fire. Body-referenced foreign-key ids (such as `inventory_batch_id` in a loss-record body) are validated after path resolution; an unresolved body reference yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.8. Validation Priority

When a single request has multiple things wrong with it, the server evaluates checks in a fixed order and returns the first failure encountered. Authentication (`ERR_AUTH_REQUIRED`) is checked first, then role validity (`ERR_INVALID_ROLE`), then endpoint authorization (`ERR_FORBIDDEN`); these three precede every other check. After auth comes existence — path resources (`ERR_NOT_FOUND`) before body foreign keys (`ERR_REFERENCE_NOT_FOUND`). After existence comes state — the target resource must be in a state from which the requested transition is legal (`ERR_INVALID_STATE`), then optimistic-concurrency match when the client supplied `version` (`ERR_STALE_VERSION`). Only after all of these do business-rule checks fire — safety and compliance rules first (TIER3-disposal-required, temperature-zone compatibility, abnormal-loss investigation), then referential rules (catalog permission, batch readiness, driver match), then temporal rules (order window, cutoff, delivery-window overlap, shelf-life sufficiency), then constraint rules (equipment capacity, vehicle availability, vehicle capacity, quantity range, responsibility-attribution match, replenishment cycle), and finally fiscal rules (`ERR_LOSS_EXCEEDS_ON_HAND`).

This ordering is observable: a delivery dispatch that would violate both vehicle capacity and temperature-zone compatibility surfaces the temperature-zone error first because temperature-zone compatibility is a safety check that ranks ahead of constraint checks.

### 2.9. Money, Quantities, and Rounding

Monetary amounts are integer cents — `unit_price_cents`, `unit_cost_cents`, `total_value_cents`, `line_value_cents`, `low_amount_bypass_cents`, `financial_impact_cents`, `avg_daily_sales_cents`, and the cost-allocation outputs are all whole-cent values. Order quantities, batch unit counts, vehicle capacity, and stock counts are integer units. Ingredient quantities used in production are tracked in milligrams (integer) internally to avoid floating-point drift during the bill-of-materials roll-up.

The system uses **round half up** to integer cents (or to integer units, where applicable) at clearly defined rounding boundaries; intermediate values may be carried in floating-point but each rule below names the single boundary at which rounding lands. When a rounded sum across many parts must equal an originally-computed total, the residual cent or unit is assigned to a deterministically-chosen recipient — the rules name that recipient explicitly so two implementations cannot diverge on the leftover cent.

### 2.10. Temperature, Shelf Life, and Equipment Zones

Three controlled vocabularies recur throughout the system. Storage and transport temperature zones come from `{AMBIENT, CHILLED, FROZEN}`; a `Store.temperature_zone` may additionally be `MIXED` to indicate it accommodates any of the three. `Recipe.equipment_class` is one of `{OVEN, FRYER, MIXER, ASSEMBLY}`. `Recipe.status` is one of `{ACTIVE, RETIRED}`. `Store.status` is one of `{ACTIVE, SUSPENDED}`. `Vehicle.status` is one of `{AVAILABLE, ASSIGNED, OUT_OF_SERVICE}`. These exact strings are the only values accepted by input fields and the only values returned by output fields.

### 2.11. Test-Driving Capabilities

Three administrative capabilities exist solely to make deterministic testing of time- and sweep-driven behavior possible. A clock-advance capability moves the simulated clock forward to a supplied `to_iso8601` instant; an expiry-alert sweep capability evaluates near-expiry tiers across all on-hand inventory; and a replenishment sweep capability evaluates each `ReplenishmentRule` whose cycle has elapsed. A synthetic event-emission capability accepts a `system` discriminator and a `payload` object and writes a corresponding row through the audit log so tests can drive POS, ERP, FINANCE, or LOGISTICS event chains without a real peripheral integration. All four are restricted to `PlatformAdmin`.

## 3. Business Logic & Workflows

### 3.1. Stores, Recipes, Ingredients, and the Bill of Materials

A `Store` is created by the platform with a public `store_code` (case-sensitive unique), a `name`, and a `temperature_zone` describing the storage capability the store can maintain. The store's `catalog_permission` is an allow-list of recipe ids that this store may order; an empty array means the store cannot place orders for any recipe at all. Two daily-window settings — `order_window_open_minute` and `order_window_close_minute`, both expressed as minute-of-day in the range 0 to 1439 in UTC — bracket when the store may submit and modify orders, and `cutoff_minutes_before_close` (default 60) names the lockout window before close during which modifications and cancellations are forbidden. Submission of replenishment orders below `low_amount_bypass_cents` (default 50000) auto-approves without manager intervention. The store's `avg_daily_sales_cents` is a read-only computed field — a rolling 7-day mean of fulfilled order-line value, in cents — that the forecast and replenishment calculations consume. A new `Store` is created with `status` of `ACTIVE`.

A `Recipe` carries a chain-unique `recipe_code`, a `name`, the `temperature_zone` it must be stored at after production, a `shelf_life_hours` (the number of hours from production complete to expiry, strictly positive), a `production_minutes_per_unit` (equipment-minutes consumed per unit produced, strictly positive), the required `equipment_class`, and a `unit_price_cents` selling price used for both order valuation and cost allocation. A new `Recipe` is created with `status` of `ACTIVE` and may transition to `RETIRED` via `PlatformAdmin` administrative action elsewhere; the system surfaces both states verbatim in API responses.

An `Ingredient` is a stock-keeping unit identified by `sku`, with a `name`, a base `unit` (such as kg, l, or ea), a raw `shelf_life_hours` from receipt, and a standard `unit_cost_cents` per base unit. A `RecipeIngredient` row joins one `Recipe` to one `Ingredient` with a `quantity_per_unit` (in base units, strictly positive) describing how much of that ingredient produces one unit of the recipe. Recipe-ingredient rows are immutable once attached.

### 3.2. Store Orders: Drafting, Submission, and Cancellation

A store manager begins a daily order by creating a draft `StoreOrder`. The body supplies `target_delivery_date` — the ISO date (`YYYY-MM-DD`) on which the manager wants to receive the goods — and the new order is created with `status` of `DRAFT`, with `store_id` populated from `X-User-ID`. Lines are appended one at a time: each line names a `recipe_id` and a `quantity` of integer units, and the appended `OrderLine` carries `store_order_id` set to the parent order's id so the line is permanently linked to it. Quantity must be at least 1 and at most 10,000; outside that band, the line is rejected with `ERR_QUANTITY_OUT_OF_RANGE`.

Submission moves the order from `DRAFT` to `SUBMITTED`. Five preconditions must hold at submit time: the current instant must lie inside the store's daily ordering window (between `order_window_open_minute` inclusive and `order_window_close_minute` exclusive, evaluated as UTC minute-of-day; otherwise `ERR_ORDER_WINDOW_CLOSED`), the store's `status` must be `ACTIVE`, the order must have at least one line, every line's `recipe_id` must appear in the store's `catalog_permission` (otherwise `ERR_CATALOG_PERMISSION_DENIED`), and every line's `quantity` must lie in the 1-to-10,000 band. On success, each `OrderLine.line_value_cents` is locked at `quantity` multiplied by `Recipe.unit_price_cents`, the order's `total_units` is recomputed as the sum of all `quantity` values, and `total_value_cents` is recomputed as the sum of all `line_value_cents`. The system stamps `submitted_at` to the current instant, appends an `AuditLogEntry` with the action `SUBMIT_ORDER` and `external_systems` listing both `POS` and `ERP`, and bumps `version`. Submitting a `StoreOrder` that is already past `DRAFT` is rejected with `ERR_INVALID_STATE`; this is also the rejection that surfaces when two double-clicks race and the second loses (only the first transition wins).

Cancellation is permitted from either `DRAFT` or `SUBMITTED`. Both transitions require that the current instant be at least `cutoff_minutes_before_close` before `order_window_close_minute`; closer to close than that, the request is rejected with `ERR_ORDER_CUTOFF_PASSED`. Cancellation from `SUBMITTED` additionally requires that `consolidation_batch_id` is null — an order that has already been folded into a production batch cannot be cancelled, and the attempt is again rejected with `ERR_INVALID_STATE`. On success, `cancelled_at` is stamped, `status` moves to `CANCELLED`, and an audit row is appended.

Header-level modification of a `DRAFT` order — the only permitted field at present is `target_delivery_date` — is also subject to the cutoff rule and yields `ERR_ORDER_CUTOFF_PASSED` if attempted within the lockout window.

### 3.3. Production: Consolidation, Scheduling, Production, Completion

Each evening (or whenever the planner triggers it), `CentralKitchenPlanner` runs the consolidation sweep for a chosen `target_delivery_date`. The body supplies just that date. The sweep selects every `StoreOrder` whose `status` is `SUBMITTED` and whose `target_delivery_date` matches, and groups all `OrderLine` rows by `recipe_id`. For each group it creates (or updates) one `ProductionBatch` per recipe per planning run, populating `recipe_id`, `target_delivery_date`, and computing `planned_units` as the sum of `OrderLine.quantity` across the consolidated lines. Each consolidated `StoreOrder` transitions from `SUBMITTED` to `CONSOLIDATED` and has its `consolidation_batch_id` set to the relevant batch's id. Cancelled orders submitted before consolidation are excluded; orders not yet submitted are excluded; orders whose target dates differ are excluded. A new batch is created with `status` of `PLANNED` and an `equipment_minutes` value equal to `planned_units` multiplied by `Recipe.production_minutes_per_unit`. If the consolidation would attach a `Store` whose `status` is not `ACTIVE`, that store's orders are excluded from the run. `AuditLogEntry` rows are appended for every `StoreOrder` touched and every `ProductionBatch` row written.

Concurrent with consolidation, the planner pulls a planned-vs-forecast view for each batch. The forecast view returns `forecast_units` per recipe and a forecast ingredient demand: for every `Store` whose `status` is `ACTIVE` and that has an `ACTIVE` `ReplenishmentRule` for the recipe, the projected unit count is the store's `avg_daily_sales_cents` divided by the recipe's `unit_price_cents`, multiplied by a forecast horizon of one day, multiplied by the rule's `velocity_multiplier`, with the result rounded half-up to integer units at the per-recipe-per-store boundary; the per-recipe forecast is the sum of these per-store rounded values. The forecast ingredient demand is then the sum across recipes of `forecast_units` multiplied by `RecipeIngredient.quantity_per_unit`. Intermediate multiplications are floating-point; the rounding boundary is the per-recipe row. The forecast and the planned ingredient explosion (described next) form a deliberate dual-variant pair: the planned explosion uses actual `SUBMITTED` `OrderLine.quantity`, the forecast explosion uses sales velocity. They are intentionally not reconciled by the system — the planner reads both and decides.

The planned ingredient explosion runs as part of consolidation. For every `OrderLine` belonging to a `StoreOrder` whose `status` is `SUBMITTED` and whose `target_delivery_date` matches the request, the system multiplies `OrderLine.quantity` by `RecipeIngredient.quantity_per_unit` (joining via `recipe_id`) and sums the results grouped by `ingredient_id`. Cancelled lines and orders not in `SUBMITTED` are excluded. All ingredient quantities are tracked in milligrams (integer) — multiplication then sum is exact. The aggregated demand is returned ordered by `ingredient_id` ascending.

A `PLANNED` batch transitions to `SCHEDULED` via the schedule action. The body optionally supplies `preferred_start_at`. Two preconditions must hold. First, equipment-class capacity for the chosen day must have remaining minutes greater than or equal to the batch's `equipment_minutes`; if not, the request is rejected with `ERR_EQUIPMENT_CAPACITY_EXCEEDED`. Equipment-class capacity per day is 8 hours (480 minutes) per `equipment_class`, applied separately to each class. Second, the chosen window must satisfy shelf-life sufficiency: the `scheduled_start_at` plus `equipment_minutes` plus `Recipe.shelf_life_hours` must be greater than or equal to the `target_delivery_date` end-of-day at 23:59 UTC; otherwise `ERR_SHELF_LIFE_INSUFFICIENT`.

Scheduling itself follows shelf-life-aware sequencing. All `PLANNED` batches for the same `target_delivery_date` are sorted by ascending `Recipe.shelf_life_hours` (with `Recipe.recipe_code` ascending as the tie-break), and each batch is then placed on its `equipment_class` line by selecting the latest free contiguous window of length `equipment_minutes` whose start, plus `equipment_minutes`, plus `shelf_life_hours`, is still at or after the target date's 23:59 UTC. Because shorter shelf-life items are placed last, they reach stores fresher. The result writes `scheduled_start_at` and `scheduled_end_at` (the start plus equipment minutes, rounded up to whole minutes via ceiling) onto the batch. When two planners simultaneously schedule batches that would together exceed their equipment-class minute reservation for a day, the server serializes the reservation: the first writer succeeds; the second sees the first's reservation and is rejected with `ERR_EQUIPMENT_CAPACITY_EXCEEDED`.

Starting production transitions the batch from `SCHEDULED` to `IN_PRODUCTION`. The current instant must be at or after `scheduled_start_at`; tests use the clock-advance capability to reach that instant. Completion transitions from `IN_PRODUCTION` to `COMPLETED`, stamps `produced_at` with the current instant, and computes `expires_at` as `produced_at` plus `Recipe.shelf_life_hours`. Completion also runs the provisional cost allocation described in §3.6 and appends an audit row whose `external_systems` lists both `ERP` and `LOGISTICS`. A failed batch transitions from `IN_PRODUCTION` to `FAILED`; this reverts every linked `StoreOrder` from `CONSOLIDATED` back to `SUBMITTED` and clears its `consolidation_batch_id`, so those store orders re-enter the next consolidation run. Each reverted order has its `updated_at` refreshed, its `version` bumped, and an audit row appended.

### 3.4. Vehicles and Delivery Routes

A `Vehicle` is registered with a `vehicle_code`, an integer `capacity_units` (strictly positive), and a non-empty `temperature_zones` array (a subset of `{AMBIENT, CHILLED, FROZEN}` enumerating the zones the vehicle can maintain). New vehicles begin with `status` of `AVAILABLE`.

A `DeliveryRoute` is planned by `CentralKitchenPlanner`. The request body names a `vehicle_id`, a `driver_user_id` (the opaque user id of the assigned driver), a `target_delivery_date` (the ISO date all loaded `ProductionBatch` rows must share), and `planned_stops` — an ordered list of stop objects, each specifying `store_id`, a `time_window_start`, a `time_window_end`, and a `batch_ids` array enumerating the production batches loaded for that stop. From the stops the system computes `total_units_loaded` (the sum of batch units across stops, which must be at most `Vehicle.capacity_units`) and `required_zones` (the set-union of `Recipe.temperature_zone` across all batches loaded, which must be a subset of the vehicle's `temperature_zones`).

Dispatch transitions the route from `PLANNED` to `DISPATCHED`. Five preconditions must hold. The vehicle's `status` must be `AVAILABLE`; otherwise the request is rejected with `ERR_VEHICLE_NOT_AVAILABLE`. The route's `total_units_loaded` must be at most the vehicle's `capacity_units`; otherwise `ERR_VEHICLE_CAPACITY_EXCEEDED`. The route's `required_zones` must be a subset of the vehicle's `temperature_zones`; otherwise `ERR_TEMPERATURE_ZONE_INCOMPATIBLE`. Every loaded `ProductionBatch` must be in `COMPLETED` state; otherwise `ERR_BATCH_NOT_READY`. And no two stops on the same vehicle may have overlapping time windows: each stop's `time_window_start` must be strictly less than its `time_window_end`, and the stops' half-open intervals (start inclusive, end exclusive) must not overlap; otherwise `ERR_DELIVERY_WINDOW_OVERLAP`. On success, the vehicle's `status` flips from `AVAILABLE` to `ASSIGNED`, `dispatched_at` is stamped, and an audit row is appended with `external_systems` listing `LOGISTICS`. When two planners race to dispatch routes that share a vehicle, the server serializes on `Vehicle.status`: the first dispatch flips it to `ASSIGNED` and wins; the second loses with `ERR_VEHICLE_NOT_AVAILABLE`.

The driver subsequently transitions the route from `DISPATCHED` to `IN_TRANSIT` by departing — the request requires `X-User-ID` to match `driver_user_id` (otherwise `ERR_DRIVER_MISMATCH`). On the road, the driver may either complete the route or raise an exception. Completion (`IN_TRANSIT` to `COMPLETED`) again requires the driver match, stamps `completed_at`, flips the vehicle's `status` from `ASSIGNED` back to `AVAILABLE`, creates one `InventoryBatch` per stop at the receiving store (with `store_id` set from the stop, `recipe_id` and `production_batch_id` from the loaded batch, an initial `quantity_on_hand` equal to the loaded units, `received_at` stamped to now, `expires_at` copied from the originating `ProductionBatch.expires_at`, an `alert_tier` of `NONE`, and `status` of `ON_HAND`), and transitions every linked `StoreOrder` from `CONSOLIDATED` to `DELIVERED`. An audit row is appended with `external_systems` listing `LOGISTICS` and `POS`.

Raising an exception transitions the route from `IN_TRANSIT` to `EXCEPTION` and requires a non-empty `exception_reason` in the request body, which is recorded onto the route. Reroute (from `EXCEPTION` to `REROUTED`, action recorded as `EXCEPTION_REROUTE`) is invoked by the planner with a `replacement_vehicle_id`; the replacement vehicle must be `AVAILABLE` and must satisfy the same capacity and temperature-zone constraints as the original. On success the original vehicle's `status` flips from `ASSIGNED` back to `AVAILABLE`, the replacement's flips from `AVAILABLE` to `ASSIGNED`, the route's `vehicle_id` is updated, the `planned_stops` are preserved, and an audit row is appended with `external_systems` listing `LOGISTICS`. From `REROUTED` the driver may depart again (driver-match required), returning the route to `IN_TRANSIT`. If a driver completes a route while a planner simultaneously triggers a reroute on the same exception, exactly one operation succeeds and the loser receives `ERR_INVALID_STATE` because the state precondition is no longer met.

### 3.5. Inventory, Replenishment, and Near-Expiry Lifecycle

Inventory at a store is held as one or more `InventoryBatch` rows, each tracing back to one `ProductionBatch` via `production_batch_id`, with a current `quantity_on_hand` decremented by sales, transfers, losses, and disposal. Stock is created by route completion (§3.4) and progresses through `ON_HAND` to one of three terminal states: `DEPLETED`, `DISPOSED`, or `TRANSFERRED_OUT`.

A store manager may adjust a batch via the inventory adjust action, supplying a `delta` (positive or negative) and a free-text `reason`. If the resulting `quantity_on_hand` would equal zero exactly, the batch transitions from `ON_HAND` to `DEPLETED`; the requirement is `quantity_on_hand` plus `delta` equals zero. Depletion does not imply disposal — they are different terminal states.

The near-expiry alert sweep tags each `ON_HAND` `InventoryBatch` with an `alert_tier`. The hour distance is computed as the integer floor of `(expires_at - now()).total_seconds() / 3600`. If that distance is at most zero hours, `alert_tier` becomes `TIER3` (mandatory disposal). Otherwise, if the distance is at most 8 hours, `alert_tier` becomes `TIER2` (also a mandatory-disposal candidate). Otherwise, if the distance is at most 24 hours, `alert_tier` becomes `TIER1` (promotion or transfer recommended). Otherwise `alert_tier` is `NONE`. Boundaries are inclusive: a batch exactly 24 hours from expiry is `TIER1`, not `NONE`; a batch exactly 8 hours from expiry is `TIER2`, not `TIER1`.

A `TIER3` batch (or any batch whose `expires_at` is at or before the current instant) must be disposed of via the dispose action. Disposal transitions the batch from `ON_HAND` to `DISPOSED`, auto-creates a `LossRecord` whose `cause` is `SPOILAGE` and whose `quantity_lost` equals the batch's `quantity_on_hand` at disposal time, and appends an audit row whose action is `DISPOSE_STOCK` and whose payload archives the disposal record immutably. Transferring a `TIER3` batch is forbidden — the request is rejected with `ERR_TIER3_DISPOSAL_REQUIRED` — because `TIER3` must be disposed.

Inter-store transfer is permitted from `ON_HAND` to `TRANSFERRED_OUT` for batches whose `alert_tier` is either `TIER1` or `TIER2`; `NONE` batches have no near-expiry justification for a transfer and are also rejected. The body supplies `destination_store_id`. The destination store must have `status` of `ACTIVE`, and the destination's `temperature_zone` must support the recipe's `temperature_zone` — `MIXED` accommodates any zone, `AMBIENT` accommodates only `AMBIENT`, and so on. Otherwise the transfer is rejected with `ERR_TEMPERATURE_ZONE_INCOMPATIBLE`. On success, a new `InventoryBatch` is created at the destination store with `expires_at` copied from the original and a `quantity_on_hand` equal to the originating batch's quantity, the originating batch transitions to `TRANSFERRED_OUT`, and an audit row with action `INTER_STORE_TRANSFER` is appended whose `external_systems` lists `FINANCE`.

The replenishment sweep evaluates each `ReplenishmentRule` whose `status` is `ACTIVE`. A rule names a `recipe_id`, a `safety_stock_units` (the at-or-below threshold; non-negative), a `replenish_to_units` (the target stock level after replenishment, strictly greater than the safety stock), a `cycle_hours` (the minimum number of hours between evaluations of this rule, strictly positive), a server-maintained `velocity_multiplier` (a 1.0 baseline recomputed per ops-run from rolling sales velocity), and a `last_evaluated_at` timestamp. For each `ACTIVE` rule, if the current instant minus `last_evaluated_at` is less than `cycle_hours` (in hours), the rule is skipped. Otherwise, the system computes the on-hand quantity as the sum of `quantity_on_hand` across `InventoryBatch` rows for the same `(store_id, recipe_id)` whose `status` is `ON_HAND`. If the on-hand quantity is less than or equal to `safety_stock_units` (boundary inclusive — at exactly the safety threshold the rule still triggers), a replenishment `StoreOrder` is generated: the target unit count is `replenish_to_units` multiplied by `velocity_multiplier`, rounded up to the next whole unit (ceiling); the shortfall is that velocity-adjusted target minus the current on-hand quantity. The generated order has `status` of `DRAFT` and one `OrderLine` of `{recipe_id, quantity=shortfall}`, with a minimum replenishment of 1 unit. If the resulting `total_value_cents` is strictly less than the store's `low_amount_bypass_cents`, the order is auto-submitted (the bypass goes through the same `DRAFT`-to-`SUBMITTED` transition used by managers, but without a manager action); otherwise it stays `DRAFT` awaiting `StoreManager` review. The rule's `last_evaluated_at` is then stamped to the current instant, regardless of whether the rule fired or was skipped for the cycle, so the next sweep sees the elapsed cycle correctly.

A manager may also trigger a manual replenishment for a single rule. If the cycle has not elapsed since `last_evaluated_at` — that is, current instant minus `last_evaluated_at` is less than `cycle_hours` — the request is rejected with `ERR_REPLENISHMENT_CYCLE_NOT_ELAPSED`. If the sweep and a manual manager request race for the same `(store_id, recipe_id, current cycle window)`, only the first writer succeeds; the second is rejected with `ERR_REPLENISHMENT_DUPLICATE`. The system serializes on the tuple `(store_id, recipe_id, last_evaluated_at-bucketed-by-cycle_hours)`.

A rule may be moved between `ACTIVE` and `SUSPENDED` and back at any time — both transitions append an audit row but have no other side effects.

### 3.6. Loss Recording, Investigation, and Approval

A `LossRecord` is created via the loss-records endpoint by a store manager. The body supplies `inventory_batch_id`, an integer `quantity_lost` (strictly positive and at most the targeted batch's `quantity_on_hand` at recording time — otherwise `ERR_LOSS_EXCEEDS_ON_HAND`), a `cause` from `{SPOILAGE, DAMAGE, THEFT, PREPARATION}`, and an optional `responsibility_user_id`. Responsibility-attribution semantics are strict: when `cause` is `SPOILAGE`, `responsibility_user_id` must be omitted (or null); when `cause` is one of `DAMAGE`, `THEFT`, or `PREPARATION`, `responsibility_user_id` is required. Either mismatch is rejected with `ERR_RESPONSIBILITY_REQUIRED`.

Recording a loss has immediate inventory consequences: `InventoryBatch.quantity_on_hand` is decremented by `quantity_lost` at the moment of creation. The record itself is created with `status` of `RECORDED`. Its `financial_impact_cents` is computed as `quantity_lost` multiplied by `Recipe.unit_price_cents` at the time of recording and locked. An audit row with action `RECORD_LOSS` is appended.

At record creation the system also evaluates whether this event is abnormal. The event-level loss rate at the receiving store is computed over a rolling window of 168 hours (one week). The window-losses figure is the sum of `quantity_lost` across this store's `LossRecord` rows whose `created_at` is at or after `now() - 168 hours` and whose `status` is not `REVERSED`. The window-throughput figure is the sum of `OrderLine.quantity` across this store's `StoreOrder` rows whose `status` is `DELIVERED` and whose `updated_at` is at or after the window start. The loss rate is the window losses divided by the maximum of the window throughput and 1, evaluated in floating point. If that loss rate is strictly greater than 0.05 (5%) — the comparison is strict, so a rate of exactly 5% is not abnormal — the new record's `is_abnormal` is set to true and its `investigation_status` flips automatically from `NONE` to `PENDING`. Otherwise `is_abnormal` is false and `investigation_status` remains `NONE`.

A `FinanceController` resolves an abnormal investigation via the resolve-investigation action, optionally supplying `resolution_notes`; the action moves `investigation_status` to `RESOLVED`. Approval transitions the loss record from `RECORDED` to `APPROVED`. If the record is abnormal (`is_abnormal` is true), `investigation_status` must be `RESOLVED`; otherwise the approval is rejected with `ERR_INVESTIGATION_PENDING`. Approval bumps the version, refreshes `updated_at`, and appends an audit row with action `APPROVE_LOSS` whose `external_systems` lists `FINANCE`. Approval makes no further change to `InventoryBatch.quantity_on_hand` — that field was already decremented at record creation.

Reversal transitions the loss from `RECORDED` to `REVERSED`. Reversal is the only path that restores stock: the batch's `quantity_on_hand` is incremented by `quantity_lost`, compensating the decrement at recording. An audit row is appended.

### 3.7. Cost Allocation

Cost allocation runs in two phases. The provisional phase fires every time a `ProductionBatch` is completed: per-batch production cost is computed as the sum across the batch's `RecipeIngredient` rows of `quantity_per_unit` multiplied by `Ingredient.unit_cost_cents` multiplied by `ProductionBatch.planned_units`, plus a fixed batch setup fee of 100 cents. That total is then split across receiving stores in proportion to each store's share of the batch's `planned_units` (the share is each store's contributed `OrderLine.quantity` divided by `planned_units`). The rounding order is pinned: first, multiply the total cost by each store's share without an intermediate round; second, round each per-store value half-up to integer cents; third, sum the rounded per-store allocations; fourth, if that sum is not equal to the un-rounded total in cents, assign the remainder to the store with the largest share (breaking ties by lowest `Store.store_code`). Receiving stores are exactly the stores whose `SUBMITTED` orders contributed `OrderLine` rows that ended up in this batch — orders that cancelled before consolidation are excluded.

The final phase is run on demand by a `FinanceController` via the cost-allocation run action. The body supplies `period_start`, `period_end`, and `indirect_basis` — the basis discriminator chosen at run time, which must be either `SALES_VALUE` or `ORDER_VOLUME`. The run processes events with a timestamp in the half-open period (start inclusive, end exclusive), in chronological order — when two events share an exact timestamp, the tie-break is `AuditLogEntry.id` ascending. The events processed are batch completions, delivery completions, inter-store transfers, and recorded sales. Each contributes to running per-store accumulators as follows. **Direct production cost** is the sum of provisional allocations on `ProductionBatch.completed_at` instants in the period. **Transportation cost** is distributed across the stops on each route in proportion to the units loaded for each stop. **Indirect cost** is overhead allocated by the chosen basis: when `indirect_basis` is `SALES_VALUE`, indirect is allocated in proportion to `StoreOrder.total_value_cents`; when `indirect_basis` is `ORDER_VOLUME`, indirect is allocated in proportion to `StoreOrder.total_units` count. Indirect overhead is 15% of the direct production cost for the period (`INDIRECT_OVERHEAD_PCT` = 0.15). **Inter-store transfer cost** is the recipe's `unit_price_cents` multiplied by the transferred quantity multiplied by a transfer overhead rate of 0.10, charged to the sending store and refunded to the receiving store. The final per-store amount is the sum of the four buckets. Rounding is per `(store, cost_bucket)` pair, rounded half-up to integer cents and summed; any leftover-cent remainder lands on the top-volume store. `REVERSED` `LossRecord` rows are excluded from the run's loss-derived inputs. The two `indirect_basis` options form a deliberate dual-variant pair: identical period and stores, different per-store final allocations, with no automatic reconciliation.

### 3.8. Audit Log and External Synchronization

Every state-changing operation appends one immutable `AuditLogEntry`. Each row records the `target_type` (one of `InventoryBatch`, `LossRecord`, `StoreOrder`, `ProductionBatch`, `DeliveryRoute`), the `target_id`, a short verb in `action` (such as `ADJUST_STOCK`, `RECORD_LOSS`, `APPROVE_LOSS`, `DISPATCH_ROUTE`, `EXCEPTION_REROUTE`, `REPLENISHMENT_GENERATE`), the request actor's role in `actor_role`, `X-User-ID` in `actor_user_id`, a frozen JSON snapshot of relevant before/after fields in `payload`, and a list of synchronized peripheral systems in `external_systems` (drawn from `{POS, ERP, FINANCE, LOGISTICS}`). External synchronization is best-effort and fire-and-forget — the audit row is the system of record; downstream peripheral systems consume the entries asynchronously. The audit log is filterable by `target_type`, `target_id`, and `action` and is readable by `PlatformAdmin` and `FinanceController`.

## 4. Endpoint Definitions

The status-code rules across the API are uniform: a request that creates a new resource returns HTTP 201 with the created resource in `data`; a request that modifies an existing resource (including state transitions, header updates, action endpoints, and sweep runs) returns HTTP 200; list endpoints return HTTP 200 with an array in `data` and pagination fields in `meta`; failed requests return one of the 4xx codes named in §5 with an error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /supply-chain/stores | Create store | PlatformAdmin |
| GET | /supply-chain/stores | List stores | PlatformAdmin, CentralKitchenPlanner, FinanceController |
| GET | /supply-chain/stores/{id} | Read store | PlatformAdmin, CentralKitchenPlanner, FinanceController, StoreManager |
| PATCH | /supply-chain/stores/{id} | Update store catalog permission / windows | PlatformAdmin |
| POST | /supply-chain/recipes | Create recipe | CentralKitchenPlanner |
| GET | /supply-chain/recipes | List recipes | PlatformAdmin, CentralKitchenPlanner, StoreManager |
| GET | /supply-chain/recipes/{id} | Read recipe | PlatformAdmin, CentralKitchenPlanner, StoreManager |
| POST | /supply-chain/ingredients | Create ingredient | CentralKitchenPlanner |
| POST | /supply-chain/recipes/{id}/ingredients | Attach RecipeIngredient (BOM line) | CentralKitchenPlanner |
| POST | /supply-chain/store-orders | Create draft store order | StoreManager |
| POST | /supply-chain/store-orders/{id}/lines | Append order line (DRAFT only) | StoreManager |
| POST | /supply-chain/store-orders/{id}/submit | Submit order (DRAFT to SUBMITTED) | StoreManager |
| POST | /supply-chain/store-orders/{id}/cancel | Cancel order | StoreManager |
| PATCH | /supply-chain/store-orders/{id} | Modify draft order header | StoreManager |
| GET | /supply-chain/store-orders | List store orders (filterable) | PlatformAdmin, CentralKitchenPlanner, StoreManager |
| GET | /supply-chain/store-orders/{id} | Read store order | PlatformAdmin, CentralKitchenPlanner, StoreManager |
| POST | /supply-chain/production-batches/consolidate | Consolidate SUBMITTED orders for a date into ProductionBatches | CentralKitchenPlanner |
| GET | /supply-chain/production-batches | List production batches | CentralKitchenPlanner, FinanceController |
| GET | /supply-chain/production-batches/{id} | Read production batch | CentralKitchenPlanner, FinanceController |
| GET | /supply-chain/production-batches/{id}/forecast | Forecast variant (forward-looking) | CentralKitchenPlanner |
| POST | /supply-chain/production-batches/{id}/schedule | Schedule batch (PLANNED to SCHEDULED) | CentralKitchenPlanner |
| POST | /supply-chain/production-batches/{id}/start | Start production (SCHEDULED to IN_PRODUCTION) | CentralKitchenPlanner |
| POST | /supply-chain/production-batches/{id}/complete | Complete production (IN_PRODUCTION to COMPLETED) | CentralKitchenPlanner |
| POST | /supply-chain/production-batches/{id}/fail | Fail production (IN_PRODUCTION to FAILED) | CentralKitchenPlanner |
| POST | /supply-chain/vehicles | Register vehicle | PlatformAdmin |
| GET | /supply-chain/vehicles | List vehicles | PlatformAdmin, CentralKitchenPlanner |
| POST | /supply-chain/delivery-routes | Plan a delivery route (PLANNED) | CentralKitchenPlanner |
| GET | /supply-chain/delivery-routes | List delivery routes | CentralKitchenPlanner, Driver |
| POST | /supply-chain/delivery-routes/{id}/dispatch | Dispatch route (PLANNED to DISPATCHED) | CentralKitchenPlanner |
| POST | /supply-chain/delivery-routes/{id}/depart | Driver departs (DISPATCHED or REROUTED to IN_TRANSIT) | Driver |
| POST | /supply-chain/delivery-routes/{id}/complete | Driver completes (IN_TRANSIT to COMPLETED) | Driver |
| POST | /supply-chain/delivery-routes/{id}/raise-exception | Raise exception (IN_TRANSIT to EXCEPTION) | Driver |
| POST | /supply-chain/delivery-routes/{id}/reroute | Reroute (EXCEPTION to REROUTED) | CentralKitchenPlanner |
| GET | /supply-chain/inventory-batches | List inventory at a store (filterable) | StoreManager, CentralKitchenPlanner, FinanceController |
| POST | /supply-chain/inventory-batches/{id}/adjust | Adjust quantity (delta, with reason) | StoreManager |
| POST | /supply-chain/inventory-batches/{id}/transfer | Transfer to peer store | StoreManager |
| POST | /supply-chain/inventory-batches/{id}/dispose | Mandatory disposal (TIER3 or expired) | StoreManager |
| POST | /supply-chain/replenishment-rules | Create replenishment rule | StoreManager |
| GET | /supply-chain/replenishment-rules | List replenishment rules | StoreManager, CentralKitchenPlanner |
| POST | /supply-chain/replenishment-rules/{id}/suspend | Suspend rule | StoreManager |
| POST | /supply-chain/replenishment-rules/{id}/activate | Activate rule | StoreManager |
| POST | /supply-chain/replenishment-rules/{id}/manual-replenish | Manually trigger replenishment for this rule (cycle must have elapsed) | StoreManager |
| POST | /supply-chain/loss-records | Record a loss (creates record in RECORDED, decrements InventoryBatch.quantity_on_hand) | StoreManager |
| GET | /supply-chain/loss-records | List loss records | StoreManager, FinanceController, CentralKitchenPlanner |
| POST | /supply-chain/loss-records/{id}/approve | Approve loss (RECORDED to APPROVED) | FinanceController |
| POST | /supply-chain/loss-records/{id}/reverse | Reverse loss (RECORDED to REVERSED) | FinanceController |
| POST | /supply-chain/loss-records/{id}/resolve-investigation | Mark abnormal loss investigation_status RESOLVED | FinanceController |
| POST | /supply-chain/cost-allocations/run | Run final period cost allocation (chronological) | FinanceController |
| GET | /supply-chain/audit-log | List audit log entries (filterable) | PlatformAdmin, FinanceController |
| POST | /supply-chain/_clock/advance | Advance the simulated clock (test-only) | PlatformAdmin |
| POST | /supply-chain/_sweep/expiry-alerts | Run the near-expiry alert sweep (ops-run checkpoint) | PlatformAdmin |
| POST | /supply-chain/_sweep/replenish | Run replenishment sweep (ops-run checkpoint) | PlatformAdmin |
| POST | /supply-chain/_events/emit | Emit a synthetic external event (POS sale, ERP update) for tests | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 409 |
| ERR_CATALOG_PERMISSION_DENIED | 422 |
| ERR_ORDER_WINDOW_CLOSED | 422 |
| ERR_ORDER_CUTOFF_PASSED | 422 |
| ERR_QUANTITY_OUT_OF_RANGE | 422 |
| ERR_EQUIPMENT_CAPACITY_EXCEEDED | 422 |
| ERR_SHELF_LIFE_INSUFFICIENT | 422 |
| ERR_VEHICLE_NOT_AVAILABLE | 409 |
| ERR_VEHICLE_CAPACITY_EXCEEDED | 422 |
| ERR_TEMPERATURE_ZONE_INCOMPATIBLE | 422 |
| ERR_DELIVERY_WINDOW_OVERLAP | 422 |
| ERR_BATCH_NOT_READY | 422 |
| ERR_DRIVER_MISMATCH | 403 |
| ERR_TIER3_DISPOSAL_REQUIRED | 422 |
| ERR_RESPONSIBILITY_REQUIRED | 422 |
| ERR_LOSS_EXCEEDS_ON_HAND | 422 |
| ERR_INVESTIGATION_PENDING | 422 |
| ERR_REPLENISHMENT_CYCLE_NOT_ELAPSED | 422 |
| ERR_REPLENISHMENT_DUPLICATE | 409 |
