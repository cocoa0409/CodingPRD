# Sar Volunteer Coordination API — Product Requirements Document

## 1. Introduction

Search-and-rescue operations run on volunteers, and volunteers arrive faster than paperwork can keep up. This API is the coordination backbone for a SAR organization that must stand up an incident, call out qualified team members, assign specialized resources such as K9 units and aircraft, track ground coverage, evaluate clues, and eventually reimburse responders — all while remaining faithful to the Incident Command System (ICS) that governs field operations. The system exists to make the operational picture trustworthy: who is deployed where, which search segments are covered, which assets are committed to which windows, and what the organization ultimately owes.

The domain is deliberately unforgiving about state. A responder cannot be sent into the field on an expired certification; an aircraft cannot occupy two overlapping windows; an incident cannot be closed while tasks are still running; and money cannot be approved before an incident has begun to wind down. The API encodes these realities as an interlocking set of state machines, cascading side effects, and dual-variant calculations (a planning-time estimate versus an evidence-reconciled final figure). Every resource lives as a peer under a shared `/sar` root, and every foreign-key relationship is navigable through filtered list endpoints so that the full operational graph is reconstructable at any time.

This document specifies the complete contract: the response envelope, authentication and role model, pagination, the lifecycle of each entity, the precise calculation rules, and the full error catalogue. It is written for the engineer who must implement the service and for the reviewer who must confirm that field operations, safety governance, and financial adjudication all behave exactly as command staff expect.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Coordinator`, `IncidentCommander`, `FinanceOfficer`, and `Member`. A `Coordinator` owns the operational surface — creating incidents, tasks, teams, members, certifications, and resources, running callouts, assigning resources, and logging ground tracks and clues. An `IncidentCommander` owns command decisions — the incident lifecycle, task assignment, clue evaluation, and after-action finalization. A `FinanceOfficer` owns reimbursement adjudication. A `Member` is a volunteer who acts on their own callouts, claims, and ground tracks.

Three of these roles carry an operator identity that is not tied to any stored record. When `X-User-Role` is `Coordinator`, `IncidentCommander`, or `FinanceOfficer`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare that resource's member foreign key to `X-User-ID`. In practice this means that when a `Member` acknowledges or declines a callout, submits a reimbursement claim, or logs a ground track, the target's `member_id` must equal the caller's `X-User-ID`, or the action is rejected with `ERR_FORBIDDEN_NOT_OWNER`.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data — only the clock-setting call — the `data` field is `null`. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is clamped to the nearest bound rather than rejected, and a non-integer value falls back to its default (10 and 0 respectively).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching records before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a server-minted `id` formatted as a UUID (with no type prefix) and a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded when the resource is first created. Most resources additionally carry an `updated_at` timestamp — refreshed on every mutation — and an integer `version` that starts at 1 and increments by one on each mutation.

There is one deliberate exception. The `GroundTrack` entity is an append-only event log: each track carries only `id` and `created_at`. A `GroundTrack` has no `updated_at` and no `version`, because it is immutable once recorded and is never updated after creation.

All time-sensitive evaluation in the system — certification expiry, resource occupation windows, callout stamping, and deployment timing — is measured against a **logical clock**, never the real wall clock. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an operator explicitly advances it. An operator may set the clock to a supplied `to_iso8601` instant through the administrative clock-setting capability described in §4; this is the only way the clock moves.

### 2.5. Validation Precedence and Ownership

When more than one rule could reject a request, the checks are applied in a fixed order so that the returned `error_id` is deterministic. The order is:

1. **Authentication.** Both headers must be present and `X-User-Role` must be a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The role must be permitted for the operation per §2.1 and the endpoint table, else `ERR_UNAUTHORIZED` (403).
3. **Path existence.** Every resource named in the path must exist, validated left-to-right (see §2.7), else `ERR_NOT_FOUND` (404).
4. **Body well-formedness.** The request body must be well-formed: required fields present, enum values legal, numeric ranges honored (for example `segment_area_sqkm` strictly greater than 0, `planned_end` strictly after `planned_start`, `window_end` strictly after `window_start`, and non-negative amounts), and any foreign key named in the body must reference an existing record. Otherwise `ERR_VALIDATION` (422).
5. **Ownership.** For a `Member` acting on their own callout, claim, or ground track, the target's member foreign key must equal `X-User-ID`, else `ERR_FORBIDDEN_NOT_OWNER` (403).
6. **State legality.** The target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
7. **Sibling-entity state.** Any required state of a referenced sibling entity must hold, else the specific sibling error (`ERR_TASK_NOT_READY`, `ERR_RESOURCE_UNAVAILABLE`, `ERR_INCIDENT_NOT_ACTIVE`, `ERR_INCIDENT_NOT_DEMOBILIZING`, `ERR_INCIDENT_NOT_CLOSED`, or `ERR_TEAM_INACTIVE`), all at 409.
8. **Certification currency** (deployment only), else `ERR_CERT_REQUIREMENT_NOT_MET` (409).
9. **Temporal overlap**, else `ERR_RESOURCE_WINDOW_CONFLICT` or `ERR_MEMBER_DOUBLE_BOOKED` (409).
10. **Capacity and uniqueness**, else `ERR_TASK_AT_CAPACITY`, `ERR_DUPLICATE_CLAIM`, or `ERR_INCIDENT_HAS_ACTIVE_TASKS` (409).
11. **Deployed-responder presence** (task start only), else `ERR_NO_DEPLOYED_RESPONDERS` (409).
12. **Optimistic concurrency** on resource-assignment creation, checked last, after every business rule has passed, else `ERR_STALE_VERSION` (412).

The practical consequence is that an authentication failure always masks an authorization failure, a missing path resource always masks a malformed body, and the optimistic-concurrency check can only fire on a request that is otherwise entirely valid.

### 2.6. Hierarchical State Cascades and Reconciliation

Many transitions in this system do not touch a single resource; they ripple through the operational graph. When an operation mutates more than one entity, every affected entity is updated in the same operation, and each such mutation refreshes that entity's `updated_at` and increments its `version`. Two conserved quantities anchor these cascades and must always agree with reality: an incident's `total_approved_reimbursement_cents` (a running ledger of approved and paid claim value) and a resource's `active_assignment_count` (the number of live assignments holding the asset). Whenever a claim is approved, rejected from approval, or a resource assignment is created, released, or cancelled, the corresponding conserved quantity is adjusted by exactly the compensating amount so that the ledger and the count never drift.

Derived and computed fields — an incident's `active_task_count`, `total_logged_hours`, and `total_mileage_miles`; a resource's `status` and `active_assignment_count`; a certification's `status`; a member's `status` — are always kept consistent with the underlying records. The server transitions parent or child resources automatically when the cascade requires it, without an explicit client request against each affected resource. The individual cascade chains (incident cancellation reaching down to members, task suspension releasing resource assignments, task debrief demobilizing responders) are described in the workflow narratives of §3.

### 2.7. Nested Path Resolution

Requests are addressed by path identifiers, and every identifier named in a path is validated left-to-right before any business logic runs. The first identifier in the path that does not correspond to an existing resource causes immediate rejection with `ERR_NOT_FOUND`. Because all resources are peers under the shared `/sar` root, most paths carry a single identifier; nonetheless the left-to-right existence rule governs uniformly, and a resource is only acted upon once its own existence — and the existence of anything named ahead of it in the path — has been confirmed.

### 2.8. Optimistic Concurrency on Resource Scheduling

Creating a resource assignment reserves an asset's schedule for a window and legitimately supersedes any prior scheduling view of that asset. To protect against acting on a stale view, the create-assignment operation requires a non-optional `expected_resource_version` field carrying the client's last-observed `version` of the target `Resource`. The server compares this value to the resource's current `version`. If another assignment has been created against the same resource since the client last read it — advancing that resource's `version` and its set of occupied windows — the supplied `expected_resource_version` will be older than the current one, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This check is performed only after every other business rule for the create has passed, and it applies exclusively to resource-assignment creation; no other endpoint accepts or requires a version field.

### 2.9. Precision, Rounding, and Unit Conversion

All monetary figures are stored and returned as whole integer cents. Because every reimbursement input is an integer, the reimbursement arithmetic requires no rounding and the result is an exact number of cents.

Where rounding is required, the system always uses the **round-half-up** method. Coverage percentages, effort rollups, and reconciled mileage each specify their own rounding scale in the workflow narratives, but two conversion constants recur and are fixed system-wide: distance in kilometers is converted to miles by multiplying by `0.621371` (miles per kilometer), and durations recorded in minutes are converted to hours by dividing by 60. When a set being summed is empty, its sum is zero and any derived rollup is likewise zero. The specific scales — hours to two decimal places, aggregate mileage to a whole number, per-track coverage fractions to four decimal places, and coverage percentages to two decimal places — are stated with the calculations that use them in §3.

## 3. Business Logic & Workflows

### 3.1. Incidents and the Operational Period

An incident is the top-level container for a mission. A `Coordinator` or an `IncidentCommander` opens one by supplying its `name`, its `incident_type` (one of `WILDERNESS_SEARCH`, `DISASTER`, `URBAN`, `WATER`, or `AIR_SEARCH`), an `ics_incident_number` for external ICS integration, and optionally the `operational_period_hours` — the length of the current operational period, which defaults to 12 when omitted. A new incident starts in `PLANNING` status, and its ledger and rollup fields (`total_approved_reimbursement_cents`, `total_logged_hours`, `total_mileage_miles`, `active_task_count`) all begin at zero.

Only an `IncidentCommander` drives the incident lifecycle. Activating the incident moves it from `PLANNING` to `ACTIVE`, which is the precondition for assigning tasks. Winding down moves it from `ACTIVE` to `DEMOBILIZING`, the point at which reimbursement approval becomes possible. Closing moves it from `DEMOBILIZING` to `CLOSED`, but only when the incident has no live tasks: closing requires `active_task_count` to equal zero — that is, no task remains in `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED` — otherwise the close is rejected with `ERR_INCIDENT_HAS_ACTIVE_TASKS`. On close, the incident's effort rollups are recomputed: `total_logged_hours` is the sum of `duration_min` across every `GroundTrack` recorded on any task of this incident divided by 60, rounded half up to two decimal places; `total_mileage_miles` is the sum of `distance_km` across those same tracks multiplied by `0.621371`, rounded half up to a whole number. The `active_task_count` is the count of this incident's tasks currently in `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED`. These rollups are also refreshed whenever a new ground track is created, and they read as zero for an incident whose tasks carry no tracks.

Cancelling an incident is the most consequential command. From either `PLANNING` or `ACTIVE`, an `IncidentCommander` can move the incident to `CANCELLED`, and this fires a three-level cascade. First, every task of the incident whose status is `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED` is driven to `CANCELLED`. Each of those task cancellations in turn fires the task's own cancellation side effects: every non-terminal callout on the task is demobilized, each member who was `DEPLOYED` through such a callout is restored to `ACTIVE` (when they hold no other `DEPLOYED` callout), and every `RESERVED` or `ACTIVE` resource assignment on the task is cancelled with its resource's `active_assignment_count` decremented. `CLOSED` and `CANCELLED` are terminal for an incident.

### 3.2. Teams, Members, and Certification Currency

A `Coordinator` builds the roster. Teams are created with a `name`, a `team_type` (one of `GROUND`, `K9`, `AIR`, `SWIFTWATER`, or `MOUNTAIN`), and a `base_location`; a team opens in `ACTIVE` status. A `Coordinator` may deactivate a team, moving it from `ACTIVE` to `INACTIVE`, which blocks new deployments of the team's members. Members are created under a team by supplying the parent's `team_id` together with the volunteer's `full_name`, `email`, and `member_role` (one of `SEARCHER`, `TEAM_LEADER`, `K9_HANDLER`, or `PILOT`). A member opens in `ACTIVE` status; over an operation their `status` moves to `STANDBY` and `DEPLOYED` as their callouts advance, and back to `ACTIVE` when they demobilize.

Certifications are the gate to field deployment. A `Coordinator` records a certification for a member by supplying the parent's `member_id`, the `cert_type` (one of `WFR`, `ICS_100`, `TRACKER`, `K9_AREA`, `ROPE_TECH`, `SWIFTWATER`, or `PILOT`), an `issued_date`, and an `expires_date`. A certification's `status` is computed, not stored as input: it is `EXPIRED` when the logical clock is at or after the `expires_date`, and `VALID` otherwise. The boundary is inclusive on expiry — a certification whose `expires_date` exactly equals the current logical-clock instant is already `EXPIRED`, because expiry takes effect at the very start of the expiry instant. This currency is evaluated freshly every time a certification is read and every time a deployment checks a task's certification requirements.

### 3.3. Tasks: Planning, Assignment, and the Operational Window

Within an incident, a `Coordinator` or `IncidentCommander` defines the search work as tasks. A task is created against its parent `incident_id` and carries a `task_number` (the ICS task number), a `task_type` (one of `HASTY`, `GRID_SEARCH`, `K9`, `AIR_RECON`, `EVAC`, or `CONTAINMENT`), and an optional `priority` (`URGENT`, `STANDARD`, or `LOW`, defaulting to `STANDARD`). Planners describe the segment with `segment_area_sqkm` (the search segment area in square kilometers, which must be strictly greater than zero) and `planned_searcher_hours` (the planned total searcher-hours, which must be at least zero). The task also declares `required_cert_types` — an array of certification types a member must hold as `VALID` in order to be deployed, defaulting to an empty array — and `max_responders`, the ceiling on simultaneous non-terminal callouts, defaulting to 8. The operational window is fixed by `planned_start` and `planned_end`, both ISO 8601 UTC instants, with `planned_end` required to be strictly after `planned_start`. A new task opens in `DRAFT`, with both `estimated_coverage_pct` and `actual_coverage_pct` null until their respective transitions (assignment and debrief) compute them.

Only an `IncidentCommander` may assign a task, advancing it from `DRAFT` to `ASSIGNED`, and only while the parent incident is `ACTIVE`; otherwise the assignment is rejected with `ERR_INCIDENT_NOT_ACTIVE`. Assignment computes the planning-time coverage estimate stored in `estimated_coverage_pct`: multiply `planned_searcher_hours` by the coverage rate `COVERAGE_RATE_SQKM_PER_HOUR` of 0.5 square kilometers swept per searcher-hour to obtain a projected swept area, divide that by `segment_area_sqkm`, cap the resulting ratio at 1.0, multiply by 100, and round half up to two decimal places. This estimate uses planned effort only and consults no ground tracks.

A `Coordinator` or `IncidentCommander` starts an assigned task, advancing it from `ASSIGNED` to `IN_PROGRESS`, but only when at least one callout on the task is already `DEPLOYED`; a start with no deployed responder is rejected with `ERR_NO_DEPLOYED_RESPONDERS`. A running task can enter a weather-hold loop: suspending it moves it from `IN_PROGRESS` to `SUSPENDED`, and resuming moves it back from `SUSPENDED` to `IN_PROGRESS`. Suspension carries a cascade — every `ACTIVE` resource assignment on the task is released to `RELEASED`, and each such release decrements its resource's `active_assignment_count`, with the resource recomputed to `AVAILABLE` when its count reaches zero.

Debriefing moves the task from `IN_PROGRESS` to `DEBRIEFED` and produces the evidence-based coverage figure stored in `actual_coverage_pct`. This figure is computed with a **pinned rounding order** that must be honored exactly: for each `GroundTrack` recorded against the task, compute that track's coverage fraction as its `coverage_area_sqkm` divided by the task's `segment_area_sqkm`, and round that fraction half up to four decimal places; then sum those per-track fractions; then cap the sum at 1.0; then multiply by 100 and round half up to two decimal places. The per-track fractions are each rounded first and only then summed — rounding per track before summing, never summing before rounding — because the two orders can differ in the last cent of a percent. Debrief also demobilizes the field: every callout on the task that is `DEPLOYED` transitions to `DEMOBILIZED`, and each such demobilization restores its member to `ACTIVE` when that member holds no other `DEPLOYED` callout. Both `DEBRIEFED` and `CANCELLED` are terminal for a task.

A `Coordinator` or `IncidentCommander` may cancel any non-terminal task — one in `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED` — driving it to `CANCELLED`; the same transition also occurs automatically as the system cascade from an incident cancellation. Task cancellation fires the full field cascade: every callout on the task in `REQUESTED`, `ACKNOWLEDGED`, `STANDBY`, or `DEPLOYED` is demobilized; each callout that was `DEPLOYED` restores its member to `ACTIVE` (when the member has no other `DEPLOYED` callout); and every resource assignment on the task in `RESERVED` or `ACTIVE` is cancelled, each decrementing its resource's `active_assignment_count`.

### 3.4. Callouts: Paging, Acknowledgment, and Deployment

A callout is the junction that pages a specific member to a specific task. A `Coordinator` or `IncidentCommander` creates one by supplying the `task_id` and `member_id`; the server stamps `requested_at` from the logical clock, sets `status` to `REQUESTED`, and leaves `deployed_at` null until the member is actually deployed. A callout may only be created while the task has room: the number of non-terminal callouts on the task must be below its `max_responders`, or the create is rejected with `ERR_TASK_AT_CAPACITY`.

The responder controls the early lifecycle. The paged `Member`, acting on their own callout, can acknowledge it, moving it from `REQUESTED` to `ACKNOWLEDGED`, or decline it, moving it from either `REQUESTED` or `ACKNOWLEDGED` to `DECLINED`. Command staff then stage and commit responders. A `Coordinator` or `IncidentCommander` places an acknowledged callout on standby, moving it from `ACKNOWLEDGED` to `STANDBY`; this requires the member's team to be `ACTIVE`, otherwise it is rejected with `ERR_TEAM_INACTIVE`, and it sets the member's `status` to `STANDBY` when the member holds no `DEPLOYED` callout.

Deployment is the safety-critical step. A `Coordinator` or `IncidentCommander` deploys a standby callout, moving it from `STANDBY` to `DEPLOYED`, and three preconditions must all hold. First, the target task must be `ASSIGNED` or `IN_PROGRESS`, else `ERR_TASK_NOT_READY`. Second, the member must hold a `VALID` certification for every certification type listed in the task's `required_cert_types`, evaluated against the logical clock, else `ERR_CERT_REQUIREMENT_NOT_MET`. Third, the member must not be double-booked: they may hold no other `DEPLOYED` callout on a task whose planned window lies within the rest buffer of 60 minutes of this task's window — concretely, a conflict is raised when this task's window and the other's, each extended by 60 minutes, overlap (`this_start < other_end + 60min` and `other_start < this_end + 60min`), so a clear gap of at least 60 minutes between the two windows is permitted — else `ERR_MEMBER_DOUBLE_BOOKED`. A successful deploy sets the member's `status` to `DEPLOYED` and stamps `deployed_at` from the logical clock.

Standing responders down closes the loop. A `Coordinator` or `IncidentCommander` demobilizes a deployed callout, moving it from `DEPLOYED` to `DEMOBILIZED`, and this restores the member to `ACTIVE` when they hold no other `DEPLOYED` callout; the same demobilization also happens automatically as the system cascade from a task debrief or cancel. As part of the task-cancellation cascade, a callout still in `STANDBY` or `ACKNOWLEDGED` is moved to `DEMOBILIZED`, while a callout still in `REQUESTED` and never acknowledged is instead moved to `NO_RESPONSE`. The terminal callout states are `DEMOBILIZED`, `DECLINED`, and `NO_RESPONSE`.

### 3.5. Resources and Scheduling

Resources are the physical and canine assets of the operation. A `Coordinator` registers one with a `name`, a `resource_type` (one of `K9`, `HELICOPTER`, `FIXED_WING`, `DRONE`, `UTV`, or `BOAT`), and an optional `handler_member_id` naming the handler or pilot — nullable in general but required for a `K9`. A resource opens with `active_assignment_count` at zero and, being idle and in service, an effective `status` of `AVAILABLE`. A resource's `status` is always computed: it is `OUT_OF_SERVICE` whenever its `out_of_service` flag is set; otherwise it is `ASSIGNED` when `active_assignment_count` is greater than zero and `AVAILABLE` when the count is zero. A `Coordinator` toggles the manual `out_of_service` flag through the set-status capability by supplying the boolean `out_of_service`, and the computed `status` is refreshed accordingly.

Scheduling an asset is done through a resource assignment, created by a `Coordinator` or `IncidentCommander` who supplies the `resource_id`, the `task_id`, a `window_start` and `window_end` for a half-open occupation window `[window_start, window_end)` (with `window_end` strictly after `window_start`), and the `expected_resource_version` for the optimistic-concurrency check described in §2.8. The window is half-open: two assignments on the same resource conflict only when their intervals actually overlap, so an assignment ending exactly when another begins does not collide. A create is rejected with `ERR_RESOURCE_WINDOW_CONFLICT` when the proposed window overlaps any existing `RESERVED` or `ACTIVE` assignment on the same resource, and with `ERR_RESOURCE_UNAVAILABLE` when the resource is `OUT_OF_SERVICE`. A successful create opens the assignment in `RESERVED`, increments the resource's `active_assignment_count` by one, and increments the resource's `version` by one.

Assignments then track the task. A `Coordinator` or `IncidentCommander` activates a reserved assignment, moving it from `RESERVED` to `ACTIVE`, but only while the target task is `IN_PROGRESS`, else `ERR_TASK_NOT_READY`. Releasing an active assignment moves it from `ACTIVE` to `RELEASED`, and cancelling a reserved assignment moves it from `RESERVED` to `CANCELLED`; both decrement the resource's `active_assignment_count`, with the resource recomputed to `AVAILABLE` once the count reaches zero. These same releases and cancellations also occur automatically — a release as the cascade from a task suspension, and a cancellation as the cascade from a task cancellation, including the case where an already-`ACTIVE` assignment is cancelled wholesale during a task cancel. The count decrement always compensates the earlier increment so that the conserved `active_assignment_count` stays exact. `RELEASED` and `CANCELLED` are terminal for an assignment.

### 3.6. Ground Tracks and Effort Reconciliation

Ground tracks are the raw evidence of the search. A `Coordinator` or the searching `Member` logs a track against a `task_id` and a `member_id`, recording the instant it was captured in `recorded_at`, the distance walked in `distance_km` (at least zero), the elapsed time in `duration_min` (a non-negative whole number of minutes), and the area swept in `coverage_area_sqkm` (at least zero). A `Member` may only log tracks they own, matching the caller's `X-User-ID`. Tracks are append-only and immutable once written.

Every new track feeds the reconciliation machinery. It updates the parent incident's effort rollups — `total_logged_hours` and `total_mileage_miles` — as described in §3.1, and it becomes part of the evidence pool that a task debrief uses to compute `actual_coverage_pct` as described in §3.3. Tracks also feed the reimbursement reconciliation described in §3.8, where the mileage a member actually covered on an incident is derived from the distance of their tracks.

### 3.7. The Clue Log

Clues are logged by a `Coordinator`, `IncidentCommander`, or `Member` against an `incident_id`, optionally naming the `task_id` that surfaced the clue, together with a `clue_number`, an optional `clue_priority` (`URGENT`, `SIGNIFICANT`, or `ROUTINE`, defaulting to `ROUTINE`), a free-text `description`, and the `found_at` instant. A clue opens in `LOGGED`.

Evaluation is the `IncidentCommander`'s prerogative and forms a branching fork at `LOGGED`: the commander can promote a logged clue, moving it from `LOGGED` to `ACTIONABLE`, or dismiss it, moving it from `LOGGED` to `DISMISSED`. An actionable clue can subsequently be resolved, moving it from `ACTIONABLE` to `RESOLVED`, or dismissed after the fact, moving it from `ACTIONABLE` to `DISMISSED`. The terminal clue states are `DISMISSED` and `RESOLVED`.

### 3.8. Reimbursement Claims and the Incident Ledger

Reimbursement follows a member from the field to the finance desk. A `Coordinator` or the claiming `Member` opens a claim against a `member_id` and `incident_id`, declaring `declared_mileage_miles` (whole miles, at least zero) and optionally `meal_count` and `lodging_nights` (each defaulting to zero). A `Member` may only open a claim they own. At most one non-`REJECTED` claim may exist for any given member-and-incident pair; a second such claim is rejected with `ERR_DUPLICATE_CLAIM`. A new claim opens in `DRAFT`.

Reimbursement is computed on a fixed tiered schedule. The mileage component reimburses the first `MILEAGE_TIER1_LIMIT_MI` of 50 miles at `MILEAGE_RATE_TIER1_CPM` of 65 cents per mile and every mile strictly beyond 50 at `MILEAGE_RATE_TIER2_CPM` of 40 cents per mile: concretely, the tier-1 portion is the smaller of the mileage and 50 multiplied by 65 cents, the tier-2 portion is the mileage minus 50 (when positive, otherwise zero) multiplied by 40 cents, and exactly 50 miles is billed entirely at tier-1. The meal component is the smaller of `meal_count` and the cap `MEAL_MAX_COUNT` of 6, multiplied by `MEAL_PER_DIEM_CENTS` of 1500 cents per meal. The lodging component is `lodging_nights` multiplied by `LODGING_RATE_CENTS` of 9000 cents per night. The total is the sum of the mileage, meal, and lodging components, expressed in whole cents; because every input is an integer, no rounding is applied.

The claim moves through adjudication with two variants of that calculation. The claiming `Member` submits the claim, moving it from `DRAFT` to `SUBMITTED` (and later, after a return, from `RETURNED` to `SUBMITTED`); submission computes the **estimate variant** and stores it in `estimated_amount_cents`, using the member-declared, unverified `declared_mileage_miles` as the mileage input. A `FinanceOfficer` may return a submitted claim for revision, moving it from `SUBMITTED` to `RETURNED`, from which the member may submit again — the `SUBMITTED` and `RETURNED` states form a revision loop, and each resubmission recomputes `estimated_amount_cents`.

Approval is where evidence overrides declaration. A `FinanceOfficer` approves a submitted claim, moving it from `SUBMITTED` to `APPROVED`, but only when the parent incident is `DEMOBILIZING` or `CLOSED`, else `ERR_INCIDENT_NOT_DEMOBILIZING`. Approval computes the **final variant** and stores it in `final_amount_cents`, differing from the estimate only in its mileage input: instead of the declared figure, it uses the reconciled mileage, obtained by summing `distance_km` across every `GroundTrack` whose `member_id` equals the claim's member and whose task belongs to the claim's incident, multiplying that sum by `0.621371` miles per kilometer, and rounding half up to a whole number of miles. Where declared and tracked mileage disagree, the estimate and final figures diverge. Approval also credits the incident ledger: the incident's `total_approved_reimbursement_cents` is increased by the claim's `final_amount_cents`.

The remaining transitions keep that ledger honest. A `FinanceOfficer` may reject a claim from either `SUBMITTED` or `APPROVED`, moving it to `REJECTED`; when the rejection comes from `APPROVED`, the earlier ledger credit is reversed by decreasing the incident's `total_approved_reimbursement_cents` by that claim's `final_amount_cents`, restoring the pre-approval total. A `FinanceOfficer` pays an approved claim, moving it from `APPROVED` to `PAID`. The terminal claim states are `PAID` and `REJECTED`.

### 3.9. After-Action Reporting

The final artifact of an incident is its after-action report. A `Coordinator` or `IncidentCommander` opens one against an `incident_id`, supplying a `summary` and an optional `lessons_learned` narrative (defaulting to empty). The report opens in `DRAFT`. An `IncidentCommander` finalizes it, moving it from `DRAFT` to `FINALIZED`, but only once the parent incident is `CLOSED`, else `ERR_INCIDENT_NOT_CLOSED`. `FINALIZED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; state transitions and other modifications return `200 OK`. The administrative clock-setting call returns `200 OK`. All GET endpoints are readable by every role — `Coordinator`, `IncidentCommander`, `FinanceOfficer`, and `Member` — and are listed below as "All roles".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sar/_clock/set_current_utc` | Set the server logical clock | Coordinator |
| POST | `/sar/incidents` | Create an incident | Coordinator, IncidentCommander |
| GET | `/sar/incidents/{incidentId}` | Get one incident (computed rollups included) | All roles |
| GET | `/sar/incidents` | List incidents | All roles |
| POST | `/sar/incidents/{incidentId}/activate` | Activate an incident (PLANNING → ACTIVE) | IncidentCommander |
| POST | `/sar/incidents/{incidentId}/demobilize` | Begin demobilization (ACTIVE → DEMOBILIZING) | IncidentCommander |
| POST | `/sar/incidents/{incidentId}/close` | Close an incident (DEMOBILIZING → CLOSED) | IncidentCommander |
| POST | `/sar/incidents/{incidentId}/cancel` | Cancel an incident with three-level cascade | IncidentCommander |
| POST | `/sar/tasks` | Create a task under an incident | Coordinator, IncidentCommander |
| GET | `/sar/tasks/{taskId}` | Get one task | All roles |
| GET | `/sar/tasks` | List tasks | All roles |
| POST | `/sar/tasks/{taskId}/assign` | Assign a task (DRAFT → ASSIGNED) | IncidentCommander |
| POST | `/sar/tasks/{taskId}/start` | Start a task (ASSIGNED → IN_PROGRESS) | IncidentCommander, Coordinator |
| POST | `/sar/tasks/{taskId}/suspend` | Suspend a task (IN_PROGRESS → SUSPENDED) | IncidentCommander, Coordinator |
| POST | `/sar/tasks/{taskId}/resume` | Resume a task (SUSPENDED → IN_PROGRESS) | IncidentCommander, Coordinator |
| POST | `/sar/tasks/{taskId}/debrief` | Debrief a task (IN_PROGRESS → DEBRIEFED) | IncidentCommander, Coordinator |
| POST | `/sar/tasks/{taskId}/cancel` | Cancel a non-terminal task with cascade | IncidentCommander, Coordinator |
| POST | `/sar/teams` | Create a team | Coordinator |
| GET | `/sar/teams/{teamId}` | Get one team | All roles |
| GET | `/sar/teams` | List teams | All roles |
| POST | `/sar/teams/{teamId}/deactivate` | Deactivate a team (ACTIVE → INACTIVE) | Coordinator |
| POST | `/sar/members` | Create a member under a team | Coordinator |
| GET | `/sar/members/{memberId}` | Get one member | All roles |
| GET | `/sar/members` | List members | All roles |
| POST | `/sar/certifications` | Create a certification for a member | Coordinator |
| GET | `/sar/certifications/{certificationId}` | Get one certification (status recomputed vs clock) | All roles |
| GET | `/sar/certifications` | List certifications | All roles |
| POST | `/sar/callouts` | Create a callout (page a member to a task) | Coordinator, IncidentCommander |
| GET | `/sar/callouts/{calloutId}` | Get one callout | All roles |
| GET | `/sar/callouts` | List callouts | All roles |
| POST | `/sar/callouts/{calloutId}/acknowledge` | Acknowledge a callout (REQUESTED → ACKNOWLEDGED) | Member |
| POST | `/sar/callouts/{calloutId}/decline` | Decline a callout (REQUESTED/ACKNOWLEDGED → DECLINED) | Member |
| POST | `/sar/callouts/{calloutId}/standby` | Place a callout on standby (ACKNOWLEDGED → STANDBY) | Coordinator, IncidentCommander |
| POST | `/sar/callouts/{calloutId}/deploy` | Deploy a callout (STANDBY → DEPLOYED) | Coordinator, IncidentCommander |
| POST | `/sar/callouts/{calloutId}/demobilize` | Demobilize a callout (DEPLOYED → DEMOBILIZED) | Coordinator, IncidentCommander |
| POST | `/sar/resources` | Create a resource/asset | Coordinator |
| GET | `/sar/resources/{resourceId}` | Get one resource | All roles |
| GET | `/sar/resources` | List resources | All roles |
| POST | `/sar/resources/{resourceId}/set-status` | Toggle the OUT_OF_SERVICE flag | Coordinator |
| POST | `/sar/resource-assignments` | Assign a resource to a task for a window (OCC on resource version) | Coordinator, IncidentCommander |
| GET | `/sar/resource-assignments/{assignmentId}` | Get one resource assignment | All roles |
| GET | `/sar/resource-assignments` | List resource assignments | All roles |
| POST | `/sar/resource-assignments/{assignmentId}/activate` | Activate an assignment (RESERVED → ACTIVE) | Coordinator, IncidentCommander |
| POST | `/sar/resource-assignments/{assignmentId}/release` | Release an assignment (ACTIVE → RELEASED) | Coordinator, IncidentCommander |
| POST | `/sar/resource-assignments/{assignmentId}/cancel` | Cancel a reserved assignment (RESERVED → CANCELLED) | Coordinator, IncidentCommander |
| POST | `/sar/ground-tracks` | Log a ground track for a task | Coordinator, Member |
| GET | `/sar/ground-tracks/{groundTrackId}` | Get one ground track | All roles |
| GET | `/sar/ground-tracks` | List ground tracks | All roles |
| POST | `/sar/clues` | Log a clue for an incident | Coordinator, IncidentCommander, Member |
| GET | `/sar/clues/{clueId}` | Get one clue | All roles |
| GET | `/sar/clues` | List clues | All roles |
| POST | `/sar/clues/{clueId}/promote` | Promote a clue (LOGGED → ACTIONABLE) | IncidentCommander |
| POST | `/sar/clues/{clueId}/dismiss` | Dismiss a clue (LOGGED/ACTIONABLE → DISMISSED) | IncidentCommander |
| POST | `/sar/clues/{clueId}/resolve` | Resolve a clue (ACTIONABLE → RESOLVED) | IncidentCommander |
| POST | `/sar/reimbursement-claims` | Create a reimbursement claim | Coordinator, Member |
| GET | `/sar/reimbursement-claims/{claimId}` | Get one claim | All roles |
| GET | `/sar/reimbursement-claims` | List claims | All roles |
| POST | `/sar/reimbursement-claims/{claimId}/submit` | Submit a claim (DRAFT/RETURNED → SUBMITTED) | Member |
| POST | `/sar/reimbursement-claims/{claimId}/return` | Return a claim (SUBMITTED → RETURNED) | FinanceOfficer |
| POST | `/sar/reimbursement-claims/{claimId}/approve` | Approve a claim (SUBMITTED → APPROVED) | FinanceOfficer |
| POST | `/sar/reimbursement-claims/{claimId}/reject` | Reject a claim (SUBMITTED/APPROVED → REJECTED) | FinanceOfficer |
| POST | `/sar/reimbursement-claims/{claimId}/pay` | Pay a claim (APPROVED → PAID) | FinanceOfficer |
| POST | `/sar/after-action-reports` | Create an after-action report draft | Coordinator, IncidentCommander |
| GET | `/sar/after-action-reports/{aarId}` | Get one after-action report | All roles |
| GET | `/sar/after-action-reports` | List after-action reports | All roles |
| POST | `/sar/after-action-reports/{aarId}/finalize` | Finalize a report (DRAFT → FINALIZED) | IncidentCommander |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INCIDENT_NOT_ACTIVE` | 409 |
| `ERR_INCIDENT_NOT_DEMOBILIZING` | 409 |
| `ERR_INCIDENT_NOT_CLOSED` | 409 |
| `ERR_INCIDENT_HAS_ACTIVE_TASKS` | 409 |
| `ERR_TASK_NOT_READY` | 409 |
| `ERR_NO_DEPLOYED_RESPONDERS` | 409 |
| `ERR_TASK_AT_CAPACITY` | 409 |
| `ERR_TEAM_INACTIVE` | 409 |
| `ERR_CERT_REQUIREMENT_NOT_MET` | 409 |
| `ERR_MEMBER_DOUBLE_BOOKED` | 409 |
| `ERR_RESOURCE_UNAVAILABLE` | 409 |
| `ERR_RESOURCE_WINDOW_CONFLICT` | 409 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_STALE_VERSION` | 412 |
