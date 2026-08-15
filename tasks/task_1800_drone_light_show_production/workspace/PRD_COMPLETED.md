# Drone Light Show Production API — Product Requirements Document

## 1. Introduction

A drone light show production company operates at the intersection of live entertainment and regulated aviation. Every performance requires an approved airspace authorization (often with waivers for night operations, beyond-visual-line-of-sight flight, or operations over people), a choreographed show design that has survived flight-path simulation, a geofenced and failsafe-configured fleet, a defensible crowd-distance perimeter, favorable weather confirmed through a formal go/no-go ritual, and a fully paid contract. After the drones land, the operation is not finished: post-flight telemetry must be reconciled against the fleet's batteries and airframes, and any incident must be investigated and closed with auditable segregation of duties.

This document specifies the API that backs that operation. The system manages venues and show bookings, design revisions and their simulations, authorization applications and their authority-side adjudication, safety configurations, the drone fleet with its charging infrastructure and launch grid, weather observations and go/no-go evaluations, payments and cancellation refunds, flight logs, and incident reports. All endpoints are mounted under the `/api` prefix. Five operator roles share the surface with deliberately segregated write powers, and every temporal rule in the system reads a controllable logical clock so that multi-day production timelines can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `ProductionPlanner`, `AuthorityOfficer`, `SafetyOfficer`, `FleetManager`, and `OpsAdmin`. A request that arrives without these headers, or whose `X-User-Role` value is not one of the five declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN`.

The five roles partition the write surface along professional lines. A `ProductionPlanner` is the show producer: they own venues, shows, design revisions, simulations, authorization applications, payments, postponements, and cancellations. An `AuthorityOfficer` is the aviation-authority reviewer: they process authorization applications — requesting information, deciding, and revoking. A `SafetyOfficer` is the safety authority: they approve safety configurations, record weather, run and certify go/no-go evaluations, certify a show for flight, file and close incident reports, and ground or release drones. A `FleetManager` is the fleet operator: they register drones, manage charge bays and charge sessions, populate the launch grid, and upload flight logs. An `OpsAdmin` is the platform operator: they alone drive the logical clock and the operations sweep. All five roles may use every read endpoint.

For every role — `ProductionPlanner`, `AuthorityOfficer`, `SafetyOfficer`, `FleetManager`, and `OpsAdmin` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an action demands an audit trail (for example as `created_by_user_id` on a safety configuration, `approved_by_user_id` on a safety configuration, `decided_by` on an authorization, `certified_by_user_id` on a go/no-go evaluation, `filed_by_user_id` and `closed_by_user_id` on an incident report), but it never compares `X-User-ID` to any entity's `id` for ownership. The only identity comparisons in the system are the segregation-of-duties checks described in §2.8, which compare the caller's `X-User-ID` against these recorded audit fields.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is generated from the server's wall clock at response time; unlike entity timestamps (§2.4) it does not read the logical clock.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter controls how many items are skipped and defaults to 0. A `limit` outside the 1-to-100 range, or a negative `offset`, is a request-body-level validation failure rejected with `ERR_VALIDATION`; a non-integer `limit` or `offset` is likewise `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order; ties on the creation timestamp — common while the logical clock is frozen — are broken by creation order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and the Operations Sweep

Every temporal rule in this document — windows being in the past or future, evaluation freshness, weather recency, turnaround buffers, entity timestamp stamping — reads a server-side **logical clock**, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set call the clock continues to report this default, and it never falls back to wall-clock time. An `OpsAdmin` may set the clock through a test-driving capability whose request carries a `to_iso8601` timestamp; any well-formed value is accepted, earlier or later than the current reading, and the response echoes the supplied timestamp verbatim as `current_utc`. All system-stamped timestamps on entities — `started_at` and `ended_at` on charge sessions, `evaluated_at` and `certified_at` on evaluations, `cancelled_at` on shows, `decided_at` on authorizations, and the `created_at` and `updated_at` of every entity — are taken from this logical clock. Client-supplied timestamps (show and authorization window fields, weather `recorded_at`, `to_iso8601`) are stored and echoed verbatim in the spelling supplied; they are parsed only for comparisons.

A second `OpsAdmin`-only capability runs the **operations sweep**. The sweep transitions every `APPROVED` airspace authorization whose window end is strictly before the current logical-clock reading to `EXPIRED`, with the show-downgrade cascade described in §3.3. The sweep response reports two arrays: `expired_authorization_ids` and `downgraded_show_ids`.

### 2.5. Resource Identity, Timestamps, and Versioning

All primary resources — Sites, ShowEvents, AirspaceAuthorizations, ShowDesigns, SafetyConfigurations, Drones, ChargeBays, ChargeSessions, LaunchGridAssignments, GoNoGoEvaluations, and IncidentReports — share a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascades originating elsewhere.

Three record types are immutable telemetry and carry only `id` and `created_at`: a **SimulationRun**, a **WeatherReading**, and a **FlightLog** have neither `updated_at` nor `version`. Once written, these records are never modified.

Cascades matter to versioning. When one operation touches several entities — a design lock superseding the previous design, a cancellation voiding grid slots and releasing drones, an incident closure grounding airframes — each touched entity independently refreshes its `updated_at` and increments its `version`.

### 2.6. Currency, Units, and Rounding Discipline

All monetary amounts are represented as integer numbers of cents; the relevant field names end in `_cents` (`contract_value_cents`, `deposit_cents`, `balance_cents`, `paid_total_cents`, `refunded_total_cents`, `refund_due_cents`, and the payment input `amount_cents`). Whenever a monetary computation produces a fraction of a cent, the result is rounded half up to the nearest integer cent.

Three other precision regimes appear in the system and must not be conflated. Crowd-distance radii and wind-speed limits are computed to exactly one decimal place with round-half-up. The cold-weather effective battery charge used at launch-grid assignment time is computed to exactly two decimal places with round-half-up. Battery percentages recorded on the drone and its charge sessions (`charge_pct`, `charge_from_pct`, `charge_to_pct`) and the flight-log `battery_consumed_pct` are integers.

Physical units are fixed across the API: altitudes and ceilings in feet above ground level, wind speeds in knots, precipitation in millimeters per hour, temperature in degrees Celsius, distances and radii in meters, speeds in meters per second, and choreographed durations in seconds.

### 2.7. Optimistic Concurrency on the Show Aggregate

Two write operations mutate the ShowEvent aggregate as a side effect of creating or promoting a sibling artifact, and both therefore require the client to declare which version of the show it last observed. Creating a safety configuration supersedes the show's current non-superseded configuration, and locking a show design re-pins the show while superseding the previously locked design; in both cases the request body must carry `expected_show_event_version` holding the show's `version` as the caller last read it. If the show's current `version` does not match the supplied value — because the caller's view of the show is stale relative to writes it has not observed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no supersession or re-pin occurs. No other endpoint in the API accepts a version field; these two are the only optimistic-concurrency checkpoints.

### 2.8. Segregation of Duties

Three actions in the system are entity-bound segregation-of-duties checkpoints, each comparing the caller's `X-User-ID` to an audit field recorded earlier on a related entity. A `SafetyOfficer` approving a safety configuration must not be the user who created it: the caller must differ from the configuration's `created_by_user_id`. A `SafetyOfficer` certifying a go/no-go evaluation must not be the user who approved the show's pinned safety configuration: the caller must differ from that configuration's `approved_by_user_id`. A `SafetyOfficer` closing an incident report must not be the user who filed it: the caller must differ from the report's `filed_by_user_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). These checks are entity-bound and are evaluated only after existence and state checks have passed, per the ordering in §2.9.

### 2.9. Identifier Resolution and the Validation Cascade Order

Every identifier presented to the API must resolve. Path identifiers — `siteId`, `showEventId`, `authorizationId`, `designId`, `simulationRunId`, `configId`, `droneId`, `chargeBayId`, `chargeSessionId`, `assignmentId`, `weatherReadingId`, `evaluationId`, `incidentId`, and `flightLogId` — are validated first, in left-to-right order as they appear in the path; the first identifier that does not resolve produces the corresponding 404 error and no further validation runs. After the path, every `*_id` reference in the request body must resolve, and body references that must belong to the path's scope are checked within that scope — for example, an `authorization_id` supplied to the authorize action must reference an authorization whose `show_event_id` is that very show, failing as `ERR_AUTHORIZATION_NOT_FOUND` when it is not. The 404 family is keyed per resource type: `ERR_SITE_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_SIMULATION_RUN_NOT_FOUND`, `ERR_SAFETY_CONFIG_NOT_FOUND`, `ERR_DRONE_NOT_FOUND`, `ERR_CHARGE_BAY_NOT_FOUND`, `ERR_CHARGE_SESSION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WEATHER_READING_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and `ERR_FLIGHT_LOG_NOT_FOUND`.

When several validations could reject the same request, they are evaluated in a fixed priority order, and the first failing check produces the response. The order is:

1. **Request-body schema validation** — required fields present, types valid, enum values in range, and numeric constraints honored (a gust reading no lower than its sustained wind, coordinates in range, a window end strictly after its start, a backup window at least 24 hours after the main window's end, pagination parameters in range). Required string fields must be non-empty, and timestamp fields must be well-formed ISO 8601 date-times that include seconds and a UTC designator or numeric offset. Computed or system-managed fields supplied in a request body are likewise rejected. All such failures carry `ERR_VALIDATION` (HTTP 400). Schema validation is staged rather than atomic: rejection of system-managed fields and required-field presence are always enforced first, before authentication; every other field check is applied at the point its value is first consumed — which, depending on the endpoint, may fall before or after the authentication, role-permission, and identifier-resolution checks — and always before the business rule that consumes the value.
2. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and the role recognized, else `ERR_UNAUTHENTICATED`.
3. **Role permission** — the caller's role must be permitted on the endpoint, else `ERR_FORBIDDEN`.
4. **Existence** — path then body identifiers, as described above.
5. **Optimistic concurrency** — where §2.7 applies, `expected_show_event_version` must equal the show's current `version`, else `ERR_STALE_VERSION`.
6. **State admissibility** — the target entity must be in a from-state that permits the requested transition (for example a show in `DESIGN_LOCKED` for the authorize action, deposit recorded before balance, a drone currently `AVAILABLE` to start charging — a drone already `CHARGING` fails here — a show `EXECUTED` with a `FLOWN` slot for the drone before a flight log is accepted, and a pinned `LOCKED` design present before safety approval). Creation of child artifacts — designs, simulation runs, authorization applications, and safety configurations — is not gated on the parent show's lifecycle. Failures carry `ERR_INVALID_STATE`, or `ERR_DESIGN_NOT_LOCKED` for the pinned-design gates on safety approval and on go/no-go evaluation requests.
7. **Segregation of duties** — the three entity-bound checks of §2.8, carrying `ERR_SEGREGATION_OF_DUTIES`.
8. **Safety and regulatory limits** — drone flyability, derated charge minimums, altitude ceilings against site maximums, geofence radius against the required crowd distance, configuration ceiling against the design's maximum altitude, and perimeter containment.
9. **Temporal window rules** — authorization window overlap, show turnaround buffers, drone double-booking across overlapping windows, weather readings not in the future, evaluation freshness, backup-window availability, and show-window placement.
10. **Uniqueness and capacity** — grid slot uniqueness, one slot per drone per show, grid coordinates within the site, charge-bay port capacity, charging a drone that is already full, grid size against the pinned design, and serial-number uniqueness.
11. **Referenced-object content rules** — authorization coverage and approval state at authorize time, the latest simulation passing at design lock, evaluation membership and certification at certify-go, the drone requirement on `MAJOR` incidents, charge-target ordering, and flight-telemetry availability for the as-flown perimeter variant.
12. **Fiscal rules** — payment amounts matching the exact component due, and the paid-in-full gate at execution. These are evaluated last.

## 3. Business Logic & Workflows

### 3.1. Venues and Booking a Show

Every production begins with a venue. A `ProductionPlanner` registers a Site by supplying its display `name`, its geographic position as `latitude` (between −90 and 90 degrees inclusive) and `longitude` (between −180 and 180 degrees inclusive), the usable ground rectangle as `ground_length_m` and `ground_width_m` (both strictly positive — the launch grid and the safety perimeter must physically fit inside it), and the venue's hard environmental ceilings: `site_max_wind_kt` for sustained wind, `site_max_gust_kt` for gusts, and `site_max_altitude_ft` for altitude, each strictly positive. Values outside these ranges are rejected with `ERR_VALIDATION`.

With a venue on file, the planner books a **ShowEvent**. The creation payload carries the `site_id` of the hosting venue, a display `name`, the planned performance window as `window_start` (inclusive) and `window_end` (exclusive), and the `drone_count_planned` the client has booked — at least one drone. The window start must be strictly after the current logical-clock reading; a window that is not in the future is rejected with `ERR_SHOW_WINDOW_IN_PAST`, and a `window_end` that is not after `window_start` fails schema validation with `ERR_VALIDATION`. The planner may optionally reserve a backup slot by supplying `backup_window_start` and `backup_window_end`: the two backup fields are paired, so each is required exactly when the other is present; the backup start must fall at least 24 hours after the main window's end; and the backup end must be after the backup start. Violations of the backup pairing or the 24-hour gap are `ERR_VALIDATION` failures.

Two shows at the same venue must respect a turnaround buffer of 120 minutes between one show's window end and the next show's start. At creation — and later at reschedule and at backup activation — the new window conflicts with another show at the same `site_id` when that other show is in any lifecycle other than `CANCELLED` or `POSTPONED` and the two windows fail to keep the buffer: the new window is clear of the other only when it starts at or after 120 minutes past the other's window end, or ends at or before 120 minutes before the other's window start. Any other arrangement is rejected with `ERR_SHOW_WINDOW_CONFLICT`. At creation the turnaround-conflict check is evaluated before the window-in-past check, so a window that violates both reports `ERR_SHOW_WINDOW_CONFLICT`.

Booking a show fixes its commercial terms immediately, computed once at creation and frozen on the record. The drone fee is tiered by the booked count: 2,500 cents for each of the first 100 drones, 2,200 cents for each of the next 200 drones (the 101st through the 300th), and 2,000 cents for every drone beyond 300. The pre-surcharge subtotal is a base fee of 500,000 cents (five thousand dollars) plus the drone fee. A logistics surcharge is then applied to that subtotal: 8 percent when the pre-surcharge subtotal is at least 1,000,000 cents (ten thousand dollars), otherwise 5 percent — note that the surcharge tier is keyed on the pre-surcharge subtotal, never on the final total that itself contains the surcharge. The surcharge amount is the subtotal multiplied by the applicable rate, rounded half up to integer cents, and the `contract_value_cents` is the subtotal plus the surcharge. The `deposit_cents` is 30 percent of the contract value, rounded half up to integer cents, and the `balance_cents` is the contract value minus the deposit.

A freshly booked show carries `lifecycle_status` `PLANNING` and `payment_status` `DEPOSIT_DUE` — two parallel state dimensions that evolve independently. Its `readiness_posture` starts at `NOT_READY`, `cancellation_status` at `NONE`, `backup_consumed` at false, `paid_total_cents` and `refunded_total_cents` at zero, and `assigned_count` at zero. The three pin references — `pinned_design_id`, `pinned_safety_config_id`, and `pinned_authorization_id` — are null until the corresponding artifacts lock or approve in, and `cancelled_at`, `cancellation_tier`, and `refund_due_cents` remain null unless the show is cancelled.

### 3.2. Choreography: Design Revisions and Simulation

A show's choreography lives in **ShowDesign** revisions. Creating a design requires the `show_event_id` of the parent show plus the choreography parameters: `drone_count` (at least one), `max_altitude_ft` (strictly positive), `duration_sec` (at least 60 seconds of flight), and `min_separation_m` (strictly positive — the minimum pairwise drone separation the choreography guarantees). Each design receives a `design_version_no`, a per-show monotone counter that starts at 1 and is assigned in creation order: the number is one more than the count of designs already existing for that show, regardless of those designs' statuses. New designs begin in `DRAFT` status.

Before a design can be trusted, it must be simulated. Recording a **SimulationRun** takes the `show_design_id` under test and three observed metrics: `min_separation_observed_m` (the tightest pairwise separation seen, zero or greater), `battery_draw_pct` (the worst-drone draw, between 0 and 100 inclusive), and `max_speed_mps` (the fastest groundspeed, zero or greater). The run's `verdict` is computed: `PASS` when the observed separation is at least the design's guaranteed `min_separation_m` (the boundary is inclusive — equality passes), the battery draw is at most 80 percent, and the speed is at most 12.0 meters per second; any shortfall yields `FAIL`. A run recorded while its design is `DRAFT` moves the design to `SIMULATED` — including the first run after a revision returned the design to `DRAFT`; runs recorded against a design in any other status (`SIMULATED`, `LOCKED`, or `SUPERSEDED`) are stored without further state change, which is what makes the revision loop possible. Runs can be listed and filtered by `show_design_id` or `verdict`.

The revision loop is deliberately simple: revising a `SIMULATED` design returns it to `DRAFT` for another round of simulation (any other from-state is `ERR_INVALID_STATE`). When the choreography is final, the planner locks the design. Locking requires the design to be `SIMULATED` (else `ERR_INVALID_STATE`), requires the most recent simulation run for the design — the latest by `created_at`, with ties (common while the logical clock is frozen) broken by creation order, the later-created run winning — to hold a `PASS` verdict (else `ERR_SIMULATION_NOT_PASSING`), and requires the parent show's `lifecycle_status` to be one of `PLANNING`, `DESIGN_LOCKED`, `AUTHORIZED`, or `READY` (else `ERR_INVALID_STATE`). Because locking re-pins the show, the lock request must carry `expected_show_event_version` per §2.7; a stale view of the show is rejected with `ERR_STALE_VERSION`.

A successful lock is a small cascade. The design becomes `LOCKED`. Any other design for the same show that was `LOCKED` is automatically moved to `SUPERSEDED` with its own version incremented — a `LOCKED` design has no manual transitions out, only this automatic supersession. The parent show's `pinned_design_id` is set to the newly locked design, and the show's lifecycle moves to `DESIGN_LOCKED` from whichever of `PLANNING`, `AUTHORIZED`, or `READY` it occupied: re-pinning a new design invalidates the authorization readiness built on the old one. The show's `readiness_posture` is recomputed and its `version` incremented alongside the design's.

### 3.3. The Airspace Authorization Lifecycle

No show flies without airspace approval. The planner files an **AirspaceAuthorization** application with the `show_event_id` it serves, the requested `window_start` (inclusive) and `window_end` (exclusive), the requested `altitude_ceiling_ft` (strictly positive), and `waiver_types` — an array of waiver kind strings such as `NIGHT_OPS`, `BVLOS`, or `OVER_PEOPLE`, which may be empty when no waivers are needed. Applications are born in `DRAFT`.

Submitting moves an application from `DRAFT` to `UNDER_REVIEW` and runs three regulatory checks, in the order presented here. The requested ceiling must not exceed the `site_max_altitude_ft` of the venue hosting the parent show, else `ERR_ALTITUDE_CEILING_EXCEEDS_SITE`. The requested window must fully cover the show's window — starting no later than the show's start and ending no earlier than the show's end — and must likewise cover the backup window when one is set and not yet consumed, else `ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`. And the requested window must not overlap any other application serving a show at the same site that is `UNDER_REVIEW` or `APPROVED`: overlap uses half-open interval semantics, so two windows that merely touch — one ending exactly when the other begins — do not conflict, while any strict interleaving of one window's start before the other's end and the other's start before the first's end is rejected with `ERR_AUTHORIZATION_WINDOW_OVERLAP`. A submission attempted from any status other than `DRAFT` is `ERR_INVALID_STATE`.

On the authority side, an `AuthorityOfficer` may park an `UNDER_REVIEW` application by requesting more information (optionally carrying an `info_note`), moving it to `INFO_REQUESTED`; the planner answers by resubmitting (optionally with an `amendment_note`), which returns it to `UNDER_REVIEW`. The decision call takes a `decision` of `APPROVED` or `DENIED` and is only valid from `UNDER_REVIEW` (else `ERR_INVALID_STATE`). Approval deliberately re-validates the regulatory trio at decision time, because the world may have changed since submission: the ceiling is checked against the site maximum again (`ERR_ALTITUDE_CEILING_EXCEEDS_SITE`), the window coverage is checked against the show's current window and unconsumed backup window again (`ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`), and the overlap check is re-run — this time against other `APPROVED` authorizations at the same site (`ERR_AUTHORIZATION_WINDOW_OVERLAP`). The three re-validations run in the order stated. Either decision stamps `decided_at` from the logical clock and records the deciding officer's identifier in `decided_by`.

A `DENIED` application is not dead: the planner may revise it back to `DRAFT`, optionally supplying amended `window_start`, `window_end`, or `altitude_ceiling_ft` values; the two window fields amend independently — an unamended field keeps its stored value — the resulting window must still end strictly after it starts (else `ERR_VALIDATION`), and an amended ceiling must be strictly positive (else `ERR_VALIDATION`); revision clears `decided_at` and `decided_by` so the refiled application carries no stale adjudication metadata. A `DRAFT` application may instead be withdrawn outright, moving it to `WITHDRAWN`. Each of these planner and authority actions is valid only from its named from-state — revise from `DENIED`, withdraw from `DRAFT`, request-info and decide from `UNDER_REVIEW`, resubmit from `INFO_REQUESTED` — and any other status is rejected with `ERR_INVALID_STATE`. On the enforcement side, an `AuthorityOfficer` may revoke an `APPROVED` authorization (optionally with a `reason`), moving it to `REVOKED`; revocation cascades — every show whose `pinned_authorization_id` names this authorization and whose lifecycle is `DESIGN_LOCKED`, `AUTHORIZED`, `READY`, or `GO_CERTIFIED` is dropped back to `PLANNING` with `readiness_posture` `NOT_READY`, each such show's version incremented. The same `APPROVED`-to-`EXPIRED` fate with the identical cascade arrives via the operations sweep once the logical clock has passed the authorization's window end, and a confirmed critical incident revokes the show's authorization through the cascade in §3.8. The terminal states of this machine are `DENIED`, `REVOKED`, `EXPIRED`, and `WITHDRAWN`.

### 3.4. Geofencing, Failsafes, and Crowd-Distance Governance

The **SafetyConfiguration** captures the firmware-level guardrails for a show. Creating one takes the `show_event_id`, the `geofence_radius_m` of the geofence cylinder around the launch point (strictly positive), the `altitude_hard_ceiling_ft` enforced in firmware (strictly positive), the `lost_link_action` — one of `HOVER_THEN_LAND`, `RETURN_TO_HOME`, or `IMMEDIATE_LAND` — the `geofence_breach_action` — one of `RETURN_TO_HOME` or `IMMEDIATE_LAND` — and the `battery_rtl_threshold_pct`, the remaining-battery percentage at which drones automatically return to launch, which must lie between 10 and 80 inclusive. Because creation supersedes the show's current configuration, the request must carry `expected_show_event_version` per §2.7, and a stale show version is rejected with `ERR_STALE_VERSION`. The creator's identifier is recorded as `created_by_user_id`, and the new configuration starts in `DRAFT`. Creation is itself a mutation of the show aggregate: whether or not any supersession or downgrade occurs, the show's `updated_at` refreshes and its `version` increments (twice when a pinned configuration is superseded — once for the downgrade cascade and once for the creation itself).

Supersession is aggressive in both directions. When a new configuration is created for a show, the show's previous non-superseded configuration — whether `DRAFT` or `APPROVED` — automatically becomes `SUPERSEDED` with its version incremented. If the superseded configuration was the show's pinned one, the show itself downgrades: a `lifecycle_status` of `DESIGN_LOCKED`, `AUTHORIZED`, `READY`, or `GO_CERTIFIED` falls back to `PLANNING`, the `readiness_posture` becomes `NOT_READY`, and the show's version increments. Approving one configuration likewise supersedes any other `APPROVED` configuration for the show.

Crowd distance is governed by a single formula used in several places. The **required radius** is 40 meters, plus 0.4 meters for every foot of altitude, plus 1.2 meters per drone, rounded half up to one decimal place. **Containment** is `VALID` when the required radius plus a 15-meter buffer fits within half of the smaller of the site's `ground_length_m` and `ground_width_m`; otherwise it is `INSUFFICIENT`. The formula has two variants. The `PLANNED` variant — the default whenever a pinned design exists — draws altitude and count from the pinned design's `max_altitude_ft` and `drone_count`. The `AS_FLOWN` variant is a post-flight audit: it uses the highest `max_altitude_reached_ft` across the show's flight logs and the count of those logs, producing a different radius whenever reality deviated from the plan; requesting `AS_FLOWN` for a show with no flight logs is rejected with `ERR_NO_FLIGHT_DATA`. The perimeter-assessment computed read takes an optional `variant` (`PLANNED` by default) and returns the `variant` used, the computed `required_radius_m`, the `buffer_m` (15 meters), the site's `site_min_half_dim_m` — half of the smaller ground dimension — and the resulting `containment`. A `variant` value other than `PLANNED` or `AS_FLOWN` is rejected with `ERR_VALIDATION`, and requesting `PLANNED` for a show with no pinned design is rejected with `ERR_DESIGN_NOT_LOCKED`.

Approval of a configuration is a `SafetyOfficer` action with five gates, evaluated in the order presented. The configuration must be `DRAFT`, else `ERR_INVALID_STATE`. The parent show must hold a pinned design in `LOCKED` status, else `ERR_DESIGN_NOT_LOCKED`. Segregation of duties applies per §2.8: the approver must not be the configuration's creator, else `ERR_SEGREGATION_OF_DUTIES`. The `geofence_radius_m` must be at least the required crowd-distance radius computed for the pinned design under the `PLANNED` variant, else `ERR_GEOFENCE_BELOW_REQUIRED`. The `altitude_hard_ceiling_ft` must be at least the pinned design's `max_altitude_ft`, else `ERR_CEILING_BELOW_DESIGN`, while also not exceeding the venue's `site_max_altitude_ft`, else `ERR_ALTITUDE_CEILING_EXCEEDS_SITE`. A successful approval stamps the configuration `APPROVED`, records the approver as `approved_by_user_id`, supersedes any other `APPROVED` configuration for the show, sets the show's `pinned_safety_config_id` to this configuration, recomputes the show's posture, and increments both versions.

With a locked design and an approved configuration in place, the planner performs the **authorize** step, which moves the show from `DESIGN_LOCKED` to `AUTHORIZED`. The request names an `authorization_id`; that identifier must resolve to an authorization whose `show_event_id` is this show (else `ERR_AUTHORIZATION_NOT_FOUND`), whose status is `APPROVED` (else `ERR_AUTHORIZATION_NOT_APPROVED`), and whose window covers the show's window — plus the backup window when one is set and unconsumed (else `ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`). Authorizing also requires the show to actually be `DESIGN_LOCKED` (else `ERR_INVALID_STATE`), a pinned safety configuration in `APPROVED` status (else `ERR_SAFETY_CONFIG_NOT_APPROVED`), and `PLANNED` perimeter containment equal to `VALID` (else `ERR_PERIMETER_INSUFFICIENT`). These gates are evaluated in a fixed order: the authorization's resolution against this show (`ERR_AUTHORIZATION_NOT_FOUND`), the show's `DESIGN_LOCKED` state (`ERR_INVALID_STATE`), the pinned configuration's approval (`ERR_SAFETY_CONFIG_NOT_APPROVED`), the authorization's `APPROVED` status (`ERR_AUTHORIZATION_NOT_APPROVED`), window coverage (`ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`), and finally perimeter containment (`ERR_PERIMETER_INSUFFICIENT`). On success the show's `pinned_authorization_id` is set to the named authorization, the posture is recomputed, and the show's version increments. If the launch grid is already complete for the pinned design — `assigned_count` equals its `drone_count` — and containment is `VALID` at authorize time, the show advances directly to `READY` rather than `AUTHORIZED`.

### 3.5. Fleet Logistics: Drones, Charging, and the Launch Grid

The `FleetManager` maintains the airframe registry. Registering a **Drone** requires a `serial_number` that is globally unique across all drones — a duplicate is rejected with `ERR_DUPLICATE_SERIAL` — and an airframe `model`. The `charge_pct` may be supplied (0 to 100 inclusive) and defaults to 100; `battery_cycle_count` may likewise be seeded to register a used airframe — a non-negative integer, else `ERR_VALIDATION` — and defaults to 0. New drones start `AVAILABLE`.

Charging infrastructure is per-venue. A **ChargeBay** is registered with its `site_id`, an operator-chosen `bay_code` that must be unique within that site — a duplicate `bay_code` at the same site is rejected with `ERR_VALIDATION` — and a `port_count` of at least one — the number of drones the bay can charge at once, enforced as aggregate capacity. Starting a **ChargeSession** pairs a `drone_id` with a `charge_bay_id`. The drone must be `AVAILABLE`: a drone already `CHARGING` (or in any other non-available state) fails the state check with `ERR_INVALID_STATE`, which also enforces the one-active-session-per-drone rule. A bay already hosting `port_count` `ACTIVE` sessions rejects the request with `ERR_BAY_CAPACITY_EXCEEDED`, and a drone whose `charge_pct` is already 100 is rejected with `ERR_CHARGE_NOT_NEEDED`. A new session captures the drone's current charge as `charge_from_pct`, stamps `started_at` from the logical clock, enters `ACTIVE` status, and moves the drone to `CHARGING`.

Sessions end in one of two ways, each carrying the reached `charge_to_pct`. Completing requires the target to be strictly above `charge_from_pct` and at most 100, otherwise `ERR_INVALID_CHARGE_TARGET`; the session becomes `COMPLETED`. Interrupting keeps a partial charge: the target need only be at least `charge_from_pct` and at most 100, with the same `ERR_INVALID_CHARGE_TARGET` on violation; the session becomes `INTERRUPTED`. Either way `ended_at` is stamped, the drone's `charge_pct` is set to the session's `charge_to_pct`, and the drone returns from `CHARGING` to `AVAILABLE`.

Populating the **launch grid** is the last fleet step before flight. An assignment names the `show_event_id`, the `drone_id`, and the 0-based slot coordinates `grid_row` and `grid_col`. The show must be `AUTHORIZED` or `READY` (else `ERR_INVALID_STATE`), and the drone must be `AVAILABLE` or `RESERVED` — a `GROUNDED`, `IN_MAINTENANCE`, `RETIRED`, or `CHARGING` drone is rejected with `ERR_DRONE_NOT_FLYABLE`, while a `RESERVED` drone (held by another, non-overlapping show) remains assignable subject to the checks below.

Cold weather degrades batteries, so the charge check at assignment time uses a derated effective charge rather than the raw gauge. The system takes the most recent weather reading at the show's site whose `recorded_at` lies within the trailing 120 minutes up to and including the current logical-clock reading — a reading exactly 120 minutes old is included — the latest by `recorded_at`, with ties broken by `created_at` and any remaining ties by creation order, the later-created reading winning. When no such reading exists, or the latest reading's temperature is at least 5 degrees Celsius, the derate factor is 1.0 and eligibility is decided on the raw `charge_pct`. A latest temperature below 5 but at least −5 degrees Celsius derates to 0.85; below −5 degrees the factor is 0.70. The effective charge is the drone's `charge_pct` multiplied by the factor, rounded half up to two decimal places, and the assignment is eligible only when that effective charge reaches the 85 percent launch minimum, else `ERR_CHARGE_BELOW_MINIMUM`. The boundary is exact: a fully charged drone at the 0.85 derate posts an effective charge of exactly 85.00 and passes, while the same derate on a 99 percent drone yields 84.15 and fails.

Grid geometry and uniqueness rules then apply. The launch grid uses a 2.0-meter slot pitch over the venue's ground rectangle: one more than `grid_row`, multiplied by the 2.0-meter pitch, must not exceed the site's `ground_length_m`, and one more than `grid_col` times the pitch must not exceed `ground_width_m`; out-of-bounds coordinates are rejected with `ERR_GRID_OUT_OF_BOUNDS`. A coordinate pair is occupied for the show when an existing slot in `ASSIGNED`, `FLOWN`, or `RECONCILED` status sits on it — a `VOIDED` slot frees its coordinate — and reusing an occupied pair is `ERR_GRID_SLOT_OCCUPIED`. A drone may hold at most one `ASSIGNED` slot on the show (else `ERR_DRONE_ALREADY_ASSIGNED`) and must not already hold an `ASSIGNED` slot on another show whose window overlaps this one — the same half-open semantics as airspace windows, so back-to-back shows touching at an endpoint do not conflict — else `ERR_DRONE_DOUBLE_BOOKED`. Finally, the grid must not exceed the choreography: when the show's `assigned_count` already equals the pinned design's `drone_count`, further assignments are rejected with `ERR_ASSIGNMENT_EXCEEDS_DESIGN`. The assignment checks apply in a fixed order: show state (`ERR_INVALID_STATE`), drone flyability (`ERR_DRONE_NOT_FLYABLE`), derated charge (`ERR_CHARGE_BELOW_MINIMUM`), cross-show double-booking (`ERR_DRONE_DOUBLE_BOOKED`), then a single creation-ordered pass over the show's existing slots that reports the first slot-occupancy (`ERR_GRID_SLOT_OCCUPIED`) or per-show drone-reuse (`ERR_DRONE_ALREADY_ASSIGNED`) violation encountered, then grid bounds (`ERR_GRID_OUT_OF_BOUNDS`), and finally design capacity (`ERR_ASSIGNMENT_EXCEEDS_DESIGN`).

Each accepted assignment moves an `AVAILABLE` drone to `RESERVED` — a drone already `RESERVED` keeps its state and version unchanged — and increments the show's `assigned_count` by one. When the count thereby reaches the pinned design's `drone_count` while perimeter containment is `VALID`, the show automatically advances from `AUTHORIZED` to `READY`. Conversely, voiding an assignment — a `FleetManager` action valid only from `ASSIGNED`, else `ERR_INVALID_STATE` — moves the slot to `VOIDED`, returns the drone from `RESERVED` to `AVAILABLE` when it holds no remaining `ASSIGNED` slot on any show (a drone still reserved elsewhere stays `RESERVED`), decrements `assigned_count`, and drops a `READY` show whose grid is no longer complete back to `AUTHORIZED`, with the posture recomputed and both versions incremented.

The remaining drone lifecycle is safety-driven. A `FleetManager` may send an `AVAILABLE` drone to maintenance (`IN_MAINTENANCE`; any other from-state is `ERR_INVALID_STATE`); the same transition happens automatically when a flight log pushes the airframe's `battery_cycle_count` to 200, as detailed in §3.8. A `SafetyOfficer` may ground a drone from `AVAILABLE`, `RESERVED`, or `IN_MAINTENANCE` (any other from-state is `ERR_INVALID_STATE`): grounding moves it to `GROUNDED`, and grounding a `RESERVED` drone additionally voids every `ASSIGNED` launch-grid slot it holds — each voided slot decrements its show's `assigned_count` and downgrades a `READY` show to `AUTHORIZED` with posture recomputed. Release from `IN_MAINTENANCE` or `GROUNDED` back to `AVAILABLE` is a `SafetyOfficer` action (else `ERR_INVALID_STATE`). Retirement to the terminal `RETIRED` state is a `FleetManager` action available only from `AVAILABLE`, `IN_MAINTENANCE`, or `GROUNDED` (else `ERR_INVALID_STATE`).

### 3.6. Weather Surveillance, Go/No-Go Certification, and Flying the Show

Weather enters the system as immutable **WeatherReading** observations recorded by a `SafetyOfficer` against a `site_id`. Each reading carries its `recorded_at` timestamp — which must not be after the current logical-clock reading, else `ERR_READING_IN_FUTURE` — plus `wind_speed_kt` and `gust_kt` (both non-negative, and the gust must be at least the sustained speed, else `ERR_VALIDATION`), `precip_mm_hr` (non-negative), and `temperature_c`. Readings can be listed and filtered by `site_id`.

A show's effective wind limits derate a baseline of 18 knots according to the pinned design's ambition. The altitude factor is 1.0 when the pinned design's `max_altitude_ft` is at most 200 feet, 0.9 when it is above 200 but at most 400 feet, and 0.8 above 400 feet. The fleet factor is 1.0 when the design's `drone_count` is at most 100, 0.9 when above 100 but at most 300, and 0.8 above 300. The `effective_wind_limit_kt` is the lesser of the venue's `site_max_wind_kt` and the 18-knot baseline multiplied by both factors, rounded half up to one decimal place. The `effective_gust_limit_kt` is the effective wind limit multiplied by 1.3, again rounded half up to one decimal place. Computing these limits requires the show to hold a pinned design in `LOCKED` status, since the derates read its parameters; requesting an evaluation for a show without one is rejected with `ERR_DESIGN_NOT_LOCKED`.

A `SafetyOfficer` requests a **GoNoGoEvaluation** for a show by its `show_event_id`; the show must be `AUTHORIZED`, `READY`, or `GO_CERTIFIED` (else `ERR_INVALID_STATE`), and this lifecycle check is evaluated before the pinned-design check above. The evaluation stamps `evaluated_at` from the logical clock and examines the weather readings at the show's site whose `recorded_at` falls within the 60-minute lookback up to and including `evaluated_at` — a reading exactly 60 minutes old is included. The operative reading is the latest by `recorded_at`, with ties broken by `created_at` and any remaining ties by creation order, the later-created reading winning. When the lookback window holds no readings at all, the verdict is `NO_GO` and `reason_codes` is the single entry `NO_WEATHER_DATA`. Otherwise the system evaluates four checks in a fixed order, collecting every failed reason: sustained wind strictly above the effective wind limit records `WIND_SUSTAINED_EXCEEDED` (a reading exactly at the limit passes — the comparison is strictly-greater); gust strictly above the effective gust limit records `GUST_EXCEEDED`; any nonzero precipitation rate records `PRECIPITATION`; and a temperature below −10 degrees Celsius or above 40 degrees Celsius records `TEMPERATURE`. The `verdict` is `GO` exactly when `reason_codes` is empty, and `NO_GO` otherwise. The computed limits are stored on the evaluation as `effective_wind_limit_kt` and `effective_gust_limit_kt`. New evaluations are `PROVISIONAL`.

Certification is a second `SafetyOfficer` act, segregated per §2.8: the certifier must not be the `approved_by_user_id` of the show's pinned safety configuration, else `ERR_SEGREGATION_OF_DUTIES`. Certifying a `PROVISIONAL` evaluation (any other state is `ERR_INVALID_STATE`) moves it to `CERTIFIED` and stamps `certified_at` and `certified_by_user_id`.

Two gates then stand between the show and flight. **Certify-go**, performed by a `SafetyOfficer`, moves a `READY` show to `GO_CERTIFIED`: the request names an `evaluation_id` that must reference an evaluation belonging to this show (else `ERR_EVALUATION_NOT_FOUND`), in `CERTIFIED` status (else `ERR_EVALUATION_NOT_CERTIFIED`), with a `GO` verdict (else `ERR_NO_GO_IN_EFFECT`), and certified recently — the gap between `certified_at` and the current logical-clock reading must not exceed 240 minutes, with an evaluation exactly 240 minutes old still acceptable, else `ERR_EVALUATION_STALE`. A show must also simply be `READY` for this step (else `ERR_INVALID_STATE`). The gates are evaluated in the order: the evaluation's resolution against this show (`ERR_EVALUATION_NOT_FOUND`), the show's `READY` state (`ERR_INVALID_STATE`), certification status (`ERR_EVALUATION_NOT_CERTIFIED`), verdict (`ERR_NO_GO_IN_EFFECT`), and freshness (`ERR_EVALUATION_STALE`). Success sets the show's `readiness_posture` to `GO` outright and increments its version.

**Execute**, performed by the `ProductionPlanner`, is the point of no return. The show must be `GO_CERTIFIED` (else `ERR_INVALID_STATE`); the logical clock must read at or after `window_start` and strictly before `window_end` (else `ERR_OUTSIDE_SHOW_WINDOW`); a `CERTIFIED` `GO` evaluation whose certification is still within the 240-minute freshness window must exist (else `ERR_EVALUATION_STALE`); and the commercial gate applies — `payment_status` must be `PAID_IN_FULL` (else `ERR_SHOW_NOT_PAID_IN_FULL`). Execution moves the show to the terminal `EXECUTED` state, flips every `ASSIGNED` launch-grid slot for the show to `FLOWN` (each flipped slot's version increments), and recomputes the show's posture from the gates.

Throughout this arc, the show's **readiness posture** is a computed aggregate of six gates, recomputed on any mutation to the show, its designs, its safety configurations, its authorizations, its grid assignments, or its evaluations. Gate g1 holds when a pinned design exists in `LOCKED` status and the latest simulation run for it returned `PASS`. Gate g2 holds when a pinned safety configuration exists in `APPROVED` status. Gate g3 holds when a pinned authorization exists in `APPROVED` status whose window covers the show's window, and additionally covers the backup window when one is set and not consumed. Gate g4 holds when the `PLANNED` crowd-distance containment is `VALID`. Gate g5 holds when `assigned_count` equals the pinned design's `drone_count`. Gate g6 holds when a `CERTIFIED` evaluation with verdict `GO` exists whose `certified_at` is within the trailing 240 minutes. The posture is `GO` when all six gates hold, `CLEARED` when g1 through g5 hold, and `NOT_READY` otherwise. The readiness computed read reports `posture`, the per-gate breakdown `gates` in the fixed order g1 through g6, the current `assigned_count`, and `required_drone_count` — the pinned design's `drone_count`, or null when no design is pinned.

Posture and lifecycle also move without operator action when the ground shifts. While `READY`, a show automatically falls back to `AUTHORIZED` when its `assigned_count` drops below the pinned design's `drone_count`, or when a pinned reference — design, configuration, or authorization — is invalidated; the posture is recomputed in either case. Separately, the invalidation cascades themselves are heavier: a pinned design becoming `SUPERSEDED`, the pinned safety configuration becoming `SUPERSEDED`, or the pinned authorization becoming `REVOKED` or `EXPIRED` each move a show in `DESIGN_LOCKED`, `AUTHORIZED`, `READY`, or `GO_CERTIFIED` back to `PLANNING` with posture `NOT_READY`, incrementing the show's version.

### 3.7. Schedule Changes, Payments, and Cancellation Policy

Weather and authority timelines slip, and the production calendar absorbs the slippage through three planner actions. **Postponing** a show is valid from `AUTHORIZED`, `READY`, or `GO_CERTIFIED` (else `ERR_INVALID_STATE`) and moves the show to `POSTPONED` with posture `NOT_READY`; the request may carry an optional free-text `reason`. A postponed show returns to the pipeline in one of two ways. **Rescheduling** replaces the window with the supplied `window_start` and `window_end`: the new start must be strictly after the current logical-clock reading (else `ERR_SHOW_WINDOW_IN_PAST`) and the new window must clear the 120-minute turnaround buffer against the venue's other shows (else `ERR_SHOW_WINDOW_CONFLICT`), with the turnaround-conflict check evaluated before the in-past check. **Activating the backup window** requires a backup window to be set with `backup_consumed` still false, and the backup start must be strictly after the current logical-clock reading; failures on either count are `ERR_BACKUP_WINDOW_UNAVAILABLE`. Activation moves the show's window to the backup window, sets `backup_consumed` to true, clears the backup fields, and re-runs the turnaround check on the moved window (else `ERR_SHOW_WINDOW_CONFLICT`). Both paths land the show in `PLANNING`, and both then recompute: if the pinned design is still `LOCKED`, the show immediately advances to `DESIGN_LOCKED` without further operator action, and the posture is recomputed with the show's version incremented.

On the commercial track, payment arrives in exactly two installments recorded through the record-payment action with a `kind` and an `amount_cents` — the amount must be a non-negative integer (else `ERR_VALIDATION`). A payment with `kind` `DEPOSIT` is accepted only while `payment_status` is `DEPOSIT_DUE` (else `ERR_INVALID_STATE`) and its amount must equal `deposit_cents` exactly — no partial deposits, no overpayments — else `ERR_PAYMENT_AMOUNT_MISMATCH`; acceptance adds the amount to `paid_total_cents` and moves the show to `DEPOSIT_PAID`. A payment with `kind` `BALANCE` likewise requires `DEPOSIT_PAID` and an amount exactly equal to `balance_cents`, completing the contract at `PAID_IN_FULL`. The deposit must precede the balance; `paid_total_cents` only ever accumulates and is never decremented by any operation.

**Cancelling** a show is valid from every lifecycle except the terminal `EXECUTED` and `CANCELLED` states (else `ERR_INVALID_STATE`) and may carry an optional `reason`. Cancellation stamps `cancelled_at` from the logical clock, moves `cancellation_status` from `NONE` to `FILED`, and computes — once, freezing the result — the cancellation tier and the `refund_due_cents`. It also cascades through the grid: every `ASSIGNED` launch-grid slot for the show becomes `VOIDED`, the show's `assigned_count` drops to zero, and each drone released by such a void returns from `RESERVED` to `AVAILABLE` with its own version incremented. The show lands in `CANCELLED` with posture `NOT_READY`.

The refund schedule keys on lead time — the hours between `cancelled_at` and the show's `window_start`. The paid money is first split into a deposit portion (the lesser of `paid_total_cents` and `deposit_cents`) and a balance portion (the remainder of `paid_total_cents`). With at least 336 hours of lead time — fourteen days — the tier is `T1_FULL` and both portions refund at 100 percent. With at least 168 hours — seven days — the tier is `T2_DEPOSIT_HALF`: the deposit portion refunds at half and the balance portion in full. With at least 72 hours — three days — the tier is `T3_BALANCE_ONLY`: the deposit portion refunds nothing and the balance portion refunds in full. Below 72 hours the tier is `T4_HALF_ALL`, refunding half of each portion. The rounding order is pinned: each portion is multiplied by its tier percentage and rounded half up to integer cents first, and only then are the two rounded components summed. For `T1_FULL` alone, an administration fee of 25,000 cents (250 dollars) is then subtracted from the sum. Finally the result is floored at zero, and that frozen figure is stored as `refund_due_cents` with the tier recorded in `cancellation_tier`.

Settlement and reversal close the loop. **Settling** a cancellation requires the show to be `CANCELLED` with `cancellation_status` `FILED` (else `ERR_INVALID_STATE`); it posts the frozen refund by setting `refunded_total_cents` to `refund_due_cents`, moves `cancellation_status` to `SETTLED`, and moves `payment_status` to `REFUNDED` from whichever of `DEPOSIT_DUE`, `DEPOSIT_PAID`, or `PAID_IN_FULL` it held. **Voiding** a settled cancellation requires `cancellation_status` `SETTLED` on a `CANCELLED` show (else `ERR_INVALID_STATE`); it reverses the refund by zeroing `refunded_total_cents`, moves `cancellation_status` to `VOIDED`, and recomputes `payment_status` from `paid_total_cents`: zero paid means `DEPOSIT_DUE`, an amount equal to `deposit_cents` means `DEPOSIT_PAID`, and an amount equal to `contract_value_cents` means `PAID_IN_FULL`. A paid total falling strictly between these anchors — unreachable through the payment endpoints, which accept only exact component amounts — recomputes conservatively: below `deposit_cents` yields `DEPOSIT_DUE`, below `contract_value_cents` yields `DEPOSIT_PAID`, and anything at or above `contract_value_cents` yields `PAID_IN_FULL`. The show itself remains `CANCELLED` — voiding is a financial reversal, not a resurrection.

### 3.8. Post-Flight Reconciliation and Incident Management

After an `EXECUTED` show, the fleet uploads **FlightLog** telemetry. A log names the `show_event_id` and `drone_id` and carries `battery_consumed_pct` (0 to 100 inclusive), `max_altitude_reached_ft` (zero or greater), and `max_deviation_m` (zero or greater) — the largest lateral deviation from the planned path. The log is accepted only when the show is `EXECUTED` and the named drone holds a `FLOWN` slot for that show; otherwise `ERR_INVALID_STATE`.

Receipt of a flight log triggers a reconciliation whose order of operations is pinned. First, the drone's slot for the show moves from `FLOWN` to `RECONCILED`. Second, the drone itself returns from `RESERVED` to `AVAILABLE` — but only when it holds no remaining `ASSIGNED` slot on any show; a drone still reserved elsewhere stays `RESERVED`. Third, the drone's `charge_pct` is reduced by the log's `battery_consumed_pct`, floored at zero. Fourth, the drone's `battery_cycle_count` increments by one. Fifth, if the cycle count has reached 200, the drone is sent to `IN_MAINTENANCE` automatically — unless it is already `RETIRED`, in which case it remains `RETIRED`. Finally, a `max_deviation_m` strictly above 5.0 meters marks the log's `flag_status` as `FLAGGED` — it otherwise remains `RECEIVED` — and auto-files an incident report: `severity` `MINOR`, `source` `AUTO_DEVIATION`, status `FILED`, linked to this drone and show, with `filed_by_user_id` recorded as `SYSTEM` and a `description` of the form `Auto-filed: max deviation {max_deviation_m}m exceeded threshold` carrying the log's deviation value. Manually filed reports carry the default `source` `MANUAL`. Flight logs can be listed and filtered by `show_event_id`, `drone_id`, or `flag_status`.

Manual **IncidentReport** filing is a `SafetyOfficer` act against an `EXECUTED` show (else `ERR_INVALID_STATE`), naming a `severity` of `MINOR`, `MAJOR`, or `CRITICAL` and a free-text `description`. A `MAJOR` report must name the specific airframe via `drone_id` — omitting it is rejected with `ERR_DRONE_REQUIRED` — while `drone_id` is optional for `CRITICAL` and `MINOR` reports. The filer is recorded as `filed_by_user_id`, and the report opens in `FILED` status. Opening an investigation moves a `FILED` report to `UNDER_INVESTIGATION`.

Closing an investigation takes an `outcome` of `CONFIRMED` or `REJECTED`, requires the report to be `UNDER_INVESTIGATION` (else `ERR_INVALID_STATE`), and is segregated per §2.8 — the closer must differ from `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Either way the closer is recorded as `closed_by_user_id`. A `REJECTED` outcome moves the report to `CLOSED_REJECTED` with no fleet effects. A `CONFIRMED` outcome moves it to `CLOSED_CONFIRMED` and discharges the severity cascades. For `CRITICAL`, every drone that has a flight log for the show is grounded, and each such grounding voids that drone's `ASSIGNED` launch-grid slots wherever it holds them — decrementing those shows' `assigned_count` and dropping any `READY` show among them to `AUTHORIZED` with posture recomputed — while every `APPROVED` authorization serving the show is revoked, each itself cascading any show pinning it back to `PLANNING` per §3.3. For `MAJOR`, the report's `drone_id` is grounded with the same slot-void cascade. These cascades are the intended serialization point between post-flight findings and the readiness of other productions sharing the fleet.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, actions, and both test-driving capabilities — as well as all single-resource fetches, computed reads, and list retrievals, return `200 OK`. The request and response details of each endpoint are specified by the workflows in §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/sites` | Create a venue site | ProductionPlanner |
| GET | `/api/sites/{siteId}` | Get a site | All roles |
| GET | `/api/sites` | List sites (paginated) | All roles |
| POST | `/api/show-events` | Create a show (pricing computed; PLANNING / DEPOSIT_DUE) | ProductionPlanner |
| GET | `/api/show-events/{showEventId}` | Get a show with computed posture, pins, and counters | All roles |
| GET | `/api/show-events` | List shows (filterable by `site_id`, `lifecycle_status`; paginated) | All roles |
| POST | `/api/show-events/{showEventId}/authorize` | DESIGN_LOCKED to AUTHORIZED; pins an APPROVED authorization | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/certify-go` | READY to GO_CERTIFIED using a fresh CERTIFIED GO evaluation | SafetyOfficer |
| POST | `/api/show-events/{showEventId}/execute` | GO_CERTIFIED to EXECUTED; flips grid slots to FLOWN | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/postpone` | AUTHORIZED, READY, or GO_CERTIFIED to POSTPONED | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/reschedule` | POSTPONED to PLANNING with a new window | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/activate-backup` | POSTPONED to PLANNING inside the backup window, consuming it | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/cancel` | Non-terminal lifecycle to CANCELLED; computes tier and refund; voids grid | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/settle-cancellation` | Posts the frozen refund; FILED to SETTLED | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/void-cancellation` | Reverses a settled refund; SETTLED to VOIDED | ProductionPlanner |
| POST | `/api/show-events/{showEventId}/record-payment` | Records the DEPOSIT then the BALANCE; exact amounts only | ProductionPlanner |
| GET | `/api/show-events/{showEventId}/readiness` | Computed posture with per-gate breakdown g1 through g6 | All roles |
| GET | `/api/show-events/{showEventId}/perimeter-assessment` | Computed required crowd radius and containment (`variant` PLANNED or AS_FLOWN) | All roles |
| POST | `/api/airspace-authorizations` | File an authorization/waiver application (DRAFT) | ProductionPlanner |
| GET | `/api/airspace-authorizations/{authorizationId}` | Get an authorization | All roles |
| GET | `/api/airspace-authorizations` | List authorizations (filterable by `show_event_id`, `status`; paginated) | All roles |
| POST | `/api/airspace-authorizations/{authorizationId}/submit` | DRAFT to UNDER_REVIEW; ceiling, coverage, and overlap validated | ProductionPlanner |
| POST | `/api/airspace-authorizations/{authorizationId}/request-info` | UNDER_REVIEW to INFO_REQUESTED | AuthorityOfficer |
| POST | `/api/airspace-authorizations/{authorizationId}/resubmit` | INFO_REQUESTED back to UNDER_REVIEW | ProductionPlanner |
| POST | `/api/airspace-authorizations/{authorizationId}/decide` | UNDER_REVIEW to APPROVED or DENIED; approval re-validates | AuthorityOfficer |
| POST | `/api/airspace-authorizations/{authorizationId}/revise` | DENIED back to DRAFT with optional amended window/ceiling | ProductionPlanner |
| POST | `/api/airspace-authorizations/{authorizationId}/revoke` | APPROVED to REVOKED; downgrades shows pinning it | AuthorityOfficer |
| POST | `/api/airspace-authorizations/{authorizationId}/withdraw` | DRAFT to WITHDRAWN | ProductionPlanner |
| POST | `/api/show-designs` | Create a design revision (DRAFT); per-show version number assigned | ProductionPlanner |
| GET | `/api/show-designs/{designId}` | Get a design | All roles |
| GET | `/api/show-designs` | List designs (filterable by `show_event_id`, `status`; paginated) | All roles |
| POST | `/api/show-designs/{designId}/revise` | SIMULATED back to DRAFT | ProductionPlanner |
| POST | `/api/show-designs/{designId}/lock` | SIMULATED to LOCKED with show OCC; supersedes the prior lock and re-pins | ProductionPlanner |
| POST | `/api/simulation-runs` | Record a simulation run; verdict computed; first run moves design to SIMULATED | ProductionPlanner |
| GET | `/api/simulation-runs/{simulationRunId}` | Get a simulation run | All roles |
| GET | `/api/simulation-runs` | List simulation runs (filterable by `show_design_id`, `verdict`; paginated) | All roles |
| POST | `/api/safety-configurations` | Create a geofence/failsafe configuration (DRAFT) with show OCC; supersedes the current one | ProductionPlanner |
| GET | `/api/safety-configurations/{configId}` | Get a safety configuration | All roles |
| GET | `/api/safety-configurations` | List safety configurations (filterable by `show_event_id`, `status`; paginated) | All roles |
| POST | `/api/safety-configurations/{configId}/approve` | DRAFT to APPROVED; geofence and ceiling gates; segregated from creator | SafetyOfficer |
| POST | `/api/drones` | Register a drone (AVAILABLE) | FleetManager |
| GET | `/api/drones/{droneId}` | Get a drone | All roles |
| GET | `/api/drones` | List drones (filterable by `status`; paginated) | All roles |
| POST | `/api/drones/{droneId}/ground` | AVAILABLE, RESERVED, or IN_MAINTENANCE to GROUNDED; voids its slots | SafetyOfficer |
| POST | `/api/drones/{droneId}/release` | GROUNDED or IN_MAINTENANCE back to AVAILABLE | SafetyOfficer |
| POST | `/api/drones/{droneId}/maintain` | AVAILABLE to IN_MAINTENANCE | FleetManager |
| POST | `/api/drones/{droneId}/retire` | AVAILABLE, IN_MAINTENANCE, or GROUNDED to RETIRED | FleetManager |
| POST | `/api/charge-bays` | Register a charging bay at a site | FleetManager |
| GET | `/api/charge-bays/{chargeBayId}` | Get a charge bay | All roles |
| GET | `/api/charge-bays` | List charge bays (filterable by `site_id`; paginated) | All roles |
| POST | `/api/charge-sessions` | Start a charging session; drone to CHARGING | FleetManager |
| GET | `/api/charge-sessions/{chargeSessionId}` | Get a charge session | All roles |
| GET | `/api/charge-sessions` | List charge sessions (filterable by `drone_id`, `charge_bay_id`, `status`; paginated) | All roles |
| POST | `/api/charge-sessions/{chargeSessionId}/complete` | ACTIVE to COMPLETED; drone charged and released | FleetManager |
| POST | `/api/charge-sessions/{chargeSessionId}/interrupt` | ACTIVE to INTERRUPTED; partial charge kept | FleetManager |
| POST | `/api/launch-grid-assignments` | Assign a drone to a grid slot; completing the grid advances the show to READY | FleetManager |
| GET | `/api/launch-grid-assignments/{assignmentId}` | Get an assignment | All roles |
| GET | `/api/launch-grid-assignments` | List assignments (filterable by `show_event_id`, `drone_id`, `status`; paginated) | All roles |
| POST | `/api/launch-grid-assignments/{assignmentId}/void` | ASSIGNED to VOIDED; releases the drone; downgrades a READY show | FleetManager |
| POST | `/api/weather-readings` | Record a weather observation (immutable) | SafetyOfficer |
| GET | `/api/weather-readings/{weatherReadingId}` | Get a weather reading | All roles |
| GET | `/api/weather-readings` | List weather readings (filterable by `site_id`; paginated) | All roles |
| POST | `/api/go-no-go-evaluations` | Compute a go/no-go evaluation from the latest weather in the lookback | SafetyOfficer |
| GET | `/api/go-no-go-evaluations/{evaluationId}` | Get an evaluation | All roles |
| GET | `/api/go-no-go-evaluations` | List evaluations (filterable by `show_event_id`, `verdict`, `status`; paginated) | All roles |
| POST | `/api/go-no-go-evaluations/{evaluationId}/certify` | PROVISIONAL to CERTIFIED; segregated from the pinned config's approver | SafetyOfficer |
| POST | `/api/incident-reports` | File an incident against an EXECUTED show; MAJOR requires a drone | SafetyOfficer |
| GET | `/api/incident-reports/{incidentId}` | Get an incident report | All roles |
| GET | `/api/incident-reports` | List incident reports (filterable by `show_event_id`, `drone_id`, `severity`, `status`; paginated) | All roles |
| POST | `/api/incident-reports/{incidentId}/investigate` | FILED to UNDER_INVESTIGATION | SafetyOfficer |
| POST | `/api/incident-reports/{incidentId}/close` | UNDER_INVESTIGATION to CLOSED_CONFIRMED or CLOSED_REJECTED; severity cascades | SafetyOfficer |
| POST | `/api/flight-logs` | Upload a post-flight log; reconciles battery and cycles; may auto-flag and auto-file | FleetManager |
| GET | `/api/flight-logs/{flightLogId}` | Get a flight log | All roles |
| GET | `/api/flight-logs` | List flight logs (filterable by `show_event_id`, `drone_id`, `flag_status`; paginated) | All roles |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | OpsAdmin |
| POST | `/api/_ops/run_sweep` | Expire APPROVED authorizations past their window end, with cascade | OpsAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every business-rule error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3. Three further identifiers exist outside the business catalogue: requests to undefined routes are rejected with `ERR_NOT_FOUND` (404), requests using an unsupported method with `ERR_METHOD_NOT_ALLOWED` (405), and unexpected server failures with `ERR_INTERNAL` (500); all three use the standard error envelope.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_SHOW_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGN_NOT_FOUND` | 404 Not Found |
| `ERR_SIMULATION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_SAFETY_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_DRONE_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WEATHER_READING_NOT_FOUND` | 404 Not Found |
| `ERR_EVALUATION_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DRONE_NOT_FLYABLE` | 409 Conflict |
| `ERR_CHARGE_BELOW_MINIMUM` | 409 Conflict |
| `ERR_ALTITUDE_CEILING_EXCEEDS_SITE` | 409 Conflict |
| `ERR_GEOFENCE_BELOW_REQUIRED` | 409 Conflict |
| `ERR_CEILING_BELOW_DESIGN` | 409 Conflict |
| `ERR_PERIMETER_INSUFFICIENT` | 409 Conflict |
| `ERR_AUTHORIZATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHOW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DRONE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_READING_IN_FUTURE` | 409 Conflict |
| `ERR_EVALUATION_STALE` | 409 Conflict |
| `ERR_BACKUP_WINDOW_UNAVAILABLE` | 409 Conflict |
| `ERR_SHOW_WINDOW_IN_PAST` | 409 Conflict |
| `ERR_OUTSIDE_SHOW_WINDOW` | 409 Conflict |
| `ERR_GRID_SLOT_OCCUPIED` | 409 Conflict |
| `ERR_DRONE_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_GRID_OUT_OF_BOUNDS` | 409 Conflict |
| `ERR_BAY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CHARGE_NOT_NEEDED` | 409 Conflict |
| `ERR_ASSIGNMENT_EXCEEDS_DESIGN` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_AUTHORIZATION_WINDOW_INSUFFICIENT` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_APPROVED` | 409 Conflict |
| `ERR_SIMULATION_NOT_PASSING` | 409 Conflict |
| `ERR_EVALUATION_NOT_CERTIFIED` | 409 Conflict |
| `ERR_NO_GO_IN_EFFECT` | 409 Conflict |
| `ERR_SAFETY_CONFIG_NOT_APPROVED` | 409 Conflict |
| `ERR_DRONE_REQUIRED` | 409 Conflict |
| `ERR_INVALID_CHARGE_TARGET` | 409 Conflict |
| `ERR_NO_FLIGHT_DATA` | 409 Conflict |
| `ERR_DESIGN_NOT_LOCKED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_SHOW_NOT_PAID_IN_FULL` | 409 Conflict |
