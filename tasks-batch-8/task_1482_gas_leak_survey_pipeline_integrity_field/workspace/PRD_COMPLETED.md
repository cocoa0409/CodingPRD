# Gas Leak Survey Pipeline Integrity API — Product Requirements Document

## 1. Introduction

Local gas distribution companies operate under an integrity-management mandate: every mile of buried main and service line must be surveyed for leaks on a regulator-defined cadence, every leak found must be graded and repaired inside a grade-dependent clock, every cathodic-protection test point must be read and its anomalies dispositioned, and the whole program must be defensible in a filing to the regulator. Today that evidence chain lives in paper route books, spreadsheets, and the memories of field supervisors. When a regulator asks "show me the overdue Grade 1 leaks on transmission pipe in high consequence areas," the answer takes days.

This document specifies an API for the field-integrity program of a gas local distribution company. The API maintains a registry of pipe segments, an instrument inventory with calibration discipline, a survey-route lifecycle from planning through completion, a leak record with a formal grading and re-grading workflow, a repair-dispatch pipeline with excavation-permit tracking, cathodic-protection readings with anomaly disposition, a versioned risk-model snapshot store, and a compliance-report lifecycle that pins its evidentiary inputs before submission to a regulator. Segregation of duties is enforced between the people who perform field work and the people who attest to it.

The intended consumers are the internal engineering, field-operations, and compliance teams who will build survey-planning tools, dispatch consoles, and regulatory filing automation on top of this API.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting individual, and `X-User-Role` identifying the acting role. The role set is exactly five roles, spelled as follows: `IntegrityAnalyst`, `FieldTechnician`, `ComplianceOfficer`, `DispatchCoordinator`, and `CalibrationTech`. A request missing either header, or carrying a role string outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

All five roles are entity-backed identities. When `X-User-Role` is `IntegrityAnalyst`, `X-User-ID` is the `id` of the acting `IntegrityAnalyst` record; likewise for `FieldTechnician`, `ComplianceOfficer`, `DispatchCoordinator`, and `CalibrationTech` — in each case `X-User-ID` is the `id` of a persisted record of that entity type, and any ownership or segregation-of-duties check that compares a requester to a stored user reference (for example, the `technician_id` recorded on a survey run) compares that field to the `X-User-ID` header value. Authentication itself verifies only that both headers are present and that the role string is recognized; the server does not verify that `X-User-ID` references an existing personnel record except where a business rule dereferences it (starting a survey route resolves the `FieldTechnician` record, and filing a report resolves the `ComplianceOfficer` record — see §3.4 and §3.11). New personnel records of each type are created by an `IntegrityAnalyst`; there is no self-registration.

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

A request to a path the API does not define yields `ERR_NOT_FOUND` (HTTP 404); a request to a defined path with an unsupported HTTP method yields an `ERR_INVALID_REQUEST` error body with HTTP status 405.

### 2.3. Pagination

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may be at most 100. The `offset` parameter defaults to 0 and must be at least 0. A non-integer `limit` or `offset`, or a value outside these bounds, yields `ERR_INVALID_REQUEST`. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless an endpoint documents otherwise, list results are ordered by `created_at` ascending, with ties broken by creation order (earlier-created first). Boolean filter query parameters (such as `is_high_consequence_area` and `is_anomalous`) accept `true`/`1` and `false`/`0`, case-insensitively; any other value yields `ERR_INVALID_REQUEST`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` field holding a server-minted UUID with no type prefix, and a `created_at` field holding an ISO 8601 UTC timestamp with three fractional digits. All resources additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer starting at 1 on creation and incremented by exactly 1 on every mutation of that resource, including mutations caused by cascading side effects from operations on other resources).

All time-dependent logic in this system — survey-window checks, calibration expiry, permit expiry, overdue-leak detection, report filing deadlines, the 90-day lookback for clean cathodic-protection readings — is evaluated against a **server logical clock**, never against real wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z` and must not fall back to wall-clock time before it is explicitly set. An admin-only test-driving capability, restricted to `IntegrityAnalyst`, sets the logical clock to a supplied `to_iso8601` instant — any instant is accepted, forward or backward, with no monotonicity constraint — and responds with HTTP 200 and a body of the form `{"current_utc": "<the new logical time>"}`; every computed field and every time-gated transition then evaluates against the new logical time. The automatic time-based transitions of §2.6 and §3.6 are applied by a sweep that runs immediately when the clock is set and before every subsequent request is processed. Timestamps recorded by the system (for example `discovered_at`, `started_at`, `submitted_at`) are always logical-clock readings, precise to the second.

### 2.5. Validation Order and Error Selection

When a request violates more than one rule, the error returned is determined by a fixed priority order, evaluated from first to last. Authentication comes first: a missing or invalid `X-User-Role` or `X-User-ID` header yields `ERR_UNAUTHENTICATED` before anything else is examined. Authorization comes second: a recognized role invoking an endpoint it is not permitted to use yields `ERR_FORBIDDEN`. Third, every identifier referenced by the request — path-template identifiers resolved left to right, then identifiers referenced in the request body — must resolve to an existing entity, else `ERR_NOT_FOUND`. Fourth, the target entity must be in a state from which the requested transition is defined, else the state-specific conflict error (an HTTP 409 error such as `ERR_ROUTE_NOT_PLANNED` or `ERR_LEAK_NOT_OPEN`; where no domain-specific state error exists, `ERR_INVALID_STATE`). Only after those four classes pass are business rules evaluated: business-safety checks (instrument calibration status, segregation of duties, officer jurisdiction), then business-temporal checks (scheduled windows, filing deadlines, permit validity), then business-constraint checks (crew capacity, crew qualification, coverage minimums, regrade limits), then business-referential checks (snapshot currency, post-repair survey existence, cleanup readings), and finally optimistic-concurrency version checks (§2.7). Malformed input, a missing required field, or an out-of-range value yields `ERR_INVALID_REQUEST` (HTTP 400); these request-parse failures are detected as the request is parsed — after authentication, authorization, and path-identifier resolution, but before body-identifier resolution, state checks, and business checks. Uniqueness violations (also `ERR_INVALID_REQUEST`) are detected at the point the new resource is created, after any state checks on the target.

### 2.6. Instrument Calibration Discipline

Every survey instrument belongs to one of five instrument types — `FLAME_IONIZATION`, `CGI`, `OMD`, `AERIAL_LIDAR`, `CP_VOLTMETER` — and may be used in a survey run only while its status is `IN_SERVICE`. Calibration is recorded against a reference gas of known concentration: the technician supplies `reference_gas_ppm` (which must be greater than 0, else `ERR_INVALID_REQUEST`) and the instrument's `observed_ppm`, and the system computes `drift_pct` as the absolute difference between `observed_ppm` and `reference_gas_ppm`, divided by `reference_gas_ppm`, multiplied by 100, recorded at full precision without rounding. If the drift is at most 5.0 percent the calibration outcome is `PASS`; strictly above 5.0 percent it is `FAIL`. A calibration attempted on a `RETIRED` instrument is rejected with `ERR_INVALID_STATE`.

Each instrument type has a fixed recalibration interval: 90 days for `FLAME_IONIZATION`, 60 days for `CGI`, 90 days for `OMD`, 180 days for `AERIAL_LIDAR`, and 365 days for `CP_VOLTMETER`. A passing calibration sets the instrument's `calibrated_at` to the current logical clock and sets `calibration_due_at` to `calibrated_at` plus the interval for the instrument's type. Whenever the logical clock passes an instrument's `calibration_due_at`, the instrument automatically moves from `IN_SERVICE` to `OUT_OF_CALIBRATION`; a subsequent passing calibration returns it to `IN_SERVICE`. A newly registered instrument starts in `IN_SERVICE` with `calibrated_at` and `calibration_due_at` both null until its first calibration.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; no other endpoint takes a version field. First, scheduling a repair for a leak requires the request body to carry `expected_leak_version`, the value of the leak's `version` the dispatcher last observed; if the leak's current `version` has advanced since then — for example because the leak was re-graded or already scheduled — the request is rejected with `ERR_STALE_LEAK_VERSION` (HTTP 412). Second, submitting a draft compliance report for review requires `expected_report_version` matching the report's current `version`; a mismatch is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412). Third, binding risk-model snapshots onto a draft compliance report likewise requires `expected_report_version`, with the same `ERR_STALE_REPORT_VERSION` (HTTP 412) on mismatch. In all three cases the rejected writer must re-read the resource and re-issue against the fresh version; the server never merges or overwrites silently.

### 2.8. Pipe Segment Posture

Every pipe segment carries a derived `posture` field, one of `NORMAL`, `ELEVATED`, or `CRITICAL`, recomputed whenever the inputs change. Posture is derived from the segment's open-leak counters and its open cathodic-protection anomalies, evaluated in this order: if the segment has at least one open Grade 1 leak (`open_grade1_count` of 1 or more), posture is `CRITICAL`. Otherwise, if it has two or more open Grade 2 leaks (`open_grade2_count` of at least 2), posture is `CRITICAL`. Otherwise, if it has exactly one open Grade 2 leak, or at least one cathodic-protection anomaly in `OPEN` or `ACKNOWLEDGED` status, posture is `ELEVATED`. Otherwise, if it has three or more open Grade 3 leaks, posture is `ELEVATED`. In all remaining cases posture is `NORMAL`.

### 2.9. Precision, Rounding, and Numeric Conventions

Risk scores are expressed on a 0–100 scale rounded half-up to 2 decimal places. The crew dispatch ranking score is rounded half-up to 4 decimal places. Ratios embedded in compliance report payloads are rounded half-up to 4 decimal places at the ratio level, before assembly into the payload; the final aggregate is never re-rounded. Leak concentrations are recorded as integer ppm values; a `concentration_ppm` supplied with a fractional part is rounded half-up to the nearest integer at recording time, before grading. All computed timestamps are precise to the second. Interval arithmetic that yields fractional days (the re-survey interval rule of §3.9) truncates down to a whole number of days.

### 2.10. Cascade and Compensating-Action Semantics

Several operations mutate more than one resource in a single atomic action: taking a segment out of service abandons its open leaks and cancels their undispatched repair orders; permit expiry can unwind a dispatched repair back to pending; rejecting a survey run abandons the leaks it reported. Every cascade described in §3 updates each touched resource's `updated_at` and increments that resource's `version` by 1, exactly as if the mutation had been applied individually. Compensating actions are explicitly directional — a cancelled repair order moves its leak from `REPAIR_SCHEDULED` back to `OPEN`, not to any other state.

## 3. Business Logic & Workflows

### 3.1. Registering Pipe Segments

An `IntegrityAnalyst` onboards infrastructure by creating pipe segments. The creation payload carries the operator-assigned `segment_code` (which must be unique across all segments, e.g. "ML-2024-NORTH-001"), the `install_year` (which must be 1900 or later, else `ERR_INVALID_REQUEST`), the `material` (one of `STEEL`, `CAST_IRON`, `PLASTIC_PE`, `PLASTIC_PVC`, `COPPER`), the `diameter_inches`, the `length_feet`, the `operating_pressure_psi`, the `pressure_class` (one of `DISTRIBUTION`, `TRANSMISSION`, `SERVICE`), and `is_high_consequence_area` indicating whether the segment lies in a high consequence area under 49 CFR §192.903. An optional `region_hint` may be supplied; it is used by the crew dispatch ranking described in §3.6, and contributes nothing when null. A new segment starts with all three open-grade counters at 0, `posture` of `NORMAL`, `status` of `ACTIVE`, and both `last_surveyed_at` and `next_survey_due_at` null; its `risk_score` is computed at creation per §3.8.

Segment listing supports filtering by `status`, `posture`, `pressure_class`, and `is_high_consequence_area`. From a segment one can also navigate to its leaks (filterable by `status` and `grade`), to its cathodic-protection readings (filterable by `anomaly_status` and `is_anomalous`), and to a derived compliance summary exposing the segment's `overdue_leak_count`, current `posture`, `next_survey_due_at`, the three open-grade counters, and the current `risk_score`. A leak counts toward `overdue_leak_count` when its status is one of `OPEN`, `REPAIR_SCHEDULED`, `UNDER_REPAIR`, or `REPAIRED_PENDING_VERIFICATION` and the current logical clock is strictly later than the leak's `repair_due_at`; a leak whose `repair_due_at` equals the current logical clock exactly is not yet overdue. A separate on-demand capability, restricted to `IntegrityAnalyst`, recomputes the segment's `next_survey_due_at` live using current counters and current anomaly flags, anchoring the interval at the segment's `last_surveyed_at` when one is recorded and at the current logical clock otherwise, and returning the recomputed `next_survey_due_at` and the `interval_days` that produced it; because it uses current values rather than the snapshot taken at route completion, its answer may differ from the stored `next_survey_due_at` whenever leaks or anomalies have changed since the last completed route.

### 3.2. Instrument Lifecycle

A `CalibrationTech` registers an instrument with its unique `serial_number` (e.g. "FI-2241-A") and `instrument_type`. Calibration events are then recorded against the instrument over its life, each producing a persisted `Calibration` record holding the `instrument_id`, the `performed_by_user_id` of the `CalibrationTech` (taken from `X-User-ID`), the `reference_gas_ppm`, the `observed_ppm`, the computed `drift_pct`, and the computed `outcome`. A calibration whose drift exceeds the 5.0 percent ceiling is rejected with `ERR_CALIBRATION_DRIFT_EXCEEDED` before any record is created — so every persisted `Calibration` has `outcome` of `PASS` — and leaves the instrument's status untouched; a passing calibration persists the record, refreshes `calibrated_at` and `calibration_due_at` per the interval table in §2.6, and returns the instrument to `IN_SERVICE` if it had drifted out. The calibrate endpoint responds with HTTP 201 and the created `Calibration` record (not the instrument).

Retiring an instrument requires the instrument to be `IN_SERVICE` — an instrument in any other status is rejected with `ERR_INVALID_STATE` — and is then allowed only when no survey run in `DRAFT` or `SUBMITTED` status references it; otherwise the retire is refused with `ERR_INSTRUMENT_IN_USE`. A retired instrument (`RETIRED`) never returns to service. Instruments can be listed with filters on `status` and `instrument_type`, and each instrument exposes its calibration history.

### 3.3. Personnel and Repair Crews

An `IntegrityAnalyst` provisions the org's people. A `FieldTechnician` record carries a unique `employee_code`, `full_name`, a `qualified_methods` list naming the survey methods the technician is certified to perform — every entry must be one of the four survey methods of §3.4, else `ERR_INVALID_REQUEST` — and a `home_region`. A `ComplianceOfficer` record carries `employee_code`, `full_name`, and a `jurisdiction_scope` list of regulators the officer is authorized to file with — every entry must be one of the three regulators of §3.11, else `ERR_INVALID_REQUEST`. `CalibrationTech`, `DispatchCoordinator`, and `IntegrityAnalyst` records carry `employee_code` and `full_name`. For every personnel record type, `employee_code` must be unique among records of that same type; a duplicate is rejected with `ERR_INVALID_REQUEST`. Every personnel record has a `status` of `ACTIVE`, `SUSPENDED`, or `TERMINATED`; a newly created record starts `ACTIVE`, and personnel listings accept a `status` filter.

Repair crews are managed separately by the `DispatchCoordinator`. A `RepairCrew` is created with a unique `crew_code`, a `home_region`, an `is_qualified_excavation` flag, and a `max_concurrent_orders` capacity (which must be at least 0, else `ERR_INVALID_REQUEST`); a new crew starts with `open_order_count` of 0 and `status` of `AVAILABLE`. The system maintains `open_order_count` — the number of the crew's repair orders currently in `DISPATCHED` or `ON_SITE` status — and derives the crew's `status` automatically: `AT_CAPACITY` when `open_order_count` reaches `max_concurrent_orders`, back to `AVAILABLE` when it falls below. A coordinator may move a crew to `OFF_DUTY` at any time from `AVAILABLE`; from `AT_CAPACITY` the move is allowed only when the crew has no open repair orders, else `ERR_CREW_HAS_OPEN_ORDERS`; a crew already `OFF_DUTY` rejects the move with `ERR_INVALID_STATE`. Setting a crew back on duty requires it to be `OFF_DUTY` (any other state yields `ERR_INVALID_STATE`) and returns it to `AVAILABLE`. Crew listings filter by `status`, and a crew's assigned repair orders can be listed with a `dispatch_status` filter.

### 3.4. Planning and Executing Survey Routes

A `DispatchCoordinator` plans a survey route with a unique `route_code`, a `survey_method` (one of `WALKING`, `MOBILE`, `AERIAL`, `PATROL`), and an authorized window from `scheduled_window_start` (inclusive) to `scheduled_window_end` (exclusive); the two window endpoints are not cross-validated at creation. The route begins in `PLANNED`. While `PLANNED`, the coordinator adds segments to the route as `RouteSegmentAssignment` records, each referencing the target segment via `segment_id` and carrying a 1-based `sequence_index` (a value below 1 yields `ERR_INVALID_REQUEST`) giving the order in which the segment is walked; adding to a route that is no longer `PLANNED` is refused with `ERR_ROUTE_NOT_PLANNED`. The server does not enforce uniqueness of `sequence_index` or of the referenced segment across a route's assignments. An assignment's `status` is one of `PENDING`, `COVERED`, or `SKIPPED`, and each assignment starts in `PENDING`.

Dispatching the route moves it `PLANNED → DISPATCHED` and is refused with `ERR_ROUTE_NOT_PLANNED` if the route is not `PLANNED`, with `ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT` if any assignment references a segment whose `status` is not `ACTIVE`, and with `ERR_ROUTE_WINDOW_PASSED` if the logical clock has already reached `scheduled_window_end`. A `FieldTechnician` then starts the route (`DISPATCHED → IN_PROGRESS`), which requires the route to be `DISPATCHED` (`ERR_ROUTE_NOT_DISPATCHED`), then requires the caller's `X-User-ID` to reference an existing `FieldTechnician` record (`ERR_NOT_FOUND`), then requires the technician's `qualified_methods` to include the route's `survey_method` (`ERR_TECHNICIAN_NOT_QUALIFIED`), and requires the logical clock to be within the half-open window from `scheduled_window_start` to `scheduled_window_end` (`ERR_OUTSIDE_SCHEDULED_WINDOW`). A route may be aborted from either `PLANNED` or `DISPATCHED` by a `DispatchCoordinator`, moving it to the terminal state `ABORTED`; a route in any other state is rejected with `ERR_ROUTE_NOT_ABORTABLE`.

While the route is in progress, the technician records survey runs against it. Creating a run takes the `route_id`, the `instrument_id` of the instrument in use, and the `distance_covered_feet` (which must be at least 0, else `ERR_INVALID_REQUEST`); the server stamps `technician_id` from `X-User-ID` and `started_at` from the logical clock, and the run begins in `DRAFT`. Beyond existence, the route's status is not checked at run creation — a run may be created against a route in any status. The instrument referenced must be `IN_SERVICE` at run start, and the same check is repeated when the run is submitted — both are enforced with `ERR_INSTRUMENT_OUT_OF_CALIBRATION`. Submitting a run (`DRAFT → SUBMITTED`) evaluates its checks in the order given by §2.5: ownership first, so the caller must be the technician who recorded the run (`ERR_NOT_RUN_OWNER`, HTTP 403), then state, so the run must be `DRAFT` (`ERR_RUN_NOT_DRAFT`), then instrument currency (`ERR_INSTRUMENT_OUT_OF_CALIBRATION`). A run also carries an `ended_at` timestamp; the run ends at submission, and `ended_at` is stamped from the logical clock at that point.

Review is performed by an `IntegrityAnalyst`. Accepting a run (`SUBMITTED → ACCEPTED`) evaluates three checks in the order given by §2.5: the run must be `SUBMITTED` (`ERR_RUN_NOT_SUBMITTED`); segregation of duties requires the accepting analyst not be the technician who recorded the run (`ERR_SEGREGATION_OF_DUTIES`); and the run's `coverage_pct` must be at least 95 (`ERR_COVERAGE_BELOW_MINIMUM`). Coverage follows a prefix model over all of the route's assignments, whatever their current status, walked in `sequence_index` order: an assignment lies inside the run's coverage while the cumulative `length_feet` of the assignments preceding it plus its own `length_feet` is at most the run's `distance_covered_feet`, and coverage stops at the first assignment that does not fit — later assignments are not covered even if they would fit on their own. `coverage_pct` is the summed `length_feet` of the covered prefix divided by the total assigned length, multiplied by 100 (0 when the route has no assignments); it is computed and stored when the run is created and recomputed at acceptance. On acceptance, every assignment inside the run's coverage is set to `COVERED`; every leak reported from this run remains `OPEN`; the segment open-grade counters refresh; and `posture` is recomputed for every covered segment. Rejecting a run (`SUBMITTED → REJECTED`) requires only `SUBMITTED` state and abandons every `OPEN` leak that references the run — those leaks move to `ABANDONED_SEGMENT` — then recomputes counters and posture on the affected segments.

Completing the route (`IN_PROGRESS → COMPLETED`) requires `IN_PROGRESS` state (`ERR_ROUTE_NOT_IN_PROGRESS`) and at least one `ACCEPTED` survey run for the route (`ERR_NO_ACCEPTED_RUN`); any `FieldTechnician` may complete the route — no ownership check ties completion to the technician who started it. On completion, for every assignment marked `COVERED`, the segment's `last_surveyed_at` is set to the completion timestamp and `next_survey_due_at` is recomputed per the re-survey interval rule of §3.9, and `risk_score` is recomputed for every covered segment per §3.8. Survey runs are listable with filters on `status`, `route_id`, and `instrument_id`; routes filter by `status` and `survey_method`; assignments by `status`.

### 3.5. Leak Reporting, Grading, and Re-Grading

A `FieldTechnician` reports a leak discovered during a survey run with a payload naming the `segment_id`, the `survey_run_id` that detected it, the measured `concentration_ppm`, the optional `distance_to_building_feet` (null when the leak sits in an open field), the `bar_hole_reading_pct_lel` (a bar-hole reading expressed as percent of the lower explosive limit, from 0 to 100), and `is_migration_evidence` indicating whether gas migration was observed. Beyond existence, no status check is applied to the referenced segment or survey run. The server stamps `discovered_at` from the logical clock, computes the `grade`, computes `repair_due_at`, increments the segment's matching open-grade counter, recomputes the segment's `posture`, and marks any risk-model snapshot touching the segment as stale. A leak is born in `OPEN` status with `regrade_count` of 0.

Grading is threshold-based and evaluated in order. The leak is `G1` if the bar-hole reading is at least 25 percent of LEL, or if migration evidence is present and the distance to the nearest building is at most 20 feet. Failing that, the leak is `G2` if `concentration_ppm` is at least 10000, or if a building distance was recorded and is at most 50 feet, or if the bar-hole reading is at least 5 percent of LEL. Otherwise the leak is `G3`. The grade sets the repair clock: `repair_due_at` is `discovered_at` plus 1 day for `G1`, 30 days for `G2`, or 365 days for `G3`. When the segment lies in a high consequence area (`is_high_consequence_area` true), grading is conservative — whenever the inputs land exactly on a threshold boundary the grade escalates one level (`G3` becomes `G2`, `G2` becomes `G1`; `G1` remains `G1`). The boundaries that trigger escalation are exactly: a bar-hole reading equal to 25, a bar-hole reading equal to 5, a `concentration_ppm` equal to 10000, a building distance equal to 50 feet, or a building distance equal to 20 feet together with migration evidence. Outside high consequence areas the thresholds apply exactly as written.

A technician may re-grade an `OPEN` leak, supplying a `new_grade` and a free-text `reason`. Regrading requires the leak to be `OPEN` (`ERR_LEAK_NOT_OPEN`); then, per the validation order of §2.5, the regrade ceiling is evaluated next — a leak whose `regrade_count` has already reached the ceiling of 3 rejects a further attempt with `ERR_REGRADE_LIMIT_EXCEEDED` — and finally the `new_grade` must differ from the current `grade` (`ERR_REGRADE_SAME_GRADE`). Each regrade persists a `RegradeEvent` recording the `leak_id`, the `previous_grade`, the `new_grade`, the `reason`, the `performed_by_user_id` of the technician, and the `triggered_at` timestamp; it recomputes `repair_due_at` from the new grade against the **original** `discovered_at`; it shifts the segment's open-grade counters (decrementing the old grade's counter, incrementing the new grade's) and recomputes `posture`; it increments `regrade_count` by 1; and it marks risk-model snapshots touching the segment stale. Leaks list with filters on `status`, `grade`, and `segment_id`, and each leak exposes its regrade-event history.

### 3.6. Repair Dispatch and the Excavation Permit Track

A `DispatchCoordinator` schedules repair of an `OPEN` leak on an `ACTIVE` segment by supplying the `repair_method` — one of `CLAMP`, `WRAP`, `CUT_AND_REPLACE`, `ABANDON_SEGMENT`, `INSERT_LINER` — together with the OCC field `expected_leak_version` (§2.7). Scheduling is rejected with `ERR_LEAK_NOT_OPEN` if the leak is not `OPEN`, with `ERR_SEGMENT_NOT_ACTIVE` if the segment is not `ACTIVE`, and with `ERR_STALE_LEAK_VERSION` if the version does not match. On success the leak moves `OPEN → REPAIR_SCHEDULED` and a `RepairOrder` is created in `PENDING_DISPATCH` with its `priority` mapped from the leak's grade: `G1` maps to `P1_EMERGENCY`, `G2` to `P2_URGENT`, `G3` to `P3_ROUTINE`; the endpoint responds with HTTP 201 and the created `RepairOrder`. The new order's `excavation_permit_status` starts at `PERMIT_REQUIRED` for the two excavation methods and `NOT_REQUIRED` for the others. The order's `crew_id` and `dispatched_at` are null until dispatch.

The repair order carries two independent state dimensions. `dispatch_status` runs `PENDING_DISPATCH → DISPATCHED → ON_SITE → WORK_COMPLETE` (with `CANCELLED` as a terminal alternative reachable from `PENDING_DISPATCH` or `DISPATCHED`). `excavation_permit_status` runs `NOT_REQUIRED | PERMIT_REQUIRED | PERMIT_APPLIED | PERMIT_GRANTED | PERMIT_DENIED | PERMIT_EXPIRED` and evolves independently of dispatch progress. The two excavation methods — `CUT_AND_REPLACE` and `ABANDON_SEGMENT` — require a granted, unexpired permit before dispatch.

Permit application is a `ComplianceOfficer` action on an order still in `PENDING_DISPATCH` whose `excavation_permit_status` is `PERMIT_REQUIRED`; the officer supplies the municipality-issued `permit_number` (unique across all permits), the issuing `jurisdiction`, and the `expires_at` expiry timestamp. The attempt is refused with `ERR_ORDER_NOT_PENDING_DISPATCH` if the order has left `PENDING_DISPATCH`, and with `ERR_PERMIT_NOT_REQUIRED` if the order's permit status is not `PERMIT_REQUIRED`. Success creates an `ExcavationPermit` in `APPLIED` status with `applied_at` stamped from the logical clock, and flips the order's `excavation_permit_status` to `PERMIT_APPLIED`. The officer later records the municipality's decision: granting requires the permit to be `APPLIED` (`ERR_PERMIT_NOT_APPLIED`), stamps `granted_at`, and flips the order to `PERMIT_GRANTED`; denying likewise requires `APPLIED` and flips the order to `PERMIT_DENIED`. If the logical clock passes a granted permit's `expires_at` while the parent order is not yet `WORK_COMPLETE`, the permit automatically becomes `EXPIRED`, the order's `excavation_permit_status` flips to `PERMIT_EXPIRED`, and — if the order was `DISPATCHED` or `ON_SITE` at the time — the system performs a compensating unwind: the order returns to `PENDING_DISPATCH` with its `crew_id` and `dispatched_at` cleared to null, the crew's `open_order_count` decrements (recomputing crew `status`), and the leak reverts to `REPAIR_SCHEDULED`.

Dispatching an order may name a target crew explicitly via an optional `crew_id`, or omit it and let the selector policy choose. Either way, dispatch enforces, after the state check, in the order given by §2.5: the order must be `PENDING_DISPATCH` (`ERR_ORDER_NOT_PENDING_DISPATCH`); the target crew must not be `OFF_DUTY` (`ERR_CREW_OFF_DUTY`); for the two excavation methods a permit must exist in `GRANTED` status with `expires_at` later than the current logical clock (`ERR_NO_VALID_EXCAVATION_PERMIT`); the crew's `open_order_count` must be strictly below its `max_concurrent_orders` (`ERR_CREW_AT_CAPACITY`); and for the two excavation methods the crew's `is_qualified_excavation` must be true (`ERR_CREW_NOT_QUALIFIED_EXCAVATION`). When `crew_id` is supplied explicitly it is resolved only after the `PENDING_DISPATCH` state check, so a state failure takes precedence over a crew `ERR_NOT_FOUND` (an exception to the general ordering of §2.5). When `crew_id` is omitted for an excavation method, the permit check is evaluated before crew selection, so `ERR_NO_VALID_EXCAVATION_PERMIT` takes precedence over `ERR_NO_ELIGIBLE_CREW`.

The selector policy, used when `crew_id` is omitted, considers all crews not `OFF_DUTY` whose `open_order_count` is strictly below `max_concurrent_orders`, additionally requiring `is_qualified_excavation` for excavation methods and a valid granted permit for the order. Each candidate is ranked by a dispatch score computed as follows: take the crew's utilization ratio (`open_order_count` divided by `max_concurrent_orders`); the score is 0.7 times one minus the utilization ratio, plus 0.3 times one if the crew's `home_region` equals the segment's `region_hint` (zero if the hint is null or does not match); the score is rounded half-up to 4 decimal places. Candidates sort by score descending; ties break first on `open_order_count` ascending, then on `created_at` ascending. If no candidate is eligible, dispatch fails with `ERR_NO_ELIGIBLE_CREW`. A successful dispatch sets the order's `crew_id` and `dispatched_at`, increments the crew's `open_order_count` by 1, and recomputes the crew's `status` (`AT_CAPACITY` once the count reaches the maximum).

From `DISPATCHED`, the coordinator records arrival on site — requiring `DISPATCHED` (`ERR_ORDER_NOT_DISPATCHED`) — which flips the order to `ON_SITE` and simultaneously moves the leak `REPAIR_SCHEDULED → UNDER_REPAIR`. From `ON_SITE`, marking work complete — requiring `ON_SITE` (`ERR_ORDER_NOT_ON_SITE`) — stamps the order's `completed_at` from the logical clock, decrements the crew's `open_order_count` and recomputes its `status`, and moves the leak `UNDER_REPAIR → REPAIRED_PENDING_VERIFICATION`. Cancelling is possible from `PENDING_DISPATCH` or `DISPATCHED` (any other dispatch state yields `ERR_ORDER_NOT_CANCELLABLE`); if the order had been dispatched, the crew's `open_order_count` decrements and crew status recomputes, and in both cases the leak reverts from `REPAIR_SCHEDULED` to `OPEN` as a compensating action. Repair orders list with filters on `dispatch_status`, `excavation_permit_status`, `crew_id`, and `leak_id`; permits list with filters on `status` and `repair_order_id`.

### 3.7. Post-Repair Verification

Clearance of a repaired leak is a `ComplianceOfficer` action and is deliberately separated from the field work. Verification evaluates its checks in the order given by §2.5: the leak must be in `REPAIRED_PENDING_VERIFICATION` (`ERR_LEAK_NOT_PENDING_VERIFICATION`); segregation of duties then requires the verifying officer not be the field technician who created the originating survey run — the same `X-User-ID` on both sides is rejected with `ERR_SEGREGATION_OF_DUTIES`; and finally a post-repair survey run on the segment with `ACCEPTED` status and a leak-free finding must exist (`ERR_NO_POST_REPAIR_SURVEY`). A qualifying post-repair run is an `ACCEPTED` survey run that no leak record references (the leak-free finding), whose route carries a `COVERED` assignment for the leak's segment, and that was created at or after the `completed_at` of the leak's most recently completed repair order (no time constraint applies if the leak has no completed order). On success the leak moves to `VERIFIED_CLEARED`, the `verified_by_officer_id` of the leak's most recently completed repair order is set from `X-User-ID`, the segment's open-grade counter for the grade the leak held decrements, `posture` recomputes, `risk_score` recomputes per §3.8, and risk-model snapshots touching the segment go stale. `VERIFIED_CLEARED` is terminal.

### 3.8. Integrity Risk Scoring

Every `ACTIVE` segment carries a `risk_score` on a 0–100 scale, recomputed when a leak on the segment is verified cleared, when a route covering the segment completes, when a cathodic-protection anomaly on the segment transitions, and whenever the segment's posture changes. The score is a weighted sum of four components, followed by a high-consequence-area multiplier. The age component takes the segment's age in years (the current year minus `install_year`), divides by 50, caps the quotient at 1.0, and multiplies by a weight of 0.20. The material component maps `material` to a factor — `STEEL` 0.8, `CAST_IRON` 1.0, `PLASTIC_PE` 0.2, `PLASTIC_PVC` 0.3, `COPPER` 0.5 — and multiplies by a weight of 0.15. The leak component takes `open_grade1_count` times 3.0 plus `open_grade2_count` times 1.5 plus `open_grade3_count` times 0.5, caps the result at 1.0, and multiplies by a weight of 0.30. The cathodic-protection component counts the segment's readings whose `anomaly_status` is `OPEN` or `ACKNOWLEDGED`, divides the count by 3, caps the quotient at 1.0, and multiplies by a weight of 0.20. The four components sum to a base value; if the segment lies in a high consequence area the base is multiplied by 1.5 after the sum. The final `risk_score` is the base multiplied by 100, rounded half-up to 2 decimal places, and capped at 100.0.

Two readings of the score exist by design. The score computed at route completion is provisional — it snapshots the open-grade counters as they stood at completion time and does not reflect leaks verified cleared after the route completed. The score recomputed when a leak is verified cleared or an anomaly resolves is the final score — it uses post-event counters and may differ from the provisional value by a cent or more for the same segment. A segment whose `risk_score` reaches 70.0 or higher is considered high risk.

### 3.9. Re-Survey Intervals

Completing a route fixes the next due date for every covered segment. The base interval in days depends on `pressure_class` and high-consequence-area status: 90 days for `TRANSMISSION` in an HCA; 180 days for `TRANSMISSION` outside an HCA; 180 days for `DISTRIBUTION` in an HCA; 365 days for `DISTRIBUTION` outside an HCA; 365 days for `SERVICE` in an HCA; and 730 days for `SERVICE` outside an HCA. A multiplicative adjustment factor, starting at 1.0, then tightens the base: if the segment has any open Grade 1 leak, the factor drops to 0.25 (a quarterly cadence); otherwise, if it has any open Grade 2 leak, the factor drops to 0.5 (semiannual). Independently, if the segment has any cathodic-protection reading with `anomaly_status` of `OPEN` or `ACKNOWLEDGED`, the factor is multiplied by 0.5. The interval in days is the base multiplied by the factor, truncated down to a whole number of days, and `next_survey_due_at` is the route's completion timestamp plus that many days.

This stored value is a forward-looking estimate: it freezes the counters and anomaly flags as of completion, and later leak activity does not retroactively rewrite it. The on-demand recompute capability described in §3.1 instead applies the same formula to the counters and anomaly flags current at request time, so the two answers can legitimately differ.

### 3.10. Cathodic Protection and Anomaly Disposition

A `FieldTechnician` records a cathodic-protection reading against a segment with the operator-assigned `test_point_id`, the `pipe_to_soil_potential_mv` (a negative millivolt value), and the `instant_off_potential_mv`. The segment may be in any status — only its existence is checked. The server stamps `recorded_at` and computes `is_anomalous`: the reading is anomalous when the instant-off potential is greater (less negative) than -850 mV. An anomalous reading is born with `anomaly_status` of `OPEN`; recording it recomputes the segment's `posture` (per §2.8, an open anomaly alone raises posture to `ELEVATED`) and marks any risk-model snapshot touching the segment stale. A clean reading keeps `anomaly_status` of `NONE` and triggers no recomputation.

An `IntegrityAnalyst` acknowledges an `OPEN` anomaly (`OPEN → ACKNOWLEDGED`); any other state is rejected with `ERR_ANOMALY_NOT_OPEN`. Resolving requires `ACKNOWLEDGED` (`ERR_ANOMALY_NOT_ACKNOWLEDGED`) and additionally requires a newer cathodic-protection reading on the same segment with `is_anomalous` false — the cleanup evidence — else `ERR_NO_CLEANUP_READING`; "newer" means a `recorded_at` strictly later than the anomalous reading's, with ties broken by creation order. Resolution moves the anomaly to `RESOLVED` (terminal) and recomputes the segment's `posture`. Readings list with filters on `segment_id`, `anomaly_status`, and `is_anomalous`.

### 3.11. Risk Model Snapshots and Regulatory Reporting

An `IntegrityAnalyst` generates a `RiskModelSnapshot` by supplying a human `snapshot_label` (e.g. "Q3-2026-leak-section") and a `snapshot_kind` of `LEAK_SECTION`, `CP_SECTION`, or `FULL`. Generation runs the risk scoring of §3.8 for every `ACTIVE` segment — writing the freshly computed score back onto each segment whose stored `risk_score` differs — records the count scored in `total_segments_scored`, collects the ids of segments scoring at or above 70.0 into `high_risk_segment_ids` in segment listing order (`created_at` ascending), computes a deterministic `input_set_hash` — the SHA-256 hex digest of the sorted ids of all `ACTIVE` segments together with the leaks and cathodic readings on those segments — stamps `generated_at`, and marks any prior same-kind snapshots `STALE` so the new one is the sole `CURRENT` snapshot of its kind. Beyond regeneration, snapshots also stale automatically the moment any underlying input changes — a new leak, a leak verified cleared, a cathodic anomaly opening, a segment posture shift. Snapshots list with filters on `status` and `snapshot_kind`.

A `ComplianceOfficer` assembles a regulatory filing as a `ComplianceReport`. Creating the report takes the `reporting_period_start` (inclusive), the `reporting_period_end` (exclusive), and the target `regulator` — one of `PHMSA`, `STATE_PUC`, `LOCAL_FIRE_MARSHAL` — and produces a `DRAFT`. The report body aggregates two sections over all leaks and cathodic readings whose `discovered_at` or `recorded_at` falls inside the half-open reporting window: a leak section counting leaks opened by grade, leaks verified cleared in the window (a leak counts when the logical timestamp of its verify-clear action falls inside the window), and the on-time repair rate; and a cathodic section counting readings taken, anomalies opened (readings in the window whose `is_anomalous` is true), and anomalies resolved (readings recorded in the window whose `anomaly_status` is now `RESOLVED`). Each embedded ratio — the on-time repair rate (leaks verified cleared at or before their `repair_due_at`, divided by the number verified cleared in the window, with the divisor floored at 1) and the cathodic anomaly rate (anomalous readings divided by readings taken in the window, divisor floored at 1) — is computed at full precision and rounded half-up to 4 decimal places **before** assembly; the assembled payload is never rounded again. The payload is aggregated when the report is created and re-aggregated when the report is submitted to the regulator. The generated artifact's location is recorded in `report_payload_uri`, which takes the form `/integrity-program/compliance-reports/{id}/payload`.

Before review, the officer binds evidence onto the draft by supplying `leak_section_snapshot_id` and `cp_section_snapshot_id` — each naming a `RiskModelSnapshot`, with no requirement that the snapshot's kind match the section it is bound to — together with `expected_report_version`. Binding requires the report to be `DRAFT` (`ERR_REPORT_NOT_DRAFT`), is rejected with `ERR_SNAPSHOT_STALE` if either named snapshot is not `CURRENT`, and — per the validation order of §2.5, which places concurrency checks last — with `ERR_STALE_REPORT_VERSION` on a version mismatch. Submitting the draft for review (`DRAFT → PENDING_REVIEW`) again carries `expected_report_version` with `ERR_STALE_REPORT_VERSION` on mismatch; it requires the report to be `DRAFT` (`ERR_REPORT_NOT_DRAFT`) and both bound snapshots to be `CURRENT` (`ERR_SNAPSHOT_STALE`), and on success it pins both snapshots — their status becomes `PINNED` and they are immutable thereafter. Filing with the regulator (`PENDING_REVIEW → SUBMITTED`) requires `PENDING_REVIEW` state (`ERR_REPORT_NOT_PENDING_REVIEW`), requires the officer's `jurisdiction_scope` to include the report's `regulator` (`ERR_OFFICER_OUT_OF_JURISDICTION` — an `X-User-ID` with no `ComplianceOfficer` record is treated as out of jurisdiction), and requires the logical clock to be no later than 60 days after `reporting_period_end` (`ERR_REPORT_PAST_DUE`); success stamps `submitted_at`. The regulator's answer is recorded by the officer: acceptance (`SUBMITTED → ACCEPTED`, terminal) or rejection (`SUBMITTED → REJECTED_BY_REGULATOR`), each requiring `SUBMITTED` state (`ERR_REPORT_NOT_SUBMITTED`).

A rejected filing re-enters the workflow. Requesting resubmission (`REJECTED_BY_REGULATOR → RESUBMISSION_REQUIRED`) requires `REJECTED_BY_REGULATOR` state (`ERR_REPORT_NOT_REJECTED`). Reopening the draft (`RESUBMISSION_REQUIRED → DRAFT`) requires `RESUBMISSION_REQUIRED` state (`ERR_REPORT_NOT_RESUBMISSION_REQUIRED`) and, on success, both pinned snapshots revert from `PINNED` to `STALE` — forcing fresh snapshots to be generated — while `leak_section_snapshot_id` and `cp_section_snapshot_id` are nulled out, ready for a new binding. Reports list with filters on `status` and `regulator`.

### 3.12. Segment Decommissioning

Taking a segment out of service is an `IntegrityAnalyst` action requiring the segment to be `ACTIVE` (`ERR_SEGMENT_NOT_ACTIVE`) and requiring that no repair order on the segment be in `DISPATCHED` or `ON_SITE` status (`ERR_OPEN_REPAIR_ORDERS_EXIST`). The transition `ACTIVE → OUT_OF_SERVICE` cascades: every leak on the segment in `OPEN` or `REPAIR_SCHEDULED` moves to `ABANDONED_SEGMENT`; any repair order on those leaks still in `PENDING_DISPATCH` moves to `CANCELLED`; all three open-grade counters recompute to 0; and `posture` recomputes to `NORMAL`.

Returning a segment to service (`OUT_OF_SERVICE → ACTIVE`) requires `OUT_OF_SERVICE` state (`ERR_SEGMENT_NOT_OUT_OF_SERVICE`) and requires a cathodic-protection reading on the segment, taken within the last 90 days, with `is_anomalous` false (`ERR_NO_RECENT_CLEAN_CP_READING`); the 90-day cutoff is inclusive, so a reading recorded exactly 90 days before the current logical clock qualifies. Abandoning a segment (`OUT_OF_SERVICE → ABANDONED`, terminal) likewise requires `OUT_OF_SERVICE` state (`ERR_SEGMENT_NOT_OUT_OF_SERVICE`). Abandonment is permanent; the segment no longer participates in surveying, scoring, or dispatch.

## 4. Endpoint Definitions

All endpoints are mounted under the `/integrity-program` prefix. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, retrieve resources, or perform an action respond with HTTP 200. Errors carry the HTTP status listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /pipe-segments | Create a new PipeSegment | IntegrityAnalyst |
| GET | /pipe-segments | List PipeSegments with pagination and filtering | IntegrityAnalyst, ComplianceOfficer, FieldTechnician, DispatchCoordinator |
| GET | /pipe-segments/{id} | Get a single PipeSegment | IntegrityAnalyst, ComplianceOfficer, FieldTechnician, DispatchCoordinator |
| GET | /pipe-segments/{id}/leaks | List Leaks on this PipeSegment | IntegrityAnalyst, ComplianceOfficer, FieldTechnician, DispatchCoordinator |
| GET | /pipe-segments/{id}/cp-readings | List CathodicProtectionReadings for this segment | IntegrityAnalyst, ComplianceOfficer, FieldTechnician |
| GET | /pipe-segments/{id}/compliance-summary | Derived compliance summary (overdue leaks, posture, due date, counters, risk score) | IntegrityAnalyst, ComplianceOfficer |
| GET | /pipe-segments/{id}/next-survey-due | Recompute next_survey_due_at on demand using current counters | IntegrityAnalyst |
| POST | /pipe-segments/{id}/out-of-service | Take PipeSegment out of service | IntegrityAnalyst |
| POST | /pipe-segments/{id}/return-to-service | Return PipeSegment to service | IntegrityAnalyst |
| POST | /pipe-segments/{id}/abandon | Mark PipeSegment as ABANDONED (terminal) | IntegrityAnalyst |
| POST | /instruments | Create a new Instrument | CalibrationTech |
| GET | /instruments | List Instruments | CalibrationTech, FieldTechnician, IntegrityAnalyst |
| GET | /instruments/{id} | Get one Instrument | CalibrationTech, FieldTechnician, IntegrityAnalyst |
| GET | /instruments/{id}/calibrations | List Calibrations for this instrument | CalibrationTech, IntegrityAnalyst |
| POST | /instruments/{id}/calibrate | Record a calibration; updates Instrument status if PASS | CalibrationTech |
| POST | /instruments/{id}/retire | Retire an instrument | CalibrationTech |
| POST | /field-technicians | Create a FieldTechnician | IntegrityAnalyst |
| GET | /field-technicians | List FieldTechnicians | IntegrityAnalyst, DispatchCoordinator |
| GET | /field-technicians/{id} | Get one FieldTechnician | IntegrityAnalyst, DispatchCoordinator |
| POST | /compliance-officers | Create a ComplianceOfficer | IntegrityAnalyst |
| GET | /compliance-officers | List ComplianceOfficers | IntegrityAnalyst |
| GET | /compliance-officers/{id} | Get one ComplianceOfficer | IntegrityAnalyst |
| POST | /calibration-techs | Create a CalibrationTech | IntegrityAnalyst |
| GET | /calibration-techs | List CalibrationTechs | IntegrityAnalyst |
| POST | /dispatch-coordinators | Create a DispatchCoordinator | IntegrityAnalyst |
| GET | /dispatch-coordinators | List DispatchCoordinators | IntegrityAnalyst |
| POST | /integrity-analysts | Create an IntegrityAnalyst | IntegrityAnalyst |
| GET | /integrity-analysts | List IntegrityAnalysts | IntegrityAnalyst |
| POST | /repair-crews | Create a RepairCrew | DispatchCoordinator |
| GET | /repair-crews | List RepairCrews | DispatchCoordinator, IntegrityAnalyst |
| GET | /repair-crews/{id} | Get one RepairCrew | DispatchCoordinator, IntegrityAnalyst |
| GET | /repair-crews/{id}/repair-orders | List RepairOrders assigned to this crew | DispatchCoordinator, IntegrityAnalyst |
| POST | /repair-crews/{id}/set-off-duty | Set crew OFF_DUTY | DispatchCoordinator |
| POST | /repair-crews/{id}/set-on-duty | Set crew back to AVAILABLE | DispatchCoordinator |
| POST | /survey-routes | Create a SurveyRoute (PLANNED) | DispatchCoordinator |
| GET | /survey-routes | List SurveyRoutes | DispatchCoordinator, IntegrityAnalyst, FieldTechnician |
| GET | /survey-routes/{id} | Get one SurveyRoute | DispatchCoordinator, IntegrityAnalyst, FieldTechnician |
| GET | /survey-routes/{id}/route-segment-assignments | List RouteSegmentAssignments on this route | DispatchCoordinator, IntegrityAnalyst, FieldTechnician |
| POST | /survey-routes/{id}/route-segment-assignments | Add a segment to a route (PLANNED only) | DispatchCoordinator |
| POST | /survey-routes/{id}/dispatch | Dispatch a PLANNED route | DispatchCoordinator |
| POST | /survey-routes/{id}/start | FieldTechnician starts the route (within window) | FieldTechnician |
| POST | /survey-routes/{id}/complete | Mark route COMPLETED; recomputes risk scores and next_survey_due_at | FieldTechnician |
| POST | /survey-routes/{id}/abort | Abort the route | DispatchCoordinator |
| POST | /survey-runs | Create a SurveyRun (DRAFT) against a route | FieldTechnician |
| GET | /survey-runs | List SurveyRuns | FieldTechnician, IntegrityAnalyst, DispatchCoordinator |
| GET | /survey-runs/{id} | Get one SurveyRun | FieldTechnician, IntegrityAnalyst, DispatchCoordinator |
| POST | /survey-runs/{id}/submit | FieldTechnician submits run for review | FieldTechnician |
| POST | /survey-runs/{id}/accept | IntegrityAnalyst accepts run; assigns covered segments | IntegrityAnalyst |
| POST | /survey-runs/{id}/reject | IntegrityAnalyst rejects run | IntegrityAnalyst |
| POST | /leaks | Report a Leak discovered during a SurveyRun | FieldTechnician |
| GET | /leaks | List Leaks | IntegrityAnalyst, ComplianceOfficer, FieldTechnician, DispatchCoordinator |
| GET | /leaks/{id} | Get one Leak | IntegrityAnalyst, ComplianceOfficer, FieldTechnician, DispatchCoordinator |
| GET | /leaks/{id}/regrade-events | List RegradeEvents for this leak | IntegrityAnalyst, ComplianceOfficer, FieldTechnician |
| GET | /leaks/{id}/repair-orders | List RepairOrders for this leak | IntegrityAnalyst, DispatchCoordinator, ComplianceOfficer |
| POST | /leaks/{id}/regrade | FieldTechnician re-grades a leak (OPEN self-loop) | FieldTechnician |
| POST | /leaks/{id}/schedule-repair | DispatchCoordinator schedules repair; creates RepairOrder | DispatchCoordinator |
| POST | /leaks/{id}/verify-clear | ComplianceOfficer verifies leak cleared | ComplianceOfficer |
| GET | /repair-orders | List RepairOrders | DispatchCoordinator, IntegrityAnalyst, ComplianceOfficer |
| GET | /repair-orders/{id} | Get one RepairOrder | DispatchCoordinator, IntegrityAnalyst, ComplianceOfficer |
| POST | /repair-orders/{id}/dispatch | Dispatch a RepairOrder to a crew (selector policy runs if crew omitted) | DispatchCoordinator |
| POST | /repair-orders/{id}/arrive-on-site | Mark crew arrived on site | DispatchCoordinator |
| POST | /repair-orders/{id}/mark-work-complete | Mark work complete | DispatchCoordinator |
| POST | /repair-orders/{id}/cancel | Cancel a RepairOrder | DispatchCoordinator |
| POST | /repair-orders/{id}/apply-permit | ComplianceOfficer applies for excavation permit on this order | ComplianceOfficer |
| GET | /excavation-permits | List ExcavationPermits | ComplianceOfficer, DispatchCoordinator |
| GET | /excavation-permits/{id} | Get one ExcavationPermit | ComplianceOfficer, DispatchCoordinator |
| POST | /excavation-permits/{id}/grant | ComplianceOfficer records permit granted | ComplianceOfficer |
| POST | /excavation-permits/{id}/deny | ComplianceOfficer records permit denied | ComplianceOfficer |
| POST | /cp-readings | Record a CP reading on a PipeSegment | FieldTechnician |
| GET | /cp-readings | List CathodicProtectionReadings | IntegrityAnalyst, ComplianceOfficer, FieldTechnician |
| GET | /cp-readings/{id} | Get one CP reading | IntegrityAnalyst, ComplianceOfficer, FieldTechnician |
| POST | /cp-readings/{id}/acknowledge | IntegrityAnalyst acknowledges an OPEN anomaly | IntegrityAnalyst |
| POST | /cp-readings/{id}/resolve | IntegrityAnalyst resolves an ACKNOWLEDGED anomaly | IntegrityAnalyst |
| POST | /risk-model-snapshots | Generate a new RiskModelSnapshot (older same-kind become STALE) | IntegrityAnalyst |
| GET | /risk-model-snapshots | List RiskModelSnapshots | IntegrityAnalyst, ComplianceOfficer |
| GET | /risk-model-snapshots/{id} | Get one snapshot | IntegrityAnalyst, ComplianceOfficer |
| POST | /compliance-reports | Create a DRAFT ComplianceReport | ComplianceOfficer |
| GET | /compliance-reports | List ComplianceReports | ComplianceOfficer, IntegrityAnalyst |
| GET | /compliance-reports/{id} | Get one ComplianceReport | ComplianceOfficer, IntegrityAnalyst |
| POST | /compliance-reports/{id}/bind-snapshots | Bind RiskModelSnapshots to DRAFT report (OCC-guarded) | ComplianceOfficer |
| POST | /compliance-reports/{id}/submit-for-review | Submit DRAFT for review (OCC-guarded); pins snapshots | ComplianceOfficer |
| POST | /compliance-reports/{id}/submit-to-regulator | Submit report to regulator | ComplianceOfficer |
| POST | /compliance-reports/{id}/record-acceptance | Regulator accepted | ComplianceOfficer |
| POST | /compliance-reports/{id}/record-rejection | Regulator rejected | ComplianceOfficer |
| POST | /compliance-reports/{id}/request-resubmission | Officer requests resubmission | ComplianceOfficer |
| POST | /compliance-reports/{id}/reopen-draft | Reopen report as DRAFT for resubmission | ComplianceOfficer |
| POST | /_clock/set_current_utc | Set the server logical clock (test-driving endpoint) | IntegrityAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGMENT_NOT_ACTIVE | 409 |
| ERR_SEGMENT_NOT_OUT_OF_SERVICE | 409 |
| ERR_OPEN_REPAIR_ORDERS_EXIST | 422 |
| ERR_NO_RECENT_CLEAN_CP_READING | 422 |
| ERR_INSTRUMENT_OUT_OF_CALIBRATION | 422 |
| ERR_CALIBRATION_DRIFT_EXCEEDED | 422 |
| ERR_INSTRUMENT_IN_USE | 422 |
| ERR_ROUTE_NOT_PLANNED | 409 |
| ERR_ROUTE_NOT_DISPATCHED | 409 |
| ERR_ROUTE_NOT_IN_PROGRESS | 409 |
| ERR_ROUTE_NOT_ABORTABLE | 409 |
| ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT | 422 |
| ERR_ROUTE_WINDOW_PASSED | 422 |
| ERR_OUTSIDE_SCHEDULED_WINDOW | 422 |
| ERR_TECHNICIAN_NOT_QUALIFIED | 422 |
| ERR_NO_ACCEPTED_RUN | 422 |
| ERR_RUN_NOT_DRAFT | 409 |
| ERR_RUN_NOT_SUBMITTED | 409 |
| ERR_NOT_RUN_OWNER | 403 |
| ERR_COVERAGE_BELOW_MINIMUM | 422 |
| ERR_LEAK_NOT_OPEN | 409 |
| ERR_LEAK_NOT_PENDING_VERIFICATION | 409 |
| ERR_REGRADE_SAME_GRADE | 422 |
| ERR_REGRADE_LIMIT_EXCEEDED | 422 |
| ERR_NO_POST_REPAIR_SURVEY | 422 |
| ERR_ORDER_NOT_PENDING_DISPATCH | 409 |
| ERR_ORDER_NOT_DISPATCHED | 409 |
| ERR_ORDER_NOT_ON_SITE | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_NO_ELIGIBLE_CREW | 422 |
| ERR_CREW_HAS_OPEN_ORDERS | 422 |
| ERR_CREW_AT_CAPACITY | 422 |
| ERR_CREW_NOT_QUALIFIED_EXCAVATION | 422 |
| ERR_CREW_OFF_DUTY | 422 |
| ERR_NO_VALID_EXCAVATION_PERMIT | 422 |
| ERR_PERMIT_NOT_APPLIED | 409 |
| ERR_PERMIT_NOT_REQUIRED | 409 |
| ERR_ANOMALY_NOT_OPEN | 409 |
| ERR_ANOMALY_NOT_ACKNOWLEDGED | 409 |
| ERR_NO_CLEANUP_READING | 422 |
| ERR_REPORT_NOT_DRAFT | 409 |
| ERR_REPORT_NOT_PENDING_REVIEW | 409 |
| ERR_REPORT_NOT_SUBMITTED | 409 |
| ERR_REPORT_NOT_REJECTED | 409 |
| ERR_REPORT_NOT_RESUBMISSION_REQUIRED | 409 |
| ERR_SNAPSHOT_STALE | 422 |
| ERR_OFFICER_OUT_OF_JURISDICTION | 422 |
| ERR_REPORT_PAST_DUE | 422 |
| ERR_STALE_LEAK_VERSION | 412 |
| ERR_STALE_REPORT_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
