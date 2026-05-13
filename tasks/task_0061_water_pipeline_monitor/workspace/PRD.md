# Water Pipeline Monitor API — Product Requirements Document

## 1. Introduction

Municipal and industrial water utilities increasingly operate their pipeline networks as instrumented systems: pressure and flow sensors stream readings, district-metering-areas (DMAs) are reconciled against billed consumption, and any deviation can mean a buried leak silently bleeding water for weeks. This API is the backend of that monitoring loop. It accepts sensor ingest over multiple device protocols, classifies pressure and flow anomalies into severity-graded alerts, supports an investigation workflow that narrows a suspected leak to a small set of pipeline segments, and orchestrates the resulting repair work orders end-to-end — from assignment, through field repair, to post-repair verification.

The system is built around two interlocking concerns. First, the pipeline **topology** itself is a versioned graph: any change (a new node, a re-routed segment, a re-drawn DMA boundary) is proposed, reviewed, and published as a `TopologyVersion`, never edited in place. Operations downstream — device mounting, water-balance computation, work-order target resolution — always evaluate against the network's currently `PUBLISHED` topology. Second, the **live monitoring loop** must remain robust under partial sensor failure, clock drift across remote devices, and the operational reality that crews and supervisors collaborate but must never short-circuit safety controls; segregation of duties is enforced both at the topology-governance level and at the repair-verification level.

Test-time clock progression is explicit. Because device-offline detection, reading archive tiering, and reading-timestamp validity all depend on the network's notion of "now", the API exposes a deterministic clock-advance capability that drives time-gated sweeps. This makes the system fully reproducible under automated test fixtures while preserving wall-clock-like semantics in production.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. Missing or empty values on either header produce `ERR_UNAUTHENTICATED` with HTTP 401. When the role does not include the requested operation in its permission matrix, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

There are exactly six roles, and their names are case-sensitive:

- `TopologyEngineer` — designs and submits pipeline topology versions; creates DMAs and adds nodes and segments to `DRAFT` versions.
- `TopologyApprover` — approves, rejects, or rolls back published topology versions; also creates new `Network` tenants. May not approve a version they themselves submitted.
- `ControlOperator` — runs the live monitoring loop: ingests sensor readings, acknowledges, resolves and suppresses alerts, opens and narrows investigations, dispatches technicians, runs water-balance reports, and advances the test clock.
- `MaintenanceSupervisor` — owns the repair workflow: creates, assigns, cancels and verifies `WorkOrder` records.
- `Technician` — the field worker; requests parts, starts work, and submits repair records on `WorkOrder` rows assigned to them.
- `Auditor` — read-only access across the API plus exclusive access to the audit log and sync-event streams.

All six roles use opaque identifiers: when `X-User-Role` is any of `TopologyEngineer`, `TopologyApprover`, `ControlOperator`, `MaintenanceSupervisor`, `Technician`, or `Auditor`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity row. The server records `X-User-ID` onto resources where a scaffold transition writes it — for example, `submitted_by` and `reviewed_by` on `TopologyVersion`, `acknowledged_by` on `Alert`, `assigned_technician_id` on `WorkOrder` and `LeakInvestigation`, and `actor_id` on `AuditLog` — but it does not compare `X-User-ID` to any entity's `id` field for identity resolution. Ownership constraints in this system are expressed as field equality against these stored opaque IDs (e.g., a technician's `X-User-ID` must equal `WorkOrder.assigned_technician_id` when they request parts, start work, or complete it).

Two segregation-of-duties rules apply across the API and both surface as `ERR_SEGREGATION_OF_DUTIES` with HTTP 403. First, the `TopologyApprover` who approves or rejects a `TopologyVersion` must not be the same `X-User-ID` recorded in that version's `submitted_by`. Second, the `MaintenanceSupervisor` who verifies a `WorkOrder` must not be the same `X-User-ID` recorded in that order's `assigned_technician_id`.

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

All list endpoints accept `limit` and `offset` query parameters. The default `limit` is 10; clients may supply values from a minimum of 1 to a maximum of 100. The default `offset` is 0. Results are sorted by `created_at` in ascending order. The response `meta` block carries `limit`, `offset`, `total_count`, and `has_more` so a client can detect whether further pages remain.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most entities — `Network`, `TopologyVersion`, `DMA`, `Device`, `Alert`, `LeakInvestigation`, `WorkOrder` — carry the standard quartet: a server-minted `id` rendered as a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp that refreshes on every mutation, and a monotonically increasing integer `version` that increments on every mutation. Timestamps are ISO 8601 UTC strings with three fractional digits.

Four entities are append-only and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent on `PipelineNode`, `PipelineSegment`, `Reading`, `WaterBalanceReport`, `SyncEvent`, and `AuditLog`. (`WaterBalanceReport` records a `published_at` timestamp set at finalization and is immutable from that point on.)

Optimistic concurrency control applies to PATCH endpoints. A client supplies the `version` field they last observed; if it matches the stored value, the write proceeds and `version` increments by one. If the client supplies a `version` that no longer matches, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. The `version` field is optional on the request body — omitting it skips the check entirely and accepts the write unconditionally.

### 2.5. Test Clock and Time-Gated Sweeps

The system runs on a deterministic logical clock per `Network`, exposed as `clock_epoch_ms` (milliseconds since the Unix epoch). The clock starts at server wall-clock time when a network is created and only advances through an explicit clock-advance capability on the network, by a positive number of milliseconds passed as `advance_ms`. Advancing the clock triggers three sweeps in order: device-offline detection per the `device_offline_detection` rule (any `ACTIVE` `Device` whose missed-poll count crosses the offline threshold transitions to `OFFLINE`); reading archive-tier re-evaluation per the `reading_archive_tier` rule (each `Reading.archive_tier` is recomputed and may advance monotonically from `HOT` through `WARM` to `COLD`); and alert suppression for any open `Alert` whose `trigger_device_id` has just gone `OFFLINE` (those alerts transition to `SUPPRESSED` with `resolution_note` recorded as `DEVICE_OFFLINE`).

### 2.6. Numeric Precision and Rounding

Numeric outputs follow rule-specific precision contracts, with round-half-up as the universal rounding direction. Percentages reported by alert classification (the deviation percentage between a reading and its baseline, and the ratio for flow spikes) are rounded to two decimal places. The non-revenue water percentage `nrw_pct` is rounded to two decimal places. All cubic-meter quantities on `WaterBalanceReport` — `input_volume_m3`, `billed_consumption_m3`, `unbilled_authorized_m3`, `apparent_loss_m3`, `real_loss_m3` — are rounded to three decimal places. Loss and flow values on a `LeakInvestigation` (`water_balance_loss_lps`, `min_night_flow_lps`) are rounded to three decimals; head-loss intermediates used in pressure-gradient analysis are rounded to two decimals. Quantities expressed in integer seconds (clock advances, polling intervals, dedup windows, archive thresholds) are integer arithmetic with no rounding.

### 2.7. Nested Resource Path Resolution

Many endpoints are nested under `/networks/{network_id}/...` and further nested under `dmas/{dma_id}`, `devices/{id}`, `topology-versions/{id}`, `alerts/{id}`, `investigations/{id}`, or `work-orders/{id}`. Path-id resources are validated strictly left-to-right: if the `Network` does not exist, the request is rejected with `ERR_NOT_FOUND` before any child resource is even looked up; only once the `Network` is resolved does the system check the next path segment, and so on. The first missing resource in the path determines the 404 — downstream existence is never inspected when an upstream parent is absent.

### 2.8. DMA Posture and the Frozen Safety Rule

Each `DMA` carries a `status` field that takes one of three postures: `OPEN`, `RESTRICTED`, or `FROZEN`. The posture is system-managed and is driven by `open_critical_alert_count` — the live count of `Alert` rows whose `dma_id` matches this DMA, whose `severity` is `CRITICAL`, and whose `status` is one of `OPEN`, `ACKNOWLEDGED`, or `INVESTIGATING`. When `open_critical_alert_count` crosses from zero to one or more, the DMA transitions from `OPEN` to `RESTRICTED`; when it reaches three or more, the DMA transitions from `RESTRICTED` to `FROZEN`; when it drops below three the DMA transitions back from `FROZEN` to `RESTRICTED`; and when it falls to zero the DMA transitions back from `RESTRICTED` to `OPEN`. The two DMA posture transitions that cross the freeze boundary (`RESTRICTED → FROZEN` and `RESTRICTED → OPEN`) each emit an `AuditLog` row with `action` set to `DMA_POSTURE_CHANGED`, recording the from/to pair in the `detail` payload; the `OPEN → RESTRICTED` and `FROZEN → RESTRICTED` transitions do not emit audit rows. A DMA in `RESTRICTED` posture allows existing work to continue but blocks new repair-dispatch assignment to a technician. A DMA in `FROZEN` posture additionally blocks every mutation — every state-changing endpoint within the DMA's scope — except topology rollback and clock advance; any blocked mutation is rejected with `ERR_DMA_FROZEN` and HTTP 409. When `FROZEN` is entered, every non-terminal `WorkOrder` in the DMA that is currently `IN_PROGRESS` pauses by transitioning to `AWAITING_VERIFICATION` with its `verification_failure_count` unchanged.

### 2.9. Audit Logging and System Sync

Two append-only streams capture the lifecycle of governed actions. `AuditLog` rows are written for nine governed `action` values: `TOPOLOGY_SUBMITTED`, `TOPOLOGY_PUBLISHED`, `TOPOLOGY_REJECTED`, `TOPOLOGY_ROLLED_BACK`, `ALERT_ACK`, `ALERT_SUPPRESSED`, `ALERT_RESOLVED`, `DMA_POSTURE_CHANGED`, and `WORK_ORDER_VERIFIED`. Each row carries `actor_role`, `actor_id` (taken from the request headers at the moment of action), the `resource_kind` (the entity name of the affected resource), the `resource_id`, a `detail` object with before/after fragments of state, and a `recorded_at` server timestamp. `SyncEvent` rows are emitted to external systems on five `event_type` values: `TOPOLOGY_PUBLISHED`, `ALERT_OPENED`, `ALERT_RESOLVED`, `WORK_ORDER_CLOSED`, and `WATER_BALANCE_PUBLISHED`. Every `SyncEvent` carries `network_id`, `target_system` (one of `BILLING`, `GIS`, or `IM`), `resource_kind`, `resource_id`, a `payload` snapshot, an `emitted_at` server time, and a `sequence_no` that is monotonic within a given `(network_id, target_system)` pair to support deterministic replay ordering. Publishing or rolling back a topology emits three sync events — one each to `BILLING`, `GIS`, and `IM`. Resolving an alert emits two sync events — one to `BILLING` and one to `IM`. Verifying and closing a work order emits two sync events — one to `BILLING` and one to `IM`. Publishing a water-balance report emits one sync event — to `BILLING`.

## 3. Business Logic & Workflows

### 3.1. Network Tenancy and the Logical Clock

A `Network` represents a single utility tenant in the system. A `TopologyApprover` creates a network by supplying a display `name`, a globally unique `utility_code` that identifies the operating entity, and optionally a `nrw_target_pct` to express the utility's non-revenue-water goal (for example, `12.0` means a target of 12.0%). At creation, the network's `active_topology_version_id` is `null` (no topology has been published yet) and `clock_epoch_ms` is initialized to the server wall-clock time at creation, expressed as integer milliseconds since the Unix epoch.

The clock can only move forward, and it only moves through an explicit operator action. A `ControlOperator` invokes an admin-only test-driving capability on the network with an `advance_ms` body parameter, which must be strictly greater than zero. The clock-advance triggers a sweep of every `ACTIVE` `Device` against its expected next polling time, recomputes archive tiers for affected readings, and propagates the consequences of any device that has just gone offline (open alerts on that device flip to `SUPPRESSED` with `resolution_note='DEVICE_OFFLINE'`).

### 3.2. Topology Versioning and Governance

A pipeline network's physical layout is described as a directed graph of nodes and segments, but the graph itself is never edited in place. Instead, a `TopologyEngineer` opens a new `DRAFT` `TopologyVersion`, providing a `change_summary` describing what they intend to change and optionally a `parent_version_id` to record the lineage of the draft. `version_number` is assigned monotonically per network, starting at 1 on the first draft; only the very first draft of a network may omit `parent_version_id`.

Within a `DRAFT`, the engineer adds `PipelineNode` rows — each carrying the `topology_version_id` of the draft it belongs to (a node belongs to exactly one version) and a `node_code` that is stable across versions, a `kind` drawn from the closed set `JUNCTION`, `VALVE`, `PUMP_STATION`, `RESERVOIR`, or `CUSTOMER_TAP`, a geographic `latitude` and `longitude` on the WGS-84 datum, an `elevation_m` value in meters above sea level that is used later by pressure-gradient analysis, and (for nodes of `kind` `VALVE`) a `valve_default_open` flag indicating its default position. A node references its containing DMA by `dma_id`; the only `kind` for which `dma_id` may be `null` is `RESERVOIR`, because reservoirs sit upstream of every DMA. Segments are then added by specifying a `segment_code` unique within the draft, a `from_node_code` and a `to_node_code` (which must both reference nodes in the same topology version and must not be equal), a strictly positive `length_m`, a strictly positive `diameter_mm`, and a `material` drawn from `PVC`, `DUCTILE_IRON`, `STEEL`, or `HDPE`. The `dma_id` of a segment is computed by inheriting from the `from_node_code`; segments whose endpoints lie in different DMAs are marked as boundary segments with `dma_id` set to `null`. A segment endpoint that does not resolve to a node in the same topology version, or a segment with identical `from_node_code` and `to_node_code`, is rejected with `ERR_TOPOLOGY_DANGLING_REFERENCE` and HTTP 422. This same dangling-reference rule applies at submission time as well — submission verifies that every segment's endpoints still resolve within the version.

A `TopologyEngineer` submits a draft for review, transitioning the version from `DRAFT` to `UNDER_REVIEW`. Submission has four preconditions: the version must contain at least one `PipelineNode` and at least one `PipelineSegment`; every segment's `from_node_code` and `to_node_code` must reference nodes in the same version; every non-`RESERVOIR` node must reference a DMA whose posture is `OPEN` or `RESTRICTED` (a `FROZEN` DMA causes submission to fail); and the network must have no other `TopologyVersion` already in `UNDER_REVIEW` status. The submission writes the engineer's `X-User-ID` to `submitted_by` on the version and emits an `AuditLog` row with `action=TOPOLOGY_SUBMITTED`. If a second engineer attempts to submit a different draft for the same network while one is already `UNDER_REVIEW`, the second submission is rejected with `ERR_REVIEW_IN_PROGRESS` and HTTP 409. When two engineers race to submit different drafts of the same network simultaneously, the system serializes the writes such that at most one ever lands in `UNDER_REVIEW`; the loser receives `ERR_REVIEW_IN_PROGRESS` and HTTP 409.

Approval by a `TopologyApprover` transitions the version from `UNDER_REVIEW` to `PUBLISHED`. The approver's `X-User-ID` must differ from the version's `submitted_by` value, and every DMA referenced by this version must be `OPEN` or `RESTRICTED` (no `FROZEN` DMAs). On approval, four cascades fire. First, any other version of the same network that was previously in `PUBLISHED` status transitions to `SUPERSEDED`, and the network's `active_topology_version_id` is repointed to the newly approved version. Second, any `Device` whose `mounted_on_node_code` no longer exists in the new active version transitions back to `PROVISIONED` with its `mounted_on_node_code` cleared. Third, any open `Alert` whose `trigger_device_id` is on a pipeline segment that has been removed in the new version transitions to `SUPPRESSED` with `resolution_note='TOPOLOGY_SUPERSEDED'`. Fourth, three `SyncEvent` rows are emitted with `event_type=TOPOLOGY_PUBLISHED` — one each to `BILLING`, `GIS`, and `IM` — and an `AuditLog` row is written with `action=TOPOLOGY_PUBLISHED`. The system also records `reviewed_by` from the approver's `X-User-ID` and stamps `published_at` with the server-time ISO 8601 UTC instant of publication.

Rejection by a `TopologyApprover` transitions the version from `UNDER_REVIEW` to `REJECTED`. The approver's `X-User-ID` must differ from `submitted_by`, and the request body must supply a non-empty `rejection_reason`, which is stored on the version. An `AuditLog` row is written with `action=TOPOLOGY_REJECTED`. The system blocks the same actor from both submitting and approving (or rejecting) the same version: the rejection comes back as `ERR_SEGREGATION_OF_DUTIES` with HTTP 403.

When two `TopologyApprover` actors race to act on the same `UNDER_REVIEW` version — either both approving simultaneously, or one approving while another rejects — the system serializes on the version's `status`. Exactly one transition wins; the loser sees `ERR_INVALID_STATE` with HTTP 409 because the version is no longer in `UNDER_REVIEW`.

A `TopologyApprover` may also roll back to an earlier `SUPERSEDED` version, which republishes it: the current `PUBLISHED` version transitions to `SUPERSEDED`, the target version transitions from `SUPERSEDED` to `PUBLISHED`, and the network's `active_topology_version_id` is repointed. Rollback requires that a currently `PUBLISHED` version exists (one cannot rollback to no active topology) and that no open `WorkOrder` references a `target_segment_code` that exists in the target version but not in the current `PUBLISHED` version — such a rollback would create a dangling repair, and the operation is rejected with `ERR_TOPOLOGY_ROLLBACK_BLOCKED` and HTTP 409. On successful rollback, an `AuditLog` row is written with `action=TOPOLOGY_ROLLED_BACK` and three `SyncEvent` rows with `event_type=TOPOLOGY_PUBLISHED` are emitted to `BILLING`, `GIS`, and `IM`. Rollback is one of the only two mutations permitted while a DMA is `FROZEN` — the other is clock advance.

### 3.3. DMAs and the Posture Cascade

A `DMA` (district metering area) carves a region of the network into a self-contained input-output zone. A `TopologyEngineer` creates a DMA by supplying a `dma_code` unique within the network, a display `name`, and optionally the `inlet_node_codes` and `outlet_node_codes` arrays — the inlets are the nodes whose sensors count toward input reconciliation, the outlets are the boundary nodes through which water leaves the zone. A new DMA always initializes with `status=OPEN`.

The posture transitions are driven by the live count of critical, unresolved alerts, captured on `open_critical_alert_count`. The recomputation of this count happens whenever an alert in the DMA opens, is acknowledged, resolves, is suppressed, or transitions out of one of the contributing states; whenever the count crosses a threshold, the posture moves accordingly per §2.8. Posture cascades are reentrant: resolving a critical alert may take `open_critical_alert_count` from 3 down to 2 (which transitions a `FROZEN` DMA back to `RESTRICTED`), and resolving the last of them returns the DMA to `OPEN`.

### 3.4. Devices, Readings, and the Live Monitoring Loop

A `Device` represents a single physical sensor on the pipeline network. A `ControlOperator` creates a device by supplying a `device_code` that is unique within the network, optionally a `mounted_on_node_code` that references a node in the network's `active_topology_version_id` (spare devices may be created without a mount), a `protocol` chosen from `NB_IOT`, `LORA`, or `WIRED`, a `sensor_kind` chosen from `PRESSURE` (reporting kPa), `FLOW` (reporting liters per second), or `METER` (reporting cumulative cubic meters), a polling cadence `polling_interval_s` expressed in integer seconds, and the lower and upper bounds of physically plausible readings `valid_range_min` and `valid_range_max`. The polling interval must lie between 30 and 3600 seconds inclusive, and the lower bound must be strictly less than the upper bound; violations are rejected with `ERR_DEVICE_CONFIG_INVALID` and HTTP 422. The same constraint applies to PATCH updates of these fields. The device enters life in `status=PROVISIONED`.

A device transitions from `PROVISIONED` to `ACTIVE` when an operator activates it. Activation requires that `mounted_on_node_code` is non-null and resolves to a node in the network's currently `PUBLISHED` topology version; a device with no mount, or one whose mount no longer exists in the active version, is rejected with `ERR_DEVICE_UNMOUNTED` and HTTP 409. The configuration constraint that `valid_range_min` is strictly less than `valid_range_max` is rechecked at activation time as well.

A patch capability lets an operator update `polling_interval_s`, `valid_range_min`, `valid_range_max`, or `mounted_on_node_code`, subject to optimistic concurrency on `version`. When two operators race a stale write against a fresh one, the stale write is rejected with `ERR_VERSION_CONFLICT` and HTTP 409.

Ingest is the high-volume operation in this system. An operator posts a sensor reading carrying `observed_at` (the device-side timestamp, in ISO 8601 UTC), `raw_value` (the value as reported by the device), and optionally an `idempotency_key` and a `strict_mode` query flag. The server stamps `ingested_at` with its own server time. Two temporal checks gate the reading: `observed_at` must fall within a backdate window of seven days behind the current `clock_now` and a forward window of 60 seconds ahead (in other words, the difference `clock_now - observed_at` must be at most 604800 seconds, and `observed_at - clock_now` must be at most 60 seconds), or the reading is rejected with `ERR_READING_TIMESTAMP_OUT_OF_RANGE` and HTTP 422. The raw value is compared against the device's `valid_range_min` and `valid_range_max`: a value strictly within the range (lower bound inclusive, upper bound inclusive) is `ACCEPTED`; a value outside is normally stored with `validity` set to `ABNORMAL_OUT_OF_RANGE` but does not update the device's `last_reading_at` or `last_reading_value`. When the operator passes the `strict_mode` flag set to true, an out-of-range raw value is instead rejected with `ERR_READING_OUT_OF_RANGE` and HTTP 422. Other abnormal classifications are computed similarly: a reading whose `observed_at` predates the device's most recent `ACCEPTED` reading is flagged `ABNORMAL_STALE`; a reading that exactly duplicates a prior reading on the same device by `(observed_at, raw_value)` is flagged `ABNORMAL_DUPLICATE`. All abnormal readings are persisted (so audits remain complete) but do not update the device's last-reading state.

The `idempotency_key` provides exactly-once ingest semantics. When two clients submit identical `(device_id, idempotency_key)` pairs simultaneously, at most one `Reading` row is created; the duplicate request returns the original `Reading` with the same `id` as the first, the response carries HTTP 200 (not 201, because no new resource was created), and the response surfaces `ERR_DUPLICATE_READING` as the idempotency-replay signal.

When an `ACCEPTED` reading lands, the device's `last_reading_at` and `last_reading_value` advance, `missed_polls_consecutive` resets to 0, and — if the device was in `OFFLINE` — the device transitions back to `ACTIVE`.

A reading's `archive_tier` is computed at ingest time and re-evaluated on every clock advance. The age of a reading is the difference between `clock_now` and `ingested_at`. A reading with age strictly less than 86400 seconds is `HOT`; from 86400 seconds (inclusive) to 2592000 seconds (exclusive) it is `WARM`; at 2592000 seconds and beyond it is `COLD`. Tier transitions are strictly monotonic in the direction `HOT → WARM → COLD` — a tier never regresses, even if a clock advance somehow re-evaluated an earlier window.

A device transitions from `ACTIVE` to `OFFLINE` when a clock-advance sweep detects too many missed polls. The expected next poll for a device is `last_reading_at + polling_interval_s` seconds; if the device has not yet recorded an `ACCEPTED` reading, the baseline is `created_at + polling_interval_s`. The number of missed polls is computed as the floor of `(clock_now − expected_next_poll) / polling_interval_s`, plus one, whenever `clock_now` is at or past `expected_next_poll`; if `clock_now` is still strictly before `expected_next_poll`, missed polls is 0. The boundary is inclusive: a `clock_now` exactly equal to `expected_next_poll` counts as one missed poll. When `missed_polls_consecutive` reaches 3 or more on a device whose status is currently `ACTIVE`, the device transitions to `OFFLINE`. Upon entering `OFFLINE`, any open `Alert` whose `trigger_device_id` equals this device and whose `alert_kind` is `PRESSURE_LOW`, `PRESSURE_HIGH`, or `FLOW_SPIKE` transitions to `SUPPRESSED` with `resolution_note='DEVICE_OFFLINE'`. The reverse — from `OFFLINE` back to `ACTIVE` — happens automatically when the device next posts an `ACCEPTED` reading, which also resets `missed_polls_consecutive` to 0.

A device may be decommissioned by an operator from either `ACTIVE` or `OFFLINE`, transitioning to `DECOMMISSIONED`. From `ACTIVE`, the precondition is that no `OPEN` or `ACKNOWLEDGED` `Alert` references this device; from `OFFLINE`, no such precondition applies (the device is already known not to be reporting). Decommissioning from `ACTIVE` carries one cascade: every non-terminal `LeakInvestigation` whose parent `Alert.trigger_device_id` equals this device, and whose current status is `OPEN` or `NARROWED`, transitions to `FALSE_POSITIVE`.

### 3.5. Anomaly Detection, Severity, and Alert Aggregation

When an `ACCEPTED` reading lands that breaches a threshold for its sensor kind, an `Alert` is generated. The `alert_kind` is determined by the breach scenario: `PRESSURE_HIGH` and `PRESSURE_LOW` flag a `PRESSURE` device whose reading deviates from a baseline above or below; `FLOW_SPIKE` flags a `FLOW` device whose reading exceeds its baseline by a multiplicative factor; `FLOW_NIGHT_HIGH` flags an inlet flow that does not drop appropriately during the nighttime minimum-flow window; and `CROSS_SENSOR_DISAGREEMENT` flags a reading that disagrees with peer sensors in the same DMA. Every alert captures, at trigger time, the `baseline_used` object — recording whether the baseline was `STATIC` or `DYNAMIC`, the numeric `threshold` value the system compared against, the `hour_of_day`, and the `day_of_week` — so subsequent review can reconstruct exactly what was evaluated.

Severity is computed as follows. For `PRESSURE_LOW` and `PRESSURE_HIGH`, the deviation percentage is `|reading − baseline| / baseline × 100`, rounded to two decimals. When this percentage is strictly less than 15.0, the severity is `INFO`; from 15.0 (inclusive) to 30.0 (exclusive) the severity is `WARNING`; at 30.0 and above the severity is `CRITICAL`. For `FLOW_SPIKE`, the comparison is a ratio: the reading divided by the baseline, rounded to two decimals. When this ratio is strictly less than 1.5 the severity is `INFO`; from 1.5 (inclusive) to 2.5 (exclusive) it is `WARNING`; at 2.5 and above it is `CRITICAL`. For `CROSS_SENSOR_DISAGREEMENT`, the system counts how many peer sensors in the same DMA report a value that deviates from the cluster median by at least 10.0 percent. When exactly one peer disagrees the severity is `WARNING`; when two or more peers disagree the severity is `CRITICAL`.

The baseline against which a pressure or flow reading is compared is itself either dynamic or static. When a device has accumulated at least 168 hours of `ACCEPTED` readings within the current `(hour_of_day, day_of_week)` bucket — that is, at least one week's worth of readings binned to the right time of week — the baseline is `DYNAMIC` and is computed as the arithmetic mean of `ACCEPTED` readings in that bucket over the past 28 days. When fewer than 168 hours of data exist in the bucket, the baseline falls back to `STATIC` and is the midpoint of `valid_range_min` and `valid_range_max`. The same deviation-percentage formula applies in both cases.

Once an alert is open, additional breach readings from the same device with the same `alert_kind` are merged in rather than spawning duplicate alerts. The dedup rule is time-windowed: when a new breach reading arrives and there is a latest non-terminal `Alert` for this `(trigger_device_id, alert_kind)` pair, the system compares the new reading's `ingested_at` to the alert's `last_breach_at`. If the difference is at most 900 seconds (the 15-minute dedup window, with the equality boundary inclusive), the new reading is merged: `occurrence_count` is incremented by 1, `last_breach_at` is advanced to the new reading's `ingested_at`, and severity is recomputed; severity may upgrade — for example, an `INFO` alert may upgrade to `WARNING` and then to `CRITICAL` — but it may not downgrade once the alert has been acknowledged. If the time gap strictly exceeds 900 seconds, a fresh `Alert` is opened with `occurrence_count=1`, `first_breach_at` set from the reading's `observed_at`, and `last_breach_at` set from the reading's `ingested_at`.

Every newly opened alert (not aggregations) emits a `SyncEvent` with `event_type=ALERT_OPENED`. The alert's `dma_id` is derived at trigger time from the mounted node of the device that produced the reading; this snapshot is durable, so subsequent topology changes do not retro-edit historical alerts.

### 3.6. Alert Triage Workflow

A `ControlOperator` walks an alert through a triage workflow. An alert begins life in `OPEN`. Acknowledging the alert advances it from `OPEN` to `ACKNOWLEDGED`, records the operator's `X-User-ID` to `acknowledged_by`, and writes an `AuditLog` row with `action=ALERT_ACK`. An alert classified as `INFO` cannot be acknowledged — `INFO` alerts auto-resolve and reject acknowledgement attempts as invalid-state transitions. When two operators race to acknowledge the same `OPEN` alert simultaneously, the system serializes on the alert's `status`: the first writer wins, and the second receives `ERR_INVALID_STATE` with HTTP 409.

From `ACKNOWLEDGED`, the operator may either resolve the alert directly (when investigation is unnecessary) or open a `LeakInvestigation`, advancing the alert to `INVESTIGATING`. Opening an investigation requires that the alert's severity is `WARNING` or `CRITICAL` and that no existing non-terminal `LeakInvestigation` already references this alert; a new investigation is created in status `OPEN`, with `alert_id` and `dma_id` snapshotted from the parent alert. Resolution from `INVESTIGATING` to `RESOLVED` requires either that the linked investigation has reached `CONFIRMED_LEAK` or `FALSE_POSITIVE`, or that a `CLOSED_VERIFIED` `WorkOrder` exists for the same investigation; the request body must also supply a `resolution_note`. The resolution side-effects are: the DMA's `open_critical_alert_count` is recomputed (which may transition the DMA's posture), a `SyncEvent` row is emitted with `event_type=ALERT_RESOLVED` to `BILLING` and to `IM`, and an `AuditLog` row is written with `action=ALERT_RESOLVED`. Resolution from `OPEN` directly to `RESOLVED` is permitted only for `INFO` alerts and likewise requires `resolution_note`; this path writes the `ALERT_RESOLVED` audit row.

Suppression takes an alert directly to `SUPPRESSED` from either `OPEN` or `ACKNOWLEDGED`. From `OPEN`, the request body must supply a `resolution_note`. Suppression always recomputes the DMA's `open_critical_alert_count` (which may flip DMA posture) and writes an `AuditLog` row with `action=ALERT_SUPPRESSED`.

### 3.7. Leak Localization and Investigation Narrowing

A `LeakInvestigation` begins life in `OPEN`. Narrowing the investigation runs three coupled computations and, on success, populates `suspected_segment_codes` and advances the investigation from `OPEN` to `NARROWED`. The narrowing endpoint may only be invoked when the server has computed at least one of `min_night_flow_lps` or `water_balance_loss_lps`; otherwise the request is rejected with `ERR_INVESTIGATION_NO_SIGNAL` and HTTP 409. The DMA must also not be `FROZEN`.

The first computation produces `pressure_gradient_anomaly_segments`. For every `PipelineSegment` in the active topology whose two endpoints both carry an `ACTIVE` pressure sensor, the system computes the expected hydraulic head loss from the Hazen-Williams relation: `HAZEN_WILLIAMS_K` (10.67) multiplied by `length_m`, divided by `diameter_mm` raised to the 4.87 power, multiplied by the flow estimate raised to the 1.85 power. The flow estimate is the median of `FLOW` device readings in the segment's DMA over the past 3600 seconds (the look-back window), or 0 when no `FLOW` devices report. The measured head loss is the pressure-sensor difference `P_from − P_to` plus the elevation difference between the endpoints multiplied by 9.81 (the kPa-per-meter conversion factor). A segment is included in the anomaly set when the difference between measured and expected head loss is at least 25.0 percent of the expected head loss — that is, when `measured_head_loss − expected_head_loss` is greater than or equal to `expected_head_loss × 25.0 / 100`. Head-loss intermediates are rounded to two decimals.

The second computation produces `min_night_flow_lps`. The system identifies the inlet `FLOW` devices for the DMA, gathers their `ACCEPTED` readings from the past 7 nights, computes the hourly average flow during the local-time window 02:00 to 04:00 each night (14 hours in total), and reports the minimum across all those hourly averages.

The third computation produces `water_balance_loss_lps` by reading the most recent `WaterBalanceReport` for the DMA whose window length was exactly one day (86400 seconds), converting its `real_loss_m3` to liters per second using the relation `real_loss_m3 × 1000 / 86400`.

The final step computes `suspected_segment_codes`. The primary result is the intersection of `pressure_gradient_anomaly_segments` with the set of segments reachable downstream of the DMA's inlet nodes following the directed graph edges (in the gradient-driven variant, when the gradient anomaly set is non-empty and `min_night_flow_lps` is at least 2.0 liters per second). When the intersection is empty but the night-flow signal is at or above 2.0 liters per second (the night-flow-only variant), the fallback result is the set of segments downstream of the inlet that border the lowest-pressure node, ranked by `segment_code` in ascending order. All loss and flow values are rounded to three decimals.

From `NARROWED`, the operator dispatches a technician, advancing the investigation to `DISPATCHED`. Dispatch requires that `suspected_segment_codes` is non-empty, that the request body assigns an `assigned_technician_id` that is owned by an actor whose role is `Technician`, and that the DMA's status is `OPEN` or `RESTRICTED` (FROZEN blocks dispatch). The dispatch side-effects are: `assigned_technician_id` is stored on the investigation, and a new `WorkOrder` is created with `origin=INVESTIGATION` and `status=NEW`, with its priority computed (see §3.8). The dispatch endpoint also accepts a `target_segment_code` to seed the work order's target.

The terminal transitions on a `LeakInvestigation` are system-driven. When the linked `WorkOrder` is verified with `repair_record.leak_class` in `LEAK_CONFIRMED`, `JOINT_FAILURE`, or `PIPE_BURST`, the investigation transitions from `DISPATCHED` to `CONFIRMED_LEAK`. When the linked work order is verified with `repair_record.leak_class=NO_LEAK_FOUND`, the investigation transitions from `DISPATCHED` to `FALSE_POSITIVE`. Additionally, an `OPEN` investigation transitions to `FALSE_POSITIVE` if its parent `Alert` is `SUPPRESSED` or its trigger `Device` is `DECOMMISSIONED`; a `NARROWED` investigation transitions to `FALSE_POSITIVE` if its parent `Alert` is `SUPPRESSED`.

### 3.8. Work Order Priority, Repair Workflow, and Verification

A `WorkOrder` may originate in three ways, captured as `origin`: `ALERT_AUTO` (created directly by a `MaintenanceSupervisor` from an alert), `INVESTIGATION` (auto-created by the dispatch step on an investigation), or `INSPECTION_FINDING` (created from a manual field inspection by the supervisor). When `origin=ALERT_AUTO`, the supervisor must supply `alert_id`; when `origin=INVESTIGATION`, `investigation_id` is required. Every work order carries a `target_segment_code` referencing the segment scheduled for repair, which must resolve to a segment in the network's `active_topology_version_id` at creation time; failure is `ERR_WORK_ORDER_SEGMENT_MISSING` with HTTP 422. The same target-segment check is repeated at assignment time.

A work order's `priority` is computed at creation and bucketed into `P1`, `P2`, or `P3`. The computation is executed in a pinned five-step sequence so that an audit can reconstruct it deterministically. First, a severity score is computed: 10 if the parent alert (when `origin` is `ALERT_AUTO` or `INVESTIGATION`) has severity `CRITICAL`, 5 if `WARNING`, and 0 if `INFO` or if the order has no parent alert. Second, a DMA score is computed: 5 if the DMA's `open_critical_alert_count` is at least 3, otherwise 2 if it is at least 1, otherwise 0. Third, a leak score is computed: 8 when `origin=INVESTIGATION` and the parent investigation reports a `water_balance_loss_lps` of at least 1.0, otherwise 0. Fourth, a downstream-customer score is computed: count the `PipelineNode` rows of `kind=CUSTOMER_TAP` that are reachable downstream of `target_segment_code` in the active topology, divide by 50, and round up to the next whole number. Fifth, the total score is the sum of severity, DMA, leak, and downstream-customer scores. The bucket assignment: a total score of 15 or more is `P1`; a total score from 8 (inclusive) up to but not including 15 is `P2`; a total score strictly less than 8 is `P3`. All arithmetic is integer; the only rounding is the ceiling on the downstream-customer bucket.

The lifecycle of a work order proceeds along `NEW → ASSIGNED → (PARTS_PENDING →) IN_PROGRESS → AWAITING_VERIFICATION → CLOSED_VERIFIED`, with `CLOSED_REJECTED` and `CANCELLED` as alternative terminal states. A `MaintenanceSupervisor` assigns a technician, advancing the order from `NEW` to `ASSIGNED`. Assignment requires the DMA's status to be `OPEN` (a `RESTRICTED` DMA blocks new assignment), the `target_segment_code` to still resolve to a segment in the active topology version, and the `assigned_technician_id` to belong to a known `Technician` role. Two supervisors racing to assign the same `NEW` work order simultaneously serialize on the order's `status`: exactly one assignment succeeds, and the loser receives `ERR_INVALID_STATE` with HTTP 409. The supervisor's action writes an `AuditLog` row.

From `ASSIGNED`, the technician may request parts, transitioning the order to `PARTS_PENDING`. Requesting parts requires the technician's `X-User-ID` to equal `WorkOrder.assigned_technician_id` and the supplied `parts_required` array to be non-empty (each element is a `{part_code, quantity}` object). From `PARTS_PENDING`, the technician starts work, transitioning to `IN_PROGRESS` and stamping `started_at` with the current clock time; if no parts are needed, the technician may also start directly from `ASSIGNED` to `IN_PROGRESS`, but only when `parts_required` is empty (or absent on the order). Starting work requires the DMA's status not to be `FROZEN` and again confirms the technician identity matches `assigned_technician_id`.

Completion transitions the order from `IN_PROGRESS` to `AWAITING_VERIFICATION`. The technician submits a `repair_record` object — carrying free-form notes such as a `summary`, a `valve_isolations_used` list, and a categorical `leak_class` — which is stored on the order. The completion stamps `completed_at` with the current clock time. The technician's `X-User-ID` must equal `assigned_technician_id`.

Verification is performed by a `MaintenanceSupervisor` who is not the same person as the assigned technician (a violation produces `ERR_SEGREGATION_OF_DUTIES` with HTTP 403). The supervisor passes an `outcome` of `PASS` or `FAIL`, and optionally a `verification_note`. The system additionally requires that at least one `ACCEPTED` `Reading` has been ingested after `completed_at` from a `Device` mounted on the repaired segment; this enforces post-repair instrumentation of the fix. On `outcome=PASS`, the order transitions to `CLOSED_VERIFIED`, `verified_at` is stamped, an `AuditLog` row is written with `action=WORK_ORDER_VERIFIED`, a pair of `SyncEvent` rows with `event_type=WORK_ORDER_CLOSED` are emitted to `BILLING` and `IM`, and (when `origin=INVESTIGATION`) the parent `LeakInvestigation` advances per `repair_record.leak_class`. On the first `outcome=FAIL` (when `verification_failure_count` is strictly less than 1), the order returns to `IN_PROGRESS` and `verification_failure_count` is incremented to 1; on a second `outcome=FAIL` (when `verification_failure_count` is at least 1), the order transitions to `CLOSED_REJECTED`, `verification_failure_count` is incremented to 2, and an `AuditLog` row is written.

Cancellation is available from any pre-`IN_PROGRESS` state — that is, from `NEW`, `ASSIGNED`, or `PARTS_PENDING` — and is performed by a `MaintenanceSupervisor`. Cancellation has no preconditions.

### 3.9. DMA Water Balance and Non-Revenue Water

A `WaterBalanceReport` reconciles, over a fixed-length window, the water that enters a DMA against the water that has been accounted for, and partitions the unaccounted portion into apparent versus real losses. A `ControlOperator` creates a report by supplying `window_start` and `window_end`, both expressed as ISO 8601 UTC timestamps. The window length — that is, `window_end − window_start` — must equal exactly one hour (3600 seconds), one day (86400 seconds), or one week (604800 seconds); `window_end` must be strictly greater than `window_start`; failure surfaces as `ERR_INVALID_WINDOW` with HTTP 422.

The computation uses only `ACCEPTED` readings; any `ABNORMAL_OUT_OF_RANGE`, `ABNORMAL_STALE`, or `ABNORMAL_DUPLICATE` reading is excluded. The window is closed-open: the start instant is inclusive and the end instant is strictly exclusive, so a reading observed exactly at `window_end` is not included in the integration. When two readings on the same device share an `observed_at`, the system selects the one with the lower `ingested_at` to make the integration deterministic.

`input_volume_m3` is the sum, over the DMA's inlet devices, of the integral of `flow_lps` across the window, treating the flow series as piecewise-constant between consecutive readings; the unit is converted from liters per second to cubic meters by dividing by 1000. `billed_consumption_m3` is the sum, over `METER` devices in the DMA tagged with `billed_flag` true, of the difference between the last and first meter readings in the window. `unbilled_authorized_m3` is the same difference computed for `METER` devices tagged `billed_flag` false and `authorized` true (for example, hydrant flushing). `apparent_loss_m3` represents the estimated meter inaccuracy plus unauthorized consumption and is computed as `input_volume_m3` multiplied by 0.04 (a fixed 4.0 percent apparent-loss rate). `real_loss_m3` is the physical leakage, computed as `input_volume_m3 − billed_consumption_m3 − unbilled_authorized_m3 − apparent_loss_m3`, with a floor of 0 (so a negative arithmetic result is clamped to 0). The non-revenue water percentage `nrw_pct` is `(input_volume_m3 − billed_consumption_m3) / input_volume_m3 × 100`, rounded to two decimal places. All cubic-meter quantities are rounded to three decimal places using round-half-up.

If `input_volume_m3` evaluates to zero — that is, no inlet device produced an `ACCEPTED` reading in the window — the request is rejected with `ERR_INSUFFICIENT_DATA` and HTTP 422 (this is also the rejection when no inlet device has at least one `ACCEPTED` reading in the window).

A report's window length classifies it for downstream archive tier and trend reporting. An hourly window report is intended for recent (HOT-tier) review; a daily window report is the canonical input for the non-revenue-water trend; a weekly window report aggregates seven daily reports by summing them rather than re-computing from raw readings, to avoid compounding rounding error.

When a report finalizes, its `published_at` timestamp is stamped, the report becomes immutable, and a `SyncEvent` row with `event_type=WATER_BALANCE_PUBLISHED` is emitted to `BILLING`.

### 3.10. Validation Ordering Across the API

When multiple validation checks could plausibly fire on the same request, the system evaluates them in a pinned priority order so the error surfaced is always the same. The order, from highest priority to lowest, is: authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); role permission for the endpoint (`ERR_FORBIDDEN`); existence of every path-id resource, evaluated strictly left-to-right (`ERR_NOT_FOUND`); current state of the target resource permitting the requested transition (`ERR_INVALID_STATE`); the DMA frozen safety rule that blocks all mutations except topology rollback and clock advance when the DMA is `FROZEN` (`ERR_DMA_FROZEN`); the segregation-of-duties rule on topology approve and reject (`ERR_SEGREGATION_OF_DUTIES`); the topology dangling-reference check on segment creation and submission (`ERR_TOPOLOGY_DANGLING_REFERENCE`); the device-mounted-on-known-node check on activation (`ERR_DEVICE_UNMOUNTED`); the reading-timestamp temporal-window check (`ERR_READING_TIMESTAMP_OUT_OF_RANGE`); the strict-mode reading-range check (`ERR_READING_OUT_OF_RANGE`); the at-most-one-review-in-progress check on submission (`ERR_REVIEW_IN_PROGRESS`); the segregation-of-duties rule on work-order verification (`ERR_SEGREGATION_OF_DUTIES` again, scoped to the verify path); the rollback-orphans-no-open-work check (`ERR_TOPOLOGY_ROLLBACK_BLOCKED`); the water-balance window-length check (`ERR_INVALID_WINDOW`); the water-balance non-zero-input check (`ERR_INSUFFICIENT_DATA`); the device-configuration range check (`ERR_DEVICE_CONFIG_INVALID`); the optimistic-concurrency check on PATCH endpoints (`ERR_VERSION_CONFLICT`); the work-order target-segment existence check (`ERR_WORK_ORDER_SEGMENT_MISSING`); and finally the investigation-narrowing signal-availability check (`ERR_INVESTIGATION_NO_SIGNAL`). Malformed JSON, missing required fields, type mismatches, or unknown enum values surface as `ERR_BAD_REQUEST` with HTTP 400.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; modifications, state transitions, and read endpoints return HTTP 200; idempotent replays of reading ingest return HTTP 200. The full request and response shapes for each endpoint are reconstructed by following the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/networks` | Create a `Network` (utility tenant) | `TopologyApprover` |
| GET | `/networks/{network_id}` | Get a `Network` | `TopologyEngineer`, `TopologyApprover`, `ControlOperator`, `MaintenanceSupervisor`, `Technician`, `Auditor` |
| POST | `/networks/{network_id}/_clock/advance` | Advance the test clock; drives device-offline and archive-tier sweeps | `ControlOperator` |
| POST | `/networks/{network_id}/topology-versions` | Create a `DRAFT` `TopologyVersion` | `TopologyEngineer` |
| GET | `/networks/{network_id}/topology-versions/{id}` | Read a `TopologyVersion` with nested nodes and segments | `TopologyEngineer`, `TopologyApprover`, `ControlOperator`, `Auditor` |
| POST | `/networks/{network_id}/topology-versions/{id}/nodes` | Add a `PipelineNode` to a `DRAFT` version | `TopologyEngineer` |
| POST | `/networks/{network_id}/topology-versions/{id}/segments` | Add a `PipelineSegment` to a `DRAFT` version | `TopologyEngineer` |
| POST | `/networks/{network_id}/topology-versions/{id}/submit` | Submit `DRAFT` for review | `TopologyEngineer` |
| POST | `/networks/{network_id}/topology-versions/{id}/approve` | Approve `UNDER_REVIEW` and publish | `TopologyApprover` |
| POST | `/networks/{network_id}/topology-versions/{id}/reject` | Reject `UNDER_REVIEW` | `TopologyApprover` |
| POST | `/networks/{network_id}/topology-versions/{id}/rollback` | Republish a `SUPERSEDED` version | `TopologyApprover` |
| POST | `/networks/{network_id}/dmas` | Create a `DMA` | `TopologyEngineer` |
| GET | `/networks/{network_id}/dmas/{dma_id}` | Get a `DMA` | `TopologyEngineer`, `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| GET | `/networks/{network_id}/dmas` | List `DMA` rows with optional `status` filter | `TopologyEngineer`, `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| POST | `/networks/{network_id}/dmas/{dma_id}/water-balance-reports` | Run a DMA water-balance report over a fixed-length window | `ControlOperator` |
| GET | `/networks/{network_id}/dmas/{dma_id}/water-balance-reports` | List published reports for a DMA | `ControlOperator`, `Auditor` |
| POST | `/networks/{network_id}/devices` | Create a `Device` in `PROVISIONED` | `ControlOperator` |
| GET | `/networks/{network_id}/devices/{id}` | Get a `Device` | `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| PATCH | `/networks/{network_id}/devices/{id}` | Update polling and range fields (OCC via `version`) | `ControlOperator` |
| POST | `/networks/{network_id}/devices/{id}/activate` | Transition `Device` from `PROVISIONED` to `ACTIVE` | `ControlOperator` |
| POST | `/networks/{network_id}/devices/{id}/decommission` | Transition `Device` to `DECOMMISSIONED` | `ControlOperator` |
| POST | `/networks/{network_id}/devices/{id}/readings` | Ingest a sensor reading | `ControlOperator` |
| GET | `/networks/{network_id}/devices/{id}/readings` | List readings, optional `archive_tier` filter | `ControlOperator`, `Auditor` |
| GET | `/networks/{network_id}/alerts` | List alerts with optional filters | `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| GET | `/networks/{network_id}/alerts/{id}` | Get an `Alert` | `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| POST | `/networks/{network_id}/alerts/{id}/acknowledge` | Acknowledge an `OPEN` alert | `ControlOperator` |
| POST | `/networks/{network_id}/alerts/{id}/resolve` | Resolve an alert | `ControlOperator` |
| POST | `/networks/{network_id}/alerts/{id}/suppress` | Suppress an alert | `ControlOperator` |
| POST | `/networks/{network_id}/alerts/{id}/investigations` | Open a `LeakInvestigation` for an `ACKNOWLEDGED` alert | `ControlOperator` |
| GET | `/networks/{network_id}/investigations/{id}` | Get a `LeakInvestigation` with computed signals | `ControlOperator`, `MaintenanceSupervisor`, `Auditor` |
| POST | `/networks/{network_id}/investigations/{id}/narrow` | Run leak-localization narrowing | `ControlOperator` |
| POST | `/networks/{network_id}/investigations/{id}/dispatch` | Dispatch a technician; auto-create a `WorkOrder` | `ControlOperator` |
| POST | `/networks/{network_id}/work-orders` | Create a `WorkOrder` directly | `MaintenanceSupervisor` |
| GET | `/networks/{network_id}/work-orders/{id}` | Get a `WorkOrder` | `MaintenanceSupervisor`, `Technician`, `ControlOperator`, `Auditor` |
| GET | `/networks/{network_id}/work-orders` | List `WorkOrder` rows with filters | `MaintenanceSupervisor`, `Technician`, `ControlOperator`, `Auditor` |
| POST | `/networks/{network_id}/work-orders/{id}/assign` | Assign a technician | `MaintenanceSupervisor` |
| POST | `/networks/{network_id}/work-orders/{id}/request-parts` | Request parts; transition to `PARTS_PENDING` | `Technician` |
| POST | `/networks/{network_id}/work-orders/{id}/start` | Begin repair work | `Technician` |
| POST | `/networks/{network_id}/work-orders/{id}/complete` | Submit `repair_record`; transition to `AWAITING_VERIFICATION` | `Technician` |
| POST | `/networks/{network_id}/work-orders/{id}/verify` | Verify completed repair | `MaintenanceSupervisor` |
| POST | `/networks/{network_id}/work-orders/{id}/cancel` | Cancel a non-terminal `WorkOrder` | `MaintenanceSupervisor` |
| GET | `/networks/{network_id}/sync-events` | List emitted `SyncEvent` rows | `Auditor` |
| GET | `/networks/{network_id}/audit-logs` | List `AuditLog` rows | `Auditor` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_BAD_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_DMA_FROZEN` | 409 |
| `ERR_REVIEW_IN_PROGRESS` | 409 |
| `ERR_TOPOLOGY_ROLLBACK_BLOCKED` | 409 |
| `ERR_DEVICE_UNMOUNTED` | 409 |
| `ERR_INVESTIGATION_NO_SIGNAL` | 409 |
| `ERR_DUPLICATE_READING` | 200 |
| `ERR_TOPOLOGY_DANGLING_REFERENCE` | 422 |
| `ERR_READING_TIMESTAMP_OUT_OF_RANGE` | 422 |
| `ERR_READING_OUT_OF_RANGE` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_INSUFFICIENT_DATA` | 422 |
| `ERR_DEVICE_CONFIG_INVALID` | 422 |
| `ERR_WORK_ORDER_SEGMENT_MISSING` | 422 |
