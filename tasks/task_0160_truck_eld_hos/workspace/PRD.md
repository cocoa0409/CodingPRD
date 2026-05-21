# Truck ELD HOS API — Product Requirements Document

## 1. Introduction

Commercial motor carriers in the United States must record every change in a driver's duty status on a federally certified Electronic Logging Device (ELD) and must produce the resulting Records of Duty Status (RODS) to the Federal Motor Carrier Safety Administration (FMCSA) on demand. The rules layered on top of that recording obligation — the eleven-hour driving limit, the fourteen-hour on-duty window, the seventy- or sixty-hour rolling cycle, the ten-hour reset, the thirty-four-hour restart, the sleeper-berth split, the personal-conveyance carve-out, and the adverse-conditions exemption — are deceptively easy to state and notoriously difficult to enforce in software. A single duty-event write can simultaneously close one limit, open another, trigger a violation, propagate an exemption from `ACTIVE` to `CONSUMED`, and reshape the driver's projected hours of service.

This document specifies an ELD-and-HOS backend that registers carriers, vehicles, and devices; binds a driver's identity to a specific vehicle through its installed device; ingests duty-status events in strict per-driver chronological order; computes the driver's three legally binding limits on every write; detects, records, and surfaces violations for the carrier safety officer; and produces tamper-evident daily logs that drivers certify and FMCSA auditors review. The system also supports the regulatory escape hatches — sleeper-berth pairs, personal conveyance, yard moves, and the two-hour adverse-conditions extension — and the driver's right to correct an erroneous entry within the eight-day FMCSA edit window. Because much of the regulation is time-gated (a log only becomes certifiable after its calendar date has passed, an exemption expires at home-terminal midnight, an edit window closes eight days after the event), the system exposes a test-driving clock endpoint that allows controlled time progression.

The audience for this document is the engineering team building the service. Where this PRD describes a regulation, the regulation is normative; where it describes a calculation or a side effect, that calculation or side effect is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the calling user: `X-User-ID` (the user's unique identifier) and `X-User-Role` (the role the user is acting under). If either header is missing or unparsable, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401). If both headers are present but the role does not appear on the endpoint's allow-list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognises exactly four roles, with the following exact spellings: `Driver`, `CarrierSafetyOfficer`, `FMCSAAuditor`, and `PlatformAdmin`.

When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity; every operation a driver performs is scoped to themselves, and ownership checks on any resource that references a `Driver` (a `DutyEvent`, a `DailyLog`, a `Violation`, an `AdverseConditionsExemption`) compare the resource's `driver_id` foreign-key field to `X-User-ID`. When `X-User-Role` is `CarrierSafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `Carrier.safety_contact_user_id` during carrier registration) but does not compare it to any entity's `id`. When `X-User-Role` is `FMCSAAuditor`, `X-User-ID` is likewise an opaque federal-auditor identifier with no entity backing. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque platform-operator identifier, again with no entity backing.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. Values outside these ranges yield `ERR_INVALID_INPUT` (HTTP 400). List endpoints sort the result set by `created_at` in ascending order before applying `offset` and `limit`. The response envelope's `meta` block exposes the echoed `limit` and `offset`, the unpaged `total_count`, and the boolean `has_more` flag indicating whether further pages exist beyond the current window.

### 2.4. Common Resource Properties

Every resource of types `Driver`, `Carrier`, `Vehicle`, `ELDDevice`, `DailyLog`, `Violation`, and `AdverseConditionsExemption` carries four system-managed properties in addition to its domain attributes: `id` (a server-minted UUID with no type prefix), `created_at` (the ISO 8601 UTC instant of creation, with three fractional digits), `updated_at` (the ISO 8601 UTC instant of the most recent mutation, with three fractional digits), and `version` (an integer that begins at 1 on creation and increments by 1 on every server-side mutation of the resource). The `DutyEvent` resource is an immutable audit record and carries only `id` and `created_at`; it has no `updated_at` and no `version` — corrections to a duty event are performed by writing a replacement event rather than by mutating the existing record.

Identifiers in URL paths are validated left to right. A path of the form `/drivers/{driver_id}/daily-logs/{log_id}` first resolves the `driver_id` against the `Driver` collection; if the driver does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any attempt is made to resolve the `log_id`. The same left-to-right rule applies to every nested path in the API. The same `ERR_NOT_FOUND` code surfaces when any other path or body identifier — `carrier_id`, `device_id`, `vehicle_id`, `event_id`, `violation_id`, an `eld_device_id` referenced from a `Vehicle` registration, or an `adverse_conditions_exemption_id` referenced from a duty-event write — resolves to no row.

### 2.5. Optimistic Concurrency Control

Mutating requests on versioned resources may include a `version` field in the request body. When the client supplies `version`, the server compares it to the stored `version`; on mismatch the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the client omits `version`, the server performs no concurrency check and the write proceeds. Every successful mutation increments the stored `version` by 1 and refreshes `updated_at`.

### 2.6. Precision, Rounding, and Time

All HOS minute computations — driving minutes, on-duty minutes, window-remaining minutes, cycle-remaining minutes, exemption minutes, and the legs of a sleeper-berth pair — are expressed as integer minutes; any fractional minute that arises in intermediate arithmetic is truncated toward zero. Geographic coordinates `latitude` and `longitude` are decimal degrees and, when included in the canonical projection used to derive a `DailyLog`'s tamper-evident digest, are rounded half-up to six decimal places. The `odometer_miles` reading is a numeric value reported by the ELD, treated as a vehicle-monotonic non-decreasing counter (see §3.3). All timestamps stored and returned by the API are ISO 8601 UTC with three fractional digits.

### 2.7. Driver-Identity Binding and ELD Pairing

A driver may interact with the road-side rules — appending DRIVING, ON_DUTY_NOT_DRIVING, YARD_MOVES, or PERSONAL_CONVEYANCE events — only while bound to a vehicle whose ELD device is certified for FMCSA. The `Driver`'s `bound_vehicle_id` foreign-key field is null while the driver is unbound and is populated atomically with the `Vehicle`'s `current_driver_id` field at bind time. At the same instant, the driver's `bound_eld_device_id` is set to mirror the bound vehicle's `eld_device_id`. Unbinding clears all three fields atomically. The exact bind preconditions (carrier alignment, device certification, vehicle availability, duty-status gating) and their associated error codes are specified in §3.2.

### 2.8. Tamper-Evident Daily Logs

Each `DailyLog` carries an `integrity_hash` field that is recomputed as a side effect of every transition that mutates the log — appending a new event on that `log_date`, editing an event whose `daily_log_id` points at the log, certifying the log, or recertifying it. The hash is the lowercase hexadecimal SHA-256 (64 characters) of a deterministic canonical JSON projection of the log's `ACTIVE` duty events; the exact projection is specified in §3.7. A `SUPERSEDED` duty event never contributes to the projection. Once a log is certified, its `status` is `CERTIFIED`; subsequent driver edits to events whose `daily_log_id` points at that log transition the log to `RECERTIFIED`, increment `certification_count` by 1, refresh `certified_at`, and recompute `integrity_hash` against the new `ACTIVE` set.

### 2.9. Hierarchical Consistency, Cascades, and `version`

A single accepted duty-event write may mutate the parent `Driver` (its `duty_status`, possibly its `last_34_hour_restart_completed_at`), the affected `DailyLog` (its `total_driving_minutes`, `total_on_duty_minutes`, `integrity_hash`), one or more `AdverseConditionsExemption` rows (`ACTIVE` to `CONSUMED`), and may create a fresh `Violation` row. Every entity that is mutated has its `updated_at` refreshed and its `version` incremented by 1 in the same transaction. Cascades stop at the carrier-notification layer: when a `Violation` is created as a downstream side effect of an over-limit duty event, the notification record on the owning `Carrier` is the third and final hop of the cascade chain. A driver edit that produces a `RECERTIFIED` log re-evaluates open violations attached to the affected window and may flip a `Violation` from `OPEN` or `ACKNOWLEDGED` to `RESOLVED` when the recomputed minutes-remaining at the original triggering event time is greater than or equal to zero.

### 2.10. Validation Priority

When multiple validations could apply to the same request, the server evaluates them in a strictly ordered sequence and returns the first failure rather than aggregating. Authentication (the presence of `X-User-ID` and `X-User-Role`) is evaluated first, then authorisation against the endpoint's allow-list, then existence of every resource referenced in the path (left to right) and body, then the workflow-specific state and business checks listed in §3, and finally the generic schema/pagination and optimistic-concurrency checks. Concretely: for a duty-event write, the `Driver`-must-be-bound check precedes the log-already-certified check, which precedes the strict per-driver event-time monotonicity check, which precedes the annotation-required check, which precedes the insufficient-rest check, which precedes the eleven-hour, fourteen-hour, and cycle checks in that order, which precede the vehicle-mismatch and exemption-validity checks, which precede the odometer-monotonicity check, which precedes generic schema validation, which precedes the optimistic-concurrency check. The implementer must surface the earliest applicable failure code; later failures are not reported alongside.

### 2.11. Adverse-Conditions Extension Principle

The FMCSA two-hour adverse-conditions exemption may extend both the eleven-hour driving limit (to thirteen hours) and the fourteen-hour on-duty window (to sixteen hours) but never the seventy-hour or sixty-hour cycle. An exemption is consumed when its `id` is first attached, via the request body field `adverse_conditions_exemption_id`, to a DRIVING event whose `event_time` exceeds the driver's unextended driving or on-duty limit; it expires either at home-terminal midnight of its `applies_to_log_date` or when the driver enters an unbroken ten-hour OFF_DUTY-plus-SLEEPER_BERTH rest, whichever comes first. The mechanics of declaration, attachment, consumption, and expiry are spelled out in §3.6.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Carrier, Its Vehicles, and Its Devices

The lifecycle of an ELD record begins at the platform-administrator's console. A `PlatformAdmin` registers a motor carrier by supplying a `dot_number` (digits only, five to eight characters long, unique across the system), a `legal_name`, and a `safety_contact_user_id`; the system mints the carrier and returns it. A `PlatformAdmin` also registers each ELD device by supplying a `serial_number` (six to thirty-two characters, unique across devices), a `firmware_version` (a semver string such as "3.4.1"), and an optional `certified_for_fmcsa` flag that defaults to true; uncertified devices may be recorded for inventory purposes but cannot bind to a driver — see §3.2 for the certification check.

A `CarrierSafetyOfficer` then pairs the carrier's vehicles with their installed devices by registering each `Vehicle` with a `vin` (a Vehicle Identification Number that is exactly seventeen uppercase alphanumeric characters excluding the letters I, O, and Q, unique across the fleet), the owning `carrier_id`, and the `eld_device_id` of the device installed in that vehicle; a device may pair with at most one vehicle. The same officer enrolls drivers by supplying a `cdl_number` (unique across drivers, between six and twenty uppercase alphanumeric characters), a `full_name`, the driver's `carrier_id`, an optional `cycle_type` that defaults to `SEVENTY_HOUR_EIGHT_DAY` (the alternative being `SIXTY_HOUR_SEVEN_DAY`), and an optional `home_terminal_timezone` IANA name that defaults to `America/New_York`. A newly minted `Driver` has `duty_status` of `OFF_DUTY`, a null `bound_vehicle_id`, a null `bound_eld_device_id`, a null `last_34_hour_restart_completed_at`, an `odometer_miles` baseline of zero on each vehicle she will later board, and a `current_driver_id` of null on every vehicle her carrier owns.

### 3.2. Identity Binding to the ELD

Before a driver can record on-vehicle activity, she binds her identity to a specific vehicle through that vehicle's installed device. Binding, which transitions the `Driver`'s binding state from `UNBOUND` to `BOUND`, requires four conditions to hold simultaneously: the driver's `duty_status` is `OFF_DUTY`, the vehicle's `current_driver_id` is null, the vehicle's `carrier_id` equals the driver's `carrier_id`, and the device installed in that vehicle has `certified_for_fmcsa` equal to true. The bind request body carries the target `vehicle_id`. On success, the server atomically sets the driver's `bound_vehicle_id` to the supplied `vehicle_id`, sets the driver's `bound_eld_device_id` to that vehicle's `eld_device_id`, and sets the vehicle's `current_driver_id` to the driver's id; the response carries the updated `Driver`.

A bind attempted while the driver is not `OFF_DUTY` is rejected with `ERR_INVALID_DUTY_STATUS_FOR_BIND`; a bind whose vehicle is already paired to another driver is rejected with `ERR_VEHICLE_ALREADY_BOUND`; a bind by a driver already bound to a different vehicle is rejected with `ERR_DRIVER_ALREADY_BOUND`; a bind whose vehicle and driver belong to different carriers is rejected with `ERR_CROSS_CARRIER_BIND`; and a bind whose device is not FMCSA-certified is rejected with `ERR_ELD_NOT_CERTIFIED`. Two `CarrierSafetyOfficer`-orchestrated bind attempts that race for the same driver against two different vehicles serialise first-writer-wins on `Driver.bound_vehicle_id`: exactly one bind succeeds, and the loser receives `ERR_DRIVER_ALREADY_BOUND`. Two drivers racing for the same vehicle serialise first-writer-wins on `Vehicle.current_driver_id`: the loser receives `ERR_VEHICLE_ALREADY_BOUND`.

The reverse transition, from `BOUND` to `UNBOUND`, requires only that the driver's current `duty_status` be either `OFF_DUTY` or `SLEEPER_BERTH`; if she is in any other status, the unbind is rejected with `ERR_INVALID_DUTY_STATUS_FOR_BIND`. On a successful unbind the server atomically clears `Driver.bound_vehicle_id`, clears `Driver.bound_eld_device_id`, and clears `Vehicle.current_driver_id`.

### 3.3. Appending Duty Events

The duty-event append is the load-bearing operation of the system. A driver supplies a `new_status` from the enumerated set `OFF_DUTY`, `SLEEPER_BERTH`, `DRIVING`, `ON_DUTY_NOT_DRIVING`, `PERSONAL_CONVEYANCE`, or `YARD_MOVES`; an `event_time` that is a UTC instant strictly greater than the latest accepted `DutyEvent.event_time` for this driver; a geographic `latitude` in the inclusive range -90 to 90 and `longitude` in the inclusive range -180 to 180; and optionally a `vehicle_id`, an `odometer_miles` reading, an `annotation`, and an `adverse_conditions_exemption_id`. On acceptance, the server appends an immutable `DutyEvent` with `edit_state` of `ACTIVE` and a null `superseded_by_event_id`, sets its `daily_log_id` to the `DailyLog` that owns the calendar date computed from `event_time` in the driver's `home_terminal_timezone` (creating the log on demand if it does not yet exist), updates `Driver.duty_status` to `new_status`, recomputes the affected log's `total_driving_minutes`, `total_on_duty_minutes`, and `integrity_hash`, and may produce additional cascading effects described below.

A duty event whose `new_status` is `DRIVING`, `ON_DUTY_NOT_DRIVING`, `YARD_MOVES`, or `PERSONAL_CONVEYANCE` requires `Driver.bound_vehicle_id` to be non-null; otherwise the request is rejected with `ERR_DRIVER_NOT_BOUND`. A duty event whose `event_time` falls on a calendar date whose `DailyLog.status` is `CERTIFIED` or `RECERTIFIED` cannot be appended directly and is rejected with `ERR_LOG_ALREADY_CERTIFIED`; the driver must instead use the edit workflow described in §3.5. An `event_time` that is not strictly greater than the latest accepted event for this driver is rejected with `ERR_DUTY_EVENT_OUT_OF_ORDER`; two simultaneous duty-event writes for the same driver, both with `event_time` later than the latest stored event, serialise first-writer-wins on the pair (driver, `event_time`) — exactly one is appended, and the writer that commits second observes a stored `event_time` no longer strictly less than its own `event_time` and is rejected with `ERR_DUTY_EVENT_OUT_OF_ORDER`.

`PERSONAL_CONVEYANCE` and `YARD_MOVES` events require an `annotation` whose length is at least ten characters; a shorter or absent annotation is rejected with `ERR_ANNOTATION_REQUIRED`. When `new_status` is `DRIVING`, `ON_DUTY_NOT_DRIVING`, `YARD_MOVES`, or `PERSONAL_CONVEYANCE`, the request must supply a `vehicle_id` and that `vehicle_id` must equal the driver's currently bound vehicle; a mismatch (or a missing `vehicle_id` for an on-vehicle status) is rejected with `ERR_VEHICLE_MISMATCH`. The `odometer_miles` of any accepted event must be greater than or equal to the latest accepted `odometer_miles` for that same vehicle — odometers do not run backward — and a smaller reading is rejected with `ERR_ODOMETER_DECREASED`. If the event carries an `adverse_conditions_exemption_id`, that id must reference an `AdverseConditionsExemption` whose `status` is `ACTIVE`, whose `driver_id` matches the acting driver, and whose `applies_to_log_date` equals the log date computed from `event_time` in the driver's home-terminal timezone; otherwise the request is rejected with `ERR_EXEMPTION_NOT_ACTIVE`.

Each accepted duty event updates the parent `Driver`'s `duty_status` to match `new_status`. Transitions out of `DRIVING` close the open driving interval on the affected `DailyLog`. The transition from `OFF_DUTY` or `SLEEPER_BERTH` to a state that breaks the rest period is the moment at which a continuous OFF_DUTY-plus-SLEEPER_BERTH window stops accruing; if that accumulated continuous window had reached at least 34 hours in length when broken, the server sets `Driver.last_34_hour_restart_completed_at` to the `event_time` of the breaking transition (more precisely, to the boundary at which the rest window closes). This is the first of a three-deep cascade chain whose later hops are reflected in cycle computation (depth 2) and in the violation/notification record (depth 3) described below. Transitions into `PERSONAL_CONVEYANCE` accrue time to neither driving nor on-duty totals, per 49 CFR 395.8; transitions into `YARD_MOVES` accrue time to on-duty totals but not to driving totals; transitions into `DRIVING` accrue time to both.

The state machine on `Driver.duty_status` defines which transitions are admissible. Permitted moves include `OFF_DUTY → DRIVING`, `OFF_DUTY → SLEEPER_BERTH`, `OFF_DUTY → ON_DUTY_NOT_DRIVING`, `OFF_DUTY → PERSONAL_CONVEYANCE`, `DRIVING → ON_DUTY_NOT_DRIVING`, `DRIVING → OFF_DUTY`, `DRIVING → SLEEPER_BERTH`, `SLEEPER_BERTH → DRIVING`, `SLEEPER_BERTH → OFF_DUTY`, `ON_DUTY_NOT_DRIVING → DRIVING`, `ON_DUTY_NOT_DRIVING → OFF_DUTY`, `ON_DUTY_NOT_DRIVING → YARD_MOVES`, `YARD_MOVES → ON_DUTY_NOT_DRIVING`, `PERSONAL_CONVEYANCE → OFF_DUTY`, and `PERSONAL_CONVEYANCE → DRIVING`. Beyond bind, annotation, vehicle, and ordering checks, each on-duty transition is gated by three legal limits explained in §3.4.

### 3.4. The Eleven-Hour, Fourteen-Hour, and Cycle Limits

For any duty-event write whose `new_status` is `DRIVING`, the server computes the driver's available driving hours and rejects the request when zero or fewer minutes remain. The computation walks back through the driver's history of `ACTIVE` duty events to find the most recent qualifying break — the latest instant such that the continuous OFF_DUTY-plus-SLEEPER_BERTH run ending at that instant totals at least 600 minutes (ten hours). `PERSONAL_CONVEYANCE` minutes do not count toward this break, and `YARD_MOVES` minutes do not count either. The driving minutes accumulated since that break are then summed across `ACTIVE` events whose `new_status` is `DRIVING` and whose interval intersects the half-open range from the qualifying-break end up to (but not including) `event_time`; `PERSONAL_CONVEYANCE` and `YARD_MOVES` intervals contribute zero driving minutes. The driving cap is 660 minutes (eleven hours) by default; if and only if the duty event is being written with an `adverse_conditions_exemption_id` referencing an `ACTIVE` exemption attached to the current 14-hour window, the cap is extended by an additional 120 minutes (two hours), to 780 minutes. The available driving minutes remaining is the cap minus the accumulated driving minutes since the break; if the result is zero or fewer minutes when the event is being written, the request is rejected with `ERR_ELEVEN_HOUR_LIMIT_EXCEEDED`. All values are expressed as integer minutes and any fractional minute is truncated toward zero.

For any duty-event write whose `new_status` is `DRIVING`, `ON_DUTY_NOT_DRIVING`, or `YARD_MOVES`, the server also computes the driver's available 14-hour window. The window starts at the `event_time` of the first `ACTIVE` event of one of those three statuses written after the most recent qualifying break; the elapsed wall-clock minutes from that window start to the new `event_time` is compared to a base cap of 840 minutes (fourteen hours), extended to 960 minutes (sixteen hours) if and only if an `ACTIVE` `AdverseConditionsExemption` is attached to the same window. Critically, the 14-hour window measures wall-clock elapsed time and not on-duty accumulated time: OFF_DUTY, SLEEPER_BERTH, and PERSONAL_CONVEYANCE intervals all consume the window even though they do not contribute to on-duty totals. If the wall-clock elapsed minutes equal or exceed the cap, the request is rejected with `ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED`.

For any duty-event write whose `new_status` is `DRIVING`, `ON_DUTY_NOT_DRIVING`, or `YARD_MOVES`, the server further checks the driver's rolling cycle balance. If the driver's `cycle_type` is `SEVENTY_HOUR_EIGHT_DAY`, the cycle cap is 4200 minutes (seventy hours) and the rolling window spans the eight days ending at `event_time`; if `cycle_type` is `SIXTY_HOUR_SEVEN_DAY`, the cap is 3600 minutes (sixty hours) and the window spans seven days. When the driver's `last_34_hour_restart_completed_at` is non-null and falls strictly inside the rolling window, the effective window start is bumped forward to that instant — on-duty minutes earned before the restart are excluded. On-duty minutes within the effective window are summed across `ACTIVE` events whose `new_status` is `DRIVING`, `ON_DUTY_NOT_DRIVING`, or `YARD_MOVES`; OFF_DUTY, SLEEPER_BERTH, and PERSONAL_CONVEYANCE minutes contribute zero. The cycle minutes remaining is the cap minus the in-window on-duty minutes; if zero or fewer minutes remain, the request is rejected with `ERR_CYCLE_LIMIT_EXCEEDED`. The minimum reset that qualifies as a 34-hour restart is 2040 minutes of unbroken OFF_DUTY-plus-SLEEPER_BERTH; the adverse-conditions extension never extends the cycle cap. The driver's projected `last_34_hour_restart_completed_at` is recomputed as a side effect of any duty-event write whose transition closes a continuous rest window of at least 34 hours, as already described in §3.3.

A driver who completes a duty event such that — using the appropriate variant (`UNEXTENDED` when no `ACTIVE` exemption attaches to the relevant window, `ADVERSE_EXTENDED` when one does) — the available driving minutes remaining at `event_time` becomes negative, or the available 14-hour wall-clock minutes remaining becomes negative, or the available cycle minutes remaining becomes negative, generates a `Violation` row on the transition that closes the over-limit DRIVING interval. The cascade depth is two for the violation itself and three for the carrier-notification record. The violation's `triggering_duty_event_id` points at the duty event whose acceptance produced the breach; `rule_code` is one of `ELEVEN_HOUR_DRIVING`, `FOURTEEN_HOUR_WINDOW`, `SEVENTY_HOUR_CYCLE`, or `SIXTY_HOUR_CYCLE` (the last two distinguished by the driver's `cycle_type`); `detected_at` is the server clock at the triggering write; `overage_minutes` is the positive number of minutes by which the limit was exceeded at detection; `status` is `OPEN`; and `reported_to_fmcsa_at` and `fmcsa_report_id` are null until reported.

### 3.5. The Sleeper-Berth Split

The default reset between two driving shifts is a single unbroken 600-minute OFF_DUTY-plus-SLEEPER_BERTH window. The FMCSA sleeper-berth split allows a driver to pair two periods that together meet the reset. Going from `SLEEPER_BERTH` to `DRIVING` is admissible if the continuous OFF_DUTY-plus-SLEEPER_BERTH minutes ending at `event_time` are at least 600, or if a qualifying sleeper-berth pair exists; if neither condition holds, the request is rejected with `ERR_INSUFFICIENT_REST`. The pair qualifies when the following four conditions are simultaneously true, evaluated in the pinned order: first, the most recent unbroken `SLEEPER_BERTH` run ending at `event_time` (call this the long leg, with start S1, end E1, length L1) has L1 at least 420 minutes (seven hours); second, the most recent unbroken OFF_DUTY-or-SLEEPER_BERTH run ending at or before S1 (call this the short leg, with start S2, end E2, length L2) has L2 at least 120 minutes (two hours); third, the short leg ends no later than the long leg begins (E2 less than or equal to S1, so the two legs are ordered and never overlap); and fourth, the combined length L1 plus L2 is at least 600 minutes. If step one or step two finds no candidate run, the pair does not qualify. When the pair qualifies, the driving and on-duty windows reset at the end of the long leg E1.

Two pair shapes are recognised as legally distinct variants. A `SEVEN_THREE_SPLIT` is a long leg in the half-open range from 420 to 480 minutes paired with a short leg of at least 180 minutes — seven hours of `SLEEPER_BERTH` plus three hours of OFF_DUTY-or-SLEEPER_BERTH. An `EIGHT_TWO_SPLIT` is a long leg of at least 480 minutes paired with a short leg in the half-open range from 120 to 180 minutes — eight hours of `SLEEPER_BERTH` plus two hours of OFF_DUTY-or-SLEEPER_BERTH. The lookback for candidate legs is restricted to the most recent 36 hours of `ACTIVE` events for the driver.

### 3.6. Adverse Conditions

The two-hour adverse-conditions exemption is declared independently of the duty event that consumes it. A driver submits an `AdverseConditionsExemption` declaration carrying a UTC `declared_at` instant that must fall within the driver's current 14-hour window, and a `reason` string whose length is at least 10 characters (a brief justification — weather, traffic, road closure, or similar). The server mints the exemption with a `status` of `ACTIVE`, sets `extra_minutes_granted` to a fixed value of 120, and computes `applies_to_log_date` as the calendar date of `declared_at` in the driver's `home_terminal_timezone`.

An exemption is consumed exactly when the driver submits the first `DRIVING` duty event whose body carries that exemption's id in the `adverse_conditions_exemption_id` field and whose `event_time` is past the driver's unextended 11-hour driving limit or unextended 14-hour on-duty window. On consumption, the exemption's `status` flips from `ACTIVE` to `CONSUMED`. An `ACTIVE` exemption that is never consumed expires either when the server clock crosses midnight (in the driver's `home_terminal_timezone`) of the exemption's `applies_to_log_date`, or when the driver completes an unbroken OFF_DUTY-plus-SLEEPER_BERTH rest of at least 600 minutes; expiry flips the `status` from `ACTIVE` to `EXPIRED`. The clock-crossing branch is what makes the test clock necessary: an admin-only capability advances the server clock to a supplied `to` instant and, as a side effect, transitions any `AdverseConditionsExemption` rows whose home-terminal midnight is crossed during the advance from `ACTIVE` to `EXPIRED`.

Driving past the unextended limit with an exemption is the only way the eleven-hour and fourteen-hour caps stretch — see §3.4 — and the cycle cap is never affected by the exemption.

### 3.7. Daily Logs, Certification, and the Integrity Hash

A `DailyLog` is the per-driver, per-calendar-date roll-up of `ACTIVE` duty events. Its `log_date` is the calendar date expressed as a YYYY-MM-DD string in the driver's `home_terminal_timezone`, and the pair (`driver_id`, `log_date`) is unique. `total_driving_minutes` is the sum of `ACTIVE` event intervals on that date whose `new_status` is `DRIVING`, clipped to the log's 24-hour window. `total_on_duty_minutes` is the sum of `ACTIVE` event intervals on the same date whose `new_status` is one of `DRIVING`, `ON_DUTY_NOT_DRIVING`, or `YARD_MOVES`, again clipped — `PERSONAL_CONVEYANCE` and `SLEEPER_BERTH` are excluded. The log begins life with a `status` of `UNCERTIFIED`, a `certified_at` of null, and a `certification_count` of zero.

A driver certifies a log once she attests its accuracy. The transition from `UNCERTIFIED` to `CERTIFIED` requires the log's `log_date` to be strictly earlier than today as measured in the driver's `home_terminal_timezone`; certifying a log whose date is today or in the future is rejected with `ERR_LOG_NOT_YET_CERTIFIABLE`. On a successful certify, `DailyLog.status` is set to `CERTIFIED`, `certified_at` is set to the server clock at the moment of certification, `certification_count` is set to 1, and `integrity_hash` is recomputed and frozen against the canonical projection described below. If a duty-event append and a certify race for the same log, exactly one wins on `DailyLog.integrity_hash` plus `status`: when certify commits first, the event append loses with `ERR_LOG_ALREADY_CERTIFIED`; when the append commits first, the certify loses with `ERR_LOG_ALREADY_CERTIFIED` because the integrity hash has changed underneath the certify attempt.

Recertification is triggered by a driver edit on a duty event whose owning log is already `CERTIFIED` or `RECERTIFIED`. The driver supplies new values for any of `new_status`, `event_time`, `latitude`, `longitude`, `odometer_miles`, or `annotation`; the server appends a fresh `DutyEvent` with `edit_state` of `ACTIVE`, flips the old event's `edit_state` to `SUPERSEDED`, and sets the old event's `superseded_by_event_id` to the new event's id. The transition from `CERTIFIED` to `RECERTIFIED` (and the self-loop `RECERTIFIED` to `RECERTIFIED` for subsequent edits) requires the old event's `edit_state` to be `ACTIVE` and the server clock to be strictly less than `event_time` plus eight days — the FMCSA edit window; an edit submitted after that window is rejected with `ERR_EDIT_WINDOW_EXPIRED`. On a successful edit-induced transition, the affected log's `status` becomes `RECERTIFIED`, `certification_count` is incremented by 1, `integrity_hash` is recomputed against the new `ACTIVE` projection, and any `OPEN` or `ACKNOWLEDGED` `Violation` rows attached to the affected window are re-evaluated: a violation whose recomputed minutes-remaining at its `triggering_duty_event_id`'s `event_time` is greater than or equal to zero after the edit is flipped to `RESOLVED`, and new violations may be opened if the edit introduced a fresh overage.

The `integrity_hash` itself is the lowercase hexadecimal SHA-256 (64 characters) of a deterministic canonical-JSON serialisation of the log's `ACTIVE` `DutyEvent` projection. The serialisation includes only events whose `driver_id` matches the log's `driver_id`, whose `daily_log_id` matches the log's id, and whose `edit_state` is `ACTIVE`; `SUPERSEDED` events are excluded. Events are sorted ascending first by `event_time` and then by id as the tie-breaker. Each event projects to an object with seven keys in this exact order: `event_time` rendered as an ISO 8601 UTC timestamp with millisecond precision and a trailing Z; `new_status`; `vehicle_id`; `odometer_miles` as a floating-point number (with a missing reading rendered as 0); `latitude` rounded half-up to six decimal places; `longitude` rounded half-up to six decimal places; and `annotation` (with a missing annotation rendered as the empty string). The list is JSON-encoded with separators `","` and `":"`, with non-ASCII characters preserved as-is rather than escaped, and the UTF-8 byte representation is passed to SHA-256. The result is recomputed as a side effect of every event append on the log, every edit, every certify, and every recertify.

### 3.8. Violations, Acknowledgement, and Reporting to FMCSA

Every `Violation` is created automatically as a side effect of a duty event that exceeds a legal limit, as described in §3.4. The lifecycle of a violation starts at `OPEN`. A driver acknowledges it, transitioning `Violation.status` from `OPEN` to `ACKNOWLEDGED`; an acknowledgement attempt on a violation whose `status` is not `OPEN` is rejected with `ERR_INVALID_VIOLATION_STATE`. From `ACKNOWLEDGED`, the violation may follow either of two paths. A `CarrierSafetyOfficer` whose carrier matches the driver's carrier reports the violation, transitioning it from `ACKNOWLEDGED` to `REPORTED`; on success the server sets `reported_to_fmcsa_at` to the server clock and `fmcsa_report_id` to a freshly generated tracking identifier. A report attempt on a violation whose `status` is not `ACKNOWLEDGED` is rejected with `ERR_INVALID_VIOLATION_STATE`. Two safety officers racing to report the same violation serialise first-writer-wins on `Violation.status`: exactly one report is generated, and the second is rejected with `ERR_INVALID_VIOLATION_STATE` because the status has already advanced to `REPORTED`. Alternatively — and irrespective of whether the violation is `OPEN` or `ACKNOWLEDGED` — a driver edit that resolves the underlying overage transitions the violation to `RESOLVED` (`OPEN → RESOLVED` or `ACKNOWLEDGED → RESOLVED`) as the system-driven side effect of the `RECERTIFIED` flow described in §3.7; the resolution precondition is that the recomputed minutes-remaining at the triggering event time is non-negative. `REPORTED` and `RESOLVED` are terminal states.

### 3.9. The HOS Snapshot

At any point a `Driver`, `CarrierSafetyOfficer`, or `FMCSAAuditor` may ask for a driver's current hours-of-service view. The snapshot returns the three minutes-remaining values — driving (eleven-hour), window (fourteen-hour), and cycle (seventy- or sixty-hour, per the driver's `cycle_type`) — computed exactly as described in §3.4 against the current server clock. If an `ACTIVE` `AdverseConditionsExemption` attaches to the driver's current 14-hour window, both the `UNEXTENDED` and `ADVERSE_EXTENDED` variants are returned so that the caller can see what extra room the declaration would buy.

### 3.10. The Test Clock

Several rules in this system are time-gated: a log only becomes certifiable after its `log_date` has passed; an `AdverseConditionsExemption` only `EXPIRED`s at home-terminal midnight; the edit window closes at `event_time` plus eight days. To make these rules testable, a `PlatformAdmin` may advance the logical server clock to a supplied `to` instant via the test-driving capability. The side effect of an advance is that any `AdverseConditionsExemption` whose home-terminal-midnight of `applies_to_log_date` is crossed during the advance transitions from `ACTIVE` to `EXPIRED`. The current clock is queryable by `PlatformAdmin`, `Driver`, `CarrierSafetyOfficer`, and `FMCSAAuditor` alike via the read-only clock capability described in §4.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 on success. Endpoints that modify an existing resource — including bind, unbind, certify, acknowledge, report-to-FMCSA, and clock advance — respond with HTTP 200. List and fetch endpoints respond with HTTP 200. Authentication failures are 401, authorisation failures are 403, not-found is 404, schema-level invalid input is 400, and business and concurrency failures are either 409 or 422 per the catalogue in §5. The request and response bodies for every endpoint should be reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /carriers | Register a motor carrier. | PlatformAdmin |
| GET | /carriers/{carrier_id} | Fetch a carrier. | PlatformAdmin, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /eld-devices | Register an ELD device. | PlatformAdmin |
| GET | /eld-devices/{device_id} | Fetch an ELD device. | PlatformAdmin, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /vehicles | Register a vehicle and pair it with an ELD device. | CarrierSafetyOfficer |
| GET | /vehicles/{vehicle_id} | Fetch a vehicle. | CarrierSafetyOfficer, Driver, FMCSAAuditor |
| POST | /drivers | Register a driver. | CarrierSafetyOfficer |
| GET | /drivers/{driver_id} | Fetch a driver. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /drivers/{driver_id}/bind | Bind the driver to a vehicle through its installed ELD device. | Driver |
| POST | /drivers/{driver_id}/unbind | Unbind the driver from the currently bound vehicle. | Driver |
| POST | /drivers/{driver_id}/duty-events | Append a duty-status change event; triggers HOS evaluation and may create a Violation. | Driver |
| GET | /drivers/{driver_id}/duty-events | List a driver's duty events. Supports filter by `edit_state`, `from`, `to`, `daily_log_id`; paginated. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /drivers/{driver_id}/duty-events/{event_id}/edit | Driver edits an earlier event; the old event is superseded by a new ACTIVE one. | Driver |
| GET | /drivers/{driver_id}/hos-snapshot | Return the driver's current HOS view across all three limits with both UNEXTENDED and ADVERSE_EXTENDED variants when applicable. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| GET | /drivers/{driver_id}/daily-logs | List a driver's daily logs. Filter by `status`, `from_date`, `to_date`; paginated. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| GET | /drivers/{driver_id}/daily-logs/{log_id} | Fetch a daily log including its integrity hash and totals. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /drivers/{driver_id}/daily-logs/{log_id}/certify | Driver certifies a daily log. | Driver |
| GET | /violations | List violations. Filter by `driver_id`, `carrier_id`, `status`, `rule_code`; paginated. | CarrierSafetyOfficer, FMCSAAuditor |
| GET | /violations/{violation_id} | Fetch a violation. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /violations/{violation_id}/acknowledge | Driver acknowledges a violation. | Driver |
| POST | /violations/{violation_id}/report-to-fmcsa | Carrier safety officer reports an acknowledged violation to FMCSA. | CarrierSafetyOfficer |
| POST | /drivers/{driver_id}/adverse-conditions | Driver declares adverse conditions for the current 14-hour window. | Driver |
| GET | /drivers/{driver_id}/adverse-conditions | List a driver's adverse-conditions declarations. Filter by `status`; paginated. | Driver, CarrierSafetyOfficer, FMCSAAuditor |
| POST | /_clock/advance | Test-driving capability that advances the logical server clock to a supplied `to` instant. | PlatformAdmin |
| GET | /_clock | Read the current logical server clock. | PlatformAdmin, Driver, CarrierSafetyOfficer, FMCSAAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_INPUT | 400 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_DUTY_EVENT_OUT_OF_ORDER | 409 |
| ERR_DRIVER_NOT_BOUND | 409 |
| ERR_DRIVER_ALREADY_BOUND | 409 |
| ERR_VEHICLE_ALREADY_BOUND | 409 |
| ERR_INVALID_DUTY_STATUS_FOR_BIND | 409 |
| ERR_CROSS_CARRIER_BIND | 422 |
| ERR_ELD_NOT_CERTIFIED | 422 |
| ERR_VEHICLE_MISMATCH | 422 |
| ERR_ELEVEN_HOUR_LIMIT_EXCEEDED | 409 |
| ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED | 409 |
| ERR_CYCLE_LIMIT_EXCEEDED | 409 |
| ERR_INSUFFICIENT_REST | 409 |
| ERR_ANNOTATION_REQUIRED | 422 |
| ERR_EXEMPTION_NOT_ACTIVE | 422 |
| ERR_ODOMETER_DECREASED | 422 |
| ERR_LOG_ALREADY_CERTIFIED | 409 |
| ERR_LOG_NOT_YET_CERTIFIABLE | 422 |
| ERR_EDIT_WINDOW_EXPIRED | 422 |
| ERR_INVALID_VIOLATION_STATE | 409 |
