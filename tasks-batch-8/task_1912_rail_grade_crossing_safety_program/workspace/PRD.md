# Rail Crossing Safety API — Product Requirements Document

## 1. Introduction

Every year, collisions at highway-rail grade crossings kill and injure more people than any other category of railroad accident, and a state Department of Transportation rail safety office carries the statutory duty of deciding where limited federal safety dollars do the most good. That duty is not a single decision but a braided set of workflows: the office maintains the federally mandated crossing inventory and computes each crossing's exposure to train-vehicle conflict; it convenes multi-agency diagnostic teams to review high-exposure crossings; it investigates incidents and reports qualifying ones to the Federal Railroad Administration; it runs an annual competitive funding program for warning-device upgrades; it negotiates crossing closures and consolidations with the localities that own the roads; it adjudicates quiet zone applications that trade train-horn relief against supplemental safety measures; it tracks who — railroad or road authority — is responsible for maintaining what at each crossing; and it verifies the timing design when a crossing's warning signals are interconnected with a nearby traffic signal for preemption.

This document specifies the Rail Crossing Safety API, the system of record through which the office, local authorities, and railroad maintenance organizations execute those workflows. The API enforces the program's hard rules — exposure thresholds that force diagnostic review, version-pinned priority scores that keep a competitive award round honest, segregation of duties so the officer who tables a closure offer cannot also accept it, and timing minimums that a preemption interconnection must satisfy before it is commissioned — while keeping every derived figure (exposure, hazard, risk indices, program balances) recomputed deterministically from the authoritative inputs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting doctrines that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role value the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles: `ProgramAdministrator`, `RailSafetyOfficer`, `LocalAuthority`, and `RailroadMaintainer`. Every endpoint admits a specific list of roles (§4); a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` differs by role, and the difference is load-bearing for ownership checks:

- When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the office's administrators act on the inventory, programs, assignments, interconnections, closure execution, and the logical clock without any resource-ownership comparison.
- When `X-User-Role` is `RailSafetyOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server does record it where a workflow writes the acting officer — for example, as `dot_accepted_by_user_id` on a closure agreement, as `created_by_user_id`, or as `last_offer_by_user_id` — and segregation-of-duties rules compare those recorded values against a later caller's `X-User-ID`, but it is never compared to any entity's `id`.
- When `X-User-Role` is `LocalAuthority`, `X-User-ID` is the `id` of the acting `Locality`; ownership checks on any resource that references a locality compare the resource's locality foreign-key field (for example `locality_id` on a quiet zone application or closure agreement, or `road_authority_locality_id` on a crossing) to `X-User-ID`.
- When `X-User-Role` is `RailroadMaintainer`, `X-User-ID` is an opaque operator identifier carrying the railroad's reporting mark; it is not tied to any persisted entity's `id`, but responsibility checks on maintenance work compare it to a crossing's `railroad_code` field, since flagging protection and railroad-responsible work are always performed by the operating railroad of record.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

Most list endpoints also accept filter query parameters scoped to their resource. Crossing lists accept `status`, `railroad_code`, `road_authority_locality_id`, and `diagnostic_review_due`. Diagnostic review lists accept `crossing_id`, `team_id`, and `status`. Incident report lists accept `crossing_id` and `status`. Upgrade project lists accept `crossing_id`, `program_id`, and `status`. Closure agreement lists accept `crossing_id`, `locality_id`, `consolidation_target_crossing_id`, and `status`. Quiet zone application lists accept `locality_id` and `status`; zone membership lists accept `quiet_zone_application_id` and `crossing_id`. Maintenance assignment lists accept `crossing_id`, `category`, and `status`; work order lists accept `crossing_id` and `status`; interconnection lists accept `crossing_id` and `status`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` refreshes on every mutation of the resource. `version` is a system-managed integer that starts at 1 when the resource is created and increments on mutation, providing the basis for optimistic concurrency control.

Two configuration-style resources are deliberate exceptions. A `Locality` and a `QuietZoneCrossing` membership row each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these two resources, and no endpoint exposes a version check against them.

### 2.5. The Logical Clock

All time-gated rules in the system — the trailing five-year incident window, the work-order begin-work window, the rejection of incidents dated in the future — read a single logical clock, never the wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. The clock moves only when a `ProgramAdministrator` invokes the test-driving clock capability with a `to_iso8601` instant; the response echoes the new `current_utc`. Deterministic timekeeping is what makes the five-year incident window and the work-window gates reproducible across test runs.

### 2.6. Version Semantics and Optimistic Concurrency Control

An entity's `version` increments exactly when the entity's own fields are written through its own endpoints — an inventory patch on a `Crossing`, a transition or action endpoint acting on the entity itself, or a closure agreement's execution writing the crossing's status. Derived-field recomputation cascading from *other* entities' actions refreshes the affected entity's `updated_at` but never increments its `version`. In particular, a `FundingProgram`'s recomputed `eligible_demand_cents` does not bump the program's `version`, and a `Crossing`'s recomputed exposure, hazard score, or incident count does not bump the crossing's `version`. A `FundingProgram`'s `version` therefore moves only on allocation lock, award, and rescind; a `Crossing`'s `version` moves only on an inventory patch and on closure execution.

Two write endpoints enforce optimistic concurrency control against this discipline:

- Updating a crossing's inventory requires the request to carry `expected_crossing_version`, a non-optional field holding the `version` the client last observed on that crossing. If another writer has advanced the crossing's `version` since — through an inventory patch, a closure execution, or any direct write — the values no longer match and the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting inventory it has not observed.
- Issuing an upgrade award requires the request to carry `expected_funding_program_version`, a non-optional field holding the `version` the client last observed on the funding program. Because a prior award or rescind legitimately changes the program's `available_cents`, a mismatch with the program's current `version` means the client's view of the pool is stale, and the award is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field.

### 2.7. Precision, Units, and Rounding

Monetary amounts are integers of whole cents throughout the API — apportionments, cost estimates, awards, incentive offers, and property damage alike. Exposure and risk figures (`exposure_index`, `projected_exposure_index`, `hazard_score`, `riwh_pre_ssm`, `riwh_post_ssm`) are decimal numbers carried to exactly 2 decimal places using round-half-up. Signal-timing quantities are integer seconds, with division results rounded up to the next whole second where the governing calculation says so. Proportional funding shares are the one place a downward rounding is used: each pro-rata share is the floor of the exact quotient, never rounded up.

### 2.8. Existence Validation and Lookup Order

For any request that references resources — by path identifier or by a foreign key in the request body — the server validates existence in a fixed left-to-right order: path identifiers first, in the order they appear in the URL, then body foreign keys. The first reference that does not resolve to an existing resource produces the response, and each resource family has its own code: `ERR_CROSSING_NOT_FOUND`, `ERR_LOCALITY_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_QZ_APPLICATION_NOT_FOUND`, `ERR_QZ_MEMBER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and `ERR_INTERCONNECTION_NOT_FOUND` (all HTTP 404). A request naming both a nonexistent crossing and a nonexistent team, for example, surfaces whichever reference is validated first — never a business-rule error — because existence outranks every later check.

### 2.9. Validation Precedence

When several rules could reject the same request, the server applies checks in a fixed priority order and reports the first failure only:

1. **Authentication** — missing or malformed `X-User-ID` / `X-User-Role` headers yield `ERR_UNAUTHENTICATED`.
2. **Role authorization** — a role outside the endpoint's admitted list yields `ERR_FORBIDDEN_ROLE`. (Ownership-style mismatches that are themselves business rules — `ERR_LOCALITY_MISMATCH`, `ERR_RESPONSIBILITY_MISMATCH`, `ERR_COUNTER_TURN`, `ERR_SELF_ACCEPT_FORBIDDEN` — are *not* decided here; they are evaluated at step 6.)
3. **Existence** — path identifiers and body foreign keys, validated left-to-right per §2.8.
4. **State eligibility** — the target entity must be in a from-state the requested transition or action allows, else `ERR_INVALID_STATE_TRANSITION`; cross-entity state gates live here too, such as `ERR_CROSSING_NOT_ACTIVE` when a child creation, nomination, review acceptance, or commissioning targets a crossing that is not `ACTIVE`, and `ERR_PROJECT_NOT_SELECTED` when an award targets a project that is neither `ELIGIBLE` nor `SELECTED`.
5. **Optimistic concurrency** — the `expected_*_version` fields of §2.6 are compared here, after state is confirmed; a mismatch yields `ERR_STALE_VERSION`.
6. **Business safety** — flagging-plan requirements (`ERR_FLAGGING_PLAN_REQUIRED`), quiet-zone reinstatement sufficiency (`ERR_SSM_INSUFFICIENT`), and the preemption timing check (`ERR_PREEMPTION_TIMING_INADEQUATE`).
7. **Business constraints** — uniqueness (`ERR_DUPLICATE_DOT_NUMBER`, `ERR_DUPLICATE_FISCAL_YEAR`), self-consolidation (`ERR_SELF_CONSOLIDATION`), one-open-project and one-open-interconnection rules (`ERR_ACTIVE_PROJECT_EXISTS`, `ERR_ACTIVE_INTERCONNECTION_EXISTS`), zone membership conflicts (`ERR_ZONE_MEMBERSHIP_CONFLICT`), the casualty-severity investigation rule (`ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION`), the negotiation round cap (`ERR_NEGOTIATION_ROUND_LIMIT`), empty-zone submission (`ERR_EMPTY_ZONE`), missing revocation fallback (`ERR_NO_FALLBACK_ASSIGNMENT`), the FRA-reportability gate (`ERR_FRA_NOT_REPORTABLE`), the gates-required commissioning rule (`ERR_PREEMPTION_REQUIRES_GATES`), the party rules (`ERR_COUNTER_TURN`, `ERR_SELF_ACCEPT_FORBIDDEN`, `ERR_LOCALITY_MISMATCH`, `ERR_RESPONSIBILITY_MISMATCH`), award amount bounds (`ERR_AWARD_AMOUNT_INVALID`), closing a program with open projects (`ERR_PROGRAM_HAS_OPEN_PROJECTS`), and general request-shape failures (`ERR_INVALID_REQUEST`: missing required fields, type mismatches, unknown fields, invalid enum values, negative counts, and the like).
8. **Referential business rules** — a work order without an active responsibility assignment (`ERR_RESPONSIBILITY_GAP`) and quiet-zone submission without accepted diagnostic reviews (`ERR_DIAGNOSTIC_REVIEW_REQUIRED`).
9. **Temporal rules** — work-window overlap (`ERR_WORK_WINDOW_OVERLAP`), the diagnostic team scheduling buffer (`ERR_TEAM_SCHEDULE_BUFFER`), beginning work outside the window (`ERR_OUTSIDE_WORK_WINDOW`), and future-dated incidents (`ERR_INCIDENT_IN_FUTURE`).
10. **Fiscal rules** — `ERR_INSUFFICIENT_FUNDS` on awards, and the incentive cap (`ERR_INCENTIVE_CAP_EXCEEDED`) and counter-direction (`ERR_INCENTIVE_REGRESSION`) rules on closure counters.

The ordering is observable. Because safety (step 6) outranks temporal rules (step 9), a work order that both lacks a required flagging plan and overlaps another window is rejected with `ERR_FLAGGING_PLAN_REQUIRED`, not `ERR_WORK_WINDOW_OVERLAP`. Because existence (step 3) outranks state (step 4), a transition against a nonexistent review yields `ERR_REVIEW_NOT_FOUND` even if the supplied `to_status` would also be invalid.

## 3. Business Logic & Workflows

### 3.1. Crossing Inventory and Risk Evaluation

The **Crossing** is the system's anchor entity; every other workflow ultimately references one. Before any crossing can reference a jurisdiction, a `ProgramAdministrator` registers each **Locality** with its `locality_name` (the city or county), its two-letter `state_code`, and a public-works `contact_email`; the locality's server-minted `id` is thereafter what crossings, agreements, quiet zone applications, and `LocalAuthority` callers use to name it. A `ProgramAdministrator` registers a crossing by supplying its federally assigned `dot_crossing_number` (unique across all crossings — a duplicate is rejected with `ERR_DUPLICATE_DOT_NUMBER`), the operating railroad's reporting mark `railroad_code`, the `road_authority_locality_id` of the jurisdiction that owns the roadway, the `highway_functional_class` (one of `ARTERIAL`, `COLLECTOR`, or `LOCAL`), the `annual_train_count` and `aadt` exposure inputs, the `train_speed_max_mph` timetable maximum (between 1 and 110), the `sight_distance_rating` (1 for the worst approach visibility through 5 for the best), the installed `warning_device_class` (`PASSIVE_CROSSBUCK`, `FLASHING_LIGHTS`, `GATES`, or `FOUR_QUADRANT_GATES`), and optionally a daily `school_bus_count` that defaults to 0 when omitted. Traffic counts and bus counts must be non-negative; negative values are rejected with `ERR_INVALID_REQUEST`. A new crossing starts in `ACTIVE` status with `version` 1, and its derived risk profile is computed immediately.

Two exposure figures are maintained on every crossing. The snapshot `exposure_index` is the crossing's average trains per day — its `annual_train_count` divided by 365 — multiplied by its `aadt` and divided by 1,000, with the result rounded half-up to 2 decimal places. The `projected_exposure_index` is a five-year planning variant of the same formula: the annual train count is first grown by compounding at two percent per year for five years, the AADT is grown by compounding at three percent per year for five years, and the snapshot formula is then applied to those grown figures; because both growth rates are positive, the projected figure is always strictly greater than the snapshot. The snapshot drives threshold gating and hazard scoring; the projected figure is reported on the crossing record for planning.

The crossing's `hazard_score` condenses its risk into a number from 0 to 100, recomputed at creation, on every inventory patch, whenever incident findings are issued, and whenever an upgrade project completes and changes the warning devices. The score combines five factors: a device factor of 1.50 for `PASSIVE_CROSSBUCK`, 1.20 for `FLASHING_LIGHTS`, 1.00 for `GATES`, and 0.90 for `FOUR_QUADRANT_GATES`; an exposure band multiplier applied to the snapshot `exposure_index` — 1.40 (`SEVERE`) when exposure is at least 25, 1.20 (`HIGH`) when at least 10, 1.10 (`MEDIUM`) when at least 3, and 1.00 (`LOW`) below 3; an incident term equal to the crossing's five-year incident count capped at 5 and then multiplied by 8; a bus term equal to the `school_bus_count` capped at 20 and then multiplied by 0.5; and a sight multiplier of 1.15 when the `sight_distance_rating` is 2 or worse, otherwise 1.00. The raw score is the sum of exposure times its band multiplier, the incident term, and the bus term, all multiplied by the device factor and the sight multiplier; the final `hazard_score` is that raw score capped at 100 and rounded half-up to 2 decimal places.

The incident term draws on `incident_count_5yr`, a live derived count of the crossing's investigated incidents: incident reports of this crossing whose status is `FINDINGS_ISSUED`, `FRA_SUBMITTED`, or `CLOSED` and whose `occurred_at` falls within the trailing five-year window — from five years before the logical clock through the logical clock, both bounds inclusive. Reports still in `REPORTED`, `SCREENED`, `FIELD_INVESTIGATION`, or `DESK_REVIEW`, and reports that were `REJECTED`, never count.

A crossing's `diagnostic_review_due` flag is `true` when its snapshot `exposure_index` reaches 10.00 or higher, and it also becomes `true` the moment any incident at the crossing is assigned to a field investigation (§3.3); it remains the office's signal that the crossing needs a diagnostic team on the ground.

A `ProgramAdministrator` keeps the inventory current by patching a crossing's counts — any of `annual_train_count`, `aadt`, `school_bus_count`, `sight_distance_rating`, `warning_device_class`, and `train_speed_max_mph` may be revised — subject to the optimistic-concurrency rule of §2.6: the request must carry `expected_crossing_version`, and a stale value is rejected with `ERR_STALE_VERSION`. A successful patch increments the crossing's `version` by exactly 1 and recomputes `exposure_index`, `projected_exposure_index`, `hazard_score`, and `diagnostic_review_due` from the new inputs.

### 3.2. Diagnostic Teams and Field Reviews

Diagnostic reviews are how the office brings railroad, roadway, and regulatory eyes to a crossing. A `ProgramAdministrator` first registers each **DiagnosticTeam** with a `team_name` and its `lead_agency` (the convening body — DOT, railroad, FRA, or locality). Reviews themselves are scheduled by a `ProgramAdministrator` through a payload containing the `crossing_id` under review, the `team_id` assigned, and the `scheduled_date` of the field visit as an ISO calendar date. Two guards apply at scheduling time: the crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`), and the team must not already have a non-`CANCELLED` review whose `scheduled_date` is less than 2 days from the requested date — the office requires at least a two-day buffer between a team's engagements, and a tighter spacing is rejected with `ERR_TEAM_SCHEDULE_BUFFER`.

A review begins life `SCHEDULED`. When the team convenes, a `RailSafetyOfficer` moves it `SCHEDULED` → `IN_SESSION`; any other from-state is rejected with `ERR_INVALID_STATE_TRANSITION`. Findings are then formalized by issuing recommendations: the officer supplies a non-empty `recommendations` list drawn from `UPGRADE_DEVICES`, `CLOSE_CROSSING`, `CONSOLIDATE`, `INSTALL_PREEMPTION`, and `NO_ACTION`, moving the review `IN_SESSION` → `RECOMMENDATIONS_ISSUED` with the list stored on the record; an empty list is rejected with `ERR_INVALID_REQUEST`. The office accepts a review's recommendations by moving it `RECOMMENDATIONS_ISSUED` → `ACCEPTED`, which requires the crossing to still be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`); acceptance stamps `accepted_at` and, because only one review may speak for a crossing at a time, the crossing's previously `ACCEPTED` review — if any — is automatically moved `ACCEPTED` → `SUPERSEDED` with its `superseded_by_review_id` set to the newly accepted review's `id`. A review may instead be cancelled from either `SCHEDULED` or `IN_SESSION`, ending `CANCELLED`; `SUPERSEDED` and `CANCELLED` are terminal.

### 3.3. Incident Reporting, Investigation, and FRA Submission

Anyone close to the event may file the initial report: incident creation is open to all four roles. The report names the `crossing_id`, the `occurred_at` timestamp, and the `severity` — `CASUALTY`, `INJURY`, `PROPERTY_DAMAGE`, or `NEAR_MISS` — with optional `fatalities`, `injuries`, and `property_damage_cents` counts (each defaulting to 0 and each non-negative), an optional `train_speed_at_impact_mph`, and an optional free-text `narrative`. A report whose `occurred_at` is after the logical clock is rejected with `ERR_INCIDENT_IN_FUTURE`. At creation the server derives `fra_reportable`: the report is FRA-reportable when it records any fatality, any injury, or property damage of at least 1,100,000 cents — the damage threshold is inclusive, so damage of exactly 1,100,000 cents qualifies. A new report enters `REPORTED`.

Screening forks the workflow. A `RailSafetyOfficer` moves a `REPORTED` report to `SCREENED` to open it, or straight to `REJECTED` when the report does not warrant investigation; both moves require the `REPORTED` from-state, else `ERR_INVALID_STATE_TRANSITION`. From `SCREENED` the officer assigns the investigation track: moving to `FIELD_INVESTIGATION` records `investigation_track` as `FIELD_INVESTIGATION` and, as a branch side effect, flips the crossing's `diagnostic_review_due` to `true`; moving to `DESK_REVIEW` records the `DESK_REVIEW` track with no such side effect. A `CASUALTY` incident may never be desk-reviewed — attempting the `SCREENED` → `DESK_REVIEW` move on one is rejected with `ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION`.

Issuing findings is the pivotal act. From either `FIELD_INVESTIGATION` or `DESK_REVIEW`, the officer supplies the `findings_summary` text and the `warning_devices_functioning` flag, moving the report to `FINDINGS_ISSUED`. That single move fires a three-link cascade. Link 1: the crossing's `incident_count_5yr` is recomputed over the trailing five-year window and its `hazard_score` is recomputed with the new incident term (neither recompute increments the crossing's `version`, per §2.6). Link 2: because the crossing's live `hazard_score` has changed, every upgrade project of this crossing currently in `ELIGIBLE` reverts `ELIGIBLE` → `PROPOSED` with its `score_stale` flag set to `true` — its pinned `priority_score` no longer matches the live hazard. Link 3: because those projects left `ELIGIBLE`, each affected funding program's `eligible_demand_cents` is recomputed, decreasing by each reverted project's `estimated_cost_cents`.

Closure of the file depends on reportability. A report in `FINDINGS_ISSUED` with `fra_reportable` equal to `true` must be submitted to the FRA first: the officer moves it to `FRA_SUBMITTED`, which stamps `fra_submitted_at`, and only then to `CLOSED`. Attempting the FRA-submission move on a non-reportable incident is rejected with `ERR_FRA_NOT_REPORTABLE`. Conversely, a non-reportable report moves directly from `FINDINGS_ISSUED` to `CLOSED`; attempting to close a reportable one without the FRA submission is rejected with `ERR_INVALID_STATE_TRANSITION`. `CLOSED` and `REJECTED` are terminal.

### 3.4. Funding Programs and Upgrade Awards

Each fiscal year the office opens a competitive funding program. A `ProgramAdministrator` creates one with its `fiscal_year` (unique across programs — a repeat is rejected with `ERR_DUPLICATE_FISCAL_YEAR`), the total `apportionment_cents` (greater than zero), and the `allocation_method`, which selects how the lock-day sweep distributes funds: `WATERFALL_BY_RANK` or `PROPORTIONAL_SHARE`. A new program is `OPEN`, its `available_cents` starts equal to the full `apportionment_cents`, and `encumbered_cents` and `eligible_demand_cents` start at zero. Thereafter the invariant `available_cents` plus `encumbered_cents` equals `apportionment_cents` holds at all times: `encumbered_cents` is the sum of `awarded_cents` over the program's projects in `AWARDED`, `IN_PROGRESS`, or `COMPLETED`, and `available_cents` is what remains. Separately, `eligible_demand_cents` tracks the sum of `estimated_cost_cents` over the program's projects currently in `ELIGIBLE`, recomputed on every project status change.

An **UpgradeProject** is proposed against a crossing and a program by a `ProgramAdministrator` or `RailSafetyOfficer`, supplying `crossing_id`, `program_id`, the `target_device_class` (same four-value device enum as the crossing), and the engineer's `estimated_cost_cents` (greater than zero). The crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`), the target class must differ from the crossing's current `warning_device_class` (else `ERR_INVALID_REQUEST`), and a crossing may carry at most one non-terminal project at a time — if one already exists in `PROPOSED`, `ELIGIBLE`, `SELECTED`, `AWARDED`, or `IN_PROGRESS`, the proposal is rejected with `ERR_ACTIVE_PROJECT_EXISTS`. A new project is `PROPOSED`, with `priority_score` still `null`.

Nomination moves a project `PROPOSED` → `ELIGIBLE` and is performed by a `RailSafetyOfficer`; it requires the crossing `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`) and the program still `OPEN` (else `ERR_INVALID_STATE_TRANSITION`). Nomination is the system's version-pinning moment: the project's `priority_score` is set to the crossing's `hazard_score` at that instant and `score_stale` is set to `false`, and the program's `eligible_demand_cents` recomputes. Thereafter `score_stale` is `true` whenever the crossing's live `hazard_score` no longer equals the pinned `priority_score` — and as §3.3 describes, any hazard recompute that changes the value automatically reverts the crossing's `ELIGIBLE` projects to `PROPOSED` with `score_stale` set, recomputing demand.

Lock day is when the sweep runs. A `ProgramAdministrator` moves the program `OPEN` → `ALLOCATION_LOCKED`; the candidate set is the program's projects in `ELIGIBLE` at that instant, ranked by `priority_score` descending, ties broken by the crossing's `incident_count_5yr` descending, and remaining ties by the project's `created_at` ascending. Under `WATERFALL_BY_RANK` the sweep walks the ranking with a running remainder initialized to `available_cents`: each project whose `estimated_cost_cents` fits within the remainder is moved to `SELECTED` with `tentative_award_cents` set to its full `estimated_cost_cents` and the remainder reduced accordingly — a project whose cost exactly equals the remainder is funded, leaving zero — and the first project that does not fit stops the sweep immediately, with no skipping ahead to smaller projects. Under `PROPORTIONAL_SHARE` every candidate becomes `SELECTED`: each project's `tentative_award_cents` is the smaller of its `estimated_cost_cents` and the floor of `available_cents` multiplied by its `estimated_cost_cents` and divided by the total requested across all candidates, and any unallocated remainder cents stay in `available_cents`. Projects not funded remain `ELIGIBLE` with `tentative_award_cents` null. Locking with zero `ELIGIBLE` projects is permitted and simply selects nothing; either way the lock increments the program's `version`.

Awards are issued by a `ProgramAdministrator` and are subject to the optimistic-concurrency rule of §2.6: the request carries `expected_funding_program_version` and is rejected with `ERR_STALE_VERSION` when the program has moved on. The project must be `ELIGIBLE` or `SELECTED` (else `ERR_PROJECT_NOT_SELECTED`) — a `SELECTED` project is awarded after a lock, while an `ELIGIBLE` project may receive a rolling award straight from an `OPEN` program — and the program must be `OPEN` or `ALLOCATION_LOCKED` (else `ERR_INVALID_STATE_TRANSITION`). The effective award is the request's optional `award_cents`, defaulting to the project's `tentative_award_cents` when `SELECTED` and to its `estimated_cost_cents` otherwise; it must lie between 1 and the `estimated_cost_cents` inclusive (else `ERR_AWARD_AMOUNT_INVALID`) and must not exceed the program's `available_cents` (else `ERR_INSUFFICIENT_FUNDS`, HTTP 402). A successful award sets `awarded_cents` to the effective amount, splits it into the 80/20 federal/state match — `federal_share_cents` is the awarded amount multiplied by 0.80 and rounded half-up to whole cents, computed per award line first, and `state_share_cents` is the awarded amount minus the federal share; program-level totals are always the sum of these per-line rounded values and are never re-rounded in aggregate — adds `awarded_cents` to `encumbered_cents`, subtracts it from `available_cents`, moves the project to `AWARDED`, and increments the program's `version`.

Rescission is the compensating mirror. A `ProgramAdministrator` rescinding an `AWARDED` project (the program still `OPEN` or `ALLOCATION_LOCKED`, else `ERR_INVALID_STATE_TRANSITION`) moves it back `AWARDED` → `ELIGIBLE`: the program's `available_cents` is increased and its `encumbered_cents` decreased by exactly the rescinded `awarded_cents`, restoring the pool exactly; the project's `awarded_cents`, `federal_share_cents`, and `state_share_cents` return to `null`; and the program's `version` increments.

From `AWARDED` a project moves to `IN_PROGRESS` under a `ProgramAdministrator`, and from `IN_PROGRESS` to `COMPLETED` — completion requires the crossing still `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`) and writes the crossing's `warning_device_class` to the project's `target_device_class`, which changes the device factor and forces a `hazard_score` recompute. That recompute runs the same staleness cascade as incident findings: the crossing's other `ELIGIBLE` projects revert to `PROPOSED` with `score_stale` set, and affected programs recompute `eligible_demand_cents`. A project may also be withdrawn from `PROPOSED`, `ELIGIBLE`, or `SELECTED` by a `RailSafetyOfficer`; leaving `ELIGIBLE` recomputes the program's demand, and leaving `SELECTED` nulls `tentative_award_cents`. `COMPLETED` and `WITHDRAWN` are terminal.

Finally, a `ProgramAdministrator` may close an `ALLOCATION_LOCKED` program, but only when none of its projects remain in `SELECTED`, `AWARDED`, or `IN_PROGRESS` — open commitments block the close with `ERR_PROGRAM_HAS_OPEN_PROJECTS`. `CLOSED` is terminal.

### 3.5. Closure and Consolidation Negotiation

When a crossing should close — or consolidate into a better neighbor — the DOT and the locality negotiate through a **ClosureAgreement**. Either side may open one: a `RailSafetyOfficer` creates it for the DOT, a `LocalAuthority` caller for the locality, and the server records which side created it in `created_by_party` (`DOT` or `LOCALITY`) along with the caller's identity in `created_by_user_id`. Creation takes the `crossing_id` proposed for closure, the `locality_id` of the negotiating jurisdiction, and the `closure_type` — `CLOSURE` or `CONSOLIDATION`. For a consolidation the payload must also carry `consolidation_target_crossing_id`, the receiving crossing; it must differ from the crossing being closed (a self-reference is rejected with `ERR_SELF_CONSOLIDATION`), it must be `ACTIVE`, and it must be absent entirely for a plain `CLOSURE` — a missing or extraneous target for the declared type is `ERR_INVALID_REQUEST`. The crossing under closure must likewise be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`).

The DOT's minimum incentive is computed at creation and fixed for the life of the agreement: `computed_incentive_cents` is a base of 250,000 cents for a `CLOSURE` or 175,000 cents for a `CONSOLIDATION`, plus 5,000 cents for each point of the crossing's snapshot `exposure_index` with the exposure contribution capped at 50 points, all in whole cents. The negotiable `current_offer_cents` starts equal to that computed minimum, and the `negotiation_round` starts at 0 while the agreement sits in `DRAFT`.

Tabling the opening offer moves the agreement `DRAFT` → `PROPOSED`: the round advances to 1, `current_offer_cents` is set to `computed_incentive_cents`, and `last_offer_by_party` / `last_offer_by_user_id` record the side and user that tabled it. Only the side that created the agreement may propose it — a DOT-created agreement is proposed by a `RailSafetyOfficer`, a locality-created one by the owning `LocalAuthority` — and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`.

Counter-offers drive a `PROPOSED` ↔ `COUNTERED` cycle. A counter names `proposed_incentive_cents` and obeys four rules: the agreement must be in `PROPOSED` or `COUNTERED` (else `ERR_INVALID_STATE_TRANSITION`); turns strictly alternate, so the party that tabled the current offer may not counter their own offer (else `ERR_COUNTER_TURN`), and a locality counter must come from the owning locality (else `ERR_LOCALITY_MISMATCH`); the `negotiation_round` must still be below the cap of 6 rounds (else `ERR_NEGOTIATION_ROUND_LIMIT`); and direction is enforced — a locality counter must *raise* the offer, landing strictly above `current_offer_cents` and at or below the hard cap of 1,000,000 cents (a counter that fails to raise is `ERR_INCENTIVE_REGRESSION`, one above the cap is `ERR_INCENTIVE_CAP_EXCEEDED`), while a DOT counter must *lower* the offer, landing strictly below `current_offer_cents` but never below `computed_incentive_cents` (either failure is `ERR_INCENTIVE_REGRESSION`). A valid counter sets `current_offer_cents` to the proposed amount, increments `negotiation_round` by 1, updates `last_offer_by_party` and `last_offer_by_user_id`, and flips the state — `PROPOSED` to `COUNTERED` or `COUNTERED` back to `PROPOSED`.

Acceptance is segregated. Moving `PROPOSED` or `COUNTERED` to `DOT_ACCEPTED` is a `RailSafetyOfficer` action, but when the current offer was tabled by the DOT, the accepting officer must not be the same user who tabled it — the officer whose `X-User-ID` equals `last_offer_by_user_id` is rejected with `ERR_SELF_ACCEPT_FORBIDDEN`. Acceptance records `dot_accepted_by_user_id`. The locality then ratifies: a `LocalAuthority` caller whose `X-User-ID` equals the agreement's `locality_id` (else `ERR_LOCALITY_MISMATCH`) moves `DOT_ACCEPTED` → `LOCALITY_RATIFIED`. Execution is the final, administrative act: a `ProgramAdministrator` moves `LOCALITY_RATIFIED` → `EXECUTED`, which flips the crossing `ACTIVE` → `CLOSURE_PENDING` and increments the crossing's `version`.

The locality may walk away at any point before execution — from `PROPOSED`, `COUNTERED`, or `DOT_ACCEPTED` the owning locality may reject the agreement into terminal `REJECTED`. The creating side may likewise withdraw its own offer from `DRAFT`, `PROPOSED`, `COUNTERED`, or `DOT_ACCEPTED` into terminal `WITHDRAWN` — a DOT-created agreement is withdrawn by a `RailSafetyOfficer`, a locality-created one by the owning `LocalAuthority`.

Execution does not itself close the crossing; the physical confirmation does. A `ProgramAdministrator` confirming closure on a `CLOSURE_PENDING` crossing (any other state: `ERR_INVALID_STATE_TRANSITION`) moves it to terminal `CLOSED` and fires the closure cascade. Every zone membership row for the crossing flips from `MEMBER` to `REMOVED`. Each affected quiet zone application then recomputes its `riwh_post_ssm` over its remaining `MEMBER` rows using their live hazard scores, and if the application is `EFFECTIVE` and either no `MEMBER` rows remain or the recomputed value exceeds the national risk threshold, it moves `EFFECTIVE` → `SUSPENDED` automatically. In parallel, the crossing's non-terminal work orders — those in `PLANNED` or `FLAGGING_CONFIRMED` — are cancelled, and its preemption interconnections in `DRAFT`, `TIMING_VERIFIED`, or `COMMISSIONED` are decommissioned.

### 3.6. Quiet Zones and Supplemental Safety Measures

A quiet zone trades the routine sounding of train horns for engineering measures that keep risk at or below the national threshold. A **QuietZoneApplication** is opened by a `LocalAuthority` caller, and the `locality_id` in the payload must equal the caller's `X-User-ID` — a locality may only ever apply for itself, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`. Optional `notes` may accompany the application. The new application is a `DRAFT` with both risk indices, `riwh_pre_ssm` and `riwh_post_ssm`, still unset.

Membership is managed through junction rows. While the zone is `DRAFT` or `SUPPLEMENT_REQUIRED` — the two editable states; adding to a zone in any other state is `ERR_INVALID_STATE_TRANSITION` — the owning locality adds a member crossing with a payload containing the `crossing_id` and an optional `ssm_codes` list of supplemental safety measures drawn from `FOUR_QUADRANT_GATES`, `MEDIANS`, `CHANNELIZATION`, `ONE_WAY_STREET`, and `WAYSIDE_HORN` (defaulting to an empty list). The crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`) and must not already be a `MEMBER` of another zone whose status is neither `REJECTED` nor `WITHDRAWN` (else `ERR_ZONE_MEMBERSHIP_CONFLICT`). Each row records its `quiet_zone_application_id` from the path and starts with `membership_status` `MEMBER`. The owning locality may remove a member while the zone remains editable — a removal attempted under another locality's identity is rejected with `ERR_LOCALITY_MISMATCH` — which sets the row's `membership_status` to `REMOVED`; removals otherwise occur only through the closure cascade. Removal deliberately does **not** recompute the parent application's risk indices: they stay pinned at the values from the last submission until the zone is next submitted.

Submission is the risk-pinning moment. From `DRAFT` — or from `SUPPLEMENT_REQUIRED` when the locality has strengthened its measures — the owning locality submits, and the server runs the full submission gauntlet: the caller must own the zone (else `ERR_LOCALITY_MISMATCH`); at least one membership row must be `MEMBER` (else `ERR_EMPTY_ZONE`); every member crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`); and every member crossing must have at least one diagnostic review in `ACCEPTED` status (else `ERR_DIAGNOSTIC_REVIEW_REQUIRED`). On success the server computes and pins both risk indices. `riwh_pre_ssm` is the mean of the member crossings' live `hazard_score` values, rounded half-up to 2 decimal places. If that pre-SSM index is already at or below the Nationwide Significant Risk Threshold of 40.00, the SSM credits are irrelevant to the outcome — the pre-check is evaluated first. Otherwise each member crossing earns a credit equal to the sum of the effectiveness values of its `ssm_codes` — 0.82 for `FOUR_QUADRANT_GATES`, 0.40 for `MEDIANS`, 0.33 for `CHANNELIZATION`, 0.25 for `ONE_WAY_STREET`, and 0.15 for `WAYSIDE_HORN` — capped at 0.75 per crossing, and `riwh_post_ssm` is the mean over member crossings of each hazard score multiplied by one minus its capped credit, rounded half-up to 2 decimal places. The zone moves to `SUBMITTED` with both values pinned; re-submission from `SUPPLEMENT_REQUIRED` recomputes and re-pins both.

Review and decision belong to the office. A `RailSafetyOfficer` moves `SUBMITTED` → `UNDER_REVIEW`, and then decides — the decision is server-computed from the pinned values in a fixed evaluation order, never chosen by the officer. The outcome is `APPROVED` when `riwh_pre_ssm` is at or below 40.00, or when `riwh_post_ssm` is at or below 40.00. Failing that, the outcome is `SUPPLEMENT_REQUIRED` when `riwh_post_ssm` remains above 40.00 but is strictly below `riwh_pre_ssm` — the proposed measures help, just not enough. Otherwise — `riwh_post_ssm` at or above `riwh_pre_ssm`, meaning the proposed measures make no progress — the outcome is `REJECTED`, which is terminal.

An approved zone is activated by its owning locality, moving `APPROVED` → `EFFECTIVE` (ownership mismatch: `ERR_LOCALITY_MISMATCH`). An `EFFECTIVE` zone may be suspended by a `RailSafetyOfficer`, and it is also suspended automatically by the closure cascade of §3.5 when a member crossing closes and the recomputed post-SSM index exceeds the threshold or no members remain. Reinstatement returns a `SUSPENDED` zone to `EFFECTIVE` at a `RailSafetyOfficer`'s hand, but only after the server recomputes the post-SSM index live over the current `MEMBER` rows: reinstatement requires at least one remaining member and a recomputed `riwh_post_ssm` at or below 40.00, and failure is rejected with `ERR_SSM_INSUFFICIENT`; on success both risk indices are re-pinned to the recomputed values. Before review, the owning locality may also withdraw — from `DRAFT` or `SUBMITTED` into terminal `WITHDRAWN`.

### 3.7. Maintenance Responsibility and Work Coordination

Responsibility at a crossing is divided by category. A `ProgramAdministrator` records a **MaintenanceResponsibilityAssignment** naming the `crossing_id`, the work `category` (`SIGNAL`, `SURFACE`, `VEGETATION`, or `STRIPING`), the `responsible_party` (`RAILROAD` or `ROAD_AUTHORITY`), and the `effective_from` date. The crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`). Exactly one assignment per crossing-and-category pair is `ACTIVE` at all times: creating a new assignment for a pair automatically moves the pair's previous `ACTIVE` row to `SUPERSEDED`. Revocation is the compensating action with a fallback — a `ProgramAdministrator` revoking the `ACTIVE` row requires at least one `SUPERSEDED` row to exist for the same pair (else `ERR_NO_FALLBACK_ASSIGNMENT`); the superseded row with the most recent `updated_at` (ties broken by the most recent `created_at`) is reinstated to `ACTIVE`, so the pair again has exactly one active row and the revoked row ends `REVOKED`. `SUPERSEDED` and `REVOKED` are terminal.

Work itself is planned as a **MaintenanceWorkOrder** by the party responsible for the category: creation is open to `RailroadMaintainer` and `LocalAuthority` callers, and the server copies `responsible_party` onto the order from the pair's `ACTIVE` assignment — when no such assignment exists, creation is rejected with `ERR_RESPONSIBILITY_GAP`. The creator must match that responsible party: a `RAILROAD`-responsible order is created by a `RailroadMaintainer` whose `X-User-ID` equals the crossing's `railroad_code`, and a `ROAD_AUTHORITY`-responsible order by a `LocalAuthority` whose `X-User-ID` equals the crossing's `road_authority_locality_id`; a mismatch is `ERR_RESPONSIBILITY_MISMATCH`. The order specifies `window_start` (inclusive) and `window_end` (exclusive) as ISO 8601 UTC instants, with `window_end` required to be after `window_start` (else `ERR_INVALID_REQUEST`), and windows on the same crossing must not overlap under half-open semantics — two orders that merely touch, one ending exactly when the other begins, are allowed, while a true overlap with a non-terminal order on the crossing is rejected with `ERR_WORK_WINDOW_OVERLAP`. Work that fouls the track is flagged at creation: `fouls_track` set to `true` requires a `flagging_vendor` reference naming the railroad flagging provider, and its absence is rejected with `ERR_FLAGGING_PLAN_REQUIRED`. A new order is `PLANNED`.

Railroad flagging is confirmed before fouling work begins: a `RailroadMaintainer` whose `X-User-ID` equals the crossing's `railroad_code` — flagging is always provided by the operating railroad — moves the order `PLANNED` → `FLAGGING_CONFIRMED`; anyone else is rejected with `ERR_RESPONSIBILITY_MISMATCH`. Beginning work is the most heavily gated move in the workflow, and all four gates must pass: the order must be in `PLANNED` or `FLAGGING_CONFIRMED` (else `ERR_INVALID_STATE_TRANSITION`); when `fouls_track` is true the order must have reached `FLAGGING_CONFIRMED` first (else `ERR_FLAGGING_NOT_CONFIRMED`); the logical clock must fall within the half-open window — at or after `window_start` and before `window_end` (else `ERR_OUTSIDE_WORK_WINDOW`); the crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`); and the caller must match the order's `responsible_party`, railroad code for railroad work or owning locality for road-authority work (else `ERR_RESPONSIBILITY_MISMATCH`). Success moves the order to `IN_WORK`, and completion — again by the matching party — moves `IN_WORK` → `COMPLETED`. An order still in `PLANNED` or `FLAGGING_CONFIRMED` may be cancelled by its responsible party into `CANCELLED`, and the closure cascade of §3.5 cancels such orders automatically. `COMPLETED` and `CANCELLED` are terminal.

### 3.8. Signal Preemption Interconnections

Where a signalized intersection sits close to a crossing, the crossing's warning signals and the traffic signal must be interconnected so the traffic controller gets advance warning and clears the storage between them. A `ProgramAdministrator` registers a **PreemptionInterconnection** design with the `crossing_id`, the `traffic_signal_ref` controller identifier, the `track_approach_distance_ft` from the start of the approach circuit to the crossing (greater than zero), the `design_train_speed_mph` used for approach-time design (greater than zero), the `clear_storage_distance_ft` to clear between crossing and intersection (zero or more), and the designed `advance_preemption_seconds` and `track_clearance_green_seconds` (each zero or more). A crossing may have at most one interconnection that is not `DECOMMISSIONED` — a second registration is rejected with `ERR_ACTIVE_INTERCONNECTION_EXISTS` — and the crossing must be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`). The design starts in `DRAFT`.

Three timing requirements are derived from the design inputs. The `approach_seconds` is the approach distance divided by the design train speed converted to feet per second — at 1.46667 feet per second per mile per hour — rounded up to the next whole second. The `required_clearance_green_seconds` is the clear storage distance divided by a clearance speed of 15.0 feet per second, rounded up to the next whole second. The `required_advance_preemption_seconds` is the required clearance green plus a 5-second preemption buffer minus a 10-second overlap allowance, floored at zero.

Verification is a `RailSafetyOfficer` moving the design `DRAFT` → `TIMING_VERIFIED`, and it runs the full timing check: the `approach_seconds` must be at least 20 seconds of warning; the designed `track_clearance_green_seconds` must be at least the `required_clearance_green_seconds`; and the designed `advance_preemption_seconds` must be at least the `required_advance_preemption_seconds`. All three comparisons admit equality — meeting a requirement exactly passes. When all three hold, `timing_check_pass` is set to `true` and the design is verified; when any fails, the request is rejected with `ERR_PREEMPTION_TIMING_INADEQUATE` and the design stays `DRAFT`.

Commissioning puts the design into service: a `RailSafetyOfficer` moves `TIMING_VERIFIED` → `COMMISSIONED`, which requires the crossing still `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`) and equipped with gates — the crossing's `warning_device_class` must be `GATES` or `FOUR_QUADRANT_GATES`, since preemption without a gate mechanism is not permitted (else `ERR_PREEMPTION_REQUIRES_GATES`). Any interconnection in `DRAFT`, `TIMING_VERIFIED`, or `COMMISSIONED` may be taken out of service by a `ProgramAdministrator`, moving it to terminal `DECOMMISSIONED`; the closure cascade of §3.5 decommissions them automatically when the crossing closes.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, actions, awards, counters, inventory patches — return `200 OK`. The single member-removal operation returns `204 No Content` with no resource payload. All resources are mounted under the API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/crossings` | Register a crossing; computes exposure, projected exposure, hazard score, and review-due flag | ProgramAdministrator |
| GET | `/crossings` | List crossings with filters and pagination | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/crossings/{crossingId}` | Get one crossing | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| PATCH | `/crossings/{crossingId}/inventory` | Update inventory counts with OCC on the crossing version; recomputes derived risk fields | ProgramAdministrator |
| POST | `/crossings/{crossingId}/confirm-closure` | Confirm physical closure (CLOSURE_PENDING to CLOSED); fires the closure cascade | ProgramAdministrator |
| POST | `/localities` | Register a locality | ProgramAdministrator |
| GET | `/localities/{localityId}` | Get one locality | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/diagnostic-teams` | Register a diagnostic review team | ProgramAdministrator |
| GET | `/diagnostic-teams/{teamId}` | Get one diagnostic team | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/diagnostic-reviews` | Schedule a diagnostic review; enforces the team buffer rule and an ACTIVE crossing | ProgramAdministrator |
| GET | `/diagnostic-reviews` | List diagnostic reviews | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/diagnostic-reviews/{reviewId}` | Get one diagnostic review | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/diagnostic-reviews/{reviewId}/transition` | State moves: IN_SESSION, ACCEPTED (supersedes the prior accepted review), CANCELLED | ProgramAdministrator, RailSafetyOfficer |
| POST | `/diagnostic-reviews/{reviewId}/issue-recommendations` | Issue the team's recommendation set (IN_SESSION to RECOMMENDATIONS_ISSUED) | RailSafetyOfficer |
| POST | `/incident-reports` | File an incident report; computes FRA-reportability | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/incident-reports` | List incident reports | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/incident-reports/{incidentId}` | Get one incident report | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/incident-reports/{incidentId}/transition` | State moves per the investigation state machine (desk review forbidden for CASUALTY) | RailSafetyOfficer |
| POST | `/incident-reports/{incidentId}/issue-findings` | Issue investigation findings; fires the incident cascade | RailSafetyOfficer |
| POST | `/funding-programs` | Create an annual funding program (OPEN) | ProgramAdministrator |
| GET | `/funding-programs/{programId}` | Get one funding program | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/funding-programs/{programId}/transition` | State moves: ALLOCATION_LOCKED (runs the allocation sweep) or CLOSED | ProgramAdministrator |
| POST | `/upgrade-projects` | Propose a warning-device upgrade project | ProgramAdministrator, RailSafetyOfficer |
| GET | `/upgrade-projects` | List upgrade projects | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/upgrade-projects/{projectId}` | Get one upgrade project | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/upgrade-projects/{projectId}/transition` | State moves: ELIGIBLE (nominate; pins the priority score), IN_PROGRESS, COMPLETED, WITHDRAWN | ProgramAdministrator, RailSafetyOfficer |
| POST | `/upgrade-projects/{projectId}/award` | Issue an award with OCC on the program version; rolling from ELIGIBLE or post-lock from SELECTED | ProgramAdministrator |
| POST | `/upgrade-projects/{projectId}/rescind-award` | Rescind an award; restores the program pool exactly | ProgramAdministrator |
| POST | `/closure-agreements` | Open a closure or consolidation negotiation (DRAFT); computes the minimum incentive | RailSafetyOfficer, LocalAuthority |
| GET | `/closure-agreements` | List closure agreements | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/closure-agreements/{agreementId}` | Get one closure agreement | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/closure-agreements/{agreementId}/transition` | State moves: PROPOSED, DOT_ACCEPTED, LOCALITY_RATIFIED, EXECUTED, REJECTED, WITHDRAWN | ProgramAdministrator, RailSafetyOfficer, LocalAuthority |
| POST | `/closure-agreements/{agreementId}/counter` | Counter-offer; alternation, round cap, direction, and cap rules apply | RailSafetyOfficer, LocalAuthority |
| POST | `/quiet-zone-applications` | Create a quiet zone application (DRAFT) for the acting locality | LocalAuthority |
| GET | `/quiet-zone-applications` | List quiet zone applications | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/quiet-zone-applications/{qzId}` | Get one quiet zone application | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/quiet-zone-applications/{qzId}/members` | Add a member crossing with supplemental safety measures while the zone is editable | LocalAuthority |
| GET | `/quiet-zone-crossings` | List zone membership rows | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/quiet-zone-crossings/{memberId}` | Get one membership row | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| DELETE | `/quiet-zone-crossings/{memberId}` | Remove a member while the zone is DRAFT or SUPPLEMENT_REQUIRED (owner locality) | LocalAuthority |
| POST | `/quiet-zone-applications/{qzId}/transition` | State moves: SUBMITTED, UNDER_REVIEW, EFFECTIVE (activate or reinstate), SUSPENDED, WITHDRAWN | LocalAuthority, RailSafetyOfficer |
| POST | `/quiet-zone-applications/{qzId}/decide` | Officer decision on an UNDER_REVIEW application; outcome is server-computed | RailSafetyOfficer |
| POST | `/maintenance-assignments` | Create a responsibility assignment; supersedes the pair's current ACTIVE row | ProgramAdministrator |
| GET | `/maintenance-assignments` | List responsibility assignments | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/maintenance-assignments/{assignmentId}` | Get one assignment | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/maintenance-assignments/{assignmentId}/revoke` | Revoke the ACTIVE assignment; reinstates the most recently superseded row | ProgramAdministrator |
| POST | `/maintenance-work-orders` | Plan a work window; copies the responsible party from the ACTIVE assignment | RailroadMaintainer, LocalAuthority |
| GET | `/maintenance-work-orders` | List work orders | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/maintenance-work-orders/{workOrderId}` | Get one work order | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/maintenance-work-orders/{workOrderId}/transition` | State moves: FLAGGING_CONFIRMED, IN_WORK (flagging and window gates), COMPLETED, CANCELLED | RailroadMaintainer, LocalAuthority |
| POST | `/preemption-interconnections` | Register a signal-preemption interconnection design (DRAFT); computes the derived timing fields | ProgramAdministrator |
| GET | `/preemption-interconnections` | List interconnections | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| GET | `/preemption-interconnections/{interconnectionId}` | Get one interconnection | ProgramAdministrator, RailSafetyOfficer, LocalAuthority, RailroadMaintainer |
| POST | `/preemption-interconnections/{interconnectionId}/transition` | State moves: TIMING_VERIFIED (runs the timing check), COMMISSIONED (requires gates), DECOMMISSIONED | ProgramAdministrator, RailSafetyOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock; startup default is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time | ProgramAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described; this catalogue is the index of codes and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CROSSING_NOT_FOUND` | 404 |
| `ERR_LOCALITY_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_QZ_APPLICATION_NOT_FOUND` | 404 |
| `ERR_QZ_MEMBER_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_INTERCONNECTION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_CROSSING_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_NOT_SELECTED` | 409 |
| `ERR_PROGRAM_HAS_OPEN_PROJECTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FLAGGING_PLAN_REQUIRED` | 422 |
| `ERR_FLAGGING_NOT_CONFIRMED` | 409 |
| `ERR_SSM_INSUFFICIENT` | 409 |
| `ERR_PREEMPTION_TIMING_INADEQUATE` | 422 |
| `ERR_PREEMPTION_REQUIRES_GATES` | 409 |
| `ERR_ACTIVE_INTERCONNECTION_EXISTS` | 409 |
| `ERR_DUPLICATE_DOT_NUMBER` | 409 |
| `ERR_DUPLICATE_FISCAL_YEAR` | 409 |
| `ERR_SELF_CONSOLIDATION` | 422 |
| `ERR_ACTIVE_PROJECT_EXISTS` | 409 |
| `ERR_NO_FALLBACK_ASSIGNMENT` | 409 |
| `ERR_FRA_NOT_REPORTABLE` | 409 |
| `ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION` | 422 |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 409 |
| `ERR_EMPTY_ZONE` | 422 |
| `ERR_ZONE_MEMBERSHIP_CONFLICT` | 409 |
| `ERR_COUNTER_TURN` | 403 |
| `ERR_SELF_ACCEPT_FORBIDDEN` | 403 |
| `ERR_LOCALITY_MISMATCH` | 403 |
| `ERR_RESPONSIBILITY_MISMATCH` | 403 |
| `ERR_RESPONSIBILITY_GAP` | 409 |
| `ERR_DIAGNOSTIC_REVIEW_REQUIRED` | 409 |
| `ERR_WORK_WINDOW_OVERLAP` | 409 |
| `ERR_TEAM_SCHEDULE_BUFFER` | 409 |
| `ERR_OUTSIDE_WORK_WINDOW` | 409 |
| `ERR_INCIDENT_IN_FUTURE` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_AWARD_AMOUNT_INVALID` | 422 |
| `ERR_INCENTIVE_CAP_EXCEEDED` | 422 |
| `ERR_INCENTIVE_REGRESSION` | 422 |
