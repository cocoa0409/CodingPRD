# Beach & Lifeguard Operations API — Product Requirements Document

## 1. Introduction

Coastal municipalities run their public beaches as tightly coupled safety operations: a swim flag can only fly when enough certified guards are actually on their towers, a bacteria spike in the surf can close the water within minutes, and a rip current can force everyone out of the sea regardless of how sunny the afternoon is. This document specifies the Beach & Lifeguard Operations API, the system of record that ties these concerns together. It governs beach and zone posture (swim-flag and water-quality status), lifeguard shift and tower staffing, rescue and medical incident reporting with EMS handoff, water-quality sampling with bacteria advisories and closures, and parking and resident-pass issuance, culminating in a seasonal operational rollup per beach.

The system serves four operational roles that each own a distinct surface — a captain who runs the beach and its staffing, front-line lifeguards who work shifts and log incidents, public-health inspectors who sample the water and raise advisories, and parking clerks who issue passes — plus an unauthenticated public consumer that only reads. The recurring theme across every workflow is *reconciliation*: guard counts, available parking spaces, and zone posture are derived from underlying events and must stay consistent the instant those events occur. Because so much automatic state change cascades from a single operation (a guard clocking out can lower a swim flag; a closure advisory can cancel scheduled shifts), the specification below is precise about which action triggers which downstream effect.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are served under the `/beach-ops` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `BeachCaptain`, `Lifeguard`, `WaterQualityInspector`, `ParkingClerk`, and `Public`. When a recognized role attempts an operation its role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles map to identity as follows. When `X-User-Role` is `Lifeguard`, `X-User-ID` is the `id` of the acting `Lifeguard`; any ownership check on a resource that references a `Lifeguard` (for example a `Shift` or an `Incident` carrying a `lifeguard_id`) compares that foreign-key field to `X-User-ID`. When `X-User-Role` is `BeachCaptain`, `WaterQualityInspector`, `ParkingClerk`, or `Public`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Write operations are partitioned by role. A `BeachCaptain` owns beach, zone, tower, lifeguard, and shift-scheduling administration, may cancel shifts and create parking lots, and may drive the logical clock. A `Lifeguard` logs incidents and drives incident lifecycle, and clocks their own shifts through the duty states. A `WaterQualityInspector` records bacteria samples, issues advisories, and lifts them. A `ParkingClerk` issues and revokes parking passes and may create parking lots. Every role — including `Public` — may perform all read (GET) operations; `Public` may perform nothing else. Wherever this document lists "all roles" as authorized for a read, it means these five roles inclusive of `Public`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Immutable Records

Most resources — `Beach`, `Zone`, `Tower`, `Lifeguard`, `Shift`, `Incident`, `Advisory`, `ParkingLot`, and `ParkingPass` — carry a common set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it underpins optimistic concurrency (see §2.6).

One entity is deliberately different. A `WaterQualitySample` is an append-only, immutable event record: it carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because once recorded a sample is never changed. This is why samples accumulate as an audit trail from which advisories are later computed.

### 2.5. Request Validation Order and Error Precedence

Every request is screened through a fixed precedence so that failures surface deterministically. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then authorization against the acting role (`ERR_UNAUTHORIZED`, 403). Next, every identifier the request depends on — each id embedded in the path, then each foreign-key id in the body — must resolve to an existing row; identifiers are resolved left to right, and the first one that does not resolve yields `ERR_RESOURCE_NOT_FOUND` (404). A request whose path names a `shift_id`, `incident_id`, `sample_id`, `advisory_id`, `pass_id`, `lot_id`, `tower_id`, `zone_id`, `beach_id`, or `lifeguard_id` that does not exist is rejected here before any business rule runs. After existence, the body must parse and every required field must be present with a valid enum or numeric type, or the request fails with `ERR_INVALID_REQUEST` (400).

Only after those universal gates do domain-specific checks run, and they too follow a defined order wherever several can apply to the same operation. For scheduling a shift, the checks run in this sequence: the shift window is validated (`ERR_SHIFT_WINDOW_INVALID`, 422), then the tower must be online (`ERR_TOWER_OFFLINE`, 409), then the guard must not be double-booked (`ERR_LIFEGUARD_DOUBLE_BOOKED`, 409), and finally tower capacity is checked (`ERR_TOWER_CAPACITY_EXCEEDED`, 409). For raising a swim flag, the requested transition must first be legal for the zone's current posture (`ERR_INVALID_STATE`, 409), then no active closure may be in force (`ERR_ZONE_UNDER_CLOSURE`, 409), then the rip current must be safe (`ERR_RIP_CURRENT_UNSAFE`, 409), and finally the zone must be adequately staffed (`ERR_ZONE_UNDERSTAFFED`, 409). This ordering matters: a mid-flight closure surfaces as its own error rather than being masked by a later staffing check.

Any attempt to drive a state machine from a state that has no legal transition for the requested action is rejected with `ERR_INVALID_STATE` (409).

### 2.6. Optimistic Concurrency on Advisory Issuance

Issuing a water-quality advisory is the one write in this system guarded by optimistic concurrency, because issuing an advisory legitimately supersedes any prior active advisory for the zone and advances the zone's `version`. An advisory-issuance request must carry `expected_zone_version` as a required field, holding the `version` of the target `Zone` that the inspector last observed. If `expected_zone_version` does not equal the zone's current `version` — that is, another writer has advanced the zone since the inspector last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the inspector from acting on a stale view of the zone. No other endpoint takes a version field; only advisory issuance is OCC-guarded.

### 2.7. Derived Fields and Cascade Consistency

Several fields are never written directly by clients; the server recomputes them from underlying rows the moment a triggering event occurs, and the system's consistency model is immediate. A `Zone`'s `on_duty_guard_count` is derived from the shifts on the zone's towers. A `ParkingLot`'s `available_spaces` is derived from the lot's active passes. Whenever the server recomputes such a derived field or performs an automatic state transition on a resource, that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` increments by one. Cascades that cross entities — a clock-out that lowers a swim flag, a closure advisory that cancels scheduled shifts and closes the water — are described with their triggering workflow in §3, and each independently mutates every resource it touches.

### 2.8. Numeric Precision and Rounding

Monetary amounts are held as whole integer cents; wherever a fee or revenue line is computed, the result is rounded to the nearest integer cent using the round-half-up convention. Bacteria measurements (`enterococci_mpn`) are non-negative integers; when a geometric mean is computed it is rounded half-up to two decimal places, while a single-sample assessment carries the raw integer value. Shift coverage durations are expressed in whole minutes, taking the floor of the elapsed seconds divided by sixty. Guard counts and available-space counts are plain integers.

### 2.9. The Logical Clock

The server runs on a logical clock rather than wall-clock time. Its startup default is `2026-03-01T00:00:00Z`, and it never falls back to wall-clock time. An administrative test-driving capability lets a `BeachCaptain` set the clock to a supplied `to_iso8601` instant, advancing or rewinding it. All server-stamped times — `clock_in_at`, `clock_out_at`, an advisory's `issued_at`, a pass's `issued_at`, and the "now" used in geometric-mean windows, parking day-type selection, and actual-coverage duration — read from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Founding a Beach and Carving Out Zones

A `BeachCaptain` establishes a `Beach` by supplying its `name`, the owning municipality's `town_code`, and the inclusive season boundaries `season_start_date` and `season_end_date`, each written as `YYYY-MM-DD`. The season close must fall strictly after the season open; a `season_end_date` that is not later than `season_start_date` is rejected with `ERR_SEASON_DATES_INVALID` (422).

Within a beach, the captain carves out one or more `Zone` records, each created with its owning `beach_id`, a `name` such as "North Cove", and an optional `min_guards_required`. The `min_guards_required` value is the minimum number of on-duty guards the zone must have staffed before any swim flag may fly, and it defaults to 1 when omitted. A freshly created zone opens in a fixed posture: its `flag_status` is `RED`, its `water_status` is `OPEN`, its `rip_current_level` is `LOW`, and its `on_duty_guard_count` is 0. The `weather_note` field carries the free-text note from the most recent conditions update and is empty until one is posted.

A zone's posture spans two parallel dimensions. The `flag_status` enum takes `GREEN` (swim), `YELLOW` (caution), `RED` (no-swim on an otherwise open beach), or `BLACK` (hard closure). The `water_status` enum is either `OPEN` or `CLOSED` and is driven by water-quality closures rather than by the captain directly. The `rip_current_level` enum is `LOW`, `MODERATE`, or `HIGH`.

### 3.2. Towers and the Lifeguard Roster

A `BeachCaptain` adds a `Tower` to a zone by supplying the owning `zone_id`, a `label` such as "Tower 4", and an optional `max_concurrent_guards` that sets the tower's aggregate capacity — the maximum number of overlapping non-cancelled shifts permitted at any instant — defaulting to 2. A tower's `status` is `OPEN` on creation and toggles between `OPEN` and `OFFLINE`; the captain flips it by requesting the target status. An `OFFLINE` tower can be neither scheduled onto nor clocked into.

The captain also maintains the roster, registering each `Lifeguard` with a home `beach_id`, the guard's full `name`, a `certification_level` of `JUNIOR`, `SENIOR`, or `CAPTAIN`, and an `employee_ref` for payroll.

### 3.3. Staffing Shifts and the Duty Clock

Scheduling a `Shift` places a chosen guard on a tower over a planned window. A `BeachCaptain` creates the shift with the `lifeguard_id` of the guard, the `tower_id` of the staffed tower, and a `scheduled_start` and `scheduled_end` given as ISO 8601 UTC instants that bound a half-open interval `[start, end)`. The planned end must be strictly after the planned start, or the request fails with `ERR_SHIFT_WINDOW_INVALID` (422). A shift cannot be scheduled onto an `OFFLINE` tower — that yields `ERR_TOWER_OFFLINE` (409). Two scheduling constraints then protect people and capacity. The guard may not be double-booked: the new window must not overlap any other non-cancelled shift for the same guard, and because intervals are half-open, one shift ending exactly when another begins does not count as an overlap; a genuine overlap is rejected with `ERR_LIFEGUARD_DOUBLE_BOOKED` (409). Separately, the new shift must not push the count of concurrent non-cancelled shifts on its tower above that tower's `max_concurrent_guards` at any instant within its half-open interval, or it is rejected with `ERR_TOWER_CAPACITY_EXCEEDED` (409). A new shift begins in `SCHEDULED` status.

Each shift then runs through a duty lifecycle driven by the assigned guard, who submits an `action` naming the step. The guard clocks in, advancing the shift from `SCHEDULED` to `ON_DUTY`; this is refused when the tower is `OFFLINE` with `ERR_TOWER_OFFLINE`. On clock-in the server stamps `clock_in_at` from the logical clock and recomputes the zone's `on_duty_guard_count`, which rises by one. During duty the guard may take a break, moving `ON_DUTY` to `ON_BREAK`, and later resume, moving `ON_BREAK` back to `ON_DUTY`; a guard on break still counts toward staffing, so `on_duty_guard_count` is unchanged across both steps. The zone's `on_duty_guard_count` is defined at all times as the number of shifts on that zone's towers whose status is either `ON_DUTY` or `ON_BREAK`.

Clocking out ends the shift, moving it from either `ON_DUTY` or `ON_BREAK` to the terminal `OFF_DUTY`. The server stamps `clock_out_at` from the logical clock and recomputes the zone's `on_duty_guard_count`, which falls by one. This is the first link of an understaffing cascade: if the resulting `on_duty_guard_count` drops below the zone's `min_guards_required` while the zone's `flag_status` is `GREEN` or `YELLOW`, the server automatically forces `flag_status` down to `RED`, because a swim flag may not fly over an understaffed zone. A `BeachCaptain` may instead cancel a shift that is still `SCHEDULED`, moving it to the terminal `CANCELLED` and optionally recording a `cancel_reason`; scheduled shifts are also cancelled automatically by the water-closure cascade described in §3.5. `OFF_DUTY` and `CANCELLED` are both terminal.

### 3.4. Flag Posture, Conditions, and Swim Safety

Only a `BeachCaptain` sets a zone's swim flag, and the legal moves form a cycle. From `RED` the captain may raise the flag to `GREEN`; from `GREEN` to `YELLOW`; from `YELLOW` back to `GREEN`; and from either `GREEN` or `YELLOW` back down to `RED`. Lowering the flag to `RED` carries no safety preconditions. Raising a swim flag — that is, setting `flag_status` to `GREEN` or `YELLOW` — is gated by three safety checks applied uniformly to both target colors. First, the zone must not be under a hard closure: raising the flag requires the zone's `water_status` to be `OPEN` and no advisory of `CLOSURE` level to be `ACTIVE` for the zone, otherwise the raise is rejected with `ERR_ZONE_UNDER_CLOSURE` (409). Second, the `rip_current_level` must not be `HIGH`, or the raise is rejected with `ERR_RIP_CURRENT_UNSAFE` (409). Third, the zone's `on_duty_guard_count` must be at least its `min_guards_required`, or the raise is rejected with `ERR_ZONE_UNDERSTAFFED` (409). These checks run in the precedence given in §2.5.

The captain reports surf and weather through a conditions update carrying a new `rip_current_level` and an optional `weather_note`, which overwrites the zone's `weather_note`. Posting a `rip_current_level` of `HIGH` is itself a safety event: when a zone currently flying `GREEN` or `YELLOW` is updated to a `HIGH` rip current, the server sets `rip_current_level` to `HIGH` and forces the swim flag down to `RED` in the same operation.

### 3.5. Water Quality: Sampling, Advisories, and Closures

A `WaterQualityInspector` records surf bacteria readings as `WaterQualitySample` events, each tagging the sampled `zone_id`, the measured `enterococci_mpn` (a non-negative integer count in MPN per 100 mL), the `sampled_at` collection time, a `lab_ref`, and the collecting `technician`. Samples are immutable and simply accumulate; assessment happens later, when an advisory is issued.

Issuing an advisory is how bacteria data becomes an operational posture. The inspector requests a new `Advisory` for a zone, choosing a `basis` of either `SINGLE_SAMPLE` or `GEOMEAN_30DAY`, supplying the `expected_zone_version` that guards the write (see §2.6), and optionally a `reason` note. The server computes the advisory's `level` and `assessed_value` from the zone's samples according to the chosen basis. Under `SINGLE_SAMPLE`, the assessment uses the single most recent sample — the one with the latest `sampled_at`, breaking ties by the later `created_at` — and `assessed_value` is that sample's raw integer `enterococci_mpn`; because it rides on one reading, a lone spike can trip a closure. Under `GEOMEAN_30DAY`, the assessment gathers every sample whose `sampled_at` falls within the trailing thirty-day window ending at the current logical-clock instant, inclusive of both ends. If that window holds no samples, `assessed_value` is 0 and `level` is `NONE`; otherwise `assessed_value` is the geometric mean of those samples' `enterococci_mpn` values — the product of the readings raised to the power of one divided by the number of readings — rounded half-up to two decimal places. Because the geometric mean damps a single outlier, the same readings that would close the beach on a single sample can land merely at advisory level here.

The resulting `level` follows one threshold ladder for both bases. If `assessed_value` is at least 104, the level is `CLOSURE`. Otherwise, if `assessed_value` is at least 35 (and thus below 104), the level is `ADVISORY`. Below 35, the level is `NONE`.

Issuing an advisory carries several side effects, all committed together. The new advisory records its computed `level` and `assessed_value`, is stamped with an `issued_at` from the logical clock, and enters `ACTIVE` status. Any advisory for the same zone that was previously `ACTIVE` is moved to `SUPERSEDED`. The zone's `version` increments by one. And when the computed `level` is `CLOSURE`, a hard-closure cascade fires: the zone's `flag_status` is system-transitioned to `BLACK`, its `water_status` is set to `CLOSED`, and every shift still in `SCHEDULED` status on that zone's towers is moved to `CANCELLED`. A `BLACK` flag can be reached from `GREEN`, `YELLOW`, or `RED` by this closure event.

An inspector later lifts an advisory once conditions clear. Lifting is permitted only while the advisory is still `ACTIVE`; lifting anything else fails with `ERR_ADVISORY_NOT_ACTIVE` (409). On a successful lift the advisory moves to the terminal `LIFTED`, and if it was a `CLOSURE` advisory, the zone reopens: `water_status` returns to `OPEN`, the `flag_status` drops from `BLACK` to `RED` (a manual re-raise is then needed to fly a swim flag again), and the zone's `version` increments by one. `SUPERSEDED` and `LIFTED` are both terminal advisory states.

### 3.6. Incident Response and EMS Handoff

A `Lifeguard` logs an `Incident` against the `zone_id` where it happened, recording its `type` — one of `RESCUE`, `MEDICAL`, `LOST_CHILD`, or `FIRST_AID` — the `occurred_at` time, and a free-text `description`. The report may also carry a `severity` of `LOW`, `MODERATE`, or `CRITICAL` (defaulting to `LOW`), a `victim_count` of people involved (defaulting to 1), and the `lifeguard_id` of the responding guard. A new incident opens in `OPEN` status.

From `OPEN`, the responding guard drives the incident to one of three outcomes by naming an `action`. Resolving on scene moves it to `RESOLVED_ON_SCENE` and sets no EMS fields. Escalating to EMS moves it to `ESCALATED_EMS`, but only if the escalation payload supplies all four handoff details — `ems_hospital`, `ems_unit`, `ems_narrative`, and `ems_transported` — otherwise the escalation is rejected with `ERR_EMS_DETAILS_REQUIRED` (422); on success those four values are written onto the incident, where `ems_transported` records whether the patient was transported, `ems_hospital` the receiving hospital, `ems_unit` the responding EMS unit, and `ems_narrative` the handoff narrative. Reuniting a lost child moves the incident to `REUNITED`, but is allowed only when the incident's `type` is `LOST_CHILD`; attempting it on any other type is rejected with `ERR_INCIDENT_TYPE_MISMATCH` (422). From any of `RESOLVED_ON_SCENE`, `ESCALATED_EMS`, or `REUNITED`, the guard closes the incident, moving it to the terminal `CLOSED`.

### 3.7. Parking and Resident Passes

Parking capacity is organized into lots and passes. A `ParkingLot` is created under a beach — by a `ParkingClerk` or a `BeachCaptain` — with the owning `beach_id`, a `name`, the physical `total_spaces` capacity, and a base `daily_rate_cents`. Its `available_spaces` is a derived count, always equal to `total_spaces` minus the number of passes on the lot that are currently `ACTIVE`, and it starts equal to `total_spaces`.

A `ParkingClerk` issues a `ParkingPass` against a lot, supplying the `lot_id`, the vehicle `plate`, a `vehicle_type` of `CAR` or `OVERSIZED`, a `pass_type` of `DAILY` or `SEASON` (a `SEASON` pass being the resident/season badge), and an optional `is_resident` flag that defaults to false. A pass may be issued only when the lot has at least one available space, otherwise it is rejected with `ERR_LOT_FULL` (409). On issuance the server computes the `fee_cents`, decrements the lot's `available_spaces` by one, stamps `issued_at` from the logical clock, and sets the pass to `ACTIVE`.

The `fee_cents` computation depends on the pass type. First the day type is derived from the logical-clock date: it is a weekend if that date falls on Saturday or Sunday, and otherwise a weekday. For a `DAILY` pass, start from the lot's `daily_rate_cents` multiplied by the day-type factor — 1.5 on a weekend, 1.0 on a weekday — then add a surcharge of 2000 cents if the `vehicle_type` is `OVERSIZED` (and nothing otherwise); finally, if `is_resident` is true, apply a resident discount by multiplying the running amount by one-half (that is, take fifty percent off), and if not, apply no discount; the final amount is rounded half-up to whole cents. For a `SEASON` pass, the base is 15000 cents when `is_resident` is true and 30000 cents when it is false, plus an additional 5000 cents when the `vehicle_type` is `OVERSIZED`; the result is already in whole cents.

A clerk may revoke a pass that is currently `ACTIVE`, moving it to the terminal `REVOKED`; revoking a pass that is not `ACTIVE` fails with `ERR_PASS_NOT_ACTIVE` (409). Revocation is a compensating action: it increments the lot's `available_spaces` back up by one.

### 3.8. Seasonal Reporting

At any time, a `BeachCaptain` or a `Public` consumer may pull a computed seasonal rollup for a beach. The rollup is read-time only and mutates nothing. It reports the beach's operational totals: `total_incidents` counts all incidents in the beach's zones, `rescue_count` counts those of type `RESCUE`, and `ems_escalations` counts those that reached `ESCALATED_EMS`. `total_water_samples` counts every sample recorded across the beach's zones, and `active_closures` counts the zones currently under an `ACTIVE` `CLOSURE` advisory.

Two financial and staffing aggregates round out the report. `total_parking_revenue_cents` sums parking revenue across every `ACTIVE` pass whose lot belongs to the beach, and the rounding order is pinned: for each pass, its `fee_cents` is first grossed up by the town surcharge of 8.5 percent — multiplying by 1.085 and rounding that line half-up to whole cents — and only then are the per-pass lines summed; the surcharge is applied and rounded per pass before summation, never after. Coverage is reported two ways over the shifts whose tower's zone belongs to the beach. `scheduled_coverage_minutes` sums, over every shift that is not `CANCELLED`, the planned length `scheduled_end` minus `scheduled_start` expressed in whole minutes, counting planned schedule length regardless of whether the guard actually clocked in. `actual_coverage_minutes` sums, over every shift whose `clock_in_at` is set, the real clocked duration from `clock_in_at` to `clock_out_at` — or to the current logical-clock instant when the guard has not yet clocked out — again in whole minutes; a guard who clocked out early thus contributes fewer minutes than scheduled. Each duration is taken as the floor of its elapsed seconds divided by sixty.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state-machine transitions and the logical-clock control — return `200 OK`. Read operations return `200 OK`. "All roles" below denotes `BeachCaptain`, `Lifeguard`, `WaterQualityInspector`, `ParkingClerk`, and `Public`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/beach-ops/beaches` | Create a beach | BeachCaptain |
| GET | `/beach-ops/beaches/{beach_id}` | Get a beach | All roles |
| GET | `/beach-ops/beaches/{beach_id}/seasonal-report` | Computed seasonal rollup for the beach | BeachCaptain, Public |
| POST | `/beach-ops/zones` | Create a zone under a beach | BeachCaptain |
| GET | `/beach-ops/zones/{zone_id}` | Get a zone | All roles |
| GET | `/beach-ops/zones` | List zones (filterable by beach) | All roles |
| POST | `/beach-ops/zones/{zone_id}/flag` | Set zone swim flag | BeachCaptain |
| POST | `/beach-ops/zones/{zone_id}/conditions` | Post rip-current / weather conditions | BeachCaptain |
| POST | `/beach-ops/zones/{zone_id}/advisories` | Issue a water-quality advisory (OCC-guarded) | WaterQualityInspector |
| POST | `/beach-ops/towers` | Create a tower under a zone | BeachCaptain |
| GET | `/beach-ops/towers/{tower_id}` | Get a tower | All roles |
| GET | `/beach-ops/towers` | List towers (filterable by zone) | All roles |
| POST | `/beach-ops/towers/{tower_id}/status` | Set tower OPEN/OFFLINE | BeachCaptain |
| POST | `/beach-ops/lifeguards` | Create a lifeguard | BeachCaptain |
| GET | `/beach-ops/lifeguards/{lifeguard_id}` | Get a lifeguard | All roles |
| GET | `/beach-ops/lifeguards` | List lifeguards (filterable by beach) | All roles |
| POST | `/beach-ops/shifts` | Schedule a shift | BeachCaptain |
| GET | `/beach-ops/shifts/{shift_id}` | Get a shift | All roles |
| GET | `/beach-ops/shifts` | List shifts (filterable by lifeguard and/or tower) | All roles |
| POST | `/beach-ops/shifts/{shift_id}/transitions` | Drive shift lifecycle (CLOCK_IN, BREAK, RESUME, CLOCK_OUT, CANCEL) | Lifeguard, BeachCaptain |
| POST | `/beach-ops/incidents` | Log an incident | Lifeguard |
| GET | `/beach-ops/incidents/{incident_id}` | Get an incident | All roles |
| GET | `/beach-ops/incidents` | List incidents (filterable by zone and/or lifeguard) | All roles |
| POST | `/beach-ops/incidents/{incident_id}/transitions` | Drive incident lifecycle (RESOLVE_ON_SCENE, ESCALATE_EMS, REUNITE, CLOSE) | Lifeguard |
| POST | `/beach-ops/water-quality-samples` | Record a bacteria sample | WaterQualityInspector |
| GET | `/beach-ops/water-quality-samples/{sample_id}` | Get a sample | All roles |
| GET | `/beach-ops/water-quality-samples` | List samples (filterable by zone) | All roles |
| GET | `/beach-ops/advisories/{advisory_id}` | Get an advisory | All roles |
| GET | `/beach-ops/advisories` | List advisories (filterable by zone) | All roles |
| POST | `/beach-ops/advisories/{advisory_id}/lift` | Lift an ACTIVE advisory | WaterQualityInspector |
| POST | `/beach-ops/parking-lots` | Create a parking lot under a beach | ParkingClerk, BeachCaptain |
| GET | `/beach-ops/parking-lots/{lot_id}` | Get a parking lot | All roles |
| GET | `/beach-ops/parking-lots` | List parking lots (filterable by beach) | All roles |
| POST | `/beach-ops/parking-passes` | Issue a parking / resident pass | ParkingClerk |
| GET | `/beach-ops/parking-passes/{pass_id}` | Get a parking pass | All roles |
| GET | `/beach-ops/parking-passes` | List parking passes (filterable by lot) | All roles |
| POST | `/beach-ops/parking-passes/{pass_id}/revoke` | Revoke an ACTIVE parking pass | ParkingClerk |
| POST | `/_clock/set_current_utc` | Set the server logical clock | BeachCaptain |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SHIFT_WINDOW_INVALID` | 422 |
| `ERR_SEASON_DATES_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TOWER_OFFLINE` | 409 |
| `ERR_ADVISORY_NOT_ACTIVE` | 409 |
| `ERR_PASS_NOT_ACTIVE` | 409 |
| `ERR_ZONE_UNDER_CLOSURE` | 409 |
| `ERR_RIP_CURRENT_UNSAFE` | 409 |
| `ERR_INCIDENT_TYPE_MISMATCH` | 422 |
| `ERR_LIFEGUARD_DOUBLE_BOOKED` | 409 |
| `ERR_TOWER_CAPACITY_EXCEEDED` | 409 |
| `ERR_ZONE_UNDERSTAFFED` | 409 |
| `ERR_EMS_DETAILS_REQUIRED` | 422 |
| `ERR_LOT_FULL` | 409 |
