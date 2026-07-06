# Pool Construction API — Product Requirements Document

## 1. Introduction

Building or remodeling an in-ground swimming pool is a months-long general-contracting effort that threads design and permitting through a strict physical construction sequence — excavation, steel, plumbing, gunite, and finally plaster — while money, inspections, and independent crews all move in lockstep with that sequence. The purpose of this API is to give a pool builder a single system of record that keeps the paperwork, the field work, and the checkbook consistent with one another: a homeowner's contract cannot be over-drawn, a phase cannot begin before the one beneath it has passed inspection, a permit cannot be skipped, and a safety defect discovered in the field can freeze the entire job until it is cleared.

The platform coordinates five kinds of participants. A builder's project manager owns the job record, opens the construction phases, books crews, applies change orders, and funds progress draws. A designer produces the pool design and drives the permit submission. The homeowner approves the design, decides change orders and draws, and ultimately accepts the finished pool. A municipal or QA inspector issues the permit and records the pass/fail outcome of each phase inspection. Finally, each subcontracting company acts only on the crew bookings that belong to it. The sections below define the shared API contract first, then the domain workflows that tie these participants together, and finally the exhaustive endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Authentication, and Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting as. The recognized roles are exactly `BuilderPM`, `Designer`, `Owner`, `Inspector`, and `Subcontractor`. A request whose `X-User-Role` header is missing or does not name one of these five roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Only the `X-User-Role` header governs authentication; a missing or empty `X-User-ID` does not by itself trigger `ERR_UNAUTHENTICATED`, and `X-User-ID` is consulted only by the `Owner` and `Subcontractor` ownership checks below, so its absence surfaces (if at all) as an `ERR_FORBIDDEN` when one of those checks runs. A request that authenticates successfully but whose role is not permitted to perform the requested operation — or that fails an ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles differ in how `X-User-ID` relates to persisted data:

- When `X-User-Role` is `BuilderPM`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `Designer`, `X-User-ID` is likewise an opaque operator identifier that the server does not compare to any entity's `id`.
- When `X-User-Role` is `Inspector`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity and not compared to any entity's `id`.
- When `X-User-Role` is `Owner`, `X-User-ID` is an opaque homeowner identifier. It is not an entity `id`; instead, ownership is enforced by comparing `X-User-ID` to the `owner_user_id` value recorded on the project the request touches. An `Owner` whose `X-User-ID` does not equal the target project's `owner_user_id` is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting `Subcontractor`. Ownership checks on any crew booking compare that booking's `subcontractor_id` field to `X-User-ID`; a `Subcontractor` acting on a booking whose `subcontractor_id` is not its own `X-User-ID` is rejected with `ERR_FORBIDDEN`.

Read operations (all single-resource reads and all list endpoints) are available to every one of the five roles. Write operations are restricted to specific roles as detailed in §3 and summarized in the §4 authorization column.

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

Every collection resource is peer-mounted under the shared `/pool-build` prefix; there are no nested ownership URLs. A child is instead discovered by filtering a collection on a foreign-key query parameter. Design plans, phase gates, change orders, punch items, and draw requests each accept an optional `pool_project_id` filter; inspections and draw requests additionally accept a `phase_gate_id` filter; crew assignments accept any combination of `pool_project_id`, `subcontractor_id`, and `phase_gate_id`. Inspections may be filtered by both `pool_project_id` and `phase_gate_id` together. When a filter is supplied, only resources whose corresponding foreign key equals the supplied value are returned.

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. Values outside these bounds are clamped to the nearest bound rather than rejected, and a non-integer or otherwise unparseable `limit`/`offset` silently falls back to its default. Results are always sorted by `created_at` in ascending order (oldest first), with ties on an identical `created_at` broken by ascending creation order (the order in which the resources were persisted). The pagination fields `limit`, `offset`, `total_count`, and `has_more` are returned inside the `meta` object of a list response, where `total_count` reflects the full count of matching resources before the limit/offset window is applied and `has_more` is true when resources remain beyond the current window.

### 2.4. Common Resource Properties and Entity Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version`. When a resource is first created its `version` is 1. Mutating that resource's own stored fields — a state transition or a stored-field update — advances `updated_at` to the time of the change and increments `version` by 1. Derived and computed fields (postures, ledger balances, the `current_phase`/`design_status` projections, `committed_crew_hours`, reliability scores, and `inspection_attempts`) are recomputed lazily whenever the resource is read and do not by themselves advance `updated_at` or `version`. Certain cross-entity operations described in §3 additionally bump the `version` of a *related* resource (most importantly the project record); those bumps are called out explicitly where they occur. The `PoolProject` is the sole exception to the stored-field rule above: its `version` advances only on those explicit ledger-affecting bumps — draw creation, draw funding, change-order application, and change-order reversal (§2.5) — while the project's own `construction_status` lifecycle transitions advance `updated_at` only and leave `version` unchanged.

### 2.5. Optimistic Concurrency Control on the Project Ledger

Creating a progress draw is the one write in this system guarded by optimistic concurrency control against the project. A create-draw request must include a non-optional `expected_pool_project_version` field carrying the client's last observed `version` of the target `PoolProject`. Before the draw is created, the server compares `expected_pool_project_version` to the project's current `version`. If they do not match — because some earlier write (a prior draw creation, a change-order application or reversal, or a draw funding, each of which advances the project `version`) has moved the project's `contract_amount_cents` or `amount_remaining_cents` since the client last read it — the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and the client must re-read the project before retrying so that it is not billing against a stale view of the fundable ceiling. No other write in the system accepts a project-version field; only the create-draw operation carries `expected_pool_project_version`.

### 2.6. Request Validation Order

When more than one thing is wrong with a request, the server reports the failure that comes first in the following fixed precedence, so that outcomes are deterministic regardless of how many rules a request violates:

1. **Authentication** — `X-User-Role` present and recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization and ownership** — the role is permitted for this operation, and any `Owner` or `Subcontractor` ownership check holds, else `ERR_FORBIDDEN` (403). The role-permission part of this step runs before existence; but an `Owner`/`Subcontractor` ownership check is evaluated against the resolved target resource, so it runs only after that resource's existence has been confirmed (step 3) — though still before body validity (step 4) — which means acting on a non-existent target yields `ERR_NOT_FOUND` (404), not `ERR_FORBIDDEN`.
3. **Existence** — every id, whether a path id or a foreign-key id in the request body, resolves to an existing resource. Ids are resolved left-to-right in the order they appear, and the first unresolved id yields `ERR_NOT_FOUND` (404).
4. **Body validity** — required body fields are present, enum-typed fields carry a legal value, numeric fields that must be positive are greater than zero, else `ERR_VALIDATION` (422). For a crew booking specifically, `end_at` must be strictly after `start_at`; when it is not, the dedicated code `ERR_INVALID_INTERVAL` (422) is returned.
5. **State legality** — for a transition endpoint, the target resource is in a state from which the requested transition is legal, else `ERR_INVALID_STATE` (409).
6. **Optimistic concurrency** — for create-draw, `expected_pool_project_version` matches the project's current `version`, else `ERR_STALE_PROJECT_VERSION` (412).
7. **Posture: stop-work** — a `STOP_WORK` posture does not block this operation, else `ERR_POSTURE_STOP_WORK` (409).
8. **Posture: hold** — a `HOLD` posture does not block this operation, else `ERR_POSTURE_HOLD` (409).
9. **Crew double-booking**, then **site occupancy**, then **cure buffer** — the three temporal scheduling checks for a crew booking, in that order, yielding `ERR_SUBCONTRACTOR_DOUBLE_BOOKED`, `ERR_SITE_OCCUPIED`, and `ERR_CURE_BUFFER` respectively (all 409).
10. **Referential preconditions** — permit issuance and phase-sequence/phase-status rules, yielding `ERR_PERMIT_NOT_ISSUED`, `ERR_PHASE_SEQUENCE`, `ERR_PHASE_NOT_ACTIVE`, or `ERR_PHASE_NOT_PASSED` (all 409).
11. **Uniqueness and eligibility guards** — duplicate design/phase guards and sub/design/change-order eligibility, yielding `ERR_DESIGN_ALREADY_EXISTS`, `ERR_PHASE_ALREADY_EXISTS`, `ERR_SUBCONTRACTOR_INACTIVE`, `ERR_PHASE_NOT_IN_PROGRESS`, `ERR_DESIGN_NOT_APPROVED`, or `ERR_CHANGE_ORDER_NOT_APPROVED` (all 409).
12. **Fiscal limits** — the draw-funding contract ceiling and the project-close punch-list rule, yielding `ERR_DRAW_EXCEEDS_CONTRACT` or `ERR_OPEN_PUNCH_ITEMS` (both 409), checked last of all.

The intent of this ordering is that structural problems (who you are, whether the thing exists, whether the body is shaped correctly) are always reported before domain problems, and among domain problems the physical and safety gates are reported before the money gates.

### 2.7. The Project Posture Gate

Each `PoolProject` carries a computed `posture` that acts as a master gate over field work. `posture` is one of `OPEN`, `HOLD`, or `STOP_WORK`, and it is re-derived every time a phase gate's status changes, an inspection is recorded, a punch item is created or resolved, a draw is funded, or a change order is applied or reversed. The value is decided by evaluating the following rules in order and taking the first that matches:

1. If any phase gate on the project has status `FAILED`, the posture is `STOP_WORK`.
2. Otherwise, if any punch item on the project is `OPEN` with severity `SAFETY`, the posture is `STOP_WORK`.
3. Otherwise, if the project's `amount_remaining_cents` is less than zero, the posture is `STOP_WORK`.
4. Otherwise, if any punch item on the project is `OPEN` with severity `MAJOR`, the posture is `HOLD` — a major defect holds new field work but is not a full stop.
5. Otherwise, the posture is `OPEN`.

An `OPEN` punch item of severity `MINOR` never affects posture. A `STOP_WORK` posture blocks four field operations: starting a phase, scheduling an inspection, booking a crew, and creating a draw. A `HOLD` posture is narrower — it blocks only starting a phase and booking a crew, and it never blocks inspection scheduling or draw creation. Where a posture check fails, a `STOP_WORK` posture reports `ERR_POSTURE_STOP_WORK` and a `HOLD` posture reports `ERR_POSTURE_HOLD` (both 409). The single exception to the stop-work block, described in §3.3, is the rework of the very gate whose failure caused the stop.

### 2.8. Ledger Conservation and Numeric Precision

The project record maintains a small ledger of computed integer-cent fields — `contract_amount_cents`, `amount_disbursed_cents`, `retainage_held_cents`, and `amount_remaining_cents` — whose exact derivations live in §3.1, §3.6, and §3.7. These four quantities are conserved: at all times `amount_remaining_cents` equals `contract_amount_cents` minus `amount_disbursed_cents` minus `retainage_held_cents`, so that the contract amount is always fully accounted for as the sum of what has been disbursed, what is held back as retainage, and what remains available.

All monetary quantities are integer numbers of cents. Wherever a rule multiplies a cent amount by a factor or a percentage — a phase budget by a completion factor, an eligible amount by the retainage percentage, a price delta by a discount — the product is rounded to the nearest whole cent using round-half-up (a value ending in exactly half a cent rounds up), at the point the rule specifies and before any subsequent step consumes it. Crew durations and their running totals are expressed in hours to two decimal places, also rounded half-up. Subcontractor reliability scores are whole integers from 0 to 100, rounded half-up.

### 2.9. The Logical Construction Clock

All interval, overlap, and cure-buffer reasoning about crew bookings is computed directly from the bookings' own supplied `start_at`/`end_at` endpoints compared against one another, never from real wall-clock time. Before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. An admin-only test-driving capability, available to `BuilderPM`, sets the logical clock to the instant supplied in the `to_iso8601` field, which is required and must parse as an ISO 8601 datetime (else `ERR_VALIDATION`); the §4 table lists the exact route. The logical clock is retained but is not consulted by any scheduling check, so setting it does not by itself alter any scheduling outcome.

## 3. Business Logic & Workflows

Throughout the workflows below, every lifecycle-transition request selects the operation it performs through an `action` field in its body (the one exception is recording an inspection result, which uses an `outcome` field instead); the specific value expected for each move is named as that move is introduced.

### 3.1. Project Intake and Ledger Initialization

A job begins when a `BuilderPM` creates a `PoolProject`. The intake payload supplies the homeowner display name `owner_name`, the opaque `owner_user_id` that the homeowner will later authenticate against as the `Owner` role, the build site's `site_address`, the signed base `contract_price_cents` (which must be greater than zero), and the design water volume `pool_gallons` that will drive chemical dosing at startup. The `pool_type` field may be supplied as either `GUNITE` or `REMODEL`; when it is omitted it defaults to `GUNITE`.

At creation the project's `construction_status` is `NOT_STARTED` and its `version` is 1. The ledger is seeded so that `contract_amount_cents` equals the signed `contract_price_cents`, `amount_disbursed_cents` and `retainage_held_cents` are both zero, and `amount_remaining_cents` therefore equals the full `contract_price_cents`. With no design filed yet the project's `design_status` is `NO_DESIGN`, and with no failed gates, no open safety or major punch items, and a non-negative balance, its `posture` is `OPEN`. The project's `current_phase` is `NONE` until construction phases exist. Reading a project returns all of these fields, including the live computed ledger, posture, phase, and version values.

The project's lifecycle `construction_status` moves through `NOT_STARTED`, `IN_CONSTRUCTION`, `STARTUP_READY`, `ORIENTED`, and finally the terminal `CLOSED`. The system advances it from `NOT_STARTED` to `IN_CONSTRUCTION` automatically the first time any phase gate leaves `PENDING` for `IN_PROGRESS`. The remaining lifecycle steps — the system-driven arrival at `STARTUP_READY`, the builder's orientation handoff to `ORIENTED`, and the owner's acceptance into `CLOSED` — are described in §3.8.

### 3.2. Design Rendering and the Permit Track

A `Designer` opens the project's single `DesignPlan` by submitting the owning `pool_project_id` together with the pool geometry: `length_ft`, `width_ft`, and `avg_depth_ft`, each a positive number of feet. At most one design plan may exist per project; a second attempt is rejected with `ERR_DESIGN_ALREADY_EXISTS`. A new plan starts with its design `status` at `DRAFT`, its `permit_status` at `NONE`, and its `revision_count` at 0.

A design plan tracks two independent dimensions on the same record. The **design track** (`status`) runs `DRAFT` → `RENDERED_3D` → `OWNER_APPROVED` and may cycle backward. The `Designer` renders the draft, advancing the plan from `DRAFT` to `RENDERED_3D`. The homeowner then either approves it, advancing `RENDERED_3D` to `OWNER_APPROVED`, or sends it back for revision. A revision request from `RENDERED_3D` returns the plan to `DRAFT` and adds one to `revision_count`. The homeowner may also request a revision of an already-approved plan, returning `OWNER_APPROVED` to `DRAFT` and again adding one to `revision_count` — but only while the plan's `permit_status` is `NONE` or `REJECTED`; a design whose permit is `SUBMITTED` or `ISSUED` cannot be revised, and the attempt is rejected with `ERR_INVALID_STATE`.

The **permit track** (`permit_status`) runs independently and begins only once the design is approved. The `Designer` submits for permit, which requires the design `status` to be `OWNER_APPROVED` — otherwise `ERR_DESIGN_NOT_APPROVED` — and moves `permit_status` from `NONE` to `SUBMITTED`, recording the permitting authority in the optional `jurisdiction` field when it is supplied (it is left null if omitted). An `Inspector` then rules on the submission: issuing the permit advances `SUBMITTED` to `ISSUED` and stamps the optional `permit_number` when it is supplied (it remains null if omitted), while rejecting it advances `SUBMITTED` to `REJECTED`. After a rejection the `Designer` may resubmit — permitted while the design remains `OWNER_APPROVED` — which moves `permit_status` from `REJECTED` back to `SUBMITTED` to await the inspector's re-decision.

The project's `design_status` is a projection of this single plan, recomputed on plan creation and on every plan transition. When no design plan exists, `design_status` is `NO_DESIGN`. While the plan sits in `DRAFT` and has never yet been rendered — that is, its `revision_count` is still 0 — `design_status` also reads `NO_DESIGN`; once the plan has reached `RENDERED_3D`, or has been rendered before and cycled back to `DRAFT` for revision, `design_status` reads `IN_DESIGN`. When the plan is `OWNER_APPROVED` but its `permit_status` is not yet `ISSUED`, `design_status` is `DESIGN_APPROVED`. When the plan is `OWNER_APPROVED` and its `permit_status` is `ISSUED`, `design_status` rolls all the way up to `PERMITTED`. Issuing the permit is therefore the event that unblocks construction; rejecting it, or an owner revision that drops an approved design back to draft, rolls `design_status` back below `PERMITTED` and re-blocks phase work.

### 3.3. Phase Gates and the Construction Pipeline

Construction is organized as five sequential `PhaseGate` records, one per phase, created by the `BuilderPM`. Creating a gate supplies the owning `pool_project_id`, the `phase` — one of `EXCAVATION`, `STEEL`, `PLUMBING`, `GUNITE`, or `PLASTER` — and the `budget_cents` allocated to that phase, which is the draw ceiling for it. A gate may be created only once the project's `design_status` is `PERMITTED`; an attempt made before the permit is issued is rejected with `ERR_PERMIT_NOT_ISSUED`. Each phase may appear at most once per project; a duplicate is rejected with `ERR_PHASE_ALREADY_EXISTS`. On creation the gate's `status` is `PENDING`, and its `sequence_index` is derived from the phase: `EXCAVATION` is 1, `STEEL` is 2, `PLUMBING` is 3, `GUNITE` is 4, and `PLASTER` is 5. A gate's `inspection_attempts` counter begins at 0.

Starting a phase advances a gate from `PENDING` to `IN_PROGRESS`, and it is the most heavily guarded field action. It requires, first, that the project posture is `OPEN`: a `STOP_WORK` posture rejects the start with `ERR_POSTURE_STOP_WORK` and a `HOLD` posture rejects it with `ERR_POSTURE_HOLD`. It requires, second, that the project's `design_status` is `PERMITTED`, else `ERR_PERMIT_NOT_ISSUED`. It requires, third, that every phase gate on the project with a lower `sequence_index` than this one already has status `PASSED`; if any lower phase is unfinished the start is rejected with `ERR_PHASE_SEQUENCE`. On a successful start the gate becomes `IN_PROGRESS`, the project's `construction_status` becomes `IN_CONSTRUCTION` if it was still `NOT_STARTED`, and the project's `current_phase` is recomputed.

A gate that has failed inspection can be reworked, which also drives it to `IN_PROGRESS`, this time from `FAILED`. Rework still requires that every lower-sequence gate is `PASSED`. Its posture rule is deliberately narrower than an initial start: the only stop-work condition exempted is this gate's own `FAILED` status, since that is exactly what the rework is meant to clear. If, setting aside this gate's own failure, the project would still be in `STOP_WORK` for any other reason — a *different* gate is also `FAILED`, an `OPEN` `SAFETY` punch item exists, or `amount_remaining_cents` has gone negative — the rework is rejected with `ERR_POSTURE_STOP_WORK`. When rework succeeds the gate returns to `IN_PROGRESS` and the project posture is recomputed, at which point the stop-work caused by this gate lifts.

The project's `current_phase` is a projection over all of a project's gates ordered by `sequence_index`, recomputed whenever a phase is started or an inspection passes. If the project has no phase gates, `current_phase` is `NONE`. If every gate is `PASSED`, `current_phase` is `STARTUP`. Otherwise it is the `phase` of the gate with the lowest `sequence_index` whose status is not `PASSED`.

### 3.4. Inspection Milestones and Gate Outcomes

Progress on an in-flight phase is certified through an `Inspection`. An `Inspector` schedules one by supplying the `pool_project_id`, the `phase_gate_id` of the phase being inspected, the `inspector_name`, and the `scheduled_at` instant (ISO 8601 UTC). Scheduling requires the target gate to be `IN_PROGRESS`; if it is in any other state the request is rejected with `ERR_PHASE_NOT_IN_PROGRESS`. Because scheduling immediately moves the gate from `IN_PROGRESS` to `INSPECTION_PENDING`, this same rule prevents a second, overlapping inspection from being opened on a gate that already has one in flight. Scheduling an inspection is a field operation blocked by a `STOP_WORK` posture (with `ERR_POSTURE_STOP_WORK`) but not by a `HOLD` posture. A new inspection's `status` is `SCHEDULED`.

The inspector later records the outcome, optionally attaching `result_notes`. Recording carries an `outcome` of `PASS`, `FAIL`, or `CANCEL`, and each outcome cascades to the underlying gate. A `PASS` moves the inspection from `SCHEDULED` to `PASSED` and drives the gate from `INSPECTION_PENDING` to `PASSED`, adding one to the gate's `inspection_attempts`, recomputing the project's `current_phase`, and — when the gate that just passed is `PLASTER` and every gate on the project is now `PASSED` — carrying the project into `STARTUP_READY` as described in §3.8. A `FAIL` moves the inspection from `SCHEDULED` to `FAILED` and drives the gate from `INSPECTION_PENDING` to `FAILED`, adding one to `inspection_attempts`, and forces the project posture to `STOP_WORK` (matching posture rule 1). A `CANCEL` moves the inspection from `SCHEDULED` to `CANCELLED` and returns the gate from `INSPECTION_PENDING` to `IN_PROGRESS` without counting an attempt, so a cancelled inspection leaves `inspection_attempts` untouched. The `PASSED`, `FAILED`, and `CANCELLED` inspection states are terminal.

### 3.5. Subcontractor Roster and Crew Coordination

Crews come from `Subcontractor` companies, registered by the `BuilderPM` with a `company_name` and a `trade` — one of `EXCAVATOR`, `STEEL`, `PLUMBER`, `GUNITE`, `PLASTER`, or `GENERAL`. A newly registered sub has `status` `ACTIVE` and `committed_crew_hours` of 0. The builder may suspend a sub, moving `ACTIVE` to `SUSPENDED`, and later reactivate it, moving `SUSPENDED` back to `ACTIVE`. A booking that references a `SUSPENDED` sub is rejected with `ERR_SUBCONTRACTOR_INACTIVE`.

A `CrewAssignment` books one sub to one phase for one time interval and is created by the `BuilderPM`. The booking payload names the `pool_project_id` of the site, the `subcontractor_id` of the crew, the `phase_gate_id` of the phase, and the interval endpoints `start_at` (inclusive) and `end_at` (exclusive). `end_at` must be strictly after `start_at`, else `ERR_INVALID_INTERVAL`. The booking's `duration_hours` is computed as the total seconds between `start_at` and `end_at` divided by 3600, expressed in hours to two decimal places. A new booking's `status` is `SCHEDULED`. Booking is a field operation blocked by both postures: a `STOP_WORK` project rejects it with `ERR_POSTURE_STOP_WORK` and a `HOLD` project rejects it with `ERR_POSTURE_HOLD`.

Three temporal guards apply to a new booking, evaluated in this order. First, the interval must not overlap any other non-`CANCELLED` booking of the *same* subcontractor; treating the interval as half-open, exact adjacency where one booking's end equals another's start is allowed, but any true overlap is rejected with `ERR_SUBCONTRACTOR_DOUBLE_BOOKED`. Second, the site has an aggregate capacity of one crew at a time: the interval must not overlap any other non-`CANCELLED` booking on the *same* `pool_project_id`, else `ERR_SITE_OCCUPIED`, under the same half-open, adjacency-allowed rule. Third, a curing buffer protects fresh gunite: a booking for a gate in the `PLASTER` phase must start at least 24 hours after the `end_at` of any non-`CANCELLED` booking for a `GUNITE`-phase gate on the same site; a plaster crew that would start sooner is rejected with `ERR_CURE_BUFFER`.

A subcontractor completes its own booking, moving `SCHEDULED` to `COMPLETED`. Completion is restricted to the owning sub — `X-User-ID` must equal the booking's `subcontractor_id` — and it requires the referenced phase gate to be actively under way, meaning the gate's status is `IN_PROGRESS` or `INSPECTION_PENDING`; a completion against a gate in any other status is rejected with `ERR_PHASE_NOT_ACTIVE`. A booking may instead be cancelled, moving `SCHEDULED` to `CANCELLED`; cancellation may be performed by the owning subcontractor or by the `BuilderPM`. The `COMPLETED` and `CANCELLED` states are terminal.

A subcontractor's `committed_crew_hours` is the sum of `duration_hours` over that sub's bookings whose status is `SCHEDULED` or `COMPLETED`. Creating a booking adds exactly that booking's `duration_hours` to the total; cancelling a booking subtracts exactly the same `duration_hours` back out, so that a create-then-cancel pair leaves `committed_crew_hours` unchanged. The running total is carried in hours to two decimal places, rounded half-up.

Each sub also exposes two reliability scores, both whole integers from 0 to 100, recomputed when a booking is completed or cancelled and when an inspection is recorded. The forward-looking `reliability_projected` looks across the sub's bookings whose status is `SCHEDULED` or `COMPLETED`: let the denominator be the count of those bookings and the numerator be the count of them whose referenced phase gate is *not* `FAILED`. If the denominator is zero the score defaults to 100; otherwise it is 100 multiplied by the numerator divided by the denominator, rounded half-up. The backward-looking `reliability_realized` looks only across the sub's `COMPLETED` bookings: let the denominator be the count of `COMPLETED` bookings and the numerator be the count of them whose referenced phase gate is `PASSED` *and* whose `inspection_attempts` equals exactly 1 (that is, the gate passed on its first inspection with no rework). If the denominator is zero the score defaults to 100; otherwise it is 100 multiplied by the numerator divided by the denominator, rounded half-up. The two scores diverge whenever a gate passed only after rework, or is still open, because such a gate counts as good for the projected score but not for the realized one.

### 3.6. Change Orders, Equipment Selection, and Volume Discounts

Equipment and feature selections and scope changes are handled as `ChangeOrder` records, proposed by the `BuilderPM`. A proposal supplies the `pool_project_id`, a `category` — one of `PUMP`, `HEATER`, `LIGHTING`, `WATER_FEATURE`, `CLEANER`, or `SCOPE` — a `description` of what the change adds or removes, and a signed pre-discount `price_delta_cents` that may be positive (an upgrade) or negative (a credit). A change may optionally name a `phase` — one of `EXCAVATION`, `STEEL`, `PLUMBING`, `GUNITE`, or `PLASTER` — whose gate `budget_cents` the change adjusts. A new change order's `status` is `PROPOSED` and its `applied_delta_cents` is 0.

The homeowner decides a proposal, either approving it (`PROPOSED` to `APPROVED`) or rejecting it (`PROPOSED` to `REJECTED`, terminal). The builder then applies an approved change, moving `APPROVED` to `APPLIED`; applying a change whose status is not `APPROVED` is rejected with `ERR_CHANGE_ORDER_NOT_APPROVED`. An applied change may later be reversed, moving `APPLIED` to the terminal `REVERSED`.

Applying a change computes its `applied_delta_cents` under a volume-discount schedule whose evaluation order is fixed to resolve the apparent circularity (the contract amount depends on the applied delta, which depends on a discount tier keyed on the contract's cumulative change value). The steps are: first, compute the cumulative pre-discount base as the sum of `price_delta_cents` over the project's *already*-`APPLIED` change orders whose `price_delta_cents` is greater than zero, excluding this change order itself. Second, read the discount tier from that cumulative base *before* adding this change: if the cumulative base is below 500,000 cents the discount is 0%; if it is at least 500,000 cents but below 1,500,000 cents the discount is 3%; if it is 1,500,000 cents or more the discount is 5%. Third, set the applied delta: when this change's `price_delta_cents` is greater than zero, `applied_delta_cents` is `price_delta_cents` multiplied by one minus the discount rate, rounded half-up to whole cents; when `price_delta_cents` is zero or negative (a credit), no discount applies and `applied_delta_cents` equals `price_delta_cents` unchanged. Fourth, the project's `contract_amount_cents` increases by `applied_delta_cents`, and if the change names a `phase`, that gate's `budget_cents` increases by the same `applied_delta_cents`. The project's `amount_remaining_cents` is recomputed, the project posture is re-derived (a positive delta can lift a stop-work that arose from a negative balance), and the project `version` is incremented by 1.

Reversing an applied change undoes exactly what was posted. The project's `contract_amount_cents` decreases by the same `applied_delta_cents` that was posted at apply time, and if the change named a `phase`, that gate's `budget_cents` decreases by the same amount. The project's `amount_remaining_cents` is recomputed, its posture is re-derived, and its `version` is incremented by 1. Across all applied change orders, the project's `contract_amount_cents` always equals the original signed `contract_price_cents` plus the sum of `applied_delta_cents` over every change currently in `APPLIED` status.

### 3.7. Progress Draws, Retainage, and Disbursement

The builder bills the homeowner phase by phase through `DrawRequest` records. Creating a draw supplies the `pool_project_id`, the `phase_gate_id` the draw bills against, the `requested_cents` amount (greater than zero), and the `expected_pool_project_version` required by the optimistic-concurrency rule of §2.5. Creating a draw is a field operation blocked by a `STOP_WORK` posture (with `ERR_POSTURE_STOP_WORK`) but not by a `HOLD` posture. On creation the draw's `status` is `REQUESTED`, its forward-looking `provisional_eligible_cents` is snapshotted (see below), and the project's `version` is incremented by 1.

Eligibility is computed from the referenced gate's budget and a completion factor keyed on the gate's status: a `PENDING` gate earns a factor of 0.0, an `IN_PROGRESS` gate 0.5, an `INSPECTION_PENDING` gate 0.8, a `PASSED` gate 1.0, and a `FAILED` gate 0.0. The phase-earned amount is the gate's `budget_cents` multiplied by that factor, rounded half-up to whole cents. The eligible amount is then the phase-earned amount but never below zero and never above `requested_cents` — that is, it is the smaller of phase-earned and `requested_cents`, floored at zero. At draw creation this is snapshotted forward-looking into `provisional_eligible_cents`, so a gate that is only `IN_PROGRESS` or `INSPECTION_PENDING` still yields a positive provisional amount (half or four-fifths of its budget). Importantly, the eligible amount is *not* capped at the contract's remaining balance here; the contract ceiling is enforced only as a separate fiscal check at funding time.

The homeowner decides the draw, either approving it (`REQUESTED` to `APPROVED`) or rejecting it (`REQUESTED` to `REJECTED`, terminal). The builder then funds an approved draw, moving `APPROVED` to `FUNDED`. Funding runs three checks in order: the draw must be in `APPROVED` status, else `ERR_INVALID_STATE`; the referenced gate must be `PASSED`, else `ERR_PHASE_NOT_PASSED`; and the resulting net disbursement must not exceed the project's `amount_remaining_cents`, else `ERR_DRAW_EXCEEDS_CONTRACT`, which is checked last. At funding the eligibility is recomputed in its final form: because the gate must be `PASSED`, its completion factor is 1.0 and the final `eligible_cents` therefore equals the gate's `budget_cents` (still capped at `requested_cents` and floored at zero) — which differs from `provisional_eligible_cents` whenever the draw had been created before the gate passed.

Funding then withholds retainage. The draw's `retainage_cents` is 10% of its `eligible_cents`, rounded half-up to whole cents on that single draw line, and its `net_disbursed_cents` is `eligible_cents` minus `retainage_cents` — the cash actually paid to the builder at funding. Both `eligible_cents`, `retainage_cents`, and `net_disbursed_cents` are 0 until the draw is funded, and the draw's `retainage_released` flag is false until release at startup. When the draw funds, the project's `amount_disbursed_cents` increases by this draw's `net_disbursed_cents`, its `retainage_held_cents` increases by this draw's `retainage_cents`, `amount_remaining_cents` is recomputed, the posture is re-derived, and the project `version` is incremented by 1.

The project ledger is derived from the whole draw and change history taken together. `contract_amount_cents` is the base `contract_price_cents` plus the sum of `applied_delta_cents` over applied change orders. `retainage_held_cents` is the sum of the individually-rounded `retainage_cents` over all funded draws whose `retainage_released` is still false — and the per-line rounding matters: each draw's retainage is rounded to whole cents first and only then summed, never summed and rounded once, because the two orders can differ by a cent when several draws round the same way. `amount_disbursed_cents` is the sum of `net_disbursed_cents` over all funded draws, plus the sum of `retainage_cents` over funded draws whose retainage has since been released. `amount_remaining_cents` is `contract_amount_cents` minus `amount_disbursed_cents` minus `retainage_held_cents`.

### 3.8. Startup, Owner Orientation, and Warranty Closeout

When the `PLASTER` gate passes and, with it, every one of the project's five gates is `PASSED`, the system carries the project's `construction_status` from `IN_CONSTRUCTION` to `STARTUP_READY` and recomputes `current_phase` to `STARTUP`. Reaching startup releases retainage: every funded draw whose `retainage_released` is still false has that flag set to true, and the project's held retainage is disbursed — the entire `retainage_held_cents` balance is moved into `amount_disbursed_cents` so that `retainage_held_cents` becomes 0. The `pool_gallons` captured at intake informs the startup chemical dosing performed during this phase.

With the pool started up, the `BuilderPM` records the owner orientation and handoff, advancing `construction_status` from `STARTUP_READY` to `ORIENTED`; attempting this orientation while the project is not in `STARTUP_READY` is rejected with `ERR_NOT_STARTUP_READY`.

Warranty and punch work is tracked as `PunchItem` records, filed by either an `Inspector` or the `Owner`. A punch item supplies the `pool_project_id`, a `description` of the defect, and a `severity` of `MINOR`, `MAJOR`, or `SAFETY`. A new item's `status` is `OPEN`. Filing a `SAFETY` item recomputes the project posture and drives it to `STOP_WORK`; filing a `MAJOR` item recomputes the posture and drives it to `HOLD` unless a stop-work condition already dominates; a `MINOR` item never changes posture. An open item is closed by the builder or the owner resolving it (`OPEN` to `RESOLVED`) or by the owner waiving it (`OPEN` to `WAIVED`); both `RESOLVED` and `WAIVED` are terminal. When the item being closed is of `SAFETY` or `MAJOR` severity, closing it recomputes the project posture, so that clearing the last blocking defect can lift a `STOP_WORK` or `HOLD`.

The homeowner finally accepts the pool, advancing `construction_status` from `ORIENTED` to the terminal `CLOSED`. Closing requires the project to be in `ORIENTED` — an attempt from any other state is rejected with `ERR_INVALID_STATE` — and it requires that the count of `OPEN` punch items on the project is exactly zero; if any punch item remains open the close is rejected with `ERR_OPEN_PUNCH_ITEMS`.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; reads, list retrievals, and state-changing transitions return HTTP 200 with the affected resource (the logical-clock utility returns 200 with an empty data object). The complete request and response semantics for each route are given by the §3 narratives above; this table lists only the method, path, purpose, and authorized roles. "All roles" means `BuilderPM`, `Designer`, `Owner`, `Inspector`, and `Subcontractor`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/pool-build/pool-projects` | Create a pool project; initialize the ledger and lifecycle | BuilderPM |
| GET | `/pool-build/pool-projects/{id}` | Read a pool project with all computed fields | All roles |
| POST | `/pool-build/pool-projects/{id}/transition` | Orient (STARTUP_READY→ORIENTED) or close (ORIENTED→CLOSED) | BuilderPM, Owner |
| POST | `/pool-build/design-plans` | Create the project's single design plan | Designer |
| GET | `/pool-build/design-plans/{id}` | Read a design plan | All roles |
| GET | `/pool-build/design-plans` | List design plans, optionally filtered by project | All roles |
| POST | `/pool-build/design-plans/{id}/transition` | Design/permit workflow (render, approve, revise, submit/issue/reject permit) | Designer, Owner, Inspector |
| POST | `/pool-build/phase-gates` | Create a construction phase gate | BuilderPM |
| GET | `/pool-build/phase-gates/{id}` | Read a phase gate | All roles |
| GET | `/pool-build/phase-gates` | List phase gates, optionally filtered by project | All roles |
| POST | `/pool-build/phase-gates/{id}/start` | Start or rework a phase | BuilderPM |
| POST | `/pool-build/inspections` | Schedule an inspection milestone for a phase | Inspector |
| GET | `/pool-build/inspections/{id}` | Read an inspection | All roles |
| GET | `/pool-build/inspections` | List inspections, optionally filtered by project and/or phase | All roles |
| POST | `/pool-build/inspections/{id}/record` | Record a pass, fail, or cancel outcome | Inspector |
| POST | `/pool-build/subcontractors` | Register a subcontractor | BuilderPM |
| GET | `/pool-build/subcontractors/{id}` | Read a subcontractor with committed hours and reliability | All roles |
| POST | `/pool-build/subcontractors/{id}/transition` | Suspend or reactivate a subcontractor | BuilderPM |
| POST | `/pool-build/crew-assignments` | Book a crew to a phase for an interval | BuilderPM |
| GET | `/pool-build/crew-assignments/{id}` | Read a crew assignment | All roles |
| GET | `/pool-build/crew-assignments` | List crew assignments, optionally filtered by project, sub, and/or phase | All roles |
| POST | `/pool-build/crew-assignments/{id}/transition` | Complete or cancel a crew assignment | Subcontractor, BuilderPM |
| POST | `/pool-build/change-orders` | Propose a change order | BuilderPM |
| GET | `/pool-build/change-orders/{id}` | Read a change order | All roles |
| GET | `/pool-build/change-orders` | List change orders, optionally filtered by project | All roles |
| POST | `/pool-build/change-orders/{id}/transition` | Approve, reject, apply, or reverse a change order | Owner, BuilderPM |
| POST | `/pool-build/draw-requests` | Create a progress draw (requires project-version OCC) | BuilderPM |
| GET | `/pool-build/draw-requests/{id}` | Read a draw request | All roles |
| GET | `/pool-build/draw-requests` | List draw requests, optionally filtered by project and/or phase | All roles |
| POST | `/pool-build/draw-requests/{id}/transition` | Approve, reject, or fund a draw | Owner, BuilderPM |
| POST | `/pool-build/punch-items` | File a warranty/punch item | Inspector, Owner |
| GET | `/pool-build/punch-items/{id}` | Read a punch item | All roles |
| GET | `/pool-build/punch-items` | List punch items, optionally filtered by project | All roles |
| POST | `/pool-build/punch-items/{id}/resolve` | Resolve or waive a punch item | BuilderPM, Owner |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | BuilderPM |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_PROJECT_VERSION | 412 |
| ERR_POSTURE_STOP_WORK | 409 |
| ERR_POSTURE_HOLD | 409 |
| ERR_DESIGN_ALREADY_EXISTS | 409 |
| ERR_DESIGN_NOT_APPROVED | 409 |
| ERR_PERMIT_NOT_ISSUED | 409 |
| ERR_PHASE_ALREADY_EXISTS | 409 |
| ERR_PHASE_SEQUENCE | 409 |
| ERR_PHASE_NOT_IN_PROGRESS | 409 |
| ERR_PHASE_NOT_ACTIVE | 409 |
| ERR_PHASE_NOT_PASSED | 409 |
| ERR_SUBCONTRACTOR_DOUBLE_BOOKED | 409 |
| ERR_SITE_OCCUPIED | 409 |
| ERR_CURE_BUFFER | 409 |
| ERR_SUBCONTRACTOR_INACTIVE | 409 |
| ERR_CHANGE_ORDER_NOT_APPROVED | 409 |
| ERR_DRAW_EXCEEDS_CONTRACT | 409 |
| ERR_OPEN_PUNCH_ITEMS | 409 |
| ERR_NOT_STARTUP_READY | 409 |
