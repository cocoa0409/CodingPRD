# Evacuation Zone Management API — Product Requirements Document

## 1. Introduction

When a wildfire jumps a ridge or a hurricane track shifts overnight, the difference between an orderly evacuation and a catastrophe is the emergency operations center's ability to keep one authoritative picture of who is at risk, where they can shelter, which roads can carry them out, and when it is safe to return. This document specifies the **Evacuation Zone Management API**, the system of record that a county or city emergency-management organization uses to run a public-warning and evacuation response end to end. It coordinates the geographic zones under evacuation order, the population estimates that drive resourcing, the shelters and their staffed bed capacity, the road network and contraflow scheduling, the functional-needs household registry, the multi-channel public alerting pipeline (including federal IPAWS dispatch), and the re-entry credentialing that governs the return home.

The system is built around a small number of operational roles, each owning a distinct family of resources, working against a shared incident. A response moves through phases — a `DRAFT` incident is stood up, activated, driven through voluntary and mandatory zone orders, and finally brought to all-clear and stood down — and nearly every meaningful action ripples outward: raising a zone to mandatory advances the evacuation status of every household in it, may auto-check-in those already holding a shelter reservation, and can tip a shelter to full. Because these effects cascade across peer resources and because several operators may be acting at once, the API is precise about ordering, about optimistic-concurrency protection on the households being placed, and about the conserved quantities (reserved beds, IPAWS slots) that must never drift. The sections that follow define the global contracts first, then the business workflows where these rules are woven together.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `IncidentCommander`, `ShelterCoordinator`, `TrafficManager`, `Registrar`, and `PublicInfoOfficer`. Each role owns a distinct resource family — the commander owns incidents, zone evacuation orders, and the logical clock; the shelter coordinator owns shelters, staffing, and shelter assignments; the traffic manager owns routes and contraflow; the registrar owns the functional-needs registry and re-entry credentials; and the public-information officer owns alerting. All five roles may perform every read (GET) operation. Creating a shelter assignment is shared between the `ShelterCoordinator` and the `Registrar`; all other write operations are exclusive to the single owning role listed in the endpoint table of Section 4.

For all five roles the value carried in `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity. The server may accept and log it, but it never compares `X-User-ID` to any resource's `id`; authorization depends solely on the `X-User-Role`. There is no per-record ownership check in this domain — a `ShelterCoordinator` may operate any shelter, a `TrafficManager` any route, and so on.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a request that supplies a `limit` outside this range is a validation failure. The `offset` defaults to 0 and has no upper bound. List results are always ordered by `created_at` ascending (oldest first). Each list response includes `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page) in the `meta` object.

### 2.4. Common Resource Properties, Versioning, and Optimistic Concurrency

Every resource in this system carries a server-minted `id` — an opaque UUID with no type prefix — and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Every entity in this domain also carries an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource, whether the mutation is caused directly by an operator request or indirectly by a cascade from another resource; `updated_at` is refreshed to the current logical clock on every such mutation. When a cascade advances a child resource — for example a zone order that moves a household's status, or an incident all-clear that activates a credential — that child's own `version` increments and its `updated_at` is refreshed independently of the parent's.

Placing a household into a shelter is protected by **optimistic concurrency control** against the household record. The shelter-assignment create operation requires a non-optional `expected_registrant_version` field carrying the household `version` the client last observed. Because creating an assignment supersedes the household's prior active placement (releasing the old reservation and redirecting its beds), a create whose `expected_registrant_version` does not equal the target `Registrant`'s current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's view is stale, another placement has already advanced the registrant, and proceeding would overwrite a placement the client never saw. This is a pure comparison of the submitted version against the stored `Registrant.version`; it makes no assumption about wall-clock time or request ordering. No other endpoint in this system takes a version field.

### 2.5. The Logical Clock, Day/Night Population, and Time-Windowed Reconciliation

The server keeps a single **logical clock** rather than reading real wall-clock time. At startup, and before any clock-setting call has been made, the clock reads exactly `2026-03-01T00:00:00Z`. An `IncidentCommander` may advance it by supplying a `to_iso8601` instant. Setting the clock recomputes every clock-dependent derived field: each zone's day/night population estimate and each shelter's staffed and effective capacity. Windowed statuses (a credential past its validity end, a contraflow window past its end) are evaluated against this same logical clock.

Population at risk is a **day/night dual-variant** estimate. The system reads the UTC hour-of-day of the current logical clock as an integer from 0 through 23; the daytime window is the hours from 6 up to but not including 18 (that is, an hour at least 6 and less than 18). During daytime, a zone's `population_at_risk` is the resident headcount multiplied by the `daytime_occupancy_factor` plus the full `transient_population`, then rounded half-up to a whole number. During nighttime (any hour outside that window), the transient population is excluded entirely and `population_at_risk` is the resident headcount multiplied by the `nighttime_occupancy_factor`, rounded half-up to a whole number. This value is recomputed at zone creation, on every zone order change, whenever the clock is set, and on any read of the zone.

### 2.6. Cascading Order Postures and Hierarchical Consistency

This domain is **posture-driven**: a zone's `order_level` gates what may happen to the households in it, an incident's `status` gates what may happen to its zones and routes, and a shelter's `status` gates check-ins. State changes propagate downward as cascades, and each entity touched by a cascade has its `version` incremented and `updated_at` refreshed as described in Section 2.4. The cascades in this system reach as deep as three hops (a zone order can move households, auto-check-in their reservations, and tip shelters to full) and can be transitive across aggregates (an incident all-clear moves zones and then activates credentials on those zones). The specific propagation rules live with the workflows in Section 3; the invariant here is that a single request commits all of its cascade effects together, immediately and consistently, before the response is returned.

### 2.7. Shelter Capacity Accounting, Bed Conservation, and Rounding

Shelter capacity is a **dual-variant** calculation layered on staffing. For a given shelter at the current clock, the staffed bed count `staffed_capacity_now` is the sum of `staffed_beds` across that shelter's `SCHEDULED` staff shifts whose window covers the clock — that is, shifts whose `start_utc` is at or before the current instant and whose `end_utc` is at or after it (both bounds inclusive). The general-population usable capacity `effective_capacity` is then derived by taking the smaller of the shelter's `physical_capacity` and its `staffed_capacity_now` as the base, computing the functional-needs reservation as the base multiplied by `ada_reserved_pct` rounded up to the next whole bed, and subtracting that reservation from the base; the result is floored at 0 so it is never negative.

Against effective capacity the system tracks two conserved bed quantities. The `reserved_beds` total is the sum of `party_size` across all `RESERVED` assignments on the shelter; the `occupied_beds` total is the sum of `party_size` across all `CHECKED_IN` assignments. From these it exposes two availability views: `provisional_available`, the planning view used when deciding whether a new reservation fits, is `effective_capacity` minus both `reserved_beds` and `occupied_beds`; `confirmed_available`, the physical-occupancy view, is `effective_capacity` minus `occupied_beds` only and ignores reservations. Reserved and occupied beds are strictly conserved: reserving a household adds its `party_size` to `reserved_beds`, and cancelling that reservation subtracts exactly the same `party_size`, so a reserve-then-cancel pair leaves `reserved_beds` unchanged; a check-in moves that `party_size` out of `reserved_beds` and into `occupied_beds` with no net change to their sum. All bed counts, capacities, and population figures are integers; the only fractional inputs are the occupancy factors and `ada_reserved_pct`, and every rounding step named above is explicit (population rounds half-up to a whole number, the functional-needs reservation rounds up, availability is plain integer subtraction).

### 2.8. IPAWS Slot Budget as a Conserved Quantity

The federal alerting pipeline is rate-limited per incident. Each incident carries an `ipaws_daily_slot_budget` (an integer, defaulting to 5, never negative) capping how many IPAWS-bearing alerts may be in flight at once, and a computed `ipaws_slots_reserved` that counts, across all alerts targeting the incident's zones, those whose requested `channels` include IPAWS and whose `overall_status` is currently `QUEUED`. This count is a conserved quantity: queuing an IPAWS-bearing alert adds exactly one to it, and cancelling that queued alert (or the alert finishing its send) releases exactly one, so a queue-then-cancel pair nets to zero. The enforcement that guards this budget is described with the alerting workflow in Section 3.

### 2.9. Validation Precedence and Nested-Resource Resolution

When several checks could reject a request, they are evaluated in a fixed precedence so the returned `error_id` is deterministic. The global order is: first the user-context headers (`ERR_MISSING_USER_CONTEXT`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then existence of every resource named in the URL path — validated left to right so that a parent id is resolved before a child id and the earliest missing segment determines which `ERR_..._NOT_FOUND` is returned — then existence of every foreign key referenced in the request body (again the matching `ERR_..._NOT_FOUND`), then the optimistic-concurrency check on the household version (`ERR_STALE_VERSION`), then presence and type/range validity of required body fields (`ERR_VALIDATION`), then enum-membership and channel-array validity (`ERR_INVALID_ENUM`). Only after all of these pass are the domain-state and business rules evaluated. `ERR_VALIDATION` (HTTP 400) covers a missing required field or a value that violates its declared type or numeric range; `ERR_INVALID_ENUM` (HTTP 422) covers an enum field carrying a non-member value and covers a `channels` array that is empty or contains an unrecognized channel.

The domain-state and business checks that follow share the 409-conflict family and are themselves ordered per operation; their trigger conditions are described alongside the workflows they guard in Section 3. For any endpoint whose path names a parent and a child (for example a shelter's staff shifts, or a route's contraflow segments), the parent id is resolved first and the child id second.

## 3. Business Logic & Workflows

### 3.1. Standing Up and Winding Down an Incident

An `IncidentCommander` opens a response by creating an incident, supplying its human `name`, the `jurisdiction` operating the response, and the `hazard_type` driving the evacuation — one of `WILDFIRE`, `FLOOD`, `HURRICANE`, `HAZMAT`, or `TSUNAMI`. The commander may also set the `ipaws_daily_slot_budget`; when omitted it defaults to 5. A new incident begins in `status` `DRAFT` with `activated_at`, `all_clear_at`, and `clearance_estimate_minutes` unpopulated, and `ipaws_slots_reserved` at zero.

The incident advances through its phases by the commander submitting a target `to_phase`. Moving from `DRAFT` to `ACTIVE` is permitted only from `DRAFT` and stamps `activated_at` with the current logical clock. Activation matters system-wide because many operations require an active incident (see below). Moving from `ACTIVE` to `ALL_CLEAR` stamps `all_clear_at` and is blocked while any zone belonging to the incident is still at `order_level` `MANDATORY` — such an attempt is rejected with `ERR_ALL_CLEAR_BLOCKED`. When all-clear does proceed, it drives a two-hop transitive cascade: first, every zone of the incident currently at `VOLUNTARY` is moved to `RE_ENTRY_ALLOWED` (each such zone's `version` increments); zones at `NONE` are left untouched, and no `MANDATORY` zone can be present because all-clear is blocked otherwise. Second, for each zone that just became `RE_ENTRY_ALLOWED`, every credential on that zone in status `ISSUED` whose validity window contains the current clock — that is, `valid_from_utc` at or before now and now strictly before `valid_until_utc` — is moved to `ACTIVE`. Finally, moving from `ALL_CLEAR` to `STOOD_DOWN` (permitted only from `ALL_CLEAR`, and terminal) closes the response: every shelter of the incident in status `OPEN` or `FULL` is moved to `CLOSED`, and every `RESERVED` assignment on those shelters is `CANCELLED`, releasing its reserved beds. Each phase transition increments the incident's `version`.

On any read of an incident the system reports `clearance_estimate_minutes`, the estimated minutes to clear all zones under order. It is computed with a **pinned rounding order** that must not be rearranged. For each zone of the incident whose `order_level` is `VOLUNTARY` or `MANDATORY`, the system computes that zone's vehicle count as its `population_at_risk` divided by an average vehicle occupancy of 2.5 people per vehicle, rounded up to a whole number of vehicles, and accumulates these per-zone vehicle counts into a total. Separately it sums the `throughput_vph` of every route of the incident whose `status` is `OPEN` or `CONGESTED`. If that total throughput is zero, `clearance_estimate_minutes` is null. Otherwise it is the total vehicles divided by the total throughput, multiplied by 60, and rounded up to a whole number of minutes. The per-zone round-up-then-sum order is deliberate; summing populations first and dividing once would yield a different number and is explicitly not the rule.

### 3.2. Zones, Evacuation Orders, and the Household Cascade

A commander defines a zone under an incident by supplying the `incident_id`, a `name`, the boundary as a `geofence_wkt` polygon, and the `residential_population`. Optionally the zone carries a `transient_population` of daytime commuters and visitors (default 0), a `daytime_occupancy_factor` and a `nighttime_occupancy_factor` (each default 1.0, each constrained between 0 and 2 inclusive). A new zone starts at `order_level` `NONE` with `order_issued_at` unset and its `population_at_risk` computed from the current clock per Section 2.5. Zones may be listed and optionally filtered by their `incident_id`.

Evacuation orders drive a cyclic posture machine on the zone: the commander submits a target `level` (one of `NONE`, `VOLUNTARY`, `MANDATORY`, or `RE_ENTRY_ALLOWED`), and every order transition requires the owning incident to be `ACTIVE`; otherwise the order is rejected with `ERR_INCIDENT_NOT_ACTIVE`. The requested target must additionally be reachable from the zone's current `order_level`, or the request is rejected with `ERR_INVALID_ORDER_TRANSITION`. The legal operator-driven transitions and their household cascades are as follows, and each recomputes the zone's `population_at_risk`, stamps `order_issued_at` with the current clock, and increments the zone `version`:

- Raising `NONE → VOLUNTARY` advises the zone: every household in the zone at status `REGISTERED` moves to `ADVISED`.
- Raising `NONE → MANDATORY` or `VOLUNTARY → MANDATORY` orders the zone in a three-hop cascade. First, every household at `REGISTERED` or `ADVISED` moves to `ORDERED`. Second, for each such household whose `current_assignment_id` points to an assignment still in `RESERVED`, that assignment is auto-checked-in — moved to `CHECKED_IN` with `checked_in_at` stamped to now — and the household moves to `SHELTERED`. Third, each shelter that received an auto-check-in recomputes its `reserved_beds` and `occupied_beds`, and if `occupied_beds` has reached or exceeded `effective_capacity` it moves `OPEN → FULL`.
- Downgrading `MANDATORY → VOLUNTARY` moves every household at `ORDERED` back to `ADVISED`.
- Rescinding `VOLUNTARY → NONE` moves every household at `ADVISED` back to `REGISTERED`.
- Opening re-entry `MANDATORY → RE_ENTRY_ALLOWED` (permitted while the incident is `ACTIVE` or `ALL_CLEAR`) moves every household at `ORDERED` or `SHELTERED` to `CLEARED_FOR_REENTRY`.
- Re-evacuating `RE_ENTRY_ALLOWED → MANDATORY` reverses re-entry as a compensation: every credential on the zone currently `ACTIVE` is `SUSPENDED`, and every household at `CLEARED_FOR_REENTRY` moves back to `ORDERED`.

There is no direct operator order from `VOLUNTARY` to `RE_ENTRY_ALLOWED`; that transition happens only as the system-driven hop of an incident all-clear (Section 3.1), which additionally moves every household in the affected zone from `ADVISED` to `CLEARED_FOR_REENTRY`. A household's own status thus tracks the zone's posture at all times, and each cascade step increments the moved household's `version`.

### 3.3. The Functional-Needs Registry

A `Registrar` enrolls a household into a zone by supplying the `zone_id`, a `household_name`, and the `party_size` (at least 1 person). The registration optionally records a `functional_needs` classification — one of `NONE`, `MOBILITY`, `MEDICAL_ELECTRICITY`, `OXYGEN`, or `COGNITIVE` (default `NONE`) — and a `transport_required` flag (default false) marking households that need assisted transport. A new household's evacuation `status` is set at creation from the owning zone's current `order_level`: a household created into a `NONE` zone starts `REGISTERED`, into a `VOLUNTARY` zone starts `ADVISED`, and into a `MANDATORY` zone starts `ORDERED`. Its `current_assignment_id` is initially unset. Households may be listed and optionally filtered by `zone_id`. Once enrolled, a household's status is advanced only by the zone cascades of Section 3.2 and the sheltering transitions of Section 3.4.

### 3.4. Shelters, Staffing, and Sheltering Households

A `ShelterCoordinator` creates a shelter under an incident with its `incident_id`, a `name`, and its `physical_capacity` (the maximum beds the building holds). Optionally the shelter records an `ada_reserved_pct` (the fraction of usable beds held back for functional-needs access, between 0 and 1 inclusive, default 0.10) and a `power_backup` flag (default true) marking whether it can sustain electricity-dependent evacuees. A new shelter begins in `status` `STANDBY`. Its capacity fields — `staffed_capacity_now`, `effective_capacity`, `reserved_beds`, `occupied_beds`, `provisional_available`, and `confirmed_available` — are computed per Section 2.7 on every read. Shelters may be listed and optionally filtered by `incident_id`.

Staffing is scheduled as shifts. The coordinator schedules a shift by supplying the `shelter_id`, a `role_label` (for example NURSE or GENERAL), the `staffed_beds` the shift can cover, and its `start_utc` and `end_utc`, where the end must be strictly after the start. A shift begins `SCHEDULED`. Two `SCHEDULED` shifts on the same shelter must be separated by at least a 30-minute handover buffer — the later shift's `start_utc` must be at least 30 minutes after the earlier shift's `end_utc` — otherwise the schedule request is rejected with `ERR_STAFF_SHIFT_OVERLAP`. A shift may be cancelled, moving it `SCHEDULED → CANCELLED`; both scheduling and cancelling a shift recompute the parent shelter's `staffed_capacity_now` and `effective_capacity`. A shelter's staff shifts may be listed under the shelter.

A coordinator opens a shelter by moving it `STANDBY → OPEN`, which is permitted only when `staffed_capacity_now` is greater than zero — at least one `SCHEDULED` shift must cover the current clock — and is otherwise rejected with `ERR_INVALID_STATE`. A shelter reaches `FULL` automatically: after any check-in, if `occupied_beds` has reached or exceeded `effective_capacity` the shelter moves `OPEN → FULL`; conversely, after a check-out or a reservation cancellation, if `occupied_beds` falls below `effective_capacity` a `FULL` shelter moves back to `OPEN`. The boundary is inclusive — full fires when occupied beds equal effective capacity, not only when they exceed it. Closing a shelter directly from `STANDBY` is always allowed. Closing from `OPEN` is permitted only when no assignment on the shelter is `CHECKED_IN` (otherwise `ERR_INVALID_STATE`); when it proceeds, every `RESERVED` assignment on the shelter is `CANCELLED`, releasing its reserved beds and clearing each affected household's `current_assignment_id`. `CLOSED` is terminal.

Placing a household is where reservations, superseding, and optimistic concurrency meet. A `ShelterCoordinator` or a `Registrar` reserves a bed block by supplying the `registrant_id`, the destination `shelter_id`, and the `expected_registrant_version` described in Section 2.4. The household's owning zone must be under order — its `order_level` must be `VOLUNTARY` or `MANDATORY` — otherwise the reservation is rejected with `ERR_ZONE_NOT_UNDER_ORDER`. On success the new assignment copies the household's `party_size` (this is the bed count it consumes), begins `RESERVED`, adds that `party_size` to the shelter's `reserved_beds`, and is recorded as the household's `current_assignment_id`, incrementing the household's `version`. Because a household may hold only one active placement, creating a new assignment **supersedes** any prior active one: if the household already had a `RESERVED` or `CHECKED_IN` assignment, that older assignment is `CANCELLED` and its beds released. This supersede semantics is exactly why the create is version-guarded: a stale `expected_registrant_version` means another placement already moved the household, and the create is rejected with `ERR_STALE_VERSION`.

An assignment's later life is driven by an `action` of `CHECK_IN`, `CHECK_OUT`, or `CANCEL`, exclusive to the `ShelterCoordinator`. A `CHECK_IN` moves the assignment `RESERVED → CHECKED_IN` and is guarded by an ordered set of checks: the shelter must not be `CLOSED` (else `ERR_SHELTER_CLOSED`), the shelter must be `OPEN` and not `STANDBY` (a `STANDBY` shelter yields `ERR_SHELTER_NOT_OPEN`), the assignment must currently be `RESERVED` (else `ERR_INVALID_STATE`), then a safety rule requires that if the household's `functional_needs` is `MEDICAL_ELECTRICITY` or `OXYGEN` the shelter's `power_backup` must be true (else `ERR_SHELTER_NOT_POWER_CAPABLE`), and finally a capacity rule requires that `occupied_beds` plus the assignment's `party_size` not exceed `effective_capacity` (else `ERR_SHELTER_CAPACITY_EXCEEDED`). These five checks are evaluated in that order, so a closed shelter surfaces as `ERR_SHELTER_CLOSED` before any capacity concern. On success the check-in stamps `checked_in_at` to now, moves that `party_size` out of `reserved_beds` and into `occupied_beds`, moves the owning household to `SHELTERED`, and if `occupied_beds` has reached or exceeded `effective_capacity` tips the shelter `OPEN → FULL`. A `CHECK_OUT` moves the assignment `CHECKED_IN → CHECKED_OUT`, releases its `party_size` from `occupied_beds`, clears the household's `current_assignment_id`, and if the shelter was `FULL` and now has room moves it `FULL → OPEN`. A `CANCEL` moves a `RESERVED` assignment to `CANCELLED`, releases its `party_size` from `reserved_beds`, and clears the household's `current_assignment_id`. Assignments may be listed and filtered by `registrant_id` and/or `shelter_id`.

### 3.5. Evacuation Routes and Contraflow

A `TrafficManager` creates an evacuation route under an incident with its `incident_id`, a `name`, a physical `corridor_label`, and its `throughput_vph` (the vehicles per hour the corridor can move, at least 1). A route begins `PLANNED`. Opening a route `PLANNED → OPEN` requires the owning incident to be `ACTIVE`, otherwise it is rejected with `ERR_INCIDENT_NOT_ACTIVE`. An open route may be flagged `OPEN → CONGESTED` and cleared back `CONGESTED → OPEN`. Closing a route from either `OPEN` or `CONGESTED` moves it to `CLOSED` and cancels every contraflow segment on that route currently `SCHEDULED` or `ACTIVE` (each moved to `CANCELLED`). `CLOSED` is terminal. Only routes in `OPEN` or `CONGESTED` contribute their `throughput_vph` to the incident's clearance estimate of Section 3.1. Routes may be listed and optionally filtered by `incident_id`.

Contraflow reverses a road segment during a scheduled window. The traffic manager schedules a segment by supplying the parent `route_id`, the `segment_key` identifying the physical road segment, a `direction` of `INBOUND_REVERSED` or `OUTBOUND`, and a half-open window from `window_start_utc` (inclusive) to `window_end_utc` (exclusive), where the end must be strictly after the start. A new segment begins `SCHEDULED`. Two `SCHEDULED` or `ACTIVE` segments on the same `route_id` and `segment_key` must not overlap on their half-open windows; adjacency, where one window's end equals the next window's start, is permitted, but any true overlap is rejected with `ERR_CONTRAFLOW_WINDOW_OVERLAP`. A segment is driven by a `state` of `ACTIVE` or `CANCELLED`. Activating `SCHEDULED → ACTIVE` requires the parent route to be `OPEN` (else `ERR_ROUTE_NOT_OPEN`) and the current clock to fall within the window — `window_start_utc` at or before now and now strictly before `window_end_utc` — otherwise `ERR_INVALID_STATE`. An active segment completes automatically to `COMPLETED` once the clock reaches or passes `window_end_utc`. A segment may be cancelled from either `SCHEDULED` or `ACTIVE`, moving it to `CANCELLED`; `CANCELLED` and `COMPLETED` are terminal. A route's contraflow segments may be listed under the route.

### 3.6. Re-Entry Access Credentials

A `Registrar` issues a re-entry credential tying a household to the zone it may re-enter, supplying the `zone_id`, the holder's `registrant_id`, a `credential_type` of `RESIDENT`, `ESSENTIAL_WORKER`, or `UTILITY`, and a validity window from `valid_from_utc` (inclusive) to `valid_until_utc` (exclusive), where the end must be strictly after the start. A new credential begins `ISSUED`. Credentials may be listed and filtered by `zone_id` and/or `registrant_id`.

A credential is driven by a `state` of `ACTIVE` or `REVOKED`. Activating a credential — moving `ISSUED → ACTIVE`, or reactivating `SUSPENDED → ACTIVE` — requires the owning zone to be at `order_level` `RE_ENTRY_ALLOWED` (else `ERR_ZONE_NOT_REENTRY`) and the current clock to fall within the validity window, `valid_from_utc` at or before now and now strictly before `valid_until_utc` (else `ERR_CREDENTIAL_WINDOW_INVALID`). As described in Sections 3.1 and 3.2, the system also activates eligible `ISSUED` credentials automatically when an incident all-clear opens their zone to re-entry, and it suspends `ACTIVE` credentials automatically (`ACTIVE → SUSPENDED`) when a zone is re-evacuated back to `MANDATORY`. A credential may be revoked from `ISSUED`, `ACTIVE`, or `SUSPENDED`, moving it to `REVOKED`. Credentials also expire automatically from `ISSUED` or `ACTIVE` to `EXPIRED` once the clock reaches or passes `valid_until_utc`. `EXPIRED` and `REVOKED` are terminal.

### 3.7. Multi-Channel Alerting and IPAWS Dispatch

A `PublicInfoOfficer` drafts a public warning targeting a zone, supplying the `zone_id`, the `message` body, a `severity` of `ADVISORY`, `WATCH`, `WARNING`, or `EXTREME`, and the requested delivery `channels` — a non-empty subset of `WEA`, `EAS`, `IPAWS`, and `SMS`. An alert tracks each channel as an independent parallel dimension: `wea_status`, `eas_status`, `ipaws_status`, and `sms_status` are each set to `PENDING` if that channel was requested and to `NA` if it was not, and each later resolves to `SENT` or `FAILED`. The alert's `overall_status` is a rollup that begins `DRAFT`. Alerts may be listed and optionally filtered by `zone_id`.

The officer moves an alert with a `state` of `QUEUED` or `CANCELLED`. Queuing `DRAFT → QUEUED` is where the IPAWS budget of Section 2.8 is enforced: if the requested `channels` include `IPAWS`, the queue is permitted only when the count of the incident's already-in-flight IPAWS alerts — those on the incident's zones with `IPAWS` among their channels and `overall_status` of `QUEUED`, `SENT`, or `PARTIAL` — is strictly less than the incident's `ipaws_daily_slot_budget`; otherwise the queue is rejected with `ERR_IPAWS_SLOTS_EXHAUSTED`. On queuing, an IPAWS-bearing alert begins counting toward the incident's `ipaws_slots_reserved`. A queued alert may be cancelled `QUEUED → CANCELLED`, which releases its IPAWS reservation as a compensation, restoring `ipaws_slots_reserved` to its pre-queue value.

Delivery results arrive per channel: the officer records a `channel` (one of the requested channels) and its `result` (`SENT` or `FAILED`), which sets that channel's own status dimension. The `overall_status` can leave `QUEUED` only once every requested channel has resolved. When all resolve `SENT`, the alert rolls to `SENT`; when they resolve to a mix of at least one `SENT` and at least one `FAILED`, it rolls to `PARTIAL`; when every requested channel resolves `FAILED`, it rolls to `FAILED`. Each of these terminal rollups releases the alert's IPAWS `QUEUED` reservation so it no longer counts toward `ipaws_slots_reserved`. `SENT`, `PARTIAL`, `FAILED`, and `CANCELLED` are terminal for an alert.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`; state transitions, cancellations, and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. Setting the logical clock returns HTTP 200 with an empty `data` object. The request and response bodies and side effects for each endpoint are specified in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /evac/_clock/set_current_utc | Set the server logical clock | IncidentCommander |
| POST | /evac/incidents | Create an incident (DRAFT) | IncidentCommander |
| GET | /evac/incidents/{id} | Fetch an incident (with computed IPAWS slots and clearance estimate) | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/incidents/{id}/phase | Advance incident phase (ACTIVE / ALL_CLEAR / STOOD_DOWN) | IncidentCommander |
| POST | /evac/zones | Create a zone under an incident | IncidentCommander |
| GET | /evac/zones/{id} | Fetch a zone | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/zones | List zones, optionally filtered by incident_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/zones/{id}/order | Set the zone evacuation-order level | IncidentCommander |
| POST | /evac/shelters | Create a shelter (STANDBY) | ShelterCoordinator |
| GET | /evac/shelters/{id} | Fetch a shelter (with computed capacity fields) | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/shelters | List shelters, optionally filtered by incident_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/shelters/{id}/status | Open or close a shelter | ShelterCoordinator |
| GET | /evac/shelters/{id}/staff-shifts | List a shelter's staff shifts | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/staff-shifts | Schedule a staffing shift on a shelter | ShelterCoordinator |
| POST | /evac/staff-shifts/{id}/cancel | Cancel a scheduled staff shift | ShelterCoordinator |
| POST | /evac/routes | Create an evacuation route (PLANNED) | TrafficManager |
| GET | /evac/routes/{id} | Fetch a route | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/routes | List routes, optionally filtered by incident_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/routes/{id}/status | Transition route posture (OPEN / CONGESTED / CLOSED) | TrafficManager |
| GET | /evac/routes/{id}/contraflow-segments | List a route's contraflow segments | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/contraflow-segments | Schedule a contraflow window on a route segment | TrafficManager |
| POST | /evac/contraflow-segments/{id}/status | Activate or cancel a contraflow segment | TrafficManager |
| POST | /evac/registrants | Register a household in a zone | Registrar |
| GET | /evac/registrants/{id} | Fetch a registrant | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/registrants | List registrants, optionally filtered by zone_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/shelter-assignments | Reserve a shelter bed block for a household (supersedes prior; OCC on registrant) | ShelterCoordinator, Registrar |
| GET | /evac/shelter-assignments/{id} | Fetch a shelter assignment | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/shelter-assignments | List assignments, filtered by registrant_id and/or shelter_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/shelter-assignments/{id}/status | Check in / check out / cancel an assignment | ShelterCoordinator |
| POST | /evac/access-credentials | Issue a re-entry access credential | Registrar |
| GET | /evac/access-credentials/{id} | Fetch an access credential | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/access-credentials | List credentials, filtered by zone_id and/or registrant_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/access-credentials/{id}/status | Activate or revoke an access credential | Registrar |
| POST | /evac/alerts | Draft a multi-channel alert for a zone | PublicInfoOfficer |
| GET | /evac/alerts/{id} | Fetch an alert dispatch (per-channel and overall status) | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| GET | /evac/alerts | List alerts, optionally filtered by zone_id | IncidentCommander, ShelterCoordinator, TrafficManager, Registrar, PublicInfoOfficer |
| POST | /evac/alerts/{id}/status | Queue or cancel an alert | PublicInfoOfficer |
| POST | /evac/alerts/{id}/channel-result | Record a per-channel delivery result | PublicInfoOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_USER_CONTEXT | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_ENUM | 422 |
| ERR_INCIDENT_NOT_FOUND | 404 |
| ERR_ZONE_NOT_FOUND | 404 |
| ERR_SHELTER_NOT_FOUND | 404 |
| ERR_STAFF_SHIFT_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_CONTRAFLOW_NOT_FOUND | 404 |
| ERR_REGISTRANT_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_CREDENTIAL_NOT_FOUND | 404 |
| ERR_ALERT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INCIDENT_NOT_ACTIVE | 409 |
| ERR_INVALID_ORDER_TRANSITION | 409 |
| ERR_ALL_CLEAR_BLOCKED | 409 |
| ERR_SHELTER_CLOSED | 409 |
| ERR_SHELTER_NOT_OPEN | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_ZONE_NOT_REENTRY | 409 |
| ERR_ROUTE_NOT_OPEN | 409 |
| ERR_ZONE_NOT_UNDER_ORDER | 409 |
| ERR_SHELTER_NOT_POWER_CAPABLE | 409 |
| ERR_STAFF_SHIFT_OVERLAP | 409 |
| ERR_CONTRAFLOW_WINDOW_OVERLAP | 409 |
| ERR_CREDENTIAL_WINDOW_INVALID | 409 |
| ERR_SHELTER_CAPACITY_EXCEEDED | 409 |
| ERR_IPAWS_SLOTS_EXHAUSTED | 409 |
