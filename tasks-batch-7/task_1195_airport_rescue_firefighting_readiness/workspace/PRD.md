# Airport Rescue & Firefighting Readiness API — Product Requirements Document

## 1. Introduction

An airport's Aircraft Rescue and Firefighting (ARFF) posture is not a static certificate on the wall — it is a continuously computed readiness posture driven by which aircraft types are scheduled, which vehicles are rolling and measured ready, and which firefighters are both rostered and live-fire current. When any of those inputs shifts, the airport's certificated ARFF index can silently become unsupported, and Federal Aviation Administration (FAA) certification is jeopardized.

This document specifies the ARFF Readiness API. The platform maintains a singleton airport operations profile whose computed readiness index is derived from three independent inputs — the largest qualifying aircraft on the field, the fire-suppression capacity of the in-service and measured-ready fleet, and the count of deployment-ready firefighters. The system then enforces regulatory gates across the operational lifecycle: response drills must be timed and certified, mutual-aid agreements must cover an incident's alert level, downgrade notifications must be acknowledged and cured within thirty days, incident reports must be authored and independently reviewed, and an annual FAA inspection closes only when no blocking notifications remain and a valid certified drill exists.

The API is mounted under `/arff` and serves five distinct operator roles — airport executives, station chiefs, safety officers, FAA inspectors, and individual firefighters — each with narrowly scoped authority over the slice of the readiness lifecycle they own.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or whose role value does not match one of the declared roles below, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). After the headers validate, the role is checked against the endpoint's authorization list; a role not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The declared roles are:

- `AirportManager` — airport operator executive. Owns the singleton profile, the aircraft register, index determinations, mutual-aid agreements, incident-report adjudication, FAA-inspection scheduling, and the logical clock.
- `ArffChief` — ARFF station chief. Owns vehicles, readiness checks, firefighters, training records, response drills, incidents, mutual-aid requests, and out-of-service events.
- `SafetyOfficer` — airport safety officer. Authors incident reports and post-incident reviews.
- `FaaInspector` — FAA certification inspector. Acknowledges downgrade notifications and conducts the annual inspection.
- `Firefighter` — line firefighter with read-only access. When `X-User-Role` is `Firefighter`, `X-User-ID` is the `id` of the acting `Firefighter` entity; ownership checks on any resource that references a `Firefighter` compare the resource's foreign-key field to `X-User-ID`. In particular, when a `Firefighter` reads their own roster record, the path `id` must equal `X-User-ID`.

For the four non-firefighter roles — `AirportManager`, `ArffChief`, `SafetyOfficer`, and `FaaInspector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `author_user_id` on an `IncidentReport` created by a `SafetyOfficer`) but does not compare it to any entity's `id`. Resource-level ownership checks for incident reports compare the caller's `X-User-ID` to the report's `author_user_id` field, not to any role-backed entity.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). List responses populate the `meta` envelope with `limit`, `offset`, `total_count`, and `has_more`. Default sort order for every list endpoint is `created_at` ascending.

### 2.4. Common Resource Properties

Every persisted entity carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits. `version` starts at 1 and increments by 1 on every mutation of the entity. Entities with computed fields recompute those fields whenever the inputs change and bump their own `version` accordingly. The `AirportOpsProfile` in particular increments its `version` on every cascade that touches it — vehicle out-of-service open or restore, readiness check recording, firefighter suspend or reactivate, training record creation, aircraft create or update, index-determination creation, and any logical-clock-driven recompute that changes a derived field.

### 2.5. The Logical Clock

Time inside the system is governed by a logical clock, not wall-clock time. Before any operator sets it, the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. An `AirportManager` may advance the logical clock via the test-driving endpoint by supplying a `to_iso8601` timestamp; the response echoes the new `current_utc`. Advancing the clock re-evaluates every time-derived field in the system: firefighter training currency, mutual-aid agreement auto-expiry, downgrade-notification overdue transition, and the full effective-index recomputation with its notification create/resolve rules.

Everywhere the PRD says "logical clock," "current logical date," or "now," it refers to this logical clock. Fields like `checked_at`, `executed_at`, `reported_at`, `controlled_at`, `started_at`, `restored_at`, and `notified_at` are stamped from the logical clock at the moment of the action that sets them.

### 2.6. The Singleton Airport Operations Profile

There is exactly one `AirportOpsProfile` per deployment, identified by an IATA-style `airport_code` and a `certificated_index` in `A | B | C | D | E`. A second attempt to create the profile is rejected with `ERR_PROFILE_ALREADY_EXISTS` (HTTP 409). Reading the profile before it exists yields `ERR_PROFILE_NOT_FOUND` (HTTP 404).

The profile carries four derived fields whose complete computation is described in §3: `required_index_by_aircraft`, `supported_index_by_equipment`, `supported_index_by_staffing`, and `effective_index`, plus a derived `index_compliance_status` enum (`COMPLIANT`, `DOWNGRADED`, `NONCOMPLIANT`). Index ordering throughout the system is `NONE < A < B < C < D < E`; `NONE` dominates any minimum.

### 2.7. Precision and Rounding

All monetary values are integer cents. Agent-expense lines are rounded per line using round-half-up before summation — the rounding order is pinned and not negotiable: round each line to a whole cent first, then sum the rounded line cents to form the report total. Gallon-based capacity comparisons in the readiness derivation use two decimal places of precision, and threshold comparisons are exact (no tolerance).

### 2.8. Optimistic Concurrency Control on Index Determination

Creating an `IndexDetermination` is the only OCC-protected write in the system. The request must carry an `expected_profile_version` field equal to the profile's current `version`. If the profile's `version` has advanced beyond what the caller last observed — whether because another determination superseded the prior `ACTIVE` one, or because any readiness cascade recomputed the profile — the create is rejected with `ERR_STALE_PROFILE_VERSION` (HTTP 412). No other endpoint takes a version field; clients do not pass `version` on vehicle, firefighter, drill, incident, agreement, report, review, or inspection writes.

### 2.9. Nested Resource Retrieval

Endpoints that nest one resource under another (for example, a vehicle's readiness checks, an incident's reports, an aircraft's incidents) validate path identifiers from left to right. The leftmost path `id` is resolved first; if it does not exist, the request is rejected with the corresponding `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) before any right-hand identifier is examined. Within an existing parent, a nonexistent child `id` is rejected with that child's own not-found error.

### 2.10. Validation Ordering

When multiple rules could fire on the same request, the system applies them in priority order so that earlier errors mask later ones. The ordering is: (1) header presence and role declaration (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role authorization (`ERR_INSUFFICIENT_PERMISSIONS`); (3) path-id existence, then body foreign-key existence, evaluated left-to-right (`ERR_<RESOURCE>_NOT_FOUND`); (3.5) required body-field presence and types (`ERR_VALIDATION_FAILED`); (3.6) OCC stale-version on the index-determination endpoint (`ERR_STALE_PROFILE_VERSION`); (4) state-machine preconditions (the various `ERR_*_NOT_*` 409 errors); (5) safety and regulatory gates (the 422 family — `ERR_INDEX_INSUFFICIENT_FOR_ALERT`, `ERR_RESPONSE_TIME_EXCEEDED`, `ERR_READINESS_RECHECK_REQUIRED`, `ERR_FIREFIGHTER_NOT_ACTIVE`, `ERR_INSPECTION_BLOCKING_NOTIFICATIONS`, `ERR_NO_VALID_CERTIFIED_DRILL`, `ERR_PROFILE_NOT_COMPLIANT`); (6) referential-state rules (`ERR_AGREEMENT_NOT_ACTIVE`, `ERR_ALERT_LEVEL_NOT_COVERED`, `ERR_REPORT_NOT_ACCEPTED`, `ERR_REVIEW_ALREADY_OPEN`); (7) temporal rules (`ERR_REPORT_WINDOW_EXPIRED`, `ERR_TRAINING_DATE_IN_FUTURE`, `ERR_DRILL_WINDOW_INVALID`, `ERR_DRILL_WINDOW_EXPIRED`, `ERR_AGREEMENT_WINDOW_INVALID`); and (8) constraint rules (duplicates, overlaps, narrative length, capacity ceilings, escalation monotonicity, open-request and open-action gates, author identity, and the determination-specific `ERR_AIRCRAFT_NOT_QUALIFYING`, `ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT`, `ERR_INDEX_BELOW_REQUIRED`).

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Airport Profile and Aircraft Register

An `AirportManager` brings the system online by creating the singleton profile with an `airport_code` and a starting `certificated_index`. At creation the profile runs an initial recompute of every derived field, but the notification-create rule is suppressed for that first pass — there is no prior `effective_index` to "drop from," so no `IndexDowngradeNotification` fires. The profile's initial `required_index_by_aircraft` is `A` because no aircraft are registered yet; both `supported_index_by_equipment` and `supported_index_by_staffing` evaluate to `NONE` until vehicles, readiness checks, and current firefighters exist; the resulting `effective_index` is therefore `NONE`, and `index_compliance_status` evaluates accordingly (since `NONE` is below `A`, the very first status is `NONCOMPLIANT` until the fleet and roster catch up).

Once the profile exists, the `AirportManager` registers each aircraft type with `model_name`, `length_ft`, `avg_daily_departures`, and an optional `in_scheduled_service` flag that defaults to `true`. The system computes two derived fields on each aircraft. `qualifies_for_index` is `true` exactly when `in_scheduled_service` is `true` and `avg_daily_departures` is at least `5.0` — the threshold is inclusive, so exactly 5.0 qualifies. `index_band` derives from `length_ft` with inclusive lower bounds and exclusive upper bounds: `A` when `length_ft` is below 90 feet; `B` when `length_ft` is at least 90 and below 126; `C` when at least 126 and below 159; `D` when at least 159 and below 200; and `E` when at least 200 feet. Aircraft updates may touch `model_name`, `length_ft`, `avg_daily_departures`, or `in_scheduled_service`, and every create or update recomputes `qualifies_for_index`, `index_band`, the profile-level `required_index_by_aircraft`, and bumps the profile's `version`.

`required_index_by_aircraft` aggregates across the entire aircraft register: consider only rows where `in_scheduled_service` is `true` and `avg_daily_departures` is at least `5.0`. If no aircraft qualifies, the value is `A`. Otherwise, identify the qualifying aircraft with the greatest `length_ft` (ties broken by greatest `avg_daily_departures`, then by `created_at` ascending) and take that aircraft's `index_band`. This value is recomputed on every aircraft create, every aircraft update touching `length_ft`, `avg_daily_departures`, or `in_scheduled_service`, and on every read of the profile.

### 3.2. Vehicle Fleet, Readiness Measurement, and Equipment-Supported Index

An `ArffChief` builds the fleet one vehicle at a time, registering each with a unique `call_sign` (for example, `RED-1`), a `water_capacity_gal` strictly greater than zero, and a `dry_chem_capacity_lb` greater than or equal to zero. A duplicate `call_sign` is rejected with `ERR_DUPLICATE_CALL_SIGN`. A vehicle begins life with `status` `IN_SERVICE`, `latest_readiness_result` `NONE` (because no check exists yet), and `open_oos_event_id` null.

Readiness is measured, not rated. To record a measurement the `ArffChief` submits a check naming the target `vehicle_id` together with `water_available_gal`, `dry_chem_available_lb`, and `discharge_system_ok`. Measured quantities must be non-negative and may not exceed the vehicle's rated `water_capacity_gal` and `dry_chem_capacity_lb` — a measurement above rated capacity is rejected with `ERR_MEASURED_EXCEEDS_CAPACITY`. The server stamps `checked_at` from the logical clock and computes the check's `result`: `PASS` exactly when `discharge_system_ok` is `true` and `water_available_gal` is greater than zero; otherwise `FAIL`. The vehicle's `latest_readiness_result` updates to this result, with ties in `checked_at` broken by `created_at` descending so the most recently created check wins. A readiness check may be recorded against a vehicle in either `IN_SERVICE` or `OUT_OF_SERVICE` status — the latter path exists specifically to support the recheck-before-restore rule in §3.3.

The equipment-supported side of the profile derives from the measured-ready fleet. Define the eligible fleet as vehicles whose `status` is `IN_SERVICE` and whose `latest_readiness_result` is `PASS`. For each such vehicle, take its most recent `ReadinessCheck` by `checked_at` (tie-break: `created_at` descending) and use that check's `water_available_gal` and `dry_chem_available_lb`. Sum these across the fleet into a `water_sum` and a `chem_sum`. Dry chemical converts to water-equivalent gallons at `1.2` gallons per pound. The system then walks candidate indexes in descending order `E, D, C, B, A` and picks the first one whose requirements are met. For a candidate index `I`, the vehicle-count requirement `VEH_REQ[I]` is `1` for `A`, `2` for `B`, `2` for `C`, `3` for `D`, and `3` for `E`; the fleet size must be at least that number. The water requirement `WATER_REQ[I]` is `100` gallons for `A`, `1500` for `B`, `3000` for `C`, `4000` for `D`, and `6000` for `E`. Dry-chemical substitution is capped: the contribution counted toward water is the lesser of the full water-equivalent (`chem_sum` times `1.2`) and one-half of `WATER_REQ[I]`. Effective water at index `I` is then `water_sum` plus that capped substitution. Index `I` is met when both the vehicle count and the effective-water thresholds clear. `supported_index_by_equipment` is the highest met index, or `NONE` when even `A` is unmet.

For audit comparison the readiness detail view also exposes a rated-basis variant named `rated_basis_supported_index`, which performs the same walk but uses the rated `water_capacity_gal` and `dry_chem_capacity_lb` of every `IN_SERVICE` vehicle regardless of readiness-check outcome. The rated-basis variant never feeds `supported_index_by_equipment`; it exists purely for audit. The same readiness view surfaces `effective_water_gal_at_certificated_index` (the effective-water figure evaluated at the profile's certificated index) and `in_service_passing_vehicle_count`.

### 3.3. Out-of-Service Events, Recheck, and Downgrade Notifications

When a vehicle must leave the line, the `ArffChief` opens an out-of-service event with a free-text `reason`. The vehicle must currently be `IN_SERVICE`; opening a second event on an already-`OUT_OF_SERVICE` vehicle is rejected with `ERR_VEHICLE_ALREADY_OUT_OF_SERVICE`. On open, the system creates an `OutOfServiceEvent` with `status` `OPEN` and `started_at` stamped from the logical clock, sets the vehicle's `open_oos_event_id` to the new event's `id`, flips the vehicle's `status` to `OUT_OF_SERVICE`, and recomputes `supported_index_by_equipment`, `effective_index`, and `index_compliance_status` on the profile, bumping the profile's `version`. If the recompute caused `effective_index` to drop from a value at-or-above `certificated_index` to a value strictly below it, and no `IndexDowngradeNotification` currently sits in `PENDING`, `ACKNOWLEDGED`, or `OVERDUE`, the system creates one in `PENDING` status with `notified_at` set to now, `cure_deadline` set to thirty days after `notified_at`, `prior_index` recording the pre-recompute `effective_index`, `downgraded_index` recording the post-recompute value, and `cause` set to `EQUIPMENT` when `supported_index_by_equipment` is below `certificated_index` at trigger time, otherwise `STAFFING` — `EQUIPMENT` wins ties.

Restore is gated. The event must currently be `OPEN` (a restore on a `RESTORED` event is rejected with `ERR_OOS_EVENT_NOT_OPEN`), and there must exist a `ReadinessCheck` for the same vehicle with `result` `PASS` whose `checked_at` is at-or-after the event's `started_at`; without that recheck the restore is rejected with `ERR_READINESS_RECHECK_REQUIRED`. When both preconditions pass, the event flips to `RESTORED` with `restored_at` stamped from the logical clock, the vehicle's `open_oos_event_id` clears to null, the vehicle returns to `IN_SERVICE`, and the profile recomputes with `version` bumped. If the recompute lifts `effective_index` back to equality with `certificated_index` and a notification in `PENDING`, `ACKNOWLEDGED`, or `OVERDUE` exists, that notification transitions to `RESOLVED`.

Notification lifecycle runs independent of vehicle events. An `IndexDowngradeNotification` is created in `PENDING`. A `FaaInspector` may acknowledge a `PENDING` or `OVERDUE` notification, moving it to `ACKNOWLEDGED`; acknowledging a `RESOLVED` one is rejected with `ERR_NOTIFICATION_NOT_ACKNOWLEDGEABLE`. Independently, whenever the logical clock advances past `cure_deadline` (or any read occurs after that point), a notification in `PENDING` or `ACKNOWLEDGED` flips to `OVERDUE`. And whenever a recompute returns `effective_index` to `certificated_index`, any notification in `PENDING`, `ACKNOWLEDGED`, or `OVERDUE` flips to `RESOLVED`. The `cure_deadline` is always thirty days after `notified_at`.

### 3.4. Firefighter Roster, Live-Fire Currency, and Staffing-Supported Index

The `ArffChief` maintains the roster. A firefighter is added with a unique `employee_no` (duplicates rejected with `ERR_DUPLICATE_EMPLOYEE_NO`) and a `full_name`. New roster entries start with `status` `ACTIVE` and, because no passing training exists yet, `last_live_fire_completed_on` null, `is_training_current` `false`, and `is_deployable` `false`.

Currency is earned through live-fire training. Each `LiveFireTrainingRecord` names a `firefighter_id`, a `completed_on` ISO date, a `drill_type` of `AIRCRAFT` or `STRUCTURAL`, and a `result` of `PASS` or `FAIL`. The `completed_on` may not be later than the current logical date — a future date is rejected with `ERR_TRAINING_DATE_IN_FUTURE`. The named firefighter must currently be `ACTIVE`; recording training for a `SUSPENDED` firefighter is rejected with `ERR_FIREFIGHTER_NOT_ACTIVE`. Only `PASS` records feed currency. `last_live_fire_completed_on` is the ISO date of the most recent `PASS` record by `completed_on` (ties broken by the record's `created_at` descending); it is null when no `PASS` record exists.

Training currency follows a twelve-month window computed in whole calendar months. Define `month_index` of a date as the year multiplied by twelve plus the month (with month in `1..12`). A firefighter's `is_training_current` is `true` exactly when a `PASS` record exists and `month_index` of today minus `month_index` of `last_live_fire_completed_on` is at most twelve. So training completed in month M confers currency through the end of month M+12. `is_deployable` is `true` exactly when `status` is `ACTIVE` and `is_training_current` is `true`.

Suspension and reactivation cycle the roster. Suspending an `ACTIVE` firefighter (a suspend on a `SUSPENDED` firefighter is rejected with `ERR_INVALID_STATE`) flips `status` to `SUSPENDED`, recomputes `is_deployable` to `false`, recomputes the staffing-side and effective index, and bumps the profile's `version`. Reactivating a `SUSPENDED` firefighter (rejected with `ERR_INVALID_STATE` when already `ACTIVE`) flips `status` back to `ACTIVE`, recomputes `is_deployable`, and recomputes the staffing and effective index. Both transitions apply the notification create/resolve rules: a suspension that drops `effective_index` below `certificated_index` fires a `PENDING` notification (with `cause` `STAFFING` when equipment is not the lower of the two), and a reactivation that restores `effective_index` to the certificated level flips any open notification to `RESOLVED`.

The staffing-supported index is a separate derivation from the equipment side. Consider only firefighters whose `status` is `ACTIVE` and whose `is_training_current` is `true`. Walking candidate indexes in descending order `E, D, C, B, A`, the staffing requirement `STAFF_REQ[I]` is `2` for `A`, `3` for `B`, `3` for `C`, `4` for `D`, and `5` for `E`. The first index whose requirement is met by the deployment-ready count wins; `supported_index_by_staffing` is that index, or `NONE` when even `A` is unmet. The readiness detail view also exposes a `roster_basis_supported_index` variant that counts every `ACTIVE` firefighter regardless of training currency — this variant is exposed for audit only and never feeds the production `supported_index_by_staffing`. The view additionally reports `roster_active_count` (all `ACTIVE` firefighters) and `deployment_ready_count` (those both `ACTIVE` and `is_training_current`).

### 3.5. Effective Index, Compliance Status, and Notification Rules

`effective_index` is the minimum of `certificated_index`, `supported_index_by_equipment`, and `supported_index_by_staffing`, under the ordering `NONE < A < B < C < D < E` — `NONE` dominates any minimum. `index_compliance_status` is then derived: `NONCOMPLIANT` when `effective_index` is below `required_index_by_aircraft`; `COMPLIANT` when `effective_index` equals `certificated_index` and `certificated_index` is at-or-above `required_index_by_aircraft`; otherwise `DOWNGRADED`.

Any mutation that changes `certificated_index`, `required_index_by_aircraft`, `supported_index_by_equipment`, or `supported_index_by_staffing` triggers a recompute of `effective_index` and `index_compliance_status` and increments the profile's `version`. The notification create rule fires only when a recompute transitions `effective_index` from a value at-or-above `certificated_index` to a value strictly below it — build-up recomputes that never reach the certificated index do not fire, and the initial profile-creation recompute (which has no previous value) never fires. The notification resolve rule fires whenever a recompute brings `effective_index` back to equality with `certificated_index` and an open notification exists. The notification's `cause` field captures `EQUIPMENT` when `supported_index_by_equipment` is below `certificated_index` at trigger time, otherwise `STAFFING`; when both are below, `EQUIPMENT` wins.

### 3.6. Index Determinations and Optimistic Concurrency

Periodically the airport formalizes its ARFF index through an `IndexDetermination`. An `AirportManager` creates one by naming a `largest_aircraft_id`, a `new_certificated_index` in `A | B | C | D | E`, and the OCC field `expected_profile_version` carrying the profile `version` the caller last observed. If the profile's current `version` has moved past `expected_profile_version` — because another determination landed in the interim or any cascade bumped the profile — the create is rejected with `ERR_STALE_PROFILE_VERSION` (HTTP 412), protecting the caller from overwriting a posture they have not seen.

Beyond OCC, three business rules fire on creation, in the validation order given in §2.10. The named aircraft must qualify — meaning `in_scheduled_service` is `true` and `avg_daily_departures` is at least `5.0`; otherwise the request is rejected with `ERR_AIRCRAFT_NOT_QUALIFYING`. The named aircraft must be the longest qualifying aircraft by the ordering of §3.1; otherwise `ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT`. And `new_certificated_index` must be at-or-above the `required_index` computed across all qualifying aircraft at creation time; otherwise `ERR_INDEX_BELOW_REQUIRED`.

When creation succeeds, the system records the computed `required_index` on the determination, evaluates `vehicle_requirement_met` as whether `supported_index_by_equipment` is at-or-above `required_index` at that moment, evaluates `staffing_requirement_met` analogously against `supported_index_by_staffing`, and captures `supersedes_determination_id` as the `id` of the previously `ACTIVE` determination (null on the very first). The previous `ACTIVE` determination flips to `SUPERSEDED`. The profile's `certificated_index` updates to `new_certificated_index`, the profile recomputes `effective_index` and `index_compliance_status`, and the profile's `version` increments by 1. Exactly one `ACTIVE` determination exists at any time.

### 3.7. Response Drills and Certification

The `ArffChief` schedules a timed response drill by naming a `runway_designator` and a window with `scheduled_start` strictly before `scheduled_end`; a non-positive window is rejected with `ERR_DRILL_WINDOW_INVALID`. The window uses half-open semantics: the interval includes `scheduled_start` and excludes `scheduled_end`. A new drill whose half-open window overlaps any other `SCHEDULED` drill on the same runway is rejected with `ERR_DRILL_WINDOW_OVERLAP`. A scheduled drill carries `first_vehicle_arrival_seconds` and `all_vehicles_arrival_seconds` unset until execute, `executed_at` null, and `outcome` null; its `status` begins at `SCHEDULED`.

Execution transitions the drill from `SCHEDULED` to `EXECUTED`. The drill must currently be `SCHEDULED` (otherwise `ERR_DRILL_NOT_EXECUTABLE`), and the logical clock must fall within the scheduled window. An attempt to execute before `scheduled_start` is rejected with `ERR_DRILL_WINDOW_INVALID`; an attempt after `scheduled_end` is rejected with `ERR_DRILL_WINDOW_EXPIRED`. On execute, the caller supplies `first_vehicle_arrival_seconds` (seconds from alarm until the first vehicle reaches the midpoint of the farthest runway) and `all_vehicles_arrival_seconds` (seconds until all required vehicles are in position), each non-negative. The server stamps `executed_at` from the logical clock and computes `outcome`: `PASS` exactly when `first_vehicle_arrival_seconds` is at most 180 and `all_vehicles_arrival_seconds` is at most 240; otherwise `FAIL`. The thresholds are inclusive — exactly 180 and exactly 240 both pass.

An `EXECUTED` drill has two exits. Certification moves it to `CERTIFIED` and is gated on the drill currently being `EXECUTED` (otherwise `ERR_DRILL_NOT_CERTIFIABLE`) and on `outcome` being `PASS` (otherwise `ERR_RESPONSE_TIME_EXCEEDED`). Failing a drill moves it from `EXECUTED` to `FAILED` and only requires the drill currently be `EXECUTED` (otherwise `ERR_DRILL_NOT_EXECUTABLE`). Both `CERTIFIED` and `FAILED` are terminal.

### 3.8. Incident Response and Alert Escalation

When an emergency occurs, the `ArffChief` reports an incident by supplying an `alert_level` (`ALERT_1` for minor difficulty, `ALERT_2` for major difficulty, `ALERT_3` for accident — with ordering `ALERT_1 < ALERT_2 < ALERT_3`), a `location` description, and optionally an `aircraft_id` identifying the involved aircraft (the field may be null). The server stamps `reported_at` from the logical clock, leaves `controlled_at` null, and sets `status` to `REPORTED`.

Response is gated on capability. The incident must currently be `REPORTED` (otherwise `ERR_INCIDENT_NOT_OPEN`), and the profile's `effective_index` must be at-or-above the alert level's required index: `A` for `ALERT_1`, `B` for `ALERT_2`, `C` for `ALERT_3`. A profile below that floor is rejected with `ERR_INDEX_INSUFFICIENT_FOR_ALERT`. On success the incident transitions from `REPORTED` to `RESPONDING`.

Once responding, the `ArffChief` marks the incident controlled, transitioning `RESPONDING` to `CONTROLLED` and stamping `controlled_at` from the logical clock; a control attempt on a non-`RESPONDING` incident is rejected with `ERR_INCIDENT_NOT_RESPONDING`. Closure moves `CONTROLLED` to `CLOSED` and is blocked when any mutual-aid request for the incident sits in `REQUESTED` or `DEPLOYED` — such a close is rejected with `ERR_OPEN_REQUESTS_EXIST`. A close attempt on a non-`CONTROLLED` incident is rejected with `ERR_INCIDENT_NOT_CONTROLLED`.

Alert level can escalate in place while the incident is open. The escalation is a self-transition allowed from either `REPORTED` or `RESPONDING` (attempts from other states are rejected with `ERR_INCIDENT_NOT_OPEN`), and the new `alert_level` must be strictly higher than the current value — a same-level or downgrade patch is rejected with `ERR_ALERT_LEVEL_NOT_ESCALATION`. The `alert_level` field updates in place; no other fields change.

### 3.9. Mutual-Aid Agreements and Requests

An `AirportManager` negotiates a mutual-aid agreement with a partner airport or fire service. Each agreement names a `partner_airport_code`, a `max_alert_level` (the highest incident alert level the agreement covers), and a closed date window from `start_date` to `end_date`, both inclusive. `start_date` must be at-or-before `end_date`, otherwise `ERR_AGREEMENT_WINDOW_INVALID`. The window is closed — so a new agreement whose `start_date` equals an existing agreement's `end_date` for the same partner conflicts. A new agreement whose closed window overlaps another `DRAFT` or `ACTIVE` agreement for the same partner is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. New agreements start in `DRAFT` status.

Activation moves `DRAFT` to `ACTIVE` (an activate on a non-`DRAFT` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`). Termination moves `ACTIVE` to `TERMINATED` (terminate on a non-`ACTIVE` agreement is likewise rejected with `ERR_AGREEMENT_NOT_ACTIVE`). Independently, whenever the logical clock advances past `end_date`, an agreement in `DRAFT` or `ACTIVE` auto-transitions to `EXPIRED`. Both `EXPIRED` and `TERMINATED` are terminal.

When an incident needs help, the `ArffChief` raises a mutual-aid request naming the `agreement_id` and the `units_requested` (at least one). Three referential preconditions fire in order. The incident must currently be `REPORTED` or `RESPONDING`; otherwise `ERR_INCIDENT_NOT_RESPONDING`. The named agreement must currently be `ACTIVE`; otherwise `ERR_AGREEMENT_NOT_ACTIVE`. And the agreement's `max_alert_level` must cover the incident's `alert_level` — a request raised under an agreement whose ceiling is below the incident's level is rejected with `ERR_ALERT_LEVEL_NOT_COVERED`. The server populates `incident_id` from the path and starts the request in `REQUESTED` status.

The request lifecycle then runs through the `ArffChief`. Deploy moves `REQUESTED` to `DEPLOYED`; release moves `DEPLOYED` to `RELEASED`; decline moves `REQUESTED` to `DECLINED`. Each is gated on the request being in the required source state — deploy or decline on a non-`REQUESTED` request, or release on a non-`DEPLOYED` request, is rejected with `ERR_REQUEST_NOT_ACTIONABLE`. `RELEASED` and `DECLINED` are terminal.

### 3.10. Incident Reports and the Review Loop

Once an incident is `CONTROLLED` or `CLOSED`, a `SafetyOfficer` authors an incident report. The narrative must be at least 200 characters — shorter submissions are rejected with `ERR_NARRATIVE_TOO_SHORT`. The creation must occur within ten days of the incident's `controlled_at`, inclusive; a report attempted more than ten days after is rejected with `ERR_REPORT_WINDOW_EXPIRED`. The `SafetyOfficer` optionally supplies `agent_expenditure_lines`, an array of line items each carrying `vehicle_id`, `water_gal_used`, and `dry_chem_lb_used`, with both quantities non-negative; when omitted, the field defaults to an empty array. The server stamps `author_user_id` from the caller's `X-User-ID`, populates `incident_id` from the path, initializes `review_cycle_count` to zero, and sets `status` to `DRAFT`.

Agent expense is computed by a pinned rounding order. Each line's cost in cents is the line's `water_gal_used` multiplied by 137 plus the line's `dry_chem_lb_used` multiplied by 89, rounded half-up to a whole cent. The report's `agent_expense_total_cents` is the sum of the per-line rounded cents. Round per line first, then sum — never the reverse.

The review loop runs as a cycle. The author (and only the author — `X-User-ID` must equal `author_user_id`, otherwise `ERR_NOT_REPORT_AUTHOR`) may submit a `DRAFT` report, moving it to `SUBMITTED`; submitting a non-`DRAFT` report is rejected with `ERR_REPORT_NOT_SUBMITTABLE`. An `AirportManager` then reviews. Accept moves `SUBMITTED` to `ACCEPTED` (terminal). Return moves `SUBMITTED` back to `RETURNED` and increments `review_cycle_count` by one. Both accept and return require the report currently be `SUBMITTED` (otherwise `ERR_REPORT_NOT_REVIEWABLE`), and both forbid the reviewer being the original author — a reviewer whose `X-User-ID` equals `author_user_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. While a report is `DRAFT` or `RETURNED`, the author may edit it; editing updates `narrative` and/or `agent_expenditure_lines`, recomputes `agent_expense_total_cents` by the same rounding-pinned formula, and — when the previous status was `RETURNED` — resets status to `DRAFT`. Edits by anyone other than the author are rejected with `ERR_NOT_REPORT_AUTHOR`; edits on a `SUBMITTED` or `ACCEPTED` report are rejected with `ERR_REPORT_NOT_EDITABLE`.

### 3.11. Post-Incident Reviews and Corrective Actions

An accepted report supports a post-incident review. A `SafetyOfficer` opens one by supplying `findings` text and a count of `corrective_actions_open` (non-negative). The parent report must currently be `ACCEPTED`; opening a review on a non-`ACCEPTED` report is rejected with `ERR_REPORT_NOT_ACCEPTED`. At most one `OPEN` review may exist per report; a second open attempt is rejected with `ERR_REVIEW_ALREADY_OPEN`. The server populates `incident_report_id` from the path and starts the review in `OPEN` status.

While `OPEN`, the `SafetyOfficer` may patch `findings` or `corrective_actions_open` to track progress; a patch on a `CLOSED` review is rejected with `ERR_REVIEW_NOT_EDITABLE`. Closure moves `OPEN` to `CLOSED` and requires the review currently be `OPEN` (otherwise `ERR_REVIEW_NOT_CLOSABLE`) and `corrective_actions_open` to equal zero — a close attempt with any actions outstanding is rejected with `ERR_ACTIONS_STILL_OPEN`.

### 3.12. Annual FAA Inspection

Each calendar year the airport schedules an FAA inspection. An `AirportManager` schedules one by naming the `inspection_year` (unique across inspections — a duplicate year is rejected with `ERR_DUPLICATE_INSPECTION_YEAR`) and a `scheduled_on` ISO date. The inspection starts in `SCHEDULED` status, with `findings_count` null and `concluded_outcome` null.

A `FaaInspector` then drives the inspection lifecycle. Begin moves `SCHEDULED` to `IN_PROGRESS` (begin on a non-`SCHEDULED` inspection is rejected with `ERR_INSPECTION_NOT_BEGINNABLE`). Issue-findings moves `IN_PROGRESS` to `FINDINGS_ISSUED` and records `findings_count` from the caller's input (issue-findings on a non-`IN_PROGRESS` inspection is rejected with `ERR_INSPECTION_NOT_IN_PROGRESS`). Conclude moves `FINDINGS_ISSUED` to either `CLOSED_PASS` or `CLOSED_FAIL` based on the supplied `outcome`. A conclude on a non-`FINDINGS_ISSUED` inspection is rejected with `ERR_INSPECTION_NOT_CONCLUDABLE`.

A `PASS` conclusion applies three compliance gates on top of the state check. First, no `IndexDowngradeNotification` may sit in `PENDING`, `ACKNOWLEDGED`, or `OVERDUE` — a blocking notification yields `ERR_INSPECTION_BLOCKING_NOTIFICATIONS`. Second, at least one `ResponseDrill` must sit in `CERTIFIED` whose `executed_at` falls within the preceding twelve calendar months, measured by the same `month_index` arithmetic as training currency — `month_index` of today minus `month_index` of the drill's `executed_at` must be at most twelve; without one, `ERR_NO_VALID_CERTIFIED_DRILL`. Third, the profile's `index_compliance_status` must currently be `COMPLIANT`; otherwise `ERR_PROFILE_NOT_COMPLIANT`. On a `PASS` conclusion the server records `concluded_outcome` `PASS`; on a `FAIL` conclusion it records `concluded_outcome` `FAIL` and no additional gates apply. Both `CLOSED_PASS` and `CLOSED_FAIL` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/arff`. Resource-creation endpoints return HTTP 201 on success; modifications, state transitions, and reads return HTTP 200. Errors follow the standard error envelope. The table below is a summary only — request and response payloads are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/arff/_clock/set_current_utc` | Advance the logical clock to a supplied instant | `AirportManager` |
| POST | `/arff/airport-profile` | Create the singleton airport ARFF profile | `AirportManager` |
| GET | `/arff/airport-profile` | Read the profile with computed posture fields | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/airport-profile/readiness` | Computed readiness view with both calculation variants | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/aircraft` | Register an aircraft type | `AirportManager` |
| GET | `/arff/aircraft` | List aircraft types (optional `in_scheduled_service` filter) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/aircraft/{id}` | Get one aircraft type | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| PATCH | `/arff/aircraft/{id}` | Update an aircraft type's service figures | `AirportManager` |
| GET | `/arff/aircraft/{id}/index-determinations` | List determinations naming this aircraft as largest | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/aircraft/{id}/incidents` | List incidents involving this aircraft | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/vehicles` | Register an ARFF vehicle | `ArffChief` |
| GET | `/arff/vehicles` | List ARFF vehicles (optional `status` filter) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/vehicles/{id}` | Get one ARFF vehicle | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/vehicles/{id}/readiness-checks` | List readiness checks for a vehicle | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/vehicles/{id}/out-of-service-events` | List out-of-service events for a vehicle | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/readiness-checks` | Record a readiness check for a vehicle | `ArffChief` |
| POST | `/arff/firefighters` | Add a firefighter to the roster | `ArffChief` |
| GET | `/arff/firefighters` | List firefighters (optional `status` filter) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/firefighters/{id}` | Get one firefighter (Firefighter role: own id only) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/firefighters/{id}/training-records` | List a firefighter's live-fire training records | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/firefighters/{id}/suspend` | Suspend a firefighter | `ArffChief` |
| POST | `/arff/firefighters/{id}/reactivate` | Reactivate a firefighter | `ArffChief` |
| POST | `/arff/live-fire-training-records` | Record a live-fire training completion | `ArffChief` |
| POST | `/arff/response-drills` | Schedule a response drill on a runway | `ArffChief` |
| GET | `/arff/response-drills` | List response drills (optional `runway_designator`, `status` filters) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/response-drills/{id}` | Get one response drill | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/response-drills/{id}/execute` | Record measured arrival times and compute outcome | `ArffChief` |
| POST | `/arff/response-drills/{id}/certify` | Certify an executed drill (requires outcome PASS) | `ArffChief` |
| POST | `/arff/response-drills/{id}/fail` | Record a failed drill disposition | `ArffChief` |
| POST | `/arff/index-determinations` | Create an index determination (OCC-protected) | `AirportManager` |
| POST | `/arff/incidents` | Report an alert incident | `ArffChief` |
| GET | `/arff/incidents` | List incidents (optional `status`, `alert_level` filters) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/incidents/{id}` | Get one incident | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/incidents/{id}/respond` | Begin response (index-sufficiency gate) | `ArffChief` |
| POST | `/arff/incidents/{id}/control` | Mark incident controlled | `ArffChief` |
| POST | `/arff/incidents/{id}/close` | Close incident (blocked by open mutual-aid requests) | `ArffChief` |
| PATCH | `/arff/incidents/{id}/alert-level` | Escalate the alert level (strictly increasing) | `ArffChief` |
| GET | `/arff/incidents/{id}/mutual-aid-requests` | List mutual-aid requests for an incident | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/incidents/{id}/reports` | List incident reports for an incident | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/mutual-aid-agreements` | Create a mutual-aid agreement | `AirportManager` |
| GET | `/arff/mutual-aid-agreements` | List mutual-aid agreements (optional `partner_airport_code`, `status` filters) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/mutual-aid-agreements/{id}` | Get one mutual-aid agreement | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/mutual-aid-agreements/{id}/activate` | Activate an agreement | `AirportManager` |
| POST | `/arff/mutual-aid-agreements/{id}/terminate` | Terminate an agreement | `AirportManager` |
| GET | `/arff/mutual-aid-agreements/{id}/mutual-aid-requests` | List requests made under an agreement | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/incidents/{id}/mutual-aid-requests` | Request mutual aid for an incident | `ArffChief` |
| POST | `/arff/mutual-aid-requests/{id}/deploy` | Deploy requested units | `ArffChief` |
| POST | `/arff/mutual-aid-requests/{id}/release` | Release deployed units | `ArffChief` |
| POST | `/arff/mutual-aid-requests/{id}/decline` | Decline a request | `ArffChief` |
| POST | `/arff/vehicles/{id}/out-of-service-events` | Open an out-of-service event for a vehicle | `ArffChief` |
| POST | `/arff/out-of-service-events/{id}/restore` | Restore a vehicle to service after a passing recheck | `ArffChief` |
| GET | `/arff/index-downgrade-notifications` | List downgrade notifications (optional `status` filter) | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/index-downgrade-notifications/{id}` | Get one downgrade notification | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/index-downgrade-notifications/{id}/acknowledge` | FAA acknowledges a notification | `FaaInspector` |
| POST | `/arff/incidents/{id}/reports` | Create an incident report | `SafetyOfficer` |
| GET | `/arff/incident-reports/{id}` | Get one incident report | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| PATCH | `/arff/incident-reports/{id}` | Edit a DRAFT or RETURNED report (author only) | `SafetyOfficer` |
| POST | `/arff/incident-reports/{id}/submit` | Submit a report for review | `SafetyOfficer` |
| POST | `/arff/incident-reports/{id}/accept` | Accept a submitted report | `AirportManager` |
| POST | `/arff/incident-reports/{id}/return` | Return a submitted report for revision | `AirportManager` |
| POST | `/arff/incident-reports/{id}/post-incident-reviews` | Open a post-incident review on an ACCEPTED report | `SafetyOfficer` |
| GET | `/arff/incident-reports/{id}/post-incident-reviews` | List reviews for a report | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| PATCH | `/arff/post-incident-reviews/{id}` | Update an OPEN review's findings or open-action count | `SafetyOfficer` |
| POST | `/arff/post-incident-reviews/{id}/close` | Close a review (requires zero open actions) | `SafetyOfficer` |
| POST | `/arff/faa-inspections` | Schedule the annual FAA inspection | `AirportManager` |
| GET | `/arff/faa-inspections` | List FAA inspections | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| GET | `/arff/faa-inspections/{id}` | Get one FAA inspection | `AirportManager`, `ArffChief`, `SafetyOfficer`, `FaaInspector`, `Firefighter` |
| POST | `/arff/faa-inspections/{id}/begin` | Begin an inspection | `FaaInspector` |
| POST | `/arff/faa-inspections/{id}/issue-findings` | Record findings | `FaaInspector` |
| POST | `/arff/faa-inspections/{id}/conclude` | Conclude an inspection (PASS applies compliance gates) | `FaaInspector` |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the §2 and §3 narratives; this table is a reference index only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_PROFILE_NOT_FOUND` | 404 |
| `ERR_PROFILE_ALREADY_EXISTS` | 409 |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_FIREFIGHTER_NOT_FOUND` | 404 |
| `ERR_DRILL_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_REQUEST_NOT_FOUND` | 404 |
| `ERR_OOS_EVENT_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_STALE_PROFILE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VEHICLE_ALREADY_OUT_OF_SERVICE` | 409 |
| `ERR_READINESS_RECHECK_REQUIRED` | 422 |
| `ERR_MEASURED_EXCEEDS_CAPACITY` | 422 |
| `ERR_DRILL_NOT_EXECUTABLE` | 409 |
| `ERR_DRILL_NOT_CERTIFIABLE` | 409 |
| `ERR_RESPONSE_TIME_EXCEEDED` | 422 |
| `ERR_DRILL_WINDOW_INVALID` | 422 |
| `ERR_DRILL_WINDOW_EXPIRED` | 422 |
| `ERR_DRILL_WINDOW_OVERLAP` | 409 |
| `ERR_INCIDENT_NOT_OPEN` | 409 |
| `ERR_INCIDENT_NOT_RESPONDING` | 409 |
| `ERR_INCIDENT_NOT_CONTROLLED` | 409 |
| `ERR_OPEN_REQUESTS_EXIST` | 409 |
| `ERR_ALERT_LEVEL_NOT_ESCALATION` | 422 |
| `ERR_INDEX_INSUFFICIENT_FOR_ALERT` | 422 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_ALERT_LEVEL_NOT_COVERED` | 422 |
| `ERR_AGREEMENT_WINDOW_INVALID` | 422 |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_REQUEST_NOT_ACTIONABLE` | 409 |
| `ERR_OOS_EVENT_NOT_OPEN` | 409 |
| `ERR_NOTIFICATION_NOT_ACKNOWLEDGEABLE` | 409 |
| `ERR_REPORT_WINDOW_EXPIRED` | 422 |
| `ERR_NARRATIVE_TOO_SHORT` | 422 |
| `ERR_NOT_REPORT_AUTHOR` | 403 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 |
| `ERR_REPORT_NOT_SUBMITTABLE` | 409 |
| `ERR_REPORT_NOT_REVIEWABLE` | 409 |
| `ERR_REPORT_NOT_EDITABLE` | 409 |
| `ERR_REPORT_NOT_ACCEPTED` | 409 |
| `ERR_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_REVIEW_NOT_CLOSABLE` | 409 |
| `ERR_ACTIONS_STILL_OPEN` | 422 |
| `ERR_REVIEW_NOT_EDITABLE` | 409 |
| `ERR_DUPLICATE_CALL_SIGN` | 409 |
| `ERR_DUPLICATE_EMPLOYEE_NO` | 409 |
| `ERR_DUPLICATE_INSPECTION_YEAR` | 409 |
| `ERR_INSPECTION_NOT_BEGINNABLE` | 409 |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 |
| `ERR_INSPECTION_NOT_CONCLUDABLE` | 409 |
| `ERR_INSPECTION_BLOCKING_NOTIFICATIONS` | 422 |
| `ERR_NO_VALID_CERTIFIED_DRILL` | 422 |
| `ERR_PROFILE_NOT_COMPLIANT` | 422 |
| `ERR_AIRCRAFT_NOT_QUALIFYING` | 422 |
| `ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT` | 422 |
| `ERR_INDEX_BELOW_REQUIRED` | 422 |
| `ERR_FIREFIGHTER_NOT_ACTIVE` | 409 |
| `ERR_TRAINING_DATE_IN_FUTURE` | 422 |
