# Frozen Prepared Food Manufacturing API — Product Requirements Document

## 1. Introduction

A frozen entrée manufacturer lives or dies by the discipline of its cold chain. Recipes must scale cleanly from a test-kitchen batch to a full production run; blast freezer cells must be booked against real thermal capacity rather than optimism; packaging lines must be scheduled around film supply and customer changeover rules; and every lot leaving the building carries a shelf-life promise that regulators and retail buyers will hold the plant to. When this manufacturer also runs co-pack programs for external customers, the stakes compound: billing must follow each customer's contracted metering, quality holds must respect strict segregation of duties, and a single freezer-burn complaint can no longer be filed away — it must be traceable to a lot, a recipe, and a shipping window.

This document specifies the API for operating that plant end to end. All endpoints are mounted under the `/plant` prefix. The surface covers master data (recipes and their component bills of material, co-pack customers, freezer cells, packaging lines, storage slots, and film supply), production execution (orders, batches, freezing cycles, and line runs), quality disposition (critical-control-point verification, holds, lot release, rejection, quarantine, and recall), and post-market feedback (complaints whose valid resolutions can cascade into lot-level and recipe-level quarantine). A server-side logical clock, rather than wall-clock time, drives every time-dependent gate in the system so that shelf-life enforcement, scheduling windows, and trailing complaint windows are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. Seven roles are recognized, spelled exactly as follows: `PlantManager`, `ProductionPlanner`, `LineOperator`, `QATechnician`, `QAManager`, `WarehouseLead`, and `CoPackCustomer`. A request arriving without both headers, or carrying a role outside this declared list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The identity carried by `X-User-ID` differs by role. For six of the seven roles — `PlantManager`, `ProductionPlanner`, `LineOperator`, `QATechnician`, `QAManager`, and `WarehouseLead` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `performed_by_user_id` on a critical-control-point check or as `reported_by_user_id` on a complaint, where a workflow writes it) but it does not compare it to any entity's `id` for ownership purposes. When `X-User-Role` is `CoPackCustomer`, `X-User-ID` is the `id` of the acting `CoPackCustomer` record; ownership checks on any resource that references a co-pack customer compare the resource's `copack_customer_id` field to `X-User-ID`, and any attempt by a customer-scoped caller to read or file against an order, lot, or complaint outside their own customer scope is rejected with `ERR_CROSS_CUSTOMER_ACCESS` (HTTP 403). On list endpoints the same discipline is enforced by restriction rather than rejection: a `CoPackCustomer` listing orders, lots, or complaints sees only records inside its own scope, while an explicit filter that names a foreign chain — a `copack_customer_id` filter on the order list, or a `lot_id` or `batch_id` filter that resolves to another customer's resource — is rejected with `ERR_CROSS_CUSTOMER_ACCESS`. Reading another customer's record through `GET /plant/copack-customers/{customerId}` is likewise rejected with `ERR_CROSS_CUSTOMER_ACCESS`.

The roles divide the plant's duties along deliberate lines. A `PlantManager` administers master data: recipes and their approval cycle, component lines, co-pack customers, freezer cells, packaging lines, storage slots, film reception, and the logical clock. A `ProductionPlanner` plans production: orders, batches, freezing-cycle bookings and voids, line-run scheduling, and cancellations. A `LineOperator` executes the physical steps: kitting, cooking, cycle starts and completions, run starts and completions. A `QATechnician` works the quality floor: recording critical-control-point checks, placing and releasing batch holds, quarantining film lots and released lots, and intake plus investigation of complaints. A `QAManager` holds disposition authority: lot release, rejection, rework, and recall, complaint resolution, film de-quarantine, and sending held batches to rework. A `WarehouseLead` performs cold-storage movements: put-away and withdrawal. A `CoPackCustomer` is an external portal role that reads its own orders, lots, and complaints and files complaints against its own lots. Read endpoints are broadly shared across roles, subject to the customer-scope rule above.

Two segregation-of-duties rules are enforced as authorization-level checks. The operator who releases a finished-goods lot must differ from every operator who recorded a critical-control-point check on that lot's batch. The manager who resolves a complaint must differ from the user who reported it. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with creation (insertion) order breaking ties.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Request Validation Pipeline

Every request passes through a fixed validation pipeline. When several checks could reject the same request, the earliest failing stage in the order below determines the error that is returned; later stages are never consulted for that request. The stages, in priority order, are:

1. **Authentication.** Both headers are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Endpoint authorization.** The role is permitted for the endpoint per the role matrix; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Segregation of duties.** On the two sensitive dispositions — lot release and complaint resolution — the acting user differs from the recorded performers or reporter; otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
4. **Customer scope.** On calls made with the `CoPackCustomer` role against orders, lots, and complaints, `X-User-ID` equals the `copack_customer_id` of the order chain being read or complained about; otherwise `ERR_CROSS_CUSTOMER_ACCESS` (HTTP 403).
5. **Request shape.** Required fields are present, types are correct, enum members are valid, and numeric ranges are respected (for example, unit counts must be positive and a component's `scale_exponent` must be greater than zero and no greater than 1.5); otherwise `ERR_INVALID_REQUEST` (HTTP 400).
6. **Existence.** Path identifiers are resolved left to right, then foreign keys in the request body; the first missing reference yields `ERR_NOT_FOUND` (HTTP 404).
7. **Optimistic concurrency.** The version guard fields described in §2.8 match the parent's current version; otherwise `ERR_STALE_VERSION` (HTTP 412).
8. **State preconditions.** Transition from-states are valid and state-dependent gates hold: the recipe is `APPROVED` where required, the order is open where required, the batch is `COOKED` for cycle start, the batch is `FROZEN` for run start, the lot is in a complainable status, and the recipe is `DRAFT` for component edits. Violations surface as the state-family errors — `ERR_BATCH_STATE`, `ERR_CYCLE_STATE`, `ERR_RUN_STATE`, `ERR_LOT_STATE`, `ERR_COMPLAINT_STATE`, `ERR_RECIPE_STATE`, `ERR_RECIPE_NOT_APPROVED`, `ERR_ORDER_NOT_OPEN`, or `ERR_RECIPE_BUSY` — all HTTP 409.
9. **Critical-control safety.** The latest check of each required type is `PASS` before lot release, and the film lot is not `QUARANTINED` at run creation or run start; otherwise `ERR_CCP_NOT_CURRENT` or `ERR_FILM_LOT_QUARANTINED` (HTTP 409).
10. **Temporal windows.** Freezer-cell windows including the sanitation buffer, packaging-line windows including changeover buffers, and expiry gates all hold; otherwise `ERR_CELL_WINDOW_CONFLICT`, `ERR_LINE_WINDOW_CONFLICT`, or `ERR_LOT_EXPIRED` (HTTP 409).
11. **Capacity and structural constraints.** Freezer loads sit within cell bounds, the auto-select pool is non-empty, line and film types match the pack format, film meters suffice, slot capacity and temperature class hold, withdrawals stay within stored cases, and recipe approval finds at least one component and an acyclic component graph; otherwise the corresponding error among `ERR_CAPACITY_EXCEEDED`, `ERR_BELOW_MIN_LOAD`, `ERR_NO_CELL_AVAILABLE`, `ERR_LINE_FORMAT_MISMATCH`, `ERR_FILM_TYPE_MISMATCH`, `ERR_FILM_INSUFFICIENT`, `ERR_STORAGE_CAPACITY_EXCEEDED`, `ERR_TEMPERATURE_CLASS_MISMATCH`, `ERR_INSUFFICIENT_CASES`, `ERR_RECIPE_NO_COMPONENTS`, or `ERR_RECIPE_COMPONENT_CYCLE` (HTTP 409).
12. **Aggregate fiscal check.** A complaint's `units_affected` does not exceed the complained lot's `cases_produced`; otherwise `ERR_COMPLAINT_UNITS_INVALID` (HTTP 422).

### 2.5. Resource Identity and Common Fields

All primary resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T00:00:00.000Z`) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including the state transitions and recorded side effects described throughout §3.

One deliberate exception exists: the critical-control-point check record is append-only. It carries `id` and `created_at` only — both `updated_at` and `version` are absent, because a check, once recorded, is never modified. This preserves a tamper-evident audit trail for the plant's hazard-analysis records.

### 2.6. The Logical Clock

The server maintains a logical clock that starts, at server startup, at exactly `2026-08-01T00:00:00Z`. The clock never falls back to wall-clock time; it moves only when a `PlantManager` exercises the test-driving capability that sets the current logical time to a supplied `to_iso8601` instant — any valid ISO 8601 instant is accepted, whether ahead of or behind the current value — after which the server reports the resulting `current_utc`. Server-stamped business timestamps — `performed_at` on critical-control-point checks and `reported_at` on complaints — are taken from this logical clock at creation time. Every rule in this document that refers to "the current date" or "the current logical date" — expiry gates at release and shipment, and the trailing windows of the complaint-contagion math — evaluates against this clock.

### 2.7. Numeric Precision and Rounding

All derived quantities in the plant follow one rounding convention: round half up, applied at the precision each quantity declares. Scaled component quantities in a recipe scale-up preview are rounded half up to three decimal places. Net weights on finished-goods lots are rounded half up to three decimal places. Batch yield percentages are rounded half up to two decimal places. Film reservations are rounded half up to whole meters, per run, before any aggregation. Co-pack billing under the per-kilogram variant is rounded half up to whole cents, once, on the aggregate. Freezer dwell times are whole hours, with ceiling rounding applied where division produces a fraction. Case counts are whole cases, rounded up by ceiling. Expiry dates and complaint day counts are whole calendar days. The recipe-level complaint rate is compared in exact rational arithmetic — affected cases divided by shipped cases — with no floating-point rounding applied before the threshold comparison.

### 2.8. Optimistic Concurrency Control

Two creation endpoints are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

When creating a production batch under an order, the request must carry `expected_order_version` holding the client last-observed `version` of the target order. If the order's current `version` has advanced beyond what the client observed — another writer may legitimately have added a batch to the same order in the meantime — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a view of the order it has not observed.

When booking a freezing cycle for a batch, the request must carry `expected_batch_version` holding the client's last-observed `version` of the target batch. A mismatch with the batch's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412); because a newly booked cycle legitimately supersedes any prior reserved cycle of the batch, a stale view of the batch is exactly the condition this guard exists to catch.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated hierarchically, left to right along the path. When a path contains multiple resource identifiers — for example, a batch nested under an order, or a freezing cycle nested under a batch — the server resolves each identifier in sequence and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before attempting to resolve anything further along the path. Foreign keys carried in the request body are resolved only after all path identifiers have been validated, and a missing body reference likewise yields `ERR_NOT_FOUND`.

### 2.10. Scheduling Windows and Buffer Discipline

All bookings in the plant — freezer cycles on cells and production runs on packaging lines — occupy half-open time windows: a booking occupies the interval from its `planned_start` up to, but not including, its `planned_end`. Two bookings on the same resource whose half-open windows merely touch — one ending exactly when the other begins — do not by themselves conflict.

Buffers extend the occupied window beyond the raw booking. On a blast freezer cell, a mandatory sanitation gap follows each cycle: the next cycle on that cell may not begin until the cell's `sanitation_minutes` have elapsed after the preceding cycle's `planned_end`, and this buffered window participates in the conflict check against every other reserved or in-progress cycle on the cell. On a packaging line, changeover buffers apply between runs: when a run follows a run belonging to a different co-pack customer, the two must be separated by the incoming customer's `base_changeover_minutes` (which defaults to 45 minutes); and when the incoming run's customer has `requires_allergen_changeover` set and the preceding run packed a recipe carrying an `allergen_tag` on any component, the separation is 120 minutes. Runs of the same customer — including two house-brand runs whose `copack_customer_id` are both null — require no changeover separation beyond the raw half-open overlap check, and a house-brand incoming run (no customer) uses the standard 45-minute gap and never triggers the allergen rule. These buffered windows participate in the conflict check against every other scheduled or in-progress run on the line.

### 2.11. State Propagation Across the Plant Hierarchy

The plant's entities form a hierarchy — recipe to order to batch, and batch to cycle, run, and lot — and the server keeps that hierarchy consistent by transitioning resources automatically the moment their criteria are satisfied, without waiting for an explicit client request on the affected resource. Orders advance and complete themselves as batches appear and resolve; batches advance as cycles verify and runs complete; lots deplete themselves when their last case leaves the shelf. Cascades flow downward as well: cancelling an order cancels its open batches, a failed critical-control check holds its batch and tears down the batch's scheduled runs, and a valid complaint can quarantine a lot and then every releasable lot of the same recipe. All such side effects apply immediately within the triggering request — there is no deferred or asynchronous reconciliation — and every state transition carries the version increments declared for it in §3, so a client holding a stale `version` of a cascaded parent will fail the §2.8 guard on its next guarded write.

## 3. Business Logic & Workflows

### 3.1. Recipe Authoring, Component Structure, and Scale-Up

A `PlantManager` authors a recipe by supplying a `name`, a `product_style` of `ENTREE`, `BOWL`, or `SKILLET`, a `base_batch_yield_units` (the positive integer count of units one base batch produces, which serves as the scale-up denominator), a positive `portion_weight_g` (the net weight per unit in grams), and a positive integer `shelf_life_days` (the frozen shelf life in days). Recipes whose `shelf_life_days` exceeds 545 days carry a storage consequence explored in §3.7: their lots demand `DEEP` temperature-class storage. Every new recipe begins life in `DRAFT` status. The recipe list is filterable by `status`.

Beneath the recipe, the bill of material is built line by line. Each component line records its owning recipe through `recipe_id`, plus a `component_name`, a `component_type` of `RAW_INGREDIENT`, `SUB_ASSEMBLY`, or `PACKAGING`, a positive `quantity_per_base_batch`, and a `unit_of_measure` of `KG`, `L`, `EACH`, or `M`. Sub-assembly structure is expressed through `parent_component_id`: null for top-level lines, and otherwise a reference to another component of the same recipe, allowing a sub-assembly to nest its own children; a `parent_component_id` naming no existing component yields `ERR_NOT_FOUND`, while one naming a component of a different recipe is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An optional `scale_exponent` — greater than zero, no greater than 1.5, defaulting to 1.0 — captures non-linear scale-up behavior for that line, and an optional `allergen_tag` (such as a milk or soy marker, null when the component is allergen-free) drives the changeover discipline of §2.10. Component lines may be added, and an existing line may be re-parented by submitting a new `parent_component_id`, only while the recipe is `DRAFT`; attempting either on an `APPROVED` or `RETIRED` recipe is rejected with `ERR_RECIPE_STATE`, and a successful re-parent increments the component's `version` by one. The component collection is filterable by `recipe_id` and `parent_component_id` for convenient bill-of-material navigation.

Approval is the gate that makes a recipe production-ready, moving it from `DRAFT` to `APPROVED` under a `PlantManager`. Two structural checks guard the transition, and both must hold: the recipe must have at least one component line, otherwise the approval is rejected with `ERR_RECIPE_NO_COMPONENTS`; and the component graph formed by `parent_component_id` must be acyclic, otherwise the approval is rejected with `ERR_RECIPE_COMPONENT_CYCLE`. A successful approval sets the recipe's `status` to `APPROVED` and increments its `version` by one.

Approved recipes are not frozen forever. Revision returns an `APPROVED` recipe to `DRAFT`, and retirement moves a recipe to the terminal `RETIRED` state — reachable from either `DRAFT` or `APPROVED`. Both revision from `APPROVED` and retirement from `APPROVED` are blocked while any batch of any order of the recipe occupies a non-terminal state, surfacing `ERR_RECIPE_BUSY`; retirement from `DRAFT` carries no such gate, since a draft can have no production in flight. Each of these transitions sets `status` and increments the recipe's `version`. Attempting any recipe transition from a state where it is not defined — approving a `RETIRED` recipe, for instance — is rejected with `ERR_RECIPE_STATE`.

Before committing an order, planners can preview scale-up through a computed read that takes a `target_units` quantity — supplied as a query parameter and required to be a positive integer, otherwise `ERR_INVALID_REQUEST` — and answers with the requested `target_units`, the resulting `scale_factor`, and one entry per component in `lines`, each entry carrying `component_id`, `component_name`, `component_type`, `parent_component_id`, `unit_of_measure`, `quantity_per_base_batch`, `scale_exponent`, `effective_exponent`, and `scaled_quantity`. The computation proceeds as follows. The raw scale factor is `target_units` divided by the recipe's `base_batch_yield_units`, and the working scale factor clamps that raw value to a floor of 0.25 and a ceiling of 8.0. Components are then traversed in topological order over `parent_component_id`, parents before their sub-assembly children, with creation order breaking ties among peers; any components left unvisited because their parent chain is cyclic (possible only while the recipe is `DRAFT`) are appended in creation order. Each component's effective exponent is the product of the `scale_exponent` values along its ancestor chain, from the root down to and including the component itself — except that every `PACKAGING` component along the chain, whether the component itself or one of its ancestors, contributes 1.0 to the product in place of its own `scale_exponent`, while non-`PACKAGING` ancestors' exponents still contribute to the product. The scaled quantity of each component is its `quantity_per_base_batch` multiplied by the working scale factor raised to the power of the component's effective exponent, rounded half up to three decimal places. The preview is available regardless of the recipe's status, so it can be used while drafting, after approval, and on retired recipes alike.

### 3.2. Co-Pack Customers and Production Order Intake

Co-pack programs begin with customer registration by a `PlantManager`. A customer record carries a `name` and a `billing_method` of `PER_CASE` or `PER_KG`, which selects the billing variant applied at lot release in §3.7. The rate fields are conditional on that selection: `case_rate_cents` is a non-negative integer required exactly when the method is `PER_CASE` and null otherwise, while `kg_rate_cents` is a non-negative integer required exactly when the method is `PER_KG` and null otherwise; supplying the wrong combination is a request-shape failure rejected with `ERR_INVALID_REQUEST`. Two scheduling fields complete the record: `requires_allergen_changeover`, a boolean defaulting to false that demands the 120-minute allergen changeover gap described in §2.10, and `base_changeover_minutes`, a non-negative integer defaulting to 45 that sets the standard gap when a line switches from a different customer's run.

With a recipe approved, a `ProductionPlanner` opens a production order by supplying the `recipe_id`, a `pack_format` of `RETAIL` or `FOODSERVICE`, and a positive integer `units_planned`, optionally attaching a `copack_customer_id` (null for house-brand orders) and a `due_at` customer due timestamp. The referenced recipe must be `APPROVED` at creation; referencing a draft or retired recipe is rejected with `ERR_RECIPE_NOT_APPROVED`. The chosen `pack_format` drives three downstream facts: which line type may pack the order (§3.5), how many units make a case — twelve per case for `RETAIL`, six per case for `FOODSERVICE` — and how much film each unit consumes. A new order starts in `PLANNED` status with `units_packed_total` and `releasable_cases` at zero and `billed_amount_cents` null. The order list is filterable by `recipe_id`, `copack_customer_id`, and `status`.

Batches are added to an order by a `ProductionPlanner` supplying the batch's positive integer `units_planned` together with the optimistic-concurrency field `expected_order_version` described in §2.8. The order must be open — `PLANNED` or `IN_PROGRESS`; attempting to add a batch to a `CANCELLED` or `COMPLETED` order is rejected with `ERR_ORDER_NOT_OPEN`. On success the batch begins in `CREATED` status, stamped with its `order_id`, the order's `version` increments by one, and the very first batch created under a `PLANNED` order automatically moves that order to `IN_PROGRESS` with its own version increment. The order's batch collection, and the plant-wide batch list filterable by `order_id` and `status`, serve planning review.

Orders complete themselves. When every batch of an `IN_PROGRESS` order has resolved into `COMPLETED` or `CANCELLED` and at least one of them is `COMPLETED`, the order automatically transitions from `IN_PROGRESS` to `COMPLETED`, incrementing its `version`. Cancellation is the manual path: a `ProductionPlanner` may cancel an order from either `PLANNED` or `IN_PROGRESS`, but only while every batch of the order sits in `CREATED` or `CANCELLED`; a batch that has progressed further blocks the cancellation with `ERR_ORDER_NOT_OPEN`. A successful cancellation moves the order to `CANCELLED`, cascades every `CREATED` batch to `CANCELLED`, and increments the order's `version`.

### 3.3. Batch Execution: Kitting, Cooking, Holds, and Rework

A batch is the unit of physical production, and its floor lifecycle begins with kitting. A `LineOperator` kits a `CREATED` batch, moving it to `KITTED`, provided two preconditions hold: the owning order is in `PLANNED` or `IN_PROGRESS` (otherwise `ERR_ORDER_NOT_OPEN`), and the order's recipe is `APPROVED` (otherwise `ERR_RECIPE_NOT_APPROVED`). Cooking follows: from `KITTED`, the operator records the actual `cooked_mass_kg` — a value that stays null until this step and must be positive once present — and the batch moves to `COOKED`. Freezing and packing advance the batch automatically, as §3.4 and §3.5 describe: a verified freezing cycle moves the batch from `COOKED` to `FROZEN`, and a completed line run moves it from `FROZEN` to `PACKED`. Any batch transition attempted from a state where that transition is not defined — cooking a batch that is still `CREATED`, for example — is rejected with `ERR_BATCH_STATE`.

Quality intervention can interrupt this flow at almost any point. A `QATechnician` may place a batch on hold from `KITTED`, `COOKED`, `FROZEN`, or `PACKED`, supplying a `reason`; the batch moves to `ON_HOLD`, the state it just occupied is recorded in `hold_origin_state`, the supplied text is recorded in `hold_reason`, and the batch's `version` increments. Resuming is symmetric: a `QATechnician` resumes a held batch, and the batch returns to exactly the state recorded in `hold_origin_state` — a batch held from `KITTED` returns to `KITTED`, one held from `COOKED` returns to `COOKED`, and likewise for `FROZEN` and `PACKED`. When the `hold_reason` carries the critical-control failure marker described in §3.6, an additional gate applies: the latest recorded check of the named type on this batch must be `PASS`, otherwise the resume is rejected with `ERR_BATCH_STATE`. A successful resume clears both `hold_origin_state` and `hold_reason` to null and increments the batch's `version`.

Two further dispositions exist for held and unstarted batches. A `QAManager` may send an `ON_HOLD` batch to `REWORK` — supplying a `reason` — which clears the hold fields and increments the version; the rework loop then runs through kitting again, where a `LineOperator` may kit a `REWORK` batch back to `KITTED` provided the owning order is `IN_PROGRESS` (otherwise `ERR_ORDER_NOT_OPEN`). A `ProductionPlanner` may cancel a batch outright: from `CREATED` the batch simply moves to `CANCELLED`, while cancelling from `ON_HOLD` additionally voids every `RESERVED` freezing cycle of the batch and cancels every `SCHEDULED` line run of the batch with its film reservation released, all within the same request. `COMPLETED` and `CANCELLED` are the batch's terminal states.

Two computed measures track a batch's productivity. `units_packed_total` accumulates the packed output of the batch's completed runs, starting at zero, and `yield_pct` — null until the first completed run — expresses that accumulation as a percentage of the batch's `units_planned`, rounded half up to two decimal places. Completion of the batch itself is a deliberate act: a `LineOperator` completes a `PACKED` batch, but only when at least one finished-goods lot exists for it — completing a packed batch that somehow produced no lot is rejected with `ERR_BATCH_STATE`. The completion moves the batch to `COMPLETED`, increments its `version`, and triggers the order's automatic completion check described in §3.2.

### 3.4. Blast Freezing: Cells, Cycle Booking, and Verification

Freezing capacity is registered cell by cell under a `PlantManager`. Each cell carries a unique `cell_code`, a positive integer `capacity_kg` (the maximum load per cycle), a positive integer `min_load_kg` no greater than that capacity (the minimum economic load), a positive integer `pull_down_kg_per_hour` (the cell's freezing throughput), and a non-negative integer `sanitation_minutes` (the mandatory gap after a cycle's `planned_end` before the next cycle may start on that cell); a duplicate `cell_code`, or a `min_load_kg` exceeding `capacity_kg`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A cell's `status` is derived rather than set: it reads `IN_USE` while any cycle of that cell is `RESERVED` or `IN_PROGRESS`, and `IDLE` otherwise.

Booking a cycle is a `ProductionPlanner` act against a specific batch, carrying a positive integer `load_kg`, the product's numeric `entry_temp_c` at load-in, a `planned_start` window start, an optional `cell_id`, and the optimistic-concurrency field `expected_batch_version` from §2.8. The batch must be in `CREATED`, `KITTED`, or `COOKED` — booking against a batch in any other state is rejected with `ERR_BATCH_STATE`. When `cell_id` is supplied, the load must fit that cell: a `load_kg` exceeding the cell's `capacity_kg` is rejected with `ERR_CAPACITY_EXCEEDED`, and one below its `min_load_kg` is rejected with `ERR_BELOW_MIN_LOAD`. The buffered window check of §2.10 then applies against every other `RESERVED` or `IN_PROGRESS` cycle on the cell, rejecting collisions with `ERR_CELL_WINDOW_CONFLICT`.

When `cell_id` is omitted, the server selects the cell itself. The candidate pool is every cell whose bounds admit the load — capacity at least `load_kg`, minimum load at most `load_kg` — and on which no reserved or in-progress cycle violates the sanitation-buffered window rule for the requested start. Candidates are ranked by ascending `capacity_kg`, so the tightest fitting cell wins; ties break toward the earlier `created_at`, and any remaining tie breaks toward the lexicographically smaller `cell_code`. An empty candidate pool rejects the booking with `ERR_NO_CELL_AVAILABLE`.

Booking also supersedes: if a previous cycle of the same batch is still `RESERVED`, it automatically becomes `VOIDED` the moment the new reservation is created, and this supersede is applied before the window-conflict validation runs, so a batch's own superseded cycle never conflicts with its replacement. The new cycle's `batch_id` ties it to its batch, the batch's `version` increments by one, and the server computes the cycle's dwell. The base dwell is `load_kg` divided by the cell's `pull_down_kg_per_hour`, rounded up to a whole hour. When `entry_temp_c` is above zero degrees, that base dwell is multiplied by 1.25 and rounded up to a whole hour again, capturing the extra thermal load of warm product. The cycle's `required_hours` is the greater of four hours and the computed base dwell, and its `planned_end` is `planned_start` plus exactly `required_hours` hours. A new cycle starts life in `RESERVED` status.

Execution on the floor belongs to a `LineOperator`. Starting a reserved cycle moves it from `RESERVED` to `IN_PROGRESS` and is permitted only while the batch is `COOKED` — starting earlier, before the cook step has landed, is rejected with `ERR_BATCH_STATE`. Completing a cycle records the `actual_end` timestamp and the measured `final_core_temp_c` — both null until this moment — then computes the outcome: the cycle becomes `VERIFIED` when the final core temperature is at or below minus eighteen degrees Celsius and the elapsed time from `planned_start` to `actual_end` does not exceed `required_hours` plus a two-hour grace; otherwise the cycle becomes `FAILED`. Verification cascades upward immediately — the batch moves from `COOKED` to `FROZEN` automatically, provided it is still `COOKED` at that moment (a batch since moved, for example onto `ON_HOLD`, keeps its current state) — while a failed cycle leaves the batch in `COOKED` so the planner may book a replacement cycle. Every cycle transition increments the cycle's `version`. A `ProductionPlanner` may also void a cycle outright, moving it from `RESERVED` to `VOIDED`; attempting to void a cycle already `IN_PROGRESS` — or any cycle transition from a state where it is undefined — is rejected with `ERR_CYCLE_STATE`. The cycle list is filterable by `cell_id`, `batch_id`, and `status`.

### 3.5. Packaging Lines, Film Supply, and Line Runs

Packaging capacity is registered under a `PlantManager`, one line at a time: a unique `line_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `line_type` of `TRAY` or `POUCH`, a positive integer `rate_units_per_minute`, and a `supported_film_type` of `TRAY_FILM` or `POUCH_FILM`. Film arrives as supply lots, likewise registered by a `PlantManager` with a `film_type`, a positive integer `rolls_received`, and a positive integer `meters_per_roll`; the lot's `meters_received` is the product of rolls and length per roll and is a conserved quantity — at every moment, the meters reserved plus the meters consumed plus the meters available equal the meters received. The lot's `meters_reserved` sums the reservations of its `SCHEDULED` and `IN_PROGRESS` runs, its `meters_consumed` sums the actual consumption of its `COMPLETED` runs, and its `meters_available` is what remains of the received quantity after both. A film lot begins `AVAILABLE`; a `QATechnician` may quarantine it, moving it to `QUARANTINED`, and a `QAManager` may release the quarantine, returning it to `AVAILABLE`, each transition incrementing the lot's `version` and each attempted from the wrong status — quarantining a lot that is not `AVAILABLE`, or releasing one that is not `QUARANTINED` — rejected with `ERR_INVALID_REQUEST` (HTTP 400). The film-lot list is filterable by `film_type` and `status`.

Scheduling a run is a `ProductionPlanner` act against a specific packaging line, supplying the `batch_id` of the batch to pack, the `film_lot_id` of the film to consume, a `planned_start`, and a positive integer `units_planned`; the booked line is recorded on the run as `line_id`. A run may be booked while its batch is `KITTED`, `COOKED`, or `FROZEN` — booking against a batch in any other state is rejected with `ERR_BATCH_STATE`. Format discipline is enforced at booking: a `RETAIL` order requires a `TRAY` line and a `FOODSERVICE` order requires a `POUCH` line, and a mismatch is rejected with `ERR_LINE_FORMAT_MISMATCH`; the film lot's `film_type` must equal the line's `supported_film_type`, otherwise `ERR_FILM_TYPE_MISMATCH`; and the film lot must be `AVAILABLE`, otherwise `ERR_FILM_LOT_QUARANTINED`. The buffered window check of §2.10 applies against every other `SCHEDULED` or `IN_PROGRESS` run on the line — this is where the customer `base_changeover_minutes` and the 120-minute allergen changeover bite — rejecting collisions with `ERR_LINE_WINDOW_CONFLICT`.

Two quantities are computed at booking. The run's `duration_minutes` is `units_planned` divided by the line's `rate_units_per_minute`, rounded up to a whole minute, and its `planned_end` is `planned_start` plus that duration. The film reservation follows the pinned rounding order: the run's `reserved_film_m` is `units_planned` multiplied by the per-unit film allowance of the order's pack format — 0.42 meters per unit for `RETAIL`, 0.35 meters per unit for `FOODSERVICE` — and then multiplied by 1.06 to cover the six percent waste allowance, with the result rounded half up to a whole meter for this run. Only then do per-run reservations sum into the lot's `meters_reserved`; summing raw unrounded values and rounding once would produce different totals and is not the contract. Booking requires the lot's `meters_available` to be at least the new reservation — equality is allowed — otherwise the booking is rejected with `ERR_FILM_INSUFFICIENT`; on success the lot's `meters_reserved` grows by exactly the run's `reserved_film_m`, and the run begins in `SCHEDULED` status. The run list is filterable by `line_id`, `batch_id`, `film_lot_id`, and `status`.

A `LineOperator` starts a scheduled run, moving it from `SCHEDULED` to `IN_PROGRESS`, under two gates: the batch must be `FROZEN` — starting the pack before freezing has verified is rejected with `ERR_BATCH_STATE` — and the film lot must still be `AVAILABLE`, otherwise `ERR_FILM_LOT_QUARANTINED`. Attempting any run transition from a state where it is undefined, such as starting a `CANCELLED` run, is rejected with `ERR_RUN_STATE`. Cancelling a scheduled run is a `ProductionPlanner` act that moves the run from `SCHEDULED` to `CANCELLED` and releases its film reservation, dropping the lot's `meters_reserved` by the run's `reserved_film_m`.

Completion is where the run pays out. A `LineOperator` completes an in-progress run by recording the actual `units_packed` and `film_meters_consumed` — both null until completion and positive integers once present — and a cascade follows within the same request. The run moves to `COMPLETED`; its film reservation is released and its consumption recorded, so the lot's `meters_reserved` falls by `reserved_film_m` while `meters_consumed` grows by `film_meters_consumed`. A finished-goods lot is created in `QA_PENDING` release status, its `pack_format` denormalized from the order, and the pack-out math runs: the lot's `cases_produced` is `units_packed` divided by the case pack of the order's pack format — twelve units per case for `RETAIL`, six for `FOODSERVICE` — rounded up to a whole case, and its `net_weight_kg` is `units_packed` multiplied by the recipe's `portion_weight_g` and divided by one thousand, rounded half up to three decimal places; the lot's expiry fields are computed per §3.7. The batch's `units_packed_total` grows by `units_packed`, its `yield_pct` recomputes as the accumulated total divided by the batch's `units_planned` and expressed as a percentage rounded half up to two decimal places, and the batch automatically advances from `FROZEN` to `PACKED`, provided it is still `FROZEN` (a batch since moved, for example onto `ON_HOLD`, keeps its state, though the lot is still created). The order's `units_packed_total` grows by the same `units_packed`, and the run's `version` increments.

### 3.6. Critical Control Point Verification and the Fail Cascade

Metal detection and X-ray inspection are the plant's critical control points, and every check is an append-only record created by a `QATechnician` against a specific batch. The recording carries a `check_type` of `METAL_DETECTOR` or `XRAY`, a `test_piece_detected` boolean reporting whether the challenge test piece was detected, and an optional `measured_size_mm` capturing the smallest detected size. The batch must be in `FROZEN`, `PACKED`, `COMPLETED`, or `ON_HOLD` — the `ON_HOLD` admission exists so investigative re-checks can be recorded while a batch is held — and recording against a batch in any other state is rejected with `ERR_BATCH_STATE`. The check's `result` is computed, never supplied: `PASS` when the test piece was detected, `FAIL` otherwise. The server stamps `performed_by_user_id` with the caller's `X-User-ID` and `performed_at` with the logical clock, and the record is immutable thereafter — the segregation-of-duties reference for lot release lives in these stamps. Checks are retrievable individually, as a plant-wide list filterable by `batch_id` and `check_type`, or as the check history of a single batch.

A failing check detonates a cascade. When a `FAIL` is recorded while the batch is `FROZEN` or `PACKED`, the batch immediately moves to `ON_HOLD` with `hold_origin_state` recording the state it occupied and `hold_reason` set to the failure marker formed by prefixing the check type — exactly the string `CCP_FAIL:` followed by the check type, for example `CCP_FAIL:METAL_DETECTOR` — the marker that later governs the resume gate of §3.3. Every `SCHEDULED` line run of the batch transitions to `CANCELLED` in the same request, and each cancelled run releases its film reservation, dropping its film lot's `meters_reserved` by that run's `reserved_film_m`; the batch's `version` increments. When a `FAIL` is recorded while the batch is `COMPLETED`, by contrast, no hold is placed — the product is already packed and past intervention, and enforcement instead lands at release time through the latest-check gate of §3.7. A `PASS` carries no side effects beyond the record itself.

### 3.7. Cold Storage, Lot Disposition, and Co-Pack Billing

Cold storage is registered as slots under a `PlantManager`: a unique `slot_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `zone` of `FREEZER_A`, `FREEZER_B`, or `DEEP_FREEZE`, a `temperature_class` of `STANDARD` or `DEEP`, and a positive integer `capacity_cases`. A slot's `occupied_cases` starts at zero and is maintained as the sum of `stored_cases` over the lots pointing at it, with the standing invariant that occupied cases plus remaining free capacity always equal `capacity_cases`.

Every finished-goods lot is born from a completed run with its `batch_id` and denormalized `pack_format` fixed, its `slot_id` null, its `stored_cases` and `cases_shipped` at zero, its `valid_complaint_count` at zero, and its `release_status` at `QA_PENDING`. The lot's `cases_on_hand` is its `cases_produced` minus every case ever withdrawn. Two expiry dates ride on each lot, anchored to the batch's verified freezing cycle — the latest by `created_at`, when several cycles of the batch have verified. The `provisional_expiry_date` is the calendar date of that cycle's `planned_start` plus the recipe's `shelf_life_days`; it serves planning, labels, and pre-verification projections. The `final_expiry_date` is the calendar date of that cycle's `actual_end` plus the recipe's `shelf_life_days`; it governs release gating, shipment gating, and the complaint day math of §3.8, and it is recomputed when the lot is released. The two variants diverge whenever the cycle verifies on a different calendar date than planned, and each has its own consumers — confusing them is a real production bug, not a rounding preference.

Put-away and withdrawal belong to a `WarehouseLead`. Putting away supplies a `slot_id` and a positive integer `cases` count; the lot must be in `QA_PENDING`, `RELEASED`, or `QUARANTINED` — put-away from any other release status is rejected with `ERR_LOT_STATE` — and the first put-away pins the lot's `slot_id` immutably, so a later put-away naming a different slot is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The slot must have room: if adding the cases would push `occupied_cases` above `capacity_cases` the request is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`, though an exact fill is allowed. Temperature class is enforced at the same moment: a lot whose recipe's `shelf_life_days` exceeds 545 days may only be put away into a `DEEP` slot, and attempting a `STANDARD` slot is rejected with `ERR_TEMPERATURE_CLASS_MISMATCH`. A successful put-away grows both the lot's `stored_cases` and the slot's `occupied_cases` by `cases`.

Withdrawal takes a positive integer `cases` and a required `purpose` string. The `purpose` is free-form: exactly `SHIPMENT` marks a shipment withdrawal — driving the expiry gate below, the `cases_shipped` accumulation, and the shipment-window accounting of §3.8 — while any other value, such as `DESTRUCTION`, is a non-shipment withdrawal. The lot must be `RELEASED` — withdrawing from any other status is rejected with `ERR_LOT_STATE` — and the count may not exceed the lot's `stored_cases`, otherwise `ERR_INSUFFICIENT_CASES`. When the `purpose` is shipment, one more gate applies: the current logical date must be on or before the lot's `final_expiry_date`, otherwise the withdrawal is rejected with `ERR_LOT_EXPIRED`. A successful withdrawal lowers the lot's `stored_cases` and `cases_on_hand` by `cases`, lowers the slot's `occupied_cases` by the same amount, and — for shipment withdrawals — adds `cases` to `cases_shipped`; when `cases_on_hand` reaches zero the lot automatically moves from `RELEASED` to `DEPLETED`.

Release is the `QAManager`'s central disposition, moving a lot from `QA_PENDING` to `RELEASED`, or from `QUARANTINED` back to `RELEASED`. Four gates guard the transition from `QA_PENDING`, and all four must hold: the lot's batch must be `COMPLETED`, otherwise `ERR_BATCH_STATE`; for each of `METAL_DETECTOR` and `XRAY`, the latest check of that type on the batch must exist and be `PASS`, otherwise `ERR_CCP_NOT_CURRENT`; the current logical date must be on or before the lot's `final_expiry_date`, otherwise `ERR_LOT_EXPIRED`; and the releasing manager's `X-User-ID` must differ from the `performed_by_user_id` of every check recorded on the batch, otherwise `ERR_SEGREGATION_OF_DUTIES`. On success the lot's `release_status` becomes `RELEASED`, its `final_expiry_date` is recomputed per the final variant, the owning order's `releasable_cases` grows by the lot's `cases_on_hand`, the order's `billed_amount_cents` is recomputed per the customer's billing variant, and the lot's `version` increments. Release from `QUARANTINED` applies the same four gates; on success the lot returns to `RELEASED` and the order's `releasable_cases` grows by the lot's `cases_on_hand`, with the lot's `version` incrementing.

The billing variant is selected by the customer's `billing_method`, and the two variants genuinely meter different quantities. Under `PER_CASE`, the order's `billed_amount_cents` is the sum of `cases_produced` across all of the order's `RELEASED` lots, multiplied by the customer's `case_rate_cents`. Under `PER_KG`, it is the sum of `net_weight_kg` across those same released lots, multiplied by the customer's `kg_rate_cents`, with the product rounded half up to whole cents exactly once, on the aggregate — never per lot. House-brand orders, whose `copack_customer_id` is null, keep `billed_amount_cents` null. Identical physical output can therefore bill differently under the two variants, and the variant in force is always the customer's declared method.

The remaining dispositions round out the lot lifecycle. A `QAManager` may reject a lot — supplying a `reason` — moving it from `QA_PENDING` or `QUARANTINED` to `REJECTED`; rejection is not terminal, because the same authority may send a `REJECTED` lot back to `QA_PENDING` through the rework loop, again supplying a `reason`. A `QATechnician` may manually quarantine a `RELEASED` lot, which moves it to `QUARANTINED` and subtracts its `cases_on_hand` from the order's `releasable_cases` in the same request. A `QAManager` recall — with a `reason` — moves a lot from `RELEASED` or `QUARANTINED` to the terminal `RECALLED`; from `RELEASED` the order's `releasable_cases` falls by the lot's `cases_on_hand` as part of the recall. Every one of these transitions increments the lot's `version`, and any lot transition attempted from a status where it is undefined is rejected with `ERR_LOT_STATE`. The lot collection is filterable by `batch_id`, `slot_id`, and `status`.

### 3.8. Complaints, Investigation, and Contagion

Post-market feedback enters as a complaint filed by a `QATechnician`, or by a `CoPackCustomer` against one of its own lots, supplying the `lot_id`, a `complaint_type` of `FREEZER_BURN`, `TEXTURE`, `FOREIGN_MATERIAL`, or `OFF_ODOR`, and a positive integer `units_affected`. The complained lot is resolved first — including the customer-scope check for `CoPackCustomer` callers — before the remaining body fields are validated, so a missing lot yields `ERR_NOT_FOUND` even when other fields are malformed. The complained lot must be in `RELEASED`, `QUARANTINED`, or `DEPLETED` status — complaining against a `QA_PENDING`, `REJECTED`, or `RECALLED` lot is rejected with `ERR_LOT_STATE` — and `units_affected` may not exceed the lot's `cases_produced`, an aggregate check that fails with `ERR_COMPLAINT_UNITS_INVALID` (HTTP 422). A new complaint opens in `OPEN` status with `reported_by_user_id` stamped from the caller's `X-User-ID`, `reported_at` stamped from the logical clock, and `days_before_expiry` computed as the lot's `final_expiry_date` minus the calendar date of `reported_at`, in whole days — negative when the complaint arrives after expiry. Complaints are listable plant-wide with filters by `lot_id` and `status`, or per lot.

Investigation moves a complaint from `OPEN` to `UNDER_INVESTIGATION` under a `QATechnician`. Resolution belongs to a `QAManager`, who supplies a `verdict` of `VALID` or `INVALID` and an optional `notes`, which is validated as a string but not persisted on the complaint resource. Segregation binds here as everywhere: the resolver's `X-User-ID` must differ from the complaint's `reported_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Resolving a complaint that is still `OPEN`, or one already resolved, is rejected with `ERR_COMPLAINT_STATE`, and a resolved state — `RESOLVED_VALID` or `RESOLVED_INVALID` — is terminal. An `INVALID` verdict simply lands the complaint in `RESOLVED_INVALID` with a version increment and no further effect.

A `VALID` verdict sets off the three-hop contagion cascade, all within the same request. First, the lot's `valid_complaint_count` grows by one. Second, when that count reaches at least three and the lot is currently `RELEASED`, the lot moves to `QUARANTINED` and its order's `releasable_cases` falls by the lot's `cases_on_hand` — the threshold is inclusive, so exactly the third valid complaint triggers the quarantine. Third, the recipe-level complaint rate is recomputed across every lot of the same recipe, reached through each lot's batch and order: shipped volume is the total cases withdrawn with the shipment purpose over the trailing ninety days — a half-open window that excludes the instant exactly ninety days before the current logical clock and includes everything up to now — and affected volume is the summed `units_affected` of the complaints in `RESOLVED_VALID` status whose `reported_at` falls within that same window. When shipped volume is positive and the ratio of affected to shipped reaches or exceeds 0.005, compared in exact rational arithmetic with no floating-point rounding so that a ratio landing exactly on the threshold triggers, every lot of that recipe currently in `RELEASED` status moves to `QUARANTINED`, each one recomputing its own order's `releasable_cases` as it falls. A lot quarantined by contagion can only return to the market through the release gates of §3.7, and the complaint's own `version` increments as the cascade completes.

## 4. Endpoint Definitions

Operations that create a new resource — a recipe, a component line, a customer, an order, a batch, a cycle, a run, a film lot, a check, a slot, or a complaint — return `201 Created`. Operations that modify an existing resource, including every state transition, the re-parenting edit, put-away and withdrawal movements, and the logical-clock set, return `200 OK`, as do all reads and the computed scale-up preview. In the table below, "Plant roles" means the six internal roles — `PlantManager`, `ProductionPlanner`, `LineOperator`, `QATechnician`, `QAManager`, and `WarehouseLead` — and "All roles" means those six plus `CoPackCustomer`; list endpoints additionally accept the `limit` and `offset` pagination parameters and the filter parameters referenced in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/_clock/set_current_utc` | Set the server's logical clock | PlantManager |
| POST | `/plant/recipes` | Create a recipe (status DRAFT) | PlantManager |
| GET | `/plant/recipes` | List recipes | Plant roles |
| GET | `/plant/recipes/{recipeId}` | Get a recipe | Plant roles |
| POST | `/plant/recipes/{recipeId}/components` | Add a BOM component line (recipe must be DRAFT) | PlantManager |
| GET | `/plant/components` | List components, filterable by recipe and parent | Plant roles |
| GET | `/plant/components/{componentId}` | Get a component | Plant roles |
| PATCH | `/plant/components/{componentId}` | Re-parent a component (recipe must be DRAFT) | PlantManager |
| POST | `/plant/recipes/{recipeId}/approve` | Approve a recipe (DRAFT to APPROVED) | PlantManager |
| POST | `/plant/recipes/{recipeId}/revise` | Return an approved recipe to DRAFT | PlantManager |
| POST | `/plant/recipes/{recipeId}/retire` | Retire a recipe (terminal) | PlantManager |
| GET | `/plant/recipes/{recipeId}/scale-preview` | Computed scale-up preview for a target unit count | Plant roles |
| POST | `/plant/copack-customers` | Register a co-pack customer | PlantManager |
| GET | `/plant/copack-customers/{customerId}` | Get a co-pack customer | PlantManager, ProductionPlanner, CoPackCustomer |
| POST | `/plant/production-orders` | Create a production order (recipe must be APPROVED) | ProductionPlanner |
| GET | `/plant/production-orders` | List production orders | All roles |
| GET | `/plant/production-orders/{orderId}` | Get a production order | All roles |
| POST | `/plant/production-orders/{orderId}/cancel` | Cancel an order (all batches must be CREATED or CANCELLED) | ProductionPlanner |
| POST | `/plant/production-orders/{orderId}/batches` | Create a batch under an order (OCC on the order) | ProductionPlanner |
| GET | `/plant/production-orders/{orderId}/batches` | List batches of an order | Plant roles |
| GET | `/plant/production-batches` | List batches, filterable by order | Plant roles |
| GET | `/plant/production-batches/{batchId}` | Get a batch | Plant roles |
| POST | `/plant/production-batches/{batchId}/kit` | Kit a batch (CREATED to KITTED; also the REWORK to KITTED loop) | LineOperator |
| POST | `/plant/production-batches/{batchId}/cook` | Cook a batch (KITTED to COOKED) | LineOperator |
| POST | `/plant/production-batches/{batchId}/complete` | Complete a batch (PACKED to COMPLETED) | LineOperator |
| POST | `/plant/production-batches/{batchId}/hold` | Place a batch on quality hold | QATechnician |
| POST | `/plant/production-batches/{batchId}/resume` | Resume a held batch to its hold origin state | QATechnician |
| POST | `/plant/production-batches/{batchId}/rework` | Send a held batch to rework | QAManager |
| POST | `/plant/production-batches/{batchId}/cancel` | Cancel a batch (CREATED or ON_HOLD to CANCELLED) | ProductionPlanner |
| POST | `/plant/freezer-cells` | Register a blast freezer cell | PlantManager |
| GET | `/plant/freezer-cells` | List freezer cells | Plant roles |
| GET | `/plant/freezer-cells/{cellId}` | Get a freezer cell | Plant roles |
| POST | `/plant/production-batches/{batchId}/freezing-cycles` | Book a freezing cycle for a batch (OCC on the batch) | ProductionPlanner |
| GET | `/plant/freezing-cycles` | List freezing cycles | Plant roles |
| GET | `/plant/freezing-cycles/{cycleId}` | Get a freezing cycle | Plant roles |
| POST | `/plant/freezing-cycles/{cycleId}/start` | Start a reserved cycle (batch must be COOKED) | LineOperator |
| POST | `/plant/freezing-cycles/{cycleId}/complete` | Complete a cycle; outcome computed as VERIFIED or FAILED | LineOperator |
| POST | `/plant/freezing-cycles/{cycleId}/void` | Void a RESERVED cycle | ProductionPlanner |
| POST | `/plant/packaging-lines` | Register a packaging line | PlantManager |
| GET | `/plant/packaging-lines` | List packaging lines | Plant roles |
| GET | `/plant/packaging-lines/{lineId}` | Get a packaging line | Plant roles |
| POST | `/plant/packaging-lines/{lineId}/runs` | Schedule a line run (reserves film) | ProductionPlanner |
| GET | `/plant/line-runs` | List line runs | Plant roles |
| GET | `/plant/line-runs/{runId}` | Get a line run | Plant roles |
| POST | `/plant/line-runs/{runId}/start` | Start a scheduled run (batch must be FROZEN, film lot AVAILABLE) | LineOperator |
| POST | `/plant/line-runs/{runId}/complete` | Complete a run; creates the finished-goods lot | LineOperator |
| POST | `/plant/line-runs/{runId}/cancel` | Cancel a scheduled run (releases the film reservation) | ProductionPlanner |
| POST | `/plant/film-lots` | Receive a film supply lot | PlantManager |
| GET | `/plant/film-lots` | List film lots | Plant roles |
| GET | `/plant/film-lots/{lotId}` | Get a film lot | Plant roles |
| POST | `/plant/film-lots/{lotId}/quarantine` | Quarantine a film lot | QATechnician |
| POST | `/plant/film-lots/{lotId}/release-quarantine` | Release a film lot from quarantine | QAManager |
| POST | `/plant/production-batches/{batchId}/ccp-checks` | Record a critical-control-point check (append-only) | QATechnician |
| GET | `/plant/ccp-checks/{checkId}` | Get a CCP check | Plant roles |
| GET | `/plant/ccp-checks` | List CCP checks, filterable by batch | Plant roles |
| GET | `/plant/production-batches/{batchId}/ccp-checks` | List CCP checks of a batch | Plant roles |
| POST | `/plant/storage-slots` | Register a cold storage slot | PlantManager |
| GET | `/plant/storage-slots` | List storage slots | Plant roles |
| GET | `/plant/storage-slots/{slotId}` | Get a storage slot | Plant roles |
| GET | `/plant/lots` | List finished goods lots | All roles |
| GET | `/plant/lots/{lotId}` | Get a lot | All roles |
| POST | `/plant/lots/{lotId}/put-away` | Put cases away into a slot (first put-away pins the slot) | WarehouseLead |
| POST | `/plant/lots/{lotId}/withdraw` | Withdraw stored cases (lot must be RELEASED) | WarehouseLead |
| POST | `/plant/lots/{lotId}/quarantine` | Manually quarantine a released lot | QATechnician |
| POST | `/plant/lots/{lotId}/release` | Release a lot (CCP, expiry, and segregation gates) | QAManager |
| POST | `/plant/lots/{lotId}/reject` | Reject a lot | QAManager |
| POST | `/plant/lots/{lotId}/rework` | Return a rejected lot to QA_PENDING | QAManager |
| POST | `/plant/lots/{lotId}/recall` | Recall a lot (terminal) | QAManager |
| POST | `/plant/complaints` | File a complaint against a lot | QATechnician, CoPackCustomer |
| GET | `/plant/complaints` | List complaints, filterable by lot | PlantManager, ProductionPlanner, QATechnician, QAManager, CoPackCustomer |
| GET | `/plant/complaints/{complaintId}` | Get a complaint | PlantManager, ProductionPlanner, QATechnician, QAManager, CoPackCustomer |
| GET | `/plant/lots/{lotId}/complaints` | List complaints of a lot | All roles |
| POST | `/plant/complaints/{complaintId}/investigate` | Open investigation (OPEN to UNDER_INVESTIGATION) | QATechnician |
| POST | `/plant/complaints/{complaintId}/resolve` | Resolve a complaint (a VALID verdict triggers the contagion cascade) | QAManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CROSS_CUSTOMER_ACCESS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RECIPE_STATE` | 409 Conflict |
| `ERR_RECIPE_NOT_APPROVED` | 409 Conflict |
| `ERR_RECIPE_BUSY` | 409 Conflict |
| `ERR_RECIPE_NO_COMPONENTS` | 409 Conflict |
| `ERR_RECIPE_COMPONENT_CYCLE` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_BATCH_STATE` | 409 Conflict |
| `ERR_CYCLE_STATE` | 409 Conflict |
| `ERR_RUN_STATE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BELOW_MIN_LOAD` | 409 Conflict |
| `ERR_CELL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_NO_CELL_AVAILABLE` | 409 Conflict |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LINE_FORMAT_MISMATCH` | 409 Conflict |
| `ERR_FILM_TYPE_MISMATCH` | 409 Conflict |
| `ERR_FILM_LOT_QUARANTINED` | 409 Conflict |
| `ERR_FILM_INSUFFICIENT` | 409 Conflict |
| `ERR_CCP_NOT_CURRENT` | 409 Conflict |
| `ERR_LOT_STATE` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_TEMPERATURE_CLASS_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_CASES` | 409 Conflict |
| `ERR_COMPLAINT_STATE` | 409 Conflict |
| `ERR_COMPLAINT_UNITS_INVALID` | 422 Unprocessable Entity |
