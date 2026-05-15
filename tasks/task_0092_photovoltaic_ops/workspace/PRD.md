# Photovoltaic Ops API — Product Requirements Document

## 1. Introduction

A utility-scale photovoltaic portfolio is simultaneously an engineering asset, a financial instrument, and a regulated participant in an electricity market. The platform described here unifies these three perspectives behind a single REST surface mounted under `/pv-ops`. Equipment data — stations, arrays, strings, modules, inverters, combiner boxes, transformers, suppliers, spare parts — coexists with high-frequency telemetry (one-minute generation readings from SCADA), with the alarm-and-defect workflow that arises from that telemetry, with the periodic patrol regime that complements automated detection, and with the settlement, revenue distribution, and subsidy-declaration processes that turn kilowatt-hours into investor cash and policy-funded receivables.

The discriminating design constraint is that every "obvious" operation in any one of those columns has consequences in another. A critical alarm acknowledged by an operations engineer must escalate into a defect, lock the affected inverter, and re-evaluate the parent station's operational posture. A grid-confirmed energy total that lands a fraction of a percent away from what the station's own meters reported must either yield a finalized revenue line item with re-allocated investor shares or escalate to a disputed period that blocks downstream subsidy claims. The PRD is therefore organized so that each cross-cutting concern is declared once in §2 and then woven into the business workflows in §3, with the §4 endpoint table acting only as an index back into those narratives.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to any endpoint under `/pv-ops` (and to the two test-only operational endpoints described later) MUST carry two headers: `X-User-ID` and `X-User-Role`. The first is a free-form opaque identifier for the calling principal; the second names the principal's role and MUST exactly match one of the four values in the registered role catalogue. If either header is missing, malformed, or carries a role string outside the catalogue, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). If both headers are well-formed but the role is not entitled to perform the requested operation per the role catalogue, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are spelled exactly as follows: `PlatformAdmin`, `O&MEngineer`, `FieldOperator`, and `FinanceOfficer`. Their responsibilities are summarized below; full endpoint-level entitlements appear in the §4 table.

- A `PlatformAdmin` configures the equipment ledger (stations, arrays, strings, modules, inverters, combiner boxes, transformers), maintains the supplier directory and spare-part SKUs, registers vendor alarm-code mappings and subsidy policies, defines investor shares, and is the only role that may approve or reject submitted subsidy declarations. The administrator also owns the two test/operational hooks for clock advancement and external event emission.
- An `O&MEngineer` runs the alarm response workflow (acknowledging, clearing, archiving), creates and schedules patrol plans, verifies or rejects submitted patrols, manually opens defects, dispatches work orders against defects, cancels work orders that have not yet started, and closes or reopens defects.
- A `FieldOperator` is the on-site technician who starts patrols, logs zone-by-zone findings with photo and GPS evidence, submits patrols for verification, and starts or completes work orders.
- A `FinanceOfficer` records on-grid metering lines, drives settlement periods through their reconciliation, confirmation, dispute, and invoicing transitions, performs compensating revenue-adjustment when a confirmed period requires correction, drafts subsidy declarations and submits them for approval, and books receipts (including those for arrears).

All four roles carry **opaque** identities: `X-User-ID` is an operator handle that is not foreign-keyed to any persisted user entity. The server records this opaque identifier wherever a transition demands attribution — for example, as `acknowledged_by` on `AlarmEvent` when an alarm is acknowledged, as `actor_id` on `PatrolRecord` when a patrol is started, and as `actor_id` on every `AuditEntry` — but it never compares `X-User-ID` to any entity's `id`. The single comparison the platform makes between two `X-User-ID` values is the segregation-of-duties check that compares a patrol's verifier against its `actor_id`, described in §3.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside that range are rejected as `ERR_VALIDATION`. The default `offset` is 0; negative values are likewise rejected. List responses always sort by `created_at` ascending as the stable default ordering. The `meta` block for any list response carries four pagination fields: `limit`, `offset`, `total_count` (the number of rows that match the filters before pagination), and `has_more` (true when more rows are available beyond the current page).

### 2.4. Common Resource Properties

Most entities expose four common fields. The `id` field is a server-minted UUID with no type-name prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the row was first persisted. The `updated_at` field is an ISO 8601 UTC timestamp with three fractional digits that is refreshed on every mutation, including every cascade hop that touches the row. The `version` field is an integer that starts at 1 on creation and increments by one on every successful mutation.

The exceptions to this rule are `GenerationReading`, `MeteringRecord`, `RevenueDistribution`, `AlarmCodeMap`, and `AuditEntry`: these entities are append-only and carry only `id` and `created_at`. They do not expose `updated_at`, and they do not expose `version`. The platform does not support mutating individual rows of any of these entities through the public API; reconciliation amendments are expressed by deleting and rewriting the affected children of the parent (for example, `revenue-adjust` deletes and recomputes the `RevenueDistribution` rows of a settlement period rather than patching them in place).

### 2.5. Optimistic Concurrency Control

Mutating endpoints that operate on a single existing resource — supplier updates, spare-part stock adjustments, alarm acknowledgement, alarm clearance, alarm archival — accept an optional `version` field in the request body. When `version` is supplied, the server compares it to the current `version` of the target row before applying any state change; on mismatch the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When `version` is omitted, the OCC check is skipped, the requested mutation proceeds, and the row's `version` increments by one on success. The check uses strict equality (the supplied integer must equal the stored one), not a "no older than" comparison.

### 2.6. Nested Resource Path Validation

Many endpoints embed parent identifiers as path segments — for example, the metering endpoint takes a `station_id` and a request body that itself names a `settlement_period_id`. The server validates path identifiers strictly left-to-right: a `Station` must resolve before any `Array`, `Transformer`, `PatrolPlan`, `PatrolRecord` (via its plan), or `SettlementPeriod` under it is even looked up. The first unresolved id in the chain yields `ERR_NOT_FOUND` (HTTP 404), and no later validation runs. Foreign-key fields supplied in the request body (such as `station_id`, `inverter_id`, `subsidy_policy_id`, `parent_defect_id`, `settlement_period_id`, `warranty_supplier_id`, `assigned_supplier_id`) are validated in the same way: any unresolved reference yields `ERR_NOT_FOUND`.

### 2.7. Validation Priority

When more than one validation rule applies to the same request, the server evaluates them in a fixed priority order. Header presence is checked first; role catalogue membership next; RBAC entitlement third; path/foreign-key existence fourth; transition-state preconditions fifth; and only then domain-specific business rules. The intent is that an authenticated and entitled caller targeting a non-existent resource always sees `ERR_NOT_FOUND` rather than a deeper business error, and a caller in the wrong state always sees `ERR_INVALID_STATE` rather than a domain-specific business code that would only matter if the state were valid. The §3 narratives describe the order of business rules within a single endpoint where relevant — for example, the subsidy submission walks settlement-state, commissioning-date eligibility, eligibility-window, document completeness, and minimum-payout in that documented sequence so that a caller missing a required document never sees a payout-threshold error first, and vice versa.

### 2.8. Precision and Rounding

Monetary amounts are stored and returned with **two decimal places** using **half-up rounding**. Energy quantities — `on_grid_kwh`, `expected_generation_kwh`, `actual_generation_kwh` — use **three decimal places** with half-up rounding. The `performance_ratio` and `capacity_factor` indicators are reported with **four decimal places**, also half-up. Tariff fields (`feed_in_tariff_cny_per_kwh`, `rate_cny_per_kwh`) are accepted and persisted with four decimal places. Geographic coordinates and physical parameters (angles, temperatures, kVA, kV) are accepted as supplied without forced rounding, subject only to the range constraints stated in §3.

A few calculations pin their internal rounding order, and the order matters: per-line rounding before summation is not equivalent to summing then rounding once. Where the order is pinned, §3 states it explicitly.

### 2.9. Hierarchical Consistency and Cascade Semantics

Most mutations in this platform fan out to related rows. The base rule is that every directly mutated row refreshes its `updated_at` and bumps its `version`, and every row reached by a cascade — even a row whose only change is a state field or a counter — does the same. The longest cascade chain in the system originates at alarm acknowledgement: acknowledging an alarm of `MAJOR` or `CRITICAL` severity mints a new `Defect`; the new defect, if `CRITICAL`, locks the offending inverter into `UNDER_REPAIR`; the inverter lock then forces the parent `Station`'s `operational_status` to be recomputed. The symmetric inbound cascade originates at work-order completion: completing a work order resolves the defect, which (if the defect's subject was an inverter that the platform itself had moved to `UNDER_REPAIR`) returns that inverter to `OPERATING` and once again triggers recomputation of the station's `operational_status`. Each of these hops also produces an `updated_at` and a `version` bump on the touched row.

Compensating actions follow the same convention: cancelling a dispatched work order returns the originating defect to `OPEN` and releases all of the spare-part reservations the dispatch had taken, and reverting a confirmed settlement period to `RECONCILING` deletes every `RevenueDistribution` row that the confirmation had emitted.

### 2.10. Idempotency, Dedup, and the Audit Trail

Alarm ingestion is the primary idempotency surface. SCADA may emit the same vendor alarm code on the same inverter repeatedly while a fault persists; rather than accumulate one row per emission, the platform deduplicates within a five-minute window keyed on the resolved canonical code. Two operator actions also have audited consequences that must survive subsequent rollback: alarm acknowledgement, settlement-period confirmation, settlement-period revenue adjustment, and settlement-period dispute all write `AuditEntry` rows. Each audit row captures the caller's `actor_id` (a snapshot of `X-User-ID` at the time of the action) and `actor_role` (a snapshot of `X-User-Role`), a `target_type` of `ALARM`, `SETTLEMENT`, `DECLARATION`, or `DEFECT`, the `target_id` of the audited record, a symbolic `action` such as `ALARM_ACK`, `SETTLEMENT_CONFIRM`, `REVENUE_ADJUST`, or `SETTLEMENT_DISPUTE`, and a paired `before_value` and `after_value` object capturing the relevant fields immediately before and after the change. The audit endpoint exposes these rows for read-only inspection by `PlatformAdmin` and `FinanceOfficer`, and accepts optional `target_type`, `target_id`, and `actor_id` filters along with `limit` and `offset`.

### 2.11. Concurrency Guarantees

Five distinct races are explicitly serialized. (1) Two operators acknowledging the same `OPEN` alarm simultaneously: exactly one transition `OPEN` → `ACKNOWLEDGED` lands on first-writer-wins; the loser receives `ERR_ALARM_ALREADY_ACKED`. (2) Two work orders requisitioning the same spare part where the combined quantity would exceed available stock (defined as `stock_on_hand` minus `reserved_qty`): the reservation step is atomic, exactly one work-order creation succeeds, and the loser receives `ERR_SPARE_PART_INSUFFICIENT`. (3) Two finance officers attempting to confirm overlapping settlement periods on the same station: at most one period reaches `CONFIRMED`; the loser receives `ERR_SETTLEMENT_PERIOD_OVERLAP`, with overlap evaluated as half-open intervals `[period_start, period_end)`. (4) Two duplicate alarm-ingestion calls arriving inside the deduplication window: exactly one `AlarmEvent` row exists at the end; the loser, when its payload would have created a parallel row, receives `ERR_ALARM_DEDUP_RACE`. (5) Two simultaneous moves out of a `CONFIRMED` settlement period — one issuing an invoice and one initiating a revenue adjustment: exactly one wins on first-writer-wins of `state`, and the loser receives `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. The Equipment Ledger and Its Cascading Status

The asset hierarchy is rooted at the `Station`. A station carries an operator-supplied display `name` (1 to 120 characters, unique case-insensitively across the operator's portfolio), a nameplate `installed_capacity_kw` in kW (strictly positive, at most one million, stored to three decimal places), an `ac_capacity_kw` (the inverter side rating; strictly positive and not allowed to exceed the installed DC capacity multiplied by 1.2), a `commissioning_date` marking first grid connection, geographic `latitude` in decimal degrees between -90 and 90 inclusive, `longitude` between -180 and 180 inclusive, a `grid_company` string naming the utility off-taker for settlement, a locked-in `feed_in_tariff_cny_per_kwh` (zero or positive, four decimal places), and a `market_trading_enabled` boolean that defaults to false. Two enumerated postures live on the station: a `lifecycle_state` that is `ACTIVE` on creation and may later be moved to `DECOMMISSIONED` by administrative process, and an `operational_status` that the platform itself computes — never accepted from the client — and that takes one of three values, `OPERATIONAL`, `DEGRADED`, or `OUT_OF_SERVICE`.

Underneath the station sits an `Array`, identified within its parent by a `code` of 1 to 32 characters unique per station, with a `tilt_angle_deg` between 0 and 90 inclusive, an `azimuth_deg` between 0 and 360 inclusive (where 0 means north), and a `string_count` that the platform maintains as the number of `PVString` children directly attached. Each `PVString` carries its own `code` (unique within its array), references its parent `array_id`, names the `inverter_id` of the inverter that drives it and optionally a `combiner_box_id` that defaults to null, declares a `module_count` between 1 and 40, and exposes a computed `rated_dc_power_kw` derived from the modules' `wp_rating` figures. A `Module` belongs to a string by `string_id`, has a globally unique `serial_no`, a peak `wp_rating` strictly positive and at most 1000 watts, a `manufacturer`, a `warranty_supplier_id` and `warranty_until` date, and a `lifecycle_state` that begins at `INSTALLED` and may later become `REMOVED`, `RETURN_TO_VENDOR`, or `SCRAPPED`.

The other equipment family is the `Inverter` ledger, which doubles as the combiner-box ledger. Each row references a `station_id` and optionally an `array_id` (null when the device serves more than one array), declares its `role` (either `INVERTER` or `COMBINER_BOX`), carries `model` and `vendor` strings that become lookup keys into the alarm-code map, has a globally unique `serial_no`, a `rated_ac_power_kw` figure (zero or positive; combiner boxes typically register zero), a `warranty_supplier_id` and `warranty_until` for the device, and an asset `lifecycle_state` that begins at `OPERATING` and may move through `UNDER_REPAIR` and ultimately `RETIRED`. The `Transformer` row likewise hangs off a station, carries a station-unique `code`, a `rated_capacity_kva` strictly positive, the `primary_voltage_kv` and `secondary_voltage_kv` on either side, a `grid_connection_point_no` that is unique globally, and the same `warranty_supplier_id` / `warranty_until` pair.

`Supplier` rows are top-level. Each carries a case-insensitively unique `name`, a free-form `contact` blob, a service `rating` of `A`, `B`, or `C` that defaults to `B`, and a `lifecycle_state` of `ACTIVE` or `BLACKLISTED` (default `ACTIVE`). The administrator may patch any of `contact`, `rating`, `lifecycle_state`, or supply a `version` for OCC checking; a blacklisted supplier cannot subsequently be assigned to a new work order. `SparePart` rows have a unique `sku`, a display `name`, a `stock_on_hand` integer maintained by the platform, a `reserved_qty` integer that the work-order dispatch flow manipulates, and a `unit_cost_cny`; administrators may patch `stock_on_hand` (with optional `version`) when manual stock adjustments are needed.

Whenever the inverter ledger moves between `OPERATING` and `UNDER_REPAIR` — whether by the cascade off an alarm acknowledgement or by the cascade off a work-order completion — the parent station's `operational_status` is recomputed by counting the inverters under it whose `lifecycle_state` is either `OPERATING` or `UNDER_REPAIR` (the denominator) and the subset whose `lifecycle_state` is exactly `UNDER_REPAIR` (the numerator). If the denominator is zero (the station has no active inverters), the status is set to `OPERATIONAL`. Otherwise the ratio of `UNDER_REPAIR` to total is taken. If that ratio is at least one half, the status becomes `OUT_OF_SERVICE`; otherwise, if it is at least one fifth, the status becomes `DEGRADED`; otherwise it is `OPERATIONAL`. Both thresholds are closed at the boundary — a ratio of exactly 0.20 is `DEGRADED`, and a ratio of exactly 0.50 is `OUT_OF_SERVICE`.

### 3.2. Telemetry, Performance, and Historical Aggregation

SCADA pushes one-minute `GenerationReading` rows into each station's stream. Each reading carries a UTC `timestamp` aligned to one-minute boundaries, the measured `dc_power_kw` at the panel side, the measured `ac_power_kw` at the meter side, the plane-of-array `irradiance_w_m2`, and the `module_temp_c` surface temperature. All four numeric inputs are zero-or-positive except `module_temp_c` which may be negative. Every row also carries a `granularity` enumeration that defaults to `RAW_1MIN` on ingestion; downsampled rows produced by the sweep job carry `AGG_15MIN`, `AGG_1H`, or `AGG_1DAY`. Generation readings are append-only and never carry `version` or `updated_at`.

The performance endpoint accepts a `window_start` and `window_end` and an optional `granularity` and returns four figures: `expected_generation_kwh`, `actual_generation_kwh`, `performance_ratio`, and `capacity_factor`. The two energy figures are computed by different algorithms, and the difference between them is the point of the indicator.

The **expected** figure is computed forward-looking from irradiance. The server scans every `RAW_1MIN` reading whose `timestamp` lies in the half-open interval starting at `window_start` and ending before `window_end`, for the requested station. For each reading the contribution is the irradiance ratio (the reading's `irradiance_w_m2` divided by the reference one-sun figure of 1000 watts per square metre) multiplied by the station's `installed_capacity_kw` and by one sixtieth of an hour (because each reading represents a minute). The sum of those contributions across the window is rounded half-up to three decimal places. Critically, the expected calculation makes **no state-based exclusion** — readings that fell inside an active major or critical alarm still count, and missing slices contribute zero without any interpolation. The constant 1000 watts per square metre is the reference standard test condition irradiance and is not configurable through the API.

The **actual** figure is computed chronologically with a state filter. The server iterates the same set of `RAW_1MIN` readings in ascending `timestamp` order. For each reading, it asks whether any `AlarmEvent` on any inverter under that station meets all three of the following at once: its `severity` is `MAJOR` or `CRITICAL`, its `state` is `OPEN` or `ACKNOWLEDGED`, and the reading's `timestamp` falls inside the closed interval bounded by the alarm's `first_seen_at` on the left and `last_seen_at` on the right (boundaries inclusive on both ends). If such an alarm exists, the slice contributes zero (downtime exclusion). Otherwise, the slice contributes the reading's `ac_power_kw` multiplied by one sixtieth of an hour. The sum across the window is rounded half-up to three decimal places. `INFO`-severity and `WARN`-severity alarms do not exclude slices; only the two highest severities do.

From those two figures the platform reports two indicators. The `performance_ratio` is the actual divided by the expected when the expected is strictly positive, and zero otherwise, then rounded half-up to four decimal places. The `capacity_factor` is the actual divided by the product of the station's `ac_capacity_kw` and the number of hours between `window_start` and `window_end`, also rounded half-up to four decimal places.

A sweep endpoint (administrator-only or system-driven) walks the raw readings and produces downsampled rows at the three coarser granularities. Bucketing is **closed-open**: a reading whose `timestamp` is `t` lands in the bucket beginning at the multiple of the bucket size at or below `t` and ending strictly before the next multiple. The `AGG_15MIN` bucket size is fifteen minutes, the `AGG_1H` bucket size is one hour (sixty minutes), and the `AGG_1DAY` bucket size is one day (one thousand four hundred forty minutes). For each non-empty bucket, the average of `dc_power_kw` is rounded half-up to three decimal places, the average of `ac_power_kw` is also rounded half-up to three decimal places, the average of `irradiance_w_m2` is rounded half-up to one decimal place, and the average of `module_temp_c` is rounded half-up to two decimal places. Empty buckets are not materialized. The same sweep run, in its second pass, scans `SubsidyDeclaration` rows in the `APPROVED` state and moves any whose `approval_due_date` is more than thirty days in the past into `ARREARS`; this transition is system-initiated and is the only way the `ARREARS` state is reached.

A test-only clock-advancement capability allows administrators to move the logical clock forward to a supplied `to` instant, and a test-only event-emission capability accepts a `source` and a `payload` for simulating SCADA, weather-service, grid-dispatch, or financial-accounting message inflows; both are administrative hooks rather than business operations and live alongside the sweep in §4.

### 3.3. Alarm Ingestion, Deduplication, and the Acknowledgement Cascade

When SCADA emits an alarm, the platform receives a payload containing the source `inverter_id`, a raw `vendor_code` as the device reported it, and a `first_seen_at` timestamp. The server first resolves the inverter (returning `ERR_NOT_FOUND` if the device is unknown), reads the inverter's `vendor` and `model`, and looks up the `AlarmCodeMap` row keyed on the triple `(vendor, model, vendor_code)`. If no such mapping exists, ingestion is rejected with `ERR_ALARM_CODE_UNMAPPED`. The mapping yields a `canonical_code` (the internal normalized identifier such as `INV_OVERTEMP`), a default `severity` from the enumeration `INFO`, `WARN`, `MAJOR`, `CRITICAL`, and a `root_cause_hint` string surfaced to the operator for triage.

The platform then consults the deduplication index. If an `OPEN` `AlarmEvent` already exists on this `inverter_id` for this `canonical_code`, and that event's `last_seen_at` is within the deduplication window of five minutes ahead or behind the incoming `first_seen_at`, the new payload is merged into the existing row rather than producing a new one: the existing row's `occurrence_count` increments by one, its `last_seen_at` is updated to the incoming `first_seen_at`, and the row's `version` and `updated_at` are refreshed in the usual way. No new event is created. When two such ingestion calls race inside the window and exactly one of them would have created a parallel row, the loser receives `ERR_ALARM_DEDUP_RACE`. Outside the dedup window — or when no `OPEN` event exists on the pair — a new `AlarmEvent` is created with `state = OPEN`, the resolved `canonical_code`, the resolved `severity`, `first_seen_at` taken from the payload, `last_seen_at` initially equal to `first_seen_at`, `occurrence_count = 1`, a `station_id` denormalized from the inverter for station-scoped queries, and `acknowledged_by`, `acknowledged_at`, and `defect_id` all null. The deduplication window of five minutes is expressed internally as 300 seconds.

Acknowledgement is the heaviest single transition in the system. An `O&MEngineer` posts the acknowledgement action against an `OPEN` event with an optional `version` for OCC. The platform first rejects `INFO`-severity alarms with `ERR_ALARM_INFO_NOT_ACKABLE` — informational alarms have to be archived directly rather than acknowledged. If the event is already past `OPEN` (because another operator beat this caller), the loser receives `ERR_ALARM_ALREADY_ACKED`. On success the event moves `OPEN → ACKNOWLEDGED`, the `acknowledged_by` field is set to the caller's `X-User-ID`, `acknowledged_at` is set to the current instant, and an audit row with `target_type = ALARM` and `action = ALARM_ACK` is written capturing the before-and-after snapshot.

A `MAJOR` or `CRITICAL` acknowledgement then mints a `Defect` automatically — the first downstream hop — whose `source` is `ALARM`, `source_ref_id` is the alarm's `id`, `subject_type` is `INVERTER`, `subject_id` is the alarm's `inverter_id`, severity is `MAJOR` if the alarm was `MAJOR` and `CRITICAL` if the alarm was `CRITICAL`, and `state` is `OPEN`. The alarm's own `defect_id` is then set to point at the newly created defect. As the second hop, caused by the defect creation rather than the acknowledgement directly, a `CRITICAL` defect on an inverter forces that inverter's `lifecycle_state` from `OPERATING` to `UNDER_REPAIR`; `MAJOR` defects and defects on non-inverter subjects do not touch the inverter. As the third hop, caused by the inverter mutation, the parent station's `operational_status` is recomputed using the formula in §3.1. Each hop refreshes its row's `updated_at` and bumps its row's `version`. A `WARN` acknowledgement, by contrast, only writes the audit row and bumps the alarm's own metadata — it does not create a defect and does not move any inverter or station.

Clearance is a lighter transition. Posting the clear action moves an `ACKNOWLEDGED` event to `CLEARED`; if the event has an associated defect (its `defect_id` is non-null), that defect must already be in `RESOLVED` or `CLOSED`, otherwise the request fails with `ERR_INVALID_STATE`. Archival behaves in two distinct ways depending on the event's prior history. An `OPEN` `INFO`-severity event can be archived directly with the archival action, moving the event to `ARCHIVED` (this is, in fact, the only way an `INFO` alarm leaves the open state). A `CLEARED` event of any severity can also be archived, transitioning `CLEARED` to `ARCHIVED`; no further precondition applies in that path. Either path writes an audit row with `action = ALARM_ARCHIVE`. The `archive` capability is the only one of the three alarm-workflow capabilities (`ack`, `clear`, `archive`) that is reachable from two different `from` states; the disambiguation is by severity in one path and by prior `CLEARED` history in the other.

### 3.4. Patrol Planning, Field Execution, and the Segregation-of-Duties Gate

The patrol regime exists to catch issues that telemetry would not have flagged. An `O&MEngineer` creates a `PatrolPlan` against a station with a plan `name` (1 to 120 characters, unique per station), a `zone_route` array of 1 to 50 zone codes (no duplicates) describing the geographic walk-through order, a `kind` of either `PERIODIC` or `SPECIAL_POST_STORM`, a `cadence_days` integer between 1 and 180 that is required when `kind` is `PERIODIC` and must be null when `kind` is `SPECIAL_POST_STORM`, and a `checklist` keyed by equipment type (for example, `INVERTER` mapping to a list like `[temp, fan_noise]`). The plan's `lifecycle_state` begins at `ACTIVE` and may be moved to `RETIRED` administratively. Scheduling a patrol on an active plan accepts a `scheduled_for` instant and produces a `PatrolRecord` carrying the parent `patrol_plan_id`, the `station_id` denormalized from the plan, `state = SCHEDULED`, an empty `zone_progress`, and `completed_zone_count = 0`.

A `FieldOperator` starts the patrol; the operator's `X-User-ID` is recorded as the record's `actor_id` and the state moves to `IN_PROGRESS`. Starting is rejected if the parent plan is no longer `ACTIVE`. Once started, the same operator (and only the same operator — the platform compares `X-User-ID` to the captured `actor_id`) logs each zone in turn, with the target zone identified by a `zone` path parameter, and a payload containing a `photo_url`, a `gps` object with `lat` and `lng`, and the per-zone `checklist_findings` covering every checklist item for that equipment type. The platform appends or replaces the zone's record inside `zone_progress` and recomputes `completed_zone_count` as the number of zones in the route whose required checklist items have all been recorded. Submission is permitted only when `completed_zone_count` equals the length of the plan's `zone_route` — every zone in the route must be fully logged — and moves the record from `IN_PROGRESS` to `SUBMITTED`.

Verification and rejection are the segregation-of-duties gate. Both are performed by an `O&MEngineer`, and both compare the verifier's `X-User-ID` to the record's `actor_id`; the two MUST differ, or the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Verification moves the record from `SUBMITTED` to `VERIFIED` and, as a side effect, scans the submitted `zone_progress` for any finding flagged as `defect: true`; each such finding mints a new `Defect` with `source = PATROL`, `source_ref_id` set to the patrol record's `id`, and the equipment subject taken from the finding. Rejection moves the record from `SUBMITTED` to `REJECTED`, captures the verifier's `notes` payload into `verification_notes`, and does not mint any defects. The `VERIFIED` and `REJECTED` states are terminal. The segregation-of-duties check applies to both verification and rejection — an operator cannot reject their own submission to avoid being verified.

### 3.5. Defect Aggregation, Work Orders, and Spare-Part Reservation

`Defect` rows aggregate everything that needs repair. Each defect names a `station_id`, a `subject_type` drawn from `INVERTER`, `MODULE`, `TRANSFORMER`, `STRING`, or `ARRAY`, and a `subject_id` that is a polymorphic foreign key to the subject equipment of that type. The `source` enumeration records where the defect came from — `ALARM`, `PATROL`, `DATA_ANOMALY`, or `EXTERNAL_INSPECTION` — and the optional `source_ref_id` references the originating record (the `AlarmEvent.id` for alarm-sourced defects, the `PatrolRecord.id` for patrol-sourced defects, and so on; the field may be null for `DATA_ANOMALY` defects that have no concrete originating row). Severity at intake is one of `MINOR`, `MODERATE`, `MAJOR`, or `CRITICAL`. The `state` enumeration spans `OPEN`, `DISPATCHED`, `UNDER_REPAIR`, `RESOLVED`, `CLOSED`, and `REOPENED`. The platform records `opened_at` when a defect enters `OPEN` and `resolved_at` when it enters `RESOLVED`. Defects opened automatically from alarm acknowledgement or patrol verification have their data populated by those cascades; defects opened manually accept the same input set directly.

Recurring defects are tracked through the `parent_defect_id` self-reference. When a defect is created with a non-null `parent_defect_id`, that ancestor must refer to a defect with the same `subject_type` and `subject_id`; otherwise the request fails with `ERR_DEFECT_PARENT_SUBJECT_MISMATCH`. The `recurrence_index` is computed at intake: starting from one, the platform walks the `parent_defect_id` chain and adds one for every ancestor whose `state` is `CLOSED`. (Ancestors in other states do not increment the count, but the subject-equality check still applies at every hop.) If the resulting `recurrence_index` is three or greater, the defect's `severity` is automatically escalated to at least `MAJOR` — that is, the maximum of its supplied severity and `MAJOR` — to flag the chronic nature of the issue. The chain cannot cycle because of the subject-equality requirement on every hop. The recurrence threshold (the count of three) is the boundary at which auto-escalation takes effect. The defect-listing endpoint accepts a `recurrence_index_min` query filter that returns only defects whose `recurrence_index` is at least the supplied value, alongside other filters on `station_id`, `state`, `source`, and `subject_type` plus the standard `limit` and `offset`.

Dispatching a work order against a defect creates a `WorkOrder` row. The order names the `defect_id`, an `assigned_supplier_id` (which MUST refer to a supplier whose `lifecycle_state` is `ACTIVE` and not `BLACKLISTED`, otherwise the request fails with `ERR_SUPPLIER_BLACKLISTED`), an `assigned_technician_id` opaque handle, a `scheduled_start` and a `scheduled_end` instant (the end must be strictly after the start), an optional `before_metrics` object snapshot of subject metrics at intake, and a `spare_part_lines` array of items each carrying a `part_id` and a `quantity` to requisition. For every line, the platform verifies that the part's `stock_on_hand` minus its `reserved_qty` is greater than or equal to the requested `quantity`; the comparison is closed at the boundary, so a request for exactly the available quantity succeeds. If any line fails the check, the entire dispatch is rejected with `ERR_SPARE_PART_INSUFFICIENT` — the reservation step is atomic across all lines. On success, each line's `quantity` is added to the part's `reserved_qty`, and the parent defect moves from `OPEN` (or `REOPENED`) to `DISPATCHED`. The work order itself enters `DISPATCHED`.

Starting a work order is performed by the assigned `FieldOperator` and moves the order from `DISPATCHED` to `IN_PROGRESS`; this transition requires that the order's `state` is `DISPATCHED` and that the parent defect's `state` is also `DISPATCHED` (a cross-entity gate that prevents starting a work order whose defect has been independently reverted). The order's `actual_start` is set to the current instant, and the defect mirrors into `UNDER_REPAIR`. Completion accepts an `after_metrics` payload; both `before_metrics` and `after_metrics` MUST be non-empty objects at completion time, and each spare-part line must still satisfy the available-stock check (`stock_on_hand` greater than or equal to the line's `quantity`) so that the consumption can land. On success the order moves to `COMPLETED`, its `actual_end` is set, the defect cascades from `UNDER_REPAIR` to `RESOLVED` with its `resolved_at` recorded, every spare-part line decrements both `stock_on_hand` and `reserved_qty` by the line's `quantity`, the inverter ledger flips back to `OPERATING` (only when the defect's subject is an inverter that the platform itself had locked to `UNDER_REPAIR`; defects on modules, transformers, strings, and arrays do not touch any inverter), and the parent station's `operational_status` is recomputed once again.

Cancellation is the compensating action for a dispatched-but-not-yet-started work order. Posting the cancel action on a `DISPATCHED` work order moves it to `CANCELED`, returns every spare-part line's `quantity` back from `reserved_qty` (the reservations are released), and reverts the parent defect from `DISPATCHED` back to `OPEN`. The cancellation capability is `O&MEngineer`-only; a `FieldOperator` cannot cancel their own assignment.

A resolved defect may be either closed or reopened. Closure moves the defect from `RESOLVED` to `CLOSED` and, if a linked alarm exists in the `ACKNOWLEDGED` state, the closure permits a subsequent manual transition of that alarm to `CLEARED`. Reopening moves the defect from `RESOLVED` back to `REOPENED`, but only if the time elapsed since the defect's `resolved_at` is at most thirty days; the grace window is a hard cap, so a defect resolved thirty-one days ago cannot be reopened and must instead be reopened by chaining a new defect via `parent_defect_id`. A defect in `REOPENED` accepts a fresh work-order dispatch, which re-enters the `DISPATCHED` lane with its own spare-part reservations.

### 3.6. Metering, Settlement Reconciliation, and Compensating Adjustment

Revenue capture begins with the `FinanceOfficer` drafting a `SettlementPeriod` for a station with a `period_start` and a `period_end` instant. The end must be strictly later than the start, the triple `(station_id, period_start, period_end)` must be unique, and during the eventual confirmation step the system additionally verifies that no other `CONFIRMED` period on the same station has a half-open `[period_start, period_end)` interval that overlaps this one. A draft period has `state = DRAFT`, both `provisional_revenue_cny` and `final_revenue_cny` null, an `invoice_no` that is null until issuance, and a `grid_company_confirmed_kwh` figure that will be supplied at reconciliation. The officer records `MeteringRecord` lines under the period through a separate endpoint; each line carries the parent `settlement_period_id`, a half-open `(window_start, window_end)` of its own, an `on_grid_kwh` figure (zero or positive, three decimal places), a `pricing_channel` of either `FEED_IN` or `MARKET_TRADING`, and — only for `MARKET_TRADING` lines — a `market_price_cny_per_kwh`. A `MARKET_TRADING` line on a station whose `market_trading_enabled` is false, or a `MARKET_TRADING` line with no `market_price_cny_per_kwh`, is rejected with `ERR_MARKET_TRADING_DISABLED`; the same metering submission with a missing market price on an enabled station is rejected with `ERR_MARKET_PRICE_REQUIRED`. Metering records carry only `id` and `created_at` from the common-fields set.

Reconciliation begins when the officer posts the start-reconciliation action on a `DRAFT` period with a `grid_company_confirmed_kwh` payload — the figure the grid company has independently confirmed. The transition is gated on two checks (after the standard auth, RBAC, existence, and state-from-DRAFT preconditions). First, the current instant must be at or past the period's `period_end`; a period whose end has not yet been reached cannot start reconciliation, and the comparison is closed at the boundary (a `period_end` equal to now is accepted), with violations rejected by `ERR_PERIOD_NOT_ENDED`. Second, at least one `MeteringRecord` must already exist under the period; an empty period cannot be reconciled and is rejected with `ERR_NO_METERING_RECORDS`. On success the period moves to `RECONCILING`, the `grid_company_confirmed_kwh` is stored, and the platform computes `provisional_revenue_cny` from the recorded metering lines.

Provisional revenue is computed line-by-line. For each `MeteringRecord` under the period, the `FEED_IN`-channel line's line amount is the line's `on_grid_kwh` multiplied by the station's `feed_in_tariff_cny_per_kwh`; the `MARKET_TRADING`-channel line's line amount is the line's `on_grid_kwh` multiplied by the line's own `market_price_cny_per_kwh`. Each line's amount is then rounded half-up to two decimal places before any summation. `provisional_revenue_cny` is the sum of those rounded line amounts, kept as-is without any second round. The per-line-then-sum order is deliberate and pinned: summing first and rounding once would produce different totals when the lines carry many sub-cent fractions, and tests rely on the per-line order.

Two outcomes are then possible. If the absolute difference between the sum of all `MeteringRecord.on_grid_kwh` and the `grid_company_confirmed_kwh`, divided by the larger of that sum or 0.001 (a small floor that protects against division by zero on stations with no recorded energy), is at most 0.005 — five tenths of one percent — the officer may confirm the period. Otherwise the officer must dispute it, and confirmation will be rejected with `ERR_RECONCILIATION_OUT_OF_TOLERANCE`. The boundary is closed: a ratio of exactly 0.005 is within tolerance and confirmation may proceed.

Confirmation does three things in sequence. First, it computes `final_revenue_cny`. Letting the sum of metering `on_grid_kwh` be the raw total, the platform computes an adjustment ratio: 1.0 when the raw total is exactly zero, and the `grid_company_confirmed_kwh` divided by the raw total otherwise. Then, walking the metering lines in ascending `window_start` order (with the `id` as the deterministic tie-break for two lines sharing the same window start), the platform multiplies each line's `on_grid_kwh` by the adjustment ratio and rounds the resulting `adjusted_kwh` half-up to three decimal places. The line price is taken from the appropriate side — the station's `feed_in_tariff_cny_per_kwh` for `FEED_IN`-channel lines, and the line's own `market_price_cny_per_kwh` for `MARKET_TRADING`-channel lines — and the line amount is `adjusted_kwh` multiplied by that price, again rounded half-up to two decimal places before being added to a running total. `final_revenue_cny` is the running total rounded half-up to two decimal places at the end. Because the per-line rounding occurs before the summation, the provisional and final totals may differ by more than just the bulk adjustment ratio applied at the end — this is the discriminating trait of the chronological-with-adjustment formula versus a simple-multiplier shortcut.

Second, confirmation distributes the final revenue across investors. Active `InvestorShare` rows on the station for the period are gathered: a share is active if its `effective_from` falls strictly before the period's `period_end` and its `effective_to` is either null or strictly after the period's `period_start`. The active shares are ordered ascending by `investor_name` (with `id` as the deterministic tie-break for two shares with identical names). The sum of their `share_basis_points` must equal exactly 10000 (each basis point being one ten-thousandth); a sum that diverges from 10000 rejects the confirmation with `ERR_INVESTOR_SHARES_INVALID`. The distribution then works in integer centiyuan (one hundredth of a CNY) to avoid floating-point drift: the platform multiplies `final_revenue_cny` by one hundred to get the integer cent total, then for each share computes its raw cent allocation as the cent total times the share's `share_basis_points` divided by 10000, rounded half-up to the nearest cent. The cumulative sum of those raw allocations is compared against the cent total; the difference (the "drift", possibly zero, possibly negative, possibly one or two cents in either direction) is added to the last share in the ordering as a deterministic tie-break. The result is a set of `RevenueDistribution` rows, one per active share, each carrying its `settlement_period_id`, a snapshot of its `investor_share_id`, the snapshotted `investor_name` and `share_basis_points` (so that subsequent deletion of the share record cannot break the ledger), and an `amount_cny` equal to its raw cent allocation divided by one hundred. The invariant the platform enforces is that the sum of `amount_cny` across the period's distributions equals `final_revenue_cny` exactly — zero drift.

Third, confirmation writes an `AuditEntry` with `target_type = SETTLEMENT` and `action = SETTLEMENT_CONFIRM` capturing a before-and-after snapshot of the period's revenue fields. The dispute path, by contrast, moves the period to the terminal `DISPUTED` state, writes an `AuditEntry` with `action = SETTLEMENT_DISPUTE`, and does not produce distributions or a final figure.

A `CONFIRMED` period may be invoiced or adjusted. Issuing an invoice attaches a unique `invoice_no` payload to the period; if that invoice number has been used for any other settlement period anywhere on the platform, the request is rejected with `ERR_INVOICE_DUPLICATE`. Revenue adjustment is the compensating action that returns a `CONFIRMED` period to `RECONCILING` for re-computation. It is gated by two preconditions beyond the obvious `state == CONFIRMED` check: no subsidy declaration that references this period may be in `SUBMITTED`, `APPROVED`, or `RECEIVED` (a downstream subsidy claim freezes the underlying settlement), and a once-`INVOICED` period cannot be revenue-adjusted at all. On success, the period's existing `RevenueDistribution` rows are deleted (the first compensation hop) and `final_revenue_cny` is set back to null while `provisional_revenue_cny` is recomputed from the metering lines (the second hop — and the invariant that the sum of the distribution amounts equals `final_revenue_cny` is restored at zero on both sides). An `AuditEntry` with `action = REVENUE_ADJUST` captures the before-and-after snapshot, including the deleted distributions, and the officer carries an explanatory `reason` field on the request. The `invoice_no` is preserved through the adjustment because the data is still considered the same period; only the financial figures reset.

Two concurrent moves out of a `CONFIRMED` period — one issuing an invoice and the other initiating revenue adjustment — serialize on first-writer-wins of the period's `state`, and the loser receives `ERR_INVALID_STATE`.

### 3.7. Subsidy Eligibility, Declaration, Approval, and the Arrears Watchdog

Subsidies live in `SubsidyPolicy` rows registered by administrators. Each policy carries a unique policy `code`, a `scope` of `NATIONAL` or `LOCAL`, a `rate_cny_per_kwh` figure (zero or positive, four decimal places), a half-open eligibility window `[eligible_from, eligible_to)`, an optional `min_commissioning_date` and `max_commissioning_date` that bound which stations qualify by their first grid-connection date, a `required_documents` array of document keys (e.g., `GRID_CONNECTION_CERT`, `METER_REPORT`), and a `lifecycle_state` that begins at `ACTIVE` and may be moved to `RETIRED`.

A `FinanceOfficer` drafts a `SubsidyDeclaration` against a station by referencing a `subsidy_policy_id`, the `settlement_period_id` whose energy the declaration claims, and a `documents` array of objects each pairing a document `key` with a `ref_url`. The draft enters `state = DRAFT`, with `claimed_kwh`, `subsidy_amount_cny`, `approval_due_date`, `received_at`, and `rejection_reason` all null. Submission of the draft to `SUBMITTED` walks the following business checks in order, on top of the usual auth-RBAC-existence-state stack. First, the referenced settlement period MUST be in `CONFIRMED` or `INVOICED` (a `DRAFT`, `RECONCILING`, or `DISPUTED` period cannot back a subsidy claim), failing with `ERR_SETTLEMENT_NOT_CONFIRMED`. Second, when the policy supplies bounds, the station's `commissioning_date` MUST fall within the half-open `[policy.min_commissioning_date, policy.max_commissioning_date)`; outside that range yields `ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE`. Third, the period's `period_end` MUST fall within the half-open `[policy.eligible_from, policy.eligible_to)`, failing with `ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW`. Fourth, the set of document keys in `policy.required_documents` MUST be entirely contained in the set of keys present in the declaration's `documents` (the declaration may carry extra documents, but it MUST cover all required ones), failing with `ERR_DOCUMENTS_INCOMPLETE`. Fifth, the computed payout MUST be at least one hundred yuan.

On a passing submission, the platform fixes `claimed_kwh` to the period's `grid_company_confirmed_kwh` and computes `subsidy_amount_cny` as `claimed_kwh` multiplied by the policy's `rate_cny_per_kwh`, rounded half-up to two decimal places and floored at zero. If the resulting payout would be strictly less than the minimum-payout constant of one hundred yuan, the submission is rejected with `ERR_SUBSIDY_BELOW_THRESHOLD`; the boundary is closed, so a payout of exactly one hundred is acceptable. The `approval_due_date` is set to ninety days after the moment of submission.

Approval is administrator-only. A `SUBMITTED` declaration becomes `APPROVED` on the approve action, with no further preconditions beyond the state check. Rejection is also administrator-only, requires a `reason` payload that is stored as `rejection_reason`, and moves the declaration to terminal `REJECTED`. An `APPROVED` declaration is moved to `RECEIVED` by the finance officer recording the receipt, which sets `received_at` to the current instant; the same `receive` capability handles arrears settlement and likewise moves an `ARREARS` declaration to `RECEIVED`.

The arrears watchdog is the only system-driven transition in the declaration lifecycle. During every sweep run, the platform scans `SubsidyDeclaration` rows in `APPROVED` and, for any whose `approval_due_date` is more than thirty days in the past — that is, where the current instant is strictly greater than the `approval_due_date` plus thirty days — moves the declaration into `ARREARS`. The grace period is thirty days and is enforced strictly: a declaration approved-due-yesterday is not yet in arrears. The receipt action then settles the `ARREARS` declaration the same way it settles an `APPROVED` one. `RECEIVED` and `REJECTED` are terminal.

## 4. Endpoint Definitions

All operations are mounted under `/pv-ops`, with the exception of the two test-only hooks (`/_clock/advance`, `/_events/emit`) and the maintenance sweep (`/_sweep/run`), which sit at the root. Creating a new resource returns HTTP 201; modifications and queries return HTTP 200; the event-emit hook returns HTTP 202. Error responses follow the §2.2 contract with their HTTP status drawn from §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /pv-ops/stations | Create a station. | PlatformAdmin |
| GET | /pv-ops/stations | List stations with pagination. | PlatformAdmin, O&MEngineer, FinanceOfficer, FieldOperator |
| GET | /pv-ops/stations/{id} | Get a station including derived `operational_status`. | PlatformAdmin, O&MEngineer, FinanceOfficer, FieldOperator |
| POST | /pv-ops/stations/{`station_id`}/arrays | Create an Array under a station. | PlatformAdmin |
| POST | /pv-ops/arrays/{`array_id`}/strings | Create a PVString under an array. | PlatformAdmin |
| POST | /pv-ops/strings/{`string_id`}/modules | Register a module on a string. | PlatformAdmin |
| POST | /pv-ops/inverters | Register an inverter or combiner box. | PlatformAdmin |
| GET | /pv-ops/inverters/{id} | Get an inverter. | PlatformAdmin, O&MEngineer, FieldOperator |
| POST | /pv-ops/stations/{`station_id`}/transformers | Register a transformer / grid-connection point. | PlatformAdmin |
| POST | /pv-ops/suppliers | Register a supplier. | PlatformAdmin |
| PATCH | /pv-ops/suppliers/{id} | Update supplier (including blacklist). | PlatformAdmin |
| POST | /pv-ops/stations/{`station_id`}/readings | Ingest a generation reading from SCADA. | PlatformAdmin, system |
| GET | /pv-ops/stations/{id}/performance | Compute expected vs actual generation, PR, and capacity factor. | PlatformAdmin, O&MEngineer, FinanceOfficer |
| POST | /_sweep/run | Run historical-data downsampling sweep and auto-arrears scan. | PlatformAdmin, system |
| POST | /_clock/advance | Advance the logical clock to a supplied instant (test-only). | PlatformAdmin |
| POST | /_events/emit | Emit an external-system event (test-only). | PlatformAdmin |
| POST | /pv-ops/alarm-code-map | Register vendor-to-canonical alarm-code mappings. | PlatformAdmin |
| POST | /pv-ops/alarms | Ingest an alarm event from SCADA (deduplicated). | PlatformAdmin, system |
| GET | /pv-ops/alarms | List alarms with filters. | PlatformAdmin, O&MEngineer |
| POST | /pv-ops/alarms/{id}/ack | Acknowledge alarm; may auto-create defect. | O&MEngineer |
| POST | /pv-ops/alarms/{id}/clear | Clear an acknowledged alarm. | O&MEngineer |
| POST | /pv-ops/alarms/{id}/archive | Archive an alarm (INFO directly, or after CLEARED). | O&MEngineer |
| POST | /pv-ops/stations/{`station_id`}/patrol-plans | Create a patrol plan. | O&MEngineer |
| POST | /pv-ops/patrol-plans/{id}/schedule | Schedule one patrol record. | O&MEngineer |
| POST | /pv-ops/patrol-records/{id}/start | Start the patrol. | FieldOperator |
| POST | /pv-ops/patrol-records/{id}/zones/{zone}/log | Log a zone with photo, GPS, and checklist findings. | FieldOperator |
| POST | /pv-ops/patrol-records/{id}/submit | Submit a patrol record for verification. | FieldOperator |
| POST | /pv-ops/patrol-records/{id}/verify | Verify and accept a submitted patrol. | O&MEngineer |
| POST | /pv-ops/patrol-records/{id}/reject | Reject a submitted patrol. | O&MEngineer |
| POST | /pv-ops/defects | Open a defect (manual external-inspection or data-anomaly). | O&MEngineer |
| GET | /pv-ops/defects | List defects with filters and recurring-defect view. | PlatformAdmin, O&MEngineer |
| POST | /pv-ops/defects/{id}/work-orders | Dispatch a work order against a defect. | O&MEngineer |
| POST | /pv-ops/work-orders/{id}/start | Start a work order. | FieldOperator |
| POST | /pv-ops/work-orders/{id}/complete | Complete a work order with after-metrics. | FieldOperator |
| POST | /pv-ops/work-orders/{id}/cancel | Cancel a dispatched work order (compensation). | O&MEngineer |
| POST | /pv-ops/defects/{id}/close | Close a resolved defect. | O&MEngineer |
| POST | /pv-ops/defects/{id}/reopen | Reopen a recently resolved defect. | O&MEngineer |
| POST | /pv-ops/spare-parts | Register a spare part SKU. | PlatformAdmin |
| PATCH | /pv-ops/spare-parts/{id} | Adjust stock. | PlatformAdmin |
| POST | /pv-ops/stations/{`station_id`}/settlement-periods | Create a settlement period draft. | FinanceOfficer |
| POST | /pv-ops/stations/{`station_id`}/metering | Record an on-grid metering line. | FinanceOfficer |
| POST | /pv-ops/settlement-periods/{id}/start-reconciliation | Move DRAFT to RECONCILING and compute provisional revenue. | FinanceOfficer |
| POST | /pv-ops/settlement-periods/{id}/confirm | Confirm settlement; compute final revenue and distributions. | FinanceOfficer |
| POST | /pv-ops/settlement-periods/{id}/dispute | Mark a reconciling period as DISPUTED. | FinanceOfficer |
| POST | /pv-ops/settlement-periods/{id}/issue-invoice | Issue an invoice number on a CONFIRMED period. | FinanceOfficer |
| POST | /pv-ops/settlement-periods/{id}/revenue-adjust | Revert a CONFIRMED period back to RECONCILING. | FinanceOfficer |
| GET | /pv-ops/settlement-periods/{id} | Get a settlement period including computed amounts. | PlatformAdmin, FinanceOfficer |
| POST | /pv-ops/stations/{`station_id`}/investor-shares | Define investor shares for a station. | PlatformAdmin |
| POST | /pv-ops/subsidy-policies | Register a subsidy policy. | PlatformAdmin |
| POST | /pv-ops/stations/{`station_id`}/subsidy-declarations | Draft a subsidy declaration. | FinanceOfficer |
| POST | /pv-ops/subsidy-declarations/{id}/submit | Submit a declaration. | FinanceOfficer |
| POST | /pv-ops/subsidy-declarations/{id}/approve | Approve a submitted declaration. | PlatformAdmin |
| POST | /pv-ops/subsidy-declarations/{id}/reject | Reject a submitted declaration. | PlatformAdmin |
| POST | /pv-ops/subsidy-declarations/{id}/receive | Record subsidy receipt (also settles arrears). | FinanceOfficer |
| GET | /pv-ops/subsidy-declarations | List declarations. | PlatformAdmin, FinanceOfficer |
| GET | /pv-ops/audit-entries | Query the audit log. | PlatformAdmin, FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION | 422 |
| ERR_SUPPLIER_BLACKLISTED | 422 |
| ERR_SOD_VIOLATION | 403 |
| ERR_DEFECT_PARENT_SUBJECT_MISMATCH | 422 |
| ERR_SETTLEMENT_NOT_CONFIRMED | 422 |
| ERR_PERIOD_NOT_ENDED | 422 |
| ERR_NO_METERING_RECORDS | 422 |
| ERR_SETTLEMENT_PERIOD_OVERLAP | 409 |
| ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE | 422 |
| ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW | 422 |
| ERR_DOCUMENTS_INCOMPLETE | 422 |
| ERR_MARKET_TRADING_DISABLED | 422 |
| ERR_MARKET_PRICE_REQUIRED | 422 |
| ERR_INVESTOR_SHARES_INVALID | 422 |
| ERR_SPARE_PART_INSUFFICIENT | 422 |
| ERR_SUBSIDY_BELOW_THRESHOLD | 422 |
| ERR_RECONCILIATION_OUT_OF_TOLERANCE | 422 |
| ERR_ALARM_INFO_NOT_ACKABLE | 422 |
| ERR_ALARM_ALREADY_ACKED | 409 |
| ERR_ALARM_DEDUP_RACE | 409 |
| ERR_ALARM_CODE_UNMAPPED | 422 |
| ERR_INVOICE_DUPLICATE | 409 |
| ERR_UNIQUE_VIOLATION | 409 |
