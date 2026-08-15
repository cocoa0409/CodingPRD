# Tortilla & Masa Production API — Product Requirements Document

## 1. Introduction

Tortilla manufacturing lives at the intersection of food chemistry and route logistics. Corn must be nixtamalized, steeped, milled, and moisture-corrected before it becomes masa; masa must be scheduled onto production lines whose allergen zoning and changeover downtime constrain what can run where and when; finished cases must clear weight-and-count verification before they are sealed; sealed cases must be allocated onto DSD routes against vehicle capacity, customer shelf-life floors, credit standing, and — during Cinco de Mayo or Navidad-tamales spikes — strict seasonal allotments. Every one of these steps is a gate that can fail, and every failure has a specific business consequence: a quarantined batch demotes the runs it was feeding, a failed changeover blocks the next run from starting, a shorted stop refunds a seasonal allotment.

This document specifies the Tortilla & Masa Production API, a single-tenant REST surface mounted under `/plant` that models the full nixtamal-to-delivery lifecycle for a corn tortilla manufacturer serving retail, tortilleria, and foodservice Hispanic-market channels. The API is built around seven roles with strict segregation of duties — the sanitation technician who performs a changeover can never verify it — and around a set of conservation invariants that keep masa kilograms, packed cases, and route capacity honest across every cascade. A logical clock, settable only by plant management, drives every time-gated validation so the system is fully deterministic under test.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two authentication headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the seven declared below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The seven roles are `PlantManager`, `MillerOperator`, `QualityInspector`, `LineScheduler`, `SanitationTech`, `PackagingLead`, and `RouteDispatcher`. All seven roles share read access to every list and detail endpoint; write operations are exclusive to a single role.

- `PlantManager` — plant administration: products, lines, customers, seasonal windows, corn lot intake, and the logical clock.
- `MillerOperator` — nixtamalization floor: lot conditioning and the batch cook/steep/mill lifecycle.
- `QualityInspector` — quality gate: batch evaluation and quarantine, run QC hold and release, changeover verification; never the changeover performer.
- `LineScheduler` — line scheduling and masa allocation.
- `SanitationTech` — performs changeover sanitation; barred by segregation of duties from verifying own work.
- `PackagingLead` — packaging hall: pack orders, weight/count verification, seal and reject.
- `RouteDispatcher` — DSD logistics: routes and stops for retail, tortilleria, and foodservice channels.

All seven roles carry an **opaque** identity. When `X-User-Role` is `PlantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `MillerOperator`, `QualityInspector`, `LineScheduler`, `SanitationTech`, `PackagingLead`, or `RouteDispatcher` — in each case `X-User-ID` is opaque. The server may record it: specifically, when a `SanitationTech` begins a changeover, the acting `X-User-ID` is written to `performed_by` on the `ChangeoverRecord`, and subsequent verification compares against that recorded value rather than against any persisted user entity.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0. List responses sort by `created_at` ascending. The `meta` block of a list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity carries `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that increments on every mutation of that entity). All entities in this domain carry the full set of common fields; none is a thin join-table with `updated_at` and `version` absent.

The server maintains a **logical clock** that governs every time-gated validation: cook duration, steep duration, shelf-life remaining days, and seasonal window activation dates. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. A `PlantManager` advances it via an admin-only test-driving capability that takes a `to_iso8601` payload; advancing the clock causes time-gated validations to re-evaluate against the new clock value. Clock timestamps written by the system — `cook_started_at`, `steep_started_at`, `sealed_at` — always record the logical clock value at the moment the corresponding transition succeeded.

### 2.5. Numeric Precision and Rounding

Two precision regimes coexist, and the choice is fixed per field. Quantities expressed to two decimal places — `theoretical_masa_kg`, `actual_masa_kg`, `masa_wasted_kg`, `masa_available_kg`, `yield_variance_pct`, `masa_required_kg`, `count_accuracy_pct` — are rounded **half-up to 2 decimal places**. Weights expressed to one decimal place — `declared_pack_net_g`, `declared_case_net_g`, `avg_pack_weight_g` — are rounded **half-up to 1 decimal place**. In every case, rounding to the declared precision happens **before** any downstream band or threshold comparison: the rounded value, not the raw value, is what gets compared against a tolerance band.

### 2.6. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control; no other endpoint takes a version field.

Creating a production run requires `expected_line_version` as a non-optional input field carrying the client's last observed `version` of the target `ProductionLine`. If the line's current `version` has advanced since the client last read it — because another writer scheduled a run, started a run, or toggled line status — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from scheduling against a stale view of the line.

Adding a route stop requires `expected_route_version` as a non-optional input field carrying the client's last observed `version` of the parent `Route`. If the route's current `version` has advanced since the client last read it — because a prior stop creation legitimately advanced it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from allocating against a stale view of route capacity.

### 2.7. Hierarchical Consistency and Cascading Mutation

Mutations propagate immediately and are visible in the same request response. When a batch is quarantined, three cascades fire in order: every `BatchAllocation` of that batch in `RESERVED` flips to `RELEASED` and the batch's `masa_available_kg` is restored per release; each affected run has its `masa_reserved_kg` recomputed, and any run in `SCHEDULED` whose recomputed `masa_reserved_kg` now falls below its `masa_required_kg` demotes from `SCHEDULED` to `PLANNED`; and each demoted run's gating `ChangeoverRecord`, if still in `REQUIRED`, `IN_PROGRESS`, or `FAILED`, flips to `CANCELLED`, and the owning line's `line_posture` is recomputed. The same cascade fires when a quarantined batch is rejected outright — the release step is idempotent because the allocations were already released at quarantine time.

When a run is cancelled, every `RESERVED` allocation of that run flips to `RELEASED` and the batch's `masa_available_kg` is restored, every non-terminal child `PackOrder` flips to `CANCELLED`, and the gating `ChangeoverRecord`, if in `REQUIRED`, `IN_PROGRESS`, or `FAILED`, flips to `CANCELLED`. When a route is cancelled, every `ALLOCATED` stop flips to `SHORTED`, the pack's `cases_available` is restored, and any seasonal allotment that consumed the allocation is refunded. Every mutation bumps the mutated entity's `version` and refreshes its `updated_at`.

### 2.8. Nested Resource Retrieval

Endpoints with multi-segment paths validate path parameters **left to right**: the parent identifier is resolved first, and only if the parent exists is the child identifier resolved against it. A request naming a non-existent parent yields `ERR_NOT_FOUND` regardless of whether the child exists. This ordering applies uniformly across nested routes — a lot's batches, a line's runs and changeovers, a run's allocations, pack orders and changeovers, a window's allotments, a customer's stops and allotments, a route's stops.

### 2.9. Validation Priority Order

When a request triggers multiple validations, they are evaluated in a fixed priority order, and the first failure surfaces its error; later failures are masked. The order, from highest priority to lowest, is:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted for this endpoint (`ERR_FORBIDDEN`), and segregation of duties on changeover verify and fail (`ERR_SOD_VIOLATION`).
3. Request shape and enums — required fields present, types correct, declared enum members only (`ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`, `ERR_VALIDATION` for numeric semantic ranges such as `delivered_cases` not exceeding `allocated_cases`, `lime_pct` inside its band, `cook_minutes` at least 30, `steep_target_hours` at least 8).
4. Existence — path ids and foreign-key references resolve (`ERR_NOT_FOUND`).
5. State — OCC stale-version checks and target-entity from-state checks (`ERR_STALE_VERSION`, `ERR_BATCH_INVALID_STATE`, `ERR_LOT_INVALID_STATE`, `ERR_RUN_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`, `ERR_CHANGEOVER_INVALID_STATE`, `ERR_PACK_INVALID_STATE`, `ERR_PACK_NOT_SEALED`, `ERR_ROUTE_INVALID_STATE`, `ERR_STOP_INVALID_STATE`, `ERR_WINDOW_INVALID_STATE`, `ERR_PRODUCT_DISCONTINUED`).
6. Business safety — allergen zone, shelf-life gate, QC hold, changeover verification (`ERR_ALLERGEN_ZONE_VIOLATION`, `ERR_SHELF_LIFE_INSUFFICIENT`, `ERR_QC_HOLD_ACTIVE`, `ERR_CHANGEOVER_NOT_VERIFIED`).
7. Business temporal — cook, steep, line-window overlap, changeover buffer, seasonal-window overlap (`ERR_COOK_INCOMPLETE`, `ERR_STEEP_INCOMPLETE`, `ERR_LINE_WINDOW_OVERLAP`, `ERR_CHANGEOVER_WINDOW_INSUFFICIENT`, `ERR_WINDOW_DATE_OVERLAP`).
8. Business constraint — masa, line capacity, route capacity, pack stock, weight-check sample, code uniqueness (`ERR_MASA_INSUFFICIENT`, `ERR_LINE_CAPACITY_EXCEEDED`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_PACK_STOCK_INSUFFICIENT`, `ERR_WEIGHT_SAMPLE_INVALID`, `ERR_DUPLICATE_CODE`).
9. Business fiscal — customer credit and seasonal allotment (`ERR_CUSTOMER_CREDIT_HOLD`, `ERR_ALLOTMENT_EXCEEDED`).
10. Business referential — run completion, route completion, product discontinue, route dispatch preconditions (`ERR_UNRESOLVED_PACK_ORDERS`, `ERR_RUN_CASE_SHORTFALL`, `ERR_UNRESOLVED_STOPS`, `ERR_PRODUCT_IN_USE`, `ERR_ROUTE_EMPTY`).

So, for example, a stale-version rejection surfaces before an allergen-zone violation, and a missing foreign key surfaces before either.

### 2.10. Conservation Invariants

Two conserved quantities govern the domain. The **masa conservation invariant** states that for any nixtamal batch, `actual_masa_kg` always equals `masa_available_kg` plus the sum of `allocated_kg` over that batch's allocations in `RESERVED` or `CONSUMED`. Allocation moves kilograms from `masa_available_kg` into `RESERVED`; release moves them back; consume re-labels `RESERVED` to `CONSUMED` — the forward and compensating pair leaves the sum unchanged.

The **case load invariant** states that for any pack order, `cases_packed` always equals `cases_available` plus the sum of `allocated_cases` over route stops in `ALLOCATED` or `DELIVERED` that reference this pack. Stop creation moves cases from `cases_available` into `ALLOCATED`; shorting moves them back; delivery keeps the label without restock because the route has already dispatched. On the route side, `committed_cases` is the sum of `allocated_cases` over stops in `ALLOCATED` or `DELIVERED`, and `open_cases` is `vehicle_capacity_cases` minus `committed_cases`.

## 3. Business Logic & Workflows

### 3.1. Corn Receiving and Lot Conditioning

Corn arrives at the mill dock and a `PlantManager` receives it by declaring its `lot_code`, `corn_variety` (`WHITE_CORN`, `YELLOW_CORN`, or `BLUE_CORN`), gross `received_kg`, and the kernel `moisture_pct` measured at receipt. `received_kg` must be greater than zero, and `moisture_pct` must lie strictly between 0 and 30. The `lot_code` must be unique across all ingredient lots; a duplicate is rejected with `ERR_DUPLICATE_CODE`. A new lot enters in `lot_status` `RECEIVED`.

A `MillerOperator` then conditions the lot before it can feed a batch. Conditioning from `RECEIVED` to `CONDITIONED` is the default outcome; the same action with `decision` set to `REJECT` instead drives the lot from `RECEIVED` to terminal `REJECTED`. Either way, attempting the action against a lot not currently in `RECEIVED` is rejected with `ERR_LOT_INVALID_STATE`.

Two computed fields track draw-down. `drawn_kg` is the sum of `corn_kg` over all non-`REJECTED` batches that name this lot as their `ingredient_lot_id`. `available_kg` is `received_kg` minus `drawn_kg` and is never negative. When a batch draw pushes `available_kg` to exactly zero, the lot auto-transitions from `CONDITIONED` to terminal `DEPLETED` without any explicit action.

### 3.2. Nixtamalization: Cook, Steep, Mill

A `MillerOperator` creates a nixtamalization batch by naming the source lot via `ingredient_lot_id` and declaring `corn_kg`, `lime_pct`, `cook_minutes`, and `steep_target_hours`. `corn_kg` must be greater than zero and may not exceed the lot's current `available_kg`. `lime_pct` must lie between 0.1 and 2.0 inclusive. `cook_minutes` must be at least 30; `steep_target_hours` must be at least 8. Creation computes the batch's provisional yield: `theoretical_masa_kg` is `corn_kg` multiplied by a variety yield factor looked up from the linked lot's `corn_variety` — 1.70 for `WHITE_CORN`, 1.65 for `YELLOW_CORN`, 1.60 for `BLUE_CORN` — rounded half-up to two decimal places. The batch enters in `batch_status` `PLANNED`, and `recook_count` starts at zero. Creation also adds `corn_kg` to the lot's `drawn_kg`, recomputes `available_kg`, and may trigger the lot's automatic transition from `CONDITIONED` to `DEPLETED` as described above.

A `MillerOperator` starts the cook. The batch must be in `PLANNED` — otherwise `ERR_BATCH_INVALID_STATE` — and the linked lot must be in `CONDITIONED` — otherwise `ERR_LOT_INVALID_STATE`. A successful start stamps `cook_started_at` with the logical clock's current value and advances the batch to `COOKING`.

A `MillerOperator` starts the steep. The batch must be in `COOKING`, and the logical clock must show at least `cook_minutes` elapsed since `cook_started_at`; an early attempt is rejected with `ERR_COOK_INCOMPLETE`. A successful start stamps `steep_started_at` and advances the batch to `STEEPING`.

A `QualityInspector` evaluates the steeped batch. The batch must be in `STEEPING` and the logical clock must show at least `steep_target_hours` elapsed since `steep_started_at`; an early evaluation is rejected with `ERR_STEEP_INCOMPLETE`. The evaluation carries a `decision`: `PASS` advances the batch to `MILLING`; `RECOOK` loops the batch back to `COOKING`, increments `recook_count` by one, and resets `cook_started_at` to the current logical clock (the steep clock resets on the recook loop); `REJECT` drives the batch to terminal `REJECTED`. The same `REJECT` decision is also honored from `QUARANTINED`, again driving the batch to terminal `REJECTED`.

A `MillerOperator` mills a batch in `MILLING`, supplying `milled_masa_kg`, `measured_moisture_pct`, and `masa_wasted_kg`. The final yield differs from the provisional one: net milled kilograms are `milled_masa_kg` minus `masa_wasted_kg`; a moisture penalty is computed as the amount by which `measured_moisture_pct` exceeds the target masa moisture of 55 percent, divided by 100, floored at zero (so a batch milled at or below target carries no penalty); `actual_masa_kg` is the net milled kilograms multiplied by one minus the moisture penalty, rounded half-up to two decimal places. `masa_available_kg` initializes to `actual_masa_kg`. `yield_variance_pct` is the difference between `actual_masa_kg` and `theoretical_masa_kg`, divided by `theoretical_masa_kg`, multiplied by 100, rounded half-up to two decimal places; it remains null until mill. The batch advances to `MASA_AVAILABLE`. `masa_wasted_kg` is informational — it has already been netted inside `actual_masa_kg`.

### 3.3. Masa Allocation and Quarantine Cascade

A `LineScheduler` reserves masa from a batch in `MASA_AVAILABLE` for a run in `PLANNED` or `SCHEDULED` by creating a batch allocation naming `nixtamal_batch_id`, `production_run_id`, and `allocated_kg`. `allocated_kg` must be greater than zero and may not exceed the batch's current `masa_available_kg`; an over-allocation is rejected with `ERR_MASA_INSUFFICIENT`. Creation subtracts `allocated_kg` from the batch's `masa_available_kg`, recomputes the run's `masa_reserved_kg` (the sum of `allocated_kg` over that run's `RESERVED` allocations), and enters the allocation in `allocation_status` `RESERVED`.

Releasing an allocation flips it from `RESERVED` to terminal `RELEASED`, adds `allocated_kg` back to the batch's `masa_available_kg`, and recomputes the run's `masa_reserved_kg`; if a `SCHEDULED` run's coverage drops below its `masa_required_kg` as a result, the run demotes to `PLANNED` and its gating changeover, if in `REQUIRED`, `IN_PROGRESS`, or `FAILED`, cancels. Consuming an allocation flips it from `RESERVED` to terminal `CONSUMED`; the batch may auto-transition from `MASA_AVAILABLE` to terminal `DEPLETED` when `masa_available_kg` reaches zero and `actual_masa_kg` is greater than zero. Both release and consume require the allocation to currently be in `RESERVED` — otherwise `ERR_ALLOCATION_INVALID_STATE` — and consume additionally requires the linked run to be in `SCHEDULED` or `IN_PROGRESS` — otherwise `ERR_RUN_INVALID_STATE`.

A `QualityInspector` quarantines a batch in `MASA_AVAILABLE`, driving it to `QUARANTINED` and firing the three-link cascade described in §2.7: reserved allocations release with masa restored, demoted runs drop to `PLANNED`, and their gating changeovers cancel. Releasing the quarantine returns the batch from `QUARANTINED` to `MASA_AVAILABLE` with no cascade. Rejecting a quarantined batch via evaluation drives it to terminal `REJECTED` and re-fires the same cascade idempotently.

### 3.4. Product Configuration and Declared Weights

A `PlantManager` creates a product by declaring `sku_code`, `diameter_in` (`D6`, `D8`, `D10`, or `D12` inches), `count_per_pack`, `packs_per_case`, `unit_weight_g` in grams, `channel` (`RETAIL` or `FOODSERVICE`), `preservative_system` (`NONE`, `PROPIONATE`, or `FUMARIC_ACID`), `allergen_class` (`CORN_ONLY`, `WHEAT_FLOUR`, or `SOY_BLENDED`), and optionally `weight_tolerance_pct`. `count_per_pack`, `packs_per_case`, and `unit_weight_g` must each be greater than zero. `weight_tolerance_pct` defaults to 2.0 when omitted and must be greater than zero. The `sku_code` must be unique; a duplicate is rejected with `ERR_DUPLICATE_CODE`.

Two fields derive from `preservative_system` and the declared weights. `shelf_life_days` is 5 when `preservative_system` is `NONE`, 20 when it is `PROPIONATE`, and 45 when it is `FUMARIC_ACID`. Declared weights follow a **pinned rounding order**: `declared_pack_net_g` is `unit_weight_g` multiplied by `count_per_pack`, rounded half-up to one decimal place, computed per-pack first; `declared_case_net_g` is then `declared_pack_net_g` multiplied by `packs_per_case`, rounded half-up to one decimal place. Rounding the raw per-case product in one step is forbidden — the per-pack-then-per-case order is normative. A new product enters in `product_status` `ACTIVE`.

A `PlantManager` discontinues a product. The product must currently be `ACTIVE` — otherwise `ERR_PRODUCT_DISCONTINUED` — and no production run naming this product may exist in `PLANNED`, `SCHEDULED`, or `IN_PROGRESS` — otherwise `ERR_PRODUCT_IN_USE`. Discontinuation drives the product to terminal `DISCONTINUED`.

### 3.5. Line Setup, Run Scheduling, and the Changeover Gate

A `PlantManager` creates a production line by declaring `line_code`, `allergen_zone` (`DEDICATED_CORN` or `SHARED`), and `cases_per_hour`. `cases_per_hour` must be greater than zero; the `line_code` must be unique. A new line enters with `line_status` `ACTIVE`, `line_posture` `AVAILABLE`, and `current_product_id` null. The `PlantManager` may also take a line down or return it to service via a set-status action supplying `line_status`; taking a line down is blocked while any run on that line is `IN_PROGRESS` (`ERR_RUN_INVALID_STATE`), and every status toggle increments the line's `version` by one. `line_posture` is a computed gate, not a stored state: it reads `RUNNING` if any run on the line is `IN_PROGRESS`, else `CHANGEOVER_PENDING` if any changeover on the line is in `REQUIRED`, `IN_PROGRESS`, or `FAILED`, else `AVAILABLE`. A `DOWN` line blocks new run creation.

A `LineScheduler` creates a run against a line by supplying `product_id`, `line_id`, `planned_cases`, `start_at`, `end_at`, and `expected_line_version`. `planned_cases` must be greater than zero; `end_at` must be strictly after `start_at` (a non-positive window is rejected with `ERR_INVALID_REQUEST`). The referenced product must be `ACTIVE` — a `DISCONTINUED` product yields `ERR_PRODUCT_DISCONTINUED`. The referenced line must be `ACTIVE` — a `DOWN` line yields `ERR_RUN_INVALID_STATE`. The OCC check described in §2.6 fires at this point. Allergen zoning is then enforced: a product with `allergen_class` `WHEAT_FLOUR` or `SOY_BLENDED` may not be scheduled on a `DEDICATED_CORN` line — violation yields `ERR_ALLERGEN_ZONE_VIOLATION`.

The run's time window is a **half-open interval** `[start_at, end_at)`: two sibling runs on the same line overlap when the first's `start_at` is before the second's `end_at` and the first's `end_at` is after the second's `start_at`. Adjacency — one run's `end_at` exactly equal to the next's `start_at` — is **not** a conflict. Only sibling runs on the same line whose `production_status` is not `CANCELLED` participate in the comparison. An overlap is rejected with `ERR_LINE_WINDOW_OVERLAP`. Line throughput is also enforced: `planned_cases` may not exceed `cases_per_hour` multiplied by the window length in hours; an overrun is rejected with `ERR_LINE_CAPACITY_EXCEEDED`.

When the immediately-preceding non-`CANCELLED` run on the line used a different product, a **product-switch buffer** is additionally required: the new run's `start_at` must be at least the previous run's `end_at` plus the `required_downtime_min` of the changeover that would be required between the two products; a shortfall is rejected with `ERR_CHANGEOVER_WINDOW_INSUFFICIENT`. In this same product-switch case, run creation auto-creates a gating `ChangeoverRecord` in `REQUIRED` with its `required_level` and `required_downtime_min` computed per §3.6. Run creation also computes `masa_required_kg` as `planned_cases` multiplied by `packs_per_case` multiplied by `count_per_pack` multiplied by `unit_weight_g`, divided by 1000, multiplied by the masa loss factor 1.05, rounded to two decimal places — and increments the line's `version` by one. The new run enters with `production_status` `PLANNED` and `qc_status` `PENDING`.

A `LineScheduler` confirms a planned run, advancing `production_status` from `PLANNED` to `SCHEDULED`. Starting the run requires the run to be in `SCHEDULED`, requires any gating `ChangeoverRecord` to be `VERIFIED` (otherwise `ERR_CHANGEOVER_NOT_VERIFIED`), and requires full masa coverage — the sum of `allocated_kg` over the run's `RESERVED` allocations must be at least `masa_required_kg` (otherwise `ERR_MASA_INSUFFICIENT`). A successful start flips every `RESERVED` allocation of the run to `CONSUMED`, sets the line's `current_product_id` to this run's product, increments the line's `version` by one, recomputes `line_posture` to `RUNNING`, and advances the run to `IN_PROGRESS`.

A `LineScheduler` completes a run in `IN_PROGRESS`. Every child `PackOrder` must be in a terminal state — `SEALED`, `REJECTED`, or `CANCELLED` — otherwise `ERR_UNRESOLVED_PACK_ORDERS`. `produced_cases` — the sum of `cases_packed` over the run's `SEALED` pack orders — must be at least `planned_cases` multiplied by 0.95 and rounded up to a whole number; a shortfall is rejected with `ERR_RUN_CASE_SHORTFALL`. Completion finalizes `produced_cases` and advances the run to `COMPLETED`.

Cancelling a run is permitted from `PLANNED`, `SCHEDULED`, or `IN_PROGRESS` and drives the run to terminal `CANCELLED`. The cascade releases every `RESERVED` allocation (restoring batch `masa_available_kg`), cancels every non-terminal child `PackOrder`, and cancels the gating `ChangeoverRecord` if in `REQUIRED`, `IN_PROGRESS`, or `FAILED`. `CONSUMED` allocations are **not** reversed by cancellation.

In parallel to `production_status`, every run carries an independent `qc_status` dimension. A `QualityInspector` places a run on QC hold, moving `qc_status` from `PENDING` to `ON_HOLD`; the run must not already be `COMPLETED` or `CANCELLED`. Releasing the hold moves `qc_status` from `ON_HOLD` to `PASSED`. The two dimensions advance independently — a run may be `IN_PROGRESS` and `ON_HOLD` simultaneously — and the QC dimension gates pack sealing as described in §3.7.

### 3.6. Changeover Sanitation and Segregation of Duties

When a run is created against a line whose previous non-`CANCELLED` run used a different product, the system auto-creates a `ChangeoverRecord` in `changeover_status` `REQUIRED`. A `SanitationTech` may also register one manually, supplying `line_id`, `from_product_id`, and `to_product_id` — for example, end-of-shift sanitation without a gated run; manual records carry a null `production_run_id`.

The required cleaning level derives from the allergen classes and diameters of the from-product and to-product. Allergen classes are ranked: `CORN_ONLY` is rank 0, `WHEAT_FLOUR` is rank 1, `SOY_BLENDED` is rank 2. When both products share the same allergen class, the level is `FLUSH` if their `diameter_in` values match, else `WET_WASH`. When the from-product's rank exceeds the to-product's rank — an allergen downgrade, moving to a stricter product — the level is `FULL_SANITATION`. Otherwise — an allergen upgrade — the level is `WET_WASH`. Base downtime is 30 minutes for `FLUSH`, 60 for `WET_WASH`, 120 for `FULL_SANITATION`. A diameter penalty of 15 additional minutes applies when the two products' `diameter_in` values differ and the level is not `FULL_SANITATION`. `required_downtime_min` is the base plus the diameter penalty.

A `SanitationTech` begins the work from `REQUIRED` or `FAILED`, advancing the record to `IN_PROGRESS` and stamping `performed_by` with the acting `X-User-ID`. A `QualityInspector` then verifies or fails the work. Verification advances the record from `IN_PROGRESS` to `VERIFIED` and recomputes the owning line's `line_posture`. Failure returns it from `IN_PROGRESS` to `FAILED` and increments `fail_count` by one. Segregation of duties is enforced at both gates: the verifying or failing inspector's `X-User-ID` must differ from the recorded `performed_by` — a match is rejected with `ERR_SOD_VIOLATION`. A `FAILED` record can be re-begun by a `SanitationTech`, looping back to `IN_PROGRESS`. When the run a changeover gates is cancelled or demoted, the changeover auto-cancels from `REQUIRED`, `IN_PROGRESS`, or `FAILED` to terminal `CANCELLED`.

### 3.7. Packaging, Weight Verification, and Sealing

A `PackagingLead` opens a pack order under a run by supplying `production_run_id`, `cases_planned`, and `verification_method` (`AVERAGE_WEIGHT` or `COUNT_VERIFY`). `cases_planned` must be greater than zero. `verification_method` is immutable after creation. The new pack order enters in `pack_status` `OPEN`.

Starting to pack requires the pack order to be in `OPEN` and the parent run to be `IN_PROGRESS` — otherwise `ERR_PACK_INVALID_STATE` or `ERR_RUN_INVALID_STATE` respectively — and advances the pack order to `PACKING`.

The weight check is the quality gate and accepts a payload of `cases_packed`, `sample_weights_g`, and `sample_counts`. Only the array matching the pack order's declared `verification_method` is evaluated; supplying the wrong array, or a sample with cardinality below 3, is rejected with `ERR_WEIGHT_SAMPLE_INVALID`. The check is permitted from `PACKING` or `HOLD` — the rework loop — and produces one of two outcomes.

Under `AVERAGE_WEIGHT`, the declared pack net weight and the product's `weight_tolerance_pct` define an inclusive band: the lower bound is `declared_pack_net_g` multiplied by one minus `weight_tolerance_pct` divided by 100; the upper bound is `declared_pack_net_g` multiplied by one plus `weight_tolerance_pct` divided by 100. `avg_pack_weight_g` is the mean of `sample_weights_g` rounded half-up to one decimal place, and the check passes when the rounded average lies at or above the lower bound and at or below the upper bound; individual piece counts are ignored.

Under `COUNT_VERIFY`, the check passes when **every** entry of `sample_counts` equals the product's `count_per_pack` **and** the average pack weight is at or above the lower bound — the upper band is not applied. `count_accuracy_pct` is the share of sampled packs with exactly `count_per_pack` pieces, expressed as a percentage to two decimal places.

A passing check advances the pack order from `PACKING` to `PASSED` (or from `HOLD` back to `PASSED` on a re-test) and records `cases_packed`, `avg_pack_weight_g`, and — for `COUNT_VERIFY` — `count_accuracy_pct`. A failing check moves the pack order from `PACKING` to `HOLD` and still records the failed metrics — `avg_pack_weight_g` and `count_accuracy_pct` are updated even on failure. The same physical cartons can pass under `AVERAGE_WEIGHT` and fail under `COUNT_VERIFY`.

Sealing requires the pack order to be in `PASSED` and the parent run's `qc_status` to be anything other than `ON_HOLD` — sealing against an active QC hold is rejected with `ERR_QC_HOLD_ACTIVE`. A successful seal stamps `sealed_at` with the logical clock, computes `expires_on` as the ISO date `sealed_at` plus the product's `shelf_life_days`, initializes `cases_available` to `cases_packed`, and advances the pack order to terminal `SEALED`. Rejecting a pack order is permitted from `OPEN`, `PACKING`, or `HOLD` and drives it to terminal `REJECTED`. Cancelling the parent run cascades every non-terminal pack order — `OPEN`, `PACKING`, `HOLD`, or `PASSED` — to terminal `CANCELLED`.

### 3.8. Customers, Seasonal Windows, and the Allotment Waterfall

A `PlantManager` registers a customer by supplying `account_name`, `channel` (`RETAIL_GROCERY`, `TORTILLERIA`, or `FOODSERVICE_DIST`), `region`, `base_weekly_cases`, `priority_tier` (`A`, `B`, or `C` — `A` is served first in the seasonal waterfall), and `min_shelf_life_pct`. `base_weekly_cases` must be at least zero; `min_shelf_life_pct` must lie between 1 and 100 inclusive. A new customer enters with `credit_standing` `GOOD`. The `PlantManager` may later set credit standing to `HOLD` or back to `GOOD`; a customer on `HOLD` is blocked from receiving new stop allocations with `ERR_CUSTOMER_CREDIT_HOLD`.

A `PlantManager` creates a seasonal window by supplying `window_name`, `starts_on`, `ends_on`, `demand_multiplier`, and `forecast_total_cases`. `ends_on` must be on or after `starts_on`; `demand_multiplier` must be at least 1.0; `forecast_total_cases` must be at least zero. Window dates form a **closed inclusive interval** `[starts_on, ends_on]` — both ends inclusive — which differs from the half-open semantics of line windows: two windows conflict when the first's `starts_on` is on or before the second's `ends_on` and the first's `ends_on` is on or after the second's `starts_on`. Adjacency — one window's `ends_on` plus one day equal to the next's `starts_on` — is allowed; sharing even one calendar day is a conflict. Only windows in `SCHEDULED` or `ACTIVE` participate in the comparison. An overlap is rejected with `ERR_WINDOW_DATE_OVERLAP`. A new window enters in `window_status` `SCHEDULED`, and `is_strict` computes to true when `demand_multiplier` is at least 1.5.

Activating a window requires it to be in `SCHEDULED` and the logical clock's date to lie inside `[starts_on, ends_on]` — otherwise `ERR_WINDOW_INVALID_STATE`. Activation creates a `SeasonalAllotment` for every customer with `credit_standing` `GOOD`, each stamped with the `seasonal_window_id` of the activating window and the `customer_id` of its recipient, computing `allotted_cases` by a pinned waterfall evaluation order. **Step one**: foodservice customers — channel `FOODSERVICE_DIST` — go first, in `created_at` ascending order; each is allotted `base_weekly_cases` multiplied by the window's `demand_multiplier`, rounded up to a whole number. **Step two**: the retail pool is `forecast_total_cases` minus the sum of step-one allotments, floored at zero. **Step three**: retail customers — channel `RETAIL_GROCERY` or `TORTILLERIA` — are processed tier `A` before tier `B` before tier `C`, with `created_at` ascending as tie-break inside a tier; each retail customer's request is `base_weekly_cases` multiplied by `demand_multiplier` multiplied by a tier factor — 1.0 for `A`, 0.8 for `B`, 0.6 for `C` — rounded up to a whole number; each is allotted the smaller of their request and the remaining retail pool, and the pool is decremented by the allotment. The waterfall order is normative: the retail pool depends on the foodservice allotments, so foodservice must evaluate first for the value to be well-defined.

For **strict** windows — those with `is_strict` true — activation additionally runs an enforcement sweep: pre-existing stops in `ALLOCATED` on routes dated inside the window that exceed the new allotment are shorted, processed in `created_at` ascending order, with each short atomic (no partial fills). Each shorted stop restores the pack's `cases_available`, refunds the route's `committed_cases`, and refunds the allotment's `consumed_cases`. Each allotment tracks `allotted_cases`, `consumed_cases` (cases consumed by `ALLOCATED` or `DELIVERED` stops on routes dated inside the window, refunded on short), and `remaining_cases` (`allotted_cases` minus `consumed_cases`), and enters in `allotment_status` `ACTIVE`.

Closing a window requires it to be `ACTIVE` and drives it to terminal `CLOSED`; every allotment of the window cascades from `ACTIVE` to `CLOSED`.

### 3.9. Routes, Stops, and Delivery

A `RouteDispatcher` creates a DSD route by supplying `route_code`, `route_date`, `region`, and `vehicle_capacity_cases`. `vehicle_capacity_cases` must be greater than zero; the `route_code` must be unique. A new route enters in `route_status` `PLANNED` with `committed_cases` zero and `open_cases` equal to `vehicle_capacity_cases`.

Adding a stop to a planned route is the densest gate in the system. The `RouteDispatcher` supplies `customer_id`, `pack_order_id`, `requested_cases`, and `expected_route_version`. `requested_cases` must be greater than zero. The OCC check of §2.6 fires first among the state checks. The parent route must be in `PLANNED` — otherwise `ERR_ROUTE_INVALID_STATE`. The referenced pack order must be `SEALED` — otherwise `ERR_PACK_NOT_SEALED`. The shelf-life gate then applies: `remaining_days` is the whole-day difference between the pack's `expires_on` and the route's `route_date`, and the gate passes when `remaining_days` multiplied by 100 is at least the customer's `min_shelf_life_pct` multiplied by the product's `shelf_life_days`; the comparison is integer arithmetic and inclusive at the exact boundary — violation yields `ERR_SHELF_LIFE_INSUFFICIENT`. The route must have enough open capacity — `open_cases` at least `requested_cases`, otherwise `ERR_ROUTE_CAPACITY_EXCEEDED`. The pack must have enough stock — `cases_available` at least `requested_cases`, otherwise `ERR_PACK_STOCK_INSUFFICIENT`. The customer must be in `credit_standing` `GOOD` — otherwise `ERR_CUSTOMER_CREDIT_HOLD`. And when the route's `route_date` falls inside a strict seasonal window, the customer's allotment for that window must have `remaining_cases` at least `requested_cases` — otherwise `ERR_ALLOTMENT_EXCEEDED`.

When every gate passes, allocation is **atomic**: `allocated_cases` equals `requested_cases` with no partial fills. The pack's `cases_available` drops by `requested_cases`, the route's `committed_cases` rises by `requested_cases` and the route's `version` increments by one, and when the route date falls inside a strict seasonal window the customer's allotment `consumed_cases` rises by `requested_cases`. The new stop enters in `stop_status` `ALLOCATED`, and its `route_id` is bound to the parent route named in the request path.

Dispatching a route requires it to be in `PLANNED` and to have at least one stop in `ALLOCATED` — dispatching an empty route is rejected with `ERR_ROUTE_EMPTY`. Completing a route requires it to be in `DISPATCHED` and every stop to be in a terminal state — `DELIVERED` or `SHORTED` — otherwise `ERR_UNRESOLVED_STOPS`. Cancelling a route is permitted only from `PLANNED` and shorts every `ALLOCATED` stop, restoring pack `cases_available` and refunding any seasonal allotment consumption.

Delivering a stop requires it to be in `ALLOCATED` and the parent route to be `DISPATCHED`. The dispatcher supplies `delivered_cases`, which may not exceed `allocated_cases` — a larger value is rejected with `ERR_VALIDATION`. Delivery sets `delivered_cases`, computes `shortage_cases` as `allocated_cases` minus `delivered_cases`, and advances the stop to terminal `DELIVERED`. A shortage recorded at delivery is **not** restocked — the route has already dispatched.

Shorting a stop pre-dispatch requires it to be in `ALLOCATED` and the parent route to be in `PLANNED`. Shorting advances the stop to terminal `SHORTED`, adds `allocated_cases` back to the pack's `cases_available`, subtracts `allocated_cases` from the route's `committed_cases`, and — when the stop had consumed a seasonal allotment — subtracts `allocated_cases` from the allotment's `consumed_cases`.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Resource-creating `POST` endpoints return HTTP 201 with the new resource in `data`. State-transition and mutation `POST` endpoints return HTTP 200 with the updated resource in `data`. All `GET` endpoints return HTTP 200. Errors return the HTTP status declared in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /plant/_clock/set_current_utc | Advance the logical clock; startup default is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock | PlantManager |
| POST | /plant/ingredient-lots | Receive a corn lot | PlantManager |
| GET | /plant/ingredient-lots | List lots | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/ingredient-lots/{id} | Get one lot | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/ingredient-lots/{id}/condition | Condition (or reject) a received lot | MillerOperator |
| GET | /plant/ingredient-lots/{id}/batches | Batches drawn from this lot | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/nixtamal-batches | Create a nixtamalization batch (draws `corn_kg` from the lot) | MillerOperator |
| GET | /plant/nixtamal-batches/{id} | Get one batch | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/nixtamal-batches/{id}/start-cook | Begin cooking | MillerOperator |
| POST | /plant/nixtamal-batches/{id}/start-steep | Begin steeping (cook duration must have elapsed) | MillerOperator |
| POST | /plant/nixtamal-batches/{id}/evaluate | Quality gate: `PASS` to `MILLING`, `RECOOK` to `COOKING`, `REJECT` to `REJECTED` (also from `QUARANTINED`) | QualityInspector |
| POST | /plant/nixtamal-batches/{id}/mill | Mill the batch; computes actual yield | MillerOperator |
| POST | /plant/nixtamal-batches/{id}/quarantine | Quarantine available masa; cascades allocation release, run demotion, changeover cancel | QualityInspector |
| POST | /plant/nixtamal-batches/{id}/release-quarantine | Release quarantined masa back to availability | QualityInspector |
| GET | /plant/nixtamal-batches/{id}/allocations | Allocations drawing masa from this batch | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/products | Create a SKU configuration | PlantManager |
| GET | /plant/products | List products | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/products/{id} | Get one product | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/products/{id}/discontinue | Discontinue a product (blocked while runs are open) | PlantManager |
| GET | /plant/products/{id}/runs | Runs of this product | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/lines | Create a production line | PlantManager |
| GET | /plant/lines | List lines | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/lines/{id} | Get one line (version source for run-create OCC) | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/lines/{id}/set-status | Take a line down or return it to service | PlantManager |
| GET | /plant/lines/{id}/runs | Runs scheduled on this line | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/lines/{id}/changeovers | Changeovers recorded for this line | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/runs | Create a run on a line (OCC on line version; window, capacity, zone, changeover-buffer checks; auto-creates gating changeover on product switch) | LineScheduler |
| GET | /plant/runs/{id} | Get one run | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/runs/{id}/schedule | Confirm a planned run | LineScheduler |
| POST | /plant/runs/{id}/start | Start a scheduled run (requires `VERIFIED` changeover and full masa coverage) | LineScheduler |
| POST | /plant/runs/{id}/complete | Complete a run (all pack orders terminal; at least 95 percent case attainment) | LineScheduler |
| POST | /plant/runs/{id}/cancel | Cancel a run; cascades allocation release, pack-order cancel, changeover cancel | LineScheduler |
| POST | /plant/runs/{id}/qc-hold | Place run on QC hold (parallel qc dimension) | QualityInspector |
| POST | /plant/runs/{id}/qc-release | Release QC hold | QualityInspector |
| GET | /plant/runs/{id}/allocations | Masa allocations feeding this run | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/runs/{id}/pack-orders | Pack orders of this run | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/runs/{id}/changeovers | Changeover records gating this run | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/allocations | Reserve masa from a `MASA_AVAILABLE` batch for a `PLANNED` or `SCHEDULED` run | LineScheduler |
| GET | /plant/allocations/{id} | Get one allocation | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/allocations/{id}/release | Release a reservation (compensating action) | LineScheduler |
| POST | /plant/allocations/{id}/consume | Mark reserved masa consumed | LineScheduler |
| POST | /plant/changeovers | Manually register a changeover (e.g., end-of-shift sanitation without a gated run) | SanitationTech |
| GET | /plant/changeovers | List changeovers with filters | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/changeovers/{id} | Get one changeover | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/changeovers/{id}/begin | Begin sanitation work (records `performed_by`) | SanitationTech |
| POST | /plant/changeovers/{id}/verify | Verify completed changeover (segregation of duties enforced) | QualityInspector |
| POST | /plant/changeovers/{id}/fail | Fail a changeover inspection (rework loop) | QualityInspector |
| POST | /plant/pack-orders | Open a pack order under a run | PackagingLead |
| GET | /plant/pack-orders/{id} | Get one pack order | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/pack-orders/{id}/start-packing | Begin packing (run must be `IN_PROGRESS`) | PackagingLead |
| POST | /plant/pack-orders/{id}/weight-check | Submit QC sample; pass to `PASSED`, fail to `HOLD` (rework loop) | PackagingLead |
| POST | /plant/pack-orders/{id}/seal | Seal passed cases (blocked while run QC is `ON_HOLD`) | PackagingLead |
| POST | /plant/pack-orders/{id}/reject | Reject a non-terminal pack order | PackagingLead |
| GET | /plant/pack-orders/{id}/stops | Route stops sourcing this pack order | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/seasonal-windows | Create a seasonal demand window (inclusive dates; overlap rejected) | PlantManager |
| GET | /plant/seasonal-windows | List windows | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/seasonal-windows/{id} | Get one window | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/seasonal-windows/{id}/activate | Activate a window: computes allotments (waterfall) and runs the strict-mode shorting sweep | PlantManager |
| POST | /plant/seasonal-windows/{id}/close | Close a window and its allotments | PlantManager |
| GET | /plant/seasonal-windows/{id}/allotments | Allotments of this window | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/allotments/{id} | Get one allotment | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/customers | Register a Hispanic-market channel customer | PlantManager |
| GET | /plant/customers | List customers | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/customers/{id} | Get one customer | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/customers/{id}/set-credit-standing | Set credit standing (`GOOD` or `HOLD`) | PlantManager |
| GET | /plant/customers/{id}/stops | Stops serving this customer | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| GET | /plant/customers/{id}/allotments | Seasonal allotments of this customer | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/routes | Create a DSD route | RouteDispatcher |
| GET | /plant/routes/{id} | Get one route (version source for stop-create OCC) | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/routes/{id}/dispatch | Dispatch a planned route (requires at least one `ALLOCATED` stop) | RouteDispatcher |
| POST | /plant/routes/{id}/complete | Complete a dispatched route (all stops terminal) | RouteDispatcher |
| POST | /plant/routes/{id}/cancel | Cancel a planned route; shorts all `ALLOCATED` stops | RouteDispatcher |
| GET | /plant/routes/{id}/stops | Stops on this route | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/routes/{id}/stops | Allocate a stop on a planned route (OCC on route version; shelf-life, capacity, stock, credit, allotment gates; atomic full-case allocation) | RouteDispatcher |
| GET | /plant/stops/{id} | Get one stop | PlantManager, MillerOperator, LineScheduler, SanitationTech, QualityInspector, PackagingLead, RouteDispatcher |
| POST | /plant/stops/{id}/deliver | Deliver an allocated stop (shortage recorded, not restocked) | RouteDispatcher |
| POST | /plant/stops/{id}/short | Short an allocated stop pre-dispatch (restocks pack, refunds route and allotment) | RouteDispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_VALIDATION | 422 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_BATCH_INVALID_STATE | 409 |
| ERR_LOT_INVALID_STATE | 409 |
| ERR_RUN_INVALID_STATE | 409 |
| ERR_ALLOCATION_INVALID_STATE | 409 |
| ERR_CHANGEOVER_INVALID_STATE | 409 |
| ERR_PACK_INVALID_STATE | 409 |
| ERR_PACK_NOT_SEALED | 409 |
| ERR_ROUTE_INVALID_STATE | 409 |
| ERR_STOP_INVALID_STATE | 409 |
| ERR_WINDOW_INVALID_STATE | 409 |
| ERR_PRODUCT_DISCONTINUED | 409 |
| ERR_ALLERGEN_ZONE_VIOLATION | 422 |
| ERR_SHELF_LIFE_INSUFFICIENT | 422 |
| ERR_QC_HOLD_ACTIVE | 409 |
| ERR_CHANGEOVER_NOT_VERIFIED | 409 |
| ERR_COOK_INCOMPLETE | 409 |
| ERR_STEEP_INCOMPLETE | 409 |
| ERR_LINE_WINDOW_OVERLAP | 409 |
| ERR_CHANGEOVER_WINDOW_INSUFFICIENT | 409 |
| ERR_WINDOW_DATE_OVERLAP | 409 |
| ERR_MASA_INSUFFICIENT | 422 |
| ERR_LINE_CAPACITY_EXCEEDED | 422 |
| ERR_ROUTE_CAPACITY_EXCEEDED | 422 |
| ERR_PACK_STOCK_INSUFFICIENT | 422 |
| ERR_WEIGHT_SAMPLE_INVALID | 422 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_CUSTOMER_CREDIT_HOLD | 422 |
| ERR_ALLOTMENT_EXCEEDED | 422 |
| ERR_UNRESOLVED_PACK_ORDERS | 409 |
| ERR_RUN_CASE_SHORTFALL | 422 |
| ERR_UNRESOLVED_STOPS | 409 |
| ERR_PRODUCT_IN_USE | 409 |
| ERR_ROUTE_EMPTY | 409 |
