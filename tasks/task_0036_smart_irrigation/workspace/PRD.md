# Smart Irrigation API — Product Requirements Document

## 1. Introduction

Modern precision agriculture lives or dies on the closed loop between the field and the back office. Sensors describe the soil and the sky; plans translate those signals into prescriptions; valves and pumps execute the prescriptions; quotas keep consumption within the water rights granted by a regulator or owner; bills settle the cost; alerts surface anything that breaks the loop. This document specifies the back-end API for a multi-tenant smart-irrigation platform that sits at the centre of all of that.

The platform is operated by a `PlatformAdmin`, water-resource personnel acting as `WaterAdmin`, day-to-day field users acting as `Operator`, IoT gateways and devices identified as `DeviceAgent`, and end-customer `Tenant` users who view, dispute, and pay their own bills. The system must reconcile two quite different rhythms — the high-frequency, machine-driven traffic of sensor readings and control feedback, and the slower, human-driven cadence of plan creation, quota allocation, and bill settlement — while keeping a fully auditable record of every control command issued and every quota change made. It must continue to operate, in a degraded local-control mode, when remote dispatch is unavailable, and it must surface anomalies (offline sensors, abnormal flow, pipe-burst suspicion, valve faults) to operators with severity that reflects the recent history of the affected subject. The API exposes all of these capabilities through a single REST surface mounted under `/plots` and the related top-level resource collections described in §4.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to a non-test-driving endpoint must include both an `X-User-ID` header and an `X-User-Role` header. Either header missing or blank is rejected with `ERR_MISSING_AUTH_HEADERS` and HTTP 401. The role value must be one of `PlatformAdmin`, `WaterAdmin`, `Operator`, `DeviceAgent`, or `Tenant`; if the role is not authorised for the endpoint per the §4 endpoint table, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403. The three test-driving endpoints (`/_clock/advance`, `/_sweep/run`, `/_events/emit`) accept calls without auth headers because they are not part of the production surface; all other endpoints require both headers.

When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant` entity; ownership checks on any resource that references a `Tenant` (a `Plot`, a `WaterQuota` reached via its `plot_id`, a `WaterBill`) compare the resource's `tenant_id` to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `WaterAdmin`, `Operator`, or `DeviceAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `acknowledged_by` or `resolved_by` on `Alert`, or as `actor_id` on `AuditLog`) but does not compare it to any entity's `id`. The `WaterAdmin` role hierarchically overrides the `Operator` role: any operation an `Operator` can perform, a `WaterAdmin` may perform as well, in addition to its own exclusive operations.

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

List endpoints accept two optional query parameters: `limit` and `offset`. The default value for `limit` is 10, the minimum is 1, and the maximum is 100. The default value for `offset` is 0. List endpoints sort results by `created_at` in ascending order. The `meta` object on list responses includes `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true if more records remain beyond the current page).

### 2.4. Common Resource Properties

Most resources share four standard fields: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set at insertion time and `updated_at` is refreshed on every mutation. The `version` is a non-negative integer that begins at 1 on creation and increments by 1 on every mutation. The exceptions are `SensorReading` and `AuditLog`: both are append-only event records and carry only `id` and `created_at` — they have no `updated_at` and no `version`. The `Tenant`, `Plot`, `Sensor`, `IrrigationPlan`, `ValveGroup`, `ControlCommand`, `WaterQuota`, `Alert`, and `WaterBill` entities all carry the full four standard fields.

### 2.5. Optimistic Concurrency Control

`PATCH` endpoints accept an optional `version` field in the request body. If the request includes `version`, the server compares it to the entity's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 409. If the request omits `version`, the OCC check is skipped and the update proceeds. On any successful mutation, `version` is incremented and `updated_at` is refreshed.

### 2.6. Numeric Precision and Rounding

Liter quantities (such as `planned_volume_liters`, `requested_volume_liters`, `actual_volume_liters`, `allocated_liters`, `carry_forward_liters`, `provisional_used_liters`, `final_used_liters`, `peak_liters`, `offpeak_liters`, `approval_extra_liters`) are stored to two decimal places and rounded half-up at every step that produces a liter quantity. Money is stored as integer cents in `total_amount_cents`, `amount_paid_cents`, and the `amount_cents` field of each entry of `line_items`; rounding for tiered fees is applied half-up per individual line item before the line items are summed (see §3.6). The `severity` score for an `Alert` is computed to one decimal place using round half-up; all percentage thresholds (such as the warning threshold check) are compared as floating-point values with an epsilon of 1e-6.

### 2.7. Path Resolution and Existence Checks

Path parameters are resolved left-to-right. For a nested URL such as a plan reached via its parent plot, the outer `plot_id` is checked first; if it does not resolve, the response is `ERR_NOT_FOUND` with HTTP 404, and the inner `plan_id` is not consulted. If the outer identifier resolves but the inner identifier does not, or the inner resource exists but does not belong to the outer resource named by the URL, the same `ERR_NOT_FOUND` is returned. The same left-to-right rule governs every path-parameterised endpoint: top-level identifiers such as `tenant_id`, `sensor_id`, `command_id`, `valve_group_id`, `quota_id`, `alert_id`, and `bill_id` are first resolved on their own resource collections, and only then is any further nested identifier checked. Body-level shape and type validation happens after path validation; any missing required field or wrong-typed field is reported as `ERR_VALIDATION` with HTTP 400.

### 2.8. Hierarchical Mutation Cascade

The platform exhibits several deliberate cross-entity cascades. Whenever an operation mutates a parent record, every secondary effect documented in §3 — an `IrrigationPlan` going `ACTIVE → SUSPENDED` because its `WaterQuota` flipped to `OVER`; pending `ControlCommand` records being released to `FAILED` when their plan suspends; `Plot.last_irrigated_at` being refreshed when a `ControlCommand` reaches `EXECUTED`; `WaterQuota.provisional_used_liters` and `WaterQuota.final_used_liters` being recomputed — bumps each affected entity's `version` and refreshes its `updated_at`. Cascades are immediate: the system applies them within the same logical transaction as the triggering operation. Audit cascades also happen synchronously: the `AuditLog` records described in §3 are appended in the same transaction as the action they record.

### 2.9. Validation Priority

When a request triggers more than one validation, the rules are evaluated in the following fixed order, and the first failure short-circuits the rest. Auth-header presence is checked first (`ERR_MISSING_AUTH_HEADERS`, 401), then role authorisation (`ERR_FORBIDDEN_ROLE`, 403), then path-parameter existence (`ERR_NOT_FOUND`, 404). State-machine guards then run in the order ControlCommand transitions, IrrigationPlan transitions, WaterBill transitions — each producing `ERR_INVALID_STATE` (409). Domain safety checks follow in this order: sensor poll-interval bounds (`ERR_POLL_INTERVAL_OUT_OF_RANGE`, 422), pump-and-valve interlock (`ERR_PUMP_INTERLOCK_BUSY`, 409), valve-group/pump referential integrity (`ERR_VALVE_GROUP_PUMP_MISMATCH`, 422), plan-window overlap (`ERR_PLAN_WINDOW_OVERLAP`, 409), valve-group internal constraints (`ERR_VALVE_GROUP_INVALID`, 422), the quota guard for new control commands (`ERR_QUOTA_EXCEEDED`, 422), the override amount range (`ERR_OVERRIDE_AMOUNT_INVALID`, 422), and bill-period validity (`ERR_BILL_PERIOD_INVALID`, 422). Generic body-shape validation (`ERR_VALIDATION`, 400) and OCC (`ERR_STALE_VERSION`, 409) on `PATCH` endpoints sit at the lowest priority. The practical implication is that, for example, a quota-exceeded condition is reported in preference to a generic body-shape error, but yields to a missing-auth-header error.

### 2.10. Concurrency and Race Resolution

Five concrete races are explicitly serialised. When two operators simultaneously activate two `IrrigationPlan` records whose windows overlap on the same plot, the system serialises on the `status` flip from `DRAFT` to `ACTIVE` for that plot; only the first writer succeeds, and the loser receives `ERR_PLAN_WINDOW_OVERLAP` with HTTP 409. When two `ControlCommand` dispatches target valve groups that share the same `pump_id` and at least one group is in `SEQUENTIAL` mode, the system serialises on the `status` flip from `PENDING` to `DISPATCHING` for that pump; the loser receives `ERR_PUMP_INTERLOCK_BUSY` with HTTP 409. When a `WaterAdmin` simultaneously approves and rejects the same quota override request, the system serialises on the `approval_state` transition out of `PENDING_APPROVAL`; whichever decision lands first wins, and the loser receives `ERR_OVERRIDE_ALREADY_DECIDED` with HTTP 409. When a `Tenant` disputes a bill while a `WaterAdmin` records a payment for the same bill, the system uses optimistic concurrency on `WaterBill.version`; the loser receives `ERR_BILL_STATE_CONFLICT` with HTTP 409 and must reload. When two devices post `EXECUTED` feedback for the same `ControlCommand`, the system serialises on the `status` flip from `EXECUTING` to `EXECUTED`; only the first feedback advances state and debits the quota, and the duplicate is rejected with `ERR_FEEDBACK_ALREADY_RECORDED` and HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Plots, Sensors, and Sensor Reading Ingestion

A `Tenant` record carries the customer's display `name`, a `contact_email` used for fee notifications, and a lifecycle `status` whose default is `ACTIVE` and whose only other value is `SUSPENDED` (the `SUSPENDED` value also drives the punitive multiplier in §3.6).

A plot is registered by a `WaterAdmin` who supplies the owning `tenant_id`, a human-readable `name`, a positive `area_hectares`, the currently planted `crop_type` (one of `WHEAT`, `CORN`, `RICE`, `COTTON`, `VEGETABLE`), the current `crop_stage` (one of `SEEDLING`, `VEGETATIVE`, `FLOWERING`, `FRUITING`, `MATURE`), and the `pump_id` of the upstream pump that feeds the plot. The plot's operational `status` defaults to `ACTIVE` and may transition to `FALLOW` when the field is taken out of cultivation. The `last_irrigated_at` field is a computed timestamp that the system populates whenever a `ControlCommand` for the plot reaches `EXECUTED`; it is `null` until the first such event. Updates to a plot's `crop_stage` or `pump_id` flow through a separate edit operation by a `WaterAdmin`; if the `crop_stage` changes, every subsequent automatic plan generation uses the new stage in the water-demand model described in §3.2.

Each plot may carry one or more sensors of four kinds — `SOIL_MOISTURE`, `SOIL_TEMPERATURE`, `SOIL_EC`, and `WEATHER_STATION` — registered by a `WaterAdmin` who supplies `plot_id`, `sensor_type`, the polling cadence as `poll_interval_seconds`, and the inclusive validity bounds `min_valid_value` and `max_valid_value`. The polling cadence has a default of 300 seconds and must be at least 30 seconds and at most 3600 seconds; an attempt to set it outside that range, either at creation or via a sensor edit, is rejected with `ERR_POLL_INTERVAL_OUT_OF_RANGE` (422). A sensor's `status` defaults to `ONLINE` and may move to `OFFLINE` or `FAULTY`; an edit that flips the status from `ONLINE` to `OFFLINE` emits a `SENSOR_OFFLINE` `Alert` whose `subject_type` is `SENSOR`. The `last_reading_at` field tracks the timestamp of the most recently accepted reading.

Sensor readings are append-only events posted by either a `DeviceAgent` or a `WaterAdmin`. A reading carries a `sensor_id`, a numeric `value`, and a `reading_timestamp` in ISO 8601. The classification step assigns the reading's `validity` as follows: if the `value` lies within the inclusive interval defined by the sensor's `min_valid_value` and `max_valid_value`, the reading is `VALID`; otherwise it is `OUT_OF_RANGE`. If the same sensor produces three consecutive `OUT_OF_RANGE` readings, the third reading's `validity` is reclassified to `ABNORMAL_FILTERED` and an `ABNORMAL_FLOW` `Alert` is emitted with `subject_type` `SENSOR`. Every accepted reading refreshes the parent sensor's `last_reading_at`. Readings carry an `archived` flag (default `false`) and may eventually be reclassified to `ARCHIVED` by the periodic archival sweep described in §3.7. A list query for readings on a sensor accepts an `include_archived` flag plus the standard pagination parameters, and as readings are append-only events they expose `id` and `created_at` only — there is no `updated_at` or `version` on a reading.

### 3.2. Irrigation Plans and the Water-Demand Model

An irrigation plan is the prescription that ties a plot's water demand to a concrete time window. A plan is created by an `Operator` or a `WaterAdmin` against a target plot, with a half-open `[window_start, window_end)` interval and an optional `source` and `planned_volume_liters`. When `source` is `AUTO` (the default) and `planned_volume_liters` is not supplied, the system computes the planned volume using the **crop-stage water-demand model**. The model multiplies a stage-specific base demand per hectare by the plot's `area_hectares`, then adjusts upward by a moisture deficit factor and downward by a recent-rainfall factor. Specifically: the stage base demand in liters per hectare is 20000 for `SEEDLING`, 35000 for `VEGETATIVE`, 50000 for `FLOWERING`, 45000 for `FRUITING`, and 25000 for `MATURE`; this is multiplied by `area_hectares` to obtain the base liters. The moisture adjustment is the larger of zero and the result of subtracting the latest valid moisture reading percentage from the crop's target moisture percentage and then dividing by 100; the target moisture percentages are 60 for `WHEAT`, 65 for `CORN`, 80 for `RICE`, 55 for `COTTON`, and 70 for `VEGETABLE`. The latest valid moisture reading is the most recent `SensorReading` from a `SOIL_MOISTURE` sensor on the plot whose `validity` is `VALID`, ordered by `reading_timestamp` descending and taking the first one; if no such reading exists, the model uses 50 as the default. The weather adjustment is the larger of zero and the result of subtracting, from one, the ratio of recent rainfall in millimetres to the rainfall offset constant of 30; the recent rainfall is the most recent `VALID` `SensorReading` from a `WEATHER_STATION` sensor on the plot taken within the last 24 hours, defaulting to zero millimetres if none. The `planned_volume_liters` is then the base liters multiplied by the quantity (one plus the moisture adjustment), multiplied by the weather adjustment, with the final amount rounded half-up to two decimal places. When `source` is `MANUAL_OVERRIDE`, the formula is skipped and `planned_volume_liters` is taken verbatim from the request body; the `AuditLog` records both the original automatic value and the override.

Every plan begins in `DRAFT` with `plan_version` 1 and a null `parent_plan_id`. Activation by an `Operator` or `WaterAdmin` advances the plan from `DRAFT` to `ACTIVE` and is gated by four preconditions evaluated in this order: the parent `Plot.status` must equal `ACTIVE`; the plot must carry at least one `Sensor` whose `status` is `ONLINE`; the plan's `[window_start, window_end)` must not overlap any other `IrrigationPlan` on the same plot whose `status` is in the set of `ACTIVE` or `SUSPENDED`; and the owning `WaterQuota` covering the plan window must have `usage_state` other than `OVER`, or, if `OVER`, an `approval_state` of `APPROVED`. Failure of the first two preconditions yields `ERR_PRECONDITION_NOT_MET` (422); failure of the overlap check yields `ERR_PLAN_WINDOW_OVERLAP` (409); failure of the quota precondition yields `ERR_QUOTA_EXCEEDED` (422). On successful activation, the system reserves the plan's `planned_volume_liters` against the covering `WaterQuota.provisional_used_liters`. A plan may also be created and then never activated; cancelling a `DRAFT` plan with the delete operation moves it to `CANCELLED`.

A plan in `ACTIVE` may be suspended back to `SUSPENDED` either explicitly by an `Operator` or `WaterAdmin`, or implicitly by the system when its covering `WaterQuota` flips to `OVER` while the quota's `approval_state` is still `NOT_REQUIRED`. Suspension has two cross-entity cascades: every `ControlCommand` on the plan whose `status` is `PENDING` is moved to `FAILED` with `failure_reason` set to `'PLAN_SUSPENDED'`, and the remaining reservation is released by reducing `WaterQuota.provisional_used_liters`. Resumption from `SUSPENDED` back to `ACTIVE` requires that the covering `WaterQuota` is in `usage_state` `UNDER` or `WARNING`, or that the quota's `approval_state` is `APPROVED`; on success the reservation is re-applied to `WaterQuota.provisional_used_liters`. Failing the resumption guard yields `ERR_PRECONDITION_NOT_MET` (422); attempting to resume a plan that is not in `SUSPENDED` yields `ERR_INVALID_STATE` (409).

A `WaterAdmin` may revise a live plan through the override path. Override is a deliberate cycle from `ACTIVE` back to `DRAFT`: the original plan moves from `ACTIVE` to `DRAFT`, its quota reservation is released, a brand-new `IrrigationPlan` record is created with `parent_plan_id` set to the original plan's `id`, `plan_version` set to one greater than the original's `plan_version`, `source` set to `MANUAL_OVERRIDE`, and `status` set to `DRAFT`. The override request body may supply a new `planned_volume_liters` or new `window_start` / `window_end` values, and an `AuditLog` entry with `action_type` of `PLAN_OVERRIDDEN` is appended. The new draft revision must then be activated through the normal activation path. Finally, when the system clock advances past a plan's `window_end` and no `ControlCommand` for the plan remains in `PENDING`, `DISPATCHING`, or `EXECUTING`, the system transitions the plan from `ACTIVE` to `COMPLETED` and reconciles the reservation against the `WaterQuota.final_used_liters`.

### 3.3. Valve Groups and the Pump-and-Valve Interlock

Valves on a plot are dispatched in **valve groups**. A `WaterAdmin` configures a valve group by supplying the owning `tenant_id`, a `name`, the `pump_id` of the pump that feeds every valve in the group, the ordered `valve_ids` array, the `control_mode` (one of `SEQUENTIAL` or `PARALLEL`), and the `max_parallel_valves` cap. Three internal constraints are enforced together as `ERR_VALVE_GROUP_INVALID` (422): the `valve_ids` array must be non-empty (and may carry at most 16 entries); the `max_parallel_valves` must be at least 1; and `control_mode` of `SEQUENTIAL` forces `max_parallel_valves` to equal 1. The same constraint set applies to valve-group edits.

The pump-and-valve interlock is the central safety rule for control dispatch. When a `ControlCommand` is dispatched, the system locates the pump that feeds the target valve group via `ValveGroup.pump_id`. If any other `ControlCommand` whose target group sits on the same `pump_id` is currently in `DISPATCHING` or `EXECUTING`, the new dispatch is allowed only if every active command on that pump targets a valve group whose `control_mode` is `PARALLEL`. In every other configuration — that is, whenever at least one of the active commands on the same pump targets a `SEQUENTIAL` group — the new dispatch is rejected with `ERR_PUMP_INTERLOCK_BUSY` (409). The interlock is enforced as a first-writer-wins serialisation point on the `status` flip from `PENDING` to `DISPATCHING` for that pump.

### 3.4. Control Commands, Feedback, and the Offline-Local Branch

A control command represents a single dispatch of a measured volume of water against an active plan. An `Operator` or `WaterAdmin` creates the command by supplying `plan_id`, `valve_group_id`, and a positive `requested_volume_liters`. Two referential checks fire at creation: the chosen valve group must exist, and its `pump_id` must match the `Plot.pump_id` of the plot that owns the driving plan (reached via `IrrigationPlan.plot_id`). A mismatch is rejected with `ERR_VALVE_GROUP_PUMP_MISMATCH` (422). The quota guard then evaluates whether reserving the new command's `requested_volume_liters` against `WaterQuota.provisional_used_liters` would push the covering quota's `usage_state` to `OVER`; if it would and the quota's `approval_state` is anything other than `APPROVED`, the creation is rejected with `ERR_QUOTA_EXCEEDED` (422). A successful creation reserves the volume and stores the command in `PENDING`.

Dispatching the command moves it from `PENDING` to `DISPATCHING` and is the point at which the pump-and-valve interlock fires. An `AuditLog` record with `action_type` of `CONTROL_COMMAND_ISSUED` is appended on a successful dispatch. The dispatch endpoint is also the gateway to the offline-local branch: when a caller attaches the `X-Device-Mode: OFFLINE` header to the dispatch request, the command transitions instead from `PENDING` to `OFFLINE_LOCAL` and the `dispatch_mode` field is set to `LOCAL_DEGRADED`; this represents an on-site fallback when remote dispatch is unavailable, and the reservation persists until reconciliation occurs out-of-band. With the header absent the `dispatch_mode` is `REMOTE`.

Subsequent device feedback advances the command. Feedback is posted by a `DeviceAgent` or `WaterAdmin` with three possible `phase` values: `STARTED`, `COMPLETED`, or `ERROR`. A `STARTED` feedback advances `DISPATCHING → EXECUTING` with no other side effect. A `COMPLETED` feedback carries an `actual_volume_liters` (which must be at least zero) and advances either `EXECUTING → EXECUTED` or `OFFLINE_LOCAL → EXECUTED`; on success the system stores `actual_volume_liters` on the command, sets `feedback_received_at` to the current time, refreshes the parent `Plot.last_irrigated_at`, increases `WaterQuota.final_used_liters` by `actual_volume_liters`, and recomputes the quota's `usage_state` (which may emit an `Alert` if the new usage crosses into `OVER` while `approval_state` is `NOT_REQUIRED`). An `ERROR` feedback carries a `failure_reason` and advances either `DISPATCHING → FAILED` or `EXECUTING → FAILED`; on failure the system stores `failure_reason`, releases the reserved volume from `WaterQuota.provisional_used_liters` as a compensating release, appends an `AuditLog` with `action_type` of `CONTROL_COMMAND_FAILED`, and — when the `failure_reason` equals `'VALVE_FAULT'` — emits an `Alert` with `rule_code` of `VALVE_FAULT` and `subject_type` of `VALVE_GROUP`. Feedback for a command not in the expected state (for instance, a second `COMPLETED` feedback for a command that has already reached `EXECUTED`) is rejected with `ERR_FEEDBACK_ALREADY_RECORDED` (409); note that the same first-writer-wins guarantee applies to the `EXECUTING → EXECUTED` transition specifically, so two simultaneous `COMPLETED` feedback posts for the same command serialise to exactly one winner.

### 3.5. Water Quotas, Carry-Forward, and Over-Quota Approval

A water quota describes the volume of water a plot may consume over a half-open `[period_start, period_end)` window. A `WaterAdmin` allocates a quota by supplying `plot_id`, `period_start`, `period_end`, a non-negative `allocated_liters`, and an optional `warning_threshold_pct` whose default is 80 and which must be at least 1 and at most 100. On creation the system computes `carry_forward_liters` from the immediately prior period for the same plot using the rule: the smaller of the prior period's unused liters and twenty percent of the prior period's `allocated_liters`. If there is no prior period, `carry_forward_liters` is zero. A `QUOTA_ALLOCATED` `AuditLog` entry is appended.

The quota tracks consumption along two dimensions. The `provisional_used_liters` field is the sum of `requested_volume_liters` across every `ControlCommand` whose `plan_id` belongs to a plan on this plot, whose `created_at` falls inside `[period_start, period_end)`, and whose `status` is in `PENDING`, `DISPATCHING`, or `EXECUTING`; an `OFFLINE_LOCAL` command also counts against `provisional_used_liters` until reconciled. The `final_used_liters` field is the sum of `actual_volume_liters` across every `ControlCommand` whose `status` is `EXECUTED` and whose `feedback_received_at` falls inside the same period interval. Liter sums are computed to two decimal places with round half-up, and percentage thresholds are compared as floats with an epsilon of 1e-6. The two figures intentionally differ — provisional includes in-flight commands at the requested volume and so over-counts; final reflects only reconciled actual consumption — and the system uses each for its own purpose: provisional drives the activation and resumption guardrails, while final drives the threshold state and the alerts.

The quota carries two parallel state dimensions. The first, `usage_state`, is computed from final consumption against `effective_allocation`, where `effective_allocation` is the sum of `allocated_liters`, `carry_forward_liters`, and `approval_extra_liters`. If `final_used_liters` is at least equal to `effective_allocation` the state is `OVER`; otherwise, if the ratio of `final_used_liters` to `effective_allocation` is at least `warning_threshold_pct` divided by 100, the state is `WARNING`; otherwise the state is `UNDER`. Crossing into `WARNING` from `UNDER` emits an `ABNORMAL_FLOW` `Alert` at `WARN` severity with `subject_type` of `PLOT`. Crossing into `OVER` while the second dimension `approval_state` is `NOT_REQUIRED` triggers a cross-entity cascade in which every `IrrigationPlan` on the plot whose `status` is `ACTIVE` is moved to `SUSPENDED` (with the corresponding `PENDING` command cleanup described in §3.2). Reallocating the quota — by an admin updating `allocated_liters` or `warning_threshold_pct` — recomputes the `usage_state`; if after reallocation the ratio of `final_used_liters` to `effective_allocation` is below `warning_threshold_pct` divided by 100, the state moves from `WARNING` back to `UNDER`.

The second dimension, `approval_state`, governs the over-quota approval workflow and runs independently of `usage_state` on the same `WaterQuota` row. It begins at `NOT_REQUIRED`. An `Operator` may post an override request (supplying a free-text `reason`) when `usage_state` is `OVER` and `approval_state` is `NOT_REQUIRED`; this advances `approval_state` from `NOT_REQUIRED` to `PENDING_APPROVAL`. From `PENDING_APPROVAL` a `WaterAdmin` may either approve or reject. Approval requires the request body to specify an `extra_liters` value strictly greater than zero and at most fifty percent of `allocated_liters`; an out-of-range `extra_liters` is rejected with `ERR_OVERRIDE_AMOUNT_INVALID` (422). On approval the system sets `approval_extra_liters` to the supplied `extra_liters`, recomputes `effective_allocation` and `usage_state` (which may flip the quota from `OVER` back to `WARNING`, allowing suspended plans on the plot to be resumed by an operator), and appends a `QUOTA_OVERRIDE_APPROVED` `AuditLog` entry. Rejection accepts an optional `reason`, advances `approval_state` to `REJECTED`, and appends a `QUOTA_OVERRIDE_REJECTED` `AuditLog` entry. As stated in §2.10, simultaneous approve and reject calls serialise to exactly one winner; the loser receives `ERR_OVERRIDE_ALREADY_DECIDED` (409). An attempt to decide a request that is not in `PENDING_APPROVAL` returns `ERR_INVALID_STATE` (409).

### 3.6. Bills, Tiered Pricing, and Settlement

A `WaterAdmin` creates a draft bill for a plot and a half-open `[period_start, period_end)` interval by supplying `tenant_id`, `plot_id`, `period_start`, and `period_end`. The bill's `period_end` must be strictly greater than its `period_start`, and the `period_start` must align to a `period_start` of a `WaterQuota` for the same plot; failure of either check yields `ERR_BILL_PERIOD_INVALID` (422). The draft bill begins in `status` `DRAFT` with empty `peak_liters`, `offpeak_liters`, an empty `line_items` array, and zero `total_amount_cents` and `amount_paid_cents`.

Drafting a bill triggers the **tiered fee calculation** combined with the **bill-total settlement**. First, the system partitions consumption into peak and off-peak windows. For every `ControlCommand` whose `status` is `EXECUTED` and whose `feedback_received_at` lies within the bill's `[period_start, period_end)` interval, the command's `actual_volume_liters` is added to `peak_liters` if the hour-of-day component of `feedback_received_at` is in the set of peak hours `{6, 7, 8, 9, 18, 19, 20, 21}`, and otherwise to `offpeak_liters`. Second, for each window the system walks a tier table in order. For peak consumption the tiers are: liters from zero up to (but not including) one hundred thousand at thirty cents per liter, liters from one hundred thousand up to (but not including) two hundred fifty thousand at fifty cents per liter, and any liters beyond two hundred fifty thousand at eighty cents per liter. For off-peak consumption the tiers are: liters from zero up to (but not including) one hundred thousand at eighteen cents per liter, liters from one hundred thousand up to (but not including) two hundred fifty thousand at thirty cents per liter, and any liters beyond two hundred fifty thousand at fifty cents per liter. Within each tier, the slab attributable to that tier is the smaller of the remaining liters for the window and the difference between the tier's upper bound and the previous tier's upper bound. The tier amount for the slab is the slab quantity multiplied by the tier's per-liter rate, multiplied by a `tenant_multiplier` whose value is 1.0 when the owning `Tenant.status` is `ACTIVE` and 1.25 when it is `SUSPENDED` (a punitive multiplier applied to suspended tenants). Each tier slab is appended to `line_items` with the tier index, the window (peak or off-peak), the slab quantity, the rate, and an `amount_cents` field equal to the tier amount rounded half-up to whole cents — this **per-line rounding order is pinned**: each line item's `amount_cents` is rounded before any further arithmetic. Once both windows are processed, the raw integer subtotal is the sum of every line item's `amount_cents`.

The bill-total settlement then folds in the **carry-forward credit**. The credit in cents is computed by multiplying the carry-forward liters from the same plot's matching `WaterQuota` by the blended rate of 25 cents per liter, with the result rounded half-up to whole cents. The bill's `total_amount_cents` is the larger of zero and the integer subtotal minus the carry-forward credit in cents. The `amount_paid_cents` field is the running cumulative payment received against the bill, and the balance due is `total_amount_cents` minus `amount_paid_cents`. At issue time, `line_items`, `total_amount_cents`, and the carry-forward snapshot are frozen.

Once a `WaterAdmin` issues a draft bill, it transitions from `DRAFT` to `ISSUED`, the `line_items` are pinned, and the `total_amount_cents` is locked. A bill in `ISSUED` may receive payments from a `Tenant` or `WaterAdmin`, with each payment supplying an `amount_cents` integer; on every payment, `amount_paid_cents` is incremented by `amount_cents`, and once `amount_paid_cents` is at least `total_amount_cents`, `status` advances from `ISSUED` to `PAID`. Payments are also accepted while a bill is `DISPUTED` and may resolve the dispute by reaching the threshold. A `Tenant` may dispute an `ISSUED` bill by supplying a non-empty `dispute_reason`, which advances `status` from `ISSUED` to `DISPUTED` and stores the reason in `dispute_reason`. A `WaterAdmin` resolves the dispute by supplying an `outcome`: a `REJECT` outcome advances `status` from `DISPUTED` back to `ISSUED` (a deliberate cycle), and an `ACCEPT` outcome advances `status` from `DISPUTED` to `CANCELLED` and forces `total_amount_cents` to zero (preserving any non-zero `amount_paid_cents`, so the balance due may be negative, surfacing a refund obligation). As described in §2.10, a dispute racing a payment on the same bill is resolved by optimistic concurrency on `WaterBill.version`, with the loser receiving `ERR_BILL_STATE_CONFLICT` (409).

### 3.7. Alerts, Severity Scoring, and the Reopen Window

Alerts surface anomalies. Each `Alert` carries a `tenant_id` for routing, a `subject_type` (one of `SENSOR`, `PLOT`, or `VALVE_GROUP`), a `subject_id`, a `rule_code` (one of `SENSOR_OFFLINE`, `ABNORMAL_FLOW`, `PIPE_BURST_SUSPICION`, or `VALVE_FAULT`), a computed `severity` (one of `INFO`, `WARN`, or `CRITICAL`), and a `status` that begins at `TRIGGERED`. Alerts may be acknowledged by an `Operator` or `WaterAdmin` (advancing `status` from `TRIGGERED` or `REOPENED` to `ACKNOWLEDGED` and recording the actor as `acknowledged_by`), then resolved (advancing `status` from `ACKNOWLEDGED` to `RESOLVED` and recording `resolved_by`). Attempting to acknowledge or resolve an alert that is not in the corresponding source state yields `ERR_INVALID_STATE` (409).

The reopen mechanism is cyclic. When the same `rule_code` re-fires on the same `subject_id` within 24 hours of the alert's resolution — that is, the current time is strictly less than the alert's `updated_at` plus 24 hours — the alert moves from `RESOLVED` back to `REOPENED`, and `acknowledged_by` is reset to null so that a fresh acknowledgement is required. A reopened alert can again be acknowledged (`REOPENED → ACKNOWLEDGED`) and resolved (`ACKNOWLEDGED → RESOLVED`), forming the cycle `RESOLVED → REOPENED → ACKNOWLEDGED → RESOLVED`. The 24-hour window is enforced by the system clock and is re-evaluated when the platform admin advances the logical clock through the test-driving capability described later in this section.

The `severity` is produced by the **alert severity score**, computed to one decimal place with round half-up. The score is the sum of three weighted contributions: a rule-code weight (2 for `SENSOR_OFFLINE`, 3 for `ABNORMAL_FLOW`, 5 for `PIPE_BURST_SUSPICION`, 4 for `VALVE_FAULT`), a subject-type weight (1 for `SENSOR`, 2 for `PLOT`, 3 for `VALVE_GROUP`), and a recency contribution equal to the constant 0.5 multiplied by the count of recent abnormal sensor readings on the subject within the last 24 hours. The recency count is computed two ways and the choice depends on context. At alert-creation time, before the archival sweep runs, the count includes every `SensorReading` for the subject (or, when `subject_type` is `PLOT`, for any sensor on that plot) whose `validity` is `OUT_OF_RANGE` or `ABNORMAL_FILTERED` and whose `archived` flag is still false — this is the **provisional variant** and it tends to skew severity higher. At read time on a single alert lookup, after the archival sweep has run, the count is restricted to readings whose `archived` flag is true — this is the **reconciled variant**, in which `ABNORMAL_FILTERED` readings drop out because the archival step has removed them from the abnormal count, and the resulting severity may downgrade. The score thresholds are: a score of at least 6.0 yields `CRITICAL`; a score in the half-open range from 3.0 (inclusive) up to 6.0 (exclusive) yields `WARN`; a score strictly less than 3.0 yields `INFO`. Reads of an alert recompute `severity` using the reconciled variant.

### 3.8. Test-Driving and Event Synchronisation

Three platform-admin-only capabilities exist for testing and external synchronisation. A clock-advance capability accepts a `to_iso8601` instant and advances the logical clock to it; this re-evaluates time-gated transitions, including `ACTIVE → COMPLETED` for every plan whose `window_end` is in the past and whose commands are all in terminal states, and the 24-hour reopen window for resolved alerts. An archival sweep capability runs over `SensorReading` records older than 24 hours or with `validity` of `ABNORMAL_FILTERED`, sets their `archived` flag to true, and causes subsequent alert reads to use the reconciled variant of the severity score. An event-emit capability accepts an `event_type` and a `payload` and synchronises external systems: a `WEATHER_RAINFALL` event refreshes the cached rainfall the water-demand model consumes; a `DEVICE_OFFLINE` event flips the target sensor's `status` to `OFFLINE` and emits a `SENSOR_OFFLINE` alert; and a `PAYMENT_CONFIRMED` event is equivalent to recording a payment against the named bill. The audit-log query exposes the recorded `AuditLog` entries with optional filters `subject_type`, `action_type`, `since`, and `until` plus the standard pagination, where each `AuditLog` entry carries `actor_role`, `actor_id`, `action_type`, `subject_type`, `subject_id`, and a `payload` object that snapshots the relevant before/after fields. The `action_type` field on an audit entry is one of `CONTROL_COMMAND_ISSUED`, `CONTROL_COMMAND_FAILED`, `QUOTA_ALLOCATED`, `QUOTA_OVERRIDE_APPROVED`, `QUOTA_OVERRIDE_REJECTED`, or `PLAN_OVERRIDDEN`, and the `subject_type` field on an audit entry is one of `CONTROL_COMMAND`, `WATER_QUOTA`, or `IRRIGATION_PLAN`.

## 4. Endpoint Definitions

The API mounts under the resource-collection paths listed below. Endpoints that create a brand-new resource return HTTP 201; endpoints that modify an existing resource (including state-machine transitions, payments, and dispute actions) return HTTP 200; the cancellation of a `DRAFT` `IrrigationPlan` returns HTTP 204. Test-driving endpoints return HTTP 200 and are accessible only to `PlatformAdmin`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /tenants | Create a tenant | PlatformAdmin |
| GET | /tenants/{tenant_id} | Read a tenant | PlatformAdmin, WaterAdmin, Operator, Tenant |
| POST | /plots | Create a plot | WaterAdmin |
| GET | /plots/{plot_id} | Read a plot | PlatformAdmin, WaterAdmin, Operator, Tenant |
| PATCH | /plots/{plot_id} | Update plot crop_stage / pump_id | WaterAdmin |
| GET | /plots | List plots; supports tenant_id filter and pagination | PlatformAdmin, WaterAdmin, Operator |
| POST | /sensors | Register a sensor on a plot | WaterAdmin |
| PATCH | /sensors/{sensor_id} | Update sensor poll interval / valid range / status | WaterAdmin |
| GET | /sensors/{sensor_id} | Read a sensor | PlatformAdmin, WaterAdmin, Operator |
| POST | /sensors/{sensor_id}/readings | Ingest a sensor reading; classifies validity | DeviceAgent, WaterAdmin |
| GET | /sensors/{sensor_id}/readings | List readings; supports include_archived and pagination | PlatformAdmin, WaterAdmin, Operator |
| POST | /plots/{plot_id}/irrigation-plans | Create irrigation plan; computes planned_volume_liters | Operator, WaterAdmin |
| POST | /plots/{plot_id}/irrigation-plans/{plan_id}/activate | Activate a DRAFT plan | Operator, WaterAdmin |
| POST | /plots/{plot_id}/irrigation-plans/{plan_id}/suspend | Suspend an ACTIVE plan | Operator, WaterAdmin |
| POST | /plots/{plot_id}/irrigation-plans/{plan_id}/resume | Resume a SUSPENDED plan | Operator, WaterAdmin |
| POST | /plots/{plot_id}/irrigation-plans/{plan_id}/override | Manual override of an ACTIVE plan; creates a revision | WaterAdmin |
| DELETE | /plots/{plot_id}/irrigation-plans/{plan_id} | Cancel a DRAFT plan | Operator, WaterAdmin |
| GET | /plots/{plot_id}/irrigation-plans | List plans for a plot | PlatformAdmin, WaterAdmin, Operator |
| POST | /valve-groups | Configure a valve group | WaterAdmin |
| PATCH | /valve-groups/{valve_group_id} | Update a valve group | WaterAdmin |
| GET | /valve-groups/{valve_group_id} | Read a valve group | PlatformAdmin, WaterAdmin, Operator |
| POST | /control-commands | Create a ControlCommand for an ACTIVE plan | Operator, WaterAdmin |
| POST | /control-commands/{command_id}/dispatch | Issue dispatch (or offline-local fallback when X-Device-Mode: OFFLINE is present) | Operator, WaterAdmin |
| POST | /control-commands/{command_id}/feedback | Device feedback; advances state | DeviceAgent, WaterAdmin |
| GET | /control-commands/{command_id} | Read a control command | PlatformAdmin, WaterAdmin, Operator, DeviceAgent |
| GET | /control-commands | List commands; filterable by plan_id, status | PlatformAdmin, WaterAdmin, Operator |
| POST | /water-quotas | Allocate quota for a plot/period | WaterAdmin |
| PATCH | /water-quotas/{quota_id} | Reallocate quota | WaterAdmin |
| POST | /water-quotas/{quota_id}/request-override | Operator requests over-quota approval | Operator |
| POST | /water-quotas/{quota_id}/approve-override | Admin grants approval_extra_liters | WaterAdmin |
| POST | /water-quotas/{quota_id}/reject-override | Admin rejects override | WaterAdmin |
| GET | /water-quotas/{quota_id} | Read a quota | PlatformAdmin, WaterAdmin, Operator, Tenant |
| GET | /water-quotas | List quotas | PlatformAdmin, WaterAdmin, Operator, Tenant |
| GET | /alerts/{alert_id} | Read an alert (severity recomputed using reconciled variant) | PlatformAdmin, WaterAdmin, Operator |
| POST | /alerts/{alert_id}/acknowledge | Acknowledge an alert | Operator, WaterAdmin |
| POST | /alerts/{alert_id}/resolve | Resolve an alert | Operator, WaterAdmin |
| GET | /alerts | List alerts | PlatformAdmin, WaterAdmin, Operator |
| POST | /water-bills | Create draft bill for plot/period | WaterAdmin |
| POST | /water-bills/{bill_id}/issue | Issue bill; freezes line_items | WaterAdmin |
| POST | /water-bills/{bill_id}/payments | Record a payment | WaterAdmin, Tenant |
| POST | /water-bills/{bill_id}/dispute | Tenant disputes a bill | Tenant |
| POST | /water-bills/{bill_id}/dispute-resolve | Admin resolves dispute (REJECT or ACCEPT) | WaterAdmin |
| GET | /water-bills/{bill_id} | Read a bill | PlatformAdmin, WaterAdmin, Tenant |
| GET | /water-bills | List bills | PlatformAdmin, WaterAdmin, Tenant |
| GET | /audit-logs | List audit logs; filter by subject_type, action_type, since, until | PlatformAdmin, WaterAdmin |
| POST | /_clock/advance | Advance the system clock; triggers time-gated auto-transitions | PlatformAdmin |
| POST | /_sweep/run | Run archival sweep over old / abnormal SensorReadings | PlatformAdmin |
| POST | /_events/emit | Emit external event for synchronisation | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH_HEADERS | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 409 |
| ERR_POLL_INTERVAL_OUT_OF_RANGE | 422 |
| ERR_VALVE_GROUP_INVALID | 422 |
| ERR_VALVE_GROUP_PUMP_MISMATCH | 422 |
| ERR_PUMP_INTERLOCK_BUSY | 409 |
| ERR_PLAN_WINDOW_OVERLAP | 409 |
| ERR_QUOTA_EXCEEDED | 422 |
| ERR_OVERRIDE_AMOUNT_INVALID | 422 |
| ERR_OVERRIDE_ALREADY_DECIDED | 409 |
| ERR_FEEDBACK_ALREADY_RECORDED | 409 |
| ERR_BILL_PERIOD_INVALID | 422 |
| ERR_BILL_STATE_CONFLICT | 409 |
| ERR_PRECONDITION_NOT_MET | 422 |
