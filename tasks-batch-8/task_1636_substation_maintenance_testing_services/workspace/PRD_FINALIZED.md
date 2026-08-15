# Substation Maintenance Testing API — Product Requirements Document

## 1. Introduction

A NETA-accredited testing firm coordinates the full maintenance lifecycle of high-voltage substation apparatus: power transformers, circuit breakers, and protective relays. The work is unforgiving of ambiguity. A relay that is mis-set by one turn of a time dial can fail to trip during a fault; an outage window that begins switching before the upstream protective margin is verified can injure a crew; a spill-prevention inspection that measures containment against the wrong regulatory variant can expose the firm to federal penalty. This platform exists to make every one of those judgments deterministic, auditable, and reproducible.

The system manages the substation register and its equipment fleet, the maintenance-interval policy book per equipment class, outage and clearance windows (with their switching sequences), the test record (insulation resistance, oil moisture, relay timing), the defect pipeline from finding through verified corrective work, the spare transformer and mobile substation logistics pool, the relay setting version chain, and the environmental (oil containment) compliance file. Field technicians, outage coordinators, switching supervisors, operations managers, and compliance officers all act on the same entities from different angles, so segregation-of-duties and optimistic concurrency are first-class concerns, not afterthoughts.

Every timestamp, every state transition, every capacity figure, and every grading threshold in this document is normative. Where two regulatory or operational variants exist for the same quantity — maintenance forecasting, containment requirement, defect SLA — both are specified, and the document says which one is authoritative for which field.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two authentication headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role string the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The platform declares exactly five roles, spelled exactly as follows: `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer`.

Identity is bound differently for one role than the other four. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on any resource that references a `Technician` — the `technician_id` on a `TestEvent`, the `author_technician_id` on a `RelaySetting`, the `assigned_technician_id` on a `WorkOrder`, the `verified_by_technician_id` on a `RelaySetting` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by` on an `OutageWindow`, `approved_by` on an `OutageWindow`, `executed_by` or `verified_by` on a `SwitchingStep`, or `reviewed_by` on a `TestEvent`) but does not compare it to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. The default `limit` is 10, the minimum is 1, the maximum is 100, and the default `offset` is 0. Results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted entity carries `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that increments by exactly 1 on every state transition and on every mutation the platform applies to that row). There are no exceptions to the common-fields rule for this platform: every entity in the domain carries the full set.

When an operation mutates more than one entity — for example, scheduling a work order both advances the work order and commits hours against its window — each affected entity's `version` increments independently, and each affected entity's `updated_at` refreshes independently.

### 2.5. Precision, Rounding, and Monetary Discipline

Wherever the platform emits a decimal measurement, capacity figure, score, or cost, the value is expressed at 2 decimal places, rounded half-up. Two sub-domains pin this further. Insulation-resistance grading performs its threshold comparison on the unrounded temperature-corrected value — no rounding occurs before the comparison. Work-order costing rounds each individual labor and parts line to 2 decimal places half-up before any summation, and only then sums the rounded lines into `cost_subtotal`; the mobilization fee is then computed from that subtotal and itself rounded to 2 decimal places half-up. Summing first and rounding once at the end produces different cents and is forbidden.

### 2.6. Optimistic Concurrency Control

Two write endpoints carry a mandatory OCC field. Activating a relay setting requires the request to carry `expected_asset_version` equal to the current `version` of the target `Asset`. Scheduling a work order requires the request to carry `expected_outage_window_version` equal to the current `version` of the target `OutageWindow`. In both cases, a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes an OCC field; clients do not supply version fields elsewhere.

The intent is stale-basis rejection, not request ordering: an activation carrying an older `expected_asset_version` is acting on a coordination basis the server has already advanced past, and a schedule carrying an older `expected_outage_window_version` would commit hours against a stale remaining-capacity figure. Both are refused for the same reason.

### 2.7. The Logical Clock

The platform runs on a logical clock, not on wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. An administrative capability advances the clock to a supplied `to_iso8601` instant; this is the only way time passes. Two domain rules are clock-driven: any `Defect` in `DEFERRED` whose `deferred_until` is at or before the new clock value reopens to `OPEN` and clears its `deferred_until`; and every `TechnicianCertification`'s derived `status` is recomputed against the new clock value (so a certification whose `expires_at` has been reached flips to `EXPIRED`).

### 2.8. Validation Priority Ordering

When a request would trip more than one rule, the platform surfaces exactly one error, chosen by priority. The order is fixed: authentication (HTTP 401) runs first; then role authorization (HTTP 403); then path-id resolution, left-to-right along nested URL segments (HTTP 404); then request-body schema and field-type checks (HTTP 400); then foreign-key resolution for ids supplied in the body (HTTP 404); then the asset-class policy existence check on asset creation (HTTP 404, `ERR_POLICY_NOT_FOUND`); then uniqueness conflicts (`ERR_DUPLICATE_KEY`, HTTP 409); then the state-machine permission check (`ERR_STATE_TRANSITION`, HTTP 409); then the OCC stale-version check (`ERR_STALE_VERSION`, HTTP 412); then the certification gate (`ERR_CERTIFICATION_REQUIRED`, HTTP 403); then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); then the open-critical-defect guard on outage create/approve (`ERR_OPEN_CRITICAL_DEFECT`, HTTP 422); then interval-in-the-past (`ERR_INTERVAL_IN_PAST`, HTTP 422); then clock-gated action windows (`ERR_OUTSIDE_WINDOW`, HTTP 422); then outage-window overlap and the 24-hour buffer (`ERR_OUTAGE_WINDOW_CONFLICT`, HTTP 409); then spare-reservation overlap (`ERR_SPARE_RESERVATION_CONFLICT`, HTTP 409); then the spare selector's empty-pool outcome (`ERR_NO_COMPATIBLE_SPARE`, HTTP 422); then switching-step ordering (`ERR_STEP_ORDER_VIOLATION`, HTTP 409); then the all-steps-verified check on clear (`ERR_STEPS_NOT_VERIFIED`, HTTP 409); then the revalidation flag (`ERR_OUTAGE_NEEDS_REVALIDATION`, HTTP 409); then the deferral cap (`ERR_DEFERRAL_LIMIT_EXCEEDED`, HTTP 422); then the in-service precondition on relay activation (`ERR_ASSET_NOT_IN_SERVICE`, HTTP 409); then the relay coordination margin (`ERR_RELAY_COORDINATION_VIOLATION`, HTTP 422); then the decommissioned-asset guard (`ERR_ASSET_DECOMMISSIONED`, HTTP 422); then the spare decommission guard (`ERR_ACTIVE_RESERVATIONS`, HTTP 409); then the outage-cleared precondition on outage-gated test submission (`ERR_OUTAGE_NOT_CLEARED`, HTTP 409); then the outage-capacity check on schedule (`ERR_OUTAGE_CAPACITY_EXCEEDED`, HTTP 422); and finally the cross-reference consistency checks (HTTP 400).

### 2.9. Nested Resource Retrieval

Where a URL nests one resource under another (a switching step under its outage window, a certification under its technician, an environmental inspection under its substation), path identifiers resolve left-to-right. A failure at any segment produces `ERR_NOT_FOUND` (HTTP 404) before the request proceeds to deeper validation.

## 3. Business Logic & Workflows

### 3.1. Fleet Register and Maintenance Policy Book

An `OperationsManager` builds the platform's reference data first. A substation is registered with a `name`, a `code` unique across all substations, and a `region`; it arrives in `ACTIVE` status and may later be decommissioned to `DECOMMISSIONED`. The maintenance policy book is a set of `AssetClassPolicy` rows, one per equipment class. Each policy names its `asset_class` (one of `POWER_TRANSFORMER`, `CIRCUIT_BREAKER`, `RELAY`; the class label is unique across policies), a baseline `interval_months` (an integer greater than 0), two condition thresholds (`condition_escalation_threshold` and `condition_critical_threshold`), two oil-moisture thresholds (`oil_warn_ppm` and `oil_critical_ppm`), a minimum acceptable insulation resistance `ir_min_mohm`, two relay-timing deviation bounds (`relay_timing_warn_pct` and `relay_timing_fail_pct`), and the three weights `w_insulation`, `w_oil`, `w_relay` used by the condition score. Creating a second policy for a class that already has one is rejected with `ERR_DUPLICATE_KEY` (HTTP 409), as is creating a second substation with the same `code` or a second technician with the same `employee_code`.

An `Asset` is then registered against a substation by `substation_id`. The caller supplies `asset_class`, `voltage_kv`, `install_date`, and optionally `criticality` (default `MEDIUM`; one of `HIGH`, `MEDIUM`, `LOW`), `nameplate_mva` (required in practice for `POWER_TRANSFORMER`), `last_maintenance_completed_at`, and `upstream_asset_id`. The platform refuses to register an asset whose class has no `AssetClassPolicy` with `ERR_POLICY_NOT_FOUND` (HTTP 404). When `upstream_asset_id` is supplied, it must point at an existing `Asset` whose `asset_class` is `RELAY`; a mismatch is a cross-reference violation and is rejected with `ERR_VALIDATION` (HTTP 400). The new asset arrives in `IN_SERVICE` status with `condition_score` initialized to 100.00 and `next_due_date` computed from the condition-adjusted variant described in §3.5.

### 3.2. Outage Windows and the Approval Gate

An `OutageCoordinator` requests an outage window by supplying `substation_id`, `asset_id`, `start_ts`, `end_ts`, and `purpose`. The interval is half-open: `start_ts` is the inclusive bound, `end_ts` is the exclusive bound, and `end_ts` must be strictly after `start_ts`. The start must lie strictly in the future relative to the logical clock; otherwise the request is rejected with `ERR_INTERVAL_IN_PAST` (HTTP 422). The new window is checked against every other non-terminal window of the same asset — that is, windows in `REQUESTED`, `APPROVED`, `SWITCHING`, or `CLEARED`. Any overlap under half-open semantics, or a gap to the nearest such window of strictly less than 24 hours, is rejected with `ERR_OUTAGE_WINDOW_CONFLICT` (HTTP 409); a gap of exactly 24 hours is permitted. If the asset carries an open critical defect — a `Defect` at severity `C1` in `OPEN`, `WORK_ORDERED`, or `DEFERRED` — creation is rejected with `ERR_OPEN_CRITICAL_DEFECT` (HTTP 422). And if the asset is `DECOMMISSIONED`, creation is rejected with `ERR_ASSET_DECOMMISSIONED` (HTTP 422). A successfully created window arrives in `REQUESTED` with `requested_by` stamped from the caller's `X-User-ID` and `duration_hours` computed as the difference between `end_ts` and `start_ts` expressed in hours at 2 decimal places rounded half-up.

Approval is performed by an `OperationsManager` and is a different operator from the requester; an approver whose `X-User-ID` equals the window's `requested_by` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval enforces, in order, that the window is in `REQUESTED`, that `needs_revalidation` is false (otherwise `ERR_OUTAGE_NEEDS_REVALIDATION`, HTTP 409), and that no `C1` defect in `OPEN`, `WORK_ORDERED`, or `DEFERRED` exists against the window's asset (otherwise `ERR_OPEN_CRITICAL_DEFECT`, HTTP 422). A successful approval transitions the window `REQUESTED → APPROVED`, stamps `approved_by` from the caller's `X-User-ID`, adds the window's `duration_hours` into the asset's `approved_outage_hours`, and increments the window's `version`. Rejection transitions `REQUESTED → REJECTED` and is a terminal state.

An `OutageCoordinator` may cancel a window while it is `REQUESTED` or `APPROVED`. Cancelling from `REQUESTED` simply transitions to `CANCELLED`. Cancelling from `APPROVED` performs compensation: the window's `duration_hours` is subtracted from the asset's `approved_outage_hours`, and every linked `WorkOrder` still in `DRAFT` or `SCHEDULED` is transitioned to `CANCELLED` — with each such cancellation in turn returning its linked `Defect` from `WORK_ORDERED` to `OPEN`.

### 3.3. Switching Execution and Clearance

A switching plan is a sequence of `SwitchingStep` rows under a window. An `OutageCoordinator` adds steps while the window is `REQUESTED` or `APPROVED` by supplying `sequence_no` (an integer at least 1, unique within the window — duplicates are rejected with `ERR_DUPLICATE_KEY`, HTTP 409) and a free-text `description`. Each step arrives `PENDING` with `executed_by`, `executed_at`, `verified_by`, and `verified_at` all null.

Beginning switching is a `SwitchingSupervisor` action gated on four conditions: the window is `APPROVED`; `needs_revalidation` is false; the logical clock lies within `[start_ts, end_ts)` — that is, at or after `start_ts` and strictly before `end_ts`, otherwise `ERR_OUTSIDE_WINDOW` (HTTP 422); and the window has at least one switching step. Success transitions the window `APPROVED → SWITCHING` and drives the asset `IN_SERVICE → OUT_OF_SERVICE`, incrementing both entities' versions.

While the window is `SWITCHING`, a `SwitchingSupervisor` executes each `PENDING` step. Execution is strictly ordered: a step may execute only when every sibling step of the same window with a lower `sequence_no` is already `VERIFIED`; violating the order is rejected with `ERR_STEP_ORDER_VIOLATION` (HTTP 409). Executing stamps `executed_by` from the caller's `X-User-ID` and `executed_at` from the logical clock. Verification is a second `SwitchingSupervisor` action on an `EXECUTED` step; the verifier's `X-User-ID` must differ from `executed_by`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verification stamps `verified_by` and `verified_at` from the logical clock and transitions the step `EXECUTED → VERIFIED`.

Clearing the window requires every switching step of the window to be `VERIFIED`; any shortfall is rejected with `ERR_STEPS_NOT_VERIFIED` (HTTP 409). A successful clear transitions `SWITCHING → CLEARED`. Restoring the asset to service requires that no `WorkOrder` linked to this window remains in `SCHEDULED` or `IN_PROGRESS`; success transitions `CLEARED → RESTORED` and drives the asset `OUT_OF_SERVICE → IN_SERVICE`, again incrementing both versions.

### 3.4. Test Events, Grading, and Review

A `Technician` records a test event against an asset by supplying `asset_id`, `test_type` (one of `INSULATION_RESISTANCE`, `OIL_MOISTURE`, `RELAY_TIMING`), `value_primary`, `measured_at`, and optionally `value_secondary`, `ambient_temp_c`, `requires_outage`, and `outage_window_id`. The semantics of the two value fields depend on `test_type`: for `INSULATION_RESISTANCE`, `value_primary` is the measured insulation resistance in megaohms and `ambient_temp_c` (Celsius) is required; for `OIL_MOISTURE`, `value_primary` is the moisture content in ppm; for `RELAY_TIMING`, `value_primary` is the measured operating time in milliseconds and `value_secondary` is the nominal operating time in milliseconds, and `value_secondary` is required. The `technician_id` is stamped from the caller's `X-User-ID`. The event arrives in `DRAFT` with `result` null. Creating a test against a `DECOMMISSIONED` asset is rejected with `ERR_ASSET_DECOMMISSIONED` (HTTP 422).

Submission is gated. Only the creator may submit — the caller's `X-User-ID` must equal the event's `technician_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The technician must hold the required certification: `NETA_LEVEL_3` or higher for a `RELAY_TIMING` submission, `NETA_LEVEL_2` or higher for any other test type; a technician without an `ACTIVE` certification at the required rank is rejected with `ERR_CERTIFICATION_REQUIRED` (HTTP 403). When `requires_outage` is true, the linked outage window must be in `CLEARED` — submitting against a window in any other state is rejected with `ERR_OUTAGE_NOT_CLEARED` (HTTP 409). Submission from `DRAFT` transitions to `SUBMITTED`; submission from `RETURNED` (a resubmission) also transitions to `SUBMITTED` and recomputes the result from the current `value_primary`, `value_secondary`, and `ambient_temp_c`.

Grading runs at submit time and depends on `test_type`:

- For `INSULATION_RESISTANCE`, the platform computes the temperature-corrected resistance by multiplying `value_primary` by 2 raised to the power of one-tenth of the difference between `ambient_temp_c` and the 40-degree reference temperature — that is, the measured resistance doubles for every 10 degrees Celsius the ambient is above 40 and halves for every 10 degrees below. The corrected value is compared against the policy's `ir_min_mohm`: a corrected value at or above `ir_min_mohm` grades `PASS`; a corrected value strictly below `ir_min_mohm` but at or above half of `ir_min_mohm` grades `MARGINAL`; anything below half grades `FAIL`. The comparison is performed on the unrounded corrected value.
- For `OIL_MOISTURE`, the comparison is inclusive at both bounds: a `value_primary` at or above `oil_critical_ppm` grades `FAIL`; strictly below that but at or above `oil_warn_ppm` grades `MARGINAL`; below `oil_warn_ppm` grades `PASS`. A reading exactly equal to `oil_warn_ppm` is `MARGINAL`; exactly equal to `oil_critical_ppm` is `FAIL`.
- For `RELAY_TIMING`, the deviation percent is the absolute difference between `value_primary` and `value_secondary`, divided by `value_secondary`, multiplied by 100. A deviation strictly greater than `relay_timing_fail_pct` grades `FAIL`; strictly greater than `relay_timing_warn_pct` but not greater than `relay_timing_fail_pct` grades `MARGINAL`; otherwise `PASS`. A deviation exactly equal to `relay_timing_warn_pct` is `PASS`; exactly equal to `relay_timing_fail_pct` is `MARGINAL`.

Review is a `ComplianceOfficer` action carrying a `decision` and an optional `review_note`. A decision of `ACCEPT` transitions `SUBMITTED → ACCEPTED` and stamps `reviewed_by`. A decision of `RETURN` requires `review_note` to be present — its absence is rejected with `ERR_VALIDATION` (HTTP 400) — and transitions `SUBMITTED → RETURNED`, also stamping `reviewed_by`.

Acceptance triggers a three-hop cascade. First, the asset's `condition_score` is recomputed (see §3.5). Second, when the accepted `result` is `MARGINAL` or `FAIL`, the platform auto-creates a `Defect` on the same asset with `test_event_id` pointing at the accepted event, a system-generated `title`, severity mapped from the result (`FAIL` becomes `C2`; `MARGINAL` becomes `C3` — any severity supplied by the caller on this path is ignored), and status `OPEN`. Third, the defect creation re-runs the condition-score computation so the new defect's penalty lands immediately; if the recomputed score has fallen strictly below the policy's `condition_escalation_threshold`, every outage window of the asset still in `REQUESTED` or `APPROVED` has `needs_revalidation` set true, and the asset's `next_due_date` is recomputed. When the score later recovers to at or above the escalation threshold, the flag clears back to false on the same set of windows.

### 3.5. Condition Score and Maintenance Forecasting

The asset `condition_score` is a weighted, renormalized score over the three test disciplines, minus open-defect penalties. For each of `INSULATION_RESISTANCE`, `OIL_MOISTURE`, and `RELAY_TIMING`, the platform considers this asset's `ACCEPTED` test events whose `measured_at` falls within the trailing 24 months up to and including the logical clock. If any exist for a discipline, the one with the latest `measured_at` is chosen — ties broken by `created_at` ascending — and its result maps to a component score: `PASS` is 100, `MARGINAL` is 70, `FAIL` is 30. The base score is the weighted average over present components only: each present component is multiplied by its policy weight (`w_insulation`, `w_oil`, `w_relay`), summed, and divided by the sum of the weights of the present components; the weights of absent disciplines are dropped entirely. If no discipline has any qualifying event, the base is 100. The penalty is computed over the asset's defects in `OPEN`, `WORK_ORDERED`, or `DEFERRED`: each `C1` defect subtracts 5, each `C2` subtracts 2, each `C3` subtracts 1. The final `condition_score` is the base minus the penalty, floored at zero, and rounded half-up to 2 decimal places.

The maintenance due date has two sanctioned variants. Both share a baseline: the asset's `last_maintenance_completed_at` when set, else its `install_date`. The **interval-baseline** variant adds the policy's `interval_months` to the baseline regardless of condition. The **condition-adjusted** variant — which is authoritative for the asset's stored `next_due_date` — divides the interval by 4 when `condition_score` is strictly below `condition_critical_threshold`, divides it by 2 when the score is strictly below `condition_escalation_threshold` but not below the critical threshold, and otherwise uses the full `interval_months`; the result is added to the baseline. Both variants produce whole ISO dates (`YYYY-MM-DD`), with month arithmetic clamping to the end of the month when the target month has fewer days. A computed read on the asset exposes both variants together with the current `condition_score` and an `escalation_active` flag, under the response keys `condition_score`, `next_due_interval_baseline`, `next_due_condition_adjusted`, and `escalation_active`.

`next_due_date` is recomputed at asset creation, at every condition-score recompute, and at work-order verification (which refreshes `last_maintenance_completed_at`).

### 3.6. Defects, Deferral, and Corrective Work Orders

A `Defect` may be reported manually by a `Technician` supplying `asset_id`, `title`, `description`, and `severity` (one of `C1`, `C2`, `C3`), or may be auto-created by test review as described in §3.4. The defect arrives `OPEN` with `deferral_count` 0 and `test_event_id` null on the manual path. The `due_date` is computed from severity: `C1` defects are due 30 days after creation, `C2` after 90 days, `C3` after 365 days; the result is a whole ISO date. Defect creation recomputes the asset's `condition_score`.

An `OperationsManager` may defer an `OPEN` defect by supplying `deferred_until`. The deferral timestamp must lie strictly after the logical clock, otherwise `ERR_INTERVAL_IN_PAST` (HTTP 422). A defect may be deferred at most twice: a deferral attempted when `deferral_count` is already 2 is rejected with `ERR_DEFERRAL_LIMIT_EXCEEDED` (HTTP 422). Successful deferral transitions `OPEN → DEFERRED`, increments `deferral_count`, and records `deferred_until`. When the logical clock later reaches or passes `deferred_until`, the defect auto-reopens `DEFERRED → OPEN` and clears `deferred_until`.

Creating a `WorkOrder` against an `OPEN` defect is an `OperationsManager` action supplying `defect_id`, `assigned_technician_id`, `title`, and `estimated_hours` (strictly greater than 0). The work order's `asset_id` is denormalized from the defect's `asset_id` at creation. Creation transitions the defect `OPEN → WORK_ORDERED` and leaves the work order in `DRAFT` with `outage_window_id` null and `labor_lines` and `parts_lines` both empty arrays.

Scheduling is an `OutageCoordinator` action that places a `DRAFT` work order into a window by supplying `outage_window_id` and `expected_outage_window_version`. The target window must be in `APPROVED`, `SWITCHING`, or `CLEARED`; the window's `asset_id` must equal the work order's `asset_id` (otherwise `ERR_VALIDATION`, HTTP 400); the supplied `expected_outage_window_version` must equal the window's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412); and the work order's `estimated_hours` must fit within the window's remaining capacity — that is, `estimated_hours` is at most `duration_hours` minus `committed_hours`, otherwise `ERR_OUTAGE_CAPACITY_EXCEEDED` (HTTP 422). Success stamps the work order's `outage_window_id`, transitions `DRAFT → SCHEDULED`, adds `estimated_hours` into the window's `committed_hours`, and increments both the work order's and the window's `version`.

Starting work is a `Technician` action restricted to the assignee — the caller's `X-User-ID` must equal `assigned_technician_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and gated on the linked window being in `SWITCHING` or `CLEARED` (the asset is de-energized in those states). Success transitions `SCHEDULED → IN_PROGRESS`.

Completion is again the assignee's action, now carrying the `labor_lines` and `parts_lines` arrays. Each labor line is a `{hours, rate_per_hour}` pair; each parts line is a `{quantity, unit_price}` pair. The cost rollup proceeds in a pinned order: each labor line total is `hours` multiplied by `rate_per_hour`, rounded half-up to 2 decimal places; each parts line total is `quantity` multiplied by `unit_price`, rounded half-up to 2 decimal places; `cost_subtotal` is the sum of those rounded line totals. The mobilization tier is then keyed on `cost_subtotal` — never on `total_cost`: a subtotal of at least 500.00 earns a fee rate of 0.04, anything below earns 0.05. `mobilization_fee` is the fee rate multiplied by `cost_subtotal`, rounded half-up to 2 decimal places. `total_cost` is `cost_subtotal` plus `mobilization_fee`. Completion also stamps `completed_at` from the logical clock, transitions the linked defect `WORK_ORDERED → RESOLVED` (which recomputes the asset's `condition_score` with that defect's penalty removed), and increments the work order's `version`.

Verification by an `OperationsManager` transitions the work order `COMPLETED → VERIFIED`, cascades the defect `RESOLVED → VERIFIED`, stamps the asset's `last_maintenance_completed_at` from the logical clock, and recomputes the asset's `next_due_date`.

An `OperationsManager` may cancel a work order in `DRAFT` or `SCHEDULED`. Cancelling from `DRAFT` simply returns the defect `WORK_ORDERED → OPEN`. Cancelling from `SCHEDULED` additionally subtracts `estimated_hours` from the window's `committed_hours` and increments the window's `version`, in compensation for the schedule.

### 3.7. Spare Transformer and Mobile Substation Logistics

An `OperationsManager` registers spare apparatus with `unit_type` (one of `SPARE_TRANSFORMER`, `MOBILE_SUBSTATION`), `rating_mva`, `voltage_class_kv`, `impedance_pct`, and `home_location`. The unit arrives `AVAILABLE` and remains so until a reservation lands.

An `OutageCoordinator` reserves a unit by supplying `unit_type`, `required_mva`, `required_voltage_kv`, `start_ts`, `end_ts`, and optionally `spare_unit_id`, `preferred_impedance_pct`, `site_location`, and `work_order_id`. The interval is half-open, `end_ts` strictly after `start_ts`, and `start_ts` strictly in the future (otherwise `ERR_INTERVAL_IN_PAST`, HTTP 422). When `spare_unit_id` is supplied explicitly, it must resolve and its unit's `unit_type` must match the requested `unit_type` — a mismatch is `ERR_VALIDATION` (HTTP 400) — and the new reservation must not overlap any existing `ACTIVE` reservation of the same unit under half-open semantics; adjacency, where one reservation's `end_ts` equals the next's `start_ts`, is permitted with zero buffer. An overlap is `ERR_SPARE_RESERVATION_CONFLICT` (HTTP 409).

When `spare_unit_id` is omitted, the platform selects a unit by score. The eligible pool is every unit that is `AVAILABLE`, whose `unit_type` matches the request, whose `voltage_class_kv` exactly equals `required_voltage_kv`, whose `rating_mva` is at least the required capacity (for `MOBILE_SUBSTATION` requests the unit's rating is derated by a factor of 0.9 before this comparison — a mobile unit must have `rating_mva` at least 0.9 times `required_mva`; for `SPARE_TRANSFORMER` the factor is 1.0), and which has no `ACTIVE` reservation overlapping the requested half-open interval. The ranking score is the sum of three terms: an adequacy term of 100 times the lesser of 1.0 and the unit's `rating_mva` divided by `required_mva`; an impedance term that is 0 when `preferred_impedance_pct` is not supplied and otherwise 25 times the greater of 0 and one minus the absolute difference between the unit's `impedance_pct` and `preferred_impedance_pct` divided by 4.0; and a location term of 10 when `site_location` is supplied and equals the unit's `home_location`, else 0. Higher score wins; ties break by the unit's `created_at` ascending. If the eligible pool is empty the request is rejected with `ERR_NO_COMPATIBLE_SPARE` (HTTP 422).

A successful reservation arrives `ACTIVE` and drives its unit from `AVAILABLE` to `RESERVED`. A unit that already has an `ACTIVE` reservation may accept additional non-overlapping reservations; it stays `RESERVED` while at least one `ACTIVE` reservation exists.

An `OutageCoordinator` may cancel an `ACTIVE` reservation provided the unit is not currently deployed under it — a deployed reservation must be returned, not cancelled; cancelling it is rejected with `ERR_STATE_TRANSITION` (HTTP 409). Cancellation transitions the reservation `ACTIVE → CANCELLED` and recomputes the unit's status: `AVAILABLE` when no `ACTIVE` reservation remains on the unit, else `RESERVED`. Deploying the unit is gated on the logical clock lying within the reservation's half-open window — at or after `start_ts` and strictly before `end_ts`, otherwise `ERR_OUTSIDE_WINDOW` (HTTP 422) — and drives the unit `RESERVED → DEPLOYED`. Returning a deployed reservation transitions the reservation `ACTIVE → FULFILLED` and recomputes the unit status the same way: `AVAILABLE` when no other `ACTIVE` reservation remains, else `RESERVED`.

An `OperationsManager` may decommission a spare unit while it is `AVAILABLE` and carries no `ACTIVE` reservations. The `AVAILABLE` precondition is enforced by the state-machine permission check first: decommissioning a unit in any status other than `AVAILABLE` — including a unit that carries an `ACTIVE` reservation, since a successful reservation drives its unit out of `AVAILABLE` and the unit is not recomputed back to `AVAILABLE` while an `ACTIVE` reservation remains — is rejected with `ERR_STATE_TRANSITION` (HTTP 409). The spare decommission guard `ERR_ACTIVE_RESERVATIONS` (HTTP 409) is evaluated only after that state-machine check passes, applying to an `AVAILABLE` unit that nonetheless carries an `ACTIVE` reservation, consistent with the priority order in Section 2.8. Decommissioning transitions the unit `AVAILABLE → DECOMMISSIONED`.

### 3.8. Relay Settings and Coordination Margin

A `Technician` drafts a `RelaySetting` against a relay asset by supplying `asset_id`, `setting_group`, `pickup_a`, `time_dial`, and `curve`. The referenced asset's `asset_class` must be `RELAY`, otherwise `ERR_VALIDATION` (HTTP 400); a `DECOMMISSIONED` relay asset is rejected with `ERR_ASSET_DECOMMISSIONED` (HTTP 422). The setting arrives `DRAFT` with `author_technician_id` stamped from the caller's `X-User-ID` and `verified_by_technician_id`, `supersedes_setting_id`, and `rejection_note` all null.

Submission is the author's own action — the caller's `X-User-ID` must equal `author_technician_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and is permitted from either `DRAFT` or `REJECTED`. Verification and rejection are performed by a different technician holding an `ACTIVE` `NETA_LEVEL_4` certification; a reviewer without that certification is rejected with `ERR_CERTIFICATION_REQUIRED` (HTTP 403), and a reviewer whose `X-User-ID` equals the author's is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verification transitions `SUBMITTED → VERIFIED` and stamps `verified_by_technician_id`. Rejection requires `rejection_note` (absent is `ERR_VALIDATION`, HTTP 400) and transitions `SUBMITTED → REJECTED`.

Activation is the most heavily gated write in the platform. The activator must hold an `ACTIVE` `NETA_LEVEL_4` certification. The asset must be `IN_SERVICE` — activation against an asset in any other state is rejected with `ERR_ASSET_NOT_IN_SERVICE` (HTTP 409). The request must carry `expected_asset_version` equal to the asset's current `version`, otherwise `ERR_STALE_VERSION` (HTTP 412). The coordination margin is then checked: when the asset's `upstream_asset_id` is set and that upstream asset has an `ACTIVE` relay setting in the same `setting_group`, the upstream setting's `pickup_a` must be at least 1.3 times the activating setting's `pickup_a`; a shortfall is rejected with `ERR_RELAY_COORDINATION_VIOLATION` (HTTP 422). Success transitions the setting `VERIFIED → ACTIVE`, transitions any previously `ACTIVE` setting of the same `(asset_id, setting_group)` to `SUPERSEDED`, stamps this setting's `supersedes_setting_id` to the superseded setting's `id` (null when none existed), and increments both the setting's and the asset's `version`.

### 3.9. Technician Certification

An `OperationsManager` registers a technician with `full_name` and `employee_code` (unique). The technician arrives `ACTIVE` and may later be deactivated to `INACTIVE`. Certifications are granted under the technician by supplying `cert_type` (one of `NETA_LEVEL_2`, `NETA_LEVEL_3`, `NETA_LEVEL_4`, `SWITCHING_QUALIFIED`), `issued_at`, and `expires_at`, with `expires_at` strictly after `issued_at`.

A certification's `status` is derived, never stored by the caller: `REVOKED` when `revoked_at` is set; otherwise `EXPIRED` when the logical clock has reached or passed `expires_at` — the boundary is inclusive, so a clock exactly equal to `expires_at` is `EXPIRED`; otherwise `ACTIVE`. Revocation by an `OperationsManager` stamps `revoked_at` from the logical clock and the status flips to `REVOKED`. Advancing the logical clock recomputes every certification's derived status.

The certification gate compares enum ranks: `NETA_LEVEL_2` ranks below `NETA_LEVEL_3`, which ranks below `NETA_LEVEL_4`. The gate passes when the acting technician holds at least one certification whose `cert_type` rank is at or above the required rank and whose derived `status` is `ACTIVE`. Submitting a `RELAY_TIMING` test event requires `NETA_LEVEL_3` or higher; submitting any other test type requires `NETA_LEVEL_2` or higher; verifying, rejecting, or activating a relay setting requires `NETA_LEVEL_4` exactly as the minimum rank.

### 3.10. Environmental Inspection and Oil Containment Compliance

A `ComplianceOfficer` files an `EnvironmentalInspection` under a substation (the substation's `id` rides in the URL as the parent path parameter) by supplying `inspection_date`, `largest_vessel_gal`, `containment_capacity_gal`, `rainfall_freeboard_gal`, and `method` (one of `SPCC_SIMPLE`, `SPCC_WITH_FREEBOARD`). The inspection arrives `DRAFT` with `required_capacity_gal`, `compliance`, and `next_inspection_due` not yet computed.

Completing the inspection computes the required containment capacity under the variant named by `method`. Under `SPCC_SIMPLE`, the required capacity is 1.10 times `largest_vessel_gal`. Under `SPCC_WITH_FREEBOARD`, it is 1.00 times `largest_vessel_gal` plus `rainfall_freeboard_gal`. The result is stored in `required_capacity_gal` at 2 decimal places rounded half-up. `compliance` is `COMPLIANT` when `containment_capacity_gal` is at or above `required_capacity_gal` — the boundary is inclusive, so capacity exactly equal to required is `COMPLIANT` — and `DEFICIENT` otherwise. `next_inspection_due` is set to `inspection_date` plus 12 months when `COMPLIANT`, and plus 6 months when `DEFICIENT`. Completion transitions `DRAFT → COMPLETED`.

Closing is permitted from `COMPLETED`. When `compliance` is `DEFICIENT`, a `remediation_note` must be supplied — its absence is rejected with `ERR_VALIDATION` (HTTP 400). Closure transitions `COMPLETED → CLOSED`.

### 3.11. Asset Decommissioning and Cross-Cutting Guards

An `OperationsManager` may decommission an `IN_SERVICE` asset provided no outage window of that asset remains in `REQUESTED`, `APPROVED`, `SWITCHING`, or `CLEARED`. Success transitions `IN_SERVICE → DECOMMISSIONED`. Once an asset is `DECOMMISSIONED`, three creation paths are closed against it: recording a test event, requesting an outage window, and drafting a relay setting — each is rejected with `ERR_ASSET_DECOMMISSIONED` (HTTP 422).

Two further guards deserve restatement because they cross entity boundaries. The open-critical-defect guard fires on both outage-window creation and outage-window approval: any `C1` defect in `OPEN`, `WORK_ORDERED`, or `DEFERRED` against the asset blocks the operation with `ERR_OPEN_CRITICAL_DEFECT` (HTTP 422). The revalidation guard fires on both approval and begin-switching: while a window's `needs_revalidation` is true, both operations are rejected with `ERR_OUTAGE_NEEDS_REVALIDATION` (HTTP 409). The flag is set when the asset's `condition_score` falls strictly below the policy's `condition_escalation_threshold` while the window is `REQUESTED` or `APPROVED`, and clears when the score recovers to at or above that threshold.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources return HTTP 200. All list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock; reopens elapsed deferrals and recomputes certification statuses | `OperationsManager` |
| POST | `/substations` | Create a substation | `OperationsManager` |
| GET | `/substations` | List substations (paginated) | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/substations/{id}/decommission` | Decommission a substation | `OperationsManager` |
| POST | `/asset-class-policies` | Create an asset-class policy | `OperationsManager` |
| GET | `/asset-class-policies` | List asset-class policies | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/assets` | Register an asset against a substation | `OperationsManager` |
| GET | `/assets` | List assets with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/assets/{id}` | Get one asset | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/assets/{id}/forecast` | Computed read: condition score and both maintenance-due variants | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/assets/{id}/decommission` | Decommission an in-service asset | `OperationsManager` |
| POST | `/outage-windows` | Request an outage/clearance window | `OutageCoordinator` |
| GET | `/outage-windows` | List outage windows with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/outage-windows/{id}` | Get one outage window | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/outage-windows/{id}/approve` | Approve a requested window (approver differs from requester) | `OperationsManager` |
| POST | `/outage-windows/{id}/reject` | Reject a requested window | `OperationsManager` |
| POST | `/outage-windows/{id}/cancel` | Cancel a requested or approved window | `OutageCoordinator` |
| POST | `/outage-windows/{id}/begin-switching` | Begin switching; takes the asset out of service | `SwitchingSupervisor` |
| POST | `/outage-windows/{id}/clear` | Clear the window once every step is verified | `SwitchingSupervisor` |
| POST | `/outage-windows/{id}/restore` | Restore the asset to service | `SwitchingSupervisor` |
| POST | `/outage-windows/{id}/switching-steps` | Add a switching step to a window | `OutageCoordinator` |
| GET | `/outage-windows/{id}/switching-steps` | List a window's switching steps | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/switching-steps/{id}/execute` | Execute a pending step in sequence | `SwitchingSupervisor` |
| POST | `/switching-steps/{id}/verify` | Verify an executed step (verifier differs from executor) | `SwitchingSupervisor` |
| POST | `/test-events` | Record a test event draft against an asset | `Technician` |
| GET | `/test-events` | List test events with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/test-events/{id}` | Get one test event | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/test-events/{id}/submit` | Submit a draft or returned test event for grading | `Technician` |
| POST | `/test-events/{id}/review` | Review a submitted test; accept or return | `ComplianceOfficer` |
| POST | `/defects` | Report a manual defect finding | `Technician` |
| GET | `/defects` | List defects with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/defects/{id}` | Get one defect | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/defects/{id}/defer` | Defer an open defect | `OperationsManager` |
| POST | `/work-orders` | Create a corrective work order for an open defect | `OperationsManager` |
| GET | `/work-orders` | List work orders with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/work-orders/{id}` | Get one work order | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/work-orders/{id}/schedule` | Schedule a draft work order into a window | `OutageCoordinator` |
| POST | `/work-orders/{id}/start` | Start a scheduled work order (assignee only) | `Technician` |
| POST | `/work-orders/{id}/complete` | Complete an in-progress work order with labor and parts lines | `Technician` |
| POST | `/work-orders/{id}/verify` | Verify a completed work order; closes the defect | `OperationsManager` |
| POST | `/work-orders/{id}/cancel` | Cancel a draft or scheduled work order | `OperationsManager` |
| POST | `/spare-units` | Register a spare transformer or mobile substation | `OperationsManager` |
| GET | `/spare-units` | List spare units with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/spare-units/{id}` | Get one spare unit | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/spare-units/{id}/decommission` | Decommission an available spare unit | `OperationsManager` |
| GET | `/spare-units/{id}/reservations` | List a spare unit's reservations | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/spare-reservations` | Reserve a spare unit; omission of `spare_unit_id` triggers the selector | `OutageCoordinator` |
| GET | `/spare-reservations` | List spare reservations with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/spare-reservations/{id}` | Get one spare reservation | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/spare-reservations/{id}/cancel` | Cancel an active, non-deployed reservation | `OutageCoordinator` |
| POST | `/spare-reservations/{id}/deploy` | Deploy the reserved unit inside its window | `OutageCoordinator` |
| POST | `/spare-reservations/{id}/return` | Return a deployed unit; fulfils the reservation | `OutageCoordinator` |
| POST | `/relay-settings` | Draft a relay setting document | `Technician` |
| GET | `/relay-settings` | List relay settings with filters | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/relay-settings/{id}` | Get one relay setting | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/relay-settings/{id}/submit` | Submit a draft or rejected setting for verification | `Technician` |
| POST | `/relay-settings/{id}/verify` | Verify a submitted setting | `Technician` |
| POST | `/relay-settings/{id}/reject` | Reject a submitted setting (note required) | `Technician` |
| POST | `/relay-settings/{id}/activate` | Activate a verified setting; supersedes the prior active setting | `Technician` |
| POST | `/technicians` | Register a technician | `OperationsManager` |
| GET | `/technicians` | List technicians | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/technicians/{id}` | Get one technician | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/technicians/{id}/deactivate` | Deactivate a technician | `OperationsManager` |
| POST | `/technicians/{id}/certifications` | Grant a certification to a technician | `OperationsManager` |
| GET | `/technicians/{id}/certifications` | List a technician's certifications | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/certifications/{id}/revoke` | Revoke a certification | `OperationsManager` |
| POST | `/substations/{sid}/environmental-inspections` | File an environmental inspection for a substation | `ComplianceOfficer` |
| GET | `/environmental-inspections` | List environmental inspections | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| GET | `/environmental-inspections/{id}` | Get one environmental inspection | `OperationsManager`, `OutageCoordinator`, `SwitchingSupervisor`, `Technician`, `ComplianceOfficer` |
| POST | `/environmental-inspections/{id}/complete` | Complete an inspection; computes required capacity, compliance, next due | `ComplianceOfficer` |
| POST | `/environmental-inspections/{id}/close` | Close a completed inspection | `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CERTIFICATION_REQUIRED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_OPEN_CRITICAL_DEFECT` | 422 |
| `ERR_INTERVAL_IN_PAST` | 422 |
| `ERR_OUTSIDE_WINDOW` | 422 |
| `ERR_OUTAGE_WINDOW_CONFLICT` | 409 |
| `ERR_SPARE_RESERVATION_CONFLICT` | 409 |
| `ERR_NO_COMPATIBLE_SPARE` | 422 |
| `ERR_STEP_ORDER_VIOLATION` | 409 |
| `ERR_STEPS_NOT_VERIFIED` | 409 |
| `ERR_OUTAGE_NEEDS_REVALIDATION` | 409 |
| `ERR_DEFERRAL_LIMIT_EXCEEDED` | 422 |
| `ERR_ASSET_NOT_IN_SERVICE` | 409 |
| `ERR_RELAY_COORDINATION_VIOLATION` | 422 |
| `ERR_ASSET_DECOMMISSIONED` | 422 |
| `ERR_ACTIVE_RESERVATIONS` | 409 |
| `ERR_OUTAGE_NOT_CLEARED` | 409 |
| `ERR_OUTAGE_CAPACITY_EXCEEDED` | 422 |
