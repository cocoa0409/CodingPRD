# Cmms Preventive Maintenance API — Product Requirements Document

## 1. Introduction

Industrial maintenance teams spend their days reconciling two competing realities: the physical wear of machinery that runs on hours, cycles, or kilometres, and the calendar obligations that arrive whether or not a machine has been used. The Cmms Preventive Maintenance API is a computerized-maintenance-management backend that unifies both worlds. It tracks a fleet of physical **assets** arranged in a parent-and-child hierarchy, records the runtime each asset accrues against a usage meter, and lets maintenance planners attach preventive-maintenance schedules that fire automatically — either when a meter threshold is crossed or when a calendar interval elapses.

When a schedule comes due, the system generates a **work order**: a unit of maintenance work that carries a computed priority, reserves spare parts from a finite storeroom inventory, is assigned to a technician whose weekly workload is tracked, and ultimately records the labour and parts cost incurred. The platform additionally logs **downtime events** with reason codes so it can derive reliability metrics — mean time between failures and mean time to repair — for every asset, and it allows the cost of a closed work order to be reimbursed by a manufacturer **warranty claim** rather than charged against a site's maintenance budget.

This document specifies the complete behavioural contract for that backend: the resource model, the parallel state machines that govern work orders and their parts, the dual-variant calculations for scheduling, priority, reliability, and warranty payout, the validation hierarchy, and the role-based permissions that bind every operator action to a single accountable role.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and structural contracts that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the request is made. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and recognized but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely as follows: `MaintenanceManager`, `Planner`, `Technician`, `InventoryClerk`, and `WarrantyAdmin`. Their responsibilities are peer-scoped rather than tiered, with one exception: `MaintenanceManager` is the operational superset that owns asset configuration, site and technician records, retirement, and the test-driving clock, and may additionally act on most operator surfaces shared with the other roles.

The identity semantics differ by role. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on work-order execution actions compare the work order's `assigned_technician_id` to `X-User-ID`, so a technician may start, hold, resume, or close only the work orders assigned to them. A technician acting on a work order they are not assigned to — including any work order whose `assigned_technician_id` is null, such as one still in `DRAFT` — fails this ownership check and is rejected with `ERR_FORBIDDEN`; this ownership gate is part of authorization and is therefore evaluated before the target's state validity (§3.10). When `X-User-Role` is `MaintenanceManager`, `Planner`, `InventoryClerk`, or `WarrantyAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

For every list response, the envelope's `meta` object includes `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created, and `updated_at` is an ISO 8601 UTC timestamp recording the most recent mutation. The `version` field is an integer that starts at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.6.

One entity is the exception to this convention. A `MeterReading` is immutable once recorded: it carries only `id` and `created_at`, and it has neither `updated_at` nor `version`. Every other entity — `Site`, `SparePart`, `Technician`, `Asset`, `PMSchedule`, `WorkOrder`, `PartReservation`, `DowntimeEvent`, and `WarrantyClaim` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

Recomputation of a derived field counts as a mutation of the resource that owns it. When the server recalculates an asset's `meter_reading`, `mtbf_hours`, `mttr_hours`, or `status`, a technician's `backlog_hours`, a spare part's `reserved_qty`, a site's `budget_spent_cents`, or a schedule's anchor and next-due fields, that resource's `updated_at` is refreshed and its `version` is incremented.

### 2.5. Hierarchical Consistency and Cascading Effects

The system holds a strict invariant: derived fields and parent state must always agree with the source rows that feed them, and that reconciliation happens atomically inside the request that triggers it. There is no deferred or eventually-consistent settlement — every cascade completes before the response is returned.

Several operations therefore touch more than one resource. Closing a work order, for example, simultaneously debits storeroom stock, releases reservations, rebases a PM schedule's anchors, recomputes a technician's backlog, and charges a site budget. An asset's operational `status` is itself derived: it is `DOWN` whenever any downtime event on that asset is `OPEN`, returns to `OPERATIONAL` when the last open downtime is resolved, and becomes `RETIRED` only through an explicit retire action. The detailed cascades are described inline with the workflows in §3; the governing principle is that no client request leaves the data set in a partially reconciled state.

### 2.6. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of their parent resource by requiring the client to declare the parent version it last observed.

The first is reserving spare parts for a work order. That request must include `expected_spare_part_version` carrying the client's last observed `version` of the target `SparePart`. If that value does not match the part's current `version` — because another reservation against the same part has already consumed availability and advanced the part's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. A reservation create can legitimately succeed on its own when availability remains, which is precisely why this guard is needed: it stops a client from committing a reservation against a part whose supply picture it has not actually seen.

The second is retiring an asset. That request must include `expected_asset_version` carrying the client's last observed `version` of the target `Asset`. If a meter reading, downtime open, or PM rebase has advanced the asset's `version` since the client read it, the value will not match the asset's current `version` and the retire is rejected with `ERR_STALE_VERSION` and HTTP status 412.

No other endpoint takes a version field; operations not listed here are not subject to an OCC check.

### 2.7. Monetary Values, Meter Values, and Precision

Monetary amounts are stored and exchanged as integer cents — `maintenance_budget_cents`, `budget_spent_cents`, `unit_cost_cents`, `committed_cost_cents`, `actual_cost_cents`, `acquisition_cost_cents`, `warranty_cost_cap_cents`, `claimed_cost_cents`, and `payable_cost_cents` are all whole-cent integers, never decimal currency, so warranty payout math is exact and requires no rounding.

Calculated numeric scores that are not cents — a work order's `priority_score`, an asset's `mtbf_hours`, and an asset's `mttr_hours` — are rounded half-up to two decimal places. Meter quantities (`meter_reading`, `meter_interval`, `next_due_meter`, `anchor_meter`) are plain numbers carried without rounding. Calendar arithmetic adds whole days.

### 2.8. Reference Validation and Path Resolution

Several resources reference others by foreign key. When a request path contains resource identifiers, the system validates them left to right and rejects the first one that does not resolve with `ERR_NOT_FOUND`. When a create request body carries a foreign key — an asset's `site_id` or `parent_asset_id`, a schedule's or reading's or downtime's or work order's `asset_id`, a reservation's `spare_part_id`, a claim's `work_order_id`, and so on — each referenced resource must exist, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Beyond existence and authorization, every create or action request body must contain its required fields with the correct types and valid enum values; a missing field, wrong type, or unrecognized enum value yields `ERR_INVALID_REQUEST`.

List endpoints expose foreign keys as optional filters so callers can navigate the graph in reverse. Assets can be filtered by `site_id` or `parent_asset_id`; meter readings, PM schedules, and downtime events by `asset_id`; work orders by `asset_id`, `pm_schedule_id`, `assigned_technician_id`, or `warranty_claim_id`; reservations by `spare_part_id`; downtime events by `work_order_id`; and warranty claims by `asset_id` or `work_order_id`.

### 2.9. The Test-Driving Clock

Because calendar-based preventive maintenance and warranty coverage both depend on the current time, the server exposes a controllable logical clock. A `MaintenanceManager` may set the server's current UTC instant by supplying a `to_iso8601` value; every subsequent reference to "now" — calendar PM due-checks, warranty coverage windows, timestamps written into `closed_at`, `opened_at`, and resolved downtime — uses this value until it is set again.

## 3. Business Logic & Workflows

### 3.1. Sites, Spare Parts, and Technicians: The Operating Resources

Three foundational records exist independently of the asset hierarchy. A **Site** is created by a `MaintenanceManager` with a `name`, an optional `timezone` (an IANA identifier used for display only — all timestamps are stored in UTC, and the timezone defaults to `UTC` when omitted), and a `maintenance_budget_cents` figure that must be zero or greater. The site's `budget_spent_cents` begins at 0 and is a running total: it is the sum of `actual_cost_cents` over every `CLOSED` work order whose asset belongs to the site and whose cost was not covered by an approved warranty claim. It is recomputed whenever a work order closes and whenever a warranty claim is approved or denied.

A **SparePart** is created by an `InventoryClerk` or a `MaintenanceManager`. Each part has a `sku` that must be non-empty and unique across all parts by exact case-sensitive match — a duplicate `sku` at create time is rejected with `ERR_DUPLICATE_SKU`. A part also carries a `name`, an `on_hand_qty` of physical units in the storeroom (which must be zero or greater and includes any units currently reserved), a `unit_cost_cents` used to value committed parts, and an optional `reorder_point` (defaulting to 0) that flags low stock when available quantity falls to or below it. The part's `reserved_qty` is computed: it begins at 0 and equals the sum of `qty` over reservations on that part whose status is `RESERVED` or `COMMITTED`, recomputed on every reservation create, commit, and release. Available units are therefore `on_hand_qty` minus `reserved_qty`.

A **Technician** is created by a `MaintenanceManager` with a `name`, a `skill_level` of `JUNIOR`, `SENIOR`, or `MASTER`, and a `weekly_capacity_hours` that must be greater than zero and serves as the backlog ceiling. The technician's `backlog_hours` begins at 0 and is the sum of `estimated_labor_hours` over the work orders assigned to that technician whose execution status is `ASSIGNED`, `IN_PROGRESS`, or `ON_HOLD`; it is recomputed on assign, unassign, hold, resume, and close.

### 3.2. The Asset Hierarchy and Its Meter

A `MaintenanceManager` creates an **Asset** by supplying the `site_id` it is located at, an optional `parent_asset_id` naming its parent in the hierarchy (null for a top-level asset), and a `name`. Both `site_id` and `parent_asset_id` are fixed at creation and cannot be changed afterward. Optional inputs include `criticality` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, defaulting to `MEDIUM`), `meter_unit` (`HOURS`, `CYCLES`, or `KM`, defaulting to `HOURS`), `warranty_expires_at` (the exclusive UTC end of manufacturer warranty coverage, null when there is no warranty), `warranty_cost_cap_cents` (the maximum cents a single warranty claim will reimburse, null for unlimited within coverage), and `acquisition_cost_cents` (the capital cost, zero or greater, defaulting to 0).

On creation an asset's `status` is `OPERATIONAL`, its `meter_reading` is 0, and its `mtbf_hours` and `mttr_hours` are both 0. The asset's status is never set directly: it becomes `DOWN` while any downtime event on it is open and returns to `OPERATIONAL` when the last open downtime is resolved, and the only deliberate transition is retirement.

The `meter_reading` is the cumulative usage value: it equals the `value` of the most recent `MeterReading` for the asset ordered by `reading_at` (breaking ties by `created_at` ascending), or 0 when no reading exists. A `Technician` or `MaintenanceManager` records a reading by supplying a `value` and a `reading_at` timestamp. Because a meter only ever advances, the submitted `value` must be at least the asset's current `meter_reading` and the `reading_at` must be strictly later than the latest existing reading's `reading_at`; a value below the current reading or a non-advancing timestamp is rejected with `ERR_METER_NOT_MONOTONIC`. Submitting a reading increments the asset's `version`. Each reading carries a `triggered_pm` flag, computed as true when that reading caused at least one meter-based PM schedule to come due and generate a work order.

An asset can be retired by a `MaintenanceManager`. Retirement is permitted only when the asset is `OPERATIONAL` — an asset that is `DOWN`, or that has any work order in `UNASSIGNED`, `ASSIGNED`, `IN_PROGRESS`, or `ON_HOLD`, is considered busy and the attempt is rejected with `ERR_ASSET_BUSY`. The request must also carry `expected_asset_version` matching the asset's current `version` (§2.6); a mismatch yields `ERR_STALE_VERSION`. A successful retire moves the asset to the terminal `RETIRED` status, increments its `version`, and cascades by setting `active` to false on every PM schedule of that asset so no further preventive work is generated.

### 3.3. Preventive Maintenance Schedules and Due Evaluation

A `Planner` or `MaintenanceManager` attaches a **PMSchedule** to an asset. Each schedule names a `trigger_type` of either `METER` or `CALENDAR`, an `estimated_labor_hours` (greater than zero) that a generated work order is expected to consume, an optional `severity` of `ROUTINE`, `MAJOR`, or `OVERHAUL` (defaulting to `ROUTINE`) that is copied onto generated work orders and gates technician skill, and an optional `active` flag (defaulting to true) that, when false, soft-pauses generation so the schedule never produces work orders.

The two trigger types require mutually exclusive interval fields. A `METER` schedule must supply a `meter_interval` (greater than zero) — the number of meter units between PMs — and must leave `calendar_interval_days` null. A `CALENDAR` schedule must supply a `calendar_interval_days` (a positive integer count of days between PMs) and must leave `meter_interval` null. Any other combination — a meter schedule missing its interval or carrying a calendar interval, or vice versa — is rejected with `ERR_SCHEDULE_CONFIG_INVALID`.

Every schedule tracks a baseline from which the next PM is measured. The `anchor_meter` is the meter value at the last PM completion, initialized to the asset's `meter_reading` at schedule creation; the `anchor_date` is the UTC timestamp of the last completion, initialized to creation time. From these the server computes the next-due targets. For a meter schedule, `next_due_meter` is the anchor meter plus the meter interval, and `next_due_date` is null; the schedule is **due** when the asset's `meter_reading` is greater than or equal to `next_due_meter` (the boundary value itself counts as due). For a calendar schedule, `next_due_date` is the anchor date plus the calendar interval expressed in whole days, and `next_due_meter` is null; the schedule is due when the current clock instant is greater than or equal to `next_due_date` (again, the boundary instant counts as due).

Meter schedules are evaluated automatically each time a reading is submitted: for every active meter schedule on the asset that has become due, the server auto-creates a preventive work order and marks the reading's `triggered_pm` true. Calendar schedules — and any manual sweep — are evaluated through an explicit generate-due capability available to a `Planner` or `MaintenanceManager`: if the schedule is due it creates a preventive work order, and if it is not yet due the request is rejected with `ERR_PM_NOT_DUE`.

### 3.4. Work Orders and the Priority Score

A work order is the unit of maintenance work. Preventive work orders are generated by the scheduling machinery of §3.3 and are never created directly. Corrective (unplanned) work orders are created by a `Planner` or `MaintenanceManager`, who supplies the `asset_id`, a `wo_type` of `CORRECTIVE`, a `severity`, and an `estimated_labor_hours` (greater than zero). For a generated preventive order the `wo_type` is `PREVENTIVE`, the `pm_schedule_id` records the schedule that produced it, and the `severity` and `estimated_labor_hours` are copied from that schedule; a corrective order has a null `pm_schedule_id` and supplies its own severity. Every work order starts with `execution_status` of `DRAFT`, `parts_status` of `NONE`, a null `assigned_technician_id`, a null `warranty_claim_id`, null `opened_at` and `closed_at`, and an `actual_cost_cents` of 0.

The `priority_score` is computed once at creation from the asset and schedule as observed at that moment, then frozen — it is never recomputed when the asset later changes. The score combines three multiplicative factors and a conditional additive bump. A criticality weight is drawn from the asset's `criticality`: `LOW` is 1, `MEDIUM` is 2, `HIGH` is 4, and `CRITICAL` is 8. A severity weight is drawn from the work order's `severity`: `ROUTINE` is 1, `MAJOR` is 3, and `OVERHAUL` is 5. An overrun multiplier applies only when the order is `PREVENTIVE` and its schedule's trigger type is `METER`: the raw overrun is the asset's `meter_reading` divided by the larger of the schedule's `next_due_meter` and 1, then clamped to lie between 1.0 and 3.0 inclusive; in every other case the overrun multiplier is exactly 1.0. The base is the product of the criticality weight, the severity weight, and the overrun multiplier. To this base, add 10 when the work order is `CORRECTIVE` and 0 otherwise. The result is rounded half-up to two decimal places and stored as `priority_score`.

### 3.5. Planning Work: Release, Assignment, Scheduling, and Cancellation

A work order's execution lifecycle is driven by the `Planner` (with `MaintenanceManager` able to act in the same surface). A draft order is moved into the queue, advancing `execution_status` from `DRAFT` to `UNASSIGNED`; this is permitted only while the order is `DRAFT` and the asset is not `RETIRED`, and it changes no inventory or backlog.

Assigning an `UNASSIGNED` order to a technician requires the caller to supply that `technician_id`. Two gates apply. First is the skill gate: ranking severities as `ROUTINE` 1, `MAJOR` 2, `OVERHAUL` 3, and skill levels as `JUNIOR` 1, `SENIOR` 2, `MASTER` 3, the technician's skill rank must be greater than or equal to the work order's severity rank — an exact match is allowed — otherwise the assignment is rejected with `ERR_SKILL_INSUFFICIENT`. Second is the backlog gate: the technician's `backlog_hours` plus the work order's `estimated_labor_hours` must not exceed the technician's `weekly_capacity_hours`, or the assignment is rejected with `ERR_BACKLOG_EXCEEDED`. A successful assign advances `execution_status` from `UNASSIGNED` to `ASSIGNED`, sets `assigned_technician_id`, and increases the technician's `backlog_hours` by the order's `estimated_labor_hours`.

Once a work order is `ASSIGNED`, a planner may book a maintenance window for it by supplying a `scheduled_start` and a `scheduled_end`, where `scheduled_end` must be strictly after `scheduled_start`. The window is treated as the half-open interval from `scheduled_start` up to but not including `scheduled_end`: two windows that merely touch at an endpoint do not overlap, but any positive-length overlap does. Booking is rejected with `ERR_TECH_DOUBLE_BOOKED` when the new window overlaps any window already booked on another non-terminal work order (one whose execution status is not `CLOSED` or `CANCELLED`) for the same assigned technician. Scheduling a window leaves the order in `ASSIGNED` and does not change backlog. An `ASSIGNED` order can also be returned to the queue: unassigning it advances `execution_status` back to `UNASSIGNED`, clears `assigned_technician_id`, and decreases the technician's `backlog_hours` by the order's `estimated_labor_hours`.

A work order may be cancelled by a planner while its execution status is `DRAFT`, `UNASSIGNED`, or `ASSIGNED`. Cancellation moves the order to the terminal `CANCELLED` status. If the order was `ASSIGNED`, the cascade decreases the assigned technician's `backlog_hours` by the order's `estimated_labor_hours` and clears `assigned_technician_id`. In all cancel cases the cascade releases every reservation on the order whose status is `RESERVED` by setting it to `RELEASED` and recomputing the affected spare part's `reserved_qty`; because committed reservations cannot exist before a work order reaches `IN_PROGRESS`, no stock is debited by a cancel.

### 3.6. Executing Work: Start, Hold, Resume, and Close

Execution actions are reserved to the `Technician` who is assigned to the order — the acting technician's identity must match the order's `assigned_technician_id`. Starting an `ASSIGNED` order advances it to `IN_PROGRESS` and sets `opened_at` to the current clock instant if it was previously null. A start is allowed only when the order's `parts_status` is `NONE` or `RESERVED`; parts that are not yet committed do not block starting work.

While in progress, a technician may put the order `ON_HOLD` and later resume it back to `IN_PROGRESS`; this hold-and-resume cycle is the one non-linear loop in the execution dimension. A held order still counts toward the technician's backlog — placing it on hold and resuming it leave `backlog_hours` unchanged.

Closing an order is permitted only while it is `IN_PROGRESS`. Two preconditions guard the close. No reservation on the order may still be `RESERVED` — the parts status must be `NONE` or `COMMITTED`, and any uncommitted reservation blocks the close with `ERR_PARTS_NOT_COMMITTED`. And no downtime event referencing this work order may be `OPEN`, or the close is rejected with `ERR_DOWNTIME_OPEN`. The technician supplies the order's `actual_cost_cents` at close. A successful close advances `execution_status` to `CLOSED`, sets `closed_at` to the current instant, and decreases the assigned technician's `backlog_hours` by the order's `estimated_labor_hours`. It then runs three cascades. If the parts status is `COMMITTED`, each committed reservation's `qty` is debited from its spare part's `on_hand_qty`, those reservations are set to `RELEASED`, and each affected part's `reserved_qty` is recomputed (the order's `parts_status` thereby becomes `RELEASED`). If the order is `PREVENTIVE` with a `pm_schedule_id`, the schedule is rebased — `anchor_meter` is set to the asset's current `meter_reading`, `anchor_date` to the close time, and the next-due fields recomputed. Finally, if the order has no `warranty_claim_id`, the asset's site has its `budget_spent_cents` increased by the order's `actual_cost_cents`; warranty-covered orders never touch the budget.

### 3.7. Spare-Part Reservations: Reserve, Commit, and Release

Spare parts flow through a finite pool managed by the `InventoryClerk`. A reservation is created against a work order by supplying the `spare_part_id`, the `qty` (greater than zero), and the OCC token `expected_spare_part_version`. The work order must be in a state that admits reservations — `UNASSIGNED`, `ASSIGNED`, `IN_PROGRESS`, or `ON_HOLD`, but not `DRAFT` and not a terminal state. There must be enough free stock: the part's `on_hand_qty` minus its `reserved_qty` must be at least the requested `qty`, otherwise the reservation is rejected with `ERR_INSUFFICIENT_STOCK`. The OCC check described in §2.6 also applies here. Creating the reservation records it with status `RESERVED`, recomputes the part's `reserved_qty`, increments the part's `version`, and sets the work order's `parts_status` to `RESERVED` (the first reservation moves it from `NONE`; subsequent reservations keep it at `RESERVED`).

A `RESERVED` reservation can be released early by the inventory clerk, provided the parent work order is not already `CLOSED`. Releasing sets the reservation's status to `RELEASED`, recomputes the part's `reserved_qty` (freeing the units, with `on_hand_qty` unchanged), and — if this was the work order's last reservation that had not yet been released — sets the work order's `parts_status` to `RELEASED`.

Committing parts is a single action that operates on the whole work order: it requires the order to be `IN_PROGRESS` and at least one reservation to be `RESERVED`. It transitions every `RESERVED` reservation on the order to `COMMITTED`, freezing each reservation's `committed_cost_cents` as its `qty` multiplied by the part's `unit_cost_cents`, and sets the work order's `parts_status` to `COMMITTED`. Committing does not yet change `on_hand_qty` — committed units still count toward `reserved_qty` until the close cascade debits stock — and `committed_cost_cents` remains 0 while a reservation is `RESERVED` or after it has been `RELEASED`.

### 3.8. Downtime, Reliability Metrics, and Asset Status

A downtime event records an interval during which an asset is out of service. A `Technician` or `MaintenanceManager` logs one against an asset by supplying a `reason_code`, a `started_at` UTC instant, and optionally the `work_order_id` of the corrective order addressing it (null when logged standalone). The reason code is one of `MECHANICAL_FAILURE`, `ELECTRICAL_FAILURE`, `OPERATOR_ERROR`, `PLANNED_PM`, or `IDLE`; the first two are the failure-class codes that feed reliability metrics, and the others do not. A new event opens with status `OPEN`, an `ended_at` of null, and a `duration_hours` of 0. Because an asset cannot have two concurrently open downtimes, logging a new open event whose interval would overlap an existing open downtime on the same asset is rejected with `ERR_DOWNTIME_OVERLAP`. Opening a downtime moves the asset to `DOWN` if it was `OPERATIONAL`, and if the reason code is a failure class it recomputes the asset's `mtbf_hours`.

Resolving an open event is done by a `Technician` or `MaintenanceManager` who supplies the `ended_at` instant, which must be strictly after `started_at`. The resolved interval must additionally not extend past the `started_at` of the next failure-class downtime on the same asset — closed intervals may touch but not overlap — and a violation of either bound is rejected with `ERR_DOWNTIME_INTERVAL_INVALID`. Resolving sets `ended_at`, marks the event `RESOLVED`, and sets `duration_hours` to the elapsed time in hours, computed as the difference between `ended_at` and `started_at` divided by 3600 seconds. If the reason code is a failure class, the asset's `mttr_hours` is recomputed. And if this was the asset's last open downtime, the asset transitions from `DOWN` back to `OPERATIONAL`.

The two reliability metrics are derived per asset. Mean time between failures considers the asset's downtime rows whose reason code is `MECHANICAL_FAILURE` or `ELECTRICAL_FAILURE`, regardless of whether they are open or resolved, ordered by `started_at` ascending and breaking ties by `created_at` ascending. If fewer than two such failures exist, `mtbf_hours` is 0; otherwise it is the mean of the consecutive start-to-start gaps — for each adjacent pair, the difference between the later event's `started_at` and the earlier event's `started_at` divided by 3600 seconds — rounded half-up to two decimal places. It is recomputed each time a failure-class downtime opens. Mean time to repair considers only resolved failure-class downtime rows for the asset; if there are none, `mttr_hours` is 0, otherwise it is the mean of those events' `duration_hours` rounded half-up to two decimal places. It is recomputed each time a failure-class downtime is resolved.

### 3.9. Warranty Claims and Budget Reimbursement

When a closed work order's cost should be borne by the manufacturer rather than the site, a `WarrantyAdmin` or `MaintenanceManager` submits a **WarrantyClaim** by supplying the `asset_id`, the `work_order_id` whose cost the claim seeks to cover, and a `claim_type` of either `REPLACEMENT` or `REPAIR`. The claim opens with status `SUBMITTED`, a `claimed_cost_cents` and `payable_cost_cents` of 0, and a null `decision_reason`.

A `WarrantyAdmin` decides the claim. Approval requires the claim to be `SUBMITTED`, the referenced work order to be `CLOSED`, the work order's `closed_at` to fall strictly before the asset's `warranty_expires_at` (otherwise `ERR_WARRANTY_EXPIRED`), and the asset not to be `RETIRED`. On approval the payout is computed in a fixed order: first the cost basis, then the cap. The basis, `claimed_cost_cents`, is the asset's `acquisition_cost_cents` when the claim type is `REPLACEMENT` and the work order's `actual_cost_cents` when the claim type is `REPAIR`. The cap is the asset's `warranty_cost_cap_cents`: when the cap is null the `payable_cost_cents` equals the claimed amount, and otherwise it is the smaller of the claimed amount and the cap. Approval sets the claim to `APPROVED`, records the optional `decision_reason`, links the work order by setting its `warranty_claim_id` to this claim, and reimburses the site by decreasing `budget_spent_cents` by the work order's `actual_cost_cents` — the charge that was applied when the order closed is returned because warranty now covers it. Denial requires only that the claim be `SUBMITTED`; it sets the claim to `DENIED`, records the optional `decision_reason`, fixes `payable_cost_cents` at 0, and leaves the site's `budget_spent_cents` unchanged so the close-time charge stands.

### 3.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed precedence so the returned error is deterministic. Authentication comes first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a recognized role lacking permission yields `ERR_FORBIDDEN`, and the technician-ownership check on work-order execution actions (§2.1) is part of this same authorization stage, so a `Technician` acting on a work order not assigned to them is rejected with `ERR_FORBIDDEN` here — before any state-validity check. Then path existence is checked left to right, returning `ERR_NOT_FOUND` on the first unresolved path id, followed by body foreign-key existence yielding `ERR_REFERENCE_NOT_FOUND`. Request well-formedness is then checked, yielding `ERR_INVALID_REQUEST` for missing fields, wrong types, or bad enums. State validity comes next: an action whose target is not in a state from which the transition is defined yields `ERR_INVALID_STATE`. The optimistic-concurrency check (`ERR_STALE_VERSION`) is then applied where it is in force. Only after all of these structural checks pass does the system evaluate the domain-specific business rules — skill gating, schedule configuration, meter monotonicity, downtime overlap and interval bounds, stock availability, technician backlog, warranty coverage, parts-committed and downtime-open close guards, SKU uniqueness, asset-busy retirement, and technician double-booking — each surfacing its own error as described alongside the workflow it guards.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or act on an existing resource return `200 OK`. The clock-setting capability returns `200 OK` with no resource body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sites` | Create a site with a maintenance budget | MaintenanceManager |
| GET | `/sites/{id}` | Fetch a site including computed budget_spent_cents | MaintenanceManager, Planner, WarrantyAdmin |
| GET | `/sites` | List sites | MaintenanceManager, Planner, WarrantyAdmin |
| POST | `/spare-parts` | Create a spare part | InventoryClerk, MaintenanceManager |
| GET | `/spare-parts/{id}` | Fetch a spare part with computed reserved_qty | InventoryClerk, MaintenanceManager, Planner |
| GET | `/spare-parts` | List spare parts | InventoryClerk, MaintenanceManager, Planner |
| POST | `/technicians` | Create a technician | MaintenanceManager |
| GET | `/technicians/{id}` | Fetch a technician with computed backlog_hours | MaintenanceManager, Planner, Technician |
| GET | `/technicians` | List technicians | MaintenanceManager, Planner, Technician |
| POST | `/assets` | Create an asset (optionally under a parent asset) | MaintenanceManager |
| GET | `/assets/{id}` | Fetch an asset with computed meter/status/reliability | MaintenanceManager, Planner, Technician, WarrantyAdmin, InventoryClerk |
| GET | `/assets` | List assets; filter by site_id or parent_asset_id | MaintenanceManager, Planner, Technician, WarrantyAdmin, InventoryClerk |
| POST | `/assets/{id}/retire` | Retire an asset (OCC-guarded); deactivates its PM schedules | MaintenanceManager |
| POST | `/assets/{id}/meter-readings` | Submit a meter reading; may trigger PM generation | Technician, MaintenanceManager |
| GET | `/assets/{id}/meter-readings` | List meter readings for an asset | MaintenanceManager, Planner, Technician |
| POST | `/assets/{id}/pm-schedules` | Create a PM schedule on an asset | Planner, MaintenanceManager |
| GET | `/assets/{id}/pm-schedules` | List PM schedules for an asset | Planner, MaintenanceManager, Technician |
| GET | `/pm-schedules/{id}` | Fetch a PM schedule with computed next-due fields | Planner, MaintenanceManager, Technician |
| POST | `/pm-schedules/{id}/generate-due` | Force-evaluate a schedule and generate a work order if due | Planner, MaintenanceManager |
| POST | `/work-orders` | Create a corrective work order | Planner, MaintenanceManager |
| GET | `/work-orders/{id}` | Fetch a work order with computed priority and both status dimensions | Planner, MaintenanceManager, Technician, WarrantyAdmin, InventoryClerk |
| GET | `/work-orders` | List work orders; filter by asset_id, pm_schedule_id, assigned_technician_id, or warranty_claim_id | Planner, MaintenanceManager, Technician, WarrantyAdmin, InventoryClerk |
| POST | `/work-orders/{id}/release-to-queue` | Move a DRAFT work order to UNASSIGNED | Planner, MaintenanceManager |
| POST | `/work-orders/{id}/assign` | Assign an UNASSIGNED work order to a technician | Planner, MaintenanceManager |
| POST | `/work-orders/{id}/schedule-window` | Book a maintenance time window for the assigned technician | Planner, MaintenanceManager |
| POST | `/work-orders/{id}/unassign` | Return an ASSIGNED work order to the queue | Planner, MaintenanceManager |
| POST | `/work-orders/{id}/start` | Begin work (ASSIGNED to IN_PROGRESS) | Technician |
| POST | `/work-orders/{id}/hold` | Pause an IN_PROGRESS work order | Technician |
| POST | `/work-orders/{id}/resume` | Resume an ON_HOLD work order | Technician |
| POST | `/work-orders/{id}/close` | Complete a work order; commits parts, debits stock, rebases PM, charges budget | Technician |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal, non-started work order | Planner, MaintenanceManager |
| POST | `/work-orders/{id}/reservations` | Reserve units of a spare part for a work order (OCC-guarded on the part) | InventoryClerk |
| GET | `/work-orders/{id}/reservations` | List reservations for a work order | InventoryClerk, Planner, MaintenanceManager, Technician |
| GET | `/reservations/{id}` | Fetch a reservation with computed status and committed_cost_cents | InventoryClerk, Planner, MaintenanceManager |
| GET | `/reservations` | List reservations; filter by spare_part_id | InventoryClerk, Planner, MaintenanceManager |
| POST | `/reservations/{id}/release` | Release a RESERVED reservation early | InventoryClerk |
| POST | `/work-orders/{id}/commit-parts` | Commit all RESERVED reservations on an IN_PROGRESS work order | InventoryClerk |
| POST | `/assets/{id}/downtime-events` | Log a downtime event on an asset with a reason code | Technician, MaintenanceManager |
| GET | `/assets/{id}/downtime-events` | List downtime events for an asset | MaintenanceManager, Planner, Technician |
| GET | `/downtime-events/{id}` | Fetch a downtime event with computed duration_hours and status | MaintenanceManager, Planner, Technician |
| GET | `/downtime-events` | List downtime events; filter by work_order_id | MaintenanceManager, Planner, Technician |
| POST | `/downtime-events/{id}/resolve` | Resolve an open downtime event; recomputes MTTR and may restore the asset | Technician, MaintenanceManager |
| POST | `/warranty-claims` | Submit a warranty claim against a closed work order | WarrantyAdmin, MaintenanceManager |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim with computed claimed/payable amounts | WarrantyAdmin, MaintenanceManager, Planner |
| GET | `/warranty-claims` | List warranty claims; filter by asset_id or work_order_id | WarrantyAdmin, MaintenanceManager, Planner |
| POST | `/warranty-claims/{id}/approve` | Approve a claim; computes payable, links work order, reimburses budget | WarrantyAdmin |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | WarrantyAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC time | MaintenanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SKILL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_CONFIG_INVALID` | 422 Unprocessable Entity |
| `ERR_METER_NOT_MONOTONIC` | 422 Unprocessable Entity |
| `ERR_DOWNTIME_OVERLAP` | 409 Conflict |
| `ERR_DOWNTIME_INTERVAL_INVALID` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_BACKLOG_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_PARTS_NOT_COMMITTED` | 409 Conflict |
| `ERR_DOWNTIME_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_ASSET_BUSY` | 409 Conflict |
| `ERR_PM_NOT_DUE` | 409 Conflict |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
</content>
</invoke>
