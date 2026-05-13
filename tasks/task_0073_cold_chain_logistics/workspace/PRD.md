# Cold Chain Logistics API — Product Requirements Document

## 1. Introduction

Perishable cargo — fresh food, vaccines and biological samples — moves through long distribution chains under strict temperature envelopes, and a single excursion that goes unanswered for too long can render an entire load worthless. The Cold Chain Logistics platform documented here gives shippers, carriers, drivers, dispatch operations, consignees, compliance staff and insurance adjusters a shared system of record covering the full lifecycle of a refrigerated transport job: the route plan and crew assignment, the live stream of sensor readings, the abnormal-temperature alerts that those readings produce, the post-trip damage assessment, the multi-party responsibility negotiation, the insurance claim that follows from it, and the periodic regulatory reports that summarise the whole programme.

The platform's distinguishing requirement is that every numeric, temporal and custodial fact must be reconstructable later. Temperature readings stream in from IoT devices on the vehicle compartment and the cargo box; the server pins their validity and threshold verdict at ingest; abnormal samples automatically open alerts whose severity is recomputed as the violation persists; damage amounts are settled via one of two declared calculation variants with deterministic rounding; responsibility splits between shipper, carrier and consignee are advisory-computed yet negotiated, with mediation cycles when parties dispute; and insurance payouts honour a conserved-quantity invariant linking assessment, payout and subrogation. The audit log captures every alert and responsibility lifecycle event so that compliance officers and insurance adjusters can defend each decision under regulatory inspection.

This document specifies the HTTP contract, the cross-entity state machinery, the calculations and validations, and the role-based access controls of that platform. All endpoints described below are mounted under the `/transport-tasks` API surface and its sibling resources (`/vehicles`, `/drivers`, `/alerts`, `/damage-assessments`, `/responsibility-decisions`, `/insurance-claims`, `/compliance-reports`, `/audit-log`, plus the `/_clock` test-fixture).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the request is made. A request that omits either header, or sends them empty, is rejected with `ERR_AUTH_MISSING`. A request whose `X-User-Role` is not one of the seven recognised roles, or whose role is not authorised for the endpoint, is rejected with `ERR_FORBIDDEN`.

The seven recognised roles are `SHIPPER`, `CARRIER`, `DRIVER`, `CONSIGNEE`, `DISPATCHER`, `COMPLIANCE_OFFICER`, and `INSURANCE_ADJUSTER`. An eighth principal — `SYSTEM` — is reserved for test-fixture clock control and IoT-batch ingest paths.

For every recognised business role, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity row. The server may record it as a foreign-key-like value on certain resources — for example, a `TransportTask` records `shipper_id`, `carrier_id` and `consignee_id` whose values are expected to match the `X-User-ID` of the corresponding party — but it does not compare `X-User-ID` to an `id` field on a `Shipper`, `Carrier` or `Consignee` row, because no such row exists. Ownership-based access (for instance, a `SHIPPER` reading a transport task they own) is enforced by comparing `X-User-ID` to the `shipper_id`, `carrier_id`, or `consignee_id` stored on the task. The same opaque-identifier rule applies to `DRIVER`, `DISPATCHER`, `COMPLIANCE_OFFICER`, `INSURANCE_ADJUSTER`, and `SYSTEM` — `X-User-ID` is recorded as `actor_id` on `AuditLogEntry`, as `mediator_id` on a `ResponsibilityDecision` entering mediation, and as the comparison key for the segregation-of-duties rule, but is never matched against a persisted user-entity primary key.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside this range are rejected with `ERR_VALIDATION`. The default `offset` is 0. Sort order is ascending by `created_at` unless an endpoint says otherwise. The pagination block of `meta` exposes `limit`, `offset`, `total_count`, and `has_more` on every list response.

### 2.4. Resource Identifiers and Common Properties

Every resource the system creates carries a server-minted `id`. The identifier is a UUID and does not include any type prefix. Most entities additionally carry `created_at` and `updated_at` timestamps (ISO 8601 UTC with three fractional digits) and a monotonic integer `version` that increments by one on every mutation; these three properties — `id`, `created_at`, `updated_at`, `version` — are present on `Vehicle`, `Driver`, `TransportTask`, `TaskStop`, `Alert`, `DamageAssessment`, `ResponsibilityDecision`, `InsuranceClaim`, and `ComplianceReport`.

A small number of records exist as immutable lifecycle artefacts and carry only `id` and `created_at` — there is no `updated_at` and no `version` field on these rows. They are `HandoverRecord`, `ResponseAction`, `TemperatureReading`, and `AuditLogEntry`.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate a versioned resource (the `PATCH` endpoints for `TransportTask`, `DamageAssessment`, and `ResponsibilityDecision`) accept an optional `version` field in their request body. If supplied, the value is compared against the row's current `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT`. Omitting `version` from the body skips the check entirely. Every successful mutation refreshes `updated_at` and increments `version` by one.

### 2.6. Validation Ordering and Path Traversal

When multiple validations can apply to a single request, the server evaluates them in a fixed priority order so that one failure cannot mask a deeper one. Authentication is checked first — a missing `X-User-ID` or `X-User-Role` surfaces as `ERR_AUTH_MISSING` (status 401). Authorisation is checked next: an unrecognised role or an endpoint the role is not permitted to call yields `ERR_FORBIDDEN` (status 403). Path-id existence is checked third, left-to-right: every id segment in the URL (the transport-task id, then the stop id, then the alert / assessment / decision / claim / report / vehicle / driver id as applicable) is resolved in order, and the first missing id is reported as `ERR_NOT_FOUND` (status 404). Body foreign-key existence is checked fourth — any of `vehicle_id`, `driver_id`, `task_id`, `assessment_id`, `decision_id`, or any element of `evidence_alert_ids` that does not refer to an existing row produces `ERR_REFERENCE_NOT_FOUND` (status 404). State eligibility — that the target resource is in the from-state the requested transition requires — is checked fifth and yields `ERR_INVALID_STATE` (status 409) when it fails.

Beyond those five gates, business-safety, business-referential, business-constraint, business-temporal and business-fiscal checks fire in scaffold-priority order — segregation of duties on finalize (`ERR_SEGREGATION_VIOLATION`, 403); the cross-entity check that an alert can only be resolved while its parent task is `IN_TRANSIT`, `AT_STOP`, or `DELIVERED` (`ERR_TASK_NOT_RESOLVABLE`, 409); the requirement that the linked responsibility decision is `FINALIZED` before an insurance claim can be reported (`ERR_DECISION_NOT_FINALIZED`, 409); the evidence-chain requirement on damage assessments (`ERR_EVIDENCE_REQUIRED`, 422); the invoice-value requirement when the assessment variant is `INVOICE_VALUE` (`ERR_INVOICE_VALUE_REQUIRED`, 422); the vehicle-overlap check at dispatch (`ERR_VEHICLE_OVERLAP`, 409); the driver hours-of-service check at dispatch (`ERR_DRIVER_HOURS_EXCEEDED`, 409); the strict-mode out-of-window check on readings (`ERR_READING_OUT_OF_WINDOW`, 422); the responsibility-split sum-to-one check (`ERR_PCT_SUM_INVALID`, 422); the insurance-cap check on claim reporting (`ERR_INSURANCE_CAP_EXCEEDED`, 422); the damaged-quantity bounds check (`ERR_QUANTITY_INVALID`, 422); the amount-bounds check on assess and subrogate (`ERR_AMOUNT_INVALID`, 422); the optimistic-concurrency check on PATCH endpoints (`ERR_VERSION_CONFLICT`, 409); and finally generic schema/field-type validation (`ERR_VALIDATION`, 422). The numeric ordering above is the order callers should expect; for example, if a `PATCH /damage-assessments/{id}` request has both a stale `version` and a malformed `salvage_pct`, the OCC failure surfaces before the schema-validation failure.

### 2.7. Numeric Precision, Rounding, and Time

All monetary quantities are integer cents. Damage-amount calculations round half up to the nearest whole cent and follow a pinned evaluation order: compute the per-unit damage and round it first, then multiply by the damaged-unit count, then apply the vehicle insurance cap. Responsibility-split percentages are stored to two decimal places, rounded half up; remainder cents from rounding are allocated to the party with the largest pre-round share, with ties broken alphabetically in the order `CARRIER` > `CONSIGNEE` > `SHIPPER`. Temperature values are stored to two decimal places and rounded half up; GPS latitude and longitude are stored to four decimal places. Duration values associated with alerts are integer seconds. Driver hours-of-service durations are converted into minutes by taking the ceiling of seconds divided by 60.

All datetimes in the system are ISO 8601 UTC with millisecond precision. To allow time-gated transitions to be reached in tests without wall-clock waits, an admin-only test-fixture capability advances the logical clock by a supplied `seconds` value and a sibling capability returns the current logical clock as a `now` field; every time-derived calculation, including alert duration and the driver's rolling-24-hour window, reads from this logical clock.

### 2.8. Concurrency Guarantees and Cascading Effects

Many state transitions in this system fan out to mutate companion entities. The dispatch transition flips a `Vehicle` from `AVAILABLE` to `IN_USE` and a `Driver` from `OFF_DUTY` to `ON_DUTY`; the delivery cascade flips them both back when the final stop's handover lands and the parent task becomes `DELIVERED`; an abort while the task is `DISPATCHED` or `IN_TRANSIT` likewise returns the vehicle to `AVAILABLE` and the driver to `OFF_DUTY`. A task transition to `CLOSED` cascades any of the task's alerts in `RESOLVED` to `CLOSED`. Every such cascade refreshes the affected entity's `updated_at` and increments its `version`.

Concurrent attempts to mutate the same entity are serialised by first-writer-wins on the entity's status field, and the loser is rejected with the specific `error_id` appropriate to the contention point. When two dispatch requests race for the same `Vehicle`, the first dispatch wins, flips `Vehicle.status` to `IN_USE`, and the second is rejected with `ERR_VEHICLE_OVERLAP`; the second caller, on re-read, sees the vehicle already `IN_USE`. When two dispatches race for the same `Driver` such that the second would push the driver's rolling 24-hour minutes above `max_daily_minutes`, the second is rejected with `ERR_DRIVER_HOURS_EXCEEDED`. When two IoT devices retry the same temperature ingest with the same `idempotency_key` on the same task, exactly one `TemperatureReading` row is created; subsequent retries return that first row verbatim with HTTP 200 — under the `ERR_IDEMPOTENT_REPLAY` semantics — and do not re-open or duplicate alerts. When acknowledge and resolve race on the same alert, exactly one wins on `Alert.status` and the loser sees `ERR_INVALID_STATE` because the alert has advanced past the expected from-state. When two compliance officers race to `FINALIZED` the same responsibility decision, the first wins on `ResponsibilityDecision.status` and the second sees `ERR_INVALID_STATE`. When two insurance adjusters race a pay against a reject on the same claim, exactly one terminal transition succeeds; the loser receives `ERR_INVALID_STATE` because `InsuranceClaim.status` has already advanced. When two drivers race to create a `HandoverRecord` on the final-sequence stop — both attempting to cascade the parent task to `DELIVERED` — the unique-per-stop constraint admits exactly one handover; the other is rejected with `ERR_HANDOVER_ALREADY_EXISTS`, and the parent's `AT_STOP` to `DELIVERED` cascade fires exactly once.

### 2.9. Chain of Custody and Evidence

The chain of custody is built up through `HandoverRecord` rows whose successive `handed_over_at` timestamps partition the task's lifetime into custody segments belonging to a shipper, carrier, driver, or consignee principal. Every `HandoverRecord` is unique per stop — at most one handover can be recorded against a given `TaskStop`. The evidence chain used downstream by damage-assessment and responsibility-split work is precisely this handover chain plus the alerts referenced through `evidence_alert_ids`. Photographic evidence is referenced by `photo_evidence_ref` and persists for the assessment trail. The audit log captures every lifecycle event on alerts and responsibility decisions; `AuditLogEntry.subject_type` is polymorphic and may take the value `ALERT` or `RESPONSIBILITY_DECISION`, with `subject_id`, `action`, `actor_role`, `actor_id`, and `occurred_at` recording who did what and when.

### 2.10. Regulatory Domains and Compliance Coverage

Cargo declared as `FOOD`, `PHARMACEUTICAL`, or `BIOLOGICAL` falls under three distinct regulatory regimes; a `ComplianceReport` covers exactly one of these `regulatory_domain` values for a half-open `[period_start, period_end)` window. The report summarises three counts — total matching tasks (`task_count`), alerts opened within the period for those tasks (`alert_count`), and the subset whose severity reached the highest band (`critical_alert_count`) — which are populated when the report is generated.

## 3. Business Logic & Workflows

### 3.1. Fleet Onboarding: Vehicles and Drivers

A carrier organisation registers its rolling stock and crew before any transport job can dispatch. A `CARRIER` creates a `Vehicle` by submitting `vehicle_no`, `compartment_count`, and `insured_cap_cents`. `vehicle_no` is the carrier-assigned plate or fleet identifier, must be unique across the system, and is a non-empty string of length one to thirty-two characters. `compartment_count` is the number of independently temperature-controlled compartments and must be an integer in the range one through six. `insured_cap_cents` is the per-incident cap in cents on cargo carried by this vehicle and must be a positive integer. On creation the server assigns `status` of `AVAILABLE`; from then on, `status` is computed from active task assignments — `AVAILABLE`, `IN_USE`, or `OUT_OF_SERVICE`.

A `CARRIER` registers each driver with `license_no`, `name`, and an optional `max_daily_minutes`. `license_no` is the government driver licence number, is unique system-wide, and is a non-empty string of length one to thirty-two. `name` is the driver's display name, a non-empty string of length one to one-hundred-twenty. `max_daily_minutes` defaults to 660 — that is, eleven hours — when omitted; otherwise it is an integer in the range one to one thousand four hundred forty. The driver's `status` is computed and is one of `OFF_DUTY`, `ON_DUTY`, or `SUSPENDED`, with `OFF_DUTY` set on creation and `ON_DUTY` set when the driver is dispatched onto an active task.

### 3.2. Planning a Transport Task and Defining the Route

A shipper, or a dispatcher operating on the shipper's behalf, creates a `TransportTask` in the `PLANNED` state. The creation payload carries the cargo profile, the temperature envelope, the parties, the schedule, the sensor cadence, and the route. The cargo profile is `cargo_type` — one of `FOOD`, `PHARMACEUTICAL`, or `BIOLOGICAL` — together with `cargo_value_cents`, the declared total shipper value in cents (a positive integer), and `cargo_quantity`, an integer count of cartons or pallets loaded at origin (a positive integer). The temperature envelope is given by `temp_min_celsius` and `temp_max_celsius`, each a number stored to two decimal places; `temp_min_celsius` must be strictly greater than minus eighty and strictly less than `temp_max_celsius`, while `temp_max_celsius` must be strictly less than eighty and strictly greater than `temp_min_celsius`. The parties are `shipper_id`, `consignee_id`, and `carrier_id`, each of which must match an existing role principal of the corresponding kind. The schedule is `planned_start_at` (ISO 8601 UTC, no earlier than current clock at the moment of creation) and `planned_end_at` (ISO 8601 UTC, strictly later than `planned_start_at`). The sensor cadence is `polling_interval_seconds`, an integer in the range ten to three thousand six hundred, defaulting to sixty when omitted.

The route is supplied as a `stops` array; each element becomes a `TaskStop` row with the parent `task_id` set immutably to the new task. Each stop carries a one-based `sequence` (the origin is sequence one and the final destination is the maximum sequence, with sequence numbers unique within a task); a `location_label` (non-empty string, length one to two hundred); a `planned_arrival_at` ISO 8601 UTC timestamp strictly greater than the preceding stop's `planned_arrival_at`; and a boolean `handover_required` (default true) declaring whether a `HandoverRecord` must exist before the stop can advance to `HANDED_OVER`. The system clock-stamps `actual_arrival_at` later, when arrival fires. The dispatcher may amend `vehicle_id`, `driver_id`, and `polling_interval_seconds` while the task is still `PLANNED`; both `vehicle_id` and `driver_id` are nullable while the task is in `PLANNED` and become required at the dispatch transition.

### 3.3. Dispatch: Pre-flight Checks and Resource Locking

A `DISPATCHER` advances the task from `PLANNED` to `DISPATCHED`. Five preconditions guard this step. The task must have a non-null `vehicle_id` pointing to a `Vehicle` whose `status` is `AVAILABLE` and a non-null `driver_id` pointing to a `Driver` whose `status` is `OFF_DUTY`. The vehicle must have no overlapping active task — when both intervals are treated as half-open ranges of the form starting at `planned_start_at` (inclusive) and ending at `planned_end_at` (exclusive), no other task on this vehicle in `DISPATCHED`, `IN_TRANSIT`, or `AT_STOP` may have an interval that strictly intersects the new task's interval. Exact equality at endpoints — the existing task's end timestamp equalling the new task's start timestamp — is allowed under half-open semantics and does not trigger the rejection. A rejection here is reported as `ERR_VEHICLE_OVERLAP`.

The driver must remain within the hours-of-service ceiling. For each task already assigned to the driver in status `DISPATCHED`, `IN_TRANSIT`, or `AT_STOP`, treat the interval `[planned_start_at, planned_end_at]` as closed, with its full duration in minutes computed as the ceiling of total seconds divided by sixty. For any candidate 24-hour rolling window — anchored at the new task's `planned_start_at`, at its `planned_end_at`, or at any boundary timestamp from any other task already assigned to the driver — the driver's accumulated minutes within that window is the sum, over all assigned tasks, of the minute-count of the intersection of each task's interval with that window. The dispatch is rejected if there exists any such anchored window where the driver's accumulated minutes plus the new task's overlap into that window strictly exceeds `max_daily_minutes`; equality with `max_daily_minutes` is allowed. The rejection code is `ERR_DRIVER_HOURS_EXCEEDED`. Finally, the route must already have at least two stops (origin plus at least one destination); a route shorter than that cannot dispatch.

Successful dispatch produces three side effects in the same request: the vehicle moves to `IN_USE`, the driver moves to `ON_DUTY`, and the task's `updated_at` and `version` are refreshed. Any time before dispatch — and only before dispatch — a `DISPATCHER` can abort the task by submitting a `reason`, which moves it from `PLANNED` to `ABORTED` without further side effects. The same abort capability is available while the task is `DISPATCHED` or `IN_TRANSIT`, in which case the vehicle is restored to `AVAILABLE` and the driver to `OFF_DUTY` as a side effect of the abort.

### 3.4. Movement and Multi-stop Handover

Once a task is `DISPATCHED`, the driver departs origin to advance from `DISPATCHED` to `IN_TRANSIT`. Departure is gated by the clock: the current logical clock must be at least `planned_start_at` minus 3600 seconds — that is, no earlier than one hour before the planned start. As a side effect of departure, the first `TaskStop` (sequence equal to one) advances from `PENDING` to `ARRIVED` because the cargo is already at origin.

Arrival at the next intermediate stop advances the parent task from `IN_TRANSIT` to `AT_STOP`. This arrival fires for the `TaskStop` with the lowest `sequence` whose `status` is still `PENDING`; calling arrival for a stop that is not the lowest-sequence pending one is rejected. As a side effect, the stop's `actual_arrival_at` is clock-stamped and the stop's `status` moves from `PENDING` to `ARRIVED`. When the stop is intermediate (not the final destination), the driver subsequently departs the stop to return the parent task from `AT_STOP` to `IN_TRANSIT`; the departure requires either that the stop is in `HANDED_OVER`, or that the stop has `handover_required` set to false and is in `ARRIVED`, and that at least one further stop remains `PENDING` on this task.

A handover is created against a stop by the driver, supplying `from_party_id` (the custodian releasing the cargo) and `to_party_id` (the custodian receiving it) — each of which must reference an existing `Shipper`, `Carrier`, `Driver`, or `Consignee` principal — together with `temperature_at_handover_celsius` (a two-decimal number in the range minus eighty through eighty), `quantity_attested` (a non-negative integer, no greater than the task's `cargo_quantity`), and `photo_evidence_ref` (a non-empty string, length one to two hundred fifty-five). The server clock-stamps `handed_over_at` and immutably records `stop_id` and the denormalised parent `task_id` on the new row. The stop advances from `ARRIVED` to `HANDED_OVER`. When the handed-over stop is the final-sequence stop and every other stop on the task is in `HANDED_OVER` or `SKIPPED`, the parent task automatically advances `AT_STOP` to `DELIVERED` with cascade depth two; the driver is returned to `OFF_DUTY` and the vehicle to `AVAILABLE`. Because `HandoverRecord` is unique per stop, a second handover attempt against the same stop — including the racing pair that both attempt to land the final cascade — is rejected with `ERR_HANDOVER_ALREADY_EXISTS`.

Some stops are operationally optional. A `DISPATCHER` may mark a stop as `SKIPPED` directly from `PENDING` only when that stop's `handover_required` is false; the request is rejected otherwise.

### 3.5. Sensor Ingestion, Validity Pinning and Threshold Verdicts

Throughout the active leg of a task — that is, while the task is in `DISPATCHED`, `IN_TRANSIT`, or `AT_STOP` — IoT devices stream `TemperatureReading` rows into the system. Each reading carries `sensor_id` (a non-empty identifier of length one to sixty-four), `sensor_kind` (either `COMPARTMENT` or `CARGO_BOX`), `temperature_celsius` (a two-decimal number nominally in the range minus eighty through eighty), `gps_lat` (a four-decimal WGS84 latitude in the range minus ninety through ninety), `gps_lng` (a four-decimal WGS84 longitude in the range minus one-hundred-eighty through one-hundred-eighty), `captured_at` (an ISO 8601 UTC timestamp), and `idempotency_key` (a non-empty string of length one to one hundred twenty-eight, unique per `task_id`). The reading is keyed off `task_id` for storage; the task to which it is being attached must already be in one of `DISPATCHED`, `IN_TRANSIT`, or `AT_STOP`.

At ingest the server pins `validity` to one of `VALID`, `INVALID_OUT_OF_WINDOW`, `INVALID_SCHEMA`, or `ARCHIVED`, in two stages. First, if `captured_at` is strictly earlier than the parent task's `planned_start_at`, or strictly later than the current logical clock, `validity` is set to `INVALID_OUT_OF_WINDOW`. Otherwise, if `sensor_kind` is not in the set `COMPARTMENT` or `CARGO_BOX`, or `gps_lat` falls outside minus ninety through ninety, or `gps_lng` falls outside minus one-hundred-eighty through one-hundred-eighty, or `temperature_celsius` falls outside minus eighty through eighty, `validity` is set to `INVALID_SCHEMA`. When neither of those branches fires, `validity` is set to `VALID`. The server also computes `violation`: if `temperature_celsius` is strictly less than the task's `temp_min_celsius`, the verdict is `BELOW_MIN`; if `temperature_celsius` is strictly greater than the task's `temp_max_celsius`, the verdict is `ABOVE_MAX`; otherwise the verdict is `WITHIN`. Equality with either bound is `WITHIN` — the bounds are inclusive.

By default an out-of-window reading is persisted with `validity` of `INVALID_OUT_OF_WINDOW` and a HTTP 200 OK is returned; the reading does not open an alert. When the caller adds the query flag `strict=true`, an out-of-window reading is instead rejected with `ERR_READING_OUT_OF_WINDOW`. Duplicate ingest of the same `idempotency_key` against the same `task_id` produces no new row — the existing row is returned verbatim with HTTP 200 under `ERR_IDEMPOTENT_REPLAY` semantics — and does not re-open or duplicate any alert. Once a task is `CLOSED`, a compliance officer can run an archival capability that moves every `VALID` reading older than that task's `closed_at` into `validity` of `ARCHIVED`, returning the affected-row count.

### 3.6. Alert Open, Severity Escalation, and Notification

When a freshly ingested reading has `validity` of `VALID` and a `violation` of either `BELOW_MIN` or `ABOVE_MAX`, and no prior alert on the same task with the same `violation` exists in any of `OPEN`, `ACKNOWLEDGED`, `IN_RESPONSE`, or `ESCALATED`, the server automatically opens an `Alert`. The newly opened alert records the immutable parent `task_id`, the `opening_reading_id` of the reading that triggered it, the inherited `violation`, the `opened_at` timestamp set from the reading's `captured_at`, and an initial `level` and `notified_channels` derived by the rules below; `status` starts at `OPEN`. An `AuditLogEntry` is written with `subject_type` of `ALERT` and `action` of `OPENED`, with `actor_role` equal to `SYSTEM` and `actor_id` equal to the literal string `system`.

The alert's `level` — one of `WARNING`, `MAJOR`, or `CRITICAL` — is recomputed at every relevant moment: at the initial open, again on every subsequent valid reading for the same task while the alert is unresolved, and once more when the alert is resolved (final classification). The recomputation uses two inputs. The first is `duration_seconds`, the running count of continuous seconds the violation has persisted; this is the difference between `current_clock` (or `resolved_at` once the alert resolves) and `opened_at`, stored as a non-negative integer. The second is `peak_deviation_celsius`, the maximum across all `VALID` readings on the same task with `captured_at` in the closed interval from `opened_at` through the alert's resolution timestamp (or the current clock if still unresolved) of the larger of zero, the task's `temp_min_celsius` minus the reading's `temperature_celsius`, and the reading's `temperature_celsius` minus the task's `temp_max_celsius`; the value is non-negative and stored to two decimal places, round half up. The classification is then: if `duration_seconds` is at least 1800 seconds, or `peak_deviation_celsius` is at least 5.00 degrees Celsius, the level is `CRITICAL`; otherwise, if `duration_seconds` is at least 600 seconds, or `peak_deviation_celsius` is at least 2.00 degrees Celsius, the level is `MAJOR`; otherwise the level is `WARNING`. The thresholds are inclusive on the upper-band side.

The `notified_channels` set is recomputed monotonically on every level recomputation — once a channel is added it stays. When `level` is `WARNING`, the level's contributed channel set is `DRIVER`. When `level` is `MAJOR`, the contributed set is `DRIVER` together with `DISPATCH`. When `level` is `CRITICAL`, the contributed set is `DRIVER`, `DISPATCH`, and `CUSTOMER`. The alert's `notified_channels` is the union of its prior value with the new contribution.

### 3.7. Alert Response Workflow

A `DRIVER` or `DISPATCHER` acknowledges an alert, moving it from `OPEN` to `ACKNOWLEDGED`. Acknowledgement is permitted only while the parent task is in `DISPATCHED`, `IN_TRANSIT`, or `AT_STOP`. Each acknowledgement writes an `AuditLogEntry`.

Recording a first `ResponseAction` advances the alert from `ACKNOWLEDGED` to `IN_RESPONSE`. The action payload supplies `action_kind` — one of `VENTILATION`, `REFRIGERATION_ADJUSTMENT`, `TRANSSHIPMENT`, or `INSPECTION` — and an optional `notes` field of zero to five hundred characters. The server sets `executed_by_role` from the caller's `X-User-Role` (either `DRIVER` or `DISPATCHER`) and clock-stamps `executed_at`. The link to the parent alert is recorded as an immutable `alert_id`. An `AuditLogEntry` is written.

A `DISPATCHER` may escalate an `IN_RESPONSE` alert, advancing it to `ESCALATED`. Escalation expands `notified_channels` to include `CUSTOMER` (idempotent on subsequent escalates) and writes an `AuditLogEntry`. From `ESCALATED`, recording a further `ResponseAction` cycles the alert back to `IN_RESPONSE`.

Resolution is performed by a `DISPATCHER` and is valid from either `IN_RESPONSE` or `ESCALATED`. Two preconditions guard it: the parent task must be in `IN_TRANSIT`, `AT_STOP`, or `DELIVERED` and not in `CLOSED` or `ABORTED` (the cross-entity rule, reported as `ERR_TASK_NOT_RESOLVABLE` when violated), and at least one `ResponseAction` must already exist on the alert. As a side effect the server sets `resolved_at` to the current clock, finalises `duration_seconds` as `resolved_at` minus `opened_at`, runs the final level recomputation, and writes an `AuditLogEntry`. Once the parent task transitions from `DELIVERED` to `CLOSED`, every alert on the task whose status is `RESOLVED` is cascaded to `CLOSED`, with an audit-log entry written for each.

### 3.8. Closing Out a Task

A `CARRIER` closes a task from `DELIVERED` to `CLOSED`. The transition is rejected with `ERR_INVALID_STATE` when any alert on the task is still in `OPEN`, `ACKNOWLEDGED`, `IN_RESPONSE`, or `ESCALATED`. The server stamps `closed_at` to the current clock and cascades any `RESOLVED` alerts on the task to `CLOSED`. Tasks reach the terminal `CLOSED` and `ABORTED` states by these paths only.

### 3.9. Damage Assessment with Dual-Variant Calculation

After a task lands in `DELIVERED` or `CLOSED`, a `COMPLIANCE_OFFICER` may create a `DamageAssessment` in `DRAFT`. The payload carries `task_id` (which must refer to a task in `DELIVERED` or `CLOSED`), `damaged_quantity` (an integer that must satisfy at least one and at most the task's `cargo_quantity`, with violations reported as `ERR_QUANTITY_INVALID`), `damage_class` (one of `MINOR`, `MODERATE`, or `TOTAL_LOSS`), `salvage_pct` (a two-decimal number in the range from 0.00 through 0.99, naming the fraction of declared value recoverable as salvage on the damaged units), `cause_primary` (one of `TEMPERATURE_DEVIATION`, `DURATION`, `CARGO_SENSITIVITY`, or `OTHER`), and `evidence_alert_ids` (the list of supporting `Alert` ids — non-empty, with every referenced alert sharing the same `task_id` and being in either `RESOLVED` or `CLOSED`; violations are reported as `ERR_EVIDENCE_REQUIRED`). The payload also carries `variant`, the calculation-mode selector, which is required.

The computed `damage_amount_cents` is produced by a deterministic two-variant rule. First, the damage factor lookup table assigns 0.30 to `MINOR`, 0.60 to `MODERATE`, and 1.00 to `TOTAL_LOSS`. Second, the per-unit value is computed differently depending on `variant`. Under `variant` of `INSURED_VALUE`, the per-unit value in cents is the floor of the task's `cargo_value_cents` divided by the task's `cargo_quantity`; `invoice_unit_value_cents` is ignored under this variant. Under `variant` of `INVOICE_VALUE`, the per-unit value is `invoice_unit_value_cents` supplied in the payload, which must be a positive integer (greater than zero); a missing or non-positive `invoice_unit_value_cents` under this variant is rejected with `ERR_INVOICE_VALUE_REQUIRED`. Third, the per-unit damage in cents is the per-unit value multiplied by the damage factor for `damage_class` multiplied by one minus `salvage_pct`, rounded half up to a whole cent — this is the rounded per-unit damage. Fourth, the raw total is the per-unit damage in cents multiplied by `damaged_quantity`. Fifth and finally, `damage_amount_cents` is the smaller of the raw total and the task's vehicle `insured_cap_cents`; when the raw total equals the cap exactly no cap-clipping error is raised, and when the raw total exceeds the cap only the capped value is persisted (the unclipped raw total is not retained). The evaluation order is pinned: per-unit first and rounded, then multiplied by quantity, then capped.

The same rule is rerun on `PATCH` to mutable fields while the assessment is still `DRAFT` — `damaged_quantity`, `damage_class`, `salvage_pct`, `cause_primary`, `evidence_alert_ids`, `variant`, `invoice_unit_value_cents`. Finalising the assessment requires that `damage_amount_cents` has been computed (non-null) and that `evidence_alert_ids` is non-empty (size at least one). Finalising advances the assessment from `DRAFT` to `FINALIZED`; subsequent PATCH attempts to mutable fields are rejected with `ERR_INVALID_STATE`. Finalisation is the gate that lets a `ResponsibilityDecision` be drafted for the task.

### 3.10. Responsibility Determination, Mediation, and Finalisation

A `COMPLIANCE_OFFICER` opens a `ResponsibilityDecision` in `DRAFT` against a task that has at least one `FINALIZED` `DamageAssessment` and that has no other responsibility decision (decisions are unique per task). The payload carries `task_id`, `assessment_id` (pointing to a finalised damage assessment on the same task), the three party percentages `shipper_pct`, `carrier_pct`, and `consignee_pct` (each a two-decimal number in the range 0.00 through 1.00), and `split_method` — either `DURATION_WEIGHTED` or `SEVERITY_WEIGHTED`. The three percentages must sum to 1.00 exactly when rounded half up to two decimals; any other sum is rejected with `ERR_PCT_SUM_INVALID`. Drafting writes an `AuditLogEntry` with `action` of `DRAFTED`.

Alongside the stored percentages, the server returns an `advisory_split` computed from the evidence chain. Build the per-party time-in-custody segments from the chain of `HandoverRecord` rows on the task — each successive `handed_over_at` boundary partitions the task's lifetime into segments belonging to a `SHIPPER`, `CARRIER`, or `CONSIGNEE` principal, with the driver acting on behalf of the carrier. Gather the evidence alerts referenced by the assessment's `evidence_alert_ids`. Under `DURATION_WEIGHTED`, for each of the three parties sum, over the evidence alerts, the overlap in seconds between the alert's open-to-resolved interval and the custody segments belonging to that party; the advisory percentage for each party is that sum divided by the total across all parties. Under `SEVERITY_WEIGHTED`, for each evidence alert attribute its `peak_deviation_celsius` to the party whose custody segment covers the alert's `opened_at` moment, then sum per party and divide by the total across all parties. Either variant must yield three percentages summing to 1.00 exactly: round each to two decimals half up, and allocate any rounding remainder cents to the party with the largest pre-round share, breaking ties alphabetically in the order `CARRIER` > `CONSIGNEE` > `SHIPPER`. The advisory is also stored as an auxiliary field on the decision; the stored `shipper_pct`, `carrier_pct`, and `consignee_pct` reflect the negotiated decision and may differ from the advisory. A `PATCH` to the decision while in `DRAFT` recomputes the advisory; the same recomputation fires when the decision cycles back to `DRAFT` from `MEDIATION`. PATCH revisions must still preserve the sum-to-1.00 invariant or are rejected with `ERR_PCT_SUM_INVALID`.

Submitting the decision moves it from `DRAFT` to `UNDER_REVIEW`. From `UNDER_REVIEW`, each of the three parties — shipper, carrier, consignee — may accept; the server tracks acceptance per `X-User-ID`, and when all three parties have accepted the status moves to `ACCEPTED`. Any of the three parties may instead dispute, supplying a `reason`, which moves the decision from `UNDER_REVIEW` to `DISPUTED`. A compliance officer then enters mediation, advancing the decision from `DISPUTED` to `MEDIATION` and recording their `X-User-ID` as `mediator_id`. During mediation the compliance officer cycles the decision back to `DRAFT` via PATCH, revising the splits — again subject to the sum-to-one rule — which writes a fresh `DRAFTED` audit entry; the cycle of submit, accept, dispute, mediate may repeat.

Once the decision is `ACCEPTED`, a compliance officer finalises it, advancing it from `ACCEPTED` to `FINALIZED`. Segregation of duties is the load-bearing check here: the finalizing actor's `X-User-ID` must not equal any of the task's `shipper_id`, `carrier_id`, or `consignee_id` — that is, a party cannot finalise a decision that involves them. A violation is reported as `ERR_SEGREGATION_VIOLATION`. As side effects, `finalizing_role` is set to `COMPLIANCE_OFFICER`, `attributed_quantity` is set to the assessment's `damaged_quantity` (so the invariant that party-attributed quantity totals the assessment's damaged quantity is enforced), and an `AuditLogEntry` is written with `action` of `FINALIZED`. Finalisation cascades to the task: the task becomes eligible to be the subject of an insurance claim.

### 3.11. Insurance Claim Lifecycle and the Payout Invariant

A `CARRIER` reports an `InsuranceClaim` against a task whose responsibility decision is finalised. The payload carries `task_id`, `decision_id` (pointing to a `FINALIZED` responsibility decision on the same task — a non-finalised decision is rejected with `ERR_DECISION_NOT_FINALIZED`), and `requested_amount_cents` (a non-negative integer). The requested amount must not exceed the task's vehicle `insured_cap_cents`; a violation is reported as `ERR_INSURANCE_CAP_EXCEEDED`. On success the claim enters `REPORTED`.

The carrier prepares the evidence package, advancing the claim from `REPORTED` to `EVIDENCE_PREP`. The insurance adjuster then assesses, supplying `assessed_amount_cents` (an integer in the range from zero through `requested_amount_cents`, with out-of-range values reported as `ERR_AMOUNT_INVALID`); this advances the claim from `EVIDENCE_PREP` to `ASSESSMENT`. From `ASSESSMENT` the carrier or insurance adjuster may negotiate, advancing to `NEGOTIATING`, after which the adjuster reassesses (cycling back to `ASSESSMENT` with a revised `assessed_amount_cents`).

From `ASSESSMENT` the adjuster takes one of two terminal directions. Paying out advances the claim to `PAID_OUT`, and as a side effect `payout_amount_cents` is set to `assessed_amount_cents`. Paying requires `assessed_amount_cents` strictly greater than zero; an attempt to pay a zero-assessment claim is rejected. Rejecting the claim advances it to `REJECTED`, with `reason` supplied in the body, and as a side effect `payout_amount_cents` is set to zero.

After payout the adjuster may run a subrogation step, advancing the claim from `PAID_OUT` to `SUBROGATION`. The payload supplies `subrogation_recovered_cents` (an integer in the range from zero through the current `payout_amount_cents`, with out-of-range values reported as `ERR_AMOUNT_INVALID`). The conserved-quantity invariant binding assessment, payout and subrogation is: the net insurer outflow in cents equals the payout amount, which after subrogation equals `assessed_amount_cents` minus `subrogation_recovered_cents`. Implementing this, `subrogation_recovered_cents` is recorded and `payout_amount_cents` is set to the previous payout amount minus `subrogation_recovered_cents`, with a floor of zero applied. The claim closes by advancing from `SUBROGATION` to `CLOSED`; alternatively a paid-out claim with no subrogation step closes by advancing directly from `PAID_OUT` to `CLOSED`. The terminal states are `CLOSED` and `REJECTED`.

### 3.12. Compliance Reporting

A `COMPLIANCE_OFFICER` creates a `ComplianceReport` in `DRAFT` against a `regulatory_domain` (one of `FOOD`, `PHARMACEUTICAL`, or `BIOLOGICAL`) over an inclusive-start, exclusive-end period defined by `period_start` and `period_end` (each ISO 8601 UTC, with `period_end` strictly greater than `period_start`). Generating the report advances it from `DRAFT` to `GENERATED` and populates three counts. The set of in-period tasks is those `TransportTask` rows whose `cargo_type` equals the report's `regulatory_domain` and whose `planned_start_at` is at least `period_start` and strictly less than `period_end`; `task_count` is the size of that set. The set of in-period alerts is those `Alert` rows whose `task_id` is in the in-period task set and whose `opened_at` is at least `period_start` and strictly less than `period_end`; `alert_count` is the size of that set. `critical_alert_count` is the size of the subset of in-period alerts whose `level` is `CRITICAL`. Submission moves the report from `GENERATED` to `SUBMITTED`; the regulator's acknowledgement moves it from `SUBMITTED` to `ACKNOWLEDGED`.

### 3.13. Audit Log

Every alert lifecycle event and every responsibility-decision lifecycle event writes an `AuditLogEntry`. The entry's `subject_type` is either `ALERT` or `RESPONSIBILITY_DECISION`, and `subject_id` names the relevant row; `action` is the lifecycle verb — one of `OPENED`, `ACKNOWLEDGED`, `RESPONSE_RECORDED`, `ESCALATED`, `RESOLVED`, `CLOSED`, `DRAFTED`, `UNDER_REVIEW`, `DISPUTED`, `MEDIATED`, `ACCEPTED`, or `FINALIZED`; `actor_role` is the actor's `X-User-Role` for human actions, or `SYSTEM` for the automatic transitions (alert auto-open and the cascade close); `actor_id` is the literal string `system` for system actions and the actor's `X-User-ID` otherwise; and `occurred_at` is the ISO 8601 UTC clock timestamp of the action. The audit log is read by compliance officers and insurance adjusters, with filters by `subject_type` and `subject_id`.

## 4. Endpoint Definitions

All endpoints follow uniform conventions for status codes. New resources are returned with HTTP 201; reads, list endpoints, and state-mutating operations on existing resources return HTTP 200. The `_clock` test fixture endpoints return 200. Error responses use the codes called out alongside the `error_id` catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/advance | Advance the server clock by N seconds (test fixture). | SYSTEM |
| GET | /_clock | Return current server clock (test fixture). | SYSTEM |
| POST | /vehicles | Register a vehicle. | CARRIER |
| GET | /vehicles/{id} | Fetch a vehicle. | CARRIER, DISPATCHER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| GET | /vehicles | List vehicles with pagination. | CARRIER, DISPATCHER, COMPLIANCE_OFFICER |
| POST | /drivers | Register a driver. | CARRIER |
| GET | /drivers/{id} | Fetch a driver. | CARRIER, DISPATCHER, COMPLIANCE_OFFICER |
| POST | /transport-tasks | Create a transport task in PLANNED. | SHIPPER, DISPATCHER |
| GET | /transport-tasks/{id} | Fetch a task with its stops. | SHIPPER, CARRIER, DRIVER, CONSIGNEE, DISPATCHER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| PATCH | /transport-tasks/{id} | Update mutable fields. | DISPATCHER |
| GET | /transport-tasks | List tasks with filters. | SHIPPER, CARRIER, DISPATCHER, COMPLIANCE_OFFICER |
| POST | /transport-tasks/{id}/dispatch | Transition PLANNED to DISPATCHED. | DISPATCHER |
| POST | /transport-tasks/{id}/depart | Transition DISPATCHED to IN_TRANSIT. | DRIVER |
| POST | /transport-tasks/{id}/stops/{stop_id}/arrive | Transition IN_TRANSIT to AT_STOP for the lowest-sequence PENDING stop. | DRIVER |
| POST | /transport-tasks/{id}/stops/{stop_id}/depart | Transition AT_STOP to IN_TRANSIT (intermediate stops only). | DRIVER |
| POST | /transport-tasks/{id}/stops/{stop_id}/handovers | Record a HandoverRecord; transitions stop to HANDED_OVER and may cascade parent to DELIVERED. | DRIVER |
| POST | /transport-tasks/{id}/stops/{stop_id}/skip | Mark a stop SKIPPED. | DISPATCHER |
| POST | /transport-tasks/{id}/close | Transition DELIVERED to CLOSED. | CARRIER |
| POST | /transport-tasks/{id}/abort | Abort a task from any non-terminal state. | DISPATCHER |
| POST | /transport-tasks/{id}/temperature-readings | Ingest a sensor reading. Idempotent. | SYSTEM, DISPATCHER |
| GET | /transport-tasks/{id}/temperature-readings | List readings with filter. | SHIPPER, CARRIER, DRIVER, DISPATCHER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| POST | /transport-tasks/{id}/temperature-readings/archive | Archive valid readings on a closed task. | COMPLIANCE_OFFICER |
| GET | /alerts/{id} | Fetch an alert. | SHIPPER, CARRIER, DRIVER, DISPATCHER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER, CONSIGNEE |
| GET | /alerts | List alerts. | SHIPPER, CARRIER, DISPATCHER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| POST | /alerts/{id}/acknowledge | Transition OPEN to ACKNOWLEDGED. | DRIVER, DISPATCHER |
| POST | /alerts/{id}/responses | Record a ResponseAction. | DRIVER, DISPATCHER |
| POST | /alerts/{id}/escalate | Transition IN_RESPONSE to ESCALATED. | DISPATCHER |
| POST | /alerts/{id}/resolve | Transition IN_RESPONSE or ESCALATED to RESOLVED. | DISPATCHER |
| POST | /damage-assessments | Create a damage assessment in DRAFT. | COMPLIANCE_OFFICER |
| PATCH | /damage-assessments/{id} | Update DRAFT-only mutable fields. | COMPLIANCE_OFFICER |
| POST | /damage-assessments/{id}/finalize | Transition DRAFT to FINALIZED. | COMPLIANCE_OFFICER |
| GET | /damage-assessments/{id} | Fetch a damage assessment. | SHIPPER, CARRIER, CONSIGNEE, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| POST | /responsibility-decisions | Create a decision in DRAFT. | COMPLIANCE_OFFICER |
| PATCH | /responsibility-decisions/{id} | Revise splits while in DRAFT. | COMPLIANCE_OFFICER |
| POST | /responsibility-decisions/{id}/submit | Transition DRAFT to UNDER_REVIEW. | COMPLIANCE_OFFICER |
| POST | /responsibility-decisions/{id}/accept | Party acceptance toward ACCEPTED. | SHIPPER, CARRIER, CONSIGNEE |
| POST | /responsibility-decisions/{id}/dispute | Transition UNDER_REVIEW to DISPUTED. | SHIPPER, CARRIER, CONSIGNEE |
| POST | /responsibility-decisions/{id}/mediate | Transition DISPUTED to MEDIATION. | COMPLIANCE_OFFICER |
| POST | /responsibility-decisions/{id}/finalize | Transition ACCEPTED to FINALIZED. | COMPLIANCE_OFFICER |
| GET | /responsibility-decisions/{id} | Fetch a decision. | SHIPPER, CARRIER, CONSIGNEE, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| POST | /insurance-claims | Report a claim. | CARRIER |
| POST | /insurance-claims/{id}/prepare-evidence | Transition REPORTED to EVIDENCE_PREP. | CARRIER |
| POST | /insurance-claims/{id}/assess | Pin assessed_amount_cents. | INSURANCE_ADJUSTER |
| POST | /insurance-claims/{id}/negotiate | Transition ASSESSMENT to NEGOTIATING. | CARRIER, INSURANCE_ADJUSTER |
| POST | /insurance-claims/{id}/pay | Transition ASSESSMENT to PAID_OUT. | INSURANCE_ADJUSTER |
| POST | /insurance-claims/{id}/reject | Transition ASSESSMENT to REJECTED. | INSURANCE_ADJUSTER |
| POST | /insurance-claims/{id}/subrogate | Transition PAID_OUT to SUBROGATION. | INSURANCE_ADJUSTER |
| POST | /insurance-claims/{id}/close | Transition to CLOSED. | INSURANCE_ADJUSTER |
| GET | /insurance-claims/{id} | Fetch a claim. | CARRIER, COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| POST | /compliance-reports | Create a compliance report in DRAFT. | COMPLIANCE_OFFICER |
| POST | /compliance-reports/{id}/generate | Transition DRAFT to GENERATED. | COMPLIANCE_OFFICER |
| POST | /compliance-reports/{id}/submit | Transition GENERATED to SUBMITTED. | COMPLIANCE_OFFICER |
| POST | /compliance-reports/{id}/acknowledge | Transition SUBMITTED to ACKNOWLEDGED. | COMPLIANCE_OFFICER |
| GET | /compliance-reports/{id} | Fetch a compliance report. | COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |
| GET | /audit-log | List audit log entries. | COMPLIANCE_OFFICER, INSURANCE_ADJUSTER |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_SEGREGATION_VIOLATION | 403 |
| ERR_TASK_NOT_RESOLVABLE | 409 |
| ERR_DECISION_NOT_FINALIZED | 409 |
| ERR_EVIDENCE_REQUIRED | 422 |
| ERR_INVOICE_VALUE_REQUIRED | 422 |
| ERR_VEHICLE_OVERLAP | 409 |
| ERR_DRIVER_HOURS_EXCEEDED | 409 |
| ERR_READING_OUT_OF_WINDOW | 422 |
| ERR_PCT_SUM_INVALID | 422 |
| ERR_INSURANCE_CAP_EXCEEDED | 422 |
| ERR_QUANTITY_INVALID | 422 |
| ERR_AMOUNT_INVALID | 422 |
| ERR_VALIDATION | 422 |
| ERR_IDEMPOTENT_REPLAY | 200 |
| ERR_HANDOVER_ALREADY_EXISTS | 409 |
