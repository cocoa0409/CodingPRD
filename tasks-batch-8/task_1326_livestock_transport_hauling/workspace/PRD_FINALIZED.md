# Livestock Transport & Hauling API — Product Requirements Document

## 1. Introduction

Livestock hauling sits at the intersection of animal-welfare law, driver fatigue regulation, and commodity-weight commerce. A cattle carrier must decide, for every trailer compartment, how many head of which species may ride together; must prove at every inspection station that health certificates and brand inspections are current; must wash trailers between loads; must pull drivers off the road before their legal hours run out; and must settle freight bills against scale weights that the receiving yard is entitled to dispute. This document specifies the Livestock Transport & Hauling API, mounted under `/haul`, which backs those operations end to end.

The API covers the complete chain of custody: shippers and their shrink-allowance defaults; the driver roster and its hours-of-service duty-event log; trailers and their compartments; load intake with optional backhaul linkage; compartment-level allocation; compliance paperwork with segregation of duties; dispatch, departure, weather holds, rest-and-unload stops, and arrival; scale tickets and delivery confirmation; provisional-to-final settlement with a dispute window; and welfare-incident reporting that can suspend a driver and reshuffle the fleet. All timestamp-sensitive decisions — washout freshness, the 28-hour confinement limit, hours-of-service windows, dispute deadlines — are evaluated against a single logical clock so that behavior is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing, or in which the role is not one of the recognized values, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The recognized roles are `CarrierAdmin`, `Dispatcher`, `ComplianceOfficer`, `Driver`, `ConsigneeAgent`, and `WashoutOperator`; the wildcard `Any` used elsewhere in this document means any authenticated role. When the declared role is not permitted to invoke an endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identities resolve as follows. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver entity; ownership checks on any resource that references a Driver compare the resource's driver field to `X-User-ID`. When `X-User-Role` is `CarrierAdmin`, `Dispatcher`, `ComplianceOfficer`, `ConsigneeAgent`, or `WashoutOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` and `verified_by_user_id` on a `HealthPaper` or `BrandInspection`, where it anchors the segregation-of-duties check — but it is never compared to an entity's `id` outside those audit fields.

Ownership rule for the `Driver` role: a driver may append duty events only to their own record (the path driver id must equal `X-User-ID`), and may perform depart, arrive, rest-unload, resume-transit, weather-hold placement and release, and welfare-incident reporting only on a load whose `driver_id` equals `X-User-ID`. Any violation is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless a more specific ordering is stated for a particular collection, all list endpoints return resources sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versions

Every primary resource carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, including mutations caused by cross-entity cascades.

Three record types are immutable once written and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: a `DriverDutyEvent`, a `WashoutEvent`, and a `WeightTicket`. All other entities (`Shipper`, `Driver`, `Trailer`, `TrailerCompartment`, `Load`, `CompartmentAllocation`, `HealthPaper`, `BrandInspection`, `Settlement`, `WelfareIncident`, `WeatherHold`) carry the full standard set.

### 2.5. The Logical Clock

Every occurrence of "now" in this document refers to the server's logical clock, never to wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, the clock continues to report this default and never falls back to wall-clock time. A `CarrierAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc` string. All timestamp-sensitive evaluations — the 96-hour washout window, confinement and rest-unload clocks, hours-of-service windows, the 48-hour dispute window, and every "not in the future" check — are computed against this clock.

### 2.6. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control. Each requires a non-optional version field in the request body carrying the caller's last observed `version` of the named parent entity; if that value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Creating a compartment allocation against a load requires `expected_load_version` matching the load's current `version`. After a reopen-plan or another allocation, a client allocating against a stale plan is rejected.
- Releasing an allocation requires `expected_load_version` matching the current `version` of the load the allocation belongs to.
- Assigning a driver to a load requires `expected_driver_version` matching the driver's current `version`; the assignment decision was made on a snapshot of the driver's hours and standing, and new duty events or another assignment recorded in between advance that version.
- Countering a settlement requires `expected_settlement_version` matching the settlement's current `version`; because a fresh counter legitimately supersedes a prior one, the stale writer must re-read before countering.

Endpoints not listed here do not accept a version field.

### 2.7. Validation Pipeline and Error Precedence

Every request passes through validation layers in a fixed precedence order, and a failure in an earlier layer masks every later layer. The order is:

1. **Identity headers.** `X-User-ID` and `X-User-Role` are present and the role is recognized — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The declared role may invoke this endpoint — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Driver ownership.** For write operations performed under the `Driver` role, the ownership rule of §2.1 — otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
4. **Request-body shape.** Required fields are present, types and enum values are valid, numeric inputs are positive, and on a health certificate `expires_at` is strictly later than `issued_at` — otherwise `ERR_INVALID_REQUEST` (HTTP 400), or `ERR_INVALID_TIME_RANGE` (HTTP 400) for the certificate time-range case.
5. **Path existence.** Identifiers in the URL path are validated left to right; the first identifier that does not resolve rejects the request with that resource's specific not-found error (HTTP 404): `ERR_SHIPPER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`, `ERR_COMPARTMENT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_HEALTH_PAPER_NOT_FOUND`, `ERR_BRAND_INSPECTION_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOLD_NOT_FOUND`. A nested request therefore fails on the parent before the child is ever consulted.
6. **Body reference existence.** Identifiers carried in the request body — `shipper_id`, `trailer_compartment_id`, `driver_id`, `backhaul_of_load_id`, `load_id` — must resolve to existing resources, again producing the referenced resource's specific not-found error (HTTP 404).
7. **State preconditions.** The target resource must be in the state its state machine requires for the attempted transition. State violations produce the transition's specific state error at HTTP 409 — for example `ERR_LOAD_NOT_DRAFT` or `ERR_SETTLEMENT_NOT_PENDING` — with one exception: attempting to pay a settlement that is `DISPUTED` or `COUNTERED` yields `ERR_UNRESOLVED_DISPUTE` at HTTP 422.
8. **Optimistic concurrency.** On the four guarded operations of §2.6, the expected-version field is compared against the parent's current `version` — a mismatch yields `ERR_STALE_VERSION` (HTTP 412).

Only after all eight layers pass do the endpoint-specific business rules run, in the per-endpoint priority order narrated with each workflow in §3. Where several business checks guard one endpoint, §3 states their relative order explicitly.

### 2.8. Units, Precision, and Rounding

All monetary amounts are integer cents; all weights are whole pounds; all durations are whole minutes; all temperatures are integer degrees Fahrenheit; percentages are carried as given. Rounding, wherever a computed value must be materialized, is round half up.

Two pinning rules eliminate ambiguity in compound calculations. First, rounding is applied per line before summation: each allocation's `weight_lb` is rounded to a whole pound before load and compartment totals are summed, and each incident's `fine_cents` is rounded to whole cents before a settlement's welfare deduction is summed. Second, the settlement base is rounded before any backhaul discount is applied, and the discounted figure is rounded again. The alternative orders — summing raw products and rounding once, or discounting the rate before multiplying — produce different cents and are forbidden.

### 2.9. Derived State and Cascading Consistency

Derived fields are never cached stale: every derived value described in §3 is recomputed within the request that triggers it, and reads of a driver or a trailer recompute that resource's derived fields at read time. Any mutation — including one caused by a cascade rather than by the client's direct action — refreshes the affected entity's `updated_at` and increments its `version` by 1.

Several cascades propagate across entity boundaries and are specified in full where they occur: allocation changes recompute compartment occupancy and load totals; assignment changes recompute a trailer's `reserved_until`; delivery releases allocations, dirties the trailer, finalizes the settlement, and can force-unassign the driver from other loads; closing a welfare incident can reprice a settlement and suspend a driver, which in turn force-unassigns that driver's assigned loads. A change that does not dirty a trailer (cancellation or replanning) is called out explicitly where it applies.

## 3. Business Logic & Workflows

### 3.1. Shippers, Drivers, and the Hours-of-Service Ledger

A `CarrierAdmin` registers a shipper — a ranch or feedlot — with its legal `name` and billing `contact_email`. An optional `default_shrink_allowance_pct` establishes the shipper's standard shrink allowance; when omitted it defaults to 2.0 percent and applies to every load of that shipper that does not carry its own override.

Drivers join the roster through a `CarrierAdmin` as well, supplying a `name` and a CDL `license_no`. The license number is unique across drivers: a duplicate submission is rejected with `ERR_DUPLICATE_LICENSE_NO` (HTTP 409), a check that runs after the request body's shape has been validated. A freshly created driver has `status` `ACTIVE` and `hos_status` `ELIGIBLE`. Beyond these inputs, a driver record is dominated by computed fields — `session_driving_minutes`, `calendar_day_driving_minutes`, `cycle_on_duty_minutes_8d`, `driving_since_break_minutes`, `duty_window_expires_at`, `hos_status`, and `critical_incident_count_90d` — all of which are derived from the driver's duty-event log and recomputed whenever the driver is read. The driver roster list can be filtered by `status` and by `hos_status`.

The duty-event log is the single source of truth for fatigue accounting. A `CarrierAdmin` may append an event to any driver; a `Driver` may append only to their own record, with a mismatch rejected as `ERR_OWNERSHIP_MISMATCH`. Each event carries an `event_type` — one of `DUTY_ON`, `DUTY_OFF`, `DRIVING_ON`, `DRIVING_OFF`, `BREAK_START`, `BREAK_END` — and an `occurred_at` timestamp. The `source` distinguishes `MANUAL` events posted through this log from `SYSTEM` events the server appends itself during depart, arrive, deliver, hold, and release transitions; system events also carry the `load_id` of the load being worked, which is null on manual events. The event list of a driver is returned in chronological order: `occurred_at` ascending, ties broken by `created_at` ascending.

Three temporal checks guard every appended event, and they run in this order after ownership and body validation. First, `occurred_at` must not be later than the current logical time, or the append fails with `ERR_EVENT_IN_FUTURE` (HTTP 422). Second, `occurred_at` must not be earlier than the previous event's `occurred_at` — equality is allowed, because duty and driving intervals are half-open and a `DUTY_ON` stamped at exactly the previous `DUTY_OFF`'s timestamp is legal back-to-back adjacency; a strictly earlier timestamp would invert an interval and is rejected with `ERR_DUTY_INTERVAL_OVERLAP` (HTTP 409). Third, the event type must be legal for the driver's current duty sub-state: `DUTY_ON` is legal only while off duty; `DRIVING_ON` only while on duty and not driving; `DRIVING_OFF` only while driving; `BREAK_START` only while on duty, not driving, and not on break; `BREAK_END` only while on break; and `DUTY_OFF` only while on duty — a `DUTY_OFF` auto-closes any open driving or break interval at its own timestamp. An illegal transition is rejected with `ERR_DUTY_EVENT_SEQUENCE` (HTTP 409). A successful append recomputes the driver's hours-of-service fields and, when a derived field changes as a result, increments the driver `version`.

Hours-of-service derivation replays the log in chronological order — `occurred_at` ascending, ties broken by `created_at` ascending, never by `id`. A rest is an off-duty gap, from a `DUTY_OFF` to the next `DUTY_ON`, of at least 600 minutes (ten hours); such a rest resets the driving session, and the session window begins at the end of the most recent qualifying rest, or at the driver's first event when no such rest exists. `session_driving_minutes` sums the driving intervals (`DRIVING_ON` to `DRIVING_OFF`) inside the session window, with a still-open driving interval counted up to the current time. A break credit is a `BREAK_START`–`BREAK_END` pair spanning at least 30 minutes, or any off-duty gap of at least 30 minutes; `driving_since_break_minutes` accumulates driving minutes since the end of the most recent break credit, or since the session start when no break credit exists. The duty-window anchor is the latest `DUTY_ON` preceded by at least 600 minutes off duty — or the first `DUTY_ON` when no such rest exists — and `duty_window_expires_at` is that anchor plus 840 minutes (fourteen hours); the anchor is cleared once an off-duty stretch of at least 600 minutes has elapsed, so `duty_window_expires_at` is null when no shift is anchored. `cycle_on_duty_minutes_8d` sums on-duty minutes (`DUTY_ON` to `DUTY_OFF`, an open interval counted to now) clipped to the trailing window of the last 11520 minutes (eight days). Independently of the session model, `calendar_day_driving_minutes` sums driving minutes clipped to the current UTC calendar day from midnight to now, with intervals clipped at midnight — an identical event stream produces different session and calendar-day figures whenever a trip crosses midnight.

From these derived fields, `hos_status` is evaluated in a pinned priority order, first match wins: `CYCLE_EXHAUSTED` when `cycle_on_duty_minutes_8d` has reached 4200 (seventy hours); otherwise `SESSION_EXHAUSTED` when `session_driving_minutes` has reached 660 (eleven hours); otherwise `WINDOW_CLOSED` when the driver is on duty and the current time is past `duty_window_expires_at`; otherwise `BREAK_REQUIRED` when `driving_since_break_minutes` has reached 480 (eight hours); otherwise `ELIGIBLE`. Every threshold is inclusive — being exactly at a limit means the driver is exhausted or a break is due. Separately, `critical_incident_count_90d` counts the driver's closed welfare incidents of severity `CRITICAL` whose `occurred_at` falls within the trailing 90 days; its consequence — suspension — is described in §3.7.

### 3.2. Trailers, Compartments, and Washout Biosecurity

A `CarrierAdmin` creates a trailer by supplying its fleet `trailer_no` — unique across the fleet — its `max_gross_weight_lb` (the GVWR that no single load's allocated weight may exceed), and a `compartments` array that atomically creates the trailer's compartments in the same request. Each compartment definition supplies `compartment_index` (a 1-based number unique within the trailer), `max_head_count`, and `max_weight_lb`, both capacities strictly greater than zero. A compartment's live fill is exposed as `occupied_head_count` and `occupied_weight_lb`, computed as the sums over that compartment's `ACTIVE` allocations across all loads. A trailer's compartment listing is ordered by `compartment_index` ascending, and the trailer list can be filtered by `washout_status`.

Biosecurity is tracked per trailer through a washout ledger. A `WashoutOperator` or `CarrierAdmin` records a wash with its `washed_at` completion timestamp — which must not be later than the current logical time, or the record is rejected with `ERR_EVENT_IN_FUTURE` — a `method` of `HIGH_PRESSURE`, `STEAM`, or `CHEMICAL`, and an optional `operator_note`. Recording a wash sets the trailer's `last_washed_at` to `washed_at`, clears `dirtied_at` to null, sets `washout_valid_until` to `washed_at` plus 96 hours, and recomputes `washout_status`.

The trailer's `washout_status` follows a strict rule. It is `DIRTY` when the trailer has never been washed, or when it was dirtied after its most recent wash — concretely, when `dirtied_at` is set and either `last_washed_at` is null or `dirtied_at` is later than `last_washed_at`. Otherwise it is `CLEAN` while the current time is at or before `last_washed_at` plus 96 hours — the boundary is inclusive, so a trailer at exactly 96 hours since its wash is still clean — and `STALE` once that moment has passed. A brand-new trailer has never been washed and therefore starts `DIRTY`: it must be washed before its first load can depart. A trailer becomes dirty through delivery: when a load riding that trailer is delivered, `dirtied_at` is set to the delivery time and the status recomputes to `DIRTY`. Cancellation and replanning never dirty a trailer. Reading a trailer recomputes `washout_status` at read time.

A trailer also exposes `reserved_until`: the latest planned window end — each window running from the load's `planned_departure_at` for `planned_duration_hours` hours — over this trailer's loads in `ASSIGNED`, `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, or `ARRIVED`; it is null when no such load exists. The value is recomputed whenever assignments or load states touching the trailer change.

### 3.3. Load Intake, Backhaul Linkage, and Compartment Allocation

A `Dispatcher` opens a load with a payload containing `shipper_id`, the hauled `species` (exactly one of `CATTLE`, `SWINE`, `SHEEP`, or `HORSES` per load), the shipper-declared `declared_head_count` and `declared_weight_lb` (both greater than zero), free-text `origin` and `destination`, the `planned_departure_at` window start, `planned_duration_hours` (greater than zero), the contract `rate_per_loaded_mile_cents` (greater than zero), and the contract `loaded_miles` (greater than zero). Two optional fields modify commercial terms: `shrink_allowance_pct`, a per-load override of the shrink allowance, and `backhaul_of_load_id`, declaring this load the backhaul of an earlier one. The referenced shipper must exist (`ERR_SHIPPER_NOT_FOUND`), as must the backhaul target (`ERR_LOAD_NOT_FOUND`). A new load starts in `DRAFT` with no `driver_id`, no `trailer_id`, and zero `allocated_head_count` and `allocated_weight_lb`; the actual timestamps `departed_at`, `arrived_at`, and `delivered_at`, and the clocks `confinement_anchor_at` and `rest_unload_started_at`, are all null until the road events of §3.5 and §3.6 set them.

Shrink resolution happens at creation: `effective_shrink_pct` is the load's own `shrink_allowance_pct` when one was provided, and the shipper's `default_shrink_allowance_pct` otherwise. A load list may be filtered by `status`, `shipper_id`, `driver_id`, `trailer_id`, or `backhaul_of_load_id`.

Backhaul linkage is validated when `backhaul_of_load_id` is present. The target load must be `DELIVERED`; the target's `destination` must equal this load's `origin`; the target's `delivered_at` must be at or before this load's `planned_departure_at`; and the gap between that delivery and this planned departure must not exceed 72 hours — a gap of exactly 72 hours is acceptable. Any failure is rejected with `ERR_INVALID_BACKHAUL_LINK` (HTTP 422). When the link is valid, the load's derived `is_backhaul` is true, and the settlement created at departure applies the backhaul discount described in §3.6.

With the load in `DRAFT`, a `Dispatcher` places animals into compartments by creating an allocation with `trailer_compartment_id`, `head_count` (greater than zero), `avg_weight_lb` (greater than zero), and the optimistic-concurrency field `expected_load_version`. The checks run in a fixed order: the compartment must exist (`ERR_COMPARTMENT_NOT_FOUND`); the load must still be `DRAFT` (`ERR_LOAD_NOT_DRAFT`, HTTP 409); `expected_load_version` must match the load's current `version` (`ERR_STALE_VERSION`, HTTP 412); the compartment must not already hold an `ACTIVE` allocation of a different species (`ERR_SPECIES_MIX_FORBIDDEN`, HTTP 422); the compartment's head room must suffice — `occupied_head_count` plus the new `head_count` may not exceed `max_head_count`, with a placement exactly at capacity allowed (`ERR_COMPARTMENT_HEAD_EXCEEDED`, HTTP 422); and the compartment's weight room must suffice — `occupied_weight_lb` plus the new allocation's `weight_lb` may not exceed `max_weight_lb` (`ERR_COMPARTMENT_WEIGHT_EXCEEDED`, HTTP 422).

Each allocation's `weight_lb` is its `head_count` multiplied by `avg_weight_lb`, rounded half up to a whole pound — this per-allocation rounding is pinned before any summation. The load's `allocated_head_count` and `allocated_weight_lb` are the sums of `head_count` and `weight_lb` over its `ACTIVE` allocations only; `RELEASED` rows are excluded. Creating an allocation recomputes the compartment's occupancy and the load's totals and increments the load `version` by 1.

A `Dispatcher` may also release an allocation manually. The load must be `DRAFT` (`ERR_LOAD_NOT_DRAFT`) and the request must carry `expected_load_version` matching the load's current `version` (`ERR_STALE_VERSION`). The allocation's `status` becomes `RELEASED` with `release_reason` `REPLANNED`; the compartment occupancy and the load's totals are recomputed; and the load `version` increments by 1. The `release_reason` vocabulary distinguishes how an allocation ended: `REPLANNED` for a manual release or a reopened plan, `CANCELLED` when the load is cancelled, and `DELIVERED` when the load is delivered; it is null while the allocation is `ACTIVE`. Allocations can be browsed per load (ordered by `created_at` ascending, filterable by `status`) or across loads with `trailer_compartment_id`, `load_id`, and `status` filters, and fetched individually by id (`ERR_ALLOCATION_NOT_FOUND`).

### 3.4. Plan Finalization and Compliance Paperwork

Finalizing a plan moves a load from `DRAFT` to `PLANNED` and is performed by a `Dispatcher`. The transition enforces four checks in order: the load is `DRAFT` (`ERR_LOAD_NOT_DRAFT`); every `ACTIVE` allocation belongs to compartments of a single trailer (`ERR_MIXED_TRAILER_ALLOCATIONS`, HTTP 422); at least one `ACTIVE` allocation exists and the allocated totals equal the declared totals — `allocated_head_count` must equal `declared_head_count` and `allocated_weight_lb` must equal `declared_weight_lb` (`ERR_ALLOCATION_TOTAL_MISMATCH`, HTTP 422); and the load's `allocated_weight_lb` must not exceed the trailer's `max_gross_weight_lb` (`ERR_GVWR_EXCEEDED`, HTTP 422). On success the load's `trailer_id` is bound to that single trailer and the load `version` increments by 1.

Reopening reverses finalization: a `Dispatcher` may move a `PLANNED` load back to `DRAFT` (any other state fails with `ERR_LOAD_NOT_PLANNED`, HTTP 409). Every `ACTIVE` allocation is released with `release_reason` `REPLANNED` and compartment occupancy recomputed, the load's `trailer_id` is cleared to null, and the load `version` increments by 1.

Compliance paperwork begins with the health paper — the certificate of veterinary inspection. A `ComplianceOfficer` attaches one to a load by supplying `cert_number`, the covered `species`, `head_count_listed`, the `issued_at` timestamp (at or before the current time), and `expires_at`. A certificate whose `expires_at` is not strictly later than its `issued_at` is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 400) at body validation. The new paper starts `PENDING`, and the server records the uploader in `created_by_user_id` from `X-User-ID`.

Verification enforces segregation of duties: the verifier must not be the uploader. A `ComplianceOfficer` verifies a paper through a chain of checks in fixed order — the paper is `PENDING` (`ERR_PAPERWORK_NOT_PENDING`, HTTP 409); the load is `PLANNED` or `PAPERWORK_VERIFIED` (`ERR_LOAD_NOT_PLANNED`); the verifier's `X-User-ID` differs from `created_by_user_id` (`ERR_SOD_VIOLATION`, HTTP 403); the paper's `species` equals the load's `species` and `head_count_listed` equals `declared_head_count` (`ERR_PAPER_MISMATCH`, HTTP 422); and `expires_at` is strictly later than the load's `planned_departure_at` (`ERR_PAPER_EXPIRED`, HTTP 422). A verified paper records `verified_by_user_id` from the verifier's `X-User-ID`, moves to `VERIFIED`, and increments its `version`. Rejection — available from `PENDING` with an optional `reason` — moves the paper to `REJECTED` and likewise increments `version`. Both `VERIFIED` and `REJECTED` are terminal.

The brand inspection follows the same pattern. A `ComplianceOfficer` attaches one with `inspection_no`, `inspected_at`, the registered `brand_owner`, and `head_count_inspected`; the record starts `PENDING` with `created_by_user_id` captured. Verification checks, in order: the inspection is `PENDING` (`ERR_PAPERWORK_NOT_PENDING`); the load is `PLANNED` or `PAPERWORK_VERIFIED` (`ERR_LOAD_NOT_PLANNED`); the verifier is not the creator (`ERR_SOD_VIOLATION`); `head_count_inspected` equals the load's `declared_head_count` (`ERR_PAPER_MISMATCH`); and the inspection is fresh — `inspected_at` is at or before the current time and the span from `inspected_at` to the load's `planned_departure_at` does not exceed 96 hours (`ERR_BRAND_INSPECTION_STALE`, HTTP 422). Verification sets `verified_by_user_id`, moves the record to `VERIFIED`, and increments `version`; rejection moves it to `REJECTED` with an optional `reason`.

Once the paperwork is in place, a `ComplianceOfficer` advances the load from `PLANNED` to `PAPERWORK_VERIFIED` (any other state fails with `ERR_LOAD_NOT_PLANNED`). The transition requires at least one `VERIFIED` health paper for the load whose `expires_at` is later than `planned_departure_at`, and at least one `VERIFIED` brand inspection for the load; a shortfall in either is rejected with `ERR_PAPERWORK_INCOMPLETE` (HTTP 422). Success increments the load `version` by 1.

### 3.5. Dispatch and Line-Haul Operations

Assigning a driver moves a load from `PAPERWORK_VERIFIED` to `ASSIGNED`. A `Dispatcher` submits `driver_id` together with `expected_driver_version`, and the checks run in order: the load exists; the referenced driver exists (`ERR_DRIVER_NOT_FOUND`); the load is `PAPERWORK_VERIFIED` (`ERR_LOAD_NOT_PAPERWORK_VERIFIED`, HTTP 409); `expected_driver_version` matches the driver's current `version` (`ERR_STALE_VERSION`, HTTP 412) — the assignment decision rests on a snapshot of the driver's hours and standing, and new duty events or another assignment recorded since that snapshot advance the version; the driver is `ACTIVE` (`ERR_DRIVER_SUSPENDED`, HTTP 422); the driver's `hos_status` is `ELIGIBLE` (`ERR_DRIVER_NOT_HOS_ELIGIBLE`, HTTP 422); and neither the driver nor the trailer has a conflicting planned window (`ERR_TRAILER_WINDOW_OVERLAP`, HTTP 409).

The window rule treats every load's planned window as the closed interval from `planned_departure_at` to `planned_departure_at` plus `planned_duration_hours`, inclusive at both ends. A conflict exists when any other load sharing the same `driver_id` or the same `trailer_id`, in any of `ASSIGNED`, `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, or `ARRIVED`, has a window that touches or overlaps this load's window. Touching endpoints conflict — one load's window beginning exactly when another's ends leaves no turnaround and is rejected. A successful assignment sets the load's `driver_id`, moves the load to `ASSIGNED`, increments the load `version` by 1, increments the driver `version` by 1 to record the assignment on the driver, and recomputes the trailer's `reserved_until`.

Unassigning compensates an assignment: a `Dispatcher` moves an `ASSIGNED` load back to `PAPERWORK_VERIFIED` (any other state fails with `ERR_LOAD_NOT_ASSIGNED`). The load's `driver_id` is cleared to null, the driver `version` increments by 1, the load `version` increments by 1, and the trailer's `reserved_until` is recomputed.

Departure belongs to the assigned driver: the caller's `X-User-ID` must equal the load's `driver_id` (`ERR_OWNERSHIP_MISMATCH`). The driver submits `origin_temperature_f`, the observed temperature at the origin. The checks run in order: ownership; the load is `ASSIGNED` (`ERR_LOAD_NOT_ASSIGNED`); the driver is not `SUSPENDED` (`ERR_DRIVER_SUSPENDED`); the driver's `hos_status` is `ELIGIBLE` at the current time (`ERR_DRIVER_NOT_HOS_ELIGIBLE`); the trailer's `washout_status` is `CLEAN` at the current time (`ERR_TRAILER_NOT_CLEAN`, HTTP 422); and the weather gate — departure is forbidden, and a weather hold is required instead, when `origin_temperature_f` is at or above the species heat threshold (95 for `CATTLE`, 85 for `SWINE`, 90 for `SHEEP`, 95 for `HORSES`) or at or below the species cold threshold (0 for `CATTLE`, 10 for `SWINE`, -5 for `SHEEP`, 5 for `HORSES`), with the thresholds inclusive on both sides (`ERR_WEATHER_HOLD_REQUIRED`, HTTP 422). Finally, the paperwork that was verified against the planned departure must still be valid at the actual moment of departure: a `VERIFIED` health paper with `expires_at` later than now must exist (`ERR_PAPER_EXPIRED`), and a `VERIFIED` brand inspection whose `inspected_at` is no more than 96 hours before now must exist (`ERR_BRAND_INSPECTION_STALE`).

A successful departure sets `departed_at` and `confinement_anchor_at` to the current time and increments the load `version`. The server appends duty events on the driver's log with `source` `SYSTEM`: a `DUTY_ON` if the driver was off duty, then a `DRIVING_ON`. Departure also creates the load's settlement in `PRELIMINARY` — its amounts are specified in §3.6 — and recomputes the trailer's `reserved_until`.

Weather holds interrupt the plan without cancelling it. A `Dispatcher`, or the assigned `Driver` on their own load, may place a hold while the load is `ASSIGNED` or `IN_TRANSIT` (any other state fails with `ERR_LOAD_NOT_HOLDABLE`, HTTP 409). The request carries `hold_type` (`HEAT` or `COLD`), the observed `temperature_f` driving the hold, and an optional `reason`. A `WeatherHold` is created `ACTIVE` — its `status` is `ACTIVE` while `released_at` is null — the load moves to `WEATHER_HOLD`, and the load `version` increments by 1. When the load was in transit, the server also appends a system `DRIVING_OFF` event at the current time. Time spent under a hold counts toward the animals' confinement: they remain on the trailer.

Releasing a hold — again a `Dispatcher` or the load's own `Driver` — requires the hold to be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`, HTTP 409; a hold id that does not resolve fails earlier with `ERR_HOLD_NOT_FOUND`). The release sets `released_at` to now, increments the hold's `version`, and resumes the load along one of two sibling branches with equal effect on the load `version` (incremented by 1 in both): if the load never departed — `departed_at` is null — it returns `WEATHER_HOLD → ASSIGNED`; if the load was held in transit — `departed_at` is set — the server appends a system `DRIVING_ON` event and the load returns `WEATHER_HOLD → IN_TRANSIT`.

Long trips are punctuated by the twenty-eight-hour confinement rule. At any point in transit the assigned driver may begin a rest-and-unload stop, moving `IN_TRANSIT → REST_UNLOAD` (any other state fails with `ERR_LOAD_NOT_IN_TRANSIT`); the server appends a system `DRIVING_OFF`, records `rest_unload_started_at` at the current time, and increments the load `version`. Resuming transit moves `REST_UNLOAD → IN_TRANSIT` (any other state fails with `ERR_LOAD_NOT_REST_UNLOAD`) and is allowed only once at least 300 minutes (five hours) have elapsed since `rest_unload_started_at` — exactly 300 minutes qualifies, anything less fails with `ERR_INSUFFICIENT_REST_UNLOAD` (HTTP 422). A qualifying resume resets the confinement clock: `confinement_anchor_at` is set to now, `rest_unload_started_at` is cleared to null, a system `DRIVING_ON` is appended, and the load `version` increments.

Arrival moves `IN_TRANSIT → ARRIVED` under the assigned driver (ownership first, then the `ERR_LOAD_NOT_IN_TRANSIT` state check). The confinement rule binds here: the span from `confinement_anchor_at` to now must not exceed 1680 minutes (twenty-eight hours) — exactly 1680 minutes is allowed, any more is rejected with `ERR_CONFINEMENT_LIMIT_EXCEEDED` (HTTP 422). Because hold time counts toward confinement, a driver who waited out a storm must count those hours against the same clock. Arrival sets `arrived_at` to now, appends a system `DRIVING_OFF`, and increments the load `version`.

A `Dispatcher` may cancel a load from `DRAFT`, `PLANNED`, `PAPERWORK_VERIFIED`, or `ASSIGNED` — from any other state the attempt fails with `ERR_LOAD_NOT_CANCELLABLE` (HTTP 409). Cancellation releases every `ACTIVE` allocation with `release_reason` `CANCELLED` and recomputes compartment occupancy; it does not dirty the trailer. When the load was `ASSIGNED`, the driver is detached — `driver_id` set to null and the driver `version` incremented — and the trailer's `reserved_until` is recomputed. In all cases the load's `trailer_id` is cleared to null and the load `version` increments by 1, leaving the load terminally `CANCELLED`.

### 3.6. Scale Tickets, Delivery, and the Settlement Cascade

Scale tickets are the commercial evidence of the trip. A `ConsigneeAgent` or a `Driver` records one against a load with `ticket_type` (`ORIGIN` or `DELIVERY`), `gross_lb`, `tare_lb`, and `weighed_at`; the ticket's `net_weight_lb` is `gross_lb` minus `tare_lb`. The checks run in order: body shape, then load existence, then the state rule — an `ORIGIN` ticket is accepted only while the load is in `DRAFT`, `PLANNED`, `PAPERWORK_VERIFIED`, `ASSIGNED`, or `IN_TRANSIT`, and a `DELIVERY` ticket only while the load is `ARRIVED` or while it is `DELIVERED` with its settlement still `PENDING`; any other combination is rejected with `ERR_TICKET_STATE_FORBIDDEN` (HTTP 409). After the state rule, `gross_lb` must be strictly greater than `tare_lb` (`ERR_INVALID_TICKET_WEIGHT`, HTTP 422; `tare_lb` itself may be zero), and `weighed_at` must not be later than the current logical time (`ERR_EVENT_IN_FUTURE`). A `DELIVERY` ticket recorded while the settlement is `PENDING` is a reweigh: the settlement's `delivered_weight_lb` and `effective_delivered_weight_lb` are refreshed from the new latest `DELIVERY` ticket and the final settlement is recomputed as specified below.

Delivery confirmation belongs to the `ConsigneeAgent`. The load must be `ARRIVED` (`ERR_LOAD_NOT_ARRIVED`, HTTP 409) and at least one `DELIVERY` ticket must exist (`ERR_NO_DELIVERY_TICKET`, HTTP 422). Confirmation sets `delivered_at` to now, increments the load `version`, appends a system `DUTY_OFF` if the driver is on duty, and then fires a five-link cascade. First — chain link 1 — every `ACTIVE` allocation is released with `release_reason` `DELIVERED`, and compartment occupancy and the load's allocated totals are recomputed. Second — chain link 2 — because the release reason is `DELIVERED`, the trailer's `dirtied_at` is set to the delivery time and its `washout_status` recomputes to `DIRTY`; releases with reason `CANCELLED` or `REPLANNED` never dirty a trailer. Third, the settlement is finalized: `delivered_weight_lb` becomes the `net_weight_lb` of the latest `DELIVERY` ticket — ordered by `weighed_at` descending with `created_at` descending as the tie-break — `effective_delivered_weight_lb` is set to the same value, the shrink and final fields are computed, the settlement moves from `PRELIMINARY` to `PENDING`, and `dispute_deadline_at` is set to `delivered_at` plus 48 hours. Fourth, the driver's hours-of-service fields are recomputed from the appended duty events. Fifth — chain link 3 — if that recomputation leaves `cycle_on_duty_minutes_8d` at or above 4200, the driver's `hos_status` becomes `CYCLE_EXHAUSTED` and every other load still holding this driver in `ASSIGNED` is force-unassigned back to `PAPERWORK_VERIFIED`: its `driver_id` is set to null, its `version` increments by 1, and its trailer's `reserved_until` is recomputed. Delivery is terminal for the load.

The settlement is created at departure in `PRELIMINARY`, one per load — its `load_id` is unique. Its `base_amount_cents` is the load's `rate_per_loaded_mile_cents` multiplied by `loaded_miles`, rounded half up to integer cents; when `is_backhaul` is true, that rounded product is then multiplied by 0.85 — a 15 percent backhaul discount — and rounded half up again. The rounding order is pinned: round the rate-times-miles product first, then apply the discount and round again; discounting the rate before multiplying yields different cents and is forbidden. `provisional_amount_cents` equals `base_amount_cents`: the provisional figure assumes an on-weight delivery, with no shrink penalty and no welfare deduction.

Final settlement is computed at delivery, at a reweigh while `PENDING`, at dispute resolution, and at every incident close. The load's shrink allowance in pounds, `shrink_allowance_lb`, is `declared_weight_lb` multiplied by `effective_shrink_pct` and divided by 100, rounded half up to a whole pound. `shrink_lb` is the shortfall — `declared_weight_lb` minus `effective_delivered_weight_lb`, floored at zero. `excess_shrink_lb` is the part of the shortfall beyond the allowance — `shrink_lb` minus `shrink_allowance_lb`, floored at zero. The `shrink_penalty_cents` is `excess_shrink_lb` multiplied by 2.5 cents per pound, rounded half up. The `welfare_deduction_cents` sums `fine_cents` over the load's closed, non-waived welfare incidents. The `final_amount_cents` is `provisional_amount_cents` minus `shrink_penalty_cents` minus `welfare_deduction_cents`, floored at zero. A money identity holds after every mutation: the final amount always equals the provisional amount less the shrink penalty less the welfare deduction, so a dispute round-trip whose countered weight equals the delivered weight reproduces the pre-dispute final exactly. A settlement record also carries `disputed_weight_lb`, `counter_weight_lb`, and `dispute_adjustment_cents` for the dispute workflow of §3.8, and `paid_at`, set when the settlement is paid. Reading a load's settlement returns an array of zero or one element, and the settlement list can be filtered by `status`.

### 3.7. Welfare Incidents and Driver Standing

The assigned driver reports a welfare incident on their own load (ownership per §2.1) with a payload containing `load_id`, `incident_type` (`INJURY`, `DOWNER`, `DEAD_ON_ARRIVAL`, or `ESCAPE`), `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), `head_count_affected` (at least 1), the `occurred_at` timestamp, and an optional `description`. The referenced load must exist (`ERR_LOAD_NOT_FOUND`) and must be in `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, `ARRIVED`, or `DELIVERED` (`ERR_LOAD_NOT_REPORTABLE`, HTTP 409); `occurred_at` must not be in the future (`ERR_EVENT_IN_FUTURE`). The report records the reporter by setting `driver_id` from `X-User-ID` and starts in `REPORTED`. The incident list supports `load_id`, `driver_id`, `status`, and `severity` filters.

A `ComplianceOfficer` drives the review. Starting review moves `REPORTED → UNDER_REVIEW` (any other state fails with `ERR_INCIDENT_NOT_REPORTED`, HTTP 409) and increments the incident `version`. Closing moves `UNDER_REVIEW → CLOSED` (any other state fails with `ERR_INCIDENT_NOT_UNDER_REVIEW`) and accepts an optional `fine_waived` flag defaulting to false.

Closing computes the fine. When `fine_waived` is true, `fine_cents` is zero. Otherwise the fine is a per-incident-type base in cents — 33333 for `INJURY`, 41667 for `DOWNER`, 100000 for `DEAD_ON_ARRIVAL`, 25000 for `ESCAPE` — multiplied by `head_count_affected` and by a severity multiplier — 1.5 for `MINOR`, 2.5 for `MAJOR`, 4.0 for `CRITICAL` — with the product rounded half up to whole cents for each incident before any summation. The close also sets `closed_at` to now and increments the incident `version`.

Closing then fires a three-link cascade. Chain link 1: when the load's settlement exists and is not `PAID`, its `welfare_deduction_cents` is recomputed as the sum of `fine_cents` over the load's closed, non-waived incidents, and `final_amount_cents` is recomputed per §3.6. Chain link 2: the driver's `critical_incident_count_90d` is recomputed — closed `CRITICAL` incidents occurring within the trailing 90 days — and when the count reaches 2 while the driver is `ACTIVE`, the driver's `status` becomes `SUSPENDED`. Chain link 3: upon suspension, every load holding this driver in `ASSIGNED` is force-unassigned back to `PAPERWORK_VERIFIED` — `driver_id` set to null, load `version` incremented by 1 — and each affected trailer's `reserved_until` is recomputed. A suspended driver can neither be assigned nor depart until standing is restored.

### 3.8. Weight Disputes, Counters, and Payment

When the consignee disagrees with the delivered weight, a `ConsigneeAgent` disputes the settlement, moving `PENDING → DISPUTED` (any other state fails with `ERR_SETTLEMENT_NOT_PENDING`, HTTP 409). Dispute is allowed only while the current time is at or before `dispute_deadline_at` — the window is inclusive, closing at exactly `delivered_at` plus 48 hours — after which the attempt fails with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422). The dispute records the claimed `disputed_weight_lb` and an optional `reason`, and increments the settlement `version`.

From `DISPUTED`, two sibling branches resolve or escalate. Accepting the original weight — a `ConsigneeAgent` action — moves `DISPUTED → RESOLVED` (any other state fails with `ERR_SETTLEMENT_NOT_DISPUTED`): `effective_delivered_weight_lb` is set back to `delivered_weight_lb`, the shrink fields and `final_amount_cents` are recomputed, `dispute_adjustment_cents` is set to 0, and the settlement `version` increments. Countering — a `Dispatcher` action — moves `DISPUTED → COUNTERED`; countering is also legal from `COUNTERED`, where the new counter supersedes the previous one (from any state other than `DISPUTED` or `COUNTERED` the attempt fails with `ERR_SETTLEMENT_NOT_DISPUTED`). The counter request carries `counter_weight_lb` and `expected_settlement_version`; the version must match the settlement's current `version` or the counter is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the dispatcher to re-read before overwriting. A successful counter records `counter_weight_lb` and increments the settlement `version`.

From `COUNTERED`, two further sibling branches mirror those above. Re-disputing — a `ConsigneeAgent` action — moves `COUNTERED → DISPUTED` (any other state fails with `ERR_SETTLEMENT_NOT_COUNTERED`, HTTP 409) and is allowed only while the current time is still at or before `dispute_deadline_at` (`ERR_DISPUTE_WINDOW_CLOSED`); it records `disputed_weight_lb` when one is provided and increments the settlement `version`. Accepting the counter — also a `ConsigneeAgent` action — moves `COUNTERED → RESOLVED` (any other state fails with `ERR_SETTLEMENT_NOT_COUNTERED`): `dispute_adjustment_cents` is set to the shrink penalty as computed at delivery on the delivered-weight basis minus the shrink penalty recomputed on the countered-weight basis, `effective_delivered_weight_lb` becomes `counter_weight_lb`, the shrink fields and `final_amount_cents` are recomputed, and the settlement `version` increments.

Payment is the `CarrierAdmin`'s act and moves a settlement to `PAID`. It is permitted from `PENDING` or `RESOLVED`; from `PRELIMINARY` or from an already `PAID` settlement the attempt fails with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409), and from `DISPUTED` or `COUNTERED` it fails with `ERR_UNRESOLVED_DISPUTE` (HTTP 422). After the state check, payment is blocked while any welfare incident of severity `CRITICAL` on this load remains open in `REPORTED` or `UNDER_REVIEW` (`ERR_OPEN_CRITICAL_INCIDENT`, HTTP 422). Finally, paying directly from `PENDING` — without any dispute — additionally requires the dispute window to have run out: the current time must be strictly later than `dispute_deadline_at`, or the attempt fails with `ERR_DISPUTE_WINDOW_OPEN` (HTTP 422); a `RESOLVED` settlement carries no such waiting requirement. A successful payment sets `paid_at` to now and increments the settlement `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`; all reads return `200 OK`. The complete request and response content of each operation is specified by the narratives of §2 and §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/haul/shippers` | Create a shipper | CarrierAdmin |
| GET    | `/haul/shippers` | List shippers | Any |
| GET    | `/haul/shippers/{id}` | Get a shipper | Any |
| POST   | `/haul/drivers` | Create a driver (license number unique) | CarrierAdmin |
| GET    | `/haul/drivers` | List drivers, filterable by `status` and `hos_status` | Any |
| GET    | `/haul/drivers/{id}` | Get a driver including computed HOS fields | Any |
| POST   | `/haul/drivers/{id}/duty-events` | Append a duty event (Driver: own id only) | CarrierAdmin, Driver |
| GET    | `/haul/drivers/{id}/duty-events` | List duty events chronologically | Any |
| POST   | `/haul/trailers` | Create a trailer with its compartments atomically | CarrierAdmin |
| GET    | `/haul/trailers` | List trailers, filterable by `washout_status` | Any |
| GET    | `/haul/trailers/{id}` | Get a trailer | Any |
| GET    | `/haul/trailers/{id}/compartments` | List a trailer's compartments | Any |
| POST   | `/haul/trailers/{id}/washouts` | Record a biosecurity washout | WashoutOperator, CarrierAdmin |
| GET    | `/haul/trailers/{id}/washouts` | List washout events | Any |
| POST   | `/haul/loads` | Create a load in `DRAFT` | Dispatcher |
| GET    | `/haul/loads` | List loads with filters | Any |
| GET    | `/haul/loads/{id}` | Get a load | Any |
| POST   | `/haul/loads/{id}/allocations` | Allocate animals to a compartment (OCC on the load version) | Dispatcher |
| GET    | `/haul/loads/{id}/allocations` | List a load's allocations | Any |
| GET    | `/haul/allocations/{id}` | Get an allocation | Any |
| GET    | `/haul/allocations` | List allocations across loads | Any |
| POST   | `/haul/allocations/{id}/release` | Manually release an allocation (OCC on the load version) | Dispatcher |
| POST   | `/haul/loads/{id}/finalize-plan` | Finalize the plan: `DRAFT` to `PLANNED` | Dispatcher |
| POST   | `/haul/loads/{id}/reopen-plan` | Reopen the plan: `PLANNED` to `DRAFT` | Dispatcher |
| POST   | `/haul/loads/{id}/health-papers` | Attach a health paper to a load | ComplianceOfficer |
| GET    | `/haul/loads/{id}/health-papers` | List a load's health papers | Any |
| POST   | `/haul/health-papers/{id}/verify` | Verify a health paper (verifier differs from uploader) | ComplianceOfficer |
| POST   | `/haul/health-papers/{id}/reject` | Reject a health paper | ComplianceOfficer |
| POST   | `/haul/loads/{id}/brand-inspections` | Attach a brand inspection to a load | ComplianceOfficer |
| GET    | `/haul/loads/{id}/brand-inspections` | List a load's brand inspections | Any |
| POST   | `/haul/brand-inspections/{id}/verify` | Verify a brand inspection | ComplianceOfficer |
| POST   | `/haul/brand-inspections/{id}/reject` | Reject a brand inspection | ComplianceOfficer |
| POST   | `/haul/loads/{id}/verify-paperwork` | Advance `PLANNED` to `PAPERWORK_VERIFIED` | ComplianceOfficer |
| POST   | `/haul/loads/{id}/assign-driver` | Assign a driver: `PAPERWORK_VERIFIED` to `ASSIGNED` (OCC on the driver version) | Dispatcher |
| POST   | `/haul/loads/{id}/unassign-driver` | Unassign the driver: `ASSIGNED` to `PAPERWORK_VERIFIED` | Dispatcher |
| POST   | `/haul/loads/{id}/depart` | Depart: `ASSIGNED` to `IN_TRANSIT` | Driver |
| POST   | `/haul/loads/{id}/weather-holds` | Place a weather hold (`ASSIGNED` or `IN_TRANSIT` to `WEATHER_HOLD`) | Driver, Dispatcher |
| GET    | `/haul/loads/{id}/weather-holds` | List a load's weather holds | Any |
| POST   | `/haul/weather-holds/{id}/release` | Release an active weather hold | Dispatcher, Driver |
| POST   | `/haul/loads/{id}/rest-unload` | Begin a rest/unload stop: `IN_TRANSIT` to `REST_UNLOAD` | Driver |
| POST   | `/haul/loads/{id}/resume-transit` | Resume transit after the rest/unload minimum | Driver |
| POST   | `/haul/loads/{id}/arrive` | Arrive: `IN_TRANSIT` to `ARRIVED` | Driver |
| POST   | `/haul/loads/{id}/weight-tickets` | Record a scale ticket | ConsigneeAgent, Driver |
| GET    | `/haul/loads/{id}/weight-tickets` | List a load's weight tickets | Any |
| POST   | `/haul/loads/{id}/deliver` | Confirm delivery: `ARRIVED` to `DELIVERED` | ConsigneeAgent |
| POST   | `/haul/loads/{id}/cancel` | Cancel a load | Dispatcher |
| POST   | `/haul/incidents` | Report a welfare incident | Driver |
| GET    | `/haul/incidents` | List incidents with filters | Any |
| GET    | `/haul/incidents/{id}` | Get an incident | Any |
| POST   | `/haul/incidents/{id}/start-review` | Start review: `REPORTED` to `UNDER_REVIEW` | ComplianceOfficer |
| POST   | `/haul/incidents/{id}/close` | Close an incident: `UNDER_REVIEW` to `CLOSED` | ComplianceOfficer |
| GET    | `/haul/loads/{id}/settlement` | Get a load's settlement (array of zero or one) | Any |
| GET    | `/haul/settlements` | List settlements, filterable by `status` | Any |
| GET    | `/haul/settlements/{id}` | Get a settlement | Any |
| POST   | `/haul/settlements/{id}/dispute` | Dispute the delivered weight: `PENDING` to `DISPUTED` | ConsigneeAgent |
| POST   | `/haul/settlements/{id}/accept-original` | Accept the original delivered weight: `DISPUTED` to `RESOLVED` | ConsigneeAgent |
| POST   | `/haul/settlements/{id}/counter` | Counter with a different weight (OCC on the settlement version) | Dispatcher |
| POST   | `/haul/settlements/{id}/redispute` | Re-dispute: `COUNTERED` to `DISPUTED` | ConsigneeAgent |
| POST   | `/haul/settlements/{id}/accept-counter` | Accept the countered weight: `COUNTERED` to `RESOLVED` | ConsigneeAgent |
| POST   | `/haul/settlements/{id}/pay` | Pay a settlement: `PENDING` or `RESOLVED` to `PAID` | CarrierAdmin |
| POST   | `/haul/_clock/set_current_utc` | Set the logical clock | CarrierAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue lists identifiers and HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_INVALID_TICKET_WEIGHT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_TRAILER_NOT_FOUND` | 404 Not Found |
| `ERR_COMPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_HEALTH_PAPER_NOT_FOUND` | 404 Not Found |
| `ERR_BRAND_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_NOT_DRAFT` | 409 Conflict |
| `ERR_LOAD_NOT_PLANNED` | 409 Conflict |
| `ERR_LOAD_NOT_PAPERWORK_VERIFIED` | 409 Conflict |
| `ERR_LOAD_NOT_ASSIGNED` | 409 Conflict |
| `ERR_LOAD_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_LOAD_NOT_REST_UNLOAD` | 409 Conflict |
| `ERR_LOAD_NOT_ARRIVED` | 409 Conflict |
| `ERR_LOAD_NOT_HOLDABLE` | 409 Conflict |
| `ERR_LOAD_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_LOAD_NOT_REPORTABLE` | 409 Conflict |
| `ERR_TICKET_STATE_FORBIDDEN` | 409 Conflict |
| `ERR_PAPERWORK_NOT_PENDING` | 409 Conflict |
| `ERR_INCIDENT_NOT_REPORTED` | 409 Conflict |
| `ERR_INCIDENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PENDING` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DISPUTED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_COUNTERED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_UNRESOLVED_DISPUTE` | 422 Unprocessable Entity |
| `ERR_SPECIES_MIX_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_DRIVER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_DRIVER_NOT_HOS_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_TRAILER_NOT_CLEAN` | 422 Unprocessable Entity |
| `ERR_WEATHER_HOLD_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CONFINEMENT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_REST_UNLOAD` | 422 Unprocessable Entity |
| `ERR_OPEN_CRITICAL_INCIDENT` | 422 Unprocessable Entity |
| `ERR_PAPER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAPER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BRAND_INSPECTION_STALE` | 422 Unprocessable Entity |
| `ERR_PAPERWORK_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_DELIVERY_TICKET` | 422 Unprocessable Entity |
| `ERR_COMPARTMENT_HEAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COMPARTMENT_WEIGHT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MIXED_TRAILER_ALLOCATIONS` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_TOTAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GVWR_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LICENSE_NO` | 409 Conflict |
| `ERR_INVALID_BACKHAUL_LINK` | 422 Unprocessable Entity |
| `ERR_EVENT_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_DUTY_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_DUTY_EVENT_SEQUENCE` | 409 Conflict |
| `ERR_TRAILER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_OPEN` | 422 Unprocessable Entity |
