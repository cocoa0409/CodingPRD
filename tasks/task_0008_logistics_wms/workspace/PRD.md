# Logistics WMS API — Product Requirements Document

## 1. Introduction

This document specifies the contract for a Warehouse Management System (WMS) backend that drives a single distribution center end-to-end: receiving inbound shipments at the dock, sampling them for quality, putting goods away into capacity-controlled bins by item category, allocating outbound orders against on-hand inventory under expiry- or arrival-based selection rules, releasing waves of pick tasks along an optimised path, packing and shipping with carrier-prefixed tracking, counting cycle inventory under segregation of duties, and tracing lots forward and backward when a recall or expiry is declared.

The system is built around three operational realities that shape almost every rule in §3. First, time is a simulated, manually advanced quantity — the warehouse keeps a `clock_now` that operators advance through an explicit test-driving capability, and threshold-driven transitions such as near-expiry and expired only fire on that advance or on a periodic operations checkpoint. Second, the warehouse operates under a calculated **operational posture** — `OPEN`, `RESTRICTED`, or `FROZEN` — derived from rolling shrinkage, recent abnormal events, and the count of open recalls; that posture gates whether new outbound allocations may proceed. Third, every floor action that changes physical reality (putaway, allocation, picking, packing, shipping, cycle-count adjustment, recall, dispose) cascades into a tightly defined chain of secondary effects across bins, inventory rows, pick tasks, orders, and warehouse-level counters, and the test suite asserts each of those secondary effects directly.

The reader audience is the engineer building the implementation. Domain concepts are introduced before the structural contract, but the structural contract — response envelope, pagination, role headers, optimistic-concurrency mechanics, validation priority — is precise where the business logic is deliberately spread across §3 subsections.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (a non-empty opaque caller identifier) and `X-User-Role` (the caller's role name). If either header is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED` and HTTP status 401. If both headers are present but `X-User-Role` is not one of the three role names below, the request is rejected with `ERR_FORBIDDEN` and HTTP status 403. The same `ERR_FORBIDDEN` is returned when the caller's role is recognised but is not authorised for the specific endpoint per the role-permission matrix in §4.

There are exactly three role names, spelled exactly as follows:

- `WarehouseStaff` — day-to-day floor operations: receiving and inspecting inbound shipments, putaway, order allocation, picking, packing, shipping, scheduling cycle counts, and disposing of lots.
- `Auditor` — independent inventory auditor whose exclusive capability is approving cycle-count adjustments, bound by segregation of duties (an auditor cannot approve a count they themselves submitted).
- `WarehouseManager` — privileged operator: creates warehouses, bins, and lots, declares lot recalls, runs the operations checkpoint, and advances the simulated clock.

For all three roles the `X-User-ID` header is an opaque operator identifier and is not tied to any persisted entity — the server does not look up a `WarehouseStaff` row, `Auditor` row, or `WarehouseManager` row by id, nor does it perform any ownership check that compares `X-User-ID` to a field on a resource. The server does, however, **record** `X-User-ID` on entities that need to track who acted: when a cycle count is submitted, the caller's `X-User-ID` is captured as `submitted_by_user_id` on the `CycleCount`, and when an adjustment is approved, the approver's `X-User-ID` is captured as `approved_by_user_id`. The segregation-of-duties check (see §3.8) is the only place the server compares one `X-User-ID` against another, and it does so by comparing the approver's header to the recorded `submitted_by_user_id` on the same `CycleCount` — yielding `ERR_SEGREGATION_OF_DUTIES` and HTTP status 403 when they match.

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

List endpoints accept two query parameters, `limit` and `offset`. The default for `limit` is 10, the minimum is 1, and the maximum is 100; `offset` defaults to 0 and must be a non-negative integer. List endpoints sort their results by `created_at` in ascending order (oldest first).

The `meta` object for list responses includes `limit` (the effective page size used), `offset` (the effective starting index used), `total_count` (the total number of matching rows before pagination is applied), and `has_more` (true when more rows exist past the current page, false otherwise).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource — `Warehouse`, `Bin`, `Lot`, `InboundShipment`, `InboundLine`, `Inventory`, `Wave`, `Order`, `PickTask`, and `CycleCount` — carries four common properties: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set once when the resource is first persisted and is never modified, and `updated_at` is rewritten to the current server time on every mutation that bumps `version`. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every mutation (state transition, field write, computed-field recomputation that the rules below explicitly mark as a `version` bump).

Optimistic concurrency control (OCC) is offered on every mutating endpoint by allowing the request body to include an optional `version` field. When `version` is supplied, the server compares it to the current `version` of the target resource: if the values differ, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP status 409, and no state change occurs. When `version` is omitted from the request body, the OCC check is skipped and the operation proceeds based on its other validations. The OCC check sits within the validation priority described in §2.6 — it is evaluated after authentication, role check, existence checks, and after the target's state has been confirmed eligible for the requested transition.

### 2.5. Hierarchical Path Resolution and Foreign Keys

Resource URLs are nested: bins, lots, inbound shipments, inbound lines, inventory rows, waves, orders, pick tasks, and cycle counts all live underneath their parent warehouse. Each persisted resource records its parent reference as a system field — `warehouse_id` on every entity directly nested under a warehouse, and `inbound_shipment_id` on every inbound line — and these parent references are server-set on creation, never accepted from request bodies. Path-id parameters are resolved left-to-right, and the first id that does not exist within its parent scope yields `ERR_NOT_FOUND` with HTTP status 404. Concretely, `warehouseId` is checked before any nested id; if the warehouse does not exist, the request fails before the system attempts to look up the nested resource. Likewise, when a request body carries foreign-key fields — `bin_id`, `lot_id`, `order_ids`, `inventory_id` — each referenced id must resolve to an existing entity scoped to the same warehouse as the parent path; an unresolvable foreign key in the body also yields `ERR_NOT_FOUND` with HTTP status 404.

### 2.6. Validation Priority

When a single request triggers more than one possible failure, validations are evaluated in a fixed priority order, and the first failing rule decides the response. The order, from highest priority (evaluated first) to lowest priority (evaluated last), is:

1. **Authentication.** Both `X-User-ID` and `X-User-Role` headers must be present and non-empty, otherwise `ERR_AUTH_REQUIRED`.
2. **Role recognition.** `X-User-Role` must be one of `WarehouseStaff`, `Auditor`, `WarehouseManager`, otherwise `ERR_FORBIDDEN`.
3. **Path-existence (left-to-right).** Every path-id must exist within its parent scope, otherwise `ERR_NOT_FOUND`.
4. **Body foreign-key existence.** Every foreign-key id in the request body (`lot_id`, `bin_id`, entries of `order_ids`, etc.) must exist in the same warehouse, otherwise `ERR_NOT_FOUND`.
5. **State eligibility.** The target resource must be in a state that admits the requested transition, otherwise `ERR_INVALID_STATE`.
6. **Lot-status pickability.** A lot may not be picked, shipped, or putaway when its `status` is in the set `RECALLED`, `EXPIRED`, or `DISPOSED`; an order may not be shipped if any lot referenced by a `PICKED` pick task has fallen into `RECALLED`, `EXPIRED`, or `QUARANTINED` (this latter guard surfaces as `ERR_LOT_NOT_SHIPPABLE`). Pick-task start failures and inbound-line lot-status failures surface as `ERR_LOT_NOT_PICKABLE` and `ERR_LOT_NOT_ACTIVE` respectively at the point each is reached.
7. **Segregation of duties.** When approving a cycle-count adjustment, the caller's `X-User-ID` must differ from the cycle count's `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.
8. **Zone match.** For inbound putaway the chosen bin's `zone` must equal the line's lot `category`; for quarantine the chosen bin's `zone` must equal `RETURNS`. A mismatch is `ERR_ZONE_MISMATCH`.
9. **ASN match.** On start-of-inspection, `declared_total_units` on the inbound shipment must equal the sum of `declared_units` over all of its inbound lines; a mismatch is `ERR_ASN_MISMATCH`.
10. **Bin freeze.** A bin whose `status` is `FROZEN` (held by an open cycle count) cannot host putaway nor be the source of a pick task start, yielding `ERR_BIN_FROZEN`.
11. **Wave overlap.** A wave cannot transition `PLANNED` → `RELEASED` while another wave on the same warehouse is in `RELEASED` or `IN_PROGRESS`; the loser receives `ERR_WAVE_OVERLAP`.
12. **Bin capacity.** For each putaway line, the chosen bin must have remaining volume at least `received_units` × the lot's `unit_volume_cm3` and remaining weight at least `received_units` × the lot's `unit_weight_g`; if no bin satisfies these along with the zone and active filters, the response is `ERR_NO_BIN_AVAILABLE`.
13. **Inventory sufficiency.** Each requested order line must be fully satisfiable from inventory whose lot `status` is `ACTIVE` or `NEAR_EXPIRY`; a shortfall yields `ERR_INSUFFICIENT_INVENTORY`.
14. **Operational posture gate.** While the warehouse `posture` is `FROZEN`, no order may transition `CREATED` → `ALLOCATED` and no `SHORT_PICKED` order may be replanned back to `ALLOCATED`; both are rejected with `ERR_POSTURE_FROZEN`.
15. **Pick-complete payload bounds.** On pick-task completion, `picked_units` must satisfy "at least 0 and at most `planned_units`", otherwise `ERR_INVALID_INPUT` (HTTP status 422).
16. **Inspection-complete payload bounds.** On complete-inspection, `inspection_defect_count` must satisfy "at least 0 and at most `inspection_sample_size`", otherwise `ERR_INVALID_INPUT` (HTTP status 422).
17. **Pack pre-conditions.** A `PICKED` order may pack to `PACKED` only when none of its pick tasks is in `SHORT_PICKED` or `FAILED`; a `SHORT_PICKED` order may pack to `PACKED` only when the request body field `allow_partial` is exactly `true` and at least one pick task is `PICKED`. Otherwise the response is `ERR_INVALID_STATE`.
18. **Lot-dispose openness.** Disposing a lot is rejected with `ERR_LOT_HAS_OPEN_PICKS` while at least one pick task referencing the lot is in `CREATED` or `PICKING`.
19. **Carrier enumeration.** On order creation, `carrier` must be one of `UPS`, `FEDEX`, `USPS`; any other value yields `ERR_INVALID_INPUT` (HTTP status 422).

The OCC check (`ERR_VERSION_CONFLICT`) sits between rules 5 and 6 — i.e., it is applied after the target's state is confirmed eligible and before any business-safety check.

### 2.7. Time, Simulated Clock, and Operational Checkpoints

Every warehouse owns a `clock_now` field that represents simulated wall-clock time. On warehouse creation `clock_now` is initialised to the fixed epoch `1970-01-01T00:00:00.000Z` and `ops_run_index` is initialised to 0. Real time does not advance `clock_now`; instead, an admin-only test-driving capability advances `clock_now` by request, taking a `warehouse_id` body parameter and a `new_time` body parameter and rewriting `clock_now` to the supplied `new_time` instant. Whenever `clock_now` advances, two scans run automatically against that warehouse: a near-expiry scan over every lot not already in `EXPIRED`, `RECALLED`, `QUARANTINED`, or `DISPOSED`, and a recomputation of the rolling counters that depend on time windows (see §3.1).

The operations checkpoint is a separate manager-only capability; calling it increments `ops_run_index` by 1, runs the same near-expiry scan, automatically closes any inbound shipment whose lines are all in `PUTAWAY` or all in `QUARANTINED`, decays `abnormal_event_count_24h` by dropping events whose timestamp is older than 86400 seconds before `clock_now`, recomputes `shrinkage_value_30d_cents` by dropping cycle counts that were `ADJUSTED` more than 30 simulated days ago, and recomputes `risk_score` and `posture` from the resulting counters.

### 2.8. Precision, Rounding, and Numeric Conventions

All rounding in this system is "round half up" — fractional values whose dropped digit is exactly 5 round upward in magnitude. Specific precisions:

- `defect_rate` on inbound shipments is rounded to 4 decimal places.
- `distance_from_dock` on bins and `total_path_distance` on waves are rounded to 4 decimal places.
- `risk_score` on warehouses is rounded to 2 decimal places and capped at 1000.00.
- `variance_value_cents` on cycle counts is rounded to integer cents (no fractional cents) before being summed into `shrinkage_value_30d_cents`. Summing fractional values across cycle counts and rounding once at the end is wrong; the rounding-then-summing order is fixed.
- `used_volume_cm3`, `used_weight_g`, `remaining_volume_cm3`, `remaining_weight_g`, `qty_units`, `reserved_units`, `available_units`, `planned_units`, `picked_units`, `book_qty`, `counted_qty`, `variance_units`, `inspection_sample_size`, `inspection_defect_count`, `declared_total_units`, `declared_units`, `received_units`, `provisional_carton_count`, `final_carton_count`, `unit_weight_g`, `unit_volume_cm3`, `unit_value_cents`, `capacity_volume_cm3`, `capacity_weight_g`, `position_x`, `position_y`, `dock_position_x`, `dock_position_y`, `ops_run_index`, `recall_count_open`, `abnormal_event_count_24h`, `shrinkage_value_30d_cents`, `planned_unit_count`, `picked_unit_count`, and `sequence` are integer-valued; intermediate products are integer and not rounded.
- All monetary quantities are integer cents.

### 2.9. Concurrency, Serialization, and Cross-Entity Cascades

The system promises immediate consistency: every write that the API confirms is reflected in subsequent reads on the same resource without delay. Five concurrency races have specific guarantees:

- Two callers attempting to allocate the same order at the same time serialize on `Order.status`: exactly one allocate succeeds, and the loser — which now observes a status other than `CREATED` — is rejected with `ERR_INVALID_STATE` and HTTP status 409.
- Two callers attempting to schedule a cycle count on the same `(bin_id, lot_id)` pair simultaneously serialize on `Bin.frozen_by_cycle_count_id`: at most one cycle count can hold a bin's freeze at a time, and the second caller is rejected with `ERR_BIN_FROZEN` and HTTP status 409.
- Two callers attempting to release different waves on the same warehouse at the same time serialize on the warehouse-level wave-exclusivity check: exactly one wave reaches `RELEASED`, and the loser receives `ERR_WAVE_OVERLAP` and HTTP status 409.
- Two pickers attempting to complete the same pick task simultaneously serialize on `PickTask.status`: the first completion wins, and the second observes a status other than `PICKING` and is rejected with `ERR_INVALID_STATE` and HTTP status 409.
- Order-allocation racing with a lot recall on a candidate lot: the lot's `status` as read at allocation time defines the selector's candidate set. If the recall completes first, the allocate either succeeds while excluding that lot (when other lots cover the requested units) or fails with `ERR_INSUFFICIENT_INVENTORY` (when exclusion creates a shortfall). If the allocate completes first, the recall cascades through the now-existing pick tasks to fail them, per the cascade rules in §3.9.

Mutation always bumps `version` and rewrites `updated_at` on every entity that the operation directly modifies. When a single operation mutates more than one entity (allocation, putaway, recall, cycle-count adjustment, ship), every secondary entity that is touched also gets its `version` bumped and `updated_at` refreshed; the §3 narratives below name each cascade explicitly so that no secondary effect is left implicit.

## 3. Business Logic & Workflows

### 3.1. Warehouse Setup, Reference Data, and Operational Posture

A warehouse is the top-level container for everything else. Creating a warehouse takes a `name`, an inbound dock location given by `dock_position_x` and `dock_position_y` (the origin from which bin distances are measured), and an optional `putaway_strategy` selector that defaults to `DISTANCE_OPTIMIZED` when the request omits it; the alternative value is `CAPACITY_OPTIMIZED`. On creation the system also seeds the warehouse with `ops_run_index` set to 0, `clock_now` set to the fixed epoch `1970-01-01T00:00:00.000Z`, the rolling counters `shrinkage_value_30d_cents`, `abnormal_event_count_24h`, and `recall_count_open` set to 0, the `risk_score` set to 0, and the `posture` set to `OPEN`.

Inside a warehouse, a manager creates bins with a `bin_code` that must be unique within the warehouse, a `zone` chosen from `AMBIENT`, `COLD`, `HAZMAT`, or `RETURNS`, the position parameters `position_x` and `position_y`, and the capacity parameters `capacity_volume_cm3` and `capacity_weight_g`. The system computes `distance_from_dock` as the Euclidean distance from the bin position to the warehouse's dock position — that is, the square root of the sum of the squared differences between `position_x` and `dock_position_x` and between `position_y` and `dock_position_y` — rounded half-up to four decimal places. Each new bin starts with `used_volume_cm3` and `used_weight_g` at 0, `status` `ACTIVE`, and `frozen_by_cycle_count_id` null. The bin's `remaining_volume_cm3` is always the difference `capacity_volume_cm3` minus `used_volume_cm3`, and `remaining_weight_g` is always `capacity_weight_g` minus `used_weight_g`; both are recomputed every time the inventory inside the bin changes (putaway, ship, dispose, or cycle-count adjustment).

A manager also creates lots — the SKU-batched material that physically occupies bins. A lot carries a `lot_code` unique within the warehouse, a `sku`, a `category` chosen from `AMBIENT`, `COLD`, `HAZMAT`, or `RETURNS` (which must match a bin's `zone` for putaway), the per-unit quantities `unit_weight_g`, `unit_volume_cm3`, and `unit_value_cents` (cents per unit, used for variance valuation), the `manufacture_date` and `expiry_date`, and the external supplier reference `supplier_lot_ref`. The `received_at` timestamp on the lot is left empty at creation and is filled by the system the very first time the lot is putaway from an inbound shipment — once written, `received_at` is never overwritten by later putaways. Newly-created lots have `status` `ACTIVE`; the `recalled_at` and `recall_reason` fields are populated only when the lot transitions into `RECALLED`.

The warehouse's **operational posture** is a derived guard. The `risk_score` is the sum of three rolling components: one point for every dollar of `shrinkage_value_30d_cents` (i.e., the integer cents counter divided by 100), plus 10 points per event in `abnormal_event_count_24h`, plus 100 points per lot in `recall_count_open`. The raw sum is rounded half-up to two decimals and capped at 1000.00. The `posture` derives directly from the score: when `risk_score` is greater than 200 the posture is `FROZEN`, when `risk_score` is greater than 100 but at most 200 the posture is `RESTRICTED`, and when `risk_score` is at most 100 the posture is `OPEN`. The score and posture recompute whenever any of the three input counters changes — so posture can change during inspection completion (which may bump `abnormal_event_count_24h`), pick-task short-pick rollups (which may bump `abnormal_event_count_24h`), recall (which bumps `recall_count_open`), dispose of a recalled lot (which decrements `recall_count_open`), cycle-count approval (which bumps `shrinkage_value_30d_cents`), and the operations checkpoint or clock advance (which may decay the windows).

The operations checkpoint is invoked by a manager and represents an explicit "wall-clock has moved" event for the warehouse. Each call increments `ops_run_index` by 1, runs the near-expiry scan over every lot whose `status` is in `ACTIVE` or `NEAR_EXPIRY` (see §3.9), automatically transitions inbound shipments whose every line is in `PUTAWAY` to `CLOSED` and inbound shipments whose every line is in `QUARANTINED` to `CLOSED`, decays `abnormal_event_count_24h` by dropping events older than 86400 seconds before `clock_now`, recomputes `shrinkage_value_30d_cents` by re-summing the integer-cent variance values from cycle counts that are `ADJUSTED` and whose `approved_at` is within the last 30 simulated days, and recomputes `risk_score` and `posture` from the refreshed counters.

Read-only retrieval of a warehouse exposes all of the fields above: identity, name, dock position, the `putaway_strategy`, the `clock_now`, `ops_run_index`, the rolling counters, the `risk_score`, and the `posture`.

### 3.2. Inbound Receiving, Inspection Sampling, and Quarantine

Inbound goods arrive as an **inbound shipment** with a server-recorded ASN. Floor staff create the shipment with an `asn_number` (unique within the warehouse), a `supplier_name`, a `declared_total_units`, and a `lines` array each carrying a `lot_id` and a `declared_units` count. A shipment begins life in status `ASN_RECEIVED`; each created line is in status `PENDING_INSPECTION`. The lot referenced by each line must already exist within the same warehouse — body foreign-key resolution applies, and an unresolvable `lot_id` yields `ERR_NOT_FOUND`.

The lifecycle continues with start-of-inspection, which is the first guarded transition. Going from `ASN_RECEIVED` to `INSPECTING` enforces two preconditions: first, `declared_total_units` on the shipment must equal the sum of `declared_units` across its lines (otherwise `ERR_ASN_MISMATCH`); second, every line's referenced lot must currently be in `ACTIVE` status (otherwise `ERR_LOT_NOT_ACTIVE`). The transition computes `inspection_sample_size` from the `declared_total_units` using the AQL sampling tier table: when total declared is at most 50 units the sample size is 8; when at most 150 it is 13; when at most 280 it is 20; when at most 500 it is 32; otherwise the sample size is 50.

Completion of inspection submits an `inspection_defect_count` along with a per-line `lines` array containing each line's `lot_id` and actual `received_units`. The `inspection_defect_count` must be at least 0 and at most `inspection_sample_size`; any other value is rejected with `ERR_INVALID_INPUT` and HTTP status 422. The system then computes `defect_rate` as `inspection_defect_count` divided by `inspection_sample_size`, rounded half-up to four decimal places. The result splits cleanly: when `defect_rate` is at most 0.025, the shipment moves from `INSPECTING` to `PASSED` and every inbound line moves from `PENDING_INSPECTION` to `INSPECTED_PASS`; when `defect_rate` is strictly greater than 0.025, the shipment moves from `INSPECTING` to `FAILED`, every inbound line moves from `PENDING_INSPECTION` to `INSPECTED_FAIL`, and `abnormal_event_count_24h` on the warehouse is incremented by exactly 1 (a single increment per failed inspection, regardless of how many lines failed).

A shipment that landed in `FAILED` may be reworked back to `INSPECTING` by floor staff: this clears `inspection_defect_count` and `defect_rate` (both are reset to null) and returns every line from `INSPECTED_FAIL` back to `PENDING_INSPECTION`, ready for re-inspection. Alternatively, a `FAILED` shipment may be quarantined into `RETURNS`-zone bins (see §3.3); doing so transitions the shipment from `FAILED` to `QUARANTINED`, sets each line's `bin_id`, moves each line from `INSPECTED_FAIL` to `QUARANTINED`, and additionally transitions every affected lot's `status` to `QUARANTINED` so the goods cannot be picked.

A `PASSED` shipment is putaway by floor staff, which moves the shipment from `PASSED` to `PUTAWAY`, sets each line's `bin_id` and transitions the line's `status` from `INSPECTED_PASS` to `PUTAWAY`, upserts inventory for the chosen `(bin_id, lot_id)` pair by adding `received_units`, recomputes the affected bins' used and remaining capacity, and writes `received_at` on each lot for which this is the first putaway (subsequent putaways of the same lot do not overwrite an existing `received_at`). A request to putaway a shipment whose lines do not all carry a positive `received_units`, or for which any line has no eligible bin in the candidate set, is rejected with `ERR_NO_BIN_AVAILABLE` for that line.

A shipment whose lines are all in `PUTAWAY` reaches the terminal `CLOSED` state automatically on the next operations checkpoint, and the same automatic closure applies when every line is in `QUARANTINED`.

### 3.3. Putaway Selection and Bin Capacity

Putaway always asks the same question: given an inbound line carrying `received_units` of a particular lot, which bin should hold it? The candidate set is built from the warehouse's bins by filtering on three properties simultaneously: the bin's `status` is `ACTIVE` (i.e., not `FROZEN` by an open cycle count); the bin's `zone` matches the lot's `category` for the putaway case, or the bin's `zone` is exactly `RETURNS` for the quarantine case; the bin's `remaining_volume_cm3` is at least `received_units` multiplied by the lot's `unit_volume_cm3` AND its `remaining_weight_g` is at least `received_units` multiplied by the lot's `unit_weight_g`. If no bin satisfies all three filters, the operation fails with `ERR_NO_BIN_AVAILABLE`. If a candidate bin satisfies the volume and weight test but its `zone` does not match `category` (or, for quarantine, is not `RETURNS`), the response is `ERR_ZONE_MISMATCH`; if the only available bin happens to be `FROZEN`, the response is `ERR_BIN_FROZEN`.

The non-empty candidate set is then sorted, and the warehouse's `putaway_strategy` chooses the sort key. Under the `DISTANCE_OPTIMIZED` strategy the candidate set is sorted by `distance_from_dock` in ascending order — the bin closest to the dock wins; ties on `distance_from_dock` are broken by `bin_code` in lexicographic ascending order. Two candidate bins of identical zone and capacity will resolve to the one with smaller `distance_from_dock` even if the other is emptier. Under the `CAPACITY_OPTIMIZED` strategy the candidate set is sorted by `remaining_volume_cm3` in descending order — the emptiest bin wins; ties on `remaining_volume_cm3` are broken by `bin_code` in lexicographic ascending order. Two candidate bins of identical zone and reachable capacity will resolve to the one with greater `remaining_volume_cm3` even if the other is closer to the dock. The selector takes the first element of the sorted candidate set and writes its id onto the inbound line.

After a putaway transition, the bin's used volume and weight are recomputed by summing across every inventory row in that bin: `used_volume_cm3` is the sum over the bin's inventory rows of `qty_units` multiplied by the row's lot `unit_volume_cm3`, and `used_weight_g` is the corresponding sum using `unit_weight_g`. Inventory rows whose lot is `DISPOSED` are excluded from this aggregation. The remaining-capacity fields are then derived as the corresponding capacity minus the recomputed used quantity.

### 3.4. Order Allocation and Pick Planning

An outbound order represents a customer shipment. Floor staff create an order with an external `order_number` (unique within the warehouse), a `customer_name`, an array `requested_lines` where each entry has a `sku` and a `qty_units` (each line must have at least one unit and the array must have at least one entry), an optional `pick_strategy` that defaults to `FEFO` when the request omits it (the alternative is `FIFO`), and a `carrier` chosen from `UPS`, `FEDEX`, or `USPS` (any other value is rejected with `ERR_INVALID_INPUT` and HTTP status 422). New orders begin life with `status` `CREATED`. The order's `wave_id`, `provisional_carton_count`, `final_carton_count`, `shipping_label_id`, and `tracking_number` are all empty at creation and are populated by later transitions.

Allocation is the first guarded transition for orders. Going from `CREATED` to `ALLOCATED` enforces two preconditions: first, the warehouse `posture` must be `OPEN` or `RESTRICTED` (otherwise `ERR_POSTURE_FROZEN`); second, every requested line must be fully satisfiable from inventory rows whose lot `status` is in `ACTIVE` or `NEAR_EXPIRY` (otherwise `ERR_INSUFFICIENT_INVENTORY`). Any candidate lot whose status is `RECALLED` or `EXPIRED` is excluded from the candidate set up-front; if the resulting set cannot fully satisfy the line, the response is still `ERR_INSUFFICIENT_INVENTORY`. A successful allocation generates pick tasks per the lot-selector rule, increases each consumed inventory row's `reserved_units` by the units allocated to the corresponding pick task, and sets the order's `provisional_carton_count` (see §3.7).

The lot selector runs once per requested line. For a requested line with a particular `sku` and a particular `qty_units`, the system collects every inventory row in the warehouse whose lot `sku` matches and whose lot `status` is `ACTIVE` or `NEAR_EXPIRY` and whose `available_units` is greater than 0. Inventory rows whose lot is in `EXPIRED`, `RECALLED`, `QUARANTINED`, or `DISPOSED` are not in the candidate set. The candidate inventory rows are then sorted: under the `FEFO` strategy the primary sort key is the lot's `expiry_date` in ascending order — the earliest-expiring lot is consumed first; under the `FIFO` strategy the primary sort key is the lot's `received_at` in ascending order — the earliest-received lot is consumed first, and `expiry_date` is irrelevant. In both strategies the tie-breaker is the lot's `lot_code` in lexicographic ascending order. The selector then walks the sorted candidates greedily: at each step it takes the smaller of the line's remaining `qty_units` and the row's `available_units`, creates a pick task on that `(bin_id, lot_id)` for that quantity, increases the row's `reserved_units` by the same quantity, and decrements the line's remaining requirement. The walk halts as soon as the line's remaining requirement reaches 0; if the candidate list is exhausted before then, allocation fails with `ERR_INSUFFICIENT_INVENTORY` and no pick tasks survive. Each pick task created this way carries `order_id`, `bin_id`, `lot_id`, `inventory_id` (the source row), `planned_units` (the quantity taken), `picked_units` initialised to 0, and `status` `CREATED`; `wave_id` and `sequence` are filled later when a wave is released.

Cancellation of orders depends on which state the order is in. A `CREATED` order may be cancelled with no preconditions and with no side effects beyond the state change. An `ALLOCATED` order may be cancelled with no preconditions; cancellation cascades all of its `CREATED` pick tasks to `CANCELLED` and reduces each consumed inventory row's `reserved_units` by the per-task `planned_units` of the cancelled pick task. A `PICKING` order — meaning at least one pick task has started — may be cancelled only when none of its pick tasks is yet in `PICKED`; if any pick task is already `PICKED`, cancellation is rejected with `ERR_INVALID_STATE`. Cancellation of a permitted `PICKING` order or of a `SHORT_PICKED` order moves all non-terminal pick tasks to `CANCELLED` and releases their reservations.

### 3.5. Wave Release and Pick Path Optimisation

A wave groups one or more `ALLOCATED` orders for a coordinated floor sweep. Floor staff create a wave with a `wave_code` (unique within the warehouse), a `strategy` chosen from `BATCH`, `ZONE`, or `ORDER`, and an `order_ids` array enumerating the orders to include. New waves enter `status` `PLANNED`; on creation, every listed order's `wave_id` is set to the new wave id, and `planned_unit_count` on the wave is computed as the sum of `planned_units` across all pick tasks of those orders.

Releasing the wave from `PLANNED` to `RELEASED` enforces two preconditions: first, no other wave on the same warehouse may be in `RELEASED` or `IN_PROGRESS` (otherwise `ERR_WAVE_OVERLAP`); second, every order id in `order_ids` must currently be in `ALLOCATED` (otherwise `ERR_INVALID_STATE`). On release, the system stamps `wave_id` onto every pick task of the included orders, assigns `sequence` numbers along the optimised pick path, sets `released_at` to the warehouse's `clock_now`, and computes `total_path_distance`.

The pick-path computation walks all of the wave's pick tasks in a deterministic order: the primary sort key is the source bin's `bin_code` in lexicographic ascending order, and the tie-breaker is the pick task's `id` in ascending order. Each pick task in that order is assigned `sequence = 1, 2, … N` where N is the wave's task count. The `total_path_distance` is then the sum of Euclidean distances along the route: starting from the warehouse's dock position, the picker walks to the first bin's `(position_x, position_y)`, then to each subsequent bin's position in `sequence` order, and finally back to the dock; each leg's distance is the square root of the sum of the squared coordinate differences between the two endpoints. The grand total is rounded half-up to four decimal places and stored as `total_path_distance` on the wave.

A `RELEASED` wave automatically transitions to `IN_PROGRESS` the moment its first pick task is started. An `IN_PROGRESS` wave automatically transitions to `COMPLETED` the moment every one of its pick tasks reaches a terminal state (`PICKED`, `SHORT_PICKED`, `FAILED`, or `CANCELLED`); the system writes `completed_at = clock_now` on the wave at that moment. A wave's `picked_unit_count` is the running sum of `picked_units` across pick tasks that have reached `PICKED` or `SHORT_PICKED`, updated as each such task completes. A `PLANNED` wave may also be cancelled with no side effects beyond the state change.

### 3.6. Picking, Short-Pick Handling, and Replan

A pick task represents one floor pick from a specific bin against a specific lot. Starting a pick task takes it from `CREATED` to `PICKING` and enforces three preconditions: the parent wave must be in `RELEASED` or `IN_PROGRESS`; the source lot's `status` must be `ACTIVE` or `NEAR_EXPIRY` (otherwise `ERR_LOT_NOT_PICKABLE`); and the source bin's `status` must be `ACTIVE` (otherwise `ERR_BIN_FROZEN`). On the first such start within a wave, the wave automatically advances from `RELEASED` to `IN_PROGRESS`; on the first such start within an order, the order automatically advances from `ALLOCATED` to `PICKING`.

Completion of a pick task takes a `picked_units` count in the request body that must be at least 0 and at most `planned_units` (any other value yields `ERR_INVALID_INPUT` with HTTP status 422). When `picked_units` exactly equals `planned_units`, the pick task moves from `PICKING` to `PICKED` and `Wave.picked_unit_count` is increased by `picked_units`. When `picked_units` is at least 0 and strictly less than `planned_units`, the pick task moves from `PICKING` to `SHORT_PICKED`: the system writes `picked_units` from the body onto the pick task, releases the unpicked reservation by decreasing the source inventory row's `reserved_units` by the difference between `planned_units` and `picked_units`, and increases `Wave.picked_unit_count` by `picked_units`.

The order's status is rolled up automatically once every pick task of the order is terminal. If every pick task is in `PICKED` or `CANCELLED` and at least one is `PICKED`, the order moves from `PICKING` to `PICKED`. If every pick task is terminal and at least one is `SHORT_PICKED` or `FAILED`, the order moves from `PICKING` to `SHORT_PICKED` and `abnormal_event_count_24h` on the warehouse is incremented by 1.

A `SHORT_PICKED` order may be replanned by floor staff, sending it back to `ALLOCATED`. The same posture gate as initial allocation applies — replan is rejected with `ERR_POSTURE_FROZEN` while `posture` is `FROZEN`. The terminal pick tasks from the previous round are retained for audit; new pick tasks are generated for the residual units (each line's `planned_units` minus the sum of `picked_units` over its existing terminal pick tasks for that lot or sku); reservations on inventory rows are adjusted by the new pick tasks' `planned_units`; and `provisional_carton_count` is recomputed from the original `requested_lines` (see §3.7).

### 3.7. Packing, Carton Calculation, and Shipping

When a wave's pick tasks complete cleanly, the order arrives at packing. Packing an order moves it from `PICKED` to `PACKED` and is rejected with `ERR_INVALID_STATE` while any pick task of the order is in `SHORT_PICKED` or `FAILED`. Packing also accepts `SHORT_PICKED` orders, but only when the request body's `allow_partial` field is exactly the boolean `true` and at least one pick task has reached `PICKED`; otherwise the response is `ERR_INVALID_STATE`. On a successful pack the system writes `final_carton_count` onto the order.

Carton counts are computed in two distinct passes: a provisional one at allocation and a final one at packing. Both share the same physical constants — a single carton holds at most 50000 cubic centimetres of volume and 20000 grams of weight — and both compute the count by taking the maximum of three values: cartons-by-volume (the order's total volume divided by 50000, rounded up to a whole carton), cartons-by-weight (the order's total weight divided by 20000, rounded up to a whole carton), and the floor of one carton (so that even a tiny order ships in at least one carton).

The two variants differ in their inputs. The **provisional** variant uses the order's `requested_lines` and a SKU-weighted average per-unit volume and weight: for each requested line, the system aggregates the per-unit volume and weight by averaging across all `ACTIVE` and `NEAR_EXPIRY` lots of that SKU at allocation time, weighted by each lot's `qty_units` in inventory; if no inventory exists for the SKU at allocation time, the lot from the most recent `PUTAWAY` inbound line is used. Provisional counts depend only on what was requested, not on which lots happen to be picked. The **final** variant uses the actual per-unit volume and weight from the lots picked: the total volume is the sum over `PICKED` pick tasks of `picked_units` times that pick task's lot `unit_volume_cm3`, and the total weight is the corresponding sum using `unit_weight_g`. `SHORT_PICKED` and `FAILED` pick tasks contribute nothing to the final volume or weight. As a consequence, two orders with identical `requested_lines` produce identical `provisional_carton_count` values regardless of how their lots were allocated, but their `final_carton_count` values may diverge.

Shipping the order moves it from `PACKED` to `SHIPPED` and enforces one further safety check: no lot referenced by any `PICKED` pick task on this order may be in `RECALLED`, `EXPIRED`, or `QUARANTINED` (otherwise `ERR_LOT_NOT_SHIPPABLE`). On a successful ship the system mints a `shipping_label_id` (formatted as `lbl_<uuid>`) and a `tracking_number` whose prefix is taken from the order's `carrier`: a `UPS` order gets a `1Z`-prefixed tracking number, a `FEDEX` order gets an `FX`-prefixed tracking number, and a `USPS` order gets a `US`-prefixed tracking number, each followed by a sequence string. Shipping also debits the warehouse's inventory: for each `PICKED` pick task of the order, the source inventory row's `qty_units` is decreased by `picked_units` and the same row's `reserved_units` is decreased by the same `picked_units`, atomically (so that `available_units`, which is always `qty_units` minus `reserved_units`, ends with the units truly gone from the warehouse). The corresponding bins recompute their used and remaining capacity.

### 3.8. Cycle Counts and Variance Adjustment

A cycle count is a planned recount of the inventory in a single `(bin_id, lot_id)` pair, executed by either floor staff or an auditor. Scheduling a cycle count creates the entity in status `SCHEDULED`, captures `book_qty` as a snapshot of the current `Inventory.qty_units` for that pair, sets `scheduled_at` to the warehouse's `clock_now`, and freezes the bin: the bin's `status` flips from `ACTIVE` to `FROZEN` and `frozen_by_cycle_count_id` is set to the new cycle-count id. While the bin is frozen, no putaway may target it and no pick task may be started on it.

Counting begins when the cycle count moves from `SCHEDULED` to `COUNTING`. Submission of the count carries a `counted_qty` that must be a non-negative integer (negative values are rejected with `ERR_INVALID_INPUT`). When `counted_qty` equals `book_qty`, the cycle count moves from `COUNTING` to `RECONCILED`: `variance_units` and `variance_value_cents` are both 0, the system records the caller's `X-User-ID` as `submitted_by_user_id`, and the bin is unfrozen — `status` returns to `ACTIVE` and `frozen_by_cycle_count_id` is cleared. When `counted_qty` differs from `book_qty`, the cycle count moves from `COUNTING` to `VARIANCE_FOUND`: `variance_units` is computed as `counted_qty` minus `book_qty` (a signed integer), `variance_value_cents` is computed as the absolute value of `variance_units` multiplied by the lot's `unit_value_cents` and rounded half-up to integer cents, the system records `submitted_by_user_id`, and `abnormal_event_count_24h` on the warehouse is increased by 1. The bin remains frozen pending audit.

A `VARIANCE_FOUND` cycle count is then either approved or disputed. Approval is exclusive to the `Auditor` role and enforces segregation of duties: the approver's `X-User-ID` must differ from the cycle count's `submitted_by_user_id`, otherwise the response is `ERR_SEGREGATION_OF_DUTIES`. On approval the cycle count moves from `VARIANCE_FOUND` to `ADJUSTED`: `Inventory.qty_units` for the `(bin_id, lot_id)` pair is overwritten with `counted_qty`; the bin recomputes `used_volume_cm3` and `used_weight_g`; `approved_by_user_id` is set to the approver's `X-User-ID` and `approved_at` is set to `clock_now`; the bin is unfrozen; and `shrinkage_value_30d_cents` on the warehouse is increased by the cycle count's `variance_value_cents` (so long as the approval falls within the rolling 30-day window). Disputing a `VARIANCE_FOUND` cycle count is open to staff or auditors, moves the cycle count to `DISPUTED`, leaves inventory unchanged, and unfreezes the bin.

The warehouse-level shrinkage aggregate is stable: `shrinkage_value_30d_cents` is the sum, over every cycle count whose `status` is `ADJUSTED` and whose `approved_at` is within the rolling 30-day window ending at `clock_now`, of that cycle count's already-rounded integer-cent `variance_value_cents`. This rounding-then-summing order is fixed; summing fractional values across cycle counts and rounding once at the end is incorrect.

### 3.9. Lot Recall, Expiry, and Disposal

Lots may leave the `ACTIVE` shelf for several reasons: time, supplier action, regulatory action, or quarantine on inspection failure. Each pathway has a specific cascade.

**Time-driven near-expiry and expiry.** During every clock advance and every operations checkpoint, the system scans every lot whose `status` is `ACTIVE` or `NEAR_EXPIRY` and computes the integer number of whole simulated days remaining until `expiry_date` — that is, the floor of (`expiry_date` minus `clock_now`) divided by 86400 seconds. When that value is strictly less than 0, the lot transitions directly to `EXPIRED` (skipping `NEAR_EXPIRY` if the clock leapt past expiry). When that value is at most 30, the lot transitions to `NEAR_EXPIRY` (the threshold is inclusive, so a lot exactly 30 days from expiry is `NEAR_EXPIRY`). Otherwise the lot remains `ACTIVE`. The `EXPIRED` transition cascades: every pick task in `CREATED` that references the now-expired lot is moved to `FAILED`, and each cancelled pick task's `Inventory.reserved_units` is decreased by its `planned_units`. Once a lot is `NEAR_EXPIRY`, it remains pickable and shippable (allocation, pick-task start, and ship all permit `NEAR_EXPIRY` alongside `ACTIVE`), but FEFO will reach for it first because of its earlier `expiry_date`.

**Supplier or safety recall.** A `WarehouseManager` may recall an `ACTIVE` or `NEAR_EXPIRY` lot, supplying a `recall_reason` chosen from `SUPPLIER_RECALL`, `SAFETY_ISSUE`, or `EXPIRY_BATCH`. A recall on any other status is rejected with `ERR_INVALID_STATE`. Recalling moves the lot to `RECALLED` and writes `recalled_at = clock_now` and `recall_reason` from the body. The cascade is broader than expiry: every pick task that references the lot in either `CREATED` or `PICKING` is moved to `FAILED`, each affected pick task's `Inventory.reserved_units` is decreased by its `planned_units`, and each affected order then rolls up to `SHORT_PICKED` (with the corresponding `abnormal_event_count_24h` increment) once its remaining pick tasks are terminal. The warehouse's `recall_count_open` is incremented by 1 and `risk_score` and `posture` are recomputed from the new counters. An `Order` whose `version` was captured before the recall and is then submitted to a state-changing operation will see `ERR_VERSION_CONFLICT` if it tries to act on the older snapshot.

**Quarantine on inspection failure.** When a `FAILED` inbound shipment is quarantined into `RETURNS`-zone bins, every affected lot's `status` is moved from `ACTIVE` to `QUARANTINED`. A `QUARANTINED` lot may not be picked or shipped — pick-task start surfaces `ERR_LOT_NOT_PICKABLE` and order ship surfaces `ERR_LOT_NOT_SHIPPABLE` if a `PICKED` pick task points at one — but the lot can be disposed of.

**Disposal.** A floor staff caller may dispose a lot whose `status` is `EXPIRED`, `RECALLED`, or `QUARANTINED`, taking it to the terminal `DISPOSED`. Disposal is rejected with `ERR_LOT_HAS_OPEN_PICKS` while at least one pick task in `CREATED` or `PICKING` references the lot. On a successful dispose, every inventory row for the lot has its `qty_units` set to 0, every affected bin recomputes `used_volume_cm3`, `used_weight_g`, `remaining_volume_cm3`, and `remaining_weight_g`, and — when the lot was leaving `RECALLED` — `recall_count_open` is decreased by 1 and `risk_score` and `posture` are recomputed.

The recall, expiry, and disposal cascades together provide forward and backward traceability: starting from a recalled lot, the recall scope is exactly the set of pick tasks, orders, inventory rows, and bins reached by these cascades; starting from any pick task, order, or shipment, the inbound `lot_id` chain back through the inbound line and the lot itself identifies the upstream supplier, the `manufacture_date`, the `expiry_date`, and the `supplier_lot_ref`.

## 4. Endpoint Definitions

All endpoints follow the rules of §2 — auth headers, response envelope, pagination defaults, validation priority, and OCC are enforced uniformly. New resources (warehouses, bins, lots, inbound shipments, orders, waves, cycle counts) are created with HTTP status 201; all other state changes and read operations succeed with HTTP status 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /warehouses | Create a warehouse | WarehouseManager |
| GET | /warehouses/{warehouseId} | Get a warehouse | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/run_ops | Operations checkpoint (near-expiry scan, auto-close shipments, decay counters, recompute posture) | WarehouseManager |
| POST | /warehouses/{warehouseId}/bins | Create a bin | WarehouseManager |
| GET | /warehouses/{warehouseId}/bins/{binId} | Get a bin | WarehouseStaff, Auditor, WarehouseManager |
| GET | /warehouses/{warehouseId}/bins | List bins | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/lots | Create a lot | WarehouseManager |
| GET | /warehouses/{warehouseId}/lots/{lotId} | Get a lot | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/lots/{lotId}/recall | Recall a lot (cascades to pick tasks and orders) | WarehouseManager |
| POST | /warehouses/{warehouseId}/lots/{lotId}/dispose | Dispose a lot (zeroes inventory, frees bin capacity) | WarehouseStaff |
| POST | /warehouses/{warehouseId}/inbound_shipments | Create an inbound shipment with one or more inbound lines | WarehouseStaff |
| GET | /warehouses/{warehouseId}/inbound_shipments/{shipmentId} | Get an inbound shipment (includes lines) | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/inbound_shipments/{shipmentId}/start_inspection | Start inspection (computes sample size; ASN match check) | WarehouseStaff |
| POST | /warehouses/{warehouseId}/inbound_shipments/{shipmentId}/complete_inspection | Submit inspection result; transitions to PASSED or FAILED | WarehouseStaff |
| POST | /warehouses/{warehouseId}/inbound_shipments/{shipmentId}/rework | Rework a FAILED shipment back to INSPECTING | WarehouseStaff |
| POST | /warehouses/{warehouseId}/inbound_shipments/{shipmentId}/putaway | Putaway PASSED shipment lines | WarehouseStaff |
| POST | /warehouses/{warehouseId}/inbound_shipments/{shipmentId}/quarantine | Quarantine FAILED shipment lines into RETURNS-zone bins | WarehouseStaff |
| GET | /warehouses/{warehouseId}/inventory | List inventory rows | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/waves | Create a wave grouping ALLOCATED orders | WarehouseStaff |
| GET | /warehouses/{warehouseId}/waves/{waveId} | Get a wave | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/waves/{waveId}/release | Release a wave (assigns pick path; transitions to RELEASED) | WarehouseStaff |
| POST | /warehouses/{warehouseId}/waves/{waveId}/cancel | Cancel a PLANNED wave | WarehouseStaff |
| POST | /warehouses/{warehouseId}/orders | Create an order | WarehouseStaff |
| GET | /warehouses/{warehouseId}/orders/{orderId} | Get an order | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/orders/{orderId}/allocate | Allocate inventory; generate pick tasks; set provisional_carton_count | WarehouseStaff |
| POST | /warehouses/{warehouseId}/orders/{orderId}/cancel | Cancel an order; release reservations and cancel pick tasks | WarehouseStaff |
| POST | /warehouses/{warehouseId}/orders/{orderId}/replan | Replan a SHORT_PICKED order | WarehouseStaff |
| POST | /warehouses/{warehouseId}/orders/{orderId}/pack | Pack the order; set final_carton_count | WarehouseStaff |
| POST | /warehouses/{warehouseId}/orders/{orderId}/ship | Ship the order; mint label; debit inventory | WarehouseStaff |
| GET | /warehouses/{warehouseId}/pick_tasks/{pickTaskId} | Get a pick task | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/pick_tasks/{pickTaskId}/start | Start a pick task | WarehouseStaff |
| POST | /warehouses/{warehouseId}/pick_tasks/{pickTaskId}/complete | Complete a pick task with picked_units | WarehouseStaff |
| POST | /warehouses/{warehouseId}/cycle_counts | Schedule a cycle count for (bin_id, lot_id); freezes the bin | WarehouseStaff, Auditor |
| GET | /warehouses/{warehouseId}/cycle_counts/{cycleCountId} | Get a cycle count | WarehouseStaff, Auditor, WarehouseManager |
| POST | /warehouses/{warehouseId}/cycle_counts/{cycleCountId}/start | Begin counting (SCHEDULED → COUNTING) | WarehouseStaff, Auditor |
| POST | /warehouses/{warehouseId}/cycle_counts/{cycleCountId}/submit_count | Submit counted_qty; transitions to RECONCILED or VARIANCE_FOUND | WarehouseStaff, Auditor |
| POST | /warehouses/{warehouseId}/cycle_counts/{cycleCountId}/approve_adjustment | Approve adjustment (Auditor only; segregation of duties) | Auditor |
| POST | /warehouses/{warehouseId}/cycle_counts/{cycleCountId}/dispute | Dispute the count without adjusting inventory | WarehouseStaff, Auditor |
| POST | /_clock/advance | Advance the simulated wall clock for a warehouse | WarehouseManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_INPUT | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ASN_MISMATCH | 409 |
| ERR_LOT_NOT_ACTIVE | 409 |
| ERR_ZONE_MISMATCH | 409 |
| ERR_NO_BIN_AVAILABLE | 409 |
| ERR_BIN_FROZEN | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_LOT_NOT_PICKABLE | 409 |
| ERR_LOT_NOT_SHIPPABLE | 409 |
| ERR_LOT_HAS_OPEN_PICKS | 409 |
| ERR_POSTURE_FROZEN | 409 |
| ERR_WAVE_OVERLAP | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VERSION_CONFLICT | 409 |
