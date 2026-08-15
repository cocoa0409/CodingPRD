# Lift Station Ops API — Product Requirements Document

## 1. Introduction

Municipal wastewater utilities operate networks of sewage lift stations that move flow uphill from low-lying collection areas into gravity mains and treatment plants. Each station is a small mechanical plant — two to eight pumps, a wet well that accumulates grease, a backup generator, and SCADA telemetry — and each one is a potential sanitary sewer overflow (SSO) waiting to happen. When a station loses pumping capacity, when a generator test lapses, or when a grease cap thickens unnoticed, the consequence is not merely mechanical: raw sewage reaches streets and surface waters, and a statutory 24-hour reporting clock starts running against the utility.

This document specifies the Lift Station Ops API, a unified monitoring and maintenance platform for a wastewater utility's lift-station fleet. The system ingests SCADA alarm signals and pump runtime telemetry, dispatches on-call operators through a fairness-weighted callout rotation, schedules wet-well cleanings and backup-generator tests, enforces confined-space entry permitting with strict segregation of duties, tracks spare-pump inventory and pump rebuilds, and runs the compliance clock on SSO events from first overflow through regulator acceptance. On top of operations, the platform supports capital replacement planning: station risk scores, project ranking, budget-constrained approval, and a cooling-period lock.

The governing design idea is the **operational posture** of a station. Rather than letting operators act on child resources in isolation, every station continuously derives one of four postures — `NORMAL`, `DEGRADED`, `EMERGENCY`, or `FROZEN` — from the live state of its pumps, alarms, SSO events, permits, and generator tests. Child operations are gated by that posture: a frozen station refuses nearly all writes, an emergency station narrows the permitted workflow to SSO and alarm handling, and a degraded station raises a MAJOR alarm on its own. Posture is not a convenience flag; it is the system's primary safety interlock, and every workflow described in §3 is written against it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. If `X-User-Role` is missing, malformed, or does not name one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If `X-User-ID` is missing or is an empty string, the request is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present but the declared role is not permitted to invoke the endpoint (per the authorization column of §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These authentication checks run before any existence, state, or business validation.

The platform recognizes nine roles, spelled exactly as follows: `UtilityAdmin`, `OperationsSupervisor`, `OnCallOperator`, `Operator`, `MaintenancePlanner`, `ComplianceOfficer`, `CapitalProgramManager`, `ScadaWebhook`, and `RegulatorPortal`.

Identity semantics differ by role. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` entity; ownership checks on any resource that references an `Operator` (for example, an alarm ticket's `assigned_operator_id` or a permit's `entry_supervisor_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is any of `UtilityAdmin`, `OperationsSupervisor`, `OnCallOperator`, `MaintenancePlanner`, `ComplianceOfficer`, `CapitalProgramManager`, `ScadaWebhook`, or `RegulatorPortal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. This distinction is load-bearing in §3: actions such as arriving on-scene at a dispatched alarm, closing a confined-space permit, or issuing a permit as its named supervisor are only legal when the caller's `X-User-ID` equals the `Operator` `id` recorded on the resource.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be non-negative. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reports the full size of the filtered result set and `has_more` indicates whether additional pages exist beyond the returned window. Unless a subsection states otherwise, every list endpoint returns its results sorted by `created_at` ascending (oldest first).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, plus a `version` integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations caused by cascading side effects from another resource's lifecycle event. The exception is the runtime-reading feed: because readings are an append-only telemetry stream, a runtime reading carries only `id` and `created_at`; `updated_at` and `version` are absent from that resource entirely and must not appear in its serialized form.

### 2.5. Numeric Precision and Monetary Conventions

Numeric fields fall into three precision classes, and the class is fixed per field. Monetary amounts — a rebuild's `cost_usd`, a plan's `budget_total_usd`, `budget_allocated_usd`, and `budget_remaining_usd`, and a project's `estimated_cost_usd` — are carried at exactly two decimal places with round-half-up applied at assignment. The composite `risk_score` on a capital project is likewise two decimal places, round-half-up. Runtime deltas (`run_hours_delta`) are numbers with two-decimal precision, round-half-up, bounded to the range from 0 to 24 inclusive. Grease depths (`grease_depth_inches_pre`, `grease_depth_inches_post`) are non-negative numbers recorded to one decimal place. The derived grease accumulation rate is rounded half-up to three decimal places. Volumes (`estimated_volume_gal`) are whole gallons with round-half-up to zero decimal places. Firm capacity figures (`design_capacity_gpm`, `rated_gpm`, `firm_capacity_available_gpm`) and all counters (`pump_count`, `starts_count`, `rebuild_count`, `active_ticket_count`, `consecutive_callouts_24h`, `duration_minutes`, `response_minutes`, `priority_rank`) are integers with no rounding. Wherever a calculation below specifies a comparison between hours, the comparison is performed at two-decimal precision.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its guard field explicitly:

- Recording a new SSO event against a station requires the request to carry `expected_station_version`, set to the value of the station's `version` the client last observed. If the station's current `version` does not match, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just opened an SSO event or otherwise mutated station state and the current writer's view is therefore stale.
- Dispatching an alarm ticket requires the request to carry `expected_ticket_version`, the ticket `version` last observed by the on-call operator. A mismatch with the ticket's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), guarding against double-dispatch when the ticket was already dispatched by another on-call operator.
- Approving a capital plan requires the request to carry `expected_plan_version`, the plan `version` last observed by the approver. A mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing two planners stepping a plan through its lifecycle from approving on a stale read.

No other endpoint accepts or requires a version field. Clients obtain current versions by reading the resource; every mutation — user-driven or cascading — increments the owning resource's `version` and refreshes its `updated_at`.

### 2.7. Operational Posture as the Master Interlock

Each lift station continuously derives an `operational_posture` of `NORMAL`, `DEGRADED`, `EMERGENCY`, or `FROZEN`. `FROZEN` is sticky and privileged: it is entered only through an explicit freeze action by a `UtilityAdmin` and exited only through an explicit unfreeze; no automatic recomputation moves a station into or out of `FROZEN`. When the station is not frozen, posture is recomputed on every state change of any child pump, alarm ticket, SSO event, confined-space permit, or generator test attached to the station. The derivation is ordered: if any SSO event for the station is in `OPEN`, `CONTAINED`, `REPORT_DRAFT`, or `REPORT_SUBMITTED`, the posture is `EMERGENCY`. Otherwise, if the station's available firm capacity has fallen below its design capacity, or any pump at the station is in `REBUILD`, or any generator test for the station is in `SCHEDULED`, `RUNNING`, or `FAILED` with its `scheduled_for` already in the past, the posture is `DEGRADED`. Otherwise the posture is `NORMAL`.

Posture gates child writes. Any mutation targeting a station's child resources — any action beneath a station in the URL hierarchy, and any child mutation that names a `station_id` — is rejected with `ERR_STATION_FROZEN` (HTTP 409) while the station's `operational_posture` is `FROZEN`. While the posture is `EMERGENCY`, non-critical child mutations are rejected with `ERR_STATION_EMERGENCY` (HTTP 409); only the SSO lifecycle actions and alarm-ticket actions remain permitted in that posture. The specific action-level preconditions in §3 restate these gates where they bind.

### 2.8. Nested Resources and Validation Order

Where a URL is path-templated — for example a sub-resource beneath a station or pump — path identifiers are resolved left to right, and the first identifier that does not resolve to an existing row produces `ERR_NOT_FOUND` (HTTP 404). A body-provided foreign key such as `station_id`, `pump_id`, `plan_id`, `authorized_entrant_id`, `attendant_operator_id`, `entry_supervisor_id`, or `crew_lead_operator_id` that references a non-existent row is a different failure and produces `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

When several validation rules could reject the same request, the server evaluates them in a fixed order and surfaces only the first failure: authentication and role authorization first (`ERR_UNAUTHENTICATED` before `ERR_UNAUTHORIZED`); then path-existence (`ERR_NOT_FOUND`); then body foreign-key existence (`ERR_REFERENCE_NOT_FOUND`); then the target entity's lifecycle state (`ERR_INVALID_STATE`); then posture gating (`ERR_STATION_FROZEN` / `ERR_STATION_EMERGENCY`); then the business-safety rules in their declared sequence — firm-capacity preservation, segregation of duties, certification, gas test; then business constraints such as uniqueness and zone compatibility; then temporal rules (reading order, test duration, grease depth, report deadline); then referential rules (open SSO, permit required, permit expired, budget); then fiscal rules (settlement period, plan lock); then dispatch eligibility; and finally generic shape validation (`ERR_INVALID_REQUEST`) for required-field presence, enum membership, and simple numeric ranges. Because shape validation is last in the declared ordering, a request that fails both a business rule and a shape rule surfaces the business rule's error.

### 2.9. Logical Clock and Scheduled Transitions

The server maintains a logical clock used for every time comparison in this document: overdue derivation, permit expiry, deadline enforcement, callout-window decay, and risk-score recency. Before any explicit clock-set call, the logical clock defaults to 2026-08-01T00:00:00Z and must never fall back to wall-clock time. A `UtilityAdmin` may set the clock to a supplied `to_iso8601` instant — the response echoes the new logical time as `current_utc` — and may invoke a tick capability that re-evaluates all time-driven automatic transitions described in §3, returning a `transitioned_counts` object summarizing what moved: scheduled cleanings and generator tests that have slipped more than 24 hours past their planned start become `OVERDUE`, and station postures are recomputed against the new "now". Every reference to "now" in the rules below means this logical clock.

Where a compound aggregate check fails in a way not covered by a more specific identifier — for example a plan-level budget or station-level capacity inconsistency detected outside the specific gates named in §3 — the server surfaces `ERR_VALIDATION_AGGREGATE` (HTTP 422) rather than a generic shape error.

### 2.10. Auto-Fired Alarms

Several lifecycle events raise alarm tickets automatically, without a client call to the alarm-creation endpoint: a station sliding into `DEGRADED` fires a `MAJOR` ticket with `alarm_code` `STATION_DEGRADED`; a pump marked out of service fires a `MAJOR` ticket with `alarm_code` `PUMP_OUT_OF_SERVICE`; a failed generator test fires a `MAJOR` ticket with `alarm_code` `GEN_TEST_FAILED`; a cleaning that becomes overdue fires a `MINOR` ticket with `alarm_code` `CLEANING_OVERDUE`. Auto-fired tickets enter the same `OPEN` state and follow the same acknowledge-dispatch-clear lifecycle as operator- or SCADA-raised tickets, and they participate in posture recomputation like any other child row.

## 3. Business Logic & Workflows

### 3.1. Registering the Fleet: Stations, Operators, and Spare Pumps

A `UtilityAdmin` onboards a station by supplying its regulatory `station_code`, the owning `service_zone`, the rated `design_capacity_gpm`, the number of installed `pump_count` slots, whether it `has_backup_generator`, and the physical `wet_well_volume_gal`. The `station_code` must be unique across all stations and must match the pattern of the letters "LS-" followed by exactly four digits; a collision or a malformed code is rejected with `ERR_DUPLICATE_STATION_CODE` (HTTP 422). The `design_capacity_gpm` must be a positive integer no smaller than 50, `pump_count` must be an integer between 2 and 8 inclusive, and `wet_well_volume_gal` must be a positive integer — shape violations of these kinds surface as `ERR_INVALID_REQUEST` (HTTP 400). A newly created station begins life in posture `NORMAL`, with `firm_capacity_available_gpm` computed from its pumps and `last_sso_occurred_at` null until an overflow occurs.

The operator roster is likewise maintained by `UtilityAdmin`. Each operator record carries a unique `employee_code` of the form "OP-" followed by four digits (violations are `ERR_DUPLICATE_EMPLOYEE_CODE`, HTTP 422), a `full_name`, an array of `certifications` whose values are drawn from `CSE_1`, `CSE_2`, `ELEC_1`, `GEN_OP`, and `COLLECTIONS_2`, and a `home_zone` used by the callout rotation. Operators are created active; setting `is_active` to false excludes the operator from callout and assignment entirely. Two counters track workload fairness: `active_ticket_count`, the number of tickets currently assigned to the operator in `DISPATCHED` or `ON_SCENE` status, and `consecutive_callouts_24h`, the count of dispatch events in which the operator was selected within the trailing 24 hours as measured from each event's creation.

The spare-pump pool is registered by `UtilityAdmin` or a `MaintenancePlanner`. Each spare carries a unique `asset_tag` of the form "SP-" followed by four digits (violations are `ERR_DUPLICATE_ASSET_TAG`, HTTP 422), a `rated_gpm` capacity, and a `compatible_zone` naming the service zone into which the spare is certified to deploy — deployment legality is judged against the target station's `service_zone`. A new spare starts `AVAILABLE`, with `reserved_for_station_id` and `deployed_at_station_id` empty.

### 3.2. Pumps, Runtime Telemetry, and the N-1 Capacity Rule

Pumps are registered against a station by a `MaintenancePlanner` or `UtilityAdmin`, naming the `station_id`, a 1-based physical `position_index`, and a nameplate `rated_gpm`; an optional `status` may be supplied but defaults to `IN_SERVICE`. The `position_index` must lie between 1 and the station's `pump_count` and must be unique within the station — a duplicate or out-of-range slot is rejected with `ERR_DUPLICATE_POSITION` (HTTP 422). Each pump tracks `cumulative_runtime_hours` (lifetime run time), `runtime_since_rebuild_hours` (run time since the most recent completed rebuild), `last_alternation_at` (when it last became lead), and `rebuild_count` (completed rebuilds, starting at 0).

A station's firm capacity follows the N-1 criterion: `firm_capacity_available_gpm` is the sum of `rated_gpm` across the station's pumps whose status is `IN_SERVICE`, minus the largest single `rated_gpm` among those pumps. If no pump is `IN_SERVICE`, firm capacity is zero. Pumps in `STANDBY`, `OUT_OF_SERVICE`, or `REBUILD` contribute nothing. This figure is recomputed on every pump status mutation, pump creation, and nameplate edit, and each recomputation in turn triggers a station-posture recompute — the compare of available firm capacity against `design_capacity_gpm` is one of the three drivers into `DEGRADED`.

Runtime telemetry arrives through the reading-ingestion capability, usable by an `Operator`, the `ScadaWebhook` service account, or a `UtilityAdmin`. Each reading names the pump implicitly through the URL and supplies `recorded_at`, a `run_hours_delta` between 0 and 24 hours at two-decimal precision, a non-negative integer `starts_count`, and a `source` of `SCADA`, `MANUAL`, or `BACKFILL`. Readings for a pump must be chronological: a `recorded_at` earlier than the prior reading's `recorded_at` for the same pump is rejected with `ERR_READING_OUT_OF_ORDER` (HTTP 422). Each accepted reading adds its `run_hours_delta` to both `cumulative_runtime_hours` and `runtime_since_rebuild_hours`; the latter resets to 0 only when a pump returns from rebuild. Readings can be listed with optional `since` and `until` bounds plus standard pagination.

### 3.3. Alarm Handling and the Callout Rotation

An alarm ticket is born when SCADA or a human raises one against a station, supplying `alarm_class` (`CRITICAL`, `MAJOR`, `MINOR`, or `INFO`), the SCADA-originated `alarm_code` (such as `HI_LEVEL`, `P1_FAIL`, `GEN_FAIL`, or `COMM_LOSS`), the `raised_at` instant, and an optional `is_sso_related` flag that defaults to false. The `ScadaWebhook`, an `OnCallOperator`, or a `UtilityAdmin` may raise a ticket. Creating a ticket bumps the parent station's `version`. A new ticket sits in `OPEN`.

The response workflow runs `OPEN → ACKED → DISPATCHED → ON_SCENE → CLEARED`, with cancellation shortcuts. Acknowledgement by an `OnCallOperator` moves an `OPEN` ticket to `ACKED` and stamps `acked_at`; it is refused at a frozen station. An `OnCallOperator` may cancel an `OPEN` ticket directly, but only when its `alarm_class` is not `CRITICAL` — critical alarms may never be cancelled.

Dispatch is the heart of the workflow and is OCC-guarded as described in §2.6: the request must carry `expected_ticket_version`. The server then selects the responding operator through the callout-selection rule. The eligible pool is every `Operator` with `is_active` true and an `active_ticket_count` below 3; if the ticket's `alarm_class` is `CRITICAL`, the pool is further restricted to operators holding the `COLLECTIONS_2` certification. If the pool is empty — or, for a `CRITICAL` ticket, no active under-capacity operator holds `COLLECTIONS_2` — the dispatch is rejected with `ERR_NO_ELIGIBLE_OPERATOR` (HTTP 422). Each eligible operator receives a `callout_score`: 100 points if the operator's `home_zone` equals the station's `service_zone` (0 otherwise), minus 50 points per currently active ticket, minus 10 points per consecutive callout in the trailing 24 hours. The winner is the highest score, with ties broken by the operator's earlier `created_at`. Dispatch stamps `dispatched_at`, records the winner in `assigned_operator_id`, moves the ticket to `DISPATCHED`, and increments the winner's `active_ticket_count` and `consecutive_callouts_24h`. Dispatch is refused at a frozen station.

From there the assigned field operator drives: arriving on scene (an `Operator` whose `X-User-ID` equals the ticket's `assigned_operator_id`) moves `DISPATCHED → ON_SCENE`; clearing moves `ON_SCENE → CLEARED`, stamps `cleared_at`, computes `response_minutes` as the whole minutes between `raised_at` and `dispatched_at`, and decrements the operator's `active_ticket_count`. Clearing an SSO-flagged ticket carries an extra condition: if `is_sso_related` is true, the station must have an SSO event in `CONTAINED`, `REPORT_DRAFT`, `REPORT_SUBMITTED`, `REPORT_ACCEPTED`, or `CLOSED` — attempting to clear while the station's SSO event is still `OPEN` is rejected with `ERR_SSO_EVENT_OPEN` (HTTP 422). An `OperationsSupervisor` may cancel an `ON_SCENE` ticket when its `alarm_class` is not `CRITICAL`; cancellation clears `assigned_operator_id` and decrements the operator's `active_ticket_count`. `CLEARED` and `CANCELLED` are terminal.

### 3.4. Pump Rebuilds and the Spare-Pump Pool

When a pump needs shop work, a `MaintenancePlanner` opens a rebuild by supplying the `pump_id`, an external CMMS `work_order_ref`, the `started_at` timestamp at which the pump was taken out of service, and the invoiced `cost_usd` (a non-negative two-decimal amount that later feeds capital scoring). Opening the rebuild drives the pump `IN_SERVICE → REBUILD`; it is refused at a frozen station, and it is refused with `ERR_FIRM_CAPACITY_VIOLATION` (HTTP 422) when it would leave the station without at least one remaining `IN_SERVICE` pump. The same firm-capacity rule guards an `OperationsSupervisor` marking a pump out of service (`IN_SERVICE → OUT_OF_SERVICE`, which also auto-fires the `PUMP_OUT_OF_SERVICE` `MAJOR` alarm). Moving a pump between `IN_SERVICE` and `STANDBY`, and returning a pump from `OUT_OF_SERVICE` to service, are `OperationsSupervisor` actions refused only at a frozen station. Every pump status change recomputes the station's firm capacity and posture; when activation makes a pump the lead — the lowest `position_index` among `IN_SERVICE` pumps — its `last_alternation_at` is stamped.

The rebuild itself runs `OPEN → IN_PROGRESS → COMPLETED`. Starting work requires the pump to actually be in `REBUILD` and snapshots the pump's current `runtime_since_rebuild_hours` into the rebuild's `pre_rebuild_runtime_hours`. Completion — again requiring the pump in `REBUILD` — stamps the rebuild's `completed_at`, flips the pump `REBUILD → IN_SERVICE`, resets the pump's `runtime_since_rebuild_hours` to 0, and increments its `rebuild_count`. Cancellation is possible from `OPEN` (by a `MaintenancePlanner`) or `IN_PROGRESS` (by an `OperationsSupervisor`); either way the pump slides `REBUILD → OUT_OF_SERVICE` rather than returning to duty. `COMPLETED` and `CANCELLED` are terminal.

The spare-pump pool cycles `AVAILABLE → RESERVED → DEPLOYED → AVAILABLE`, with side paths to `REBUILD` and terminal `RETIRED`. A `MaintenancePlanner` reserves an `AVAILABLE` spare for a station by supplying the target `station_id`; the spare's `compatible_zone` must equal the station's `service_zone`, or the reservation is rejected with `ERR_ZONE_MISMATCH` (HTTP 422). Reservation records `reserved_for_station_id`. Deployment moves `RESERVED → DEPLOYED`, copying the reserving station into `deployed_at_station_id` and clearing the reservation. Returning a spare — from either `DEPLOYED` or `REBUILD` — restores `AVAILABLE` and clears `deployed_at_station_id`; releasing a `RESERVED` spare restores `AVAILABLE` and clears `reserved_for_station_id`. A `MaintenancePlanner` may also send an `AVAILABLE` spare to `REBUILD`, and a `UtilityAdmin` may retire an `AVAILABLE` spare permanently.

### 3.5. Pump Alternation

Pumps at a station are physically ordered by `position_index`, and the lowest-indexed `IN_SERVICE` pump is the lead — the one that runs first and wears fastest. To equalize wear, an `OperationsSupervisor` or `UtilityAdmin` may invoke alternation at a station, naming the `station_id`. The rule considers only the station's `IN_SERVICE` pumps; if fewer than two are in service, no alternation is possible and the request is rejected with `ERR_NO_PUMPS_TO_ALTERNATE` (HTTP 422). Otherwise the server identifies the current lead (lowest `position_index` among `IN_SERVICE` pumps) and the candidate successor: among the other `IN_SERVICE` pumps, the one with the lowest `runtime_since_rebuild_hours`, ties broken by earlier `created_at`. The swap executes only when the candidate's `runtime_since_rebuild_hours` is greater than or equal to the current lead's `runtime_since_rebuild_hours` plus the 24.0-hour alternation threshold, with hour comparisons carried at two-decimal precision. When the threshold is met the two pumps exchange `position_index` values, the new lead's `last_alternation_at` is stamped with the current time, and the alternated pump is returned; when it is not, nothing changes.

### 3.6. Wet-Well Cleaning and Grease Management

Wet-well cleanings are scheduled against a station by a `MaintenancePlanner` or `OperationsSupervisor`, supplying the planned `scheduled_for` start, the measured `grease_depth_inches_pre` cap depth, the `crew_lead_operator_id` of the operator leading the crew, and a `requires_confined_space_entry` flag. A new cleaning sits in `SCHEDULED`.

Time pressure is built in: if the logical clock passes `scheduled_for` by more than 24 hours while the cleaning is still `SCHEDULED`, the system flips it to `OVERDUE` on the next tick and auto-fires a `MINOR` alarm with `alarm_code` `CLEANING_OVERDUE`.

An `Operator` starts the work, moving `SCHEDULED → IN_PROGRESS` or `OVERDUE → IN_PROGRESS`. Two preconditions bind: the station must not be `FROZEN`, and if `requires_confined_space_entry` is true there must exist a confined-space permit for the station in `ISSUED` or `ACTIVE` status — without one, the start is rejected with `ERR_PERMIT_REQUIRED` (HTTP 422). Completion moves `IN_PROGRESS → COMPLETED` (or `OVERDUE → COMPLETED` when work finished without an intervening start), requires the request to supply `grease_depth_inches_post`, and demands that the post-cleaning depth be strictly less than `grease_depth_inches_pre`; a post depth greater than or equal to the pre depth is rejected with `ERR_GREASE_DEPTH_INVALID` (HTTP 422). Completion stamps `completed_at` and records the post depth. An `OperationsSupervisor` may cancel a cleaning from `SCHEDULED` or `OVERDUE`. `COMPLETED` and `CANCELLED` are terminal.

Each completion also feeds the station's grease intelligence. The historical accumulation rate is computed from the station's completed cleanings ordered by `completed_at`: with fewer than two completed cleanings the rate is undefined; otherwise it is the sum of `grease_depth_inches_pre` across all completed cleanings after the first (the first serves as the baseline) divided by the calendar days between the first and last completed `completed_at`, rounded half-up to three decimal places — and undefined when that day-span is zero. From the rate, the platform projects the next due date: using the calendar-day variant, when the rate is defined and positive, the projection takes the most recent completion time, adds the number of days required for the grease cap to grow from the latest recorded post-cleaning depth to the 6.0-inch action threshold at the computed rate, and reports the result to the minute. When the rate is undefined or non-positive, no projection is produced. Both figures surface on the station summary read (§3.11).

### 3.7. Backup Generator Testing

Generator tests are scheduled against a station by a `MaintenancePlanner` or `OperationsSupervisor` with a planned `scheduled_for`, a `test_kind` of `NO_LOAD`, `LOAD_BANK`, or `TRANSFER_SWITCH`, the `load_percent` applied during the run (a number from 0 to 100), and optional `outcome_notes`. New tests are `SCHEDULED`.

Starting a test is an `Operator` action that moves `SCHEDULED → RUNNING` (or `OVERDUE → RUNNING` for a late start) and stamps `started_at`. Start is refused at stations whose posture is `FROZEN` or `EMERGENCY`, and refused outright when the station's `has_backup_generator` is false. Like cleanings, a test still `SCHEDULED` more than 24 hours past its `scheduled_for` flips to `OVERDUE` on the next tick and triggers a station-posture recompute — an overdue (or running, or failed) test whose planned time has passed is one of the three drivers into `DEGRADED`.

Finishing a running test records a pass: the operator supplies `duration_minutes`, and the run must have lasted at least 30 minutes when `test_kind` is `LOAD_BANK`, or at least 15 minutes for the other kinds; a shorter duration is rejected with `ERR_TEST_DURATION_TOO_SHORT` (HTTP 422). A passing finish moves `RUNNING → PASSED` and stores the duration. Alternatively the operator may record a failure (`RUNNING → FAILED`), which auto-fires a `MAJOR` alarm with `alarm_code` `GEN_TEST_FAILED` and recomputes station posture, or abort the run (`RUNNING → ABORTED`) with no further effect. An `OperationsSupervisor` may cancel a test from `SCHEDULED` or `OVERDUE`. `PASSED`, `FAILED`, `ABORTED`, and `CANCELLED` are terminal.

### 3.8. Sanitary Sewer Overflow Events and the Regulatory Clock

An SSO event is recorded against a station by the `ScadaWebhook`, an `Operator`, or a `UtilityAdmin`, supplying the `started_at` instant the overflow began, a `cause_code` of `GREASE_BLOCKAGE`, `DEBRIS`, `POWER_FAILURE`, `PUMP_FAILURE`, `INFLOW_INFILTRATION`, `VANDALISM`, or `UNKNOWN`, and a `reached_surface_water` flag. Creation is OCC-guarded as described in §2.6: the request must carry `expected_station_version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

Recording an SSO is the most consequential write in the system. The new event enters `OPEN`; the station's posture cascades to `EMERGENCY`; the station's `last_sso_occurred_at` is set to the event's `started_at`; the station's `version` increments; every `SCHEDULED` generator test at the station is automatically moved to `ABORTED`; and every `DRAFT` confined-space permit at the station is automatically moved to `CANCELLED`. At creation the statutory reporting deadline is fixed on the event as `regulator_deadline_at`: normally 24 hours after `started_at`, but tightened to 12 hours after `started_at` when `reached_surface_water` is true — the stricter tier for overflows that reach a water body.

Containment is an `Operator` action allowed only while the station's posture is `EMERGENCY`, moving the event `OPEN → CONTAINED`, stamping `stopped_at`, and computing the provisional `estimated_volume_gal`. The volume rule measures the overflow duration in whole minutes — the difference between `stopped_at` and `started_at`, floored to integer minutes — and multiplies it by the station's `firm_capacity_available_gpm` as computed at `stopped_at`. When `reached_surface_water` is true, that base volume is then multiplied by the 1.20 regulatory penalty multiplier for water-body reach. The result is rounded half-up to whole gallons.

The reporting pipeline is owned by the `ComplianceOfficer` and the regulator. Drafting moves `CONTAINED → REPORT_DRAFT`. Submission moves `REPORT_DRAFT → REPORT_SUBMITTED` and stamps `report_submitted_at`; submission must occur on or before `regulator_deadline_at`, and a late submission is accepted only when the request carries an `override_note` explaining the escalation — otherwise it is rejected with `ERR_REPORT_DEADLINE_MISSED` (HTTP 422). Submission also recomputes the volume estimate in its final variant: the same duration-times-capacity rule is re-evaluated using the capacity snapshot in effect at submission time, and the new value overwrites the provisional `estimated_volume_gal`. The two variants can legitimately differ, because station capacity may have changed between containment and submission.

The `RegulatorPortal` integration then dispositions the report: acceptance moves `REPORT_SUBMITTED → REPORT_ACCEPTED` and stamps `report_accepted_at`, recomputing the station's `last_sso_occurred_at`; rejection returns the event `REPORT_SUBMITTED → REPORT_DRAFT` for rework and resubmission. Finally, a `ComplianceOfficer` closes an accepted event (`REPORT_ACCEPTED → CLOSED`), which recomputes both the station's `last_sso_occurred_at` and its posture. Every recomputation of `last_sso_occurred_at` — at creation, at acceptance, at closure, and at any other station-state change — re-derives the field as the maximum `started_at` across all SSO events ever recorded at the station, whatever their status; the field is a persistent historical timestamp and never reverts to null once any SSO event exists at the station. Note the posture interplay: an event remains posture-forcing through `OPEN`, `CONTAINED`, `REPORT_DRAFT`, and `REPORT_SUBMITTED`; only acceptance or closure releases the station from `EMERGENCY` (into `DEGRADED` if capacity or rebuild or overdue-test drivers remain, else `NORMAL`). `REPORT_ACCEPTED` and `CLOSED` are terminal for the event.

### 3.9. Confined-Space Entry Permits

Entering a wet well is a permitted activity. A permit is drafted against a station by an `Operator` or `OperationsSupervisor`, supplying a `work_description`, the `authorized_entrant_id` of the operator who will enter, the `attendant_operator_id` of the attendant stationed outside, the `entry_supervisor_id` of the supervisor authorizing entry, and a `gas_test_passed` flag that defaults to false. New permits are `DRAFT`.

Segregation of duties is enforced hard: the entrant, attendant, and supervisor must be three distinct operators. Any collision — supervisor equal to entrant, supervisor equal to attendant, or entrant equal to attendant — is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 422), both when the permit is created and when it is issued. Certification is checked at both moments as well: the named entrant and the named attendant must each hold `CSE_1` or `CSE_2` among their `certifications`, or the request is rejected with `ERR_INSUFFICIENT_CERTIFICATION` (HTTP 422).

Issuance (`DRAFT → ISSUED`) is performed by an `Operator` whose `X-User-ID` equals the permit's `entry_supervisor_id` — only the named supervisor may issue. Beyond segregation and certification, issuance requires `gas_test_passed` to be true (a false flag is rejected with `ERR_GAS_TEST_REQUIRED`, HTTP 422) and requires the station's posture to be neither `FROZEN` nor `EMERGENCY`. Issuance stamps `issued_at` and fixes `valid_until` at 12 hours after issuance.

Once issued, the permit may be activated (`ISSUED → ACTIVE`, and likewise `SUSPENDED → ACTIVE`) — but only while the current time is still before `valid_until`; activating at or after expiry is rejected with `ERR_PERMIT_EXPIRED` (HTTP 422). An `ACTIVE` permit may be suspended and re-activated within its validity window. Closing (`ACTIVE → CLOSED`) is again restricted to the named supervisor and stamps `closed_at`. An `OperationsSupervisor` may cancel a permit from `DRAFT` or `ISSUED`, and recall that a station sliding into `EMERGENCY` automatically cancels that station's `DRAFT` permits. `CLOSED` and `CANCELLED` are terminal.

### 3.10. Capital Planning: Risk Scores, Ranking, and Budget-Gated Approval

A `CapitalProgramManager` opens a capital plan for a four-digit `plan_year` (unique across plans, between 2024 and 2100; duplicates are rejected with `ERR_DUPLICATE_PLAN_YEAR`, HTTP 422) with an authorized `budget_total_usd`. New plans are `DRAFT`. The plan tracks `budget_allocated_usd` — the sum of `estimated_cost_usd` across its projects in `PROPOSED`, `RANKED`, or `APPROVED` — and `budget_remaining_usd`, the difference between total and allocated, floored at 0.00 for reporting purposes while the raw difference drives gating.

Projects are created under a plan by the `CapitalProgramManager`, naming the `plan_id`, the `station_id` whose asset is being replaced or upgraded, a `project_name`, an `estimated_cost_usd` (a positive two-decimal amount), and two SME scores: `consequence_of_failure` and `likelihood_of_failure`, each an integer from 1 to 10. New projects are `PROPOSED`.

Every project carries a computed `risk_score` between 0.00 and 100.00, recomputed on project creation, on field mutation, and whenever the parent plan is ranked. The score starts from the product of `consequence_of_failure` and `likelihood_of_failure`. A recency bonus of 15 points is added when the referenced station's `last_sso_occurred_at` is set and falls less than 365 days before the current time. A resilience bonus of 10 points is added when the station has no backup generator. An age component is added equal to the station's age in whole years — the elapsed days between the station's `created_at` and now, divided by 365.25 and floored — capped at 25 points. The sum is capped at 100.00 and rounded half-up to two decimal places.

Ranking is a plan-level action by the `CapitalProgramManager`, moving `DRAFT → RANKED` and requiring at least one `PROPOSED` project in the plan. Ranking orders every `PROPOSED` project by `risk_score` descending, with deterministic tie-breaks of lower `estimated_cost_usd` first, then earlier `created_at`, then `id`; assigns `priority_rank` values 1, 2, 3, ... in that order; recomputes each project's `risk_score`; and cascades each ranked project `PROPOSED → RANKED`. Ranking increments the plan's `version`. Unranking reverts the plan `RANKED → DRAFT` and cascades every `RANKED` project back to `PROPOSED`, clearing its `priority_rank`.

Approval is the budget gate, performed by a `UtilityAdmin` and OCC-guarded per §2.6 via `expected_plan_version`. Approval is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422) when the plan's `budget_allocated_usd` exceeds its `budget_total_usd`. On approval the plan stamps `approved_at`, increments its `version`, and walks its `RANKED` projects in ascending `priority_rank`: the longest prefix of projects whose cumulative `estimated_cost_usd` stays within `budget_total_usd` transitions `RANKED → APPROVED`, and every remaining `RANKED` project transitions `RANKED → DEFERRED` — each project individually approved when the running total including its own cost remains within budget, and deferred otherwise. Approval recomputes `budget_allocated_usd`.

Locking is the final plan transition (`APPROVED → LOCKED`), performed by a `UtilityAdmin` no sooner than 7 days after `approved_at`; an earlier attempt is rejected with `ERR_PLAN_NOT_SETTLED` (HTTP 422). `LOCKED` is terminal for the plan and seals its projects: rejecting or cancelling a project while its plan is `LOCKED` is rejected with `ERR_PLAN_LOCKED` (HTTP 409).

Individual projects have their own side exits. While `PROPOSED`, the `CapitalProgramManager` may reject (`PROPOSED → REJECTED`) or cancel (`PROPOSED → CANCELLED`) the project; both actions recompute the parent plan's `budget_allocated_usd`. A `DEFERRED` project may be resubmitted (`DEFERRED → PROPOSED`), but only while its plan is back in `DRAFT`. `APPROVED`, `REJECTED`, and `CANCELLED` are terminal project states.

### 3.11. Station Summary Read

For dispatch and planning consoles, the platform exposes a computed per-station summary returning the station's `station_id`, its current `operational_posture`, the live `firm_capacity_available_gpm`, the count of open alarm tickets as `open_alarm_count`, the count of overdue cleanings as `overdue_cleaning_count`, the count of overdue generator tests as `overdue_generator_test_count`, the current `grease_accumulation_rate_inches_per_day`, the projected `next_cleaning_due_at`, and the station's `last_sso_occurred_at`. All figures are derived at read time from the rules in §3.2, §3.6, and §3.8.

### 3.12. Freezing a Station

Freezing is the administrative interlock described in §2.7. A `UtilityAdmin` freezes a station, moving its posture `NORMAL → FROZEN` — but only when the station has no SSO event in `OPEN`, `CONTAINED`, `REPORT_DRAFT`, or `REPORT_SUBMITTED` and no confined-space permit in `ISSUED` or `ACTIVE`; an active emergency or live permit must be wound down first. Freezing cascades: every `SCHEDULED` wet-well cleaning at the station moves to `CANCELLED`, and every `SCHEDULED` generator test moves to `CANCELLED`. The station's `version` increments and `updated_at` refreshes. Unfreezing returns the station from `FROZEN`, at which point posture is recomputed from live child state per §2.7. Recall from §2.7 that all child mutations at a frozen station are refused with `ERR_STATION_FROZEN`, and that non-critical child mutations at an emergency station are refused with `ERR_STATION_EMERGENCY`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/lift-station-ops` prefix. Creation of a new resource returns HTTP 201; actions that modify an existing resource and all reads return HTTP 200. Request and response shapes for each endpoint are governed by the workflows in §3 within the envelope of §2.2; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /lift-station-ops/stations | Create a LiftStation. | UtilityAdmin |
| GET | /lift-station-ops/stations | List LiftStations; filterable by `service_zone` and `operational_posture`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner, ComplianceOfficer, CapitalProgramManager |
| GET | /lift-station-ops/stations/{id} | Fetch a LiftStation. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner, ComplianceOfficer, CapitalProgramManager |
| POST | /lift-station-ops/stations/{id}/freeze | Freeze the station (posture → `FROZEN`); cancels scheduled cleanings and generator tests. | UtilityAdmin |
| POST | /lift-station-ops/stations/{id}/unfreeze | Unfreeze the station; posture recomputed. | UtilityAdmin |
| POST | /lift-station-ops/pumps | Register a Pump at a station. | MaintenancePlanner, UtilityAdmin |
| GET | /lift-station-ops/pumps | List Pumps; filterable by `station_id` and `status`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner |
| GET | /lift-station-ops/stations/{id}/pumps | List Pumps for a station. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner |
| GET | /lift-station-ops/pumps/{id} | Fetch a Pump. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner |
| POST | /lift-station-ops/pumps/{id}/standby | Transition pump `IN_SERVICE` → `STANDBY`. | OperationsSupervisor |
| POST | /lift-station-ops/pumps/{id}/activate | Transition pump `STANDBY` or `OUT_OF_SERVICE` → `IN_SERVICE`. | OperationsSupervisor |
| POST | /lift-station-ops/pumps/{id}/mark-out-of-service | Transition pump `IN_SERVICE` → `OUT_OF_SERVICE`. | OperationsSupervisor |
| POST | /lift-station-ops/pumps/alternate | Run pump alternation at a station; swaps lead/lag when the threshold is crossed. | OperationsSupervisor, UtilityAdmin |
| POST | /lift-station-ops/pumps/{id}/runtime-readings | Ingest a runtime reading for a pump. | Operator, ScadaWebhook, UtilityAdmin |
| GET | /lift-station-ops/pumps/{id}/runtime-readings | List runtime readings for a pump; filterable by `since`/`until`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner |
| POST | /lift-station-ops/operators | Create an Operator. | UtilityAdmin |
| GET | /lift-station-ops/operators | List Operators; filterable by `is_active` and `home_zone`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, MaintenancePlanner |
| GET | /lift-station-ops/operators/{id} | Fetch an Operator. | UtilityAdmin, OperationsSupervisor, OnCallOperator, MaintenancePlanner |
| POST | /lift-station-ops/stations/{id}/alarm-tickets | Raise an AlarmTicket at a station. | ScadaWebhook, OnCallOperator, UtilityAdmin |
| GET | /lift-station-ops/stations/{id}/alarm-tickets | List AlarmTickets for a station; filterable by `status` and `alarm_class`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, ComplianceOfficer |
| GET | /lift-station-ops/alarm-tickets | Filtered list of AlarmTickets by `station_id`, `assigned_operator_id`, `status`, `alarm_class`. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, ComplianceOfficer |
| GET | /lift-station-ops/alarm-tickets/{id} | Fetch an AlarmTicket. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, ComplianceOfficer |
| POST | /lift-station-ops/alarm-tickets/{id}/ack | Acknowledge an `OPEN` ticket. | OnCallOperator |
| POST | /lift-station-ops/alarm-tickets/{id}/dispatch | Dispatch the ticket; selects the callout winner. OCC-guarded by `expected_ticket_version`. | OnCallOperator |
| POST | /lift-station-ops/alarm-tickets/{id}/arrive | Mark ticket `ON_SCENE`. | Operator |
| POST | /lift-station-ops/alarm-tickets/{id}/clear | Clear an `ON_SCENE` ticket. | Operator |
| POST | /lift-station-ops/alarm-tickets/{id}/cancel | Cancel a ticket. | OnCallOperator, OperationsSupervisor |
| POST | /lift-station-ops/pump-rebuilds | Open a PumpRebuild; drives the pump `IN_SERVICE` → `REBUILD`. | MaintenancePlanner |
| GET | /lift-station-ops/pump-rebuilds | Filtered list of PumpRebuilds by `pump_id` and `status`. | UtilityAdmin, OperationsSupervisor, MaintenancePlanner |
| GET | /lift-station-ops/pumps/{id}/rebuilds | List PumpRebuilds for a pump. | UtilityAdmin, OperationsSupervisor, MaintenancePlanner |
| GET | /lift-station-ops/pump-rebuilds/{id} | Fetch a PumpRebuild. | UtilityAdmin, OperationsSupervisor, MaintenancePlanner |
| POST | /lift-station-ops/pump-rebuilds/{id}/start | Transition rebuild `OPEN` → `IN_PROGRESS`. | MaintenancePlanner |
| POST | /lift-station-ops/pump-rebuilds/{id}/complete | Transition rebuild `IN_PROGRESS` → `COMPLETED`; pump `REBUILD` → `IN_SERVICE`. | MaintenancePlanner |
| POST | /lift-station-ops/pump-rebuilds/{id}/cancel | Cancel the rebuild; pump transitions `REBUILD` → `OUT_OF_SERVICE`. | MaintenancePlanner, OperationsSupervisor |
| POST | /lift-station-ops/stations/{id}/wet-well-cleanings | Schedule a wet-well cleaning at a station. | MaintenancePlanner, OperationsSupervisor |
| GET | /lift-station-ops/stations/{id}/wet-well-cleanings | List cleanings for a station; filterable by `status`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/wet-well-cleanings | Filtered list of cleanings by `station_id`, `status`, `crew_lead_operator_id`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/wet-well-cleanings/{id} | Fetch a cleaning. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| POST | /lift-station-ops/wet-well-cleanings/{id}/start | Start cleaning (`SCHEDULED` or `OVERDUE` → `IN_PROGRESS`). | Operator |
| POST | /lift-station-ops/wet-well-cleanings/{id}/complete | Complete cleaning; records `grease_depth_inches_post`. | Operator |
| POST | /lift-station-ops/wet-well-cleanings/{id}/cancel | Cancel a cleaning. | OperationsSupervisor |
| POST | /lift-station-ops/stations/{id}/generator-tests | Schedule a generator test. | MaintenancePlanner, OperationsSupervisor |
| GET | /lift-station-ops/stations/{id}/generator-tests | List generator tests for a station; filterable by `status`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/generator-tests | Filtered list of generator tests by `station_id`, `status`, `test_kind`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/generator-tests/{id} | Fetch a generator test. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| POST | /lift-station-ops/generator-tests/{id}/start | Start a generator test (`SCHEDULED` or `OVERDUE` → `RUNNING`). | Operator |
| POST | /lift-station-ops/generator-tests/{id}/finish | Mark `RUNNING` → `PASSED`; supplies `duration_minutes`. | Operator |
| POST | /lift-station-ops/generator-tests/{id}/fail | Mark `RUNNING` → `FAILED`; fires the `GEN_TEST_FAILED` alarm. | Operator |
| POST | /lift-station-ops/generator-tests/{id}/abort | Abort a `RUNNING` test. | Operator |
| POST | /lift-station-ops/generator-tests/{id}/cancel | Cancel a `SCHEDULED` or `OVERDUE` test. | OperationsSupervisor |
| POST | /lift-station-ops/stations/{id}/sso-events | Record an SSO event at a station. OCC-guarded by `expected_station_version`. | ScadaWebhook, Operator, UtilityAdmin |
| GET | /lift-station-ops/stations/{id}/sso-events | List SSO events for a station; filterable by `status`. | UtilityAdmin, OperationsSupervisor, Operator, ComplianceOfficer, RegulatorPortal |
| GET | /lift-station-ops/sso-events | Filtered list of SSO events by `station_id`, `status`, `cause_code`. | UtilityAdmin, OperationsSupervisor, Operator, ComplianceOfficer, RegulatorPortal |
| GET | /lift-station-ops/sso-events/{id} | Fetch an SSO event. | UtilityAdmin, OperationsSupervisor, Operator, ComplianceOfficer, RegulatorPortal |
| POST | /lift-station-ops/sso-events/{id}/contain | Mark SSO `OPEN` → `CONTAINED`; computes the provisional `estimated_volume_gal`. | Operator |
| POST | /lift-station-ops/sso-events/{id}/draft-report | Move SSO `CONTAINED` → `REPORT_DRAFT`. | ComplianceOfficer |
| POST | /lift-station-ops/sso-events/{id}/submit-report | Move SSO `REPORT_DRAFT` → `REPORT_SUBMITTED`; recomputes the final `estimated_volume_gal`. | ComplianceOfficer |
| POST | /lift-station-ops/sso-events/{id}/accept-report | Regulator accepts the report. | RegulatorPortal |
| POST | /lift-station-ops/sso-events/{id}/reject-report | Regulator rejects; returns to `REPORT_DRAFT`. | RegulatorPortal |
| POST | /lift-station-ops/sso-events/{id}/close | Close an accepted SSO. | ComplianceOfficer |
| POST | /lift-station-ops/stations/{id}/confined-space-permits | Create a `DRAFT` confined-space permit. | Operator, OperationsSupervisor |
| GET | /lift-station-ops/stations/{id}/confined-space-permits | List permits for a station; filterable by `status`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/confined-space-permits | Filtered list of permits by `station_id`, `status`, `authorized_entrant_id`, `attendant_operator_id`, `entry_supervisor_id`. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| GET | /lift-station-ops/confined-space-permits/{id} | Fetch a permit. | UtilityAdmin, OperationsSupervisor, Operator, MaintenancePlanner |
| POST | /lift-station-ops/confined-space-permits/{id}/issue | Issue the permit (`DRAFT` → `ISSUED`). | Operator |
| POST | /lift-station-ops/confined-space-permits/{id}/activate | Activate the permit (`ISSUED` or `SUSPENDED` → `ACTIVE`). | Operator |
| POST | /lift-station-ops/confined-space-permits/{id}/suspend | Suspend an `ACTIVE` permit. | Operator |
| POST | /lift-station-ops/confined-space-permits/{id}/close | Close an `ACTIVE` permit. | Operator |
| POST | /lift-station-ops/confined-space-permits/{id}/cancel | Cancel a `DRAFT` or `ISSUED` permit. | OperationsSupervisor |
| POST | /lift-station-ops/capital-plans | Create a CapitalPlan for a `plan_year`. | CapitalProgramManager |
| GET | /lift-station-ops/capital-plans | List CapitalPlans; filterable by `status` and `plan_year`. | UtilityAdmin, OperationsSupervisor, CapitalProgramManager |
| GET | /lift-station-ops/capital-plans/{id} | Fetch a CapitalPlan. | UtilityAdmin, OperationsSupervisor, CapitalProgramManager |
| POST | /lift-station-ops/capital-plans/{id}/rank | Rank all `PROPOSED` projects (`DRAFT` → `RANKED`). | CapitalProgramManager |
| POST | /lift-station-ops/capital-plans/{id}/approve | Approve the ranked plan (`RANKED` → `APPROVED`). OCC-guarded by `expected_plan_version`. | UtilityAdmin |
| POST | /lift-station-ops/capital-plans/{id}/lock | Lock an approved plan after the 7-day cooling period (`APPROVED` → `LOCKED`). | UtilityAdmin |
| POST | /lift-station-ops/capital-plans/{id}/unrank | Revert `RANKED` → `DRAFT`; cascades projects `RANKED` → `PROPOSED`. | CapitalProgramManager |
| POST | /lift-station-ops/capital-projects | Create a CapitalProject under a plan. | CapitalProgramManager |
| GET | /lift-station-ops/capital-plans/{id}/capital-projects | List projects under a plan; filterable by `status`. | UtilityAdmin, OperationsSupervisor, CapitalProgramManager |
| GET | /lift-station-ops/capital-projects | Filtered list of projects by `plan_id`, `station_id`, `status`. | UtilityAdmin, OperationsSupervisor, CapitalProgramManager |
| GET | /lift-station-ops/capital-projects/{id} | Fetch a project. | UtilityAdmin, OperationsSupervisor, CapitalProgramManager |
| POST | /lift-station-ops/capital-projects/{id}/reject | Reject a `PROPOSED` project. | CapitalProgramManager |
| POST | /lift-station-ops/capital-projects/{id}/cancel | Cancel a `PROPOSED` project. | CapitalProgramManager |
| POST | /lift-station-ops/capital-projects/{id}/resubmit | Move `DEFERRED` → `PROPOSED` when the parent plan is `DRAFT`. | CapitalProgramManager |
| POST | /lift-station-ops/spare-pumps | Register a SparePump. | UtilityAdmin, MaintenancePlanner |
| GET | /lift-station-ops/spare-pumps | List SparePumps; filterable by `status`, `compatible_zone`, `reserved_for_station_id`, `deployed_at_station_id`. | UtilityAdmin, OperationsSupervisor, MaintenancePlanner |
| GET | /lift-station-ops/spare-pumps/{id} | Fetch a SparePump. | UtilityAdmin, OperationsSupervisor, MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/reserve | Reserve an `AVAILABLE` spare for a station. | MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/deploy | Deploy a `RESERVED` spare. | MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/return | Return a `DEPLOYED` or `REBUILD` spare to `AVAILABLE`. | MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/release | Release a `RESERVED` spare to `AVAILABLE`. | MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/send-to-rebuild | Send an `AVAILABLE` spare to `REBUILD`. | MaintenancePlanner |
| POST | /lift-station-ops/spare-pumps/{id}/retire | Retire an `AVAILABLE` spare. | UtilityAdmin |
| GET | /lift-station-ops/stations/{id}/summary | Computed station summary: posture, firm capacity, open/overdue counts, grease rate, next cleaning due, last SSO. | UtilityAdmin, OperationsSupervisor, OnCallOperator, Operator, MaintenancePlanner, ComplianceOfficer |
| POST | /lift-station-ops/_clock/set_current_utc | Set the server logical clock to a supplied `to_iso8601` instant. | UtilityAdmin |
| POST | /lift-station-ops/_clock/tick | Advance the system tick; re-evaluates automatic transitions (`SCHEDULED` → `OVERDUE`, posture recompute). | UtilityAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API may return, with its HTTP status code. The conditions under which each error is raised are defined in the narrative of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_STATION_FROZEN | 409 |
| ERR_STATION_EMERGENCY | 409 |
| ERR_FIRM_CAPACITY_VIOLATION | 422 |
| ERR_DUPLICATE_STATION_CODE | 422 |
| ERR_DUPLICATE_EMPLOYEE_CODE | 422 |
| ERR_DUPLICATE_PLAN_YEAR | 422 |
| ERR_DUPLICATE_ASSET_TAG | 422 |
| ERR_DUPLICATE_POSITION | 422 |
| ERR_ZONE_MISMATCH | 422 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 422 |
| ERR_INSUFFICIENT_CERTIFICATION | 422 |
| ERR_GAS_TEST_REQUIRED | 422 |
| ERR_PERMIT_REQUIRED | 422 |
| ERR_PERMIT_EXPIRED | 422 |
| ERR_NO_ELIGIBLE_OPERATOR | 422 |
| ERR_READING_OUT_OF_ORDER | 422 |
| ERR_TEST_DURATION_TOO_SHORT | 422 |
| ERR_GREASE_DEPTH_INVALID | 422 |
| ERR_REPORT_DEADLINE_MISSED | 422 |
| ERR_SSO_EVENT_OPEN | 422 |
| ERR_BUDGET_EXCEEDED | 422 |
| ERR_PLAN_NOT_SETTLED | 422 |
| ERR_PLAN_LOCKED | 409 |
| ERR_NO_PUMPS_TO_ALTERNATE | 422 |
| ERR_VALIDATION_AGGREGATE | 422 |
