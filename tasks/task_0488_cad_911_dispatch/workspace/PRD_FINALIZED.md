# CAD-911-Dispatch API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Computer-Aided Dispatch (CAD) platform operating within a Next-Generation 911 (NG911) public-safety environment. The system is the system of record for the full life of a call for service: a calltaker captures the inbound call and its automatic caller and location identification, the platform classifies the incident and computes its urgency, a dispatcher recommends and commits the nearest available field units, those units report their status as they roll to and arrive on scene, supervisors retain override authority to escalate, hold, resume, and ultimately close the incident, and a records team produces the regulatory call-for-service reports once the incident is finalized.

The domain is unusually demanding for three reasons. First, unit selection is a policy problem: the platform must recommend the nearest available unit of the correct discipline using a deterministic, tie-broken ranking, and degrade gracefully to mutual-aid resources when in-jurisdiction units are exhausted. Second, an incident carries two state dimensions that evolve independently on the same record — a workflow lifecycle and a cyclic priority that can ratchet upward as time pressure mounts — alongside a separate per-assignment field pipeline and a per-unit availability dimension. Third, every time-derived metric (response time, total handle time, SLA breach, and the report snapshots) must be reproducible run after run; the platform therefore reads a deterministic logical clock rather than wall-clock time.

Because dispatch decisions race — two dispatchers may both be looking at the same pending incident and the same "nearest unit" — the platform applies optimistic concurrency control to incident mutations so that a dispatcher cannot commit a unit against a view of the incident that has already moved on. The sections that follow define the global contract first, then the business workflows, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If `X-User-Role` is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes six roles, spelled exactly as follows: `Calltaker`, `Dispatcher`, `FieldUnit`, `Supervisor`, `Records`, and `SystemClock`. A `Calltaker` performs call intake and may cancel an incident that was never dispatched. A `Dispatcher` obtains nearest-unit recommendations and commits units to incidents, and may advance or cancel assignments. A `FieldUnit` reports its own availability and drives its assignment's field progress. A `Supervisor` holds override authority — escalation, hold and resume, closing incidents, and managing agencies, stations, units, and premise alerts. A `Records` user generates regulatory reports and maintains premise alerts. The `SystemClock` role is a test-driving operator that advances the logical clock and does nothing else.

Most roles carry an opaque identity. When `X-User-Role` is `Calltaker`, `Dispatcher`, `Supervisor`, `Records`, or `SystemClock`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The single exception is `FieldUnit`: when `X-User-Role` is `FieldUnit`, `X-User-ID` is the `id` of the acting `Unit`. Ownership checks on a field operation that advances an assignment compare the assignment's referenced unit to `X-User-ID` — that is, a field unit acts on its own assignment, identified by the unit it is.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system — agencies, stations, units, premise alerts, incidents, assignments, and dispositions — are mutable records that carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID. It carries no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification of the resource.
- **`version`** — an integer that begins at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control.

A call-for-service report is different: it is an immutable, append-only record. A `CfsReport` therefore carries only `id` and `created_at`; it has no `updated_at` and no `version`, and once written it is never modified.

A subtle but critical distinction governs timestamps. The `created_at` and `updated_at` audit fields are real recording timestamps. By contrast, every *business* instant the platform records — when an incident was received, when it was first dispatched, when the first unit arrived, when an assignment went enroute, onscene, or cleared, when an incident was closed, and the instant captured into a report — is read from a deterministic **logical clock**, never from wall-clock time. At server startup, before any call is processed, the logical clock reads `2026-01-01T00:00:00Z`. It is advanced only by an administrative test-driving capability that sets it to a supplied instant, and it never falls back to wall-clock time. All response-time, handle-time, stale-recommendation, and report-window computations read this clock so that results are reproducible across runs.

### 2.5. Optimistic Concurrency on Incident Dispatch

Committing a unit to an incident is the one operation guarded by optimistic concurrency control. The request that creates an assignment against an incident must carry `expected_incident_version`, a non-optional field whose value is the `version` of the target incident as the client last observed it. The server compares this value against the incident's current `version`. If they differ — meaning another writer has advanced the incident since the client's last read — the create is rejected with `ERR_STALE_INCIDENT_VERSION` and HTTP status 412.

This guard exists because the recommendation a dispatcher is acting on can go stale the moment another dispatcher commits the nearest unit: that commit bumps the incident's `version` and may flip its `lifecycle_status` from `PENDING` to `DISPATCHED`, so the first dispatcher's view of "which unit is still the nearest available recommendation" is no longer current. Rejecting on a version mismatch forces the dispatcher to re-read and re-recommend before committing. No other endpoint takes a version field; only assignment creation participates in this check.

### 2.6. Validation Ordering and Reference Integrity

When more than one rule could reject a request, the platform evaluates them in a fixed precedence so that the returned error is deterministic. Authentication is checked first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Third, every resource identifier named in the URL path is checked for existence, validated left to right, with the first missing identifier yielding `ERR_NOT_FOUND`. Fourth, for operations that carry foreign-key references in their body, each referenced resource must exist or the request is rejected with `ERR_REFERENCE_NOT_FOUND`; this applies to creating an assignment, creating a station, creating a unit, recording a disposition, and generating a report. Fifth, the body itself is validated for well-formedness — required fields present, enumerated values legal, integers within range, the `ani` exactly ten digits, and every grid coordinate within the inclusive range from 0 to 1000 — with violations yielding `ERR_INVALID_REQUEST`.

Only after those five gates pass does the platform evaluate state and business rules. For assignment creation the order continues: the optimistic-concurrency check on `expected_incident_version` (priority six, `ERR_STALE_INCIDENT_VERSION`); then the general state-validity check that the target resource is in a legal state for the requested transition (priority seven, `ERR_INVALID_STATE`); then the held-incident guard (priority eight, `ERR_INCIDENT_HELD`); then discipline match (priority nine, `ERR_DISCIPLINE_MISMATCH`); then agency availability (priority ten, `ERR_AGENCY_UNAVAILABLE`); then unit availability (priority eleven, `ERR_UNIT_NOT_AVAILABLE`); then the duplicate-assignment guard (priority twelve, `ERR_DUPLICATE_ASSIGNMENT`); and finally, when the dispatch is an auto-selection, the no-eligible-unit outcome (priority thirteen, `ERR_NO_UNIT_AVAILABLE`). The left-to-right path existence rule means that, for a nested path such as the one used to list an incident's assignments, a non-existent incident surfaces `ERR_NOT_FOUND` before any assignment is considered.

### 2.7. Hierarchical Consistency and Cascades

A single operation in this domain routinely mutates several records at once, and the platform must keep them consistent in one atomic step. Committing the first unit to a pending incident not only creates the assignment but also advances the incident's lifecycle and stamps its first-dispatch instant, drives the unit into a committed availability state, and increments the incident's `version`. The first on-scene arrival bubbles up to flip the incident from `DISPATCHED` to `ACTIVE` and triggers the response-time, handle-time, and SLA recomputations. Closing an incident cascades across every still-open assignment and the units they hold. Cancelling the sole pre-arrival assignment can revert the incident back to `PENDING`.

Whenever the platform mutates a record as part of such a cascade, that record's `updated_at` is refreshed. The incident's `version` is incremented specifically on first dispatch, on each escalation, and on close — the mutations enumerated in §3 — so that any client holding a prior `version` will be caught by the optimistic-concurrency check described in §2.5. These automatic transitions occur without a separate client request against each affected record; they are the defined side effects of the triggering operation.

### 2.8. Grid Geometry, Distance, and Numeric Precision

Locations in this system are expressed on an integer grid. Every grid coordinate — a station's `grid_x` and `grid_y`, a unit's current `grid_x` and `grid_y`, a premise alert's `grid_x` and `grid_y`, and an incident's `ali_grid_x` and `ali_grid_y` — is an integer in the inclusive range from 0 to 1000. The travel distance the platform uses for unit ranking and records on each assignment is the **Manhattan distance**: the absolute difference of the x-coordinates plus the absolute difference of the y-coordinates between the unit's current position and the incident's ALI location. This distance is an exact integer and is never rounded.

Time-derived metrics are likewise integers. Response time and total handle time are each computed as a difference of two logical-clock instants expressed in whole seconds, with any fractional second discarded by taking the floor. Priority levels are integers in the inclusive range from 1 (highest urgency) through 5 (lowest). The SLA-breach determination is a boolean produced by a strict comparison described in §3. There are no decimal money fields in this domain; all quantitative outputs are exact integers or booleans.

### 2.9. Enumerations and the Mutual-Aid Posture

Several fields are constrained to fixed vocabularies, and implementations must use these exact strings. An agency's `discipline` is one of `POLICE`, `FIRE`, or `EMS`, and its operational `status` is one of `ONLINE`, `MUTUAL_AID_ONLY`, or `OFFLINE`. A unit's `capability` is one of `PATROL`, `K9`, `SUPERVISOR_UNIT`, `ENGINE`, `LADDER`, `MEDIC_ALS`, or `MEDIC_BLS`, and its `status` is one of `AVAILABLE`, `DISPATCHED`, `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE`. A premise alert's `hazard_class` is one of `WEAPONS`, `HAZMAT`, `COMBATIVE_SUBJECT`, `STRUCTURAL`, `MEDICAL_HISTORY`, or `NONE`. An incident's `incident_type` is one of `STRUCTURE_FIRE`, `MEDICAL_EMERGENCY`, `TRAFFIC_COLLISION`, `ASSAULT_IN_PROGRESS`, `ALARM`, or `WELFARE_CHECK`; its `ali_confidence` is one of `HIGH`, `LOW`, or `UNKNOWN`; and its `lifecycle_status` is one of `PENDING`, `DISPATCHED`, `ACTIVE`, `HELD`, `CLOSED`, or `CANCELLED`. An assignment's `status` is one of `DISPATCHED`, `ENROUTE`, `ONSCENE`, `CLEARED`, or `CANCELLED`. A disposition outcome is one of `REPORT_TAKEN`, `ARREST`, `TRANSPORT`, `FIRE_OUT`, `UNFOUNDED`, `GONE_ON_ARRIVAL`, or `CANCELLED`; an incident's `disposition_code` may also be unset until close. A report's `report_standard` is either `NENA` or `NFIRS`.

An agency's `status` shapes whether its units may be recommended. An `ONLINE` agency is fully in service. A supervisor may move an `ONLINE` agency to `MUTUAL_AID_ONLY`, which excludes its units from the in-jurisdiction recommendation pass but keeps them eligible as a mutual-aid fallback; from `MUTUAL_AID_ONLY` the supervisor may move the agency to `OFFLINE`, which excludes its units from all recommendation passes, or back to `ONLINE`. Each of these is a single-step transition: `ONLINE → MUTUAL_AID_ONLY`, `MUTUAL_AID_ONLY → OFFLINE`, and `MUTUAL_AID_ONLY → ONLINE`. Requesting a status change from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Standing the Network Up: Agencies, Stations, and Units

Before any call can be worked, a supervisor builds out the responder network. An **agency** represents a police, fire, or EMS jurisdiction and is created with a display `name`, a `discipline`, and a `response_sla_seconds` target — the on-scene service-level target for that discipline, an integer of at least 1. A newly created agency comes up with its `status` set to `ONLINE`.

A **station** is the physical house an agency operates from. It is created with its owning `agency_id`, a `name`, and an integer grid position given by `grid_x` and `grid_y`, each between 0 and 1000 inclusive.

A **unit** is a deployable field resource. Creating one requires the owning `agency_id`, the home `station_id`, a radio `call_sign`, and a `capability` tier; the unit's discipline is inherited from its agency. A unit's starting position may be supplied as `grid_x` and `grid_y`, but when those are omitted the platform defaults the unit's grid to the home station's grid. A new unit comes up with `status` set to `AVAILABLE` and `active_incident_id` set to nothing, since it is not yet committed to any incident. Two integrity rules guard unit creation: the `call_sign` must be unique within the unit's agency — a collision is rejected with `ERR_DUPLICATE_CALL_SIGN` — and the referenced station must belong to the same agency as the unit, or the request is rejected with `ERR_STATION_AGENCY_MISMATCH`.

A field unit governs its own readiness independently of any incident. Toggling a unit that is `AVAILABLE` into `OUT_OF_SERVICE` removes it from the recommendation candidate pool; the reverse transition from `OUT_OF_SERVICE` back to `AVAILABLE` returns it to service. These two transitions, `AVAILABLE → OUT_OF_SERVICE` and `OUT_OF_SERVICE → AVAILABLE`, are the only ones the manual readiness toggle performs; it is not the path for assignment-driven status changes, and attempting it from any other status is rejected with `ERR_INVALID_STATE`. Units may be listed and filtered by their owning agency, their home station, their `status`, and the incident they are currently committed to via `active_incident_id`. Agencies may be listed and filtered by `discipline` and `status`; stations may be filtered by `agency_id`.

### 3.2. Premise and Hazard Alerts

A **premise alert** is a standing safety notice keyed to a grid location. A supervisor or a records user creates one by supplying the `grid_x` and `grid_y` it covers, a `hazard_class`, and a `min_priority_floor` — an integer between 1 and 5 inclusive that represents the most-urgent priority any incident at that grid should be clamped to (a lower number meaning higher urgency). A new alert comes up with `active` set to true. The same users may later deactivate or reactivate an alert by toggling its `active` flag. Toggling `active` is forward-looking only: it never retroactively re-clamps incidents that were already created, so an alert deactivated after an intake leaves that incident's computed priority untouched. Premise alerts may be listed and filtered by `grid_x`, `grid_y`, and `active`.

### 3.3. Call Intake and Priority Computation

Call intake is performed by a calltaker (or a supervisor). The intake payload carries the caller's `ani` — the Automatic Number Identification, a ten-digit phone number — the Automatic Location Identification grid given by `ali_grid_x` and `ali_grid_y`, the `incident_type`, and an optional `ali_confidence` that defaults to `HIGH`. On acceptance the platform mints a human-readable `incident_number` in the format `CFS-YYYY-NNNNNN`, assigned monotonically; stamps `received_at` from the logical clock; and brings the incident up with `lifecycle_status` set to `PENDING`. The fields `first_dispatch_at`, `first_onscene_at`, and `closed_at` are unset at intake, `escalation_count` starts at 0, `disposition_code` is unset, and the computed metrics `response_time_seconds` and `total_handle_seconds` are unset while `sla_breached` starts as false.

Intake also derives the incident's disciplines and urgency. The `required_disciplines` set is fixed by `incident_type`: a `STRUCTURE_FIRE` requires `FIRE` and `EMS`; a `MEDICAL_EMERGENCY` requires `EMS`; a `TRAFFIC_COLLISION` requires `POLICE` and `EMS`; an `ASSAULT_IN_PROGRESS` requires `POLICE`; an `ALARM` requires `POLICE`; and a `WELFARE_CHECK` requires `POLICE`.

Priority is computed in a fixed four-step order at intake. First, the `base_priority_level` is read from the incident type: a `STRUCTURE_FIRE` and an `ASSAULT_IN_PROGRESS` each have base 1; a `MEDICAL_EMERGENCY` has base 2; a `TRAFFIC_COLLISION` has base 3; an `ALARM` has base 4; and a `WELFARE_CHECK` has base 5. Second, the platform searches for an active premise alert whose `grid_x` and `grid_y` exactly equal the incident's `ali_grid_x` and `ali_grid_y`; if more than one matches, it selects the one with the lowest `min_priority_floor`, breaking any remaining tie by earliest creation timestamp. Third, if an alert matched, the incident's `premise_alert_id` is set to that alert and the `priority_level` becomes the smaller of the `base_priority_level` and the alert's `min_priority_floor` — clamping the incident toward higher urgency; if no alert matched, `premise_alert_id` stays unset and the `priority_level` equals the `base_priority_level`. Fourth, and applied strictly after the premise clamp, if `ali_confidence` is `UNKNOWN` the `priority_level` is set to the smaller of its current value and 2 — a degrade-safe clamp that guarantees an uncertain fix is treated as at least moderately urgent. Incidents may be listed and filtered by `lifecycle_status`, `priority_level`, and `premise_alert_id`.

### 3.4. Recommending and Committing Units

When a dispatcher prepares to send help, they first ask the platform for the nearest unit. The recommendation targets a single discipline: the caller may name a `discipline`, but if none is supplied the platform picks the next discipline among the incident's `required_disciplines` that is not yet covered by a non-cancelled assignment on this incident. The candidate pool is every unit that satisfies all of these conditions at once: the unit's `status` is `AVAILABLE`; the unit's agency `status` is `ONLINE`; the unit's agency `discipline` equals the requested discipline; and the unit is not already tied to this incident through a non-cancelled assignment.

Candidates are ranked lexicographically in ascending order, lowest winning, on three keys in this order. The first key is the Manhattan `travel_distance` from the unit's current grid to the incident's ALI grid. The second key is a capability preference for the incident type: a unit whose `capability` is among the incident type's preferred tiers ranks ahead of one whose capability is not. The preferred tiers are, for a `STRUCTURE_FIRE`, `ENGINE` then `LADDER`; for a `MEDICAL_EMERGENCY`, `MEDIC_ALS` then `MEDIC_BLS`; for a `TRAFFIC_COLLISION`, `PATROL` then `MEDIC_BLS`; for an `ASSAULT_IN_PROGRESS`, `PATROL` then `K9`; for an `ALARM`, `PATROL` then `ENGINE`; and for a `WELFARE_CHECK`, `PATROL`. The third key, used only to break a remaining tie, is the unit's creation timestamp, earliest winning — never the unit's `id`.

If the primary pass yields no candidate, the platform runs a second, mutual-aid pass with the agency-status condition widened to include both `ONLINE` and `MUTUAL_AID_ONLY` agencies. If that pass is also empty there is no recommendation. The recommendation response reports `recommended_unit_id`, the chosen `discipline`, the winning `travel_distance`, and the `candidate_count` of eligible units considered; when no unit qualifies, the recommendation returns successfully with `recommended_unit_id` unset.

Committing a unit is how a dispatcher actually dispatches. The request carries the mandatory `expected_incident_version` (see §2.5) and identifies the unit either explicitly by `unit_id` or by setting `auto_select` true to take the platform's own recommendation; a `discipline` may also be named to steer which discipline an auto-selection covers. The platform records the new assignment with `status` `DISPATCHED`, sets its `recommended` flag true exactly when the committed unit was the unit the recommendation would have chosen at that moment, computes and stores its Manhattan `travel_distance`, stamps its `dispatched_at` from the logical clock, drives the unit's `status` to `DISPATCHED`, and sets the unit's `active_incident_id` to this incident. The assignment fields `enroute_at`, `onscene_at`, and `cleared_at` remain unset for now. When this is the incident's first accepted assignment, the incident's `lifecycle_status` advances from `PENDING` to `DISPATCHED`, its `first_dispatch_at` is stamped, and its `version` is incremented; the precondition for this transition is that the incident is `PENDING` and that the committed unit's agency discipline is among the incident's `required_disciplines`.

Several guards protect this commit, each tied to a specific rejection. If the incident is currently `HELD`, no new unit may be committed and the request is rejected with `ERR_INCIDENT_HELD`. The committed unit's agency `discipline` must be one of the incident's `required_disciplines`, or the request is rejected with `ERR_DISCIPLINE_MISMATCH`. The unit's agency must be `ONLINE` for an in-jurisdiction dispatch, or `MUTUAL_AID_ONLY` only when no `ONLINE` unit of that discipline exists; an agency that is `OFFLINE`, or `MUTUAL_AID_ONLY` while an `ONLINE` unit of that discipline still exists, is rejected with `ERR_AGENCY_UNAVAILABLE`. The unit must be `AVAILABLE`; a unit already `DISPATCHED`, `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with `ERR_UNIT_NOT_AVAILABLE`. A unit may not be committed to the same incident twice through a non-cancelled assignment, which is rejected with `ERR_DUPLICATE_ASSIGNMENT`. And when the dispatch is an auto-selection but neither the primary nor the mutual-aid pass yields an eligible unit, the request is rejected with `ERR_NO_UNIT_AVAILABLE`. Assignments may be listed and filtered by `incident_id`, `unit_id`, and `status`, both globally and as the reverse lookup of a single incident's assignments.

### 3.5. The Field Pipeline: Enroute, Onscene, Clear, and Cancel

Once committed, a unit reports its own progress, and each report advances the assignment along its pipeline while dragging the unit's availability with it. A `FieldUnit` ordinarily drives these reports — and may act only on its own assignment, the one whose unit matches `X-User-ID` — while a dispatcher or supervisor may drive clears and cancels as well. Every report is carried on the same field-status operation and names the target `status`; an attempt to make a transition that the assignment's current state does not allow is rejected with `ERR_INVALID_STATE`.

From `DISPATCHED`, going **enroute** moves the assignment `DISPATCHED → ENROUTE`, stamps its `enroute_at`, and drives the unit's `status` to `ENROUTE`. From `ENROUTE`, going **onscene** moves the assignment `ENROUTE → ONSCENE`, stamps its `onscene_at`, drives the unit's `status` to `ONSCENE`, and snaps the unit's `grid_x` and `grid_y` to the incident's ALI grid. The on-scene report carries a critical bubble-up: if this is the incident's *first* unit to reach the scene, the incident's `lifecycle_status` advances `DISPATCHED → ACTIVE`, its `first_onscene_at` is stamped, and its response time, total handle time, and SLA breach are recomputed as described in §3.6.

The pipeline is deliberately non-linear. A unit pulled back off scene may **re-stage** from `ONSCENE → ENROUTE`; this clears the assignment's `onscene_at` and returns the unit's `status` to `ENROUTE`, but it does not undo the incident's `first_onscene_at` — the incident remains `ACTIVE`. Re-staging is permitted only while the incident is not `HELD`. **Clearing** ends the assignment: from `ONSCENE`, clearing moves it `ONSCENE → CLEARED`, stamps `cleared_at`, and walks the unit's `status` through `CLEARING` and on to `AVAILABLE` while clearing the unit's `active_incident_id`; from `ENROUTE`, clearing moves the assignment `ENROUTE → CLEARED`, stamps `cleared_at`, and returns the unit directly to `AVAILABLE` with its `active_incident_id` cleared. **Cancelling** a still-pending assignment likewise frees the unit: from `DISPATCHED`, cancelling moves it `DISPATCHED → CANCELLED` and returns the unit to `AVAILABLE` with `active_incident_id` cleared; from `ENROUTE`, cancelling moves it `ENROUTE → CANCELLED` and likewise frees the unit. A cancellation from `DISPATCHED` carries one further cascade: if the cancelled assignment was the only non-terminal assignment on the incident and it had carried the incident's first dispatch with no unit ever having reached the scene, the incident reverts `DISPATCHED → PENDING` and its `first_dispatch_at` is cleared, returning the incident to an undispatched state.

### 3.6. Response Time, Handle Time, and SLA Breach

The platform tracks two distinct timing metrics that share a pair of subject instants but anchor their clocks differently, so identical incidents produce different numbers whenever queue time is non-zero. Both are recomputed at the moment the first unit reaches the scene, and both are re-snapshotted when a report is generated.

The dispatch-based **response time**, stored as `response_time_seconds`, is the whole number of seconds from the incident's `first_dispatch_at` to its `first_onscene_at`, with any fractional second discarded by flooring. It uses the dispatch instant as the clock start and therefore excludes the intake-to-dispatch queue time. It is defined only once both `first_dispatch_at` and `first_onscene_at` are set, and is unset otherwise. The call-receipt-based **total handle time**, stored as `total_handle_seconds`, is the whole number of seconds from the incident's `received_at` to its `first_onscene_at`, again floored. It uses the call-receipt instant as the clock start and therefore *includes* the intake-to-dispatch queue time. Because the two metrics share the same `first_onscene_at` endpoint but start from different anchors, they diverge by exactly the intake-to-dispatch queue delay.

The SLA breach is evaluated against a governing target. The platform first determines the governing SLA as the largest `response_sla_seconds` among the agencies that both have a discipline within the incident's `required_disciplines` and have at least one non-cancelled assignment on this incident; if no such agency exists, it instead uses the smallest `response_sla_seconds` across agencies of the required disciplines, taking the strictest applicable target. The incident's `sla_breached` is true only when `total_handle_seconds` is strictly greater than the governing SLA — a handle time exactly equal to the target is not a breach.

### 3.7. Escalation, Hold, Resume, and the Priority Dimension

An incident's priority is a second, independent state dimension that can ratchet upward while the incident is open. **Escalation** — invoked manually by a supervisor, or by the timer-driven system actor when an incident has gone too long without a first dispatch past its SLA grace — raises urgency by one step: the `priority_level` is decremented by one toward 1, the `escalation_count` is incremented by one, and the incident's `version` is incremented. An optional `reason` may accompany the request. Escalation is permitted only while the incident's `lifecycle_status` is not `CLOSED` or `CANCELLED` and its `priority_level` is greater than 1; an incident already at top urgency or in a terminal lifecycle state cannot escalate and is rejected with `ERR_INVALID_STATE`. Because priority is cyclic, an incident may escalate repeatedly over its life.

A supervisor may **hold** an incident to freeze it, with an optional `reason`. Holding moves the `lifecycle_status` `ACTIVE → HELD` and is permitted only when the incident is `ACTIVE` and at least one assignment on it is `ONSCENE`; otherwise the request is rejected with `ERR_INVALID_STATE`. While an incident is `HELD` no new units may be committed to it (see the `ERR_INCIDENT_HELD` guard in §3.4) and an on-scene unit may not re-stage. **Resuming** moves the incident `HELD → ACTIVE`, unfreezing it; it is permitted only from `HELD` and is otherwise rejected with `ERR_INVALID_STATE`.

### 3.8. Closing the Incident and Cancelling Pre-Dispatch

There are two terminal paths for an incident. The first is **cancellation before any dispatch**: a calltaker or supervisor may cancel an incident that is still `PENDING` and against which no assignment has ever been created, with an optional `reason`. Cancellation moves the `lifecycle_status` `PENDING → CANCELLED`, stamps `closed_at`, and sets the `disposition_code` to `CANCELLED`. If the incident is not `PENDING`, or any assignment exists for it, the cancel is rejected with `ERR_INVALID_STATE`.

The second path is **closing with a disposition**, which a supervisor performs by recording a disposition against the incident. The disposition payload carries a `disposition_code` — one of `REPORT_TAKEN`, `ARREST`, `TRANSPORT`, `FIRE_OUT`, `UNFOUNDED`, `GONE_ON_ARRIVAL`, or `CANCELLED` — and a free-text `narrative`. Closing requires that the incident be `DISPATCHED`, `ACTIVE`, or `HELD`, and that every assignment on the incident already be `CLEARED` or `CANCELLED`; if any assignment is still `DISPATCHED`, `ENROUTE`, or `ONSCENE`, the close is rejected with `ERR_OPEN_ASSIGNMENTS`, and an incident not in a closable lifecycle state is rejected with `ERR_INVALID_STATE`. On a successful close the platform sets the incident's `closed_at`, copies the disposition's outcome into the incident's `disposition_code`, and increments the incident's `version`. The `ERR_OPEN_ASSIGNMENTS` precondition is the sole guard on the assignment dimension and it wins outright: because the close cannot succeed while any assignment is still `DISPATCHED`, `ENROUTE`, or `ONSCENE`, every assignment is already `CLEARED` or `CANCELLED` at the moment of a successful close, so the close itself never force-clears an open assignment and never alters any unit's `status` or `active_incident_id` — each unit was already returned to `AVAILABLE` (and its `active_incident_id` cleared) by the field-pipeline clear or cancel that drove its assignment to a terminal state. The disposition record also computes `requires_nfirs`, which is true exactly when the incident required `FIRE` discipline, signalling that a fire report will be mandatory. Dispositions may be listed as the reverse lookup of a single incident.

### 3.9. Regulatory Reporting

Once an incident is closed, a records user or a supervisor may generate a **call-for-service report** by naming a `report_standard` of either `NENA` or `NFIRS`. A report is an immutable snapshot: at generation the platform copies the incident's `response_time_seconds`, `total_handle_seconds`, `sla_breached`, and `disposition_code` into the report and records the covering `incident_id`. It also computes the report's `unit_count` as the number of assignments on the incident whose `status` is `ONSCENE` or `CLEARED` — only units that actually reached the scene are rolled in, while `DISPATCHED`, `ENROUTE`, and `CANCELLED` assignments are excluded.

Two rules guard report generation. A report may only be generated for a `CLOSED` incident; a request against an incident in any other lifecycle state is rejected with `ERR_INCIDENT_NOT_CLOSED`. And an `NFIRS` report may only be generated for an incident that required `FIRE` discipline — the requested standard must match the incident's disciplines — so requesting `NFIRS` for a non-fire incident, or a standard incompatible with the incident's disciplines, is rejected with `ERR_REPORT_STANDARD_MISMATCH`. Reports may be listed as the reverse lookup of a single incident and filtered by `report_standard`, and a single report may be retrieved by its identifier.

### 3.10. Driving the Logical Clock

Because every business instant is read from the logical clock described in §2.4, the platform exposes an administrative test-driving capability, restricted to the `SystemClock` role, that sets the clock to a supplied instant. The request carries `to_iso8601`, the ISO 8601 instant the clock should advance to, and the response reports the resulting `current_utc`. Setting the clock changes the timestamps that subsequent intake, dispatch, on-scene, close, and report operations will record; it does not retroactively alter instants already stamped on existing records.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, change its state, or set the logical clock return `200 OK`. The table below lists method, path, purpose, and authorized roles only; the request and response payloads and side effects for each operation are defined in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/agencies` | Create an agency (police/fire/EMS jurisdiction) | Supervisor |
| GET    | `/agencies/{id}` | Get one agency | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/agencies` | List agencies | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| PATCH  | `/agencies/{id}/status` | Change agency operational status | Supervisor |
| POST   | `/stations` | Create a station under an agency | Supervisor |
| GET    | `/stations/{id}` | Get one station | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/stations` | List stations, optionally filtered by agency | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| POST   | `/units` | Create a field unit attached to an agency and home station | Supervisor |
| GET    | `/units/{id}` | Get one unit | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/units` | List units, filterable by agency, station, status | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| PATCH  | `/units/{id}/status` | Toggle unit AVAILABLE/OUT_OF_SERVICE | FieldUnit, Supervisor |
| POST   | `/premise-alerts` | Create a standing premise/hazard alert keyed to a grid | Supervisor, Records |
| GET    | `/premise-alerts/{id}` | Get one premise alert | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/premise-alerts` | List premise alerts, filterable by grid | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| PATCH  | `/premise-alerts/{id}` | Deactivate or reactivate a premise alert | Supervisor, Records |
| POST   | `/incidents` | Call intake: create an incident from ANI/ALI and type | Calltaker, Supervisor |
| GET    | `/incidents/{id}` | Get one incident (full computed state) | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/incidents` | List incidents, filterable by lifecycle and priority | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/incidents/{id}/recommendation` | Nearest-unit recommendation for the next uncovered discipline | Dispatcher, Supervisor |
| POST   | `/incidents/{id}/assignments` | Dispatch a unit to the incident | Dispatcher, Supervisor |
| GET    | `/incidents/{id}/assignments` | List assignments for an incident | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| POST   | `/incidents/{id}/escalate` | Escalate incident priority by one level | Supervisor |
| POST   | `/incidents/{id}/hold` | Freeze an ACTIVE incident | Supervisor |
| POST   | `/incidents/{id}/resume` | Resume a HELD incident | Supervisor |
| POST   | `/incidents/{id}/cancel` | Cancel a PENDING incident never dispatched | Calltaker, Supervisor |
| GET    | `/assignments/{id}` | Get one assignment | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| GET    | `/assignments` | List assignments, filterable by incident, unit, status | Calltaker, Dispatcher, FieldUnit, Supervisor, Records |
| PATCH  | `/assignments/{id}/status` | Advance assignment status (enroute/onscene/clear/cancel/re-stage) | FieldUnit, Dispatcher, Supervisor |
| POST   | `/incidents/{id}/dispositions` | Close an incident with a disposition code | Supervisor |
| GET    | `/incidents/{id}/dispositions` | List dispositions for an incident | Calltaker, Dispatcher, Supervisor, Records |
| POST   | `/incidents/{id}/reports` | Generate a NENA or NFIRS report for a CLOSED incident | Records, Supervisor |
| GET    | `/incidents/{id}/reports` | List reports for an incident | Calltaker, Dispatcher, Supervisor, Records |
| GET    | `/reports/{id}` | Get one report | Calltaker, Dispatcher, Supervisor, Records |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock | SystemClock |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_INCIDENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INCIDENT_HELD` | 409 |
| `ERR_DISCIPLINE_MISMATCH` | 409 |
| `ERR_AGENCY_UNAVAILABLE` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 |
| `ERR_NO_UNIT_AVAILABLE` | 409 |
| `ERR_OPEN_ASSIGNMENTS` | 409 |
| `ERR_REPORT_STANDARD_MISMATCH` | 409 |
| `ERR_INCIDENT_NOT_CLOSED` | 409 |
| `ERR_DUPLICATE_CALL_SIGN` | 409 |
| `ERR_STATION_AGENCY_MISMATCH` | 409 |
