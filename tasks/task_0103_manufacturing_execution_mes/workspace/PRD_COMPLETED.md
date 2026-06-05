# Manufacturing Execution MES API — Product Requirements Document

## 1. Introduction

This document specifies the Manufacturing Execution System (MES) API, the system of record for translating engineering master data into executed, traceable production. The platform spans the full shop-floor arc: engineers author products, multi-level bills of material, routings, and the operations that run on physical machines; planners release work orders that explode those bills into concrete component demands and mint the in-process work nodes that the floor will execute; operators run those nodes, record machine run windows, issue raw lots, and raise defects; and quality inspectors sign the electronic traveler and decide the fate of scrapped or reworked units.

The system's defining challenge is that a single business event almost never touches a single record. Releasing a work order explodes a graph of bills, computes standard cost, and instantiates a sequence of operations in one cascade. Dispositioning a defect either debits work-in-process and computes scrap cost, or reopens an already-completed operation and voids its sign-off — two divergent outcomes from one endpoint. Lot genealogy must remain conserved through issues, reversals, and cancellations so that every produced serial can be traced to the exact component lots consumed. Machine effectiveness (OEE) is recomputed from raw run logs with pinned rounding so that two engineers reading the same logs always agree. Throughout, the API enforces optimistic concurrency on work-order release, immediate consistency across all derived fields, and a strict validation precedence so that the same request always fails for the same, most-significant reason.

This PRD defines the entities, their lifecycles, the calculations that derive cost and effectiveness, the validation rules that guard each transition, and the precise API contract a conforming implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across every collection in the API. All collections — `products`, `bom-lines`, `routings`, `machines`, `lots`, `work-orders`, `work-order-operations`, `scrap-dispositions`, `lot-issues`, `component-demands`, and `genealogy-links` — are peer, top-level resources mounted directly under the API root; there is no nested-ownership URL tree.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes five roles, spelled exactly as follows: `ManufacturingEngineer`, `ProductionPlanner`, `MachineOperator`, `QualityInspector`, and `PlantAdmin`.

- A `ManufacturingEngineer` owns master data — products, BOM lines, routings, operations, and machine registration — and may also recompute machine OEE.
- A `ProductionPlanner` owns the work-order lifecycle: creating, releasing, completing, closing, and cancelling work orders.
- A `MachineOperator` executes the floor: starting, pausing, resuming, and completing work-order operations, recording machine run logs and status, receiving lots, and issuing lots; an operator may also raise scrap dispositions.
- A `QualityInspector` signs the electronic traveler, dispositions scrap and rework, may raise scrap dispositions, and may recompute machine OEE.
- A `PlantAdmin` is an operational override authorized to perform any operation across every module as a superset of all other roles.

Identity semantics are uniform across all five roles: every role's `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, the `QualityInspector` who signs a traveler is captured as `inspector_user_id` on the resulting sign-off record — but the server never compares `X-User-ID` to any entity's `id` for ownership purposes. There are no entity-backed roles in this system; authorization is determined solely by `X-User-Role` against the operation, never by matching the user to a resource owner.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Almost every resource carries a system-managed core. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and the `version` field is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource.

One entity is deliberately leaner. A `TravelerSignoff` is an append-only record: once written it is never modified. It therefore carries only `id` and `created_at` — it has no `updated_at` and no `version` field. Every other entity in this specification carries the full `id`, `created_at`, `updated_at`, and `version` set.

When a computed field is recalculated as a side effect of some operation — for example, a work order's `wip_qty` after a scrap is dispositioned, or a machine's OEE ratios after a recompute — that recalculation is itself a mutation of the owning resource: it refreshes the owner's `updated_at` and increments the owner's `version`.

### 2.5. Cascading Consistency and Derived-Field Reconciliation

The system maintains immediate consistency: every derived value reflects the current state of its inputs the moment a triggering operation returns. Many operations deliberately reach beyond their target resource. Starting the first operation of a work order bubbles the parent work order forward. Dispositioning a defect debits the work order's scrap tally and the operation's scrap tally together. Completing a work order finalizes lot quantities and seals genealogy. These cross-entity effects are not optional or best-effort; each one named in §3 is part of the contract for its operation, and each mutated resource independently has its `updated_at` refreshed and its `version` incremented.

Some transitions are also *reverting*: cancelling a released work order walks back its committed lot issues, restoring inventory, and removes the component demands it had created. These compensating effects exist so that the inventory and genealogy invariants survive an aborted build.

### 2.6. Nested Path Resolution

Several read and write endpoints address a child collection through a parent identifier in the path — for instance, listing the operations of a routing, the operations of a work order, the sign-offs of a work-order operation, or the genealogy of a work order. The system resolves path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not correspond to an existing resource, before evaluating anything further to its right. The same left-to-right existence rule applies to every foreign-key identifier supplied in a request body: any referenced resource that does not exist yields `ERR_NOT_FOUND`.

### 2.7. Precision, Rounding, and Cost Representation

All monetary amounts are integer cents; all OEE ratios are decimals in the range from 0 through 1 inclusive. Two distinct rounding regimes apply and must not be confused.

- **Cost rounding.** Every per-item cost component is rounded to whole cents using the round-half-up method *before* it is summed into a total. This pinned "round each, then sum" order applies to BOM standard cost, actual material cost, and labor cost; rounding the sum instead of the parts would yield a different cent total and is incorrect.
- **OEE rounding.** Each effectiveness ratio is rounded to 4 decimal places using round-half-up, with the ratio first clamped into the range from 0 through 1 inclusive. The overall figure is computed *once* from the full-precision (clamped but not pre-rounded) component ratios and only then rounded to 4 decimal places; it is never derived by multiplying the already-rounded components.

### 2.8. Optimistic Concurrency on Work-Order Release

Releasing a work order is the one operation in this system guarded by optimistic concurrency control. The release request must include `expected_work_order_version`, carrying the `version` of the target work order that the client last observed; this field is required, not optional. The server compares it against the work order's current `version`. If they do not match — because another writer advanced the work order's `version` after the client read it — the release is rejected with `ERR_STALE_VERSION` (HTTP 412). This stops a client holding a stale `PLANNED` snapshot from re-exploding the bill against an order that has already been released and supersedes its prior state. No other endpoint in this API takes a version field or performs an OCC check; release alone requires `expected_work_order_version`.

### 2.9. Validation Precedence

When more than one validation could reject a request, the system evaluates them in a fixed order and returns the error for the first rule that fails, so that the same request always fails for the same, most-significant reason. The global order is:

1. Authentication — headers present and `X-User-Role` is a known role; otherwise `ERR_UNAUTHENTICATED` (401).
2. Authorization — the acting role is permitted for the operation; otherwise `ERR_FORBIDDEN` (403).
3. Existence — every resource referenced in the path or body exists, checked left to right; otherwise `ERR_NOT_FOUND` (404).
4. State — the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409).

Beyond these four universal gates, operation-specific business rules are evaluated. Where several business rules guard one endpoint, their relative order is stated alongside the workflow that uses them in §3. The lowest-precedence check is the generic well-formedness gate: required fields present and well-typed and enum members valid, failing which the request is rejected with `ERR_INVALID_REQUEST` (400). A malformed-literal or invalid-enum condition that can be detected purely from the request shape is reported as `ERR_INVALID_REQUEST`; the more specific business errors below are reserved for violations that depend on stored state.

## 3. Business Logic & Workflows

### 3.1. Engineering Master Data: Products and the Bill of Materials

A `ManufacturingEngineer` (or a `PlantAdmin`) defines the catalog by creating a **Product**. A product carries a `sku` — an uppercase alphanumeric stock-keeping code that must be unique across all products and between 3 and 32 characters long — together with a human-readable `name` and a `product_type` that classifies it in the bill-of-material tree as one of `FINISHED_GOOD`, `SUBASSEMBLY`, or `RAW_MATERIAL`. Each product also records a `unit_cost_cents`, an integer standard unit cost that must be zero or greater and defaults to 0; this cost is meaningful for raw materials and subassemblies and drives material variance. A `lot_controlled` boolean, defaulting to false, marks products whose issues must reference a specific lot so that genealogy can be traced.

The bill of material is built one edge at a time. Adding a **BomLine** records that an assembly consumes a component: the payload names the `parent_product_id` of the consuming assembly and the `component_product_id` of the consumed item, the `quantity_per` units of component used per one unit of parent (which must be strictly greater than 0), and an optional `scrap_factor_pct` expressing expected line scrap as a percent, defaulting to 0 and constrained to be at least 0 and strictly less than 100. A bill line may never point a product at itself: if `parent_product_id` equals `component_product_id`, or if the new edge would introduce a cycle anywhere in the bill-of-material graph, the line is rejected with `ERR_BOM_CYCLE`. BOM lines can be listed and filtered by their `parent_product_id` or by their `component_product_id`.

### 3.2. Routings, Operations, and Machines

A routing is the ordered recipe of operations that builds a product. A `ManufacturingEngineer` creates a **Routing** for a given `product_id` with a `routing_code` that must be unique within that product. A new routing begins in `DRAFT` `status` and exposes an `operation_count` that starts at 0 and is recomputed whenever an operation is attached.

Operations are attached only while the routing is in `DRAFT`. Each **Operation** names the `routing_id` it belongs to and the `machine_id` that runs it, a `sequence_no` that orders it within the routing (strictly greater than 0 and unique within that routing — a duplicate is rejected with `ERR_DUPLICATE_SEQUENCE`, with lower numbers running first), the `ideal_cycle_time_secs` that one unit should take at that operation (strictly greater than 0, the basis for OEE performance), and an optional `setup_buffer_secs` (an integer of at least 0, defaulting to 0) giving the idle buffer required before the next operation may begin on the same work center. Attaching an operation increments the routing's `operation_count`.

Before a routing can drive production it must be released. A `ManufacturingEngineer` releases a `DRAFT` routing, advancing its `status` from `DRAFT` to `RELEASED`; this is permitted only when the routing has at least one operation (`operation_count` of 1 or more) and every operation under it references an existing machine, and it increments the routing's `version`. A `RELEASED` routing advances from `RELEASED` to `ARCHIVED` only when no work order in `RELEASED` or `IN_PROCESS` status still references that routing; archiving likewise increments the routing's `version`, and `ARCHIVED` is terminal. Any attempt to release or archive a routing that is not in the required starting state is an `ERR_INVALID_STATE`.

Machines are registered separately. A **Machine** carries a unique `machine_code`, a `work_center` grouping used for setup-buffer overlap checks, an operational `status` (one of `AVAILABLE`, `RUNNING`, or `DOWN`, defaulting to `AVAILABLE`), and a `planned_production_secs` value — the planned available production time per shift, strictly greater than 0, which serves as the denominator for OEE availability. A machine additionally exposes the computed effectiveness fields `oee_availability`, `oee_performance`, `oee_quality`, and `oee_overall` (each a ratio from 0 through 1, defaulting to 0) and a `quality_flagged` boolean (defaulting to false). An operator or admin may set a machine's `status` directly — for example marking it `DOWN` for maintenance. The list of operations running on a given machine can be retrieved by machine.

### 3.3. Machine Run Logs and OEE Effectiveness

Operators record actual machine behavior as **MachineRunLog** windows. Each log names its `machine_id` and a half-open interval from `window_start` (inclusive) to `window_end` (exclusive), where `window_end` must be strictly later than `window_start`. The log records the `run_time_secs` the machine was actually running within the window (at least 0 and no greater than the window's own duration in seconds), the `total_units` produced in the window (good plus defective, at least 0), and the `good_units` that were defect-free (at least 0 and no greater than `total_units`). A new run-log window may not overlap any existing window already recorded for the same machine; because the interval is half-open, a window that starts exactly when another ends does not overlap, but any genuine overlap is rejected with `ERR_RUNLOG_OVERLAP`.

Overall effectiveness is recalculated on demand by a `ManufacturingEngineer`, `QualityInspector`, or `PlantAdmin`, which aggregates the machine's entire set of run logs (window order is irrelevant, since the inputs are pure sums). The computation proceeds as follows. First, sum `run_time_secs` across all of the machine's logs to get the total run time; availability is that total run time divided by the machine's `planned_production_secs`, clamped to lie within 0 through 1. Second, sum `total_units` across all logs and separately sum `good_units` across all logs. Performance is the product of the primary operation's `ideal_cycle_time_secs` and the summed total units, divided by the total run time, again clamped to 0 through 1; the **primary operation** for a machine is the operation that runs on it with the lowest `sequence_no` across all routings, breaking ties by the earliest operation `created_at`. Quality is the summed good units divided by the summed total units, clamped to 0 through 1; if the summed total units is zero, quality is taken to be 0.

Rounding order is pinned to remove ambiguity. The three component ratios are each stored rounded to 4 decimal places as `oee_availability`, `oee_performance`, and `oee_quality`. The overall figure `oee_overall` is computed by multiplying the three full-precision clamped ratios — availability, performance, and quality, *not* their already-rounded forms — together and rounding that single product to 4 decimal places. As a side effect of the same recompute, the machine's `quality_flagged` is set to true when the just-computed `oee_quality` is at or below the quality floor of 0.95, and false otherwise; the comparison uses the stored 4-decimal-rounded `oee_quality` value (not the unrounded ratio), and the boundary value of exactly 0.95 does flag. (This default recompute computes performance on the ideal-cycle-time basis described above; a nameplate-rate basis that would instead derive performance from run time over planned time is documented only as a divergent alternative and is not used.)

### 3.4. Creating and Releasing a Work Order: the Explosion Cascade

A `ProductionPlanner` opens production by creating a **WorkOrder** that names the finished-good `product_id` to build, the `routing_id` to follow, and the `order_qty` to produce (strictly greater than 0). A new work order begins in `PLANNED` `status` and carries a family of computed quantity fields that all start at 0: `started_qty` (units that entered the first operation), `completed_qty` (units that passed the final operation), `scrapped_qty` (units scrapped via disposition), `wip_qty` (the in-process count, which always equals `started_qty` minus `completed_qty` minus `scrapped_qty`), and `material_variance_cents` (filled in at completion).

Releasing the work order advances its `status` from `PLANNED` to `RELEASED` and is the system's signature cascade. The request must carry `expected_work_order_version` for the concurrency check described in §2.8; a mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (412). Release is permitted only when the referenced routing is in `RELEASED` status — otherwise the release is rejected with `ERR_ROUTING_NOT_RELEASED` — and when that routing's `product_id` equals the work order's `product_id` (a product mismatch is likewise rejected with `ERR_ROUTING_NOT_RELEASED`). These routing-status and product-match gates are evaluated before the `expected_work_order_version` concurrency check, so a request that both names an unreleased routing and carries a stale version fails with `ERR_ROUTING_NOT_RELEASED` rather than `ERR_STALE_VERSION`. When those conditions hold, release performs three cascading hops in one transaction: it explodes the multi-level bill of material into **ComponentDemand** rows (hop one); it computes each demand's `required_qty` and `standard_cost_cents` (hop two); and it creates one **WorkOrderOperation** per operation in the routing, in ascending sequence order (hop three). The work order's `version` is then incremented.

The explosion walks the bill-of-material graph top-down from the work order's product. Exactly one component demand row is created per distinct component product reached — counting both subassemblies and raw materials — and quantities from every path that reaches the same component accumulate into that single row. For each edge along a path, the effective quantity consumed per parent unit is the line's `quantity_per` divided by the quantity that remains after scrap, namely one minus `scrap_factor_pct` expressed as a fraction of one (so a `scrap_factor_pct` of 10 divides by 0.9). The `required_qty` for a component is the order quantity multiplied by the product of those effective per-parent quantities along each path, summed across all paths reaching that component; it is stored as a full-precision (possibly fractional) numeric value and is not rounded up to a whole unit. A demand's `standard_cost_cents` is its `required_qty` multiplied by that component's own `unit_cost_cents`, rounded to whole cents — and because a subassembly with no unit cost contributes 0, only priced components add to the standard total. Each component demand also tracks an `issued_qty`, the running sum of quantities issued against it, which starts at 0. Component demands for a work order can be listed by work order, fetched individually, or listed and filtered by their `component_product_id`.

### 3.5. Executing Work-Order Operations on the Floor

Each **WorkOrderOperation** is a work-in-process node minted at release. It records the `work_order_id` it belongs to, the `operation_id` of the routing operation it instantiates, the `machine_id` copied from that operation at release, and a `sequence_no` copied from the operation that defines its place in the WIP flow. A node begins in `QUEUED` `status` and carries `units_in` (units routed into the operation, defaulting to 0), the computed `good_qty` and `scrap_qty` (each defaulting to 0), and optional planned-schedule fields `scheduled_start` and `scheduled_end` (each defaulting to null). The full set of statuses a node can hold is `QUEUED`, `IN_PROGRESS`, `PAUSED`, `COMPLETED`, and `REWORK`.

**Starting** a node advances it from `QUEUED` to `IN_PROGRESS`. An operator may supply `scheduled_start`, `scheduled_end`, and `units_in` on the start request; when `units_in` is omitted it defaults to the parent work order's `order_qty`. A start is gated by several checks. The parent work order must be in `RELEASED` or `IN_PROCESS` status. Every work-order operation in the same order with a lower `sequence_no` must already be `COMPLETED`; starting out of order is rejected with `ERR_OPERATION_SEQUENCE_VIOLATION`. The referenced machine must not be `DOWN`, or the start is rejected with `ERR_MACHINE_DOWN`. Finally, the node's scheduled window must clear the prior operation's reserved time on the same work center: a start is rejected with `ERR_SETUP_BUFFER_CONFLICT` when its window would begin at or before the prior operation's `scheduled_end` extended by that operation's `setup_buffer_secs` — the buffered interval is treated as closed, so a window that begins exactly at the buffered end-instant still conflicts. When a start succeeds it sets the node's `units_in`, sets its `status` to `IN_PROGRESS`, and sets the referenced machine's `status` to `RUNNING`; and if this is the first operation of the order, it bubbles the work order forward from `PLANNED` or `RELEASED` to `IN_PROCESS`, sets the order's `started_qty` to its `order_qty`, and recomputes the order's `wip_qty`.

A running node can be **paused**, moving from `IN_PROGRESS` to `PAUSED` and returning its machine to `AVAILABLE`. A `PAUSED` node can be **resumed** back to `IN_PROGRESS`, which also requires that its machine is not `DOWN` (again `ERR_MACHINE_DOWN` otherwise) and sets the machine to `RUNNING`. The pause and resume edges together form a cyclic loop. A node in `REWORK` is also re-opened through the same resume action, advancing from `REWORK` to `IN_PROGRESS` (the rework re-entry edge produced by a disposition, described in §3.7); this rework resume likewise requires the machine not to be `DOWN` and, exactly like the `PAUSED` resume, sets the referenced machine's `status` to `RUNNING`.

**Completing** a node advances it from `IN_PROGRESS` to `COMPLETED`. Completion is gated by the electronic traveler: a `TravelerSignoff` whose `result` is `PASS` must already exist for this node, or completion is rejected with `ERR_TRAVELER_NOT_SIGNED`. Completion also requires the unit balance to hold — the `good_qty` supplied on the request plus the units already scrapped at this node must equal the units routed into the node (`units_in`); this balance check runs after the traveler gate, and a balance that does not hold is rejected with `ERR_INVALID_REQUEST` (400). On success the node's `good_qty` is set from the request, its `status` becomes `COMPLETED`, and its machine returns to `AVAILABLE`; and if this is the final operation of the order, the work order's `completed_qty` is increased by that `good_qty` and the order's `wip_qty` is recomputed. `COMPLETED` is the terminal state for a WIP node. Work-order operations can be listed under their work order, fetched individually, or listed and filtered by `operation_id`, `machine_id`, `work_order_id`, or `status`.

### 3.6. The Electronic Traveler

Quality sign-off is recorded as an append-only **TravelerSignoff** against a work-order operation. A `QualityInspector` (or `PlantAdmin`) appends a sign-off carrying a `result` of either `PASS` or `FAIL`; the server stamps the signing user's opaque identifier as `inspector_user_id`, records the operation as `work_order_operation_id`, and stamps `signed_at` as the server time of the sign-off. Appending a sign-off requires only that the target work-order operation exists; it is not gated on the node's `status`, so a sign-off may be appended against a node in any state. Sign-offs are immutable once written and can be listed for a given work-order operation. As noted in §2.4, a sign-off carries only `id` and `created_at` and has neither `updated_at` nor `version`. The presence of a `PASS` sign-off is precisely what unlocks completion of the corresponding operation in §3.5.

### 3.7. Defect Disposition: the Scrap-or-Rework Fork

When defects are found at an operation, a `MachineOperator` or `QualityInspector` raises a **ScrapDisposition** against the work-order operation. The disposition records the `work_order_operation_id`, the `quantity` of units in question (strictly greater than 0), and a `defect_code` classifying the defect. It begins in `PENDING` `status` and carries a computed `scrap_cost_cents` defaulting to 0. At creation the requested `quantity` must not exceed the operation's still-available units — that is, the node's `units_in` minus the units already recorded in its `scrap_qty` — or the request is rejected with `ERR_SCRAP_QTY_EXCEEDS`. Dispositions can be listed for a work-order operation and fetched individually.

A `QualityInspector` (or `PlantAdmin`) then resolves a `PENDING` disposition by supplying a `decision`, which forks into two terminal outcomes with deliberately divergent effects. Both forks first require that the disposition is still `PENDING` and re-confirm that its `quantity` does not exceed the operation's available units (`units_in` minus current `scrap_qty`), rejecting an over-quantity re-confirmation with `ERR_SCRAP_QTY_EXCEEDS` (422) just as at creation.

- **Scrap.** A `decision` of `SCRAP` advances the disposition from `PENDING` to `SCRAPPED`. It computes `scrap_cost_cents` as the disposition `quantity` multiplied by the affected product's `unit_cost_cents`, where the affected product is the parent work order's finished-good `product_id` (not the operation's machine, routing, or any component product). It adds that `quantity` to the work-order operation's `scrap_qty`. And it adds that `quantity` to the parent work order's `scrapped_qty` and recomputes the order's `wip_qty`. This branch debits cost and work-in-process and does not reopen the operation.
- **Rework.** A `decision` of `REWORK` advances the disposition from `PENDING` to `REWORKED`, and computes no scrap cost (its `scrap_cost_cents` stays 0). It sets the referenced work-order operation's `status` to `REWORK`, reopening it. If the reopened operation was the order's final operation, it decreases the work order's `completed_qty` by the disposition `quantity` and recomputes the order's `wip_qty`. And it voids the operation's existing `PASS` traveler sign-off so the operation must be signed off again before it can re-complete. This branch reopens the operation and reverses its completion but assesses no scrap cost.

Resolving either way requires the disposition to be `PENDING`; a disposition already `SCRAPPED` or `REWORKED` cannot be dispositioned again and yields `ERR_INVALID_STATE`.

### 3.8. Lot Inventory, Issues, and Genealogy

Raw and subassembly inventory enters the system as **Lot** records, received by a `MachineOperator` or `PlantAdmin`. A lot names the lot-controlled `product_id` it holds, a unique `lot_code`, and the `received_qty` brought into inventory (strictly greater than 0). On creation the lot's `on_hand_qty` is set equal to its `received_qty` and its `issued_qty` is set to 0; thereafter the conservation invariant `on_hand_qty` plus `issued_qty` equals `received_qty` is held at all times. Lots can be listed and filtered by `product_id`.

Material is consumed by recording a **LotIssue**, which both decrements inventory and builds genealogy. An issue names the `component_demand_id` it fulfills, the `lot_id` it draws from, the `work_order_operation_id` that consumes the material (the genealogy anchor), and the `issued_qty` drawn (strictly greater than 0). Two business rules guard an issue, evaluated after the universal existence and state gates: first, the source lot's product must match the demand's component — the lot's `product_id` must equal the demand's `component_product_id`, or the issue is rejected with `ERR_LOT_PRODUCT_MISMATCH`; second, the requested `issued_qty` must not exceed the source lot's `on_hand_qty`, or the issue is rejected with `ERR_INSUFFICIENT_LOT_QTY`. A successful issue decrements the lot's `on_hand_qty`, increments the lot's `issued_qty`, and increments the matching component demand's `issued_qty`, each by the issued amount. Each issue also carries a `reversed` boolean, defaulting to false, set to true only when a compensating reversal later restores its quantity. Lot issues can be listed and filtered by `component_demand_id`, `lot_id`, or `work_order_operation_id`.

Genealogy is captured in **GenealogyLink** rows that bind a produced lot to the component lots consumed into it. A link records the `work_order_id` of the build, the `parent_lot_id` of the produced finished or subassembly lot, the `child_lot_id` of a consumed component lot, and the server-set `consumed_qty` of that child drawn into the parent. Genealogy links for a work order can be listed by work order, fetched individually, or listed and filtered by `parent_lot_id` or `child_lot_id`.

### 3.9. Completing, Closing, and Cancelling a Work Order

Once execution finishes, a `ProductionPlanner` **completes** the work order, advancing it from `IN_PROCESS` to `COMPLETED`. Completion is permitted only when every work-order operation for the order is in `COMPLETED` status and the order's `wip_qty` is 0. On success it finalizes the consumed lots' `issued_qty` and seals the genealogy links for the order — both already settled incrementally (lot `issued_qty` is maintained at each issue, and the system mints no `GenealogyLink` rows, so the genealogy collection stays empty and these are no-op confirmations at completion) — computes the work order's `material_variance_cents`, sets the status to `COMPLETED`, and increments the order's `version`. Material variance is the actual material cost minus the standard material cost: the actual cost is the sum, over every non-reversed lot issue for this order, of that issue's `issued_qty` multiplied by its source lot's product `unit_cost_cents`, each per-issue product rounded to whole cents before being summed; the standard cost is the sum of `standard_cost_cents` across the order's component demands. The variance is the actual integer total minus the standard integer total, so it is positive when operators over-issued relative to standard and negative when they under-issued.

A `COMPLETED` work order is **closed** by a `ProductionPlanner`, advancing it from `COMPLETED` to `CLOSED`, but only when no scrap disposition for the order remains `PENDING`; closing increments the order's `version`, and `CLOSED` is terminal.

A work order may instead be **cancelled** by a `ProductionPlanner` from either of two earlier states, each with its own precondition and effects. Cancelling a `PLANNED` order (permitted while it is still `PLANNED`) advances it from `PLANNED` to `CANCELLED` and increments its `version`. Cancelling a `RELEASED` order advances it from `RELEASED` to `CANCELLED` but is permitted only when no work-order operation for the order is currently `IN_PROGRESS`; this richer cancellation reverses every non-reversed lot issue for the order — restoring each source lot's `on_hand_qty` and marking the issue `reversed` — deletes the order's component demand rows, sets the status to `CANCELLED`, and increments the order's `version`. `CANCELLED` is terminal. Any cancel, complete, close, or release attempted from a state for which the transition is not defined is rejected with `ERR_INVALID_STATE`.

### 3.10. The Cost Summary

At any point a `ManufacturingEngineer`, `ProductionPlanner`, or `PlantAdmin` may request a work order's cost summary, a purely computed read that returns four integer-cent figures: `bom_standard_total_cents`, `actual_cost_cents`, `labor_total_cents`, and `material_variance_cents`. The standard total is the sum of `standard_cost_cents` across the order's component demands. The actual cost is the same actual material figure used for variance — the sum over non-reversed lot issues of `issued_qty` times the source lot's product `unit_cost_cents`, each per-issue cost rounded to whole cents before summing. The material variance figure mirrors `material_variance_cents`, the actual total minus the standard total.

Labor is computed fresh for the summary. For each work-order operation in `COMPLETED` status, the operation's labor seconds are the operation's `ideal_cycle_time_secs` multiplied by that node's `good_qty`, and the operation's labor cost is those seconds multiplied by the labor rate of 2 cents per second, rounded to whole cents. The reported `labor_total_cents` is the sum of those per-operation labor costs, with each operation's labor rounded before summing — summing exact seconds-cost and rounding once is the documented naive alternative and is not used.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or recompute an existing resource, and all read operations, return `200 OK`. All endpoints are mounted directly under the API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product (finished good, subassembly, or raw material) | ManufacturingEngineer, PlantAdmin |
| GET | `/products/{id}` | Fetch a product | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/bom-lines` | Add a BOM line; rejects self-loops and cycles | ManufacturingEngineer, PlantAdmin |
| GET | `/bom-lines/{id}` | Fetch a BOM line | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| GET | `/bom-lines` | List BOM lines; filter by parent or component product | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| POST | `/routings` | Create a DRAFT routing for a product | ManufacturingEngineer, PlantAdmin |
| GET | `/routings/{id}` | Fetch a routing | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| GET | `/routings` | List routings; filter by product or status | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| POST | `/routings/{id}/operations` | Attach an operation to a DRAFT routing | ManufacturingEngineer, PlantAdmin |
| GET | `/routings/{id}/operations` | List operations of a routing | ManufacturingEngineer, ProductionPlanner, MachineOperator, PlantAdmin |
| POST | `/routings/{id}/release` | Release a DRAFT routing | ManufacturingEngineer, PlantAdmin |
| POST | `/routings/{id}/archive` | Archive a RELEASED routing | ManufacturingEngineer, PlantAdmin |
| POST | `/machines` | Register a machine / work center | ManufacturingEngineer, PlantAdmin |
| GET | `/machines/{id}` | Fetch a machine including latest OEE fields | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/machines/{id}/operations` | List routing operations that run on a machine | ManufacturingEngineer, ProductionPlanner, MachineOperator, PlantAdmin |
| POST | `/machines/{id}/status` | Set machine operational status | MachineOperator, PlantAdmin |
| POST | `/machines/{id}/run-logs` | Append a run-log window; rejects overlap | MachineOperator, PlantAdmin |
| GET | `/machines/{id}/run-logs` | List a machine's run logs | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/machines/{id}/recompute-oee` | Recompute A/P/Q and overall OEE; set quality flag | ManufacturingEngineer, QualityInspector, PlantAdmin |
| POST | `/lots` | Receive a lot of a lot-controlled product | MachineOperator, PlantAdmin |
| GET | `/lots/{id}` | Fetch a lot | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/lots` | List lots; filter by product | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/work-orders` | Create a PLANNED work order | ProductionPlanner, PlantAdmin |
| GET | `/work-orders/{id}` | Fetch a work order with WIP fields | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/work-orders` | List work orders; filter by product, routing, or status | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/work-orders/{id}/release` | Release a work order: explode BOM and mint operations | ProductionPlanner, PlantAdmin |
| POST | `/work-orders/{id}/complete` | Complete an IN_PROCESS work order | ProductionPlanner, PlantAdmin |
| POST | `/work-orders/{id}/close` | Close a COMPLETED work order | ProductionPlanner, PlantAdmin |
| POST | `/work-orders/{id}/cancel` | Cancel a PLANNED or RELEASED work order | ProductionPlanner, PlantAdmin |
| GET | `/work-orders/{id}/cost-summary` | Computed cost read for a work order | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| GET | `/work-orders/{id}/component-demands` | List exploded component demands for a work order | ManufacturingEngineer, ProductionPlanner, MachineOperator, PlantAdmin |
| GET | `/component-demands/{id}` | Fetch a component demand | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| GET | `/component-demands` | List component demands; filter by work order or component product | ManufacturingEngineer, ProductionPlanner, PlantAdmin |
| GET | `/work-orders/{id}/operations` | List WorkOrderOperations of a work order | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/work-order-operations/{id}` | Fetch a WIP node | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/work-order-operations` | List WIP nodes; filter by operation, machine, work order, or status | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/work-order-operations/{id}/start` | Start a QUEUED op; enforces sequence, machine, and setup-buffer gates | MachineOperator |
| POST | `/work-order-operations/{id}/pause` | Pause an IN_PROGRESS op | MachineOperator |
| POST | `/work-order-operations/{id}/resume` | Resume a PAUSED or REWORK op | MachineOperator |
| POST | `/work-order-operations/{id}/complete` | Complete an IN_PROGRESS op; requires PASS sign-off and balanced units | MachineOperator |
| POST | `/work-order-operations/{id}/signoffs` | Append a traveler sign-off to a WIP node | QualityInspector, PlantAdmin |
| GET | `/work-order-operations/{id}/signoffs` | List traveler sign-offs for a WIP node | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/work-order-operations/{id}/scrap-dispositions` | Raise a PENDING scrap/rework disposition | MachineOperator, QualityInspector |
| GET | `/work-order-operations/{id}/scrap-dispositions` | List scrap dispositions for a WIP node | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/scrap-dispositions/{id}/disposition` | Disposition a PENDING scrap record as SCRAP or REWORK | QualityInspector, PlantAdmin |
| GET | `/scrap-dispositions/{id}` | Fetch a scrap disposition | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| POST | `/lot-issues` | Issue lot quantity against a component demand | MachineOperator, PlantAdmin |
| GET | `/lot-issues/{id}` | Fetch a lot issue | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/lot-issues` | List lot issues; filter by demand, lot, or consuming op | ManufacturingEngineer, ProductionPlanner, MachineOperator, QualityInspector, PlantAdmin |
| GET | `/work-orders/{id}/genealogy` | List genealogy links for a work order | ManufacturingEngineer, ProductionPlanner, QualityInspector, PlantAdmin |
| GET | `/genealogy-links/{id}` | Fetch a genealogy link | ManufacturingEngineer, ProductionPlanner, QualityInspector, PlantAdmin |
| GET | `/genealogy-links` | List genealogy links; filter by parent or child lot | ManufacturingEngineer, ProductionPlanner, QualityInspector, PlantAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OPERATION_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_ROUTING_NOT_RELEASED` | 409 Conflict |
| `ERR_MACHINE_DOWN` | 409 Conflict |
| `ERR_TRAVELER_NOT_SIGNED` | 409 Conflict |
| `ERR_RUNLOG_OVERLAP` | 409 Conflict |
| `ERR_SETUP_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_BOM_CYCLE` | 409 Conflict |
| `ERR_DUPLICATE_SEQUENCE` | 409 Conflict |
| `ERR_SCRAP_QTY_EXCEEDS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QTY` | 422 Unprocessable Entity |
| `ERR_LOT_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
