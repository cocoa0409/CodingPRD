# Commercial Fishing Quota API — Product Requirements Document

## 1. Introduction

Alaska's catch-share fisheries run on a tight loop: a vessel holds quota shares for a fishery and season, plans trips against regulatory area openings, reports every haul, declares landings at the dock, and settles crew shares once the trip's books close — all under observer coverage rules, vessel monitoring requirements, and a compliance-points regime that can ground a vessel mid-season. This document specifies an API that manages that loop end to end: vessel and permit administration, annual quota share holdings, season and area openings with total allowable catch enforcement, trip planning and execution, catch reporting, landing declaration and verification, quota leasing between vessels, observer scheduling, gear tracking, trip expense adjudication, crew settlement, and violation adjudication with appeals.

Seven distinct roles interact with the platform under a deliberate segregation of duties: the regulator administers the fishery and drives time itself through a logical clock; vessel owners negotiate quota leases and approve settlements; captains operate trips and file declarations; settlement clerks compute payouts but may not approve them; observers confirm and debrief their own assignments. Because lease negotiation, trip rescheduling, observer assignment, and settlement recalculation all mutate shared state that other actors read before writing, those four write paths are guarded by optimistic concurrency. The sections that follow define the global contracts every endpoint obeys, then walk each business workflow in narrative form.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The seven declared roles, spelled exactly as shown, are `VesselOwner`, `Captain`, `CrewMember`, `Observer`, `ObserverCoordinator`, `FisheriesRegulator`, and `SettlementClerk`.

Authorization is two-layered. First, the caller's role must be permitted on the endpoint; a role that is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Second, entity-backed roles must pass an ownership check against the target resource; a caller whose role is allowed but whose identity fails ownership is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The identity behind `X-User-ID` depends on the role:

- When `X-User-Role` is `VesselOwner`, `X-User-ID` is the `id` of the acting `Vessel`; ownership checks on any resource that references a vessel compare the resource's vessel foreign-key field to `X-User-ID`. When `X-User-Role` is `Captain`, the same rule applies — `X-User-ID` is the `id` of the vessel the captain operates, and ownership is likewise established by matching a resource's vessel reference to `X-User-ID`. For creation payloads that name a vessel (trip planning, expense recording), the caller's `X-User-ID` must equal the `vessel_id` in the payload.
- When `X-User-Role` is `CrewMember`, `X-User-ID` is the `id` of the acting `CrewShareContract`; ownership checks require it to be an `ACTIVE` crew share contract on the vessel relevant to the request.
- When `X-User-Role` is `Observer`, `X-User-ID` is the `id` of the acting `Observer`; ownership checks compare it to the assignment's `observer_id`.
- When `X-User-Role` is `ObserverCoordinator`, `FisheriesRegulator`, or `SettlementClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but does not compare it to any entity's `id`.

All read endpoints (every list and every single-resource retrieval) are open to all seven roles.

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
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints; `has_more` is `true` exactly when `offset` plus the number of returned rows is less than `total_count`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. Either parameter may be sent as a stringified integer; a non-integer value is not an error and falls back to the default, and out-of-range values are clamped into range. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless stated otherwise, list results are sorted by `created_at` in ascending order, with ties broken by creation order (the order in which resources were minted). List endpoints also support exact-match filtering via query parameters on selected fields of the listed resource (for example `status`, `vessel_id`, `fishery_code`, `season_year`, `gear_type`, `area_code`, `trip_id`, `observer_id`, `from_vessel_id`, `to_vessel_id`); unrecognized query parameters are ignored.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id`, a server-minted UUID with no type prefix. Resources also carry `created_at` and `updated_at` timestamps in ISO 8601 UTC format with three fractional digits, and a `version` integer. Every mutation of a resource increments its `version` by exactly one and refreshes `updated_at`; this applies uniformly to state transitions, field edits, and system-driven cascades (for example, accepting a quota lease increments the transfer's `version` and also bumps each affected holding's `version`).

Three resource kinds are append-only event records: catch reports, gear events, and VMS pings. These carry only `id` and `created_at` — both `updated_at` and `version` are absent — and once created they cannot be modified or deleted.

### 2.5. The Logical Clock and Season Timers

The platform never reads wall-clock time. A logical clock governs all time-based behavior, and before any advance call it reads exactly 2026-08-01T00:00:00Z. A `FisheriesRegulator` advances the clock through an admin-only test-driving capability that takes a target instant `to_iso8601` and returns the resulting `current_utc`. The clock may only move forward: a `to_iso8601` earlier than or equal to the current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400).

Each clock advance fires every time-based transition whose threshold the new reading has crossed:

- A season opening in `SCHEDULED` moves to `OPEN` once the clock reaches its `opens_at` (the opening instant is inclusive).
- An opening in `OPEN` moves to `CLOSED` once the clock passes its `closes_at`, and every trip still `PLANNED` on that opening is cancelled, with each cancelled trip's non-terminal observer assignments cancelled in turn.
- A permit in `ISSUED` or `SUSPENDED` moves to `EXPIRED` once the clock passes its `valid_to`.
- A quota transfer in `PROPOSED`, `COUNTERED`, or `ACCEPTED` moves to `EXPIRED` once the clock passes the end of the transfer's `season_year` — that is, past 23:59:59 UTC on December 31 of that year. An `ACCEPTED` transfer expiring performs a compensating release of its reserved pounds (see §3.7).
- A quota share holding in `ACTIVE` moves to `CLOSED` once the clock passes the end of its `season_year`.

### 2.6. Optimistic Concurrency Control

Four write operations require the caller to supply the last-observed `version` of a parent entity, and the field is non-optional on those operations:

- Assigning an observer to an assignment requires `expected_observer_version`, matching the target `Observer`'s current `version`. The caller is selecting an observer from an availability picture; if that observer's version has advanced since the caller last read it (for example, the observer has since been assigned elsewhere), the write is refused rather than allowed to proceed on a stale picture.
- Rescheduling a trip requires `expected_trip_version`, matching the trip's current `version`; a client whose planned window no longer reflects the trip's current state is refused.
- Recalculating a settlement requires `expected_settlement_version`, matching the settlement's current `version`; the recalculation basis (expense set, dispute round) must be current.
- Countering a quota transfer requires `expected_transfer_version`, matching the transfer's current `version`; a counter supersedes the prior negotiation round, so the caller must have observed the latest round.

In all four cases, a value that does not match the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these four accepts a version field.

### 2.7. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic:

1. **Authentication context** — both headers present and the role declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Authorization and ownership** — the role must be allowed on the endpoint (`ERR_FORBIDDEN_ROLE`, 403), and entity-backed callers must satisfy the ownership rule (`ERR_NOT_RESOURCE_OWNER`, 403) at this same tier.
3. **Existence** — path identifiers and body-referenced identifiers must resolve to existing resources (the 404 family, §2.9). A body field that must be a string or an enum but carries the id of a referenced resource (`vessel_id`, `season_opening_id`, `from_vessel_id`, `to_vessel_id`, `observer_id`) surfaces a malformed or invalid value as `ERR_INVALID_REQUEST` (400) from tier 9 before the existence lookup is reached, so a non-string id or an invalid enum fails shape first.
4. **Optimistic concurrency** — where an endpoint declares an expected-version field, it must equal the parent entity's current `version` (`ERR_STALE_VERSION`, 412).
5. **State preconditions** — the target resource must be in the state the transition requires (state-specific 409 errors such as `ERR_TRIP_NOT_PLANNED`, `ERR_TRANSFER_NOT_OPEN`, or `ERR_SETTLEMENT_NOT_DRAFT`).
6. **Safety gates** — observer coverage at departure, observer debrief at landing verification, gear sufficiency at departure, and observer certification level at assignment (`ERR_OBSERVER_COVERAGE_MISSING`, `ERR_OBSERVER_NOT_DEBRIEFED`, `ERR_GEAR_SHORTAGE` are 409; `ERR_OBSERVER_CERT_INSUFFICIENT` is 422).
7. **Temporal rules** — opening-window containment, opening overlap, vessel trip overlap, and observer double-booking with its rest buffer (`ERR_OUTSIDE_OPENING_WINDOW`, `ERR_OPENING_WINDOW_OVERLAP`, `ERR_TRIP_WINDOW_OVERLAP`, `ERR_OBSERVER_DOUBLE_BOOKED`; all 409). Within a single request the temporal rules are evaluated in the order listed here, and the temporal tier as a whole runs before the cross-entity link tier — so a trip-planning call whose window breaches an opening rule and whose vessel is also inactive surfaces the temporal error first.
8. **Cross-entity link state** — vessels must be `ACTIVE`, fishery permits must be `ISSUED`, and quota holdings must exist for the required fishery and year (`ERR_VESSEL_NOT_ACTIVE` and `ERR_PERMIT_NOT_ACTIVE` are 409; `ERR_QUOTA_HOLDING_NOT_FOUND` is 404).
9. **Shape and consistency** — malformed bodies, wrong types, invalid enum values, non-positive quantities, inverted time windows, clock regression, self-transfers, duplicate holdings or licenses, duplicate declarations or settlements, illegal gear events, and missing active crew (`ERR_INVALID_REQUEST`, `ERR_INVALID_TIME_WINDOW`, `ERR_CLOCK_REGRESSION` are 400; `ERR_DUPLICATE_HOLDING`, `ERR_DUPLICATE_LICENSE`, `ERR_DECLARATION_EXISTS`, `ERR_SETTLEMENT_EXISTS` are 409; `ERR_SELF_TRANSFER`, `ERR_INVALID_GEAR_EVENT`, `ERR_NO_ACTIVE_CREW` are 422). A non-object or missing JSON body is treated as an empty object, so missing-field failures surface as `ERR_INVALID_REQUEST`. String fields must be non-empty; an empty string is `ERR_INVALID_REQUEST`. A timestamp field that is not a string, or a string that is not parseable ISO 8601, is `ERR_INVALID_REQUEST`; a parseable timestamp without an explicit offset is read as UTC. Decimal values are not rounded on ingestion: integer fields reject non-integer types outright (`ERR_INVALID_REQUEST`), while fields that admit fractional values (`share_points`, `latitude`, `longitude`) store the submitted number as-is.
10. **Fiscal gates** — quota sufficiency and settlement solvency (`ERR_QUOTA_EXCEEDED` is 402; `ERR_SETTLEMENT_UNDERWATER` is 422).

### 2.8. Precision, Rounding, and Boundary Semantics

All pound amounts (quota, catch, landings, TAC) are whole integers and never rounded. All monetary amounts are integer cents. Percentage-derived money is rounded half-up to whole cents at exactly the steps named in §3 — the settlement processing fee, the vessel share, each transfer-fee tier component, and the landing discrepancy tolerance — and nowhere else. Crew payouts are floored per member with the remainder distributed cent by cent, never rounded. Observer day counts are rounded up to whole days per assignment.

Boundary semantics matter and are pinned per rule: the TAC closure threshold is inclusive (landing exactly up to `tac_pounds` closes the opening); the landing discrepancy tolerance is inclusive (a difference exactly equal to the tolerance passes); the opening instant is inclusive (the clock reaching `opens_at` opens the fishery); closing instants are exclusive in the other direction (the clock must pass `closes_at` to close); the 72-hour observer-duration threshold is strict (exactly 72 hours does not trigger the requirement); and the 120-minute VMS gap threshold is strict (a gap of exactly 120 minutes is compliant).

### 2.9. Nested Resources and Left-to-Right Existence Checking

Several resources are addressed through their parent in the URL — a permit through its vessel, a catch report through its trip, and so on. Path identifiers are validated left to right: the vessel id is checked before the permit id, the trip id before the declaration, the gear asset id before its events. A failure at any segment yields the not-found error for that segment's resource. Identifiers referenced in request bodies — `vessel_id`, `season_opening_id`, `from_vessel_id`, `to_vessel_id`, `observer_id`, and holding lookups by fishery and year — must likewise resolve to existing resources.

The resource-specific not-found errors are: `ERR_VESSEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_QUOTA_HOLDING_NOT_FOUND`, `ERR_SEASON_OPENING_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_LANDING_DECLARATION_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_OBSERVER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_CONTRACT_NOT_FOUND`, `ERR_EXPENSE_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_GEAR_ASSET_NOT_FOUND`, and `ERR_VIOLATION_NOT_FOUND` — all HTTP 404. `ERR_QUOTA_HOLDING_NOT_FOUND` doubles as the failure when no holding matches a required fishery-and-year combination implied by a request body.

### 2.10. Cascading State Propagation and Compensating Actions

State changes rarely stay on one entity. A vessel suspended for low compliance standing drags its permits to `SUSPENDED` and cancels its planned trips, and each cancelled trip in turn cancels its non-terminal observer assignments; every assignment cancellation recomputes the affected observer's availability. An opening that closes — on schedule or early — cancels its planned trips with the same downstream cascade. An adjudicated violation deducts points and may itself trigger the vessel suspension cascade. An accepted lease that expires at season end performs a compensating release, returning the reserved pounds to the leasing-out vessel's availability. Releasing a confirmed observer from a trip that still needs coverage auto-creates a fresh request so the trip is not silently left uncovered. Two transitions bubble upward rather than downward: finalizing a landing declaration advances its trip, and paying a settlement settles the trip. These cascades are described in context in §3; this section exists to state the general principle that the platform favors explicit compensating actions over silent drift.

## 3. Business Logic & Workflows

### 3.1. Vessel Registration, Permits, and Compliance Standing

A vessel enters the system when a `FisheriesRegulator` registers it with a `vessel_name`, a `license_number` that must be unique across all vessels (a duplicate is rejected with `ERR_DUPLICATE_LICENSE`, HTTP 409), a `home_port`, a `length_ft` that must be greater than zero, an `observer_coverage_class` of `FULL`, `PARTIAL`, or `EXEMPT`, and an optional `vms_unit_id` identifying the vessel's monitoring transponder. A freshly registered vessel is in `REGISTERED` status with `compliance_points` at 100.

Activation moves a vessel from `REGISTERED` to `ACTIVE`; only a regulator may activate, and attempting it from any other status is rejected with `ERR_VESSEL_NOT_ACTIVE` (HTTP 409). Suspension is never manual: when a violation adjudication pushes a vessel's `compliance_points` below 50, the vessel drops from `ACTIVE` to `SUSPENDED` automatically, and the cascade fires — every permit of the vessel in `ISSUED` moves to `SUSPENDED`, and every trip of the vessel in `PLANNED` moves to `CANCELLED`, with each cancelled trip's non-terminal observer assignments cancelled as well.

A regulator may reinstate a `SUSPENDED` vessel to `ACTIVE`, but only when its `compliance_points` have recovered to at least 50; below that threshold the attempt is rejected with `ERR_COMPLIANCE_TOO_LOW` (HTTP 409), and attempting reinstatement from any status other than `SUSPENDED` is rejected with `ERR_VESSEL_NOT_ACTIVE`. The status check runs before the points check, so a non-`SUSPENDED` vessel with low points surfaces `ERR_VESSEL_NOT_ACTIVE`. Reinstatement restores the vessel's `SUSPENDED` permits to `ISSUED`, but only those whose `valid_to` is still ahead of the current logical clock — a permit whose validity has already lapsed stays down and will expire on schedule.

Decommissioning is terminal. From `REGISTERED`, `ACTIVE`, or `SUSPENDED`, a regulator may move a vessel to `DECOMMISSIONED` provided the vessel has no trip in `PLANNED`, `DEPARTED`, `RETURNED`, or `LANDING_FINALIZED`; open trips block decommissioning with `ERR_VESSEL_HAS_OPEN_TRIPS`. Decommissioning from `DECOMMISSIONED` itself is rejected with `ERR_VESSEL_NOT_ACTIVE` (HTTP 409). Decommissioning revokes every permit of the vessel in `ISSUED` or `SUSPENDED`, moving each to `REVOKED`; permits already `EXPIRED` or `REVOKED` are left untouched.

Permits themselves are issued by a regulator to a specific vessel, carrying a `fishery_code` (one of `HALIBUT`, `SABLEFISH`, `POLLOCK`, `PACIFIC_COD`), a `gear_type` (one of `TRAWL_NET`, `LONGLINE`, `POT`, `GILLNET`), and a validity window `valid_from` to `valid_to`. The window must be well-formed: a `valid_to` that is not later than `valid_from` is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400). A new permit starts `ISSUED`. A regulator may revoke a permit in `ISSUED` or `SUSPENDED`, moving it to `REVOKED`; revoking from any other status is rejected with `ERR_PERMIT_NOT_ACTIVE`. Permits also expire by the clock (§2.5), moving from `ISSUED` or `SUSPENDED` to `EXPIRED` once time passes `valid_to`.

### 3.2. Quota Share Holdings and Season Openings

Before a vessel can fish or lease, a regulator allocates it an annual quota share holding: a `fishery_code`, a `season_year` such as 2026, and an `initial_pounds` allocation that must be greater than zero. Allocation is open with respect to vessel status — the vessel need only exist, and the allocation goes through even for a `REGISTERED`, `SUSPENDED`, or `DECOMMISSIONED` vessel. The combination of vessel, fishery, and season year is unique — a second allocation for the same triple is rejected with `ERR_DUPLICATE_HOLDING` (HTTP 409). A holding starts `ACTIVE` with `landed_pounds` at zero, and it closes (`ACTIVE` → `CLOSED`) when the logical clock passes the end of its season year.

Two availability figures are derived from each holding, and the platform uses them in different places. The **committed** figure, `available_committed_pounds`, is the holding's `initial_pounds` minus its `landed_pounds`, plus pounds leased in, minus pounds leased out — where leased amounts count only transfers in `ACCEPTED` or `SETTLED` status matching the holding's vessel side, `fishery_code`, and `season_year`. The **conservative** figure, `available_conservative_pounds`, additionally subtracts the vessel's outgoing offers still in negotiation — transfers in `PROPOSED` or `COUNTERED` for the same fishery and year — so a vessel cannot over-commit while offers are open; with identical inputs the conservative figure is lower than the committed figure whenever open offers exist. Landing verification gates on the committed figure, while transfer creation and acceptance gate on the conservative figure. A computed read on any holding reports both variants together with the underlying components: `available_committed_pounds`, `available_conservative_pounds`, `landed_pounds`, `leased_in_pounds`, and `leased_out_pounds`.

Season openings are the regulator's expression of when and where a fishery runs. Creating one takes a `fishery_code`, an `area_code` such as 3A, an `opens_at` instant, a `closes_at` instant that must be later than `opens_at` (otherwise `ERR_INVALID_TIME_WINDOW`), and a `tac_pounds` total allowable catch that must be greater than zero. Openings for the same fishery and area must not overlap, regardless of either opening's status: the windows are treated as closed intervals, so two openings whose windows merely touch still conflict and the second is rejected with `ERR_OPENING_WINDOW_OVERLAP`; the overlap check runs before the window well-formedness check, so an inverted window that also overlaps an existing opening surfaces the overlap error. A new opening is `SCHEDULED` with `landed_against_tac_pounds` at zero.

An opening moves from `SCHEDULED` to `OPEN` when the clock reaches `opens_at`, and from `OPEN` to `CLOSED` when the clock passes `closes_at`. A regulator may also close an `OPEN` opening early, moving it to `CLOSED_EARLY`; the manual path requires the opening to actually be `OPEN`, failing otherwise with `ERR_OPENING_NOT_OPEN`. Early closure also fires automatically when a verified landing pushes `landed_against_tac_pounds` to meet or exceed `tac_pounds` — the threshold is inclusive, so landing exactly up to the TAC closes the fishery. Either closure path cancels every `PLANNED` trip on the opening, cancels each such trip's non-terminal observer assignments, and recomputes the affected observers' availability. For completeness, the model also admits a direct `SCHEDULED` → `CLOSED` transition when the clock passes `closes_at` while the opening never opened; in practice this is unreachable, because `opens_at` always precedes `closes_at` and the clock crosses the opening instant first.

### 3.3. Trip Planning, Gear Readiness, and Departure

A vessel owner or a captain plans a trip by supplying the `vessel_id`, the `season_opening_id` the trip will fish under, a `planned_departure_utc`, a `planned_return_utc`, and an optional `gear_requirements` list whose entries each name a `gear_type` and a number of `units` (the list defaults to empty; a non-array value or an entry with an unknown `gear_type` or a non-positive `units` is `ERR_INVALID_REQUEST`). Planning enforces a chain of conditions, evaluated in the tier order of §2.7 — temporal rules before cross-entity link state: the planned window must sit inside the opening's window — departure no earlier than `opens_at` and return no later than `closes_at` (`ERR_OUTSIDE_OPENING_WINDOW`); the planned window must not overlap another non-`CANCELLED` trip of the same vessel; the vessel must be `ACTIVE` (`ERR_VESSEL_NOT_ACTIVE`); the vessel must hold an `ISSUED` permit for the opening's fishery (`ERR_PERMIT_NOT_ACTIVE`); and the return must be later than the departure (`ERR_INVALID_TIME_WINDOW`). Trip windows use half-open semantics, so back-to-back trips — one returning exactly when the next departs — are allowed; anything tighter is rejected with `ERR_TRIP_WINDOW_OVERLAP`. Because the temporal tier runs first, an out-of-window or overlapping plan on an inactive vessel surfaces the temporal error, not `ERR_VESSEL_NOT_ACTIVE`. A successfully planned trip starts in `PLANNED`.

Two observer flags are computed at planning time. `observer_required` is true when the vessel's `observer_coverage_class` is `FULL`, or when the class is `PARTIAL` and the planned trip duration is strictly longer than 72 hours; it is false for `EXEMPT` vessels. When the requirement holds, an observer assignment is auto-created in `REQUESTED` status with `auto_created` set to true. `observer_waived` starts false and becomes true only if a regulator later waives coverage. The trip's `actual_departure_utc` and `actual_return_utc` remain null until the corresponding events occur.

Rescheduling is possible while the trip is `PLANNED` (otherwise `ERR_TRIP_NOT_PLANNED`). The owner or captain supplies a new `planned_departure_utc` and `planned_return_utc` together with `expected_trip_version` under the optimistic-concurrency rule of §2.6; the same window-containment and trip-overlap checks are re-evaluated against the new window, in that order — the overlap check compares against the vessel's other trips, excluding the trip being rescheduled, so a trip can always be rescheduled onto its own existing window — and the return-later-than-departure shape check runs after them, before the write. `observer_required` is recomputed from the new duration; the vessel and permit checks of trip planning are not re-run on reschedule, so a vessel suspended after planning does not block the reschedule itself.

Gear readiness is tracked per vessel through gear assets and an append-only event log. An owner registers a gear asset with a `gear_type` and a `units_total` greater than zero; the asset starts with `units_lost` at zero, `units_in_maintenance` at zero, `units_operational` equal to `units_total`, and status `OPERATIONAL`. Thereafter the owner or captain appends gear events to a specific asset — each stored event carries its `gear_asset_id` back-reference — with an `event_type` of `LOSS`, `REPAIR`, `MAINTENANCE_START`, or `MAINTENANCE_END`, a `units` count greater than zero, an `occurred_at` timestamp, and an optional `trip_id` linking the event to the trip where the loss or repair happened (a supplied `trip_id` must reference an existing trip, otherwise `ERR_TRIP_NOT_FOUND`). The asset's counters are a projection replayed over its events in `occurred_at` ascending order, with ties broken by `created_at` ascending: a `LOSS` event adds its units to `units_lost`; a `REPAIR` event subtracts its units from `units_lost`, floored at zero; a `MAINTENANCE_START` event adds its units to `units_in_maintenance` and is legal only if at least that many units are operational, otherwise `ERR_INVALID_GEAR_EVENT` (HTTP 422); a `MAINTENANCE_END` event subtracts its units from `units_in_maintenance` and is legal only if at least that many units are currently in maintenance, otherwise the same `ERR_INVALID_GEAR_EVENT`. The derived `units_operational` is `units_total` minus `units_lost` minus `units_in_maintenance`, and the asset's status is `OPERATIONAL` while that figure is greater than zero, otherwise `DOWN` — there is no explicit gear state machine, only this projection.

Departure is the captain's call and the most heavily gated transition in the system. The trip must be `PLANNED` (`ERR_TRIP_NOT_PLANNED`); then the safety gates run in the order of §2.7 tier 6 — observer coverage must be satisfied: the trip is not observer-required, or the requirement has been waived, or an assignment of the trip stands in `CONFIRMED` (`ERR_OBSERVER_COVERAGE_MISSING`); then gear sufficiency: for every `gear_requirements` entry, the summed `units_operational` across the vessel's gear assets of that `gear_type` must be at least the required `units` (`ERR_GEAR_SHORTAGE`); then the temporal tier — the season opening must be `OPEN` with the logical clock inside the window from `opens_at` through `closes_at`, both ends inclusive (`ERR_OUTSIDE_OPENING_WINDOW`); and finally the cross-entity tier — the vessel must be `ACTIVE` (`ERR_VESSEL_NOT_ACTIVE`). On success the trip moves from `PLANNED` to `DEPARTED`, `actual_departure_utc` is stamped from the logical clock, and the trip's `CONFIRMED` observer assignment advances to `DEPLOYED`.

A planned trip can be cancelled by the owner or the captain, moving `PLANNED` → `CANCELLED` and cancelling every assignment of the trip in `REQUESTED`, `ASSIGNED`, or `CONFIRMED`, with each cancellation recomputing the observer's availability. The same cancellation cascade runs when the system cancels a trip because its opening closed or its vessel was suspended.

### 3.4. At-Sea Operations: Catch Reports, VMS Pings, and Return

While a trip is `DEPARTED`, the captain appends catch reports, one per haul, each carrying a `fishery_code`, a `report_type` of `HARVEST` or `DISCARD`, a `reported_lbs` greater than zero, and a `reported_at` timestamp of when the haul occurred. Each report receives a `haul_seq`, a per-trip sequence number starting at 1 and assigned in creation order, and exists in a permanent `RECORDED` state. Reports are append-only: creation is the only write, and attempting to file one before the trip has departed is rejected with `ERR_TRIP_NOT_DEPARTED`.

The captain also relays vessel monitoring data by ingesting VMS pings, each with a `recorded_at` timestamp, a `latitude`, and a `longitude`. Pings are likewise append-only.

Returning is a captain action on a `DEPARTED` trip (`ERR_TRIP_NOT_DEPARTED` otherwise): the trip moves from `DEPARTED` to `RETURNED`, and `actual_return_utc` is stamped from the logical clock. When the vessel has a `vms_unit_id`, return triggers a gap-detection pass over the trip's actual window. The vessel's pings with `recorded_at` inside the window from `actual_departure_utc` through `actual_return_utc` are sorted by `recorded_at` ascending with ties broken by `created_at` ascending; the departure and return instants themselves are treated as synthetic boundary pings. Consecutive pings — including the synthetic boundaries — are then compared, and if any gap is strictly longer than 120 minutes, the system creates a compliance violation of type `VMS_GAP` in `OPEN` status linked to this trip, with `details` recording the longest gap. A gap of exactly 120 minutes is compliant; the comparison is strictly greater-than. Vessels without a `vms_unit_id` skip this check entirely.

### 3.5. Landing Declarations: Discrepancy, Verification, and Quota Posting

Once a trip has `RETURNED`, the captain files the trip's landing declaration — at most one per trip; a second attempt is rejected with `ERR_DECLARATION_EXISTS`, and filing before return is rejected with `ERR_TRIP_NOT_RETURNED`. The declaration names a `port_code` and a non-empty list of `lines`, each line pairing a `fishery_code` with a `declared_lbs` that may be zero but not negative. A new declaration starts in `DRAFT`.

Submitting — allowed from `DRAFT` or from `AMENDED`, and rejected from anything else with `ERR_DECLARATION_NOT_SUBMITTED` — requires the trip to be `RETURNED` (otherwise `ERR_TRIP_NOT_RETURNED`) and recomputes the declaration's `discrepancy_details`. For each line, the expected poundage `expected_lbs` is the sum of `reported_lbs` over the trip's catch reports of that fishery with `report_type` `HARVEST`, minus the sum over reports of that fishery with `report_type` `DISCARD`. The line's `within_tolerance` flag is then determined: when `expected_lbs` is zero, the line is within tolerance only if its `declared_lbs` is also zero; otherwise the tolerance is 5 percent of `expected_lbs` rounded half-up to whole pounds, and the line is within tolerance when the absolute difference between `declared_lbs` and `expected_lbs` is no greater than that tolerance — the boundary is inclusive, so a difference exactly equal to the tolerance passes. Submission moves the declaration to `SUBMITTED`.

Verification is a regulator action with three gates, evaluated in order. First, the declaration must be `SUBMITTED` (`ERR_DECLARATION_NOT_SUBMITTED`). Second, the observer gate: the trip's observer requirement must be resolved — not required, waived, or an assignment of the trip in `DEBRIEFED` (`ERR_OBSERVER_NOT_DEBRIEFED`). Third, the discrepancy gate: `discrepancy_details` are recomputed against the current catch reports at verification time and stored, and if any line is outside its tolerance, the declaration does not error — it transitions from `SUBMITTED` to `DISPUTED` with a normal success response, and verification stops there. Only when every line is within tolerance does the quota gate run: for each line, the vessel's quota share holding matching the line's `fishery_code` and the applicable season year — the calendar year of the logical clock at verification time — must have `available_committed_pounds` at least equal to the line's `declared_lbs`; a missing holding is `ERR_QUOTA_HOLDING_NOT_FOUND`, and insufficient quota is `ERR_QUOTA_EXCEEDED` (HTTP 402). Every line is checked against its holding before any posting occurs, so a quota failure leaves all holdings and the opening untouched.

A successful verification moves the declaration to `VERIFIED` and posts the landings: for every line, the holding's `landed_pounds` increases by `declared_lbs`, and the opening's `landed_against_tac_pounds` increases by `declared_lbs`. If that posting pushes the opening to its TAC, the early-closure cascade of §3.2 fires from within the verification — but only when the opening is still `OPEN` at that moment; postings against an opening already `CLOSED` or `CLOSED_EARLY` (for example a manual early closure while the trip was at sea) do not re-fire it.

A disputed declaration returns to the captain, who amends it by supplying a replacement set of `lines`; amendment requires `DISPUTED` status (`ERR_DECLARATION_NOT_DISPUTED`) and moves the declaration to `AMENDED`, from which it may be submitted again. Finally, a regulator finalizes a `VERIFIED` declaration — `ERR_DECLARATION_NOT_VERIFIED` from any other status — moving it to `FINALIZED`, and the trip bubbles up from `RETURNED` to `LANDING_FINALIZED` (the trip is always `RETURNED` here, since finalize cannot run before verification).

### 3.6. Observer Coverage and Assignment Lifecycle

An `ObserverCoordinator` maintains the observer registry, registering each observer with an `observer_name`, a `certification_level` of `A` (highest), `B`, or `C`, and a `home_base`. An observer's `status` is computed rather than set: it is `ON_ASSIGNMENT` while the observer has any assignment in `ASSIGNED`, `CONFIRMED`, or `DEPLOYED`, and `AVAILABLE` otherwise. Newly registered observers start `AVAILABLE`.

Assignment requests enter `REQUESTED` either automatically at trip planning (§3.3) or through the compensating re-request described below. Assigning is a coordinator action on a `REQUESTED` assignment — `ERR_ASSIGNMENT_NOT_REQUESTED` from any other status — supplying the `observer_id`, a `coverage_from`, and a `coverage_to` that must be later than `coverage_from` (`ERR_INVALID_TIME_WINDOW`), together with `expected_observer_version` under §2.6; until assigned, `observer_id` and the coverage window are null. Certification must match the vessel's coverage class: a `FULL` vessel requires level `A`; a `PARTIAL` vessel requires `A` or `B`; an `EXEMPT` vessel accepts any level. Insufficient certification is rejected with `ERR_OBSERVER_CERT_INSUFFICIENT` (HTTP 422). Double-booking is checked against the observer's other assignments in `ASSIGNED`, `CONFIRMED`, or `DEPLOYED`, with a 24-hour rest buffer after each assignment: the new window must begin no earlier than 24 hours after the end of an existing committed window, or end no later than 24 hours before one begins; anything closer is `ERR_OBSERVER_DOUBLE_BOOKED`. The double-booking check runs before the coverage window's own well-formedness check, so an inverted window that also collides with an existing committed assignment surfaces `ERR_OBSERVER_DOUBLE_BOOKED`, not `ERR_INVALID_TIME_WINDOW`. A successful assignment moves the request to `ASSIGNED`, stamps the observer and window onto it, flips the observer to `ON_ASSIGNMENT`, and increments the observer's `version` — the observer's version advances on every successful assignment, including an assignment to an observer who was already `ON_ASSIGNMENT`.

From `ASSIGNED`, the observer personally confirms — the caller's `X-User-ID` must equal the assignment's `observer_id`, otherwise `ERR_NOT_RESOURCE_OWNER` — moving to `CONFIRMED`; confirming from any other status is `ERR_ASSIGNMENT_NOT_ASSIGNED`. When the trip departs, a `CONFIRMED` assignment advances automatically to `DEPLOYED`. After the trip has returned — the trip must be in `RETURNED`, `LANDING_FINALIZED`, or `SETTLED` (`ERR_TRIP_NOT_RETURNED`) — the observer debriefs, again under the same ownership check, moving from `DEPLOYED` to `DEBRIEFED` (`ERR_ASSIGNMENT_NOT_DEPLOYED` from elsewhere), and the observer's availability is recomputed.

A coordinator may release a `CONFIRMED` assignment — `ERR_ASSIGNMENT_NOT_CONFIRMABLE` (HTTP 409) otherwise — moving it to `RELEASED` and recomputing the observer's availability. Release carries a compensating action: if the trip is still `PLANNED`, still observer-required, and not waived, a fresh assignment in `REQUESTED` is auto-created for the trip so coverage is re-sought rather than silently dropped. A regulator may instead waive a `REQUESTED` assignment (`ERR_ASSIGNMENT_NOT_REQUESTED` otherwise), moving it to `WAIVED` and setting the trip's `observer_waived` to true. Trip cancellation cascades cancel assignments in `REQUESTED`, `ASSIGNED`, or `CONFIRMED`, recomputing observer availability whenever an observer had been named. `DEBRIEFED`, `RELEASED`, `WAIVED`, and `CANCELLED` are terminal.

### 3.7. Quota Lease Negotiation Between Vessels

Quota moves between vessels through a negotiated lease. A vessel owner opens a lease by proposing a transfer with `from_vessel_id` — which must equal the caller's `X-User-ID` — a `to_vessel_id`, a `fishery_code`, a `season_year`, a `pounds` amount greater than zero, and a `price_per_lb_cents` that may be zero but not negative. Checks run in the tier order of §2.7: both vessels must be `ACTIVE` (`ERR_VESSEL_NOT_ACTIVE`), both must hold an `ISSUED` permit for the fishery (`ERR_PERMIT_NOT_ACTIVE`), and both must have a quota share holding for the fishery and season year (`ERR_QUOTA_HOLDING_NOT_FOUND`) — all at the cross-entity tier — before the shape tier rejects a lease from a vessel to itself with `ERR_SELF_TRANSFER` (HTTP 422) or a non-positive `pounds` / negative `price_per_lb_cents` with `ERR_INVALID_REQUEST`; consequently a self-transfer payload on an inactive vessel surfaces the vessel error first. Finally, the leasing-out vessel's `available_conservative_pounds` must cover `pounds` (`ERR_QUOTA_EXCEEDED`). A valid proposal starts in `PROPOSED` with `round_number` 1 and `last_offered_by` set to `FROM_VESSEL`.

Negotiation alternates sides. A counter-offer is valid from either `PROPOSED` or `COUNTERED` (`ERR_TRANSFER_NOT_OPEN` otherwise), requires `expected_transfer_version` per §2.6, and must come from the side that did not table the current offer — the `TO_VESSEL` owner counters a `PROPOSED` transfer, the `FROM_VESSEL` owner counters a `COUNTERED` one; the side that tabled the standing offer attempting to counter it is rejected with `ERR_TRANSFER_OWN_OFFER`. A counter replaces `pounds` and `price_per_lb_cents` with the payload values, increments `round_number` by one, flips `last_offered_by` to the other side, and toggles the status — `PROPOSED` to `COUNTERED`, or `COUNTERED` back to `PROPOSED`.

Acceptance likewise belongs to the side that did not table the current offer, from `PROPOSED` or `COUNTERED` (`ERR_TRANSFER_NOT_OPEN`, `ERR_TRANSFER_OWN_OFFER` as applicable). At acceptance the platform re-checks that both vessels still hold an `ISSUED` permit for the fishery (`ERR_PERMIT_NOT_ACTIVE`), that both vessels' holdings for the fishery and season year still exist (`ERR_QUOTA_HOLDING_NOT_FOUND`), and that the from-side's `available_conservative_pounds` still covers the standing `pounds` (`ERR_QUOTA_EXCEEDED`); the vessels' `ACTIVE` status is not re-checked at acceptance. Acceptance moves the transfer to `ACCEPTED` and posts the reservation: the from-side holding's leased-out total increases by `pounds`, the to-side holding's leased-in total increases by `pounds`, and both availability figures move accordingly — committed and conservative availability both drop on the from-side — with both holdings' versions incrementing alongside the transfer's.

Declining is available to the non-tabling side from `PROPOSED` or `COUNTERED` and moves the transfer to `DECLINED`. Withdrawing is the mirror image: available only to the side that tabled the current offer — the `last_offered_by` side — from the same two statuses, moving the transfer to `WITHDRAWN`; either move by the wrong side is `ERR_TRANSFER_OWN_OFFER`, and either from a closed status is `ERR_TRANSFER_NOT_OPEN`.

An `ACCEPTED` transfer is settled by a `SettlementClerk` — any other status yields `ERR_TRANSFER_NOT_ACCEPTED` — moving it to `SETTLED` and computing `transfer_fee_cents`, which remains null until this point. The fee is tiered on the transfer's final, last-countered values of `pounds` and `price_per_lb_cents`. When the settled poundage is at most 1,000 pounds, the fee is a flat 25,000 cents. When the poundage is greater than 1,000 and at most 10,000 pounds, the fee is 25,000 cents plus 4 percent of the lease's total value — pounds multiplied by the price per pound in cents — with that percentage component rounded half-up to whole cents. When the poundage exceeds 10,000 pounds, the fee is 25,000 cents plus 4 percent of the value of the first 10,000 pounds (10,000 times the price per pound), rounded half-up, plus 7 percent of the value of the pounds above 10,000, that component also rounded half-up to whole cents.

Leases that never settle expire with the season: when the logical clock passes the end of the transfer's `season_year`, a transfer in `PROPOSED` or `COUNTERED` moves to `EXPIRED` with no further effect, while a transfer in `ACCEPTED` moves to `EXPIRED` with a compensating release — the from-side holding's leased-out total decreases by `pounds` and the to-side holding's leased-in total decreases by `pounds`, unwinding the reservation.

### 3.8. Expenses, Crew Shares, and Trip Settlement

Crew compensation rests on share contracts. A vessel owner registers a crew share contract on their own vessel with a `crew_name`, `share_points` greater than zero (fractional points are accepted), and a `joined_at` date; the contract starts `ACTIVE`. Deactivation moves it to `INACTIVE`, excluding it from future settlement splits without touching past ones; deactivation is not state-guarded, so deactivating an already-`INACTIVE` contract succeeds as a no-op transition rather than erroring.

Trip expenses are recorded by the captain or the owner with a `category` of `FUEL`, `BAIT`, `ICE`, `GROCERIES`, `GEAR_REPAIR`, or `OTHER`, an `amount_cents` greater than zero, and an `incurred_at` timestamp; expenses may be recorded against a trip in any status — recording is not gated on the trip having departed. Each expense starts `PENDING`. A settlement clerk adjudicates expenses individually: verifying moves `PENDING` → `VERIFIED`, rejecting moves `PENDING` → `REJECTED`, and either action on an already-terminal expense is `ERR_EXPENSE_NOT_PENDING`.

Once the trip's landing is finalized — the trip must be in `LANDING_FINALIZED`, otherwise `ERR_TRIP_NOT_LANDING_FINALIZED` — a clerk creates the trip's settlement, at most one per trip (`ERR_SETTLEMENT_EXISTS`), supplying the `gross_revenue_cents` ex-vessel revenue, which must be greater than zero; the trip-status check runs before the duplicate-settlement check, so a second settlement attempt after the trip has been paid out surfaces `ERR_TRIP_NOT_LANDING_FINALIZED`. The settlement starts in `DRAFT`, and a **provisional** variant of the settlement math runs immediately, counting both `PENDING` and `VERIFIED` expenses, populating `provisional_total_expenses_cents`, `provisional_processing_fee_cents`, `provisional_vessel_share_cents`, and `provisional_crew_pool_cents` so stakeholders see an early estimate before adjudication finishes.

The settlement waterfall itself runs in a pinned order, which breaks the circularity that the processing fee is a percentage of crew-visible money while the crew pool depends on the fee:

1. **Total expenses** — the sum of `amount_cents` over the trip's expense records. The final variant counts `VERIFIED` expenses only; the provisional variant counts `PENDING` and `VERIFIED`. The provisional variant never errors on a negative net before fee — it reports whatever the arithmetic yields.
2. **Observer fee** — for each of the trip's assignments in `DEPLOYED` or `DEBRIEFED`, the coverage window length in hours (fractional hours allowed) is divided by 24 and rounded up to a whole day count, and that day count is multiplied by 45,000 cents; the results are summed. Assignments in `REQUESTED`, `ASSIGNED`, `CONFIRMED`, `RELEASED`, `WAIVED`, or `CANCELLED` contribute zero.
3. **Gear loss charge** — the number of `LOSS` units minus the number of `REPAIR` units among gear events attributed to this trip, floored at zero, multiplied by 25,000 cents.
4. **Net before fee** — `gross_revenue_cents` minus total expenses, minus the observer fee, minus the gear loss charge. This figure must be zero or positive; a negative result is rejected with `ERR_SETTLEMENT_UNDERWATER` (HTTP 422).
5. **Processing fee** — 1.5 percent of the net before fee, rounded half-up to whole cents.
6. **Net** — the net before fee minus the processing fee.
7. **Vessel share** — 60 percent of the net, rounded half-up to whole cents.
8. **Crew pool** — the net minus the vessel share.

The books balance exactly: gross revenue equals the sum of total expenses, observer fee, gear loss charge, processing fee, vessel share, and crew pool.

Calculation is a clerk action on a `DRAFT` settlement — `ERR_SETTLEMENT_NOT_DRAFT` otherwise — and it runs the final variant. Three gates guard it: every expense of the trip must be terminal, `VERIFIED` or `REJECTED` (`ERR_EXPENSES_UNRESOLVED`); at least one crew share contract on the vessel must be `ACTIVE` (`ERR_NO_ACTIVE_CREW`, HTTP 422); and the underwater check of step 4 must pass. Success moves the settlement to `CALCULATED` and populates the final fields — `total_expenses_cents`, `observer_fee_cents`, `gear_loss_charge_cents`, `processing_fee_cents`, `net_cents`, `vessel_share_cents`, `crew_pool_cents`, all of which are null until calculated — along with `crew_payouts`.

The crew pool split is deterministic down to the cent. The eligible contracts are the vessel's `ACTIVE` crew share contracts, and their `share_points` are summed into a total. Contracts are then processed in a pinned order — `share_points` descending, then `joined_at` ascending, then `created_at` ascending — and each contract's raw payout, the crew pool multiplied by its points and divided by the total points, is floored to whole cents. The remainder — the pool minus the sum of the floored payouts — is distributed one cent at a time to contracts in that same order until nothing remains. Each `crew_payouts` entry records the `crew_contract_id`, the `crew_name`, and the `payout_cents`, and the payouts always sum exactly to `crew_pool_cents`; any sum-then-round shortcut yields different per-member cents and is non-conformant.

Approval belongs to the vessel owner, whose `X-User-ID` must equal the trip's vessel id (`ERR_NOT_RESOURCE_OWNER`), acting on a `CALCULATED` settlement (`ERR_SETTLEMENT_NOT_CALCULATED`) to move it to `APPROVED`. A crew member holding an `ACTIVE` contract on the trip's vessel may instead dispute a `CALCULATED` settlement (same state error; ownership failure also `ERR_NOT_RESOURCE_OWNER`), moving it to `DISPUTED`. A clerk then recalculates from `DISPUTED` — `ERR_SETTLEMENT_NOT_DISPUTED` otherwise — carrying `expected_settlement_version` under §2.6 and re-running the expense-resolution and underwater gates against current data, returning the settlement to `CALCULATED`; unlike the initial calculation, recalculation does not re-check the active-crew gate, so a dispute cycle begun while crew contracts existed is not stranded if they are later deactivated. Finally, a clerk pays an `APPROVED` settlement (`ERR_SETTLEMENT_NOT_APPROVED` otherwise), moving it to `PAID`; payment bubbles the trip from `LANDING_FINALIZED` to `SETTLED`, its terminal state.

### 3.9. Compliance Violations, Adjudication, and Appeals

Violations enter the system two ways: a regulator manually cites a vessel with a `vessel_id`, a `violation_type` of `OVER_QUOTA`, `OUT_OF_SEASON`, `OBSERVER_BREACH`, `VMS_GAP`, `GEAR_MISMATCH`, or `MANUAL_CITATION`, free-text `details` (required — it must be present and a string, though it may be empty), and an optional `trip_id` that, when supplied, must reference an existing trip (`ERR_TRIP_NOT_FOUND`); or the system creates a `VMS_GAP` violation automatically on trip return (§3.4). Either way the violation starts `OPEN`, its `season_year` is the calendar year of the logical clock at creation, and its `severity_points` remain null until adjudication.

Adjudication is a regulator action on an `OPEN` violation — `ERR_VIOLATION_NOT_OPEN` otherwise — moving it to `ADJUDICATED` and scoring it. The penalty starts from a base by type: 20 points for `OVER_QUOTA`, 25 for `OUT_OF_SEASON`, 15 for `OBSERVER_BREACH`, 10 for `VMS_GAP`, 5 for `GEAR_MISMATCH`, and 10 for `MANUAL_CITATION`. The base is scaled by a tier multiplier read from the vessel's `compliance_points` before any deduction: 80 or more points yields a multiplier of 1.0; 50 through 79 yields 1.5; below 50 yields 2.0. A repeat factor of 1.5 applies when any other violation of the same vessel, same `violation_type`, and same `season_year` already stands in `ADJUDICATED` or `UPHELD`; otherwise the factor is 1.0. The three factors are multiplied and the product rounded half-up once, at the end, to whole points — that figure is stored in `severity_points` and deducted from the vessel's `compliance_points`. If the deduction leaves the vessel below 50 points, the vessel moves to `SUSPENDED` with the full cascade of §3.1; a landing on exactly 50 does not suspend.

A regulator may instead dismiss an `OPEN` violation — same `ERR_VIOLATION_NOT_OPEN` guard — moving it to `DISMISSED` with no penalty. The owner of the cited vessel may appeal an `ADJUDICATED` violation, with `X-User-ID` matching the violation's `vessel_id` (`ERR_NOT_RESOURCE_OWNER`), moving it to `APPEALED`; appealing from any other status is `ERR_VIOLATION_NOT_ADJUDICATED`. On appeal, a regulator either reverses or upholds: reversal moves `APPEALED` → `REVERSED` and refunds the stored `severity_points` back to the vessel's `compliance_points`, but deliberately does not lift a suspension — regaining `ACTIVE` status requires the manual reinstatement path with its own 50-point gate; upholding moves `APPEALED` → `UPHELD` and the penalty stands. Both actions require `APPEALED` status, failing otherwise with `ERR_VIOLATION_NOT_APPEALED`. `DISMISSED`, `REVERSED`, and `UPHELD` are terminal.

## 4. Endpoint Definitions

All endpoints share the status-code convention that creating a new resource returns 201, while reads, modifications, and action-style transitions return 200. Where the Authorized Role(s) column below reads "All seven roles", every declared role — `VesselOwner`, `Captain`, `CrewMember`, `Observer`, `ObserverCoordinator`, `FisheriesRegulator`, and `SettlementClerk` — may call the endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock; fires all time-based transitions | FisheriesRegulator |
| POST | /vessels | Register a vessel | FisheriesRegulator |
| GET | /vessels | List vessels | All seven roles |
| GET | /vessels/{id} | Get one vessel | All seven roles |
| POST | /vessels/{id}/activate | Activate a REGISTERED vessel | FisheriesRegulator |
| POST | /vessels/{id}/reinstate | Reinstate a SUSPENDED vessel with sufficient compliance points | FisheriesRegulator |
| POST | /vessels/{id}/decommission | Decommission a vessel with no open trips | FisheriesRegulator |
| POST | /vessels/{id}/permits | Issue a fishery permit to a vessel | FisheriesRegulator |
| GET | /vessels/{id}/permits | List permits of a vessel | All seven roles |
| POST | /permits/{id}/revoke | Revoke an ISSUED or SUSPENDED permit | FisheriesRegulator |
| POST | /vessels/{id}/quota-holdings | Allocate an annual quota share holding | FisheriesRegulator |
| GET | /vessels/{id}/quota-holdings | List quota holdings of a vessel | All seven roles |
| GET | /quota-holdings/{id} | Get one quota holding | All seven roles |
| GET | /quota-holdings/{id}/availability | Computed read of both availability variants | All seven roles |
| POST | /season-openings | Create a season/area opening | FisheriesRegulator |
| GET | /season-openings | List season openings | All seven roles |
| GET | /season-openings/{id} | Get one season opening | All seven roles |
| POST | /season-openings/{id}/close-early | Manually close an OPEN opening early | FisheriesRegulator |
| POST | /fishing-trips | Plan a trip inside an opening window | VesselOwner, Captain |
| GET | /fishing-trips | List trips | All seven roles |
| GET | /fishing-trips/{id} | Get one trip | All seven roles |
| PATCH | /fishing-trips/{id} | Reschedule a PLANNED trip (OCC on trip version) | VesselOwner, Captain |
| POST | /fishing-trips/{id}/depart | Depart on a PLANNED trip | Captain |
| POST | /fishing-trips/{id}/return | Return from a DEPARTED trip; runs VMS gap detection when the vessel has a transponder | Captain |
| POST | /fishing-trips/{id}/cancel | Cancel a PLANNED trip | VesselOwner, Captain |
| POST | /fishing-trips/{id}/catch-reports | Append a catch report while the trip is DEPARTED | Captain |
| GET | /fishing-trips/{id}/catch-reports | List catch reports of a trip | All seven roles |
| POST | /fishing-trips/{id}/landing-declarations | Create the trip's landing declaration | Captain |
| GET | /fishing-trips/{id}/landing-declarations | List landing declarations of a trip (0 or 1 rows) | All seven roles |
| GET | /landing-declarations/{id} | Get one landing declaration | All seven roles |
| POST | /landing-declarations/{id}/submit | Submit a DRAFT or AMENDED declaration | Captain |
| POST | /landing-declarations/{id}/verify | Verify a SUBMITTED declaration; over-tolerance moves it to DISPUTED without an error | FisheriesRegulator |
| POST | /landing-declarations/{id}/amend | Amend a DISPUTED declaration's lines | Captain |
| POST | /landing-declarations/{id}/finalize | Finalize a VERIFIED declaration; bubbles the trip to LANDING_FINALIZED | FisheriesRegulator |
| POST | /quota-transfers | Propose a quota lease between two vessels | VesselOwner |
| GET | /quota-transfers | List transfers | All seven roles |
| GET | /quota-transfers/{id} | Get one transfer | All seven roles |
| POST | /quota-transfers/{id}/counter | Counter-offer the current round (OCC on transfer version) | VesselOwner |
| POST | /quota-transfers/{id}/accept | Accept the current offer; debits the from-holding and credits the to-holding | VesselOwner |
| POST | /quota-transfers/{id}/decline | Decline the current offer | VesselOwner |
| POST | /quota-transfers/{id}/withdraw | Withdraw your own tabled offer | VesselOwner |
| POST | /quota-transfers/{id}/settle | Settle an ACCEPTED transfer; computes the tiered transfer fee | SettlementClerk |
| POST | /observers | Register an observer | ObserverCoordinator |
| GET | /observers | List observers | All seven roles |
| GET | /observers/{id} | Get one observer | All seven roles |
| GET | /observer-assignments | List assignments | All seven roles |
| GET | /observer-assignments/{id} | Get one assignment | All seven roles |
| POST | /observer-assignments/{id}/assign | Assign an observer to a REQUESTED assignment (OCC on observer version) | ObserverCoordinator |
| POST | /observer-assignments/{id}/confirm | Observer confirms their assignment | Observer |
| POST | /observer-assignments/{id}/debrief | Observer debriefs after the trip has returned | Observer |
| POST | /observer-assignments/{id}/release | Release a CONFIRMED assignment; may auto-create a fresh request | ObserverCoordinator |
| POST | /observer-assignments/{id}/waive | Regulator waives a REQUESTED assignment | FisheriesRegulator |
| POST | /vessels/{id}/crew-contracts | Add a crew share contract | VesselOwner |
| GET | /vessels/{id}/crew-contracts | List crew contracts of a vessel | All seven roles |
| POST | /crew-contracts/{id}/deactivate | Deactivate a crew contract | VesselOwner |
| POST | /fishing-trips/{id}/expenses | Record a trip expense | Captain, VesselOwner |
| GET | /fishing-trips/{id}/expenses | List expenses of a trip | All seven roles |
| POST | /expenses/{id}/verify | Verify a PENDING expense | SettlementClerk |
| POST | /expenses/{id}/reject | Reject a PENDING expense | SettlementClerk |
| POST | /fishing-trips/{id}/settlement | Create the trip's settlement in DRAFT with provisional figures | SettlementClerk |
| GET | /fishing-trips/{id}/settlement | Get the settlement of a trip (array of 0 or 1) | All seven roles |
| GET | /trip-settlements/{id} | Get one settlement | All seven roles |
| POST | /trip-settlements/{id}/calculate | Calculate the final settlement from DRAFT | SettlementClerk |
| POST | /trip-settlements/{id}/recalculate | Recalculate a DISPUTED settlement (OCC on settlement version) | SettlementClerk |
| POST | /trip-settlements/{id}/approve | Vessel owner approves a CALCULATED settlement | VesselOwner |
| POST | /trip-settlements/{id}/dispute | Crew member disputes a CALCULATED settlement | CrewMember |
| POST | /trip-settlements/{id}/pay | Pay an APPROVED settlement; bubbles the trip to SETTLED | SettlementClerk |
| POST | /vessels/{id}/gear-assets | Register a gear asset | VesselOwner |
| GET | /vessels/{id}/gear-assets | List gear assets of a vessel | All seven roles |
| GET | /gear-assets/{id} | Get one gear asset | All seven roles |
| POST | /gear-assets/{id}/events | Append a gear event; replays the operational-units projection | VesselOwner, Captain |
| GET | /gear-assets/{id}/events | List events of a gear asset | All seven roles |
| GET | /fishing-trips/{id}/gear-events | List gear events attributed to a trip | All seven roles |
| POST | /vessels/{id}/vms-pings | Ingest a VMS position ping | Captain |
| GET | /vessels/{id}/vms-pings | List VMS pings of a vessel | All seven roles |
| POST | /violations | Manually cite a vessel | FisheriesRegulator |
| GET | /violations | List violations | All seven roles |
| GET | /violations/{id} | Get one violation | All seven roles |
| POST | /violations/{id}/adjudicate | Adjudicate an OPEN violation; computes and deducts penalty points | FisheriesRegulator |
| POST | /violations/{id}/dismiss | Dismiss an OPEN violation | FisheriesRegulator |
| POST | /violations/{id}/appeal | Vessel owner appeals an ADJUDICATED violation | VesselOwner |
| POST | /violations/{id}/reverse | Reverse an appealed violation; refunds the penalty points | FisheriesRegulator |
| POST | /violations/{id}/uphold | Uphold an appealed violation; the penalty stands | FisheriesRegulator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them (§2 and §3); this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VESSEL_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_QUOTA_HOLDING_NOT_FOUND | 404 |
| ERR_SEASON_OPENING_NOT_FOUND | 404 |
| ERR_TRIP_NOT_FOUND | 404 |
| ERR_LANDING_DECLARATION_NOT_FOUND | 404 |
| ERR_TRANSFER_NOT_FOUND | 404 |
| ERR_OBSERVER_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_CREW_CONTRACT_NOT_FOUND | 404 |
| ERR_EXPENSE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_GEAR_ASSET_NOT_FOUND | 404 |
| ERR_VIOLATION_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_TIME_WINDOW | 400 |
| ERR_CLOCK_REGRESSION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_VESSEL_NOT_ACTIVE | 409 |
| ERR_COMPLIANCE_TOO_LOW | 409 |
| ERR_VESSEL_HAS_OPEN_TRIPS | 409 |
| ERR_PERMIT_NOT_ACTIVE | 409 |
| ERR_OPENING_NOT_OPEN | 409 |
| ERR_TRIP_NOT_PLANNED | 409 |
| ERR_TRIP_NOT_DEPARTED | 409 |
| ERR_TRIP_NOT_RETURNED | 409 |
| ERR_TRIP_NOT_LANDING_FINALIZED | 409 |
| ERR_DECLARATION_EXISTS | 409 |
| ERR_DECLARATION_NOT_SUBMITTED | 409 |
| ERR_DECLARATION_NOT_DISPUTED | 409 |
| ERR_DECLARATION_NOT_VERIFIED | 409 |
| ERR_TRANSFER_NOT_OPEN | 409 |
| ERR_TRANSFER_NOT_ACCEPTED | 409 |
| ERR_TRANSFER_OWN_OFFER | 409 |
| ERR_ASSIGNMENT_NOT_REQUESTED | 409 |
| ERR_ASSIGNMENT_NOT_ASSIGNED | 409 |
| ERR_ASSIGNMENT_NOT_DEPLOYED | 409 |
| ERR_ASSIGNMENT_NOT_CONFIRMABLE | 409 |
| ERR_EXPENSE_NOT_PENDING | 409 |
| ERR_EXPENSES_UNRESOLVED | 409 |
| ERR_SETTLEMENT_EXISTS | 409 |
| ERR_SETTLEMENT_NOT_DRAFT | 409 |
| ERR_SETTLEMENT_NOT_CALCULATED | 409 |
| ERR_SETTLEMENT_NOT_DISPUTED | 409 |
| ERR_SETTLEMENT_NOT_APPROVED | 409 |
| ERR_VIOLATION_NOT_OPEN | 409 |
| ERR_VIOLATION_NOT_ADJUDICATED | 409 |
| ERR_VIOLATION_NOT_APPEALED | 409 |
| ERR_OBSERVER_COVERAGE_MISSING | 409 |
| ERR_OBSERVER_NOT_DEBRIEFED | 409 |
| ERR_GEAR_SHORTAGE | 409 |
| ERR_OBSERVER_CERT_INSUFFICIENT | 422 |
| ERR_OUTSIDE_OPENING_WINDOW | 409 |
| ERR_OPENING_WINDOW_OVERLAP | 409 |
| ERR_TRIP_WINDOW_OVERLAP | 409 |
| ERR_OBSERVER_DOUBLE_BOOKED | 409 |
| ERR_SELF_TRANSFER | 422 |
| ERR_DUPLICATE_HOLDING | 409 |
| ERR_DUPLICATE_LICENSE | 409 |
| ERR_INVALID_GEAR_EVENT | 422 |
| ERR_NO_ACTIVE_CREW | 422 |
| ERR_QUOTA_EXCEEDED | 402 |
| ERR_SETTLEMENT_UNDERWATER | 422 |
