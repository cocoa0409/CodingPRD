# Flight Dispatch Release API — Product Requirements Document

## 1. Introduction

An airline's dispatch center carries a legal burden that few software systems share: no flight may depart until a licensed dispatcher and the pilot in command have jointly signed a dispatch release, and every operational decision made between scheduling and arrival must be reconstructible after the fact. This document specifies the Flight Dispatch Release API, the system of record for that dispatch center. It governs the full arc of a flight leg — reference data and desk staffing, leg creation and dispatcher assignment, flight planning with wind and fuel computation, payload and center-of-gravity verification, the joint-signature release cycle, en-route monitoring, and the delay, diversion, arrival, and cancellation decisions that close a leg out.

Two design commitments shape every workflow below. First, all operational authority is exercised against a server-maintained logical clock rather than wall-clock time, so that repair deadlines, shift windows, weather validity, and urgency weighting are deterministic and testable. Second, the dispatcher and the captain hold separate, non-transferable signature slots on every release, and the system structurally prevents one person from occupying both. All API resources are mounted under the `/dispatch` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts, conventions, and cross-cutting rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Dispatcher`, `Captain`, and `DispatchSupervisor`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the target endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity is bound to request headers as follows. When `X-User-Role` is `Dispatcher`, `X-User-ID` is the `id` of the acting `Dispatcher` entity; ownership checks on any resource that references a `Dispatcher` compare the resource's foreign-key field (such as a leg's `dispatcher_id` or a release's `dispatcher_id`) to `X-User-ID`, and a mismatch on an ownership-restricted operation is rejected with `ERR_NOT_ASSIGNED_DISPATCHER` (HTTP 403). When `X-User-Role` is `Captain`, `X-User-ID` is the `id` of the acting `Captain` entity; ownership checks compare the resource's `captain_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_ASSIGNED_CAPTAIN` (HTTP 403). When `X-User-Role` is `DispatchSupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on an `OperationalControlRecord`) but does not compare it to any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

The server maintains a single logical clock that drives every time-dependent rule in the system: desk-shift window derivation, desk occupancy counts, dispatcher urgency weighting, weather validity windows, MEL repair deadlines, and the MEL expiry sweep. At server startup the logical clock is set to exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time at any point afterward. A `DispatchSupervisor` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the new `current_utc`. Advancing the clock triggers the MEL expiry sweep described in §3.6 and re-derives every clock-dependent computed value, including each `DeskShift`'s derived `status`, each `Desk`'s `active_shift_count`, and the urgency tiers behind `weighted_load_score`.

### 2.5. Common Resource Properties

All primary resources — Station, Aircraft, Dispatcher, Captain, Desk, DeskShift, FlightLeg, FlightPlan, PayloadManifest, MelCdlItem, WeatherPackage, FlightRelease, and MonitoringEvent — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Two resources are deliberately lighter. A `ReleaseSignature` and an `OperationalControlRecord` each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these two append-only record types.

### 2.6. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, each guarding a parent entity whose state the writer must have observed:

- Creating a flight plan for a leg requires the request to carry `expected_leg_version`, a non-optional field holding the client last-observed `version` of the target FlightLeg. If the leg's current `version` has advanced beyond that value — for example because another plan was created or a delay was accepted in the meantime — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before superseding the leg's current plan.
- Replacing a weather package requires the request to carry `expected_station_version`, a non-optional field holding the client's last-observed `version` of the Station the target package belongs to. A mismatch with the station's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so a forecaster whose view of the station predates another publish or replace must re-read before superseding.

No endpoint other than these two accepts a version field; all other mutations are processed without an OCC check.

### 2.7. Precision, Rounding, and Units

All fuel and weight quantities are integer kilograms, and every rounding applied to them is decimal round-half-up to the nearest whole kilogram unless a calculation explicitly states otherwise. Planned trip time is an integer number of minutes, rounded half-up. Center of gravity is the single exception to whole-number output: `cg_percent_mac` is expressed in percent of mean aerodynamic chord with exactly two decimal places, rounded half-up. Several calculations keep an exact, unrounded intermediate value for downstream sums; where that rule applies, the workflow narrative in §3 says so explicitly, and the reader can assume that any field not described as "exact" is stored at its stated rounded precision.

### 2.8. Nested Resource Retrieval

Requests that target nested resources are validated strictly left-to-right along the path. The system confirms the existence of each path identifier in sequence and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before examining any later identifier or any body content. The same rule covers foreign-key references supplied in a request body — such as `leg_id`, `station_id`, `aircraft_id`, `dispatcher_id`, `captain_id`, `desk_id`, or `divert_station_id`: a reference to a resource that does not exist is rejected with `ERR_NOT_FOUND`.

### 2.9. Evaluation Order of Validation Rules

When a request violates more than one rule, the error returned is determined by a fixed evaluation order, not by whichever check happens to run first internally. The ordering is:

1. **Structural parse first.** A malformed body — a missing required field, a wrong-typed value, an unknown field, an invalid enum member, or a non-positive quantity — is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any other check runs.
2. **Authentication.** Missing or unknown `X-User-Role`, or a missing `X-User-ID`, yields `ERR_UNAUTHENTICATED`.
3. **Role and ownership.** A role outside the endpoint's authorized list yields `ERR_UNAUTHORIZED_ROLE`; on ownership-restricted operations, an entity-backed caller who is not the dispatcher or captain of record yields `ERR_NOT_ASSIGNED_DISPATCHER` or `ERR_NOT_ASSIGNED_CAPTAIN`.
4. **Existence.** Missing path identifiers or body foreign-key references yield `ERR_NOT_FOUND`, left-to-right per §2.8.
5. **Optimistic concurrency.** A stale `expected_leg_version` or `expected_station_version` yields `ERR_STALE_VERSION`.
6. **State-machine admissibility.** A target resource in the wrong from-state for the requested transition yields `ERR_INVALID_STATE`, `ERR_RELEASE_NOT_PENDING`, or `ERR_LEG_NOT_IN_FLIGHT` as the workflow specifies.
7. **Business safety.** Deferred-defect expiry, worst-case wind enforcement, captain qualification, dual-role segregation, and the rest buffer yield `ERR_MEL_ITEM_EXPIRED`, `ERR_WORST_CASE_REQUIRED`, `ERR_CAPTAIN_NOT_QUALIFIED`, `ERR_DUAL_ROLE_ASSIGNMENT`, or `ERR_REST_VIOLATION`.
8. **Uniqueness and cardinality.** Duplicate unique fields, duplicate manifests or releases per leg, plan-in-use blocking, duplicate signatures, shift overlap, and weather-window overlap yield `ERR_DUPLICATE_RESOURCE`, `ERR_MANIFEST_EXISTS`, `ERR_RELEASE_EXISTS`, `ERR_PLAN_IN_USE`, `ERR_DUPLICATE_SIGNATURE`, `ERR_SHIFT_OVERLAP`, or `ERR_WEATHER_WINDOW_OVERLAP`.
9. **Temporal well-formedness.** Malformed windows, invalid delay times, over-long repair deadlines, and missing active-shift coverage yield `ERR_WINDOW_INVALID`, `ERR_DELAY_INVALID_TIME`, `ERR_REPAIR_WINDOW_EXCEEDED`, or `ERR_NO_ACTIVE_SHIFT`.
10. **Referential prerequisites.** A plan that is not locked or a missing manifest yields `ERR_PLAN_NOT_LOCKED` or `ERR_MANIFEST_MISSING`.
11. **Fiscal and capacity economics, always last.** Weight, balance, fuel-capacity, alternate-pool, and workload checks yield `ERR_MZFW_EXCEEDED`, `ERR_MTOW_EXCEEDED`, `ERR_MLW_EXCEEDED`, `ERR_CG_OUT_OF_ENVELOPE`, `ERR_PAYLOAD_EXCEEDS_LIMIT`, `ERR_FUEL_EXCEEDS_CAPACITY`, `ERR_NO_SUITABLE_ALTERNATE`, `ERR_DISPATCHER_OVERLOADED`, `ERR_DESK_OVERLOADED`, `ERR_NO_DESK_AVAILABLE`, or `ERR_NO_DISPATCHER_AVAILABLE`. Within this level, the five manifest weight-and-balance checks of §3.4 run in a fixed order relative to one another wherever they are evaluated — manifest creation, manifest update, and release submission alike: the zero-fuel-weight check first (`ERR_MZFW_EXCEEDED`), then the takeoff-weight check (`ERR_MTOW_EXCEEDED`), then the landing-weight check (`ERR_MLW_EXCEEDED`), then the center-of-gravity check (`ERR_CG_OUT_OF_ENVELOPE`), and finally the payload check against `max_payload_kg` (`ERR_PAYLOAD_EXCEEDS_LIMIT`), so a request that violates several of them surfaces the earliest failure in that sequence.

Because of this ordering, a request that fails both a structural check and a fiscal check always surfaces the structural error; a request that fails both an authorization check and a weight check always surfaces the authorization error; and weight economics can never mask an earlier safety violation.

### 2.10. Joint Responsibility and the Two Signature Slots

A dispatch release becomes legally effective only when two distinct signature slots are filled: a `DISPATCHER` slot and a `CAPTAIN` slot. The slot a signing call occupies is derived entirely from the caller's `X-User-Role` — a `Dispatcher` caller can only ever fill the `DISPATCHER` slot, and a `Captain` caller can only ever fill the `CAPTAIN` slot. The `DispatchSupervisor` role has no signature authority whatsoever. Segregation of duties is enforced structurally: leg creation rejects a captain whose license number equals the assigned dispatcher's license number, so the same physical person can never hold both slots of the joint responsibility. Signature validity is additionally bound to the release's signature cycle, as §3.5 describes.

### 2.11. The Operational Control Audit Trail

Every consequential decision in the system appends an `OperationalControlRecord`, an append-only audit row scoped to a leg. Each record carries the `leg_id` it belongs to; a `release_id` naming the release the action pertains to, or null when the action does not concern a release; the `actor_role` of the actor, one of `Dispatcher`, `Captain`, `DispatchSupervisor`, or `system`; the `actor_id`, which is the caller's `X-User-ID` or the literal value `system`; an `action` drawn from the fixed enumeration `LEG_CREATED`, `DELAY_DECISION`, `CANCEL_DECISION`, `DEPARTURE`, `ARRIVAL`, `DIVERSION`, `RELEASE_CREATED`, `RELEASE_SUBMITTED`, `SIGNATURE_RECORDED`, `RELEASE_RECALLED`, `RELEASE_AMENDED`, `RELEASE_AUTO_AMENDED`, `DIVERT_RECOMMENDED`, and `MEL_EXPIRED`; the `from_status` and `to_status` bracketing the action where applicable, either of which may be null when not meaningful; a free-form `note` (used, for example, to carry a delay reason); and the `recorded_at_utc` logical-clock instant at which the record was written. The trail for a leg is listable in `created_at` ascending order with the standard pagination parameters, and records are never updated or deleted.

## 3. Business Logic & Workflows

### 3.1. Reference Data and Desk Staffing

Before any flight can be planned, a `DispatchSupervisor` seeds the operating environment. A **Station** is created with its unique `iata_code`, the `runway_length_m` of its longest available runway, the `alternate_distance_nm` measuring its distance from whichever arrival station is being planned for when it is evaluated as an alternate candidate, and the `min_ceiling_ft` and `min_visibility_m` that define the legal minima for releases naming it as destination. A station's `status` defaults to `OPEN` on creation and may be `CLOSED`; a `CLOSED` station is excluded from alternate selection and may not be used as a diversion target. Re-using an existing `iata_code` is rejected with `ERR_DUPLICATE_RESOURCE`. The station list supports an optional `status` filter alongside the standard pagination parameters.

An **Aircraft** profile captures the tail's unique `tail_no` and its `type_code` (for example `A320`), together with the certified limits that drive every weight check: `oew_kg`, `mzfw_kg`, `mtow_kg`, and `mlw_kg`. The fuel side is defined by `fuel_capacity_kg` and the performance pair `cruise_tas_kts` and `burn_kg_per_hour`, the latter being the base cruise burn at the reference zero-fuel weight. Runway compatibility comes from `min_runway_m`, and the center-of-gravity computation consumes `lemac_m` and `mac_m`. A duplicate `tail_no` is rejected with `ERR_DUPLICATE_RESOURCE`.

A **Dispatcher** is registered with a `name`, a unique `license_no` that doubles as the person's identity for segregation-of-duties checks, and an optional `max_active_legs` capacity that defaults to 6 when omitted. Two computed counters are exposed on read: `workload_leg_count`, the flat count of the dispatcher's legs whose `ops_status` is `SCHEDULED` or `DEPARTED`, and `weighted_load_score`, a departure-weighted sum over the same leg set in which a leg departing within two hours of the current clock contributes 3, a leg departing more than two and at most six hours out contributes 2, and any later leg contributes 1. Both counters start at 0 on creation. The two variants are deliberately distinct: a dispatcher holding one leg one hour from departure and another ten hours out shows a flat `workload_leg_count` of 2 but a `weighted_load_score` of 4.

A **Captain** is registered with a `name`, a unique `license_no`, and `qualified_type_codes`, the array of aircraft type codes the captain is type-rated on. A **Desk** is registered with a unique `code`, a `region`, and `max_dispatchers`, the maximum number of dispatchers whose shifts may cover any single instant at that desk. Reading a desk reports the computed `active_shift_count` — the number of shift rows whose window covers the current logical clock under half-open semantics (start inclusive, end exclusive) — and `free_slots`, which is `max_dispatchers` minus `active_shift_count`. Both start at 0 and `max_dispatchers` respectively on creation.

Staffing a desk means creating a **DeskShift** for a `dispatcher_id` over the window from `shift_start_utc` (inclusive) to `shift_end_utc` (exclusive). The window must be well-formed — the end strictly after the start — or the request is rejected with `ERR_WINDOW_INVALID`. Two shifts of the same dispatcher whose half-open windows intersect are rejected with `ERR_SHIFT_OVERLAP`, and two non-overlapping shifts of the same dispatcher separated by less than a thirty-minute rest buffer are rejected with `ERR_REST_VIOLATION`. Desk capacity is enforced at every covered instant: if accepting the shift would make the number of concurrent shifts at the desk exceed `max_dispatchers` at any moment of the window, the create is rejected with `ERR_DESK_OVERLOADED`. When `desk_id` is omitted, the server selects the desk itself: every desk whose `active_shift_count` is strictly below its `max_dispatchers` is eligible; eligible desks are ranked by the sum of the `weighted_load_score` values of the dispatchers currently holding an active shift there, ascending (an empty desk scores 0); ties break by desk `created_at` ascending, never by id. An empty eligibility pool is rejected with `ERR_NO_DESK_AVAILABLE`. A shift's `status` is never stored as input; it is derived from the logical clock: before `shift_start_utc` the shift is `PLANNED`, within the window it is `ACTIVE`, and at or after `shift_end_utc` it is `ENDED`. The shift list is filterable by `dispatcher_id` and `desk_id`.

### 3.2. Leg Creation and Dispatcher Assignment

A `Dispatcher` opens the operational record of a flight by creating a **FlightLeg** with its published `flight_no`, the `dep_station_id` and `arr_station_id`, the assigned `aircraft_id` and `captain_id`, the planned great-circle `distance_nm`, and the current `sched_dep_utc` and `sched_arr_utc`. A new leg is born with `ops_status` `SCHEDULED`, `monitor_status` `UNMONITORED`, `delay_count` 0, `actual_dep_utc` null, and `diverted_from_leg_id` null. Creation writes an `OperationalControlRecord` with action `LEG_CREATED`.

The dispatcher of record is resolved in one of two ways. When the caller supplies `dispatcher_id` explicitly, it must equal the caller's own identity, and if that dispatcher's `workload_leg_count` has already reached their `max_active_legs` — equality included, so at the limit the dispatcher is full — the assignment is rejected with `ERR_DISPATCHER_OVERLOADED`. When `dispatcher_id` is omitted, the server auto-selects: eligibility requires an `ACTIVE` desk shift whose window covers the current clock on any desk, plus a `workload_leg_count` strictly below the dispatcher's `max_active_legs`. Eligible dispatchers are ranked by `workload_leg_count` ascending, with ties broken by `weighted_load_score` ascending and then by dispatcher `created_at` ascending, never by id. If the pool is empty the create fails with `ERR_NO_DISPATCHER_AVAILABLE`.

Two safety checks complete creation. The named captain's `qualified_type_codes` must contain the aircraft's `type_code`, failing which the create is rejected with `ERR_CAPTAIN_NOT_QUALIFIED`. And the captain's `license_no` must differ from the dispatcher's `license_no`; equality means one person would hold both joint-responsibility slots and is rejected with `ERR_DUAL_ROLE_ASSIGNMENT`. The leg list supports filters on `dep_station_id`, `arr_station_id`, `aircraft_id`, `captain_id`, `dispatcher_id`, `ops_status`, and `diverted_from_leg_id` — the last of these serving as the reverse lookup that finds the continuation leg a diversion created.

### 3.3. Flight Planning: Wind, Fuel, and Alternate Selection

Planning a leg produces a **FlightPlan**. The creating dispatcher supplies the `leg_id`, a `route_code` string such as a direct-route specification, the `cruise_altitude_ft`, the `forecast_wind_kts` (the forecast average wind component, positive for a tailwind), and a `wind_assumption` of either `FORECAST` or `WORST_CASE`. The request must also carry `expected_leg_version` per §2.6. Each plan receives a per-leg monotone `plan_seq` starting at 1 and incrementing on every new plan for the leg, and is born in `COMPUTED` status. Creating a plan supersedes the leg's prior non-superseded plans: any earlier `COMPUTED` or `LOCKED` plan of the same leg transitions to `SUPERSEDED`. There is one hard exception — when a non-terminal release still references the leg's `LOCKED` plan, the supersede path is closed and plan creation is rejected with `ERR_PLAN_IN_USE`. A successful creation also increments the leg's `version` by one.

Wind handling is pinned. Under `FORECAST`, the effective wind component is the client-supplied `forecast_wind_kts`. Under `WORST_CASE`, the forecast is ignored entirely and a 50-knot headwind is assumed, so ground speed is the aircraft's `cruise_tas_kts` minus 50; for identical legs this yields strictly more trip fuel than the forecast variant whenever `forecast_wind_kts` is greater than minus 50. The worst-case variant is mandatory, not optional, in one situation: when any `OPEN` deferred defect on the aircraft carries a `fuel_penalty_pct` greater than zero, creating a plan with `wind_assumption` `FORECAST` is rejected with `ERR_WORST_CASE_REQUIRED`.

Fuel computation proceeds in stages. First the **weight-adjusted burn**: the reference zero-fuel weight is the aircraft's `oew_kg` plus the leg manifest's `total_payload_kg` when a manifest exists, or just `oew_kg` otherwise. That reference is divided into whole 10,000-kilogram steps, rounding any fraction up to the next step — exactly 50,000 kg is five steps, while 50,001 kg is six. The effective burn is the aircraft's `burn_kg_per_hour` increased by one percent per step, rounded half-up to a whole kilogram per hour and exposed as `burn_eff_kg_per_hour`.

Next, **trip fuel**. The `ground_speed_kts` is the `cruise_tas_kts` plus the effective wind component for the chosen assumption. The `trip_time_min` is the `distance_nm` divided by `ground_speed_kts`, converted from hours to minutes, and rounded half-up to a whole minute. The exact trip fuel is the flight time in hours multiplied by the exact effective burn. The plan exposes `trip_fuel_kg`, the round-half-up of that exact value, and `mel_fuel_penalty_kg`, the round-half-up of the exact trip fuel multiplied by the sum of `fuel_penalty_pct` over all `OPEN` deferred defects on the aircraft, divided by 100. The penalized exact trip fuel — the exact trip fuel grown by that same percentage — is kept unrounded for the next stage.

Then, **required fuel**. The `contingency_kg` is the round-half-up of the larger of two quantities: five percent of the penalized exact trip fuel, or a floor of 100 kg. The `alternate_fuel_kg` is the round-half-up of the selected alternate's `alternate_distance_nm` divided by `cruise_tas_kts` and multiplied by the exact effective burn. The `final_reserve_kg` is the round-half-up of the exact effective burn flown for half an hour. Finally, `required_fuel_kg` is a single round-half-up applied to the sum of the penalized exact trip fuel, the exact contingency, the exact alternate fuel, and the exact reserve — exactly one rounding at the final sum, with no intermediate rounded values feeding it.

The **alternate selection** runs as part of every plan computation. A station is eligible only if its `status` is `OPEN`, it is neither the leg's departure nor arrival station, its `alternate_distance_nm` is at most 200 nautical miles, and its `runway_length_m` is at least the aircraft's `min_runway_m`. Eligible stations are ranked by `alternate_distance_nm` ascending, with ties broken by station `created_at` ascending, never by id. The winner becomes the plan's `alternate_station_id`. An empty pool rejects the plan creation outright with `ERR_NO_SUITABLE_ALTERNATE`. The plan list is filterable by `leg_id` and `alternate_station_id`.

A `COMPUTED` plan becomes `LOCKED` when the dispatcher assigned to the plan's leg locks it — any other caller is rejected with `ERR_NOT_ASSIGNED_DISPATCHER`. Locking re-verifies the destination environment: an `ACTIVE` weather package for the arrival station must cover the current `sched_arr_utc` (`ERR_WEATHER_NOT_CURRENT` when none does); that package's ceiling and visibility must meet the arrival station's minima, raised by the MEL bump described in §3.6 when any `OPEN` defect with `minima_bump` exists on the aircraft (`ERR_WEATHER_BELOW_MINIMA` otherwise); and the plan's `required_fuel_kg` must not exceed the aircraft's `fuel_capacity_kg` (`ERR_FUEL_EXCEEDS_CAPACITY`).

A `LOCKED` plan returns to `COMPUTED` through recompute, which the dispatcher assigned to the plan's leg may trigger manually — any other caller is rejected with `ERR_NOT_ASSIGNED_DISPATCHER` — and which the weather-revalidation cascade of §3.7 also triggers automatically. Recompute re-derives every computed field — ground speed, trip time, burn, trip fuel, MEL penalty, contingency, alternate fuel, reserve, required fuel, and the alternate itself — against the current set of `OPEN` deferred defects and the current alternate pool, while keeping the stored `route_code`, `cruise_altitude_ft`, `forecast_wind_kts`, and `wind_assumption` inputs unchanged. One input does float: the weight reference behind the effective burn now uses the current manifest's `total_payload_kg` when a manifest exists, so a manifest filed after the first compute changes `burn_eff_kg_per_hour` on the next recompute.

### 3.4. The Payload Manifest: Weight, Balance, and Center of Gravity

Load planning for a leg produces a **PayloadManifest**, created by a dispatcher with the `leg_id`, the `pax_count`, the `bags_count`, and the `cargo_kg` (which may carry one decimal). Two referential gates guard creation: the leg's current non-superseded plan must be `LOCKED` (`ERR_PLAN_NOT_LOCKED` otherwise), and a leg carries at most one manifest, so a second create is rejected with `ERR_MANIFEST_EXISTS`. At write time the manifest pins `plan_id` to that locked plan, freezing the fuel figures its weight checks run against.

The weight rollup is component-first, and the order matters. The `pax_weight_kg` is the round-half-up of `pax_count` times 87.5 kg per passenger; the `baggage_kg` is the round-half-up of `bags_count` times 12.5 kg per bag; the `cargo_billed_kg` is the round-half-up of `cargo_kg`. The `total_payload_kg` is then the sum of those three already-rounded components — so one passenger, one bag, and 0.4 kg of cargo total 101 kg, not 100. From there, the `zero_fuel_weight_kg` is the aircraft's `oew_kg` plus `total_payload_kg`; the `takeoff_weight_kg` is the zero-fuel weight plus the pinned plan's `required_fuel_kg`; and the `landing_weight_kg` is the takeoff weight minus the pinned penalized trip fuel, that is, the pinned plan's `trip_fuel_kg` plus its `mel_fuel_penalty_kg`.

Four fiscal checks guard every manifest write: `zero_fuel_weight_kg` must not exceed `mzfw_kg` (`ERR_MZFW_EXCEEDED`), `takeoff_weight_kg` must not exceed `mtow_kg` (`ERR_MTOW_EXCEEDED`), `landing_weight_kg` must not exceed `mlw_kg` (`ERR_MLW_EXCEEDED`), and `total_payload_kg` must not exceed `max_payload_kg` — where equality is accepted, so a payload exactly at the limit passes (`ERR_PAYLOAD_EXCEEDS_LIMIT` only when strictly above).

The `max_payload_kg` envelope is a single-pass computation, deliberately pinned against circularity. It takes the smallest of three structural ceilings — `mzfw_kg` minus `oew_kg`; `mtow_kg` minus `oew_kg` minus the pinned plan's `required_fuel_kg`; and `mlw_kg` minus `oew_kg` minus the pinned plan's fuel still on board at landing, which is `required_fuel_kg` less `trip_fuel_kg` less `mel_fuel_penalty_kg` — and then subtracts the sum of `payload_penalty_kg` over all `OPEN` deferred defects on the aircraft. The fuel figures in this envelope come only from the pinned locked plan; changing the payload never re-derives fuel inside this calculation, and the only way to refresh the fuel figures is an explicit plan recompute and re-lock.

Balance is verified through `cg_percent_mac`. A total moment is formed by weighting each component at its standard arm: the operating empty weight at 18.0, `pax_weight_kg` at 17.6, `baggage_kg` at 18.4, `cargo_billed_kg` at 19.5, and the pinned plan's `required_fuel_kg` at 18.1. The balance arm is that moment divided by `takeoff_weight_kg`, and the center of gravity is the arm's offset from `lemac_m` expressed as a percentage of `mac_m`, rounded half-up to two decimal places. The acceptable envelope normally runs from 20.0 to 31.0 percent inclusive; when any `OPEN` deferred defect of `category` `CDL` exists on the aircraft, the envelope narrows to 22.0 through 30.0 inclusive. A center of gravity outside the applicable envelope is rejected with `ERR_CG_OUT_OF_ENVELOPE`, while a value exactly on either bound is accepted.

A manifest may be updated with new `pax_count`, `bags_count`, or `cargo_kg` values. The update re-runs the rollup, the envelope, and the center-of-gravity checks against the leg's current `LOCKED` plan and re-pins `plan_id` to it; if the leg's current plan is not locked, the update is rejected with `ERR_PLAN_NOT_LOCKED`. The manifest list is filterable by `leg_id` and `plan_id`.

### 3.5. The Dispatch Release and the Joint Signature Cycle

With a locked plan and a manifest in place, a dispatcher opens a **FlightRelease** for the leg by supplying its `leg_id`. Creation requires the leg's plan to be `LOCKED` (`ERR_PLAN_NOT_LOCKED` otherwise) and a manifest to exist for the leg (`ERR_MANIFEST_MISSING` otherwise), and at most one non-terminal release may exist per leg — a second open attempt is rejected with `ERR_RELEASE_EXISTS`. The release snapshots its accountability at creation: `plan_id` names the locked plan it was created against, while `dispatcher_id` and `captain_id` are copied from the leg and name the two accountable officers from that moment on. A new release starts in `DRAFT` status with `cycle_seq` 1 and `amendment_count` 0, and creation writes an `OperationalControlRecord` with action `RELEASE_CREATED`. The release list is filterable by `leg_id`, `plan_id`, `dispatcher_id`, and `captain_id`.

Submitting moves a `DRAFT` release — or an `UNDER_AMENDMENT` one, with every check re-evaluated against the current world state — to `PENDING_SIGNATURES`. Only the dispatcher of record may submit (`ERR_NOT_ASSIGNED_DISPATCHER` otherwise), and submission re-validates the entire safety envelope: the release's `plan_id` must still refer to a `LOCKED` plan (`ERR_PLAN_NOT_LOCKED`); a manifest must exist for the leg (`ERR_MANIFEST_MISSING`) and all four weight checks plus the payload check of §3.4 must pass against the pinned plan (`ERR_MZFW_EXCEEDED`, `ERR_MTOW_EXCEEDED`, `ERR_MLW_EXCEEDED`, `ERR_CG_OUT_OF_ENVELOPE`, `ERR_PAYLOAD_EXCEEDS_LIMIT`); no deferred defect on the leg's aircraft may be `EXPIRED` (`ERR_MEL_ITEM_EXPIRED`); an `ACTIVE` weather package must cover the current `sched_arr_utc` at the arrival station and meet its minima including any MEL bump (`ERR_WEATHER_NOT_CURRENT`, `ERR_WEATHER_BELOW_MINIMA`); the captain must be type-qualified for the aircraft (`ERR_CAPTAIN_NOT_QUALIFIED`); and the plan's `required_fuel_kg` must fit within `fuel_capacity_kg` (`ERR_FUEL_EXCEEDS_CAPACITY`). A successful submission writes a `RELEASE_SUBMITTED` record.

Signing is the joint act. Either accountable officer signs with an optional free-text `statement`; the release must be in `PENDING_SIGNATURES` or the attempt is rejected with `ERR_RELEASE_NOT_PENDING`, and no `EXPIRED` defect may exist on the aircraft (`ERR_MEL_ITEM_EXPIRED`). Each signing appends a **ReleaseSignature** recording the `release_id`, the `signer_role` derived from the caller's role (`DISPATCHER` for a `Dispatcher` caller, `CAPTAIN` for a `Captain` caller), the `signer_id` taken from the caller's `X-User-ID`, the release's `cycle_seq` at signing time, and the `signed_at_utc` logical-clock instant. A captain caller must be the release's `captain_id` and a dispatcher caller its `dispatcher_id` (`ERR_NOT_ASSIGNED_CAPTAIN`, `ERR_NOT_ASSIGNED_DISPATCHER`); no one may sign a slot that is not theirs. A signature is valid only while its recorded `cycle_seq` equals the release's current `cycle_seq`; the moment the cycle advances, every earlier signature goes stale. Signing the same slot twice within one cycle is rejected with `ERR_DUPLICATE_SIGNATURE`. When both slots hold valid signatures for the current cycle, the release transitions to `RELEASED` — the moment joint responsibility attaches — and each signing writes a `SIGNATURE_RECORDED` record. The signature list of a release is append-only and readable with standard pagination.

A `PENDING_SIGNATURES` release may be recalled to `DRAFT` by the dispatcher of record; recall increments `cycle_seq` by one, which is precisely what invalidates the signatures already collected, and writes a `RELEASE_RECALLED` record. A `RELEASED` release may be amended by the dispatcher of record, moving it to `UNDER_AMENDMENT` with `cycle_seq` incremented by one, `amendment_count` incremented by one, and a `RELEASE_AMENDED` record written; amendment likewise invalidates the existing signatures, so an amended release must pass through submission and a fresh dual signature before it is effective again.

A release reaches its terminal states in two ways. When the leg arrives, a `RELEASED` release transitions to `CLOSED`. When the leg is cancelled or diverted, any non-terminal release — `DRAFT`, `PENDING_SIGNATURES`, `UNDER_AMENDMENT`, and in the diversion case `RELEASED` as well — transitions to `CANCELLED`. Terminal states are locked: no further transitions occur from `CANCELLED` or `CLOSED`.

### 3.6. MEL/CDL Deferrals and the Repair Clock

A `DispatchSupervisor` records a deferred defect as a **MelCdlItem** on an `aircraft_id`, with an `item_code` reference, a `category` of `MEL` or `CDL`, a `deferral_category` repair interval class, and a `repair_deadline_utc`. The deferral class bounds the deadline from the creation clock: class `A` allows at most one day, `B` at most three days, `C` at most ten days, and `D` at most thirty days; a deadline beyond its class interval is rejected with `ERR_REPAIR_WINDOW_EXCEEDED`. Three operational penalties are optional on creation: `fuel_penalty_pct` (default 0), the percent by which trip fuel grows while the item is open; `payload_penalty_kg` (default 0), subtracted from the payload envelope while open; and `minima_bump` (default false), which while open raises the destination weather minima required of any release by 200 feet of ceiling and 500 meters of visibility. A new item starts `OPEN`. The item list is filterable by `aircraft_id` and `status`.

Clearing an open item — the repair is accomplished — transitions it from `OPEN` to `CLEARED`; from that point on it contributes no fuel penalty, no payload penalty, and no minima bump to any calculation.

The repair clock is enforced by the expiry sweep, which runs whenever the logical clock is advanced. Every item still `OPEN` whose `repair_deadline_utc` lies before the new clock becomes `EXPIRED`, processed in `repair_deadline_utc` ascending order with ties broken by `created_at` ascending, never by id; `CLEARED` items are never touched by the sweep. Expiry cascades into the release world: for every leg flying that aircraft whose `ops_status` is `SCHEDULED` or `DEPARTED`, a release in `RELEASED` moves to `UNDER_AMENDMENT` with `cycle_seq` and `amendment_count` each incremented by one, and a release in `PENDING_SIGNATURES` rolls back to `DRAFT` with `cycle_seq` incremented by one — in both cases invalidating collected signatures, and with each auto-amended or rolled-back release writing a `RELEASE_AUTO_AMENDED` record. Each affected leg also receives an `OperationalControlRecord` with action `MEL_EXPIRED`. And while any `EXPIRED` item exists on an aircraft, release submission, release signing, and departure for legs of that aircraft are all rejected with `ERR_MEL_ITEM_EXPIRED`.

### 3.7. Weather Currency and Revalidation Cascades

A `DispatchSupervisor` publishes a **WeatherPackage** for a `station_id` covering the half-open window from `valid_from_utc` (inclusive) to `valid_to_utc` (exclusive), carrying the `ceiling_ft` and `visibility_m` of the observation or forecast. The window must be well-formed — `valid_to_utc` strictly after `valid_from_utc` — or the publish is rejected with `ERR_WINDOW_INVALID`. Among one station's `ACTIVE` packages, windows must never intersect, though adjacency is allowed: a new window beginning exactly where another ends is legal, while any true overlap is rejected with `ERR_WEATHER_WINDOW_OVERLAP`. A new package starts `ACTIVE`, and publishing one increments the station's `version` by one.

When a forecast is corrected, the supervisor replaces a package rather than editing it. The replacement supplies fresh `valid_from_utc`, `valid_to_utc`, `ceiling_ft`, and `visibility_m` values plus `expected_station_version` per §2.6. The target package transitions from `ACTIVE` to `SUPERSEDED`, the replacement is created `ACTIVE`, the station's `version` increments by one, and overlap is validated against the station's other `ACTIVE` packages with the replaced package itself excluded from the check.

Replacement triggers the **weather revalidation cascade**. For every `LOCKED` plan whose leg arrives at the replaced station, considered in plan `created_at` ascending order (never by id), the system re-checks that an `ACTIVE` package covers the leg's current `sched_arr_utc` and meets the arrival minima. When the check fails, the cascade runs three hops deep: the plan drops from `LOCKED` back to `COMPUTED`; any release referencing that plan moves from `RELEASED` to `UNDER_AMENDMENT` or from `PENDING_SIGNATURES` to `DRAFT`, with `cycle_seq` incremented by one in either case and `amendment_count` incremented by one when the release came from `RELEASED`; and the cycle increment invalidates the release's collected signatures. Each cascaded release writes a `RELEASE_AUTO_AMENDED` record. The package list is filterable by `station_id`.

### 3.8. En-Route Operations: Delay, Departure, Monitoring, Diversion, and Closure

Once a leg is scheduled, its operational life is a sequence of decisions, each appended to the audit trail.

A **delay decision** by the assigned dispatcher supplies `new_dep_utc`, `new_arr_utc`, and a `reason_code`. The new departure must be strictly after the current `sched_dep_utc`, and the new arrival strictly after the new departure; violations are rejected with `ERR_DELAY_INVALID_TIME`. An accepted delay updates `sched_dep_utc` and `sched_arr_utc`, increments `delay_count` by one, increments the leg's `version` by one, and writes a `DELAY_DECISION` record carrying the reason. Delay also triggers the auto-amendment rule: when the push in whole minutes is at least sixty — exactly sixty triggers; fifty-nine does not — and the leg's release is currently `RELEASED`, the release moves to `UNDER_AMENDMENT` with `cycle_seq` and `amendment_count` each incremented by one and a `RELEASE_AUTO_AMENDED` record written. The chain is three links long: the delay mutates the leg, the release auto-amends, and the cycle increment invalidates the release's existing signatures.

**Departure** moves a leg from `SCHEDULED` to `DEPARTED`. Only the assigned dispatcher may mark it (`ERR_NOT_ASSIGNED_DISPATCHER`); a release for the leg must exist in `RELEASED` status (`ERR_INVALID_STATE` otherwise); an `ACTIVE` desk shift for the leg's dispatcher must cover the current clock on some desk (`ERR_NO_ACTIVE_SHIFT`); and no `EXPIRED` deferred defect may exist on the aircraft (`ERR_MEL_ITEM_EXPIRED`). Departure stamps `actual_dep_utc` with the current clock, moves `monitor_status` from `UNMONITORED` to `MONITORING`, and writes a `DEPARTURE` record.

While airborne, the dispatcher of record files **MonitoringEvents** — position and fuel reports carrying `fuel_remaining_kg`, the current `eta_destination_utc`, and optionally the latest `dest_ceiling_ft` and `dest_visibility_m`, which may be omitted when unchanged and are then treated as above minima. Filing an event for a leg that is not `DEPARTED` is rejected with `ERR_LEG_NOT_IN_FLIGHT`. Each event computes a fuel picture against the plan pinned by the leg's release: the remaining estimate is the exact effective burn of that plan multiplied by the hours from the current clock to `eta_destination_utc`; the `projected_arrival_fuel_kg` is the round-half-up of `fuel_remaining_kg` minus that estimate; and the `fuel_margin_kg` is the projection minus the pinned plan's `final_reserve_kg`. The fuel recommendation follows fixed thresholds: a margin of at least 500 kg yields `NONE`; a margin of zero or more but under 500 yields `CONSIDER_DIVERT`; a negative margin yields `RECOMMEND_DIVERT` — a margin of exactly 500 is `NONE`, exactly 0 is `CONSIDER_DIVERT`. Independently, weather can force escalation: when the reported destination ceiling is below the required ceiling or the reported visibility below the required visibility — where "required" means the arrival station's `min_ceiling_ft` and `min_visibility_m` raised by the MEL bump when an `OPEN` `minima_bump` defect exists on the aircraft — the weather recommendation is `RECOMMEND_DIVERT`, and `NONE` otherwise. The event's `recommendation` is the more severe of the two, with `NONE` below `CONSIDER_DIVERT` below `RECOMMEND_DIVERT`. A new event starts `OPEN`; a recommendation of `CONSIDER_DIVERT` or `RECOMMEND_DIVERT` moves the leg's `monitor_status` from `MONITORING` to `ALERTED`, and a `RECOMMEND_DIVERT` additionally writes a `DIVERT_RECOMMENDED` record. The event list is filterable by `leg_id`.

Acknowledging an event, done by the dispatcher assigned to the event's leg (`ERR_NOT_ASSIGNED_DISPATCHER`), moves the event from `OPEN` to `ACKNOWLEDGED` — an event not currently `OPEN` is rejected with `ERR_INVALID_STATE`. Acknowledgement de-escalates the leg only when it clears the board: the leg's `monitor_status` returns from `ALERTED` to `MONITORING` only if, after this acknowledgement, no other event for the same leg remains `OPEN` with a recommendation other than `NONE`.

**Arrival** moves a `DEPARTED` leg to `ARRIVED`, again restricted to the assigned dispatcher. Arrival moves `monitor_status` to `CLOSED`, closes a `RELEASED` release by moving it to `CLOSED` (a release in any other non-terminal state is instead `CANCELLED`), drops the leg from the dispatcher's `workload_leg_count` and `weighted_load_score`, and writes an `ARRIVAL` record.

**Diversion** is the joint prerogative of dispatcher and captain: either may initiate it, and it applies only to a leg currently `DEPARTED` — a diversion attempt on a leg in any other state is rejected with `ERR_INVALID_STATE`. The `divert_station_id` must reference a station whose `status` is `OPEN` (`ERR_INVALID_STATE` for a closed one) and must differ from both the leg's `arr_station_id` and its `dep_station_id` (`ERR_INVALID_REQUEST` otherwise); the request also carries the continuation's `distance_nm`, `sched_dep_utc`, `sched_arr_utc`, and a `reason_code`. Diversion moves the leg to `DIVERTED` and its `monitor_status` to `CLOSED`, cancels any non-terminal release on the leg — including one that is `RELEASED` — and creates a continuation leg: `ops_status` `SCHEDULED`, `monitor_status` `UNMONITORED`, `diverted_from_leg_id` pointing back to the diverted leg, `dep_station_id` set to the diversion target, `arr_station_id`, `aircraft_id`, `captain_id`, and `dispatcher_id` copied from the diverted leg, and the schedule and distance taken from the request. A `DIVERSION` record is written on both legs, and the response presents the continuation leg.

**Cancellation** moves a `SCHEDULED` leg to `CANCELLED` at the assigned dispatcher's hand, taking a `reason_code`. Cancellation cancels any non-terminal release on the leg, drops the leg from the dispatcher's workload counters, and writes a `CANCEL_DECISION` record. The terminal states `ARRIVED`, `DIVERTED`, and `CANCELLED` admit no further operational transitions.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — including the continuation leg produced by a diversion and the replacement produced by a weather-package replace — return `201 Created`. Operations that modify an existing resource in place, including state transitions such as lock, submit, sign, delay, depart, arrive, and acknowledge, return `200 OK`. All resources are mounted under the `/dispatch` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dispatch/stations` | Create a Station | DispatchSupervisor |
| GET | `/dispatch/stations/{stationId}` | Get a Station | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/stations` | List Stations with pagination and optional status filter | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/aircraft` | Create an Aircraft | DispatchSupervisor |
| GET | `/dispatch/aircraft/{aircraftId}` | Get an Aircraft | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/dispatchers` | Create a Dispatcher | DispatchSupervisor |
| GET | `/dispatch/dispatchers/{dispatcherId}` | Get a Dispatcher (includes computed workload fields) | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/captains` | Create a Captain | DispatchSupervisor |
| GET | `/dispatch/captains/{captainId}` | Get a Captain | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/desks` | Create a Desk | DispatchSupervisor |
| GET | `/dispatch/desks/{deskId}` | Get a Desk (includes computed active_shift_count and free_slots at the current clock) | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/desk-shifts` | Assign a dispatcher to a desk for a shift window; desk_id omitted triggers server desk selection | DispatchSupervisor |
| GET | `/dispatch/desk-shifts/{shiftId}` | Get a DeskShift | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/desk-shifts` | List DeskShifts, filterable by dispatcher_id and/or desk_id | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/legs` | Create a FlightLeg (SCHEDULED / UNMONITORED); dispatcher_id omitted triggers server dispatcher selection | Dispatcher |
| GET | `/dispatch/legs/{legId}` | Get a FlightLeg | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/legs` | List FlightLegs with pagination and foreign-key filters (including continuation-leg lookup via diverted_from_leg_id) | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/legs/{legId}/delay` | Delay decision: push the schedule out; a push of at least the review threshold auto-amends a RELEASED release | Dispatcher |
| POST | `/dispatch/legs/{legId}/cancel` | Cancel decision: leg SCHEDULED to CANCELLED; cascades to the release | Dispatcher |
| POST | `/dispatch/legs/{legId}/depart` | Mark departure; requires a RELEASED release and an ACTIVE shift for the assigned dispatcher | Dispatcher |
| POST | `/dispatch/legs/{legId}/arrive` | Mark arrival at destination | Dispatcher |
| POST | `/dispatch/legs/{legId}/divert` | Joint dispatcher/captain diversion decision; creates the continuation leg | Dispatcher, Captain |
| POST | `/dispatch/plans` | Create and compute a FlightPlan for a leg (OCC on the leg); supersedes prior non-superseded plans | Dispatcher |
| GET | `/dispatch/plans/{planId}` | Get a FlightPlan | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/plans` | List FlightPlans, filterable by leg_id / alternate_station_id | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/plans/{planId}/lock` | Lock a COMPUTED plan (validates destination weather, minima, fuel capacity) | Dispatcher |
| POST | `/dispatch/plans/{planId}/recompute` | Re-derive a LOCKED plan against current weather, MEL, and manifest state (LOCKED to COMPUTED) | Dispatcher |
| POST | `/dispatch/manifests` | Create the payload manifest for a leg (requires a LOCKED plan; one per leg) | Dispatcher |
| GET | `/dispatch/manifests/{manifestId}` | Get a PayloadManifest | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/manifests` | List PayloadManifests, filterable by leg_id / plan_id | Dispatcher, Captain, DispatchSupervisor |
| PUT | `/dispatch/manifests/{manifestId}` | Update manifest load figures; re-runs weight and CG checks against the current LOCKED plan and re-pins plan_id | Dispatcher |
| POST | `/dispatch/mel-items` | Defer an MEL/CDL item on an aircraft | DispatchSupervisor |
| GET | `/dispatch/mel-items/{itemId}` | Get a MelCdlItem | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/mel-items` | List MelCdlItems, filterable by aircraft_id / status | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/mel-items/{itemId}/clear` | Clear an OPEN deferral (repair accomplished) | DispatchSupervisor |
| POST | `/dispatch/weather-packages` | Publish a weather package for a station; half-open windows of ACTIVE packages must not overlap | DispatchSupervisor |
| GET | `/dispatch/weather-packages/{packageId}` | Get a WeatherPackage | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/weather-packages` | List WeatherPackages, filterable by station_id | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/weather-packages/{packageId}/replace` | Replace (supersede) a package with a corrected forecast (OCC on the station); runs weather revalidation | DispatchSupervisor |
| POST | `/dispatch/releases` | Open a dispatch release for a leg (DRAFT); snapshots dispatcher, captain, and plan | Dispatcher |
| GET | `/dispatch/releases/{releaseId}` | Get a FlightRelease | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/releases` | List FlightReleases, filterable by leg_id / plan_id / dispatcher_id / captain_id | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/releases/{releaseId}/submit` | Submit a DRAFT or UNDER_AMENDMENT release for joint signature (full revalidation) | Dispatcher |
| POST | `/dispatch/releases/{releaseId}/sign` | Sign the release; the signature slot is derived from the caller role; the second valid signature releases it | Dispatcher, Captain |
| POST | `/dispatch/releases/{releaseId}/recall` | Recall a PENDING_SIGNATURES release to DRAFT (invalidates signatures) | Dispatcher |
| POST | `/dispatch/releases/{releaseId}/amend` | Amend a RELEASED release (moves to UNDER_AMENDMENT; signatures invalidated) | Dispatcher |
| GET | `/dispatch/releases/{id}/signatures` | List ReleaseSignatures of a release (append-only; validity is cycle_seq match) | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/monitoring-events` | File a position/fuel report for a DEPARTED leg; computes margin and recommendation | Dispatcher |
| GET | `/dispatch/monitoring-events/{eventId}` | Get a MonitoringEvent | Dispatcher, Captain, DispatchSupervisor |
| GET | `/dispatch/monitoring-events` | List MonitoringEvents, filterable by leg_id | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/monitoring-events/{eventId}/acknowledge` | Acknowledge an OPEN event; returns the leg monitor to MONITORING when it was the last OPEN alerting event | Dispatcher |
| GET | `/dispatch/legs/{id}/control-records` | List OperationalControlRecords for a leg (audit trail, append-only) | Dispatcher, Captain, DispatchSupervisor |
| POST | `/dispatch/_clock/set_current_utc` | Set the logical clock (test-driving); triggers the MEL expiry sweep and clock-derived recomputes | DispatchSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_DISPATCHER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_CAPTAIN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RELEASE_NOT_PENDING` | 409 Conflict |
| `ERR_LEG_NOT_IN_FLIGHT` | 409 Conflict |
| `ERR_RELEASE_EXISTS` | 409 Conflict |
| `ERR_MANIFEST_EXISTS` | 409 Conflict |
| `ERR_PLAN_IN_USE` | 409 Conflict |
| `ERR_PLAN_NOT_LOCKED` | 409 Conflict |
| `ERR_MANIFEST_MISSING` | 409 Conflict |
| `ERR_MEL_ITEM_EXPIRED` | 409 Conflict |
| `ERR_WORST_CASE_REQUIRED` | 409 Conflict |
| `ERR_WEATHER_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_WEATHER_BELOW_MINIMA` | 422 Unprocessable Entity |
| `ERR_CAPTAIN_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_DUAL_ROLE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_REST_VIOLATION` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_WEATHER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DELAY_INVALID_TIME` | 422 Unprocessable Entity |
| `ERR_REPAIR_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_DUPLICATE_SIGNATURE` | 409 Conflict |
| `ERR_MZFW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MTOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MLW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CG_OUT_OF_ENVELOPE` | 422 Unprocessable Entity |
| `ERR_PAYLOAD_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_FUEL_EXCEEDS_CAPACITY` | 422 Unprocessable Entity |
| `ERR_NO_SUITABLE_ALTERNATE` | 422 Unprocessable Entity |
| `ERR_DISPATCHER_OVERLOADED` | 409 Conflict |
| `ERR_DESK_OVERLOADED` | 409 Conflict |
| `ERR_NO_ACTIVE_SHIFT` | 422 Unprocessable Entity |
| `ERR_NO_DESK_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_NO_DISPATCHER_AVAILABLE` | 422 Unprocessable Entity |
