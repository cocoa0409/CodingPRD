# Truck ELD HOS API — Product Requirements Document

## 1. Introduction

This document specifies the Truck ELD HOS API, an electronic-logging-device back end that records a commercial driver's duty status in real time and enforces the United States Federal Motor Carrier Safety Administration Hours-of-Service rules from the recorded event stream. The fundamental design premise is event sourcing: a driver's compliance picture is never edited in place. Instead, the driver's bound device appends an immutable sequence of duty-status events, and every clock, every daily total, and every violation is *derived* from replaying that sequence. Corrections do not overwrite history either; a correcting event supersedes its target and the entire derived picture is recomputed from the surviving record. This audit-first posture is what an FMCSA roadside inspection or a carrier safety audit demands, and the API is built so that the recorded events are the single source of truth and every consequence is reproducible from them.

The system serves three human constituencies and one automated one. A driver, operating through a single device they are logged in to, owns their own duty log: they bind to a device, append events, file for adverse-conditions relief, and certify their daily logs. A carrier's back-office staff manage the fleet — drivers, vehicles, and devices — and hold the authority to mark erroneous records and to flag malfunctioning hardware. Compliance reviewers adjudicate the violations the engine surfaces and decide adverse-conditions claims. Underpinning all three, an automated system actor performs the recomputations that flip compliance dispositions, force re-certification of stale logs, and auto-dismiss violations that a correction has rendered moot. The remainder of this document defines the global contract every client obeys (Section 2), the business logic and workflows that govern the duty-status engine (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they act. The role value must be one of exactly three callable roles: `Driver`, `CarrierAdmin`, or `SafetyOfficer`. A request missing the role header, carrying a role outside this set, or omitting `X-User-ID` where the acting role requires it is rejected with `ERR_UNAUTHENTICATED`. A well-authenticated request whose role is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`.

The three roles bind to identity differently. When `X-User-Role` is `Driver`, the role is entity-backed: `X-User-ID` is the `id` of the acting `Driver`, and ownership checks on any resource that references a driver compare the resource's `driver_id` (or, for a device logout, the device's `bound_driver_id`) against `X-User-ID`. A `Driver` may therefore act only on their own duty events, daily logs, and adverse-conditions claims; acting on a resource owned by another driver is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `CarrierAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server accepts it for attribution but never compares it to any entity's `id`. When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`. There is also a fourth, non-callable actor — the automated ELD system — which performs system-triggered transitions (recompute-driven re-certification, auto-dismissal of corrected violations, and compliance-disposition flips). It is never invoked directly by a client; it documents the side effects the server itself originates.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of records to skip from the front of the result set and defaults to 0. A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific list operation states otherwise, list endpoints return records sorted by `created_at` in ascending order. The `meta` object on a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the full filtered set and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Version Semantics

Every primary resource is minted with a server-generated `id` — a UUID carrying no type prefix. The `id` is identity only and is never itself an input to any business decision. Most resources additionally carry three system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits fixed at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arise as cascaded side effects rather than a direct client write; and `version`, an integer that starts at 1 on creation and increments by exactly one on every mutation. The `version` field doubles as the optimistic-concurrency token described in Section 2.6.

The `Driver`, `Vehicle`, `ELDDevice`, `DutyStatusEvent`, `DailyLog`, `HOSViolation`, and `AdverseConditionsClaim` resources all carry the full set of `created_at`, `updated_at`, and `version`. The `PersonalConveyanceSegment` resource is the sole exception: it is a derived audit record carrying only `id` and `created_at`. It has neither an `updated_at` nor a `version` field, because it is never the direct target of a client write — it is created, refreshed, and removed entirely as a consequence of duty-event recomputation.

### 2.5. Derived State, Recomputation, and Cascade Consistency

A defining characteristic of this system is that large portions of a resource's state are *computed*, not stored as client input, and are reconciled atomically whenever the underlying event stream changes. A driver's `current_duty_status` and `cycle_on_duty_minutes`, a duty event's `duration_minutes` and `compliance_disposition`, a vehicle reference snapshot on an event, and a daily log's `total_driving_minutes`, `total_on_duty_minutes`, and `total_off_duty_minutes` are all derived fields. Whenever a recomputation changes any of these, the owning resource is mutated: its `updated_at` is refreshed and its `version` increments by one, exactly as a direct write would. A recompute that touches a daily log therefore advances that log's `version` even though no client called the certify operation.

Cascades propagate downstream automatically. When recomputation changes a day's totals after the driver had already certified that day's log, the log's `certification_status` is forced from `CERTIFIED` back to `RECERTIFY_REQUIRED` and its `certified_at` is cleared to null — the driver must re-certify the corrected day. When a correction or an erroneous-record marking causes a previously open violation's trigger interval to no longer cross its limit, that violation is auto-dismissed by the system without any reviewer action. These reconciliations are the server's own work; they are not requested on the cascaded resource directly, yet each one is a full mutation of the resource it touches.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each demands a non-optional version field in its request body that the client must set to the `version` it last observed on the relevant parent resource.

Appending a duty status event requires `expected_driver_version` to equal the acting driver's current `version`. A duty-event append legitimately mutates the driver — recomputation refreshes the driver's `current_duty_status` and `cycle_on_duty_minutes` and bumps the driver's `version` — so a second append still carrying the pre-append version is operating on a stale view of the driver's clocks. When `expected_driver_version` does not equal the driver's current `version`, the append is rejected with `ERR_STALE_VERSION` (HTTP 412) before any event is recorded. Marking a duty event as erroneous requires `expected_dutystatusevent_version` to equal that event's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Approving an adverse-conditions claim requires `expected_adverseconditionsclaim_version` to equal that claim's current `version`; if the claim's version has advanced since the reviewer last read it, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) before any clock recomputation runs. Two further administrative writes — updating mutable driver fields and changing a vehicle's service status — likewise accept a version field, `expected_driver_version` and `expected_vehicle_version` respectively, checked against the target resource's current `version`. Operations not named here take no version field.

### 2.7. Nested Resource Retrieval and Reference Validation

When a request addresses a resource by an identifier embedded in its URL path, the server validates that identifier's existence before proceeding; an unknown path identifier yields `ERR_NOT_FOUND`. Where a path carries more than one identifier, validation proceeds strictly left to right, and the first identifier that does not resolve to an existing resource is the one reported. Foreign-key identifiers supplied in a request body — a `driver_id`, `device_id`, `vehicle_id`, `trigger_event_id`, or `edited_from_event_id` — are a separate concern: when any of these references a resource that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Both of these conditions carry HTTP 404, but the path case and the body-reference case use distinct identifiers so a reader can tell which kind of reference failed.

### 2.8. Time, Days, and Minute Precision

Time is central to every Hours-of-Service rule, so the system is precise about how it is measured. Each duty event's `event_time` is an ISO 8601 UTC instant. The duration an event occupies is the whole number of minutes from that event's `event_time` to the next surviving event's `event_time` for the same driver; the latest (still-open) event has no successor and therefore carries a null `duration_minutes` until a later event closes it. All HOS arithmetic is in integer minutes. Each interval's contribution is truncated downward to a whole minute first, and the truncated per-interval values are then summed — the totals are a sum of floored intervals, never a floor applied to a sum of fractional intervals.

Calendar days are not UTC days. A driver's `home_terminal_tz_offset_minutes` gives the minutes east of UTC of the driver's home terminal (for example, -300 for US Eastern standard time), and this offset defines the 24-hour boundary used to partition events into daily logs and to align the rolling cycle window. The offset defaults to 0 and must be an integer no less than -720 and no greater than 840. A daily log's `log_date` is the home-terminal calendar date, written as a `YYYY-MM-DD` string, that the log covers.

### 2.9. Uniqueness and Request Validity

Several business identifiers are unique within their kind. A `Driver`'s `license_number` must be unique across all drivers; a duplicate is rejected with `ERR_DUPLICATE_LICENSE`. A `Vehicle`'s `unit_number` must be unique across all vehicles; a duplicate is rejected with `ERR_DUPLICATE_UNIT`. An `ELDDevice`'s `serial_number` must be unique across all devices; a duplicate is rejected with `ERR_DUPLICATE_SERIAL`. Beyond uniqueness, every write is checked for basic well-formedness: required body fields must be present and of the correct type, every enum-valued field must carry a value inside its declared domain, and pagination parameters must lie within their bounds. A request failing any of these structural checks is rejected with `ERR_INVALID_REQUEST`.

### 2.10. Order of Validation

When several conditions could reject a single request, they are evaluated in a fixed priority so that the returned error is stable and meaningful. Authentication is checked first: a missing or invalid role header, or a missing `X-User-ID` on an entity-backed driver call, yields `ERR_UNAUTHENTICATED`. Role authorization is checked next, yielding `ERR_UNAUTHORIZED` when the role may not perform the operation. The system then confirms that every resource identifier in the path exists (`ERR_NOT_FOUND`), then that every foreign key in the body resolves (`ERR_REFERENCE_NOT_FOUND`). Resource-level ownership is checked next for driver-scoped mutations: an entity-backed driver acting on a resource whose `driver_id` — or, on logout, whose device `bound_driver_id` — is not their own `X-User-ID` is rejected with `ERR_UNAUTHORIZED`. The system then confirms the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), after which the operation-specific business rules described in Section 3 apply in the order set out there, with the optimistic-concurrency version check (`ERR_STALE_VERSION`) and the catch-all structural check (`ERR_INVALID_REQUEST`) sitting at the low-priority end of the chain.

## 3. Business Logic & Workflows

### 3.1. Fleet Setup: Drivers, Vehicles, and Devices

Before any logging can happen, a carrier operator stands up the fleet. Creating a driver supplies a `license_number` and a `full_name`, and may supply a `home_terminal_tz_offset_minutes`, a `cycle_rule`, and a `pc_authorized` flag. A new driver is created with `status` `ACTIVE`, `version` 1, a `current_duty_status` of `OFF_DUTY` because no events yet exist, and the three optional fields defaulting respectively to an offset of 0, a `cycle_rule` of `SEVENTY_HOUR_8_DAY`, and `pc_authorized` set to false. The `cycle_rule` selects which cycle limit governs the driver and must be either `SEVENTY_HOUR_8_DAY` or `SIXTY_HOUR_7_DAY`. The `pc_authorized` flag records whether the carrier has authorized this driver to use Personal Conveyance duty status. A carrier operator may later update a driver's mutable fields — `pc_authorized`, `cycle_rule`, and lifecycle `status` (which is one of `ACTIVE` or `DEACTIVATED`) — supplying `expected_driver_version`; the update bumps the driver's `version` by one.

Creating a vehicle supplies a `unit_number` and a `vin`; the vehicle starts `IN_SERVICE` at `version` 1, where its `status` is one of `IN_SERVICE` or `OUT_OF_SERVICE`. A carrier operator can later change a vehicle's `status`, supplying `expected_vehicle_version`, and that change bumps the vehicle's `version` by one. Registering an ELD device supplies a `serial_number` and the `vehicle_id` of the vehicle it is installed in; the device is created `UNBOUND` at `version` 1, with its `bound_driver_id` null and its `status` one of `UNBOUND`, `BOUND`, or `MALFUNCTION`. Devices may be listed and filtered by their `vehicle_id`, their `bound_driver_id`, or their `status`, which is how an operator finds, for example, every device currently bound to a given driver.

### 3.2. Identity Binding: Logging In and Out of a Device

A driver establishes identity by logging in to a device, which transitions that device `UNBOUND → BOUND` and writes the acting driver's id into the device's `bound_driver_id`, bumping the device's `version`. Login is permitted only when the device is `UNBOUND`; attempting it on a device that is not `UNBOUND` is rejected with `ERR_DEVICE_ALREADY_BOUND`. The device's vehicle must be `IN_SERVICE`; a login against a device whose vehicle is `OUT_OF_SERVICE` is rejected with `ERR_VEHICLE_OUT_OF_SERVICE`. The acting driver must not already hold another bound device — a driver may be bound to at most one device at a time — and a second concurrent binding is rejected with `ERR_DRIVER_ALREADY_BOUND`. The driver's own `status` must be `ACTIVE`.

Logging out transitions the device `BOUND → UNBOUND` and clears `bound_driver_id` back to null, bumping the device's `version`. Only the driver currently bound to the device may log it out; a logout by anyone other than the bound driver is rejected with `ERR_UNAUTHORIZED`. Logout is also blocked while the driver is actually driving: if the driver's `current_duty_status` is `DRIVING`, the logout is rejected with `ERR_CANNOT_LOGOUT_WHILE_DRIVING`, since a driver cannot end their session mid-drive. Separately, a carrier operator may flag a bound device as malfunctioning, transitioning it `BOUND → MALFUNCTION` while retaining the binding for forensic trace; this is permitted only from `BOUND`, and from any other state is rejected with `ERR_INVALID_STATE`. Clearing the malfunction transitions the device `MALFUNCTION → UNBOUND` and clears `bound_driver_id`; it is permitted only from `MALFUNCTION` and otherwise rejected with `ERR_INVALID_STATE`. Both malfunction transitions bump the device's `version`.

### 3.3. Appending Duty-Status Events

The heart of the system is the append of a duty status event by the driver. The body carries the `driver_id` of the driver whose log the event belongs to, the `device_id` of the recording ELD, a `duty_status`, an `event_time`, and `expected_driver_version`; it may also carry a `special_driving_category`, an `edited_from_event_id`, and an `annotation`. The `duty_status` is one of `OFF_DUTY`, `SLEEPER_BERTH`, `DRIVING`, or `ON_DUTY_NOT_DRIVING`. The event records the vehicle on a computed `vehicle_id` snapshot copied from the device's installed vehicle at append time. A new event is created with `record_status` `ACTIVE`, a `compliance_disposition` of `COMPLIANT`, and `version` 1.

Several preconditions guard the append. The referenced driver must exist and be `ACTIVE`. The referenced device must be `BOUND` and its `bound_driver_id` must equal the supplied `driver_id`; if the device is not bound to the driver, the append is rejected with `ERR_DEVICE_NOT_BOUND`. The `event_time` must be strictly greater than the `event_time` of the latest surviving event for this driver — events arrive in strictly increasing time order — and an `event_time` that is not strictly later is rejected with `ERR_EVENT_OUT_OF_ORDER`. The `special_driving_category` annotates a driving or off-duty event as Personal Conveyance or as a yard move and is one of `NONE`, `PERSONAL_CONVEYANCE`, or `YARD_MOVE`, defaulting to `NONE`. When it is `PERSONAL_CONVEYANCE`, the driver must have `pc_authorized` set to true and the `duty_status` must be either `DRIVING` or `OFF_DUTY`; a Personal Conveyance annotation that fails either condition is rejected with `ERR_PC_NOT_AUTHORIZED`. Whenever the `special_driving_category` is anything other than `NONE`, or whenever `edited_from_event_id` is supplied, a non-empty `annotation` is required, and its absence is rejected with `ERR_ANNOTATION_REQUIRED`.

A plain append that succeeds closes the previously open event by setting that prior event's `duration_minutes` to the whole-minute gap between the prior event's `event_time` and this new event's `event_time`. It then runs the clock recomputation and the violation scan described in Section 3.4, refreshing the driver's `current_duty_status` and `cycle_on_duty_minutes` and the affected daily logs' rolling totals, opening any violations the new interval crosses, and setting `compliance_disposition` to `VIOLATING` on the offending events. Any daily log touched by the recomputation that was `CERTIFIED` flips to `RECERTIFY_REQUIRED`. The driver's `version` increments by one as part of this mutation.

### 3.4. Deriving the Hours-of-Service Clocks

Every append, every correction, every erroneous-record marking, and every adverse-claim approval triggers a full recomputation of the driver's clocks from the surviving event stream, followed immediately by a violation scan. The recomputation considers only `ACTIVE` events for that driver; events in `INACTIVE_CHANGED` or `INACTIVE_ERROR` are excluded from every clock and every violation calculation entirely. The driver's `ACTIVE` events are replayed in `event_time` order, with the earlier `created_at` breaking ties. Each closed event spans the interval from its `event_time` to the next `ACTIVE` event's `event_time`; the latest open event contributes nothing until it is closed.

Each closed interval is classified by its `duty_status` and `special_driving_category`. A `DRIVING` interval with category `NONE` advances the driving clock, the 14-hour window clock, and the cycle. An `ON_DUTY_NOT_DRIVING` interval with category `NONE` advances the window clock and the cycle but not the driving clock. A `DRIVING` interval annotated `YARD_MOVE` advances the window clock and the cycle but not the driving clock. An interval annotated `PERSONAL_CONVEYANCE` is excluded from the driving clock, the window clock, and the cycle alike. `OFF_DUTY` intervals with category `NONE` and `SLEEPER_BERTH` intervals are off-duty time and advance none of the driving, window, or cycle clocks.

The driving clock is the running total of `DRIVING`-with-`NONE` plus `YARD_MOVE` minutes accumulated since the last driving reset. A driving reset occurs on a qualifying off-duty break, which is either a single continuous off-duty span — combined `OFF_DUTY` and/or `SLEEPER_BERTH` time of at least 600 minutes (10 hours) — or a valid sleeper-berth split pairing as described below; in both cases the driving clock and the window clock are reset to zero. The window clock is the elapsed time since the first on-duty event following the last driving reset — that is, the 14-hour window measured as wall-clock elapsed time from window start — reduced by any minutes that fall inside qualifying sleeper-split rest periods. The break clock is the run of consecutive `DRIVING`-with-`NONE` plus `YARD_MOVE` minutes accumulated since the last non-driving interval of at least 30 minutes (which may be `OFF_DUTY`, `SLEEPER_BERTH`, or `ON_DUTY_NOT_DRIVING`).

A driver's `cycle_on_duty_minutes` is the sum of `DRIVING`-with-`NONE`, `YARD_MOVE`, and `ON_DUTY_NOT_DRIVING` minutes over the rolling cycle window: all events whose home-terminal calendar day falls within the last 8 days for a `SEVENTY_HOUR_8_DAY` driver, or within the last 7 days for a `SIXTY_HOUR_7_DAY` driver, counting inclusively up to and including the home-terminal day of the latest event. Personal Conveyance, sleeper, and off-duty time are excluded from the cycle. All four clocks are kept in integer minutes, each interval truncated to whole minutes before summing.

The sleeper-berth split lets a driver bank rest in two periods rather than one continuous break. A valid split is a pair of qualifying rest periods that together total at least 600 minutes, in which one period — the long rest — is at least 420 minutes and is entirely `SLEEPER_BERTH`, and the other period — the short rest — is at least 120 minutes and is either `SLEEPER_BERTH` or `OFF_DUTY`; the familiar 7-and-3 and 8-and-2 arrangements are the common cases of this general rule. Each rest period pairs with the nearest preceding qualifying period that has not already been paired, taking earliest-unpaired periods first and breaking ties on `created_at` ascending. When a pair completes — which happens at the end of the later of the two periods — the driving clock and window clock are recomputed as though the minutes inside both paired rest periods had not elapsed, and the driving and window clocks are credited as reset from the end of that later period. A single continuous off-duty or sleeper span of at least 600 minutes is the degenerate full reset and is handled directly by the driving-reset rule rather than by the split rule.

### 3.5. Detecting and Recording Violations

Immediately after the clocks are recomputed, the violation scan walks the recomputed running clocks in chronological order and, after adding each closed interval to its relevant clock, tests each limit. The first interval that pushes a clock strictly past its limit is the trigger for a violation of that type, recorded as the violation's `trigger_event_id`. Equality with a limit is compliant: the test is a strict exceedance, so a driving clock of exactly 660 minutes is fine and 661 violates. There are four limit types. A `DRIVING_11H` violation arises when the driving clock exceeds 660 minutes (11 hours). A `WINDOW_14H` violation arises when the window clock exceeds 840 minutes (14 hours). A `BREAK_30MIN` violation arises when the break clock exceeds 480 minutes (8 hours of driving) without a qualifying non-driving interval of at least 30 minutes having been taken. A `CYCLE_70H` violation arises when `cycle_on_duty_minutes` exceeds 4200 minutes (70 hours) for a `SEVENTY_HOUR_8_DAY` driver, or exceeds 3600 minutes (60 hours) for a `SIXTY_HOUR_7_DAY` driver.

A violation row records the `driver_id` who incurred it, its `trigger_event_id`, its `violation_type` — one of `DRIVING_11H`, `WINDOW_14H`, `BREAK_30MIN`, or `CYCLE_70H` — and an `overage_minutes` equal to the clock value after the triggering interval minus the applicable limit; a row is only opened when that overage is at least 1 minute. Duplicate rows are suppressed: at most one open violation exists per driver, per violation type, per driving-reset epoch, while `CYCLE_70H` is at most one open row per rolling cycle window. When a later interval pushes an already-open type further past its limit, that existing row's `overage_minutes` is revised upward rather than opening a second row. A new violation is created with `status` `OPEN`, where the violation review lifecycle's `status` is one of `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, or `DISMISSED`. Violations are the substance of FMCSA reporting and may be listed and filtered by `driver_id`, `trigger_event_id`, `violation_type`, or `status`.

### 3.6. Corrections and Erroneous Records

The event stream is immutable, so a driver fixes a mistake not by editing an event but by appending a correcting event that names the superseded event in `edited_from_event_id` and carries the required `annotation`. The `edited_from_event_id` must reference an `ACTIVE` event belonging to the same driver; a target that is not an active event of that driver is rejected with `ERR_EDIT_TARGET_INVALID`. The correcting event must itself satisfy every append precondition from Section 3.3. On success the superseded event's `record_status` transitions `ACTIVE → INACTIVE_CHANGED`, its `version` increments, and the clocks and violations are recomputed over the corrected stream. Because the surviving set has changed, a neighbouring event's `compliance_disposition` may flip in either direction between `COMPLIANT` and `VIOLATING`. If a previously `OPEN` violation's trigger interval no longer crosses its limit after the correction, that violation is auto-transitioned `OPEN → DISMISSED` with its `resolution_note` set to the system note "auto-dismissed: corrected".

A carrier operator handles a different kind of mistake — a record that should never have existed — by marking an event erroneous, supplying `expected_dutystatusevent_version`. This is permitted only while the event's `record_status` is `ACTIVE`; from any other record status it is rejected with `ERR_INVALID_STATE`. Marking transitions the event `ACTIVE → INACTIVE_ERROR`, which removes it from every clock and violation computation, increments its `version`, and triggers the same recomputation and reconciliation of downstream daily-log totals, driver clocks, and affected violations. A duty event carries two independent status dimensions on the same record: `record_status` — one of `ACTIVE`, `INACTIVE_CHANGED`, or `INACTIVE_ERROR` — tracks the record's origin lifecycle, while `compliance_disposition` tracks whether the event's interval currently sits inside a violation window. The two evolve independently and never gate one another; a correction drives the first while a recomputation drives the second. Events may be listed and filtered by `driver_id`, `device_id`, `vehicle_id`, `record_status`, or `edited_from_event_id`, the last of which walks the edit chain.

### 3.7. Personal Conveyance Segments

When a driver operates under Personal Conveyance, the time spent does not advance any HOS clock, and the system keeps an explicit audit trail of that exclusion. Once the event following a `PERSONAL_CONVEYANCE`-annotated driving-or-off-duty event arrives and closes the PC interval — fixing that event's `duration_minutes` — the system creates exactly one Personal Conveyance segment for the prior PC event. The segment records the `driver_id`, the `event_id` of the PC event it summarizes, and a computed `minutes_excluded` equal to that event's `duration_minutes` — the minutes deliberately withheld from the driving, window, and cycle clocks. The segment's `minutes_excluded` is recomputed whenever the underlying event's duration changes, and the segment is removed if its event ever leaves `ACTIVE` status. Summing `minutes_excluded` across a driver's home-terminal day yields the day's audit total of Personal Conveyance time that advanced no clock. Segments may be listed and filtered by `driver_id` or by `event_id`.

### 3.8. Daily Logs and Certification

A daily log materializes a driver's 24-hour record for one home-terminal day so its totals can be tracked and certified. Opening a log supplies the `driver_id` and the `log_date`; the log is created `UNCERTIFIED` with its totals computed from the current `ACTIVE` events that fall in that home-terminal day. The log's three derived totals are: `total_driving_minutes`, the sum of `duration_minutes` over `ACTIVE` `DRIVING` events with category `NONE` whose `event_time` falls in the day; `total_on_duty_minutes`, the sum over `ACTIVE` `ON_DUTY_NOT_DRIVING` plus category-`NONE` `DRIVING` events in the day; and `total_off_duty_minutes`, the sum over `ACTIVE` `OFF_DUTY` events of any category plus `SLEEPER_BERTH` events in the day. A log's `certification_status` is one of `UNCERTIFIED`, `CERTIFIED`, or `RECERTIFY_REQUIRED`, and its `certified_at` holds the instant of certification, null until then. Logs may be listed and filtered by `driver_id`, `certification_status`, or `log_date`.

Certifying a log is a driver action: it transitions the log to `CERTIFIED`, sets `certified_at` to the current clock, and bumps the log's `version`. Certification is allowed both from `UNCERTIFIED` and from `RECERTIFY_REQUIRED` — the second is the re-certification path after a late edit forced the day stale — and from any other state the request is not a defined transition. Only the owning driver may certify their log; a certify by anyone whose `X-User-ID` is not the log's `driver_id` is rejected with `ERR_UNAUTHORIZED`. A log whose `log_date` is in the future relative to the server's current clock cannot be certified and is rejected with `ERR_CANNOT_CERTIFY_FUTURE`. Furthermore, a past day — one whose `log_date` is earlier than today — cannot be certified while any `ACTIVE` event in that day still has a null `duration_minutes`, because an open event means the day is not yet closed; such an attempt is rejected with `ERR_OPEN_EVENT_ON_CLOSED_DAY`. As described in Section 2.5, when a later append, correction, or erroneous-record marking changes a previously `CERTIFIED` day's totals, the system itself forces that log `CERTIFIED → RECERTIFY_REQUIRED`, clears `certified_at`, and bumps the log's `version`.

### 3.9. Adverse Conditions Claims and the Extended-Limit Recompute

A driver who hit unforeseen conditions may file an Adverse Conditions exemption claim for a day, supplying the `driver_id`, the `log_date` the exemption applies to, a `reason` — one of `WEATHER`, `ROAD_CLOSURE`, or `TRAFFIC_INCIDENT` — and a non-empty `narrative` explaining the circumstances; an empty narrative is rejected with `ERR_ANNOTATION_REQUIRED`. The claim is created `PENDING`, where its `status` is one of `PENDING`, `APPROVED`, or `REJECTED`. A compliance reviewer adjudicates the claim, and the two outcomes are deliberately asymmetric.

Approving a claim is the consequential branch. It requires the claim still be `PENDING`, otherwise `ERR_INVALID_STATE`, and it requires `expected_adverseconditionsclaim_version` to match the claim's current `version` per Section 2.6. It also requires that no other `APPROVED` claim already exist for the same `driver_id` and `log_date` pair; a second approved claim for that day is rejected with `ERR_DUPLICATE_ADVERSE_CLAIM`. On approval the claim moves `PENDING → APPROVED` and the clocks and violation scan are rerun for that driver-day under the extended-limit variant: only for intervals whose home-terminal day is the claimed day, the driving limit is raised from 660 to 780 minutes (13 hours) and the window limit is raised from 840 to 960 minutes (16 hours). The break requirement and the cycle limit are never extended, and the cycle clock is never recomputed under extended limits. Any `OPEN` or `ACKNOWLEDGED` `DRIVING_11H` or `WINDOW_14H` violation on that day whose overage disappears under the extended limits is auto-transitioned to `DISMISSED` with its `resolution_note` set to "auto-dismissed: adverse conditions". The approval bumps the claim's `version`, and the recompute bumps the driver's `version`. Rejecting a claim is the inert branch: it requires the claim be `PENDING` (else `ERR_INVALID_STATE`), moves it `PENDING → REJECTED`, changes no clock, and bumps only the claim's `version`. Claims may be listed and filtered by `driver_id`, `status`, or `log_date`.

### 3.10. The Violation Review Lifecycle

A compliance reviewer works each open violation through a review lifecycle that allows for revision. Acknowledging an open violation transitions it `OPEN → ACKNOWLEDGED` and bumps its `version`; it is permitted only from `OPEN`, otherwise `ERR_INVALID_STATE`. An acknowledged violation may be re-opened, transitioning `ACKNOWLEDGED → OPEN` and bumping its `version`, permitted only from `ACKNOWLEDGED` (else `ERR_INVALID_STATE`) — this lets a reviewer undo a premature acknowledgement. Resolving a violation transitions it `ACKNOWLEDGED → RESOLVED`, stores the supplied `resolution_note`, and bumps its `version`; it is permitted only from `ACKNOWLEDGED` (else `ERR_INVALID_STATE`) and requires a non-empty `resolution_note`, whose absence is rejected with `ERR_ANNOTATION_REQUIRED`. Both `RESOLVED` and `DISMISSED` are terminal review outcomes. Beyond the reviewer's manual path, the system itself can dismiss a violation: when a correction or an extended-limit recompute makes a trigger interval compliant, an `OPEN` or `ACKNOWLEDGED` violation auto-transitions to `DISMISSED` and records the corresponding system `resolution_note`, as set out in Sections 3.6 and 3.9.

### 3.11. Deterministic Clock Control

Because several rules turn on "now" — whether a `log_date` is in the future, where a rolling cycle window's edge falls, and whether a day is closed — the server exposes an administrative capability that pins its current UTC clock to a supplied instant. A carrier operator invokes it with a `to_iso8601` value, after which the certify future-check and the cycle-window boundary arithmetic evaluate against that pinned instant. This capability exists to make time-gated behaviour deterministic for verification; it transitions no business resource and returns no resource body.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and the administrative clock-control call — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eld/drivers` | Create a driver | CarrierAdmin |
| GET | `/eld/drivers/{id}` | Fetch a driver with computed clocks | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/drivers` | List drivers (paginated) | CarrierAdmin, SafetyOfficer |
| PATCH | `/eld/drivers/{id}` | Update mutable driver fields | CarrierAdmin |
| POST | `/eld/vehicles` | Create a vehicle | CarrierAdmin |
| GET | `/eld/vehicles/{id}` | Fetch a vehicle | Driver, CarrierAdmin, SafetyOfficer |
| PATCH | `/eld/vehicles/{id}` | Change vehicle service status | CarrierAdmin |
| POST | `/eld/devices` | Register an ELD device against a vehicle | CarrierAdmin |
| GET | `/eld/devices/{id}` | Fetch a device with binding state | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/devices` | List devices (filterable) | CarrierAdmin, SafetyOfficer |
| POST | `/eld/devices/{id}/login` | Driver logs in to a device | Driver |
| POST | `/eld/devices/{id}/logout` | Driver logs out of a device | Driver |
| POST | `/eld/devices/{id}/flag-malfunction` | Mark a bound device malfunctioning | CarrierAdmin |
| POST | `/eld/devices/{id}/clear-malfunction` | Clear a malfunction and unbind | CarrierAdmin |
| POST | `/eld/duty-events` | Append a duty status event (or a correction) | Driver |
| GET | `/eld/duty-events/{id}` | Fetch a duty event with computed fields | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/duty-events` | List duty events (filterable) | Driver, CarrierAdmin, SafetyOfficer |
| POST | `/eld/duty-events/{id}/mark-error` | Mark an active event erroneous | CarrierAdmin |
| POST | `/eld/daily-logs` | Open a daily log for a driver-day | Driver, CarrierAdmin |
| GET | `/eld/daily-logs/{id}` | Fetch a daily log with computed totals | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/daily-logs` | List daily logs (filterable) | Driver, CarrierAdmin, SafetyOfficer |
| POST | `/eld/daily-logs/{id}/certify` | Driver certifies a daily log | Driver |
| GET | `/eld/hos-violations/{id}` | Fetch a violation | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/hos-violations` | List violations (FMCSA reporting, filterable) | Driver, CarrierAdmin, SafetyOfficer |
| POST | `/eld/hos-violations/{id}/acknowledge` | Acknowledge an open violation | SafetyOfficer |
| POST | `/eld/hos-violations/{id}/reopen` | Re-open an acknowledged violation | SafetyOfficer |
| POST | `/eld/hos-violations/{id}/resolve` | Resolve an acknowledged violation with a note | SafetyOfficer |
| POST | `/eld/adverse-claims` | File an Adverse Conditions exemption claim | Driver |
| GET | `/eld/adverse-claims/{id}` | Fetch an adverse-conditions claim | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/adverse-claims` | List adverse-conditions claims (filterable) | Driver, CarrierAdmin, SafetyOfficer |
| POST | `/eld/adverse-claims/{id}/approve` | Approve a claim; recompute under extended limits | SafetyOfficer |
| POST | `/eld/adverse-claims/{id}/reject` | Reject a claim | SafetyOfficer |
| GET | `/eld/pc-segments/{id}` | Fetch one Personal Conveyance segment | Driver, CarrierAdmin, SafetyOfficer |
| GET | `/eld/pc-segments` | List Personal Conveyance segments (filterable) | Driver, CarrierAdmin, SafetyOfficer |
| POST | `/_clock/set_current_utc` | Pin the server's current UTC clock | CarrierAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DEVICE_NOT_BOUND` | 409 Conflict |
| `ERR_DEVICE_ALREADY_BOUND` | 409 Conflict |
| `ERR_DRIVER_ALREADY_BOUND` | 409 Conflict |
| `ERR_VEHICLE_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_EVENT_OUT_OF_ORDER` | 409 Conflict |
| `ERR_PC_NOT_AUTHORIZED` | 422 Unprocessable Entity |
| `ERR_ANNOTATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EDIT_TARGET_INVALID` | 409 Conflict |
| `ERR_DUPLICATE_ADVERSE_CLAIM` | 409 Conflict |
| `ERR_CANNOT_CERTIFY_FUTURE` | 409 Conflict |
| `ERR_OPEN_EVENT_ON_CLOSED_DAY` | 409 Conflict |
| `ERR_CANNOT_LOGOUT_WHILE_DRIVING` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE` | 409 Conflict |
| `ERR_DUPLICATE_UNIT` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
