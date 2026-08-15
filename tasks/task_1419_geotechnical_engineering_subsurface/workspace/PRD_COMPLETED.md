# Geotechnical Subsurface API — Product Requirements Document

## 1. Introduction

A geotechnical engineering firm runs every subsurface investigation as a chain of gated commitments: a scope is negotiated, borings are planned, drilling subcontractors are scheduled, underground utilities are cleared before any steel touches soil, samples travel under chain-of-custody into the laboratory, and only then can a licensed engineer publish foundation bearing recommendations and stand behind them with a sealed report. Each stage depends on the integrity of the one before it, and each carries commercial exposure — standby rig time, laboratory fees, and changed-condition claims from contractors who insist the ground was not what the report said it would be. This document specifies an API that orchestrates that entire engagement lifecycle, from client intake through construction-phase observation and claim settlement.

The API is built around a Project resource whose lifecycle machine mirrors the real engagement arc — scoping, field authorization, drilling, laboratory analysis, report review, issuance, construction support, and closure — and around a set of derived fiscal and safety rollups (a committed-authorization total, a claims-exposure figure, a testing invoice, a volume-discounted total fee, and a three-valued operational posture) that must stay consistent with every child record as events unfold. Safety gating is deliberate: a single utility-conflict ticket freezes field operations project-wide, an expired one-call ticket blocks drilling even when a rig is mobilized, and no report can be sealed while any laboratory order remains unaccepted or the underlying analysis has gone stale. The specification is written for the engineering team implementing the service: §2 defines system-wide contracts, §3 walks the business workflows, §4 summarizes the endpoint surface, and §5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across the API. Where §3 narrates when a rule fires, this section pins down how the rule is represented on the wire.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are exactly these ten: `FirmAdmin`, `ClientRep`, `ProjectManager`, `StaffEngineer`, `FieldGeologist`, `DrillingSub`, `LabManager`, `LabTechnician`, `SeniorEngineer`, and `PrincipalEngineer`. A request whose headers are missing, or whose `X-User-Role` value is not one of these ten names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `ClientRep`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` — directly, or through a Project's `client_id` — compare that foreign key to `X-User-ID`. When `X-User-Role` is `DrillingSub`, `X-User-ID` is the `id` of the acting `Subcontractor`; ownership checks compare a RigAssignment's `subcontractor_id` to `X-User-ID`. The remaining eight roles — `FirmAdmin`, `ProjectManager`, `StaffEngineer`, `FieldGeologist`, `LabManager`, `LabTechnician`, `SeniorEngineer`, and `PrincipalEngineer` — are opaque: for each of them, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, as `prepared_by_user_id` on a Report, `sealed_by_pe_user_id` on a sealed Report, or `submitted_by_user_id` on a LabTestResult) but never compares it to any entity's `id`. On list endpoints the entity-backed ownership rules act as visibility scoping rather than rejection: a `ClientRep` listing projects, reports, claims, or exploration authorizations sees only records tied to their own client id, and a `DrillingSub` listing rig assignments sees only their own assignments.

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

### 2.3. Pagination and List Filtering

List endpoints paginate through two query parameters. `limit` caps the number of items returned: it defaults to 10, accepts a minimum of 1, and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Every list response sorts by `created_at` in ascending order, and its envelope `meta` carries `limit`, `offset`, `total_count`, and `has_more`. A `limit` or `offset` that is not an integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Records created within the same logical-clock instant share their `created_at` and are ordered by creation sequence, earliest-created first.

Most list endpoints also accept optional equality filters named after the owning or related resource — for example `client_id` on the project list, `project_id` on the boring-plan, lab-order, analysis, report, visit, claim, and authorization lists, `boring_id` on the rig-assignment, clearance, and sample lists, `subcontractor_id` on the rig-assignment list, `boring_plan_id` and `offset_of_boring_id` on the boring list, `supersedes_plan_id` on the boring-plan list, `sample_id` on the lab-order list, `lab_test_order_id` on the lab-result list, and `observation_visit_id` on the claim list. A filter that is absent imposes no constraint.

### 2.4. Common Resource Properties

Every resource in the system — Client, Project, BoringPlan, Subcontractor, RigAssignment, UtilityClearance, Boring, Sample, LabTestOrder, LabTestResult, FoundationAnalysis, Report, ObservationVisit, ChangedConditionClaim, and ExplorationAuthorization — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation of the resource, whether client-driven or system-driven.

Every state transition described in §3 increments the transitioning resource's `version` by 1 and refreshes its `updated_at`; side effects that mutate a second resource (for example, a plan being locked by a first drill, or a prior issued report being superseded) increment that resource's `version` as well. In addition, three events increment the parent Project's `version` by 1 even though the Project itself is not the target: every explicit Project lifecycle transition, the creation of a new boring-plan revision, and the approval or revocation of an exploration authorization.

### 2.5. Nested Resource Retrieval

Endpoints whose paths contain multiple resource identifiers validate them strictly left to right. Each identifier must resolve to an existing resource before the next is examined; the first identifier that does not resolve aborts the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no later identifier or body validation is evaluated for that request. A nested identifier that exists but belongs to a different parent than the path implies is treated as not found under that path.

### 2.6. The Logical Clock

All time-dependent rules in the system evaluate against a single server-side logical clock, never against wall-clock time. Before any client call adjusts it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. A `FirmAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp and sets the current logical instant to it; the capability returns 200 with an empty data object. Advancing the clock performs a sweep: every utility clearance ticket in `FILED` or `CLEARED` whose `expires_on` now lies strictly in the past transitions to `EXPIRED`. All timestamp comparisons in this document use second-precision ISO 8601 instants.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. Each requires a non-optional version field in the request body carrying the client's last observed `version` of the named parent resource; if that value does not equal the resource's current `version` at evaluation time, the request is rejected and no side effect occurs.

- Creating a boring-plan revision — `POST /geo/projects/{id}/boring-plans` — requires `expected_project_version` matching the target Project's current `version`. A mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412): another writer may have created a plan revision (which the next approval can legitimately supersede) since the client last read the project, and the client's view of the project is stale.
- Approving or revoking an exploration authorization — `POST /geo/exploration-authorizations/{id}/transition` — requires `expected_project_version` matching the Project's current `version`; a mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The transition mutates the project's committed-authorization total, so a stale view of that total must not drive the cap check.
- Issuing a report — `POST /geo/reports/{id}/issue` — requires `expected_report_version` matching the Report's current `version`; a mismatch is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412), covering the case where a reviewer has cycled the report back to `DRAFT` since the issuer last observed it.

Endpoints not named above take no version field at all; callers must not supply one elsewhere.

### 2.8. Money, Measurement, and Rounding Conventions

All monetary amounts are represented as integer cents — `base_fee_cents`, `additional_auth_cap_cents`, `fee_cents`, `drilling_cost_cents`, `claimed_amount_cents`, and their kin are whole numbers of cents with no fractional part. Where a monetary formula produces a fraction, the result is rounded half-up to whole cents; a half-cent rounds away from zero. Bearing capacities (`bearing_capacity_provisional_psf`, `bearing_capacity_final_psf`) are carried to 2 decimal places, rounded half-up. Settlement estimates (`settlement_est_in`) are carried to 3 decimal places, rounded half-up. Committed rig time (`committed_rig_hours`) is expressed in fractional hours with 1 decimal place. Soil-classification inputs (`percent_passing_200`, `liquid_limit`, `plasticity_index`) are consumed as given to 1 decimal place, and the plasticity A-line comparison value is evaluated without rounding.

### 2.9. Request Evaluation Order

Every request is evaluated against an ordered pipeline of check categories. A failure in an earlier category aborts evaluation, so a request never surfaces a later category's error when an earlier one applies:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization and ownership** — the acting role appears in the endpoint's authorized list, and entity-backed ownership holds: a `ClientRep` must own the target Project's `client_id`, a `DrillingSub` must own the target assignment's `subcontractor_id` (`ERR_FORBIDDEN_ROLE`, 403).
3. **Existence** — every path identifier resolves, left to right (`ERR_RESOURCE_NOT_FOUND`, 404).
4. **Body well-formedness** — required fields are present, enum values are in range, and numbers are in domain: `recovery_pct` between 0 and 100 inclusive, `refusal_depth_ft` strictly less than the boring's `planned_depth_ft`, `claimed_amount_cents` non-negative, and so on (`ERR_VALIDATION`, 400). The request body must be a JSON object (`ERR_VALIDATION` otherwise); an absent or unparseable body is treated as an empty object. Note that rig-window ordering is deliberately not part of this category; it is a temporal rule in category 8.
5. **State legality** — the target resource's current state permits the requested transition per its state machine, parent states permit the child operation, and the OCC checks of §2.7 pass. This category carries the 409 family — `ERR_INVALID_STATE`, `ERR_PROJECT_STATE_FORBIDS`, `ERR_PLAN_NOT_EDITABLE`, `ERR_ANALYSIS_DATA_STALE`, `ERR_ORDER_STATE_FORBIDS`, `ERR_RIG_NOT_MOBILIZED`, `ERR_SAMPLE_NOT_IN_LAB`, `ERR_ANALYSIS_NOT_VERIFIED`, `ERR_CLAIM_STATE_FORBIDS` — and the 412 stale-version errors `ERR_STALE_PROJECT_VERSION` and `ERR_STALE_REPORT_VERSION`. For transition requests, establishing that the named (from, to) pair exists in the target resource's state machine is the first check of this category and precedes any transition-specific payload validation (for example, the drilling measurements), which is evaluated immediately after it.
6. **Field-safety gates** — clearance presence and validity, and the frozen-posture freeze (`ERR_CLEARANCE_MISSING`, `ERR_CLEARANCE_EXPIRED`, `ERR_POSTURE_FROZEN`, all 409).
7. **Business constraints** — plan exclusivity, rig double-booking, subcontractor standing, laboratory capacity, rerun and appeal caps, segregation of duties, and uniqueness of ticket and license numbers (409 family).
8. **Temporal rules** — rig-window ordering and visit-date arrival (`ERR_INVALID_WINDOW`, `ERR_VISIT_DATE_FUTURE`, both 422).
9. **Cross-referential consistency** — the referenced sample, visit, or parent boring belongs to the implied project or bears the required state (`ERR_SAMPLE_PROJECT_MISMATCH`, `ERR_VISIT_PROJECT_MISMATCH`, `ERR_OFFSET_PARENT_NOT_REFUSED`, all 422).
10. **Fiscal guards** — authorization cap, extra-boring availability, and claim-amount floors (`ERR_AUTH_CAP_EXCEEDED`, `ERR_EXTRA_BORINGS_EXHAUSTED`, `ERR_CLAIM_AMOUNT_INVALID`, all 422).

### 2.10. Derived Rollups and Hierarchical Consistency

Several resources expose computed rollups that the server maintains as child records change; clients never write them directly. On the Project: `posture` summarizes operational safety (see §3.2 and §3.7), `additional_committed_cents` accumulates approved exploration budget, `claims_exposure_cents` measures open claim exposure, `testing_invoice_cents` accumulates laboratory fees, and `total_fee_cents` is the project's volume-discounted commercial total. On the Subcontractor, `committed_rig_hours` tracks outstanding rig-window commitments. On the Boring, `drilling_cost_cents` is computed at drilling time. On the Sample, `uscs_class` is derived from accepted laboratory results. Whenever an event changes a child's contribution to a rollup, the server recomputes the parent figure immediately as part of the same operation; such recomputation refreshes the parent's `updated_at`. Cascades also propagate state: a conflict-marked clearance freezes the project's posture, a first drilled boring locks its plan, a rejected laboratory order stalenes every verified analysis of the project, and a verified analysis supersedes its predecessors. §3 specifies each cascade at the point it fires.

## 3. Business Logic & Workflows

The workflows below follow a geotechnical engagement in its natural chronological order. State names appear as exact strings; where a transition has no guard listed, only the from-state itself constrains it, and requesting any transition from a state that does not offer it is rejected with `ERR_INVALID_STATE` (HTTP 409). Every workflow resource carries a system-managed state field: most call it `status`, while the Sample calls its own `custody_status` and the Subcontractor calls its own `standing`.

### 3.1. Client Intake, Project Setup, and Boring Plan Revisions

A `FirmAdmin` opens a commercial relationship by creating a Client with the organization's `name` and primary `contact_email`. With the client on file, the same administrator creates a Project, supplying the owning `client_id` (which must reference an existing Client, failing with `ERR_VALIDATION` otherwise), a descriptive `name`, the `site_address`, the contractual `target_report_date`, the fixed `base_fee_cents` for base services (a non-negative integer), the client-negotiated `additional_auth_cap_cents` ceiling on cumulative approved additional-exploration amounts (likewise a non-negative integer), and the `assumed_gwt_depth_ft` — the assumed groundwater table depth, recorded for reference only; no calculation in this specification consumes it. A new Project starts in `DRAFT` with `posture` equal to `OPEN`, `additional_committed_cents` at zero, `claims_exposure_cents` at zero, and `testing_invoice_cents` at zero. The project list can be narrowed by `client_id`.

The Project lifecycle runs `DRAFT` → `SCOPED` → `FIELD_AUTHORIZED` → `FIELDWORK` → `LAB_ANALYSIS` → `REPORT_REVIEW` → `ISSUED` → `CONSTRUCTION_SUPPORT` → `CLOSED`, with one revision loop (§3.6) returning `REPORT_REVIEW` to `LAB_ANALYSIS`. A `ProjectManager` drives most of these transitions. Moving `DRAFT` → `SCOPED` requires that at least one boring plan of the project already stands in `APPROVED` or `LOCKED`; without one the transition is rejected with `ERR_PROJECT_STATE_FORBIDS` (HTTP 409). Every explicit Project transition increments the Project's `version` by 1.

Scope is expressed through **BoringPlan** revisions. A `StaffEngineer` drafts a plan against a project by supplying `planned_boring_count` — the number of borings in scope, a non-negative integer — and `planned_total_footage_ft`, the total planned drilling footage, a non-negative number; an optional `supersedes_plan_id` names the earlier revision this one replaces and defaults to null, and when supplied it must reference an existing plan of the same project (`ERR_VALIDATION` otherwise). Each revision receives a `revision_no` assigned as one greater than the highest existing revision number of the same project, starting at 1, and the creation carries the OCC guard of §2.7: the request must include `expected_project_version` equal to the project's current `version`, failing which it is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). Plan creation itself increments the parent Project's `version` by 1. Plans can be listed with `project_id` and `supersedes_plan_id` filters.

A plan begins in `DRAFT`. The drafting `StaffEngineer` submits it (`DRAFT` → `SUBMITTED`); submission requires `planned_boring_count` of at least 1, enforced as a body check failing with `ERR_VALIDATION` (HTTP 400). A `ProjectManager` then either returns the plan to `DRAFT` for rework (`SUBMITTED` → `DRAFT`, the revise loop) or approves it (`SUBMITTED` → `APPROVED`). Approval is guarded twice: the project must still be in `DRAFT` or `SCOPED` — otherwise `ERR_PROJECT_STATE_FORBIDS` — and no other boring plan of the same project may stand in `APPROVED` or `LOCKED`, otherwise the approval is rejected with `ERR_PLAN_ALREADY_ACTIVE` (HTTP 409); the revision named in the new plan's `supersedes_plan_id` is the natural exception to that exclusivity, since approving it is precisely what retires the earlier plan. When an approval succeeds for a revision naming a superseded predecessor, the predecessor — if it stands in `APPROVED` — transitions to `SUPERSEDED` automatically, as it also does whenever a later revision of the same project is approved while naming it. Throughout this document, **active plan** means the project's latest revision standing in `APPROVED` or `LOCKED`.

Once field work begins, the plan freezes: the first boring of a plan to reach `DRILLED` flips the plan from `APPROVED` to `LOCKED` automatically, bumps the plan's `version`, and freezes plan scope — further borings enter only via the offset mechanism of §3.3. A `StaffEngineer` adds borings directly only to an `APPROVED` plan; attempting to add one to a `LOCKED` or `SUPERSEDED` plan is rejected with `ERR_PLAN_NOT_EDITABLE` (HTTP 409). Each new boring carries a `boring_no` identifier within the plan (for example B-1), a strictly positive `planned_depth_ft` termination depth, and an optional `access_difficult` flag defaulting to false that marks the limited-access drilling surcharge; it starts life in `PLANNED` with `offset_of_boring_id` null. The boring list view can be narrowed by `boring_plan_id` or by `offset_of_boring_id` to find a refused boring's replacements.

### 3.2. Rig Scheduling, Subcontractor Standing, and Utility Clearance

Drilling capacity comes from registered subcontractors. A `FirmAdmin` registers each Subcontractor with its legal `name`, its driller `license_no` — unique across subcontractors, with duplicates rejected as `ERR_DUPLICATE_TICKET` (HTTP 409) — its standby `day_rate_cents`, and its `max_concurrent_rigs` ceiling — both non-negative integers, and both recorded attributes only: no guard or calculation in this specification consumes them. A subcontractor starts in `GOOD_STANDING`; the same administrator may later suspend it (`GOOD_STANDING` → `SUSPENDED`) or reinstate it (`SUSPENDED` → `GOOD_STANDING`). Each subcontractor exposes `committed_rig_hours`, the sum of its outstanding rig-window commitments: for every one of its rig assignments in `SCHEDULED` or `MOBILIZED`, the window length — `window_end` minus `window_start` — in fractional hours, totaled and expressed with one decimal place. Scheduling then cancelling, or mobilizing then demobilizing, restores the prior value exactly.

A `ProjectManager` schedules a rig window for a boring by naming the `subcontractor_id` (which must reference an existing Subcontractor, failing with `ERR_VALIDATION` otherwise) and the half-open window `window_start` (inclusive) to `window_end` (exclusive). Four guards apply. The window must not overlap any existing `SCHEDULED` or `MOBILIZED` assignment of the same subcontractor; because intervals are half-open, one assignment's `window_end` equaling another's `window_start` is permitted — an overlap is rejected with `ERR_RIG_DOUBLE_BOOKED` (HTTP 409). The subcontractor must stand in `GOOD_STANDING`, since a suspended firm can neither receive new assignments nor mobilize (`ERR_STANDING_SUSPENDED`, HTTP 409). The project's `posture` must not be `FROZEN` (`ERR_POSTURE_FROZEN`, HTTP 409). And `window_end` must lie strictly after `window_start` — a temporal rule whose violation returns `ERR_INVALID_WINDOW` (HTTP 422), not a body-validation error. A successful creation starts the assignment in `SCHEDULED`, adds the window's hours to `committed_rig_hours`, and — when this is the boring's first assignment — advances the boring from `PLANNED` to `SCHEDULED` automatically. Assignments are listed with `boring_id` and `subcontractor_id` filters.

From `SCHEDULED`, the assigned `DrillingSub` mobilizes the rig (`SCHEDULED` → `MOBILIZED`): the caller's `X-User-ID` must equal the assignment's `subcontractor_id` (`ERR_FORBIDDEN_ROLE`), the subcontractor must remain in `GOOD_STANDING` (`ERR_STANDING_SUSPENDED`), and the project must not be `FROZEN` (`ERR_POSTURE_FROZEN`). Demobilization (`MOBILIZED` → `DEMOBILIZED`) is likewise restricted to the owning `DrillingSub` and releases the window's hours from `committed_rig_hours`. A `ProjectManager` may cancel an assignment (transitioning it to `CANCELLED`): from `SCHEDULED` unconditionally — the boring then stays `SCHEDULED` so a later assignment may re-cover it — and from `MOBILIZED` only while the boring has not reached `DRILLED`, `LOGGED`, or `CLOSED` (`ERR_INVALID_STATE` otherwise). Either cancellation releases the window's hours as compensation.

Before any boring advances, utilities must be cleared. A `StaffEngineer` files a one-call UtilityClearance ticket against a boring with its `ticket_number` — unique per boring, duplicates rejected as `ERR_DUPLICATE_TICKET` — the `issued_on` timestamp, and an optional `valid_days` defaulting to 14 (a positive integer when supplied). The system computes `expires_on` as `issued_on` plus `valid_days` times twenty-four hours. The ticket is valid while the current logical time is less than or equal to `expires_on`: the boundary is inclusive, so clearing or drilling at exactly `expires_on` succeeds, while one second later fails with `ERR_CLEARANCE_EXPIRED` (HTTP 409). A ticket starts `FILED`; a `StaffEngineer` marks it `CLEARED` (`FILED` → `CLEARED`) provided it is still valid (`ERR_CLEARANCE_EXPIRED` otherwise). When the logical clock advances strictly past `expires_on`, a ticket in `FILED` or `CLEARED` transitions to `EXPIRED` automatically. Clearances are listed with a `boring_id` filter.

Conflict marking is the project's emergency brake. A `ProjectManager` may mark a ticket in `FILED` or `CLEARED` as `CONFLICT_MARKED`; doing so recomputes the project's `posture` to `FROZEN`, a safety freeze that gates rig mobilization, new rig scheduling, boring clearance, and drilling. A `StaffEngineer` can return a `CONFLICT_MARKED` ticket to `CLEARED` provided the ticket is still valid (`ERR_CLEARANCE_EXPIRED` otherwise); the project's posture is then recomputed, and the freeze lifts when no other clearance on the active plan's borings remains `CONFLICT_MARKED`. The posture rule, stated once and applied everywhere: `posture` is `FROZEN` when any clearance of the active plan's borings is `CONFLICT_MARKED`; otherwise it is `CLAIM_REVIEW` when any claim of the project stands in `UNDER_REVIEW` or `SUBSTANTIATED` (§3.7); otherwise it is `OPEN`. `FROZEN` dominates `CLAIM_REVIEW`, which dominates `OPEN`.

With rigs scheduled and tickets filed, the project can be authorized for the field: a `ProjectManager` moves it `SCOPED` → `FIELD_AUTHORIZED`, which requires at least one rig assignment in `SCHEDULED` covering a boring of the active plan (`ERR_PROJECT_STATE_FORBIDS` otherwise) and requires every boring of the active plan to hold at least one clearance ticket in `FILED` or `CLEARED` (`ERR_CLEARANCE_MISSING`, HTTP 409, otherwise). Fieldwork itself begins with the `FIELD_AUTHORIZED` → `FIELDWORK` transition, permitted only while `posture` is not `FROZEN` (`ERR_POSTURE_FROZEN`).

### 3.3. Drilling Execution, Refusal, and Additional Exploration Authorization

Once the project stands in `FIELDWORK`, each boring walks its own machine: `PLANNED` → `SCHEDULED` → `CLEARED` → `DRILLED` → `LOGGED` → `CLOSED`, with `REFUSED` and `ABANDONED` as alternate terminals. A `StaffEngineer` advances a boring from `SCHEDULED` to `CLEARED` once utility clearance is in hand: at least one of the boring's tickets must stand in `CLEARED` (`ERR_CLEARANCE_MISSING` otherwise), that ticket must still be valid at the current logical time (`ERR_CLEARANCE_EXPIRED`), and the project must not be `FROZEN` (`ERR_POSTURE_FROZEN`).

Drilling (`CLEARED` → `DRILLED`) belongs to the `DrillingSub`. Four gates guard it, all evaluated before any footage is recorded: the project must stand in `FIELDWORK` (`ERR_PROJECT_STATE_FORBIDS` otherwise); a rig assignment for this boring must stand in `MOBILIZED` and the caller's `X-User-ID` must equal that assignment's `subcontractor_id` (`ERR_RIG_NOT_MOBILIZED`, HTTP 409, otherwise); a `CLEARED` ticket of the boring must still be valid (`ERR_CLEARANCE_EXPIRED`); and the project must not be `FROZEN` (`ERR_POSTURE_FROZEN`). The drilling report payload sets the boring's `actual_depth_ft` (required, strictly positive), `rock_depth_ft` (feet drilled in rock, a subset of the actual depth, optional and non-negative, defaulting to 0 — recorded as given, with no cross-check against `actual_depth_ft`), `groundwater_depth_ft` (measured groundwater depth, optional and non-negative, defaulting to null), and `avg_n60` (the average corrected SPT N60 over the boring, required and non-negative). At that moment the server also computes `drilling_cost_cents`; locks the plan — the owning plan transitions `APPROVED` → `LOCKED` on this first drill; flips the plan's `mobilization_charged` flag from false to true when this is the first boring of the plan to reach `DRILLED`; and marks every `VERIFIED` FoundationAnalysis of the project `STALE` (§3.5). All four boring measurements default to null until this transition records them.

The drilling cost is a tiered per-foot price on `actual_depth_ft`. Each of the first 25 feet bills at 4,200 cents per foot; each foot beyond 25, up to and including 75 feet, bills at 6,800 cents per foot; each foot beyond 75 bills at 9,500 cents per foot. Rock carries a multiplier: the deepest `rock_depth_ft` feet of the drilled interval are rock, and each rock foot bills at its own depth band's rate multiplied by 1.8 instead of the plain band rate — equivalently, the rock premium adds eight-tenths of the applicable band rate per rock foot. When `access_difficult` is true, a flat 15,000-cent surcharge applies. A per-boring floor then raises the boring's cost to 25,000 cents when footage plus rock premium plus surcharge would otherwise total less. Finally, mobilization: 45,000 cents is added only for the first boring of the plan to reach `DRILLED`, the event that flips `mobilization_charged`. The result is stored on the boring as `drilling_cost_cents` in integer cents, the tier arithmetic itself exact.

After drilling, a `FieldGeologist` marks the boring `LOGGED` (`DRILLED` → `LOGGED`) once at least one Sample of the boring exists in any custody state (`ERR_INVALID_STATE` otherwise), and a `StaffEngineer` later closes the log (`LOGGED` → `CLOSED`), at which point the boring is backfilled and sealed. When the rig hits refusal, the `DrillingSub` instead reports `DRILLED` → `REFUSED` with a non-negative `refusal_depth_ft` that must lie strictly below the boring's `planned_depth_ft` (`ERR_VALIDATION` otherwise); the refusal depth is recorded on the boring. A `ProjectManager` may abandon a boring from `PLANNED` or `SCHEDULED`; abandoning a `SCHEDULED` boring also transitions every one of its rig assignments in `SCHEDULED` or `MOBILIZED` to `CANCELLED` and releases their committed rig hours. The field phase ends when a `ProjectManager` moves the project `FIELDWORK` → `LAB_ANALYSIS`, permitted only once every boring of the active plan stands in `CLOSED` or `ABANDONED` (`ERR_PROJECT_STATE_FORBIDS` otherwise).

Refusal triggers the offset mechanism. A `StaffEngineer` may create an offset boring from a parent boring that stands in `REFUSED`; a parent in any other state draws `ERR_OFFSET_PARENT_NOT_REFUSED` (HTTP 422). The offset is a new boring of the same plan — created even when the plan is `LOCKED`, the one way into a frozen scope — with its own `boring_no`, strictly positive `planned_depth_ft`, and optional `access_difficult`, and with `offset_of_boring_id` pointing back to the refused parent. When the offset would push the plan's boring tally beyond `planned_boring_count`, the project must hold an `APPROVED` ExplorationAuthorization whose `consumed_boring_count` is still below its `extra_boring_count` (`ERR_EXTRA_BORINGS_EXHAUSTED`, HTTP 422, otherwise; when several qualifying authorizations exist, the earliest-created one is consumed); creating such an over-plan offset increments the authorization's `consumed_boring_count` by 1, and when the count reaches `extra_boring_count` the authorization transitions automatically from `APPROVED` to `EXHAUSTED`, its amount remaining committed on the project. Offsets within the planned count consume no authorization.

That authorization is the commercial instrument for extra exploration. A `ProjectManager` proposes an ExplorationAuthorization under a project in `FIELDWORK` (other states are rejected with `ERR_PROJECT_STATE_FORBIDS`), supplying `authorized_amount_cents` — the client-authorized additional exploration budget, a non-negative integer — and `extra_boring_count`, likewise a non-negative integer, the number of offset borings the authorization permits beyond `planned_boring_count`; the proposal starts in `PROPOSED` with `consumed_boring_count` at zero. The owning `ClientRep` approves it (`PROPOSED` → `APPROVED`): the caller's `X-User-ID` must equal the project's `client_id` (`ERR_FORBIDDEN_ROLE` otherwise); the project's `additional_committed_cents` plus the new `authorized_amount_cents` must not exceed `additional_auth_cap_cents`, an inclusive boundary — a total exactly equal to the cap passes, one cent over fails with `ERR_AUTH_CAP_EXCEEDED` (HTTP 422); and the request must carry `expected_project_version` per §2.7, a mismatch drawing `ERR_STALE_PROJECT_VERSION`. Approval adds `authorized_amount_cents` to `additional_committed_cents` and increments the Project's `version` by 1. The `ClientRep` may instead revoke an approval (`APPROVED` → `REVOKED`) under the same ownership and OCC guards, but only while `consumed_boring_count` is still zero (`ERR_INVALID_STATE` otherwise); revocation subtracts the amount from `additional_committed_cents` as compensation and likewise increments the Project's `version`. The project's `additional_committed_cents` therefore always equals the sum of `authorized_amount_cents` over authorizations in `APPROVED`, plus those in `EXHAUSTED`, which keep their amounts committed. Authorizations are listed with a `project_id` filter.

### 3.4. Sample Custody, Laboratory Testing, and Soil Classification

Sampling begins once a boring stands in `DRILLED` or `LOGGED` — logging a sample against a boring in any other state is rejected with `ERR_PROJECT_STATE_FORBIDS`. A `FieldGeologist` records each Sample with `depth_top_ft` and `depth_bottom_ft` delimiting the sampled interval — both non-negative, the top must lie strictly above the bottom, and neither may exceed the boring's `actual_depth_ft` — a `sampler_type` of `SPT`, `SHELBY`, `BULK`, or `ROCK_CORE`, and a `recovery_pct` between 0 and 100 inclusive; malformed intervals or out-of-range recovery fail with `ERR_VALIDATION`. Samples start in `COLLECTED` custody and can be listed by `boring_id`.

Custody is a one-way street with two bad endings. The `FieldGeologist` ships the sample (`COLLECTED` → `IN_TRANSIT`); a `LabTechnician` receives it (`IN_TRANSIT` → `LAB_RECEIVED`); a sample that never arrives is reported `LOST` by the `FieldGeologist` (`IN_TRANSIT` → `LOST`). From `LAB_RECEIVED` a `LabManager` may archive the sample (`LAB_RECEIVED` → `ARCHIVED`) only when no laboratory order of the sample stands in `REQUESTED`, `AUTHORIZED`, `IN_TEST`, `RESULT_SUBMITTED`, or `REJECTED` (`ERR_INVALID_STATE` otherwise). Destructive testing consumes material: when an order of type `UNCONFINED_COMPRESSION` or `DIRECT_SHEAR` for the sample reaches `ACCEPTED`, the sample's custody transitions automatically from `LAB_RECEIVED` to `CONSUMED`.

Laboratory work runs on LabTestOrders. A `LabManager` orders a test under a project standing in `FIELDWORK`, `LAB_ANALYSIS`, or `REPORT_REVIEW` — errata orders during review are expressly permitted, other states rejected with `ERR_PROJECT_STATE_FORBIDS` — naming the `sample_id`, a `test_type` of `MOISTURE_CONTENT`, `ATTERBERG`, `SIEVE_ANALYSIS`, `UNCONFINED_COMPRESSION`, `DIRECT_SHEAR`, `CONSOLIDATION`, or `PROCTOR`, and an optional `priority` of `STANDARD` (the default) or `RUSH`. The sample must belong to this project: its boring's plan must trace back to the same project, otherwise the order is rejected with `ERR_SAMPLE_PROJECT_MISMATCH` (HTTP 422); a `sample_id` that does not resolve to any existing sample fails the same way. Every order carries a `fee_cents` computed at creation: the base fee for its `test_type` — 4,533 cents for `MOISTURE_CONTENT`, 24,500 for `ATTERBERG`, 18,500 for `SIEVE_ANALYSIS`, 32,000 for `UNCONFINED_COMPRESSION`, 55,000 for `DIRECT_SHEAR`, 88,000 for `CONSOLIDATION`, 21,000 for `PROCTOR` — multiplied by 1.5 when `priority` is `RUSH` and by 1.0 otherwise, rounded half-up to whole cents per order line with a half-cent rounding away from zero. The rounding order is pinned: each line is rounded first and only then summed. Summing unrounded products and rounding once is forbidden and yields a different total — two rush moisture-content orders must total 13,600 cents (two lines of 6,800), not 13,599. The project's `testing_invoice_cents` is the sum of `fee_cents` over all of the project's orders in any status: fees accrue at order time and rejected reruns are never refunded. The order list filters by `project_id` and `sample_id`.

An order walks `REQUESTED` → `AUTHORIZED` → `IN_TEST` → `RESULT_SUBMITTED` → `ACCEPTED`, with rejection and rerun branches. A `LabManager` authorizes an order (`REQUESTED` → `AUTHORIZED`) only while its sample's custody is `LAB_RECEIVED` (`ERR_SAMPLE_NOT_IN_LAB`, HTTP 409, otherwise). A `LabTechnician` starts the test (`AUTHORIZED` → `IN_TEST`) only while fewer than six orders across the laboratory stand in `IN_TEST` — an aggregate capacity cap, not an interval check — otherwise `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409). Result submission by a `LabTechnician` creates a LabTestResult against the order, records the caller's `X-User-ID` as `submitted_by_user_id`, and moves the order from `IN_TEST` to `RESULT_SUBMITTED`; the payload carries whichever of `percent_passing_200` (percent finer than the No. 200 sieve, 0 to 100), `liquid_limit`, `plasticity_index`, `qu_psf` (unconfined compressive strength in psf), and `moisture_content_pct` (gravimetric water content) the test produced, each defaulting to null. Results are listed by `lab_test_order_id`. Disposition belongs to the `LabManager`: acceptance (`RESULT_SUBMITTED` → `ACCEPTED`) applies its side effects below, while rejection (`RESULT_SUBMITTED` → `REJECTED`) starts a limited rerun loop — a `LabTechnician` may return a rejected order to `IN_TEST` while `rerun_count` remains below its cap of 2 and the laboratory capacity check passes (`ERR_RERUN_LIMIT`, HTTP 409, at the cap; `ERR_LAB_CAPACITY_EXCEEDED` when full), and each rerun increments `rerun_count` by 1 from its initial 0.

Acceptance cascades in three directions. First, for a destructive `UNCONFINED_COMPRESSION` or `DIRECT_SHEAR` order, the sample's custody becomes `CONSUMED`. Second, when both the `SIEVE_ANALYSIS` and the `ATTERBERG` order of the same sample stand in `ACCEPTED`, the sample's `uscs_class` is recomputed from the latest accepted results of each type; if the latest accepted sieve result lacks `percent_passing_200`, or the latest accepted Atterberg result lacks `liquid_limit` or `plasticity_index`, no reclassification occurs and `uscs_class` is left unchanged. Third, the project's `testing_invoice_cents` and `total_fee_cents` are recomputed. Rejection cascades as a three-link chain: the sample's `uscs_class` resets to null (link 1); every `VERIFIED` FoundationAnalysis of the project goes `STALE` (link 2, caused by the classification reset); and report issuance is consequently blocked, because sealing requires a verified analysis whose data is current (link 3, §3.6).

The classification itself takes `percent_passing_200` from the latest accepted sieve result — call it F — and `liquid_limit` and `plasticity_index` — LL and PI — from the latest accepted Atterberg result, and compares PI against the A-line value computed as 0.73 times LL-minus-20, evaluated without rounding. When F is below 5, the class is `SW`. When F is at least 5 and at most 12, the class is `SM`. When F is greater than 12 and at most 50 — coarse-grained with fines — the class is `SC` if PI is greater than 7 and `SM` otherwise. When F is strictly greater than 50 the soil is fine-grained: if LL is below 50, the class is `CL` when PI is at least 7 and also at least the A-line value, and `ML` otherwise; if LL is 50 or more, the class is `CH` when PI is at least the A-line value and `MH` otherwise. The boundary is exact: F equal to precisely 50.0 falls in the 12-to-50 coarse-with-fines bucket, because the fine-grained branch requires strictly more than 50. The field's full domain — `GW`, `GP`, `GM`, `GC`, `SW`, `SP`, `SM`, `SC`, `ML`, `CL`, `OL`, `MH`, `CH`, `OH`, `PT`, or null — exceeds what the rule produces; until both result types are accepted, or after either is rejected, `uscs_class` is null.

### 3.5. Foundation Analysis: Provisional Values, Verification, and Staleness

Analysis begins in the field phase and matures with the laboratory. A `SeniorEngineer` creates a FoundationAnalysis while the project stands in `FIELDWORK` or `LAB_ANALYSIS` (else `ERR_PROJECT_STATE_FORBIDS`), choosing a design `method` of `ALLOWABLE_STRESS` or `LRFD`, an optional `fs_required` factor of safety defaulting to 3.0 (strictly positive when supplied), the design `footing_width_ft` (strictly positive), and the `applied_bearing_psf` net bearing demand (non-negative). At creation the server computes `bearing_capacity_provisional_psf` from SPT data alone: four hundred psf per unit of `n60_average`, capped at 8,000 psf and rounded half-up to two decimal places. Here `n60_average` is the mean of `avg_n60` over the active plan's borings standing in `DRILLED`, `LOGGED`, `CLOSED`, or `REFUSED`, recomputed whenever a boring reaches `DRILLED` and itself rounded half-up to two decimal places; if that input set is empty — no boring has drilled data yet — analysis creation is rejected with `ERR_VALIDATION`. The new analysis stands in `PRELIMINARY` with `data_status` equal to `CURRENT`, while `bearing_capacity_final_psf`, `settlement_est_in`, and `deep_foundation_required` remain null until verification. Analyses are listed with a `project_id` filter.

Verification (`PRELIMINARY` → `VERIFIED`) is the `SeniorEngineer`'s act of adopting laboratory strength over correlation. It requires at least one accepted `UNCONFINED_COMPRESSION` order on the project (`ERR_ANALYSIS_NOT_VERIFIED` otherwise) and requires the analysis's `data_status` to be `CURRENT` (`ERR_ANALYSIS_DATA_STALE`, HTTP 409, otherwise). On verification the server takes `qu_psf` from the project's latest accepted unconfined-compression result, halves it for the undrained shear strength, multiplies by nine for the ultimate bearing capacity, and divides by `fs_required`; the quotient is floored at 1,500 psf and capped at 12,000 psf — the stored `bearing_capacity_final_psf` is the smaller of the cap and the larger of the floor and the quotient, rounded half-up to two decimal places. Settlement follows: `settlement_est_in` is the product of `applied_bearing_psf` and `footing_width_ft` divided by the product of 1,200 and `n60_average`, rounded half-up to three decimal places, and `deep_foundation_required` is true exactly when the rounded estimate reaches 1.0 inch — the threshold is inclusive and applied to the stored three-decimal value, so an estimate of precisely 1.000 requires a deep foundation. When `n60_average` is zero the settlement estimate and the deep-foundation flag are not recomputed and retain their prior values. The provisional and final variants deliberately diverge for the same ground: with `n60_average` of 12, `qu_psf` of 4,000, and `fs_required` of 3.0, the provisional value is 4,800 psf while the final value is 6,000 psf. Verification also retires competition: every other `VERIFIED` analysis of the same project transitions to `SUPERSEDED`.

Staleness keeps analysis honest as new data lands. Two events flip a `VERIFIED` analysis's `data_status` to `STALE`: any laboratory order of the project being rejected, and any boring of the project reaching `DRILLED` while the analysis stands verified. A stale analysis cures through a self-loop refresh (`VERIFIED` → `VERIFIED`) performed by a `SeniorEngineer`, permitted only while `data_status` is `STALE` (`ERR_INVALID_STATE` otherwise); the refresh recomputes `bearing_capacity_final_psf` and `settlement_est_in` from current inputs and restores `data_status` to `CURRENT`.

### 3.6. Report Review, Professional Sealing, and Project Issuance

When laboratory work is complete, a `SeniorEngineer` advances the project `LAB_ANALYSIS` → `REPORT_REVIEW`: a FoundationAnalysis of the project must stand in `VERIFIED` with `data_status` equal to `CURRENT` (`ERR_ANALYSIS_NOT_VERIFIED` otherwise), and every laboratory order of the project must stand in `ACCEPTED` (`ERR_ORDER_STATE_FORBIDS` otherwise).

The Report resource captures the deliverable. A `SeniorEngineer` creates a report revision under a project standing in `REPORT_REVIEW` (`ERR_PROJECT_STATE_FORBIDS` otherwise); creation takes no body fields — the report starts in `DRAFT`, receives a `revision_no` one greater than the project's highest existing report revision (starting at 1), and records the caller's `X-User-ID` as `prepared_by_user_id`. Reports are listed with a `project_id` filter. Review is cyclic: the preparer submits the draft to technical review (`DRAFT` → `TECH_REVIEW`; any `SeniorEngineer` may perform this — only the role is checked, never the recorded `prepared_by_user_id`); a `ProjectManager` either returns it for rework (`TECH_REVIEW` → `DRAFT`) or advances it to the PE (`TECH_REVIEW` → `PE_REVIEW`); a `PrincipalEngineer` may reject it back (`PE_REVIEW` → `DRAFT`).

Issuance seals the report. A `PrincipalEngineer` issues a report standing in `PE_REVIEW`, subject to five guards: the issuer's `X-User-ID` must differ from the report's `prepared_by_user_id` — segregation of duties, violated with `ERR_SOD_PE_IS_PREPARER` (HTTP 409); a FoundationAnalysis of the project must stand in `VERIFIED` (`ERR_ANALYSIS_NOT_VERIFIED`); that analysis must carry `data_status` equal to `CURRENT` (`ERR_ANALYSIS_DATA_STALE`); every laboratory order of the project must stand in `ACCEPTED` (`ERR_ORDER_STATE_FORBIDS`); and the request must carry `expected_report_version` equal to the report's current `version` per §2.7 (`ERR_STALE_REPORT_VERSION`, HTTP 412). Issuance sets `sealed_by_pe_user_id` to the issuer and `sealed_at` to the current logical timestamp, transitions any previously `ISSUED` report of the project to `SUPERSEDED`, and increments the report's `version`.

Project issuance follows report issuance: a `ProjectManager` moves the project `REPORT_REVIEW` → `ISSUED` only when the highest-revision Report of the project stands in `ISSUED` (`ERR_REPORT_NOT_ISSUABLE`, HTTP 409, otherwise). If review instead surfaces analytical deficiencies, a `PrincipalEngineer` reopens the analysis scope by sending the project `REPORT_REVIEW` → `LAB_ANALYSIS` — the revision loop of the project machine. Finally, the owning `ClientRep` confirms construction start (`ISSUED` → `CONSTRUCTION_SUPPORT`); the caller's `X-User-ID` must equal the project's `client_id` (`ERR_FORBIDDEN_ROLE` otherwise).

The project's commercial rollups deserve a final statement here, since issuance is the moment they are read together. The `total_fee_cents` recomputes whenever the base fee changes or the testing invoice is recomputed, in a pinned order: first take the project's `testing_invoice_cents`; add it to `base_fee_cents` for the gross; when that gross is at least 500,000 cents, the discount is five percent of the testing invoice rounded half-up to whole cents, and when the gross is below the tier the discount is zero; `total_fee_cents` is the gross minus the discount. The tier test keys on the pre-discount gross, so a project whose gross is exactly 500,000 cents — say a 300,000-cent base fee and a 200,000-cent testing invoice — receives the 10,000-cent discount and lands at 490,000 cents, below the tier it qualified on.

### 3.7. Construction-Phase Observation, Changed-Condition Claims, and Project Closeout

During construction support the firm observes foundation subgrades in the field. A `ProjectManager` schedules an ObservationVisit with a `visit_date` under a project standing in `CONSTRUCTION_SUPPORT` (`ERR_PROJECT_STATE_FORBIDS` otherwise); the visit starts in `SCHEDULED`, and visits are listed with a `project_id` filter. A `StaffEngineer` performs the visit (`SCHEDULED` → `PERFORMED`) once the project stands in `CONSTRUCTION_SUPPORT` (`ERR_PROJECT_STATE_FORBIDS` otherwise) and the current logical time has reached `visit_date` — an early performance is rejected with `ERR_VISIT_DATE_FUTURE` (HTTP 422). A `StaffEngineer` files findings (`PERFORMED` → `FINDINGS_FILED`), recording a `findings` value of `CONSISTENT`, `MARGINAL`, or `DIFFERING` together with the `observed_bearing_psf` of the exposed subgrade (optional; non-negative when supplied, defaulting to null). A `DIFFERING` filing is the first link of the claim-intake cascade: the server automatically opens a ChangedConditionClaim on the project in `SUBMITTED` with `claimed_amount_cents` equal to 0, `basis_text` set to 'Auto-opened from differing-site-condition finding', and `observation_visit_id` pointing at this visit. A `ProjectManager` eventually closes the visit (`FINDINGS_FILED` → `CLOSED`).

Changed-condition claims adjudicate the difference between report and reality. Beyond the automatic intake, a `ProjectManager` or `ClientRep` may file a claim manually under a project in `CONSTRUCTION_SUPPORT` (`ERR_PROJECT_STATE_FORBIDS` otherwise), supplying `claimed_amount_cents` — the contractor's claimed extra cost, which must be non-negative as a body check (`ERR_VALIDATION`) and at least 1 cent for a manual filing (`ERR_CLAIM_AMOUNT_INVALID`, HTTP 422; only auto-opened claims may carry zero) — a narrative `basis_text`, and an optional `observation_visit_id` that must resolve to a visit of the same project (`ERR_VISIT_PROJECT_MISMATCH`, HTTP 422, otherwise). At creation the server snapshots `baseline_bearing_psf` from the project's `VERIFIED` analysis's `bearing_capacity_final_psf`; when no verified analysis exists the snapshot is null. Claims are listed with `project_id` and `observation_visit_id` filters.

A `SeniorEngineer` opens review (`SUBMITTED` → `UNDER_REVIEW`), which computes both quantum variants. Let B be the claim's `baseline_bearing_psf` and O the observed bearing: the linked visit's `observed_bearing_psf` when `observation_visit_id` is set, otherwise the `observed_bearing_psf` of the project's most recent visit in `FINDINGS_FILED` chosen by `visit_date` with ties broken by the earliest `created_at`. If B is null, or O is null, or O is greater than or equal to B, both quanta are zero. Otherwise the shortfall is the difference between B and O divided by B, evaluated without rounding. The report-baseline variant stores `quantum_report_baseline_cents` as the claimed amount multiplied by the shortfall capped at one-half, rounded half-up to whole cents — at most fifty percent of the claim is recoverable on the report's numbers. The site-observed variant stores `quantum_site_observed_cents` as the claimed amount multiplied by the shortfall scaled by 1.25 and capped at three-quarters, rounded half-up to whole cents — an aggravation multiplier with a higher ceiling, so identical inputs yield a different figure: a baseline of 6,000 psf, an observed 4,000 psf, and a claim of 120,000 cents produce 40,000 cents report-baseline against 50,000 cents site-observed. Entering review also recomputes the project's `claims_exposure_cents` (link 1) and its `posture`, which becomes `CLAIM_REVIEW` while any claim stands in `UNDER_REVIEW` or `SUBSTANTIATED` (link 2).

Review concludes in one of three directions. Substantiation (`UNDER_REVIEW` → `SUBSTANTIATED`, by a `SeniorEngineer`) requires the baseline snapshot to exist (`ERR_ANALYSIS_NOT_VERIFIED` when it is null). Rebuttal (`UNDER_REVIEW` → `REBUTTED`, same actor) needs no guard beyond the from-state. A rebutted claim may be appealed back into review exactly once (`REBUTTED` → `UNDER_REVIEW`, by a `SeniorEngineer`): the attempt requires `appeal_count` still below its cap of 1, drawing `ERR_APPEAL_LIMIT` (HTTP 409) at the cap, and re-entry increments `appeal_count` from its initial 0 and recomputes both quanta. Settlement (`SUBSTANTIATED` → `SETTLED`) belongs to the `ProjectManager`, who supplies an `awarded_amount_cents` that must be non-negative (`ERR_VALIDATION` otherwise) and which is recorded on the claim. Every one of these transitions recomputes the project's exposure and posture.

The exposure rollup is precise: `claims_exposure_cents` sums `claimed_amount_cents` over claims in `UNDER_REVIEW` and `quantum_report_baseline_cents` over claims in `SUBSTANTIATED`; claims in `SUBMITTED`, `REBUTTED`, or `SETTLED` contribute zero. Rebuttal therefore zeroes a claim's contribution, substantiation switches it from the claimed amount to the report-baseline quantum, settlement drops it out entirely, and appeal re-entry restores the claimed amount.

Closeout is guarded. A `ProjectManager` moves the project `CONSTRUCTION_SUPPORT` → `CLOSED` — its terminal state — only when no claim of the project stands in `SUBMITTED`, `UNDER_REVIEW`, or `SUBSTANTIATED` (`ERR_CLAIM_STATE_FORBIDS` otherwise; rebutted and settled claims do not block) and every ObservationVisit of the project stands in `CLOSED` (`ERR_INVALID_STATE` otherwise). With that transition the engagement ends: scope, fieldwork, laboratory, analysis, report, and claims all reconciled.

## 4. Endpoint Definitions

Operations that create a new resource — a client, project, plan revision, subcontractor, rig assignment, boring, offset, clearance ticket, sample, laboratory order, result, analysis, report, visit, claim, or authorization — return `201 Created`. Operations that read, transition, or otherwise modify an existing resource return `200 OK`. The request and response details of each operation are governed by the workflows of §3; this table is an index, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/geo/clients` | Create a client | FirmAdmin |
| GET | `/geo/clients/{id}` | Fetch a client | FirmAdmin, ProjectManager, ClientRep, SeniorEngineer |
| POST | `/geo/projects` | Create a project for a client | FirmAdmin |
| GET | `/geo/projects/{id}` | Fetch a project including computed posture, exposure, invoice, and fee fields | FirmAdmin, ProjectManager, StaffEngineer, FieldGeologist, SeniorEngineer, PrincipalEngineer, LabManager, LabTechnician, ClientRep, DrillingSub |
| GET | `/geo/projects` | List projects; optional `client_id` filter | FirmAdmin, ProjectManager, SeniorEngineer, ClientRep |
| POST | `/geo/projects/{id}/transition` | Drive the Project lifecycle machine; body field `to` names the target state | ProjectManager, SeniorEngineer, PrincipalEngineer, ClientRep |
| POST | `/geo/projects/{id}/boring-plans` | Create a new boring plan revision (OCC-guarded on the project's version) | StaffEngineer |
| GET | `/geo/boring-plans/{id}` | Fetch a boring plan | FirmAdmin, ProjectManager, StaffEngineer, SeniorEngineer, PrincipalEngineer |
| GET | `/geo/boring-plans` | List boring plans; filters `project_id` and/or `supersedes_plan_id` | FirmAdmin, ProjectManager, StaffEngineer, SeniorEngineer |
| POST | `/geo/boring-plans/{id}/transition` | Drive the BoringPlan machine (submit, return to draft, approve) | StaffEngineer, ProjectManager |
| POST | `/geo/subcontractors` | Register a drilling subcontractor | FirmAdmin |
| GET | `/geo/subcontractors/{id}` | Fetch a subcontractor including `committed_rig_hours` | FirmAdmin, ProjectManager, DrillingSub |
| POST | `/geo/subcontractors/{id}/transition` | Set standing `SUSPENDED` or `GOOD_STANDING` | FirmAdmin |
| POST | `/geo/borings/{id}/rig-assignments` | Schedule a rig window for a boring; half-open overlap check per subcontractor | ProjectManager |
| GET | `/geo/rig-assignments/{id}` | Fetch a rig assignment | FirmAdmin, ProjectManager, DrillingSub |
| GET | `/geo/rig-assignments` | List rig assignments; filters `boring_id` and/or `subcontractor_id` | FirmAdmin, ProjectManager, DrillingSub |
| POST | `/geo/rig-assignments/{id}/transition` | Drive the RigAssignment machine (mobilize, demobilize, cancel) | DrillingSub, ProjectManager |
| POST | `/geo/boring-plans/{id}/borings` | Add a boring to an `APPROVED` plan | StaffEngineer |
| GET | `/geo/borings/{id}` | Fetch a boring | FirmAdmin, ProjectManager, StaffEngineer, FieldGeologist, DrillingSub, SeniorEngineer |
| GET | `/geo/borings` | List borings; filters `boring_plan_id` and/or `offset_of_boring_id` | FirmAdmin, ProjectManager, StaffEngineer, FieldGeologist, DrillingSub, SeniorEngineer |
| POST | `/geo/borings/{id}/transition` | Drive the Boring machine (clear, drill, log, close, refuse, abandon) | StaffEngineer, FieldGeologist, DrillingSub, ProjectManager |
| POST | `/geo/borings/{id}/offsets` | Create an offset boring for a `REFUSED` boring; consumes extra-exploration authorization when beyond planned count | StaffEngineer |
| POST | `/geo/borings/{id}/clearances` | File a utility clearance ticket for a boring | StaffEngineer |
| GET | `/geo/clearances/{id}` | Fetch a clearance ticket | FirmAdmin, ProjectManager, StaffEngineer |
| GET | `/geo/clearances` | List clearance tickets; filter `boring_id` | FirmAdmin, ProjectManager, StaffEngineer |
| POST | `/geo/clearances/{id}/transition` | Drive the clearance machine (`CLEARED`, `CONFLICT_MARKED`); `EXPIRED` is system-only | StaffEngineer, ProjectManager |
| POST | `/geo/borings/{id}/samples` | Log a sample from a drilled (or logged) boring | FieldGeologist |
| GET | `/geo/samples/{id}` | Fetch a sample including computed `uscs_class` | FirmAdmin, ProjectManager, StaffEngineer, FieldGeologist, LabManager, LabTechnician, SeniorEngineer |
| GET | `/geo/samples` | List samples; filter `boring_id` | FirmAdmin, ProjectManager, StaffEngineer, FieldGeologist, LabManager, LabTechnician, SeniorEngineer |
| POST | `/geo/samples/{id}/transition` | Drive the custody machine (ship, receive, report lost, archive) | FieldGeologist, LabTechnician, LabManager |
| POST | `/geo/projects/{id}/lab-test-orders` | Order a laboratory test on a sample; per-line fee computed at creation | LabManager |
| GET | `/geo/lab-test-orders/{id}` | Fetch a laboratory test order | FirmAdmin, ProjectManager, LabManager, LabTechnician, SeniorEngineer |
| GET | `/geo/lab-test-orders` | List laboratory test orders; filters `project_id` and/or `sample_id` | FirmAdmin, ProjectManager, LabManager, LabTechnician, SeniorEngineer |
| POST | `/geo/lab-test-orders/{id}/transition` | Drive the order machine (authorize, start, accept, reject, rerun) | LabManager, LabTechnician |
| POST | `/geo/lab-test-orders/{id}/results` | Submit a laboratory result; the order moves from `IN_TEST` to `RESULT_SUBMITTED` | LabTechnician |
| GET | `/geo/lab-test-results/{id}` | Fetch a laboratory result | FirmAdmin, ProjectManager, LabManager, LabTechnician, SeniorEngineer |
| GET | `/geo/lab-test-results` | List laboratory results; filter `lab_test_order_id` | FirmAdmin, ProjectManager, LabManager, LabTechnician, SeniorEngineer |
| POST | `/geo/projects/{id}/foundation-analyses` | Create a foundation analysis; provisional bearing capacity computed at creation | SeniorEngineer |
| GET | `/geo/foundation-analyses/{id}` | Fetch an analysis | FirmAdmin, ProjectManager, SeniorEngineer, PrincipalEngineer |
| GET | `/geo/foundation-analyses` | List analyses; filter `project_id` | FirmAdmin, ProjectManager, SeniorEngineer, PrincipalEngineer |
| POST | `/geo/foundation-analyses/{id}/transition` | Drive the analysis machine (`VERIFIED`, including the self-loop refresh) | SeniorEngineer |
| POST | `/geo/projects/{id}/reports` | Create a report revision (`DRAFT`) under a `REPORT_REVIEW` project | SeniorEngineer |
| GET | `/geo/reports/{id}` | Fetch a report | FirmAdmin, ProjectManager, SeniorEngineer, PrincipalEngineer, ClientRep |
| GET | `/geo/reports` | List reports; filter `project_id` | FirmAdmin, ProjectManager, SeniorEngineer, PrincipalEngineer, ClientRep |
| POST | `/geo/reports/{id}/transition` | Drive the report review machine (technical review, PE review, return to draft) | SeniorEngineer, ProjectManager, PrincipalEngineer |
| POST | `/geo/reports/{id}/issue` | PE seals and issues a `PE_REVIEW` report (OCC plus segregation of duties) | PrincipalEngineer |
| POST | `/geo/projects/{id}/observation-visits` | Schedule a construction-phase observation visit | ProjectManager |
| GET | `/geo/observation-visits/{id}` | Fetch a visit | FirmAdmin, ProjectManager, StaffEngineer, SeniorEngineer |
| GET | `/geo/observation-visits` | List visits; filter `project_id` | FirmAdmin, ProjectManager, StaffEngineer, SeniorEngineer |
| POST | `/geo/observation-visits/{id}/transition` | Drive the visit machine (perform, file findings, close) | StaffEngineer, ProjectManager |
| POST | `/geo/projects/{id}/claims` | File a changed-condition claim; baseline bearing snapshot taken at creation | ProjectManager, ClientRep |
| GET | `/geo/claims/{id}` | Fetch a claim including both quantum variants | FirmAdmin, ProjectManager, SeniorEngineer, ClientRep |
| GET | `/geo/claims` | List claims; filters `project_id` and/or `observation_visit_id` | FirmAdmin, ProjectManager, SeniorEngineer, ClientRep |
| POST | `/geo/claims/{id}/transition` | Drive the claim machine (review, substantiate, rebut, appeal, settle) | SeniorEngineer, ProjectManager |
| POST | `/geo/projects/{id}/exploration-authorizations` | Propose an additional exploration authorization | ProjectManager |
| GET | `/geo/exploration-authorizations/{id}` | Fetch an authorization | FirmAdmin, ProjectManager, ClientRep |
| GET | `/geo/exploration-authorizations` | List authorizations; filter `project_id` | FirmAdmin, ProjectManager, ClientRep |
| POST | `/geo/exploration-authorizations/{id}/transition` | ClientRep approves or revokes (OCC-guarded on the project's version) | ClientRep |
| POST | `/geo/_clock/set_current_utc` | Test-driving capability: set the logical clock; advancing triggers clearance expiry sweeps | FirmAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the workflow narratives of §2 and §3; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROJECT_STATE_FORBIDS` | 409 |
| `ERR_RIG_NOT_MOBILIZED` | 409 |
| `ERR_SAMPLE_NOT_IN_LAB` | 409 |
| `ERR_ANALYSIS_NOT_VERIFIED` | 409 |
| `ERR_ANALYSIS_DATA_STALE` | 409 |
| `ERR_REPORT_NOT_ISSUABLE` | 409 |
| `ERR_CLAIM_STATE_FORBIDS` | 409 |
| `ERR_ORDER_STATE_FORBIDS` | 409 |
| `ERR_CLEARANCE_MISSING` | 409 |
| `ERR_CLEARANCE_EXPIRED` | 409 |
| `ERR_POSTURE_FROZEN` | 409 |
| `ERR_PLAN_ALREADY_ACTIVE` | 409 |
| `ERR_PLAN_NOT_EDITABLE` | 409 |
| `ERR_RIG_DOUBLE_BOOKED` | 409 |
| `ERR_STANDING_SUSPENDED` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_RERUN_LIMIT` | 409 |
| `ERR_SOD_PE_IS_PREPARER` | 409 |
| `ERR_DUPLICATE_TICKET` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_VISIT_DATE_FUTURE` | 422 |
| `ERR_SAMPLE_PROJECT_MISMATCH` | 422 |
| `ERR_VISIT_PROJECT_MISMATCH` | 422 |
| `ERR_OFFSET_PARENT_NOT_REFUSED` | 422 |
| `ERR_AUTH_CAP_EXCEEDED` | 422 |
| `ERR_EXTRA_BORINGS_EXHAUSTED` | 422 |
| `ERR_CLAIM_AMOUNT_INVALID` | 422 |
| `ERR_APPEAL_LIMIT` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_REPORT_VERSION` | 412 |
